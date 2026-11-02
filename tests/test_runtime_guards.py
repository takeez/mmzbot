# -*- coding: utf-8 -*-
"""这轮补的几件小事：--version、消息去重、单实例锁、日志轮转。"""
import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "phone-bot-v2.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    return spec, mod


def test_version_flag():
    import subprocess
    p = subprocess.run([sys.executable, "-X", "utf8", "phone-bot-v2.py", "--version"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, p.stderr[-800:]
    assert p.stdout.strip().startswith("机魂小悦 ")


def test_message_dedupe():
    from fgbot import server
    server._SEEN_MSG.clear()
    server._SEEN_MSG_ORDER.clear()
    evt = {"message_id": 123456}
    assert server._msg_dupe(evt) is False      # 第一次见
    assert server._msg_dupe(evt) is True       # 重推
    assert server._msg_dupe({"message_id": 999}) is False
    assert server._msg_dupe({}) is False       # 没有 id 就不去重（别误吞）


def test_seen_cache_is_bounded():
    from fgbot import server
    server._SEEN_MSG.clear()
    server._SEEN_MSG_ORDER.clear()
    for i in range(server._SEEN_MSG_MAX + 50):
        server._msg_dupe({"message_id": 10_000_000 + i})
    assert len(server._SEEN_MSG_ORDER) <= server._SEEN_MSG_MAX
    assert len(server._SEEN_MSG) <= server._SEEN_MSG_MAX


def test_log_rotation(tmp_path, monkeypatch):
    from fgbot import base
    log = tmp_path / "bot.log"
    monkeypatch.setattr(base, "LOG_PATH", str(log))
    monkeypatch.setattr(base, "LOG_MAX_BYTES", 200)
    for i in range(40):
        base.log("第 %d 行" % i)
    assert (tmp_path / "bot.log.1").exists(), "超过上限应该滚出一份 bot.log.1"


def test_instance_lock_single(tmp_path, monkeypatch):
    from fgbot import base, server
    monkeypatch.setattr(base, "DATA_DIR", str(tmp_path))
    first = server._take_instance_lock()
    assert first is not None, "第一次应该能拿到锁"
    second = server._take_instance_lock()
    assert second is None or second is True, "第二次要么拿不到，要么平台不支持"
