"""截图：抓取屏幕 / 前台窗口 / 拖框选区，并自动按日期归档。

目录结构：
    素材\截图\2026-11-19\15-32-08_全屏.png
    素材\录像\2026-11-19\……            （录屏模块写入）

设计取舍：
  - 抓屏用 Qt 的 grabWindow，不用第三方库；
  - 窗口截图取「前台窗口矩形」再裁剪，不依赖游戏是否允许 PrintWindow；
  - 归档一律按 素材/类型/日期 分层，文件名以时间开头，天生可排序。
"""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from pathlib import Path
from typing import List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from .store import app_dir

SHOT_DIR = "截图"
VIDEO_DIR = "录像"
ROOT_DIR = "素材"

user32 = ctypes.WinDLL("user32", use_last_error=True)


# ---------------------------------------------------------------- 目录与命名
_CUSTOM_ROOT: Optional[Path] = None


def set_root(path) -> None:
    """把素材根目录挪到别处（空 = 回到程序目录下的「素材」）。"""
    global _CUSTOM_ROOT
    if path:
        try:
            p = Path(str(path))
            p.mkdir(parents=True, exist_ok=True)
            _CUSTOM_ROOT = p
            return
        except OSError:
            pass
    _CUSTOM_ROOT = None


def custom_root() -> Optional[Path]:
    return _CUSTOM_ROOT


def media_root() -> Path:
    if _CUSTOM_ROOT is not None:
        return _CUSTOM_ROOT
    return app_dir() / ROOT_DIR


def day_dir(kind: str, when: Optional[time.struct_time] = None) -> Path:
    when = when or time.localtime()
    path = media_root() / kind / time.strftime("%Y-%m-%d", when)
    path.mkdir(parents=True, exist_ok=True)
    return path


def shot_path(label: str = "全屏") -> Path:
    stamp = time.strftime("%H-%M-%S")
    path = day_dir(SHOT_DIR) / f"{stamp}_{label}.png"
    # 同一秒内连拍时避免覆盖
    if path.exists():
        for i in range(2, 100):
            path = day_dir(SHOT_DIR) / f"{stamp}_{label}_{i}.png"
            if not path.exists():
                break
    return path


def video_path(label: str = "录像") -> Path:
    stamp = time.strftime("%H-%M-%S")
    path = day_dir(VIDEO_DIR) / f"{stamp}_{label}.mp4"
    if path.exists():
        for i in range(2, 100):
            path = day_dir(VIDEO_DIR) / f"{stamp}_{label}_{i}.mp4"
            if not path.exists():
                break
    return path


def save_pixmap(pixmap: QtGui.QPixmap, label: str = "全屏") -> Optional[Path]:
    if pixmap is None or pixmap.isNull():
        return None
    path = shot_path(label)
    if not pixmap.save(str(path), "PNG"):
        return None
    return path


# ---------------------------------------------------------------- 屏幕抓取
def current_screen() -> QtGui.QScreen:
    screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
    if screen is None:
        screen = QtGui.QGuiApplication.primaryScreen()
    return screen


def grab_screen() -> tuple[QtGui.QPixmap, QtCore.QRect]:
    screen = current_screen()
    geo = screen.geometry()
    return screen.grabWindow(0), geo


def grab_foreground_window() -> Optional[QtGui.QPixmap]:
    """抓当前前台窗口：先整屏截，再按窗口矩形裁。"""
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return None
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width < 80 or height < 80:
            return None

        pixmap, geo = grab_screen()
        offset = QtCore.QPoint(rect.left - geo.x(), rect.top - geo.y())
        area = QtCore.QRect(offset, QtCore.QSize(width, height))
        area = area.intersected(pixmap.rect())
        if area.width() < 40 or area.height() < 40:
            return None
        return pixmap.copy(area)
    except Exception:
        return None


