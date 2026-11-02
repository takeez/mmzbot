#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTTP 服务：**NapCat 从这里推进来，她的回答从这里发出去**。

    POST /     ← NapCat 上报（OneBot11 事件）。这是唯一的"入口"。
    GET  /status → 一行 JSON（活着没、跑了多久、端口）—— App / 网页面板 / 看门狗要看
    POST /api  → 控制面（restart + agent 层那些动作，见下）+ **电脑发来的两条**：
                 `announce`（播报）与 `status.push`（心跳）
    GET  /     → 一句人话，告诉我"我在跑"（浏览器里能看见）
                 ⚠️ 2026-10-04 起：**只给本机 + 局域网** —— 公网来源一律
                 **404 + 空正文**（外面不该看到任何东西；本机 / 局域网一个字不变）
    GET  /panel → 网页面板（浏览器控制她；页面本体在 fgbot/panel.py。
                  ⚠️ **页面里不再有任何 token** —— 本机 / 局域网打开后要你手输一次，
                  存在浏览器 localStorage 里；见 A5）
    GET  /login → 登录页（**公网 / 反代后面**那条路；见「远程面板」那一段）
    POST /login → 交口令（表单或 JSON）→ 验过发 `Set-Cookie: fgPanelSession=…`
    GET/POST /logout → 退出登录（服务端**立刻**删掉这条会话）
    GET  /onboard → 设置页的现算值（每块状态 + 「能不能跑」检查表）。
                  ⚠️ **只有主人**能拿（token 已打码）；远程开面板靠 `panel.allowRemote`。

═══ 鉴权（2026-10-03 互联网改造那一批，契约见三份只读文档）═══

| 凭据 | 谁用 | 认成谁 |
|---|---|---|
| `bot.napcatToken`（= 旧 `bot.token`，缺了自动回退） | NapCat 推上报（`POST /`）、主人自己那台（**仅本机 / 局域网 + `role: owner`**）、老 `X-Signature: sha1=` | **主人** |
| `users.json` 里每条的 `token` | 朋友的电脑调 `POST /api`（新签名 / 老签名 / Bearer） | **那条记录的人** |

- **新签名**：`X-FG-Signature: sha256=<hex>` + `X-FG-Timestamp` + `X-FG-Nonce`
  （`fgsig.py`，内容 = `时间戳 + "\n" + nonce + "\n" + 正文原始字节`，窗口 ±120 秒，
   nonce 内存去重）。
- **老头** `X-Signature: sha1=…` **原样继续接受**（老契约一个字节不动，NapCat 上报不许动）。
- **`Authorization: Bearer`**：**只对本机 + 局域网**接受（A4②）——公网来源一律 403 空正文
  （明文 HTTP 下局域网浏览器算不了 HMAC，所以面板/App 这条路必须留着，但要挡住公网）。
  ⚠️ 2026-10-31 起**公网 / 反代后面不再认 Bearer**（连 `panel.allowRemote` 开着也不认）：
  那条路改成 `/login` → `Set-Cookie: fgPanelSession=…`，见下面「远程面板」。
- ⚠️ **2026-10-04（第四批）：推送那两条只认「每人一把」的用户令牌**（见 `PUSH_ACTIONS`）：
  `announce`（含别名「播报」/「broadcast」）与 `status.push` —— 凭据必须是 `users.json`
  里某一条记录的那把 token；**共享那把**（`bot.token` / `napcatToken`）来推 →
  **403 空正文** + 照 D2 计一次失败。⛔ 别的动作一个字没动：`POST /`（NapCat 上报）照旧
  只认共享那把；控制面 / 面板动作共享那把照旧认。
- **`token` 为空 → 拒绝服务**（不再"空就放行"，A4①）：启动时不监听，运行中被清空则
  `/` 和 `/api` 一律 403 空正文并留一行日志。
- 鉴权没过 → **403 + 空正文**（C4 定稿；不回显 nonce / timestamp）。
- 失败限流（D2）：**每 IP 5 分钟 10 次鉴权失败 → 封 15 分钟 → 429 + `Retry-After` + 空正文**；
  正常请求不算失败；**本机 / 局域网来源永不封**。
- 请求体上限：`/api` **1 MB → 413 + 空正文**（D2）。
- **并发上限**（2026-10-03 加）：`config.json` 的 `maxConcurrent`（默认 **32**）；
  同时在处理的请求超过上限 → **503 + 空正文 + `Retry-After`**（见 `GatedServer`）。
  503 是**叫对方退避**，不是"让她排队" —— 排队只会把她的回复一起拖死。

═══ 公网入口（2026-10-03 加的那颗开关）═══

`bot.control.allowPublic`（布尔，`config.json` 或手机本地 `local-config.json` 都认，
按 `base._deep_merge` 那套分层）—— **默认关**：

| 这颗键 | 公网来源能到哪 |
|---|---|
| **关**（缺省 / false，= 从前一模一样） | 哪都到不了：`/api`、`/panel`、`/status`、`POST /` 一律 **403 空正文** |
| **开**（true） | **只有 `POST /api`** 这一条路放到**鉴权那一步**；`/panel`、`/status`、`POST /` 一个字都不放 |

- 放开的是"**能来验凭据**"，不是"谁来都行"：公网来源必须带**有效凭据** ——
  **新签名** `X-FG-Signature` 或**老签名** `X-Signature: sha1=`，而且只能用
  `users.json` 里**每人一把**的 token（共享那把 `napcatToken` **公网一律不认**）；
  没凭据 / 签错 → **403 空正文**，并照 D2 **计一次鉴权失败**（5 分钟 10 次 → 429）。
- 就算凭据是对的，公网来源也**只许调那两个动作**（`PUBLIC_ACTIONS`）：
  `status.push`（心跳）与 `announce`（播报）。别的动作 —— 重启她、清对话记忆、
  改/删模型 API、改记忆、用户管理 —— 从公网一律 **403 空正文**
  （那些是"手机上自己人干的活"，开公网不等于把控制面一起开出去）。
- **`Bearer` 仍然只给本机 / 局域网**（A4②）：明文 HTTP 下公网那把 token 会被
  中间人拿走、还能重放，所以公网这条路只认 HMAC 签名。
- 公网来源**每一跳都写一行日志**（含来源 IP，**不记请求内容**）；被拒也写。
- ⛔ `POST /`（**NapCat 上报**，它就在同一台手机上）**只许本机 / 局域网**；
  ⛔ `/panel` / `/status`（面板里有用户管理）**只许本机 + `bot.control.allowIps`**。
- ⛔ **根路径 `GET /`（信息类入口）也只许本机 + `bot.control.allowIps`**（2026-10-04 收的）：
  公网来源 **404 + 空正文**（用 404 不用 403 —— 那更"这里什么都没有"）；本机 / 局域网
  照旧看得见那行字（用户平时在电脑上开它）。
- ⛔ **响应头里不报服务器指纹**（2026-10-04 一起加固的）：标准库默认会加
  `Server: BaseHTTP/0.6 Python/3.x`，端口一映射出去就等于白送一条"这是 Python
  http.server"的线索 —— 现在把 `Server` 头**整个摘掉**，只留 HTTP/1.1 必须的 `Date`。
- 这颗键**关掉就立刻回到"公网一律 403"**（配置文件热重载，不用重启进程）。
  ⚠️ 只认**真正的布尔** `true` / `false`：写成 `"true"`、`1`、`"yes"` 这种**一律当关**
     （安全开关，宁可不生效也不许手滑打错就开出去）。

═══ 远程面板（`panel.allowRemote` + 登录会话，2026-10-31）═══

用户定的部署目标：面板要能从**公网 / 反代后面**用，但**必须登录**、不能裸奔。
本机 / 局域网那条老路**一个字节没变**（打开面板 → 浏览器里粘一次令牌 → localStorage）。

| 来源 | `/panel` | `/status` `/settings` `/providers` `/onboard` | `POST /api` |
|---|---|---|---|
| 本机 / 局域网 | 直接给页面（老路） | 要有效凭据（Bearer / 签名，老路） | 老路不变 |
| 公网 + `allowRemote` 关 | **403 空正文**（连"有面板"都不说） | 403 空正文 | 只有 `allowPublic` 那条签名路 |
| 公网 + `allowRemote` 开、没登录 | **200 登录页**（不是白屏也不是面板） | 403 空正文 | 403 空正文 |
| 公网 + `allowRemote` 开、已登录 | 200 面板（页面里**没有令牌**） | 200（会话 = **主人**） | 200（主人身份） |

