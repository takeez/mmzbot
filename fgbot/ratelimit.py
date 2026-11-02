#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""鉴权失败限流：**每 IP 5 分钟内 10 次失败 → 封 15 分钟 → 429 + Retry-After**。

契约（`给PCStatus的答复.md` D2 + `PCStatus\给手机那边的答复-第三批.md` §11）：
  · 计数只数**鉴权失败**（签名不符 / 缺头 / 超窗口 / nonce 重放 / 没带凭据）；
  · **正常请求不算失败**（200 的那些一个字节都不加计数）；
  · 封禁期间来自该 IP 的请求一律 **429 + `Retry-After: <秒>` + 空正文**
    （第一批曾写 403，第三批 §11 定稿改成 **429**，电脑侧会照 `Retry-After` 等）；
  · **本机 / 局域网来源永不封** —— 那是自己人（用户在同一个家里网里），
    误封他会以为是"她坏了"，而且公网扫描根本进不来这一层（门禁在更前面）。
  · 表**只在内存里**（重启就清空；落盘反而会把"临时误伤"拖成永久的）。

⚠️ 一个必须说清的事实（答复 D2 原文）：端口一映射，这台手机就会被全网扫。
   这一套只是**抬门槛**，不是"安全"；真正的边界是"必须先拿到 token"。
"""

import threading
import time

WINDOW_SECONDS = 300          # 5 分钟
MAX_FAILS = 10                # 10 次
BAN_SECONDS = 900             # 15 分钟
RETRY_AFTER_MAX = 900         # 契约里电脑侧最多认到 15 分钟

# ⚠️ 必须是 **RLock**：`state()` 自己拿着锁、里面又调 `retry_after()`（也要锁）。
#    用普通 Lock 会在第一次调用就死锁（自检直接挂住，2026-10-03 踩过）。
_lock = threading.RLock()
_fails = {}                   # ip -> [失败时刻, …]
_bans = {}                    # ip -> 解封时刻


def _prune(now):
    for ip in list(_fails):
        keep = [t for t in _fails[ip] if now - t <= WINDOW_SECONDS]
        if keep:
            _fails[ip] = keep
        else:
            _fails.pop(ip, None)
    for ip in list(_bans):
        if _bans[ip] <= now:
            _bans.pop(ip, None)


def retry_after(ip, now=None):
    """还要等几秒（**没被封就是 0**）。给 `Retry-After` 用，上限 15 分钟。"""
    now = time.time() if now is None else float(now)
    with _lock:
        _prune(now)
        left = _bans.get(str(ip or ""))
        if not left:
            return 0
        return max(1, min(RETRY_AFTER_MAX, int(round(left - now))))


def banned(ip, now=None):
    """现在封着吗。"""
    return retry_after(ip, now) > 0


def fail(ip, now=None):
    """记一次**鉴权失败**。返回 `(现在封着吗, 还要等几秒)`。

    ⚠️ 只在"窗口内失败次数 ≥ 10"的那一刻开始封 —— 封了之后**不再累加**，
       所以反复打也不会把 15 分钟延长（免得扫描器把用户自己人拖进长封禁）。
    """
    ip = str(ip or "")
    now = time.time() if now is None else float(now)
    if not ip:
        return False, 0
    with _lock:
        _prune(now)
        if ip in _bans:
            return True, max(1, min(RETRY_AFTER_MAX, int(round(_bans[ip] - now))))
        hits = _fails.setdefault(ip, [])
        hits.append(now)
        if len(hits) >= MAX_FAILS:
            _bans[ip] = now + BAN_SECONDS
            _fails.pop(ip, None)
            return True, BAN_SECONDS
        return False, 0


def state(ip, now=None):
    """给日志用的一行（**不含任何凭据**）。"""
    now = time.time() if now is None else float(now)
    with _lock:
        _prune(now)
        left = retry_after(ip, now)
        n = len(_fails.get(str(ip or ""), []))
    if left:
        return "封着（还有 %d 秒）" % left
    return "窗口内失败 %d 次" % n


def reset():
    """清空（**只给自检用**）。"""
    with _lock:
        _fails.clear()
        _bans.clear()
