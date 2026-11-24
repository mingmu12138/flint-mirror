# -*- coding: utf-8 -*-
"""平台视频 · 燧镜模组（apiVersion = 1）

功能：粘贴 B 站 / YouTube 等链接 → yt-dlp 下载 → ffmpeg 统一转 H.264 + AAC 的 MP4
→ 在置顶无边框悬浮窗里用 QtMultimedia 播放，打游戏时旁边看攻略不用切出去。

规矩（照 docs\\MOD_API.md）：
1. on_load 只登记：界面页 + 热键，不起业务
2. on_enable 起业务：建悬浮窗、读配置、出提示
3. on_disable 收干净：停线程、杀转码进程、关播放器、关窗、清 temp
4. on_unload 再清一遍本地缓存（temp + 复制的 ffmpeg）
5. 只用 host 给的能力，不 import 燧镜内部模块，不自造 QMainWindow
"""

from __future__ import annotations

import ctypes
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from PySide6 import QtCore, QtGui, QtMultimedia, QtMultimediaWidgets, QtWidgets

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
HOTKEY_TOGGLE = "Ctrl+Alt+V"          # 显隐悬浮窗
TEMP_DIR = "temp"                     # 缓存目录，放在 host.paths.data_dir 下
BIN_DIR = "bin"                       # 复制过来的 ffmpeg.exe
DEFAULT_SIZE = (760, 428)

KEY_URL = "url"
KEY_VOLUME = "volume"
KEY_MUTED = "muted"
KEY_CLICK_THROUGH = "click_through"
KEY_GEOMETRY = "geometry"

# 全局上下文：宿主对象 + 窗口 + 任务，只有一份
_CTX = {
    "host": None,
    "overlay": None,
    "panel": None,
    "job": None,
    "enabled": False,
}


class _Cancelled(Exception):
    """用户取消（停用模组时触发）。"""


# ---------------------------------------------------------------------------
# 小工具：配置 / 路径 / ffmpeg
# ---------------------------------------------------------------------------
def _cfg_get(key, default=None):
    host = _CTX["host"]
    if host is None:
        return default
    try:
        return host.cfg.get(key, default)
    except Exception:
        return default


def _cfg_set(key, value):
    host = _CTX["host"]
    if host is None:
        return
    try:
        host.cfg.set(key, value)
    except Exception:
        host.log.warn(f"配置写不进去：{key}")


def _temp_dir() -> Path:
    d = _CTX["host"].paths.data_dir / TEMP_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def _mount_pylibs() -> None:
    """兜底挂载：宿主正常会把 assets\\lib（或 pylibs）挂好，这里只补老宿主那一手。

    按 docs\\模组接口提示词.txt：宿主在 on_load 之前就挂进 sys.path，模组不要自己 insert；
    所以这里的顺序是「先看有没有，宿主没挂才补」，不覆盖、不重复。
    """
    host = _CTX["host"]
    for name in ("lib", "pylibs"):
        libs = host.paths.assets / name
        if not libs.is_dir():
            continue
        p = str(libs)
        if p in sys.path:                       # 宿主已经挂好了
            host.log.info(f"依赖目录已由宿主挂载：{p}")
            return
        sys.path.insert(0, p)
        _CTX["lib_path"] = p
        host.log.warn(f"宿主没挂依赖目录，模组自己补上：{p}")
        return
    host.log.warn("包里没有 assets\\lib（或 pylibs），下载功能会依赖宿主环境是否装了 yt-dlp")


def _unmount_pylibs() -> None:
    """只摘自己插的那条；宿主插的由宿主在 unload 里摘，别越权删别人的。"""
    p = _CTX.get("lib_path")
    if not p:
        return
    while p in sys.path:
        sys.path.remove(p)
    _CTX["lib_path"] = ""


