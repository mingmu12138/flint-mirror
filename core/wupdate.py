# -*- coding: utf-8 -*-
"""一键推迟 Windows 自动更新。

做法和系统「设置 → Windows 更新 → 暂停更新」完全同一套注册表项，
所以状态在系统设置里也能看到，到期会自动恢复，不是把更新彻底关掉。
"""
from __future__ import annotations

import winreg
from datetime import datetime, timedelta, timezone

KEY_PATH = r"SOFTWARE\Microsoft\WindowsUpdate\UX\Settings"

PAUSE_VALUES = (
    "PauseUpdatesExpiryTime",
    "PauseUpdatesStartTime",
    "PauseFeatureUpdatesStartTime",
    "PauseFeatureUpdatesEndTime",
    "PauseQualityUpdatesStartTime",
    "PauseQualityUpdatesEndTime",
)

MAX_DAYS = 35


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse(text: str) -> datetime | None:
    for pat in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, pat).replace(tzinfo=timezone.utc)
        except Exception:
            continue
    return None


def status() -> tuple[bool, str]:
    """返回 (是否正在推迟, 给人看的状态文案)。"""
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY_PATH)
    except FileNotFoundError:
        return False, "这台系统没有更新暂停项（可能是精简版）"
    except PermissionError:
        return False, "没有权限读取（用管理员身份重开燧镜即可）"
    except OSError as exc:
        return False, f"读不到状态：{exc}"
    try:
        raw, _ = winreg.QueryValueEx(key, "PauseUpdatesExpiryTime")
    except FileNotFoundError:
        return False, "未推迟，系统会按计划自动更新"
    except OSError:
        return False, "未推迟"
    finally:
        try:
            winreg.CloseKey(key)
        except Exception:
            pass

    dt = _parse(str(raw))
    if dt is None:
        return False, "未推迟"
    left = dt - datetime.now(timezone.utc)
    if left.total_seconds() <= 0:
        return False, "上次的推迟已到期（%s）" % dt.astimezone().strftime("%Y-%m-%d")
    days = max(0, left.days)
    return True, "已推迟到 %s（还剩 %d 天）" % (dt.astimezone().strftime("%Y-%m-%d"), days)


def pause(days: int = MAX_DAYS) -> tuple[bool, str]:
    days = max(1, min(MAX_DAYS, int(days)))
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days)
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, KEY_PATH, 0, winreg.KEY_SET_VALUE
        )
    except PermissionError:
        return False, "需要管理员权限：右键燧镜「以管理员身份运行」后再点一次"
    except FileNotFoundError:
        return False, "找不到 Windows 更新设置项，这台系统可能被精简过"

    try:
        for name in PAUSE_VALUES:
            value = _fmt(end) if "Expiry" in name or "End" in name else _fmt(now)
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
    except PermissionError:
        return False, "需要管理员权限：右键燧镜「以管理员身份运行」后再点一次"
    except OSError as exc:
        return False, f"写入失败：{exc}"
    finally:
        try:
            winreg.CloseKey(key)
        except Exception:
            pass
    return True, "已把系统更新推迟到 %s（%d 天）" % (end.astimezone().strftime("%Y-%m-%d"), days)


def resume() -> tuple[bool, str]:
    try:
        key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, KEY_PATH, 0, winreg.KEY_SET_VALUE
        )
    except PermissionError:
        return False, "需要管理员权限：右键燧镜「以管理员身份运行」后再点一次"
    except FileNotFoundError:
        return False, "找不到 Windows 更新设置项"

    removed = 0
    try:
        for name in PAUSE_VALUES:
            try:
                winreg.DeleteValue(key, name)
                removed += 1
            except FileNotFoundError:
                continue
            except OSError:
                continue
    finally:
        try:
            winreg.CloseKey(key)
        except Exception:
            pass
    if removed:
        return True, "已取消推迟，系统会恢复按计划更新"
    return True, "本来就没在推迟"
