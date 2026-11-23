# -*- coding: utf-8 -*-
"""「显示器滤镜」窗口：预设卡片 + 左原图右滤镜的对比预览 + 参数细调。

样子参考滤镜盒那类工具，但只做能真生效的部分：显示器 Gamma 曲线。
窗口关掉就把曲线还原（除非用户自己把"关窗恢复"的勾去掉）。
"""

from __future__ import annotations

from typing import Dict, Optional

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from core import screenfilter as sf

try:
    import numpy as _np
except Exception:  # noqa: BLE001
    _np = None

BG = "#0b1117"
CARD = "rgba(255,255,255,.05)"
EDGE = "rgba(255,255,255,.10)"
MAIN = "#20ffe0"


def _fmt_pct(v: float) -> str:
    return f"{int(round(v * 100))}%"


class FilterWindow(QtWidgets.QWidget):
    """独立窗口，主窗口点「滤镜」模组时弹出来。"""

    def __init__(self, cfg=None) -> None:
        super().__init__(None)
        self.setWindowTitle("显示器滤镜 · 燧镜")
        self.setMinimumSize(880, 660)
        self.resize(900, 680)
        self.setStyleSheet(
            f"QWidget{{background:{BG};color:#dbe7f2;}}"
            "QLabel{background:transparent;}"
        )
        self.cfg = cfg
        self._cfgs: Dict[str, float] = dict(sf.DEFAULT)
        self._preset = ""
        self._dev = ""
        self._base: Optional[QtGui.QImage] = None
        self._devices = []
        self._busy = False
        self._suppress = False

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 12)
        root.setSpacing(10)

        root.addLayout(self._build_top())
        root.addLayout(self._build_body(), 1)
        hint = QtWidgets.QLabel(
            "滤镜只改显示器的输出曲线（伽马 / 亮度 / 对比度 / 色温），不注入游戏、不叠画面层；"
            "关窗或退出程序会自动还原。"
        )
        hint.setStyleSheet("color:#7d8fa3;font-size:11.5px;")
        root.addWidget(hint)

        self._deb = QtCore.QTimer(self)
        self._deb.setSingleShot(True)
        self._deb.setInterval(260)
        self._deb.timeout.connect(self._apply_if_active)
        self._preview_deb = QtCore.QTimer(self)
        self._preview_deb.setSingleShot(True)
        self._preview_deb.setInterval(160)
        self._preview_deb.timeout.connect(self._render_preview)

        self._reload_devices()

    # ------------------------------------------------------------ 顶部
    def _build_top(self) -> QtWidgets.QHBoxLayout:
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(8)

        cap = QtWidgets.QLabel("显示器")
        cap.setStyleSheet("color:#93a6ba;font-size:12px;")
        top.addWidget(cap)

        self.dev_box = QtWidgets.QComboBox()
        self.dev_box.setFixedWidth(170)
        self.dev_box.setStyleSheet(
            "QComboBox{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);"
            "border-radius:9px;padding:4px 10px;font-size:12px;color:#dff0f7;}"
            "QComboBox QAbstractItemView{background:#0e1720;color:#dff0f7;selection-background-color:"
            "rgba(32,255,224,.28);border:1px solid rgba(255,255,255,.12);}"
        )
        self.dev_box.currentIndexChanged.connect(self._on_dev)
        top.addWidget(self.dev_box)

        self.state_lbl = QtWidgets.QLabel("未启用 · 只预览")
        self.state_lbl.setStyleSheet(
            "font-size:12px;color:#ffd166;background:rgba(255,209,102,.10);"
            "border:1px solid rgba(255,209,102,.34);border-radius:9px;padding:3px 10px;"
        )
        top.addWidget(self.state_lbl)
        top.addStretch(1)

        self.chk_restore = QtWidgets.QCheckBox("关窗自动还原")
        self.chk_restore.setChecked(True)
        self.chk_restore.setStyleSheet("font-size:12px;color:#9fb2c6;")
        top.addWidget(self.chk_restore)

        self.btn_apply = QtWidgets.QPushButton("应用")
        self.btn_apply.setCursor(Qt.PointingHandCursor)
        self.btn_apply.setFixedHeight(30)
        self.btn_apply.setStyleSheet(
            "QPushButton{padding:0 16px;border:none;border-radius:9px;font-size:12.5px;"
            "font-weight:600;background:rgba(32,255,224,.30);color:#04231d;}"
            "QPushButton:hover{background:rgba(60,255,230,.46);}"
        )
        self.btn_apply.clicked.connect(self._apply_now)
        top.addWidget(self.btn_apply)

        self.btn_reset = QtWidgets.QPushButton("还原")
        self.btn_reset.setCursor(Qt.PointingHandCursor)
        self.btn_reset.setFixedHeight(30)
        self.btn_reset.setStyleSheet(
            "QPushButton{padding:0 14px;border:1px solid rgba(255,255,255,.16);"
            "border-radius:9px;font-size:12.5px;background:transparent;color:#d5e3ee;}"
            "QPushButton:hover{background:rgba(255,255,255,.10);}"
        )
        self.btn_reset.clicked.connect(self._restore_now)
        top.addWidget(self.btn_reset)
        return top

    # ------------------------------------------------------------ 主体
    def _build_body(self) -> QtWidgets.QHBoxLayout:
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(14)

        # 左：预设
        left = QtWidgets.QVBoxLayout()
        left.setSpacing(6)
        t = QtWidgets.QLabel("预设模式")
        t.setStyleSheet("font-size:13px;font-weight:700;color:#eaf6ff;")
        left.addWidget(t)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        holder = QtWidgets.QWidget()
        holder.setStyleSheet("background:transparent;")
        self._grid = QtWidgets.QGridLayout(holder)
        self._grid.setContentsMargins(0, 0, 6, 0)
        self._grid.setSpacing(8)
        scroll.setWidget(holder)
        left.addWidget(scroll, 1)
        body.addLayout(left, 0)

        self._preset_btns: Dict[str, QtWidgets.QPushButton] = {}
        for i, name in enumerate(sf.PRESETS.keys()):
            b = QtWidgets.QPushButton(name)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(52)
            b.setStyleSheet(
                "QPushButton{border:1px solid rgba(255,255,255,.10);border-radius:11px;"
                "background:rgba(255,255,255,.05);color:#d7e6f1;font-size:12px;}"
                "QPushButton:hover{background:rgba(255,255,255,.10);}"
                "QPushButton:checked{background:rgba(32,255,224,.22);"
                "border:1px solid rgba(120,255,228,.62);color:#eafffb;font-weight:700;}"
            )
            b.clicked.connect(lambda _=False, n=name: self._pick_preset(n))
            self._preset_btns[name] = b
            self._grid.addWidget(b, i // 3, i % 3)
        self._grid.setRowStretch(self._grid.rowCount(), 1)
        scroll.setFixedWidth(360)

        # 右：预览 + 参数
        right = QtWidgets.QVBoxLayout()
        right.setSpacing(8)

        self.preview = QtWidgets.QLabel()
        self.preview.setFixedHeight(232)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setStyleSheet(
            "border:1px solid rgba(255,255,255,.12);border-radius:11px;"
            "background:rgba(255,255,255,.03);color:#7b8ea3;font-size:12px;"
        )
        self.preview.setText("点「抓一张」把当前画面拿来做对比")
        right.addWidget(self.preview)

        prow = QtWidgets.QHBoxLayout()
        prow.setSpacing(8)
        self.btn_shot = QtWidgets.QPushButton("抓一张当前画面")
        self.btn_shot.setCursor(Qt.PointingHandCursor)
        self.btn_shot.setFixedHeight(28)
        self.btn_shot.setStyleSheet(
            "QPushButton{border:1px solid rgba(255,255,255,.14);border-radius:8px;"
            "font-size:12px;padding:0 12px;background:transparent;color:#d5e3ee;}"
            "QPushButton:hover{background:rgba(255,255,255,.10);}"
        )
        self.btn_shot.clicked.connect(self._grab)
        prow.addWidget(self.btn_shot)
        self.tip_lbl = QtWidgets.QLabel("左边原图，右边是这套参数的效果")
        self.tip_lbl.setStyleSheet("color:#7d8fa3;font-size:11.5px;")
        prow.addWidget(self.tip_lbl)
        prow.addStretch(1)
        right.addLayout(prow)

        panel = QtWidgets.QFrame()
        panel.setStyleSheet(
            f"QFrame{{background:{CARD};border:1px solid {EDGE};border-radius:12px;}}"
        )
        pv = QtWidgets.QVBoxLayout(panel)
        pv.setContentsMargins(12, 10, 12, 10)
        pv.setSpacing(6)
        right.addWidget(panel, 1)

        self._rows: Dict[str, tuple] = {}
        self._add_row(pv, "temp", "色温", 4500, 8500, 50, "K")
        self._add_row(pv, "bright", "亮度", 70, 160, 1, "%")
        self._add_row(pv, "contrast", "对比度", 70, 160, 1, "%")
        self._add_row(pv, "gamma", "伽马", 70, 180, 1, "")
        self._add_row(pv, "scurve", "S 曲线", 0, 30, 1, "%")
        self._add_row(pv, "r", "红增益", 80, 120, 1, "%")
        self._add_row(pv, "g", "绿增益", 80, 120, 1, "%")
        self._add_row(pv, "b", "蓝增益", 80, 120, 1, "%")

        body.addLayout(right, 1)
        return body

    def _add_row(self, lay: QtWidgets.QVBoxLayout, key: str, label: str,
                 lo: int, hi: int, step: int, unit: str) -> None:
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        cap = QtWidgets.QLabel(label)
        cap.setFixedWidth(58)
        cap.setStyleSheet("font-size:12px;color:#a9bacb;")
        row.addWidget(cap)

        s = QtWidgets.QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setCursor(Qt.PointingHandCursor)
        s.setStyleSheet(
            "QSlider::groove:horizontal{height:4px;background:rgba(255,255,255,.16);border-radius:2px;}"
            "QSlider::sub-page:horizontal{background:#20ffe0;border-radius:2px;}"
            "QSlider::handle:horizontal{width:12px;height:12px;margin:-4px 0;border-radius:6px;"
            "background:#eafffb;}"
        )
        row.addWidget(s, 1)

        val = QtWidgets.QLabel("")
        val.setFixedWidth(52)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        val.setStyleSheet("font-size:12px;color:#8fe8d8;")
        row.addWidget(val)
        lay.addLayout(row)

        s.valueChanged.connect(lambda v, k=key: self._on_slider(k, v))
        self._rows[key] = (s, val, unit)

    # ------------------------------------------------------------ 设备
    def _reload_devices(self) -> None:
        self._devices = sf.devices()
        self.dev_box.blockSignals(True)
        self.dev_box.clear()
        for d in self._devices:
            self.dev_box.addItem(sf.device_label(d), d)
        self.dev_box.blockSignals(False)
        if self._devices:
            self._dev = self._devices[0]
        else:
            self.dev_box.addItem("没找到能调的屏", "")
            self.btn_apply.setEnabled(False)
            self.state_lbl.setText("这块屏不支持")
        self._sync_sliders()

    def _on_dev(self, _i: int) -> None:
        d = self.dev_box.currentData()
        if d:
            self._dev = d
            sf.restore_all()
            self._refresh_state()

    # ------------------------------------------------------------ 参数
    def _on_slider(self, key: str, v: int) -> None:
        if self._suppress:
            return
        if key == "temp":
            self._cfgs["temp"] = float(v)
        elif key in ("bright", "contrast", "r", "g", "b"):
            self._cfgs[key] = v / 100.0
        elif key == "gamma":
            self._cfgs["gamma"] = v / 100.0
        else:
            self._cfgs["scurve"] = v / 100.0
        self._show_val(key, v)
        self._clear_preset_checks()
        self._preview_deb.start()
        if sf.is_active(self._dev):
            self._deb.start()

    def _show_val(self, key: str, v: int) -> None:
        row = self._rows.get(key)
        if not row:
            return
        _s, val, unit = row
        if key == "temp":
            val.setText(f"{v}K")
        elif key == "gamma":
            val.setText(f"{v / 100:.2f}")
        else:
            val.setText(f"{v}%")

    def _sync_sliders(self) -> None:
        self._suppress = True
        try:
            vals = {
                "temp": int(self._cfgs["temp"]),
                "bright": int(round(self._cfgs["bright"] * 100)),
                "contrast": int(round(self._cfgs["contrast"] * 100)),
                "gamma": int(round(self._cfgs["gamma"] * 100)),
                "scurve": int(round(self._cfgs["scurve"] * 100)),
                "r": int(round(self._cfgs["r"] * 100)),
                "g": int(round(self._cfgs["g"] * 100)),
                "b": int(round(self._cfgs["b"] * 100)),
            }
            for k, v in vals.items():
                if k in self._rows:
                    self._rows[k][0].setValue(v)
                    self._show_val(k, v)
        finally:
            self._suppress = False
        self._preview_deb.start()

    def _pick_preset(self, name: str) -> None:
        params = dict(sf.DEFAULT)
        params.update(sf.PRESETS.get(name, {}))
        self._cfgs = params
        self._preset = name
        self._clear_preset_checks()
        btn = self._preset_btns.get(name)
        if btn:
            btn.setChecked(True)
        self._sync_sliders()
        if sf.is_active(self._dev):
            self._apply_now()
        self.tip_lbl.setText(f"当前预设：{name}")

    def _clear_preset_checks(self) -> None:
        for b in self._preset_btns.values():
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)

    # ------------------------------------------------------------ 应用 / 还原
    def _apply_now(self) -> None:
        if not self._dev:
            return
        ok = sf.apply(self._dev, self._cfgs)
        if not ok:
            self.state_lbl.setText("显卡不让改这块屏")
            self.state_lbl.setStyleSheet(
                "font-size:12px;color:#ff8a8a;background:rgba(255,90,90,.10);"
                "border:1px solid rgba(255,120,120,.36);border-radius:9px;padding:3px 10px;"
            )
            return
        self._refresh_state()

    def _apply_if_active(self) -> None:
        if sf.is_active(self._dev):
            self._apply_now()

    def _restore_now(self) -> None:
        sf.restore(self._dev)
        self._cfgs = dict(sf.DEFAULT)
        self._preset = ""
        self._clear_preset_checks()
        self._sync_sliders()
        self._refresh_state()

    def _refresh_state(self) -> None:
        if sf.is_active(self._dev):
            self.state_lbl.setText("已启用")
            self.state_lbl.setStyleSheet(
                "font-size:12px;color:#7dffe8;background:rgba(32,255,224,.12);"
                "border:1px solid rgba(32,255,224,.40);border-radius:9px;padding:3px 10px;"
            )
        else:
            self.state_lbl.setText("未启用 · 只预览")
            self.state_lbl.setStyleSheet(
                "font-size:12px;color:#ffd166;background:rgba(255,209,102,.10);"
                "border:1px solid rgba(255,209,102,.34);border-radius:9px;padding:3px 10px;"
            )

    # ------------------------------------------------------------ 预览
    def _grab(self) -> None:
        scr = QtGui.QGuiApplication.primaryScreen()
        if scr is None:
            return
        shot = scr.grabWindow(0)
        if shot.isNull():
            self.preview.setText("抓不到画面（可能是独占全屏的游戏，先切回桌面）")
            return
        self._base = shot.toImage().convertToFormat(QtGui.QImage.Format_RGBA8888)
        self._render_preview()

    def _render_preview(self) -> None:
        if self._base is None:
            return
        W = max(320, self.preview.width())
        H = max(160, self.preview.height())
        scaled = self._base.scaled(W, H, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        # 居中裁一块，保证铺满
        off_x = max(0, (scaled.width() - W) // 2)
        off_y = max(0, (scaled.height() - H) // 2)
        crop = scaled.copy(off_x, off_y, min(W, scaled.width()), min(H, scaled.height()))
        crop = crop.scaled(W, H, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

        after = self._simulate(crop)
        half = W // 2
        canvas = QtGui.QImage(W, H, QtGui.QImage.Format_RGBA8888)
        painter = QtGui.QPainter(canvas)
        painter.drawImage(QtCore.QRect(0, 0, half, H), crop, QtCore.QRect(0, 0, half, H))
        painter.drawImage(QtCore.QRect(half, 0, W - half, H), after,
                          QtCore.QRect(half, 0, W - half, H))
        # 分割线 + 两个角标
        painter.setPen(QtGui.QPen(QtGui.QColor(32, 255, 224), 2))
        painter.drawLine(half, 0, half, H)
        # 角标垫个半透明底，压在亮画面上也看得清
        painter.fillRect(QtCore.QRect(8, H - 26, 46, 18), QtGui.QColor(6, 12, 18, 190))
        painter.fillRect(QtCore.QRect(W - 54, H - 26, 46, 18), QtGui.QColor(6, 12, 18, 190))
        painter.setPen(QtGui.QColor(220, 235, 245))
        painter.setFont(QtGui.QFont("Microsoft YaHei UI", 9))
        painter.drawText(QtCore.QRect(8, H - 26, 46, 18), Qt.AlignCenter, "原始")
        painter.drawText(QtCore.QRect(W - 54, H - 26, 46, 18), Qt.AlignCenter, "滤镜")
        painter.end()

        self.preview.setPixmap(QtGui.QPixmap.fromImage(canvas))

    def _simulate(self, img: QtGui.QImage) -> QtGui.QImage:
        if _np is None:
            return img
        lr, lg, lb = sf.luts(self._cfgs)
        buf = _np.frombuffer(img.constBits(), dtype=_np.uint8).reshape(
            img.height(), img.bytesPerLine() // 4, 4
        )[:, : img.width(), :].copy()
        for ch, lut in ((0, lr), (1, lg), (2, lb)):
            table = _np.array(lut, dtype=_np.uint8)
            buf[..., ch] = table[buf[..., ch]]
        out = _np.ascontiguousarray(buf)
        res = QtGui.QImage(out.data, out.shape[1], out.shape[0], out.strides[0],
                           QtGui.QImage.Format_RGBA8888)
        return res.copy()

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._base is not None:
            self._preview_deb.start()

    # ------------------------------------------------------------ 生命周期
    def show_window(self) -> None:
        self._reload_devices()
        self._refresh_state()
        if self._base is None:
            QtCore.QTimer.singleShot(200, self._grab)
        self.show()
        self.raise_()
        self.activateWindow()

    def shutdown(self, force: bool = False) -> None:
        """退出程序时兜底还原，别把别人的屏留在滤镜状态里。"""
        if force or self.chk_restore.isChecked():
            sf.restore_all()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:  # noqa: N802
        if self.chk_restore.isChecked():
            sf.restore_all()
            self._refresh_state()
        event.ignore()
        self.hide()
