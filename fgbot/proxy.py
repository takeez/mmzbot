#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""反向代理后面：**来源 IP 到底是谁**。

    直连：       客户端 ──────────────────→ 她（TCP 对端就是真来源）
    反代后面：   客户端 → nginx/caddy → 她（TCP 对端是 **127.0.0.1**！）

⚠️ 为什么必须做这件事：来源判定（`server.is_local` / `client_allowed`）是整套
   门禁的地基。反代一加，**所有请求的对端都变成 127.0.0.1** ——
   如果不看 `X-Forwarded-For` / `X-Real-IP`，公网来的人会被当成"本机"，
   于是面板免登录、Bearer 也给他用：**反代反而把门拆了**。

⛔ 但也**不能无条件信这两个头**：谁都能往请求里塞一个 `X-Forwarded-For: 127.0.0.1`。
   所以规矩是：

   · 只有**对端 IP 在 `panel.trustedProxies` 名单里**（= 那确实是我们自己那台反代）
     才看这两个头；
   · 看 `X-Forwarded-For` 时**从右往左走**，跳过所有"可信代理"，停在第一个不可信的
     地址上 —— 那就是客户端。为什么从右往左：反代是**追加**的
     （nginx `$proxy_add_x_forwarded_for` / caddy 默认），左边那些是**客户端自己
     塞进来的**，信不得；
   · 对端不在名单里 → 那两个头**当空气**，只认 TCP 对端（伪造头提不了权）。

默认名单只有回环（`127.0.0.1/32`、`::1/128`）：本机反代开箱即用；
反代在 Docker / 另一台机器上时，把它的地址/CIDR 填进 `panel.trustedProxies`。
⛔ **别把 `0.0.0.0/0` 填进去** —— 那等于谁说话都算数，等于没做。
"""

import ipaddress
import threading

from . import base

# 默认只信本机（同机反代就是 127.0.0.1 → 她）。
DEFAULT_TRUSTED = ("127.0.0.1/32", "::1/128")

_cache_lock = threading.Lock()
_cache_key = None
_cache_nets = None


def normalize(ip):
    """把一个 IP 字符串收拾成标准形状（IPv4-mapped IPv6 还原成 IPv4）。

    `::ffff:127.0.0.1` 和 `127.0.0.1` 是**同一个对端**（Windows / 双栈常见），
    名单里写 `127.0.0.1/32` 时必须也认它 —— 否则本机反代会被漏判成"不可信"。
    """
    s = str(ip or "").strip()
    if not s:
        return ""
    if s.startswith("[") and "]" in s:          # `[::1]:1234` 这种形状
        s = s[1:s.index("]")]
    s = s.split("%", 1)[0]                      # 去 IPv6 scope id
    try:
        a = ipaddress.ip_address(s)
    except ValueError:
        return s.lower()
    if a.version == 6 and a.ipv4_mapped is not None:
        a = a.ipv4_mapped
    return str(a)


def parse_trusted(raw):
    """把 `panel.trustedProxies` 解析成 `[ip_network, …]`（**纯函数**，好自检）。

    · 键缺省 / 不是列表 / 是字符串以外的怪东西 → **默认只信回环**；
    · 列表里的空项 / 写错的项**跳过**（⛔ 写错一项不等于"全信"）；
    · 显式写 `[]` → **一个都不信**（用户有权这么做，但这时候反代后面人人都是 127.0.0.1，
      等于所有人都是本机 —— 文档里会警告）。
    """
    if raw is None:
        raw = DEFAULT_TRUSTED
    elif isinstance(raw, str):
        raw = [raw]
    elif isinstance(raw, (list, tuple)):
        raw = list(raw)
    else:
        raw = DEFAULT_TRUSTED
    nets = []
    for item in raw:
        s = str(item or "").strip()
        if not s:
            continue
        try:
            nets.append(ipaddress.ip_network(s, strict=False))
        except ValueError:
            continue
    return nets


def trusted_networks(raw=None):
    """`panel.trustedProxies` 的现算值（带一层缓存，配置热重载也跟着变）。"""
    global _cache_key, _cache_nets
    if raw is None:
        raw = (base.cfg().get("panel") or {}).get("trustedProxies")
    try:
        key = tuple(raw) if isinstance(raw, (list, tuple)) else repr(raw)
    except Exception:
        key = repr(raw)
    with _cache_lock:
        if _cache_key == key and _cache_nets is not None:
            return _cache_nets
    nets = parse_trusted(raw)
    with _cache_lock:
        _cache_key = key
        _cache_nets = nets
    return nets


def is_trusted(ip, nets):
    """这个地址是不是名单里的反代？解析不了的地址**一律不可信**。"""
    s = normalize(ip)
    if not s:
        return False
    try:
        a = ipaddress.ip_address(s)
    except ValueError:
        return False
    for n in nets or ():
        try:
            if a.version == n.version and a in n:
                return True
        except TypeError:
            continue
    return False


def _xff_chain(raw):
    out = []
    for part in str(raw or "").split(","):
        s = normalize(part)
        if s:
            out.append(s)
    return out


def resolve(peer, headers, nets=None):
    """这条请求的**真来源 IP**（`headers` 只要有个 `.get` 就行）。

    `peer` = TCP 对端（`self.client_address[0]`）。
    `nets` 不传就按配置现算（`panel.trustedProxies`）。
    """
    peer = normalize(peer)
    if nets is None:
        nets = trusted_networks()
    if not is_trusted(peer, nets):
        # ⛔ 不是我们那台反代：它说什么都当空气（伪造头在这里被丢掉）
        return peer
    chain = _xff_chain(headers.get("X-Forwarded-For") if headers else "")
    cur = peer
    i = len(chain) - 1
    # 从右往左：只要"当前这一跳"仍在可信名单里，就往左走一跳；停在第一个不可信的地址。
    while i >= 0 and is_trusted(cur, nets):
        cur = chain[i]
        i -= 1
    if chain:
        return cur
    xri = headers.get("X-Real-IP") if headers else ""
    if xri:
        return normalize(xri)
    return peer


def is_https(peer, headers, nets=None):
    """这条请求**对客户端**来说是不是 HTTPS（决定 cookie 加不加 `Secure`）。

    只看可信反代给的 `X-Forwarded-Proto`；直连永远是明文 HTTP（本项目不做 TLS）。
    """
    if nets is None:
        nets = trusted_networks()
    if not is_trusted(peer, nets):
        return False
    proto = ""
    if headers:
        proto = str(headers.get("X-Forwarded-Proto") or "").split(",")[0]
    return proto.strip().lower() == "https"
