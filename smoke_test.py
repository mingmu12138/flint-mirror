"""功能自检脚本（不影响桌面，用 offscreen 平台跑）。

用法：.venv\\Scripts\\python.exe smoke_test.py
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent))

from PySide6 import QtWidgets

app = QtWidgets.QApplication([])

from core.store import Config, Mod, ProcessGuard, KIND_EXE, KIND_HTML  # noqa: E402
from core import display  # noqa: E402
import gui  # noqa: E402

ok_all = True


def check(name: str, cond: bool, detail: str = "") -> None:
    global ok_all
    mark = "PASS" if cond else "FAIL"
    if not cond:
        ok_all = False
    print(f"[{mark}] {name} {detail}")


# 1. 配置读写
cfg = Config()
check("配置加载", len(cfg.mods) >= 1, f"模组数={len(cfg.mods)}")
check("原生分辨率记录", cfg.has_native(), f"native={cfg.native}")
check("目标分辨率", cfg.target[0] > 0, f"target={cfg.target}")

# 2. 进程托管（用 pythonw 起个假进程，不弹窗）
guard = ProcessGuard()
runner = Path(sys.executable).with_name("pythonw.exe")
if runner.exists():
    fake = Mod(id="__test__", name="假进程", path=str(runner), args=["-c", "import time; time.sleep(60)"])
    ok, msg = guard.launch(fake)
    check("模组启动", ok, msg)
    time.sleep(0.8)
    check("运行状态检测", guard.is_running(fake))
    ok2, msg2 = guard.stop(fake)
    check("模组停止", ok2 and not guard.is_running(fake), msg2)

# 3. 网页类模组不托管进程
html_mod = Mod(id="__html__", name="假网页", path="https://example.com", kind="html")
check("网页模组不视为进程", guard.is_running(html_mod) == False)

# 4. 路径判断
check("html 类型识别", Mod.from_dict({"path": "a.html"}).kind == KIND_HTML)
check("exe 类型识别", Mod.from_dict({"path": "a.exe"}).kind == KIND_EXE)

# 5. 界面与托盘
win = gui.MainWindow(cfg, guard, guard)
check("主窗口创建", win.width() > 0, f"{win.width()}x{win.height()}")
check("模组卡片数量", len(win.cards) == len(cfg.mods), f"{len(win.cards)}/{len(cfg.mods)}")

tray = gui.AppTray(win, guard, cfg)
tray.rebuild()
check("托盘菜单构建", len(tray.menu.actions()) >= 3, f"顶级项={len(tray.menu.actions())}")

# 6. 添加模组对话框
dlg = gui.AddModDialog(win)
dlg.path_edit.setText(str(Path(__file__).resolve()))
dlg.name_edit.setText("测试模组")
dlg._accept()
check("添加对话框校验", dlg.result_path != "", dlg.result_path)

# 7. 分辨率枚举
modes = display.mode_43()
check("4:3 模式枚举", len(modes) > 0, f"{len(modes)} 个")

win.close()
print()
print("全部通过" if ok_all else "存在失败项")
sys.exit(0 if ok_all else 1)