# ---------------------------------------------------------------- 框选
class RegionPicker(QtWidgets.QWidget):
    """全屏遮罩，按住鼠标拖出选区。

    松开先不落盘：选区内留着亮图，右下角给一个对勾一个叉号，
    点对勾才回调保存，点叉号 / Esc / 右键都算放弃 —— 跟系统截图一个手感。
    """

    BTN = 25          # 按钮半径（逻辑像素）
    GAP = 12          # 两个按钮之间留的空

    def __init__(self, pixmap: QtGui.QPixmap, geo: QtCore.QRect, on_done, on_cancel=None):
        super().__init__(
            None,
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.WindowStaysOnTopHint | QtCore.Qt.Tool,
        )
        self.setAttribute(QtCore.Qt.WA_DeleteOnClose, True)
        self.setCursor(QtCore.Qt.CrossCursor)
        self.setGeometry(geo)
        self._pixmap = pixmap
        self._geo = geo
        self._on_done = on_done
        self._on_cancel = on_cancel
        self._origin: Optional[QtCore.QPoint] = None
        self._current: Optional[QtCore.QPoint] = None
        self._pending: Optional[QtCore.QRect] = None   # 已框好、等确认的选区
        self._hover = ""                                # "ok" / "no" / ""

    # ------------------------------------------------------------ 布局
    def _btn_centers(self):
        """对勾 / 叉号的圆心，默认贴选区右下外侧，出屏就往里收。"""
        rect = self._pending
        if rect is None:
            return None
        r = self.BTN
        ok = QtCore.QPoint(
            min(rect.right() - r - 4, self.width() - r - 6),
            rect.bottom() + self.GAP + r + 2,
        )
        if ok.y() + r > self.height() - 6:
            ok = QtCore.QPoint(ok.x(), rect.bottom() - r - 6)
        if ok.y() - r < 6:
            ok = QtCore.QPoint(ok.x(), rect.top() + r + 6)
        no = QtCore.QPoint(ok.x() - 2 * r - self.GAP, ok.y())
        if no.x() - r < 6:
            no = QtCore.QPoint(ok.x() + 2 * r + self.GAP, ok.y())
            if no.x() + r > self.width() - 6:
                no = QtCore.QPoint(ok.x(), ok.y() + 2 * r + self.GAP)
        return ok, no

    def _hit(self, pos) -> str:
        c = self._btn_centers()
        if not c:
            return ""
        for tag, p in (("ok", c[0]), ("no", c[1])):
            dx = pos.x() - p.x()
            dy = pos.y() - p.y()
            if dx * dx + dy * dy <= (self.BTN + 3) ** 2:
                return tag
        return ""

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, True)
        painter.drawPixmap(self.rect(), self._pixmap)

        if self._pending is not None:
            # 选区之外压暗，选区里面保持原亮 —— 这样看得清拍的是什么
            clip = QtGui.QRegion(self.rect()).subtracted(QtGui.QRegion(self._pending))
            painter.save()
            painter.setClipRegion(clip)
            painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 118))
            painter.restore()
        else:
            painter.fillRect(self.rect(), QtGui.QColor(0, 0, 0, 110))

        rect = self._pending
        if rect is None and self._origin and self._current:
            rect = QtCore.QRect(self._origin, self._current).normalized()

        if rect is not None and not rect.isNull():
            if self._pending is not None:
                painter.drawPixmap(rect, self._pixmap, QtCore.QRect(rect))
            painter.setPen(QtGui.QPen(QtGui.QColor("#20ffe0"), 2))
            painter.drawRect(rect)
            painter.setPen(QtGui.QColor("#e8f0ff"))
            font = painter.font()
            font.setPointSize(10)
            painter.setFont(font)
            painter.drawText(
                QtCore.QPoint(rect.left() + 6, max(rect.top() - 8, 14)),
                f"{rect.width()} × {rect.height()}",
            )

        if self._pending is not None:
            self._paint_buttons(painter)

    def _paint_buttons(self, painter) -> None:
        c = self._btn_centers()
        if not c:
            return
        okc, noc = c
        r = self.BTN
        for tag, center, good in (("ok", okc, True), ("no", noc, False)):
            hot = self._hover == tag
            face = QtGui.QColor(18, 34, 38, 245 if hot else 226)
            edge = QtGui.QColor("#20ffe0") if good else QtGui.QColor("#ff6b6b")
            if hot:
                edge = edge.lighter(120)
            painter.setBrush(face)
            painter.setPen(QtGui.QPen(edge, 2))
            painter.drawEllipse(center, r, r)
            painter.setPen(QtGui.QPen(edge, 2.4))
            if good:
                a = QtCore.QPoint(center.x() - 8, center.y() + 1)
                b = QtCore.QPoint(center.x() - 2, center.y() + 7)
                d = QtCore.QPoint(center.x() + 9, center.y() - 7)
                painter.drawLine(a, b)
                painter.drawLine(b, d)
            else:
                k = 7
                painter.drawLine(QtCore.QPoint(center.x() - k, center.y() - k),
                                 QtCore.QPoint(center.x() + k, center.y() + k))
                painter.drawLine(QtCore.QPoint(center.x() + k, center.y() - k),
                                 QtCore.QPoint(center.x() - k, center.y() + k))

        painter.setPen(QtGui.QColor(220, 232, 240, 210))
        font = painter.font()
        font.setPointSize(9)
        painter.setFont(font)
        painter.drawText(
            QtCore.QPoint(okc.x() - 62, okc.y() + self.BTN + 16),
            "回车保存 · Esc 放弃",
        )

    # ------------------------------------------------------------ 交互
    def mousePressEvent(self, event) -> None:
        pos = event.position().toPoint()
        if event.button() == QtCore.Qt.RightButton:
            self._cancel()
            return
        if event.button() != QtCore.Qt.LeftButton:
            return
        if self._pending is not None:
            hit = self._hit(pos)
            if hit == "ok":
                self._commit()
                return
            if hit == "no":
                self._cancel()
                return
            # 点在别处 = 重框一次
            self._pending = None
            self._hover = ""
            self.setCursor(QtCore.Qt.CrossCursor)
        self._origin = pos
        self._current = pos
        self.update()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position().toPoint()
        if self._pending is not None:
            hit = self._hit(pos)
            if hit != self._hover:
                self._hover = hit
                self.setCursor(
                    QtCore.Qt.PointingHandCursor if hit else QtCore.Qt.CrossCursor
                )
                self.update()
            return
        if self._origin is not None:
            self._current = pos
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._pending is not None or event.button() != QtCore.Qt.LeftButton:
            return
        if self._origin is None:
            return
        rect = QtCore.QRect(self._origin, event.position().toPoint()).normalized()
        self._origin = None
        self._current = None
        if rect.width() >= 8 and rect.height() >= 8:
            area = rect.intersected(self._pixmap.rect())
            if not area.isEmpty():
                self._pending = area
                self.update()
                return
        self._cancel()

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == QtCore.Qt.Key_Escape:
            self._cancel()
            return
        if key in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and self._pending is not None:
            self._commit()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------ 收尾
    def _commit(self) -> None:
        area = self._pending
        self._pending = None
        self.hide()
        try:
            if area is not None and not area.isEmpty() and self._on_done:
                self._on_done(self._pixmap.copy(area), area)
        finally:
            self.close()

    def _cancel(self) -> None:
        self._pending = None
        try:
            if self._on_cancel:
                self._on_cancel()
        finally:
            self.close()


