"""本机已装三方工具的探测。

只做只读的事：读注册表卸载表、几个常见目录，看看这几个推荐工具是不是
已经装在这台机器上。认出来了就返回可执行文件路径，交给 store 把那条
「三方工具」升级成本地工具（点一下直接启动）。

认不出来不算错：用户可能真没装，或者装在了非常规目录 —— 那就继续挂官网入口。
"""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

try:
    import winreg  # type: ignore
except ImportError:  # 非 Windows 直接不探测
    winreg = None  # type: ignore

UNINSTALL_ROOTS = (
    (0x80000002, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),  # HKLM
    (0x80000002, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    (0x80000001, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),  # HKCU
)


def _read_uninstall() -> List[Dict[str, str]]:
    """把三处卸载表里的条目摊平成 dict 列表。"""
    rows: List[Dict[str, str]] = []
    if winreg is None:
        return rows
    for hive, key_path in UNINSTALL_ROOTS:
        try:
            key = winreg.OpenKey(hive, key_path)
        except OSError:
            continue
        count = 0
        try:
            count = winreg.QueryInfoKey(key)[0]
        except OSError:
            count = 0
        for i in range(count):
            try:
                sub = winreg.EnumKey(key, i)
            except OSError:
                continue
            try:
                sk = winreg.OpenKey(key, sub)
            except OSError:
                continue
            row: Dict[str, str] = {}
            for field, name in (
                ("name", "DisplayName"),
                ("loc", "InstallLocation"),
                ("icon", "DisplayIcon"),
            ):
                try:
                    val, _t = winreg.QueryValueEx(sk, name)
                    row[field] = str(val or "")
                except OSError:
                    row[field] = ""
            try:
                sk.Close()
            except OSError:
                pass
            if row.get("name"):
                rows.append(row)
        try:
            key.Close()
        except OSError:
            pass
    return rows


def _expand(p: str) -> str:
    return os.path.expandvars(os.path.expanduser(p or "").strip().strip('"'))


def _find_exe(root: Path, patterns: Iterable[str], depth: int = 2) -> str:
    """在 root 下按文件名通配找可执行文件，最多下潜 depth 层。"""
    if not root.is_dir():
        return ""
    root_s = str(root)
    pats = tuple(p.lower() for p in patterns)
    best = ""
    for dirpath, dirnames, filenames in os.walk(root_s):
        rel = os.path.relpath(dirpath, root_s)
        level = 0 if rel in (".", "") else rel.count(os.sep) + 1
        if level >= depth:
            dirnames[:] = []
        for fn in filenames:
            low = fn.lower()
            if not low.endswith(".exe"):
                continue
            if any(fnmatch.fnmatch(low, p) for p in pats):
                full = os.path.join(dirpath, fn)
                # 同一个名字出现多个版本目录时，挑最新的那个（app-0.112.0 > app-0.111.0）
                if not best or full.lower() > best.lower():
                    best = full
    return best


def _roots_from_uninstall(records: List[Dict[str, str]], pattern: str) -> List[str]:
    """按 DisplayName 正则从卸载表里取安装目录。"""
    try:
        rx = re.compile(pattern, re.I)
    except re.error:
        return []
    out: List[str] = []
    for r in records:
        if not rx.search(r.get("name", "")):
            continue
        loc = _expand(r.get("loc", ""))
        if loc and Path(loc).is_dir():
            out.append(loc)
        icon = _expand(r.get("icon", "")).split(",")[0]
        if icon:
            d = str(Path(icon).parent)
            if Path(d).is_dir() and d not in out:
                out.append(d)
    return out


def _drive_roots() -> List[Path]:
    """所有能用的盘根。A/B 基本是软驱，跳过，免得卡住。"""
    roots: List[Path] = []
    for letter in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        p = Path(f"{letter}:\\")
        try:
            if p.exists():
                roots.append(p)
        except OSError:
            continue
    return roots


def _matching_dirs(root: Path, patterns: Iterable[str]) -> List[str]:
    """只看下一层，目录名对上就收 —— 不递归，几毫秒的事。"""
    pats = tuple(p.lower() for p in patterns)
    out: List[str] = []
    try:
        for e in root.iterdir():
            if not e.is_dir():
                continue
            if any(fnmatch.fnmatch(e.name.lower(), p) for p in pats):
                out.append(str(e))
    except OSError:
        return out
    return out


def _loose_dirs(name_patterns: Iterable[str]) -> List[str]:
    """没有注册表的绿色包：各盘根 / 桌面 / 下载 只翻一层找同名目录。"""
    spots = list(_drive_roots())
    for env in (r"%USERPROFILE%\Desktop", r"%USERPROFILE%\Downloads",
                r"%USERPROFILE%\Documents", r"%LOCALAPPDATA%\Programs",
                r"%ProgramFiles%", r"%ProgramFiles(x86)%"):
        d = Path(_expand(env))
        if d.is_dir():
            spots.append(d)
    out: List[str] = []
    for spot in spots:
        for hit in _matching_dirs(spot, name_patterns):
            if hit not in out:
                out.append(hit)
    return out


# (显示名, 卸载表匹配, exe 通配, 固定目录, 固定相对子目录, 绿色包目录名通配)
SPECS: Tuple[Tuple[str, str, Tuple[str, ...], Tuple[str, ...], Tuple[str, ...], Tuple[str, ...]], ...] = (
    ("Steam", r"^steam$", ("steam.exe",),
     (r"%ProgramFiles(x86)%\Steam", r"%ProgramFiles%\Steam"), (), ()),
    ("Epic Games", r"epic games launcher", ("epicgameslauncher.exe",),
     (r"%ProgramFiles(x86)%\Epic Games", r"%ProgramFiles%\Epic Games"),
     (r"Launcher\Portal\Binaries\Win64", r"Launcher\Portal\Binaries\Win32"), ()),
    ("KOOK", r"^kook$", ("kook.exe",),
     (r"%LOCALAPPDATA%\Programs\KOOK", r"%ProgramFiles%\KOOK"), (), ()),
    ("OOPZ", r"^oopz$", ("oopz.exe",),
     (r"%LOCALAPPDATA%\Programs\OOPZ", r"%ProgramFiles%\OOPZ"), (), ()),
    ("图吧工具箱", r"图吧", ("图吧工具箱*.exe", "*工具箱*.exe"),
     (), (), ("图吧*", "*工具箱*")),
    ("PCL2 启动器", r"pcl|plain craft", ("pcl.exe", "pcl2*.exe", "plain craft launcher*.exe"),
     (), (), ("pcl*", "plain craft*")),
    ("飞鼠格式", r"飞鼠", ("飞鼠格式*.exe", "flyingmouse*.exe", "飞鼠*.exe"),
     (), (), ("飞鼠*", "flyingmouse*")),
)


def _steam_from_registry() -> str:
    """Steam 有个现成的 SteamPath，比翻卸载表准。"""
    if winreg is None:
        return ""
    try:
        with winreg.OpenKey(0x80000001, r"Software\Valve\Steam") as k:
            val, _t = winreg.QueryValueEx(k, "SteamPath")
            p = Path(_expand(str(val)))
            exe = p / "steam.exe"
            if exe.exists():
                return str(exe)
    except OSError:
        return ""
    return ""


def detect_installed(names: Iterable[str] | None = None) -> Dict[str, str]:
    """返回 {显示名: exe 绝对路径}，只含真找到了的。"""
    wanted = set(names) if names else None
    records = _read_uninstall()
    out: Dict[str, str] = {}
    for name, rx, exes, extra_dirs, subs, loose in SPECS:
        if wanted is not None and name not in wanted:
            continue
        found = ""
        if name == "Steam":
            found = _steam_from_registry()
        roots: List[str] = []
        if not found:
            roots = _roots_from_uninstall(records, rx)
            for d in extra_dirs:
                d2 = _expand(d)
                if Path(d2).is_dir() and d2 not in roots:
                    roots.append(d2)
            # 先按"根目录 + 固定子目录"找（Epic 的启动器埋得深）
            for r in roots:
                for sub in subs:
                    cand = Path(r) / sub.replace("\\", os.sep)
                    found = _find_exe(cand, exes, depth=1)
                    if found:
                        break
                if found:
                    break
            # 再在整个根目录下浅扫一层
            if not found:
                for r in roots:
                    found = _find_exe(Path(r), exes, depth=2)
                    if found:
                        break
            # 绿色包没有注册表：各盘根 / 桌面 / 下载里按目录名认
            if not found and loose:
                for d in _loose_dirs(loose):
                    found = _find_exe(Path(d), exes, depth=3)
                    if found:
                        break
        if found and Path(found).exists():
            out[name] = str(Path(found))
    return out
