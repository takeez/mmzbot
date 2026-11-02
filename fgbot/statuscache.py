#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""电脑发来的心跳（出站 `status.push`）—— 落盘缓存 + 过期判定 + 战况查询的备用材料。

**契约**（PCStatus《给手机那边的规格-多电脑接入.md》§4.1「⭐ 出站心跳 `status.push`」，
逐字读出来的，别看二手文档）：
  · `POST {电脑那侧的 notify.her.url}/api`，正文里 `action = "status.push"`；
  · 一跳 **30 分钟**，只在「工作日 + 工作时段」内发（时段外**一跳都不发**）；
  · 她收到要回 **200 / 204** —— 回 501 的话电脑会一直以为"她还不认识这个动作"；
  · 载荷键：`action/ok/日期/专注/摸鱼/摸鱼来源/现在/电脑名/上报时段/时段/UTC偏移`；
  · `时段`（机器可读）= `{工作日:[1..7], 时段:["HH:mm-HH:mm",…], 日期切换点:"HH:mm"}`。

这一层只做三件事：

  ① **收**（`record`）：那一跳的**载荷 + 我们收到的时刻**落进 `status-cache.json`（每位用户一条最新）；
  ② **判**（`within_window` / `same_logical_day` / `fresh`）：他这会儿在不在**他的**上报时段、
     缓存里那条心跳的 `日期` 是不是**他那台的"今天"**（`computer_day()`，跨时区按他那台算）；
  ③ **答**（`material`）：给 `t_pc_status` 拼那几句**用户已经逐字批准**的材料。

⭐ **2026-10-09（用户拍板）「当天的战况永不过期」**：`material()` 现在**只看日期** ——
   缓存那条心跳的 `日期` == **他那台的逻辑日**（`computer_day()`：拿载荷里现成的 `UTC偏移`
   + `时段.日期切换点` + 手机此刻算出来的）→ **一律可用**（哪怕它是 8 小时前那一跳），
   照旧带 `数据时间`；**只有日期不匹配**（= 他那台已经跨天）才回**现有那两句**
   （按他此刻在不在上报时段选：`他这会儿不在上报时段（…）` / `电脑没开机（…）`）。
   ⛔ 那句「最后心跳是 X 分钟前，已经超过 90 分钟没动静了」**留在代码里当死文本**
   （`STALE_TEXT` / `stale_text()`）—— 正式路径**再也不走它**，⛔ 不许删；
   原来那条 90 分钟的线（`STALE_SECONDS` / `fresh()`）照旧留着，自检里继续单测它。
     ⚠️ 2026-10-05 起：**同一个人（同一个 QQ）的其它电脑会并进来**（用户拍板的 1(a)/2(a)/3(a)，
        规则与解析/格式化在 `fgbot/merge.py`）—— 合并只动那几个**取值**，
        键名、形状、以及那三句话一个字都没动。

⚠️ **身份**：`server.py` 鉴权过了之后**按用户表的 id 存**（`users.json` → 契约：id 就是
缓存键，2026-10-03 互联网改造那一批接上的）；万一认不出人（不该发生）才退回
`cred_id()` = token 的 SHA-256 前 12 位（**不落明文**）。

