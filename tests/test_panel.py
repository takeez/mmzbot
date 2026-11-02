# -*- coding: utf-8 -*-
"""面板的 JS 单独成文件之后，可以直接做语法检查（不用先渲染页面再抽出来）。"""
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def test_js_syntax(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("这台机器没有 node（CI 的 runner 自带）")
    from fgbot import panel_js

    js = tmp_path / "panel.js"
    js.write_text(panel_js.JS1 + "\n" + panel_js.JS2 + "\n" + panel_js.JS3, encoding="utf-8")
    p = subprocess.run([node, "--check", str(js)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr[-2000:]


def test_panel_renders():
    from fgbot import panel

    page = panel.render()
    assert "<title>" in page and "</html>" in page
    assert "{{CSS}}" not in page and "{{JS1}}" not in page      # 占位都填掉了
    assert len(page) > 100_000
