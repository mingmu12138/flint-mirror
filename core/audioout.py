# -*- coding: utf-8 -*-
"""音频输出设备：枚举（soundcard 拿名字）+ 读/设默认（Core Audio COM）"""
from __future__ import annotations

import ctypes
from ctypes import POINTER, c_int, c_ulong, c_void_p, c_wchar_p
from typing import List, Optional, Tuple

import comtypes
from comtypes import CLSCTX_ALL, COMMETHOD, GUID, HRESULT, IUnknown, CoCreateInstance

_CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
_CLSID_PolicyConfig = GUID("{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}")

E_RENDER = 0
DEVICE_STATE_ACTIVE = 0x00000001
ROLE_CONSOLE, ROLE_MULTIMEDIA, ROLE_COMMUNICATIONS = 0, 1, 2


class IMMDevice(IUnknown):
    _iid_ = GUID("{D666063F-1587-4E43-81F1-B948E807363F}")
    _methods_ = [
        COMMETHOD([], HRESULT, "Activate",
                  (["in"], POINTER(GUID), "iid"),
                  (["in"], c_ulong, "clsctx"),
                  (["in"], c_void_p, "params"),
                  (["out"], POINTER(POINTER(IUnknown)), "iface")),
        COMMETHOD([], HRESULT, "OpenPropertyStore",
                  (["in"], c_ulong, "access"),
                  (["out"], POINTER(POINTER(IUnknown)), "store")),
        COMMETHOD([], HRESULT, "GetId", (["out"], POINTER(c_wchar_p), "id")),
        COMMETHOD([], HRESULT, "GetState", (["out"], POINTER(c_ulong), "state")),
    ]


class IMMDeviceCollection(IUnknown):
    _iid_ = GUID("{0BD7A1BE-7A1A-44DB-8397-CC5392387B5E}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetCount", (["out"], POINTER(c_ulong), "count")),
        COMMETHOD([], HRESULT, "Item",
                  (["in"], c_ulong, "index"),
                  (["out"], POINTER(POINTER(IMMDevice)), "dev")),
    ]


class IMMDeviceEnumerator(IUnknown):
    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        COMMETHOD([], HRESULT, "EnumAudioEndpoints",
                  (["in"], c_int, "flow"),
                  (["in"], c_ulong, "mask"),
                  (["out"], POINTER(POINTER(IMMDeviceCollection)), "coll")),
        COMMETHOD([], HRESULT, "GetDefaultAudioEndpoint",
                  (["in"], c_int, "flow"),
                  (["in"], c_int, "role"),
                  (["out"], POINTER(POINTER(IMMDevice)), "dev")),
        COMMETHOD([], HRESULT, "GetDevice",
                  (["in"], c_wchar_p, "id"),
                  (["out"], POINTER(POINTER(IMMDevice)), "dev")),
    ]


