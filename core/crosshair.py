# -*- coding: utf-8 -*-
"""准星叠加层：铺满整屏的透明窗口，只在正中画一个准星。

- 无边框、总在最前、不抢焦点、鼠标完全穿透
- 样式：十字 / 点 / T 形 / 圆环
- 臂长、粗细、间隙、颜色、透明度、中心点、黑色描边都可调
- 只覆盖主屏；游戏要跑「无边框窗口」才看得见（全屏独占会被游戏盖掉）
"""

from __future__ import annotations

import ctypes

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_NOACTIVATE = 0x08000000

STYLE_KEYS = ("cross", "dot", "t", "circle")
STYLE_NAMES = {"cross": "十字", "dot": "点", "t": "T 形", "circle": "圆环"}
DEFAULT_COLOR = "#20ffe0"


class CrosshairWindow(QtWidgets.QWidget):
    """整屏透明准星层。改完参数调 refresh() 就行，不用重建窗口。"""

    def __init__(self, cfg) -> None:
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.cfg = cfg
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        # Qt 自己的穿透：够用就够用，下面再补一层 Win32 的
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setWindowTitle("准星")
        self._apply_geometry()

    # ------------------------------------------------------------ 参数
    def _params(self):
        cfg = self.cfg
        style = str(getattr(cfg, "cross_style", "cross") or "cross")
        if style not in STYLE_KEYS:
            style = "cross"
        arm = max(2, min(90, int(getattr(cfg, "cross_size", 8) or 8)))
        th = max(1, min(10, int(getattr(cfg, "cross_thickness", 2) or 2)))
        gap = max(0, min(60, int(getattr(cfg, "cross_gap", 4) or 0)))
        color = str(getattr(cfg, "cross_color", DEFAULT_COLOR) or DEFAULT_COLOR)
        alpha = max(15, min(100, int(getattr(cfg, "cross_alpha", 92) or 92)))
        dot = bool(getattr(cfg, "cross_dot", True))
        outline = bool(getattr(cfg, "cross_outline", True))
        return style, arm, th, gap, color, alpha, dot, outline

    def refresh(self) -> None:
        self._apply_geometry()
        self.update()

    def _apply_geometry(self) -> None:
        scr = QtGui.QGuiApplication.primaryScreen()
        if scr is None:
            return
        self.setGeometry(scr.geometry())

    # ------------------------------------------------------------ 绘制
    def paintEvent(self, event) -> None:  # noqa: ANN001
        style, arm, th, gap, color, alpha, dot, outline = self._params()
        p = QtGui.QPainter(self)
        # 准星要硬边，开抗锯齿反而糊
        p.setRenderHint(QtGui.QPainter.Antialiasing, False)

        cx = self.width() // 2
        cy = self.height() // 2
        col = QtGui.QColor(color)
        if not col.isValid():
            col = QtGui.QColor(DEFAULT_COLOR)
        a = alpha / 100.0

        segs = []
        if style == "cross":
            segs = [
                (cx, cy - gap - arm, cx, cy - gap),
                (cx, cy + gap, cx, cy + gap + arm),
                (cx - gap - arm, cy, cx - gap, cy),
                (cx + gap, cy, cx + gap + arm, cy),
            ]
        elif style == "t":
            segs = [
                (cx, cy - gap - arm, cx, cy - gap),
                (cx - gap - arm, cy, cx - gap, cy),
                (cx + gap, cy, cx + gap + arm, cy),
            ]

        def stroke(qcolor, width) -> None:
            pen = QtGui.QPen(qcolor)
            pen.setWidth(width)
            pen.setCapStyle(Qt.FlatCap)
            p.setPen(pen)
            for x1, y1, x2, y2 in segs:
                p.drawLine(QtCore.QPoint(int(x1), int(y1)), QtCore.QPoint(int(x2), int(y2)))

        # 先来一层黑描边：亮背景（雪地、白墙）上准星才不会消失
        if outline and segs:
            oc = QtGui.QColor(0, 0, 0)
            oc.setAlphaF(0.50 * a)
            stroke(oc, th + 2)

        main = QtGui.QColor(col)
        main.setAlphaF(a)
        if segs:
            stroke(main, th)

        if style == "circle":
            pen = QtGui.QPen(main)
            pen.setWidth(th)
            p.setPen(pen)
            r = gap + arm
            p.drawEllipse(QtCore.QPoint(cx, cy), r, r)

        if dot or style == "dot":
            p.setPen(Qt.NoPen)
            p.setBrush(main)
            # 纯点样式下这个点就是全部，得给足大小；其余样式只做中心小点
            r2 = max(2, min(8, th * 2)) if style == "dot" else max(1, (th + 1) // 2)
            p.drawEllipse(QtCore.QPoint(cx, cy), r2, r2)

        p.end()

    # ------------------------------------------------------------ 显隐 / 穿透
    def show_cross(self) -> None:
        self._apply_geometry()
        self.show()
        self._apply_click_through()

    def hide_cross(self) -> None:
        self.hide()

    def _apply_click_through(self) -> None:
        """鼠标一律穿透：准星永远不该抢游戏的点击。"""
        try:
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:  # noqa: BLE001
            pass

    def keyPressEvent(self, event) -> None:  # noqa: ANN001
        event.ignore()

    def closeEvent(self, event) -> None:  # noqa: ANN001
        self.hide()
        event.ignore()
