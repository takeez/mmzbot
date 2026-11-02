# -*- coding: utf-8 -*-
"""面板 JS 里几个关键函数的**行为**测试（不引浏览器：把函数摘出来在 node 里跑）。"""
import json
import os
import re
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

NODE = shutil.which("node")


def _js():
    from fgbot import panel_js
    return panel_js.JS1 + "\n" + panel_js.JS2 + "\n" + panel_js.JS3


def _grab(name):
    """从面板 JS 里摘出一个函数（按括号配对找结尾）。"""
    src = _js()
    i = src.index("function %s(" % name)
    j = src.index("{", i)
    depth = 0
    for k in range(j, len(src)):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[i:k + 1]
    raise AssertionError("没摘到函数 %s" % name)


def _run_node(script):
    if not NODE:
        pytest.skip("这台机器没有 node")
    p = subprocess.run([NODE, "-e", script], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-1500:]
    return json.loads(p.stdout.strip() or "null")


def test_esc_escapes_html():
    """用户可控的文本进 innerHTML 前必须转义（XSS）。"""
    esc = _grab("esc")
    script = esc + "\nconsole.log(JSON.stringify([" \
        "'<script>alert(1)</script>', 'a&b', '\"quote\"', null, undefined, 42" \
        "].map(esc)))"
    got = _run_node(script)
    assert got[0] == "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert got[1] == "a&amp;b"
    assert got[2] == "&quot;quote&quot;"
    assert got[3] == "" and got[4] == ""          # null / undefined → 空串
    assert got[5] == "42"


def test_esc_no_double_escape_bug():
    """已经转义过的文本再过一次只会更多转义一层 —— 至少不能把 & 吃掉（防回归）。"""
    esc = _grab("esc")
    got = _run_node(esc + "\nconsole.log(JSON.stringify([esc('&'), esc(esc('&'))]))")
    assert got[0] == "&amp;"
    assert got[1] == "&amp;amp;"


def test_half_width_normalization():
    """全角数字/字母要转成半角（中文输入法最常见的坑）。"""
    fn = _grab("half")
    got = _run_node(fn + "\nconsole.log(JSON.stringify([half('１２３'), half('ａｂ'), half('1 2')]))")
    assert got[0] == "123"
    assert got[1] == "ab"
    assert got[2] == "1 2"
