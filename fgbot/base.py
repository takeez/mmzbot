#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基础设施：路径（代码目录 / 数据目录）、配置加载（+热重载）、日志、时区。

**这一层不是 agent** —— agent 要的东西（提示词、记忆、工具、人格…）全都由
新 agent 从零写。这里只保证四件很土的事：

  ① **代码在哪、数据在哪，分得清**（数据目录可配：环境变量 / 配置文件 / 平台默认）
  ② 配置读得进来（config.json 改了不用重启）
  ③ 日志写得出去（一台手机上的黑盒，出问题只能靠它）
  ④ **时区是对的** —— 容器默认 UTC，不修的话绝对时刻会差 8 小时（这个坑踩过）

═══ 时区（2026-10-31 重做：不依赖 tzdata）═══

以前是「`os.environ["TZ"] = "Asia/Shanghai"` + `time.tzset()`」，再用 `datetime.now()`。
两个毛病：

  · Windows 上没有 `time.tzset()`，设了 `TZ` 也没人理（而且 IANA 名字 Windows 不认）
    → `now` 静默变成另一个时区，只有**绝对时刻**（「九点半」）会错，相对时间全对，
      所以这个 bug 平时几乎发现不了；
  · 手机上容器里如果没有 tzdata（proot 的 Debian 精简镜像很可能没有），
    `Asia/Shanghai` 也解析不出来，`tzset()` 之后照样是 UTC。

现在改成**自己算**：本地墙上时间 = UTC 时间 + 本机 UTC 偏移。
偏移只从三处来，全都不用 tzdata：

  ① `MMZBOT_UTC_OFFSET`（显式偏移，形如 `+08:00` / `8` / `-300`，最后那个按分钟算）；
  ② `MMZBOT_TZ` / `FG_TZ`（老名字）里的**固定偏移时区**（中国 1991 年后没有夏令时，
     写死 +8 是安全的；表在 `_FIXED_TZ_HOURS`）；
  ③ 都没有 → 用平台自己的本地时区（`time.localtime()` + `time.timezone` / `time.altzone`，
     Windows 上这就是系统时区，本来就是对的）。

Unix 上顺手还是会设 `TZ` + `tzset()`（如果有的话）—— 那是给**别的库**看的，
我们自己的时间不再依赖它。`tz_info()` 会把"现在按哪条规则"说清楚，自检里会打印。

═══ 数据目录（2026-10-31 加）═══

优先级：`MMZBOT_DATA` > `local-config.json` 的 `dataDir` > 平台默认：

    Linux / macOS   ~/mmzbot
    Termux          $HOME/mmzbot（就是手机上的 ~/mmzbot）
    Windows         %LOCALAPPDATA%\\MMZBOT

所有**会变的东西**（config / memory / reminders / settings / plan-* / bot.log /
personality.md …）都从 `DATA_DIR` 派生；代码（`fgbot/`、`phone-bot-v2.py`）在
`CODE_DIR`。两者可以是同一个目录（老安装 / 就地部署就是这样）。

