"""系统媒体控制（SMTC）：看别人在放什么，并把播放/暂停/切歌按下去。

只做“看”和“按按钮”：音频始终由用户自己的客户端播放，这里不取任何音频流、
不登录账号、不碰平台接口。Windows 10/11 自带这条通道，只要播放器上报过会话
（网易云、QQ 音乐、酷狗、酷我、Spotify、浏览器都上报）就能读到，换播放器自动跟着变。
"""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import timedelta
from typing import Optional

from PySide6 import QtCore

log = logging.getLogger(__name__)

try:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as _Manager,
    )
    from winrt.windows.storage.streams import DataReader

    HAVE_SMTC = True
    _IMPORT_ERR = ""
except Exception as exc:  # 没装 winrt 或系统太老
    _Manager = None
    DataReader = None
    HAVE_SMTC = False
    _IMPORT_ERR = str(exc)

# 进程 id → 好认的名字（认不出就显示 exe 名）
_APP_NAMES = {
    "cloudmusic": "网易云音乐",
    "netease": "网易云音乐",
    "qqmusic": "QQ 音乐",
    "qqm": "QQ 音乐",
    "kugou": "酷狗音乐",
    "kuwo": "酷我音乐",
    "spotify": "Spotify",
    "foobar": "foobar2000",
    "potplayer": "PotPlayer",
    "vlc": "VLC",
    "wmplayer": "媒体播放器",
    "zunemusic": "Groove 音乐",
    "msedge": "浏览器",
    "chrome": "浏览器",
    "firefox": "浏览器",
    "music": "音乐播放器",
}


def friendly_app(app_id: str) -> str:
    """把 SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify 这类 id 抹成好认的名字。"""
    if not app_id:
        return "系统"
    low = app_id.lower()
    for k, v in _APP_NAMES.items():
        if k in low:
            return v
    tail = app_id.split("!")[-1].strip()
    if tail:
        return tail
    return app_id.split(".")[-1]


def _seconds(span) -> float:
    """TimeSpan（pywinrt 里是 timedelta）→ 秒。"""
    if span is None:
        return 0.0
    try:
        return max(0.0, span.total_seconds())
    except AttributeError:
        return max(0.0, float(span) / 10_000_000.0)


class Watcher(QtCore.QObject):
    """后台线程轮询会话，把快照发给界面；控制命令投回那个线程里跑。"""

    changed = QtCore.Signal(dict)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.available = HAVE_SMTC
        self.reason = _IMPORT_ERR
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop = False
        self._last_cover_key = ""
        self._cover: Optional[bytes] = None
        self.last: dict = {}

    # ---------------- 生命周期 ----------------
    def start(self) -> None:
        if not HAVE_SMTC or self._thread is not None:
            return
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="smtc-watch", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop = True
        self._loop = None

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._poll())
        except Exception:
            log.exception("媒体会话轮询退出")
        finally:
            try:
                loop.close()
            except Exception:
                pass
            self._loop = None

    async def _poll(self) -> None:
        mgr = None
        while not self._stop:
            try:
                if mgr is None:
                    mgr = await _Manager.request_async()
                snap = await asyncio.wait_for(self._snapshot(mgr), timeout=4.0)
                reply = {"ok": True}
                reply.update(snap)
            except Exception as exc:
                mgr = None
                reply = {
                    "ok": False,
                    "error": str(exc),
                    "state": "none",
                    "title": "",
                    "artist": "",
                    "album": "",
                    "app": "",
                    "pos": 0.0,
                    "dur": 0.0,
                    "playing": False,
                    "cover": None,
                }
            self.last = reply
            try:
                self.changed.emit(reply)
            except Exception:
                pass
            await asyncio.sleep(1.2)

    # ---------------- 读 ----------------
    async def _snapshot(self, mgr) -> dict:
        cur = mgr.get_current_session()
        if cur is None:
            self._last_cover_key = ""
            self._cover = None
            return {
                "state": "none",
                "title": "",
                "artist": "",
                "album": "",
                "app": "",
                "pos": 0.0,
                "dur": 0.0,
                "playing": False,
                "cover": None,
            }

        props = await cur.try_get_media_properties_async()
        title = (props.title or "").strip()
        artist = (props.artist or "").strip()
        album = (props.album_title or "").strip()
        key = title + "\u0001" + artist
        cover = None
        if key != self._last_cover_key:
            self._last_cover_key = key
            try:
                cover = await self._cover_bytes(props.thumbnail)
            except Exception:
                cover = b""

        info = cur.get_playback_info()
        try:
            status = int(info.playback_status)
        except Exception:
            status = 0
        playing = status == 4  # PLAYING
        tl = cur.get_timeline_properties()
        return {
            "state": "playing" if playing else ("paused" if title else "idle"),
            "status": status,
            "title": title,
            "artist": artist,
            "album": album,
            "app": friendly_app(cur.source_app_user_model_id or ""),
            "pos": _seconds(tl.position),
            "dur": _seconds(tl.end_time),
            "playing": playing,
            "cover": cover,
        }

    async def _cover_bytes(self, ref) -> Optional[bytes]:
        if ref is None:
            return None
        stream = await ref.open_read_async()
        size = int(stream.size)
        if size <= 0 or size > 4_000_000:
            return None
        buf = await stream.read_async(size, 0)  # 0 = InputStreamOptions.NONE
        reader = DataReader.from_buffer(buf)
        return bytes(reader.read_buffer(int(buf.length)))

    # ---------------- 控 ----------------
    def toggle(self) -> None:
        self._post("toggle")

    def next(self) -> None:
        self._post("next")

    def prev(self) -> None:
        self._post("prev")

    def seek(self, seconds: float) -> None:
        self._post("seek", seconds)

    def _post(self, action: str, arg=None) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            log.info("媒体控制还没起来（没有会话或后台线程未启动）")
            return
        try:
            asyncio.run_coroutine_threadsafe(self._control(action, arg), loop)
        except Exception:
            log.exception("投递媒体控制命令失败")

    async def _control(self, action: str, arg=None) -> None:
        mgr = await _Manager.request_async()
        cur = mgr.get_current_session()
        if cur is None:
            return
        try:
            if action == "toggle":
                await cur.try_toggle_play_pause_async()
            elif action == "next":
                await cur.try_skip_next_async()
            elif action == "prev":
                await cur.try_skip_previous_async()
            elif action == "seek":
                await cur.try_change_playback_position_async(
                    timedelta(seconds=max(0.0, float(arg or 0.0)))
                )
        except Exception:
            log.exception("媒体控制失败：%s", action)
