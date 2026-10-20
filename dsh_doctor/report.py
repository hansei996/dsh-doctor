"""四种输出：表格、JSON、Markdown、单文件 HTML。"""

import html
import json
from typing import List

from . import __version__
from .rules import MARK, Finding, grade, reclaimable
from .scanner import Scan, human


def _rel(scan: Scan, path) -> str:
    prefix = str(scan.root).rstrip("/") + "/"
    text = str(path)
    return text[len(prefix):] if text.startswith(prefix) else text


def _largest_html(scan: Scan) -> str:
    if not scan.largest_files:
        return ""
    items = "\n".join(
        '      <li><code>%s</code><span class="size">%s</span></li>'
        % (html.escape(_rel(scan, path)), html.escape(human(size)))
        for path, size in scan.largest_files
    )
    return '    <h2>空间 Top %d</h2>\n    <ul class="files">\n%s\n    </ul>' % (
        len(scan.largest_files),
        items,
    )


def _largest_lines(scan: Scan) -> List[str]:
    return ["  %-9s %s" % (human(size), _rel(scan, path)) for path, size in scan.largest_files]


def to_table(scan: Scan, findings: List[Finding], value: int, delta: str = None) -> str:
    width = max(len(f.title) for f in findings)
    top = " · ".join("%s %s" % (d.name, human(d.size)) for d in scan.dirs[:4])
    lines = [
        "dsh-doctor · %s" % scan.root,
        "健康分 %d/100  评级 %s  可回收 %s"
        % (value, grade(value), human(reclaimable(findings))),
        "体积分布：%s" % (top or "-"),
    ]
    if delta:
        lines.append("趋势：%s" % delta)
    if scan.largest_files:
        lines.append("")
        lines.append("空间 Top %d（按单文件大小）" % len(scan.largest_files))
        lines.extend(_largest_lines(scan))
    lines.append("")
    for finding in findings:
        lines.append(
            "%s %-*s  %s" % (MARK[finding.level], width, finding.title, finding.detail)
        )
        if finding.suggestion:
            lines.append("  %s → %s" % (" " * width, finding.suggestion))
    fixable = [f for f in findings if f.fixable]
    if fixable:
        lines.append("")
        lines.append("可自动清理：%s" % "、".join("%s(%s)" % (f.title, human(f.reclaimable)) for f in fixable))
        lines.append("执行：dsh-doctor --fix")
    return "\n".join(lines)


def to_markdown(scan: Scan, findings: List[Finding], value: int, delta: str = None) -> str:
    lines = [
        "# dsh-doctor：%s" % scan.root,
        "",
        "**健康分 %d/100 · 评级 %s · 可回收 %s**"
        % (value, grade(value), human(reclaimable(findings))),
        "",
        "体积分布：%s"
        % " · ".join("%s %s" % (d.name, human(d.size)) for d in scan.dirs[:4]),
        "",
    ]
    if delta:
        lines.extend(["**趋势**：%s" % delta, ""])
    lines.extend(["| 状态 | 检查项 | 详情 | 建议 |", "| --- | --- | --- | --- |"])
    for finding in findings:
        lines.append(
            "| %s | %s | %s | %s |"
            % (MARK[finding.level], finding.title, finding.detail, finding.suggestion or "-")
        )
    if scan.largest_files:
        lines.extend(["", "**空间 Top %d**" % len(scan.largest_files), ""])
        for path, size in scan.largest_files:
            lines.append("- `%s` — %s" % (_rel(scan, path), human(size)))
    return "\n".join(lines)


