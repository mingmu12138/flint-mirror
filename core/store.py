"""配置与模组数据层。

- config.json 保存原生分辨率、4:3 目标、热键开关和全部模组
- 模组类型支持：exe 程序 / 本地 html / 网址
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import psutil


# 随软件一起打包的内置模组：路径相对程序目录，换电脑也不用改
BUNDLED_DIR = "bundled"
# (显示名, 相对路径, 启动参数)
BUNDLED_MODS = [
    # 口琴已经搬成 .sjmod 模组（mods/_builtin/com.flint.harmonica），
    # 工具页不再放第二份，免得两个入口抢同一个进程
    # 手机音频接收：手机蓝牙连电脑，把手机的声当电脑输出（A2DP Sink）
    ("手机音频接收", f"{BUNDLED_DIR}/apc/AudioPlaybackConnector64.exe", []),
    # qBittorrent：BT 下载。--profile 让配置和缓存留在包内，不碰系统 %APPDATA%
    ("qBittorrent", f"{BUNDLED_DIR}/qbittorrent/qbittorrent.exe", ["--profile=profile"]),
    # 手机投屏（scrcpy）不走模组：主页右上角有专门的「手机投屏」方块，
    # 在模组页再放一张同样的卡就是重复入口，老版本生成的卡下面会自动清掉
]

# 内置页面模组：key 是软件内部的页面标识，不指向任何外部文件
# (显示名, 页面 key, 说明)
BUILTIN_PAGES = [
    ("三角洲情报", "delta", "密码门 · 子弹 · 假账榜 · 制造利润"),
    # 显示器滤镜：直接调显示器 Gamma 曲线，预设 + 对比预览，关窗自动还原
    ("显示器滤镜", "filter", "预设 + 对比预览 · 关窗自动还原"),
]

CONFIG_NAME = "config.json"

KIND_EXE = "exe"
KIND_HTML = "html"
KIND_URL = "url"
# 三方工具：path 存官网地址，dl 存直链（可空）；没直链就开浏览器，有直链就软件内下载
KIND_REMOTE = "remote"
# 内置页面：不是外部程序，点一下切到软件自己的某个页面
KIND_PAGE = "page"

KIND_LABEL = {
    KIND_EXE: "程序",
    KIND_HTML: "网页",
    KIND_URL: "网址",
    KIND_REMOTE: "三方工具",
    KIND_PAGE: "内置",
}


def app_dir() -> Path:
    """程序所在目录（打包后是 exe 所在目录，源码运行时是项目根目录）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def config_path() -> Path:
    return app_dir() / CONFIG_NAME


def guess_kind(path: str) -> str:
    lower = (path or "").lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        return KIND_URL
    suffix = Path(lower).suffix
    if suffix in (".exe", ".bat", ".cmd"):
        return KIND_EXE
    if suffix in (".html", ".htm"):
        return KIND_HTML
    return KIND_EXE


# ---------------------------------------------------------------------------
# 模组
# ---------------------------------------------------------------------------
@dataclass
class Mod:
    id: str
    name: str
    path: str
    kind: str = KIND_EXE
    # 三方工具的直链下载地址（只有 kind == remote 用得上；空 = 只挂官网）
    dl: str = ""
    args: List[str] = field(default_factory=list)
    enabled: bool = True
    autostart: bool = False
    note: str = ""
    # 启动前延迟多少秒（有些工具需要等游戏先起来）
    delay: int = 0

    # ---------- 运行时 ----------
    pid: Optional[int] = None
    _last_launch: float = 0.0
    # 最近一次启动失败的原因（空 = 没出过错）；只放内存，不写进配置
    last_error: str = ""
    # 这一轮是否已经自动重试过；只放内存，手工再点一次启动会复位
    _retried: bool = False
    # 进程退出后留下的退出码：is_running 清理记录前先存下来，健康检查要用
    _exit_code: Optional[int] = None

    @property
    def resolved(self) -> str:
        """真实路径：相对路径按程序目录展开（内置模组就是打包进来的那一份）。"""
        if self.kind in (KIND_URL, KIND_PAGE, KIND_REMOTE):
            return self.path
        try:
            path = Path(self.path)
        except (OSError, TypeError):
            return self.path
        if path.is_absolute():
            return str(path)
        return str(app_dir() / path)

    @property
    def exists(self) -> bool:
        if self.kind in (KIND_URL, KIND_PAGE, KIND_REMOTE):
            return True
        try:
            return Path(self.resolved).exists()
        except OSError:
            return False

    @property
    def kind_label(self) -> str:
        return KIND_LABEL.get(self.kind, "程序")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "kind": self.kind,
            "dl": self.dl,
            "args": list(self.args),
            "enabled": bool(self.enabled),
            "autostart": bool(self.autostart),
            "note": self.note,
            "delay": int(self.delay),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Mod":
        path = str(d.get("path", ""))
        return cls(
            id=str(d.get("id") or uuid.uuid4().hex[:8]),
            name=str(d.get("name") or Path(path).stem or "未命名模组"),
            path=path,
            kind=str(d.get("kind") or guess_kind(path)),
            dl=str(d.get("dl") or ""),
            args=list(d.get("args") or []),
            enabled=bool(d.get("enabled", True)),
            autostart=bool(d.get("autostart", False)),
            note=str(d.get("note") or ""),
            delay=int(d.get("delay") or 0),
        )


