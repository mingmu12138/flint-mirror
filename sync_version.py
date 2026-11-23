# -*- utf-8 -*-
"""版本号单一源：只改 version.txt，三处自动同步。

- version_info.txt → 决定 燧镜.exe 自己的版本资源（PyInstaller 用）
- installer.nsi 的 APP_VER / APP_VER4 / OutFile → 决定安装包自己的版本资源
  （「检查更新」读的就是安装包这个版本号，漏改会导致永远认不出新版）

用法：python sync_version.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

VERSION_INFO = """VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, 0),
    prodvers=({a}, {b}, {c}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '080404B0',
          [StringStruct('CompanyName', '布鲁托是小馋猫'),
           StringStruct('FileDescription', '燧镜 FLINT MIRROR'),
           StringStruct('FileVersion', '{v4}'),
           StringStruct('InternalName', 'FlintMirror'),
           StringStruct('LegalCopyright', '作者：布鲁托是小馋猫'),
           StringStruct('OriginalFilename', '燧镜.exe'),
           StringStruct('ProductName', '燧镜'),
           StringStruct('ProductVersion', '{v4}')])
      ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""


def read_version() -> str:
    p = ROOT / "version.txt"
    if not p.exists():
        sys.exit("没有 version.txt（里面就写一行版本号，比如 1.1.0）")
    nums = re.findall(r"\d+", p.read_text(encoding="utf-8").strip())
    if not nums:
        sys.exit("version.txt 里没有数字")
    nums = (nums + ["0", "0", "0"])[:3]
    return ".".join(nums)


def main() -> int:
    ver = read_version()
    a, b, c = (int(x) for x in ver.split("."))
    v4 = f"{a}.{b}.{c}.0"

    # 1) version_info.txt
    (ROOT / "version_info.txt").write_text(
        VERSION_INFO.format(a=a, b=b, c=c, v4=v4), encoding="utf-8"
    )
    print(f"OK version_info.txt → {v4}")

    # 2) installer.nsi
    nsi = ROOT / "installer.nsi"
    if not nsi.exists():
        sys.exit("没有 installer.nsi")
    txt = nsi.read_text(encoding="utf-8-sig")
    txt, n1 = re.subn(r'!define APP_VER "[^"]*"', f'!define APP_VER "{ver}"', txt)
    txt, n2 = re.subn(r'!define APP_VER4 "[^"]*"', f'!define APP_VER4 "{v4}"', txt)
    txt, n3 = re.subn(r'OutFile "[^"]*"', f'OutFile "燧镜_v{ver}_安装包.exe"', txt)
    txt, n4 = re.subn(
        r'VIProductVersion "[^"]*"', f'VIProductVersion "{v4}"', txt
    )
    if not (n1 and n2 and n3 and n4):
        sys.exit(f"installer.nsi 替换不完全：{n1},{n2},{n3},{n4}")
    nsi.write_text(txt, encoding="utf-8-sig")
    print(f"OK installer.nsi → APP_VER {ver}，安装包名 燧镜_v{ver}_安装包.exe")

    # 3) gui.py 里给人看的版本号
    gp = ROOT / "gui.py"
    g = gp.read_text(encoding="utf-8")
    g2, n5 = re.subn(
        r'^APP_VERSION = "[^"]*"', f'APP_VERSION = "v{ver}"', g, count=1, flags=re.M
    )
    if n5:
        gp.write_text(g2, encoding="utf-8")
        print(f"OK gui.py → APP_VERSION v{ver}")
    else:
        print("!! gui.py 里没找到 APP_VERSION，界面上的版本号要手动看一眼")
    print(f"\n当前版本：v{ver}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
