#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""出站：经 NapCat 的 HTTP 接口发消息，以及把事件转发给电脑。

两条完全独立的路，别混：
  · NapCat 出站（send_group / send_private / poke）—— 她说话，走 127.0.0.1:3000
  · 电脑转发（forward_to_pc / pc_alive）—— 「状态」「说明」要电脑的数据时走这条路

═══ 太长怎么办：**自动拆成几条依次发**（2026-10-04 用户拍板）═══

以前是硬截断（超出的丢掉、末尾补「…」）—— 真机上真丢过话（1020 字截到 800）。
现在 `send_group` / `send_private` 都走 `send_long`：按上限拆开、**依次发**、
两条之间停一小会儿，**一个字都不丢**。拆分规则本身在 `chunker.py`（全项目唯一一份），
出口只有这一处 —— 她的话、提醒、播报、她主动插话全从这儿出去，所以口径天然一致。

  · 引用（`reply`）和 @（`at`）**只挂在第 1 条**上：第二条再"回复一次"同一条消息很怪，
    而且 OneBot 的 `reply` 本来就只认一条（见 `_segs`）。
  · 表情（`faces`）挂在**最后一条**尾巴上（那本来就是句尾的装饰）。
  · 中间有一条没发出去 → **后面的不发了**（别硬凑，那只会把半截话刷出去），
    写一行日志说明发到第几条、剩几条没发。

