# -*- utf-8 -*-
"""把手机 App 打成 APK（不依赖 gradle，直接用 aapt2 + javac + d8 + apksigner）。

用法：python build_apk.py
产物：项目根 燧镜手机版_v<版本>.apk
说明：构建目录 C:\\Users\\1\\flint-build 是纯英文路径，源码和资源先拷进去再编，
免得 aapt2/javac 在中文路径上翻车。
"""
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(r"C:\Users\1\Desktop\游戏助手")
SRC = ROOT / "_android" / "app"
BUILD = Path(r"C:\Users\1\flint-build")
SDK = Path(r"C:\Users\1\android-sdk")
BT = SDK / "build-tools" / "34.0.0"
JAR_ANDROID = SDK / "platforms" / "android-35" / "android.jar"
JDK = Path(r"C:\Users\1\jdk17")
JAVAC = JDK / "bin" / "javac.exe"
AAPT2 = BT / "aapt2.exe"
D8 = BT / "d8.bat"
ZIPALIGN = BT / "zipalign.exe"
APKSIGNER = BT / "apksigner.bat"
KS = BUILD / "flint.jks"
ZXING = BUILD / "zxing.jar"
CORE = BUILD / "core.jar"

ENV = dict(os.environ)
ENV["JAVA_HOME"] = str(JDK)
ENV["PATH"] = str(JDK / "bin") + os.pathsep + str(BT) + os.pathsep + ENV.get("PATH", "")


def run(cmd, allow_fail=False):
    print(">>", " ".join(str(c) for c in cmd))
    r = subprocess.run([str(c) for c in cmd], cwd=str(BUILD), capture_output=True, env=ENV)
    out = (r.stdout or b"").decode("utf-8", "ignore") + (r.stderr or b"").decode("utf-8", "ignore")
    if out.strip():
        print(out.strip()[-2500:])
    if r.returncode != 0 and not allow_fail:
        sys.exit("失败，退出码 %s" % r.returncode)
    return r.returncode


manifest = (SRC / "AndroidManifest.xml").read_text("utf-8")
ver = re.search(r'android:versionName="([^"]+)"', manifest).group(1)
vcode = re.search(r'android:versionCode="(\d+)"', manifest).group(1)
print("版本:", ver, "versionCode:", vcode)

# 0) 输入全部搬进英文路径
shutil.copy2(SRC / "AndroidManifest.xml", BUILD / "AndroidManifest.xml")
shutil.copy2(ROOT / "_android" / "core-3.5.3.jar", CORE)
for d in ("res", "src", "classes", "dex", "gen"):
    p = BUILD / d
    if p.exists():
        shutil.rmtree(p)
shutil.copytree(SRC / "res", BUILD / "res")
shutil.copytree(SRC / "src", BUILD / "src")
(BUILD / "classes").mkdir()
(BUILD / "dex").mkdir()

# 1) 编资源
res_zip = BUILD / "res.zip"
if res_zip.exists():
    res_zip.unlink()
run([AAPT2, "compile", "--dir", "res", "-o", "res.zip"])

# 2) 链资源 + 清单 -> base.apk
base = BUILD / "base.apk"
if base.exists():
    base.unlink()
run([AAPT2, "link", "-o", "base.apk", "--manifest", "AndroidManifest.xml",
     "-I", JAR_ANDROID, "--min-sdk-version", "24", "--target-sdk-version", "34",
     "--version-code", vcode, "--version-name", ver, "res.zip"])

# 3) javac
srcs = sorted(str(p.relative_to(BUILD)) for p in (BUILD / "src").rglob("*.java"))
run([JAVAC, "-encoding", "UTF-8", "-source", "8", "-target", "8",
     "-cp", "%s;%s;%s" % (JAR_ANDROID, ZXING, CORE),
     "-d", "classes"] + srcs)

# 4) d8 -> classes.dex
classes = sorted(str(p.relative_to(BUILD)) for p in (BUILD / "classes").rglob("*.class"))
run([D8, "--release", "--min-api", "24", "--lib", JAR_ANDROID,
     "--output", "dex"] + classes + [str(ZXING)])

# 5) dex 塞进 apk
unsigned = BUILD / "unsigned.apk"
shutil.copy2(base, unsigned)
with zipfile.ZipFile(unsigned, "a", zipfile.ZIP_DEFLATED) as z:
    z.write(BUILD / "dex" / "classes.dex", "classes.dex")

# 6) 对齐
aligned = BUILD / "aligned.apk"
if aligned.exists():
    aligned.unlink()
run([ZIPALIGN, "-f", "-p", "4", "unsigned.apk", "aligned.apk"])

# 7) 签名
signed = BUILD / "signed.apk"
for f in (signed, Path(str(signed) + ".idsig")):
    if f.exists():
        f.unlink()
run([APKSIGNER, "sign", "--ks", KS, "--ks-pass", "pass:flintmirror",
     "--ks-key-alias", "flint", "--key-pass", "pass:flintmirror",
     "--out", "signed.apk", "aligned.apk"])

out = ROOT / ("燧镜手机版_v%s.apk" % ver)
shutil.copy2(signed, out)
print("\n[OK] %s  %.1f KB" % (out, out.stat().st_size / 1024))
