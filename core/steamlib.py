"""Steam 本地台账：只读 libraryfolders.vdf 和 appmanifest_*.acf。

不联网、不启动 Steam、不改任何文件，纯粹把"这台机器上装了哪些游戏、
占了多少、装在哪个盘"读出来。
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Dict, List, Optional

log = logging.getLogger(__name__)

STEAM_APP = "https://store.steampowered.com/app/%s/"
COVER_CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps/%s/header.jpg"
RUN_PREFIX = "steam://rungameid/%s"


# ---------------------------------------------------------------------------
# Valve KeyValues 解析：只认 "键" "值" 和 "键" { ... }，容错为主
# ---------------------------------------------------------------------------
class _KV:
    def __init__(self, text: str):
        self.s = text
        self.i = 0
        self.n = len(text)

    def _ws(self) -> None:
        while self.i < self.n and self.s[self.i] in " \t\r\n":
            self.i += 1

    def _string(self) -> str:
        """读一个带引号的字符串，i 指向开引号之后。"""
        buf = []
        while self.i < self.n:
            ch = self.s[self.i]
            if ch == "\\" and self.i + 1 < self.n:
                buf.append(self.s[self.i + 1])
                self.i += 2
                continue
            if ch == '"':
                self.i += 1
                break
            buf.append(ch)
            self.i += 1
        return "".join(buf)

    def block(self) -> Dict[str, object]:
        d: Dict[str, object] = {}
        while True:
            self._ws()
            if self.i >= self.n:
                break
            ch = self.s[self.i]
            if ch == "}":
                self.i += 1
                break
            if ch != '"':
                self.i += 1
                continue
            self.i += 1
            key = self._string()
            self._ws()
            if self.i >= self.n:
                d[key] = ""
                break
            if self.s[self.i] == "{":
                self.i += 1
                d[key] = self.block()
            elif self.s[self.i] == '"':
                self.i += 1
                d[key] = self._string()
            else:
                j = self.i
                while self.i < self.n and self.s[self.i] not in '\r\n}"{':
                    self.i += 1
                d[key] = self.s[j:self.i].strip()
        return d


def parse_vdf(text: str) -> Dict[str, object]:
    """解析一份 vdf / acf，返回最外层字典（通常是单键包一层）。"""
    try:
        return _KV(text).block()
    except Exception as exc:  # noqa: BLE001
        log.warning("vdf 解析失败：%s", exc)
        return {}


# ---------------------------------------------------------------------------
# 定位 Steam
# ---------------------------------------------------------------------------
def steam_dir() -> Optional[Path]:
    """先查注册表，再猜两个常见位置。"""
    try:
        import winreg

        for root, key in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
        ):
            try:
                with winreg.OpenKey(root, key) as k:
                    for name in ("SteamPath", "InstallPath"):
                        try:
                            p = winreg.QueryValueEx(k, name)[0]
                        except OSError:
                            continue
                        cand = Path(str(p).replace("/", "\\"))
                        if (cand / "steamapps").is_dir():
                            return cand
            except OSError:
                continue
    except Exception:  # noqa: BLE001
        pass

    for cand in (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)") + r"\Steam"),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files") + r"\Steam"),
    ):
        if (cand / "steamapps").is_dir():
            return cand
    return None


def libraries(root: Optional[Path] = None) -> List[Dict[str, object]]:
    """列出所有库目录：path / 目录体积占用来自 appmanifest 自己算。"""
    root = root or steam_dir()
    if root is None:
        return []

    vdf = root / "steamapps" / "libraryfolders.vdf"
    libs: List[Dict[str, object]] = []
    if vdf.is_file():
        try:
            data = parse_vdf(vdf.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:  # noqa: BLE001
            log.warning("读 libraryfolders 失败：%s", exc)
            data = {}
        folders = data.get("libraryfolders") or data.get("LibraryFolders") or {}
        if isinstance(folders, dict):
            for k, v in folders.items():
                if not str(k).isdigit():
                    continue
                if isinstance(v, dict):
                    p = v.get("path") or v.get("Path") or ""
                else:
                    p = v
                if not p:
                    continue
                libs.append({"path": Path(str(p))})

    # 主目录自己在不在列表里都要算一份，老版本 vdf 只列追加出来的盘
    root_key = str(root).rstrip("\\").lower()
    if not any(str(l["path"]).rstrip("\\").lower() == root_key for l in libs):
        libs.insert(0, {"path": root})

    return libs


def _app_from_acf(acf: Path) -> Optional[Dict[str, object]]:
    try:
        txt = acf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    data = parse_vdf(txt)
    st = data.get("AppState") or data.get("appstate") or {}
    if not isinstance(st, dict) or not st.get("appid"):
        return None

    def num(key: str) -> int:
        try:
            return int(str(st.get(key) or "0").strip() or 0)
        except (TypeError, ValueError):
            return 0

    appid = str(st.get("appid")).strip()
    if not appid.isdigit():
        return None
    state = num("StateFlags")
    return {
        "appid": appid,
        "name": str(st.get("name") or st.get("installdir") or appid),
        "installdir": str(st.get("installdir") or ""),
        "size": num("SizeOnDisk"),
        "state": state,
        "installed": bool(state & 4),
        "lastplayed": num("LastPlayed"),
        "updated": num("LastUpdated"),
        "acf": str(acf),
    }


def snapshot(root: Optional[Path] = None) -> Dict[str, object]:
    """一次扫完，返回 {steam, libraries:[...], games:[...], total_size, installed, ...}。"""
    root = root or steam_dir()
    out: Dict[str, object] = {
        "steam": str(root) if root else "",
        "libraries": [],
        "games": [],
        "error": "",
    }
    if root is None:
        out["error"] = "没找到 Steam"
        return out

    seen: Dict[str, bool] = {}
    lib_items: List[Dict[str, object]] = []
    for lib in libraries(root):
        p = Path(str(lib["path"]))
        sa = p / "steamapps"
        item: Dict[str, object] = {"path": str(p), "exists": sa.is_dir(), "games": 0, "size": 0}
        if sa.is_dir():
            for acf in sa.glob("appmanifest_*.acf"):
                app = _app_from_acf(acf)
                if app is None or app["appid"] in seen:
                    continue
                seen[str(app["appid"])] = True
                app["library"] = str(p)
                out["games"].append(app)  # type: ignore[index]
                item["games"] = int(item["games"]) + 1
                item["size"] = int(item["size"]) + int(app["size"])
        try:
            usage = shutil.disk_usage(str(p))
            item["free"] = usage.free
            item["total"] = usage.total
        except OSError:
            item["free"] = 0
            item["total"] = 0
        lib_items.append(item)

    games: List[Dict[str, object]] = out["games"]  # type: ignore[assignment]
    out["libraries"] = lib_items
    out["total_size"] = sum(int(g["size"]) for g in games)
    out["installed"] = sum(1 for g in games if g["installed"])
    if not games:
        out["error"] = "库目录里没读到 appmanifest_*.acf"
    return out


def cover_cdn(appid: str) -> str:
    """商店封面（header.jpg，约 460×215）；个别 App 没有这张图，客户端要能接受 404。"""
    return COVER_CDN % str(appid)


def local_cover(root: Optional[Path] = None, appid: str = "") -> str:
    """Steam 客户端自己缓存过的封面，离线也能用；找不到返回空串。"""
    root = root or steam_dir()
    if root is None or not str(appid).isdigit():
        return ""
    cache = Path(root) / "appcache" / "librarycache" / str(appid)
    if not cache.is_dir():
        return ""
    for p in cache.rglob("library_header.jpg"):
        return str(p)
    return ""


def human(n: float) -> str:
    """字节换成人看的单位，步进 1024。"""
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return (f"{n:.0f} {unit}" if unit in ("B", "KB") else f"{n:.1f} {unit}")
        n /= 1024
    return "—"
