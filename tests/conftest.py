# -*- coding: utf-8 -*-
"""pytest 入口：跑一次自检（离线、不写正式目录），把每一段拆成一条用例。

自检是一个大函数，中间某段抛异常会整份停下 —— 所以除了逐段结果，
这里还会读"跑到哪一段"的进度文件：崩掉的段单独报失败，
它后面没跑到的段也各自报一条"被前面拖崩了"，不会整份只剩一个红。
"""
import json
import os
import subprocess
import sys
import tempfile

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run_selftest():
    fd, progress = tempfile.mkstemp(prefix="mmz-selftest-progress-", suffix=".jsonl")
    os.close(fd)
    env = dict(os.environ)
    env["MMZBOT_SELFTEST_PROGRESS"] = progress
    try:
        p = subprocess.run(
            [sys.executable, "-X", "utf8", "phone-bot-v2.py", "--selftest", "--json"],
            cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env,
        )
        started = []
        try:
            with open(progress, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        started.append(json.loads(line)["section"])
        except Exception:
            started = []
    finally:
        try:
            os.remove(progress)
        except Exception:
            pass

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
    done = {s["name"] for s in data["sections"]}
    # 只把**最后一段开始过、却没结果**的当成"崩在这里"：
    # 有些段的第一个断言前没有埋点，它们的名字不会出现在结果里，那不叫崩。
    crashed = []
    if started and started[-1] not in done:
        crashed = [started[-1]]
    data["_crashed"] = crashed
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


def all_section_names(result):
    names = [s["name"] for s in result["sections"]]
    for n in result.get("_crashed") or []:
        if n not in names:
            names.append(n)
    return names


def sid(name):
    out = "".join(ch if (ch.isalnum() or ch in "._-") else "_" for ch in name)
    return out[:48] or "sect"
