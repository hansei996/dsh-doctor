"""三种输出：表格、JSON、Markdown。"""

import json
from typing import List

from .rules import MARK, Finding, grade, reclaimable
from .scanner import Scan, human


def to_table(scan: Scan, findings: List[Finding], value: int) -> str:
    width = max(len(f.title) for f in findings)
    top = " · ".join("%s %s" % (d.name, human(d.size)) for d in scan.dirs[:4])
    lines = [
        "dsh-doctor · %s" % scan.root,
        "健康分 %d/100  评级 %s  可回收 %s"
        % (value, grade(value), human(reclaimable(findings))),
        "体积分布：%s" % (top or "-"),
        "",
    ]
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


def to_markdown(scan: Scan, findings: List[Finding], value: int) -> str:
    lines = [
        "# dsh-doctor：%s" % scan.root,
        "",
        "**健康分 %d/100 · 评级 %s · 可回收 %s**"
        % (value, grade(value), human(reclaimable(findings))),
        "",
        "体积分布：%s"
        % " · ".join("%s %s" % (d.name, human(d.size)) for d in scan.dirs[:4]),
        "",
        "| 状态 | 检查项 | 详情 | 建议 |",
        "| --- | --- | --- | --- |",
    ]
    for finding in findings:
        lines.append(
            "| %s | %s | %s | %s |"
            % (MARK[finding.level], finding.title, finding.detail, finding.suggestion or "-")
        )
    return "\n".join(lines)


def to_json(scan: Scan, findings: List[Finding], value: int) -> str:
    payload = {
        "root": str(scan.root),
        "score": value,
        "grade": grade(value),
        "reclaimable_bytes": reclaimable(findings),
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