def _accept_ffmpeg(path: str) -> str:
    """验一次再交出去：用 host.shell.capture 跑一遍 ffmpeg -version。

    两件事一起办了：① 免得拿个坏二进制去转码、转一半才报错；
    ② 让 shell 权限用在明面上——用户装之前就在权限卡上看到「启动外部程序」。
    老宿主没有 capture 就跳过校验，直接当能用。
    """
    if _CTX.get("ffmpeg_ok"):
        return path
    cap = getattr(getattr(_CTX["host"], "shell", None), "capture", None)
    if cap is not None:
        try:
            code, out, err = cap([path, "-version"], 10)
        except Exception as e:
            raise RuntimeError(f"ffmpeg 探测失败：{e}") from e
        if code != 0:
            detail = (err or out or f"返回码 {code}").strip()[:200]
            raise RuntimeError(f"ffmpeg 跑不起来：{detail}")
    _CTX["ffmpeg_ok"] = True
    return path


def _ffmpeg_exe() -> str:
    """拿一个可用的 ffmpeg.exe。

    优先用宿主环境里的 imageio-ffmpeg（燧镜依赖里已经有），
    把它复制成 bin\\ffmpeg.exe 固定文件名 —— yt-dlp 只认得 ffmpeg.exe 这个名字。
    复制一次就复用，别每次下载都拷 80MB。
    """
    host = _CTX["host"]
    bin_dir = host.paths.data_dir / BIN_DIR
    bin_dir.mkdir(parents=True, exist_ok=True)
    target = bin_dir / "ffmpeg.exe"
    if target.exists() and target.stat().st_size > 1024 * 1024:
        try:
            return _accept_ffmpeg(str(target))
        except RuntimeError as e:
            host.log.warn(f"缓存的 ffmpeg 校验没过，重新找：{e}")
            try:
                target.unlink()
            except OSError:
                pass

    # ① 系统 PATH 里的 ffmpeg（用户自己装过就省事）
    for name in ("ffmpeg.exe", "ffmpeg"):
        found = shutil.which(name)
        if not found:
            continue
        try:
            shutil.copy2(found, target)      # 固定成 bin\ffmpeg.exe，yt-dlp 才认
            return _accept_ffmpeg(str(target))
        except OSError:
            return _accept_ffmpeg(found)     # 拷不动就直接用原路径

    # ② 模组自己包里的 assets\bin（随包带 exe 的话就走这条，manifest 必须申请 shell）
    packed = host.paths.assets / "bin" / "ffmpeg.exe"
    if packed.exists():
        try:
            shutil.copy2(packed, target)
            return _accept_ffmpeg(str(target))
        except OSError:
            return _accept_ffmpeg(str(packed))

    # ③ 源码环境兜底：宿主 venv 里有 imageio-ffmpeg（装机版没有，只有开发时能用到）
    src = ""
    try:
        import imageio_ffmpeg  # 纯本地，不联网

        src = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        src = ""

    if src and Path(src).exists():
        shutil.copy2(src, target)
        return _accept_ffmpeg(str(target))

    if target.exists():
        return str(target)

    raise RuntimeError(
        "找不到可用的 ffmpeg，视频下好了但转不了码。\n"
        f"① 把 ffmpeg.exe 放到这里：{target}\n"
        "② 没有的话去 https://www.gyan.dev/ffmpeg/builds/ 或 "
        "https://github.com/BtbN/FFmpeg-Builds/releases 下个 Windows 版，"
        "解压后把 bin\\ffmpeg.exe 拷到上面那个路径\n"
        "③ 放好之后在模组页点「停用」再「启用」，让它重新找一次"
    )


# ---------------------------------------------------------------------------
# 下载 + 转码（跑在后台线程里，界面只收信号）
# ---------------------------------------------------------------------------
class _Bridge(QtCore.QObject):
    """后台线程 → 界面线程的唯一通道。"""

    progress = QtCore.Signal(int, str)   # 百分比（-1 = 不确定），阶段文字
    stage = QtCore.Signal(str)
    done = QtCore.Signal(str)            # 成品文件路径
    failed = QtCore.Signal(str)


