# -*- coding: utf-8 -*-
"""每日密码悬浮窗（HUD）

只干一件事：把 shushu.fan 的当天密码贴在屏幕侧边，游戏里也能瞄一眼。
- 无边框、总在最前、不抢焦点
- 默认鼠标穿透：鼠标直接穿过去，不挡点击
- 位置固定在左侧或右侧（设置里切），垂直居中
- 数据直接读 delta_cache.json（三角洲页刷新后会自动跟上）
"""

import ctypes
import json
import time

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from .store import app_dir

CACHE_NAME = "delta_cache.json"
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020


class DailyHud(QtWidgets.QWidget):
    """每日密码小窗。"""

    def __init__(self, cfg, on_open_page=None):
        super().__init__(None, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.cfg = cfg
        self.on_open_page = on_open_page
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowTitle("每日密码")

        self._cache_mtime = 0.0
        self._scale = int(getattr(cfg, "hud_scale", 16) or 16)
        self._alpha = int(getattr(cfg, "hud_alpha", 92) or 92)
        self.side = "left" if getattr(cfg, "hud_side", "right") == "left" else "right"
        self._through = bool(getattr(cfg, "hud_click_through", True))

        shell = QtWidgets.QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)

        self.card = QtWidgets.QFrame()
        self.card.setObjectName("HudCard")
        shell.addWidget(self.card)

        box = QtWidgets.QVBoxLayout(self.card)
        box.setContentsMargins(14, 11, 14, 12)
        box.setSpacing(7)

        self.title = QtWidgets.QLabel("每日密码")
        box.addWidget(self.title)

        line = QtWidgets.QFrame()
        line.setFixedHeight(3)
        line.setObjectName("HudLine")
        box.addWidget(line)

        self.grid = QtWidgets.QGridLayout()
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(3)
        self.grid.setColumnStretch(1, 1)
        box.addLayout(self.grid)

        self.rows = []
        self._apply_style()
        self.reload(force=True)

        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.reload)
        self.timer.start(10000)

    # ---------------------------------------------------------- 外观
    def _apply_style(self):
        self.card.setStyleSheet(
            "QFrame#HudCard{"
            f"background: rgba(10, 14, 20, {self._alpha / 100:.2f});"
            "border: 1px solid rgba(32, 255, 224, 0.45);"
            "border-radius: 12px;}"
            "QFrame#HudLine{background: rgba(32, 255, 224, 0.22); border: none;}"
        )
        self.title.setStyleSheet(
            f"color:#9aa4b4; font-size:{max(10, self._scale - 5)}px;"
            "font-family:'Microsoft YaHei UI'; font-weight:600;"
        )

    # ---------------------------------------------------------- 位置
    def _apply_side(self) -> None:
        """贴左边或右边，垂直居中（略偏上）。"""
        self.adjustSize()
        screen = QtGui.QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        margin = 24
        if self.side == "left":
            x = area.left() + margin
        else:
            x = area.right() - self.width() - margin
        y = area.top() + int((area.height() - self.height()) / 2) - 36
        y = max(area.top() + 48, min(y, area.bottom() - self.height() - 24))
        self.move(x, y)

    def set_side(self, side: str) -> None:
        self.side = "left" if side == "left" else "right"
        self.cfg.hud_side = self.side
        self.cfg.hud_pos = []
        self.cfg.save()
        self._apply_side()

    # ---------------------------------------------------------- 数据
    def _read_cache(self, force: bool = False) -> dict:
        path = app_dir() / CACHE_NAME
        if not path.exists():
            return {}
        try:
            mtime = path.stat().st_mtime
            if not force and mtime == self._cache_mtime:
                return None
            self._cache_mtime = mtime
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def reload(self, force: bool = False) -> None:
        """读缓存，把当天密码铺到窗口上。"""
        data = self._read_cache(force)
        if data is None:
            return
        block = (data or {}).get("passwords") or {}
        maps = block.get("maps") or {}
        card_date = str(block.get("codes_date") or "")
        clock = str(block.get("checked_at") or "")
        today = time.strftime("%Y-%m-%d")

        if not maps:
            self.title.setText("每日密码　还没有数据")
            self.title.setStyleSheet(
                f"color:#ff8a8a; font-size:{max(10, self._scale - 5)}px;"
                "font-family:'Microsoft YaHei UI'; font-weight:600;"
            )
            self._fill([("打开三角洲页 点刷新", "")])
            return

        if card_date == today:
            head = f"每日密码　{card_date[5:]} 今日"
            color = "#7ee787"
            if clock:
                head += f" · {clock[11:]}"
        elif card_date:
            head = f"每日密码　{card_date[5:]} 昨日 ⚠ 可能已失效"
            color = "#ffb86b"
        else:
            head = "每日密码　今日"
            color = "#9aa4b4"

        self.title.setText(head)
        self.title.setStyleSheet(
            f"color:{color}; font-size:{max(10, self._scale - 5)}px;"
            "font-family:'Microsoft YaHei UI'; font-weight:600;"
        )
        self._fill(list(maps.items()))

    def _fill(self, rows):
        for name_lb, code_lb in self.rows:
            name_lb.deleteLater()
            code_lb.deleteLater()
        self.rows = []
        for i, (name, code) in enumerate(rows):
            name_lb = QtWidgets.QLabel(str(name))
            name_lb.setStyleSheet(
                f"color:#dfe6f0; font-size:{self._scale}px;"
                "font-family:'Microsoft YaHei UI';"
            )
            code_lb = QtWidgets.QLabel(str(code))
            code_lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            code_lb.setStyleSheet(
                f"color:#20ffe0; font-size:{self._scale + 2}px; font-weight:700;"
                "font-family:'Consolas','Menlo',monospace;"
            )
            self.grid.addWidget(name_lb, i, 0)
            self.grid.addWidget(code_lb, i, 1)
            self.rows.append((name_lb, code_lb))
        self._apply_side()

    # ---------------------------------------------------------- 开关
    def show_hud(self) -> None:
        self.reload(force=True)
        self._apply_side()
        self.show()
        self.raise_()
        self._apply_click_through()

    def hide_hud(self) -> None:
        self.hide()

    def set_click_through(self, on: bool) -> None:
        self._through = bool(on)
        self.cfg.hud_click_through = self._through
        self.cfg.save()
        self._apply_click_through()

    def _apply_click_through(self) -> None:
        """穿透后鼠标直接穿过去，点不到这个窗（游戏里不会挡操作）。"""
        try:
            self.setAttribute(Qt.WA_TransparentForMouseEvents, self._through)
            hwnd = int(self.winId())
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            if self._through:
                style |= (WS_EX_TRANSPARENT | WS_EX_LAYERED)
            else:
                style &= ~WS_EX_TRANSPARENT
            ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception:
            pass

    def _on_scale(self, delta: int) -> None:
        self._scale = max(12, min(26, self._scale + delta))
        self.cfg.hud_scale = self._scale
        self.cfg.save()
        self._apply_style()
        self.reload(force=True)

    # ---------------------------------------------------------- 右键
    def contextMenuEvent(self, event):
        """只在关掉鼠标穿透时能用（穿透时点不到它）。"""
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(
            "QMenu{background:#151b24;border:1px solid #232a36;padding:4px;}"
            "QMenu::item{color:#cfd6e2;padding:5px 16px;}"
            "QMenu::item:selected{background:#1e2531;color:#20ffe0;}"
        )
        menu.addAction(f"字号 {self._scale} → 更大", lambda: self._on_scale(2))
        menu.addAction(f"字号 {self._scale} → 更小", lambda: self._on_scale(-2))
        menu.addAction("贴到左侧", lambda: self.set_side("left"))
        menu.addAction("贴到右侧", lambda: self.set_side("right"))
        if self.on_open_page:
            menu.addAction("打开三角洲情报页…", self.on_open_page)
        menu.addSeparator()
        menu.addAction("隐藏（可在设置里再打开）", self._hide_from_menu)
        menu.exec(event.globalPos())

    def _hide_from_menu(self) -> None:
        self.hide_hud()
        self.cfg.hud_show = False
        self.cfg.save()

    def closeEvent(self, event):
        # 用户按 Esc / 被外部关闭时，别把开关状态搞乱
        self.hide()
        event.ignore()
