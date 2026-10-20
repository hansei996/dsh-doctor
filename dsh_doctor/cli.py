"""命令行入口。"""

import argparse
import sys
from pathlib import Path

from . import __version__
from .report import to_json, to_markdown, to_table
from .rules import build_findings, grade, reclaimable, score
from .scanner import default_root, human, scan


def parse_older_than(text):
    """把 "30d" / "30" 解析成正整数天。"""
    raw = str(text).strip().lower()
    if raw.endswith("d"):
        raw = raw[:-1]
    try:
        days = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError("--older-than 需要天数，例如 30d")
    if days <= 0:
        raise argparse.ArgumentTypeError("--older-than 必须是正整数天")
    return days


def build_parser():
    parser = argparse.ArgumentParser(
        prog="dsh-doctor", description="DeepSeek Harness 安装体检与瘦身（只清理缓存、旧备份与超期附件）"
    )
    parser.add_argument(
        "--root", help="DSH 主目录，默认 ~/.dsh，也可用环境变量 DSH_HOME"
    )
    parser.add_argument("--format", choices=("table", "json", "markdown"), default="table")
    parser.add_argument("--fix", action="store_true", help="执行安全清理（缓存 + 旧备份 + 超期附件）")
    parser.add_argument(
        "--older-than",
        metavar="30d",
        type=parse_older_than,
        help="只统计/清理超过 N 天的历史附件；不加 --fix 时仅报告",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="与 --fix 一起用时只打印将清理什么"
    )
    parser.add_argument("--version", action="version", version="dsh-doctor " + __version__)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    root = Path(args.root).expanduser() if args.root else default_root()

    current = scan(root)
    findings = build_findings(current, args.older_than)
    value = score(findings)

    if args.fix:
        targets = [f for f in findings if f.fixable]
        if not targets:
            print("没有可安全清理的项目。")
            return 0
        freed = 0
        for finding in targets:
            if args.dry_run:
                print("[dry-run] 将清理 %s（%s）" % (finding.title, human(finding.reclaimable)))
                continue
            got = finding.fix() if finding.fix else 0
            freed += got
            print("已清理 %s，释放 %s" % (finding.title, human(got)))
        if not args.dry_run:
            current = scan(root)
            findings = build_findings(current, args.older_than)
            value = score(findings)
            print("共释放 %s，当前体积 %s，健康分 %d" % (human(freed), human(current.total_size), value))
        return 0

    if args.format == "json":
        print(to_json(current, findings, value))
    elif args.format == "markdown":
        print(to_markdown(current, findings, value))
    else:
        print(to_table(current, findings, value))
    return 0 if value >= 60 else 1
