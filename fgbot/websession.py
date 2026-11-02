#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""远程面板的**登录会话**：cookie 里一把随机串，服务端只存它的 sha256。

为什么不是把令牌写在 localStorage 里（那是局域网 / 本机那条老路，保留）：
反代后面是**公网**，页面里、请求头里都不该长期躺着一把"等于机器人身份"的明文令牌。
现在这条路是：

    浏览器 POST /login（口令 = 共享令牌）
      → 服务端验过 → 发一个 `Set-Cookie: fgPanelSession=<随机 43 字符>`
        （HttpOnly / SameSite=Lax / Path=/；HTTPS 反代后面再加 Secure）
      → 之后浏览器每个请求自动带 cookie，服务端只认 **cookie 的 sha256**
      → POST /logout → 服务端把这条会话从内存里删掉 + 浏览器把 cookie 清掉
        **立刻失效**（不是"等它过期"）

⛔ 三条纪律：
   · **内存里不存 cookie 原值**（只存 sha256）—— 就算有人 dump 进程内存，也拿不到能用的会话；
   · **日志里一个字节都不落**（登录成功 / 失败只写来源 IP 和原因）；
   · 表只在内存里：**重启进程 = 所有会话失效**（要重新登录）。这是有意的 ——
     少一份能落盘的"长期钥匙"。

