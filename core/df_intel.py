# -*- coding: utf-8 -*-
"""三角洲情报 · 数据层

数据来源：https://shushu.fan/（服务端渲染，普通 HTTP 请求即可拿到明文数据）
设计原则：
  1. 只用标准库 urllib，不引第三方依赖
  2. 只在用户点「刷新」时发请求，平时不发
  3. 任一区块解析失败都只返回空值，不抛异常
  4. 只抓公开页面，不碰它的 /api/（站点 robots 明确禁止）

对外接口：
    DataSource(cache_path).refresh() -> dict
    DataSource(cache_path).load_cache() -> dict
"""

import json
import re
import time
import urllib.request
from pathlib import Path

BASE = "https://shushu.fan"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

MAP_NAMES = ["零号大坝", "长弓溪谷", "巴克什", "航天基地", "潮汐监狱", "AZ3"]
STATIONS = ("防具台", "制药台", "技术中心", "工作台", "技术中心", "医疗台")


# ------------------------------------------------------------------ 基础
def fetch(path: str, timeout: int = 20) -> str:
    url = path if path.startswith("http") else BASE + path
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": BASE + "/",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "replace")


def to_text(html: str) -> str:
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<style.*?</style>", " ", html, flags=re.S | re.I)
    html = re.sub(r"<!--.*?-->", " ", html, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", html)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&#x27;", "'"))
    return re.sub(r"\s+", " ", text).strip()


def _num(s: str) -> int:
    try:
        return int(re.sub(r"[^\d-]", "", s))
    except ValueError:
        return 0


# ------------------------------------------------------------------ 各块解析
def parse_passwords(html: str) -> dict:
    out = {"maps": {}, "updated": ""}
    for name in MAP_NAMES:
        for m in re.finditer(r'alt="' + re.escape(name) + r'"', html):
            window = html[m.end():m.end() + 1600]
            hit = re.search(r"<span[^>]*>" + re.escape(name) +
                            r"</span><span[^>]*>(\d{3,5})</span>", window)
            if hit:
                out["maps"][name] = hit.group(1)
                break
    date = re.search(r"20\d{2}-\d{2}-\d{2}", to_text(html))
    if date:
        out["updated"] = date.group(0)
    return out


def parse_craft(html: str) -> list:
    """首页「制造台推荐」：物品 / 台子 / 利润。"""
    items = []
    pat = re.compile(
        r'<h3[^>]*>([^<]{1,24})</h3>.{0,400}?'
        r'<span[^>]*>([^<]{1,10}台|技术中心|工作台)</span>.{0,400}?'
        r'<span[^>]*>([\d,]{3,})</span>', re.S)
    for name, station, profit in pat.findall(html):
        items.append({"name": name.strip(), "station": station.strip(),
                      "profit": _num(profit)})
    return items[:8]


def parse_kzb(html: str) -> dict:
    """卡战备：五个目标档 + 页面默认档的三套方案。

    页面先列五个档位目标，再列当前默认档（11W）的三套方案；
    其它档位要靠页面内交互切换，服务端只渲染默认档 —— 所以这里只取默认档。
    """
    text = to_text(html)
    tiers = [{"value": m.group(1), "target": m.group(2)}
             for m in re.finditer(
                 r"(\d{1,3}W)\s*(大坝、长弓—机密|航天、巴克什—机密|巴克什—绝密|"
                 r"航天基地—绝密|潮汐监狱—绝密)", text)]

    plans = []
    plan_pat = re.compile(
        r"(枪械优先|均衡套装|胸挂优先)\s*售价\s*([\d.]+W)\s*战备\s*([\d.]+W)\s*假账\s*(-?[\d.]+W)")
    matches = list(plan_pat.finditer(text))
    item_pat = re.compile(
        r"([\u4e00-\u9fa5A-Za-z0-9\-.]+?(?:\s*\(破损\))?)\s+([\d,]+)\s+([+-]\s*[\d,]+)")
    for idx, m in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        seg = text[m.end():min(end, m.end() + 300)]
        gear = [{"name": a.strip(), "price": _num(b), "diff": _num(c)}
                for a, b, c in item_pat.findall(seg)]
        plans.append({"type": m.group(1), "sell": m.group(2), "gear": m.group(3),
                      "fake": m.group(4), "items": gear})
    updated = ""
    d = re.search(r"20\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", text)
    if d:
        updated = d.group(0)
    return {"tiers": tiers, "plans": plans, "updated": updated,
            "note": "方案为页面默认档（11W 大坝、长弓—机密）"}


def parse_ammo_bundle(html: str) -> list:
    items = []
    for m in re.finditer(r'alt="([^"]{2,30})"[^>]*class="w-12 h-12[^"]*"', html):
        name = m.group(1)
        window = html[m.end():m.end() + 1500]
        cnt = re.search(r"x<!-- -->(\d+)</span>", window)
        unit = re.search(r'alt="哈夫币"[^>]*/><span[^>]*>([\d,]+)</span>', window)
        total = re.search(r'text-green-600[^>]*>([\d,]+)</p>', window)
        if cnt and unit and total:
            items.append({"name": name, "count": _num(cnt.group(1)),
                          "unit": _num(unit.group(1)), "total": _num(total.group(1))})
    updated = ""
    t = to_text(html)
    d = re.search(r"20\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", t)
    if d:
        updated = d.group(0)
    return {"list": items[:30], "updated": updated}


