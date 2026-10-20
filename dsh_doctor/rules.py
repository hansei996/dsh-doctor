"""体检规则：从 Scan 得出结论、可回收空间与清理动作。

约定：只有 cache 和旧备份允许自动清理。sessions / memories / profiles /
plugins / extensions / 凭据 一律只报告、不动手。
"""

import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from .scanner import Backup, Scan, human
from .version import compare
from .scanner import AttachmentFile, Backup, Scan, human

OK = "ok"
WARN = "warn"
PROBLEM = "problem"

MARK = {OK: "✓", WARN: "△", PROBLEM: "✗"}
PENALTY = {OK: 0, WARN: 8, PROBLEM: 20}

BACKUPS_TO_KEEP = 2
CACHE_WARN_BYTES = 50 * 1024 * 1024
ATTACHMENTS_WARN_BYTES = 1024 ** 3
RUNTIMES_WARN_BYTES = 500 * 1024 * 1024
DISK_WARN_BYTES = 10 * 1024 ** 3


@dataclass
class Finding:
    key: str
    level: str
    title: str
    detail: str
    suggestion: str = ""
    reclaimable: int = 0
    fix: Optional[Callable[[], int]] = None

    @property
    def fixable(self) -> bool:
        return self.fix is not None and self.reclaimable > 0


def _clear_dir(path: Path) -> int:
    freed = 0
    if not path.is_dir():
        return 0
    for entry in list(path.iterdir()):
        try:
            if entry.is_dir() and not entry.is_symlink():
                size = sum(f.stat().st_size for f in entry.rglob("*") if f.is_file())
                shutil.rmtree(str(entry))
                freed += size
            else:
                size = entry.stat().st_size
                entry.unlink()
                freed += size
        except OSError:
            continue
    return freed


def _delete_backups(root: Path, backups: List[Backup]) -> int:
    freed = 0
    for backup in backups[BACKUPS_TO_KEEP:]:
        target = root / "backups" / backup.name
        try:
            shutil.rmtree(str(target))
            freed += backup.size
        except OSError:
            continue
    return freed


def _is_expired(mtime: float, days: int, now: float) -> bool:
    """年龄刚好等于 N 天也算超期（>=），避免"第 30 天还留着"的歧义。"""
    return (now - mtime) >= days * 86400


def _delete_attachments(files: List[AttachmentFile]) -> int:
    """只删传入的文件；空目录保留，避免误伤会话引用的路径。"""
    freed = 0
    for item in files:
        try:
            item.path.unlink()
            freed += item.size
        except OSError:
            continue
    return freed


