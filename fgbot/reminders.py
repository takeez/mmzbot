#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""唤醒：账本 + 把「几点几分」听成人话
+ **到点把她叫醒**。

三件事分清楚（这一层最容易写歪）：

  · **时间怎么算**是代码的事（绝对时刻靠 base.py 设好的 TZ，容器里是 UTC，
    不修就差 8 小时 —— v1 栽过）。工具返回的是**具体时刻**这个事实。
  · **到点说什么**是模型的事：这里只负责「把事实递过去 + 把她叫醒」，
    一个字都不许是现成台词（红线 2）。所以 `on_due(rec)` 由 agent 层给。
  · **账本**落在 store 的 reminders.json（手机上的状态，deploy 不许覆盖）。

⚠️ 唤醒是**一次性的**：响过就从账本里删掉（用户没要周期唤醒）。
⚠️ 手机被关机/看门狗重启期间错过的那条，只在 `LATE_WINDOW_MIN` 以内补一次 ——
   三天后开机突然连响二十条，比不响更糟。

⚠️ （A6）：`remind` / `reminders` 两个工具合并成 `wake` ——
   记录里还是叫 `what`（内部字段，数据库兼容），对外一律叫「醒来做什么」；
   新增 `where_qq` / `where_name`：留空 = 在当前会话说，填了 = 私聊那个人。
   `parse_when` 新增**过去模式**（`past=True`，history 那个工具要用）：
   ⛔ 将来那套行为一个字都没动。
