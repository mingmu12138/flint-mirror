# -*- coding: utf-8 -*-
"""硬件走势记录 + 报告导出。

sysmon 只管"现在多少"，这里管"这一段时间怎么走的"：
内存里留最近 30 分钟（默认 2.5 秒一个点，约 720 点），不写盘、不联网；
开了才记，关了立刻清空，不占内存。
"""

from __future__ import annotations

import time
from collections import deque
from typing import Deque, List, Optional, Tuple

KEEP_SECONDS = 1800
SAMPLE_STEP = 2.5

FIELDS = (
    ("cpu", "CPU 占用", "%"),
    ("mem", "内存占用", "%"),
    ("gpu", "显卡占用", "%"),
    ("temp", "显卡温度", "°C"),
)

_COLORS = {
    "cpu": "#6ad4ff",
    "mem": "#7de38a",
    "gpu": "#ffd36a",
    "temp": "#ff7a90",
}


class Recorder:
    """只留最近一段时间的采样；关掉就什么都不存。"""

    def __init__(self, keep_seconds: int = KEEP_SECONDS, step: float = SAMPLE_STEP) -> None:
        self.cap = max(60, int(keep_seconds / max(0.5, float(step))))
        self.samples: Deque[dict] = deque(maxlen=self.cap)
        self.on = False

    def feed(self, data: dict) -> None:
        if not self.on:
            return
        self.samples.append({
            "t": time.time(),
            "cpu": data.get("cpu"),
            "mem": data.get("mem"),
            "gpu": data.get("gpu"),
            "temp": data.get("temp"),
        })

    def clear(self) -> None:
        self.samples.clear()

    def span(self) -> float:
        if len(self.samples) < 2:
            return 0.0
        return float(self.samples[-1]["t"]) - float(self.samples[0]["t"])

    def count(self) -> int:
        return len(self.samples)


def _stat(values: List[Optional[float]]) -> Optional[Tuple[float, float, float]]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return (sum(vals) / len(vals), max(vals), min(vals))


def _at(samples: List[dict], key: str, value: float) -> str:
    """最高值出现在第几秒（相对第一条）。"""
    if not samples:
        return "?"
    t0 = float(samples[0]["t"])
    for s in samples:
        if s.get(key) is not None and float(s[key]) == value:
            return f"+{int(float(s['t']) - t0)}s"
    return "?"


