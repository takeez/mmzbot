#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公网入口的两道闸：**非重放校验**（时间戳 + nonce）与**失败限流**。

契约（原样照做）：
  · 契约里的重放保护口径；
  · 契约 **C1/C2/C3/C4/C5**（我们自己第一批答复里定死的六条细节）；
  · （历史决定）（窗口 **±120 秒**、nonce **小写 hex ≥32 字符**）；
  · 历史讨论 §11 / §12（429 口径、±120 秒不变）。

写死的东西：

| 项 | 值 |
|---|---|
| 新头 | `X-FG-Signature: sha256=<hex 小写>` |
| 签什么 | `HMAC-SHA256(key = 该用户的 token, message = 时间戳 + "\n" + nonce + "\n" + 正文原始字节)` |
| 时间戳 | `X-FG-Timestamp`：Unix 秒（十进制整数，无小数、无前导零） |
| nonce | `X-FG-Nonce`：`secrets.token_hex(16)` → 32 个**小写 hex** 字符 |
| 窗口 | **±120 秒**（按**服务端当前时间**算，不按对方的时间戳） |
| nonce 表 | **内存**字典，只留窗口内；按 **token+nonce** 去重；不落盘 |
| 老头 | `X-Signature: sha1=<hex>` **原样继续接受**（老契约一个字节不动，**不要求**那两个新头） |
| 拒绝 | 一律 **403 + 空正文**（不回显 nonce / timestamp） |

⚠️ **手机上（宿主机）的时钟实测偏 30 多秒**（答复 C3），所以窗口定 **120 秒**、
   `clock` 那一层不再对本模块做任何补偿 —— 别自己发明"对时"。
