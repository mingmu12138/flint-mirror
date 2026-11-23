# -*- coding: utf-8 -*-
"""桌面音乐悬浮条：播放时贴在屏幕边上的小条，只有四个按钮。

和主窗口里的灵动岛（MiniPlayer）不是一回事：
  · 灵动岛在主窗口里面，切页面时浮在窗口中间
  · 这条是独立的桌面窗口（跟帧率窗、每日密码窗同一类），主窗口收进托盘也照样能用

规矩：
  · 没歌在放就不露头；一旦有歌（播放或暂停都算）就出来
  · 上一首 / 播放暂停 / 下一首 / 关闭
  · 按着左边那块把手能拖，拖到屏幕左 / 右边缘松开就自动贴边收成一条，
    鼠标碰到再自己展开，走开两秒又收回去
  · 点「关闭」只是这一首期间不露头，换下一首会再出来
"""

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

W_FULL = 258
H_FULL = 44
W_TUCK = 9          # 收到边上之后留在屏幕里的宽度
SNAP = 22           # 松开时离屏幕边缘小于这个就算"要贴边"
AWAY_MS = 1800      # 鼠标走开多久后收回


def _bar_icon(kind: str, size: int = 13, color: str = "#eaf6ff") -> QtGui.QIcon:
    """四个按钮的图标都用 QPainter 现画，不依赖 gui.py 里那套资源函数。"""
    pm = QtGui.QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    c = QtGui.QColor(color)
    s = size
    if kind == "play":
        poly = QtGui.QPolygonF([
            QtCore.QPointF(s * 0.30, s * 0.18),
            QtCore.QPointF(s * 0.30, s * 0.82),
            QtCore.QPointF(s * 0.80, s * 0.50),
        ])
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        p.drawPolygon(poly)
    elif kind == "pause":
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        bw = s * 0.14
        p.drawRoundedRect(QtCore.QRectF(s * 0.28, s * 0.20, bw, s * 0.60), 1.6, 1.6)
        p.drawRoundedRect(QtCore.QRectF(s * 0.58, s * 0.20, bw, s * 0.60), 1.6, 1.6)
    elif kind in ("prev", "next"):
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        if kind == "prev":
            p.drawPolygon(QtGui.QPolygonF([
                QtCore.QPointF(s * 0.72, s * 0.18),
                QtCore.QPointF(s * 0.72, s * 0.82),
                QtCore.QPointF(s * 0.26, s * 0.50),
            ]))
            p.drawRect(QtCore.QRectF(s * 0.20, s * 0.18, s * 0.08, s * 0.64))
        else:
            p.drawPolygon(QtGui.QPolygonF([
                QtCore.QPointF(s * 0.28, s * 0.18),
                QtCore.QPointF(s * 0.28, s * 0.82),
                QtCore.QPointF(s * 0.74, s * 0.50),
            ]))
            p.drawRect(QtCore.QRectF(s * 0.72, s * 0.18, s * 0.08, s * 0.64))
    p.end()
    return QtGui.QIcon(pm)