# ---------------------------------------------------------------------------
# 进程托管
# ---------------------------------------------------------------------------
class ProcessGuard:
    """负责启动 / 停止模组进程，并检测它们是否还活着。"""

    def __init__(self) -> None:
        self._procs: Dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    # ---- 查询 ----
    def is_running(self, mod: Mod) -> bool:
        if mod.kind != KIND_EXE:
            return False
        with self._lock:
            proc = self._procs.get(mod.id)
        if proc is not None:
            if proc.poll() is None:
                return True
            # 清理之前把退出码存进模组，否则健康检查就没依据了
            mod._exit_code = proc.returncode
            with self._lock:
                self._procs.pop(mod.id, None)
        # 兜底：按记录的 pid 判断
        if mod.pid:
            try:
                p = psutil.Process(mod.pid)
                if p.is_running() and p.status() != psutil.STATUS_ZOMBIE:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                mod.pid = None
        return False

    def pid_of(self, mod: Mod) -> Optional[int]:
        with self._lock:
            proc = self._procs.get(mod.id)
        if proc is not None and proc.poll() is None:
            return proc.pid
        return mod.pid

    # ---- 启动 ----
    def launch(self, mod: Mod) -> Tuple[bool, str]:
        target = mod.resolved
        if not mod.kind == KIND_URL and not Path(target).exists():
            mod.last_error = f"文件不在了：{target}"
            return (False, mod.last_error)

        if mod.kind in (KIND_HTML, KIND_URL):
            try:
                if mod.kind == KIND_URL:
                    os.startfile(target)
                else:
                    # 直接打开原始文件，不做任何拷贝：文件自己更新后打开即最新
                    os.startfile(target)
            except OSError as exc:
                return (False, f"打开失败：{exc}")
            mod._last_launch = time.time()
            return (True, "已在浏览器中打开")

        if self.is_running(mod):
            return (True, "已经在运行了")

        try:
            exe = str(Path(target))
            cwd = str(Path(target).parent)
            creationflags = 0
            if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
            proc = subprocess.Popen(
                [exe] + list(mod.args),
                cwd=cwd,
                close_fds=True,
                creationflags=creationflags,
            )
        except OSError as exc:
            msg = self._explain_oserror(exc, target)
            mod.last_error = msg
            return (False, msg)
        except ValueError as exc:
            msg = f"启动失败：{exc}"
            mod.last_error = msg
            return (False, msg)

        with self._lock:
            self._procs[mod.id] = proc
        mod.pid = proc.pid
        mod._last_launch = time.time()
        mod.last_error = ""
        mod._exit_code = None  # 新一轮，旧退出码作废
        return (True, f"已启动（PID {proc.pid}）")

    def health(self, mod: Mod) -> Tuple[bool, str]:
        """启动后过一两秒回头看一眼：还活着 = 正常，已经退出 = 给原因。

        单独拿出来，是为了不在启动那一刻阻塞界面。
        注意：进程可能在启动后不到 1 秒就退了，界面刷新时 is_running 已经
        把记录清掉——所以这里还要认模组自己记下的退出码。
        """
        with self._lock:
            proc = self._procs.get(mod.id)
        if proc is None:
            if mod._exit_code is None:
                return (True, "")
            rc = mod._exit_code
        else:
            rc = proc.poll()
            if rc is None:
                mod.last_error = ""
                return (True, "")
            with self._lock:
                self._procs.pop(mod.id, None)
        if rc == 0:
            mod.last_error = ""
            return (True, f"{mod.name} 启动后自己退出了（可能它拉了别的进程）")
        msg = self._explain_exit(rc, mod.name)
        mod.last_error = msg
        return (False, msg)

    # ---- 健康检查：把系统错误翻译成人话 ----
    @staticmethod
    def _explain_oserror(exc: OSError, target: str) -> str:
        code = getattr(exc, "winerror", None)
        name = Path(target).name
        if code == 2:
            return f"找不到文件：{name}"
        if code in (5, 740):
            return f"权限不足：{name} 需要管理员身份（右键 → 以管理员身份运行燧镜）"
        if code in (32, 33):
            return f"{name} 正被别的程序占用，先关掉它再启动"
        if code in (193, 216):
            return (
                f"{name} 不是能在本机跑的程序（下错版本 / 架构不符 / 文件损坏），"
                "换对应系统的那份再试"
            )
        if code == 225:
            return f"{name} 被杀毒软件拦了，先加信任区"
        return f"启动失败：{exc}"

    @staticmethod
    def _explain_exit(code, name: str) -> str:
        code = int(code or 0) & 0xFFFFFFFF
        hints = {
            0xC0000135: "缺运行库（.NET Framework 或 VC++ 运行库没装）",
            0xC000007B: "运行库位数不对（32 位程序缺 32 位运行库）",
            0xC0000005: "一启动就崩了（多半是显卡驱动或兼容问题）",
            0xC0000142: "加载 DLL 失败（重装运行库或换安装目录）",
            3221225781: "缺运行库（.NET Framework 或 VC++ 运行库没装）",
            3221225592: "加载 DLL 失败（重装运行库或换安装目录）",
            1: "程序自己报错退出，可能缺配置文件或需要管理员",
            2: "找不到它依赖的文件（别把它从原目录挪走）",
            5: "权限不足，用管理员身份启动燧镜再试",
        }
        hint = hints.get(code, "程序刚启动就退出了")
        return f"{name} 启动即退出（退出码 {code}）：{hint}"

    # ---- 停止 ----
    def stop(self, mod: Mod) -> Tuple[bool, str]:
        if mod.kind != KIND_EXE:
            return (False, "网页类模组不接管浏览器进程，无法停止")

        targets: List[psutil.Process] = []
        with self._lock:
            proc = self._procs.pop(mod.id, None)
        if proc is not None and proc.poll() is None:
            try:
                targets.append(psutil.Process(proc.pid))
            except psutil.NoSuchProcess:
                pass
        if not targets and mod.pid:
            try:
                targets.append(psutil.Process(mod.pid))
            except psutil.NoSuchProcess:
                pass

        if not targets:
            mod.pid = None
            return (True, "进程已经结束")

        killed = 0
        for p in targets:
            try:
                for child in p.children(recursive=True):
                    try:
                        child.terminate()
                    except psutil.Error:
                        pass
                p.terminate()
                killed += 1
            except psutil.Error:
                pass

        # 给 2 秒优雅退出，不退就强杀
        deadline = time.time() + 2.0
        while time.time() < deadline:
            still = [p for p in targets if _alive(p)]
            if not still:
                break
            time.sleep(0.1)
        for p in targets:
            if _alive(p):
                try:
                    p.kill()
                except psutil.Error:
                    pass

        mod.pid = None
        return (True, "已停止" if killed else "已停止")


