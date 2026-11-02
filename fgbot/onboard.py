#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""初始化：**新部署的人在面板上把该填的填完，一个文件都不用碰。**

这一层只做五件事（全部走同一个校验 / 同一个落点）：

  ① `snapshot()`  —— 面板「初始化」页要的那一份：现在的值 + 每块状态 + 「能不能跑」那张表；
  ② `save()`      —— 校验 + **深合并写进 `local-config.json`** + 热生效（不重启）；
  ③ `probe()`     —— 问 NapCat 的 `get_login_info`，告诉用户它登的是哪个 QQ；
  ④ `pull_groups()` —— 从 NapCat 拉群列表 / 最近会话（拉不到就让用户手填）；
  ⑤ `persona_save()` —— 写 `personality.md` 的正文 + 热生效。

⛔ 出厂模板 `config.json` **一个字都不改**（它是仓库里的部署事实，deploy 会覆盖它）。
   面板上填的一切都落在 `local-config.json`（`base.save_local()`，deploy 的 NEVER 名单里），
   读的时候由 `base._deep_merge()` 逐层叠在 `config.json` 上 —— 所以改一个键不会把
   同一节的兄弟键（token / groups / control）顶掉。

⛔ **token / key 永远不回明文**：`snapshot()` 里 token 只有 `****`（或者空串），
   真值只经 `token.show` 那条（只有主人能调、响应带 no-store）。
⛔ 这个模块**不拼给模型看的任何材料** —— 它只改部署配置和行为开关。

⚠️ 与 `settings.json` 的关系（2026-10-30 那层「运行参数」）：`agent.maxGroupReplyChars` /
   `agent.maxPrivateReplyChars` 也在 `settings.REGISTRY` 里，而 settings 的优先级高于
   config（面板改过的值 > config.json > 默认）。这里写完 local-config 后会**把这两个键的
   settings 覆盖删掉**，否则用户在这儿填的数会被旧覆盖值压住（"存了不生效"）。
   同理 `agent.triggerWords` 在 `runtime.json` 里有覆盖时也清掉（配置优先）。
