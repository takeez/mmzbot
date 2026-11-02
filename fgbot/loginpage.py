#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""公网 / 反代后面那张**登录页**（`/login`，也是没登录时打开 `/panel` 看到的那一页）。

⛔ 这里**不许出现任何凭据**（令牌、cookie、会话值一个字节都不行）：
   页面只问你要口令，验口令在 `server._handle_login` 那一层。
⛔ 参数只有"给人看的一句话"，**绝不回显用户输入的内容**。
"""

from html import escape

# 一句人话：告诉用户这是什么、口令在哪、局域网不用这一步。
_HINT = ("这个面板在公网上，要先登录才能用。口令 = 机器人的配置里那把"
         " <b>bot.token</b>（在面板「用户 → 看共享令牌」里也能看到）。")


def render(error="", notice="", next_url="/panel"):
    """渲染登录页。`error` / `notice` 都会做 HTML 转义（不拼原始输入）。"""
    err = ('<p class="msg bad" role="alert">%s</p>' % escape(str(error))) if error else ""
    note = ('<p class="msg warn">%s</p>' % escape(str(notice))) if notice else ""
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow">
<meta name="color-scheme" content="light dark">
<title>机魂小悦 · 登录</title>
<style>
:root{color-scheme:light;--bg:#F6F7F9;--card:#fff;--ink:#151922;--ink2:#4A5261;
  --muted:#78808E;--line:#E4E7ED;--accent:#2F5FA8;--accent-ink:#24497F;
  --bad:#AF332A;--bad-soft:#FBEDEB;--warn:#8F6410;--warn-soft:#FBF3E3}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--bg:#0E1116;--card:#161B22;
  --ink:#E8EBF0;--ink2:#B9C0CC;--muted:#8B94A3;--line:#252C36;--accent:#7EA6E8;
  --accent-ink:#A9C6F2;--bad:#F08A80;--bad-soft:#33191A;--warn:#E5BD6E;--warn-soft:#2E2718}}
*{box-sizing:border-box}
html,body{height:100%%}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans SC",
  "Microsoft YaHei",sans-serif;display:flex;align-items:center;justify-content:center;
  padding:24px;padding-bottom:calc(24px + env(safe-area-inset-bottom))}
.box{width:100%%;max-width:380px;background:var(--card);border:1px solid var(--line);
  border-radius:16px;padding:26px 22px;box-shadow:0 12px 30px rgba(0,0,0,.08)}
h1{margin:0 0 6px;font-size:20px;letter-spacing:.2px}
.desc{margin:0 0 18px;color:var(--ink2);font-size:13.5px}
.desc b{color:var(--ink)}
label{display:block;font-size:13px;color:var(--muted);margin:0 0 6px}
input[type=password]{width:100%%;padding:12px 13px;font:inherit;color:var(--ink);
  background:var(--bg);border:1px solid var(--line);border-radius:10px;outline:none}
input[type=password]:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(47,95,168,.16)}
button{width:100%%;margin-top:14px;padding:12px;font:inherit;font-weight:600;color:#fff;
  background:var(--accent);border:0;border-radius:10px;cursor:pointer}
button:active{background:var(--accent-ink)}
.msg{margin:10px 0 0;font-size:13px;padding:9px 11px;border-radius:9px}
.msg.bad{color:var(--bad);background:var(--bad-soft)}
.msg.warn{color:var(--warn);background:var(--warn-soft)}
.foot{margin:16px 0 0;font-size:12px;color:var(--muted)}
</style>
</head>
<body>
<main class="box">
  <h1>先登录</h1>
  <p class="desc">%(hint)s</p>
  <form method="post" action="/login" autocomplete="on">
    <input type="hidden" name="next" value="%(next)s">
    <label for="pw">口令</label>
    <input id="pw" name="password" type="password" placeholder="粘一次就行"
           autocomplete="current-password" autocapitalize="off" spellcheck="false"
           maxlength="200" required autofocus>
    <button type="submit">登录</button>
  </form>
  %(err)s
  %(note)s
  <p class="foot">同一个局域网里打开面板不用这一步；这个页面不会把口令写进网址、日志或页面源码。</p>
</main>
</body>
</html>
""" % {"hint": _HINT, "next": escape(str(next_url or "/panel")), "err": err, "note": note}
