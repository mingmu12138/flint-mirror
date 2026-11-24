"""把模组文件夹打成 .sjmod 包。

用法：
    .\\.venv313\\Scripts\\python.exe tool\\make_sjmod.py 我的模组文件夹

做的事：校验 manifest → 检查入口文件 → 按 UTF-8 打包（跳过 __pycache__）→ 打印结果。

产出落在源文件夹旁边：<文件夹名>.sjmod
"""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from core.mod_api import MOD_SUFFIX, ManifestError, parse_manifest, read_manifest
except Exception as e:  # pragma: no cover
    print(f"导入 core.mod_api 失败：{e}")
    raise SystemExit(1)

SKIP_DIRS = {"__pycache__", ".git", ".idea", ".vscode"}
SKIP_SUFFIX = {".pyc", ".pyo", ".sjmod"}


def iter_files(root: Path):
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if p.suffix.lower() in SKIP_SUFFIX:
            continue
        yield p, rel


def main(argv) -> int:
    if len(argv) < 2:
        print("用法：python tool\\make_sjmod.py <模组文件夹>")
        return 2

    src = Path(argv[1]).resolve()
    if not src.is_dir():
        print(f"不是文件夹：{src}")
        return 2

    # 1. manifest 校验
    try:
        raw = read_manifest(src)
        spec = parse_manifest(raw, src)
    except ManifestError as e:
        print(f"[manifest 不合格] {e}")
        return 1

    if spec.kind == "external":
        exe = Path(spec.resolved_external)
        if not exe.exists():
            print(f"[警告] 外部程序不在包里也不在本机：{exe}")
            print("       如果是故意的（让用户自己放），忽略这条；否则把它放进包的 bin\\ 下")
    else:
        entry = src / spec.entry
        if not entry.exists():
            print(f"[错误] 入口文件不存在：{entry}")
            return 1

    # 2. 打包
    out = src.parent / f"{src.name}{MOD_SUFFIX}"
    files = list(iter_files(src))
    if not files:
        print("[错误] 文件夹是空的")
        return 1

    try:
        with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for p, rel in files:
                zf.write(p, arcname=str(rel).replace("\\", "/"))
    except OSError as e:
        print(f"[错误] 写包失败：{e}")
        return 1

    size = out.stat().st_size
    print()
    print(f"打包完成：{out.name}")
    print(f"  模组：{spec.name}（{spec.id}）v{spec.version}  kind={spec.kind}")
    print(f"  权限：{'、'.join(spec.permissions) or '无'}")
    print(f"  文件：{len(files)} 个，{size / 1024:.1f} KB")
    for p, rel in files:
        print(f"    + {rel}")
    print()
    print("下一步：把这个 .sjmod 拖进燧镜的「模组」页，或者用 mod_test.py 先自检一遍。")
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    raise SystemExit(main(sys.argv))
