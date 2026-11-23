# -*- coding: utf-8 -*-
"""启动项管理。

做法和任务管理器里「禁用启动项」完全同一套机制：不动 Run 键里的值、
也不删启动文件夹里的文件，只在 StartupApproved 下打一个标记位。
所以随时能切回来，卸载本软件也不会留下"被删掉的启动项"。
"""
from __future__ import annotations

import os
import struct
import time
import winreg

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
FOLDER_USER = os.path.join(
    os.environ.get("APPDATA", r""), r"Microsoft\Windows\Start Menu\Programs\Startup"
)
FOLDER_MACHINE = os.path.join(
    os.environ.get("ProgramData", r""), r"Microsoft\Windows\Start Menu\Programs\StartUp"
)

# 任务管理器同一套标记位：首字节 02 = 启用，03 = 禁用
AP_RUN = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"
AP_RUN32 = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run32"
AP_FOLDER = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\StartupFolder"

FLAG_ON = b"\x02\x00\x00\x00" + b"\x00" * 8
FLAG_OFF_HEAD = b"\x03\x00\x00\x00"


def _now_ft() -> int:
    """Windows FILETIME（1601 起的 100ns 计数），任务管理器禁用时也带这个时间。"""
    return int((time.time() + 11644473600) * 10_000_000)


def _flag(on: bool) -> bytes:
    if on:
        return FLAG_ON
    return FLAG_OFF_HEAD + struct.pack("<Q", _now_ft())


def _read_flags(path: str, hkey=winreg.HKEY_CURRENT_USER) -> dict:
    """读某个 StartupApproved 分支下所有条目的启用状态。"""
    out = {}
    try:
        key = winreg.OpenKey(hkey, path, 0, winreg.KEY_READ)
    except OSError:
        return out
    with key:
        i = 0
        while True:
            try:
                name, val, _t = winreg.EnumValue(key, i)
            except OSError:
                break
            i += 1
            # 首字节 03 开头就是被禁用；其他（02 / 06）都按启用算
            disabled = bool(val) and val[0] == 3
            out[name.lower()] = not disabled
    return out


def _exe_of(cmd: str) -> str:
    """从命令行里抠出可执行文件名，用来在主界面上一眼认出是谁。"""
    text = (cmd or "").strip()
    if not text:
        return ""
    if text.startswith('"'):
        end = text.find('"', 1)
        return os.path.basename(text[1:end] if end > 0 else text[1:])
    low = text.lower()
    idx = low.find(".exe")
    if idx != -1:
        # C:\Program Files\... 这种带空格的路径，按反斜杠切最后一段才准
        return os.path.basename(text[: idx + 4].strip())
    return os.path.basename(text.split(" ")[0])


def list_entries() -> list[dict]:
    """返回全部启动项。machine=True 的打头是系统级，改动要管理员权限。"""
    items: list[dict] = []

    # 一、注册表 Run
    for hkey, scope, machine, ap in (
        (winreg.HKEY_CURRENT_USER, "当前用户", False, AP_RUN),
        (winreg.HKEY_LOCAL_MACHINE, "所有用户", True, AP_RUN32),
    ):
        flags = _read_flags(ap, hkey)
        try:
            key = winreg.OpenKey(hkey, RUN_KEY, 0, winreg.KEY_READ)
        except OSError:
            continue
        with key:
            i = 0
            while True:
                try:
                    name, val, _t = winreg.EnumValue(key, i)
                except OSError:
                    break
                i += 1
                if not name or name.startswith("__"):  # __PSFX 之类系统内部标记
                    continue
                items.append(
                    {
                        "name": name,
                        "cmd": str(val or ""),
                        "exe": _exe_of(str(val or "")),
                        "kind": "run",
                        "scope": scope,
                        "machine": machine,
                        "enabled": flags.get(name.lower(), True),
                    }
                )

    # 二、启动文件夹里的快捷方式
    fflags = _read_flags(AP_FOLDER)
    for folder, scope, machine, use_flags in (
        (FOLDER_USER, "当前用户", False, True),
        (FOLDER_MACHINE, "所有用户", True, False),
    ):
        if not folder or not os.path.isdir(folder):
            continue
        try:
            names = os.listdir(folder)
        except OSError:
            continue
        for fn in names:
            if fn.lower() == "desktop.ini" or not fn.lower().endswith(".lnk"):
                continue
            items.append(
                {
                    "name": os.path.splitext(fn)[0],
                    "cmd": os.path.join(folder, fn),
                    "exe": fn,
                    "kind": "folder",
                    "scope": scope,
                    "machine": machine,
                    "enabled": fflags.get(fn.lower(), True) if use_flags else True,
                }
            )

    items.sort(key=lambda x: (x["machine"], not x["enabled"], x["name"].lower()))
    return items


def set_enabled(item: dict, on: bool) -> tuple[bool, str]:
    """开 / 关一个启动项。只写标记位，原值原文件都不动。"""
    path = AP_RUN if item["kind"] == "run" else AP_FOLDER
    hkey = winreg.HKEY_LOCAL_MACHINE if item.get("machine") else winreg.HKEY_CURRENT_USER
    if item.get("machine"):
        path = AP_RUN32 if item["kind"] == "run" else AP_FOLDER
    name = item["name"] if item["kind"] == "run" else os.path.basename(str(item["cmd"]))
    try:
        key = winreg.CreateKeyEx(hkey, path, 0, winreg.KEY_SET_VALUE)
    except PermissionError:
        return False, "系统级启动项要管理员权限，用任务管理器改更稳"
    except OSError as exc:
        return False, "写不进去：" + str(exc)
    with key:
        try:
            winreg.SetValueEx(key, name, 0, winreg.REG_BINARY, _flag(on))
        except PermissionError:
            return False, "系统级启动项要管理员权限，用任务管理器改更稳"
        except OSError as exc:
            return False, "写不进去：" + str(exc)
    return True, ("已启用 " + item["name"]) if on else ("已禁用 " + item["name"])


def summary() -> tuple[int, int]:
    """(启用数, 总数)，给主界面那一行用。"""
    items = list_entries()
    return sum(1 for i in items if i["enabled"]), len(items)