- 登录：`POST /login`，字段 `password`（表单或 JSON 都认）。口令 = **共享令牌**
  （`bot.napcat_token()`，面板「看共享令牌」那把）。⛔ 用户表里朋友的令牌**登不进来**
  （面板是主人的东西；朋友那台走签名调 `/api` 那套）。
- 会话：`Set-Cookie: fgPanelSession=<43 字符随机串>; Path=/; HttpOnly; SameSite=Lax`
  （HTTPS 反代后面再加 `Secure`）。**服务端只存它的 sha256**，表在内存里 ——
  重启进程 = 全部失效。寿命 `panel.sessionHours`（默认 12 小时）+
  `panel.sessionIdleMinutes`（默认 120 分钟没动就失效）。
- 退出：`GET` / `POST /logout` → 服务端把那条会话**从内存里删掉** + 下发 `Max-Age=0`
  的 cookie。⚠️ 退化不到"只是浏览器那头忘了"：**原 cookie 再拿来是 403**。
- 防爆破：同一个 IP **10 分钟窗口错 `panel.loginMaxFails`（默认 5）次 →
  冷却 `panel.loginCooldownSeconds`（默认 300 秒）**，冷却期里**正确口令也不收**
  （429 + `Retry-After`）。日志只写来源 IP + 原因，⛔ **输入内容一个字节不落**。
- 防 CSRF：走 cookie 的请求，**非 GET 必须带 `X-FG-Panel: 1`**（面板 JS 每条都带）；
  跨站表单设不了自定义头，再加上 `SameSite=Lax`，两道。
- ⛔ **不做自己的 TLS**：远程一定放在 HTTPS 反代后面（`docs/reverse-proxy.md`）。

═══ 反代后面的来源 IP（`panel.trustedProxies`）═══

反代一加，TCP 对端全是 127.0.0.1 —— 不看头就会把公网当本机（**等于门没锁**）。
所以：只有**对端在 `panel.trustedProxies` 名单里**才认 `X-Forwarded-For` /
`X-Real-IP`；`X-Forwarded-For` **从右往左**走、跳过可信代理，停在第一个不可信地址。
默认名单只有回环（同机反代开箱即用）；反代在 Docker / 另一台机器上时把它的
地址/CIDR 填进去（⛔ 别填 `0.0.0.0/0`）。对端不在名单里 → 那两个头当空气，
**伪造的 `X-Forwarded-For: 127.0.0.1` 提不了权**（自检里钉着）。细节在 `fgbot/proxy.py`。

⚠️ **这个文件不是 agent**，别把"该怎么想、该不该回、怎么说话"写进来 ——
   那些全在 agent 层（见「项目约定」）。这里只做搬运和鉴权。

═══ 两个不能忘的坑 ═══

① **读请求体要自己处理 chunked**：NapCat 用的是 `Transfer-Encoding: chunked`，
   标准库的 `Content-Length` 读法会拿到空 body（踩过）。
② **鉴权有两种形式**：NapCat 可以配 `X-Signature: sha1=<hmac>`，也可以走
   `Authorization: Bearer <token>`。两种都要认 —— App / 网页面板用的是后者。