def build_findings(scan: Scan, older_than_days: Optional[int] = None) -> List[Finding]:
    findings: List[Finding] = []
    root = scan.root

    if not root.exists():
        return [
            Finding(
                "root",
                PROBLEM,
                "DSH 主目录不存在",
                str(root),
                "确认 DSH 是否安装，或用 --root 指定目录",
            )
        ]

    findings.append(
        Finding(
            "total",
            OK if scan.total_size < 2 * 1024 ** 3 else WARN,
            "主目录体积",
            "%s（%d 个子目录）" % (human(scan.total_size), len(scan.dirs)),
            "profiles 与 dsh-runtimes 通常占大头",
            reclaimable=0,
        )
    )

    cache = scan.dir("cache")
    if cache and cache.size > 0:
        level = WARN if cache.size >= CACHE_WARN_BYTES else OK
        findings.append(
            Finding(
                "cache",
                level,
                "缓存目录",
                "%s / %d 个文件" % (human(cache.size), cache.files),
                "可安全清理，下次启动会重建",
                reclaimable=cache.size,
                fix=(lambda p=root / "cache": _clear_dir(p)),
            )
        )

    old_backups = scan.backups[BACKUPS_TO_KEEP:]
    if scan.backups:
        reclaimable = sum(b.size for b in old_backups)
        findings.append(
            Finding(
                "backups",
                WARN if reclaimable > 0 else OK,
                "备份目录",
                "%d 份备份，共 %s" % (len(scan.backups), human(sum(b.size for b in scan.backups))),
                "建议保留最近 %d 份" % BACKUPS_TO_KEEP if reclaimable else "数量正常",
                reclaimable=reclaimable,
                fix=(lambda r=root, b=list(scan.backups): _delete_backups(r, b)) if reclaimable else None,
            )
        )

    runtimes = scan.dir("dsh-runtimes")
    if runtimes:
        findings.append(
            Finding(
                "runtimes",
                WARN if runtimes.size >= RUNTIMES_WARN_BYTES else OK,
                "运行时",
                "%s，%d 个版本" % (human(runtimes.size), len(scan.runtime_versions)),
                "旧版本可在 DSH 更新后手动清理，工具不自动删",
            )
        )

    state, version_detail = compare(
        scan.app_version, scan.runtime_versions, scan.runtime_meta_versions
    )
    if state == "warn":
        findings.append(
            Finding(
                "version",
                WARN,
                "版本一致性",
                version_detail,
                "关闭并重开 DSH 会重新解包运行时；仍不一致时清理 ~/.dsh/dsh-runtimes 下的残留版本",
            )
        )
    else:
        findings.append(
            Finding(
                "version",
                OK,
                "版本一致性",
                version_detail,
                "无法判断，不影响体检结论" if state == "unknown" else "",
            )
        )

    attachments = scan.dir("attachments")
    if attachments:
        findings.append(
            Finding(
                "attachments",
                WARN if attachments.size >= ATTACHMENTS_WARN_BYTES else OK,
                "附件",
                "%s / %d 个文件" % (human(attachments.size), attachments.files),
                "截图与会话绑定，删前先确认会话是否还需要",
            )
        )

    if older_than_days and scan.attachment_files:
        now = time.time()
        expired = [
            item
            for item in scan.attachment_files
            if _is_expired(item.mtime, older_than_days, now)
        ]
        expired_size = sum(item.size for item in expired)
        findings.append(
            Finding(
                "attachments_old",
                WARN if expired else OK,
                "历史附件",
                "%d 个文件超过 %d 天，共 %s" % (len(expired), older_than_days, human(expired_size))
                if expired
                else "没有超过 %d 天的附件" % older_than_days,
                "用 --fix --older-than %dd 清理" % older_than_days if expired else "",
                reclaimable=expired_size,
                fix=(lambda items=list(expired): _delete_attachments(items)) if expired else None,
            )
        )

    findings.append(
        Finding(
            "credentials",
            PROBLEM if scan.credentials is None else (WARN if scan.credential_mode != 0o600 else OK),
            "凭据文件",
            "缺失" if scan.credentials is None
            else "权限 %o" % scan.credential_mode,
            "应存在且权限为 600" if scan.credentials is not None else "重新登录 DSH",
        )
    )

    if scan.session_count:
        largest = scan.largest_session
        findings.append(
            Finding(
                "sessions",
                OK,
                "会话",
                "%d 个，最大 %s" % (scan.session_count, human(largest[1]) if largest else "-"),
                "只在需要时清理",
            )
        )

    if scan.disk_total:
        level = WARN if scan.disk_free < DISK_WARN_BYTES else OK
        findings.append(
            Finding(
                "disk",
                level,
                "磁盘余量",
                "%s 可用 / 共 %s" % (human(scan.disk_free), human(scan.disk_total)),
                "剩余不足 10 GB 时建议先清理缓存与旧备份" if level == WARN else "",
            )
        )

    findings.append(
        Finding(
            "addons",
            OK,
            "插件与扩展",
            "%d 个插件，%d 个扩展" % (scan.plugin_count, scan.extension_count),
            "",
        )
    )

    return findings


def score(findings: List[Finding]) -> int:
    return max(0, 100 - sum(PENALTY[f.level] for f in findings))


def grade(value: int) -> str:
    if value >= 90:
        return "A"
    if value >= 80:
        return "B"
    if value >= 70:
        return "C"
    if value >= 60:
        return "D"
    return "F"


def reclaimable(findings: List[Finding]) -> int:
    return sum(f.reclaimable for f in findings if f.fixable)
