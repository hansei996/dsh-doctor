"""扫描 DSH 主目录：体积分布、关键文件、磁盘余量。

只读，不做任何删除；清理动作在 rules.fix 里，且只由 CLI 的 --fix 触发。
"""

import heapq
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .version import app_path as default_app_path
from .version import read_app_version, read_runtime_version

# 已知子目录；未知目录也会被统计，只是没有专门规则
KNOWN_DIRS = (
    "profiles",
    "dsh-runtimes",
    "plugins",
    "extensions",
    "attachments",
    "cache",
    "sessions",
    "backups",
    "memories",
    "llm-deepseek",
)


def human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024.0:
            return "%.1f %s" % (size, unit) if unit != "B" else "%d B" % int(size)
        size /= 1024.0
    return "%.1f PB" % size


TOP_FILES_LIMIT = 50


def dir_size(
    path: Path, heap=None, heap_limit: int = TOP_FILES_LIMIT, skipped=None
) -> Tuple[int, int]:
    """返回 (总字节, 文件数)。软链接只计链接本身，不跟随。

    传入 heap 时会顺手收集最大的若干文件（小顶堆，堆顶是最小的那个），
    这样只遍历一次就能同时拿到体积和"空间黑洞"。
    """
    total = 0
    files = 0
    try:
        entries = list(os.scandir(str(path)))
    except OSError:
        # 无权限或目录刚被删：记下来继续，不让体检整体失败
        if skipped is not None:
            skipped.append(str(path))
        return total, files
    for entry in entries:
        try:
            if entry.is_symlink():
                total += entry.stat(follow_symlinks=False).st_size
                files += 1
            elif entry.is_dir(follow_symlinks=False):
                sub_total, sub_files = dir_size(Path(entry.path), heap, heap_limit, skipped)
                total += sub_total
                files += sub_files
            elif entry.is_file(follow_symlinks=False):
                size = entry.stat(follow_symlinks=False).st_size
                total += size
                files += 1
                if heap is not None:
                    heapq.heappush(heap, (size, entry.path))
                    if len(heap) > heap_limit:
                        heapq.heappop(heap)
        except OSError:
            continue
    return total, files


@dataclass
class DirStat:
    name: str
    size: int
    files: int


@dataclass
class Backup:
    name: str
    size: int
    mtime: float


@dataclass
class AttachmentFile:
    """单个附件文件的 (路径, 大小, 修改时间)。

    scanner 只记录事实，是否算"超期"由 rules 判断。
    """

    path: Path
    size: int
    mtime: float


def collect_files(path: Path) -> List[AttachmentFile]:
    """递归收集文件 (路径, 大小, mtime)。只读，不跟随软链接。"""
    items: List[AttachmentFile] = []
    for entry in os.scandir(str(path)):
        try:
            if entry.is_symlink():
                continue
            if entry.is_dir(follow_symlinks=False):
                items.extend(collect_files(Path(entry.path)))
            elif entry.is_file(follow_symlinks=False):
                stat = entry.stat(follow_symlinks=False)
                items.append(AttachmentFile(Path(entry.path), stat.st_size, stat.st_mtime))
        except OSError:
            continue
    return items



@dataclass
class Scan:
    root: Path
    dirs: List[DirStat] = field(default_factory=list)
    files: Dict[str, int] = field(default_factory=dict)
    credentials: Optional[Path] = None
    credential_mode: Optional[int] = None
    session_count: int = 0
    largest_session: Optional[Tuple[str, int]] = None
    runtime_versions: List[str] = field(default_factory=list)
    runtime_meta_versions: List[str] = field(default_factory=list)
    backups: List[Backup] = field(default_factory=list)
    extension_count: int = 0
    plugin_count: int = 0
    disk_free: int = 0
    disk_total: int = 0
    app_path: Optional[Path] = None
    app_version: Optional[str] = None
    attachment_files: List[AttachmentFile] = field(default_factory=list)
    largest_files: List[Tuple[str, int]] = field(default_factory=list)
    skipped_dirs: List[str] = field(default_factory=list)

    @property
    def total_size(self) -> int:
        return sum(d.size for d in self.dirs) + sum(self.files.values())

    def dir(self, name: str) -> Optional[DirStat]:
        for item in self.dirs:
            if item.name == name:
                return item
        return None


def default_root() -> Path:
    return Path(os.environ.get("DSH_HOME") or (Path.home() / ".dsh"))


def scan(root: Optional[Path] = None, app_root: Optional[Path] = None) -> Scan:
    root = Path(root or default_root()).expanduser()
    result = Scan(root=root)
    # 应用包与 ~/.dsh 相互独立，默认取标准的 /Applications 位置，可被参数或环境变量覆盖
    result.app_path = Path(app_root) if app_root is not None else default_app_path()
    result.app_version = read_app_version(result.app_path)
    if not root.exists():
        return result

    heap = []
    for entry in sorted(os.scandir(str(root)), key=lambda e: e.name):
        path = Path(entry.path)
        if not entry.is_dir(follow_symlinks=False):
            try:
                result.files[entry.name] = entry.stat(follow_symlinks=False).st_size
            except OSError:
                pass
            continue
        size, files = dir_size(path, heap, skipped=result.skipped_dirs)
        result.dirs.append(DirStat(entry.name, size, files))

    result.largest_files = sorted(
        ((path, size) for size, path in heap), key=lambda item: item[1], reverse=True
    )

    result.dirs.sort(key=lambda d: d.size, reverse=True)

    credentials = root / ".credentials.yaml"
    if credentials.is_file():
        result.credentials = credentials
        result.credential_mode = credentials.stat().st_mode & 0o777

    sessions_dir = root / "sessions"
    if sessions_dir.is_dir():
        counts = []
        for entry in os.scandir(str(sessions_dir)):
            if not entry.is_dir(follow_symlinks=False):
                continue
            size, _ = dir_size(Path(entry.path))
            counts.append((entry.name, size))
        result.session_count = len(counts)
        if counts:
            result.largest_session = max(counts, key=lambda item: item[1])

    runtimes_dir = root / "dsh-runtimes"
    if runtimes_dir.is_dir():
        names, metas = [], []
        for entry in sorted(os.scandir(str(runtimes_dir)), key=lambda e: e.name):
            if not entry.is_dir(follow_symlinks=False):
                continue
            names.append(entry.name)
            version = read_runtime_version(Path(entry.path))
            if version:
                metas.append(version)
        result.runtime_versions = names
        result.runtime_meta_versions = metas

    backups_dir = root / "backups"
    if backups_dir.is_dir():
        for entry in os.scandir(str(backups_dir)):
            if entry.is_dir(follow_symlinks=False):
                size, _ = dir_size(Path(entry.path))
                result.backups.append(Backup(entry.name, size, entry.stat().st_mtime))
        result.backups.sort(key=lambda b: b.mtime, reverse=True)

    for name, attr in (("extensions", "extension_count"), ("plugins", "plugin_count")):
        path = root / name
        if path.is_dir():
            setattr(
                result,
                attr,
                sum(1 for e in os.scandir(str(path)) if e.is_dir(follow_symlinks=False)),
            )

    attachments_dir = root / "attachments"
    if attachments_dir.is_dir():
        result.attachment_files = collect_files(attachments_dir)

    try:
        usage = shutil.disk_usage(str(root))
        result.disk_free = usage.free
        result.disk_total = usage.total
    except OSError:
        pass

    return result
