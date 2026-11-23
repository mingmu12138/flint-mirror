# -*- coding: utf-8 -*-
"""硬件规格：CPU / 主板 / BIOS / 内存条 / 显卡 / 硬盘 / 显示器 / 系统 / 电源计划。

慢的走 WMI（一条 PowerShell 一次查完，2~5 秒），快的走注册表和 psutil。
进程内缓存，同一次运行里第二次打开秒开。
"""

from __future__ import annotations

import ctypes
import json
import os
import platform
import shutil
import subprocess
import time
from typing import Any, Dict, List, Optional

CREATE_NO_WINDOW = 0x08000000

MEM_TYPE = {
    20: "DDR", 21: "DDR2", 24: "DDR3", 26: "DDR4",
    27: "LPDDR", 28: "LPDDR2", 29: "LPDDR3", 30: "LPDDR4", 34: "DDR5", 35: "LPDDR5",
}
DISK_MEDIA = {"SSD": "固态", "HDD": "机械", "Unspecified": "", "SCM": "存储级"}
DISK_BUS = {"NVMe": "NVMe", "SATA": "SATA", "USB": "USB", "RAID": "RAID", "SCSI": "SCSI"}
WIN_NAME = {
    "10.0.26200": "Windows 11 25H2",
    "10.0.26100": "Windows 11 24H2",
    "10.0.22631": "Windows 11 23H2",
    "10.0.22621": "Windows 11 22H2",
    "10.0.22000": "Windows 11 21H2",
    "10.0.19045": "Windows 10 22H2",
    "10.0.19044": "Windows 10 21H2",
}

PS_SCRIPT = r"""
$ErrorActionPreference = 'SilentlyContinue'
$c   = Get-CimInstance Win32_ComputerSystem
$b   = Get-CimInstance Win32_BaseBoard
$bi  = Get-CimInstance Win32_BIOS
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
$mem = @(Get-CimInstance Win32_PhysicalMemory |
        Select-Object Capacity, Speed, Manufacturer, PartNumber,
                      SMBIOSMemoryType, DeviceLocator, ConfiguredClockSpeed)
$gpu = @(Get-CimInstance Win32_VideoController |
         Select-Object Name, AdapterRAM, DriverVersion, PNPDeviceID)
$pd  = @(Get-PhysicalDisk |
         Select-Object FriendlyName, MediaType, BusType, Size)
$dd  = @(Get-CimInstance Win32_DiskDrive |
         Select-Object Model, Size, InterfaceType, MediaType)
[pscustomobject]@{
  cpu    = @{ name = $cpu.Name; cores = $cpu.NumberOfCores;
              threads = $cpu.NumberOfLogicalProcessors;
              mhz = $cpu.MaxClockSpeed; l3 = $cpu.L3CacheSize }
  board  = @{ mfr = $b.Manufacturer; product = $b.Product }
  bios   = @{ vendor = $bi.Manufacturer; version = $bi.SMBIOSBIOSVersion;
              date = $bi.ReleaseDate }
  system = @{ mfr = $c.Manufacturer; model = $c.Model }
  mem    = $mem
  gpu    = $gpu
  pd     = $pd
  dd     = $dd
} | ConvertTo-Json -Depth 7 -Compress
"""

# ---------- 小工具 ----------


def firmware_type() -> str:
    try:
        kind = ctypes.c_uint(0)
        if not ctypes.windll.kernel32.GetFirmwareType(ctypes.byref(kind)):
            return ""
        return "UEFI" if kind.value in (2, 3, 5) else "BIOS"
    except Exception:  # noqa: BLE001
        return ""


def power_plan() -> str:
    """当前电源计划名。powercfg 输出是 GBK，不能直接当 utf-8 解。"""
    try:
        out = subprocess.run(
            ["powercfg", "/getactivescheme"],
            capture_output=True, timeout=6, creationflags=CREATE_NO_WINDOW,
        )
    except Exception:  # noqa: BLE001
        return ""
    raw = out.stdout or b""
    text = ""
    for enc in ("utf-8", "gbk", "cp936"):
        try:
            text = raw.decode(enc)
            break
        except Exception:  # noqa: BLE001
            continue
    text = text.strip()
    if "(" in text and ")" in text:
        return text[text.rindex("(") + 1: text.rindex(")")].strip()
    return ""


