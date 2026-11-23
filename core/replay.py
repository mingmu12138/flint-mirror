"""最近 N 分钟回放：ffmpeg 分段缓冲 + 按键合并成片。

思路：
  - 常驻一个 ffmpeg 进程用 gdigrab 录桌面，按 10 秒切成小段写进 回放缓冲/
  - 后台清理线程只留最近 11~12 分钟，磁盘不会暴涨
  - 保存时把"已经写完的段"用 concat 无损拼接（正在写的最新一段跳过，最多丢 10 秒）

为什么不用 Qt：QMediaRecorder 只能从头写到尾，无法只保留最后一段时间。
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

from .capture import VIDEO_DIR, day_dir, video_path
from .store import app_dir

BUF_DIR_NAME = "回放缓冲"
SEG_SECONDS = 10          # 每段时长
KEEP_SECONDS = 720        # 缓冲保留 12 分钟（比 10 分钟多一点，保证够取）
CREATE_NO_WINDOW = 0x08000000


def ffmpeg_path() -> Optional[Path]:
    for cand in (
        app_dir() / "bundled" / "ffmpeg" / "ffmpeg.exe",
        app_dir() / "ffmpeg.exe",
    ):
        if cand.exists():
            return cand
    return None


class ReplayBuffer:
    """分段缓冲控制器。"""

    def __init__(self, max_bytes: int = 0, buf_root: Optional[Path] = None) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._buf: Optional[Path] = None
        # 体积上限（0 = 不限，只按时间清）；缓存根目录（None = 程序目录）
        self.max_bytes = int(max_bytes)
        self._root: Optional[Path] = buf_root
        self._stop_flag = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._audio = None
        self._audio_path: Optional[Path] = None
        self.error_text = ""

    # ------------------------------------------------------------ 状态
    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def buffer_dir(self) -> Optional[Path]:
        return self._buf

    def segments(self) -> List[Path]:
        if self._buf is None or not self._buf.exists():
            return []
        return sorted(self._buf.glob("seg_*.mp4"), key=lambda p: p.name)

    def buffered_seconds(self) -> int:
        segs = self.segments()
        # 最后一段还在写，不计入
        return max(0, len(segs) - 1) * SEG_SECONDS

    # ------------------------------------------------------------ 开始
    def configure(self, max_gb: int = 5, root: Optional[Path] = None) -> None:
        """运行前设置上限和缓存盘（跑着的时候改不动，下次开启生效）。"""
        try:
            self.max_bytes = max(0, int(max_gb)) * 1024 ** 3
        except (TypeError, ValueError):
            self.max_bytes = 5 * 1024 ** 3
        self._root = root

    def buffer_size(self) -> int:
        """当前缓冲占了多少字节。"""
        buf = self._buf
        if buf is None or not buf.exists():
            return 0
        total = 0
        for p in buf.glob("*.mp4"):
            try:
                total += p.stat().st_size
            except OSError:
                pass
        return total

    def start(self) -> Tuple[bool, str]:
        if self.is_running:
            return False, "缓冲已经在跑"
        exe = ffmpeg_path()
        if exe is None:
            return False, "没找到 ffmpeg.exe，回放功能不可用"

        buf = (self._root or app_dir()) / BUF_DIR_NAME
        try:
            buf.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return False, f"缓存盘不可写：{exc}"
        shutil.rmtree(buf, ignore_errors=True)
        buf.mkdir(parents=True, exist_ok=True)
        self._buf = buf

        cmd = [
            str(exe), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "gdigrab", "-framerate", "30", "-i", "desktop",
            "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
            "-pix_fmt", "yuv420p", "-b:v", "8M", "-g", "60",
            "-f", "segment", "-segment_time", str(SEG_SECONDS),
            "-reset_timestamps", "1", "-segment_format", "mp4",
            str(buf / "seg_%05d.mp4"),
        ]
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as exc:  # noqa: BLE001
            self.error_text = str(exc)
            self._proc = None
            return False, f"启动 ffmpeg 失败：{exc}"

        self._stop_flag.clear()
        self._thread = threading.Thread(target=self._clean_loop, daemon=True)
        self._thread.start()

        # 声音也一起留（拿不到扬声器就只留画面）
        from . import audio as _audio

        self._audio_path = buf / "audio.wav"
        self._audio = _audio.LoopbackRecorder()
        if not self._audio.start(self._audio_path):
            self._audio = None
            self._audio_path = None

        return True, str(buf)

    # ------------------------------------------------------------ 停止
    def stop(self) -> None:
        self._stop_flag.set()
        if self._audio is not None:
            self._audio.stop()
            self._audio = None
        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
        self._proc = None

    # ------------------------------------------------------------ 清理
    def _clean_loop(self) -> None:
        # 两条线：时间上留够 11 分钟（保证能取 10 分钟）；体积上不超过上限
        keep_segments = max(3, KEEP_SECONDS // SEG_SECONDS)
        while not self._stop_flag.wait(6):
            try:
                segs = self.segments()
                if len(segs) > keep_segments + 2:
                    for seg in segs[: len(segs) - keep_segments]:
                        try:
                            seg.unlink()
                        except OSError:
                            pass
                    segs = self.segments()

                if self.max_bytes > 0:
                    sizes = []
                    total = 0
                    for seg in segs:
                        try:
                            n = seg.stat().st_size
                        except OSError:
                            n = 0
                        sizes.append((seg, n))
                        total += n
                    # 删最旧的，但至少留够 11 分钟，宁可不删也别把有用的删了
                    while total > self.max_bytes and len(sizes) > keep_segments:
                        seg, n = sizes.pop(0)
                        try:
                            seg.unlink()
                            total -= n
                        except OSError:
                            pass
            except Exception:
                pass

    # ------------------------------------------------------------ 保存
    def save(self, minutes: int = 10) -> Tuple[bool, str]:
        """把最近 minutes 分钟拼成一个 mp4，落到 素材/录像/日期。"""
        exe = ffmpeg_path()
        if exe is None:
            return False, "没找到 ffmpeg.exe"
        if self._buf is None or not self._buf.exists():
            return False, "缓冲还没开始"

        segs = self.segments()
        usable = segs[:-1] if len(segs) > 1 else []
        if not usable:
            return False, "缓冲里还没有完整的片段，再等十几秒"

        want = max(1, int((minutes * 60) // SEG_SECONDS))
        usable = usable[-want:]

        target = video_path(f"回放{minutes}分钟")
        list_file = self._buf / "concat.txt"
        list_file.write_text(
            "".join(f"file '{seg.as_posix()}'\n" for seg in usable),
            encoding="utf-8",
        )

        cmd = [
            str(exe), "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-c", "copy", str(target),
        ]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=180,
            )
        except Exception as exc:  # noqa: BLE001
            return False, f"合并失败：{exc}"
        if proc.returncode != 0 or not target.exists():
            msg = (proc.stderr or b"").decode("utf-8", "ignore")[-160:]
            return False, f"合并失败：{msg or '未知错误'}"

        # 把这段时间的系统声音并进去
        if self._audio is not None and self._audio_path is not None:
            video_len = len(usable) * SEG_SECONDS
            audio_len = self._audio.duration()
            offset = max(0.0, audio_len - video_len)
            from . import audio as _audio

            _audio.mux(target, self._audio_path, start_offset=offset)

        return True, str(target)


def clear_buffer() -> None:
    shutil.rmtree(app_dir() / BUF_DIR_NAME, ignore_errors=True)
