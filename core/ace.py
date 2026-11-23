"""把 ACE 反作弊的扫描进程"压低"，让它别跟游戏抢 CPU 和磁盘。

做法（和社区教程一致，官方任务管理器也能这么点）：
  · 优先级压到最低（优先用 PROCESS_MODE_BACKGROUND_BEGIN，同时压低磁盘 I/O 优先级）
  · CPU 亲和性只留最后一个逻辑核

为什么只做这两件事、不做「禁止读取」：
  · 禁止读取（火绒自定义防护那种 ACL 拦截）会真的挡死反作弊的扫描，
    属于干扰安全组件，可能触发「安全组件运行异常」甚至封号。
  · 压低优先级只是让它在调度上排在游戏后面，扫描照常跑完，功能不受影响，
    目的就是别在游戏里抢 CPU / 抢磁盘导致掉帧。
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import List, Tuple

import psutil

# 进程名匹配（小写）。ACE 的扫描进程以 SGuard 开头，另有 ACE- 前缀的几个。
NAME_PATTERNS = (
    "sguard",
    "ace-guard",
    "aceguard",
    "ace-tray",
    "anticheatexpert",
    "ace-base",
    "ace-guard client",
)

PROCESS_SET_INFORMATION = 0x0200
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

IDLE_PRIORITY_CLASS = 0x00000040
NORMAL_PRIORITY_CLASS = 0x00000020
PROCESS_MODE_BACKGROUND_BEGIN = 0x00100000
PROCESS_MODE_BACKGROUND_END = 0x00200000
HIGH_PRIORITY_CLASS = 0x00000080

PROCESS_IO_PRIORITY = 33  # SetProcessInformation 的 ProcessIoPriority
IO_PRIORITY_VERY_LOW = 0

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.OpenProcess.restype = wintypes.HANDLE
_k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.SetPriorityClass.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_k32.SetPriorityClass.restype = wintypes.BOOL
_k32.GetPriorityClass.argtypes = [wintypes.HANDLE]
_k32.GetPriorityClass.restype = wintypes.DWORD
_k32.SetProcessAffinityMask.argtypes = [wintypes.HANDLE, ctypes.c_size_t]
_k32.SetProcessAffinityMask.restype = wintypes.BOOL
_k32.GetProcessAffinityMask.argtypes = [
    wintypes.HANDLE,
    ctypes.POINTER(ctypes.c_size_t),
    ctypes.POINTER(ctypes.c_size_t),
]
_k32.GetProcessAffinityMask.restype = wintypes.BOOL


class _IoPriorityInfo(ctypes.Structure):
    _fields_ = [("IoPriority", wintypes.ULONG)]


_k32.SetProcessInformation.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
]
_k32.SetProcessInformation.restype = wintypes.BOOL


# ---------------------------------------------------------------------------
# 权限
# ---------------------------------------------------------------------------
def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def enable_debug_privilege() -> bool:
    """打开 SeDebugPrivilege；改 SYSTEM 进程（SGuard 就是）需要它。"""
    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    TOKEN_ADJUST_PRIVILEGES = 0x0020
    TOKEN_QUERY = 0x0008
    SE_PRIVILEGE_ENABLED = 0x00000002

    class LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Luid", LUID), ("Attributes", wintypes.DWORD)]

    class TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [
            ("PrivilegeCount", wintypes.DWORD),
            ("Privileges", LUID_AND_ATTRIBUTES * 1),
        ]

    token = wintypes.HANDLE()
    if not advapi.OpenProcessToken(
        _k32.GetCurrentProcess(),
        TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY,
        ctypes.byref(token),
    ):
        return False
    try:
        luid = LUID()
        if not advapi.LookupPrivilegeValueW(
            None, ctypes.c_wchar_p("SeDebugPrivilege"), ctypes.byref(luid)
        ):
            return False
        tp = TOKEN_PRIVILEGES(
            1,
            (LUID_AND_ATTRIBUTES * 1)(LUID_AND_ATTRIBUTES(luid, SE_PRIVILEGE_ENABLED)),
        )
        advapi.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None)
        return ctypes.get_last_error() == 0
    finally:
        _k32.CloseHandle(token)


def relaunch_as_admin() -> bool:
    """以管理员身份重新拉起自己（静默进托盘，用户再双击开面板）。"""
    exe = sys.executable
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, "--tray", None, 1)
        return rc > 32
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 进程识别
# ---------------------------------------------------------------------------
def _matched(name: str) -> bool:
    low = (name or "").lower()
    return any(p in low for p in NAME_PATTERNS)


def find_processes() -> List[Tuple[int, str]]:
    found: List[Tuple[int, str]] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            name = proc.info.get("name") or ""
            if _matched(name):
                found.append((int(proc.info["pid"]), name))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return found


def _cpu_count() -> int:
    try:
        n = psutil.cpu_count(logical=True) or 1
    except Exception:
        n = 1
    return max(1, n)


def _last_core_mask() -> int:
    return 1 << (_cpu_count() - 1)


def _all_core_mask() -> int:
    n = min(_cpu_count(), 64)
    return (1 << n) - 1


def _open(pid: int, access: int):
    return _k32.OpenProcess(access, False, pid)


# ---------------------------------------------------------------------------
# 施加 / 还原
# ---------------------------------------------------------------------------
def _set_io_priority(handle, level: int) -> bool:
    info = _IoPriorityInfo(level)
    return bool(
        _k32.SetProcessInformation(
            handle, PROCESS_IO_PRIORITY, ctypes.byref(info), ctypes.sizeof(info)
        )
    )


def limit_one(pid: int, limit_cpu: bool = True) -> Tuple[bool, str]:
    handle = _open(pid, PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION)
    if not handle:
        code = ctypes.get_last_error()
        return False, f"打不开进程（错误 {code}，多为权限不足）"
    try:
        lowered = bool(_k32.SetPriorityClass(handle, IDLE_PRIORITY_CLASS))
        if not lowered:
            return False, "被进程拒绝了（反作弊自我保护）"

        _set_io_priority(handle, IO_PRIORITY_VERY_LOW)

        if limit_cpu:
            _k32.SetProcessAffinityMask(handle, _last_core_mask())
        return True, "已压低"
    finally:
        _k32.CloseHandle(handle)


def restore_one(pid: int) -> Tuple[bool, str]:
    handle = _open(pid, PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION)
    if not handle:
        return False, "打不开进程"
    try:
        _k32.SetPriorityClass(handle, NORMAL_PRIORITY_CLASS)
        _set_io_priority(handle, 2)
        _k32.SetProcessAffinityMask(handle, _all_core_mask())
        return True, "已恢复"
    finally:
        _k32.CloseHandle(handle)


def apply_limits(limit_cpu: bool = True) -> Tuple[int, int, List[str]]:
    """返回 (成功数, 总数, 失败原因列表)。"""
    procs = find_processes()
    ok = 0
    fails: List[str] = []
    if is_admin():
        enable_debug_privilege()
    for pid, _name in procs:
        good, why = limit_one(pid, limit_cpu)
        if good:
            ok += 1
        else:
            fails.append(why)
    return ok, len(procs), fails


def restore_all() -> Tuple[int, int]:
    procs = find_processes()
    ok = 0
    for pid, _name in procs:
        good, _why = restore_one(pid)
        if good:
            ok += 1
    return ok, len(procs)


# ---------------------------------------------------------------------------
# 状态
# ---------------------------------------------------------------------------
def _read_state(pid: int) -> Tuple[str, int]:
    handle = _open(pid, PROCESS_QUERY_LIMITED_INFORMATION)
    if not handle:
        return "unknown", 0
    try:
        cls = int(_k32.GetPriorityClass(handle))
        proc_mask = ctypes.c_size_t(0)
        sys_mask = ctypes.c_size_t(0)
        has_mask = bool(
            _k32.GetProcessAffinityMask(
                handle, ctypes.byref(proc_mask), ctypes.byref(sys_mask)
            )
        )
        return ("low" if cls in (IDLE_PRIORITY_CLASS, PROCESS_MODE_BACKGROUND_BEGIN) else "normal"), (
            int(proc_mask.value) if has_mask else 0
        )
    finally:
        _k32.CloseHandle(handle)


def snapshot() -> Tuple[int, int, bool]:
    """返回 (进程数, 已压低的个数, 是否被限制到单核)。"""
    procs = find_processes()
    if is_admin():
        enable_debug_privilege()
    lowered = 0
    single = False
    for pid, _name in procs:
        state, mask = _read_state(pid)
        if state == "low":
            lowered += 1
        if mask and bin(mask).count("1") == 1:
            single = True
    return len(procs), lowered, single
