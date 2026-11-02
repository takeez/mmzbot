#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**同一个人（同一个 QQ）有多台电脑 → 战报拼成一份**（用户 2026-10-05 拍板的规则）。

用户定的形状（他拍的是 1(a) + 2(a) + 3(a)）：

  · 参与合并的判据 = **只要"今天"有数据就算** —— ⛔ **不看心跳新旧**（时长是累计的，
    旧数据也是真实的）；
  · "今天" = 以**心跳最新那条**的 `日期` 为准，**只并 `日期` 相同的那几条**（不同天的旧数据不混进来）；
  · `专注` / `摸鱼` = **相加**；
  · `摸鱼来源` = **按来源名相加**，输出**按总时长降序**（⛔ 不许写电脑名）；
  · `现在` = 取心跳最新那条的值；
  · `数据时间`（走缓存时那个键）由调用方按最新那条算 —— **不在这一份里**。

⚠️ 缓存与电脑应答里 `专注`/`摸鱼`/`摸鱼来源` 都是**格式化字符串**
   （`"1 小时 12 分"` / `"20 分 26 秒"` / `"0"` / 空），所以必须先**解析成秒**、相加、
   再**按同一套风格格式化回去**。解析要能吃下：`X 小时 Y 分 Z 秒` / `X 小时 Y 分` /
   `Y 分 Z 秒` / `Y 分` / `Z 秒` / `0` / 空。

⛔ 这一份是**纯函数**：不 import 项目里的任何东西、不碰盘、不吃网络 —— 好离线打桩。

⛔ 键名/字段一个字都不改：还是那五个中文键（`日期` / `专注` / `摸鱼` / `摸鱼来源` / `现在`），
   缺的照旧**不出现**（电脑那边就是这个规矩）。
