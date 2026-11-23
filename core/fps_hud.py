# -*- coding: utf-8 -*-
"""帧率悬浮窗：屏幕角落一个小方块，显示当前游戏 FPS。

- 无边框、总在最前、不抢焦点
- 可拖动（拖完记住位置），也可固定在左侧 / 右侧
- 独立鼠标穿透开关：开了鼠标直接穿过去，不挡游戏点击
"""

from __future__ import annotations

import ctypes

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020


class FpsHud(QtWidgets.QWidget):
    # 用户点了右键里那条「以管理员重启」，交给主窗口去执行
    admin_requested = QtCore.Signal()

    def __init__(self, cfg) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.cfg = cfg
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowTitle("FPS")

        self._scale = int(getattr(cfg, "fps_scale", 20) or 20)
        self._alpha = int(getattr(cfg, "fps_alpha", 88) or 88)
        self._through = bool(getattr(cfg, "fps_click_through", True))
        self._dragging = False
        self._drag_off = QtCore.QPoint()
        self._value = 0.0

        shell = QtWidgets.QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)

        self.card = QtWidgets.QFrame()
        self.card.setObjectName("FpsCard")
        shell.addWidget(self.card)

        box = QtWidgets.QHBoxLayout(self.card)
        box.setContentsMargins(12, 6, 12, 6)
        box.setSpacing(6)

        self.value_lbl = QtWidgets.QLabel("--")
        self.value_lbl.setObjectName("FpsValue")
        box.addWidget(self.value_lbl)

        self.unit_lbl = QtWidgets.QLabel("FPS")
        self.unit_lbl.setObjectName("FpsUnit")
        box.addWidget(self.unit_lbl)

        self._apply_style()
        self.adjustSize()
        QtCore.QTimer.singleShot(0, self._apply_layout)

    # ---------------------------------------------------------- 外观
    def _apply_style(self) -> None:
        self.card.setStyleSheet(
            "QFrame#FpsCard{"
            f"background: rgba(10, 14, 20, {self._alpha / 100:.2f});"
            "border: 1px solid rgba(32, 255, 224, 0.45);"
            "border-radius: 10px;}"
        )
        self.value_lbl.setStyleSheet(
            f"color:#20ffe0; font-size:{self._scale}px; font-weight:700;"
            "font-family:'Consolas','Microsoft YaHei UI';"
        )
        self.unit_lbl.setStyleSheet(
            f"color:#9aa4b4; font-size:{max(10, self._scale - 8)}px; font-weight:600;"
            "font-family:'Microsoft YaHei UI';"
        )

    def set_scale(self, scale: int) -> None:
        self._scale = max(12, min(36, int(scale)))
        self.cfg.fps_scale = self._scale
        self.cfg.save()
        self._apply_style()
        self.adjustSize()

    def set_value(self, fps: float) -> None:
        self._value = fps
        if fps <= 0:
            self.value_lbl.setText("--")
            return
        self.value_lbl.setText(str(int(round(fps))))
        # 低帧变个色，一眼看出卡
        color = "#ff6b6b" if fps < 25 else ("#ffd166" if fps < 45 else "#20ffe0")
        self.value_lbl.setStyleSheet(
            f"color:{color}; font-size:{self._scale}px; font-weight:700;"
            "font-family:'Consolas','Microsoft YaHei UI';"
        )

    # ---------------------------------------------------------- 位置
    def _apply_layout(self) -> None:
        self.adjustSize()
        saved = getattr(self.cfg, "fps_pos", []) or []
        if isinstance(saved, (list, tuple)) and len(saved) == 2:
            self.move(int(saved[0]), int(saved[1]))
        else:
            self._apply_side()

    def _apply_side(self) -> None:
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        margin = 18
        side = "left" if getattr(self.cfg, "fps_side", "right") == "left" else "right"
        x = area.left() + margin if side == "left" else area.right() - self.width() - margin
        y = area.top() + margin
        self.move(x, y)

    def set_side(self, side: str) -> None:
        self.cfg.fps_side = "left" if side == "left" else "right"
        self.cfg.fps_pos = []
        self.cfg.save()
        self._apply_side()

    # ---------------------------------------------------------- 穿透 / 拖动
    def set_click_through(self, on: bool) -> None:
        self._through = bool(on)
        self.cfg.fps_click_through = self._through
        self.cfg.save()
        self._apply_click_through()

    def _apply_click_through(self) -> None:
        try:
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if self._through:
                style |= (WS_EX_TRANSPARENT | WS_EX_LAYERED)
            else:
                style &= ~WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def show_hud(self) -> None:
        self.show()
        self._apply_layout()
        self._apply_click_through()

    def hide_hud(self) -> None:
        self.hide()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._drag_off = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._dragging:
            self.move(event.globalPosition().toPoint() - self._drag_off)
            event.accept()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if self._dragging:
            self._dragging = False
            self.cfg.fps_pos = [self.x(), self.y()]
            self.cfg.save()
            event.accept()

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent) -> None:
        menu = QtWidgets.QMenu(self)
        menu.addAction("贴左侧", lambda: self.set_side("left"))
        menu.addAction("贴右侧", lambda: self.set_side("right"))
        menu.addSeparator()
        act = menu.addAction("鼠标穿透")
        act.setCheckable(True)
        act.setChecked(self._through)
        act.triggered.connect(lambda checked: self.set_click_through(checked))
        menu.addSeparator()
        a_admin = menu.addAction("读不到帧？以管理员重启（游戏是管理员跑的就得这样）")
        a_admin.triggered.connect(self.admin_requested.emit)
        menu.addSeparator()
        menu.addAction("隐藏帧率窗", self.hide_hud)
        menu.exec(event.globalPos())

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self.hide()
        event.ignore()