"""

import hashlib
import hmac
import ipaddress
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from . import (agent, base, files, fgsig, im, llm, loginpage, napcat, onboard, panel,
               proxy, ratelimit, settings, statuscache, users, websession)

_STARTED = time.monotonic()

# D2：公网入口的请求体上限。`/api` 1 MB（契约数字）；NapCat 那条路放宽到 8 MB
# （它只在本机来，8 MB 已经远超任何一条真上报；上限只是"别让人把内存喂爆"）。
MAX_API_BODY = 1024 * 1024
MAX_NAPCAT_BODY = 8 * 1024 * 1024
# 登录那个表单只有两个字段（口令 + next），4 KB 已经离谱地宽了。
MAX_LOGIN_BODY = 4 * 1024

# ── 并发闸────────────────────────────────────────────
#
# 为什么要有它：`ThreadingHTTPServer` **每个请求开一条线程、一条上限都没有** ——
# 端口一旦映射到公网，任何人拿几百条并发连接就能把它撑死（线程一多，内存和调度
# 先垮，**她自己那条消息也跟着排不上队**）。所以要在**还没开线程的那一步**挡住。
#
# 规矩（和电脑侧讲好的那套一致）：
#   · 满了 → **503 + 空正文 + `Retry-After`**（对方照 503 退避，别原地重试）；
#   · **正常请求一个字都不改**：没满就照旧一路走到底；
#   · **不泄漏名额**：名额在"这条请求交出去"时拿、在"这条请求的线程干完"时还；
#     连 `t.start()` 抛异常那条路都还（否则一次异常就永久少一个名额）。
#   · 上限从 `config.json` 的 `maxConcurrent` 读（**改了要重启**才生效）。
DEFAULT_MAX_CONCURRENT = 32
DEFAULT_RETRY_AFTER = 1


def max_concurrent_cfg():
    """`config.json` 的 `maxConcurrent`（读不出来 / 不是数就回默认 32）。"""
    try:
        n = int(base.cfg().get("maxConcurrent") or DEFAULT_MAX_CONCURRENT)
    except Exception:
        return DEFAULT_MAX_CONCURRENT
    return n if n >= 1 else DEFAULT_MAX_CONCURRENT


class GatedServer(ThreadingHTTPServer):
    """带并发闸的 `ThreadingHTTPServer`。

    ⚠️ **线程模型没改**（还是一个请求一条线程、照旧 `daemon_threads`）——
       只在外头套了一道"最多几条同时在处理"的门。满了的那条请求**根本不进 Handler**：
       直接在 accept 那条线程上回 503 然后把连接关掉。
    """

    daemon_threads = True

    # listen 的 backlog。标准库默认只有 5 —— 并发一上来，多出来的连接会**在
    # 还没被 accept 的时候就被内核丢掉**（客户端看到 connection refused，
    # 而不是我们要的 503）。既然上面已经有并发闸了，backlog 就得够它把
    # "超限" 一条条 accept 进来、回完 503 再关。
    request_queue_size = 64

    def __init__(self, addr, handler, max_concurrent=DEFAULT_MAX_CONCURRENT,
                 retry_after=DEFAULT_RETRY_AFTER):
        self.max_concurrent = max(1, int(max_concurrent or DEFAULT_MAX_CONCURRENT))
        self.retry_after = max(0, int(retry_after or 0))
        self._gate_lock = threading.Lock()
        self._inflight = 0
        self._rejected = 0
        self._last_reject_log = 0.0
        ThreadingHTTPServer.__init__(self, addr, handler)

    # 拿名额：满了就当场回 503（**这一步还没开线程**，所以撑不出线程风暴）
    def process_request(self, request, client_address):
        with self._gate_lock:
            if self._inflight >= self.max_concurrent:
                self._rejected += 1
                full = True
            else:
                self._inflight += 1
                full = False
        if full:
            self._reject(request, client_address)
            return
        try:
            ThreadingHTTPServer.process_request(self, request, client_address)
        except Exception:
            self._give()                     # 线程没起来也得把名额还回去
            raise

    # 这条请求干完了 → 还名额（**必须 finally**：Handler 里抛什么都得还）
    def process_request_thread(self, request, client_address):
        try:
            ThreadingHTTPServer.process_request_thread(self, request, client_address)
        finally:
            self._give()

    def _give(self):
        with self._gate_lock:
            if self._inflight > 0:
                self._inflight -= 1

    def inflight(self):
        """现在有几条在处理（自检 / 排查看）。"""
        with self._gate_lock:
            return self._inflight

    def rejected(self):
        """到现在一共挡掉几条（自检 / 排查看）。"""
        with self._gate_lock:
            return self._rejected

    def _reject(self, request, client_address):
        """并发满了：**503 + 空正文**（+ `Retry-After`），然后关掉这条连接。"""
        with self._gate_lock:
            n_rej = self._rejected
            quiet = (time.monotonic() - self._last_reject_log) < 10.0
            if not quiet:
                self._last_reject_log = time.monotonic()
        if not quiet:
            # 被刷的时候别把日志写爆 —— 10 秒最多一行，但计数一条不落
            base.log("并发满了（上限 %d）→ 回 503；到现在一共挡了 %d 条（最近这条来自 %s）"
                     % (self.max_concurrent, n_rej, client_address[0]))
        head = ("HTTP/1.1 503 Service Unavailable\r\n"
                "Content-Length: 0\r\n"
                "Connection: close\r\n")
        if self.retry_after:
            head += "Retry-After: %d\r\n" % self.retry_after
        try:
            request.sendall((head + "\r\n").encode("ascii"))
        except Exception:
            pass
        self.shutdown_request(request)


# ── 来源判定（本机 / 局域网 / 白名单）────────────────────────────────
#
# ⚠️ 改过一处**行为**：`allowIps` **留空不再等于"谁都能进"**。
#    A5 实测过：原来是 `(not allow) or (ip in allow)` → 留空 = **任何 IP 都放行**
#    （连公网来源都算"局域网"）。现在：留空 = **只认本机**；要开局域网必须写明网段，
#    而且支持 **CIDR**（`192.168.1.0/24`，原来是字符串精确相等，填网段根本匹配不上）。

def is_local(ip):
    """手机自己（127.0.0.1）—— 永远放行、**永远不封**（App / ctl 脚本走这里）。"""
    return (ip or "").strip() in ("127.0.0.1", "::1", "localhost", "::ffff:127.0.0.1")


def _ip_in(ip, net):
    """`192.168.1.101` 在 `192.168.1.0/24` 里吗（也支持直接写一个 IP）。"""
    try:
        addr = ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return False
    txt = str(net).strip()
    try:
        if "/" in txt:
            return addr in ipaddress.ip_network(txt, strict=False)
        return addr == ipaddress.ip_address(txt)
    except ValueError:
        return False


def client_allowed(ip):
    """这个来源能不能用 `/status` `/api` `/panel`（控制面）。

    本机永远放行（手机上的 App 走 127.0.0.1）；别的设备要
    `config.json` 的 `bot.control.lanEnabled` 开了**并且**命中 `allowIps`
    （网段或 IP）。**`allowIps` 留空 = 只认本机**（A5 定稿：宽松版要把
    `allowIps` 填成 `192.168.1.0/24`）。

    ⚠️ 这里**只说"是不是本机/局域网"**（限流、`Bearer`、主人模式都看它）。
        "公网能不能进 `/api` 验凭据"是**另一颗键**：`allow_public()`。
       ⛔ 别把两者混成一个 —— 公网来源永远不是"局域网"（否则它就不计数、
         还能用 Bearer、还能当主人）。
    """
    ip = (ip or "").strip()
    if is_local(ip):
        return True
    c = base.bot_cfg().get("control") or {}
    if not c.get("lanEnabled"):
        return False
    allow = [str(x).strip() for x in (c.get("allowIps") or []) if str(x).strip()]
    if not allow:
        return False
    return any(_ip_in(ip, a) for a in allow)


def is_lan(ip):
    """本机 + 局域网白名单（**限流永不对它生效**；Bearer 也只对它开放）。"""
    return client_allowed(ip)


def allow_public():
    """`bot.control.allowPublic`：公网来源**能不能走到 `/api` 的鉴权那一步**。
    ⚠️ **默认关**（配置里没有这颗键 = 和从前一模一样：公网来源一律 403 空正文）。
       打开之后**只有 `POST /api` 这一条路**对公网放开，而且放开的只是
       "能来验凭据" —— **没凭据 / 签错照样 403 空正文**，并照 D2 计一次失败。
       ⛔ `POST /`（NapCat 上报）、`/panel`、`/status` 一个字都不放（它们在
          各自那条路上用 `client_allowed()` 单独挡，**不走这颗键**）。
    ⛔ 它**不是** `is_lan()`：公网来源在限流那一层照常计数、照常封，
       也不许用 `Bearer`（那条明文凭据只给本机 / 局域网），更认不成主人。

    ⚠️ **只认真正的布尔 `true`**（`v is True`）：写成 `"true"` / `1` / `"yes"`
       这种**一律当关** —— 这是个安全开关，**宁可不生效也不许"手滑打错就开出去"**
       （错的那一头必须是"朋友连不上"，不是"公网谁都能来试"）。
    """
    c = base.bot_cfg().get("control") or {}
    return c.get("allowPublic") is True


def allow_legacy_sha1():
    """`bot.control.allowLegacySha1`：老签名 `X-Signature: sha1=` 许不许用。

    老签名不带时间戳、不带 nonce（只签正文）—— 公网上抓一次包就能无限重放。
    默认 **false**：新客户端走 `X-FG-Signature`（±120 秒 + nonce）。
    ⚠️ `POST /`（NapCat 上报）那条路不受这颗键管：它只许本机 / 局域网，
       而且 NapCat 的契约就是 sha1，动了会把它弄断。
    """
    c = base.bot_cfg().get("control") or {}
    return c.get("allowLegacySha1") is True


def panel_remote():
    """`panel.allowRemote`：公网来源**能不能走到网页面板那扇门**（默认关）。

    默认关 = 和从前一模一样（公网来源连 `/panel` 都打不开，403 空正文）。
    开 = 公网来源可以拿到**登录页**；登录过（有效的 `fgPanelSession` cookie）才给
    **面板页面 + 那几个 GET 数据**，而且会话身份 = **主人**（面板本来就是主人的东西）。
    ⚠️ **没登录不等于"能给页面"**：页面里没有任何凭据，没会话就是一张登录页。
    ⛔ `POST /api` 不走这颗键：公网那条签名路归 `bot.control.allowPublic`；
       面板登录出来的会话是**另一条路**（见 `_handle_api` 里 `_via_session` 那几处）。
    ⚠️ 只认真正的布尔 `true`（和 `allowPublic` 同一个口径）。
    ⛔ 这个项目**不自己做 TLS**：远程一定要放在反向代理（HTTPS）后面 ——
       cookie 不带 Secure 时是明文走的（README / docs/reverse-proxy.md 里写着）。
    """
    p = base.cfg().get("panel") or {}
    return p.get("allowRemote") is True


def panel_allowed(ip):
    """这个来源能不能打开面板 / 看那几个 GET 数据（登录仍然另算）。

    本机 / 局域网照旧（`client_allowed()`）；公网只在 `panel.allowRemote` 开着时放行。
    ⚠️ 放行的是"能走到登录页"；有没有登录看 `Handler._ensure_session()`。
    """
    return client_allowed(ip) or panel_remote()


# 公网来源**只许调这几个动作**（`allowPublic` 开着、签名也验过之后才看这张表）：
#   · `status.push` —— 电脑的心跳（只落盘缓存，一个模型请求都不发）；
#   · `announce` / `broadcast` / `播报` —— 播报（要她开口，走 agent 层）。
# 别的动作（restart / reset / add / use / del / test / effort / triggers /
# memory* / user.* …）都是"手机上自己人干的活"：拿一把**朋友的** token 从公网
# 就能删掉模型 API 配置、清对话记忆、反复重启她 —— 那不是"开公网"，那是把控制面
# 一起开出去。所以**公网来源调这些一律 403 空正文**（本机 / 局域网一个字不变）。
# ⚠️ 这里**不算鉴权失败**（凭据是对的）：它不该把朋友自己拖进 429 封禁里。
PUBLIC_ACTIONS = ("status.push", "announce", "broadcast", "播报")

# 推送那两条动作：**只认 `users.json` 里「每人一把」的用户令牌**。
#   · `announce` / `broadcast` / `播报`（播报）与 `status.push`（心跳）—— 电脑推上来的数据；
#   · 凭据必须是用户表里某一条记录那把 token（`_identify()` 认出来的身份 = 那条记录的 id）；
#   · **共享那把**（`bot.token` / `napcatToken`，身份 `own`）来推 → **403 空正文**，
#     并照 D2 计一次失败（本机 / 局域网照旧永不封；见 `_handle_api` 里那一步）。
# ⛔ 只有这两条受这条规矩管：`POST /`（NapCat 上报）照旧只认共享那把；控制面 / 面板动作
#    （`user.*` / `group.*` / `request.*` / `token.show` / `restart` / `reset` / `mem_*`）
#    共享那把照旧认（`role: owner` 那套语义一个字没动）。
# ⚠️ 值和上面 `PUBLIC_ACTIONS` 刚好一样，但**那是另一个口径**（"公网许调什么"）——
#    两个各写一份、别互相引用（哪天公网那条改了口径，推送这条不该被带着变）。
PUSH_ACTIONS = ("status.push", "announce", "broadcast", "播报")

# 哪些动作的响应**绝不许被浏览器 / 中间层缓存**：
#   · `token.show` —— 正文里就是那把共享令牌明文（已鉴权 + 主人那一支才拿得到）。
# ⚠️ 动作名的**唯一真相在 `agent.TOKEN_SHOW_ACTIONS`**（含中文别名）——
#    那边加一个别名，这里自动跟上，别在两处各写一份。
NO_STORE_HEADER = [("Cache-Control", "no-store")]


def _shared_token_ok(ip):
    """共享那把 token（`napcatToken`）能不能在 `/api` 上当"主人"？

    · 本机 → 能（手机上的 App / 面板：App 那把 token 是编译进 APK 的，不能废掉它）；
    · 局域网 → **要看隐藏键 `role: owner`**（用户 2026-10-03 定的"主人模式"：
      填上 = 主人自己那台走局域网、免邀请码）；
    · 公网 → 一律不认（它不是给公网用的；朋友走 `users.json` 里自己那把）。
    """
    if is_local(ip):
        return True
    if client_allowed(ip):
        return base.owner_mode()
    return False


def _candidates(ip, allow_shared=False):
    """`[(身份, token), …]`：这条请求可能是谁签的（就几个人，挨个比）。

    `allow_shared=True` 只剩**兼容签名**（没有调用方再用它）：2026-10-31 起
    公网 / 反代后面**不再走共享令牌当 Bearer**，改成 `/login` 发的会话 cookie。
    本机 / 局域网照旧（`_shared_token_ok()` 说了算）。
    """
    out = []
    if allow_shared or _shared_token_ok(ip):
        tok = base.napcat_token()
        if tok:
            out.append((users.owner_ident(), tok))
    for r, t in users.tokens():
        out.append((users.ident_of(r), t))
    return out


def _form_fields(body, ctype):
    """把登录表单解析成 dict（`application/json` 和 `application/x-www-form-urlencoded`
    都认）。⚠️ 解析失败一律回空 dict —— 上层按"没填"处理，绝不回显原文。"""
    raw = (body or b"").decode("utf-8", "replace")
    ct = str(ctype or "").lower()
    data = {}
    if "application/json" in ct:
        try:
            obj = json.loads(raw or "{}")
        except Exception:
            return {}
        return obj if isinstance(obj, dict) else {}
    if "application/x-www-form-urlencoded" in ct or "=" in raw:
        try:
            qs = parse_qs(raw, keep_blank_values=True)
        except Exception:
            qs = {}
        data = {k: (v[0] if isinstance(v, list) and v else "") for k, v in qs.items()}
    if not data and raw.strip().startswith("{"):
        # 没写 Content-Type / 写错了，但正文明显是 JSON —— 照顾 curl 用法
        try:
            obj = json.loads(raw)
        except Exception:
            return {}
        return obj if isinstance(obj, dict) else {}
    return data


def _safe_next(raw):
    """登录成功后往哪跳：**只认面板**（免得登录页变成开放重定向）。"""
    return "/panel"


def build_ctx(evt, raw_body):
    """把 NapCat 的事件拼成 agent 层要的 ctx。

    ⚠️ 这就是**接口契约**，加字段可以，改字段名要两边一起改（agent 层也在用）。
    """
    is_group = evt.get("message_type") == "group"
    uid = evt.get("user_id")
    gid = evt.get("group_id")
    raw = napcat.text_of(evt)
    return {
        "key": ("g", gid) if is_group else ("p", uid),   # 一场对话一把钥匙
        "is_group": is_group,
        "group_id": gid,
        "user_id": uid,
        "who": napcat.who_of(evt),        # 群名片（已去掉不可见控制符）
        "text": napcat.display_text(raw),  # 给人看的文本（[图片] 已替换）
        "raw": raw,                        # CQ 原文 —— 路由判断用这个
        "raw_body": raw_body,              # 原始上报体（要转发给电脑时用）
        "evt": evt,                        # 原样事件（要什么自己取）
        "images": napcat.image_refs(raw),  # 图片候选：本地路径在前，CDN 在后
        # 这条消息里的**文件**（群文件 / 私聊文件）：`[{id, name, size}]`。
        # 正文里仍然只显示 `[文件]` 占位；要真拿到文件是 `package` 工具的 fetch。
        # ⚠️ 段数组也认（老版本 NapCat 的 raw_message 里可能没有 file 段）。
        "files": (files.refs_from_raw(raw)
                  or files.refs_from_segs(evt.get("message") or [])),
        # 他**引用（回复）了哪一条**（被引用那条的 message_id；没引用就是 None）。
        # 路：引用里那张已经发出去过的图，也要让她看见
        # （历史里只剩 [图片] 占位）。取图在 images.load_quoted() 里。
        "reply_to": napcat.reply_id(evt),
        "message_id": napcat.message_id(evt),
        "at": time.time(),
    }


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    # ── 响应头里**不报服务器指纹**────────────────────
    #
    # 标准库的 `send_response()` 默认在**每条**响应上加两个头：`Server: BaseHTTP/0.6
    # Python/3.11.2` 和 `Date`。端口一映射到公网，那个 `Server` 就是白送一条"这台机器
    # 上是 Python 的 http.server"的线索（版本号都在里面）。所以这里**整个不发它**，
    # 自己发状态行 + `Date`（HTTP/1.1 的源服务器必须带 `Date`，这个留着）。
    #
    # ⚠️ 为什么改 `send_response()` 而不是只改 `server_version`：摘不干净 ——
    #    标准库在**每一条**响应上都会发它，包括 `send_error()` 那条错页（比如 HEAD → 501）。
    #    改这一个方法 = 所有出口（`_send` / `_empty` / `_json` / 错页 / 413）一起干净。
    server_version = ""
    sys_version = ""

    def version_string(self):
        return ""

    def send_response(self, code, message=None):
        self.log_request(code)
        self.send_response_only(code, message)
        self.send_header("Date", self.date_time_string())

    def log_message(self, *a):        # 别让标准库把每条请求打到 stderr
        pass

    # ── 读体：chunked 要自己拆；超上限立刻停（别喂到内存爆）───────────
    def _read_body(self, limit=MAX_API_BODY):
        """返回 `(body, 超上限了吗)`。"""
        if (self.headers.get("Transfer-Encoding") or "").lower() == "chunked":
            buf = b""
            while True:
                line = self.rfile.readline().strip()
                if not line:
                    continue
                size = int(line.split(b";")[0], 16)
                if size == 0:
                    self.rfile.readline()
                    break
                buf += self.rfile.read(size)
                self.rfile.readline()
                if limit and len(buf) > limit:
                    self.close_connection = True      # 别等它发完（D2 的原话）
                    return b"", True
            return buf, False
        n = int(self.headers.get("Content-Length") or 0)
        if limit and n > limit:
            self.close_connection = True
            return b"", True
        return (self.rfile.read(n) if n else b""), False

    # ── 会话 / 来源（每个请求开头算一次）──────────────────────────────
    def _begin(self):
        """一条请求开头：算**真来源 IP**、把上一条留的标记全清掉（keep-alive 复用）。

        ⚠️ 反代后面 TCP 对端是 127.0.0.1 —— 真来源在 `X-Forwarded-For` /
           `X-Real-IP` 里，**只信 `panel.trustedProxies` 名单里的对端**（`fgbot/proxy.py`）。
           `self.client_address[0]` 从这里往后**别再直接读**（那会把反代当本机）。
        """
        self._remote_panel = False
        self._via_session = False
        self._session_ident = None
        self._matched_token = ""
        self._ip = proxy.resolve(self.client_address[0], self.headers)
        self._session_raw = websession.raw_from_cookie(self.headers.get("Cookie"))

    def _cookie_secure(self):
        """这条响应的 cookie 加不加 `Secure`（只看可信反代给的 `X-Forwarded-Proto`）。"""
        return proxy.is_https(self.client_address[0], self.headers)

    def _ensure_session(self):
        """这条请求的登录会话（没有 / 过期 / 退出过 → `None`）。

        ⚠️ 走 cookie 的**非 GET** 必须带 `X-FG-Panel: 1`（面板 JS 每条都带）：
           跨站表单设不了自定义头，再加 `SameSite=Lax` 是双保险（防 CSRF）。
        """
        if self._session_ident is not None:
            return self._session_ident
        if not self._session_raw:
            return None
        if self.command not in ("GET", "HEAD"):
            if (self.headers.get("X-FG-Panel") or "") != "1":
                return None
        ident = websession.lookup(self._session_raw)
        if ident is None:
            return None
        self._session_ident = ident
        self._via_session = True
        return ident

    def _session_marker(self):
        """会话 id 的**日志指纹**（前 8 位 sha256）—— 从不出原值。"""
        return websession.fingerprint(self._session_raw)

    def _redirect(self, location, code=303, extra=None):
        """跳一下（登录成功 / 退出都用 303：让浏览器换成 GET）。"""
        self._send(code, b"", None, list(extra or []) + [("Location", location)])

    # ── 鉴权 ────────────────────────────────────────────────────────
    def _identify(self, body):
        """这条请求是谁？返回 `(身份, 说明)`；身份 None = 没通过（说明只进日志）。

        ⚠️ **顺序就是契约**：新签名 → 老签名 → Bearer → **登录会话 cookie**。
           带了新签名但没过，**不往下走**（不给"签名失败就换 Bearer 蒙一下"留路）。

        ⚠️ 顺手把**实际验过的那把凭据**记在 `self._matched_token` 上（返回形状一个字没动）：
           推送那两条要靠它判断"用的是用户表里那把，还是共享那把"—— 光看身份 id 分不出来
           （共享那把认出来的身份是 `users.owner_ident()`，用户表里只要有一条标着
           `主人: true`，它就会顶着那个人的 id 出现，见 `_pushed_by_user_token`）。
        """
        ip = self._ip
        cand = _candidates(ip)
        self._matched_token = ""
        sig = self.headers.get(fgsig.HEAD_SIG)
        if sig:
            ident, tok, why = fgsig.verify_new(
                sig, self.headers.get(fgsig.HEAD_TS), self.headers.get(fgsig.HEAD_NONCE),
                body, cand)
            self._matched_token = tok or ""
            return ident, why
        old = self.headers.get("X-Signature") or self.headers.get("X-Signature-Sha1")
        if old:
            if not allow_legacy_sha1():
                return None, "老签名已关（bot.control.allowLegacySha1）"
            ident, tok, why = fgsig.verify_old(old, body, cand)
            self._matched_token = tok or ""
            return ident, why
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            tok = auth[7:].strip()
            if tok:
                if not is_lan(ip):
                    return None, ("公网来源不许用 Bearer（A4②）—— 远程面板请先 /login "
                                  "拿会话 cookie")
                for ident, t in cand:
                    if hmac.compare_digest(t.encode("utf-8"), tok.encode("utf-8")):
                        self._matched_token = t
                        return ident, "Bearer（本机/局域网）"
                return None, "Bearer 那把令牌不认识"
            # Bearer 后面是空的 = 浏览器在远程模式下**没有**令牌（正常）——
            # 不在这里判死，往下走会话 cookie 那条路。
        sess = self._ensure_session()
        if sess:
            self._matched_token = ""
            return sess, "登录会话（cookie）"
        return None, "一个凭据都没带"

    def _pushed_by_user_token(self):
        """这条请求的凭据是 `users.json` 里「每人一把」那把吗（推送那两条只认它）？

        ⚠️ 为什么**不能只看 `ident["id"]`**：共享那把（`bot.token` / `napcatToken`）认出来的
           身份是 `users.owner_ident()` —— 用户表里只要有一条标着 `主人: true`（B1 说
           "有且只有一条 = 用户自己"），它就会顶着**那个人的 id** 出现，光看身份根本分不出
           "这是他电脑上那把，还是手机配置里那把共享的"。所以看的是**实际验过的凭据**
           （`self._matched_token`，`_identify()` 里填）：它得是用户表里某一条的 token，
           而且**不等于共享那把**。
        """
        tok = str(getattr(self, "_matched_token", "") or "")
        if not tok or users.find_by_token(tok) is None:
            return False
        shared = str(base.napcat_token() or "")
        return not (shared and hmac.compare_digest(shared.encode("utf-8"),
                                                   tok.encode("utf-8")))

    def _bearer(self):
        """`Authorization: Bearer <token>` 里那把 token（没有就是空串）。

        ⚠️ 只为了**认"这是哪台电脑"**（心跳缓存 key 用它的指纹）——
           绝不打印、绝不落明文（E3 的日志纪律）。
        """
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return ""

    def _cache_key(self, ident):
        """心跳缓存按谁分人存：**认得出人就用他的 id**（契约：id = 缓存键），
        认不出（不该发生，鉴权已经过了）才退回 token 指纹。"""
        uid = str((ident or {}).get("id") or "").strip()
        if uid:
            return uid
        return statuscache.cred_id(self._bearer() or base.napcat_token())

    # ── 回话的小工具 ────────────────────────────────────────────────
    def _send(self, code, body=b"", ctype=None, extra=None):
        """发一条响应。`body` 是 bytes（空 = 空正文）。"""
        self.send_response(code)
        for k, v in (extra or []):
            self.send_header(k, v)
        if ctype and body:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _empty(self, code, extra=None):
        """**空正文**的那些码：403 / 413 / 429 / 204（契约：403 不带 Content-Type）。"""
        self._send(code, b"", None, extra)

    def _json(self, obj, code=200, extra=None):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8", extra)

    def _text(self, s, code=200):
        self._send(code, s.encode("utf-8"), "text/plain; charset=utf-8")

    def _html(self, s, code=200, extra=None):
        self._send(code, s.encode("utf-8"), "text/html; charset=utf-8", extra)

    # ── GET ────────────────────────────────────────────────────────
    def do_GET(self):
        try:
            # ⚠ 面板/登录/status 这条路以前**从不重载配置**，
            #   只有"收到消息"那条路会调 maybe_reload() ——
            #   于是 `--set panel.allowRemote=true` 后面板还是 403、
            #   `--set llm.apiKey` 后 /status 还是"没有"（VM 验收时真踩到）。
            base.maybe_reload()
            self._begin()
            ip = self._ip
            path = (self.path or "/").split("?")[0].rstrip("/") or "/"
            if path == "/":
                # ⚠️ 根路径也是**信息类**入口（会回内容），所以和 /panel 一样
                #    只给本机 + `bot.control.allowIps`。公网来源一律 **404 + 空正文**
                #    （用 404 而不是 403：对外就是"这里没有任何东西"）。
                #    ⚠️ 本机 / 局域网**一个字都不变** —— 用户平时在电脑上开它。
                if not client_allowed(ip):
                    base.log("根路径：拦下一个非本机/局域网的来源 %s（公网一律 404 空正文）"
                             % ip)
                    self._empty(404)
                    return
                self._text("机魂小悦在跑。\n入口是 POST /（NapCat 上报），"
                           "状态看 GET /status。\n")
                return
            if path == "/login":
                # 登录页：公网要 `panel.allowRemote`；本机 / 局域网不需要（直接去面板）。
                if not panel_allowed(ip):
                    base.log("登录页：拦下一个非本机/局域网的来源 %s（panel.allowRemote 没开）"
                             % ip)
                    self._empty(403)
                    return
                if client_allowed(ip):
                    self._redirect("/panel", code=302)
                    return
                if self._ensure_session():
                    self._redirect("/panel", code=303)
                    return
                self._html(loginpage.render(), 200, NO_STORE_HEADER)
                return
            if path == "/logout":
                self._do_logout()
                return
            if path == "/panel":
                # ⚠️ A5 定稿：本机 / 局域网打开面板要手输一次令牌（页面里不带凭据）。
                # ⚠️ 公网 / 反代后面（`panel.allowRemote: true`）先过**登录**：
                #    没会话 → 登录页（不是 403 白屏、也不是直接进）；有会话 → 面板，
                #    页面里仍然**没有任何令牌**（凭据在 HttpOnly cookie 里）。
                if not panel_allowed(ip):
                    base.log("面板：拦下一个非本机/局域网的来源 %s" % ip)
                    self._empty(403)
                    return
                if client_allowed(ip):
                    self._html(panel.render())
                    return
                if not self._ensure_session():
                    base.log("面板：远程来源 %s 还没登录 → 给登录页" % ip)
                    self._html(loginpage.render(), 200, NO_STORE_HEADER)
                    return
                self._html(panel.render(remote=True), 200, NO_STORE_HEADER)
                return
            if not panel_allowed(ip):
                self._empty(403)
                return
            ident, why = self._identify(b"")
            if ident is None:
                base.log("GET %s 鉴权没过（%s，来源 %s）" % (path, why, ip))
                self._empty(403)
                return
            if path == "/status":
                self._json(status())
                return
            if path == "/settings":
                # 运行参数快照（面板「设置 → 运行参数 / 高级参数」）。
                # ⚠️ 和 /status 同一道门：本机 + 局域网白名单 + 有效凭据；
                #    这份里**没有任何 token / API key**。
                self._json(settings.snapshot())
                return
            if path == "/providers":
                # 提供商 / 模型目录（面板「她的大脑」「后台模型」两张卡）。
                # ⚠️ 同一道门（本机 + 局域网 + 有效凭据）。
                # ⛔ 这里的 key **一律打码**（`llm.mask`）—— 明文绝不出服务端。
                self._json(llm.providers_public())
                return
            if path == "/onboard":
                # 设置页的现算值：每块状态 + 「能不能跑」那张表。
                # ⚠️ 同一道门（面板那几个 GET）+ **只有主人**（和 token.show 同口径）——
                #    这一份里有她的 QQ 号、NapCat 地址、群号；token 只有 `****`。
                # ⛔ 响应带 `no-store`：别让浏览器/中间层把它缓存下来。
                if not ident.get("主人"):
                    base.log("初始化：%s 想看 /onboard —— 不是主人，回 403（身份 %s）"
                             % (ip, ident.get("id") or "?"))
                    self._empty(403)
                    return
                self._json(onboard.snapshot(), 200, NO_STORE_HEADER)
                return
            self._json({"ok": False, "error": "没有这个接口"}, 404)
        except Exception:
            # ⛔ 日志里**只留路径，不留查询串**：`?token=…` 那种地址（老书签 / 面板链接）
            #    一出异常就会整条进 bot.log —— 日志会被 tail、会被发出去，等于漏令牌。
            base.log_exc("GET %s" % ((self.path or "/").split("?")[0] or "/"))
            try:
                self._empty(500)     # 别让对端干等（HTTP/1.1 keep-alive 下会挂住）
            except Exception:
                pass

    # ── POST ───────────────────────────────────────────────────────
    def do_POST(self):
        try:
            base.maybe_reload()          # 同 do_GET：每个请求都先看配置动了没
            self._begin()
            ip = self._ip
            path = (self.path or "/").split("?")[0].rstrip("/")
            if path == "/login":
                self._handle_login()
                return
            if path == "/logout":
                self._do_logout()
                return
            is_api = (path == "/api")
            try:
                body, too_big = self._read_body(
                    MAX_API_BODY if is_api else MAX_NAPCAT_BODY)
            except Exception as e:
                base.log("读请求体失败：%r" % e)
                body, too_big = b"", False

            if too_big:
                # D2：超上限 → 413 + 空正文 + **立刻断开**（请求本身有问题，别退避）
                base.log("请求体超上限，回 413（%s，来源 %s）" % (path, ip))
                self._empty(413)
                return

            if is_api:
                self._handle_api(body)
                return

            # ── NapCat 上报 ──
            # ⛔ 这条路**只许本机 / 局域网**（NapCat 就在同一台手机上）：端口映射出去
            #    之后，`/api` 是**有意**开的（`bot.control.allowPublic`），这条**不是** ——
            #    公网来源一律 **403 + 空正文**，绝不对外。⚠️ `allowPublic` 管不到这里
            #    （那颗键只给 `/api`），所以这里永远只问 `client_allowed()`。
            #    ⚠️ 登录会话也**不**给 NapCat 这条路（cookie 只认证面板 / 控制面）。
            if not client_allowed(ip):
                base.log("POST /：拦下一个非本机/局域网的来源 %s（NapCat 上报只许本机，"
                         "公网一律 403）" % ip)
                self._empty(403)
                return

            # 契约 C4②：这条路**照旧一律回 204 + 空正文**（鉴权失败也只写一行日志），
            # 那是 NapCat 的既有契约，不动它。token 为空 = 拒绝服务（A4①）。
            try:
                tok = base.napcat_token()
                if not tok:
                    base.log("✗ 没有配置令牌 —— 拒绝服务（POST / 不处理）")
                    self._empty(403)
                    return
                sig = self.headers.get("X-Signature") or ""
                ok_auth = False
                if sig.lower().startswith("sha1="):
                    want = hmac.new(tok.encode(), body, hashlib.sha1).hexdigest()
                    ok_auth = hmac.compare_digest(sig[5:].strip().lower(), want)
                if not ok_auth:
                    auth = self.headers.get("Authorization") or ""
                    if auth.lower().startswith("bearer "):
                        ok_auth = hmac.compare_digest(auth[7:].strip(), tok)
                if not ok_auth:
                    base.log("鉴权失败，丢弃一条上报（config.json 的 bot.napcatToken 和 NapCat 那边对一下）")
                else:
                    # 设置页的检查表：「NapCat 连得上」除了手点「测一下」，也认"最近收到过上报"。
                    # ⚠️ 只记一个时间戳，**不记内容**（和 statuscache 一个纪律）。
                    onboard.note_napcat_event()
                    evt = json.loads(body.decode("utf-8", "replace") or "{}")
                    ptype = evt.get("post_type")
                    if ptype == "message":
                        threading.Thread(target=_on_message, args=(evt, body), daemon=True).start()
                    elif ptype == "notice":
                        threading.Thread(target=agent.on_notice, args=(evt,), daemon=True).start()
                    elif ptype == "request":
                        # 「请求」这类上报（典型：朋友把机器人拉进群）。
                        # ⚠️ 之前这里落进下面那个 else，只写一行「没处理」——
                        #    也就是**从来不应答**，用户得自己拿手机点同意。现在交给 agent 层
                        #    （和 notice 一个形状：单开一条线程，她那一层出事绝不牵连这条路）。
                        threading.Thread(target=agent.on_request, args=(evt,), daemon=True).start()
                    else:
                        base.log("收到一种没处理的上报：post_type=%r" % ptype)
            except Exception:
                base.log_exc("处理上报")
            self._empty(204)
        except Exception:
            base.log_exc("POST %s" % ((self.path or "/").split("?")[0] or "/"))

    # ── 登录 / 退出 ─────────────────────────────────────────────────
    def _handle_login(self):
        """`POST /login`：验口令 → 发会话 cookie。

        四条纪律（用户点名要的）：
          · 只认**共享令牌**（主人那把）；朋友的令牌登不进来；
          · 口令错 = **一句人话 + 401**，⛔ 不回显输入、日志一个字节不落；
          · 同一个 IP 错太多次 → **冷却**（429 + `Retry-After`），冷却期里
            **正确口令也不收**（登录页不能当口令测速器）；
          · cookie `HttpOnly`（JS 读不到）；服务端只存它的 sha256。
        """
        ip = self._ip
        try:
            if not panel_allowed(ip):
                base.log("登录：拦下一个非本机/局域网的来源 %s（panel.allowRemote 没开）"
                         % ip)
                self._empty(403)
                return
            left = websession.login_blocked(ip)
            if left:
                base.log("登录：%s 还在冷却期（还有 %d 秒），回 429" % (ip, left))
                self._html(loginpage.render(
                    notice="试得太多次了，请 %d 秒后再来。" % left),
                    429, NO_STORE_HEADER + [("Retry-After", str(left))])
                return
            try:
                body, too_big = self._read_body(MAX_LOGIN_BODY)
            except Exception as e:
                base.log("登录：读请求体失败：%r" % e)
                self._empty(400)
                return
            if too_big:
                base.log("登录：请求体超上限，回 413（来源 %s）" % ip)
                self._empty(413)
                return
            fields = _form_fields(body, self.headers.get("Content-Type"))
            pw = str(fields.get("password") or fields.get("口令") or "").strip()
            if not pw:
                # 空的**不算**一次失败（用户只是没填）；也不回显任何东西。
                self._html(loginpage.render(error="口令不能为空。"), 400, NO_STORE_HEADER)
                return
            want = str(base.napcat_token() or "")
            if not want:
                base.log("登录：这台机器没有配置共享令牌 —— 登录不可用")
                self._html(loginpage.render(error="这台机器人还没配置令牌，登录用不了。"),
                           503, NO_STORE_HEADER)
                return
            if not hmac.compare_digest(pw.encode("utf-8"), want.encode("utf-8")):
                blocked, secs = websession.login_fail(ip)
                if blocked:
                    base.log("登录失败：来源 %s 口令不对 → **冷却 %d 秒**（不记输入）"
                             % (ip, secs))
                    self._html(loginpage.render(
                        notice="试得太多次了，请 %d 秒后再来。" % secs),
                        429, NO_STORE_HEADER + [("Retry-After", str(secs))])
                    return
                base.log("登录失败：来源 %s 口令不对（%s；不记输入）"
                         % (ip, websession.login_state(ip)))
                self._html(loginpage.render(error="口令不对。再试一次。"), 401,
                           NO_STORE_HEADER)
                return
            # ── 验过了：发会话 ──
            websession.login_ok(ip)
            ident = {k: v for k, v in users.owner_ident().items() if k != "token"}
            ident["主人"] = True
            raw = websession.new(ident)
            secure = self._cookie_secure()
            base.log("登录成功：来源 %s（会话已发；%s；不记 cookie）"
                     % (ip, "HTTPS" if secure else "HTTP"))
            self._redirect(_safe_next(fields.get("next")),
                           extra=[("Set-Cookie",
                                   websession.cookie_header(
                                       raw, websession.session_seconds(), secure))])
        except Exception:
            base.log_exc("登录")
            self._empty(500)

    def _do_logout(self):
        """退出登录：**服务端删会话** + 让浏览器把 cookie 清掉。

        ⚠️ 必须真的从表里删（不是只下发 `Max-Age=0`）：原 cookie 再拿来要是 403。
        """
        try:
            ip = self._ip
            gone = websession.revoke(self._session_raw) if self._session_raw else False
            base.log("退出登录：来源 %s（%s；会话指纹 %s；不记 cookie）"
                     % (ip, "删掉一条会话" if gone else "本来就没有会话",
                        self._session_marker()))
            self._redirect("/login", extra=[("Set-Cookie", websession.cookie_header(
                "", 0, self._cookie_secure()))])
        except Exception:
            base.log_exc("退出登录")
            self._redirect("/login")

    def _handle_api(self, body):
        """控制面。**只放运维动作 + 电脑那两条入站**，agent 相关的一律交给 agent 层。

        入站两条：
          · `announce` —— 播报（要她开口，所以在 agent 层）；
          · `status.push` —— **电脑的心跳**：只落盘缓存、**一个模型请求都不发**，
            所以就在这一层收（见 `_handle_status_push`）。

        这里的四道闸（顺序就是契约顺序）：
          ① 限流（封着 → 429 + Retry-After + 空正文；**本机/局域网永不封**）
          ② 来源（本机 + `bot.control.allowIps`；公网 → 403 空正文）
             ⚠️ 2026-10-03 起多了 `bot.control.allowPublic`：**开着就只把这条路
                放到"鉴权那一步"**（凭据不对照样 403 + 计一次失败），
                关着 = 和从前一模一样。`POST /` / `/panel` / `/status` 不受它影响。
          ③ 鉴权（新签名 / 老签名 / Bearer；失败 → **403 空正文** + 记一次失败）
             ⚠️ 公网来源**只认签名**（新签名 / 老 sha1），`Bearer` 只给本机/局域网。
          ④ 没配 token → 拒绝服务（403 空正文）
          ⑤ **推送那两条**（`PUSH_ACTIONS`）只认「每人一把」的用户令牌 ——
             共享那把来推 → 403 空正文 + 计一次失败（2026-10-04 第四批；别的动作不受影响）
          ⑥ **控制面那些动作只有主人能调**（2026-10-05 加）：`restart` 在这层挡，
             `reset` / `add` / `use` / `del` / `test` / `effort` / `triggers` /
             `memory`·`mem_*` / `mode` 在 `agent.on_api` 挡（`agent.OWNER_ONLY_ACTIONS`）——
             不是主人一律 **403 空正文**（和 `user.*` 同一个口径）。
             ⚠️ 面板 / 共享令牌走的是**主人身份**（本机 / 局域网），所以面板照旧能用。
           ⑦ **登录会话**（2026-10-31）：远程来源走 `/login` 拿到的 `fgPanelSession`
              cookie → 身份 = 主人，`/api` 控制面动作放行（`PUBLIC_ACTIONS` 那道闸跳过）。
              ⚠️ 推送那两条**不跳过**（它们仍只认用户表里那把，见⑤）—— 会话是从共享令牌
              换来的，而推送的规矩是"不认共享令牌"。
        """
        ip = self._ip
        try:
            left = ratelimit.retry_after(ip)
            if left:
                base.log("限流：%s 还在封禁期（还有 %d 秒），回 429" % (ip, left))
                self._empty(429, [("Retry-After", str(left))])
                return
            session = self._ensure_session()
            if not client_allowed(ip):
                # 公网来源：默认一律 403（一个字节的正文都不回）；开了那颗键才放它
                # 走到下面鉴权那一步，并且**每跳都留一行日志**（来源 IP，不记内容）。
                if session:
                    # `/login` 拿到的会话 = 主人，远程面板的 `/api` 走这条。
                    base.log("控制面：远程登录会话（来源 %s）进来 —— 身份 = 主人" % ip)
                elif not allow_public():
                    base.log("控制面：拦下一个公网来源 %s（bot.control.allowPublic 没开，"
                             "公网一律 403）" % ip)
                    self._empty(403)
                    return
                else:
                    base.log("控制面：公网来源 %s 进来（allowPublic 开着）—— 下一步只看凭据"
                             "（新签名 / 老 sha1；Bearer 不给公网）" % ip)
            if not (base.napcat_token() or users.tokens()):
                base.log("✗ 没有任何令牌（napcatToken / 用户表都空）—— 拒绝服务")
                self._empty(403)
                return
            ident, why = self._identify(body)
            if ident is None:
                # 「正常请求不算失败」：只有走到这里（鉴权没过）才计数；
                # 「本机 / 局域网来源永不封」：自己人写错 token 只会 403，不会被封。
                if not is_lan(ip):
                    now_banned, secs = ratelimit.fail(ip)
                    base.log("鉴权没过（%s，来源 %s）：%s"
                             % (why, ip, ("已封 %d 秒" % secs) if now_banned
                                else ratelimit.state(ip)))
                    if now_banned:
                        self._empty(429, [("Retry-After", str(secs))])
                        return
                else:
                    base.log("鉴权没过（%s，来源 %s —— 本机/局域网，不计数）" % (why, ip))
                self._empty(403)
                return
            req = json.loads(body.decode("utf-8", "replace") or "{}")
            act = (req.get("action") or "").strip().lower()
            # 公网来源**只许那两条**（见 PUBLIC_ACTIONS）：控制面那些动作
            # （重启/清记忆/删模型 API/改记忆…）从公网一律 403 空正文。
            # ⚠️ **登录会话**那条路是例外 —— 会话身份 = 主人（`/login` 验过
            #    共享令牌才发的），远程面板的 `/api` 要能调控制面。公网签名那条路
            #    （`allowPublic`）一个字没松，仍然只放那两条。
            if (not is_lan(ip)) and act not in PUBLIC_ACTIONS and not self._via_session:
                base.log("控制面：公网来源 %s 想调 %r —— 不在公网白名单里，回 403"
                         "（公网只放 %s）" % (ip, act, "、".join(PUBLIC_ACTIONS)))
                self._empty(403)
                return
            # ── （第四批）：推送那两条**只认「每人一把」的用户令牌** ──
            #    `announce`（含别名「播报」/「broadcast」）与 `status.push` 是**电脑推上来的
            #    数据**：凭据必须是 `users.json` 里某一条记录的那把 token（身份 = 那条的 id）。
            #    **共享那把**（`bot.token` / `napcatToken`）来推 → **403 空正文**，
            #    并照 D2 那套**计一次失败**（本机 / 局域网照旧永不封）。
            #    ⛔ 只有这两条走这道闸：`POST /`（NapCat 上报）与控制面 / 面板动作一个字没动
            #       （共享那把照旧认；`role: owner` 语义照旧）。
            if act in PUSH_ACTIONS and not self._pushed_by_user_token():
                base.log("推送 %r：凭据不是用户表里那把（身份 %s，来源 %s）—— 推送只认"
                         "「每人一把」的用户令牌，**不认共享令牌** → 403 空正文"
                         % (act, ident.get("id") or "?", ip))
                if not is_lan(ip):
                    now_banned, secs = ratelimit.fail(ip)
                    if now_banned:
                        base.log("限流：%s 推送用错凭据已到线 —— 封 %d 秒，回 429"
                                 % (ip, secs))
                        self._empty(429, [("Retry-After", str(secs))])
                        return
                self._empty(403)
                return
            if act == "status.push":
                self._handle_status_push(req, ident)
                return
            if act == "restart":
                # ⚠️ （"需要只有我能调"）：重启她**只有主人**能调
                #    （和 `user.*` / `group.*` / `request.*` / `token.show` 同一个口径：
                #    不是主人 → **403 空正文**）。从前本机 / 局域网任何一把有用户令牌的人
                #    都能让她重启。⚠️ `agent.on_api` 里那条 `重启` 走的是同一道闸
                #    （`agent.OWNER_ONLY_ACTIONS`）；动作名 / 返回结构一个字都没动。
                if not ident.get("主人"):
                    base.log("控制面：%r 被拒（不是主人，身份 %s）"
                             % (act, ident.get("id") or "?"))
                    self._empty(403)
                    return
                # 她自己重启不了自己（进程得由 Termux 那边重新拉）——只写一个请求文件，
                # 看门狗（tools/bot-watchdog-v2.sh）看到就把她杀了重拉。
                with open(base.RESTART_PATH, "w", encoding="utf-8") as f:
                    f.write("restart")
                msg = "已请求重启 —— 看门狗最多 1 分钟内把她拉起来"
                base.log("控制面：%s" % msg)
                self._json({"ok": True, "message": msg, "status": status()})
                return
            # ⚠️ 留给 agent 层：网页面板和 App 还会发这些动作 ——
            #    reset（清对话记忆）、add/use/del/test（管 API 配置，老 App 还在用）、
            #    providers.*（提供商 / 模型目录 / 后台模型，新面板走这套）、
            #    user.*（用户管理，**只有主人能调**，B6）、
            #    token.show（看共享令牌，**只有主人能调**；响应里带凭据明文 → 加 no-store）。
            out = agent.on_api(act, req, ident)
            if out is agent.FORBIDDEN:
                # B6：用户管理这类动作**只有主人**能调；别人一律 403 空正文
                base.log("控制面：%r 被拒（不是主人，身份 %s）" % (act, ident.get("id") or "?"))
                self._empty(403)
                return
            if out is None:
                self._json({"ok": False, "error": "agent 层还没实现这个动作：%r" % act}, 501)
            else:
                # ⚠️ `token.show` 那条响应**正文里就是那把共享令牌** —— 绝不许被
                #    浏览器 / 中间层缓存（拿到手的人不用再登录）。别的动作照旧不带这个头。
                extra = NO_STORE_HEADER if act in agent.TOKEN_SHOW_ACTIONS else None
                self._json(out, 200, extra)
        except Exception as e:
            base.log_exc("控制面")
            self._json({"ok": False, "error": repr(e)}, 500)

    def _handle_status_push(self, req, ident=None):
        """电脑的一跳心跳（`action = "status.push"`）——**只落盘缓存，不叫模型**。

        契约定死的两件事（`给手机那边的规格-多电脑接入.md` §4.1）：
          · **成功判定 = 200 / 204**（"她不回正文也算收到"）；
          · 一跳 **30 分钟**、时段外一跳都不发。

        ⚠️ 所以这里**只回 200**，连"这一跳不合规"也回 200 + `ok:false`：
           心跳那一跳**不看正文**，回 4xx / 5xx 只会让它按"别的码"那一档去重试；
           而 501（"还不认识这个动作"）这条路从今天起必须彻底消失 —— 它是本轮最要紧的一条。
        """
        who = self._cache_key(ident)
        ok, why = statuscache.record(req, who)
        tag = "身份 %s" % (who or "?")
        if ok:
            base.log("心跳：收到 status.push —— %s（%s）" % (why, tag))
            self._json({"ok": True})
        else:
            base.log("心跳：收到一跳 status.push 但没收下（%s；%s）" % (why, tag))
            self._json({"ok": False, "error": why})


def send_reply(ctx, reply):
    """把她的一句话发出去（群里带引用回复，私聊直接发）。

    ⚠️ **全项目只有这一处"发她的回复"** —— 正常路径（`_on_message`）和
       迟到补发路径（agent 层超时后回调过来，见 `agent.handle` 的 `late`）
       都走这里，所以两条路的格式**天然一模一样**，不可能各写一套飘掉。
    """
    if ctx["is_group"]:
        return im.send_group(ctx["group_id"], reply,
                             reply_to=ctx.get("message_id")
                             if base.bot_cfg().get("quoteReply", True) else None)
    return im.send_private(ctx["user_id"], reply)


def _on_message(evt, raw_body):
    """一条消息 → 交给 agent → 要把话发回去。"""
    try:
        base.maybe_reload()
        ctx = build_ctx(evt, raw_body)
        # ⚠️ `ctx["text"]` 里已经没有 `[CQ:reply,id=…]` 了（：
        #    机器码不进给模型看的文本）。日志里要一眼看出"这条是引用"，所以这里
        #    单独补一个**纯日志用**的标记 —— 不进模型、不影响任何判定。
        quote = "（引用 %s）" % ctx["reply_to"] if ctx.get("reply_to") else ""
        base.log("收到 %s%s%s: %s"
                 % ("群 " if ctx["is_group"] else "私聊 ", ctx.get("group_id") or "",
                    quote, ctx["text"][:70]))
        # 发送回调一起递下去：这条要是等超时了，就由后台 job 拿它补发（迟到也发）。
        reply = agent.handle(ctx, late=send_reply)
        if reply is agent.LATE_PENDING:
            # 前台等到 maxWaitSeconds 还没算完 —— 这一下**什么都不发**是明确的，
            # 不是"她决定不说"：后台算完会自己补发，且只发一次（见 agent._late_reply）。
            return
        if not reply:
            return
        send_reply(ctx, reply)
    except Exception:
        base.log_exc("处理消息")


def status():
    """给 App / 网页面板 / 看门狗看的。**别把 key 放进来**（也不放 token）。"""
    return {
        "ok": True,
        "version": "v2-skeleton",
        "port": base.cfg().get("port"),
        "uptimeSeconds": int(time.monotonic() - _STARTED),
        "pid": os.getpid(),
        "用户": users.stats(),
        "主人模式": bool(base.owner_mode()),
        "公网地址": base.public_url() or "",
        "agent": agent.info(),
    }


def serve():
    if not base.napcat_token():
        # A4①：token 为空 = **拒绝服务**（不再"空就放行"）。
        # 这里选择"打一行大字 + 不监听"：正常启动路径上她会起不来，
        # deploy 那一步会当场报"端口不通"，看得见、查得到。
        base.log("✗ config.json 里 bot.napcatToken / bot.token 都是空的 —— 拒绝启动"
                 "（公网一映射，空的令牌等于让任何人伪造上报让她说话）")
        print("✗ 没有令牌：拒绝启动（见 bot.log）")
        sys.exit(2)
    port = int(base.cfg().get("port") or 17383)
    # 监听地址：`config.json` 的 `host`（默认 0.0.0.0 = 所有网卡，局域网/云端都能连）。
    # 想只给本机用就填 127.0.0.1（面板也会跟着只在本机打得开）。
    host = str(base.cfg().get("host") or "0.0.0.0").strip() or "0.0.0.0"
    # 并发闸：`config.json` 的 `maxConcurrent`（默认 32）。⚠️ 改了要重启才生效。
    srv = GatedServer((host, port), Handler,
                      max_concurrent=max_concurrent_cfg())
    base.log("机魂小悦启动，监听 %s:%d（%s；公网地址 %s；并发上限 %d，超了回 503；"
             "公网 /api：%s；公网面板：%s；信任的反代：%s）"
             % (host, port, users.stats(), base.public_url() or "没填", srv.max_concurrent,
                "开着（要签名凭据，Bearer 不给公网）" if allow_public()
                else "关着（公网一律 403，默认）",
                "开着（先登录，会话 cookie；页面里没有令牌）" if panel_remote()
                else "关着（只许本机 / 局域网）",
                "、".join(str(x) for x in
                         (base.cfg().get("panel") or {}).get("trustedProxies")
                         or proxy.DEFAULT_TRUSTED)))
    srv.serve_forever()
