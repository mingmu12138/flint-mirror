"""托盘图标常驻任务栏。

Windows 11 会把每个托盘图标的「隐藏/显示」记在
HKCU\\Control Panel\\NotifyIconSettings 里；重装、换路径或者系统抽风时，
本程序的条目常被写成 IsPromoted=0，图标就掉进溢出区。
这里在启动后把自己那条改回 1，只碰 ExecutablePath 与本程序完全一致的条目，失败静默。
"""

from __future__ import annotations

import logging
import os
import sys

log = logging.getLogger(__name__)

_KEY = r"Control Panel\NotifyIconSettings"


def promote(exe: str | None = None) -> int:
    """把本程序所有托盘条目设为常驻显示，返回改动条数。"""
    try:
        import winreg
    except Exception:  # noqa: BLE001
        return 0

    path = (exe or sys.executable or "").strip()
    if not path:
        return 0

    try:
        root = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY, 0, winreg.KEY_READ)
    except OSError:
        return 0

    changed = 0
    with root:
        i = 0
        while True:
            try:
                name = winreg.EnumKey(root, i)
            except OSError:
                break
            i += 1
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _KEY + "\\" + name) as sk:
                    exe_v, _ = winreg.QueryValueEx(sk, "ExecutablePath")
                    try:
                        promoted, _ = winreg.QueryValueEx(sk, "IsPromoted")
                    except OSError:
                        promoted = 0
            except OSError:
                continue

            if os.path.normcase(str(exe_v)) != os.path.normcase(path):
                continue
            if promoted == 1:
                continue
            try:
                with winreg.OpenKey(
                    winreg.HKEY_CURRENT_USER, _KEY + "\\" + name, 0, winreg.KEY_SET_VALUE
                ) as wk:
                    winreg.SetValueEx(wk, "IsPromoted", 0, winreg.REG_DWORD, 1)
                changed += 1
            except OSError:
                continue

    if changed:
        log.info("托盘：已把 %d 条图标条目设为常驻显示", changed)
    return changed