⚠️ 上限/间隔/兜底条数都在 `config.json` 的 `agent` 一节（见 `_split_cfg`）。
"""

import hashlib
import hmac
import json
import re
import socket
import threading
import time
import urllib.request

from . import base, chunker, fgsig, settings

_last_scan = 0     # 上次扫网段找电脑的时间（避免频繁扫）


# ── NapCat 出站 ─────────────────────────────────────────────────────

def _napcat_raw(endpoint, payload, timeout=20, retry=True, kind="send"):
    """真正发请求的那一层。返回 `(ok, why, data)`：

        ok=True   → why=''，data = 响应里的 `data` 段（原样，dict/list/None 都可能）
        ok=False  → why='retcode' 或 'network'，data=None

    ⚠️ 为什么单独留这一层：**两种调用方要的东西不一样**。
       · 发送那套（`_napcat_post`）只要「成没成 + 什么原因」，靠 why 决定降级重发；
       · 查询那套（`_napcat_call`，比如群名）要的是**返回值本身**。
       以前只有前者，而它**把响应正文丢了** —— `group_name()` 于是把「失败原因」
       当成 JSON 正文去解析，拿到空串、静默返回空群名（踩过，见 `group_name`）。

    `kind`（2026-09-30 加，**只管日志措辞**）：`"send"` = 发送，`"query"` = 查询。
    ⚠️ 以前查询失败也打「NapCat 报发送失败」—— 查个消息不存在，日志里却写着
       "发送失败"，排查时能把人带沟里（实测就踩了：`get_msg` 报"消息不存在"，
       日志读起来像她的消息没发出去）。查询就是查询，措辞分开，一个字的正文都不变。
    """
    url = base.napcat_url() + "/" + endpoint
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    tok = base.cfg().get("napcat", {}).get("token") or ""
    if tok:
        req.add_header("Authorization", "Bearer " + tok)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
            if d.get("retcode", 0) != 0:
                # ⚠️ 措辞别写成「没发出去」—— 实测这句不成立。
                # NapCat 报 failed（`Timeout: NTEvent ... NodeIKernelMsgService/sendMsg`）
                # 之后，消息**过一会儿还是落地了**（它内部排队）。
                # 所以这里只能照它的话说：它报了失败。真真假假查不出来。
                if kind == "query":
                    base.log("查 NapCat 失败（%s）：%s" % (endpoint, str(d)[:160]))
                else:
                    base.log("NapCat 报发送失败（不一定是真失败，它经常过会儿又发出去）：%s -> %s"
                             % (endpoint, str(d)[:160]))
                if retry and base.cfg().get("napcat", {}).get("retryOnReject", False):
                    # 默认走不到这里（retryOnReject 默认 false）。
                    # 开着就会重复发送，证据见 config.json 里那段说明。
                    time.sleep(1.5)
                    base.log("按配置重试一次：%s（这可能发出第二遍）" % endpoint)
                    return _napcat_raw(endpoint, payload, timeout=timeout, retry=False, kind=kind)
                return False, "retcode", None
            return True, "", d.get("data")
    except Exception as e:
        if kind == "query":
            base.log("查 NapCat 失败（%s）：%r" % (endpoint, e))
        else:
            base.log("发消息失败 %s: %r" % (endpoint, e))
        return False, "network", None


def _napcat_post(endpoint, payload, timeout=20, retry=True):
    """**只关心成没成**的 NapCat 调用。返回 (是否成功, 原因)。

    原因分两类，调用方要靠它决定要不要降级重试：
      'retcode' —— NapCat 明确拒了（比如消息段不认），重试有意义
      'network' —— 连不上/超时，重试没意义（而且可能造成重复发送）

    ⚠️ 关于 timeout：发消息时用 `_timeout()`（默认 8 秒，刻意压短），
       见那个函数的注释。这里的 20 秒是给**非发送**调用用的默认值。

    ⚠️ 这一段踩过两次，两次结论相反，按**后面的**来：

    【第一次】原以为是「超时给短点，失败就失败」。结果发现 NapCat 发群消息会先撞
    一次「没有可用的网络适配器」再自己重试（§8 记过这条噪音），整个过程经常
    超过 8 秒。实测 13:55:10 / 13:55:20 各报一次 `TimeoutError('timed out')`，
    但消息**其实都发出去了**（QQ 记录里能看到）—— 日志里留下两条假失败。

    【第二次，推翻了上面的结论】NapCat 报 failed **不代表没发出去**。实测它
    内部排队，报失败之后过十几秒消息照样落地。所以「等久一点」并不能让我们
    更确定，只是白等 —— 等待期间整个发送队列都被堵住，用户那边的观感就是
    「非常非常慢」。因此**发送超时反而压到 8 秒**（见 `_timeout()`）：
    我们等多久不影响它什么时候真的发出去，只影响我们白等多久。

    另外这两次都印证了同一条规则：**network 超时绝不重试**
    （消息可能已经发出去了，重试就发两遍）；只有 NapCat「明确报拒」才允许
    降级重发（比如去掉引用/表情再发一次）。

    ⚠️ 它**不回响应正文**（第二个位置是原因串）。要返回值请用 `_napcat_call`。
    """
    ok, why, _data = _napcat_raw(endpoint, payload, timeout=timeout, retry=retry)
    return ok, why


def _napcat_call(endpoint, payload, timeout=20, retry=False):
    """**要返回值**的 NapCat 调用（查询类，比如 `get_group_info`）。

    返回 `(ok, data)`：ok=True 时 data 是响应里的 `data` 段，否则是原因串。

    ⚠️ 默认 `retry=False`：查询是只读的，重试不会造成重复发送，
       但也**没必要**重试 —— 查群名失败就安静退回，别给 NapCat 加负担。
    """
    ok, why, data = _napcat_raw(endpoint, payload, timeout=timeout, retry=retry, kind="query")
    return (True, data) if ok else (False, why)



def encode_url(url):
    """把网址里的非 ASCII 字符转成百分号编码。

    ⚠️ **这步不能省。** urllib 不会自动做 —— 请求行是按 ASCII 编码的，
    地址里只要有一个中文字符就直接抛
    `UnicodeEncodeError: 'ascii' codec can't encode ... 'GET /zh/wiki/真永夜刃'`。
    实测踩过：她搜到中文 wiki 的链接（中文 wiki 的地址**全是中文**），
    然后 `fetch_url` 全部打不开。

    路径和查询串分开转（用的 safe 字符集不一样），已存在的 %XX 保持原样。
    """
    try:
        p = urllib.parse.urlsplit(url)
        return urllib.parse.urlunsplit((
            p.scheme,
            p.netloc,
            urllib.parse.quote(p.path, safe="/%:@&=+,;~()*!'$"),
            urllib.parse.quote(p.query, safe="=&%+/?@,;~()*!'$:"),
            p.fragment,
        ))
    except Exception:
        return url


def _segs(text, at=None, faces=None, reply_to=None):
    """拼一条消息的段。

    `reply`（引用某条消息）必须是**第一段**，这是 OneBot 11 的规矩。
    """
    msg = []
    if reply_to not in (None, "", 0):
        msg.append({"type": "reply", "data": {"id": str(reply_to)}})
    if at:
        msg.append({"type": "at", "data": {"qq": str(at)}})
        msg.append({"type": "text", "data": {"text": "\n" + (text or "")}})
    else:
        msg.append({"type": "text", "data": {"text": text or ""}})
    for f in (faces or []):
        msg.append({"type": "face", "data": {"id": str(f)}})
    return msg


def _timeout():
    # 发送超时。**调小一点是有意的**：
    # NapCat 的 send_msg 会一直等 QQ 内核确认，实测经常 10~20 秒才回，
    # 甚至回一个「失败」而消息其实已经发出去了（见 §8）。
    # 我们等多久**不影响它什么时候真的发出去**，只影响我们白等多久。
    # 所以宁可少等：把超时压到 8 秒，把这些时间还给下一条消息。
    return int(base.cfg().get("napcat", {}).get("sendTimeoutSeconds") or 8)


def _group_one(group_id, text, at=None, faces=None, reply_to=None):
    """群里发**一条**（拆分的活儿在 `send_long`，这里只管这一条）。

    带「装饰」的发送（引用 / 表情）被拒时，**自动去掉装饰重发** ——
    装饰只是锦上添花，不能因为它让整条回复丢掉。
    只在 NapCat 明确拒绝时重试，网络错误不重试
    （那种情况消息可能已经发出去了，重试会发两遍，见 §8）。
    """
    if faces or reply_to:
        ok, why = _napcat_post("send_group_msg",
                               {"group_id": group_id, "message": _segs(text, at, faces, reply_to)},
                               timeout=_timeout())
        if ok:
            return True
        if why == "retcode":
            base.log("带引用/表情的发送被拒，去掉装饰重发")
        else:
            return False
    return _napcat_post("send_group_msg",
                        {"group_id": group_id, "message": _segs(text, at)},
                        timeout=_timeout())[0]


def _private_one(user_id, text, faces=None, reply_to=None):
    """私聊发**一条**（同上：拆分的活儿在 `send_long`）。"""
    if faces or reply_to:
        ok, why = _napcat_post("send_private_msg",
                               {"user_id": user_id, "message": _segs(text, None, faces, reply_to)},
                               timeout=_timeout())
        if ok:
            return True
        if why == "retcode":
            base.log("带引用/表情的发送被拒，去掉装饰重发")
        else:
            return False
    return _napcat_post("send_private_msg",
                        {"user_id": user_id, "message": _segs(text)},
                        timeout=_timeout())[0]


def _split_cfg(kind):
    """拆条这件事的三个数：(每条上限, 两条之间停几秒, 兜底最多几条)。

    ⚠️ **群和私聊可以不一样**（用户 2026-10-04 允许的）：
       群里有别人看着，上限小一点（防刷屏，原值 800 → 现在 1200）；
       私聊只有她俩，原本**根本没有上限**，现在给 1500 ——
       用户明确要求"别调成无限"，所以给一个宽松但有限的值。

    ⚠️ 为什么兜底条数默认 8：正常根本用不到（1200 的上限下要 >9600 字才可能撞上），
       它纯粹防"模型抽风输出几万字 → 几十条连发刷屏"。真撞上不是丢内容，
       而是**把剩下的全部并进最后一条**（见 `chunker.chunk`）。
    """
    ag = base.cfg().get("agent") or {}
    # ⚠️ 单条上限走注册表（面板能调，改完下一条就生效）；间隔 / 兜底条数仍读 config。
    if kind == "group":
        cap = settings.get("agent.maxGroupReplyChars")
    else:
        cap = settings.get("agent.maxPrivateReplyChars")
    gap = ag.get("replySplitGapSeconds")
    gap = 0.5 if gap is None else float(gap)
    mp = ag.get("replySplitMaxParts")
    mp = 8 if mp is None else int(mp)
    return max(1, cap), max(0.0, gap), mp


def _cq_clean(text, faces=None):
    """把模型写出来的 CQ 码收拾干净（2026-10-30）。

    她偶尔会照上下文写出 `[CQ:face,id=319]`（那是 QQ 表情码）：
      · `face` → 真当成表情段发出去（`faces` 走现有那条路）
      · 别的 CQ 码（at / image / image_url / 红包 / 分享…）→ **一律剥掉** ✗
        否则她能自己拼出「@全体成员」或者把外部图片发进群 —— 那是注入 ✗
    返回 `(干净文本, 表情 id 列表)`。
    """
    text = text or ""
    ids = [str(f) for f in (faces or [])]
    m_cq = re.compile(r"\[CQ:([A-Za-z0-9_.\-]+)((?:,[^\]]*)?)\]")
    bad = []

    def _one(m):
        kind = (m.group(1) or "").lower()
        args = m.group(2) or ""
        if kind == "face":
            hit = re.search(r"(?:^|,)id=(\d+)", args)
            if hit:
                if hit.group(1) not in ids:
                    ids.append(hit.group(1))
                return ""
        bad.append(kind)
        return ""

    out = m_cq.sub(_one, text)
    # 用户 2026-10-30：别的 CQ 码直接剥掉，**不记日志**（日志留给真问题）
    # ⚠️ 只在"整条被剥空"时才返回空串；别 strip 尾部空白（拆条要逐字拼回去）
    if not out.strip() and ids:
        out = ""
    return out, ids


def send_long(kind, target, text, at=None, faces=None, reply_to=None):
    """**她的每一句话都从这儿出去**：按上限拆开，依次发。返回 `(全成没, 发出几条, 共几条)`。

    拆分的全部规则（在哪儿切、CQ 码不劈开、兜底条数）都在 `chunker.py`，
    这里只管"按拆出来的段一条条发出去 + 节奏 + 失败就停"。
    """
    from . import guards as _g
    text, faces = _cq_clean(text, faces)
    text = _g.strip_markdown(text)      # QQ 不渲染 Markdown：星号/井号/代码点全剥掉
    cap, gap, mp = _split_cfg(kind)
    parts, merged = chunker.chunk(text, cap, mp)
    if not parts:
        return True, 0, 0

    if merged:
        # 兜底条数撞上了：剩下的**并进最后一条**，不丢字。那一条会超上限 —— 允许。
        base.log("这条太长：按上限 %d 字拆，撞上兜底上限 %d 条 —— 剩下的 %d 字"
                 "**并进最后一条**（那一条变成 %d 字，超上限；⛔ 一个字都没丢）"
                 % (cap, mp, merged, len(parts[-1])))
    if len(parts) > 1:
        base.log("这条太长（%d 字，上限 %d）：拆成 %d 条依次发，两条之间停 %.1f 秒"
                 "（引用/@ 只挂在第 1 条）" % (len(text), cap, len(parts), gap))

    sent = 0
    for i, seg in enumerate(parts):
        if i:
            if gap > 0:
                time.sleep(gap)          # 小间隔：别连着刷屏、别招频率限制
        if kind == "group":
            ok = _group_one(target, seg,
                            at if i == 0 else None,
                            faces if i == len(parts) - 1 else None,
                            reply_to if i == 0 else None)
        else:
            ok = _private_one(target, seg,
                              faces if i == len(parts) - 1 else None,
                              reply_to if i == 0 else None)
        if not ok:
            base.log("拆开发：%d 条里第 %d 条没发出去 —— **后面的 %d 条不发了**"
                     "（已经发出去 %d 条）" % (len(parts), i + 1, len(parts) - i - 1, sent))
            return False, sent, len(parts)
        sent += 1
    return True, sent, len(parts)


def send_group(group_id, text, at=None, faces=None, reply_to=None):
    """群里说一句话。**太长会自动拆成几条依次发**（一个字都不丢）。

    返回 `(全发成了没)` —— 拆开之后中间有一条没出去就是 `False`
    （要"发出去几条"这种细节请直接用 `send_long`）。
    """
    return send_long("group", group_id, text, at=at, faces=faces, reply_to=reply_to)[0]


def send_private(user_id, text, faces=None, reply_to=None):
    """私聊说一句话。**太长会自动拆成几条依次发**（同上）。"""
    return send_long("private", user_id, text, faces=faces, reply_to=reply_to)[0]


def poke(group_id, user_id):
    return _napcat_post("group_poke", {"group_id": group_id, "user_id": user_id}, timeout=15)[0]


def set_group_add_request(flag, approve=True, sub_type="invite", reason=""):
    """同意 / 拒绝一条**加群请求**（OneBot 的 `set_group_add_request`）。

    ⚠️ 为什么要有它（2026-10-04 查实）：NapCat **没有**「自动同意群邀请」这种开关，
       它只做两件事 —— 把事件转发过来 + 提供这个**被动 API**。所以同不同意得我们自己调。

    ⚠️ **调用方只有一处**：`reqs.approve / reqs.reject` —— 也就是**用户在网页面板上
       点了「通过 / 拒绝」**才调（2026-10-04 第二批改的：以前是收到邀请就自动同意，
       现在群里那条邀请**进面板排队等用户裁决**，见 `fgbot/reqs.py`）。

    ⚠️ `sub_type` **必须跟事件对上**：`"invite"` = 被拉进群（我们的场景），
       `"add"` = 别人申请加群。两边的 flag 不是一回事，传错了 NapCat 找不到那条请求
       （默认值给 `"invite"` 是有意的：这条路的调用方只有群邀请）。

    ⚠️ `flag` 是**一次性凭据**：它只存在那一条事件里，本地只落 `requests.json`
       （deploy 的 NEVER，只活在手机上）—— ⛔ 不记日志、不进 `/api` 响应、不进面板 HTML。

    返回 `(成没成, 原因)` —— 和别的出站一样**只写日志、绝不抛**（出事只影响这一件事）。
    """
    payload = {"flag": str(flag or ""), "sub_type": str(sub_type or "invite"),
               "approve": bool(approve)}
    if reason:
        payload["reason"] = str(reason)
    return _napcat_post("set_group_add_request", payload, timeout=15)


def set_friend_add_request(flag, approve=True, remark=""):
    """同意 / 拒绝一条**加好友请求**（OneBot 的 `set_friend_add_request`）。

    ⚠️ 参数名按 **NapCat 的 schema** 核过（2026-10-04，见公开的 tool schema：
       `flag` / `approve` / `remark`）：⛔ **没有 `reason`** —— 好友这条接口
       **不带"拒绝理由"**（群那条才有）。所以面板上用户填的原因发不出去，
       只能记在本地 `requests.json` 里、并在 `reqs._decide` 里如实写明。
    ⚠️ `remark` = 给这个人起的**备注名**（通过时才有意义）；留空就不传这个键
       （少一个键少一种被 NapCat 挑刺的机会）。
    ⚠️ `flag` 是一次性凭据，规矩同 `set_group_add_request`（⛔ 不记日志、不上面板）。
    ⚠️ 调用方只有 `reqs.approve / reqs.reject`（用户在面板上裁决那一下）。

    返回 `(成没成, 原因)`。
    """
    payload = {"flag": str(flag or ""), "approve": bool(approve)}
    r = str(remark or "").strip()
    if r:
        payload["remark"] = r
    return _napcat_post("set_friend_add_request", payload, timeout=15)


def napcat_alive(timeout=1.5):
    """NapCat 自己还在吗（探端口，不做业务）。"""
    m = re.match(r"https?://([^:/]+):(\d+)", base.napcat_url())
    if not m:
        return False
    return _probe(m.group(1), int(m.group(2)), timeout)


# ── 电脑：发现与转发 ────────────────────────────────────────────────

def _pc_target():
    m = re.match(r"http://([^:/]+):(\d+)", base.cfg().get("pc", {}).get("url", ""))
    return (m.group(1), int(m.group(2))) if m else (None, None)


def _probe(host, port, timeout):
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def _local_prefix():
    """拿到手机自己的网段前缀，比如 192.168.1。

    容器里的网络命名空间就是手机的，所以 connect 一个外网地址
    就能问出本机 IP。"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip.rsplit(".", 1)[0]
    except Exception:
        return None


