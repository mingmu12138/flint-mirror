"""酷我音乐接口层：搜索 + 取播放地址。

搜索走 search.kuwo.cn 的老接口，返回体是单引号的伪 JSON，要清洗一遍。
取流走 antiserver 的 convert_url，匿名就能拿到 128k mp3 直链，不用登录。
封面用搜索结果里的 web_albumpic_short 拼 img1.kuwo.cn。
"""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
SEARCH = "http://search.kuwo.cn/r.s"
ANTI = "http://antiserver.kuwo.cn/anti.s"
COVER = "https://img1.kuwo.cn/star/albumcover/%s"


def _clean(text: str) -> str:
    t = str(text or "")
    t = t.replace("\\u0026", "&").replace("&nbsp;", " ").replace("&amp;", "&")
    t = t.replace("&quot;", '"')
    t = re.sub(r"\s+", " ", t)
    return t.strip()


def _dur_ms(v) -> int:
    """酷我网页接口的时长可能是 "3:20" 也可能是秒数。"""
    s = str(v or "")
    try:
        if ":" in s:
            mm, ss = s.split(":", 1)
            return int(float(mm) * 60000 + float(ss) * 1000)
        return int(float(s) * 1000)
    except Exception:  # noqa: BLE001
        return 0


def _track(it: dict) -> Dict:
    rid = str(it.get("MUSICRID") or "")
    short = str(it.get("web_albumpic_short") or "")
    cover = (COVER % short) if short else ""
    return {
        "id": rid,
        "name": _clean(it.get("SONGNAME")) or "未知",
        "artist": _clean(it.get("ARTIST")) or "—",
        "album": _clean(it.get("ALBUM")),
        "dur": int(float(it.get("DURATION") or 0) * 1000),
        "cover": cover,
        "src": "kw",
    }


