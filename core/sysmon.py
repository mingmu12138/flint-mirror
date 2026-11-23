# -*- coding: utf-8 -*-
"""系统监控：CPU / 内存 / 显卡占用 / 显卡温度。

CPU 和内存用 psutil；显卡走 nvidia-smi（N 卡）。没有 nvidia-smi 就显示 --，
不假装有数据。
"""

from __future__ import annotations

import shutil
import subprocess
from typing import Dict, Optional

from PySide6 import QtCore

CREATE_NO_WINDOW = 0x08000000
QUERY = "utilization.gpu,memory.used,memory.total,temperature.gpu"


def _nvidia_smi() -> Optional[str]:
    for cand in (
        shutil.which("nvidia-smi"),
        r"C:\Windows\System32\nvidia-smi.exe",
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ):
        if cand and __import__("pathlib").Path(cand).exists():
            return str(cand)
    return None


def gpu_stats() -> Dict[str, Optional[float]]:
    """返回 {'util': %, 'mem_used': MB, 'mem_total': MB, 'temp': °C}，取不到就是 None。"""
    empty = {"util": None, "mem_used": None, "mem_total": None, "temp": None}
    exe = _nvidia_smi()
    if not exe:
        return empty
    try:
        out = subprocess.run(
            [exe, "--query-gpu=" + QUERY, "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=CREATE_NO_WINDOW,
        )
        line = (out.stdout or "").strip().splitlines()
        if not line:
            return empty
        parts = [p.strip() for p in line[0].split(",")]
        if len(parts) < 4:
            return empty

        def num(v: str) -> Optional[float]:
            try:
                return float(v)
            except ValueError:
                return None

        return {
            "util": num(parts[0]),
            "mem_used": num(parts[1]),
            "mem_total": num(parts[2]),
            "temp": num(parts[3]),
        }
    except Exception:
        return empty


class SysMon(QtCore.QObject):
    updated = QtCore.Signal(dict)

    def __init__(self, interval_ms: int = 2500, parent=None) -> None:
        super().__init__(parent)
        self._gpu_cache: Dict[str, Optional[float]] = {}
        self._gpu_ts = 0.0
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self._tick)
        self._interval = max(1000, int(interval_ms))

        try:
            import psutil

            self._psutil = psutil
            psutil.cpu_percent(interval=None)  # 先打一次基准，第一次读才是真值
        except Exception:
            self._psutil = None

    def start(self) -> None:
        self.timer.start(self._interval)
        self._tick()

    def stop(self) -> None:
        self.timer.stop()

    def _tick(self) -> None:
        self.updated.emit(self.snapshot())

    def snapshot(self) -> dict:
        data = {"cpu": None, "mem": None, "mem_used": None, "mem_total": None,
                "gpu": None, "gpu_mem": None, "gpu_mem_total": None, "temp": None}
        ps = self._psutil
        if ps is not None:
            try:
                data["cpu"] = ps.cpu_percent(interval=None)
                vm = ps.virtual_memory()
                data["mem"] = vm.percent
                data["mem_used"] = vm.used / (1024 ** 3)
                data["mem_total"] = vm.total / (1024 ** 3)
            except Exception:
                pass

        # nvidia-smi 启动一次要几十毫秒，别和 CPU 一样频繁刷
        import time

        now = time.time()
        if now - self._gpu_ts > 3 or not self._gpu_cache:
            self._gpu_cache = gpu_stats()
            self._gpu_ts = now
        g = self._gpu_cache
        data["gpu"] = g.get("util")
        data["temp"] = g.get("temp")
        if g.get("mem_used") is not None:
            data["gpu_mem"] = g["mem_used"] / 1024.0
        if g.get("mem_total") is not None:
            data["gpu_mem_total"] = g["mem_total"] / 1024.0
        return data
