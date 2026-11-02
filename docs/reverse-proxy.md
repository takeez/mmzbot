# 公网面板访问：反向代理与登录

> 局域网可按配置免登录；公网访问面板必须登录。本项目不提供 TLS，HTTPS 由反向代理终止；机魂小悦仅监听本机或内网 HTTP 端口。

配置结果：

```
浏览器 ──HTTPS──→ nginx / caddy ──HTTP──→ 127.0.0.1:17383
                   （证书在反代上）        （服务不监听公网）
```

---

## 1. 配置机魂小悦

改 `local-config.json`（面板改也行，键名一样）：

```json
{
  "host": "127.0.0.1",
  "panel": {
    "allowRemote": true,
    "trustedProxies": ["127.0.0.1/32", "::1/128"]
  }
}
```

也可以命令行（和面板 / 手改同一份 `local-config.json`）：

```bash
python phone-bot-v2.py --set host=127.0.0.1 panel.allowRemote=true \
    panel.trustedProxies=127.0.0.1/32,::1/128
```

| 键 | 为什么 |
|---|---|
| `host: 127.0.0.1` | 反向代理与机魂小悦在同一台机器时，将 `host` 设为 `127.0.0.1`，使机魂小悦仅监听回环接口，外网只能通过反向代理访问。反代在另一台机器/Docker 里时，改成内网地址（如 `172.17.0.1` 或 `0.0.0.0` 并用防火墙挡住 17383）。 |
| `panel.allowRemote: true` | 公网来源只有在启用后才能访问登录页。默认值 `false` 时返回 403；该配置必须为布尔值 `true`。 |
| `panel.trustedProxies` | 反向代理连接后，机魂小悦看到的 TCP 对端是代理地址；只有代理地址位于该列表中，才会信任其转发的 `X-Forwarded-For` / `X-Real-IP`。同机代理默认可用回环地址；Docker 或其他主机上的代理需填写其实际地址（例如 `["127.0.0.1/32", "172.17.0.1/32"]`）。不要设置为 `0.0.0.0/0`，否则任意来源都将被视为可信代理，可能导致来源校验失效。 |

部署顺序：先修改配置，重启机魂小悦（`python phone-bot-v2.py`），再配置反向代理。
改完访问 `https://你的域名/panel`，看到的应该是**登录页**（不是 403 白屏、也不是直接进面板）。

---

## 2. 登录是怎么回事

- 登录页在 `/login`；`/panel` 没登录也会给这张页。
- 口令 = **共享令牌**（`bot.token` / `bot.napcatToken`）。面板登录后在「用户 → 看共享令牌」能看到。
- 登录成功 → `Set-Cookie: fgPanelSession=<随机串>; Path=/; HttpOnly; SameSite=Lax`
  （HTTPS 反代后面自动加 `Secure`）。之后 `/panel`、`/status`、`/settings`、`/providers`、
  `/onboard`、`POST /api` 都能用，身份 = **主人**。
- **会话表只在内存里**，只存 cookie 的 sha256；重启进程 = 全部失效。
  寿命：`panel.sessionHours`（默认 12 小时）+ `panel.sessionIdleMinutes`（默认 120 分钟没动）。
- 退出：面板右上角「退出」→ `/logout`，服务端**立刻删掉**那条会话 + 下发过期 cookie。
  原 cookie 再拿来是 **403**（不是等它过期）。
- 防爆破：同一个 IP 10 分钟内错 `panel.loginMaxFails`（默认 5）次 →
  冷却 `panel.loginCooldownSeconds`（默认 300 秒），冷却期里**正确口令也不收**。
- 日志里只有来源 IP 和原因，**口令 / cookie 一个字节都不落**。

---

## 3. Nginx 配置

`/etc/nginx/sites-enabled/mmzbot.conf`：