def _nvidia() -> List[dict]:
    """nvidia-smi 能给准显存和驱动版本；WMI 的 AdapterRAM 32 位会溢出。"""
    out = []
    for cand in (
        shutil.which("nvidia-smi"),
        r"C:\Windows\System32\nvidia-smi.exe",
        r"C:\Program Files\NVIDIA Corporation\NVSMI\nvidia-smi.exe",
    ):
        if not cand or not os.path.exists(cand):
            continue
        try:
            r = subprocess.run(
                [cand, "--query-gpu=name,memory.total,driver_version",
                 "--format=csv,noheader,nounits"],
                capture_output=True, text=True, timeout=6,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception:  # noqa: BLE001
            continue
        for line in (r.stdout or "").strip().splitlines():
            p = [x.strip() for x in line.split(",")]
            if len(p) >= 3:
                try:
                    mb = float(p[1])
                except ValueError:
                    mb = 0.0
                out.append({
                    "name": p[0],
                    "vram": round(mb / 1024.0, 1),
                    "driver": p[2],
                })
        break
    return out


def _ps_json() -> Optional[dict]:
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + PS_SCRIPT],
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=45, creationflags=CREATE_NO_WINDOW,
        )
    except Exception:  # noqa: BLE001
        return None
    text = (out.stdout or "").strip()
    if not text.startswith("{"):
        i = text.find("{")
        if i < 0:
            return None
        text = text[i:]
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


def _one(v: Any) -> dict:
    if isinstance(v, dict):
        return v
    if isinstance(v, list) and v:
        return v[0] if isinstance(v[0], dict) else {}
    return {}


def _many(v: Any) -> List[dict]:
    if isinstance(v, list):
        return [x for x in v if isinstance(x, dict)]
    if isinstance(v, dict):
        return [v]
    return []


def _gb(n: Any) -> float:
    try:
        return round(float(n) / (1024 ** 3), 1)
    except Exception:  # noqa: BLE001
        return 0.0


def _s(v: Any) -> str:
    return str(v).strip() if v is not None else ""


def _date(v: Any) -> str:
    """WMI 日期有两种：/Date(1631664000000)/ 或 20240115000000.000000+000。"""
    t = _s(v)
    if not t:
        return ""
    if t.startswith("/Date(") and t.endswith(")/"):
        try:
            ms = int(t[6:-2])
            return time.strftime("%Y-%m-%d", time.localtime(ms / 1000))
        except Exception:  # noqa: BLE001
            return ""
    if len(t) >= 8 and t[:8].isdigit():
        return f"{t[0:4]}-{t[4:6]}-{t[6:8]}"
    return t


def _n(v: Any) -> str:
    """15.0 → 15，476.9 → 476.9。"""
    try:
        f = float(v)
    except Exception:  # noqa: BLE001
        return str(v)
    return str(int(f)) if abs(f - int(f)) < 1e-9 else str(f)


def _win_name(build: str) -> str:
    if build in WIN_NAME:
        return WIN_NAME[build]
    if build.startswith("10.0.26"):
        return "Windows 11（预览版 " + build.rsplit(".", 1)[-1] + "）"
    return "Windows"


# ---------- 主入口 ----------

_CACHE: Optional[dict] = None