class MusicBar(QtWidgets.QWidget):
    """屏幕上的那条音乐悬浮条。"""

    def __init__(self, player, cfg) -> None:
        super().__init__(
            None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
        )
        self.player = player
        self.cfg = cfg
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowTitle("燧镜 · 音乐条")

        self._key = None          # 当前这首歌，用来判断是不是换歌了
        self._title_full = ""     # 完整歌名，显示时按宽度截
        self._dismissed = False   # 点过关闭：这首歌期间不露头
        self._edge = str(getattr(cfg, "bar_side", "") or "")
        self._collapsed = False
        self._dragging = False
        self._drag_off = QtCore.QPoint()

        self.setFixedSize(W_FULL, H_FULL)

        shell = QtWidgets.QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.setSpacing(0)

        self.card = QtWidgets.QFrame()
        self.card.setObjectName("MusicBarCard")
        self.card.setStyleSheet(
            "QFrame#MusicBarCard{background:rgba(10,14,22,.88);"
            "border:1px solid rgba(32,255,224,.42);border-radius:22px;}"
        )
        shell.addWidget(self.card)

        self.inner = QtWidgets.QWidget()
        il = QtWidgets.QHBoxLayout(self.inner)
        il.setContentsMargins(8, 0, 8, 0)
        il.setSpacing(4)
        card_lay = QtWidgets.QHBoxLayout(self.card)
        card_lay.setContentsMargins(0, 0, 0, 0)
        card_lay.addWidget(self.inner)

        # 左边的把手：按住这里拖，别的地方是按钮
        self.grip = QtWidgets.QFrame()
        self.grip.setFixedWidth(12)
        self.grip.setCursor(Qt.SizeAllCursor)
        self.grip.setToolTip("整条都能按住拖，拖到屏幕左 / 右边缘松开就自动贴边收起")
        self.grip.installEventFilter(self)
        il.addWidget(self.grip)

        self.tit = QtWidgets.QLabel("")
        self.tit.setStyleSheet(
            "font-size:12px;color:#dcecfa;background:transparent;"
        )
        self.tit.setMinimumWidth(0)
        self.tit.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tit.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred
        )
        il.addWidget(self.tit, 1)

        self.btn_prev = self._mk_btn("prev", "上一首", self._prev)
        self.btn_play = self._mk_btn("play", "播放 / 暂停", self._toggle)
        self.btn_next = self._mk_btn("next", "下一首", self._next)
        il.addWidget(self.btn_prev, 0)
        il.addWidget(self.btn_play, 0)
        il.addWidget(self.btn_next, 0)

        self.btn_close = QtWidgets.QPushButton("✕")
        self.btn_close.setCursor(Qt.PointingHandCursor)
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.setToolTip("关掉（下一首会再出来）")
        self.btn_close.setStyleSheet(
            "QPushButton{border:none;background:transparent;color:#7f92a6;"
            "font-size:13px;padding:0px;}"
            "QPushButton:hover{color:#ff8a8a;}"
        )
        self.btn_close.clicked.connect(self.dismiss)
        il.addWidget(self.btn_close, 0, Qt.AlignVCenter)

        self._leave = QtCore.QTimer(self)
        self._leave.setSingleShot(True)
        self._leave.setInterval(AWAY_MS)
        self._leave.timeout.connect(self._maybe_collapse)

        if player is not None and hasattr(player, "changed"):
            player.changed.connect(self.sync)

        # 所有子控件都建完了再挂监听，整条空白处才都能拖
        self.card.installEventFilter(self)

    # --------------------------------------------------------- 小工具
    def _mk_btn(self, kind: str, tip: str, slot) -> QtWidgets.QPushButton:
        b = QtWidgets.QPushButton()
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedSize(30, 30)
        b.setIconSize(QtCore.QSize(13, 13))
        b.setIcon(_bar_icon(kind))
        b.setToolTip(tip)
        b.setStyleSheet(
            "QPushButton{border:none;border-radius:15px;background:transparent;padding:0px;}"
            "QPushButton:hover{background:rgba(255,255,255,.10);}"
            "QPushButton:pressed{background:rgba(32,255,224,.22);}"
        )
        b.clicked.connect(slot)
        return b

    def _screen(self) -> QtGui.QScreen:
        scr = self.screen()
        return scr or QtGui.QGuiApplication.primaryScreen()

    # --------------------------------------------------------- 开关
    def set_enabled(self, on: bool) -> None:
        self.cfg.bar_on = bool(on)
        self.cfg.save()
        if not on:
            self.hide()
            return
        self._dismissed = False
        self.sync()

    def dismiss(self) -> None:
        self._dismissed = True
        self.hide()

    # --------------------------------------------------------- 跟随播放
    def sync(self, *_a) -> None:
        if not bool(getattr(self.cfg, "bar_on", True)):
            self.hide()
            return
        p = self.player
        if p is None:
            self.hide()
            return
        try:
            st = p.state()
        except Exception:  # noqa: BLE001
            self.hide()
            return
        track = st.get("track") or {}
        name = track.get("name") or ""
        if not name:
            self.hide()
            return
        key = (name, track.get("artist") or "")
        if key != self._key:
            self._key = key
            self._dismissed = False
        if self._dismissed:
            self.hide()
            return
        self._title_full = name
        self._fit_title()
        playing = bool(st.get("playing"))
        self.btn_play.setIcon(_bar_icon("pause" if playing else "play"))
        self.btn_play.setToolTip("暂停" if playing else "播放")
        if not self.isVisible():
            self._place()
            self.show()

    def _fit_title(self) -> None:
        """按当下宽度截歌名，尾巴加省略号；完整名字放 tooltip 里。"""
        full = self._title_full or "没在放歌"
        self.tit.setToolTip(full)
        w = max(20, self.tit.width() - 2)
        f = self.tit.font()
        f.setPixelSize(12)
        fm = QtGui.QFontMetrics(f)
        self.tit.setText(fm.elidedText(full, Qt.ElideRight, w))

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._fit_title()

    # --------------------------------------------------------- 位置 / 贴边
    def _place(self) -> None:
        saved = getattr(self.cfg, "bar_pos", []) or []
        g = self._screen().availableGeometry()
        if isinstance(saved, (list, tuple)) and len(saved) >= 2:
            x = max(g.left(), min(int(saved[0]), g.right() - W_FULL))
            y = max(g.top(), min(int(saved[1]), g.bottom() - H_FULL))
            self.move(x, y)
        else:
            # 第一次：屏幕右侧、偏上一点，先摊开让人看见
            self.move(g.right() - W_FULL - 24, g.top() + int(g.height() * 0.28))
        if self._edge:
            self._pin()
            self.collapse()

    def _pin(self) -> None:
        if not self._edge:
            return
        g = self._screen().availableGeometry()
        y = max(g.top(), min(self.y(), g.bottom() - H_FULL))
        x = g.left() if self._edge == "left" else g.right() - self.width() + 1
        self.move(x, y)

    def _save_pos(self) -> None:
        self.cfg.bar_pos = [self.x(), self.y()]
        self.cfg.bar_side = self._edge
        self.cfg.save()

    def collapse(self) -> None:
        if not self._edge or self._collapsed:
            return
        self._collapsed = True
        self.inner.hide()
        self.setFixedWidth(W_TUCK)
        self._pin()

    def expand(self) -> None:
        if not self._edge:
            return
        if self._collapsed:
            self.setFixedWidth(W_FULL)
            self.inner.show()
            self._collapsed = False
        self._pin()

    def _maybe_collapse(self) -> None:
        if not self._edge or self._collapsed:
            return
        if not self.isVisible():
            return
        if self.geometry().contains(QtGui.QCursor.pos()):
            self._leave.start()
            return
        self.collapse()

    def _snap(self) -> None:
        g = self._screen().availableGeometry()
        x, w = self.x(), self.width()
        side = ""
        if x <= g.left() + SNAP:
            side = "left"
        elif x + w >= g.right() - SNAP:
            side = "right"
        y = max(g.top(), min(self.y(), g.bottom() - H_FULL))
        if side:
            self._edge = side
            self.move(x, y)
            self._pin()
            self.collapse()
        else:
            self._edge = ""
            self._collapsed = False
            self.setFixedWidth(W_FULL)
            self.inner.show()
            self.move(x, y)
        self._save_pos()

    # --------------------------------------------------------- 拖动
    def _drag_handle(self, ev) -> bool:
        """按下就记住抓点，移动就跟着走，松手贴边。

        以前只有左边 12px 那个把手能动，缩起来或者手滑一点就拖不到，
        现在空白处（卡片、歌名、封面缩略图）都算抓手。
        """
        t = ev.type()
        if t == QtCore.QEvent.Type.MouseButtonPress:
            if ev.button() == Qt.LeftButton and not self._collapsed:
                self._dragging = True
                self._drag_off = (
                    ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
                )
                return True
            return False
        if t == QtCore.QEvent.Type.MouseMove and self._dragging:
            self.move(ev.globalPosition().toPoint() - self._drag_off)
            return True
        if t == QtCore.QEvent.Type.MouseButtonRelease and self._dragging:
            self._dragging = False
            self._snap()
            return True
        return False

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        if obj is getattr(self, "grip", None) or obj is getattr(self, "card", None):
            if self._drag_handle(ev):
                return True
        return super().eventFilter(obj, ev)

    def mousePressEvent(self, ev) -> None:  # noqa: N802
        if self._drag_handle(ev):
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev) -> None:  # noqa: N802
        if self._drag_handle(ev):
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if self._drag_handle(ev):
            return
        super().mouseReleaseEvent(ev)

    def enterEvent(self, event: QtGui.QEnterEvent) -> None:  # noqa: N802
        self._leave.stop()
        if self._edge and self._collapsed:
            self.expand()
        super().enterEvent(event)

    def leaveEvent(self, event: QtCore.QEvent) -> None:  # noqa: N802
        if self._edge:
            self._leave.start()
        super().leaveEvent(event)

    # --------------------------------------------------------- 控制
    def _prev(self) -> None:
        if self.player is not None and getattr(self.player, "queue", None):
            self.player.prev()

    def _toggle(self) -> None:
        p = self.player
        if p is None or not getattr(p, "queue", None):
            return
        p.toggle()

    def _next(self) -> None:
        if self.player is not None and getattr(self.player, "queue", None):
            self.player.next()

    # --------------------------------------------------------- 右键
    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:  # noqa: N802
        menu = QtWidgets.QMenu(self)
        menu.addAction("贴左侧", lambda: self._set_side("left"))
        menu.addAction("贴右侧", lambda: self._set_side("right"))
        menu.addAction("不贴边", lambda: self._set_side(""))
        menu.addSeparator()
        menu.addAction("隐藏（下一首再出）", self.dismiss)
        menu.exec(event.globalPos())

    def _set_side(self, side: str) -> None:
        self._edge = side if side in ("left", "right") else ""
        if not self._edge:
            self._collapsed = False
            self.setFixedWidth(W_FULL)
            self.inner.show()
        else:
            self.setFixedWidth(W_FULL)
            self.inner.show()
            self._collapsed = False
            self._pin()
            self.collapse()
        self._save_pos()

    def closeEvent(self, event) -> None:  # noqa: ANN001
        # 关掉的是这条悬浮条，不是程序
        self.hide()
        event.ignore()
