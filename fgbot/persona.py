#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""她是谁：读用户手改的 `personality.md` + 拼那一小段运行层提示词。

分两半，别搅在一起：

  · **性格**（personality.md）＝ 用户的地盘。他随时手改，代码不写死一个字。
    字段少、纯文本、每个字段都有注释说明它是干嘛的。
  · **运行层提示词**（本文件里的 `TEMPLATE`）＝ 代码的地盘：身份 + 场合 + 输出约定。
    越短越好（验收要求 ≤ 400 字）。性格文件那部分不算字数。

⚠️ 别往运行层提示词里堆「别…别…」的规矩。v1 就是这么死的：
   规矩越多，她的注意力越在「别犯规」上，回答越笨。
   能用**结构**解决的（谁在说话写成前缀、旁路信息走 system）就别写提示词；
   能用**代码**兜底的（削内心独白、查谎话）就别指望她自觉。
"""

import os
import re
import threading

from . import base

DEFAULT_FILE = "personality.md"

# ── 运行层提示词（**这段要 ≤ 400 字**，自检里会打印字数）───────────────
#
# 只写三件事：性格（从文件来）、对话长什么样、怎么说话。
# 「场合」（几点、在哪个群、跟谁说话）**不在这里** —— 那是每一轮现给的事实。
#
# ⚠️ 删掉了开头那句"你是…下面这段是用户写给你的性格，照它来："
#    —— 那种"介绍这是什么"的话是写给人看的，她不需要（她要的是内容本身）；
#    文件自己的标题行（`# 机魂小悦的性格（这个文件是给你改的）`）同理，
#    而且那行里的括注是给**改文件的人**看的备注，不该占她的注意力。
# ⚠️ （定稿）：这两行里的「【称呼】」统一改叫
#    「【消息前缀】」—— 它指的就是**每行开头那个名字**（称呼 / 本群名片 / 昵称 / QQ 号
#    四级降级），跟 `memory` / `history` 那些工具说明里的【消息前缀】是同一个概念。
#    ⛔ 这两行是定稿过的，别自己再动一个字。
# ⚠️ （定稿）：**删掉**了最后那句全局的
#    「不想说话就只回某个哨兵词」。从这一批起，沉默 = `end_turn` 工具（条件出现：
#    触发词 / 随机接话 / 唤醒到点 / 先说 `say` 之后）+ 模型直接给空文本。
#    那两句场合说明见 `agent._occasion`（第 40/41 条），@她/叫名字/唤醒/播报都不加。
#    `你对他的【称呼】` 那对方括号也是加的。
#    ⛔ 整段是定稿给的，一个字都不许改（自检里钉着）。
TEMPLATE = """你的名字是{name}。你是由**{owner}**部署的qq机器人助手。{persona}