def _discover_pc(port):
    """电脑的 IP 是 DHCP，路由器重启后可能会变。

    配置里那个地址连不上时，扫一遍同网段找谁在听这个端口。
    只在真的连不上时才扫，而且十分钟内最多扫一次。"""
    global _last_scan
    now = time.time()
    with base.lock():
        if now - _last_scan < 600:
            return None
        _last_scan = now

    prefix = _local_prefix()
    if not prefix:
        return None

    base.log("配置里的电脑 %s:%d 连不上，开始扫同网段找它" % (prefix + ".?", port))
    found = []

    def work(i):
        h = "%s.%d" % (prefix, i)
        if _probe(h, port, 0.3):
            found.append(h)

    ts = [threading.Thread(target=work, args=(i,), daemon=True) for i in range(1, 255)]
    for t in ts:
        t.start()
    for t in ts:
        t.join(timeout=2.0)

    if not found:
        base.log("扫了一圈没找到电脑（它可能真的没开）")
        return None

    host = found[0]
    base.log("找到电脑了：%s（原配置 %s）" % (host, base.cfg().get("pc", {}).get("url")))
    # ⚠️ 2026-10-03：这里原来还有一行 `base.save_pc_url(...)`，把找到的地址落进
    #    `pc-address.txt`。全仓库 grep 过 —— 那个文件**只被写、从来没被读回来**
    #    （重启就丢 = 死代码），用户拍板选 (b)：**删掉写点，让这个文件彻底消失**。
    #    ⚠️ **扫描逻辑本身保留**（这一段一个字没动）：找到的那一次照样用，
    #       只是不再"记住"它 —— 下次连不上还是照规矩再扫一遍。
    return host



