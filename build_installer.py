# -*- utf-8 -*-
"""一条命令出安装包：先跑 build_dist.py，再编 NSIS。

版本号只认 version.txt —— 编译前自动同步到 installer.nsi，
所以不会出现"界面写着 1.1.0、安装包版本还是 1.0"这种自己认不出新版的情况。
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NSIS = ROOT / "_nsis" / "nsis-3.11" / "makensis.exe"
SRC = ROOT / "分发版" / "燧镜"

if not SRC.exists():
    sys.exit("没有 分发版\\燧镜，先跑 build_dist.py")

if not NSIS.exists():
    sys.exit("没有 NSIS，先跑 _i1_getnsis.py 下载（或手动解压到 _nsis）")

# 1) 版本号同步（幂等，跑多少次都一样）
rc = subprocess.run(
    [sys.executable, str(ROOT / "sync_version.py")], cwd=str(ROOT)
).returncode
if rc != 0:
    sys.exit("版本号同步失败")

ver = (ROOT / "version.txt").read_text(encoding="utf-8").strip()
out_name = f"燧镜_v{ver}_安装包.exe"

# 2) 编译前重写 BOM（NSIS 对带 BOM 的 UTF-8 才认中文）
nsi = ROOT / "installer.nsi"
nsi.write_text(nsi.read_text(encoding="utf-8-sig"), encoding="utf-8-sig")

rc = subprocess.run([str(NSIS), "/V2", str(nsi)], cwd=str(ROOT)).returncode
out = ROOT / out_name
print("退出码", rc)
if out.exists():
    print(f"安装包：{out}  {out.stat().st_size / 1024 / 1024:.1f} MB")
else:
    # 万一文件名对不上，兜一层
    cands = sorted(ROOT.glob("燧镜_v*_安装包.exe"))
    if cands:
        print(f"安装包：{cands[-1]}  {cands[-1].stat().st_size / 1024 / 1024:.1f} MB")
    else:
        sys.exit(f"没找到 {out_name}")
