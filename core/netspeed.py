# -*- coding: utf-8 -*-
"""网络测速：多线程拉固定大小的测速文件，算下载带宽；顺便测一下到国内镜像的延迟。

用公共测速端点（Cloudflare 官方测速后端的 __down 接口），失败自动换备用源。
"""

from __future__ import annotations

import socket
import threading
import time
import urllib.request
from typing import List, Optional, Tuple

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# 每个线程要拉的长度（字节）；4 线程合计约 32MB，家用宽带跑十几秒
PER_THREAD = 8_000_000
THREADS = 4
TIMEOUT = 15

SOURCES = [
    "https://speed.cloudflare.com/__down?bytes={n}",
    "https://mirrors.aliyun.com/ubuntu-releases/24.04/ubuntu-24.04.2-desktop-amd64.iso",
]
PING_HOSTS = [("mirrors.aliyun.com", 443), ("www.baidu.com", 443)]


def _pick_source() -> Optional[str]:
    for url in SOURCES:
        try:
            req = urllib.request.Request(url.format(n=1_000_000) if "{n}" in url else url,
                                         headers=UA)
            with urllib.request.urlopen(req, timeout=6) as r:
                r.read(64)
            return url
        except Exception:
            continue
    return None


def download_speed(url: str, threads: int = THREADS, per_thread: int = PER_THREAD
                   ) -> Tuple[Optional[float], int, float]:
    """返回 (Mbps, 总字节, 秒)。"""
    total = 0
    lock = threading.Lock()
    stop = threading.Event()
    start = time.time()

    def worker(index: int) -> None:
        nonlocal total
        begin = index * per_thread
        end = begin + per_thread - 1
        target = url.format(n=per_thread) if "{n}" in url else url
        headers = dict(UA)
        if "{n}" not in url:
            headers["Range"] = f"bytes={begin}-{end}"
        try:
            req = urllib.request.Request(target, headers=headers)
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                got = 0
                while got < per_thread and not stop.is_set():
                    buf = resp.read(min(65536, per_thread - got))
                    if not buf:
                        break
                    got += len(buf)
                    with lock:
                        total += len(buf)
        except Exception:
            pass

    ts = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(TIMEOUT + 5)
    elapsed = time.time() - start
    if elapsed <= 0 or total <= 0:
        return None, total, elapsed
    mbps = (total * 8) / elapsed / 1_000_000
    return mbps, total, elapsed


def ping() -> Optional[float]:
    """到国内节点的 TCP 建连延迟（毫秒，取最低三次）。"""
    samples: List[float] = []
    for host, port in PING_HOSTS:
        for _ in range(3):
            try:
                t0 = time.perf_counter()
                with socket.create_connection((host, port), timeout=3):
                    samples.append((time.perf_counter() - t0) * 1000)
            except Exception:
                continue
    return min(samples) if samples else None


def run() -> dict:
    """一次性测完。结果：{'mbps','mb','sec','ping','source'}，失败字段为 None。"""
    result = {"mbps": None, "mb": None, "sec": None, "ping": ping(), "source": None}
    if result["ping"] is None:
        # 连都连不上，就不用测下载了
        return result
    url = _pick_source()
    if not url:
        return result
    result["source"] = "Cloudflare" if "cloudflare" in url else "阿里云镜像"

    # 先试多线程，被拒就退回单连接（不少网络和防火墙会掐掉并发连接）
    for threads, per_thread in ((3, 5_000_000), (1, 8_000_000)):
        mbps, total, sec = download_speed(url, threads=threads, per_thread=per_thread)
        if mbps:
            result["mbps"] = mbps
            result["mb"] = total / 1_000_000
            result["sec"] = sec
            break
    return result


# ---------------------------------------------------------------- 连续采样
def ping_once(host: str, port: int, timeout: float = 2.5) -> Optional[float]:
    """一次 TCP 握手耗时（毫秒）。失败返回 None（算丢包）。"""
    try:
        t0 = time.perf_counter()
        with socket.create_connection((host, port), timeout=timeout):
            return (time.perf_counter() - t0) * 1000
    except Exception:  # noqa: BLE001
        return None