def parse_price_top(html: str) -> dict:
    """假账排行榜：排名 / 物品 / 战备值 / 售价 / 差价。"""
    pat = re.compile(
        r'tabular-nums[^>]*>(\d{1,3})</div>.{0,700}?'
        r'truncate text-sm font-medium">([^<]{1,40})</div>'
        r'<div[^>]*>战备[^<]*<!-- -->([\d,]+)</div>'
        r'<div[^>]*>售价[^<]*<!-- -->([\d,]+)</div>.{0,300}?'
        r'tabular-nums[^>]*>\s*(-?[\d,]+)\s*</div>', re.S)
    items = [{"rank": _num(r), "name": n.strip(), "gear": _num(g),
              "sell": _num(s), "diff": _num(d)} for r, n, g, s, d in pat.findall(html)]
    updated = ""
    t = to_text(html)
    d = re.search(r"20\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", t)
    if d:
        updated = d.group(0)
    return {"list": items[:40], "updated": updated}


def parse_profit_rank(html: str) -> dict:
    """制造利润排行：按台子分组的表格。"""
    groups = []
    # 每个台子一个 <h2>，取到下一个 h2 之间
    heads = list(re.finditer(r"<h2[^>]*>([^<]{1,12}台|技术中心|工作台)</h2>", html))
    for idx, hm in enumerate(heads):
        station = hm.group(1)
        chunk = html[hm.end(): heads[idx + 1].start() if idx + 1 < len(heads) else len(html)]
        row_pat = re.compile(
            r'truncate">([^<]{1,40})</p>'
            r'.{0,200}?<span[^>]*>(\d{1,3})小时</span>'
            r'.{0,300}?text-green-600[^>]*>([\d,]+)</p>'
            r'.{0,200}?>([\d,]+)<!-- -->/h', re.S)
        rows = [{"name": n.strip(), "hours": _num(h), "profit": _num(p),
                 "hourly": _num(hr)} for n, h, p, hr in row_pat.findall(chunk)]
        if rows:
            groups.append({"station": station, "list": rows})
    updated = ""
    d = re.search(r"20\d{2}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", to_text(html))
    if d:
        updated = d.group(0)
    return {"groups": groups, "updated": updated}


# ------------------------------------------------------------------ 缓存与刷新
class DataSource:
    def __init__(self, cache_path) -> None:
        self.cache_path = Path(cache_path)

    def load_cache(self) -> dict:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def save_cache(self, data: dict) -> None:
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                                       encoding="utf-8")
        except Exception:
            pass

    def refresh(self, progress=None) -> dict:
        """抓一次全部数据；某个块失败不影响其它块。"""
        result = {"fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"), "errors": []}
        home = None

        def step(name, path, parser, key, need_home=False):
            nonlocal home
            if progress:
                progress(name)
            try:
                if need_home:
                    home = home or fetch("/")
                    result[key] = parser(home)
                else:
                    result[key] = parser(fetch(path))
            except Exception as exc:
                result[key] = parser("") if key == "passwords" and False else _empty(key)
                result["errors"].append(f"{name}: {type(exc).__name__} {exc}")

        step("密码门", "/", parse_passwords, "passwords", need_home=True)
        step("制造推荐", "/", parse_craft, "craft", need_home=True)
        step("子弹自选包", "/chi/bullet-to-profit", parse_ammo_bundle, "ammo")
        step("假账排行", "/priceTop", parse_price_top, "price_top")
        step("制造利润榜", "/chi/profitRank", parse_profit_rank, "profit")

        code_block = result.get("passwords") or {}
        if code_block.get("maps"):
            # 记下「这批密码属于哪一天」，跨天判断只认这个日期
            code_block["codes_date"] = time.strftime("%Y-%m-%d")
            code_block["checked_at"] = time.strftime("%Y-%m-%d %H:%M")
            self.save_cache(result)
        return result

    def refresh_codes(self) -> dict:
        """只抓首页的每日密码，其它块沿用缓存（跨天自动更新用这个，省请求）。"""
        data = self.load_cache() or {}
        try:
            pw = parse_passwords(fetch("/"))
        except Exception as exc:  # noqa: BLE001
            errs = list(data.get("errors") or [])
            errs.append(f"密码: {type(exc).__name__} {exc}")
            data["errors"] = errs[-3:]
            data["last_code_error"] = f"{type(exc).__name__} {exc}"
            return data
        if not pw.get("maps"):
            data["last_code_error"] = "没有解析到密码"
            return data
        pw["codes_date"] = time.strftime("%Y-%m-%d")
        pw["checked_at"] = time.strftime("%Y-%m-%d %H:%M")
        data["passwords"] = pw
        data["fetched_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        data["errors"] = []
        data.pop("last_code_error", None)
        self.save_cache(data)
        return data


def _empty(key):
    return {
        "passwords": {"maps": {}, "updated": ""},
        "kzb": {"tiers": [], "plans": [], "updated": "", "note": ""},
        "ammo": {"list": [], "updated": ""},
        "price_top": {"list": [], "updated": ""},
        "profit": {"groups": [], "updated": ""},
    }.get(key, [])


if __name__ == "__main__":
    ds = DataSource(Path(__file__).with_name("delta_cache.json"))
    data = ds.refresh(progress=lambda n: print("抓取:", n))
    print("\n密码门:", data["passwords"])
    print("制造推荐:", len(data.get("craft", [])), data.get("craft", [])[:2])
    k = data.get("kzb", {})
    print("卡战备档位:", [t["value"] + t["target"] for t in k.get("tiers", [])])
    for p in k.get("plans", []):
        print("   ", p["type"], p["sell"], p["gear"], p["fake"], len(p["items"]), "件")
    print("子弹自选包:", len(data.get("ammo", {}).get("list", [])))
    print("假账榜:", len(data.get("price_top", {}).get("list", [])))
    print("制造利润组:", [(g["station"], len(g["list"])) for g in data.get("profit", {}).get("groups", [])])
    print("errors:", data.get("errors"))
