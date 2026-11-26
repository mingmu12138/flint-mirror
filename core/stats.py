"""设备级日活计数。

每次启动向一个公共计数器打一次，本机同一天只计一次 —— 一台电脑一天算一个日活。
界面不显示任何东西，断网/服务挂了就静默跳过，绝不影响启动。

两个计数键：
  dau20261126  当天开过的设备数（日活，去重到「台/天」）
  v1103        这个版本的累计启动次数（看哪个版本还在被用）

局限：只有「日活」和「版本启动量」，没有「此刻在线」。在线要求服务端存
设备 id + 最近在线时间（5 分钟窗口），得自建后端，公共计数器存不了。

不想统计了：把 NS 置空，或者注释掉 gui.py showEvent 里那三行调用。
"""

from __future__ import annotations

import datetime
import json
import re
import threading
import urllib.error
import urllib.request
from pathlib import Path

# 计数用的命名空间。拼成两段只是为了让它在一堆代码里不显眼 ——
# 别人不知道这一串就查不到数据，也没有办法把数字改小；改掉它等于换一个计数器。
NS = "fm3a71c" + "3dd1a"
_ENDPOINT = "https://abacus.jasoncameron.dev"
_TIMEOUT = 4
_UA = "FlintMirror-stats/1"


def _hit(key: str) -> int:
    url = "%s/hit/%s/%s" % (_ENDPOINT, NS, key)
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        body = json.loads((r.read() or b"{}").decode("utf-8", "replace"))
    return int(body.get("value") or 0)


def _report(app_dir: Path, ver: str = "") -> None:
    if not NS:
        return
    today = datetime.date.today().strftime("%Y%m%d")
    mark = app_dir / "cache" / "_s.txt"
    counted = False
    try:
        counted = mark.read_text("utf-8").strip() == today
    except Exception:  # noqa: BLE001
        counted = False
    try:
        if not counted:
            _hit("dau%s" % today)
            try:
                mark.parent.mkdir(parents=True, exist_ok=True)
                mark.write_text(today, "utf-8")
            except Exception:  # noqa: BLE001
                pass
        if ver:
            # "v1.10.3" → "v1103"，一个版本一个键
            tag = re.sub(r"[^0-9a-zA-Z]", "", ver)
            if tag:
                _hit(tag)
    except Exception:  # noqa: BLE001
        return


def report_async(app_dir, ver: str = "") -> None:
    """起一条后台线程上报，调用方立刻返回（不卡启动）。"""
    try:
        threading.Thread(target=_report, args=(Path(app_dir), ver), daemon=True).start()
    except Exception:  # noqa: BLE001
        pass


def today_count() -> int:
    """查今天的设备数（调通了才有值，-1 表示查询失败）。"""
    try:
        url = "%s/get/%s/dau%s" % (_ENDPOINT, NS, datetime.date.today().strftime("%Y%m%d"))
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
            return int(json.loads(r.read().decode("utf-8", "replace")).get("value") or 0)
    except urllib.error.HTTPError as exc:
        return 0 if exc.code == 404 else -1   # 今天还没人来过，就是 0
    except Exception:  # noqa: BLE001
        return -1
