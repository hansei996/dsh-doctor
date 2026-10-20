import os
import tempfile
import time
import unittest
from pathlib import Path

from dsh_doctor import rules
from dsh_doctor.rules import (
    OK,
    PROBLEM,
    WARN,
    _delete_attachments,
    _is_expired,
    build_findings,
    grade,
    reclaimable,
    score,
)
from dsh_doctor.scanner import AttachmentFile, Backup, DirStat, Scan


ROOT = Path(tempfile.mkdtemp(prefix="dsh-doctor-test-"))


def base_scan(**overrides):
    scan = Scan(root=ROOT)
    scan.dirs = [
        DirStat("cache", 80 * 1024 * 1024, 10),
        DirStat("backups", 1000, 3),
        DirStat("attachments", 10 * 1024, 1),
        DirStat("dsh-runtimes", 400 * 1024 * 1024, 50),
    ]
    scan.credentials = ROOT / ".credentials.yaml"
    scan.credential_mode = 0o600
    scan.backups = [
        Backup("b3", 400, 300),
        Backup("b2", 300, 200),
        Backup("b1", 300, 100),
    ]
    scan.session_count = 2
    scan.largest_session = ("s1", 2048)
    scan.disk_free = 100 * 1024 ** 3
    scan.disk_total = 500 * 1024 ** 3
    for key, value in overrides.items():
        setattr(scan, key, value)
    return scan


class FindingTests(unittest.TestCase):
    def test_cache_is_fixable(self):
        findings = {f.key: f for f in build_findings(base_scan())}
        self.assertTrue(findings["cache"].fixable)
        self.assertEqual(findings["cache"].reclaimable, 80 * 1024 * 1024)
        self.assertEqual(findings["cache"].level, WARN)

    def test_only_old_backups_are_reclaimable(self):
        findings = {f.key: f for f in build_findings(base_scan())}
        self.assertEqual(findings["backups"].reclaimable, 300)

    def test_missing_credentials_is_a_problem(self):
        findings = {f.key: f for f in build_findings(base_scan(credentials=None))}
        self.assertEqual(findings["credentials"].level, PROBLEM)
        baseline = score(build_findings(base_scan()))
        self.assertEqual(baseline - score(list(findings.values())), 20)

    def test_loose_permissions_warn(self):
        findings = {f.key: f for f in build_findings(base_scan(credential_mode=0o644))}
        self.assertEqual(findings["credentials"].level, WARN)

    def test_low_disk_warns(self):
        findings = {f.key: f for f in build_findings(base_scan(disk_free=1024))}
        self.assertEqual(findings["disk"].level, WARN)

    def test_reclaimable_only_counts_fixable(self):
        findings = build_findings(base_scan())
        self.assertEqual(reclaimable(findings), 80 * 1024 * 1024 + 300)

    def test_score_and_grade(self):
        findings = build_findings(base_scan())
        value = score(findings)
        self.assertLessEqual(value, 100)
        self.assertIn(grade(value), ("A", "B", "C", "D", "F"))

    def test_missing_root_short_circuits(self):
        findings = build_findings(Scan(root=Path("/tmp/definitely-not-here")))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].level, PROBLEM)


