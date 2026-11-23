"""图标：优先读取 assets/icon.ico（可随时替换），没有则用代码绘制兜底。"""

from __future__ import annotations

import struct
import sys
from pathlib import Path
from typing import List, Optional

from PySide6 import QtCore, QtGui
from PySide6.QtCore import Qt

SIZES = (16, 24, 32, 48, 64, 128, 256)


def _asset_dirs() -> List[Path]:
    dirs: List[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        dirs.append(Path(meipass) / "assets")
    try:
        from core.store import app_dir

        dirs.append(app_dir() / "assets")
    except Exception:
        pass
    dirs.append(Path(__file__).resolve().parent.parent / "assets")
    return dirs


def icon_path() -> Optional[Path]:
    """找到可用的 icon.ico。exe 同目录的 assets 优先，方便你换图标不用重新打包。"""
    for d in _asset_dirs():
        p = d / "icon.ico"
        try:
            if p.exists() and p.stat().st_size > 1024:
                return p
        except OSError:
            continue
    return None


# ---------------------------------------------------------------------------
# 代码绘制的兜底图标
# ---------------------------------------------------------------------------
def _paint(size: int) -> QtGui.QImage:
    img = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32)
    img.fill(Qt.transparent)

    p = QtGui.QPainter(img)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)

    rect = QtCore.QRectF(2, 2, size - 4, size - 4)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#0f1116"))
    p.drawRoundedRect(rect, size * 0.22, size * 0.22)

    pen = QtGui.QPen(QtGui.QColor("#20ffe0"))
    pen.setWidthF(size * 0.045)
    p.setPen(pen)
    inner = QtCore.QRectF(size * 0.20, size * 0.27, size * 0.60, size * 0.44)
    p.setBrush(QtGui.QColor(32, 255, 224, 28))
    p.drawRoundedRect(inner, size * 0.05, size * 0.05)

    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#20ffe0"))
    p.drawRect(QtCore.QRectF(size * 0.44, size * 0.73, size * 0.12, size * 0.055))
    p.drawRect(QtCore.QRectF(size * 0.33, size * 0.79, size * 0.34, size * 0.045))

    p.setBrush(QtGui.QColor("#a855f7"))
    p.drawEllipse(QtCore.QPointF(size * 0.78, size * 0.76), size * 0.045, size * 0.045)

    p.end()
    return img


def app_icon() -> QtGui.QIcon:
    p = icon_path()
    if p is not None:
        icon = QtGui.QIcon(str(p))
        if not icon.isNull():
            return icon
    icon = QtGui.QIcon()
    for s in SIZES:
        icon.addPixmap(QtGui.QPixmap.fromImage(_paint(s)))
    return icon


# ---------------------------------------------------------------------------
# 生成 ico（打包 / 换图标用）
# ---------------------------------------------------------------------------
def _png_bytes(image: QtGui.QImage) -> bytes:
    buf = QtCore.QByteArray()
    device = QtCore.QBuffer(buf)
    device.open(QtCore.QIODevice.WriteOnly)
    image.save(device, "PNG")
    device.close()
    return bytes(buf)


def save_ico_multi(image: QtGui.QImage, path: str | Path, sizes=SIZES) -> bool:
    """把一张图导出为多尺寸 .ico（每个条目内嵌 PNG）。"""
    try:
        blobs = []
        for s in sizes:
            scaled = image.scaled(
                s, s, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            blobs.append((s, _png_bytes(scaled)))

        header = struct.pack("<HHH", 0, 1, len(blobs))
        offset = 6 + 16 * len(blobs)
        entries = b""
        data = b""
        for s, blob in blobs:
            w = 0 if s >= 256 else s
            h = 0 if s >= 256 else s
            entries += struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(blob), offset)
            offset += len(blob)
            data += blob

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(header + entries + data)
        return True
    except (OSError, ValueError):
        return False


def save_ico(path: str | Path, size: int = 256) -> bool:
    """兼容旧调用：用兜底绘制的图标导出多尺寸 ico。"""
    return save_ico_multi(_paint(size), path)
