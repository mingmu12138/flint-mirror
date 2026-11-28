# -*- coding: utf-8 -*-
"""按键模拟层：把一串文本送进「当前前台窗口」，只做文本生成 + 键鼠模拟。

明确不做的事（这条是红线，写在这里防以后手滑）：
  · 不注入进程、不读写游戏内存、不改游戏文件、不 hook 任何东西
  · 不绕过任何反作弊，不做"拟人抖动"这类对抗
只是"我替你按 Ctrl+V 和回车"，跟你自己手按没有任何区别。

默认用剪贴板粘贴（长指令、中文名字都稳）；逐字 Unicode 输入是备选。
"""
from __future__ import annotations

import ctypes
import time
from ctypes import wintypes
from typing import List, Optional, Tuple

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

SW_RESTORE = 9
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

VK_CONTROL = 0x11
VK_MENU = 0x12
VK_RETURN = 0x0D
VK_V = 0x56

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# Java 版跑起来是 javaw.exe；基岩版是 Minecraft.Windows.exe；启动器另算
DEFAULT_GAME_PROCESS = (
    "javaw.exe",
    "java.exe",
    "minecraft.windows.exe",
    "minecraftlauncher.exe",
    "hmcl.exe",
    "prismlauncher.exe",
    "pcl2.exe",
    "pcl.exe",
)
GAME_TITLE_WORDS = ("minecraft", "我的世界")

MAX_TEXT = 4000


def _declare_prototypes() -> None:  # noqa: D401
    """Win32 原型必须写死：不声明 restype，64 位句柄会被 ctypes 当 32 位截断，
    剪贴板那种 GlobalLock(截断句柄) 就会直接读崩（实测踩过一次）。"""
    u = user32
    k = kernel32
    u.OpenClipboard.argtypes = [wintypes.HWND]
    u.OpenClipboard.restype = wintypes.BOOL
    u.CloseClipboard.restype = wintypes.BOOL
    u.EmptyClipboard.restype = wintypes.BOOL
    u.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    u.IsClipboardFormatAvailable.restype = wintypes.BOOL
    u.GetClipboardData.argtypes = [wintypes.UINT]
    u.GetClipboardData.restype = wintypes.HANDLE
    u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u.SetClipboardData.restype = wintypes.HANDLE
    u.GetForegroundWindow.restype = wintypes.HWND
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.c_void_p]
    u.GetWindowThreadProcessId.restype = wintypes.DWORD
    u.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    u.GetWindowTextLengthW.restype = ctypes.c_int
    u.GetWindowTextW.argtypes = [wintypes.HWND, ctypes.c_wchar_p, ctypes.c_int]
    u.GetWindowTextW.restype = ctypes.c_int
    u.IsWindowVisible.argtypes = [wintypes.HWND]
    u.IsWindowVisible.restype = wintypes.BOOL
    u.EnumWindows.restype = wintypes.BOOL
    u.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    u.ShowWindow.restype = wintypes.BOOL
    u.SetForegroundWindow.argtypes = [wintypes.HWND]
    u.SetForegroundWindow.restype = wintypes.BOOL
    u.BringWindowToTop.argtypes = [wintypes.HWND]
    u.BringWindowToTop.restype = wintypes.BOOL
    u.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                               ctypes.c_int, ctypes.c_int, wintypes.UINT]
    u.SetWindowPos.restype = wintypes.BOOL
    u.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    u.AttachThreadInput.restype = wintypes.BOOL
    u.SendInput.argtypes = [wintypes.UINT, ctypes.c_void_p, ctypes.c_int]
    u.SendInput.restype = wintypes.UINT
    k.GetCurrentThreadId.restype = wintypes.DWORD
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.CloseHandle.restype = wintypes.BOOL
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                             ctypes.c_wchar_p, ctypes.c_void_p]
    k.QueryFullProcessImageNameW.restype = wintypes.BOOL
    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k.GlobalAlloc.restype = wintypes.HANDLE
    k.GlobalLock.argtypes = [wintypes.HANDLE]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalUnlock.argtypes = [wintypes.HANDLE]
    k.GlobalUnlock.restype = wintypes.BOOL
    k.GlobalFree.argtypes = [wintypes.HANDLE]
    k.GlobalFree.restype = wintypes.HANDLE


