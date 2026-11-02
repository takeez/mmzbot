#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""接入用户表：**每台电脑一个用户、每人一把 token、能单独撤销**。

契约（只读那三份，原样照做，别改形状）：
  · `给手机那边的规格-多电脑接入.md` §3「多用户模型」；
  · 契约 **B1 / B2 / B4**（我们自己第一批答复里定的字段与字符集）；
  · （历史决定）（同一份字段清单的另一种写法）。

落盘文件 `users.json`（**进 `deploy.py` 的 NEVER**，只活在手机上）：

```json
{"用户": [
  {"id": "3f7k", "token": "<20 位 Crockford base32 大写>", "名字": "张三",
   "群": 123456789, "主人QQ": 10002, "主人": false,
   "建立时间": "12:00", "备注": ""}
]}
```

字段（B1 那张表，一个都不能少）：
  `id`（4~8 位短 id，**日志/缓存键用**，不是密钥）、`token`（B2.4：Crockford base32 大写、
  **20 字符**、无 `I L O U`）、`群`（`int` 或 `""`，空 = 沿用电脑 payload 里的 `group_id`）、
  `主人QQ`（**必填**；他本人的 QQ —— "按提问者绑定"查它，**身份就是它**）、
  `名字`（**备注（选填）** —— 展示用，"留空就显示她的称呼"；见 `who.display_name`）、
  `主人`（`true` 的有且只有一条 = 用户自己）、`建立时间`、`备注`（给用户自己看的记事）。

⚠️ **身份 = QQ**：备注 / 称呼 / 昵称都只是**别名**
   认人的唯一实现在 `fgbot/who.py`（`resolve()` / `display_name()`）—— ⛔ 别在别处再写一份。
⚠️ **同一个 QQ 允许有多条记录**（同一个人两台电脑）：主键仍是那个短 `id`，
   挑哪一条的规矩在 `who._pick()`（带电脑名就用它、否则心跳最新那条）。

⚠️ **撤销立刻生效**：本模块按 **mtime 热重载**（带一个 ~1.5 秒的进程内缓存），
   删掉/停用一条只影响那一个人，不重启进程、不动别人的 token（B2.3）。
⚠️ **任何输出里都不出现 token 明文**（E3 的日志纪律）：日志只许用 `id` 或 `token` 的指纹
   （`fingerprint()`），面板"用户管理"页是**唯一的例外**（它必须把邀请码显示给主人看）。