class _Job(threading.Thread):
    """一次「下载 + 转码」。线程自己带 stop 标志，停用模组时能立刻断。"""

    def __init__(self, host, url: str) -> None:
        super().__init__(daemon=True, name="platform-video-job")
        self.host = host
        self.url = url
        self.bridge = _Bridge()
        self._stop = threading.Event()
        self._proc = None       # 转码子进程，取消时要能杀掉
        self._last_pct = -2

    # ---------- 对外 ----------
    def cancel(self) -> None:
        self._stop.set()
        p = self._proc
        if p is not None and p.poll() is None:
            try:
                p.terminate()
            except Exception:
                pass

    # ---------- 内部 ----------
    def _check_stop(self) -> None:
        if self._stop.is_set():
            raise _Cancelled()

    def _hook(self, d) -> None:
        self._check_stop()
        status = d.get("status")
        if status == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            got = d.get("downloaded_bytes") or 0
            pct = int(got * 100 / total) if total else -1
            if pct != self._last_pct:
                self._last_pct = pct
                self.bridge.progress.emit(pct, "下载中")
        elif status == "finished":
            self.bridge.progress.emit(100, "下载完成")

    def run(self) -> None:
        try:
            self._do()
        except _Cancelled:
            self.bridge.stage.emit("已取消")
        except Exception as e:
            detail = str(e).strip() or e.__class__.__name__
            self.host.log.error(f"下载失败：{detail}", exc=True)
            self.bridge.failed.emit(detail)

    def _do(self) -> None:
        url = self.url.strip()
        if not url:
            raise RuntimeError("链接是空的")

        tmp = _temp_dir()
        shutil.rmtree(tmp, ignore_errors=True)
        tmp.mkdir(parents=True, exist_ok=True)

        ffmpeg = _ffmpeg_exe()
        ff_dir = str(Path(ffmpeg).parent)

        try:
            import yt_dlp
        except Exception as e:
            # 打包版宿主是 PyInstaller 裁过的 Python，标准库里偏门模块可能没被打进去
            # （典型：optparse / struct / xml.etree）。这些已经随包放在 assets\pylibs，
            # 所以这里把真实异常带出来，缺哪个一眼能看出来。
            raise RuntimeError(
                f"yt-dlp 加载失败：{type(e).__name__}: {e}\n"
                "模组自带的 assets\\pylibs 里应该有完整的依赖，"
                "包可能被拆过或装漏了文件，重装一次模组试试"
            )

        self.bridge.stage.emit("正在解析链接…")
        opts = {
            # 优先直接要 avc1 + m4a（不用转码也省事），拿不到再退到最佳单文件
            "format": "bv*[vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
            "outtmpl": str(tmp / "src.%(ext)s"),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "ffmpeg_location": ff_dir,
            "progress_hooks": [self._hook],
            "retries": 3,
            "socket_timeout": 20,
        }

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise RuntimeError("这个链接解析不出可下载的内容")
            src_text = ydl.prepare_filename(info)

        src = Path(src_text)
        if not src.exists():
            cands = [p for p in tmp.glob("src.*") if p.is_file()]
            if not cands:
                raise RuntimeError("下载完成但找不到文件")
            src = max(cands, key=lambda p: p.stat().st_size)

        self._check_stop()
        self.bridge.progress.emit(-1, "正在转码为 H.264 + AAC…")
        final = tmp / "final.mp4"
        self._transcode(ffmpeg, src, final)
        self._check_stop()

        try:
            src.unlink()
        except OSError:
            pass

        self.bridge.progress.emit(100, "就绪")
        self.bridge.done.emit(str(final))

    def _transcode(self, ffmpeg: str, src: Path, dst: Path) -> None:
        # shell 权限已在 manifest 里声明（用户装之前看得见「启动外部程序」）。
        # 这里没用 host.shell.capture：转码要跑几十秒到几分钟，停用模组时必须能当场
        # terminate，capture 是同步的、掐不断。短命令（-version 探测）走 capture。
        cmd = [
            ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(src),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p",           # 保证各平台/显卡都能解
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart",
            str(dst),
        ]
        flags = 0x08000000  # CREATE_NO_WINDOW，别弹黑框
        try:
            p = subprocess.Popen(
                cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                creationflags=flags,
            )
        except OSError as e:
            raise RuntimeError(f"ffmpeg 起不来：{e}") from e

        self._proc = p
        while p.poll() is None:
            if self._stop.is_set():
                try:
                    p.terminate()
                except Exception:
                    pass
                raise _Cancelled()
            time.sleep(0.2)

        if p.returncode != 0:
            err = ""
            try:
                err = (p.stderr.read() or b"").decode("utf-8", "replace").strip()
            except Exception:
                pass
            raise RuntimeError(f"转码失败：{err[-300:] or 'ffmpeg 返回 ' + str(p.returncode)}")
        if not dst.exists() or dst.stat().st_size == 0:
            raise RuntimeError("转码没有产出文件")