def build_report(samples: List[dict], title: str = "性能报告") -> str:
    """人话版的 md：时间范围、每个指标的均值/峰值/谷值、峰值出现在哪。"""
    if not samples:
        return "# " + title + "\n\n（还没有记录到数据）\n"
    span = float(samples[-1]["t"]) - float(samples[0]["t"])
    lines = [
        "# " + title,
        "",
        "生成时间：" + time.strftime("%Y-%m-%d %H:%M:%S"),
        "记录区间：" + time.strftime("%H:%M:%S", time.localtime(float(samples[0]["t"])))
        + " → " + time.strftime("%H:%M:%S", time.localtime(float(samples[-1]["t"])))
        + "（共 %d 分 %d 秒）" % (int(span // 60), int(span % 60)),
        "采样点：%d 个（约 %.1f 秒一个）" % (len(samples), SAMPLE_STEP),
        "",
        "| 指标 | 平均 | 最高 | 最低 | 最高出现在 |",
        "| --- | --- | --- | --- | --- |",
    ]
    missing = []
    for key, label, unit in FIELDS:
        st = _stat([s.get(key) for s in samples])
        if st is None:
            lines.append(f"| {label} | 未取到 | 未取到 | 未取到 | — |")
            missing.append(label)
            continue
        avg, hi, lo = st
        lines.append(
            f"| {label} | {avg:.0f}{unit} | {hi:.0f}{unit} | {lo:.0f}{unit} | {_at(samples, key, hi)} |"
        )
    if missing:
        lines += [
            "",
            "> " + "、".join(missing) + " 这一路没读到数据，报告里写「未取到」而不是 0："
            "多半是没装 N 卡驱动 / `nvidia-smi` 不在，或者机器是 A 卡 / 核显。",
        ]
    lines += ["", "曲线图在同一个目录下，文件名以 `性能走势_` 开头。", ""]
    return "\n".join(lines)


def render_png(samples: List[dict], path, width: int = 960, height: int = 460) -> bool:
    """画四条走势曲线存 PNG（Qt 自己画，不依赖 matplotlib）。"""
    from PySide6 import QtCore, QtGui

    if not samples:
        return False
    img = QtGui.QImage(int(width), int(height), QtGui.QImage.Format_RGB32)
    img.fill(QtGui.QColor("#101318"))
    p = QtGui.QPainter(img)
    try:
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        font = QtGui.QFont("Microsoft YaHei", 10)
        p.setFont(font)

        left, right, top, bottom = 56, 16, 54, 34
        plot = QtCore.QRectF(left, top, width - left - right, height - top - bottom)

        p.setPen(QtGui.QPen(QtGui.QColor("#2a3038"), 1))
        for i in range(5):
            y = plot.top() + plot.height() * i / 4.0
            p.drawLine(QtCore.QPointF(plot.left(), y), QtCore.QPointF(plot.right(), y))
            p.setPen(QtGui.QColor("#6e7681"))
            p.drawText(QtCore.QRectF(4, y - 10, 44, 20), QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter,
                       str(100 - i * 25) + "%")
            p.setPen(QtGui.QPen(QtGui.QColor("#2a3038"), 1))

        t0 = float(samples[0]["t"])
        t1 = float(samples[-1]["t"])
        dur = max(1.0, t1 - t0)

        def xy(i: int, v: float) -> QtCore.QPointF:
            x = plot.left() + plot.width() * ((float(samples[i]["t"]) - t0) / dur)
            y = plot.bottom() - plot.height() * max(0.0, min(100.0, v)) / 100.0
            return QtCore.QPointF(x, y)

        for key, label, _unit in FIELDS:
            pen = QtGui.QPen(QtGui.QColor(_COLORS[key]), 2)
            p.setPen(pen)
            last = None
            for i, s in enumerate(samples):
                v = s.get(key)
                if v is None:
                    last = None
                    continue
                pt = xy(i, float(v))
                if last is not None:
                    p.drawLine(last, pt)
                last = pt

        p.setPen(QtGui.QColor("#e6edf3"))
        p.drawText(QtCore.QRectF(left, 10, width - left - right, 22), QtCore.Qt.AlignLeft,
                   "性能走势 · " + time.strftime("%Y-%m-%d %H:%M"))
        lx = left
        for key, label, _unit in FIELDS:
            p.setBrush(QtGui.QColor(_COLORS[key]))
            p.setPen(QtCore.Qt.NoPen)
            p.drawRect(QtCore.QRectF(lx, 34, 10, 10))
            p.setPen(QtGui.QColor("#9aa4b2"))
            p.drawText(QtCore.QRectF(lx + 14, 28, 110, 22), QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter, label)
            lx += 128

        p.setPen(QtGui.QColor("#6e7681"))
        p.drawText(QtCore.QRectF(left, height - 28, 240, 20), QtCore.Qt.AlignLeft,
                   time.strftime("%H:%M:%S", time.localtime(t0)))
        p.drawText(QtCore.QRectF(width - right - 240, height - 28, 240, 20), QtCore.Qt.AlignRight,
                   time.strftime("%H:%M:%S", time.localtime(t1)))
    finally:
        p.end()
    return img.save(str(path), "PNG")


def export(samples: List[dict], tag: str = "") -> Tuple[bool, str, list]:
    """落成 md + png，返回 (成功, 提示, [文件路径])。"""
    from core import capture

    out = []
    if not samples:
        return False, "还没有记录到数据：先在设置里把「记录性能走势」打开，跑一会儿再导出", out
    base = capture.media_root() / "报告"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return False, "建不了报告目录：" + str(exc), out
    stamp = time.strftime("%Y%m%d-%H%M%S")
    md = base / ("性能报告_" + stamp + (("_" + tag) if tag else "") + ".md")
    png = base / ("性能走势_" + stamp + (("_" + tag) if tag else "") + ".png")
    try:
        md.write_text(build_report(samples, "性能报告 " + time.strftime("%Y-%m-%d %H:%M")), encoding="utf-8")
        out.append(md)
    except OSError as exc:
        return False, "写报告失败：" + str(exc), out
    try:
        if render_png(samples, png):
            out.append(png)
    except Exception:  # noqa: BLE001
        pass
    return True, "报告已生成（%d 个采样点）" % len(samples), out
