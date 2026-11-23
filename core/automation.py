"""自动化：动作执行 + 进程监视。

设计成纯逻辑，不依赖 Qt，方便自检脚本直接跑。
"""

from __future__ import annotations

import re
import time
from typing import List, Optional, Set, Tuple

import psutil

from core import display
from core.store import (
    ACTION_ACE_LIMIT,
    ACTION_ACE_RESTORE,
    ACTION_CACHE_CLEAN,
    ACTION_FPS_HIDE,
    ACTION_FPS_SHOW,
    ACTION_HUD_HIDE,
    ACTION_HUD_SHOW,
    ACTION_MOD_START,
    ACTION_MOD_STOP,
    ACTION_RECORD_START,
    ACTION_RECORD_STOP,
    ACTION_REPLAY_SAVE,
    ACTION_REPLAY_START,
    ACTION_REPLAY_STOP,
    ACTION_RESOLUTION,
    ACTION_RESTORE,
    ACTION_SHOT,
    ACTION_WAIT,
    Action,
    Config,
    ProcessGuard,
)

# 这些动作是"面板上的开关"，逻辑活在 GUI 里（要弹 toast、要动悬浮窗），
# 所以统一交给 ui.run_gui_action(action) 执行，本模块只做转交和文案。
GUI_ACTIONS = {
    ACTION_ACE_LIMIT,
    ACTION_ACE_RESTORE,
    ACTION_FPS_SHOW,
    ACTION_FPS_HIDE,
    ACTION_HUD_SHOW,
    ACTION_HUD_HIDE,
    ACTION_REPLAY_START,
    ACTION_REPLAY_STOP,
    ACTION_REPLAY_SAVE,
    ACTION_RECORD_START,
    ACTION_RECORD_STOP,
    ACTION_SHOT,
    ACTION_CACHE_CLEAN,
}

_NUM = re.compile(r"(\d+)\s*[x×*]\s*(\d+)", re.IGNORECASE)


def parse_resolution(text: str) -> Optional[Tuple[int, int]]:
    m = _NUM.search(text or "")
    if not m:
        return None
    w, h = int(m.group(1)), int(m.group(2))
    if w <= 0 or h <= 0:
        return None
    return (w, h)


def snapshot() -> Set[str]:
    """当前所有进程名（小写）。"""
    names: Set[str] = set()
    for proc in psutil.process_iter(["name"]):
        try:
            name = proc.info.get("name")
            if name:
                names.add(str(name).lower())
        except (psutil.Error, OSError):
            continue
    return names


def preview(action: "Action", cfg: Config) -> str:
    """只描述这一步会干什么，不碰任何状态。试运行专用。"""
    if action.type in GUI_ACTIONS:
        return f"面板动作：{ACTION_LABEL_TEXT(action.type)}（试运行不会真点）"
    if action.type == ACTION_RESOLUTION:
        res = parse_resolution(action.value)
        if not res:
            return f"切分辨率（写法不对：{action.value or '(空)'}）"
        cur = display.get_current()
        tag = "，和现在一样不会动" if cur == res else ""
        return f"切到 {res[0]}×{res[1]}{tag}"
    if action.type == ACTION_RESTORE:
        nw, nh, _ = cfg.native
        if nw <= 0 or nh <= 0:
            return "恢复原生（没记录过原生，这一步会跳过）"
        cur = display.get_current()
        if cur == (nw, nh):
            return f"恢复原生 {nw}×{nh}（本来就在，不会动）"
        return f"恢复原生 {nw}×{nh}（当前 {cur[0]}×{cur[1]}）"
    if action.type in (ACTION_MOD_START, ACTION_MOD_STOP):
        mod = cfg.get_mod(action.value)
        if mod is None:
            return "启停模组（找不到这个模组，会跳过）"
        if not mod.enabled:
            return "启停模组（这个模组已被屏蔽，会跳过）"
        verb = "启动" if action.type == ACTION_MOD_START else "停止"
        return f"{verb} {mod.name}"
    if action.type == ACTION_WAIT:
        try:
            sec = max(0.0, float(action.value or 0))
        except ValueError:
            sec = 0.0
        return f"等 {sec:g} 秒（试运行不等）"
    return f"不认识的动作：{action.type}"