def _alive(p: psutil.Process) -> bool:
    try:
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


# ---------------------------------------------------------------------------
# 默认预置模组（路径不存在也不影响；界面上会标红，可删除或重新添加）
# ---------------------------------------------------------------------------
def default_mods() -> List[Mod]:
    desktop = Path(os.path.expanduser("~")) / "Desktop"
    items = [
        ("灵引系统", desktop / "灵引系统历史版本" / "灵引系统v2.0" / "LingYin.exe"),
        ("聆域系统", desktop / "聆域系统历史版本" / "聆域V4.0" / "LingyuSystem.exe"),
        ("三角洲改枪码仓库", desktop / "三角洲改枪码仓库.html"),
    ]
    mods: List[Mod] = []
    for name, path in items:
        p = str(path)
        mods.append(
            Mod(
                id=uuid.uuid4().hex[:8],
                name=name,
                path=p,
                kind=guess_kind(p),
                enabled=True,
            )
        )
    return mods


# ---------------------------------------------------------------------------
# 全局热键：动作 id / 中文名 / 默认组合
# ---------------------------------------------------------------------------
HOTKEY_ACTIONS = [
    ("toggle_resolution", "切换分辨率 / 回原生", "Ctrl+Alt+R"),
    ("show_panel", "打开控制面板", "Ctrl+Alt+M"),
    ("shot_full", "全屏截图", "Ctrl+Alt+S"),
    ("shot_region", "框选截图", "Ctrl+Alt+Shift+S"),
    ("record", "开始 / 停止录屏", "Ctrl+Alt+V"),
    ("replay_save", "保存最近回放", "Ctrl+Alt+B"),
    ("audio_toggle", "耳机 / 音箱 一键切换", "Alt+Z"),
    ("music_toggle", "音乐 播放 / 暂停", "Ctrl+Alt+P"),
    ("music_next", "音乐 下一首", "Ctrl+Alt+N"),
    ("music_prev", "音乐 上一首", "Ctrl+Alt+J"),
]
DEFAULT_HOTKEYS = {key: default for key, _label, default in HOTKEY_ACTIONS}
HOTKEY_LABEL = {key: label for key, label, _default in HOTKEY_ACTIONS}


