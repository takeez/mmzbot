#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""运行参数注册表：**一张表 + 三层取值**（面板改过 > config.json > 默认值）。

为什么要这一层（2026-10-30 用户拍板）：
  · 以前这些数散在各个 `.py` 里（`MAX_KEEP = 2000`、`maxToolRounds or 50` …），
    想调一个就得改代码、重新部署；
  · 现在它们只有**一个真源**：本文件的 `REGISTRY`。代码一律 `settings.get(...)`
    **每次用到时现读** —— 面板改完下一条消息就生效，不用重启；
  · 面板改的值**不写 config.json**（那份是部署事实，deploy 会覆盖），
    而是写 `settings.json`（手机上的状态，deploy 的 NEVER 名单里有它）。

三层优先级（用户 2026-10-30 定）：
    settings.json 里的 overrides  >  base.cfg()（config.json + local-config.json）
    >  REGISTRY[key]["default"]

⛔ 这里不碰任何 API key / token —— 面板上也**不显示**它们。
⛔ 每个 default 都**等于改造前代码里的那个数**（自检 ⑤ 逐项断言，防手滑改行为）。
"""

import builtins
import threading

from . import base, store

FILE = "settings.json"

# 来源（给面板显示用；内部值只认这三个）
SOURCE_DEFAULT = "default"
SOURCE_CONFIG = "config"
SOURCE_PANEL = "panel"
SOURCE_LABEL = {
    SOURCE_DEFAULT: "默认",
    SOURCE_CONFIG: "配置文件",
    SOURCE_PANEL: "面板改过",
}

# 高级折叠区按功能域分组（顺序就是面板上的顺序）
GROUP_LABELS = {
    "context": "上下文",
    "loop": "循环",
    "wake": "唤醒",
    "memory": "记忆",
    "history": "历史",
    "plan": "计划",
    "output": "输出",
    "limit": "上限",
}

# `apply` 的两种取值：live = 下一次用到就生效；restart = 要重启她。
# ⚠️ 现在表里**全部是 live** —— 这些数都是每次用到时现读的。
APPLY_LABELS = {"live": "立即生效", "restart": "重启后生效"}

# 字符串型的可选值（面板给 datalist，后端也照这个校验）
#
# ⚠️ 2026-10-30：思考强度和后台模型搬去面板「她的大脑」/「后台模型」两张卡
#    （存 `llm-apis.txt`），这里**一项都不剩** —— 但字典留着，以后加字符串项方便。
_CHOICES = {}

# ══════════════════════════════════════════════════════════════════════
# 注册表：唯一真源
# ══════════════════════════════════════════════════════════════════════
# 字段（用户 2026-10-30 定的形状）：
#   key     点分键名（沿用 config 的路径，例如 llm.threadLimit）
#   label   中文名（面板显示）
#   group   功能域（context / loop / wake / memory / history / plan / output / limit）
#   tier    basic → 设置页卡片；advanced → 折叠区
#   type    int / float / bool / str
#   default 默认值（= 改造前代码里那个数）
#   min,max 范围（钳制用；bool / str 省略）
#   unit    单位（段 / 字 / 次 / 分钟 / 条 / 层 / 版本 / 天 / 步 / token / 秒）
#   doc     一句话说明（大白话，只进面板，⛔ 不进给模型的任何材料）
#   apply   live / restart（面板上标出来）
REGISTRY = {it["key"]: it for it in (
    # ── basic：设置页新卡片「运行参数」────────────────────────────────
    {"key": "llm.threadLimit", "label": "群聊历史段数", "group": "context",
     "tier": "basic", "type": "int", "default": 16,
     "min": 2, "max": 20, "unit": "段",
     "doc": "群聊时带进上下文的对话段数。越多越记得住，也越费 token。",
     "apply": "live"},
    {"key": "llm.historyLimitPrivate", "label": "私聊历史字数", "group": "context",
     "tier": "basic", "type": "int", "default": 4096,
     "min": 20, "max": 20000, "unit": "字",
     "doc": "私聊按字数切窗口；滑出窗口的旧对话会自动压成摘要。",
     "apply": "live"},
    {"key": "llm.maxToolRounds", "label": "工具轮次上限", "group": "loop",
     "tier": "basic", "type": "int", "default": 50,
     "min": 1, "max": 200, "unit": "次",
     "doc": "一轮对话里最多调几次工具。用完就摘掉工具目录，让她直接说。",
     "apply": "live"},
    {"key": "llm.maxTokens", "label": "单次回复上限", "group": "output",
     "tier": "basic", "type": "int", "default": 4000,
     "min": 100, "max": 32000, "unit": "token",
     "doc": "单次回复最多用多少 token。撞到上限会接着写，不是硬截断。",
     "apply": "live"},
    {"key": "agent.maxSendsPerTurn", "label": "每轮主动发言", "group": "output",
     "tier": "basic", "type": "int", "default": 10,
     "min": 1, "max": 50, "unit": "次",
     "doc": "一轮里她最多主动插几句话（收尾那句不算）。",
     "apply": "live"},

    # ── advanced：设置页折叠区「高级参数」─────────────────────────────
    {"key": "wake.maxChain", "label": "唤醒链层数", "group": "wake",
     "tier": "advanced", "type": "int", "default": 3,
     "min": 1, "max": 10, "unit": "层",
     "doc": "一条唤醒链最多套几层（到点后她又设了新的唤醒）。",
     "apply": "live"},
    {"key": "wake.maxPerHour", "label": "每小时叫醒上限", "group": "wake",
     "tier": "advanced", "type": "int", "default": 6,
     "min": 1, "max": 60, "unit": "次",
     "doc": "全局每小时最多叫醒几次；超了只记日志，一条消息都不发。",
     "apply": "live"},
    {"key": "wake.lateWindowMin", "label": "迟到补发窗口", "group": "wake",
     "tier": "advanced", "type": "int", "default": 120,
     "min": 0, "max": 1440, "unit": "分钟",
     "doc": "手机重启/关机导致错过的那次，迟到多久以内还补。",
     "apply": "live"},
    {"key": "wake.histSegs", "label": "唤醒冻结段数", "group": "wake",
     "tier": "advanced", "type": "int", "default": 6,
     "min": 0, "max": 20, "unit": "段",
     "doc": "设唤醒时冻结几段当时的对话，到点那一轮带上。",
     "apply": "live"},
    {"key": "wake.histChars", "label": "唤醒冻结字数", "group": "wake",
     "tier": "advanced", "type": "int", "default": 1500,
     "min": 0, "max": 10000, "unit": "字",
     "doc": "冻结的对话最多留多少字（从最新往回取，超了截最早的）。",
     "apply": "live"},
    {"key": "wake.digestChars", "label": "唤醒数据上限", "group": "wake",
     "tier": "advanced", "type": "int", "default": 600,
     "min": 0, "max": 5000, "unit": "字",
     "doc": "唤醒时「当时查到的数据」最多留多少字。",
     "apply": "live"},
    {"key": "wake.briefChars", "label": "单条结果摘要", "group": "wake",
     "tier": "advanced", "type": "int", "default": 120,
     "min": 0, "max": 1000, "unit": "字",
     "doc": "每条工具结果压成一句话时最多留多少字。",
     "apply": "live"},
    {"key": "memory.maxFacts", "label": "每人记忆条数", "group": "memory",
     "tier": "advanced", "type": "int", "default": 30,
     "min": 1, "max": 500, "unit": "条",
     "doc": "一个人最多记多少条事实，满了丢最早的。",
     "apply": "live"},
    {"key": "memory.maxKeep", "label": "时间线保留", "group": "memory",
     "tier": "advanced", "type": "int", "default": 120,
     "min": 10, "max": 5000, "unit": "条",
     "doc": "一场对话在内存里最多留多少条（防长跑吃内存）。",
     "apply": "live"},
    {"key": "memory.backupKeep", "label": "记忆备份版本", "group": "memory",
     "tier": "advanced", "type": "int", "default": 5,
     "min": 1, "max": 50, "unit": "版本",
     "doc": "memory.json 写前备份保留几个版本。",
     "apply": "live"},
    {"key": "memory.summaryMaxTokens", "label": "私聊压缩上限", "group": "memory",
     "tier": "advanced", "type": "int", "default": 500,
     "min": 100, "max": 4000, "unit": "token",
     "doc": "私聊自动压缩那次请求的 token 上限。",
     "apply": "live"},
    {"key": "keeper.maxDelete", "label": "管家删条上限", "group": "memory",
     "tier": "advanced", "type": "int", "default": 3,
     "min": 0, "max": 50, "unit": "条",
     "doc": "管家一次最多删几条；超了整次放弃，一条都不动。",
     "apply": "live"},
    {"key": "keeper.maxAdd", "label": "管家加条上限", "group": "memory",
     "tier": "advanced", "type": "int", "default": 10,
     "min": 0, "max": 100, "unit": "条",
     "doc": "管家一次最多加几条（防它抽风倒一大堆）。",
     "apply": "live"},
    {"key": "keeper.maxTokens", "label": "管家请求上限", "group": "memory",
     "tier": "advanced", "type": "int", "default": 1200,
     "min": 100, "max": 8000, "unit": "token",
     "doc": "管家那次请求的 token 上限。",
     "apply": "live"},
    {"key": "history.defaultDays", "label": "默认回看天数", "group": "history",
     "tier": "advanced", "type": "int", "default": 7,
     "min": 1, "max": 3650, "unit": "天",
     "doc": "回看历史时默认查最近几天。",
     "apply": "live"},
    {"key": "history.defaultCount", "label": "默认条数", "group": "history",
     "tier": "advanced", "type": "int", "default": 30,
     "min": 1, "max": 1000, "unit": "条",
     "doc": "回看历史时默认给几条。",
     "apply": "live"},
    {"key": "history.maxCount", "label": "单次最多条数", "group": "history",
     "tier": "advanced", "type": "int", "default": 100,
     "min": 1, "max": 5000, "unit": "条",
     "doc": "一次查询最多给几条。",
     "apply": "live"},
    {"key": "history.perHour", "label": "每人每小时查询", "group": "history",
     "tier": "advanced", "type": "int", "default": 20,
     "min": 1, "max": 1000, "unit": "次",
     "doc": "每人每小时最多查几次历史，防一个人把 NapCat 问穿。",
     "apply": "live"},
    {"key": "history.maxKeep", "label": "历史缓冲条数", "group": "history",
     "tier": "advanced", "type": "int", "default": 2000,
     "min": 100, "max": 100000, "unit": "条",
     "doc": "内存环形缓冲最多留多少条（不落盘，重启即失）。",
     "apply": "live"},
    {"key": "history.cacheTtl", "label": "查询缓存时间", "group": "history",
     "tier": "advanced", "type": "int", "default": 300,
     "min": 0, "max": 86400, "unit": "秒",
     "doc": "同样条件的查询结果缓存多少秒，期间不再打 NapCat。",
     "apply": "live"},
    {"key": "plan.maxSteps", "label": "计划步数上限", "group": "plan",
     "tier": "advanced", "type": "int", "default": 50,
     "min": 1, "max": 500, "unit": "步",
     "doc": "一张计划最多几步。",
     "apply": "live"},
    {"key": "plan.maxContent", "label": "单步内容上限", "group": "plan",
     "tier": "advanced", "type": "int", "default": 120,
     "min": 10, "max": 2000, "unit": "字",
     "doc": "单步内容（以及计划目标）最多多少字。",
     "apply": "live"},
    {"key": "toolkit.clipChars", "label": "工具结果截断", "group": "output",
     "tier": "advanced", "type": "int", "default": 6000,
     "min": 100, "max": 100000, "unit": "字",
     "doc": "工具结果塞进请求前最多留多少字。",
     "apply": "live"},
    {"key": "agent.maxGroupReplyChars", "label": "群聊单条上限", "group": "output",
     "tier": "advanced", "type": "int", "default": 1200,
     "min": 100, "max": 10000, "unit": "字",
     "doc": "群里单条回复最多多少字；超了拆成几条发，一个字都不丢。",
     "apply": "live"},
    {"key": "agent.maxPrivateReplyChars", "label": "私聊单条上限", "group": "output",
     "tier": "advanced", "type": "int", "default": 1500,
     "min": 100, "max": 10000, "unit": "字",
     "doc": "私聊单条回复最多多少字；同样只拆不截。",
     "apply": "live"},
)}

_LOCK = threading.RLock()
_MISSING = object()


class SettingsError(ValueError):
    """参数不合法（键不认识 / 类型不对 / 超出可选值）。"""


def _item(key):
    it = REGISTRY.get(str(key or ""))
    if not it:
        raise KeyError("没有这个运行参数：%s" % (key,))
    return it


# ── 取值 ────────────────────────────────────────────────────────────

def _config_raw(key):
    """按点分路径从**当前生效的配置**里取（base.cfg 已经并过 local-config）。"""
    node = base.cfg()
    for part in str(key).split("."):
        if not isinstance(node, dict) or part not in node:
            return _MISSING
        node = node[part]
    return node


def _coerce(item, raw):
    """把面板 / 配置里给的东西转成注册表声明的类型；转不了就抛 SettingsError。"""
    label = item["label"]
    t = item["type"]
    if t == "int":
        if isinstance(raw, bool) or isinstance(raw, (dict, list, tuple, builtins.set)):
            raise SettingsError("「%s」要填整数" % label)
        if isinstance(raw, int):
            return int(raw)
        try:
            s = str(raw).strip().replace(",", "")
            if not s:
                raise ValueError
            try:
                return int(s, 10)
            except ValueError:
                f = float(s)
                if not f.is_integer():
                    raise
                return int(f)
        except SettingsError:
            raise
        except Exception:
            raise SettingsError("「%s」要填整数（给的是「%s」）" % (label, raw))
    if t == "float":
        if isinstance(raw, bool) or isinstance(raw, (dict, list, tuple, builtins.set)):
            raise SettingsError("「%s」要填数字" % label)
        try:
            v = float(raw)
        except Exception:
            raise SettingsError("「%s」要填数字（给的是「%s」）" % (label, raw))
        if v != v or v in (float("inf"), float("-inf")):
            raise SettingsError("「%s」要填有限的数字" % label)
        return v
    if t == "bool":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in ("1", "true", "yes", "on", "是", "开"):
            return True
        if s in ("0", "false", "no", "off", "否", "关", ""):
            return False
        raise SettingsError("「%s」只能是开 / 关" % label)
    # str
    if raw is None or isinstance(raw, (dict, list, tuple, builtins.set)):
        raise SettingsError("「%s」要填文字" % label)
    v = str(raw).strip()
    if len(v) > 200:
        raise SettingsError("「%s」太长了（最多 200 字）" % label)
    choices = _CHOICES.get(item["key"])
    if choices and v not in choices:
        raise SettingsError("「%s」只能是 %s 之一（给的是「%s」）"
                            % (label, " / ".join(choices), v))
    return v


def _clamp(item, value):
    """按 min/max 钳制；返回 (值, 有没有被夹)。"""
    clamped = False
    lo, hi = item.get("min"), item.get("max")
    if lo is not None and value < lo:
        value, clamped = lo, True
    if hi is not None and value > hi:
        value, clamped = hi, True
    return value, clamped


def _load():
    d = store.read_json(FILE, {})
    return dict(d) if isinstance(d, dict) else {}


def _write(d):
    if not store.write_json(FILE, d):
        raise SettingsError("settings.json 写不进去（手机那边可能没权限）")


def _effective(item, overrides):
    """一项的生效值 + 来源（不写盘）。"""
    key = item["key"]
    if key in overrides:
        raw, source = overrides[key], SOURCE_PANEL
    else:
        raw = _config_raw(key)
        if raw is not _MISSING and raw is not None:
            source = SOURCE_CONFIG
        else:
            raw, source = item["default"], SOURCE_DEFAULT
    try:
        value = _coerce(item, raw)
    except SettingsError:
        # 配置 / settings.json 被人手改坏了：退回默认值，绝不让她整个趴窝。
        value = _coerce(item, item["default"])
        source = SOURCE_DEFAULT
    value, _clamped = _clamp(item, value)
    return value, source


def get(key, ctx=None):
    """取**生效值**：面板改过 > config.json > 默认值，最后按 min/max 钳制。

    `ctx` 只是为了跟项目里别的 `get` 保持同一个调用形状，现在没有用。
    """
    with _LOCK:
        item = _item(key)
        return _effective(item, _load())[0]


def source(key):
    """这一项现在从哪来（default / config / panel）。面板标来源、自检都用它。"""
    with _LOCK:
        item = _item(key)
        return _effective(item, _load())[1]


def check(key, raw):
    """只校验 + 钳制，不写盘。返回 (值, 有没有被夹)；不合法抛 SettingsError。"""
    item = _item(key)
    value, clamped = _clamp(item, _coerce(item, raw))
    return value, clamped


def clamp_note(key, raw):
    """给面板显示「你填了 999，已按 20 存」；没被夹 / 填得不对就返回空串。"""
    try:
        _value, clamped = check(key, raw)
    except (KeyError, SettingsError):
        return ""
    if not clamped:
        return ""
    return "你填了 %s，已按 %s 存" % (raw, _value)


# ── 写 ──────────────────────────────────────────────────────────────

def set(key, raw, who="面板"):
    """校验 → 钳制 → 写进 settings.json → 记日志。返回 (值, 是否被夹了)。

    ⚠️ **只写 overrides**，一个字节都不碰 config.json（那是部署事实）。
    ⚠️ 非法键 / 非数字类型 → KeyError / SettingsError，调用方自己接住。
    """
    with _LOCK:
        item = _item(key)
        value, clamped = check(key, raw)
        old_over = _load()
        old_value, old_source = _effective(item, old_over)
        old_over[item["key"]] = value
        _write(old_over)
        note = clamp_note(key, raw)
        base.log("设置：%s 把 %s 由 %r 改成 %r（原值来源：%s；现在：面板改过）%s"
                 % (who, item["key"], old_value, value,
                    SOURCE_LABEL.get(old_source, old_source),
                    ("；" + note) if note else ""))
        return value, clamped


def reset(key, who="面板"):
    """删掉这一项的面板覆盖值（恢复成 config.json / 默认值）。返回原来有没有覆盖。"""
    with _LOCK:
        item = _item(key)
        d = _load()
        had = item["key"] in d
        if had:
            old = d.pop(item["key"])
            _write(d)
            base.log("设置：%s 把 %s 恢复默认（删掉了面板值 %r）"
                     % (who, item["key"], old))
        return had


def reset_all(who="面板"):
    """把所有面板覆盖值清掉。返回清掉几条。"""
    with _LOCK:
        d = _load()
        n = len(d)
        if n:
            _write({})
            base.log("设置：%s 把全部运行参数恢复默认（清掉 %d 项面板值）" % (who, n))
        return n


def snapshot():
    """给面板的一页快照：每项的 值 / 默认 / 范围 / 来源 / 单位 / 说明 / 生效方式。"""
    with _LOCK:
        overrides = _load()
        items = []
        for key, item in REGISTRY.items():
            value, src = _effective(item, overrides)
            row = dict(item)
            row.update({
                "value": value,
                "source": src,
                "sourceLabel": SOURCE_LABEL.get(src, src),
                "overridden": key in overrides,
                "applyLabel": APPLY_LABELS.get(item.get("apply"), item.get("apply")),
                "groupLabel": GROUP_LABELS.get(item.get("group"), item.get("group")),
                "choices": list(_CHOICES.get(key) or ()),
            })
            row.setdefault("min", None)
            row.setdefault("max", None)
            row.setdefault("unit", "")
            items.append(row)
        basic = [r for r in items if r["tier"] == "basic"]
        advanced = [r for r in items if r["tier"] == "advanced"]
        groups = []
        for r in advanced:
            g = r["group"]
            hit = next((x for x in groups if x["group"] == g), None)
            if hit is None:
                hit = {"group": g, "label": GROUP_LABELS.get(g, g), "keys": []}
                groups.append(hit)
            hit["keys"].append(r["key"])
        return {"ok": True, "file": FILE, "count": len(items),
                "items": items, "basic": basic, "advanced": advanced,
                "groups": groups}

