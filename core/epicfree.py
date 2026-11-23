"""Epic 每周免费游戏：读官方公开的免费促销接口，只负责"看见"和"跳转"。

领取还是要在网页/客户端里点，这里不做代领 —— 那需要登录态，也不该碰用户的账号。
"""

from __future__ import annotations

import json
import logging
import urllib.request
from datetime import datetime, timezone
from typing import Dict, List

log = logging.getLogger(__name__)

ENDPOINT = (
    "https://store-site-backend-static.ak.epicgames.com/freeGamesPromotions"
    "?locale=%s&country=%s&allowCountries=%s"
)
STORE = "https://store.epicgames.com/zh-CN/p/%s"


def _get_iso(t: str) -> datetime | None:
    if not t:
        return None
    try:
        return datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except ValueError:
        return None


def _local(t: str) -> str:
    """UTC 的 ISO 换成本机时间，给卡片直接显示。"""
    dt = _get_iso(t)
    if dt is None:
        return ""
    try:
        dt = dt.astimezone()
    except (OSError, ValueError):
        pass
    return dt.strftime("%m月%d日 %H:%M")


def _page_slug(e: dict) -> str:
    p = str(e.get("productSlug") or "").strip()
    if p:
        return p.split("/")[0]
    for m in (e.get("catalogNs") or {}).get("mappings") or []:
        if isinstance(m, dict) and m.get("pageSlug"):
            return str(m["pageSlug"])
    for m in e.get("offerMappings") or []:
        if isinstance(m, dict) and m.get("pageSlug"):
            return str(m["pageSlug"])
    return str(e.get("urlSlug") or "").strip()


def _image(e: dict) -> str:
    imgs = e.get("keyImages") or []
    for want in ("OfferImageWide", "Thumbnail", "OfferImageTall", "featuredMedia"):
        for i in imgs:
            if isinstance(i, dict) and i.get("type") == want and i.get("url"):
                return str(i["url"])
    for i in imgs:
        if isinstance(i, dict) and i.get("url"):
            return str(i["url"])
    return ""


def _price(e: dict) -> str:
    tp = (e.get("price") or {}).get("totalPrice") or {}
    fmt = str((tp.get("fmtPrice") or {}).get("originalPrice") or "").strip()
    return "" if fmt in ("0", "¥0.00", "¥0", "0.00") else fmt


def _item(e: dict, mode: str, start: str, end: str) -> Dict[str, str]:
    slug = _page_slug(e)
    return {
        "title": str(e.get("title") or "未命名"),
        "desc": str(e.get("description") or "").strip(),
        "slug": slug,
        "url": (STORE % slug) if slug else str(e.get("url") or ""),
        "image": _image(e),
        "price": _price(e),
        "start": start,
        "end": end,
        "start_local": _local(start),
        "end_local": _local(end),
        "mode": mode,   # now / soon
    }


def fetch(locale: str = "zh-CN", country: str = "CN", timeout: int = 15) -> Dict[str, object]:
    """返回 {"now": [...], "soon": [...], "error": ""}，失败也把 error 带回界面。"""
    out: Dict[str, object] = {"now": [], "soon": [], "error": ""}
    url = ENDPOINT % (locale, country, country)
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                "Accept": "application/json",
            },
        )
        raw = urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8")
        data = json.loads(raw)
        els = (((data.get("data") or {}).get("Catalog") or {}).get("searchStore") or {}).get("elements") or []
    except Exception as exc:  # noqa: BLE001
        log.warning("Epic 免费接口拉取失败：%s", exc)
        out["error"] = f"没拉到 Epic 的免费列表：{exc}"
        return out

    now_at = datetime.now(timezone.utc)
    now_list: List[Dict[str, str]] = []
    soon_list: List[Dict[str, str]] = []

    for e in els:
        if not isinstance(e, dict):
            continue
        pr = e.get("promotions") or {}
        for blk in pr.get("promotionalOffers") or []:
            rules = (blk or {}).get("promotionalOffers") or []
            for r in rules:
                if not isinstance(r, dict):
                    continue
                pct = ((r.get("discountSetting") or {}).get("discountPercentage"))
                start, end = str(r.get("startDate") or ""), str(r.get("endDate") or "")
                s_dt, e_dt = _get_iso(start), _get_iso(end)
                live = (s_dt is None or s_dt <= now_at) and (e_dt is None or e_dt > now_at)
                # 只认真正 0 折的那档，别的促销不当免费
                if pct not in (0, "0", None) or not live:
                    continue
                now_list.append(_item(e, "now", start, end))

        for blk in pr.get("upcomingPromotionalOffers") or []:
            rules = (blk or {}).get("promotionalOffers") or []
            for r in rules:
                if not isinstance(r, dict):
                    continue
                pct = ((r.get("discountSetting") or {}).get("discountPercentage"))
                if pct not in (0, "0", None):
                    continue
                soon_list.append(_item(e, "soon", str(r.get("startDate") or ""), str(r.get("endDate") or "")))

    # 同款在上面两个循环里重复加入的情况去掉
    def dedup(lst: List[Dict[str, str]]) -> List[Dict[str, str]]:
        seen, out_l = set(), []
        for it in lst:
            key = (it["slug"] or it["title"], it["mode"])
            if key in seen:
                continue
            seen.add(key)
            out_l.append(it)
        return out_l

    out["now"] = dedup(now_list)
    out["soon"] = sorted(dedup(soon_list), key=lambda x: x["start"] or "9999")
    if not out["now"] and not out["soon"] and not out["error"]:
        out["error"] = "这一档没有免费游戏（接口正常）"
    return out
