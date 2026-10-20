import os
import tempfile
import unittest
from pathlib import Path

from dsh_doctor.scanner import collect_files, dir_size, human, scan


def make_file(path: Path, size: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


class HumanTests(unittest.TestCase):
    def test_units(self):
        self.assertEqual(human(0), "0 B")
        self.assertEqual(human(512), "512 B")
        self.assertEqual(human(2048), "2.0 KB")
        self.assertEqual(human(5 * 1024 ** 2), "5.0 MB")


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        make_file(self.root / "cache" / "a.bin", 1000)
        make_file(self.root / "cache" / "nested" / "b.bin", 500)
        make_file(self.root / "sessions" / "s1" / "log.jsonl", 2000)
        make_file(self.root / "sessions" / "s2" / "log.jsonl", 500)
        make_file(self.root / "backups" / "old" / "f", 300)
        make_file(self.root / "backups" / "new" / "f", 100)
        runtime = self.root / "dsh-runtimes" / "dsh-primary-runtime"
        runtime.mkdir(parents=True)
        (runtime / "runtime.json").write_text(
            '{"desktopVersion": "0.2.1-rc.2"}', encoding="utf-8"
        )
        (self.root / "extensions" / "ext-a").mkdir(parents=True)
        (self.root / "plugins" / "p1").mkdir(parents=True)
        cred = self.root / ".credentials.yaml"
        cred.write_text("refs:\n  GITHUB_TOKEN: abc\n")
        os.chmod(str(cred), 0o600)

    def tearDown(self):
        self.tmp.cleanup()

    def test_dir_size_sums_nested_files(self):
        size, files = dir_size(self.root / "cache")
        self.assertEqual(size, 1500)
        self.assertEqual(files, 2)

    def test_scan_collects_sections(self):
        result = scan(self.root)
        self.assertEqual(result.dir("cache").size, 1500)
        self.assertEqual(result.session_count, 2)
        self.assertEqual(result.largest_session[0], "s1")
        self.assertEqual(result.runtime_versions, ["dsh-primary-runtime"])
        self.assertEqual(result.runtime_meta_versions, ["0.2.1-rc.2"])
        self.assertEqual(result.extension_count, 1)
        self.assertEqual(result.plugin_count, 1)
        self.assertEqual(result.credential_mode, 0o600)

    def test_scan_tolerates_missing_root(self):
        result = scan(self.root / "nope")
        self.assertEqual(result.total_size, 0)
        self.assertEqual(result.dirs, [])


class AttachmentCollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        make_file(self.root / "attachments" / "v1" / "a.webp", 120)
        make_file(self.root / "attachments" / "v1" / "deep" / "b.png", 80)
        make_file(self.root / "attachments" / "c.txt", 40)

    def tearDown(self):
        self.tmp.cleanup()

    def test_scan_collects_attachment_files_with_mtime(self):
        result = scan(self.root)
        sizes = sorted(item.size for item in result.attachment_files)
        self.assertEqual(sizes, [40, 80, 120])
        for item in result.attachment_files:
            self.assertGreater(item.mtime, 0)
            self.assertTrue(item.path.is_file())

    def test_collect_files_is_read_only(self):
        before = sorted(p.name for p in (self.root / "attachments").rglob("*"))
        collect_files(self.root / "attachments")
        after = sorted(p.name for p in (self.root / "attachments").rglob("*"))
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()


class PermissionRobustnessTests(unittest.TestCase):
    """无权限目录不能让体检崩掉。"""

    def setUp(self):
        if os.geteuid() == 0:
            self.skipTest("root 不受权限位限制")
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "dsh"
        locked = self.root / "profiles" / "locked"
        locked.mkdir(parents=True)
        (locked / "secret.bin").write_bytes(b"x" * 100)
        (self.root / "cache").mkdir(parents=True)
        (self.root / "cache" / "ok.bin").write_bytes(b"x" * 10)
        os.chmod(str(locked), 0o000)
        self.locked = locked

    def tearDown(self):
        os.chmod(str(self.locked), 0o755)
        self.tmp.cleanup()

    def test_scan_survives_unreadable_dir(self):
        result = scan(self.root)
        self.assertEqual(len(result.skipped_dirs), 1)
        self.assertIn("locked", result.skipped_dirs[0])
        self.assertTrue(result.dir("cache"))

    def test_finding_reports_skipped_dirs(self):
        from dsh_doctor.rules import WARN, build_findings

        findings = {f.key: f for f in build_findings(scan(self.root))}
        self.assertIn("skipped", findings)
        self.assertEqual(findings["skipped"].level, WARN)
        self.assertIn("1", findings["skipped"].detail)