# ---------------------------------------------------------------------------
# 自动化：动作 + 规则
# ---------------------------------------------------------------------------
ACTION_RESOLUTION = "resolution"   # 切到指定分辨率（value = "1280x960"）
ACTION_RESTORE = "restore"         # 恢复原生
ACTION_MOD_START = "mod_start"     # 启动模组（value = 模组 id）
ACTION_MOD_STOP = "mod_stop"       # 停止模组
ACTION_WAIT = "wait"               # 等待（value = 秒）
# 下面这些是"把面板上的开关也交给自动化"：
ACTION_ACE_LIMIT = "ace_limit"         # 限制 ACE 扫盘（压低优先级）
ACTION_ACE_RESTORE = "ace_restore"     # 解除 ACE 限制
ACTION_FPS_SHOW = "fps_show"           # 开帧率悬浮窗
ACTION_FPS_HIDE = "fps_hide"           # 关帧率悬浮窗
ACTION_HUD_SHOW = "hud_show"           # 显示每日密码悬浮窗
ACTION_HUD_HIDE = "hud_hide"           # 隐藏每日密码悬浮窗
ACTION_REPLAY_START = "replay_start"   # 开启回放缓冲
ACTION_REPLAY_STOP = "replay_stop"     # 关闭回放缓冲
ACTION_REPLAY_SAVE = "replay_save"     # 保存最近一段回放
ACTION_RECORD_START = "record_start"   # 开始录屏
ACTION_RECORD_STOP = "record_stop"     # 停止并保存录屏
ACTION_SHOT = "shot"                   # 截一张图（value = full / region）
ACTION_CACHE_CLEAN = "cache_clean"     # 清理着色器缓存

ACTION_LABEL = {
    ACTION_RESOLUTION: "切换分辨率",
    ACTION_RESTORE: "恢复原生分辨率",
    ACTION_MOD_START: "启动模组",
    ACTION_MOD_STOP: "停止模组",
    ACTION_WAIT: "等待",
    ACTION_ACE_LIMIT: "反作弊优化",
    ACTION_ACE_RESTORE: "还原反作弊优化",
    ACTION_FPS_SHOW: "开帧率悬浮窗",
    ACTION_FPS_HIDE: "关帧率悬浮窗",
    ACTION_HUD_SHOW: "显示密码悬浮窗",
    ACTION_HUD_HIDE: "隐藏密码悬浮窗",
    ACTION_REPLAY_START: "开启回放缓冲",
    ACTION_REPLAY_STOP: "关闭回放缓冲",
    ACTION_REPLAY_SAVE: "保存最近回放",
    ACTION_RECORD_START: "开始录屏",
    ACTION_RECORD_STOP: "停止录屏并保存",
    ACTION_SHOT: "截一张图",
    ACTION_CACHE_CLEAN: "清理着色器缓存",
}

TRIGGER_START = "process_start"    # 进程出现
TRIGGER_STOP = "process_stop"      # 进程消失
TRIGGER_MANUAL = "manual"          # 只能手动跑

TRIGGER_LABEL = {
    TRIGGER_START: "当进程启动",
    TRIGGER_STOP: "当进程退出",
    TRIGGER_MANUAL: "仅手动执行",
}


@dataclass
class Action:
    type: str = ACTION_RESOLUTION
    value: str = ""

    def to_dict(self) -> dict:
        return {"type": self.type, "value": self.value}

    @classmethod
    def from_dict(cls, d: dict) -> "Action":
        t = str(d.get("type") or ACTION_RESOLUTION)
        if t not in ACTION_LABEL:
            t = ACTION_RESOLUTION
        return cls(type=t, value=str(d.get("value") or ""))


@dataclass
class Rule:
    """一条自动化规则：触发条件 + 一串动作。"""

    id: str
    name: str
    trigger: str = TRIGGER_START
    process: str = ""
    enabled: bool = True
    actions: List[Action] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "trigger": self.trigger,
            "process": self.process,
            "enabled": bool(self.enabled),
            "actions": [a.to_dict() for a in self.actions],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Rule":
        trigger = str(d.get("trigger") or TRIGGER_START)
        if trigger not in TRIGGER_LABEL:
            trigger = TRIGGER_START
        actions_raw = d.get("actions")
        actions = [
            Action.from_dict(x) for x in actions_raw if isinstance(x, dict)
        ] if isinstance(actions_raw, list) else []
        return cls(
            id=str(d.get("id") or uuid.uuid4().hex[:8]),
            name=str(d.get("name") or "未命名规则"),
            trigger=trigger,
            process=str(d.get("process") or ""),
            enabled=bool(d.get("enabled", True)),
            actions=actions,
        )


