"""Steam 账号维度：从本地登录记录认出账号，再算自己的库存和游玩时长。

不联网、不要 API Key。数据来源只有两份本地文件：
  config/loginusers.vdf                          —— 这台机器登录过的账号、名字、最近使用
  userdata/<accountid>/config/localconfig.vdf    —— 该账号的 apps（Playtime 单位是分钟）
"""

from __future__ import annotations

import io
import logging
from pathlib import Path
from typing import Dict, List, Optional

from core.steamlib import parse_vdf, steam_dir

log = logging.getLogger(__name__)

BASE64_DELTA = 76561197960265728


def to_accountid(steamid64: str) -> str:
    try:
        return str(int(str(steamid64).strip()) - BASE64_DELTA)
    except (TypeError, ValueError):
        return ""


def to_steamid64(accountid: str) -> str:
    try:
        return str(int(str(accountid).strip()) + BASE64_DELTA)
    except (TypeError, ValueError):
        return ""


def _read(path: Path) -> Dict[str, object]:
    try:
        txt = io.open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return {}
    return parse_vdf(txt)


def login_users(root: Optional[Path] = None) -> List[Dict[str, object]]:
    """登录过这台机器的账号，AutoLogin 的排最前，其余按最近使用排序。"""
    root = root or steam_dir()
    if root is None:
        return []
    data = _read(Path(root) / "config" / "loginusers.vdf")
    users = data.get("users") or {}
    if not isinstance(users, dict):
        return []

    out: List[Dict[str, object]] = []
    for sid, v in users.items():
        if not str(sid).isdigit() or not isinstance(v, dict):
            continue
        out.append(
            {
                "steamid64": str(sid),
                "accountid": to_accountid(str(sid)),
                "account": str(v.get("AccountName") or ""),
                "persona": str(v.get("PersonaName") or "") or str(v.get("AccountName") or sid),
                "autologin": str(v.get("AutoLogin") or "") == "1",
                "timestamp": int(str(v.get("timestamp") or "0") or 0),
            }
        )
    out.sort(key=lambda a: (not a["autologin"], -int(a["timestamp"])))
    return out


def active_account(root: Optional[Path] = None, users: Optional[List[Dict[str, object]]] = None) -> \
        Optional[Dict[str, object]]:
    """现在是谁：先问注册表里 Steam 记的活动用户，认不出来就取登录列表第一个。"""
    users = users if users is not None else login_users(root)

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam\ActiveProcess") as k:
            aid = int(winreg.QueryValueEx(k, "ActiveUser")[0])
    except Exception:  # noqa: BLE001
        aid = 0
    if aid:
        sid = to_steamid64(str(aid))
        for u in users:
            if u["steamid64"] == sid:
                return u
        return {
            "steamid64": sid,
            "accountid": str(aid),
            "account": "",
            "persona": f"账号 {aid}",
            "autologin": False,
            "timestamp": 0,
        }

    return users[0] if users else None


def stats(root: Optional[Path] = None, accountid: str = "") -> Dict[str, int]:
    """某账号的库存数和总时长；文件不在就给 0。"""
    root = root or steam_dir()
    out = {"apps": 0, "played": 0, "minutes": 0, "appids": [], "items": {}}
    if root is None or not accountid:
        return out
    p = Path(root) / "userdata" / str(accountid) / "config" / "localconfig.vdf"
    if not p.is_file():
        return out

    data = _read(p)
    store = data.get("UserLocalConfigStore") or {}
    steam = ((store.get("Software") or {}).get("Valve") or {}).get("Steam") or {}
    apps = steam.get("apps") or {}
    if not isinstance(apps, dict):
        return out

    out["items"] = {}
    mins = 0
    for aid, v in apps.items():
        key = str(aid)
        if not key.isdigit() or int(key) <= 0 or not isinstance(v, dict):
            continue
        out["appids"].append(key)
        pt = 0
        if v.get("Playtime"):
            try:
                pt = int(str(v["Playtime"]).strip())
            except ValueError:
                pt = 0
        lp = 0
        if v.get("LastPlayed"):
            try:
                lp = int(str(v["LastPlayed"]).strip())
            except ValueError:
                lp = 0
        out["items"][key] = {"playtime": pt, "last": lp}
        if pt:
            mins += pt
            out["played"] += 1
    out["apps"] = len(out["appids"])
    out["minutes"] = mins
    return out


def snapshot(root: Optional[Path] = None, accountid: str = "") -> Dict[str, object]:
    users = login_users(root)
    cur = active_account(root, users)
    if accountid:
        for u in users:
            if u["accountid"] == str(accountid):
                cur = u
                break
    st = stats(root, str(cur["accountid"])) if cur else {"apps": 0, "played": 0, "minutes": 0}
    return {"accounts": users, "current": cur, "stats": st}
