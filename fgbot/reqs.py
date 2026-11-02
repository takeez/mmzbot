#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""待处理申请队列：**好友申请 + 群邀请**都在这里排队，等用户在网页面板上裁决。

改的（原话）：「可以运行加群的话，可以允许通过好友申请吗？
不过不要自动通过，而是把申请放到网页面板上，我决定拒绝还是通过还是忽略。
然后加群也改成那样。」—— 于是：

  · 以前：群邀请**自动同意**（`bot.autoAcceptGroupInvite`，默认 true）；
          好友申请**只写一行日志、零动作**。
  · 现在：两样都**只入库**（`requests.json`），一个动作都不发；用户在面板上点
          **通过 / 拒绝 / 忽略**（`request.approve` / `request.reject` / `request.ignore`）。

落盘文件 `requests.json`（**进 `deploy.py` 的 NEVER**，只活在手机上）：

```json
{"申请": [
  {"id": "A1B2C3", "类型": "好友", "qq": 10002, "群": 0, "名字": "张三",
   "验证消息": "我是张三", "flag": "…", "收到": 1750000000.0,
   "状态": "待处理", "处理时间": null, "处理结果": ""}
]}
```

字段口径（用户定的形状，别改）：
  · `类型` —— `"好友"` 或 `"群邀请"`（**只有这两种**，别的一律收）；
  · `qq`   —— 好友申请 = 申请人 QQ；群邀请 = **邀请人** QQ（谁把她拉进去的）；
  · `群`   —— 群邀请才有（群号），好友那条是 `0`；
  · `名字` —— 好友问 `get_stranger_info`、群邀请问 `get_group_info`（都只问一次，
             取不到就留空，绝不报错）；
  · `flag` —— NapCat 那条**一次性凭据**（真正裁决时要用它调被动 API）。
             ⛔ **它是一次性凭据**：只落这个本地文件，**绝不进日志、绝不进 /api 响应、
             绝不进面板 HTML**（`panel()` / `rows()` 都不带它）。
  · `状态` —— `待处理` / `已通过` / `已拒绝` / `已忽略` / `已过期`；
  · `处理时间` —— unix 秒或 `null`；`处理结果` —— 一行人话（面板上显示）。

三条语义（用户定死）：
  · **通过** = 真调 NapCat（好友 `set_friend_add_request(approve=True)`；
    群邀请 `set_group_add_request(approve=True, sub_type="invite")`）；
  · **拒绝** = 真调（`approve=False`）；
  · **忽略** = **一个 API 都不调**，只是从面板的待处理列表里收起来（标 `已忽略`），
    QQ 那边那条申请**还挂着** —— 所以随时可以 `restore()` 放回来再说。

⚠️ **过期**：挂了超过 `TTL_DAYS`（7）天、**没人碰过**的「待处理」→ 标成「已过期」
   （**不删**，面板「处理过的申请」里看得见）；`restore()` 放回来的那条**不会再自动过期**
   （用户亲手捞回来的，就该一直留着等他决定）。默认列表只显示「待处理」。

⛔ 这一整个模块**不进任何给模型看的文本**（改这些文字要先问维护者）：
   申请里的 `验证消息` 是**别人写的话**，它只给用户自己在面板上看，
   既不进提示词、也不进任何工具材料。
