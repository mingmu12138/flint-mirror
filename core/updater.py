"""本地升级助手（不联网、不下载）。

分发走网盘：用户自己把安装包下到本机，这里只负责三件事：

1. 扫「程序目录」「下载」「桌面」和用户自己指定的目录，找出像我们自己安装包的文件；
2. 读它的版本资源（不看文件名，改不改名都认得出），跟当前版本逐位比较；
3. 交给安装器去装 —— 配置和素材由安装器那边保住。

不联网、不上传、不静默下载，用户全程自己掌控。
"""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# 安装包里的 ProductName / FileDescription 会带上这个字，用来确认"是我们自己的包"
PRODUCT_WORD = "燧镜"

_VER = ctypes.WinDLL("version", use_last_error=True)


# ---------------------------------------------------------------------------
# 版本号
# ---------------------------------------------------------------------------
def parse_version(value) -> Tuple[int, ...]:
    """'1.1.0' / 'v1.1.0.0' / '1.1.0-beta' → (1, 1, 0, 0)。

    按数字逐位比较，绝不按字符串比 —— 否则 1.10 会小于 1.9。
    """
    nums = re.findall(r"\d+", str(value or ""))
    if not nums:
        return ()
    return tuple(int(n) for n in nums[:4])


def vstr(t: Tuple[int, ...]) -> str:
    return ".".join(str(x) for x in (t or ()))


def is_newer(a, b) -> bool:
    """a 比 b 新吗？位数不足按 0 补齐。"""
    ta, tb = parse_version(a), parse_version(b)
    if not ta or not tb:
        return False
    n = max(len(ta), len(tb))
    ta = ta + (0,) * (n - len(ta))
    tb = tb + (0,) * (n - len(tb))
    return ta > tb


# ---------------------------------------------------------------------------
# 读 exe 的版本资源
# ---------------------------------------------------------------------------
def _query(path: str) -> Dict[str, str]:
    """返回 {version, product, desc}；读不到就是空串。"""
    out = {"version": "", "product": "", "desc": ""}
    try:
        size = _VER.GetFileVersionInfoSizeW(str(path), None)
        if not size:
            return out
        buf = ctypes.create_string_buffer(size)
        if not _VER.GetFileVersionInfoW(str(path), 0, size, buf):
            return out

        ptr = ctypes.c_void_p()
        ln = ctypes.c_uint()

        # 1) 固定信息里的版本号：MS/LS 各是两个 WORD
        if _VER.VerQueryValueW(buf, "\\", ctypes.byref(ptr), ctypes.byref(ln)) and ptr.value:
            fixed = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint32 * 4)).contents
            ms, ls = fixed[2], fixed[3]
            out["version"] = "%d.%d.%d.%d" % (
                (ms >> 16) & 0xFFFF,
                ms & 0xFFFF,
                (ls >> 16) & 0xFFFF,
                ls & 0xFFFF,
            )

        # 2) 语言/代码页，用来拼字符串表的 key
        if _VER.VerQueryValueW(
            buf, "\\VarFileInfo\\Translation", ctypes.byref(ptr), ctypes.byref(ln)
        ) and ptr.value:
            pair = ctypes.cast(ptr, ctypes.POINTER(ctypes.c_uint16 * 2)).contents
            code = "%04x%04x" % (pair[0], pair[1])
            for key, field in (
                ("FileVersion", "version"),
                ("ProductName", "product"),
                ("FileDescription", "desc"),
            ):
                if (
                    _VER.VerQueryValueW(
                        buf,
                        "\\StringFileInfo\\%s\\%s" % (code, key),
                        ctypes.byref(ptr),
                        ctypes.byref(ln),
                    )
                    and ptr.value
                ):
                    text = ctypes.wstring_at(ptr.value) or ""
                    if text.strip():
                        out[field] = text.strip()
    except Exception:  # noqa: BLE001
        return out
    return out


def file_info(path: str) -> Dict[str, object]:
    """读一个文件的版本信息 + 大小/时间。"""
    p = Path(path)
    info: Dict[str, object] = {"path": str(p), "version": "", "product": "", "desc": ""}
    try:
        st = p.stat()
        info["size"] = st.st_size
        info["mb"] = st.st_size / 1048576
        info["mtime"] = time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime))
    except OSError:
        info["size"] = 0
        info["mb"] = 0.0
        info["mtime"] = "—"
    info.update(_query(str(p)))
    return info


def looks_like_ours(info: Dict[str, object]) -> bool:
    """是不是我们自己的安装包：产品名/描述里带「燧镜」，且版本号读得出来。"""
    text = "%s %s" % (info.get("product") or "", info.get("desc") or "")
    return (PRODUCT_WORD in text) and bool(info.get("version"))


# ---------------------------------------------------------------------------
# 扫目录
# ---------------------------------------------------------------------------
def default_dirs() -> List[str]:
    """默认看哪几个地方。"""
    dirs: List[str] = []
    try:
        from core.store import app_dir

        dirs.append(str(app_dir()))
    except Exception:  # noqa: BLE001
        if getattr(sys, "frozen", False):
            dirs.append(str(Path(sys.executable).resolve().parent))
    home = Path(os.path.expanduser("~"))
    dirs.append(str(home / "Downloads"))
    dirs.append(str(home / "Desktop"))
    return [d for d in dirs if d and Path(d).is_dir()]


def scan(current_version: str, extra_dir: str = "") -> List[Dict[str, object]]:
    """在默认目录 + 自选目录里找比当前版本新的安装包，按版本从新到旧。"""
    dirs = default_dirs()
    if extra_dir and Path(extra_dir).is_dir():
        dirs.insert(0, str(Path(extra_dir)))
    found: List[Dict[str, object]] = []
    seen = set()
    for d in dirs:
        try:
            entries = sorted(Path(d).glob("*.exe"))
        except OSError:
            continue
        for f in entries:
            key = str(f).lower()
            if key in seen:
                continue
            seen.add(key)
            try:
                if not f.is_file():
                    continue
            except OSError:
                continue
            info = file_info(str(f))
            if not looks_like_ours(info):
                continue
            if not is_newer(info.get("version") or "", current_version):
                continue
            found.append(info)
    found.sort(key=lambda i: parse_version(i.get("version") or ""), reverse=True)
    return found


# ---------------------------------------------------------------------------
# 安装
# ---------------------------------------------------------------------------
def launch_installer(path: str, silent: bool = True) -> Tuple[bool, str]:
    """拉起安装包。silent=True 走 /S，装完安装器会自己把新程序打开。"""
    p = Path(path)
    if not p.exists():
        return (False, "安装包不在了：" + str(p))
    args = [str(p)]
    if silent:
        args.append("/S")
        # /UPDATING：告诉安装器"这是一次升级"，装完自动把新版本拉起来
        args.append("/UPDATING")
    try:
        # DETACHED_PROCESS：让安装器彻底脱离燧镜.exe。
        # 否则它是子进程，安装时杀 燧镜.exe 可能把它自己一起带走（装到一半就没了）。
        flags = 0
        if hasattr(subprocess, "DETACHED_PROCESS"):
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            args, cwd=str(p.parent), close_fds=True, creationflags=flags
        )
    except OSError as exc:
        return (False, "打不开安装包：" + str(exc))
    return (True, "安装程序已启动，燧镜马上会自动关掉并更新")
