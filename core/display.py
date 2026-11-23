"""显示器分辨率控制模块。

纯 ctypes 调用 Windows API，不依赖第三方库。
只负责"主显示器"的分辨率读取、枚举与切换。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import List, Optional, Tuple

user32 = ctypes.WinDLL("user32", use_last_error=True)

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
ENUM_CURRENT_SETTINGS = -1
CDS_UPDATEREGISTRY = 0x00000001
CDS_TEST = 0x00000002

DISP_CHANGE_SUCCESSFUL = 0
DISP_CHANGE_RESTART = 1
DISP_CHANGE_FAILED = -1
DISP_CHANGE_BADMODE = -2
DISP_CHANGE_NOTUPDATED = -3
DISP_CHANGE_BADFLAGS = -4
DISP_CHANGE_BADPARAM = -5
DISP_CHANGE_BADDUALVIEW = -6

DISP_CHANGE_MSG = {
    DISP_CHANGE_SUCCESSFUL: "成功",
    DISP_CHANGE_RESTART: "需要重启后生效",
    DISP_CHANGE_FAILED: "驱动不支持该模式",
    DISP_CHANGE_BADMODE: "不支持该显示模式（显卡/显示器未提供此分辨率）",
    DISP_CHANGE_NOTUPDATED: "无法写入注册表",
    DISP_CHANGE_BADFLAGS: "参数标志无效",
    DISP_CHANGE_BADPARAM: "参数无效",
    DISP_CHANGE_BADDUALVIEW: "多显示器模式下不支持",
}

DM_BITSPERPEL = 0x00040000
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
DM_DISPLAYFREQUENCY = 0x00400000


# ---------------------------------------------------------------------------
# 结构体
# ---------------------------------------------------------------------------
class POINTL(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _DevmodePrinter(ctypes.Structure):
    """DEVMODEW 里 union 的第一种解释（打印机相关，8 个 short = 16 字节）。"""

    _fields_ = [
        ("dmOrientation", ctypes.c_short),
        ("dmPaperSize", ctypes.c_short),
        ("dmPaperLength", ctypes.c_short),
        ("dmPaperWidth", ctypes.c_short),
        ("dmScale", ctypes.c_short),
        ("dmCopies", ctypes.c_short),
        ("dmDefaultSource", ctypes.c_short),
        ("dmPrintQuality", ctypes.c_short),
    ]


class _DevmodeDisplay(ctypes.Structure):
    """DEVMODEW 里 union 的第二种解释（显示器位置 / 方向，也是 16 字节）。"""

    _fields_ = [
        ("dmPosition", POINTL),
        ("dmDisplayOrientation", wintypes.DWORD),
        ("dmDisplayFixedOutput", wintypes.DWORD),
    ]


class _DevmodeUnion(ctypes.Union):
    _fields_ = [
        ("printer", _DevmodePrinter),
        ("display", _DevmodeDisplay),
    ]


class DEVMODEW(ctypes.Structure):
    """完整的 DEVMODEW 定义（union 用 ctypes.Union 正确重叠），sizeof = 220。"""

    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("_u1", _DevmodeUnion),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


# ---------------------------------------------------------------------------
# 数据模型
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Mode:
    width: int
    height: int
    bpp: int = 32
    hz: int = 0

    @property
    def ratio(self) -> float:
        return round(self.width / self.height, 3) if self.height else 0.0

    @property
    def label(self) -> str:
        if self.hz:
            return f"{self.width} × {self.height}  ({self.hz}Hz)"
        return f"{self.width} × {self.height}"


# ---------------------------------------------------------------------------
# API 封装
# ---------------------------------------------------------------------------
def _devmode() -> DEVMODEW:
    dm = DEVMODEW()
    dm.dmSize = ctypes.sizeof(DEVMODEW)
    return dm


# 当前"动作作用在哪块屏"：None = 主屏（老行为，所有调用都不用改就能用）
_ACTIVE_DEVICE: Optional[str] = None


def target_device() -> Optional[str]:
    """当前作用的显示器设备名；None 表示主屏。"""
    return _ACTIVE_DEVICE


def set_target(device: Optional[str]) -> None:
    """切换作用屏。传 None 回主屏。"""
    global _ACTIVE_DEVICE
    _ACTIVE_DEVICE = device or None


def list_displays() -> List[dict]:
    """列出接在桌面上的显示器：device / 型号 / 是否主屏 / 当前分辨率。"""
    out: List[dict] = []
    dev = DISPLAY_DEVICEW()
    dev.cb = ctypes.sizeof(DISPLAY_DEVICEW)
    index = 0
    while user32.EnumDisplayDevicesW(None, index, ctypes.byref(dev), 0):
        if dev.StateFlags & 0x1:  # DISPLAY_DEVICE_ATTACHED_TO_DESKTOP
            dm = _devmode()
            ok = user32.EnumDisplaySettingsW(
                dev.DeviceName, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)
            )
            w = int(dm.dmPelsWidth) if ok else 0
            h = int(dm.dmPelsHeight) if ok else 0
            model = (dev.DeviceString or "").strip()
            mon = DISPLAY_DEVICEW()
            mon.cb = ctypes.sizeof(DISPLAY_DEVICEW)
            if user32.EnumDisplayDevicesW(
                dev.DeviceName, 0, ctypes.byref(mon), 0
            ):
                name = (mon.DeviceString or "").strip()
                if name and "Generic" not in name:
                    model = name
            short = (dev.DeviceName or "").replace(chr(92) + chr(92) + "." + chr(92), "")
            out.append(
                {
                    "device": dev.DeviceName,
                    "short": short,
                    "model": model,
                    "primary": bool(dev.StateFlags & 0x4),
                    "w": w,
                    "h": h,
                    "label": f"{short} · {model} · {w}×{h}"
                    + ("（主屏）" if dev.StateFlags & 0x4 else ""),
                }
            )
        index += 1
        if index > 8:
            break
    return out


def get_current(device: Optional[str] = None) -> Tuple[int, int]:
    """返回当前分辨率 (宽, 高)。不传 device 就用作用屏（默认主屏）。"""
    device = device or _ACTIVE_DEVICE
    dm = _devmode()
    if not user32.EnumDisplaySettingsW(
        device, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)
    ):
        return (0, 0)
    return (int(dm.dmPelsWidth), int(dm.dmPelsHeight))


def get_native(device: Optional[str] = None) -> Tuple[int, int, int]:
    """读取系统记录的原生推荐模式 (宽, 高, 刷新率)。失败则退回当前值。"""
    dm = _devmode()
    device = device or _ACTIVE_DEVICE
    if user32.EnumDisplaySettingsW(device, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
        # 用注册表里保存的"最后设置"不一定等于原生，这里直接以当前为准
        return (int(dm.dmPelsWidth), int(dm.dmPelsHeight), int(dm.dmDisplayFrequency))
    return (*get_current(), 0)


def list_modes(device: Optional[str] = None) -> List[Mode]:
    """枚举主显示器所有支持的显示模式（去重宽高，保留最高刷新率）。"""
    found: dict[Tuple[int, int], Mode] = {}
    dm = _devmode()
    index = 0
    device = device or _ACTIVE_DEVICE
    while user32.EnumDisplaySettingsW(device, index, ctypes.byref(dm)):
        w, h = int(dm.dmPelsWidth), int(dm.dmPelsHeight)
        bpp, hz = int(dm.dmBitsPerPel), int(dm.dmDisplayFrequency)
        key = (w, h)
        old = found.get(key)
        # 优先保留 32 位色、较高刷新率
        if old is None or (bpp >= old.bpp and hz >= old.hz):
            found[key] = Mode(w, h, bpp, hz)
        index += 1
        if index > 2000:  # 防死循环
            break
    return sorted(found.values(), key=lambda m: (m.width, m.height))


def is_43(mode_or_w, h: Optional[int] = None) -> bool:
    """判断是否为 4:3 比例（容差 0.01）。"""
    if isinstance(mode_or_w, Mode):
        w, hh = mode_or_w.width, mode_or_w.height
    else:
        w, hh = int(mode_or_w), int(h or 0)
    if not hh:
        return False
    return abs((w / hh) - (4 / 3)) < 0.01


def mode_43(width: int = 0) -> List[Mode]:
    """列出支持的 4:3 模式；width > 0 时只保留宽度不超标定的（避免超出屏幕）。"""
    res = [m for m in list_modes() if is_43(m)]
    native_w, native_h = get_current()
    limit = width or native_w
    res = [m for m in res if m.width <= limit and m.height <= (limit * 3 // 4)]
    return sorted(res, key=lambda m: m.width, reverse=True)


RATIO_ORDER = ["4:3", "16:10", "5:4", "16:9", "其他"]

# 常见游戏分辨率里值得推荐的那几档（只在屏幕真实支持时才会显示）
RECOMMENDED = {
    (1440, 1080): "1K 4:3 首选",
    (1920, 1440): "2K 4:3 强力推荐",
    (2088, 1440): "2K 4:3 · 27 寸",
    (1280, 960): "4:3 老牌",
    (1152, 864): "4:3 轻量",
    (1728, 1080): "1K 16:10 · 多人用",
    (1680, 1050): "16:10",
    (1280, 800): "16:10 轻量",
    (1600, 900): "16:9 轻量",
    (1366, 768): "16:9 笔记本常见",
}


def ratio_group(width: int, height: int) -> str:
    """按宽高比归类：4:3 / 16:10 / 5:4 / 16:9 / 其他。"""
    if not height:
        return "其他"
    r = width / height
    if abs(r - 4 / 3) < 0.01:
        return "4:3"
    if abs(r - 16 / 10) < 0.01:
        return "16:10"
    if abs(r - 5 / 4) < 0.01:
        return "5:4"
    if abs(r - 16 / 9) < 0.01:
        return "16:9"
    return "其他"


def grouped_modes() -> List[Tuple[str, List[Mode]]]:
    """把枚举到的模式按比例分组，组内按像素数从大到小。"""
    buckets: dict[str, List[Mode]] = {}
    for m in list_modes():
        buckets.setdefault(ratio_group(m.width, m.height), []).append(m)
    out: List[Tuple[str, List[Mode]]] = []
    for g in RATIO_ORDER:
        items = buckets.get(g) or []
        if items:
            out.append((g, sorted(items, key=lambda m: -(m.width * m.height))))
    return out


def tag_for(width: int, height: int) -> str:
    """推荐标签；没有就返回空串。"""
    return RECOMMENDED.get((int(width), int(height)), "")


def _copy_devmode(src: DEVMODEW) -> DEVMODEW:
    dst = DEVMODEW()
    ctypes.memmove(ctypes.byref(dst), ctypes.byref(src), ctypes.sizeof(DEVMODEW))
    dst.dmSize = ctypes.sizeof(DEVMODEW)
    return dst


def _find_devmode(
    width: int, height: int, hz: int = 0, device: Optional[str] = None
) -> Optional[DEVMODEW]:
    """在系统枚举的模式里找到匹配的完整 DEVMODE 模板。

    直接拿枚举返回的结构去切换最稳：驱动对字段的要求（色深、刷新率）
    已经被系统填好，避免自己拼 dmFields 被判定为 BADMODE。
    """
    dm = _devmode()
    device = device or _ACTIVE_DEVICE
    cur_hz = get_native(device)[2]
    best: Optional[DEVMODEW] = None
    best_hz = -1
    index = 0
    while user32.EnumDisplaySettingsW(device, index, ctypes.byref(dm)):
        if int(dm.dmPelsWidth) == int(width) and int(dm.dmPelsHeight) == int(height):
            h = int(dm.dmDisplayFrequency)
            if hz:
                if h == int(hz):
                    return _copy_devmode(dm)
            else:
                if h == cur_hz:
                    return _copy_devmode(dm)
                if h > best_hz:
                    best = _copy_devmode(dm)
                    best_hz = h
        index += 1
        if index > 2000:
            break
    return best


def set_resolution(width: int, height: int, hz: int = 0, bpp: int = 32,
                   test_only: bool = False,
                   device: Optional[str] = None) -> Tuple[bool, int, str]:
    """切换主显示器分辨率。

    返回 (是否成功, 返回码, 人类可读说明)。
    对不支持的组合会返回 DISP_CHANGE_BADMODE，不会把屏幕设黑。
    test_only=True 时只做可行性检测，不真正改分辨率。
    """
    device = device or _ACTIVE_DEVICE
    dm = _find_devmode(width, height, hz, device)
    if dm is None:
        code = DISP_CHANGE_BADMODE
        return (False, code, DISP_CHANGE_MSG.get(code, "模式不存在"))

    def _apply(flags: int) -> int:
        if device:
            # 指定屏：必须用 Ex 版本，第一个参数就是要动的那块屏
            return user32.ChangeDisplaySettingsExW(
                ctypes.c_wchar_p(device), ctypes.byref(dm), None, flags, None
            )
        return user32.ChangeDisplaySettingsW(ctypes.byref(dm), flags)

    # 先 TEST，能过滤掉不支持的模式，减少闪黑
    code = _apply(CDS_TEST)
    if code != DISP_CHANGE_SUCCESSFUL or test_only:
        ok = code == DISP_CHANGE_SUCCESSFUL or code == DISP_CHANGE_RESTART
        return (ok, code, DISP_CHANGE_MSG.get(code, f"未知错误 {code}"))

    code = _apply(CDS_UPDATEREGISTRY)
    ok = code == DISP_CHANGE_SUCCESSFUL or code == DISP_CHANGE_RESTART
    return (ok, code, DISP_CHANGE_MSG.get(code, f"未知错误 {code}"))


def restore_native(width: int, height: int, hz: int = 0) -> Tuple[bool, int, str]:
    """恢复指定的原生分辨率。"""
    return set_resolution(width, height, hz=hz)


def detect_native(device: Optional[str] = None) -> Tuple[int, int, int]:
    """按本机实际支持的显示模式推断原生分辨率。

    取面积最大的模式（4:3 档不会超过面板本身），再在同样尺寸里取最高刷新率。
    """
    modes = list_modes(device)
    if not modes:
        cur = get_current()
        return (*cur, 0)
    biggest = max(modes, key=lambda m: (m.width * m.height, m.hz))
    same = [m for m in modes if (m.width, m.height) == (biggest.width, biggest.height)]
    best = max(same, key=lambda m: m.hz)
    return (best.width, best.height, best.hz)


# 常见分辨率 → 推荐的"轻一档、同比例"目标。同比例 = 不拉伸也不会黑边。
_RECOMMEND = {
    (1920, 1080): (1600, 900),     # 1K：16:9 屏，降一档，无黑边
    (2560, 1440): (1920, 1080),    # 2K：降到 1080p，无黑边
    (3840, 2160): (2560, 1440),    # 4K：降到 2K
    (1680, 1050): (1280, 800),     # 16:10
    (1920, 1200): (1600, 1000),    # 16:10
    (1366, 768): (1280, 720),
    (3440, 1440): (2560, 1080),    # 21:9 带鱼屏
    (2560, 1080): (1920, 810),
    (1280, 960): (1024, 768),
}


def recommend_target(native) -> Tuple[int, int]:
    """按这块屏的原生分辨率，给一个"没黑边、又比原生轻"的目标档位。

    优先用预设表（1K → 1600×900，2K → 1920×1080），表里的档位这块屏不支持时，
    退到"同比例、不超过原生"的最大档；实在没有就保持原生（宁可不降，也不出黑边）。
    """
    nw, nh = int(native[0]), int(native[1])
    if nw <= 0 or nh <= 0:
        return (1280, 960)
    try:
        modes = [(m.width, m.height) for m in list_modes()]
    except Exception:
        modes = []
    has_modes = bool(modes)

    cand = _RECOMMEND.get((nw, nh))
    if cand and (not has_modes or cand in modes):
        return cand

    ratio = nw / nh if nh else 0.0
    same = [m for m in modes if abs(m[0] / m[1] - ratio) <= 0.02 and m[0] <= nw and m[1] <= nh]
    if same:
        same.sort()
        if same[-1] != (nw, nh):
            return same[-1]

    if abs(ratio - 16 / 9) <= 0.02:
        for c in ((1920, 1080), (1600, 900), (1280, 720), (960, 540)):
            if c[0] < nw and (not has_modes or c in modes):
                return c
    return (nw, nh)


def recommend_note(native, target) -> str:
    """推荐理由，写给人看的一句话。"""
    nw, nh = int(native[0]), int(native[1])
    tw, th = int(target[0]), int(target[1])
    if (tw, th) == (nw, nh):
        return f"就按原生 {nw}×{nh} 跑"
    same_ratio = bool(nh) and abs((tw / th) - (nw / nh)) <= 0.02
    tail = "同比例，不会出黑边" if same_ratio else "比例和屏幕不同，需要在显卡里设拉伸"
    return f"{nw}×{nh} 的屏配 {tw}×{th}（{tail}）"


def monitor_name() -> str:
    """主显示器型号名（EDID 描述），拿不到就退回适配器名。"""
    adapter = DISPLAY_DEVICEW()
    adapter.cb = ctypes.sizeof(DISPLAY_DEVICEW)
    idx = 0
    while user32.EnumDisplayDevicesW(None, idx, ctypes.byref(adapter), 0):
        if adapter.StateFlags & 0x1:
            mon = DISPLAY_DEVICEW()
            mon.cb = ctypes.sizeof(DISPLAY_DEVICEW)
            if user32.EnumDisplayDevicesW(adapter.DeviceName, 0, ctypes.byref(mon), 0):
                name = (mon.DeviceString or "").strip()
                if name and "Generic" not in name and "通用" not in name:
                    return name
            return (adapter.DeviceString or "").strip()
        idx += 1
        if idx > 32:
            break
    return primary_device_name()


def machine_tag() -> str:
    """机器指纹：显示器型号 + 原生分辨率。换机器 / 换屏会变。"""
    w, h, hz = detect_native()
    return f"{monitor_name()}|{w}x{h}"


def primary_device_name() -> str:
    """主显示器设备名，如 \\\\.\\DISPLAY1（日志用）。"""
    dev = DISPLAY_DEVICEW()
    dev.cb = ctypes.sizeof(DISPLAY_DEVICEW)
    index = 0
    while user32.EnumDisplayDevicesW(None, index, ctypes.byref(dev), 0):
        if dev.StateFlags & 0x1:  # DISPLAY_DEVICE_ATTACHED_TO_DESKTOP
            return dev.DeviceName
        index += 1
    return ""
