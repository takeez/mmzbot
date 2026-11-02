#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""下载语义记忆用的模型（安装流程的一部分，默认要装）。

默认从 GitHub release 拉三个文件到一个数据目录：
    model_quantized.onnx        168 KB   （图）
    model_quantized.onnx_data   23.8 MB  （权重，必须同名同目录）
    tokenizer.json

用法：
    python3 tools/fetch_model.py                  # 下到 <数据目录>/models/bge-small-zh-v1.5-onnx
    python3 tools/fetch_model.py --dir D:\\models  # 指到别处
    python3 tools/fetch_model.py --base https://.../download/model-bge   # 换源（镜像）

失败了就照直说，不假装成功。装不上就是安装没完成 —— 程序还能跑，但记忆检索是缺的。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.request

# 模型放在一个**公开**的仓库里（代码仓库是私有的，release 资产匿名下不到）
DEFAULT_BASE = "https://github.com/takeez/miao-models/releases/download/model-bge-small-zh-v1.5"
SUBDIR = os.path.join("models", "bge-small-zh-v1.5-onnx")
FILES = (
    ("model_quantized.onnx", "onnx/model_quantized.onnx", 168002),
    ("model_quantized.onnx_data", "onnx/model_quantized.onnx_data", 23774208),
    ("tokenizer.json", "tokenizer.json", None),
)
UA = "curl/8.5.0"


def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url, dest, expect_size=None):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r, open(dest, "wb") as f:
        total = 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
    if expect_size and total != expect_size:
        raise ValueError("大小不对：%d（应为 %d）" % (total, expect_size))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="", help="数据目录（默认用项目的数据目录）")
    ap.add_argument("--base", default=DEFAULT_BASE, help="下载源前缀")
    args = ap.parse_args()

    if args.dir:
        data_dir = args.dir
    else:
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        sys.path.insert(0, here)
        from fgbot import base
        base.load()
        data_dir = base.DATA_DIR

    out = os.path.join(data_dir, SUBDIR)
    os.makedirs(os.path.join(out, "onnx"), exist_ok=True)
    print("目标目录：%s" % out)
    print("下载源：%s" % args.base)

    ok = 0
    for name, rel, size in FILES:
        dest = os.path.join(out, rel)
        if os.path.exists(dest) and (not size or os.path.getsize(dest) == size):
            print("  ✓ 已有 %s（跳过）" % name)
            ok += 1
            continue
        url = "%s/%s" % (args.base.rstrip("/"), name)
        print("  下载 %s ..." % name)
        try:
            fetch(url, dest, size)
        except Exception as e:
            print("  ✗ %s 失败：%s" % (name, str(e)[:120]))
            try:
                os.remove(dest)
            except Exception:
                pass
            continue
        print("    ✓ %s（%d 字节）" % (name, os.path.getsize(dest)))
        ok += 1

    print()
    if ok == len(FILES):
        print("全部就位。重启服务后，首次记忆查询或写入会加载 embedder；日志应出现“语义召回：模型加载好了”。")
        print("依赖：`pip install -r requirements.txt`")
        return 0
    print("只下到 %d/%d 个文件 —— 安装没完成：记忆检索用不了（程序还能跑）。" % (ok, len(FILES)))
    print("换源重试：python3 tools/fetch_model.py --base <镜像地址>")
    return 1


if __name__ == "__main__":
    sys.exit(main())