# ---------------------------------------------------------------- 素材列表
def _fmt_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size} B"


_PROBE_CACHE: dict = {}


def _boxes(f, start: int, end: int):
    """在 [start, end) 范围里逐个吐 (类型, 内容起点, 内容终点)。"""
    pos = start
    while pos < end:
        f.seek(pos)
        head = f.read(8)
        if len(head) < 8:
            return
        size = int.from_bytes(head[0:4], "big")
        typ = head[4:8].decode("ascii", "replace")
        hdr = 8
        if size == 1:  # 64 位长度
            more = f.read(8)
            if len(more) < 8:
                return
            size = int.from_bytes(more, "big")
            hdr = 16
        elif size == 0:  # 一直到文件尾
            size = end - pos
        if size < hdr:
            return
        yield typ, pos + hdr, pos + size
        pos += size


def probe_video(path: Path) -> tuple:
    """读 mp4 的 (时长秒, 有没有音轨)。

    纯 Python 扫 moov，不调 ffprobe（内置 ffmpeg 是单文件，没有 probe）。
    读不出来给 (None, None)：文件太小、缺 moov（录到一半断了）都算。
    """
    try:
        st = path.stat()
    except OSError:
        return (None, None)
    key = (str(path), st.st_size, int(st.st_mtime))
    cached = _PROBE_CACHE.get(key)
    if cached is not None:
        return cached

    result = (None, None)
    try:
        if st.st_size > 1024:
            with open(path, "rb") as f:
                moov = None
                for typ, s0, s1 in _boxes(f, 0, st.st_size):
                    if typ == "moov":
                        moov = (s0, s1)
                        break
                if moov is not None:
                    duration = None
                    audio = False
                    for typ, s0, s1 in _boxes(f, moov[0], moov[1]):
                        if typ == "mvhd":
                            f.seek(s0)
                            head = f.read(24)
                            if head:
                                if head[0] == 1:  # version 1：64 位时间
                                    body = f.read(12)
                                    if len(body) >= 12:
                                        ts = int.from_bytes(body[0:4], "big")
                                        dur = int.from_bytes(body[4:12], "big")
                                        duration = dur / ts if ts else None
                                elif len(head) >= 20:
                                    ts = int.from_bytes(head[12:16], "big")
                                    dur = int.from_bytes(head[16:20], "big")
                                    duration = dur / ts if ts else None
                        elif typ == "trak":
                            for t2, a0, a1 in _boxes(f, s0, s1):
                                if t2 != "mdia":
                                    continue
                                for t3, b0, b1 in _boxes(f, a0, a1):
                                    if t3 == "hdlr":
                                        f.seek(b0)
                                        hb = f.read(12)
                                        if len(hb) >= 12 and hb[8:12] == b"soun":
                                            audio = True
                    result = (duration, audio)
    except (OSError, ValueError):
        result = (None, None)

    if len(_PROBE_CACHE) > 4096:
        _PROBE_CACHE.clear()
    _PROBE_CACHE[key] = result
    return result


