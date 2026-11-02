#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""识图：把这条消息里的图**真拿到手**，转成 base64 塞进给模型的请求里。

「真能看见」和「装作看见」的区别，全在这个文件里。踩过的坑（写在 napcat.py 开头）：

  · 关掉 `enableLocalFile2Url` 之后推过来的是「裸文件名 + CDN 地址」，
    而**那个文件根本没落到磁盘上** —— 所以本地找不到就得下载；
  · CQ 码里的 `&` 被转义成 `&amp;`，地址原样去下会 400 invalid rkey
    （`napcat.params_of()` 已经 unescape 好了，这里直接用它的结果）；
  · CDN 地址里的 rkey **十几分钟就过期**，要下就趁早；
  · 下载要带 UA + `Referer: https://qun.qq.com/`。

═══ 晚：CDN 那条路被 QQ 换掉了，改成「先问 NapCat 要」 ═══

那天 19:42 起她连续两次「图没拿到：下载失败（HTTPError）」。真机探针查出来的事实：

  · 09-19 ~ 09-29 的群图地址**全是** `multimedia.nt.qq.com.cn/download`（rkey 70 字），
    直连下得动（09-29 15:41 还成功取到过一张）；
  · 09-30 17:09（北京）起**全变成** `gchat.qpic.cn/download`（rkey 59 字），
    NapCat 日志里 7 条一条不落，一个旧域名都没有；
  · 同一个地址直连 → `HTTP 400 {"retcode":-5503007,"retmsg":"download url has expired"}`；
    把 `&` 还原成 `&amp;` 再试 → `-5503010 invalid rkey`。
    （两条都试过 = unescape 那步是**好的**，坏的不是它，是地址本身在 CDN 那边就作废了。）
  · 换头（UA / Referer / 不带任何头）**结果一模一样** —— 不是请求头的事。
  · 但把**同一个**文件名交给 NapCat 的 `get_image`，它 0.5~3.0 秒就把图交出来了，
    落的还是真图片（JPEG 的 `\\xff\\xd8\\xff`、PNG 的 `\\x89PNG`）；
    连那两张失败过的图也一样拿得到 —— 它走的是 QQ 客户端自己的下载通道，
    不认我们手里那个 rkey。

所以现在的顺序变成（**首选是 ②**）：

  ① 本地绝对路径（老配置的遗留，`enableLocalFile2Url` 开着时才有）
  ② **问 NapCat 要**：拿事件里的文件名调 `get_image` → 它给本地路径 → 读那个文件
  ③ 直连 CDN 抓（域名被换过、rkey 又短命，只当兜底留着）

⛔ 四种失败原因（`why`）是**给模型看的文本**（它进 `note`、进 `_occasion`）——
   要改先问用户。所以状态码/响应体一律**只写 `base.log`**，
   一个字都不许漏进给模型的那句话里。

⚠️ 图**只看当前这条消息**里的：历史消息里只剩 `[图片]` 占位（§9.11）。
   拿不到就老实说拿不到 —— 绝不能让模型猜图上有什么。

═══════ 晚：加了一条「引用里那张图」的路（`load_quoted`）═══════

的：他把「只给当前这一轮的图、历史里只剩 `[图片]` 占位」这个**省 token 的
设计留着**（图大多是表情包，本来不用给模型看），但**有时候需要她看见已经发出去过
的图** —— 手机端有时发不出「图 + 文字」一条，只能先发图、再引用着那张图说话。

所以现在图有两个来源，**都挂到当前这一轮**：

  ① 他自己这条消息里的（`refs_of` → `load`，上限 `MAX_IMAGES`）—— 老路，没变；
  ② **他引用的那条**里的（`quoted_refs` → `load_quoted`，上限 `MAX_QUOTED`）——
     新路，**只认引用关系**（`[CQ:reply,id=…]` → NapCat `get_msg` 取那条 →
     再用下面同一套取图顺序把图拿到手）。

⛔ 新路的两条硬约束（用户定的）：
   · **不许靠关键词猜**（「提到图/照片才去找」那种做法他明确否了）—— 只认引用；
   · **图失败静默** —— 所以它没并进 `load()`：`load()` 拿不到图会生成一句给模型
     看的话（「这条消息带了 N 张图，但一张都没取下来」），引用这条取不到就当没看见
     （原来那四种失败话术一个字都不动）。

