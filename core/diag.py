# -*- coding: utf-8 -*-
"""诊断：崩溃捕获 / 日志读取 / 一键导出诊断包"""
from __future__ import annotations

import logging
import platform
import sys
import traceback
import zipfile
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path

MAX_BYTES = 4 * 1024 * 1024
BACKUPS = 2


def log_dir() -> Path:
    from .store import app_dir

    d = app_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ensure_handler() -> None:
    """保证日志一定落盘。--noconsole 下没有控制台，这是唯一能看到错误的地方。"""
    root = logging.getLogger()
    if root.handlers:
        return
    h = RotatingFileHandler(
        log_dir() / "app.log",
        maxBytes=MAX_BYTES,
        backupCount=BACKUPS,
        encoding="utf-8",
    )
    h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    root.addHandler(h)
    root.setLevel(logging.INFO)


def _flush() -> None:
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass


def install_excepthook() -> None:
    """接住所有没被处理的异常，写进日志。"""
    ensure_handler()

    def hook(etype, value, tb):
        logging.getLogger("gamehub").critical(
            "未捕获异常：%s: %s\n%s",
            getattr(etype, "__name__", etype),
            value,
            "".join(traceback.format_exception(etype, value, tb)),
        )
        _flush()

    sys.excepthook = hook
    try:
        import threading

        def thook(args):
            logging.getLogger("gamehub").critical(
                "线程 %s 崩了：%s: %s\n%s",
                getattr(args.thread, "name", "?"),
                getattr(args.exc_type, "__name__", args.exc_type),
                args.exc_value,
                "".join(
                    traceback.format_exception(
                        args.exc_type, args.exc_value, args.exc_traceback
                    )
                ),
            )
            _flush()

        threading.excepthook = thook
    except Exception:
        pass


def log_files() -> list[Path]:
    d = log_dir()
    files = [p for p in d.glob("app.log*") if p.is_file()]
    return sorted(files, key=lambda p: p.stat().st_mtime)


def tail(lines: int = 400) -> str:
    ensure_handler()
    _flush()
    chunks = []
    for p in log_files():
        try:
            chunks.append(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
    rows = "\n".join(chunks).splitlines()
    if len(rows) > lines:
        rows = ["…… 更早的日志已省略 ……"] + rows[-lines:]
    return "\n".join(rows)


def environment() -> str:
    out = ["生成时间：" + datetime.now().strftime("%Y-%m-%d %H:%M:%S")]
    out.append("系统：" + platform.platform())
    out.append(
        "Python " + sys.version.split()[0] + "（打包运行：" + ("是" if getattr(sys, "frozen", False) else "否") + "）"
    )
    try:
        from PySide6 import QtCore

        out.append("Qt：" + QtCore.qVersion())
    except Exception:
        pass
    try:
        from . import display

        w, h, hz = display.detect_native()
        out.append(f"原生分辨率：{w}x{h} @ {hz}Hz")
    except Exception:
        pass
    try:
        import psutil

        vm = psutil.virtual_memory()
        out.append(f"内存：{vm.percent}% / {vm.total >> 30}G")
        out.append(f"CPU 核心：{psutil.cpu_count()} 负载 {psutil.cpu_percent(interval=0.3)}%")
    except Exception:
        pass
    keys = ("ace", "ffmpeg", "presentmon", "wegame", "delta", "燧镜", "qtwebengine", "tencent")
    procs = []
    try:
        import psutil

        for p in psutil.process_iter(["name"]):
            n = (p.info.get("name") or "").lower()
            if n.endswith(".exe") and any(k in n for k in keys):
                procs.append(p.info["name"])
    except Exception:
        pass
    out.append("相关进程：" + (", ".join(sorted(set(procs))) if procs else "无"))
    return "\n".join(out)


def export_bundle(target: Path | None = None) -> Path:
    """把日志 + 配置 + 环境信息打包成一个 zip，方便直接发出来定位问题。"""
    ensure_handler()
    _flush()
    if target is None:
        target = log_dir() / ("诊断包_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".zip")
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        for p in log_files():
            try:
                z.writestr("logs/" + p.name, p.read_text(encoding="utf-8", errors="replace"))
            except Exception:
                continue
        try:
            from .store import app_dir

            cfg = app_dir() / "config.json"
            if cfg.exists():
                z.writestr("config.json", cfg.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            pass
        z.writestr("环境.txt", environment())
    return target


def clear_logs() -> None:
    for p in log_files():
        try:
            p.unlink()
        except Exception:
            pass
    logging.getLogger("gamehub").info("日志已清空")
