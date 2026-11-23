"""显示缩放模式：读取当前是「保持宽高比（有黑边）」还是「拉伸铺满（无黑边）」。

只做读取和引导，不写入 —— N 卡/A 卡都不允许外部程序改这个开关，
驱动面板里点一次就行，改完是全局持久的。
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import Tuple

user32 = ctypes.WinDLL("user32", use_last_error=True)

QDC_ONLY_ACTIVE_PATHS = 0x2

SCALING_IDENTITY = 1
SCALING_CENTERED = 2
SCALING_STRETCHED = 3
SCALING_ASPECTRATIOCENTEREDMAX = 4
SCALING_CUSTOM = 5
SCALING_PREFERRED = 128

SCALING_TEXT = {
    SCALING_IDENTITY: "不缩放（1:1 居中，四周都有黑边）",
    SCALING_CENTERED: "居中显示（四周都有黑边）",
    SCALING_STRETCHED: "拉伸铺满（无黑边，画面会横向变宽）",
    SCALING_ASPECTRATIOCENTEREDMAX: "保持宽高比（左右有黑边）",
    SCALING_CUSTOM: "自定义缩放",
    SCALING_PREFERRED: "驱动推荐缩放",
}


class LUID(ctypes.Structure):
    _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", ctypes.c_long)]


class PATH_SOURCE_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("statusFlags", wintypes.UINT),
    ]


class RATIONAL(ctypes.Structure):
    _fields_ = [("Numerator", wintypes.UINT), ("Denominator", wintypes.UINT)]


class PATH_TARGET_INFO(ctypes.Structure):
    _fields_ = [
        ("adapterId", LUID),
        ("id", wintypes.UINT),
        ("modeInfoIdx", wintypes.UINT),
        ("outputTechnology", wintypes.UINT),
        ("rotation", wintypes.UINT),
        ("scaling", wintypes.UINT),
        ("refreshRate", RATIONAL),
        ("scanLineOrdering", wintypes.UINT),
    ]


class PATH_INFO(ctypes.Structure):
    _fields_ = [
        ("sourceInfo", PATH_SOURCE_INFO),
        ("targetInfo", PATH_TARGET_INFO),
        ("flags", wintypes.UINT),
        # 结构在 x64 下按 8 字节对齐，尾部留 8 字节，否则系统写越界
        ("_tail", ctypes.c_byte * 8),
    ]


class MODE_INFO(ctypes.Structure):
    _fields_ = [
        ("infoType", ctypes.c_int),
        ("id", wintypes.UINT),
        ("adapterId", LUID),
        ("_pad", ctypes.c_byte * 48),
    ]


OUTPUT_TECH = {
    0: "VGA",
    1: "S-Video",
    2: "复合视频",
    3: "分量",
    4: "DVI",
    5: "HDMI",
    6: "LVDS（笔记本内屏）",
    7: "D_JPN",
    8: "SDI",
    9: "DisplayPort",
    10: "DisplayPort（内置）",
    11: "UDI",
    12: "UDI",
    13: "SDTV 转接",
    0xFFFFFFFF: "未知",
}


def get_state() -> dict:
    """读主屏的完整状态。

    返回 {'code','desc','tech','tech_name','hz'}；读不到时 code=0、tech=-1。
    """
    out = {"code": 0, "desc": "读不到", "tech": -1, "tech_name": "读不到", "hz": 0.0}
    np = wintypes.UINT(0)
    nm = wintypes.UINT(0)
    try:
        rc = user32.GetDisplayConfigBufferSizes(
            QDC_ONLY_ACTIVE_PATHS, ctypes.byref(np), ctypes.byref(nm)
        )
        if rc != 0 or np.value == 0:
            return out
        paths = (PATH_INFO * np.value)()
        modes = (MODE_INFO * nm.value)()
        rc = user32.QueryDisplayConfig(
            QDC_ONLY_ACTIVE_PATHS, ctypes.byref(np), paths, ctypes.byref(nm), modes, None
        )
        if rc != 0:
            return out
        t = paths[0].targetInfo
        code = int(t.scaling)
        tech = int(t.outputTechnology)
        hz = 0.0
        try:
            num = int(t.refreshRate.Numerator)
            den = int(t.refreshRate.Denominator) or 1
            hz = num / den
        except Exception:  # noqa: BLE001
            hz = 0.0
        return {
            "code": code,
            "desc": SCALING_TEXT.get(code, f"未知模式 {code}"),
            "tech": tech,
            "tech_name": OUTPUT_TECH.get(tech, f"接口 {tech}"),
            "hz": hz,
        }
    except Exception:  # noqa: BLE001
        return out


def advice(state: dict) -> str:
    """根据接口和刷新率给一条「你这台大概是哪种情况」。"""
    if not state:
        return ""
    code = state.get("code") or 0
    tech = state.get("tech", -1)
    hz = state.get("hz") or 0.0
    name = state.get("tech_name", "")
    if code == SCALING_STRETCHED:
        return "已经拉伸铺满，不用再改。"
    if tech == 5 and hz >= 120:  # HDMI + 高刷，GPU 缩放常被驱动关掉
        return (
            f"你这台是 {name} 走 {hz:.0f}Hz 高刷：GPU 缩放大概率被驱动关掉了，"
            "属于「乙方案」——换 DP 线再试；临时想铺满就在游戏里设 4:3 + 独占全屏。"
        )
    if tech in (9, 10):
        return (
            f"你这台是 {name} 输出：去显卡面板把缩放设备改成「GPU」、模式「全屏」，"
            "一般就能铺满，不用换线。"
        )
    if tech >= 0 and name:
        return f"{name} 输出：先试显卡面板的「全屏 / 拉伸」，改不动再用游戏内 4:3 + 独占全屏。"
    return "先试显卡面板的「全屏 / 拉伸」，改不动再用游戏内 4:3 + 独占全屏。"


def get_scaling() -> Tuple[int, str]:
    """返回主路径的缩放模式 (代码, 中文说明)。读不到时返回 (0, "读不到")。"""
    np = wintypes.UINT(0)
    nm = wintypes.UINT(0)
    try:
        rc = user32.GetDisplayConfigBufferSizes(
            QDC_ONLY_ACTIVE_PATHS, ctypes.byref(np), ctypes.byref(nm)
        )
        if rc != 0 or np.value == 0:
            return (0, "读不到")
        paths = (PATH_INFO * np.value)()
        modes = (MODE_INFO * nm.value)()
        rc = user32.QueryDisplayConfig(
            QDC_ONLY_ACTIVE_PATHS, ctypes.byref(np), paths, ctypes.byref(nm), modes, None
        )
        if rc != 0:
            return (0, "读不到")
        # 取第一条活动路径（主屏）
        code = int(paths[0].targetInfo.scaling)
        return (code, SCALING_TEXT.get(code, f"未知模式 {code}"))
    except Exception:
        return (0, "读不到")


def is_stretched() -> bool:
    return get_scaling()[0] == SCALING_STRETCHED


VENDOR_PATHS = {
    "nvidia": [
        (
            r"C:\Program Files\NVIDIA Corporation\NVIDIA app\CEF\NVIDIA app.exe",
            "NVIDIA App",
        ),
        (
            r"C:\Program Files\NVIDIA Corporation\NVIDIA App\CEF\NVIDIA app.exe",
            "NVIDIA App",
        ),
        (
            r"C:\Program Files\NVIDIA Corporation\Control Panel Client\nvcplui.exe",
            "NVIDIA 控制面板",
        ),
    ],
    "amd": [
        (r"C:\Program Files\AMD\CNext\CNext\RadeonSoftware.exe", "AMD Software"),
    ],
    "intel": [
        (
            r"C:\Program Files\Intel\Intel(R) Graphics Command Center\Intel.Graphics.Command.Center.exe",
            "Intel 显卡中心",
        ),
    ],
}

STEPS = {
    "nvidia": "NVIDIA App → 系统 → 显示器 → 点显示器卡片 → 缩放：模式选「全屏」、设备选「GPU」",
    "amd": "AMD Software → 齿轮「设置」→ 显示 → 缩放模式 → 选「整个面板」",
    "intel": "Intel 显卡中心 → 显示 → 缩放 → 选「拉伸」",
    "auto": "在显卡面板里把缩放模式改成「全屏 / 拉伸」",
}

HELP_DETAIL = {
    "nvidia": (
        "控制面板 → 显示 → 调整桌面尺寸和位置：\n"
        "  缩放模式：全屏；缩放设备：GPU；勾「覆盖由游戏和程序设置的缩放模式」\n\n"
        "如果「缩放设备」只有「显示」而且灰着（HDMI 高刷很常见），说明 GPU 缩放被驱动关了。\n"
        "这种情况下黑边是显卡画在画面里的：显示器收到的仍是 1920×1080 整幅图，\n"
        "所以改显示器 OSD 的画面比例不会有效果。能拉满的只有两条：\n"
        "  ① 游戏内把分辨率设成 4:3，显示模式选「独占全屏」，游戏自己会铺满\n"
        "  ② 换 DP 线再试（DP 跑高刷不需要 DSC，GPU 缩放可能解锁）"
    ),
    "amd": (
        "AMD Software → 右上齿轮「设置」→ 显示 → 缩放模式 → 选「整个面板」，下面开启 GPU 缩放。"
    ),
    "intel": "Intel 显卡中心 → 显示 → 缩放 → 选「拉伸」。",
    "auto": "在显卡面板里把缩放模式改成「全屏 / 拉伸」。",
}


def detect_vendor() -> str:
    """看装了哪家的独显。有 NVIDIA 独显就优先 NVIDIA（外接屏通常走它）。"""
    names = []
    try:
        import winreg

        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}",
        )
        i = 0
        while True:
            try:
                sub = winreg.EnumKey(key, i)
            except OSError:
                break
            if sub.isdigit():
                try:
                    with winreg.OpenKey(key, sub) as sk:
                        desc, _ = winreg.QueryValueEx(sk, "DriverDesc")
                        names.append(str(desc))
                except OSError:
                    pass
            i += 1
    except OSError:
        return "auto"

    low = [n.lower() for n in names]
    if any("nvidia" in n or "geforce" in n for n in low):
        return "nvidia"
    if any("radeon rx" in n or "radeon pro" in n for n in low):
        return "amd"
    if any("intel" in n for n in low):
        return "intel"
    if any("amd" in n or "radeon" in n for n in low):
        return "amd"
    return "auto"


def open_driver_panel(vendor: str = "auto") -> tuple:
    """打开能改缩放模式的地方。返回 (打开了什么, 该点哪里)。"""
    v = (vendor or "auto").strip().lower()
    if v == "auto":
        v = detect_vendor()

    order = [v] if v in VENDOR_PATHS else ["nvidia", "amd", "intel"]
    target = v if v in VENDOR_PATHS else "auto"

    for key in order:
        for path, name in VENDOR_PATHS.get(key, []):
            if os.path.exists(path):
                try:
                    os.startfile(path)
                    return (name, STEPS.get(key, STEPS["auto"]))
                except OSError:
                    continue

    try:
        os.startfile("ms-settings:display-advanced")
        return ("Windows 高级显示设置", "缩放模式在显卡面板里，系统设置里没有")
    except OSError:
        return ("没找到显卡面板", STEPS.get(target, STEPS["auto"]))
