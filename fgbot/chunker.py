#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**太长就自动分条** —— 全项目唯一的拆分实现（一处实现，多处复用）。

以前的做法是**硬截断**（超出的部分直接丢掉，末尾补一个「…」），真机上真发生过：
18:18:18 那条 1020 字的回复被截到 800，**220 个字没了**。
：「干脆别截断。自动切自动发」—— 这个模块就是那句话的实现。

═══ 三条硬性质（自检逐条验，见 phone-bot-v2.py 的「6e」那一节）═══

  ① **一个字都不许少**：`"".join(split(t, n)) == t`，逐字节相等。
     所以切点只决定「在哪儿切」，绝不做 strip / 补字 / 改写 ——
     段与段之间那点空白留在**前一段的尾巴**上（切点越过句末标点后顺手把
     后面的空格收进上一段），这样拼回去跟原文一模一样。
  ② **只切在体面的地方**：优先句末（`。！？；…` 和换行），其次停顿（`：`）
     再次空白（英文词之间），最后才硬切；硬切也不许把一个英文单词劈两半。
  ③ **`[CQ:...]` 机器码绝不能劈开**：切点落在 CQ 码中间就往回退到它的开头
     （整段码留给下一条）；万一是**本条开头**那个码比切点还长，就把它整个
     留在本条（宁可超一点，也不切坏机器码 —— 切坏了 QQ 那边就是一条报错）。

═══ 关于「第一段带引用回复、后续段不带」═══

那个不由这里管：引用（`reply`）和 @（`at`）在 OneBot 11 里是**消息段**，
不是正文里的字符 —— 调用方（`im.send_long`）只在**第一段**带它们，
后面几段只发纯文本。所以这里只要保证正文本身切得干净就够了。
（引用的 id 是 `ctx["message_id"]`，@ 的 qq 是收件人，两者都不在正文里。）

═══ 上限条数为什么要有个兜底 ═══