"""

import ipaddress
import os
import re
import time
import urllib.parse

from . import base, groups, im, llm, memory, persona, settings, statuscache

# 「她的大脑」那两个键也在 settings 注册表里（见文件头）。
_SETTINGS_SHADOWED = ("agent.maxGroupReplyChars", "agent.maxPrivateReplyChars")

# 面板 / CLI 能写的**全部**键（点分路径，和 config.json 的路径一致）。
# ⚠️ 不在这个集合里的键**直接忽略**（不报错、也不写盘）——
#    免得面板哪天手滑多传一个键就把 local-config 写脏。
KEYS = (
    "bot.selfId", "bot.token", "bot.napcatToken", "bot.groups",
    "bot.autoAcceptGroupInvite",
    # ⚠ 2026-11-01：主人 QQ 提到配置里（唯一判据）；称呼写 memory
    "bot.ownerQQ", "bot.ownerCallName",
    "bot.control.allowPublic", "bot.control.allowIps",
    "port", "host",
    "napcat.baseUrl", "napcat.token",
    # ⚠️ 2026-10-31：文档验收时发现——无头配置改不了模型 ✗（只能靠 llm-key.txt）
    #    这三颗补上后，`--set llm.baseUrl=... llm.model=... llm.apiKey=...` 和面板等价 ✓
    "llm.baseUrl", "llm.model", "llm.apiKey",
    # ⚠ 2026-11-01：思考强度以前只能面板改，无头部署没入口
    "llm.effort",
    # 面板远程访问（2026-10-31）：公网要登录 / 反代后面信谁（见 docs/reverse-proxy.md）
    "panel.allowRemote", "panel.trustedProxies",
    "agent.name", "agent.wakeWords", "agent.triggerWords",
    "agent.chimeIn.chancePercent", "agent.pokeBack.enabled",
    "agent.maxGroupReplyChars", "agent.maxPrivateReplyChars",
    "pcStatus.enabled", "pcStatus.reportWindow", "pcStatus.dayCutoff",
    "pcStatus.computerName",
    # 扩展包下载白名单的**额外**域名（2026-10-31）：默认那几个在 capabilities.DEFAULT_HOSTS
    "capability.extraHosts",
    "capability.downloadProxy",
)

# 「最近一次收到 NapCat 上报」的时间（只活在内存里；重启就没了 —— 它只用来
# 回答「NapCat 连得上吗」，不是状态。面板上点一下「测一下」也能得到同一个答案）。
_LAST_EVENT = [0.0]
_LAST_PROBE = [0.0]

# 判"最近"的线：心跳 / 探测 10 分钟内算"连得上"（面板最多一分钟就会刷一次检查表）。
RECENT_SECONDS = 10 * 60

QQ_RE = re.compile(r"^\d{5,12}$")
GID_RE = re.compile(r"^\d{5,12}$")
HHMM_RE = re.compile(r"^(\d{1,2}):(\d{2})$")

# 工厂默认值：`bot.selfId` 还是它 = 还没填（QQ 号从 10001 起）。
FACTORY_SELF_ID = base.DEFAULT_SELF_ID

MAX_PERSONA_CHARS = 20000


# ── 小工具 ──────────────────────────────────────────────────────────

def _s(v):
    """去首尾空白 + 零宽字符（从聊天软件里粘过来的值最常见的就是这些）。"""
    return str(v if v is not None else "").replace("\u200b", "").replace("\u200c", "") \
        .replace("\u200d", "").replace("\ufeff", "").strip()


def _bool(v):
    """只认真的布尔（也认字符串 "true"/"false"）——安全开关别手滑。"""
    if isinstance(v, bool):
        return v
    s = _s(v).lower()
    if s in ("true", "1", "yes", "on", "开"):
        return True
    if s in ("false", "0", "no", "off", "关", ""):
        return False
    raise ValueError("要开或关（给的是「%s」）" % v)


def _int(v, what, lo, hi):
    s = _s(v)
    if not re.match(r"^-?\d+$", s):
        raise ValueError("%s要整数（给的是「%s」）" % (what, v))
    n = int(s)
    if n < lo or n > hi:
        raise ValueError("%s要 %d~%d（给的是 %d）" % (what, lo, hi, n))
    return n


def _host(v):
    """监听地址：IP 或主机名（`0.0.0.0` / `127.0.0.1` / 内网地址）。"""
    s = _s(v)
    if not s or len(s) > 64 or re.search(r"[\s/]", s):
        raise ValueError("监听地址要写一个 IP 或主机名（例如 127.0.0.1 / 0.0.0.0），"
                         "给的是「%s」" % v)
    return s


def _nets(v, allow_empty=False):
    """IP/CIDR 列表校验；可信代理必填，API 来源白名单允许清空。"""
    if isinstance(v, str):
        v = re.split(r"[,，\s]+", v)
    out = []
    for item in (v or []):
        s = _s(item)
        if not s:
            continue
        try:
            net = ipaddress.ip_network(s, strict=False)
        except ValueError:
            raise ValueError("IP / CIDR 格式不对（例如 192.168.1.0/24、127.0.0.1/32），"
                             "给的是「%s」" % s)
        if net.prefixlen == 0:
            raise ValueError("不能填写全网范围（0.0.0.0/0 或 ::/0）")
        if s not in out:
            out.append(s)
    if len(out) > 32:
        raise ValueError("IP / CIDR 最多 32 项")
    if not out and not allow_empty:
        raise ValueError("可信代理至少要有一个地址；不要用 0.0.0.0/0 或 ::/0")
    return out


def _list_values(v):
    """把配置里的字符串 / 数组统一成面板安全显示的字符串列表。"""
    if isinstance(v, str):
        return [x for x in re.split(r"[,，\s]+", v) if x]
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    return []


def _qq(v):
    s = _s(v)
    if not QQ_RE.match(s):
        raise ValueError("机器人 QQ 号须为 5–12 位数字。")
    return int(s)


HOST_RE = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)*"
                     r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")


def _hosts(v):
    """`capability.extraHosts`：域名列表（也认命令行里逗号 / 换行隔开的一串）。

    ⚠️ 只收**域名**（不带协议 / 端口 / 路径）；匹配时按"域名或子域"。
    """
    if isinstance(v, str):
        v = re.split(r"[,，\s]+", v)
    out = []
    for item in (v or []):
        s = _s(item).lower()
        if not s:
            continue
        if "://" in s:
            s = (urllib.parse.urlsplit(s).hostname or "")
        s = s.strip().strip(".").rstrip(".")
        if not s:
            continue
        if not HOST_RE.match(s):
            raise ValueError("额外允许域名只写域名（例如 ghproxy.com），给的是「%s」" % item)
        if s not in out:
            out.append(s)
    return out


def _extra_hosts_now():
    """配置里现在的额外域名（**快照**用：坏值当空，别让检查表跟着炸）。"""
    try:
        return _hosts((base.cfg().get("capability") or {}).get("extraHosts"))
    except ValueError:
        return []


def _gid(v):
    s = _s(v)
    if s.endswith(".0"):
        s = s[:-2]
    if not GID_RE.match(s):
        raise ValueError("群号要 5~12 位数字（给的是「%s」）" % v)
    return int(s)


def _url(v):
    """NapCat 的 API 地址：允许只写 `127.0.0.1:3000`，补成 http://。"""
    s = _s(v)
    if not s:
        raise ValueError("NapCat 的 API 地址不能空 —— 例如 http://127.0.0.1:3000")
    if "://" not in s:
        s = "http://" + s
    s = s.rstrip("/")
    try:
        u = urllib.parse.urlsplit(s)
        if u.scheme not in ("http", "https") or not u.hostname or not u.port:
            raise ValueError
        if u.path not in ("", "/") or u.query or u.fragment:
            raise ValueError
    except Exception:
        raise ValueError("NapCat 的 API 地址要写成 http://主机:端口（例如 http://127.0.0.1:3000），"
                         "只写到端口、不要带路径；给的是「%s」" % v)
    return s


