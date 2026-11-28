# -*- coding: utf-8 -*-
"""燧镜自己的磁盘占用：看清多少、清掉能清的，但不碰用户的成果。

可以清（删了会自动重建）：
    官网图标缓存、日志

一律不动：素材（截图/录屏成品）、回放缓冲、收到/分享、配置、模组。
那些删了就是用户的损失，跟"缓存"不是一回事。

着色器缓存（NVIDIA / AMD / Intel）在 core/cacheclean.py，是另一件事：
清了之后游戏首局更卡，所以两个入口故意分开，不合并成"一键清理"。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import List, Tuple

from core.cacheclean import _dir_size, fmt_size
from core.store import app_dir


# key, 显示名, 能不能清, 一句说明
ITEMS = [
    ("icons", "官网图标缓存", True, "三方工具的图标，删了下次打开会重新抓"),
    ("names", "Steam 名字缓存", False, "公开的商品名，很小，留着省得每次补"),
    ("logs", "日志", True, "排查问题用；程序正在写的那个会被跳过"),
    ("media", "素材（截图 + 录屏）", False, "你的成品，不动"),
    ("replay", "回放缓冲", False, "最近 10 分钟的临时片段，上限在「回放缓存」那组单独设"),
]


def _path_of(key: str, cfg) -> Path:
    """每一项的真实位置；配置里没指定就落到程序目录下的同名子目录。"""
    root = app_dir()
    if key == "icons":
        return root / "cache" / "favicons"
    if key == "names":
        return root / "steam_names.json"
    if key == "logs":
        return root / "logs"
    if key == "media":
        custom = str(getattr(cfg, "media_dir", "") or "").strip()
        return Path(custom) if custom else root / "素材"
    if key == "replay":
        custom = str(getattr(cfg, "replay_dir", "") or "").strip()
        return Path(custom) if custom else root / "回放缓冲"
    return root


def _measure(path: Path) -> Tuple[int, int]:
    if not path.exists():
        return 0, 0
    if path.is_dir():
        return _dir_size(path)
    try:
        return path.stat().st_size, 1
    except OSError:
        return 0, 0


def scan(cfg=None) -> List[dict]:
    """列出每一项：key / 名称 / 路径 / 字节 / 文件数 / 能不能清 / 说明。"""
    rows: List[dict] = []
    for key, label, cleanable, note in ITEMS:
        path = _path_of(key, cfg)
        size, files = _measure(path)
        rows.append({
            "key": key,
            "label": label,
            "path": str(path),
            "size": size,
            "files": files,
            "cleanable": cleanable,
            "note": note,
            "exists": path.exists(),
        })
    return rows


def total_size(rows: List[dict] | None = None, cfg=None) -> int:
    rows = rows if rows is not None else scan(cfg)
    return sum(r["size"] for r in rows)


def cleanable_size(rows: List[dict] | None = None, cfg=None) -> int:
    rows = rows if rows is not None else scan(cfg)
    return sum(r["size"] for r in rows if r["cleanable"])


def _remove(path: Path, skipped: List[str]) -> Tuple[int, int]:
    """删一个文件或目录。被占用的跳过并记一笔，不中断整轮。"""
    freed = removed = 0
    if path.is_file():
        try:
            freed = path.stat().st_size
            path.unlink()
            removed = 1
        except OSError:
            skipped.append(path.name)
        return freed, removed

    if not path.is_dir():
        return 0, 0

    for item in list(path.iterdir()):
        try:
            if item.is_dir():
                size, files = _dir_size(item)
                try:
                    shutil.rmtree(item)
                    freed += size
                    removed += files
                except OSError:
                    # 目录里有文件被占用：能删的先删，剩下的下次再来
                    for sub in item.rglob("*"):
                        if not sub.is_file():
                            continue
                        try:
                            freed += sub.stat().st_size
                            sub.unlink()
                            removed += 1
                        except OSError:
                            skipped.append(sub.name)
                    try:
                        item.rmdir()
                    except OSError:
                        pass
            else:
                size = item.stat().st_size
                item.unlink()
                freed += size
                removed += 1
        except OSError:
            skipped.append(item.name)
    return freed, removed


def clean(cfg=None) -> Tuple[int, int, List[str]]:
    """清掉可清的那几项。返回 (释放字节, 删除文件数, 跳过的文件名列表)。"""
    freed = removed = 0
    skipped: List[str] = []
    for key, _label, cleanable, _note in ITEMS:
        if not cleanable:
            continue
        path = _path_of(key, cfg)
        if not path.exists():
            continue
        f, r = _remove(path, skipped)
        freed += f
        removed += r
    return freed, removed, skipped


def human(num: int) -> str:
    return fmt_size(num)


def total_text(cfg=None) -> str:
    """设置页那一行：总共多少 + 明细。"""
    rows = scan(cfg)
    total = total_size(rows, cfg)
    parts = [
        f"{r['label'].split('（')[0]} {human(r['size'])}"
        for r in rows
        if r["exists"] and r["size"]
    ]
    head = f"一共占用 {human(total)}"
    if parts:
        head += "（" + " · ".join(parts) + "）"
    return head