def execute(
    action: Action,
    cfg: Config,
    guard: ProcessGuard,
    ui=None,
    dry: bool = False,
) -> Tuple[float, str]:
    """执行一个动作，返回 (需要等待的秒数, 给人看的日志)。

    ui 是主窗口，面板开关类动作（ACE / 帧率窗 / 回放 / 录屏 / 截图 / 清缓存）
    都转给它执行；没有 ui 时（比如自检脚本）就跳过并说明原因。
    """
    if dry:
        return (0.0, "〔试运行〕" + preview(action, cfg))

    if action.type in GUI_ACTIONS:
        runner = getattr(ui, "run_gui_action", None)
        if runner is None:
            return (0.0, f"{ACTION_LABEL_TEXT(action.type)}：需要在面板里执行，已跳过")
        return runner(action)
    if action.type == ACTION_RESOLUTION:
        res = parse_resolution(action.value)
        if not res:
            return (0.0, f"分辨率写法不对：{action.value or '(空)'}")
        ok, _code, msg = display.set_resolution(res[0], res[1])
        return (0.0, f"切到 {res[0]}×{res[1]}：{'成功' if ok else msg}")

    if action.type == ACTION_RESTORE:
        nw, nh, _ = cfg.native
        if nw <= 0 or nh <= 0:
            return (0.0, "没有原生分辨率记录，跳过恢复")
        cur = display.get_current()
        if cur == (nw, nh):
            # 本来就是原生（比如开战模板根本没切档），不用再切一次，省得黑一下
            return (0.0, f"本来就在 {nw}×{nh}，不用还原")
        ok, _code, msg = display.set_resolution(nw, nh)
        return (0.0, f"恢复 {nw}×{nh}：{'成功' if ok else msg}")

    if action.type in (ACTION_MOD_START, ACTION_MOD_STOP):
        mod = cfg.get_mod(action.value)
        if mod is None:
            return (0.0, "找不到对应模组，可能已被移除")
        if not mod.enabled:
            return (0.0, f"{mod.name}：已被屏蔽，跳过")
        if action.type == ACTION_MOD_START:
            ok, msg = guard.launch(mod)
            return (0.0, f"启动 {mod.name}：{msg}")
        ok, msg = guard.stop(mod)
        return (0.0, f"停止 {mod.name}：{msg}")

    if action.type == ACTION_WAIT:
        try:
            sec = max(0.0, float(action.value or 0))
        except ValueError:
            sec = 0.0
        return (sec, f"等待 {sec:g} 秒")

    return (0.0, f"不认识的动作：{action.type}")


def describe(rule, cfg: Config) -> str:
    """把规则渲染成一句人话，界面和日志都用。"""
    parts = []
    for a in rule.actions:
        if a.type == ACTION_RESOLUTION:
            res = parse_resolution(a.value)
            parts.append(f"切 {res[0]}×{res[1]}" if res else "切分辨率")
        elif a.type == ACTION_RESTORE:
            parts.append("恢复原生")
        elif a.type == ACTION_MOD_START:
            mod = cfg.get_mod(a.value)
            parts.append(f"启动 {mod.name if mod else '模组'}")
        elif a.type == ACTION_MOD_STOP:
            mod = cfg.get_mod(a.value)
            parts.append(f"停止 {mod.name if mod else '模组'}")
        elif a.type == ACTION_WAIT:
            parts.append(f"等 {a.value}s")
        else:
            parts.append(ACTION_LABEL_TEXT(a.type))
    return " → ".join(parts) if parts else "（没有动作）"


def ACTION_LABEL_TEXT(action_type: str) -> str:
    """动作类型的中文名（给日志和 describe 用）。"""
    from core.store import ACTION_LABEL

    return ACTION_LABEL.get(action_type, action_type)
