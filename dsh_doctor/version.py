"""DSH 应用版本读取与归一化比较。

只做纯字符串归一化（去掉 v 前缀、取主.次），不引入 packaging 依赖：
这里的目的不是语义化版本排序，而是判断"应用包"和"运行时目录"是不是同一代。
"""

import json
import os
import plistlib
from pathlib import Path
from typing import List, Optional, Tuple

DEFAULT_APP_PATH = "/Applications/DeepSeek Harness.app"
APP_PATH_ENV = "DSH_APP_PATH"
RUNTIME_META = "runtime.json"
RUNTIME_VERSION_KEYS = ("desktopVersion", "version")


def app_path() -> Path:
    """应用包路径，可用 DSH_APP_PATH 覆盖（测试和自建安装都用得上）。"""
    return Path(os.environ.get(APP_PATH_ENV) or DEFAULT_APP_PATH).expanduser()


def read_app_version(path: Optional[Path] = None) -> Optional[str]:
    """读 Contents/Info.plist 的 CFBundleShortVersionString。

    任何异常都吞掉并返回 None —— 体检工具不该因为读不到版本而失败。
    """
    root = Path(path) if path is not None else app_path()
    plist = root / "Contents" / "Info.plist"
    try:
        with plist.open("rb") as handle:
            data = plistlib.load(handle)
    except Exception:  # noqa: BLE001 - 文件缺失、权限、plist 损坏都归为"读不到"
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("CFBundleShortVersionString")
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def normalize(version: Optional[str]) -> Optional[str]:
    """归一化成 "主.次"；无法解析返回 None。"""
    if not version:
        return None
    text = version.strip().lower()
    if text.startswith("v"):
        text = text[1:]
    parts = [p for p in text.replace("-", ".").replace("_", ".").split(".") if p]
    numeric: List[str] = []
    for part in parts:
        if part.isdigit():
            numeric.append(part)
            continue
        break  # 遇到非数字段就停下，只看前面的数字部分
    if not numeric:
        return None
    while len(numeric) < 2:
        numeric.append("0")
    return "%s.%s" % (numeric[0], numeric[1])


def runtime_versions(versions: List[str]) -> List[str]:
    """从运行时目录名里挑出能解析出版本的，返回归一化结果。"""
    normalized = [normalize(name) for name in versions]
    return [item for item in normalized if item]


def read_runtime_version(path: Path) -> Optional[str]:
    """从运行时目录的 runtime.json 读版本号（desktopVersion 优先）。

    这比目录名可靠得多：目录名可以是 dsh-primary-runtime 这种不带版本的形式，
    而 runtime.json 是 DSH 自己写下的元数据。
    """
    meta = Path(path) / RUNTIME_META
    try:
        with meta.open(encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:  # noqa: BLE001 - 缺失、权限、坏 JSON 都算"读不到"
        return None
    if not isinstance(data, dict):
        return None
    for key in RUNTIME_VERSION_KEYS:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def compare(
    app_version: Optional[str],
    versions: List[str],
    meta_versions: Optional[List[str]] = None,
) -> Tuple[str, str]:
    """返回 (结论, 说明)，结论是 ok / warn / unknown。

    unknown 表示"判断不了"，调用方应降级为 OK 并说明原因。
    """
    app = normalize(app_version)
    if app is None:
        return "unknown", "未找到应用包或读不到版本号"

    # runtime.json 是权威来源，优先于目录名猜测
    raw_metas = [v for v in (meta_versions or []) if v]
    metas = []
    for value in raw_metas:
        normalized = normalize(value)
        if normalized:
            metas.append(normalized)
    if metas:
        unique = sorted(set(metas))
        shown = "、".join(raw_metas) if raw_metas else "、".join(unique)
        if app in unique:
            return "ok", "应用 %s，runtime.json 记录 %s" % (app_version, shown)
        return "warn", "应用 %s，runtime.json 记录 %s（可能残留旧运行时）" % (
            app_version,
            shown,
        )

    candidates = runtime_versions(versions)
    if not candidates:
        return "unknown", "运行时既没有 runtime.json 版本，目录名也不含版本号（%s）" % (
            "、".join(versions) or "空"
        )
    if app in candidates:
        return "ok", "应用 %s，目录名 %s" % (app_version, "、".join(sorted(set(versions))))
    return "warn", "应用 %s，目录名 %s" % (app_version, "、".join(sorted(set(versions))))