_declare_prototypes()


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", _ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


# ---------------------------------------------------------------- 底层按键
def _vk(vk: int, up: bool = False) -> "INPUT":
    ki = KEYBDINPUT(wVk=int(vk), wScan=0,
                    dwFlags=KEYEVENTF_KEYUP if up else 0,
                    time=0, dwExtraInfo=0)
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=ki))


def _uni(code: int, up: bool = False) -> "INPUT":
    flags = KEYEVENTF_UNICODE | (KEYEVENTF_KEYUP if up else 0)
    ki = KEYBDINPUT(wVk=0, wScan=int(code), dwFlags=flags, time=0, dwExtraInfo=0)
    return INPUT(type=INPUT_KEYBOARD, u=_INPUTUNION(ki=ki))


def _send(items: List["INPUT"]) -> bool:
    if not items:
        return True
    arr = (INPUT * len(items))(*items)
    sent = user32.SendInput(len(items), ctypes.byref(arr, 0), ctypes.sizeof(INPUT))
    return int(sent or 0) == len(items)


# ---------------------------------------------------------------- 前台 / 窗口
def foreground_hwnd() -> int:
    return int(user32.GetForegroundWindow() or 0)


def process_name(hwnd: int) -> str:
    pid = wintypes.DWORD(0)
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return ""
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value.rsplit("\\", 1)[-1].lower()
    finally:
        kernel32.CloseHandle(h)
    return ""


def window_title(hwnd: int) -> str:
    if not hwnd:
        return ""
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def foreground_info() -> Tuple[int, str, str]:
    hwnd = foreground_hwnd()
    return hwnd, process_name(hwnd), window_title(hwnd)


def is_game_window(hwnd: int) -> bool:
    proc = process_name(hwnd)
    if proc in DEFAULT_GAME_PROCESS:
        return True
    low = window_title(hwnd).lower()
    return any(w in low for w in GAME_TITLE_WORDS)


def enum_windows() -> List[Tuple[int, str, str]]:
    """可见的顶层窗口（hwnd, 进程名, 标题）。"""
    out: List[Tuple[int, str, str]] = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def _cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            title = window_title(hwnd)
            if title:
                out.append((int(hwnd), process_name(hwnd), title))
        return True

    user32.EnumWindows(proto(_cb), 0)
    return out


def find_game_window() -> Optional[int]:
    """先按进程名精确找，再按标题兜底；找不到返回 None。"""
    hits = enum_windows()
    for hwnd, proc, _title in hits:
        if proc in DEFAULT_GAME_PROCESS:
            return hwnd
    for hwnd, _proc, title in hits:
        if any(w in title.lower() for w in GAME_TITLE_WORDS):
            return hwnd
    return None