def _hhmm(v):
    s = _s(v)
    m = HHMM_RE.match(s)
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        raise ValueError("日期切换点要 HH:mm（例如 04:00），给的是「%s」" % v)
    return "%02d:%02d" % (int(m.group(1)), int(m.group(2)))


def _words(v):
    """触发词：也接受「摸鱼、好累」这种一整串（CLI 方便）。"""
    if isinstance(v, str):
        v = re.split(r"[、,，/\s]+", v)
    out = []
    for w in (v or []):
        w = _s(w)
        if not w:
            continue
        if re.search(r"\s", w):
            raise ValueError("触发词里不能有空格（给的是「%s」）" % w)
        if len(w) > 12:
            raise ValueError("触发词最多 12 个字（给的是「%s」）" % w)
        if w not in out:
            out.append(w)
    if len(out) > 50:
        raise ValueError("触发词最多 50 个（现在 %d 个）" % len(out))
    return out


def _set_path(d, path, val):
    """`"bot.control.allowPublic"` → 嵌套 dict（浅层已经有的不覆盖兄弟键）。"""
    parts = path.split(".")
    cur = d
    for p in parts[:-1]:
        nxt = cur.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[p] = nxt
        cur = nxt
    cur[parts[-1]] = val


# ── 读：现在的值 / 每块状态 / 能不能跑 ───────────────────────────────

def probe_napcat(timeout=4):
    """真去问一次 NapCat（`get_login_info`），成了就把时间戳记上。

    ⚠️ 2026-10-31：`--check` 以前只看内存里的时间戳 → **独立进程永远是 ✗** ✗
       导致 CLI 拿不到退出码 0（面板里点「测一下」才行）。现在 CLI 先真探一次 ✓
    """
    import urllib.request as _u
    try:
        url = base.napcat_url().rstrip("/") + "/get_login_info"
        tok = str((base.cfg().get("napcat") or {}).get("token") or "").strip()
        hdr = {"Content-Type": "application/json"}
        if tok:
            hdr["Authorization"] = "Bearer " + tok
        req = _u.Request(url, data=b"{}", headers=hdr)
        with _u.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "replace")[:400]
        ok = '"retcode":0' in body.replace(" ", "")
        if ok:
            _LAST_PROBE[0] = time.time()
        return ok, ("" if ok else body)
    except Exception as e:
        return False, str(e)[:120]


def _cfg_bool(v):
    return v is True


def _token_state():
    """`(设置了吗, 打码后的样子)` —— ⛔ 绝不返回明文。"""
    t = _s(base.napcat_token())
    # 模板里的占位值不算"填了"（新部署还没换过）
    return (bool(t) and t != "change-me"), ("****" if t and t != "change-me" else "")


def _self_id():
    try:
        return int((base.bot_cfg().get("selfId") or 0))
    except Exception:
        return 0


# 占位值黑名单（出厂模板、教程里的假号码）。
# ⚠ 2026-11-01：VM 验收时用 1234567890 就能让 `--check` 全绿 ✗
#   那不是"能跑"，是"填了个假的"。现在这些一律当成没填。
_FAKE_QQ = {"10000", "1234567890", "123456789", "12345678", "10001"}
_FAKE_KEY_BITS = ("placeholder", "your-key", "yourkey", "sk-test", "changeme",
                  "change-me", "xxx", "todo", "fake", "你的key")


def _looks_fake_key(k):
    low = str(k or "").lower()
    if not low:
        return True
    return any(b in low for b in _FAKE_KEY_BITS)


def _qq_filled(n):
    if not n:
        return False
    if str(n) in _FAKE_QQ:
        return False
    return n >= 10001 and len(str(n)) <= 12


def _group_rows():
    """群列表：并集（config + 用户表 + groups.json），带备注 / 来源 / 能不能删。"""
    rows = []
    try:
        for gid in groups.known():
            src = groups.source_of(gid)
            note = ""
            for r in groups.records():
                if str(r["id"]) == str(gid):
                    note = r.get("备注") or ""
                    break
            notes = ((base.bot_cfg().get("groupNotes") or {}) if isinstance(
                base.bot_cfg().get("groupNotes"), dict) else {})
            note = notes.get(str(gid)) or note
            rows.append({"id": int(gid), "note": note, "source": src,
                         "removable": src != "user"})
    except Exception:
        pass
    return rows


def _brain():
    """她的大脑：现在用哪家、哪个模型、key 配没配（**都打码**）。"""
    try:
        conn = llm.connection()
        key = _s(conn.get("key"))
        # ⚠ 2026-11-01：`sk-PLACEHOLDER-not-a-real-key` 过去也算"已配置" ✗
        return {"ok": bool(_s(conn.get("model")) and key and not _looks_fake_key(key)),
                "provider": _s(conn.get("name")),
                "model": _s(conn.get("model")),
                "baseUrl": _s(conn.get("baseUrl")),
                "key": ("已配置" if key else "没有")}
    except Exception as e:
        return {"ok": False, "provider": "", "model": "", "baseUrl": "",
                "key": "没有", "error": repr(e)[:80]}