"""

import hashlib
import hmac
import re
import threading
import time

HEAD_SIG = "X-FG-Signature"
HEAD_TS = "X-FG-Timestamp"
HEAD_NONCE = "X-FG-Nonce"

WINDOW_SECONDS = 120          # ±120 秒（C3 定稿）
MIN_NONCE_CHARS = 32          # ≥16 字节随机 → 32 个 hex 字符（C2）

_HEX = re.compile(r"^[0-9a-fA-F]+$")

_nonced = {}                  # "token\nnonce" -> 过期时刻（epoch 秒）
_nlock = threading.Lock()


# ── nonce 表（内存、只留窗口内、不落盘）─────────────────────────────

def _prune(now):
    dead = [k for k, exp in _nonced.items() if exp <= now]
    for k in dead:
        _nonced.pop(k, None)


def seen_before(token, nonce, ts, now=None):
    """这个 (token, nonce) 在窗口内见过吗？没见过就记下来并返回 False。

    ⚠️ 过期时刻取 `max(现在, 对方时间戳) + 2×窗口`：
       对方的时间戳最多能比服务端快 120 秒，只按"现在 + 窗口"留会漏掉最边上的重放。
    """
    now = time.time() if now is None else float(now)
    key = "%s\n%s" % (str(token or ""), str(nonce or ""))
    with _nlock:
        _prune(now)
        if key in _nonced:
            return True
        _nonced[key] = max(now, float(ts)) + 2 * WINDOW_SECONDS
        return False


def nonce_count():
    """表里现在有几条（日志/自检用）。"""
    with _nlock:
        return len(_nonced)


def reset_nonces():
    """清空（**只给自检用**）。"""
    with _nlock:
        _nonced.clear()


# ── 签名 ────────────────────────────────────────────────────────────

def message(ts, nonce, body):
    """被签的那串字节：`时间戳 + "\\n" + nonce + "\\n" + 正文原始字节`。"""
    return ("%s\n%s\n" % (ts, nonce)).encode("utf-8") + (body or b"")


def sign_sha256(token, body, ts=None, nonce=None):
    """算一套新头（**手机 → 电脑**那个方向用它，见 `im.forward_to_pc`）。"""
    ts = int(time.time()) if ts is None else int(ts)
    nonce = new_nonce() if nonce is None else str(nonce)
    h = hmac.new(str(token or "").encode("utf-8"), message(ts, nonce, body),
                 hashlib.sha256).hexdigest()
    return {"ts": ts, "nonce": nonce, "sig": "sha256=" + h}


def new_nonce():
    """≥16 字节随机的小写 hex（C2 `secrets.token_hex(16)` 这种来源）。"""
    import secrets
    return secrets.token_hex(16)


def sign_sha1(token, body):
    """老契约那把（`X-Signature: sha1=`）—— **继续用同一个 token**，别混。"""
    return hmac.new(str(token or "").encode("utf-8"), body or b"", hashlib.sha1).hexdigest()


def _match(body, token, hexsig, algo):
    if algo == "sha256":
        want = hmac.new(str(token).encode("utf-8"), body, hashlib.sha256).hexdigest()
    else:
        want = hmac.new(str(token).encode("utf-8"), body, hashlib.sha1).hexdigest()
    return hmac.compare_digest(want, hexsig)


def _match_new(body, token, hexsig, ts, nonce):
    """新签名那一份：**签的是"时间戳 + \\n + nonce + \\n + 正文"**，不是光正文。

    ⚠️ 这就是 C1 那个洞的正解（从前只签正文 → 改时间戳/nonce 签名照样匹配）。
       别图省事拿 `_match()` 顶替 —— 那等于把重放保护签成空气（自检里踩过）。
    """
    want = hmac.new(str(token).encode("utf-8"), message(ts, nonce, body),
                    hashlib.sha256).hexdigest()
    return hmac.compare_digest(want, hexsig)


def verify_new(sig_header, ts_header, nonce_header, body, candidates, now=None):
    """认这条**新签名**是哪把 token 签的。

    `candidates` = `[(身份, token), …]`（身份可以是任何东西，原样回给你）。
    返回 `(身份, token, 说明)` —— 认不出来时身份是 None，说明**只进日志**（不进 HTTP 正文）。

    ⚠️ 顺序：形状 → 窗口 → 签名 → **nonce 去重**。
       去重放在签名之后：不能让"随便编个 nonce"的人把表撑爆（C5 那句"时间戳超窗口就
       不往表里放"也是同一个意思）。
    """
    now = time.time() if now is None else float(now)
    raw = str(sig_header or "").strip()
    low = raw.lower()
    if not low.startswith("sha256="):
        return None, None, "新签名头没有 sha256= 前缀"
    hexsig = low[7:].strip()
    if not hexsig or not _HEX.match(hexsig):
        return None, None, "新签名头不是十六进制"
    ts_txt = str(ts_header or "").strip()
    if not ts_txt.isdigit():
        return None, None, "缺时间戳（或不是十进制整数）"
    ts = int(ts_txt)
    if abs(now - ts) > WINDOW_SECONDS:
        return None, None, "时间戳超出 ±%d 秒窗口" % WINDOW_SECONDS
    raw_nonce = str(nonce_header or "").strip()
    if len(raw_nonce) < MIN_NONCE_CHARS or not _HEX.match(raw_nonce):
        return None, None, "缺 nonce（或不是 ≥%d 个 hex 字符）" % MIN_NONCE_CHARS
    hit = None
    for ident, tok in candidates:
        if tok and _match_new(body or b"", tok, hexsig, ts, raw_nonce):
            hit = (ident, tok)
            break
    if hit is None:
        return None, None, "签名不符（不是任何一把已知令牌签的）"
    if seen_before(hit[1], raw_nonce, ts, now=now):
        return None, None, "nonce 重复（同一条请求被重放了）"
    return hit[0], hit[1], "新签名 OK"


def parse_old_sig(sig_header):
    """老头 `X-Signature: sha1=<hex>`（也接受不写前缀 / 大小写不敏感）。"""
    raw = str(sig_header or "").strip()
    low = raw.lower()
    if low.startswith("sha1="):
        return low[5:].strip()
    if raw and _HEX.match(raw):
        return low
    return ""


def verify_old(sig_header, body, candidates):
    """认这条**老签名**是哪把 token 签的（老契约：**不要求**时间戳和 nonce）。"""
    hexsig = parse_old_sig(sig_header)
    if not hexsig:
        return None, None, "老签名格式不对"
    for ident, tok in candidates:
        if tok and _match(body or b"", tok, hexsig, "sha1"):
            return ident, tok, "老签名（SHA-1）OK"
    return None, None, "老签名不符"
