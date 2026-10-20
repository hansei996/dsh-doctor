"""体检历史：记录每次扫描的体积，用来看趋势。

存储是一个 JSONL 文件，追加写、按行读；坏行直接跳过——
历史数据出问题不该让体检本身失败。
"""

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

HISTORY_ENV = "DSH_DOCTOR_HISTORY"
DEFAULT_MAX_POINTS = 100


def default_path() -> Path:
    override = os.environ.get(HISTORY_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".dsh-doctor" / "history.jsonl"


@dataclass
class Point:
    ts: float
    total: int
    reclaimable: int = 0
    dirs: Dict[str, int] = field(default_factory=dict)


def make_point(scan, reclaimable_bytes: int = 0, now: Optional[float] = None) -> Point:
    return Point(
        ts=now if now is not None else time.time(),
        total=scan.total_size,
        reclaimable=reclaimable_bytes,
        dirs={d.name: d.size for d in scan.dirs[:8]},
    )


def load(path: Path, limit: int = DEFAULT_MAX_POINTS) -> List[Point]:
    """读历史，按时间升序返回；坏行跳过。"""
    target = Path(path)
    if not target.is_file():
        return []
    points: List[Point] = []
    try:
        with target.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(raw, dict):
                    continue
                try:
                    points.append(
                        Point(
                            ts=float(raw["ts"]),
                            total=int(raw["total"]),
                            reclaimable=int(raw.get("reclaimable") or 0),
                            dirs={
                                str(k): int(v)
                                for k, v in (raw.get("dirs") or {}).items()
                                if isinstance(v, (int, float))
                            },
                        )
                    )
                except (KeyError, TypeError, ValueError):
                    continue
    except OSError:
        return []
    return points[-limit:]


def append(path: Path, point: Point, max_points: int = DEFAULT_MAX_POINTS) -> None:
    """追加一条记录；超过上限时只保留最近 max_points 条。写失败静默忽略。"""
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        existing = load(target, limit=10 ** 6)
        existing.append(point)
        trimmed = existing[-max_points:]
        with target.open("w", encoding="utf-8") as handle:
            for item in trimmed:
                handle.write(
                    json.dumps(
                        {
                            "ts": item.ts,
                            "total": item.total,
                            "reclaimable": item.reclaimable,
                            "dirs": item.dirs,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    except OSError:
        return


def previous(points: List[Point], ts: Optional[float] = None) -> Optional[Point]:
    """取早于 ts 的最近一条记录。"""
    if not points:
        return None
    cutoff = ts if ts is not None else time.time()
    earlier = [p for p in points if p.ts < cutoff]
    return max(earlier, key=lambda p: p.ts) if earlier else None


def describe(prev: Optional[Point], now: Point) -> str:
    """给人看的对比文案。"""
    if prev is None:
        return "首次记录，下次运行可对比变化"
    days = max(0, int((now.ts - prev.ts) // 86400))
    delta = now.total - prev.total
    sign = "+" if delta >= 0 else "-"
    amount = abs(delta)
    when = "刚刚" if days == 0 else "%d 天前" % days
    if delta == 0:
        return "与上次（%s）持平" % when
    return "较上次（%s）%s%s" % (when, sign, _human(amount))


def _human(size: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024.0:
            return "%d %s" % (int(size), unit) if unit == "B" else "%.1f %s" % (size, unit)
        size /= 1024.0
    return "%.1f PB" % size


def trend(points: List[Point], limit: int = 5) -> List[Point]:
    return points[-limit:]