⚠️ **这里一个字的台词都不许自己编**：`material()` 里那三句（"不在上报时段" / "数据时间" /
"最后心跳是 X 分钟前…"）是用户 2026-10-03 点名批准的，⛔ 别改写、别加话。
"""

import hashlib
import re
import time
from datetime import datetime, timedelta, timezone

from . import base, merge, store

CACHE_NAME = "status-cache.json"

# 过期线（用户拍板 90 分钟；他允许的范围是 60~90）。
# ⚠️ 判据是**严格大于** —— 正好 90:00 仍算新鲜，因为已批准那句说的是"**超过** 90 分钟"。
# ⚠️ **2026-10-09 起正式路径不再用它**（`material()` 改成"只看日期"，见文件头）：
#    这条线连同 `fresh()` 一起**留着**，自检里继续单测它（用户点名："可以留着"）。
STALE_SECONDS = 90 * 60

# ⛔ **死文本**（用户 2026-10-09 拍板：留在代码里、正式路径**不再触发**它）。
#    第三批那句「最后心跳是 X 分钟前，已经超过 90 分钟没动静了」—— ⛔ 不许删，
#    也⛔ 不许拿它当正式路径的答案（`material()` 里一个字都不提它）。
STALE_TEXT = "最后心跳是 %d 分钟前，已经超过 %d 分钟没动静了"


def stale_text(seconds):
    """那句**死文本**长什么样（只给自检/留档看；正式路径一个调用点都没有）。"""
    return STALE_TEXT % (int(seconds) // 60, STALE_SECONDS // 60)


# 逻辑日换日点的兜底（契约里 `日期切换点` 恒有，默认 04:00）
DEFAULT_DAY_START_MINUTES = 4 * 60

# 「我没指定这条缓存，你自己现取」的哨兵 —— `t_pc_status` 指名道姓查某台电脑时用得上：
# 那一路查不到必须答"没有"，**不能**退回成"全体最新那条"（那会答成别人的数据）。
_ALL = object()

_HHMM = re.compile(r"^(\d{1,2}):(\d{2})$")
_OFFSET = re.compile(r"^([+-])(\d{2}):(\d{2})$")


# ── 身份 ────────────────────────────────────────────────────────────

def cred_id(token):
    """「这是哪台电脑」的**兜底**键 —— 那把 token 的指纹，不是明文。

    ⚠️ 2026-10-03 之后正常路径不用它了：`server._cache_key()` 认得出人就拿
       `users.json` 的 **id** 当键（契约：id = 日志/缓存键）。这一份留给
       "认不出人"（主人模式、或用户表里没有他）那种兜底，**形状不变**。
    """
    tok = str(token or "").strip()
    if not tok:
        return "anon"
    return "t-" + hashlib.sha256(tok.encode("utf-8")).hexdigest()[:12]


# ── ① 收 ────────────────────────────────────────────────────────────

def record(payload, who="anon", now=None):
    """把一跳心跳落盘。返回 `(成没成, 说明)` —— 说明**只进日志**，不进给她的材料。"""
    if not isinstance(payload, dict):
        return False, "载荷不是 JSON 对象"
    if payload.get("ok") is False:
        # 契约：算不出战况就整条不发，所以 ok:false 的心跳本来就不该出现。
        return False, "ok=false 的那一跳不算战况（按契约它不该发）"
    ent = {
        "收到": float(now if now is not None else time.time()),
        "电脑名": str(payload.get("电脑名") or "")[:64],
        "载荷": payload,                      # 他们发来的那一份，原样存
    }
    d = store.read_json(CACHE_NAME) or {}
    if not isinstance(d, dict):
        d = {}
    users = d.get("用户")
    if not isinstance(users, dict):
        users = {}
    old = users.get(who) or {}
    users[who] = ent
    if not store.write_json(CACHE_NAME, {"版本": 1, "用户": users}):
        return False, "落盘失败（写不进 %s）" % CACHE_NAME
    where = str(payload.get("电脑名") or "?")
    tag = "覆盖上一条" if old else "第一条"
    return True, "%s（%s；键 %s）" % (where, tag, who or "未配 token")


def _entries():
    """所有缓存条目：`[(收到时刻, key, 条目), …]`（坏文件当空的，绝不抛）。"""
    d = store.read_json(CACHE_NAME) or {}
    users = d.get("用户") if isinstance(d, dict) else None
    if not isinstance(users, dict):
        return []
    out = []
    for who, ent in users.items():
        if isinstance(ent, dict) and isinstance(ent.get("载荷"), dict):
            try:
                at = float(ent.get("收到") or 0)
            except Exception:
                at = 0.0
            out.append((at, str(who), ent))
    return out


def _data_of(ent):
    """一条缓存条目里那几个**战况键**（一个都没有就给空 dict）。

    ⚠️ 电脑那边的规矩：值空着就**整个键不出现**（`摸鱼来源` / `现在` 都是这个规矩），
       所以这里也照"空的不进"来收。
    """
    p = ent.get("载荷") if isinstance(ent, dict) else None
    p = p if isinstance(p, dict) else {}
    out = {}
    for k in merge.FIELDS:
        v = p.get(k)
        if v not in (None, "", []):
            out[k] = v
    return out


def _ent_key(ent):
    """这条缓存是**哪个身份**的（拿 `收到` 时刻 + 载荷回查一遍）—— 找不到给空串。

    ⚠️ 正式路径用不上（按 `who` 取、或取全体最新那条时，键天生就在手上）；
       只有调用方**直接递一条条目进来**时才需要回查（自检那么用）。
       回查不到 → 空串 → 认不出人 → 这次不合并（**绝不瞎猜**）。
    """
    if not isinstance(ent, dict):
        return ""
    try:
        at = float(ent.get("收到") or 0)
    except Exception:
        at = 0.0
    pay = ent.get("载荷")
    for a, key, e in _entries():
        if e is ent:
            return key
        if at and abs(a - at) < 1e-6 and e.get("载荷") == pay:
            return key
    return ""


# ── 同一个人的几台电脑 → 拼成一份（用户 2026-10-05 拍板）────────────────
#
# 规则与实现（纯函数）在 `fgbot/merge.py` 里；这一节只负责"**去哪几条缓存里找那个人另外几台**"。
# ⛔ 这里一个字的台词都不许编：合并只动 `日期`/`专注`/`摸鱼`/`摸鱼来源`/`现在` 那几个**取值**，
#    键名、形状、以及那三句话一个字都不改。

def _rec_id(rec):
    return str((rec or {}).get("id") or "")


def person_qq(key):
    """这个缓存键（= 用户表里那条记录的 `id`）那个人**本人的 QQ 号**；认不出来给空串。

    ⚠️ 身份 = QQ（用户 2026-10-04 拍板）：同一个人**可能有多条记录**（几台电脑），
       它们共用这一个 QQ —— 合并就是按它把几台并成一份。
    """
    k = str(key or "").strip()
    if not k:
        return ""
    from . import users                       # 懒 import：users 又 import 本模块
    rec = users.by_id(k)
    return str((rec or {}).get("主人QQ") or "").strip()


def _same_person(qq):
    """同一个 QQ 的**所有**记录（同一个人多台电脑）；空 QQ / 认不出 → `[]`。"""
    s = str(qq or "").strip()
    if not s:
        return []
    from . import users                       # 懒 import：users 又 import 本模块
    return [r for r in users.records() if str(r.get("主人QQ") or "").strip() == s]


def merge_person(data, qq, skip=()):
    """把**同一个人的其它电脑**里「同一天」的战况并进 `data`（`data` = 主那条）。

    用户定的判据：**只要"今天"有数据就算**（⛔ 不看心跳新旧）；"今天" = 主那条（= 心跳最新
    那条）的 `日期`，只并**那一天**的那几条。
    `skip` = 不参与的那些记录 id（**直连那条要把它自己跳过**，不然同一台会被算两遍）。

    并不了（只有一台 / 认不出人 / 没人今天有数据 / 主那条连 `日期` 都没有）→ **原样返回**
    （`data` 这个对象本身，调用方拿 `is` 就能看出"没合并"）。
    """
    if not isinstance(data, dict) or not data:
        return data
    date = str(data.get("日期") or "")
    if not date:
        return data                           # 判不了"今天" → 不并（宁可不并，也不混别的天）
    recs = _same_person(qq)
    if len(recs) <= 1:
        return data                           # 只有一台（或者认不出人）→ 行为与从前逐字一致
    skip_ids = set(str(x) for x in (skip or ()) if str(x))
    parts = []
    for r in recs:
        k = _rec_id(r)
        if not k or k in skip_ids:
            continue
        d = _data_of(latest(k))
        if not d or str(d.get("日期") or "") != date:
            continue                          # 没数据 / 不是同一天 → 不参与
        if not any(d.get(x) not in (None, "") for x in ("专注", "摸鱼", "摸鱼来源")):
            continue                          # 只有个日期、没有战况 → 不算"今天有数据"
        parts.append(d)
    if not parts:
        return data
    return merge.merge_data([data] + parts)



def latest(who=None):
    """找**某台电脑**最新的一跳心跳那条缓存。

    ⚠️ 2026-10-03（A2）起可以指名道姓地找：`who` = `users.json` 里那台电脑的 **id**
       （= 缓存键，契约 B1；`t_pc_status` 拿到 `who` 那条用户记录后就用它）。
       `who` 留空 = 还是老行为：全体里取最新那条（主人没登记时的兜底）。
    找不到（没这个人 / 他从没发过心跳）就给 `None`。
    """
    es = _entries()
    if who is not None:
        w = str(who or "")
        if not w:
            return None
        for _at, key, ent in es:
            if key == w:
                return ent
        return None
    if not es:
        return None
    es.sort(key=lambda x: x[0], reverse=True)
    return es[0][2]


def drop(who):
    """删掉某个身份的那一条缓存（**撤销用户时一并删**，B2.3 的附带要求）。"""
    who = str(who or "")
    if not who:
        return False
    d = store.read_json(CACHE_NAME) or {}
    u = d.get("用户") if isinstance(d, dict) else None
    if not isinstance(u, dict) or who not in u:
        return False
    u.pop(who, None)
    return bool(store.write_json(CACHE_NAME, {"版本": 1, "用户": u}))


def age(ent, now=None):
    """这一条缓存多旧了（秒）。"""
    try:
        at = float(ent.get("收到") or 0)
    except Exception:
        at = 0.0
    return max(0.0, (time.time() if now is None else float(now)) - at)


def fresh(ent, now=None):
    """还没过期吗（过期线 90 分钟，严格大于才算过期）。"""
    return ent is not None and age(ent, now) <= STALE_SECONDS


# ── ② 判：他的"上报时段" ─────────────────────────────────────────────
#
# 口径照契约（`规格-多电脑接入.md:255-256`）+ 电脑侧实现（`ConfigSnapshot.cs:80-98/145-163`）：
#   · `From <= t < To`（**结束不含**）；`From > To` = 跨零点；`To = 24:00` = 到当天结束；
#   · `t` = **电脑本地**时刻（不是手机的）；
#   · 工作日 = **逻辑日**的星期几（本地时刻 < `日期切换点` 就减一天，`LogicalDay.cs:45-51`）。

def _parse_hhmm(s, allow_24=False):
    """`HH:mm` → 从 0 点起的分钟数；读不出来给 None。"""
    m = _HHMM.match(str(s or "").strip())
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if mi > 59:
        return None
    if h == 24 and allow_24 and mi == 0:
        return 24 * 60
    if h > 23:
        return None
    return h * 60 + mi


def _split_span(s):
    """`"09:00-18:00"` → `(540, 1080)`；`"10:00-24:00"` → `(600, 1440)`。坏的就 None。"""
    txt = str(s or "").strip()
    if "-" not in txt:
        return None
    a, _, b = txt.partition("-")
    f = _parse_hhmm(a, allow_24=False)
    t = _parse_hhmm(b, allow_24=True)
    if f is None or t is None:
        return None
    return f, t


def _in_span(minutes, f, t):
    if f <= t:
        return f <= minutes < t
    return minutes >= f or minutes < t      # 跨零点（22:00-06:00）


def _offset_minutes(s):
    """`"+08:00"` → 480；`"-05:00"` → -300；`"+05:30"` → 330。读不出来给 None。"""
    m = _OFFSET.match(str(s or "").strip())
    if not m:
        return None
    sign = -1 if m.group(1) == "-" else 1
    return sign * (int(m.group(2)) * 60 + int(m.group(3)))


def computer_now(payload, now=None):
    """把"此刻"投影成**那台电脑的本地时刻**（`UTC偏移` 是唯一的时区信息）。

    朋友的电脑在西班牙 —— 拿手机自己的时区去判他的上报时段会判错。
    `UTC偏移` 读不出来时退回手机本地时刻（尽力而为，别把整条路弄断）。
    """
    now = time.time() if now is None else float(now)
    off = _offset_minutes((payload or {}).get("UTC偏移"))
    if off is None:
        # 没有"他那台"的偏移 → 退回**本机**本地时刻（走 base，别用 datetime.fromtimestamp：
        # 数据目录/时区可配之后，本机本地时间只有一个出口）
        return base.local_at(now)
    tz = timezone(timedelta(minutes=off))
    return datetime.fromtimestamp(now, timezone.utc).astimezone(tz).replace(tzinfo=None)


# ── 「他那台现在算几号」──────────────────────────────────────────────
#
# ⭐ 2026-10-09「当天战况永不过期」就靠这一个数：**同一个逻辑日的口径**（电脑侧
#    `LogicalDay.Of`，`LogicalDay.cs:45-51`）—— 那台电脑的本地时刻 < `日期切换点`
#    就减一天。⚠️ 一个字的解析都不新写：偏移用 `computer_now()`、切换点用 `_parse_hhmm()`。

def _day_start_minutes(payload):
    """`时段.日期切换点` → 从 0 点起的分钟数（读不出来 = 兜底 `04:00`）。"""
    w = (payload or {}).get("时段")
    w = w if isinstance(w, dict) else {}
    start = _parse_hhmm(w.get("日期切换点"))
    return DEFAULT_DAY_START_MINUTES if start is None else start


def _logical_date(t, start):
    """某个**电脑本地时刻**落在哪个逻辑日（`t` = 那台的本地 naive 时刻）。"""
    d = t.date()
    if t.hour * 60 + t.minute < start:
        d = d - timedelta(days=1)        # 凌晨那一段属于**前一天**
    return d


def computer_day(payload, now=None):
    """**他那台现在算几号** —— `"MM-DD"`（跟载荷里 `日期` 一个写法）；判不出来给 `""`。

    ⚠️ 三个输入全是**现成的**：载荷里的 `UTC偏移`（`computer_now()`）、
       `时段.日期切换点`（`_parse_hhmm()`，缺了按契约默认 `04:00`）、手机此刻。
       ⛔ 别拿手机自己的日期去顶他那台 —— 西班牙那台会在半夜被算成北京日期（用户点名）。
    """
    if not isinstance(payload, dict) or not payload:
        return ""
    t = computer_now(payload, now)
    return _logical_date(t, _day_start_minutes(payload)).strftime("%m-%d")


def _norm_day(s):
    """`"10-09"` / `"2026-10-09"` → `"10-09"`（契约给的是 `MM-dd`；多写了年份也认）。"""
    t = str(s or "").strip()
    return t[-5:] if len(t) >= 5 and t[-3] == "-" else t


def same_logical_day(ent, now=None):
    """缓存里那条心跳的 `日期` == **他那台的"今天"** 吗（判不了 → `False`）。

    ⭐ 这就是"当天战况永不过期"的那一条判据：只要它真，`material()` 一律给数据
       （⛔ 不看心跳多旧）；它假 = 他那台已经跨天 → 回现有那两句。
    """
    if not isinstance(ent, dict):
        return False
    p = ent.get("载荷") if isinstance(ent.get("载荷"), dict) else {}
    d = _norm_day(p.get("日期"))
    return bool(d) and d == _norm_day(computer_day(p, now))


def within_window(ent, now=None):
    """他这会儿在**他的**上报时段里吗？→ `True` / `False` / `None`（判不了）。

    `None` 的三种情形：这份缓存里没有机器可读的 `时段`（老版本电脑 / 夹具）、
    `工作日` 是 `[]`（这台电脑永远不发心跳 —— "时段"这件事等于不存在）、时段写坏了。
    """
    if not isinstance(ent, dict):
        return None
    p = ent.get("载荷") if isinstance(ent.get("载荷"), dict) else {}
    w = p.get("时段")
    if not isinstance(w, dict):
        return None

    days, hours = w.get("工作日"), w.get("时段")
    if not isinstance(days, list) or not isinstance(hours, list):
        return None
    day_nums = []
    for d in days:
        try:
            n = int(d)
        except Exception:
            return None
        if n not in (1, 2, 3, 4, 5, 6, 7):
            return None
        day_nums.append(n)
    if not day_nums:
        return None                      # [] = 永远不发心跳 → 不用判"时段"
    spans = []
    for h in hours:
        r = _split_span(h)
        if r is None:
            return None
        spans.append(r)
    if not spans:
        return None

    t = computer_now(p, now)
    day = _logical_date(t, _day_start_minutes(p))   # 逻辑日：凌晨那一段属于**前一天**
    if day.isoweekday() not in day_nums:
        return False
    minutes = t.hour * 60 + t.minute
    return any(_in_span(minutes, f, to) for f, to in spans)


# ── ③ 答：给 t_pc_status 的材料 ──────────────────────────────────────
#
# ⛔ 这一个函数里的中文**全部**是用户 2026-10-03 点名批准的原话（三句 + 一个键），
#    一个字都不许改写、不许再加别的话。要改先去问用户（改这些文字要先问维护者）。

# 「这会儿拿不到它的数据」那一句 —— 用户 2026-10-03 逐字定的原话，**一个字都不许改**。
# ⚠️ 与 `toolkit._NO_HB` **同一句**（toolkit 那边引用的就是这个常量，省得两处各写一遍漂了）。
#    用处有两处，都是"拿不到他那台的数据"这**同一个事实**：
#      · 他有登记、但一跳心跳都没发过（toolkit 那条老路）；
#      · 缓存里那条已经**跨天**、他那台这会儿在（或判不出在不在）上报时段（这一层）。
NO_HEARTBEAT = "电脑没开机（或者换了地址、连不上）—— 这会儿拿不到它的数据"


def last_seen(who, now=None):
    """某个身份的缓存有多旧（秒）；没有他的缓存就 `None`。

    只给**面板「用户管理」页**看"这个人最近有没有在报心跳"用 —— 不进给她的材料。
    """
    who = str(who or "")
    for at, key, ent in _entries():
        if key == who:
            return max(0.0, (time.time() if now is None else float(now)) - at)
    return None


def ago_text(seconds):
    """`23 秒前` / `12 分钟前` / `6 小时前` —— 前两档照用户给的那个例子（2026-10-03 批准）。

    ⚠️ **2026-10-09**：加了 `N 小时前` 这一档，而且**只在 `secs > STALE_SECONDS`（90 分钟）
       那一段用** —— 那一段在旧的正式路径上**从来不会说话**（超 90 分钟直接回那句死文本），
       所以用户已经批准的那两档输出**一个字都没变**（≤90 分钟照旧 `N 分钟前`）。
       写法沿用面板里既有的那一种（`groups.py` 的 `_human_ago`：`"%d 小时前"`）。
    """
    s = max(0, int(seconds))
    if s < 60:
        return "%d 秒前" % s
    if s > STALE_SECONDS:
        return "%d 小时前" % (s // 3600)
    return "%d 分钟前" % (s // 60)


# 老名字（自检里原先写的是私名，留个别名免得老引用炸）
_ago_text = ago_text


def material(ent=_ALL, who=None, now=None):
    """战况查询能用的那份**材料**；没有缓存时返回 `None`（调用方走原来那三句）。

    `ent` 留空 = 现取（`latest(who)`，`who` 留空就是全体最新那条）；
    也可以直接把一条缓存条目递进来（自检这么用）。
    ⚠️ 别把 `None` 当第二条的参数用 —— `None` 是"这条缓存没有"的正常返回值，
       拿它当"没指定"的话，**指名道姓查某人查不到时反而会答成别人的数据**（踩过）。

    ⛔ **`who` 留空（= "全体最新那条"那个兜底）2026-10-05 起正式路径一个调用方都没有了**：
       用户拍板「真的做到所有人都一样」之后，`t_pc_status` 一律拿**说话人那条记录的 `id`**
       进来查（认不出 id 就当"没有缓存"，绝不退回这里）。这一段**保留**（自检还在用它验
       "一份缓存都没有"），但**谁都不许拿它当正式路径** —— 那等于把别人的数据答给他。
       ⚠️ 自检里有一条断言：`pc_status` 的每一次调用递进来的 `who` 都是**非空**的。

    三种表现（定稿）：
      · 缓存那条 `日期` == **他那台的今天** → 缓存那几个键 + 一个 `数据时间`
        （⭐ 2026-10-09 起**不再看心跳新旧** —— 当天的数据永不判过期，见文件头）
      · 跨天了 + 他这会儿**不在**上报时段 → `他这会儿不在上报时段（工作日 09:00-18:00）`
      · 跨天了 + 他这会儿**在**上报时段（或判不出在不在） → `电脑没开机（…）`（`NO_HEARTBEAT`）

    ⚠️ 2026-10-05：**同一个人的其它电脑会并进来**（用户拍板的 1(a)/2(a)/3(a)，
       规则在 `fgbot/merge.py`）：主那条 = 这里选出来的这条（心跳最新那条），
       `日期` 跟它相同的其它台相加、`摸鱼来源` 按来源名相加，`现在` / `数据时间`
       照旧只看主那条。**只有一台时逐字不变**；那几句话也一个字都没动。
    """
    if ent is _ALL:
        # 主那条 = 原来那套选取（`who` 给了就按那个身份取、没给就全体最新），
        # 顺带把它的**键**拿在手上 —— 合并要靠它认出"这是谁"。
        ents = _entries()
        pick = None
        if who is not None:
            w = str(who or "")
            for x in ents:
                if w and x[1] == w:
                    pick = x
                    break
        elif ents:
            pick = max(ents, key=lambda x: x[0])
        ent, key = (pick[2], pick[1]) if pick else (None, "")
    else:
        ent, key = ent, _ent_key(ent)
    if not ent:
        return None
    p = ent.get("载荷") if isinstance(ent.get("载荷"), dict) else {}
    data = _data_of(ent)
    if not data:
        return None                      # 这一跳里一个战况键都没有 —— 当没有缓存

    # ⭐ 2026-10-09（用户拍板）：**当天的数据永不判过期** —— 缓存那条 `日期` 就是
    #    他那台的"今天"（`computer_day()`，跨时区按他那台算）→ 一律可用，
    #    ⛔ 不管它是多久以前收到的（8 小时前那一跳也算）；照旧带 `数据时间`。
    if same_logical_day(ent, now):
        secs = age(ent, now)
        # 同一个人的其它台（同一天）并进来；自己那条（`key`）一定要跳过，不能算两遍
        data = merge_person(data, person_qq(key), skip=(key,))
        out = {"ok": True}
        out.update(data)
        out["数据时间"] = ago_text(secs)
        return out

    # 日期不匹配 = 他那台已经跨天 → 回**现有那两句**（按他此刻在不在时段内选）。
    # ⛔ 这里一句新话都没有；那句 90 分钟的死文本（`STALE_TEXT`）谁也不许捡回来用。
    if within_window(ent, now) is False:
        win = str(p.get("上报时段") or "").strip()
        if win:
            return {"ok": False, "error": "他这会儿不在上报时段（%s）" % win}
        return {"ok": False, "error": "他这会儿不在上报时段"}
    return {"ok": False, "电脑不在线": True, "error": NO_HEARTBEAT}