def read(force: bool = False) -> Dict[str, Any]:
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE

    import psutil

    raw = _ps_json() or {}

    cpu = _one(raw.get("cpu"))
    board = _one(raw.get("board"))
    bios = _one(raw.get("bios"))
    system = _one(raw.get("system"))

    # CPU
    name = _s(cpu.get("name"))
    if not name:
        try:
            import winreg
            with winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            ) as k:
                name = _s(winreg.QueryValueEx(k, "ProcessorNameString")[0])
        except Exception:  # noqa: BLE001
            pass
    l3 = cpu.get("l3") or 0
    cpu_info = {
        "name": name,
        "cores": cpu.get("cores"),
        "threads": cpu.get("threads"),
        "ghz": round((cpu.get("mhz") or 0) / 1000.0, 2) if cpu.get("mhz") else 0.0,
        "l3_mb": round(float(l3) / 1024.0, 1) if l3 else 0.0,
    }
    try:
        cpu_info["threads"] = cpu_info["threads"] or psutil.cpu_count()
        cpu_info["cores"] = cpu_info["cores"] or psutil.cpu_count(logical=False)
    except Exception:  # noqa: BLE001
        pass

    # 内存条
    sticks = []
    for s in _many(raw.get("mem")):
        sticks.append({
            "cap": _gb(s.get("Capacity")),
            "speed": s.get("ConfiguredClockSpeed") or s.get("Speed") or 0,
            "type": MEM_TYPE.get(s.get("SMBIOSMemoryType"), ""),
            "slot": _s(s.get("DeviceLocator")),
        })
    vm = psutil.virtual_memory()
    mem_info = {"total": _gb(vm.total), "count": len(sticks), "sticks": sticks}

    # 显卡：nvidia-smi 最准，WMI 兜底
    gpus = _nvidia()
    if not gpus:
        for g in _many(raw.get("gpu")):
            gname = _s(g.get("Name"))
            if not gname or "Microsoft Basic" in gname:
                continue
            gpus.append({
                "name": gname,
                "vram": _gb(g.get("AdapterRAM")) if g.get("AdapterRAM") else 0.0,
                "driver": _s(g.get("DriverVersion")),
            })
    if not gpus:
        gpus = _gpu_from_registry()

    # 硬盘：Get-PhysicalDisk 判断固态/机械最准，Win32_DiskDrive 兜底
    disks = []
    for d in _many(raw.get("pd")):
        disks.append({
            "model": _s(d.get("FriendlyName")),
            "size": _gb(d.get("Size")),
            "media": DISK_MEDIA.get(_s(d.get("MediaType")), _s(d.get("MediaType"))),
            "bus": DISK_BUS.get(_s(d.get("BusType")), _s(d.get("BusType"))),
        })
    if not disks:
        for d in _many(raw.get("dd")):
            disks.append({
                "model": _s(d.get("Model")),
                "size": _gb(d.get("Size")),
                "media": "",
                "bus": _s(d.get("InterfaceType")),
            })

    # 容量：以分区实际可用为准
    total_disk = 0.0
    total_free = 0.0
    try:
        for p in psutil.disk_partitions(all=False):
            if "cdrom" in p.opts or not p.fstype:
                continue
            try:
                u = psutil.disk_usage(p.mountpoint)
            except Exception:  # noqa: BLE001
                continue
            total_disk += u.total / (1024 ** 3)
            total_free += u.free / (1024 ** 3)
    except Exception:  # noqa: BLE001
        pass

    # 系统
    build = platform.win32_ver()[1] or platform.version()
    os_info = {
        "name": _win_name(build),
        "build": build,
        "arch": platform.machine(),
        "mode": firmware_type(),
        "power": power_plan(),
    }

    _CACHE = {
        "cpu": cpu_info,
        "board": {"mfr": _s(board.get("mfr")), "product": _s(board.get("product"))},
        "system": {"mfr": _s(system.get("mfr")), "model": _s(system.get("model"))},
        "bios": {
            "vendor": _s(bios.get("vendor")),
            "version": _s(bios.get("version")),
            "date": _date(bios.get("date")),
        },
        "mem": mem_info,
        "gpu": gpus,
        "disk": disks,
        "disk_total": round(total_disk, 1),
        "disk_free": round(total_free, 1),
        "os": os_info,
        "monitors": monitors(),
        "ts": int(time.time()),
    }
    return _CACHE


def monitors() -> List[dict]:
    """显示器：型号 + 当前分辨率 + 原生刷新率 + 连接方式。"""
    out = []
    try:
        from core import display as _d

        for m in _d.list_displays():
            w, h, hz = 0, 0, 0
            try:
                w, h, hz = _d.get_native(m.get("device"))
            except Exception:  # noqa: BLE001
                w, h = m.get("w", 0), m.get("h", 0)
            model = (m.get("model") or "").strip()
            if any(k in model for k in ("NVIDIA", "GeForce", "Radeon", "Intel(R)", "Microsoft Basic")):
                model = ""  # 内置屏读不到 EDID 型号，别拿显卡名冒充
            out.append({
                "model": model,
                "w": w or m.get("w", 0),
                "h": h or m.get("h", 0),
                "hz": hz,
                "primary": bool(m.get("primary")),
            })
    except Exception:  # noqa: BLE001
        pass
    return out


