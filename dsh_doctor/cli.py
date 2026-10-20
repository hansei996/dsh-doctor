"""命令行入口。"""

import argparse
import sys
from pathlib import Path

from . import __version__, history
from .report import to_html, to_json, to_markdown, to_table
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
    parser.add_argument(
        "--format", choices=("table", "json", "markdown", "html"), default="table"
    )
    parser.add_argument("--fix", action="store_true", help="执行安全清理（缓存 + 旧备份 + 超期附件）")
    parser.add_argument(
        "--yes", action="store_true", help="与 --fix 一起用时跳过确认（非交互环境必需）"
    )
    parser.add_argument(
        "--older-than",
        metavar="30d",
        type=parse_older_than,
        help="只统计/清理超过 N 天的历史附件；不加 --fix 时仅报告",
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="与 --fix 一起用时只打印将清理什么"
    )
    parser.add_argument(
        "--top",
        metavar="N",
        type=int,
        default=5,
        help="展示最大的 N 个文件（按单文件大小），默认 5，0 表示不展示",
    )
    parser.add_argument(
        "--history",
        metavar="PATH",
        help="体检历史文件路径，默认 ~/.dsh-doctor/history.jsonl（可用 DSH_DOCTOR_HISTORY 覆盖）",
    )
    parser.add_argument(
        "--no-history", action="store_true", help="不读也不写历史，纯单次体检"
    )
    parser.add_argument("--version", action="version", version="dsh-doctor " + __version__)
    return parser


def _history_path(args):
    if args.no_history:
        return None
    return Path(args.history).expanduser() if args.history else history.default_path()


def _record(path, scan_result, findings):
    """追加一次记录；拿不到就安静跳过。"""
    if path is None:
        return None
    point = history.make_point(scan_result, reclaimable(findings))
    previous = history.previous(history.load(path), point.ts)
    delta = history.describe(previous, point)
    history.append(path, point)
    return delta


def _confirm(fix_targets) -> bool:
    """在交互终端里等一次确认。非交互环境返回 False（要求显式 --yes）。"""
    try:
        interactive = sys.stdin.isatty()
    except (AttributeError, ValueError):
        interactive = False
    if not interactive:
        print("非交互环境，未执行清理；确认无误请加 --yes。", file=sys.stderr)
        return False
    try:
        answer = input("确认清理？[y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        return False
    return answer in ("y", "yes")


def main(argv=None):
    args = build_parser().parse_args(argv)
    root = Path(args.root).expanduser() if args.root else default_root()
    history_path = _history_path(args)

    current = scan(root)
    if args.top <= 0:
        current.largest_files = []
    else:
        current.largest_files = current.largest_files[: args.top]
    findings = build_findings(current, args.older_than)
    value = score(findings)
    delta = None

    if args.fix:
        targets = [f for f in findings if f.fixable]
        if not targets:
            print("没有可安全清理的项目。")
            return 0
        if args.dry_run:
            for finding in targets:
                print("[dry-run] 将清理 %s（%s）" % (finding.title, human(finding.reclaimable)))
            return 0

        print("将清理：")
        for finding in targets:
            print("  %-10s %s" % (finding.title, human(finding.reclaimable)))
        print("合计 %s" % human(sum(f.reclaimable for f in targets)))
        if not args.yes and not _confirm(targets):
            return 0

        freed = 0
        for finding in targets:
            got = finding.fix() if finding.fix else 0
            freed += got
            print("已清理 %s，释放 %s" % (finding.title, human(got)))

        current = scan(root)
        if args.top <= 0:
            current.largest_files = []
        else:
            current.largest_files = current.largest_files[: args.top]
        findings = build_findings(current, args.older_than)
        value = score(findings)
        _record(history_path, current, findings)
        print("共释放 %s，当前体积 %s，健康分 %d" % (human(freed), human(current.total_size), value))
        return 0

    delta = _record(history_path, current, findings)
    if args.format == "json":
        print(to_json(current, findings, value, delta))
    elif args.format == "markdown":
        print(to_markdown(current, findings, value, delta))
    elif args.format == "html":
        print(to_html(current, findings, value, delta))
    else:
        print(to_table(current, findings, value, delta))
    return 0 if value >= 60 else 1