**零迁移**：没有显式配置、平台默认目录又不存在、而代码目录里已经有 `config.json`
→ 就地把代码目录当数据目录（老手机上 `/root/fg-bot-v2` 那套照旧跑，不用改任何东西）。
"""

import json
import os
import threading
import time
import traceback
from datetime import datetime, timedelta, timezone

# 应用名（Windows 数据目录、systemd 服务名、Docker 卷名都用它）
APP = "MMZBOT"

# ── 目录：代码 / 数据 ────────────────────────────────────────────────

CODE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR = CODE_DIR                  # 兼容老代码（以前只有一个目录）


def _is_termux():
    """是不是 Termux（安卓上的那个终端）。判断只看两样，都不需要联网。"""
    prefix = os.environ.get("PREFIX") or ""
    return "com.termux" in prefix or os.path.isdir("/data/data/com.termux/files/home")


def platform_data_dir():
    """这台机器上的**默认**数据目录（还没被配置改过时用这个）。"""
    home = os.path.expanduser("~")
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.path.join(home, "AppData", "Local")
        return os.path.join(base, APP)
    return os.path.join(home, "mmzbot")


def _read_json_quiet(path):
    """读一个 JSON 文件；读不出来回 None（**绝不抛**）。"""
    try:
        with open(path, encoding="utf-8") as f:
            obj = json.load(f)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def resolve_data_dir(code_dir=None, environ=None, bootstrap_cfg=None):
    """数据目录怎么定（**纯函数**，好自检）：返回 `(绝对路径, 来源说明)`。

    优先级：`MMZBOT_DATA` > `local-config.json` 的 `dataDir` > 平台默认。
    `bootstrap_cfg` 传了就当成"代码目录里那份 local-config.json"（自检用）。
    """
    code_dir = code_dir or CODE_DIR
    env = os.environ if environ is None else environ
    raw = str(env.get("MMZBOT_DATA") or "").strip()
    how = "环境变量 MMZBOT_DATA"
    if not raw:
        boot = bootstrap_cfg
        if boot is None:
            boot = _read_json_quiet(os.path.join(code_dir, "local-config.json")) or {}
        raw = str((boot or {}).get("dataDir") or "").strip()
        how = "local-config.json 的 dataDir"
        if raw:
            raw = os.path.expanduser(raw)
            if not os.path.isabs(raw):
                raw = os.path.join(code_dir, raw)
    if not raw:
        raw = platform_data_dir()
        how = "平台默认（%s）" % ("Windows %%LOCALAPPDATA%%" if os.name == "nt" else "~")
        # 零迁移：默认目录还不存在，而代码目录里已经有 config.json（老安装 / 开发机）
        # → 就地把代码目录当数据目录，一个字节都不用搬。
        if not os.path.isdir(raw) and os.path.isfile(os.path.join(code_dir, "config.json")):
            raw = code_dir
            how = "就地（代码目录里已经有 config.json）"
    return os.path.abspath(os.path.expanduser(str(raw))), how


DATA_DIR, DATA_DIR_HOW = resolve_data_dir()


def set_data_dir(path):
    """换数据目录（**给自检 / 特殊部署用**）。返回新的绝对路径。

    会把下面那些派生路径全部重算 —— 单测里设一次，全进程就都跟着走。
    """
    global DATA_DIR, DATA_DIR_HOW, CFG_PATH, LOCAL_CFG_PATH, LOG_PATH, RESTART_PATH
    DATA_DIR = os.path.abspath(os.path.expanduser(str(path)))
    DATA_DIR_HOW = "set_data_dir()"
    CFG_PATH = existing_or_data("config.json")
    LOCAL_CFG_PATH = data_path("local-config.json")
    LOG_PATH = data_path("bot.log")
    RESTART_PATH = data_path("restart.txt")
    return DATA_DIR


def data_path(name):
    """数据文件的绝对路径（**写**都写这儿）。"""
    return os.path.join(DATA_DIR, name)


def code_path(name):
    """代码目录里的同名文件（只读兜底）。"""
    return os.path.join(CODE_DIR, name)


def existing_or_data(name):
    """先数据目录、再代码目录 —— 哪个有就用哪个；都没有就返回数据目录里的位置。

    ⚠️ 为什么要有兜底：没"部署"过、直接在仓库里跑的时候，`config.json` /
       `personality.md` 还在代码目录里。硬要它们先搬进数据目录，本地就没法跑了。
    """
    p = data_path(name)
    if os.path.isfile(p):
        return p
    q = code_path(name)
    if os.path.isfile(q):
        return q
    return p


# ── 时区：自己算，不依赖 tzdata ──────────────────────────────────────
#
# 没有夏令时、或者 1991 年之后没有夏令时的时区才能进这张表（写死偏移是安全的）。
_FIXED_TZ_HOURS = {
    "asia/shanghai": 8, "asia/chongqing": 8, "asia/harbin": 8, "asia/beijing": 8,
    "asia/hong_kong": 8, "asia/macau": 8, "asia/taipei": 8,
    "asia/singapore": 8, "asia/urumqi": 6,
    "asia/tokyo": 9, "asia/seoul": 9,
    "utc": 0, "etc/utc": 0, "gmt": 0, "etc/gmt": 0, "z": 0,
    "prc": 8, "hkt": 8, "jst": 9,
}


def _parse_offset(raw):
    """把 `+08:00` / `8` / `8.0` / `-300` 解析成秒。解析不了回 None。

    规则：带冒号按 `±HH:MM`；不带冒号且绝对值 ≤ 14 当**小时**；否则当**分钟**。
    """
    s = str(raw or "").strip()
    if not s:
        return None
    try:
        if ":" in s:
            sign = -1 if s.startswith("-") else 1
            hh, mm = s.lstrip("+-").split(":", 1)
            return int(sign * (int(hh) * 3600 + int(mm) * 60))
        v = float(s)
    except Exception:
        return None
    if abs(v) <= 14:
        return int(round(v * 3600))
    return int(round(v * 60))


def _tz_name():
    """配置里的时区名（`MMZBOT_TZ` 优先，兼容老的 `FG_TZ`，最后 `TZ`）。"""
    for k in ("MMZBOT_TZ", "FG_TZ", "TZ"):
        v = str(os.environ.get(k) or "").strip()
        if v:
            return v
    return "Asia/Shanghai"


# 是不是**人显式设过**（没设 = 用默认 Asia/Shanghai）—— Windows 上要靠它区分：
#   · 没设：Windows 的系统时区才是权威（别把一台欧洲的机器硬掰成 +8）；
#   · 显式设了固定偏移的时区（Asia/Tokyo 这种）：按它算。
TZ_EXPLICIT = bool(str(os.environ.get("MMZBOT_TZ") or os.environ.get("FG_TZ")
                       or os.environ.get("TZ") or "").strip())
TZ_NAME = _tz_name()
# 显式偏移（人定的，绝对值最大 14 小时；写错了就当没写）
OFFSET_OVERRIDE = _parse_offset(os.environ.get("MMZBOT_UTC_OFFSET"))
if OFFSET_OVERRIDE is not None and abs(OFFSET_OVERRIDE) > 14 * 3600:
    OFFSET_OVERRIDE = None

# 固定偏移表里能不能查到这个时区（查得到就不用 tzdata，也不用问操作系统）
_TZ_FIXED = _FIXED_TZ_HOURS.get(TZ_NAME.strip().lower())

# Unix 上顺手把 TZ 设给 C 库（别的库 / 子进程看的是它）。Windows 没有 tzset，
# 设了也没人理，而且 IANA 名字 Windows 不认 —— 索性不设，别留下"以为设了"的假象。
TZ_APPLIED = False
if os.name != "nt":
    os.environ["TZ"] = TZ_NAME
    if hasattr(time, "tzset"):
        try:
            time.tzset()
            TZ_APPLIED = True
        except Exception:
            TZ_APPLIED = False

# 我们自己的偏移（秒）。None = 完全信平台本地时区（time.localtime）。
#
#   · 显式 MMZBOT_UTC_OFFSET 永远最大；
#   · Unix：固定偏移表里有它就用（容器里常常没有 tzdata，问 glibc 不如自己算）；
#   · Windows：只有**显式设过** MMZBOT_TZ/FG_TZ 才用固定偏移表，
#     否则老实读系统时区（Windows 控制面板里那个才是用户想要的）。
_OFFSET = OFFSET_OVERRIDE
if _OFFSET is None and _TZ_FIXED is not None and (os.name != "nt" or TZ_EXPLICIT):
    _OFFSET = int(_TZ_FIXED * 3600)


def tz_offset():
    """现在用的 UTC 偏移（秒）。`None` = 用平台本地时区（含夏令时）。"""
    return _OFFSET


def tz_info():
    """一句话说清"现在按哪条规则算时间"（自检会打印，部署排错也看它）。"""
    if OFFSET_OVERRIDE is not None:
        return "MMZBOT_UTC_OFFSET=%s（固定 UTC%+g）" % (
            os.environ.get("MMZBOT_UTC_OFFSET"), OFFSET_OVERRIDE / 3600.0)
    if _OFFSET is not None:
        return "%s（固定偏移 UTC%+g，不用 tzdata）" % (TZ_NAME, _OFFSET / 3600.0)
    if os.name == "nt":
        return "系统时区（Windows 没有 tzset；%s 这种 IANA 名不认，用系统时区）" % TZ_NAME
    return "系统时区（%s 不在固定偏移表里，按平台本地时区算）" % TZ_NAME


def _os_offset(ts):
    """平台本地相对 UTC 的偏移（秒）：`time.timezone` / `time.altzone`。

    ⚠️ 这是"不依赖 tzdata"的那条路：C 库自己知道夏令时（`tm_isdst`），
       我们只拿它算出来的偏移，不去解析任何时区文件。
    """
    try:
        lt = time.localtime(ts)
        if time.daylight and lt.tm_isdst > 0:
            return -int(time.altzone)
        return -int(time.timezone)
    except Exception:
        return 0


def utc_offset(ts=None):
    """`ts` 这一刻的本地 UTC 偏移（秒）。固定偏移模式下就是那个常数。"""
    if _OFFSET is not None:
        return _OFFSET
    return _os_offset(time.time() if ts is None else float(ts))


def _from_ts(ts):
    """epoch → 本地墙上时间（naive datetime）。**全程不碰 tzdata。**

    做法就一句：UTC 墙上时间 + 本机 UTC 偏移。偏移只来自
    `time.timezone` / `time.altzone`（见 `_os_offset`）或固定偏移表 ——
    没有任何 `zoneinfo` / `ZoneInfo` / tzdata 解析。
    """
    ts = float(ts)
    utc = datetime.fromtimestamp(ts, timezone.utc)
    off = _OFFSET if _OFFSET is not None else _os_offset(ts)
    return (utc + timedelta(seconds=off)).replace(tzinfo=None)


def local_now():
    """现在的本地墙上时间（naive）。**别再用 `datetime.now()`** —— Windows 上那个不可信。"""
    return _from_ts(time.time())


def local_at(ts):
    """epoch → 本地墙上时间（naive）。"""
    return _from_ts(ts)


def local_stamp(dt):
    """本地墙上时间（naive）→ epoch。`local_at()` 的逆运算。

    ⚠️ **必须**用它，别直接 `dt.timestamp()`：naive datetime 会被解释成"系统本地时间"，
       在容器（UTC）里那就差了 8 小时 —— 这正是「提醒我九点半」到 17:30 才响的原因。
    """
    if not isinstance(dt, datetime):
        return float(dt)
    utc_ts = dt.replace(tzinfo=timezone.utc).timestamp()
    if _OFFSET is not None:
        # 当成"UTC 墙上时间"再减偏移：完全不用系统时区
        return utc_ts - _OFFSET
    # 平台本地时区：偏移可能随夏令时变，按算出来的 epoch 复核一次
    off = _os_offset(utc_ts)
    ts = utc_ts - off
    off2 = _os_offset(ts)
    return utc_ts - off2 if off2 != off else ts


def tz_selfcheck():
    """时区自检：**拿 `time.localtime()` 和内部算出来的比**。

    返回 `(ok, 说明, 明细)`。`ok=False` 只有一种情况：内部偏移和平台本地偏移不一致，
    而且我们还**没有**显式指定偏移（那就是有人的机器时区配错了，或者代码算错了）。
    显式指定过偏移（`MMZBOT_UTC_OFFSET` / 固定时区表）时，两边本来就允许不同，
    这时只验"内部自洽"：`local_now()` 和 `local_at(time.time())` 必须一模一样。
    """
    now_ts = time.time()
    mine = _from_ts(now_ts).replace(microsecond=0)     # 按秒比（time.localtime 没有微秒）
    lt = time.localtime(now_ts)
    plat = datetime(*lt[:6])
    plat_off = (-int(time.altzone) if (time.daylight and lt.tm_isdst > 0)
                else -int(time.timezone))
    my_off = utc_offset(now_ts)
    skew = (mine - plat).total_seconds()
    detail = ("内部 UTC%+g ｜ time.localtime() UTC%+g ｜ 差 %.0f 秒 ｜ %s"
              % (my_off / 3600.0, plat_off / 3600.0, skew, tz_info()))
    if abs(skew) <= 2:
        return True, "`now` 和 `time.localtime()` 一致（同一时刻、同一个墙上时间）", detail
    if _OFFSET is not None:
        # 显式偏移：平台时区本来就可以和它不一样，只要求自洽
        self_ok = abs((_from_ts(now_ts) - mine).total_seconds()) < 0.001
        return self_ok, "显式偏移和平台时区不同（允许），内部换算自洽", detail
    return False, "`now` 和 `time.localtime()` **对不上**（差 %.0f 秒）" % skew, detail


DEFAULT_SELF_ID = 10000

_cfg = {}
_mtimes = {}
_lock = threading.RLock()
_fallback_logged = False        # `napcatToken` 缺失回退那行提醒，只写一次

# ── 派生路径（全部从 DATA_DIR 来）────────────────────────────────────
#
#   config.json        出厂模板 / 部署事实（**读**时先找数据目录，再找代码目录）
#   local-config.json  用户覆盖（面板 / --set 写这里，deploy 永不覆盖）
#   bot.log            日志
#   restart.txt        请求重启（看门狗认它）
CFG_PATH = existing_or_data("config.json")
LOCAL_CFG_PATH = data_path("local-config.json")
LOG_PATH = data_path("bot.log")
RESTART_PATH = data_path("restart.txt")


def state_path(name):
    """她自己的状态文件放哪（提醒账本、称呼表…）。

    这些文件**不该被 deploy 覆盖** —— 它们是「这台机器上的状态」，不是代码。
    deploy.py 里有一份 NEVER 名单，加新状态文件时记得同步。
    """
    return data_path(name)


# ── 日志 ────────────────────────────────────────────────────────────

def log(msg):
    """一行一条，时间戳在前。

    ⚠️ 时间戳走 `local_now()`（不是 `datetime.now()`）：Windows 上 `datetime.now()`
       跟 `TZ` 无关，见文件开头那个时区坑。日志时间错了，排错时会把人带沟里。
    ⚠️ **别拿"手机日志的时间戳"和"电脑的时间戳"直接相减**：手机整机比电脑慢约 1.7 秒
       （2026-10-03 实测：RTT 修正后 5 次均值 −1.71 / −1.73 秒，7.5 分钟里只漂 26 毫秒）。
       ⚠️ 这里原来写的是"容器时钟比真机慢几十秒" —— **那句是错的、已实测推翻**：
       容器时钟和 Termux **是同一个内核时钟**（proot 不虚拟时钟，两边实测差不到 0.2 秒）。
       要量耗时，就在**同一台机器**上取两个时间戳。
    """
    line = "%s %s" % (local_now().strftime("%F %T"), msg)
    with _lock:
        try:
            d = os.path.dirname(LOG_PATH)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        try:
            print(line)
        except Exception:
            pass


def log_exc(where):
    log("%s 出错：\n%s" % (where, traceback.format_exc()))


# ── 配置 ────────────────────────────────────────────────────────────

def _deep_merge(under, over):
    """把 `over` 叠在 `under` 上（字典逐层合、别的类型直接替换）。

    ⚠️ 只做"浅一层替换"是不够的：`local-config.json` 里一般只写
       `{"bot": {"publicUrl": "…"}}`，浅替换会把 config.json 里
       `bot` 那一节的 token / groups / control 全抹掉 —— 她就聋了。
    """
    if not isinstance(under, dict) or not isinstance(over, dict):
        return over
    out = dict(under)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _read_json(path):
    """读一个 JSON 文件；读不出来回 None（**绝不抛**）。"""
    return _read_json_quiet(path)


def _cfg_path():
    """配置文件的**读**路径：数据目录优先，没有就退回代码目录里那份。"""
    return existing_or_data("config.json")


def _local_cfg_path():
    """本地覆盖层：**永远**在数据目录（面板 / --set 写这里；deploy 不覆盖）。"""
    return LOCAL_CFG_PATH


def load():
    """读配置。失败时**保留旧的**（配置写坏了不能让她整个趴窝）。

    `config.json`（出厂模板，deploy 会推）读完之后，再叠上
    `local-config.json`（本机那份，deploy 永不覆盖）。
    """
    global _cfg
    with _lock:
        p = _cfg_path()
        new = _read_json(p)
        if new is None:
            # ⚠ 2026-11-01：文件**不存在**是正常状态（还没 --init-config），
            #   以前这里也打「读不出来」→ 新手以为装坏了（部署验收时真被问到）。
            if os.path.exists(p):
                log("config.json 读不出来（或者不是 JSON 对象）—— 沿用上一份")
            return
        local = _read_json(_local_cfg_path()) or {}
        _cfg = _deep_merge(new, local)
        for q in (p, _local_cfg_path()):
            try:
                _mtimes[q] = os.path.getmtime(q)
            except Exception:
                _mtimes[q] = 0
        if local:
            log("配置：叠上了本地的 local-config.json（%d 个顶层键）" % len(local))
        _fill_selftest_defaults()


def _fill_selftest_defaults():
    """⚠ 仅自检：出厂模板的身份字段是空的，自检要一套假值才跑得起来。

    读 `MMZBOT_SELFTEST=1`（只有 phone-bot-v2.py --selftest 会设），把空着的那几个
    身份键补成假值；不写磁盘、不影响正式目录。
    """
    import os as _os
    if _os.environ.get("MMZBOT_SELFTEST") != "1":
        return
    b = _cfg.setdefault("bot", {})
    b.setdefault("selfId", "10000")
    b["selfId"] = b.get("selfId") or "10000"
    b["token"] = b.get("token") or "selftest-token"
    b["napcatToken"] = b.get("napcatToken") or b["token"]
    b["ownerQQ"] = b.get("ownerQQ") or "10001"
    if not b.get("groups"):
        b["groups"] = [123456789]
    _cfg["role"] = _cfg.get("role") or "owner"


def maybe_reload():
    """config.json / local-config.json 改了就跑一次热重载（只比 mtime）。"""
    changed = False
    for p in (_cfg_path(), _local_cfg_path()):
        try:
            m = os.path.getmtime(p)
        except Exception:
            m = 0
        if m != _mtimes.get(p, 0):
            changed = True
    if not changed:
        return False
    load()
    log("配置已热重载")
    return True


def save_local(patch):
    """把一段配置**合并进** `local-config.json`（原子写，先临时文件再 rename）。

    ⚠️ 这是"用户在面板上填一次"的落点（D3 + 用户 2026-10-03 定的落点 A）：
       写的是本机数据目录里那份，**deploy 不会覆盖它**。
    """
    with _lock:
        cur = _read_json(LOCAL_CFG_PATH) or {}
        merged = _deep_merge(cur, patch or {})
        tmp = LOCAL_CFG_PATH + ".tmp"
        try:
            d = os.path.dirname(LOCAL_CFG_PATH)
            if d and not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, LOCAL_CFG_PATH)
        except Exception as e:
            log("local-config.json 写不进去：%r" % e)
            try:
                os.remove(tmp)
            except Exception:
                pass
            return False
    load()
    return True


def cfg():
    return _cfg


def bot_cfg():
    return _cfg.get("bot") or {}


def napcat_token():
    """**NapCat 上报那条路**该用的 token（`bot.napcatToken`）。

    ⚠️ 契约 A3 拆成两把：`bot.napcatToken` 只给 NapCat 推上报（`POST /`）和老
       `X-Signature: sha1=`；朋友每人一把的 token 只存在 `users.json` 里。
    ⚠️ **兼容不许砍**：配置里没有 `bot.napcatToken` 时**回退用旧的 `bot.token`**
       （用户 2026-10-03 的原话：「⛔ 不许因为她配置没升级就让她变聋」），
       并且在**第一次回退时写一行日志提醒**。
    """
    global _fallback_logged
    tok = str((bot_cfg().get("napcatToken") or "")).strip()
    if tok:
        return tok
    old = str((bot_cfg().get("token") or "")).strip()
    if old and not _fallback_logged:
        _fallback_logged = True
        log("⚠️ config.json 里没有 bot.napcatToken，回退用旧的 bot.token"
            "（能跑，但建议把 NapCat 上报那把拆成 bot.napcatToken）")
    return old


def role():
    """配置里的**隐藏键** `role`（顶层）。只认一个值：`owner`。"""
    return str(_cfg.get("role") or "").strip().lower()


def owner_qq():
    """**主人的 QQ 号**（`bot.ownerQQ`）—— 这是"说话的人是不是主人"的**唯一判据**。

    ⚠️ 2026-11-01 用户定的：以前这个号藏在 users.json 那条 `主人: true` 记录里，
       现在提到配置里，**所有判定都走这个键**（用户表里那条记录只剩展示用途）。
       没填 = 认不出主人（需要主人的工具一律不给）。
    """
    return str(bot_cfg().get("ownerQQ") or "").strip()


def is_owner(qq):
    """这个 QQ 是不是主人（按 `bot.ownerQQ` 比，纯字符串比较）。"""
    want = owner_qq()
    return bool(want) and str(qq or "").strip() == want


def owner_mode():
    """主人模式开着吗（`role: owner`）。

    用户 2026-10-03 定的语义：**主人自己那台不需要邀请码** ——
    填上这颗键，主人那台电脑就能从**局域网**用现有那把 token 调 `/api`
    （认成主人身份），不用给他发邀请码、也不在面板上加任何入口。
    """
    return role() == "owner"


def public_url():
    """邀请码里那半地址（`公网IP:端口` 或 `DDNS名:端口`，不带 `http://`）。"""
    return str(bot_cfg().get("publicUrl") or "").strip()


def napcat_url():
    """NapCat 的 HTTP API 地址（例如 `http://127.0.0.1:3000`）。

    ⚠️ 两个键都认：**`napcat.baseUrl` 优先**（面板「初始化」页写的是它），
       其次老的 `napcat.url`（老配置照旧能跑，一个字节都不用改），
       都没有才用本机 3000（NapCat 的默认地址）。
    """
    n = _cfg.get("napcat") or {}
    return (str(n.get("baseUrl") or n.get("url") or "http://127.0.0.1:3000")
            .strip().rstrip("/") or "http://127.0.0.1:3000")


def lock():
    return _lock


def self_id():
    return int(bot_cfg().get("selfId") or DEFAULT_SELF_ID)
