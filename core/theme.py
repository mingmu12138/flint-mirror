# -*- utf-8 -*-
"""主题与皮肤。

界面上的颜色和圆角都从这里取，不再直接写死。
一套皮肤 = 一个 json（只有颜色 + 圆角，不含布局，所以换皮肤不会打乱排版）。

皮肤文件坏了、字段缺了、或者用户手改坏了，一律回落内置「赛博青」，绝不会留白屏。
"""
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .store import app_dir

log = logging.getLogger(__name__)

# 不随皮肤变：红就是出错，黄就是注意，紫就是提示，绿就是正常。
# 这几样一旦跟着换颜色，「红=报错」的语感就乱了。
FIXED = {
    "state-danger": "#ff6b6b",
    "state-alert": "#ffb020",
    "state-warn": "#d9a441",
    "state-info": "#8a7bd4",
    "state-ok": "#7ee787",
}

_DEFAULT_RADIUS = {"sm": 9, "md": 15, "lg": 19, "xl": 23, "btn": 10}

# 内置三套。赛博青就是原来那套，改皮肤之前和之后看起来一模一样。
BUILTIN: Dict[str, dict] = {
    "cyber": {
        "name": "赛博青",
        "author": "内置",
        "desc": "原来那套青绿配色，默认",
        "colors": {
            "bg-page": "#0e1015",
            "bg-sunken": "#0b0e13",
            "bg-card": "#161a22",
            "bg-raised": "#1a1f29",
            "bg-button": "#1e242f",
            "bg-hover": "#262e3c",
            "bg-off": "#141822",
            "bg-off2": "#10131a",
            "line-1": "#242b38",
            "line-2": "#3a4455",
            "line-sep": "#2a3240",
            "fg-title": "#f6f9fe",
            "fg-0": "#eef3fb",
            "fg-1": "#c9cfda",
            "fg-2": "#8b95a5",
            "fg-3": "#5f6878",
            "fg-off": "#4d5563",
            "accent": "#20ffe0",
            "accent-strong": "#17c8a8",
            "accent-hover": "#24e3be",
            "accent-press": "#12b295",
            "accent-dim": "#14c2a4",
            "accent-bg": "#102a27",
            "accent-line": "#1c4a43",
            "on-accent": "#04120f",
        },
    },
    "ink": {
        "name": "墨紫",
        "author": "内置",
        "desc": "近黑底配紫电，国产二次元工具里最常见的那套",
        "colors": {
            "bg-page": "#14121a",
            "bg-sunken": "#100e15",
            "bg-card": "#1c1826",
            "bg-raised": "#221d2e",
            "bg-button": "#272135",
            "bg-hover": "#322a43",
            "bg-off": "#191520",
            "bg-off2": "#15121b",
            "line-1": "#2c2540",
            "line-2": "#40355c",
            "line-sep": "#302948",
            "fg-title": "#f8f5ff",
            "fg-0": "#f0ebfa",
            "fg-1": "#cec4e4",
            "fg-2": "#948aa8",
            "fg-3": "#6a617c",
            "fg-off": "#554d64",
            "accent": "#8b6cf6",
            "accent-strong": "#6f52d8",
            "accent-hover": "#a087ff",
            "accent-press": "#5a3fc0",
            "accent-dim": "#7a5ce0",
            "accent-bg": "#1e1830",
            "accent-line": "#3a2f5e",
            "on-accent": "#100a22",
        },
    },
    "blue": {
        "name": "白蓝",
        "author": "内置",
        "desc": "深底配白光蓝，冷色科技感，默认青绿的替代档",
        "colors": {
            "bg-page": "#0d1218",
            "bg-sunken": "#0a0f14",
            "bg-card": "#141b24",
            "bg-raised": "#18212b",
            "bg-button": "#1d2733",
            "bg-hover": "#24313f",
            "bg-off": "#121821",
            "bg-off2": "#0f141b",
            "line-1": "#222d3a",
            "line-2": "#35475c",
            "line-sep": "#28323f",
            "fg-title": "#f7fbff",
            "fg-0": "#eef5fc",
            "fg-1": "#c6d3e2",
            "fg-2": "#8798ac",
            "fg-3": "#5c6b7d",
            "fg-off": "#4a5867",
            "accent": "#3e9bff",
            "accent-strong": "#2c7fd6",
            "accent-hover": "#5aabff",
            "accent-press": "#2470c2",
            "accent-dim": "#2f86d8",
            "accent-bg": "#10202f",
            "accent-line": "#1d3f5c",
            "on-accent": "#04121f",
        },
    },
    "orange": {
        "name": "橙黑",
        "author": "内置",
        "desc": "黑底焦橙，暖得厉害，夜里看屏幕像开了护眼",
        "colors": {
            "bg-page": "#14110d",
            "bg-sunken": "#0f0d0a",
            "bg-card": "#1c1811",
            "bg-raised": "#231e15",
            "bg-button": "#2a241a",
            "bg-hover": "#332c1f",
            "bg-off": "#181410",
            "bg-off2": "#141110",
            "line-1": "#2e271a",
            "line-2": "#4a3c26",
            "line-sep": "#332b1d",
            "fg-title": "#fff6ea",
            "fg-0": "#f8eddc",
            "fg-1": "#dcc9ad",
            "fg-2": "#a3907a",
            "fg-3": "#736a5b",
            "fg-off": "#5a5247",
            "accent": "#ff7a33",
            "accent-strong": "#d9601f",
            "accent-hover": "#ff9358",
            "accent-press": "#bf5216",
            "accent-dim": "#e86f2c",
            "accent-bg": "#2a1a0f",
            "accent-line": "#5e3a1e",
            "on-accent": "#180a02",
        },
    },
    "pink": {
        "name": "粉黑",
        "author": "内置",
        "desc": "黑底樱花粉，字偏冷，配壁纸最好看",
        "colors": {
            "bg-page": "#161114",
            "bg-sunken": "#110d10",
            "bg-card": "#1f171c",
            "bg-raised": "#261d23",
            "bg-button": "#2d232a",
            "bg-hover": "#372b33",
            "bg-off": "#1a1418",
            "bg-off2": "#161115",
            "line-1": "#33262e",
            "line-2": "#4d3a46",
            "line-sep": "#382a33",
            "fg-title": "#fff5f9",
            "fg-0": "#faeaf2",
            "fg-1": "#e2c6d4",
            "fg-2": "#a98c9b",
            "fg-3": "#7c6371",
            "fg-off": "#5f4c58",
            "accent": "#ff6fa5",
            "accent-strong": "#d95087",
            "accent-hover": "#ff8fb9",
            "accent-press": "#b93c6e",
            "accent-dim": "#e85f96",
            "accent-bg": "#2b1722",
            "accent-line": "#5c2f43",
            "on-accent": "#1a0510",
        },
    },
    "snow": {
        "name": "粉白",
        "author": "内置",
        "desc": "浅底粉调，白天用最舒服；状态色也一起压深了，浅底上不乱",
        "colors": {
            "bg-page": "#fbf6f8",
            "bg-sunken": "#f4edf1",
            "bg-card": "#ffffff",
            "bg-raised": "#fffbfd",
            "bg-button": "#f8f0f4",
            "bg-hover": "#efdfe7",
            "bg-off": "#f6eff3",
            "bg-off2": "#fbf5f8",
            "line-1": "#e9dbe2",
            "line-2": "#cfb8c3",
            "line-sep": "#e3d3db",
            "fg-title": "#241a20",
            "fg-0": "#2b2228",
            "fg-1": "#4a3d45",
            "fg-2": "#7a6771",
            "fg-3": "#9c8a94",
            "fg-off": "#b3a2ab",
            "accent": "#e5447c",
            "accent-strong": "#c62f68",
            "accent-hover": "#f0638f",
            "accent-press": "#ad2557",
            "accent-dim": "#d8447a",
            "accent-bg": "#fde7ee",
            "accent-line": "#f6c2d3",
            "on-accent": "#ffffff",
            "state-danger": "#c62d2d",
            "state-alert": "#b26a00",
            "state-warn": "#8a6d00",
            "state-info": "#6b5bd2",
            "state-ok": "#1f8a5f",
        },
    },
    "gold": {
        "name": "暗金",
        "author": "内置",
        "desc": "黑底镀金，字偏暖，夜里看眼睛没那么累",
        "colors": {
            "bg-page": "#12100c",
            "bg-sunken": "#0c0a07",
            "bg-card": "#1a1710",
            "bg-raised": "#221d14",
            "bg-button": "#2a2418",
            "bg-hover": "#332b1c",
            "bg-off": "#16130d",
            "bg-off2": "#12100b",
            "line-1": "#2e2718",
            "line-2": "#4a3f26",
            "line-sep": "#332b1a",
            "fg-title": "#fdf6e6",
            "fg-0": "#f5ecd8",
            "fg-1": "#d6c9ad",
            "fg-2": "#9d8f76",
            "fg-3": "#6f6552",
            "fg-off": "#544b3d",
            "accent": "#e8b53a",
            "accent-strong": "#c9962a",
            "accent-hover": "#f0c455",
            "accent-press": "#a87d1f",
            "accent-dim": "#b8862a",
            "accent-bg": "#2a2110",
            "accent-line": "#5a4519",
            "on-accent": "#1a1206",
        },
    },
    "black": {
        "name": "纯黑",
        "author": "内置",
        "desc": "黑白两色，不看颜色只看字，OLED 屏省电",
        "colors": {
            "bg-page": "#000000",
            "bg-sunken": "#000000",
            "bg-card": "#0a0a0a",
            "bg-raised": "#111111",
            "bg-button": "#161616",
            "bg-hover": "#1e1e1e",
            "bg-off": "#080808",
            "bg-off2": "#050505",
            "line-1": "#1c1c1c",
            "line-2": "#2e2e2e",
            "line-sep": "#181818",
            "fg-title": "#ffffff",
            "fg-0": "#f0f0f0",
            "fg-1": "#c8c8c8",
            "fg-2": "#8a8a8a",
            "fg-3": "#5a5a5a",
            "fg-off": "#3a3a3a",
            "accent": "#d8d8d8",
            "accent-strong": "#e8e8e8",
            "accent-hover": "#ffffff",
            "accent-press": "#c0c0c0",
            "accent-dim": "#b0b0b0",
            "accent-bg": "#1a1a1a",
            "accent-line": "#2e2e2e",
            "on-accent": "#0a0a0a",
        },
    },
}

