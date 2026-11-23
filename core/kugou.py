"""酷狗音乐接口层：搜索、取播放地址、cookie 登录。

不登录能听免费歌；登录（贴 userid + token）之后，有会员权限的歌才会给直链。
搜索走 mobilecdn 老接口（https 证书和域名对不上，只能 http）。
取流优先用 app 端的 getSongInfo（认 cookie），不行再回退 trackercdn v2。
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, List

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
SEARCH = "http://mobilecdn.kugou.com/api/v3/search/song"
PLAYINFO = "https://m.kugou.com/app/i/getSongInfo.php"
TRACKER = ("http://trackercdn.kugou.com/i/v2/?key=%s&hash=%s&br=hq&appid=1005"
           "&pid=2&cmd=25&behavior=play")


def _clean(text: str) -> str:
    return (text or "").replace("<em>", "").replace("</em>", "").strip()


def _track(it: dict) -> Dict:
    album_id = str(it.get("album_id") or "")
    cover = ("https://imge.kugou.com/stdmusic/240/%s.jpg" % album_id) if album_id else ""
    name = _clean(it.get("songname") or it.get("filename")) or "未知"
    artist = _clean(it.get("singername")) or ""
    if not artist and " - " in name:
        artist, name = name.split(" - ", 1)
    return {
        "id": it.get("hash") or "",
        "name": name or "未知",
        "artist": artist or "—",
        "album": _clean(it.get("album_name") or it.get("albumname")),
        "dur": int((it.get("duration") or 0) * 1000),
        "cover": cover,
        "src": "kg",
    }


def _v2_key(hash_: str) -> str:
    return hashlib.md5((hash_.lower() + "kgcloudv2").encode()).hexdigest()


class KG:
    """酷狗：匿名听免费歌，登录后能听自己有权限的歌。"""

    def __init__(self, store: Path):
        self.dir = Path(store)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass
        self.userid = ""
        self.token = ""
        self.nick = ""
        self.error = ""
        self.lock = threading.RLock()
        self.mid = uuid.uuid4().hex
        self.dfid = "1bqFBj2hycsc29gwNT4TeLEH"
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Referer": "https://www.kugou.com/"})
        self.cookie_file = self.dir / "kg_cookie.json"
        try:
            self.s.cookies.set("kg_mid", self.mid, domain=".kugou.com")
        except Exception:  # noqa: BLE001
            pass
        self._load()

    # ---------------- 会话 ----------------
    @property
    def logged(self) -> bool:
        return bool(self.userid and self.token)

    def _load(self) -> None:
        try:
            if self.cookie_file.exists():
                d = json.loads(self.cookie_file.read_text("utf-8"))
                self._apply(d.get("userid") or "", d.get("token") or "")
        except Exception as exc:  # noqa: BLE001
            self.error = "读 cookie 失败：%s" % exc

    def _apply(self, userid: str, token: str) -> None:
        self.userid = "".join(ch for ch in str(userid or "") if ch.isdigit())
        self.token = str(token or "").strip()
        if self.userid:
            for name, val in (("userid", self.userid), ("KugouID", self.userid),
                              ("kg_userid", self.userid)):
                try:
                    self.s.cookies.set(name, val, domain=".kugou.com")
                except Exception:  # noqa: BLE001
                    pass
        if self.token:
            for name in ("token", "KugouToken"):
                try:
                    self.s.cookies.set(name, self.token, domain=".kugou.com")
                except Exception:  # noqa: BLE001
                    pass

    def set_cookie(self, userid: str, token: str) -> Dict:
        with self.lock:
            self._apply(userid, token)
            ok = self.logged
            if ok:
                self.nick = self.nick or ("酷狗 %s" % self.userid)
                try:
                    self.cookie_file.write_text(
                        json.dumps({"userid": self.userid, "token": self.token},
                                   ensure_ascii=False), "utf-8"
                    )
                except Exception:  # noqa: BLE001
                    pass
            return {"ok": ok, "userid": self.userid}

    def logout(self) -> Dict:
        with self.lock:
            self.userid = ""
            self.token = ""
            self.nick = ""
            try:
                self.cookie_file.unlink()
            except Exception:  # noqa: BLE001
                pass
            self.s.cookies.clear()
            try:
                self.s.cookies.set("kg_mid", self.mid, domain=".kugou.com")
            except Exception:  # noqa: BLE001
                pass
            return {"ok": True}

    # ---------------- 数据 ----------------
    def search(self, kw: str, limit: int = 30) -> List[Dict]:
        try:
            r = self.s.get(SEARCH, timeout=12, params={
                "format": "json", "keyword": kw, "page": 1,
                "pagesize": limit, "showtype": 1,
            })
            info = ((r.json().get("data") or {}).get("info") or [])
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            return []
        res = [_track(it) for it in info if it.get("hash")]
        # 顺手并发问一遍地址，问不到的标 VIP
        if res:
            playable = self.vurls([t["id"] for t in res])
            for t in res:
                t["vip"] = not bool(playable.get(t["id"]))
        return res

    def _playinfo(self, hash_: str) -> str:
        """酷狗这条要带 appid/clientver/mid/dfid，缺一个就回 data not found。"""
        params = {"cmd": "playInfo", "hash": str(hash_), "from": "mkugou",
                  "appid": 1005, "clientver": 11430,
                  "mid": self.mid or "", "dfid": self.dfid or ""}
        try:
            r = self.s.get(PLAYINFO, params=params, timeout=10)
            d = r.json()
        except Exception:  # noqa: BLE001
            return ""
        u = d.get("url") or ""
        if not u:
            bu = d.get("backup_url")
            if isinstance(bu, list) and bu:
                u = bu[0]
            elif isinstance(bu, str):
                u = bu
        if u:
            return u
        if "付费" in str(d.get("error") or ""):
            self.error = "这首歌在酷狗要会员"
        return ""

    def _tracker(self, hash_: str) -> str:
        try:
            r = self.s.get(TRACKER % (_v2_key(hash_), hash_), timeout=10)
            d = r.json()
            urls = d.get("url") or []
            return urls[0] if urls else ""
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            return ""

    def _one_url(self, hash_: str) -> str:
        return self._playinfo(hash_) or self._tracker(hash_)

    def vurls(self, hashes) -> Dict[str, str]:
        hashes = [h for h in (hashes or []) if h]
        if not hashes:
            return {}
        out: Dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=8) as pool:
            for h, u in zip(hashes, pool.map(self._one_url, hashes)):
                if u:
                    out[h] = u
        return out

    def track_url(self, hash_) -> str:
        return self._one_url(str(hash_))

    can_playlists = True
    SPECIAL_SONG = "http://mobilecdn.kugou.com/api/v3/special/song"

    def _pl_items(self, d) -> List[Dict]:
        """酷狗几个口返回的结构不一样，这里统一成 id/name/count。"""
        out: List[Dict] = []
        data = d.get("data") if isinstance(d, dict) else None
        if isinstance(data, dict):
            for key in ("list", "info", "playlist", "lists", "userlist"):
                v = data.get(key)
                if isinstance(v, list):
                    for it in v:
                        sid = (it.get("specialid") or it.get("global_collection_id")
                               or it.get("listid") or it.get("id") or it.get("collectionid"))
                        if not sid:
                            continue
                        out.append({
                            "id": str(sid),
                            "name": (it.get("specialname") or it.get("name")
                                     or it.get("listname") or "歌单"),
                            "count": int(it.get("songcount") or it.get("total")
                                         or it.get("count") or it.get("song_count") or 0),
                            "cover": it.get("imgurl") or it.get("pic") or "",
                        })
                    return out
        return out

    def _pl_title(self, sid) -> str:
        """歌单名只能从分享页标题里抠，抠不到就用 ID 兜底。"""
        try:
            r = self.s.get("https://www.kugou.com/yy/special/single/%s.html" % sid,
                           timeout=10)
            m = re.search(r"<title>(.*?)</title>", r.text or "", re.S)
            if m:
                s = m.group(1).strip()
                s = s.replace("- 酷狗音乐", "").replace("-酷狗音乐", "")
                s = s.replace("_酷狗音乐", "").replace("|酷狗音乐", "")
                s = re.split(r"[_|]", s)[0].strip()
                if s and "酷狗" not in s and len(s) <= 40:
                    return s
        except Exception:  # noqa: BLE001
            pass
        return ""

    def _pl_file(self) -> Path:
        return self.dir / "kg_playlists.json"

    def local_playlists(self) -> List[Dict]:
        """本地记住的酷狗歌单（用户粘贴链接导入的那些）。"""
        try:
            data = json.loads(self._pl_file().read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return []
        return [p for p in (data or []) if isinstance(p, dict) and p.get("id")]

    def add_local(self, text) -> Dict:
        """从酷狗歌单链接/ID 导入：.../special/single/1234.html 或 specialid=1234。"""
        s = str(text or "")
        m = (re.search(r"specialid[=/](\d{4,})", s)
             or re.search(r"single/(\d{4,})", s)
             or re.search(r"(\d{4,})", s))
        if not m:
            return {"_error": "链接里没找到歌单 ID"}
        sid = m.group(1)
        name, total = "", 0
        try:
            r = self.s.get(self.SPECIAL_SONG, timeout=10,
                           params={"specialid": sid, "page": 1, "pagesize": 1,
                                   "format": "json", "version": 8000})
            d = r.json() or {}
            dd = d.get("data") if isinstance(d.get("data"), dict) else d
            info = dd.get("info")
            if isinstance(info, dict):
                name = info.get("specialname") or info.get("name") or ""
            total = int(dd.get("total") or 0)
        except Exception as exc:  # noqa: BLE001
            return {"_error": "打不开这个歌单：%s" % str(exc)[:30]}
        if not name:
            name = self._pl_title(sid)
        item = {"id": sid, "name": name or ("酷狗歌单 %s" % sid),
                "count": total, "cover": ""}
        items = [p for p in self.local_playlists() if p.get("id") != sid]
        items.append(item)
        try:
            self._pl_file().write_text(
                json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return item

    def my_playlists(self) -> List[Dict]:
        """我的歌单：官方私人口被 WAF 全拦，能用的只有用户自己导入的。"""
        local = self.local_playlists()
        if local:
            return local
        if not self.logged:
            return []
        cands = [
            ("http://mobilecdn.kugou.com/api/v3/user/playlist",
             {"userid": self.userid, "token": self.token, "page": 1,
              "pagesize": 30, "format": "json"}),
            ("https://www.kugou.com/yy/index.php",
             {"r": "user/playlist", "userid": self.userid, "t": self.token}),
        ]
        for url, params in cands:
            try:
                r = self.s.get(url, params=params, timeout=10)
                if "Deny" in (r.text or "")[:60]:
                    continue
                items = self._pl_items(r.json())
            except Exception:  # noqa: BLE001
                continue
            if items:
                return items
        self.error = "读不到酷狗自动歌单，可点下面「粘贴歌单链接导入」"
        return []

    def playlist_tracks(self, pid) -> List[Dict]:
        """取歌单里的歌：special/song 是公开口，不用登录，按页拉全。"""
        res: List[Dict] = []
        total = 0
        page = 1
        while page <= 30:
            try:
                r = self.s.get(self.SPECIAL_SONG, timeout=12,
                               params={"specialid": str(pid), "page": page,
                                       "pagesize": 30, "format": "json", "version": 1})
                data = r.json().get("data") or {}
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
                break
            total = int(data.get("total") or total or 0)
            info = data.get("info") or []
            for it in info:
                if it.get("hash"):
                    res.append(_track(it))
            if len(info) < 30 or (total and len(res) >= total):
                break
            page += 1
        if res:
            urls = self.vurls([t["id"] for t in res])
            for t in res:
                t["vip"] = not bool(urls.get(t["id"]))
        return res

    def recommend(self, limit: int = 30) -> List[Dict]:
        """每日推荐：走热歌榜（rankid 8888），登录后照样能用。"""
        try:
            r = self.s.get("http://mobilecdn.kugou.com/api/v3/rank/song", timeout=12,
                           params={"rankid": 8888, "page": 1, "pagesize": limit,
                                   "format": "json"})
            info = (r.json().get("data") or {}).get("info") or []
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            return []
        res = []
        for it in info:
            fn = it.get("filename") or ""
            if " - " in fn:
                artist, name = fn.split(" - ", 1)
            else:
                artist, name = (it.get("singername") or "—"), fn
            album_id = str(it.get("album_id") or "")
            res.append({
                "id": it.get("hash") or "",
                "name": name or "未知",
                "artist": artist or "—",
                "album": "",
                "dur": int((it.get("duration") or 0) * 1000),
                "cover": ("https://imge.kugou.com/stdmusic/240/%s.jpg" % album_id)
                         if album_id else "",
                "src": "kg",
            })
        res = [t for t in res if t["id"]]
        if res:
            urls = self.vurls([t["id"] for t in res])
            for t in res:
                t["vip"] = not bool(urls.get(t["id"]))
        return res[:limit]
