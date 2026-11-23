# -*- coding: utf-8 -*-
"""Windows 电源计划：读当前、列全部、切过去。

一律用 GUID 定位，不用名字 —— 中文系统叫「高性能」，英文系统叫 High performance，
用户还能自己新建并改名，只有 GUID 是稳的。

坑（spec.py 里踩过一次）：powercfg 输出是 GBK，按 utf-8 解会抛 UnicodeDecodeError，
所以这里统一 capture_output 拿 bytes 再依次试编码。
"""

from __future__ import annotations

import re
import subprocess
from typing import List, Tuple

# 内置四档的固定 GUID，跟系统语言无关
KNOWN = {
    "节能": "a1841308-3541-4fab-bc81-f71556f20b4a",
    "平衡": "381b4222-f694-41f0-9685-ff5bb260df2e",
    "高性能": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
    "卓越性能": "e9a42b02-d5df-448d-aa00-03f14749eb61",
}
MODE_ORDER = ("节能", "平衡", "高性能", "卓越性能")

GUID_RE = re.compile(r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")
NAME_RE = re.compile(r"\(([^()]*)\)")


def _decode(data: bytes) -> str:
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", "ignore")


def _run(args: List[str]) -> str:
    try:
        out = subprocess.run(
            ["powercfg"] + args,
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return _decode(out.stdout or b"")


def list_plans() -> List[Tuple[str, str, bool]]:
    """返回 [(guid, 名字, 是否当前), ...]，按内置顺序优先排列。"""
    text = _run(["/list"])
    plans: List[Tuple[str, str, bool]] = []
    for line in text.splitlines():
        gid = GUID_RE.search(line)
        if not gid:
            continue
        found = NAME_RE.findall(line)
        name = found[-1].strip() if found else ""
        plans.append((gid.group(1).lower(), name or gid.group(1)[:8], "*" in line))
    return plans


def current() -> Tuple[str, str]:
    """返回 (guid, 名字)；读不到就给空。"""
    text = _run(["/getactivescheme"])
    gid = GUID_RE.search(text)
    if not gid:
        return "", ""
    found = NAME_RE.findall(text)
    name = found[-1].strip() if found else ""
    return gid.group(1).lower(), name


def set_active(guid: str) -> Tuple[bool, str]:
    """切到指定计划。成功返回 (True, 名字)。"""
    guid = str(guid or "").strip()
    if not GUID_RE.fullmatch(guid):
        return False, "GUID 不对"
    try:
        out = subprocess.run(
            ["powercfg", "/setactive", guid],
            capture_output=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)
    if out.returncode == 0:
        gid, name = current()
        return True, name or "已切换"
    return False, _decode(out.stderr or b"").strip() or "切换失败"


def find_known(guid_map: dict) -> List[Tuple[str, str]]:
    """从系统实际存在的计划里，挑出内置四档可用的，返回 [(名字, guid)]。"""
    alive = {g for g, _, _ in list_plans()}
    result = []
    for name in MODE_ORDER:
        gid = KNOWN[name]
        if gid in alive:
            result.append((name, gid))
    return result
