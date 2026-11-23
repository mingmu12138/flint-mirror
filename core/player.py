"""本地播放器：QMediaPlayer + 播放队列 + 取流。"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from PySide6 import QtCore, QtMultimedia


class Player(QtCore.QObject):
    """一条播放队列。取音频地址在工作线程，播放与状态都在主线程。"""

    changed = QtCore.Signal()
    track_changed = QtCore.Signal(dict)
    failed = QtCore.Signal(str)
    _ready = QtCore.Signal(str)
    _missing = QtCore.Signal(str)

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.queue: List[Dict] = []
        self.index = -1
        self.current: Dict = {}
        self._loading = False
        self.volume = 0.7

        self.out = None
        self.qmp = None
        self._rebinding = False
        self._pending_pos = 0
        self._pending_play = False
        self._new_qmp()

        self._ready.connect(self._start)
        self._missing.connect(self._no_url)

    # ---------------- 队列 ----------------
    def set_queue(self, tracks: List[Dict], index: int = 0) -> None:
        self.queue = list(tracks or [])
        if self.queue:
            self.play_index(index)

    def play_index(self, i: int) -> None:
        if not (0 <= i < len(self.queue)):
            return
        self.index = i
        track = self.queue[i]
        self.current = track
        self.track_changed.emit(track)
        self._loading = True
        threading.Thread(target=self._fetch, args=(track,), daemon=True).start()

    def _fetch(self, track: Dict) -> None:
        url = ""
        api = (getattr(self, "api_map", {}) or {}).get(track.get("src") or "ny") or self.api
        try:
            url = api.track_url(track.get("id"))
        except Exception:  # noqa: BLE001
            url = ""
        if url:
            self._ready.emit(url)
        else:
            self._missing.emit(track.get("name") or "这首歌")

    # ---------------- 主线程侧 ----------------
    def _new_qmp(self) -> None:
        """换一首歌就换一个播放器实例。

        实测：复用同一个 QMediaPlayer 在播放中 setSource，FFmpeg 后端会直接崩进程；
        每次新建实例（音频输出复用）换源十几次都稳。
        """
        old = self.qmp
        old_out = self.out
        # 音频输出也一起换：同一个 QAudioOutput 被旧播放器卸下后再挂到新播放器，
        # 实测会让新播放器直接报 InvalidMedia
        self.out = QtMultimedia.QAudioOutput(self)
        self.out.setVolume(getattr(self, "volume", 0.7))
        pl = QtMultimedia.QMediaPlayer(self)
        pl.setAudioOutput(self.out)
        pl.positionChanged.connect(lambda *_: self.changed.emit())
        pl.durationChanged.connect(lambda *_: self.changed.emit())
        pl.playbackStateChanged.connect(lambda *_: self.changed.emit())
        pl.mediaStatusChanged.connect(self._on_status)
        pl.errorOccurred.connect(self._on_error)
        self.qmp = pl
        if old is not None:
            for sig in (old.mediaStatusChanged, old.errorOccurred,
                        old.positionChanged, old.durationChanged,
                        old.playbackStateChanged):
                try:
                    sig.disconnect()
                except Exception:  # noqa: BLE001
                    pass
            try:
                old.stop()
                old.setAudioOutput(None)
                old.deleteLater()
            except Exception:  # noqa: BLE001
                pass
        if old_out is not None:
            try:
                old_out.deleteLater()
            except Exception:  # noqa: BLE001
                pass

    def _start(self, url: str) -> None:
        self._loading = False
        self._new_qmp()
        self.qmp.setSource(QtCore.QUrl(url))
        self.qmp.play()

    def _no_url(self, name: str) -> None:
        self._loading = False
        self.failed.emit("《%s》拿不到播放地址（可能要会员，或者版权限制）" % name)

    def _on_status(self, status) -> None:
        if status == QtMultimedia.QMediaPlayer.MediaStatus.EndOfMedia:
            self.next(auto=True)
        elif status == QtMultimedia.QMediaPlayer.MediaStatus.InvalidMedia:
            self.failed.emit("这个音频流放不了，试试下一首")
        self.changed.emit()

    def _on_error(self, *_args) -> None:
        try:
            import logging
            q = self.qmp
            logging.getLogger("player").warning(
                "播放出错 error=%s msg=%s state=%s status=%s src=%s",
                int(q.error()), q.errorString(), int(q.playbackState()),
                int(q.mediaStatus()), q.source().toString()[:80])
        except Exception:  # noqa: BLE001
            pass
        self.changed.emit()

    # ---------------- 控制 ----------------
    def toggle(self) -> None:
        if self.qmp.playbackState() == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState:
            self.qmp.pause()
        else:
            if self.qmp.source().isEmpty() and self.queue:
                self.play_index(max(0, self.index))
            elif self._device_stale():
                self.rebind_output(play_if_stopped=True)
            else:
                self.qmp.play()

    def pause(self) -> None:
        self.qmp.pause()

    def next(self, auto: bool = False) -> None:
        if not self.queue:
            return
        i = self.index + 1
        if i >= len(self.queue):
            i = 0 if auto else len(self.queue) - 1
        self.play_index(i)

    def prev(self) -> None:
        if not self.queue:
            return
        self.play_index(max(0, self.index - 1))

    def seek(self, ms: int) -> None:
        self.qmp.setPosition(max(0, int(ms)))

    def set_volume(self, v: float) -> None:
        self.volume = max(0.0, min(1.0, float(v)))
        self.out.setVolume(self.volume)

    # ---------------- 换输出设备 ----------------
    def _device_stale(self) -> bool:
        """当前音频输出挂的设备，还是不是系统现在认定的默认那台。"""
        try:
            cur = self.out.device()
            want = QtMultimedia.QMediaDevices.defaultAudioOutput()
            if cur.isNull() or want.isNull():
                return False
            return cur.id() != want.id()
        except Exception:  # noqa: BLE001
            return False

    def rebind_output(self, play_if_stopped: bool = False) -> bool:
        """系统默认输出设备换了：把音频输出重建一遍，让声音跟着新设备走。

        QAudioOutput 创建那一刻就绑死了当时的默认设备，系统默认换掉以后
        已经在播的流不会自己迁过去，所以只能重建（这次是别的播放器的通病，
        我们靠这一下补上）。
        """
        pl = self.qmp
        if pl is None or self._rebinding:
            return False
        src = pl.source()
        if src.isEmpty():
            return False
        pos = max(0, int(pl.position()))
        state = pl.playbackState()
        was_playing = state == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState
        was_paused = state == QtMultimedia.QMediaPlayer.PlaybackState.PausedState
        if not (was_playing or was_paused) and not play_if_stopped:
            # 停着没播，下次开播自然就用新设备了
            return False

        self._rebinding = True
        self._pending_pos = pos
        self._pending_play = was_playing or play_if_stopped
        self._pending_pause = was_paused

        self._new_qmp()
        self.qmp.setSource(src)
        self.qmp.mediaStatusChanged.connect(self._rebind_loaded)
        # 兜底：网络慢的时候媒体状态迟迟不报 loaded，也别一直不响
        QtCore.QTimer.singleShot(1500, self._rebind_go)
        return True

    def _rebind_loaded(self, status) -> None:
        mst = QtMultimedia.QMediaPlayer.MediaStatus
        if status in (mst.LoadedMedia, mst.BufferedMedia, mst.BufferingMedia):
            self._rebind_go()

    def _rebind_go(self) -> None:
        if not self._rebinding:
            return
        self._rebinding = False
        try:
            self.qmp.mediaStatusChanged.disconnect(self._rebind_loaded)
        except Exception:  # noqa: BLE001
            pass
        try:
            pos = self._pending_pos
            dur = self.qmp.duration()
            if dur > 0 and pos >= dur - 600:
                pos = 0   # 已经停在末尾了，就从头上重放，别一开播就结束
            if pos > 0:
                self.qmp.setPosition(pos)
            if self._pending_play:
                self.qmp.play()
            elif getattr(self, "_pending_pause", False):
                self.qmp.pause()
        except Exception:  # noqa: BLE001
            pass
        self.changed.emit()

    def stop_silent(self) -> None:
        self.qmp.stop()
        self.queue = []
        self.index = -1
        self.current = {}
        self.changed.emit()

    # ---------------- 读 ----------------
    def state(self) -> Dict:
        return {
            "pos": self.qmp.position(),
            "dur": self.qmp.duration(),
            "playing": self.qmp.playbackState()
            == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState,
            "loading": self._loading,
            "index": self.index,
            "total": len(self.queue),
            "track": self.current,
            "volume": self.volume,
        }