"""

import re
import threading
import time
from datetime import datetime, timedelta

from . import base, clock, guards, settings, store

LEDGER = "reminders.json"
# ⚠️ 下面这三个数改成**运行时从注册表现读**（面板能调）。
#    常量留着当默认值引用 / 自检用；唯一真源在 settings.REGISTRY。
LATE_WINDOW_MIN = 120             # 迟到超过这么久就不补了（2026-10-30：30 → 120 分钟）
TICK_SECONDS = 5
MIN_AHEAD = 5                      # 至少 5 秒以后（当场到点没意义）
MAX_AHEAD = 400 * 24 * 3600

# ── A6 的三个安全阀──────────────────────────────
#  · `MAX_CHAIN`：同一条唤醒链最多 3 层（第 4 层在 `toolkit.t_wake` 里直接拒）；
#  · `MAX_PER_HOUR`：全局每小时最多叫醒 6 次 —— 超了**不叫醒**，只记日志、一个字都不发；
#  · `LATE_WINDOW_MIN`：迟到 2 小时以内补一次（原来是 30 分钟）。
MAX_CHAIN = 3
MAX_PER_HOUR = 6
_FIRED = []                        # 这一小时真叫醒过的时刻（只活在内存里，重启清零）

_LOCK = threading.RLock()
_TIMER = None
_STOP = threading.Event()

WEEK = ("一", "二", "三", "四", "五", "六", "日")
CN = {"零": 0, "〇": 0, "一": 1, "两": 2, "二": 2, "三": 3, "四": 4,
      "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}


# ── 中文数字 ────────────────────────────────────────────────────────

def _num(s):
    """「9」「九」「十五」「二十三」「三十」→ int；认不出返回 None。"""
    s = (s or "").strip()
    if not s:
        return None
    if s.isdigit():
        return int(s)
    if not all(c in CN or c == "十" for c in s):
        return None
    if "十" in s:
        a, _, b = s.partition("十")
        tens = CN.get(a, 1) if a else 1
        ones = CN.get(b, 0) if b else 0
        return tens * 10 + ones
    return CN.get(s) if len(s) == 1 else None


_N = r"(\d{1,3}|[零〇一两二三四五六七八九十]{1,3})"


# ── 把「几点」听成时刻 ──────────────────────────────────────────────

def parse_when(s, now=None, past=False):
    """把一句时间说法算成绝对时刻。返回 (epoch, 人话描述)。

    认这些（不是穷举，认不出就抛 ValueError，让她去问清楚）：
        九点半 / 21:30 / 下午三点 / 晚上8点 / 明天早上7点 / 后天中午
        20分钟后 / 半小时后 / 两个钟头后 / 一会儿 / 3天后

    ⚠️ **纯英文**也认（走单独那条 `_parse_en`，中文这套一个字没动）
        tomorrow 8am / tomorrow morning / tonight / today 3pm / in 20 minutes /
        in 2 hours / at 9 / 8:30pm / next monday / this friday /
        yesterday 3pm / 3 days ago（过去模式给 history 用）。

    ⚠️ （history 那个工具要查"更早"）：加了**过去模式** `past=True` ——
       认「3天前 / 20分钟前 / 半小时前 / 昨天晚上 / 今天早上 / 前天」，
       算成**最近的那个过去时刻**（没说日期时往回退一天，不是往后）。
       ⛔ 将来那套（`past=False`，默认）**一个字、一个分支都没动**：
          两套是分开的两条路（过去那套在 `_parse_past` 里），别搅在一起。
    """
    if now is None:
        now = clock.now()          # ⚠️ 别用 datetime.now()：见 clock.py（Windows 上差 8 小时）
    raw = (s or "").strip()
    if not raw:
        raise ValueError("没说时间")
    # ⭐ （要的）：他说英文时也得听懂 —— **纯英文**才走那条新路
    #    （有英文字母、一个汉字都没有）；中文那条路一个字节都不经过这里。
    if _is_en(raw):
        return _parse_en(raw, now, past)
    t = re.sub(r"\s+", "", raw)
    t = t.replace("钟头", "小时").replace("个钟", "小时").replace("點", "点")
    if past:
        return _parse_past(t, now, raw)

    # ① 相对时间：20分钟后 / 半小时后 / 一小时以后 / 一会儿
    #
    # ⚠️ 那个前置否定 `(?<![\d点：])` 是必须的，两件事都靠它挡住
    #    「9点30分」里的「30分」长得像相对时间（连"0分"都会匹配上，读出「5 秒后」
    #    这种鬼结果），「点」后面的数字不是时长。这种 bug 平时不显形，直到有人
    #    在九点二十九分让她「九点三十分提醒我」。
    rel = re.search(r"(?<![\d点:：])" + _N + r"(秒|s|分钟|分|小时|h)(后|以后|之后|之内|内)?", t, re.I)
    if rel:
        n = _num(rel.group(1))
        if n is not None:
            u = rel.group(2).lower()
            mult = 1 if u in ("秒", "s") else 60 if u in ("分钟", "分", "min") else 3600
            at = now + timedelta(seconds=max(n * mult, MIN_AHEAD))
            return _out(at, now)
    if re.search(r"半小时|半个钟头?", t):
        return _out(now + timedelta(minutes=30), now)
    if re.search(r"一个半?小时", t):
        return _out(now + timedelta(minutes=90 if "半" in t else 60), now)
    if re.search(r"一会儿|待会|待会儿|稍后|马上|立刻", t):
        return _out(now + timedelta(minutes=10), now)

    # ② 哪一天
    day = None                                       # None = 还没定
    if re.search(r"大后天", t):
        day = now.date() + timedelta(days=3)
    elif "后天" in t:
        day = now.date() + timedelta(days=2)
    elif re.search(r"明天|明日|明早|明晚", t):
        day = now.date() + timedelta(days=1)
    elif re.search(r"今天|今晚|今早|今日", t):
        day = now.date()
    else:
        off = re.search(_N + r"(?:天|日)(?:后|以后|之后)?", t)
        if off and _num(off.group(1)) is not None:
            day = now.date() + timedelta(days=_num(off.group(1)))
        m = re.search(r"(下下|下|这|本)?(?:周|星期|礼拜)([一二三四五六日天1-7])", t)
        if day is None and m:
            w = "一二三四五六日".find(m.group(2))
            if w < 0:
                w = int(m.group(2)) - 1
            ahead = (w - now.weekday()) % 7
            if ahead == 0:
                ahead = 7
            if m.group(1) == "下":
                ahead += 7 if ahead < 7 else 0
            day = now.date() + timedelta(days=ahead)
        elif re.search(r"(下下|下)?(个)?月", t):
            raise ValueError("只认到天，别超过一个月")

    # ③ 几点
    hh, mm = _clock_of(t)
    if hh is None:
        raise ValueError("没听出几点")
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError("这个点不存在")

    at = datetime.combine(day or now.date(), datetime.min.time()).replace(hour=hh, minute=mm)
    if day is None and at <= now:
        at += timedelta(days=1)          # 「九点半」在 22:00 说 = 明早九点半
    return _out(at, now)


# 「哪一天」「几点」这两段的解析对过去 / 将来两个方向是同一份 —— 抽出来
# 只给 `_parse_past` 复用；⛔ 将来那条路的行为一个字都没变（还是同一套正则）。
def _clock_of(t):
    """从这句话里听出 `(时, 分)`；一个钟点都没有就返回 `(None, None)`。"""
    m = re.search(_N + r"[点时:：]" + r"(" + _N + r"|半|一刻|三刻)?分?", t)
    hh = mm = None
    if m:
        hh = _num(m.group(1))
        tail = m.group(2)
        if tail == "半":
            mm = 30
        elif tail == "一刻":
            mm = 15
        elif tail == "三刻":
            mm = 45
        elif tail:
            mm = _num(tail)
        mm = 0 if mm is None else mm
    else:
        # 没写钟点，只说了「早上/晚上」这种 —— 给个合理的默认
        for k, h in (("凌晨", 5), ("早上", 8), ("早晨", 8), ("上午", 9),
                     ("中午", 12), ("下午", 15), ("傍晚", 18), ("晚上", 20),
                     ("夜里", 21), ("今晚", 20), ("明早", 8), ("明晚", 20)):
            if k in t:
                hh, mm = h, 0
                break
    if hh is None:
        return None, None

    # 上午/下午 修正
    if re.search(r"下午|傍晚|晚上|夜里|今晚|明晚|中午", t) and hh < 12:
        hh += 12
    if re.search(r"凌晨|早上|早晨|上午|今早|明早", t) and hh == 12:
        hh = 0
    if hh == 24:
        hh = 0
    return hh, mm


# ── 英文时间──────────────────
#
# ⛔ 中文那套（`parse_when` 的将来分支 + `_parse_past` + `_clock_of`）**一个分支都没动**：
#    只有"有英文字母、而且一个汉字都没有"的句子才走下面这条新路（`_is_en`）。
# 语义照中文那套对齐：
#   · 只认将来（`past=False`，默认）；过去模式给 history 用（`past=True`）；
#   · 没说日期 → 今天那个点，已经过了就顺延一天（过去模式反过来往回退一天）；
#   · 只说 morning/afternoon/… 没写钟点 → 同一套合理默认
#     （morning 8 / afternoon 15 / evening 18 / night 20 / noon 12 / midnight 0）；
#   · `this friday` = 本周那个周五（今天就是周五 → 今天；时间已过 → 顺延 7 天）；
#     `next monday` = 下一个周一（今天就是周一 → 7 天后；否则从今天起最近的那个）。
# ⚠️ 认不出时的报错**只复用中文那几句现成的** ValueError，一个字都不新加
#    （用户说过：报错那句的例子「先别动」）。

_EN_UNIT = {"s": 1, "sec": 1, "second": 1, "m": 60, "min": 60, "mins": 60,
            "minute": 60, "minutes": 60, "h": 3600, "hr": 3600, "hrs": 3600,
            "hour": 3600, "hours": 3600, "d": 86400, "day": 86400, "days": 86400}
_EN_DAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tues": 1, "tue": 1,
            "wednesday": 2, "weds": 2, "wed": 2, "thursday": 3, "thurs": 3,
            "thur": 3, "thu": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5,
            "sunday": 6, "sun": 6}
_EN_DAY_RE = "|".join(sorted(_EN_DAYS, key=len, reverse=True))


def _is_en(raw):
    """这句是纯英文吗（有英文字母、一个汉字都没有）。⛔ 中文说法一律不进这条路。"""
    s = raw or ""
    return bool(re.search(r"[A-Za-z]", s)) and not re.search(r"[\u4e00-\u9fff]", s)


def _en_clock(t):
    """英文里听 `(时, 分)`；一个钟点都没有就返回 `(None, None)`。

    认 8:30pm / 8pm / at 9 / at 9:30，以及只说了 morning / tonight 这种（给默认点）。
    """
    hh = mm = None
    ap = None
    m = re.search(r"\b(\d{1,2}):(\d{2})\s*(am|pm)?\b", t)
    if m:
        hh, mm, ap = int(m.group(1)), int(m.group(2)), m.group(3)
    else:
        m = re.search(r"\b(\d{1,2})\s*(am|pm)\b", t)
        if m:
            hh, mm, ap = int(m.group(1)), 0, m.group(2)
        else:
            m = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\b", t)
            if m:
                hh, mm = int(m.group(1)), int(m.group(2) or 0)
    if hh is not None:
        if ap == "pm":
            if hh < 12:
                hh += 12
        elif ap == "am":
            if hh == 12:
                hh = 0
        elif re.search(r"\bafternoon\b|\bevening\b|\bnight\b|\btonight\b", t):
            if hh < 12:
                hh += 12                # 「at 8 in the evening」这种没写 pm 的
        elif re.search(r"\bmorning\b", t) and hh == 12:
            hh = 0
        return hh, mm
    # 没写钟点，只说了 morning / tonight 这种 —— 跟中文那套一样的默认点
    # ⚠️ 顺序有讲究：midnight 要在 night 前、afternoon 要在 noon 前、tonight 要在 night 前。
    for k, h in (("midnight", 0), ("tonight", 20), ("afternoon", 15), ("evening", 18),
                 ("morning", 8), ("noon", 12), ("night", 20)):
        if k in t:
            return h, 0
    return None, None


def _parse_en(raw, now, past=False):
    """英文时间说法 → (epoch, 人话)。认不出就抛 ValueError（人话跟中文那套一样）。"""
    t = (raw or "").strip().lower()
    t = t.replace("a.m.", "am").replace("p.m.", "pm").replace("o'clock", "")
    t = re.sub(r"\s+", " ", t).strip()

    # ⓪ 过去模式只认"过去"：带了明天的词就直说（跟中文那条同一个句子）。
    if past and not re.search(r"\b(ago|before|earlier|last)\b", t) \
            and re.search(r"\b(tomorrow|next|in)\b", t):
        raise ValueError("只认过去的说法（比如 3天前 / 昨天晚上 / 今天早上）")

    def _back(sec):
        """过去就往前退（`past=True`）；将来模式退到过去 → 由 `_out` 说「已经过去了」。"""
        at = now - timedelta(seconds=sec)
        return _out(at, now, past=True) if past else _out(at, now)

    # ① 过去的相对时间：3 days ago / half an hour ago / an hour ago
    if re.search(r"\bhalf an hour ago\b|\bhalf hour ago\b", t):
        return _back(30 * 60)
    if re.search(r"\ban hour ago\b|\bone hour ago\b", t):
        return _back(60 * 60)
    ago = re.search(r"\b(\d{1,4})\s+([a-z]+)\s+ago\b", t)
    if ago and ago.group(2) in _EN_UNIT:
        return _back(int(ago.group(1)) * _EN_UNIT[ago.group(2)])

    # ② 将来的相对时间：in 20 minutes / in 2 hours / 20 minutes from now
    rel = (re.search(r"\bin\s+(\d{1,4})\s*([a-z]+)\b", t)
           or re.search(r"\b(\d{1,4})\s+([a-z]+)\s+(?:from now|later)\b", t))
    if rel and rel.group(2) in _EN_UNIT:
        sec = max(int(rel.group(1)) * _EN_UNIT[rel.group(2)], MIN_AHEAD)
        return _out(now + timedelta(seconds=sec), now)
    if re.search(r"\bhalf an hour\b|\bhalf hour\b", t):
        return _out(now + timedelta(seconds=max(30 * 60, MIN_AHEAD)), now)
    if re.search(r"\ban hour and a half\b|\bone and a half hours?\b", t):
        return _out(now + timedelta(seconds=max(90 * 60, MIN_AHEAD)), now)
    if re.search(r"\ban hour\b|\bone hour\b", t):
        return _out(now + timedelta(seconds=max(60 * 60, MIN_AHEAD)), now)
    # 光写 `20m` / `1h` / `2d`（中文那条老正则可以认 `1h`，这里别把它弄丢）
    bare = re.search(r"\b(\d{1,4})\s*(s|m|min|mins|h|hr|hrs|d)\b", t)
    if bare and bare.group(2) in _EN_UNIT:
        sec = max(int(bare.group(1)) * _EN_UNIT[bare.group(2)], MIN_AHEAD)
        return _out(now + timedelta(seconds=sec), now)

    # ③ 哪一天
    day = None
    wd_this = False                        # 「this friday / 只说 friday」= 本周那个
    if re.search(r"\bday after tomorrow\b", t):
        day = now.date() + timedelta(days=2)
    elif re.search(r"\btomorrow\b|\btmr\b|\btmrw\b", t):
        day = now.date() + timedelta(days=1)
    elif re.search(r"\byesterday\b|\blast night\b", t):
        day = now.date() - timedelta(days=1)
    elif re.search(r"\btoday\b|\btonight\b", t):
        day = now.date()
    else:
        m = re.search(r"\b(next|this|coming|upcoming)?\s*(%s)\b" % _EN_DAY_RE, t)
        if m:
            ahead = (_EN_DAYS[m.group(2)] - now.weekday()) % 7
            if m.group(1) == "next":
                if ahead == 0:
                    ahead = 7              # 今天就是那天 → 下一个（7 天后）
            else:
                wd_this = True             # this / coming / 只说星期几 → 今天就是那天就算今天
            day = now.date() + timedelta(days=ahead)

    # ④ 几点
    hh, mm = _en_clock(t)
    if hh is None:
        if past and day is not None:
            hh, mm = 0, 0                     # 只说了 yesterday：当成昨天零点（同中文）
        elif day is not None:
            # 只说了哪天（`next monday` / `this friday`）没给钟点 → 那天早上 9 点。
            # ⚠️ 中文那条路这种时候是抛「没听出几点」；英文这几句是要认的
            #    所以给一个明确的默认点（9 = 中文「上午」那个默认）。
            hh, mm = 9, 0
        else:
            raise ValueError("没听出几点")
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError("这个点不存在")

    at = datetime.combine(day or now.date(), datetime.min.time()).replace(hour=hh, minute=mm)
    if day is None:
        if past and at >= now:
            at -= timedelta(days=1)           # 过去模式：还没到就退回昨天
        elif not past and at <= now:
            at += timedelta(days=1)           # 将来模式：已经过了就顺延明天
    elif wd_this and not past and at <= now:
        at += timedelta(days=7)               # 「this friday」在今天、但那个点已经过了 → 下周五
    return _out(at, now, past=past)


_PAST_MULT = {"秒": 1, "s": 1, "分钟": 60, "分": 60, "min": 60,
              "小时": 3600, "h": 3600, "天": 86400, "日": 86400}


def _parse_past(t, now, raw=""):
    """**过去模式**：同一句时间说法，算成「最近的那个过去时刻」。

    history 那个工具要「after=3天前 / before=昨天晚上」这种口子，所以单独一条路：
      · 相对时间：「20分钟前 / 3天前 / 半小时前」（不带「前」也当过去，模式就是过去）；
      · 哪天：「昨天 / 前天 / 大前天 / 今天早上」；
      · 钟点没说日期 → 今天那个点，**已经过了才算今天，还没到就退回昨天**
        （跟将来模式正好反过来）。

    ⛔ 将来模式（`parse_when` 默认那条）一个分支都不走这里。
    """
    # ⓪ 过去模式只认"过去"：带了明天的词就直说，别把「2天后」悄悄算成两天前。
    if not re.search(r"(前|以前|之前)", t) and \
            re.search(r"(明天|明日|明早|明晚|后天|大后天|以后|之后|下次)", t):
        raise ValueError("只认过去的说法（比如 3天前 / 昨天晚上 / 今天早上）")

    # ① 相对时间：20分钟前 / 3天前 / 2小时前（不带方向词也按过去算）
    rel = re.search(r"(?<![\d点:：])" + _N + r"(秒|s|分钟|分|小时|h|天|日)(前|以前|之前)?", t, re.I)
    if rel:
        n = _num(rel.group(1))
        if n is not None:
            u = rel.group(2).lower()
            mult = _PAST_MULT.get(u, 60)
            return _out(now - timedelta(seconds=n * mult), now, past=True)
    if re.search(r"半小时|半个钟头?", t):
        return _out(now - timedelta(minutes=30), now, past=True)
    if re.search(r"一个半?小时", t):
        return _out(now - timedelta(minutes=90 if "半" in t else 60), now, past=True)

    # ② 哪一天
    day = None
    if "大前天" in t:
        day = now.date() - timedelta(days=3)
    elif "前天" in t:
        day = now.date() - timedelta(days=2)
    elif re.search(r"昨天|昨日|昨晚|昨早|昨儿", t):
        day = now.date() - timedelta(days=1)
    elif re.search(r"今天|今日|今晚|今早", t):
        day = now.date()

    # ③ 几点
    hh, mm = _clock_of(t)
    if hh is None:
        if day is None:
            raise ValueError("没听出几点")
        hh, mm = 0, 0                    # 只说了「昨天」：当成昨天零点
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        raise ValueError("这个点不存在")

    at = datetime.combine(day or now.date(), datetime.min.time()).replace(hour=hh, minute=mm)
    if day is None and at >= now:
        at -= timedelta(days=1)          # 「九点半」在 22:00 问 = 今早九点半（过去）
    return _out(at, now, past=True)


def _out(at, now, past=False):
    if past:
        delta = (now - at).total_seconds()
        if delta < 0:
            raise ValueError("这个时间还没到（要查更早的话，换个过去的说法）")
        if delta > MAX_AHEAD:
            raise ValueError("太远了（超过一年）")
        d = (now.date() - at.date()).days
        # ⚠️ 这个 `human` 只写日志（history 那边自己拼行），所以别为了好看去加新词。
        day = {0: "今天", 1: "昨天", 2: "前天"}.get(d) or "%d 天前" % d
        human = "%s %s %02d:%02d（星期%s）" % (
            at.strftime("%Y-%m-%d"), day, at.hour, at.minute, WEEK[at.weekday()])
        return clock.stamp(at), human
    delta = (at - now).total_seconds()
    if delta < MIN_AHEAD:
        raise ValueError("这个时间已经过去了")
    if delta > MAX_AHEAD:
        raise ValueError("太远了（超过一年）")
    d = (at.date() - now.date()).days
    day = {0: "今天", 1: "明天", 2: "后天"}.get(d, "%d 天后" % d if d > 0 else "")
    human = "%s %s %02d:%02d（%s，星期%s）" % (
        at.strftime("%Y-%m-%d"), day, at.hour, at.minute,
        ago(delta), WEEK[at.weekday()])
    return clock.stamp(at), human


def ago(sec):
    """「还有多久」的人话（工具结果里要用，所以是公开的）。"""
    if sec < 90:
        return "%d 秒后" % int(sec)
    if sec < 5400:
        return "%d 分钟后" % int(sec / 60)
    if sec < 48 * 3600:
        return "%.1f 小时后" % (sec / 3600)
    return "%d 天后" % int(sec / 86400)


def human_at(ts):
    return clock.at(ts).strftime("%Y-%m-%d %H:%M")


# ── 唤醒记录怎么给她看──────────────────────────────
#
# 返回里的键名 / 取值是定稿的：
#     编号 / 时刻 / 醒来做什么 / 还有 / 在哪说
#     在哪说的取值：当前会话 ｜ 私聊 某人
# ⛔ 别再叫「提醒什么 / 提醒谁」，那是旧工具的话。

def where_text(rec):
    """这条唤醒醒来时在哪儿说话。"""
    qq = str((rec or {}).get("where_qq") or "")
    if qq:
        return "私聊 %s" % ((rec or {}).get("where_name") or qq)
    return "当前会话"


def row(rec, now=None):
    """一条唤醒 → 给她看的那一行（键名见上面那三行）。"""
    now = time.time() if now is None else now
    return {"编号": rec.get("id"),
            "时刻": human_at(rec.get("at") or now),
            "醒来做什么": rec.get("what"),
            "还有": ago(float(rec.get("at") or now) - now),
            "在哪说": where_text(rec)}


def wake_note(rec):
    """到点那一刻进请求的那段话（定稿的，⛔ 一个字都不许改）。

    `<system-reminder>` 信封统一走 `guards.system_reminder`（A5：只有这一种形态），
    两个字面量就是用户批的那两句 —— 别在这里额外加称呼、加时间、加 @ 的说明。
    """
    return guards.system_reminder("你被唤醒功能唤醒起来执行任务：「%s」（%s）"
                                  % ((rec or {}).get("what") or "",
                                     where_text(rec)))


# ── 账本 ────────────────────────────────────────────────────────────

def _load():
    d = store.read_json(LEDGER) or {}
    if not isinstance(d, dict):
        d = {}
    items = [x for x in (d.get("items") or []) if isinstance(x, dict) and x.get("at")]
    return {"items": items, "nextId": int(d.get("nextId") or (len(items) + 1))}


def _save(d):
    store.write_json(LEDGER, d)


def add(key, group_id, user_id, who, what, at, by=None, where_qq=None, where_name="",
        depth=1, hist=None, digest=""):
    """记一条唤醒。返回这条记录（含 id 和给人看的时间）。

    ⚠️ （A6）：多了 `where_qq` / `where_name` —— 醒来时私聊谁。
       留空 = 醒来就在**当初那个会话**说话（`group_id` / `user_id` / `key` 都在记录里）。
    ⚠️ （A6 安全阀）：`depth` = 这条唤醒在**唤醒链**里是第几层（1 = 最初那条）
       第 4 层在 `toolkit.t_wake` 就被拒了，到不了这里。
    ⚠️ （A7′）：「当时」的现场，两条可选字段（⛔ 老记录没有它们，读的时候当空）
       · `hist`   = 设这个唤醒那一刻的对话（最多 6 段，原样「名字: 内容」）；
       · `digest` = 她那一轮调过的工具摘要（一句话，≤600 字）。
       ⛔ 现有字段名一个都不许改（老账本照旧读得出来）。
    """
    what = (what or "").strip()
    if not what:
        raise ValueError("没说醒来要干什么")
    try:
        depth = max(1, int(depth or 1))
    except Exception:
        depth = 1
    # 「当时」的现场（A7′）：只存非空的，⛔ 老记录没有这两个键照样读（见 _load）。
    if not isinstance(hist, (list, tuple)):
        hist = []
    hist = [str(x) for x in hist if str(x or "").strip()][:6]
    digest = str(digest or "").strip()[:600]
    with _LOCK:
        d = _load()
        rec = {"id": d["nextId"], "at": float(at), "what": what[:200],
               "key": list(key) if key else None,
               "group_id": group_id, "user_id": user_id,
               "who": who or str(user_id), "by": by, "depth": depth,
               "where_qq": str(where_qq or ""), "where_name": str(where_name or ""),
               "created": time.time()}
        if hist:
            rec["hist"] = hist
        if digest:
            rec["digest"] = digest
        d["items"].append(rec)
        d["nextId"] = rec["id"] + 1
        _save(d)
    base.log("记下唤醒 #%s：%s 醒来做「%s」（%s，第 %d 层）"
             % (rec["id"], human_at(rec["at"]), rec["what"], where_text(rec), depth))
    return rec


def pending():
    """还挂着的（到点没响的）。"""
    with _LOCK:
        return sorted([x for x in _load()["items"] if not x.get("done")], key=lambda x: x["at"])


def done_recent(within=24 * 3600):
    """**刚响过**的（保留一天，顺手清掉更老的）。

    为什么要留着：她答「刚那条提醒响了吗」得答得上来。响过就删的话，
    她一查账本什么都没有，只能瞎猜 —— 实测她答成「你之前也没让我设过」，
    这句就是假的，用户会以为她失忆。
    """
    now = time.time()
    with _LOCK:
        d = _load()
        keep = [x for x in d["items"] if not x.get("done") or now - x["done"] <= within]
        if len(keep) != len(d["items"]):
            d["items"] = keep
            _save(d)
        out = [x for x in keep if x.get("done") and now - x["done"] <= within]
    return sorted(out, key=lambda x: x["done"], reverse=True)


def cancel(which):
    """按编号或关键词取消。返回 (取消掉的记录列表, 没匹配上的原话)。"""
    w = str(which or "").strip()
    if not w:
        return [], w
    hit, rest = [], []
    with _LOCK:
        d = _load()
        for it in d["items"]:
            if str(it["id"]) == w or (len(w) >= 2 and (w in (it.get("what") or "")
                                                       or w in (it.get("who") or ""))):
                hit.append(it)
            else:
                rest.append(it)
        if hit:
            d["items"] = rest
            _save(d)
    for it in hit:
        base.log("取消提醒 #%s（%s「%s」）" % (it["id"], it["who"], it["what"]))
    return hit, w


def ensure_timer(on_due):
    """起一个看账本的线程（**第一次收到消息时**才起，import 期不做事）。

    import 期就起线程的话，自检（离线、不许有副作用）会被它牵连 —— 所以是懒起。
    """
    global _TIMER
    with _LOCK:
        if _TIMER is not None and _TIMER.is_alive():
            return _TIMER
        _STOP.clear()
        _TIMER = threading.Thread(target=_loop, args=(on_due,), name="reminders", daemon=True)
        _TIMER.start()
        base.log("提醒账本看着了（每 %d 秒看一次，现在有 %d 条）" % (TICK_SECONDS, len(pending())))
        return _TIMER


def stop():
    _STOP.set()


def _loop(on_due):
    while not _STOP.wait(TICK_SECONDS):
        try:
            _fire(on_due)
        except Exception:
            base.log_exc("提醒线程")


def _allow_wake(now=None):
    """A6 安全阀：**全局每小时最多叫醒几次**（默认 6，面板可调）。到顶了就不再叫醒
    （只记日志、不吭声）。"""
    now = time.time() if now is None else now
    per_hour = settings.get("wake.maxPerHour")
    with _LOCK:
        _FIRED[:] = [t for t in _FIRED if now - t < 3600]
        if len(_FIRED) >= per_hour:
            return False, len(_FIRED)
        _FIRED.append(now)
        return True, len(_FIRED)


def _fire(on_due):
    now = time.time()
    late_window = settings.get("wake.lateWindowMin")
    per_hour = settings.get("wake.maxPerHour")
    due = []
    with _LOCK:
        d = _load()
        for it in d["items"]:
            if it.get("done") or it["at"] > now:
                continue
            # ⚠️ 响过的**不删**，只打一个 done 戳（留一天，见 done_recent）：
            #    删了她就答不上「刚那条提醒响了吗」，只能瞎猜。
            it["done"] = now
            if now - it["at"] <= late_window * 60:
                due.append(dict(it))
            else:
                it["missed"] = True
                base.log("唤醒 #%s 早该在 %s 响，过太久了（%.0f 分钟），不补了"
                         % (it["id"], human_at(it["at"]), (now - it["at"]) / 60))
        _save(d)
    for it in due:
        # ⭐ A6 安全阀：全局每小时最多叫醒几次 —— 到顶了这条**不叫醒**
        #    （记录已经打了 done 戳，不会再重试），只记一行日志，一个字都不发。
        ok_wake, n = _allow_wake(now)
        if not ok_wake:
            base.log("这一小时已经叫醒 %d 次了（上限 %d），唤醒 #%s 这次不叫了（只记日志）"
                     % (n, per_hour, it.get("id")))
            continue
        # 她说话要花几秒到几十秒，别堵住账本线程
        threading.Thread(target=_wake, args=(on_due, it), daemon=True).start()


def _wake(on_due, rec):
    try:
        on_due(rec)
    except Exception:
        base.log_exc("提醒到点后叫她（#%s）" % rec.get("id"))