"""

import re

# 一项 `摸鱼来源` 的尾巴 = 时长：`[H 小时][M 分][S 秒]`（三档都可缺，整串必须被吃完）
_TAIL = re.compile(r"^(?P<name>.*?)\s*"
                   r"(?P<dur>(?:(?:\d+)\s*小时)?\s*(?:(?:\d+)\s*分)?\s*(?:(?:\d+)\s*秒)?)\s*$")

# 一整段时长：`1 小时 12 分` / `20 分 26 秒` / `18 分` / `45 秒` / `0 分`
_UNIT = re.compile(r"^\s*(?:(\d+)\s*小时)?\s*(?:(\d+)\s*分)?\s*(?:(\d+)\s*秒)?\s*$")

# 裸数字：电脑那边只有 `0` 这一种（`Dur()` 的 0 → "0"）
_BARE = re.compile(r"^\s*(\d+)\s*$")

# `摸鱼来源` 里几段之间的分隔符（电脑侧 `OneBot.cs` 写死的 `" / "`）
SEP = " / "

# 战况那几个键（顺序 = 电脑应答里那个顺序，合并后也照这个顺序拼）
FIELDS = ("日期", "专注", "摸鱼", "摸鱼来源", "现在")


# ── 时长：字符串 ⇄ 秒 ────────────────────────────────────────────────

def parse_secs(text):
    """`"1 小时 12 分"` → 4320（秒）；空 → `0`；**认不出来给 `None`**（调用方保留原值）。

    ⚠️ 认不出来和"0 秒"是两件事：前者要给 `None`（宁可这一项不合并，
       也不能把它当成 0 悄悄算错）。
    """
    s = str(text if text is not None else "").strip()
    if not s:
        return 0
    m = _BARE.match(s)
    if m:
        # 裸数字只有"0"是电脑的写法；别的（"18"）没有单位，认不出来
        n = int(m.group(1))
        return n if n == 0 else None
    m = _UNIT.match(s)
    if not m or not any(m.groups()):
        return None
    h, mi, sec = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mi * 60 + sec


def fmt_secs(sec):
    """秒 → 电脑那种人话，**与电脑侧 `Durations.Status` 逐字一致**（用户 2026-10-05 拍板）：

        0            → `"0"`
        < 60 秒       → `"45 秒"`
        不足 1 小时    → `"18 分"` / `"20 分 26 秒"`（秒为 0 时不写"0 秒"）
        ≥ 1 小时      → 余 0 分：`"2 小时"` / 否则 `"1 小时 32 分"`（**秒直接丢掉**）

    ⚠️ 电脑侧 `PCStatus.Core.Bot.Durations.Status`（`Bot/Durations.cs:24-38`，
       就是 `BotCommands.cs` 那个 `Dur()`）在 ≥1 小时那一档**只看分钟**：
       `mm == 0 → "{h} 小时"`、否则 `"{h} 小时 {mm} 分"` —— 秒**不写**。
       这里跟它逐字一样，所以手机合并出来的时长和电脑自己算的写法完全相同。
    """
    s = max(0, int(sec or 0))
    if s <= 0:
        return "0"
    if s < 60:
        return "%d 秒" % s
    m, s2 = divmod(s, 60)
    if m < 60:
        return "%d 分" % m if s2 == 0 else "%d 分 %d 秒" % (m, s2)
    h, m2 = divmod(m, 60)
    return "%d 小时" % h if m2 == 0 else "%d 小时 %d 分" % (h, m2)


# ── 摸鱼来源：`"<名字> <时长>"` 的几段 ────────────────────────────────

def parse_sources(text):
    """`"B 站 56 分 16 秒 / 小红书 2 分 17 秒"` → `[("B 站", 3376), ("小红书", 137)]`。

    空 / 缺 → `[]`；**有一段拆不开就给 `None`**（调用方保留主那条，不瞎拼）。
    ⚠️ 名字里**可以带空格**（`B 站` 就是），所以时长是从**尾巴**上剥下来的。
    """
    s = str(text if text is not None else "").strip()
    if not s:
        return []
    out = []
    for part in s.split(SEP):
        p = part.strip()
        if not p:
            return None
        m = _TAIL.match(p)
        if not m:
            return None
        name = m.group("name").strip()
        dur = m.group("dur").strip()
        sec = parse_secs(dur)
        if not name or not dur or sec is None:
            return None                      # 名字空 / 没时长 / 时长认不出来 → 不瞎拼
        out.append((name, sec))
    return out


def fmt_sources(items):
    """`[("B 站", 3376), …]` → `"B 站 56 分 16 秒 / …"`（**顺序照调用方给的**）。"""
    return SEP.join("%s %s" % (n, fmt_secs(v)) for n, v in items)


def sum_sources(texts):
    """好几台的 `摸鱼来源` **按来源名相加**，按**总时长降序**输出；拆不开给 `None`。

    并列（总时长一样）时保持**第一次出现的先后** —— 结果稳定，不会来回抖。
    ⛔ 绝不把电脑名写进去：合并出来的每一项就是 `"<来源名> <时长>"`。
    """
    total, order = {}, []
    for t in texts:
        got = parse_sources(t)
        if got is None:
            return None
        for name, sec in got:
            if name not in total:
                total[name] = 0
                order.append(name)
            total[name] += sec
    order.sort(key=lambda n: -total[n])          # 稳定排序：并列保持先后
    return fmt_sources([(n, total[n]) for n in order])


# ── 合并：几台 → 一份 ───────────────────────────────────────────────

def merge_data(parts):
    """把同一个人的几台数据并成一份：`parts[0]` = **主那条**（= 心跳最新那条），其余是其它台。

    ⛔ 形状一个字不改：还是那五个中文键，缺的照旧不出现；
       `现在` **只取主那条**的值；`专注`/`摸鱼` 相加；`摸鱼来源` 按来源名相加、总时长降序。
    ⚠️ **只有一台时原样返回**（`dict(head)`，逐字不变）—— 这条是"单台输出与从前一模一样"的地基。

    某一项**有人拆不开**（电脑换了写法）→ 那一项**保留主那条原值**，别的项照并
    （宁可少并一项，也不把它当成 0 算错）。
    """
    keep = [p for p in (parts or []) if isinstance(p, dict) and p]
    if not keep:
        return {}
    head = keep[0]
    if len(keep) == 1:
        return dict(head)

    out = {}
    if head.get("日期") not in (None, ""):
        out["日期"] = head["日期"]

    for k in ("专注", "摸鱼"):
        vals = [p.get(k) for p in keep if p.get(k) not in (None, "")]
        if not vals:
            continue
        secs = [parse_secs(v) for v in vals]
        if any(x is None for x in secs):
            # 有一台的这一项认不出来 → 这一项不合并，保留主那条（有就保留，没有就取第一台的原值）
            out[k] = head.get(k) if head.get(k) not in (None, "") else vals[0]
        else:
            out[k] = fmt_secs(sum(secs))

    src = [p.get("摸鱼来源") for p in keep if p.get("摸鱼来源") not in (None, "")]
    if src:
        got = sum_sources(src)
        if got is None:
            got = head.get("摸鱼来源") if head.get("摸鱼来源") not in (None, "") else src[0]
        out["摸鱼来源"] = got

    if head.get("现在") not in (None, ""):
        out["现在"] = head["现在"]           # ⚠️ 取心跳最新那条的值，不从别的台补
    return out