def fmt_duration(seconds: Optional[float]) -> str:
    """秒 → 0:07 / 2:31 / 1:12:40。"""
    if not seconds or seconds <= 0:
        return ""
    total = int(round(seconds))
    if total >= 3600:
        return f"{total // 3600}:{(total % 3600) // 60:02d}:{total % 60:02d}"
    return f"{total // 60}:{total % 60:02d}"


def list_by_day(kinds: tuple = (SHOT_DIR, VIDEO_DIR)) -> List[dict]:
    """返回 [{date, items:[{path, name, kind, size, size_text, mtime}]}]，新日期在前。"""
    root = media_root()
    days: dict[str, dict] = {}

    for kind in kinds:
        base = root / kind
        if not base.exists():
            continue
        for day in base.iterdir():
            if not day.is_dir():
                continue
            for f in day.iterdir():
                if not f.is_file():
                    continue
                if f.suffix.lower() not in (".png", ".jpg", ".jpeg", ".mp4", ".mkv", ".avi"):
                    continue
                try:
                    stat = f.stat()
                except OSError:
                    continue
                key = day.name
                entry = days.setdefault(key, {"date": key, "items": []})
                item = {
                    "path": f,
                    "name": f.name.replace(f"{key}_", ""),
                    "kind": kind,
                    "size": stat.st_size,
                    "size_text": _fmt_size(stat.st_size),
                    "mtime": stat.st_mtime,
                    "is_video": f.suffix.lower() in (".mp4", ".mkv", ".avi"),
                    "duration": None,
                    "has_audio": None,
                }
                if item["is_video"]:
                    dur, audio = probe_video(f)
                    item["duration"] = dur
                    item["has_audio"] = audio
                entry["items"].append(item)

    for entry in days.values():
        entry["items"].sort(key=lambda x: x["mtime"], reverse=True)
        entry["count"] = len(entry["items"])

    return [days[k] for k in sorted(days.keys(), reverse=True)]
