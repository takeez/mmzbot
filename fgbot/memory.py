#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""她的记性：**对话线程** + **按 QQ 分的长期记忆库**。

═══ 两个功能，别混（用户特意区分过）═══

**① 称呼功能**（字段 `name`）—— 一个人说「以后叫我张三」之后，**程序层面**就把他
   消息行的前缀从群名片换成「张三」：

       张三（QQ 10001）: 你好

   ⚠️ 它**不需要她调用任何工具**，每一轮她天然就知道 —— 它是长在消息前缀里的**结构**，
      不是"附加消息"。改称呼只有两条路：他自己再说一次，或者她说「别这么叫了」。

**② 记忆功能**（字段 `facts`）—— 关于这个人的事（住哪、生日、口味、什么身份）。
   她**要用的时候才调 `memory` 这个工具去取**，平时一个字都不在上下文里。

一个 QQ 号一块地方：

    {"10001": {"name": "张三", "facts": ["住在杭州", "喝咖啡不加糖"],
                    "cards": {"123456789": "主群那张名片"}, "at": …},
     "1111111111": {"facts": ["爱吃辣"]}}

⚠️ **群名片按群各存一张** —— `cards: {"<群号>": "<名片>"}`。

  · `touch()` 只在**群聊**里写（私聊没有"本群名片"这回事 → 一个字都不写）；
  · 认人只看**当前群**那张：`who.resolve()` 拿到 `ctx["group_id"]` 才启用名片档，
    私聊 / 没群号 → 名片档**整档不可用**；
  · 老的单字段 `card`（"最后一次见到的"那张）**从这天起只当历史残留**：
    本模块既不读它、也不再写它。要哪张名片走 `card_in(qq, 群号)`。

三条硬约定：

① **谁说的就记在谁名下**：他说「记住我住杭州」，那条只进他自己那块，不会串到别人身上。
② **默认不进上下文**：聊天时**不**把任何人的记忆塞进提示词 —— 需要某个人的信息，
   她自己调 `memory` 那个工具去取（这样她的注意力不会被"他住哪""谁是机主"这类背景占着）。
③ **只取一个人的那块**：`record_of(qq)` / `memory` 那个工具只返回那一个人的内容，
   **绝不把整份文件（含别人的信息）发出去**。

═══ 对话线程 ═══

三条从 v1 的翻车里抄下来的硬规矩（都是**结构**，不是提示词）：

① **不同人的消息绝不合并成一条。**
   踩过：群里 A 说完 B 接着说，她一句没回（她选了不回），渲染历史时按
   「连续的同类角色」合并，两条就被拼成一条 user 消息：
   `A（QQ 111）: 帮我…` 和 `B（QQ 222）: 你真可爱` 挤在同一段里。
   她看到一条消息里两个名字，就把两件事一起答了，还把 B 的事算到 A 头上。
   → 这里只合并**同一个 QQ 号**的连续消息（而且要中间没有她的回复）。

② **谁在说话写进消息前缀，而且必须带 QQ 号。**
   光写名字不够：机主的群名片叫「已深度思考20秒」，模型分不清那是"说话人"
   还是"系统状态"，于是问他"我叫什么"，她答的是背景里刷屏那位的名字。
   → 每条都是 `名字（QQ 123456）: 话`。

③ **每场对话一个串行 worker，严格先来先服务。**
   `server.py` 是每条消息开一个线程来调 `handle()` 的，同一个人连发三条
   就会三个线程一起读历史、一起写历史 —— 她会答串。所以按 `ctx["key"]`
   （群一把钥匙、私聊一把钥匙）排队，先来先服务；排满 `queueMax` 条之后才丢。

⚠️ 跨轮次只保留**看得见的对话**（用户说的话 + 她发出去的话），工具调用
   藏在单轮内部。原因是手机的上下文很贵，而且裁剪历史时如果切断了
   `tool_calls` 和它的 `tool` 回复之间的配对，DeepSeek 会直接 400
   （实测：「An assistant message with 'tool_calls' must be followed by tool
   messages responding to each 'tool_call_id'」）。对话线程只留对话，就没有这个雷。
"""

import re
import threading
import time

from . import base, napcat, settings, store

MEMORY = "memory.json"            # ⚠️ 手机上的状态文件，deploy.py 的 NEVER 名单里有它
# ⚠️ 下面这些数改成运行时 settings.get(...) 现读；常量只留着当
#    默认值引用 / 自检用。唯一真源在 settings.REGISTRY。
MAX_KEEP = 120                    # 一条时间线在内存里最多留多少条（防长跑吃内存）
DEFAULT_RENDER = 16               # 渲染进请求的历史条数（settings 的 llm.threadLimit）
DEFAULT_PRIVATE = 4096            # 私聊：按**字数**切窗口（settings 的 llm.historyLimitPrivate）
MAX_FACTS = 30                    # 一个人最多记多少条记忆（满了丢最早的）

# 写前备份留几版（memory-keeper 动记忆之前会调 `backup_versions()`）
BACKUP_PREFIX = "memory-backup-"
BACKUP_KEEP = 5

# 私聊自动压缩（B3）：摘要套的那层壳 / 那次请求的正文 —— 。
SUMMARY_SHELL = "<compacted-summary>\n%s\n</compacted-summary>"
SUMMARY_BODY = """把下面这段对话压成不超过 3 条事实，每条一行、一句话；整段尽量不超过 300 字。不要解释

