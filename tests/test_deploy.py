# -*- coding: utf-8 -*-
"""deploy.py 的本地链路：备份 → 换入 → 回滚（tmp_path，不碰真目录）。"""
import importlib.util
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def deploy():
    spec = importlib.util.spec_from_file_location("mmz_deploy", os.path.join(ROOT, "deploy.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["mmz_deploy"] = mod
    spec.loader.exec_module(mod)
    return mod


def _target(deploy, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    opts = {
        "local_dir": str(data), "python": sys.executable, "port": 17383,
        "keep_backups": 5, "service": "mmzbot", "restart_cmd": "", "host": "",
    }
    return deploy.LocalTarget(opts), data


def test_backup_copies_runtime_files(deploy, tmp_path):
    """备份要把代码 / 配置 / 人设复制出去（回滚就靠它）。"""
    t, data = _target(deploy, tmp_path)
    (data / "phone-bot-v2.py").write_text("print(1)\n", encoding="utf-8")
    (data / "config.json").write_text("{}\n", encoding="utf-8")
    (data / "personality.md").write_text("人设\n", encoding="utf-8")
    (data / "fgbot").mkdir()
    (data / "fgbot" / "base.py").write_text("x = 1\n", encoding="utf-8")

    path = t.backup()
    assert path and os.path.isdir(path)
    assert os.path.isfile(os.path.join(path, "phone-bot-v2.py"))
    assert os.path.isfile(os.path.join(path, "config.json"))
    assert os.path.isfile(os.path.join(path, "personality.md"))
    assert os.path.isfile(os.path.join(path, "fgbot", "base.py"))


def test_backup_skips_missing_dir(deploy, tmp_path):
    """目标目录还不存在（第一次部署）→ 不备份、也不抛。"""
    opts = {"local_dir": str(tmp_path / "nope"), "python": sys.executable,
            "port": 17383, "keep_backups": 5, "service": "mmzbot",
            "restart_cmd": "", "host": ""}
    assert deploy.LocalTarget(opts).backup() == ""


def test_swap_writes_files_and_keeps_user_personality(deploy, tmp_path):
    """换入：代码覆盖、personality.md 不覆盖用户改过的那份。"""
    t, data = _target(deploy, tmp_path)
    (data / "personality.md").write_text("用户改过的人设\n", encoding="utf-8")

    stage = tmp_path / "stage"
    (stage / "fgbot").mkdir(parents=True)
    (stage / "phone-bot-v2.py").write_text("v2\n", encoding="utf-8")
    (stage / "fgbot" / "base.py").write_text("new\n", encoding="utf-8")
    (stage / "personality.md").write_text("出厂人设\n", encoding="utf-8")

    t.swap(str(stage), ["phone-bot-v2.py", "fgbot/base.py", "personality.md"])

    assert (data / "phone-bot-v2.py").read_text(encoding="utf-8") == "v2\n"
    assert (data / "fgbot" / "base.py").read_text(encoding="utf-8") == "new\n"
    assert (data / "personality.md").read_text(encoding="utf-8") == "用户改过的人设\n"
    # 临时文件不能留在目标目录里
    assert not [p for p in os.listdir(data) if ".tmp-" in p]


def test_swap_is_rollbackable(deploy, tmp_path):
    """先备份、再换入 → 从备份里能把旧文件取回来（这就是"回滚"的全部）。"""
    t, data = _target(deploy, tmp_path)
    (data / "phone-bot-v2.py").write_text("old\n", encoding="utf-8")
    bak = t.backup()
    assert bak

    stage = tmp_path / "stage2"
    stage.mkdir()
    (stage / "phone-bot-v2.py").write_text("new\n", encoding="utf-8")
    t.swap(str(stage), ["phone-bot-v2.py"])
    assert (data / "phone-bot-v2.py").read_text(encoding="utf-8") == "new\n"

    # 回滚 = 把备份里的文件拷回去
    for name in ("phone-bot-v2.py",):
        src = os.path.join(bak, name)
        if os.path.isfile(src):
            os.replace(src, os.path.join(data, name))
    assert (data / "phone-bot-v2.py").read_text(encoding="utf-8") == "old\n"


def test_keep_recent_backups(deploy):
    """备份只留最近 N 个（用户定的 5）。"""
    names = ["20260101-00000%d" % i for i in range(1, 9)]
    kept, drop, others = deploy.keep_recent_backups(names, 5)
    assert len(kept) == 5 and len(drop) == 3
    assert not others