DEFAULT_KEY = "cyber"

# 老代码里写死的色值 → 语义名。留着这张表，152 处内联样式不用逐个手改，
# 调用时自动翻译成当前皮肤的值。表里没有的（红黄紫绿那些状态色）原样不动。
LEGACY: Dict[str, str] = {
    # 主色系
    "#20ffe0": "accent",
    "#19e0d0": "accent",
    "#23e2c8": "accent",
    "#37e6cd": "accent",
    "#5fd9c8": "accent-dim",
    "#79c3b9": "accent-dim",
    "#17c8a8": "accent-strong",
    "#24e3be": "accent-hover",
    "#12b295": "accent-press",
    "#14c2a4": "accent-dim",
    "#102a27": "accent-bg",
    "#10302c": "accent-bg",
    "#16202a": "accent-bg",
    "#16323a": "accent-bg",
    "#1c4a43": "accent-line",
    "#1c5049": "accent-line",
    "#225a52": "accent-line",
    "#1f3a3a": "accent-line",
    "#75551b": "accent-line",
    "#04120f": "on-accent",
    # 背景
    "#0e1015": "bg-page",
    "#0b0e13": "bg-sunken",
    "#0b0f15": "bg-sunken",
    "#0d1319": "bg-sunken",
    "#0f131a": "bg-sunken",
    "#101620": "bg-sunken",
    "#101720": "bg-sunken",
    "#12161d": "bg-sunken",
    "#10141b": "bg-off2",
    "#10131a": "bg-off2",
    "#141822": "bg-off",
    "#151b24": "bg-off",
    "#161a22": "bg-card",
    "#171c26": "bg-card",
    "#121a24": "bg-card",
    "#152129": "bg-card",
    "#151119": "bg-card",
    "#1a1f29": "bg-raised",
    "#171c25": "bg-raised",
    "#171d26": "bg-raised",
    "#151a23": "bg-raised",
    "#212936": "bg-raised",
    "#16222c": "bg-raised",
    "#1b212b": "bg-button",
    "#1b2230": "bg-button",
    "#1e242f": "bg-button",
    "#191f29": "bg-button",
    "#262e3c": "bg-hover",
    "#242c39": "bg-hover",
    "#171d28": "bg-hover",
    # 描边
    "#2c3543": "line-1",
    "#232a36": "line-1",
    "#1f2632": "line-1",
    "#242b38": "line-1",
    "#252d3b": "line-1",
    "#2a3341": "line-1",
    "#2c3444": "line-1",
    "#2b3546": "line-1",
    "#191e27": "line-1",
    "#181d26": "line-1",
    "#232b38": "line-1",
    "#3a4455": "line-2",
    "#35455c": "line-2",
    "#33445a": "line-2",
    "#334052": "line-2",
    "#3a4557": "line-2",
    "#262d3a": "line-sep",
    "#2a3240": "line-sep",
    # 文字
    "#f6f9fe": "fg-title",
    "#f0f4fa": "fg-0",
    "#eef3fb": "fg-0",
    "#e6ebf3": "fg-0",
    "#e2e7f0": "fg-0",
    "#dbe3ee": "fg-0",
    "#eaf8f6": "fg-0",
    "#c9cfda": "fg-1",
    "#dfe5ef": "fg-1",
    "#cfd6e2": "fg-1",
    "#b6c1d0": "fg-1",
    "#c6cede": "fg-1",
    "#c9d2e0": "fg-1",
    "#c9d3e0": "fg-1",
    "#7b8494": "fg-2",
    "#9aa4b4": "fg-2",
    "#8b95a5": "fg-2",
    "#6d7686": "fg-2",
    "#9aa5b7": "fg-2",
    "#8c97a8": "fg-2",
    "#6b7488": "fg-2",
    "#7e8798": "fg-2",
    "#6f7a8c": "fg-2",
    "#8d97a8": "fg-2",
    "#69737f": "fg-2",
    "#94a3b2": "fg-2",
    "#5f6878": "fg-3",
    "#5f6b7c": "fg-3",
    "#5d6676": "fg-3",
    "#4d5563": "fg-off",
    "#525b69": "fg-off",
    "#4f5764": "fg-off",
}

