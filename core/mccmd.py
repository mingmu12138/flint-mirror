# -*- coding: utf-8 -*-
"""MC 指令生成：快捷指令 / NBT 双语法 / 区域填充。

这一层只做一件事：把参数拼成一条正确的指令文本。
不读取游戏、不判断世界状态、不改存档 —— 拼完交给 input_send 去"按 Ctrl+V"。

语法分两套，因为 1.20.5 把 NBT 换成了「组件」：
  · modern（1.20.5+）：/give @p minecraft:diamond_sword[minecraft:custom_name='"名字"',minecraft:enchantments={levels:{...}}]
  · legacy（≤1.20.4）：/give @p minecraft:diamond_sword{display:{Name:'{"text":"名字"}'},Enchantments:[{id:...,lvl:..}]}
选错了游戏会直接报语法错误，所以界面上要能切。
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Sequence, Tuple

# Java 版 /fill 一次最多 32768 个方块（1.13+ 的硬限制）
FILL_LIMIT = 32768

# (显示名, 物品 id)
ITEMS: Tuple[Tuple[str, str], ...] = (
    ("钻石剑", "minecraft:diamond_sword"),
    ("下界合金剑", "minecraft:netherite_sword"),
    ("钻石镐", "minecraft:diamond_pickaxe"),
    ("下界合金镐", "minecraft:netherite_pickaxe"),
    ("钻石斧", "minecraft:diamond_axe"),
    ("弓", "minecraft:bow"),
    ("弩", "minecraft:crossbow"),
    ("箭", "minecraft:arrow"),
    ("盾牌", "minecraft:shield"),
    ("金苹果", "minecraft:golden_apple"),
    ("附魔金苹果", "minecraft:enchanted_golden_apple"),
    ("不死图腾", "minecraft:totem_of_undying"),
    ("末影珍珠", "minecraft:ender_pearl"),
    ("鞘翅", "minecraft:elytra"),
    ("三叉戟", "minecraft:trident"),
    ("钻石", "minecraft:diamond"),
    ("下界合金锭", "minecraft:netherite_ingot"),
    ("铁锭", "minecraft:iron_ingot"),
    ("绿宝石", "minecraft:emerald"),
    ("火药", "minecraft:gunpowder"),
    ("末影之眼", "minecraft:ender_eye"),
    ("命令方块", "minecraft:command_block"),
    ("屏障", "minecraft:barrier"),
    ("基岩", "minecraft:bedrock"),
    ("玻璃", "minecraft:glass"),
    ("火把", "minecraft:torch"),
    ("水桶", "minecraft:water_bucket"),
    ("岩浆桶", "minecraft:lava_bucket"),
)

# (显示名, 附魔 id, 最高等级)
ENCHANTS: Tuple[Tuple[str, str, int], ...] = (
    ("锋利", "minecraft:sharpness", 5),
    ("亡灵杀手", "minecraft:smite", 5),
    ("节肢杀手", "minecraft:bane_of_arthropods", 5),
    ("击退", "minecraft:knockback", 2),
    ("火焰附加", "minecraft:fire_aspect", 2),
    ("抢夺", "minecraft:looting", 3),
    ("耐久", "minecraft:unbreaking", 3),
    ("经验修补", "minecraft:mending", 1),
    ("保护", "minecraft:protection", 4),
    ("爆炸保护", "minecraft:blast_protection", 4),
    ("火焰保护", "minecraft:fire_protection", 4),
    ("摔落保护", "minecraft:feather_falling", 4),
    ("荆棘", "minecraft:thorns", 3),
    ("水下呼吸", "minecraft:respiration", 3),
    ("深海探索者", "minecraft:depth_strider", 3),
    ("迅捷潜行", "minecraft:swift_sneak", 3),
    ("灵魂疾行", "minecraft:soul_speed", 3),
    ("效率", "minecraft:efficiency", 5),
    ("时运", "minecraft:fortune", 3),
    ("精准采集", "minecraft:silk_touch", 1),
    ("力量", "minecraft:power", 5),
    ("无限", "minecraft:infinity", 1),
    ("冲击", "minecraft:punch", 2),
    ("穿透", "minecraft:piercing", 4),
    ("多重射击", "minecraft:multishot", 1),
    ("快速装填", "minecraft:quick_charge", 3),
    ("饵钓", "minecraft:lure", 3),
    ("海之眷顾", "minecraft:luck_of_the_sea", 3),
    ("忠诚", "minecraft:loyalty", 3),
    ("引雷", "minecraft:channeling", 1),
)

# (显示名, 方块 id)
BLOCKS: Tuple[Tuple[str, str], ...] = (
    ("空气", "minecraft:air"),
    ("石头", "minecraft:stone"),
    ("圆石", "minecraft:cobblestone"),
    ("泥土", "minecraft:dirt"),
    ("草方块", "minecraft:grass_block"),
    ("沙子", "minecraft:sand"),
    ("砂岩", "minecraft:sandstone"),
    ("橡木木板", "minecraft:oak_planks"),
    ("玻璃", "minecraft:glass"),
    ("荧石", "minecraft:glowstone"),
    ("海晶灯", "minecraft:sea_lantern"),
    ("萤石", "minecraft:shroomlight"),
    ("下界岩", "minecraft:netherrack"),
    ("水", "minecraft:water"),
    ("岩浆", "minecraft:lava"),
    ("屏障", "minecraft:barrier"),
    ("基岩", "minecraft:bedrock"),
    ("命令方块", "minecraft:command_block"),
    ("火把", "minecraft:torch"),
    ("羊毛", "minecraft:white_wool"),
)

# 快捷指令：group = world（世界/自己） / clean（清理，多半带危险）
QUICK: Tuple[Dict[str, object], ...] = (
    {"label": "切创造", "cmd": "/gamemode creative @s", "danger": False, "group": "world"},
    {"label": "切生存", "cmd": "/gamemode survival @s", "danger": False, "group": "world"},
    {"label": "切旁观", "cmd": "/gamemode spectator @s", "danger": False, "group": "world"},
    {"label": "白天", "cmd": "/time set day", "danger": False, "group": "world"},
    {"label": "黑夜", "cmd": "/time set night", "danger": False, "group": "world"},
    {"label": "正午", "cmd": "/time set noon", "danger": False, "group": "world"},
    {"label": "晴天", "cmd": "/weather clear", "danger": False, "group": "world"},
    {"label": "下雨", "cmd": "/weather rain", "danger": False, "group": "world"},
    {"label": "雷雨", "cmd": "/weather thunder", "danger": False, "group": "world"},
    {"label": "死亡不掉落·开", "cmd": "/gamerule keepInventory true", "danger": False, "group": "world"},
    {"label": "死亡不掉落·关", "cmd": "/gamerule keepInventory false", "danger": False, "group": "world"},
    {"label": "和平难度", "cmd": "/difficulty peaceful", "danger": True, "group": "world"},
    {"label": "普通难度", "cmd": "/difficulty normal", "danger": True, "group": "world"},
    {"label": "回满血", "cmd": "/effect give @s minecraft:instant_health 2 255 true",
     "danger": False, "group": "world"},
    {"label": "吃饱", "cmd": "/effect give @s minecraft:saturation 2 20 true",
     "danger": False, "group": "world"},
    {"label": "清掉落物", "cmd": "/kill @e[type=minecraft:item]", "danger": True, "group": "clean"},
    {"label": "清怪（不含玩家）", "cmd": "/kill @e[type=!minecraft:player]", "danger": True, "group": "clean"},
    {"label": "清空背包", "cmd": "/clear @s", "danger": True, "group": "clean"},
    {"label": "设重生点", "cmd": "/spawnpoint @s ~ ~ ~", "danger": False, "group": "clean"},
    {"label": "回世界中心高空", "cmd": "/tp @s 0 120 0", "danger": True, "group": "clean"},
    {"label": "存档同步刷盘", "cmd": "/save-all flush", "danger": False, "group": "clean"},
)

# 自由输入的指令按前缀判危险：这些一动就是删东西 / 传人 / 停服
DANGER_PREFIXES = (
    "/kill", "/clear", "/fill", "/setblock", "/tp", "/teleport",
    "/ban", "/op", "/deop", "/stop", "/difficulty", "/forceload",
    "/clone", "/data merge", "/summon",
)


def normalize_name(name: str) -> str:
    """自定义名字里的引号要处理：单引号换成全角，双引号转义。

    NBT 那套把名字包在单引号里，名字里再有单引号会把 SNBT 撕开；
    组件那套名字是 JSON 字符串，双引号必须转义。
    """
    text = str(name or "").strip()
    text = text.replace("\\", "").replace("'", "’")
    text = text.replace('"', '\\"')
    text = text.replace("{", "").replace("}", "")
    return text[:64]


def _enchant_pairs(enchants: Iterable[Tuple[str, int]]) -> List[Tuple[str, int]]:
    out: List[Tuple[str, int]] = []
    for eid, lvl in enchants:
        try:
            lvl = int(lvl)
        except (TypeError, ValueError):
            continue
        if lvl <= 0:
            continue
        out.append((str(eid), min(255, lvl)))
    return out


def give_command(target: str = "@s", item_id: str = "minecraft:diamond_sword",
                 count: int = 1, custom_name: str = "",
                 enchants: Sequence[Tuple[str, int]] = (),
                 modern: bool = True) -> str:
    """拼 /give。modern=True 是 1.20.5+ 的组件语法，False 是旧 NBT 语法。"""
    target = (target or "@s").strip() or "@s"
    item = (item_id or "minecraft:stone").strip()
    try:
        count = max(1, min(640, int(count)))
    except (TypeError, ValueError):
        count = 1
    name = normalize_name(custom_name)
    pairs = _enchant_pairs(enchants)

    if modern:
        parts: List[str] = []
        if name:
            parts.append('minecraft:custom_name=\'"%s"\'' % name)
        if pairs:
            levels = ",".join('"%s":%d' % (eid, lvl) for eid, lvl in pairs)
            parts.append("minecraft:enchantments={levels:{%s}}" % levels)
        if parts:
            return "/give %s %s[%s] %d" % (target, item, ",".join(parts), count)
        return "/give %s %s %d" % (target, item, count)

    nbt: List[str] = []
    if name:
        nbt.append("display:{Name:'{\"text\":\"%s\",\"italic\":false}'}" % name)
    if pairs:
        items = ",".join('{id:"%s",lvl:%d}' % (eid, lvl) for eid, lvl in pairs)
        nbt.append("Enchantments:[%s]" % items)
    if nbt:
        return "/give %s %s{%s} %d" % (target, item, ",".join(nbt), count)
    return "/give %s %s %d" % (target, item, count)


def _num(text: str, default: int = 0) -> int:
    try:
        return int(str(text).strip())
    except (TypeError, ValueError):
        return default


def parse_box(text: str) -> Optional[List[int]]:
    """把「x y z」或「x,y,z」解析成三个整数；不合规返回 None。"""
    raw = str(text or "").replace(",", " ").replace("，", " ").split()
    if len(raw) != 3:
        return None
    try:
        return [int(raw[0]), int(raw[1]), int(raw[2])]
    except (TypeError, ValueError):
        return None


def box_volume(a: Sequence[int], b: Sequence[int]) -> int:
    if len(a) < 3 or len(b) < 3:
        return 0
    dx = abs(int(b[0]) - int(a[0])) + 1
    dy = abs(int(b[1]) - int(a[1])) + 1
    dz = abs(int(b[2]) - int(a[2])) + 1
    return dx * dy * dz


def fill_command(p1: Sequence[int], p2: Sequence[int], block: str,
                 old_block: str = "", mode: str = "fill") -> str:
    """mode=fill → /fill（带 replace 过滤）；mode=replace → WorldEdit //replace。"""
    x1, y1, z1 = (int(v) for v in list(p1)[:3])
    x2, y2, z2 = (int(v) for v in list(p2)[:3])
    new = (block or "minecraft:stone").strip()
    old = (old_block or "").strip()
    if mode == "replace":
        # //replace <原方块> <新方块>；范围由你手里那把木斧选区决定
        if old:
            return "//replace %s %s" % (old, new)
        return "//replace %s" % new
    if old:
        return "/fill %d %d %d %d %d %d %s replace %s" % (x1, y1, z1, x2, y2, z2, new, old)
    return "/fill %d %d %d %d %d %d %s" % (x1, y1, z1, x2, y2, z2, new)


def fill_advice(volume: int, mode: str = "fill") -> Tuple[bool, str]:
    """返回 (能不能直接发, 提示文字)。"""
    if mode == "replace":
        return True, "WorldEdit 不限体积，但得先拿木斧选好区域"
    if volume > FILL_LIMIT:
        return False, "这块 %d 格，超过 /fill 一次 %d 格的上限——拆成几次填，或者换 //replace" % (
            volume, FILL_LIMIT)
    if volume > 20000:
        return True, "%d 格，离上限 %d 不远了，游戏会卡一下" % (volume, FILL_LIMIT)
    return True, "%d 格" % volume


def is_dangerous(cmd: str) -> Tuple[bool, str]:
    """自由输入的指令该不该先问一句。"""
    text = " " + (cmd or "").strip().lower() + " "
    if not text.strip().startswith("/"):
        # 不带斜杠的多半是聊天内容，不拦
        return False, ""
    for pre in DANGER_PREFIXES:
        if text.lstrip().startswith(pre):
            return True, "这条会真的改动世界 / 踢人 / 停服"
    for word in (" kill ", " clear ", " fill ", " setblock ", " tp ", " stop "):
        if word in text:
            return True, "里面带 %s" % word.strip()
    return False, ""
