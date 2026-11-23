# -*- coding: utf-8 -*-
"""显示器滤镜：直接改 GDI 的 Gamma 曲线，做出"滤镜盒"那种观感。

说清楚它是什么、不是什么：
  · 只调显示器输出曲线（亮度 / 对比度 / 伽马 / 色温 / S 曲线 / 三通道增益）
  · 不注入游戏、不叠半透明覆盖层、不抓画面、不改游戏文件
  · 应用前先把原始曲线存下来，点恢复 / 关窗帘 / 退出程序都会写回去
  · 有些屏或显卡驱动不让改（SetDeviceGammaRamp 会被拒），那就直说"这块屏改不了"

参数全是 0~1 之间的浮点，界面那边负责换算成百分比 / K 值。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Dict, List, Optional, Tuple

_GDI = ctypes.windll.gdi32


class _RAMP(ctypes.Structure):
    _fields_ = [
        ("Red", wintypes.WORD * 256),
        ("Green", wintypes.WORD * 256),
        ("Blue", wintypes.WORD * 256),
    ]


# 参数默认：什么都不改
DEFAULT: Dict[str, float] = {
    "bright": 1.00,      # 亮度（乘性）
    "contrast": 1.00,    # 对比度
    "gamma": 1.00,       # 伽马
    "scurve": 0.00,      # S 曲线强度 0~0.35
    "temp": 6500.0,      # 色温 K（6500 = 中性，低=暖，高=冷）
    "r": 1.00,           # 三通道增益
    "g": 1.00,
    "b": 1.00,
}

PRESETS: Dict[str, Dict[str, float]] = {
    "去曝光": {"bright": 1.16, "contrast": 1.02, "gamma": 1.12, "temp": 6500.0},
    "鲜艳": {"bright": 1.04, "contrast": 1.18, "gamma": 1.06, "scurve": 0.10, "temp": 6600.0},
    "电影": {"bright": 0.98, "contrast": 1.10, "gamma": 1.14, "scurve": 0.06, "temp": 6250.0},
    "高亮": {"bright": 1.26, "contrast": 1.06, "gamma": 1.20, "temp": 6500.0},
    "柔和": {"bright": 0.96, "contrast": 0.92, "gamma": 1.04, "scurve": 0.05, "temp": 6800.0},
    "游戏": {"bright": 1.05, "contrast": 1.14, "gamma": 1.10, "scurve": 0.08, "temp": 6500.0, "g": 1.03},
    "阅读": {"bright": 1.10, "contrast": 0.94, "gamma": 1.06, "temp": 6600.0},
    "暗部增强": {"bright": 1.02, "contrast": 0.98, "gamma": 1.26, "scurve": 0.04, "temp": 6500.0},
    "偏暖": {"bright": 1.02, "contrast": 1.00, "gamma": 1.02, "temp": 5900.0},
    "偏冷": {"bright": 1.02, "contrast": 1.00, "gamma": 1.02, "temp": 7300.0},
    "冷色调": {"bright": 1.00, "contrast": 1.08, "gamma": 1.05, "temp": 7500.0, "b": 1.02},
    "原亮冷调": {"bright": 1.06, "contrast": 1.10, "gamma": 1.04, "temp": 7600.0},
}

# 三角洲那组：稍微抬中间调、压一点高光、绿色稍微提一点，实战看着不刺眼
for _i, _p in enumerate(
    (
        {"bright": 1.08, "contrast": 1.12, "gamma": 1.06, "scurve": 0.06, "temp": 6700.0},
        {"bright": 1.12, "contrast": 1.10, "gamma": 1.10, "scurve": 0.05, "temp": 6600.0},
        {"bright": 1.05, "contrast": 1.16, "gamma": 1.02, "scurve": 0.08, "temp": 6800.0},
        {"bright": 1.10, "contrast": 1.08, "gamma": 1.14, "scurve": 0.03, "temp": 6400.0},
        {"bright": 1.14, "contrast": 1.06, "gamma": 1.18, "scurve": 0.04, "temp": 6500.0},
    ),
    1,
):
    PRESETS[f"三角洲推荐{_i}"] = _p
PRESETS["三角洲超级推荐"] = {
    "bright": 1.09, "contrast": 1.14, "gamma": 1.09, "scurve": 0.07, "temp": 6550.0, "g": 1.02
}


def _temp_gains(temp: float) -> Tuple[float, float, float]:
    """色温 → RGB 增益。6500 中性；越低越暖（红重蓝少），越高越冷。"""
    t = max(4000.0, min(9000.0, float(temp)))
    k = (t - 6500.0) / 2500.0        # -1 .. +1
    r = 1.0 - 0.09 * k
    g = 1.0
    b = 1.0 + 0.11 * k
    return r, g, b


def _channel_lut(params: Dict[str, float], gain: float) -> List[int]:
    """一条通道的 256 级映射（0~255）。"""
    p = dict(DEFAULT)
    p.update({k: v for k, v in params.items() if k in DEFAULT})
    br = max(0.4, min(2.0, p["bright"]))
    ct = max(0.5, min(2.0, p["contrast"]))
    gm = max(0.5, min(2.4, p["gamma"]))
    sc = max(0.0, min(0.35, p["scurve"]))
    out: List[int] = []
    for i in range(256):
        x = i / 255.0
        x = (x - 0.5) * ct + 0.5
        x = x * br
        x = max(0.0, min(1.0, x))
        x = x ** (1.0 / gm)
        if sc:
            x = x + sc * 4.0 * x * (1.0 - x)
        x = max(0.0, min(1.0, x)) * gain
        out.append(1 if x <= 0 else (255 if x >= 1 else int(round(x * 255))))
    return out


def luts(params: Dict[str, float]) -> Tuple[List[int], List[int], List[int]]:
    tr, tg, tb = _temp_gains(params.get("temp", 6500.0))
    return (
        _channel_lut(params, tr * max(0.5, min(1.5, params.get("r", 1.0)))),
        _channel_lut(params, tg * max(0.5, min(1.5, params.get("g", 1.0)))),
        _channel_lut(params, tb * max(0.5, min(1.5, params.get("b", 1.0)))),
    )


def _hdc(dev: str):
    return _GDI.CreateDCW(dev, None, None, None)


def _read_ramp(dev: str) -> Optional[_RAMP]:
    hdc = _hdc(dev)
    if not hdc:
        return None
    ramp = _RAMP()
    ok = bool(_GDI.GetDeviceGammaRamp(hdc, ctypes.byref(ramp)))
    _GDI.DeleteDC(hdc)
    return ramp if ok else None


def devices() -> List[str]:
    """能读到 gamma 曲线的显示设备（\\\\.\\DISPLAY1 这种），读不到的跳过。"""
    found: List[str] = []
    for i in range(1, 5):
        dev = f"\\\\.\\DISPLAY{i}"
        if _read_ramp(dev) is not None:
            found.append(dev)
    return found


_ORIG: Dict[str, _RAMP] = {}
_APPLIED: Dict[str, Dict[str, float]] = {}


def apply(dev: str, params: Dict[str, float]) -> bool:
    """把参数写到这块屏。返回 False = 系统不让改。"""
    if dev not in _ORIG:
        orig = _read_ramp(dev)
        if orig is None:
            return False
        _ORIG[dev] = orig
    lr, lg, lb = luts(params)
    ramp = _RAMP()
    for i in range(256):
        ramp.Red[i] = lr[i] * 257
        ramp.Green[i] = lg[i] * 257
        ramp.Blue[i] = lb[i] * 257
    hdc = _hdc(dev)
    if not hdc:
        return False
    ok = bool(_GDI.SetDeviceGammaRamp(hdc, ctypes.byref(ramp)))
    _GDI.DeleteDC(hdc)
    if ok:
        _APPLIED[dev] = dict(params)
    return ok


def restore(dev: str) -> None:
    orig = _ORIG.get(dev)
    if orig is None:
        return
    hdc = _hdc(dev)
    if hdc:
        _GDI.SetDeviceGammaRamp(hdc, ctypes.byref(orig))
        _GDI.DeleteDC(hdc)
    _ORIG.pop(dev, None)
    _APPLIED.pop(dev, None)


def restore_all() -> None:
    for dev in list(_ORIG.keys()):
        restore(dev)


def is_active(dev: str) -> bool:
    return dev in _APPLIED


def active_params(dev: str) -> Dict[str, float]:
    return dict(_APPLIED.get(dev, {}))


def device_label(dev: str) -> str:
    """\\\\.\\DISPLAY1 → 主显示器 / 第 2 块屏。"""
    try:
        idx = int(dev.rsplit("DISPLAY", 1)[1])
    except (ValueError, IndexError):
        return dev
    return "主显示器" if idx == 1 else f"第 {idx} 块屏"
