import unittest
from pathlib import Path

from dsh_doctor.cli import build_parser
from dsh_doctor.report import to_html
from dsh_doctor.rules import OK, PROBLEM, WARN, Finding, grade, reclaimable
from dsh_doctor.scanner import DirStat, Scan


def make_scan(root="/Users/tester/.dsh"):
    scan = Scan(root=Path(root))
    scan.dirs = [
        DirStat("profiles", 343 * 1024 ** 2, 120),
        DirStat("dsh-runtimes", 300 * 1024 ** 2, 80),
        DirStat("cache", 4 * 1024 ** 2, 23),
    ]
    scan.files = {"pet.json": 450}
    return scan


def make_findings():
    return [
        Finding("total", OK, "主目录体积", "678.0 MB（3 个子目录）", "通常占大头"),
        Finding(
            "cache",
            WARN,
            "缓存目录",
            "4.0 MB / 23 个文件",
            "可安全清理",
            reclaimable=4 * 1024 ** 2,
            fix=lambda: 0,
        ),
        Finding("credentials", PROBLEM, "凭据文件", "权限 644", "应为 600"),
    ]


class HtmlReportTests(unittest.TestCase):
    def setUp(self):
        self.scan = make_scan()
        self.findings = make_findings()
        self.value = 72
        self.html = to_html(self.scan, self.findings, self.value)

    def test_is_a_full_document(self):
        self.assertTrue(self.html.startswith("<!DOCTYPE html>"))
        self.assertIn('<html lang="zh-CN">', self.html)
        self.assertIn("</html>", self.html)
        self.assertIn('<meta charset="utf-8">', self.html)

    def test_contains_path_and_score(self):
        self.assertIn("/Users/tester/.dsh", self.html)
        self.assertIn("72/100", self.html)
        self.assertIn(grade(self.value), self.html)
        self.assertGreater(reclaimable(self.findings), 0)
        self.assertIn("4.0 MB", self.html)
        self.assertIn("可自动清理", self.html)

    def test_every_finding_has_a_row(self):
        self.assertEqual(self.html.count('class="mark"'), len(self.findings))
        for finding in self.findings:
            self.assertIn(finding.title, self.html)
            self.assertIn(finding.detail, self.html)

    def test_levels_map_to_colored_rows(self):
        for level in (OK, WARN, PROBLEM):
            self.assertIn('<tr class="%s">' % level, self.html)
        self.assertIn("tr.problem td.mark { color: #cf222e; }", self.html)

    def test_size_bars_use_percentages(self):
        # 最大的目录应该占满整条
        self.assertIn('style="width: 100.0%"', self.html)
        self.assertIn("profiles", self.html)
        self.assertIn("dsh-runtimes", self.html)
        # 0 字节或缺失时不至于除零
        empty = to_html(make_scan(), [], 0)
        self.assertIn("<!DOCTYPE html>", empty)

    def test_path_with_markup_is_escaped(self):
        scan = make_scan('/tmp/<script>alert("x")</script>&co')
        html = to_html(scan, make_findings(), 90)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("&amp;co", html)

    def test_finding_text_is_escaped(self):
        findings = [Finding("odd", WARN, "a<b", "c>d", "e&f")]
        html = to_html(make_scan(), findings, 50)
        self.assertNotIn("a<b", html)
        self.assertIn("a&lt;b", html)
        self.assertIn("e&amp;f", html)

    def test_no_external_resources(self):
        self.assertNotIn("http://", self.html)
        self.assertNotIn("https://", self.html)
        self.assertNotIn("<script", self.html)
        self.assertNotIn("<link", self.html)


class CliHtmlFormatTests(unittest.TestCase):
    def test_html_is_an_accepted_format(self):
        args = build_parser().parse_args(["--format", "html"])
        self.assertEqual(args.format, "html")

    def test_default_format_unchanged(self):
        self.assertEqual(build_parser().parse_args([]).format, "table")


if __name__ == "__main__":
    unittest.main()
