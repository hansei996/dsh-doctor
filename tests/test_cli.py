import argparse
import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from dsh_doctor.cli import main, parse_older_than


def touch(path: Path, size: int, age_days: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    stamp = time.time() - age_days * 86400
    os.utime(str(path), (stamp, stamp))


class ParseOlderThanTests(unittest.TestCase):
    def test_accepts_day_suffix(self):
        self.assertEqual(parse_older_than("30d"), 30)
        self.assertEqual(parse_older_than("7D"), 7)

    def test_accepts_bare_integer(self):
        self.assertEqual(parse_older_than("30"), 30)

    def test_rejects_invalid_values(self):
        for bad in ("0d", "-3d", "abc", "", "1.5d"):
            with self.assertRaises(argparse.ArgumentTypeError):
                parse_older_than(bad)


class CliIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        touch(self.root / "attachments" / "x" / "old.bin", 100, 45)
        touch(self.root / "attachments" / "y" / "new.bin", 20, 2)
        touch(self.root / "cache" / "c.bin", 30, 1)

    def tearDown(self):
        self.tmp.cleanup()

    def test_older_than_appears_in_json_report(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main(["--root", str(self.root), "--format", "json", "--older-than", "30d"])
        payload = json.loads(buffer.getvalue())
        keys = {item["key"]: item for item in payload["findings"]}
        self.assertIn("attachments_old", keys)
        self.assertEqual(keys["attachments_old"]["reclaimable"], 100)

    def test_without_flag_no_attachment_rule(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main(["--root", str(self.root), "--format", "json"])
        keys = {item["key"] for item in json.loads(buffer.getvalue())["findings"]}
        self.assertNotIn("attachments_old", keys)

    def test_fix_older_than_removes_only_expired(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main(["--root", str(self.root), "--fix", "--older-than", "30d"])
        self.assertFalse((self.root / "attachments" / "x" / "old.bin").exists())
        self.assertTrue((self.root / "attachments" / "y" / "new.bin").exists())

    def test_dry_run_keeps_files(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main(["--root", str(self.root), "--fix", "--dry-run", "--older-than", "30d"])
        self.assertTrue((self.root / "attachments" / "x" / "old.bin").exists())
        self.assertIn("dry-run", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
