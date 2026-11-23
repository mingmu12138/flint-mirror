"""立绘：主界面右下角那张陪衬的图。

用户自己往 `art` 文件夹里扔图片就行（png / jpg / webp 都认），
也可以在设置里直接选一张，会自动拷进去。

这里只管"读、缩、压暗"三件事，位置由主窗口算。
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import List, Optional

from PySide6 import QtCore, QtGui

from .store import app_dir

log = logging.getLogger("gamehub")

SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
# 默认压到这个透明度：能看清人，又不至于把后面的字搅花
DEFAULT_OPACITY = 0.70
# 立绘占窗口宽度的比例（右下角，贴底）
WIDTH_RATIO = 0.42


def art_dir() -> Path:
    return app_dir() / "art"


def ensure_dir() -> Path:
    d = art_dir()
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError as exc:  # noqa: BLE001
        log.warning("立绘目录建不起来：%s", exc)
    return d


def list_files() -> List[Path]:
    d = art_dir()
    if not d.is_dir():
        return []
    try:
        return [p for p in sorted(d.iterdir()) if p.suffix.lower() in SUFFIXES and p.is_file()]
    except OSError:
        return []


def resolve(name: str) -> Optional[Path]:
    """配置里存的是文件名就查 art 目录；存的是绝对路径就直接用。"""
    if not name:
        return None
    p = Path(name)
    if p.is_absolute():
        return p if p.is_file() else None
    for cand in (art_dir() / name, app_dir() / name):
        if cand.is_file():
            return cand
    return None


def import_file(src: str | Path) -> Optional[str]:
    """把用户的图片拷进 art 目录，返回存下来的文件名。"""
    src = Path(src)
    if not src.is_file() or src.suffix.lower() not in SUFFIXES:
        return None
    d = ensure_dir()
    name = src.name
    dst = d / name
    if dst.exists() and dst.resolve() != src.resolve():
        # 同名就加个序号，别覆盖人家原来的
        stem, suffix = src.stem, src.suffix
        for i in range(2, 100):
            cand = d / f"{stem}_{i}{suffix}"
            if not cand.exists():
                dst = cand
                name = cand.name
                break
    try:
        if dst.resolve() != src.resolve():
            shutil.copy2(src, dst)
        return name
    except OSError as exc:  # noqa: BLE001
        log.warning("立绘拷不过来：%s", exc)
        return None


def _blur_pixmap(pm: QtGui.QPixmap, radius: float) -> QtGui.QPixmap:
    """真高斯模糊：拿 QGraphicsBlurEffect 渲一遍，出来是糊的。"""
    from PySide6 import QtWidgets

    scene = QtWidgets.QGraphicsScene()
    item = QtWidgets.QGraphicsPixmapItem(pm)
    eff = QtWidgets.QGraphicsBlurEffect()
    eff.setBlurRadius(float(radius))
    eff.setBlurHints(QtWidgets.QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(eff)
    scene.addItem(item)
    out = QtGui.QImage(pm.size(), QtGui.QImage.Format_ARGB32_Premultiplied)
    out.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(out)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    scene.render(p, QtCore.QRectF(out.rect()), QtCore.QRectF(pm.rect()))
    p.end()
    return QtGui.QPixmap.fromImage(out)


def load(path: Optional[Path], size: QtCore.QSize, opacity: float = DEFAULT_OPACITY,
         tint: str = "", darken: float = 0.30,
         blur: float = 0.0) -> Optional[QtGui.QPixmap]:
    """读图 → 等比缩进 size → 混一层背景色压暗 → 整体压到指定不透明度。

    tint 给背景色（比如 #0e1015），压暗后人物不会在深色界面上晃眼，
    白裙也不会把白字顶得看不清。不传 tint 就只做透明度。
    """
    if path is None or not size.isValid() or size.width() < 8 or size.height() < 8:
        return None
    pm = QtGui.QPixmap(str(path))
    if pm.isNull():
        return None
    if pm.width() <= 0 or pm.height() <= 0:
        return None
    # 铺满整窗：先放大到能盖住，再把多出来的两边居中裁掉
    scale = max(size.width() / pm.width(), size.height() / pm.height())
    if scale <= 0:
        return None
    target = QtCore.QSize(
        max(1, int(pm.width() * scale) + 1), max(1, int(pm.height() * scale) + 1)
    )
    pm = pm.scaled(target, QtCore.Qt.KeepAspectRatioByExpanding,
                   QtCore.Qt.SmoothTransformation)
    if pm.width() > size.width() or pm.height() > size.height():
        cx = max(0, (pm.width() - size.width()) // 2)
        cy = 0
        pm = pm.copy(cx, cy, min(size.width(), pm.width()), min(size.height(), pm.height()))

    if blur and blur > 0:
        pm = _blur_pixmap(pm, blur)

    # 第一层：原图 + 叠背景色压暗
    mid = QtGui.QPixmap(pm.size())
    mid.fill(QtCore.Qt.transparent)
    p1 = QtGui.QPainter(mid)
    p1.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p1.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
    p1.drawPixmap(0, 0, pm)
    if tint and darken > 0:
        p1.setCompositionMode(QtGui.QPainter.CompositionMode_SourceAtop)
        tint_color = QtGui.QColor(tint)
        if tint_color.isValid():
            tint_color.setAlphaF(max(0.0, min(1.0, darken)))
            p1.fillRect(mid.rect(), tint_color)
        p1.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
    p1.end()

    # 第二层：整体透明度
    out = QtGui.QPixmap(mid.size())
    out.fill(QtCore.Qt.transparent)
    p2 = QtGui.QPainter(out)
    p2.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p2.setOpacity(max(0.05, min(1.0, opacity)))
    p2.drawPixmap(0, 0, mid)
    p2.end()
    return out


def target_size(window_w: int, window_h: int) -> QtCore.QSize:
    """整窗铺满，跟桌面壁纸一个意思。"""
    return QtCore.QSize(max(200, int(window_w)), max(200, int(window_h)))