对话里每行的格式是【消息前缀】: 他说的话。
【消息前缀】是那个人的名字，可能是你对他的【称呼】、他在这个群的群名片、他的 QQ 昵称，或者他的 QQ 号。
要办事、要准确数字、要知道新东西，就调用工具，然后照工具给的事实说。
请你自己判断要不要调用工具，简单的直接答；复杂的，用户要求时，就用 search 查。
按用户发言的语言回复"""

MAX_CHARS = 400

# 认得的字段。**只给自检显示**，正文原样带给她 —— 用户写了个
# 不认得的字段不该被吃掉。
FIELDS = ("名字", "别名", "她是谁", "说话风格", "在意的事", "口头习惯")

FIELD_ALIAS = {"别名": "别名", "别称": "别名", "大名": "别名", "真正的大名": "别名",
               "小名": "别名", "外号": "别名", "昵称": "别名"}

_LOCK = threading.RLock()
_CACHE = {}                      # path -> (mtime, parsed)


def _persona_name():
    name = ((base.cfg().get("agent") or {}).get("personaFile") or DEFAULT_FILE).strip()
    return name or DEFAULT_FILE


def profile_path():
    """性格文件**读**哪份。config 里能改（`agent.personaFile`），默认 `personality.md`。

    ⚠️ 用 `base.existing_or_data()`：**先数据目录、再代码目录**。没"部署"过、
       直接在仓库里跑的时候，`personality.md` 还在代码目录里（和 config.json 一样）。
       别写成 `os.path.join(base.DIR, …)` —— 数据目录可配之后那会读错地方。
    """
    name = _persona_name()
    return name if os.path.isabs(name) else base.existing_or_data(name)


def write_path():
    """性格文件**写**哪份：**永远写数据目录**（`MMZBOT_DATA` / 平台默认）。

    ⚠️ 和 `profile_path()` 分开：读可以退回代码目录（开发机上那份），写必须落在
       数据目录 —— 「所有会变的东西都从数据目录派生」（requirements §3）。
    """
    name = _persona_name()
    return name if os.path.isabs(name) else base.data_path(name)


def _strip_comments(text):
    """去掉 <!-- … --> 注释块（那是写给**人**看的说明，不该进她的上下文）。"""
    return re.sub(r"<!--.*?-->", "", text or "", flags=re.S).strip()


def _clean_body(text):
    """正文清洗：去注释 → 去 markdown 标题行 → 压掉多余空行。

    ⚠️ 标题行（`# 机魂小悦的性格（这个文件是给你改的）`）是写给人看的门牌，
       括号里那句更是"改文件的人"的备注 —— 不要让她读到。
    """
    body = _strip_comments(text)
    body = re.sub(r"^#{1,6}\s.*$", "", body, flags=re.M)       # 标题行整行丢掉
    body = re.sub(r"\n{2,}", "\n", body)                        # 注释留下的空行压掉
    return body.strip()


def _parse(text):
    """把文件拆成 {字段: 值}。正文（含认不出的行）会原样回去。

    两种写法都认。
    """
    body = _clean_body(text)
    vals, extra = {}, []
    for raw in body.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^([^：:]{1,6})[：:]\s*(.*)$", line)
        if m:
            k = FIELD_ALIAS.get(m.group(1).strip(), m.group(1).strip())
            if k in FIELDS:
                v = m.group(2).strip()
                if v:
                    vals[k] = (vals.get(k, "") + " " + v).strip() if k in vals else v
                continue
        extra.append(line)
    # 散文写法：从整段里捞名字/别名
    if not vals.get("名字"):
        hit = re.search(r"名字是\s*([^\s，,。；;、]{1,12})", body)
        if hit:
            vals["名字"] = hit.group(1)
    if not vals.get("别名"):
        got = []
        for pat in (r"大名是\s*([^\s，,。；;、]{1,12})", r"别名(?:是|：|:)\s*([^\s，,。；;、]{1,12})"):
            for one in re.findall(pat, body):
                if one and one not in got:
                    got.append(one)
        if got:
            vals["别名"] = "、".join(got)
    vals["_正文"] = body
    vals["_其它"] = extra
    return vals


def profile():
    """读性格文件（按 mtime 缓存）。文件没了也有兜底，她不会因此哑巴。"""
    p = profile_path()
    with _LOCK:
        try:
            m = os.path.getmtime(p)
        except Exception:
            m = None
        hit = _CACHE.get(p)
        if hit and m is not None and hit[0] == m:
            return hit[1]
        text = ""
        if m is not None:
            try:
                with open(p, encoding="utf-8") as f:
                    text = f.read()
            except Exception as e:
                base.log("性格文件 %s 读不出来：%r" % (p, e))
        else:
            base.log("⚠️ 找不到性格文件 %s —— 她按默认性格说话（去建一个吧）" % p)
        out = _parse(text)
        out["_path"] = p
        out["_missing"] = (m is None)
        _CACHE[p] = (m, out)
        return out


DEFAULT_NAME = "机魂小悦"


def name():
    """她叫什么：**只从配置来**（`agent.name`）。

    ⚠ 用户定的：名字以配置为准，不再从性格文件里捞（那份是散文）；
      也没有"小名/大名"两层 —— 就一个名字。另外的称呼放 `agent.wakeWords`。
    """
    a = base.cfg().get("agent") or {}
    n = str(a.get("name") or "").strip()
    if not n:                                   # 老配置兼容
        n = str(a.get("nickname") or "").strip()
    return n or DEFAULT_NAME


def owner_title():
    """「主人」这个位置该填什么：**她给人定的称呼 → QQ 昵称 → 「主人」**。

    ⚠️ 用户定的（选 B：代码注入，不靠手写性格文件）。
    来源：
      ① `memory` 里给主人定的**称呼**（他自己说「以后叫我 X」就有了）
      ② memory 记过的 **QQ 昵称**
      ③ 都没有 → 字面「主人」
    """
    qq = base.owner_qq()
    if not qq:
        return "主人"
    try:
        from . import memory
        n = (memory.name_of(qq) or "").strip()
        if n:
            return n
        for p in memory.all_people():
            if str(p.get("qq") or "") == qq and (p.get("nick") or "").strip():
                return str(p.get("nick")).strip()
    except Exception:
        pass
    return "主人"


def wake_words():
    """唤醒词：配置 `agent.wakeWords`（列表，可为空）。

    ⚠ 老配置的 `agent.fullName` 也当一个唤醒词认（升级后不丢能力）。
    """
    a = base.cfg().get("agent") or {}
    raw = a.get("wakeWords")
    out = []
    if isinstance(raw, (list, tuple)):
        items = raw
    else:
        items = re.split(r"[、,，/|\s]+", str(raw or ""))
    for w in items:
        w = str(w or "").strip()
        if w and w not in out:
            out.append(w)
    legacy = str(a.get("fullName") or "").strip()
    if legacy and legacy not in out:
        out.append(legacy)
    return out


def forget():
    """清掉按 mtime 的解析缓存（面板刚写完文件时用）。

    ⚠️ 为什么要单独一个入口：`profile()` 只比 mtime，而有些文件系统的 mtime
       精度只到秒 —— 同一秒里"读一次、写一次"，缓存就还当它是旧的。
    """
    with _LOCK:
        _CACHE.clear()


def call_names():
    """哪些词出现在**消息开头**就算在叫她：名字 + 唤醒词。

    ⚠ 用户定的：名字和唤醒词**都只从配置来**（`agent.name` / `agent.wakeWords`）
      不再读性格文件里的「名字 / 大名 / 别名」—— 那份只是散文。
    """
    out = []
    for w in [name()] + wake_words():
        w = (w or "").strip()
        if w and w not in out:
            out.append(w)
    return out


def trigger_words():
    """触发词：消息里**任何位置**出现它，就把这条交给模型（等于在叫她）。

    ⚠️ 跟「别名」的分工
       · 别名  = 她的另一个**名字**，只在**消息开头**出现才算在叫她；
       · 触发词 = **话题词**（"摸鱼""好累"这种），出现在**哪儿都算**。
    触发词只负责"把话递给她"，回什么完全由模型自己组织 —— 没有任何现成回复
    （用户原话：「触发词只是触发，也就是有这个词就送给llm让他正常说话」）。

    ⚠️ **不放在性格文件里**（的：性格文件是"她是谁"，触发词是程序规则；
       而且性格正文会整段进提示词，写在那儿等于把配置塞进她的脑子 ✗）。
    存两处：config.json 的 `agent.triggerWords`（部署默认值）+ runtime.json 的同名键
    （面板/App 改的，deploy 不覆盖），后者优先 —— 跟"思考强度"一个道理。
    """
    out = []
    for w in ((base.cfg().get("agent") or {}).get("triggerWords") or []):
        w = str(w).strip()
        if w and w not in out:
            out.append(w)
    try:
        from . import llm
        rt = llm.runtime_get("triggerWords")
        if isinstance(rt, list):
            out = []
            for w in rt:
                w = str(w).strip()
                if w and w not in out:
                    out.append(w)
    except Exception:
        pass                      # runtime 读不到就用 config 里的默认值，别把搭话整个搞挂
    return out


def personality_text():
    """性格文件正文（去掉给用户看的注释），原样带给她。"""
    return profile().get("_正文") or ""


def system_prompt():
    """给模型的第一条 system：身份 + 性格 + 说话约定。

    ⚠️ 这里**只有性格**。关于某个人的信息（他住哪、是谁、喜欢什么）一个字都不放 ——
       那是「长期记忆库」，她要用的自己调 `memory` 那个工具去取（见 memory.py）。
       常驻的附加消息越多，她越容易被背景信息占着注意力。
    """
    p = personality_text()
    if not p:
        p = "（性格文件是空的，你自己拿捏：像个正常人一样说话。）"
    return (TEMPLATE.replace("{name}", name())
            .replace("{owner}", owner_title())
            .replace("{persona}", p))


def prompt_chars():
    """运行层提示词的字数（**不含性格文件**，验收看的是这个数）。"""
    return len(TEMPLATE.replace("{name}", name())
                   .replace("{owner}", owner_title())
                   .replace("{persona}", ""))


def fields_help():
    """给自检/人看的字段说明。"""
    return [
        ("名字", "她叫什么。群里消息开头出现这个词就算在叫她（她自己介绍也用这个）。"),
        ("别名", "额外的叫法，顿号/逗号分开；叫这些也算在叫她。写「大名」「小名」「别称」「外号」也一样认。"),
        ("她是谁", "一句话说清她是个什么人。"),
        ("说话风格", "她怎么说话：长短、语气、带不带口头禅。"),
        ("在意的事", "她在乎什么、按什么做判断。"),
        ("口头习惯", "常带的小尾巴、常用词。"),
    ]
