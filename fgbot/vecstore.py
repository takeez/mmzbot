#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""记忆的**向量旁挂文件**：`vectors.json`（+ 每条记忆的写入时间）。

═══ 为什么不塞进 memory.json ═══

`memory.json` 的 `facts` **必须继续是字符串数组** —— 网页面板和手机 App 在读它，
改形状会把它们读坏。而且它是「手机上的状态」不是代码，deploy 不会覆盖它。
所以：
    memory.json   facts=字符串数组（形状一个字都不动）
    vectors.json  {"版本":…, "模型":…, "配方":…,
                   "人": {qq: {"条": [{"时间":…, "向量":[…512…]}, …]}}}

═══ 两级自愈 ═══

**① 每条记忆一个正文指纹**（正文的 sha1 前 16 位）。读的时候按位置核对：
   对不上（被面板/App 改过、删过、换过顺序）就**只重算那一条**。
   面板/App 直接改 memory.json 也照样能被接住（它们不经过我们任何函数）。

**② 整份一个「模型指纹 + 配方版本」**（`embed.stamp()`）：
   模型换了、或者改了"怎么把文本变成向量"（前缀/池化/维度/批法），
   旧向量在数学上就不再是同一个空间里的东西了。这时候**整份作废**、
   按需重算。没有这一级的话，旧向量会被继续用，**分数悄悄变坏而且不报错**。

   ⚠️ 作废必须是**整份**的，不能只清当前这个人：`put()` 是按人写的，
      只清一个人、下一个 `put` 就把新戳写上去，别人那些旧模型算的行
      会被当成"新的"继续用 —— 那正是这一级要防的事。

═══ 拿不到指纹时（模型不可用）═══

`stamp=None` → **维持现状，绝不清空**。降级模式下 `memory` 那个工具本来就退回
「把这个人的全部记忆给她」，向量留着，等模型回来还能接着用。

═══ 向后兼容 ═══

· 老数据（这份文件还不存在时记下的）没有时间戳 → `时间` 给 0，
  `semantic.rank` 把 0 当「并列」，tiebreak 静默跳过，不报错。
· 升级前写下的文件没有「模型/配方」两项 → 当成**对不上**，作废重算一次
  （保守但安全：没法证明那些向量是这套配方算的）。
