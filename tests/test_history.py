import json
import os
import tempfile
import unittest
from pathlib import Path

from dsh_doctor import history
from dsh_doctor.history import Point, append, default_path, describe, load, make_point, previous, trend
from dsh_doctor.scanner import DirStat, Scan


def scan_with(dirs, total=None):
    scan = Scan(root=Path("/tmp/x"))
    scan.dirs = [DirStat(name, size, 1) for name, size in dirs]
    return scan


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "sub" / "history.jsonl"

    def tearDown(self):
        self.tmp.cleanup()

    def test_append_creates_parent_and_roundtrips(self):
        point = Point(ts=100.0, total=1234, reclaimable=10, dirs={"cache": 100})
        append(self.path, point)
        loaded = load(self.path)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0].total, 1234)
        self.assertEqual(loaded[0].dirs, {"cache": 100})

    def test_append_trims_to_max_points(self):
        for i in range(5):
            append(self.path, Point(ts=float(i), total=i), max_points=3)
        loaded = load(self.path)
        self.assertEqual([p.total for p in loaded], [2, 3, 4])

    def test_broken_lines_are_skipped(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            '{"ts": 1, "total": 10}\nnot json\n\n{"ts": 2}\n{"ts": 3, "total": 30}\n',
            encoding="utf-8",
        )
        loaded = load(self.path)
        self.assertEqual([p.total for p in loaded], [10, 30])

    def test_missing_file_returns_empty(self):
        self.assertEqual(load(self.path), [])

    def test_env_override_for_default_path(self):
        with unittest.mock.patch.dict(os.environ, {history.HISTORY_ENV: "/tmp/custom.jsonl"}):
            self.assertEqual(default_path(), Path("/tmp/custom.jsonl"))


class QueryTests(unittest.TestCase):
    def test_previous_picks_latest_earlier(self):
        points = [Point(ts=1, total=1), Point(ts=5, total=5), Point(ts=9, total=9)]
        self.assertEqual(previous(points, ts=6).total, 5)
        self.assertIsNone(previous(points, ts=1))

    def test_trend_returns_tail(self):
        points = [Point(ts=i, total=i) for i in range(10)]
        self.assertEqual([p.total for p in trend(points, 3)], [7, 8, 9])

    def test_make_point_snapshots_top_dirs(self):
        scan = scan_with([("a", 10), ("b", 5)])
        point = make_point(scan, reclaimable_bytes=7, now=42.0)
        self.assertEqual(point.ts, 42.0)
        self.assertEqual(point.total, 15)
        self.assertEqual(point.reclaimable, 7)
        self.assertEqual(point.dirs, {"a": 10, "b": 5})


class DescribeTests(unittest.TestCase):
    def test_first_run(self):
        now = Point(ts=100, total=10)
        self.assertIn("首次", describe(None, now))

    def test_growth(self):
        now = Point(ts=100 + 86400 * 3, total=20 * 1024 * 1024)
        prev = Point(ts=100, total=10 * 1024 * 1024)
        text = describe(prev, now)
        self.assertIn("+10.0 MB", text)
        self.assertIn("3 天前", text)

    def test_shrink(self):
        now = Point(ts=100, total=1024)
        prev = Point(ts=50, total=2048)
        self.assertIn("-1.0 KB", describe(prev, now))

    def test_unchanged(self):
        now = Point(ts=100, total=5)
        prev = Point(ts=99, total=5)
        self.assertIn("持平", describe(prev, now))


class CliHistoryTests(unittest.TestCase):
    def test_no_history_does_not_write(self):
        from dsh_doctor import cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsh"
            (root / "cache").mkdir(parents=True)
            (root / "cache" / "x.bin").write_bytes(b"x" * 100)
            record = Path(tmp) / "h.jsonl"
            cli.main(["--root", str(root), "--history", str(record), "--no-history"])
            self.assertFalse(record.exists())

    def test_runs_write_history(self):
        from dsh_doctor import cli

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "dsh"
            (root / "cache").mkdir(parents=True)
            record = Path(tmp) / "h.jsonl"
            cli.main(["--root", str(root), "--history", str(record)])
            cli.main(["--root", str(root), "--history", str(record)])
            self.assertEqual(len(load(record)), 2)


if __name__ == "__main__":
    unittest.main()