# ---------------------------------------------------------------------------
# 配置
# ---------------------------------------------------------------------------
class Config:
    def __init__(self) -> None:
        # 原生分辨率（第一次运行时记录）
        self.native: Tuple[int, int, int] = (0, 0, 0)
        # 目标档位：首次按本机原生分辨率自动推荐（同比例、无黑边），用户一改就固定
        self.target: Tuple[int, int] = (1280, 960)
        self.target_auto: bool = True
        self.hotkey_enabled: bool = True
        # 每个热键单独开关：关掉的那一个不注册，别的照常用
        self.hotkey_on: Dict[str, bool] = {k: True for k in DEFAULT_HOTKEYS}
        # 每个动作对应一个组合字符串，用户可在设置里改（"Ctrl+Alt+R" 这种）
        self.hotkeys: Dict[str, str] = dict(DEFAULT_HOTKEYS)
        self.close_to_tray: bool = True
        self.clip_enabled: bool = True
        self.tray_tip_shown: bool = False
        # 模组区的展示方式："list" 列表 / "grid" 图标
        self.view_mode: str = "list"
        # 「模组」页的展示方式（.sjmod 那套）：默认宫格
        self.mod_view_mode: str = "grid"
        self.mods: List[Mod] = []
        # 自定义自动化规则 / 开机自启
        self.rules: List[Rule] = []
        self.autostart: bool = False
        # 嘉豪模式：切到非原生档后要「拉伸铺满」，不要黑边
        self.stretch: bool = False
        # 显卡厂家：auto / nvidia / amd / intel（决定「去显卡设置」打开哪个面板）
        self.gpu_vendor: str = "auto"
        # ACE 扫盘限制：自动守护（游戏重启 ACE 进程后自动再压一次）
        self.ace_guard: bool = False
        # 每日密码自动更新：跨天自动抓当天密码（关掉就只手动刷）
        self.pwd_auto: bool = True
        # 每日密码悬浮窗：只显示当天密码，常驻桌面
        self.hud_show: bool = False
        self.hud_pos: List[int] = []
        self.hud_scale: int = 16
        self.hud_alpha: int = 92
        self.hud_lock: bool = False
        # 回放缓冲：体积上限（GB，5/7/10）与缓存盘（空 = 程序目录里的 回放缓冲）
        self.replay_max_gb: int = 5
        self.replay_dir: str = ""
        # 素材（截图 + 录屏成品）存放根目录；空 = 程序目录下的「素材」
        self.media_dir: str = ""
        # 音频输出切换：两个槽位存设备 id（Distributed: 用户自己选，不写死名字）
        self.audio_a: str = ""
        self.audio_b: str = ""
        # 是否在任务栏单独放一个小喇叭图标（关掉就只从主托盘菜单 / 热键切）
        self.audio_tray_icon: bool = True
        # 游戏服务器地址（可选）：测速时额外打这个，填 "host" 或 "host:端口"
        self.ping_host: str = ""
        # 悬浮窗贴哪一侧：left / right
        self.hud_side: str = "right"
        # 鼠标穿透（默认开，不挡点击）
        self.hud_click_through: bool = True
        # 帧率悬浮窗
        self.fps_show: bool = False
        self.fps_pos: List[int] = []
        self.fps_side: str = "right"
        self.fps_scale: int = 20
        self.fps_alpha: int = 88
        self.fps_click_through: bool = True
        # 准星叠加层
        self.cross_show: bool = False
        self.cross_style: str = "cross"
        self.cross_size: int = 8
        self.cross_thickness: int = 2
        self.cross_gap: int = 4
        self.cross_color: str = "#20ffe0"
        self.cross_alpha: int = 92
        self.cross_dot: bool = True
        self.cross_outline: bool = True
        # 当前皮肤（内置 key 或 themes/*.json 里的 key）
        self.theme: str = "cyber"
        # 窗口外观：classic = 系统标题栏；glass = 无边框毛玻璃（自绘标题栏）
        self.window_mode: str = "classic"
        # 立绘：开关 + 图片文件名（存在程序目录的 art 文件夹里）
        self.art_show: bool = False
        self.art_file: str = ""
        self.art_blur: int = 18
        # 作用显示器：空 = 主屏；填设备名（\\.\DISPLAY2）就只切那一块
        self.screen_device: str = ""
        # 局域网剪贴板的通行口令：存下来，重启程序之后手机扫过的码还能用
        self.clip_token: str = ""
        # 这台机器的局域网身份（随机一段，第一次开就生成）：手机靠它认出
        # 「换了个 IP 的还是原来那台电脑」，不用重新扫码
        self.lan_id: str = ""
        # 上次退出时剪贴板服务是不是开着：开着的话下次启动自动起来
        self.clip_auto: bool = False
        # 手机传来的文件存哪；空着就存程序目录下的「收到」
        self.recv_dir: str = ""
        # 机器指纹（显示器 + 原生分辨率），用来认出换了电脑 / 换了屏
        self.machine_tag: str = ""
        # 桌面音乐悬浮条：开关、上次位置、贴哪边（left / right / 空 = 不贴边）
        self.bar_on: bool = True
        self.bar_pos: List[int] = []
        self.bar_side: str = ""
        # 新手引导是否已经看过（第一次启动自动弹一次）
        self.guide_shown: bool = False
        self.load()

    # ---------- 读写 ----------
    def load(self) -> None:
        path = config_path()
        raw: dict = {}
        if path.exists():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = {}

        native = raw.get("native") or []
        if isinstance(native, (list, tuple)) and len(native) >= 2:
            self.native = (int(native[0]), int(native[1]), int(native[2]) if len(native) > 2 else 0)

        target = raw.get("target") or []
        if isinstance(target, (list, tuple)) and len(target) >= 2:
            self.target = (int(target[0]), int(target[1]))
        self.target_auto = bool(raw.get("target_auto", True))
        self.clip_token = str(raw.get("clip_token") or "")[:32]
        self.lan_id = str(raw.get("lan_id") or "")[:40]
        self.clip_auto = bool(raw.get("clip_auto", False))
        self.recv_dir = str(raw.get("recv_dir") or "")[:400]

        self.hotkey_enabled = bool(raw.get("hotkey_enabled", True))
        raw_on = raw.get("hotkey_on") or {}
        if isinstance(raw_on, dict):
            for key in DEFAULT_HOTKEYS:
                self.hotkey_on[key] = bool(raw_on.get(key, True))
        raw_hk = raw.get("hotkeys") or {}
        if isinstance(raw_hk, dict):
            for key, default in DEFAULT_HOTKEYS.items():
                val = raw_hk.get(key)
                if isinstance(val, str) and val.strip():
                    self.hotkeys[key] = val.strip()
                else:
                    self.hotkeys[key] = default
        try:
            gb = int(raw.get("replay_max_gb", 5))
        except (TypeError, ValueError):
            gb = 5
        self.replay_max_gb = gb if gb in (5, 7, 10) else 5
        self.replay_dir = str(raw.get("replay_dir", "") or "").strip()
        self.media_dir = str(raw.get("media_dir", "") or "").strip()
        self.audio_tray_icon = bool(raw.get("audio_tray_icon", True))
        self.audio_a = str(raw.get("audio_a", "") or "").strip()
        self.audio_b = str(raw.get("audio_b", "") or "").strip()
        self.ping_host = str(raw.get("ping_host", "") or "").strip()
        self.close_to_tray = bool(raw.get("close_to_tray", True))
        self.clip_enabled = bool(raw.get("clip_enabled", True))
        self.tray_tip_shown = bool(raw.get("tray_tip_shown", False))

        mode = str(raw.get("view_mode") or "list").lower()
        self.view_mode = mode if mode in ("list", "grid") else "list"

        mmode = str(raw.get("mod_view_mode") or "grid").lower()
        self.mod_view_mode = mmode if mmode in ("list", "grid") else "grid"

        mods_raw = raw.get("mods")
        if isinstance(mods_raw, list):
            self.mods = [Mod.from_dict(d) for d in mods_raw if isinstance(d, dict)]
        else:
            self.mods = default_mods()

        rules_raw = raw.get("rules")
        if isinstance(rules_raw, list):
            self.rules = [
                Rule.from_dict(d) for d in rules_raw if isinstance(d, dict)
            ]

        self.autostart = bool(raw.get("autostart", False))
        self.stretch = bool(raw.get("stretch", False))
        self.screen_device = str(raw.get("screen_device") or "")
        vendor = str(raw.get("gpu_vendor") or "auto").lower()
        self.gpu_vendor = vendor if vendor in ("auto", "nvidia", "amd", "intel") else "auto"
        self.ace_guard = bool(raw.get("ace_guard", False))
        self.pwd_auto = bool(raw.get("pwd_auto", True))

        self.hud_show = bool(raw.get("hud_show", False))
        self.hud_lock = bool(raw.get("hud_lock", False))
        try:
            self.hud_scale = max(12, min(26, int(raw.get("hud_scale", 16))))
        except (TypeError, ValueError):
            self.hud_scale = 16
        try:
            self.hud_alpha = max(55, min(100, int(raw.get("hud_alpha", 92))))
        except (TypeError, ValueError):
            self.hud_alpha = 92
        side = str(raw.get("hud_side") or "right").lower()
        self.hud_side = side if side in ("left", "right") else "right"
        self.hud_click_through = bool(raw.get("hud_click_through", True))

        self.fps_show = bool(raw.get("fps_show", False))
        self.fps_click_through = bool(raw.get("fps_click_through", True))
        side2 = str(raw.get("fps_side") or "right").lower()
        self.fps_side = side2 if side2 in ("left", "right") else "right"
        try:
            self.fps_scale = max(12, min(36, int(raw.get("fps_scale", 20))))
        except (TypeError, ValueError):
            self.fps_scale = 20
        try:
            self.fps_alpha = max(55, min(100, int(raw.get("fps_alpha", 88))))
        except (TypeError, ValueError):
            self.fps_alpha = 88
        self.cross_show = bool(raw.get("cross_show", False))
        cstyle = str(raw.get("cross_style") or "cross").strip().lower()
        self.cross_style = cstyle if cstyle in ("cross", "dot", "t", "circle") else "cross"
        try:
            self.cross_size = max(2, min(90, int(raw.get("cross_size", 8))))
        except (TypeError, ValueError):
            self.cross_size = 8
        try:
            self.cross_thickness = max(1, min(10, int(raw.get("cross_thickness", 2))))
        except (TypeError, ValueError):
            self.cross_thickness = 2
        try:
            self.cross_gap = max(0, min(60, int(raw.get("cross_gap", 4))))
        except (TypeError, ValueError):
            self.cross_gap = 4
        ccol = str(raw.get("cross_color") or "#20ffe0").strip()
        self.cross_color = ccol if ccol.startswith("#") else "#20ffe0"
        try:
            self.cross_alpha = max(15, min(100, int(raw.get("cross_alpha", 92))))
        except (TypeError, ValueError):
            self.cross_alpha = 92
        self.cross_dot = bool(raw.get("cross_dot", True))
        self.cross_outline = bool(raw.get("cross_outline", True))
        self.theme = str(raw.get("theme") or "cyber").strip() or "cyber"
        mode = str(raw.get("window_mode") or "classic").strip().lower()
        self.window_mode = mode if mode in ("classic", "glass", "liquid") else "classic"
        self.art_show = bool(raw.get("art_show", False))
        self.art_file = str(raw.get("art_file") or "").strip()
        try:
            self.art_blur = max(0, min(60, int(raw.get("art_blur", 18))))
        except (TypeError, ValueError):
            self.art_blur = 18
        self.machine_tag = str(raw.get("machine_tag") or "")
        self.guide_shown = bool(raw.get("guide_shown", False))
        self.bar_on = bool(raw.get("bar_on", True))
        bp = raw.get("bar_pos") or []
        self.bar_pos = [int(bp[0]), int(bp[1])] if isinstance(bp, (list, tuple)) and len(bp) >= 2 else []
        bs = str(raw.get("bar_side") or "").lower()
        self.bar_side = bs if bs in ("left", "right") else ""
        # 内置页面模组只播种一次，用户删掉后不再自动加回来
        self.page_mods_seeded = bool(raw.get("page_mods_seeded", False))
        fpos = raw.get("fps_pos") or []
        self.fps_pos = [int(fpos[0]), int(fpos[1])] if isinstance(fpos, (list, tuple)) and len(fpos) == 2 else []
        pos = raw.get("hud_pos") or []
        self.hud_pos = [int(pos[0]), int(pos[1])] if isinstance(pos, (list, tuple)) and len(pos) == 2 else []
        self._migrate_bundled()
        self.save()

    def _migrate_bundled(self) -> None:
        """内置模组存在时，把指桌面上旧路径的同名模组切到内置副本，缺了就补一条。"""
        for name, rel, extra_args in BUNDLED_MODS:
            builtin = app_dir() / rel
            if not builtin.exists():
                continue
            builtin_name = Path(rel).name
            hit = False
            for mod in self.mods:
                if mod.kind != KIND_EXE:
                    continue
                if mod.name == name or Path(mod.path).name == builtin_name:
                    if mod.path != rel:
                        mod.path = rel
                    mod.kind = KIND_EXE
                    if not mod.name:
                        mod.name = name
                    # 内置模组的启动参数是功能必需（比如 --profile 不碰系统目录）
                    if extra_args and not mod.args:
                        mod.args = list(extra_args)
                    hit = True
            if not hit:
                self.mods.append(
                    Mod(
                        id=uuid.uuid4().hex[:8],
                        name=name,
                        path=rel,
                        kind=KIND_EXE,
                        args=list(extra_args),
                    )
                )

        # 内置页面（不指向外部文件）：缺哪条补哪条，这样老用户升级后
        # 也能拿到后来才加进来的内置页（自己删掉的不强求，下次启动会补回）
        for name, key, note in BUILTIN_PAGES:
            if any(m.kind == KIND_PAGE and m.path == key for m in self.mods):
                continue
            self.mods.append(
                Mod(
                    id=f"builtin-{key}",
                    name=name,
                    path=key,
                    kind=KIND_PAGE,
                    note=note,
                )
            )
        # 投屏挪回主页方块之后，模组里那张同款卡不再保留（升级过的用户也一起清）
        # 口琴搬成 .sjmod 模组之后同理：工具页那份摘掉，免得两个入口抢一个进程
        keep = []
        for m in self.mods:
            p = str(m.path or "").replace("\\", "/").lower()
            if m.kind == KIND_EXE and p.endswith("bundled/scrcpy/scrcpy.exe"):
                continue
            if m.kind == KIND_EXE and p.endswith("口琴可视化曲谱.exe"):
                continue
            keep.append(m)
        self.mods = keep
        self.page_mods_seeded = True

    def save(self) -> None:
        data = {
            "native": list(self.native),
            "target": list(self.target),
            "target_auto": self.target_auto,
            "clip_token": self.clip_token,
            "lan_id": self.lan_id,
            "clip_auto": self.clip_auto,
            "recv_dir": self.recv_dir,
            "hotkey_enabled": self.hotkey_enabled,
            "hotkey_on": dict(self.hotkey_on),
            "replay_max_gb": self.replay_max_gb,
            "replay_dir": self.replay_dir,
            "media_dir": self.media_dir,
            "audio_a": self.audio_a,
            "audio_b": self.audio_b,
            "audio_tray_icon": self.audio_tray_icon,
            "ping_host": self.ping_host,
            "hotkeys": dict(self.hotkeys),
            "close_to_tray": self.close_to_tray,
            "clip_enabled": self.clip_enabled,
            "tray_tip_shown": self.tray_tip_shown,
            "view_mode": self.view_mode,
            "mod_view_mode": self.mod_view_mode,
            "autostart": self.autostart,
            "stretch": self.stretch,
            "screen_device": self.screen_device,
            "gpu_vendor": self.gpu_vendor,
            "ace_guard": self.ace_guard,
            "pwd_auto": self.pwd_auto,
            "hud_show": self.hud_show,
            "hud_pos": list(self.hud_pos or []),
            "hud_scale": self.hud_scale,
            "hud_alpha": self.hud_alpha,
            "hud_lock": self.hud_lock,
            "hud_side": self.hud_side,
            "hud_click_through": self.hud_click_through,
            "fps_show": self.fps_show,
            "fps_pos": list(self.fps_pos or []),
            "fps_side": self.fps_side,
            "fps_scale": self.fps_scale,
            "fps_alpha": self.fps_alpha,
            "fps_click_through": self.fps_click_through,
            "cross_show": self.cross_show,
            "cross_style": self.cross_style,
            "cross_size": self.cross_size,
            "cross_thickness": self.cross_thickness,
            "cross_gap": self.cross_gap,
            "cross_color": self.cross_color,
            "cross_alpha": self.cross_alpha,
            "cross_dot": self.cross_dot,
            "cross_outline": self.cross_outline,
            "theme": self.theme,
            "window_mode": self.window_mode,
            "art_show": self.art_show,
            "art_file": self.art_file,
            "art_blur": self.art_blur,
            "machine_tag": self.machine_tag,
            "guide_shown": self.guide_shown,
            "bar_on": self.bar_on,
            "bar_pos": list(self.bar_pos or []),
            "bar_side": self.bar_side,
            "page_mods_seeded": bool(self.page_mods_seeded),
            "mods": [m.to_dict() for m in self.mods],
            "rules": [r.to_dict() for r in self.rules],
        }
        try:
            config_path().write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError:
            pass

    # ---------- 模组增删 ----------
    def add_mod(self, name: str, path: str, kind: str = "", dl: str = "") -> Mod:
        path = str(path)
        mod = Mod(id=uuid.uuid4().hex[:8], name=name or Path(path).stem, path=path,
                  kind=kind or guess_kind(path), dl=str(dl or ""), enabled=True)
        self.mods.append(mod)
        self.save()
        return mod

    def remove_mod(self, mod_id: str) -> None:
        self.mods = [m for m in self.mods if m.id != mod_id]
        self.save()

    def get_mod(self, mod_id: str) -> Optional[Mod]:
        for m in self.mods:
            if m.id == mod_id:
                return m
        return None

    # ---------- 原生分辨率 ----------
    def set_native(self, w: int, h: int, hz: int = 0) -> None:
        self.native = (int(w), int(h), int(hz))
        self.save()

    def has_native(self) -> bool:
        return self.native[0] > 0 and self.native[1] > 0

    # ---------- 自动化规则 ----------
    def add_rule(self, rule: Rule) -> None:
        self.rules.append(rule)
        self.save()

    def update_rule(self, rule: Rule) -> None:
        for i, r in enumerate(self.rules):
            if r.id == rule.id:
                self.rules[i] = rule
                break
        self.save()

    def remove_rule(self, rule_id: str) -> None:
        self.rules = [r for r in self.rules if r.id != rule_id]
        self.save()

    def get_rule(self, rule_id: str) -> Optional[Rule]:
        for r in self.rules:
            if r.id == rule_id:
                return r
        return None
