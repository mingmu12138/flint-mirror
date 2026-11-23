"""系统声音录制（WASAPI 回环）：录的是"扬声器在放什么"，不需要开立体声混音。

不依赖 Qt，直接用 soundcard 抓默认扬声器的 loopback，写 16bit wav；
停止后再用 ffmpeg 把音轨并进 mp4。
"""

from __future__ import annotations

import os
import threading
import wave
from pathlib import Path
from typing import Optional, Tuple

import numpy as np
import soundcard as sc

from .replay import ffmpeg_path

SAMPLE_RATE = 48000
CHANNELS = 2
BLOCK = 4800          # 0.1 秒一块
ROLL_SECONDS = 900    # 单个文件最长 15 分钟，超了就从头重开，避免无限变大


class LoopbackRecorder:
    """后台线程持续录扬声器输出。"""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._path: Optional[Path] = None
        self._frames = 0
        self.error_text = ""

    # ------------------------------------------------------------ 状态
    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def path(self) -> Optional[Path]:
        return self._path

    def duration(self) -> float:
        return self._frames / SAMPLE_RATE

    @staticmethod
    def available() -> bool:
        try:
            return sc.default_speaker() is not None
        except Exception:
            return False

    # ------------------------------------------------------------ 开始
    def start(self, path: Path) -> bool:
        if self.is_running:
            return False
        try:
            speaker = sc.default_speaker()
            mic = sc.get_microphone(id=str(speaker.name), include_loopback=True)
        except Exception as exc:  # noqa: BLE001
            self.error_text = f"没有可录的扬声器：{exc}"
            return False

        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._frames = 0
        self.error_text = ""
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(mic,), daemon=True)
        self._thread.start()
        return True

    # ------------------------------------------------------------ 循环
    def _loop(self, mic) -> None:
        wf: Optional[wave.Wave_write] = None
        try:
            with mic.recorder(samplerate=SAMPLE_RATE, channels=CHANNELS, blocksize=BLOCK) as rec:
                while not self._stop.is_set():
                    data = rec.record(numframes=BLOCK)
                    if data is None or len(data) == 0:
                        continue
                    pcm = (np.clip(data, -1.0, 1.0) * 32767).astype(np.int16)
                    if wf is None:
                        wf = self._open_wav()
                    wf.writeframes(pcm.tobytes())
                    self._frames += len(pcm)

                    # 太长就重开，丢掉前面的
                    if self._frames >= ROLL_SECONDS * SAMPLE_RATE:
                        try:
                            wf.close()
                        except Exception:
                            pass
                        self._frames = 0
                        wf = self._open_wav()
        except Exception as exc:  # noqa: BLE001
            self.error_text = str(exc)
        finally:
            try:
                if wf is not None:
                    wf.close()
            except Exception:
                pass

    def _open_wav(self) -> wave.Wave_write:
        wf = wave.open(str(self._path), "wb")
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        return wf

    # ------------------------------------------------------------ 停止
    def stop(self, timeout: float = 2.0) -> Optional[Path]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        path = self._path
        if path is not None and (not path.exists() or path.stat().st_size < 1024):
            return None
        return path


def mux(video: Path, audio: Path, start_offset: float = 0.0) -> Tuple[bool, str]:
    """把 wav 音轨并进 mp4（视频不重编码），成功后替换原文件。"""
    exe = ffmpeg_path()
    if exe is None:
        return False, "没找到 ffmpeg.exe"
    if not Path(video).exists():
        return False, "视频文件不存在"
    if Path(video).stat().st_size < 1024:
        return False, "视频文件是空的（录制没成功）"
    if not Path(audio).exists():
        return False, "音频文件不存在"

    tmp = Path(video).with_name(Path(video).stem + "_av.mp4")
    cmd = [
        str(exe), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video),
        "-ss", f"{max(0.0, start_offset):.2f}", "-i", str(audio),
        "-map", "0:v", "-map", "1:a",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        str(tmp),
    ]
    try:
        proc = subprocess_run(cmd)
    except Exception as exc:  # noqa: BLE001
        return False, f"合成失败：{exc}"
    if proc != 0 or not tmp.exists() or tmp.stat().st_size < 1024:
        try:
            tmp.unlink()
        except OSError:
            pass
        return False, "合成失败：ffmpeg 没产出有效文件"
    try:
        os.replace(tmp, video)
    except Exception as exc:  # noqa: BLE001
        return False, f"替换文件失败：{exc}"
    return True, str(video)


def subprocess_run(cmd) -> int:
    import subprocess

    proc = subprocess.run(cmd, capture_output=True, timeout=600,
                          creationflags=0x08000000)
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "ignore")[-200:]
        if err:
            print("ffmpeg:", err)
    return proc.returncode