class IPolicyConfig(IUnknown):
    """只用第 11 个方法 SetDefaultEndpoint，其余按签名占位保证 vtable 偏移正确。"""

    _iid_ = GUID("{F8679F50-850A-41CF-9C72-430F290290C8}")
    _methods_ = [
        COMMETHOD([], HRESULT, "GetMixFormat",
                  (["in"], c_wchar_p, "id"), (["out"], POINTER(c_void_p), "fmt")),
        COMMETHOD([], HRESULT, "GetDeviceFormat",
                  (["in"], c_wchar_p, "id"), (["in"], c_int, "def"),
                  (["out"], POINTER(c_void_p), "fmt")),
        COMMETHOD([], HRESULT, "ResetDeviceFormat", (["in"], c_wchar_p, "id")),
        COMMETHOD([], HRESULT, "SetDeviceFormat",
                  (["in"], c_wchar_p, "id"), (["in"], c_void_p, "fmt"),
                  (["in"], c_void_p, "blob")),
        COMMETHOD([], HRESULT, "GetProcessingPeriod",
                  (["in"], c_wchar_p, "id"), (["in"], c_void_p, "a"),
                  (["in"], c_void_p, "b"), (["out"], POINTER(c_void_p), "x")),
        COMMETHOD([], HRESULT, "SetProcessingPeriod",
                  (["in"], c_wchar_p, "id"), (["in"], c_void_p, "a")),
        COMMETHOD([], HRESULT, "GetShareMode",
                  (["in"], c_wchar_p, "id"), (["out"], POINTER(c_void_p), "x")),
        COMMETHOD([], HRESULT, "SetShareMode",
                  (["in"], c_wchar_p, "id"), (["in"], c_void_p, "a")),
        COMMETHOD([], HRESULT, "GetPropertyValue",
                  (["in"], c_wchar_p, "id"), (["in"], c_void_p, "k"),
                  (["out"], POINTER(c_void_p), "v")),
        COMMETHOD([], HRESULT, "SetPropertyValue",
                  (["in"], c_wchar_p, "id"), (["in"], c_void_p, "k"),
                  (["in"], c_void_p, "v")),
        COMMETHOD([], HRESULT, "SetDefaultEndpoint",
                  (["in"], c_wchar_p, "id"), (["in"], c_int, "role")),
        COMMETHOD([], HRESULT, "SetEndpointVisibility",
                  (["in"], c_wchar_p, "id"), (["in"], c_int, "visible")),
    ]


_enumerator = None
_policy = None


def _init() -> None:
    global _enumerator, _policy
    if _enumerator is not None:
        return
    comtypes.CoInitialize()
    try:  # 打包后程序目录只读，别让 comtypes 往 disk 上写生成代码
        from comtypes import client as _ct_client

        _ct_client.gen_dir = None
    except Exception:  # noqa: BLE001
        pass
    _enumerator = CoCreateInstance(
        _CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, CLSCTX_ALL
    )
    _policy = CoCreateInstance(_CLSID_PolicyConfig, IPolicyConfig, CLSCTX_ALL)


def _dev_id(dev) -> str:
    try:
        return dev.GetId() or ""
    except Exception:  # noqa: BLE001
        return ""


def list_render_devices() -> List[Tuple[str, str]]:
    """活动中的输出设备：(设备 id, 设备名)。"""
    _init()
    coll = _enumerator.EnumAudioEndpoints(E_RENDER, DEVICE_STATE_ACTIVE)
    count = int(coll.GetCount())

    names = {}
    try:
        import soundcard as _sc

        for sp in _sc.all_speakers():
            names[str(sp.id).lower()] = sp.name
    except Exception:  # noqa: BLE001
        pass

    out = []
    for i in range(count):
        try:
            dev = coll.Item(i)
        except Exception:  # noqa: BLE001
            continue
        did = _dev_id(dev)
        if not did:
            continue
        name = names.get(did.lower(), "")
        if not name:
            name = did.split("}.")[-1][:8] if "}" in did else did[-8:]
            name = f"输出设备 {name}"
        out.append((did, name))
    return out


def get_default_render() -> str:
    """当前默认输出设备的 id。"""
    _init()
    try:
        dev = _enumerator.GetDefaultAudioEndpoint(E_RENDER, ROLE_CONSOLE)
    except Exception:  # noqa: BLE001
        return ""
    return _dev_id(dev)


def set_default_render(device_id: str) -> Tuple[bool, str]:
    """把某个输出设备切成默认（控制/多媒体/通信三个角色一起切）。"""
    if not device_id:
        return False, "设备 id 是空的"
    _init()
    try:
        for role in (ROLE_CONSOLE, ROLE_MULTIMEDIA, ROLE_COMMUNICATIONS):
            _policy.SetDefaultEndpoint(device_id, role)
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, str(exc)


def device_name(device_id: str) -> str:
    for did, name in list_render_devices():
        if did.lower() == (device_id or "").lower():
            return name
    return ""
