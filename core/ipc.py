"""跨进程通信：互斥量判断单实例 + 命令文件传递指令。

纯 ctypes / 标准库实现，不加载 Qt，所以双击时可以在 0.1 秒内完成"切换分辨率"。
"""

from __future__ import annotations

import ctypes
import json
import tempfile
import time
from pathlib import Path
from typing import Optional

MUTEX_NAME = "Local\\GameHub.Mutex.3843703688"
CMD_FILE = Path(tempfile.gettempdir()) / "gamehub_command.json"
ERROR_ALREADY_EXISTS = 183
SYNCHRONIZE = 0x00100000

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = ctypes.c_void_p
_kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
_kernel32.OpenMutexW.restype = ctypes.c_void_p
_kernel32.OpenMutexW.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p]
_kernel32.SetHandleInformation.restype = ctypes.c_int
_kernel32.SetHandleInformation.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint]
HANDLE_FLAG_INHERIT = 0x00000001

_kernel32.CloseHandle.restype = ctypes.c_int
_kernel32.CloseHandle.argtypes = [ctypes.c_void_p]


def instance_running() -> bool:
    """已经有主实例在运行吗？"""
    handle = _kernel32.OpenMutexW(SYNCHRONIZE, 0, MUTEX_NAME)
    if handle:
        _kernel32.CloseHandle(handle)
        return True
    return False


def acquire_mutex() -> Optional[int]:
    """主实例调用：抢占互斥量。成功返回句柄（进程退出自动释放），已被占用返回 None。"""
    handle = _kernel32.CreateMutexW(None, 0, MUTEX_NAME)
    if not handle:
        return None
    _kernel32.SetHandleInformation(handle, HANDLE_FLAG_INHERIT, 0)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(handle)
        return None
    return handle


def send_command(cmd: str) -> bool:
    """向正在运行的实例发送指令（toggle / show）。"""
    try:
        CMD_FILE.write_text(
            json.dumps({"cmd": cmd, "ts": time.time()}), encoding="utf-8"
        )
        return True
    except OSError:
        return False


def poll_command() -> Optional[str]:
    """主实例调用：取走并删除等待中的指令。"""
    try:
        if not CMD_FILE.exists():
            return None
        raw = CMD_FILE.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        CMD_FILE.unlink()
    except OSError:
        pass
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return ""
    if isinstance(data, dict):
        return str(data.get("cmd") or "")
    return ""


def clear_command() -> None:
    try:
        CMD_FILE.unlink()
    except OSError:
        pass
