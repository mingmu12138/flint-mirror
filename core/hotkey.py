"""全局热键：RegisterHotKey + Qt 原生事件过滤器（无需第三方库）。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable, Dict, List, Optional, Tuple

from PySide6 import QtCore

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
WM_HOTKEY = 0x0312

user32 = ctypes.WinDLL("user32", use_last_error=True)

# 常用虚拟键码（历史保留，新代码请用 parse_hotkey）
VK = {
    "R": 0x52,
    "S": 0x53,
    "V": 0x56,
    "B": 0x42,
    "M": 0x4D,
    "O": 0x4F,
    "1": 0x31,
    "2": 0x32,
}

# 键名 ↔ 虚拟键码
_NAMED = {
    "SPACE": 0x20, "TAB": 0x09, "ENTER": 0x0D, "RETURN": 0x0D,
    "ESC": 0x1B, "ESCAPE": 0x1B, "BACKSPACE": 0x08,
    "INSERT": 0x2D, "DELETE": 0x2E, "HOME": 0x24, "END": 0x23,
    "PGUP": 0x21, "PAGEUP": 0x21, "PGDN": 0x22, "PAGEDOWN": 0x22,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    "CAPSLOCK": 0x14,
}
_SYMBOLS = {
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE,
    "/": 0xBF, "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}
_SYMBOL_NAME = {v: k for k, v in _SYMBOLS.items()}
_NAMED_NAME = {v: k for k, v in _NAMED.items()}


def vk_for(name: str) -> Optional[int]:
    """键名 → 虚拟键码。支持 A-Z、0-9、F1-F24、Space/Enter 等。"""
    u = (name or "").strip().upper()
    if not u:
        return None
    if len(u) == 1:
        if "A" <= u <= "Z" or "0" <= u <= "9":
            return ord(u)
        return _SYMBOLS.get(u)
    if u.startswith("F") and u[1:].isdigit():
        n = int(u[1:])
        if 1 <= n <= 24:
            return 0x70 + n - 1
    return _NAMED.get(u)


def key_name(vk: int) -> str:
    """虚拟键码 → 键名。"""
    vk = int(vk)
    if 0x41 <= vk <= 0x5A or 0x30 <= vk <= 0x39:
        return chr(vk)
    if 0x70 <= vk <= 0x87:
        return f"F{vk - 0x70 + 1}"
    if vk in _SYMBOL_NAME:
        return _SYMBOL_NAME[vk]
    if vk in _NAMED_NAME:
        return _NAMED_NAME[vk].capitalize()
    return f"VK{vk}"


def format_hotkey(vk: int, modifiers: int) -> str:
    """(主键, 修饰键) → "Ctrl+Alt+M"。参数顺序与 parse_hotkey 的返回值一致，方便 * 展开。"""
    parts: List[str] = []
    if modifiers & MOD_CONTROL:
        parts.append("Ctrl")
    if modifiers & MOD_ALT:
        parts.append("Alt")
    if modifiers & MOD_SHIFT:
        parts.append("Shift")
    if modifiers & MOD_WIN:
        parts.append("Win")
    parts.append(key_name(vk))
    return "+".join(parts)


def parse_hotkey(text: str) -> Optional[Tuple[int, int]]:
    """“Ctrl+Alt+M” → (vk, modifiers)。必须有修饰键，且只有一个主键，否则返回 None。"""
    if not text:
        return None
    raw = str(text).replace(" ", "")
    if not raw:
        return None
    parts = [p for p in raw.split("+") if p]
    if not parts:
        return None
    mods = 0
    vk: Optional[int] = None
    for p in parts:
        u = p.upper()
        if u in ("CTRL", "CONTROL"):
            mods |= MOD_CONTROL
        elif u == "ALT":
            mods |= MOD_ALT
        elif u == "SHIFT":
            mods |= MOD_SHIFT
        elif u in ("WIN", "META", "SUPER"):
            mods |= MOD_WIN
        else:
            v = vk_for(u)
            if v is None or vk is not None:
                return None
            vk = v
    if vk is None or mods == 0:
        return None
    return vk, mods


class HotkeyManager(QtCore.QAbstractNativeEventFilter):
    """在指定窗口句柄上注册全局热键，触发时回调 Python 函数。"""

    def __init__(self) -> None:
        super().__init__()
        self._handlers: Dict[int, Callable[[], None]] = {}
        self._next_id = 0x0001
        self._hwnd: Optional[int] = None
        self.ok_count = 0
        self.fail_count = 0

    # ------------------------------------------------------------------
    def attach(self, widget: QtCore.QObject) -> None:
        """绑定窗口句柄（窗口 show 之后再调用）。"""
        try:
            self._hwnd = int(widget.winId())
        except Exception:
            self._hwnd = None

    def register(self, vk: int, modifiers: int, callback: Callable[[], None]) -> bool:
        if self._hwnd is None:
            return False
        hotkey_id = self._next_id
        self._next_id += 1
        ok = bool(user32.RegisterHotKey(self._hwnd, hotkey_id, modifiers, vk))
        if ok:
            self._handlers[hotkey_id] = callback
            self.ok_count += 1
        else:
            self.fail_count += 1
        return ok

    def unregister_all(self) -> None:
        if self._hwnd is None:
            return
        for hotkey_id in list(self._handlers.keys()):
            user32.UnregisterHotKey(self._hwnd, hotkey_id)
        self._handlers.clear()

    @property
    def active_count(self) -> int:
        return len(self._handlers)

    # ------------------------------------------------------------------
    def nativeEventFilter(self, eventType, message):
        try:
            if eventType in ("windows_generic_MSG", b"windows_generic_MSG"):
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY:
                    handler = self._handlers.get(int(msg.wParam))
                    if handler is not None:
                        handler()
                        return True, 0
        except Exception:
            pass
        return False, 0