```nginx
server {
    listen 80;
    server_name panel.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name panel.example.com;

    # ── 证书（certbot 会自动填好这两行）────────────────────────────
    ssl_certificate     /etc/letsencrypt/live/panel.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/panel.example.com/privkey.pem;

    # 面板是一个普通网页 + JSON 接口，没有大上传；1 MB 跟她自己的上限对齐
    client_max_body_size 1m;

    location / {
        proxy_pass http://127.0.0.1:17383;

        # ⚠️ 这两行**必须传**，否则来源判定错：她会把所有人当成 127.0.0.1。
        #    X-Forwarded-For 用 `$proxy_add_x_forwarded_for`（**追加**，不是覆盖）：
        #    客户端自己塞的值留在左边，最右边一定是最靠近她那一跳的真实地址。
        proxy_set_header X-Real-IP        $remote_addr;
        proxy_set_header X-Forwarded-For  $proxy_add_x_forwarded_for;

        # 让她的 `?` 重定向 / 登录页表单走对域名（不是 127.0.0.1:17383）
        proxy_set_header Host             $host;

        # cookie 的 Secure 靠这一行（没有它，反代后面拿到的 cookie 不会带 Secure）
        proxy_set_header X-Forwarded-Proto $scheme;

        # ⛔ 不需要 WebSocket：面板没有长连接 / 没有 Upgrade，别抄那两行
        proxy_http_version 1.1;
        proxy_read_timeout 60s;
    }
}
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

## 4. Caddy（照抄）

`/etc/caddy/Caddyfile`：

```caddyfile
panel.example.com {
    reverse_proxy 127.0.0.1:17383 {
        # ⚠️ 这一行**必须**：Caddy 默认不设 X-Real-IP；我们要真实客户端地址。
        #    `{remote_host}` 在 Caddy 里就是 TCP 对端（真实来源）。
        header_up X-Real-IP {remote_host}

        # X-Forwarded-For 由 Caddy 自动处理（默认**不信任**客户端自带的 XFF；
        # 只有全局 `trusted_proxies` 里的来源才会被追加），不用手写。
        # X-Forwarded-Proto 也会自动带上 https。
        # Host 默认保留原样（等价 nginx 的 proxy_set_header Host $host）。
        # ⛔ 不需要开 WebSocket；没有 Upgrade 的需求。
    }
}
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile && sudo systemctl reload caddy
```

> Caddy 前面还有一层 CDN / 负载均衡时（比如 Cloudflare），`{remote_host}` 会变成
> 那一层的地址。这时把那一层的网段加进 Caddy 的 `trusted_proxies`（Caddy 全局项），
> 并把本项目的 `panel.trustedProxies` 指向 Caddy 所在地址。**逐层都要配**，别图省事全信。

---

## 5. 判定规则（为什么伪造 X-Forwarded-For 不管用）

```
对端不在 panel.trustedProxies  →  XFF / X-Real-IP 全当空气，只认 TCP 对端
对端在名单里                   →  XFF 从右往左走，跳过可信代理，停在第一个不可信地址
```

举例（默认只信 `127.0.0.1`，nginx 用 `$proxy_add_x_forwarded_for`）：

| 客户端发来的头 | 反代追加后 | 她认定的来源 |
|---|---|---|
| `X-Forwarded-For: 127.0.0.1`（伪造） | `127.0.0.1, 203.0.113.9` | **203.0.113.9** → 公网，要登录 |
| 不带 | `203.0.113.9` | 203.0.113.9 |
| `X-Real-IP: 127.0.0.1`（伪造） | nginx 用 `$remote_addr` **覆盖**成 `203.0.113.9` | 203.0.113.9 |

同一个局域网里直接开 `http://192.168.1.50:17383/panel`（不经过反代）仍然是
**免登录**的老样子；如果你希望"经过反代的局域网来源也免登录"，把 LAN 网段同时填进
`bot.control.allowIps`（例：`["192.168.1.0/24"]`）即可 —— 她的来源判定用的是
**反代解出来的真实 IP**，所以局域网仍然认得出是局域网。

---

## 6. 配完怎么验（curl）

```bash
# ① 没登录：/panel 必须是登录页（200 + 有 password 输入框），不是面板
curl -si https://panel.example.com/panel | head -20

# ② 没登录：数据接口 403 空正文
curl -si https://panel.example.com/status | head -3

# ③ 登录：拿 cookie（口令从面板「看共享令牌」拿；下面是占位）
curl -si -c /tmp/mmz.cookie -X POST https://panel.example.com/login \
     --data-urlencode 'password=你的共享令牌' | head -20
# → 303 + Set-Cookie: fgPanelSession=…; Path=/; HttpOnly; SameSite=Lax; Secure

# ④ 带着 cookie：面板 / 数据都通
curl -sb /tmp/mmz.cookie https://panel.example.com/panel | head -3
curl -sb /tmp/mmz.cookie https://panel.example.com/status

# ⑤ 错口令：401 + 一句人话（不会告诉你"口令对不对"的细节）
curl -si -X POST https://panel.example.com/login --data-urlencode 'password=错的' | head -10

# ⑥ 退出后再用旧 cookie：403
curl -sb /tmp/mmz.cookie -X POST https://panel.example.com/logout -o /dev/null -w '%{http_code}\n'
curl -sb /tmp/mmz.cookie -o /dev/null -w '%{http_code}\n' https://panel.example.com/status

# ⑦ 伪造 XFF（直连她、不经过反代时应该被无视；经过反代时见第 5 节）
curl -si -H 'X-Forwarded-For: 127.0.0.1' http://127.0.0.1:17383/status | head -3
```