正常情况下不限条数（她很少写超过 2000 字，1200/1500 的上限下最多 2 条）。
`max_parts` 纯粹是**防跑飞**的：万一模型抽风输出几万字，按上限拆会变成
几十条连发 —— 那是刷屏，正是当初加上限想避免的事。所以超过兜底就把
**剩下的全部并进最后一条**（那一条于是超上限，允许）——
⛔ 宁可最后一条长一点，也**绝不静默丢内容**（丢的话日志必须写明丢了多少字，
而现在这条路上一个字都不会丢）。
"""

import re

# 一级切点：句末（切在它**后面**）。换行也算 —— 她自己分好的段就是最体面的边界。
HARD_STOPS = "。！？!?；;…\n"
# 二级切点：句中的停顿（实在没有句末标点时才用它，比硬切强）
SOFT_STOPS = "，,、：:）)】」》〉”’"

_CQ = re.compile(r"\[CQ:[^\]]*\]")

#: 每段的「最短容忍」—— 切点至少要落在窗口的这个比例之后。
#  0.5 = 不许切出「一小截 + 一大截」那种难看的比例；窗口后半段找不到切点就
#  再看下一级切点，全都没有才硬切。
MIN_FILL = 0.5


def _is_word(c):
    """英文字母/数字？—— 只认 ASCII。

    ⚠️ **必须限定 ASCII**：`"中".isalnum()` 在 Python 里是 True，中文一个字
       也会被当成"单词字符"，于是"不许劈开单词"那条会把切点一路退回段首，
       直接死循环（这个坑写的时候就想到了，注释留在这儿免得以后有人改成 isalnum）。
    """
    return c.isascii() and (c.isalnum() or c == "_")


def _cut_at(text, start, limit):
    """决定从 `start` 起的这一段切在哪儿（返回绝对下标，保证 > start）。

    窗口 = `text[start:start+limit]`（这就是"不超过上限"的边界）。
    找不到体面的切点就硬切，硬切再躲开"劈开英文单词"和"劈开 CQ 码"。
    """
    n = len(text)
    end = min(n, start + limit)
    window = text[start:end]
    floor = start + max(1, int(len(window) * MIN_FILL))

    cut = 0
    for chars in (HARD_STOPS, SOFT_STOPS):
        # 从后往前找：切点 = 标点的**后一个**位置，这样标点留在上一段末尾。
        for k in range(len(window), 0, -1):
            if window[k - 1] in chars and (start + k) >= floor:
                cut = start + k
                break
        if cut:
            break

    if not cut:
        # 退一步：英文那种"词与词之间"的空格，切在空格**之后**（空格留在上一段）
        for k in range(len(window), 0, -1):
            if window[k - 1] in " \t" and (start + k) >= floor:
                cut = start + k
                break

    if not cut:
        cut = end                      # 实在没有：硬切

    # ── 不许劈开 `[CQ:...]` ──────────────────────────────────────────
    #
    # ⚠️ 这里**不能**给 finditer 传 endpos=cut+1：endpos 会把"跨过切点"的那个
    #    匹配整个丢掉（匹配必须完整落在 [start, endpos) 里），于是正好漏掉要防的那种情形。
    #    改成从 start 顺序扫，碰到第一个起点在切点之后的就收工（量级有界）。
    for m in _CQ.finditer(text, start):
        if m.start() >= cut:
            break
        if cut < m.end():
            if m.start() > start:
                cut = m.start()        # 整段 CQ 码留给下一条
            else:
                cut = m.end()          # 码就在本条开头：整个留在本条（宁可超一点）
            break

    # ── 不许劈开英文单词（只在硬切那一路还需要，标点/空格切点天然在词外）──
    if cut <= start:
        cut = start + 1                # 兜底：无论如何要有进展，绝不死循环
    if cut < n and _is_word(text[cut - 1]) and _is_word(text[cut]):
        back = cut
        while back > start and _is_word(text[back - 1]):
            back -= 1
        if back > start:
            cut = back                 # 退回整个单词的前面（词整个留给下一条）
        else:
            # 这一整段从头到尾都是"一个词"（典型：一条没有空格的超长 URL/base64）。
            # 词**本身**放得下就整个留着；放不下就没别的办法了，照硬切来 ——
            # 那种情况下"不许劈开单词"已经做不到，硬切至少保证每条不超上限。
            j = start
            while j < n and _is_word(text[j]):
                j += 1
            if j - start <= limit:
                cut = j

    # 切点越过标点后，把紧跟的空格收进上一段 —— 免得下一段开头带着一个空格
    # （拼回去照样一个字不少，只是空白落在前一段尾巴上）。
    # ⚠️ 吸收到上限为止：别让这一小步把这一段撑过上限（上面那些不等式才成立）。
    while cut < start + limit and cut < n and text[cut] in " \t":
        cut += 1
    return cut


def chunk(text, limit, max_parts=8):
    """把 `text` 按 `limit` 拆成若干段。返回 `(段列表, 并进最后一条的字数)`。

    · `"".join(段列表) == text`（**逐字节相等**，一个字都不少）；
    · 每段长度 ≤ `limit`，只有两种**明说的例外**：① 最后那条"兜底并进来的"
      （见下）；② 某一段开头那个 `[CQ:...]` 码**本身就比上限长**时，
      那一段为了不劈坏机器码会超一点（真实配置 1200/1500 下不可能发生）。
    · `max_parts` 是兜底条数（0/None = 不限）：真超过了就把多出来的段全部
      并进最后一条，第二项返回**并进来的字数**（0 = 没并）。
    """
    text = text or ""
    limit = max(1, int(limit or 1))
    if len(text) <= limit:
        return ([text] if text else []), 0

    parts = []
    i, n = 0, len(text)
    while i < n:
        if n - i <= limit:
            parts.append(text[i:])
            break
        cut = _cut_at(text, i, limit)
        parts.append(text[i:cut])
        i = cut

    merged = 0
    mp = int(max_parts or 0)
    if mp > 0 and len(parts) > mp:
        tail = "".join(parts[mp - 1:])
        merged = len(tail)
        parts = parts[:mp - 1] + [tail]
    return parts, merged


def split(text, limit, max_parts=8):
    """只要段列表（测试和调用方都用这个就够）。"""
    return chunk(text, limit, max_parts)[0]
