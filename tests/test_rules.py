import tempfile
import unittest
from pathlib import Path

from dsh_doctor import rules
from dsh_doctor.rules import PROBLEM, WARN, build_findings, grade, reclaimable, score
from dsh_doctor.scanner import Backup, DirStat, Scan


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


if __name__ == "__main__":
    unittest.main()
