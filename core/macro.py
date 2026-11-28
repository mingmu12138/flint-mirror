# -*- coding: utf-8 -*-
"""键鼠宏：录一遍、然后让它自己跳。

定位是「外部模拟」——录音机在系统层面轮询你按了什么，回放时用 SendInput 再按一遍。
**不进游戏进程、不读写游戏内存、不改游戏文件**，所以它就是"一个人坐在电脑前一直按"，
跟你自己按键没有区别。反过来也别指望它躲反作弊：公共服一样按人肉频率算。

用途对准重复劳动：挂机钓鱼（右键循环）、自动挥剑练经验（左键连点）、农作物收割（走+砍）。
"""

from __future__ import annotations

import base64
import json
import threading
import time
import zlib
from pathlib import Path
from typing import List, Optional, Tuple

from core import input_send as ins
from core.store import app_dir

MACRO_DIR = "宏"

# 录哪些键：字母、数字、F1–F12、方向键、空格 / 回车 / Tab / Esc / 退格、Shift/Ctrl/Alt、鼠标三键
_MOUSE_VKS = (0x01, 0x02, 0x04)
RECORD_KEYS: Tuple[int, ...] = (
    tuple(range(0x41, 0x5B))          # A-Z
    + tuple(range(0x30, 0x3A))        # 0-9
    + tuple(v for v in range(0x70, 0x7C) if v != 0x7B)   # F1-F11（F12 是急停键，不录）
    + (0x25, 0x26, 0x27, 0x28)        # 方向
    + (0x20, 0x0D, 0x09, 0x1B, 0x08)  # 空格 回车 Tab Esc 退格
    + (0x10, 0x11, 0x12)              # Shift Ctrl Alt
    + _MOUSE_VKS                      # 左 右 中键
)

STOP_VK = 0x7B      # F12：录/放都能用它停
MOUSE_NAME = {0x01: "left", 0x02: "right", 0x04: "middle"}

Event = List  # [t_ms, "key"|"mouse", vk, down]


def macro_dir() -> Path:
    d = app_dir() / MACRO_DIR
    try:
        d.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return d


def list_macros() -> List[str]:
    d = macro_dir()
    try:
        return sorted(p.stem for p in d.glob("*.json"))
    except OSError:
        return []


def save_macro(name: str, events: List[Event]) -> Tuple[bool, str]:
    name = (name or "").strip()
    if not name:
        return False, "先给宏起个名字"
    if not events:
        return False, "这条宏里什么都没有，先录一段"
    bad = set('\\/:*?"<>|')
    if any(ch in bad for ch in name):
        return False, "名字里不能有 \\ / : * ? \" < > |"
    path = macro_dir() / f"{name}.json"
    data = {
        "name": name,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "duration_ms": int(events[-1][0]) if events else 0,
        "count": len(events),
        "events": events,
    }
    try:
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return True, f"已保存 {name}（{len(events)} 个动作）"
    except OSError as exc:
        return False, "写文件失败：" + str(exc)


def load_macro(name: str) -> Optional[dict]:
    path = macro_dir() / f"{name}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def delete_macro(name: str) -> bool:
    path = macro_dir() / f"{name}.json"
    try:
        if path.exists():
            path.unlink()
            return True
    except OSError:
        return False
    return False


# ---------------------------------------------------------------- 分享码
# 跟滤镜的 F1- 码一个思路：压成一段能复制粘贴的文字，对方粘进去就还原。
# 宏是一串事件，比滤镜参数大得多，所以走「紧凑 json → zlib → base64url」。
# 码里带一位校验，抄漏一个字符会直接判失败，不会套一条半截宏上去。

CODE_PREFIX = "M1"
_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"
_MAX_CODE = 200000          # 超过这个长度就不认（防手滑粘进一整篇文档）
_MAX_RAW = 8 * 1024 * 1024  # 解压后上限，防压缩炸弹


