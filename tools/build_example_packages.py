#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 `examples/packages/<包名>/` 打成安装包 `<包名>-<版本>.zip`（**别手搓**）。

用法：

    python tools/build_example_packages.py                 # 就地生成（写 examples/packages/）
    python tools/build_example_packages.py --out 临时目录   # 只生成到别处（自检用）
    python tools/build_example_packages.py --check         # 只核对现有 zip 是不是最新的

规则：

  · 一个示例包 = `examples/packages/<包名>/`（里面必须有 SKILL.md）；
  · 版本号取 SKILL.md frontmatter 的 `version`，没写就是 `1.0.0`；
  · zip 里**套一层同名文件夹**（`<包名>/SKILL.md`）—— 安装器两种都认，
    但套一层之后别人解压出来也是一个完整的文件夹，不会散一地；
  · 跳过 `__pycache__` / `*.pyc` / `*.bak-*` / `.DS_Store`；
  · **确定性**：文件按名字排序、时间戳固定成 1980-01-01，
    同样的源码每次打出来的 zip 一个字节都不差（自检靠这个核对）。
"""

import argparse
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
EXAMPLES = os.path.join(REPO, "examples", "packages")

# 固定时间戳：zip 里 DOS 时间最早就是 1980-01-01 00:00:00
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)

_SKIP_DIRS = {"__pycache__", ".git", ".idea", ".vscode"}
_SKIP_NAMES = {".DS_Store"}


def _frontmatter(text):
    """SKILL.md 开头 `---` … `---` 那一段 → dict（只认 a: b 这种一行一条）。"""
    lines = (text or "").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    out = {}
    for ln in lines[1:]:
        if ln.strip() in ("---", "..."):
            break
        if ":" in ln:
            k, v = ln.split(":", 1)
            out[k.strip().lower()] = v.strip().strip("\"'")
    return out


def _version(pkg_dir, name):
    """读 SKILL.md 的 version（没写 / 不是 x.y.z 就用 1.0.0）。"""
    try:
        with open(os.path.join(pkg_dir, "SKILL.md"), encoding="utf-8") as f:
            v = _frontmatter(f.read()).get("version") or ""
    except Exception:
        v = ""
    if re.match(r"^\d+\.\d+\.\d+$", v or ""):
        return v
    return "1.0.0"


def _files(pkg_dir):
    """包里的文件 → 相对路径列表（`/` 分隔、排序）。"""
    out = []
    for d, dirs, names in os.walk(pkg_dir):
        dirs[:] = sorted(x for x in dirs if x not in _SKIP_DIRS and ".bak-" not in x)
        for n in sorted(names):
            if n in _SKIP_NAMES or n.endswith(".pyc") or ".bak-" in n:
                continue
            full = os.path.join(d, n)
            rel = os.path.relpath(full, pkg_dir).replace(os.sep, "/")
            out.append((rel, full))
    out.sort(key=lambda x: x[0])
    return out


def build_one(pkg_dir, out_dir=None):
    """打一个包的 zip。返回 `(zip 路径, 包名, 版本)`。"""
    name = os.path.basename(os.path.abspath(pkg_dir))
    ver = _version(pkg_dir, name)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir or EXAMPLES, "%s-%s.zip" % (name, ver))
    tmp = dest + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel, full in _files(pkg_dir):
            info = zipfile.ZipInfo(filename="%s/%s" % (name, rel),
                                   date_time=_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(full, "rb") as f:
                zf.writestr(info, f.read())
    os.replace(tmp, dest)
    return dest, name, ver


def packages():
    """`examples/packages/` 下的示例包目录（有 SKILL.md 的）。"""
    out = []
    try:
        names = sorted(os.listdir(EXAMPLES))
    except Exception:
        return out
    for n in names:
        d = os.path.join(EXAMPLES, n)
        if os.path.isdir(d) and os.path.isfile(os.path.join(d, "SKILL.md")):
            out.append(d)
    return out


def build_all(out_dir=None):
    """打全部示例包。返回 `[(zip 路径, 包名, 版本)]`。"""
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    return [build_one(d, out_dir) for d in packages()]


def _zip_same(a, b):
    """两个 zip 的**内容**是否一致（忽略时间戳/压缩差异）。

    ⚠ 2026-11-01：以前直接比原始字节 ✗ zip 头里带每个文件的 mtime，
       换个目录、或文件被 scp/rsync 换过 mtime，重打出来的字节就不同 ——
       于是"内容完全一样"却被判成不一致（部署验收时在 VM 上真的踩到了）。
    """
    import zipfile
    try:
        with zipfile.ZipFile(a) as za, zipfile.ZipFile(b) as zb:
            na = sorted(za.namelist())
            nb = sorted(zb.namelist())
            if na != nb:
                return False
            for n in na:
                if za.read(n) != zb.read(n):
                    return False
            return True
    except Exception:
        return False


def check():
    """现有 zip 是不是和源码一致（不一致返回 False）。"""
    import tempfile
    ok = True
    tmp = tempfile.mkdtemp(prefix="pkg-check-")
    try:
        built = build_all(tmp)
        if not built:
            print("✗ examples/packages/ 下没有示例包")
            return False
        for path, name, ver in built:
            want = os.path.join(EXAMPLES, "%s-%s.zip" % (name, ver))
            same = _zip_same(path, want)
            print(("  ✓ " if same else "  ✗ ") + "%s-%s.zip%s"
                  % (name, ver, "" if same else "（和源码不一致：跑一遍 tools/build_example_packages.py）"))
            ok &= same
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description="打示例扩展包的 zip")
    ap.add_argument("--out", default="", help="输出目录（默认 examples/packages）")
    ap.add_argument("--check", action="store_true", help="只核对现有 zip 是否最新")
    args = ap.parse_args(argv)
    if args.check:
        return 0 if check() else 1
    built = build_all(args.out or None)
    for path, name, ver in built:
        print("✓ %s-%s.zip  ←  %s" % (name, ver, os.path.relpath(
            os.path.dirname(path) + os.sep + name, REPO)))
    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    sys.exit(main())