class KW:
    """酷我：不用登录，128k 免费听，收费歌 autiserver 不给直链就标 VIP。"""

    def __init__(self, store: Path):
        self.dir = Path(store)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass
        self.nick = ""
        self.error = ""
        self.token = ""
        self.lock = threading.RLock()
        self.s = requests.Session()
        self.s.headers.update({
            "User-Agent": UA,
            "Referer": "http://www.kuwo.cn/",
        })
        self.cookie_file = self.dir / "kw_cookie.json"
        self._load()

    # ---------------- 会话 ----------------
    @property
    def logged(self) -> bool:
        return bool(self.token)

    WEB_KEYS = ("userid", "sid", "websid", "logintype", "username", "uname3", "pic3")

    def _load(self) -> None:
        try:
            if self.cookie_file.exists():
                d = json.loads(self.cookie_file.read_text("utf-8"))
                web = d.get("web") or {}
                if web:
                    self._apply_web(web)
                if d.get("token") and not self.token:
                    self._apply(d.get("token") or "")
        except Exception as exc:  # noqa: BLE001
            self.error = "读 cookie 失败：%s" % exc

    def _apply_web(self, ck: dict) -> None:
        """网页版登录态：身份靠 userid，会话靠 sid/websid。"""
        for name in self.WEB_KEYS:
            val = str((ck or {}).get(name) or "").strip()
            if not val:
                continue
            try:
                self.s.cookies.set(name, val, domain=".kuwo.cn")
            except Exception:  # noqa: BLE001
                pass
        uid = str((ck or {}).get("userid") or "").strip()
        if uid:
            self.token = uid
            nick = str((ck or {}).get("uname3") or (ck or {}).get("username") or "").strip()
            self.nick = nick or "酷我已登录"

    def set_web(self, ck: dict) -> Dict:
        """从网页登录窗收来的 cookie 直接落进会话。"""
        keep = {k_: (ck or {}).get(k_) for k_ in self.WEB_KEYS if (ck or {}).get(k_)}
        with self.lock:
            self._apply_web(keep)
            ok = bool(self.token)
            if ok:
                try:
                    self.cookie_file.write_text(
                        json.dumps({"token": self.token, "web": keep}, ensure_ascii=False),
                        "utf-8",
                    )
                except Exception:  # noqa: BLE001
                    pass
            return {"ok": ok, "userid": keep.get("userid") or ""}

    def _apply(self, token: str) -> None:
        tok = str(token or "").strip()
        m = re.search(r"kw_token=([0-9a-zA-Z]+)", tok)
        if m:
            tok = m.group(1)
        self.token = tok
        if tok:
            for name in ("kw_token", "csrf"):
                try:
                    self.s.cookies.set(name, tok, domain=".kuwo.cn")
                except Exception:  # noqa: BLE001
                    pass
            self.s.headers["csrf"] = tok

    def set_cookie(self, token, _b: str = "") -> Dict:
        with self.lock:
            self._apply(token)
            ok = bool(self.token)
            if ok:
                self.nick = self.nick or "酷我已登录"
                try:
                    self.cookie_file.write_text(
                        json.dumps({"token": self.token}, ensure_ascii=False), "utf-8"
                    )
                except Exception:  # noqa: BLE001
                    pass
            return {"ok": ok}

    def logout(self) -> Dict:
        with self.lock:
            self.token = ""
            self.nick = ""
            self.s.headers.pop("csrf", None)
            try:
                self.cookie_file.unlink()
            except Exception:  # noqa: BLE001
                pass
            self.s.cookies.clear()
            return {"ok": True}

    # ---------------- 数据 ----------------
    def search(self, kw: str, limit: int = 30) -> List[Dict]:
        try:
            r = self.s.get(SEARCH, timeout=12, params={
                "all": kw, "ft": "music", "itemset": "web_2013", "client": "kt",
                "pn": 0, "rn": limit, "rformat": "json", "encoding": "utf8",
            })
            text = r.text or ""
            try:
                data = json.loads(text)
            except Exception:  # noqa: BLE001
                data = json.loads(text.replace("'", '"'))
            items = data.get("abslist") or []
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            return []
        res = [_track(it) for it in items if it.get("MUSICRID")]
        if res:
            playable = self.vurls([t["id"] for t in res])
            for t in res:
                t["vip"] = not bool(playable.get(t["id"]))
        return res

    def _playurl(self, rid: str) -> str:
        """登录后才走得通的高码率接口，失败就交给 antiserver 兜底。"""
        mid = str(rid).replace("MUSIC_", "")
        try:
            r = self.s.get("http://www.kuwo.cn/api/v1/www/music/playUrl",
                           timeout=10, params={"mid": mid, "type": "music",
                                               "httpsStatus": 1})
            d = r.json()
            if d.get("success"):
                u = (d.get("data") or {}).get("url") or ""
                return u if u.startswith("http") else ""
        except Exception:  # noqa: BLE001
            pass
        return ""

    def _one_url(self, rid: str) -> str:
        if self.token:
            u = self._playurl(rid)
            if u:
                return u
        try:
            r = self.s.get(ANTI, timeout=10, params={
                "type": "convert_url", "rid": rid, "format": "mp3",
                "response": "url",
            })
            u = (r.text or "").strip()
            return u if u.startswith("http") else ""
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            return ""

    def vurls(self, rids) -> Dict[str, str]:
        rids = [x for x in (rids or []) if x]
        if not rids:
            return {}
        out: Dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            for rid, u in zip(rids, pool.map(self._one_url, rids)):
                if u:
                    out[rid] = u
        return out

    def track_url(self, rid) -> str:
        return self._one_url(str(rid))

    can_playlists = False   # 网页口全被风控拦着，先老老实实说不支持

    def my_playlists(self) -> List[Dict]:
        return []

    def _web_track(self, it: dict) -> Dict:
        rid = it.get("rid") or it.get("musicrid") or it.get("id") or ""
        rid = ("MUSIC_%s" % rid) if str(rid).isdigit() else str(rid)
        pic = it.get("albumpic") or ""
        cover = pic if pic.startswith("http") else (
            ("https://img1.kuwo.cn/star/albumcover/%s" % pic) if pic else "")
        return {
            "id": rid,
            "name": _clean(it.get("name") or it.get("songname")),
            "artist": _clean(it.get("artist") or it.get("songername")),
            "album": _clean(it.get("album")),
            "dur": _dur_ms(it.get("duration")),
            "cover": cover,
            "src": "kw",
        }

    def recommend(self, limit: int = 30) -> List[Dict]:
        """每日推荐：登录后先走那两条给账号的接口，不行再退回热歌。

        酷我网页版现在用的是另一套签名（reqId 那套），第三方带登录 cookie 请求
        api/www 一律回 illegal，所以必须留一条兜底，否则登录了推荐还是空白。
        """
        res = self._recommend_api(limit)
        if res:
            return res
        return self._hot_fallback(limit)

    HOT_WORDS = ("周杰伦", "林俊杰", "邓紫棋", "薛之谦", "陈奕迅", "李荣浩", "毛不易", "张杰")

    def _hot_fallback(self, limit: int = 30) -> List[Dict]:
        """推荐接口被风控时的兜底：按热门歌手搜，凑一份像样的歌单。"""
        out: List[Dict] = []
        seen = set()
        per = max(3, limit // len(self.HOT_WORDS) + 1)
        for word in self.HOT_WORDS:
            try:
                hit = self.search(word, per)
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
                continue
            for t in hit:
                if t["id"] in seen:
                    continue
                seen.add(t["id"])
                out.append(t)
            if len(out) >= limit:
                break
        return out[:limit]

    def _recommend_api(self, limit: int = 30) -> List[Dict]:
        if not self.token:
            return []
        for url, params in (
            ("http://www.kuwo.cn/api/www/star/recommendMusic",
             {"rn": limit, "httpsStatus": 1}),
            ("http://www.kuwo.cn/api/www/bang/bang/musicList",
             {"bangId": 16, "pn": 1, "rn": limit, "httpsStatus": 1}),
        ):
            try:
                r = self.s.get(url, timeout=12, params=params)
                d = r.json() or {}
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
                continue
            if not d.get("success"):
                continue
            data = d.get("data") or {}
            lst = data.get("musicList") or data.get("musiclist") or []
            if not lst and data.get("list"):
                lst = data.get("list")
            res = [self._web_track(x) for x in lst]
            res = [t for t in res if t["id"] and t["name"]]
            if res:
                urls = self.vurls([t["id"] for t in res])
                for t in res:
                    t["vip"] = not bool(urls.get(t["id"]))
                return res[:limit]
        return []