def _check(body: str) -> str:
    return _B36[sum(body.encode("ascii", "ignore")) % 36]


def _clean(code: str) -> str:
    return "".join(ch for ch in str(code or "") if not ch.isspace())


def code_looks(code: str) -> bool:
    """粗看像不像一个宏分享码（给"粘了就直接导入"用）。"""
    text = _clean(code)
    return text.startswith(CODE_PREFIX + ".") and text.count(".") >= 2


def code_encode(events: List[Event]) -> str:
    """事件列表 → 分享码。空的或全是坏事件就返回空串。"""
    packed = []
    for ev in events or []:
        try:
            t, kind, vk, down = int(ev[0]), ev[1], int(ev[2]), bool(ev[3])
        except (IndexError, TypeError, ValueError):
            continue
        if t < 0 or vk < 0 or vk > 255:
            continue
        packed.append([t, 1 if kind == "key" else 2, vk, 1 if down else 0])
    if not packed:
        return ""
    raw = json.dumps(packed, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    body = base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode("ascii").rstrip("=")
    return CODE_PREFIX + "." + body + "." + _check(body)


def code_decode(code: str) -> Optional[List[Event]]:
    """分享码 → 事件列表。认不出来一律 None，不去猜。"""
    text = _clean(code)
    if not text or len(text) > _MAX_CODE or not text.startswith(CODE_PREFIX + "."):
        return None
    parts = text.split(".")
    if len(parts) != 3:
        return None
    _p, body, check = parts
    if not body or _check(body) != check:
        return None
    try:
        comp = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        d = zlib.decompressobj()
        raw = d.decompress(comp, _MAX_RAW + 1)
        if len(raw) > _MAX_RAW or d.unconsumed_tail:
            return None
        packed = json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(packed, list) or not packed:
        return None
    events: List[Event] = []
    for item in packed:
        if not isinstance(item, list) or len(item) != 4:
            return None
        try:
            t, kind, vk, down = int(item[0]), int(item[1]), int(item[2]), int(item[3])
        except (TypeError, ValueError):
            return None
        if t < 0 or vk < 0 or vk > 255 or kind not in (1, 2) or down not in (0, 1):
            return None
        events.append([t, "key" if kind == 1 else "mouse", vk, bool(down)])
    return events


class Recorder:
    """轮询版录音机：每 10ms 看一遍那一小撮键有没有变化。"""

    def __init__(self) -> None:
        self.events: List[Event] = []
        self._prev: dict = {}
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.status = "idle"

    def start(self) -> None:
        self.events = []
        self._prev = {vk: False for vk in RECORD_KEYS}
        self._stop.clear()
        self.status = "recording"
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> int:
        self._stop.set()
        self.status = "stopped"
        return len(self.events)

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run(self) -> None:
        t0 = time.perf_counter()
        while not self._stop.is_set():
            now = int((time.perf_counter() - t0) * 1000)
            for vk in RECORD_KEYS:
                down = ins.is_key_down(vk)
                if down != self._prev.get(vk):
                    self._prev[vk] = down
                    kind = "mouse" if vk in _MOUSE_VKS else "key"
                    self.events.append([now, kind, vk, down])
            if ins.is_key_down(STOP_VK):
                self.status = "stopped"
                break
            time.sleep(0.01)
        # 收尾一：还按着没松的键补一个抬起，否则回放会一直卡在「按住」
        now = int((time.perf_counter() - t0) * 1000)
        for vk, down in list(self._prev.items()):
            if down:
                kind = "mouse" if vk in _MOUSE_VKS else "key"
                self.events.append([now, kind, vk, False])
                self._prev[vk] = False
        self._trim_tail()

    def _trim_tail(self) -> None:
        """把末尾 120ms 里的「鼠标」事件丢掉：那多半是用户去点「停止」按钮的那一下。

        键盘事件一律保留 —— 顺手把刚松开的键删了，回放就会一直按住不放。
        """
        if not self.events:
            return
        last = self.events[-1][0]
        self.events = [e for e in self.events
                       if not (e[0] > last - 120 and e[1] == "mouse")]


class Player:
    """回放：按录制时的节奏重放，支持倍速、循环、F12/切窗急停。"""

    def __init__(self, events: List[Event], loops: int = 1, speed: float = 1.0,
                 require_game: bool = True) -> None:
        self.events = list(events or [])
        self.loops = max(1, int(loops))
        self.speed = max(0.2, float(speed))
        self.require_game = require_game
        self.round = 0
        self.status = "idle"
        self.msg = ""
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._away_since: Optional[float] = None

    def start(self) -> None:
        if not self.events:
            self.status = "error"
            self.msg = "这条宏是空的"
            return
        self._stop.clear()
        self.status = "playing"
        self.round = 0
        self.msg = ""
        self._away_since = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, reason: str = "手动停止") -> None:
        self.msg = reason
        self._stop.set()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ---------------------------------------------------------------- 内部
    def _run(self) -> None:
        try:
            self._loop()
        except Exception as exc:  # noqa: BLE001
            # 宏文件被手改坏了也别让线程静默死掉，界面上要说清楚
            self.status = "error"
            self.msg = "宏数据坏了：" + str(exc)[:60]

    def _loop(self) -> None:
        first = float(self.events[0][0])
        for i in range(self.loops):
            if self._stop.is_set():
                break
            self.round = i + 1
            base = time.perf_counter()
            for ev in self.events:
                if self._stop.is_set():
                    break
                if ins.is_key_down(STOP_VK):
                    self.msg = "你按了 F12，停了"
                    self._stop.set()
                    break
                if not self._gate():
                    break
                target = base + ((float(ev[0]) - first) / 1000.0) / self.speed
                while True:
                    remain = target - time.perf_counter()
                    if remain <= 0 or self._stop.is_set():
                        break
                    time.sleep(min(0.01, remain))
                if self._stop.is_set():
                    break
                self._inject(ev)
        self.status = "stopped" if self._stop.is_set() else "done"
        if self.status == "done":
            self.msg = f"跑完了（{self.loops} 轮）"

    def _gate(self) -> bool:
        """要求游戏在前台才动手；切走得超过 15 秒就停下，免得后台乱按。"""
        if not self.require_game:
            return True
        if ins.is_game_window(ins.foreground_hwnd()):
            self._away_since = None
            return True
        now = time.perf_counter()
        if self._away_since is None:
            self._away_since = now
        elif now - self._away_since > 15:
            self.msg = "游戏不在前台超过 15 秒，停了"
            self._stop.set()
            return False
        time.sleep(0.2)
        return not self._stop.is_set()

    @staticmethod
    def _inject(ev: Event) -> None:
        try:
            t, kind, code, down = ev[0], ev[1], int(ev[2]), bool(ev[3])
        except (IndexError, TypeError, ValueError):
            return
        if kind == "mouse":
            name = MOUSE_NAME.get(code)
            if name:
                ins.mouse_event(name, down)
        else:
            ins.key_event(code, down)


def describe(events: List[Event]) -> str:
    """一句话概括这条宏大概在干嘛（界面上显示用）。"""
    if not events:
        return "空宏"
    dur = float(events[-1][0]) / 1000.0
    keys = [e for e in events if e[1] == "key"]
    mice = [e for e in events if e[1] == "mouse"]
    parts = [f"{dur:.1f} 秒 · {len(events)} 个动作"]
    if mice:
        lefts = sum(1 for e in mice if int(e[2]) == 0x01 and e[3])
        rights = sum(1 for e in mice if int(e[2]) == 0x02 and e[3])
        if lefts or rights:
            parts.append(f"点击 {lefts + rights} 次")
    if keys:
        parts.append(f"按键 {len(keys)} 次")
    return "，".join(parts)
