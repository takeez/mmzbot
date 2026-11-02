#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时间：**一律走这里**拿"现在"，别直接 `datetime.now()`。

这一层现在只是 `base` 的薄壳 —— 真正的时区算法在 `base.py`（2026-10-31 重做）：

  · **不依赖 tzdata**：本地墙上时间 = UTC + 偏移；偏移从 `MMZBOT_UTC_OFFSET` /
    `MMZBOT_TZ` 固定偏移表 / 平台本地时区（`time.localtime` + `time.timezone`/
    `time.altzone`）三处来；
  · Android/Termux、Linux、Windows 三处 `now` 都是**本机的墙上时间**；
  · Windows 上没有 `tzset`，所以不再像以前那样"设了 `TZ` 就以为设上了"。

⛔ 别再在别的模块里写 `datetime.now()` —— 那会在 Windows / UTC 容器上静默差几小时，
   而且只有**绝对时刻**（「九点半」）会错，相对时间全对，特别难查（v1 真差过半天）。
"""

from . import base


def fallback_on():
    """现在是不是"我们自己算偏移"（而不是完全交给平台本地时区）。"""
    return base.tz_offset() is not None


def how():
    """一句话说清现在按哪条规则算时间。"""
    return base.tz_info()


def zone():
    """配置里的时区名（默认 `Asia/Shanghai`）。"""
    return base.TZ_NAME


def now():
    """现在的"墙上时间"（naive，但一定是本机的墙上时间）。"""
    return base.local_now()


def at(ts):
    """epoch → 本地墙上时间（naive）。"""
    return base.local_at(ts)


def stamp(dt):
    """本地墙上时间（naive）→ epoch。

    ⚠️ **必须**用它，别直接 `dt.timestamp()`：naive datetime 会被解释成
       "系统本地时间"，在容器（UTC）里那就差了 8 小时。
    """
    return base.local_stamp(dt)


def weekday_cn(dt=None):
    dt = dt or now()
    return "星期" + "一二三四五六日"[dt.weekday()]
