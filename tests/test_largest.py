import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from dsh_doctor import cli
from dsh_doctor.rules import build_findings, score
from dsh_doctor.report import to_json, to_markdown, to_table
from dsh_doctor.scanner import TOP_FILES_LIMIT, Scan, scan


class ScannerLargestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name, size in (("big", 3000), ("mid", 2000), ("small", 1000)):
            sub = self.root / "cache" / name
            sub.parent.mkdir(parents=True, exist_ok=True)
            (sub).write_bytes(b"x" * size)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sorted_desc(self):
        result = scan(self.root)
        sizes = [size for _, size in result.largest_files]
        self.assertEqual(sizes, sorted(sizes, reverse=True))
        self.assertEqual(sizes[:3], [3000, 2000, 1000])

    def test_paths_are_absolute(self):
        result = scan(self.root)
        for path, _ in result.largest_files:
            self.assertTrue(str(path).startswith(str(self.root)))

    def test_heap_limit(self):
        result = scan(self.root)
        self.assertLessEqual(len(result.largest_files), TOP_FILES_LIMIT)


class ReportLargestTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        scan_result = Scan(root=self.root)
        scan_result.largest_files = [
            (self.root / "a" / "big.bin", 5 * 1024 * 1024),
            (self.root / "a" / "small.bin", 1024),
        ]
        self.scan = scan_result
        self.findings = build_findings(self.scan)
        self.value = score(self.findings)

    def tearDown(self):
        self.tmp.cleanup()

    def test_table_shows_top_section_with_relative_paths(self):
        text = to_table(self.scan, self.findings, self.value)
        self.assertIn("空间 Top 2", text)
        self.assertIn("a/big.bin", text)
        self.assertIn("5.0 MB", text)
        self.assertNotIn(str(self.root / "a" / "big.bin"), text)

    def test_markdown_lists_files(self):
        text = to_markdown(self.scan, self.findings, self.value)
        self.assertIn("**空间 Top 2**", text)
        self.assertIn("`a/big.bin` — 5.0 MB", text)

    def test_json_has_largest_files(self):
        payload = json.loads(to_json(self.scan, self.findings, self.value))
        self.assertEqual(len(payload["largest_files"]), 2)
        self.assertEqual(payload["largest_files"][0]["size"], 5 * 1024 * 1024)
        self.assertFalse(payload["largest_files"][0]["path"].startswith("/"))

    def test_no_files_no_section(self):
        empty = Scan(root=self.root)
        text = to_table(empty, self.findings, self.value)
        self.assertNotIn("空间 Top", text)


class CliTopTests(unittest.TestCase):
    def test_top_zero_hides_section(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsh"
            (root / "cache").mkdir(parents=True)
            (root / "cache" / "a.bin").write_bytes(b"x" * 500)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["--root", str(root), "--top", "0", "--no-history"])
            self.assertNotIn("空间 Top", out.getvalue())

    def test_top_limits_entries(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsh"
            (root / "cache").mkdir(parents=True)
            for i in range(4):
                (root / "cache" / ("f%d.bin" % i)).write_bytes(b"x" * (100 * (i + 1)))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                cli.main(["--root", str(root), "--top", "2", "--no-history"])
            text = out.getvalue()
            self.assertIn("空间 Top 2", text)
            self.assertEqual(text.count("cache/f"), 2)


if __name__ == "__main__":
    unittest.main()