_GROUP_NAMES = {}          # 进程内缓存：群号 -> 群名（查过就不再查）
_GROUP_TRIED = set()       # 这一轮进程里试过的（失败的别反复查，免得每条消息都打一次接口）


def group_name(group_id):
    """群名（`油库里观察日记` 这种）。查不到就返回空串，调用方自己决定省不省那半句。

    ⚠️ 群名**不在消息事件里**（OneBot 只给 group_id），得问 NapCat 的 get_group_info。
       所以：进程内缓存 + 落盘缓存（store，跟 runtime.json 一个待遇 —— deploy 不覆盖），
       每个群每次进程只问一次；失败也记下"试过了"，不再重试（别给它加负担）。

    ⚠️ 这里踩过一个**静默失效**的坑（2026-09-28 修）：
       原先写的是 `ok, body = _napcat_post(...)` 然后把 `body` 当 JSON 解析 ——
       可 `_napcat_post` 的第二个位置是**失败原因**（'retcode'/'network'），
       成功时是**空串**，它**根本不回响应正文**。于是：
           · 查询其实成功了（NapCat 正常回了群名），
           · 但这里解析的是空串 → {} → 取不到名字 → **一声不响地 return ""**，
           · 日志里既没有「群名查到了」也没有「群名没查到」，group-names.json 也不生成。
       现在改用 `_napcat_call`（真返回 data 段），并且**每条退出路径都留痕** ——
       再有下次，日志里能直接看出来是哪一步没成。
    """
    gid = str(group_id or "").strip()
    if not gid:
        return ""
    if gid in _GROUP_NAMES:
        return _GROUP_NAMES[gid]
    if gid in _GROUP_TRIED:
        return ""
    _GROUP_TRIED.add(gid)
    try:
        from . import store
        d = store.read_json("group-names.json") or {}
        if isinstance(d, dict) and d.get(gid):
            _GROUP_NAMES[gid] = str(d[gid])
            return _GROUP_NAMES[gid]
    except Exception as e:
        base.log("群名：读落盘缓存出错（当没有）：%r" % (e,))
    try:
        ok, data = _napcat_call("get_group_info", {"group_id": int(gid)})
        name = ""
        if ok and isinstance(data, dict):
            name = (data.get("group_name") or "").strip()
        if not name:
            # ⚠️ 这一行是**故意留的**：以前这条路径完全静默，一个 bug 藏了很久。
            base.log("群名没查到（%s）：ok=%r data 里没有 group_name（%s）"
                     % (gid, ok, str(data)[:120]))
            return ""
        _GROUP_NAMES[gid] = name
        try:
            from . import store
            d = store.read_json("group-names.json") or {}
            if not isinstance(d, dict):
                d = {}
            d[gid] = name
            store.write_json("group-names.json", d)
        except Exception as e:
            base.log("群名：写落盘缓存出错（不影响这一轮）：%r" % (e,))
        base.log("群名查到了：%s = %s" % (gid, name))
        return name
    except Exception as e:
        base.log("群名没查到（%s）：%r" % (gid, e))
    return ""