"""

from __future__ import annotations

import hashlib
import threading
import time

from . import base, store

VECTORS = "vectors.json"
VERSION = 1

_LOCK = threading.RLock()


def _fp(text):
    """一条记忆的指纹：正文变了指纹就变 → 那一条自动作废重算。"""
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def _stamp_of(d):
    """这份文件里存着的「谁算的」：(模型指纹, 配方版本)。没写过就是 (None, None)。"""
    return (d.get("模型"), d.get("配方"))


def _brief(stamp):
    """日志里给人看的一行（日志不是给模型看的文本）。"""
    fp, ver = stamp if stamp else (None, None)
    if not fp and ver is None:
        return "（空）"
    return "模型=%s 配方=%s" % (fp or "?", ver if ver is not None else "?")


# ── 读写整份 ────────────────────────────────────────────────────────

def _load():
    d = store.read_json(VECTORS) or {}
    if not isinstance(d, dict):
        return {"版本": VERSION, "人": {}}
    d.setdefault("版本", VERSION)
    if not isinstance(d.get("人"), dict):
        d["人"] = {}
    return d


def _save(d):
    return store.write_json(VECTORS, d)


def _person(d, qq):
    p = d["人"].get(str(qq))
    if not isinstance(p, dict) or not isinstance(p.get("条"), list):
        p = {"条": []}
        d["人"][str(qq)] = p
    return p


# ── 读 ──────────────────────────────────────────────────────────────

def current_stamp():
    """这份文件里现在存的「谁算的」（没写过就是 (None, None)）。自检/面板用。"""
    with _LOCK:
        return _stamp_of(_load())


def _invalidate(d, stamp, why):
    """整份作废：清掉**所有人**的向量，写上新的戳，落盘。

    ⚠️ 一定要连别人的一起清（理由见文件开头那段）。
    """
    n = sum(len((p or {}).get("条") or []) for p in d["人"].values())
    d["人"] = {}
    d["模型"], d["配方"] = stamp
    _save(d)
    base.log("语义召回：向量整份作废（%s；丢掉 %d 条旧向量，按需重算）" % (why, n))


def load_for(qq, facts, stamp=None):
    """把这个人**当前**的 facts 配上旁挂数据。

    `stamp` = `embed.stamp()` = `(模型指纹, 配方版本)`：
      · 给了、和文件里存的一致         → 正常复用
      · 给了、但**不一致**（换模型／改配方／老文件没这两项）
        → **整份作废**，按需重算（不报错、不抛异常）
      · **None**（模型不可用，拿不到指纹）→ **维持现状，绝不清空**

    返回 `(vectors, times)`：
        vectors  每条一个 512 长的 list，**没有的给 None**
        times    每条一个写入时间，**没有的给 0**（=并列）
    """
    facts = list(facts or [])
    with _LOCK:
        d = _load()
        if stamp is not None and _stamp_of(d) != stamp:
            _invalidate(d, stamp,
                        "存的是 %s，现在要 %s" % (_brief(_stamp_of(d)), _brief(stamp)))
        rows = _person(d, qq)["条"]
    vectors, times = [], []
    for i, f in enumerate(facts):
        row = rows[i] if i < len(rows) and isinstance(rows[i], dict) else {}
        ok = (row.get("指纹") == _fp(f))
        v = row.get("向量") if ok else None
        vectors.append(list(v) if isinstance(v, list) and v else None)
        times.append(float(row.get("时间") or 0) if ok else 0.0)
    return vectors, times


def missing(facts, vectors):
    """哪些位置缺向量（自愈要补算的就是这些）。"""
    return [i for i, v in enumerate(vectors) if not v]


# ── 写 ──────────────────────────────────────────────────────────────

def put(qq, facts, vectors, times=None, stamp=None, keep_old_time=True):
    """把这个人**整条**旁挂数据写回去（对不上指纹的位置丢掉）。

    `vectors[i]` 可以是 None（那条没算出来 → 不写，下次再补）。

    `stamp` 只在文件**还没有戳**的时候写上（第一次建这份文件）。
    戳不一致时**故意不写** —— 那种情况该由 `load_for` 先整份作废，
    而不是在这里偷偷把一批旧向量"认证"成新的。
    """
    facts = list(facts or [])
    times = list(times or [])
    with _LOCK:
        d = _load()
        if stamp is not None and _stamp_of(d) == (None, None):
            d["模型"], d["配方"] = stamp
        old = _person(d, qq)["条"]
        rows = []
        for i, f in enumerate(facts):
            v = vectors[i] if i < len(vectors) else None
            if not v:
                continue
            t = times[i] if i < len(times) else 0
            if not t and keep_old_time and i < len(old) and isinstance(old[i], dict) \
                    and old[i].get("指纹") == _fp(f):
                t = old[i].get("时间") or 0
            if not t:
                t = time.time()
            rows.append({"指纹": _fp(f), "时间": float(t),
                         "向量": [round(float(x), 6) for x in v]})
        d["人"][str(qq)] = {"条": rows}
        return _save(d)


def drop(qq):
    """这个人的旁挂数据整块删掉（forget_person 用）。"""
    with _LOCK:
        d = _load()
        if str(qq) in d["人"]:
            d["人"].pop(str(qq), None)
            return _save(d)
    return False


def prune(known_qqs):
    """把记忆库里已经没有的人清掉（省地方）。"""
    known = set(str(x) for x in (known_qqs or []))
    with _LOCK:
        d = _load()
        dead = [k for k in d["人"] if k not in known]
        if dead:
            for k in dead:
                d["人"].pop(k, None)
            base.log("语义召回：清掉 %d 个已经不在记忆库里的人的向量" % len(dead))
            return _save(d)
    return False


def stats():
    """面板/自检用：有多少人、多少条向量、这份是谁算的。"""
    with _LOCK:
        d = _load()
        people = d["人"]
        return {"人": len(people),
                "条": sum(len((p or {}).get("条") or []) for p in people.values()),
                "版本": d.get("版本", VERSION),
                "模型": d.get("模型"),
                "配方": d.get("配方")}
