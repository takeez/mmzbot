#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跟 NapCat 打交道：**收进来的消息怎么读**。

出站（发消息/戳）不在这里，在 `im.py` —— 那套是 v1 用过、验证过的，
**别重写**，它踩过的坑都写在它自己的注释里（发送约 8 秒延迟、`retryOnReject`
会让每条发两遍、超时≠没发出去…）。这个文件只管**读**。

═══ 读的时候必须知道的四个坑（都是实测出来的）═══

① **事件有两种形态**
   NapCat 配的是 `messagePostFormat: "array"`：`message` 是段数组，
   但**同时**总带一个 `raw_message`（CQ 码字符串）。别只认一种。

② **CQ 码字符串里的 `&` 被转义过**（今天最贵的一个坑）
   它把 `&` 写成 `&amp;`、`,` 写成 `&#44;`。图片地址原样拿去下会得到
   `HTTP 400 {"retmsg":"invalid rkey"}`，`html.unescape` 之后 **同一个地址就 200**。
   所以抠出来的值一律 unescape —— 见 `params_of()`。

③ **图片别指望本地文件**
   关掉 `enableLocalFile2Url`（必须关，开着带图消息会卡在"推给她"那一步）之后，
   推过来的是「裸文件名 + QQ CDN 地址」，而**那个文件根本没落到磁盘上**（全盘搜过）。
   所以图片只能：先试本地（`file=` 是绝对路径时），否则下载 CDN（带 UA + Referer）。
   ⚠️ CDN 地址里的 rkey **有时效**（实测十几分钟），要下就赶紧下。

④ **媒体段换成可读占位**
   给模型看的文本里，`[CQ:image,…]` 要变成 `[图片]`，别把几百字 CQ 码原样喂进去。

⑤ **「引用（回复）」是 `reply` 段，只有 id**
   实测（2026-09-30，probe 打 `get_group_msg_history` + `get_msg` 验的）两种形态
   一模一样，都只给**被引用那条的 message_id**，没有别的字段：

       CQ 原文：`[CQ:reply,id=1692039722][CQ:at,qq=10001] 有点可爱`
       段数组：`[{"type":"reply","data":{"id":"1692039722"}},
                {"type":"at","data":{"qq":"10001"}},
                {"type":"text","data":{"text":" 有点可爱"}}]`

   所以 `raw_message` 里是 `[CQ:reply,id=…]`、数组里是 `type:"reply"`，
   **两种都要认**（取被引用的那条靠 `reply_id()`，见下）。
   ⚠️ 这个 id 只是**"他引用了哪一条"**这个事实；那条消息的内容要另外问
       NapCat 的 `get_msg`（在 `images.py` 那条路里，用户点名只要引用关系、
       不许靠关键词猜）。