def to_json(scan: Scan, findings: List[Finding], value: int, delta: str = None) -> str:
    payload = {
        "root": str(scan.root),
        "score": value,
        "grade": grade(value),
        "reclaimable_bytes": reclaimable(findings),
        "trend": delta,
        "largest_files": [
            {"path": _rel(scan, path), "size": size} for path, size in scan.largest_files
        ],
        "total_bytes": scan.total_size,
        "findings": [
            {
                "key": f.key,
                "level": f.level,
                "title": f.title,
                "detail": f.detail,
                "suggestion": f.suggestion,
                "reclaimable": f.reclaimable,
                "fixable": f.fixable,
            }
            for f in findings
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


_HTML_STYLE = """
    .trend { color: #475569; font-size: 13px; margin: 0 0 8px; }
    ul.files { list-style: none; padding: 0; margin: 0 0 16px; }
    ul.files li { display: flex; justify-content: space-between; gap: 12px; padding: 4px 0; border-bottom: 1px solid #e2e8f0; font-size: 13px; }
    ul.files .size { color: #64748b; white-space: nowrap; }
  * { box-sizing: border-box; }
  body { margin: 0; padding: 32px 24px 48px; background: #ffffff; color: #1f2328;
         font: 14px/1.6 -apple-system, "PingFang SC", "Helvetica Neue", Arial, sans-serif; }
  .wrap { max-width: 880px; margin: 0 auto; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .path { color: #57606a; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
          font-size: 12px; word-break: break-all; }
  .summary { display: flex; flex-wrap: wrap; gap: 12px; margin: 20px 0 8px; }
  .stat { border: 1px solid #d0d7de; border-radius: 8px; padding: 10px 14px; min-width: 128px; }
  .stat .k { color: #57606a; font-size: 12px; }
  .stat .v { font-size: 18px; font-weight: 600; }
  h2 { font-size: 15px; margin: 32px 0 12px; padding-bottom: 6px; border-bottom: 1px solid #d8dee4; }
  .bar-row { display: grid; grid-template-columns: 140px 1fr 84px; gap: 10px;
             align-items: center; margin: 6px 0; font-size: 12px; }
  .bar-name { font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
              overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .bar-track { background: #eaeef2; border-radius: 4px; height: 10px; overflow: hidden; }
  .bar-fill { background: #6e7781; height: 100%; border-radius: 4px; }
  .bar-size { text-align: right; color: #57606a; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid #eaeef2;
           vertical-align: top; }
  th { color: #57606a; font-weight: 600; font-size: 12px; }
  td.mark { width: 28px; font-weight: 700; text-align: center; }
  tr.ok td.mark { color: #1a7f37; }
  tr.warn td.mark { color: #9a6700; }
  tr.problem td.mark { color: #cf222e; }
  .suggest { color: #57606a; }
  .hint { margin-top: 12px; padding: 10px 12px; border: 1px solid #d0d7de;
          border-radius: 8px; background: #f6f8fa; font-size: 12px; color: #57606a; }
  footer { margin-top: 36px; color: #8c959f; font-size: 12px; }
  @media print {
    body { padding: 0; }
    .bar-fill { background: #444; }
    .hint { background: transparent; }
  }
"""


def to_html(scan: Scan, findings: List[Finding], value: int, delta: str = None) -> str:
    """单文件 HTML：内联样式、无外部资源、无 JS，可直接用浏览器打开或打印。"""
    root = html.escape(str(scan.root))
    reclaim = human(reclaimable(findings))
    fixable = [f for f in findings if f.fixable]

    max_size = max([d.size for d in scan.dirs], default=0) or 1
    bars = []
    for item in scan.dirs:
        percent = 100.0 * item.size / max_size
        if item.size > 0:
            percent = max(percent, 1.0)  # 小目录也留一条可见的细线
        bars.append(
            '      <div class="bar-row">'
            '<span class="bar-name" title="%s">%s</span>'
            '<span class="bar-track"><span class="bar-fill" style="width: %.1f%%"></span></span>'
            '<span class="bar-size">%s</span></div>'
            % (
                html.escape(item.name),
                html.escape(item.name),
                percent,
                html.escape(human(item.size)),
            )
        )

    rows = []
    for finding in findings:
        rows.append(
            '      <tr class="%s"><td class="mark">%s</td><td>%s</td><td>%s</td><td class="suggest">%s</td></tr>'
            % (
                html.escape(finding.level),
                html.escape(MARK[finding.level]),
                html.escape(finding.title),
                html.escape(finding.detail),
                html.escape(finding.suggestion or "-"),
            )
        )

    hint = ""
    if fixable:
        hint = (
            '    <p class="hint">可自动清理：%s。执行 <code>dsh-doctor --fix</code> 释放。</p>'
            % html.escape("、".join("%s(%s)" % (f.title, human(f.reclaimable)) for f in fixable))
        )

    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>dsh-doctor · %(root)s</title>
  <style>%(style)s  </style>
</head>
<body>
  <div class="wrap">
    <h1>dsh-doctor 体检报告</h1>
    <p class="path">%(root)s</p>
    <div class="summary">
      <div class="stat"><div class="k">健康分</div><div class="v">%(score)d/100</div></div>
      <div class="stat"><div class="k">评级</div><div class="v">%(grade)s</div></div>
      <div class="stat"><div class="k">可回收</div><div class="v">%(reclaim)s</div></div>
      <div class="stat"><div class="k">检查项</div><div class="v">%(count)d</div></div>
    </div>

    %(trend)s
    <h2>体积分布</h2>
%(bars)s

%(largest)s

    <h2>检查项</h2>
    <table>
      <thead><tr><th>状态</th><th>检查项</th><th>详情</th><th>建议</th></tr></thead>
      <tbody>
%(rows)s
      </tbody>
    </table>
%(hint)s

    <footer>由 dsh-doctor %(version)s 生成 · 单文件报告，无外部资源</footer>
  </div>
</body>
</html>
""" % {
        "root": root,
        "style": _HTML_STYLE,
        "score": value,
        "grade": html.escape(grade(value)),
        "reclaim": html.escape(reclaim),
        "count": len(findings),
        "bars": "\n".join(bars),
        "largest": _largest_html(scan),
        "rows": "\n".join(rows),
        "hint": hint,
        "trend": ('    <p class="trend">趋势：%s</p>' % html.escape(delta)) if delta else "",
        "version": html.escape(__version__),
    }
