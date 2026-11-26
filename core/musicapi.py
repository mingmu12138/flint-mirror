"""网易云音乐接口层：登录、搜索、歌单、取音频地址。

这里的函数都会阻塞（走网络），调用方负责放到后台线程。
构造时不联网：会话在后台线程里恢复/匿名登录，用 ready 事件兜住。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, List

try:
    import pyncm
    from pyncm.apis.cloudsearch import GetSearchResult
    from pyncm.apis.login import (
        GetCurrentLoginStatus, GetLoginQRCodeUrl, LoginQrcodeCheck,
        LoginQrcodeUnikey, LoginViaAnonymousAccount,
    )
    from pyncm.apis import WeapiCryptoRequest
    from pyncm.apis.playlist import GetPlaylistInfo
    from pyncm.apis.track import GetTrackAudioV1
    from pyncm.apis.user import GetUserPlaylists

    HAVE = True
except Exception:  # noqa: BLE001
    HAVE = False

# pyncm 1.8 起 WeapiCryptoRequest 是个装饰器：被修饰的函数只返回 (url, 参数)，
# session 和加密由它自己接管。老写法 WeapiCryptoRequest(url, 参数) 现在会直接
# TypeErrors（"takes 1 positional argument"），每日推荐就是这么变成空列表的。
if HAVE:
    @WeapiCryptoRequest
    def _daily_recommend(limit: int = 30):
        return (
            "/api/v1/discovery/recommend/songs",
            {"limit": limit, "offset": 0, "total": True},
        )


LEVELS = ["exhigh", "higher", "standard"]


def _artist(song: dict) -> str:
    ar = song.get("ar") or song.get("artists") or []
    names = [a.get("name") or "" for a in ar]
    return " / ".join(n for n in names if n)


def _track(song: dict) -> Dict:
    al = song.get("al") or song.get("album") or {}
    return {
        "id": song.get("id"),
        "name": song.get("name") or "",
        "artist": _artist(song),
        "album": al.get("name") or "",
        "dur": song.get("dt") or song.get("duration") or 0,
        "cover": al.get("picUrl") or "",
        "src": "ny",
    }


class Ny:
    """一个网易云会话。第一次用到时自动匿名登录；登录后能读自己的歌单。"""

    def __init__(self, store: Path):
        self.dir = Path(store)
        self.logged = False
        self.nick = ""
        self.uid = 0
        self.error = "" if HAVE else "没装 pyncm（pip install pyncm）"
        self.lock = threading.RLock()
        self.ready = threading.Event()
        if not HAVE:
            self.ready.set()
            return
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass
        self.sess_file = self.dir / "session.json"
        threading.Thread(target=self._boot, daemon=True).start()

    def _wait(self) -> None:
        if not self.ready.is_set():
            self.ready.wait(10)

    # ---------------- 会话 ----------------
    def _boot(self) -> None:
        try:
            with self.lock:
                restored = False
                try:
                    if self.sess_file.exists():
                        # pyncm 的 LoadSessionFromString 只「解析」出一份会话，并不会
                        # 接管当前会话；漏掉下面这句，恢复等于没做，接着的匿名登录
                        # 还会把真实登录态覆盖掉 —— 这就是每次启动都要重新扫码的原因
                        sess = pyncm.LoadSessionFromString(
                            self.sess_file.read_text("utf-8"))
                        pyncm.SetCurrentSession(sess)
                        restored = True
                except Exception as exc:  # noqa: BLE001
                    self.error = "恢复登录态失败：%s" % exc
                st = self._status()
                if not st.get("logged"):
                    if restored:
                        # 恢复出来的登录态已经失效（MUSIC_U 过期），清掉，别再拖累下次
                        try:
                            self.sess_file.unlink()
                        except Exception:  # noqa: BLE001
                            pass
                    try:
                        LoginViaAnonymousAccount()
                        self._status()
                    except Exception as exc:  # noqa: BLE001
                        self.error = "匿名登录失败：%s" % exc
                else:
                    # 认到了：顺手把这次请求刷新过的 cookie 写回去
                    self.save()
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
        finally:
            self.ready.set()

    def _status(self) -> Dict:
        try:
            st = GetCurrentLoginStatus()
            acc = st.get("account") or {}
            prof = st.get("profile") or {}
            self.uid = acc.get("id") or 0
            self.nick = prof.get("nickname") or ""
            self.logged = bool(acc) and not acc.get("anonimousUser")
            return {"logged": self.logged, "nick": self.nick, "uid": self.uid,
                    "code": st.get("code")}
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            return {"logged": False, "nick": "", "uid": 0, "code": -1}

    def refresh_status(self) -> Dict:
        self._wait()
        with self.lock:
            return self._status()

    def save(self) -> None:
        with self.lock:
            try:
                self.sess_file.write_text(
                    pyncm.DumpSessionAsString(pyncm.GetCurrentSession()), "utf-8"
                )
            except Exception:  # noqa: BLE001
                pass

    def logout(self) -> Dict:
        self._wait()
        with self.lock:
            try:
                from pyncm.apis.login import LoginLogout

                LoginLogout()
            except Exception:  # noqa: BLE001
                pass
            self.logged = False
            self.nick = ""
            self.uid = 0
            try:
                self.sess_file.unlink()
            except Exception:  # noqa: BLE001
                pass
            try:
                pyncm.SetNewSession()
                LoginViaAnonymousAccount()
            except Exception:  # noqa: BLE001
                pass
            return self._status()

    # ---------------- 二维码登录 ----------------
    def qr_start(self) -> Dict:
        self._wait()
        with self.lock:
            try:
                r = LoginQrcodeUnikey()
                key = r.get("unikey") or ""
                url = GetLoginQRCodeUrl(key) if key else ""
                return {"ok": bool(key), "unikey": key, "url": url}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "unikey": "", "url": "", "error": str(exc)}

    def qr_poll(self, unikey: str) -> Dict:
        self._wait()
        with self.lock:
            try:
                r = LoginQrcodeCheck(unikey)
                code = r.get("code")
                if code == 803:
                    self._status()
                    self.save()
                    return {"code": 803, "ok": True, "msg": "登录成功，正在读你的歌单…",
                            "logged": self.logged, "nick": self.nick}
                msg = {
                    800: "二维码过期了，点“换一张”",
                    801: "等手机上确认…",
                    802: "已扫描，在手机上点一下确认",
                }.get(code, r.get("message") or ("状态 %s" % code))
                return {"code": code, "ok": False, "msg": msg}
            except Exception as exc:  # noqa: BLE001
                return {"code": -1, "ok": False, "msg": "轮询失败：%s" % exc}

    # ---------------- 数据 ----------------
    def my_playlists(self) -> List[Dict]:
        self._wait()
        with self.lock:
            if not (self.logged and self.uid):
                return []
            try:
                r = GetUserPlaylists(self.uid, limit=200)
            except Exception:  # noqa: BLE001
                return []
            out = []
            for p in (r.get("playlist") or []):
                out.append({
                    "id": p.get("id"),
                    "name": p.get("name") or "未命名",
                    "count": p.get("trackCount") or 0,
                    "cover": p.get("coverImgUrl") or "",
                })
            return out

    def playlist_tracks(self, pid) -> List[Dict]:
        self._wait()
        with self.lock:
            try:
                r = GetPlaylistInfo(pid, limit=1000)
            except Exception:  # noqa: BLE001
                return []
            pl = r.get("playlist") or {}
            return [_track(s) for s in (pl.get("tracks") or [])]

    def search(self, kw: str, limit: int = 30) -> List[Dict]:
        self._wait()
        with self.lock:
            try:
                r = GetSearchResult(kw, limit=limit)
            except Exception:  # noqa: BLE001
                return []
            return [_track(s) for s in ((r.get("result") or {}).get("songs") or [])]

    def track_url(self, sid, level: str = "exhigh") -> str:
        self._wait()
        with self.lock:
            for lv in LEVELS:
                try:
                    r = GetTrackAudioV1([sid], level=lv)
                    d = (r.get("data") or [{}])[0]
                    u = d.get("url")
                    if u:
                        return u
                except Exception:  # noqa: BLE001
                    continue
            return ""

    def recommend(self, limit: int = 30) -> List[Dict]:
        """每日推荐：官方 weapi 接口，跟当前登录的账号走。"""
        self._wait()
        if not HAVE:
            return []
        with self.lock:
            try:
                resp = _daily_recommend(limit)
            except Exception as exc:  # noqa: BLE001
                self.error = str(exc)
                return []
        if not isinstance(resp, dict):
            self.error = "每日推荐回包不是 JSON"
            return []
        if resp.get("code") not in (200, None):
            self.error = "网易云说：%s（%s）" % (
                resp.get("message") or resp.get("msg") or "没给原因",
                resp.get("code"),
            )
        songs = resp.get("recommend")
        if not songs:
            songs = (resp.get("data") or {}).get("dailySongs")
        return [_track(s) for s in (songs or []) if s.get("id")][:limit]
