"""生成"分发版"：一个可以直接打包发给别人的干净副本。

和 App 的区别：
  1. config.json 是空配置 —— 不记录你的分辨率、不带你的模组路径
  2. 对方第一次运行时，程序会自动识别他那台电脑的屏幕分辨率并记下来
  3. 附带一份给对方看的说明和救援 bat

用法：.venv\\Scripts\\python.exe build_dist.py
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "App"
DIST_DIR = ROOT / "分发版"
NAME = "燧镜"
_VER_TXT = ROOT / "version.txt"
_V = _VER_TXT.read_text(encoding="utf-8").strip() if _VER_TXT.exists() else "1.1.0"
VERSION = f"v{_V}"
AUTHOR = "布鲁托是小馋猫"
ZIP_PATH = ROOT / f"{NAME}_{VERSION}_分发版.zip"

def _builtin_mods() -> list:
    """分发版自带的模组：以内置模组表为准，表里有几条就带几条。

    BUNDLED_MODS / BUILTIN_PAGES 是软件启动时给每一台机器补装用的同一张表，
    这里直接读它，避免分发模板跟程序本体各维护一份、越走越偏。
    某个内置文件在 bundled 里不存在就跳过并告警，免得带上一张点不动的卡。
    """
    import sys

    sys.path.insert(0, str(ROOT))
    from core.store import BUNDLED_MODS, BUILTIN_PAGES

    bundled = ROOT / "bundled"
    src_bundled = APP / "bundled"
    if src_bundled.exists():
        bundled = src_bundled

    mods = []
    for name, rel, extra_args in BUNDLED_MODS:
        if not (bundled / rel.split("/", 1)[1]).exists():
            print(f"  ! 内置模组文件缺失，跳过：{rel}")
            continue
        mods.append(
            {
                "id": "builtin-" + __import__("hashlib").md5(rel.encode("utf-8")).hexdigest()[:8],
                "name": name,
                "path": rel,
                "kind": "exe",
                "args": list(extra_args),
                "enabled": True,
                "autostart": False,
                "note": "",
                "delay": 0,
            }
        )
    for name, key, note in BUILTIN_PAGES:
        mods.append(
            {
                "id": f"builtin-{key}",
                "name": name,
                "path": key,
                "kind": "page",
                "args": [],
                "enabled": True,
                "autostart": False,
                "note": note,
                "delay": 0,
            }
        )
    print(f"  内置模组 {len(mods)} 条：{', '.join(m['name'] for m in mods)}")
    return mods


# 使用说明：正文放在 使用说明模板.txt 里，改文案不用动这个脚本，
# 也不用操心反斜杠和花括号转义
README_TEXT = (ROOT / "使用说明模板.txt").read_text(encoding="utf-8")
README_TEXT = README_TEXT.replace("{VERSION}", VERSION).replace("{AUTHOR}", AUTHOR)

RESTORE_BAT = """@echo off
cd /d "%~dp0"

echo ==========================================
echo   强制恢复原生分辨率
echo ==========================================
echo.

if exist "燧镜.exe" (
    "燧镜.exe" --restore
    echo 已恢复原生分辨率。
) else (
    echo [错误] 找不到 燧镜.exe，请确认本文件放在程序目录里。
)

