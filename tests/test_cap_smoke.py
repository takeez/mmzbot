# -*- coding: utf-8 -*-
"""真实路径冒烟：**不设** MMZBOT_SELFTEST，真装一个包、真 dispatch 一次。

为什么单独一条：其余用例都从 `MMZBOT_SELFTEST=1` 那扇门进去（为了打桩、离线），
而那扇门会绕开 `_ctx_json` / `run_isolated` / `available_isolated` —— 正是最容易坏的地方。
这条用例曾经抓到过 `isinstance(v, (list, tuple))` 把内建 list 遮蔽的 bug。
"""
import os
import subprocess
import sys
import textwrap

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SCRIPT = textwrap.dedent('''
    import json, os, shutil, sys, tempfile
    sys.path.insert(0, os.getcwd())
    from fgbot import base, capabilities

    base.load()
    work = tempfile.mkdtemp(prefix="smoke-pkg-")
    src = os.path.join(work, "echo")
    os.makedirs(src)
    open(os.path.join(src, "SKILL.md"), "w", encoding="utf-8").write(
        "---\\nname: echo\\ndescription: 冒烟\\nformatVersion: 1\\n---\\n\\n正文\\n")
    open(os.path.join(src, "tool.py"), "w", encoding="utf-8").write(
        "NAME = 'echo_tool'\\nDESC = '回声'\\n"
        "PARAMS = {'type': 'object', 'properties': {}, 'required': []}\\n"
        "def available(ctx=None):\\n    return True\\n"
        "def run(args, ctx):\\n    return {'ok': True, '说明': 'from-child'}\\n")
    r = capabilities.install(src)
    if not r.get("ok"):
        print(json.dumps({"install": r}))
        sys.exit(1)
    capabilities._CACHE.clear()
    # ctx 里带一个 tuple 的 key：这条曾经直接踩 isinstance 那行
    ok, res = capabilities.dispatch("echo_tool", {},
                                    {"user_id": "10001", "key": ("p", 10001)})
    print(json.dumps({"ok": ok, "res": res}, ensure_ascii=False))
    shutil.rmtree(work, ignore_errors=True)
''')


def test_real_path_dispatch(tmp_path):
    env = dict(os.environ)
    env.pop("MMZBOT_SELFTEST", None)
    env["MMZBOT_DATA"] = str(tmp_path / "data")
    os.makedirs(env["MMZBOT_DATA"], exist_ok=True)
    p = subprocess.run([sys.executable, "-X", "utf8", "-c", SCRIPT], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", env=env, timeout=300)
    assert p.returncode == 0, (p.stdout or "")[-2000:] + (p.stderr or "")[-2000:]
    line = [x for x in (p.stdout or "").splitlines() if x.startswith('{"ok"')]
    assert line, (p.stdout or "")[-2000:] + (p.stderr or "")[-2000:]
    import json
    data = json.loads(line[-1])
    assert data["ok"] is True
    assert data["res"]["ok"] is True
    assert data["res"]["说明"] == "from-child"
