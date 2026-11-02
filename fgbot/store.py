#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""她自己的小仓库：数据目录 + 状态文件的读写（写在临时文件上再 rename，不会写坏）。

为什么单独一个文件：v1 栽过一次特别难查的 —— 自检里那段代码真的写了状态文件，
deploy 又把**暂存目录整个搬进正式目录**，于是「没人按按钮，她的设定却变了」。
所以这里留了一个开关 `set_dir()`：自检一开始就把它指到临时目录，
**自检跑完，正式目录里一个字节都不会多**。

这个目录下的东西（deploy.py 的 NEVER 名单里也有它们，推代码时绝不覆盖）：
    memory.json      她的长期记忆库：按 QQ 号一人一块（称呼 / 关于这个人的事）
    reminders.json   提醒账本
    llm-apis.txt     手机 App 或网页面板里配的几家 API
    control.txt      手机上的 ctl 脚本写的「重置对话」请求
    status-cache.json 电脑发来的心跳缓存（status.push）：每位用户一条最新 + 收到时间
                     （2026-10-03 第三批加的；`fgbot/statuscache.py` 在写，90 分钟算过期）

⚠️ 这些是「手机上的状态」，不是代码。任何时候都不要把它们当成可以重新生成的东西。
"""

import json
import os
import tempfile
import threading

from . import base

_DIR = base.DATA_DIR            # 数据目录（默认平台相关；手机上就是 proot 里的 ~/mmzbot）
_LOCK = threading.RLock()
_CACHE = {}                     # path -> (mtime, obj)；小文件读得多，按 mtime 挡一下


def set_dir(d):
    """换数据目录。**只给自检用** —— 指向临时目录，保证自检没有副作用。"""
    global _DIR
    with _LOCK:
        _DIR = d
        _CACHE.clear()
    return _DIR


def dir_path():
    return _DIR


def path(name):
    """状态文件的绝对路径。每次都要现算 —— 自检会中途换目录。"""
    return os.path.join(_DIR, name)


def read_json(name, default=None):
    """读一个 JSON 状态文件。读不出来就返回默认值（**绝不抛异常**）。

    她宁可忘了刚才记的东西，也不能因为一个坏文件整个不说话。
    """
    p = path(name)
    with _LOCK:
        try:
            m = os.path.getmtime(p)
        except Exception:
            return default
        hit = _CACHE.get(p)
        if hit and hit[0] == m:
            return hit[1]
        try:
            with open(p, encoding="utf-8") as f:
                obj = json.load(f)
        except Exception as e:
            base.log("状态文件 %s 读不出来（当空的用）：%r" % (name, e))
            return default
        _CACHE[p] = (m, obj)
        return obj


def write_json(name, obj):
    """原子写：先写同目录的临时文件，再 rename 覆盖。

    ⚠️ 不能直接 open(...,"w") 写 —— 手机上随时可能被看门狗杀掉/断电，
       写一半就变成一个坏 JSON，下次读出来是空的（人设、提醒全丢）。
       rename 在同一分区上是原子的：要么旧的，要么新的。
    """
    p = path(name)
    with _LOCK:
        try:
            d = os.path.dirname(p)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d or ".", prefix=".tmp-", suffix=".json")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(obj, f, ensure_ascii=False, indent=1)
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp, p)
            except Exception:
                try:
                    os.remove(tmp)
                except Exception:
                    pass
                raise
            _CACHE.pop(p, None)
            return True
        except Exception as e:
            base.log("状态文件 %s 写不进去：%r" % (name, e))
            return False


def remove(name):
    try:
        os.remove(path(name))
        return True
    except Exception:
        return False
