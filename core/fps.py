# -*- coding: utf-8 -*-
"""帧率采集：跟着前台窗口跑 PresentMon，读它写出的 CSV 算 FPS。

为什么用 PresentMon：Windows 没有公开的 FPS 接口，只有 DXGI 的 present 事件
（ETW）能算出真实帧间隔。PresentMon 就是干这个的，Intel 开源，单个 exe 不到 1MB。

两条踩过的坑，都在这里兜住了：
1. ETW 会话名必须固定且独立。机器上常驻几十个 ETW 会话（管家 / 加速器 / 驱动面板），
   用默认的 "PresentMon" 名字会跟别人撞车，撞上就一条数据都收不到。
2. 列位置不能写死。PresentMon 2.x 的 CSV 列顺序跟着选项变，这里按表头找
   msBetweenPresents，找不着才退回老位置。
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from PySide6 import QtCore

from .store import app_dir

CREATE_NO_WINDOW = 0x08000000
WINDOW_SECONDS = 1.2
SESSION_NAME = "FlintMirrorFps"
BUFFER_SIZE = "65536"
# 起动多久还一条数据都没有，就认定读不到，给个说法
NO_DATA_SECONDS = 8.0
FALLBACK_COL = 9
# 这些前台进程没有 DXGI 呈现，盯着它们只会一直是 0
SKIP_PROCESSES = {
    "explorer.exe", "燧镜.exe", "searchhost.exe", "textinputhost.exe",
    "startmenuexperiencehost.exe", "shellexperiencehost.exe",
}


def presentmon_path() -> Optional[Path]:
    for cand in (
        app_dir() / "bundled" / "presentmon" / "PresentMon.exe",
        app_dir() / "PresentMon.exe",
    ):
        if cand.exists():
            return cand
    return None


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _dword(key_path: str, name: str) -> Optional[int]:
    """读 HKLM 下的一个 DWORD；值不存在返回 None。"""
    try:
        import winreg
    except ImportError:
        return None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key_path) as key:
            try:
                return int(winreg.QueryValueEx(key, name)[0])
            except FileNotFoundError:
                return None
    except OSError:
        return None


def mpo_enabled() -> bool:
    """MPO（多平面叠加）是不是开着。

    开着的时候，游戏画面由显卡直接合成扫描输出，绕过了 DWM 的呈现路径，
    靠监听"呈现事件"来数帧的工具（PresentMon、Xbox Game Bar、RTSS 全都一样）
    一个数都收不到。注册表里 OverlayTestMode = 5 表示已禁用。
    """
    return _dword(r"SOFTWARE\Microsoft\Windows\Dwm", "OverlayTestMode") != 5


def hags_enabled() -> bool:
    """硬件加速 GPU 计划（HAGS）开着吗（HwSchMode = 2 表示开启）。"""
    return _dword(r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode") == 2


def explain() -> str:
    """给设置页那个问号用：说清楚为什么读不到，以及按什么顺序排查。"""
    admin_ok = is_admin()
    mpo = mpo_enabled()
    hags = hags_enabled()

    lines = [
        "【本机自检】",
        f"· 管理员权限：{'有' if admin_ok else '没有'}",
        f"· MPO 多平面叠加：{'开着' if mpo else '已关闭'}",
        f"· 硬件加速 GPU 计划：{'开启' if hags else '关闭'}",
        "",
        "【为什么读不到帧】",
        "帧率没法直接问游戏，只能监听「显卡把画面送到屏幕」的那个呈现事件。",
        "如果这个事件被系统或别的软件截走了，就一个数都拿不到。",
        "",
        "【按这个顺序排查】",
        "1. MPO（多平面叠加）",
        "   开着的时候游戏画面由显卡直接合成输出，绕过系统的呈现路径，",
        "   所有「不往游戏里注入代码」的采集方式都收不到帧，",
        "   Windows 自带的 Xbox Game Bar 也一样收不到。这是最常见的原因。",
        "   关掉：注册表 HKLM\\SOFTWARE\\Microsoft\\Windows\\Dwm 下新建 DWORD",
        "   OverlayTestMode = 5，然后重启电脑。想还原就删掉这个值再重启。",
        "2. 管理员权限",
        "   呈现事件在内核层，普通权限只能收到残缺的事件流。",
        "   右键燧镜 → 以管理员身份运行。",
        "3. 占着事件通道的软件",
        "   电脑管家、游戏加速器、录屏工具会占住系统的跟踪会话，退出一个再试。",
        "4. 前台窗口不是游戏",
        "   燧镜跟着最前面的窗口走，人在桌面上时一定是 --。",
        "",
        "【这不是软件坏了】",
        "同一份程序在别的机器上能正常显示帧率。是这台机器的环境把事件通道挡住了，",
        "上面四条做完基本就恢复。",
    ]
    return "\n".join(lines)


def foreground_pid() -> int:
    """当前前台窗口所属进程 pid。"""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return 0
        pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def process_name(pid: int) -> str:
    try:
        import ctypes.wintypes as wt

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return ""
        buf = ctypes.create_unicode_buffer(260)
        size = wt.DWORD(260)
        ok = kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        kernel32.CloseHandle(handle)
        return Path(buf.value).name if ok else ""
    except Exception:
        return ""


class FpsMonitor(QtCore.QObject):
    """每秒推一次 fps（0 表示当前没数据）。"""

    changed = QtCore.Signal(float)
    # 读不到帧 / 读回来了，各发一次：设置页那个问号靠它显隐
    hint = QtCore.Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._proc: Optional[subprocess.Popen] = None
        self._proc_name = ""
        self._proc_pid = 0
        self._csv: Optional[Path] = None
        self._offset = 0
        self._cols: Optional[int] = None
        self._samples: List[tuple] = []
        self._poll = QtCore.QTimer(self)
        self._poll.timeout.connect(self._tick)
        self.current = 0.0
        self.error_text = ""
        self._started_at = 0.0
        self._got_any = False
        self._warned = False

    # ------------------------------------------------------------ 控制
    def available(self) -> bool:
        return presentmon_path() is not None

    def start(self) -> bool:
        if not self.available():
            self.error_text = "缺少 PresentMon.exe"
            return False
        self.error_text = ""
        self._got_any = False
        self._warned = False
        self._started_at = time.time()
        self._poll.start(1000)
        self._tick()
        return True

    def stop(self) -> None:
        self._poll.stop()
        self._kill()
        self._proc_name = ""
        self._proc_pid = 0
        self.current = 0.0

    def follow(self, pid: int) -> None:
        """手动指定盯哪个进程（不传就自动跟前台）。"""
        if pid and pid != self._proc_pid:
            self._proc_pid = pid
            self._restart(process_name(pid), pid)

    # ------------------------------------------------------------ 内部
    def _tick(self) -> None:
        pid = foreground_pid()
        name = process_name(pid) if pid else ""
        if not pid or name.lower() in SKIP_PROCESSES:
            self.current = 0.0
            self.changed.emit(0.0)
            return
        proc = self._proc
        if (name != self._proc_name or pid != self._proc_pid
                or proc is None or proc.poll() is not None):
            self._restart(name, pid)

        self._read_new_rows()

        now = time.time()
        self._samples = [(t, ms) for t, ms in self._samples if now - t <= WINDOW_SECONDS]
        vals = [ms for _t, ms in self._samples if 0 < ms < 1000]
        if vals:
            avg = sum(vals) / len(vals)
            fps = 1000.0 / avg if avg > 0 else 0.0
        else:
            fps = 0.0

        if not self._got_any and now - self._started_at > NO_DATA_SECONDS:
            if not self._warned:
                self._warned = True
                self.error_text = self._diagnose()
                self.hint.emit(self.error_text)
        elif fps > 0 and (self.error_text or self._warned):
            # 有数了：把提示收回去，问号跟着消失
            self.error_text = ""
            self._warned = False
            self.hint.emit("")
        self.current = fps
        self.changed.emit(fps)

    def _diagnose(self) -> str:
        """一条数据都没有时，给出最可能的原因（越具体越好）。"""
        if not is_admin():
            return (
                "读不到帧：多半是权限不够——呈现事件在内核层，普通权限只能收到残缺的事件流"
                "（右键帧率窗可一键以管理员重启）"
            )
        if mpo_enabled():
            return (
                "读不到帧：系统开着 MPO（多平面叠加），游戏画面绕过了系统的呈现路径，"
                "采集工具收不到任何帧。设置 → 显示 →「帧率悬浮窗」旁边的问号里有具体做法"
            )
        return (
            "读不到帧：事件通道被别的软件占着，可能有监控 / 录屏 / 安全软件占住了跟踪会话，"
            "也可能当前最前面的窗口不是游戏"
        )

    def _read_new_rows(self) -> None:
        csv = self._csv
        if csv is None or not csv.exists():
            return
        try:
            with csv.open("r", encoding="utf-8", errors="ignore") as f:
                f.seek(self._offset)
                text = f.read()
                self._offset = f.tell()
        except OSError:
            return
        if not text:
            return
        for line in text.splitlines():
            line = line.lstrip("\ufeff").strip()
            if not line:
                continue
            if self._cols is None and ("msBetweenPresents" in line or line.startswith("Application")):
                header = [c.strip() for c in line.split(",")]
                if "msBetweenPresents" in header:
                    self._cols = header.index("msBetweenPresents")
                continue          # 表头本身不是数据
            parts = line.split(",")
            col = self._cols if self._cols is not None else FALLBACK_COL
            if len(parts) <= col:
                continue
            try:
                ms = float(parts[col])
            except ValueError:
                continue
            self._samples.append((time.time(), ms))
            self._got_any = True
        if len(self._samples) > 2000:
            del self._samples[: len(self._samples) - 2000]

    def _restart(self, name: str, pid: int) -> None:
        self._kill()
        self._proc_name = name
        self._proc_pid = pid
        self._cols = None
        self._samples = []
        self._offset = 0
        if not self._got_any:
            self._started_at = time.time()

        exe = presentmon_path()
        if exe is None:
            return
        if not name and pid <= 0:
            return

        csv = Path(tempfile.gettempdir()) / f"flint_fps_{os.getpid()}_{int(time.time() * 1000)}.csv"
        try:
            csv.unlink()
        except OSError:
            pass
        self._csv = csv

        args = [
            str(exe),
            "--session_name", SESSION_NAME,
            "--stop_existing_session",
            "--output_file", str(csv),
            "--no_console_stats",
            "--set_circular_buffer_size", BUFFER_SIZE,
            # 刻意不加 --terminate_on_proc_exit：
            # 它的语义是"目标全退出就自杀"，切窗口 / 读图 / 游戏短暂消失都会触发，
            # 我们一看进程没了又重启，结果每秒重建一次跟踪会话，事件全挤丢。
        ]
        if name:
            args += ["--process_name", name]
        else:
            args += ["--process_id", str(pid)]
        try:
            self._proc = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as exc:  # noqa: BLE001
            self.error_text = f"启动 PresentMon 失败：{exc}"
            self._proc = None

    def _kill(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        if self._csv is not None:
            try:
                self._csv.unlink()
            except OSError:
                pass
            self._csv = None