%s"""
SUMMARY_MAX_TOKENS = 500

_LOCK = threading.RLock()
_CONVS = {}
_COMPACT = {}                     # key -> {"summary": str, "upto": 条目序号}


# ── 时间线 ──────────────────────────────────────────────────────────

class _Conv(object):
    def __init__(self):
        self.entries = []          # [{"role":"user"/"assistant","text":…,"qq":…,"name":…,"at":…,"n":…}]
        self.q = []
        self.lock = threading.RLock()
        self.worker = None
        self.n = 0                 # 这条时间线的序号（自动压缩要知道"压到哪一条了"）


def _conv(key):
    with _LOCK:
        c = _CONVS.get(key)
        if c is None:
            c = _CONVS[key] = _Conv()
        return c


def record(key, role, text, qq=None, name=None):
    """往时间线上记一条。**按到达顺序**记（谁先说话谁在前）。"""
    text = (text or "").strip()
    if not text:
        return
    c = _conv(key)
    max_keep = settings.get("memory.maxKeep")
    with c.lock:
        c.n += 1
        c.entries.append({"role": role, "text": text, "qq": qq,
                          "name": name or (str(qq) if qq else ""), "at": time.time(),
                          "n": c.n})
        if len(c.entries) > max_keep:
            del c.entries[:len(c.entries) - max_keep]


def _render_entries(entries, grp, gid, keep_n=False):
    """条目 → messages（同一个人连发的几条合并成一条；每行带 `名字: ` 前缀）。

    ⚠️ 她自己的话**不合并**（和以前一样一条一条放）—— 这里只合并同一个人的连续发言。
    """
    out = []
    for e in entries:
        if e["role"] == "assistant":
            out.append({"role": "assistant", "content": e["text"], "_n": e.get("n") or 0})
            continue
        # 前缀**现在现算**（称呼/昵称都可能刚改过），不存快照 ——
        # 但条目里那份 name 当兜底传进去（见 display_name 的说明）。
        # ⚠️ （）：历史行**也按"所在群"那张名片** ——
        #    历史消息都在同一个会话里，所以直接把**当前群号**传下去，
        #    前缀就走「称呼 → 本群名片 → 昵称 → QQ 号」那四级（⛔ 不再拼方括号那截）。
        line = "%s: %s" % (display_name(e.get("qq"), grp, e.get("name"), group_id=gid),
                           e["text"])
        if out and out[-1]["role"] == "user" and out[-1].get("_qq") == e.get("qq"):
            out[-1]["content"] += "\n" + line
            out[-1]["_n"] = max(out[-1].get("_n") or 0, e.get("n") or 0)
        else:
            out.append({"role": "user", "content": line, "_qq": e.get("qq"),
                        "_n": e.get("n") or 0})
    if keep_n:
        return out
    for m in out:                                  # 私有字段别发给协议层
        m.pop("_qq", None)
        m.pop("_n", None)
    return out


def _take_tail(msgs, budget):
    """私聊那个**按字数**的窗口：从最新往回**累加整条**，停在下一条的开头。

    ⚠️ **单条超预算就整条给**（宁可超，不切半句）—— 的切法。
    """
    budget = int(budget or 0)
    if budget <= 0 or not msgs:
        return list(msgs)
    total, start = 0, len(msgs)
    for i in range(len(msgs) - 1, -1, -1):
        L = len(str(msgs[i].get("content") or "")) + 1
        if start < len(msgs) and total + L > budget:
            break
        total += L
        start = i
    return msgs[start:]


def _tidy_summary(s):
    """摘要收拾成「≤3 条、整段 ≤300 字」（用户定的是"尽量"，这里按硬上限兜一下）。"""
    lines = [x.strip() for x in str(s or "").splitlines() if x.strip()]
    out, total = [], 0
    for ln in lines[:3]:
        if total + len(ln) > 300:
            break
        out.append(ln)
        total += len(ln)
    if not out:
        out = [str(s or "").strip()[:300]]
    return "\n".join([x for x in out if x])


def _compact(key, overflow):
    """把**滑出窗口的那一段**压成摘要（合并式：上一次摘要 + 这一段 → 新的）。

    返回要挂在上下文最前面的那段摘要正文；没压成就返回上一次的（可能是空串）。
    """
    st = _COMPACT.setdefault(key, {"summary": "", "upto": -1})
    fresh = [m for m in overflow if int(m.get("_n") or -1) > int(st["upto"])]
    if not fresh:
        return st["summary"]
    parts = ([st["summary"]] if st["summary"] else []) + \
            [str(m.get("content") or "") for m in fresh if m.get("content")]
    text = "\n".join(parts).strip()
    if not text:
        return st["summary"]
    try:
        from . import llm
        got = llm.utility_text([{"role": "user", "content": SUMMARY_BODY % text}],
                               max_tokens=settings.get("memory.summaryMaxTokens"))
    except Exception as e:
        base.log("私聊压缩：这次没压成（%r）—— 先留着旧摘要，下一条再试" % (e,))
        return st["summary"]
    if not got:
        base.log("私聊压缩：模型回了空的 —— 先留着旧摘要，下一条再试")
        return st["summary"]
    st["summary"] = _tidy_summary(got)
    st["upto"] = max(int(m.get("_n") or -1) for m in fresh)
    base.log("私聊压缩：把 %d 条旧对话压成 %d 字摘要（一共不超过 3 条）"
             % (len(fresh), len(st["summary"])))
    return st["summary"]


def render(key, limit=None, drop_last=False):
    """把时间线渲染成给模型的 messages（**只含 user/assistant**）。

    · 同一个人连发的几条合并成一条（用换行），中间隔了别人的话或她的回复就不合并；
    · 每行都带 `名字: ` 前缀；
    · `drop_last=True` 时去掉最后一条 —— 当前这条要由 agent 层单独拼
      （它可能要带图，必须保证是最后一条，而且不能被任何说明文字污染）。

    ⚠️ （B1 / B3）**群聊和私聊切法不一样**
       · 群聊：还是「最近 `threadLimit` 条」（16 段，连发合并成一段 —— 沿用现状）；
       · 私聊：按**字数**（`llm.historyLimitPrivate`，默认 4096）**从最新往回累加整条**，
         停在下一条的开头；单条超预算就整条给；
       · 私聊滑出去的那一段**自动压成摘要**（`<compacted-summary>` 那层壳），
         摘要挂在历史最前面 —— 永远只有一份（每次都跟上一份合并着压）。
       ⚠️ `limit` 是显式给的那种（自检/老调用）→ 照老行为按条数切，两套互不影响。
    """
    c = _conv(key)
    with c.lock:
        entries = list(c.entries)
    if drop_last and entries:
        entries = entries[:-1]
    grp = (key[0] == "g") if isinstance(key, (tuple, list)) and key else False
    gid = str(key[1]) if grp and len(key) > 1 else ""

    if limit is not None:
        entries = entries[-max(2, int(limit)):]
        return _render_entries(entries, grp, gid)

    if grp:
        lim = settings.get("llm.threadLimit")
        entries = entries[-max(2, lim):]
        return _render_entries(entries, grp, gid)

    # ── 私聊：字数窗口 + 自动压缩 ──
    msgs = _render_entries(entries, grp, gid, keep_n=True)
    budget = settings.get("llm.historyLimitPrivate")
    kept = _take_tail(msgs, budget)
    overflow = msgs[:len(msgs) - len(kept)] if kept else msgs
    summary = _compact(key, overflow) if overflow else \
        (_COMPACT.get(key) or {}).get("summary") or ""
    out = []
    if summary:
        out.append({"role": "user", "content": SUMMARY_SHELL % summary})
    for m in kept:
        m.pop("_qq", None)
        m.pop("_n", None)
    out.extend(kept)
    return out


def count(key):
    with _conv(key).lock:
        return len(_conv(key).entries)


def threads():
    with _LOCK:
        return len([k for k, c in _CONVS.items() if c.entries])


def reset(keys=None):
    """清对话记忆。keys=None = 全清（面板的「重置对话」/ control.txt 走这里）。

    ⚠️ 只清**对话**：称呼表、唤醒账本不动 —— 手机上的 ctl 脚本写的
       「重置对话」是「当第一次见你」，不是「把你说过的话也忘掉」。
    ⚠️ （扩展包 / 知识锁）：**一场对话结束 / 换会话 → 已解锁的技能清空**
       （知识不跨会话乱串）。收口就放在这里 —— 所有"重置对话"的路都经过它。
    """
    try:
        from . import capabilities
        if keys is None:
            capabilities.clear_sessions()
        else:
            for k in keys:
                capabilities.clear_sessions(k)
    except Exception:
        base.log_exc("重置对话时清空扩展包解锁")
    if keys is None:
        with _LOCK:
            for c in _CONVS.values():
                with c.lock:
                    c.entries = []
            _COMPACT.clear()
        base.log("对话记忆已重置（全部）")
        return True
    for k in keys:
        with _conv(k).lock:
            _conv(k).entries = []
        _COMPACT.pop(k, None)
    return True


# ── 一场对话一个 worker：严格先来先服务 ─────────────────────────────

# 「前台先走了，job 还在后台算」—— handle() 返回这个哨兵（不是字符串），
# `server.py` 看到它就**什么都不发**：句子的发送权在 job 那边（见 LATE 事件）。
# 用哨兵而不是 None：None 是「她决定不说话」，两个意思绝不能混。
LATE_PENDING = object()

# 一条等待的状态。**发送权只能被认领一次** —— 这就是"同一句话绝不发两遍"的硬保证：
#   · 前台等到了（正常路径）→ 前台带走句子去发；
#   · 前台超时走了（迟到路径）→ 后台 job 自己认领去发。
# 两边都要 `with item.lock:` 抢同一把锁，谁先抢到谁发，另一个看到 is_sent() 就闭嘴。
LATE = "late"          # 后台补发时写字用的标记（日志要能看出这是补发的那条）
_SENT = "sent"
_FG_WAIT = "fg"        # 前台等到了
_FG_TIMEOUT = "fg-timeout"


class _QueuedItem(object):
    def __init__(self, job, late=None):
        self.job = job
        self.late = late             # 前台超时后由后台调它把结果发出去
        self.done = threading.Event()
        self.reply = None            # job 算出来的那句话（算完才写，读它要先 done.wait）
        self.finished = False
        self.lock = threading.Lock()
        self.waited = 0              # 谁先到的：_FG_WAIT / _FG_TIMEOUT
        self.sent_by = ""            # 谁发的：_SENT / LATE / 空=还没发
        self.async_at = 0.0          # 前台放弃等待的时刻（算"迟到几秒"用，纯日志）

    def is_sent(self):
        with self.lock:
            return bool(self.sent_by)

    def mark_sent(self, who):
        with self.lock:
            self.sent_by = who
            return True


def submit(key, job, timeout=300, late=None):
    """把 `job()` 排到这把钥匙的队尾，等它做完并返回结果。

    为什么不在 handle() 里直接做：`server.py` 每条消息一个线程，
    同一个人连发三条就会并发跑三轮 LLM、并发读写同一份历史 —— 她会答串。
    排队的代价是慢一点，换来的是「她按顺序读、按顺序答」。

    ═══ `late` 回调：**等不到 ≠ 丢掉** ═══

    `timeout` 不是"这条不回了"，只是"我在这儿不陪等了"的分界：超过了就
    `handle()` 先回 `LATE_PENDING`（前台什么都不发），后台 job 算完之后
    自己把结果交给 `late(item, reply)` 去发。

    ⚠️ 踩过的事故：`maxWaitSeconds` 一到就 `return None`
    而 server.py 那边 `if not reply: return` 静默不发 —— 后台 job 后来算出来的话
    **一个字都没出去**，用户等 45 分钟看到的是一片空白。现在这条路补上了。

    `late(item, reply)` 拿到的 `item` 有 `is_sent()` / `mark_sent(who)`：
    **必须**用它们认领发送权（前台可能已经发过了，见 _QueuedItem 的注释）。
    返回 None = 这场对话排满了，这条从头到尾没人管（跟以前一样丢掉）。
    """
    c = _conv(key)
    qmax = int((base.cfg().get("llm") or {}).get("queueMax") or 8)
    item = _QueuedItem(job, late)
    with c.lock:
        if len(c.q) >= qmax:
            base.log("这场对话排满了（%d 条），丢掉一条" % qmax)
            return None
        c.q.append(item)
        if c.worker is None or not c.worker.is_alive():
            c.worker = threading.Thread(target=_work, args=(c,), daemon=True)
            c.worker.start()
    item.done.wait(timeout)
    with item.lock:
        if item.finished:
            item.waited = _FG_WAIT
            return item.reply
        # 前台先走了 —— 从此这条的发送权归后台（_work 里用 late 回调发）。
        item.waited = _FG_TIMEOUT
        item.async_at = time.time()
    base.log("排队等太久了（>%d 秒），前台先不等了 —— 后台算完会**补发**（不会丢）" % timeout)
    return LATE_PENDING


def _work(c):
    while True:
        with c.lock:
            if not c.q:
                c.worker = None
                return
            item = c.q.pop(0)
        try:
            item.reply = item.job()
        except Exception:
            base.log_exc("处理一条消息")
        item.finished = True
        item.done.set()
        # ⚠️ set 之后前台随时可能带着句子走人 —— "谁发"必须在这把锁里定死：
        #    前台等到了 → 它在自己那边（submit 里）先拿到锁、把句子带走；
        #    前台超时了 → waited 已是 _FG_TIMEOUT，这单归我，补发。
        #    抢不到锁 = 前台正在认领 = 这一次由前台发，我什么都不做。
        if not item.lock.acquire(blocking=False):
            continue
        try:
            mine = (item.waited == _FG_TIMEOUT) and callable(item.late)
        finally:
            item.lock.release()
        if mine:
            try:
                item.late(item, item.reply)
            except Exception:
                base.log_exc("补发一条迟到的回复")


# ── 长期记忆库：一个 QQ 号一块地方 ──────────────────────────────────
#
# 每块地方两个字段：
#   name  —— **称呼功能**（他让她怎么叫；长在消息前缀里，每轮都知道）
#   facts —— **记忆功能**（关于他的事；要用的时候她自己调 memory 那个工具）

# 「把自己抬到她头上」的称呼，**不记**。用户的原话：「那肯定是不行的」。
# 这是数据完整性检查，不是提示词里的规矩 —— 提示词是概率的，这里是硬的。
THRONE = ("主人", "主子", "爸爸", "爹", "老爸", "父亲", "皇上", "圣上", "陛下",
          "万岁", "殿下", "老爷", "少爷", "大人", "上帝", "神仙", "祖宗")

_CTRL = re.compile(r"[\x00-\x1f\x7f\u200b-\u200f\u202a-\u202e\u2066-\u206f]")


def clean_name(s):
    s = _CTRL.sub("", (s or "")).strip()
    s = s.strip("「」『』\"'“”‘’ 　")
    return re.sub(r"\s+", " ", s)[:12]


def throne_why(name):
    """这个称呼为什么不能记。能记就返回空串。"""
    n = clean_name(name)
    if not n:
        return "空的"
    for bad in THRONE:
        if bad in n:
            return bad
    if len(n) > 8:
        return "太长了（像句话，不像称呼）"
    return ""


def _load_names():
    d = store.read_json(MEMORY) or {}
    return d if isinstance(d, dict) else {}


def _save_names(d):
    # ⚠️ 把写盘成没成**返回出去**（memory-keeper 要靠它判断"这次到底写进去没有"）——
    #    老调用方都不看这个返回值，所以多返回一个布尔不影响任何行为。
    return store.write_json(MEMORY, d)


def remember_name(qq, name):
    """给他定个称呼。返回 (ok, 说明) —— 说明是给模型看的事实，不是台词。"""
    qq = str(qq or "").strip()
    if not qq:
        return False, "不知道他是谁（没拿到 QQ 号）"
    why = throne_why(name)
    if why:
        base.log("拒绝一个称呼：%r（%s）" % (name, why))
        return False, "不能这么叫（%s 这种把自己放在她头上的称呼不记）" % why
    n = clean_name(name)
    with _LOCK:
        d = _load_names()
        rec = d.get(qq) or {}
        rec["name"] = n
        rec["at"] = time.time()
        d[qq] = rec
        _save_names(d)
    base.log("记下称呼：%s -> %s" % (qq, n))
    return True, "已记下：以后叫他「%s」" % n


def forget_name(qq):
    qq = str(qq or "").strip()
    with _LOCK:
        d = _load_names()
        rec = d.get(qq)
        if rec and rec.get("name"):
            old = rec.pop("name")
            d[qq] = rec
            _save_names(d)
            base.log("取消称呼：%s（原来叫 %s）" % (qq, old))
            return True, "已取消「%s」这个叫法，回到他的群名片/昵称" % old
    return False, "他本来就没有专门定过称呼"


def name_of(qq):
    """他让她怎么叫 —— 没定过就返回空串（调用方再退回群名片/昵称/QQ 号）。"""
    rec = _load_names().get(str(qq or ""))
    return (rec or {}).get("name") or ""


def _clean_field(raw):
    """借通信层的清洗（去掉群名片里那些不可见的排版控制符 U+2066–U+206F）。

    ⚠️ 借用而不是抄一遍：那份坑是 napcat.py 踩出来的，逻辑只该有一处。
    """
    if not (raw or "").strip():
        return ""
    got = napcat.who_of({"sender": {"card": raw}})
    return "" if got == "?" else got


def call_name(ctx):
    """她该怎么**称呼**这个人（工具结果、提醒、日志里用的那种"一个名字"）。

        他定的称呼 > 群名片(群聊) / 昵称(私聊) > QQ 号

    ⚠️ 这只是"一个名字"。**消息前缀上显示什么**是另一套规矩（见 display_name）：
       前缀要把"他是谁 + 名片/昵称"一起带上，这个函数不干那件事。

    为什么群聊不给昵称：群里同一件事有两套名字（名片和昵称），昵称又常常是
    「已深度思考20秒」这种不像人名的东西 —— 混进来她会认错人、也叫错人。
    昵称只在私聊用（私聊根本没有群名片）。

    ⚠️ `napcat.who_of()` 是「名片优先、其次昵称」，它是**给通信层自己用的**
       （不看聊天类型）；这里按聊天类型再收紧一次，是 agent 层的事。
    """
    ctx = ctx or {}
    uid = str(ctx.get("user_id") or "")
    got = name_of(uid)
    if got:
        return got
    sender = (ctx.get("evt") or {}).get("sender") or {}
    raw = sender.get("card") if ctx.get("is_group") else sender.get("nickname")
    return _clean_field(raw) or uid or "?"


# QQ 会把"没设置群名片"给成这个**字面值**（不是空串），当成名字用会很难看：
# 她看到的前缀会变成「未设置（QQ 30003）」，群里那位明明有昵称。实测踩到过。
PLACEHOLDER = ("未设置", "未设置昵称", "未设置群名片", "无", "none", "null", "-", "--", "……")


def _clean_side(x):
    x = (x or "").strip()
    return "" if x.lower() in PLACEHOLDER else x


def display_name(qq, is_group, fallback_name="", card_now=None, group_id=""):
    """**消息前缀**（以及历史行 / 被引用那条）上的名字 —— 的**统一**降级

        群聊：① 称呼 → ② **本群**名片 → ③ 昵称 → ④ QQ 号
        私聊：① 称呼 → ③ 昵称 → ④ QQ 号

    ⛔ **格式就是 `名字: ` 那一截** —— 以前那截
       `称呼[群名片:X]` / `称呼[qq昵称:X]` **整条去掉了**（前缀/材料两侧都不再有方括号）。
       名片/昵称从"方括号里的补充"降级成 fallback 的一档。
       ⚠️ 方括号那套的来历：用户定的 —— 以前写成 `称呼（群名片 X）`
          她常把括号里的群名片当成那个人的名字 ✗。现在那截整个没了。

    `qq` 是那个人的 QQ 号；空/无 → 空串。
    `fallback_name` 是**历史条目里存的那个称呼快照**：活记忆里查不到时用它兜底
    （比如那个人后来被清空了记忆，老对话行也不该退化成光秃秃的 QQ 号）。
    ⚠️ 它**只占"称呼"这一格**，而且**等于那串 QQ 号就当没有**（`record()` 当时的兜底
       写的正是 QQ 号）—— 否则新加的名片/昵称那两级会被一个 QQ 号影子挡死。

    ⚠️ 群名片**按群各有一张**（`cards[群号]`）：这里的顺序是
       `card_now`（调用方手里那张**当下的**，例如当前消息的 `sender.card`）
       → 记忆里**这个群**那张（`card_in(qq, group_id)`）。
       私聊（`is_group=False`）→ **整档不可用**（私聊根本没有"本群"这回事）。
       ⛔ 记忆里那份**老单字段 `card`** 一个字节都不读（历史残留）。
    """
    qq = str(qq or "")
    rec = record_of(qq)
    head = (rec.get("name") or "").strip()
    if not head:
        # ⚠️ `fallback_name` 是**历史条目里那个称呼快照**（`record()` 存的是"当时的称呼"）。
        #    它**只占"称呼"这一格**：等于那串 QQ 号就说明当时根本没有称呼
        #    （`record()` 的兜底写的就是 QQ 号）—— 那种要**接着往下走**
        #    （名片 → 昵称 → QQ 号），不然新加的那两级会被一个 QQ 号影子挡死。
        fb = (fallback_name or "").strip()
        head = "" if fb == qq else fb
    card = ""
    if is_group:
        card = _clean_side(card_now) or (card_in(qq, group_id) if qq else "")
    nick = _clean_side(rec.get("nick"))
    for v in (head, card, nick, qq):
        if v:
            return v
    return ""


def add_fact(qq, text):
    """往**这个 QQ 名下**加一条记忆。返回 (ok, 说明)。

    他说的就记在他名下 —— 这条约定比工具描述重要，所以写死在代码里。
    """
    text = (text or "").strip()[:200]
    if not text:
        return False, "没说要记什么"
    qq = str(qq or "").strip()
    if not qq:
        return False, "不知道他是谁（没拿到 QQ 号），记不到谁名下"
    with _LOCK:
        d = _load_names()
        rec = d.get(qq) or {}
        facts = rec.get("facts") or []
        if text not in facts:
            facts.append(text)
        rec["facts"] = facts[-settings.get("memory.maxFacts"):]
        rec["at"] = time.time()
        d[qq] = rec
        _save_names(d)
    base.log("记下关于 %s 的一条：%s" % (qq, text))
    return True, "记在他名下了（以后你要用的时候能查出来）"


def backup_versions():
    """写前备份：把现在的 memory.json 存一份，**只留最近 5 版**（`memory-backup-*`）。

    ⚠️ 谁在用：memory-keeper 动记忆之前（用户定的「写前备份留 5 版」）。
    ⚠️ 文件名带时间戳；同一秒里连着备份两次就覆盖同一份（够用）。
    """
    import os
    import shutil
    src = store.path(MEMORY)
    if not os.path.isfile(src):
        return False
    try:
        name = "%s%s.json" % (BACKUP_PREFIX, time.strftime("%Y%m%d-%H%M%S"))
        shutil.copyfile(src, store.path(name))
        old = sorted([n for n in os.listdir(store.dir_path())
                      if n.startswith(BACKUP_PREFIX) and n.endswith(".json")])
        keep = settings.get("memory.backupKeep")
        for n in old[:-keep]:
            try:
                os.remove(store.path(n))
            except Exception:
                pass
        return True
    except Exception as e:
        base.log("备份 memory.json 没成（不影响这次动作）：%r" % (e,))
        return False


def set_facts(qq, facts):
    """把这个人名下的记忆**整份换掉**（memory-keeper 用）。

    ⚠️ 形状不变：`facts` 还是一串**短句字符串**（面板/App 在读它）。
    ⚠️ 只动这一个 QQ 那一块；称呼 / 昵称 / 群名片一栏都不碰。
    """
    qq = str(qq or "").strip()
    if not qq:
        return False
    clean = []
    for f in (facts or []):
        s = (f or "").strip()[:200]
        if s and s not in clean:
            clean.append(s)
    with _LOCK:
        d = _load_names()
        rec = d.get(qq) or {}
        rec["facts"] = clean[-settings.get("memory.maxFacts"):]
        rec["at"] = time.time()
        d[qq] = rec
        return _save_names(d)


def fix_fact(qq, old, new=""):
    """**改/删**这个人记忆里的一条。返回 (ok, 说明, [碰到的那几条])。

    `new` 留空 = 删掉。他说「那条记错了」「我不喝咖啡了」时用。
    ⚠️ 只在**这个人的那块**里找，永远动不到别人的记忆。
    """
    qq = str(qq or "").strip()
    old = (old or "").strip()
    new = (new or "").strip()[:200]
    if not qq:
        return False, "不知道他是谁（没拿到 QQ 号）", []
    if len(old) < 2:
        return False, "得说清是哪一条（关键词至少两个字，不然容易伤到别的）", []
    with _LOCK:
        d = _load_names()
        rec = d.get(qq) or {}
        facts = list(rec.get("facts") or [])
        # ⚠️ 先试**整条一字不差**：面板/App 上是点着某一行改的，给的往往就是那一条的原文
        #    —— 这时候只许动它一个（不然「住在苏州」会连「现在住在苏州」一起改掉）。
        #    对不上再退回按关键词找（她在 QQ 里说「那条记错了」时给的是短关键词）。
        hit = [f for f in facts if f == old] or [f for f in facts if old in f]
        if not hit:
            return False, "他名下没有这一条", facts
        rest = [f for f in facts if f not in hit]
        if new:
            rest.append(new)
        rec["facts"] = rest[-settings.get("memory.maxFacts"):]
        rec["at"] = time.time()
        d[qq] = rec
        _save_names(d)
    base.log("改/删 %s 的记忆：%s -> %s（碰到 %s）"
             % (qq, old, new or "（删掉）", hit))
    return True, ("改成了「%s」" % new) if new else "删掉了", hit


def facts_of(qq):
    """⚠️ 只返回**这一个人**的记忆 —— 调用方永远不该拿到别人的。"""
    rec = _load_names().get(str(qq or ""))
    return list((rec or {}).get("facts") or [])


def record_of(qq):
    """这个人的那一块（没记过就是空的）。**只有他自己那块**，不含别人。"""
    return dict(_load_names().get(str(qq or "")) or {})


def find_all(who):
    """按 QQ 号 / 称呼 / **记忆内容**找人 —— **所有**命中的 `[(qq, 记录), …]`。

    为什么要有"全部命中"这一版：认人的口径是**每档必须唯一命中才定案**，
    同一档 ≥2 个不同 QQ = 重名 → **一律不猜**（见 `who.identify()`）。
    `find()` 那种"给第一个"的老接口喂不了这个判据，所以真正的实现在这里。
    """
    w = str(who or "").strip()
    if not w:
        return []
    out = []
    for qq, rec in (_load_names() or {}).items():
        if not isinstance(rec, dict):
            continue
        name = rec.get("name") or ""
        # ⚠️ 这里是 "facts" 不是 v1 的 "notes"（改字段名时漏了这个地方，
        #    结果「按记忆内容找人」一直静默失效：说出他记过的那件事也找不到人）。
        if (str(qq) == w or name == w or w in name
                or any(w in n for n in (rec.get("facts") or []))):
            out.append((str(qq), rec))
    return out


def find(who):
    """按 QQ 号或称呼找人（她问「张三是谁」时用）。返回 (qq, 记录) 或 (None, None)。

    ⚠️ 重名时这里**只给第一个**（老接口：探针/给人看的那种）；**认人那条路**走
       `who.identify()` —— 那边同一档 ≥2 个不同 QQ 是"重名 → 不猜"。
    """
    hit = find_all(who)
    return hit[0] if hit else (None, None)


def people():
    return len(_load_names())


def card_in(qq, group_id=""):
    """他**在这个群**里那张名片（`cards[群号]`）；私聊 / 没群号 → 空串。

    ⚠️ 群名片**按群各存一张**，所以要问"哪张"必须先说"哪个群"。
    ⛔ 老的单字段 `card` 在这里**一个字节都不读**（它只是历史残留，见模块开头）。
    """
    gid = str(group_id or "").strip()
    if not gid:
        return ""
    cards = (record_of(qq) or {}).get("cards")
    if not isinstance(cards, dict):
        return ""
    return _clean_side(cards.get(gid))


def touch(qq, nick="", card="", group_id=""):
    """记下他最近一次的 QQ 昵称 / **这个群里**的群名片。

    ⚠️ **群名片按群存**：`rec["cards"][群号] = 名片`。
       · `group_id` 空（私聊）→ **名片一个字都不写**（私聊里没有"本群名片"这回事）；
       · 有群号 + 那张名片变了 → 只动**那个群那一格**；
       · 占位符（QQ 给的「未设置」那种）当"没名片" → 不落盘。
    ⛔ 老的单字段 `card` **从这天起既不读也不写**（历史残留留在那儿不动，别拿它当
       "当前群名片"、也别拿它当别名 —— 见 who.py）。

    ⚠️ 只在**变了**的时候写盘 —— 这个方法每条消息都会调用，而 memory.json 是
       一人一块的活数据文件，不能每条消息都重写一遍（手机上是闪存，没必要）。
    """
    qq = str(qq or "").strip()
    nick = (nick or "").strip()[:24]
    gid = str(group_id or "").strip()
    card = _clean_side((card or "").strip()[:24]) if gid else ""
    if not qq or not (nick or card):
        return False
    with _LOCK:
        d = _load_names()
        rec = d.get(qq)
        if not isinstance(rec, dict):
            rec = {}
        # ⚠️ 只更新**这次事件真的带来了值**的那个字段。
        #    旧写法一个事件同时覆盖两个字段 —— 私聊事件没有群名片，
        #    于是把存着的群名片抹成空：他私聊说一句，他在群里的前缀就从
        #    `主人[群名片:某人的昵称]` 退化成光秃秃的 `主人`。
        changed = False
        if nick and nick != (rec.get("nick") or ""):
            rec["nick"] = nick
            changed = True
        if card:
            cards = rec.get("cards")
            if not isinstance(cards, dict):
                cards = {}
            if card != _clean_side(cards.get(gid)):
                cards[gid] = card
                rec["cards"] = cards
                changed = True
        if not changed:
            return False
        rec["seen"] = time.time()
        d[qq] = rec
        _save_names(d)
    return True


def ensure_person(qq, name=""):
    """给这个 QQ 建一块空的（面板上「加一个人」用）。已经有了就只补称呼。"""
    qq = str(qq or "").strip()
    if not qq.isdigit():
        return False, "QQ 号得是数字（给的是「%s」）" % qq
    with _LOCK:
        d = _load_names()
        rec = d.get(qq) if isinstance(d.get(qq), dict) else {}
        fresh = not rec
        rec.setdefault("facts", [])
        rec["at"] = time.time()
        d[qq] = rec
        _save_names(d)
    if name:
        return remember_name(qq, name)
    return True, ("给他建了一块空的" if fresh else "他本来就有一块") + "（接着往里加记忆就行）"


def forget_person(qq):
    """整块删掉（连称呼一起）。"""
    qq = str(qq or "").strip()
    with _LOCK:
        d = _load_names()
        rec = d.pop(qq, None)
        if rec is None:
            return False, "记忆里本来就没有这个 QQ"
        _save_names(d)
    # 旁挂的语义向量也跟着删（不删也不影响正确性 —— 指纹对不上就会重算 ——
    # 但留着白占地方，而且下次 self-heal 会把它当成"已存在的旧数据"）
    try:
        from . import vecstore
        vecstore.drop(qq)
    except Exception as e:
        base.log("清向量时出错了（不影响删人）：%r" % (e,))
    return True, "整块删掉了（称呼「%s」和 %d 条记忆一起没了）" % (
        (rec or {}).get("name") or "（没定）", len((rec or {}).get("facts") or []))


def known_names():
    """她认识的名字（所有"称呼"）。给 guards.strip_echo 判断"行首是不是谁说的"用。"""
    return [p.get("name") for p in all_people() if p.get("name")]


def known_nicks():
    """她记忆里见过的所有 **QQ 昵称**（`rec["nick"]`）—— `strip_echo` 用。

    ⚠️ 消息前缀里那截方括号**去掉了**，名片/昵称
       直接就是行首那个名字 —— 所以"可能被她误抄的名字"要多这两份（见
       `guards.speaker_names()`），不然她把自己话头那个名字一起抄出来就削不掉了。
    """
    return [p.get("nick") for p in all_people() if p.get("nick")]


def known_cards(group_id=""):
    """**群名片**（`rec["cards"]` 里那些）—— `strip_echo` 用（同上）。

    `group_id` 留空 = **所有群**的名片都算（前缀是从任意群里抄出来的）；
    给了就只要那个群的那张。
    """
    out = []
    for p in all_people():
        cards = p.get("cards") or {}
        if not isinstance(cards, dict):
            continue
        vals = [cards.get(str(group_id))] if str(group_id or "") else list(cards.values())
        for v in vals:
            s = _clean_side(v)
            if s and s not in out:
                out.append(s)
    return out


def all_records():
    """整份记忆库的**原始形状**（`{qq: 那块}`）—— 认人（`who`）与自检用。

    ⚠️ 里面是**所有人**的底细，只许内部/控制面拿：她永远只该看到 `memory` 那个工具取的那一块。
    """
    return _load_names()


def cards_display(rec):
    """把**按群那张表**拼成面板/App 要的那一行（⛔ 老的单字段 `card` 一个字节都不读）。

    一个人可能在好几个群里各有一张名片 —— 所以要带上是哪个群：
        `阿猫（群 20002）`；一张都没有 → 空串（面板/App 那行整个不显示）。
    """
    cards = (rec or {}).get("cards")
    if not isinstance(cards, dict):
        return ""
    out = []
    for g in sorted(cards, key=lambda x: str(x)):
        c = _clean_side(cards.get(g))
        if c:
            out.append("%s（群 %s）" % (c, g))
    return "、".join(out)


def all_people():
    """整份记忆库（**控制面**用：网页面板 / 手机 App 上编辑）。

    ⚠️ 只给控制面（要 token、本机或局域网）—— 给她看的永远只有 `memory` 那个工具取的那
       一块（"她不该一眼看到所有人的底细"这条没变）。
    ⚠️ 那份 `card` **不再读老的单字段**（历史残留）—— 它由**按群那张表**
       （`cards`）拼出来，一个群一张就带群号，见 `cards_display()`。
    """
    out = []
    for qq, rec in (_load_names() or {}).items():
        if not isinstance(rec, dict):
            continue
        out.append({"qq": str(qq), "name": rec.get("name") or "",
                    "nick": rec.get("nick") or "",
                    "card": cards_display(rec),
                    "cards": dict(rec.get("cards") or {}) if isinstance(rec.get("cards"), dict) else {},
                    "facts": list(rec.get("facts") or []), "at": rec.get("at") or 0,
                    "seen": rec.get("seen") or 0})
    # 定了称呼的排前面，其余按 QQ 排 —— 面板上的气泡顺序就照这个来
    out.sort(key=lambda p: (0 if p["name"] else 1, p["qq"]))
    return out