def split_host(text: str) -> Tuple[Optional[str], int]:
    """把 "例子.com" / "例子.com:8080" / "1.2.3.4:9000" 拆成 (host, port)。"""
    raw = (text or "").strip()
    if not raw:
        return (None, 443)
    if raw.startswith("[") and "]" in raw:  # IPv6 带方括号
        host, _, tail = raw[1:].partition("]")
        port = 443
        if tail.startswith(":") and tail[1:].isdigit():
            port = int(tail[1:])
        return (host or None, port)
    if ":" in raw:
        host, _, port_s = raw.rpartition(":")
        if port_s.isdigit():
            return (host or None, int(port_s))
    return (raw, 443)


def ping_monitor(
    seconds: float = 12.0,
    interval: float = 0.5,
    on_sample=None,
    targets=None,
) -> dict:
    """连续 ping 一段时间，算均值/极值/抖动/丢包。

    on_sample(第几次, 总次, 当前毫秒或 None, 已统计的 dict) 用于实时刷界面。
    抖动按 RFC3550 那套：相邻两次差值的平均绝对值。
    """
    hosts = list(targets) if targets else list(PING_HOSTS)
    values: List[float] = []
    lost = 0
    rounds = max(1, int(seconds / interval))
    start = time.time()
    for i in range(rounds):
        if time.time() - start > seconds:
            break
        host, port = hosts[i % len(hosts)]
        ms = ping_once(host, port)
        if ms is None:
            lost += 1
        else:
            values.append(ms)
        if on_sample is not None:
            try:
                on_sample(i + 1, rounds, ms, _stats(values, lost))
            except Exception:  # noqa: BLE001
                pass
        time.sleep(max(0.0, interval - 0.0))
    return _stats(values, lost)


def _stats(values: List[float], lost: int) -> dict:
    if not values:
        return {
            "avg": None, "min": None, "max": None, "jitter": None,
            "loss": 100.0 if lost else None, "count": lost, "ok": 0,
        }
    values_sorted = sorted(values)
    avg = sum(values) / len(values)
    # 抖动：相邻差值绝对值的平均
    diffs = [abs(values[i] - values[i - 1]) for i in range(1, len(values))]
    jitter = sum(diffs) / len(diffs) if diffs else 0.0
    total = len(values) + lost
    return {
        "avg": avg,
        "min": values_sorted[0],
        "max": values_sorted[-1],
        "jitter": jitter,
        "loss": (lost / total * 100.0) if total else None,
        "count": total,
        "ok": len(values),
        "values": values,
    }


def verdict(stats: dict) -> str:
    """大白话判定：这次卡，怪网络还是怪机器。"""
    if not stats or stats.get("avg") is None:
        return "连测速节点都连不上，先检查网线 / WiFi / 路由器"
    loss = stats.get("loss") or 0.0
    jitter = stats.get("jitter") or 0.0
    avg = stats.get("avg") or 0.0
    peak = stats.get("max") or 0.0
    if loss >= 8:
        return f"丢包 {loss:.0f}%，这是网络问题（掉线/路由器/校园网限速），换有线或重启路由器"
    if jitter >= 45 or peak - avg >= 80:
        return (
            f"抖动大：平均 {avg:.0f} ms 但最高 {peak:.0f} ms，"
            "典型 WiFi 干扰或后台在下载，先关后台同步再试"
        )
    if avg >= 90:
        return f"延迟偏高（{avg:.0f} ms），延迟本身就不适合打 FPS，尽量用有线 + 就近服务器"
    if loss <= 1 and jitter <= 12:
        return (
            f"网络很稳（{avg:.0f} ms / 抖动 {jitter:.0f} ms / 几乎不丢包）——"
            "这时候卡就不是网络的锅，去查显卡占用、温度、帧率灯"
        )
    return f"网络基本可用（{avg:.0f} ms · 抖动 {jitter:.0f} ms · 丢包 {loss:.0f}%）"