"""

import hmac
import json
import os
import re
import secrets
import threading
import time

from . import base, statuscache, store

FILE = "users.json"

# B2.4 写死的字符集与长度（Crockford base32：去掉了 I L O U）
ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
TOKEN_LEN = 20
ID_LEN = 4

# 短 id 的字符集：同款 Crockford（好念、不会看混）
_HOST_OK = re.compile(r"^[A-Za-z0-9.\-]+$")

_lock = threading.RLock()
_cached = {"mtime": None, "data": None, "at": 0.0}
CACHE_SECONDS = 1.5          # 改完最多 1.5 秒内全体生效（B2.3 要的"立刻"）


# ── token / id ──────────────────────────────────────────────────────

def new_token():
    """一把新的用户 token：20 位 Crockford base32 **大写**（B2.4 定死）。"""
    return "".join(secrets.choice(ALPHABET) for _ in range(TOKEN_LEN))


def _upper(s):
    return str(s or "").strip().upper()


def valid_token(t):
    """形状对不对（长度 + 字符集）。**大小写不敏感**（比较前统一 upper）。"""
    s = _upper(t)
    return len(s) == TOKEN_LEN and all(ch in ALPHABET for ch in s)


def fingerprint(t, n=4):
    """token 的指纹：**前 4 位 + 长度** —— 够定位是谁，不足以复原（C5 的口径）。
    长度不对时前 4 位照给（日志里要能看出"疑似某人配错了"）。"""
    s = str(t or "")
    return "%s…（共 %d 位）" % (s[:n], len(s)) if s else "（空）"


def _new_id(taken):
    for _ in range(64):
        i = "".join(secrets.choice(ALPHABET) for _ in range(ID_LEN))
        if i not in taken:
            return i
    return "".join(secrets.choice(ALPHABET) for _ in range(8))


def _now():
    return base.local_now().strftime("%Y-%m-%d %H:%M")


# ── 读（mtime 热重载）────────────────────────────────────────────────

def _mtime():
    try:
        return os.path.getmtime(store.path(FILE))
    except Exception:
        return None


def records(force=False):
    """当前这张表（`list`，坏文件当空的）。**每次调用都看 mtime** —— 撤销立刻生效。"""
    p = store.path(FILE)
    now = time.time()
    with _lock:
        m = _mtime()
        if (not force and _cached["data"] is not None and _cached["mtime"] == m
                and (now - _cached["at"]) < CACHE_SECONDS):
            return _cached["data"]
        d = store.read_json(FILE)
        out = []
        if isinstance(d, dict):
            rows = d.get("用户")
            if isinstance(rows, list):
                for r in rows:
                    if isinstance(r, dict) and str(r.get("token") or "").strip():
                        out.append(r)
        _cached.update({"mtime": m, "data": out, "at": now})
        return out


def _invalidate():
    with _lock:
        _cached.update({"mtime": None, "data": None, "at": 0.0})


def tokens():
    """`[(记录, token), …]` —— 鉴权时挨个比（就几个人，够快）。"""
    out = []
    for r in records():
        t = str(r.get("token") or "").strip()
        if t:
            out.append((r, t))
    return out


def find_by_token(tok, refresh=False):
    """按 token 认人（B2.3「按 token 认人」）。**定长比较**，防时序侧信道。

    ⚠️ 拿 **bytes** 比，不是 str：`hmac.compare_digest` 对"带非 ASCII 的字符串"
       直接抛 TypeError（有人在头里塞中文就会把请求打成 500，自检里踩到过）。
    """
    want = _upper(tok)
    if not want:
        return None
    wb = want.encode("utf-8")
    for r, t in tokens():
        if hmac.compare_digest(_upper(t).encode("utf-8"), wb):
            return r
    return None


def owner():
    """`主人: true` 的那条（有且只有一条，B1/B6）。没有就 None。"""
    for r in records():
        if r.get("主人"):
            return r
    return None


def owner_qq():
    """主人**他本人的 QQ 号** —— **直接转发 `base.owner_qq()`**（配置 `bot.ownerQQ`）。

    ⚠️ 这是「说话的人是不是主人」的唯一判据（`package` 工具用它做 available）：
       用户表里有且只有一条 `主人: true`（B1/B6）。配了 `role: owner` 但用户表
       里还没那条记录时认不出是谁 —— 返回空串（宁可不给这个工具）。
    """
    return base.owner_qq()


def by_qq(qq):
    """按**他本人的 QQ** 找那台电脑（A2 的"按提问者绑定"查这个）。

    ⚠️ 同一个人**允许两条记录**（两台电脑）。这时候**不能随便返回第一条**——
       挑哪一条的规矩在 `who._pick()`（那个词里带了电脑名就用它，否则取心跳最新那条）。
       这里的调用方（`who`）拿到的就是**挑好的那一条**。
    """
    s = str(qq or "").strip()
    if not s:
        return None
    hit = [r for r in records() if str(r.get("主人QQ") or "").strip() == s]
    if not hit:
        return None
    if len(hit) == 1:
        return hit[0]
    from . import who                     # 懒 import：who 在模块层就 import 本模块
    return who._pick(hit, "")


def by_id(uid):
    """按 **id** 找那条记录（鉴权认出来的身份就是它）。"""
    s = str(uid or "").strip()
    if not s:
        return None
    for r in records():
        if str(r.get("id") or "") == s:
            return r
    return None


def groups():
    """所有用户登记的群（`int` 的那些）—— `bot.groups` 要并上它们（B5）。"""
    out = []
    for r in records():
        g = r.get("群")
        try:
            n = int(g)
        except Exception:
            continue
        if n > 0 and n not in out:
            out.append(n)
    return out


def ident_of(rec):
    """给 `server._identify()`（契约里叫 `_authorized`，本批落地成这个名字）用的身份
    （A3：`{"id","主人","名字","群"}`）。
    `rec` 为 None = 认不出人。"""
    if not isinstance(rec, dict) or not rec:
        return None
    return {
        "id": str(rec.get("id") or ""),
        "主人": bool(rec.get("主人")),
        "名字": str(rec.get("名字") or ""),
        "群": rec.get("群") if rec.get("群") not in (None, "") else "",
        "主人QQ": str(rec.get("主人QQ") or ""),
        # token 只在这一层内部流转（算签名要它）；绝不打日志、绝不进 HTTP 正文
        "token": str(rec.get("token") or ""),
    }


def owner_ident():
    """主人身份（`role: owner` 那个隐藏键认出来的就是它）。没有用户表记录时用这个形状。"""
    r = owner()
    if r:
        return ident_of(r)
    return {"id": "own", "主人": True, "名字": "", "群": "", "主人QQ": "", "token": ""}


# ── 写（原子：走 store.write_json）──────────────────────────────────

def _save(rows):
    prev = store.read_json(FILE)
    top = dict(prev) if isinstance(prev, dict) else {}
    top["用户"] = rows
    okw = store.write_json(FILE, top)
    _invalidate()
    return okw


def _int_or_blank(v):
    s = str(v if v is not None else "").strip()
    if not s:
        return ""
    try:
        return int(s)
    except Exception:
        return ""


def add(name="", qq="", group="", note="", is_owner=False):
    """发一把新 token（B2.1：**手机生成**）。返回 `(ok, 说明, 记录)`。

    ⚠️ ：**QQ 必填、名字（备注）选填**。
       · 身份 = QQ（认人 / 播报 / 心跳缓存键都靠它）；
       · `名字` 降级成"面板备注"，留空就按 `who.display_name` 显示她的称呼/昵称/QQ 号；
       · **同一个 QQ 允许两条**（同一个人两台电脑）—— 所以这里**不再拦重复**。
    """
    qq = str(qq or "").strip()
    if not qq:
        return False, "得填这个人的 QQ 号（认人、播报、心跳都靠它；名字只是备注，可以不填）", None
    if not re.match(r"^\d{4,12}$", qq):
        return False, "QQ 号得是 4~12 位数字", None
    name = str(name or "").strip()
    rows = [dict(r) for r in records(force=True)]
    taken = set(str(r.get("id") or "") for r in rows)
    rec = {
        "id": _new_id(taken),
        "token": new_token(),
        "名字": name,
        "群": _int_or_blank(group),
        "主人QQ": int(qq),
        "主人": bool(is_owner),
        "建立时间": _now(),
        "备注": str(note or "").strip(),
    }
    rows.append(rec)
    if not _save(rows):
        return False, "写不进 %s（手机上磁盘满了？）" % FILE, None
    return True, "给「%s」发了一把新令牌（id %s）" % (name or ("QQ " + qq), rec["id"]), rec


def remove(uid):
    """撤销：删掉那一条 —— **立刻生效、只影响他一个**（B2.3）。"""
    uid = str(uid or "").strip()
    rows = [dict(r) for r in records(force=True)]
    keep = [r for r in rows if str(r.get("id") or "") != uid]
    if len(keep) == len(rows):
        return False, "没有 id = %s 这条记录" % uid
    if not _save(keep):
        return False, "写不进 %s" % FILE
    # B2.3 附带：撤销他之后，他的心跳缓存也一并删掉（别留着他的数据）
    dropped = statuscache.drop(uid)
    return True, "撤销了 id %s（他那把令牌立刻作废%s）" % (
        uid, "，他的心跳缓存也删了" if dropped else "")


def update(uid, name=None, group=None, note=None, qq=None):
    """改备注（= `名字`）/ 群 / 记事（= `备注`）/ QQ（B2/E1 的"改名字和群"）。

    ⚠️ `名字` 是**备注（选填）**，所以**允许清空**（清空 = 显示名往下走
       她的称呼 / 昵称 / QQ 号）。改 QQ 也一样允许清空，但清空之后这个人就没身份了
       —— 说明里会提醒他一句（只是面板上的字，不进她的材料）。
    """
    uid = str(uid or "").strip()
    rows = [dict(r) for r in records(force=True)]
    hit = None
    for r in rows:
        if str(r.get("id") or "") == uid:
            hit = r
    if hit is None:
        return False, "没有 id = %s 这条记录" % uid
    warn = ""
    if name is not None:
        hit["名字"] = str(name).strip()          # 空 = 不留备注（显示名往下走）
    if group is not None:
        hit["群"] = _int_or_blank(group)
    if note is not None:
        hit["备注"] = str(note).strip()
    if qq is not None:
        s = str(qq).strip()
        if s and not re.match(r"^\d{4,12}$", s):
            return False, "QQ 号得是 4~12 位数字"
        if not s and str(hit.get("主人QQ") or "").strip() not in ("", "0"):
            warn = "（QQ 清空了 —— 认不出这个人了，补上才能按 QQ 认人）"
        hit["主人QQ"] = int(s) if s else 0
    if not _save(rows):
        return False, "写不进 %s" % FILE
    return True, "改好了（id %s）%s" % (uid, warn)


# ── 邀请码（B4：`FG2-1|<公网host:port>|<token>`）──────────────────

def valid_public_url(text):
    """`bot.publicUrl` / 邀请码第二段的形状校验。

    ⚠️ 逐条照抄电脑侧 `InviteCode.cs` 的拒收规则（**最终口径**，B4/D3）：
       含 `://` → 拒；含 `/` → 拒；没有 `:` / `:` 在最前 / `:` 在最后 → 拒；
       host 只允许字母数字点减号（IPv6 字面量会被拒）；端口必须 1~65535。
    返回 `(host, port)` 或 `None`。
    """
    s = str(text or "").strip()
    if not s or "://" in s or "/" in s:
        return None
    if ":" not in s:
        return None
    host, _, port = s.rpartition(":")
    host = host.strip()
    port = port.strip()
    if not host or not port or ":" in host:
        return None
    if not _HOST_OK.match(host):
        return None
    if not port.isdigit():
        return None
    n = int(port)
    if not (1 <= n <= 65535):
        return None
    return host, n


def invite_code(rec, public_url):
    """拼一条邀请码。返回 `(码, 错在哪)` —— 地址没填/形状不对就生成不出来。"""
    if not isinstance(rec, dict) or not rec:
        return None, "没有这条记录"
    if valid_public_url(public_url) is None:
        return None, ("没填对公网地址（要 `公网IP:端口` 或 `DDNS名:端口`：不带 http://、"
                      "不带斜杠、端口 1~65535；端口是**你在光猫上填的那个**，不是 17383）")
    tok = str(rec.get("token") or "").strip()
    if not tok:
        return None, "这条记录没有令牌"
    return "FG2-1|%s|%s" % (str(public_url).strip(), tok), ""


def panel_rows(public_url="", fetch_nick=False):
    """面板"用户管理"页要的那份（**唯一会带着 token 明文出去的地方** = 邀请码）。

    ⚠️ 它只回给**主人**（`agent.on_api` 里先判身份），公网来源根本进不来（门禁在 server 层）。

    ⚠️ 多给三个**给人看**的键（都是 `who.py` 算出来的，不进任何给模型看的材料）
       `显示名`（四级兜底：备注 → 称呼 → 昵称 → QQ）、`称呼`、`昵称`。
       `fetch_nick=True`（面板那条路）才允许为"还看不出是谁"的那几条**现取一次**昵称；
       默认关着 —— 别让任何一个调用方顺手把网络请求带进来。
    """
    from . import who                       # 懒 import：who 在模块层就 import 本模块
    out = []
    for r in records():
        tok = str(r.get("token") or "")
        code, _err = invite_code(r, public_url) if tok else (None, "")
        qq = str(r.get("主人QQ") or "")
        m = who.aliases(r)
        if fetch_nick and qq and not m.get("昵称"):
            # 面板那一列要把**昵称**也摆出来（"别只显示裸号"）。现取只在"还没有昵称"时发生，
            # 而且 `who.fetch_nick` 每人每进程只问一次、**不落盘** —— 第一次打开面板才付这个钱。
            got = who.fetch_nick(qq)
            if got:
                m["昵称"] = [got]
        out.append({
            "id": str(r.get("id") or ""),
            "名字": str(r.get("名字") or ""),
            "群": r.get("群") if r.get("群") not in (None, "") else "",
            "主人QQ": qq,
            "主人": bool(r.get("主人")),
            "建立时间": str(r.get("建立时间") or ""),
            "备注": str(r.get("备注") or ""),
            "指纹": fingerprint(tok),
            "邀请码": code or "",
            "显示名": who.display_name(r, fetch=fetch_nick),
            "称呼": (m.get("称呼") or [""])[0],
            "昵称": (m.get("昵称") or [""])[0],
        })
    return out


def stats():
    """一行字（日志/状态用）—— **不带 token**。"""
    rs = records()
    own = owner()
    who = ("主人 id %s" % own.get("id")) if own else "主人走配置文件里的 role: owner"
    return "%d 个用户（%s）" % (len(rs), who)


# ── 导出 / 导入（面板「用户管理」页那两个按钮）──────────────────────
#
# ⚠️ 这一节是整个项目**第二处**允许把 token 明文交出去的地方（第一处是邀请码
#    `users.panel_rows` 的 `邀请码` 字段）—— 只回给**主人**（agent 层已经判过身份），
#    公网来源根本走不到这里（门禁在 server 层）。
#    ⛔ **日志里一个字都不许出现**（E3 的日志纪律）：调用方只许记条数/字节数。
#    ⛔ 导出的那份**含密钥**，面板上必须写清"别外传"（已写死在那页的 hint 里）。

def export_text():
    """把 `users.json` 原文导出成一段 JSON 文本（**含每个人的 token**）。

    形状照抄文件本身（`{"用户": [...]}`），这样导出的东西**直接粘回去就能用**，
    也方便人拿眼睛看。文件坏了/不存在就回一张空表（不炸）。
    """
    d = store.read_json(FILE)
    top = dict(d) if isinstance(d, dict) else {}
    rows = top.get("用户")
    if not isinstance(rows, list):
        rows = []
    top["用户"] = rows
    return json.dumps(top, ensure_ascii=False, indent=2) + "\n"


def import_text(text):
    """把导出的那份写回去（**整张表覆盖**）。返回 `(ok, 说明, 条数)`。

    为什么要校验：这是"用一份文件换掉她整道门禁"的操作，宁可直接拒掉，
    也别把 id 重复 / token 形状不对的表写进去 —— 那种表会让她**认不出人来**，
    而且症状很难懂（"码是对的，就是进不来"）。

    校验逐条：JSON 得是对象、`用户` 得是 list、每条得有非空且不重复的 `id`、
    `token` 得是合法形状（20 位 Crockford base32）、`主人` 最多一条。
    ⚠️ 出错信息里**只有 id 和序号，没有 token**。
    """
    if isinstance(text, dict):
        d = text
    else:
        s = str(text or "").strip()
        if not s:
            return False, "没给内容（空的）", 0
        try:
            d = json.loads(s)
        except Exception as e:
            # ⚠️ **不能回显原文**（那里面全是 token）；只说错在第几行第几列
            where = ""
            if getattr(e, "lineno", None):
                where = "（第 %s 行第 %s 列）" % (e.lineno, e.colno)
            return False, "不是合法 JSON%s" % where, 0
    if not isinstance(d, dict):
        return False, "这份东西不是个 JSON 对象（应该是 {\"用户\": [ … ]}）", 0
    rows = d.get("用户")
    if not isinstance(rows, list):
        return False, "没有「用户」这一段（或者它不是个列表）", 0

    clean, seen, owners = [], set(), 0
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            return False, "第 %d 条不是个对象" % (i + 1), 0
        uid = str(r.get("id") or "").strip()
        if not uid:
            return False, "第 %d 条没有 id" % (i + 1), 0
        if uid in seen:
            return False, "id 重复了：%s" % uid, 0
        seen.add(uid)
        if not valid_token(str(r.get("token") or "").strip()):
            return False, ("第 %d 条（id %s）的令牌形状不对 —— 要 20 位 "
                           "Crockford base32 大写（没有 I L O U）" % (i + 1, uid)), 0
        if r.get("主人"):
            owners += 1
        clean.append(r)
    if owners > 1:
        return False, "有 %d 条都标着「主人」—— 只能有一条" % owners, 0

    # 覆盖之前先把现在这张留一份（一个固定名字的文件，就地放着；不进备份流程）
    prev = store.read_json(FILE)
    if isinstance(prev, dict) and isinstance(prev.get("用户"), list) and prev["用户"]:
        try:
            with open(store.path(FILE + ".bak"), "w", encoding="utf-8") as f:
                json.dump(prev, f, ensure_ascii=False, indent=2)
        except Exception:
            pass                        # 备份写不进去也照样导 —— 别为了备份把正事挡住

    top = dict(d)
    top["用户"] = clean
    if not store.write_json(FILE, top):
        return False, "写不进 %s（手机上磁盘满了？）" % FILE, 0
    _invalidate()                        # 立刻生效（不等那 1.5 秒缓存）
    return True, "导入了 %d 个人（覆盖了原来那张表；旧的备份在 %s.bak）" % (len(clean), FILE), len(clean)