def _napcat_reachable():
    """NapCat 连得上吗：最近一次「测一下」成功，或者最近收到过它的上报。"""
    now = time.time()
    if _LAST_PROBE[0] and (now - _LAST_PROBE[0]) <= RECENT_SECONDS:
        return True, "刚测过"
    if _LAST_EVENT[0] and (now - _LAST_EVENT[0]) <= RECENT_SECONDS:
        secs = int(now - _LAST_EVENT[0])
        if secs >= 60:
            return True, "最近一次上报在 %d 分钟前" % max(1, secs // 60)
        return True, "最近一次上报在 %d 秒前" % secs
    return False, "检查 NapCat 地址与令牌，或点击「检测 NapCat」。"


def note_napcat_event():
    """收到一条**鉴权通过**的 NapCat 上报（`server.py` 调）—— 只记时间，不记内容。"""
    _LAST_EVENT[0] = time.time()


def _owner_title():
    """快照里的「对主人的称呼」（没有就空字串，面板自己决定怎么显示）。"""
    qq = base.owner_qq()
    if not qq:
        return ""
    try:
        return (memory.name_of(qq) or "").strip()
    except Exception:
        return ""


def snapshot():
    """面板 / CLI 要的全部现算值。**一个 token 明文都没有。**"""
    b = base.bot_cfg() or {}
    a = base.cfg().get("agent") or {}
    ps = base.cfg().get("pcStatus") or {}
    token_set, token_mask = _token_state()
    self_id = _self_id()
    qq_ok = _qq_filled(self_id)
    nap_url = _s(base.napcat_url())
    nap_cfg = (base.cfg().get("napcat") or {})
    nap_configured = bool(_s(nap_cfg.get("baseUrl")) or _s(nap_cfg.get("url")))
    brain = _brain()
    persona_text = persona.personality_text()
    reachable, reach_why = _napcat_reachable()

    # 群列表
    grows = _group_rows()
    # ⚠ 2026-11-01：出厂模板里的群号（123456789 之类）是**占位值**，
    #   以前一律算"填了" → 部署验收时出现**假绿**：一个真群都没有却 ✓
    #   （新手最容易漏这项，而它偏偏是绿的 ✗）
    _PLACEHOLDER_GIDS = {"123456789", "10000", "666000111", "666000333", "987654321"}
    grows = [g for g in grows if str(g.get("id") or "").strip() not in _PLACEHOLDER_GIDS]
    group_ok = bool(grows)

    # 每块状态（已完成 / 待完成）
    blocks = {
        "a": {"ok": qq_ok, "why": "" if qq_ok else "填写机器人 QQ 号"},
        "b": {"ok": token_set and (nap_configured or reachable),
              "why": "" if token_set else "设置共用令牌"},
        "c": {"ok": group_ok, "why": "" if group_ok else "至少添加一个目标群"},
        "d": {"ok": brain["ok"], "why": "" if brain["ok"] else "选择模型并填写密钥"},
        "e": {"ok": bool(_s(persona_text)), "why": "" if persona_text else "填写人设正文"},
        "f": {"ok": True, "why": ""},
        "g": {"ok": True, "why": ""},
    }

    checklist = [
        {"key": "qq", "label": "机器人 QQ", "ok": qq_ok,
         "hint": "" if qq_ok else "在机器人身份中填写"},
        {"key": "token", "label": "共用令牌", "ok": token_set,
         "hint": "" if token_set else "在消息通道中设置"},
        {"key": "groups", "label": "目标群", "ok": group_ok,
         "hint": "" if group_ok else "至少添加一个目标群"},
        {"key": "brain", "label": "模型与密钥", "ok": brain["ok"],
         "hint": "" if brain["ok"] else "在模型页选择提供商和模型"},
        {"key": "persona", "label": "人设正文", "ok": bool(_s(persona_text)),
         "hint": "" if persona_text else "在人设页填写正文"},
        {"key": "napcat", "label": "NapCat 连接", "ok": reachable,
         "hint": "" if reachable else reach_why},
    ]
    missing = sum(1 for c in checklist if not c["ok"])

    return {
        "ok": True,
        "values": {
            "bot.selfId": self_id,
            "bot.token": token_mask,
            "bot.tokenSet": token_set,
            "port": int(base.cfg().get("port") or 17383),
            "bot.autoAcceptGroupInvite": bool(b.get("autoAcceptGroupInvite")),
            "napcat.baseUrl": nap_url,
            "bot.groups": grows,
            "bot.ownerQQ": base.owner_qq(),
            "bot.ownerCallName": _owner_title(),
            "agent.name": _s(a.get("name") or a.get("nickname")),
            "agent.wakeWords": "、".join(
                [str(x) for x in (a.get("wakeWords") or [])]),
            "agent.triggerWords": persona.trigger_words(),
            "agent.chimeIn.chancePercent": int(
                (a.get("chimeIn") or {}).get("chancePercent") or 0),
            "agent.pokeBack.enabled": bool((a.get("pokeBack") or {}).get("enabled")),
            "bot.control.allowPublic": _cfg_bool((b.get("control") or {}).get("allowPublic")),
            "agent.maxGroupReplyChars": settings.get("agent.maxGroupReplyChars"),
            "agent.maxPrivateReplyChars": settings.get("agent.maxPrivateReplyChars"),
            "pcStatus.enabled": ps.get("enabled") is True,
            "pcStatus.reportWindow": _s(ps.get("reportWindow")),
            "pcStatus.dayCutoff": _s(ps.get("dayCutoff")) or "04:00",
            "pcStatus.computerName": _s(ps.get("computerName")),
            "capability.extraHosts": _extra_hosts_now(),
            "capability.downloadProxy": _s((base.cfg().get("capability") or {}).get("downloadProxy")),
        },
        "blocks": blocks,
        "checklist": checklist,
        "summary": {
            "ok": missing == 0,
            "text": "可以跑了" if missing == 0 else "还差 %d 项" % missing,
            "missing": missing,
        },
        "brain": brain,
        "persona": {"text": persona_text, "file": os.path.basename(
            persona.profile_path()), "chars": len(persona_text)},
        "napcat": {"url": nap_url, "reachable": reachable, "detail": reach_why},
        "server": {
            "host": _s(base.cfg().get("host")) or "0.0.0.0",
            "port": int(base.cfg().get("port") or 17383),
            "allowRemote": (base.cfg().get("panel") or {}).get("allowRemote") is True,
            "trustedProxies": _list_values((base.cfg().get("panel") or {}).get("trustedProxies")),
            "allowIps": _list_values((base.bot_cfg().get("control") or {}).get("allowIps")),
        },
    }


# ── 写：校验 + 深合并 + 热生效 ───────────────────────────────────────

def _group_plan(rows):
    """算出「这次要写进 local-config 的群号 / 备注」，**不碰盘**。

    返回 `(cfg_ids, notes, msgs, keep)`。⚠️ 用户表里登记的群**删不掉**（它在 users.json
    里），这里如实把它从待写列表里拿掉并说明 —— 不假装删成功。
    """
    notes = {}
    keep = []
    for r in rows or []:
        if isinstance(r, dict):
            gid = _gid(r.get("id"))
            note = _s(r.get("note"))
        else:
            gid = _gid(r)
            note = ""
        if gid not in keep:
            keep.append(gid)
        if note:
            notes[str(gid)] = note
    user_ids = set(groups.user_ids())
    msgs = []
    for gid in list(keep):
        if str(gid) in user_ids:
            keep.remove(gid)
            msgs.append("群 %s 来自用户表，这里删不掉" % gid)
    # 用户表里本来就有、但这次没传上来的：并集照旧生效，如实说一句
    for gid in user_ids:
        if gid not in keep:
            msgs.append("群 %s 来自用户表，照旧生效" % gid)
    return [int(g) for g in keep], notes, "；".join(msgs), keep


def _sync_group_store(keep, notes):
    """把这次的结果同步进 `groups.json`（旧的「群」那一页也看得见这些备注）。

    ⚠️ 在 `local-config.json` **写成功之后**才调 —— 主落点失败时一个字节都不动。
    失败只记一行日志（`groups.json` 是附属，不该把这次保存整个弄红）。
    """
    try:
        for gid in groups.local_ids():
            if str(gid) not in [str(x) for x in keep]:
                groups.remove(gid)
        for gid in keep:
            note = notes.get(str(gid), "")
            if groups.is_local(gid):
                groups.set_note(gid, note)
            elif note:
                groups.add(gid, note=note)
    except Exception as e:
        base.log("初始化：同步 groups.json 失败（不影响 local-config）：%r" % e)


def save(values):
    """校验 + 写 `local-config.json` + 热生效。返回 `(ok, message, snapshot)`。"""
    if not isinstance(values, dict) or not values:
        return False, "没有要保存的值", snapshot()

    plan = []                 # [(path, 规范化后的值)]
    errors = []
    skipped = 0
    for k, raw in values.items():
        key = str(k or "").strip()
        if key not in KEYS:
            skipped += 1
            continue
        try:
            if key == "bot.selfId":
                n = _qq(raw)
                if n == FACTORY_SELF_ID:
                    raise ValueError("请填写实际的机器人 QQ 号。")
                plan.append((key, n))
            elif key in ("bot.token", "bot.napcatToken"):
                tok = _s(raw)
                if not tok or set(tok) == {"*"}:
                    continue          # 打码值 / 空 = 没改，跳过（不报错）
                if len(tok) < 8:
                    raise ValueError("令牌至少 8 位；可使用随机生成。")
                if len(tok) > 200:
                    raise ValueError("令牌不能超过 200 位。")
                plan.append((key, tok))
            elif key == "napcat.token":
                tok = _s(raw)
                if not tok or set(tok) == {"*"}:
                    continue                      # 空 / 打码值 = 不改
                if len(tok) < 8:
                    raise ValueError("NapCat 令牌至少 8 位。")
                if len(tok) > 200:
                    raise ValueError("NapCat 令牌不能超过 200 位。")
                plan.append((key, tok))
            elif key == "llm.baseUrl":
                u = _s(raw).rstrip("/")
                if not (u.startswith("http://") or u.startswith("https://")):
                    raise ValueError("模型地址要写 http:// 或 https:// 开头")
                plan.append((key, u[:200]))
            elif key == "llm.model":
                m = _s(raw)
                if not m:
                    raise ValueError("模型名不能空着")
                plan.append((key, m[:100]))
            elif key == "llm.effort":
                v = _s(raw).lower()
                if v not in ("none", "low", "medium", "high", "off", "max"):
                    raise ValueError("思考强度只能是 none / low / medium / high")
                plan.append((key, v))
            elif key == "llm.apiKey":
                k = _s(raw)
                if not k or set(k) == {"*"}:
                    continue
                plan.append((key, k[:400]))
            elif key == "bot.control.allowIps":
                plan.append((key, _nets(raw, allow_empty=True)))
            elif key == "bot.groups":
                if not isinstance(raw, list):
                    raise ValueError("群列表要是一串群号")
                plan.append((key, raw))     # 真的校验在 _sync_groups
            elif key == "bot.autoAcceptGroupInvite" or key == "bot.control.allowPublic" \
                    or key == "agent.pokeBack.enabled" or key == "pcStatus.enabled":
                plan.append((key, _bool(raw)))
            elif key == "port":
                plan.append((key, _int(raw, "上报端口", 1, 65535)))
            elif key == "host":
                plan.append((key, _host(raw)))
            elif key == "panel.allowRemote":
                plan.append((key, _bool(raw)))
            elif key == "panel.trustedProxies":
                plan.append((key, _nets(raw)))
            elif key == "napcat.baseUrl":
                plan.append((key, _url(raw)))
            elif key == "bot.ownerQQ":
                v = _s(raw)
                if v and (not v.isdigit() or not 5 <= len(v) <= 12):
                    raise ValueError("\u4e3b\u4eba QQ \u8981\u662f\u4e00\u4e32\u6570\u5b57")
                if v in _FAKE_QQ:
                    raise ValueError("\u8fd9\u4e2a QQ \u770b\u7740\u50cf\u5360\u4f4d\u503c\uff0c\u6362\u4f60\u771f\u7684\u53f7")
                plan.append((key, v))
            elif key == "bot.ownerCallName":
                plan.append((key, _s(raw)))
            elif key == "agent.name":
                v = _s(raw)
                if not v:
                    raise ValueError("机器人名字不能为空。")
                if len(v) > 20:
                    raise ValueError("名字太长了（最多 20 个字）")
                plan.append((key, v))
            elif key == "agent.wakeWords":
                if isinstance(raw, (list, tuple)):
                    items = [str(x) for x in raw]
                else:
                    items = re.split(r"[、,，/|\s]+", _s(raw))
                words = []
                for item in items:
                    w = _s(item)
                    if not w:
                        continue
                    if re.search(r"\s", w):
                        raise ValueError("唤醒词里不能有空格")
                    if len(w) > 20:
                        raise ValueError("唤醒词最多 20 个字")
                    if w not in words:
                        words.append(w)
                if len(words) > 12:
                    raise ValueError("唤醒词最多 12 个")
                plan.append((key, words))
            elif key == "agent.triggerWords":
                plan.append((key, _words(raw)))
            elif key == "agent.chimeIn.chancePercent":
                plan.append((key, _int(raw, "随机接话概率", 0, 100)))
            elif key in ("agent.maxGroupReplyChars", "agent.maxPrivateReplyChars"):
                plan.append((key, _int(raw, "回复上限", 100, 10000)))
            elif key == "pcStatus.reportWindow":
                plan.append((key, _s(raw)[:60]))
            elif key == "pcStatus.dayCutoff":
                plan.append((key, _hhmm(raw)))
            elif key == "pcStatus.computerName":
                plan.append((key, _s(raw)[:32]))
            elif key == "capability.extraHosts":
                plan.append((key, _hosts(raw)))
            elif key == "capability.downloadProxy":
                _px = _s(raw)
                if _px and not (_px.startswith("http://") or _px.startswith("https://")):
                    raise ValueError("下载代理要写 http:// 或 https:// 开头")
                plan.append((key, _px[:200]))
        except ValueError as e:
            errors.append(str(e))
    if errors:
        return False, "没保存：" + "；".join(errors), snapshot()

    # 同一批里如果同时提交了 ownerQQ 和 ownerCallName，称呼要用这批里的新值
    _owner_in_plan = ""
    for _k, _v in plan:
        if _k == "bot.ownerQQ":
            _owner_in_plan = str(_v or "")

    patch = {}
    notes = []
    group_side = None
    try:
        for key, val in plan:
            if key == "bot.groups":
                cfg_ids, note_map, gmsg, keep = _group_plan(val)
                _set_path(patch, "bot.groups", cfg_ids)
                if note_map:
                    _set_path(patch, "bot.groupNotes", note_map)
                if gmsg:
                    notes.append(gmsg)
                group_side = (keep, note_map)
            elif key == "bot.token":
                # 「两边的 token」= NapCat 上报那把 + 面板登录那把，写同一个值。
                # ⚠️ 2026-10-31：还要写 `napcat.token` —— 她**出站**调 NapCat 的 HTTP
                #    用的正是这把；漏了它，NapCat 一设 token 她就调不动（文档验收发现的）。
                _set_path(patch, "bot.token", val)
                _set_path(patch, "bot.napcatToken", val)
                if not any(k == "napcat.token" for k, _v in plan):
                    _set_path(patch, "napcat.token", val)
            elif key == "llm.effort":
                ok_eff, msg_eff = llm.set_effort(val)
                if not ok_eff:
                    raise ValueError(msg_eff)
                notes.append("思考强度：" + msg_eff)
            elif key == "bot.ownerCallName":
                # 称呼存在 memory（她对这个人的叫法），不是 config 键
                _own_qq = _owner_in_plan or base.owner_qq()
                _v = _s(val)
                if not _own_qq:
                    raise ValueError("请先填写主人 QQ，再填写称呼。")
                if _v:
                    _ok, _why = memory.remember_name(_own_qq, _v)
                    if not _ok:
                        raise ValueError(_why)
                    notes.append("对主人的称呼：" + _v)
            elif key == "llm.apiKey":
                _set_path(patch, "llm.apiKey", val)
                # 有 keyFile 的话它会盖过 apiKey ✗ 顺手清掉，别让"填了不生效"
                _set_path(patch, "llm.keyFile", "")
            else:
                _set_path(patch, key, val)
    except ValueError as e:
        return False, "没保存：" + str(e), snapshot()

    if not patch:
        return False, "没有要改的值", snapshot()

    okw = base.save_local(patch)
    if not okw:
        return False, "写不进 local-config.json（磁盘满了？权限？）", snapshot()

    # 主落点写成功了，再同步 groups.json（「群」那一页也看得见这些备注）
    if group_side is not None:
        _sync_group_store(*group_side)

    # ⚠️ 让「真的立刻生效」落地：
    #   ① 这两个键在 settings 注册表里时，settings.json 的旧覆盖会压过 local-config；
    #   ② 触发词在 runtime.json 里有覆盖时同理。
    for key in _SETTINGS_SHADOWED:
        if key in [k for k, _v in plan]:
            try:
                settings.reset(key, who="初始化")
            except Exception:
                pass
    if "agent.triggerWords" in [k for k, _v in plan]:
        try:
            llm.runtime_del("triggerWords")
        except Exception:
            pass

    saved = len(plan)
    msg = "已保存（%d 项），下一条消息就按新值走" % saved
    if "port" in [k for k, _v in plan]:
        msg += "；端口要重启后才开始监听"
    if "host" in [k for k, _v in plan]:
        msg += "；监听地址要重启后才生效"
    if notes:
        msg += "；" + "；".join(notes)
    if skipped:
        msg += "；忽略了 %d 个不认识的键" % skipped
    base.log("初始化：保存了 %d 项到 local-config.json（热生效）" % saved)
    return True, msg, snapshot()


# ── NapCat：测一下 / 拉群 ────────────────────────────────────────────

def probe(timeout=6):
    """问 NapCat 的 `get_login_info`：它登的是哪个 QQ。

    返回 `{ok, message, qq, nickname, url}` —— `message` 是**原因 + 怎么做**。
    ⛔ 日志里只有失败原因，没有 token。
    """
    url = base.napcat_url()
    ok, why, data = im._napcat_raw("get_login_info", {}, timeout=timeout,
                                   retry=False, kind="query")
    if ok and isinstance(data, dict):
        qq = _s(data.get("user_id") or data.get("userId") or data.get("uin"))
        nick = _s(data.get("nickname") or data.get("nickName") or data.get("nick"))
        if qq:
            _LAST_PROBE[0] = time.time()
            _LAST_EVENT[0] = _LAST_PROBE[0]
            base.log("初始化：NapCat 测通了（登的 QQ 号只给面板显示，不入日志）")
            return {"ok": True, "qq": qq, "nickname": nick, "url": url,
                    "message": "它登的是 QQ %s%s" % (qq, ("（%s）" % nick) if nick else "")}
        return {"ok": False, "qq": "", "nickname": nick, "url": url,
                "message": "NapCat 连上了，但没回登录信息 —— 去 NapCat 里重新登录一次 QQ"}
    # 刚测过、而且失败 —— 那两条"最近连得上"的证据一起作废（检查表要跟手测结果一致）
    _LAST_PROBE[0] = 0.0
    _LAST_EVENT[0] = 0.0
    if why == "retcode":
        msg = "NapCat 拒绝请求，请检查令牌和版本。"
    else:
        msg = "无法连接到 %s，请检查服务、地址和端口。" % url
    return {"ok": False, "qq": "", "nickname": "", "url": url, "message": msg}


def _recent_rows(data):
    """`get_recent_contact` 的形状：群聊那条的群号在 `peerUin`（chatType=2）或 `group_id`。"""
    out = []
    for r in (data or []):
        if not isinstance(r, dict):
            continue
        try:
            ctype = int(r.get("chatType") or r.get("chat_type") or 0)
        except Exception:
            ctype = 0
        gid = r.get("group_id") or r.get("groupId") or ""
        if not gid and ctype == 2:
            gid = r.get("peerUin") or r.get("peer_uin") or ""
        if not gid:
            continue
        name = (r.get("group_name") or r.get("groupName") or r.get("peerName")
                or r.get("remark") or "")
        out.append({"id": _s(gid), "name": _s(name)})
    return out


def pull_groups(timeout=8):
    """从 NapCat 拉群：先 `get_group_list`，再并上 `get_recent_contact`。

    返回 `{ok, message, groups:[{id, name, known}]}`；拉不到就 `ok:false` +
    「手填也行」的提示（用户明确要的正路是手填，拉得到是锦上添花）。
    """
    found = {}
    errors = []
    ok1, d1 = im._napcat_call("get_group_list", {}, timeout=timeout)
    if ok1 and isinstance(d1, list):
        for r in d1:
            if not isinstance(r, dict):
                continue
            gid = _s(r.get("group_id") or r.get("groupId"))
            if not gid:
                continue
            found[gid] = {"id": gid, "name": _s(r.get("group_name") or r.get("groupName"))}
    elif not ok1:
        errors.append("群列表（%s）" % d1)
    ok2, d2 = im._napcat_call("get_recent_contact", {}, timeout=timeout)
    if ok2 and isinstance(d2, list):
        for r in _recent_rows(d2):
            gid = r["id"]
            if gid not in found:
                found[gid] = r
            elif not found[gid]["name"] and r["name"]:
                found[gid]["name"] = r["name"]
    elif not ok2:
        errors.append("最近会话（%s）" % d2)

    if not found:
        base.log("初始化：从 NapCat 拉群没拉到（%s）" % "、".join(errors or ["两边都空"]))
        return {"ok": False, "groups": [],
                "message": "无法读取群列表，请检查 NapCat；也可手动输入群号。"}

    known = set(groups.known())
    rows = [dict(v, known=(v["id"] in known)) for v in found.values()]
    rows.sort(key=lambda x: (not x["known"], x["id"]))
    base.log("初始化：从 NapCat 拉到 %d 个群（%d 个已经在名单里）"
             % (len(rows), sum(1 for r in rows if r["known"])))
    return {"ok": True, "groups": rows,
            "message": "已读取 %d 个群，请选择要添加的群。" % len(rows)}


# ── 人设：直接编辑 personality.md 的正文 ────────────────────────────

_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def _split_comments(text):
    """正文（注释不显示） + 原样保留的尖括号注释块。"""
    comments = _COMMENT_RE.findall(text or "")
    body = _COMMENT_RE.sub("", text or "").strip("\n")
    # 注释拿走后会在开头留下空行，去掉就行（不影响她读到的正文）
    body = re.sub(r"^\s*\n", "", body)
    return body, comments


def _persona_text():
    p = persona.profile_path()
    try:
        with open(p, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return ""


def persona_get():
    body, comments = _split_comments(_persona_text())
    return {"text": body, "comments": len(comments),
            "file": os.path.basename(persona.profile_path())}


def persona_save(text):
    """写 `personality.md` 的正文（尖括号注释原样保留在开头），热生效。

    ⚠️ 这是**用户自己在面板上改他的人设**，不是代码改文案：正文一个字都不加工
       （不 trim 内部、不换行重排），只去掉首尾空白、保证末尾一个换行。
    """
    body = str(text if text is not None else "")
    if not body.strip():
        return False, "人设正文不能空 —— 至少写一句她是谁", persona_get()
    if len(body) > MAX_PERSONA_CHARS:
        return False, "人设正文最多 %d 字（现在 %d 字）" % (MAX_PERSONA_CHARS, len(body)), persona_get()
    old = _persona_text()
    _b, comments = _split_comments(old)
    head = "".join(c.rstrip("\n") + "\n" for c in comments)
    out = (head + "\n" + body.strip() + "\n") if head else (body.strip() + "\n")
    # ⚠️ 写数据目录那份（`persona.write_path()`），不是读的那份：读允许退回代码目录，
    #    但"人设改动"属于会变的东西，必须落在 MMZBOT_DATA 里。
    p = persona.write_path()
    try:
        d = os.path.dirname(p)
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(out)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    except Exception as e:
        return False, "写不进 %s（%s）" % (os.path.basename(p), e), persona_get()
    persona.forget()          # 按 mtime 的缓存可能同一秒内看不出变化 —— 直接清掉
    base.log("初始化：人设正文已保存（%d 字，尖括号注释 %d 段原样保留）"
             % (len(body.strip()), len(comments)))
    return True, "人设存好了，下一句就用新的（不用重启）", persona_get()


# ── /api 的入口（`agent.on_api` 转进来；只有主人能到这一步）──────────

def api(action, req):
    a = (action or "").strip().lower()
    req = req or {}
    if a == "onboarding.save":
        ok, msg, snap = save(req.get("values") or {})
        return {"ok": ok, "message": msg, "onboard": snap}
    if a == "onboarding.probe":
        r = probe()
        r["onboard"] = snapshot()
        return r
    if a == "onboarding.groups":
        r = pull_groups()
        r["onboard"] = snapshot()
        return r
    if a == "onboarding.persona":
        ok, msg, p = persona_save(req.get("text") or "")
        return {"ok": ok, "message": msg, "persona": p, "onboard": snapshot()}
    return None
