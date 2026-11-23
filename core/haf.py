# -*- coding: utf-8 -*-
"""哈夫币盈亏：本地记录 + 从战绩页文本里抽余额

账号安全原则：
  只在内嵌浏览器里让你自己登录，软件不接收、不保存任何密码；
  读取方式是「官方页面自己渲染出来的文字」，软件只负责把数字抄下来。
"""

import json
import re
import time
from pathlib import Path
from urllib.parse import quote

from .store import app_dir

HISTORY_NAME = "haf_history.json"
DEBUG_NAME = "haf_debug.txt"
MAX_RECORDS = 200

# 主入口用 WeGame 助手页：电脑浏览器/内嵌浏览器里能走 QQ / 微信扫码登录。
# 官方小程序那个 H5 只在小程序里才让登录，电脑上登录框是空的，留作参考。
RECORD_URL = "https://www.wegame.com.cn/helper/df/score/"

# 直连扫码登录（WeGame 用的就是这套 QQ / 微信登录参数）
_S_URL = quote("https://www.wegame.com.cn/helper/df/score/", safe="")
LOGIN_QQ = (
    "https://xui.ptlogin2.qq.com/cgi-bin/xlogin"
    "?appid=1600001063&daid=733&style=20&pt_no_auth=0&target=self"
    "&hide_close_icon=1&lang=&hide_border=1&s_url=" + _S_URL
)
LOGIN_WX = (
    "https://open.weixin.qq.com/connect/qrconnect?appid=wx911818d5d92affa8"
    "&scope=snsapi_login&login_type=jssdk&self_redirect=true"
    "&styletype=&sizetype=&bgcolor=&rst=&redirect_uri=" + _S_URL + "&state=wegame"
)

ENTRY_POINTS = [
    ("WeGame 助手（推荐，电脑可扫码登录）", "https://www.wegame.com.cn/helper/df/score/"),
    ("官方小程序 H5（手机端才让登录）", "https://df.qq.com/cp/a20241230webmp/index.html"),
    ("本周战报", "https://df.qq.com/cp/weekly20250821/index.html"),
    ("旧战绩页 2024", "https://df.qq.com/cp/record202410ver/"),
]

# 余额类：哈夫币 / 总资产（读到的是一共多少钱）
_BALANCE_PATTERNS = [
    r"(?:哈夫币|总资产|总计资产|资产总额)[^0-9\-+]{0,14}([-+]?[\d][\d,]*(?:\.\d+)?)\s*(万|亿|w|W|e|E)?",
    r"([\d][\d,]{5,})\s*哈夫币",
]

# 收益类：净收益 / 昨日收益（读到的是一段盈亏，新赛季小程序战绩页用这个）
_PROFIT_PATTERNS = [
    # WeGame 生涯页给的是"场均盈亏"（每局平均赚多少哈夫币）
    r"(?:场均盈亏|场均收益|平均盈亏|平均收益)[^0-9\-+]{0,14}([-+]?[\d][\d,]*(?:\.\d+)?)\s*(万|亿|w|W|e|E)?",
    r"(?:总盈亏|累计盈亏|总收益|累计收益)[^0-9\-+]{0,14}([-+]?[\d][\d,]*(?:\.\d+)?)\s*(万|亿|w|W|e|E)?",
    r"(?:净收益|昨日收益|今日收益|本日收益)[^0-9\-+]{0,14}([-+]?[\d][\d,]*(?:\.\d+)?)\s*(万|亿|w|W|e|E)?",
    r"(?:收益)[^0-9\-+]{0,10}([-+]?[\d][\d,]*(?:\.\d+)?)\s*(万|亿|w|W|e|E)?",
]


def history_path() -> Path:
    return app_dir() / HISTORY_NAME


def load_history() -> list:
    path = history_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    items = data.get("items") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    out = []
    for it in items:
        if isinstance(it, dict) and it.get("value"):
            out.append(
                {
                    "time": str(it.get("time", "")),
                    "value": int(it["value"]),
                    "kind": str(it.get("kind") or "balance"),
                }
            )
    return out


def save_record(value: int, source: str = "web", kind: str = "balance") -> list:
    """追加一条余额记录（同一分钟内的重复读数只保留最新一条）。"""
    items = load_history()
    now = time.strftime("%Y-%m-%d %H:%M")
    value = int(value)
    if items and items[-1]["time"] == now:
        items[-1]["value"] = value
        items[-1]["kind"] = kind
    else:
        items.append({"time": now, "value": value, "kind": kind})
    items = items[-MAX_RECORDS:]
    try:
        history_path().write_text(
            json.dumps({"items": items}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError:
        pass
    return items


def save_debug(text: str) -> None:
    """把页面文字存下来，方便网站改版时对结构。"""
    try:
        (app_dir() / DEBUG_NAME).write_text(
            f"# 抓取时间 {time.strftime('%Y-%m-%d %H:%M:%S')}\n{text}", encoding="utf-8"
        )
    except OSError:
        pass


def _first_value(patterns, flat: str) -> int:
    for pat in patterns:
        for m in re.finditer(pat, flat):
            raw = (m.group(1) or "").replace(",", "")
            unit = (m.group(2) or "") if m.lastindex and m.lastindex >= 2 else ""
            try:
                v = float(raw)
            except ValueError:
                continue
            if unit in ("亿", "e", "E"):
                v *= 100000000
            elif unit:
                v *= 10000
            v = int(round(v))
            if 10**3 <= abs(v) <= 10**12:
                return v
    return 0


def parse_haf(text: str) -> tuple:
    """从页面文字里抽数字。

    返回 (值, 类型)：类型 "balance" 表示余额（一共多少钱），
    "profit" 表示一段净收益；抽不到返回 (0, "")。
    """
    if not text:
        return 0, ""
    flat = re.sub(r"[ \t]+", " ", text)
    v = _first_value(_BALANCE_PATTERNS, flat)
    if v:
        return v, "balance"
    v = _first_value(_PROFIT_PATTERNS, flat)
    if v:
        return v, "profit"
    return 0, ""


def diff_text(items: list) -> tuple:
    """(当前余额, 与上一条的差值)。只有一条记录时差值为 0。"""
    if not items:
        return 0, 0
    cur = items[-1]["value"]
    if len(items) < 2:
        return cur, 0
    return cur, cur - items[-2]["value"]
