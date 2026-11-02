#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`history`：**回看上下文里没有的更早发言**。

数据源只有一个（定稿）：
NapCat 的 `get_group_msg_history` / `get_friend_msg_history`。

   ⛔ **不落盘**：结果只活在这份进程内存里 —— 重启即失，手机上不留任何文件。
   ✓ 内存里一个 2000 条的环形缓冲（≈300 KB），同一段话不重复问 NapCat；
   ✓ 查询结果缓存 5 分钟（同样的条件连着问，不再打接口）；
   ✓ 默认只查最近 **7 天**（再往前手机上一次要好几秒，用户拍板先限 7 天）；
   ✓ 一次最多 **100 条**；**每人每小时最多 20 次**（防她一个人把 NapCat 问穿）。

时间怎么认：`reminders.parse_when(..., past=True)` —— **过去模式**，⛔ 将来那套没动。
返回（定稿的键名）：`{"ok","匹配","给出","说明","记录"}`；
`说明` 的写法是「匹配 120 条，其中 30 条」（第 9 条那两行）。

⚠️ NapCat 的返回形状按 `{"messages":[…]}` 认，但也容得下直接给数组 / 给 `data`
   包一层 —— 手机上的版本不一定跟文档一样，认不出来就当这一页没查到（记日志）。
