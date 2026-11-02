#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""她的工具：**只给她"办事"的能力，不给她"改自己"的权限。**

这份目录是刻意小的。DSH 自己踩出来的教训（anchored 预设那一段注释）：
工具目录一长，模型的行为就被目录本身拖着走。所以这里每个工具只干一件事，
描述只有一句「什么时候用」，不写台词、不写规矩。

═══ 三条写作纪律 ═══

① **工具描述里绝不写现成台词。**
   v1 栽过：描述里写了「私聊发你了」，她真的照抄进正文，而她根本没调这个工具。
② **工具返回的是"事实材料"，不是最终发言。**
   「电脑没开机，查不到」这种可以是固定串 —— 它不是她说的话，是给模型看的材料。
③ **不改自己、不改环境。**
   没有"写代码""改配置""改提示词""改文件"这类工具。她只有"调用工具办事"这一项权限。

⚠️ 每个工具都必须**吃掉所有异常**并返回 `{"ok": false, "error": …}` ——
   工具炸了就让她看到事实、自己跟人说，绝不能让整轮对话挂掉。
"""

import json
import time
import urllib.parse

from . import (base, clock, groups, guards, history, im, memory, plan, recall,
               reminders, settings, web, who)

try:
    from . import persona
except Exception:                                   # pragma: no cover
    persona = None


# ── 小工具 ──────────────────────────────────────────────────────────

def _who(ctx):
    return str((ctx or {}).get("user_id") or "")


def _identify_word(ctx, w):
    """一个词 → `(QQ 号, 认不出的原因)`（走**统一认人**那条路）。

    ⚠️ 为什么要单独包一层：`say` / `pc_status` 这几个工具的参数就叫 `who`
       （在那个函数体里把模块名遮住了），模块得从这里拿。
    ⚠️ 原因要一起交出去：`"ambiguous"` = **重名**，调用方要回 `_AMBIGUOUS` 那句；
       其余认不出来一律 `_NOBODY`（2026-10-06 拍板：两个工具**同一套两句**）。
    """
    qq, _rec, why = who.identify(w, ctx)
    return str(qq or ""), why


# 「认不出这个人」那一句 —— **逐字定稿**（他给了才写的），一个字都不许改。
# ⚠️ 只有这一份字面（以前它内联在 `_target` 里）。
_NOBODY = "没找到「%s」这个人 —— 让他起个称呼"

# ⚠️ **重名**（同一个词 ≥2 个**不同 QQ** 命中同一档）时给模型的那句话 ——
#    **逐字定稿**（他给了才写的），⛔ 一个字都不许改（标点、那个破折号、
#    空格都在内）。为什么不提 QQ：新设计里**她看不到 QQ 号**，更不该让她去问人要号 ——
#    重名了就让那个人自己起个称呼。
_AMBIGUOUS = "「%s」重名了，查不到 —— 让他起个称呼"


def _target(ctx, who_=""):
    """工具里「对谁」那个可选参数：留空 = 当前说话的人；填名字或 QQ 号 = 那个人。

    2026-09-27 要的（B5）：称呼 / 记忆 / 提醒 / 私聊这些"给别人办事"的工具
    都该能指定人。所以"把 who 解析成 QQ 号"**只有 `who.identify()` 那一处实现**。
    返回 (qq, 拿不到时的人话原因)；qq 为空串 = 没解析出来。

    ⚠️ 2026-10-04：认人整条改走 `who.qq()` —— **称呼 / 昵称 / QQ 号都认**，
       用户表里没有的人照旧退到记忆层（行为和以前一样）。
    ⚠️ 2026-10-06（用户拍板）：
       · `ctx` **真的传下去**了 —— 认人要用它取**当前群号**（名片按群各一张）；
       · 面板备注 / 私有备注**完全不参与匹配**；
       · 同一档命中 ≥2 个**不同 QQ** = **重名 → 一律不猜**：回定稿的那句
         `_AMBIGUOUS`（「X」重名了，查不到 —— 让他起个称呼）。
       · 认不出来那句也**重定稿**了：`_NOBODY`（没找到「X」这个人 —— 让他起个称呼）；
         `say` / `pc_status` 都复用它，**同一套两句**。
       · `电脑名` 不再是任何一档（整条链路清干净）。
    """
    who_ = str(who_ or "").strip()
    if not who_:
        return _who(ctx), ""
    qq, _rec, why = who.identify(who_, ctx)
    if qq:
        return str(qq), ""
    return "", (_AMBIGUOUS if why == "ambiguous" else _NOBODY) % who_


def _name_of(qq):
    """材料里显示用：这个 QQ 号现在叫什么（**备注 → 称呼 → 昵称 → QQ 号**）。

    ⚠️ 2026-10-04：改走 `who.display_name()`（唯一一处显示名实现）。
       ⛔ 默认**不现取**昵称（`fetch=False`）—— 工具返回里绝不为一个名字去等网络；
         她记忆里见过的那个昵称照样用得上。
    """
    return who.display_name(str(qq or "")) or str(qq)


def _cname(ctx):
    """当前说话人怎么称呼 —— 和 agent 层用同一套规则（memory.call_name）。"""
    return memory.call_name(ctx)


def _num(x, default=0):
    try:
        return int(str(x).strip())
    except Exception:
        return default


# ── 各工具的实现 ────────────────────────────────────────────────────

WEEK = ("一", "二", "三", "四", "五", "六", "日")


def t_now(ctx):
    n = clock.now()
    return {"ok": True,
            "时间": n.strftime("%Y-%m-%d %H:%M:%S"),
            "星期": clock.weekday_cn(n),
            "时区": clock.zone()}


_SELF = who.SELF_WORDS


def _recall_shape(facts, query, qq=None):
    """`memory` 那个工具的返回形状 —— **只有这三种**（用户定死的，一个字都别加）。

        ① 填了 `ask`、有对上的：   {"ok": true, "一共": 7, "这几条": ["喜欢喝美式", "爱喝手冲"]}
        ② 填了 `ask`、一条都没对上：{"ok": true, "一共": 7, "没找到相关的": true}
        ③ 没填 `ask`：            {"ok": true, "一共": 7, "记着他这些": [...]}

    `一共` = 这个人的**总条数**（三种形状里是同一个意思）。

    ⚠️ 只给这几种形状，不给她相似度数字、不加任何说明话术。
    """
    ss = [f for f in (facts or []) if isinstance(f, str) and f.strip()]
    if not query:
        return {"ok": True, "一共": len(ss), "记着他这些": ss}
    picked, degraded = recall.pick(qq, ss, query)
    if degraded or picked is None:
        # 语义召回用不了（模型不在/出错）→ 退回形状③：把这个人的全部给她。
        # 用户定的：绝不能让工具报错，降级就行。
        return {"ok": True, "一共": len(ss), "记着他这些": ss}
    if not picked:
        return {"ok": True, "一共": len(ss), "没找到相关的": True}
    return {"ok": True, "一共": len(ss), "这几条": [t for t, _s in picked]}


def _recall_who(ctx, who_):
    """解析「查谁」→ `(qq, 这个人的记录, 是不是查她自己, 认人失败的原因)`。

    ⚠️ 这里有三条从老代码抄下来的坑，别顺手改掉：
    ① 她**不知道自己的 QQ 号**（场合里不告诉她），所以留了几个词让她能指
       「我自己」（用户点名要的：她该能查到自己是哪来的）；
    ② `memory.find` **不认纯数字**，所以 QQ 号要单独直接当 QQ 用（实测过）；
    ③ `w == uid` 时走下面那条，不能当成"填了 who"。

    ⚠️ 2026-10-06：把词变成 QQ 这一步改走 `who`（**称呼 / 昵称 / QQ 都认**）；
       `电脑名` 那一档整条删掉了（只写日志，不当别名）。
    ⚠️ 2026-10-06（用户拍板）：工具名从 `recall` 改成 `memory`，参数
       「问什么」改成 `ask` —— ⛔ 说明文字一个字都没动（只改名）。
    """
    me = str(base.self_id())
    w = (who_ or "").strip()
    if w in _SELF or (w and w == me):
        return me, memory.record_of(me), True, ""

    uid = _who(ctx)
    why = ""
    if w and w != uid:
        qq, _rec, why = who.identify(w, ctx)
        qq = qq or None
    else:
        qq = uid
    rec = memory.record_of(qq) if qq else {}
    return qq, (rec or {}), False, why


def t_recall(ctx, who="", ask=""):
    """查长期记忆 —— **只取一个人的那一块**，绝不把整份文件（含别人的）发出去。

    填了 `ask` 时走**语义召回**：只把最像的 1~10 条给她，而不是把那个人的
    全部记忆倒给她（倒全部会让她"输出要素过多"）。一条都没对上就回
    「没找到相关的」。不填就是全部 —— 用户明确要的，不是"最近 3 条"。

    ⚠️ 2026-10-06（用户拍板）：工具名 `recall` → `memory`，参数「问什么」→ `ask`
       —— ⛔ 说明文字一个字没动，⛔ 没有多出任何参数。
    """
    query = str(ask or "").strip()
    w = (who or "").strip()
    me = str(base.self_id())

    # 查她自己：她不知道自己的 QQ 号（场合里不告诉她），「自己 / MMZ / 她自己的 QQ 号」都算
    self_lookup = bool(w) and (w in _SELF or w == me)
    qq, rec, _self, why = _recall_who(ctx, who)
    if why == "ambiguous":
        # **重名**（同一个词 ≥2 个不同 QQ）→ 一律不猜：回逐字定稿那句。
        return {"ok": False, "error": _AMBIGUOUS % w}
    facts = [f for f in (rec.get("facts") or []) if isinstance(f, str) and f.strip()]

    # 这个人名下什么都没有
    if not facts:
        if self_lookup:
            return {"ok": True, "查到了": False, "说明": "关于你自己，这块还是空的"}
        return {"ok": True, "查到了": False,
                "说明": "关于 %s（QQ %s）你这里什么都没记过；他的群名片是「%s」"
                        % (w or _cname(ctx), qq or w, (ctx or {}).get("who") or "")}

    # 没填 `ask` → 全部。查自己时保持老形状（自检/面板认这个），其余人用形状③。
    if not query:
        if self_lookup:
            return {"ok": True, "查到了": True, "QQ": me, "这块是": "你自己",
                    "你叫": rec.get("name") or (persona.name() if persona else "机魂小悦"),
                    "关于你自己的事": facts}
        return _recall_shape(facts, "", qq)

    # 填了 `ask` → 语义召回。查自己也走同一套形状 —— 她填「自己」的时候
    # 本来就知道问的是谁，而且用户已经把「称呼」从里面删掉了，
    # 所以结果里不带任何称呼字段。
    return _recall_shape(facts, query, qq)


# `user_info` 的 `fields`：**宽松认"包含"**——
# `称呼` ✓　`QQ` / `号` ✓　`昵称` ✓　`名片` / `群名片` ✓；**认不出的项忽略**。
# 键名固定 `QQ` / `称呼` / `QQ昵称` / `本群名片`；⛔ **没有"设备/电脑"这一项**。
_INFO_FIELDS = (("QQ", ("qq", "号")),
                ("称呼", ("称呼",)),
                ("QQ昵称", ("昵称",)),
                ("本群名片", ("名片",)))
_INFO_ORDER = ("QQ", "称呼", "QQ昵称", "本群名片")


def t_user_info(ctx, who="", fields=""):
    """查用户的资料：QQ 号、称呼、QQ 昵称、本群名片。

    返回**逐字**长这样（取不到的项**整个不出现**；`QQ` 恒有）：
        {"ok": true, "QQ": "30001", "称呼": "李四",
         "QQ昵称": "華仙", "本群名片": "阿猫"}

    认人走 `_target()`（= `who.identify()` 唯一那一处）：撞名 → `_AMBIGUOUS`，
    没找到 → `_NOBODY`；`who` 留空 = 当前说话的人。
    `fields` 留空 = 全给；填了就只给那几项（宽松认"包含"，认不出的项忽略）。

    ⚠️ 私聊**永远没有 `本群名片`**（私聊根本没有"本群"这回事）。
    ⚠️ 昵称**现取**（`who.fetch_nick`，每个号每进程只问一次、只放进程内缓存）——
       2026-10-06 拍板：**面板 + 这个查询**才现取，⛔ 给模型看的材料路径不现取。
    ⛔ 没有"设备/电脑"这一项（2026-10-06 拍板删掉的）。
    """
    qq, bad = _target(ctx, who)
    if not qq:
        return {"ok": False, "error": bad}
    # ⚠️ 这个函数的参数就叫 `who`，把模块名遮住了 —— 模块得从这里拿
    #    （和 `_identify_word` 那个坑同一个）。
    from . import who as _who_mod
    m = memory.record_of(qq)
    nick = _who_mod._clean(m.get("nick"))
    if not nick:
        try:
            nick = _who_mod._clean(_who_mod.fetch_nick(qq))   # 现取（进程内缓存，重复问不花第二次）
        except Exception:
            nick = ""
    gid = (ctx or {}).get("group_id") if (ctx or {}).get("is_group") else ""
    vals = {"QQ": qq,
            "称呼": _who_mod._clean(m.get("name")),
            "QQ昵称": nick,
            "本群名片": memory.card_in(qq, gid) if gid else ""}
    s = str(fields or "").strip()
    if s:
        low = s.lower()
        want = [k for k, words in _INFO_FIELDS if any(w in low for w in words)]
    else:
        want = list(_INFO_ORDER)
    out = {"ok": True, "QQ": qq}
    for k in _INFO_ORDER[1:]:
        v = vals.get(k)
        if k in want and v:
            out[k] = v
    return out


def t_memory(ctx, who="", ask="", text=""):
    """查**或**记某个人的长期记忆（2026-10-30 起是一个工具，A3）。

    · `text` 非空 → **记**一条（一条一件事的短句），记完立刻跑一次 memory-keeper
      （后台管家负责跟已有记忆去重 / 改 / 删，她自己不用给 old/new）；
    · `text` 留空 → **查**（就是原来的 `t_recall`：填了 `ask` 走语义召回，
      留空把这个人的全部记忆给她）。
    """
    body = str(text or "").strip()
    if not body:
        return t_recall(ctx, who=who, ask=ask)
    qq, bad = _target(ctx, who)
    if not qq:
        return {"ok": False, "error": bad}
    # ⭐ 管家先跑、再写：以前是先 add 再 review，
    #    管家看到的列表里已经有这条新的 ✓ 它就把列表里那条当"重复"删掉 ✗
    #    结果新事实丢了、她还回用户"记下了" ✗ 现在顺序反过来：
    #      · 管家看到的是【旧列表 + 这条新的】✓ 不会重复 ✓
    #      · 它判断完会把"该留的/改得更准的"写进「加」✓ 返回值 = 加进去的句子 ✓
    #      · 它没加（比如这条跟已有的完全重复）→ 我们再原样记一条 ✓
    keeper_added = None
    try:
        from . import keeper
        keeper_added = keeper.review(qq, body)
    except Exception as e:
        base.log("管家没跑起来（这条按原样记下）：%r" % (e,))
    if keeper_added is not False and keeper_added is not None:
        # 管家这一趟**真的动过记忆**（哪怕只是删了旧的、没往「加」里写）。
        # ⚠️ P2-1：以前写 `if keeper_added:` —— 只删不加时它返回 []，
        #    会被当成"什么都没发生" → 把「别记我住哪了」这种**删除请求**当成事实记下来 ✗
        #    现在按"是不是 False（没动）"判断，[] 也算动过 ✓
        explained = ("管家整理过了：%s" % "、".join(keeper_added[:3])) if keeper_added \
                    else "管家整理过了（删掉了过时的，不用再加这条）"
        return {"ok": True, "记在谁名下": _name_of(qq), "说明": explained,
                "现在记着他这些": memory.facts_of(qq)}
    ok, why = memory.add_fact(qq, body)
    if not ok:
        return {"ok": False, "说明": why}
    return {"ok": True, "记在谁名下": _name_of(qq), "说明": why,
            "现在记着他这些": memory.facts_of(qq)}


def t_callname(ctx, who="", name=""):
    """定 / 取消某个人的【称呼】（2026-10-30 起是一个工具，A3）。

    `name` 留空 = **取消**（回到他的群名片/昵称），填了 = 定成它。
    """
    qq, bad = _target(ctx, who)
    if not qq:
        return {"ok": False, "error": bad}
    n = str(name or "").strip()
    if not n:
        ok, why = memory.forget_name(qq)
        return {"ok": ok, "取消的是": _name_of(qq), "QQ": qq, "说明": why}
    ok, why = memory.remember_name(qq, n)
    return {"ok": ok, "称呼": memory.clean_name(n), "给谁定的": _name_of(qq),
            "QQ": qq, "说明": why}


def t_plan(ctx, objective="", steps=""):
    """规划：跨轮的任务计划（目标 + 整张步骤表）。整张替换上一次的表。"""
    return plan.update((ctx or {}).get("key"), objective, steps)


def t_history(ctx, who="", q="", after="", before="", count=""):
    """回看上下文里没有的更早发言（数据源只有 NapCat 的历史接口）。"""
    qq = ""
    w = str(who or "").strip()
    if w:
        qq, bad = _target(ctx, w)
        if not qq:
            return {"ok": False, "error": bad}
    return history.query(ctx, who_qq=qq, q=q, after=after, before=before, count=count)




# ── pc_status 搬走了──────────────────────────────────
#
# `pc_status`（战况）不再是内置工具：它现在是**第一个示例包**
# （`examples/packages/pc-status/`，默认不装；知识锁：读技能才解锁工具）。
# 原来那一整段（`_pc_target` / `_NO_PERSON` / `_pc_forward` / `_NO_HB` / `t_pc_status`）
# **原样搬**进了那个包的 `tool.py` —— ⛔ 那些句子是定稿的，一个字都没改。
# `call("pc_status", …)` 照样派发（走 `capabilities.dispatch`），只是**目录里不常驻**：
# 要她先 `skill("pc-status")` 解锁，schema 才进请求（见 `schemas()` 末尾）。

_SET_ACTIONS = ("设", "设定", "定", "新", "新建", "加")
_LIST_ACTIONS = ("列", "列表", "列一下", "看", "看看", "查看")
_CANCEL_ACTIONS = ("取消", "撤", "撤销", "删", "删掉", "撤掉")

# ── 唤醒「当时」的现场──────────────────
#
# 到点那一轮要像「那场对话的下一轮」：把**设唤醒那一刻**的对话、以及她当时查到的
# 东西一起冻结进账本（`reminders.json` 的 `hist` / `digest`，都是可选字段）。
# ⛔ 中间新聊的一律不带：这里取的是 `t_wake` 被调用那一刻的快照。
# ⛔ `wake` 自己、`say`（那是说话，不算查东西）、`end_turn` 不进摘要。
# ⚠️ 这些数运行时一律 settings.get(...) 现读（面板能调）。
#    常量留着当默认值引用 / 自检用；唯一真源在 settings.REGISTRY。
WAKE_HIST_SEGS = 6              # 最近 6 段
WAKE_HIST_CHARS = 1500          # 总长 ≤1500 字（从最新往回取，超了截断最早的）
WAKE_DIGEST_CHARS = 600         # 摘要 ≤600 字
WAKE_BRIEF_CHARS = 120          # 单条结果只留 120 字
_WAKE_NO_DATA = ("say", "wake", "end_turn")


def _wake_hist(key):
    """设唤醒那一刻的最近 6 段对话（`memory.render` 原样，总长 ≤1500 字）。

    ⚠️ 取的是**整段**（同一个人连发的几条会合并成一段，跟历史那条路一模一样），
       ⛔ 不切半句：从最新往回累加整条；只有"最早的这一段"放不下时才截断它
       （2026-10-30 拍板：超了截断最早的）。
    ⚠️ 只取那个会话（`key` 就是会话的唯一标识）；读不出来就返空 —— 不许炸。
    """
    if not key:
        return []
    try:
        msgs = memory.render(key)
    except Exception:
        base.log_exc("唤醒快照：读当时的对话")
        return []
    segs = [m.get("content") for m in msgs
            if isinstance(m, dict) and isinstance(m.get("content"), str)
            and m.get("content").strip()]
    segs_n = settings.get("wake.histSegs")
    segs = segs[-segs_n:] if segs_n > 0 else []
    chars = settings.get("wake.histChars")
    out, total = [], 0
    for s in reversed(segs):
        left = chars - total
        if left <= 0:
            break
        if len(s) <= left:
            out.append(s)
            total += len(s)
        else:
            out.append(s[:left])
            break
    return list(reversed(out))


def _flat(s):
    """一句事实里不留换行 / 连串空白（摘要是一行）。"""
    return " ".join(str(s if s is not None else "").split())


def _wake_brief(res):
    """工具结果里最关键的那点（≤120 字，一句话事实）。

    格式跟用户批的示例一致：`键 值`，几条用「 / 」连；失败就把那句 error 给她。
    ⛔ 这不是台词，是"她当时看到了什么"的压缩记录。
    """
    brief = settings.get("wake.briefChars")
    if not isinstance(res, dict):
        return _flat(res)[:brief]
    if res.get("ok") is False and str(res.get("error") or "").strip():
        return _flat(res.get("error"))[:brief]
    bits = []
    for k, v in res.items():
        # `_raw_text`（`skill` 的原文）不进摘要：那是正文，不是"查到的一点事实"
        if k in ("ok", "error", "_raw_text") or isinstance(v, bool) or v in (None, ""):
            continue
        if isinstance(v, (list, tuple)):
            flat = [str(x) for x in v[:3] if not isinstance(x, (dict, list))]
            s = "%s %s" % (k, "、".join(flat)) if flat else "%s %d 条" % (k, len(v))
        elif isinstance(v, dict):
            flat = ["%s %s" % (kk, vv) for kk, vv in list(v.items())[:2]
                    if isinstance(vv, (str, int, float)) and not isinstance(vv, bool)]
            s = "%s %s" % (k, "；".join(flat)) if flat else ""
        else:
            s = "%s %s" % (k, v)
        if not s:
            continue
        if len(" / ".join(bits + [s])) > brief:
            left = brief - len(" / ".join(bits)) - (3 if bits else 0)
            if left > 0:
                bits.append(s[:left])
            break
        bits.append(s)
    return _flat(" / ".join(bits))[:brief]


def _wake_args(args):
    """工具调用里那几个「关键参数」→ `名字=值`（最多 3 个、每个 30 字以内）。

    ⚠️ 参数值太长（比如一段要发出去的话）只留开头，⛔ 别让摘要被它撑爆。
    """
    if not isinstance(args, dict):
        return ""
    parts = []
    for k, v in args.items():
        s = _flat(v)
        if not s:
            continue
        if len(s) > 30:
            s = s[:30] + "…"
        parts.append("%s=%s" % (k, s))
        if len(parts) >= 3:
            break
    return ",".join(parts)[:60]


def _wake_digest(ctx):
    """她这一轮调过的工具 → 一句事实（≤600 字，多个用「；」连）。

    数据来自 `call()` 往 `ctx["_tool_log"]` 追加的 `(name, args, brief)`；
    这一轮是新的 ctx（见 `agent._wake_ctx`），⛔ 不用清理。
    """
    log = (ctx or {}).get("_tool_log") if isinstance(ctx, dict) else None
    limit = settings.get("wake.digestChars")
    bits, total = [], 0
    for item in log or []:
        try:
            name, args, brief = item
        except Exception:
            continue
        if not name or name in _WAKE_NO_DATA or not brief:
            continue
        a = _wake_args(args)
        s = ("%s（%s）→ %s" % (name, a, brief)) if a else ("%s → %s" % (name, brief))
        sep = 1 if bits else 0
        left = limit - total - sep
        if left <= 0:
            break
        if len(s) > left:
            bits.append(s[:left])
            break
        bits.append(s)
        total += sep + len(s)
    return _flat("；".join(bits))[:limit]


def _log_tool(ctx, name, args, res):
    """把这一次工具调用记进 `ctx["_tool_log"]`（`call()` 里每个调用记一次）。"""
    if not isinstance(ctx, dict):
        return
    try:
        log = ctx.setdefault("_tool_log", [])
        if isinstance(log, list):
            log.append((name, args if isinstance(args, dict) else {},
                        _wake_brief(res)))
    except Exception:
        pass


def t_wake(ctx, action="", when="", note="", where="", id=""):
    """设 / 列 / 取消一条唤醒（2026-10-30 起是一个工具，A3 / A6）。

    `action` 留空 = 给自己定一个新唤醒（这时 `when` / `note` 要有）；
    「列」= 看现在还挂着哪些；「取消」= 按 `id`（编号或关键词）撤掉一条。
    `where` 留空 = 醒来在**这个会话**说话；填某人的【消息前缀】= 醒来私聊他。
    """
    a = str(action or "").strip()

    if a in _LIST_ACTIONS:
        items = reminders.pending()
        out = {"ok": True, "一共": len(items),
               "还没响的": [reminders.row(i) for i in items[:20]]}
        # 刚响过的也报给她 —— 不然「刚才那条醒了吗」她答不上来（实测踩过）
        fired = reminders.done_recent()
        if fired:
            out["最近响过的"] = [{"醒来做什么": i.get("what"),
                                  "定在": reminders.human_at(i["at"]),
                                  "响的时刻": reminders.human_at(i.get("done") or i["at"]),
                                  "响成了吗": "没响（过太久错过了）" if i.get("missed") else "响了"}
                                 for i in fired[:5]]
        return out

    if a in _CANCEL_ACTIONS:
        which = str(id or when or note or "").strip()
        hit, raw = reminders.cancel(which)
        if not hit:
            return {"ok": False, "没找到": raw,
                    "现在有哪些": [reminders.row(i) for i in reminders.pending()[:20]],
                    "error": "没匹配上，看看编号或关键词对不对"}
        return {"ok": True, "取消了": [reminders.row(i) for i in hit]}

    if a and a not in _SET_ACTIONS:
        return {"ok": False, "error": "action 只认「列」和「取消」，留空就是定一个新的"}

    # ── 定一个新的 ──
    # ⭐ A6 安全阀：同一条唤醒链最多 settings.get("wake.maxChain") 层（默认 3，第 4 层直接拒）。
    #    `ctx["_wake_depth"]` 由 `agent._wake_ctx()` 在唤醒轮里放进来；普通轮没有 = 0
    #    （= 她主动设的第一层）。
    try:
        depth = max(1, int((ctx or {}).get("_wake_depth") or 0) + 1)
    except Exception:
        depth = 1
    max_chain = settings.get("wake.maxChain")
    if depth > max_chain:
        return {"ok": False, "error": "这条唤醒链已经 %d 层了，不能再套一个" % max_chain}
    try:
        at, _human = reminders.parse_when(when)
    except ValueError as e:
        return {"ok": False, "没听懂时间": str(e), "他说的": when,
                "error": "时间没听出来，先问清楚（可写「九点半」「20分钟后」「明天早上7点」）"}
    body = str(note or "").strip()
    if not body:
        # ⚠️ 这句话是定稿的（第 7 条）—— **结尾那个空格也在内**，别顺手 strip 掉。
        return {"ok": False, "error": "没说醒来要干什么 "}
    where_qq, where_name = "", ""
    w = str(where or "").strip()
    if w:
        qq, bad = _target(ctx, w)
        if not qq:
            return {"ok": False, "error": bad}
        where_qq, where_name = qq, _name_of(qq)
    # ⭐ A7′：「当时」的现场（到点那一轮要像那场对话的下一轮）。取的是**现在**这个快照 ——
    #    设完之后的新消息一条都进不来（用户明确要"只要当时的"）。
    rec = reminders.add(ctx.get("key"), ctx.get("group_id"), _who(ctx),
                        _cname(ctx), body, at, by=_who(ctx),
                        where_qq=where_qq, where_name=where_name, depth=depth,
                        hist=_wake_hist((ctx or {}).get("key")),
                        digest=_wake_digest(ctx))
    return {"ok": True, "编号": rec["id"], "时刻": reminders.human_at(at),
            "醒来做什么": rec["what"], "还有": reminders.ago(at - time.time()),
            "在哪说": reminders.where_text(rec)}


# ── 天气（不用 key 的开放接口）──────────────────────────────────────

_WMO = {0: "晴", 1: "少云", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
        51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨", 56: "冻雨", 57: "冻雨",
        61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
        71: "小雪", 73: "中雪", 75: "大雪", 77: "米雪",
        80: "阵雨", 81: "阵雨", 82: "强阵雨", 85: "阵雪", 86: "阵雪",
        95: "雷阵雨", 96: "雷阵雨夹冰雹", 99: "雷阵雨夹冰雹"}


def t_weather(ctx, city=""):
    city = (city or "").strip()
    if not city:
        # ⚠️ 这里**没有"默认城市"**了（用户点名去掉的）：他是哪儿人属于"关于他的信息"，
        #    该存在长期记忆库里，让她自己调 memory 那个工具查出来再传进来 ——
        #    而不是常驻在配置里。
        # ⚠️ （定稿）：失败话改成下面这句，一个字都不许改。
        return {"ok": False, "error": "没说哪个城市。要是他以前说过自己住哪，先查一下他的记忆。"}
    try:
        raw, _ = web.get("https://geocoding-api.open-meteo.com/v1/search?count=1&language=zh&name="
                         + urllib.parse.quote(city), timeout=12)
        j = json.loads(raw.decode("utf-8", "replace"))
        hit = (j.get("results") or [None])[0]
        if not hit:
            return {"ok": False, "error": "没找到这个城市：%s" % city}
        name = hit.get("name") or city
        lat, lon = hit.get("latitude"), hit.get("longitude")
    except Exception as e:
        return {"ok": False, "error": "查城市失败（%s）" % type(e).__name__}

    try:
        raw, _ = web.get(
            "https://api.open-meteo.com/v1/forecast?timezone=Asia%%2FShanghai&forecast_days=2"
            "&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m"
            "&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
            "&latitude=%s&longitude=%s" % (lat, lon), timeout=12)
        j = json.loads(raw.decode("utf-8", "replace"))
        cur = j.get("current") or {}
        day = j.get("daily") or {}
        out = {"ok": True, "城市": "%s（%s）" % (name, hit.get("admin1") or hit.get("country") or ""),
               "现在": "%s %s℃，体感 %s℃，湿度 %s%%，风 %s km/h" % (
                   _WMO.get(cur.get("weather_code"), "?"), cur.get("temperature_2m"),
                   cur.get("apparent_temperature"), cur.get("relative_humidity_2m"),
                   cur.get("wind_speed_10m")),
               "今天": "%s，%s~%s℃，降水概率 %s%%" % (
                   _WMO.get((day.get("weather_code") or [None])[0], "?"),
                   (day.get("temperature_2m_min") or [None])[0],
                   (day.get("temperature_2m_max") or [None])[0],
                   (day.get("precipitation_probability_max") or [None])[0]),
               "更新": (cur.get("time") or "").replace("T", " "),
               "来源": "open-meteo"}
        try:
            idx = (day.get("time") or []).index(time.strftime("%Y-%m-%d"))
        except Exception:
            idx = 1 if len(day.get("time") or []) > 1 else 0
        if len(day.get("time") or []) > idx + 1:
            k = idx + 1
            out["明天"] = "%s，%s~%s℃，降水概率 %s%%" % (
                _WMO.get((day.get("weather_code") or [None])[k], "?"),
                (day.get("temperature_2m_min") or [None])[k],
                (day.get("temperature_2m_max") or [None])[k],
                (day.get("precipitation_probability_max") or [None])[k])
        return out
    except Exception as e:
        base.log("open-meteo 没成：%r" % e)
    # 兜底：wttr.in（返回一段现成的天气文字，当材料用）
    try:
        raw, _ = web.get("https://wttr.in/%s?format=%%l:+%%c+%%t+%%f+%%h+%%w&lang=zh"
                         % urllib.parse.quote(city), timeout=12)
        txt = raw.decode("utf-8", "replace").strip()
        if txt and "Unknown" not in txt:
            return {"ok": True, "城市": city, "现在": txt, "来源": "wttr.in"}
    except Exception as e:
        base.log("wttr.in 也没成：%r" % e)
    return {"ok": False, "error": "两个天气源都没查通（手机网可能不通）"}


def t_search(ctx, q):
    return web.search(q)


def t_read_url(ctx, url):
    return web.fetch(url)


def t_send_private(ctx, text, who=""):
    uid, bad = _target(ctx, who)
    if not uid:
        return {"ok": False, "error": bad or "不知道发给谁"}
    text = (text or "").strip()
    if not text:
        return {"ok": False, "error": "没给内容"}
    # ⚠️ 这里**原来有一处 3000 字硬截断**
    #    （`text = text[:3000] + "\n…（太长，截断了）"`）—— 用户拍板「干脆别截断，
    #    自动切自动发」，所以把那两行删掉。`im.send_private` 自己会按上限
    #    （群/私聊不同，见 config 的 agent 一节）拆成几条依次发，**一个字都不丢**。
    #    这一段的其它逻辑一个字都没动（返回值、错误话术全照旧）。
    ok = im.send_private(uid, text)
    if not ok:
        return {"ok": False, "error": "这条私聊没发出去（NapCat 那边拒了或没连上）"}
    return {"ok": True, "已私聊发给": _name_of(uid), "QQ": uid, "字数": len(text)}


# ── 主动插话：说一句，然后接着干活 ──────────────────────────────────
#
# 用户要的用法：「先发一句『等下我查查』→ 继续查 → 再发结果」，都交给她自己判断。
# 所以这里是个**工具**（不是最终回复）：调完还能继续想、继续调别的工具。
# 最后 `handle()` 返回的那句话才是"这一轮的收尾话"（群里带引用回复）。


def _allow_send(ctx):
    """还能不能插话：只看**这一轮**发了几条。

    ⚠️ 曾经这里还有一道"每小时总量"的闸（怕 QQ 风控）。用户明确说不用管风控、
       删掉它 —— 所以现在唯一的硬上限就是每轮那 10 条（2026-10-30 用户从 15 调到 10）。
       计数挂在 ctx 上：一轮一个 ctx，两个会话并行也各算各的。
    """
    per_turn = settings.get("agent.maxSendsPerTurn")
    n = int(ctx.get("_sends") or 0)
    if n >= per_turn:
        return False, "这一轮已经主动发过 %d 条（上限 %d），剩下的收尾时说" % (n, per_turn)
    ctx["_sends"] = n + 1
    return True, ""


def t_say(ctx, text, who=""):
    """现在就往 QQ 里发一句 —— **发完还能继续想、继续调别的工具**。

    `to` 留空 = 发在当前这个会话里（群里就发群里）；填 QQ 号或她记得的名字 = 私聊那个人。
    ⚠️ 发出去的话也要记进对话线程，不然她下一轮不知道自己刚说过什么。
    """
    text = guards.strip_echo((text or "").strip())   # 中途插话也可能带上日志前缀，一样削
    if not text:
        return {"ok": False, "error": "没给要发的话"}
    ok, why = _allow_send(ctx)
    if not ok:
        return {"ok": False, "error": why}

    target = (who or "").strip()
    where = ""
    if target:
        # ⚠️ 踩过的坑：材料里写了"要发到群 123456789"，她就把这个**群号**填进了 to，
        #    而这里原来只认人 → 走成 send_private_msg → NapCat 回「无法获取用户信息」✗。
        #    所以：数字先看是不是**群号**（当前群 / 她理的群名单），是就发群；否则当人。
        # ⚠️ （「群管理」那一批）：群名单**统一走 `groups.known()`**
        #    （config ∪ 用户表 ∪ 面板加的 `groups.json`），这里不再自己读 config。
        groups_ = [str(g) for g in groups.known()]
        if ctx.get("group_id"):
            groups_.append(str(ctx["group_id"]))
        if target.isdigit() and target in groups_:
            ok = im.send_group(int(target), text)
            where = "群 %s" % target
            memory.record(("g", int(target)), "assistant", text)
            base.log("say：发到群 %s（她自己填了群号）：%s" % (target, text[:40]))
            return {"ok": bool(ok), "发出去了": where if ok else "",
                    "error": "" if ok else "没发出去（NapCat 拒了或没连上）"}
        qq = target if target.isdigit() and len(target) >= 5 else ""
        why = ""
        if not qq:
            # ⚠️ （）：这条弱路**切到统一认人**（`who.identify`）——
            #    以前只认 `memory.find`（称呼/记忆内容），**昵称**和**本群名片**都不认，
            #    跟别的工具"同一个词两个结果"。`ctx` 照样传下去（认本群那张名片要用群号）。
            qq, why = _identify_word(ctx, target)
        if not qq:
            # ⚠️ （）：**统一那两句** —— 撞名 → `_AMBIGUOUS`、
            #    没找到 → `_NOBODY`。⛔ 它原来自己那句「不知道…的 QQ 号…」**整句删掉了**
            #    （连同里面那个早就改掉的参数名）。
            return {"ok": False,
                    "error": (_AMBIGUOUS if why == "ambiguous" else _NOBODY) % target}
        ok = im.send_private(int(qq), text)
        where = "私聊 %s（QQ %s）" % (target, qq)
    elif ctx.get("is_group"):
        ok = im.send_group(ctx.get("group_id"), text)
        where = "群 %s" % ctx.get("group_id")
    else:
        ok = im.send_private(_who(ctx), text)
        where = "私聊 %s" % _cname(ctx)

    if not ok:
        return {"ok": False, "error": "没发出去（NapCat 拒了或没连上）"}
    if ctx.get("key"):
        memory.record(ctx["key"], "assistant", text)     # 她说过的话要进对话线程
    base.log("她主动插了一句（%s）：%s" % (where, text[:60]))
    return {"ok": True, "发出去了": where, "字数": len(text),
            "提示": "这条已经发出去了，不是收尾那句；你还可以接着办事"}


def t_end_turn(ctx):
    """主动结束这一轮：之后**不再请求模型**，也不再发任何字。

    ⚠️ 2026-10-30（定稿）：这是**条件出现**的工具 —— 只有触发词 / 随机接话 /
       唤醒到点 / 这一轮已经用 `say` 说过话（`ctx["_sends"] >= 1`）时才进目录，
       ⛔ @她 / 私聊正常对话 / 播报里根本看不到它（见 `schemas(ctx)`）。
       已经用 `say` 发出去的话照旧；这里只把"这一轮到此为止"记在 ctx 上，
       由 `llm.run_turn` 在**这一批工具执行完之后**立刻收尾（不再问模型）。
    """
    if isinstance(ctx, dict):
        ctx["_end_turn"] = True
    return {"ok": True}


# ── 技能（知识锁的"开锁"那一下）────────────────────────────────────

def t_skill(ctx, name=""):
    """读一个技能的完整说明（**知识锁**：读完才解锁那个包的工具）。

    2026-10-31 逐字定死的两种返回：

        读到 → `<skill_content name="名字">` + SKILL.md 正文原文 + `</skill_content>`
        没有 → error = `没有叫「名字」的【技能】。看【技能目录】里的名字。`

    ⚠️ 读完把这个包记进 `ctx["_skills_opened"]`（会话级、最新在末尾）——
       `schemas(ctx)` 下一步就会把它的工具 schema **追加**到目录末尾。
    ⚠️ 返回的是**纯文本**（`_raw_text`）：`result_text()` 会原样交给模型，
       ⛔ 不套 JSON（那会把换行转义成 \n，正文就不是原文了）。
    """
    from . import capabilities
    n = str(name or "").strip()
    body = capabilities.skill_body(n) if n else None
    if body is None:
        return {"ok": False, "error": "没有叫「%s」的【技能】。看【技能目录】里的名字。" % n}
    cap = capabilities.get(n)
    capabilities.mark_opened(ctx, cap.name if cap is not None else n)
    return {"ok": True, "_raw_text": body}


# ── 目录 ────────────────────────────────────────────────────────────
#
# 描述只有一句「什么时候用」。参数名一律英文（中文参数名也能用，但英文稳），
# 描述里说清每个参数是什么、以及**什么时候该用它而不是别的**（DSH 的写法：
# "用 X，不要用 Y" 比"必须遵守"清单省字且有效）。
#
# ⚠️ 条件出现的工具（不在常态目录里，由 `schemas(ctx)` 每步现算）：
#   · `end_turn` —— 触发词 / 随机接话 / 唤醒到点 / 这一轮已经 say 过；
#   · 扩展包的工具 —— 她 `skill(名字)` 读过那个技能之后才解锁（每次最多 6 个包）。
# `pc_status`（战况）搬进了示例包 `examples/packages/pc-status/`（默认不装）。

TOOLS = [
    {"name": "now", "fn": t_now, "desc": "看现在几点、今天几号、星期几。",
     "params": {}},

    {"name": "memory", "fn": t_memory,
     "desc": "查或记某个人的记忆（住哪、性别、生日、口味、身份、喜好等）",
     "params": {"who": ("string", "【消息前缀】或「自己」；留空=当前说话的人", False),
                "ask": ("string", "查什么；留空=全部", False),
                "text": ("string", "要记或要改的一条事实", False)}},

    {"name": "user_info", "fn": t_user_info,
     "desc": "查用户的资料：QQ 号、称呼、QQ 昵称、本群名片。",
     "params": {"who": ("string", "【消息前缀】；留空=当前说话的人", False),
                "fields": ("string", "想知道的项，留空=全给", False)}},

    {"name": "callname", "fn": t_callname,
     "desc": "给某个人定【称呼】",
     "params": {"who": ("string", "【消息前缀】；留空=当前说话的人", False),
                "name": ("string", "他要你怎么叫他（新的【称呼】）；留空=取消，回到他的群名片/昵称", False)}},

    {"name": "wake", "fn": t_wake,
     "desc": "给自己设一个唤醒：到点你会被叫醒执行任务",
     "params": {"action": ("string", "留空=定新的；列=看现有的；取消=撤一条", False),
                "when": ("string", "什么时候唤醒，例如 九点半 / 20分钟后 / 明天早上7点", False),
                "note": ("string", "醒来时给自己看的说明：为什么醒、做什么", False),
                "where": ("string", "醒来在哪儿说话：留空=当前会话；填某人的【消息前缀】=私聊他", False),
                "id": ("string", "要撤的那一条：编号或关键词", False)}},

    {"name": "plan", "fn": t_plan,
     "desc": "多步任务先建一份计划（目标 + 步骤表）；一步能办完的不用。",
     "params": {"objective": ("string", "这次要办成什么，一句话（可选）", False),
                "steps": ("array", "每步一条带状态（未开始/进行中/已完成）；整张替换，最多一个进行中", True,
                          {"items": {"type": "object",
                                     "properties": {"content": {"type": "string"},
                                                    "status": {"type": "string",
                                                               "enum": ["未开始", "进行中", "已完成"]}},
                                     "required": ["content"]}})}},

    {"name": "history", "fn": t_history,
     "desc": "回看你上下文里没有的更早发言",
     "params": {"count": ("integer", "几条，默认 30，最多 100", False),
                "who": ("string", "只看这个人说的：【消息前缀】；留空=所有人", False),
                "q": ("string", "只看含这个词的消息；条件之间是且", False),
                "after": ("string", "只看这个时刻之后的：昨天晚上 / 今天早上 / 3天前", False),
                "before": ("string", "只看这个时刻之前的：昨天晚上 / 今天早上 / 3天前", False)}},

    {"name": "weather", "fn": t_weather,
     "desc": "查某个城市的天气。",
     "params": {"city": ("string", "城市名，例如 青岛")}},

    {"name": "search", "fn": t_search,
     "desc": "上网搜，返回一段答案和几条来源。",
     "params": {"q": ("string", "搜索词")}},

    {"name": "read_url", "fn": t_read_url,
     "desc": "打开一个网址，读它的正文。搜到看着有用的链接时用它。",
     "params": {"url": ("string", "http/https 网址")}},

    {"name": "send_private", "fn": t_send_private,
     "desc": "给某个人单独私聊发消息",
     "params": {"text": ("string", "要私聊发出去的完整内容"),
                 "who": ("string", "发给谁：【消息前缀】；留空=当前说话的人", False)}},

    {"name": "say", "fn": t_say,
     "desc": "先在当前会话说一句，说完还能接着做事。",
     "params": {"text": ("string", "要发出去的那句话"),
                "who": ("string", "发给谁：【消息前缀】就是私聊他；留空=发在当前会话里", False)}},

    {"name": "skill", "fn": t_skill,
     # ⚠️ 名字 / 说明 / 参数说明是**逐字批的**，⛔ 一个字都不许改。
     "desc": "读取一个技能的完整说明",
     "params": {"name": ("string", "【技能】名字")}},
]

_BY_NAME = {t["name"]: t for t in TOOLS}

# ── 条件出现的工具──────────────────────────
#
# `end_turn` **不在** `TOOLS` 里：常态目录是 `names()` 那 12 个（`TOOLS` 去掉
# 条件出现的 `pc_status`），它只在下面四种场合出现
# （由 `schemas(ctx)` 每步现算，所以 `say` 之后**下一步**才看得到它）：
#   ① `ctx["_trigger"] == "触发词"`  ② == "chime"（随机接话 1%）
#   ③ == "wake"（唤醒到点）          ④ 同一轮里 `ctx["_sends"] >= 1`（她已经用 say 说过话）
# ⛔ @她 / 私聊正常对话 / 播报 → 不出现（那几种场合她只能回话）。
# ⚠️ `call()` 照旧能派发它（`_BY_NAME` 里有），只是目录里看不看得见由 `schemas(ctx)` 决定。
END_TURN = {"name": "end_turn", "fn": t_end_turn,
            "desc": "主动结束此轮对话，不再说话", "params": {}}


def _offer_end_turn(ctx):
    """这一轮该不该把 `end_turn` 放进工具目录（四种场合，见上面那段）。"""
    if not isinstance(ctx, dict):
        return False
    if str(ctx.get("_trigger") or "") in ("触发词", "chime", "wake"):
        return True
    try:
        return int(ctx.get("_sends") or 0) >= 1
    except Exception:
        return False


_BY_NAME[END_TURN["name"]] = END_TURN

# ── 扩展包的工具──────────────────────────────
#
# 扩展包（`fgbot/capabilities.py`）声明了哪些工具，**不常驻**在目录里：
#   ① 技能目录（一条独立的 user 消息，见 `agent._build`）告诉她"有这些技能"；
#   ② 她调 `skill(name)` 读一个技能 → 这个包的工具 schema 才**追加**到本轮及后续
#      请求的 tools **末尾**（不重排已有工具）；同时最多 6 个包，超了摘最久没用的；
#   ③ 一场对话结束 / 换会话 → 清空（`capabilities.clear_sessions()`）。
# ⚠️ `end_turn` / 扩展包的工具都由 `schemas(ctx)` 每步现算 —— 传 ctx 才有区别。
def schemas(ctx=None):
    """给模型看的工具目录（OpenAI/DeepSeek 的 function 格式）。

    参数写法：`名字: (类型, 说明)` 或 `名字: (类型, 说明, False)` —— 第三个位置给
    False 就是"可选参数"（不进 required）。JSON Schema 支持可选，模型也看得懂。
    ⚠️ 2026-10-30（`plan.steps`）：多了第四个位置 —— 一个 dict，原样并进这个参数的
       schema（`plan` 的步骤表要 `items` / `enum`，光给类型模型写不对形状）。
    ⚠️ 2026-10-30（`end_turn`）：`ctx` 是可选参数 —— 传了就按 `_offer_end_turn(ctx)`
       现算要不要带上那个收尾工具；**不传/传 None 也不炸**。
    ⚠️ 2026-10-31（扩展包）：常态目录 = **13 个**（`TOOLS` 那 12 个 + `skill`）；
       解锁了扩展包之后，它们的工具**追加在末尾**（最多 6 个包），再撞上 end_turn
       的场合还会再多一个。所以每一步都要重新调一次（`llm.run_turn` 就是这么做的）。
    ⚠️ 「工具列表变了」记一行日志（`capabilities.note_tool_list`）—— 排查缓存问题用。
    """
    catalog = list(TOOLS)
    if _offer_end_turn(ctx):
        catalog.append(END_TURN)
    out = []
    for t in catalog:
        props, req = {}, []
        for k, spec in (t.get("params") or {}).items():
            ty, d = spec[0], spec[1]
            props[k] = {"type": ty, "description": d}
            if len(spec) >= 4 and isinstance(spec[3], dict):
                props[k].update(spec[3])
            if len(spec) < 3 or spec[2] is not False:
                req.append(k)
        out.append({"type": "function",
                    "function": {"name": t["name"], "description": t["desc"],
                                 "parameters": {"type": "object", "properties": props,
                                                "required": req}}})
    # ⭐ 知识锁：解锁了（并且现在可用）的扩展包工具 → **追加在末尾**，不重排已有的。
    try:
        from . import capabilities
        out.extend(capabilities.tool_schemas(ctx))
        capabilities.note_tool_list(
            ctx, [t["function"]["name"] for t in out])
    except Exception:
        base.log_exc("扩展包的工具目录")
    return out


def names():
    """**常态目录**（13 个 = 12 个内置 + `skill`）。

    ⚠️ `end_turn` 和扩展包的工具都不在这里：它们是**条件出现 / 解锁后才有**的，
       由 `schemas(ctx)` 每步现算。`pc_status`（战况）2026-10-31 搬成了第一个
       示例包（`examples/packages/pc-status/`，默认不装），要她先 `skill("pc-status")` 解锁。
    """
    return [t["name"] for t in TOOLS]


def call(name, args, ctx):
    """执行一个工具。**永远返回 dict，永远不抛** —— 炸了就把事实给她。

    ⚠️ 2026-10-30（A7′）：每个调用**记一次**进 `ctx["_tool_log"]`（`(name, args, brief)`）——
       设唤醒时用它拼「你当时查到的数据」。`ctx` 每轮都是新的，⛔ 不用清理；
       一次调用记一次，同一批里不会重复追加（`llm.run_turn` 对每个 tool_call 只调一次）。
       ⛔ 返回给她的 dict 一个字都没动（记日志是旁路，改不到结果）。
    ⚠️ 2026-10-31（扩展包）：内置工具里找不到 → 交给 `capabilities.dispatch()`。
       包里的 `run(args, ctx)` 抛的异常在这里**同一处**兜住（和内置工具同一句兜底）；
       超时也一样（`TimeoutError`）。
    """
    t = _BY_NAME.get(name)
    if t is None:
        try:
            from . import capabilities
            hit, res = capabilities.dispatch(name, args if isinstance(args, dict) else {},
                                             ctx)
        except TypeError as e:
            res = {"ok": False, "error": "参数不对（%s）" % e}
            hit = True
        except Exception as e:
            base.log_exc("扩展包工具 %s" % name)
            res = {"ok": False, "error": "这个工具出错了：%s" % type(e).__name__}
            hit = True
        if hit:
            _log_tool(ctx, name, args, res)
            return res
        return {"ok": False, "error": "没有这个工具：%s" % name}
    if not isinstance(args, dict):
        args = {}
    try:
        sig = t["fn"]
        want = list((t.get("params") or {}).keys())
        kw = {k: args.get(k) for k in want if k in args}
        res = sig(ctx, **kw)
    except TypeError as e:
        res = {"ok": False, "error": "参数不对（%s）" % e}
    except Exception as e:
        base.log_exc("工具 %s" % name)
        res = {"ok": False, "error": "这个工具出错了：%s" % type(e).__name__}
    _log_tool(ctx, name, args, res)
    return res


def result_text(name, res):
    """工具结果 → 塞进 `tool` 消息里的字符串。

    ⚠️ 空结果也要给点东西：DeepSeek 那边 `tool` 消息空着会让配对看起来不对
       （DSH 的适配器就是用一个 "(no output)" 兜的）。
    ⚠️ 2026-10-30（B2）：`search` / `read_url` / `history` 这三个的结果太长被切短时，
       **末尾补一句通用的事实**（用户批的第 14 条）—— 不报具体字数。
       别的那几个工具照旧静默截断（一个字节的新文本都没有）。
    ⚠️ 2026-10-31（`skill`）：带 `_raw_text` 的结果**原样**交出去
       （`<skill_content>…</skill_content>` 就是给模型看的那段原文，⛔ 不许套 JSON）。
       它**不截断**：技能正文可能比 `clipChars` 长，切了就不是"完整说明"了。
    """
    if isinstance(res, dict) and res.get("_raw_text") is not None:
        return str(res["_raw_text"]) or "(no output)"
    try:
        s = json.dumps(res, ensure_ascii=False)
    except Exception:
        s = json.dumps({"ok": False, "error": "结果没法序列化"}, ensure_ascii=False)
    clip = settings.get("toolkit.clipChars")
    if len(s) > clip:
        s = s[:clip]
        if name in CLIP_TOOLS:
            s = s + "\n" + CLIP_NOTE
    return s or "(no output)"


# 工具结果塞进请求时最多留多少字（默认 6000；运行时 settings.get("toolkit.clipChars")）
CLIP_CHARS = 6000
# 只在**会给出长材料**的这三个工具上说这一句
CLIP_TOOLS = ("search", "read_url", "history")
CLIP_NOTE = "（这条被截断了：内容太长，这里只是一部分）"
