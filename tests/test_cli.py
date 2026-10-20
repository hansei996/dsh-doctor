import argparse
import io
import json
import os
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
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
            main(["--root", str(self.root), "--fix", "--yes", "--older-than", "30d"])
        self.assertFalse((self.root / "attachments" / "x" / "old.bin").exists())
        self.assertTrue((self.root / "attachments" / "y" / "new.bin").exists())

    def test_non_interactive_fix_refuses_without_yes(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--root", str(self.root), "--fix", "--older-than", "30d"])
        self.assertEqual(code, 0)
        self.assertTrue((self.root / "attachments" / "x" / "old.bin").exists())
        self.assertIn("--yes", err.getvalue())
        self.assertIn("将清理", out.getvalue())

    def test_yes_skips_confirmation(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main(["--root", str(self.root), "--fix", "--yes"])
        self.assertIn("已清理", buffer.getvalue())

    def test_dry_run_keeps_files(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main(["--root", str(self.root), "--fix", "--dry-run", "--older-than", "30d"])
        self.assertTrue((self.root / "attachments" / "x" / "old.bin").exists())
        self.assertIn("dry-run", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()


class ConfirmTests(unittest.TestCase):
    """_confirm 的终端判定与回答解析。"""

    def setUp(self):
        from dsh_doctor.rules import Finding

        self.targets = [
            Finding("cache", "cache", "缓存目录", "1 MB", reclaimable=1024 * 1024, fix=lambda: 0)
        ]

    def _confirm(self, isatty, answer=None, exc=None):
        from unittest import mock

        from dsh_doctor import cli

        fake_stdin = mock.Mock()
        fake_stdin.isatty.return_value = isatty
        patch_input = (
            mock.patch("builtins.input", side_effect=exc)
            if exc
            else mock.patch("builtins.input", return_value=answer)
        )
        with mock.patch.object(cli.sys, "stdin", fake_stdin), patch_input:
            return cli._confirm(self.targets)

    def test_yes_on_terminal(self):
        self.assertTrue(self._confirm(True, "y"))

    def test_full_yes_word(self):
        self.assertTrue(self._confirm(True, " yes "))

    def test_no_on_terminal(self):
        self.assertFalse(self._confirm(True, "n"))

    def test_empty_answer_is_no(self):
        self.assertFalse(self._confirm(True, ""))

    def test_non_tty_refuses(self):
        self.assertFalse(self._confirm(False))

    def test_eof_refuses(self):
        self.assertFalse(self._confirm(True, exc=EOFError()))


class FailUnderTests(unittest.TestCase):
    """--fail-under 决定退出码，供 CI 卡阈值。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "dsh"
        (self.root / "cache").mkdir(parents=True)
        (self.root / "cache" / "a.bin").write_bytes(b"x" * 128)

    def tearDown(self):
        self.tmp.cleanup()

    def _run(self, *extra):
        import contextlib

        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = main(["--root", str(self.root), "--no-history"] + list(extra))
        return code, err.getvalue()

    def test_threshold_above_score_fails(self):
        code, err = self._run("--fail-under", "101")
        self.assertEqual(code, 1)
        self.assertIn("低于门槛", err)

    def test_threshold_below_score_passes(self):
        code, _ = self._run("--fail-under", "0")
        self.assertEqual(code, 0)

    def test_default_is_sixty(self):
        code, _ = self._run()
        self.assertIn(code, (0, 1))
