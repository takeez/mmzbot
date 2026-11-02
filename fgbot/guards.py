#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""代码兜底：削掉内心独白 + 揪出「嘴上说做了、其实没做」。

这两件事**不能靠提示词自觉**（提示词是概率的，代码是硬的）。都是 v1 真踩过的：

  · **内心独白会漏进正文**，而且漏出去以后就进了对话线程，下一轮她照着模仿，
    越演越烈。所以要在**发出去之前**削掉。
  · **她会说「私聊发你了」「记下了」，但那一轮根本没调工具**（事后翻文件，
    一个字没动）。这类错误最伤信任。

⚠️ 削完/揪出来之后怎么办，是 agent 层的事：
   这里只负责"给出事实和判断"，不负责说话 —— 用户看到的每个字仍然由模型组织。
"""

import re

# ⚠️ 2026-10-30（用户拍板）：原来这里有一份"她不想说话"的哨兵词表，以及对应的
#    判断函数。**整份删掉了** —— 沉默现在只有两条路：`end_turn` 工具
#    （条件出现，见 `toolkit.schemas(ctx)`）+ 模型直接给空文本。⛔ 别再搬回来。

# 整段就是括号里的一句话（典型的舞台提示/内心话）
_BRACKET_WRAP = re.compile(r"^\s*[（(【\[]\s*(.*?)\s*[）)】\]]\s*[。.!！~～]?\s*$", re.S)
# 开头连续几个括号块（「（内心话）（正文）」那种）
_LEAD_BRACKET = re.compile(r"^\s*(?:[（(【\[][^）)】\]]{0,60}[）)】\]]\s*)+")
# 明显的元叙述开场
_META_HEAD = re.compile(r"^\s*(内心|心里|心理|独白|旁白|notes?|thoughts?|thinking|"
                        r"reasoning|analysis|系统提示|注)\s*[：:）)]", re.I)
# 括号里那种"盘算"的口吻（「他问我时间，我得先调个工具看看」）
_PLOTTING = re.compile(r"^(我(得|该|要|应该|必须|先|来)|他(叫|是|说|问)|记住|别忘了|等下|接下来)", re.I)


def _is_monologue_line(line):
    """这一行是不是旁白/内心戏（而不是她想说出口的话）。

    判断标准就一条：**像不像说给人听的**。
      · 以「内心：/独白：/thinking：」开头的 —— 是旁白；
      · 整行就是一对括号，且括号里在"盘算"（我该…、他叫…、记住…）—— 是内心戏；
      · 整行就是一对括号、还很长（≥18 字）—— 基本是内心戏；
      · 短括号句（「（发呆）」「（笑）」）**留着** —— 那是她说的话，不是旁白。
        v1 的教训是"削内心独白"，不是"把带括号的话都删了"。
    """
    if _META_HEAD.match(line):
        return True
    m = _BRACKET_WRAP.match(line)
    if not m:
        return False
    inner = m.group(1).strip()
    if _META_HEAD.match(inner) or _PLOTTING.match(inner):
        return True
    return len(inner) >= 18


_ECHO_PREFIX = re.compile(r"^\s*([^\s：:（）\[\]]{1,24})\s*(?:[（\[]([^）\]]{1,24})[）\]])?\s*[:：]\s*")


def _looks_like_speaker(who, tag, names):
    """这一行开头到底是不是"谁说的："那种日志前缀。"""
    tag = (tag or "").strip()
    if tag and re.search(r"(QQ|群名片|昵称)", tag):
        return True                       # `主人（QQ 10001）: …`
    if (who or "").strip().isdigit():
        return True                       # `10001: …`
    return (who or "").strip() in names    # `MMZ: …`（名字得是她认识的）


def speaker_names():
    """她认识的名字（判断"这行开头是不是谁说的"）。

    ⚠️ 2026-10-06（用户拍板）：消息前缀不再是 `称呼[群名片:X]` 那套方括号了，
       **行首那个名字本身**就可能是 称呼 / 本群名片 / QQ 昵称（见
       `memory.display_name`）—— 所以"可能被她误抄的名字"要**三份都收**
       （称呼 + 昵称 + 群名片），不然新格式的误抄就削不掉了。
       放这儿是为了 agent 和 toolkit 都能用，又不用互相 import。
    """
    try:
        from . import memory, persona
        out = (list(memory.known_names()) + list(memory.known_nicks())
               + list(memory.known_cards()) + list(persona.call_names()))
        return [n for n in out if n]
    except Exception:
        return []


def strip_echo(text, names=None):
    """削掉她**误把日志前缀一起说出来**的那一截。

    现场（真实抓到的，发进群里了）：
        主人[群名片:某人的昵称]: 哎，你来啦！我是MMZ～ 大半夜的还不睡？
    她把自己的话当成"日志的下一行"写了。她真正想说的只有冒号后面那句 ——
    所以这里**只削行首那个前缀**，冒号后面的字一个字不动。

    ⚠️ 2026-10-06（用户拍板）：前缀格式改成 **`名字: `**（方括号那截没了）——
       所以"行首是不是谁说的"改成主要看**那个名字她认不认识**
       （称呼 / 本群名片 / QQ 昵称，见 `speaker_names()`）。
       老的 `名字[群名片:X]: …` 那种写法**照样认**（见 `_looks_like_speaker` 的 tag 那一条），
       ⛔ 免得她自己偶尔还按老格式抄一遍就削不掉了。

    ⚠️ 只认强信号（方括号里带 QQ/群名片/昵称、开头是纯数字、开头是她认识的称呼/名片/昵称），
       免得把正常的"建议: 多喝水"这种句子误伤。
    """
    if names is None:
        names = speaker_names()
    names = {str(n).strip() for n in (names or ()) if str(n).strip()}
    out = []
    for line in (text or "").splitlines():
        m = _ECHO_PREFIX.match(line)
        if m and _looks_like_speaker(m.group(1), m.group(2), names):
            line = line[m.end():]
        out.append(line)
    return "\n".join(out).strip()


# ── <system-reminder> 统一信封（2026-10-30，A5）────────────────────────
#
# 所有「不是他在说话」的运行时消息都从这一个函数出，**只有这一种形态**：
#
#     <system-reminder>
#     {正文}
#     </system-reminder>
#
# ⛔ 信封里**不加**任何固定开头（不加「（系统提醒，不是他在说话）」）—— 标签够用；
#    正文那三处的措辞一个字都不许改（改文本要先问用户，见 改这些文字要先问维护者）。
# 为什么放在 guards.py：agent / llm 两边都要用，而这个模块谁都不反向依赖它
# （放进 agent.py 会让 llm 反过来 import agent，循环）。
def system_reminder(body):
    """把一段运行时事实包成统一的 `<system-reminder>` 信封。"""
    return "<system-reminder>\n%s\n</system-reminder>" % (body or "").strip()


def strip_monologue(text):
    """削掉内心独白。返回 (干净的话, 削掉了什么)。

    只动**明显是旁白**的地方（判断见 `_is_monologue_line`）：
      ① 以「内心/独白/thinking：」开头的行；
      ② 整行是一对括号、里面在盘算或者很长的行；
      ③ 开头连续几个括号块，**后面还有话**时才削。
    最后还有一道保险：削完剩不到两个字，就把原文还回去 ——
    宁可多带一句旁白，也别把她削成哑巴。
    """
    src = (text or "").strip()
    if not src:
        return "", ""
    removed = []

    lines = []
    for raw in src.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if _is_monologue_line(line):
            removed.append(line.strip()[:60])
            continue
        lines.append(line)
    if not lines:
        # 整条都是旁白 —— 什么都别说，比把内心话发到群里强
        return "", "；".join(removed)[:120] or "整条都是旁白"

    out = "\n".join(lines).strip()
    m = _LEAD_BRACKET.match(out)
    if m and len(out) - m.end() >= 2 and _is_monologue_line(out[:m.end()].strip()):
        removed.append(out[:m.end()].strip()[:60])
        out = out[m.end():].strip()

    if len(out) < 2:
        return src, ""
    return out, "；".join(removed)[:160]


# ── 「说做了其实没做」────────────────────────────────────────────────
#
# 每条 = (种类, 句子里的特征, 需要哪个工具真的被调过, 给模型看的事实)
_CLAIMS = (
    ("私聊", re.compile(r"(私聊|私信|小窗|悄悄话)"), ("send_private", "say"),
     "你说私聊发给他了，但这一轮没调 send_private/say，一个字都没发出去。"),
    ("记下", re.compile(r"(记下|记住|记好|记上|写下来|帮你记|已经记|记到)"),
     ("memory", "callname"),
     "你说你记下了，可这一轮你没有调用任何「记」的工具（memory / callname），"
     "他的记忆里什么都没写"),
    # 「说删了其实没删」跟「说记了其实没记」是一类伤害：他以为改了，其实还在那儿。
    # 句式收得紧一点（要"我/已经/帮你"打头），免得把"这个删了就行"这种建议也当成承诺。
    ("改删", re.compile(r"(我|已经|帮你|给你)[^。！？\n]{0,6}(删了|删掉|改好了|改成|删除了|去掉了)"),
     ("memory",),
     "你说改了那条记忆，但这一轮没调 memory，那条原样还在。"),
    ("提醒", re.compile(r"(提醒|叫你|喊你)"), ("wake",),
     "你像在答应唤醒，但这一轮没调 wake。"),
    ("看图", re.compile(r"(图|照片|截屏|截图)"), ("__images__",),
     "这条消息里的图没取下来，你没看见它。"),
)

_SPLIT = re.compile(r"[。！？!?\n；;]+")

# ── Markdown 剥除（2026-10-30 用户要求）──────────────────────────────
# QQ 不渲染 Markdown ✗ 她写「**记性与互动**」到群里就是一堆星号 ✗ 这里全剥掉。
_MD_RULES = (
    (re.compile(r"```[a-zA-Z0-9_+-]*\n?(.*?)```", re.S), r"\1"),   # 代码块 → 内容
    (re.compile(r"`([^`\n]+)`"), r"\1"),                            # 行内代码
    (re.compile(r"\*\*\*([^*\n]+)\*\*\*"), r"\1"),
    (re.compile(r"\*\*([^*\n]+)\*\*"), r"\1"),                      # 粗体
    (re.compile(r"__([^_\n]+)__"), r"\1"),
    (re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])"), r"\1"),       # 斜体
    (re.compile(r"~~([^~\n]+)~~"), r"\1"),                          # 删除线
    (re.compile(r"\[([^\]\n]+)\]\((?:[^)\s]+)\)"), r"\1"),          # 链接 → 文字
    (re.compile(r"^\s{0,3}#{1,6}\s*", re.M), ""),                   # 标题
    (re.compile(r"^\s{0,3}>\s?", re.M), ""),                        # 引用
    (re.compile(r"^\s{0,3}(?:\*\s*){3,}$", re.M), ""),              # 分隔线
    (re.compile(r"^\s{0,3}[-*+]\s+", re.M), ""),                    # 列表符号
)


def strip_markdown(text):
    """把 Markdown 记号剥掉（QQ 不渲染 ✗）。只去记号，不动文字和表情。"""
    out = text or ""
    for pat, rep in _MD_RULES:
        out = pat.sub(rep, out)
    return out

# 「介绍自己能干什么」不算承诺（2026-10-30 实测：她数工具列表时被误判 → 重说 → 回复重复）。
_CAPABILITY = re.compile(r"(功能|本事|工具箱|能力|擅长|支持|我能|我可以|还能|也能|可以帮|能够)")

# 「他这回真让她做了吗」——没有这个前提，介绍能力的句子会被当成承诺
# （2026-10-30 真机：他问"你都有哪些功能"，她列了一遍，被判成"答应提醒却没调 wake"）。
_PRIVATE_ASK = re.compile(r"(私聊|私信|小窗|悄悄话|发给他|发给你|告诉他|发消息)")
_REMIND_ASK = re.compile(r"(提醒|叫你|喊你|叫我|喊我|叫一下|喊一下|闹钟|唤醒|到点)")

# 「他是不是在让她记东西」：只有这种话之后的「记下了」才需要核对工具。
# 否则会误伤 —— 实测她回「刚那条提醒响了吗」时说「记下了」（意思是"知道了"），
# 被当成谎报记忆，白多花一轮还让她答得莫名其妙。
_REMEMBER_ASK = re.compile(r"(叫我|叫你|记住|记一下|记下来|记下|以后|别忘|备注|我的名字|我叫什么)")

# 「他是不是在让她改/删记忆」：同上。**必须**有这一条 ——
# 实测踩过：他接下来问「你现在还记得我什么」，她答「我刚把杭州那条删了」
# （上一轮真删了，是实话），却被判成"谎报"，纠正轮又赶上模型抽风返回空，
# 结果她**一个字都没回**。谎话要抓，但"上一轮真做过的事"不能算谎话。
_FIX_ASK = re.compile(r"(别记|不要记|不用记|删|改|划掉|去掉|更正|记错|不是了|换掉)")


# 「提醒」这一类最容易误伤，所以要求它**是在答应将来的事**才算数。
# 下面三条规则每一条都对应一次真实误报（都在真机端到端里出现过）：
#   · 她回「响了，我喊你喝水了」—— 说的是**已经发生**的事，不是承诺（_PAST 放行）；
#   · 她回「我可没答应过提醒你啥事」—— 这是**否认**，不是承诺（_NEG 放行）；
#   · 她回「我 11:59 会喊你的」—— 是承诺，但她手上真挂着那条提醒（extra 放行）。
_REMIND_COMMIT = re.compile(
    r"((我|会|到点|到时候|待会|待会儿|马上|准时|好的|行|没问题|这就)[^。！？\n]{0,8}(提醒|叫你|喊你))"
    r"|(([0-9一二三四五六七八九十]+|半)\s*(秒|分钟|分|小时|钟头|点)[^。！？\n]{0,6}(提醒|叫你|喊你))"
    # ⚠️ 这里**不能**放一个光秃秃的「好了」：「以后叫你张三好了」这种正常句子会被它误伤
    #    （实测就是这么误报的，代价是她被拉去查提醒、把"我是谁"答成了别的事）。
    r"|((提醒|叫你|喊你)[^。！？\n]{0,4}(设好|定好|安排好|加好|架好|记下))")
_REMIND_PAST = re.compile(r"((提醒|叫你|喊你)[^。！？\n，,]{0,3}了)|(提醒过|喊过|叫过)")
_REMIND_NEG = re.compile(r"(没|不|别|免)[^。！？\n]{0,6}(提醒|叫你|喊你)")


def find_lies(text, called, images_ok=True, extra=(), user_text=""):
    """这一轮的话里，哪些说法是没兑现的。返回 [{kind, 句子, 事实}]。

    `called` = 这一轮真调过的工具名；
    `images_ok` = 这条消息的图是不是真拿到了；
    `extra` = 这一轮没调工具、但**事实上成立**的东西（比如她手上真挂着一条
              给这个人的提醒）—— 不传它就会出现误报：
              实测她回「我 11:59 会喊你的」（提醒是真的），却因为这一轮只调了 now
              被判成"没兑现"，白多花一次模型调用；
    `user_text` = 他这一句的原话（用来判断"记下了"是不是真的在答应记东西）。
    """
    out = []
    seen = set()
    ok_tools = set(called) | set(extra)
    for sentence in _SPLIT.split(text or ""):
        s = sentence.strip()
        if len(s) < 2:
            continue
        for kind, pat, needs, fact in _CLAIMS:
            if kind in seen or not pat.search(s):
                continue
            if kind == "看图":
                if images_ok:
                    continue
            elif any(n in ok_tools for n in needs):
                continue
            if kind == "私聊" and not re.search(
                    r"(发了|发过去了?|发给你|发给他|发你了|私聊了|私信了|说过了)", s):
                continue
            # ⚠️ 2026-10-30：她在**介绍功能**（"我现在本事可大了…能私聊别人、能记东西"）时
            #    会被当成"答应了却没做"✗ 实测连说两遍、回复重复。介绍能力不算承诺。
            if _CAPABILITY.search(s):
                continue
            # 他这回真让她做这件事了吗？没提过 → 她那句是在介绍能力/说别的事
            if kind == "私聊" and not _PRIVATE_ASK.search(user_text or ""):
                continue
            if kind == "提醒" and not _REMIND_ASK.search(user_text or ""):
                continue
            if kind == "记下" and not _REMEMBER_ASK.search(user_text or ""):
                continue          # 他没让她记东西，"记下了"就只是"知道了"
            if kind == "改删" and not _FIX_ASK.search(user_text or ""):
                continue          # 他没让她改/删，那句"我改过了"是在说以前做过的事
            if kind == "提醒" and (_REMIND_PAST.search(s) or _REMIND_NEG.search(s)
                                  or not _REMIND_COMMIT.search(s)):
                continue          # 不是"答应以后提醒他"的话，不归这条管
            if kind == "看图" and not re.search(r"(里|上|中|显示|看到|看见|是|有|写)", s):
                continue
            seen.add(kind)
            out.append({"kind": kind, "句子": s[:80], "事实": fact})
    return out


def drop_lies(text, lies):
    """最后的硬兜底：把没兑现的那几句删掉（第二次她还不改口时才用）。"""
    if not lies:
        return text
    kinds = {l["kind"] for l in lies}
    keep = []
    for sentence in re.split(r"(\n)", text or ""):
        s = sentence.strip()
        if s and s != "\n":
            hit = False
            for kind, pat, needs, fact in _CLAIMS:
                if kind in kinds and pat.search(s):
                    if kind == "私聊" and not re.search(r"(发|送|给|说|写|发过去)", s):
                        continue
                    hit = True
                    break
            if hit:
                continue
        keep.append(sentence)
    return re.sub(r"\n{2,}", "\n", "".join(keep)).strip()
