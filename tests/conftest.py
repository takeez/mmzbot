# -*- coding: utf-8 -*-
"""pytest 入口：跑一次自检（离线、不写正式目录），把每一段拆成一条用例。"""
import json
import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_selftest():
    p = subprocess.run(
        [sys.executable, "-X", "utf8", "phone-bot-v2.py", "--selftest", "--json"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    blob = None
    for line in (p.stdout or "").splitlines():
        if line.lstrip().startswith('{"rc"'):
            blob = line.strip()
    if blob is None:
        pytest.exit("自检没吐出 JSON 结果（退出码 %s）：\n%s\n%s"
                    % (p.returncode, (p.stdout or "")[-2000:], (p.stderr or "")[-2000:]),
                    returncode=1)
    data = json.loads(blob)
    data["_stdout_tail"] = "\n".join((p.stdout or "").splitlines()[-40:])
    return data


def result_of(config):
    """整个会话只跑一次（收集阶段就要用，所以挂在 config 上缓存）。"""
    cached = getattr(config, "_mmz_selftest", None)
    if cached is None:
        cached = _run_selftest()
        config._mmz_selftest = cached
    return cached


@pytest.fixture(scope="session")
def selftest_result(request):
    return result_of(request.config)


def sid(name):
    out = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in name)
    return out[:48] or "sect"
