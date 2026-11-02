#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`plan` 那个工具：**跨轮的任务计划**（目标 + 每步一行 + 状态）。

为什么要有它（定稿）：

  · 她碰到「要多步、要跨轮」的事时，先写一张计划；之后**每一轮请求**都会把整张表
    附在 user 快照末尾 —— 所以她随时知道自己在办什么、下一步是什么；
  · 一步就能办完的小事不该用它（那是工具说明里的事，代码不管）；
  · **全部完成就自动清空**（下次请求一个字都不加），没计划也一个字都不加。

存储：**每会话一份状态文件**（`plan-<会话>.json`）——
⛔ 不塞进 memory.json（那是她的长期记忆，形状一个字都不许动，面板/App 在读它）。

⚠️ 这里的字都会进请求（第 10 条批过的那几种形状），⛔ 改文本要先问用户。
"""

import json
import re
import threading
import time

from . import base, settings, store

STATUS = ("未开始", "进行中", "已完成")
# ⚠️ 运行时一律 settings.get(...) 现读；这两个常量留着当默认值引用 / 自检用。
MAX_STEPS = 50
MAX_CONTENT = 120

_LOCK = threading.RLock()

# 会话标记：群 `g<群号>` / 私聊 `p<QQ号>`。
# ⚠️ 名字进文件名，所以只许 [0-9a-zA-Z_]（会话键本来就是数字，这里再兜一道）。
_SLUG = re.compile(r"^[A-Za-z0-9_]+$")


def _slug(key):
    """会话键 `("g", 123456789)` / `("p", 10001)` → `g123456789` / `p10001`。"""
    try:
        if isinstance(key, (tuple, list)) and len(key) >= 2:
            kind = str(key[0])
            gid = str(key[1])
            s = (("g" if kind == "g" else "p") + gid).strip()
            if _SLUG.match(s):
                return s
    except Exception:
        pass
    return ""


def _file(key):
    s = _slug(key)
    return ("plan-%s.json" % s) if s else ""


def load(key):
    """这个会话现在的计划：`{"objective": str, "steps": [{"content","status"}], "at": ts}`。"""
    name = _file(key)
    if not name:
        return {"objective": "", "steps": [], "at": 0.0}
    d = store.read_json(name) or {}
    if not isinstance(d, dict):
        d = {}
    steps = []
    for it in (d.get("steps") or []):
        if not isinstance(it, dict):
            continue
        c = str(it.get("content") or "").strip()
        s = str(it.get("status") or "").strip()
        if not c:
            continue
        steps.append({"content": c, "status": s if s in STATUS else STATUS[0]})
    return {"objective": str(d.get("objective") or "").strip(),
            "steps": steps, "at": float(d.get("at") or 0)}


def save(key, objective, steps):
    name = _file(key)
    if not name:
        return False
    return store.write_json(name, {"objective": objective or "",
                                   "steps": list(steps or []),
                                   "at": time.time()})


def clear(key):
    name = _file(key)
    if not name:
        return False
    return store.remove(name)


def done(steps):
    """整张表都做完了（空表也算「没有什么要办的」）。"""
    return not steps or all(s.get("status") == STATUS[2] for s in steps)


def _clean_status(s):
    s = str(s or "").strip()
    return s if s in STATUS else ""


def _norm_steps(raw):
    """把模型给的步骤表整理成 `[{"content","status"}]`（去重 / 状态合法 / 最多一个进行中）。

    返回 `(steps, 改了什么)` —— 改了什么只用来写日志，不进请求。
    """
    items = raw
    if isinstance(items, str):
        s = items.strip()
        try:
            items = json.loads(s) if s else []
        except Exception:
            items = [x for x in re.split(r"[\n；;]+", s) if x.strip()]
    if not isinstance(items, (list, tuple)):
        items = [items]

    notes = []
    out, seen = [], set()
    running = False
    max_steps = settings.get("plan.maxSteps")
    max_content = settings.get("plan.maxContent")
    for it in items:
        content, status = "", ""
        if isinstance(it, dict):
            content = str(it.get("content") or it.get("内容") or it.get("步骤") or "").strip()
            status = _clean_status(it.get("status") or it.get("状态"))
        else:
            # 她也可能一条一条用文字写：「1. 查数据 — 已完成」
            line = str(it or "").strip()
            m = re.match(r"^\s*(?:\d+[.、)]\s*)?(.*?)(?:\s*[—–-]{1,2}\s*(未开始|进行中|已完成))?\s*$", line)
            if m:
                content, status = (m.group(1) or "").strip(), (m.group(2) or "")
            else:
                content = line
        content = content[:max_content]
        if not content:
            continue
        if content in seen:
            notes.append("去重：%s" % content[:20])
            continue
        seen.add(content)
        if status == "进行中":
            if running:
                notes.append("第二个「进行中」降成未开始：%s" % content[:20])
                status = "未开始"
            else:
                running = True
        out.append({"content": content, "status": status or STATUS[0]})
        if len(out) >= max_steps:
            notes.append("步骤超过 %d 条，后面的没要" % max_steps)
            break
    return out, "；".join(notes)


def update(key, objective="", steps=None):
    """`plan` 工具的实现：整张替换。返回给模型看的那份 dict。"""
    obj = str(objective or "").strip()[:settings.get("plan.maxContent")]
    with _LOCK:
        old = load(key)
        norm, notes = _norm_steps(steps)
        if not norm:
            #（原来那句「步骤表里一条都没有」换掉了）
            return {"ok": False, "error": "步骤表不能是空的"}
        if not obj:
            obj = old.get("objective") or ""            # 这次没给目标：沿用上一次那个
        if done(norm):
            # 全部完成 → 自动清空（用户定的：省得它一直挂在上下文里）
            clear(key)
            base.log("计划：%d 步全部完成，自动清空" % len(norm))
            return {"ok": True, "目标": obj,
                    "步骤": _lines(norm), "还有几步": 0}
        save(key, obj, norm)
        left = len([s for s in norm if s["status"] != STATUS[2]])
    if notes:
        base.log("计划：整理步骤表时动了这些 —— %s" % notes)
    base.log("计划：存下 %d 步（还剩 %d 步没做完）" % (len(norm), left))
    return {"ok": True, "目标": obj, "步骤": _lines(norm), "还有几步": left}


def _lines(steps):
    """`["1. 查昨天战况 — 已完成", …]` —— 注入和工具返回共用的那一种写法。"""
    return ["%d. %s — %s" % (i, s.get("content") or "", s.get("status") or STATUS[0])
            for i, s in enumerate(steps or [], 1)]


def table(key):
    """**每一轮请求自动带上的那张表**；没计划 / 全做完 → 空串（一个字都不加）。

    形状（用户批的，第 10 条那第 (3) 块）：
        计划：<目标>
        1. 查昨天战况 — 已完成
        2. 比对两天数据 — 进行中
        3. 写成一句话发给他 — 未开始
    ⚠️ 目标是可选参数 —— 没给目标时就不写「计划：」那一行（免得出现一个空冒号）。
    """
    d = load(key)
    steps = [s for s in (d.get("steps") or []) if s.get("content")]
    if not steps or done(steps):
        return ""
    out = []
    if d.get("objective"):
        out.append("计划：%s" % d["objective"])
    out.extend(_lines(steps))
    return "\n".join(out)


def pending_count(key):
    """还有几步没做完（面板/自检看用）。"""
    d = load(key)
    return len([s for s in (d.get("steps") or []) if s.get("status") != STATUS[2]])