另外管**登录失败冷却**：同一个 IP 在 10 分钟窗口里错 N 次 → 冷却一段时间，
期间连**正确口令**也不收（免得拿"登录页"当口令爆破的测速器）。本机 / 局域网
不需要登录（面板本来就直接开），所以这套只对公网 / 反代后面的来源有意义。
"""

import hashlib
import re
import secrets
import threading
import time

from . import base

COOKIE_NAME = "fgPanelSession"
COOKIE_RE = re.compile(r"^[A-Za-z0-9_-]{20,128}$")

# 会话寿命（都能用 `panel.*` 覆盖）：
DEFAULT_SESSION_HOURS = 12        # 绝对寿命：签发起 12 小时后一定失效
DEFAULT_IDLE_MINUTES = 120        # 闲置寿命：2 小时没动就失效
# 登录失败冷却：
DEFAULT_MAX_FAILS = 5             # 10 分钟窗口内错 5 次
DEFAULT_COOLDOWN_SECONDS = 300    # 冷却 5 分钟
LOGIN_WINDOW_SECONDS = 600

_lock = threading.RLock()
_sessions = {}                    # sha256(cookie) -> {"ident", "created", "last"}
_fails = {}                       # ip -> [失败时刻, …]
_blocks = {}                      # ip -> 解冻时刻


def _panel():
    return base.cfg().get("panel") or {}


def _int(key, default, lo=1, hi=10 ** 9):
    try:
        n = int(_panel().get(key) or default)
    except Exception:
        n = default
    return max(lo, min(hi, n))


def session_seconds():
    """一条会话的**绝对**寿命（秒）。"""
    return _int("sessionHours", DEFAULT_SESSION_HOURS, 1, 24 * 365) * 3600


def idle_seconds():
    """一条会话**闲置**多久失效（秒）。"""
    return _int("sessionIdleMinutes", DEFAULT_IDLE_MINUTES, 1, 24 * 365) * 60


def max_fails():
    return _int("loginMaxFails", DEFAULT_MAX_FAILS, 1, 1000)


def cooldown_seconds():
    return _int("loginCooldownSeconds", DEFAULT_COOLDOWN_SECONDS, 1, 24 * 3600)


def _hash(raw):
    return hashlib.sha256(str(raw).encode("utf-8")).hexdigest()


def fingerprint(raw):
    """会话 id 的**日志指纹**（sha256 前 8 位）—— 排查时能对上，但拿不到原值。"""
    raw = str(raw or "").strip()
    return _hash(raw)[:8] if raw else "-"


def _purge(now):
    ttl = session_seconds()
    idle = idle_seconds()
    for h in list(_sessions):
        rec = _sessions[h]
        if now - rec["created"] > ttl or now - rec["last"] > idle:
            _sessions.pop(h, None)


def new(ident, now=None):
    """签一条会话，返回**要写进 cookie 的原值**（只在这一刻存在）。"""
    raw = secrets.token_urlsafe(32)
    ts = time.time() if now is None else float(now)
    rec = {"ident": dict(ident or {}), "created": ts, "last": ts}
    with _lock:
        _purge(ts)
        _sessions[_hash(raw)] = rec
    return raw


def lookup(raw, now=None):
    """这个 cookie 值对应的身份（无效 / 过期 / 退出过 → `None`）。"""
    raw = str(raw or "").strip()
    if not COOKIE_RE.match(raw):
        return None
    ts = time.time() if now is None else float(now)
    h = _hash(raw)
    with _lock:
        rec = _sessions.get(h)
        if not rec:
            return None
        if (ts - rec["created"] > session_seconds()
                or ts - rec["last"] > idle_seconds()):
            _sessions.pop(h, None)
            return None
        rec["last"] = ts
        # 身份里**不带 token**（`users.owner_ident()` 那份可能带每人的 token，别捂着）
        return {k: v for k, v in rec["ident"].items() if k != "token"}


def revoke(raw):
    """退出登录：把这条会话**立刻**从服务端删掉。返回是否真的删了一条。"""
    raw = str(raw or "").strip()
    if not COOKIE_RE.match(raw):
        return False
    with _lock:
        return _sessions.pop(_hash(raw), None) is not None


def count():
    """现在有几条活着的会话（自检 / 排查看）。"""
    with _lock:
        _purge(time.time())
        return len(_sessions)


def reset():
    """清空所有会话（**只给自检用**）。"""
    with _lock:
        _sessions.clear()
        _fails.clear()
        _blocks.clear()


# ── 登录失败冷却 ──────────────────────────────────────────────────────

def _prune_login(now):
    for ip in list(_fails):
        keep = [t for t in _fails[ip] if now - t <= LOGIN_WINDOW_SECONDS]
        if keep:
            _fails[ip] = keep
        else:
            _fails.pop(ip, None)
    for ip in list(_blocks):
        if _blocks[ip] <= now:
            _blocks.pop(ip, None)


def login_blocked(ip, now=None):
    """还在冷却期吗？返回还要等几秒（没冷却 = 0）。"""
    ip = str(ip or "")
    if not ip:
        return 0
    ts = time.time() if now is None else float(now)
    with _lock:
        _prune_login(ts)
        left = _blocks.get(ip)
        if not left:
            return 0
        return max(1, int(round(left - ts)))


def login_fail(ip, now=None):
    """记一次登录失败。返回 `(现在冷却了吗, 还要等几秒)`。"""
    ip = str(ip or "")
    if not ip:
        return False, 0
    ts = time.time() if now is None else float(now)
    with _lock:
        _prune_login(ts)
        left = _blocks.get(ip)
        if left:
            return True, max(1, int(round(left - ts)))
        hits = _fails.setdefault(ip, [])
        hits.append(ts)
        if len(hits) >= max_fails():
            _blocks[ip] = ts + cooldown_seconds()
            _fails.pop(ip, None)
            return True, cooldown_seconds()
        return False, 0


def login_ok(ip):
    """登录成功 → 这个 IP 的失败记录清掉（不背旧账）。"""
    ip = str(ip or "")
    with _lock:
        _fails.pop(ip, None)
        # ⚠️ **不**清 `_blocks`：冷却期内根本走不到"成功"这一步（登录入口先拦）。
        #    真到了这里（比如冷却刚好到点），把残留也一起清掉更干净。
        _blocks.pop(ip, None)


def login_state(ip, now=None):
    """给日志用的一行（**不含任何输入内容**）。"""
    ts = time.time() if now is None else float(now)
    left = login_blocked(ip, ts)
    if left:
        return "冷却中（还有 %d 秒）" % left
    with _lock:
        _prune_login(ts)
        n = len(_fails.get(str(ip or ""), []))
    return "窗口内失败 %d 次" % n


# ── cookie 那点字符串 ─────────────────────────────────────────────────

def raw_from_cookie(value):
    """从 `Cookie:` 请求头里挑出会话那把（只认合法形状，别的一律空串）。"""
    for part in str(value or "").split(";"):
        k, _, v = part.strip().partition("=")
        if k.strip() != COOKIE_NAME:
            continue
        v = v.strip().strip('"')
        return v if COOKIE_RE.match(v) else ""
    return ""


def cookie_header(raw, max_age, secure=False):
    """拼 `Set-Cookie` 的值。

    · `HttpOnly` —— JS 读不到（XSS 也偷不走）；
    · `SameSite=Lax` —— 跨站 POST 不带它（配合服务端那道 `X-FG-Panel` 头，双保险）；
    · `Path=/` —— 面板的每个接口都要带；
    · `Secure` —— **只在 HTTPS（可信反代的 `X-Forwarded-Proto: https`）时加**：
      直连 HTTP（局域网老路）加了它就发不出去，浏览器会整条丢掉。
    """
    raw = str(raw or "")
    parts = ["%s=%s" % (COOKIE_NAME, raw), "Path=/", "HttpOnly", "SameSite=Lax",
             "Max-Age=%d" % int(max_age)]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)
