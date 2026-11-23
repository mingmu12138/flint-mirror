"""录屏：Qt 屏幕采集 + H.264 编码，同时录系统声音，落盘到 素材\\录像\\日期。

声音走 WASAPI 回环（soundcard），停止后用 ffmpeg 把音轨并进 mp4（视频不重编码）。
拿不到扬声器时自动只录画面。
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional, Tuple

from PySide6 import QtCore, QtGui, QtMultimedia

from . import audio
from .capture import video_path

MPEG4 = QtMultimedia.QMediaFormat.FileFormat.MPEG4
H264 = QtMultimedia.QMediaFormat.VideoCodec.H264


class ScreenRecorder(QtCore.QObject):
    """一次录一段，start() 开始、stop() 结束；画面 + 系统声音。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._capture = None
        self._session = None
        self._recorder = None
        self._path: Optional[Path] = None
        self._audio: Optional[audio.LoopbackRecorder] = None
        self._audio_path: Optional[Path] = None
        self.last_path: Optional[Path] = None
        self.error_text = ""
        self._started_at = 0.0

    # ------------------------------------------------------------ 状态
    @property
    def is_recording(self) -> bool:
        if self._recorder is None:
            return False
        state = self._recorder.recorderState()
        return state == QtMultimedia.QMediaRecorder.RecorderState.RecordingState

    @property
    def elapsed(self) -> float:
        return time.time() - self._started_at if self.is_recording else 0.0

    # ------------------------------------------------------------ 开始
    def start(self) -> Tuple[bool, str]:
        if self.is_recording:
            return False, "已经在录了"

        path = video_path()
        screen = QtGui.QGuiApplication.screenAt(QtGui.QCursor.pos())
        if screen is None:
            screen = QtGui.QGuiApplication.primaryScreen()

        try:
            capture = QtMultimedia.QScreenCapture(self)
            capture.setScreen(screen)

            session = QtMultimedia.QMediaCaptureSession(self)
            session.setScreenCapture(capture)

            recorder = QtMultimedia.QMediaRecorder(self)
            session.setRecorder(recorder)

            fmt = QtMultimedia.QMediaFormat()
            fmt.setFileFormat(MPEG4)
            fmt.setVideoCodec(H264)
            recorder.setMediaFormat(fmt)
            recorder.setVideoFrameRate(30)
            recorder.setVideoBitRate(8_000_000)
            recorder.setOutputLocation(QtCore.QUrl.fromLocalFile(str(path)))

            self._capture, self._session, self._recorder, self._path = (
                capture,
                session,
                recorder,
                path,
            )
            capture.start()
            recorder.record()
            self._started_at = time.time()

            if recorder.error() != QtMultimedia.QMediaRecorder.Error.NoError:
                self.error_text = recorder.errorString()
                return False, f"录制器报错：{self.error_text}"

            # 同步录系统声音，拿不到扬声器就只留画面
            self._audio_path = path.with_name(path.stem + "_audio.wav")
            self._audio = audio.LoopbackRecorder()
            if not self._audio.start(self._audio_path):
                self._audio = None
                self._audio_path = None

            return True, str(path)
        except Exception as exc:  # noqa: BLE001
            self.error_text = str(exc)
            self._cleanup()
            return False, f"启动录制失败：{exc}"

    # ------------------------------------------------------------ 停止
    def stop(self) -> Optional[Path]:
        if self._recorder is None:
            return None

        path = self._path
        try:
            self._recorder.stop()
        except Exception:
            pass
        try:
            if self._capture is not None:
                self._capture.stop()
        except Exception:
            pass

        time.sleep(0.3)  # 等 Qt 把 mp4 收尾写完

        # 停声音，再把音轨并进去
        audio_path = None
        if self._audio is not None:
            audio_path = self._audio.stop()
            self._audio = None
        self._audio_path = None

        if path is not None and Path(path).exists() and Path(path).stat().st_size > 1024:
            if audio_path is not None and Path(audio_path).exists():
                ok, msg = audio.mux(path, Path(audio_path))
                # 合成了就删临时音轨；合不进去也删——那段 wav 单独放着谁也打不开
                try:
                    Path(audio_path).unlink()
                except OSError:
                    pass
                if not ok:
                    log.warning("音轨合并失败（%s），已清掉临时 wav", msg)
            self.last_path = path
        else:
            self.error_text = "录制没拿到画面，文件是空的"
            path = None
            if audio_path is not None and Path(audio_path).exists():
                try:
                    Path(audio_path).unlink()
                except OSError:
                    pass

        self._path = None
        self._recorder = None
        self._session = None
        self._capture = None
        return path

    def _cleanup(self) -> None:
        for obj in (self._capture, self._session, self._recorder):
            try:
                if obj is not None:
                    obj.deleteLater()
            except Exception:
                pass
        self._capture = self._session = self._recorder = None
