"""只读自检一个 .sjmod 包，不会安装到模组目录。

用法：
    .\\.venv313\\Scripts\\python.exe tool\\mod_test.py 我的模组.sjmod

检查项：
    1. 是不是合法 zip
    2. manifest 在不在最外层
    3. 必填字段、id 格式、apiVersion、权限名
    4. 入口文件在不在包里
    5. 有没有夹带不该有的东西（exe 混进 package 包 / pyc / 超体积）
"""

from __future__ import annotations

import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from core.mod_api import (
        KIND_EXTERNAL,
        KIND_PACKAGE,
        MANIFEST_NAME,
        MOD_SUFFIX,
        ManifestError,
        load_spec,
    )
except Exception as e:  # pragma: no cover
    print(f"导入 core.mod_api 失败：{e}")
    raise SystemExit(1)

WARN_SIZE_MB = 30.0
BIG_SIZE_MB = 120.0


def main(argv) -> int:
    if len(argv) < 2:
        print("用法：python tool\\mod_test.py <某个.sjmod>")
        return 2

    pkg = Path(argv[1]).resolve()
    if not pkg.exists():
        print(f"文件不存在：{pkg}")
        return 2

    problems = []
    warns = []

    # 1. zip
    try:
        zf = zipfile.ZipFile(pkg)
    except zipfile.BadZipFile:
        print("[失败] 不是合法的 zip 包")
        return 1

    with zf:
        bad = zf.testzip()
        if bad is not None:
            print(f"[失败] 包内文件损坏：{bad}")
            return 1
        names = zf.namelist()

    size_mb = pkg.stat().st_size / 1024 / 1024
    print(f"包：{pkg.name}   {size_mb:.1f} MB   {len(names)} 个条目")

    # 2. manifest 位置
    if MANIFEST_NAME not in names:
        top_dirs = {n.split("/")[0] for n in names if "/" in n}
        hint = ""
        if len(top_dirs) == 1:
            hint = f"（看起来套了一层目录 {list(top_dirs)[0]}/，安装器能纠正，但建议重打）"
        print(f"[失败] 最外层没有 {MANIFEST_NAME} {hint}")
        return 1

    # 3. 解到临时目录做完整校验
    with tempfile.TemporaryDirectory() as tmp:
        try:
            with zipfile.ZipFile(pkg) as z:
                z.extractall(tmp)
        except (OSError, zipfile.BadZipFile) as e:
            print(f"[失败] 解压失败：{e}")
            return 1

        root = Path(tmp)
        if not (root / MANIFEST_NAME).exists():
            subs = [d for d in root.iterdir() if d.is_dir()]
            if len(subs) == 1:
                root = subs[0]

        try:
            spec = load_spec(root, builtin=False)
        except ManifestError as e:
            print(f"[失败] manifest 不合格：{e}")
            return 1

        print(f"  名称：{spec.name}")
        print(f"  id  ：{spec.id}")
        print(f"  版本：{spec.version}   apiVersion={spec.api_version}")
        print(f"  作者：{spec.author}")
        print(f"  类型：{spec.kind}（{spec.kind_label}）")
        print(f"  权限：{'、'.join(spec.permissions) or '无'}")

        # 4. 入口
        if spec.kind == KIND_PACKAGE:
            entry = root / spec.entry
            if not entry.exists():
                problems.append(f"入口文件缺失：{spec.entry}")
            elif entry.stat().st_size == 0:
                problems.append(f"入口文件是空的：{spec.entry}")
        elif spec.kind == KIND_EXTERNAL:
            exe = Path(spec.resolved_external)
            if not exe.exists():
                warns.append(f"外部程序不在包里：{spec.external_path}（用户机器上得有这个文件）")
            if not spec.external_path.lower().endswith((".exe", ".bat", ".cmd")):
                warns.append(f"external.path 不像可执行文件：{spec.external_path}")

        # 5. 夹带检查
        py_files = [n for n in names if n.lower().endswith((".pyc", ".pyo"))]
        if py_files:
            warns.append(f"包里带了编译缓存 {len(py_files)} 个，建议删掉再打")

        if spec.kind == KIND_PACKAGE:
            exes = [n for n in names if n.lower().endswith((".exe", ".dll"))]
            if exes:
                problems.append(
                    "kind=package 的包里不该有 exe/dll（" + "、".join(exes[:3]) + "）"
                    "，要走外部程序请用 kind=external"
                )

        if size_mb > BIG_SIZE_MB:
            problems.append(f"包体积 {size_mb:.0f} MB 偏大，检查一下是不是把整个程序目录打进去了")
        elif size_mb > WARN_SIZE_MB:
            warns.append(f"包体积 {size_mb:.0f} MB 偏大")

    # 结论
    print()
    if problems:
        print("结果：不合格")
        for x in problems:
            print(f"  ✗ {x}")
        for x in warns:
            print(f"  ! {x}")
        return 1

    print("结果：通过，可以装")
    for x in warns:
        print(f"  ! {x}")
    print()
    print("装法：把文件拖进燧镜「模组」页，或点页面上的「安装模组文件」。")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main(sys.argv))