"""

import html
import re

from . import base

# 媒体类 CQ 码 → 给人看的标记
_MEDIA = re.compile(r"\[CQ:(image|record|video|file|face|json|xml)[^\]]*\]")
_MEDIA_NAME = {"image": "图片", "record": "语音", "video": "视频", "file": "文件",
               "face": "表情", "json": "卡片", "xml": "卡片"}

# 引用（回复）：`[CQ:reply,id=1692039722]`。id 取到 `,` 或 `]` 为止（实测是纯数字）
_REPLY = re.compile(r"\[CQ:reply,id=([^,\]]+)\]")


def text_of(evt):
    """拿到这条消息的**原文**（CQ 码字符串）。

    优先 `raw_message`（永远在）；没有就退回把 `message` 段数组拼成 CQ 码。
    """
    raw = (evt.get("raw_message") or "").strip()
    if raw:
        return raw
    out = []
    for seg in evt.get("message") or []:
        if not isinstance(seg, dict):
            continue
        t, d = seg.get("type"), (seg.get("data") or {})
        if t == "text":
            out.append(str(d.get("text") or ""))
        elif t:
            out.append("[CQ:%s,%s]" % (t, ",".join("%s=%s" % (k, v) for k, v in d.items())))
    return "".join(out).strip()


def display_text(raw):
    """给模型和日志看的版本：去掉 @她的 CQ 码、**去掉引用机器码**、媒体换成 `[图片]` 这种标记。

    ⚠️ 只用于"给她看"和写日志。**路由判断要用原文** —— 那里要靠 CQ 码
       和名字前缀判断该不该理（例如开头有 `[CQ:at,…]` 时名字不在第一位）。

    ⚠️ 2026-09-30 用户批的：`[CQ:reply,id=…]` 也要剥掉。两个理由：
       ① 它是**给模型看的文本**里的一段机器码，对她没意义、白占 token；
       ② 更要紧的是：`agent._why()` 用 `startswith` 比"她叫什么"，
          引用之后不 @ 只叫名字（`[CQ:reply,id=X]MMZ…`）**原本叫不动她** ——
          机器码挡在名字前面，判定直接落空。剥掉之后两种叫法都接得上。
       （引用 id 本身没丢：日志那行由 `server.py` 补 `（引用 <id>）`；
        要拿它办事看 `reply_id()` / `ctx["reply_to"]`，都不经过这里。）
    """
    t = raw or ""
    t = re.sub(r"\[CQ:at,qq=%d\]\s*" % base.self_id(), "", t)
    t = _REPLY.sub("", t)
    t = _MEDIA.sub(lambda m: "[%s]" % _MEDIA_NAME.get(m.group(1), "媒体"), t)
    return t.strip()


def params_of(cq_params):
    """拆一段 CQ 码里的参数表（传 `[CQ:image,` 之后、`]` 之前那串）。

    ⚠️ 三个坑都在这几行里：
      ① 不能 `split(",")` —— `url=` 的值里**可能带逗号**，会把地址切碎；
      ② 值也不能用 `[^,]*` —— 它永远不吃逗号，带逗号的地址整条匹配失败；
         要用 `.*?` 配合前瞻 `,key=` 或结尾来判断边界；
      ③ **必须 html.unescape** —— NapCat 把 `&` 写成了 `&amp;`（见模块开头）。
    """
    out = {}
    for m in re.finditer(r"([A-Za-z_]+)=(.*?)(?=,[A-Za-z_]+=|$)", cq_params or ""):
        out[m.group(1)] = html.unescape(m.group(2))
    return out


def image_refs(raw, limit=3):
    """这条消息里的图片引用，**按可靠性排序**：先本地路径，其次 CDN 地址。

    返回一串字符串，每张图可能给两个候选（本地路径在前）。
    ⚠️ 用它们之前先看模块开头 ③：关掉 enableLocalFile2Url 之后，
       本地那一条基本找不到文件，最后还是要下载。
    """
    out = []
    for m in re.finditer(r"\[CQ:image,([^\]]*)\]", raw or ""):
        d = params_of(m.group(1))
        f = (d.get("file") or "").strip()
        u = (d.get("url") or "").strip()
        if f:
            out.append(f)
        if u:
            out.append(u)
        if len(out) >= limit * 2:
            break
    return out


def reply_id(evt):
    """这条消息**引用（回复）了哪一条** —— 返回被引用那条的 message_id（字符串）。

    没有引用就返回 `None`。

    ⚠️ 两种形态都认（跟 `text_of` 同一个理由，见模块开头 ⑤）：
       · CQ 原文：`[CQ:reply,id=1692039722]`
       · 段数组：`{"type":"reply","data":{"id":"1692039722"}}`
    先看 `raw_message`（永远在、实测就是它），没有再退到段数组。

    ⚠️ 拿到的只是一个 **message_id**，不是那条消息的内容 —— 内容要问 NapCat 的
       `get_msg`（`images.py` 那条引用取图的路在用它）。
    """
    m = _REPLY.search(evt.get("raw_message") or "")
    if m:
        return m.group(1)
    for seg in evt.get("message") or []:
        if not isinstance(seg, dict) or seg.get("type") != "reply":
            continue
        rid = str((seg.get("data") or {}).get("id") or "").strip().strip('"')
        if rid:
            return rid
    return None


def who_of(evt):
    """这条消息是谁发的：**群名片优先**，其次昵称，最后 QQ 号。

    ⚠️ 群名片会夹不可见的排版控制符（U+2066–U+2069），拿它当身份时会搅乱显示 ——
       要放进消息前缀的话记得先把那一段去掉。
    """
    s = evt.get("sender") or {}
    name = (s.get("card") or s.get("nickname") or "").strip()
    name = "".join(ch for ch in name if not (0x2066 <= ord(ch) <= 0x206F))
    return name or str(evt.get("user_id") or "?")


def message_id(evt):
    """引用回复要用它。"""
    return evt.get("message_id")
