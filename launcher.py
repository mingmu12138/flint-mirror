"""燧镜 —— 轻量入口。

这个文件被设计成**不加载 Qt**：双击程序图标时，
  - 如果后台已经有实例在跑 → 投递一个"切换分辨率"命令，立刻退出（0.1~0.3 秒）
  - 如果没有实例 → 才去加载界面（首次配置 / 手动打开面板）

命令行：
  燧镜.exe                 切换 4:3 ⇄ 原生（有实例时秒切；没实例时打开界面）
  燧镜.exe --show          打开控制面板
  燧镜.exe --toggle        本地切换一次后退出（不依赖后台实例）
  燧镜.exe --restore       恢复原生分辨率后退出（救援用，界面挂了也能救）
  燧镜.exe --panic         全部还原（分辨率/ACE/帧率灯/回放/悬浮窗），有实例时交给它做
  燧镜.exe --shot FILE     启动界面并截图后退出（自检用）
  燧镜.exe --main          强制以主实例身份启动界面
  燧镜.exe --tray          静默进托盘（开机自启用，不弹面板）
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_system32() -> None:
    """把 System32 塞进 PATH。

    Python 3.13 起 ctypes.util.find_library 靠 PATH 搜系统 DLL，打包成 exe
    后如果 PATH 里没有 System32，soundcard 加载 ole32 会直接失败、界面起不来。
    """
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    sys32 = os.path.join(root, "System32")
    parts = [p for p in os.environ.get("PATH", "").split(";") if p]
    if not any(p.lower().rstrip("\\") == sys32.lower() for p in parts):
        os.environ["PATH"] = sys32 + ";" + os.environ.get("PATH", "")


_ensure_system32()


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE = base_dir()
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))


def local_command(mode: str) -> int:
    """不加载界面，直接改分辨率。"""
    from core import display
    from core.store import Config

    cfg = Config()
    cur = display.get_current()
    if not cfg.has_native() and cur[0] > 0:
        cfg.set_native(cur[0], cur[1], display.get_native()[2])

    if mode == "restore" or (cur and cur == tuple(cfg.target)):
        nw, nh, _ = cfg.native
        ok, _code, msg = display.set_resolution(nw, nh)
        print(f"恢复 {nw}x{nh}: {'成功' if ok else msg}")
    else:
        tw, th = cfg.target
        ok, _code, msg = display.set_resolution(tw, th)
        print(f"切换 {tw}x{th}: {'成功' if ok else msg}")
    return 0 if ok else 1


def run_gui(show_panel: bool = True) -> int:
    from gui import run

    return run(show_panel)


def main() -> int:
    args = sys.argv[1:]

    # 0) 先把崩溃捕获挂上：无控制台时，异常只能靠日志看到
    try:
        from core import diag

        diag.install_excepthook()
    except Exception:
        pass

    # 0.5) 全部还原：有后台实例就让它做完整的，没有就只把分辨率救回来
    if "--panic" in args:
        from core import ipc

        if ipc.instance_running():
            try:
                if ipc.send_command("panic"):
                    return 0
            except Exception:  # noqa: BLE001
                pass
        return local_command("restore")

    # 1) 救援 / 命令行切换：完全不碰界面
    if "--restore" in args or "--toggle" in args:
        return local_command("restore" if "--restore" in args else "toggle")

    # 2) 自检截图 / 强制主实例：直接进界面
    if ("--shot" in args or "--shot-settings" in args or "--main" in args
            or "--rec-check" in args or "--replay-check" in args or "--audio-check" in args):
        return run_gui()

    # 3) 开机自启：静默进托盘，不弹面板
    if "--tray" in args:
        return run_gui(False)

    # 4) 默认：双击 = 打开面板（不再直接切分辨率，避免误触）
    from core import ipc

    if ipc.instance_running():
        if ipc.send_command("show"):
            return 0

    # 没有实例（或命令投递失败）：启动界面
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
