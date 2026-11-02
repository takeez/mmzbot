#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""群名单：她**理哪些群**。

背景（为什么要有这个模块）：
  以前"她理哪些群"写死在 `config.json` 的 `bot.groups` —— 那是**仓库里的文件**，
  deploy 每次都会把它推上去、覆盖手机上的。朋友把机器人邀请到自己群里，
  用户想加一个群就得改 config.json 再推一遍，而且**根本不知道群号是多少**。

落盘文件 `groups.json`（**进 `deploy.py` 的 NEVER**，只活在手机上）：

```json
{"群": [{"id": 123456789, "名字": "油库里观察日记", "备注": "", "加入时间": "12:00"}]}
```

⚠️ **读的时候是「并集」**（`known()`），一条都不能少：
    `config.json` 的 `bot.groups`
  ∪ `users.json` 里每个用户登记的 `群`
  ∪ 本文件 `groups.json` 的 `群`
   前两项是**兜底**：升级/第一次部署时她原来那两个群绝不能丢，朋友登记的群也照旧理。
   面板上能增删的只有第三项（本文件）。

⚠️ **「最近见过的群」不是白名单**：她收到过**不在白名单里**的群消息时，
   这里只记一条 `{"id", "名字", "最后见到", "谁在说话", "邀请人"}` ——
   ⛔ **绝不记消息内容**（那是别人群里的聊天，她没资格留）。它的唯一用途是：
   面板上列出来，用户点一下"加入白名单"（他不可能去 QQ 里翻群号）。
   ⚠️ `邀请人`**只在"朋友把机器人拉进群"那条路上**写
   来源是 NapCat 的 request 事件（见 `agent.on_request`）—— 记的是**谁把她拉进去的**，
   和 `谁在说话` 不是一回事（一个是"谁拉的"，一个是"谁在群里说话"）。

