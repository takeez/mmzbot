#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**测试用的**最小反向代理（不是产品代码，不 import 本项目任何东西）。

模拟 nginx / caddy 在面板前面干的那几件事：

    · 把请求转给 `--target`（默认 127.0.0.1:17383）；
    · **追加** `X-Forwarded-For`（等价 nginx 的 `$proxy_add_x_forwarded_for`）——
      客户端自己塞的值留在左边，真实地址在**右边**；
    · 用真实对端**覆盖** `X-Real-IP`（等价 nginx 的 `proxy_set_header X-Real-IP $remote_addr`）；
    · 可选 `--proto https` → 带上 `X-Forwarded-Proto: https`（验 cookie 的 `Secure`）；
    · 保留原来的 `Host`（等价 nginx 的 `proxy_set_header Host $host`）。

用法（本机实测远程面板）：

    # 起她（另开一个窗口；测试时把 host 设成 127.0.0.1、allowRemote 设成 true）
    python phone-bot-v2.py

    # 起反代：`--client-ip` 假装"公网来的客户端就是这个地址"
    python tools/revproxy.py --listen 127.0.0.1:18080 --target 127.0.0.1:17383 \\
        --client-ip 203.0.113.9

    curl -i http://127.0.0.1:18080/panel          # → 登录页
    curl -i -H 'X-Forwarded-For: 127.0.0.1' ...   # → 还是登录页（伪造的头被追加在左边）

⛔ 它只监听 127.0.0.1、只用来跑自检 / 手工验证，**别拿它上公网**。
"""

import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
       "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length"}


class Proxy(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _go(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        real = self.server.client_ip or self.client_address[0]

        # 追加 XFF（**不是覆盖**）：左边留着客户端自己塞的，右边是真实地址。
        incoming = self.headers.get("X-Forwarded-For") or ""
        xff = (incoming + ", " + real) if incoming.strip() else real

        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP}
        headers["X-Forwarded-For"] = xff
        headers["X-Real-IP"] = real
        if self.server.proto:
            headers["X-Forwarded-Proto"] = self.server.proto
        if self.server.host:
            headers["Host"] = self.server.host
        else:
            headers.setdefault("Host", "%s:%d" % self.server.addr)

        conn = http.client.HTTPConnection(self.server.addr[0], self.server.addr[1],
                                          timeout=10)
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in HOP:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if data:
                self.wfile.write(data)
        finally:
            conn.close()

    do_GET = do_POST = do_HEAD = _go


def main():
    ap = argparse.ArgumentParser(description="测试用反向代理（见文件头）")
    ap.add_argument("--listen", default="127.0.0.1:18080")
    ap.add_argument("--target", default="127.0.0.1:17383")
    ap.add_argument("--client-ip", default="",
                    help="假装反代看到的客户端地址（默认用真实对端，即 127.0.0.1）")
    ap.add_argument("--proto", default="", help="例：https（决定 cookie 是否带 Secure）")
    ap.add_argument("--host", default="", help="覆盖 Host；留空 = 保留客户端原样")
    a = ap.parse_args()

    def pair(s):
        h, _, p = s.rpartition(":")
        return (h or "127.0.0.1", int(p))

    srv = ThreadingHTTPServer(pair(a.listen), Proxy)
    srv.addr, srv.client_ip, srv.proto, srv.host = pair(a.target), a.client_ip, a.proto, a.host
    print("revproxy: http://%s → %s（client-ip=%s proto=%s）"
          % (a.listen, a.target, a.client_ip or "真实对端", a.proto or "-"), flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
