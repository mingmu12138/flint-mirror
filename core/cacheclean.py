# -*- coding: utf-8 -*-
"""着色器缓存清理：赛季更新后帧率塌了、进图卡顿，八成是旧缓存。

只删这些"删了会自动重建"的缓存目录，不动游戏本体：
  NVIDIA DXCache / GLCache / NV_Cache、AMD DxCache / GLCache / VkCache、
  Intel ShaderCache、DirectX D3DSCache
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import List, Tuple

LOCAL = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
ROAM = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming"))
PROGRAMDATA = Path(os.environ.get("PROGRAMDATA", Path("C:/ProgramData")))

CACHE_DIRS: List[Tuple[str, Path]] = [
    ("NVIDIA DX 缓存", LOCAL / "NVIDIA" / "DXCache"),
    ("NVIDIA GL 缓存", LOCAL / "NVIDIA" / "GLCache"),
    ("NVIDIA NV_Cache", LOCAL / "NVIDIA Corporation" / "NV_Cache"),
    ("NVIDIA 驱动缓存", PROGRAMDATA / "NVIDIA Corporation" / "NV_Cache"),
    ("AMD DX 缓存", LOCAL / "AMD" / "DxCache"),
    ("AMD GL 缓存", LOCAL / "AMD" / "GLCache"),
    ("AMD Vulkan 缓存", LOCAL / "AMD" / "VkCache"),
    ("Intel 着色器缓存", LOCAL / "Intel" / "ShaderCache"),
    ("DirectX 着色器缓存", LOCAL / "D3DSCache"),
]


def _dir_size(path: Path) -> Tuple[int, int]:
    total = files = 0
    try:
        for item in path.rglob("*"):
            if item.is_file():
                try:
                    total += item.stat().st_size
                    files += 1
                except OSError:
                    pass
    except OSError:
        pass
    return total, files


def scan() -> List[dict]:
    """列出存在的缓存目录及其大小。"""
    rows = []
    for label, path in CACHE_DIRS:
        if not path.exists():
            continue
        size, files = _dir_size(path)
        rows.append({"label": label, "path": str(path), "size": size, "files": files})
    return rows


def total_size(rows: List[dict] | None = None) -> int:
    rows = rows if rows is not None else scan()
    return sum(r["size"] for r in rows)


def clean() -> Tuple[int, int, List[str]]:
    """删缓存。返回 (释放字节, 删除文件数, 跳过说明列表)。

    游戏开着时部分文件被占用删不掉，跳过就好，下次再清。
    """
    freed = removed = 0
    skipped: List[str] = []
    for label, path in CACHE_DIRS:
        if not path.exists():
            continue
        for item in list(path.iterdir()):
            try:
                if item.is_dir():
                    size, files = _dir_size(item)
                    shutil.rmtree(item, ignore_errors=True)
                    freed += size
                    removed += files
                    continue
                size = item.stat().st_size
                item.unlink()
                freed += size
                removed += 1
            except OSError:
                skipped.append(f"{label}：{item.name} 正在被占用")
    return freed, removed, skipped


def fmt_size(num: int) -> str:
    value = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit in ("B", "KB") else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"