⚠️ **任何输出里都不出现 token**：这个模块不碰 token，页面/日志也没有它。
"""

import os
import re
import threading
import time

from . import base, store

WHITELIST_FILE = "groups.json"     # 白名单（面板改的就是它；deploy 的 NEVER 里）
SEEN_FILE = "seen-groups.json"     # 「最近见过的群」（不含消息内容）

# 「最近见过的群」里同一条**最少隔多久才写一次盘** —— 别的群里刷屏时别一条消息写一次盘。
# （时间戳会因此最多滞后 60 秒，面板上显示的是"大致什么时候见的"，够用。）
TOUCH_SECONDS = 60

# 「最近见过的群」最多留多少条 / 最多记多久（先到先出）
SEEN_MAX = 80
SEEN_TTL_DAYS = 14

# 群号的形状（和 users.py 里 QQ 号一个口径）
_ID_RE = re.compile(r"^\d{4,12}$")

_lock = threading.RLock()
_cache = {"mtime": None, "data": None, "at": 0.0, "path": None}
CACHE_SECONDS = 1.0        # 面板改完最多 1 秒内全体生效（要的"立刻"）


# ── 小工具 ──────────────────────────────────────────────────────────

def _gid(v):
    """群号 → 字符串（不合法回空串）。**只认 4~12 位数字**。"""
    s = str(v if v is not None else "").strip()
    if not s:
        return ""
    # 容忍 "123456789.0" 这种从别处抄来的写法
    if s.endswith(".0"):
        s = s[:-2]
    return s if _ID_RE.match(s) else ""


def _now():
    return base.local_now().strftime("%Y-%m-%d %H:%M")


def _human_ago(ts):
    """`最后见到` 那个时间戳 → 人看的字（面板用）。"""
    try:
        ts = float(ts)
    except Exception:
        return ""
    if ts <= 0:
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
    return base.local_at(ts).strftime("%Y-%m-%d")


# ── 白名单：读（mtime 热重载）────────────────────────────────────────

def _mtime_of(name):
    """文件的 mtime（拿不到回 None）—— 热重载就靠它。"""
    try:
        return os.path.getmtime(store.path(name))
    except Exception:
        return None


def records(force=False):
    """`groups.json` 里那几条（`list`，坏文件当空的）。**按 mtime 热重载**。"""
    now = time.time()
    with _lock:
        m = _mtime_of(WHITELIST_FILE)
        if (not force and _cache["data"] is not None and _cache["mtime"] == m
                and (now - _cache["at"]) < CACHE_SECONDS):
            return _cache["data"]
        d = store.read_json(WHITELIST_FILE)
        out = []
        if isinstance(d, dict):
            rows = d.get("群")
            if isinstance(rows, list):
                for r in rows:
                    if not isinstance(r, dict):
                        continue
                    g = _gid(r.get("id"))
                    if not g:
                        continue
                    out.append({
                        "id": int(g),
                        "名字": str(r.get("名字") or "").strip(),
                        "备注": str(r.get("备注") or "").strip(),
                        "加入时间": str(r.get("加入时间") or "").strip(),
                    })
        _cache.update({"mtime": m, "data": out, "at": now})
        return out


def _invalidate():
    with _lock:
        _cache.update({"mtime": None, "data": None, "at": 0.0})


def _save(rows):
    top = {"群": rows}
    okw = store.write_json(WHITELIST_FILE, top)
    _invalidate()
    return okw


def local_ids():
    """**只** `groups.json` 里的（面板能增删的那一份）。"""
    return [str(r["id"]) for r in records()]


def config_ids():
    """`config.json` 的 `bot.groups`（仓库那份；只读的兜底）。"""
    from . import base
    out = []
    for g in (base.bot_cfg().get("groups") or []):
        s = _gid(g)
        if s and s not in out:
            out.append(s)
    return out


def user_ids():
    """`users.json` 里每个用户登记的 `群`（只读的兜底）。"""
    from . import users
    out = []
    try:
        for g in users.groups():
            s = _gid(g)
            if s and s not in out:
                out.append(s)
    except Exception:
        pass
    return out


def known():
    """**她理哪些群** —— 三份的并集（`list[str]`，顺序 = config → 用户 → 本文件）。

    ⚠️ **全项目只有这一个取数点**：`agent._in_scope` / 面板 / `toolkit.t_say`
       都走它，谁也别再自己去读 `config.json` 的 `bot.groups`（各读各的必然飘）。
    """
    out = []
    for s in config_ids() + user_ids() + local_ids():
        if s not in out:
            out.append(s)
    return out


def in_scope(group_id):
    """这个群现在理不理（**纯判断、无副作用**）。"""
    g = _gid(group_id)
    return bool(g) and g in known()


def is_local(group_id):
    """这条在 `groups.json` 里吗（= 面板上能移除的那种）。"""
    return _gid(group_id) in local_ids()


def source_of(group_id):
    """这条从哪来：`"local"` / `"config"` / `"user"` / `""`（不在名单里）。"""
    g = _gid(group_id)
    if not g:
        return ""
    if g in local_ids():
        return "local"
    if g in config_ids():
        return "config"
    if g in user_ids():
        return "user"
    return ""


# ── 白名单：增 / 删（立刻生效）──────────────────────────────────────

def add(group_id, name="", note=""):
    """加一个群。返回 `(ok, 说明)`。**写盘 + 清缓存 = 下一条消息就生效**。"""
    g = _gid(group_id)
    if not g:
        return False, "群号得是 4~12 位数字（QQ 群号都是纯数字）"
    n = int(g)
    rows = [dict(r) for r in records(force=True)]
    for r in rows:
        if int(r["id"]) == n:
            changed = False
            if name and not r.get("名字"):
                r["名字"] = str(name).strip()
                changed = True
            if note and not r.get("备注"):
                r["备注"] = str(note).strip()
                changed = True
            if changed and not _save(rows):
                return False, "写不进 %s（手机上磁盘满了？）" % WHITELIST_FILE
            return True, "群 %s 已经在名单里了（没重复加）" % g
    rows.append({"id": n, "名字": str(name or "").strip(),
                 "备注": str(note or "").strip(), "加入时间": _now()})
    if not _save(rows):
        return False, "写不进 %s（手机上磁盘满了？）" % WHITELIST_FILE
    left = ""
    if source_of(g) in ("config", "user"):
        left = "（它本来就在 config.json / 用户表里，所以之前也一直生效）"
    return True, "把群 %s 加进名单了 —— 她从那一条开始收得到这个群的消息%s" % (g, left)


def remove(group_id):
    """移掉一个群。返回 `(ok, 说明)`。**只停止处理，绝不退群**。

    ⚠️ 万一它还挂在 `config.json` 的 `bot.groups` / 某个用户的 `群` 上，
       那就**删不掉**（并集里还有它）—— 如实说明，别让用户以为已经移除了。
    """
    g = _gid(group_id)
    if not g:
        return False, "群号得是 4~12 位数字"
    n = int(g)
    rows = [dict(r) for r in records(force=True)]
    keep = [r for r in rows if int(r["id"]) != n]
    if len(keep) == len(rows):
        return False, "群 %s 不在 groups.json 里（%s）" % (
            g, "它来自 config.json 的 bot.groups，只能改那份文件"
                if g in config_ids() else
                "它来自用户表里某人登记的群" if g in user_ids() else "本来就不在名单里")
    if not _save(keep):
        return False, "写不进 %s" % WHITELIST_FILE
    if g in config_ids():
        return True, "从 groups.json 里移掉了，但 config.json 的 bot.groups 里还有它 —— **照旧生效**"
    if g in user_ids():
        return True, "从 groups.json 里移掉了，但用户表里有人登记了这个群 —— **照旧生效**"
    return True, "把群 %s 移出名单了 —— 她立刻就不再收这个群的消息（她**没有**退群）" % g


def set_note(group_id, note=""):
    """改备注（面板上那一个字段）。"""
    g = _gid(group_id)
    n = int(g) if g else 0
    rows = [dict(r) for r in records(force=True)]
    hit = None
    for r in rows:
        if int(r["id"]) == n:
            hit = r
    if hit is None:
        return False, "群 %s 不在 groups.json 里" % g
    hit["备注"] = str(note or "").strip()
    if not _save(rows):
        return False, "写不进 %s" % WHITELIST_FILE
    return True, "群 %s 的备注改好了" % g


def set_name(group_id, name=""):
    """把群名补进 `groups.json`（取到了名字就顺手存一次，省得下次再问 NapCat）。"""
    g = _gid(group_id)
    if not g:
        return False
    name = str(name or "").strip()
    if not name:
        return False
    rows = [dict(r) for r in records(force=True)]
    hit = None
    for r in rows:
        if int(r["id"]) == int(g):
            hit = r
    if hit is None or hit.get("名字") == name:
        return False
    hit["名字"] = name
    return _save(rows)


# ── 「最近见过的群」（⛔ 不含消息内容）───────────────────────────────

def seen_records():
    """见过的群那份（`dict[str, dict]`）。坏文件当空的。"""
    d = store.read_json(SEEN_FILE)
    out = {}
    if isinstance(d, dict):
        rows = d.get("群")
        if isinstance(rows, list):
            for r in rows:
                if not isinstance(r, dict):
                    continue
                g = _gid(r.get("id"))
                if not g:
                    continue
                out[g] = {
                    "id": int(g),
                    "名字": str(r.get("名字") or "").strip(),
                    "最后见到": float(r.get("最后见到") or 0),
                    "谁在说话": str(r.get("谁在说话") or "").strip(),
                    "邀请人": str(r.get("邀请人") or "").strip(),
                    "次数": int(r.get("次数") or 0),
                    "最先见到": float(r.get("最先见到") or 0),
                }
    return out


def _save_seen(d):
    rows = sorted(d.values(), key=lambda r: r.get("最后见到") or 0, reverse=True)
    rows = rows[:SEEN_MAX]
    return store.write_json(SEEN_FILE, {"群": rows})


def see(group_id, who="", name="", inviter=""):
    """她见到一个**不在白名单里**的群 —— 记一笔（**只记事实，不记消息内容**）。

    两种情况都走这里：
      · 她收到一条不在名单里的群消息（`agent.handle`）→ 只填 `who`；
      · 朋友把机器人拉进一个群（`agent.on_request` 的群邀请）→ 只填 `inviter`。
    ⛔ 两种情况都**不写白名单**（那是用户在面板上的动作）。

    ⚠️ **这里一个网络请求都不发**（`_cached_name`，不是 `name_of(lookup=True)`）：
       它跑在**收消息那条路上**，不能因为"想显示个群名"去等 NapCat。
       群名由面板按需补（`_fill_names` 顺手也会把名字回填到这里）。

    返回 `(记了吗, 说明)`。调用方（`agent.handle` / `agent.on_request`）拿到 `False`
    时什么都不用管 —— 这个函数**绝不抛异常**，也绝不因为"记不下来"影响那一轮的任何判断。
    """
    try:
        g = _gid(group_id)
        if not g:
            return False, "群号形状不对"
        if in_scope(g):
            return False, "已经在名单里"          # 名单里的群不用记（面板只列名单外的）
        d = seen_records()
        now = time.time()
        old = d.get(g)
        # 名字：传进来的优先，其次上次记住的，再其次**只翻缓存**（⛔ 不问 NapCat）
        nm = str(name or "").strip() or (old or {}).get("名字") or _cached_name(g)
        # 邀请人：**记下就不覆盖**（"谁拉的"是个历史事实，后面那条群消息不该把它抹掉）
        iv = str(inviter or "").strip() or (old or {}).get("邀请人") or ""
        if (old and (now - float(old.get("最后见到") or 0)) < TOUCH_SECONDS
                and old.get("名字") == nm and (old.get("邀请人") or "") == iv):
            # 刚记过 —— 别一条消息写一次盘（面板上那点时间差无所谓）
            return False, "刚记过（%.0f 秒内不重复写）" % TOUCH_SECONDS
        d[g] = {
            "id": int(g),
            "名字": nm,
            "最后见到": now,
            "谁在说话": str(who or "").strip(),
            "邀请人": iv,
            "次数": int((old or {}).get("次数") or 0) + 1,
            "最先见到": float((old or {}).get("最先见到") or now),
        }
        # 顺手清掉太老的
        cutoff = now - SEEN_TTL_DAYS * 86400
        d = {k: v for k, v in d.items() if (v.get("最后见到") or 0) >= cutoff}
        if not _save_seen(d):
            return False, "写不进 %s" % SEEN_FILE
        return True, "群 %s 记下了（不在名单里）" % g
    except Exception as e:
        try:
            from . import base
            base.log("见过的群：记不下来（不影响这一轮）：%r" % (e,))
        except Exception:
            pass
        return False, "出错"


def fill_seen_names(limit=8):
    """给「最近见过的群」**按需补群名**（面板调的；每组每进程最多问一次）。"""
    d = seen_records()
    changed = False
    n = 0
    for g, r in list(d.items()):
        if r.get("名字") or n >= limit:
            continue
        n += 1
        nm = name_of(g, lookup=True)
        if nm:
            r["名字"] = nm
            changed = True
    if changed:
        _save_seen(d)
    return seen_rows()


def seen_rows(only_outside=True):
    """面板要的「最近见过的群」（人看的形状）。`only_outside` = 只列**不在白名单里**的。

    ⚠️ `邀请人` 存的是**一个 QQ 号**，面板上再显示一串裸数字很难看 ——
       所以多给一个 `邀请人显示名`（备注 → 称呼 → 昵称 → QQ 号，走 `who.display_name`）。
       ⛔ 不现取昵称（这条路上一个网络请求都不发）。
    """
    from . import who                        # 懒 import：只有面板/控制面读这个函数
    out = []
    for g, r in seen_records().items():
        if only_outside and in_scope(g):
            continue
        iv = str(r.get("邀请人") or "")
        out.append({
            "id": int(r["id"]),
            "名字": r.get("名字") or "",
            "最后见到": _human_ago(r.get("最后见到")),
            "最后见到戳": r.get("最后见到") or 0,
            "谁在说话": r.get("谁在说话") or "",
            "邀请人": iv,
            "邀请人显示名": who.display_name(iv) if iv else "",
            "次数": int(r.get("次数") or 0),
        })
    out.sort(key=lambda x: x["最后见到戳"], reverse=True)
    for r in out:
        r.pop("最后见到戳", None)
    return out


def forget_seen(group_id):
    """把一条从「最近见过的群」里删掉（面板上那个「忽略」）。"""
    g = _gid(group_id)
    d = seen_records()
    if g not in d:
        return False, "没有群 %s 这条记录" % g
    d.pop(g, None)
    return (True, "忽略了群 %s（下次它再来消息又会冒出来）" % g) if _save_seen(d) \
        else (False, "写不进 %s" % SEEN_FILE)


# ── 群名（取不到就留空，绝不报错）───────────────────────────────────

def _lookup_name(group_id):
    """问 NapCat 要一次群名（`im.group_name` 自己有进程内 + 落盘缓存）。取不到回空串。"""
    try:
        from . import im
        return im.group_name(group_id) or ""
    except Exception:
        return ""


def _cached_name(group_id):
    """**只翻缓存**（`groups.json` → 见过的群 → `group-names.json` → 进程内），
    ⛔ 绝不发网络请求。面板列表先用它填名字，剩下空白的才按需去问一次。"""
    g = _gid(group_id)
    if not g:
        return ""
    for r in records():
        if str(r["id"]) == g and r.get("名字"):
            return r["名字"]
    s = seen_records().get(g)
    if s and s.get("名字"):
        return s["名字"]
    try:
        from . import im
        n = str(im._GROUP_NAMES.get(g) or "").strip()
        if n:
            return n
        disk = store.read_json("group-names.json") or {}
        if isinstance(disk, dict):
            # ⚠️ 别把空串当"查到了"：`im.group_name` 失败时会往这个文件里写一个空值，
            #    照原样返回就等于"永远填不上名字"（自检里踩到过）。
            n = str(disk.get(g) or "").strip()
            if n:
                return n
    except Exception:
        pass
    return ""


def name_of(group_id, lookup=False):
    """群名。**默认只查缓存**（`groups.json` / 见过的群 / `group-names.json`），
    `lookup=True` 时才问 NapCat 一次（面板按需补）。取不到回空串。"""
    n = _cached_name(group_id)
    if n or not lookup:
        return n
    n = _lookup_name(group_id)
    if n:
        # 取到了就顺手记进 groups.json / 见过的群 —— 下次不用再问（也省一次网络）
        set_name(group_id, n)
        _seen_remember_name(group_id, n)
    return n


def _seen_remember_name(group_id, name):
    g = _gid(group_id)
    d = seen_records()
    if g in d and not d[g].get("名字") and name:
        d[g]["名字"] = str(name)
        _save_seen(d)


def _fill_names(rows):
    """给面板那份**按需补名字**：缓存里有就用，没有的才问一次 NapCat（取不到留空）。

    ⚠️ 每个群在**每个进程**里最多问一次（`im.group_name` 的 `_GROUP_TRIED`），
       所以连续刷新面板不会反复打 NapCat。
    """
    for r in rows:
        if r.get("名字"):
            continue
        r["名字"] = name_of(r["id"], lookup=True) or ""
    return rows


def panel_rows():
    """面板「群管理」页要的那份（**不带任何凭据**）。

    每一行都带 `生效`（现在到底理不理这个群）和 `来源` —— 并集是三份拼的，
    用户得一眼看出"这条是面板加的，还是 config.json 里本来就有的"。
    ⚠️ 这里**只翻缓存**（`_cached_name`），**一个网络请求都不发** ——
       查群名是 `agent._group_api` 那一层**按需**做的（见 `_fill_names`）。
    """
    out = []
    rows = records()
    for r in rows:
        g = str(r["id"])
        out.append({
            "id": r["id"],
            "名字": _cached_name(g) or r.get("名字") or "",
            "备注": r.get("备注") or "",
            "加入时间": r.get("加入时间") or "",
            "来源": "local",
            "生效": in_scope(g),
            "能移除": True,
        })
    have = set(str(r["id"]) for r in rows)
    for g in config_ids():
        if g in have:
            continue
        out.append({"id": int(g), "名字": _cached_name(g), "备注": "", "加入时间": "",
                    "来源": "config", "生效": in_scope(g), "能移除": False})
        have.add(g)
    for g in user_ids():
        if g in have:
            continue
        out.append({"id": int(g), "名字": _cached_name(g), "备注": "", "加入时间": "",
                    "来源": "user", "生效": in_scope(g), "能移除": False})
        have.add(g)
    return out


def stats():
    """一行字（日志/状态用）—— **不带 token**。"""
    return "群名单 %d 个（config %d + 用户 %d + 面板 %d）" % (
        len(known()), len(config_ids()), len(user_ids()), len(local_ids()))