_RE_HEX = re.compile(r"#[0-9a-fA-F]{6}")
_RE_ACCENT_RGBA = re.compile(r"rgba\(32,\s*255,\s*224,\s*")


def _hex_to_rgb(value: str) -> Tuple[int, int, int]:
    v = (value or "#000000").lstrip("#")
    if len(v) == 3:
        v = "".join(c * 2 for c in v)
    try:
        return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
    except (ValueError, IndexError):
        return 32, 255, 224


class Theme:
    """当前生效的一套皮肤"""

    def __init__(self, key: str, data: dict) -> None:
        self.key = key
        self.name = str(data.get("name") or key)
        self.author = str(data.get("author") or "")
        self.desc = str(data.get("desc") or "")

        colors = dict(FIXED)
        raw = data.get("colors") or {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if isinstance(v, str) and v.strip():
                    colors[str(k).strip()] = v.strip()
        # 该有的一个都不能少，缺哪补哪，补不上就用内置那套
        base = BUILTIN[DEFAULT_KEY]["colors"]
        for k, v in base.items():
            colors.setdefault(k, v)
        self.colors = colors

        radius = dict(_DEFAULT_RADIUS)
        raw_r = data.get("radius") or {}
        if isinstance(raw_r, dict):
            for k, d in _DEFAULT_RADIUS.items():
                try:
                    radius[k] = max(0, min(40, int(raw_r.get(k, d))))
                except (TypeError, ValueError):
                    radius[k] = d
        self.radius = radius
        # 运行时临时覆盖（开着立绘时把底色透一点），不动磁盘上的皮肤文件
        self.overrides: Dict[str, str] = {}

    # ---------- 取用 ----------
    def color(self, token: str, fallback: str = "") -> str:
        return self.value(token, fallback)

    def value(self, token: str, fallback: str = "") -> str:
        """取一个 token 的当前值：先看运行时覆盖，再看皮肤本身。"""
        if token in self.overrides:
            return self.overrides[token]
        return self.colors.get(token, fallback)

    def render(self, text: str) -> str:
        """把 @token 换成实际值；@radius-sm 之类换成数字。"""
        if not text or "@" not in text:
            return text

        def sub(m: "re.Match[str]") -> str:
            name = m.group(1)
            if name.startswith("radius-"):
                return str(self.radius.get(name[7:], 8))
            if name == "accent-rgb":
                # 半透明主色要写成 rgba(@accent-rgb, 0.08)
                r, g, b = _hex_to_rgb(self.value("accent", "#20ffe0"))
                return f"{r}, {g}, {b}"
            return self.value(name, m.group(0))

        return re.sub(r"@([a-z0-9-]+)", sub, text)

    def recolor(self, text: str) -> str:
        """老代码里写死的色值 → 当前皮肤对应的值。表里没有的原样返回。"""
        if not text or "#" not in text:
            return text
        colors = self.colors

        def sub(m: "re.Match[str]") -> str:
            token = LEGACY.get(m.group(0).lower())
            if not token:
                return m.group(0)
            return self.value(token, m.group(0))

        out = _RE_HEX.sub(sub, text)
        # 主色的半透明写法（按钮底色那种）也要跟着换
        r, g, b = _hex_to_rgb(self.value("accent", "#20ffe0"))
        return _RE_ACCENT_RGBA.sub(f"rgba({r}, {g}, {b}, ", out)


# ---------- 加载 ----------
_cache: Optional[Dict[str, Theme]] = None
_current: Optional[Theme] = None


def themes_dir() -> Path:
    return app_dir() / "themes"


def _read_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("皮肤文件读不了，已跳过：%s（%s）", path.name, exc)
        return None
    if not isinstance(data, dict):
        log.warning("皮肤文件格式不对，已跳过：%s", path.name)
        return None
    return data


def scan(force: bool = False) -> Dict[str, Theme]:
    """内置三套 + themes/*.json。同名文件覆盖内置，方便自己想改就改。"""
    global _cache
    if _cache is not None and not force:
        return _cache

    found: Dict[str, Theme] = {}
    for key, data in BUILTIN.items():
        try:
            found[key] = Theme(key, data)
        except Exception as exc:  # noqa: BLE001
            log.error("内置皮肤建不起来：%s（%s）", key, exc)

    folder = themes_dir()
    if folder.is_dir():
        for path in sorted(folder.glob("*.json")):
            data = _read_json(path)
            if not data:
                continue
            key = str(data.get("key") or path.stem).strip() or path.stem
            try:
                found[key] = Theme(key, data)
            except Exception as exc:  # noqa: BLE001
                log.warning("皮肤 %s 建不起来，已跳过（%s）", path.name, exc)

    _cache = found
    return found


def available() -> List[Theme]:
    """按名字排序，内置的三套永远在前"""
    themes = scan()
    order = list(BUILTIN.keys())
    rest = [k for k in themes if k not in order]
    return [themes[k] for k in order if k in themes] + [themes[k] for k in rest]


def current() -> Theme:
    global _current
    if _current is None:
        _current = scan().get(DEFAULT_KEY) or Theme(DEFAULT_KEY, BUILTIN[DEFAULT_KEY])
    return _current


def set_current(key: str) -> Theme:
    """切到某套皮肤。key 不存在就回落默认，绝不报错。"""
    global _current
    themes = scan()
    hit = themes.get(key) or themes.get(DEFAULT_KEY)
    if hit is None:
        hit = Theme(DEFAULT_KEY, BUILTIN[DEFAULT_KEY])
    _current = hit
    return hit


def set_overrides(colors: Dict[str, str]) -> None:
    """临时盖几个 token 的值（开立绘时让卡片透一点），不写进配置文件。"""
    current().overrides = dict(colors or {})


def recolor(text: str) -> str:
    """给内联样式用：写死的色值自动翻成当前皮肤的。"""
    return current().recolor(text)


def render(text: str) -> str:
    """给样式表模板用：@token 换成当前皮肤的值。"""
    return current().render(text)


def write_sample(folder: Optional[Path] = None) -> Path:
    """导出一份皮肤模板，用户可以照着改。"""
    folder = folder or themes_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "自定义示例.json"
    sample = {
        "key": "custom",
        "name": "我的皮肤",
        "author": "玩家",
        "desc": "照着改颜色就行，圆角不用动",
        "colors": dict(BUILTIN["gold"]["colors"]),
        "radius": dict(_DEFAULT_RADIUS),
    }
    path.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