def _gpu_from_registry() -> List[dict]:
    out = []
    try:
        import winreg
        root = (r"SYSTEM\CurrentControlSet\Control\Class"
                r"\{4d36e968-e325-11ce-bfc1-08002be10318}")
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, root) as key:
            for i in range(0, 12):
                try:
                    sub = winreg.OpenKey(key, f"{i:04d}")
                except OSError:
                    continue
                desc = drv = ""
                vram = 0.0
                try:
                    desc = _s(winreg.QueryValueEx(sub, "DriverDesc")[0])
                    drv = _s(winreg.QueryValueEx(sub, "DriverVersion")[0])
                    vram = _gb(winreg.QueryValueEx(sub, "HardwareInformation.qwMemorySize")[0])
                except OSError:
                    pass
                finally:
                    sub.Close()
                if desc:
                    out.append({"name": desc, "vram": vram, "driver": drv})
    except Exception:  # noqa: BLE001
        pass
    return out


# ---------- 报告 ----------

def report_text(d: Optional[dict] = None) -> str:
    d = d or read()
    line = "-" * 46
    rows: List[str] = []
    rows.append(f"燧镜 · 硬件报告　{time.strftime('%Y-%m-%d %H:%M')}")
    rows.append(line)

    osi = d.get("os") or {}
    sysm = d.get("system") or {}
    board = d.get("board") or {}
    bios = d.get("bios") or {}

    rows.append("【系统】")
    rows.append(f"  系统：{osi.get('name','')}　{osi.get('build','')}　{osi.get('arch','')}")
    rows.append(f"  启动：{osi.get('mode','') or '—'}　电源计划：{osi.get('power','') or '—'}")
    if sysm.get("model"):
        rows.append(f"  整机：{sysm.get('mfr','')} {sysm.get('model','')}".rstrip())
    if board.get("product"):
        rows.append(f"  主板：{board.get('mfr','')} {board.get('product','')}".rstrip())
    if bios.get("version"):
        rows.append(f"  BIOS：{bios.get('version','')}　{bios.get('date','')}".rstrip())

    cpu = d.get("cpu") or {}
    rows.append("")
    rows.append("【CPU】")
    rows.append(f"  {cpu.get('name','—')}")
    bits = []
    if cpu.get("cores"):
        bits.append(f"{cpu['cores']} 核")
    if cpu.get("threads"):
        bits.append(f"{cpu['threads']} 线程")
    if cpu.get("ghz"):
        bits.append(f"最高 {cpu['ghz']} GHz")
    if cpu.get("l3_mb"):
        bits.append(f"L3 {_n(cpu['l3_mb'])} MB")
    rows.append("  " + "　".join(bits) if bits else "  核心信息读不到")

    mem = d.get("mem") or {}
    rows.append("")
    rows.append("【内存】")
    rows.append(f"  共 {_n(mem.get('total',0))} GB　{_n(mem.get('count',0))} 条")
    for s in mem.get("sticks") or []:
        desc = f"{_n(s.get('cap',0))} GB {s.get('type','')}".strip()
        if s.get("speed"):
            desc += f"-{s['speed']}"
        rows.append(f"    · {desc}　{s.get('slot','')}".rstrip())

    rows.append("")
    rows.append("【显卡】")
    for g in d.get("gpu") or []:
        vram = f"{_n(g.get('vram'))} GB" if g.get("vram") else "显存未知"
        rows.append(f"  {g.get('name','—')}　{vram}　驱动 {g.get('driver','') or '—'}")
    if not d.get("gpu"):
        rows.append("  读不到")

    rows.append("")
    rows.append("【硬盘】")
    for x in d.get("disk") or []:
        rows.append(
            f"  {x.get('model','—')}　{_n(x.get('size',0))} GB　"
            f"{x.get('media','')}{(' ' + x['bus']) if x.get('bus') else ''}"
        )
    rows.append(f"  合计 {_n(d.get('disk_total',0))} GB，可用 {_n(d.get('disk_free',0))} GB")

    mons = d.get("monitors") or []
    if mons:
        rows.append("")
        rows.append("【显示器】")
        for m in mons:
            tag = "（主屏）" if m.get("primary") else ""
            hz = f" {m['hz']}Hz" if m.get("hz") else ""
            name = m.get("model") or "显示器"
            rows.append(f"  {name}　{m.get('w',0)}×{m.get('h',0)}{hz}{tag}")

    rows.append(line)
    rows.append("由 燧镜 生成本地报告，不含上传。")
    return "\n".join(rows)