_STRANGER_NAMES = {}       # 进程内缓存：QQ -> 昵称（查过就不再查）
_STRANGER_TRIED = set()    # 这一轮进程里试过的（失败也别反复打接口）


def stranger_name(user_id):
    """一个**陌生人**的昵称（`get_stranger_info` 的 `nickname`）。查不到回空串。

    ⚠️ 用途只有一个：**好友申请**进面板排队时，让用户看得见"是谁在申请"
       （见 `agent.on_request` → `reqs.add` 的 `名字`）。⛔ 它**不进给模型看的任何材料**。

    ⚠️ 和 `group_name` 一样：进程内缓存 + 每人每进程只问一次（失败也记"试过了"），
       别给 NapCat 加负担。

    ⚠️ 和 `group_name` **不一样**的一处：**不落盘**。申请那条记录里本来就存了名字
       （`requests.json`），没必要再养一个状态文件 —— 也就少一个 deploy 的 NEVER 要记。

    ⚠️ 为什么不用事件里的 `sender.nickname`：那条上报里带着**别人的**卡片/昵称，
       照老规矩一律不落盘（只认我们主动问出来的这一个字段）。
    """
    uid = str(user_id or "").strip()
    if not uid or not uid.isdigit():
        return ""
    if uid in _STRANGER_NAMES:
        return _STRANGER_NAMES[uid]
    if uid in _STRANGER_TRIED:
        return ""
    _STRANGER_TRIED.add(uid)
    try:
        ok, data = _napcat_call("get_stranger_info", {"user_id": int(uid)})
        name = ""
        if ok and isinstance(data, dict):
            name = (data.get("nickname") or data.get("nick") or "").strip()
        if not name:
            base.log("陌生人昵称没查到（%s）：ok=%r（%s）" % (uid, ok, str(data)[:120]))
            return ""
        _STRANGER_NAMES[uid] = name
        base.log("陌生人昵称查到了：%s = %s" % (uid, name))
        return name
    except Exception as e:
        base.log("陌生人昵称没查到（%s）：%r" % (uid, e))
    return ""