echo.
timeout 4
"""


def write_gbk(path: Path, text: str) -> None:
    """cmd 读 bat / 记事本看 txt 都用 GBK + CRLF 最稳。"""
    crlf = text.replace("\r\n", "\n").replace("\n", "\r\n")
    path.write_bytes(crlf.encode("gbk", errors="replace"))


def source_dir() -> Path | None:
    """打包产物优先用 dist\\燧镜，其次老的 App 副本。"""
    for cand in (ROOT / "dist" / "燧镜", APP):
        if (cand / "燧镜.exe").exists():
            return cand
    return None


def main() -> int:
    src = source_dir()
    if src is None:
        print("[错误] 还没打包。先双击 更新.bat，或单独跑 PyInstaller 出 dist\\燧镜。")
        return 1
    print(f"[信息] 程序本体取自 {src}")

    target = DIST_DIR / NAME
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)

    # 复制程序本体
    shutil.copy2(src / "燧镜.exe", target / "燧镜.exe")
    # 剔除 QtWebEngine 的调试 pak（4 个，解压后 74.8MB，纯开发者用，运行不需要）
    shutil.copytree(
        src / "_internal",
        target / "_internal",
        ignore=shutil.ignore_patterns("*.debug.pak"),
    )

    # 内置模组（口琴可视化曲谱等）跟着一起走；dist 里没有就取源码目录那份
    bundled = src / "bundled"
    if not bundled.exists():
        bundled = ROOT / "bundled"
    if bundled.exists():
        shutil.copytree(bundled, target / "bundled")

    # 内置模组包（.sjmod）：新模组页只认这个格式，跟着一起走
    mods_builtin = ROOT / "mods" / "_builtin"
    if mods_builtin.exists():
        (target / "mods").mkdir(exist_ok=True)
        shutil.copytree(mods_builtin, target / "mods" / "_builtin")
        print(f"[信息] 内置模组包：{len(list(mods_builtin.iterdir()))} 个")

    # 干净配置：不写死分辨率、不带模组
    cfg = {
        "native": [0, 0, 0],
        "target": [1280, 960],
        # True = 首次运行按本机原生分辨率推荐同比例档位（1600×900 / 1920×1080），不会黑边
        "target_auto": True,
        "guide_shown": False,
        # 手机互联服务跟着开机走：装上就能被手机找到，不用每次手动开
        "clip_auto": True,
        "hotkey_enabled": True,
        "close_to_tray": True,
        "tray_tip_shown": False,
        "view_mode": "list",
        "mods": _builtin_mods(),
        "rules": [],
        "autostart": False,
        "stretch": False,
        "gpu_vendor": "auto",
        # 新机器第一次运行：native 留空，由程序自动识别本机原生分辨率
        "machine_tag": "",
        "fps_show": False,
        "fps_side": "right",
        "fps_scale": 20,
        "fps_alpha": 88,
        "fps_click_through": True,
        "fps_pos": [],
        # 外观默认：经典窗口、皮肤走内置赛博青、立绘先关着（用户想要再开）
        "window_mode": "classic",
        "art_show": False,
        # 不预置立绘：之前这里写死成开发时那张样张，升级或换目录安装会把用户的
        # 选择顶掉，看着就像"自带壁纸被换成了测试图"
        "art_file": "",
        "art_blur": 18,
    }
    (target / "config.json").write_text(
        json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 立绘样张不随包走：包里一张图都不带，art 目录留给用户自己放，
    # 免得开发用的样张被当成出厂默认
    (target / "art").mkdir(exist_ok=True)

    # 手机版 App 跟着一起走：所以主页「连接手机」弹窗里的「获取 App」
    # 打开就是程序目录，用户不用另外去哪儿下
    for apk in sorted(ROOT.glob("燧镜手机版_*.apk")):
        shutil.copy2(apk, target / apk.name)
        print(f"[OK] 附带手机版：{apk.name} ({apk.stat().st_size} 字节)")

    # Steam 名字缓存：公开的商品名，跨机器通用。带上它，别人第一次进 Steam 库
    # 就有名字，不用干等接口一个个补（没有也能用，只是先显示 AppID）
    names = ROOT / "steam_names.json"
    if names.exists():
        shutil.copy2(names, target / "steam_names.json")
        print(f"[OK] 附带 Steam 名字缓存：{names.stat().st_size} 字节")

    write_gbk(target / "使用说明.txt", README_TEXT)
    write_gbk(target / "恢复分辨率.bat", RESTORE_BAT)

    # 官网图标缓存：三方工具那排的图标。带上它，别人第一次打开就是官方图标，
    # 不用先等程序自己去官网抓一遍（抓不到会退回首字母方块）
    fav_src = ROOT / "cache" / "favicons"
    if fav_src.is_dir():
        fav_dst = target / "cache" / "favicons"
        fav_dst.mkdir(parents=True, exist_ok=True)
        count = 0
        for f in fav_src.iterdir():
            if f.is_file():
                shutil.copy2(f, fav_dst / f.name)
                count += 1
        print(f"[OK] 附带官网图标缓存：{count} 个文件")

    # 打 zip
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for f in sorted(target.rglob("*")):
            if f.is_file():
                zf.write(f, f.relative_to(DIST_DIR))

    size_mb = ZIP_PATH.stat().st_size / 1024 / 1024
    print(f"[OK] 分发版目录：{target}")
    print(f"[OK] 压缩包：{ZIP_PATH}  ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