class FixTests(unittest.TestCase):
    def test_clear_dir_empties_but_keeps_dir(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "cache"
            (root / "sub").mkdir(parents=True)
            (root / "sub" / "f.bin").write_bytes(b"x" * 100)
            (root / "g.bin").write_bytes(b"x" * 50)
            freed = rules._clear_dir(root)
            self.assertEqual(freed, 150)
            self.assertTrue(root.is_dir())
            self.assertEqual(list(root.iterdir()), [])

    def test_delete_backups_keeps_newest_two(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backups = []
            for name, mtime, size in (("new", 3, 10), ("mid", 2, 20), ("old", 1, 30)):
                path = root / "backups" / name
                path.mkdir(parents=True)
                (path / "f").write_bytes(b"x" * size)
                backups.append(Backup(name, size, mtime))
            backups.sort(key=lambda b: b.mtime, reverse=True)
            freed = rules._delete_backups(root, backups)
            self.assertEqual(freed, 30)
            remaining = sorted(p.name for p in (root / "backups").iterdir())
            self.assertEqual(remaining, ["mid", "new"])


class VersionFindingTests(unittest.TestCase):
    def findings(self, **overrides):
        return {f.key: f for f in build_findings(base_scan(**overrides))}

    def test_consistent_version_is_ok(self):
        finding = self.findings(app_version="0.4.1", runtime_versions=["v0.4.7"])["version"]
        self.assertEqual(finding.level, rules.OK)

    def test_mismatch_is_warn(self):
        finding = self.findings(app_version="0.5.0", runtime_versions=["0.4.2"])["version"]
        self.assertEqual(finding.level, WARN)
        self.assertIn("0.5", finding.detail)

    def test_missing_app_degrades_to_ok(self):
        finding = self.findings(app_version=None, runtime_versions=["0.4.2"])["version"]
        self.assertEqual(finding.level, rules.OK)
        self.assertIn("未找到", finding.detail)

    def test_unversioned_runtime_degrades_to_ok(self):
        finding = self.findings(app_version="0.2.1", runtime_versions=["dsh-primary-runtime"])["version"]
        self.assertEqual(finding.level, rules.OK)
        self.assertIn("不含版本号", finding.detail)

    def test_unknown_version_does_not_change_score(self):
        baseline = score(build_findings(base_scan()))
        with_unknown = score(build_findings(base_scan(app_version=None, runtime_versions=[])))
        self.assertEqual(baseline, with_unknown)
def make_attachment(path: Path, size: int, age_days: float) -> AttachmentFile:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    stamp = time.time() - age_days * 86400
    os.utime(str(path), (stamp, stamp))
    return AttachmentFile(path, size, path.stat().st_mtime)


class OlderThanTests(unittest.TestCase):
    def test_boundary_is_inclusive(self):
        now = 1_000_000_000.0
        self.assertTrue(_is_expired(now - 30 * 86400, 30, now))
        self.assertFalse(_is_expired(now - 30 * 86400 + 1, 30, now))

    def test_default_call_has_no_extra_finding(self):
        keys = [f.key for f in build_findings(base_scan())]
        self.assertNotIn("attachments_old", keys)

    def test_expired_files_are_reclaimable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = make_attachment(root / "attachments" / "x" / "old.bin", 100, 40)
            fresh = make_attachment(root / "attachments" / "y" / "new.bin", 50, 10)
            scan = base_scan()
            scan.root = root
            scan.attachment_files = [old, fresh]

            findings = {f.key: f for f in build_findings(scan, older_than_days=30)}
            finding = findings["attachments_old"]
            self.assertEqual(finding.reclaimable, 100)
            self.assertTrue(finding.fixable)
            self.assertEqual(finding.level, WARN)
            self.assertIn("30", finding.detail)

    def test_all_fresh_is_not_fixable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fresh = make_attachment(root / "attachments" / "new.bin", 50, 3)
            scan = base_scan()
            scan.root = root
            scan.attachment_files = [fresh]

            findings = {f.key: f for f in build_findings(scan, older_than_days=30)}
            finding = findings["attachments_old"]
            self.assertEqual(finding.level, OK)
            self.assertEqual(finding.reclaimable, 0)
            self.assertFalse(finding.fixable)

    def test_fix_deletes_only_expired_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            old = make_attachment(root / "attachments" / "x" / "old.bin", 100, 40)
            fresh = make_attachment(root / "attachments" / "y" / "new.bin", 50, 10)
            scan = base_scan()
            scan.root = root
            scan.attachment_files = [old, fresh]

            finding = {f.key: f for f in build_findings(scan, older_than_days=30)}["attachments_old"]
            freed = finding.fix()

            self.assertEqual(freed, 100)
            self.assertFalse(old.path.exists(), "超期文件应被删除")
            self.assertTrue(fresh.path.exists(), "未超期的文件必须还在")
            self.assertTrue((root / "attachments" / "x").is_dir(), "目录保留，避免影响会话引用")

    def test_delete_attachments_tolerates_missing_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            gone = AttachmentFile(Path(tmp) / "nope.bin", 10, time.time())
            self.assertEqual(_delete_attachments([gone]), 0)


if __name__ == "__main__":
    unittest.main()