# ---------------------------------------------------------------------------
# 悬浮窗
# ---------------------------------------------------------------------------
class _Overlay(QtWidgets.QWidget):
    """置顶无边框播放窗。是 QWidget，不是 QMainWindow。"""

    geometryChanged = QtCore.Signal(list)

    def __init__(self, host) -> None:
        super().__init__(None)
        self.host = host
        self._drag_from = None
        self._click_through = False
        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self._emit_geometry)

        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint
            | QtCore.Qt.WindowStaysOnTopHint
            | QtCore.Qt.Tool
        )
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground, True)
        self.setWindowTitle("平台视频悬浮窗")
        self.setMinimumSize(360, 220)

        shell = QtWidgets.QVBoxLayout(self)
        shell.setContentsMargins(0, 0, 0, 0)

        self._root = QtWidgets.QWidget(self)
        self._root.setObjectName("Root")
        self._root.setStyleSheet(
            "QWidget#Root{background:rgba(12,14,18,232);"
            "border:1px solid #2B3038;border-radius:10px;}"
        )
        shell.addWidget(self._root)

        col = QtWidgets.QVBoxLayout(self._root)
        col.setContentsMargins(1, 1, 1, 1)
        col.setSpacing(0)

        self.video = QtMultimediaWidgets.QVideoWidget(self._root)
        self.video.setStyleSheet("background:#000;border-radius:9px;")
        col.addWidget(self.video, 1)

        self.bar = QtWidgets.QWidget(self._root)
        self.bar.setFixedHeight(30)
        self.bar.setStyleSheet("background:transparent;")
        row = QtWidgets.QHBoxLayout(self.bar)
        row.setContentsMargins(8, 0, 6, 0)
        row.setSpacing(6)

        self.grip_label = QtWidgets.QLabel("按住这里拖动", self.bar)
        self.grip_label.setStyleSheet("color:#8A939E;font-size:11px;")
        row.addWidget(self.grip_label)
        row.addStretch(1)

        self.btn_play = self._mini_button("暂停")
        self.btn_mute = self._mini_button("静音")
        self.btn_close = self._mini_button("关闭")
        self.btn_play.clicked.connect(self.toggle_play)
        self.btn_mute.clicked.connect(self.toggle_mute)
        self.btn_close.clicked.connect(self.hide)
        row.addWidget(self.btn_play)
        row.addWidget(self.btn_mute)
        row.addWidget(self.btn_close)

        self.grip = QtWidgets.QSizeGrip(self._root)   # 右下角缩放
        self.grip.setFixedSize(14, 14)
        self.grip.setStyleSheet("background:transparent;")

        col.addWidget(self.bar)
        self.bar.installEventFilter(self)

        # 播放器
        self.player = QtMultimedia.QMediaPlayer(self)
        self.audio = QtMultimedia.QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.player.setVideoOutput(self.video)
        self.player.errorOccurred.connect(self._on_player_error)
        self.player.playbackStateChanged.connect(self._on_state)

        self._apply_volume()
        self.set_click_through(bool(_cfg_get(KEY_CLICK_THROUGH, False)))

    # ---------- 小控件 ----------
    def _mini_button(self, text: str) -> QtWidgets.QPushButton:
        b = QtWidgets.QPushButton(text, self.bar)
        b.setFixedHeight(22)
        b.setCursor(QtCore.Qt.PointingHandCursor)
        b.setStyleSheet(
            "QPushButton{background:#20242B;color:#D6DCE4;border:1px solid #333941;"
            "border-radius:5px;padding:0 8px;font-size:11px;}"
            "QPushButton:hover{background:#2A2F38;}"
        )
        return b

    # ---------- 播放 ----------
    def load_and_play(self, path: str) -> None:
        self.player.stop()
        self.player.setSource(QtCore.QUrl.fromLocalFile(str(path)))
        self._apply_volume()
        self.player.play()

    def toggle_play(self) -> None:
        state = self.player.playbackState()
        if state == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def toggle_mute(self) -> None:
        muted = not bool(_cfg_get(KEY_MUTED, False))
        _cfg_set(KEY_MUTED, muted)
        self._apply_volume()

    def _apply_volume(self) -> None:
        pct = int(_cfg_get(KEY_VOLUME, 70) or 0)
        self.audio.setVolume(max(0.0, min(1.0, pct / 100.0)))
        self.audio.setMuted(bool(_cfg_get(KEY_MUTED, False)))
        self.btn_mute.setText("取消静音" if bool(_cfg_get(KEY_MUTED, False)) else "静音")

    def set_volume(self, pct: int) -> None:
        _cfg_set(KEY_VOLUME, int(pct))
        self._apply_volume()

    def set_muted(self, muted: bool) -> None:
        _cfg_set(KEY_MUTED, bool(muted))
        self._apply_volume()

    def _on_state(self, state) -> None:
        playing = state == QtMultimedia.QMediaPlayer.PlaybackState.PlayingState
        self.btn_play.setText("暂停" if playing else "播放")

    def _on_player_error(self, *_args) -> None:
        msg = self.player.errorString() or "播放器报错"
        self.host.log.warn(f"播放出错：{msg}")
        self.video.setStyleSheet("background:#000;border-radius:9px;")

    def stop(self) -> None:
        try:
            self.player.stop()
            self.player.setSource(QtCore.QUrl())
        except Exception:
            pass

    # ---------- 穿透 / 几何 ----------
    def set_click_through(self, on: bool) -> None:
        self._click_through = bool(on)
        _cfg_set(KEY_CLICK_THROUGH, self._click_through)
        try:
            hwnd = int(self.winId())
            gwl_exstyle = -20
            ws_ex_layered = 0x00080000
            ws_ex_transparent = 0x00000020
            style = ctypes.windll.user32.GetWindowLongW(hwnd, gwl_exstyle)
            if self._click_through:
                style |= (ws_ex_layered | ws_ex_transparent)
            else:
                style &= ~ws_ex_transparent
            ctypes.windll.user32.SetWindowLongW(hwnd, gwl_exstyle, style)
        except Exception:
            self.host.log.warn("设置鼠标穿透失败（非 Windows 或窗口还没建好）")

    @property
    def click_through(self) -> bool:
        return self._click_through

    def apply_geometry(self, geo) -> None:
        try:
            x, y, w, h = [int(v) for v in geo]
        except Exception:
            return
        if w < 200 or h < 120:
            return
        self.setGeometry(x, y, w, h)

    def geometry_list(self) -> list:
        g = self.geometry()
        return [g.x(), g.y(), g.width(), g.height()]

    def _emit_geometry(self) -> None:
        if self.isVisible():
            self.geometryChanged.emit(self.geometry_list())

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._save_timer.start()

    def moveEvent(self, e) -> None:
        super().moveEvent(e)
        self._save_timer.start()

    # ---------- 拖控制条移动窗口 ----------
    def eventFilter(self, obj, ev):
        if obj is self.bar:
            et = ev.type()
            if et == QtCore.QEvent.MouseButtonPress and ev.button() == QtCore.Qt.LeftButton:
                self._drag_from = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            if et == QtCore.QEvent.MouseMove and self._drag_from is not None:
                self.move(ev.globalPosition().toPoint() - self._drag_from)
                return True
            if et == QtCore.QEvent.MouseButtonRelease:
                self._drag_from = None
                return True
        return super().eventFilter(obj, ev)


