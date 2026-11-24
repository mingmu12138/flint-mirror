"""燧镜 —— 界面层（Qt）。

由 launcher.py 在确实需要显示界面时才导入，保证"双击打开面板 / 秒切"走的是
不加载 Qt 的快速路径（0.1~0.3 秒完成）。
"""

from __future__ import annotations

import ctypes
import logging
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import weakref
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QTimer, Signal

from core import (ace, artwork, audioout, automation, cacheclean, crosshair, capture, epicfree, music,
                    musicapi, qqmusic, kugou, kuwo,
                    daily_hud, df_intel, display, fps,
                    clipboard_lan, fps_hud, ipc, netspeed, power, recorder, replay, scaling, spec,
                    startup, steamaccount, steamlib, steamnames, store, sysmon, theme,
                    traypin, wupdate, musicbar, screenfilter, filterwin, scrcpy_tool)
from core import player as mplayer
from core.hotkey import (
    MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, VK, HotkeyManager,
    format_hotkey, key_name, parse_hotkey,
)
from core.flow import FlowLayout, FlowPage
from core.icon import app_icon


def _asset_file(name: str) -> Path:
    """找一个随包资源：打包目录(_MEIPASS) → exe 同目录 → 源码目录，逐个试。

    打包成 exe 后 datas 落在 _internal\assets，exe 同目录那份不一定有，
    所以不能只按 app_dir() 拼路径，否则换台机器就"看不到图"。
    """
    meipass = getattr(sys, "_MEIPASS", None)
    cands = []
    if meipass:
        cands.append(Path(meipass) / "assets" / name)
    cands.append(app_dir() / "assets" / name)
    cands.append(Path(__file__).resolve().parent / "assets" / name)
    for p in cands:
        try:
            if p.exists() and p.stat().st_size > 512:
                return p
        except OSError:
            continue
    return cands[-1]
from core.store import (
    ACTION_ACE_LIMIT,
    ACTION_ACE_RESTORE,
    ACTION_CACHE_CLEAN,
    ACTION_FPS_HIDE,
    ACTION_FPS_SHOW,
    ACTION_HUD_HIDE,
    ACTION_HUD_SHOW,
    ACTION_LABEL,
    ACTION_MOD_START,
    ACTION_MOD_STOP,
    ACTION_RECORD_START,
    ACTION_RECORD_STOP,
    ACTION_REPLAY_SAVE,
    ACTION_REPLAY_START,
    ACTION_REPLAY_STOP,
    ACTION_RESOLUTION,
    ACTION_RESTORE,
    ACTION_SHOT,
    ACTION_WAIT,
    Action,
    Config,
    DEFAULT_HOTKEYS,
    HOTKEY_ACTIONS,
    HOTKEY_LABEL,
    KIND_EXE,
    KIND_HTML,
    KIND_PAGE,
    KIND_REMOTE,
    KIND_URL,
    Mod,
    ProcessGuard,
    Rule,
    TRIGGER_LABEL,
    TRIGGER_MANUAL,
    TRIGGER_START,
    TRIGGER_STOP,
    app_dir,
)

APP_NAME = "燧镜"
APP_NAME_EN = "FLINT MIRROR"
APP_VERSION = "v1.10.3"
APP_AUTHOR = "布鲁托是小馋猫"

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
LOG_DIR = app_dir() / "logs"

LOG_DIR.mkdir(parents=True, exist_ok=True)
from core import diag  # noqa: E402

diag.ensure_handler()
log = logging.getLogger("gamehub")


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------
def _emit_mod_event(name: str, **kw) -> None:
    """把宿主事件广播给模组（没装模组、没人订阅时是空操作）。"""
    try:
        from core.mod_api import EVENTS

        EVENTS.emit(name, **kw)
    except Exception:  # noqa: BLE001
        log.debug("广播事件 %s 失败", name, exc_info=True)


def is_headset(name: str) -> bool:
    low = (name or "").lower()
    return any(k in low for k in ("耳机", "headset", "headphone", "earbud", "airpods"))


def audio_icon_pixmap(name: str = "", size: int = 22, warn: bool = False) -> QtGui.QIcon:
    """画喇叭 / 耳机小图标（不依赖外部素材，随设置变形状）。"""
    px = QtGui.QPixmap(size, size)
    px.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(px)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    color = QtGui.QColor("#ff8a6b") if warn else QtGui.QColor("#23e2c8")
    p.setPen(QtGui.QPen(color, max(1.6, size / 10.0)))
    p.setBrush(QtGui.QColor(0, 0, 0, 0))

    s = size / 22.0
    if is_headset(name):
        p.drawArc(QtCore.QRectF(3 * s, 4 * s, 16 * s, 15 * s), 0 * 16, 180 * 16)
        p.setBrush(color)
        p.drawRoundedRect(QtCore.QRectF(2 * s, 11 * s, 4.4 * s, 8 * s), 1.6 * s, 1.6 * s)
        p.drawRoundedRect(QtCore.QRectF(15.6 * s, 11 * s, 4.4 * s, 8 * s), 1.6 * s, 1.6 * s)
    else:
        poly = QtGui.QPolygonF([
            QtCore.QPointF(3 * s, 8 * s),
            QtCore.QPointF(7 * s, 8 * s),
            QtCore.QPointF(12 * s, 4 * s),
            QtCore.QPointF(12 * s, 18 * s),
            QtCore.QPointF(7 * s, 14 * s),
            QtCore.QPointF(3 * s, 14 * s),
        ])
        p.setBrush(color)
        p.drawPolygon(poly)
        p.setBrush(QtGui.QColor(0, 0, 0, 0))
        p.drawArc(QtCore.QRectF(11 * s, 6 * s, 6 * s, 10 * s), -70 * 16, 140 * 16)
        p.drawArc(QtCore.QRectF(13 * s, 3 * s, 8 * s, 16 * s), -70 * 16, 140 * 16)
    p.end()
    return QtGui.QIcon(px)


def audio_switch_icon(name: str = "", size: int = 24) -> QtGui.QIcon:
    """两段小图标合成一个：左边是当前输出设备，右边上下箭头表示「点一下换一路」。"""
    px = QtGui.QPixmap(size, size)
    px.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(px)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)

    dev = audio_icon_pixmap(name, 16).pixmap(16, 16)
    p.drawPixmap(QtCore.QRectF(0, (size - 16) / 2.0, 16, 16), dev, QtCore.QRectF(0, 0, 16, 16))

    color = QtGui.QColor("#23e2c8")
    p.setPen(QtGui.QPen(color, 1.4))
    x0, x1 = size * 0.72, size * 0.97
    cx = (x0 + x1) / 2.0
    top, bot = size * 0.16, size * 0.84
    p.drawLine(QtCore.QPointF(cx, top + size * 0.14), QtCore.QPointF(cx, bot - size * 0.14))
    p.setBrush(color)
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(x0, top + size * 0.18),
        QtCore.QPointF(x1, top + size * 0.18),
        QtCore.QPointF(cx, top),
    ]))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(x0, bot - size * 0.18),
        QtCore.QPointF(x1, bot - size * 0.18),
        QtCore.QPointF(cx, bot),
    ]))
    p.end()
    return QtGui.QIcon(px)


def list_drives() -> list:
    """列出这台机器上有空间的磁盘（用于选择缓存盘）。"""
    out = []
    for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
        root = Path(f"{letter}:\\")
        if not root.exists():
            continue
        try:
            free = shutil.disk_usage(root).free
        except OSError:
            continue
        out.append((f"{letter}:", free))
    return out


def ratio_text(w: int, h: int) -> str:
    if not h:
        return "?"
    g = math.gcd(w, h)
    rw, rh = w // g, h // g
    if rw <= 24 and rh <= 24:
        return f"{rw}:{rh}"
    return f"{w / h:.2f}:1"


def set_dark_title_bar(widget: QtWidgets.QWidget) -> None:
    """让 Windows 标题栏跟随暗色主题。"""
    try:
        hwnd = int(widget.winId())
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), 20, ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass


def autostart_enabled() -> bool:
    import winreg

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
        )
        winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return True
    except OSError:
        return False


def _autostart_cmd() -> str:
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --tray'
    return f'"{sys.executable}" "{app_dir() / "launcher.py"}" --tray'


def ensure_autostart() -> str:
    """开机自启项指向的程序换了地方（搬文件夹 / 换安装目录）就就地改过来。

    以前只在勾选那一刻写一次路径，之后程序被挪走，注册表里还留着老地址，
    开机自然起不来。这里每次启动对一遍，顺手把被系统禁用的标记解开。
    """
    import winreg

    key_path = r"Software\\Microsoft\\Windows\\CurrentVersion\\Run"
    want = _autostart_cmd()
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
    except OSError:
        return "none"
    fixed = False
    try:
        try:
            cur, _t = winreg.QueryValueEx(key, APP_NAME)
        except OSError:
            return "none"
        if str(cur).strip().lower() != want.strip().lower():
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, want)
            fixed = True
    finally:
        winreg.CloseKey(key)

    cleared = False
    sk = None
    try:
        sk = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\StartupApproved\\Run",
            0,
            winreg.KEY_ALL_ACCESS,
        )
    except OSError:
        sk = None
    if sk is not None:
        try:
            data, _t = winreg.QueryValueEx(sk, APP_NAME)
            if data and data[0] == 3:   # 03 = 被「启动项」里手动禁用
                winreg.SetValueEx(sk, APP_NAME, 0, winreg.REG_BINARY,
                                  bytes([2, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]))
                cleared = True
        except OSError:
            pass
        finally:
            winreg.CloseKey(sk)
    if fixed:
        return "fixed"
    if cleared:
        return "enabled"
    return "ok"


def set_autostart(enable: bool) -> None:
    import winreg

    key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_ALL_ACCESS)
    except OSError:
        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
    try:
        if enable:
            if getattr(sys, "frozen", False):
                cmd = f'"{sys.executable}" --tray'
            else:
                cmd = f'"{sys.executable}" "{app_dir() / "launcher.py"}" --tray'
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except OSError:
                pass
    finally:
        winreg.CloseKey(key)


# ---------------------------------------------------------------------------
# 样式
# ---------------------------------------------------------------------------
QSS_TEMPLATE = """
* {
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI";
    font-size: 13px;
    color: @fg-1;
}
QWidget#Root { background: @bg-page; }
QFrame#StatCard { background: @bg-card; border: 1px solid @line-1; border-radius: @radius-lg; }
QFrame#StatCard:hover { border-color: @line-2; }
QLabel#StatValue { color: @fg-0; font-size: 18px; font-weight: 700; }
QLabel#StatValueWarn { color: @state-danger; font-size: 18px; font-weight: 700; }
QProgressBar#StatBar { border: none; background: @bg-raised; border-radius: 3px; }
QProgressBar#StatBar::chunk {
    border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 @accent-dim, stop:1 @accent);
}
QFrame#Card { background: @bg-card; border: 1px solid @line-1; border-radius: @radius-xl; }
QFrame#ToolTile { background: @bg-raised; border: 1px solid @line-1; border-radius: @radius-lg; }
QFrame#ToolTile:hover { background: @bg-hover; border-color: @accent-line; }
QFrame#VLine { background: @line-sep; }
QLabel#Title { font-size: 22px; font-weight: 700; color: @fg-title; letter-spacing: 0.6px; }
QLabel#Sub { color: @fg-3; font-size: 10.5px; letter-spacing: 1.4px; }
QLabel#Badge {
    color: @accent; background: @accent-bg; border: 1px solid @accent-line;
    border-radius: @radius-sm; padding: 2px 8px; font-size: 11px;
}
QLabel#BadgeDim {
    color: @fg-2; background: @bg-raised; border: 1px solid @line-1;
    border-radius: @radius-sm; padding: 2px 8px; font-size: 11px;
}
QPlainTextEdit#LogView {
    background: @bg-sunken; border: 1px solid @line-1; border-radius: @radius-md;
    color: @fg-1; font-family: "Consolas", "Cascadia Mono", "Courier New";
    font-size: 11.5px; padding: 8px; selection-background-color: @accent-line;
}
QLabel#Section { font-size: 14px; font-weight: 600; color: @fg-0; }
QLabel#ResValue { font-size: 21px; font-weight: 700; color: @accent; }
QLabel#Hint { color: @fg-2; font-size: 12.5px; }
QLabel#Small { color: @fg-2; font-size: 12px; }
QPushButton {
    background: @bg-button; border: 1px solid @line-1; border-radius: @radius-btn;
    padding: 7px 14px; color: @fg-1;
}
QPushButton:hover { background: @bg-hover; border-color: @line-2; }
QPushButton:pressed { background: @bg-raised; }
QPushButton:disabled { color: @fg-off; background: @bg-off; border-color: @line-1; }
QPushButton#Primary {
    background: @accent-strong; border: none; color: @on-accent;
    font-weight: 700; font-size: 14px; padding: 10px 22px; border-radius: @radius-btn;
}
QPushButton#Primary:hover { background: @accent-hover; }
QPushButton#Primary:pressed { background: @accent-press; }
QPushButton#Ghost { background: transparent; border: 1px solid @line-1; color: @fg-2; }
QPushButton#Ghost:hover { color: @accent; border-color: @accent; background: rgba(@accent-rgb, 0.07); }
QPushButton#Skin {
    background: @bg-raised; border: 1px solid @line-1;
    border-radius: @radius-sm; padding: 0px;
}
QPushButton#Skin:hover { border-color: @accent; background: @bg-hover; }
QPushButton#Skin:pressed { background: @bg-button; }
QPushButton#Seg {
    background: @bg-button; border: 1px solid @line-1; color: @fg-2;
    border-radius: @radius-btn; padding: 7px 12px; font-size: 12.5px;
}
QPushButton#Seg:hover { color: @fg-0; border-color: @accent-line; }
QPushButton#Seg:checked {
    background: rgba(@accent-rgb, 0.18); border-color: @accent;
    color: @fg-0; font-weight: 600;
}
QFrame#Divider { background: @line-1; border: none; }
QWidget#Page { background: transparent; }
QSlider::groove:horizontal {
    height: 4px; background: @bg-off2; border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: @accent; border-radius: 2px;
}
QSlider::add-page:horizontal {
    background: @bg-off2; border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 13px; height: 13px; margin: -5px 0;
    border-radius: 7px; background: @accent; border: none;
}
QSlider::handle:horizontal:hover {
    background: @state-ok; margin: -6px 0;
    width: 15px; height: 15px; border-radius: 8px;
}
QLabel#GmTag {
    background: #ff3f3f; color: #ffffff; border-radius: 3px;
    padding: 0px 5px; font-size: 9px; font-weight: 700;
}
QLabel#NativeHint {
    background: rgba(10, 12, 16, 0.55);
    color: @fg-2; border-radius: 9px; padding: 2px 9px;
}
QPushButton#WinBtn {
    background: transparent; border: 1px solid @line-1; color: @fg-2;
    border-radius: 14px; padding: 0px; font-size: 13px;
}
QPushButton#WinBtn:hover { color: @accent; border-color: @accent; background: @bg-hover; }
QPushButton#WinBtn:pressed { background: @bg-button; }
QPushButton#FpsWhy {
    background: rgba(255, 176, 32, 0.10); border: 1px solid @state-warn;
    color: @state-alert; border-radius: @radius-md;
    font-weight: 700; font-size: 12px; padding: 0px;
}
QPushButton#FpsWhy:hover {
    background: rgba(255, 176, 32, 0.24); border-color: @state-alert; color: #ffd489;
}
QPushButton#FpsWhy:pressed { background: rgba(255, 176, 32, 0.34); }
QPushButton#Native {
    background: rgba(@accent-rgb, 0.08); border: 1px solid @accent-line;
    color: @accent; font-weight: 600; font-size: 12.5px;
    padding: 8px 16px; border-radius: @radius-btn;
}
QPushButton#Native:hover { background: rgba(@accent-rgb, 0.14); border-color: @accent; }
QPushButton#Native:pressed { background: rgba(@accent-rgb, 0.22); }
QPushButton#Native:disabled {
    color: @fg-2; background: @bg-off; border-color: @line-1;
}
QPushButton#Mini { padding: 3px 9px; font-size: 11px; border-radius: @radius-sm; background: @bg-button; }
QPushButton#Mini:checked { border: 1px solid @accent-line; color: @accent; font-weight: 600; }
QPushButton#Mini:hover { background: @bg-hover; }
QPushButton#Danger { background: transparent; border: none; color: @fg-3; font-size: 16px; padding: 0 6px; }
QPushButton#Danger:hover { color: @state-danger; }
QComboBox {
    background: @bg-raised; border: 1px solid @line-1; border-radius: @radius-btn;
    padding: 7px 10px; min-width: 172px; color: @fg-1;
}
QComboBox:hover { border-color: @line-2; }
QComboBox::drop-down { border: none; width: 24px; }
QComboBox::down-arrow { image: none; }
QComboBox QAbstractItemView {
    background: @bg-raised; border: 1px solid @line-1; outline: none;
    selection-background-color: @accent-strong; selection-color: @on-accent;
}
QCheckBox { spacing: 6px; }
QCheckBox::indicator {
    width: 15px; height: 15px; border-radius: 5px;
    border: 1px solid @line-2; background: @bg-sunken;
}
QCheckBox::indicator:checked { background: @accent-strong; border-color: @accent-strong; }
QCheckBox::indicator:hover { border-color: @accent; }
QScrollArea { border: none; background: transparent; }
QScrollArea > QWidget { background: transparent; }
QScrollArea > QWidget > QWidget { background: transparent; }
QWidget#HomePage { background: transparent; }
QLabel#Empty {
    color: @fg-2; font-size: 12.5px; line-height: 20px;
    padding: 30px 16px; border: 1px dashed @line-1; border-radius: @radius-md;
    background: @bg-off2;
}
QScrollBar:vertical { background: transparent; width: 8px; margin: 2px; }
QScrollBar::handle:vertical { background: @line-sep; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: @line-2; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QFrame#ModCard { background: @bg-off; border: 1px solid @line-1; border-radius: @radius-md; }
QFrame#ModCard[off="true"] { background: @bg-off2; border-color: @line-1; }
QFrame#ModTile { background: @bg-off; border: 1px solid @line-1; border-radius: @radius-md; }
QFrame#ModTile[off="true"] { background: @bg-off2; border-color: @line-1; }
QFrame#ModTile[hover="true"] { border-color: @line-2; background: @bg-hover; }
QFrame#ModCard[glass="true"], QFrame#ModTile[glass="true"] {
  background: rgba(14, 18, 26, 0.52);
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-top-color: rgba(255, 255, 255, 0.28);
  border-radius: 18px; }
QFrame#ModCard[glass="true"][off="true"], QFrame#ModTile[glass="true"][off="true"] {
  background: rgba(11, 14, 20, 0.42);
  border-color: rgba(255, 255, 255, 0.09); }
QFrame#ModTile[glass="true"][hover="true"] {
  background: rgba(24, 31, 43, 0.66);
  border-color: rgba(255, 255, 255, 0.24); }
QFrame#ModCard[liquid="true"], QFrame#ModTile[liquid="true"] {
  background: rgba(17, 22, 32, 0.36);
  border: 1px solid rgba(255, 255, 255, 0.16);
  border-top-color: rgba(255, 255, 255, 0.40);
  border-radius: 22px; }
QFrame#ModCard[liquid="true"][off="true"], QFrame#ModTile[liquid="true"][off="true"] {
  background: rgba(13, 17, 24, 0.30);
  border-color: rgba(255, 255, 255, 0.10); }
QToolButton#Seg {
    background: @bg-raised; border: 1px solid @line-1; border-radius: @radius-sm;
    color: @fg-2; padding: 3px 10px; font-size: 11.5px;
}
QToolButton#Seg:hover { border-color: @line-2; color: @fg-1; }
QToolButton#Seg:checked { background: @accent-bg; border-color: @accent-line; color: @accent; }
QMenu { background: @bg-card; border: 1px solid @line-1; padding: 6px; }
QMenu::item { padding: 8px 30px 8px 14px; border-radius: @radius-sm; }
QMenu::item:selected { background: @bg-hover; color: @accent; }
QMenu::item:disabled { color: @fg-off; }
QMenu::separator { height: 1px; background: @line-sep; margin: 5px 8px; }
QToolTip { background: @bg-raised; color: @fg-1; border: 1px solid @line-1; padding: 5px; }
"""


_glass_on = False
_liquid_on = False
_NOISE_PM = None


def _system_blur(hwnd: int, alpha: int = 0xA0,
                 rgb: tuple = (14, 16, 21)) -> str:
    """让 Windows 给窗口做亚克力磨砂（背后内容真糊）。

    走的是 SetWindowCompositionAttribute 这条老接口，Win10 1803 到 Win11 都能用；
    不支持的机器上会直接返回 "none"，不抛异常。
    """
    import ctypes
    from ctypes import wintypes

    class ACCENT_POLICY(ctypes.Structure):
        _fields_ = [
            ("AccentState", ctypes.c_uint),
            ("AccentFlags", ctypes.c_uint),
            ("GradientColor", ctypes.c_uint),
            ("AnimationId", ctypes.c_uint),
        ]

    class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
        _fields_ = [
            ("Attribute", ctypes.c_uint),
            ("Data", ctypes.POINTER(ACCENT_POLICY)),
            ("SizeOfData", ctypes.c_uint),
        ]

    try:
        user32 = ctypes.windll.user32
        fn = user32.SetWindowCompositionAttribute
    except (AttributeError, OSError):
        return "none"

    data = ACCENT_POLICY()
    data.AccentState = 4  # ACCENT_ENABLE_ACRYLICBLURBEHIND
    data.AccentFlags = 2
    r, g, b = rgb
    # GradientColor 是 AABBGGRR，注意字节序和 rgb 反着来
    data.GradientColor = (alpha << 24) | (b << 16) | (g << 8) | r
    wdata = WINDOWCOMPOSITIONATTRIBDATA()
    wdata.Attribute = 19  # WCA_ACCENT_POLICY
    wdata.Data = ctypes.pointer(data)
    wdata.SizeOfData = ctypes.sizeof(data)
    try:
        fn.argtypes = [wintypes.HWND, ctypes.POINTER(WINDOWCOMPOSITIONATTRIBDATA)]
        if fn(wintypes.HWND(hwnd), ctypes.byref(wdata)):
            return "acrylic"
    except Exception:  # noqa: BLE001
        pass
    # 退一步：老的纯模糊（Win10 早期）
    try:
        data.AccentState = 3  # ACCENT_ENABLE_BLURBEHIND
        if fn(wintypes.HWND(hwnd), ctypes.byref(wdata)):
            return "blur"
    except Exception:  # noqa: BLE001
        pass
    return "none"


def _noise_pixmap(size: int = 180):
    """一张可平铺的细颗粒纹理，毛玻璃模式铺在窗口底上。"""
    global _NOISE_PM
    if _NOISE_PM is not None:
        return _NOISE_PM
    import random as _rnd

    img = QtGui.QImage(size, size, QtGui.QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    r = _rnd.Random(20261120)
    p = QtGui.QPainter(img)
    for _ in range(1500):
        p.setPen(QtGui.QColor(255, 255, 255, r.randint(8, 26)))
        p.drawPoint(r.randint(0, size - 1), r.randint(0, size - 1))
    for _ in range(700):
        p.setPen(QtGui.QColor(0, 0, 0, r.randint(8, 22)))
        p.drawPoint(r.randint(0, size - 1), r.randint(0, size - 1))
    p.end()
    _NOISE_PM = QtGui.QPixmap.fromImage(img)
    return _NOISE_PM


def qss() -> str:
    """当前皮肤的样式表。切皮肤时重新调用一次就行。"""
    return theme.render(QSS_TEMPLATE)


# 记下每个控件设过的原始样式：换皮肤时照着重放一遍，不用重启程序
_STYLE_LOG: list = []
_STYLE_HOOKED = False
_REPLAYING = False


def _install_style_hook() -> None:
    """让所有 setStyleSheet 都过一层翻译。

    老代码里写死的那些色值（#7b8494 这种）会自动翻成当前皮肤的值，
    所以 152 处内联样式不用一处一处手改。
    """
    global _STYLE_HOOKED
    if _STYLE_HOOKED:
        return
    _STYLE_HOOKED = True
    orig = QtWidgets.QWidget.setStyleSheet

    def hooked(widget, text):
        raw = text or ""
        if not _REPLAYING:
            try:
                _STYLE_LOG.append((weakref.ref(widget), raw))
                if len(_STYLE_LOG) > 4000:
                    del _STYLE_LOG[: len(_STYLE_LOG) - 4000]
            except Exception:  # noqa: BLE001
                pass
        orig(widget, theme.recolor(raw) if raw else raw)

    QtWidgets.QWidget.setStyleSheet = hooked


def apply_theme() -> None:
    """切皮肤后刷一遍界面：窗口换新样式表，内联的按记录重放。"""
    global _REPLAYING
    text = qss()
    if _glass_on:
        t = theme.current()
        r = int(float(t.value("radius-lg", "19"))) + 7
        text += (
            "\nQWidget#Root { background: " + t.value("bg-page", "#0e1015")
            + "; border-radius: " + str(r) + "px; }"
            # 透明边框的按钮压在模糊图上会发灰，给层淡底
            "\nQPushButton#Ghost { background: rgba(10, 12, 16, 0.58); color: "
            + t.value("fg-0", "#e8edf6") + "; }"
            "\nQPushButton#Danger { background: rgba(10, 12, 16, 0.32); border-radius: 6px; }"
            "\nQLabel#Note { background: rgba(10, 12, 16, 0.55);"
            " border: 1px solid rgba(255, 255, 255, 0.10);"
            " border-radius: 14px; padding: 8px 14px; }"
        )
    if _liquid_on:
        # 液态玻璃：卡片和控件都做成灰玻璃，顶部一道亮边当"厚度"
        text += (
            "\nQFrame#Card, QFrame#StatCard {"
            " background: rgba(20, 25, 33, 0.50);"
            " border: 1px solid rgba(255, 255, 255, 0.16);"
            " border-top: 1px solid rgba(255, 255, 255, 0.32);"
            " border-radius: " + t.value("radius-xl", "23") + "px; }"
            "\nQFrame#Card:hover, QFrame#StatCard:hover {"
            " border-color: rgba(255, 255, 255, 0.26); }"

            "\nQPushButton { background: rgba(255, 255, 255, 0.07);"
            " border: 1px solid rgba(255, 255, 255, 0.16); }"
            "\nQPushButton:hover { background: rgba(255, 255, 255, 0.13);"
            " border-color: rgba(255, 255, 255, 0.28); }"
            "\nQPushButton:pressed { background: rgba(255, 255, 255, 0.18); }"
            "\nQComboBox, QLineEdit, QSpinBox, QPlainTextEdit, QTextEdit, QTextBrowser {"
            " background: rgba(255, 255, 255, 0.06);"
            " border: 1px solid rgba(255, 255, 255, 0.15); }"
            "\nQToolTip { background: rgba(22, 27, 36, 0.94);"
            " border: 1px solid rgba(255, 255, 255, 0.18); }"
            "\nQLabel#Note { background: rgba(20, 25, 33, 0.50);"
            " border: 1px solid rgba(255, 255, 255, 0.16);"
            " border-top-color: rgba(255, 255, 255, 0.34);"
            " border-radius: 16px; padding: 9px 15px; }"
        )

    _REPLAYING = True
    try:
        # 1. 顶层窗口（主窗、对话框、菜单）直接用新皮肤的样式表
        for w in QtWidgets.QApplication.topLevelWidgets():
            try:
                w.setStyleSheet(text)
            except RuntimeError:
                pass
        # 2. 其余控件按当初设的原文重放，会自动翻成新皮肤的值
        for ref, raw in list(_STYLE_LOG):
            w = ref()
            if w is None:
                continue
            try:
                if not w.isWindow():
                    w.setStyleSheet(raw)
            except RuntimeError:
                pass
    finally:
        _REPLAYING = False

    _STYLE_LOG[:] = [(r, t) for r, t in _STYLE_LOG if r() is not None]


# ---------------------------------------------------------------------------
# 图标视图：流式布局 + 磁贴（布局类见 core/flow.py）
# ---------------------------------------------------------------------------
# 图标视图用的 FlowLayout / FlowPage 在 core/flow.py（工具页、模组页共用）


_ICON_PROVIDER = None
_ICON_CACHE: dict = {}
_FAVICON_EXTS = ("png", "ico", "gif", "bmp", "webp")


def _favicon_dir() -> Path:
    """官网图标缓存：扒过一次就存这儿，下次直接读，不再联网。"""
    p = app_dir() / "cache" / "favicons"
    try:
        p.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return p


def _favicon_key(host: str) -> str:
    return re.sub(r"[^a-z0-9.\-]", "_", (host or "").lower())[:64] or "site"


def _favicon_file(host: str) -> Optional[Path]:
    for ext in _FAVICON_EXTS:
        p = _favicon_dir() / f"{_favicon_key(host)}.{ext}"
        try:
            if p.exists() and p.stat().st_size > 100:
                return p
        except OSError:
            continue
    return None


def _try_favicon(mod: Mod) -> Optional[QtGui.QIcon]:
    """官网图标：网址/三方工具用 path，本机识别出来的工具用 home 里的官网地址。"""
    url = ""
    if mod.kind in (KIND_URL, KIND_REMOTE):
        url = mod.path or ""
    elif getattr(mod, "home", ""):
        url = mod.home
    if not url:
        return None
    host = (urllib.parse.urlparse(url).netloc or "").strip()
    if not host:
        return None
    p = _favicon_file(host)
    if p is None:
        return None
    icon = QtGui.QIcon(str(p))
    return icon if not icon.isNull() else None


def _sniff_image(data: bytes) -> str:
    """认一下是不是图片（有的站会返回一张 HTML 说 404）。"""
    if len(data) < 200:
        return ""
    if data[:4] == b"\x89PNG":
        return "png"
    if data[:2] == b"BM":
        return "bmp"
    if data[:4] in (b"\x00\x00\x01\x00", b"\x00\x00\x02\x00"):
        return "ico"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return ""


class _FaviconFetcher(QtCore.QThread):
    """后台扒官网图标：先试 apple-touch-icon（尺寸大更清楚），再退 favicon.ico。"""

    done = QtCore.Signal(int)  # 成功抓到几个

    def __init__(self, hosts, parent=None):
        super().__init__(parent)
        self.hosts = list(hosts)
        self.got = 0

    def run(self) -> None:
        for host in self.hosts:
            if self._grab(host):
                self.got += 1
        self.done.emit(self.got)

    def _grab(self, host: str) -> bool:
        cands = (
            f"https://{host}/apple-touch-icon.png",
            f"https://{host}/apple-touch-icon-precomposed.png",
            f"https://{host}/favicon.ico",
            f"https://{host}/favicon.png",
        )
        for url in cands:
            try:
                req = urllib.request.Request(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FlintMirror"
                    },
                )
                with urllib.request.urlopen(req, timeout=6) as resp:
                    data = resp.read(400_000)
            except Exception:
                continue
            ext = _sniff_image(data)
            if not ext:
                continue
            path = _favicon_dir() / f"{_favicon_key(host)}.{ext}"
            try:
                path.write_bytes(data)
                return True
            except OSError:
                continue
        return False


def _fallback_icon(name: str, color: str = "#20ffe0") -> QtGui.QIcon:
    px = QtGui.QPixmap(64, 64)
    px.fill(Qt.transparent)
    p = QtGui.QPainter(px)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor("#1b2230"))
    p.drawRoundedRect(QtCore.QRectF(2, 2, 60, 60), 12, 12)
    p.setPen(QtGui.QColor(color))
    f = p.font()
    f.setPixelSize(30)
    f.setBold(True)
    p.setFont(f)
    p.drawText(px.rect(), Qt.AlignCenter, (name or "?")[:1])
    p.end()
    return QtGui.QIcon(px)


def shell_icon(mod: Mod) -> QtGui.QIcon:
    """三方工具 / 网址先看官网图标缓存；程序取自身图标；都取不到画首字母方块。"""
    global _ICON_PROVIDER
    is_url_like = mod.kind in (KIND_URL, KIND_REMOTE) or bool(getattr(mod, "home", ""))
    key = ("url:" if is_url_like else "file:") + (getattr(mod, "home", "") or mod.path).lower()
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]

    fav = _try_favicon(mod)
    if fav is not None:
        _ICON_CACHE[key] = fav
        return fav

    # 内置页面没文件可取图标，三角洲情报用自带的绿三角闪电
    if mod.kind == KIND_PAGE:
        name = "delta.png" if (mod.path or "") == "delta" else ""
        if name:
            for base in (app_dir() / "assets", app_dir()):
                p = base / name
                if p.exists():
                    icon = QtGui.QIcon(str(p))
                    _ICON_CACHE[key] = icon
                    return icon

    icon = QtGui.QIcon()
    if mod.kind not in (KIND_URL, KIND_REMOTE):
        try:
            if _ICON_PROVIDER is None:
                _ICON_PROVIDER = QtWidgets.QFileIconProvider()
            info = QtCore.QFileInfo(mod.resolved)
            if info.exists():
                icon = _ICON_PROVIDER.icon(info)
        except Exception:
            icon = QtGui.QIcon()

    if icon.isNull():
        icon = _fallback_icon(
            mod.name, "#8a7bd4" if mod.kind != KIND_EXE else "#20ffe0"
        )
    _ICON_CACHE[key] = icon
    return icon


def confirm_remove(parent, mod: Mod) -> bool:
    box = QtWidgets.QMessageBox(parent)
    box.setWindowTitle("移除工具")
    box.setText(f'把「{mod.name}」从框架里移除？')
    box.setInformativeText("只从列表移除，不会删除原文件。")
    box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
    box.setDefaultButton(QtWidgets.QMessageBox.No)
    return box.exec() == QtWidgets.QMessageBox.Yes


class ModTile(QtWidgets.QFrame):
    """图标视图里的一格：双击启动 / 停止，右键有更多操作。"""

    changed = Signal()

    W = 118
    H = 124

    def __init__(self, mod: Mod, guard: ProcessGuard, cfg: Config, win: "MainWindow"):
        super().__init__()
        self.mod = mod
        self.guard = guard
        self.cfg = cfg
        self.win = win
        self.setObjectName("ModTile")
        self.setProperty("glass", bool(_glass_on))
        self.setProperty("liquid", bool(_liquid_on))
        self.setFixedSize(self.W, self.H)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_menu)
        self._build()
        self.refresh()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(8, 10, 8, 9)
        lay.setSpacing(4)

        self.icon_label = QtWidgets.QLabel()
        self.icon_label.setFixedSize(48, 48)
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setPixmap(shell_icon(self.mod).pixmap(44, 44))
        self._opacity = QtWidgets.QGraphicsOpacityEffect(self.icon_label)
        self._opacity.setOpacity(1.0)
        self.icon_label.setGraphicsEffect(self._opacity)
        lay.addWidget(self.icon_label, 0, Qt.AlignHCenter)

        self.name_label = QtWidgets.QLabel()
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setFixedHeight(18)
        lay.addWidget(self.name_label)

        lay.addStretch(1)

        self.status_label = QtWidgets.QLabel()
        self.status_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(self.status_label)

        # 内置模组（跟软件一起打包的那份）打个角标
        self.badge = QtWidgets.QLabel("内置", self)
        self.badge.setStyleSheet(
            "color:#20ffe0; background:#10302c; border:1px solid #1c5049;"
            "border-radius:5px; padding:1px 4px; font-size:9.5px;"
        )
        self.badge.adjustSize()
        builtin = self.mod.kind not in (KIND_URL, KIND_REMOTE) and not Path(self.mod.path).is_absolute()
        self.badge.setVisible(builtin)
        if builtin:
            self.badge.move(self.W - self.badge.width() - 7, 7)

    # ------------------------------------------------------------------
    def _repolish(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def enterEvent(self, event) -> None:
        self.setProperty("hover", "true")
        self._repolish()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.setProperty("hover", "false")
        self._repolish()
        super().leaveEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self._act()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------
    def _act(self) -> None:
        if not self.mod.enabled:
            self.win.toast("这个工具被屏蔽了，右键「允许框架启动」可以打开", False)
            return
        if self.mod.kind == KIND_REMOTE:
            self.win.open_remote(self.mod)
            self.refresh()
            self.changed.emit()
            return
        if self.mod.kind == KIND_EXE and self.guard.is_running(self.mod):
            ok, msg = self.guard.stop(self.mod)
            self.win.toast(msg, ok)
        else:
            self.win.launch_mod(self.mod)
        self.refresh()
        self.changed.emit()

    def _on_enable(self, checked: bool) -> None:
        self.mod.enabled = checked
        self.cfg.save()
        self.refresh()
        self.changed.emit()

    def _on_autostart(self, checked: bool) -> None:
        self.mod.autostart = checked
        self.cfg.save()

    def _on_remove(self) -> None:
        if not confirm_remove(self, self.mod):
            return
        if self.guard.is_running(self.mod):
            self.guard.stop(self.mod)
        self.cfg.remove_mod(self.mod.id)
        self.changed.emit()
        self.win.rebuild_mods()

    def _on_menu(self, pos) -> None:
        m = QtWidgets.QMenu(self)
        running = self.guard.is_running(self.mod)
        if self.mod.kind == KIND_EXE:
            act = m.addAction("停止" if running else "启动")
        else:
            act = m.addAction("打开")
        act.setEnabled(self.mod.enabled and (self.mod.exists or self.mod.kind == KIND_URL))
        act.triggered.connect(self._act)

        m.addSeparator()
        a_en = m.addAction("允许框架启动")
        a_en.setCheckable(True)
        a_en.setChecked(self.mod.enabled)
        a_en.triggered.connect(self._on_enable)

        a_auto = m.addAction("随框架启动")
        a_auto.setCheckable(True)
        a_auto.setChecked(self.mod.autostart)
        a_auto.triggered.connect(self._on_autostart)

        m.addSeparator()
        if self.mod.kind not in (KIND_URL, KIND_PAGE, KIND_REMOTE):
            a_dir = m.addAction("在文件夹中打开")
            a_dir.setEnabled(self.mod.exists)
            a_dir.triggered.connect(
                lambda: os.startfile(str(Path(self.mod.resolved).parent))
            )
        a_rm = m.addAction("从框架移除")
        a_rm.triggered.connect(self._on_remove)
        m.exec(self.mapToGlobal(pos))

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        raw = self.mod.name
        fm = self.name_label.fontMetrics()
        self.name_label.setText(fm.elidedText(raw, Qt.ElideRight, self.W - 22))
        self.name_label.setToolTip(raw)

        running = self.mod.enabled and self.guard.is_running(self.mod)
        missing = (not self.mod.exists) and self.mod.kind != KIND_URL
        err = (getattr(self.mod, "last_error", "") or "").strip()

        tip = ""
        if not self.mod.enabled:
            txt, color = "已屏蔽", "#525b69"
        elif missing:
            txt, color = "文件丢失", "#ff6b6b"
            tip = "文件不在了：换盘或挪过目录？右键编辑重新指一下"
        elif self.mod.kind == KIND_PAGE:
            txt, color = "打开页面", "#8a7bd4"
        elif self.mod.kind == KIND_REMOTE:
            txt, color = ("三方·下载" if self.mod.dl else "三方·官网"), "#8a7bd4"
        elif self.mod.kind != KIND_EXE:
            txt, color = "网页", "#8a7bd4"
        elif running:
            txt, color = "● 运行中", "#20ffe0"
        elif err:
            txt, color = "启动失败", "#ff6b6b"
            tip = err
        elif getattr(self.mod, "home", ""):
            # 这条是启动时从本机认出来的，不是从官网重新下的
            txt, color = "已安装", "#7bd4a8"
            tip = "本机已装好，点一下直接启动"
        else:
            txt, color = "未运行", "#5f6878"

        self.status_label.setText(txt)
        self.status_label.setStyleSheet(f"color: {color}; font-size: 10.5px;")
        self.status_label.setToolTip(tip)
        self.setToolTip(tip if tip else self.mod.name)
        self.name_label.setStyleSheet(
            "font-size: 12px; font-weight: 600; color: %s;"
            % ("#e6ebf3" if self.mod.enabled else "#525b69")
        )
        try:
            self._opacity.setOpacity(1.0 if self.mod.enabled else 0.35)
        except RuntimeError:
            # 卡片已经被重建掉了，这个旧 wrapper 不用再管
            pass
        self.setProperty("off", "false" if self.mod.enabled else "true")
        self._repolish()


# ---------------------------------------------------------------------------
# 工具卡片
# ---------------------------------------------------------------------------
class ModCard(QtWidgets.QFrame):
    changed = Signal()

    def __init__(self, mod: Mod, guard: ProcessGuard, cfg: Config, win: "MainWindow"):
        super().__init__()
        self.mod = mod
        self.guard = guard
        self.cfg = cfg
        self.win = win
        self.setObjectName("ModCard")
        # 玻璃/液态玻璃时卡片换成半透明玻璃面，见 QSS_TEMPLATE 里 [glass="true"]
        self.setProperty("glass", bool(_glass_on))
        self.setProperty("liquid", bool(_liquid_on))
        self._build()
        self.refresh()

    # ------------------------------------------------------------------
    def _build(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(12, 10, 10, 10)
        outer.setSpacing(6)

        row1 = QtWidgets.QHBoxLayout()
        row1.setSpacing(10)

        self.chk = QtWidgets.QCheckBox()
        self.chk.setToolTip("启用 = 允许这个工具被框架启动；取消勾选 = 从框架里屏蔽掉")
        self.chk.setChecked(self.mod.enabled)
        self.chk.toggled.connect(self._on_enable)
        row1.addWidget(self.chk)

        namebox = QtWidgets.QVBoxLayout()
        namebox.setSpacing(2)
        self.name_label = QtWidgets.QLabel(self.mod.name)
        self.name_label.setStyleSheet("font-size: 13.5px; font-weight: 600; color: #e6ebf3;")
        self.path_label = QtWidgets.QLabel()
        self.path_label.setObjectName("Small")
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        namebox.addWidget(self.name_label)
        namebox.addWidget(self.path_label)
        row1.addLayout(namebox, 1)

        self.kind_label = QtWidgets.QLabel(self.mod.kind_label)
        self.kind_label.setStyleSheet(
            "color:#6f7a8c; border:1px solid #2a3240; border-radius:5px; padding:1px 6px; font-size:10px;"
        )
        row1.addWidget(self.kind_label)

        self.status_label = QtWidgets.QLabel("● 未运行")
        self.status_label.setStyleSheet("color:#5f6878; font-size:11px;")
        row1.addWidget(self.status_label)

        self.action_btn = QtWidgets.QPushButton("启动")
        self.action_btn.setObjectName("Mini")
        self.action_btn.setMinimumWidth(58)
        self.action_btn.clicked.connect(self._on_action)
        row1.addWidget(self.action_btn)

        remove_btn = QtWidgets.QPushButton("✕")
        remove_btn.setObjectName("Danger")
        remove_btn.setToolTip("从框架里移除这个工具（不会删除原文件）")
        remove_btn.clicked.connect(self._on_remove)
        row1.addWidget(remove_btn)

        outer.addLayout(row1)

        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(10)
        row2.setContentsMargins(24, 0, 0, 0)
        self.auto_chk = QtWidgets.QCheckBox("随框架启动")
        self.auto_chk.setStyleSheet("color:#7b8494; font-size:11px;")
        self.auto_chk.setChecked(self.mod.autostart)
        self.auto_chk.setToolTip("打开燧镜时，自动把这个工具一起拉起来")
        self.auto_chk.toggled.connect(self._on_autostart)
        row2.addWidget(self.auto_chk)

        self.delay_spin = QtWidgets.QSpinBox()
        self.delay_spin.setRange(0, 300)
        self.delay_spin.setSuffix(" 秒")
        self.delay_spin.setFixedWidth(80)
        self.delay_spin.setToolTip("点启动后，等这么多秒再真正拉起来")
        self.delay_spin.setValue(int(self.mod.delay or 0))
        self.delay_spin.valueChanged.connect(self._on_delay)
        row2.addWidget(self.delay_spin)

        self.args_edit = QtWidgets.QLineEdit(" ".join(self.mod.args))
        self.args_edit.setPlaceholderText("启动参数（可选）")
        self.args_edit.setFixedHeight(24)
        self.args_edit.setToolTip("会原样跟在程序后面，比如 -windowed -novid")
        self.args_edit.editingFinished.connect(self._on_args)
        row2.addWidget(self.args_edit, 1)

        self.note_label = QtWidgets.QLabel()
        self.note_label.setObjectName("Small")
        home = getattr(self.mod, "home", "")
        if home:
            # 本机识别出来的工具：正文位置留给「打开官网」，随时能回去看官网
            self.note_label.setTextFormat(Qt.RichText)
            self.note_label.setTextInteractionFlags(Qt.TextBrowserInteraction)
            self.note_label.setOpenExternalLinks(True)
            self.note_label.setText(
                '本机已装 · <a href="%s" style="color:#8a7bd4">打开官网</a>' % home
            )
        else:
            self.note_label.setText(self.mod.note)
        row2.addWidget(self.note_label)
        outer.addLayout(row2)

    # ------------------------------------------------------------------
    def _on_enable(self, checked: bool) -> None:
        self.mod.enabled = checked
        self.cfg.save()
        self.refresh()
        self.changed.emit()

    def _on_autostart(self, checked: bool) -> None:
        self.mod.autostart = checked
        self.cfg.save()

    def _on_delay(self, value: int) -> None:
        self.mod.delay = int(value)
        self.cfg.save()

    def _on_args(self) -> None:
        text = self.args_edit.text().strip()
        self.mod.args = text.split() if text else []
        self.cfg.save()

    def _on_action(self) -> None:
        if self.mod.kind == KIND_REMOTE:
            self.win.open_remote(self.mod)
            self.refresh()
            self.changed.emit()
            return
        if self.mod.kind == KIND_EXE and self.guard.is_running(self.mod):
            ok, msg = self.guard.stop(self.mod)
            self.win.toast(msg, ok)
        else:
            self.win.launch_mod(self.mod)
        self.refresh()
        self.changed.emit()

    def _on_remove(self) -> None:
        if not confirm_remove(self, self.mod):
            return
        if self.guard.is_running(self.mod):
            self.guard.stop(self.mod)
        self.cfg.remove_mod(self.mod.id)
        self.changed.emit()
        self.win.rebuild_mods()

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        # 路径省略显示
        raw = self.mod.path
        if self.mod.kind == KIND_PAGE:
            raw = "内置页面 · 不启动外部程序"
        elif self.mod.kind == KIND_REMOTE:
            host = (urllib.parse.urlparse(raw).netloc or raw).strip()
            raw = "官网 · " + host + ("（有直链，可直接下载）" if self.mod.dl else "（自己下载）")
        elif self.mod.kind != KIND_URL and not Path(raw).is_absolute():
            raw = "内置 · " + raw.replace("/", chr(92))
        if getattr(self.mod, "home", "") and self.mod.kind == KIND_EXE:
            raw = "本机已装 · " + raw
        self._path_raw = raw
        self.path_label.setToolTip(raw)
        self._elide_path()

        running = self.mod.enabled and self.guard.is_running(self.mod)
        missing = self.mod.enabled and not self.mod.exists
        err = (getattr(self.mod, "last_error", "") or "").strip()

        if missing:
            self.status_label.setText("● 文件丢失")
            self.status_label.setStyleSheet("color:#ff6b6b; font-size:11px;")
            self.status_label.setToolTip("文件不在了：换盘或挪过目录？右键编辑重新指一下")
        elif self.mod.kind == KIND_PAGE:
            self.status_label.setText("● 内置页面")
            self.status_label.setStyleSheet("color:#8a7bd4; font-size:11px;")
            self.status_label.setToolTip("内置页面：点按钮直接切过去，不启动外部程序")
        elif self.mod.kind == KIND_REMOTE:
            self.status_label.setText("● 三方工具")
            self.status_label.setStyleSheet("color:#8a7bd4; font-size:11px;")
            self.status_label.setToolTip(
                "点一下由燧镜下载，下完自动变成工具"
                if self.mod.dl
                else "点一下打开官网，自己下载后用「+ 添加工具」指过来"
            )
        elif self.mod.kind != KIND_EXE:
            self.status_label.setText("● 网页")
            self.status_label.setStyleSheet("color:#8a7bd4; font-size:11px;")
            self.status_label.setToolTip("网页类工具用默认浏览器打开，框架不接管它")
        elif running:
            self.status_label.setText("● 运行中")
            self.status_label.setStyleSheet("color:#20ffe0; font-size:11px;")
            self.status_label.setToolTip("")
        elif err:
            self.status_label.setText("● 启动失败")
            self.status_label.setStyleSheet("color:#ff6b6b; font-size:11px;")
            self.status_label.setToolTip(err)
        elif getattr(self.mod, "home", ""):
            self.status_label.setText("● 已安装")
            self.status_label.setStyleSheet("color:#7bd4a8; font-size:11px;")
            self.status_label.setToolTip("本机已装好，点「启动」直接开")
        else:
            self.status_label.setText("● 未运行")
            self.status_label.setStyleSheet("color:#5f6878; font-size:11px;")
            self.status_label.setToolTip("")

        if self.mod.kind == KIND_REMOTE:
            self.action_btn.setText("下载" if self.mod.dl else "官网")
        elif self.mod.kind != KIND_EXE:
            self.action_btn.setText("打开")
        elif running:
            self.action_btn.setText("停止")
        else:
            self.action_btn.setText("启动")

        self.action_btn.setEnabled(
            self.mod.enabled and (not missing or self.mod.kind in (KIND_URL, KIND_REMOTE))
        )
        self.name_label.setStyleSheet(
            "font-size: 13.5px; font-weight: 600; color: %s;"
            % ("#e6ebf3" if self.mod.enabled else "#525b69")
        )
        self.setProperty("off", "false" if self.mod.enabled else "true")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def _elide_path(self) -> None:
        """路径太长就在中间省略，别顶到右边的「程序 / 未运行 / 启动」上去。"""
        raw = getattr(self, "_path_raw", "")
        if not raw:
            return
        fixed = 24
        for w in (self.kind_label, self.status_label, self.action_btn):
            fixed += w.sizeHint().width() + 10
        fixed += 96  # 右边的 ✕ 按钮 + 卡片内边距
        avail = max(90, self.width() - fixed)
        if self.path_label.maximumWidth() != avail:
            self.path_label.setFixedWidth(avail)
        fm = self.path_label.fontMetrics()
        self.path_label.setText(fm.elidedText(raw, Qt.ElideMiddle, avail))

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.refresh()


# ---------------------------------------------------------------------------
# 工具添加对话框
# ---------------------------------------------------------------------------
class AddModDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加工具")
        self.setMinimumWidth(520)
        self.setStyleSheet(qss())
        self.result_path = ""
        self.result_name = ""

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        tip = QtWidgets.QLabel("选择要挂进框架的程序或网页。支持 .exe / .bat / .html / .htm，也可以直接填网址。")
        tip.setWordWrap(True)
        tip.setObjectName("Small")
        lay.addWidget(tip)

        row = QtWidgets.QHBoxLayout()
        self.path_edit = QtWidgets.QLineEdit()
        self.path_edit.setPlaceholderText("路径或网址，例如 C:\\...\\xxx.exe 或 https://...")
        self.path_edit.setStyleSheet(
            "background:#1a1f29; border:1px solid #2c3543; border-radius:8px; padding:7px 10px; color:#dfe5ef;"
        )
        browse = QtWidgets.QPushButton("浏览…")
        browse.setObjectName("Ghost")
        browse.clicked.connect(self._browse)
        row.addWidget(self.path_edit, 1)
        row.addWidget(browse)
        lay.addLayout(row)

        row2 = QtWidgets.QHBoxLayout()
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("显示名称（留空则用文件名）")
        self.name_edit.setStyleSheet(self.path_edit.styleSheet())
        row2.addWidget(self.name_edit, 1)
        lay.addLayout(row2)

        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        cancel = QtWidgets.QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(self.reject)
        ok = QtWidgets.QPushButton("添加")
        ok.setObjectName("Primary")
        ok.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    def _browse(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "选择程序或网页",
            str(Path(os.path.expanduser("~")) / "Desktop"),
            "可执行程序 (*.exe *.bat *.cmd);;网页 (*.html *.htm);;快捷方式 (*.lnk);;所有文件 (*.*)",
        )
        if path:
            self.path_edit.setText(path)
            if not self.name_edit.text().strip():
                self.name_edit.setText(Path(path).stem)

    def _accept(self) -> None:
        path = self.path_edit.text().strip().strip('"')
        if not path:
            QtWidgets.QMessageBox.warning(self, "提示", "请先选择文件或填写网址。")
            return
        if not (path.lower().startswith("http://") or path.lower().startswith("https://")):
            if not Path(path).exists():
                QtWidgets.QMessageBox.warning(self, "提示", "这个路径不存在，请检查。")
                return
        self.result_path = path
        self.result_name = self.name_edit.text().strip() or Path(path).stem
        self.accept()


# ---------------------------------------------------------------------------
# 三方工具：官网链接 + 直链下载
# ---------------------------------------------------------------------------
_FIELD_QSS = (
    "background:#1a1f29; border:1px solid #2c3543; border-radius:8px;"
    " padding:7px 10px; color:#dfe5ef;"
)


def _downloads_dir() -> Path:
    """三方工具下载到「文档\\燧镜\\tools」，卸载软件不会跟着丢。"""
    base = Path(os.path.expanduser("~")) / "Documents" / "燧镜" / "tools"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError:
        base = app_dir() / "downloads"
        try:
            base.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return base


def _safe_folder(name: str) -> str:
    bad = '<>:"/\\|?*'
    out = "".join("_" if c in bad else c for c in (name or "")).strip()
    return (out or "tool")[:40]


def _guess_filename(url: str) -> str:
    """从直链里扒文件名；扒不到就叫 download.bin。"""
    try:
        p = urllib.parse.urlparse(url)
        name = Path(urllib.parse.unquote(p.path)).name
    except Exception:  # noqa: BLE001
        name = ""
    return name or "download.bin"


class _RemoteDownload(QtCore.QThread):
    """下载线程：只管搬字节，进度靠信号回主线程。"""

    progress = QtCore.Signal(int, int)  # 已下 / 总大小（0 = 服务器没给长度）
    ok = QtCore.Signal(str)             # 落地文件路径
    bad = QtCore.Signal(str)            # 失败原因

    def __init__(self, url: str, dest: Path, parent=None):
        super().__init__(parent)
        self.url = url
        self.dest = dest
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        try:
            req = urllib.request.Request(
                self.url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) FlintMirror",
                    "Accept": "*/*",
                },
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                got = 0
                with open(self.dest, "wb") as f:
                    while not self._stop:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
                        got += len(chunk)
                        self.progress.emit(got, total)
            if self._stop:
                try:
                    self.dest.unlink()
                except OSError:
                    pass
                self.bad.emit("已取消")
                return
            self.ok.emit(str(self.dest))
        except Exception as exc:  # noqa: BLE001
            self.bad.emit(str(exc)[:200])


class AddRemoteDialog(QtWidgets.QDialog):
    """加一条「三方工具」：名称 + 官网（必填）+ 直接下载地址（可空）。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("添加三方工具")
        self.setMinimumWidth(560)
        self.setStyleSheet(qss())
        self.result_name = ""
        self.result_home = ""
        self.result_dl = ""

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)

        tip = QtWidgets.QLabel(
            "只填官网也能加：点卡片就是开浏览器。\n"
            "要是知道安装包的直链，填第三行 —— 那样点一下燧镜自己下，"
            "下完（exe）自动变成工具页里的一条本地工具。"
        )
        tip.setWordWrap(True)
        tip.setObjectName("Small")
        lay.addWidget(tip)

        lay.addWidget(self._lab("名称"))
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("例如 图吧工具箱")
        self.name_edit.setStyleSheet(_FIELD_QSS)
        lay.addWidget(self.name_edit)

        lay.addWidget(self._lab("官网地址（必填）"))
        self.home_edit = QtWidgets.QLineEdit()
        self.home_edit.setPlaceholderText("https://…（点卡片会打开这里）")
        self.home_edit.setStyleSheet(_FIELD_QSS)
        lay.addWidget(self.home_edit)

        lay.addWidget(self._lab("直接下载地址（可空）"))
        self.dl_edit = QtWidgets.QLineEdit()
        self.dl_edit.setPlaceholderText("https://…/setup.exe 或 .zip；留空就只开官网")
        self.dl_edit.setStyleSheet(_FIELD_QSS)
        lay.addWidget(self.dl_edit)

        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        cancel = QtWidgets.QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(self.reject)
        ok = QtWidgets.QPushButton("添加")
        ok.setObjectName("Primary")
        ok.clicked.connect(self._accept)
        btns.addWidget(cancel)
        btns.addWidget(ok)
        lay.addLayout(btns)

    @staticmethod
    def _lab(text: str) -> QtWidgets.QLabel:
        lab = QtWidgets.QLabel(text)
        lab.setObjectName("Small")
        return lab

    def _accept(self) -> None:
        name = self.name_edit.text().strip()
        home = self.home_edit.text().strip().strip('"')
        dl = self.dl_edit.text().strip().strip('"')
        if not name:
            QtWidgets.QMessageBox.warning(self, "提示", "给这条三方工具起个名字。")
            return
        if not (home.lower().startswith("http://") or home.lower().startswith("https://")):
            QtWidgets.QMessageBox.warning(self, "提示", "官网地址要以 http:// 或 https:// 开头。")
            return
        if dl and not (dl.lower().startswith("http://") or dl.lower().startswith("https://")):
            QtWidgets.QMessageBox.warning(
                self, "提示", "下载地址要以 http:// 或 https:// 开头（拿不到直链就留空）。"
            )
            return
        self.result_name = name
        self.result_home = home
        self.result_dl = dl
        self.accept()


# ---------------------------------------------------------------------------
# 关于
# ---------------------------------------------------------------------------
CHANGELOG = [
    (
        "2026-11-24 · v1.10.3",
        [
            "新增：本机装好的三方工具自动认出来 —— 第一次打开（或刚升级上来）扫一遍注册表卸载表和常见安装目录，"
            "认出哪个就把那张「三方·官网」卡换成本地工具，点一下直接启动，图标还是官网那张",
            "认得出的：Steam、Epic Games、KOOK、OOPZ、图吧工具箱、PCL2 启动器、飞鼠格式；"
            "绿色包没有注册表，靠目录名猜；认不出的继续挂官网入口",
            "名单里本来就手动加过同一个程序的，不会冒出第二张卡，官网地址直接补到原来那条",
            "不会一直扫盘：只在「这份配置还没扫过」时扫一次，后台线程跑完就结束，不常驻不轮询；"
            "同一个名字 24 小时内不重复扫",
            "新增：工具页顶部「刷新」按钮，手动再扫一遍（只留这一个重扫入口，「⋯」里不再重复放一条）",
            "修：模组接口补上真实现 —— 宿主事件（app.started / game.started / game.stopped / "
            "mod.enabled / mod.disabled）以前只写在文档里没发过，现在真发了；"
            "模组注册的界面页以前被宿主忽略，现在能在模组卡片「⋯」里打开；模组热键也真能注册上了",
            "新增：装模组前先弹一次确认窗 —— 从 .sjmod 里只读捞出 manifest，把名称、版本、作者、说明和申请的权限"
            "逐条翻成中文；包里带了可执行程序（.exe/.dll/.bat）的，也逐个列出来再让你决定装不装；"
            "拖拽、点按钮选文件、拖放区三个入口都过这一道",
            "扩展包：模组可以自带依赖了 —— 纯 Python 包放 assets\\lib（pylibs 也认），宿主在 on_load 之前自动挂进 "
            "sys.path，顶层 import 也能用；命令行程序放 assets\\bin，调用走 host.shell.capture 拿返回码和输出；"
            "这些依赖仍然不进安装包，体积不为某一个模组让步",
            "扩展包自带可执行程序的两条规矩（自检脚本会查）：只能放 assets 下，且 manifest 必须申请 shell 权限",
            "修：这一页之前断了三个版本没写（v1.10.0 ~ v1.10.2），点开还停在 11-23 的 v1.9.7，现在一起补回来",
        ],
    ),
    (
        "2026-11-24 · v1.10.2",
        [
            "改：工具页去掉「全部启动」—— 这一页混着网页工具和还没下载的三方工具，一键全起容易误开一堆，"
            "要一次起一串去「自动化」写条规则",
            "改：推荐的七个三方工具改成随配置自动补齐（只补一次，自己删掉的不再塞回来），"
            "拿到别人的老配置、升级上来的配置也都有这一排",
            "改：官网图标缓存跟着安装包和分发版一起走，第一次打开就是官方图标，不用等联网抓",
        ],
    ),
    (
        "2026-11-24 · v1.10.1",
        [
            "改：工具页已下载的排上面，没下载的三方推荐用一条横线隔在下面、标「三方工具」，点一格直接去官网",
            "改：三方工具和网页类的图标换成官网那张 —— Steam、图吧工具箱、飞鼠格式、Epic Games、"
            "PCL2 启动器、KOOK、OOPZ；存进 cache\\favicons，离线也能显示，全抓不到才退回首字母",
            "改：列表视图的长路径中间省略，不再顶到右边的「程序 / 未运行 / 启动」",
            "改：全软件统一叫「工具」，托盘菜单、自动化动作、导出清单、提示文字全改过来；"
            "「模组」这个名字只留给 .sjmod 扩展包",
            "修：图吧工具箱的官网地址改回 tbtool.co（.cn 是老站，图标对不上）",
        ],
    ),
    (
        "2026-11-24 · v1.10.0",
        [
            "新增：模组框架 —— 新的 .sjmod 格式（zip 里放 manifest.json + main.py + assets），"
            "只在燧镜里能跑，单开打不开；支持拖拽安装、启用停用、卸载、打开文件夹，装坏的进 mods\\_invalid",
            "新增：宿主按 manifest 权限放行能力 —— 日志、通知、配置、界面页、热键、事件、定时器、启动外部程序",
            "改：页签重排成三页 —— 内置工具 / 工具 / 模组，原来的「模组」统一改叫「工具」",
            "改：「口琴可视化曲谱」改造成第一个模组，功能一行没动",
            "新增：docs\\MOD_API.md 接口规范、tool\\make_sjmod.py 打包、tool\\mod_test.py 只读自检、"
            "mods\\_examples\\hello 最小示例",
        ],
    ),
    (
        "2026-11-23 · v1.9.7",
        [
            "新增：设置 → 版本与更新 里加了一张赞赏码 —— 纯自愿、不影响任何功能，"
            "点一下能看大图；这张图只随安装包和分发版走",
        ],
    ),
    (
        "2026-11-22 · v1.9.6",
        [
            "改：提示不再弹到屏幕上，回到软件自己的岛 —— 跟游戏模式开关同一个位置、"
            "同一个胶囊，一次只显示一条，不再压着顶栏文字",
            "改：关窗口时顺手把还亮着的提示收掉，不留尾巴",
            "修：每次启动窗口都跑屏幕左上角去了；现在一开就摆在屏幕正中间",
        ],
    ),
    (
        "2026-11-22 · v1.9.5",
        [
            "修：投屏面板点「关闭」直接卡死闪退 —— scrcpy 进程原来挂在对话框身上，"
            "对话框一销毁，Qt 就会同步等它退出，界面当场冻住；现在进程归主窗口管",
            "改：投屏面板拆成两个按钮 ——「收起面板」只收小窗、投屏照旧跑，"
            "「结束投屏」才真断开；主页那块方块会显示「投屏中」",
            "新增：所有提示统一上岛 —— 屏幕顶部中间那条胶囊，跟手机上的灵动岛一个意思，"
            "不再写在窗口左下角那行小字里",
            "改：模组卡片在毛玻璃 / 液态玻璃下换成深色玻璃质感（亮边 + 圆角 + 半透明），"
            "以前只是把色块调透明，看着像蒙了层灰",
            "新增：模组页「⋯」菜单可以导出 / 导入模组清单，换台电脑装机不用一条条重加",
        ],
    ),
    (
        "2026-11-22 · v1.9.4",
        [
            "修：切页之后底下透出上一页的「残影」（透明页面 + 系统磨砂时旧像素没人擦）；"
            "现在每切一次都整窗重画，并把磨砂层重新套一遍",
        ],
    ),
    (
        "2026-11-22 · v1.9.3",
        [
            "改：「手机投屏」方块收成跟「连接手机 / 文件互传」一样大，"
            "竖着补齐右边那一列，落点正对 CPU / 内存那一行，右边不留空",
            "修：覆盖安装时如果投屏的 adb 还在后台跑，会卡在"
            "「无法打开要写入的文件 AdbWinApi.dll」；安装器现在会先把它关掉",
        ],
    ),
    (
        "2026-11-22 · v1.9.2",
        [
            "修：电脑重装过、口令换过之后，手机以前会卡在「链接不对」那一页出不来 —— "
            "现在连之前先验口令，对不上就直接说「回电脑上重新扫一下码」",
            "修：自动找回电脑时把上次那台的机器身份写回去的毛病 —— 现在每次都重新拉当前这台的名字和身份",
            "加固：配对码连错 5 次就作废换新的一串（6 位数字没有次数限制，同网是能被暴力试出来的）",
        ],
    ),
    (
        "2026-11-22 · v1.9.1",
        [
            "改：「手机投屏」只在主页右上角一个入口，模组页里那张同款卡去掉了，"
            "从旧版升级上来的也会自动消失",
            "改：投屏的「无线连接」自己填手机互联记下的 IP —— 扫过码或输过配对码的手机，"
            "点开就是现成地址，不用再去手机设置里抄",
            "说明：第一次切无线还是要插一次 USB 线点「允许 USB 调试」，这是 Android 的规矩，换谁做都一样",
        ],
    ),
    (
        "2026-11-22 · v1.9.0",
        [
            "新：主页多了「手机投屏」—— 包内自带 scrcpy 和 adb，插上数据线点一下，"
            "手机画面就在电脑上，鼠标键盘直接反控；手机那头不用装任何 App",
            "新：投屏会先说清楚状态 —— 没连手机就列开调试的四步；手机弹了授权框，"
            "就提示你去点「允许 USB 调试」；真连上了才让按「开始投屏」",
            "新：画质三档（流畅 / 标准 / 高清），无线也能投 —— 第一次插着线切一次，之后拔线依然能用",
            "改：投屏时让手机物理屏熄灭但保持唤醒（既省电又不掉线），窗口关掉就断开，不留后台进程",
            "修：文件互传方向补齐 —— 电脑上「选文件发给手机」可以挑任意类型（安装包 / 压缩包 / 视频 / 工程文件），"
            "下到手机「下载」文件夹直接打开或安装；手机选文件也换成了系统文件选择器，apk 之类以前挑不到的现在能挑",
            "修：中文文件名下载到手机不再被压成「_v1.0.5.apk」这种残名",
            "改：分发版和安装版带的内置模组，直接照软件自己的内置模组表生成 —— 表里有几条就带几条，不会再漏",
        ],
    ),
    (
        "2026-11-22 · v1.8.0",
        [
            "新：顶栏「自动化」左边多了个「游戏模式」开关 —— 点一下，壁纸收起来、"
            "监控采集从 2.5 秒降到 6 秒一次、系统电源计划切到高性能；再点一下或退出程序，"
            "这几样全部放回原样",
            "新：手机 App 现在自己认电脑了 —— 打开先拿上次那个地址试一下，"
            "电脑换了 IP 就在同网重新找回来，实在找不到才让你扫码/输配对码",
            "改：每台电脑第一次开机会生成一个自己的局域网身份，口令也各机独立，"
            "同一份安装包发给别人，手机不会串到你的电脑上",
            "修：文件互传现在电脑上多了「选文件发给手机」—— 从任意位置挑任意类型"
            "（安装包、压缩包、视频、工程文件），进手机「下载」文件夹后直接打开或安装",
            "修：手机端选文件换成系统文件选择器，apk、7z 这些以前在列表里看不到的类型现在都能挑",
            "修：中文文件名下载后不再被压成「_v1.0.5.apk」这种残名",
            "说明：只动燧镜自己和系统设置，不会去改游戏进程的优先级、不做注入，"
            "反作弊眼里我们始终是个旁观者；没有高性能电源计划的机器（有些笔记本）会自动跳过这一条",
        ],
    ),
    (
        "2026-11-22 · v1.7.2",
        [
            "新：主页「连接手机」方块右上角多了个状态点 —— 手机那边（App 或网页）连着电脑时是青色实心点，"
            "一断开就变回灰色空心环；鼠标停在方块上，提示里会写清楚连的是哪台手机、它的 IP 是多少",
        ],
    ),
    (
        "2026-11-21 · v1.7.1",
        [
            "改：顶栏不再挂「三角洲情报」页签 —— 它本来就该只从模组区进，"
            "现在点模组里那张卡片才切过去，顶栏少一个格子，其他标签不挤",
            "改：模组区里三角洲情报的图标换成绿三角闪电那张，不再是首字母方块",
        ],
    ),
    (
        "2026-11-21 · v1.7.0",
        [
            "新：音乐灵动岛点开以后底下多了一条音量 —— 小喇叭 + 滑块 + 百分比，"
            "拖滑块或者在上面滚滚轮都行，调完记进配置、下次还是这个音量",
            "修：桌面音乐悬浮条以前只有最左边那 12 像素的把手能按住拖，稍微偏一点就拖不动；"
            "现在整条空白处（卡片、歌名、封面那块）都是抓手，拖到屏幕左右边缘松手照样自动贴边收起",
        ],
    ),
    (
        "2026-11-21 · v1.6.7",
        [
            "改：毛玻璃和液态玻璃下窗口改成方方正正一整块 —— 之前除了底子那层，"
            "系统的 DWM 也在偷偷把四角收圆，两处都关掉了，现在壁纸整块铺满、四角就是直角，"
            "不再有圆弧边透出来",
        ],
    ),
    (
        "2026-11-21 · v1.6.6",
        [
            "改：毛玻璃和液态玻璃下窗口不再硬裁形状 —— 之前用蒙版把四角切掉，"
            "切口是锯齿、壁纸还会在四角露出缺口；现在窗口保持矩形、壁纸整块铺满，"
            "圆角只由底子那层画出来，看着才像一张图贴满整个窗口",
        ],
    ),
    (
        "2026-11-21 · v1.6.5",
        [
            "改：设置页里「立绘」全部改叫「壁纸」，复选框写成「显示壁纸（铺满整窗，半透明垫底）」，"
            "选择图片 / 清空的提示也跟着换成壁纸的说法",
            "修：壁纸现在铺满整个窗口，不再自己切圆角",
            "修：启动时配置本来就是毛玻璃 / 液态玻璃的话，窗口形状现在也会一次裁好，"
            "不用手动切一遍外观才圆",
        ],
    ),
    (
        "2026-11-21 · v1.6.4",
        [
            "修：毛玻璃 / 液态玻璃下壁纸把窗口四个角重新填成了直角，看着和窗口圆角对不上；"
            "改成壁纸铺满整窗、不再自己裁圆角，圆角统一由窗口那层裁，经典外观下不裁",
        ],
    ),
    (
        "2026-11-21 · v1.6.3",
        [
            "修：手机 App 和电脑断开时整页黑屏、也没有任何地方能点回连接页，只能按返回键再手动重连；"
            "现在网页自己每 2.5 秒问一次电脑还在不在，没应答就出一张断线卡片，"
            "写着可能的原因（电脑睡了 / 燧镜退了 / 换了 WiFi）和「马上重连」「换一台电脑」两个按钮，"
            "电脑回来以后卡片自己消失",
            "修：连不上电脑时 App 不再留一片黑，主页面加载失败会直接回到连接页（接口偶尔超时不会误踢）",
            "手机版 App 升到 1.0.4：断线卡片上的「换一台电脑」能一键回连接页，不用再按返回键",
            "改：框选截图不再是松手就存 —— 拖完先给一个对勾一个叉号，点对勾才落盘，"
            "点叉号 / Esc / 右键都算放弃，不满意还能在原地重新框；回车也能直接确认，"
            "选区内保持原亮、选区外压暗，框里拍的是什么看得清",
        ],
    ),
    (
        "2026-11-21 · v1.6.2",
        [
            "修：手机「设置」页里那块「手机传来的文件存到 D:\燧镜\收到」——那是电脑上的路径说明，手机上根本用不到，撤掉了",
            "修：电脑传过去的文件以前只在网页里点开看，没真正落到手机存储里，所以文件管理器翻不到；"
            "现在按附件下载，存进手机「下载」文件夹，重启手机也还在",
            "新增：手机文件页多了个「在手机里打开「下载」文件夹」的按钮，点一下直接调起手机的文件管理，"
            "刚传过来的那份就在里面",
            "修：开机自启不生效——注册表里存的还是老地址（程序被挪过地方），开机时系统找不到文件就直接跳过；"
            "现在每次启动会自动把地址校正到当前程序，被「启动项」里禁掉的也会重新打开",
            "修：毛玻璃 / 液态玻璃下窗口四角还是直角；现在按圆角把窗口裁出来（Win11 交给系统圆角，老系统用区域裁剪），最大化时自动收回",
            "新手引导补了一页「自带的那几个模组」：三角洲情报、显示器滤镜、qBittorrent 都是随包的，怎么用、升级后还在不在都写了",
        ],
    ),
    (
        "2026-11-21 · v1.6.1",
        [
            "修：放着歌按 Alt+Z 换输出设备，声音还赖在原来那台设备上不放（别家音乐软件一按就切过去，咱们之前不跟）",
            "原因是系统默认设备换了，播放器那条音频流在开播那刻就绑死了老设备、不会自己迁移；"
            "现在换完设备会把音频输出重挂一次，播放位置接着走，中间不断歌",
            "顺带把「歌停了切设备、再点播放」也处理了：点播放时发现输出还挂着旧设备，会先迁过去再响",
            "注意：暂停/停止时换设备不会重建，省一次起播；只要还有声在放就一直跟得上",
        ],
    ),
    (
        "2026-11-21 · v1.6.0",
        [
            "模组里多了一个内置的「显示器滤镜」，不用另装软件：点「打开页面」就能调屏幕的伽马曲线 —— "
            "提亮、把暗部抬起来、偏暖偏冷、加对比",
            "18 个预设：去曝光、鲜艳、电影、高亮、柔和、游戏、阅读、暗部增强、偏暖、偏冷、冷色调、原亮冷调，"
            "外加三角洲推荐 1~5 和超级推荐，点一下就套上",
            "右边能自己细调：色温、亮度、对比度、伽马、S 曲线、红绿蓝增益；"
            "上面左边是原图、右边是滤镜，中间一道线对比，参数动一下预览跟着变",
            "只改显示器输出曲线，不注入游戏、不叠画面层；关窗或退出程序自动还原，另有「还原」按钮，"
            "托盘「全部还原」也会把它一起归位",
            "不用手动加模组：启动时会自动把这条内置模组补进列表（原来那条三角洲情报也照旧）",
        ],
    ),
    (
        "2026-11-21 · v1.5.1",
        [
            "桌面音乐悬浮条上显示当前歌名了：名字太长会自动省略成「……」，"
            "鼠标停在条上能看到全名",
            "音乐页那排平台按钮，选中颜色按平台走：网易云红、QQ音乐绿、酷狗蓝、酷我黄，"
            "一眼就知道现在在用哪家",
        ],
    ),
    (
        "2026-11-21 · v1.5.0",
        [
            "音乐多了条「桌面悬浮条」：它和窗口里那个灵动岛是两个东西 —— 这条是直接浮在屏幕上的独立小窗，"
            "主窗口收进托盘也照样在，玩游戏时不用切回来就能暂停 / 切歌",
            "有歌才出现，没歌不出；四个按钮：上一首、暂停 / 播放、下一首、关掉。"
            "点「关掉」只管当前这一首，换下一首会再出来",
            "按住左边那块把手能拖，拖到屏幕左 / 右边缘松开就自动贴边收成一条，"
            "鼠标碰一下自己展开，走开一会儿又收回去；右键还能直接贴左 / 贴右 / 不贴边",
            "音乐页顶部多了「悬浮条」开关：关掉就完全不出现；开着时位置、贴哪边都记着，下次启动还在",
            "工具页最下面那行「这里只放不常用的开关……」去掉了，页面上只留卡片本身",
        ],
    ),
    (
        "2026-11-21 · v1.4.0",
        [
            "新页「Steam 库」：直接读本机 Steam 的记录，装了什么、装在哪、玩了多久都列出来。"
            "不用填 SteamID —— 当前账号、库存数、已装 / 未装、总游玩时长自己认出来",
            "Steam 库照商店的样子做成一屏 4 列的封面卡片墙：封面、名字、AppID、体积、"
            "玩了多久、上次开是什么时候；装着的给「启动」，没装的给「查看商店」",
            "每张卡右键还能开商店页、打开安装目录、复制 AppID；顶上能搜名字或 AppID，也能勾「只看已装」",
            "名字和封面走 Steam 商店的公开接口，第一次进页面挨个补，补完存一份缓存，以后打开直接有；"
            "接口不通就先显示 AppID，页面不会卡住",
            "换台电脑也能用：Steam 装默认位置、装在别的盘都认；没装 Steam 或者从没登录过，"
            "页面会直说没找到登录记录，不会报错",
            "新页「Epic 喜加一」：本周正在免费和即将免费的都列出来，带封面、截止 / 开始时间和原价；"
            "点「立即领取」用默认浏览器打开商店页，这页不登录、不代领",
            "修：托盘图标不再被系统折进「其他图标」里 —— 启动时自动把系统托盘设置里的开关打开",
            "修：手机端「没有内容可发」那句提示，现在 10 秒自己消失，不用等下一句才刷掉",
            "修：新版本装包不再覆盖你的 config.json，也不会再塞测试壁纸进来，素材和配置照旧",
        ],
    ),
    (
        "2026-11-21 · v1.3.1",
        [
            "修：登录之后点「每日推荐」，右边一片空白、一首歌都不出。"
            "根子是网易云那个库升级后调用方式变了，老写法每次都被吃掉变成空列表；"
            "换成新写法后，登录账号的每日推荐正常出 30 首",
            "顺带把推荐页标题重复显示的「· 30 首 · 30 首」去掉，现在只显示一次",
            "QQ音乐 / 酷狗 / 酷我的登录改成内嵌浏览器的网页登录：窗口里直接扫码或输账号，登完点一下就写进来，不用自己再去复制 cookie（老的手动贴 cookie 还留着兜底）",
        ],
    ),
    (
        "2026-11-21 · v1.3.0",
        [
            "手机端出正式 App 了（燧镜手机版 v1.0.1）：同一个 WiFi 自己发现电脑，"
            "也能扫码、或者输 6 位配对码连上",
            "主页那个「剪贴板」方块改成「连接手机」：点开二维码和配对码一起给你，"
            "配对码 10 分钟换一次、用过就作废",
            "弹窗里多了「获取 App」，点一下直接打开手机版 apk 所在文件夹并选中它",
            "apk 跟着安装包一起下发，装完就在程序目录里；卸载时一起清掉",
            "设置 → 通用 新增「手机 · 剪贴板」：关掉手机就看不到电脑剪贴板，别的照常",
            "使用说明整篇重写：按画面 / 战斗 / 状态 / 情报 / 音乐 / 手机 / 模组 / 系统分组，"
            "另加手机版 App 怎么装、三种连法各怎么用",
        ],
    ),
    (
        "2026-11-20 · v1.2.1",
        [
            "设置里多了「壁纸」：开一下，整窗垫上一张图；也能自己选图，"
            "png / jpg / webp / bmp 都认，选进来会拷到 art 文件夹，原图不动",
            "铺满整窗、自动压暗降透明度，卡片上的字照旧清楚",
            "设置里多了「窗口外观」：经典（带系统标题栏）/ 毛玻璃，一键切，窗口位置和皮肤都不丢",
            "毛玻璃模式：没有系统标题栏、四角圆、能透出背后的桌面；"
            "接了 Windows 自己的亚克力磨砂，机器不支持就自动退回自绘玻璃，不会变难看",
            "毛玻璃的「背景模糊」0~40 自己拉，默认 18，松手就重画，拖的时候不卡",
            "毛玻璃下顶栏和底栏各压了一层暗色，透明边框的按钮也垫了淡底，字不再贴在图上糊",
            "顶栏那个「设置」不再占一排文字，挪到小衣服旁边换成齿轮图标，点开还是原来那套",
        ],
    ),
    (
        "2026-11-20 · v1.2.0",
        [
            "整个界面的颜色收进 24 个语义 token：底色、描边、文字、主色、圆角各归一段，以后改配色不用满地找色值",
            "内置三套皮肤：赛博青（就是原来那套）、暗金、纯黑；OLED 屏选纯黑，夜里看着不晃眼",
            "顶栏右上角新增小衣服按钮，设置里多了「外观」分类；点一下就换，立刻生效，不用重启",
            "皮肤只管颜色和圆角，不动布局。想自己做一套：打开皮肤文件夹，照「自定义示例.json」改完再导入",
            "分辨率卡片压成三行，低频操作用不到的（以当前为原生 / 自定义分辨率 / 刷新档位）收进右侧 ··· 菜单",
        ],
    ),
    (
        "2026-11-20 · v1.1.1",
        [
            "帧率读不到时，「帧率悬浮窗」后面冒出一个问号，点开就知道为什么、按什么顺序查",
            "问号自带本机自检：有没有管理员权限、MPO（多平面叠加）是不是开着、硬件加速 GPU 计划",
            "采集参数改了两处，切窗口 / 读图时不再反复重建跟踪会话（丢事件的主要原因）",
            "修：退出程序时，由它启动的模组跟着一起结束，不再留孤儿进程在后台跑",
        ],
    ),
    (
        "2026-11-20 · v1.1.0",
        [
            "三角洲情报挪进模组区，点卡片就开；顶栏去掉「三角洲」「关于」，按钮不再挤成一排",
            "砍掉哈夫币盈亏那一块（用不上），顺带不再加载内嵌浏览器，安装包瘦了一圈",
            "设置新增第六类「版本与更新」：检查更新 / 选择本地安装包，装完自动重开",
            "升级时配置、素材、模组、qBittorrent 种子和口琴曲谱全留着，不会被覆盖",
            "装之前先把内置模组的进程关掉，不会再出现「文件被占用装不上」",
        ],
    ),
    (
        "2026-11-19 下午",
        [
            "窗口拖窄不再把右边裁掉：顶栏自动折行、目标档位和大按钮各占一行、素材卡片按窗口宽自动 4 列 / 3 列",
            "截图 / 录屏 / 素材库的存放位置可以换盘或自选文件夹，换的时候能一键把旧素材搬过去",
            "新增内置模组 qBittorrent（BT 下载），随包分发，点模组直接开",
            "它的配置和缓存都在 bundled\\qbittorrent\\profile 里，不写 %APPDATA%、不装服务、不建快捷方式",
            "预置了中文界面、跳过首次许可弹窗和更新提示；删掉 bundled\\qbittorrent 就完全干净",
        ],
    ),
    (
        "2026-11-19 凌晨",
        [
            "素材页标时长和有没有声音：录像卡片写「0:20 · 有声 · 19.7 MB」，扫 mp4 头部读，不解码",
            "素材页顶部多了筛选：全部 / 只看截图 / 有声录像 / 静音录像 / 坏档",
            "坏档（缺 moov 打不开的）能一处挑出来清掉，卡片同时标「读取失败」和「坏档」",
            "筛选时顶部汇总改成「筛出 N 个 · X MB」，不再出现文件数按筛选、大小按全部的错数",
        ],
    ),
    (
        "2026-11-19 深夜",
        [
            "自动化「试运行」改成真预览：只打日志，一个动作都不执行；要真跑用「立即执行」（会先问一句）",
            "托盘右键前五项变成开关：帧率悬浮窗 / 回放缓冲 / 录屏 / 反作弊优化 / 密码窗，勾着＝开着，点一下就切",
            "模组「全部启动」：按列表从上到下依次起，前一个站住再起下一个；起不来自动再试一次，还不行才标红",
            "多屏：分辨率卡下面多了「作用屏幕」下拉，选哪块只切哪块，换屏自动重读那块屏的原生",
        ],
    ),
    (
        "2026-11-19 晚",
        [
            "模组健康检查：起不来会标红「启动失败」，悬停直接给原因（缺运行库 / 要管理员 / 被占用 / 下错版本）",
            "启动不再阻塞界面：等 1.2 秒再回头查，闪退也抓得住",
            "关于页加文件指纹（SHA256），被杀毒拦时能证明是同一份文件",
            "嘉豪模式会读接口和刷新率，直接判断你这台属于哪种情况（HDMI 高刷 → 换 DP）",
            "接两台以上显示器时，面板上明确写「这键只切主屏」",
            "网络测速可选加一个游戏服务器，单独一行，并判断「到服这段绕不绕」",
            "说明书补目录、30 秒上手、18 动作表、FAQ",
        ],
    ),
    (
        "2026-11-19 下午",
        [
            "素材库：缩略图、搜索、按天删、清理旧素材、占用汇总、坏文件标红",
            "网络测速升级：连续采样 12 秒，给抖动 / 丢包 / 一句人话判定",
            "录屏停止后自动删临时 wav，不再在素材目录堆音轨残渣",
        ],
    ),
    (
        "2026-11-19 上午",
        [
            "反作弊优化：一键优化 / 还原 / 自动守护",
            "帧率悬浮窗、每日密码悬浮窗（可拖、可穿透）",
            "截图 / 有声录屏 / 10 分钟回放，素材按日期归档",
            "音频输出一键切换（Alt+Z、托盘小喇叭、左上角提示卡）",
            "自带「手机音频接收」模组（蓝牙把手机声音放进电脑）",
            "自带 qBittorrent 模组（BT 下载，配置留在包内不碰系统目录）",
            "素材（截图/录屏）存放位置可换盘、可自选目录，切换时能一键搬家",
            "着色器缓存清理、一键推迟 Windows 更新",
            "热键每个都能单独开关，并显示真正生效的键",
            "设置分五类：通用 / 热键 / 显示 / 音频 / 高级",
            "托盘「全部还原」：出任何事一键回默认",
        ],
    ),
    (
        "2026-11-18",
        [
            "分辨率一键切换（含 4:3 / 16:10 档位、回原生、以当前为原生）",
            "模组框架：把别的程序和网页挂进来统一启停",
            "三角洲情报：今日密码、子弹自选包、假账榜、制造利润",
            "改名为「燧镜 / FLINT MIRROR」，标题两排按钮",
        ],
    ),
]


class ChangeLogDialog(QtWidgets.QDialog):
    """更新日志：只读，能滚动，标日期。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} 更新日志")
        self.resize(560, 520)
        self.setStyleSheet(qss())

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        head = QtWidgets.QLabel("都改了什么")
        head.setObjectName("Section")
        lay.addWidget(head)

        tip = QtWidgets.QLabel(
            "只记「用起来能感觉到」的改动，内部的整理不占篇幅。"
            "升级直接替换 App 整个文件夹，config.json 和素材别删。"
        )
        tip.setObjectName("Small")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        view = QtWidgets.QTextBrowser()
        view.setObjectName("LogView")
        view.setOpenExternalLinks(False)
        html = []
        for date, items in CHANGELOG:
            html.append(f'<div style="margin:14px 0 6px 0;color:#20ffe0;'
                        f'font-size:13px;font-weight:700">{date}</div>')
            for it in items:
                html.append(
                    f'<div style="margin:4px 0 4px 14px;color:#c9d2e0;'
                    f'font-size:12.5px;line-height:1.65">· {it}</div>'
                )
        view.setHtml(
            '<body style="background:#12161d">' + "".join(html) + "</body>"
        )
        lay.addWidget(view, 1)

        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        ok = QtWidgets.QPushButton("关闭")
        ok.setObjectName("Ghost")
        ok.setMinimumWidth(96)
        ok.clicked.connect(self.accept)
        btns.addWidget(ok)
        btns.addStretch(1)
        lay.addLayout(btns)


def file_fingerprint() -> dict:
    """当前运行的 exe（或源码）指纹：杀毒误报时用来证明是不是同一份文件。"""
    import hashlib
    import sys as _sys
    import time as _time

    try:
        target = Path(_sys.executable) if getattr(_sys, "frozen", False) else Path(__file__).resolve()
    except Exception:  # noqa: BLE001
        return {}
    try:
        if not target.exists():
            return {}
        st = target.stat()
        h = hashlib.sha256()
        with target.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        digest = h.hexdigest()
        return {
            "name": target.name,
            "mb": st.st_size / 1048576,
            "mtime": _time.strftime("%Y-%m-%d %H:%M", _time.localtime(st.st_mtime)),
            "sha16": digest[:16],
            "sha256": digest,
        }
    except Exception:  # noqa: BLE001
        return {}


class AboutDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"关于 {APP_NAME}")
        self.setFixedSize(400, 400)
        self.setStyleSheet(qss())

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(26, 22, 26, 18)
        lay.setSpacing(8)

        icon_label = QtWidgets.QLabel()
        icon_label.setPixmap(app_icon().pixmap(88, 88))
        icon_label.setAlignment(Qt.AlignCenter)
        lay.addWidget(icon_label)

        name = QtWidgets.QLabel(APP_NAME)
        name.setAlignment(Qt.AlignCenter)
        name.setStyleSheet("font-size: 20px; font-weight: 700; color: #f0f4fa;")
        lay.addWidget(name)

        ver = QtWidgets.QLabel(f"{APP_NAME_EN} · {APP_VERSION}")
        ver.setAlignment(Qt.AlignCenter)
        ver.setStyleSheet("color: #20ffe0; font-size: 12px; font-weight: 600;")
        lay.addWidget(ver)

        lay.addStretch(1)

        line = QtWidgets.QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background: #262d3a;")
        lay.addWidget(line)

        author = QtWidgets.QLabel(f"作者　{APP_AUTHOR}")
        author.setAlignment(Qt.AlignCenter)
        author.setStyleSheet("color: #9aa4b4; font-size: 12.5px;")
        lay.addWidget(author)

        lay.addSpacing(6)

        fp = file_fingerprint()
        if fp:
            self.fp_text = (
                f"{fp['name']} · {fp['mb']:.1f} MB · {fp['mtime']}\n"
                f"SHA256 {fp['sha16']}…"
            )
        else:
            self.fp_text = ""

        self.fp_label = QtWidgets.QLabel(self.fp_text or "读不到文件指纹")
        self.fp_label.setObjectName("Small")
        self.fp_label.setAlignment(Qt.AlignCenter)
        self.fp_label.setWordWrap(True)
        self.fp_label.setStyleSheet("color:#7b8494; font-size:11.5px;")
        lay.addWidget(self.fp_label)

        fp_tip = QtWidgets.QLabel("被杀毒拦、或反馈误报时，把上面两行发出来最快")
        fp_tip.setObjectName("Small")
        fp_tip.setAlignment(Qt.AlignCenter)
        fp_tip.setStyleSheet("color:#5f6b7c; font-size:11px;")
        lay.addWidget(fp_tip)

        lay.addSpacing(4)

        btns = QtWidgets.QHBoxLayout()
        btns.addStretch(1)
        b_log = QtWidgets.QPushButton("更新日志")
        b_log.setObjectName("Ghost")
        b_log.setMinimumWidth(96)
        b_log.clicked.connect(lambda: ChangeLogDialog(self).exec())
        btns.addWidget(b_log)
        btns.addSpacing(8)
        if getattr(self, "fp_text", ""):
            b_copy = QtWidgets.QPushButton("复制指纹")
            b_copy.setObjectName("Ghost")
            b_copy.setMinimumWidth(96)
            b_copy.clicked.connect(
                lambda: QtWidgets.QApplication.clipboard().setText(self.fp_text)
            )
            btns.addWidget(b_copy)
            btns.addSpacing(8)
        ok = QtWidgets.QPushButton("确定")
        ok.setObjectName("Ghost")
        ok.setMinimumWidth(96)
        ok.clicked.connect(self.accept)
        btns.addWidget(ok)
        btns.addStretch(1)
        lay.addLayout(btns)


class LogDialog(QtWidgets.QDialog):
    """日志面板：出问题时先看这里，不行就一键打包发出来。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        from core import diag as dg

        self._dg = dg
        self.setWindowTitle("运行日志")
        self.resize(860, 660)
        self.setStyleSheet(qss())

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)

        head = QtWidgets.QHBoxLayout()
        t = QtWidgets.QLabel("最近发生了什么")
        t.setObjectName("Section")
        head.addWidget(t)
        self.meta = QtWidgets.QLabel("")
        self.meta.setObjectName("Small")
        head.addWidget(self.meta)
        head.addStretch(1)
        self.state = QtWidgets.QLabel("正常")
        self.state.setObjectName("Badge")
        head.addWidget(self.state)
        lay.addLayout(head)

        self.view = QtWidgets.QPlainTextEdit()
        self.view.setObjectName("LogView")
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        lay.addWidget(self.view, 1)

        tip = QtWidgets.QLabel(
            "出错、卡顿、掉帧都可以导出诊断包：里面是日志 + 配置 + 环境信息，不含账号密码。"
        )
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        foot = QtWidgets.QHBoxLayout()
        foot.setSpacing(8)
        self.refresh_btn = QtWidgets.QPushButton("刷新")
        self.refresh_btn.setObjectName("Mini")
        self.refresh_btn.clicked.connect(self.reload)
        foot.addWidget(self.refresh_btn)

        self.dir_btn = QtWidgets.QPushButton("打开日志目录")
        self.dir_btn.setObjectName("Mini")
        self.dir_btn.clicked.connect(self._open_dir)
        foot.addWidget(self.dir_btn)

        self.clear_btn = QtWidgets.QPushButton("清空")
        self.clear_btn.setObjectName("Mini")
        self.clear_btn.clicked.connect(self._clear)
        foot.addWidget(self.clear_btn)
        foot.addStretch(1)

        self.export_btn = QtWidgets.QPushButton("导出诊断包")
        self.export_btn.setObjectName("Native")
        self.export_btn.setMinimumHeight(34)
        self.export_btn.clicked.connect(self._export)
        foot.addWidget(self.export_btn)

        close_btn = QtWidgets.QPushButton("关闭")
        close_btn.setObjectName("Ghost")
        close_btn.clicked.connect(self.accept)
        foot.addWidget(close_btn)
        lay.addLayout(foot)

        self.reload()

    def reload(self) -> None:
        text = self._dg.tail(400)
        self.view.setPlainText(text)
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())
        rows = len(text.splitlines())
        files = self._dg.log_files()
        name = files[-1].name if files else "—"
        self.meta.setText(f"　{rows} 行 · {name}")
        bad = ("ERROR", "CRITICAL", "Traceback")
        self.state.setText("有错误" if any(k in text for k in bad) else "正常")
        self.state.setObjectName("Badge" if not any(k in text for k in bad) else "BadgeDim")

    def _open_dir(self) -> None:
        import os
        import subprocess

        p = self._dg.log_dir()
        try:
            subprocess.Popen(["explorer", str(p)])
        except Exception:
            os.startfile(str(p))

    def _clear(self) -> None:
        self._dg.clear_logs()
        self.reload()

    def _export(self) -> None:
        try:
            path = self._dg.export_bundle()
        except Exception as exc:  # noqa: BLE001
            QtWidgets.QMessageBox.warning(self, "导出失败", str(exc))
            return
        self.reload()
        try:
            import subprocess

            subprocess.Popen(["explorer", "/select,", str(path)])
        except Exception:
            pass


# ---------------------------------------------------------------------------
# 设置
# ---------------------------------------------------------------------------
class _ReplaySaver(QtCore.QThread):
    """后台合成回放，避免界面卡住。"""

    done = QtCore.Signal(bool, str)

    def __init__(self, buf, minutes: int, parent=None):
        super().__init__(parent)
        self.buf = buf
        self.minutes = minutes

    def run(self):
        try:
            ok, msg = self.buf.save(self.minutes)
        except Exception as exc:  # noqa: BLE001
            ok, msg = False, f"合成异常：{exc}"
        self.done.emit(ok, msg)


class _DeltaWorker(QtCore.QThread):
    """后台抓数据，避免刷新时卡界面。

    mode="all" 抓全部；mode="codes" 只抓每日密码。
    """

    done = Signal(dict)

    def __init__(self, ds, mode="all"):
        super().__init__()
        self.ds = ds
        self.mode = mode

    def run(self):
        try:
            data = self.ds.refresh_codes() if self.mode == "codes" else self.ds.refresh()
            self.done.emit(data)
        except Exception as exc:  # noqa: BLE001
            self.done.emit({"errors": [f"{type(exc).__name__} {exc}"]})


class _BlockWorker(QtCore.QThread):
    """只抓三角洲情报里的某一块（手机端点「刷新」时用）。

    「刷新全部」要发五个请求、十几秒；手机上只想看一眼子弹价格时没必要等那么久。
    """

    done = Signal(str, dict)

    _JOBS = {
        "ammo": ("/chi/bullet-to-profit", "parse_ammo_bundle", "ammo"),
        "fake": ("/priceTop", "parse_price_top", "price_top"),
        "profit": ("/chi/profitRank", "parse_profit_rank", "profit"),
    }

    def __init__(self, ds, key):
        super().__init__()
        self.ds = ds
        self.key = key

    def run(self):
        try:
            data = self.ds.load_cache() or {}
            path, parser, field = self._JOBS[self.key]
            data[field] = getattr(df_intel, parser)(df_intel.fetch(path))
            data["fetched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            self.ds.save_cache(data)
            self.done.emit(self.key, data)
        except Exception as exc:  # noqa: BLE001
            self.done.emit(self.key, {"__error__": f"{type(exc).__name__} {exc}"})


def capture_fmt(n: int) -> str:
    """把字节数说成人话（素材页统计用）。"""
    n = int(n or 0)
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / 1024 / 1024:.1f} MB"
    return f"{n / 1024 / 1024 / 1024:.2f} GB"


# ---------------------------------------------------------------------------
# 素材打码：拖框 + 马赛克
# ---------------------------------------------------------------------------

MOSAIC_BLOCK = 13  # 马赛克颗粒（像素），越大越糊


class _MaskCanvas(QtWidgets.QWidget):
    """只负责画图和记录框：坐标都换算成图片像素。"""

    def __init__(self, image: QtGui.QImage, parent=None):
        super().__init__(parent)
        self.image = image
        self.rects: List[QtCore.QRect] = []   # 图片坐标系
        self._drag_from = None
        self._drag_to = None
        self._scale = 1.0
        self._off_x = 0
        self._off_y = 0
        self.setMouseTracking(True)
        self.setCursor(Qt.CrossCursor)
        self.setMinimumSize(360, 240)

    # ---- 坐标换算 ----
    def _fit(self) -> None:
        w, h = self.width(), self.height()
        iw, ih = self.image.width(), self.image.height()
        if iw <= 0 or ih <= 0:
            return
        self._scale = min(w / iw, h / ih)
        self._off_x = int((w - iw * self._scale) / 2)
        self._off_y = int((h - ih * self._scale) / 2)

    def _to_image(self, pt: QtCore.QPoint) -> QtCore.QPoint:
        x = (pt.x() - self._off_x) / (self._scale or 1)
        y = (pt.y() - self._off_y) / (self._scale or 1)
        x = max(0, min(self.image.width() - 1, int(x)))
        y = max(0, min(self.image.height() - 1, int(y)))
        return QtCore.QPoint(x, y)

    def _to_widget(self, rect: QtCore.QRect) -> QtCore.QRect:
        return QtCore.QRect(
            int(rect.left() * self._scale + self._off_x),
            int(rect.top() * self._scale + self._off_y),
            int(rect.width() * self._scale),
            int(rect.height() * self._scale),
        )

    # ---- 事件 ----
    def mousePressEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self._drag_from = self._to_image(ev.position().toPoint())
            self._drag_to = self._drag_from
            self.update()

    def mouseMoveEvent(self, ev) -> None:
        if self._drag_from is not None:
            self._drag_to = self._to_image(ev.position().toPoint())
            self.update()

    def mouseReleaseEvent(self, ev) -> None:
        if self._drag_from is None:
            return
        to = self._to_image(ev.position().toPoint())
        rect = QtCore.QRect(self._drag_from, to).normalized()
        self._drag_from = self._drag_to = None
        if rect.width() >= 6 and rect.height() >= 6:
            self.rects.append(rect)
        self.update()

    # ---- 绘制 ----
    def paintEvent(self, ev) -> None:
        self._fit()
        painter = QtGui.QPainter(self)
        painter.fillRect(self.rect(), QtGui.QColor("#0b0e13"))
        target = QtCore.QRect(
            self._off_x, self._off_y,
            int(self.image.width() * self._scale),
            int(self.image.height() * self._scale),
        )
        painter.drawImage(target, self.image)

        def draw(rect, active=False):
            wr = self._to_widget(rect)
            painter.fillRect(wr, QtGui.QColor(255, 90, 90, 90 if active else 60))
            painter.setPen(QtGui.QPen(QtGui.QColor("#ff6b6b"), 2))
            painter.drawRect(wr)

        for r in self.rects:
            draw(r)
        if self._drag_from is not None and self._drag_to is not None:
            draw(QtCore.QRect(self._drag_from, self._drag_to).normalized(), True)
        painter.setPen(QtGui.QPen(QtGui.QColor("#8d97a8"), 1))
        painter.drawRect(target)
        painter.end()

    def undo(self) -> bool:
        if self.rects:
            self.rects.pop()
            self.update()
            return True
        return False

    def clear(self) -> None:
        self.rects.clear()
        self.update()


class MaskDialog(QtWidgets.QDialog):
    """给截图打码：拖几块 → 马赛克 → 另存为 原名_打码.png。"""

    def __init__(self, path: Path, parent=None):
        super().__init__(parent)
        self.path = Path(path)
        self.image = QtGui.QImage(str(self.path))
        self.setWindowTitle(f"打码 · {self.path.name}")
        self.resize(880, 640)
        self.setStyleSheet(qss())

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(8)

        tip = QtWidgets.QLabel(
            "在图上按住左键拖一块要遮掉的区域（可以拖多块），点「打码并保存」。"
            "原图不会被改，另存一张「原名_打码.png」。"
        )
        tip.setObjectName("Small")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        if self.image.isNull():
            lay.addWidget(QtWidgets.QLabel("这个文件打不开（可能不是图片，或者已经损坏）"))
            self.canvas = None
        else:
            self.canvas = _MaskCanvas(self.image, self)
            lay.addWidget(self.canvas, 1)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        undo = QtWidgets.QPushButton("撤销一块")
        undo.setObjectName("Ghost")
        undo.clicked.connect(lambda: self.canvas and self.canvas.undo())
        row.addWidget(undo)

        clear = QtWidgets.QPushButton("全部清掉")
        clear.setObjectName("Ghost")
        clear.clicked.connect(lambda: self.canvas and self.canvas.clear())
        row.addWidget(clear)

        row.addStretch(1)
        cancel = QtWidgets.QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.setMinimumWidth(88)
        cancel.clicked.connect(self.reject)
        row.addWidget(cancel)

        ok = QtWidgets.QPushButton("打码并保存")
        ok.setMinimumWidth(120)
        ok.clicked.connect(self._apply)
        row.addWidget(ok)
        lay.addLayout(row)

    def _apply(self) -> None:
        if self.canvas is None or not self.canvas.rects:
            QtWidgets.QMessageBox.information(self, "还没框", "先在图上拖一块要遮住的区域")
            return

        img = self.image.convertToFormat(QtGui.QImage.Format_RGB32)
        painter = QtGui.QPainter(img)
        for rect in self.canvas.rects:
            r = rect.intersected(img.rect())
            if r.width() < 2 or r.height() < 2:
                continue
            # 先把这块抠出来缩到很小再放大：标准马赛克
            piece = img.copy(r)
            small = piece.scaled(
                max(1, r.width() // MOSAIC_BLOCK),
                max(1, r.height() // MOSAIC_BLOCK),
                Qt.IgnoreAspectRatio,
                Qt.FastTransformation,
            )
            big = small.scaled(r.width(), r.height(), Qt.IgnoreAspectRatio, Qt.FastTransformation)
            painter.drawImage(r.topLeft(), big)
        painter.end()

        out = self.path.with_name(self.path.stem + "_打码.png")
        if not img.save(str(out), "PNG"):
            QtWidgets.QMessageBox.warning(self, "存不上", f"写不进：{out}")
            return
        self.saved_path = out
        self.accept()


class _ThumbLoader(QtCore.QObject):
    """后台抽帧完成的通知（主线程里接收）。"""

    done = Signal(str, str)


class _ThumbJob(QtCore.QRunnable):
    """用内置 ffmpeg 从录像里抽第一帧，抽不到就留空，不阻塞界面。"""

    def __init__(self, loader: "_ThumbLoader", src: Path, out: Path):
        super().__init__()
        self.loader = loader
        self.src = src
        self.out = out

    def run(self) -> None:
        ok = ""
        try:
            ff = str(replay.ffmpeg_path())
            if Path(ff).exists():
                self.out.parent.mkdir(parents=True, exist_ok=True)
                for ss in ("1", "0"):
                    if self.out.exists():
                        break
                    subprocess.run(
                        [
                            ff, "-y", "-ss", ss, "-i", str(self.src),
                            "-frames:v", "1", "-vf", "scale=316:-2", "-q:v", "5",
                            str(self.out),
                        ],
                        capture_output=True,
                        timeout=8,
                        creationflags=0x08000000,
                    )
                    if self.out.exists() and self.out.stat().st_size > 0:
                        ok = str(self.out)
                        break
        except Exception:  # noqa: BLE001
            ok = ""
        try:
            self.loader.done.emit(str(self.src), ok)
        except RuntimeError:
            pass


class MediaPage(QtWidgets.QWidget):
    """素材页：按日期分组看截图/录像，双击打开，右键删除；支持搜索与按日期清理。"""

    COLS = 4
    CARD_W = 176
    THUMB_DIR = ".thumbs"

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("Root")
        self._cols = self.COLS
        self._cols_pending = None
        self._keyword = ""
        self._thumb_labels = {}
        self._loader = _ThumbLoader(self)
        self._loader.done.connect(self._thumb_ready)
        self._pool = QtCore.QThreadPool(self)
        self._pool.setMaxThreadCount(2)
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self.reload)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 12)
        lay.setSpacing(10)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(10)
        title = QtWidgets.QLabel("素材")
        title.setStyleSheet("font-size:19px;font-weight:700;color:#f0f4fa;")
        head.addWidget(title)
        head.addSpacing(12)
        self.sum_lbl = QtWidgets.QLabel("")
        self.sum_lbl.setObjectName("Hint")
        head.addWidget(self.sum_lbl)
        head.addStretch(1)

        btn_refresh = QtWidgets.QPushButton("刷新")
        btn_refresh.setObjectName("Mini")
        btn_refresh.clicked.connect(self.reload)
        head.addWidget(btn_refresh)
        lay.addLayout(head)

        # 第二行：筛选 + 搜索（可伸缩）+ 两个操作按钮，窗口窄时先压搜索框
        head2 = QtWidgets.QHBoxLayout()
        head2.setSpacing(8)

        self.kind_filter = QtWidgets.QComboBox()
        self.kind_filter.setFixedWidth(112)
        self.kind_filter.setFixedHeight(28)
        self.kind_filter.addItem("全部素材", "all")
        self.kind_filter.addItem("只看截图", "shot")
        self.kind_filter.addItem("有声录像", "audio")
        self.kind_filter.addItem("静音录像", "silent")
        self.kind_filter.addItem("坏档", "broken")
        self.kind_filter.setToolTip("带声音的优先看这里：有声录像")
        self.kind_filter.currentIndexChanged.connect(lambda _i: self.reload())
        head2.addWidget(self.kind_filter)

        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("搜文件名 / 日期 / 有声")
        self.search.setClearButtonEnabled(True)
        self.search.setMinimumWidth(110)
        self.search.textChanged.connect(self._on_search)
        head2.addWidget(self.search, 1)

        btn_dir = QtWidgets.QPushButton("打开目录")
        btn_dir.setObjectName("Mini")
        btn_dir.setToolTip("在资源管理器里打开素材目录")
        btn_dir.clicked.connect(self.open_dir)
        head2.addWidget(btn_dir)
        self.btn_dir = btn_dir

        btn_old = QtWidgets.QPushButton("清理旧素材")
        btn_old.setObjectName("Mini")
        btn_old.setToolTip("按天数批量删：默认 30 天以前的")
        btn_old.clicked.connect(self._clean_old)
        head2.addWidget(btn_old)
        lay.addLayout(head2)

        tip = QtWidgets.QLabel(
            "按「素材 / 类型 / 日期」归档。双击打开，右键可删除或在文件夹中定位；"
            "每行右边的「删这一天」会整组清掉当天的素材。"
        )
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        tip_card = QtWidgets.QFrame()
        tip_card.setObjectName("Card")
        tip_lay = QtWidgets.QVBoxLayout(tip_card)
        tip_lay.setContentsMargins(16, 12, 16, 12)
        tip_lay.setSpacing(0)
        tip_lay.addWidget(tip)
        lay.addWidget(tip_card)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.inner = QtWidgets.QWidget()
        self.inner.setObjectName("Root")
        self.box = QtWidgets.QVBoxLayout(self.inner)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(10)
        self.scroll.setWidget(self.inner)
        lay.addWidget(self.scroll, 1)

        foot = QtWidgets.QHBoxLayout()
        foot.addStretch(1)
        back = QtWidgets.QPushButton("← 返回首页")
        back.setObjectName("Ghost")
        back.clicked.connect(self.win.show_home)
        foot.addWidget(back)
        lay.addLayout(foot)

        self.reload()

    # ------------------------------------------------------------ 搜索
    def _on_search(self, text: str) -> None:
        self._keyword = (text or "").strip().lower()
        self._search_timer.start(260)

    # ------------------------------------------------------------ 数据
    def _sweep_thumbs(self) -> None:
        """缓存里源文件已经不在了的缩略图，删掉。"""
        try:
            cache = capture.media_root() / self.THUMB_DIR
            if not cache.exists():
                return
            stems = set()
            for d in capture.list_by_day():
                for it in d["items"]:
                    stems.add(it["path"].stem)
            for f in cache.glob("*.jpg"):
                stem = f.name.rsplit("_", 1)[0]
                if stem not in stems:
                    f.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass

    def reload(self) -> None:
        try:
            self.btn_dir.setToolTip("在资源管理器里打开：\n" + str(capture.media_root()))
        except Exception:  # noqa: BLE001
            pass
        self._sweep_thumbs()
        while self.box.count():
            item = self.box.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)  # 立刻从布局摘掉，否则新卡片会压在旧卡片上
                widget.deleteLater()
        self._thumb_labels.clear()

        days = capture.list_by_day()
        mode = self.kind_filter.currentData() or "all"

        def _pass(it, date_key: str) -> bool:
            if mode == "shot" and it.get("is_video"):
                return False
            if mode in ("audio", "silent", "broken"):
                if not it.get("is_video"):
                    return False
                if mode == "audio" and it.get("has_audio") is not True:
                    return False
                if mode == "silent" and it.get("has_audio") is not False:
                    return False
                if mode == "broken" and capture.fmt_duration(it.get("duration")):
                    return False
            if not self._keyword:
                return True
            kw = self._keyword
            if kw in it["name"].lower() or kw in date_key or kw in it["kind"]:
                return True
            audio = it.get("has_audio")
            if kw in ("有声", "声音", "带声音", "audio") and audio is True:
                return True
            if kw in ("静音", "无声", "没声音", "silent") and audio is False:
                return True
            return False

        if mode != "all" or self._keyword:
            days = [
                {"date": d["date"], "items": [
                    it for it in d["items"] if _pass(it, d["date"])
                ]}
                for d in days
            ]
            days = [d for d in days if d["items"]]

        total_bytes = 0
        try:
            for d in capture.list_by_day():
                for it in d["items"]:
                    total_bytes += int(it.get("size") or 0)
        except Exception:  # noqa: BLE001
            total_bytes = 0

        filtered = mode != "all" or bool(self._keyword)
        if not days:
            self.sum_lbl.setText(f"共 {capture_fmt(total_bytes)}" if filtered else "")
            if self._keyword:
                empty_text = "没搜到匹配的素材，换个词试试。"
            elif mode != "all":
                empty_text = "这个分类下还没有素材，切回「全部素材」看看。"
            else:
                empty_text = (
                    "还没有素材。用主界面的「截图」按钮或 Ctrl+Alt+S 先截一张，"
                    "文件会自动进 素材\\截图\\日期 里。"
                )
            empty = QtWidgets.QLabel(empty_text)
            empty.setObjectName("Hint")
            empty.setWordWrap(True)
            empty_card = QtWidgets.QFrame()
            empty_card.setObjectName("Card")
            empty_lay = QtWidgets.QVBoxLayout(empty_card)
            empty_lay.setContentsMargins(16, 14, 16, 14)
            empty_lay.setSpacing(0)
            empty_lay.addWidget(empty)
            self.box.addWidget(empty_card)
            self.box.addStretch(1)
            return

        total = sum(len(d["items"]) for d in days)
        if filtered:
            shown = sum(int(it.get("size") or 0) for d in days for it in d["items"])
            self.sum_lbl.setText(f"筛出 {total} 个 · {capture_fmt(shown)}")
        else:
            self.sum_lbl.setText(f"{total} 个 · {capture_fmt(total_bytes)}")

        for day in days:
            row = QtWidgets.QHBoxLayout()
            day_lbl = QtWidgets.QLabel(day["date"])
            day_lbl.setStyleSheet("font-size:13.5px;font-weight:700;color:#20ffe0;")
            row.addWidget(day_lbl)
            day_bytes = sum(int(it.get("size") or 0) for it in day["items"])
            count_lbl = QtWidgets.QLabel(
                f"{len(day['items'])} 个 · {capture_fmt(day_bytes)}"
            )
            count_lbl.setObjectName("Hint")
            row.addWidget(count_lbl)
            row.addStretch(1)
            kill_btn = QtWidgets.QPushButton("删这一天")
            kill_btn.setObjectName("Mini")
            kill_btn.setToolTip(f"把 {day['date']} 这天的素材全删掉（会再确认一次）")
            kill_btn.clicked.connect(lambda _c=False, d=day: self._delete_day(d))
            row.addWidget(kill_btn)
            holder = QtWidgets.QWidget()
            holder.setLayout(row)
            self.box.addWidget(holder)

            grid_host = QtWidgets.QWidget()
            grid = QtWidgets.QGridLayout(grid_host)
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(8)
            cols = max(1, self._cols)
            for i, it in enumerate(day["items"]):
                grid.addWidget(self._tile(it), i // cols, i % cols)
            for c in range(cols):
                grid.setColumnStretch(c, 1)
            self.box.addWidget(grid_host)

        self.box.addStretch(1)

    def _cols_for_width(self) -> int:
        avail = self.width() - 24
        try:
            avail = min(avail, self.scroll.viewport().width() + 4)
        except Exception:  # noqa: BLE001
            pass
        return max(1, min(self.COLS, avail // (self.CARD_W + 8)))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        want = self._cols_for_width()
        if want == self._cols or self._cols_pending is not None:
            return
        self._cols = want
        # 拖窗口时别每像素都重建，停手 150ms 再排
        self._cols_pending = QtCore.QTimer.singleShot(150, self._after_resize_cols)

    def _after_resize_cols(self) -> None:
        self._cols_pending = None
        self.reload()

    def open_dir(self) -> None:
        root = capture.media_root()
        root.mkdir(parents=True, exist_ok=True)
        os.startfile(str(root))

    # ------------------------------------------------------------ 缩略图
    def _thumb_out(self, path: Path) -> Path:
        try:
            stamp = int(path.stat().st_mtime)
        except OSError:
            stamp = 0
        return capture.media_root() / self.THUMB_DIR / f"{path.stem}_{stamp}.jpg"

    def _thumb(self, path: Path, label=None):
        """图片直接读；视频先给占位，再丢后台抽帧，抽到就换上来。"""
        width, height = 158, 86
        if path.suffix.lower() in (".png", ".jpg", ".jpeg"):
            image = QtGui.QImage(str(path))
            if image.isNull():
                broken = QtGui.QPixmap(158, 86)
                broken.fill(QtGui.QColor("#151b24"))
                painter = QtGui.QPainter(broken)
                painter.setPen(QtGui.QColor("#ff8a6b"))
                painter.drawText(broken.rect(), QtCore.Qt.AlignCenter, "读取失败")
                painter.end()
                return broken
            return QtGui.QPixmap.fromImage(image).scaled(
                width, height,
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )

        cached = self._thumb_out(path)
        if cached.exists() and cached.stat().st_size > 0:
            pixmap = QtGui.QPixmap(str(cached))
            if not pixmap.isNull():
                return pixmap.scaled(
                    width, height, QtCore.Qt.KeepAspectRatioByExpanding,
                    QtCore.Qt.SmoothTransformation,
                )

        if label is not None:
            self._thumb_labels.setdefault(str(path), []).append(label)
            self._pool.start(_ThumbJob(self._loader, path, cached))

        pixmap = QtGui.QPixmap(width, height)
        pixmap.fill(QtGui.QColor("#151b24"))
        painter = QtGui.QPainter(pixmap)
        painter.setPen(QtGui.QColor("#20ffe0"))
        painter.drawText(pixmap.rect(), QtCore.Qt.AlignCenter, "录像")
        painter.end()
        return pixmap

    def _thumb_ready(self, src: str, jpg: str) -> None:
        labels = self._thumb_labels.pop(src, None)
        if not labels:
            return
        if not jpg or not Path(jpg).exists():
            # 抽不出帧 = 这段录像坏了（录制中途断了，没有 moov）
            broken = QtGui.QPixmap(158, 86)
            broken.fill(QtGui.QColor("#151b24"))
            painter = QtGui.QPainter(broken)
            painter.setPen(QtGui.QColor("#ff8a6b"))
            painter.drawText(broken.rect(), QtCore.Qt.AlignCenter, "读取失败")
            painter.end()
            for label in labels:
                try:
                    label.setPixmap(broken)
                    label.setToolTip("这段录像没写完（录制中途断了），打不开也修不好")
                except RuntimeError:
                    pass
            return
        pixmap = QtGui.QPixmap(jpg)
        if pixmap.isNull():
            return
        pixmap = pixmap.scaled(
            158, 86, QtCore.Qt.KeepAspectRatioByExpanding,
            QtCore.Qt.SmoothTransformation,
        )
        for label in labels:
            try:
                label.setPixmap(pixmap)
            except RuntimeError:
                pass

    def _meta_text(self, item) -> str:
        """录像给时长和声音，截图给类别和大小。"""
        kind = item.get("kind") or ""
        size = item.get("size_text") or ""
        if item.get("is_video"):
            dur = capture.fmt_duration(item.get("duration"))
            if not dur:
                return f"坏档 · {size}"
            audio = item.get("has_audio")
            if audio:
                return f"{dur} · 有声 · {size}"
            if audio is False:
                return f"{dur} · 静音 · {size}"
            return f"{dur} · {size}"
        return f"{kind} · {size}"

    def _tile(self, item) -> QtWidgets.QFrame:
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        card.setFixedSize(176, 142)

        box = QtWidgets.QVBoxLayout(card)
        box.setContentsMargins(9, 9, 9, 9)
        box.setSpacing(4)

        thumb = QtWidgets.QLabel()
        thumb.setAlignment(QtCore.Qt.AlignCenter)
        thumb.setFixedHeight(88)
        thumb.setPixmap(self._thumb(item["path"], thumb))
        box.addWidget(thumb)

        name = QtWidgets.QLabel(item["name"])
        name.setObjectName("Small")
        box.addWidget(name)

        meta = QtWidgets.QLabel(self._meta_text(item))
        meta.setObjectName("Hint")
        box.addWidget(meta)

        tip = str(item["path"])
        dur = capture.fmt_duration(item.get("duration"))
        if item.get("is_video"):
            tip += "\n时长 " + (dur or "读不出来")
            audio = item.get("has_audio")
            tip += " · " + ("有声音" if audio else ("没有音轨" if audio is False else "未知"))
        card.setToolTip(tip)
        card.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        card.customContextMenuRequested.connect(
            lambda _pos, it=item: self._menu(it)
        )
        card.mouseDoubleClickEvent = lambda _e, path=item["path"]: self._open(path)
        return card

    # ------------------------------------------------------------ 操作
    def _open(self, path: Path) -> None:
        try:
            os.startfile(str(path))
        except Exception as exc:  # noqa: BLE001
            self.win.toast("打不开：" + str(exc)[:40], False)

    def _menu(self, item) -> None:
        menu = QtWidgets.QMenu(self)
        menu.setStyleSheet(qss())
        menu.addAction("打开", lambda: self._open(item["path"]))
        menu.addAction("在文件夹中显示", lambda: self._reveal(item["path"]))
        suffix = Path(item.get("path", "")).suffix.lower()
        if suffix in (".png", ".jpg", ".jpeg", ".bmp", ".webp"):
            menu.addSeparator()
            menu.addAction(
                "打码（遮住账号 / 昵称）", lambda: self._mask(item["path"])
            )
        menu.addSeparator()
        menu.addAction("删除", lambda: self._delete(item))
        menu.exec(QtGui.QCursor.pos())

    def _mask(self, path: Path) -> None:
        dlg = MaskDialog(path, self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        out = getattr(dlg, "saved_path", None)
        self.reload()
        if out is not None:
            self.win.toast(f"已生成 {out.name}（原图还在）")
            self._reveal(out)

    def _reveal(self, path: Path) -> None:
        try:
            subprocess.Popen(["explorer", "/select,", str(path)])
        except Exception:  # noqa: BLE001
            pass

    def _delete(self, item) -> None:
        answer = QtWidgets.QMessageBox.question(
            self,
            "删除素材",
            f"确定删除这个文件吗？\n{item['name']}",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return
        try:
            item["path"].unlink()
        except OSError as exc:
            self.win.toast("删不掉：" + str(exc)[:40], False)
            return
        self.reload()
        self.win.toast("已删除")

    def _delete_day(self, day: dict) -> None:
        total = sum(int(it.get("size") or 0) for it in day["items"])
        answer = QtWidgets.QMessageBox.question(
            self,
            "删一整天的素材",
            f"{day['date']} 这天有 {len(day['items'])} 个文件，共 "
            f"{capture_fmt(total)}。\n全部删掉？删了就找不回来了。",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return
        failed = 0
        for it in day["items"]:
            try:
                it["path"].unlink()
            except OSError:
                failed += 1
        self.reload()
        if failed:
            self.win.toast(f"有 {failed} 个删不掉（可能正被占用）", False)
        else:
            self.win.toast(f"{day['date']} 已清空")

    def _clean_old(self) -> None:
        days = capture.list_by_day()
        if not days:
            self.win.toast("还没有素材")
            return
        value, ok = QtWidgets.QInputDialog.getInt(
            self, "清理旧素材", "删掉多少天以前的？（0 = 全部删）",
            30, 0, 3650, 1,
        )
        if not ok:
            return
        cut = time.time() - value * 86400
        victims = [
            it for d in days for it in d["items"] if float(it.get("mtime") or 0) < cut
        ]
        if not victims:
            self.win.toast(f"{value} 天以前没有素材")
            return
        size = sum(int(it.get("size") or 0) for it in victims)
        answer = QtWidgets.QMessageBox.question(
            self,
            "清理旧素材",
            f"将删除 {len(victims)} 个文件，共 {capture._fmt_size(size)}。\n继续？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return
        failed = 0
        for it in victims:
            try:
                it["path"].unlink()
            except OSError:
                failed += 1
        self.reload()
        self.win.toast(
            f"清掉 {len(victims) - failed} 个" + (f"，{failed} 个占用中" if failed else "")
        )


class DeltaPage(QtWidgets.QWidget):
    """三角洲情报页：密码门 / 子弹 / 假账榜 / 制造利润。

    它和主页住在同一个窗口里，点顶部「三角洲」切过来，再点一下切回主页。
    数据来自 shushu.fan 的公开页面，只在点「刷新」时联网，平时只读本地缓存；
    抓不到就继续显示上一次成功的数据。
    """

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setStyleSheet(qss())
        self.ds = df_intel.DataSource(app_dir() / "delta_cache.json")
        self.data = self.ds.load_cache() or {}
        self._worker = None

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        head = QtWidgets.QHBoxLayout()
        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(2)
        t = QtWidgets.QLabel("三角洲情报")
        t.setObjectName("Title")
        s = QtWidgets.QLabel("密码门 · 子弹 · 假账榜 · 制造利润　｜　数据来源 shushu.fan")
        s.setObjectName("Sub")
        titles.addWidget(t)
        titles.addWidget(s)
        head.addLayout(titles)
        head.addStretch(1)

        self.update_lbl = QtWidgets.QLabel("点「刷新」拉数据")
        self.update_lbl.setObjectName("Small")
        head.addWidget(self.update_lbl)

        self.refresh_btn = QtWidgets.QPushButton("刷新")
        self.refresh_btn.setFixedHeight(30)
        self.refresh_btn.setMinimumWidth(86)
        self.refresh_btn.setStyleSheet(
            "QPushButton{background:#17c8a8;border:none;color:#04120f;font-weight:700;"
            "font-size:12.5px;padding:0 16px;border-radius:8px;}"
            "QPushButton:hover{background:#24e3be;}"
            "QPushButton:pressed{background:#12b295;}"
            "QPushButton:disabled{background:#171c25;color:#4d5563;}"
        )
        self.refresh_btn.setToolTip("只在你点它的时候联网，平时不发任何请求")
        self.refresh_btn.clicked.connect(self.do_refresh)
        head.addWidget(self.refresh_btn)
        lay.addLayout(head)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setStyleSheet(
            "QTabWidget::pane{border:1px solid #232a36;border-radius:10px;background:#0b0f15;}"
            "QTabBar::tab{background:#151b24;color:#9aa4b4;padding:7px 16px;margin-right:4px;"
            "border:1px solid #232a36;border-bottom:none;"
            "border-top-left-radius:8px;border-top-right-radius:8px;font-size:12.5px;}"
            "QTabBar::tab:selected{background:#0b0f15;color:#20ffe0;border-color:#1c4a43;}"
        )
        self.pages = {}
        for key, title in (
            ("pwd", "今日密码"),
            ("ammo", "子弹自选包"),
            ("fake", "假账榜"),
            ("profit", "制造利润"),
        ):
            scroll, box = self._make_page()
            self.pages[key] = (scroll, box)
            self.tabs.addTab(scroll, title)
        lay.addWidget(self.tabs, 1)

        foot = QtWidgets.QHBoxLayout()
        tip = QtWidgets.QLabel("抓不到数据时保留上一次的结果，不会覆盖成空。")
        tip.setObjectName("Hint")
        foot.addWidget(tip)
        foot.addStretch(1)
        back = QtWidgets.QPushButton("← 返回首页")
        back.setObjectName("Ghost")
        back.setMinimumWidth(104)
        back.clicked.connect(self.win.show_home)
        foot.addWidget(back)
        lay.addLayout(foot)

        self.render_all()
        if self.data.get("fetched_at"):
            self.update_lbl.setText("更新于 " + self.data["fetched_at"])

        # 每日密码：跨天自动更新（60 秒心跳只比对日期，不发请求）
        self._auto_fail = 0
        self._last_auto = 0.0
        self._auto_timer = QTimer(self)
        self._auto_timer.timeout.connect(self._auto_tick)
        self._auto_timer.start(60000)
        QTimer.singleShot(1500, self._auto_tick)

    # ------------------------------------------------------------ 基础
    def _make_page(self):
        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        inner = QtWidgets.QWidget()
        box = QtWidgets.QVBoxLayout(inner)
        box.setContentsMargins(14, 14, 14, 14)
        box.setSpacing(9)
        scroll.setWidget(inner)
        return scroll, box

    def _reset(self, key):
        """清空某页内容（整块换一个新 widget，省得逐个删）。"""
        scroll = self.pages[key][0]
        inner = QtWidgets.QWidget()
        box = QtWidgets.QVBoxLayout(inner)
        box.setContentsMargins(14, 14, 14, 14)
        box.setSpacing(9)
        scroll.setWidget(inner)
        self.pages[key] = (scroll, box)
        return box

    def _table(self, headers, widths=None):
        t = QtWidgets.QTableWidget()
        t.setColumnCount(len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.verticalHeader().setVisible(False)
        t.setShowGrid(False)
        t.setAlternatingRowColors(True)
        t.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        t.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        t.horizontalHeader().setStretchLastSection(True)
        t.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        t.setStyleSheet(
            "QTableWidget{background:#0b0f15;border:1px solid #232a36;border-radius:8px;"
            "alternate-background-color:#101620;color:#dbe3ee;}"
            "QHeaderView::section{background:#151b24;color:#9aa4b4;border:none;"
            "padding:6px 8px;font-size:12px;}"
            "QTableWidget::item{padding:5px 8px;}"
            "QTableWidget::item:selected{background:#1b2836;color:#eaf2ff;}"
            "QTableWidget{selection-background-color:#1b2836;}"
        )
        if widths:
            for i, w in enumerate(widths):
                t.setColumnWidth(i, w)
        return t

    @staticmethod
    def _empty_tip(text):
        lb = QtWidgets.QLabel(text)
        lb.setObjectName("Small")
        lb.setAlignment(Qt.AlignCenter)
        lb.setWordWrap(True)
        return lb

    # ------------------------------------------------------------ 渲染
    def render_all(self):
        self.render_pwd()
        self.render_ammo()
        self.render_fake()
        self.render_profit()

    def render_pwd(self):
        box = self._reset("pwd")
        block = (self.data or {}).get("passwords") or {}
        maps = block.get("maps") or {}
        if not maps:
            box.addWidget(self._empty_tip("还没有数据，点右上角「刷新」"))
            box.addStretch(1)
            return

        # 状态条：这份密码是哪天的、是不是今日
        card_date = str(block.get("codes_date") or "")
        today = time.strftime("%Y-%m-%d")
        clock_now = time.strftime("%H:%M")
        if card_date == today:
            text = f"今日 {card_date[5:]}　更新 {block.get('checked_at', '')[11:] or '—'}"
            color = "#7ee787"
        elif card_date:
            text = f"昨日 {card_date[5:]}　⚠ 可能已失效，正在等今日密码"
            color = "#ffb86b"
        else:
            text = "还没有今日密码"
            color = "#ff8a8a"

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(10)
        status = QtWidgets.QLabel(text)
        status.setStyleSheet(f"color:{color};font-size:12.5px;font-weight:600;")
        bar.addWidget(status)
        bar.addStretch(1)

        auto = QtWidgets.QCheckBox("每天自动更新")
        auto.setStyleSheet(
            "QCheckBox{color:#9aa4b4;font-size:12.5px;}"
            "QCheckBox::indicator{width:14px;height:14px;border:1px solid #2c3543;"
            "border-radius:4px;background:#151b24;}"
            "QCheckBox::indicator:hover{border-color:#20ffe0;}"
            "QCheckBox::indicator:checked{background:#17c8a8;border-color:#17c8a8;}"
        )
        auto.setToolTip("打开后：跨天（过了 00:02）自动抓当天密码；关掉就只在你点刷新时联网")
        auto.setChecked(bool(getattr(self.win.cfg, "pwd_auto", True)))
        auto.toggled.connect(self._on_auto_toggled)
        bar.addWidget(auto)

        only = QtWidgets.QPushButton("只刷密码")
        only.setObjectName("Mini")
        only.setToolTip("只抓密码这一项，比整体刷新快")
        only.clicked.connect(self.refresh_codes)
        bar.addWidget(only)
        box.addLayout(bar)

        head = QtWidgets.QLabel("点卡片直接复制密码")
        head.setObjectName("Small")
        box.addWidget(head)

        grid = QtWidgets.QGridLayout()
        grid.setSpacing(9)
        for i, (name, code) in enumerate(maps.items()):
            btn = QtWidgets.QPushButton(f"{name}\n{code}")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setMinimumHeight(74)
            btn.setToolTip(f"点击复制 {name} 的密码 {code}")
            btn.setStyleSheet(
                "QPushButton{background:#121a24;border:1px solid #232a36;border-radius:10px;"
                "color:#f0f4fa;font-size:12.5px;text-align:center;}"
                "QPushButton:hover{border-color:#20ffe0;background:#16222c;}"
            )
            btn.clicked.connect(lambda _=False, n=name, c=code: self._copy_pwd(n, c))
            grid.addWidget(btn, i // 3, i % 3)
        box.addLayout(grid)
        note = QtWidgets.QLabel(
            "密码每天 0 点后更新。现在是 %s，抓到的是站点当天数据；"
            "站点偶尔会延迟，凌晨那阵抓到旧值属正常。" % clock_now)
        note.setObjectName("Hint")
        box.addWidget(note)

        box.addStretch(1)

    def _copy_pwd(self, name, code):
        QtWidgets.QApplication.clipboard().setText(code)
        old = self.update_lbl.text()
        self.update_lbl.setText(f"已复制 {name} {code}")
        QTimer.singleShot(1800, lambda: self.update_lbl.setText(old))

    def render_ammo(self):
        box = self._reset("ammo")
        block = (self.data or {}).get("ammo") or {}
        rows = block.get("list") or []
        if not rows:
            box.addWidget(self._empty_tip("还没有数据，点右上角「刷新」"))
            box.addStretch(1)
            return
        tb = self._table(["子弹", "数量", "单价", "总价值"], [0, 80, 90, 110])
        tb.setRowCount(len(rows))
        for i, it in enumerate(rows):
            for j, text in enumerate((it["name"], f"{it['count']}", f"{it['unit']:,}", f"{it['total']:,}")):
                cell = QtWidgets.QTableWidgetItem(text)
                if j > 0:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                tb.setItem(i, j, cell)
        tb.setColumnWidth(0, 260)
        box.addWidget(tb, 1)
        if block.get("updated"):
            lab = QtWidgets.QLabel("站点更新于 " + block["updated"])
            lab.setObjectName("Hint")
            box.addWidget(lab)

    def render_fake(self):
        box = self._reset("fake")
        block = (self.data or {}).get("price_top") or {}
        rows = block.get("list") or []
        if not rows:
            box.addWidget(self._empty_tip("还没有数据，点右上角「刷新」"))
            box.addStretch(1)
            return
        tb = self._table(["#", "物品", "战备值", "售价", "战备-售价"], [44, 0, 110, 100, 120])
        tb.setRowCount(len(rows))
        for i, it in enumerate(rows):
            for j, text in enumerate((str(it["rank"]), it["name"], f"{it['gear']:,}",
                                      f"{it['sell']:,}", f"{it['diff']:+,}")):
                cell = QtWidgets.QTableWidgetItem(text)
                if j >= 2:
                    cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if j == 4:
                    cell.setForeground(QtGui.QColor("#7ee787" if it["diff"] >= 0 else "#ff8a8a"))
                tb.setItem(i, j, cell)
        tb.setColumnWidth(1, 300)
        box.addWidget(tb, 1)
        if block.get("updated"):
            lab = QtWidgets.QLabel("站点更新于 " + block["updated"])
            lab.setObjectName("Hint")
            box.addWidget(lab)

    def render_profit(self):
        box = self._reset("profit")
        block = (self.data or {}).get("profit") or {}
        groups = block.get("groups") or []
        if not groups:
            box.addWidget(self._empty_tip("还没有数据，点右上角「刷新」"))
            box.addStretch(1)
            return
        for group in groups:
            title = QtWidgets.QLabel(group["station"] + f"　{len(group['list'])} 项")
            title.setStyleSheet("font-size:13px;font-weight:700;color:#20ffe0;margin-top:4px;")
            box.addWidget(title)
            rows = group["list"][:12]
            tb = self._table(["物品", "耗时", "总利润", "每小时"], [0, 80, 120, 110])
            tb.setRowCount(len(rows))
            for i, it in enumerate(rows):
                for j, text in enumerate((it["name"], f"{it['hours']}小时",
                                          f"{it['profit']:,}", f"{it['hourly']:,}")):
                    cell = QtWidgets.QTableWidgetItem(text)
                    if j > 0:
                        cell.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    tb.setItem(i, j, cell)
            tb.setFixedHeight(35 + len(rows) * 30)
            tb.setColumnWidth(0, 260)
            box.addWidget(tb)
            if len(group["list"]) > 12:
                more = QtWidgets.QLabel(f"下面还有 {len(group['list']) - 12} 行，站点上看完整的")
                more.setObjectName("Hint")
                box.addWidget(more)
        if block.get("updated"):
            lab = QtWidgets.QLabel("站点更新于 " + block["updated"])
            lab.setObjectName("Hint")
            box.addWidget(lab)
        box.addStretch(1)

    # ------------------------------------------------------------ 自动更新
    def _on_auto_toggled(self, on: bool) -> None:
        self.win.cfg.pwd_auto = bool(on)
        self.win.cfg.save()
        if on:
            self._last_auto = 0.0
            self._auto_tick()
        else:
            self.update_lbl.setText("自动更新已关闭 · 只在你点刷新时联网")

    def _auto_tick(self) -> None:
        """每 60 秒看一眼：缓存是不是今天的。不是就抓一次（带退避）。"""
        if not getattr(self.win.cfg, "pwd_auto", True):
            return
        if self._worker is not None:
            return
        today = time.strftime("%Y-%m-%d")
        cached = str((self.data.get("passwords") or {}).get("codes_date") or "")
        if cached == today:
            self._auto_fail = 0
            return
        # 跨天但还没到 00:02，站点多半还没换，等一下再抓
        if time.strftime("%H:%M") < "00:02":
            return
        # 失败退避：前 3 次 5 分钟，之后 15 分钟
        wait = 300 if self._auto_fail < 3 else 900
        if self._last_auto and (time.time() - self._last_auto) < wait:
            return
        self._last_auto = time.time()
        self.refresh_codes(auto=True)

    # ------------------------------------------------------------ 刷新
    def refresh_codes(self, auto: bool = False):
        """只抓每日密码这一块。"""
        if self._worker is not None:
            return
        self.refresh_btn.setText("刷新中…")
        self.refresh_btn.setEnabled(False)
        self.update_lbl.setText("正在抓今日密码…" if auto else "正在抓密码…")
        worker = _DeltaWorker(self.ds, mode="codes")
        worker.done.connect(self.on_refreshed)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def do_refresh(self):
        if self._worker is not None:
            return
        self.refresh_btn.setText("刷新中…")
        self.refresh_btn.setEnabled(False)
        self.update_lbl.setText("正在抓取…")
        worker = _DeltaWorker(self.ds)
        worker.done.connect(self.on_refreshed)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        worker.start()

    def on_refreshed(self, data):
        self._worker = None
        self.refresh_btn.setText("刷新")
        self.refresh_btn.setEnabled(True)
        today = time.strftime("%Y-%m-%d")
        codes = (data or {}).get("passwords") or {}
        got_today = bool(codes.get("maps")) and codes.get("codes_date") == today
        if got_today:
            self._auto_fail = 0
            self.data = data
            self.render_all()
            self.update_lbl.setText("更新于 " + str(data.get("fetched_at", "")))
            hud = getattr(self.win, "hud", None)
            if hud is not None:
                hud.reload(force=True)
            return
        # 没拿到今日密码：不清空，保留上一次的结果
        self._auto_fail += 1
        errs = (data or {}).get("errors") or []
        why = str(errs[0])[:40] if errs else str(codes.get("last_code_error") or "")[:40]
        if codes.get("maps"):
            self.data = data
            self.render_all()
        self.update_lbl.setText("没拿到今日密码，先沿用上次的" + (f" · {why}" if why else ""))

    def refresh_block(self, key: str) -> bool:
        """只抓某一块（手机端「刷新」按钮用）。正在抓别的就直接拒掉。"""
        if self._worker is not None:
            return False
        if key == "pwd":
            self.refresh_codes(auto=False)
            return True
        if key not in ("ammo", "fake", "profit"):
            return False
        worker = _BlockWorker(self.ds, key)
        worker.done.connect(self.on_block_done)
        worker.finished.connect(worker.deleteLater)
        self._worker = worker
        self.refresh_btn.setText("刷新中…")
        self.refresh_btn.setEnabled(False)
        self.update_lbl.setText("正在抓…")
        worker.start()
        return True

    def on_block_done(self, key: str, data: dict) -> None:
        self._worker = None
        self.refresh_btn.setText("刷新")
        self.refresh_btn.setEnabled(True)
        if "__error__" in data:
            self.update_lbl.setText("没抓到：" + str(data["__error__"])[:40])
            return
        self.data = data
        self.render_all()
        self.update_lbl.setText("更新于 " + str(data.get("fetched_at", "")))


class GuideDialog(QtWidgets.QDialog):
    """新手引导：4 页说清"这东西怎么用"。

    第一次启动自动弹一次（config.guide_shown 记着），之后从设置里随时重看。
    """

    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.win = win
        self.cfg = win.cfg
        self._idx = 0

        self.setWindowTitle("新手引导 · 燧镜")
        self.setMinimumSize(660, 520)
        self.setStyleSheet(qss())

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 16)
        lay.setSpacing(10)

        self.head = QtWidgets.QLabel()
        self.head.setStyleSheet("color:#20ffe0; font-size:17px; font-weight:700;")
        lay.addWidget(self.head)

        self.sub = QtWidgets.QLabel()
        self.sub.setStyleSheet("color:#7b8494; font-size:11.5px;")
        lay.addWidget(self.sub)

        self.body = QtWidgets.QLabel()
        self.body.setWordWrap(True)
        self.body.setTextFormat(Qt.RichText)
        self.body.setStyleSheet("color:#c9d3e0; font-size:13px; line-height:160%;")
        self.body.setAlignment(Qt.AlignTop)
        lay.addWidget(self.body, 1)

        foot = QtWidgets.QHBoxLayout()
        self.dots = QtWidgets.QLabel()
        self.dots.setStyleSheet("color:#5f6878; font-size:11px;")
        foot.addWidget(self.dots)
        foot.addStretch(1)

        self.b_prev = QtWidgets.QPushButton("上一步")
        self.b_prev.setObjectName("Ghost")
        self.b_prev.clicked.connect(self._prev)
        foot.addWidget(self.b_prev)

        self.b_next = QtWidgets.QPushButton("下一步")
        self.b_next.setObjectName("Primary")
        self.b_next.clicked.connect(self._next)
        foot.addWidget(self.b_next)

        self.b_skip = QtWidgets.QPushButton("以后再说")
        self.b_skip.setObjectName("Ghost")
        self.b_skip.clicked.connect(self.reject)
        foot.addWidget(self.b_skip)

        lay.addLayout(foot)

        self._pages = self._build_pages()
        self._render()

    # ------------------------------------------------------------------
    def _build_pages(self) -> List[Tuple[str, str, str]]:
        tw, th = self.cfg.target
        target = f"{tw} × {th}" if tw and th else "1280 × 960"
        ratio = display.ratio_group(tw, th) if (tw and th) else "4:3"
        return [
            (
                "一块面板，管住这几件事",
                "第一次打开先认认路",
                f"""
<div>顶上一块是 <b>分辨率</b>：左边是当前的，右边是你要切的档位，中间一个大按钮，按一下就从
{target} 和原生之间来回切。旁边的 <b>嘉豪模式</b> 管黑边，只负责看，改还是得去显卡面板点一次。</div>
<div style="margin-top:10px">第二块是 <b>反作弊优化</b>：把反作弊扫描进程的优先级压到最低，让它别跟游戏抢 CPU 和硬盘。
勾上「自动守护」就不用管了，游戏重启 ACE 之后会自己再压一次。</div>
<div style="margin-top:10px">中间四个小块是 <b>CPU / 内存 / 显卡 / 温度</b>：卡的时候瞄一眼，就知道是机器不行还是网络不行。</div>
<div style="margin-top:10px">最下面那块 <b>工具</b>：着色器缓存一键清理、网络测速、<b>一键推迟 Windows 更新</b>。
打游戏最怕打到一半被更新拽下去，最多往后挪 35 天，到期自己恢复，不是永久关掉。赛季刚更新那几局最卡，清一下缓存往往就好了。</div>
""",
            ),
            (
                "自带的那几个工具",
                "不用另装软件，点开就能用",
                """
<div>工具区带 <b>「内置」</b>角标的那几个，是跟着程序一起装进来的，升级时自动换新版，
不用自己去网上找、也不会重复下载。</div>
<div style="margin-top:12px"><b>三角洲情报</b>：点「打开页面」直接进软件自己的页面，密码、弹药、假人、收益一屏刷。</div>
<div style="margin-top:12px"><b>显示器滤镜</b>：改的是显示器输出的伽马曲线——提亮、抬暗部、偏暖偏冷、加对比，
18 个预设点一下就套上；左边原图、右边滤镜对着看，参数还能细调。关窗自动还原，不注入游戏、不叠画面层。</div>
<div style="margin-top:12px"><b>qBittorrent</b>：BT 下载器，随包装好，点开就能加种子、下任务。</div>
<div style="margin-top:12px">老用户升级后启动，内置工具会自己补进列表，不用手动加；自己删掉的那条不会再硬塞回来。</div>
<div style="margin-top:12px;color:#7b8494">想给某个工具改名字或换图标：在工具区右键那一项。</div>
""",
            ),
            (
                "最常用的三步",
                "先做这三件，其它都是补的",
                f"""
<div><b>1. 切分辨率</b>：点<input style="background:#1b2230;border:1px solid #2b3546;border-radius:4px;
padding:1px 6px;color:#20ffe0"> 切换为 {ratio} </input> 那个大按钮（右边下拉能换档位，{target} 只是其中一档），
切过去再点一次就回原生。忘了切回去就按 <b>Ctrl + Alt + R</b>。</div>
<div style="margin-top:12px"><b>2. 挂工具</b>：底下工具区点「启动」，或者图标视图里双击。关掉面板它们会继续跑，收进托盘就行。</div>
<div style="margin-top:12px"><b>3. 开自动化</b>：点顶部「自动化」→ 上面紫色的 <b>一键模板</b> → 点「两条一起加」。
<br>· A 开战准备：等 30 秒 → 反作弊优化 → 开帧率灯 → 开回放缓冲（<b>不动分辨率</b>，保持你这个显示器原生）
<br>· B 收尾归档：存最后一段回放 → 关回放 → 关帧率灯 → 还原分辨率
<br>进程名默认按国际服写，对不上就在规则里改成你任务管理器里那个。</div>
""",
            ),
            (
                "游戏里能按的键",
                "这些都不会挡游戏",
                """
<div><b>Ctrl + Alt + S</b>　全屏截图（自己会先躲开，截完回来）</div>
<div><b>Ctrl + Alt + Shift + S</b>　框选截图</div>
<div><b>Ctrl + Alt + B</b>　保存最近 10 分钟（回放缓冲要开着）</div>
<div><b>Ctrl + Alt + R</b>　切分辨率　<b>Ctrl + Alt + M</b>　打开面板</div>
<div style="margin-top:12px">录屏在面板上点「录屏」，<b>连系统声音一起录</b>，再按一次停止并保存，文件按日期进「素材」。
回放缓冲是后台循环存最近 10 分钟，等你按下保存才真正落盘，平时不占多少地方。</div>
<div style="margin-top:12px">这些键<b>每一个都能单独关</b>：设置 → 热键，每一行前面有个勾，去掉勾这个键就不响应了，别的键照常；勾回来还是原来那个组合，不用重录。</div>
<div style="margin-top:12px">帧率灯和密码窗都能拖到屏幕任意位置，也能设成 <b>鼠标穿透</b>——看得见、点不到，不影响操作。</div>
""",
            ),
            (
                "出状况先看这几处",
                "别慌，八成是权限或进程名",
                """
<div>· <b>反作弊优化不生效</b>：要管理员权限。右键桌面快捷方式 →「以管理员身份运行」，重启后会静默待在托盘。</div>
<div>· <b>自动化没触发</b>：九成是进程名写错了。任务管理器 →「详细信息」里那一列就是真名，复制过来贴进规则。</div>
<div>· <b>帧率灯一直是 --</b>：右键悬浮窗，用管理员身份跑一次就有数了。</div>
<div>· <b>换了电脑或换显示器</b>：程序自己认出来，只更新"原生"基准，<b>不会自己去改你当前的分辨率</b>。</div>
<div style="margin-top:12px">还搞不定：点顶部 <b>「日志」</b>——右上角会直接标「正常」或「有错误」；
点下面的 <b>「导出诊断包」</b> 会打成一个 zip 并自动帮你选中，发给我，照着里面能定位到具体哪一步。</div>
<div style="margin-top:16px;color:#7b8494">这一页看完就可以关掉了。想重看：设置 →「新手引导」。</div>
""",
            ),
        ]

    # ------------------------------------------------------------------
    def _render(self) -> None:
        title, sub, body = self._pages[self._idx]
        self.head.setText(title)
        self.sub.setText(sub)
        self.body.setText(body)
        self.dots.setText(f"第 {self._idx + 1} / {len(self._pages)} 页")
        self.b_prev.setEnabled(self._idx > 0)
        last = self._idx >= len(self._pages) - 1
        self.b_next.setText("开始用了" if last else "下一步")
        self.b_skip.setVisible(not last)

    def _prev(self) -> None:
        if self._idx > 0:
            self._idx -= 1
            self._render()

    def _next(self) -> None:
        if self._idx < len(self._pages) - 1:
            self._idx += 1
            self._render()
        else:
            self.accept()


class KeyCaptureButton(QtWidgets.QPushButton):
    """点一下它，然后直接按你想要的键，按钮就把组合记下来。"""

    captured = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Ghost")
        self.setMinimumWidth(150)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self._saved = ""
        self.setToolTip("点一下，再按新的组合键；按 Esc 取消")

    def set_hotkey_text(self, text: str) -> None:
        self._saved = text or ""
        self.setText(self._saved)

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.setText("按下组合键…")
        self.setStyleSheet("color:#19e0d0; border-color:#19e0d0;")

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.setStyleSheet("")
        self.setText(self._saved or "未设置")

    def keyPressEvent(self, event):
        key = event.key()
        if key == QtCore.Qt.Key_Escape:
            self.clearFocus()
            return
        # 只按了修饰键：继续等主键
        if key in (
            QtCore.Qt.Key_Shift, QtCore.Qt.Key_Control,
            QtCore.Qt.Key_Alt, QtCore.Qt.Key_Meta,
        ):
            return
        seq = QtGui.QKeySequence(event.keyCombination())
        text = seq.toString(QtGui.QKeySequence.PortableText).replace("Meta", "Win")
        parsed = parse_hotkey(text)
        if not parsed:
            self.setText("要带 Ctrl / Alt / Shift")
            return
        text = format_hotkey(*parsed)
        self._saved = text
        self.setStyleSheet("color:#19e0d0; border-color:#19e0d0;")
        self.clearFocus()
        self.setText(text)
        self.captured.emit(text)


def _art_alpha(hexv: str, a: float) -> str:
    """#rrggbb → rgba(r,g,b,a)。解析不了就原样返回，不会有副作用。"""
    h = (hexv or "").lstrip("#")
    if len(h) != 6:
        return hexv
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return hexv
    return f"rgba({r}, {g}, {b}, {a:.2f})"


def _glass_overrides() -> dict:
    """毛玻璃：页面底色半透明，后面的桌面才透得上来。"""
    t = theme.current()
    return {
        "bg-page": _art_alpha(t.value("bg-page", "#0e1015"), 0.74),
        "bg-page2": _art_alpha(t.value("bg-page2", "#0b0d12"), 0.74),
        "bg-input": _art_alpha(t.value("bg-input", "#12161e"), 0.80),
        "bg-card": _art_alpha(t.value("bg-card", "#161a22"), 0.72),
        "bg-raised": _art_alpha(t.value("bg-raised", "#1a1f29"), 0.76),
        "bg-button": _art_alpha(t.value("bg-button", "#1e242f"), 0.80),
        "bg-off": _art_alpha(t.value("bg-off", "#141822"), 0.74),
        "bg-off2": _art_alpha(t.value("bg-off2", "#10131a"), 0.74),
    }


def _art_overrides() -> dict:
    """开着壁纸时卡片降一点不透明度，图才能从层间露出来。"""
    t = theme.current()
    return {
        "bg-card": _art_alpha(t.value("bg-card", "#161a22"), 0.80),
        "bg-raised": _art_alpha(t.value("bg-raised", "#1a1f29"), 0.84),
        "bg-button": _art_alpha(t.value("bg-button", "#1e242f"), 0.92),
        "bg-off": _art_alpha(t.value("bg-off", "#141822"), 0.88),
        "bg-off2": _art_alpha(t.value("bg-off2", "#10131a"), 0.88),
    }


def _tile_pixmap(kind: str, color: str = "#20ffe0", size: int = 26) -> QtGui.QPixmap:
    """方块入口上的小图标：还是手画，不依赖字体，换皮肤时一起换色。"""
    pm = QtGui.QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(QtGui.QColor(color))
    pen.setWidthF(3.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    half = float(size)
    if kind == "cast":
        # 左边一部竖着的手机，右边一块横着的屏，中间一道箭头表示「投过去」
        p.drawRoundedRect(QtCore.QRectF(half - 19, half - 13, 10, 26), 2.6, 2.6)
        p.drawRoundedRect(QtCore.QRectF(half + 1, half - 12, 18, 22), 3, 3)
        p.drawLine(QtCore.QPointF(half - 6, half - 1), QtCore.QPointF(half - 1, half - 1))
        p.drawLine(QtCore.QPointF(half - 1, half - 1), QtCore.QPointF(half - 4, half - 4))
    if kind == "clip":
        # 一块板 + 顶部夹子 + 两条内容线
        p.drawRoundedRect(QtCore.QRectF(half - 15, half - 11, 30, 27), 5, 5)
        p.drawRoundedRect(QtCore.QRectF(half - 6, half - 17, 12, 9), 3, 3)
        p.drawLine(QtCore.QPointF(half - 7, half + 1), QtCore.QPointF(half + 7, half + 1))
        p.drawLine(QtCore.QPointF(half - 7, half + 8), QtCore.QPointF(half + 2, half + 8))
    elif kind == "share":
        # 上下两个箭头：一个上去一个下来，就是「互传」
        p.drawLine(QtCore.QPointF(half - 8, half + 13), QtCore.QPointF(half - 8, half - 9))
        p.drawLine(QtCore.QPointF(half - 8, half - 13), QtCore.QPointF(half - 14, half - 6))
        p.drawLine(QtCore.QPointF(half - 8, half - 13), QtCore.QPointF(half - 2, half - 6))
        p.drawLine(QtCore.QPointF(half + 8, half - 13), QtCore.QPointF(half + 8, half + 9))
        p.drawLine(QtCore.QPointF(half + 8, half + 13), QtCore.QPointF(half + 2, half + 6))
        p.drawLine(QtCore.QPointF(half + 8, half + 13), QtCore.QPointF(half + 14, half + 6))
    elif kind == "phone":
        # 一部手机 + 右上一道无线弧，表示「这台手机要连过来」
        p.drawRoundedRect(QtCore.QRectF(half - 10, half - 17, 20, 34), 4.5, 4.5)
        p.drawLine(QtCore.QPointF(half - 3.5, half + 12), QtCore.QPointF(half + 3.5, half + 12))
        pen.setWidthF(2.6)
        p.setPen(pen)
        p.drawArc(QtCore.QRectF(half + 3, half - 24, 15, 15), 300 * 16, 120 * 16)
        p.drawArc(QtCore.QRectF(half + 6, half - 21, 9, 9), 300 * 16, 120 * 16)
    elif kind == "startup":
        # 电源开关：一圈开口朝上的弧 + 中间一根竖线
        pen.setWidthF(2.9)
        p.setPen(pen)
        p.drawArc(QtCore.QRectF(half - 13, half - 13, 26, 26), 55 * 16, 250 * 16)
        p.drawLine(QtCore.QPointF(half, half - 16), QtCore.QPointF(half, half - 2))
    p.end()
    return pm


class ToolTile(QtWidgets.QFrame):
    """主页上的方块快捷入口：一个图标 + 一行字，点一下办事。"""

    clicked = Signal()

    def __init__(self, title: str, kind: str, tip: str = "", size: int = 72, parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("ToolTile")
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover, True)
        self.setToolTip(tip)
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(4, 8, 4, 8)
        lay.setSpacing(6)
        self._kind = kind
        self.icon = QtWidgets.QLabel()
        self.icon.setStyleSheet("background:transparent;border:none;")
        self.icon.setAlignment(Qt.AlignCenter)
        self.icon.setPixmap(_tile_pixmap(kind, color=_accent_color(), size=size * 0.42))
        lay.addWidget(self.icon, 1)
        self.caption = None
        if title:
            self.caption = QtWidgets.QLabel(title)
            self.caption.setAlignment(Qt.AlignCenter)
            self.caption.setStyleSheet(
                "background:transparent;border:none;color:%s;font-size:11.5px;font-weight:600;"
                % _fg1_color()
            )
            lay.addWidget(self.caption)

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton and self.rect().contains(ev.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(ev)


def _accent_color() -> str:
    try:
        return theme.current().colors.get("accent", "#20ffe0")
    except Exception:  # noqa: BLE001
        return "#20ffe0"


def _fg1_color() -> str:
    try:
        return theme.current().colors.get("fg-1", "#c9cfda")
    except Exception:  # noqa: BLE001
        return "#c9cfda"


def _gear_icon(color: str = "#8b95a5") -> QtGui.QIcon:
    """设置那个小齿轮：和小衣服一样手画，不依赖字体。"""
    pm = QtGui.QPixmap(36, 36)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor(color))
    c = 18.0
    p.save()
    p.translate(c, c)
    for i in range(8):
        p.save()
        p.rotate(45 * i)
        p.drawRoundedRect(QtCore.QRectF(-2.6, -12.6, 5.2, 7.2), 1.5, 1.5)
        p.restore()
    p.restore()
    p.drawEllipse(QtCore.QPointF(c, c), 9.0, 9.0)
    # 中间挖空，才像齿轮不像圆饼
    p.setCompositionMode(QtGui.QPainter.CompositionMode_Clear)
    p.drawEllipse(QtCore.QPointF(c, c), 3.6, 3.6)
    p.end()
    return QtGui.QIcon(pm)


def _skin_icon(color: str = "#8b95a5") -> QtGui.QIcon:
    """顶栏那个小衣服图标：手画一件 T 恤，不依赖任何字体。"""
    pm = QtGui.QPixmap(36, 36)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    pen = QtGui.QPen(QtGui.QColor(color))
    pen.setWidthF(3.4)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    path = QtGui.QPainterPath()
    pts = [(12, 6), (8, 8.4), (2.4, 11.6), (4.8, 18), (10, 14.8), (10, 30),
           (26, 30), (26, 14.8), (31.2, 18), (33.6, 11.6), (28, 8.4), (24, 6), (18, 10)]
    path.moveTo(*pts[0])
    for pt in pts[1:]:
        path.lineTo(*pt)
    path.closeSubpath()
    p.drawPath(path)
    p.end()
    return QtGui.QIcon(pm)


def _skin_swatch(t) -> QtWidgets.QLabel:
    """皮肤的小色卡：底色 + 描边 + 主色，一眼看出长什么样。"""
    pm = QtGui.QPixmap(46, 30)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QtGui.QColor(t.colors.get("bg-card", "#161a22")))
    p.drawRoundedRect(QtCore.QRectF(0, 0, 46, 30), 6, 6)
    p.setBrush(QtGui.QColor(t.colors.get("accent", "#20ffe0")))
    p.drawRoundedRect(QtCore.QRectF(32, 7, 8, 16), 3, 3)
    p.setPen(QtGui.QPen(QtGui.QColor(t.colors.get("line-1", "#242b38")), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRoundedRect(QtCore.QRectF(0.5, 0.5, 45, 29), 6, 6)
    p.end()
    lb = QtWidgets.QLabel()
    lb.setFixedSize(46, 30)
    lb.setPixmap(pm)
    return lb


class SkinRow(QtWidgets.QFrame):

    """皮肤列表里的一行：色卡 + 名字 + 状态，点一下就换。"""

    clicked = QtCore.Signal(str)

    def __init__(self, t, active: bool = False, parent=None):
        super().__init__(parent)
        self.key = t.key
        self.setObjectName("SkinRow")
        self.setCursor(Qt.PointingHandCursor)
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(10, 7, 12, 7)
        row.setSpacing(11)
        row.addWidget(_skin_swatch(t))

        col = QtWidgets.QVBoxLayout()
        col.setSpacing(1)
        name = QtWidgets.QLabel(t.name)
        name.setObjectName("SkinName")
        desc = QtWidgets.QLabel(t.desc or "")
        desc.setObjectName("Hint")
        col.addWidget(name)
        col.addWidget(desc)
        row.addLayout(col, 1)

        tag = QtWidgets.QLabel("正在使用" if active else "点一下切换")
        tag.setObjectName("SkinTag" if active else "Hint")
        row.addWidget(tag)

        extra = " QFrame#SkinRow { border-color:#1c4a43; background:#102a27; }" if active else ""
        self.setStyleSheet(
            "QFrame#SkinRow { background:#141822; border:1px solid #232a36; border-radius:10px; }"
            "QFrame#SkinRow:hover { border-color:#3a4455; }" + extra
        )

    def mouseReleaseEvent(self, ev) -> None:
        if ev.button() == Qt.LeftButton:
            self.clicked.emit(self.key)
        super().mouseReleaseEvent(ev)


def _import_skin_file(parent, win) -> bool:
    """挑一个 json 丢进 themes/，然后重扫一遍。"""
    import shutil as _sh

    path, _ = QtWidgets.QFileDialog.getOpenFileName(
        parent, "导入皮肤", str(Path.home()), "JSON (*.json)"
    )
    if not path:
        return False
    try:
        folder = theme.themes_dir()
        folder.mkdir(parents=True, exist_ok=True)
        _sh.copy2(path, folder / Path(path).name)
        theme.scan(force=True)
        apply_theme()
        win.toast("皮肤已导入：" + Path(path).stem)
        return True
    except Exception as exc:  # noqa: BLE001
        win.toast("导入失败：" + str(exc), False)
        return False


def _open_skin_folder(win) -> None:
    try:
        folder = theme.themes_dir()
        folder.mkdir(parents=True, exist_ok=True)
        os.startfile(str(folder))
    except Exception as exc:  # noqa: BLE001
        win.toast("打不开文件夹：" + str(exc), False)


def _num(v) -> str:
    """15.0 → 15，476.9 → 476.9。"""
    try:
        f = float(v)
    except Exception:  # noqa: BLE001
        return str(v)
    return str(int(f)) if abs(f - int(f)) < 1e-9 else str(f)


def _spec_headline(d: dict) -> str:
    """一句话摘要，折叠时显示在标题右边。"""
    bits = []
    cpu = d.get("cpu") or {}
    name = (cpu.get("name") or "")
    for junk in ("AMD ", "Intel ", "Intel(R) ", "Core(TM) ", " with Radeon Graphics", " CPU", "(R)", "(TM)"):
        name = name.replace(junk, "")
    name = name.strip()
    if name:
        bits.append(name)
    total = (d.get("mem") or {}).get("total")
    if total:
        bits.append(f"{_num(total)} GB")
    gpus = d.get("gpu") or []
    if gpus:
        gn = (gpus[0].get("name") or "")
        for junk in ("NVIDIA ", "GeForce ", "AMD ", "Radeon "):
            gn = gn.replace(junk, "")
        if gpus[0].get("vram"):
            gn += f" {_num(gpus[0]['vram'])}G"
        bits.append(gn.strip())
    tot = d.get("disk_total") or 0
    if tot >= 1024:
        bits.append(f"{tot / 1024:.1f} TB")
    elif tot:
        bits.append(f"{int(tot)} GB")
    return " · ".join(bits) or "—"


def _spec_rows(d: dict) -> List[Tuple[str, str]]:
    """规格表：左边标签，右边值。"""
    osi = d.get("os") or {}
    sysm = d.get("system") or {}
    board = d.get("board") or {}
    bios = d.get("bios") or {}
    cpu = d.get("cpu") or {}
    mem = d.get("mem") or {}
    rows: List[Tuple[str, str]] = []

    det = " · ".join(x for x in (osi.get("build"), osi.get("arch"), osi.get("mode")) if x)
    rows.append(("系统", (osi.get("name") or "Windows") + ("　" + det if det else "")))

    mp = " ".join(x for x in (sysm.get("mfr"), sysm.get("model")) if x).strip()
    if mp:
        rows.append(("整机", mp))
    bp = " ".join(x for x in (board.get("mfr"), board.get("product")) if x).strip()
    if bp:
        rows.append(("主板", bp))
    bv = "　".join(x for x in (bios.get("version"), bios.get("date")) if x).strip()
    if bv:
        rows.append(("BIOS", bv))

    cbits = []
    if cpu.get("cores") and cpu.get("threads"):
        cbits.append(f"{cpu['cores']} 核 {cpu['threads']} 线程")
    if cpu.get("ghz"):
        cbits.append(f"{cpu['ghz']} GHz")
    if cpu.get("l3_mb"):
        cbits.append(f"L3 {_num(cpu['l3_mb'])} MB")
    rows.append(("CPU", (cpu.get("name") or "读不到") + ("　" + " · ".join(cbits) if cbits else "")))

    sticks = mem.get("sticks") or []
    if sticks:
        one = sticks[0]
        desc = f"{_num(one.get('cap'))} GB × {len(sticks)}"
        if one.get("type"):
            desc += f" {one['type']}"
        if one.get("speed"):
            desc += f"-{one['speed']}"
        desc += f"　共 {_num(mem.get('total'))} GB"
        rows.append(("内存", desc))
    elif mem.get("total"):
        rows.append(("内存", f"{_num(mem.get('total'))} GB"))

    for g in d.get("gpu") or []:
        vram = f"{_num(g.get('vram'))} GB" if g.get("vram") else "显存未知"
        dv = f"驱动 {g.get('driver')}" if g.get("driver") else ""
        rows.append(("显卡", f"{g.get('name', '')}　{vram}　{dv}".strip()))

    for x in d.get("disk") or []:
        extra = " ".join(v for v in (x.get("media"), x.get("bus")) if v)
        rows.append(("硬盘", f"{x.get('model', '')}　{_num(x.get('size'))} GB　{extra}".strip()))
    if d.get("disk_total"):
        rows.append(("存储", f"共 {_num(d['disk_total'])} GB　可用 {_num(d.get('disk_free'))} GB"))

    for m in d.get("monitors") or []:
        tag = "（主屏）" if m.get("primary") else ""
        hz = f" {m['hz']}Hz" if m.get("hz") else ""
        nm = f"{m['model']}　" if m.get("model") else ""
        rows.append(("显示器", f"{nm}{m.get('w', 0)}×{m.get('h', 0)}{hz}{tag}"))

    if osi.get("power"):
        rows.append(("电源", osi["power"]))
    return rows


class _SpecWorker(QtCore.QThread):
    """后台读硬件规格：WMI 那条 PowerShell 要几秒，不能卡界面。"""

    done = QtCore.Signal(dict)

    def run(self) -> None:
        d = {}
        try:
            d = spec.read()
        except Exception as exc:  # noqa: BLE001
            log.warning("读硬件规格失败：%s", exc)
        self.done.emit(d)


def _divider() -> QtWidgets.QWidget:
    """细横线，用来切面板里的分区。"""
    w = QtWidgets.QFrame()
    w.setObjectName("Divider")
    w.setFixedHeight(1)
    return w


class SkinPanel(QtWidgets.QDialog):

    """小衣服按钮点开的「外观」面板：皮肤 + 窗口外观 + 背景模糊。

    壁纸的开关和换图留在 设置 → 外观，这里只给一句指路。
    """

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle("外观")
        self.setFixedWidth(448)
        self.setStyleSheet(qss())

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(9)

        # 皮肤
        title = QtWidgets.QLabel("皮肤")
        title.setObjectName("Section")
        v.addWidget(title)
        tip = QtWidgets.QLabel("只换颜色，不动布局。点一下就生效，不用重启。")
        tip.setObjectName("Hint")
        v.addWidget(tip)

        self.rows = QtWidgets.QVBoxLayout()
        self.rows.setSpacing(6)
        v.addLayout(self.rows)

        v.addSpacing(4)
        v.addWidget(_divider())
        v.addSpacing(4)

        # 窗口外观
        t2 = QtWidgets.QLabel("窗口外观")
        t2.setObjectName("Section")
        v.addWidget(t2)
        t2tip = QtWidgets.QLabel(
            "经典 = 系统标题栏；毛玻璃 = 无边框、四角圆、能透出桌面。\n"
            "液态玻璃 = 更透的底 + 厚亮边 + 顶部反光。"
        )
        t2tip.setObjectName("Hint")
        v.addWidget(t2tip)

        seg = QtWidgets.QHBoxLayout()
        seg.setSpacing(8)
        self._seg = {}
        for mode, text in (("classic", "经典外观"), ("glass", "毛玻璃"), ("liquid", "液态玻璃")):
            b = QtWidgets.QPushButton(text)
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setMinimumHeight(32)
            b.clicked.connect(lambda _=False, m=mode: self._pick_mode(m))
            seg.addWidget(b, 1)
            self._seg[mode] = b
        v.addLayout(seg)

        # 背景模糊
        rowb = QtWidgets.QWidget()
        hb = QtWidgets.QHBoxLayout(rowb)
        hb.setContentsMargins(0, 0, 0, 0)
        hb.setSpacing(10)
        lb = QtWidgets.QLabel("背景模糊")
        lb.setObjectName("Hint")
        lb.setFixedWidth(52)
        self.sld = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sld.setRange(0, 40)
        self.sld.setSingleStep(2)
        self.sld.valueChanged.connect(self._on_blur)
        self.lb_val = QtWidgets.QLabel()
        self.lb_val.setObjectName("Hint")
        self.lb_val.setFixedWidth(26)
        self.lb_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        hb.addWidget(lb)
        hb.addWidget(self.sld, 1)
        hb.addWidget(self.lb_val)
        v.addWidget(rowb)

        t3 = QtWidgets.QLabel("模糊只作用在壁纸那张图上，0 = 清楚，越大越糊。")
        t3.setObjectName("Hint")
        t3.setWordWrap(True)
        v.addWidget(t3)

        v.addSpacing(4)
        v.addWidget(_divider())
        v.addSpacing(4)

        art = QtWidgets.QLabel("壁纸的开关和换图在 设置 → 外观 里。")
        art.setObjectName("Hint")
        v.addWidget(art)

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(8)
        imp = QtWidgets.QPushButton("导入皮肤文件…")
        imp.setObjectName("Ghost")
        imp.clicked.connect(lambda: _import_skin_file(self, self.win) and self._sync())
        folder = QtWidgets.QPushButton("打开皮肤文件夹")
        folder.setObjectName("Ghost")
        folder.clicked.connect(lambda: _open_skin_folder(self.win))
        done = QtWidgets.QPushButton("完成")
        done.setObjectName("Primary")
        done.clicked.connect(self.accept)
        bar.addWidget(imp)
        bar.addWidget(folder)
        bar.addStretch(1)
        bar.addWidget(done)
        v.addLayout(bar)

        self._sync()

    def _sync(self) -> None:
        """按当前配置把三块都刷成真实状态。"""
        self._fill()
        mode = getattr(self.win.cfg, "window_mode", "classic") or "classic"
        for k, b in self._seg.items():
            b.setChecked(k == mode)
        val = max(0, min(40, int(getattr(self.win.cfg, "art_blur", 18))))
        self.sld.blockSignals(True)
        self.sld.setValue(val)
        self.sld.blockSignals(False)
        self.lb_val.setText(str(val))

    def _fill(self) -> None:
        while self.rows.count():
            item = self.rows.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        cur = theme.current().key
        for t in theme.available():
            row = SkinRow(t, t.key == cur)
            row.clicked.connect(self._pick)
            self.rows.addWidget(row)

    def _pick(self, key: str) -> None:
        self.win.set_theme(key)
        self._fill()

    def _pick_mode(self, mode: str) -> None:
        self.win.set_window_mode(mode)
        self.setStyleSheet(qss())
        self._sync()
        # 主窗切模式时会 hide/show 一次，把面板顶回来
        self.show()
        self.raise_()

    def _on_blur(self, val: int) -> None:
        self.lb_val.setText(str(val))
        self.win.set_art_blur(val)


class SettingsDialog(QtWidgets.QDialog):

    """把散在托盘里的开关收进一个面板；主界面「设置」按钮打开的就是这里。"""

    def _set_hotkey(self, key, text) -> None:
        self._on_hotkey(key, text)
        self._refresh_hk_actual()

    def _set_hk_on(self, key, on) -> None:
        self.win.set_hotkey_on(key, on)
        self._refresh_hk_actual()

    def _refresh_hk_actual(self) -> None:
        """每行右边那列：真正注册上的键；被别的软件占了的标黄。"""
        actual = getattr(self.win, "hotkey_actual", {}) or {}

        def _flat(t: str) -> str:
            return (t or "").lower().replace(" ", "")

        for key, lb in getattr(self, "_hk_actual", {}).items():
            want = (self.cfg.hotkeys or {}).get(key) or DEFAULT_HOTKEYS.get(key, "")
            on = bool((self.cfg.hotkey_on or {}).get(key, True))
            got = actual.get(key) or ""
            if not on:
                lb.setText("已关闭")
                lb.setStyleSheet("color:#69737f; font-size:11px;")
            elif not got:
                lb.setText("注册失败")
                lb.setStyleSheet("color:#ff8a6b; font-size:11px;")
            elif _flat(got) != _flat(want):
                lb.setText(f"生效 {got}")
                lb.setStyleSheet("color:#f2c94c; font-size:11px;")
                lb.setToolTip(f"你设的是 {want}，被别的软件占了，实际用 {got}")
            else:
                lb.setText(f"生效 {got}")
                lb.setStyleSheet("color:#79c3b9; font-size:11px;")
                lb.setToolTip("")

    def _fill_skin_rows(self) -> None:
        lay = self._skin_rows
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        cur = theme.current().key
        for t in theme.available():
            row = SkinRow(t, t.key == cur)
            row.clicked.connect(self._skin_pick)
            lay.addWidget(row)

    def _skin_pick(self, key: str) -> None:
        self.win.set_theme(key)
        self._fill_skin_rows()

    def _skin_import(self) -> None:
        if _import_skin_file(self, self.win):
            self._fill_skin_rows()

    def _skin_folder(self) -> None:
        _open_skin_folder(self.win)

    def _on_blur(self, val: int) -> None:
        self.lb_blur_val.setText(str(val))
        self.win.set_art_blur(val)

    def _on_win_mode(self, idx: int) -> None:
        mode = self.cmb_win.itemData(idx) or "classic"
        self.win.set_window_mode(mode)

    def _art_text(self) -> str:
        p = self.win.art_path()
        return "当前：" + (p.name if p is not None else "未选择（会一直空着）")

    def _on_art_toggle(self, on: bool) -> None:
        self.win.set_art_enabled(bool(on))
        self.lb_art.setText(self._art_text())

    def _art_pick(self) -> None:
        self.win.pick_art()
        self.chk_art.setChecked(bool(getattr(self.win.cfg, "art_show", False)))
        self.lb_art.setText(self._art_text())

    def _art_clear(self) -> None:
        self.win.clear_art()
        self.chk_art.setChecked(False)
        self.lb_art.setText(self._art_text())

    def _export_config(self) -> None:
        import shutil as _sh

        from core.store import config_path as _cfg_path

        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出配置", str(Path.home() / f"{APP_NAME}_配置.json"), "JSON (*.json)"
        )
        if not path:
            return
        try:
            _sh.copy2(_cfg_path(), path)
            self.win.toast("配置已导出：" + Path(path).name)
        except Exception as exc:  # noqa: BLE001
            self.win.toast("导出失败：" + str(exc), False)

    def _import_config(self) -> None:
        import json
        import shutil as _sh

        from core.store import config_path as _cfg_path

        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "导入配置", str(Path.home()), "JSON (*.json)"
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            self.win.toast("这个文件读不出来，不是 json", False)
            return
        if not isinstance(data, dict) or "native" not in data:
            self.win.toast("不像是燧镜的配置文件", False)
            return
        try:
            _sh.copy2(path, _cfg_path())
        except Exception as exc:  # noqa: BLE001
            self.win.toast("写入失败：" + str(exc), False)
            return
        self.win.toast("配置已导入，重启燧镜后全部生效")

    def _set_audio_tray_icon(self, on: bool) -> None:
        self.win.cfg.audio_tray_icon = bool(on)
        self.win.cfg.save()
        tray = getattr(self.win, "audio_tray", None)
        if tray is not None:
            if on:
                tray.show()
            else:
                tray.hide()
        self.win.toast("小喇叭图标" + ("已放回任务栏（重开程序后固定）" if on else "已收起，用主托盘菜单切音频"))

    def _test_audio(self) -> None:
        self.win.toggle_audio_output()
        self.audio_now.setText(
            "当前输出：" + (self.win.current_audio_name() or "没读到设备")
        )

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.cfg = win.cfg
        self.setWindowTitle("设置")
        self.setFixedWidth(760)
        self.setStyleSheet(qss())
        # 默认就开高一点：版本与更新那一页整页露出来，不用往下滚
        try:
            avail = QtWidgets.QApplication.primaryScreen().availableGeometry()
            want = min(880, max(560, avail.height() - 40))
            self.resize(760, want)
        except Exception:  # noqa: BLE001
            self.resize(760, 700)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        body = QtWidgets.QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self.nav = QtWidgets.QListWidget()
        self.nav.setFixedWidth(104)
        self.nav.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.nav.setStyleSheet(
            "QListWidget { background:#0d1319; border:none; color:#94a3b2; font-size:13px; outline:none; padding-top:6px; }"
            "QListWidget::item { height:36px; padding-left:16px; }"
            "QListWidget::item:selected { background:#152129; color:#37e6cd; }"
        )
        for name in ("通用", "热键", "显示", "外观", "音频", "高级", "版本与更新"):
            self.nav.addItem(name)
        body.addWidget(self.nav)

        self.stack = QtWidgets.QStackedWidget()
        body.addWidget(self.stack, 1)
        outer.addLayout(body, 1)

        def _mk_page():
            sc = QtWidgets.QScrollArea()
            sc.setWidgetResizable(True)
            sc.setFrameShape(QtWidgets.QFrame.NoFrame)
            sc.setMinimumHeight(470)
            holder = QtWidgets.QWidget()
            v = QtWidgets.QVBoxLayout(holder)
            v.setContentsMargins(20, 14, 20, 12)
            v.setSpacing(9)
            sc.setWidget(holder)
            return sc, v

        page_general, lay_general = _mk_page()
        page_hotkey, lay_hotkey = _mk_page()
        page_display, lay_display = _mk_page()
        page_skin, lay_skin = _mk_page()
        page_audio, lay_audio = _mk_page()
        page_adv, lay_adv = _mk_page()
        page_version, lay_version = _mk_page()
        for sc in (page_general, page_hotkey, page_display, page_skin, page_audio,
                   page_adv, page_version):
            self.stack.addWidget(sc)
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.nav.setCurrentRow(0)

        lay = lay_general
        tip_general = QtWidgets.QLabel("开机和关窗口时的行为；选好就能一直放着不管。")
        tip_general.setObjectName("Small")
        tip_general.setWordWrap(True)
        lay.addWidget(tip_general)

        # ---------- 行为 ----------
        lay.addWidget(self._group("行为"))
        self.chk_autostart = QtWidgets.QCheckBox("开机自启（登录后静默进托盘）")
        self.chk_autostart.setChecked(autostart_enabled())
        self.chk_autostart.toggled.connect(lambda v: self.win.set_autostart_enabled(v))
        lay.addWidget(self.chk_autostart)

        lay = lay_hotkey
        tip_hk = QtWidgets.QLabel(
            "点右边按钮再按组合键就能改；每行前面的勾是单独开关，去掉就不注册这一个。"
        )
        tip_hk.setObjectName("Small")
        tip_hk.setWordWrap(True)
        lay.addWidget(tip_hk)

        self.chk_hotkey = QtWidgets.QCheckBox("启用全局热键")
        self.chk_hotkey.setChecked(self.cfg.hotkey_enabled)
        self.chk_hotkey.toggled.connect(lambda v: self.win.set_hotkey_enabled(v))
        lay.addWidget(self.chk_hotkey)

        lay.addWidget(self._group("热键（点一下按钮，再按你想用的组合；按 Esc 取消）"))
        self._hk_buttons = {}
        self._hk_checks = {}
        self._hk_actual = {}
        for key, label, default in HOTKEY_ACTIONS:
            row_hk = QtWidgets.QHBoxLayout()
            row_hk.setSpacing(8)

            chk = QtWidgets.QCheckBox("")
            chk.setFixedWidth(20)
            chk.setChecked(bool((self.cfg.hotkey_on or {}).get(key, True)))
            chk.setToolTip("单独控制这一个热键：去掉勾就不注册它，别的照常用")
            chk.toggled.connect(lambda v, k=key: self._set_hk_on(k, v))
            row_hk.addWidget(chk)
            self._hk_checks[key] = chk

            lb = QtWidgets.QLabel(label)
            lb.setMinimumWidth(126)
            row_hk.addWidget(lb)
            btn = KeyCaptureButton()
            btn.set_hotkey_text(self.cfg.hotkeys.get(key, default))
            btn.captured.connect(lambda text, k=key: self._set_hotkey(k, text))
            row_hk.addWidget(btn, 1)
            self._hk_buttons[key] = btn

            actual_lb = QtWidgets.QLabel("")
            actual_lb.setFixedWidth(118)
            actual_lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            row_hk.addWidget(actual_lb)
            self._hk_actual[key] = actual_lb
            lay.addLayout(row_hk)
        if not self.win.cfg.hotkey_enabled:
            for btn in self._hk_buttons.values():
                btn.setEnabled(False)
            for chk in self._hk_checks.values():
                chk.setEnabled(False)
        self.chk_hotkey.toggled.connect(self._on_hotkey_switch)

        b_default = QtWidgets.QPushButton("恢复默认热键")
        b_default.setObjectName("Ghost")
        b_default.clicked.connect(self._reset_hotkeys)
        lay.addWidget(b_default)

        lay = lay_general
        self.chk_tray = QtWidgets.QCheckBox("关闭窗口时收进托盘（不退出程序）")
        self.chk_tray.setChecked(self.cfg.close_to_tray)
        self.chk_tray.toggled.connect(self._on_tray_close)
        lay.addWidget(self.chk_tray)

        # ---------- 手机：剪贴板开关 ----------
        lay.addWidget(self._group("手机 · 剪贴板"))
        self.chk_clip = QtWidgets.QCheckBox("启用剪贴板（手机能看到电脑上复制的文字）")
        self.chk_clip.setToolTip(
            "关掉之后电脑不再记录复制内容，手机页面里那一页也跟着停；"
            "传文件、看电脑状态、遥控音乐都不受影响"
        )
        self.chk_clip.setChecked(bool(getattr(self.cfg, "clip_enabled", True)))
        self.chk_clip.toggled.connect(self._on_clip_switch)
        lay.addWidget(self.chk_clip)

        # ---------- 手机传来的文件存哪（改一次一直生效） ----------
        lay.addWidget(self._group("手机传来的文件"))
        self.recv_lb = QtWidgets.QLabel("")
        self.recv_lb.setObjectName("Small")
        self.recv_lb.setWordWrap(True)
        lay.addWidget(self.recv_lb)

        row_recv = QtWidgets.QHBoxLayout()
        row_recv.setSpacing(8)
        b_recv = QtWidgets.QPushButton("选个文件夹…")
        b_recv.setObjectName("Mini")
        b_recv.setToolTip("手机传上来的文件以后都存这里；改一次就一直生效，重启也记得")
        b_recv.clicked.connect(self._pick_recv_dir)
        row_recv.addWidget(b_recv)
        b_recv_def = QtWidgets.QPushButton("恢复默认")
        b_recv_def.setObjectName("Mini")
        b_recv_def.setToolTip("回到程序目录下的「收到」")
        b_recv_def.clicked.connect(self._reset_recv_dir)
        row_recv.addWidget(b_recv_def)
        row_recv.addStretch(1)
        lay.addLayout(row_recv)
        self._refresh_recv_label()

        lay = lay_skin
        lay.addWidget(self._group("窗口外观"))
        self.cmb_win = QtWidgets.QComboBox()
        self.cmb_win.addItem("经典（带系统标题栏）", "classic")
        self.cmb_win.addItem("毛玻璃（无边框 + 半透明 + 圆角）", "glass")
        self.cmb_win.addItem("液态玻璃（更透 + 厚亮边 + 顶反光）", "liquid")
        cur_mode = getattr(self.cfg, "window_mode", "classic") or "classic"
        self.cmb_win.setCurrentIndex(max(0, self.cmb_win.findData(cur_mode)))
        self.cmb_win.currentIndexChanged.connect(self._on_win_mode)
        lay.addWidget(self.cmb_win)

        row_blur = QtWidgets.QHBoxLayout()
        row_blur.setSpacing(8)
        lb_blur = QtWidgets.QLabel("背景模糊")
        lb_blur.setFixedWidth(56)
        self.sld_blur = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.sld_blur.setRange(0, 40)
        self.sld_blur.setSingleStep(2)
        self.sld_blur.setValue(max(0, min(40, int(getattr(self.cfg, "art_blur", 18)))))
        self.sld_blur.valueChanged.connect(self._on_blur)
        self.lb_blur_val = QtWidgets.QLabel(str(self.sld_blur.value()))
        self.lb_blur_val.setFixedWidth(26)
        self.lb_blur_val.setObjectName("Small")
        row_blur.addWidget(lb_blur)
        row_blur.addWidget(self.sld_blur, 1)
        row_blur.addWidget(self.lb_blur_val)
        lay.addLayout(row_blur)

        tip_win = QtWidgets.QLabel("模糊只作用于毛玻璃模式的背景图；这模式没有系统标题栏，标题左边那一片可以直接拖窗口。")
        tip_win.setObjectName("Hint")
        tip_win.setWordWrap(True)
        lay.addWidget(tip_win)

        lay.addWidget(self._group("皮肤"))
        tip_skin = QtWidgets.QLabel("只换颜色，不动布局；点哪套就用哪套，立刻生效，不用重启。")
        tip_skin.setObjectName("Small")
        tip_skin.setWordWrap(True)
        lay.addWidget(tip_skin)
        self._skin_rows = QtWidgets.QVBoxLayout()
        self._skin_rows.setSpacing(6)
        lay.addLayout(self._skin_rows)
        self._fill_skin_rows()

        row_skin = QtWidgets.QHBoxLayout()
        row_skin.setSpacing(8)
        bt_skin_imp = QtWidgets.QPushButton("导入皮肤文件…")
        bt_skin_imp.setObjectName("Ghost")
        bt_skin_imp.clicked.connect(self._skin_import)
        bt_skin_dir = QtWidgets.QPushButton("打开皮肤文件夹")
        bt_skin_dir.setObjectName("Ghost")
        bt_skin_dir.clicked.connect(self._skin_folder)
        row_skin.addWidget(bt_skin_imp)
        row_skin.addWidget(bt_skin_dir)
        row_skin.addStretch(1)
        lay.addLayout(row_skin)

        note_skin = QtWidgets.QLabel(
            "想自己做一套：打开皮肤文件夹，照着「自定义示例.json」改颜色，存成任意名字再进来导入。"
        )
        note_skin.setObjectName("Hint")
        note_skin.setWordWrap(True)
        lay.addWidget(note_skin)

        lay.addWidget(self._group("壁纸"))
        self.chk_art = QtWidgets.QCheckBox("显示壁纸（铺满整窗，半透明垫底）")
        self.chk_art.setChecked(bool(getattr(self.cfg, "art_show", False)))
        self.chk_art.toggled.connect(self._on_art_toggle)
        lay.addWidget(self.chk_art)

        self.lb_art = QtWidgets.QLabel(self._art_text())
        self.lb_art.setObjectName("Hint")
        self.lb_art.setWordWrap(True)
        lay.addWidget(self.lb_art)

        row_art = QtWidgets.QHBoxLayout()
        row_art.setSpacing(8)
        bt_art_pick = QtWidgets.QPushButton("选择图片…")
        bt_art_pick.setObjectName("Ghost")
        bt_art_pick.clicked.connect(self._art_pick)
        bt_art_clear = QtWidgets.QPushButton("清空")
        bt_art_clear.setObjectName("Ghost")
        bt_art_clear.clicked.connect(self._art_clear)
        row_art.addWidget(bt_art_pick)
        row_art.addWidget(bt_art_clear)
        row_art.addStretch(1)
        lay.addLayout(row_art)

        note_art = QtWidgets.QLabel(
            "png / jpg / webp / bmp 都行，竖图效果最好。选进来会拷到 art 文件夹，原图不动。"
        )
        note_art.setObjectName("Hint")
        note_art.setWordWrap(True)
        lay.addWidget(note_art)

        lay.addStretch(1)

        lay = lay_audio
        tip_audio = QtWidgets.QLabel("两台设备之间来回切；热键默认为 Alt+Z，可在「热键」页改。")
        tip_audio.setObjectName("Small")
        tip_audio.setWordWrap(True)
        lay.addWidget(tip_audio)

        # ---------- 音频 ----------
        lay.addWidget(self._group("音频输出（热键 Alt+Z，托盘小喇叭双击也一样）"))
        self.audio_now = QtWidgets.QLabel(
            "当前输出：" + (self.win.current_audio_name() or "没读到设备")
        )
        self.audio_now.setObjectName("Small")
        lay.addWidget(self.audio_now)

        devs = self.win._audio_devices()
        self.audio_a_box = QtWidgets.QComboBox()
        self.audio_b_box = QtWidgets.QComboBox()
        for key, box, tag in (
            ("audio_a", self.audio_a_box, "A"),
            ("audio_b", self.audio_b_box, "B"),
        ):
            row = QtWidgets.QHBoxLayout()
            row.setSpacing(8)
            lab = QtWidgets.QLabel(f"设备 {tag}")
            lab.setFixedWidth(46)
            row.addWidget(lab)
            box.setMinimumWidth(300)
            box.addItem("未选（点这里清空）", "")
            for dev_id, dev_name in devs:
                box.addItem(dev_name, dev_id)
            cur = (getattr(self.cfg, key, "") or "").lower()
            hit = 0
            for k in range(box.count()):
                if cur and (box.itemData(k) or "").lower() == cur:
                    hit = k
                    break
            if cur and hit == 0:
                box.addItem("（这个设备现在不在了）", getattr(self.cfg, key, ""))
                hit = box.count() - 1
            box.setCurrentIndex(hit)
            box.setToolTip("A、B 要选两台不同的设备；拔掉的那台会显示「不在了」")
            box.currentIndexChanged.connect(
                lambda _i, k=key, b=box: self.win.set_audio_slot(k, b.currentData())
            )
            row.addWidget(box, 1)
            lay.addLayout(row)

        self.chk_audio_tray = QtWidgets.QCheckBox("任务栏单独放一个小喇叭图标")
        self.chk_audio_tray.setToolTip(
            "关掉之后任务栏就只剩燧镜一个图标，切音频照样能走热键和主托盘菜单"
        )
        self.chk_audio_tray.setChecked(bool(getattr(self.cfg, "audio_tray_icon", True)))
        self.chk_audio_tray.toggled.connect(self._set_audio_tray_icon)
        lay.addWidget(self.chk_audio_tray)

        row_btn = QtWidgets.QHBoxLayout()
        test_btn = QtWidgets.QPushButton("测试切换")
        test_btn.setObjectName("Mini")
        test_btn.setToolTip("点一下就会真的切过去，听声音去了哪")
        test_btn.clicked.connect(self._test_audio)
        row_btn.addWidget(test_btn)
        row_btn.addStretch(1)
        lay.addLayout(row_btn)

        hint_audio = QtWidgets.QLabel(
            "选好 A、B 之后，按 Alt+Z（或双击托盘小喇叭）就在两台之间来回来。"
            "设备拔了会提示「没找到」，不会乱切。"
            "小喇叭图标就算关掉，右键主托盘图标也能切（菜单里有「音频输出」）。"
        )
        hint_audio.setObjectName("Small")
        hint_audio.setWordWrap(True)
        lay.addWidget(hint_audio)

        lay = lay_adv
        tip_adv = QtWidgets.QLabel(
            "回放缓存放哪、别占系统盘，以及打开程序目录、日志这些杂项。"
        )
        tip_adv.setObjectName("Small")
        tip_adv.setWordWrap(True)
        lay.addWidget(tip_adv)

        # ---------- 回放缓存 ----------
        lay.addWidget(self._group("回放缓存（只放最近 10 分钟的临时片段，不是成品）"))
        row_cache = QtWidgets.QHBoxLayout()
        row_cache.setSpacing(8)
        row_cache.addWidget(QtWidgets.QLabel("上限"))
        self.replay_gb_box = QtWidgets.QComboBox()
        for gb in (5, 7, 10):
            self.replay_gb_box.addItem(f"{gb} GB", gb)
        idx = self.replay_gb_box.findData(int(getattr(self.cfg, "replay_max_gb", 5)))
        self.replay_gb_box.setCurrentIndex(max(0, idx))
        self.replay_gb_box.setToolTip("超出上限就从最旧的片段开始删；至少保留够 10 分钟的量")
        self.replay_gb_box.currentIndexChanged.connect(
            lambda _i: self.win.set_replay_max_gb(self.replay_gb_box.currentData())
        )
        row_cache.addWidget(self.replay_gb_box)

        row_cache.addSpacing(14)
        row_cache.addWidget(QtWidgets.QLabel("缓存盘"))
        self.replay_drive_box = QtWidgets.QComboBox()
        self.replay_drive_box.addItem("程序所在盘", "")
        for letter, free in list_drives():
            self.replay_drive_box.addItem(
                f"{letter}  剩 {free / 1024 ** 3:.0f} GB", str(Path(f"{letter}\\燧镜缓存"))
            )
        di = self.replay_drive_box.findData(getattr(self.cfg, "replay_dir", "") or "")
        self.replay_drive_box.setCurrentIndex(max(0, di))
        self.replay_drive_box.setToolTip("回放缓冲写在哪块盘；想少占系统盘就换一块")
        self.replay_drive_box.currentIndexChanged.connect(
            lambda _i: self.win.set_replay_dir(self.replay_drive_box.currentData())
        )
        row_cache.addWidget(self.replay_drive_box)
        row_cache.addStretch(1)
        lay.addLayout(row_cache)

        self.replay_cache_info = QtWidgets.QLabel(self.win.replay_cache_text())
        self.replay_cache_info.setObjectName("Small")
        lay.addWidget(self.replay_cache_info)

        # ---------- 素材存放位置 ----------
        lay.addWidget(self._group("素材存放位置（截图 + 录屏成品 + 素材库）"))
        row_media = QtWidgets.QHBoxLayout()
        row_media.setSpacing(8)
        row_media.addWidget(QtWidgets.QLabel("位置"))
        self.media_dir_box = QtWidgets.QComboBox()
        self.media_dir_box.setMinimumWidth(190)
        self.media_dir_box.addItem("程序所在盘（默认）", "")
        for letter, free in list_drives():
            self.media_dir_box.addItem(
                f"{letter}  剩 {free / 1024 ** 3:.0f} GB", str(Path(f"{letter}\\燧镜素材"))
            )
        cur_media = getattr(self.cfg, "media_dir", "") or ""
        mi = self.media_dir_box.findData(cur_media)
        if mi < 0 and cur_media:
            self.media_dir_box.addItem(f"自定义（{Path(cur_media).anchor}）", cur_media)
            mi = self.media_dir_box.count() - 1
        self.media_dir_box.setCurrentIndex(max(0, mi))
        self.media_dir_box.setToolTip("截图和录屏成品写在哪；想放别的盘就换一块")
        self.media_dir_box.currentIndexChanged.connect(
            lambda _i: self._apply_media(self.media_dir_box.currentData())
        )
        row_media.addWidget(self.media_dir_box)

        btn_pick_media = QtWidgets.QPushButton("选文件夹…")
        btn_pick_media.setToolTip("任意目录都行，不限于上面这几个盘")
        btn_pick_media.clicked.connect(self._pick_media_dir)
        row_media.addWidget(btn_pick_media)

        btn_media_reset = QtWidgets.QPushButton("恢复默认")
        btn_media_reset.clicked.connect(lambda: self._apply_media(""))
        row_media.addWidget(btn_media_reset)
        row_media.addStretch(1)
        lay.addLayout(row_media)

        self.media_info = QtWidgets.QLabel(self.win.media_info_text())
        self.media_info.setObjectName("Small")
        self.media_info.setWordWrap(True)
        lay.addWidget(self.media_info)

        hint_media = QtWidgets.QLabel(
            "旧位置已有素材时，换位置会问你要不要一起搬过去（日期目录保留，素材页立刻能看到）；"
            "搬大文件有进度条，可以取消。"
            "回放的临时缓存是上面「回放缓存」那组单独设的，想一起换就改那边的「缓存盘」。"
        )
        hint_media.setObjectName("Small")
        hint_media.setWordWrap(True)
        lay.addWidget(hint_media)

        # ---------- 测速节点 ----------
        lay.addWidget(self._group("网络测速：额外打一个游戏服务器"))
        row_ping = QtWidgets.QHBoxLayout()
        row_ping.setSpacing(8)
        self.ping_host_edit = QtWidgets.QLineEdit(getattr(self.cfg, "ping_host", "") or "")
        self.ping_host_edit.setPlaceholderText("例如 game.example.com:9000（留空就只测公共节点）")
        self.ping_host_edit.setToolTip(
            "填你常玩那个服的地址；测速时会额外打它，单独出一行延迟"
        )
        self.ping_host_edit.editingFinished.connect(self._on_ping_host)
        row_ping.addWidget(self.ping_host_edit, 1)
        lay.addLayout(row_ping)
        hint_ping = QtWidgets.QLabel(
            "公共节点只能说明你家宽带好不好；到游戏服这条路绕不绕，得打游戏服才知道。"
            "不确定地址就留空；游戏服常只开 UDP，连不上不代表服务器差。"
        )
        hint_ping.setObjectName("Small")
        hint_ping.setWordWrap(True)
        lay.addWidget(hint_ping)

        lay = lay_display
        tip_display = QtWidgets.QLabel(
            "桌面上的两个小窗（每日密码、帧率）都在这里；它们都能单独开关、单独设穿透。"
        )
        tip_display.setObjectName("Small")
        tip_display.setWordWrap(True)
        lay.addWidget(tip_display)

        # ---------- 显示 ----------
        lay.addWidget(self._group("显示"))
        self.chk_stretch = QtWidgets.QCheckBox("嘉豪模式 · 4:3 拉满去黑边")
        self.chk_stretch.setChecked(self.cfg.stretch)
        self.chk_stretch.toggled.connect(self._on_stretch)
        lay.addWidget(self.chk_stretch)

        self.chk_hud = QtWidgets.QCheckBox("每日密码悬浮窗（只显示当天密码，常驻桌面）")
        self.chk_hud.setChecked(self.cfg.hud_show)
        self.chk_hud.setToolTip("打开后在屏幕角落贴一张只有密码的小卡片，游戏里也能瞄一眼")
        self.chk_hud.toggled.connect(self.win.set_hud_enabled)
        lay.addWidget(self.chk_hud)

        row_hud = QtWidgets.QHBoxLayout()
        row_hud.addWidget(QtWidgets.QLabel("悬浮窗位置"))
        self.hud_side_box = QtWidgets.QComboBox()
        for label, key in (("右侧", "right"), ("左侧", "left")):
            self.hud_side_box.addItem(label, key)
        self.hud_side_box.setCurrentIndex(max(0, self.hud_side_box.findData(self.cfg.hud_side or "right")))
        self.hud_side_box.currentIndexChanged.connect(
            lambda _i: self.win.set_hud_side(self.hud_side_box.currentData() or "right"))
        row_hud.addWidget(self.hud_side_box)
        row_hud.addStretch(1)
        lay.addLayout(row_hud)

        self.chk_hud_through = QtWidgets.QCheckBox("鼠标穿透（不挡点击，游戏里操作照常）")
        self.chk_hud_through.setChecked(bool(self.cfg.hud_click_through))
        self.chk_hud_through.setToolTip("开着时鼠标直接穿过去；关掉才能右键这个小窗调字号")
        self.chk_hud_through.toggled.connect(lambda v: self.win.set_hud_through(v))
        lay.addWidget(self.chk_hud_through)

        lay.addWidget(self._group("帧率悬浮窗"))

        row_fps_chk = QtWidgets.QHBoxLayout()
        row_fps_chk.setSpacing(6)
        self.chk_fps = QtWidgets.QCheckBox("显示帧率悬浮窗（跟当前前台游戏走）")
        self.chk_fps.setChecked(bool(self.cfg.fps_show))
        self.chk_fps.setToolTip("用 PresentMon 读真实帧率，角落一个小方块，低帧会变色")
        self.chk_fps.toggled.connect(self.win.set_fps_enabled)
        row_fps_chk.addWidget(self.chk_fps)

        # 读不到帧的时候冒出一个小问号，点它告诉你为什么
        self.fps_why = QtWidgets.QPushButton("?")
        self.fps_why.setObjectName("FpsWhy")
        self.fps_why.setFixedSize(22, 22)
        self.fps_why.setToolTip("读不到帧率，点一下看原因")
        self.fps_why.clicked.connect(self._show_fps_why)
        self.fps_why.setVisible(self._fps_looks_broken())
        row_fps_chk.addSpacing(6)
        row_fps_chk.addWidget(self.fps_why)
        row_fps_chk.addStretch(1)
        lay.addLayout(row_fps_chk)

        try:
            self.win.fps_mon.hint.connect(self._on_fps_hint)
        except (AttributeError, TypeError):
            pass

        row_fps = QtWidgets.QHBoxLayout()
        row_fps.addWidget(QtWidgets.QLabel("位置"))
        self.fps_side_box = QtWidgets.QComboBox()
        for label, key in (("右侧", "right"), ("左侧", "left")):
            self.fps_side_box.addItem(label, key)
        self.fps_side_box.setCurrentIndex(
            max(0, self.fps_side_box.findData(getattr(self.cfg, "fps_side", "right"))))
        self.fps_side_box.currentIndexChanged.connect(
            lambda _i: self.win.set_fps_side(self.fps_side_box.currentData() or "right"))
        row_fps.addWidget(self.fps_side_box)

        row_fps.addWidget(QtWidgets.QLabel("字号"))
        self.fps_scale_box = QtWidgets.QSpinBox()
        self.fps_scale_box.setRange(12, 36)
        self.fps_scale_box.setValue(int(getattr(self.cfg, "fps_scale", 20)))
        self.fps_scale_box.valueChanged.connect(
            lambda v: self.win.set_fps_scale(v))
        row_fps.addWidget(self.fps_scale_box)
        row_fps.addStretch(1)
        lay.addLayout(row_fps)

        self.chk_fps_through = QtWidgets.QCheckBox("帧率窗鼠标穿透（不挡游戏点击）")
        self.chk_fps_through.setChecked(bool(getattr(self.cfg, "fps_click_through", True)))
        self.chk_fps_through.setToolTip("关掉才能拖动它、右键调位置")
        self.chk_fps_through.toggled.connect(self.win.set_fps_through)
        lay.addWidget(self.chk_fps_through)

        # ---- 显示器识别
        lay.addWidget(self._group("显示器识别"))
        self.btn_reidentify = QtWidgets.QPushButton("重新识别本机显示器")
        self.btn_reidentify.setObjectName("Ghost")
        self.btn_reidentify.setToolTip("换了显示器或调过缩放后点它，按本机真实支持的模式重记原生基准")
        self.btn_reidentify.clicked.connect(self.win.reidentify_machine)
        lay.addWidget(self.btn_reidentify)

        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("显卡厂家"))
        self.vendor = QtWidgets.QComboBox()
        for label, key in (
            ("自动", "auto"),
            ("NVIDIA", "nvidia"),
            ("AMD", "amd"),
            ("Intel", "intel"),
        ):
            self.vendor.addItem(label, key)
        idx = self.vendor.findData(self.cfg.gpu_vendor or "auto")
        self.vendor.setCurrentIndex(max(0, idx))
        self.vendor.currentIndexChanged.connect(self._on_vendor)
        row.addWidget(self.vendor)
        row.addStretch(1)
        lay.addLayout(row)

        lay = lay_adv
        # ---------- 其它 ----------
        lay.addWidget(self._group("其它"))
        row2 = QtWidgets.QHBoxLayout()
        b_dir = QtWidgets.QPushButton("打开程序目录")
        b_dir.setObjectName("Ghost")
        b_dir.clicked.connect(lambda: os.startfile(str(app_dir())))
        b_log = QtWidgets.QPushButton("查看日志")
        b_log.setObjectName("Ghost")
        b_log.clicked.connect(self._open_log)
        b_guide = QtWidgets.QPushButton("新手引导")
        b_guide.setObjectName("Ghost")
        b_guide.clicked.connect(lambda: self.win.show_guide(force=True))
        b_exp = QtWidgets.QPushButton("导出配置")
        b_exp.setObjectName("Ghost")
        b_exp.setToolTip("把热键、工具、档位这些打包成一个 json，换电脑用")
        b_exp.clicked.connect(self._export_config)
        b_imp = QtWidgets.QPushButton("导入配置")
        b_imp.setObjectName("Ghost")
        b_imp.setToolTip("读别人（或你自己）导出的 json；导入后重启生效")
        b_imp.clicked.connect(self._import_config)
        row2.addWidget(b_dir)
        row2.addWidget(b_log)
        row2.addWidget(b_guide)
        row2.addWidget(b_exp)
        row2.addWidget(b_imp)
        row2.addStretch(1)
        lay.addLayout(row2)

        self._refresh_hk_actual()

        self._build_version_page(lay_version)

        for _v in (lay_general, lay_hotkey, lay_display, lay_audio, lay_adv, lay_version):
            _v.addStretch(1)

        btns = QtWidgets.QHBoxLayout()
        btns.setContentsMargins(16, 8, 16, 12)
        btns.addStretch(1)
        ok = QtWidgets.QPushButton("完成")
        ok.setObjectName("Ghost")
        ok.setMinimumWidth(96)
        ok.clicked.connect(self.accept)
        btns.addWidget(ok)
        outer.addLayout(btns)

    # ------------------------------------------------------------ 版本与更新
    def _fps_looks_broken(self) -> bool:
        """判断"现在是不是真的读不到帧"，用来决定问号冒不冒出来。"""
        mon = getattr(self.win, "fps_mon", None)
        if mon is None:
            return False
        if (getattr(mon, "error_text", "") or "").strip():
            return True
        # 已经判定过一次没有数据，或者开着却一直没数（给 12 秒启动时间）
        if getattr(self.cfg, "fps_show", False) and getattr(mon, "current", 0) <= 0:
            started = getattr(mon, "_started_at", 0) or 0
            return (time.time() - started) > 12
        return False

    def _on_fps_hint(self, text: str) -> None:
        """帧率读不到 / 读回来了：问号的显隐跟着走。"""
        try:
            self.fps_why.setVisible(bool((text or "").strip()))
        except RuntimeError:
            pass

    def _show_fps_why(self) -> None:
        """点问号：说清楚为什么读不到帧率。"""
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("为什么读不到帧率")
        dlg.resize(600, 580)
        box = QtWidgets.QVBoxLayout(dlg)
        box.setContentsMargins(14, 12, 14, 12)
        body = QtWidgets.QTextEdit()
        body.setReadOnly(True)
        body.setPlainText(fps.explain())
        box.addWidget(body, 1)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        b_ok = QtWidgets.QPushButton("知道了")
        b_ok.clicked.connect(dlg.accept)
        row.addWidget(b_ok)
        box.addLayout(row)
        dlg.exec()

    def _build_version_page(self, lay) -> None:
        """版本、指纹、检查更新、更新日志、作者 —— 原来「关于」的东西都在这里。"""
        icon = QtWidgets.QLabel()
        icon.setPixmap(app_icon().pixmap(56, 56))
        icon.setAlignment(Qt.AlignHCenter)
        lay.addWidget(icon)

        name = QtWidgets.QLabel(APP_NAME)
        name.setAlignment(Qt.AlignCenter)
        name.setStyleSheet("font-size:18px;font-weight:700;color:#f0f4fa;")
        lay.addWidget(name)

        ver = QtWidgets.QLabel(f"{APP_NAME_EN} · {APP_VERSION}")
        ver.setAlignment(Qt.AlignCenter)
        ver.setStyleSheet("color:#20ffe0;font-size:12px;font-weight:600;")
        lay.addWidget(ver)

        self.fp_text = ""
        fp = file_fingerprint()
        if fp:
            self.fp_text = (
                f"{fp['name']} · {fp['mb']:.1f} MB · {fp['mtime']}\n"
                f"SHA256 {fp['sha16']}…"
            )
        fp_label = QtWidgets.QLabel(self.fp_text or "读不到当前文件指纹")
        fp_label.setAlignment(Qt.AlignCenter)
        fp_label.setWordWrap(True)
        fp_label.setStyleSheet("color:#7b8494;font-size:11px;")
        lay.addWidget(fp_label)
        fp_tip = QtWidgets.QLabel("被杀毒拦、或反馈误报时，把上面两行发出来最快")
        fp_tip.setAlignment(Qt.AlignCenter)
        fp_tip.setStyleSheet("color:#5f6b7c;font-size:11px;")
        lay.addWidget(fp_tip)

        # ---- 更新
        lay.addWidget(self._group("更新"))
        self.upd_state = QtWidgets.QLabel("点「检查更新」，看看本机有没有更新的安装包")
        self.upd_state.setWordWrap(True)
        self.upd_state.setStyleSheet("color:#9aa4b4;font-size:12px;")
        lay.addWidget(self.upd_state)

        row = QtWidgets.QHBoxLayout()
        self.upd_check_btn = QtWidgets.QPushButton("检查更新")
        self.upd_check_btn.setObjectName("Ghost")
        self.upd_check_btn.setToolTip("扫程序目录、下载文件夹和桌面，认出比当前版本新的安装包")
        self.upd_check_btn.clicked.connect(self._check_update)
        row.addWidget(self.upd_check_btn)

        self.upd_pick_btn = QtWidgets.QPushButton("选择本地安装包")
        self.upd_pick_btn.setObjectName("Ghost")
        self.upd_pick_btn.setToolTip("安装包放在别的地方？自己指一下")
        self.upd_pick_btn.clicked.connect(self._pick_installer)
        row.addWidget(self.upd_pick_btn)
        row.addStretch(1)
        lay.addLayout(row)

        tip = QtWidgets.QLabel(
            "新版从网盘下下来放进「下载」文件夹就行，这里会自动认出来。"
            "认的是安装包里的版本号，不看文件名，改成什么名字都认得。"
        )
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        # ---- 其它
        lay.addWidget(self._group("其它"))
        row2 = QtWidgets.QHBoxLayout()
        row2.setSpacing(10)
        row2.setContentsMargins(0, 0, 0, 0)
        b_log = QtWidgets.QPushButton("更新日志")
        b_log.setObjectName("Ghost")
        b_log.clicked.connect(lambda: ChangeLogDialog(self).exec())
        row2.addWidget(b_log)
        if self.fp_text:
            b_copy = QtWidgets.QPushButton("复制指纹")
            b_copy.setObjectName("Ghost")
            b_copy.clicked.connect(
                lambda: QtWidgets.QApplication.clipboard().setText(self.fp_text)
            )
            row2.addWidget(b_copy)
        row2.addStretch(1)
        lay.addLayout(row2)

        author = QtWidgets.QLabel(f"作者　{APP_AUTHOR}")
        author.setAlignment(Qt.AlignHCenter)
        author.setStyleSheet("color:#9aa4b4;font-size:12px;margin-top:8px;")
        lay.addWidget(author)

        # ---- 请作者喝杯咖啡：纯自愿、不影响任何功能
        lay.addWidget(self._group("请作者喝杯咖啡 ☕"))
        rw_line = QtWidgets.QLabel("如果燧镜帮到了你，欢迎扫码赞赏支持。")
        rw_line.setAlignment(Qt.AlignHCenter)
        rw_line.setWordWrap(True)
        rw_line.setStyleSheet("color:#c9d3df;font-size:12.5px;")
        lay.addWidget(rw_line)
        rw_note = QtWidgets.QLabel("（纯自愿赠与，不影响任何功能使用）")
        rw_note.setAlignment(Qt.AlignHCenter)
        rw_note.setWordWrap(True)
        rw_note.setStyleSheet("color:#68758a;font-size:11px;")
        lay.addWidget(rw_note)

        rw_row = QtWidgets.QHBoxLayout()
        rw_row.addStretch(1)
        self.reward_qr = _RewardQr(_asset_file("reward_qr.png"), self)
        rw_row.addWidget(self.reward_qr)
        rw_row.addStretch(1)
        lay.addLayout(rw_row)

        rw_tap = QtWidgets.QLabel("点一下图片放大，扫起来更准")
        rw_tap.setAlignment(Qt.AlignHCenter)
        rw_tap.setWordWrap(True)
        rw_tap.setStyleSheet("color:#68758a;font-size:11px;")
        lay.addWidget(rw_tap)
        if self.reward_qr.pixmap().isNull():
            # 兜底：图真没带上也不能留个空框，说清去哪儿看
            rw_tap.setText("赞赏码没随包带上，重下一份完整安装包即可")
            rw_tap.setStyleSheet("color:#ffc9c9;font-size:11px;")
            self.reward_qr.hide()



    def _check_update(self) -> None:
        from core import updater as up

        self.upd_check_btn.setEnabled(False)
        self.upd_state.setText("正在扫描本机的安装包…")
        QtWidgets.QApplication.processEvents()
        try:
            found = up.scan(APP_VERSION)
        except Exception as exc:  # noqa: BLE001
            self.upd_state.setText("扫描失败：" + str(exc))
            self.upd_check_btn.setEnabled(True)
            return
        self.upd_check_btn.setEnabled(True)
        if not found:
            self.upd_state.setText(
                f"没发现新版本（当前 {APP_VERSION}）。拿到新安装包后放进「下载」文件夹，再点这里。"
            )
            return
        best = found[0]
        self.upd_state.setText(
            f"发现 {best.get('version')}　{float(best.get('mb') or 0):.0f} MB　{best.get('mtime')}"
        )
        self._offer_install(best)

    def _pick_installer(self) -> None:
        from core import updater as up

        start = str(Path.home() / "Downloads")
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选一个燧镜安装包", start, "安装包 (*.exe)"
        )
        if not path:
            return
        info = up.file_info(path)
        if not up.looks_like_ours(info):
            self.upd_state.setText("这个文件不像燧镜的安装包（读不到版本信息）")
            return
        if not up.is_newer(info.get("version") or "", APP_VERSION):
            self.upd_state.setText(
                f"这个包是 {info.get('version')}，不比现在的 {APP_VERSION} 新，不用装"
            )
            return
        self.upd_state.setText(
            f"发现 {info.get('version')}　{float(info.get('mb') or 0):.0f} MB　{info.get('mtime')}"
        )
        self._offer_install(info)

    def _offer_install(self, info) -> None:
        from core import updater as up

        path = str(info.get("path") or "")
        r = QtWidgets.QMessageBox.question(
            self,
            "安装新版本",
            f"发现 {info.get('version')}（{float(info.get('mb') or 0):.0f} MB）\n{path}\n\n"
            "现在安装吗？\n配置、素材、工具都会保留，装完自动重开。",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.Yes,
        )
        if r != QtWidgets.QMessageBox.Yes:
            return
        ok, msg = up.launch_installer(path, silent=True)
        self.win.toast(msg, ok)
        if ok:
            self.accept()
            try:
                self.win.close()
            except Exception:  # noqa: BLE001
                pass
            QtWidgets.QApplication.quit()

    @staticmethod
    def _group(text):
        lbl = QtWidgets.QLabel(text)
        lbl.setStyleSheet("color:#7b8494; font-size:11.5px; margin-top:6px;")
        return lbl

    def _on_hotkey(self, key, text):
        """设置页录到一个新组合：存盘并立刻重新注册。"""
        if not text:
            return
        self.cfg.hotkeys[key] = text
        self.cfg.save()
        self.win.reapply_hotkeys()
        actual = (getattr(self.win, "hotkey_actual", {}) or {}).get(key, "")
        if actual and actual != text:
            self.win.toast(f"{text} 被别的软件占了，已改用 {actual}", False)
        elif actual:
            self.win.toast(f"{HOTKEY_LABEL.get(key, key)}：{text}")
        else:
            self.win.toast(f"{text} 注册不上，换个键试试", False)

    def _on_hotkey_switch(self, on):
        for btn in getattr(self, "_hk_buttons", {}).values():
            btn.setEnabled(bool(on))

    def _reset_hotkeys(self):
        self.cfg.hotkeys = dict(DEFAULT_HOTKEYS)
        self.cfg.save()
        for key, btn in getattr(self, "_hk_buttons", {}).items():
            btn.set_hotkey_text(DEFAULT_HOTKEYS.get(key, ""))
        self.win.reapply_hotkeys()
        self.win.toast("热键已恢复默认")

    def _refresh_recv_label(self) -> None:
        custom = getattr(self.win.cfg, "recv_dir", "")
        root = self.win.tools_card.lan.recv_root
        if custom:
            self.recv_lb.setText(f"现在存到：{root}（你指定的文件夹）")
        else:
            self.recv_lb.setText(f"现在存到：{root}（默认，程序目录下的「收到」）")

    def _pick_recv_dir(self) -> None:
        if self.win.change_recv_dir():
            self._refresh_recv_label()

    def _reset_recv_dir(self) -> None:
        self.win.cfg.recv_dir = ""
        try:
            self.win.cfg.save()
        except Exception:  # noqa: BLE001
            pass
        self.win.toast("恢复默认：手机传上来的存到程序目录下的「收到」")
        self._refresh_recv_label()

    def _on_clip_switch(self, checked):
        self.cfg.clip_enabled = bool(checked)
        self.cfg.save()
        self.win.toast("剪贴板：" + ("已启用" if checked else "已关闭"))

    def _on_tray_close(self, checked):
        self.cfg.close_to_tray = checked
        self.cfg.save()
        self.win.toast("关闭窗口：" + ("收进托盘" if checked else "直接退出程序"))

    def _on_stretch(self, checked):
        self.win.set_stretch(checked)
        self.chk_stretch.setChecked(self.cfg.stretch)

    def _pick_media_dir(self) -> None:
        start = str(capture.media_root())
        picked = QtWidgets.QFileDialog.getExistingDirectory(
            self, "选素材存放位置（截图和录屏放这里）", start
        )
        if picked:
            self._apply_media(picked)

    def _apply_media(self, path) -> None:
        path = str(path or "").strip()
        self.win.set_media_dir(path)
        self.media_dir_box.blockSignals(True)
        idx = self.media_dir_box.findData(path)
        if idx < 0 and path:
            self.media_dir_box.addItem(f"自定义（{Path(path).anchor}）", path)
            idx = self.media_dir_box.count() - 1
        self.media_dir_box.setCurrentIndex(max(0, idx))
        self.media_dir_box.blockSignals(False)
        if hasattr(self, "media_info"):
            self.media_info.setText(self.win.media_info_text())

    def _on_ping_host(self):
        self.win.set_ping_host(self.ping_host_edit.text())
        self.ping_host_edit.setText(getattr(self.cfg, "ping_host", "") or "")

    def _on_vendor(self, _index):
        v = self.vendor.currentData() or "auto"
        self.cfg.gpu_vendor = v
        self.cfg.save()
        idx = self.win.vendor_combo.findData(v)
        self.win.vendor_combo.setCurrentIndex(max(0, idx))

    def _open_log(self):
        logdir = app_dir() / "logs"
        if logdir.exists():
            os.startfile(str(logdir))
        else:
            self.win.toast("还没有日志目录，先运行一次程序", False)


# ---------------------------------------------------------------------------
# 自动化：动作行 / 规则编辑 / 规则管理
# ---------------------------------------------------------------------------

class PowerCard(QtWidgets.QFrame):
    """工具页的电源计划卡：一键在节能 / 平衡 / 高性能 / 卓越之间切。

    只用 GUID 定位，所以英文系统、用户自建并改名的计划都不会认错。
    """

    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self.setObjectName("Card")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 11, 16, 11)
        lay.setSpacing(8)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("电源计划")
        title.setObjectName("Section")
        head.addWidget(title)
        hint = QtWidgets.QLabel("打游戏切高性能，平常切平衡省电")
        hint.setObjectName("Small")
        head.addWidget(hint)
        head.addStretch(1)
        self.btn_refresh = QtWidgets.QPushButton("刷新")
        self.btn_refresh.setObjectName("Mini")
        self.btn_refresh.clicked.connect(self.refresh)
        head.addWidget(self.btn_refresh)
        lay.addLayout(head)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        self.state = QtWidgets.QLabel("读取中…")
        self.state.setObjectName("Small")
        self.state.setMinimumWidth(120)
        row.addWidget(self.state)
        row.addSpacing(6)
        self._btns = {}
        for name in ("节能", "平衡", "高性能", "卓越性能"):
            b = QtWidgets.QPushButton(name)
            b.setObjectName("Mini")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _=False, n=name: self._apply(n))
            self._btns[name] = b
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)

        QTimer.singleShot(200, self.refresh)

    def refresh(self) -> None:
        plans = power.find_known(power.KNOWN)
        # find_known 返回的是 (名字, GUID)，别把元组解反了
        alive = {gid for _, gid in plans}
        gid, name = power.current()
        self.state.setText("当前：" + (name or "读不到"))
        for n, b in self._btns.items():
            b.setVisible(power.KNOWN[n] in alive)
            try:
                b.setChecked(bool(gid) and gid == power.KNOWN[n])
            except Exception:  # noqa: BLE001
                b.setChecked(False)

    def _apply(self, name: str) -> None:
        guid = power.KNOWN.get(name, "")
        ok, msg = power.set_active(guid)
        if ok:
            self.win.toast("电源计划已切到 " + msg)
        else:
            self.win.toast("切换失败：" + msg, False)
        self.refresh()


class CrossCard(QtWidgets.QFrame):
    """工具页的准星卡：开关 + 样式 + 颜色 + 臂长/粗细/间隙/浓度。

    准星是画在一块铺满屏幕的透明窗口上，所以跟游戏画面无关：
    游戏要跑「无边框窗口」，全屏独占会把这层盖掉。
    """

    COLORS = ("#20ffe0", "#ffffff", "#ff5c5c", "#ffe066", "#8bc8ea")

    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self.cfg = win.cfg
        self.setObjectName("Card")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 11, 16, 11)
        lay.setSpacing(8)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("准星")
        title.setObjectName("Section")
        head.addWidget(title)
        need = QtWidgets.QLabel("铺满屏幕压在游戏上，鼠标穿透、不挡点击")
        need.setObjectName("Small")
        head.addWidget(need)
        head.addStretch(1)
        self.sw = QtWidgets.QPushButton("开启准星")
        self.sw.setObjectName("Mini")
        self.sw.setCheckable(True)
        self.sw.setMinimumWidth(88)
        self.sw.toggled.connect(self._toggle)
        head.addWidget(self.sw)
        lay.addLayout(head)

        r2 = QtWidgets.QHBoxLayout()
        r2.setSpacing(7)
        r2.addWidget(self._cap("样式"))
        self.cmb_style = QtWidgets.QComboBox()
        self.cmb_style.setFixedWidth(96)
        # 全局 QSS 给 QComboBox 压了 min-width:172px，这里单独解开
        self.cmb_style.setStyleSheet("QComboBox { min-width: 0px; padding: 7px 8px; }")
        for k, n in (("cross", "十字"), ("dot", "点"), ("t", "T 形"), ("circle", "圆环")):
            self.cmb_style.addItem(n, k)
        self.cmb_style.currentIndexChanged.connect(self._style_changed)
        r2.addWidget(self.cmb_style)

        r2.addSpacing(8)
        r2.addWidget(self._cap("颜色"))
        for c in self.COLORS:
            dot = QtWidgets.QPushButton()
            dot.setFixedSize(20, 20)
            dot.setCursor(Qt.PointingHandCursor)
            dot.setToolTip(c)
            dot.setStyleSheet(
                "QPushButton{background:%s;border:1px solid rgba(0,0,0,0.35);"
                "border-radius:10px;}"
                "QPushButton:hover{border:2px solid #20ffe0;}" % c
            )
            dot.clicked.connect(lambda _=False, cc=c: self._set_color(cc))
            r2.addWidget(dot)
        self.btn_any = QtWidgets.QPushButton("自选")
        self.btn_any.setObjectName("Mini")
        self.btn_any.clicked.connect(self._any_color)
        r2.addWidget(self.btn_any)

        r2.addStretch(1)
        self.cb_dot = QtWidgets.QCheckBox("中心点")
        self.cb_dot.toggled.connect(self._flag_changed)
        r2.addWidget(self.cb_dot)
        self.cb_out = QtWidgets.QCheckBox("黑描边")
        self.cb_out.setToolTip("在准星外面包一圈半透明黑边，雪地白墙上也看得见")
        self.cb_out.toggled.connect(self._flag_changed)
        r2.addWidget(self.cb_out)
        lay.addLayout(r2)

        r3 = QtWidgets.QHBoxLayout()
        r3.setSpacing(10)
        self.sld_size = self._slider(r3, "臂长", 2, 90, "cross_size")
        self.sld_th = self._slider(r3, "粗细", 1, 10, "cross_thickness")
        lay.addLayout(r3)

        r4 = QtWidgets.QHBoxLayout()
        r4.setSpacing(10)
        self.sld_gap = self._slider(r4, "间隙", 0, 60, "cross_gap")
        self.sld_alpha = self._slider(r4, "浓度", 15, 100, "cross_alpha")
        lay.addLayout(r4)

        self._sync()

    # ---------------------------------------------------------- 小工具
    def _mark_switch(self, on: bool) -> None:
        """开着的准星看不见状态，用底色和文字一起说清楚。"""
        self.sw.setText("已开启" if on else "开启准星")
        if on:
            self.sw.setStyleSheet(
                "QPushButton#Mini { background: rgba(32, 255, 224, 0.18);"
                " color: #20ffe0; border: 1px solid rgba(32, 255, 224, 0.45); }"
            )
        else:
            self.sw.setStyleSheet("")

    def _cap(self, text: str) -> QtWidgets.QLabel:
        lb = QtWidgets.QLabel(text)
        lb.setObjectName("Small")
        return lb

    def _slider(self, box, text: str, lo: int, hi: int, attr: str) -> QtWidgets.QSlider:
        cap = QtWidgets.QLabel(text)
        cap.setObjectName("Small")
        cap.setMinimumWidth(28)
        box.addWidget(cap)
        sld = QtWidgets.QSlider(Qt.Horizontal)
        sld.setRange(lo, hi)
        try:
            sld.setValue(int(getattr(self.cfg, attr, lo) or lo))
        except (TypeError, ValueError):
            sld.setValue(lo)
        sld.setMinimumWidth(80)
        box.addWidget(sld, 1)
        val = QtWidgets.QLabel(str(sld.value()))
        val.setObjectName("Small")
        val.setFixedWidth(26)
        box.addWidget(val)
        sld.valueChanged.connect(lambda v, a=attr, lb=val: self._slide(a, v, lb))
        # 松手才落盘，拖动过程不写文件
        sld.sliderReleased.connect(self._commit)
        return sld

    # ---------------------------------------------------------- 交互
    def _toggle(self, checked: bool) -> None:
        self.cfg.cross_show = bool(checked)
        self.cfg.save()
        self._mark_switch(bool(checked))
        try:
            self.win.apply_crosshair()
        except Exception:  # noqa: BLE001
            pass

    def _style_changed(self, *_) -> None:  # noqa: ANN002
        key = self.cmb_style.currentData()
        if key:
            self.cfg.cross_style = str(key)
            self.cfg.save()
            self._refresh()

    def _set_color(self, color: str) -> None:
        self.cfg.cross_color = color
        self.cfg.save()
        self._refresh()

    def _any_color(self) -> None:
        cur = QtGui.QColor(str(getattr(self.cfg, "cross_color", "#20ffe0")))
        col = QtWidgets.QColorDialog.getColor(cur, self, "选准星颜色")
        if col.isValid():
            self._set_color(col.name())

    def _flag_changed(self, *_) -> None:  # noqa: ANN002
        self.cfg.cross_dot = bool(self.cb_dot.isChecked())
        self.cfg.cross_outline = bool(self.cb_out.isChecked())
        self.cfg.save()
        self._refresh()

    def _slide(self, attr: str, val: int, label) -> None:  # noqa: ANN001
        setattr(self.cfg, attr, int(val))
        label.setText(str(int(val)))
        self._refresh()

    def _commit(self) -> None:
        self.cfg.save()

    def _refresh(self) -> None:
        try:
            self.win.crosshair.refresh()
            self.win.apply_crosshair()
        except Exception:  # noqa: BLE001
            pass

    def _sync(self) -> None:
        # 初始化时 setChecked 会发 toggled，不挡掉就会把默认值反向写进配置
        widgets = (self.sw, self.cmb_style, self.cb_dot, self.cb_out)
        for w in widgets:
            w.blockSignals(True)
        on = bool(getattr(self.cfg, "cross_show", False))
        self.sw.setChecked(on)
        self._mark_switch(on)
        idx = self.cmb_style.findData(str(getattr(self.cfg, "cross_style", "cross")))
        self.cmb_style.setCurrentIndex(max(0, idx))
        self.cb_dot.setChecked(bool(getattr(self.cfg, "cross_dot", True)))
        self.cb_out.setChecked(bool(getattr(self.cfg, "cross_outline", True)))
        for w in widgets:
            w.blockSignals(False)


class ScrcpyDialog(QtWidgets.QDialog):
    """手机投屏反控：燧镜只当外壳，真正干活的是一旁 bundled\\scrcpy 里的 scrcpy。"""

    def __init__(self, win) -> None:
        super().__init__(win)
        self.win = win
        self._last_state = ""
        self.setWindowTitle("手机投屏反控")
        self.setMinimumWidth(486)
        self.setStyleSheet(
            qss() + "\nQDialog { background: %s; }" % theme.current().colors.get("bg-page", "#0e1015")
        )
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(11)

        t = QtWidgets.QLabel("手机投屏反控")
        t.setObjectName("Section")
        lay.addWidget(t)

        # ---- 状态 ----
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        v = QtWidgets.QVBoxLayout(card)
        v.setContentsMargins(14, 11, 14, 11)
        v.setSpacing(6)
        h = QtWidgets.QHBoxLayout()
        h.setSpacing(8)
        self.st_title = QtWidgets.QLabel("正在看…")
        self.st_title.setStyleSheet("background:transparent;border:none;font-weight:700;")
        h.addWidget(self.st_title)
        h.addStretch(1)
        rb = QtWidgets.QPushButton("刷新")
        rb.setObjectName("Mini")
        rb.clicked.connect(self.refresh)
        h.addWidget(rb)
        v.addLayout(h)
        self.st_detail = QtWidgets.QLabel("")
        self.st_detail.setObjectName("Small")
        self.st_detail.setWordWrap(True)
        v.addWidget(self.st_detail)
        lay.addWidget(card)

        # ---- 首次使用的引导（认到手机后自动收起） ----
        self.guide = QtWidgets.QFrame()
        self.guide.setObjectName("Card")
        gv = QtWidgets.QVBoxLayout(self.guide)
        gv.setContentsMargins(14, 11, 14, 11)
        gv.setSpacing(4)
        gt = QtWidgets.QLabel("第一次用，手机上要先开一次权限")
        gt.setObjectName("Small")
        gt.setStyleSheet("background:transparent;border:none;font-weight:600;")
        gv.addWidget(gt)
        steps = QtWidgets.QLabel(
            "1. 设置 → 关于手机 → 连点「版本号」7 次，提示「已进入开发者模式」\n"
            "2. 设置 → 系统 / 更多设置 → 开发者选项 → 打开「USB 调试」\n"
            "3. 插数据线（得是能传文件的那种），手机弹「是否允许 USB 调试」→ 勾「一直允许」→ 确定\n"
            "4. 小米 / 红米：开发者选项里的「USB 调试（安全设置）」也打开，否则鼠标点了没反应"
        )
        steps.setObjectName("Small")
        steps.setWordWrap(True)
        steps.setStyleSheet("background:transparent;border:none;line-height:150%;")
        gv.addWidget(steps)
        lay.addWidget(self.guide)

        # ---- 画质 ----
        q_card = QtWidgets.QFrame()
        q_card.setObjectName("Card")
        qh = QtWidgets.QHBoxLayout(q_card)
        qh.setContentsMargins(14, 9, 14, 9)
        qh.setSpacing(8)
        ql = QtWidgets.QLabel("画质")
        ql.setObjectName("Small")
        qh.addWidget(ql)
        self.quality_combo = QtWidgets.QComboBox()
        self.quality_combo.setObjectName("Mini")
        self.quality_combo.setFixedWidth(168)
        for label, key in (("流畅 · 省带宽", "smooth"), ("标准", "normal"), ("高清", "hd")):
            self.quality_combo.addItem(label, key)
        self.quality_combo.setCurrentIndex(1)
        qh.addWidget(self.quality_combo)
        qh.addStretch(1)
        hint = QtWidgets.QLabel("手机屏幕会物理熄灭，电脑上照常看")
        hint.setObjectName("Hint")
        qh.addWidget(hint)
        lay.addWidget(q_card)

        # ---- 无线（默认折起） ----
        self.adv_btn = QtWidgets.QPushButton("无线连接（可选）")
        self.adv_btn.setObjectName("Mini")
        self.adv_btn.setCheckable(True)
        self.adv_btn.toggled.connect(self._toggle_adv)
        lay.addWidget(self.adv_btn, 0, Qt.AlignLeft)

        self.adv = QtWidgets.QFrame()
        self.adv.setObjectName("Card")
        av = QtWidgets.QVBoxLayout(self.adv)
        av.setContentsMargins(14, 11, 14, 11)
        av.setSpacing(7)
        arow = QtWidgets.QHBoxLayout()
        arow.setSpacing(8)
        self.ip_edit = QtWidgets.QLineEdit()
        self.ip_edit.setPlaceholderText("手机 IP，例如 192.168.5.22")
        arow.addWidget(self.ip_edit, 1)
        self.wifi_btn = QtWidgets.QPushButton("无线连上")
        self.wifi_btn.setObjectName("Mini")
        self.wifi_btn.clicked.connect(self._wifi)
        arow.addWidget(self.wifi_btn)
        av.addLayout(arow)
        self.ip_tip = QtWidgets.QLabel(
            "第一次切无线得插着线点一次（燧镜会替你把手机切到无线模式），之后拔线也能投。"
            "手机 IP 在「设置 → WiFi → 当前网络」里看。"
        )
        self.ip_tip.setObjectName("Small")
        self.ip_tip.setWordWrap(True)
        av.addWidget(self.ip_tip)
        # 手机互联那台手机的 IP 直接填进来，不用再翻手机设置抄一遍
        self._guess_ip()
        self.adv.setVisible(False)
        lay.addWidget(self.adv)

        # ---- 底部按钮 ----
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        self.desc = QtWidgets.QLabel("")
        self.desc.setObjectName("Small")
        row.addWidget(self.desc, 1)
        self.start_btn = QtWidgets.QPushButton("开始投屏")
        self.start_btn.setMinimumWidth(112)
        self.start_btn.clicked.connect(self._start)
        row.addWidget(self.start_btn)
        # 「结束投屏」是真断；「收起面板」只是把小窗收起来，投屏照旧
        self.stop_btn = QtWidgets.QPushButton("结束投屏")
        self.stop_btn.setObjectName("Danger")
        self.stop_btn.setMinimumWidth(84)
        self.stop_btn.setToolTip("把 scrcpy 的投屏窗口关掉，断开连接")
        self.stop_btn.clicked.connect(self._stop_cast)
        row.addWidget(self.stop_btn)
        close_btn = QtWidgets.QPushButton("收起面板")
        close_btn.setObjectName("Mini")
        close_btn.setMinimumWidth(84)
        close_btn.setToolTip("只收起这个小窗；投屏窗口还在，随时可以再点开这块面板")
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        lay.addLayout(row)

        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(8000)

    # ---------------------------------------------------------------- 状态
    def refresh(self) -> None:
        try:
            snap = scrcpy_tool.snapshot()
        except Exception as exc:  # noqa: BLE001
            self.st_title.setText("检测出错了")
            self.st_detail.setText(str(exc)[:120])
            return
        self._last_state = snap["state"]
        self.st_title.setText(snap["title"])
        self.st_detail.setText(snap["detail"])
        self.guide.setVisible(snap["state"] != "ready")
        self.start_btn.setEnabled(snap["state"] != "no-tool")
        running = False
        try:
            running = self.win.cast_running()
        except Exception:  # noqa: BLE001
            running = False
        self.stop_btn.setEnabled(running)
        if running:
            self.desc.setText("投屏在跑：收面板不断投屏，要断就点「结束投屏」")
        elif snap["state"] == "ready":
            self.desc.setText("点一下就开始；投屏窗口自己关掉就断开，不留后台")

    def _guess_ip(self) -> None:
        """从手机互联那边借地址：扫过码/输过配对码的手机，IP 本来就已经记着了。"""
        ip = ""
        try:
            ip = str(getattr(self.win.tools_card.lan, "last_ip", "") or "").strip()
        except Exception:  # noqa: BLE001
            ip = ""
        if not ip:
            return
        try:
            self.ip_edit.setText(ip)
            self.ip_tip.setText(
                f"已经填上手机互联那台的地址 {ip}，直接点「无线连上」就行。"
                "第一次切无线仍要插一次线授权，之后拔线也能投。"
            )
        except Exception:  # noqa: BLE001
            pass

    def _toggle_adv(self, on: bool) -> None:
        self.adv.setVisible(bool(on))
        self.adv_btn.setText("无线连接（收起）" if on else "无线连接（可选）")
        self.adjustSize()

    def _wifi(self) -> None:
        ip = self.ip_edit.text().strip()
        if not ip:
            self.win.toast("先填手机 IP")
            return
        self.wifi_btn.setEnabled(False)
        self.wifi_btn.setText("连接中…")
        QtWidgets.QApplication.processEvents()
        try:
            ok, msg = scrcpy_tool.connect_wifi(ip)
        finally:
            self.wifi_btn.setEnabled(True)
            self.wifi_btn.setText("无线连上")
        self.win.toast(msg)
        self.refresh()

    # ---------------------------------------------------------------- 启动
    def _start(self) -> None:
        snap = scrcpy_tool.snapshot()
        st = snap["state"]
        if st == "no-tool":
            self.win.toast("投屏组件缺失，bundled\\scrcpy 不见了")
            return
        if st == "unauthorized":
            self.win.toast("手机正在等你点「允许 USB 调试」，点完再按一次")
            return
        if st != "ready":
            self.win.toast(snap["detail"])
            return
        serial = snap["serials"][0] if snap["serials"] else ""
        self.start_btn.setEnabled(False)
        self.start_btn.setText("正在拉起…")
        try:
            # 进程挂主窗口，面板关掉也不跟着死；这里只拿个引用
            self.win.start_cast(serial, self.quality_combo.currentData())
        except Exception as exc:  # noqa: BLE001
            self.start_btn.setEnabled(True)
            self.start_btn.setText("开始投屏")
            self.win.toast("拉不起来：" + str(exc)[:60])
            return
        QTimer.singleShot(1200, self._after_launch)

    def _stop_cast(self) -> None:
        """结束投屏：面板留着，连接断掉。跟「收起面板」不是一回事。"""
        try:
            ok = self.win.stop_cast()
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:
            self.win.toast("现在没有在投屏")
        self.refresh()

    def _after_launch(self) -> None:
        self.start_btn.setEnabled(True)
        self.start_btn.setText("再开一个窗口")
        self.refresh()

    def closeEvent(self, ev) -> None:  # noqa: N802
        try:
            self.timer.stop()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(ev)


class ShareDialog(QtWidgets.QDialog):
    """文件互传：两个入口——发下去的「分享」，和手机传上来的「收到」。"""

    def __init__(self, win) -> None:
        super().__init__(win)
        self.win = win
        self.lan = win.tools_card.lan
        self.setWindowTitle("文件互传")
        self.setMinimumWidth(440)
        self.setStyleSheet(
            qss() + "\nQDialog { background: %s; }" % theme.current().colors.get("bg-page", "#0e1015")
        )
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(11)

        t = QtWidgets.QLabel("文件互传")
        t.setObjectName("Section")
        lay.addWidget(t)
        tip = QtWidgets.QLabel(
            "电脑和手机连在同一个 WiFi 下才传得动。手机上打开网页切到「文件」页，"
            "就能看到这边「分享」里的东西；手机选的文件会传到这边的「收到」。"
        )
        tip.setObjectName("Small")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        sh_card, self.sh_desc = self._block(
            "发给手机",
            "",
            "选文件发给手机",
            self._send_files,
            "打开分享文件夹",
            self._open_share,
        )
        lay.addWidget(sh_card)

        rc_card, self.rc_desc = self._block(
            "手机传上来的",
            "",
            "打开收到的文件",
            self._open_recv,
        )
        lay.addWidget(rc_card)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        close_btn = QtWidgets.QPushButton("关闭")
        close_btn.setObjectName("Mini")
        close_btn.setMinimumWidth(76)
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)
        lay.addLayout(row)

        self.refresh()

    def _block(self, title: str, desc: str, btn_text: str, fn,
               btn2_text: str = "", btn2_fn=None):
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        v = QtWidgets.QVBoxLayout(card)
        v.setContentsMargins(14, 11, 14, 11)
        v.setSpacing(7)
        h = QtWidgets.QHBoxLayout()
        h.setSpacing(8)
        lb = QtWidgets.QLabel(title)
        lb.setObjectName("Section")
        h.addWidget(lb)
        h.addStretch(1)
        b = QtWidgets.QPushButton(btn_text)
        b.setObjectName("Mini")
        b.clicked.connect(fn)
        h.addWidget(b)
        if btn2_text:
            b2 = QtWidgets.QPushButton(btn2_text)
            b2.setObjectName("Mini")
            b2.clicked.connect(btn2_fn)
            h.addWidget(b2)
        v.addLayout(h)
        d = QtWidgets.QLabel(desc)
        d.setObjectName("Small")
        d.setWordWrap(True)
        v.addWidget(d)
        return card, d

    def _send_files(self) -> None:
        """从电脑任意位置挑文件，直接复制进「分享」，手机刷新就能下。

        手机那头不认什么类型：安装包、压缩包、视频、工程文件都能下，
        下载完落在手机公共「下载」目录，文件管理器里点开就能用。
        """
        paths, _f = QtWidgets.QFileDialog.getOpenFileNames(
            self, "选要发给手机的文件（任意类型，可多选）", "", "所有文件 (*.*)"
        )
        if not paths:
            return
        folder = self.lan.share_dir
        sent = 0
        skipped = 0
        for p in paths:
            src = Path(p)
            if not src.is_file():
                continue
            target = folder / src.name
            if target.exists():
                try:
                    same = target.stat().st_size == src.stat().st_size
                except OSError:
                    same = False
                if same:
                    skipped += 1
                    continue
                stem, suffix = src.stem, src.suffix
                for i in range(1, 200):
                    cand = folder / f"{stem}({i}){suffix}"
                    if not cand.exists():
                        target = cand
                        break
            try:
                shutil.copy2(str(src), str(target))
                sent += 1
            except OSError as exc:
                self.win.toast("这个没复制成功：" + str(exc)[:48])
        self.refresh()
        if sent:
            self.sh_desc.setText(
                f"刚放进去 {sent} 个文件，手机上点「刷新」就能看到并下载。"
                f"路径:{self.lan.share_dir}"
                + (f"（{skipped} 个本来就在里面）" if skipped else "")
            )
        elif skipped:
            self.sh_desc.setText(f"这些都是已经在「分享」里的文件，手机上刷新一下就能看到。")

    def _open_share(self) -> None:
        self.lan.share_dir
        if not self.lan.open_share_dir():
            self.sh_desc.setText("打不开文件夹，自己去这里：" + str(self.lan.share_dir))

    def _open_recv(self) -> None:
        if not self.lan.open_recv_dir():
            self.rc_desc.setText("打不开文件夹，自己去这里：" + str(self.lan.recv_root))

    def refresh(self) -> None:
        n = len(self.lan.list_share())
        if n:
            self.sh_desc.setText(f"「分享」里现在有 {n} 个文件，手机刷新一下就能看到。"
                                 f"路径：{self.lan.share_dir}")
        else:
            self.sh_desc.setText("「分享」是空的。把视频、压缩包拖进这个文件夹，手机上点下载就行。"
                                 f"路径：{self.lan.share_dir}")
        cnt = 0
        try:
            for p in self.lan.recv_root.rglob("*"):
                if p.is_file():
                    cnt += 1
        except OSError:
            pass
        if cnt:
            self.rc_desc.setText(f"已经收下 {cnt} 个文件，按日期分在下面。路径：{self.lan.recv_root}")
        else:
            self.rc_desc.setText(f"还没有收到过东西。手机传上来的文件会按日期存在这里。"
                                 f"路径：{self.lan.recv_root}")

    def showEvent(self, ev) -> None:
        self.refresh()
        super().showEvent(ev)


class ToolsCard(QtWidgets.QFrame):
    """主界面上的「工具」卡：着色器缓存清理 + 网络测速。

    这两件事都是"平时不用、卡了才用"，所以摆在主界面一行，不藏进设置。
    """

    cache_result = Signal(str)
    speed_result = Signal(str)
    speed_progress = Signal(str)

    def __init__(self, win) -> None:
        super().__init__()
        self.win = win
        self.setObjectName("Card")
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 11, 16, 11)
        lay.setSpacing(7)

        # 局域网剪贴板桥：手机发来的文字，Qt 会自动排回主线程再写剪贴板
        self.lan = clipboard_lan.LanBridge(
            token=getattr(self.win.cfg, "clip_token", ""), parent=self
        )
        if not getattr(self.win.cfg, "clip_token", ""):
            # 第一次开：生成一个口令存进配置，以后重启程序二维码还能接着用
            self.win.cfg.clip_token = self.lan.token
            try:
                self.win.cfg.save()
            except Exception:  # noqa: BLE001
                pass
        if not getattr(self.win.cfg, "lan_id", ""):
            # 这台机器的身份：第一次开生成，之后一直用它
            self.win.cfg.lan_id = uuid.uuid4().hex[:16]
            try:
                self.win.cfg.save()
            except Exception:  # noqa: BLE001
                pass
        self.lan.lan_id = getattr(self.win.cfg, "lan_id", "")
        self.lan.pushed.connect(self._on_lan_push)
        QtWidgets.QApplication.clipboard().dataChanged.connect(self._on_clip_change)
        self._clip_mute_until = 0.0  # 自己写剪贴板后的一小段时间里，别再当成「新复制」捡一遍

        # 手机页面吃什么：电脑状态复用主窗口那个采集器，情报读「情报」页的缓存
        self.lan.sys_provider = self._sys_payload
        self.lan.intel_provider = self._intel_payload
        self.lan.intel_refresh_ask.connect(self._on_intel_refresh_ask)
        # 延迟取：改完设置立刻生效，不用重启服务
        self.lan.recv_dir_provider = lambda: getattr(self.win.cfg, "recv_dir", "")

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("工具")
        title.setObjectName("Section")
        head.addWidget(title)
        head.addStretch(1)
        lay.addLayout(head)

        cache_line = QtWidgets.QHBoxLayout()
        cache_line.setSpacing(8)
        cache_cap = QtWidgets.QLabel("着色器缓存")
        cache_cap.setObjectName("Small")
        cache_cap.setMinimumWidth(64)
        cache_line.addWidget(cache_cap)
        self.cache_info = QtWidgets.QLabel("点「统计」看看能清多少")
        self.cache_info.setObjectName("Small")
        cache_line.addWidget(self.cache_info, 1)
        self.cache_scan_btn = QtWidgets.QPushButton("统计")
        self.cache_scan_btn.setObjectName("Mini")
        self.cache_scan_btn.clicked.connect(self.scan_cache)
        cache_line.addWidget(self.cache_scan_btn)
        self.cache_clean_btn = QtWidgets.QPushButton("一键清理")
        self.cache_clean_btn.setObjectName("Mini")
        self.cache_clean_btn.setToolTip("清掉 NVIDIA / AMD / Intel 与 DirectX 的着色器缓存，赛季更新后卡顿时用")
        self.cache_clean_btn.clicked.connect(self.clean_cache)
        cache_line.addWidget(self.cache_clean_btn)
        lay.addLayout(cache_line)

        speed_line = QtWidgets.QHBoxLayout()
        speed_line.setSpacing(8)
        speed_cap = QtWidgets.QLabel("网络测速")
        speed_cap.setObjectName("Small")
        speed_cap.setMinimumWidth(64)
        speed_line.addWidget(speed_cap)
        self.speed_info = QtWidgets.QLabel("没测过。点一下会连测 12 秒，看延迟抖不抖、有没有丢包")
        self.speed_info.setObjectName("Small")
        self.speed_info.setWordWrap(True)
        speed_line.addWidget(self.speed_info, 1)
        self.speed_btn = QtWidgets.QPushButton("开始测速")
        self.speed_btn.setObjectName("Mini")
        self.speed_btn.clicked.connect(self.run_speedtest)
        speed_line.addWidget(self.speed_btn)
        lay.addLayout(speed_line)

        # 第三行：系统更新（打游戏最怕中途被更新重启）
        wu_line = QtWidgets.QHBoxLayout()
        wu_line.setSpacing(8)
        wu_cap = QtWidgets.QLabel("系统更新")
        wu_cap.setObjectName("Small")
        wu_cap.setMinimumWidth(64)
        wu_line.addWidget(wu_cap)
        self.wu_info = QtWidgets.QLabel("点一下「推迟」把自动更新往后挪，到期自动恢复")
        self.wu_info.setObjectName("Small")
        wu_line.addWidget(self.wu_info, 1)
        self.wu_pause_btn = QtWidgets.QPushButton("推迟 35 天")
        self.wu_pause_btn.setObjectName("Mini")
        self.wu_pause_btn.setToolTip(
            "和系统里「暂停更新」是同一套设置，最多 35 天；到期自动恢复，不是永久关闭"
        )
        self.wu_pause_btn.clicked.connect(self.pause_updates)
        wu_line.addWidget(self.wu_pause_btn)
        self.wu_resume_btn = QtWidgets.QPushButton("恢复更新")
        self.wu_resume_btn.setObjectName("Mini")
        self.wu_resume_btn.setToolTip("取消推迟，让系统恢复按计划更新")
        self.wu_resume_btn.clicked.connect(self.resume_updates)
        wu_line.addWidget(self.wu_resume_btn)
        lay.addLayout(wu_line)

        # 第四行：启动项（开机自启到底谁在偷偷跑）
        su_line = QtWidgets.QHBoxLayout()
        su_line.setSpacing(8)
        su_cap = QtWidgets.QLabel("启动项")
        su_cap.setObjectName("Small")
        su_cap.setMinimumWidth(64)
        su_line.addWidget(su_cap)
        self.su_info = QtWidgets.QLabel("点「管理」看谁在开机自启，能一个个关掉")
        self.su_info.setObjectName("Small")
        su_line.addWidget(self.su_info, 1)
        self.su_btn = QtWidgets.QPushButton("管理")
        self.su_btn.setObjectName("Mini")
        self.su_btn.setToolTip(
            "禁用的是系统的同一套开关（任务管理器里状态一致），不删程序、随时能切回来"
        )
        self.su_btn.clicked.connect(self.open_startup)
        su_line.addWidget(self.su_btn)
        lay.addLayout(su_line)


        self.cache_result.connect(self._on_cache_result)
        self.speed_result.connect(self._on_speed_result)
        self.speed_progress.connect(self._on_speed_progress)

        QTimer.singleShot(0, self.refresh_wu)
        QTimer.singleShot(0, self.refresh_startup)
        QTimer.singleShot(0, self._sync_clip)
        if getattr(self.win.cfg, "clip_auto", False):
            # 上次是开着的：这次启动等界面起来就自己起服务，手机那边不用重扫码
            QTimer.singleShot(1500, self._auto_start_clip)

    # ---------------------------------------------------------- 着色器缓存
    def _on_cache_result(self, text: str) -> None:
        self.cache_info.setText(text)
        self.cache_clean_btn.setEnabled(True)
        self.cache_scan_btn.setEnabled(True)
        self.cache_clean_btn.setText("一键清理")

    def scan_cache(self) -> None:
        self.cache_scan_btn.setEnabled(False)
        self.cache_info.setText("正在统计缓存…")

        def work() -> None:
            try:
                rows = cacheclean.scan()
                total = sum(r["size"] for r in rows)
                if not rows:
                    self.cache_result.emit("没找到着色器缓存目录（可能没装显卡驱动或路径不同）")
                    return
                parts = [f"{r['label']} {cacheclean.fmt_size(r['size'])}" for r in rows]
                self.cache_result.emit(f"共 {cacheclean.fmt_size(total)}｜" + "，".join(parts))
            except Exception as exc:  # noqa: BLE001
                self.cache_result.emit(f"统计失败：{exc}")

        threading.Thread(target=work, daemon=True).start()

    def clean_cache(self) -> None:
        rows = cacheclean.scan()
        total = sum(r["size"] for r in rows)
        if total <= 0:
            self.win.toast("没有可清理的缓存", False)
            return
        ask = QtWidgets.QMessageBox.question(
            self,
            "清理着色器缓存",
            f"要清掉 {cacheclean.fmt_size(total)} 的着色器缓存吗？\n\n"
            "删掉之后第一次进游戏会重新编译着色器，前一两分钟可能略卡，之后更顺。\n"
            "建议先退出游戏再清理。",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if ask != QtWidgets.QMessageBox.Yes:
            return
        self.cache_clean_btn.setEnabled(False)
        self.cache_clean_btn.setText("清理中…")

        def work() -> None:
            try:
                freed, removed, skipped = cacheclean.clean()
                text = f"已清 {cacheclean.fmt_size(freed)}（{removed} 个文件）"
                if skipped:
                    text += f"；{len(skipped)} 个被占用跳过"
                self.cache_result.emit(text)
            except Exception as exc:  # noqa: BLE001
                self.cache_result.emit(f"清理失败：{exc}")

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------- 网络测速
    def _on_speed_result(self, text: str) -> None:
        self.speed_info.setText(text)
        self.speed_btn.setEnabled(True)
        self.speed_btn.setText("开始测速")

    def _on_speed_progress(self, text: str) -> None:
        self.speed_info.setText(text)

    def run_speedtest(self) -> None:
        self.speed_btn.setEnabled(False)
        self.speed_btn.setText("测速中…")
        self.speed_info.setText("正在连续采样延迟（12 秒）…")

        def on_sample(i: int, total: int, ms, stats: dict) -> None:
            part = f"采样 {i}/{total}　"
            if ms is None:
                part += "这一次没通（记一次丢包）"
            else:
                part += f"当前 {ms:.0f} ms"
            if stats.get("avg"):
                part += (
                    f"　｜平均 {stats['avg']:.0f} ms"
                    f"　抖动 {stats['jitter']:.0f} ms"
                    f"　丢包 {(stats['loss'] or 0):.0f}%"
                )
            self.speed_progress.emit(part)

        def work() -> None:
            try:
                stats = netspeed.ping_monitor(seconds=12.0, interval=0.5, on_sample=on_sample)
                if stats.get("avg") is None:
                    self.speed_result.emit(
                        "网络不通：连测速节点都连不上，先看网线 / WiFi / 路由器"
                    )
                    return
                url = netspeed._pick_source()
                mbps = None
                source = None
                if url:
                    source = "Cloudflare" if "cloudflare" in url else "阿里云镜像"
                    for threads, per_thread in ((3, 5_000_000), (1, 8_000_000)):
                        mbps, _total, _sec = netspeed.download_speed(
                            url, threads=threads, per_thread=per_thread
                        )
                        if mbps:
                            break
                head = (
                    f"延迟 平均 {stats['avg']:.0f} ms（最低 {stats['min']:.0f} / 最高 "
                    f"{stats['max']:.0f}）　抖动 {stats['jitter']:.0f} ms　"
                    f"丢包 {(stats['loss'] or 0):.0f}%"
                )
                if mbps:
                    head += f"　｜下载 {mbps:.1f} Mbps（约 {mbps / 8:.1f} MB/s）"
                    if source:
                        head += f"（{source}）"
                else:
                    head += "　｜下载测速没成功（测速源不可达，不影响上面那行判断）"
                # 配了游戏服就额外打一路（6 秒），单独给一段结论
                tail = ""
                host, port = netspeed.split_host(
                    getattr(getattr(self.win, "cfg", None), "ping_host", "")
                )
                if host:
                    self.speed_progress.emit(f"再打一下游戏服 {host}:{port}（6 秒）…")
                    gs = netspeed.ping_monitor(
                        seconds=6.0, interval=0.5, targets=[(host, port)]
                    )
                    if gs.get("avg") is None:
                        tail = (
                            f"\n游戏服 {host}:{port}：连不上"
                            "（游戏服常只开 UDP，TCP 打不通不代表服务器差）"
                        )
                    else:
                        tail = (
                            f"\n游戏服 {host}:{port}：平均 {gs['avg']:.0f} ms"
                            f" · 抖动 {gs['jitter']:.0f} ms · 丢包 {(gs['loss'] or 0):.0f}%"
                        )
                        if stats.get("avg") is not None and gs["avg"] - stats["avg"] >= 40:
                            tail += (
                                f"\n判定：公共 {stats['avg']:.0f} ms、游戏服 {gs['avg']:.0f} ms，"
                                "到服这段绕远了——换加速器节点或换区服，比换宽带有用"
                            )
                self.speed_result.emit(head + "\n判定：" + netspeed.verdict(stats) + tail)
            except Exception as exc:  # noqa: BLE001
                self.speed_result.emit(f"测速失败：{exc}")

        threading.Thread(target=work, daemon=True).start()

    # ---------------------------------------------------------- 系统更新
    def refresh_wu(self) -> None:
        try:
            paused, text = wupdate.status()
        except Exception as exc:  # noqa: BLE001
            self.wu_info.setText("读不到更新状态：" + str(exc))
            return
        self.wu_info.setText(text)
        self.wu_pause_btn.setEnabled(not paused)
        self.wu_resume_btn.setEnabled(paused)

    def pause_updates(self) -> None:
        try:
            ok, msg = wupdate.pause(35)
        except Exception as exc:  # noqa: BLE001
            ok, msg = False, "推迟失败：" + str(exc)
        self.win.toast(msg, ok)
        self.refresh_wu()

    def resume_updates(self) -> None:
        try:
            ok, msg = wupdate.resume()
        except Exception as exc:  # noqa: BLE001
            ok, msg = False, "取消失败：" + str(exc)
        self.win.toast(msg, ok)
        self.refresh_wu()

    # ---------------------------------------------------------- 启动项
    def refresh_startup(self) -> None:
        try:
            on, total = startup.summary()
        except Exception as exc:  # noqa: BLE001
            self.su_info.setText("读不到启动项：" + str(exc))
            return
        if not total:
            self.su_info.setText("没读到启动项")
            return
        self.su_info.setText(f"{total} 个启动项，{on} 个开着")

    def open_startup(self) -> None:
        dlg = StartupDialog(self.win)
        dlg.exec()
        self.refresh_startup()

    # ---------------------------------------------------------- 局域网剪贴板
    def open_share(self) -> None:
        """打开「分享」文件夹，顺手报一下有几个文件。"""
        self.lan.share_dir  # 确保目录在
        if not self.lan.open_share_dir():
            self.win.toast("打不开文件夹，你自己去这个路径：" + str(self.lan.share_dir))
            return
        self.refresh_share()

    def refresh_share(self) -> None:
        tile = getattr(self.win, "tile_files", None)
        if tile is None:
            return
        n = len(self.lan.list_share())
        if n:
            tile.setToolTip(f"「分享」文件夹里有 {n} 个文件等着发给手机")
        else:
            tile.setToolTip("把要传的文件丢进「分享」文件夹，手机上点一下就下载")

    def _sys_payload(self) -> dict:
        """电脑状态。sysmon 是主窗口的采集器，这里延迟取——建卡的时候它可能还没造出来。"""
        mon = getattr(self.win, "sysmon", None)
        if mon is None:
            return {}
        cached = getattr(self.win, "sysmon_last", None)
        if cached:
            return dict(cached)
        try:
            return mon.snapshot()  # 第一次还没 tick 过才走到这儿
        except Exception:  # noqa: BLE001
            return {}

    def _intel_payload(self) -> dict:
        """把「情报」页里的缓存整理成手机看得下的一小坨（不联网，纯读内存）。"""
        page = getattr(self.win, "delta_page", None)
        data = getattr(page, "data", None) or {}
        pw = data.get("passwords") or {}
        ammo = data.get("ammo") or {}
        fake = data.get("price_top") or {}
        profit = data.get("profit") or {}

        def cut(items, n):
            return items[:n] if isinstance(items, list) else []

        return {
            "ok": bool(data),
            "fetched_at": str(data.get("fetched_at") or ""),
            "codes_date": str(pw.get("codes_date") or pw.get("updated") or ""),
            "busy": getattr(page, "_worker", None) is not None,
            "pwd": {"updated": str(pw.get("updated") or ""), "maps": pw.get("maps") or {}},
            "ammo": {"updated": str(ammo.get("updated") or ""), "list": cut(ammo.get("list"), 20)},
            "fake": {"updated": str(fake.get("updated") or ""), "list": cut(fake.get("list"), 20)},
            "profit": {
                "updated": str(profit.get("updated") or ""),
                "groups": [
                    {"station": str(g.get("station") or ""), "list": cut(g.get("list"), 6)}
                    for g in cut(profit.get("groups"), 4)
                ],
            },
        }

    def _on_intel_refresh_ask(self, key: str) -> None:
        """手机点了某一块的刷新，回主线程让「情报」页去抓。"""
        page = getattr(self.win, "delta_page", None)
        if page is not None:
            page.refresh_block(key)

    def _clip_hot(self) -> bool:
        """刚把内容写进剪贴板的话，这一下不算「用户又复制了新东西」。"""
        return time.time() < self._clip_mute_until

    def _on_clip_change(self) -> None:
        """电脑这边复制了新东西，存起来给手机拉。"""
        if not getattr(self.win.cfg, "clip_enabled", True):
            return
        if not self.lan.running:
            return
        if self._clip_hot():
            return
        text = QtWidgets.QApplication.clipboard().text()
        if text:
            self.lan.set_text(text)

    def _on_lan_push(self, text: str) -> None:
        """手机发过来的文字写进 Windows 剪贴板。"""
        if not getattr(self.win.cfg, "clip_enabled", True):
            self.win.toast("剪贴板在设置里关掉了，先打开再发", False)
            return
        self._clip_mute_until = time.time() + 0.9  # 挡掉这次写入引起的 dataChanged
        QtWidgets.QApplication.clipboard().setText(text)
        self.lan.set_text(text)  # 主动记一条，手机端刷出来就知道"我刚发的到了"
        self.win.toast("手机发来一段文字，已写进剪贴板", True)

    def _sync_clip(self) -> None:
        tile = getattr(self.win, "tile_clip", None)
        if tile is None:
            return
        if getattr(self, "_link_on", False):
            who = getattr(self, "_link_who", "") or "手机"
            tile.setToolTip(
                "已连接：" + who + "\n手机上打开 " + self.lan.url() + " 就能互发文字和传文件"
            )
        elif self.lan.running:
            tile.setToolTip("还没连手机 —— 点开，用「燧镜手机版」扫二维码或输配对码")
        else:
            tile.setToolTip("点开：电脑这边出个二维码，手机扫一下就能互发文字、传文件")

    def _seed_clip(self) -> None:
        """起服务时先抓一次当前的剪贴板，让历史里至少有现在这条。"""
        try:
            text = QtWidgets.QApplication.clipboard().text()
        except Exception:  # noqa: BLE001
            return
        if text:
            self.lan.set_text(text)

    def _auto_start_clip(self) -> None:
        if self.lan.running:
            return
        self.lan.clip_provider = lambda: bool(getattr(self.win.cfg, "clip_enabled", True))
        self.lan.start()
        self._seed_clip()
        self._sync_clip()
        self.refresh_share()

    def _remember_clip(self, on: bool) -> None:
        try:
            self.win.cfg.clip_auto = on
            self.win.cfg.save()
        except Exception:  # noqa: BLE001
            pass

    def open_clip(self) -> None:
        dlg = ClipDialog(self)
        dlg.exec()
        self._sync_clip()
        if self.lan.running:
            self._seed_clip()
            self._remember_clip(True)


class ClipDialog(QtWidgets.QDialog):
    """手机连过来：二维码 + 地址 + 怎么用。"""

    def __init__(self, card) -> None:
        super().__init__(card.win)
        self.card = card
        self.lan = card.lan
        self.setWindowTitle("手机连过来")
        self.setFixedWidth(438)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("手机连过来")
        title.setStyleSheet("font-size:14.5px;font-weight:600;")
        head.addWidget(title)
        head.addStretch(1)
        self.help_btn = QtWidgets.QPushButton("?")
        self.help_btn.setObjectName("Mini")
        self.help_btn.setFixedSize(26, 25)
        self.help_btn.setToolTip("连不上、打不开的时候点这里")
        self.help_btn.clicked.connect(self._show_help)
        head.addWidget(self.help_btn)
        lay.addLayout(head)

        step = QtWidgets.QLabel("手机连同一个 WiFi，用相机或浏览器扫下面这个码。")
        step.setObjectName("Small")
        lay.addWidget(step)

        self.qr = QtWidgets.QLabel()
        self.qr.setFixedSize(232, 232)
        self.qr.setAlignment(QtCore.Qt.AlignCenter)
        self.qr.setStyleSheet("background:#ffffff;border-radius:14px;")
        wrap = QtWidgets.QHBoxLayout()
        wrap.addStretch(1)
        wrap.addWidget(self.qr)
        wrap.addStretch(1)
        lay.addLayout(wrap)

        addr_line = QtWidgets.QHBoxLayout()
        addr_line.setSpacing(6)
        self.addr = QtWidgets.QLabel()
        self.addr.setObjectName("Small")
        self.addr.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        addr_line.addWidget(self.addr, 1)
        copy_btn = QtWidgets.QPushButton("复制地址")
        copy_btn.setObjectName("Mini")
        copy_btn.clicked.connect(self._copy_addr)
        addr_line.addWidget(copy_btn)
        lay.addLayout(addr_line)

        # ---------- App 配对码：自动发现到电脑之后输这 6 位就连上 ----------
        pair_line = QtWidgets.QHBoxLayout()
        pair_line.setSpacing(8)
        pl = QtWidgets.QLabel("配对码")
        pl.setObjectName("Small")
        pair_line.addWidget(pl)
        self.pair_val = QtWidgets.QLabel("------")
        self.pair_val.setStyleSheet(
            "font-size:19px;font-weight:700;letter-spacing:3px;color:#4ff0c8;"
        )
        self.pair_val.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        pair_line.addWidget(self.pair_val)
        self.pair_life = QtWidgets.QLabel("")
        self.pair_life.setObjectName("Small")
        pair_line.addWidget(self.pair_life)
        pair_line.addStretch(1)
        b_pnew = QtWidgets.QPushButton("换一个")
        b_pnew.setObjectName("Mini")
        b_pnew.setToolTip("手机输错了、或者过期了，点这里出一串新的")
        b_pnew.clicked.connect(self._new_pair)
        pair_line.addWidget(b_pnew)
        lay.addLayout(pair_line)

        pair_tip = QtWidgets.QLabel(
            "手机装「燧镜手机版」：扫上面的码直接就进；也可以自动发现到这台电脑后，"
            "输这 6 位码连上来。"
        )
        pair_tip.setObjectName("Small")
        pair_tip.setWordWrap(True)
        lay.addWidget(pair_tip)

        self._pair_timer = QtCore.QTimer(self)
        self._pair_timer.timeout.connect(self._sync_pair)
        self._pair_timer.start(1000)

        tip = QtWidgets.QLabel(
            "电脑复制了什么，手机页面两秒内就能看到，点一下「复制到手机」。\n"
            "手机往电脑发，点「读取手机剪贴板并发送」——读剪贴板必须你点一下，"
            "这是 Android 和浏览器的规矩，换谁做都一样。"
        )
        tip.setObjectName("Small")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        # 防火墙默认挡住外来连接，手机打不开基本是它。只在没放行时露出来
        self.fw_box = QtWidgets.QFrame()
        self.fw_box.setObjectName("Card")
        fb = QtWidgets.QHBoxLayout(self.fw_box)
        fb.setContentsMargins(12, 9, 10, 9)
        fb.setSpacing(8)
        fw_lab = QtWidgets.QLabel("手机连不上 / 自动发现找不到电脑，八成是 Windows 防火墙拦的")
        fw_lab.setObjectName("Small")
        fw_lab.setWordWrap(True)
        fb.addWidget(fw_lab, 1)
        self.fw_btn = QtWidgets.QPushButton("放行")
        self.fw_btn.setObjectName("Mini")
        self.fw_btn.setToolTip(
            "只放行同一网段的连接（TCP 8848-8870 + 自动发现用的 UDP 8849），"
            "外面的人还是进不来。点完会弹一次管理员确认，点「是」")
        self.fw_btn.clicked.connect(self._allow_fw)
        fb.addWidget(self.fw_btn)
        lay.addWidget(self.fw_box)

        self.state = QtWidgets.QLabel("")
        self.state.setObjectName("Small")
        lay.addWidget(self.state)

        foot = QtWidgets.QHBoxLayout()
        self.stop_btn = QtWidgets.QPushButton("关闭服务")
        self.stop_btn.setObjectName("Mini")
        self.stop_btn.clicked.connect(self._stop)
        foot.addWidget(self.stop_btn)
        self.getapp_btn = QtWidgets.QPushButton("获取 App")
        self.getapp_btn.setObjectName("Mini")
        self.getapp_btn.setToolTip("打开手机版安装包所在文件夹，把 apk 传手机装上")
        self.getapp_btn.clicked.connect(self._open_app_dir)
        foot.addWidget(self.getapp_btn)
        foot.addStretch(1)
        close_btn = QtWidgets.QPushButton("关掉窗口")
        close_btn.setObjectName("Mini")
        close_btn.clicked.connect(self.accept)
        foot.addWidget(close_btn)
        lay.addLayout(foot)

        self._start()
        if clipboard_lan.firewall_ok():
            self.fw_box.setVisible(False)

    def _start(self) -> None:
        self.lan.clip_provider = lambda: bool(getattr(self.card.win.cfg, "clip_enabled", True))
        ok, msg = self.lan.start()
        url = self.lan.url()
        if not ok or not url:
            self.state.setText(msg)
            self.qr.setText("服务没起来")
            self.addr.setText(msg)
            return
        pm = clipboard_lan.qr_pixmap(url, 7)
        if pm is None:
            self.qr.setText("二维码库没装")
        else:
            self.qr.setPixmap(pm)
        self.addr.setText(url)
        self.state.setText(msg)
        self.card._sync_clip()
        self._sync_pair()

    def _open_app_dir(self) -> None:
        """「获取 App」：打开手机版 apk 所在的文件夹，并选中那个文件。"""
        base = app_dir()
        cands = sorted(Path(base).glob("燧镜手机版_*.apk"))
        if not cands:
            cands = sorted(Path(base).glob("*.apk"))
        if cands:
            apk = cands[-1]
            try:
                subprocess.Popen(["explorer", "/select,", str(apk)])
                return
            except Exception:  # noqa: BLE001
                logging.debug("explorer /select 失败，退回只开文件夹", exc_info=True)
            try:
                os.startfile(str(apk.parent))
                return
            except Exception:  # noqa: BLE001
                logging.debug("打开 apk 目录失败", exc_info=True)
        QtWidgets.QMessageBox.information(
            self,
            "没找到手机版安装包",
            "程序目录里没有「燧镜手机版_v1.x.x.apk」。\n\n"
            "安装版里它就在程序目录（和 燧镜.exe 同一层）；\n"
            "源码运行的话，去项目根目录找。",
        )

    def _sync_pair(self) -> None:
        if not self.lan.running:
            self.pair_val.setText("------")
            self.pair_life.setText("服务没开")
            return
        self.pair_val.setText(self.lan.pair_code())
        left = self.lan.pair_left()
        self.pair_life.setText("%d 分 %02d 秒后自动换" % (left // 60, left % 60))

    def _new_pair(self) -> None:
        if not self.lan.running:
            return
        self.lan.pair_code(refresh=True)
        self._sync_pair()
        self.state.setText("配对码已换新，手机上得用新的那串")

    def _show_help(self) -> None:
        ClipHelpDialog(self).exec()

    def _allow_fw(self) -> None:
        ok, msg = clipboard_lan.allow_firewall()
        self.state.setText(msg)
        if ok:
            self.fw_btn.setEnabled(False)

    def _copy_addr(self) -> None:
        QtWidgets.QApplication.clipboard().setText(self.lan.url())
        self.state.setText("地址已复制，粘到手机浏览器里也能打开")

    def _stop(self) -> None:
        self.lan.stop()
        self.card._remember_clip(False)  # 是你主动关的，下次别再自己起来
        self.state.setText("服务已关闭，手机页面就打不开了")
        self.card._sync_clip()


class ClipHelpDialog(QtWidgets.QDialog):
    """「连不上怎么办」—— 省得用户回头翻聊天记录。"""

    ITEMS = [
        ("两边是不是同一个 WiFi", "手机别走流量，电脑也别插着另一个路由器。"),
        ("路由器有没有开访客网络 / AP 隔离",
         "开了「客户端之间不许互访」，手机就永远连不上电脑。"
         "去路由器后台把这个开关关掉，或者把手机和电脑连到同一个主 WiFi。"),
        ("电脑 IP 变了", "路由器重启或断电久了会重新分配地址。重扫一次二维码就行，口令不变。"),
        ("权限被拒过", "回到电脑上点「连手机」，看弹窗里那句状态是不是「已开启」。"
         "如果显示没起来，点一下「放行」再同意一次管理员确认。"),
        ("手机页面看着不动", "页面每 2 秒拉一次，切到后台会被系统冻结，回到前台自己就活了。"),
        ("手机上发到电脑为什么要点一下",
         "Android 10 起只有输入法和当前前台应用能读剪贴板，浏览器同理。"
         "这不是偷懒，是系统不让，换任何软件都一样。"),
        ("发过去的内容会丢吗",
         "电脑这边最近 10 条都留着，手机上也能翻；同一条重复复制不会占两个位置。"),
    ]

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("连不上怎么办")
        self.setFixedWidth(452)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(9)

        title = QtWidgets.QLabel("连不上 / 打不开，按这个顺序查")
        title.setStyleSheet("font-size:14px;font-weight:600;")
        lay.addWidget(title)

        for name, body in self.ITEMS:
            row = QtWidgets.QFrame()
            row.setObjectName("Card")
            rl = QtWidgets.QVBoxLayout(row)
            rl.setContentsMargins(13, 10, 13, 10)
            rl.setSpacing(3)
            n = QtWidgets.QLabel(name)
            n.setStyleSheet("font-size:12.5px;font-weight:600;")
            b = QtWidgets.QLabel(body)
            b.setObjectName("Small")
            b.setWordWrap(True)
            rl.addWidget(n)
            rl.addWidget(b)
            lay.addWidget(row)

        foot = QtWidgets.QHBoxLayout()
        foot.addStretch(1)
        ok = QtWidgets.QPushButton("知道了")
        ok.setObjectName("Mini")
        ok.clicked.connect(self.accept)
        foot.addWidget(ok)
        lay.addLayout(foot)


class StartupRow(QtWidgets.QFrame):
    """启动项弹窗里的一行：名字 + 命令 + 开关。"""

    def __init__(self, item: dict, dlg) -> None:
        super().__init__()
        self.item = item
        self.dlg = dlg
        self.setObjectName("Card")
        h = QtWidgets.QHBoxLayout(self)
        h.setContentsMargins(14, 9, 12, 9)
        h.setSpacing(10)

        left = QtWidgets.QVBoxLayout()
        left.setSpacing(2)
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(6)
        name = QtWidgets.QLabel(item["name"])
        name.setStyleSheet("font-size:12.5px;font-weight:600;")
        top.addWidget(name)
        top.addStretch(1)
        tag = QtWidgets.QLabel("系统" if item.get("machine") else "用户")
        tag.setObjectName("Small")
        tag.setFixedWidth(32)
        tag.setAlignment(QtCore.Qt.AlignCenter)
        tag.setStyleSheet(
            "font-size:10.5px;color:#9aa3b2;border:1px solid rgba(255,255,255,0.14);"
            "border-radius:5px;padding:1px 0px;"
        )
        top.addWidget(tag)
        left.addLayout(top)

        cmd = QtWidgets.QLabel(item["cmd"])
        cmd.setObjectName("Small")
        cmd.setStyleSheet("font-size:12px;color:#a8b0bd;")
        text = item["cmd"]
        if len(text) > 78:
            text = text[:76] + "…"
        cmd.setText(text)
        cmd.setToolTip(item["cmd"])
        left.addWidget(cmd)
        h.addLayout(left, 1)

        self.btn = QtWidgets.QPushButton()
        self.btn.setObjectName("Mini")
        self.btn.setCheckable(True)
        self.btn.setFixedWidth(64)
        self.btn.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn.clicked.connect(self._toggle)
        h.addWidget(self.btn)
        self._sync()

    def _sync(self) -> None:
        on = bool(self.item.get("enabled"))
        self.btn.blockSignals(True)
        self.btn.setChecked(on)
        self.btn.setText("已开" if on else "关了")
        self.btn.blockSignals(False)
        if on:
            self.btn.setStyleSheet(
                "QPushButton{border:1px solid #20ffe0;color:#20ffe0;font-weight:600;}"
            )
        else:
            self.btn.setStyleSheet("QPushButton{color:#8d95a3;}")

    def _toggle(self) -> None:
        want = not bool(self.item.get("enabled"))
        ok, msg = startup.set_enabled(self.item, want)
        if ok:
            self.item["enabled"] = want
        self._sync()
        self.dlg.note(msg, ok)
        if ok:
            self.dlg.refresh_head()


class StartupDialog(QtWidgets.QDialog):
    """启动项一览：谁在开机自启，一个个关。"""

    def __init__(self, win) -> None:
        super().__init__(win)
        self.win = win
        self.rows: list[StartupRow] = []
        self.setWindowTitle("启动项")
        self.resize(680, 590)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 12)
        lay.setSpacing(9)

        head = QtWidgets.QHBoxLayout()
        self.head_lab = QtWidgets.QLabel("正在读…")
        self.head_lab.setStyleSheet("font-size:13px;font-weight:600;")
        head.addWidget(self.head_lab)
        head.addStretch(1)
        ref = QtWidgets.QPushButton("刷新")
        ref.setObjectName("Mini")
        ref.clicked.connect(self.reload)
        head.addWidget(ref)
        lay.addLayout(head)

        tip = QtWidgets.QLabel(
            "关掉的是系统的同一个开关：任务管理器「启动」页里状态一样，程序本身不删、随时能切回来。"
            "系统级的项改不了是权限问题，那种用任务管理器最稳。"
        )
        tip.setObjectName("Small")
        tip.setWordWrap(True)
        tip.setStyleSheet("font-size:12px;color:#a8b0bd;")
        lay.addWidget(tip)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        # 全局滚动条 handle 用的是分隔线色，在弹窗里几乎看不见，这里单独提亮
        self.scroll.setStyleSheet(
            "QScrollBar:vertical{background:transparent;width:9px;margin:2px;}"
            "QScrollBar::handle:vertical{background:rgba(255,255,255,0.30);"
            "border-radius:4px;min-height:34px;}"
            "QScrollBar::handle:vertical:hover{background:rgba(32,255,224,0.55);}"
            "QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}"
            "QScrollBar::add-page:vertical,QScrollBar::sub-page:vertical{background:transparent;}"
        )
        self.box = QtWidgets.QWidget()
        self.box.setObjectName("Page")
        self.box_lay = QtWidgets.QVBoxLayout(self.box)
        self.box_lay.setContentsMargins(0, 0, 0, 0)
        self.box_lay.setSpacing(7)
        self.box_lay.addStretch(1)
        self.scroll.setWidget(self.box)
        lay.addWidget(self.scroll, 1)

        self.note_lab = QtWidgets.QLabel("")
        self.note_lab.setObjectName("Small")
        self.note_lab.setStyleSheet("font-size:12px;color:#a8b0bd;")
        lay.addWidget(self.note_lab)

        foot = QtWidgets.QHBoxLayout()
        foot.addStretch(1)
        close = QtWidgets.QPushButton("关闭")
        close.setObjectName("Mini")
        close.clicked.connect(self.accept)
        foot.addWidget(close)
        lay.addLayout(foot)

        self.reload()

    def note(self, text: str, ok: bool) -> None:
        self.note_lab.setText(text)
        self.note_lab.setStyleSheet(
            "font-size:12px;color:%s;" % ("#20ffe0" if ok else "#ff8a8a")
        )

    def refresh_head(self) -> None:
        on = sum(1 for r in self.rows if r.item.get("enabled"))
        self.head_lab.setText(f"{len(self.rows)} 个启动项，{on} 个开着")

    def reload(self) -> None:
        for r in self.rows:
            r.setParent(None)
            r.deleteLater()
        self.rows = []
        try:
            items = startup.list_entries()
        except Exception as exc:  # noqa: BLE001
            self.note("读不到启动项：" + str(exc), False)
            return
        for item in items:
            row = StartupRow(item, self)
            self.box_lay.insertWidget(self.box_lay.count() - 1, row)
            self.rows.append(row)
        self.refresh_head()
        if not items:
            self.note("这台机器上没读到启动项（不太常见，可能是权限受限）", False)


class ActionRow(QtWidgets.QWidget):
    """动作链里的一行：类型 + 参数 + 顺序按钮。"""

    HINTS = {
        ACTION_RESOLUTION: "只列真实支持的模式",
        ACTION_RESTORE: "回到原生",
        ACTION_MOD_START: "选一个已添加的工具",
        ACTION_MOD_STOP: "会连子进程一起关掉",
        ACTION_WAIT: "给游戏留加载时间",
        ACTION_ACE_LIMIT: "要管理员权限，没提权会跳过",
        ACTION_ACE_RESTORE: "把优先级还回去",
        ACTION_FPS_SHOW: "游戏里看帧数",
        ACTION_FPS_HIDE: "看完收起来",
        ACTION_HUD_SHOW: "每日密码贴屏幕边",
        ACTION_HUD_HIDE: "打副本时怕挡视线就关",
        ACTION_REPLAY_START: "后台留最近 12 分钟",
        ACTION_REPLAY_STOP: "省点内存和磁盘",
        ACTION_REPLAY_SAVE: "把精彩那一段单独存下来",
        ACTION_RECORD_START: "连系统声音一起录",
        ACTION_RECORD_STOP: "收工自动保存",
        ACTION_SHOT: "全屏或框选",
        ACTION_CACHE_CLEAN: "赛季更新后卡顿能救一下",
    }

    def __init__(self, action: Action, cfg: Config, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.action = action

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.type_combo = QtWidgets.QComboBox()
        for key, label in ACTION_LABEL.items():
            self.type_combo.addItem(label, key)
        idx = self.type_combo.findData(action.type)
        self.type_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.type_combo.currentIndexChanged.connect(self._on_type)
        lay.addWidget(self.type_combo, 0)

        self.value_combo = QtWidgets.QComboBox()
        lay.addWidget(self.value_combo, 1)

        self.value_spin = QtWidgets.QSpinBox()
        self.value_spin.setRange(0, 300)
        self.value_spin.setSuffix(" 秒")
        lay.addWidget(self.value_spin, 1)

        self.hint = QtWidgets.QLabel()
        self.hint.setStyleSheet("color:#5f6878; font-size:10px;")
        lay.addWidget(self.hint)

        self.btn_up = QtWidgets.QToolButton()
        self.btn_up.setText("↑")
        self.btn_up.setObjectName("Mini")
        lay.addWidget(self.btn_up)

        self.btn_down = QtWidgets.QToolButton()
        self.btn_down.setText("↓")
        self.btn_down.setObjectName("Mini")
        lay.addWidget(self.btn_down)

        self.btn_del = QtWidgets.QToolButton()
        self.btn_del.setText("✕")
        self.btn_del.setObjectName("Danger")
        lay.addWidget(self.btn_del)

        self._fill_value()

    def _on_type(self, _i: int) -> None:
        self._fill_value()

    def _fill_value(self) -> None:
        t = self.type_combo.currentData()
        self.value_combo.blockSignals(True)
        self.value_combo.clear()
        self.hint.setText(self.HINTS.get(t, ""))

        if t == ACTION_RESOLUTION:
            self.value_combo.setVisible(True)
            self.value_spin.setVisible(False)
            for group, items in display.grouped_modes():
                self.value_combo.addItem(f"── {group} ──", None)
                model = self.value_combo.model()
                item = model.item(self.value_combo.count() - 1)
                if item is not None:
                    item.setEnabled(False)
                for m in items:
                    tag = display.tag_for(m.width, m.height)
                    label = m.label + (f"   ★ {tag}" if tag else "")
                    self.value_combo.addItem(label, f"{m.width}x{m.height}")
            cur = self.action.value
            idx = self.value_combo.findData(cur)
            if idx < 0 and cur:
                res = automation.parse_resolution(cur)
                label = f"{res[0]} × {res[1]}   · 自定义" if res else cur
                self.value_combo.insertItem(0, label, cur)
                idx = 0
            if idx >= 0:
                self.value_combo.setCurrentIndex(idx)

        elif t in (ACTION_MOD_START, ACTION_MOD_STOP):
            self.value_combo.setVisible(True)
            self.value_spin.setVisible(False)
            for mod in self.cfg.mods:
                self.value_combo.addItem(mod.name, mod.id)
            idx = self.value_combo.findData(self.action.value)
            if idx >= 0:
                self.value_combo.setCurrentIndex(idx)

        elif t == ACTION_WAIT:
            self.value_combo.setVisible(False)
            self.value_spin.setVisible(True)
            try:
                self.value_spin.setValue(int(float(self.action.value or 0)))
            except ValueError:
                self.value_spin.setValue(0)

        elif t == ACTION_SHOT:
            self.value_combo.setVisible(True)
            self.value_spin.setVisible(False)
            self.value_combo.addItem("全屏截图", "full")
            self.value_combo.addItem("框选截图（会切到截屏状态）", "region")
            idx = self.value_combo.findData(self.action.value or "full")
            self.value_combo.setCurrentIndex(idx if idx >= 0 else 0)

        else:  # restore 及其它无参动作
            self.value_combo.setVisible(False)
            self.value_spin.setVisible(False)

        self.value_combo.blockSignals(False)

    def to_action(self) -> Action:
        t = self.type_combo.currentData()
        if t == ACTION_WAIT:
            value = str(self.value_spin.value())
        elif t == ACTION_RESTORE:
            value = ""
        else:
            value = str(self.value_combo.currentData() or "")
        return Action(type=t, value=value)


class RuleDialog(QtWidgets.QDialog):
    """新建 / 编辑一条自动化规则。"""

    TRIGGER_HINT = {
        TRIGGER_START: "进程一启动，就执行下面的动作 —— 一般用来切到游戏档、顺手拉起工具。",
        TRIGGER_STOP: "进程关掉以后，执行下面的动作 —— 一般用来还原分辨率。",
        TRIGGER_MANUAL: "不会自动跑，只能从主界面或托盘菜单手动点这条规则。",
    }

    def __init__(
        self,
        rule: Optional[Rule],
        cfg: Config,
        win: "MainWindow",
        preset: Optional[dict] = None,
    ):
        super().__init__(win)
        self.cfg = cfg
        self.win = win
        self.rows: List[ActionRow] = []
        self.result_rule: Optional[Rule] = None
        preset = preset or {}

        self.setWindowTitle("自动化规则")
        self.setMinimumSize(640, 520)
        self.setStyleSheet(qss())

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        # 名称
        row1 = QtWidgets.QHBoxLayout()
        row1.addWidget(QtWidgets.QLabel("名称"))
        self.name_edit = QtWidgets.QLineEdit()
        self.name_edit.setPlaceholderText("例如：打三角洲")
        self.name_edit.setText(rule.name if rule else preset.get("name", ""))
        row1.addWidget(self.name_edit, 1)
        lay.addLayout(row1)

        # 触发
        row2 = QtWidgets.QHBoxLayout()
        row2.addWidget(QtWidgets.QLabel("触发"))
        self.trigger_combo = QtWidgets.QComboBox()
        for key, label in TRIGGER_LABEL.items():
            self.trigger_combo.addItem(label, key)
        trigger = rule.trigger if rule else preset.get("trigger", TRIGGER_START)
        idx = self.trigger_combo.findData(trigger)
        if idx >= 0:
            self.trigger_combo.setCurrentIndex(idx)
        self.trigger_combo.currentIndexChanged.connect(self._on_trigger)
        row2.addWidget(self.trigger_combo, 0)

        self.process_edit = QtWidgets.QComboBox()
        self.process_edit.setEditable(True)
        self.process_edit.addItem("")
        for name in sorted(automation.snapshot()):
            if name.endswith(".exe"):
                self.process_edit.addItem(name)
        process = rule.process if rule else preset.get("process", "")
        if process:
            self.process_edit.setCurrentText(process)
        self.process_edit.setMinimumWidth(240)
        self.process_edit.setToolTip("游戏/程序的进程名，写全，比如 DeltaForceClient.exe")
        row2.addWidget(self.process_edit, 1)

        pick = QtWidgets.QPushButton("刷新进程")
        pick.setObjectName("Ghost")
        pick.setToolTip("不知道进程名？先把游戏打开，再点这里，下拉框里就能挑到它")
        pick.clicked.connect(self._reload_processes)
        row2.addWidget(pick)
        lay.addLayout(row2)

        self.tip = QtWidgets.QLabel()
        self.tip.setObjectName("Small")
        self.tip.setWordWrap(True)
        lay.addWidget(self.tip)

        # 动作
        head = QtWidgets.QHBoxLayout()
        title = QtWidgets.QLabel("动作（从上到下依次执行）")
        title.setObjectName("Section")
        head.addWidget(title)
        head.addStretch(1)
        add_act = QtWidgets.QPushButton("+ 添加动作")
        add_act.setObjectName("Ghost")
        add_act.clicked.connect(lambda: self.add_row(None))
        head.addWidget(add_act)
        lay.addLayout(head)

        scroll = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        host = QtWidgets.QWidget()
        self.act_layout = QtWidgets.QVBoxLayout(host)
        self.act_layout.setContentsMargins(0, 0, 4, 0)
        self.act_layout.setSpacing(6)
        self.act_layout.addStretch(1)
        scroll.setWidget(host)
        lay.addWidget(scroll, 1)

        actions = None
        if rule and rule.actions:
            actions = rule.actions
        elif preset.get("actions"):
            actions = preset["actions"]
        if actions:
            for a in actions:
                self.add_row(a)
        else:
            self.add_row(Action(type=ACTION_RESOLUTION, value=self._default_res()))

        # 按钮
        btns = QtWidgets.QHBoxLayout()
        test = QtWidgets.QPushButton("试运行")
        test.setObjectName("Ghost")
        test.setToolTip("只把每一步会干什么打出来，不改分辨率、不启停工具")
        test.clicked.connect(self._test)
        btns.addWidget(test)

        run_now = QtWidgets.QPushButton("立即执行")
        run_now.setObjectName("Ghost")
        run_now.setToolTip("真的跑一次（会切分辨率、启停工具），保存前想验证就用这个")
        run_now.clicked.connect(self._run_now)
        btns.addWidget(run_now)
        btns.addStretch(1)
        cancel = QtWidgets.QPushButton("取消")
        cancel.setObjectName("Ghost")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        ok = QtWidgets.QPushButton("保存")
        ok.setObjectName("Primary")
        ok.clicked.connect(self._save)
        btns.addWidget(ok)
        lay.addLayout(btns)

        self._on_trigger()

    # ------------------------------------------------------------------
    def _default_res(self) -> str:
        w, h = self.cfg.target
        return f"{w}x{h}"

    def _reload_processes(self) -> None:
        cur = self.process_edit.currentText()
        self.process_edit.clear()
        self.process_edit.addItem("")
        for name in sorted(automation.snapshot()):
            if name.endswith(".exe"):
                self.process_edit.addItem(name)
        self.process_edit.setCurrentText(cur)

    def _on_trigger(self, _i: int = 0) -> None:
        trigger = self.trigger_combo.currentData()
        manual = trigger == TRIGGER_MANUAL
        self.process_edit.setEnabled(not manual)
        hint = self.TRIGGER_HINT.get(trigger, "")
        if manual:
            self.tip.setText(hint)
        else:
            self.tip.setText(
                hint
                + "\n进程名要写全（如 DeltaForceClient.exe），只写一半不会匹配；"
                "不确定就先把游戏打开，再点右边「刷新进程」从下拉里挑。"
            )

    def add_row(self, action: Optional[Action]) -> None:
        row = ActionRow(action or Action(type=ACTION_RESOLUTION, value=self._default_res()), self.cfg, self)
        self.rows.append(row)
        self.act_layout.insertWidget(self.act_layout.count() - 1, row)
        row.btn_del.clicked.connect(lambda _=False, r=row: self._remove_row(r))
        row.btn_up.clicked.connect(lambda _=False, r=row: self._move_row(r, -1))
        row.btn_down.clicked.connect(lambda _=False, r=row: self._move_row(r, 1))

    def _remove_row(self, row: ActionRow) -> None:
        if len(self.rows) <= 1:
            self.win.toast("至少留一个动作", False)
            return
        self.rows.remove(row)
        row.setParent(None)
        row.deleteLater()

    def _move_row(self, row: ActionRow, delta: int) -> None:
        idx = self.rows.index(row)
        new = idx + delta
        if new < 0 or new >= len(self.rows):
            return
        self.rows.insert(new, self.rows.pop(idx))
        self.act_layout.removeWidget(row)
        self.act_layout.insertWidget(new, row)

    def _test(self) -> None:
        actions = [r.to_action() for r in self.rows]
        if not actions:
            self.win.toast("还没有动作可试", False)
            return
        self.win.run_actions(actions, "试运行", dry=True)

    def _run_now(self) -> None:
        actions = [r.to_action() for r in self.rows]
        if not actions:
            self.win.toast("还没有动作可执行", False)
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            "立即执行",
            "这会把动作真的跑一遍（可能切分辨率、启停工具），确定吗？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return
        self.win.run_actions(actions, "立即执行")

    def _save(self) -> None:
        name = self.name_edit.text().strip()
        if not name:
            QtWidgets.QMessageBox.information(self, "还差一步", "给这条规则起个名字。")
            return
        trigger = self.trigger_combo.currentData()
        process = self.process_edit.currentText().strip()
        if trigger != TRIGGER_MANUAL and not process:
            QtWidgets.QMessageBox.information(
                self, "还差一步", "自动触发需要一个进程名，比如 DeltaForceClient.exe。"
            )
            return
        actions = [r.to_action() for r in self.rows]
        if not actions:
            QtWidgets.QMessageBox.information(self, "还差一步", "至少加一个动作。")
            return

        self.result_rule = Rule(
            id=getattr(self, "rid", "") or uuid.uuid4().hex[:8],
            name=name,
            trigger=trigger,
            process=process,
            enabled=getattr(self, "enabled", True),
            actions=actions,
        )
        self.accept()


class AutomationDialog(QtWidgets.QDialog):
    """规则列表 + 执行日志。"""

    def __init__(self, win: "MainWindow"):
        super().__init__(win)
        self.win = win
        self.cfg = win.cfg

        self.setWindowTitle("自动化")
        self.setMinimumSize(700, 560)
        self.setStyleSheet(qss())

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 14)
        lay.setSpacing(10)

        # 新手引导（可收起）
        guide = QtWidgets.QFrame()
        guide.setObjectName("Guide")
        guide.setStyleSheet(
            "QFrame#Guide { background:#101720; border:1px solid #1f3a3a; border-radius:10px; }"
        )
        gl = QtWidgets.QVBoxLayout(guide)
        gl.setContentsMargins(14, 10, 14, 10)
        gl.setSpacing(6)

        ghead = QtWidgets.QHBoxLayout()
        gtitle = QtWidgets.QLabel("自动化怎么用？")
        gtitle.setStyleSheet("color:#20ffe0; font-size:12px; font-weight:600;")
        ghead.addWidget(gtitle)
        ghead.addStretch(1)
        self.guide_btn = QtWidgets.QPushButton("收起")
        self.guide_btn.setObjectName("Ghost")
        self.guide_btn.setFixedHeight(24)
        self.guide_btn.clicked.connect(self._toggle_guide)
        ghead.addWidget(self.guide_btn)
        gl.addLayout(ghead)

        self.guide_body = QtWidgets.QWidget()
        gb = QtWidgets.QVBoxLayout(self.guide_body)
        gb.setContentsMargins(0, 0, 0, 0)
        gb.setSpacing(6)

        steps = QtWidgets.QLabel(
            "1. 点「+ 新建规则」，起个名字（比如 打三角洲）\n"
            "2. 选触发：游戏启动时 / 游戏退出后 / 只手动点\n"
            "3. 加动作：切分辨率 / 恢复原生 / 启停工具 / 反作弊优化 / 帧率灯 / 回放 / 录屏 /\n"
            "   截图 / 清缓存 / 等待 —— 面板上能点的开关，基本都能塞进动作链\n"
            "4. 点「试运行」看一遍效果，没问题再「保存」\n"
            "5. 去掉左边的勾 = 这条规则先暂停，不会删除"
        )
        steps.setObjectName("Small")
        steps.setWordWrap(True)
        gb.addWidget(steps)

        gnote = QtWidgets.QLabel("最常用的是两条一对：开游戏切档+拉工具，关游戏自动还原。不知道从哪下手，点下面：")
        gnote.setObjectName("Small")
        gnote.setWordWrap(True)
        gb.addWidget(gnote)

        ex = QtWidgets.QHBoxLayout()
        ex.setSpacing(8)
        b_ex1 = QtWidgets.QPushButton("示例：开游戏切档 + 启动工具")
        b_ex1.setObjectName("Ghost")
        b_ex1.setFixedHeight(28)
        b_ex1.clicked.connect(lambda: self._preset("start"))
        ex.addWidget(b_ex1)
        b_ex2 = QtWidgets.QPushButton("示例：关游戏自动还原")
        b_ex2.setObjectName("Ghost")
        b_ex2.setFixedHeight(28)
        b_ex2.clicked.connect(lambda: self._preset("stop"))
        ex.addWidget(b_ex2)
        ex.addStretch(1)
        gb.addLayout(ex)

        gl.addWidget(self.guide_body)
        lay.addWidget(guide)

        # ---- 一键模板（第 4 批）--------------------------------------
        tpl = QtWidgets.QFrame()
        tpl.setObjectName("Tpl")
        tpl.setStyleSheet(
            "QFrame#Tpl { background:#151119; border:1px solid #3b2b48; border-radius:10px; }"
        )
        tl = QtWidgets.QVBoxLayout(tpl)
        tl.setContentsMargins(14, 10, 14, 10)
        tl.setSpacing(7)

        t_head = QtWidgets.QHBoxLayout()
        t_title = QtWidgets.QLabel("一键模板")
        t_title.setStyleSheet("color:#c9a4ff; font-size:12px; font-weight:600;")
        t_head.addWidget(t_title)
        t_head.addStretch(1)
        tl.addLayout(t_head)

        t_desc = QtWidgets.QLabel(
            "两条配成一对，点一下就写好。"
            "A：切档 → 等 5 秒 → 反作弊优化 → 开帧率灯 → 开回放缓冲；"
            "B：存最后一段回放 → 关回放 → 关帧率灯 → 还原分辨率。"
        )
        t_desc.setObjectName("Small")
        t_desc.setWordWrap(True)
        tl.addWidget(t_desc)

        t_row = QtWidgets.QHBoxLayout()
        t_row.setSpacing(8)
        b_t1 = QtWidgets.QPushButton("A · 开战")
        b_t1.setObjectName("Primary")
        b_t1.setMinimumHeight(38)
        b_t1.setMinimumWidth(132)
        b_t1.clicked.connect(lambda: self._add_tpl("start"))
        t_row.addWidget(b_t1)
        b_t2 = QtWidgets.QPushButton("B · 收尾")
        b_t2.setObjectName("Ghost")
        b_t2.setFixedHeight(30)
        b_t2.setMinimumWidth(104)
        b_t2.clicked.connect(lambda: self._add_tpl("stop"))
        t_row.addWidget(b_t2)
        b_t3 = QtWidgets.QPushButton("两条一起加")
        b_t3.setObjectName("Ghost")
        b_t3.setFixedHeight(30)
        b_t3.setMinimumWidth(120)
        b_t3.clicked.connect(lambda: self._add_tpl("both"))
        t_row.addWidget(b_t3)
        t_row.addStretch(1)
        tl.addLayout(t_row)

        t_tip = QtWidgets.QLabel(
            "进程名默认按三角洲国际服写的，WeGame 版对不上就在规则里改成你任务管理器里看到的那个。"
        )
        t_tip.setObjectName("Small")
        t_tip.setWordWrap(True)
        tl.addWidget(t_tip)

        lay.addWidget(tpl)

        self.listw = QtWidgets.QListWidget()
        self.listw.setAlternatingRowColors(False)
        self.listw.setSpacing(2)
        self.listw.setStyleSheet(
            "QListWidget { background:#0f131a; border:1px solid #1f2632; border-radius:10px;"
            " padding:6px; }\n"
            "QListWidget::item { padding:6px 4px; border-radius:6px; }\n"
            "QListWidget::item:selected { background:#16323a; color:#dff; }"
        )
        self.listw.itemDoubleClicked.connect(lambda _i: self._edit())
        self.listw.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.listw, 1)

        row = QtWidgets.QHBoxLayout()
        b_new = QtWidgets.QPushButton("+ 新建规则")
        b_new.setObjectName("Primary")
        b_new.clicked.connect(self._new)
        row.addWidget(b_new)
        b_edit = QtWidgets.QPushButton("编辑")
        b_edit.setObjectName("Ghost")
        b_edit.clicked.connect(self._edit)
        row.addWidget(b_edit)
        b_del = QtWidgets.QPushButton("删除")
        b_del.setObjectName("Danger")
        b_del.clicked.connect(self._del)
        row.addWidget(b_del)
        b_test = QtWidgets.QPushButton("试运行")
        b_test.setObjectName("Ghost")
        b_test.setToolTip("只打日志，不动分辨率、不启停工具")
        b_test.clicked.connect(self._test)
        row.addWidget(b_test)

        b_run = QtWidgets.QPushButton("立即执行")
        b_run.setObjectName("Ghost")
        b_run.setToolTip("真的跑一遍")
        b_run.clicked.connect(self._run_now)
        row.addWidget(b_run)
        row.addStretch(1)
        b_close = QtWidgets.QPushButton("关闭")
        b_close.setObjectName("Ghost")
        b_close.clicked.connect(self.accept)
        row.addWidget(b_close)
        lay.addLayout(row)

        log_title = QtWidgets.QLabel("执行日志")
        log_title.setObjectName("Section")
        lay.addWidget(log_title)
        self.log_view = QtWidgets.QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumHeight(160)
        self.log_view.setStyleSheet(
            "background:#10141b; border:1px solid #1f2632; border-radius:8px;"
            "color:#9aa4b4; font-size:11px; padding:6px;"
        )
        lay.addWidget(self.log_view)

        self.refresh()
        self._sync_log()

    # ------------------------------------------------------------------
    def _toggle_guide(self) -> None:
        showing = self.guide_body.isVisible()
        self.guide_body.setVisible(not showing)
        self.guide_btn.setText("怎么用？" if showing else "收起")

    DEF_PROCESS = "DeltaForceClient-Win64-Shipping.exe"

    def _tpl_actions(self, kind: str) -> List[Action]:
        """模板动作链：A 开战 / B 收尾。"""
        if kind == "start":
            # 不切分辨率：一直用原生跑，画面最稳，也不会因为切档闪一下
            return [
                Action(type=ACTION_WAIT, value="30"),         # 游戏加载慢，留够 30 秒
                Action(type=ACTION_ACE_LIMIT, value=""),       # 限 ACE 扫盘
                Action(type=ACTION_FPS_SHOW, value=""),        # 帧率灯
                Action(type=ACTION_REPLAY_START, value=""),    # 回放缓冲
            ]
        return [
            Action(type=ACTION_REPLAY_SAVE, value=""),     # 把最后一段存进素材
            Action(type=ACTION_REPLAY_STOP, value=""),
            Action(type=ACTION_FPS_HIDE, value=""),
            Action(type=ACTION_RESTORE, value=""),
        ]

    def _add_tpl(self, kind: str) -> None:
        kinds = ["start", "stop"] if kind == "both" else [kind]
        made = []
        for k in kinds:
            acts = self._tpl_actions(k)
            name = "三角洲 · 开战准备" if k == "start" else "三角洲 · 收尾归档"
            trig = TRIGGER_START if k == "start" else TRIGGER_STOP
            rule = Rule(
                id=uuid.uuid4().hex[:8],
                name=name,
                trigger=trig,
                process=self.DEF_PROCESS,
                enabled=True,
                actions=acts,
            )
            existed = any(r.name == name for r in self.cfg.rules)
            if existed:
                rule.name = f"{name} 2"
            self.cfg.add_rule(rule)
            made.append(f"{rule.name}（{automation.describe(rule, self.cfg)}）")
        self.cfg.save()
        self.refresh()
        self.win.note_rule_change()
        self.win.toast("已添加：" + "；".join(made))

    def _preset(self, kind: str) -> None:
        tw, th = self.cfg.target
        if kind == "start":
            actions = [
                Action(type=ACTION_RESOLUTION, value=f"{tw}x{th}"),
                Action(type=ACTION_WAIT, value="3"),
            ]
            for mod in self.cfg.mods:
                if mod.enabled:
                    actions.append(Action(type=ACTION_MOD_START, value=mod.id))
                    break
            preset = {
                "name": "开游戏自动切档",
                "trigger": TRIGGER_START,
                "process": "",
                "actions": actions,
            }
        else:
            preset = {
                "name": "关游戏自动还原",
                "trigger": TRIGGER_STOP,
                "process": "",
                "actions": [Action(type=ACTION_RESTORE, value="")],
            }
        dlg = RuleDialog(None, self.cfg, self.win, preset=preset)
        if dlg.exec() == QtWidgets.QDialog.Accepted and dlg.result_rule:
            self.cfg.add_rule(dlg.result_rule)
            self.refresh()
            self.win.note_rule_change()
            self.win.toast(f"已创建「{dlg.result_rule.name}」，记住填进程名并勾选启用")

    # ------------------------------------------------------------------
    def refresh(self) -> None:
        self.listw.blockSignals(True)
        self.listw.clear()
        for rule in self.cfg.rules:
            item = QtWidgets.QListWidgetItem()
            item.setText(
                f"{rule.name}\n"
                f"{TRIGGER_LABEL.get(rule.trigger, rule.trigger)}"
                f"{'  ' + rule.process if rule.process else ''}  ·  "
                f"{automation.describe(rule, self.cfg)}"
            )
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if rule.enabled else Qt.Unchecked)
            item.setData(Qt.UserRole, rule.id)
            item.setSizeHint(QtCore.QSize(0, 54))
            self.listw.addItem(item)
        if not self.cfg.rules:
            placeholder = QtWidgets.QListWidgetItem(
                "还没有规则 —— 先点上面的示例按钮，或「+ 新建规则」自己编一条"
            )
            placeholder.setFlags(Qt.NoItemFlags)
            self.listw.addItem(placeholder)
        self.listw.blockSignals(False)

    def _sync_log(self) -> None:
        self.log_view.setPlainText("\n".join(self.win.auto_log[-40:]))

    def _on_item_changed(self, item: QtWidgets.QListWidgetItem) -> None:
        rid = item.data(Qt.UserRole)
        if not rid:
            return
        rule = self.cfg.get_rule(rid)
        if rule is None:
            return
        rule.enabled = item.checkState() == Qt.Checked
        self.cfg.save()
        self.win.note_rule_change()

    def _current_id(self) -> str:
        item = self.listw.currentItem()
        if item is None:
            return ""
        return item.data(Qt.UserRole) or ""

    def _new(self) -> None:
        dlg = RuleDialog(None, self.cfg, self.win)
        if dlg.exec() == QtWidgets.QDialog.Accepted and dlg.result_rule:
            self.cfg.add_rule(dlg.result_rule)
            self.refresh()
            self.win.note_rule_change()

    def _edit(self) -> None:
        rid = self._current_id()
        rule = self.cfg.get_rule(rid) if rid else None
        if rule is None:
            self.win.toast("先选中一条规则", False)
            return
        dlg = RuleDialog(rule, self.cfg, self.win)
        dlg.rid = rule.id
        dlg.enabled = rule.enabled
        if dlg.exec() == QtWidgets.QDialog.Accepted and dlg.result_rule:
            self.cfg.update_rule(dlg.result_rule)
            self.refresh()
            self.win.note_rule_change()

    def _del(self) -> None:
        rid = self._current_id()
        rule = self.cfg.get_rule(rid) if rid else None
        if rule is None:
            return
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("删除规则")
        box.setText(f"删掉规则「{rule.name}」？")
        box.setStandardButtons(QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        box.setDefaultButton(QtWidgets.QMessageBox.No)
        if box.exec() == QtWidgets.QMessageBox.Yes:
            self.cfg.remove_rule(rule.id)
            self.refresh()
            self.win.note_rule_change()

    def _test(self) -> None:
        rid = self._current_id()
        rule = self.cfg.get_rule(rid) if rid else None
        if rule is None:
            self.win.toast("先选中一条规则", False)
            return
        self.win.run_actions(rule.actions, f"试运行：{rule.name}", dry=True)
        QTimer.singleShot(600, self._sync_log)

    def _run_now(self) -> None:
        rid = self._current_id()
        rule = self.cfg.get_rule(rid) if rid else None
        if rule is None:
            self.win.toast("先选中一条规则", False)
            return
        answer = QtWidgets.QMessageBox.question(
            self,
            "立即执行",
            f"「{rule.name}」会真的跑一遍（可能切分辨率、启停工具），确定吗？",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No,
        )
        if answer != QtWidgets.QMessageBox.Yes:
            return
        self.win.run_actions(rule.actions, f"立即执行：{rule.name}")


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class AudioOSD(QtWidgets.QWidget):
    """切音频时左上角飘一下的小卡片：不抢焦点、鼠标能穿过去、2 秒自己消失。"""

    def __init__(self):
        super().__init__(
            None,
            QtCore.Qt.Tool
            | QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.WindowTransparentForInput
            | QtCore.Qt.WindowDoesNotAcceptFocus,
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setAttribute(QtCore.Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)

        self._slide = QtCore.QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(200)
        self._fade = QtCore.QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(260)
        self._timer = QtCore.QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade_out)

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(16, 10, 22, 12)
        lay.setSpacing(12)
        self.icon = QtWidgets.QLabel()
        self.icon.setFixedSize(34, 34)
        lay.addWidget(self.icon)

        col = QtWidgets.QVBoxLayout()
        col.setSpacing(1)
        self.title = QtWidgets.QLabel("输出已切换")
        self.title.setStyleSheet("color:#5fd9c8;font-size:10pt;font-weight:600;")
        self.name = QtWidgets.QLabel("")
        self.name.setStyleSheet("color:#eaf8f6;font-size:12pt;font-weight:700;")
        col.addWidget(self.title)
        col.addWidget(self.name)
        lay.addLayout(col)
        lay.addStretch(1)

    def paintEvent(self, event):  # noqa: N802
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setBrush(QtGui.QColor(11, 19, 23, 235))
        p.setPen(QtGui.QPen(QtGui.QColor(35, 226, 200, 165), 1.6))
        p.drawRoundedRect(r, 12, 12)
        p.end()

    def show_device(self, name: str, warn: bool = False) -> None:
        self.name.setText(name)
        self.icon.setPixmap(audio_icon_pixmap(name, 34, warn=warn).pixmap(34, 34))
        self.title.setText("切换失败" if warn else "输出已切换")

        scr = QtWidgets.QApplication.screenAt(QtGui.QCursor.pos())
        if scr is None:
            scr = QtWidgets.QApplication.primaryScreen()
        area = scr.availableGeometry()
        self.adjustSize()
        end_x = area.left() + 18
        end_y = area.top() + 18
        self.setWindowOpacity(0.0)
        self.move(end_x - 24, end_y)
        self.show()

        self._slide.stop()
        self._slide.setStartValue(QtCore.QPoint(end_x - 24, end_y))
        self._slide.setEndValue(QtCore.QPoint(end_x, end_y))
        self._fade.stop()
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._slide.start()
        self._fade.start()
        self._timer.start(2000)

    def _fade_out(self) -> None:
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.start()
        self._hide_timer = QtCore.QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)
        self._hide_timer.start(280)



def _round_pixmap(pm: QtGui.QPixmap, radius: int = 12) -> QtGui.QPixmap:
    """给封面切圆角（QLabel 的 border-radius 对 pixmap 无效）。"""
    size = pm.size()
    out = QtGui.QPixmap(size)
    out.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(out)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    path = QtGui.QPainterPath()
    path.addRoundedRect(QtCore.QRectF(0, 0, size.width(), size.height()), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out


def _note_icon(size: int = 40, color: str = "#7c8798") -> QtGui.QPixmap:
    """封面位置上的小板：一个手绘音符，省得空着像加载失败。"""
    px = QtGui.QPixmap(size, size)
    px.fill(QtCore.Qt.transparent)
    p = QtGui.QPainter(px)
    p.setRenderHint(QtGui.QPainter.Antialiasing, True)
    s = size / 40.0
    col = QtGui.QColor(color)
    p.setPen(QtCore.Qt.NoPen)
    p.setBrush(col)
    p.drawEllipse(QtCore.QRectF(7 * s, 25 * s, 13 * s, 10 * s))
    p.drawEllipse(QtCore.QRectF(25 * s, 20 * s, 13 * s, 10 * s))
    p.setPen(QtGui.QPen(col, 2.2 * s))
    p.drawLine(QtCore.QPointF(19.5 * s, 29 * s), QtCore.QPointF(19.5 * s, 8 * s))
    p.drawLine(QtCore.QPointF(37.5 * s, 24 * s), QtCore.QPointF(37.5 * s, 6 * s))
    p.setBrush(QtGui.QBrush(col))
    p.drawPolygon(QtGui.QPolygonF([
        QtCore.QPointF(19.5 * s, 8 * s),
        QtCore.QPointF(37.5 * s, 6 * s),
        QtCore.QPointF(37.5 * s, 12 * s),
        QtCore.QPointF(19.5 * s, 14 * s),
    ]))
    p.end()
    return px


def _mmss(seconds: float) -> str:
    total = max(0, int(seconds or 0))
    return "%d:%02d" % (total // 60, total % 60)


def _open_icon(size: int = 13, color: str = "#cfe0ee") -> QtGui.QPixmap:
    """手绘 ↗（打开 / 跳转），不依赖字体里有没有这个符号。"""
    dpr = 2
    pm = QtGui.QPixmap(size * dpr, size * dpr)
    pm.fill(Qt.transparent)
    s = float(size * dpr)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    pen = QtGui.QPen(QtGui.QColor(color))
    pen.setWidthF(s * 0.15)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawLine(QtCore.QPointF(s * 0.24, s * 0.76), QtCore.QPointF(s * 0.76, s * 0.24))
    p.drawLine(QtCore.QPointF(s * 0.42, s * 0.24), QtCore.QPointF(s * 0.76, s * 0.24))
    p.drawLine(QtCore.QPointF(s * 0.76, s * 0.24), QtCore.QPointF(s * 0.76, s * 0.58))
    p.end()
    return pm


def _media_icon(kind: str, size: int = 16, color: str = "#eef2f8") -> QtGui.QPixmap:
    """手绘 播放 / 暂停 / 上一首 / 下一首，不依赖字体里有没有那些符号。"""
    pm = QtGui.QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QtGui.QPainter(pm)
    p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
    s = size / 16.0
    col = QtGui.QColor(color)
    p.setPen(QtGui.QPen(col, max(1.2, 1.6 * s)))
    p.setBrush(col)

    if kind == "play":
        path = QtGui.QPainterPath()
        path.moveTo(QtCore.QPointF(4.2 * s, 2.4 * s))
        path.lineTo(QtCore.QPointF(13.4 * s, 8.0 * s))
        path.lineTo(QtCore.QPointF(4.2 * s, 13.6 * s))
        path.closeSubpath()
        p.drawPath(path)
    elif kind == "pause":
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QtCore.QRectF(4.6 * s, 2.6 * s, 2.4 * s, 10.8 * s),
                          1.2 * s, 1.2 * s)
        p.drawRoundedRect(QtCore.QRectF(9.0 * s, 2.6 * s, 2.4 * s, 10.8 * s),
                          1.2 * s, 1.2 * s)
    elif kind == "prev":
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QtCore.QRectF(3.2 * s, 2.6 * s, 1.8 * s, 10.8 * s),
                          0.8 * s, 0.8 * s)
        path = QtGui.QPainterPath()
        path.moveTo(QtCore.QPointF(13.4 * s, 2.6 * s))
        path.lineTo(QtCore.QPointF(13.4 * s, 13.4 * s))
        path.lineTo(QtCore.QPointF(6.0 * s, 8.0 * s))
        path.closeSubpath()
        p.drawPath(path)
    else:
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(QtCore.QRectF(11.0 * s, 2.6 * s, 1.8 * s, 10.8 * s),
                          0.8 * s, 0.8 * s)
        path = QtGui.QPainterPath()
        path.moveTo(QtCore.QPointF(2.6 * s, 2.6 * s))
        path.lineTo(QtCore.QPointF(2.6 * s, 13.4 * s))
        path.lineTo(QtCore.QPointF(10.0 * s, 8.0 * s))
        path.closeSubpath()
        p.drawPath(path)
    p.end()
    return pm


# ---------------------------------------------------------------------------
# 音乐页（网易云：搜索 / 我的歌单 / 自己播放）
# ---------------------------------------------------------------------------
def _glass_card(w) -> None:
    """给卡片补一层更实的底：壁纸很亮的时候字也看得清。"""
    w.setStyleSheet(
        "QFrame#Card{background:rgba(10,14,22,.56);"
        "border:1px solid rgba(255,255,255,.09);border-radius:12px;}"
    )


class _Bridge(QtCore.QObject):
    done = QtCore.Signal(object)


def _bg(fn, on_done):
    """把 fn 丢进线程池跑，结果回主线程交给 on_done。"""
    br = _Bridge()

    class _Job(QtCore.QRunnable):
        def run(self):
            try:
                res = fn()
            except Exception as exc:  # noqa: BLE001
                res = {"_error": str(exc)}
            br.done.emit(res)

    QtCore.QThreadPool.globalInstance().start(_Job())
    br.done.connect(on_done)


_COVER_CACHE = {}


def _pix_from_bytes(data, size: int, radius: int = 8):
    if not data:
        return None
    img = QtGui.QImage.fromData(data)
    if img.isNull():
        return None
    pm = QtGui.QPixmap.fromImage(img).scaled(
        size, size, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation
    )
    return _round_pixmap(pm, radius)


def load_cover(url: str, size: int, on_done) -> None:
    """下封面（缓存住），回主线程给 QPixmap，失败给 None。"""
    key = (url, size)
    if key in _COVER_CACHE:
        on_done(_COVER_CACHE[key])
        return
    if not url:
        on_done(None)
        return

    def work():
        try:
            import requests

            r = requests.get(url, timeout=8)
            return r.content if r.status_code == 200 else b""
        except Exception:  # noqa: BLE001
            return b""

    def done(data):
        pm = _pix_from_bytes(data, size)
        if pm is not None:
            _COVER_CACHE[key] = pm
        on_done(pm)

    _bg(work, done)


class _SongRow(QtWidgets.QWidget):
    """一行歌：封面 + 歌名/歌手 + 时长。鼠标全穿透，点击交给列表。"""

    def __init__(self, track: dict):
        super().__init__()
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        h = QtWidgets.QHBoxLayout(self)
        h.setContentsMargins(8, 4, 10, 4)
        h.setSpacing(9)

        self.cover = QtWidgets.QLabel()
        self.cover.setFixedSize(30, 30)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet("border-radius:7px;background:rgba(255,255,255,.06);")
        self.cover.setPixmap(_note_icon(16))
        self.cover.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        h.addWidget(self.cover, 0, Qt.AlignVCenter)

        col = QtWidgets.QVBoxLayout()
        col.setSpacing(1)
        name = QtWidgets.QLabel(track.get("name") or "")
        name.setStyleSheet("font-size:12.5px;color:#eef2f8;")
        name.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        nrow = QtWidgets.QHBoxLayout()
        nrow.setSpacing(6)
        nrow.setContentsMargins(0, 0, 0, 0)
        nrow.addWidget(name, 0)
        if track.get("vip"):
            tag = QtWidgets.QLabel("VIP")
            tag.setStyleSheet(
                "font-size:9px;color:#d9b44a;border:1px solid rgba(217,180,74,.45);"
                "border-radius:4px;padding:0px 3px;"
            )
            tag.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            nrow.addWidget(tag, 0)
        nrow.addStretch(1)
        col.addLayout(nrow)
        sub = QtWidgets.QLabel(track.get("artist") or "—")
        sub.setStyleSheet("font-size:11px;color:#8f9ab0;")
        sub.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        col.addWidget(sub)
        h.addLayout(col, 1)

        dur = QtWidgets.QLabel(_mmss((track.get("dur") or 0) / 1000.0))
        dur.setStyleSheet("font-size:11px;color:#8f9ab0;")
        dur.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        h.addWidget(dur, 0, Qt.AlignVCenter)

        self._url = track.get("cover") or ""

    def load(self) -> None:
        load_cover(self._url, 30, self._set)

    def _set(self, pm) -> None:
        if pm is not None:
            self.cover.setPixmap(pm)


class LoginDialog(QtWidgets.QDialog):
    """扫码登录：出二维码，轮询到 803 就关。"""

    def __init__(self, api, parent=None):
        super().__init__(parent)
        self.api = api
        self.unikey = ""
        self.setWindowTitle("登录网易云音乐")
        self.setFixedSize(304, 396)
        self.setModal(True)

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(10)

        t = QtWidgets.QLabel("用网易云音乐 App 扫码登录")
        t.setStyleSheet("font-size:14px;font-weight:700;color:#eef2f8;")
        v.addWidget(t)

        self.qr = QtWidgets.QLabel()
        self.qr.setFixedSize(176, 176)
        self.qr.setAlignment(Qt.AlignCenter)
        self.qr.setStyleSheet(
            "background:#ffffff;border-radius:10px;color:#666;font-size:12px;"
        )
        self.qr.setText("正在取二维码…")
        v.addWidget(self.qr, 0, Qt.AlignHCenter)

        self.msg = QtWidgets.QLabel("请稍等")
        self.msg.setAlignment(Qt.AlignCenter)
        self.msg.setWordWrap(True)
        self.msg.setStyleSheet("font-size:12px;color:#8f9ab0;")
        v.addWidget(self.msg)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        self.btn_new = QtWidgets.QPushButton("换一张")
        self.btn_new.setObjectName("Ghost")
        self.btn_new.setFixedHeight(30)
        self.btn_new.clicked.connect(self.start_qr)
        self.btn_close = QtWidgets.QPushButton("取消")
        self.btn_close.setObjectName("Ghost")
        self.btn_close.setFixedHeight(30)
        self.btn_close.clicked.connect(self.reject)
        row.addStretch(1)
        row.addWidget(self.btn_new)
        row.addWidget(self.btn_close)
        row.addStretch(1)
        v.addLayout(row)

        self.timer = QTimer(self)
        self.timer.setInterval(1300)
        self.timer.timeout.connect(self.poll)
        QTimer.singleShot(60, self.start_qr)

    def start_qr(self) -> None:
        self.msg.setText("正在取二维码…")
        self.qr.setPixmap(QtGui.QPixmap())
        self.qr.setText("正在取二维码…")
        _bg(lambda: self.api.qr_start(), self._on_qr)

    def _on_qr(self, res) -> None:
        if not isinstance(res, dict) or not res.get("ok"):
            self.qr.setText("二维码取不到\n检查一下网络")
            self.msg.setText(str((res or {}).get("error") or "取二维码失败"))
            return
        self.unikey = res.get("unikey") or ""
        try:
            from core.clipboard_lan import qr_pixmap

            pm = qr_pixmap(res.get("url") or "", 3)
        except Exception:  # noqa: BLE001
            pm = None
        if pm is None:
            self.qr.setText("二维码画不出来\n（缺 segno 库）")
        else:
            self.qr.setPixmap(
                pm.scaled(164, 164, QtCore.Qt.KeepAspectRatio, QtCore.Qt.FastTransformation)
            )
        self.msg.setText("打开网易云 App → 右上角扫一扫")
        self.timer.start()

    def poll(self) -> None:
        if not self.unikey:
            return
        _bg(lambda: self.api.qr_poll(self.unikey), self._on_poll)

    def _on_poll(self, res) -> None:
        if not isinstance(res, dict):
            return
        self.msg.setText(str(res.get("msg") or ""))
        if res.get("ok"):
            self.timer.stop()
            self.msg.setText("登录成功")
            QTimer.singleShot(500, self.accept)


class CookieDialog(QtWidgets.QDialog):
    """贴浏览器 cookie 登录（QQ 音乐 / 酷狗）。"""

    SPECS = {
        "qq": {
            "title": "登录 QQ 音乐",
            "tip": (
                "1）浏览器打开 y.qq.com，扫码登录\n"
                "2）按 F12 → Application（应用）→ Cookies → https://y.qq.com\n"
                "3）找到 uin 和 qm_keyst 两行，把“值”分别复制到下面"
            ),
            "a": ("uin（形如 o0123456789）", "uin"),
            "b": ("qm_keyst（很长的那一串）", "qm_keyst"),
            "min_b": 20,
            "err": "没认出 uin，检查一下是不是带字母 o 的那串",
        },
        "kg": {
            "title": "登录酷狗音乐",
            "tip": (
                "1）浏览器打开 www.kugou.com 并登录\n"
                "2）按 F12 → Application（应用）→ Cookies → https://www.kugou.com\n"
                "3）找到 userid 和 token 两行，把“值”分别复制到下面\n"
                "（token 也可能叫 KugouToken，是一长串字母数字）"
            ),
            "a": ("userid（纯数字的酷狗号）", "userid"),
            "b": ("token（登录票据，很长一串）", "token"),
            "min_b": 16,
            "err": "userid 得是纯数字，检查一下是不是复制错了",
        },
        "kw": {
            "title": "登录酷我音乐",
            "tip": (
                "1）浏览器打开 www.kuwo.cn 并登录\n"
                "2）按 F12 → Application（应用）→ Cookies → https://www.kuwo.cn\n"
                "3）找到 kw_token 那一行，把“值”复制到下面\n"
                "（也可以整段 cookie 粘进来，里面带 kw_token 就行）"
            ),
            "a": ("kw_token（32 位字母数字串）", "kw_token"),
            "b": ("", ""),
            "min_a": 12,
            "err": "没认出 kw_token，看看是不是复制到了别的 cookie",
        },
    }

    def __init__(self, api, parent=None, src: str = "qq"):
        super().__init__(parent)
        self.api = api
        self.spec = self.SPECS.get(src) or self.SPECS["qq"]
        spec = self.spec
        self.setWindowTitle(spec["title"])
        self.setFixedSize(438, 336)
        self.setModal(True)

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 14)
        v.setSpacing(9)

        t = QtWidgets.QLabel("把浏览器里登录好的 cookie 贴进来")
        t.setStyleSheet("font-size:14px;font-weight:700;color:#eef2f8;")
        v.addWidget(t)

        tip = QtWidgets.QLabel(spec["tip"])
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        v.addWidget(tip)

        self.ed_uin = QtWidgets.QLineEdit()
        self.ed_uin.setPlaceholderText(spec["a"][0])
        self.ed_uin.setFixedHeight(30)
        v.addWidget(self.ed_uin)

        self.ed_key = QtWidgets.QLineEdit()
        self.ed_key.setPlaceholderText(spec["b"][0])
        self.ed_key.setFixedHeight(30)
        v.addWidget(self.ed_key)
        if not spec.get("b") or not spec["b"][1]:
            self.ed_key.hide()

        self.msg = QtWidgets.QLabel("")
        self.msg.setObjectName("Hint")
        self.msg.setWordWrap(True)
        v.addWidget(self.msg)
        v.addStretch(1)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        row.addStretch(1)
        btn_ok = QtWidgets.QPushButton("确定")
        btn_ok.setObjectName("Ghost")
        btn_ok.setFixedHeight(30)
        btn_ok.clicked.connect(self._ok)
        btn_no = QtWidgets.QPushButton("取消")
        btn_no.setObjectName("Ghost")
        btn_no.setFixedHeight(30)
        btn_no.clicked.connect(self.reject)
        row.addWidget(btn_ok)
        row.addWidget(btn_no)
        row.addStretch(1)
        v.addLayout(row)

    def _ok(self) -> None:
        a = (self.ed_uin.text() or "").strip()
        b = (self.ed_key.text() or "").strip()
        one = not self.spec.get("b") or not self.spec["b"][1]
        if not a or (not one and not b):
            if one:
                self.msg.setText("得填：%s" % self.spec["a"][1])
            else:
                self.msg.setText("两行都得填：%s 和 %s"
                                 % (self.spec["a"][1], self.spec["b"][1]))
            return
        if one:
            if len(a) < self.spec.get("min_a", 8):
                self.msg.setText("%s 太短，检查一下是不是贴错了" % self.spec["a"][1])
                return
            res = self.api.set_cookie(a)
        else:
            if len(b) < self.spec.get("min_b", 8):
                self.msg.setText("%s 通常是很长的一串，检查一下是不是贴错了"
                                 % self.spec["b"][1])
                return
            res = self.api.set_cookie(a, b)
        if res.get("ok"):
            self.accept()
        else:
            self.msg.setText(self.spec["err"])


_LOGIN_PROFILE = []
_SPY_KEEP = []
_SPY_SEEN = set()


def _spy_log(url: str, headers: str) -> None:
    """把网页自己发出的请求记进日志，方便从里面捡真凭据。"""
    if len(_SPY_SEEN) >= 260 or url in _SPY_SEEN:
        return
    _SPY_SEEN.add(url)
    log.info("网页请求: %s", url[:300])
    for line in (headers or "").splitlines():
        low = line.lower()
        if any(k in low for k in ("token", "csrf", "userid", "cookie", "authorization")):
            log.info("    头: %s", line.strip()[:220])
            break


def _login_profile():
    """网页登录共用一个持久浏览器配置，cookie 落到程序目录的 网页登录 里。

    必须用持久配置：Qt 的一次性（off-the-record）浏览器配置压根不上报 cookie，
    实测一条都收不到，登录信息就永远抄不进来——这就是点按钮没反应的原因。
    持久化还有个白赚的好处：下次打开登录窗还是登录态，不用重扫。
    """
    if _LOGIN_PROFILE:
        return _LOGIN_PROFILE[0]
    from PySide6.QtWebEngineCore import QWebEngineProfile

    base = app_dir() / "网页登录"
    try:
        (base / "cache").mkdir(parents=True, exist_ok=True)
    except Exception:  # noqa: BLE001
        base = app_dir()
    prof = QWebEngineProfile("flint_login")
    prof.setPersistentStoragePath(str(base))
    prof.setCachePath(str(base / "cache"))
    prof.setHttpUserAgent(WebLoginDialog.UA)
    _LOGIN_PROFILE.append(prof)
    try:
        spy = _ReqSpy(_spy_log)
        prof.setUrlRequestInterceptor(spy)
        _SPY_KEEP.append(spy)
        log.info("网页登录：请求监听器已挂上")
    except Exception as exc:  # noqa: BLE001
        log.info("网页登录：请求监听器挂不上（%s）", exc)
    return prof


def _unjs(raw: str) -> str:
    """把酷狗/酷我 cookie 里那种 %u6c90 的转义解回中文。"""
    try:
        txt = re.sub(r"%u([0-9a-fA-F]{4})", lambda m: chr(int(m.group(1), 16)), str(raw or ""))
        return urllib.parse.unquote(txt)
    except Exception:  # noqa: BLE001
        return str(raw or "")


try:
    from PySide6.QtWebEngineCore import QWebEngineUrlRequestInterceptor as _WI
except Exception:  # noqa: BLE001
    _WI = None


if _WI is not None:

    class _ReqSpy(_WI):
        LIMIT = 260

        def __init__(self, cb, parent=None) -> None:
            super().__init__(parent)
            self._cb = cb

        def interceptRequest(self, info) -> None:
            try:
                url = info.requestUrl().toString()
                hd = bytes(info.httpHeaders()).decode("utf-8", "replace")
                self._cb(url, hd)
            except Exception:  # noqa: BLE001
                return

else:

    class _ReqSpy:  # 没带浏览器的环境里的占位，什么也不做
        def __init__(self, cb, parent=None) -> None:
            self._cb = cb

        def interceptRequest(self, info) -> None:
            return


class WebLoginDialog(QtWidgets.QDialog):
    """网页登录窗：内嵌浏览器打开官网，你自己扫码/输账号，登完把 cookie 抄进会话。

    为什么不直接"扫码接口"：QQ 音乐、酷狗、酷我的扫码都是各家私有流程
    （QQ 得先过 ptlogin 再换 qm_keyst、酷狗要 mid/dfid 签名、酷我带 csrf），
    签名一改就全废。让它们的官网自己完成登录，我们只把结果 cookie 拿回来。
    """

    PAGES = {
        "qq": (
            "登录 QQ 音乐",
            "https://y.qq.com/",
            "在下面窗口里点右上角「登录」，扫码或输账号都行；登完点「我登好了」。",
        ),
        "kg": (
            "登录酷狗音乐",
            "https://www.kugou.com/",
            "在下面窗口里点右上角「登录」，扫码或输账号都行；登完点「我登好了」。",
        ),
        "kw": (
            "登录酷我音乐",
            "https://www.kuwo.cn/",
            "在下面窗口里点右上角「登录」，扫码或输账号都行；登完点「我登好了」。",
        ),
    }
    UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self, api, parent=None, src: str = "qq") -> None:
        super().__init__(parent)
        self.api = api
        self.src = src if src in self.PAGES else "qq"
        title, url, hint = self.PAGES[self.src]
        self.setWindowTitle(title)
        self.setModal(True)
        self._jar: dict = {}
        self._pending = False
        self._tries = 0
        self._answered = False
        self.view = None
        self.prof = None
        self._store = None

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)

        head = QtWidgets.QLabel(hint)
        head.setObjectName("Hint")
        head.setWordWrap(True)
        head.setMinimumHeight(26)
        v.addWidget(head)

        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtWebEngineCore import QWebEnginePage
            from PySide6.QtWebEngineWidgets import QWebEngineView

            self.prof = _login_profile()
            self.page = QWebEnginePage(self.prof, self)
            self.view = QWebEngineView(self)
            self.view.setPage(self.page)
            self.view.load(QUrl(url))
            v.addWidget(self.view, 1)
            self._store = self.prof.cookieStore()
            self._store.cookieAdded.connect(self._on_cookie)
            self._tm = QtCore.QTimer(self)
            self._tm.setInterval(2000)
            self._tm.timeout.connect(self._tick)
            self._tm.start()
            self.resize(1040, 780)
        except Exception as exc:  # noqa: BLE001
            lab = QtWidgets.QLabel(
                "这个版本没带内嵌浏览器，只能走「手动贴 cookie」。\n（%s）" % exc
            )
            lab.setObjectName("Hint")
            lab.setWordWrap(True)
            v.addWidget(lab, 1)
            self.resize(520, 260)

        self.status = QtWidgets.QLabel(
            "等你在上面登录…（登录完点右下角「我登好了」）" if self.view else ""
        )
        self.status.setObjectName("Hint")
        self.status.setWordWrap(True)
        v.addWidget(self.status)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(8)
        b_man = QtWidgets.QPushButton("手动贴 cookie")
        b_man.setObjectName("Mini")
        b_man.setToolTip("网页登录认不出来时，退回老的贴 cookie 办法")
        b_man.clicked.connect(self._manual)
        row.addWidget(b_man)
        if self.view is not None:
            b_re = QtWidgets.QPushButton("刷新页面")
            b_re.setObjectName("Mini")
            b_re.clicked.connect(self.view.reload)
            row.addWidget(b_re)
        row.addStretch(1)
        b_ok = QtWidgets.QPushButton("我登好了")
        b_ok.setObjectName("Ghost")
        b_ok.setFixedHeight(30)
        b_ok.clicked.connect(self._on_ok)
        row.addWidget(b_ok)
        b_no = QtWidgets.QPushButton("取消")
        b_no.setObjectName("Ghost")
        b_no.setFixedHeight(30)
        b_no.clicked.connect(self.reject)
        row.addWidget(b_no)
        v.addLayout(row)

    # ---------------- cookie ----------------
    def _on_cookie(self, cookie) -> None:
        try:
            name = bytes(cookie.name()).decode("utf-8", "replace").strip().lower()
            val = bytes(cookie.value()).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            return
        if not name or not val:
            return
        self._jar[name] = val
        if not self._pending and self._pick():
            self.status.setText(
                "已看到登录信息（闻到 %d 个 cookie），点「我登好了」写进来" % len(self._jar)
            )

    def _tick(self) -> None:
        """闲时只刷新状态，不影响你点按钮。"""
        if self.view is None or self._pending or self._answered:
            return
        page = getattr(self, "page", None)
        if page is None:
            return
        try:
            page.runJavaScript("document.cookie", self._tick_js)
        except Exception:  # noqa: BLE001
            return

    def _tick_js(self, text) -> None:
        self._absorb(text)
        if self._pick():
            self.status.setText(
                "已看到登录信息（%d 个 cookie），点「我登好了」写进来" % len(self._jar)
            )
        elif self._jar:
            self.status.setText("已收到 %d 个 cookie，还没看到登录那一条…" % len(self._jar))

    def _on_ok(self) -> None:
        if self.view is None:
            self._manual()
            return
        self._pending = True
        self._tries = 3
        self.status.setText("正在从浏览器里读登录信息…")
        QtWidgets.QApplication.processEvents()
        self._grab(True)

    def _grab(self, final: bool) -> None:
        page = getattr(self, "page", None)
        if page is not None:
            try:
                page.runJavaScript("document.cookie", lambda t: self._after_js(t, final))
                return
            except Exception:  # noqa: BLE001
                pass
        self._after(final)

    def _after_js(self, text, final: bool) -> None:
        self._absorb(text)
        QtCore.QTimer.singleShot(150, lambda: self._after(final))

    def _absorb(self, text) -> None:
        """把 document.cookie 那串 a=b; c=d 收进 jar。"""
        for part in str(text or "").split(";"):
            if "=" not in part:
                continue
            name, val = part.split("=", 1)
            name = name.strip().lower()
            val = val.strip()
            if name and val:
                self._jar[name] = val

    def _after(self, final: bool) -> None:
        got = self._pick()
        if got:
            self._pending = False
            self._commit_and_close(got)
            return
        if not final:
            self._pending = False
            return
        self._tries -= 1
        if self._tries > 0:
            self.status.setText("还没读到关键那条，再等一下（还剩 %d 次）…" % self._tries)
            self._grab(True)
            return
        self._pending = False
        self._answered = True
        log.info(
            "网页登录[%s] 没认出来：cookie %d 条 %s",
            self.src,
            len(self._jar),
            sorted(self._jar.keys()),
        )
        self._dig()
        self.status.setText(
            "没读到登录信息。两种可能：①上面页面还没真的登进去；"
            "②这家把登录信息设成了网页不可读的 cookie。先看页面右上角是不是你的账号，"
            "还不行就点左下角「手动贴 cookie」。"
        )

    def _pick(self):
        """从浏览器里挑出各家真正能用的那几条（名字都实测过，别凭想象改）。"""
        j = self._jar
        if self.src == "qq":
            uin = j.get("uin") or j.get("p_uin") or ""
            key = j.get("qm_keyst") or j.get("qqmusic_key") or ""
            return (uin, key) if (uin and key) else None
        if self.src == "kg":
            # 酷狗：账号、钥匙、昵称全塞在 KuGoo 这一个 cookie 的值里
            # KuGoo=KugooID=423163927&KugooPwd=...&NickName=%u6c90...&t=e799...
            blob = j.get("kugoo") or ""
            uid = ""
            m = re.search(r"KugooID=(\d+)", blob, re.I)
            if m:
                uid = m.group(1)
            if not uid:
                for k in ("kugooid", "userid", "kugouid", "kg_userid"):
                    v = "".join(ch for ch in (j.get(k) or "") if ch.isdigit())
                    if v:
                        uid = v
                        break
            tok = ""
            m2 = re.search(r"(?:^|&)t=([0-9a-fA-F]{16,})", blob)
            if m2:
                tok = m2.group(1)
            if not tok:
                for k in ("t", "token", "kugoutoken"):
                    v = (j.get(k) or "").strip()
                    if len(v) >= 16:
                        tok = v
                        break
            return (uid, tok) if (uid and tok) else None
        # 酷我：网页版登录状态就是 userid（那套接口签名跟网页版不是一回事）
        uid = (j.get("userid") or "").strip()
        return (uid,) if uid else None

    def _nick_from_cookie(self) -> str:
        if self.src == "kg":
            m = re.search(r"NickName=([^&]*)", self._jar.get("kugoo") or "")
            return _unjs(m.group(1)).strip() if m else ""
        for k in ("uname3", "username"):
            v = (self._jar.get(k) or "").strip()
            if v:
                return _unjs(v)
        m = re.search(r"NickName=([^&]*)", self._jar.get("kugoo") or "")
        return _unjs(m.group(1)).strip() if m else ""

    def _commit(self, got) -> dict:
        if self.src == "kg":
            res = self.api.set_cookie(got[0], got[1])
            nick = self._nick_from_cookie()
            if res.get("ok") and nick:
                try:
                    self.api.nick = nick
                except Exception:  # noqa: BLE001
                    pass
            return res
        if self.src == "qq":
            return self.api.set_cookie(got[0], got[1])
        if hasattr(self.api, "set_web"):
            return self.api.set_web(self._jar)
        return self.api.set_cookie(got[0], "")

    def _commit_and_close(self, got) -> None:
        self._answered = True
        self.status.setText("正在写进程序…")
        QtWidgets.QApplication.processEvents()
        try:
            res = self._commit(got)
        except Exception as exc:  # noqa: BLE001
            self._answered = True
            self.status.setText("写入失败：%s" % exc)
            return
        if not res.get("ok"):
            self._answered = True
            self.status.setText("认到了 cookie，但对面不认这把钥匙：换「手动贴 cookie」试试")
            return
        self.accept()

    _seen: set = set()

    def _on_request(self, url: str, headers: str) -> None:
        if url in WebLoginDialog._seen:
            return
        WebLoginDialog._seen.add(url)
        log.info("网页请求[%s]: %s", self.src, url[:320])
        if headers:
            for line in headers.splitlines():
                low = line.lower()
                if any(k in low for k in ("token", "csrf", "userid", "cookie")):
                    log.info("    头: %s", line.strip()[:240])

    def _dig(self) -> None:
        """认不出来就把现场翻一遍：cookie 名单 + localStorage，写进日志对症。"""
        if self.view is None or getattr(self, "page", None) is None:
            return
        script = (
            "(function(){"
            "var ls={};for(var i=0;i<localStorage.length;i++){var k=localStorage.key(i);"
            "ls[k]=String(localStorage.getItem(k)).slice(0,44);}"
            "var ss=[];for(var j=0;j<sessionStorage.length;j++){ss.push(sessionStorage.key(j));}"
            "return JSON.stringify({ck:document.cookie.slice(0,600),ls:ls,ss:ss});"
            "})()"
        )
        try:
            self.page.runJavaScript(script, self._dug)
        except Exception as exc:  # noqa: BLE001
            log.info("网页登录[%s] 现场读不出来：%s", self.src, exc)

    def _dug(self, res) -> None:
        log.info("网页登录[%s] 页面现场：%s", self.src, res)

    def _manual(self) -> None:
        dlg = CookieDialog(self.api, self, self.src)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.accept()


class _RewardQr(QtWidgets.QLabel):
    """赞赏码：等比缩成小方图，点一下开大窗看原图。"""

    def __init__(self, path: Path, parent=None) -> None:
        super().__init__(parent)
        self._pm = QtGui.QPixmap(str(path)) if path.exists() else QtGui.QPixmap()
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("点一下看大图")
        if not self._pm.isNull():
            self.setPixmap(
                self._pm.scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

    def mouseReleaseEvent(self, ev) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self.open_big()
        super().mouseReleaseEvent(ev)

    def open_big(self) -> None:
        if self._pm.isNull():
            return
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle("请作者喝杯咖啡")
        box = QtWidgets.QVBoxLayout(dlg)
        box.setContentsMargins(12, 12, 12, 12)
        lab = QtWidgets.QLabel()
        lab.setAlignment(Qt.AlignCenter)
        lab.setPixmap(
            self._pm.scaled(660, 660, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        box.addWidget(lab)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        ok = QtWidgets.QPushButton("知道了")
        ok.clicked.connect(dlg.accept)
        row.addWidget(ok)
        box.addLayout(row)
        dlg.exec()


class _ModeIsland(QtWidgets.QFrame):
    """游戏模式开 / 关的轻提示：出现在音乐灵动岛那一块，两秒多自己收回去。

    刻意不做成告警样式 —— 只是个「状态变了」的确认，青色点亮表示开，
    灰色表示关，跟主页那个连接状态点是同一套语言。
    """

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setObjectName("ModeIsland")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFixedHeight(44)
        self.setStyleSheet(
            "QFrame#ModeIsland{background:rgba(10,14,22,.90);"
            "border:1px solid rgba(255,255,255,.14);border-radius:22px;}"
        )
        row = QtWidgets.QHBoxLayout(self)
        row.setContentsMargins(15, 5, 19, 5)
        row.setSpacing(11)
        self.dot = QtWidgets.QLabel()
        self.dot.setFixedSize(9, 9)
        self.dot.setStyleSheet("background:#20ffe0;border-radius:5px;")
        row.addWidget(self.dot, 0, Qt.AlignVCenter)
        col = QtWidgets.QVBoxLayout()
        col.setSpacing(1)
        self.tit = QtWidgets.QLabel("")
        self.tit.setStyleSheet("font-size:12px;font-weight:600;color:#eef2f8;")
        self.sub = QtWidgets.QLabel("")
        self.sub.setStyleSheet("font-size:10px;color:#8b96a8;")
        col.addWidget(self.tit)
        col.addWidget(self.sub)
        row.addLayout(col, 1)

        self._eff = QtWidgets.QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._eff)
        self._eff.setOpacity(0.0)
        self._anim = QtCore.QPropertyAnimation(self._eff, b"opacity", self)
        self._tm = QtCore.QTimer(self)
        self._tm.setSingleShot(True)
        self._tm.timeout.connect(self._fade_out)
        self.hide()

    def flash(self, on: bool) -> None:
        if on:
            self.say("游戏模式已开启", "壁纸收起 · 采集 6 秒 · 电源计划", True, 2400)
        else:
            self.say("游戏模式已关闭", "壁纸、采集频率、电源计划都放回去了", False, 2400)

    def say(self, title: str, sub: str = "", ok: bool = True,
            msec: int = 2600) -> None:
        """任何提示都从这儿上岛：一行主标题 + 可选一行小字说明。"""
        title = (title or "").strip()
        if not title:
            return
        if len(title) > 26:
            title = title[:25].rstrip() + "…"
        sub = (sub or "").strip()
        self.tit.setText(title)
        self.sub.setText(sub)
        self.sub.setVisible(bool(sub))
        if sub:
            self.setFixedHeight(44)
        else:
            # 只有一行时把胶囊压矮一点，不然中间空一块
            self.setFixedHeight(34)
        self.dot.setStyleSheet(
            "background:%s;border-radius:5px;" % ("#20ffe0" if ok else "#6b7787")
        )
        self._fit()
        self.place()
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setDuration(150)
        self._anim.setStartValue(max(0.0, float(self._eff.opacity())))
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._tm.start(max(1200, int(msec)))

    def _fit(self) -> None:
        hint = self.sizeHint().width()
        self.setFixedWidth(max(262, min(380, hint)))

    def _fade_out(self) -> None:
        self._anim.stop()
        self._anim.setDuration(220)
        self._anim.setStartValue(max(0.0, float(self._eff.opacity())))
        self._anim.setEndValue(0.0)
        self._anim.start()
        QtCore.QTimer.singleShot(230, self.hide)

    def place(self) -> None:
        ww = self.win.width()
        x = (ww - self.width()) // 2
        # 右边还有音频 / 设置 / 皮肤 + 分辨率框 + 窗口按钮，别压上去
        limit = ww - 330 - self.width()
        if x > max(12, limit):
            x = max(12, limit)
        y = 6
        btn = getattr(self.win, "set_btn", None)
        if btn is not None and btn.isVisible():
            cy = btn.mapTo(self.win, QtCore.QPoint(0, 0)).y() + btn.height() // 2
            y = max(4, cy - self.height() // 2)
        isl = getattr(self.win, "island", None)
        if isl is not None and isl.isVisible():
            # 音乐岛在的话别压上去，挪到它下面
            y = isl.geometry().bottom() + 6
        self.move(max(12, x), y)


class _IslandBar(QtWidgets.QWidget):
    """灵动岛底下的声纹律动：播放时一排竖条起伏，暂停时压成一条矮线。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(11)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.playing = False
        self.ratio = 0.0
        self._phase = 0.0
        self._tm = QtCore.QTimer(self)
        self._tm.setInterval(33)
        self._tm.timeout.connect(self._tick)

    def _tick(self) -> None:
        self._phase += 0.19
        self.update()

    def set_playing(self, playing: bool) -> None:
        playing = bool(playing)
        if playing == self.playing and self._tm.isActive() == playing:
            return
        self.playing = playing
        if playing:
            if not self._tm.isActive():
                self._tm.start()
        else:
            self._tm.stop()
        self.update()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._tm.stop()
        super().hideEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        w = self.width()
        h = float(self.height())
        if w <= 8:
            return
        n = max(16, int(w / 6.0))
        gap = 3.0
        bw = max(1.4, (w - gap * (n - 1)) / n)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        p.setPen(Qt.PenStyle.NoPen)
        quiet = QtGui.QColor(255, 255, 255, 46)
        for i in range(n):
            if self.playing:
                a = math.sin(self._phase * 1.6 + i * 0.58)
                b = math.sin(self._phase * 0.86 - i * 0.27)
                c = math.sin(self._phase * 2.4 + i * 1.13)
                amp = (a * 0.46 + b * 0.32 + c * 0.22) * 0.5 + 0.5
                env = 0.42 + 0.58 * math.sin((i + 0.5) / n * math.pi)
                hh = 1.6 + (h - 2.0) * amp * env
                col = QtGui.QColor(32, 255, 224)
                col.setAlpha(int(85 + 145 * amp))
                p.setBrush(col)
            else:
                hh = 1.8
                p.setBrush(quiet)
            x = i * (bw + gap)
            p.drawRoundedRect(
                QtCore.QRectF(x, (h - hh) / 2.0, bw, hh), bw / 2.0, bw / 2.0
            )
        p.end()


class MiniPlayer(QtWidgets.QFrame):
    """顶部中间的灵动岛：有歌在放就浮出来，任何页面都能暂停 / 切歌。

    音乐页自己有整条播放器，所以在音乐页会把这块收起来，免得重复。
    """

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.player = getattr(win, "player", None)
        self._cov_url = ""
        self.setObjectName("Island")
        self.setFixedSize(300, 44)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(
            "QFrame#Island{background:rgba(10,14,22,.84);"
            "border:1px solid rgba(255,255,255,.14);border-radius:22px;}"
        )
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("点一下展开，再点收起")
        self._open = False
        self._drag = False
        self._dur = 0
        self._icons = {
            "play": QtGui.QIcon(_media_icon("play", 13)),
            "pause": QtGui.QIcon(_media_icon("pause", 13)),
            "play_big": QtGui.QIcon(_media_icon("play", 15)),
            "pause_big": QtGui.QIcon(_media_icon("pause", 15)),
        }

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # ---------------- 紧凑态 ----------------
        self.small = QtWidgets.QWidget()
        self.small.installEventFilter(self)
        sv = QtWidgets.QVBoxLayout(self.small)
        sv.setContentsMargins(0, 0, 0, 3)
        sv.setSpacing(0)

        row = QtWidgets.QHBoxLayout()
        row.setContentsMargins(9, 4, 7, 2)
        row.setSpacing(7)
        sv.addLayout(row, 1)

        self.cover = QtWidgets.QLabel()
        self.cover.setFixedSize(22, 22)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet("border-radius:6px;background:rgba(255,255,255,.07);")
        self.cover.setPixmap(_note_icon(11))
        self.cover.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        row.addWidget(self.cover, 0, Qt.AlignVCenter)

        self.tit = QtWidgets.QLabel("")
        self.tit.setStyleSheet("font-size:12px;color:#eef2f8;")
        self.tit.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.tit.setMinimumWidth(0)
        row.addWidget(self.tit, 1)

        self.btn_prev = QtWidgets.QPushButton()
        self.btn_play = QtWidgets.QPushButton()
        self.btn_next = QtWidgets.QPushButton()
        for b, kind, tip in (
            (self.btn_prev, "prev", "上一首"),
            (self.btn_play, "play", "播放 / 暂停"),
            (self.btn_next, "next", "下一首"),
        ):
            b.setObjectName("Ghost")
            b.setFixedSize(26, 23)
            b.setIconSize(QtCore.QSize(12, 12))
            b.setIcon(QtGui.QIcon(_media_icon(kind, 12)))
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            b.setStyleSheet(
                "padding:0px;border:none;border-radius:11px;background:transparent;"
                "QPushButton:hover{background:rgba(255,255,255,.10);}"
            )
            row.addWidget(b, 0)
        self.btn_prev.clicked.connect(self._prev)
        self.btn_play.clicked.connect(self._toggle)
        self.btn_next.clicked.connect(self._next)

        # 声纹律动只占歌名那一段，不压到右边按钮
        self.bar = _IslandBar()
        wsw = QtWidgets.QHBoxLayout()
        wsw.setContentsMargins(9, 0, 7, 0)
        wsw.setSpacing(0)
        wsw.addWidget(self.bar, 1)
        wsw.addSpacing(86)
        sv.addLayout(wsw)
        v.addWidget(self.small)

        # ---------------- 展开态 ----------------
        self.big = QtWidgets.QWidget()
        self.big.installEventFilter(self)
        bv = QtWidgets.QVBoxLayout(self.big)
        bv.setContentsMargins(12, 9, 12, 7)
        bv.setSpacing(5)

        btop = QtWidgets.QHBoxLayout()
        btop.setContentsMargins(0, 0, 0, 0)
        btop.setSpacing(9)

        self.cover_big = QtWidgets.QLabel()
        self.cover_big.setFixedSize(54, 54)
        self.cover_big.setAlignment(Qt.AlignCenter)
        self.cover_big.setStyleSheet("border-radius:12px;background:rgba(255,255,255,.07);")
        self.cover_big.setPixmap(_note_icon(20))
        self.cover_big.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        btop.addWidget(self.cover_big, 0, Qt.AlignTop)

        binfo = QtWidgets.QVBoxLayout()
        binfo.setContentsMargins(0, 2, 0, 0)
        binfo.setSpacing(3)
        self.tit_big = QtWidgets.QLabel("")
        self.tit_big.setStyleSheet("font-size:14px;font-weight:600;color:#f2f6fb;")
        self.tit_big.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        binfo.addWidget(self.tit_big)
        self.art_big = QtWidgets.QLabel("")
        self.art_big.setStyleSheet("font-size:11px;color:#94a6ba;")
        self.art_big.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        binfo.addWidget(self.art_big)
        binfo.addStretch(1)
        btop.addLayout(binfo, 1)

        self.btn_go = QtWidgets.QPushButton()
        self.btn_go.setObjectName("Ghost")
        self.btn_go.setFixedSize(24, 24)
        self.btn_go.setIcon(QtGui.QIcon(_open_icon(13)))
        self.btn_go.setIconSize(QtCore.QSize(13, 13))
        self.btn_go.setCursor(Qt.PointingHandCursor)
        self.btn_go.setToolTip("打开音乐页")
        self.btn_go.setStyleSheet(
            "padding:0px;border:none;border-radius:12px;background:transparent;"
            "QPushButton:hover{background:rgba(255,255,255,.10);}"
        )
        self.btn_go.clicked.connect(self._goto_page)
        btop.addWidget(self.btn_go, 0, Qt.AlignTop)
        bv.addLayout(btop)

        self.seek = QtWidgets.QSlider(Qt.Horizontal)
        self.seek.setRange(0, 1000)
        self.seek.setFixedHeight(16)
        self.seek.setCursor(Qt.PointingHandCursor)
        self.seek.setToolTip("拖一下跳转播放位置")
        self.seek.setStyleSheet(
            "QSlider{margin:0px;}"
            "QSlider::groove:horizontal{height:4px;background:rgba(255,255,255,.16);"
            "border-radius:2px;}"
            "QSlider::sub-page:horizontal{background:#20ffe0;border-radius:2px;}"
            "QSlider::add-page:horizontal{background:rgba(255,255,255,.16);"
            "border-radius:2px;}"
            "QSlider::handle:horizontal{width:11px;height:11px;margin:-4px 0px;"
            "border-radius:6px;background:#eafffb;}"
        )
        self.seek.sliderPressed.connect(self._seek_down)
        self.seek.sliderMoved.connect(self._seek_move)
        self.seek.sliderReleased.connect(self._seek_up)
        bv.addWidget(self.seek)

        brow = QtWidgets.QHBoxLayout()
        brow.setContentsMargins(0, 1, 0, 0)
        brow.setSpacing(6)
        self.time_big = QtWidgets.QLabel("0:00 / 0:00")
        self.time_big.setStyleSheet("font-size:10px;color:#8496a8;")
        self.time_big.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        brow.addWidget(self.time_big, 0, Qt.AlignVCenter)
        brow.addStretch(1)

        self.btn_prev_big = QtWidgets.QPushButton()
        self.btn_play_big = QtWidgets.QPushButton()
        self.btn_next_big = QtWidgets.QPushButton()
        for b, kind, tip in (
            (self.btn_prev_big, "prev", "上一首"),
            (self.btn_play_big, "play", "播放 / 暂停"),
            (self.btn_next_big, "next", "下一首"),
        ):
            b.setObjectName("Ghost")
            b.setFixedSize(30, 26)
            b.setIconSize(QtCore.QSize(15, 15))
            b.setIcon(QtGui.QIcon(_media_icon(kind, 15)))
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            b.setStyleSheet(
                "padding:0px;border:none;border-radius:13px;background:transparent;"
                "QPushButton:hover{background:rgba(255,255,255,.10);}"
            )
            brow.addWidget(b, 0)
        self.btn_prev_big.clicked.connect(self._prev)
        self.btn_play_big.clicked.connect(self._toggle)
        self.btn_next_big.clicked.connect(self._next)
        bv.addLayout(brow)

        # 音量：展开态才有，竖向滚轮和拖滑块都算
        vrow = QtWidgets.QHBoxLayout()
        vrow.setContentsMargins(2, 0, 2, 0)
        vrow.setSpacing(6)
        self.vol_icon = QtWidgets.QLabel()
        self.vol_icon.setFixedSize(14, 14)
        self.vol_icon.setPixmap(self._vol_glyph(13))
        self.vol_icon.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        vrow.addWidget(self.vol_icon, 0, Qt.AlignVCenter)

        self.vol = QtWidgets.QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(70)
        self.vol.setFixedHeight(16)
        self.vol.setCursor(Qt.PointingHandCursor)
        self.vol.setToolTip("音量：拖一下或滚轮调")
        self.vol.setStyleSheet(
            "QSlider{margin:0px;}"
            "QSlider::groove:horizontal{height:4px;background:rgba(255,255,255,.16);"
            "border-radius:2px;}"
            "QSlider::sub-page:horizontal{background:rgba(32,255,224,.72);border-radius:2px;}"
            "QSlider::add-page:horizontal{background:rgba(255,255,255,.16);"
            "border-radius:2px;}"
            "QSlider::handle:horizontal{width:10px;height:10px;margin:-3px 0px;"
            "border-radius:5px;background:#eafffb;}"
        )
        self.vol.sliderPressed.connect(self._vol_down)
        self.vol.sliderMoved.connect(self._vol_move)
        self.vol.sliderReleased.connect(self._vol_up)
        vrow.addWidget(self.vol, 1)

        self.vol_pct = QtWidgets.QLabel("70%")
        self.vol_pct.setFixedWidth(34)
        self.vol_pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.vol_pct.setStyleSheet("font-size:10px;color:#8496a8;background:transparent;")
        self.vol_pct.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        vrow.addWidget(self.vol_pct, 0)
        bv.addLayout(vrow)
        self._vol_drag = False

        v.addWidget(self.big)
        self.big.hide()

    # ---------------- 展开 / 收起 ----------------
    def _apply_size(self) -> None:
        if self._open:
            self.small.hide()
            self.big.show()
            self.setFixedSize(330, 152)
        else:
            self.big.hide()
            self.small.show()
            self.setFixedSize(300, 44)
        self.place()

    def _toggle_open(self) -> None:
        self._open = not self._open
        self._apply_size()

    def _goto_page(self) -> None:
        if self._open:
            self._open = False
            self._apply_size()
        self.win._goto("music_page")

    # ---------------- 音量 ----------------
    def _vol_glyph(self, size: int) -> QtGui.QPixmap:
        """小喇叭：一个方块身子 + 三角嘴 + 两道弧，跟其他图标一样是画的。"""
        px = max(8, int(size)) * 2
        pm = QtGui.QPixmap(px, px)
        pm.fill(Qt.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        k = px / 13.0
        col = QtGui.QColor(143, 182, 200)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRect(QtCore.QRectF(1.2 * k, 4.6 * k, 2.4 * k, 3.8 * k))
        p.drawPolygon(QtGui.QPolygonF([
            QtCore.QPointF(3.4 * k, 4.6 * k),
            QtCore.QPointF(6.4 * k, 2.4 * k),
            QtCore.QPointF(6.4 * k, 10.4 * k),
            QtCore.QPointF(3.4 * k, 8.4 * k),
        ]))
        pen = QtGui.QPen(col)
        pen.setWidthF(1.1 * k)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QtCore.QRectF(5.6 * k, 2.6 * k, 6.0 * k, 7.6 * k), -60 * 16, 120 * 16)
        p.drawArc(QtCore.QRectF(7.6 * k, 1.2 * k, 5.2 * k, 10.4 * k), -58 * 16, 116 * 16)
        p.end()
        return pm

    def _vol_down(self) -> None:
        self._vol_drag = True

    def _vol_move(self, v: int) -> None:
        self.vol_pct.setText("%d%%" % int(v))
        if self.player is not None:
            self.player.set_volume(int(v) / 100.0)

    def _vol_up(self) -> None:
        self._vol_drag = False
        if self.player is not None:
            self.player.set_volume(self.vol.value() / 100.0)

    def wheelEvent(self, ev) -> None:  # noqa: N802
        # 展开态：在音量那一行滚一下就能调，不用非得去抠滑块
        if self._open and self.big.geometry().contains(
            QtCore.QPoint(int(ev.position().x()), int(ev.position().y()))
        ):
            d = 3 if ev.angleDelta().y() > 0 else -3
            v = max(0, min(100, self.vol.value() + d))
            self.vol.setValue(v)
            self._vol_move(v)
            ev.accept()
            return
        super().wheelEvent(ev)

    # ---------------- 拖进度 ----------------
    def _seek_down(self) -> None:
        self._drag = True

    def _seek_move(self, v: int) -> None:
        if self._dur > 0:
            self.time_big.setText(
                "%s / %s" % (_mmss(self._dur * v / 1000.0 / 1000.0), _mmss(self._dur / 1000.0))
            )

    def _seek_up(self) -> None:
        self._drag = False
        if self._dur > 0 and self.player is not None:
            self.player.seek(int(self._dur * self.seek.value() / 1000.0))

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        """点空白（封面 / 歌名 / 波形那一片）才展开收起。按钮和进度条是各自的事件目标，不受影响。"""
        if obj is getattr(self, "small", None) or obj is getattr(self, "big", None):
            if ev.type() == QtCore.QEvent.Type.MouseButtonPress:
                if ev.button() == Qt.LeftButton:
                    self._toggle_open()
                    return True
        return super().eventFilter(obj, ev)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._toggle_open()
            return
        super().mousePressEvent(event)

    # ---------------- 控制 ----------------
    def _prev(self) -> None:
        if self.player is not None and self.player.queue:
            self.player.prev()

    def _toggle(self) -> None:
        if self.player is None:
            return
        if not self.player.queue:
            self.win.toast("电脑上还没选歌，先去音乐页点一首")
            return
        self.player.toggle()

    def _next(self) -> None:
        if self.player is not None and self.player.queue:
            self.player.next()

    # ---------------- 位置 / 刷新 ----------------
    def place(self) -> None:
        ww = self.win.width()
        x = (ww - self.width()) // 2
        # 右边那排图标 + 分辨率框 + 窗口按钮大约占 330，别压上去
        limit = ww - 330 - self.width()
        if x > max(12, limit):
            x = max(12, limit)
        if self._open:
            # 原地往下长高：顶端不动，只往下展开，别跳到别处
            self.move(max(12, x), 14)
            return
        # 和右上角那排图标（音频 / 设置 / 皮肤）保持同一水平线
        y = 6
        btn = getattr(self.win, "set_btn", None)
        if btn is not None and btn.isVisible():
            cy = btn.mapTo(self.win, QtCore.QPoint(0, 0)).y() + btn.height() // 2
            y = max(4, cy - self.height() // 2)
        self.move(max(12, x), y)

    def _hide(self) -> None:
        if self._open:
            self._open = False
            self._apply_size()
        self.hide()

    def _set_cover(self, pm) -> None:
        if pm is None:
            return
        small = pm.scaled(22, 22, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.cover.setPixmap(small)
        self.cover_big.setPixmap(_round_pixmap(pm, 12))

    def refresh(self) -> None:
        p = self.player
        if p is None:
            self.hide()
            return
        st = p.state()
        t = st["track"] or {}
        if not t.get("name"):
            self._hide()
            return
        stack = getattr(self.win, "stack", None)
        if stack is not None and stack.currentWidget() is getattr(self.win, "music_page", None):
            self._hide()
            return
        name = t.get("name") or ""
        art = t.get("artist") or ""
        playing = bool(st["playing"])
        self._dur = int(st["dur"] or 0)
        self.tit.setText(name)
        self.tit_big.setText(name)
        self.art_big.setText(art or "未知歌手")
        if not self._drag:
            self.time_big.setText(
                "%s / %s" % (_mmss(st["pos"] / 1000.0), _mmss(st["dur"] / 1000.0))
            )
            ratio = (st["pos"] / st["dur"]) if st["dur"] else 0.0
            ratio = max(0.0, min(1.0, ratio))
            self.seek.blockSignals(True)
            self.seek.setValue(int(ratio * 1000))
            self.seek.blockSignals(False)
        vol = float(st.get("volume", getattr(p, "volume", 0.7)) or 0.0)
        if not self._vol_drag:
            self.vol.blockSignals(True)
            self.vol.setValue(int(round(max(0.0, min(1.0, vol)) * 100)))
            self.vol.blockSignals(False)
            self.vol_pct.setText("%d%%" % int(round(max(0.0, min(1.0, vol)) * 100)))
        self.bar.set_playing(playing)
        self.btn_play.setIcon(self._icons["pause" if playing else "play"])
        self.btn_play_big.setIcon(self._icons["pause_big" if playing else "play_big"])
        cov = t.get("cover") or ""
        if cov != self._cov_url:
            self._cov_url = cov
            if cov:
                load_cover(cov, 54, self._set_cover)
            else:
                self.cover.setPixmap(_note_icon(11))
                self.cover_big.setPixmap(_note_icon(20))
        self.place()
        if not self.isVisible():
            self.show()
        self.raise_()


_PAGE_QSS = (
    "QFrame#Card{background:rgba(10,14,22,.74);border:1px solid rgba(255,255,255,.10);border-radius:12px;}"
    "QLabel#Hint{color:#cfd8e4;}"
    "QLineEdit{background:rgba(10,14,22,.70);border:1px solid rgba(255,255,255,.16);"
    "border-radius:8px;padding:4px 9px;}"
    "QTableWidget{background:rgba(10,14,22,.70);}"
    "QFrame#Pill{background:rgba(10,14,22,.66);border:1px solid rgba(255,255,255,.10);border-radius:13px;}"
    "QFrame#GameCard{background:rgba(10,14,22,.74);border:1px solid rgba(255,255,255,.10);border-radius:10px;}"
    "QFrame#GameCard:hover{border:1px solid rgba(32,255,224,.55);}"
)


class _CoverLabel(QtWidgets.QLabel):
    """封面图：按控件尺寸铺满裁切（cover），窗口缩放时自动重算。"""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._src = None
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)

    def set_cover(self, pm: QtGui.QPixmap) -> None:
        self._src = pm
        self._apply()

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._apply()

    def _apply(self) -> None:
        pm = self._src
        if pm is None or pm.isNull():
            return
        w, h = self.width(), self.height()
        if w <= 0 or h <= 0:
            return
        sc = pm.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = max(0, (sc.width() - w) // 2)
        y = max(0, (sc.height() - h) // 2)
        self.setPixmap(sc.copy(x, y, w, h))


class _NetJob(QtCore.QRunnable):
    """后台拉一段 bytes；QPixmap 只能回主线程再建。"""

    def __init__(self, sig, url: str):
        super().__init__()
        self.sig = sig
        self.url = url

    def run(self) -> None:
        data = b""
        try:
            req = urllib.request.Request(
                self.url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                  "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
                    "Accept": "image/avif,image/webp,image/*,*/*;q=0.8",
                },
            )
            data = urllib.request.urlopen(req, timeout=15).read()
        except Exception:  # noqa: BLE001
            data = b""
        try:
            self.sig.done.emit(self.url, data)
        except RuntimeError:
            pass


class _ImgBus(QtCore.QObject):
    done = Signal(str, object)


class _FetchBus(QtCore.QObject):
    done = Signal(dict)


class _FetchJob(QtCore.QRunnable):
    """跑 Epic 那个接口，网络慢不卡界面。"""

    def __init__(self, bus: "_FetchBus", fn):
        super().__init__()
        self.bus = bus
        self.fn = fn

    def run(self) -> None:
        try:
            res = self.fn()
        except Exception as exc:  # noqa: BLE001
            res = {"now": [], "soon": [], "error": f"拉列表出错：{exc}"}
        try:
            self.bus.done.emit(res)
        except RuntimeError:
            pass


def _ago(ts: int) -> str:
    """LastPlayed 的秒数换成"多久以前"。"""
    if not ts:
        return "没记录"
    secs = max(0, int(time.time()) - int(ts))
    if secs < 3600:
        return f"{max(1, secs // 60)} 分钟前"
    if secs < 86400:
        return f"{secs // 3600} 小时前"
    days = secs // 86400
    if days < 30:
        return f"{days} 天前"
    return time.strftime("%Y-%m-%d", time.localtime(ts))


class _NameBus(QtCore.QObject):
    done = Signal(str, str)


class _NameJob(QtCore.QRunnable):
    """后台问一次商店公开接口，名字回来再填到卡片上。"""

    def __init__(self, bus: "_NameBus", appid: str):
        super().__init__()
        self.bus = bus
        self.appid = appid

    def run(self) -> None:
        try:
            name = steamnames.fetch_name(self.appid)
        except Exception:  # noqa: BLE001
            name = ""
        try:
            self.bus.done.emit(self.appid, name)
        except RuntimeError:
            pass


def _dur(minutes: int) -> str:
    """分钟换成人话。"""
    m = int(minutes or 0)
    if m <= 0:
        return "没玩过"
    h, mm = divmod(m, 60)
    if not h:
        return f"{mm} 分钟"
    return f"{h} 小时" if not mm else f"{h} 小时 {mm} 分"


class _GameCard(QtWidgets.QFrame):
    """一张游戏卡：封面、名字、AppID 与体积、时长与最近、启动与商店。"""

    COVER_H = 84

    def __init__(self, page, item: dict):
        super().__init__()
        self.page = page
        self.item = item
        self._full = ""
        self.setObjectName("GameCard")
        self.setFixedHeight(188)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Fixed)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

        v = QtWidgets.QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        self.cover = _CoverLabel()
        self.cover.setFixedHeight(self.COVER_H)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet("background:#0d1620;color:#54697d;font-size:20px;font-weight:700;")
        v.addWidget(self.cover)

        pad = QtWidgets.QVBoxLayout()
        pad.setContentsMargins(9, 6, 9, 8)
        pad.setSpacing(2)
        v.addLayout(pad)

        self.name = QtWidgets.QLabel("—")
        self.name.setStyleSheet(
            "font-size:12.5px;font-weight:700;color:#eaf4ff;background:transparent;"
        )
        self.name.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        pad.addWidget(self.name)

        self.meta = QtWidgets.QLabel("")
        self.meta.setStyleSheet("font-size:10.5px;color:#9fb0c4;background:transparent;")
        pad.addWidget(self.meta)

        self.meta2 = QtWidgets.QLabel("")
        self.meta2.setStyleSheet("font-size:10.5px;color:#8ea1b6;background:transparent;")
        pad.addWidget(self.meta2)

        row = QtWidgets.QHBoxLayout()
        row.setSpacing(5)
        pad.addLayout(row)

        if item.get("installed"):
            b = QtWidgets.QPushButton("启动")
            b.setObjectName("Mini")
            b.setFixedHeight(24)
            b.setStyleSheet("font-size:11px;")
            b.clicked.connect(lambda _=False: self.page._launch_item(self.item))
            row.addWidget(b, 1)

        b2 = QtWidgets.QPushButton("商店" if item.get("installed") else "查看商店")
        b2.setObjectName("Ghost")
        b2.setFixedHeight(24)
        b2.setStyleSheet("font-size:11px;")
        b2.clicked.connect(lambda _=False: self.page._open_store(self.item))
        row.addWidget(b2, 1)

        self.refresh()

    def refresh(self) -> None:
        it = self.item
        self.set_name(str(it.get("name") or f"AppID {it['appid']}"))
        if it.get("installed"):
            self.meta.setText(f"AppID {it['appid']} · {steamlib.human(it.get('size') or 0)}")
            self.meta2.setText(f"{_dur(it.get('minutes'))} · {_ago(int(it.get('last') or 0))}")
        else:
            self.meta.setText(f"AppID {it['appid']} · 未安装")
            self.meta2.setText(_dur(it.get("minutes")))

    def set_name(self, name: str) -> None:
        # 只改显示，别把「AppID 123」这种占位写回数据，否则补名字那步会以为已经有了
        self._full = name or ""
        self._apply_name()

    def _apply_name(self) -> None:
        if not hasattr(self, "name"):
            return
        w = max(60, self.width() - 20)
        self.name.setText(self.name.fontMetrics().elidedText(self._full or "—", Qt.ElideRight, w))
        self.name.setToolTip(self._full)

    def resizeEvent(self, e):  # noqa: N802
        super().resizeEvent(e)
        self._apply_name()

    def load_cover(self) -> None:
        path = str(self.item.get("cover_local") or "")
        if path:
            pm = QtGui.QPixmap(path)
            if not pm.isNull():
                self.cover.set_cover(pm)
                return
        self.cover.setText(str((self._full or self.item.get("appid") or "#")[:1]) or "#")
        self.page._want_cover(str(self.item["appid"]))

    def _menu(self, pos) -> None:
        it = self.item
        m = QtWidgets.QMenu(self)
        if it.get("installed"):
            act = m.addAction("启动游戏")
            act.triggered.connect(lambda _=False: self.page._launch_item(it))
        act = m.addAction("打开 Steam 商店页")
        act.triggered.connect(lambda _=False: self.page._open_store(it))
        if it.get("installed") and it.get("library"):
            act = m.addAction("打开安装目录")
            act.triggered.connect(lambda _=False: self.page._open_dir(it))
        act = m.addAction("复制 AppID")
        act.triggered.connect(lambda _=False: QtWidgets.QApplication.clipboard().setText(it["appid"]))
        m.exec(self.mapToGlobal(pos))


class SteamPage(QtWidgets.QWidget):
    """Steam 库：封面卡片墙，能装的直接启动，没装的直接去商店。"""

    COLS = 4

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("Root")
        self.setStyleSheet(_PAGE_QSS)
        self._snap = {}
        self._acc = {}
        self._items = []
        self._cards = {}
        self._cover_cache = {}
        self._img_wait = {}
        self._pending = set()
        self._kw = ""
        self._names = steamnames.load()
        self._name_dirty = False

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 12)
        lay.setSpacing(9)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(8)
        title = QtWidgets.QLabel("Steam 库")
        title.setStyleSheet("font-size:19px;font-weight:700;color:#f0f4fa;")
        head.addWidget(title)
        head.addSpacing(6)
        self.sum_lbl = QtWidgets.QLabel("读本地库文件和登录记录，不联网、不碰游戏")
        self.sum_lbl.setObjectName("Hint")
        head.addWidget(self.sum_lbl)
        head.addStretch(1)

        btn_open = QtWidgets.QPushButton("打开 Steam")
        btn_open.setObjectName("Mini")
        btn_open.setToolTip("叫出 Steam 客户端的库页面")
        btn_open.clicked.connect(
            lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl("steam://open/games"))
        )
        head.addWidget(btn_open)

        btn_ref = QtWidgets.QPushButton("重新扫描")
        btn_ref.setObjectName("Mini")
        btn_ref.setToolTip("新装了游戏就读一遍，不用重启")
        btn_ref.clicked.connect(self.reload)
        head.addWidget(btn_ref)
        lay.addLayout(head)

        # 那排胶囊：当前账号 / 库存 / 已装 / 未装 / 总时长
        pill_row = QtWidgets.QHBoxLayout()
        pill_row.setSpacing(7)
        self.pill_acct = self._pill(pill_row, "当前账号", avatar=True)
        self.pill_pool = self._pill(pill_row, "库存")
        self.pill_inst = self._pill(pill_row, "已安装")
        self.pill_not = self._pill(pill_row, "未安装")
        self.pill_time = self._pill(pill_row, "总游玩时长")
        lay.addLayout(pill_row)

        # 库目录：一行文字，不留大卡占地方
        self.lib_row = QtWidgets.QHBoxLayout()
        self.lib_row.setSpacing(7)
        lay.addLayout(self.lib_row)

        bar = QtWidgets.QHBoxLayout()
        bar.setSpacing(8)
        self.search = QtWidgets.QLineEdit()
        self.search.setPlaceholderText("搜游戏名 / AppID")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_search)
        bar.addWidget(self.search, 1)
        self.only_inst = QtWidgets.QCheckBox("只看已装")
        self.only_inst.toggled.connect(lambda _v: self._fill_wall())
        bar.addWidget(self.only_inst)
        self.count_lbl = QtWidgets.QLabel("")
        self.count_lbl.setObjectName("Hint")
        bar.addWidget(self.count_lbl)
        lay.addLayout(bar)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self.scroll.viewport().setAutoFillBackground(False)
        self.wall = QtWidgets.QWidget()
        self.wall.setObjectName("Wall")
        self.wall.setStyleSheet("background:transparent;")
        self.wall_lay = QtWidgets.QVBoxLayout(self.wall)
        self.wall_lay.setContentsMargins(0, 0, 4, 4)
        self.wall_lay.setSpacing(0)
        self.grid = QtWidgets.QGridLayout()
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(8)
        for c in range(self.COLS):
            self.grid.setColumnStretch(c, 1)
        self.wall_lay.addLayout(self.grid)
        self.wall_lay.addStretch(1)
        self.scroll.setWidget(self.wall)
        lay.addWidget(self.scroll, 1)

        tip = QtWidgets.QLabel(
            "卡片点「启动」直接进游戏；没装的点「查看商店」。账号和时长来自本机 Steam 的登录记录。"
        )
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(260)
        self._search_timer.timeout.connect(self._fill_wall)

        self._img_bus = _ImgBus(self)
        self._img_bus.done.connect(self._on_img)
        self._name_bus = _NameBus(self)
        self._name_bus.done.connect(self._on_name)
        self._cis = QtCore.QThreadPool(self)
        self._cis.setMaxThreadCount(4)
        self._ns = QtCore.QThreadPool(self)
        self._ns.setMaxThreadCount(3)

        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setInterval(4000)
        self._save_timer.timeout.connect(self._flush_names)
        self._save_timer.start()

        self.reload()

    # ---- 骨架 -------------------------------------------------------
    def _pill(self, row, title: str, avatar: bool = False) -> QtWidgets.QLabel:
        f = QtWidgets.QFrame()
        f.setObjectName("Pill")
        h = QtWidgets.QHBoxLayout(f)
        h.setContentsMargins(11, 4, 12, 4)
        h.setSpacing(6)

        if avatar:
            self.pill_avatar = QtWidgets.QLabel(" ")
            self.pill_avatar.setFixedSize(18, 18)
            self.pill_avatar.setAlignment(Qt.AlignCenter)
            self.pill_avatar.setStyleSheet(
                "border-radius:9px;background:#2f9bd8;color:#fff;font-size:10px;font-weight:700;"
            )
            h.addWidget(self.pill_avatar)

        t = QtWidgets.QLabel(title)
        t.setStyleSheet("font-size:11px;color:#9aabc0;background:transparent;")
        h.addWidget(t)
        v = QtWidgets.QLabel("—")
        v.setStyleSheet("font-size:13px;font-weight:700;color:#eaf4ff;background:transparent;")
        h.addWidget(v)
        row.addWidget(f)
        return v

    def _lib_pill(self, path: str, games: int, size: int, free: int, total: int) -> QtWidgets.QFrame:
        f = QtWidgets.QFrame()
        f.setObjectName("Pill")
        h = QtWidgets.QHBoxLayout(f)
        h.setContentsMargins(11, 4, 12, 4)
        h.setSpacing(7)
        p = QtWidgets.QLabel(path)
        p.setStyleSheet("font-size:11.5px;font-weight:600;color:#dbe8f6;background:transparent;")
        h.addWidget(p)
        s = QtWidgets.QLabel(
            f"{games} 个 · {steamlib.human(size)} / {steamlib.human(total)} · 剩 {steamlib.human(free)}"
        )
        s.setStyleSheet("font-size:11px;color:#93a6ba;background:transparent;")
        h.addWidget(s)
        h.addStretch(1)
        return f

    # ---- 数据 -------------------------------------------------------
    def reload(self) -> None:
        snap = steamlib.snapshot()
        try:
            acc = steamaccount.snapshot()
        except Exception as exc:  # noqa: BLE001
            log.warning("读 Steam 账号失败：%s", exc)
            acc = {}
        self._snap = snap
        self._acc = acc

        if snap.get("error"):
            self.sum_lbl.setText(snap["error"])
        else:
            self.sum_lbl.setText(f"Steam：{snap.get('steam') or '—'}")

        cur = (acc or {}).get("current") or {}
        if cur:
            name = str(cur.get("persona") or cur.get("account") or "—")
            self.pill_acct.setText(name)
            self.pill_avatar.setText(name[:1])
            self.sum_lbl.setToolTip(f"{cur.get('account') or ''} · {cur.get('steamid64') or ''}")
        else:
            self.pill_acct.setText("没登录记录")
            self.pill_avatar.setText("?")
            self.sum_lbl.setToolTip("本机 Steam 目录里没有 loginusers.vdf")

        # 库目录
        while self.lib_row.count():
            it = self.lib_row.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        for lib in snap.get("libraries") or []:
            self.lib_row.addWidget(
                self._lib_pill(
                    str(lib["path"]), int(lib["games"]), int(lib["size"]),
                    int(lib.get("free") or 0), int(lib.get("total") or 0),
                ),
                1,
            )

        self._build_items()
        self._fill_wall()
        self._fetch_names()

    def _build_items(self) -> None:
        snap = self._snap or {}
        acc = self._acc or {}
        games = {str(g["appid"]): g for g in (snap.get("games") or [])}
        notes = dict(((acc.get("stats") or {}).get("items")) or {})
        for aid in games:
            notes.setdefault(aid, {"playtime": 0, "last": 0})

        root = steamlib.steam_dir()
        items = []
        for aid, note in notes.items():
            g = games.get(aid)
            if g:
                name = str(g["name"] or "")
            else:
                name = str(self._names.get(aid) or "")
                if name == steamnames.NO_NAME:
                    name = ""
            items.append(
                {
                    "appid": aid,
                    "name": name,
                    "installed": bool(g and g["installed"]),
                    "size": int(g["size"]) if g else 0,
                    "library": str(g["library"]) if g else "",
                    "minutes": int(note.get("playtime") or 0),
                    "last": int(note.get("last") or 0),
                    "cover_local": steamlib.local_cover(root, aid),
                }
            )
        items.sort(
            key=lambda x: (-int(x["last"] or 0), -int(x["installed"]), str(x["name"]).lower())
        )
        self._items = items

        inst = sum(1 for x in items if x["installed"])
        self.pill_pool.setText(str(len(items)))
        self.pill_inst.setText(str(inst))
        self.pill_not.setText(str(len(items) - inst))
        mins = int((acc.get("stats") or {}).get("minutes") or 0)
        h, m = divmod(mins, 60)
        self.pill_time.setText(f"{h} 小时" if not m else f"{h} 小时 {m} 分")

    def _visible(self) -> list:
        only = self.only_inst.isChecked()
        kw = self._kw.strip().lower()
        out = []
        for it in self._items:
            if only and not it["installed"]:
                continue
            if kw and kw not in str(it["name"]).lower() and kw not in str(it["appid"]):
                continue
            out.append(it)
        return out

    def _on_search(self, text: str) -> None:
        self._kw = text or ""
        self._search_timer.start()

    def _fill_wall(self) -> None:
        while self.grid.count():
            it = self.grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._cards = {}

        shown = self._visible()
        inst = sum(1 for x in shown if x["installed"])
        self.count_lbl.setText(f"{len(shown)} 个 · 已装 {inst}")
        for i, item in enumerate(shown):
            card = _GameCard(self, item)
            self.grid.addWidget(card, i // self.COLS, i % self.COLS)
            self._cards[str(item["appid"])] = card
            card.load_cover()
        if not shown:
            hint = QtWidgets.QLabel("没有符合条件的游戏")
            hint.setObjectName("Hint")
            self.grid.addWidget(hint, 0, 0)
        self.grid.invalidate()
        bar = self.scroll.verticalScrollBar()
        if bar is not None:
            bar.setValue(0)

    # ---- 封面 -------------------------------------------------------
    def _want_cover(self, appid: str) -> None:
        pm = self._cover_cache.get(appid)
        if pm is not None:
            card = self._cards.get(appid)
            if card is not None:
                card.cover.set_cover(pm)
            return
        if appid in self._pending:
            return
        self._pending.add(appid)
        url = steamlib.cover_cdn(appid)
        self._img_wait[url] = appid
        self._cis.start(_NetJob(self._img_bus, url))

    def _on_img(self, url: str, data) -> None:
        appid = self._img_wait.pop(url, "")
        self._pending.discard(appid)
        if not appid or not data:
            return
        pm = QtGui.QPixmap()
        if not pm.loadFromData(data):
            return
        self._cover_cache[appid] = pm
        card = self._cards.get(appid)
        if card is not None:
            card.cover.set_cover(pm)

    # ---- 名字 -------------------------------------------------------
    def _fetch_names(self) -> None:
        todo = [
            str(it["appid"]) for it in self._items
            if not it["name"] and str(it["appid"]) not in self._names
        ]
        for aid in todo[:80]:
            self._ns.start(_NameJob(self._name_bus, aid))

    def _on_name(self, appid: str, name: str) -> None:
        if not name:
            return
        self._names[appid] = name
        self._name_dirty = True
        for it in self._items:
            if str(it["appid"]) == appid and not it["name"]:
                if name != steamnames.NO_NAME:
                    it["name"] = name
                break
        card = self._cards.get(appid)
        if card is not None:
            card.refresh()

    def _flush_names(self) -> None:
        if not self._name_dirty:
            return
        self._name_dirty = False
        steamnames.save(self._names)

    # ---- 动作 -------------------------------------------------------
    def _open_store(self, item: dict) -> None:
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl(steamlib.STEAM_APP % str(item.get("appid") or ""))
        )

    def _open_dir(self, item: dict) -> None:
        lib = str(item.get("library") or "")
        if not lib:
            return
        p = Path(lib) / "steamapps" / "common"
        if p.is_dir():
            QtGui.QDesktopServices.openUrl(QtCore.QUrl("file:///" + str(p).replace("\\", "/")))

    def _launch_item(self, item: dict) -> None:
        if not item.get("installed"):
            self._open_store(item)
            return
        QtGui.QDesktopServices.openUrl(
            QtCore.QUrl(steamlib.RUN_PREFIX % str(item.get("appid") or ""))
        )


class EpicPage(QtWidgets.QWidget):
    """Epic 喜加一：读官方公开的免费促销，点按钮跳商店，代领不做。"""

    HERO_H = 208

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setObjectName("Root")
        self.setStyleSheet(_PAGE_QSS)
        self._data = {}
        self._imgs = {}
        self._bus = _ImgBus(self)
        self._bus.done.connect(self._img_ready)
        self._fbus = _FetchBus(self)
        self._fbus.done.connect(self._on_data)
        self._pool = QtCore.QThreadPool(self)
        self._pool.setMaxThreadCount(2)

        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(18, 14, 18, 12)
        lay.setSpacing(10)

        head = QtWidgets.QHBoxLayout()
        head.setSpacing(8)
        title = QtWidgets.QLabel("Epic 喜加一")
        title.setStyleSheet("font-size:19px;font-weight:700;color:#f0f4fa;")
        head.addWidget(title)
        head.addSpacing(6)
        self.sum_lbl = QtWidgets.QLabel("正在拉这一周的免费列表…")
        self.sum_lbl.setObjectName("Hint")
        head.addWidget(self.sum_lbl)
        head.addStretch(1)

        btn_store = QtWidgets.QPushButton("打开商店")
        btn_store.setObjectName("Mini")
        btn_store.clicked.connect(
            lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl("https://store.epicgames.com/zh-CN/free-games"))
        )
        head.addWidget(btn_store)

        btn_ref = QtWidgets.QPushButton("刷新")
        btn_ref.setObjectName("Mini")
        btn_ref.clicked.connect(self.reload)
        head.addWidget(btn_ref)
        lay.addLayout(head)

        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        body = QtWidgets.QWidget()
        body.setObjectName("Root")
        self.body_lay = QtWidgets.QVBoxLayout(body)
        self.body_lay.setContentsMargins(0, 0, 0, 0)
        self.body_lay.setSpacing(10)
        self.scroll.setWidget(body)
        lay.addWidget(self.scroll, 1)

        tip = QtWidgets.QLabel(
            "列表来自 Epic 官方公开的免费促销接口，点「立即领取」会用默认浏览器打开商店页；"
            "本页不登录、不碰账号，代领不支持。"
        )
        tip.setObjectName("Hint")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        self.reload()

    # ---- 数据 -------------------------------------------------------
    def reload(self) -> None:
        self.sum_lbl.setText("正在拉这一周的免费列表…")
        self._pool.start(_FetchJob(self._fbus, epicfree.fetch))

    def _on_data(self, data: dict) -> None:
        self._data = data or {}
        if data.get("error"):
            self.sum_lbl.setText(data["error"])
        now = len(data.get("now") or [])
        soon = len(data.get("soon") or [])
        self.sum_lbl.setText(f"这一周免费 {now} 款 · 即将免费 {soon} 款")
        self._render()

    # ---- 渲染 -------------------------------------------------------
    def _clear(self) -> None:
        while self.body_lay.count():
            it = self.body_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()

    def _hero(self, item: dict) -> QtWidgets.QFrame:
        f = QtWidgets.QFrame()
        f.setObjectName("Card")
        outer = QtWidgets.QVBoxLayout(f)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        img = _CoverLabel("封面加载中…")
        img.setAlignment(Qt.AlignCenter)
        img.setFixedHeight(self.HERO_H)
        img.setStyleSheet("background:#101a24;color:#6f8399;border-top-left-radius:10px;"
                          "border-top-right-radius:10px;")
        outer.addWidget(img)

        pad = QtWidgets.QVBoxLayout()
        pad.setContentsMargins(16, 10, 16, 14)
        pad.setSpacing(6)

        row = QtWidgets.QHBoxLayout()
        t = QtWidgets.QLabel(item["title"])
        t.setStyleSheet("font-size:17px;font-weight:700;color:#f0f4fa;background:transparent;")
        row.addWidget(t)
        row.addStretch(1)
        if item.get("end_local"):
            e = QtWidgets.QLabel(f"截止 {item['end_local']}")
            e.setStyleSheet("color:#ffb454;background:transparent;font-size:12px;")
            row.addWidget(e)
        pad.addLayout(row)

        if item["desc"]:
            d = QtWidgets.QLabel(item["desc"])
            d.setWordWrap(True)
            d.setObjectName("Hint")
            pad.addWidget(d)

        brow = QtWidgets.QHBoxLayout()
        if item.get("price") and item["price"] not in ("0", "¥0.00"):
            pr = QtWidgets.QLabel(f"原价 {item['price']}")
            pr.setObjectName("Hint")
            brow.addWidget(pr)
        brow.addStretch(1)
        b = QtWidgets.QPushButton("立即领取")
        b.setObjectName("Native")
        b.setMinimumHeight(32)
        b.clicked.connect(lambda _=False, u=item.get("url"): QtGui.QDesktopServices.openUrl(QtCore.QUrl(u)))
        brow.addWidget(b)
        pad.addLayout(brow)
        outer.addLayout(pad)

        if item.get("image"):
            self._imgs[item["image"]] = ("hero", img)
            self._pool.start(_NetJob(self._bus, item["image"]))
        return f

    def _row(self, item: dict, soon: bool) -> QtWidgets.QFrame:
        f = QtWidgets.QFrame()
        f.setObjectName("Card")
        h = QtWidgets.QHBoxLayout(f)
        h.setContentsMargins(14, 8, 14, 8)
        h.setSpacing(10)

        thumb = QtWidgets.QLabel()
        thumb.setFixedSize(96, 54)
        thumb.setScaledContents(True)
        thumb.setStyleSheet("background:#101a24;border-radius:6px;")
        h.addWidget(thumb)

        v = QtWidgets.QVBoxLayout()
        v.setSpacing(1)
        t = QtWidgets.QLabel(item["title"])
        t.setStyleSheet("font-size:13px;font-weight:600;color:#e8f4ff;background:transparent;")
        v.addWidget(t)
        when = f"开始 {item['start_local']}" if soon else f"截止 {item['end_local']}"
        price = item.get("price") or ""
        s = QtWidgets.QLabel(f"{when}｜" + (f"原价 {price}" if price else "免费"))
        s.setObjectName("Hint")
        v.addWidget(s)
        h.addLayout(v, 1)

        if not soon:
            b = QtWidgets.QPushButton("领取")
            b.setObjectName("Mini")
            b.clicked.connect(lambda _=False, u=item.get("url"): QtGui.QDesktopServices.openUrl(QtCore.QUrl(u)))
            h.addWidget(b)
        else:
            b = QtWidgets.QPushButton("看看")
            b.setObjectName("Mini")
            b.clicked.connect(lambda _=False, u=item.get("url"): QtGui.QDesktopServices.openUrl(QtCore.QUrl(u)))
            h.addWidget(b)

        if item.get("image"):
            self._imgs[item["image"]] = ("thumb", thumb)
            self._pool.start(_NetJob(self._bus, item["image"]))
        return f

    def _render(self) -> None:
        self._clear()
        self._imgs = {}
        data = self._data

        now_items = data.get("now") or []
        if now_items:
            self.body_lay.addWidget(self._hero(now_items[0]))
            for it in now_items[1:]:
                self.body_lay.addWidget(self._row(it, soon=False))
        else:
            empty = QtWidgets.QLabel("这一周没有正在免费的游戏，下面看即将免费的。")
            empty.setObjectName("Hint")
            self.body_lay.addWidget(empty)

        soon_items = data.get("soon") or []
        if soon_items:
            cap = QtWidgets.QLabel("即将免费")
            cap.setStyleSheet("font-size:13px;font-weight:600;color:#9fb3c8;margin-top:6px;")
            self.body_lay.addWidget(cap)
            for it in soon_items:
                self.body_lay.addWidget(self._row(it, soon=True))

        self.body_lay.addStretch(1)

    def _img_ready(self, url: str, data: bytes) -> None:
        slot = self._imgs.get(url)
        if not slot or not data:
            return
        _kind, label = slot
        pm = QtGui.QPixmap()
        if not pm.loadFromData(data):
            return
        try:
            label.isVisible()
        except RuntimeError:
            return
        if isinstance(label, _CoverLabel):
            label.set_cover(pm)
        else:
            label.setPixmap(pm.scaled(96, 54, QtCore.Qt.KeepAspectRatioByExpanding, QtCore.Qt.SmoothTransformation))

    def refresh(self) -> None:
        pass


class MusicPage(QtWidgets.QWidget):
    """音乐页：左边我的歌单，右边歌曲列表，底下一整条播放器。"""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.api = getattr(win, "music_api", None)
        self.qq = getattr(win, "qq_api", None)
        self.kg = getattr(win, "kg_api", None)
        self.apis = {"ny": self.api, "qq": self.qq, "kg": self.kg,
                     "kw": getattr(win, "kw_api", None)}
        self.platform = "ny"
        self.player = getattr(win, "player", None)
        self.tracks: list = []
        self.history: list = []
        self._rows = []
        self._dragging = False
        self._pl_cache = {}

        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(14, 2, 14, 8)
        root.setSpacing(8)

        # ---------- 顶行：搜索 + 登录 ----------
        top = QtWidgets.QHBoxLayout()
        top.setSpacing(8)
        self.q_search = QtWidgets.QLineEdit()
        self.q_search.setPlaceholderText("搜歌名、歌手，回车开始搜")
        self.q_search.setFixedHeight(30)
        self.q_search.setStyleSheet(
            "QLineEdit{background:rgba(10,14,22,.46);border:1px solid rgba(255,255,255,.10);"
            "border-radius:9px;padding:0px 11px;font-size:12.5px;color:#eef2f8;}"
            "QLineEdit:focus{border:1px solid rgba(32,255,224,.55);}"
        )
        self.q_search.returnPressed.connect(self.do_search)
        top.addWidget(self.q_search, 1)

        self.btn_search = QtWidgets.QPushButton("搜索")
        self.btn_search.setObjectName("Ghost")
        self.btn_search.setFixedSize(58, 30)
        self.btn_search.setCursor(Qt.PointingHandCursor)
        self.btn_search.clicked.connect(self.do_search)
        top.addWidget(self.btn_search)

        # 平台切换 + 登录：装进一块绿色的液态玻璃条里，和卡片保持同一套质感
        self.plat_card = QtWidgets.QFrame()
        self.plat_card.setObjectName("PlatBar")
        self.plat_card.setStyleSheet(
            "QFrame#PlatBar{background:qlineargradient(x1:0,y1:0,x2:0,y2:1,"
            "stop:0 rgba(86,255,218,.44),stop:0.45 rgba(24,158,126,.50),"
            "stop:1 rgba(8,62,52,.60));"
            "border:1px solid rgba(132,255,224,.62);border-radius:15px;}"
        )
        pc = QtWidgets.QHBoxLayout(self.plat_card)
        pc.setContentsMargins(5, 4, 5, 4)
        pc.setSpacing(3)

        self.plat_group = QtWidgets.QButtonGroup(self)
        self.plat_group.setExclusive(True)
        self._plat_btns = {}
        # 每个平台有自己的主色，选中时按平台上色：
        # 网易云红 / QQ音乐绿 / 酷狗蓝 / 酷我黄
        plat_checked = {
            "ny": ("255,74,74", "255,146,146", "#fff5f5"),
            "qq": ("49,194,124", "128,232,172", "#04241a"),
            "kg": ("48,150,255", "132,192,255", "#f3f9ff"),
            "kw": ("255,184,0", "255,214,118", "#2b1c00"),
        }
        for i, (src_name, label) in enumerate((("ny", "网易云"), ("qq", "QQ音乐"),
                                               ("kg", "酷狗"), ("kw", "酷我"))):
            rgb, edge, fg = plat_checked[src_name]
            b = QtWidgets.QPushButton(label)
            b.setObjectName("Ghost")
            b.setCheckable(True)
            b.setFixedHeight(30)
            b.setCursor(Qt.PointingHandCursor)
            b.setStyleSheet(
                "QPushButton{padding:0px 11px;font-size:12px;background:transparent;"
                "border:1px solid transparent;border-radius:9px;color:#e6fbf4;}"
                "QPushButton:hover{background:rgba(255,255,255,.14);}"
                f"QPushButton:checked{{background:rgba({rgb},.46);"
                f"border:1px solid rgba({edge},.80);color:{fg};"
                "font-weight:700;}"
            )
            b.clicked.connect(lambda _=False, s=src_name: self.switch_platform(s))
            self.plat_group.addButton(b, i)
            self._plat_btns[src_name] = b
            pc.addWidget(b)
        self._plat_btns["ny"].setChecked(True)

        self.btn_login = QtWidgets.QPushButton("登录网易云")
        self.btn_login.setObjectName("Ghost")
        self.btn_login.setFixedHeight(30)
        self.btn_login.setCursor(Qt.PointingHandCursor)
        self.btn_login.setStyleSheet(
            "QPushButton{padding:0px 12px;font-size:12px;border-radius:9px;"
            "background:rgba(30,244,200,.26);border:1px solid rgba(120,255,222,.58);"
            "color:#eafff9;}"
            "QPushButton:hover{background:rgba(40,255,210,.42);}"
        )
        self.btn_login.clicked.connect(self.open_login)
        sep = QtWidgets.QFrame()
        sep.setFixedWidth(1)
        sep.setStyleSheet("background:rgba(190,255,238,.30);border:none;")
        sep.setFixedHeight(22)
        pc.addWidget(sep)
        pc.addWidget(self.btn_login)
        top.addWidget(self.plat_card)

        # 桌面悬浮条开关：只管屏幕上那条独立小窗，和本窗口里的灵动岛无关
        self.chk_bar = QtWidgets.QPushButton("悬浮条")
        self.chk_bar.setCheckable(True)
        self.chk_bar.setFixedHeight(30)
        self.chk_bar.setCursor(Qt.PointingHandCursor)
        self.chk_bar.setToolTip(
            "屏幕边上那条四个按钮的小窗（不在本窗口里）。\n"
            "只在自己有歌时才出现；开着可以拖到屏幕边自动收起"
        )
        self.chk_bar.setChecked(bool(getattr(self.win.cfg, "bar_on", True)))
        self.chk_bar.setStyleSheet(
            "QPushButton{padding:0px 10px;font-size:12px;border-radius:9px;"
            "background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.14);"
            "color:#d8e6ef;}"
            "QPushButton:hover{background:rgba(255,255,255,.13);}"
            "QPushButton:checked{background:rgba(32,255,224,.26);"
            "border:1px solid rgba(120,255,222,.64);color:#eafff9;font-weight:700;}"
        )
        self.chk_bar.clicked.connect(self._on_bar)
        top.addWidget(self.chk_bar)
        root.addLayout(top)

        # ---------- 主体：左边歌单，右边列表 ----------
        body = QtWidgets.QHBoxLayout()
        body.setSpacing(8)

        left = QtWidgets.QFrame()
        left.setObjectName("Card")
        left.setFixedWidth(182)
        _glass_card(left)
        ll = QtWidgets.QVBoxLayout(left)
        ll.setContentsMargins(9, 9, 9, 9)
        ll.setSpacing(5)

        lbl1 = QtWidgets.QLabel("我的音乐")
        lbl1.setObjectName("Hint")
        lbl1.setStyleSheet("font-size:11px;font-weight:600;")
        ll.addWidget(lbl1)

        self.list_my = QtWidgets.QListWidget()
        self.list_my.setFixedHeight(93)
        self._style_list(self.list_my)
        self.list_my.itemClicked.connect(self._on_my_click)
        ll.addWidget(self.list_my)

        lbl2 = QtWidgets.QLabel("我的歌单")
        lbl2.setObjectName("Hint")
        lbl2.setStyleSheet("font-size:11px;font-weight:600;")
        ll.addWidget(lbl2)

        self.list_pl = QtWidgets.QListWidget()
        self._style_list(self.list_pl)
        self.list_pl.itemClicked.connect(self._on_pl_click)
        ll.addWidget(self.list_pl, 1)
        body.addWidget(left)

        right_card = QtWidgets.QFrame()
        right_card.setObjectName("Card")
        _glass_card(right_card)
        right = QtWidgets.QVBoxLayout(right_card)
        right.setContentsMargins(10, 9, 10, 9)
        right.setSpacing(6)
        self.lbl_title = QtWidgets.QLabel("搜一首歌，或者从左边挑个歌单")
        self.lbl_title.setStyleSheet("font-size:12px;font-weight:600;color:#dfe5ee;")
        right.addWidget(self.lbl_title)

        self.list = QtWidgets.QListWidget()
        self._style_list(self.list)
        self.list.itemClicked.connect(self._on_song_click)
        right.addWidget(self.list, 1)
        body.addWidget(right_card, 1)
        root.addLayout(body, 1)

        # ---------- 底部播放条 ----------
        bar = QtWidgets.QFrame()
        bar.setObjectName("Card")
        _glass_card(bar)
        bl = QtWidgets.QHBoxLayout(bar)
        bl.setContentsMargins(12, 8, 12, 8)
        bl.setSpacing(10)

        self.cover = QtWidgets.QLabel()
        self.cover.setFixedSize(52, 52)
        self.cover.setAlignment(Qt.AlignCenter)
        self.cover.setStyleSheet("border-radius:12px;background:rgba(255,255,255,.07);")
        self.cover.setPixmap(_note_icon(26))
        bl.addWidget(self.cover, 0, Qt.AlignVCenter)

        mid = QtWidgets.QVBoxLayout()
        mid.setSpacing(4)
        trow = QtWidgets.QHBoxLayout()
        trow.setSpacing(7)
        self.q_title = QtWidgets.QLabel("没在放歌")
        self.q_title.setStyleSheet("font-size:12.5px;font-weight:700;color:#eef2f8;")
        trow.addWidget(self.q_title)
        self.q_artist = QtWidgets.QLabel("")
        self.q_artist.setObjectName("Hint")
        trow.addWidget(self.q_artist)
        trow.addStretch(1)
        mid.addLayout(trow)

        grow = QtWidgets.QHBoxLayout()
        grow.setSpacing(8)
        self.slider = QtWidgets.QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setFixedHeight(14)
        self.slider.setStyleSheet(
            "QSlider::groove:horizontal{height:3px;border-radius:2px;"
            "background:rgba(255,255,255,.10)}"
            "QSlider::sub-page:horizontal{height:3px;border-radius:2px;"
            "background:qlineargradient(x1:0,y1:0,x2:1,y2:0,stop:0 #17c8a8,stop:1 #20ffe0)}"
            "QSlider::handle:horizontal{width:10px;margin:-4px 0;border-radius:5px;"
            "background:#20ffe0}"
            "QSlider::handle:horizontal:disabled{background:#454d5b}"
            "QSlider::sub-page:horizontal:disabled{background:rgba(255,255,255,.10)}"
        )
        self.slider.sliderPressed.connect(self._on_grab)
        self.slider.sliderReleased.connect(self._on_seek)
        grow.addWidget(self.slider, 1)
        self.q_time = QtWidgets.QLabel("— / —")
        self.q_time.setObjectName("Hint")
        self.q_time.setMinimumWidth(74)
        grow.addWidget(self.q_time)
        mid.addLayout(grow)
        bl.addLayout(mid, 1)

        bcol = QtWidgets.QHBoxLayout()
        bcol.setSpacing(6)
        self.btn_prev = QtWidgets.QPushButton()
        self.btn_play = QtWidgets.QPushButton()
        self.btn_next = QtWidgets.QPushButton()
        self._play_icons = {
            "play": QtGui.QIcon(_media_icon("play", 15)),
            "pause": QtGui.QIcon(_media_icon("pause", 15)),
        }
        for b, kind, tip in (
            (self.btn_prev, "prev", "上一首"),
            (self.btn_play, "play", "播放 / 暂停"),
            (self.btn_next, "next", "下一首"),
        ):
            b.setObjectName("Ghost")
            b.setFixedSize(36, 28)
            b.setIconSize(QtCore.QSize(15, 15))
            b.setIcon(QtGui.QIcon(_media_icon(kind, 15)))
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            b.setStyleSheet("padding:0px;")
        self.btn_prev.clicked.connect(self.win.music_prev)
        self.btn_play.clicked.connect(self.win.music_toggle)
        self.btn_next.clicked.connect(self.win.music_next)
        bcol.addWidget(self.btn_prev)
        bcol.addWidget(self.btn_play)
        bcol.addWidget(self.btn_next)
        bl.addLayout(bcol)

        self.vol = QtWidgets.QSlider(Qt.Horizontal)
        self.vol.setRange(0, 100)
        self.vol.setValue(int(70))
        self.vol.setFixedWidth(64)
        self.vol.setToolTip("音量")
        self.vol.valueChanged.connect(self._on_vol)
        bl.addWidget(self.vol, 0, Qt.AlignVCenter)
        root.addWidget(bar)

        self._load_history()
        self._refresh_my()
        self._refresh_login()
        if self.player is not None:
            self.player.changed.connect(self._on_change)
            self.player.track_changed.connect(self._on_track)
            self.player.failed.connect(lambda m: self.win.toast(m, False))
        lan = getattr(getattr(self.win, "tools_card", None), "lan", None)
        if lan is not None:
            try:
                lan.music_ask.connect(self._on_lan_cmd)
            except Exception:  # noqa: BLE001
                pass
        self._on_change()

    # ---------- 平台 ----------
    def cur(self):
        return self.apis.get(self.platform)

    def switch_platform(self, src_name: str) -> None:
        if src_name == self.platform:
            return
        self.platform = src_name
        btn = self._plat_btns.get(src_name)
        if btn is not None and not btn.isChecked():
            btn.setChecked(True)
        self._refresh_login()
        self._refresh_playlists()
        self._refresh_my()
        self._fill([], "搜一首歌试试")

    # ---------- 小工具 ----------
    @staticmethod
    def _style_list(lw: QtWidgets.QListWidget) -> None:
        lw.setStyleSheet(
            "QListWidget{background:transparent;border:none;outline:none;"
            " font-size:12px;}"
            "QListWidget::item{border-radius:8px;padding:2px 4px;}"
            "QListWidget::item:selected{background:rgba(32,255,224,.13);color:#eef2f8;}"
            "QListWidget::item:hover{background:rgba(255,255,255,.05);}"
        )
        lw.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollPerPixel)
        lw.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def _store_dir(self):
        return app_dir() / "音乐数据"

    # ---------- 历史 ----------
    def _load_history(self) -> None:
        try:
            p = self._store_dir() / "history.json"
            if p.exists():
                self.history = json.loads(p.read_text("utf-8"))[:60]
        except Exception:  # noqa: BLE001
            self.history = []

    def _save_history(self) -> None:
        try:
            d = self._store_dir()
            d.mkdir(parents=True, exist_ok=True)
            (d / "history.json").write_text(
                json.dumps(self.history[:60], ensure_ascii=False), "utf-8"
            )
        except Exception:  # noqa: BLE001
            pass

    def _push_history(self, track: dict) -> None:
        if not track or not track.get("id"):
            return
        self.history = [h for h in self.history if h.get("id") != track["id"]]
        self.history.insert(0, track)
        self.history = self.history[:60]
        self._save_history()
        self._refresh_my()

    def _refresh_my(self) -> None:
        self.list_my.clear()
        logged = bool(getattr(self.cur(), "logged", False)) if self.cur() else False
        d = QtWidgets.QListWidgetItem(
            "每日推荐" if logged else "每日推荐  (要登录)")
        d.setData(Qt.UserRole, "daily")
        self.list_my.addItem(d)
        it = QtWidgets.QListWidgetItem("播放历史  (%d)" % len(self.history))
        it.setData(Qt.UserRole, "history")
        self.list_my.addItem(it)
        it2 = QtWidgets.QListWidgetItem("猜你喜欢  (先搜一首)")
        it2.setFlags(Qt.NoItemFlags)
        self.list_my.addItem(it2)

    def _refresh_login(self) -> None:
        self.btn_login.setVisible(True)
        if self.platform == "kw":
            kw = (self.apis or {}).get("kw")
            if kw is not None and getattr(kw, "logged", False):
                self.btn_login.setText(kw.nick or "酷我已登录")
                self.btn_login.setToolTip("点一下可以退出登录")
            else:
                self.btn_login.setText("登录酷我")
                self.btn_login.setToolTip("贴 kw_token 之后，会员歌也能放")
            return
        if self.platform == "kg":
            self.btn_login.setEnabled(True)
            self.btn_login.setEnabled(True)
            if self.kg is not None and getattr(self.kg, "logged", False):
                self.btn_login.setText(self.kg.nick or "酷狗已登录")
                self.btn_login.setToolTip("点一下可以退出登录")
            else:
                self.btn_login.setText("登录酷狗")
                self.btn_login.setToolTip("贴 cookie 登录后，会员歌也能听")
            return
        self.btn_login.setEnabled(True)
        self.btn_login.setEnabled(True)
        if self.platform == "qq":
            if self.qq is not None and getattr(self.qq, "logged", False):
                self.btn_login.setText("QQ 已登录")
                self.btn_login.setToolTip("点一下可以退出登录")
            else:
                self.btn_login.setText("登录QQ音乐")
                self.btn_login.setToolTip("贴上浏览器的 cookie，VIP 歌也能听")
            return
        if self.api is not None and getattr(self.api, "logged", False):
            self.btn_login.setText(self.api.nick or "已登录")
            self.btn_login.setToolTip("点一下可以退出登录")
        else:
            self.btn_login.setText("登录网易云")
            self.btn_login.setToolTip("扫码登录后能读你自己的歌单")

    _PL_NAMES = {"ny": "网易云", "qq": "QQ音乐", "kg": "酷狗", "kw": "酷我"}

    def _pl_hint(self, text: str) -> None:
        self.list_pl.clear()
        it = QtWidgets.QListWidgetItem(text)
        it.setFlags(Qt.NoItemFlags)
        self.list_pl.addItem(it)

    def _refresh_playlists(self) -> None:
        api = self.cur()
        if api is None:
            self._pl_hint("这家接口没起来")
            return
        if not getattr(api, "logged", False):
            self._pl_hint("登录后显示你的歌单")
            return
        if not getattr(api, "can_playlists", True):
            self._pl_hint("%s 暂时读不了歌单，先用搜索听"
                          % self._PL_NAMES.get(self.platform, ""))
            return
        _bg(lambda: api.my_playlists(), self._on_playlists)

    def _on_playlists(self, res) -> None:
        self.list_pl.clear()
        api = self.cur()
        if not isinstance(res, list) or not res:
            why = str(getattr(api, "error", "") or "") if api is not None else ""
            it = QtWidgets.QListWidgetItem(
                ("没读到歌单：%s" % why[:36]) if why else "歌单是空的")
            it.setFlags(Qt.NoItemFlags)
            self.list_pl.addItem(it)
            self._add_import_row(api)
            return
        for p in res:
            self._pl_cache[str(p.get("id"))] = p
            it = QtWidgets.QListWidgetItem(
                "%s  ·  %s" % (p.get("name") or "未命名", p.get("count") or 0)
            )
            it.setData(Qt.UserRole, "pl:%s" % p.get("id"))
            self.list_pl.addItem(it)
        self._add_import_row(api)

    def _add_import_row(self, api) -> None:
        """歌单列表末尾挂一行「粘贴链接导入」，QQ/酷狗那种拿不到自动列表的靠它。"""
        if api is None or not hasattr(api, "add_local"):
            return
        it = QtWidgets.QListWidgetItem("＋ 粘贴歌单链接导入")
        it.setData(Qt.UserRole, "imp:%s" % self.platform)
        it.setToolTip("在 App 里点歌单「分享」复制链接，粘到这里就记住了")
        self.list_pl.addItem(it)

    def _import_playlist(self) -> None:
        api = self.cur()
        if api is None or not hasattr(api, "add_local"):
            return
        nm = self._PL_NAMES.get(self.platform, "")
        text, ok = QtWidgets.QInputDialog.getText(
            self, "导入%s歌单" % nm,
            "在%s里打开歌单，点分享复制链接，粘到这里：" % nm)
        if not ok or not (text or "").strip():
            return
        val = text.strip()

        def done(res):
            if not isinstance(res, dict) or res.get("_error"):
                self.win.toast("没导入成功：%s"
                               % str((res or {}).get("_error") or "链接不对")[:36], False)
                return
            self.win.toast("已导入「%s」" % res.get("name"), True)
            self._refresh_playlists()

        _bg(lambda: api.add_local(val), done)

    # ---------- 交互 ----------
    def _on_bar(self, checked: bool) -> None:
        self.win.set_music_bar(bool(checked))
        self.win.toast(
            "桌面悬浮条已打开：有歌时会在屏幕边上出现"
            if checked
            else "桌面悬浮条已关闭",
            True,
        )

    def do_search(self) -> None:
        kw = (self.q_search.text() or "").strip()
        if not kw:
            return
        api = self.cur()
        if api is None:
            self.win.toast("音乐接口没起来", False)
            return
        src_name = self.platform
        self.lbl_title.setText("搜索「%s」…" % kw)
        self._fill([], "搜索「%s」…" % kw)
        _bg(lambda: api.search(kw, 30), lambda r: self._on_search(r, kw, src_name))

    def _on_search(self, res, kw, src_name="ny") -> None:
        if isinstance(res, dict) and res.get("_error"):
            self.lbl_title.setText("搜索失败：%s" % res["_error"])
            return
        if not res:
            self.lbl_title.setText("「%s」没搜到东西" % kw)
            return
        for t in res:
            t["src"] = src_name
        self._fill(res, "搜索「%s」" % kw)

    def _on_my_click(self, item) -> None:
        kind = item.data(Qt.UserRole)
        if kind == "daily":
            self.load_daily()
            return
        if kind != "history":
            return
        if not self.history:
            self.lbl_title.setText("还没放过歌")
            self._fill([], "播放历史")
            return
        self._fill(self.history, "播放历史")

    # ---------- 每日推荐 ----------
    def load_daily(self) -> None:
        api = self.cur()
        if api is None:
            self.win.toast("这家接口没起来", False)
            return
        if not getattr(api, "logged", False):
            names = {"ny": "网易云", "qq": "QQ音乐", "kg": "酷狗", "kw": "酷我"}
            self.win.toast("每日推荐跟着账号走，先登录%s" % names.get(self.platform, ""), False)
            return
        self.lbl_title.setText("正在取每日推荐…")
        self._fill([], "每日推荐")

        def work():
            try:
                return api.recommend()
            except Exception as exc:  # noqa: BLE001
                return {"err": str(exc)}

        def done(res):
            if isinstance(res, dict) and res.get("err"):
                self.win.toast("每日推荐没拿到：%s" % str(res["err"])[:40], False)
                self.lbl_title.setText("每日推荐")
                return
            if not res:
                self.win.toast("这一家的每日推荐还没通，先用搜索听", False)
                self.lbl_title.setText("每日推荐")
                return
            for t in res:
                t.setdefault("src", self.platform)
            self._fill(res, "每日推荐")

        _bg(work, done)

    def _on_pl_click(self, item) -> None:
        key = item.data(Qt.UserRole)
        if key and str(key).startswith("imp:"):
            self._import_playlist()
            return
        if not key or not str(key).startswith("pl:"):
            return
        pid = str(key)[3:]
        name = (self._pl_cache.get(pid) or {}).get("name") or "歌单"
        self.lbl_title.setText("正在载入「%s」…" % name)
        api = self.cur()
        if api is None:
            return
        _bg(lambda: api.playlist_tracks(pid),
            lambda r: self._on_playlist_tracks(r, name))

    def _on_playlist_tracks(self, res, name) -> None:
        if not res:
            self.lbl_title.setText("「%s」载入失败" % name)
            return
        self._fill(res, name)

    def _fill(self, tracks: list, title: str) -> None:
        self.tracks = list(tracks or [])
        self.list.clear()
        self._rows = []
        self.lbl_title.setText(
            "%s · %d 首" % (title, len(self.tracks)) if self.tracks else title
        )
        for t in self.tracks:
            item = QtWidgets.QListWidgetItem()
            item.setSizeHint(QtCore.QSize(0, 46))
            self.list.addItem(item)
            row = _SongRow(t)
            self.list.setItemWidget(item, row)
            self._rows.append(row)
        for r in self._rows[:36]:
            r.load()
        if self.player is not None and self.player.index >= 0:
            try:
                self.list.setCurrentRow(self.player.index)
            except Exception:  # noqa: BLE001
                pass

    def _on_song_click(self, item) -> None:
        i = self.list.row(item)
        if not (0 <= i < len(self.tracks)):
            return
        if self.player is None:
            return
        t = self.tracks[i]
        if t.get("vip") and (t.get("src") == "qq"):
            self.win.toast("《%s》是 VIP 歌，登录 QQ 音乐后才能放" % (t.get("name") or ""), False)
            return
        if t.get("vip") and (t.get("src") == "kw"):
            self.win.toast("《%s》这首歌酷我要会员，换一首听听" % (t.get("name") or ""), False)
            return
        self.player.set_queue(self.tracks, i)

    def open_login(self) -> None:
        if self.platform == "kw":
            kw = (self.apis or {}).get("kw")
            if kw is None:
                self.win.toast("酷我接口没起来", False)
                return
            if getattr(kw, "logged", False):
                ans = QtWidgets.QMessageBox.question(
                    self, "退出登录", "要把酷我的登录信息清掉吗？"
                )
                if ans == QtWidgets.QMessageBox.StandardButton.Yes:
                    kw.logout()
                    self._refresh_login()
                    self.win.toast("已清掉酷我登录信息")
                return
            dlg = WebLoginDialog(kw, self, "kw")
            if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                self._refresh_login()
                self.win.toast("酷我已登录，会员歌可以试试了")
            return
        if self.platform == "kg":
            if self.kg is None:
                self.win.toast("酷狗接口没起来", False)
                return
            if getattr(self.kg, "logged", False):
                ans = QtWidgets.QMessageBox.question(
                    self, "退出登录", "要把酷狗的登录信息清掉吗？"
                )
                if ans == QtWidgets.QMessageBox.StandardButton.Yes:
                    self.kg.logout()
                    self._refresh_login()
                    self.win.toast("已清掉酷狗登录信息")
                return
            dlg = WebLoginDialog(self.kg, self, "kg")
            if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                self._refresh_login()
                self.win.toast("酷狗已登录，会员歌可以放了")
            return
        if self.platform == "qq":
            if self.qq is None:
                self.win.toast("QQ 接口没起来", False)
                return
            if getattr(self.qq, "logged", False):
                ans = QtWidgets.QMessageBox.question(
                    self, "退出登录", "要把 QQ 音乐的登录信息清掉吗？"
                )
                if ans == QtWidgets.QMessageBox.StandardButton.Yes:
                    self.qq.logout()
                    self._refresh_login()
                    self.win.toast("已清掉 QQ 登录信息")
                return
            dlg = WebLoginDialog(self.qq, self, "qq")
            if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                self._refresh_login()
                self.win.toast("QQ 音乐已登录，VIP 歌可以放了")
            return
        if self.api is None:
            self.win.toast("音乐接口没起来", False)
            return
        if getattr(self.api, "logged", False):
            ans = QtWidgets.QMessageBox.question(
                self, "退出登录",
                "现在登录的是「%s」。要退出吗？" % (self.api.nick or "已登录"),
            )
            if ans == QtWidgets.QMessageBox.StandardButton.Yes:
                _bg(lambda: self.api.logout(), self._on_logout)
            return
        dlg = LoginDialog(self.api, self)
        if dlg.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            _bg(lambda: self.api.refresh_status(), self._on_login_ok)

    def _on_login_ok(self, _res=None) -> None:
        self._refresh_login()
        self._refresh_playlists()
        self.win.toast("登录成功，歌单已载入")

    def _on_logout(self, _res=None) -> None:
        self._refresh_login()
        self._refresh_playlists()
        self.win.toast("已退出登录")

    # ---------- 播放同步 ----------
    def _on_track(self, track: dict) -> None:
        if not track:
            return
        self.q_title.setText(track.get("name") or "—")
        self.q_artist.setText(track.get("artist") or "")
        cover_url = track.get("cover") or ""
        if cover_url:
            load_cover(cover_url, 52, self._set_cover)
        else:
            self.cover.setPixmap(_note_icon(26))
        self._push_history(track)

    def _set_cover(self, pm) -> None:
        if pm is not None:
            self.cover.setPixmap(pm)

    def _on_change(self) -> None:
        if self.player is None:
            return
        st = self.player.state()
        pos = st["pos"] / 1000.0
        dur = st["dur"] / 1000.0
        if dur > 0:
            self.q_time.setText("%s / %s" % (_mmss(pos), _mmss(dur)))
            if not self._dragging:
                self.slider.setValue(int(1000 * min(1.0, pos / dur)))
        elif st["loading"]:
            self.q_time.setText("载入中…")
        else:
            self.q_time.setText("— / —")
        self.btn_play.setIcon(self._play_icons["pause" if st["playing"] else "play"])
        has = bool(st["track"])
        for b in (self.btn_prev, self.btn_play, self.btn_next):
            b.setEnabled(has)
        self.slider.setEnabled(has)
        lan = getattr(getattr(self.win, "tools_card", None), "lan", None)
        if lan is not None:
            t = st["track"] or {}
            try:
                lan.set_music({
                    "title": t.get("name") or "",
                    "artist": t.get("artist") or "",
                    "playing": bool(st["playing"]),
                    "pos": int(st["pos"] or 0),
                    "dur": int(st["dur"] or 0),
                    "cover": t.get("cover") or "",
                })
            except Exception:  # noqa: BLE001
                pass

    def _on_lan_cmd(self, cmd: str) -> None:
        """手机端点了上一首 / 播放暂停 / 下一首。"""
        p = self.player
        if p is None:
            return
        if cmd == "toggle":
            if not p.queue:
                self.win.toast("电脑上还没选歌，先在音乐页点一首")
                return
            p.toggle()
        elif cmd == "next":
            if not p.queue:
                self.win.toast("电脑上还没选歌，先在音乐页点一首")
                return
            p.next()
        elif cmd == "prev":
            if not p.queue:
                self.win.toast("电脑上还没选歌，先在音乐页点一首")
                return
            p.prev()
        self._on_change()

    def _on_grab(self) -> None:
        self._dragging = True

    def _on_seek(self) -> None:
        self._dragging = False
        if self.player is None:
            return
        dur = self.player.state()["dur"]
        if dur <= 0:
            return
        self.player.seek(int(dur * self.slider.value() / 1000.0))

    def _on_vol(self, v: int) -> None:
        if self.player is not None:
            self.player.set_volume(v / 100.0)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self.list_pl.count():
            self._refresh_playlists()
        self._refresh_login()
        if self.win.cfg is not None:
            pass


class ArtLayer(QtWidgets.QWidget):
    """整窗铺满的壁纸层。

    老老实实铺满整个矩形，圆角由窗口自己的 setMask 统一裁；
    壁纸要是自己再裁一次，四角就会露出下面的底色，反而像没铺满。
    不用 QLabel 是因为它的 1 位蒙版边缘是硬的，还会被分层窗口吃掉。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground, True)
        self._pm = None
        self._radius = 0.0

    # 接口跟 QLabel 对齐，外面照旧 setPixmap / clear / pixmap
    def setPixmap(self, pm) -> None:  # noqa: N802
        self._pm = pm
        if pm is not None and not pm.isNull():
            self.resize(pm.size())
        self.update()

    def pixmap(self):
        return self._pm

    def clear(self) -> None:
        self._pm = None
        self.update()

    def set_radius(self, radius) -> None:
        r = max(0.0, float(radius or 0))
        if abs(r - self._radius) > 0.1:
            self._radius = r
            self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if self._pm is None or self._pm.isNull():
            return
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        p.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, True)
        if self._radius > 0.5:
            path = QtGui.QPainterPath()
            path.addRoundedRect(
                QtCore.QRectF(0.0, 0.0, float(self.width()), float(self.height())),
                self._radius,
                self._radius,
            )
            p.setClipPath(path)
        p.drawPixmap(self.rect(), self._pm)
        p.end()


class MainWindow(QtWidgets.QWidget):
    # 后台线程探测完，用信号把结果递回主线程（工作线程里直接碰界面会崩）
    scan_result = QtCore.Signal(object)

    def __init__(self, cfg: Config, guard: ProcessGuard, hotkeys: HotkeyManager):
        super().__init__()
        self.cfg = cfg
        # 皮肤：先定当前皮肤，再装上样式翻译钩子，后面所有 setStyleSheet 都跟着走
        theme.set_current(getattr(cfg, "theme", "") or "cyber")
        _install_style_hook()
        self.guard = guard
        self.hotkeys = hotkeys
        # 模组注册的全局热键：{(模组 id, 组合键): (vk, modifiers)}
        self._mod_hotkeys = {}
        # 上次选的作用屏：换回主屏就传 None（模块级状态，所有切档调用自动跟随）
        try:
            display.set_target(getattr(cfg, "screen_device", "") or None)
        except Exception:  # noqa: BLE001
            pass
        # 素材根：截图 / 录屏 / 素材库都跟着这个走（空 = 程序目录下的「素材」）
        try:
            capture.set_root(getattr(cfg, "media_dir", "") or None)
        except Exception:  # noqa: BLE001
            pass
        self.recorder = recorder.ScreenRecorder(self)
        self.replay = replay.ReplayBuffer()
        self._replay_worker = None
        self.cards: List[ModCard] = []
        self.tiles: List[ModTile] = []
        self.auto_log: List[str] = []
        self._rule_active: dict = {}
        self._quitting = False
        self._hotkeys_registered = False
        # 本机工具探测的结果回主线程处理
        self.scan_result.connect(self._on_scan_result)

        self.setObjectName("Root")
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.resize(800, 780)
        # 一开就摆在屏幕正中：以前不给位置，系统会把窗口丢在左上角，
        # 每回启动都得自己拖到中间
        try:
            scr = QtWidgets.QApplication.primaryScreen()
            if scr is not None:
                g = scr.availableGeometry()
                fg = self.frameGeometry()
                fg.moveCenter(g.center())
                self.move(fg.topLeft())
        except Exception:  # noqa: BLE001
            pass
        # 内容排得开的最小宽（顶栏会换成两排、监控卡仍是四张）
        self.setMinimumWidth(660)
        self.setMinimumSize(660, 560)
        self.setStyleSheet(qss())

        # 音乐：网易云接口 + 自带播放器（音乐页自己放，不依赖外部客户端）
        self.music_api = musicapi.Ny(app_dir() / "音乐数据")
        self.qq_api = qqmusic.QQ(app_dir() / "音乐数据")
        self.kg_api = kugou.KG(app_dir() / "音乐数据")
        self.kw_api = kuwo.KW(app_dir() / "音乐数据")
        self.player = mplayer.Player(self.music_api, self)
        self.player.api_map = {"ny": self.music_api, "qq": self.qq_api,
                               "kg": self.kg_api, "kw": self.kw_api}

        self._build_ui()
        self._art_tinted = None
        self._build_art()
        self.refresh_art()
        self.rebuild_mods()
        self._identify_machine()
        self.refresh_resolution()
        self.set_window_mode(getattr(self.cfg, "window_mode", "classic"))

        # 状态刷新（模组被外部关掉时也能反映出来）
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1500)

        # 开机自启 / 只进托盘时窗口不显示，showEvent 不会触发 —— 这里主动注册一次，
        # 否则热键在托盘模式下全是哑的（showEvent 里那次是幂等的，不会重复注册）
        if self.cfg.hotkey_enabled:
            QTimer.singleShot(200, self.register_hotkeys)

        # 系统监控（控制面板上那四张小卡）
        # 老那套“读系统媒体会话”的通道不用了，音乐页自带播放器
        self.music = None

        self.sysmon = sysmon.SysMon(2500, self)
        self.sysmon.updated.connect(self._on_sysmon)
        self.sysmon.start()


        # 接收"双击程序图标"发来的命令
        self.cmd_timer = QTimer(self)
        self.cmd_timer.timeout.connect(self._poll_command)
        self.cmd_timer.start(250)

        # ACE 扫盘限制：自动守护（游戏重启 ACE 进程后再压一次）
        self.ace_timer = QTimer(self)
        self.ace_timer.timeout.connect(self._ace_tick)
        self.ace_timer.start(6000)
        QTimer.singleShot(700, self._ace_refresh_state)

        # 每日密码悬浮窗（只显示当天密码；开关在设置面板和托盘菜单里）
        self.fps_hud = fps_hud.FpsHud(self.cfg)
        self.fps_mon = fps.FpsMonitor(self)
        self.fps_mon.changed.connect(self.fps_hud.set_value)
        self.fps_hud.admin_requested.connect(self._fps_restart_as_admin)

        # 准星叠加层（默认关，开关在工具页）
        self.crosshair = crosshair.CrosshairWindow(self.cfg)
        if getattr(self.cfg, "cross_show", False):
            QTimer.singleShot(600, self.apply_crosshair)

        self.hud = daily_hud.DailyHud(self.cfg, on_open_page=self.show_delta)
        if self.cfg.hud_show:
            QTimer.singleShot(300, self.hud.show_hud)
        if not self.cfg.guide_shown:
            QTimer.singleShot(700, self.show_guide)
        if getattr(self.cfg, "fps_show", False):
            QTimer.singleShot(500, self.show_fps)

        # 自动化：进程触发
        self.rule_timer = QTimer(self)
        self.rule_timer.timeout.connect(self._watch_rules)
        self.rule_timer.start(2000)

        # 模组事件：界面起完之后广播一次 app.started（那时模组都已 load 完、订阅上了）
        QTimer.singleShot(1500, lambda: _emit_mod_event("app.started"))

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        outer = QtWidgets.QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # 一个窗口里叠两页：主页 + 三角洲情报页，顶部按钮来回切
        self.stack = QtWidgets.QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget { background: transparent; }")
        outer.addWidget(self.stack)

        self.home_page = QtWidgets.QWidget()
        self.home_page.setObjectName("HomePage")
        root = QtWidgets.QVBoxLayout(self.home_page)
        root.setContentsMargins(18, 4, 18, 10)
        root.setSpacing(14)

        # 内容一多就得能滚，不然下面那张卡会把上面的分辨率卡压扁
        self.home_scroll = QtWidgets.QScrollArea()
        self.home_scroll.setWidgetResizable(True)
        self.home_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.home_scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
        self.home_scroll.setWidget(self.home_page)
        self.stack.addWidget(self.home_scroll)

        # 标题
        head = QtWidgets.QHBoxLayout()
        titles = QtWidgets.QVBoxLayout()
        titles.setSpacing(2)
        t = QtWidgets.QLabel(APP_NAME)
        t.setObjectName("Title")
        s = QtWidgets.QLabel(APP_NAME_EN)
        s.setObjectName("Sub")

        # 游戏模式开着时这块换成金属「燧镜」+ GAME MODE 小红牌，切换在 set_game_mode 里
        self.brand_title = t
        self.brand_sub = s
        self.gm_tag = QtWidgets.QLabel("GAME MODE")
        self.gm_tag.setObjectName("GmTag")
        self.gm_tag.hide()

        row_a = QtWidgets.QHBoxLayout()
        row_a.setSpacing(9)
        row_a.addWidget(t)
        row_a.addStretch(0)
        titles.addLayout(row_a)
        row_b = QtWidgets.QHBoxLayout()
        row_b.setSpacing(7)
        row_b.addWidget(s)
        row_b.addWidget(self.gm_tag)
        row_b.addStretch(0)
        titles.addLayout(row_b)
        head.addLayout(titles)
        head.addStretch(1)

        self.audio_btn = QtWidgets.QPushButton()
        self.audio_btn.setObjectName("Skin")
        self.audio_btn.setFixedSize(30, 30)
        self.audio_btn.setIconSize(QtCore.QSize(24, 24))
        self.audio_btn.setCursor(Qt.PointingHandCursor)
        self.audio_btn.setToolTip("音频输出：点一下换一路（热键 Alt+Z）")
        self.audio_btn.clicked.connect(self.toggle_audio_output)
        head.addWidget(self.audio_btn)
        self._refresh_audio_btn()

        self.set_btn = QtWidgets.QPushButton()
        self.set_btn.setObjectName("Skin")
        self.set_btn.setFixedSize(30, 30)
        self.set_btn.setIcon(_gear_icon())
        self.set_btn.setIconSize(QtCore.QSize(19, 19))
        self.set_btn.setToolTip("设置：开机自启、热键、外观、关闭行为")
        self.set_btn.clicked.connect(self.show_settings)
        head.addWidget(self.set_btn)

        self.skin_btn = QtWidgets.QPushButton()
        self.skin_btn.setObjectName("Skin")
        self.skin_btn.setFixedSize(30, 30)
        self.skin_btn.setIcon(_skin_icon())
        self.skin_btn.setIconSize(QtCore.QSize(19, 19))
        self.skin_btn.setToolTip("外观：皮肤 / 窗口外观 / 背景模糊")
        self.skin_btn.clicked.connect(self.open_skin_panel)
        head.addWidget(self.skin_btn)

        self.native_hint = QtWidgets.QLabel()
        self.native_hint.setObjectName("NativeHint")
        self.native_hint.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        head.addWidget(self.native_hint)

        # 这两个只有毛玻璃模式才出来（那时候没有系统标题栏）
        self.btn_min = QtWidgets.QPushButton("\u2014")
        self.btn_min.setObjectName("WinBtn")
        self.btn_min.setFixedSize(28, 28)
        self.btn_min.setToolTip("最小化")
        self.btn_min.clicked.connect(self.showMinimized)
        self.btn_min.hide()
        head.addWidget(self.btn_min)

        self.btn_close = QtWidgets.QPushButton("\u2715")
        self.btn_close.setObjectName("WinBtn")
        self.btn_close.setFixedSize(28, 28)
        self.btn_close.setToolTip("关闭")
        self.btn_close.clicked.connect(self.close)
        self.btn_close.hide()
        head.addWidget(self.btn_close)
        head.setContentsMargins(18, 14, 18, 9)
        outer.insertLayout(0, head)  # 标题栏常驻，切页也在

        # 工具页 / 模组页：先把空页建好，下面再各自往里塞内容
        self.tools_page = QtWidgets.QWidget()
        self.tools_page.setObjectName("Page")
        self.tools_lay = QtWidgets.QVBoxLayout(self.tools_page)
        self.tools_lay.setContentsMargins(18, 4, 18, 12)
        self.tools_lay.setSpacing(12)
        self.stack.addWidget(self.tools_page)

        self.mods_page = QtWidgets.QWidget()
        self.mods_page.setObjectName("Page")
        self.mods_lay = QtWidgets.QVBoxLayout(self.mods_page)
        self.mods_lay.setContentsMargins(18, 4, 18, 12)
        self.mods_lay.setSpacing(10)
        self.stack.addWidget(self.mods_page)

        # 新框架的模组页：只认 .sjmod 包。外层程序仍然归上面的「工具」页。
        self.mod_page = QtWidgets.QWidget()
        self.mod_page.setObjectName("Page")
        self.mod_lay = QtWidgets.QVBoxLayout(self.mod_page)
        self.mod_lay.setContentsMargins(18, 4, 18, 12)
        self.mod_lay.setSpacing(10)
        self.stack.addWidget(self.mod_page)

        # 页签行：切页（主页 / 工具 / 模组 / 情报 / 素材）+ 右边两个管理动作
        nav_row = QtWidgets.QHBoxLayout()
        nav_row.setSpacing(6)
        self._tab_btns = {}
        for attr, text in (
            ("home_scroll", "主页"),
            ("tools_page", "内置工具"),
            ("mods_page", "工具"),
            ("mod_page", "模组"),
            ("music_page", "音乐"),
            ("steam_page", "Steam"),
            ("epic_page", "喜加一"),
        ):
            b = QtWidgets.QPushButton(text)
            b.setObjectName("Seg")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedHeight(28)
            b.setMinimumWidth(54)
            b.clicked.connect(lambda _=False, a=attr: self._goto(a))
            nav_row.addWidget(b)
            self._tab_btns[attr] = b
        nav_row.addStretch(1)

        gm_btn = QtWidgets.QPushButton("游戏模式")
        gm_btn.setObjectName("Seg")
        gm_btn.setCheckable(True)
        gm_btn.setFixedHeight(28)
        gm_btn.setMinimumWidth(74)
        gm_btn.setCursor(Qt.PointingHandCursor)
        gm_btn.setToolTip(
            "进游戏前点一下：收起壁纸、监控采集降到 6 秒一次、切到高性能电源计划。\n"
            "再点一下或退出程序，全部还原。不碰游戏进程，也不做任何注入。"
        )
        gm_btn.toggled.connect(self.set_game_mode)
        nav_row.addWidget(gm_btn)
        self.gm_btn = gm_btn

        auto_btn = QtWidgets.QPushButton("自动化")
        auto_btn.setObjectName("Seg")
        auto_btn.setFixedHeight(28)
        auto_btn.setToolTip("自己编排：看到某个进程就切分辨率、启动工具")
        auto_btn.clicked.connect(self.show_automation)
        nav_row.addWidget(auto_btn)

        log_btn = QtWidgets.QPushButton("日志")
        log_btn.setObjectName("Seg")
        log_btn.setFixedHeight(28)
        log_btn.setToolTip("看运行记录；出问题一键导出诊断包")
        log_btn.clicked.connect(self.show_logs)
        nav_row.addWidget(log_btn)
        nav_row.setContentsMargins(18, 0, 18, 9)
        outer.insertLayout(1, nav_row)

        # 主页的快速操作：截图 / 录屏 / 回放 / 音频（是动作，不是页面）
        quick_row = QtWidgets.QHBoxLayout()
        quick_row.setSpacing(6)

        shot_btn = QtWidgets.QPushButton("截图")
        shot_btn.setObjectName("Ghost")
        shot_btn.setFixedHeight(28)
        shot_menu = QtWidgets.QMenu(shot_btn)
        shot_menu.setStyleSheet(qss())
        shot_menu.addAction("全屏截图  (Ctrl+Alt+S)", self.shot_full)
        shot_menu.addAction("框选截图  (Ctrl+Alt+Shift+S)", self.shot_region)
        shot_menu.addAction("3 秒后截当前窗口", self.shot_delayed)
        shot_menu.addSeparator()
        shot_menu.addAction("打开素材页", self.show_media)
        shot_btn.setMenu(shot_menu)
        quick_row.addWidget(shot_btn)

        self.rec_btn = QtWidgets.QPushButton("录屏")
        self.rec_btn.setObjectName("Ghost")
        self.rec_btn.setFixedHeight(28)
        self.rec_btn.setToolTip("录当前屏幕，再点一次停止；文件自动进 素材\\录像\\日期")
        self.rec_btn.clicked.connect(self.toggle_record)
        quick_row.addWidget(self.rec_btn)

        self.replay_btn = QtWidgets.QPushButton("回放")
        self.replay_btn.setObjectName("Ghost")
        self.replay_btn.setFixedHeight(28)
        self.replay_btn.setToolTip("后台留着最近 12 分钟画面，按一下就存成最近 10 分钟的成片")
        replay_menu = QtWidgets.QMenu(self.replay_btn)
        replay_menu.setStyleSheet(qss())
        replay_menu.addAction("开启回放缓冲", self.toggle_replay)
        replay_menu.addAction("保存最近 10 分钟  (Ctrl+Alt+B)", self.save_replay)
        replay_menu.addSeparator()
        replay_menu.addAction("关闭回放缓冲", self.toggle_replay)
        self.replay_btn.setMenu(replay_menu)
        quick_row.addWidget(self.replay_btn)

        self.media_btn = QtWidgets.QPushButton("素材")
        self.media_btn.setObjectName("Ghost")
        self.media_btn.setFixedHeight(28)
        self.media_btn.setToolTip("截图、录像、回放存下来的成品都在这，按日期归档")
        self.media_btn.clicked.connect(self.show_media)
        quick_row.addWidget(self.media_btn)

        quick_row.addStretch(1)
        root.addLayout(quick_row)

        # 分辨率卡片：三行压紧，别占掉半屏
        card = QtWidgets.QFrame()
        card.setObjectName("Card")
        cl = QtWidgets.QVBoxLayout(card)
        cl.setContentsMargins(16, 12, 16, 12)
        cl.setSpacing(9)

        # 第一行：当前 + 比例 + 目标档位 + 换档按钮，一行看完
        line1 = QtWidgets.QHBoxLayout()
        line1.setSpacing(9)

        lbl = QtWidgets.QLabel("当前")
        lbl.setObjectName("Small")
        line1.addWidget(lbl, 0, Qt.AlignVCenter)

        self.cur_label = QtWidgets.QLabel("—")
        self.cur_label.setObjectName("ResValue")
        line1.addWidget(self.cur_label, 0, Qt.AlignVCenter)

        self.ratio_chip = QtWidgets.QLabel("—")
        self.ratio_chip.setStyleSheet(
            "color:#20ffe0; background:#102a27; border:1px solid #1c4a43;"
            "border-radius:6px; padding:2px 8px; font-size:11px;"
        )
        line1.addWidget(self.ratio_chip, 0, Qt.AlignVCenter)
        line1.addStretch(1)

        # 「回到原生」放这一行右端：它说的就是“现在这个分辨率”的状态
        self.restore_btn = QtWidgets.QPushButton("回到原生")
        self.restore_btn.setObjectName("Native")
        self.restore_btn.setMinimumHeight(32)
        self.restore_btn.setToolTip("一键回到你这块屏幕的原生分辨率和原生比例")
        self.restore_btn.clicked.connect(self.restore_native)
        line1.addWidget(self.restore_btn, 0, Qt.AlignVCenter)
        cl.addLayout(line1)

        # 第二行：目标档位（可伸缩）+ 大按钮；窗口拖窄时先压下拉，不会把按钮挤没
        line1b = QtWidgets.QHBoxLayout()
        line1b.setSpacing(9)

        tl = QtWidgets.QLabel("目标")
        tl.setObjectName("Small")
        tl.setToolTip(
            "列出这块屏真实支持的所有模式，按比例分组。"
            "「原生」单独标在最上面，4:3 里带 ★ 的是常被推荐的档。"
        )
        line1b.addWidget(tl, 0, Qt.AlignVCenter)

        self.target_combo = QtWidgets.QComboBox()
        self.target_combo.setToolTip(
            "按比例分组：原生（你这块屏）/ 4:3 / 16:10 / 5:4 / 16:9。"
            "带 ★ 的是常见游戏推荐档，选「原生」会立刻切回去。"
        )
        self.target_combo.setMinimumWidth(190)
        self.target_combo.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        line1b.addWidget(self.target_combo, 1, Qt.AlignVCenter)

        self.toggle_btn = QtWidgets.QPushButton("切换为此档")
        self.toggle_btn.setObjectName("Primary")
        self.toggle_btn.setMinimumHeight(40)
        self.toggle_btn.setMinimumWidth(150)
        self.toggle_btn.clicked.connect(self.toggle_resolution)
        line1b.addWidget(self.toggle_btn, 0, Qt.AlignVCenter)

        # 低频操作收进「⋯」：这几个一年也用不了几次，不该各占一行
        self.more_btn = QtWidgets.QPushButton("···")
        self.more_btn.setObjectName("Mini")
        self.more_btn.setFixedSize(40, 40)
        self.more_btn.setToolTip("以当前为原生 / 自定义分辨率 / 刷新档位列表")
        self.more_btn.clicked.connect(self._show_more_menu)
        self.more_menu = QtWidgets.QMenu(self)
        self.act_mark = self.more_menu.addAction("以当前为原生")
        self.act_mark.setToolTip("换了显示器或插了外接屏时，把当前分辨率重新记为「原生」")
        self.act_mark.triggered.connect(self.mark_native)
        self.act_custom = self.more_menu.addAction("自定义分辨率…")
        self.act_custom.setToolTip("输入枚举里没有的档（如 1728x1080），会先试探支持不支持")
        self.act_custom.triggered.connect(self.set_custom_resolution)
        self.act_refresh = self.more_menu.addAction("刷新档位列表")
        self.act_refresh.setToolTip("重新读一遍这块屏支持的所有模式")
        self.act_refresh.triggered.connect(self.refresh_resolution)
        line1b.addWidget(self.more_btn, 0, Qt.AlignVCenter)
        cl.addLayout(line1b)

        # 第三行：去黑边 + 显卡一行放完（窗口变窄时状态字先让位）
        line3 = QtWidgets.QHBoxLayout()
        line3.setSpacing(8)

        self.stretch_chk = QtWidgets.QCheckBox("嘉豪模式 · 4:3 拉满")
        self.stretch_chk.setToolTip(
            "开启后切到 4:3 档就不想看见左右黑边。"
            "黑边由显卡缩放模式决定，软件会帮你检测并引导去设置。"
        )
        self.stretch_chk.setChecked(self.cfg.stretch)
        self.stretch_chk.toggled.connect(self._on_stretch_toggled)
        line3.addWidget(self.stretch_chk, 0, Qt.AlignVCenter)

        self.stretch_state = QtWidgets.QLabel("")
        self.stretch_state.setObjectName("Small")
        self.stretch_state.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred
        )
        line3.addWidget(self.stretch_state, 1)
        line3.addSpacing(2)

        self.stretch_link = QtWidgets.QPushButton("去显卡设置")
        self.stretch_link.setObjectName("Mini")
        self.stretch_link.setToolTip("打开显卡面板，把缩放模式改成全屏/拉伸")
        self.stretch_link.clicked.connect(self.open_scaling_panel)
        line3.addWidget(self.stretch_link)

        self.vendor_combo = QtWidgets.QComboBox()
        self.vendor_combo.setObjectName("Mini")
        self.vendor_combo.setToolTip("自动判断有时会认错（核显独显都在），认错了就在这手动选")
        for label, key in (
            ("显卡：自动", "auto"),
            ("显卡：NVIDIA", "nvidia"),
            ("显卡：AMD", "amd"),
            ("显卡：Intel", "intel"),
        ):
            self.vendor_combo.addItem(label, key)
        idx = self.vendor_combo.findData(self.cfg.gpu_vendor or "auto")
        self.vendor_combo.setCurrentIndex(max(0, idx))
        self.vendor_combo.currentIndexChanged.connect(self._on_vendor_change)
        line3.addWidget(self.vendor_combo)
        cl.addLayout(line3)

        hint = QtWidgets.QLabel("")
        hint.setObjectName("Hint")
        self.hotkey_hint = hint
        hint.setVisible(False)
        cl.addWidget(hint)

        # 多屏时才出现的一行：切哪块屏 + 一句说明
        self.screen_row = QtWidgets.QWidget()
        srow = QtWidgets.QHBoxLayout(self.screen_row)
        srow.setContentsMargins(0, 0, 0, 0)
        srow.setSpacing(8)
        self.screen_label = QtWidgets.QLabel("作用屏幕")
        self.screen_label.setObjectName("Small")
        srow.addWidget(self.screen_label)

        self.screen_combo = QtWidgets.QComboBox()
        self.screen_combo.setFixedHeight(26)
        self.screen_combo.setMinimumWidth(240)
        self.screen_combo.setToolTip("切档只动选中的这块屏，别的屏参数不变")
        self.screen_combo.currentIndexChanged.connect(self._on_screen_change)
        srow.addWidget(self.screen_combo)

        self.screen_hint = QtWidgets.QLabel("")
        self.screen_hint.setObjectName("Hint")
        srow.addWidget(self.screen_hint)
        srow.addStretch(1)
        self.screen_row.setVisible(False)
        cl.addWidget(self.screen_row)

        # 分辨率卡占左边，右边竖着排两个方块：剪贴板 / 文件互传
        # 外面得包一层固定高度的壳，不然这两个方块会把整行撑高、把分辨率卡拉散
        res_host = QtWidgets.QWidget()
        res_host.setSizePolicy(
            QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed
        )
        res_row = QtWidgets.QHBoxLayout(res_host)
        res_row.setContentsMargins(0, 0, 0, 0)
        res_row.setSpacing(10)
        res_row.addWidget(card, 1, Qt.AlignTop)

        tile_col = QtWidgets.QVBoxLayout()
        tile_col.setContentsMargins(0, 0, 0, 0)
        tile_col.setSpacing(8)
        self.tile_clip = ToolTile(
            "连接手机", "phone",
            "点开：二维码和配对码一起给，手机用「燧镜手机版」扫或输码就连上", size=72
        )
        self.tile_clip.clicked.connect(self.open_clip_from_home)
        # 右上角一个小点：青色实心=手机连着，灰色空心=没连
        self.link_dot = QtWidgets.QLabel(self.tile_clip)
        self.link_dot.setFixedSize(9, 9)
        self.link_dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.link_dot.setStyleSheet(self._link_dot_qss(False))
        self.link_dot.move(self.tile_clip.width() - 14, 5)
        QTimer.singleShot(0, self._wire_link_dot)
        tile_col.addWidget(self.tile_clip)
        self.tile_files = ToolTile(
            "文件互传", "share", "把要传的文件丢进「分享」文件夹，手机就能下载；手机传上来的进「收到」", size=72
        )
        self.tile_files.clicked.connect(self.open_share_dialog)
        tile_col.addWidget(self.tile_files)
        self.tile_cast = ToolTile(
            "手机投屏", "cast",
            "把手机画面搬到电脑，鼠标键盘直接反控；包内自带 scrcpy，手机不用装 App",
            size=72,
        )
        self.tile_cast.clicked.connect(self.open_scrcpy_dialog)
        # 投屏不进上面那列，落到监控卡这一行的最右，正好接在「文件互传」下头
        res_row.addLayout(tile_col, 0)
        res_row.setAlignment(tile_col, Qt.AlignTop)
        root.addWidget(res_host)

        # 系统监控（CPU / 内存 / 显卡 / 显卡温度）
        mon_row = QtWidgets.QHBoxLayout()
        mon_row.setSpacing(10)
        self.stat_widgets = {}
        self.stat_cards = {}
        for key, title in (("cpu", "CPU"), ("mem", "内存"), ("gpu", "显卡"), ("temp", "显卡温度")):
            box_card = QtWidgets.QFrame()
            box_card.setObjectName("StatCard")
            bx = QtWidgets.QVBoxLayout(box_card)
            bx.setContentsMargins(12, 9, 12, 9)
            bx.setSpacing(4)

            cap = QtWidgets.QLabel(title)
            cap.setObjectName("Small")
            bx.addWidget(cap)

            val = QtWidgets.QLabel("--")
            val.setObjectName("StatValue")
            bx.addWidget(val)

            bar = QtWidgets.QProgressBar()
            bar.setObjectName("StatBar")
            bar.setRange(0, 100)
            bar.setValue(0)
            bar.setTextVisible(False)
            bar.setFixedHeight(5)
            bx.addWidget(bar)

            mon_row.addWidget(box_card, 1)
            self.stat_widgets[key] = (val, bar)
            self.stat_cards[key] = box_card
        mon_row.addWidget(self.tile_cast, 0, Qt.AlignTop)
        root.addLayout(mon_row)

        # 这台机器：硬件规格（默认收起，展开才读）
        self.spec_card = QtWidgets.QFrame()
        self.spec_card.setObjectName("Card")
        sl = QtWidgets.QVBoxLayout(self.spec_card)
        sl.setContentsMargins(16, 11, 16, 11)
        sl.setSpacing(0)

        sline = QtWidgets.QHBoxLayout()
        sline.setSpacing(8)
        st = QtWidgets.QLabel("这台机器")
        st.setObjectName("Section")
        sline.addWidget(st)

        self.spec_sum = QtWidgets.QLabel("CPU、内存条、显卡、硬盘、显示器")
        self.spec_sum.setObjectName("Hint")
        sline.addWidget(self.spec_sum)
        sline.addStretch(1)

        self.spec_copy = QtWidgets.QPushButton("复制报告")
        self.spec_copy.setObjectName("Ghost")
        self.spec_copy.setFixedHeight(26)
        self.spec_copy.setStyleSheet("padding: 0px 11px; font-size: 12px;")
        self.spec_copy.setCursor(Qt.PointingHandCursor)
        self.spec_copy.setToolTip("把整份硬件报告复制到剪贴板")
        self.spec_copy.clicked.connect(self.copy_spec)
        sline.addWidget(self.spec_copy)

        self.spec_save = QtWidgets.QPushButton("导出")
        self.spec_save.setObjectName("Ghost")
        self.spec_save.setFixedHeight(26)
        self.spec_save.setStyleSheet("padding: 0px 11px; font-size: 12px;")
        self.spec_save.setCursor(Qt.PointingHandCursor)
        self.spec_save.setToolTip("存成 txt，方便发给别人看配置")
        self.spec_save.clicked.connect(self.save_spec)
        sline.addWidget(self.spec_save)

        self.spec_btn = QtWidgets.QPushButton("展开")
        self.spec_btn.setObjectName("Native")
        self.spec_btn.setFixedHeight(26)
        self.spec_btn.setStyleSheet("padding: 0px 11px; font-size: 12px;")
        self.spec_btn.setCursor(Qt.PointingHandCursor)
        self.spec_btn.clicked.connect(self.toggle_spec)
        sline.addWidget(self.spec_btn)
        sl.addLayout(sline)

        self.spec_body = QtWidgets.QWidget()
        sg = QtWidgets.QGridLayout(self.spec_body)
        sg.setContentsMargins(0, 9, 0, 2)
        sg.setHorizontalSpacing(16)
        sg.setVerticalSpacing(6)
        sg.setColumnStretch(1, 1)
        self._spec_grid = sg
        self.spec_body.setVisible(False)
        sl.addWidget(self.spec_body)
        root.addWidget(self.spec_card)
        root.addStretch(1)

        # ACE 扫盘限制卡片
        ace_card = QtWidgets.QFrame()
        ace_card.setObjectName("Card")
        al = QtWidgets.QVBoxLayout(ace_card)
        al.setContentsMargins(16, 12, 16, 12)
        al.setSpacing(6)

        ace_line = QtWidgets.QHBoxLayout()
        ace_line.setSpacing(10)
        ace_title = QtWidgets.QLabel("反作弊优化")
        ace_title.setStyleSheet("font-size:13.5px; font-weight:700; color:#f0f4fa;")
        ace_title.setToolTip(
            "只做三件事：进程优先级拉最低、CPU 亲和性收到一个核、磁盘 I/O 优先级降到最低。\n"
            "不注入游戏进程，不读写游戏内存，不改游戏文件；反作弊扫描照常进行，\n"
            "只是让它排在游戏后面。是否使用请自行判断。"
        )
        ace_line.addWidget(ace_title)

        self.ace_badge = QtWidgets.QLabel("未生效")
        self.ace_badge.setObjectName("BadgeDim")
        ace_line.addWidget(self.ace_badge)

        ace_line.addStretch(1)

        self.ace_limit_btn = QtWidgets.QPushButton("一键优化")
        self.ace_limit_btn.setObjectName("Mini")
        self.ace_limit_btn.setToolTip("把 SGuard64 / ACE 相关进程的优先级拉到最低，并只留最后一个核")
        self.ace_limit_btn.clicked.connect(self.ace_apply)
        ace_line.addWidget(self.ace_limit_btn)

        self.ace_restore_btn = QtWidgets.QPushButton("还原")
        self.ace_restore_btn.setObjectName("Mini")
        self.ace_restore_btn.setToolTip("恢复 ACE 进程的正常优先级和全部 CPU 核心")
        self.ace_restore_btn.clicked.connect(self.ace_restore)
        ace_line.addWidget(self.ace_restore_btn)

        self.ace_guard_chk = QtWidgets.QCheckBox("自动守护")
        self.ace_guard_chk.setToolTip("游戏重启 ACE 进程后自动再压一次，不用每局手动点")
        self.ace_guard_chk.setChecked(self.cfg.ace_guard)
        self.ace_guard_chk.toggled.connect(self._on_ace_guard)
        ace_line.addWidget(self.ace_guard_chk)
        al.addLayout(ace_line)

        self.ace_state = QtWidgets.QLabel("")
        self.ace_state.setObjectName("Small")
        self.ace_state.setWordWrap(True)
        al.addWidget(self.ace_state)

        ace_desc = QtWidgets.QLabel(
            "扫描照做，只压优先级、只给一个核；不注入、不读游戏内存、不改游戏文件"
        )
        ace_desc.setObjectName("Hint")
        ace_desc.setWordWrap(True)
        al.addWidget(ace_desc)
        self.tools_lay.addWidget(ace_card)


        self.cross_card = CrossCard(self)
        self.tools_lay.addWidget(self.cross_card)

        self.power_card = PowerCard(self)
        self.tools_lay.addWidget(self.power_card)

        self.tools_card = ToolsCard(self)
        self.tools_lay.addWidget(self.tools_card)

        self.tools_lay.addStretch(1)

        # 工具区标题
        mod_head = QtWidgets.QHBoxLayout()
        self.mod_title = QtWidgets.QLabel("工具")
        self.mod_title.setObjectName("Section")
        mod_head.addWidget(self.mod_title)
        self.mod_count = QtWidgets.QLabel("")
        self.mod_count.setObjectName("Small")
        mod_head.addWidget(self.mod_count)
        mod_head.addStretch(1)

        self.seg_grid = QtWidgets.QToolButton()
        self.seg_grid.setText("图标")
        self.seg_grid.setObjectName("Seg")
        self.seg_grid.setCheckable(True)
        self.seg_grid.setCursor(Qt.PointingHandCursor)
        self.seg_grid.setToolTip("方块图标排列，双击启动 / 停止")
        self.seg_grid.clicked.connect(lambda: self.set_view_mode("grid"))

        self.seg_list = QtWidgets.QToolButton()
        self.seg_list.setText("列表")
        self.seg_list.setObjectName("Seg")
        self.seg_list.setCheckable(True)
        self.seg_list.setCursor(Qt.PointingHandCursor)
        self.seg_list.setToolTip("每行一个，显示完整路径和开关")
        self.seg_list.clicked.connect(lambda: self.set_view_mode("list"))

        view_box = QtWidgets.QHBoxLayout()
        view_box.setSpacing(0)
        view_box.addWidget(self.seg_grid)
        view_box.addWidget(self.seg_list)
        mod_head.addLayout(view_box)
        mod_head.addSpacing(10)

        # 工具页不放「全部启动」：这一页混着网页工具和还没下载的三方工具，
        # 一键全起没有意义，也容易误开一堆东西。要全起去模组页。
        self.launch_all_btn = None

        # 刷新：手动再扫一遍本机已装的三方工具（平时不会自动扫盘）
        self.scan_btn = QtWidgets.QPushButton("刷新")
        self.scan_btn.setObjectName("Ghost")
        self.scan_btn.setToolTip("重新扫一遍本机已装的三方工具：注册表卸载表 + 常见安装目录")
        self.scan_btn.clicked.connect(self.rescan_tools)
        mod_head.addWidget(self.scan_btn)

        add_btn = QtWidgets.QPushButton("+ 添加工具")
        add_btn.setObjectName("Ghost")
        add_btn.clicked.connect(self.add_mod)
        mod_head.addWidget(add_btn)

        # 导出/导入清单：换台电脑装机时，把"自己加的那些"搬过去
        self.mod_menu_btn = QtWidgets.QPushButton("⋯")
        self.mod_menu_btn.setObjectName("Ghost")
        self.mod_menu_btn.setFixedWidth(32)
        self.mod_menu_btn.setToolTip("导出 / 导入工具清单（换台电脑不用一条条重加）")
        self.mod_menu_btn.clicked.connect(self.mod_menu)
        mod_head.addWidget(self.mod_menu_btn)
        self.mods_lay.addLayout(mod_head)

        # 工具滚动区
        self.scroll = QtWidgets.QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.mod_host = QtWidgets.QWidget()
        self.mod_root = QtWidgets.QVBoxLayout(self.mod_host)
        self.mod_root.setContentsMargins(0, 0, 4, 0)
        self.mod_root.setSpacing(0)
        self.scroll.setWidget(self.mod_host)
        self.mods_lay.addWidget(self.scroll, 1)

        # 新框架模组页（只认 .sjmod）。这里出错也只是这一页空着，不影响其它页
        self.mod_view = None
        try:
            from core.mod_ui import ModPage as _ModPage

            self.mod_view = _ModPage(self, app_version=APP_VERSION)
            self.mod_lay.addWidget(self.mod_view, 1)
        except Exception as exc:  # noqa: BLE001
            hint = QtWidgets.QLabel("模组页没起来：" + str(exc)[:120])
            hint.setObjectName("Hint")
            hint.setWordWrap(True)
            self.mod_lay.addWidget(hint)

        # 底部提示
        foot = QtWidgets.QHBoxLayout()
        # 切音频时的左上角提示（顶层小窗，鼠标能穿过去）
        self.audio_osd = AudioOSD()
        self.audio_tray = None

        self.toast_label = QtWidgets.QLabel("关闭窗口会收进托盘，工具不会被关掉。")
        self.toast_label.setObjectName("Hint")
        self.toast_label.setWordWrap(True)
        # 热键冲突时这行会很长；能折行才不至于把整个窗口撑宽、把右边裁掉
        self.toast_label.setSizePolicy(
            QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred
        )
        self.toast_label.setMinimumWidth(0)
        foot.addWidget(self.toast_label, 1)
        tray_btn = QtWidgets.QPushButton("收进托盘")
        tray_btn.setObjectName("Ghost")
        tray_btn.clicked.connect(self.hide)
        foot.addWidget(tray_btn)
        foot.setContentsMargins(18, 0, 18, 10)
        outer.addLayout(foot)

        # 三角洲情报页：和主页同一个窗口，切页而不是另开窗口
        self.delta_page = DeltaPage(self)
        self.stack.addWidget(self.delta_page)

        self.media_page = MediaPage(self)
        self.stack.addWidget(self.media_page)

        self.music_page = MusicPage(self)
        self.stack.addWidget(self.music_page)

        # Steam 库 / Epic 喜加一：一个读本地台账，一个读公开免费列表
        self.steam_page = SteamPage(self)
        self.stack.addWidget(self.steam_page)

        self.epic_page = EpicPage(self)
        self.stack.addWidget(self.epic_page)

        # 顶部灵动岛：有歌在放的时候浮在窗口中间，任何页面都能控
        self.island = MiniPlayer(self)
        self.island.hide()
        self.mode_island = _ModeIsland(self)
        self.mode_island.hide()
        if self.player is not None:
            self.player.changed.connect(self.island.refresh)

        # 桌面音乐悬浮条：屏幕上的独立小窗（跟帧率窗一类），不是窗口里这条
        self.music_bar = musicbar.MusicBar(self.player, self.cfg)
        self.music_bar.hide()
        if self.player is not None:
            self.player.changed.connect(self.music_bar.sync)

        # 切页时页签高亮跟着走（托盘菜单里切过去也同步）
        self.stack.currentChanged.connect(self._on_stack_page)
        self._sync_tabs()

    # ------------------------------------------------------------------
    # 工具区
    # ------------------------------------------------------------------
    def set_music_bar(self, on: bool) -> None:
        """音乐页那个「桌面悬浮条」开关：开就等有歌时自己露头，关就收起。"""
        on = bool(on)
        mb = getattr(self, "music_bar", None)
        if mb is not None:
            mb.set_enabled(on)

    def set_view_mode(self, mode: str) -> None:
        mode = "grid" if mode == "grid" else "list"
        if self.cfg.view_mode != mode:
            self.cfg.view_mode = mode
            self.cfg.save()
            self.rebuild_mods()
            self.toast(
                "已切换为「图标」视图，双击格子启动 / 停止"
                if mode == "grid"
                else "已切换为「列表」视图",
                True,
            )
        else:
            self._sync_seg()

    def _sync_seg(self) -> None:
        is_grid = self.cfg.view_mode == "grid"
        self.seg_grid.setChecked(is_grid)
        self.seg_list.setChecked(not is_grid)

    def _make_empty(self) -> QtWidgets.QLabel:
        empty = QtWidgets.QLabel(
            "还没有工具\n\n"
            "点右上角「+ 添加工具」，选一个 exe / bat / html，\n"
            "或者直接粘贴一个网址\n\n"
            "加进来之后，这个框架就能统一启动、停止它们"
        )
        empty.setObjectName("Empty")
        empty.setAlignment(Qt.AlignCenter)
        empty.setWordWrap(True)
        return empty

    def _group_head(self, title: str, hint: str = "") -> QtWidgets.QWidget:
        """分组横线：左边「三方工具」，右边一条细线把两拨分开。"""
        w = QtWidgets.QWidget()
        row = QtWidgets.QHBoxLayout(w)
        row.setContentsMargins(2, 12, 2, 2)
        row.setSpacing(8)
        lab = QtWidgets.QLabel(title)
        lab.setStyleSheet("color:#8a7bd4; font-size:11.5px; font-weight:600;")
        row.addWidget(lab)
        if hint:
            h = QtWidgets.QLabel(hint)
            h.setObjectName("Small")
            row.addWidget(h)
        line = QtWidgets.QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet("background:#2a3240;")
        row.addWidget(line, 1)
        return w

    def _grid_group(self, mods) -> FlowPage:
        page = FlowPage()
        flow = FlowLayout(page, margin=0, hspacing=8, vspacing=8)
        page.flow = flow
        for mod in mods:
            tile = ModTile(mod, self.guard, self.cfg, self)
            tile.changed.connect(self._on_mods_changed)
            self.tiles.append(tile)
            flow.addWidget(tile)
        return page

    def rebuild_mods(self) -> None:
        while self.mod_root.count():
            item = self.mod_root.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.cards.clear()
        self.tiles.clear()
        self._sync_seg()

        # 已落地的（本地程序 / 网页 / 内置页面）和没下载的三方工具分开排
        local = [m for m in self.cfg.mods if m.kind != KIND_REMOTE]
        remote = [m for m in self.cfg.mods if m.kind == KIND_REMOTE]

        if self.cfg.view_mode == "grid":
            if not self.cfg.mods:
                page = FlowPage()
                flow = FlowLayout(page, margin=0, hspacing=8, vspacing=8)
                page.flow = flow
                flow.addWidget(self._make_empty())
                self.mod_root.addWidget(page, 0, Qt.AlignTop)
            else:
                if local:
                    self.mod_root.addWidget(self._grid_group(local), 0, Qt.AlignTop)
                if remote:
                    if local:
                        self.mod_root.addWidget(
                            self._group_head("三方工具", "没下载 · 点一格去官网"),
                            0,
                            Qt.AlignTop,
                        )
                    self.mod_root.addWidget(self._grid_group(remote), 0, Qt.AlignTop)
        else:
            page = QtWidgets.QWidget()
            col = QtWidgets.QVBoxLayout(page)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(8)
            if not self.cfg.mods:
                col.addWidget(self._make_empty())
            else:
                for mod in local:
                    card = ModCard(mod, self.guard, self.cfg, self)
                    card.changed.connect(self._on_mods_changed)
                    self.cards.append(card)
                    col.addWidget(card)
                if remote:
                    if local:
                        col.addWidget(self._group_head("三方工具", "没下载 · 点卡片去官网"))
                    for mod in remote:
                        card = ModCard(mod, self.guard, self.cfg, self)
                        card.changed.connect(self._on_mods_changed)
                        self.cards.append(card)
                        col.addWidget(card)
            col.addStretch(1)
            self.mod_root.addWidget(page)

        enabled = sum(1 for m in self.cfg.mods if m.enabled)
        self.mod_count.setText(f"{enabled} / {len(self.cfg.mods)} 已启用")
        QTimer.singleShot(0, self._fit_mod_host)
        QTimer.singleShot(0, self._ensure_favicons)

    def _ensure_favicons(self) -> None:
        """三方工具 / 网址类没图标时，后台去官网扒一次，扒回来重建换上去。"""
        th = getattr(self, "_fav_thread", None)
        if th is not None and th.isRunning():
            return
        seen = getattr(self, "_fav_seen", None)
        if seen is None:
            seen = self._fav_seen = set()
        need = []
        for m in self.cfg.mods:
            if m.kind not in (KIND_REMOTE, KIND_URL):
                continue
            host = (urllib.parse.urlparse(m.path or "").netloc or "").strip()
            if not host or host in seen:
                continue
            if _favicon_file(host) is not None:
                continue
            seen.add(host)
            need.append(host)
        if not need:
            return
        self._fav_thread = _FaviconFetcher(need, self)
        self._fav_thread.done.connect(self._on_favicons_done)
        self._fav_thread.start()

    def _on_favicons_done(self, got: int) -> None:
        _ICON_CACHE.clear()
        self.rebuild_mods()
        if got:
            self.toast(f"已抓到 {got} 个官网图标", True)

    def _fit_mod_host(self) -> None:
        """图标视图内容不满一屏时，别留一块空的可滚动区域。"""
        if not self.mod_root.count():
            return
        if self.cfg.view_mode != "grid":
            self.mod_host.setMinimumHeight(0)
            self.mod_host.setMaximumHeight(16777215)
            return
        avail = self.mod_host.width()
        view = getattr(self.mod_host, "viewport", None)
        if callable(view):
            avail = view().width()
        if avail < 200:
            avail = 200
        total = 0
        for i in range(self.mod_root.count()):
            w = self.mod_root.itemAt(i).widget()
            if w is None:
                continue
            flow = getattr(w, "flow", None)
            if flow is not None:
                h = flow.heightForWidth(avail)
                if h <= 0:
                    h = w.sizeHint().height()
                w.setFixedHeight(max(1, h))
            else:
                h = w.sizeHint().height()
                if h <= 0:
                    h = w.height()
                w.setFixedHeight(max(1, h))
            total += max(1, h)
        total += self.mod_root.spacing() * max(0, self.mod_root.count() - 1)
        self.mod_host.setFixedHeight(max(1, total))

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if getattr(self, "art", None) is not None:
            self._art_timer.start()
        if self.cfg.view_mode == "grid":
            QTimer.singleShot(0, self._fit_mod_host)

    def _on_mods_changed(self) -> None:
        enabled = sum(1 for m in self.cfg.mods if m.enabled)
        self.mod_count.setText(f"{enabled} / {len(self.cfg.mods)} 已启用")
        win = getattr(self, "tray_owner", None)
        if win is not None:
            win.mark_dirty()
        # 移除后要重建（两种视图都算）
        shown = len(self.cards) + len(self.tiles)
        if shown != len(self.cfg.mods):
            QTimer.singleShot(0, self.rebuild_mods)

    def mod_menu(self) -> None:
        m = QtWidgets.QMenu(self)
        a = m.addAction("导出工具清单…")
        a.triggered.connect(self.export_mods)
        b = m.addAction("导入工具清单…")
        b.triggered.connect(self.import_mods)
        # 重新扫描只留顶部「刷新」一个入口，这里不再重复
        m.exec(self.mod_menu_btn.mapToGlobal(self.mod_menu_btn.rect().bottomLeft()))

    def rescan_tools(self, *_a) -> None:
        """手动再扫一遍：装完新工具不用重启软件。"""
        if not any(m.kind == KIND_REMOTE for m in self.cfg.mods):
            self.toast("列表里已经没有待识别的三方工具了")
            return
        self.toast("正在扫本机已装的工具…")
        self.scan_tools_async(force=True)

    def scan_tools_async(self, force: bool = False) -> None:
        """后台线程去探测，结果回主线程套用（启动时那一次也走这条路）。

        force=False 时按 scan_stamp 过滤：同一个工具 24 小时内扫过就不再翻，
        检查是不是装了新工具这种事情交给手动按钮，不自动扫盘。
        """
        import threading
        import time as _time

        all_names = [m.name for m in self.cfg.mods if m.kind == KIND_REMOTE]
        if not all_names:
            return
        now = _time.time()
        if force:
            pending = list(all_names)
        else:
            pending = [
                n for n in all_names
                if now - float(self.cfg.scan_stamp.get(n, 0.0)) > 24 * 3600
            ]
        if not pending:
            return

        def work() -> None:
            try:
                from core.tools_detect import detect_installed

                hits = detect_installed(pending)
            except Exception as exc:  # noqa: BLE001
                log.warning("扫描本机已装工具失败：%s", exc)
                return
            self.scan_result.emit({"hits": hits, "scanned": pending, "stamp": now})

        threading.Thread(target=work, daemon=True).start()

    def _on_scan_result(self, payload: object) -> None:
        if not isinstance(payload, dict):
            return
        self._apply_scan(
            payload.get("hits") or {},
            list(payload.get("scanned") or []),
            float(payload.get("stamp") or 0.0),
        )

    def _apply_scan(self, hits: dict, scanned: list, stamp: float) -> None:
        for name in scanned:
            self.cfg.scan_stamp[name] = stamp
        try:
            names = self.cfg.apply_installed_tools(hits)
        except Exception as exc:  # noqa: BLE001
            log.warning("套用扫描结果失败：%s", exc)
            return
        self.cfg.save()
        if not names:
            return
        self.rebuild_mods()
        self.toast("认出 %d 个本机已装的工具：%s" % (len(names), "、".join(names)))

    def export_mods(self, *_a) -> None:
        """只导自己加的那些：内置的本来就随包走，搬过去反而添乱。"""
        import json as _json

        rows = []
        for mod in self.cfg.mods:
            if str(getattr(mod, "id", "")).startswith("builtin-"):
                continue
            rows.append({
                "name": mod.name,
                "path": mod.path,
                "kind": mod.kind,
                "args": list(mod.args or []),
                "enabled": bool(mod.enabled),
                "autostart": bool(mod.autostart),
                "note": mod.note or "",
                "delay": int(mod.delay or 0),
            })
        if not rows:
            self.toast("现在没有自己加的工具，导出来是空的", False)
            return
        path, _f = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "导出工具清单",
            str(Path.home() / "Desktop" / "燧镜工具清单.json"),
            "JSON (*.json)",
        )
        if not path:
            return
        try:
            Path(path).write_text(
                _json.dumps(
                    {"app": APP_NAME, "version": APP_VERSION, "mods": rows},
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        except Exception as exc:  # noqa: BLE001
            self.toast("导出失败：" + str(exc)[:60], False)
            return
        self.toast(f"已导出 {len(rows)} 条工具，换台电脑点「导入工具清单」就行")

    def import_mods(self, *_a) -> None:
        import json as _json
        import uuid as _uuid

        path, _f = QtWidgets.QFileDialog.getOpenFileName(
            self, "导入工具清单", str(Path.home() / "Desktop"), "JSON (*.json)"
        )
        if not path:
            return
        try:
            data = _json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            self.toast("这份清单读不了：" + str(exc)[:60], False)
            return
        rows = data.get("mods") if isinstance(data, dict) else data
        if not isinstance(rows, list):
            self.toast("这份清单格式不对", False)
            return
        have = {
            (m.name.strip(), str(m.path).replace("\\", "/").lower())
            for m in self.cfg.mods
        }
        added = skipped = 0
        for d in rows:
            if not isinstance(d, dict):
                continue
            name = str(d.get("name") or "").strip()
            p = str(d.get("path") or "").strip()
            if not name or not p:
                continue
            key = (name, p.replace("\\", "/").lower())
            if key in have:
                skipped += 1
                continue
            self.cfg.mods.append(
                Mod(
                    id=_uuid.uuid4().hex[:8],
                    name=name,
                    path=p,
                    kind=str(d.get("kind") or "exe"),
                    args=list(d.get("args") or []),
                    enabled=bool(d.get("enabled", True)),
                    autostart=bool(d.get("autostart", False)),
                    note=str(d.get("note") or ""),
                    delay=int(d.get("delay") or 0),
                )
            )
            have.add(key)
            added += 1
        try:
            self.cfg.save()
        except Exception:  # noqa: BLE001
            pass
        self.rebuild_mods()
        try:
            self._on_mods_changed()
        except Exception:  # noqa: BLE001
            pass
        if added:
            tail = f"，{skipped} 条本来就有" if skipped else ""
            self.toast(f"导入 {added} 条工具{tail}")
        elif skipped:
            self.toast("这些工具都已经在列表里了", False)
        else:
            self.toast("清单里没有可导入的工具", False)

    def add_mod(self) -> None:
        """「+ 添加工具」：先问一句是本地程序，还是挂官网链接的三方工具。"""
        m = QtWidgets.QMenu(self)
        m.addAction("本地程序 / 网页…", self._add_local_mod)
        m.addAction("三方工具（填官网链接）…", self._add_remote_mod)
        m.exec(QtGui.QCursor.pos())

    def _add_local_mod(self) -> None:
        dlg = AddModDialog(self)
        if dlg.exec() == QtWidgets.QDialog.Accepted:
            self.cfg.add_mod(dlg.result_name, dlg.result_path)
            self.rebuild_mods()
            self._on_mods_changed()
            self.toast("已添加工具：" + dlg.result_name, True)

    def _add_remote_mod(self) -> None:
        dlg = AddRemoteDialog(self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        self.cfg.add_mod(
            dlg.result_name, dlg.result_home, kind=KIND_REMOTE, dl=dlg.result_dl
        )
        self.rebuild_mods()
        self._on_mods_changed()
        self.toast("已添加三方工具：" + dlg.result_name, True)

    # ------------------------------------------------------------------
    # 分辨率
    # ------------------------------------------------------------------
    def _fill_combo(self) -> None:
        groups = display.grouped_modes()
        self.target_combo.blockSignals(True)
        self.target_combo.clear()

        if not groups:
            self.target_combo.addItem("没有枚举到可用模式", None)
            self.target_combo.setEnabled(False)
            self.toggle_btn.setEnabled(False)
            self.target_combo.blockSignals(False)
            return

        self.target_combo.setEnabled(True)
        self.toggle_btn.setEnabled(True)

        if self.cfg.has_native():
            nw, nh, nhz = self.cfg.native
        else:
            nw, nh = display.get_current()
            nhz = display.get_native()[2]

        # 原生单独成一组，放最上面
        native_hz = f"  ({nhz}Hz)" if nhz else ""
        self._add_header("原生 · 你的屏幕")
        self.target_combo.addItem(f"{nw} × {nh}{native_hz}   · 原生", "native")

        tw, th = self.cfg.target
        target_in_list = False
        for group, items in groups:
            self._add_header(group)
            for m in items:
                tag = display.tag_for(m.width, m.height)
                label = m.label
                if (m.width, m.height) == (tw, th):
                    target_in_list = True
                if (m.width, m.height) == (nw, nh):
                    label += "   · 原生"
                if tag:
                    label += f"   ★ {tag}"
                self.target_combo.addItem(label, (m.width, m.height))

        # 配置里的档位这块屏没有（换机器/换显示器）：换成这块屏合适的档位
        if not target_in_list:
            fallback = None
            if getattr(self.cfg, "target_auto", True):
                # 自动模式：先按原生分辨率推荐（同比例、不黑边），推荐档不存在才退回 4:3
                rec = display.recommend_target((nw, nh, nhz))
                for _g, items in groups:
                    for m in items:
                        if (m.width, m.height) == rec:
                            fallback = m
                            break
                    if fallback is not None:
                        break
            if fallback is None:
                for group, items in groups:
                    if group == "4:3":
                        starred = [m for m in items if display.tag_for(m.width, m.height)]
                        fallback = starred[0] if starred else items[0]
                        break
            if fallback is not None:
                tw, th = fallback.width, fallback.height
                self.cfg.target = (tw, th)
                self.cfg.save()
                idx = 0
                for i in range(self.target_combo.count()):
                    data = self.target_combo.itemData(i)
                    if isinstance(data, (tuple, list)) and tuple(data) == (tw, th):
                        idx = i
                        break
                self.target_combo.setCurrentIndex(idx)
                self.target_combo.blockSignals(False)
                log.info("目标档位在本机不存在，自动改为 %sx%s", tw, th)
                return

            self._add_header("自定义")
            self.target_combo.addItem(f"{tw} × {th}   · 自定义", (tw, th))

        idx = 0
        for i in range(self.target_combo.count()):
            data = self.target_combo.itemData(i)
            if isinstance(data, (tuple, list)) and tuple(data) == (tw, th):
                idx = i
                break
        self.target_combo.setCurrentIndex(idx)
        self.target_combo.blockSignals(False)

    def _add_header(self, text: str) -> None:
        """下拉里的分组标题（灰色、不可选）。"""
        self.target_combo.addItem(f"── {text} ──", None)
        model = self.target_combo.model()
        item = model.item(self.target_combo.count() - 1)
        if item is not None:
            item.setEnabled(False)

    def _on_target_changed(self, _index: int) -> None:
        data = self.target_combo.currentData()
        if data == "native":
            self.restore_native()
            QTimer.singleShot(0, self._fill_combo)
            return
        if isinstance(data, (tuple, list)) and len(data) == 2:
            self.cfg.target = (int(data[0]), int(data[1]))
            self.cfg.target_auto = False        # 这是你自己挑的，换机器也别再自动改
            self.cfg.save()
            self.refresh_resolution()

    def set_custom_resolution(self) -> None:
        tw, th = self.cfg.target
        text, ok = QtWidgets.QInputDialog.getText(
            self,
            "自定义分辨率",
            "输入「宽x高」，例如 1728x1080：",
            text=f"{tw}x{th}",
        )
        if not ok:
            return
        res = automation.parse_resolution(text)
        if not res:
            self.toast("格式不对，写成 1280x960 这样", False)
            return
        w, h = res
        ok2, code, msg = display.set_resolution(w, h, test_only=True)
        if not ok2:
            QtWidgets.QMessageBox.information(
                self,
                "这个档位切不了",
                f"{w} × {h} 不在显卡/显示器提供的模式里。\n\n"
                "如果确实想要它（比如 1728×1080 这种），去显卡控制面板：\n"
                "N 卡：显示 → 更改分辨率 → 自定义 → 新建；\n"
                "A 卡：显示 → 自定义分辨率。加完再回来点「刷新」，下拉里就有了。",
            )
            return
        self.cfg.target = (w, h)
        self.cfg.target_auto = False
        self.cfg.save()
        self.refresh_resolution()
        self.toast(f"目标档位改为 {w} × {h}，正在切换")
        self.toggle_resolution()

    def _ensure_target_supported(self) -> None:
        """目标档位在本机不存在时自动改成本机支持的档位，避免切了没反应。"""
        try:
            modes = display.list_modes()
            if not modes:
                return
            tw, th = self.cfg.target
            if any(m.width == tw and m.height == th for m in modes):
                return

            pick = None
            if getattr(self.cfg, "target_auto", True):
                # 自动模式：优先同比例（不黑边），而不是无脑塞 4:3
                rec = display.recommend_target(display.detect_native())
                for m in modes:
                    if m.width == rec[0] and m.height == rec[1]:
                        pick = m
                        break
            if pick is None:
                # 没走自动推荐（用户自己定过档位）：按目标比例 + 不超过目标尺寸就近找，
                # 绝不硬塞一个比目标更大的 4:3 档
                target_ratio = tw / th if th else 1.0
                within = [m for m in modes if m.width <= tw and m.height <= th]
                if within:
                    pick = min(
                        within,
                        key=lambda m: (
                            abs((m.width / m.height) - target_ratio),
                            -m.width,
                        ),
                    )
                else:
                    pick = min(
                        modes,
                        key=lambda m: (
                            abs((m.width / m.height) - target_ratio),
                            abs(m.width - tw),
                        ),
                    )

            self.cfg.target = (pick.width, pick.height)
            self.cfg.save()
            log.info("目标档位自动适配：%sx%s -> %sx%s", tw, th, pick.width, pick.height)
            self.refresh_resolution()
            self.toast(
                f"本机没有 {tw}×{th}，按你的比例就近改成 {pick.width}×{pick.height}", True
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("目标档位自检失败：%r", exc)

    def refresh_resolution(self) -> None:
        self._fill_combo()
        w, h = display.get_current()
        self.cur_label.setText(f"{w} × {h}")
        self.ratio_chip.setText(ratio_text(w, h))

        if not self.cfg.has_native():
            self.cfg.set_native(*display.detect_native())

        nw, nh, _ = self.cfg.native
        self.native_hint.setText(f"原生基准  {nw} × {nh}")

        tw, th = self.cfg.target
        at_target = (w, h) == (tw, th)
        at_native = self.cfg.has_native() and (w, h) == (nw, nh)

        # 一键回原生：无论当前在哪一档都能点
        self.restore_btn.setEnabled(self.cfg.has_native() and not at_native)
        if at_native:
            self.restore_btn.setText("✓ 已在原生")
            self.restore_btn.setToolTip(f"当前就是原生 {nw} × {nh}，不需要再切")
        else:
            self.restore_btn.setText(f"回到原生  {nw}×{nh}")
            self.restore_btn.setToolTip(f"一键回到原生 {nw} × {nh}")

        if at_target:
            self.toggle_btn.setText("切回原生")
            self.toggle_btn.setToolTip(f"当前已在目标档，点一下回到原生 {nw} × {nh}（Ctrl+Alt+R）")
            self.ratio_chip.setStyleSheet(
                "color:#20ffe0; background:#102a27; border:1px solid #1c4a43;"
                "border-radius:6px; padding:2px 8px; font-size:11px;"
            )
        else:
            ratio = display.ratio_group(tw, th)
            self.toggle_btn.setText(f"切换为 {ratio}")
            self.toggle_btn.setToolTip(f"切换到 {tw} × {th}（{ratio}）　Ctrl+Alt+R")
            self.ratio_chip.setStyleSheet(
                "color:#9aa4b4; background:#1a1f29; border:1px solid #2a3240;"
                "border-radius:6px; padding:2px 8px; font-size:11px;"
            )

        self._ensure_on_screen()

        self._refresh_scaling_state()

    # ------------------------------------------------------------------
    # 嘉豪模式（4:3 拉满去黑边）
    # ------------------------------------------------------------------
    def _on_stretch_toggled(self, checked: bool) -> None:
        self.set_stretch(checked)

    def set_stretch(self, checked: bool, silent: bool = False) -> None:
        self.cfg.stretch = checked
        self.cfg.save()
        self.stretch_chk.blockSignals(True)
        self.stretch_chk.setChecked(checked)
        self.stretch_chk.blockSignals(False)
        self._refresh_scaling_state()
        if checked and not scaling.is_stretched() and not silent:
            self._stretch_help()

    def _refresh_scaling_state(self) -> None:
        st = scaling.get_state()
        code = st.get("code") or 0
        tech = st.get("tech_name") or ""
        hz = st.get("hz") or 0.0
        port = f"{tech} {hz:.0f}Hz" if hz and tech else tech
        tip = scaling.advice(st)
        if tip:
            self.stretch_state.setToolTip(tip)
            self.stretch_link.setToolTip(tip)

        w, h = display.get_current()
        nw, nh, _ = self.cfg.native
        at_native = self.cfg.has_native() and (w, h) == (nw, nh)

        short = {
            scaling.SCALING_IDENTITY: "四周有黑边（1:1）",
            scaling.SCALING_CENTERED: "四周有黑边（居中）",
            scaling.SCALING_ASPECTRATIOCENTEREDMAX: "左右有黑边",
            scaling.SCALING_CUSTOM: "自定义缩放",
            scaling.SCALING_PREFERRED: "驱动默认缩放",
        }
        tail = f"　{port}" if port else ""

        if at_native:
            self.stretch_state.setText("当前：原生档，不用拉伸" + tail)
            self.stretch_state.setStyleSheet("color:#7b8494; font-size:11px;")
        elif code == scaling.SCALING_STRETCHED:
            self.stretch_state.setText("当前：拉伸铺满 · 无黑边" + tail)
            self.stretch_state.setStyleSheet("color:#20ffe0; font-size:11px;")
        elif code == 0:
            self.stretch_state.setText("当前：读不到缩放状态")
            self.stretch_state.setStyleSheet("color:#7b8494; font-size:11px;")
        else:
            label = short.get(code) or (st.get("desc") or "")
            self.stretch_state.setText("当前：" + label + tail)
            self.stretch_state.setStyleSheet("color:#d9a441; font-size:11px;")

        # 多屏：给一个下拉挑作用屏；只有一块屏时整行藏起来
        self._sync_screen_row()

    def _sync_screen_row(self) -> None:
        try:
            screens = display.list_displays()
        except Exception:  # noqa: BLE001
            screens = []
        if len(screens) <= 1:
            self.screen_row.setVisible(False)
            return

        self.screen_row.setVisible(True)
        cur = (self.cfg.screen_device or "").strip()
        self.screen_combo.blockSignals(True)
        self.screen_combo.clear()
        self.screen_combo.addItem("主屏（默认）", "")
        for sc in screens:
            if sc.get("primary"):
                continue
            self.screen_combo.addItem(sc.get("label") or sc.get("device"), sc.get("device"))
        idx = self.screen_combo.findData(cur)
        self.screen_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.screen_combo.blockSignals(False)
        self.screen_hint.setText("切档只动这一块，别的屏不动")

    def _on_screen_change(self, _index: int) -> None:
        dev = (self.screen_combo.currentData() or "").strip()
        if dev == (self.cfg.screen_device or ""):
            return
        self.cfg.screen_device = dev
        display.set_target(dev or None)
        # 换了屏，原生基准跟着换（每块屏的原生不一样）
        self.cfg.native = display.detect_native()
        self.cfg.save()
        self.refresh_resolution()
        name = self.screen_combo.currentText() or "主屏"
        self.toast(f"作用屏幕：{name} · 原生 {self.cfg.native[0]}×{self.cfg.native[1]}")

    def _on_vendor_change(self, _index: int) -> None:
        self.cfg.gpu_vendor = self.vendor_combo.currentData() or "auto"
        self.cfg.save()

    def open_scaling_panel(self) -> None:
        name, steps = scaling.open_driver_panel(self.cfg.gpu_vendor)
        self.toast(f"已打开{name} —— {steps}")

    def _stretch_help(self) -> None:
        vendor = self.cfg.gpu_vendor or "auto"
        if vendor == "auto":
            vendor = scaling.detect_vendor()
        steps = scaling.STEPS.get(vendor, scaling.STEPS["auto"])
        detail = scaling.HELP_DETAIL.get(vendor, scaling.STEPS["auto"])
        vendor_name = {
            "nvidia": "NVIDIA（3060 这类）",
            "amd": "AMD",
            "intel": "Intel",
        }.get(vendor, "你的显卡")

        guess = ""
        try:
            guess = scaling.advice(scaling.get_state())
        except Exception:  # noqa: BLE001
            guess = ""

        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("还差一步：让显卡拉伸")
        box.setText(
            (f"【这台的情况】{guess}\n\n" if guess else "")
            + "「嘉豪模式」已经打开，但去黑边这一步是显卡管的，程序改不了。\n\n"
            + f"你的显卡：{vendor_name}\n{detail}\n\n"
            "这里点一次是全局持久的，以后切分辨率自动拉满，不用再管。\n"
            "如果打开的面板不对（笔记本双显卡常见），把旁边的「显卡：自动」换成另一家。"
        )
        go = box.addButton("打开显卡设置", QtWidgets.QMessageBox.ActionRole)
        box.addButton("知道了", QtWidgets.QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is go:
            self.open_scaling_panel()

    # ------------------------------------------------------------ 换电脑识别
    def _identify_machine(self) -> None:
        """每次启动认一遍：这是不是没见过的电脑 / 没见过的显示器。

        - 第一次运行（或配置里没记过原生）：按本机实际支持的最大模式记录原生
        - 认出新机器：把原生基准换成这台电脑的，但**不动当前分辨率**
        """
        try:
            det = display.detect_native()
        except Exception:
            return
        if det[0] <= 0 or det[1] <= 0:
            return

        tag = display.machine_tag()
        old_tag = (getattr(self.cfg, "machine_tag", "") or "").strip()
        self.cfg.machine_tag = tag

        if not self.cfg.has_native():
            self.cfg.set_native(*det)
            rec = (0, 0)
            if getattr(self.cfg, "target_auto", True):
                rec = display.recommend_target(det)
                if rec[0] > 0:
                    self.cfg.target = rec
                    self.cfg.target_auto = True
            self.cfg.save()
            log.info(
                "首次运行：本机原生 %sx%s（显示器 %s），目标档位 %s",
                det[0], det[1], tag, self.cfg.target,
            )
            if rec[0] > 0:
                note = display.recommend_note(det, rec)
                QTimer.singleShot(700, lambda: self.toast("首次运行：" + note))
            # 当前分辨率跟面板最大对不上时，别默默按面板最大记，问一次
            try:
                cur = display.get_current()
            except Exception:
                cur = (0, 0)
            if cur[0] > 0 and (cur[0], cur[1]) != (det[0], det[1]):
                log.info("首次运行：当前 %sx%s 与面板最大 %sx%s 不一致，等用户确认基准",
                         cur[0], cur[1], det[0], det[1])
                QTimer.singleShot(
                    1500,
                    lambda: self._ask_first_native_later(det, cur),
                )
            return

        nw, nh, _nhz = self.cfg.native
        first_time_on_new = bool(old_tag) and old_tag != tag
        size_differs = (nw, nh) != (det[0], det[1])
        if first_time_on_new or size_differs:
            self.cfg.set_native(*det)
            log.info("认出新显示器 %s：原生基准 %sx%s -> %sx%s，当前分辨率没动",
                     tag, nw, nh, det[0], det[1])
            QTimer.singleShot(
                900,
                lambda: self.toast(
                    f"认出新显示器：原生基准改为 {det[0]} × {det[1]}（当前分辨率没动）"
                ),
            )
        else:
            self.cfg.save()

    def _ask_first_native_later(self, det, cur, tries: int = 0) -> None:
        """等新手引导关掉再问，别叠两个框。"""
        if getattr(self, "_guide_busy", False) and tries < 40:
            QTimer.singleShot(
                1200, lambda: self._ask_first_native_later(det, cur, tries + 1)
            )
            return
        self._ask_first_native(det, cur)

    def _ask_first_native(self, det, cur) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("确认「原生」基准")
        box.setIcon(QtWidgets.QMessageBox.Question)
        box.setText(
            f"你现在用的是 {cur[0]} × {cur[1]}，这块屏最大支持 {det[0]} × {det[1]}。\n\n"
            "「原生」是切完分辨率后按 Ctrl+Alt+R 要回到的地方，记错了回去的就是错的分辨率。\n"
            "这次按哪个记？"
        )
        b_big = box.addButton(
            f"面板最大 {det[0]} × {det[1]}（推荐）", QtWidgets.QMessageBox.AcceptRole
        )
        b_cur = box.addButton(
            f"就用当前 {cur[0]} × {cur[1]}", QtWidgets.QMessageBox.ActionRole
        )
        box.setDefaultButton(b_big)
        box.exec()
        hit = box.clickedButton()

        if hit is b_cur:
            self.cfg.set_native(cur[0], cur[1])
            try:
                rec = display.recommend_target((cur[0], cur[1], 0))
                if rec[0] > 0:
                    self.cfg.target = rec
                    self.cfg.target_auto = True
            except Exception:
                pass
            self.cfg.save()
            self.native_hint.setText(f"原生基准  {cur[0]} × {cur[1]}")
            self.toast(f"已按你的选择记：原生 {cur[0]} × {cur[1]}")
            log.info("首次运行：用户选了当前分辨率 %sx%s 作为原生", cur[0], cur[1])
            QTimer.singleShot(600, self.refresh_resolution)
        else:
            self.toast(f"原生基准 = 面板最大 {det[0]} × {det[1]}")
            log.info("首次运行：用户确认面板最大 %sx%s 作为原生", det[0], det[1])

    def reidentify_machine(self) -> None:
        """手动重新识别（换了显示器或调过缩放之后用）。"""
        det = display.detect_native()
        self.cfg.set_native(*det)
        self.cfg.machine_tag = display.machine_tag()
        self.cfg.save()
        self.refresh_resolution()
        self.toast(f"已按本机重新识别：原生 {det[0]} × {det[1]}" + (f" @ {det[2]}Hz" if det[2] else ""))

    # ------------------------------------------------------------ 系统监控
    def _on_sysmon(self, data: dict) -> None:
        # 手机页面读同一份缓存，别各自去调 snapshot —— 会把采样基线冲掉，CPU 一直是 0
        self.sysmon_last = dict(data)

        def put(key: str, text: str, percent) -> None:
            item = self.stat_widgets.get(key)
            if not item:
                return
            val_lbl, bar = item
            val_lbl.setText(text)
            if percent is None:
                bar.setValue(0)
                val_lbl.setObjectName("StatValue")
            else:
                bar.setValue(int(max(0, min(100, percent))))
                val_lbl.setObjectName("StatValueWarn" if percent >= 85 else "StatValue")
            val_lbl.style().unpolish(val_lbl)
            val_lbl.style().polish(val_lbl)

        cpu = data.get("cpu")
        put("cpu", "--" if cpu is None else f"{cpu:.0f}%", cpu)

        mem = data.get("mem")
        used = data.get("mem_used")
        total = data.get("mem_total")
        if mem is None:
            put("mem", "--", None)
        elif used is not None and total is not None:
            put("mem", f"{mem:.0f}% · {used:.1f}/{total:.0f}G", mem)
        else:
            put("mem", f"{mem:.0f}%", mem)

        gpu = data.get("gpu")
        gmu = data.get("gpu_mem")
        gmt = data.get("gpu_mem_total")
        if gpu is None:
            put("gpu", "--", None)
        elif gmu is not None and gmt is not None:
            put("gpu", f"{gpu:.0f}% · {gmu:.1f}/{gmt:.0f}G", gpu)
        else:
            put("gpu", f"{gpu:.0f}%", gpu)

        temp = data.get("temp")
        put("temp", "--" if temp is None else f"{temp:.0f} ℃", None if temp is None else min(100, temp / 1.0))

    def _ensure_on_screen(self) -> None:
        scr = self.screen() or QtGui.QGuiApplication.primaryScreen()
        if scr is None:
            return
        geo = scr.availableGeometry()
        g = self.geometry()
        x = min(max(g.x(), geo.left()), geo.right() - g.width())
        y = min(max(g.y(), geo.top()), geo.bottom() - g.height())
        if (x, y) != (g.x(), g.y()):
            self.move(x, y)

    def toggle_resolution(self) -> None:
        w, h = display.get_current()
        if not self.cfg.has_native():
            self.cfg.set_native(*display.detect_native())

        tw, th = self.cfg.target
        if (w, h) == (tw, th):
            nw, nh, nhz = self.cfg.native
            ok, code, msg = display.set_resolution(nw, nh)
            target_desc = f"{nw} × {nh}"
        else:
            ok, code, msg = display.set_resolution(tw, th)
            target_desc = f"{tw} × {th}"

        if ok:
            self.toast(f"已切换到 {target_desc}")
            log.info("分辨率切换成功 -> %s", target_desc)
            if self.tray is not None and not self.isVisible():
                self.tray.showMessage(
                    APP_NAME,
                    f"已切换到 {target_desc}",
                    QtWidgets.QSystemTrayIcon.Information,
                    2000,
                )
        else:
            self.toast(f"切换失败：{msg}", False)
            log.warning("分辨率切换失败 %s code=%s %s", target_desc, code, msg)
            if code == display.DISP_CHANGE_BADMODE:
                QtWidgets.QMessageBox.warning(
                    self,
                    "这个模式不支持",
                    f"显卡/显示器不提供 {target_desc} 这个模式。\n\n"
                    "请在上面的「目标档位」里换一个下拉选项（程序只列出真实支持的模式）。",
                )
        QTimer.singleShot(900, self.refresh_resolution)

    def restore_native(self) -> None:
        nw, nh, _ = self.cfg.native
        if not self.cfg.has_native():
            self.toast("还没有记录原生分辨率", False)
            return
        ok, code, msg = display.set_resolution(nw, nh)
        if ok:
            self.toast(f"已恢复原生 {nw} × {nh}")
        else:
            self.toast(f"恢复失败：{msg}", False)
        QTimer.singleShot(900, self.refresh_resolution)

    # ------------------------------------------------------------ 全还原
    def panic_restore(self, confirm: bool = True) -> None:
        """出任何异常先点这个：把常用开关一次退回默认。

        顺序是"先救数据再还原"——正在录的屏会先正常收尾保存，不会留个坏文件。
        """
        recording = bool(getattr(self.recorder, "is_recording", False))
        if confirm:
            head = "会把下面这些退回默认：\n\n"
            body = "· 分辨率 → 原生\n· 反作弊优化还原（并关掉自动守护）\n" \
                   "· 帧率悬浮窗 → 关\n· 回放缓冲 → 关\n· 每日密码悬浮窗 → 关"
            if recording:
                body += "\n· 正在录的屏 → 先保存再停"
            box = QtWidgets.QMessageBox(
                self if self.isVisible() else None
            )
            box.setWindowTitle("全部还原")
            box.setIcon(QtWidgets.QMessageBox.Question)
            box.setText(head + body + "\n\n继续吗？")
            box.setStandardButtons(
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
            )
            box.setDefaultButton(QtWidgets.QMessageBox.No)
            if box.exec() != QtWidgets.QMessageBox.Yes:
                return

        done: list = []
        failed: list = []

        # 1) 录屏：先收尾保存
        if getattr(self.recorder, "is_recording", False):
            try:
                path = self.recorder.stop()
                try:
                    self.rec_btn.setText("开始录屏")
                except Exception:
                    pass
                done.append("录像已保存 " + path.name if path else "录屏已停止")
            except Exception as exc:  # noqa: BLE001
                failed.append(f"录屏：{exc}")

        # 2) 回放缓冲
        try:
            if getattr(self.replay, "is_running", False):
                self.replay.stop()
                try:
                    self.replay_btn.setText("回放")
                except Exception:
                    pass
                done.append("回放缓冲已关")
        except Exception as exc:  # noqa: BLE001
            failed.append(f"回放：{exc}")

        # 3) 帧率悬浮窗
        if getattr(self.cfg, "fps_show", False):
            try:
                self.set_fps_enabled(False)
                done.append("帧率灯已关")
            except Exception as exc:  # noqa: BLE001
                failed.append(f"帧率灯：{exc}")

        # 4) 每日密码悬浮窗
        if getattr(self.cfg, "hud_show", False):
            try:
                self.set_hud_enabled(False)
                done.append("密码悬浮窗已关")
            except Exception as exc:  # noqa: BLE001
                failed.append(f"悬浮窗：{exc}")

        # 5) ACE：恢复优先级 + 关自动守护
        try:
            if getattr(self.cfg, "ace_guard", False):
                self.cfg.ace_guard = False
                self.cfg.save()
                chk = getattr(self, "ace_guard_chk", None)
                if chk is not None:
                    chk.blockSignals(True)
                    chk.setChecked(False)
                    chk.blockSignals(False)
            ok, total = ace.restore_all()
            if total:
                done.append(f"反作弊优化已还原 {ok}/{total}")
            self._ace_refresh_state()
        except Exception as exc:  # noqa: BLE001
            failed.append(f"反作弊优化：{exc}")

        # 6) 分辨率回原生（已经在原生就跳过）
        try:
            nw, nh, _ = self.cfg.native
            if self.cfg.has_native() and display.get_current() != (nw, nh):
                ok, _code, msg = display.set_resolution(nw, nh)
                if ok:
                    done.append(f"已回原生 {nw} × {nh}")
                else:
                    failed.append(f"分辨率：{msg}")
            QTimer.singleShot(900, self.refresh_resolution)
        except Exception as exc:  # noqa: BLE001
            failed.append(f"分辨率：{exc}")

        # 7) 显示器滤镜：曲线回默认（本来没启用就不算）
        try:
            was = any(screenfilter.is_active(d) for d in screenfilter.devices())
            screenfilter.restore_all()
            if was:
                done.append("显示器滤镜已还原")
            fw = getattr(self, "filter_win", None)
            if fw is not None:
                fw._refresh_state()
        except Exception as exc:  # noqa: BLE001
            failed.append(f"显示器滤镜：{exc}")

        if failed:
            msg = "；".join(done + ["失败 " + f for f in failed])
            self.toast("还原未全成功：" + "；".join(failed)[:70], False)
        else:
            msg = "已全部还原：" + ("、".join(done) if done else "本来就在默认状态")
            self.toast(msg)

        tray = getattr(self, "tray", None)
        if tray is not None:
            tray.showMessage(APP_NAME, msg, QtWidgets.QSystemTrayIcon.Information, 4000)
        log.info("panic 全还原：%s", msg)

    def _show_more_menu(self) -> None:
        """低频操作从这里弹出来，不占卡片行数。"""
        p = self.more_btn.mapToGlobal(QtCore.QPoint(0, self.more_btn.height() + 2))
        self.more_menu.exec(p)

    def _link_dot_qss(self, on: bool) -> str:
        if on:
            return (
                "background:#20ffe0;border:1px solid rgba(32,255,224,.85);"
                "border-radius:4px;"
            )
        return (
            "background:rgba(255,255,255,.05);border:1px solid #6f7a8c;"
            "border-radius:4px;"
        )

    def _link_card(self):
        """这页自己带着工具卡，老代码里也留了 win 那条路径，两个都认。"""
        card = getattr(self, "tools_card", None)
        if card is None:
            card = getattr(getattr(self, "win", None), "tools_card", None)
        return card

    def _fit_cast_tile(self) -> None:
        """投屏方块和右边那列同尺寸，顶边压到 CPU 这一行的顶。"""
        h = 72
        if self.tile_cast is None:
            return
        try:
            self.tile_cast.setFixedSize(72, h)
            self.tile_cast.icon.setPixmap(
                _tile_pixmap("cast", color=_accent_color(), size=int(h * 0.42))
            )
        except Exception:  # noqa: BLE001
            pass

    def _wire_link_dot(self) -> None:
        """把「连接手机」上的小点接上局域网桥的连接信号。"""
        lan = getattr(self._link_card(), "lan", None)
        if lan is None or not hasattr(lan, "link"):
            try:
                self.link_dot.hide()
            except Exception:  # noqa: BLE001
                pass
            return
        lan.link.connect(self._on_link_state)
        info = lan.link_info() if hasattr(lan, "link_info") else (False, "")
        self._on_link_state(*info)

    def _on_link_state(self, on: bool, who: str = "") -> None:
        dot = getattr(self, "link_dot", None)
        if dot is None:
            return
        dot.setStyleSheet(self._link_dot_qss(bool(on)))
        card = self._link_card()
        if card is not None:
            card._link_on = bool(on)
            card._link_who = who or ""
            try:
                card._sync_clip()
            except Exception:  # noqa: BLE001
                pass

    def open_clip_from_home(self) -> None:
        """主页那个「剪贴板」方块：借工具卡里的二维码弹窗。"""
        self.tools_card.open_clip()

    # ---------------------------------------------------------------- 投屏
    # 进程必须挂在主窗口身上：挂在对话框上，对话框一销毁 Qt 就会在
    # 析构里把 scrcpy 杀掉并同步等它退出 —— 界面上就是卡死、闪退。
    cast_proc = None
    cast_dialog = None

    def cast_running(self) -> bool:
        p = getattr(self, "cast_proc", None)
        if p is None:
            return False
        try:
            return p.state() != QtCore.QProcess.NotRunning
        except Exception:  # noqa: BLE001
            return False

    def start_cast(self, serial: str, quality: str):
        if self.cast_running():
            self.toast("投屏窗口已经开着，先点「结束投屏」再开新的")
            return self.cast_proc
        p = scrcpy_tool.start(serial, quality)
        p.setParent(self)
        p.finished.connect(self._cast_exited)
        p.errorOccurred.connect(self._cast_err)
        self.cast_proc = p
        self._refresh_cast_tile()
        return p

    def stop_cast(self, quiet: bool = False) -> bool:
        """关投屏：先 terminate，1.6 秒还没退就 kill。全程不等，界面不卡。"""
        p = getattr(self, "cast_proc", None)
        if p is None:
            return False
        try:
            if p.state() == QtCore.QProcess.NotRunning:
                self.cast_proc = None
                self._refresh_cast_tile()
                return False
            p.terminate()
        except Exception:  # noqa: BLE001
            self.cast_proc = None
            self._refresh_cast_tile()
            return False
        QTimer.singleShot(1600, self._cast_kill_if_alive)
        if not quiet:
            self.toast("正在结束投屏…")
        return True

    def _cast_kill_if_alive(self) -> None:
        p = getattr(self, "cast_proc", None)
        if p is None:
            return
        try:
            if p.state() != QtCore.QProcess.NotRunning:
                p.kill()
        except Exception:  # noqa: BLE001
            pass

    def _cast_err(self, *_a) -> None:
        err = ""
        try:
            p = getattr(self, "cast_proc", None)
            if p is not None:
                err = bytes(p.readAllStandardError()).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            err = ""
        self.toast("scrcpy 起不来：" + scrcpy_tool.explain(err), False)

    def _cast_exited(self, code: int = 0, _status=None) -> None:
        err = ""
        try:
            p = getattr(self, "cast_proc", None)
            if p is not None:
                err = bytes(p.readAllStandardError()).decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            err = ""
        self.cast_proc = None
        self._refresh_cast_tile()
        if code == 0 and not (err or "").strip():
            self.toast("投屏窗口已关闭")
        else:
            self.toast("投屏断开了：" + scrcpy_tool.explain(err), False)
        d = getattr(self, "cast_dialog", None)
        if d is not None:
            try:
                d.start_btn.setText("开始投屏")
                d.start_btn.setEnabled(True)
                d.refresh()
            except RuntimeError:
                self.cast_dialog = None

    def _cast_shutdown(self) -> None:
        """退出前真把投屏收掉，且最多等 0.8 秒，绝不拖住关闭流程。"""
        p = getattr(self, "cast_proc", None)
        self.cast_proc = None
        if p is None:
            return
        try:
            p.terminate()
            if not p.waitForFinished(400):
                p.kill()
                p.waitForFinished(400)
        except Exception:  # noqa: BLE001
            pass

    def _refresh_cast_tile(self) -> None:
        """主页那块「手机投屏」在投屏时改叫「投屏中」，一眼看得出还连着。"""
        try:
            on = self.cast_running()
            cap = getattr(self.tile_cast, "caption", None)
            if cap is not None:
                cap.setText("投屏中" if on else "手机投屏")
                cap.setStyleSheet(
                    "background:transparent;border:none;color:%s;"
                    "font-size:11.5px;font-weight:600;"
                    % (_accent_color() if on else _fg1_color())
                )
        except Exception:  # noqa: BLE001
            pass

    def open_share_dialog(self) -> None:
        ShareDialog(self).exec()

    def open_scrcpy_dialog(self) -> None:
        d = getattr(self, "cast_dialog", None)
        if d is not None:
            try:
                d.refresh()
                d.show()
                d.raise_()
                d.activateWindow()
                return
            except RuntimeError:
                self.cast_dialog = None
        d = ScrcpyDialog(self)
        self.cast_dialog = d
        d.show()

    def change_recv_dir(self) -> bool:
        """选一个文件夹当「手机传来的东西」的落点。改完立刻生效，并记进配置。"""
        cur = self.tools_card.lan.recv_root
        path = QtWidgets.QFileDialog.getExistingDirectory(
            self, "手机传来的文件存到哪", str(cur)
        )
        if not path:
            return False
        self.cfg.recv_dir = path
        try:
            self.cfg.save()
        except Exception:  # noqa: BLE001
            pass
        self.toast("以后手机传上来的文件都存这：" + path)
        return True

    def mark_native(self) -> None:
        w, h = display.get_current()
        self.cfg.set_native(w, h)
        self.native_hint.setText(f"原生基准  {w} × {h}")
        self.toast(f"已把 {w} × {h} 记为原生基准")
        QTimer.singleShot(300, self.refresh_resolution)

    # ------------------------------------------------------------------
    # 杂项
    # ------------------------------------------------------------------
    # ---------- 壁纸 ----------
    def _build_art(self) -> None:
        """壁纸就一层：铺满整窗最底下，不接鼠标事件。"""
        self.art = ArtLayer(self)
        self.art.setObjectName("Art")
        self.art.hide()
        self._art_timer = QTimer(self)
        self._art_timer.setSingleShot(True)
        self._art_timer.setInterval(120)
        self._art_timer.timeout.connect(self.refresh_art)

    def art_path(self):
        return artwork.resolve(getattr(self.cfg, "art_file", "") or "")

    def refresh_art(self) -> None:
        """读图、摆位置；开关一变顺手把卡片透明度调一下。"""
        want = bool(getattr(self.cfg, "art_show", False))
        path = self.art_path()
        blur = max(0, int(getattr(self.cfg, "art_blur", 18) or 0)) if _glass_on else 0
        pm = None
        if want and path is not None:
            key = (str(path), self.width(), self.height(), blur)
            if getattr(self, "_art_key", None) == key and getattr(self, "_art_pm", None):
                pm = self._art_pm
            else:
                pm = artwork.load(
                    path,
                    artwork.target_size(self.width(), self.height()),
                    tint=theme.current().value("bg-page", "#0e1015"),
                    blur=blur,
                )
                self._art_key = key
                self._art_pm = pm

        if pm is None:
            self.art.clear()
            self.art.hide()
            on = False
        else:
            self.art.setPixmap(pm)
            self.art.resize(pm.size())
            self.art.move(0, 0)
            self.art.show()
            self.art.lower()
            on = True

        if self._art_tinted != on:
            self._art_tinted = on
            self._sync_overrides()
        self._sync_art_mask()

    # ---------- 游戏模式 ----------
    def _gm_powercfg(self, *args) -> Tuple[bool, str]:
        """跑一条 powercfg，返回 (成功没有, 输出)。失败一律吞掉，不打扰别的。"""
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        try:
            r = subprocess.run(
                ["powercfg", *[str(a) for a in args]],
                capture_output=True,
                timeout=5,
                startupinfo=si,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
            raw = (r.stdout or b"") + (r.stderr or b"")
            try:
                text = raw.decode("utf-8")
            except Exception:  # noqa: BLE001
                text = raw.decode("gbk", "ignore")
            return r.returncode == 0, text
        except Exception:  # noqa: BLE001
            return False, ""

    def _gm_active_plan(self) -> str:
        ok, text = self._gm_powercfg("/getactivescheme")
        if not ok:
            return ""
        m = re.search(
            r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})",
            text,
        )
        return m.group(1) if m else ""

    def _gm_set_plan(self, guid: str) -> bool:
        if not guid:
            return False
        return self._gm_powercfg("/setactive", guid)[0]

    def set_game_mode(self, on: bool) -> None:
        """游戏模式：只动自己的东西 —— 壁纸、采集频率、系统电源计划。

        刻意不碰游戏进程（不改优先级、不改亲和性、不做注入），
        反作弊那边我们完全是个旁观者。
        """
        on = bool(on)
        self._gm_on = on
        self._gm_brand_switch(on)
        btn = getattr(self, "gm_btn", None)
        if btn is not None and btn.isChecked() != on:
            btn.blockSignals(True)
            btn.setChecked(on)
            btn.blockSignals(False)
        notes = []
        if on:
            if getattr(self, "_gm_art", None) is None:
                self._gm_art = bool(getattr(self.cfg, "art_show", False))
            if getattr(self.cfg, "art_show", False):
                self.cfg.art_show = False
                try:
                    self.refresh_art()
                except Exception:  # noqa: BLE001
                    pass
                notes.append("壁纸收起")
            mon = getattr(self, "sysmon", None)
            if mon is not None:
                if getattr(self, "_gm_int", None) is None:
                    self._gm_int = int(mon.timer.interval() or 2500)
                if mon.timer.interval() < 5000:
                    mon.timer.setInterval(6000)
                    notes.append("采集降到 6 秒")
            plan = self._gm_active_plan()
            if plan:
                self._gm_plan = plan
                high = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"  # 高性能
                if plan.lower() != high and self._gm_set_plan(high):
                    notes.append("已切高性能电源")
            self.toast("游戏模式已开：" + ("、".join(notes) if notes else "这台机器没什么好省的"))
        else:
            self._gm_restore()
            self.toast("游戏模式已关，壁纸、采集频率、电源计划都放回去了")
        self._gm_flash(on)
        btn = getattr(self, "gm_btn", None)
        if btn is not None and btn.isChecked() != on:
            btn.blockSignals(True)
            btn.setChecked(on)
            btn.blockSignals(False)

    def _gm_brand_switch(self, on: bool) -> None:
        """游戏模式开着时左上角换成金属「燧镜」+ GAME MODE 小红牌，关掉就切回来。"""
        t = getattr(self, "brand_title", None)
        tag = getattr(self, "gm_tag", None)
        if t is not None:
            try:
                if on:
                    # 通电感：字从白过渡到青色（横向渐变），字距拉开一点
                    t.setStyleSheet(
                        "color: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
                        " stop:0 #ffffff, stop:0.35 #b7fff4, stop:1 #25ffe2);"
                        "letter-spacing: 2.2px; font-weight: 800;"
                    )
                else:
                    t.setStyleSheet("")
            except Exception:  # noqa: BLE001
                pass
        if tag is not None:
            try:
                tag.setVisible(bool(on))
            except Exception:  # noqa: BLE001
                pass

    def _gm_flash(self, on: bool) -> None:
        """在音乐灵动岛那块位置闪一下「游戏模式已开启 / 已关闭」。"""
        try:
            self.mode_island.flash(on)
        except Exception:  # noqa: BLE001
            pass

    def _gm_restore(self) -> None:
        """把游戏模式动过的东西一件件放回去。退出程序时也会走一次。"""
        art = getattr(self, "_gm_art", None)
        if art is not None:
            self._gm_art = None
            self.cfg.art_show = bool(art)
            try:
                self.refresh_art()
            except Exception:  # noqa: BLE001
                pass
            try:
                self.cfg.save()
            except Exception:  # noqa: BLE001
                pass
        interval = getattr(self, "_gm_int", None)
        if interval is not None:
            self._gm_int = None
            mon = getattr(self, "sysmon", None)
            if mon is not None:
                try:
                    mon.timer.setInterval(int(interval))
                except Exception:  # noqa: BLE001
                    pass
        plan = getattr(self, "_gm_plan", None)
        if plan:
            self._gm_plan = None
            self._gm_set_plan(plan)
        self._gm_on = False
        self._gm_brand_switch(False)

    def _apply_text_shadow(self, on: bool) -> None:
        """液态玻璃下给文字加一层暗衬。

        卡片透到 0.50 之后，光靠底色压不住壁纸的亮部，给字加一道
        四周均匀的黑色柔光，既不改布局也不变形，像字幕那种衬边。
        """
        for lb in self.findChildren(QtWidgets.QLabel):
            try:
                if on:
                    if lb.graphicsEffect() is not None:
                        continue
                    eff = QtWidgets.QGraphicsDropShadowEffect(lb)
                    eff.setBlurRadius(13)
                    eff.setOffset(0, 0)
                    eff.setColor(QtGui.QColor(0, 0, 0, 180))
                    lb.setGraphicsEffect(eff)
                elif lb.graphicsEffect() is not None:
                    lb.setGraphicsEffect(None)
            except Exception:  # noqa: BLE001
                pass

    def _sync_overrides(self) -> None:
        d = {}
        if getattr(self, "_art_tinted", False):
            d.update(_art_overrides())
        if _glass_on:
            d.update(_glass_overrides())
        if _liquid_on:
            # 液态玻璃的圆角更大一圈，厚一点才像玻璃
            d.update({
                "radius-xl": "28",
                "radius-lg": "24",
                "radius-sm": "12",
                "radius-btn": "12",
            })
        theme.set_overrides(d)
        apply_theme()
        # 卡片背景是按 [glass=true] / [liquid=true] 选的样式，换皮后要重新
        # 挂一遍属性并 polish，不然新样式只对新建的卡片生效
        try:
            for w in self.findChildren(QtWidgets.QFrame):
                if w.objectName() in ("ModCard", "ModTile"):
                    w.setProperty("glass", bool(_glass_on))
                    w.setProperty("liquid", bool(_liquid_on))
                    w.style().unpolish(w)
                    w.style().polish(w)
                    w.update()
        except Exception:  # noqa: BLE001
            pass

    # --------------------------------------------------------------- 硬件规格

    def toggle_spec(self) -> None:
        show = not self.spec_body.isVisible()
        self.spec_body.setVisible(show)
        self.spec_btn.setText("收起" if show else "展开")
        if show and not getattr(self, "_spec_data", None):
            self.spec_sum.setText("正在读取硬件信息，第一次要几秒…")
            self._load_spec()

    def _load_spec(self) -> None:
        th = getattr(self, "_spec_thread", None)
        if th is not None and th.isRunning():
            return
        th = _SpecWorker(self)
        th.done.connect(self._on_spec)
        self._spec_thread = th
        th.start()

    def _on_spec(self, d: dict) -> None:
        self._spec_data = d or {}
        if not d:
            self.spec_sum.setText("读不到这台机器的规格（WMI 被禁或权限不足）")
            return
        self.spec_sum.setText(_spec_headline(d))
        self._fill_spec(d)

    def _fill_spec(self, d: dict) -> None:
        g = self._spec_grid
        while g.count():
            it = g.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        for i, (k, v) in enumerate(_spec_rows(d)):
            lab = QtWidgets.QLabel(k)
            lab.setObjectName("Hint")
            lab.setFixedWidth(58)
            val = QtWidgets.QLabel(v)
            val.setObjectName("Small")
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextSelectableByMouse)
            g.addWidget(lab, i, 0, Qt.AlignTop)
            g.addWidget(val, i, 1)

    def copy_spec(self) -> None:
        d = getattr(self, "_spec_data", None)
        if not d:
            self.toast("先点「展开」读一次", False)
            if not self.spec_body.isVisible():
                self.toggle_spec()
            return
        QtWidgets.QApplication.clipboard().setText(spec.report_text(d))
        self.toast("硬件报告已复制到剪贴板")

    def save_spec(self) -> None:
        d = getattr(self, "_spec_data", None)
        if not d:
            self.toast("先点「展开」读一次", False)
            if not self.spec_body.isVisible():
                self.toggle_spec()
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "导出硬件报告",
            str(Path.home() / f"硬件报告_{time.strftime('%Y%m%d')}.txt"),
            "文本 (*.txt)",
        )
        if not path:
            return
        try:
            Path(path).write_text(spec.report_text(d), encoding="utf-8")
            self.toast("已导出：" + Path(path).name)
        except Exception as exc:  # noqa: BLE001
            self.toast("导出失败：" + str(exc), False)

    def set_art_blur(self, val: int) -> None:
        """调背景模糊：每次拖完才真算，拖的时候只更新数字。"""
        self.cfg.art_blur = max(0, min(60, int(val)))
        try:
            self.cfg.save()
        except Exception:  # noqa: BLE001
            pass
        if not hasattr(self, "_blur_timer"):
            self._blur_timer = QTimer(self)
            self._blur_timer.setSingleShot(True)
            self._blur_timer.setInterval(260)
            self._blur_timer.timeout.connect(self.refresh_art)
        self._blur_timer.start()

    def _round_corners(self) -> None:
        """按当前外观摆弄窗口形状。

        现在统一不裁（壁纸要整块铺满，硬裁会把四角切出锯齿和缺口），
        只顺手请 DWM 圆一次、并清掉可能残留的蒙版。
        """
        import ctypes

        if not _glass_on:
            return
        hwnd = int(self.winId())
        if self.isMaximized() or self.isFullScreen():
            self._clear_round()
            return
        r = self._glass_radius()
        try:
            # DWMWCP_DONOTROUND：系统风格别插一手，否则四角是它裁的圆
            pref = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), 33, ctypes.byref(pref), ctypes.sizeof(pref)
            )
        except Exception:  # noqa: BLE001
            pass
        # 不再硬裁窗口形状：setMask 是 1 位蒙版，边缘切出来是锯齿，
        # 壁纸也会跟着在四角露出缺口。现在窗口保持矩形、壁纸铺满整窗，
        # 圆润那就交给 paintEvent 那层圆角底去画，看不清边也不毛糙。
        self.clearMask()

    def _clear_round(self) -> None:
        try:
            self.clearMask()
        except Exception:  # noqa: BLE001
            pass

    def _glass_radius(self) -> int:
        """玻璃状态下窗口的圆角半径，底线和 paintEvent 用的是同一套，别各算各的。"""
        try:
            base = int(float(theme.current().value("radius-lg", "19")))
        except Exception:  # noqa: BLE001
            base = 19
        return base + (12 if _liquid_on else 7)

    def _sync_art_mask(self) -> None:
        """壁纸铺满整窗，圆角交给窗口自己裁。

        壁纸单独裁圆角，四角就会露出底下的窗口底色，看着像图没铺满；
        让它老老实实铺满矩形，窗口那层 setMask 会把四角一起切掉，
        视觉上就是"整块窗口都是这张图，只是边是圆的"。
        """
        lbl = getattr(self, "art", None)
        if lbl is None:
            return
        try:
            lbl.setGeometry(self.rect())
            if hasattr(lbl, "set_radius"):
                lbl.set_radius(0)
            else:
                lbl.clearMask()
        except Exception:  # noqa: BLE001
            pass

    def _apply_round_by_cfg(self) -> None:
        """按配置里的窗口模式重裁一次窗口形状（不依赖 _glass_on 有没有被初始化）。"""
        mode = str(getattr(self.cfg, "window_mode", "classic") or "classic")
        if mode in ("glass", "liquid"):
            self._round_corners()
        else:
            self._clear_round()
        self._sync_art_mask()

    def set_window_mode(self, mode: str) -> None:
        """经典 / 毛玻璃 / 液态玻璃。

        液态玻璃是视觉近似：更透的底 + 更厚的亮边 + 穹顶反光；
        真正的实时折射 Windows 给不了，系统只给 acrylic / mica。
        """
        global _glass_on, _liquid_on
        if mode not in ("classic", "glass", "liquid"):
            mode = "classic"
        self.cfg.window_mode = mode
        try:
            self.cfg.save()
        except Exception:  # noqa: BLE001
            pass

        if getattr(self, "_mode_now", None) == mode:
            return
        # 启动时本来就是经典，不用把窗口重建一遍
        if mode == "classic" and getattr(self, "_mode_now", None) is None:
            self._mode_now = "classic"
            _glass_on = False
            _liquid_on = False
            return

        glass = mode in ("glass", "liquid")
        liquid = mode == "liquid"
        self._mode_now = mode
        _glass_on = glass
        _liquid_on = liquid
        self._apply_text_shadow(liquid)

        geo = self.geometry()
        was_max = self.isMaximized()
        self.hide()
        if glass:
            self.setWindowFlags(QtCore.Qt.Window | QtCore.Qt.FramelessWindowHint)
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        else:
            self.setWindowFlags(QtCore.Qt.Window)
            self.setAttribute(QtCore.Qt.WA_TranslucentBackground, False)
            self._clear_round()
            self._sync_art_mask()
        for b in (getattr(self, "btn_min", None), getattr(self, "btn_close", None)):
            if b is not None:
                b.setVisible(glass)
        self._sync_overrides()
        self.setGeometry(geo)
        self.show()
        if was_max:
            self.showMaximized()
        if glass:
            # 窗口刚重建过，原生句柄是新的，得重新挂一次
            try:
                self._sys_blur_mode = _system_blur(
                    int(self.winId()), 0x6A if _liquid_on else 0xA0
                )
                log.info("窗口磨砂：%s", self._sys_blur_mode)
            except Exception as exc:  # noqa: BLE001
                self._sys_blur_mode = "none"
                log.warning("系统磨砂挂不上：%s", exc)
            self._round_corners()
            # 窗口刚 show 过，平台窗口可能还没建完，setMask 会被丢掉；
            # 等一轮事件循环后再裁一次，启动那一次也能圆上。
            QTimer.singleShot(0, self._round_corners)
        self._sync_art_mask()

    def paintEvent(self, event) -> None:
        # 经典模式交给样式表画；玻璃 / 液态玻璃底下那一层自己画，圆角才真的圆
        if not _glass_on:
            super().paintEvent(event)
            return
        liquid = _liquid_on
        t = theme.current()
        r = int(float(t.value("radius-lg", "19"))) + (12 if liquid else 7)
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.Antialiasing, True)
        path = QtGui.QPainterPath()
        # 整块矩形：四角不再收圆，壁纸铺满时窗口就是个方方正正的块
        path.addRect(QtCore.QRectF(self.rect()))
        col = QtGui.QColor(t.value("bg-page", "#0e1015"))
        if not col.isValid():
            col = QtGui.QColor("#0e1015")
        # 系统真给了磨砂才敢把底色放透；不给就守住，别让桌面直接穿上来
        sys_ok = getattr(self, "_sys_blur_mode", "none") in ("acrylic", "blur")
        if liquid:
            col.setAlphaF(0.34 if sys_ok else 0.64)
        else:
            col.setAlphaF(0.46 if sys_ok else 0.72)
        p.fillPath(path, col)

        # 细颗粒：液态玻璃更细一点
        p.save()
        p.setClipPath(path)
        p.setOpacity(0.34 if liquid else 0.55)
        p.drawTiledPixmap(self.rect(), _noise_pixmap())
        p.restore()

        # 顶部压暗：磨砂背景再模糊也是亮的，字得靠这一层撑住
        grad = QtGui.QLinearGradient(0, 0, 0, 132)
        grad.setColorAt(0.0, QtGui.QColor(8, 10, 14, 150 if liquid else 168))
        grad.setColorAt(0.62, QtGui.QColor(8, 10, 14, 86 if liquid else 96))
        grad.setColorAt(1.0, QtGui.QColor(8, 10, 14, 0))
        p.setOpacity(1.0)
        p.fillRect(QtCore.QRect(0, 0, self.width(), 132), grad)
        grad2 = QtGui.QLinearGradient(0, self.height(), 0, self.height() - 52)
        grad2.setColorAt(0.0, QtGui.QColor(8, 10, 14, 132))
        grad2.setColorAt(1.0, QtGui.QColor(8, 10, 14, 0))
        p.fillRect(QtCore.QRect(0, self.height() - 52, self.width(), 52), grad2)

        if liquid:
            p.save()
            p.setClipPath(path)
            # 穹顶反光：顶部一片弧形高光，像玻璃罩被灯光扫到
            dome = QtGui.QRadialGradient(
                QtCore.QPointF(self.width() * 0.5, -self.height() * 0.35),
                float(max(self.width(), self.height()) * 1.05),
            )
            dome.setColorAt(0.0, QtGui.QColor(255, 255, 255, 68))
            dome.setColorAt(0.45, QtGui.QColor(255, 255, 255, 16))
            dome.setColorAt(1.0, QtGui.QColor(255, 255, 255, 0))
            p.fillRect(self.rect(), dome)
            # 斜向反光：左上亮、中段透明、右下再亮一点
            sheen = QtGui.QLinearGradient(0, 0, self.width() * 1.1, self.height() * 1.1)
            sheen.setColorAt(0.0, QtGui.QColor(255, 255, 255, 78))
            sheen.setColorAt(0.35, QtGui.QColor(255, 255, 255, 26))
            sheen.setColorAt(0.5, QtGui.QColor(255, 255, 255, 0))
            sheen.setColorAt(1.0, QtGui.QColor(255, 255, 255, 34))
            p.fillRect(self.rect(), sheen)
            p.restore()

        # 外高光边
        pen = QtGui.QPen(QtGui.QColor(255, 255, 255, 74 if liquid else 34))
        pen.setWidth(1)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))
        if liquid:
            # 内侧再压一道更细的高光，玻璃才有厚度
            pen2 = QtGui.QPen(QtGui.QColor(255, 255, 255, 24))
            pen2.setWidth(1)
            p.setPen(pen2)
            p.drawRect(self.rect().adjusted(4, 4, -5, -5))
        p.end()

    def mousePressEvent(self, event) -> None:
        if _glass_on and event.button() == QtCore.Qt.LeftButton:
            if event.position().y() <= 58:
                self._drag_off = event.globalPosition() - QtCore.QPointF(
                    self.frameGeometry().topLeft()
                )
                self._drag_on = True
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if getattr(self, "_drag_on", False) and (event.buttons() & QtCore.Qt.LeftButton):
            if not self.isMaximized():
                self.move((event.globalPosition() - self._drag_off).toPoint())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if getattr(self, "_drag_on", False):
            self._drag_on = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def set_art_enabled(self, on: bool) -> None:
        self.cfg.art_show = bool(on)
        try:
            self.cfg.save()
        except Exception:  # noqa: BLE001
            pass
        self.refresh_art()

    def pick_art(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "选一张壁纸", str(Path.home() / "Pictures"),
            "图片 (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not path:
            return
        name = artwork.import_file(path)
        if not name:
            self.toast("这张图用不了，换成 png / jpg 再试", False)
            return
        self.cfg.art_file = name
        self.cfg.art_show = True
        try:
            self.cfg.save()
        except Exception:  # noqa: BLE001
            pass
        self.refresh_art()
        self.toast("壁纸已换上：" + name)

    def clear_art(self) -> None:
        self.cfg.art_show = False
        try:
            self.cfg.save()
        except Exception:  # noqa: BLE001
            pass
        self.refresh_art()
        self.toast("壁纸已关掉")

    def set_theme(self, key: str) -> None:
        """换皮肤：立刻生效并记到配置里，下次开程序还是这套。"""
        t = theme.set_current(key)
        self.cfg.theme = t.key
        try:
            self.cfg.save()
        except Exception:  # noqa: BLE001
            pass
        apply_theme()
        try:
            self.toast(f"皮肤：{t.name}")
        except Exception:  # noqa: BLE001
            pass

    def open_skin_panel(self) -> None:
        dlg = SkinPanel(self)
        dlg.exec()
        self.refresh_skin_btn()

    def refresh_skin_btn(self) -> None:
        try:
            self.skin_btn.setToolTip(f"外观　当前皮肤：{theme.current().name}　点击打开")
        except Exception:  # noqa: BLE001
            pass

    def apply_crosshair(self) -> None:
        """按配置显示 / 隐藏准星层。"""
        try:
            if getattr(self.cfg, "cross_show", False):
                self.crosshair.show_cross()
            else:
                self.crosshair.hide_cross()
        except Exception:  # noqa: BLE001
            pass

    def toast(self, msg: str, ok: bool = True) -> None:
        """提示统一上岛：就走游戏模式那一条，在窗口自己顶部中间。

        原来这行字挤在左下角，还容易跟别的提示打架；现在跟游戏模式开关
        同一个控件、同一个位置，一次只显示一条。
        """
        msg = (msg or "").strip()
        if not msg:
            return
        title, sub = msg, ""
        for sep in ("：", ":"):
            if sep in msg:
                head, tail = msg.split(sep, 1)
                if 0 < len(head.strip()) <= 20:
                    title, sub = head.strip(), tail.strip()
                break
        try:
            self.mode_island.say(title, sub, ok)
            return
        except Exception:  # noqa: BLE001
            pass
        # 岛要是起不来，退回左下角那行小字
        self.toast_label.setText(msg)
        self.toast_label.setStyleSheet(
            "color:%s; font-size:11px;" % ("#20ffe0" if ok else "#ff8080")
        )
        QTimer.singleShot(4000, self._reset_toast)

    def _reset_toast(self) -> None:
        self.toast_label.setText("关闭窗口会收进托盘，工具不会被关掉。")
        self.toast_label.setStyleSheet("")

    # ------------------------------------------------------------------
    # 面板开关 → 自动化动作
    # ------------------------------------------------------------------
    def run_gui_action(self, action: Action) -> Tuple[float, str]:
        """把面板上的开关当成自动化的一个动作来跑（返回 等待秒数, 日志）。"""
        t = action.type

        if t == ACTION_ACE_LIMIT:
            if not ace.is_admin():
                return (0.0, "反作弊优化：需要管理员权限，这次跳过（用管理员身份启动燧镜后才会生效）")
            ok, total, fails = ace.apply_limits()
            self._ace_refresh_state()
            if total == 0:
                return (0.0, "反作弊优化：没找到 ACE 进程（游戏还没起全？）")
            note = f"反作弊优化：压低 {ok}/{total} 个进程"
            if fails and ok < total:
                note += f"（{len(fails)} 个被拒绝）"
            return (0.0, note)

        if t == ACTION_ACE_RESTORE:
            ok, total = ace.restore_all()
            self._ace_refresh_state()
            if total == 0:
                return (0.0, "还原反作弊优化：现在没有 ACE 进程")
            return (0.0, f"还原反作弊优化：恢复 {ok}/{total} 个进程的优先级")

        if t == ACTION_FPS_SHOW:
            self.set_fps_enabled(True)
            return (0.0, "开帧率悬浮窗：已打开")

        if t == ACTION_FPS_HIDE:
            self.set_fps_enabled(False)
            return (0.0, "关帧率悬浮窗：已关闭")

        if t == ACTION_HUD_SHOW:
            self.set_hud_enabled(True)
            return (0.0, "显示密码悬浮窗：已打开")

        if t == ACTION_HUD_HIDE:
            self.set_hud_enabled(False)
            return (0.0, "隐藏密码悬浮窗：已关闭")

        if t == ACTION_REPLAY_START:
            if self.replay.is_running:
                return (0.0, "开启回放缓冲：本来就在跑")
            ok, msg = self.replay.start()
            if not ok:
                return (0.0, f"开启回放缓冲失败：{msg}")
            self.replay_btn.setText("回放 ●")
            return (0.0, "开启回放缓冲：已开始（保留最近 12 分钟）")

        if t == ACTION_REPLAY_STOP:
            if not self.replay.is_running:
                return (0.0, "关闭回放缓冲：本来就是关的")
            self.replay.stop()
            self.replay_btn.setText("回放")
            return (0.0, "关闭回放缓冲：已关闭")

        if t == ACTION_REPLAY_SAVE:
            if not self.replay.is_running:
                return (0.0, "保存最近回放：回放缓冲没开，没东西可存")
            if self.replay.buffered_seconds() < 15:
                return (0.0, "保存最近回放：缓冲刚起步，跳过")
            self.save_replay()
            return (0.0, "保存最近回放：正在合成，完成后存进素材目录")

        if t == ACTION_RECORD_START:
            if self.recorder.is_recording:
                return (0.0, "开始录屏：已经在录了")
            ok, msg = self.recorder.start()
            if not ok:
                return (0.0, f"开始录屏失败：{msg}")
            self.rec_btn.setText("停止")
            return (0.0, "开始录屏：录制中（含系统声音）")

        if t == ACTION_RECORD_STOP:
            if not self.recorder.is_recording:
                return (0.0, "停止录屏：本来没在录")
            path = self.recorder.stop()
            self.rec_btn.setText("开始录屏")
            if path is None:
                return (0.0, "停止录屏：这次没抓到画面，文件没保存")
            return (0.0, f"停止录屏：已保存 {path.name}")

        if t == ACTION_SHOT:
            mode = (action.value or "full").strip().lower()
            if mode == "region":
                self.shot_region()
                return (0.0, "截一张图：进入框选")
            self.shot_full()
            return (0.5, "截一张图：已保存全屏截图")

        if t == ACTION_CACHE_CLEAN:
            try:
                freed, removed, skipped = cacheclean.clean()
            except Exception as exc:  # noqa: BLE001
                return (0.0, f"清理着色器缓存：失败 {exc}")
            note = f"清理着色器缓存：清掉 {cacheclean.fmt_size(freed)}"
            if skipped:
                note += f"（{len(skipped)} 个被占用）"
            card = getattr(self, "tools_card", None)
            if card is not None:
                card.cache_info.setText(note.replace("清理着色器缓存：", "已清 "))
            return (0.0, note)

        return (0.0, f"不认识的动作：{t}")

    # ------------------------------------------------------------------
    # 自动化
    # ------------------------------------------------------------------
    def set_hud_side(self, side: str) -> None:
        """悬浮窗贴左边还是右边。"""
        hud = getattr(self, "hud", None)
        if hud is None:
            return
        side = "left" if side == "left" else "right"
        hud.set_side(side)
        self.toast("悬浮窗位置：" + ("左侧" if side == "left" else "右侧"))

    def set_hud_through(self, on: bool) -> None:
        """鼠标穿透开关。"""
        hud = getattr(self, "hud", None)
        if hud is None:
            return
        hud.set_click_through(bool(on))
        self.toast("鼠标穿透：" + ("开" if on else "关（现在可以右键调字号）"))

    def set_hud_enabled(self, on: bool) -> None:
        """每日密码悬浮窗总开关：设置面板、托盘菜单共用这一个。"""
        on = bool(on)
        self.cfg.hud_show = on
        self.cfg.save()
        hud = getattr(self, "hud", None)
        if hud is None:
            return
        if on:
            hud.show_hud()
            self.toast("每日密码悬浮窗：已打开（右键可调字号 / 锁定位置）")
        else:
            hud.hide_hud()
            self.toast("每日密码悬浮窗：已关闭")

    # ------------------------------------------------------------ 截图与素材
    def shot_full(self, label: str = "全屏") -> None:
        """全屏截图：先把自己藏起来，抓完再回来。"""
        self._shot_restore = self.isVisible()
        if self._shot_restore:
            self.hide()
            QTimer.singleShot(260, lambda: self._do_full_shot(label))
        else:
            self._do_full_shot(label)

    def _do_full_shot(self, label: str) -> None:
        try:
            pixmap, _geo = capture.grab_screen()
            path = capture.save_pixmap(pixmap, label)
        except Exception as exc:  # noqa: BLE001
            path = None
            self.toast("截图失败：" + str(exc)[:40], False)
        if getattr(self, "_shot_restore", False):
            self.show()
            self._shot_restore = False
        self._after_shot(path)

    def shot_region(self) -> None:
        """框选截图：全屏遮罩上拉一个框。"""
        try:
            pixmap, geo = capture.grab_screen()
        except Exception as exc:  # noqa: BLE001
            self.toast("截图失败：" + str(exc)[:40], False)
            return
        self._shot_restore = self.isVisible()
        if self._shot_restore:
            self.hide()
        self._picker = capture.RegionPicker(
            pixmap,
            geo,
            on_done=self._region_done,
            on_cancel=self._region_cancel,
        )
        self._picker.setGeometry(geo)
        self._picker.show()
        self._picker.raise_()
        self._picker.activateWindow()

    def _region_cancel(self) -> None:
        if getattr(self, "_shot_restore", False):
            self.show()
            self._shot_restore = False

    def _region_done(self, pixmap, rect) -> None:
        path = capture.save_pixmap(pixmap, f"区域{rect.width()}x{rect.height()}")
        self._region_cancel()
        self._after_shot(path)

    def shot_delayed(self) -> None:
        """3 秒后抓前台窗口，用来截游戏。"""
        self._shot_restore = self.isVisible()
        if self._shot_restore:
            self.hide()
        if self.tray is not None:
            self.tray.showMessage(APP_NAME, "3 秒后截取当前窗口…")
        QTimer.singleShot(3000, self._shot_foreground_now)

    def _shot_foreground_now(self) -> None:
        pixmap = capture.grab_foreground_window()
        path = capture.save_pixmap(pixmap, "窗口") if pixmap is not None else None
        if getattr(self, "_shot_restore", False):
            self.show()
            self._shot_restore = False
        if path is None:
            self.toast("没抓到前台窗口，换个目标再试", False)
        self._after_shot(path)

    def _after_shot(self, path) -> None:
        if path is None:
            return
        self.toast("截图已保存：" + path.name)
        if self.tray is not None:
            self.tray.showMessage(APP_NAME, "已保存 " + path.name)

    # ------------------------------------------------------------ 录屏
    def toggle_record(self) -> None:
        if self.recorder.is_recording:
            path = self.recorder.stop()
            self.rec_btn.setText("开始录屏")
            if path is not None:
                self.toast(f"录像已保存：{path.name}")
                if self.tray is not None:
                    self.tray.showMessage(APP_NAME, "录像已保存 " + path.name)
            else:
                self.toast("录像已停止")
        else:
            ok, msg = self.recorder.start()
            if ok:
                self.rec_btn.setText("停止")
                self.toast("开始录屏，再按一次停止")
                if self.tray is not None:
                    self.tray.showMessage(APP_NAME, "开始录屏")
            else:
                self.toast(msg[:60], False)

    # ------------------------------------------------------------ 回放
    def set_replay_max_gb(self, gb) -> None:
        try:
            gb = int(gb)
        except (TypeError, ValueError):
            return
        self.cfg.replay_max_gb = gb if gb in (5, 7, 10) else 5
        self.cfg.save()
        self.toast(f"回放缓存上限 {self.cfg.replay_max_gb} GB（下次开启回放生效）")

    def set_replay_dir(self, path) -> None:
        self.cfg.replay_dir = str(path or "").strip()
        self.cfg.save()
        if self.cfg.replay_dir:
            self.toast("缓存盘已改，下次开启回放生效")
        else:
            self.toast("回放缓存回到程序目录")

    def media_info_text(self) -> str:
        root = capture.media_root()
        try:
            free = shutil.disk_usage(root).free / 1024 ** 3
            state = "已存在" if root.exists() else "还没建"
            return f"现在存到：{root}（{state}，该盘剩 {free:.0f} GB）"
        except OSError:
            return f"现在存到：{root}"

    def media_stat(self, root: Path) -> Tuple[int, int]:
        """(文件数, 总字节)，跳过缩略图缓存目录。"""
        count = 0
        size = 0
        try:
            if not root.exists():
                return (0, 0)
            for f in root.rglob("*"):
                if not f.is_file():
                    continue
                if ".thumbs" in f.parts:
                    continue
                count += 1
                try:
                    size += f.stat().st_size
                except OSError:
                    pass
        except OSError:
            pass
        return (count, size)

    def move_media_tree(self, src: Path, dst: Path) -> Tuple[int, int]:
        """把 src 下的素材搬到 dst（保留日期子目录），返回 (成功, 跳过)。"""
        moved = 0
        skipped = 0
        files = [f for f in src.rglob("*") if f.is_file()]
        total = len(files)
        if total == 0:
            return (0, 0)
        bar = QtWidgets.QProgressDialog(f"正在搬 {total} 个文件…", "取消", 0, total, self)
        bar.setWindowTitle("搬素材")
        bar.setWindowModality(Qt.WindowModal)
        bar.setMinimumDuration(0)
        bar.setValue(0)
        for i, f in enumerate(files, 1):
            bar.setValue(i)
            bar.setLabelText(f"正在搬 {i}/{total}：{f.name}")
            QtWidgets.QApplication.processEvents()
            if bar.wasCanceled():
                skipped += total - i + 1
                break
            try:
                rel = f.relative_to(src)
            except ValueError:
                skipped += 1
                continue
            target = dst / rel
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    skipped += 1
                    continue
                shutil.move(str(f), str(target))
                moved += 1
            except OSError:
                skipped += 1
        bar.close()
        # 收拾空目录（只删空的，留着有东西的）
        for d in sorted((x for x in src.rglob("*") if x.is_dir()), key=lambda x: -len(str(x))):
            try:
                d.rmdir()
            except OSError:
                pass
        try:
            src.rmdir()
        except OSError:
            pass
        return (moved, skipped)

    def set_media_dir(self, path) -> None:
        """切换素材存放位置；旧位置有东西就问一句要不要搬过去。"""
        new_dir = str(path or "").strip()
        if new_dir == getattr(self.cfg, "media_dir", ""):
            return
        old_root = capture.media_root()
        new_root = Path(new_dir) if new_dir else (capture.app_dir() / capture.ROOT_DIR)
        try:
            if old_root.resolve() == new_root.resolve():
                return
        except OSError:
            pass

        # 目标能不能写
        try:
            new_root.mkdir(parents=True, exist_ok=True)
            probe = new_root / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
        except OSError as exc:
            self.toast(f"这个位置写不进去：{exc}", False)
            return

        count, size = self.media_stat(old_root)
        moved = skipped = 0
        if count > 0:
            box = QtWidgets.QMessageBox(self)
            box.setWindowTitle("换素材位置")
            box.setText(f"旧位置还有 {count} 个素材，共 {capture_fmt(size)}。")
            box.setInformativeText(
                f"搬到新位置：{new_root}\n"
                "· 搬：文件和日期目录一起过去，素材页立刻能看到\n"
                "· 不搬：新素材进新位置，旧的留在原处（素材页就看不到它们了）"
            )
            yes = box.addButton("一起搬过去", QtWidgets.QMessageBox.AcceptRole)
            box.addButton("只换位置，旧的留着", QtWidgets.QMessageBox.RejectRole)
            box.setDefaultButton(yes)
            box.exec()
            if box.clickedButton() is yes:
                moved, skipped = self.move_media_tree(old_root, new_root)

        self.cfg.media_dir = new_dir
        self.cfg.save()
        capture.set_root(new_dir or None)
        if hasattr(self, "media_page"):
            try:
                self.media_page.reload()
            except Exception:  # noqa: BLE001
                pass

        if moved:
            tail = f"，{skipped} 个跳过（重名或读不动）" if skipped else ""
            self.toast(f"已搬 {moved} 个到 {new_root}{tail}")
        elif new_dir:
            self.toast(f"素材以后存到 {new_root}")
        else:
            self.toast("素材回到程序目录")

    def set_ping_host(self, text: str) -> None:
        text = (text or "").strip()
        if text == getattr(self.cfg, "ping_host", ""):
            return
        self.cfg.ping_host = text
        self.cfg.save()
        if text:
            host, port = netspeed.split_host(text)
            self.toast(f"测速时额外打 {host}:{port}")
        else:
            self.toast("已清空，只测公共节点")

    def replay_cache_text(self) -> str:
        try:
            size = int(self.replay.buffer_size())
        except Exception:  # noqa: BLE001
            size = 0
        cap = int(getattr(self.cfg, "replay_max_gb", 5))
        where = getattr(self.cfg, "replay_dir", "") or "程序目录"
        return f"当前缓冲 {size / 1024 ** 3:.2f} GB / 上限 {cap} GB · 缓存盘 {where}"

    def toggle_replay(self) -> None:
        if self.replay.is_running:
            self.replay.stop()
            self.replay_btn.setText("回放")
            self.toast("回放缓冲已关闭")
        else:
            root = None
            if getattr(self.cfg, "replay_dir", ""):
                root = Path(self.cfg.replay_dir)
            try:
                self.replay.configure(getattr(self.cfg, "replay_max_gb", 5), root)
            except Exception:  # noqa: BLE001
                pass
            ok, msg = self.replay.start()
            if ok:
                self.replay_btn.setText("回放 ●")
                self.toast(
                    f"回放缓冲已开启，保留最近 12 分钟（上限 "
                    f"{getattr(self.cfg, 'replay_max_gb', 5)} GB）"
                )
            else:
                self.toast(msg[:60], False)

    def save_replay(self) -> None:
        if not self.replay.is_running:
            self.toast("先开启回放缓冲，才有画面可存", False)
            return
        if self._replay_worker is not None and self._replay_worker.isRunning():
            self.toast("上一次还在合成，稍等一下", False)
            return
        if self.replay.buffered_seconds() < 15:
            self.toast("缓冲才刚开始，等十几秒再存", False)
            return

        self.toast("正在合成最近 10 分钟…")
        worker = _ReplaySaver(self.replay, 10, self)
        self._replay_worker = worker
        worker.done.connect(self._on_replay_saved)
        worker.start()

    def _on_replay_saved(self, ok: bool, msg: str) -> None:
        if ok:
            name = Path(msg).name
            self.toast("回放已保存：" + name)
            if self.tray is not None:
                self.tray.showMessage(APP_NAME, "回放已保存 " + name)
        else:
            self.toast(msg[:70], False)

    # ------------------------------------------------------------ 帧率悬浮窗
    def set_fps_enabled(self, on: bool) -> None:
        self.cfg.fps_show = bool(on)
        self.cfg.save()
        if on:
            self.show_fps()
        else:
            self.hide_fps()

    def show_fps(self) -> None:
        ok = self.fps_mon.start()
        self.fps_hud.show_hud()
        if not ok:
            self.toast("缺少 PresentMon.exe，帧率读不到", False)
            return
        QTimer.singleShot(9500, self._fps_hint)

    def _fps_hint(self) -> None:
        """开了一会儿还是 0，就把原因说出来（只提醒一次）。"""
        if self.fps_mon.current > 0:
            return
        why = (self.fps_mon.error_text or "").strip()
        if not why:
            return
        self.toast(why, False)
        if self.tray is not None:
            self.tray.showMessage(APP_NAME, why)

    def _fps_restart_as_admin(self) -> None:
        """帧率窗右键 → 以管理员重启（PresentMon 抓不到高权限游戏时用）。"""
        if ace.is_admin():
            self.toast("已经是管理员了；还读不到就关掉一个监控/加速软件再试", False)
            return
        ret = QtWidgets.QMessageBox.question(
            self,
            "需要管理员权限",
            "游戏是管理员权限在跑时，燧镜不是管理员就读不到它的帧。\n\n"
            "现在以管理员身份重启燧镜吗？（重启后静默待在托盘，双击图标再开面板）",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if ret != QtWidgets.QMessageBox.Yes:
            return
        if ace.relaunch_as_admin():
            self._quitting = True
            QtWidgets.QApplication.quit()
        else:
            self.toast("提权重启被取消或失败", False)

    def hide_fps(self) -> None:
        self.fps_mon.stop()
        self.fps_hud.hide_hud()

    def set_fps_side(self, side: str) -> None:
        self.fps_hud.set_side(side)

    def set_fps_through(self, on: bool) -> None:
        self.fps_hud.set_click_through(on)

    def set_fps_scale(self, value: int) -> None:
        self.fps_hud.set_scale(value)

    def toggle_fps(self) -> None:
        on = not bool(getattr(self.cfg, "fps_show", False))
        self.set_fps_enabled(on)
        self.toast("帧率悬浮窗已开启" if on else "帧率悬浮窗已关闭")

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        island = getattr(self, "island", None)
        if island is not None:
            island.place()

        if _glass_on:
            self._round_corners()
            self._sync_art_mask()

    def _goto(self, attr: str) -> None:
        """页签点击：按属性名切到那一页（属性是延迟取的，建页顺序不影响）。"""
        if attr == "media_page":
            self.show_media()
            return
        page = getattr(self, attr, None)
        if page is not None:
            self.stack.setCurrentWidget(page)

    def _on_stack_page(self, *_) -> None:
        """切页后强制整窗重画一遍。

        页面背景都是透明的，母窗口又在跑系统磨砂（acrylic），Qt 不会主动擦
        上一页那块像素，DWM 也不一定重算模糊层 —— 结果就是切到模组页，
        底下还透出主页那半截（"残影"）。这里把窗口整块 repaint，再把磨砂
        重新套一次，让 DWM 也认账。
        """
        self._sync_tabs()
        try:
            self.update()
            self.repaint()
        except Exception:  # noqa: BLE001
            pass
        QTimer.singleShot(0, self._flush_backdrop)

    def _flush_backdrop(self) -> None:
        try:
            self.update()
            self.repaint()
            if getattr(self, "_sys_blur_mode", "none") in ("acrylic", "blur"):
                import ctypes

                _system_blur(int(self.winId()), 0x6A if _liquid_on else 0xA0)
                ctypes.windll.dwmapi.DwmFlush()
        except Exception:  # noqa: BLE001
            pass

    def _sync_tabs(self, *_) -> None:
        cur = self.stack.currentWidget()
        for attr, b in getattr(self, "_tab_btns", {}).items():
            page = getattr(self, attr, None)
            b.setChecked(cur is page)
        island = getattr(self, "island", None)
        if island is not None:
            island.refresh()

    def show_tools(self) -> None:
        page = getattr(self, "tools_page", None)
        if page is not None:
            self.stack.setCurrentWidget(page)

    def show_mods(self) -> None:
        page = getattr(self, "mods_page", None)
        if page is not None:
            self.stack.setCurrentWidget(page)

    def show_media(self) -> None:
        page = getattr(self, "media_page", None)
        if page is None:
            return
        page.reload()
        self.stack.setCurrentWidget(page)

    def show_delta(self) -> None:
        """切到三角洲情报页；已经在那一页就切回主页。"""
        page = getattr(self, "delta_page", None)
        if page is None:
            return
        if self.stack.currentWidget() is page:
            self.show_home()
        else:
            self.stack.setCurrentWidget(page)

    def show_home(self) -> None:
        """回到主页。

        注意：主页被包在 home_scroll 里，stack 的直接子级是 home_scroll 而不是
        home_page —— 拿 home_page 去 setCurrentWidget 会被 Qt 静默忽略，按钮就像失效。
        """
        page = getattr(self, "home_scroll", None) or getattr(self, "home_page", None)
        if page is not None:
            self.stack.setCurrentWidget(page)

    def show_automation(self) -> None:
        AutomationDialog(self).exec()

    def show_guide(self, force: bool = False) -> None:
        """新手引导：第一次启动自动弹，之后从设置里主动打开。"""
        if not force and self.cfg.guide_shown:
            return
        dlg = GuideDialog(self)
        self._guide_busy = True
        try:
            dlg.exec()
        finally:
            self._guide_busy = False
        self.cfg.guide_shown = True
        self.cfg.save()

    def note_rule_change(self) -> None:
        if self.tray is not None:
            self.tray.mark_dirty()

    def _log_auto(self, msg: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        self.auto_log.append(line)
        if len(self.auto_log) > 200:
            self.auto_log = self.auto_log[-200:]
        log.info("自动化：%s", msg)

    def run_rule(self, rule: Rule, reason: str = "手动") -> None:
        if not rule.enabled:
            self._log_auto(f"规则「{rule.name}」已停用，跳过")
            return
        if not rule.actions:
            self._log_auto(f"规则「{rule.name}」没有动作，跳过")
            return
        self._log_auto(
            f"规则「{rule.name}」触发（{reason}）：{automation.describe(rule, self.cfg)}"
        )
        self.run_actions(rule.actions, rule.name)

    def run_actions(self, actions: List[Action], title: str, dry: bool = False) -> None:
        self._run_step(list(actions), 0, title, dry)

    def _run_step(
        self, actions: List[Action], idx: int, title: str, dry: bool = False
    ) -> None:
        if idx >= len(actions):
            self._log_auto(f"「{title}」{'试运行结束（什么都没改）' if dry else '执行完毕'}")
            if self.tray is not None:
                self.tray.mark_dirty()
            if not dry:
                QTimer.singleShot(800, self.refresh_resolution)
            return
        wait, msg = automation.execute(actions[idx], self.cfg, self.guard, self, dry=dry)
        self._log_auto(f"「{title}」{msg}")
        if not dry:
            for card in self.cards:
                card.refresh()
            for tile in self.tiles:
                tile.refresh()
        delay = int(max(0.12, wait) * 1000)
        QTimer.singleShot(
            delay, lambda: self._run_step(actions, idx + 1, title, dry)
        )

    def _watch_rules(self) -> None:
        auto = [
            r
            for r in self.cfg.rules
            if r.enabled
            and r.trigger in (TRIGGER_START, TRIGGER_STOP)
            and r.process.strip()
        ]
        if not auto:
            return
        names = automation.snapshot()
        for rule in auto:
            proc = rule.process.strip().lower()
            now = proc in names
            prev = self._rule_active.get(rule.id)
            self._rule_active[rule.id] = now
            if prev is None:
                # 第一次只记基线，避免程序刚启动就把已在跑的游戏当成"刚启动"
                continue
            if rule.trigger == TRIGGER_START and now and not prev:
                _emit_mod_event("game.started", process=rule.process)
                self.run_rule(rule, f"{rule.process} 启动")
            elif rule.trigger == TRIGGER_STOP and prev and not now:
                _emit_mod_event("game.stopped", process=rule.process)
                self.run_rule(rule, f"{rule.process} 退出")

    # ------------------------------------------------------------------
    # 工具启动（统一处理延迟）
    # ------------------------------------------------------------------
    def open_remote(self, mod: Mod) -> None:
        """三方工具：有直链就在软件里下载，没直链就打开官网。"""
        home = (mod.path or "").strip()
        dl = (getattr(mod, "dl", "") or "").strip()
        if not dl:
            if home:
                QtGui.QDesktopServices.openUrl(QtCore.QUrl(home))
                self.toast(f"已打开 {mod.name} 官网；下好后用「+ 添加工具」指过来")
            else:
                self.toast("这条三方工具没填官网地址", False)
            return

        worker = getattr(mod, "_dl_worker", None)
        if worker is not None and worker.isRunning():
            self.toast("正在下载，等它下完")
            return

        dest_dir = _downloads_dir() / _safe_folder(mod.name)
        try:
            dest_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.toast("建下载目录失败：" + str(exc), False)
            return

        dest = dest_dir / _guess_filename(dl)
        if dest.exists():
            stem, suffix = dest.stem, dest.suffix
            i = 1
            while (dest_dir / f"{stem}_{i}{suffix}").exists():
                i += 1
            dest = dest_dir / f"{stem}_{i}{suffix}"

        w = _RemoteDownload(dl, dest, self)
        mod._dl_worker = w
        mod._dl_pct = -10
        mod._dl_mb = -5
        self.toast(f"开始下载 {mod.name}…")

        def _on_prog(got: int, total: int) -> None:
            if total > 0:
                pct = int(got * 100 / total)
                if pct - getattr(mod, "_dl_pct", -10) >= 10:
                    mod._dl_pct = pct
                    self.toast(f"{mod.name} 下载中 {pct}%")
            else:
                mb = got / 1048576
                if mb - getattr(mod, "_dl_mb", -5) >= 5:
                    mod._dl_mb = mb
                    self.toast(f"{mod.name} 已下载 {mb:.0f} MB")

        w.progress.connect(_on_prog)
        w.ok.connect(lambda p: self._on_remote_done(mod, p))
        w.bad.connect(lambda e: self._on_remote_fail(mod, e))
        w.start()

    def _on_remote_done(self, mod: Mod, path: str) -> None:
        mod._dl_worker = None
        p = Path(path)
        if p.suffix.lower() == ".exe":
            # exe 直接落地：这条三方工具就地变成本地工具，工具页里点启动就行
            mod.kind = KIND_EXE
            mod.path = str(p)
            mod.dl = ""
            mod.note = (mod.note + " · 来自官网").strip(" ·") if mod.note else "来自官网"
            self.cfg.save()
            self.rebuild_mods()
            self._on_mods_changed()
            self.toast(f"下载完成，已加入工具：{mod.name}", True)
        else:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(p.parent)))
            self.toast(
                f"下载好了（{p.name}）。压缩包要先解压，再用「+ 添加工具」选里面的 exe", True
            )

    def _on_remote_fail(self, mod: Mod, err: str) -> None:
        mod._dl_worker = None
        self.toast(f"{mod.name} 下载失败：{err}", False)

    def launch_mod(self, mod: Mod) -> None:
        if mod.kind == KIND_REMOTE:
            self.open_remote(mod)
            return
        if mod.kind == KIND_PAGE:
            self.show_page_mod(mod)
            return
        if mod.delay > 0:
            self.toast(f"{mod.name}：{mod.delay} 秒后启动")
            QTimer.singleShot(mod.delay * 1000, lambda: self._do_launch(mod))
        else:
            self._do_launch(mod)

    def show_page_mod(self, mod: Mod) -> None:
        """内置页面工具：不启动任何进程，直接切到对应页面（或弹出窗口）。"""
        key = (mod.path or "").strip()
        if key == "delta":
            self.show_delta()
        elif key == "filter":
            self.open_filter()
        else:
            self.toast(f"内置页面「{key}」还没接上", False)

    def open_filter(self) -> None:
        """显示器滤镜：跟帧率窗一样挂在主窗口外，关掉只是隐藏。"""
        win = getattr(self, "filter_win", None)
        if win is None:
            self.filter_win = filterwin.FilterWindow(self.cfg)
            win = self.filter_win
        win.show_window()
        self.toast("滤镜窗已打开：左边原图、右边是这套参数的效果")

    def _do_launch(self, mod: Mod) -> None:
        mod._retried = False
        ok, msg = self.guard.launch(mod)
        self.toast(msg, ok)
        for card in self.cards:
            card.refresh()
        for tile in self.tiles:
            tile.refresh()
        if self.tray is not None:
            self.tray.mark_dirty()
        if ok and mod.kind == KIND_EXE:
            # 1.2 秒后回头看一眼：起来了没。不在这里 sleep，免得界面卡住
            QTimer.singleShot(1200, lambda: self._check_mod_health(mod))

    def _check_mod_health(self, mod: Mod) -> None:
        ok, msg = self.guard.health(mod)
        if not ok and msg:
            if not mod._retried:
                # 第一次没起来：不少工具是"第一次拉运行库/拉子进程会慢半拍"，再给一次机会
                mod._retried = True
                self.toast(f"{mod.name} 没起来，自动再试一次…")
                log.warning("工具 %s 首次启动未成功（%s），自动重试", mod.name, msg)
                QTimer.singleShot(900, lambda: self._retry_mod(mod))
                return
            self.toast(msg + "（已自动重试过一次）", False)
            log.warning("工具启动失败：%s", msg)
        else:
            mod._retried = False
        for card in self.cards:
            card.refresh()
        for tile in self.tiles:
            tile.refresh()
        if self.tray is not None:
            self.tray.mark_dirty()

    def _retry_mod(self, mod: Mod) -> None:
        ok, msg = self.guard.launch(mod)
        if ok:
            QTimer.singleShot(1200, lambda: self._check_mod_health(mod))
        else:
            self.toast(msg + "（已自动重试过一次）", False)
            for card in self.cards:
                card.refresh()
            for tile in self.tiles:
                tile.refresh()
            if self.tray is not None:
                self.tray.mark_dirty()

    def launch_all_mods(self) -> None:
        """按列表顺序（= 你自己排的上下顺序）一个个起，前一个站住再起下一个。"""
        todo = [
            m for m in self.cfg.mods
            if m.enabled and m.kind in (KIND_EXE, KIND_HTML, KIND_URL)
            and not self.guard.is_running(m)
        ]
        if not todo:
            self.toast("没有需要启动的工具（都已启用且未运行）")
            return
        log.info("按顺序启动 %d 个工具：%s", len(todo), "、".join(m.name for m in todo))
        self._launch_queue = list(todo)
        if self.launch_all_btn is not None:
            self.launch_all_btn.setEnabled(False)
        QTimer.singleShot(0, self._launch_next)

    def _launch_next(self) -> None:
        queue = getattr(self, "_launch_queue", [])
        if not queue:
            if self.launch_all_btn is not None:
                self.launch_all_btn.setEnabled(True)
            self.toast("全部启动走完一轮")
            return
        mod = queue.pop(0)
        self.toast(f"启动 {mod.name}…")
        self._do_launch(mod)
        if queue:
            QTimer.singleShot(800, self._launch_next)

    def _tick(self) -> None:
        # 重建工具列表时旧卡片会先销毁，这里必须防一手：
        # 刷新到已释放的 Qt 对象会抛 RuntimeError，严重时直接把界面带走
        for row in (self.cards, self.tiles):
            for it in list(row):
                try:
                    it.refresh()
                except RuntimeError:
                    continue
                except Exception:  # noqa: BLE001
                    continue
        if self.tray is not None:
            self.tray.mark_dirty()

    def _poll_command(self) -> None:
        """处理其他进程（双击图标）投递过来的命令。"""
        cmd = ipc.poll_command()
        if not cmd:
            return
        log.info("收到外部命令：%s", cmd)
        if cmd == "show":
            self.show_panel()
        elif cmd == "toggle":
            self.toggle_resolution()
        elif cmd == "panic":
            self.panic_restore()

    # ------------------------------------------------------------------
    def show_panel(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.refresh_resolution()

    # ------------------------------------------------------------------
    # ACE 扫盘限制
    # ------------------------------------------------------------------
    def _ace_badge(self, text: str, on: bool) -> None:
        badge = getattr(self, "ace_badge", None)
        if badge is None:
            return
        badge.setText(text)
        badge.setObjectName("Badge" if on else "BadgeDim")
        badge.setStyleSheet("")
        badge.style().unpolish(badge)
        badge.style().polish(badge)

    def _ace_refresh_state(self) -> None:
        try:
            n, low, single = ace.snapshot()
        except Exception as exc:
            self.ace_state.setText(f"读不到 ACE 状态：{exc}")
            self._ace_badge("读不到", False)
            return
        if n == 0:
            self.ace_state.setText("当前没有 ACE 进程（没启动游戏时是正常的）")
            self._ace_badge("待命", False)
            return
        tail = " · 已限单核" if single else ""
        self.ace_state.setText(f"检测到 {n} 个 ACE 进程 · 已压低 {low} 个{tail}")
        self._ace_badge("已限制" if low else "未限制", bool(low))

    def ace_apply(self, quiet: bool = False) -> None:
        if not ace.is_admin():
            if quiet:
                return
            ret = QtWidgets.QMessageBox.question(
                self,
                "需要管理员权限",
                "ACE 的扫描进程是以 SYSTEM 运行的，改它的优先级需要管理员权限。\n\n"
                "现在以管理员身份重启燧镜吗？（重启后会静默待在托盘，双击图标再打开面板）",
                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            )
            if ret == QtWidgets.QMessageBox.Yes:
                if ace.relaunch_as_admin():
                    self._quitting = True
                    QtWidgets.QApplication.quit()
                else:
                    self.toast("提权重启被取消或失败", False)
            return

        ok, total, fails = ace.apply_limits()
        if total == 0:
            if not quiet:
                self.toast("没找到 ACE 进程，先启动游戏再点", False)
        elif ok:
            self.toast(f"已压低 {ok}/{total} 个 ACE 进程")
        elif not quiet:
            self.toast(f"ACE 拒绝了修改：{fails[0] if fails else '未知原因'}", False)
        self._ace_refresh_state()

    def ace_restore(self) -> None:
        ok, total = ace.restore_all()
        if total == 0:
            self.toast("现在没有 ACE 进程在跑", False)
        else:
            self.toast(f"已恢复正常优先级 {ok}/{total}")
        self._ace_refresh_state()

    def _on_ace_guard(self, checked: bool) -> None:
        self.cfg.ace_guard = checked
        self.cfg.save()
        if checked:
            self.ace_apply()
        else:
            self.toast("已关闭自动守护")

    def _ace_tick(self) -> None:
        if not self.cfg.ace_guard or not ace.is_admin():
            return
        try:
            ok, total, _fails = ace.apply_limits()
        except Exception:
            return
        if total:
            self._ace_refresh_state()

    # -------------------------------------------------------- 音频输出
    def _audio_devices(self) -> list:
        try:
            return audioout.list_render_devices()
        except Exception as exc:  # noqa: BLE001
            log.info("枚举音频设备失败：%s", exc)
            return []

    def audio_slot_name(self, key: str) -> str:
        did = (getattr(self.cfg, key, "") or "").strip()
        if not did:
            return ""
        for dev_id, name in self._audio_devices():
            if dev_id.lower() == did.lower():
                return name
        return ""

    def current_audio_name(self) -> str:
        try:
            return audioout.device_name(audioout.get_default_render())
        except Exception:  # noqa: BLE001
            return ""

    def audio_switch_target(self):
        """返回 (目标设备 id, 目标设备名, 提示)。"""
        a = (getattr(self.cfg, "audio_a", "") or "").strip()
        b = (getattr(self.cfg, "audio_b", "") or "").strip()
        if not a and not b:
            return None, "先到「设置 → 音频」里选两个设备", ""
        try:
            cur = (audioout.get_default_render() or "").lower()
        except Exception:  # noqa: BLE001
            cur = ""
        devices = {dev.lower(): name for dev, name in self._audio_devices()}

        if a and cur != a.lower():
            want = a
        elif b and cur != b.lower():
            want = b
        else:
            want = b or a
        if not want:
            return None, "另一个设备位还没选", ""
        name = devices.get(want.lower(), "")
        if not name:
            return None, "没找到那个设备（可能拔了或没开机）", ""
        return want, name, ""

    def toggle_audio_output(self) -> None:
        want, name, err = self.audio_switch_target()
        if not want:
            self.toast(name or "切换不了", False)
            self.audio_osd.show_device(name or "切换不了", warn=True)
            return
        ok, msg = audioout.set_default_render(want)
        if not ok:
            self.toast("切换失败：" + (msg or "未知原因"), False)
            self.audio_osd.show_device("切换失败", warn=True)
            return
        self._log_auto(f"音频输出 → {name}")
        self.toast(f"输出：{name}")
        self.audio_osd.show_device(name)
        self.refresh_audio_tray()
        self._rebind_music_output()

    def _rebind_music_output(self) -> None:
        """刚换过系统输出设备：让正在播的音乐也跟着换过去。

        Qt 的默认设备列表是异步刷新的，等它一下再重建，不然新输出又绑回旧设备。
        """
        player = getattr(self, "player", None)
        if player is None:
            return

        def go():
            try:
                moved = player.rebind_output()
                if moved:
                    log.info("音乐输出已跟随新设备重建")
            except Exception as exc:  # noqa: BLE001
                log.warning("重建音乐输出失败：%s", exc)

        QtCore.QTimer.singleShot(380, go)

    def switch_audio_to(self, key: str) -> None:
        did = (getattr(self.cfg, key, "") or "").strip()
        if not did:
            self.toast("这个设备位还没选设备", False)
            return
        name = ""
        for dev_id, dev_name in self._audio_devices():
            if dev_id.lower() == did.lower():
                name = dev_name
                break
        if not name:
            self.toast("没找到那个设备（可能拔了或没开机）", False)
            return
        ok, msg = audioout.set_default_render(did)
        if ok:
            self.toast(f"输出：{name}")
            self.audio_osd.show_device(name)
            self.refresh_audio_tray()
            self._rebind_music_output()
        else:
            self.toast("切换失败：" + (msg or "未知原因"), False)

    def set_audio_slot(self, key: str, device_id) -> None:
        other = "audio_b" if key == "audio_a" else "audio_a"
        if device_id and getattr(self.cfg, other, "") == device_id:
            self.toast("两个槽位不能选同一个设备", False)
            return
        setattr(self.cfg, key, device_id or "")
        self.cfg.save()
        if self.audio_tray is not None:
            self.audio_tray.rebuild()
        label = "A" if key == "audio_a" else "B"
        self.toast(f"设备 {label}：" + (self.audio_slot_name(key) or "已清空"))

    def _refresh_audio_btn(self) -> None:
        btn = getattr(self, "audio_btn", None)
        if btn is None:
            return
        name = self.current_audio_name() or ""
        btn.setIcon(audio_switch_icon(name, 24))
        btn.setToolTip(
            f"当前输出：{name or '没读到设备'}\n点一下切到另一个（热键 Alt+Z）"
        )

    def refresh_audio_tray(self) -> None:
        self._refresh_audio_btn()
        if self.audio_tray is not None:
            self.audio_tray.refresh()

    def open_audio_settings(self) -> None:
        self.show_settings()

    def show_settings(self) -> None:
        SettingsDialog(self).exec()
        self.refresh_resolution()

    def set_autostart_enabled(self, checked: bool) -> None:
        set_autostart(checked)
        self.toast("开机自启：" + ("已开启" if checked else "已关闭"))

    def set_hotkey_enabled(self, checked: bool) -> None:
        self.cfg.hotkey_enabled = checked
        self.cfg.save()
        if checked:
            self.reapply_hotkeys()
            total = len(HOTKEY_ACTIONS)
            ok = len(getattr(self, "hotkey_actual", {}) or {})
            self.toast(f"热键已启用，{ok}/{total} 个生效")
        else:
            self.hotkeys.unregister_all()
            self._hotkeys_registered = False
            self.hotkey_actual = {}
            self._update_hotkey_hint()
            self.toast("热键已关闭")

    def show_logs(self) -> None:
        LogDialog(self).exec()

    def show_about(self) -> None:
        AboutDialog(self).exec()

    def show_version_page(self) -> None:
        """托盘菜单：直接打开设置里的「版本与更新」。"""
        dlg = SettingsDialog(self)
        try:
            dlg.nav.setCurrentRow(dlg.nav.count() - 1)
        except Exception:  # noqa: BLE001
            pass
        dlg.exec()

    def showEvent(self, event: QtGui.QShowEvent) -> None:
        super().showEvent(event)
        set_dark_title_bar(self)
        if not getattr(self, "_autostart_checked", False):
            self._autostart_checked = True
            try:
                st = ensure_autostart()
                if st == "fixed":
                    log.info("开机自启项已改到当前程序：%s", _autostart_cmd())
                    QTimer.singleShot(1800, lambda: self.toast("开机自启已修好，下次开机会自己起来"))
                elif st == "enabled":
                    QTimer.singleShot(1800, lambda: self.toast("开机自启之前在启动项里被禁了，已重新打开"))
            except Exception as exc:  # noqa: BLE001
                log.warning("对着开机自启项失败：%s", exc)
        if not self._hotkeys_registered and self.cfg.hotkey_enabled:
            QTimer.singleShot(0, self.register_hotkeys)
        QTimer.singleShot(300, self._ensure_target_supported)
        if not getattr(self, "_tools_scanned", False):
            self._tools_scanned = True
            # 只在"这份配置还从没扫过"时扫一次（首次装好/刚升级）。
            # 之后不再自动扫盘，想识别新装的工具就点工具页顶部「刷新」。
            if not self.cfg.scan_stamp:
                QTimer.singleShot(1500, self.scan_tools_async)
        # 窗口真正上屏时把圆角按配置补一次：
        # 构造期调的 set_window_mode 那会儿窗口还没成形，裁出来是空的。
        try:
            self._apply_round_by_cfg()
        except Exception as exc:  # noqa: BLE001
            log.warning("上屏补圆角失败：%s", exc)

    def _on_music(self, snap: dict) -> None:
        # 系统媒体会话那条老通道已停用，这里留着给以后的小浮窗用
        self.music_last = snap

    def music_toggle(self) -> None:
        if getattr(self, "player", None) is None:
            return
        self.player.toggle()
        self.toast("音乐：播放 / 暂停")

    def music_next(self, quiet: bool = False) -> None:
        if getattr(self, "player", None) is None:
            return
        self.player.next()
        if not quiet:
            self.toast("音乐：下一首")

    def music_prev(self, quiet: bool = False) -> None:
        if getattr(self, "player", None) is None:
            return
        self.player.prev()
        if not quiet:
            self.toast("音乐：上一首")

    def _hotkey_bindings(self) -> dict:
        """动作 id → 真正要执行的函数。"""
        return {
            "toggle_resolution": self.toggle_resolution,
            "show_panel": self.show_panel,
            "shot_full": lambda: self.shot_full(),
            "shot_region": self.shot_region,
            "record": self.toggle_record,
            "replay_save": self.save_replay,
            "audio_toggle": self.toggle_audio_output,
            "music_toggle": self.music_toggle,
            "music_next": lambda: self.music_next(True),
            "music_prev": lambda: self.music_prev(True),
        }

    @staticmethod
    def _alt_keys(text: str) -> list:
        """原键被别的软件占用时，按顺序试的备选：加 Shift → 加 Win → 去掉 Alt 加 Shift。"""
        parsed = parse_hotkey(text)
        if not parsed:
            return []
        vk, mods = parsed
        out = []
        for m in (mods | MOD_SHIFT, mods | MOD_WIN, (mods & ~MOD_ALT) | MOD_SHIFT):
            if m == mods:
                continue
            t = format_hotkey(vk, m)
            if t not in out:
                out.append(t)
        return out

    def _register_one(self, key: str, want: str, cb, notes: list) -> str:
        """注册一个热键；被占用就依次试备选。返回真正生效的组合（全失败返回空串）。"""
        label = HOTKEY_LABEL.get(key, key)
        for text in [want] + self._alt_keys(want):
            parsed = parse_hotkey(text)
            if not parsed:
                log.warning("热键 %s 写法不对：%r", label, text)
                continue
            if self.hotkeys.register(parsed[0], parsed[1], cb):
                if text == want:
                    log.debug("热键 %s 注册成功（%s）", text, label)
                else:
                    log.warning("热键 %s 被占用，%s 改用 %s", want, label, text)
                    notes.append(f"{label} 的 {want} 被占用，已改用 {text}")
                return text
        log.warning("热键 %s（%s）注册失败，没有可用备选", want, label)
        notes.append(f"{label} 的 {want} 注册不上，换个键试试")
        return ""

    def register_mod_hotkey(self, spec, combo: str, fn) -> bool:
        """模组申请一个全局热键。写法不对或被占用返回 False。

        热键管理器没有单独注销，所以回调包一层：模组停用后按了也不动。
        """
        parsed = parse_hotkey(str(combo))
        if not parsed:
            log.warning("模组 %s 的热键写法不对：%r", spec.id, combo)
            return False
        vk, modifiers = parsed

        def guarded() -> None:
            rt = None
            try:
                rt = self.mod_view.registry.get(spec.id) if self.mod_view else None
            except Exception:  # noqa: BLE001
                rt = None
            if rt is not None and not rt.running:
                return
            try:
                fn()
            except Exception:  # noqa: BLE001
                log.error("模组 %s 的热键回调出错", spec.id, exc_info=True)

        if not self.hotkeys.register(vk, modifiers, guarded):
            log.warning("模组 %s 的热键 %s 被别的程序占用了", spec.id, combo)
            return False
        self._mod_hotkeys[(spec.id, str(combo))] = (vk, modifiers)
        log.info("模组 %s 注册热键 %s", spec.id, combo)
        return True

    def unregister_mod_hotkey(self, spec, combo: str) -> None:
        self._mod_hotkeys.pop((spec.id, str(combo)), None)

    def register_hotkeys(self) -> None:
        if self._hotkeys_registered:
            return
        self.hotkeys.attach(self)
        QtWidgets.QApplication.instance().installNativeEventFilter(self.hotkeys)
        self._hotkeys_registered = True
        self.hotkey_actual = {}
        notes: list = []
        for key, cb in self._hotkey_bindings().items():
            if not (self.cfg.hotkey_on or {}).get(key, True):
                log.info("热键 %s 已被单独关闭，跳过", HOTKEY_LABEL.get(key, key))
                continue
            want = (self.cfg.hotkeys or {}).get(key) or DEFAULT_HOTKEYS.get(key, "")
            actual = self._register_one(key, want, cb, notes)
            if actual:
                self.hotkey_actual[key] = actual
        self._update_hotkey_hint()
        if notes:
            msg = "；".join(notes)
            self.toast("热键：" + msg, False)
            tray = getattr(self, "tray", None)
            if tray is not None:
                tray.showMessage(
                    "热键冲突", msg, QtWidgets.QSystemTrayIcon.Warning, 6000
                )

    def set_hotkey_on(self, key: str, on: bool) -> None:
        """单个热键的开关：只影响这一个。"""
        self.cfg.hotkey_on[key] = bool(on)
        self.cfg.save()
        self.reapply_hotkeys()
        self.toast(f"{HOTKEY_LABEL.get(key, key)}：{'已启用' if on else '已关闭'}")

    def reapply_hotkeys(self) -> None:
        """改完键位后重新注册一遍（先把旧的注销掉，避免占着不放）。"""
        self.hotkeys.unregister_all()
        self._hotkeys_registered = False
        self.hotkey_actual = {}
        if self.cfg.hotkey_enabled:
            self.register_hotkeys()
        else:
            self._update_hotkey_hint()

    _HK_SHORT = {
        "toggle_resolution": "切分辨率",
        "show_panel": "面板",
        "shot_full": "截图",
        "shot_region": "框选",
        "record": "录屏",
        "replay_save": "存回放",
        "audio_toggle": "切音频",
    }

    def _update_hotkey_hint(self) -> None:
        """主界面底下那行提示，改成"当前真正生效的键"，不再是写死的文案。"""
        lbl = getattr(self, "hotkey_hint", None)
        if lbl is None:
            return
        if not self.cfg.hotkey_enabled:
            lbl.setText("全局热键已关闭（设置里可以重新打开）")
            return
        actual = getattr(self, "hotkey_actual", {}) or {}
        parts = []
        for key, _label, _default in HOTKEY_ACTIONS:
            if not (self.cfg.hotkey_on or {}).get(key, True):
                parts.append(f"{self._HK_SHORT.get(key, key)} 已关")
                continue
            t = actual.get(key) or "未生效"
            parts.append(f"{self._HK_SHORT.get(key, key)} {t}")
        lbl.setText(" · ".join(parts))

    def shutdown_mods(self) -> None:
        """退出程序时，把由本程序启动的工具一起关掉，不留孤儿进程。"""
        stopped = []
        for mod in self.cfg.mods:
            if mod.kind != KIND_EXE:
                continue
            try:
                if not (self.guard.is_running(mod) or mod.pid):
                    continue
                ok, _msg = self.guard.stop(mod)
                if ok:
                    stopped.append(mod.name)
            except Exception:  # noqa: BLE001
                pass
        if stopped:
            log.info("退出：一并停掉工具 %s", " / ".join(stopped))

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        isle = getattr(self, "mode_island", None)
        if isle is not None:
            try:
                isle.hide()
            except Exception:  # noqa: BLE001
                pass
        if self._quitting or not self.cfg.close_to_tray:
            mb = getattr(self, "music_bar", None)
            if mb is not None:
                mb.hide()
            try:
                self._cast_shutdown()
            except Exception:  # noqa: BLE001
                pass
            # 退出前把显示器曲线还原，别把屏留在滤镜状态
            fw = getattr(self, "filter_win", None)
            if fw is not None:
                try:
                    fw.shutdown(force=True)
                except Exception:  # noqa: BLE001
                    screenfilter.restore_all()
            try:
                self._gm_restore()
            except Exception:  # noqa: BLE001
                pass
            event.accept()
            return
        event.ignore()
        self.hide()
        if not self.cfg.tray_tip_shown and self.tray is not None:
            self.tray.showMessage(
                APP_NAME,
                "程序已收进托盘，双击图标可以再打开；右键菜单可切换分辨率或启动工具。",
                QtWidgets.QSystemTrayIcon.Information,
                4000,
            )
            self.cfg.tray_tip_shown = True
            self.cfg.save()

    tray: Optional["AppTray"] = None


# ---------------------------------------------------------------------------
# 托盘
# ---------------------------------------------------------------------------
class AudioTray(QtWidgets.QSystemTrayIcon):
    """状态栏里的独立小喇叭：双击就切，右键能指定切到 A 还是 B。"""

    def __init__(self, win: MainWindow):
        super().__init__(audio_icon_pixmap("", 22), win)
        self.win = win
        self.menu = QtWidgets.QMenu()
        self.menu.setStyleSheet(qss())
        self.menu.aboutToShow.connect(self.rebuild)
        self.activated.connect(self._on_activate)
        self.refresh()

    def refresh(self) -> None:
        name = self.win.current_audio_name() or "没读到设备"
        self.setIcon(audio_icon_pixmap(name, 22))
        self.setToolTip(
            f"燧镜 · 音频输出：{name}\n双击就在 A / B 之间切（热键 Alt+Z 也一样）"
        )

    def rebuild(self) -> None:
        m = self.menu
        m.clear()
        cur = self.win.current_audio_name() or "—"
        item = m.addAction(f"当前：{cur}")
        item.setEnabled(False)
        m.addSeparator()

        a = self.win.audio_slot_name("audio_a")
        b = self.win.audio_slot_name("audio_b")
        act_a = m.addAction(f"切到 A   {a or '（没选）'}")
        act_a.setEnabled(bool(a))
        act_a.triggered.connect(lambda: self.win.switch_audio_to("audio_a"))
        act_b = m.addAction(f"切到 B   {b or '（没选）'}")
        act_b.setEnabled(bool(b))
        act_b.triggered.connect(lambda: self.win.switch_audio_to("audio_b"))

        m.addSeparator()
        m.addAction("设备设置…").triggered.connect(self.win.open_audio_settings)
        m.addAction("打开面板").triggered.connect(self.win.show_panel)

    def _on_activate(self, reason) -> None:
        if reason == QtWidgets.QSystemTrayIcon.Context:
            self.rebuild()
            self.menu.exec(QtGui.QCursor.pos())
            return
        if reason in (
            QtWidgets.QSystemTrayIcon.DoubleClick,
            QtWidgets.QSystemTrayIcon.Trigger,
        ):
            self.win.toggle_audio_output()


class AppTray(QtWidgets.QSystemTrayIcon):
    def __init__(self, win: MainWindow, guard: ProcessGuard, cfg: Config):
        super().__init__(app_icon(), win)
        self.win = win
        self.guard = guard
        self.cfg = cfg
        win.tray = self
        win.tray_owner = self

        self.menu = QtWidgets.QMenu()
        self.menu.setStyleSheet(qss())
        self.menu.aboutToShow.connect(self.rebuild)
        self.activated.connect(self._on_activate)
        self.setToolTip(APP_NAME)

    def _on_activate(self, reason) -> None:
        if reason == QtWidgets.QSystemTrayIcon.Context:
            # 手动弹菜单：Windows 自带的多级子菜单定位会串项
            self.rebuild()
            self.menu.exec(QtGui.QCursor.pos())
            return
        if reason in (
            QtWidgets.QSystemTrayIcon.DoubleClick,
            QtWidgets.QSystemTrayIcon.Trigger,
        ):
            self.win.show_panel()

    def win_state_text(self) -> list:
        """菜单和悬停提示共用的状态串：录屏 / 回放 / 帧率灯 / 密码窗 / ACE。"""
        try:
            parts = [
                "录屏中" if getattr(self.win.recorder, "is_recording", False) else "未录屏",
                "回放 开" if getattr(self.win.replay, "is_running", False) else "回放 关",
                "帧率灯 开" if getattr(self.cfg, "fps_show", False) else "帧率灯 关",
                "密码窗 开" if getattr(self.cfg, "hud_show", False) else "密码窗 关",
            ]
            badge = getattr(self.win, "ace_badge", None)
            if badge is not None and badge.text():
                parts.append("反作弊 " + badge.text())
            return parts
        except Exception:  # noqa: BLE001
            return ["状态读取失败"]

    def mark_dirty(self) -> None:
        """状态变化时把菜单标脏，下次打开前重建。"""
        self._dirty = True

    def rebuild(self) -> None:
        m = self.menu
        m.clear()

        w, h = display.get_current()
        nw, nh, _ = self.cfg.native
        state = self.win_state_text()
        self.setToolTip(
            f"{APP_NAME}  ·  {w} × {h} ({ratio_text(w, h)})\n"
            f"目标档位 {self.cfg.target[0]} × {self.cfg.target[1]} -> 原生 {nw} × {nh}\n"
            + " · ".join(state)
        )

        act_panel = m.addAction("打开控制面板  (Ctrl+Alt+M)")
        act_panel.triggered.connect(self.win.show_panel)

        act_panic = m.addAction("全部还原  （出问题先点这个）")
        act_panic.setToolTip("分辨率回原生、反作弊优化还原、关帧率灯、关回放、关悬浮窗、录音先保存")
        act_panic.triggered.connect(self.win.panic_restore)

        # 状态不再是"只能看不许动"：勾上就是开着，点一下就切
        m.addSeparator()
        a_fps = m.addAction("帧率悬浮窗")
        a_fps.setCheckable(True)
        a_fps.setChecked(bool(getattr(self.cfg, "fps_show", False)))
        a_fps.triggered.connect(lambda _checked: self.win.toggle_fps())

        a_replay = m.addAction("回放缓冲（最近 12 分钟）")
        a_replay.setCheckable(True)
        a_replay.setChecked(bool(getattr(self.win.replay, "is_running", False)))
        a_replay.triggered.connect(lambda _checked: self.win.toggle_replay())

        a_rec = m.addAction("录屏")
        a_rec.setCheckable(True)
        a_rec.setChecked(bool(getattr(self.win.recorder, "is_recording", False)))
        a_rec.triggered.connect(lambda _checked: self.win.toggle_record())

        a_ace = m.addAction("反作弊优化")
        a_ace.setCheckable(True)
        badge = getattr(self.win, "ace_badge", None)
        limited = bool(badge is not None and badge.text() and "已限制" in badge.text())
        a_ace.setChecked(limited)
        a_ace.setToolTip("勾上 = 反作弊扫描进程已压到最低优先级；取消 = 还原")
        a_ace.triggered.connect(
            lambda checked: self.win.ace_apply(True) if checked else self.win.ace_restore()
        )


        # 音频输出：小喇叭图标在 Win11 里可能被折叠，这里留一条常走的路
        a_name = self.win.audio_slot_name("audio_a")
        b_name = self.win.audio_slot_name("audio_b")
        cur_audio = self.win.current_audio_name() or "没读到设备"
        sub_audio = m.addMenu(f"音频输出：{cur_audio}")
        sub_audio.addAction("在这两台之间切一下（同 Alt+Z）").triggered.connect(
            self.win.toggle_audio_output
        )
        sub_audio.addSeparator()
        act_a = sub_audio.addAction(f"切到 A   {a_name or '（没选）'}")
        act_a.setEnabled(bool(a_name))
        act_a.triggered.connect(lambda: self.win.switch_audio_to("audio_a"))
        act_b = sub_audio.addAction(f"切到 B   {b_name or '（没选）'}")
        act_b.setEnabled(bool(b_name))
        act_b.triggered.connect(lambda: self.win.switch_audio_to("audio_b"))
        sub_audio.addSeparator()
        sub_audio.addAction("音频设置…").triggered.connect(self.win.open_audio_settings)
        m.addSeparator()

        # 每一段都单独兜底：某段出错只丢这一段，别把后面的项一起吞了
        for step in (
            self._sec_shot,
            self._sec_hud,
            self._sec_resolution,
            self._sec_mods,
            self._sec_rules,
            self._sec_settings,
        ):
            try:
                step(m)
            except Exception as exc:  # noqa: BLE001
                self._log_menu_error(step.__name__, exc)

        m.addSeparator()
        a_quit = m.addAction("退出")
        a_quit.triggered.connect(self._on_quit)

    def _log_menu_error(self, where: str, exc: Exception) -> None:
        try:
            with open(app_dir() / "tray_error.log", "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{where}] {exc!r}\n")
        except OSError:
            pass

    def _sec_shot(self, m) -> None:
        sub = m.addMenu("截图")
        sub.addAction("全屏截图  (Ctrl+Alt+S)", self.win.shot_full)
        sub.addAction("框选截图  (Ctrl+Alt+Shift+S)", self.win.shot_region)
        sub.addAction("3 秒后截当前窗口", self.win.shot_delayed)
        sub.addSeparator()
        sub.addAction("显示 / 隐藏帧率悬浮窗", self.win.toggle_fps)
        sub.addAction("开始 / 停止录屏  (Ctrl+Alt+V)", self.win.toggle_record)
        sub.addAction("开启 / 关闭回放缓冲", self.win.toggle_replay)
        sub.addAction("保存最近 10 分钟  (Ctrl+Alt+B)", self.win.save_replay)
        sub.addSeparator()
        sub.addAction("打开素材页", self.win.show_media)

    def _sec_hud(self, m) -> None:
        act_hud = m.addAction("每日密码悬浮窗")
        act_hud.setCheckable(True)
        act_hud.setChecked(bool(getattr(self.cfg, "hud_show", False)))
        act_hud.triggered.connect(self.win.set_hud_enabled)

        sub_hud_pos = m.addMenu("悬浮窗位置")
        for label, key in (("左侧", "left"), ("右侧", "right")):
            a_pos = sub_hud_pos.addAction(label)
            a_pos.setCheckable(True)
            a_pos.setChecked(getattr(self.cfg, "hud_side", "right") == key)
            a_pos.triggered.connect(lambda _=False, k=key: self.win.set_hud_side(k))

    def _sec_resolution(self, m) -> None:
        w, h = display.get_current()
        tw, th = self.cfg.target
        nw, nh, _ = self.cfg.native

        if (w, h) == (tw, th):
            text = f"恢复原生  {nw} × {nh}  (Ctrl+Alt+R)"
        else:
            text = f"切换为 {display.ratio_group(tw, th)}  {tw} × {th}  (Ctrl+Alt+R)"
        act_res = m.addAction(text)
        act_res.triggered.connect(self.win.toggle_resolution)

        if (w, h) != (nw, nh):
            act_back = m.addAction(f"回到原生  {nw} × {nh}")
            act_back.triggered.connect(self.win.restore_native)

        cur_ratio = m.addAction(
            f"当前：{w} × {h}  ({ratio_text(w, h)})  ·  原生 {nw} × {nh}"
        )
        cur_ratio.setEnabled(False)
        m.addSeparator()

    def _sec_mods(self, m) -> None:
        sub = m.addMenu("工具")
        enabled_mods = [x for x in self.cfg.mods if x.enabled]
        if not enabled_mods:
            empty = sub.addAction("（没有启用的工具）")
            empty.setEnabled(False)
        for mod in enabled_mods:
            running = mod.kind == KIND_EXE and self.guard.is_running(mod)
            if not mod.exists:
                label = f"⚠ {mod.name}（文件丢失）"
                a = sub.addAction(label)
                a.setEnabled(False)
                continue
            if mod.kind != KIND_EXE:
                label = f"↗ {mod.name}"
            elif running:
                label = f"■ 停止  {mod.name}"
            else:
                label = f"▶ 启动  {mod.name}"
            action = sub.addAction(label)
            action.triggered.connect(lambda _=False, x=mod: self._toggle_mod(x))

    def _sec_rules(self, m) -> None:
        sub2 = m.addMenu("自动化")
        if not self.cfg.rules:
            empty_rule = sub2.addAction("（还没有规则）")
            empty_rule.setEnabled(False)
        else:
            for rule in self.cfg.rules:
                mark = "●" if rule.enabled else "○"
                a_rule = sub2.addAction(f"{mark} {rule.name}")
                a_rule.triggered.connect(
                    lambda _=False, r=rule: self.win.run_rule(r, "托盘菜单")
                )
        sub2.addSeparator()
        a_rule_edit = sub2.addAction("编排自动化…")
        a_rule_edit.triggered.connect(self.win.show_automation)

    def _sec_settings(self, m) -> None:
        sub3 = m.addMenu("设置")
        a_open_settings = sub3.addAction("打开设置面板…")
        a_open_settings.triggered.connect(self.win.show_settings)
        a_guide = sub3.addAction("新手引导（怎么用）")
        a_guide.triggered.connect(lambda: self.win.show_guide(force=True))
        sub3.addSeparator()

        a_auto = sub3.addAction("开机自启")
        a_auto.setCheckable(True)
        a_auto.setChecked(autostart_enabled())
        a_auto.triggered.connect(self._on_autostart)

        a_hk = sub3.addAction("启用全局热键")
        a_hk.setCheckable(True)
        a_hk.setChecked(self.cfg.hotkey_enabled)
        a_hk.triggered.connect(self._on_hotkey_switch)

        a_stretch = sub3.addAction("嘉豪模式（4:3 拉满去黑边）")
        a_stretch.setCheckable(True)
        a_stretch.setChecked(self.cfg.stretch)
        a_stretch.triggered.connect(
            lambda checked: self.win.set_stretch(checked, silent=True)
        )

        a_trayclose = sub3.addAction("关闭窗口时收进托盘")
        a_trayclose.setCheckable(True)
        a_trayclose.setChecked(self.cfg.close_to_tray)
        a_trayclose.triggered.connect(self._on_tray_close)

        sub3.addSeparator()
        a_dir = sub3.addAction("打开程序目录")
        a_dir.triggered.connect(lambda: os.startfile(str(app_dir())))
        a_about = sub3.addAction(f"版本与更新（{APP_VERSION}）")
        a_about.triggered.connect(self.win.show_version_page)

    def _toggle_mod(self, mod: Mod) -> None:
        if mod.kind == KIND_EXE and self.guard.is_running(mod):
            ok, msg = self.guard.stop(mod)
            self.win.toast(msg, ok)
        else:
            self.win.launch_mod(mod)
        for card in self.win.cards:
            card.refresh()
        for tile in self.win.tiles:
            tile.refresh()

    def _on_autostart(self, checked: bool) -> None:
        self.win.set_autostart_enabled(checked)

    def _on_hotkey_switch(self, checked: bool) -> None:
        self.win.set_hotkey_enabled(checked)

    def _on_tray_close(self, checked: bool) -> None:
        self.cfg.close_to_tray = checked
        self.cfg.save()
        self.win.toast("关闭窗口：" + ("收进托盘" if checked else "直接退出程序"))

    def _on_quit(self) -> None:
        self.win._quitting = True
        self.cfg.save()
        try:
            self.win.hotkeys.unregister_all()
        except Exception:
            pass
        QtWidgets.QApplication.quit()


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------
def _keep_tray_visible() -> None:
    """启动一会儿后把本程序的托盘条目改成常驻显示；失败不影响任何功能。"""
    try:
        traypin.promote()
    except Exception:  # noqa: BLE001
        pass


def run(show_panel: bool = True) -> int:
    """启动完整界面（主实例）。show_panel=False 时静默进托盘。"""
    mutex = ipc.acquire_mutex()
    if mutex is None:
        # 自检模式：无视已有实例，照常起界面（自检进程短命，不会常驻抢窗口）
        if any(flag in sys.argv for flag in ("--shot", "--shot-page", "--shot-settings", "--shot-about", "--rec-check", "--replay-check", "--audio-check", "--fps-check", "--main")):
            pass
        elif "--tray" in sys.argv:
            return 0
        else:
            # 已有实例时只请求打开面板，绝不顺手切分辨率
            ipc.send_command("show")
            return 0

    ipc.clear_command()

    # 内嵌浏览器（音乐页的网页登录窗）要求这条，必须赶在 QApplication 之前
    QtCore.QCoreApplication.setAttribute(
        Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True
    )
    QtWidgets.QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setWindowIcon(app_icon())
    app.setQuitOnLastWindowClosed(False)
    app.setFont(QtGui.QFont("Microsoft YaHei UI", 9))

    cfg = Config()
    guard = ProcessGuard()
    hotkeys = HotkeyManager()
    win = MainWindow(cfg, guard, hotkeys)
    # 不管从托盘退出、关窗口还是别的方式退出，都先把挂着的工具关掉
    app.aboutToQuit.connect(win.shutdown_mods)

    if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
        tray = AppTray(win, guard, cfg)
        tray.show()
        # 图标掉进「隐藏的图标菜单」是 Windows 记的账，启动后把自己那条改回来
        QTimer.singleShot(1600, lambda: _keep_tray_visible())

        if getattr(cfg, "audio_tray_icon", True):
            audio_tray = AudioTray(win)
            audio_tray.show()
            win.audio_tray = audio_tray
            log.info(
                "托盘：主图标 %s / 音频图标 %s（%s）",
                "已显示" if tray.isVisible() else "未显示",
                "已显示" if audio_tray.isVisible() else "未显示",
                audio_tray.toolTip().split("\n")[0],
            )
        else:
            win.audio_tray = None
            log.info("托盘：只用了主图标（小喇叭图标按设置在设置里关掉了）")

    # 随框架启动的工具
    for mod in cfg.mods:
        if mod.enabled and mod.autostart and mod.exists:
            guard.launch(mod)
            log.info("自动启动工具：%s", mod.name)

    win.show()

    if not show_panel:
        win.hide()
        if QtWidgets.QSystemTrayIcon.isSystemTrayAvailable() and win.tray is not None:
            win.tray.showMessage(
                APP_NAME,
                "已在后台待命，双击托盘图标可以打开面板。",
                QtWidgets.QSystemTrayIcon.Information,
                2500,
            )
        else:
            win.show()

    # 自检截图
    shot = None
    if "--shot" in sys.argv:
        i = sys.argv.index("--shot")
        if i + 1 < len(sys.argv):
            shot = sys.argv[i + 1]

    if shot:
        def _grab():
            try:
                win.grab().save(shot, "PNG")
                print(f"截图已保存：{shot}")
            except Exception as exc:
                print(f"截图失败：{exc}")
            app.exit(0)
            os._exit(0)

        QTimer.singleShot(1200, _grab)

    # 自检截图：指定页面（--shot-page 页面属性名 文件），用来给模组页、工具页各自留档
    pg_shot = None
    pg_attr = ""
    if "--shot-page" in sys.argv:
        i = sys.argv.index("--shot-page")
        if i + 2 < len(sys.argv):
            pg_attr = sys.argv[i + 1]
            pg_shot = sys.argv[i + 2]

    if pg_shot:

        def _grab_page_now():
            try:
                win.grab().save(pg_shot, "PNG")
                print(f"截图已保存：{pg_shot}")
            except Exception as exc:  # noqa: BLE001
                print(f"截图失败：{exc}")
            app.exit(0)
            os._exit(0)

        def _grab_page():
            try:
                win._goto(pg_attr)
                win.repaint()
            except Exception as exc:  # noqa: BLE001
                print(f"切页失败：{exc}")
            QTimer.singleShot(700, _grab_page_now)

        QTimer.singleShot(1200, _grab_page)

    # 自检截图：设置页（第二个参数可选：第几个分类，0 开始）
    st_shot = None
    st_row = 5
    if "--shot-settings" in sys.argv:
        i = sys.argv.index("--shot-settings")
        if i + 1 < len(sys.argv):
            st_shot = sys.argv[i + 1]
        if i + 2 < len(sys.argv) and sys.argv[i + 2].isdigit():
            st_row = int(sys.argv[i + 2])

    if st_shot:
        st_dlg = SettingsDialog(win)
        st_dlg.show()
        try:
            st_dlg.nav.setCurrentRow(st_row)
        except Exception:  # noqa: BLE001
            pass

        def _grab_settings():
            try:
                st_dlg.grab().save(st_shot, "PNG")
                print(f"设置页截图已保存：{st_shot}")
            except Exception as exc:  # noqa: BLE001
                print(f"设置页截图失败：{exc}")
            app.quit()

        QTimer.singleShot(900, _grab_settings)

    # 录屏自检（打包后验证多媒体插件是否可用）
    if "--rec-check" in sys.argv:
        def _rec_start():
            ok, msg = win.recorder.start()
            def _rec_stop():
                path = win.recorder.stop()
                info = f"start={ok} msg={msg}\npath={path}\n"
                try:
                    info += f"size={path.stat().st_size if path and path.exists() else 0}\n"
                except Exception:
                    pass
                try:
                    (app_dir() / "rec_check.txt").write_text(info, encoding="utf-8")
                except Exception:
                    pass
                QTimer.singleShot(600, app.quit)
            QTimer.singleShot(4000, _rec_stop)
        QTimer.singleShot(1500, _rec_start)

    # 声音自检（打包后验证 loopback 是否可用）
    if "--audio-check" in sys.argv:
        def _ac_start():
            from core import audio as _audio_mod
            info = [f"available={_audio_mod.LoopbackRecorder.available()}"]
            rec = _audio_mod.LoopbackRecorder()
            ok = rec.start(app_dir() / "audio_check.wav")
            info.append(f"start={ok} err={rec.error_text[:80]}")

            def _ac_stop():
                dur = rec.duration()
                p = rec.stop()
                size = Path(p).stat().st_size if p else 0
                info.append(f"dur={dur:.1f} size={size}")
                try:
                    (app_dir() / "audio_check.txt").write_text("\n".join(info), encoding="utf-8")
                except Exception:
                    pass
                QTimer.singleShot(300, app.quit)

            QTimer.singleShot(3000, _ac_stop)

        QTimer.singleShot(1200, _ac_start)

    # 帧率自检（打包后验证 PresentMon 能不能读出来）
    if "--fps-check" in sys.argv:
        def _fc_start():
            lines = [f"presentmon={fps.presentmon_path()}"]
            lines.append(f"foreground={fps.process_name(fps.foreground_pid())}")
            ok = win.fps_mon.start()
            lines.append(f"start={ok} err={win.fps_mon.error_text[:80]}")
            win.fps_hud.show_hud()

            def _fc_stop():
                lines.append(f"fps={win.fps_mon.current:.1f}")
                try:
                    (app_dir() / "fps_check.txt").write_text(chr(10).join(lines), encoding="utf-8")
                except Exception:
                    pass
                win.fps_mon.stop()
                win.fps_hud.hide_hud()
                QTimer.singleShot(300, app.quit)

            QTimer.singleShot(6000, _fc_stop)

        QTimer.singleShot(1500, _fc_start)

    # 回放自检（打包后验证 ffmpeg 是否跑得起来）
    if "--replay-check" in sys.argv:
        def _rp_start():
            ok, msg = win.replay.start()
            def _rp_save():
                ok2, msg2 = win.replay.save(1)
                info = f"start={ok} {msg}\nsave={ok2} {msg2}\n"
                try:
                    p = Path(msg2)
                    info += f"size={p.stat().st_size if p.exists() else 0}\n"
                except Exception:
                    pass
                try:
                    (app_dir() / "replay_check.txt").write_text(info, encoding="utf-8")
                except Exception:
                    pass
                win.replay.stop()
                QTimer.singleShot(500, app.quit)
            QTimer.singleShot(18000, _rp_save)
        QTimer.singleShot(1500, _rp_start)

    about_shot = None
    if "--shot-about" in sys.argv:
        i = sys.argv.index("--shot-about")
        if i + 1 < len(sys.argv):
            about_shot = sys.argv[i + 1]

    if about_shot:
        dlg = AboutDialog(win)
        dlg.show()

        def _grab_about():
            try:
                dlg.grab().save(about_shot, "PNG")
                print(f"关于页截图已保存：{about_shot}")
            except Exception as exc:
                print(f"关于页截图失败：{exc}")
            app.quit()

        QTimer.singleShot(900, _grab_about)

    return app.exec()


if __name__ == "__main__":
    sys.exit(run())
