"""燧镜模组框架核心（apiVersion = "1"）。

一个 .sjmod 就是一个 zip 包：

    manifest.json
    main.py
    assets\\...

分工：
    宿主（燧镜）  —— 扫描 / 校验 / 解压安装 / 加载 / 启停 / 卸载 / 记状态
    模组（main.py）—— 只实现四个钩子，能力一律通过 host 对象申请

为什么单独双击打不开：
    1. 包里没有 exe，只有 .py 和资源
    2. main.py 里 `from host import ...` 那种写法拿不到东西，
       入口只通过宿主传进来的 host 参数工作，单独 import 必然失败
    3. manifest 里 apiVersion 对不上，宿主直接拒绝加载

约定：
    kind = "package"   纯 Python 模组，入口 main.py
    kind = "external"  包装一个现成程序（口琴这种），入口是 exe
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
API_VERSION = "1"
MOD_SUFFIX = ".sjmod"
MANIFEST_NAME = "manifest.json"
STATE_NAME = "mod_state.json"

KIND_PACKAGE = "package"
KIND_EXTERNAL = "external"

REQUIRED_FIELDS = (
    "id",
    "name",
    "version",
    "apiVersion",
    "author",
    "description",
    "kind",
    "permissions",
)

# 宿主能发的能力；manifest.permissions 里写了哪个才能用哪个
KNOWN_PERMISSIONS = (
    "notify",
    "ui.page",
    "hotkey",
    "shell",
    "events",
    "schedule",
    "fs.data",
)

ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.\-]{1,39}$")


def app_dir() -> Path:
    """程序所在目录（打包后是 exe 所在目录，源码运行时是项目根目录）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def mods_root() -> Path:
    """用户模组目录：文档\\燧镜\\mods（不放 Program Files，免得要管理员权限）。"""
    return Path(os.path.expanduser("~")) / "Documents" / "燧镜" / "mods"


def builtin_mods_root() -> Path:
    """随软件一起打包的模组目录。"""
    return app_dir() / "mods" / "_builtin"


def state_path() -> Path:
    return app_dir() / STATE_NAME


# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
_logger = logging.getLogger("sjmod")
if not _logger.handlers:
    try:
        log_dir = app_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        _h = logging.FileHandler(log_dir / "mods.log", encoding="utf-8")
        _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
        _logger.addHandler(_h)
        _logger.setLevel(logging.INFO)
    except OSError:
        pass


def log(msg: str, level: int = logging.INFO) -> None:
    _logger.log(level, msg)


# ---------------------------------------------------------------------------
# manifest
# ---------------------------------------------------------------------------
class ManifestError(Exception):
    """manifest 不合格。"""


@dataclass
class ModSpec:
    id: str
    name: str
    version: str
    api_version: str
    author: str
    description: str
    kind: str
    entry: str
    permissions: List[str]
    root: Path
    builtin: bool = False
    min_app_version: str = ""
    # kind=external 用
    external_path: str = ""
    external_args: List[str] = field(default_factory=list)

    @property
    def resolved_external(self) -> str:
        """外部程序真实路径。

        支持 {app} 占位符（指向程序目录），内置包装模组靠它引用 bundled 里的 exe，
        换电脑、换安装目录都不用改 manifest。
        """
        if not self.external_path:
            return ""
        text = self.external_path.replace("{app}", str(app_dir()))
        p = Path(text)
        if not p.is_absolute():
            p = self.root / p
        return str(p)

    @property
    def source_label(self) -> str:
        return "内置" if self.builtin else "外部"

    @property
    def kind_label(self) -> str:
        return "程序包装" if self.kind == KIND_EXTERNAL else "扩展包"

    def has(self, perm: str) -> bool:
        return perm in self.permissions