def activate(hwnd: int) -> bool:
    """把目标窗口拉到前台。Windows 有前台锁，这里用 AttachThreadInput + Alt 两招。"""
    if not hwnd:
        return False
    try:
        user32.ShowWindow(hwnd, SW_RESTORE)
    except Exception:  # noqa: BLE001
        pass
    if foreground_hwnd() == hwnd:
        return True
    fg = foreground_hwnd()
    fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    cur_thread = kernel32.GetCurrentThreadId()
    attached = False
    try:
        if fg_thread and fg_thread != cur_thread:
            attached = bool(user32.AttachThreadInput(cur_thread, fg_thread, True))
        # 轻按一下 Alt，让系统认这一步是"用户意图"
        _send([_vk(VK_MENU), _vk(VK_MENU, up=True)])
        user32.BringWindowToTop(hwnd)
        ok = bool(user32.SetForegroundWindow(hwnd))
        if not ok:
            user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
            user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)
            ok = bool(user32.SetForegroundWindow(hwnd))
        return ok
    finally:
        if attached:
            try:
                user32.AttachThreadInput(cur_thread, fg_thread, False)
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------- 剪贴板
def get_clipboard_text() -> str:
    if not user32.OpenClipboard(None):
        return ""
    try:
        if not user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return ""
        h = user32.GetClipboardData(CF_UNICODETEXT)
        if not h:
            return ""
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            return ""
        try:
            return ctypes.wstring_at(int(ptr)) or ""
        finally:
            kernel32.GlobalUnlock(h)
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text: str) -> bool:
    """写剪贴板；被别的程序占着就短重试几次。"""
    data = ctypes.create_unicode_buffer(text or "")
    size = ctypes.sizeof(data)
    for _ in range(6):
        if user32.OpenClipboard(None):
            break
        time.sleep(0.05)
    else:
        return False
    try:
        user32.EmptyClipboard()
        h = kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not h:
            return False
        ptr = kernel32.GlobalLock(h)
        if not ptr:
            kernel32.GlobalFree(h)
            return False
        try:
            ctypes.memmove(int(ptr), ctypes.addressof(data), size)
        finally:
            kernel32.GlobalUnlock(h)
        if not user32.SetClipboardData(CF_UNICODETEXT, h):
            kernel32.GlobalFree(h)
            return False
        return True
    finally:
        user32.CloseClipboard()


# ---------------------------------------------------------------- 对外动作
def type_text(text: str) -> bool:
    """逐字 Unicode 输入（不经过剪贴板）。"""
    text = (text or "")[:MAX_TEXT]
    items: List[INPUT] = []
    for ch in text:
        code = ord(ch)
        if code > 0xFFFF:
            hi = 0xD800 + ((code - 0x10000) >> 10)
            lo = 0xDC00 + ((code - 0x10000) & 0x3FF)
            items.extend([_uni(hi), _uni(hi, up=True), _uni(lo), _uni(lo, up=True)])
        else:
            items.extend([_uni(code), _uni(code, up=True)])
    return _send(items)


def paste_text(text: str, restore: bool = True) -> bool:
    """剪贴板 + Ctrl+V；完成后把原来的剪贴板还回去。"""
    text = (text or "")[:MAX_TEXT]
    old = get_clipboard_text() if restore else ""
    if not set_clipboard_text(text):
        return False
    ok = _send([
        _vk(VK_CONTROL),
        _vk(VK_V),
        _vk(VK_V, up=True),
        _vk(VK_CONTROL, up=True),
    ])
    time.sleep(0.12)
    if restore:
        try:
            set_clipboard_text(old)
        except Exception:  # noqa: BLE001
            pass
    return ok


def press_enter() -> bool:
    return _send([_vk(VK_RETURN), _vk(VK_RETURN, up=True)])


def send_command(cmd: str, method: str = "paste", enter: bool = True,
                 hwnd: Optional[int] = None,
                 activate_window: bool = True) -> Tuple[bool, str]:
    """把一条指令送进游戏。返回 (成功没有, 人话说明)。

    method: paste（剪贴板粘贴，默认） / type（逐字输入）
    失败原因写清楚，不假装成功。
    """
    cmd = (cmd or "").strip()
    if not cmd:
        return False, "指令是空的"
    if len(cmd) > MAX_TEXT:
        return False, f"这条太长了（{len(cmd)} 字），超过 {MAX_TEXT}"

    win = int(hwnd or 0) or find_game_window()
    if not win:
        return False, "没找到 Minecraft 窗口：先把游戏开起来（Java 版是 javaw.exe）"
    if activate_window:
        if not activate(win):
            return False, "拉不到游戏前台：点「延迟 3 秒发送」，然后自己点到游戏窗口"
        time.sleep(0.25)
    fg = foreground_hwnd()
    if fg and fg != win:
        return False, "现在的前台不是那个游戏窗口，怕发错地方，没发"

    if method == "type":
        ok = type_text(cmd)
    else:
        ok = paste_text(cmd)
    if not ok:
        return False, "按键没送出去（键盘可能被别的程序占了），再试一次"
    if enter:
        time.sleep(0.05)
        if not press_enter():
            return False, "文字进去了，但回车没按下去——自己按一下回车"
    return True, "已发送"