# ---------------------------------------------------------------------------
# 界面页（模组卡片「⋯」菜单里的「打开界面」，560×420 对话框显示）
# ---------------------------------------------------------------------------
class _Panel(QtWidgets.QWidget):
    def __init__(self, host) -> None:
        super().__init__(None)
        self.host = host
        self.setObjectName("Page")
        self._build()
        self._sync_from_state()

    def _build(self) -> None:
        col = QtWidgets.QVBoxLayout(self)
        col.setContentsMargins(16, 12, 16, 12)
        col.setSpacing(10)

        title = QtWidgets.QLabel("平台视频")
        title.setStyleSheet("font-size:15px;font-weight:600;")
        col.addWidget(title)

        hint = QtWidgets.QLabel(
            "粘贴 B 站 / YouTube 等视频链接，下载后自动转成 MP4，在置顶悬浮窗里播放。\n"
            f"热键 {HOTKEY_TOGGLE} 可随时显隐悬浮窗。\n"
            f"转码要用 ffmpeg：先看 {self.host.paths.data_dir / BIN_DIR}，再找系统 PATH，最后找包内 assets\\bin"
        )
        hint.setStyleSheet("color:#8A939E;font-size:11px;")
        hint.setWordWrap(True)
        col.addWidget(hint)

        row = QtWidgets.QHBoxLayout()
        self.edit_url = QtWidgets.QLineEdit()
        self.edit_url.setPlaceholderText("https://www.bilibili.com/video/BV…")
        self.edit_url.setText(str(_cfg_get(KEY_URL, "") or ""))
        self.btn_go = QtWidgets.QPushButton("下载并播放")
        self.btn_go.clicked.connect(self._on_go)
        row.addWidget(self.edit_url, 1)
        row.addWidget(self.btn_go)
        col.addLayout(row)

        self.bar_progress = QtWidgets.QProgressBar()
        self.bar_progress.setRange(0, 100)
        self.bar_progress.setValue(0)
        self.bar_progress.setTextVisible(True)
        col.addWidget(self.bar_progress)

        self.lab_stage = QtWidgets.QLabel("待命")
        self.lab_stage.setStyleSheet("color:#8A939E;font-size:11px;")
        col.addWidget(self.lab_stage)

        vol_row = QtWidgets.QHBoxLayout()
        vol_row.addWidget(QtWidgets.QLabel("音量"))
        self.slider_vol = QtWidgets.QSlider(QtCore.Qt.Horizontal)
        self.slider_vol.setRange(0, 100)
        self.slider_vol.setValue(int(_cfg_get(KEY_VOLUME, 70) or 0))
        self.slider_vol.valueChanged.connect(self._on_volume)
        vol_row.addWidget(self.slider_vol, 1)
        self.chk_mute = QtWidgets.QCheckBox("静音")
        self.chk_mute.setChecked(bool(_cfg_get(KEY_MUTED, False)))
        self.chk_mute.toggled.connect(self._on_mute)
        vol_row.addWidget(self.chk_mute)
        col.addLayout(vol_row)

        self.chk_through = QtWidgets.QCheckBox("鼠标穿透（点画面不挡游戏操作）")
        self.chk_through.setChecked(bool(_cfg_get(KEY_CLICK_THROUGH, False)))
        self.chk_through.toggled.connect(self._on_through)
        col.addWidget(self.chk_through)

        btn_row = QtWidgets.QHBoxLayout()
        self.btn_show = QtWidgets.QPushButton("显示 / 隐藏悬浮窗")
        self.btn_show.clicked.connect(self._on_show)
        self.btn_reset = QtWidgets.QPushButton("重置位置与大小")
        self.btn_reset.clicked.connect(self._on_reset)
        btn_row.addWidget(self.btn_show)
        btn_row.addWidget(self.btn_reset)
        btn_row.addStretch(1)
        col.addLayout(btn_row)

        col.addStretch(1)

    # ---------- 状态同步 ----------
    def _sync_from_state(self) -> None:
        ov = _CTX.get("overlay")
        enabled = bool(_CTX.get("enabled")) and ov is not None
        for w in (self.btn_go, self.btn_show, self.btn_reset, self.slider_vol, self.chk_mute):
            w.setEnabled(enabled)
        if not enabled:
            self.lab_stage.setText("模组未启用：先在模组卡片上点「启用」")

    # ---------- 槽 ----------
    def _on_go(self) -> None:
        host = self.host
        url = self.edit_url.text().strip()
        if not url:
            host.notify("平台视频", "先粘一个视频链接进来", "warn")
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            host.notify("平台视频", "这不像一个链接，要以 http(s):// 开头", "warn")
            return

        old = _CTX.get("job")
        if old is not None and old.is_alive():
            host.notify("平台视频", "上一个还在下，先等它下完", "warn")
            return

        _cfg_set(KEY_URL, url)
        job = _Job(host, url)
        _CTX["job"] = job
        job.bridge.progress.connect(self._on_progress)
        job.bridge.stage.connect(self.lab_stage.setText)
        job.bridge.done.connect(self._on_done)
        job.bridge.failed.connect(self._on_failed)

        self.bar_progress.setValue(0)
        self.btn_go.setEnabled(False)
        self.lab_stage.setText("开始下载…")
        job.start()

    def _on_progress(self, pct: int, text: str) -> None:
        if pct < 0:
            self.bar_progress.setRange(0, 0)     # 不确定进度：转码阶段
        else:
            self.bar_progress.setRange(0, 100)
            self.bar_progress.setValue(pct)
        if text:
            self.lab_stage.setText(text)

    def _on_done(self, path: str) -> None:
        self.bar_progress.setRange(0, 100)
        self.bar_progress.setValue(100)
        self.btn_go.setEnabled(True)
        ov = _CTX.get("overlay")
        if ov is None:
            self.lab_stage.setText("下载完成，但悬浮窗没开（先启用模组）")
            return
        self.lab_stage.setText("开始播放")
        ov.load_and_play(path)
        self.host.notify("平台视频", "攻略视频已就绪", "info")
        try:
            self.host.events.emit("platform_video.state", state="playing", path=path)
        except Exception:
            pass

    def _on_failed(self, detail: str) -> None:
        self.bar_progress.setRange(0, 100)
        self.bar_progress.setValue(0)
        self.btn_go.setEnabled(True)
        self.lab_stage.setText("失败：" + detail[:80])
        self.host.notify("平台视频", "下载/转码失败：" + detail[:120], "error")
        try:
            self.host.events.emit("platform_video.state", state="failed", reason=detail[:200])
        except Exception:
            pass

    def _on_volume(self, v: int) -> None:
        ov = _CTX.get("overlay")
        _cfg_set(KEY_VOLUME, int(v))
        if ov is not None:
            ov.set_volume(v)

    def _on_mute(self, on: bool) -> None:
        ov = _CTX.get("overlay")
        _cfg_set(KEY_MUTED, bool(on))
        if ov is not None:
            ov.set_muted(on)

    def _on_through(self, on: bool) -> None:
        ov = _CTX.get("overlay")
        if ov is None:
            return
        ov.set_click_through(on)

    def _on_show(self) -> None:
        ov = _CTX.get("overlay")
        if ov is None:
            return
        if ov.isVisible():
            ov.hide()
        else:
            ov.show()
            ov.raise_()

    def _on_reset(self) -> None:
        ov = _CTX.get("overlay")
        if ov is None:
            return
        screen = QtGui.QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        w, h = DEFAULT_SIZE
        ov.setGeometry(area.right() - w - 24, area.top() + 24, w, h)