def pc_alive():
    """电脑上的 PCStatus 还活着吗？只探一下 TCP，不做业务。"""
    host, port = _pc_target()
    if not host:
        return False
    if _probe(host, port, base.cfg().get("pc", {}).get("timeoutSeconds", 3)):
        return True
    # 连不上：可能是电脑关机，也可能是它的 IP 变了
    return _discover_pc(port) is not None


def forward_to_pc(raw_body):
    """把整条事件原样转发给电脑上的 PCStatus，**并把它回的话带回来**。

    用和 NapCat 一模一样的形态：chunked + `X-Signature: sha1=<HMAC-SHA1(token,body)>`
    **外加**一整套新签名（`X-FG-Signature: sha256=…` + `X-FG-Timestamp` + `X-FG-Nonce`，
    契约 §6.2 坑 2 要的双向重放保护）。电脑那边的桥两套都认，照抄最稳。

    返回 `(ok, 电脑回的正文)`：
      · 新版的电脑会回一段 JSON（战况的事实），她拿它自己组织语言 —— 用户点名要的
        "电脑只给程序化的事实，措辞由模型来"；
      · 旧版的电脑只回 `204 No Content`（正文空）→ 那就是"它收下了但没给数据"，
        上层会让她照实说查不到，不再石沉大海。
    """
    url = base.cfg().get("pc", {}).get("url", "")
    m = re.match(r"http://([^:/]+):(\d+)", url)
    if not m:
        return False, ""
    host, port = m.group(1), int(m.group(2))
    wait = float(base.cfg().get("pc", {}).get("timeoutSeconds", 3))

    # ⚠️ 两套签名**用同一把 token**（两台机器必须共享同一个值）：
    #    ① 老 `X-Signature: sha1=` —— 老契约，电脑侧冻结的那一条，**照旧发**；
    #    ② 新 `X-FG-Signature: sha256=` + 时间戳 + nonce —— 2026-10-03 互联网改造那一批
    #       加的双向重放保护（契约 §6.2 坑 2：手机发出的请求也要带这两样）。
    #    手机 → 电脑那个方向的 token 就是**这台电脑配的那把**；主人自己那台用的
    #    就是现有这把共享 token（`bot.napcatToken`，缺了自动回退 `bot.token`，
    #    和 im.py 从前用 `bot.token` 时**逐字节一样**）。
    tok = base.napcat_token() or ""
    sig = hmac.new(tok.encode(), raw_body, hashlib.sha1).hexdigest()
    new = fgsig.sign_sha256(tok, raw_body)
    head = (
        "POST / HTTP/1.1\r\n"
        "Host: %s:%d\r\n"
        "Content-Type: application/json\r\n"
        "X-Self-ID: %d\r\n"
        "X-Signature: sha1=%s\r\n"
        "%s: %s\r\n"
        "%s: %d\r\n"
        "%s: %s\r\n"
        "Transfer-Encoding: chunked\r\n"
        "Connection: close\r\n"
        "\r\n" % (host, port, base.self_id(), sig,
                  fgsig.HEAD_SIG, new["sig"], fgsig.HEAD_TS, new["ts"],
                  fgsig.HEAD_NONCE, new["nonce"])
    ).encode()
    mid = len(raw_body) // 2
    payload = head
    for c in (raw_body[:mid], raw_body[mid:]):
        payload += ("%X\r\n" % len(c)).encode() + c + b"\r\n"
    payload += b"0\r\n\r\n"

    try:
        with socket.create_connection((host, port), timeout=wait) as s:
            s.sendall(payload)
            s.settimeout(max(wait, 8.0))        # 等它算战况；连接那步仍然按配置的短超时
            buf = b""
            while len(buf) < 65536:
                chunk = s.recv(8192)
                if not chunk:
                    break
                buf += chunk
    except Exception as e:
        base.log("转发给电脑失败: %r" % e)
        return False, ""

    text = buf.decode("utf-8", "replace")
    head_txt, _, body = text.partition("\r\n\r\n")
    if " 204 " in head_txt.split("\r\n")[0]:
        return True, ""
    # 简单处理分块编码：把 16 进制长度行去掉即可（我们只需要那些 JSON 字）
    if "chunked" in head_txt.lower():
        out = []
        for line in body.split("\r\n"):
            s2 = line.strip()
            if not s2:
                continue
            try:
                int(s2, 16)
                continue
            except ValueError:
                pass
            out.append(line)
        body = "\n".join(out)
    return True, body.strip()
