import os
import plistlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from dsh_doctor import version
from dsh_doctor.version import (
    app_path,
    compare,
    normalize,
    read_app_version,
    read_runtime_version,
    runtime_versions,
)


def make_app(root: Path, version_value=None, extra=None) -> Path:
    """造一个应用包目录，只写体检需要的那部分。"""
    contents = root / "Contents"
    contents.mkdir(parents=True, exist_ok=True)
    payload = {"CFBundleIdentifier": "com.example.dsh"}
    if version_value is not None:
        payload["CFBundleShortVersionString"] = version_value
    if extra:
        payload.update(extra)
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(payload, handle)
    return root


class NormalizeTests(unittest.TestCase):
    def test_strips_v_prefix(self):
        self.assertEqual(normalize("v0.4.1"), "0.4")

    def test_takes_major_and_minor_only(self):
        self.assertEqual(normalize("0.4.1"), "0.4")
        self.assertEqual(normalize("1.12.99"), "1.12")

    def test_drops_prerelease_suffix(self):
        self.assertEqual(normalize("0.2.1-rc.2"), "0.2")

    def test_pads_missing_minor(self):
        self.assertEqual(normalize("3"), "3.0")

    def test_rejects_non_versions(self):
        for value in ("", None, "dsh-primary-runtime", "latest"):
            self.assertIsNone(normalize(value), value)


class ReadAppVersionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_reads_short_version_string(self):
        app = make_app(self.root / "DeepSeek Harness.app", "0.2.1")
        self.assertEqual(read_app_version(app), "0.2.1")

    def test_missing_app_returns_none(self):
        self.assertIsNone(read_app_version(self.root / "not-there.app"))

    def test_missing_key_returns_none(self):
        app = make_app(self.root / "noversion.app")
        self.assertIsNone(read_app_version(app))

    def test_broken_plist_returns_none(self):
        app = self.root / "broken.app"
        contents = app / "Contents"
        contents.mkdir(parents=True)
        (contents / "Info.plist").write_bytes(b"this is not a plist")
        self.assertIsNone(read_app_version(app))

    def test_blank_version_returns_none(self):
        app = make_app(self.root / "blank.app", "   ")
        self.assertIsNone(read_app_version(app))

    def test_env_override_changes_default_path(self):
        app = make_app(self.root / "custom.app", "1.2.3")
        with mock.patch.dict(os.environ, {version.APP_PATH_ENV: str(app)}):
            self.assertEqual(app_path(), app)
            self.assertEqual(read_app_version(), "1.2.3")

    def test_default_path_when_env_absent(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(version.APP_PATH_ENV, None)
            self.assertEqual(app_path(), Path(version.DEFAULT_APP_PATH))


class CompareTests(unittest.TestCase):
    def test_consistent_versions_are_ok(self):
        state, detail = compare("0.4.1", ["v0.4.9", "0.4.2"])
        self.assertEqual(state, "ok")
        self.assertIn("0.4", detail)

    def test_mismatch_is_warn_and_shows_both(self):
        state, detail = compare("0.5.0", ["0.4.2"])
        self.assertEqual(state, "warn")
        self.assertIn("0.5", detail)
        self.assertIn("0.4", detail)

    def test_missing_app_is_unknown(self):
        state, detail = compare(None, ["0.4.2"])
        self.assertEqual(state, "unknown")
        self.assertIn("未找到", detail)

    def test_unversioned_runtime_dirs_are_unknown(self):
        state, detail = compare("0.2.1", ["dsh-primary-runtime"])
        self.assertEqual(state, "unknown")
        self.assertIn("不含版本号", detail)

    def test_runtime_versions_filters_unparseable(self):
        self.assertEqual(runtime_versions(["dsh-primary-runtime", "v1.2.3"]), ["1.2"])


class RuntimeMetaTests(unittest.TestCase):
    """运行时目录里的 runtime.json 是版本的权威来源。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name) / "dsh-primary-runtime"
        self.dir.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write_meta(self, payload):
        import json

        (self.dir / "runtime.json").write_text(json.dumps(payload), encoding="utf-8")

    def test_reads_desktop_version(self):
        self.write_meta({"desktopVersion": "0.2.1-rc.2"})
        self.assertEqual(read_runtime_version(self.dir), "0.2.1-rc.2")

    def test_falls_back_to_version_key(self):
        self.write_meta({"version": "0.3.0"})
        self.assertEqual(read_runtime_version(self.dir), "0.3.0")

    def test_missing_meta_returns_none(self):
        self.assertIsNone(read_runtime_version(self.dir))

    def test_broken_json_returns_none(self):
        (self.dir / "runtime.json").write_text("{not json", encoding="utf-8")
        self.assertIsNone(read_runtime_version(self.dir))

    def test_non_string_version_is_ignored(self):
        self.write_meta({"desktopVersion": 42})
        self.assertIsNone(read_runtime_version(self.dir))

    def test_compare_prefers_meta_over_directory_name(self):
        state, detail = compare("0.2.1", ["dsh-primary-runtime"], ["0.2.1-rc.2"])
        self.assertEqual(state, "ok")
        self.assertIn("runtime.json", detail)

    def test_compare_warns_on_meta_mismatch(self):
        state, detail = compare("0.9.0", ["dsh-primary-runtime"], ["0.2.1-rc.2"])
        self.assertEqual(state, "warn")
        self.assertIn("0.2", detail)

    def test_compare_falls_back_to_directory_name(self):
        state, detail = compare("0.4.0", ["v0.4.7"], [])
        self.assertEqual(state, "ok")
        self.assertIn("目录名", detail)

    def test_compare_unknown_when_neither_source(self):
        state, detail = compare("0.4.0", ["dsh-primary-runtime"], [])
        self.assertEqual(state, "unknown")
        self.assertIn("runtime.json", detail)


if __name__ == "__main__":
    unittest.main()
