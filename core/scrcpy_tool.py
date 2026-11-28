# -*- coding: utf-8 -*-
"""手机投屏反控：包内自带 scrcpy + adb，燧镜只做外壳和引导。

不自己写投屏协议（那是无底洞），直接用 scrcpy 官方 release 的整套文件，
放在 bundled/scrcpy 里跟着软件走，别人装上也一样能用。

这一层负责：找工具、查设备、识别"等待授权"、启动、无线连、把报错翻成人话。
窗口本身是 scrcpy 的，关掉它进程就退出，不在这儿留后台。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from PySide6 import QtCore

CREATE_NO_WINDOW = 0x08000000
ADB_PORT = "5039"          # 独立端口，避开 Android Studio / 手机助手占着的 5037
QUALITY = {
    "smooth": ("流畅", ["-m", "1024", "-b", "2M"]),
    "normal": ("标准", ["-m", "1600", "-b", "4M"]),
    "hd": ("高清", ["-m", "1920", "-b", "8M"]),
}
# 虚拟屏默认起这个 App。scrcpy 不指定时起系统桌面，而小米/HyperOS 的桌面在虚拟屏上
# 只有一块纯白（实测），换成「设置」就正常显示，所以兜这个默认。
VIRTUAL_DEFAULT_APP = "com.android.settings"
# 虚拟屏尺寸：留空 = 跟主屏一样大
VIRTUAL_SIZES = [
    ("跟手机屏幕一样", ""),
    ("1280 × 720", "1280x720"),
    ("1600 × 900", "1600x900"),
    ("1920 × 1080", "1920x1080"),
]


def _roots():
    """程序目录（打包后是 exe 所在目录，源码时是项目根）。"""
    bases = []
    if getattr(sys, "frozen", False):
        bases.append(Path(sys.executable).resolve().parent)
    bases.append(Path(__file__).resolve().parent.parent)
    bases.append(Path(os.getcwd()))
    return bases


def tool_dir() -> Path:
    for base in _roots():
        d = base / "bundled" / "scrcpy"
        if (d / "scrcpy.exe").exists():
            return d
    for base in _roots():
        d = base / "bundled" / "scrcpy"
        if d.exists():
            return d
    return _roots()[0] / "bundled" / "scrcpy"


def exe_path() -> Path:
    return tool_dir() / "scrcpy.exe"


def adb_path() -> Path:
    return tool_dir() / "adb.exe"


def available() -> bool:
    return exe_path().exists() and adb_path().exists()


def _env() -> dict:
    env = dict(os.environ)
    td = str(tool_dir())
    env["PATH"] = td + os.pathsep + env.get("PATH", "")
    # 独立的 adb server 端口：本机要是还装着 Android Studio / 手机助手，
    # 它们的 adb 占着 5037，撞上了会报 "server version doesn't match"。
    # 注意别用 ADB_SERVER_SOCKET —— 那是"去连别人的 server"，会让 adb 不肯自己起。
    env["ANDROID_ADB_SERVER_PORT"] = ADB_PORT
    return env


def run_adb(*args: str, timeout: float = 8.0) -> tuple[int, str]:
    """跑一条 adb 命令，永远不抛异常（UI 那边只关心文字和成功与否）。"""
    if not adb_path().exists():
        return -1, "包里的 adb 不见了"
    args = tuple(a for a in args if a)
    try:
        p = subprocess.run(
            [str(adb_path()), *args],
            capture_output=True,
            timeout=timeout,
            startupinfo=_hidden(),
            creationflags=CREATE_NO_WINDOW,
            env=_env(),
            cwd=str(tool_dir()),
        )
    except subprocess.TimeoutExpired:
        return -2, "adb 没响应（可能被杀毒软件卡住了）"
    except OSError as exc:
        return -3, str(exc)
    out = (p.stdout or b"") + (p.stderr or b"")
    for enc in ("utf-8", "gbk"):
        try:
            return p.returncode, out.decode(enc, "replace")
        except Exception:  # noqa: BLE001
            continue
    return p.returncode, out.decode("utf-8", "replace")


def _hidden():
    if os.name != "nt":
        return None
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    return si


def devices() -> list[tuple[str, str]]:
    """[(序列号, 状态)]，状态是 device / unauthorized / offline / no permissions。"""
    rc, text = run_adb("devices")
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.lower().startswith("list of devices"):
            continue
        # adb 自己会刷 "* daemon started successfully"、"error: ..." 这类废话
        if line.startswith("*") or line.lower().startswith(("error", "adb:", "cannot", "failed")):
            continue
        if "\t" in line:
            serial, state = line.split("\t", 1)
        else:
            bits = line.split()
            if len(bits) < 2:
                continue
            serial, state = bits[0], bits[1]
        out.append((serial.strip(), state.strip()))
    return out


def serials() -> list[str]:
    return [s for s, st in devices() if st == "device"]


def snapshot() -> dict:
    """面板上要的那点状态：有没有工具、几台手机、要不要去点授权。"""
    if not available():
        return {
            "state": "no-tool",
            "title": "包里的投屏组件不见了",
            "detail": f"应该在这儿：{tool_dir()}",
            "ok": False,
            "serials": [],
        }
    devs = devices()
    ok_ones = [s for s, st in devs if st == "device"]
    if ok_ones:
        name = _model(ok_ones[0])
        return {
            "state": "ready",
            "title": f"已连上 {name}" if name else "已连上一台手机",
            "detail": f"序列号 {ok_ones[0]}" + (f"，另有 {len(ok_ones) - 1} 台" if len(ok_ones) > 1 else ""),
            "ok": True,
            "serials": ok_ones,
        }
    unauthed = [s for s, st in devs if "unauthorized" in st]
    if unauthed:
        return {
            "state": "unauthorized",
            "title": "等待你在手机上点「允许」",
            "detail": "手机屏幕上应该弹了「是否允许 USB 调试」，勾上「一直允许」再点确定",
            "ok": False,
            "serials": [],
        }
    if any("offline" in st for s, st in devs):
        return {
            "state": "offline",
            "title": "手机在，但没连稳",
            "detail": "拔一下数据线重插，或者手机上关掉再打开 USB 调试",
            "ok": False,
            "serials": [],
        }
    return {
        "state": "no-device",
        "title": "没检测到手机",
        "detail": "插上数据线（要能传文件的那种），手机上打开「开发者选项 → USB 调试」",
        "ok": False,
        "serials": [],
    }


_MODEL_CACHE: dict[str, str] = {}


def _model(serial: str) -> str:
    if serial in _MODEL_CACHE:
        return _MODEL_CACHE[serial]
    rc, text = run_adb("-s", serial, "shell", "getprop", "ro.product.model", timeout=6)
    name = (text or "").strip().splitlines()[0].strip() if text else ""
    if rc != 0 or not name:
        name = ""
    _MODEL_CACHE[serial] = name
    return name


def connect_wifi(ip: str) -> tuple[bool, str]:
    """无线：先让手机在 5555 上听（要插着线），再连过去。已经连过就直接连。"""
    ip = (ip or "").strip()
    if not ip:
        return False, "先填手机的 IP（在手机 WiFi 详情里能看到）"
    target = ip if ":" in ip else ip + ":5555"

    rc, text = run_adb("connect", target, timeout=12)
    low = (text or "").lower()
    if "connected to" in low and "failed" not in low:
        return True, f"无线连上了：{target}"
    if "cannot connect" in low or "failed to connect" in low or "refused" in low:
        # 手机还没开 tcpip 模式，插上 USB 线再试一次
        rc2, t2 = run_adb("tcpip", "5555", timeout=10)
        if "restarting in tcp mode" in (t2 or "").lower():
            import time as _t

            _t.sleep(1.6)
            rc, text = run_adb("connect", target, timeout=12)
            low = (text or "").lower()
            if "connected to" in low and "failed" not in low:
                return True, f"无线连上了：{target}（下次插线前就不用再开）"
        return False, "连不上。先插着 USB 线点一次「无线连上」，让手机切到无线模式，再拔线"
    if "unauthorized" in low:
        return False, "手机还没允许这台电脑的调试，先在手机上点「允许」"
    return False, (text or "").strip()[:80] or "无线连接失败"


def mdns_services() -> list[tuple[str, str, str]]:
    """扫局域网里的 adb 服务：[(名字, 类型, 地址)]。

    安卓 11 之后的「无线调试」会广播两种服务：
      _adb-tls-pairing._tcp   —— 只在你打开「使用配对码配对设备」那个弹窗时才有
      _adb-tls-connect._tcp   —— 配对成功后用来连的地址
    """
    rc, text = run_adb("mdns", "services", timeout=12)
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.lower().startswith("list of"):
            continue
        bits = line.split()
        if len(bits) >= 3 and "_adb" in bits[1]:
            out.append((bits[0], bits[1], bits[2]))
    return out


def wifi_pair_found() -> tuple[str, str]:
    """(配对地址, 连接地址)；没开配对弹窗时配对地址是空的。"""
    pair = conn = ""
    for _name, typ, addr in mdns_services():
        if "_adb-tls-pairing._tcp" in typ and not pair:
            pair = addr
        elif "_adb-tls-connect._tcp" in typ and not conn:
            conn = addr
    return pair, conn


def wifi_tags() -> list[tuple[str, str]]:
    """当前广播出来的无线设备：[(mDNS 名字, IP:端口)]。

    名字形如 `adb-4a08dccd-dTD7jM`，里面带着设备序列号；无线调试的端口
    每次关开都会变，只有这个名字是稳定的，所以拿它当"这台手机"的标识。
    """
    out = []
    for name, typ, addr in mdns_services():
        if "_adb-tls-connect._tcp" in typ:
            out.append((name, addr))
    return out


def tag_for_addr(addr: str) -> str:
    """IP:端口 → mDNS 名字（按同一 IP 认，一台机器上不会有两台手机同 IP）。"""
    ip = (addr or "").split(":")[0]
    if not ip:
        return ""
    for name, a in wifi_tags():
        if a.split(":")[0] == ip:
            return name
    return ""


def reconnect_wifi(tag: str) -> tuple[bool, str]:
    """按 mDNS 名字把上次那台无线手机接回来。

    先看是不是已经在线；不在就扫一遍局域网，找名字对得上的当前端口再连。
    手机把「无线调试」关掉之后就不再广播，这种情况只能让用户去打开一下——
    配对信息在手机端存着，重新打开后不用再配一次。
    """
    tag = (tag or "").strip()
    if not tag:
        return False, ""
    for s, st in devices():
        if st == "device" and (s == tag or s.startswith(tag) or tag.startswith(s)):
            return True, ""
    found = wifi_tags()
    cur = ""
    for name, addr in found:
        if name == tag or name.startswith(tag) or tag.startswith(name):
            cur = addr
            break
    if not cur and len(found) == 1:
        cur = found[0][1]
    if not cur:
        return False, ("手机上的「无线调试」好像被关掉了（关掉后它就不广播了）——"
                       "去开发者选项重新打开，回来点「刷新」，不用再配对一次")
    rc, text = run_adb("connect", cur, timeout=12)
    if "connected to" in (text or "").lower():
        return True, ""
    return False, "无线地址找到了但连不上，点「刷新」再试一次"


def model_name(serial: str) -> str:
    """给下拉框用的型号名（带缓存，重复调不会一直跑 adb）。"""
    return _model(serial)


def pair_wifi(code: str) -> tuple[bool, str, str]:
    """用手机上那 6 位配对码连无线，返回 (成功, 提示, mDNS 名字)。

    手机上必须先把「开发者选项 → 无线调试 → 使用配对码配对设备」点开，
    那个弹窗开着的时候配对服务才会广播出来；关掉就找不到。
    """
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False, "配对码是手机上显示的那 6 位数字", ""
    pair_addr, conn_addr = wifi_pair_found()
    if not pair_addr:
        return False, ("没发现配对服务 —— 先在手机上「开发者选项 → 无线调试 → 使用配对码配对设备」，"
                       "把那个弹窗开着别关，再点一次"), ""
    rc, text = run_adb("pair", pair_addr, code, timeout=30)
    low = (text or "").lower()
    if "successfully paired" not in low:
        if "wrong" in low or "failed" in low or "para" in low:
            return False, "配对码不对或者已经过期 —— 手机上那个弹窗重开一个，用新码", ""
        return False, "配对没成：" + (" ".join((text or "").split())[:90] or "手机没响应"), ""
    if not conn_addr:
        for _n, typ, addr in mdns_services():
            if "_adb-tls-connect._tcp" in typ:
                conn_addr = addr
                break
    if not conn_addr:
        return False, "配上了，但没找到连接端口 —— 把手机「无线调试」关一下再打开，重试", ""
    rc, text = run_adb("connect", conn_addr, timeout=15)
    if "connected to" in (text or "").lower():
        return True, "无线连上了：" + conn_addr + "（之后直接选它投屏，不用再接线）", tag_for_addr(conn_addr)
    return False, "配上了但连不上 —— 手机「无线调试」关一下再开，重试一次", ""


def build_args(serial: str = "", quality: str = "normal", fps: int = 0, record: str = "",
               virtual: bool = False, no_audio: bool = False,
               virtual_app: "str | None" = None, virtual_size: str = "",
               camera: bool = False, camera_facing: str = "", camera_id: str = "",
               camera_torch: bool = False) -> list:
    """把参数拼成列表（纯函数，方便自检；start() 只负责拉起进程）。"""
    args = ["--window-title=燧镜投屏", "--keyboard=uhid", "--mouse=sdk"]

    if camera:
        # 摄像头模式：不碰手机屏幕，也不要手机的声音（那边根本没有音频流）
        args.append("--video-source=camera")
        if camera_id:
            args.append("--camera-id=" + str(camera_id))
        elif camera_facing:
            args.append("--camera-facing=" + str(camera_facing))
        if camera_torch:
            args.append("--camera-torch")
        args.append("--no-audio")
    else:
        args += ["--turn-screen-off", "--stay-awake"]
        if virtual:
            nd = "--new-display"
            if virtual_size:
                nd += "=" + str(virtual_size)
            args.append(nd)
            # 不指定 App 时 scrcpy 会起系统桌面；HyperOS / MIUI 的桌面在虚拟屏上渲染成纯白，
            # 实测换成「设置」就正常，所以默认兜「设置」；显式给空串表示就要桌面
            app = VIRTUAL_DEFAULT_APP if virtual_app is None else virtual_app
            if app:
                args.append("--start-app=" + str(app))
        if no_audio:
            args.append("--no-audio")

    if fps:
        args.append("--max-fps=%d" % int(fps))
    if record:
        args.append("--record=" + str(record))
    q = QUALITY.get(quality)
    if q:
        args += q[1]
    if serial:
        args += ["-s", serial]
    return [a for a in args if a]


def wake_screen(serial: str = "") -> bool:
    """点亮手机屏幕（KEYCODE_WAKEUP）。

    实测坑：手机息屏时 scrcpy 的摄像头流会一直是黑帧（小米/Camera2 的省电策略），
    屏幕一亮画面立刻出来。所以投摄像头之前先唤醒一下；失败就算了，不挡主流程。
    """
    rc = -1
    try:
        if serial:
            rc, _ = run_adb("-s", serial, "shell", "input keyevent 224", timeout=4.0)
        else:
            rc, _ = run_adb("shell", "input keyevent 224", timeout=4.0)
    except Exception:
        rc = -1
    return rc == 0


def start(serial: str = "", quality: str = "normal", fps: int = 0, record: str = "",
          virtual: bool = False, no_audio: bool = False,
          virtual_app: "str | None" = None, virtual_size: str = "",
          camera: bool = False, camera_facing: str = "", camera_id: str = "",
          camera_torch: bool = False) -> QtCore.QProcess:
    """拉起 scrcpy 窗口。返回 QProcess，调用方自己接 finished 信号。

    可选的高级档（scrcpy 5.x 原生支持，不是我们造的功能）：
      fps       —— 帧率上限，0 = 不限制
      record    —— 录屏到 mp4（scrcpy 边投边录，关窗口就收尾成文件）
      virtual   —— 开一块"虚拟屏"，应用跑在里面，不动手机前台
      virtual_app / virtual_size —— 虚拟屏里起哪个 App、分辨率多大
      no_audio  —— 不把手机声音转到电脑（用手机音频接收那套时勾它，免得两边抢）
      camera    —— 走手机摄像头（Camera2 原始流，没有厂商美颜/HDR 那些算法）
      camera_facing / camera_id —— 用哪颗镜头（前置/后置，或直接给 camera id）
    拖拽互传是 scrcpy 自带的：把文件拖进投屏窗口，它就推到手机 Download 里。
    """
    args = build_args(serial, quality, fps=fps, record=record, virtual=virtual, no_audio=no_audio,
                      virtual_app=virtual_app, virtual_size=virtual_size, camera=camera,
                      camera_facing=camera_facing, camera_id=camera_id, camera_torch=camera_torch)

    if camera:
        # 息屏状态下摄像头流是黑的（见 wake_screen 注释），先亮屏
        wake_screen(serial)

    proc = QtCore.QProcess()
    env = QtCore.QProcessEnvironment()
    for k, v in _env().items():
        env.insert(k, v)
    proc.setProcessEnvironment(env)
    proc.setWorkingDirectory(str(tool_dir()))
    proc.start(str(exe_path()), args)
    return proc


def graceful_close(pid: int) -> bool:
    """发「关窗口」而不是强杀。

    Windows 上 QProcess.terminate() 是 TerminateProcess，等于直接砍掉进程；
    scrcpy 正在录 mp4 时，砍掉就没人写文件尾，录下来的是个打不开的坏文件。
    taskkill 不带 /F 会先投一个 WM_CLOSE，scrcpy 收到后正常退出并收尾。
    """
    if not pid:
        return False
    try:
        if os.name == "nt":
            p = subprocess.run(
                ["taskkill", "/PID", str(int(pid))],
                capture_output=True, timeout=8,
                startupinfo=_hidden(), creationflags=CREATE_NO_WINDOW,
            )
            return p.returncode == 0
        p = subprocess.run(["kill", "-TERM", str(int(pid))], capture_output=True, timeout=8)
        return p.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def explain(text: str) -> str:
    """把 adb / scrcpy 的报错翻成能照着做的话。"""
    low = (text or "").lower()
    if not low.strip():
        return "窗口关掉了"
    if "unauthorized" in low:
        return "手机没允许调试 —— 在手机屏幕上点「允许」"
    if "disconnected" in low or "stream disabled" in low or "connection error" in low:
        return ("手机中途掉线了 —— 这是数据线 / USB 口接触的问题，不是软件：换一根能传文件的线、"
                "插机箱后面板的口；要是线一直不稳，就用「无线连接」那条")
    if ("could not find any adb device" in low or "no devices" in low
            or "not found" in low):
        return ("没找到手机 —— 检查线是不是只能充电的那种；如果刚刚还在投屏，那就是线掉了，"
                "换线或者改用无线连接")
    if "access denied" in low or "permission" in low:
        return "系统拦了 adb 的 USB 访问 —— 换一个 USB 口，别用前置面板的那些"
    if "server version" in low or "5037" in low:
        return "本机别的软件（Android Studio / 手机助手）占着 adb 端口，已经绕开，若还报这个就关掉它们"
    if "antivirus" in low or "被杀" in low:
        return "adb 可能被杀毒软件拦了 —— 在杀软里信任 bundled\\scrcpy\\adb.exe"
    if "scrcpy-server" in low or "server" in low:
        return "手机上没有投屏服务文件 —— 换成数据线直连再试一次"
    return "scrcpy 报了这个：" + (text or "").strip().splitlines()[0][:80]
