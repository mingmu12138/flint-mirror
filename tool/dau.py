"""看日活：打印最近两周每天有多少台设备开过燧镜。

用法：在项目根目录运行 python tool/dau.py
（只读，不会改计数；某天显示 - 表示那天没查通）
"""

from __future__ import annotations

import datetime
import time

import requests

NS = "fm3a71c" + "3dd1a"
BASE = "https://abacus.jasoncameron.dev"
DAYS = 14
VERSIONS = ("v1103", "v1102", "v1101", "v1100", "v197")

_sess = requests.Session()
_sess.headers["User-Agent"] = "FlintMirror-stats/1"


def count(key: str, retry: int = 2) -> int:
    """读一个计数键。0 = 还没人写过，-1 = 查不通（重跑一次通常就好）。"""
    try:
        r = _sess.get("%s/get/%s/%s" % (BASE, NS, key), timeout=8)
        if r.status_code == 404:
            return 0
        if r.status_code != 200:
            if retry:
                time.sleep(1.5)
                return count(key, retry - 1)
            return -1
        return int((r.json() or {}).get("value") or 0)
    except Exception:  # noqa: BLE001
        if retry:
            time.sleep(1.5)
            return count(key, retry - 1)
        return -1


def main() -> None:
    print("单版本累计启动：")
    got = False
    for tag in VERSIONS:
        n = count(tag)
        if n > 0:
            print("  %-6s %d 次" % (tag, n))
            got = True
        time.sleep(0.25)
    if not got:
        print("  （还没有记录）")

    print()
    print("最近 %d 天日活：" % DAYS)
    today = datetime.date.today()
    rows = []
    for i in range(DAYS - 1, -1, -1):
        d = today - datetime.timedelta(days=i)
        rows.append((d, count("dau" + d.strftime("%Y%m%d"))))
        time.sleep(0.25)
    print("日期        日活设备")
    print("-" * 26)
    for d, n in rows:
        flag = "  ← 今天" if d == today else ""
        print("%s  %s%s" % (d.isoformat(), ("-" if n < 0 else "%d" % n), flag))
    ok = [n for _, n in rows if n > 0]
    print("-" * 26)
    if ok:
        print("峰值 %d · 有人开过的天数 %d · 合计设备日 %d" % (max(ok), len(ok), sum(ok)))
    else:
        print("这段时间没有设备记录（或者刚好都没查通）")


if __name__ == "__main__":
    main()
