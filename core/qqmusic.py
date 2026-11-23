"""QQ 音乐接口层：搜索、取播放地址、cookie 登录。

说明：QQ 音乐没有公开 API，这里走的是网页端自己在用的 musicu.fcg 通道。
不登录也能放免费歌（大约一半）；VIP 歌要登录后才会给播放地址。
"""

from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Dict, List

import requests

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
API = "https://u.y.qq.com/cgi-bin/musicu.fcg"
STREAM = "https://ws.stream.qqmusic.qq.com/"


def _track(song: dict) -> Dict:
    al = song.get("album") or {}
    singers = [s.get("name") or "" for s in (song.get("singer") or [])]
    album_mid = al.get("mid") or song.get("albummid") or ""
    cover = ""
    if album_mid:
        cover = "https://y.qq.com/music/photo_new/T002R300x300M000%s.jpg" % album_mid
    return {
        "id": song.get("mid") or song.get("songmid") or "",
        "name": (song.get("name") or song.get("songname")
                 or song.get("songorig") or ""),
        "artist": " / ".join(n for n in singers if n),
        "album": al.get("name") or song.get("albumname") or "",
        "dur": int((song.get("interval") or 0) * 1000),
        "cover": cover,
        "src": "qq",
    }


class QQ:
    """一个 QQ 音乐会话：不登录能搜能放免费歌，登录后能放 VIP 歌。"""

    def __init__(self, store: Path):
        self.dir = Path(store)
        self.uin = ""
        self.key = ""
        self.nick = ""
        self.error = ""
        self.lock = threading.RLock()
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Referer": "https://y.qq.com/"})
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass
        self.cookie_file = self.dir / "qq_cookie.json"
        self._load()
        # 预热一次，把域 cookie 种上（否则接口偶尔返回空列表）
        try:
            self.s.get("https://y.qq.com/", timeout=10)
        except Exception:  # noqa: BLE001
            pass

    # ---------------- 会话 ----------------
    @property
    def logged(self) -> bool:
        return bool(self.uin and self.key)

    def _load(self) -> None:
        try:
            if self.cookie_file.exists():
                d = json.loads(self.cookie_file.read_text("utf-8"))
                self._apply(d.get("uin") or "", d.get("qm_keyst") or "")
        except Exception as exc:  # noqa: BLE001
            self.error = "读 cookie 失败：%s" % exc

    def _apply(self, uin: str, key: str) -> None:
        uin = str(uin or "").strip()
        if uin.lower().startswith("o"):
            uin = uin[1:]
        self.uin = "".join(ch for ch in uin if ch.isdigit())
        self.key = str(key or "").strip()
        if self.uin:
            try:
                self.s.cookies.set("uin", "o" + self.uin.zfill(10), domain=".qq.com")
            except Exception:  # noqa: BLE001
                pass
        for name in ("qm_keyst", "qqmusic_key", "qm_keyst_1"):
            if self.key:
                try:
                    self.s.cookies.set(name, self.key, domain=".qq.com")
                except Exception:  # noqa: BLE001
                    pass

    def set_cookie(self, uin: str, key: str) -> Dict:
        with self.lock:
            self._apply(uin, key)
            ok = self.logged
            if ok:
                self.nick = self.nick or ("QQ %s" % self.uin)
                try:
                    self.cookie_file.write_text(
                        json.dumps({"uin": self.uin, "qm_keyst": self.key},
                                   ensure_ascii=False), "utf-8"
                    )
                except Exception:  # noqa: BLE001
                    pass
            return {"ok": ok, "uin": self.uin}

    def logout(self) -> Dict:
        with self.lock:
            self.uin = ""
            self.key = ""
            self.nick = ""
            try:
                self.cookie_file.unlink()
            except Exception:  # noqa: BLE001
                pass
            self.s.cookies.clear()
            return {"ok": True}

    # ---------------- 数据 ----------------
    def _comm(self) -> Dict:
        return {"ct": 19, "cv": 1859, "uin": self.uin or "0",
                "format": "json", "platform": "yqq.json"}

    def search(self, kw: str, limit: int = 30) -> List[Dict]:
        """搜索。QQ 这个接口连打会突然返回空，所以失败要退一步重来。"""
        res: List[Dict] = []
        for attempt in range(3):
            res = self._search_once(kw, limit)
            if res:
                return res
            if attempt < 2:
                time.sleep(1.3 + attempt * 0.7)
                try:
                    self.s.get("https://y.qq.com/", timeout=8)
                except Exception:  # noqa: BLE001
                    pass
        return res

    def _search_once(self, kw: str, limit: int = 30) -> List[Dict]:
        with self.lock:
            try:
                body = {
                    "req_1": {
                        "module": "music.search.SearchCgiService",
                        "method": "DoSearchForQQMusicDesktop",
                        "param": {"num_per_page": limit, "page_num": 1,
                                  "query": kw, "search_type": 0, "grp": 1},
                    },
                    "comm": self._comm(),
                }
                r = self.s.post(API, data=json.dumps(body), timeout=12,
                                headers={"Content-Type": "application/json"})
                d = r.json()
                lst = ((((d.get("req_1") or {}).get("data") or {}).get("body") or {})
                       .get("song") or {}).get("list") or []
                res = [_track(s) for s in lst if s.get("mid")]
                # 一次批量问地址，顺手标出匿名态放不了的（VIP / 付费）
                urls = self.vkeys([t["id"] for t in res])
                if urls:
                    for t in res:
                        t["vip"] = bool(t["id"]) and not bool(urls.get(t["id"]))
                return res
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
                return []

    def vkeys(self, mids, retry: int = 1) -> Dict[str, str]:
        """一次问一批 songmid 的播放地址，返回 {mid: url}。"""
        mids = [str(m) for m in (mids or []) if m]
        if not mids:
            return {}
        with self.lock:
            try:
                body = {
                    "req_0": {
                        "module": "vkey.GetVkeyServer",
                        "method": "CgiGetVkey",
                        "param": {"guid": "10000", "songmid": mids,
                                  "songtype": [0] * len(mids),
                                  "uin": self.uin or "0",
                                  "loginUin": self.uin or "0", "hostUin": "0",
                                  "platform": "yqq", "needNewCode": 0,
                                  "format": "json"},
                    },
                    "comm": {"uin": self.uin or "0", "format": "json", "ct": 24,
                             "cv": 0, "platform": "yqq"},
                }
                r = self.s.post(API, data=json.dumps(body), timeout=12,
                                headers={"Content-Type": "application/json"})
                d = r.json()
                data = (d.get("req_0") or {}).get("data") or {}
                sip = data.get("sip") or []
                base = sip[0] if sip else STREAM
                out = {}
                for info in (data.get("midurlinfo") or []):
                    mid = info.get("songmid") or ""
                    purl = info.get("purl") or ""
                    if mid and purl:
                        out[mid] = base + purl
                return out
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
                if retry > 0:
                    return self.vkeys(mids, retry - 1)
                return {}

    def track_url(self, mid) -> str:
        url = self.vkeys([mid]).get(str(mid), "")
        if not url:
            url = self.vkeys([mid], retry=0).get(str(mid), "")
        return url

    can_playlists = True

    def my_playlists(self) -> List[Dict]:
        """我的歌单：我喜欢 + 收藏的歌单（自建歌单接口只对网页本人下发）。"""
        if not self.logged:
            return []
        out: List[Dict] = []
        url = "https://c.y.qq.com/fav/fcgi-bin/fcg_get_profile_order_asset.fcg"
        hdr = {"Referer": "https://y.qq.com/portal/profile.html"}
        fav_total = 0
        d = {}
        try:
            r = self.s.get(url, timeout=12,
                           params={"ct": 20, "cid": 205360956, "userid": self.uin,
                                   "reqtype": 1, "sin": 0, "ein": 40, "format": "json"},
                           headers=hdr)
            fd = (r.json() or {}).get("data") or {}
            fav_total = int(fd.get("totalsong") or 0)
        except Exception:  # noqa: BLE001
            pass
        try:
            r = self.s.get(url, timeout=12,
                           params={"ct": 20, "cid": 205360956, "userid": self.uin,
                                   "reqtype": 3, "sin": 0, "ein": 40, "format": "json"},
                           headers=hdr)
            d = (r.json() or {}).get("data") or {}
        except Exception as exc:  # noqa: BLE001
            self.error = "读歌单失败：%s" % exc
        out.append({"id": "fav", "name": "我喜欢", "count": fav_total, "cover": ""})
        for part in (d.get("created_list") or [],
                     d.get("fav_list") or [],
                     d.get("cdlist") or []):
            for it in part:
                did = str(it.get("dissid") or it.get("dirid") or "")
                if not did:
                    continue
                out.append({
                    "id": did,
                    "name": it.get("dissname") or it.get("dirname") or "未命名歌单",
                    "count": int(it.get("song_cnt") or it.get("songnum") or 0),
                    "cover": it.get("logo") or "",
                })
        for p in self.local_playlists():
            if p.get("id") not in [x.get("id") for x in out]:
                out.append(p)
        return out

    def _pl_file(self) -> Path:
        return self.dir / "qq_playlists.json"

    def local_playlists(self) -> List[Dict]:
        """本地记住的 QQ 歌单（自己粘贴链接导入的）。"""
        try:
            data = json.loads(self._pl_file().read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return []
        return [p for p in (data or []) if isinstance(p, dict) and p.get("id")]

    def add_local(self, text) -> Dict:
        """从歌单链接导入：y.qq.com/n/ryqq/playlist/<disstid> 或纯数字。"""
        s = str(text or "")
        m = (re.search(r"playlist/(\d{5,})", s)
             or re.search(r"disstid=(\d{5,})", s)
             or re.search(r"(\d{5,})", s))
        if not m:
            return {"_error": "链接里没找到歌单 ID"}
        did = m.group(1)
        try:
            r = self.s.get(
                "https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg",
                timeout=12,
                params={"type": 1, "json": 1, "utf8": 1, "onlysong": 0,
                        "disstid": did, "format": "json", "g_tk": 5381,
                        "loginUin": self.uin, "hostUin": 0,
                        "platform": "yqq.json", "needNewCode": 0},
                headers={"Referer": "https://y.qq.com/"})
            cd = ((r.json() or {}).get("cdlist") or [])[0]
        except Exception as exc:  # noqa: BLE001
            return {"_error": "打不开这个歌单：%s" % str(exc)[:30]}
        songs = cd.get("songlist") or []
        item = {"id": did, "name": cd.get("dissname") or ("QQ歌单 %s" % did),
                "count": int(cd.get("songnum") or len(songs) or 0),
                "cover": cd.get("logo") or ""}
        items = [p for p in self.local_playlists() if p.get("id") != did]
        items.append(item)
        try:
            self._pl_file().write_text(
                json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
        return item

    def playlist_tracks(self, pid) -> List[Dict]:
        """取一个歌单里的歌（disstid；fav=我喜欢）。"""
        if str(pid) == "fav":
            songs: List[Dict] = []
            sin = 0
            while sin < 2000:
                try:
                    r = self.s.get(
                        "https://c.y.qq.com/fav/fcgi-bin/fcg_get_profile_order_asset.fcg",
                        timeout=12,
                        params={"ct": 20, "cid": 205360956, "userid": self.uin,
                                "reqtype": 1, "sin": sin, "ein": sin + 40,
                                "format": "json"},
                        headers={"Referer": "https://y.qq.com/portal/profile.html"},
                    )
                    fd = (r.json() or {}).get("data") or {}
                except Exception as exc:  # noqa: BLE001
                    self.error = "读「我喜欢」失败：%s" % exc
                    break
                part = fd.get("songlist") or []
                songs += [(x.get("data") or x) for x in part]
                if not fd.get("has_more") or len(part) < 40:
                    break
                sin += 40
            res = [_track(s) for s in songs if s.get("songmid") or s.get("mid")]
            if res:
                urls = self.vkeys([t["id"] for t in res])
                for t in res:
                    t["vip"] = t["id"] not in urls
            return res
        try:
            r = self.s.get(
                "https://c.y.qq.com/qzone/fcg-bin/fcg_ucc_getcdinfo_byids_cp.fcg",
                timeout=12,
                params={"type": 1, "json": 1, "utf8": 1, "onlysong": 0,
                        "disstid": str(pid), "format": "json", "g_tk": 5381,
                        "loginUin": self.uin, "hostUin": 0,
                        "platform": "yqq.json", "needNewCode": 0},
                headers={"Referer": "https://y.qq.com/"},
            )
            cd = ((r.json() or {}).get("cdlist") or [{}])[0]
            songs = cd.get("songlist") or []
        except Exception as exc:  # noqa: BLE001
            self.error = "读歌单里的歌失败：%s" % exc
            return []
        res = [_track(s) for s in songs if s.get("songmid") or s.get("mid")]
        if res:
            urls = self.vkeys([t["id"] for t in res])
            for t in res:
                t["vip"] = t["id"] not in urls
        return res

    def recommend(self, limit: int = 30) -> List[Dict]:
        """每日推荐：登录态下 QQ 的推荐 feed 没稳定接口，先用热歌榜顶住。"""
        try:
            r = self.s.get(
                "https://c.y.qq.com/v8/fcg-bin/fcg_v8_toplist_cp.fcg",
                timeout=12,
                params={"topid": 26, "format": "json", "page": "detail", "tpl": 3,
                        "type": "top", "song_begin": 0, "song_num": limit},
            )
            raw = [x.get("data") or {} for x in ((r.json() or {}).get("songlist") or [])]
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            return []
        songs = []
        for d in raw:
            if not (d.get("songmid") or d.get("mid")):
                continue
            songs.append({
                "mid": d.get("songmid") or d.get("mid"),
                "name": d.get("songname") or d.get("name") or "",
                "singer": d.get("singer") or [],
                "album": {"mid": d.get("albummid") or "",
                          "name": d.get("albumname") or ""},
                "interval": d.get("interval") or 0,
            })
        res = [_track(s) for s in songs]
        if res:
            urls = self.vkeys([t["id"] for t in res])
            for t in res:
                t["vip"] = not bool(urls.get(t["id"]))
        return res[:limit]