"""

import re
import secrets
import threading
import time
from datetime import datetime

from . import store

FILE = "requests.json"

# 短 id 的字符集：和 users.py 同款 Crockford base32（去掉了 I L O U，不会看混）
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ID_LEN = 6

FRIEND = "好友"
GROUP = "群邀请"
KINDS = (FRIEND, GROUP)
# 日志 / 面板上的叫法（`类型` 那个字段本身按用户定的形状写"好友" / "群邀请"，别改）
KIND_LABEL = {FRIEND: "好友申请", GROUP: "群邀请"}

PENDING = "待处理"
APPROVED = "已通过"
REJECTED = "已拒绝"
IGNORED = "已忽略"
EXPIRED = "已过期"
DONE = (APPROVED, REJECTED, IGNORED, EXPIRED)
ALL_STATES = (PENDING,) + DONE

# 超过这么多天的「待处理」→ 自动标成「已过期」（**不删**，让用户看得见）
TTL_DAYS = 7
TTL_SECONDS = TTL_DAYS * 86400

# 最多留多少条（先到先出：新的在后面，超了就从头丢）
KEEP = 300

# `验证消息` / `名字` / `处理结果` 的字数上限（别人写的话，别让它把文件撑爆）
COMMENT_MAX = 300
NAME_MAX = 60
RESULT_MAX = 200

# 拒绝**群邀请**时给对方的默认话（用户不填就发这句）。
# ⚠️ 这句会出现在 QQ 里（邀请人看得到），但它**不进任何给模型看的文本**。
DEFAULT_GROUP_REASON = "暂时不方便，谢谢"

_lock = threading.RLock()

_ID_RE = re.compile(r"^\d{4,12}$")


# ── 小工具 ──────────────────────────────────────────────────────────

def _now():
    return time.time()


def _ts(v):
    """时间戳 → float（拿不到回 0.0）。"""
    try:
        f = float(v)
    except Exception:
        return 0.0
    return f if f > 0 else 0.0


def _num(v):
    """QQ 号 / 群号 → 纯数字字符串（不合法回空串）。"""
    s = str(v if v is not None else "").strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s if _ID_RE.match(s) else ""


def _clean(s, n=COMMENT_MAX):
    """别人写的话：统一换行、去首尾空白、截断。⛔ 只做这些，不改写内容。"""
    t = str(s if s is not None else "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return t[:n]


def _new_id(taken):
    """内部短 id（6 位 Crockford base32 大写）—— 面板上点按钮认的就是它。"""
    for _ in range(64):
        i = "".join(secrets.choice(ALPHABET) for _ in range(ID_LEN))
        if i not in taken:
            return i
    return "".join(secrets.choice(ALPHABET) for _ in range(ID_LEN + 2))


def _ago(ts):
    """`收到`那个时间戳 → 人看的字（面板用）。"""
    ts = _ts(ts)
    if not ts:
        return ""
    d = time.time() - ts
    if d < 90:
        return "刚刚"
    if d < 3600:
        return "%d 分钟前" % int(d // 60)
    if d < 86400:
        return "%d 小时前" % int(d // 3600)
    if d < 86400 * 30:
        return "%d 天前" % int(d // 86400)
    return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")


def _at_text(ts):
    """绝对时刻（面板上写"什么时候收到的 / 什么时候处理的"）。"""
    ts = _ts(ts)
    return datetime.fromtimestamp(ts).strftime("%m-%d %H:%M") if ts else ""


# ── 读 / 写 ─────────────────────────────────────────────────────────

def records():
    """`requests.json` 里全部申请（`list`，坏文件当空）。

    ⚠️ 每次调用都现读（`store.read_json` 自己按 mtime 挡缓存）——
       这个文件小、读得也不勤，不值得再加一层进程内缓存去和别处写盘打架。
    """
    d = store.read_json(FILE)
    out = []
    if isinstance(d, dict):
        rows = d.get("申请")
        if isinstance(rows, list):
            for r in rows:
                if not isinstance(r, dict):
                    continue
                kind = str(r.get("类型") or "")
                rid = str(r.get("id") or "").strip().upper()
                if kind not in KINDS or not rid:
                    continue
                st = str(r.get("状态") or PENDING)
                if st not in ALL_STATES:
                    st = PENDING
                out.append({
                    "id": rid,
                    "类型": kind,
                    "qq": _num(r.get("qq")),
                    "群": _num(r.get("群")),
                    "名字": _clean(r.get("名字"), NAME_MAX),
                    "验证消息": _clean(r.get("验证消息")),
                    "flag": str(r.get("flag") or ""),
                    "收到": _ts(r.get("收到")),
                    "状态": st,
                    "处理时间": _ts(r.get("处理时间")) or None,
                    "处理结果": _clean(r.get("处理结果"), RESULT_MAX),
                })
    return out


def _outline(r):
    """落盘那一行（`qq` / `群` 照用户定的形状写**数字**）。"""
    return {
        "id": r["id"],
        "类型": r["类型"],
        "qq": int(r["qq"]) if r["qq"] else 0,
        "群": int(r["群"]) if r["群"] else 0,
        "名字": r["名字"],
        "验证消息": r["验证消息"],
        "flag": r["flag"],
        "收到": r["收到"],
        "状态": r["状态"],
        "处理时间": r["处理时间"],
        "处理结果": r["处理结果"],
    }


def _save(rows):
    """写盘。超过 KEEP 条就从**最老的**那头丢（新的在后面）。"""
    with _lock:
        rows = rows[-KEEP:] if len(rows) > KEEP else rows
        return store.write_json(FILE, {"申请": [_outline(r) for r in rows]})


def _expire_rows(rows, now=None):
    """把挂了超过 `TTL_DAYS` 天、**没人碰过**的「待处理」标成「已过期」（**不删**）。

    返回标了几条。
    ⚠️ "没人碰过" = `处理时间` 还是 `None`。用户**亲手从「已忽略 / 已过期」放回来**的那种
       带上了处理时间，就**不再自动过期**（他明确表示还要管这条，别跟他的手对着干）。
    """
    now = _now() if now is None else float(now)
    n = 0
    for r in rows:
        if (r["状态"] == PENDING and not r["处理时间"] and r["收到"]
                and (now - r["收到"]) > TTL_SECONDS):
            r["状态"] = EXPIRED
            r["处理时间"] = now
            r["处理结果"] = "挂了 %d 天没人管，自动标成已过期（QQ 那边那条还挂着，能放回来）" % TTL_DAYS
            n += 1
    return n


def expire(now=None):
    """过期清理（面板每次读列表前顺手跑一次）。返回标了几条。"""
    rows = records()
    n = _expire_rows(rows, now)
    if n:
        _save(rows)
    return n


def find(req_id):
    """按 id 找一条（大小写不敏感）。找不到回 `None`。**内部用**（带 flag）。"""
    rid = str(req_id or "").strip().upper()
    if not rid:
        return None
    for r in records():
        if r["id"] == rid:
            return r
    return None


def _key(r):
    """去重键：**优先 flag**（同一条上报重发时 flag 一样）。"""
    return r["flag"] or ("%s|%s|%s" % (r["类型"], r["qq"], r["群"]))


# ── 入库（收事件那条路：**只入库，一个动作都不发**）──────────────────

def add(kind, qq="", group="", name="", comment="", flag="", at=None):
    """收下一条申请。返回 `(收下了吗, 说明, 记录)`。

    ⚠️ **去重按 `flag`**： NapCat 可能把同一条上报重发一遍 —— 那就**只留一条**，
       而且**一个字的状态都不动**（已通过/已拒绝的不许被打回待处理）；
       只是"名字/验证消息还是空的"这种，顺手补上。
    ⚠️ 没有 flag 的照样收（用户该看得见"有这么一条"），只是面板上点通过/拒绝时
       会如实告诉他"这条没有 flag，得你自己在 QQ 里点"。
    ⛔ 这个函数**不发任何网络请求**（名字由调用方查好了传进来）。
    """
    kind = str(kind or "")
    if kind not in KINDS:
        return False, "不认识的申请类型：%r" % kind, None
    f = str(flag or "").strip()
    q = _num(qq)
    g = _num(group)
    if not f and not q and not g:
        return False, "这条申请既没有 flag、也没有号 —— 收不了", None
    nm = _clean(name, NAME_MAX)
    cm = _clean(comment)
    with _lock:
        rows = records()
        rec = {"id": "", "类型": kind, "qq": q, "群": g, "名字": nm, "验证消息": cm,
               "flag": f, "收到": float(at if at is not None else _now()),
               "状态": PENDING, "处理时间": None, "处理结果": ""}
        key = _key(rec)
        for r in rows:
            if _key(r) == key:
                changed = False
                if nm and not r["名字"]:
                    r["名字"] = nm
                    changed = True
                if cm and not r["验证消息"]:
                    r["验证消息"] = cm
                    changed = True
                if changed:
                    _save(rows)
                return True, "这条申请已经收过了（现在是「%s」）" % r["状态"], r
        rec["id"] = _new_id(set(r["id"] for r in rows))
        _expire_rows(rows)
        rows.append(rec)
        if not _save(rows):
            return False, "写不进 %s（手机上磁盘满了？）" % FILE, None
        return True, "收下一条%s（%s）" % (KIND_LABEL.get(kind, kind), nm or q or g or "?"), rec


def finish(req_id, status, result="", when=None):
    """直接改一条的状态（**不调 API**）—— 给"自动同意"那条老路和内部用。

    ⚠️ `处理时间` **一律写上**（包括放回「待处理」）：它同时也是"这条有人管过"的记号 ——
       `_expire_rows` 只自动过期**没人碰过**的那些（见那边的说明）。
    返回 `(改到了吗, 说明)`。
    """
    if status not in ALL_STATES:
        return False, "不认识的申请状态：%r" % status
    with _lock:
        rows = records()
        hit = None
        for r in rows:
            if r["id"] == str(req_id or "").strip().upper():
                hit = r
        if hit is None:
            return False, "没有这条申请"
        hit["状态"] = status
        hit["处理时间"] = float(when if when is not None else _now())
        hit["处理结果"] = _clean(result, RESULT_MAX)
        return (True, "「%s」标成「%s」了" % (hit["id"], status)) if _save(rows) \
            else (False, "写不进 %s" % FILE)


def _note(req_id, result):
    """只留一行说明、**不改状态**（比如"这次没办成，你可以再点一次"）。"""
    with _lock:
        rows = records()
        hit = None
        for r in rows:
            if r["id"] == str(req_id or "").strip().upper():
                hit = r
        if hit is None:
            return False
        hit["处理结果"] = _clean(result, RESULT_MAX)
        return _save(rows)


# ── 裁决：通过 / 拒绝 / 忽略 / 放回来 ───────────────────────────────

def _decide(req_id, yes, reason=""):
    """通过 / 拒绝的公共那段 —— **真的调 NapCat**。

    ⚠️ 好友和群邀请用的是**两个不同的被动 API**（参数也不一样）：
       · 好友：`set_friend_add_request(flag, approve)` —— ⛔ **没有 reason**；
       · 群邀请：`set_group_add_request(flag, sub_type="invite", approve, reason)`。
       所以用户在面板上填的原因：**群邀请**那条能发出去，**好友**那条发不出去
       （只记在这个本地文件里，面板上如实说明）。
    ⚠️ 没办成（NapCat 报错 / 没有 flag）→ **状态保持「待处理」**，只写一行说明，
       用户还能再点一次。
    """
    from . import im                       # 迟 import：免得和 im / agent 绕圈
    rec = find(req_id)
    if rec is None:
        return False, "没有这条申请（可能已经被清掉了）", panel()
    if rec["状态"] != PENDING:
        return False, "这条已经处理过了（现在是「%s」）" % rec["状态"], panel()
    flag = rec["flag"]
    if not flag:
        _note(rec["id"], "这条申请里没有 NapCat 给的凭据 —— 面板办不了，得自己在 QQ 里点")
        return False, "这条申请里**没有 NapCat 给的凭据**（事件里没带）—— 面板办不了，" \
                      "得你自己在 QQ 里点一下（或者点「忽略」把它收起来）", panel()

    reason = _clean(reason, 200)
    kind = rec["类型"]
    if kind == FRIEND:
        ok, why = im.set_friend_add_request(flag, approve=bool(yes))
    else:
        rsn = reason or ("" if yes else DEFAULT_GROUP_REASON)
        ok, why = im.set_group_add_request(flag, approve=bool(yes), sub_type="invite", reason=rsn)

    who = ("QQ %s" % rec["qq"]) if kind == FRIEND else ("群 %s" % rec["群"])
    label = "通过" if yes else "拒绝"
    name = KIND_LABEL.get(kind, kind)
    if not ok:
        _note(rec["id"], "%s%s没办成（NapCat：%s）—— 状态还是待处理，可以再点一次" % (label, name, why))
        return False, "%s%s没办成（NapCat 那边：%s）" % (label, name, why), panel()

    result = "%s了%s（%s）" % (label, name, who)
    if reason:
        if kind == FRIEND:
            result += "；你填的原因**没发出去**（好友这条接口不带原因，只记在这儿）：「%s」" % reason
        elif yes:
            result += "；你填的原因**没发出去**（通过时不带原因，只记在这儿）：「%s」" % reason
        else:
            result += "；给对方的原因：「%s」" % reason
    finish(rec["id"], APPROVED if yes else REJECTED, result)
    return True, "%s%s（%s）" % (label, name, who), panel()


def approve(req_id, reason=""):
    """通过一条申请（**真的调 NapCat**）。返回 `(成没成, 说明, 面板那份)`。"""
    return _decide(req_id, True, reason)


def reject(req_id, reason=""):
    """拒绝一条申请（**真的调 NapCat**）。返回 `(成没成, 说明, 面板那份)`。"""
    return _decide(req_id, False, reason)


def ignore(req_id):
    """**忽略** —— 只是从面板的待处理列表里收起来，**一个 API 都不调**。

    QQ 那边那条申请**还挂着**，所以随时能 `restore()` 放回来再说（用户定的语义）。
    """
    rec = find(req_id)
    if rec is None:
        return False, "没有这条申请（可能已经被清掉了）", panel()
    if rec["状态"] != PENDING:
        return False, "这条已经处理过了（现在是「%s」）" % rec["状态"], panel()
    finish(rec["id"], IGNORED, "面板上忽略了（QQ 那边那条申请还挂着，随时能放回来）")
    return True, "忽略了这条%s（QQ 那边还挂着）" % KIND_LABEL.get(rec["类型"], rec["类型"]), panel()


def restore(req_id):
    """把「已忽略 / 已过期」放回「待处理」（**不调任何 API**）。

    ⚠️ 放回来之后**不再自动过期**（`finish` 会写上处理时间，`_expire_rows` 只过期
       没人碰过的那种）—— 用户亲手捞回来的，就该一直留着等他决定。
    """
    rec = find(req_id)
    if rec is None:
        return False, "没有这条申请（可能已经被清掉了）", panel()
    if rec["状态"] not in (IGNORED, EXPIRED):
        return False, "只有「已忽略 / 已过期」能放回来（这条是「%s」）" % rec["状态"], panel()
    finish(rec["id"], PENDING, "手动放回待处理（这条不会再自动过期了）")
    return True, "把那条%s放回待处理了 —— 现在可以重新裁决" % KIND_LABEL.get(rec["类型"], rec["类型"]), panel()


# ── 面板 / 状态要的那份（⛔ 不含 flag）────────────────────────────────

def pending(now=None):
    """只看「待处理」那几条（新的在前）；顺手先把过期的标掉。"""
    expire(now)
    out = [r for r in records() if r["状态"] == PENDING]
    out.sort(key=lambda r: r["收到"], reverse=True)
    return out


def _row(r):
    """面板一行（**⛔ 绝不含 flag**）。

    ⚠️ 多给一个 `显示名`——
       备注 → 称呼 → 昵称 → QQ 号，唯一实现在 `who.display_name()`；
       `名字`（NapCat 现取的那个昵称）当"已有的昵称"喂进去，陌生人照旧看得见名字。
       **不现取**任何昵称（面板那一列不替 NapCat 加负担）。
    """
    from . import who                        # 懒 import：控制面才用到
    qq = str(r["qq"] or "")
    return {
        "id": r["id"],
        "类型": r["类型"],
        "qq": r["qq"],
        "群": r["群"],
        "名字": r["名字"],
        "显示名": who.display_name(qq, nick_hint=r["名字"]) if qq else (r["名字"] or ""),
        "验证消息": r["验证消息"],
        "多久之前": _ago(r["收到"]),
        "收到文字": _at_text(r["收到"]),
        "状态": r["状态"],
        "处理结果": r["处理结果"],
        "处理时间文字": _at_text(r["处理时间"]),
        "能恢复": r["状态"] in (IGNORED, EXPIRED),
    }


def rows(only_pending=True, limit=0):
    """面板要的那份列表（**不含 flag**）。"""
    rs = pending() if only_pending else records()
    if not only_pending:
        rs = sorted(rs, key=lambda r: (r["收到"]), reverse=True)
    if limit:
        rs = rs[:limit]
    return [_row(r) for r in rs]


def panel(history=30):
    """面板一整份：`{待处理: [...], 已处理: [...], 待处理数: n, 已处理数: m}`。"""
    now_p = pending()
    done = [r for r in records() if r["状态"] in DONE]
    done.sort(key=lambda r: (r["处理时间"] or r["收到"]), reverse=True)
    return {
        "待处理": [_row(r) for r in now_p],
        "已处理": [_row(r) for r in done[:history]],
        "待处理数": len(now_p),
        "已处理数": len(done),
    }


def stats():
    """一行字（日志 / /status 用）—— **不带 flag**。"""
    rs = records()
    n = len([r for r in rs if r["状态"] == PENDING])
    return "申请 %d 条（待处理 %d）" % (len(rs), n)