"""

import collections
import threading
import time

from . import base, clock, im, memory, napcat, persona, reminders, settings

# ⚠️ 这些数**只是默认值的引用 / 自检用**，运行时一律
#    `settings.get(...)` 现读（面板改完下一条消息就生效）。唯一真源在 settings.REGISTRY。
MAX_KEEP = 2000                    # 环形缓冲：最多留多少条（≈300 KB）
CACHE_TTL = 300                    # 查询结果缓存 5 分钟
DEFAULT_DAYS = 7                   # 默认只看最近 7 天
DEFAULT_COUNT = 30
MAX_COUNT = 100
PER_HOUR = 20                      # 每人每小时最多查几次
PAGE = 100                         # 一次向 NapCat 要几条
MAX_PAGES = 20                     # 一次查询最多往回翻几页（2000 条）

_LOCK = threading.RLock()
# key = (会话, message_id) → 一条记录；用 OrderedDict 当环形缓冲（O(1) 去重 + 挤掉最老的）
_RING = collections.OrderedDict()
_CACHE = {}                        # 查询条件 → (时间, 结果)
_RATE = {}                         # QQ → [查询时刻, …]
# 每个会话**已经往回翻到哪一刻**（再往前就没有了 → 0）。
# ⚠️ 没有它的话，每查一次都得从最新重新翻一遍（慢、而且白打 NapCat）。
_HORIZON = {}


# ── 会话 ────────────────────────────────────────────────────────────

def session(ctx):
    """`("g", 群号)` / `("p", QQ号)`；认不出来给 None。"""
    ctx = ctx or {}
    try:
        if ctx.get("is_group"):
            g = str(ctx.get("group_id") or "")
            return ("g", g) if g else None
        u = str(ctx.get("user_id") or "")
        return ("p", u) if u else None
    except Exception:
        return None


def _num(x, default=0, lo=1, hi=10 ** 12):
    try:
        n = int(str(x).strip())
    except Exception:
        return default
    return max(lo, min(hi, n))


# ── 从 NapCat 拿一页 ────────────────────────────────────────────────

def _norm(m, sid):
    """NapCat 的一条消息 → 我们环形缓冲里的一条（认不出来的给 None）。"""
    if not isinstance(m, dict):
        return None
    snd = m.get("sender") if isinstance(m.get("sender"), dict) else {}
    qq = str(snd.get("user_id") or m.get("user_id") or "")
    mid = str(m.get("message_id") or m.get("msgId") or m.get("id") or "")
    seq = str(m.get("message_seq") or m.get("real_seq") or m.get("messageSeq") or mid)
    try:
        at = float(m.get("time") or m.get("timestamp") or 0)
    except Exception:
        at = 0.0
    if not mid or not qq or at <= 0:
        return None
    text = napcat.display_text(napcat.text_of(m)).strip()
    if not text:
        return None
    return {"sid": sid, "id": mid, "seq": seq, "at": at, "qq": qq,
            "name": (snd.get("card") or snd.get("nickname") or "").strip(),
            "text": text[:2000]}


def _fetch(sid, before=None, count=PAGE):
    """向 NapCat 要**一页**（`before` = 从哪一条往前翻）。升序返回。"""
    kind, ident = sid
    try:
        ident_n = int(str(ident))
    except Exception:
        base.log("history：会话号不是数字（%r），不查了" % (ident,))
        return []
    if kind == "g":
        ep = "get_group_msg_history"
        payload = {"group_id": ident_n, "count": int(count)}
    else:
        ep = "get_friend_msg_history"
        payload = {"user_id": ident_n, "count": int(count)}
    if before:
        # ⚠️ OneBot11 的 `message_seq` 是**数字**；给字符串有些 NapCat 版本直接不认
        #    （那就翻不动页了）。能转成整数就转，转不了才原样给。
        try:
            payload["message_seq"] = int(str(before))
        except Exception:
            payload["message_seq"] = str(before)
    ok, data = im._napcat_call(ep, payload, timeout=20)
    if not ok:
        base.log("history：%s 没查通（%r）" % (ep, data))
        return []
    raw = data
    if isinstance(raw, dict):
        raw = raw.get("messages") if isinstance(raw.get("messages"), list) else raw.get("data")
    if not isinstance(raw, list):
        base.log("history：%s 回来的形状认不出（%s）" % (ep, str(data)[:120]))
        return []
    out = [e for e in (_norm(m, sid) for m in raw) if e]
    out.sort(key=lambda e: (e["at"], e["id"]))
    return out


def _remember(entries):
    """把这一页塞进环形缓冲（重复的不再进来；多了就挤掉最老的）。"""
    keep = settings.get("history.maxKeep")
    with _LOCK:
        for e in entries:
            k = (e["sid"], e["id"])
            if k in _RING:
                continue
            _RING[k] = e
            while len(_RING) > keep:
                _RING.popitem(last=False)


def _ring_list(sid):
    with _LOCK:
        return [dict(e) for e in _RING.values() if e["sid"] == sid]


def _ring_covers(sid, since):
    """这个会话**已经往回翻到 since 之前**了没有（翻到过就不用再打接口）。"""
    with _LOCK:
        h = _HORIZON.get(sid)
        if h is not None and h <= since:
            return True
        return any(e["sid"] == sid and e["at"] <= since for e in _RING.values())


def _touch_horizon(sid, at):
    """记下"这个会话最老翻到过哪一刻"（0 = 已经翻到头了）。"""
    with _LOCK:
        cur = _HORIZON.get(sid)
        _HORIZON[sid] = at if cur is None else min(cur, at)


def _collect(sid, since, until):
    """把 [since, until] 这段翻出来（先看环形缓冲，不够再往前翻页）。

    ⚠️ 翻页必须**按新拿到的东西**判断停不停：老版本 NapCat 不认 `message_seq` 时
       会把同一页反复给我们 —— 那种情况一律当"翻到头了"，否则一次查询能白打 20 次接口。
    """
    with _LOCK:
        got = {e["id"]: e for e in _RING.values() if e["sid"] == sid}
    if _ring_covers(sid, since):
        return list(got.values())
    cursor = None
    for _i in range(MAX_PAGES):
        page = _fetch(sid, before=cursor, count=PAGE)
        if not page:
            break
        _remember(page)
        fresh = [e for e in page if e["id"] not in got]
        for e in page:
            got[e["id"]] = e
        oldest = page[0]
        # 翻到头了（这一页比要的少 / 给回来的全是旧的）→ 以后不用再往前翻
        if len(page) < PAGE or not fresh:
            _touch_horizon(sid, 0)
            break
        _touch_horizon(sid, oldest["at"])
        if oldest["at"] <= since:
            break
        nxt = oldest.get("seq") or oldest.get("id")
        if not nxt or str(nxt) == str(cursor):
            _touch_horizon(sid, 0)
            break
        cursor = nxt
    return list(got.values())


# ── 时间 / 人 ───────────────────────────────────────────────────────

def _when(s, now, default):
    s = str(s or "").strip()
    if not s:
        return default
    at, _human = reminders.parse_when(s, past=True)
    return at


def _name(e, is_group, gid):
    qq = e.get("qq") or ""
    if qq and str(qq) == str(base.self_id()):
        return persona.name() or qq
    got = memory.display_name(qq, is_group, e.get("name") or "", group_id=gid)
    return got or e.get("name") or qq or "?"


def _line(e, is_group, gid):
    """一条记录给她的那一行：`2026-10-30 12:34 张三: 你好`。"""
    return "%s %s: %s" % (clock.at(e["at"]).strftime("%Y-%m-%d %H:%M"),
                          _name(e, is_group, gid), e["text"])


# ── 查询 ────────────────────────────────────────────────────────────

def query(ctx, who_qq="", q="", after="", before="", count=""):
    """`history` 那个工具的实现。`who_qq` 由 toolkit 先解析好（认人只有一处实现）。"""
    sid = session(ctx)
    if not sid:
        # ⚠️ （用户裁决）：这里**不给任何一句话** —— 理论上走不到（每个 ctx
        #    都带 key/群号/QQ），真要走到了就只回一个 `ok:false`，不编新台词。
        return {"ok": False}
    kind, gid = sid
    is_group = (kind == "g")
    uid = str((ctx or {}).get("user_id") or "")

    # 每人每小时最多 20 次（她一个人不能把 NapCat 问穿）
    per_hour = settings.get("history.perHour")
    now = time.time()
    with _LOCK:
        hits = [t for t in (_RATE.get(uid) or []) if now - t < 3600]
        if len(hits) >= per_hour:
            _RATE[uid] = hits
            base.log("history：%s 这一小时已经查了 %d 次（上限 %d），这次不查"
                     % (uid or "?", len(hits), per_hour))
            return {"ok": False, "error": "这一小时查得有点多（上限 %d 次），过一会儿再查" % per_hour}
        hits.append(now)
        _RATE[uid] = hits

    n = _num(count, settings.get("history.defaultCount"), 1,
             settings.get("history.maxCount"))
    try:
        after_ts = _when(after, now, now - settings.get("history.defaultDays") * 86400)
        before_ts = _when(before, now, now)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if before_ts > now:
        before_ts = now
    if after_ts >= before_ts:
        after_ts = before_ts - 60

    kw = str(q or "").strip()
    cache_key = (sid, n, str(who_qq or ""), kw, int(after_ts), int(before_ts))
    with _LOCK:
        hit = _CACHE.get(cache_key)
        if hit and now - hit[0] < settings.get("history.cacheTtl"):
            return dict(hit[1])

    try:
        pool = _collect(sid, after_ts, before_ts)
    except Exception as e:
        base.log("history：翻历史出错了（%r）" % (e,))
        pool = _ring_list(sid)

    if not pool:
        return {"ok": False, "error": "查不到更早的发言（NapCat 没给）"}

    picked = []
    for e in pool:
        if str(e.get("qq")) != str(who_qq) and who_qq:
            continue
        if not (after_ts <= e["at"] <= before_ts):
            continue
        if kw and kw not in (e.get("text") or ""):
            continue
        picked.append(e)
    picked.sort(key=lambda e: (e["at"], e["id"]))
    matched = len(picked)
    tail = picked[-n:]
    out = {"ok": True, "匹配": matched, "给出": len(tail),
           "说明": "匹配 %d 条，其中 %d 条" % (matched, len(tail)),
           "记录": [_line(e, is_group, gid) for e in tail]}
    base.log("history：%s 查「%s」→ 匹配 %d 条、给出 %d 条（翻了 %d 条底料）"
             % (gid, kw[:20], matched, len(tail), len(pool)))
    with _LOCK:
        _CACHE[cache_key] = (now, dict(out))
        if len(_CACHE) > 200:            # 缓存不长大（重启反正也清空）
            for k, (t, _v) in sorted(_CACHE.items(), key=lambda kv: kv[1][0])[:100]:
                _CACHE.pop(k, None)
    return out


def reset():
    """自检用：把内存里的环形缓冲 / 缓存 / 限流计数清掉。"""
    with _LOCK:
        _RING.clear()
        _CACHE.clear()
        _RATE.clear()
        _HORIZON.clear()


def stats():
    """自检 / 日志用。"""
    with _LOCK:
        return {"缓冲": len(_RING), "缓存": len(_CACHE), "限流表": len(_RATE)}