def build_panel():
    """宿主点「打开界面：platform_video」时调用，返回一个 QWidget。"""
    host = _CTX["host"]
    if host is None:
        return QtWidgets.QLabel("模组还没加载完成")
    panel = _Panel(host)
    _CTX["panel"] = panel
    return panel


# ---------------------------------------------------------------------------
# 热键回调
# ---------------------------------------------------------------------------
def _toggle_overlay() -> None:
    ov = _CTX.get("overlay")
    if ov is None:
        return
    if ov.isVisible():
        ov.hide()
    else:
        ov.show()
        ov.raise_()


# ---------------------------------------------------------------------------
# 四个钩子
# ---------------------------------------------------------------------------
def on_load(host):
    """只登记：界面页 + 热键。"""
    _CTX["host"] = host
    host.log.info(f"平台视频模组已加载，宿主版本 {getattr(host, 'app_version', '')}")
    _mount_pylibs()

    try:
        host.ui.register_page("platform_video", build_panel)
    except Exception:
        host.log.error("登记界面页失败", exc=True)

    try:
        host.hotkey.register(HOTKEY_TOGGLE, _toggle_overlay)
    except Exception:
        host.log.error("注册热键失败", exc=True)


def on_enable():
    """起业务：建悬浮窗、恢复位置音量、提示。"""
    host = _CTX["host"]
    if host is None:
        return
    _CTX["enabled"] = True

    try:
        ov = _Overlay(host)
        _CTX["overlay"] = ov
        geo = _cfg_get(KEY_GEOMETRY, None)
        if isinstance(geo, (list, tuple)) and len(geo) == 4:
            ov.apply_geometry(geo)
        else:
            screen = QtGui.QGuiApplication.primaryScreen()
            area = screen.availableGeometry()
            w, h = DEFAULT_SIZE
            ov.setGeometry(area.right() - w - 24, area.top() + 24, w, h)

        ov.geometryChanged.connect(lambda g: _cfg_set(KEY_GEOMETRY, g))
        ov.show()
        host.notify("平台视频", f"悬浮窗已就绪，热键 {HOTKEY_TOGGLE} 显隐", "info")
    except Exception:
        _CTX["overlay"] = None
        host.log.error("悬浮窗起不来", exc=True)
        host.notify("平台视频", "悬浮窗创建失败，详见 logs\\mods.log", "error")

    try:
        host.events.emit("platform_video.state", state="enabled")
    except Exception:
        pass

    panel = _CTX.get("panel")
    if panel is not None:
        try:
            panel._sync_from_state()
        except Exception:
            pass