def read_manifest(folder: Path) -> dict:
    mf = folder / MANIFEST_NAME
    if not mf.exists():
        raise ManifestError(f"缺少 {MANIFEST_NAME}")
    try:
        raw = json.loads(mf.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as e:
        raise ManifestError(f"{MANIFEST_NAME} 读不出来：{e}") from e
    if not isinstance(raw, dict):
        raise ManifestError(f"{MANIFEST_NAME} 必须是一个 JSON 对象")
    return raw


def parse_manifest(raw: dict, root: Path, builtin: bool = False) -> ModSpec:
    """把 dict 校验并转成 ModSpec；任何一处不合格就抛 ManifestError。"""
    missing = [k for k in REQUIRED_FIELDS if k not in raw]
    if missing:
        raise ManifestError("缺少必填字段：" + "、".join(missing))

    mid = str(raw.get("id") or "").strip()
    if not ID_RE.match(mid):
        raise ManifestError(f"id 不合法：{mid!r}（只能用小写字母、数字、下划线、点和横线，2-40 位）")

    api = str(raw.get("apiVersion") or "").strip()
    if api != API_VERSION:
        raise ManifestError(
            f"apiVersion 是 {api!r}，本宿主只支持 {API_VERSION!r}（要么改包，要么升级燧镜）"
        )

    kind = str(raw.get("kind") or KIND_PACKAGE).strip()
    if kind not in (KIND_PACKAGE, KIND_EXTERNAL):
        raise ManifestError(f"kind 只能是 {KIND_PACKAGE} 或 {KIND_EXTERNAL}，收到 {kind!r}")

    perms_raw = raw.get("permissions") or []
    if not isinstance(perms_raw, list):
        raise ManifestError("permissions 必须是数组")
    perms = [str(p).strip() for p in perms_raw if str(p).strip()]
    unknown = [p for p in perms if p not in KNOWN_PERMISSIONS]
    if unknown:
        raise ManifestError("未知权限：" + "、".join(unknown))

    entry = str(raw.get("entry") or "").strip()
    if kind == KIND_PACKAGE:
        entry = entry or "main.py"
        if not (root / entry).exists():
            raise ManifestError(f"入口文件不存在：{entry}")

    ext_path = ""
    ext_args: List[str] = []
    if kind == KIND_EXTERNAL:
        block = raw.get("external") or {}
        if not isinstance(block, dict):
            raise ManifestError("kind=external 时必须给 external 对象")
        ext_path = str(block.get("path") or "").strip()
        if not ext_path:
            raise ManifestError("external.path 不能为空")
        args = block.get("args") or []
        ext_args = [str(a) for a in args] if isinstance(args, list) else []

    return ModSpec(
        id=mid,
        name=str(raw.get("name") or mid).strip(),
        version=str(raw.get("version") or "0.0.0").strip(),
        api_version=api,
        author=str(raw.get("author") or "未知").strip(),
        description=str(raw.get("description") or "").strip(),
        kind=kind,
        entry=entry,
        permissions=perms,
        root=root,
        builtin=builtin or bool(raw.get("builtin", False)),
        min_app_version=str(raw.get("minAppVersion") or "").strip(),
        external_path=ext_path,
        external_args=ext_args,
    )


def load_spec(folder: Path, builtin: bool = False) -> ModSpec:
    return parse_manifest(read_manifest(folder), folder, builtin=builtin)


# ---------------------------------------------------------------------------
# 事件总线
# ---------------------------------------------------------------------------
class EventBus:
    """宿主与模组之间、模组与模组之间的轻量广播。"""

    def __init__(self) -> None:
        self._subs: Dict[str, List[Callable[..., Any]]] = {}
        self._lock = threading.Lock()

    def on(self, name: str, fn: Callable[..., Any]) -> None:
        with self._lock:
            self._subs.setdefault(name, []).append(fn)

    def off(self, name: str, fn: Callable[..., Any]) -> None:
        with self._lock:
            lst = self._subs.get(name) or []
            if fn in lst:
                lst.remove(fn)

    def emit(self, name: str, *args: Any, **kwargs: Any) -> None:
        with self._lock:
            targets = list(self._subs.get(name) or [])
        for fn in targets:
            try:
                fn(*args, **kwargs)
            except Exception:
                log(f"事件 {name} 的订阅者出错：\n{traceback.format_exc()}", logging.ERROR)


EVENTS = EventBus()


# ---------------------------------------------------------------------------
# host：模组能拿到的一切
# ---------------------------------------------------------------------------
class _PermDenied(Exception):
    pass


def guard(spec: ModSpec, perm: str) -> None:
    if not spec.has(perm):
        raise _PermDenied(
            f"模组 {spec.id} 没有申请 {perm} 权限，manifest.permissions 里加上才能调用"
        )


class _LogApi:
    def __init__(self, spec: ModSpec) -> None:
        self._spec = spec

    def info(self, msg: Any) -> None:
        log(f"[{self._spec.id}] {msg}")

    def warn(self, msg: Any) -> None:
        log(f"[{self._spec.id}] {msg}", logging.WARNING)

    def error(self, msg: Any, exc: bool = False) -> None:
        text = f"{msg}\n{traceback.format_exc()}" if exc else str(msg)
        log(f"[{self._spec.id}] {text}", logging.ERROR)


class _CfgApi:
    """每个模组一份自己的 config.json，存在 data/<id>/ 里。"""

    def __init__(self, spec: ModSpec, data_dir: Path) -> None:
        self._spec = spec
        self._dir = data_dir
        self._file = data_dir / "config.json"
        self._data: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self) -> None:
        try:
            if self._file.exists():
                raw = json.loads(self._file.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._data = raw
        except (OSError, json.JSONDecodeError) as e:
            log(f"[{self._spec.id}] 配置读失败：{e}", logging.WARNING)

    def _save(self) -> None:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._file.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as e:
            log(f"[{self._spec.id}] 配置写失败：{e}", logging.ERROR)

    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._data[key] = value
            self._save()


class _PathsApi:
    def __init__(self, spec: ModSpec, data_dir: Path) -> None:
        self._spec = spec
        self._data_dir = data_dir

    @property
    def data_dir(self) -> Path:
        return self._data_dir

    @property
    def resource(self) -> Path:
        return self._spec.root

    @property
    def assets(self) -> Path:
        return self._spec.root / "assets"


class _UiApi:
    def __init__(self, spec: ModSpec, on_register: Optional[Callable[..., Any]]) -> None:
        self._spec = spec
        self._on_register = on_register
        self._pages: List[str] = []

    def register_page(self, key: str, builder: Callable[..., Any]) -> None:
        guard(self._spec, "ui.page")
        if self._on_register is None:
            log(f"[{self._spec.id}] 宿主没接 UI，register_page({key}) 被忽略", logging.WARNING)
            return
        self._on_register(self._spec, key, builder)
        self._pages.append(key)

    def unregister_page(self, key: str) -> None:
        if key in self._pages:
            self._pages.remove(key)


class _HotkeyApi:
    def __init__(self, spec: ModSpec, on_register: Optional[Callable[..., Any]]) -> None:
        self._spec = spec
        self._on_register = on_register
        self._keys: List[str] = []

    def register(self, combo: str, fn: Callable[[], Any]) -> None:
        guard(self._spec, "hotkey")
        if self._on_register is None:
            log(f"[{self._spec.id}] 宿主没接热键，register({combo}) 被忽略", logging.WARNING)
            return
        self._on_register(self._spec, combo, fn)
        self._keys.append(combo)

    def unregister(self, combo: str) -> None:
        if combo in self._keys:
            self._keys.remove(combo)


class _ShellApi:
    def __init__(self, spec: ModSpec) -> None:
        self._spec = spec

    def launch(self, path: str, args: Optional[List[str]] = None) -> bool:
        guard(self._spec, "shell")
        try:
            subprocess.Popen(
                [str(path)] + [str(a) for a in (args or [])],
                cwd=str(Path(path).parent),
                creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
            )
            return True
        except OSError:
            log(f"[{self._spec.id}] 启动失败：\n{traceback.format_exc()}", logging.ERROR)
            return False


class _ScheduleApi:
    """极简定时器：每 N 秒跑一次，模组停用/卸载时全部掐掉。"""

    def __init__(self, spec: ModSpec) -> None:
        self._spec = spec
        self._timers: List[threading.Timer] = []
        self._stopped = False
        self._lock = threading.Lock()

    def every(self, seconds: float, fn: Callable[[], Any]) -> None:
        guard(self._spec, "schedule")
        interval = max(0.5, float(seconds))
        with self._lock:
            # 上一次停用把它置成 True 了，重新启用后要能再跑
            self._stopped = False

        def tick() -> None:
            with self._lock:
                if self._stopped:
                    return
            try:
                fn()
            except Exception:
                log(f"[{self._spec.id}] 定时任务出错：\n{traceback.format_exc()}", logging.ERROR)
            with self._lock:
                if self._stopped:
                    return
                t = threading.Timer(interval, tick)
                t.daemon = True
                self._timers.append(t)
            t.start()

        t = threading.Timer(interval, tick)
        t.daemon = True
        with self._lock:
            self._timers.append(t)
        t.start()

    def stop_all(self) -> None:
        with self._lock:
            self._stopped = True
            timers = list(self._timers)
            self._timers.clear()
        for t in timers:
            try:
                t.cancel()
            except Exception:
                pass


class _EventsApi:
    def __init__(self, spec: ModSpec) -> None:
        self._spec = spec

    def on(self, name: str, fn: Callable[..., Any]) -> None:
        guard(self._spec, "events")
        EVENTS.on(name, fn)

    def emit(self, name: str, *args: Any, **kwargs: Any) -> None:
        guard(self._spec, "events")
        EVENTS.emit(name, *args, **kwargs)


class Host:
    """传给模组 on_load(host) 的那个 host。"""

    def __init__(
        self,
        spec: ModSpec,
        data_dir: Path,
        ui_register: Optional[Callable[..., Any]] = None,
        hotkey_register: Optional[Callable[..., Any]] = None,
        notify: Optional[Callable[[str, str, str], None]] = None,
        app_version: str = "",
    ) -> None:
        self.spec = spec
        self.app_version = app_version
        self.api_version = API_VERSION

        self.log = _LogApi(spec)
        self.cfg = _CfgApi(spec, data_dir)
        self.paths = _PathsApi(spec, data_dir)
        self.ui = _UiApi(spec, ui_register)
        self.hotkey = _HotkeyApi(spec, hotkey_register)
        self.shell = _ShellApi(spec)
        self.schedule = _ScheduleApi(spec)
        self.events = _EventsApi(spec)
        self._notify = notify

    def notify(self, title: str, text: str, level: str = "info") -> None:
        guard(self.spec, "notify")
        if self._notify is not None:
            try:
                self._notify(str(title), str(text), str(level))
                return
            except Exception:
                log(f"[{self.spec.id}] 通知发送失败：\n{traceback.format_exc()}", logging.ERROR)
        log(f"[{self.spec.id}] 通知：{title} / {text}")


# ---------------------------------------------------------------------------
# 运行时：一个已加载的模组
# ---------------------------------------------------------------------------
STATUS_LOADED = "loaded"
STATUS_ENABLED = "enabled"
STATUS_FAILED = "failed"


class ModRuntime:
    """管一个模组的加载 / 启用 / 停用 / 卸载。"""

    def __init__(
        self,
        spec: ModSpec,
        data_dir: Path,
        ui_register: Optional[Callable[..., Any]] = None,
        hotkey_register: Optional[Callable[..., Any]] = None,
        notify: Optional[Callable[[str, str, str], None]] = None,
        app_version: str = "",
    ) -> None:
        self.spec = spec
        self.status = "new"
        self.error = ""
        self.host = Host(
            spec,
            data_dir,
            ui_register=ui_register,
            hotkey_register=hotkey_register,
            notify=notify,
            app_version=app_version,
        )
        self._module: Any = None
        self._enabled = False
        # 外部程序包装用
        self._proc: Optional[subprocess.Popen] = None

    # ---------- 包模组 ----------
    def _import_entry(self) -> Any:
        path = self.spec.root / self.spec.entry
        name = f"sjmod_{self.spec.id.replace('.', '_')}"
        # 让 main.py 能 import 同目录的兄弟文件（assets 之类不该 import，放这里只为兼容）
        added = str(self.spec.root)
        inserted = False
        if added not in sys.path:
            sys.path.insert(0, added)
            inserted = True
        try:
            spec = importlib.util.spec_from_file_location(name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"没法加载 {path}")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[name] = mod
            spec.loader.exec_module(mod)
            return mod
        finally:
            if inserted:
                try:
                    sys.path.remove(added)
                except ValueError:
                    pass

    def load(self) -> bool:
        if self.spec.kind == KIND_EXTERNAL:
            self.status = STATUS_LOADED
            return True
        try:
            self._module = self._import_entry()
            fn = getattr(self._module, "on_load", None)
            if callable(fn):
                fn(self.host)
            self.status = STATUS_LOADED
            self.error = ""
            return True
        except Exception:
            self.status = STATUS_FAILED
            self.error = traceback.format_exc()
            log(f"[{self.spec.id}] 加载失败：\n{self.error}", logging.ERROR)
            return False

    def enable(self) -> bool:
        if self._enabled:
            return True
        if self.status == STATUS_FAILED:
            return False
        if self.status == "new":
            if not self.load():
                return False
        try:
            if self.spec.kind == KIND_EXTERNAL:
                self._launch_external()
            else:
                fn = getattr(self._module, "on_enable", None)
                if callable(fn):
                    fn()
            self._enabled = True
            self.status = STATUS_ENABLED
            return True
        except Exception:
            self.error = traceback.format_exc()
            log(f"[{self.spec.id}] 启用失败：\n{self.error}", logging.ERROR)
            self.status = STATUS_FAILED
            return False

    def disable(self) -> bool:
        if not self._enabled:
            return True
        try:
            if self.spec.kind == KIND_EXTERNAL:
                self._stop_external()
            else:
                fn = getattr(self._module, "on_disable", None)
                if callable(fn):
                    fn()
            self.host.schedule.stop_all()
            self._enabled = False
            self.status = STATUS_LOADED
            return True
        except Exception:
            self.error = traceback.format_exc()
            log(f"[{self.spec.id}] 停用出错：\n{self.error}", logging.ERROR)
            return False

    def unload(self) -> None:
        self.disable()
        try:
            fn = getattr(self._module, "on_unload", None)
            if callable(fn):
                fn()
        except Exception:
            log(f"[{self.spec.id}] 卸载钩子出错：\n{traceback.format_exc()}", logging.ERROR)
        self._module = None

    # ---------- 外部程序 ----------
    def _launch_external(self) -> None:
        exe = self.spec.resolved_external
        if not Path(exe).exists():
            raise FileNotFoundError(f"外部程序不存在：{exe}")
        self._proc = subprocess.Popen(
            [exe] + self.spec.external_args,
            cwd=str(Path(exe).parent),
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )

    def _stop_external(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None or proc.poll() is not None:
            return
        try:
            proc.terminate()
            for _ in range(20):
                if proc.poll() is not None:
                    return
                time.sleep(0.1)
            proc.kill()
        except OSError:
            log(f"[{self.spec.id}] 关进程失败：\n{traceback.format_exc()}", logging.ERROR)

    @property
    def running(self) -> bool:
        if self.spec.kind == KIND_EXTERNAL:
            return self._proc is not None and self._proc.poll() is None
        return self._enabled


# ---------------------------------------------------------------------------
# 注册表：扫描 / 安装 / 卸载 / 状态
# ---------------------------------------------------------------------------
class ModRegistry:
    def __init__(
        self,
        on_app_dirs: Optional[List[Path]] = None,
        ui_register: Optional[Callable[..., Any]] = None,
        hotkey_register: Optional[Callable[..., Any]] = None,
        notify: Optional[Callable[[str, str, str], None]] = None,
        app_version: str = "",
    ) -> None:
        self.user_dir = mods_root()
        self.builtin_dir = builtin_mods_root()
        self.runtimes: Dict[str, ModRuntime] = {}
        self.invalid: List[tuple] = []  # [(名字, 原因)]
        self._ui_register = ui_register
        self._hotkey_register = hotkey_register
        self._notify = notify
        self.app_version = app_version
        self._lock = threading.Lock()

    # ---------- 状态 ----------
    def _read_state(self) -> dict:
        try:
            p = state_path()
            if p.exists():
                raw = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    return raw
        except (OSError, json.JSONDecodeError):
            pass
        return {}

    def _write_state(self) -> None:
        data = {"enabled": {k: bool(v.running) for k, v in self.runtimes.items()}}
        try:
            state_path().write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as e:
            log(f"状态写入失败：{e}", logging.ERROR)

    # ---------- 扫描 ----------
    def scan(self) -> List[ModRuntime]:
        """扫描两个目录，重建 runtimes；同 id 时用户目录优先。"""
        self.user_dir.mkdir(parents=True, exist_ok=True)
        found: Dict[str, ModRuntime] = {}
        self.invalid = []

        for base, is_builtin in ((self.user_dir, False), (self.builtin_dir, True)):
            if not base.exists():
                continue
            for child in sorted(base.iterdir()):
                if not child.is_dir() or child.name.startswith("_"):
                    continue
                try:
                    spec = load_spec(child, builtin=is_builtin)
                except ManifestError as e:
                    self.invalid.append((child.name, str(e)))
                    log(f"跳过 {child.name}：{e}", logging.WARNING)
                    continue
                if spec.id in found:
                    continue  # 用户目录先扫，已占位
                data_dir = app_dir() / "mods_data" / spec.id
                found[spec.id] = ModRuntime(
                    spec,
                    data_dir,
                    ui_register=self._ui_register,
                    hotkey_register=self._hotkey_register,
                    notify=self._notify,
                    app_version=self.app_version,
                )

        with self._lock:
            self.runtimes = found
        return list(found.values())

    def get(self, mod_id: str) -> Optional[ModRuntime]:
        with self._lock:
            return self.runtimes.get(mod_id)

    def all(self) -> List[ModRuntime]:
        with self._lock:
            return list(self.runtimes.values())

    # ---------- 启停 ----------
    def enable(self, mod_id: str) -> bool:
        rt = self.get(mod_id)
        if rt is None:
            return False
        ok = rt.enable()
        self._write_state()
        return ok

    def disable(self, mod_id: str) -> bool:
        rt = self.get(mod_id)
        if rt is None:
            return False
        ok = rt.disable()
        self._write_state()
        return ok

    def enable_all(self) -> None:
        state = self._read_state().get("enabled") or {}
        for rt in self.all():
            if state.get(rt.spec.id):
                rt.enable()
        self._write_state()

    def shutdown(self) -> None:
        for rt in self.all():
            rt.unload()
        self._write_state()

    # ---------- 安装 ----------
    def install(self, package: Path) -> tuple:
        """返回 (ok, 消息)。把 .sjmod 解到 mods/<id>/。"""
        package = Path(package)
        if not package.exists():
            return False, f"文件不存在：{package}"
        if package.suffix.lower() not in (MOD_SUFFIX, ".zip"):
            return False, f"不是模组包：{package.name}"

        tmp = self.user_dir / f"_tmp_{uuid.uuid4().hex[:8]}"
        try:
            tmp.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(package) as zf:
                bad = zf.testzip()
                if bad is not None:
                    return False, f"包损坏：{bad}"
                zf.extractall(tmp)

            # 允许包里套一层目录（很多人打包时习惯加一层）
            root = tmp
            if not (root / MANIFEST_NAME).exists():
                subs = [d for d in root.iterdir() if d.is_dir()]
                if len(subs) == 1 and (subs[0] / MANIFEST_NAME).exists():
                    root = subs[0]

            spec = load_spec(root, builtin=False)

            target = self.user_dir / spec.id
            if target.exists():
                return False, f"已经装了同 id 的模组（{spec.id}），先卸载或换 id"

            shutil.move(str(root), str(target))
            self.scan()
            return True, f"已安装：{spec.name} v{spec.version}"
        except ManifestError as e:
            self._quarantine(package, str(e))
            return False, f"manifest 不合格：{e}"
        except (OSError, zipfile.BadZipFile) as e:
            log(f"安装失败 {package.name}：{traceback.format_exc()}", logging.ERROR)
            return False, f"安装失败：{e}"
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def _quarantine(self, package: Path, reason: str) -> None:
        """坏包丢进 _invalid\\，方便用户回头排查。"""
        try:
            bad_dir = self.user_dir / "_invalid"
            bad_dir.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d_%H%M%S")
            dest = bad_dir / f"{package.stem}_{stamp}{package.suffix}"
            shutil.copy2(package, dest)
            log(f"坏包已移入 {dest}：{reason}", logging.WARNING)
        except OSError:
            pass

    def uninstall(self, mod_id: str) -> tuple:
        rt = self.get(mod_id)
        if rt is None:
            return False, "没这个模组"
        if rt.spec.builtin:
            return False, "内置模组不能卸载，只能停用"
        rt.unload()
        target = rt.spec.root
        try:
            shutil.rmtree(target, ignore_errors=False)
        except OSError as e:
            return False, f"删目录失败：{e}"
        self.scan()
        self._write_state()
        return True, f"已卸载：{rt.spec.name}"
