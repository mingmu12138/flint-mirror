"""模组接口审计：把 docs/MOD_API.md 里写的每个 host.* 和 core/mod_api.py 里的实现对一遍。

用法：
    .\\.venv313\\Scripts\\python.exe tool\\mod_api_audit.py

检查三件事：
  1. 文档里写了、代码里没有的（照文档写出来的模组一调就 AttributeError）
  2. 代码里有、文档里没写的公开成员（能用但没人知道，十个模组十种写法）
  3. 文档权限表跟 KNOWN_PERMISSIONS 对不上

只读，不改任何文件。改完接口跑一遍，比翻文档快。
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API_PY = ROOT / "core" / "mod_api.py"
DOC_MD = ROOT / "docs" / "MOD_API.md"


def public_methods(node: ast.AST) -> set[str]:
    names = set()
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("_"):
            names.add(child.name)
    return names


def parse_api():
    tree = ast.parse(API_PY.read_text(encoding="utf-8"), filename=str(API_PY))
    classes = {n.name: n for n in tree.body if isinstance(n, ast.ClassDef)}

    host = classes.get("Host")
    if host is None:
        raise SystemExit("core/mod_api.py 里找不到 class Host")

    # Host 上能访问到的东西：__init__ 里所有 self.x = ...
    members: set[str] = set()
    api_attrs: dict[str, str] = {}     # host.log -> _LogApi
    for fn in host.body:
        if isinstance(fn, ast.FunctionDef) and fn.name == "__init__":
            for sub in ast.walk(fn):
                if not isinstance(sub, ast.Assign) or len(sub.targets) != 1:
                    continue
                tgt, val = sub.targets[0], sub.value
                if isinstance(tgt, ast.Attribute) and isinstance(tgt.value, ast.Name) and \
                        tgt.value.id == "self":
                    members.add(tgt.attr)
                    if isinstance(val, ast.Call) and isinstance(val.func, ast.Name) and \
                            val.func.id.startswith("_"):
                        api_attrs[tgt.attr] = val.func.id

    members |= public_methods(host)

    # KNOWN_PERMISSIONS 常量
    perms: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "KNOWN_PERMISSIONS" for t in node.targets):
            perms = [e.value for e in node.value.elts if isinstance(e, ast.Constant)]

    return classes, api_attrs, members, perms


def main() -> int:
    classes, api_attrs, members, code_perms = parse_api()
    doc = DOC_MD.read_text(encoding="utf-8")

    refs: dict[str, set[str]] = {}
    for m in re.finditer(r"host\.([a-z_]+)(?:\.([a-z_]+))?", doc):
        head, leaf = m.group(1), m.group(2)
        refs.setdefault(head, set())
        if leaf:
            refs[head].add(leaf)

    missing: list[str] = []
    for head, leaves in sorted(refs.items()):
        if head not in members:
            missing.append(f"host.{head} —— 文档里有，Host 上不存在")
            continue
        cls = classes.get(api_attrs.get(head, ""))
        if cls is None:
            continue
        have = public_methods(cls)
        for leaf in sorted(leaves):
            if leaf not in have:
                missing.append(f"host.{head}.{leaf}() —— 文档里有，{cls.name} 里没有")

    undocumented: list[str] = []
    for attr, cls_name in sorted(api_attrs.items()):
        cls = classes.get(cls_name)
        if cls is None:
            continue
        for name in sorted(public_methods(cls)):
            if name not in refs.get(attr, set()):
                undocumented.append(f"host.{attr}.{name}  （{cls_name}）")
    for name in sorted(public_methods(classes["Host"])):
        if name not in refs:
            undocumented.append(f"host.{name}()  （Host）")

    print("=" * 60)
    print("一、文档写了、代码没有（照文档写模组会炸）")
    print("=" * 60)
    print("\n".join("  [缺] " + x for x in missing) if missing else "  无。每个 host.* 都能在代码里找到。")

    print()
    print("=" * 60)
    print("二、代码有、文档没写（公开成员但没人知道）")
    print("=" * 60)
    print("\n".join("  [缺文档] " + x for x in undocumented) if undocumented else "  无。所有公开成员都在文档里出现过。")

    print()
    print("=" * 60)
    print("三、权限名对齐")
    print("=" * 60)
    doc_perms = set(re.findall(r"\| `(notify|ui\.page|hotkey|shell|events|schedule|fs\.data)` \|", doc))
    print("  代码 KNOWN_PERMISSIONS：" + ("、".join(code_perms) or "未解析到"))
    print("  文档权限表：        " + ("、".join(sorted(doc_perms)) or "未解析到"))
    only_code = set(code_perms) - doc_perms
    only_doc = doc_perms - set(code_perms)
    if only_code:
        print("  [只在代码里] " + "、".join(sorted(only_code)))
    if only_doc:
        print("  [只在文档里] " + "、".join(sorted(only_doc)))
    if not only_code and not only_doc:
        print("  一致。")

    ok = not missing and not undocumented and not only_code and not only_doc
    print()
    print("结论：" + ("接口和文档一致，可以对外。" if ok else "见上面标出的条目，改完再发。"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