def on_disable():
    """收干净：停任务 → 关播放器 → 关窗 → 清 temp。"""
    host = _CTX["host"]
    _CTX["enabled"] = False

    job = _CTX.get("job")
    _CTX["job"] = None
    if job is not None:
        try:
            job.cancel()
            if job.is_alive():
                job.join(timeout=3)
        except Exception:
            if host is not None:
                host.log.error("停止下载线程出错", exc=True)

    ov = _CTX.get("overlay")
    _CTX["overlay"] = None
    if ov is not None:
        try:
            ov.stop()
            ov.hide()
            ov.close()
            ov.deleteLater()
        except Exception:
            if host is not None:
                host.log.error("关闭悬浮窗出错", exc=True)

    if host is not None:
        try:
            shutil.rmtree(host.paths.data_dir / TEMP_DIR, ignore_errors=True)
        except Exception:
            pass
        try:
            host.events.emit("platform_video.state", state="disabled")
        except Exception:
            pass
        host.log.info("平台视频已停用，缓存已清")

    panel = _CTX.get("panel")
    if panel is not None:
        try:
            panel._sync_from_state()
        except Exception:
            pass


def on_unload():
    """卸载：再停一次，并把复制的 ffmpeg 一起删掉（不留缓存目录）。"""
    on_disable()
    host = _CTX["host"]
    if host is None:
        return
    try:
        shutil.rmtree(host.paths.data_dir / BIN_DIR, ignore_errors=True)
        shutil.rmtree(host.paths.data_dir / TEMP_DIR, ignore_errors=True)
    except Exception:
        host.log.error("清理缓存目录出错", exc=True)
    _unmount_pylibs()
    host.log.info("平台视频模组已卸载")