外加一句**事实**

    （他引用的那条是 <谁> 说的：「<被引用那条的文字>」）

   · **只在被引用那条真的有图、而且那张图真取到了**时才给；引用纯文字消息
     **一个字都不加**；
   · 文字只取前 `QUOTE_TEXT_MAX`（100）字，长了加 `…`；名字用 `memory.display_name`
     （**跟前缀同一套**，同一个人不会变成两个）；
   · 全是事实，⛔ 一句指令都没有。
"""

import base64
import os
import re
import time
import urllib.error
import urllib.request

from . import base, napcat

MAX_IMAGES = 3
MAX_QUOTED = 2                       # **引用**里最多拿 2 张（防炸，用户 2026-09-30 定）
QUOTE_TEXT_MAX = 100                 # 被引用那条的文字最多带上这么多字（用户 2026-09-30 定）
MAX_BYTES = 8 * 1024 * 1024          # 单张上限（手机流量和 token 都要省）
TIMEOUT = 25
PULL_TIMEOUT = 20                    # 问 NapCat 要图那一步的超时（它要真下一张回来）
QUOTE_TIMEOUT = 15                   # 问 NapCat 要"被引用的那条"的超时（本机查询，很快）

_FETCHER = None                      # 自检用的假下载器（**不许联网**）
_PULLER = None                       # 自检用的假「问 NapCat 要图」（None = 真去问）
_QUOTER = None                       # 自检用的假「取被引用的那条消息」（None = 真去问）


def set_fetcher(fn):
    """自检挂钩：换成假的取图函数，离线跑完整链路。

    ⚠️ 设了它就等于进了「离线模式」：问 NapCat 那一步**也一起停** ——
       手机上 NapCat 的 3000 端口是真开着的，不关就会真去问它，
       自检就不再是「不联网」了。要在自检里测那一步，用 `set_puller()`。
    """
    global _FETCHER
    _FETCHER = fn


def set_puller(fn):
    """自检挂钩：只换掉「问 NapCat 要图」那一步（不设 = 真去问 NapCat）。"""
    global _PULLER
    _PULLER = fn


def set_quoter(fn):
    """自检挂钩：只换掉「取被引用的那条消息」那一步（不设 = 真去问 NapCat）。

    ⚠️ 跟 `set_puller()` 同一个道理：`set_fetcher()` 进了离线模式之后，
       这一步**也一起停**（见 `_quoted_msg`）—— 手机上 NapCat 的 3000 端口
       是真开着的，不关就真去问了，自检就不再是「不联网」了。
    """
    global _QUOTER
    _QUOTER = fn


_IMG_CQ = re.compile(r"\[CQ:image,([^\]]*)\]")
_ANY_CQ = re.compile(r"\[CQ:[^\]]*\]")     # 残余机器码（洗被引用那条的文字时用）


def _refs_from_raw(raw, limit):
    """从一段 CQ 原文里拆出每张图：{'file': 文件名, 'id': file_id, 'url': CDN 地址}。

    `refs_of()`（当前这条）和 `quoted_refs()`（被引用的那条）走的都是它 ——
    两条路的 CQ 形态一模一样，坑也一样（`&` 被写成 `&amp;`，靠 `params_of` unescape）。
    """
    out = []
    for m in _IMG_CQ.finditer(raw or ""):
        d = napcat.params_of(m.group(1))
        out.append({"file": (d.get("file") or "").strip(),
                    "id": (d.get("file_id") or "").strip(),
                    "url": (d.get("url") or "").strip()})
        if len(out) >= limit:
            break
    return out


def _refs_from_segs(segs, limit):
    """同上，只是从**段数组**那份拆（`get_msg` 也会给 `message`）。

    ⚠️ 段数组里的 `url` **没有** `&amp;` 转义（只有 CQ 原文那份才有），所以这条
       少一次 unescape。`raw_message` 优先（跟收消息那条路保持一致），
       段数组只当兜底。
    """
    out = []
    for seg in segs or []:
        if not isinstance(seg, dict) or seg.get("type") != "image":
            continue
        d = seg.get("data") or {}
        out.append({"file": str(d.get("file") or "").strip(),
                    "id": str(d.get("file_id") or "").strip(),
                    "url": str(d.get("url") or "").strip()})
        if len(out) >= limit:
            break
    return out


def refs_of(ctx):
    """这条消息里的每张图：{'file': 文件名, 'id': file_id, 'url': CDN 地址}。

    为什么不直接用 ctx["images"]：那是一个**扁平**列表（本地路径和 CDN 混在一起，
    顺序还取决于哪张图有哪个候选），配不成对。这里按 CQ 码重新拆一次，
    每张图的候选归到自己那一份里。

    ⚠️ `file` 现在是「文件名」（比如 `9C9ED4…A7.jpg`），别当成路径 ——
       它是要喂给 NapCat `get_image` 的那个键（见 `_napcat_pull`）。
    """
    raw = ctx.get("raw") or ""
    out = _refs_from_raw(raw, MAX_IMAGES)
    if out:
        return out
    # 兜底：raw 里没有 CQ 码（不该发生），就用 server 拼好的候选列表，一张一候选
    return [{"file": r, "id": "", "url": ""} if not str(r).startswith("http")
            else {"file": "", "id": "", "url": r}
            for r in (ctx.get("images") or [])][:MAX_IMAGES]


# ── 引用（回复）里带过来的图 ────────────────────────────────────────
#
# 一条新路：**他引用了一条带图的老消息时，把那条里的图
# 一起挂到这一轮**。动机（他的原话）：
#   · 「只给当前这一轮的图、历史里只剩 [图片] 占位」这个省 token 的设计他喜欢，留着；
#   · 但手机端**有时发不出「图 + 文字」一条**，只能先发图、再引用着那张图说话 ——
#     这时候历史里那张图只剩占位，她就真看不见了。
#   · ⛔ 他明确否掉了「靠关键词猜（提到图/照片才去找）」的做法，所以这里
#     **只认引用关系**（`[CQ:reply,id=…]` → `get_msg`），一个字都不猜。
#
# ⛔ 硬约束：这条路**不许新增任何给模型看的文本**。
#    所以它自己一条函数（`load_quoted`），**不并进 `load()`** —— `load()` 拿不到图
#    会生成一句给模型看的话（「这条消息带了 N 张图，但一张都没取下来」），
#    而引用这条**失败就静默**：当她没看见那张图，走现有的失败话术。


def _quoted_msg(reply_to):
    """问 NapCat 要**被引用的那条消息**（`get_msg`）。拿不到就 None。

    ⚠️ 它回来的形状跟事件一模一样：`raw_message`（CQ 原文，`&` 同样被写成 `&amp;`）
       + `message` 段数组，另外还带 `sender`（谁说的）和 `time`。
       实测：对今天的图 `retcode=0`，图片段的 `file` 就是文件名
       跟事件里那个一样能喂给 `get_image`。
    ⚠️ 拿不到时实测是 `{"retcode":200,"data":null}` —— **原因只进日志，不往上传**。
    """
    rid = str(reply_to or "").strip()
    if not rid:
        return None
    try:
        if _QUOTER is not None:
            ok, data = _QUOTER(rid)
        elif _FETCHER is not None:
            return None                   # 离线自检：不许碰 NapCat 的 3000 端口
        else:
            from . import im              # 放在函数里：免得 import 绕回去
            ok, data = im._napcat_call("get_msg",
                                       {"message_id": int(rid) if rid.isdigit() else rid},
                                       timeout=QUOTE_TIMEOUT)
    except Exception as e:
        base.log("问 NapCat 要被引用的那条炸了（%s）：%s: %s"
                 % (rid, type(e).__name__, str(e)[:160]))
        return None
    if not ok:
        base.log("问 NapCat 要被引用的那条没成（%s）：%s" % (rid, str(data)[:160]))
        return None
    if not isinstance(data, dict) or not (data.get("raw_message") or data.get("message")):
        base.log("问 NapCat 要被引用的那条，回来的不是一条消息（%s）：%s"
                 % (rid, str(data)[:160]))
        return None
    return data


def quoted_refs(ctx):
    """**被引用的那条消息**里的图片引用（最多 MAX_QUOTED 张）；拿不到就是 []。

    只认引用关系（`ctx["reply_to"]`，来自 `napcat.reply_id`），没引用就直接返回 ——
    **一次 NapCat 都不问**（没引用就不多事）。
    """
    info = _quoted_info(ctx)
    return info["refs"] if info else []


def _plain(raw):
    """被引用那条的**文字**，按"她看到的历史行"那套清洗。

    ① `napcat.display_text()`：去 @她、去引用机器码、`[CQ:image,…]`→`[图片]`；
    ② 再把**残余**的 CQ 码（`[CQ:shake]` / `[CQ:forward]` 这种没进占位表的）削掉 ——
       跟 `agent._plain()` 对历史行做的事一样（⛔ 机器码不许进给模型看的文本）。
    """
    t = napcat.display_text(raw or "")
    t = _ANY_CQ.sub(" ", t)
    return re.sub(r"[ \t]{2,}", " ", t).strip()


def _meaningful(t):
    """这段文字里有没有**真话** —— 只有 `[图片]`/`[表情]` 这种占位就不算。

    ⚠️ 纯图消息洗完就是 `[图片]`（占位非空），照原样判空会拼出一句
       「…说的：「[图片]」」—— 那不是话，是噪音（实测自检里当场抓到）。
    """
    return re.sub(r"\[[^\]]*\]", "", t or "").strip()


def _who_of_msg(msg, ctx):
    """被引用那条是谁说的 —— **跟前缀同一套写法**（`memory.display_name`）。

    ⚠️ 为什么用 `display_name`、不直接抄事件里的群名片：她别处（消息前缀、历史行）
       看到的就是同一套降级（称呼 → 本群名片 → 昵称 → QQ 号）。只给群名片的话，
       同一个人在她眼里会变成两个（`memory.display_name` 的注释里写过这条）。
       `fallback_name` 给名片/昵称，是"记忆库里查不到这个人"时的兜底。

    ⚠️ **被引用那条也按"所在群"的名片** —— 那张表是
       **按群**存的（`cards[群号]`），被引用的消息和当前这条在**同一个会话**里，
       所以直接把当前群号传下去（`card_now` 是这条被引用消息自己带的那张，优先用它）。
       ⛔ 格式就是 `名字: ` —— 方括号那截整条去掉了。
    """
    s = (msg or {}).get("sender") or {}
    uid = str(s.get("user_id") or "").strip()
    if not uid:
        return (s.get("card") or s.get("nickname") or "").strip() or "某人"
    from . import memory                    # 放在函数里：免得 import 绕回去
    return memory.display_name(uid, bool((ctx or {}).get("is_group")),
                               fallback_name=(s.get("card") or s.get("nickname") or ""),
                               card_now=(s.get("card") or ""),
                               group_id=((ctx or {}).get("group_id") or ""))


def _quoted_info(ctx):
    """被引用那条 → `{"refs": [...], "text": "…", "who": "…"}`；拿不到就是 None。

    只问一次 NapCat（`get_msg`），图和文字都从这一次的结果里取。
    """
    rid = (ctx or {}).get("reply_to")
    if not rid:
        return None
    msg = ctx.get("_quoted_msg") if isinstance(ctx, dict) else None
    if msg is None:
        msg = _quoted_msg(rid)
        if msg is not None and isinstance(ctx, dict):
            # 同一条被引用的消息只问 NapCat 一次（files.py 那条路也要读它）
            ctx["_quoted_msg"] = msg
    if not msg:
        return None
    raw = msg.get("raw_message") or ""
    refs = (_refs_from_raw(raw, MAX_QUOTED)
            or _refs_from_segs(msg.get("message") or [], MAX_QUOTED))
    if refs:
        base.log("引用的那条（%s）里有 %d 张图，一起挂到这一轮" % (rid, len(refs)))
    return {"refs": refs, "text": _plain(raw), "who": _who_of_msg(msg, ctx)}


def load_quoted(ctx):
    """把被引用那条的**图**（最多 MAX_QUOTED 张）和**那句话**取出来。

    返回 `(parts, note)`：
      parts —— 给模型的 content 段（图；一张都没拿到就是空列表）
      note  —— 一句话的**事实**：`（他引用的那条是 <谁> 说的：「<文字>」）`

    ⚠️ 图取不到**静默**（只写日志）：`load()` 拿不到图会生成一句给模型看的话
       （「这条消息带了 N 张图，但一张都没取下来」），引用这条**不许**那样 ——
       取不到就当没看见那张图。

    `note` 的规矩
      · **只在被引用那条真的有图、而且图真取到了**时才给（引用纯文字消息、
        或者那张图取不下来 → 一个字都不加，行为跟以前完全一样）；
      · 被引用那条**没话**（纯图 / 只有个表情）→ 这句话也给不出来，不给
        （`[图片]` 这种占位不算话，见 `_meaningful`）；
      · 文字**只取前 100 字**，长了加 `…`；
      · 说的全是**事实**，⛔ 没有一句指令（不写"他引用了这张图，你要…"）。
    """
    info = _quoted_info(ctx)
    if not info:
        return [], ""
    parts = []
    for ref in info["refs"]:
        b, why = _one(ref)
        if not b:
            base.log("引用的图没拿到（静默，不告诉她）：%s" % why)
            continue
        parts.append(_part(b))
    note = ""
    # ⚠️ 门槛：**真有一张图挂上了** + 被引用那条**真有话**（不是只剩 `[图片]` 占位）。
    #    「被引用那条有图、但一张都没取下来」时**不给这句话** —— 她手上没有图，
    #    却收到一句"他引用的那条说…"，等于凭空提起一张她看不见的图 ✗（静默优先）。
    if parts and _meaningful(info["text"]):
        t = info["text"]
        if len(t) > QUOTE_TEXT_MAX:
            t = t[:QUOTE_TEXT_MAX] + "…"
        note = "（他引用的那条是 %s 说的：「%s」）" % (info["who"], t)
    return parts, note


def _mime(b):
    if b[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    if b[:2] == b"BM":
        return "image/bmp"
    return "image/jpeg"


def _brief(url):
    """日志里用的短地址：留着主机和路径，把 rkey 的值掐短（它是凭据，别整条抄进日志）。"""
    try:
        head, _, q = (url or "").partition("?")
        if not q:
            return head[:300]
        parts = []
        for kv in q.split("&"):
            k, sep, v = kv.partition("=")
            if k.lower() in ("rkey", "token", "key", "sk") and len(v) > 8:
                v = v[:8] + "…"
            parts.append(k + sep + v)
        return (head + "?" + "&".join(parts))[:300]
    except Exception:
        return (url or "")[:300]


def _too_big():
    return "图太大了（超过 %d MB）" % (MAX_BYTES // 1024 // 1024)


def _read_local(path):
    """读本地文件。返回 (bytes, why)：

      · 读到了            → (bytes, "")
      · 文件在、但太大    → (None, 「图太大了…」) —— 这是给模型看的四种原因之一
      · 没有 / 不是文件   → (None, None) —— 调用方接着走下一条路
    """
    p = (path or "").strip()
    if p.startswith("file://"):
        p = p[7:]
    if not p or not os.path.isabs(p) or not os.path.isfile(p):
        return None, None
    try:
        if os.path.getsize(p) > MAX_BYTES:
            return None, _too_big()
        with open(p, "rb") as fh:
            return fh.read(), ""
    except Exception as e:
        base.log("读本地图失败（%s）：%r" % (p, e))
        return None, None


def _napcat_pull(name):
    """**首选路**：让 NapCat 用它自己的下载通道把图交出来。

    拿事件里的文件名（`file=`，就是 `9C9ED4…A7.jpg` 这种）调 NapCat 的 `get_image`，
    它回一个**本地路径**（`/root/.config/QQ/nt_qq_*/nt_data/Pic/…`）—— 图已经在手机上，
    我们直接读。这条路不认 CDN 那个 rkey，所以地址过期也照样拿得到。

    返回 (bytes, why)：拿到就是 ("…", "")；没拿到就是 (None, None)（接着走 CDN），
    或者 (None, 「图太大了…」)（本地文件真下载回来了，就是太大）。

    ⚠️ 这条路**失败不写进给模型的理由**：理由只说最后一次尝试的结果，
       四句话一个字都不变（见模块开头）。
    """
    key = (name or "").strip()
    if not key:
        return None, None
    if _PULLER is None and _FETCHER is not None:
        return None, None                 # 离线自检：不许碰 NapCat 的 3000 端口
    t0 = time.time()
    try:
        if _PULLER is not None:
            ok, data = _PULLER(key)
        else:
            from . import im               # 放在函数里：免得 import 绕回去
            ok, data = im._napcat_call("get_image", {"file": key}, timeout=PULL_TIMEOUT)
    except Exception as e:
        base.log("问 NapCat 要图炸了（%s）：%s: %s" % (key, type(e).__name__, str(e)[:160]))
        return None, None
    if not ok:
        base.log("问 NapCat 要图没成（%s）：%s" % (key, str(data)[:160]))
        return None, None
    path = (data.get("file") or "").strip() if isinstance(data, dict) else ""
    if not path:
        base.log("问 NapCat 要图，它没给路径（%s）：%s" % (key, str(data)[:160]))
        return None, None
    b, why = _read_local(path)
    if b:
        base.log("取到一张图：%d 字节、%.1f 秒（问 NapCat 要的：%s）"
                 % (len(b), time.time() - t0, path))
        return b, ""
    if why:
        base.log("问 NapCat 要图，拿回来的文件太大（%s）：%s" % (key, path))
        return None, why
    base.log("问 NapCat 要图，它给的路径读不出来（%s）：%s" % (key, path))
    return None, None


def _download(url):
    """带 UA 和 QQ 群 Referer 去下（少一个都可能被 CDN 拒）。"""
    if _FETCHER is not None:
        return _FETCHER(url)
    req = urllib.request.Request(url)
    req.add_header("User-Agent",
                   "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120 Mobile Safari/537.36")
    req.add_header("Referer", "https://qun.qq.com/")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read(MAX_BYTES + 1)


def _fetch_cdn(url):
    """兜底路：直连 CDN 抓。返回 (bytes, why)。

    ⚠️ 这里的 `why` 有两条是**给模型看的原文**（`下载失败（…）` / `下载回来是空的`）——
       不许顺手加状态码。状态码和响应体只进 `base.log`（见 `_brief` 和下面那两行）。
    """
    t0 = time.time()
    try:
        b = _download(url)
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read(200).decode("utf-8", "replace")
        except Exception:
            pass
        base.log("图下载失败（直连 CDN）：HTTP %s %s ｜ 响应体=%s ｜ 地址=%s"
                 % (e.code, e.reason, body.replace("\n", " ")[:200], _brief(url)))
        return None, "下载失败（HTTPError）"
    except Exception as e:
        # 别把 repr(e) 抄进日志：HTTPError/URLError 的 repr 里带着整条地址（含 rkey）
        base.log("图下载失败（直连 CDN）：%s: %s ｜ 地址=%s"
                 % (type(e).__name__, str(e)[:200], _brief(url)))
        return None, "下载失败（%s）" % type(e).__name__
    if not b:
        return None, "下载回来是空的"
    if len(b) > MAX_BYTES:
        return None, _too_big()
    base.log("取到一张图：%d 字节、%.1f 秒（直连 CDN）" % (len(b), time.time() - t0))
    return b, ""


def _one(ref):
    """拿一张图。返回 (bytes, 说明) —— 说明是给日志看的，拿不到时也给人看。"""
    f = (ref.get("file") or "").strip()
    # ① 本地绝对路径（老配置的遗留）
    b, why = _read_local(f) if os.path.isabs(f) else (None, None)
    if b:
        return b, "本地文件"
    if why:
        return None, why
    # ② 首选：问 NapCat 要（CDN 那条已经不可靠了，见模块开头）
    b, why = _napcat_pull(f or (ref.get("id") or "").strip())
    if b:
        return b, "NapCat 给的本地文件"
    if why:
        return None, why
    # ③ 兜底：直连 CDN
    u = (ref.get("url") or "").strip()
    if not u.startswith("http"):
        return None, "只有个文件名，没有地址（那种文件在手机上根本没落盘）"
    b, why = _fetch_cdn(u)
    if b:
        return b, "下载成功"
    return None, why


def _part(b):
    """一张图的字节 → 给模型的 content 段（当前这条和引用那条共用）。"""
    return {"type": "image_url",
            "image_url": {"url": "data:%s;base64,%s"
                                   % (_mime(b), base64.b64encode(b).decode())}}


def load(refs):
    """把 refs 变成给模型的 content 段。

    返回 (parts, note)：
      parts —— [{"type":"image_url","image_url":{"url":"data:image/jpeg;base64,…"}}, …]
      note  —— 没拿到的那些图，一句给模型看的**事实**（拿全了就是空串）
    """
    parts, miss = [], []
    for ref in refs or []:
        b, why = _one(ref)
        if not b:
            base.log("图没拿到：%s" % why)
            miss.append(why)
            continue
        parts.append(_part(b))
    note = ""
    if miss:
        note = ("这条消息带了 %d 张图，但一张都没取下来（%s）。"
                % (len(miss), "；".join(sorted(set(miss)))))
    return parts, note
