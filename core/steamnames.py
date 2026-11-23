"""商店公开接口补名字。

本地只有「装了的」和「玩过的」知道叫什么，库里没装的那一堆只有 AppID。
这里按 AppID 问一次 Steam 商店的公开接口（不需要 key、不需要登录），
结果缓存在包内的 steam_names.json，下次直接读，不再联网。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

API = "https://store.steampowered.com/api/appdetails?appids=%s&l=schinese&filters=basic"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
NO_NAME = "商品页没这个名字"


def cache_file() -> Path:
    try:
        from core.store import app_dir

        return Path(app_dir()) / "steam_names.json"
    except Exception:  # noqa: BLE001
        return Path("steam_names.json")


def load() -> dict:
    try:
        data = json.loads(cache_file().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def save(names: dict) -> None:
    try:
        cache_file().write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        log.warning("写 steam_names.json 失败：%s", exc)


def fetch_name(appid: str, timeout: float = 6.0) -> str:
    """成功返回名字；接口不通返回空串（下次再试）；确实没有这个商品返回 NO_NAME。"""
    import urllib.request

    try:
        req = urllib.request.Request(API % appid, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = json.loads(r.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001
        return ""

    node = payload.get(str(appid)) or {}
    if not node.get("success"):
        return NO_NAME
    data = node.get("data") or {}
    name = str(data.get("name") or "").strip()
    return name or NO_NAME