> `⑦` 的本意：证明**来源 IP 不是靠请求头自己说了算**。在反代后面跑时，
> 用 `curl -H 'X-Forwarded-For: 127.0.0.1' https://panel.example.com/status`
> 应该仍然是 403（nginx 会在右边追加真实地址，她取的是右边那个）。

更完整的本机实测（不用真证书、用一个 40 行的 Python 反代模拟 nginx）见
[`tools/revproxy.py`](../tools/revproxy.py)：

```bash
# 1) 起她（测试数据目录；host=127.0.0.1、panel.allowRemote=true）
MMZBOT_DATA=/tmp/mmz-test python phone-bot-v2.py

# 2) 起一个"假 nginx"：监听 18080 → 转给 17883，客户端假装是 203.0.113.9
python tools/revproxy.py --listen 127.0.0.1:18080 --target 127.0.0.1:17883 \
    --client-ip 203.0.113.9 --host panel.example.test

# 3) 按第 6 节那串 curl 打 http://127.0.0.1:18080
```

上一版实测记录（2026-10-31，Windows / Python 3.12，`tools/revproxy.py`）：

| 请求 | 结果 |
|---|---|
| 反代后 `GET /panel`（无会话） | **200 登录页**（`action="/login"`；页面里没有面板 JS / 令牌） |
| 反代后 `GET /status`（无会话） | **403 空正文** |
| `POST /login` 错口令 | **401** + 「口令不对。再试一次。」（不回显输入） |
| `POST /login` 对口令 | **303** + `Set-Cookie: fgPanelSession=…; Path=/; HttpOnly; SameSite=Lax; Max-Age=43200` |
| 带会话 `GET /panel /status /settings /providers /onboard` | 全 **200** |
| 带会话 `POST /api {"action":"user.list"}` + `X-FG-Panel: 1` | **200**（主人身份） |
| 同上但不带 `X-FG-Panel` | **403**（防 CSRF） |
| 伪造 `X-Forwarded-For: 127.0.0.1`（反代追加真地址） | `/panel` 仍是**登录页**、`/status` 仍 **403** |
| 伪造 `X-Real-IP: 127.0.0.1`（反代覆盖真地址） | `/status` **403** |
| `POST /logout` → 旧 cookie 再用 | **303**；旧 cookie `/status` **403**、`/panel` 回登录页 |
| 同一 IP 错 5 次 → 第 6 次用**正确**口令 | 前 5 次 `401 401 401 401 429`；第 6 次仍 **429**（`Retry-After: 300`） |
| 换一个 IP 登录 | **303**（冷却按 IP 分开） |
| `--proto https` 的反代 + 登录 | `Set-Cookie` 带 **`Secure`** |

> 表里"反代后"的请求都是打到 `tools/revproxy.py` 上的；它自己的响应会带一个
> `Server: BaseHTTP/…` 头（那是测试脚本的，不是她的 —— 她自己的响应头里没有 `Server`）。

---

## 7. 常见问题

| 现象 | 原因 |
|---|---|
| 反代后面**不用登录**就能进面板 | `panel.trustedProxies` 没配对（或填了 `0.0.0.0/0`）：她把反代当成本机。同机反代用默认值就行；Docker / 另一台机器要填它的地址。 |
| 配了 `trustedProxies` 还是所有人都被当成 127.0.0.1 | 反代**没传** `X-Forwarded-For` / `X-Real-IP`（漏了上面那两行）。 |
| 登录成功但下一次请求又回登录页 | 反代把 `Set-Cookie` 吞了，或 cookie 掉了（常见于反代改写了 `Path`；本项目的 cookie 是 `Path=/`）。 |
| 登录页能开，提交后 403 | `Host` 没传 / 反代把请求转到了别的端口；或者 `panel.allowRemote` 不是真正的 `true`。 |
| 浏览器里 cookie 没带 `Secure` | 反代没传 `X-Forwarded-Proto: https`。功能不受影响，但 HTTPS 下应当补上。 |
| 突然所有人 429 | 有人在同一出口 IP 上试口令；等冷却结束，或临时把 `panel.loginMaxFails` 调大（不建议）。 |
| 反代 502 | 她没在跑 / `host` 填了 `127.0.0.1` 而反代在别的机器上。 |

## 8. 不应启用 `panel.allowRemote` 的场景

- 只在局域网用：保持 `false`，反代都不用配。
- 只想让朋友的电脑推心跳：`bot.control.allowPublic: true` 就够（只放 `/api` 的签名路），
  面板仍然只给本机 / 局域网。
- 反代做的是**纯内网穿透**（Tailscale / ZeroTier / 家里 VPN 进来的）：来源 IP 是内网地址，
  按局域网那条路走即可，不必开 `allowRemote` —— 但那样就**没有登录**，谁连上 VPN 谁能开面板，
  请根据访问范围和用户信任边界决定是否启用。
