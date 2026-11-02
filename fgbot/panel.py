#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网页面板：用浏览器（手机、平板、另一台电脑）看她、管她、**编她的记忆**。

    http://<手机的局域网IP>:17383/panel

⚠️ 端口是 **17383** —— v1 退休后她接管的那个（以前 v1 的面板也是这个地址，
   所以老的收藏夹不用改）。

⚠️ **页面的 JS 要调 `/status` 和 `/api`，那两个接口都要令牌，但页面里
   `一个字都不带凭据`**（2026-10-03 互联网改造那一批，契约 A5 定稿）：
   打开以后要你**手输一次**令牌（= `config.json` 的 `bot.token`），存在浏览器的
   `localStorage` 里，之后这个浏览器自己记着。以前是把令牌内嵌在 HTML 里 ——
   端口一映射到公网，那等于把钥匙印在门上（A5 实测过：局域网别的机器打开
   `/panel` 就能拿到明文令牌）。
   ⚠️ 口径：**页面上给用户看的字一律叫「令牌」**（"token" 那个词容易和大模型的
   "词元"混）；`localStorage` 的键名 `fgPanelToken`、请求头 `Authorization: Bearer`、
   后端字段 `bot.token` / `role: owner` 这些**机制一个字节都不动**。
   登录之后面板上有一个「看共享令牌」的入口（`token.show`，只有主人能调）。
   ⚠️ 面板本身**只允许本机 + `bot.control.allowIps` 里的网段**打开，公网来源 403 空正文。
   2026-10-31 起多了一条路：`panel.allowRemote: true` 时公网能拿到**登录页**
   （`/login`，见 `fgbot/loginpage.py`），登录后由服务端渲染 `render(remote=True)` ——
   那一页凭据在 **HttpOnly cookie**（`fgPanelSession`）里，页面里照样一个令牌都没有，
   右上角多一个「退出」。本机 / 局域网那条老路一个字没变。

⚠️ **地址栏里那截 `?token=`**（2026-10-05，用户发现的问题：「网址明晃晃写着 token，
   直播就暴露了吧」）：链接里带 `token` 参数时，`<head>` 里那段脚本**先把它读出来**
   交给主脚本当**一次**登录（和手输那一次走同一条路：清洗 → 存 localStorage），
   然后**立刻**用 `history.replaceState` 把地址栏里那一截抹掉 ——
   只删 `token` 这**一个**参数（别的参数 / `#hash` 都不动），而且**不管这把认不认都抹**
   （认不认是下一步 `/status` / `/api` 的事，地址栏不能等它；直播 / 截图 / 分享链接
   看得见的就是那一截）。页面里另有一句小字提示（页脚 + 门禁 + 「共享令牌」那张卡的 hint）。
   ⛔ 它是**浏览器侧的便利**，**不是**另一条登录通道：`server.py` 只从请求头 / 签名认凭据，
      `?token=` 在服务端等于零（没请求头照样 403 空正文，见 server.py 的 `do_GET` / `_identify`）。
   ⛔ 任何时候都不许因为这个把令牌写进 HTML / `document.title` / 任何 `href`（A5 那条不松）。

⚠️ 这里**只做运维动作**，一个字都不许写"她该怎么说话" —— 那是 agent 层的事。
   能做：看状态、重置对话、重启她、改思考强度、**增删改每个人的称呼和记忆**、管 API、
   **管接入的用户（发码 / 看邀请码 / 撤销）**、**管群名单**、
   **裁决排队中的申请（好友申请 / 群邀请：通过 / 拒绝 / 忽略）**、
   **装 / 停 / 卸扩展包（「扩展」页，2026-10-31 加；动作走 `/api capability.*`）**。
   没有、也不该有：切换人格（v1 的灵珠/魔丸已经删了）。

设计（2026-10-04 重做外观与交互，**只动外观与交互，动作名和参数一个都没改**）：
   · 零依赖、完全自包含：不联网也要能用，**没有任何外部资源**（外链字体/图标/框架
     一个都没有）—— 图标是内联 SVG，字体是系统字体栈，主题是纯 CSS 变量；
   · 一套设计令牌（色板 / 圆角 / 阴影 / 间距 / 字号）集中在 `:root`，
     浅色 + 深色两套，**跟随系统 + 手动切 + 记住选择**（`localStorage.fgPanelTheme`）；
   · 信息架构：左侧固定导航（窄屏变成顶部标签条），分成
     `总览 / 申请 / 记忆 / 群 / 用户 / 初始化 / **扩展** / 设置 / 危险操作`；危险操作在导航最底下、**离得远一点**；
   · **「初始化」**（2026-10-31 加）是给**新部署的人**的一条龙：她的 QQ / NapCat / 群 /
     模型入口 / 人设 / 行为开关 + 一张「能不能跑」的检查表。
     它只写 `local-config.json`（和 `personality.md`），**不碰仓库里的 config.json**；
     所有 token 只显示 `****`（要换就整把重填）。动作走 `/onboard` + `/api onboarding.*`；
   · 填东西不容易错：数字类输入**边打边清洗**（全角→半角、去掉空格和杂字符），
     地址类自动去 `http://` 和末尾斜杠，令牌/邀请码自动去掉首尾空白和零宽字符；
     出错时**不清空已填内容**，就在那个字段旁边说明错在哪；
   · 反馈走 toast + 行内提示（**没有 `alert()`**），危险动作一律二次确认并写清后果；
   · 键盘友好：Enter 提交、Esc 关弹窗、焦点环可见、Tab 顺序合理；
   · 动效尊重 `prefers-reduced-motion`；390px 宽不横向溢出。
"""

# ⚠️ 用 **raw 字符串**：正文里有大量 JS 正则（`\s` `\d` `\/`），raw 才不用到处写双反斜杠。
TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#F4F7F8" id="themeColor">
<title>机魂小悦 · 面板</title>
<style>
/* ══ 设计令牌 ══════════════════════════════════════════════════════
   浅色在 :root，深色写两遍（一遍给 `[data-theme=dark]`，一遍给系统的
   `prefers-color-scheme`）—— 这样"手动切"和"跟随系统"共用同一份值。      */
:root{
  color-scheme:light;
  --bg:#F4F7F8; --surface:#FFFFFF; --surface-2:#F7FAFB; --sunken:#EEF4F5;
  --ink:#142026; --ink-2:#40545B; --muted:#708188; --faint:#97A5AA;
  --line:#E2EAEC; --line-2:#D4E0E2;
  --accent:#347B86; --accent-ink:#255F67; --accent-fg:#FFFFFF;
  --accent-soft:#EBF5F6; --accent-line:#CEE3E5;
  --ok:#17795A; --ok-soft:#EAF6F1;
  --warn:#8F6410; --warn-soft:#FBF3E3;
  --bad:#AF332A; --bad-soft:#FBEDEB; --bad-fg:#FFFFFF;
  --r-xs:7px; --r-sm:10px; --r:14px; --r-lg:18px;
  --sh-1:0 1px 3px rgba(22,55,62,.04);
  --sh-2:0 8px 24px -18px rgba(20,52,60,.22), 0 1px 3px rgba(20,52,60,.035);
  --sh-pop:0 10px 30px rgba(20,52,60,.14), 0 32px 72px -30px rgba(20,52,60,.34);
  --s1:4px; --s2:8px; --s3:12px; --s4:16px; --s5:24px; --s6:32px;
  --fs-xs:11.5px; --fs-sm:12.5px; --fs-md:14px; --fs-lg:16px; --fs-xl:20px;
  --side:248px; --top-h:60px;
  --mono:ui-monospace,SFMono-Regular,Menlo,Consolas,"Liberation Mono",monospace;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    color-scheme:dark;
    --bg:#0E1116; --surface:#151A21; --surface-2:#191F27; --sunken:#11151B;
    --ink:#E9EDF3; --ink-2:#B0B8C4; --muted:#868E9C; --faint:#666E7B;
    --line:#232932; --line-2:#303845;
    --accent:#74C5CA; --accent-ink:#97D9DC; --accent-fg:#0E1116;
    --accent-soft:#17272A; --accent-line:#274247;
    --ok:#4CC38A; --ok-soft:#13251E;
    --warn:#DFB25E; --warn-soft:#241F14;
    --bad:#F08B80; --bad-soft:#261817; --bad-fg:#1A0F0E;
    --sh-1:0 1px 2px rgba(0,0,0,.5);
    --sh-2:0 2px 4px rgba(0,0,0,.4), 0 12px 32px -22px rgba(0,0,0,.9);
    --sh-pop:0 2px 8px rgba(0,0,0,.5), 0 28px 64px -24px rgba(0,0,0,.85);
  }
}
:root[data-theme="dark"]{
  color-scheme:dark;
  --bg:#0E1116; --surface:#151A21; --surface-2:#191F27; --sunken:#11151B;
  --ink:#E9EDF3; --ink-2:#B0B8C4; --muted:#868E9C; --faint:#666E7B;
  --line:#232932; --line-2:#303845;
  --accent:#74C5CA; --accent-ink:#97D9DC; --accent-fg:#0E1116;
  --accent-soft:#17272A; --accent-line:#274247;
  --ok:#4CC38A; --ok-soft:#13251E;
  --warn:#DFB25E; --warn-soft:#241F14;
  --bad:#F08B80; --bad-soft:#261817; --bad-fg:#1A0F0E;
  --sh-1:0 1px 2px rgba(0,0,0,.5);
  --sh-2:0 2px 4px rgba(0,0,0,.4), 0 12px 32px -22px rgba(0,0,0,.9);
  --sh-pop:0 2px 8px rgba(0,0,0,.5), 0 28px 64px -24px rgba(0,0,0,.85);
}

/* ══ 基础 ════════════════════════════════════════════════════════ */
*{box-sizing:border-box;-webkit-tap-highlight-color:transparent}
html,body{margin:0;padding:0}
body{
  background:var(--bg); color:var(--ink); min-height:100vh;
  font:var(--fs-md)/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",
       "Segoe UI",Roboto,"Helvetica Neue",Arial,sans-serif;
  -webkit-font-smoothing:antialiased; text-rendering:optimizeLegibility;
}
button{font:inherit;color:inherit;cursor:pointer}
[hidden]{display:none!important}
h1,h2,h3{margin:0}
a{color:var(--accent-ink)}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:var(--r-xs)}
.grow{flex:1;min-width:0}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
svg{display:block;flex:none}

/* ══ 壳 ══════════════════════════════════════════════════════════ */
.shell{min-height:100vh;display:flex;flex-direction:column}
.topbar{
  position:sticky;top:0;z-index:40;height:var(--top-h);flex:none;
  display:flex;align-items:center;gap:12px;padding:0 28px;
  background:var(--surface);border-bottom:1px solid var(--line);
}
.pagetitle{display:none}
.brandmini{display:none;align-items:center;gap:8px;font-weight:660;font-size:var(--fs-md)}
.body{flex:1;display:flex;align-items:stretch;min-height:0}
.side{
  width:var(--side);flex:none;position:sticky;top:var(--top-h);align-self:flex-start;
  height:calc(100vh - var(--top-h));overflow:auto;display:flex;flex-direction:column;
  gap:14px;padding:24px 14px 18px;border-right:1px solid var(--line);background:var(--surface);
}
.main{flex:1;min-width:0}
.content{width:100%;max-width:1220px;margin:0 auto;padding:32px 38px 88px}

/* ── 品牌 ─────────────────────────────────────────────────────── */
.mark{
  width:38px;height:38px;border-radius:12px;flex:none;display:grid;place-items:center;
  background:var(--accent);color:var(--accent-fg);box-shadow:var(--sh-1);
}
.mark svg{width:19px;height:19px}
.brand{display:flex;align-items:center;gap:11px;padding:2px 9px 22px}
.brand b{display:block;font-size:17px;font-weight:720;letter-spacing:-.35px;line-height:1.2}
.brand i{display:block;font-style:normal;font-size:11px;color:var(--muted);margin-top:4px;letter-spacing:.04em}

/* ── 导航 ─────────────────────────────────────────────────────── */
.nav{display:flex;flex-direction:column;gap:5px}
.navi{
  display:flex;align-items:center;gap:12px;width:100%;text-align:left;
  padding:11px 13px;border:0;background:transparent;border-radius:12px;
  color:var(--ink-2);font-size:var(--fs-md);font-weight:610;white-space:nowrap;
  transition:background .16s,color .16s,transform .16s;
}
.navi svg{width:18px;height:18px;opacity:.72}
.navi:hover{background:var(--sunken);color:var(--ink);transform:translateX(1px)}
.navi.on{background:var(--accent-soft);color:var(--accent-ink);box-shadow:inset 3px 0 var(--accent)}
.navi.on svg{opacity:1}
.subnav{display:flex;gap:5px;overflow-x:auto;margin:0 0 var(--s4);padding:3px 0 6px;
  border-bottom:1px solid var(--line);scrollbar-width:none}
.subnav::-webkit-scrollbar{display:none}
.subnav button{flex:none;padding:7px 12px;border:1px solid transparent;border-radius:999px;
  background:transparent;color:var(--muted);font-size:var(--fs-sm);font-weight:620;white-space:nowrap}
.subnav button:hover{background:var(--sunken);color:var(--ink)}
.subnav button.on{background:var(--accent-soft);border-color:var(--accent-line);color:var(--accent-ink)}
[data-module-panel]:not(.module-visible){display:none!important}
[data-module-nav][hidden]{display:none!important}
.navi.danger{color:var(--bad)}
.navi.danger:hover{background:var(--bad-soft)}
.navi.danger.on{background:var(--bad-soft);color:var(--bad)}
/* 导航上那个小圆点数（现在有 N 条申请等你裁决）；0 条时不占地方 */
.navi .navcnt{display:none;margin-left:auto;font-style:normal;font-size:var(--fs-xs);
  font-weight:680;color:var(--accent-ink);background:var(--accent-soft);
  border:1px solid var(--accent-line);border-radius:999px;padding:0 7px;min-width:20px;
  text-align:center;flex:none}
.navi .navcnt.on{display:inline-block}
.navi.on .navcnt{background:var(--surface);border-color:var(--accent-line)}
.navi.danger .navcnt{color:var(--bad);background:var(--bad-soft);
  border-color:color-mix(in srgb,var(--bad) 26%,var(--line))}
.sidefoot{margin-top:auto;padding-top:var(--s3);border-top:1px solid var(--line);
  font-size:var(--fs-xs);color:var(--faint);line-height:1.6;padding-left:9px;padding-right:9px}

/* ── 顶栏零件 ─────────────────────────────────────────────────── */
.pill{display:inline-flex;align-items:center;gap:7px;padding:5px 11px;border-radius:999px;
  font-size:var(--fs-sm);font-weight:640;border:1px solid var(--line-2);background:var(--surface);
  color:var(--muted);white-space:nowrap}
.pill.on{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 34%,var(--line-2));
  background:var(--ok-soft)}
.pill.off{color:var(--bad);border-color:color-mix(in srgb,var(--bad) 34%,var(--line-2));
  background:var(--bad-soft)}
.dot{width:7px;height:7px;border-radius:50%;background:currentColor;flex:none}
.pill.on .dot{position:relative}
.pill.on .dot::after{content:"";position:absolute;inset:-4px;border-radius:50%;
  border:1px solid currentColor;opacity:.5;animation:ring 2.4s ease-out infinite}
@keyframes ring{0%{transform:scale(.6);opacity:.7}70%{transform:scale(1.6);opacity:0}100%{opacity:0}}

/* ── 按钮 ─────────────────────────────────────────────────────── */
.btn{
  display:inline-flex;align-items:center;justify-content:center;gap:7px;
  padding:9px 14px;border-radius:var(--r-sm);border:1px solid var(--line-2);
  background:var(--surface);color:var(--ink);font-size:var(--fs-md);font-weight:600;
  transition:background .14s,border-color .14s,color .14s,opacity .14s;white-space:nowrap;
}
.btn:hover{background:var(--sunken);border-color:var(--faint)}
.btn:active{transform:translateY(.5px)}
.btn.primary{background:var(--accent);border-color:var(--accent);color:var(--accent-fg)}
.btn.primary:hover{background:var(--accent-ink);border-color:var(--accent-ink)}
.btn.danger{color:var(--bad);border-color:color-mix(in srgb,var(--bad) 30%,var(--line-2));
  background:var(--surface)}
.btn.danger:hover{background:var(--bad-soft);border-color:var(--bad)}
.btn.danger-solid{background:var(--bad);border-color:var(--bad);color:var(--bad-fg)}
.btn.danger-solid:hover{filter:brightness(1.08)}
.btn.ghost{background:transparent;border-color:transparent;color:var(--muted)}
.btn.ghost:hover{background:var(--sunken);color:var(--ink)}
.btn.sm{padding:6px 10px;font-size:var(--fs-sm);border-radius:var(--r-xs)}
.btn.ic{padding:8px;width:34px;height:34px}
.btn.ic svg,.btn svg{width:15px;height:15px}
.btn[disabled]{opacity:.5;pointer-events:none}
.btn.done{color:var(--ok);border-color:color-mix(in srgb,var(--ok) 40%,var(--line-2))}
.spin{width:13px;height:13px;border-radius:50%;border:2px solid currentColor;
  border-top-color:transparent;animation:sp .7s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}

/* ── 分段控件 ─────────────────────────────────────────────────── */
.seg{display:inline-grid;grid-auto-flow:column;grid-auto-columns:1fr;gap:3px;
  background:var(--sunken);border:1px solid var(--line);border-radius:var(--r-sm);padding:3px}
.seg .segbtn{border:0;background:transparent;border-radius:var(--r-xs);padding:7px 12px;
  color:var(--muted);font-size:var(--fs-sm);font-weight:620;transition:.14s}
.seg .segbtn:hover{color:var(--ink)}
.seg .segbtn.on{background:var(--surface);color:var(--accent-ink);box-shadow:var(--sh-1)}
.seg.wide{display:grid;grid-auto-flow:row;grid-template-columns:repeat(4,1fr)}
.seg.tseg .segbtn{padding:6px 9px}

/* ── 卡片 ─────────────────────────────────────────────────────── */
.view{display:none}
.view.on{display:block;animation:fade .18s ease-out}
@keyframes fade{from{opacity:0;transform:translateY(3px)}to{opacity:1;transform:none}}
.vhead{margin:0 0 22px}
.vhead h2{display:flex;align-items:center;gap:10px;font-size:26px;font-weight:730;letter-spacing:-.65px}
.vhead h2::before{content:"";width:4px;height:23px;border-radius:99px;background:var(--accent);flex:none}
.vhead p{margin:7px 0 0;font-size:var(--fs-sm);color:var(--muted);line-height:1.65;max-width:76ch}
.card{background:var(--surface);border:1px solid color-mix(in srgb,var(--line) 68%,transparent);border-radius:20px;
  padding:22px;box-shadow:var(--sh-2)}
.card + .card{margin-top:18px}
.card.danger{border-color:color-mix(in srgb,var(--bad) 24%,var(--line))}
.cardhead{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:16px}
.cardhead h3{font-size:15px;font-weight:700;letter-spacing:-.18px}
.grid2{display:grid;gap:var(--s4);grid-template-columns:minmax(0,1fr) minmax(0,1fr);
  align-items:start;margin-top:var(--s4)}
.hint{font-size:var(--fs-sm);color:var(--muted);line-height:1.65}
.hint b{color:var(--ink-2)}
.hint.warn{color:var(--warn)}
.mt{margin-top:var(--s3)}
.mb{margin-bottom:var(--s3)}

/* ── 表单 ─────────────────────────────────────────────────────── */
input,textarea{font:inherit;font-size:var(--fs-md);width:100%;color:var(--ink);
  background:var(--sunken);border:1px solid var(--line-2);border-radius:var(--r-sm);
  padding:9px 12px;outline:none;transition:border-color .14s,box-shadow .14s,background .14s}
textarea{line-height:1.6;resize:vertical}
.field > label{display:block;margin-bottom:7px;color:var(--ink-2);font-size:var(--fs-sm);font-weight:680}
input::placeholder,textarea::placeholder{color:var(--faint)}
input:focus,textarea:focus{border-color:var(--accent);background:var(--surface);
  box-shadow:0 0 0 3px var(--accent-soft)}
input.bad,textarea.bad{border-color:var(--bad);box-shadow:0 0 0 3px var(--bad-soft)}
input[readonly]{font-family:var(--mono);font-size:var(--fs-sm);letter-spacing:.02em}
input.mono{font-family:var(--mono);font-size:var(--fs-sm)}
.field{min-width:0}
.field > .msg{margin:6px 2px 0;font-size:var(--fs-sm);color:var(--bad);line-height:1.5}
.field > .msg:empty{display:none}
.inline{display:flex;gap:var(--s2);align-items:flex-start;flex-wrap:wrap}
.inline > input{flex:1 1 220px;min-width:0}
.toolbar{display:flex;gap:var(--s2);align-items:center;flex-wrap:wrap;margin-bottom:var(--s3)}
.search{position:relative;flex:1 1 240px;min-width:0}
.search svg{position:absolute;left:11px;top:50%;transform:translateY(-50%);
  width:15px;height:15px;color:var(--faint);pointer-events:none}
.search input{padding-left:33px;border-radius:var(--r-sm)}
.rowsep{display:flex;gap:var(--s2);flex-wrap:wrap}

/* ── 下拉框 / 勾选框（她的大脑、后台模型两张卡用）──────────────── */
select{font:inherit;font-size:var(--fs-md);width:100%;color:var(--ink);background:var(--sunken);
  border:1px solid var(--line-2);border-radius:var(--r-sm);padding:8px 10px;outline:none;
  transition:border-color .14s,box-shadow .14s,background .14s}
select:focus{border-color:var(--accent);background:var(--surface);
  box-shadow:0 0 0 3px var(--accent-soft)}
.check{display:inline-flex;align-items:center;gap:8px;font-size:var(--fs-sm);
  font-weight:620;color:var(--ink-2);cursor:pointer}
.check input{width:auto;height:auto;padding:0;margin:0;accent-color:var(--accent)}
.msg{font-size:var(--fs-sm);color:var(--bad);line-height:1.5;margin:6px 0 0}
.msg:empty{display:none}
.brainpick{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:var(--s3)}
.bp{display:flex;flex-direction:column;gap:5px;min-width:0}
.bp > .hint{font-size:var(--fs-xs);font-weight:620}
@media (max-width:640px){ .brainpick{grid-template-columns:1fr} }
.plist2{display:flex;flex-direction:column;gap:var(--s2);margin-top:var(--s3)}
.pcard{border:1px solid var(--line);border-radius:var(--r);background:var(--surface-2);
  padding:10px 12px}
.pcard.on{border-color:color-mix(in srgb,var(--ok) 34%,var(--line))}
.phead{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.phead .grow{flex:1}
.pdot{width:8px;height:8px;border-radius:50%;background:var(--faint);flex:none}
.pcard.on .pdot{background:var(--ok)}
.pname{font-size:var(--fs-md);font-weight:660}
.pbody{margin-top:var(--s3);padding-top:var(--s3);border-top:1px dashed var(--line-2)}
details.pcustom{margin-top:var(--s3)}
details.pcustom > summary{cursor:pointer;list-style:none;font-size:var(--fs-sm);
  font-weight:620;color:var(--ink-2);padding:4px 0}
details.pcustom > summary::-webkit-details-marker{display:none}
details.pcustom > summary .chev{width:12px;height:12px;vertical-align:-2px;margin-right:4px;
  color:var(--faint);transition:transform .14s}
details.pcustom[open] > summary .chev{transform:rotate(90deg)}
.mtools{display:flex;gap:var(--s2);flex-wrap:wrap;align-items:center;margin-top:var(--s3)}
.mrows{display:flex;flex-direction:column;margin-top:4px}
.mrow{display:flex;align-items:center;gap:8px;padding:5px 0;border-top:1px solid var(--line)}
.mrow:first-child{border-top:0}
.mrow .mid{font-family:var(--mono);font-size:var(--fs-sm);flex:1 1 auto;min-width:0;
  overflow-wrap:anywhere}
.mrow .mname{font-size:var(--fs-xs);color:var(--muted);flex:0 1 38%;text-align:right;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mrow.on .mid{color:var(--ok);font-weight:660}
.mp-list{max-height:min(48vh,380px);overflow:auto;border:1px solid var(--line);
  border-radius:var(--r-sm);background:var(--surface-2);padding:4px}
.mp-item{display:flex;align-items:center;gap:9px;padding:7px 9px;border-radius:var(--r-xs);
  cursor:pointer;font-size:var(--fs-sm)}
.mp-item:hover{background:var(--sunken)}
.mp-item input{width:auto;margin:0;accent-color:var(--accent)}
.mp-item .mid{font-family:var(--mono);flex:1;min-width:0;overflow-wrap:anywhere}
.mp-item .mname{color:var(--muted);font-size:var(--fs-xs);flex:0 1 36%;text-align:right;
  overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mp-item.done{opacity:.5}
.mp-empty{color:var(--muted);font-size:var(--fs-sm);padding:10px}

/* ── 统计 ─────────────────────────────────────────────────────── */
.who{display:flex;align-items:center;gap:var(--s2);flex-wrap:wrap}
.big{font-size:22px;font-weight:700;letter-spacing:-.4px}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{font-size:var(--fs-xs);font-weight:640;color:var(--muted);background:var(--sunken);
  border:1px solid var(--line);border-radius:999px;padding:2px 9px}
.chip.ok{color:var(--ok);background:var(--ok-soft);border-color:color-mix(in srgb,var(--ok) 26%,var(--line))}
.chip.bad{color:var(--bad);background:var(--bad-soft);border-color:color-mix(in srgb,var(--bad) 26%,var(--line))}
.chip.accent{color:var(--accent-ink);background:var(--accent-soft);border-color:var(--accent-line)}
.overview-hero{padding:24px;border:1px solid var(--accent-line);background:var(--surface);overflow:hidden}
.hero-layout{display:flex;align-items:center;gap:15px;min-width:0}
.hero-mark{width:52px;height:52px;border-radius:16px;flex:none;display:grid;place-items:center;
  color:var(--accent-ink);background:var(--accent-soft)}
.hero-mark svg{width:25px;height:25px}
.hero-identity{min-width:0;flex:1}
.hero-kicker{display:block;color:var(--muted);font-size:11px;font-weight:680;letter-spacing:.08em;margin-bottom:3px}
.hero-updated{font-size:var(--fs-xs);color:var(--faint);white-space:nowrap;align-self:flex-start}
.who{display:flex;align-items:center;gap:var(--s2);flex-wrap:wrap}
.big{font-size:27px;font-weight:740;letter-spacing:-.65px}
.chips{display:flex;gap:6px;flex-wrap:wrap}
.chip{font-size:var(--fs-xs);font-weight:640;color:var(--muted);background:var(--sunken);
  border:1px solid var(--line);border-radius:999px;padding:3px 10px}
.chip.ok{color:var(--ok);background:var(--ok-soft);border-color:color-mix(in srgb,var(--ok) 26%,var(--line))}
.chip.bad{color:var(--bad);background:var(--bad-soft);border-color:color-mix(in srgb,var(--bad) 26%,var(--line))}
.chip.accent{color:var(--accent-ink);background:var(--accent-soft);border-color:var(--accent-line)}
.stats{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:22px}
.stat{background:var(--surface-2);border:1px solid transparent;border-radius:14px;padding:12px 14px;min-width:0}
.stat .k{font-size:11px;color:var(--muted);letter-spacing:.025em;font-weight:610}
.stat .v{margin-top:4px;font-family:inherit;font-size:15px;font-weight:720;line-height:1.35;
  letter-spacing:-.15px;overflow-wrap:anywhere}

/* ── 列表行 ───────────────────────────────────────────────────── */
.rows{display:flex;flex-direction:column}
.fact{display:flex;align-items:flex-start;gap:10px;padding:9px 2px;border-top:1px solid var(--line)}
.fact:first-child{border-top:0}
.fact > .dot{margin-top:7px;background:var(--accent)}
.fact .txt{flex:1;min-width:0;font-size:var(--fs-md);overflow-wrap:anywhere}
.fact .txt b{font-weight:640}
.fact .acts{display:flex;gap:3px;flex:none;flex-wrap:wrap;justify-content:flex-end}
.empty{font-size:var(--fs-sm);color:var(--muted);padding:10px 2px;line-height:1.6}

/* ── 记忆：人列表 + 详情 ──────────────────────────────────────── */
.split{display:grid;grid-template-columns:minmax(0,252px) minmax(0,1fr);gap:var(--s4);
  align-items:start}
.plist{display:flex;flex-direction:column;gap:2px;max-height:min(58vh,520px);overflow:auto;
  border:1px solid var(--line);border-radius:var(--r);padding:5px;background:var(--surface-2)}
.pitem{display:flex;align-items:center;gap:8px;width:100%;text-align:left;border:0;
  background:transparent;border-radius:var(--r-xs);padding:8px 9px;font-weight:600;
  transition:background .13s,color .13s}
.pitem:hover{background:var(--sunken)}
.pitem.on{background:var(--accent-soft);color:var(--accent-ink)}
.pitem .pname{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
  font-size:var(--fs-md)}
.pitem .pqq,.pitem .pnum{font-size:var(--fs-xs);color:var(--faint);font-family:var(--mono);flex:none}
.pitem.on .pqq,.pitem.on .pnum{color:var(--accent-ink);opacity:.75}
.detail{border:1px solid var(--line);border-radius:var(--r);padding:var(--s3) var(--s4);
  background:var(--surface-2);min-height:120px}
.dhead{display:flex;align-items:center;gap:var(--s2);flex-wrap:wrap;margin-bottom:2px}
.dhead .dname{font-size:var(--fs-lg);font-weight:680}
.dmeta{font-size:var(--fs-sm);color:var(--muted);margin-bottom:var(--s2);word-break:break-all}
.frow{display:flex;align-items:flex-start;gap:9px;padding:7px 0;border-top:1px solid var(--line)}
.frow:first-of-type{border-top:0}
.frow .bdot{width:5px;height:5px;border-radius:50%;background:var(--accent);opacity:.45;
  margin-top:8px;flex:none}
.frow .ftxt{flex:1;min-width:0;font-size:var(--fs-md);overflow-wrap:anywhere}
.frow .fops{display:flex;gap:2px;flex:none;opacity:.6;transition:opacity .14s}
.frow:hover .fops,.frow:focus-within .fops{opacity:1}
.addrow{display:flex;gap:var(--s2);margin-top:var(--s3);align-items:flex-start}
.addrow > input{flex:1;min-width:0}

/* ── 触发词：一个词一个 chip（单独加 / 单独改 / 单独删）────────── */
.tchips{display:flex;flex-wrap:wrap;gap:6px;align-items:center;min-height:32px}
.tchip{display:inline-flex;align-items:stretch;border:1px solid var(--line-2);
  border-radius:999px;background:var(--surface-2);overflow:hidden}
.tchip .tt{border:0;background:transparent;padding:5px 3px 5px 12px;font-size:var(--fs-sm);
  font-weight:620;color:var(--ink-2);border-radius:0;max-width:230px;overflow:hidden;
  text-overflow:ellipsis;white-space:nowrap}
.tchip .tt:hover{color:var(--accent-ink);background:var(--accent-soft)}
.tchip .tx{border:0;background:transparent;padding:4px 10px 4px 5px;color:var(--faint);
  font-size:15px;line-height:1.3;border-radius:0}
.tchip .tx:hover{color:var(--bad);background:var(--bad-soft)}
.tchips .none{font-size:var(--fs-sm);color:var(--muted)}

/* ── 可折叠卡片：原生 details/summary（键盘天然能开，不用 JS）──── */
details.card{padding:0}
details.card > summary{display:flex;align-items:center;gap:10px;cursor:pointer;list-style:none;
  padding:var(--s4);border-radius:var(--r-lg);transition:background .14s}
details.card > summary::-webkit-details-marker{display:none}
details.card > summary:hover{background:var(--surface-2)}
details.card > summary .chev{width:15px;height:15px;color:var(--faint);flex:none;
  transition:transform .16s}
details.card[open] > summary .chev{transform:rotate(90deg)}
details.card[open] > summary{border-bottom:1px solid var(--line);border-radius:var(--r-lg) var(--r-lg) 0 0}
details.card > summary h3{font-size:var(--fs-md);font-weight:660}
details.card > summary .cnt{font-size:var(--fs-xs);font-weight:620;color:var(--muted);
  background:var(--sunken);border:1px solid var(--line);border-radius:999px;padding:1px 9px}
details.card .cbody{padding:var(--s4)}
details.card .cbody > .hint:first-child{margin-top:calc(-1 * var(--s1))}

/* ── 运行参数：一行一项（标签 / 输入框 / 单位）──── */
.param{padding:10px 2px;border-top:1px solid var(--line)}
.param:first-child{border-top:0}
.phead{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.plabel{font-size:var(--fs-md);font-weight:640;color:var(--ink)}
.pctl{display:flex;align-items:center;gap:8px;margin-top:6px;flex-wrap:wrap}
.pctl input{flex:0 1 170px;width:170px;font-family:var(--mono);font-size:var(--fs-sm);
  padding:7px 10px}
.punit{font-size:var(--fs-sm);color:var(--muted);flex:none;min-width:22px}
.pctl .btn{margin-left:auto}
.param > .hint{margin-top:4px}
.param-search{width:min(210px,42vw)}
.param-search input{padding:6px 10px;font-size:var(--fs-sm)}
.param-tools{display:flex;align-items:center;gap:6px;margin-left:auto}
.param-meta{display:inline-flex;align-items:center;gap:6px;flex-wrap:wrap}
.param-meta .chip{font-size:10px}
[data-param-reset]{font-size:var(--fs-xs)!important}
.pgroup{margin-top:var(--s4)}
.pgroup:first-child{margin-top:0}
.pgrouphead{font-size:var(--fs-sm);font-weight:660;color:var(--ink-2);
  padding-bottom:2px}
.pmsg{font-size:var(--fs-sm);line-height:1.5;min-height:1.2em;margin-top:var(--s2)}
.pmsg:empty{display:none}
.pmsg.ok{color:var(--ok)}
.pmsg.bad{color:var(--bad)}

/* ── 行尾操作：图标 + 小字；危险动作用一条竖线隔开一点 ─────────── */
.rowacts{display:flex;align-items:center;gap:2px;flex:none}
.rowacts .sep{width:1px;height:16px;background:var(--line-2);margin:0 7px;flex:none}
.iconbtn{display:inline-flex;align-items:center;gap:5px;padding:6px 8px;border:1px solid transparent;
  border-radius:var(--r-xs);background:transparent;color:var(--muted);font-size:var(--fs-sm);
  font-weight:600;transition:.14s}
.iconbtn svg{width:15px;height:15px}
.iconbtn:hover{background:var(--sunken);color:var(--ink)}
.iconbtn.on{color:var(--accent-ink);background:var(--accent-soft)}
.iconbtn.danger:hover{background:var(--bad-soft);color:var(--bad)}
.iconbtn[disabled]{opacity:.45;pointer-events:none}
.iconbtn .lbl{white-space:nowrap}
@media (max-width:560px){ .iconbtn .lbl{display:none} .iconbtn{padding:7px} }

/* ── 弹窗里的表单字段 ─────────────────────────────────────────── */
.flab{display:block;font-size:var(--fs-sm);font-weight:620;color:var(--ink-2);margin-bottom:5px}
.flab em{font-style:normal;color:var(--bad);font-size:var(--fs-xs);font-weight:600;margin-left:5px}
.flab .opt{color:var(--faint);font-weight:500;font-size:var(--fs-xs);margin-left:5px}
.fhint{margin:5px 2px 0;font-size:var(--fs-xs);color:var(--faint);line-height:1.55}
/* 表单里的**实时提示**（例如"填完 QQ 立刻取到的昵称"）—— 跟出错的 .msg 分开，互不覆盖 */
.fnote:empty{display:none}
.fnote.ok{color:var(--ok)}
.fnote.bad{color:var(--bad)}

/* ── 行内提示条 ───────────────────────────────────────────────── */
.note{display:flex;gap:8px;align-items:flex-start;padding:9px 11px;border-radius:var(--r-sm);
  background:var(--accent-soft);border:1px solid var(--accent-line);font-size:var(--fs-sm);
  color:var(--ink-2);line-height:1.6;margin-bottom:var(--s3)}
.note.warn{background:var(--warn-soft);
  border-color:color-mix(in srgb,var(--warn) 26%,var(--line))}
.note.danger{background:var(--bad-soft);
  border-color:color-mix(in srgb,var(--bad) 26%,var(--line))}

/* ── 日志 ─────────────────────────────────────────────────────── */
.log{display:flex;flex-direction:column;gap:7px;max-height:260px;overflow:auto;
  font-size:var(--fs-sm)}
.log .li{display:flex;gap:9px;align-items:baseline;color:var(--ink-2);line-height:1.5}
.log .li time{font-family:var(--mono);font-size:var(--fs-xs);color:var(--faint);flex:none}
.log .li.bad{color:var(--bad)}

/* ── 快捷入口 ─────────────────────────────────────────────────── */
.jumps{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.jump{display:flex;align-items:center;gap:12px;min-width:0;text-align:left;
  padding:14px;border:1px solid var(--line);border-radius:16px;background:var(--surface);
  box-shadow:var(--sh-1);transition:transform .16s,border-color .16s,background .16s,box-shadow .16s}
.jump:hover{transform:translateY(-2px);border-color:var(--accent-line);background:var(--surface-2);box-shadow:var(--sh-2)}
.jump-icon{width:40px;height:40px;display:grid;place-items:center;flex:none;border-radius:13px;
  color:var(--accent-ink);background:var(--accent-soft)}
.jump-icon svg{width:19px;height:19px}
.jump-copy{display:flex;flex-direction:column;gap:3px;min-width:0}
.jump-copy b{font-size:var(--fs-md);font-weight:700;color:var(--ink)}
.jump-copy span{font-size:var(--fs-xs);color:var(--muted);line-height:1.5}

/* ── 初始化：一块一张卡，状态在卡片右上角 ─────────────────────── */
.obstate{font-size:var(--fs-xs);font-weight:660;border-radius:999px;padding:2px 9px;
  border:1px solid var(--line);color:var(--muted);background:var(--sunken);white-space:nowrap}
.obstate.ok{color:var(--ok);background:var(--ok-soft);
  border-color:color-mix(in srgb,var(--ok) 30%,var(--line))}
.obstate.bad{color:var(--bad);background:var(--bad-soft);
  border-color:color-mix(in srgb,var(--bad) 30%,var(--line))}
.obrow{display:grid;grid-template-columns:160px minmax(0,1fr);gap:var(--s4);
  align-items:center;padding:12px 0;border-top:1px solid var(--line)}
.obrow:first-of-type{border-top:0}
.obrow > label{font-size:var(--fs-sm);font-weight:680;color:var(--ink-2)}
.obrow input[type=checkbox]{width:auto;height:auto;padding:0;margin:0;accent-color:var(--accent)}
#overviewCheck,#obCheck{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:9px}
.obchk{display:grid;grid-template-columns:22px minmax(0,1fr);align-items:center;gap:8px;
  padding:10px 12px;border:1px solid var(--line);border-radius:12px;background:var(--surface-2);
  font-size:var(--fs-sm);min-width:0}
.obchk .mk{font-weight:750;display:grid;place-items:center;width:20px;height:20px;border-radius:50%;
  color:var(--ok);background:var(--ok-soft);flex:none}
.obchk.bad .mk{color:var(--bad);background:var(--bad-soft)}
.obchk .why{grid-column:2;font-size:var(--fs-xs);color:var(--muted);line-height:1.45}
.obsum{display:inline-flex;align-items:center;margin-top:14px;padding:6px 11px;border-radius:999px;
  font-size:var(--fs-sm);font-weight:700;background:var(--sunken)}
.obsum.ok{color:var(--ok);background:var(--ok-soft)}
.obsum.bad{color:var(--bad);background:var(--bad-soft)}
@media (max-width:560px){ .obrow{grid-template-columns:minmax(0,1fr)} }

/* ── 弹窗 ─────────────────────────────────────────────────────── */
.backdrop{position:fixed;inset:0;z-index:60;display:none;place-items:center;padding:16px;
  background:color-mix(in srgb,var(--ink) 42%,transparent);
  backdrop-filter:blur(3px);-webkit-backdrop-filter:blur(3px)}
.backdrop.on{display:grid}
.sheet{width:100%;max-width:440px;max-height:88vh;overflow:auto;background:var(--surface);
  border:1px solid var(--line);border-radius:var(--r-lg);padding:var(--s5);
  box-shadow:var(--sh-pop);animation:pop .18s ease-out}
@keyframes pop{from{transform:translateY(8px) scale(.985);opacity:0}to{transform:none;opacity:1}}
.sheet h3{font-size:var(--fs-lg);font-weight:680;margin-bottom:6px}
.sheet .desc{margin:0 0 var(--s4);font-size:var(--fs-sm);color:var(--muted);line-height:1.7;
  white-space:pre-line;overflow-wrap:anywhere}
.sheet .foot{display:flex;gap:var(--s2);justify-content:flex-end;margin-top:var(--s4)}
.gatewrap{text-align:center}
.gatewrap .mark{margin:0 auto var(--s3);width:40px;height:40px;border-radius:12px}
.gatewrap .mark svg{width:21px;height:21px}
.gatewrap .desc{text-align:left}

/* ── toast ────────────────────────────────────────────────────── */
#toast{position:fixed;left:50%;bottom:24px;z-index:80;transform:translate(-50%,14px);
  max-width:min(88vw,460px);padding:11px 16px;border-radius:var(--r);
  background:var(--ink);color:var(--bg);font-size:var(--fs-sm);font-weight:600;
  box-shadow:var(--sh-pop);opacity:0;transition:opacity .2s,transform .2s;pointer-events:none;
  text-align:center;line-height:1.5}
#toast.on{opacity:1;transform:translate(-50%,0)}
#toast.ok{background:var(--ok);color:#fff}
#toast.bad{background:var(--bad);color:#fff}

@media (prefers-reduced-motion:reduce){
  *{animation-duration:.001ms!important;animation-iteration-count:1!important;
    transition-duration:.001ms!important}
}

/* ══ 窄屏 ════════════════════════════════════════════════════════ */
@media (max-width:900px){
  :root{--top-h:54px}
  .topbar{padding:0 12px;gap:8px}
  .brandmini{display:flex}
  .pagetitle{display:none}
  .body{flex-direction:column}
  .side{position:sticky;top:var(--top-h);z-index:35;width:100%;height:auto;align-self:auto;
    flex-direction:row;align-items:center;gap:5px;padding:8px 10px;overflow-x:auto;
    overflow-y:hidden;border-right:0;border-bottom:1px solid var(--line);background:var(--surface);
    scrollbar-width:none}
  .side::-webkit-scrollbar{display:none}
  .side .brand,.side .sidefoot{display:none}
  .nav{flex-direction:row;gap:5px}
  .navi{width:auto;padding:8px 11px;font-size:var(--fs-sm);gap:7px;border-radius:10px}
  .navi svg{width:15px;height:15px}
  .content{padding:24px 18px 72px}
  .split{grid-template-columns:minmax(0,1fr)}
  .plist{max-height:38vh}
  .grid2{grid-template-columns:minmax(0,1fr)}
  .stats{grid-template-columns:repeat(2,minmax(0,1fr))}
}
@media (max-width:760px){
  .grid2{grid-template-columns:minmax(0,1fr)}
}
@media (max-width:420px){
  .brandmini b{display:none}
  .seg.tseg .segbtn{padding:6px 7px}
}
@media (max-width:560px){
  html,body{width:100%;max-width:100%;overflow-x:hidden}
  .main,.content{width:100%;max-width:100%;min-width:0}
  .content{margin:0;padding:18px 12px 64px}
  .card,.grid2,.stats,.stat{min-width:0}
  .card{padding:16px;border-radius:16px}
  .overview-hero{padding:18px}
  .hero-mark{width:44px;height:44px;border-radius:14px}
  .hero-mark svg{width:22px;height:22px}
  .hero-updated{font-size:10px}
  .big{font-size:23px}
  .stats{grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
  .stat{padding:11px 12px}
  .stat .v{font-size:14px}
  .grid2{grid-template-columns:minmax(0,1fr)}
  .jumps{grid-template-columns:minmax(0,1fr)}
  #overviewCheck,#obCheck{grid-template-columns:minmax(0,1fr)}
  .seg.wide{grid-template-columns:repeat(2,1fr)}
  .sheet{padding:var(--s4)}
  .dhead .dname{font-size:var(--fs-md)}
  .setup-sheet{max-height:92vh}
}
.setup-sheet{max-width:560px;text-align:left}
.setup-progress{display:flex;align-items:center;gap:10px;margin:10px 0 18px;
  color:var(--muted);font-size:var(--fs-xs);font-weight:640}
.step-track{width:86px;height:4px;border-radius:999px;background:var(--sunken);overflow:hidden}
.step-track i{display:block;width:33.3%;height:100%;border-radius:inherit;background:var(--accent);transition:width .18s}
.setup-section{display:flex;align-items:center;justify-content:space-between;margin:0 0 12px;
  color:var(--ink);font-size:var(--fs-md)}
.setup-section span{color:var(--muted);font-size:var(--fs-xs);font-weight:600}
.setup-step > .field + .field{margin-top:var(--s3)}
.setup-step .hint{margin-top:var(--s2)}
.setup-foot{align-items:center}
.wakewrap{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.chipx{border:0;background:transparent;color:var(--muted);padding:1px 5px;border-radius:999px;cursor:pointer}
.chipx:hover{background:var(--accent-soft);color:var(--accent-ink)}
</style>
<script>
/* 主题要在**第一帧之前**定下来，不然会闪一下白（⛔ 跟令牌无关的一个 localStorage 键）。 */
try{
  var _t = localStorage.getItem("fgPanelTheme");
  if (_t === "light" || _t === "dark") document.documentElement.setAttribute("data-theme", _t);
}catch(e){}
</script>
<script>
/* ⚠️ 地址栏里那截 `?token=`（老书签 / 别人发来的链接）：**读出来，然后立刻抹掉**。
   ① 页面最底下那段主脚本拿它当**一次登录**用 —— 和用户手输那一次完全一样，存 localStorage；
   ② 这里**马上** `history.replaceState` 把 `token` 这**一个**参数从地址栏删掉
      （`?view=…` 这类别的参数、`#记忆` 这类 hash 都留着，只删 token）；
   ③ **不管这把令牌认不认都先抹** —— 认不认是下一步 `/status` / `/api` 的事，
      地址栏不能等它（历史记录、直播画面、截图、发给别人的链接都看得见那一截）。

   ⚠️ 为什么摆在 `<head>` 里：这一段**第一帧之前**就跑完，令牌挂在那儿的窗口最短。
   ⛔ 值只交给主脚本去存 localStorage —— **一个字节都不许写进 HTML / `document.title` /
      任何 `href`**（这页面本来也没有外链），用完就把这个全局清空。
   ⚠️ 服务端那边**不认**查询串里的令牌（`server.py` 只从请求头 / 签名认，A5），
      所以这一节只关乎"浏览器地址栏上挂着什么"，**不是**另一条登录通道、门禁一个字节没松。 */
window.URLTOKEN = "";
try{
  if (location.search && location.search.indexOf("token") >= 0){
    var _q = new URLSearchParams(location.search);
    if (_q.has("token")){
      window.URLTOKEN = String(_q.get("token") || "");   // 主脚本里再清洗一次（首尾空白 / 零宽字符）
      _q["delete"]("token");                             // ⛔ 只删这一个参数
      var _qs = _q.toString();
      history.replaceState(null, "", location.pathname + (_qs ? "?" + _qs : "") + location.hash);
    }
  }
}catch(e){ window.URLTOKEN = ""; }
</script>
</head>
<body>
<div class="shell">

  <header class="topbar">
    <span class="brandmini"><span class="mark" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
           stroke-linecap="round" stroke-linejoin="round"><path d="M4 6.5 12 3l8 3.5v11L12 21l-8-3.5z"/>
        <path d="M12 10.5v10.4"/><path d="m4 6.5 8 4 8-4"/></svg></span><b>机魂小悦</b></span>
    <h2 class="pagetitle" id="pageTitle">总览</h2>
    <span class="grow"></span>
    <span class="pill off" id="pill"><span class="dot"></span><span id="pillTxt">读状态…</span></span>
    <button class="btn ghost ic" id="refreshBtn" title="刷新状态" aria-label="刷新状态"
            onclick="refresh(true)"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
      stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20.5 12a8.5 8.5 0 1 1-2.6-6.1"/>
      <path d="M20.5 4.2V10H15"/></svg></button>
    <div class="seg tseg" id="themeSeg" role="group" aria-label="主题">
      <button class="segbtn" data-theme="auto" title="跟随系统">跟随</button>
      <button class="segbtn" data-theme="light" title="浅色">浅</button>
      <button class="segbtn" data-theme="dark" title="深色">深</button>
    </div>
    <!-- 只有远程 / 反代后面（登录过）才显示；本机 / 局域网那条路不出现 -->
    <button class="btn ghost sm" id="logoutBtn" type="button" title="退出登录"
            aria-label="退出登录" onclick="doLogout()" hidden>退出</button>
  </header>

  <div class="body">
    <aside class="side">
      <div class="brand">
        <span class="mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
               stroke-linecap="round" stroke-linejoin="round"><path d="M4 6.5 12 3l8 3.5v11L12 21l-8-3.5z"/>
            <path d="M12 10.5v10.4"/><path d="m4 6.5 8 4 8-4"/></svg></span>
        <span><b id="herName">机魂小悦</b><i>控制台</i></span>
      </div>
      <nav class="nav" id="nav" aria-label="分区">
        <button class="navi" data-go="overview"><svg viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="3" width="7.6" height="7.6" rx="2.2"/><rect x="13.4" y="3" width="7.6" height="7.6" rx="2.2"/>
          <rect x="3" y="13.4" width="7.6" height="7.6" rx="2.2"/><rect x="13.4" y="13.4" width="7.6" height="7.6" rx="2.2"/>
        </svg>总览</button>
        <button class="navi" data-go="robot"><svg viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
          <path d="M3.5 7.5h8.2M17 7.5h3.5M3.5 16.5h3.2M12 16.5h8.5"/>
          <circle cx="14.6" cy="7.5" r="2.4"/><circle cx="9.4" cy="16.5" r="2.4"/>
        </svg>机器人</button>
        <button class="navi" data-go="access"><svg viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 3a9 9 0 1 0 4.3 16.9L21 21l-1.1-4.7A9 9 0 0 0 12 3z"/>
          <path d="M12 8.2v.01"/><path d="M12 11.4v4.4"/>
        </svg>接入与范围<i class="navcnt" id="reqNav"></i></button>
        <button class="navi" data-go="memory"><svg viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
          <path d="M6.5 3H19a1 1 0 0 1 1 1v16a1 1 0 0 1-1 1H6.5A2.5 2.5 0 0 1 4 18.5v-13A2.5 2.5 0 0 1 6.5 3z"/>
          <path d="M8.5 3v18"/><path d="M12 8h5M12 12h5"/>
        </svg>记忆</button>
        <button class="navi" data-go="extensions"><svg viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
          <rect x="3" y="3" width="7.4" height="7.4" rx="1.7"/><rect x="13.6" y="3" width="7.4" height="7.4" rx="1.7"/>
          <rect x="3" y="13.6" width="7.4" height="7.4" rx="1.7"/><path d="M17.3 13.9v6.8M13.9 17.3h6.8"/>
        </svg>扩展</button>
        <button class="navi" data-go="system"><svg viewBox="0 0 24 24" fill="none"
          stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">
          <path d="M12 3.5v2M12 18.5v2M20.5 12h-2M5.5 12h-2M18 6l-1.4 1.4M7.4 16.6 6 18M18 18l-1.4-1.4M7.4 7.4 6 6"/>
          <circle cx="12" cy="12" r="4.2"/>
        </svg>系统</button>
      </nav>
    </aside>

    <main class="main">
      <div class="content">

        <!-- ═══ 总览 ═══════════════════════════════════════════ -->
        <section class="view on" data-view="overview" aria-labelledby="pt-overview">
          <div class="vhead"><h2 id="pt-overview">总览</h2></div>

          <div class="card overview-hero">
            <div class="hero-layout">
              <span class="hero-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6.5 12 3l8 3.5v11L12 21l-8-3.5z"/><path d="M12 10.5v10.4M4 6.5l8 4 8-4"/></svg></span>
              <div class="hero-identity"><span class="hero-kicker">运行概况</span>
                <div class="who"><span class="big" id="herName2">机魂小悦</span>
                  <span class="chips" id="chips"></span></div>
              </div>
              <span class="hero-updated" id="stamp"></span>
            </div>
            <div class="stats" id="stats"></div>
          </div>

          <div class="card" id="overviewHealth">
            <div class="cardhead"><h3>运行检查</h3><span class="grow"></span>
              <button class="btn ghost sm" type="button" onclick="loadOnboard(this, true)">重新检查</button></div>
            <div id="overviewCheck"><div class="empty">正在检查…</div></div>
            <div class="obsum" id="overviewSum">检查中…</div>
          </div>
          <div class="card" id="overviewSetupCard" hidden>
            <div class="cardhead"><h3 id="overviewSetupTitle">初始配置未完成</h3><span class="grow"></span>
              <button class="btn sm" id="overviewSetupOpen" type="button" data-route="robot-identity">继续配置</button></div>
            <p class="hint" id="overviewSetupWhy"></p>
          </div>

          <div class="grid2">
            <div class="card">
              <div class="cardhead"><h3>操作记录</h3><span class="grow"></span>
                <button class="btn ghost sm" onclick="clearLog()">清空</button></div>
              <div class="log" id="log"><div class="li"><time>—</time><span>暂无操作记录</span></div></div>
            </div>
            <div class="card">
              <div class="cardhead"><h3>常用操作</h3></div>
              <div class="jumps">
                <button class="jump" data-route="robot-model"><span class="jump-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2"/></svg></span><span class="jump-copy"><b>切换模型</b><span>提供商、模型与思考强度</span></span></button>
                <button class="jump" data-go="memory"><span class="jump-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 4h13v16H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/><path d="M8 4v16M12 9h4M12 13h4"/></svg></span><span class="jump-copy"><b>维护记忆</b><span>搜索人物，编辑称呼和事实</span></span></button>
                <button class="jump" onclick="restartHer(this)"><span class="jump-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 7v5h-5"/><path d="M20 12a8 8 0 1 1-2.3-5.6L20 9"/></svg></span><span class="jump-copy"><b>重启机器人</b><span>约 10 秒；期间消息可能漏掉</span></span></button>
                <button class="jump" data-go="access"><span class="jump-icon" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="8" r="3"/><path d="M3.5 19a5.5 5.5 0 0 1 11 0M17 8h4M19 6v4M17.5 15a4.5 4.5 0 0 1 3 4"/></svg></span><span class="jump-copy"><b>群与接入</b><span>目标群、用户和申请</span></span></button>
              </div>
            </div>
          </div>
        </section>

        <!-- ═══ 申请 ═══════════════════════════════════════════ -->
        <section class="view" data-view="requests" aria-labelledby="pt-requests">
          <div class="vhead"><h2 id="pt-requests">申请</h2></div>
          <div class="subnav" aria-label="接入与范围">
            <button type="button" data-route="requests">申请</button>
            <button type="button" data-route="groups">目标群</button>
            <button type="button" data-route="users">用户</button>
          </div>

          <details class="card" id="cardReq" open>
            <summary>
              <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 5 7 7-7 7"/></svg>
              <h3 id="reqHead">待处理</h3><span class="cnt" id="reqCount">0 条</span>
            </summary>
            <div class="cbody">
              <div class="rows" id="reqList"></div>
              <div class="rowsep mt"><button class="btn sm" onclick="loadRequests(this)">刷新</button></div>
            </div>
          </details>

          <details class="card" id="cardReqDone">
            <summary>
              <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 5 7 7-7 7"/></svg>
              <h3>已处理</h3><span class="cnt" id="reqDoneCount">0 条</span>
            </summary>
            <div class="cbody">
              <div class="rows" id="reqDone"></div>
            </div>
          </details>
        </section>

        <!-- ═══ 记忆 ═══════════════════════════════════════════ -->
        <section class="view" data-view="memory" aria-labelledby="pt-memory">
          <div class="vhead"><h2 id="pt-memory">记忆</h2></div>

          <div class="card">
            <div class="toolbar">
              <div class="search">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
                     stroke-linecap="round"><circle cx="11" cy="11" r="6.4"/><path d="m20 20-3.7-3.7"/></svg>
                <input id="memQ" type="text" placeholder="搜索称呼、昵称、群名片、QQ 或记忆"
                       aria-label="搜记忆">
              </div>
              <span class="hint" id="memCount"></span>
              <button class="btn sm" onclick="loadMem(this)">刷新</button>
              <button class="btn sm primary" data-addperson="1">＋ 添加人物</button>
            </div>
            <div class="split">
              <div class="plist" id="bubs"></div>
              <div class="detail" id="memDetail"></div>
            </div>
          </div>
        </section>

        <!-- ═══ 群 ═════════════════════════════════════════════ -->
        <section class="view" data-view="groups" aria-labelledby="pt-groups">
          <div class="vhead"><h2 id="pt-groups">群</h2></div>
          <div class="subnav" aria-label="接入与范围">
            <button type="button" data-route="requests">申请</button>
            <button type="button" data-route="groups">目标群</button>
            <button type="button" data-route="users">用户</button>
          </div>

          <details class="card" id="cardSeen">
            <summary>
              <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 5 7 7-7 7"/></svg>
              <h3>最近会话群</h3><span class="cnt" id="seenCount">0 个</span>
            </summary>
            <div class="cbody">
              <div class="rows" id="groupRecent"></div>
              <div class="rowsep mt"><button class="btn sm" onclick="loadGroups(this)">刷新</button></div>
            </div>
          </details>

          <details class="card" id="cardMine" open>
            <summary>
              <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 5 7 7-7 7"/></svg>
              <h3>目标群</h3><span class="cnt" id="groupCount">0 条</span>
            </summary>
            <div class="cbody">
              <div class="toolbar">
                <div class="search">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
                       stroke-linecap="round"><circle cx="11" cy="11" r="6.4"/><path d="m20 20-3.7-3.7"/></svg>
                  <input id="groupQ" type="text" placeholder="搜群号 / 群名 / 备注" aria-label="搜群">
                </div>
              </div>
              <div class="field" id="newGroupField">
                <div class="inline">
                  <input id="newGroupId" type="text" inputmode="numeric" autocomplete="off"
                         placeholder="输入群号" data-enter="addGroupBtn" aria-label="群号">
                  <button class="btn primary" id="addGroupBtn">添加群</button>
                </div>
                <p class="msg" id="newGroupMsg"></p>
              </div>
              <p class="hint mb">输入数字群号。</p>
              <div class="rows" id="groupList"></div>
            </div>
          </details>
        </section>

        <!-- ═══ 用户 ═══════════════════════════════════════════ -->
        <section class="view" data-view="users" aria-labelledby="pt-users">
          <div class="vhead"><h2 id="pt-users">用户</h2></div>
          <div class="subnav" aria-label="接入与范围">
            <button type="button" data-route="requests">申请</button>
            <button type="button" data-route="groups">目标群</button>
            <button type="button" data-route="users">用户</button>
          </div>

          <div class="card">
            <div class="cardhead"><h3>邀请码地址</h3><span class="grow"></span>
              <span class="hint">用于生成邀请码</span></div>
            <div class="field" id="pubField">
              <div class="inline">
                <input id="pubUrl" type="text" autocomplete="off" spellcheck="false"
                       placeholder="公网域名或映射地址" aria-label="公网地址">
                <button class="btn primary" id="pubSave">保存</button>
                <button class="btn" id="pubCopy">复制</button>
              </div>
              <p class="msg" id="pubMsg"></p>
            </div>
            <p class="hint">填写外部映射端口，不是本机监听端口。</p>
          </div>

          <details class="card" id="cardUsers" open>
            <summary>
              <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 5 7 7-7 7"/></svg>
              <h3>接入用户</h3><span class="cnt" id="userCount">0 个</span>
            </summary>
            <div class="cbody">
              <div class="toolbar">
                <div class="search">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
                       stroke-linecap="round"><circle cx="11" cy="11" r="6.4"/><path d="m20 20-3.7-3.7"/></svg>
                  <input id="userQ" type="text" placeholder="搜备注 / 称呼 / 昵称 / QQ / 群号"
                         aria-label="搜用户">
                </div>
                <button class="btn primary sm" data-adduser="1">＋ 新增</button>
              </div>
              <div class="rows" id="userList"></div>
            </div>
          </details>

          <details class="card" id="cardImport">
            <summary>
              <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 5 7 7-7 7"/></svg>
              <h3>导入与导出</h3><span class="cnt" id="impCount">含用户令牌</span>
            </summary>
            <div class="cbody">
              <div class="note warn"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor"
                  stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"
                  style="width:15px;height:15px;margin-top:2px"><path d="M10.3 3.9 2.4 17.5a1.95 1.95 0 0 0 1.7 2.9h15.8a1.95 1.95 0 0 0 1.7-2.9L13.7 3.9a1.95 1.95 0 0 0-3.4 0z"/>
                  <path d="M12 9.4v4.4"/><path d="M12 17.1h.01"/></svg>
                <span>导出文件包含用户令牌，请妥善保管。</span></div>
              <div class="rowsep">
                <button class="btn sm" onclick="exportUsers(this)">⇩ 导出用户表</button>
                <button class="btn sm" onclick="pickImport()">⇧ 导入（选文件）</button>
                <button class="btn sm" onclick="pasteImport()">⇧ 导入（粘贴）</button>
                <input id="impFile" type="file" accept=".json,application/json" style="display:none">
              </div>
            </div>
          </details>

          <details class="card" id="cardToken">
            <summary>
              <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 5 7 7-7 7"/></svg>
              <h3>共享令牌</h3><span class="cnt">主人可查看</span>
            </summary>
            <div class="cbody">
              <div class="rowsep"><button class="btn" id="tokBtn">查看共享令牌</button></div>
              <div id="tokBox" style="display:none" class="mt">
                <div class="inline">
                  <input id="tokVal" type="text" readonly onclick="this.select()" aria-label="共享令牌">
                  <button class="btn primary" id="tokCopy">复制</button>
                </div>
              </div>
              <p class="hint mt" id="tokNote">仅分享给可信设备。</p>
            </div>
          </details>
        </section>


        <!-- ═══ 扩展 ═══════════════════════════════════════════ -->
        <section class="view" data-view="extensions" aria-labelledby="pt-extensions">
          <div class="vhead"><h2 id="pt-extensions">扩展</h2></div>

          <details class="card" open>
            <summary>
              <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 5 7 7-7 7"/></svg>
              <h3>已安装扩展</h3><span class="cnt" id="capCount">—</span>
            </summary>
            <div class="cbody">
              <div class="rows" id="capList"><div class="empty">正在读…</div></div>
              <div class="rowsep mt">
                <button class="btn sm" type="button" onclick="loadCapabilities(this)">刷新</button>
                <button class="btn primary sm" type="button" onclick="pickCapability(this)">安装（上传 zip）</button>
                <input type="file" id="capFile" accept=".zip,application/zip" hidden>
              </div>
              <div class="field mt">
                <label for="capUrl">通过 URL 安装</label>
                <div class="inline">
                  <input id="capUrl" type="text" autocomplete="off" spellcheck="false"
                         placeholder="https://codeload.github.com/owner/repo/zip/HEAD"
                         aria-label="扩展包网址">
                  <button class="btn primary sm" type="button" onclick="capUrlCheck(this)">预检</button>
                </div>
                <p class="hint">预检通过后确认安装。仅支持 GitHub、Gitee、jsDelivr 等白名单 ZIP，最大 5 MB。</p>
                <div id="capReceipt" hidden></div>
                <p class="msg" id="capMsg"></p>
              </div>
              <div class="field mt">
                <label>附加允许域名</label>
                <div class="wakewrap">
                  <div class="chips" id="capHostChips"></div>
                  <button class="btn sm" id="capHostAdd" type="button">＋ 加一个</button>
                </div>
                <p class="hint">每项填写一个域名，可包含子域。</p>
              </div>
              <div class="field mt">
                <label for="capProxy">下载代理</label>
                <input id="capProxy" type="text" spellcheck="false"
                       placeholder="http://127.0.0.1:7890（空 = 直连）">
                <div class="rowsep mt">
                  <button class="btn sm" type="button" onclick="capSaveProxy(this)">保存代理</button>
                </div>
                <p class="hint">用于扩展下载；仅支持 HTTP / HTTPS。</p>
              </div>
              <p class="fhint">扩展与主程序同权限运行；仅安装可信来源。</p>
            </div>
          </details>
        </section>

        <!-- ═══ 设置 ═══════════════════════════════════════════ -->
        <section class="view" data-view="settings" aria-labelledby="pt-settings">
          <div class="vhead"><h2 id="pt-settings">机器人</h2></div>
          <div class="subnav" data-module-nav="robot" aria-label="机器人设置">
            <button type="button" data-route="robot-identity">身份与通道</button>
            <button type="button" data-route="robot-model">模型</button>
            <button type="button" data-route="robot-behavior">对话行为</button>
          </div>
          <div class="subnav" data-module-nav="system" aria-label="系统设置" hidden>
            <button type="button" data-route="system-runtime">运行参数</button>
            <button type="button" data-route="system-network">网络访问</button>
            <button type="button" data-route="danger">运维操作</button>
          </div>
          <div class="card" id="setupHintCard" data-module-panel="robot-identity" hidden>
            <div class="cardhead"><h3 id="setupHint">配置未完成</h3><span class="grow"></span>
              <button class="btn sm" id="setupHintOpen" type="button">继续配置</button></div>
            <p class="hint" id="setupHintWhy"></p>
          </div>

          <div class="card" id="obA" data-module-panel="robot-identity">
            <div class="cardhead"><h3>机器人身份</h3><span class="grow"></span>
              <span class="obstate" id="obAState"></span></div>
            <p class="hint">名字或唤醒词出现在消息开头时触发。</p>
            <div class="obrow"><label for="obQQ">机器人 QQ 号</label>
              <input id="obQQ" type="text" inputmode="numeric" autocomplete="off"
                     placeholder="填写机器人 QQ 号"></div>
            <div class="obrow"><label for="obNick">机器人名字</label>
              <input id="obNick" type="text" autocomplete="off" placeholder="默认：机魂小悦"></div>
            <div class="obrow"><label>唤醒词</label>
              <div class="wakewrap">
                <div class="chips" id="obWakeChips"></div>
                <button class="btn sm" id="obWakeAdd" type="button">＋ 加一个</button>
              </div>
              </div>
            <p class="msg" id="obAMsg"></p>
            <div class="rowsep mt"><button class="btn primary" id="obASave">保存</button></div>
          </div>

          <div class="card" id="obB" data-module-panel="robot-identity">
            <div class="cardhead"><h3>消息通道</h3><span class="grow"></span>
              <span class="obstate" id="obBState"></span></div>
            <p class="hint">机器人与 NapCat 共用令牌；修改后重启 NapCat。</p>
            <div class="obrow"><label for="obPort">上报端口</label>
              <input id="obPort" type="text" inputmode="numeric" autocomplete="off"
                     placeholder="17383"></div>
            <div class="obrow"><label for="obToken">共用令牌</label>
              <div class="inline">
                <input id="obToken" type="password" autocomplete="new-password" spellcheck="false"
                       placeholder="留空则不修改">
                <button class="btn" id="obTokenEye" type="button">显示</button>
                <button class="btn" id="obTokenGen" type="button">随机生成</button>
              </div></div>
            <div class="obrow"><label for="obNapUrl">NapCat 的 API 地址</label>
              <input id="obNapUrl" type="text" autocomplete="off" spellcheck="false"
                     placeholder="http://127.0.0.1:3000"></div>
            <div class="obrow"><label for="obAccept">自动同意群邀请</label>
              <label class="check"><input type="checkbox" id="obAccept" aria-label="自动同意群邀请"> 开</label></div>
            <p class="msg" id="obBMsg"></p>
            <div class="rowsep mt">
              <button class="btn primary" id="obBSave">保存</button>
              <button class="btn" id="obProbe" type="button">检测 NapCat</button>
              <span class="hint" id="obProbeMsg"></span>
            </div>
          </div>

          <div class="card" id="obC" data-module-panel="robot-identity">
            <div class="cardhead"><h3>目标群</h3><span class="grow"></span>
              <span class="obstate" id="obCState"></span></div>
            <p class="hint">每行一个群号，可选备注。</p>
            <div class="field">
              <textarea id="obGroups" rows="5" spellcheck="false"
                        placeholder="群号，可选备注"></textarea>
              <p class="msg" id="obCMsg"></p>
            </div>
            <div class="rowsep mt">
              <button class="btn primary" id="obCSave">保存</button>
              <button class="btn" id="obPull" type="button">导入群列表</button>
              <span class="hint" id="obPullMsg"></span>
            </div>
          </div>

          <div class="card" id="obE" data-module-panel="robot-identity">
            <div class="cardhead"><h3>人设</h3><span class="grow"></span>
              <span class="obstate" id="obEState"></span></div>
            <p class="hint">注释不显示在编辑框中，保存时保留。</p>
            <div class="field">
              <textarea id="obPersona" rows="12" spellcheck="false"
                        aria-label="人设正文"></textarea>
              <p class="msg" id="obEMsg"></p>
            </div>
            <div class="rowsep mt">
              <button class="btn primary" id="obESave">保存</button>
              <span class="hint" id="obPersonaNow"></span>
            </div>
          </div>


          <div class="card" id="obG" data-module-panel="robot-behavior">
            <div class="cardhead"><h3>对话行为</h3><span class="grow"></span>
              <span class="obstate" id="obGState"></span></div>
            <div class="obrow"><label for="obChance">随机接话概率</label>
              <div class="inline"><input id="obChance" type="text" inputmode="numeric"
                     autocomplete="off" style="max-width:110px" aria-label="随机接话概率">
                <span class="punit">%</span></div></div>
            <div class="obrow"><label for="obPokeBack">戳一戳回应</label>
              <label class="check"><input type="checkbox" id="obPokeBack" aria-label="戳一戳回击"> 开</label></div>
            <div class="obrow"><label for="obAllowPublic">公网 API 调用</label>
              <label class="check"><input type="checkbox" id="obAllowPublic" aria-label="公网 API 调用"> 允许</label></div>
            <p class="hint">与公网面板登录设置无关。</p>
            <div class="obrow"><label for="obMaxGroup">群聊回复上限</label>
              <div class="inline"><input id="obMaxGroup" type="text" inputmode="numeric"
                     autocomplete="off" style="max-width:130px" aria-label="群聊回复上限">
                <span class="punit">字</span></div></div>
            <div class="obrow"><label for="obMaxPrivate">私聊回复上限</label>
              <div class="inline"><input id="obMaxPrivate" type="text" inputmode="numeric"
                     autocomplete="off" style="max-width:130px" aria-label="私聊回复上限">
                <span class="punit">字</span></div></div>
            <p class="msg" id="obGMsg"></p>
            <div class="rowsep mt"><button class="btn primary" id="obGSave">保存</button></div>
          </div>

          <div class="card" id="obH" data-module-panel="system-runtime">
            <div class="cardhead"><h3>运行检查</h3><span class="grow"></span>
              <button class="btn ghost sm" id="obRefresh" type="button">重新检查</button></div>
            <div id="obCheck"></div>
            <div class="obsum" id="obSum">检查中…</div>
          </div>


          <div class="card" id="networkAccess" data-module-panel="system-network">
            <div class="cardhead"><h3>网络访问</h3></div>
            <div class="note warn">公网访问需经 HTTPS 反向代理。可信代理仅填实际 IP/CIDR，禁止全网段。</div>
            <div class="obrow"><label for="netAllowRemote">公网面板登录</label>
              <label class="check"><input type="checkbox" id="netAllowRemote"> 允许</label></div>
            <div class="rowsep mt"><button class="btn sm" id="netSaveRemote" type="button">保存公网访问</button>
              <span class="hint" id="netRemoteMsg"></span></div>
            <div class="field mt"><label for="netHost">监听地址</label>
              <div class="inline"><input id="netHost" type="text" autocomplete="off" spellcheck="false" placeholder="127.0.0.1">
                <button class="btn sm" id="netSaveHost" type="button">保存</button></div>
              <p class="hint">修改后重启生效；代理同机时使用 127.0.0.1。</p>
              <p class="msg" id="netHostMsg"></p></div>
            <div class="field mt"><label>API 来源 IP 白名单</label>
              <div class="wakewrap"><div class="tchips" id="allowIpsChips"></div>
                <button class="btn sm" id="allowIpsAdd" type="button">＋ 添加</button></div>
              <p class="hint">限制控制 API 的来源 IP；留空表示不限制。</p>
              <p class="msg" id="allowIpsMsg"></p></div>
            <div class="field mt"><label>可信反向代理</label>
              <div class="wakewrap"><div class="tchips" id="proxyChips"></div>
                <button class="btn sm" id="proxyAdd" type="button">＋ 添加</button></div>
              <p class="hint">仅信任所列代理地址；至少保留一个 IP/CIDR。</p>
              <p class="msg" id="proxyMsg"></p></div>
          </div>

          <div class="card" id="cardBrain" data-module-panel="robot-model">
            <div class="cardhead"><h3>主模型</h3><span class="grow"></span>
              <span class="hint" id="brainNow">读取中…</span></div>
            <div class="brainpick">
              <label class="bp"><span class="hint">提供商</span>
                <select id="brainProvider" aria-label="提供商"></select></label>
              <label class="bp"><span class="hint">模型</span>
                <select id="brainModel" aria-label="模型"></select></label>
              <label class="bp"><span class="hint">思考强度</span>
                <select id="brainEffort" aria-label="思考强度"></select></label>
            </div>
            <p class="msg" id="brainMsg"></p>
            <div class="plist2" id="provList"></div>
            <div class="rowsep mt">
              <button class="btn sm" data-pact="addprov">＋ 添加提供商</button>
            </div>
            <p class="hint mt">支持 OpenAI 兼容接口；密钥仅保存在服务端。</p>
          </div>

          <div class="card" id="cardUtility" data-module-panel="robot-model">
            <div class="cardhead"><h3>后台模型</h3></div>
            <label class="check"><input type="checkbox" id="utilInherit"> 沿用主模型</label>
            <div id="utilBox" hidden>
              <div class="brainpick mt">
                <label class="bp"><span class="hint">提供商</span>
                  <select id="utilProvider" aria-label="后台提供商"></select></label>
                <label class="bp"><span class="hint">模型</span>
                  <select id="utilModel" aria-label="后台模型"></select></label>
                <label class="bp"><span class="hint">思考强度</span>
                  <select id="utilEffort" aria-label="后台思考强度"></select></label>
              </div>
            </div>
            <p class="msg" id="utilMsg"></p>
            <p class="hint mt">用于记忆维护与私聊压缩。</p>
          </div>

          <div class="card" data-module-panel="robot-behavior">
            <div class="cardhead"><h3>触发词</h3><span class="grow"></span>
              <span class="hint" id="trigNow"></span></div>
            <div class="tchips" id="trigChips"></div>
            <p class="hint">点击词条可编辑。</p>
            <div class="field mt" id="trigField">
              <div class="inline">
                <input id="trigNew" type="text" placeholder="输入触发词" data-enter="trigAdd"
                       aria-label="新触发词">
                <button class="btn primary" id="trigAdd">添加</button>
              </div>
              <p class="msg" id="trigMsg"></p>
            </div>
            <p class="hint">触发词可能启动模型调用；避免使用常见词。</p>
          </div>

          <div class="card" id="cardParams" data-module-panel="system-runtime">
            <div class="cardhead"><h3>运行参数</h3><span class="grow"></span>
              <div class="param-search"><input id="paramSearch" type="search" placeholder="搜索参数" aria-label="搜索运行参数"></div>
              <button class="btn sm" id="paramResetAll" type="button" title="清除面板值，恢复配置或默认值" hidden>全部恢复默认</button></div>
            <p class="msg" id="paramMsg"></p>
            <div class="rows" id="paramBasic"><div class="empty">读取中…</div></div>
          </div>

          <details class="card" id="cardAdvanced" data-module-panel="system-runtime">
            <summary>
              <svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                   stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 5 7 7-7 7"/></svg>
              <h3>高级参数</h3>
            </summary>
            <div class="cbody">
              <div id="paramAdvanced"><div class="empty">读取中…</div></div>
              <div class="empty" id="paramNoResults" hidden>没有匹配的参数。</div>
            </div>
          </details>
        </section>

        <!-- ═══ 危险操作 ═══════════════════════════════════════ -->
        <section class="view" data-view="danger" aria-labelledby="pt-danger">
          <div class="vhead"><h2 id="pt-danger">系统维护</h2></div>
          <div class="subnav" data-module-nav="system" aria-label="系统设置">
            <button type="button" data-route="system-runtime">运行参数</button>
            <button type="button" data-route="system-network">网络访问</button>
            <button type="button" data-route="danger">运维操作</button>
          </div>

          <div class="card danger">
            <div class="cardhead"><h3>运维操作</h3></div>
            <p class="hint mb">重置只清对话上下文，不删长期记忆。重启约 10 秒，期间消息可能漏掉。</p>
            <div class="rowsep">
              <button class="btn danger" onclick="resetChat(this)">重置对话</button>
              <button class="btn danger-solid" onclick="restartHer(this)">重启机器人</button>
            </div>
          </div>
        </section>

      </div>
    </main>
  </div>
</div>

<!-- ── 门禁：没有令牌（或这把不认）时盖上来 ─────────────────────── -->
<div class="backdrop on" id="gate">
  <div class="sheet gatewrap" role="dialog" aria-modal="true" aria-labelledby="gateTitle">
    <span class="mark" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
           stroke-linecap="round" stroke-linejoin="round"><rect x="4.5" y="10.5" width="15" height="10"
        rx="2.4"/><path d="M8 10.5V7.8a4 4 0 0 1 8 0v2.7"/><path d="M12 14.6v2.4"/></svg></span>
    <h3 id="gateTitle">输入面板令牌</h3>

    <div class="field">
      <div class="inline">
        <input id="gateInput" type="password" placeholder="令牌"
               autocomplete="off" spellcheck="false" data-enter="gateOk" aria-labelledby="gateTitle">
        <button class="btn ghost" id="gateEye" type="button">显示</button>
      </div>
      <p class="msg" id="gateErr"></p>
    </div>
    <div class="foot"><button class="btn primary" id="gateOk">登录</button></div>
  </div>
</div>

<!-- ── 首次配置：三步完成，可随时退出；退出后在机器人页保留待办入口 ── -->
<div class="backdrop" id="setup">
  <div class="sheet setup-sheet" role="dialog" aria-modal="true" aria-labelledby="setupTitle">
    <h3 id="setupTitle">完成初始配置</h3>
    <div class="setup-progress"><span id="setupStepLabel">第 1 步，共 3 步</span>
      <span class="grow"></span><span class="step-track"><i id="setupStepBar"></i></span></div>

    <div class="setup-step" data-setup-step="1">
      <div class="setup-section"><b>身份与消息通道</b><span>1 / 3</span></div>
      <div class="field"><label for="qsOwnerQQ">主人 QQ 号</label>
        <input id="qsOwnerQQ" type="text" inputmode="numeric" autocomplete="off" data-enter="setupNext" placeholder="填写主人 QQ 号"></div>
      <div class="field"><label for="qsQQ">机器人 QQ 号</label>
        <input id="qsQQ" type="text" inputmode="numeric" autocomplete="off" data-enter="setupNext" placeholder="填写机器人 QQ 号"></div>
      <div class="field"><label for="qsToken">NapCat / 机器人共用令牌</label>
        <input id="qsToken" type="password" autocomplete="new-password" spellcheck="false" data-enter="setupNext" placeholder="填写或随机生成">
        <div class="rowsep mt"><button class="btn sm" id="qsTokenGen" type="button">随机生成</button></div></div>
      <div class="field"><label for="qsNapUrl">NapCat HTTP API 地址</label>
        <input id="qsNapUrl" type="url" autocomplete="off" spellcheck="false" data-enter="setupNext" placeholder="http://127.0.0.1:3000"></div>
      <div class="field"><label for="qsGroups">目标群</label>
        <textarea id="qsGroups" rows="3" spellcheck="false" placeholder="一行一个：群号，可在群号后加备注"></textarea></div>
    </div>

    <div class="setup-step" data-setup-step="2" hidden>
      <div class="setup-section"><b>模型服务</b><span>2 / 3</span></div>
      <div class="field"><label for="qsBase">模型接口地址</label>
        <input id="qsBase" type="url" autocomplete="off" spellcheck="false" data-enter="setupNext" placeholder="https://api.example.com/v1"></div>
      <div class="field"><label for="qsKey">模型密钥</label>
        <input id="qsKey" type="password" autocomplete="new-password" spellcheck="false" data-enter="setupNext" placeholder="填写模型服务密钥"></div>
      <div class="field"><label for="qsModel">模型名</label>
        <input id="qsModel" type="text" autocomplete="off" spellcheck="false" data-enter="setupNext" placeholder="填写服务提供的模型 ID"></div>
      <p class="hint">保存后可在模型页管理提供商和模型目录。</p>
    </div>

    <div class="setup-step" data-setup-step="3" hidden>
      <div class="setup-section"><b>名字与触发</b><span>3 / 3</span></div>
      <div class="field"><label for="qsName">机器人名字</label>
        <input id="qsName" type="text" autocomplete="off" placeholder="默认 机魂小悦"></div>
      <div class="field"><label>唤醒词</label>
        <div class="tchips" id="qsWakeChips"></div>
        <div class="inline mt"><input id="qsWakeNew" type="text" autocomplete="off" placeholder="添加一个唤醒词">
          <button class="btn sm" id="qsWakeAdd" type="button">添加</button></div></div>
      <div class="field"><label>触发词</label>
        <div class="tchips" id="qTrigChips"></div>
        <div class="inline mt"><input id="qTrigNew" type="text" autocomplete="off" placeholder="添加一个触发词">
          <button class="btn sm" id="qTrigAdd" type="button">添加</button></div>
        <p class="msg" id="qTrigMsg"></p></div>
      <div class="field"><label for="qsOwnerTitle">主人称呼</label>
        <input id="qsOwnerTitle" type="text" autocomplete="off" placeholder="留空则使用 QQ 昵称"></div>
      <div class="field"><label for="qsPersona">人设正文</label>
        <div class="rowsep"><button class="btn sm" id="qsPersonaLoad" type="button">载入 .md 文件</button>
          <input type="file" id="qsPersonaFile" accept=".md,text/markdown,text/plain" hidden>
          <span class="hint" id="qsPersonaHint">可载入后继续编辑；未填写则保留现有内容。</span></div>
        <textarea id="qsPersona" rows="8" spellcheck="false" aria-label="人设正文"></textarea></div>
    </div>

    <p class="msg" id="setupErr" role="alert"></p>
    <div class="foot setup-foot">
      <button class="btn ghost" id="setupLater" type="button">稍后</button>
      <span class="grow"></span>
      <button class="btn" id="setupBack" type="button" hidden>上一步</button>
      <button class="btn primary" id="setupNext" type="button">下一步</button>
      <button class="btn primary" id="setupSave" type="button" hidden>保存并完成</button>
    </div>
  </div>
</div>

<!-- ── 通用弹窗（改一条 / 填表单 / 二次确认）────────────────────── -->
<div class="backdrop" id="backdrop">
  <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="shTitle">
    <h3 id="shTitle">改一条</h3>
    <p class="desc" id="shDesc"></p>
    <div id="shBody"></div>
    <div class="foot">
      <button class="btn" id="shCancel">取消</button>
      <button class="btn primary" id="shOk">确定</button>
    </div>
  </div>
</div>
<div id="toast" role="status" aria-live="polite"></div>

<script>
/* ⚠️ 页面里**没有**令牌。它从 localStorage 里读（用户打开面板时手输的那一次，
   见 A5：以前内嵌在 HTML 里，公网一映射就等于把钥匙印在门上）。
   ⚠️ `fgPanelToken` / `TOKEN` / `Bearer` 这些**名字是机制，别改**；
      给用户看的字一律叫「令牌」。 */
var TOKEN = "";
try { TOKEN = localStorage.getItem("fgPanelToken") || ""; } catch(e) { TOKEN = ""; }
/* ⚠️ 这一页是不是**远程 / 反代后面**打开的（2026-10-31）：是的话凭据在
   **HttpOnly cookie** 里（页面 / JS 都读不到），页面里一个令牌都没有，
   `/login` 那张登录页才是入口。值由服务端渲染时替换（⛔ 不是用户输入）。 */
var PANEL_REMOTE = __PANEL_REMOTE__;
/* ⚠️ 地址栏那一次（`?token=`）**优先**：拿它当这一次的令牌（和手输那一次一样存 localStorage）。
   地址栏上那一截**已经在 <head> 里抹掉了**（见那一段），不管这把认不认 —— 这里只管"用不用它"。
   ⛔ 值只往 localStorage 走：不进 DOM / title / 链接；用完把这个全局也清空。
   ⚠️ `TOKEN_FROM_URL` 只干两件事：boot() 里说一句"地址栏那截清掉了"，
      以及令牌不认时在门禁上说明"这把是从链接里来的"。 */
var TOKEN_FROM_URL = false;
try {
  if (window.URLTOKEN){
    TOKEN = deepTrim(window.URLTOKEN);   // deepTrim 是下面的函数声明（声明会提升，这里能用）
    TOKEN_FROM_URL = !!TOKEN;
    if (TOKEN) try { localStorage.setItem("fgPanelToken", TOKEN); } catch(e){}
  }
  window.URLTOKEN = "";
} catch(e){ TOKEN_FROM_URL = false; }
var MEM = [], ST = null, SEL = "", USERS = [], GROUPS = [], SEEN = [], REQS = [], REQHIST = [];
// SEL = 现在点开的是谁；GROUPS/SEEN = 群那一页的两份名单；REQS/REQHIST = 申请那一页的两份

function $(s){ return document.querySelector(s) }
function $$(s){ return Array.prototype.slice.call(document.querySelectorAll(s)) }
function hdr(){
  // ⚠️ `X-FG-Panel: 1` 是**防 CSRF** 的：远程那条路凭据在 cookie 里（浏览器自动带），
  //    服务端要求走 cookie 的**非 GET 必须带这个头** —— 跨站表单设不了自定义头。
  //    本机 / 局域网那条路照旧带 `Authorization: Bearer`（localStorage 里那把）。
  var h = {"X-FG-Panel":"1"};
  if (TOKEN) h["Authorization"] = "Bearer " + TOKEN;
  return h;
}
function esc(s){ return String(s==null?"":s).replace(/[&<>"]/g, function(c){
  return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c] }) }

/* ── 输入清洗：填东西不容易错的底子 ─────────────────────────────
   ① 全角转半角（中文输入法下打出来的数字）；
   ② 去掉零宽字符（从聊天软件里复制粘贴最常见的坑）；
   ③ 数字类字段只留数字；地址类只留 host:port。 */
function half(s){
  return String(s==null?"":s).replace(/[\uFF01-\uFF5E]/g, function(c){
    return String.fromCharCode(c.charCodeAt(0) - 0xFEE0);
  }).replace(/\u3000/g, " ");
}
function deepTrim(s){
  // 首尾空白 + 零宽/BOM —— 粘令牌、粘邀请码时最常见的就是这些看不见的东西
  return half(String(s==null?"":s)).replace(/[\u200B-\u200D\uFEFF]/g, "").trim();
}
function digitsOnly(s){ return half(s).replace(/[^0-9]/g, "") }
function tidyHost(s){
  var v = half(s).replace(/\s+/g, "");
  v = v.replace(/^[a-zA-Z][a-zA-Z0-9+.\-]*:\/\//, "");   // 去 http:// https:// 之类
  v = v.replace(/\/.*$/, "");                             // 去路径（含末尾斜杠）
  return v;
}
function hostOk(v){
  if (!v || v.indexOf("://") >= 0 || v.indexOf("/") >= 0) return false;
  var i = v.lastIndexOf(":");
  if (i <= 0 || i === v.length - 1) return false;
  var host = v.slice(0, i), port = v.slice(i + 1);
  if (!/^[A-Za-z0-9.\-]+$/.test(host)) return false;
  if (!/^[0-9]+$/.test(port)) return false;
  var n = parseInt(port, 10);
  return n >= 1 && n <= 65535;
}
function gidOk(v){ return /^[0-9]{5,12}$/.test(v) }

/* ── 字段级提示：**不清空已填内容**，就在这个框下面说错在哪 ─────── */
function fieldBox(el){ return (el && el.closest) ? el.closest(".field") : null }
function fieldErr(el, msg){
  var box = fieldBox(el); if (!box) return;
  var m = box.querySelector(".msg");
  el.classList.toggle("bad", !!msg);
  el.setAttribute("aria-invalid", msg ? "true" : "false");
  if (m) m.textContent = msg || "";
  if (msg){ try { el.focus(); } catch(e){} }
}
function fieldOk(el){ fieldErr(el, "") }

/* ── 数字输入框：边打边清洗（全角/空格/杂字符一进来就没）─────────
   光标按"光标前面有几个数字"还原，所以改中间也不会跳到末尾。 */
function bindNumeric(inp){
  if (!inp) return;
  inp.addEventListener("input", function(){
    var el = this, caret = el.selectionStart || 0;
    var keep = digitsOnly(el.value.slice(0, caret)).length;
    var nv = digitsOnly(el.value);
    if (nv === el.value) return;
    el.value = nv;
    var pos = Math.min(keep, nv.length);
    try { el.setSelectionRange(pos, pos); } catch(e){}
  });
  inp.addEventListener("blur", function(){ fieldOk(this) });
}

/* ══ 主题 ══════════════════════════════════════════════════════ */
var THEME_KEY = "fgPanelTheme";
function applyTheme(t){
  t = (t === "light" || t === "dark") ? t : "auto";
  document.documentElement.setAttribute("data-theme", t);
  try { localStorage.setItem(THEME_KEY, t); } catch(e){}
  var dark = (t === "dark") ||
    (t === "auto" && window.matchMedia && window.matchMedia("(prefers-color-scheme:dark)").matches);
  var m = $("#themeColor"); if (m) m.setAttribute("content", dark ? "#0E1116" : "#F4F7F8");
  $$("#themeSeg .segbtn").forEach(function(b){ b.classList.toggle("on", b.dataset.theme === t) });
}
$$("#themeSeg .segbtn").forEach(function(b){
  b.addEventListener("click", function(){ applyTheme(b.dataset.theme) });
});
if (window.matchMedia) try {
  window.matchMedia("(prefers-color-scheme:dark)").addEventListener("change", function(){
    if ((document.documentElement.getAttribute("data-theme") || "auto") === "auto") applyTheme("auto");
  });
} catch(e){}

/* ══ 分区导航 ══════════════════════════════════════════════════ */
var VNAMES = {overview:"概览", access:"接入与范围", memory:"记忆与对话",
              extensions:"扩展", robot:"机器人", system:"系统"};
var LAST_ROUTE = {access:"groups", robot:"robot-model", system:"system-runtime"};
var ROUTE_MODULE = {
  overview:"overview", access:"access", requests:"access", groups:"access", users:"access",
  memory:"memory", extensions:"extensions", robot:"robot", settings:"robot",
  "robot-identity":"robot", "robot-model":"robot", "robot-behavior":"robot",
  "system-network":"system"
};
function go(v, push){
  v = String(v || "").replace(/^#/, "");
  if (v === "settings") v = "robot-model";
  if (v === "access") v = LAST_ROUTE.access || "groups";
  if (v === "robot") v = LAST_ROUTE.robot || "robot-model";
  if (v === "system") v = LAST_ROUTE.system || "system-runtime";
  var module = ROUTE_MODULE[v];
  if (!module){ v = "overview"; module = "overview" }
  if (module === "access") LAST_ROUTE.access = v;
  if (module === "robot") LAST_ROUTE.robot = v;
  if (module === "system") LAST_ROUTE.system = v;
  var target = (module === "robot" || (module === "system" && v !== "danger"))
    ? "settings" : (module === "system" ? "danger" : v);
  $$(".view").forEach(function(s){ s.classList.toggle("on", s.dataset.view === target) });
  $$("#nav .navi").forEach(function(b){
    var on = b.dataset.go === module;
    b.classList.toggle("on", on);
    if (on) b.setAttribute("aria-current","page"); else b.removeAttribute("aria-current");
  });
  var panel = module === "robot" ? v : (module === "system" ? (v === "danger" ? "danger" : v) : "");
  $$('[data-module-panel]').forEach(function(x){
    x.classList.toggle("module-visible", x.dataset.modulePanel === panel);
  });
  $$('[data-module-nav]').forEach(function(x){ x.hidden = x.dataset.moduleNav !== module });
  $$('.subnav [data-route]').forEach(function(b){
    var on = b.dataset.route === v;
    b.classList.toggle("on", on);
    if (on) b.setAttribute("aria-current","page"); else b.removeAttribute("aria-current");
  });
  var t = $("#pageTitle"); if (t) t.textContent = VNAMES[module];
  var h = $("#pt-settings"); if (h) h.textContent = VNAMES[module] || "机器人";
  if (push !== false){ try { history.replaceState(null, "", "#" + v); } catch(e){} }
  try { window.scrollTo(0, 0); } catch(e){}
}
document.addEventListener("click", function(ev){
  var b = ev.target.closest ? ev.target.closest("[data-go],[data-route]") : null;
  if (!b) return;
  go(b.dataset.route || b.dataset.go);
});
window.addEventListener("hashchange", function(){
  go((location.hash || "").replace("#", ""), false);
});

/* ══ 门禁 ══════════════════════════════════════════════════════ */
function needToken(msg){
  if (PANEL_REMOTE){
    // 远程 / 反代后面：凭据在 cookie 里，失效了去登录页
    location.replace("/login");
    return;
  }
  TOKEN = "";
  try { localStorage.removeItem("fgPanelToken"); } catch(e){}
  hideToken();
  $("#gate").className = "backdrop on";
  $("#gateInput").value = "";
  fieldErr($("#gateInput"), msg || "");
  setTimeout(function(){ $("#gateInput").focus() }, 60);
}
function saveToken(){
  var el = $("#gateInput");
  var v = deepTrim(el.value);
  if (!v){ fieldErr(el, "请输入令牌。"); return; }
  TOKEN = v;
  TOKEN_FROM_URL = false;   // 从这一刻起这把是**手输**的，门禁上"从链接里来的"那句不再适用
  try { localStorage.setItem("fgPanelToken", v); } catch(e){}
  fieldErr(el, "");
  el.value = "";
  $("#gate").className = "backdrop";
  toast("✓ 令牌记在这个浏览器里了", "ok");
  boot();
}
function authFail(msg){
  needToken(msg || "令牌无效，请重新输入。");
  return Promise.reject(new Error("没通过鉴权"));
}
$("#gateOk").addEventListener("click", saveToken);
$("#gateInput").addEventListener("keydown", function(e){
  if (e.key === "Enter"){ e.preventDefault(); saveToken(); }
});
$("#gateEye").addEventListener("click", function(){
  var el = $("#gateInput");
  var show = el.type === "password";
  el.type = show ? "text" : "password";
  this.textContent = show ? "隐藏" : "显示";
  el.focus();
});

/* ══ 退出登录（只有远程 / 反代后面才显示这个按钮）════════════════
   服务端会把这条会话**从内存里删掉**（不是只让浏览器忘掉）—— 原 cookie 再拿来是 403。 */
function doLogout(){
  try { localStorage.removeItem("fgPanelToken"); } catch(e){}
  TOKEN = "";
  function done(){ location.replace("/login") }
  try {
    fetch("/logout", {method:"POST", headers:hdr()}).then(done, done);
  } catch(e){ done() }
}

/* ══ 提示 ══════════════════════════════════════════════════════ */
function toast(msg, kind){
  var t = $("#toast");
  t.textContent = msg;
  t.className = "on" + (kind ? " " + kind : "");
  clearTimeout(t._t);
  t._t = setTimeout(function(){ t.className = kind === "bad" ? "bad" : (kind || "") }, 3400);
}
function say(text, bad){
  var box = $("#log");
  var ph = box.querySelector(".li"); if (ph && !ph.querySelector("time").textContent.match(/[0-9]/))
    box.removeChild(ph);
  var d = document.createElement("div");
  d.className = "li" + (bad ? " bad" : "");
  var now = new Date();
  d.innerHTML = "<time>" + String(now.getHours()).padStart(2,"0") + ":" +
                String(now.getMinutes()).padStart(2,"0") + "</time><span>" + esc(text) + "</span>";
  box.insertBefore(d, box.firstChild);
  while (box.children.length > 40) box.removeChild(box.lastChild);
}
function clearLog(){
  $("#log").innerHTML = '<div class="li"><time>—</time><span>暂无操作记录</span></div>';
}
function busy(btn, on){
  if (!btn) return;
  if (on){ btn._old = btn.innerHTML; btn.innerHTML = '<span class="spin"></span>'; btn.disabled = true }
  else { if (btn._old != null) btn.innerHTML = btn._old; btn._old = null; btn.disabled = false }
}
function fmtUp(s){
  s = s | 0;
  if (s < 60) return s + " 秒";
  if (s < 3600) return Math.floor(s/60) + " 分 " + (s%60) + " 秒";
  return Math.floor(s/3600) + " 小时 " + Math.floor((s%3600)/60) + " 分";
}
function get(path){
  return fetch(path, {headers:hdr()}).then(function(r){
    if (r.status === 401 || r.status === 403) return authFail();
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  });
}
function post(body){
  return fetch("/api", {method:"POST",
    headers:Object.assign({"Content-Type":"application/json"}, hdr()),
    body:JSON.stringify(body)
  }).then(function(r){
    if (r.status === 401 || r.status === 403) return authFail("访问被拒绝（403），请重新登录。");
    if (r.status === 429){
      var wait = r.headers.get("Retry-After") || "?";
      toast("被限流了：还要等 " + wait + " 秒", "bad");
      return {ok:false, message:"被限流了（429），还要等 " + wait + " 秒"};
    }
    if (r.status === 413) return {ok:false, message:"请求太大了（413）"};
    if (r.status === 501) return {ok:false, message:"这个动作她还没实现（501）"};
    return r.text().then(function(t){
      try { return JSON.parse(t) } catch(e){ return {ok:false, message:"返回不是 JSON：" + t.slice(0,90)} }
    });
  });
}

/* ══ 状态 ══════════════════════════════════════════════════════ */
function drawStatus(st){
  ST = st;
  var a = st.agent || {}, th = a["思考"] || {}, pr = a["性格"] || {};
  var on = !!st.ok;
  $("#pill").className = "pill " + (on ? "on" : "off");
  $("#pillTxt").textContent = on ? "在跑" : "没在跑";
  $("#herName").textContent = $("#herName2").textContent = pr["名字"] || "机魂小悦";
  $("#chips").innerHTML = (pr["别名"] || []).map(function(x){
    return '<span class="chip">' + esc(x) + "</span>" }).join("");
  var s = [
    ["agent", a.ready ? "就绪" : (a.note || "还没写")],
    ["已跑", fmtUp(st.uptimeSeconds)],
    ["端口", st.port || "—"],
    ["模型", ((a["模型"]||{})["model"]) || a.note || "—"],
    ["对话", (a["对话线程"]|0) + " 场"],
    ["记着", (a["记着几个人"]|0) + " 个人"],
    ["工具", (a["工具"]||[]).length + " 个"],
    ["提示词", (a["提示词字数"]|0) + " 字"]
  ];
  $("#stats").innerHTML = s.map(function(kv){
    return '<div class="stat"><div class="k">' + esc(kv[0]) + '</div><div class="v">' +
           esc(kv[1]) + "</div></div>";
  }).join("");
  var cur = th["强度"] || "";
  // 思考强度现在在「她的大脑」那张卡里（`#brainEffort`）。/status 是每 15 秒刷新一次的，
  // 顺手把下拉同步过来 —— App 那边改的，面板这边也看得见。
  var es = $("#brainEffort");
  if (es && cur && es.value !== cur && document.activeElement !== es){
    if (PROV && PROV.active){ PROV.active.effort = cur }
    fillSelect(es, effortItems(cur), cur);
  }
  $("#stamp").textContent = "刚刚更新";
  // ⚠️ 触发词在 /status 的 **agent** 里面（a = st.agent），别按顶层读 —— 踩过一次：
  //    存进去了、群里也生效了，面板却一直显示"一个都没有"（读的路径错了 ✗）
  drawTriggers(a["触发词"] || []);
}
function refresh(loud){
  var b = $("#refreshBtn"); if (loud) busy(b, true);
  return get("/status").then(drawStatus).catch(function(e){
    say("读状态失败：" + e, true); toast("读不到她的状态：" + e, "bad");
    $("#pill").className = "pill off"; $("#pillTxt").textContent = "连不上";
  }).then(function(){ if (loud) busy(b, false) });
}

/* ══ 通用动作 ══════════════════════════════════════════════════ */
function act(action, label, extra, btn){
  var body = {action:action};
  if (extra) for (var k in extra) body[k] = extra[k];
  busy(btn, true); say(label + " …");
  return post(body).then(function(r){
    say((r.ok ? "✓ " : "✗ ") + label + "：" + (r.message || ""), !r.ok);
    toast((r.ok ? "" : "没成功：") + (r.message || label), r.ok ? "ok" : "bad");
    if (r.status) drawStatus(r.status); else if (action !== "memory") refresh(false);
    if (r.memory) drawMem(r.memory);
    return r;
  }).catch(function(e){
    say("✗ " + label + " 失败：" + e, true); toast("请求失败：" + e, "bad");
    return {ok:false};
  }).then(function(r){ busy(btn, false); return r });
}

/* ══ 触发词：一个词一个 chip（单独加 / 单独改 / 单独删）══════════
   动作名和参数跟从前一模一样（`triggers` + `words` 整个列表），
   只是面板这边从"一个大框里敲"换成了 chip。 */
var TRIG = [];
function renderTriggers(){
  var box = $("#trigChips");
  if (!TRIG.length){
    box.innerHTML = '<span class="none">还是一个都没有。</span>';
  } else {
    box.innerHTML = TRIG.map(function(w, i){
      return '<span class="tchip"><button class="tt" data-tedit="' + i +
        '" title="点一下改这个词">' + esc(w) + "</button>" +
        '<button class="tx" data-tdel="' + i + '" title="删掉「' + esc(w) + '」" ' +
        'aria-label="删掉这个词">×</button></span>';
    }).join("");
  }
  $("#trigNow").textContent = TRIG.length ? ("现在 " + TRIG.length + " 个") : "一个都没有";
  var box2 = $("#qTrigChips");
  if (box2){
    box2.innerHTML = TRIG.length ? TRIG.map(function(w, i){
      return '<span class="tchip"><span class="tt">' + esc(w) + "</span>" +
        '<button class="tx" data-qtdel="' + i + '" title="删掉「' + esc(w) +
        '」" aria-label="删掉这个词" type="button">×</button></span>';
    }).join("") : '<span class="none">还是一个都没有。</span>';
  }
}
function drawTriggers(list){
  TRIG = (list || []).slice();
  renderTriggers();
}
function saveTriggers(btn, next, label){
  return act("triggers", label || ("触发词 " + next.length + " 个"), {words: next}, btn)
    .then(function(r){
      if (r && r.triggers) drawTriggers(r.triggers);
      else if (r && r.ok) drawTriggers(next);
      else if (r && !r.ok) fieldErr($("#trigNew"), (r.message || "保存失败。"));
      return r;
    });
}
document.addEventListener("click", function(ev){
  var t = ev.target.closest ? ev.target.closest("[data-qtdel]") : null;
  if (!t) return;
  var i = parseInt(t.dataset.qtdel, 10);
  var w = TRIG[i];
  if (w == null) return;
  if ($("#setup").classList.contains("on")){
    TRIG = TRIG.filter(function(x){ return x !== w }); renderTriggers(); return;
  }
  saveTriggers(t, TRIG.filter(function(x){ return x !== w }), "触发词 －" + w);
});

function addTrigger(btn){
  var el = $("#trigNew");
  var w = deepTrim(el.value);
  if (!w){ fieldErr(el, "先写一个词再加。"); return }
  if (/\s/.test(w)){ fieldErr(el, "一次加一个词 —— 词里不能有空格。"); return }
  if (TRIG.indexOf(w) >= 0){ fieldErr(el, "「" + w + "」已经在里面了。"); return }
  fieldErr(el, "");
  saveTriggers(btn, TRIG.concat([w]), "触发词 ＋" + w).then(function(r){
    if (r && r.ok) el.value = "";
  });
}
$("#trigAdd").addEventListener("click", function(){ addTrigger(this) });
document.addEventListener("click", function(ev){
  var t = ev.target.closest ? ev.target.closest("[data-tedit],[data-tdel]") : null;
  if (!t) return;
  var i = parseInt(t.dataset.tedit != null ? t.dataset.tedit : t.dataset.tdel, 10);
  var w = TRIG[i];
  if (w == null) return;
  if (t.dataset.tdel != null){
    sheet("删掉触发词「" + w + "」？",
      "删掉以后，消息里再出现这个词就不会交给她了。存下去立刻生效。",
      null, function(){ saveTriggers(t, TRIG.filter(function(x){ return x !== w }), "触发词 －" + w) },
      "删掉", {danger:true});
    return;
  }
  sheet("改触发词", "改完立刻生效。留空 = 把这个词删掉。", w, function(v){
    var next = TRIG.slice();
    if (!v){ next.splice(i, 1) }
    else { next[i] = v }
    saveTriggers(t, next, "触发词 " + (v || "－" + w));
  }, "存下来", {rows:1, placeholder:"例：摸鱼",
    invalid:function(v){
      if (!v) return "";
      if (/\s/.test(v)) return "一个词里不能有空格。";
      if (v !== w && TRIG.indexOf(v) >= 0) return "「" + v + "」已经在里面了。";
      return "";
    }});
});

/* ══ 记忆 ══════════════════════════════════════════════════════ */
function loadMem(btn){
  busy(btn, true);
  return post({action:"memory"}).then(function(r){
    if (r.memory){ drawMem(r.memory); say("✓ 记忆：" + r.message) }
    else { say("✗ 读记忆失败：" + (r.message || "?"), true); toast("读记忆失败", "bad") }
  }).catch(function(e){ toast("读记忆失败：" + e, "bad") })
    .then(function(){ busy(btn, false) });
}
function drawMem(list){
  MEM = list || [];
  var n = MEM.length, f = MEM.reduce(function(a,p){ return a + (p.facts||[]).length }, 0);
  $("#memCount").textContent = n + " 个人 · " + f + " 条";
  if (SEL && !personOf(SEL)) SEL = "";
  if (!SEL && MEM.length) SEL = MEM[0].qq;
  renderPeople(false);
  drawDetail();
}
function labelOf(p){
  /* 列表上显示什么 —— **三级降级**（用户 2026-10-05 定的）：
       ① **称呼**（`memory.json[qq].name`，最重要的一条 —— 他就靠这个认人）；
       ② **昵称**（还没定过称呼的人才用昵称顶上这个位置）；
       ③ **QQ 号**（兜底，绝不显示空白）。
     ⚠️ 记忆页这份 payload 里的字段名和「用户」页那份**不是一回事**，别串了：
        这里是 `name` = 称呼、`nick` = 昵称、`card` = 群名片。 */
  return p.name || p.nick || p.qq;
}
function matchP(p, q){
  /* 搜索覆盖**五种写法**（占位文字和这里一一对应，别只写一半）：
     称呼 / 昵称 / 群名片 / QQ 号 / 记忆内容。 */
  if (!q) return true;
  q = q.toLowerCase();
  return [p.name, p.nick, p.card, p.qq].concat(p.facts || [])
    .join(" ").toLowerCase().indexOf(q) >= 0;
}
function renderPeople(keepPick){
  var q = deepTrim(($("#memQ") || {}).value || "");
  var hit = MEM.filter(function(p){ return matchP(p, q) });
  if (keepPick && q && hit.length && !hit.some(function(p){ return p.qq === SEL }))
    SEL = hit[0].qq;                                    // 搜出来的第一个自动选中，省一次点击
  if (!hit.length){
    $("#bubs").innerHTML = '<div class="empty">' +
      (MEM.length ? "无匹配人物，请调整搜索。" : "暂无人物记忆。") + "</div>";
    return;
  }
  $("#bubs").innerHTML = hit.map(function(p){
    var cnt = (p.facts || []).length;
    var nm = labelOf(p);
    /* 右侧**永远是 QQ 号**（用户 2026-10-05 定的：那儿以前摆的是昵称 ✗ ——
       昵称只在"没有称呼"时才顶到左边去，右边留给能唯一认人的那串号）。 */
    var sub = p.qq;
    return '<button class="pitem' + (p.qq === SEL ? " on" : "") + '" data-pick="' + esc(p.qq) + '">' +
      '<span class="pname">' + esc(nm) + "</span>" +
      '<span class="pqq">' + esc(sub) + "</span>" +
      '<span class="pnum">' + (cnt ? cnt + " 条" : "空") + "</span></button>";
  }).join("");
}
function drawDetail(){
  var box = $("#memDetail"), p = personOf(SEL);
  if (!p){
    box.innerHTML = '<div class="empty">选择人物，或点击「添加人物」。</div>';
    return;
  }
  var meta = [];
  /* 详情头部把这一行的**全部身份**摆出来（用户 2026-10-05 定的）：
     称呼 / 昵称 / 群名片 / QQ / 更新时间 —— **缺的那项整个不显示**（不写"（空）"），
     QQ 和「更新」是认人的底线，永远在。 */
  if (p.name) meta.push("称呼：" + esc(p.name));
  if (p.nick) meta.push("昵称：" + esc(p.nick));
  if (p.card) meta.push("群名片：" + esc(p.card));
  meta.push("QQ：" + esc(p.qq));
  if (p.at) meta.push("更新：" + esc(p.at));
  var facts = p.facts || [];
  var rows = facts.length ? facts.map(function(ft, i){
    return '<div class="frow"><span class="bdot"></span><span class="ftxt">' + esc(ft) + "</span>" +
      '<span class="fops"><button class="btn ghost sm" data-act="fix" data-qq="' + esc(p.qq) +
      '" data-i="' + i + '" title="修改事实记忆">改</button><button class="btn ghost sm" data-act="del" data-qq="' +
      esc(p.qq) + '" data-i="' + i + '" title="删除事实记忆">删</button></span></div>';
  }).join("") : '<div class="empty">暂无事实记忆。</div>';
  box.innerHTML =
    '<div class="dhead"><span class="dname">' + esc(labelOf(p)) + "</span>" +
    '<span class="grow"></span>' +
    '<button class="btn sm" data-act="name" data-qq="' + esc(p.qq) + '">修改称呼</button>' +
    '<button class="btn sm danger" data-act="person-del" data-qq="' + esc(p.qq) + '">删除人物</button></div>' +
    '<div class="dmeta">' + meta.join(" · ") + "</div>" +
    rows +
    '<div class="addrow"><input type="text" placeholder="输入事实记忆" ' +
    'data-add="' + esc(p.qq) + '"><button class="btn primary" data-act="add" ' +
    'data-qq="' + esc(p.qq) + '">添加</button></div>';
}
function personOf(qq){ for (var i=0;i<MEM.length;i++) if (MEM[i].qq === qq) return MEM[i]; return null }

function addPerson(btn){
  sheetForm("添加人物", "",
    [{key:"qq", label:"QQ 号", required:true, numeric:true, placeholder:"填写 QQ 号"},
     {key:"name", label:"称呼", required:false, placeholder:"输入称呼",
      hint:"留空则使用 QQ 昵称。"}],
    "添加", function(v){
      post({action:"mem_person_add", qq:v.qq, name:v.name}).then(function(r){
        say((r.ok ? "✓ " : "✗ ") + "添加人物：" + r.message, !r.ok);
        toast(r.ok ? "已添加" : ("添加失败：" + r.message), r.ok ? "ok" : "bad");
        if (r.memory){ SEL = v.qq; drawMem(r.memory) }
      });
    });
}
document.addEventListener("click", function(ev){
  var pick = ev.target.closest ? ev.target.closest("button[data-pick]") : null;
  if (pick){ SEL = pick.dataset.pick; renderPeople(false); drawDetail(); return }
  if (ev.target.closest && ev.target.closest("[data-addperson]")){ addPerson(ev.target.closest("[data-addperson]")); return }
  var b = ev.target.closest ? ev.target.closest("button[data-act]") : null;
  if (!b) return;
  var qq = b.dataset.qq; if (!qq) return;        // 没有 data-qq 的是 API 那几条，归下面那个处理器
  var p = personOf(qq), a = b.dataset.act;
  if (a === "name"){
    sheet("修改称呼", "留空则恢复为 QQ 昵称或群名片。",
      (p && p.name) || "", function(v){ act("mem_name", "修改称呼", {qq:qq, name:v}, b) }, "保存",
      {rows:1, placeholder:"输入称呼"});
  } else if (a === "add"){
    var inp = document.querySelector('input[data-add="' + qq + '"]');
    var v = deepTrim(inp && inp.value || "");
    if (!v){ fieldErr(inp, "请输入事实记忆。"); return }
    fieldErr(inp, "");
    act("mem_add", "添加记忆", {qq:qq, text:v}, b).then(function(r){
      if (r.ok && inp) inp.value = "";
    });
    if (inp) inp.value = "";   // ⚠️ 只在这里清；出错时下面那行会把它还回来（见 act 的 catch）
  } else if (a === "fix"){
    var f = (p.facts || [])[+b.dataset.i] || "";
    sheet("修改事实记忆", "留空将删除此条。", f, function(v){
      if (v) act("mem_fix", "修改记忆", {qq:qq, old:f, new:v}, b);
      else sheet("删除事实记忆？", "删除后无法恢复。", null,
        function(){ act("mem_del", "删除记忆", {qq:qq, old:f}, b) }, "删除", {danger:true});
    }, "保存", {rows:3, placeholder:"输入事实记忆"});
  } else if (a === "del"){
    var f2 = (p.facts || [])[+b.dataset.i] || "";
    sheet("删除事实记忆？", "删除后无法恢复。\n" + f2,
      null, function(){ act("mem_del", "删除记忆", {qq:qq, old:f2}, b) }, "删除", {danger:true});
  } else if (a === "person-del"){
    sheet("删除人物？", "将删除称呼和 " + ((p.facts || []).length) + " 条事实记忆，且无法恢复。",
      null, function(){ act("mem_person_del", "删除人物", {qq:qq}, b) }, "删除", {danger:true});
  }
});

/* ══ 她的大脑（提供商 / 模型目录）+ 后台模型 ═══════════════════════
   数据在服务端（llm-apis.txt v2）；⛔ key 只在服务端，这里拿到的永远是打码的。
   改了立刻生效（POST /api 的 providers.*），**成功不提示**，出错才在卡里说一句。 */
var PROV = null;        // GET /providers 那一份
var PEDIT = {};         // pid → 正在编辑、还没保存的 {key, baseUrl, custom}
var POPEN = {};         // pid → 展开着
var PFETCH = {};        // pid → 拉到过 / 拉失败了 {ok, models, error}
var EFF_ALL = ["none", "low", "medium", "high"];

function provOf(pid){
  if (!PROV) return null;
  for (var i = 0; i < PROV.providers.length; i++)
    if (PROV.providers[i].id === pid) return PROV.providers[i];
  return null;
}
function fillSelect(sel, items, value){
  if (!sel) return;
  sel.innerHTML = (items || []).map(function(it){
    return '<option value="' + esc(it.v) + '"' + (it.v === value ? " selected" : "") +
      (it.dis ? " disabled" : "") + ">" + esc(it.t) + "</option>";
  }).join("");
}
function effortItems(cur){
  var list = (PROV && PROV.efforts && PROV.efforts.length ? PROV.efforts : EFF_ALL).slice();
  if (cur && list.indexOf(cur) < 0) list.unshift(cur);
  return list.map(function(v){ return {v:v, t:v} });
}
function providerItems(){
  if (!PROV) return [];
  var out = PROV.providers.map(function(p){ return {v:p.id, t:p.name} });
  if (!out.length) out.push({v:"", t:"（还没添加）"});
  return out;
}
function modelItems(pid){
  var p = provOf(pid);
  var out = (p ? p.models : []).map(function(m){
    return {v:m.id, t:(m.name && m.name !== m.id) ? (m.name + "（" + m.id + "）") : m.id};
  });
  if (!out.length) out.push({v:"", t:"（这家还没有模型）"});
  return out;
}
function drawBrain(){
  if (!PROV) return;
  var act = PROV.active || {};
  var p = provOf(act.provider);
  $("#brainNow").textContent = p ? (p.name + " / " + (act.model || "（没选模型）")) : "";
  fillSelect($("#brainProvider"), providerItems(), act.provider || "");
  fillSelect($("#brainModel"), modelItems(act.provider || ""), act.model || "");
  fillSelect($("#brainEffort"), effortItems(act.effort), act.effort || "");
}
function drawProviders(){
  var box = $("#provList");
  if (!PROV || !box) return;
  if (!PROV.providers.length){
    box.innerHTML = '<div class="empty">还没有提供商。</div>';
    return;
  }
  box.innerHTML = PROV.providers.map(provCard).join("");
}
function provCard(p){
  var open = !!POPEN[p.id];
  var ed = PEDIT[p.id] || {};
  var head = '<div class="phead"><span class="pdot"></span>' +
    '<span class="pname">' + esc(p.name) + "</span>" +
    (p.active ? '<span class="chip ok">在用</span>' : "") +
    '<span class="grow"></span>' +
    '<button class="btn sm" data-pact="edit" data-pid="' + esc(p.id) + '">' +
      (open ? "收起" : "编辑") + "</button>" +
    '<button class="btn sm" data-pact="delprov" data-pid="' + esc(p.id) + '">删除</button></div>';
  if (!open) return '<div class="pcard' + (p.active ? " on" : "") + '">' + head + "</div>";
  var body =
    '<div class="pbody">' +
      '<div class="field"><label class="flab" for="pk_' + esc(p.id) + '">API 密钥</label>' +
        '<input id="pk_' + esc(p.id) + '" type="password" autocomplete="off" spellcheck="false"' +
        ' placeholder="留空使用已保存凭据" data-pk="' + esc(p.id) + '"' +
        ' value="' + esc(ed.key || "") + '">' +
        '<p class="fhint">' + (p.hasKey ? ("已保存 " + esc(p.key)) : "还没填") + "</p></div>" +
      '<details class="pcustom" data-pcust="' + esc(p.id) + '"' + (ed.custom ? " open" : "") + ">" +
        '<summary><svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor"' +
        ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m9 5 7 7-7 7"/></svg>' +
        "自定义设置</summary>" +
        '<div class="field mt"><label class="flab" for="pu_' + esc(p.id) + '">API 地址</label>' +
        '<input id="pu_' + esc(p.id) + '" type="text" autocomplete="off" spellcheck="false"' +
        ' placeholder="' + esc(p.defaultUrl || "https://…/v1") + '" data-pu="' + esc(p.id) + '"' +
        ' value="' + esc(ed.baseUrl != null ? ed.baseUrl : p.baseUrl) + '"></div>' +
      "</details>" +
      '<div class="mtools">' +
        '<button class="btn sm" data-pact="fetch" data-pid="' + esc(p.id) + '">获取可用模型</button>' +
        '<span class="hint" data-fhint="' + esc(p.id) + '"></span>' +
      "</div>" +
      '<p class="msg" data-pmsg="' + esc(p.id) + '"></p>' +
      modelRows(p) +
      '<div class="rowsep mt">' +
        '<button class="btn sm" data-pact="addmodel" data-pid="' + esc(p.id) + '">＋ 添加模型</button>' +
      "</div>" +
      '<div class="rowsep mt">' +
        '<button class="btn" data-pact="cancel" data-pid="' + esc(p.id) + '">取消</button>' +
        '<button class="btn primary" data-pact="save" data-pid="' + esc(p.id) + '">保存</button>' +
      "</div></div>";
  return '<div class="pcard' + (p.active ? " on" : "") + '">' + head + body + "</div>";
}
function modelRows(p){
  if (!p.models.length) return '<div class="empty">目录是空的，用「＋ 添加模型」加。</div>';
  return '<div class="mrows">' + p.models.map(function(m){
    return '<div class="mrow' + (m.active ? " on" : "") + '">' +
      '<span class="mid">' + esc(m.id) + "</span>" +
      '<span class="mname">' + esc(m.name) + "</span>" +
      (m.active ? '<span class="chip ok">在用</span>' :
        '<button class="iconbtn" data-pact="use" data-pid="' + esc(p.id) +
          '" data-mid="' + esc(m.id) + '" title="用这个模型">›<span class="lbl">用</span></button>') +
      '<button class="iconbtn danger" data-pact="delmodel" data-pid="' + esc(p.id) +
        '" data-mid="' + esc(m.id) + '" title="删掉这个模型">' + I.trash + "</button></div>";
  }).join("") + "</div>";
}
function utilityProviderItems(){
  var out = [{v:"", t:"（跟主模型）"}];
  if (PROV) PROV.providers.forEach(function(p){ out.push({v:p.id, t:p.name}) });
  return out;
}
function utilityModelItems(pid){
  if (!pid) return [{v:"", t:"（跟主模型）"}];
  var p = provOf(pid);
  var out = (p ? p.models : []).map(function(m){
    return {v:m.id, t:(m.name && m.name !== m.id) ? (m.name + "（" + m.id + "）") : m.id};
  });
  if (!out.length) out.push({v:"", t:"（这家还没有模型）"});
  return out;
}
function drawUtility(){
  if (!PROV) return;
  var u = PROV.utility || {};
  $("#utilInherit").checked = !!u.inherit;
  $("#utilBox").hidden = !!u.inherit;
  fillSelect($("#utilProvider"), utilityProviderItems(), u.provider || "");
  fillSelect($("#utilModel"), utilityModelItems(u.provider || ""), u.model || "");
  fillSelect($("#utilEffort"), effortItems(u.effort || "low"), u.effort || "low");
}
function drawProvidersData(d){
  PROV = d;
  drawBrain();
  drawProviders();
  drawUtility();
}
function loadProviders(btn){
  busy(btn, true);
  return get("/providers").then(function(d){
    drawProvidersData(d);
  }).catch(function(e){
    say("✗ 读提供商失败：" + e, true);
    $("#brainMsg").textContent = "读不到提供商：" + e;
  }).then(function(){ busy(btn, false) });
}
function pmsg(pid, text){
  var el = document.querySelector('[data-pmsg="' + String(pid).replace(/"/g, "") + '"]');
  if (el) el.textContent = text || "";
  if (!text){ if (el) $("#brainMsg").textContent = ""; return }
  if (!el) $("#brainMsg").textContent = text;      // 卡片收起了也要看得见错
}
function ppost(body, pid){
  return post(body).then(function(r){
    if (r && r.providers) drawProvidersData(r.providers);
    if (!r || !r.ok){
      var msg = (r && r.message) || "没成功，再试一次。";
      if (pid) pmsg(pid, msg); else $("#brainMsg").textContent = msg;
    } else {
      if (pid) pmsg(pid, "");
      if (r.status) drawStatus(r.status);          // 顶栏「模型」跟着变
    }
    return r;
  }).catch(function(e){
    var msg = "请求失败：" + e;
    if (pid) pmsg(pid, msg); else $("#brainMsg").textContent = msg;
    return {ok:false, message:msg};
  });
}
function activateBrain(body){
  body.action = "providers.activate";
  $("#brainMsg").textContent = "";
  return post(body).then(function(r){
    if (r && r.providers) drawProvidersData(r.providers);
    if (!r || !r.ok){
      $("#brainMsg").textContent = (r && r.message) || "没切成功。";
      drawBrain();                                  // 把下拉拨回服务端现在的值
    } else if (r.status) drawStatus(r.status);
    return r;
  }).catch(function(e){
    $("#brainMsg").textContent = "请求失败：" + e;
    drawBrain();
  });
}
$("#brainProvider").addEventListener("change", function(){
  var pid = this.value;
  fillSelect($("#brainModel"), modelItems(pid), "");
  activateBrain({provider:pid, model:$("#brainModel").value || ""});
});
$("#brainModel").addEventListener("change", function(){
  activateBrain({provider:$("#brainProvider").value || "", model:this.value || ""});
});
$("#brainEffort").addEventListener("change", function(){
  activateBrain({provider:$("#brainProvider").value || "",
                 model:$("#brainModel").value || "", effort:this.value});
});

/* 输入没保存时别被重绘冲掉（改 key / 改地址） */
document.addEventListener("input", function(ev){
  var t = ev.target;
  if (!t || !t.dataset) return;
  var pid = t.dataset.pk || t.dataset.pu;
  if (!pid) return;
  var ed = PEDIT[pid] || (PEDIT[pid] = {});
  if (t.dataset.pk) ed.key = t.value; else ed.baseUrl = t.value;
});
document.addEventListener("toggle", function(ev){
  var d = ev.target;
  if (d && d.dataset && d.dataset.pcust){
    var ed = PEDIT[d.dataset.pcust] || (PEDIT[d.dataset.pcust] = {});
    ed.custom = !!d.open;
  }
}, true);

/* 点卡片上的按钮：编辑 / 保存 / 取消 / 删除 / 拉模型 / 加模型 / 用模型 / 删模型 */
document.addEventListener("click", function(ev){
  var b = ev.target.closest ? ev.target.closest("button[data-pact]") : null;
  if (!b) return;
  var a = b.dataset.pact, pid = b.dataset.pid || "", mid = b.dataset.mid || "";
  var p = provOf(pid);
  if (a === "addprov"){ openAddProvider(); return }
  if (a === "edit"){
    POPEN[pid] = !POPEN[pid];
    if (!POPEN[pid]) delete PEDIT[pid];
    drawProviders();
    return;
  }
  if (a === "cancel"){ delete PEDIT[pid]; POPEN[pid] = false; drawProviders(); return }
  if (a === "save"){ saveProvider(pid, b); return }
  if (a === "fetch"){ fetchModels(pid, b); return }
  if (a === "addmodel"){ openModelPicker(pid); return }
  if (a === "use"){
    activateBrain({provider:pid, model:mid});
    return;
  }
  if (a === "delmodel"){
    ppost({action:"providers.delmodel", provider:pid, model:mid}, pid);
    return;
  }
  if (a === "delprov"){
    sheet("删掉「" + ((p && p.name) || pid) + "」？", "它目录里的模型也一起没掉。",
      null, function(){ ppost({action:"providers.delete", provider:pid}); }, "删掉",
      {danger:true});
  }
});

function saveProvider(pid, btn){
  var p = provOf(pid);
  if (!p) return;
  var keyEl = document.getElementById("pk_" + pid);
  var urlEl = document.getElementById("pu_" + pid);
  var body = {action:"providers.save", id:pid, name:p.name,
              baseUrl:urlEl ? deepTrim(urlEl.value) : (p.baseUrl || "")};
  var k = keyEl ? deepTrim(keyEl.value) : "";
  if (k) body.key = k;
  busy(btn, true);
  ppost(body, pid).then(function(r){
    busy(btn, false);
    if (r && r.ok){ delete PEDIT[pid]; POPEN[pid] = false; drawProviders() }
  });
}
function fetchModels(pid, btn){
  var hint = document.querySelector('[data-fhint="' + pid + '"]');
  pmsg(pid, "");
  if (hint) hint.textContent = "";
  busy(btn, true);
  post({action:"providers.fetchmodels", provider:pid}).then(function(r){
    if (r && r.ok){
      PFETCH[pid] = {ok:true, models:r.models || []};
      if (hint) hint.textContent = "拉到 " + (r.models || []).length + " 个，点「添加模型」挑";
    } else {
      PFETCH[pid] = {ok:false, models:[], error:(r && r.message) || ""};
      pmsg(pid, (r && r.message) || "没拉到模型，手动填吧。");
    }
  }).catch(function(e){
    pmsg(pid, "请求失败：" + e);
  }).then(function(){ busy(btn, false) });
}

/* 添加提供商：内置 10 家（已有置灰）+ 自定义 */
function openAddProvider(){
  if (!PROV) return;
  var box = sheetShell("添加提供商", "", "添加", false, "取消");
  var have = {};
  PROV.providers.forEach(function(p){ have[p.id] = true });
  var opts = PROV.builtins.map(function(x){
    return {v:x.id, t:x.name + (have[x.id] ? "（已有）" : ""), dis:!!have[x.id]};
  });
  opts.push({v:"__custom__", t:"自定义"});
  box.innerHTML =
    '<div class="field"><label class="flab" for="npSel">提供商</label>' +
      '<select id="npSel"></select></div>' +
    '<div id="npCustom" hidden>' +
      '<div class="field mt"><label class="flab" for="npName">名字</label>' +
        '<input id="npName" type="text" autocomplete="off" placeholder="例：公司中转"></div>' +
      '<div class="field mt"><label class="flab" for="npUrl">API 地址</label>' +
        '<input id="npUrl" type="text" autocomplete="off" spellcheck="false"' +
        ' placeholder="https://…/v1"></div>' +
    "</div>" +
    '<p class="msg" id="npMsg"></p>';
  fillSelect($("#npSel"), opts, (opts.filter(function(x){ return !x.dis })[0] || opts[opts.length - 1]).v);
  $("#npCustom").hidden = $("#npSel").value !== "__custom__";
  $("#npSel").addEventListener("change", function(){
    $("#npCustom").hidden = this.value !== "__custom__";
  });
  SHEET_ENTER = true;
  SHEET_RUN = function(){
    var v = $("#npSel").value;
    var body = {action:"providers.save"};
    if (v === "__custom__"){
      body.name = deepTrim($("#npName").value);
      body.baseUrl = deepTrim($("#npUrl").value);
      if (!body.name){ fieldErr($("#npName"), "给它起个名字。"); return }
      if (!body.baseUrl){ fieldErr($("#npUrl"), "自定义要填地址。"); return }
    } else {
      var b = (PROV.builtins.filter(function(x){ return x.id === v })[0]) || {};
      body.id = v;
      body.name = b.name || v;
      body.baseUrl = b.baseUrl || "";
    }
    post(body).then(function(r){
      if (!r || !r.ok){ $("#npMsg").textContent = (r && r.message) || "没添加成功。"; return }
      closeSheet();
      if (r.providers) drawProvidersData(r.providers);
      var newId = body.id || null;
      if (!newId && r.providers){
        var hit = r.providers.providers.filter(function(x){ return x.name === body.name })[0];
        newId = hit ? hit.id : null;
      }
      if (newId){ POPEN[newId] = true; drawProviders() }
    }).catch(function(e){ $("#npMsg").textContent = "请求失败：" + e });
  };
  setTimeout(function(){ var s = $("#npSel"); if (s) s.focus() }, 60);
}

/* 添加模型：拉到了就勾选，没拉到就手填（**只开一层弹窗**） */
function openModelPicker(pid){
  var p = provOf(pid);
  if (!p) return;
  var f = PFETCH[pid];
  var has = !!(f && f.ok && (f.models || []).length);
  var box = sheetShell("选择要添加的模型",
    has ? "" : "这家没提供模型列表，手动填。",
    has ? "添加所选" : "添加", false, "取消");
  var have = {};
  p.models.forEach(function(m){ have[m.id] = true });
  if (has){
    box.innerHTML =
      '<div class="toolbar">' +
        '<div class="search">' + I.search +
          '<input id="mpSearch" type="text" placeholder="搜索模型" aria-label="搜索模型"></div>' +
        '<label class="check"><input type="checkbox" id="mpAll"> 全选</label>' +
      "</div>" +
      '<div class="mp-list" id="mpList">' + f.models.map(function(m){
        var done = !!have[m.id];
        return '<label class="mp-item' + (done ? " done" : "") + '">' +
          '<input type="checkbox" data-mid="' + esc(m.id) + '" data-mname="' + esc(m.name) + '"' +
          (done ? " checked disabled" : "") + ">" +
          '<span class="mid">' + esc(m.id) + "</span>" +
          (done ? '<span class="chip">已添加</span>' :
            '<span class="mname">' + esc(m.name) + "</span>") + "</label>";
      }).join("") + "</div>" +
      '<p class="msg" id="mpMsg"></p>';
    $("#mpSearch").addEventListener("input", function(){
      var q = deepTrim(this.value).toLowerCase();
      $$("#mpList .mp-item").forEach(function(it){
        it.style.display = (!q || it.textContent.toLowerCase().indexOf(q) >= 0) ? "" : "none";
      });
    });
    $("#mpAll").addEventListener("change", function(){
      var on = this.checked;
      $$("#mpList input[type=checkbox]").forEach(function(c){
        if (!c.disabled) c.checked = on;
      });
    });
    SHEET_ENTER = false;
    SHEET_RUN = function(){
      var picked = $$("#mpList input[type=checkbox]").filter(function(c){
        return c.checked && !c.disabled;
      }).map(function(c){ return {id:c.dataset.mid, name:c.dataset.mname || c.dataset.mid} });
      if (!picked.length){ $("#mpMsg").textContent = "先勾几个模型。"; return }
      post({action:"providers.addmodels", provider:pid, models:picked}).then(function(r){
        if (!r || !r.ok){ $("#mpMsg").textContent = (r && r.message) || "没添加成功。"; return }
        closeSheet();
        if (r.providers) drawProvidersData(r.providers);
      }).catch(function(e){ $("#mpMsg").textContent = "请求失败：" + e });
    };
    setTimeout(function(){ var s = $("#mpSearch"); if (s) s.focus() }, 60);
    return;
  }
  box.innerHTML =
    '<div class="field"><label class="flab" for="mpId">模型 id</label>' +
      '<input id="mpId" type="text" autocomplete="off" spellcheck="false"' +
      ' placeholder="例：gemini-4-argon"></div>' +
    '<div class="field mt"><label class="flab" for="mpName">显示名</label>' +
      '<input id="mpName" type="text" autocomplete="off" spellcheck="false"' +
      ' placeholder="留空就用 id"></div>' +
    '<p class="msg" id="mpMsg"></p>';
  SHEET_ENTER = true;
  SHEET_RUN = function(){
    var mid = deepTrim($("#mpId").value);
    var nm = deepTrim($("#mpName").value) || mid;
    if (!mid){ fieldErr($("#mpId"), "先填模型 id。"); return }
    post({action:"providers.addmodels", provider:pid, models:[{id:mid, name:nm}]})
      .then(function(r){
        if (!r || !r.ok){ $("#mpMsg").textContent = (r && r.message) || "没添加成功。"; return }
        closeSheet();
        if (r.providers) drawProvidersData(r.providers);
      }).catch(function(e){ $("#mpMsg").textContent = "请求失败：" + e });
  };
  setTimeout(function(){ var s = $("#mpId"); if (s) s.focus() }, 60);
}

/* 后台模型：勾了就立刻存（成功静默） */
function saveUtility(){
  var inh = $("#utilInherit").checked;
  $("#utilBox").hidden = inh;
  $("#utilMsg").textContent = "";
  var body = {action:"providers.utility", inherit:inh};
  if (!inh){
    body.provider = $("#utilProvider").value || "";
    body.model = $("#utilModel").value || "";
    body.effort = $("#utilEffort").value || "low";
  }
  post(body).then(function(r){
    if (r && r.providers) drawProvidersData(r.providers);
    if (!r || !r.ok) $("#utilMsg").textContent = (r && r.message) || "没保存成。";
  }).catch(function(e){ $("#utilMsg").textContent = "请求失败：" + e });
}
$("#utilInherit").addEventListener("change", saveUtility);
$("#utilProvider").addEventListener("change", function(){
  var items = utilityModelItems(this.value);
  fillSelect($("#utilModel"), items, items.length === 1 && items[0].v === "" ? "" : items[0].v);
  saveUtility();
});
$("#utilModel").addEventListener("change", saveUtility);
$("#utilEffort").addEventListener("change", saveUtility);

/* ══ 运行参数（设置页：卡片「运行参数」+ 折叠区「高级参数」）════════
   数据来自 GET /settings：服务端按 `fgbot/settings.py` 的注册表现算，
   每项带 值 / 默认 / 范围 / 来源 / 单位 / 说明 / 生效方式。
   保存只发改动过的项；后端只认注册表里的键，别的忽略。 */
var PARAMS = [];
function paramInputId(key){
  return "p_" + String(key == null ? "" : key).replace(/[^A-Za-z0-9_]/g, "_");
}
function paramRange(it){
  if (it.type !== "int" && it.type !== "float") return "";
  if (it.min == null && it.max == null) return "";
  return "范围 " + (it.min == null ? "…" : it.min) + " ~ " + (it.max == null ? "…" : it.max);
}
function paramRow(it){
  var id = paramInputId(it.key);
  var num = (it.type === "int" || it.type === "float");
  /* 说明只放在悬停提示里（用户 2026-10-30：鼠标停留才浮现，不占版面） */
  var tip = (it.doc || "") + (paramRange(it) ? "（" + paramRange(it) + "）" : "");
  var attrs = ' type="' + (num ? "number" : "text") + '"' +
    ' step="' + (it.type === "float" ? "any" : "1") + '"' +
    (num && it.min != null ? ' min="' + it.min + '"' : "") +
    (num && it.max != null ? ' max="' + it.max + '"' : "") +
    ' autocomplete="off" spellcheck="false"' +
    ' value="' + esc(it.value == null ? "" : it.value) + '"' +
    ' data-param="' + esc(it.key) + '"' +
    ' aria-label="' + esc(it.label) + '"';
  var dl = "";
  if (it.choices && it.choices.length){
    var did = "dl_" + id;
    attrs += ' list="' + did + '"';
    dl = '<datalist id="' + did + '">' + it.choices.map(function(c){
      return '<option value="' + esc(c) + '"></option>' }).join("") + "</datalist>";
  }
  var search = [it.key, it.label, it.groupLabel, it.doc].join(" ").toLowerCase();
  var reset = it.overridden
    ? '<button class="btn ghost sm" type="button" data-param-reset="' + esc(it.key) + '">恢复</button>'
    : '<span class="chip">默认</span>';
  return '<div class="param" data-key="' + esc(it.key) + '" data-search="' + esc(search) + '">' +
    '<div class="param-meta"><label class="plabel" for="' + id + '" title="' + esc(tip) + '">' + esc(it.label) + "</label>" +
    '<span class="chip">' + esc(it.sourceLabel || "") + "</span>" +
    '<span class="chip">' + esc(it.applyLabel || "立即生效") + "</span></div>" +
    '<div class="pctl"><input id="' + id + '"' + attrs + ' title="' + esc(tip) + '">' + dl +
    (it.unit ? '<span class="punit">' + esc(it.unit) + "</span>" : "") + reset +
    "</div></div>";
}
function renderParams(){
  var basic = PARAMS.filter(function(it){ return it.tier === "basic" });
  var adv = PARAMS.filter(function(it){ return it.tier === "advanced" });
  $("#paramBasic").innerHTML = basic.length
    ? basic.map(paramRow).join("")
    : '<div class="empty">没有可调的运行参数。</div>';
  var order = [], by = {};
  adv.forEach(function(it){
    if (!by[it.group]){ by[it.group] = []; order.push(it.group) }
    by[it.group].push(it);
  });
  $("#paramAdvanced").innerHTML = order.length ? order.map(function(g){
    var list = by[g];
    return '<div class="pgroup"><div class="pgrouphead">' +
      esc(list[0].groupLabel || g) + "</div>" + list.map(paramRow).join("") + "</div>";
  }).join("") : '<div class="empty">没有高级参数。</div>';
  var reset = $("#paramResetAll");
  if (reset) reset.hidden = !PARAMS.some(function(it){ return !!it.overridden });
  filterParams($("#paramSearch") ? $("#paramSearch").value : "");
}
function filterParams(query){
  var q = String(query || "").trim().toLowerCase(), count = 0;
  $$(".param").forEach(function(row){
    var hit = !q || String(row.dataset.search || "").indexOf(q) >= 0;
    row.hidden = !hit; if (hit) count++;
  });
  $$("#paramAdvanced .pgroup").forEach(function(group){
    group.hidden = !group.querySelector(".param:not([hidden])");
  });
  var adv = $("#cardAdvanced");
  if (adv && q) adv.open = true;
  if (adv && !q) adv.open = false;
  var empty = $("#paramNoResults"); if (empty) empty.hidden = count > 0;
}
function resetParam(key, btn){
  var it = paramItem(key); if (!it || !it.overridden) return;
  busy(btn, true);
  post({action:"settings.reset", key:key}).then(function(r){
    if (r && r.settings && r.settings.items){ PARAMS = r.settings.items; renderParams() }
    if (r && r.ok){ $("#paramMsg").textContent = (r.message || "已恢复") + " · " + (it.applyLabel || "立即生效") }
    else $("#paramMsg").textContent = (r && r.message) || "恢复失败";
  }).catch(function(e){ $("#paramMsg").textContent = "恢复失败：" + e })
    .then(function(){ busy(btn, false) });
}
function resetAllParams(btn){
  if (!PARAMS.some(function(it){ return !!it.overridden })) return;
  busy(btn, true);
  post({action:"settings.reset"}).then(function(r){
    if (r && r.settings && r.settings.items){ PARAMS = r.settings.items; renderParams() }
    $("#paramMsg").textContent = r && r.ok
      ? ((r.message || "已恢复默认") + " · 参数立即生效")
      : ((r && r.message) || "恢复失败");
  }).catch(function(e){ $("#paramMsg").textContent = "恢复失败：" + e })
    .then(function(){ busy(btn, false) });
}
$("#paramSearch").addEventListener("input", function(){ filterParams(this.value) });
document.addEventListener("click", function(ev){
  var b = ev.target.closest ? ev.target.closest("[data-param-reset]") : null;
  if (b){ resetParam(b.dataset.paramReset, b); return }
  if (ev.target && ev.target.id === "paramResetAll") resetAllParams(ev.target);
});
function paramItem(key){
  for (var i = 0; i < PARAMS.length; i++) if (PARAMS[i].key === key) return PARAMS[i];
  return null;
}
function showPMsg(sel, text, bad){
  var el = $(sel); if (!el) return;
  el.textContent = text || "";
  el.className = "pmsg" + (bad ? " bad" : (text ? " ok" : ""));
}
function loadParams(btn){
  busy(btn, true);
  return get("/settings").then(function(d){
    if (!d || !d.items) throw new Error("快照不完整");
    PARAMS = d.items;
    renderParams();
  }).catch(function(e){
    $("#paramBasic").innerHTML = '<div class="empty">读不到运行参数：' + esc(e) + "</div>";
    $("#paramAdvanced").innerHTML = '<div class="empty">读不到高级参数：' + esc(e) + "</div>";
  }).then(function(){ busy(btn, false) });
}
/* 改了就存（用户 2026-10-30 定）：失焦 / 回车即保存。
   ⛔ 成功什么都不提示 ✗；被夹了就把框里数字换成夹后的值（这就是反馈 ✓）；
   只有真的没存上才在输入框下面红字说一句 ✓ */
function saveParamOne(key, el){
  var it = paramItem(key);
  if (!it || !el) return;
  var was = (it.value == null ? "" : String(it.value));
  var now = String(el.value == null ? "" : el.value).trim();
  if (now === was) return;
  fieldErr(el, "");
  post({action:"settings.save", values:((function(){ var o = {}; o[key] = now; return o })())})
    .then(function(r){
      if (r && r.settings && r.settings.items) PARAMS = r.settings.items;
      if (!(r && r.ok)){ fieldErr(el, (r && r.message) || "没存上"); return }
      var cur = paramItem(key);
      var saved = (cur && cur.value != null) ? String(cur.value) : now;
      if (saved !== now) el.value = saved;          // 被夹 → 写回夹后的值
      $("#paramMsg").textContent = "已保存 · " + ((cur && cur.applyLabel) || "立即生效");
      renderParams();
    })
    .catch(function(e){ fieldErr(el, "没存上：" + e) });
}
document.addEventListener("change", function(ev){
  var el = ev.target;
  if (el && el.dataset && el.dataset.param) saveParamOne(el.dataset.param, el);
});
document.addEventListener("keydown", function(ev){
  var el = ev.target;
  if (ev.key === "Enter" && el && el.dataset && el.dataset.param){ ev.preventDefault(); el.blur() }
});

/* ══ 弹窗（改一条 / 填表单 / 二次确认）══════════════════════════
   三种：
     · sheet(...)      单个输入框（或 value=null 时只有确认）
     · sheetForm(...)  一组**分开的、带标签的输入项**（加人 / 改资料用这个）
   共同点：出错时**不清空、不关闭**，就在那个框下面说错在哪；
           危险动作传 {danger:true}，确认键变红。 */
var SHEET_RUN = null, SHEET_ENTER = false;
function sheetShell(title, desc, okLabel, danger, cancelLabel){
  $("#shTitle").textContent = title;
  $("#shDesc").textContent = desc || "";
  $("#shBody").innerHTML = "";
  var ok = $("#shOk");
  ok.textContent = okLabel || "确定";
  ok.className = "btn " + (danger ? "danger-solid" : "primary");
  $("#shCancel").textContent = cancelLabel || "取消";
  $("#backdrop").className = "backdrop on";
  return $("#shBody");
}
function finishSheet(fn, arg){ closeSheet(); if (fn) fn(arg) }
function closeSheet(){ $("#backdrop").className = "backdrop"; $("#shBody").innerHTML = "";
  SHEET_RUN = null; SHEET_ENTER = false }
function sheetSubmit(){ var f = SHEET_RUN; if (f) f() }

/* 单个输入框：value === null → 纯确认 */
function sheet(title, desc, value, onOk, okLabel, opts){
  opts = opts || {};
  var box = sheetShell(title, desc, okLabel, opts.danger, value === null ? "算了" : "取消");
  if (value === null){
    SHEET_ENTER = false;
    SHEET_RUN = function(){ finishSheet(onOk, null) };
    setTimeout(function(){ $("#shOk").focus() }, 60);
    return;
  }
  var rows = opts.rows || 3;
  SHEET_ENTER = (rows === 1);
  box.innerHTML = '<div class="field"><textarea id="shInput" rows="' + rows +
    '" spellcheck="false"' + (opts.readonly ? " readonly" : "") +
    '></textarea><p class="msg"></p></div>';
  var ta = $("#shInput");
  ta.value = value || "";
  ta.placeholder = opts.placeholder || "一句话，简洁点";
  ta.setAttribute("aria-label", title);
  SHEET_RUN = function(){
    var raw = ta.value;
    if (opts.invalid){ var m = opts.invalid(raw); if (m){ fieldErr(ta, m); return } }
    finishSheet(onOk, deepTrim(opts.fix ? opts.fix(raw) : raw));
  };
  setTimeout(function(){ ta.focus(); if (rows === 1) ta.select() }, 60);
}

/* 一组带标签的输入项：fields = [{key,label,value,placeholder,hint,required,
   numeric,pattern,patternMsg,options,note,live}]
   · note:true    → 多留一个 `p.fnote`（**实时提示**，例如"填完 QQ 立刻取到的昵称"）；
                    跟 `.msg`（出错用的那个，红的）分开，免得互相覆盖。
   · live(el,f,i) → 渲染完调一次，调用方自己挂输入事件（见 bindQQLookup）。 */
function sheetForm(title, desc, fields, okLabel, onSubmit, opts){
  opts = opts || {};
  var box = sheetShell(title, desc, okLabel, opts.danger, "取消");
  var LID = "sfList";
  box.innerHTML = fields.map(function(f, i){
    var lab = '<label class="flab" for="sf' + i + '">' + esc(f.label) +
      (f.required ? "<em>必填</em>" : '<span class="opt">可空</span>') + "</label>";
    var inp = '<input id="sf' + i + '" type="' + (f.type || "text") + '" autocomplete="off"' +
      ' spellcheck="false"' + (f.numeric ? ' inputmode="numeric"' : "") +
      (f.options && f.options.length ? ' list="' + LID + '"' : "") +
      (f.value ? ' value="' + esc(f.value) + '"' : "") +
      ' placeholder="' + esc(f.placeholder || "") + '" aria-label="' + esc(f.label) + '">';
    var dl = (f.options && f.options.length)
      ? '<datalist id="' + LID + '">' + f.options.map(function(o){
          return "<option value=\"" + esc(o) + "\"></option>" }).join("") + "</datalist>"
      : "";
    return '<div class="field' + (i ? " mt" : "") + '">' + lab + inp + dl +
      (f.hint ? '<p class="fhint">' + f.hint + "</p>" : "") +
      (f.note ? '<p class="fhint fnote"></p>' : "") +
      '<p class="msg"></p></div>';
  }).join("");
  var els = fields.map(function(f, i){ return $("#sf" + i) });
  fields.forEach(function(f, i){
    if (f.numeric) bindNumeric(els[i]);
    if (typeof f.live === "function"){ try { f.live(els[i], f, i) } catch(e){} }
  });
  SHEET_ENTER = true;
  SHEET_RUN = function(){
    var vals = {}, firstBad = null;
    fields.forEach(function(f, i){
      var el = els[i], v = deepTrim(el.value);
      if (f.numeric) v = digitsOnly(v);
      if (el.value !== v) el.value = v;                 // 就地收拾干净给他看
      var msg = "";
      if (f.required && !v) msg = f.label + "不能空。";
      else if (v && f.pattern && !f.pattern.test(v)) msg = f.patternMsg || (f.label + "格式不对。");
      fieldErr(el, msg);
      if (msg && !firstBad) firstBad = el;
      vals[f.key] = v;
    });
    if (firstBad){ firstBad.focus(); return }
    finishSheet(onSubmit, vals);
  };
  setTimeout(function(){ els[0].focus() }, 60);
}
$("#shCancel").addEventListener("click", closeSheet);
$("#backdrop").addEventListener("click", function(e){ if (e.target === this) closeSheet() });
$("#shOk").addEventListener("click", sheetSubmit);
document.addEventListener("keydown", function(e){
  if (e.key === "Escape"){ closeSheet(); return }
  if ($("#backdrop").className.indexOf("on") < 0) return;
  if (e.key === "Enter"){
    if (SHEET_ENTER){ e.preventDefault(); sheetSubmit(); return }
    if (e.metaKey || e.ctrlKey){ e.preventDefault(); sheetSubmit() }
  }
});
/* Enter 提交：`data-enter="某个按钮的 id"`；记忆里那种"加一条"输入框单独认。
   ⚠️ 弹窗开着的时候按键归弹窗管，别再顺手把背后的按钮点了。 */
document.addEventListener("keydown", function(e){
  if (e.key !== "Enter" || e.isComposing || e.shiftKey) return;
  if ($("#backdrop").className.indexOf("on") >= 0) return;
  var t = e.target;
  if (!t || !t.getAttribute) return;
  var id = t.getAttribute("data-enter");
  if (id){ e.preventDefault(); var b = document.getElementById(id); if (b) b.click(); return }
  var inp = t.closest ? t.closest("input[data-add]") : null;
  if (!inp) return;
  var btn = document.querySelector('button[data-act="add"][data-qq="' + inp.dataset.add + '"]');
  if (btn) btn.click();
});

/* 行尾那几颗小图标（内联 SVG，一个外链都没有） */
var I = {
  key:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="14" r="4.1"/><path d="m11 11 8-8"/><path d="m16.6 5.4 2.2 2.2"/><path d="m14 8 2.2 2.2"/></svg>',
  pen:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4L19.5 8.5a2.1 2.1 0 0 0-3-3L5 17v3z"/><path d="m15 6 3 3"/></svg>',
  trash:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 7h15"/><path d="M9.5 7V4.8h5V7"/><path d="M6.5 7l1 12.2h9L17.5 7"/><path d="M10.5 11v5M13.5 11v5"/></svg>',
  note:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M5 4.5h14v15H5z"/><path d="M8.5 9h7M8.5 12.5h7M8.5 16h4"/></svg>',
  plus:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>',
  eyeoff:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M3 3l18 18"/><path d="M10.6 6.3A9.7 9.7 0 0 1 12 6.2c5 0 9 5.8 9 5.8a17 17 0 0 1-3 3.5"/><path d="M6.3 8.1A16.6 16.6 0 0 0 3 12s4 5.8 9 5.8a9.4 9.4 0 0 0 3.4-.6"/><path d="M9.9 10a3 3 0 0 0 4.2 4.2"/></svg>',
  search:'<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="10.5" cy="10.5" r="6.2"/><path d="m15.3 15.3 4.5 4.5"/></svg>'
};

/* ══ 用户管理 ══════════════════════════════════════════════════
   动作走 POST /api 的 user.*（契约 E1 的动作名）；**只有主人**能调，
   别人调会拿到 403 空正文（B6）—— 上面的 post() 会把它变成"重新粘令牌"。 */
function loadUsers(btn){
  busy(btn, true);
  return post({action:"user.list"}).then(function(r){
    if (r && r.users){
      drawUsers(r.users);
      if (typeof r.publicUrl === "string" && document.activeElement !== $("#pubUrl"))
        $("#pubUrl").value = r.publicUrl;
      say("✓ 用户表：" + r.users.length + " 个人" + (r.主人模式 ? "（主人模式开着）" : ""));
    } else {
      say("✗ 读用户表失败：" + ((r && r.message) || "?"), true);
    }
    return r;
  }).catch(function(e){ say("✗ 读用户表失败：" + e, true); return null })
    .then(function(r){ busy(btn, false); return r });
}
function drawUsers(list){
  USERS = list || [];
  var others = USERS.filter(function(u){ return !u["主人"] }).length;
  $("#userCount").textContent = others + " 个接入的人";
  $("#impCount").textContent = USERS.length + " 个人的令牌";
  renderUsers();
}
function renderUsers(){
  var q = deepTrim(($("#userQ") || {}).value || "").toLowerCase();
  var hit = USERS.filter(function(u){
    if (!q) return true;
    return [u.id, u["显示名"], u["名字"], u["称呼"], u["昵称"], u["主人QQ"], u["备注"],
            u["主人"] ? "主人" : ""].join(" ").toLowerCase().indexOf(q) >= 0;
  });
  if (!USERS.length){
    $("#userList").innerHTML = '<div class="empty">还没有别人接入。点上面的「＋ 新增」加一个。</div>';
    return;
  }
  if (!hit.length){
    $("#userList").innerHTML = '<div class="empty">没找到 —— 换个词试试。</div>';
    return;
  }
  /* 一行一个人：**抬头 = 显示名**（备注 → 称呼 → 昵称 → QQ 号），
     下面弱化地摆四种别名（备注 / 称呼 / 昵称 / QQ），缺哪个就写"没填/没定/没取到"。 */
  $("#userList").innerHTML = hit.map(function(u){
    var bits = [];
    bits.push("备注 " + (u["名字"] ? esc(u["名字"]) : "没填"));
    bits.push("称呼 " + (u["称呼"] ? esc(u["称呼"]) : "没定"));
    bits.push("昵称 " + (u["昵称"] ? esc(u["昵称"]) : "没取到"));
    if (u["主人QQ"]) bits.push("QQ " + esc(u["主人QQ"]));
    else bits.push("QQ 没填");
    bits.push(u["最后心跳"] ? ("心跳 " + esc(u["最后心跳"])) : "还没收到过心跳");
    bits.push("id " + esc(u.id));
    return '<div class="fact"><span class="dot" style="background:' +
      (u["心跳新鲜"] ? "var(--ok)" : "var(--faint)") + '"></span>' +
      '<div class="txt"><b>' + esc(u["显示名"] || u["名字"] || u.id) + "</b>" +
      (u["主人"] ? ' <span class="chip accent">主人</span>' : "") +
      '<div class="hint">' + bits.join(" · ") + "</div></div>" +
      '<span class="rowacts">' +
        '<button class="iconbtn" data-invite="' + esc(u.id) + '"' +
        (u["邀请码"] ? ' title="邀请码（整行给对方）"' : ' title="还没填公网地址，邀请码生不出来"') +
        ">" + I.key + '<span class="lbl">邀请码</span></button>' +
        '<button class="iconbtn" data-edit="' + esc(u.id) + '" title="改 QQ / 备注 / 群号 / 记事">' +
        I.pen + '<span class="lbl">改</span></button>' +
        '<span class="sep"></span>' +
        '<button class="iconbtn danger" data-revoke="' + esc(u.id) + '" title="撤销他那把令牌">' +
        I.trash + '<span class="lbl">撤销</span></button>' +
      "</span></div>";
  }).join("");
}
function userOf(id){ for (var i=0;i<USERS.length;i++) if (USERS[i].id === id) return USERS[i]; return null }
/* 填过的群号（群名单 + 最近见过的群 + 用户表）—— 当输入建议用，省得去 QQ 里翻 */
function knownGroups(){
  var out = [];
  function push(v){ v = String(v == null ? "" : v).trim();
    if (v && out.indexOf(v) < 0) out.push(v) }
  GROUPS.forEach(function(g){ push(g.id) });
  SEEN.forEach(function(g){ push(g.id) });
  return out;
}
/* ── 用户管理：QQ 号填完**立刻把昵称取出来给他核** ────────────────
   用户 2026-10-04 点名要的（"这是填内容不会出错的关键：填错当场能看出来"）。
   走控制面动作 `user.nick`（只有主人能调；值只在响应里，⛔ 不拼进页面、不进日志）。 */
function bindQQLookup(el){
  var box = fieldBox(el), out = box ? box.querySelector(".fnote") : null;
  var last = "", timer = null;
  function show(t, cls){
    if (!out) return;
    out.textContent = t || "";
    out.className = "fhint fnote" + (cls ? " " + cls : "");
  }
  function look(){
    var q = digitsOnly(el.value);
    if (q === last) return;                       // 这个号已经查过了（成功或失败都算）
    last = q;
    if (!q){ show(""); return }
    if (!/^[0-9]{4,12}$/.test(q)){ show("QQ 号是 4~12 位数字。"); return }
    show("正在取昵称…");
    post({action:"user.nick", qq:q}).then(function(r){
      if (digitsOnly(el.value) !== q) return;     // 这期间又改了 → 这条结果丢掉
      if (r && r.nick) show("这个号的昵称：" + r.nick + " —— 核对一下，别填错号", "ok");
      else show((r && r.message) || "取不到昵称 —— 照样能存，以后会显示称呼", "bad");
    }).catch(function(e){ show("取昵称失败：" + e, "bad") });
  }
  el.addEventListener("input", function(){
    last = "";                                    // 改了号 → 允许重查
    clearTimeout(timer); timer = setTimeout(look, 450);
  });
  el.addEventListener("blur", look);
  if (digitsOnly(el.value)) setTimeout(look, 60);  // 改已有记录：一打开就先取一次
}
function userFields(u){
  u = u || {};
  var groups = knownGroups();
  return [
    {key:"qq", label:"QQ 号", numeric:true, required:true, value:(u["主人QQ"] || ""),
     placeholder:"填写 QQ 号",
     pattern:/^[0-9]{4,12}$/, patternMsg:"QQ 号是 4~12 位数字。",
     note:true, live:bindQQLookup,
     hint:"填完会把这个号的昵称取出来给你核。"},
    {key:"name", label:"备注", required:false, value:u["名字"] || "", placeholder:"输入备注（可选）",
     hint:"<b>留空显示机器人称呼</b>；未设置时显示 QQ 号。"},
  ];
}
/* 刚加的那个人的邀请码：`user.add` 回来的 `users` 里就有（按 `新用户.id` 认人）。
   ⚠️ 码是**敏感串**：只在内存里用一下，⛔ 不写进页面初值、不进日志。 */
function freshInvite(r){
  var nu = (r && r["新用户"]) || null, list = (r && r.users) || [];
  if (!nu || !nu.id) return "";
  for (var i=0;i<list.length;i++) if (list[i].id === nu.id) return list[i]["邀请码"] || "";
  return "";
}
function addUser(){
  sheetForm("加一个人（发一把新令牌）",
    "QQ 号必填；备注和群号留空也行。",
    userFields(null), "发码", function(v){
      var body = {action:"user.add", name:v.name, qq:v.qq};
      if (v.group) body.group = v.group;
      post(body).then(function(r){
        say((r && r.ok ? "✓ " : "✗ ") + "发新码：" + ((r && r.message) || "?"), !(r && r.ok));
        if (r && r.users) drawUsers(r.users);
        if (!(r && r.ok)){ toast("没发成：" + ((r && r.message) || "?"), "bad"); return }
        var code = freshInvite(r);
        if (!code){ toast("发好了 —— 点行尾的「邀请码」给他", "ok"); return }
        // 新码**默认就进剪贴板**；浏览器不让复制就把码摆出来全选好（见 copySecret）
        copySecret(code, (r["新用户"] && (r["新用户"].名字 || r["新用户"].id)) || "新的人");
      });
    });
}
function editUser(id){
  var u = userOf(id) || {};
  var fs = userFields(u);
  fs.push({key:"note", label:"记事", required:false, value:u["备注"] || "",
           placeholder:"输入设备名称", hint:"仅用于区分设备。"});
  sheetForm("改「" + (u["显示名"] || u["名字"] || id) + "」",
    "QQ 号必填（清空就认不出这个人了）；备注 / 群号清空 = 落回默认。",
    fs, "存下来", function(v){
      post({action:"user.set", id:id, name:v.name, group:v.group, qq:v.qq, note:v.note})
        .then(function(r){
          say((r && r.ok ? "✓ " : "✗ ") + "改用户：" + ((r && r.message) || "?"), !(r && r.ok));
          toast(r && r.ok ? "改好了" : ("没改成：" + ((r && r.message) || "?")), r && r.ok ? "ok" : "bad");
          if (r && r.users) drawUsers(r.users);
        });
    });
}
/* 把一段文字塞进剪贴板：**只负责"成没成"**（`cb(true/false)`），话由调用方说。
   ⚠️ 非 HTTPS 的局域网页面（这个面板最常见的打开方式）浏览器会拦
   `navigator.clipboard`，所以必须留 `execCommand` 那条老路。 */
function clipCopy(t, cb){
  function fallback(){
    try {
      var ta = document.createElement("textarea");
      ta.value = t; ta.setAttribute("readonly","");
      ta.style.position = "fixed"; ta.style.top = "0"; ta.style.left = "-9999px";
      document.body.appendChild(ta); ta.select(); ta.setSelectionRange(0, t.length);
      var ok = document.execCommand("copy");
      document.body.removeChild(ta);
      cb(ok);
    } catch(e){ cb(false) }
  }
  if (navigator.clipboard && navigator.clipboard.writeText && window.isSecureContext)
    navigator.clipboard.writeText(t).then(function(){ cb(true) }, fallback);
  else fallback();
}
function copyText(t, btn){
  clipCopy(t, function(ok){
    if (ok){
      toast("复制好了 ✓", "ok");
      if (btn && !btn._copied){
        btn._copied = true; var old = btn.innerHTML;
        btn.innerHTML = "已复制 ✓"; btn.classList.add("done");
        setTimeout(function(){ btn.innerHTML = old; btn.classList.remove("done"); btn._copied = false }, 1500);
      }
    } else toast("浏览器不让自动复制 —— 自己选中复制一下", "bad");
  });
}
/* 复制**敏感串**（邀请码，含令牌）：成了就一句短的「已复制」；
   浏览器不让复制 → **这一次**把码摆出来、全选好，让他手动复制（⛔ 绝不许静默失败）。
   ⛔ 码只在这次点击时进 DOM（不写进页面初值）、不进日志。 */
function copySecret(code, who){
  clipCopy(code, function(ok){
    if (ok){ toast("已复制", "ok"); return }
    say("✓ " + who + " 的邀请码显示出来了（浏览器不让自动复制）");
    sheet("邀请码（" + who + "）",
      "浏览器不让自动复制（非 HTTPS 的局域网页面上会被拦）。\n" +
      "⚠️ 含他那把令牌，别发到群里。\n自己选中复制一下 —— 关掉就没了。",
      code, function(){}, "关闭", {rows:1, readonly:true});
  });
}
function showInvite(id){
  var u = userOf(id) || {};
  var who = u["显示名"] || u["名字"] || id;
  post({action:"user.invite", id:id}).then(function(r){
    if (r && r.users) drawUsers(r.users);
    if (!r || !r.invite){
      toast("生不出来：" + ((r && r.message) || "?"), "bad");
      say("✗ 邀请码：" + ((r && r.message) || "?"), true);
      return;
    }
    say("✓ " + who + " 的邀请码好了");
    copySecret(r.invite, who);
  });
}
function revokeUser(id){
  var u = userOf(id) || {};
  sheet("撤销「" + (u["显示名"] || u["名字"] || id) + "」？",
    "· 他那把令牌立刻作废，只影响他一个。\n· 心跳缓存也一起删掉。\n· 他要用得重新拿一条邀请码。\n" +
    "（这个动作不能撤销。）",
    null, function(){
      post({action:"user.del", id:id}).then(function(r){
        say((r && r.ok ? "✓ " : "✗ ") + "撤销：" + ((r && r.message) || "?"), !(r && r.ok));
        toast(r && r.ok ? "撤销了" : ("没撤销：" + ((r && r.message) || "?")), r && r.ok ? "ok" : "bad");
        if (r && r.users) drawUsers(r.users);
      });
    }, "撤销", {danger:true});
}
function savePub(btn){
  var el = $("#pubUrl");
  var v = tidyHost(el.value);
  if (v && !hostOk(v)){
    fieldErr(el, "形状不对：要「域名或IP:端口」，端口 1~65535，不带 http://、不带斜杠。" +
      (v.indexOf(":") < 0 ? "（少了冒号和端口）" : ""));
    return;
  }
  if (el.value !== v) el.value = v;                 // 把 http:// 和末尾斜杠摘掉给他看
  fieldErr(el, "");
  busy(btn, true);
  post({action:"user.publicurl", value:v}).then(function(r){
    say((r && r.ok ? "✓ " : "✗ ") + "公网地址：" + ((r && r.message) || "?"), !(r && r.ok));
    if (r && r.ok) fieldErr(el, "");
    else fieldErr(el, (r && r.message) || "保存失败。");
    toast(r && r.ok ? "已保存" : ("保存失败：" + ((r && r.message) || "?")), r && r.ok ? "ok" : "bad");
    if (r && r.users) drawUsers(r.users);
    if (r && typeof r.publicUrl === "string") el.value = r.publicUrl;
  }).catch(function(e){ toast("请求失败：" + e, "bad"); fieldErr(el, "请求失败：" + e) })
    .then(function(){ busy(btn, false) });
}
$("#pubSave").addEventListener("click", function(){ savePub(this) });
$("#pubCopy").addEventListener("click", function(){
  var v = tidyHost($("#pubUrl").value);
  if (!v){ fieldErr($("#pubUrl"), "这里还是空的 —— 先填一个再复制。"); return }
  copyText(v, this);
});

/* ══ 共享令牌：登录之后才点得动（动作 `token.show`；⛔ 页面里永远不嵌它）─────
   ⚠️ 值只从 `/api` 的响应里来（已鉴权 + **只有主人**能调，别人 403 空正文）。
      日志里只写"谁看了令牌"，**一个字节的值都不落日志**；
      门禁再盖上来（令牌不认了）时把它从 DOM 里收回去。 */
function hideToken(){
  var box = $("#tokBox"); if (box) box.style.display = "none";
  var v = $("#tokVal"); if (v) v.value = "";
  var b = $("#tokBtn"); if (b) b.textContent = "🔑 看共享令牌";
}
function showToken(btn){
  busy(btn, true);
  return post({action:"token.show"}).then(function(r){
    var v = (r && r.token) || "";
    if (!r || !r.ok || !v){
      hideToken();
      say("✗ 看共享令牌：" + ((r && r.message) || "这台手机没把令牌给我"), true);
      toast("拿不到令牌：" + ((r && r.message) || "?"), "bad");
      return r;
    }
    $("#tokVal").value = v;
    $("#tokBox").style.display = "block";
    $("#tokBtn").textContent = "隐藏";
    say("✓ 共享令牌显示出来了（只有主人能看 —— 别发群里）");
    toast("在下面那个框里，可以直接点「复制」", "ok");
    return r;
  }).catch(function(e){ hideToken(); toast("请求失败：" + e, "bad") })
    .then(function(r){ busy(btn, false); return r });
}
$("#tokBtn").addEventListener("click", function(){
  if ($("#tokBox").style.display === "block"){ hideToken(); return }
  showToken(this);
});
$("#tokCopy").addEventListener("click", function(){
  var v = ($("#tokVal") || {}).value || "";
  if (!v){ toast("先点「看共享令牌」", "bad"); return }
  copyText(v, this);
});

/* ══ 导出 / 导入用户表 ═════════════════════════════════════════
   ⚠️ **导出那份里含每个人的令牌明文**（密钥）。这是这一页第二处会把令牌
   拿出来的地方（第一处是邀请码），所以这个按钮旁边那行 hint 写死了"别外传"。
   ⛔ 任何地方都不许把它打进日志 / toast 正文 —— 日志里只有条数和字节数。 */
function downloadText(name, text){
  try {
    var url = URL.createObjectURL(new Blob([text], {type:"application/json"}));
    var a = document.createElement("a");
    a.href = url; a.download = name; a.style.display = "none";
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    setTimeout(function(){ URL.revokeObjectURL(url) }, 5000);
    return true;
  } catch(e){ return false }
}
function exportUsers(btn){
  busy(btn, true);
  post({action:"user.export"}).then(function(r){
    var txt = r && r["导出"];
    if (!txt){ say("✗ 导出：" + ((r && r.message) || "?"), true); toast("导出失败", "bad"); return }
    var name = (r && r["文件名"]) || "users.json";
    var saved = downloadText(name, txt);
    say("✓ 导出：" + name + "（" + txt.length + " 字节）—— ⚠️ 含密钥，别外传");
    toast(saved ? ("存成 " + name + " 了") : "浏览器没给下载 —— 下面这份自己复制", saved ? "ok" : "bad");
    sheet("用户表（" + name + "）",
      "⚠️ 这份里含每个人的令牌（密钥），别外传、别发群里。\n" +
      "浏览器没给下载就点「复制」。",
      txt, function(v){ copyText(v, $("#shOk")) }, "复制", {rows:10});
  }).catch(function(e){ say("✗ 导出失败：" + e, true); toast("导出失败：" + e, "bad") })
    .then(function(){ busy(btn, false) });
}
function pickImport(){
  var f = $("#impFile"); if (!f) return;
  f.value = ""; f.click();
}
function sendImport(text){
  post({action:"user.import", data:text}).then(function(r){
    say((r && r.ok ? "✓ " : "✗ ") + "导入：" + ((r && r.message) || "?"), !(r && r.ok));
    toast(r && r.ok ? "导入好了" : ("没导成：" + ((r && r.message) || "?")), r && r.ok ? "ok" : "bad");
    if (r && r.users) drawUsers(r.users);
  }).catch(function(e){ say("✗ 导入失败：" + e, true); toast("导入失败：" + e, "bad") });
}
function usersInText(text){
  try {
    var d = JSON.parse(text);
    if (d && Object.prototype.toString.call(d["用户"]) === "[object Array]") return d["用户"];
  } catch(e){}
  return null;
}
function confirmImport(text, how){
  var rows = usersInText(text);
  if (!rows){
    say("✗ 导入：这份" + how + "不是用户表（不是 JSON，或者没有「用户」这一段）", true);
    toast("读不出用户表 —— 要导出那份的原样", "bad");
    return;
  }
  sheet("导入 " + rows.length + " 个人？",
    "· 会整张表覆盖成这份文件里的内容。\n· 现在的 " + USERS.length + " 个人会被替掉。\n" +
    "· 原来那张另存成 users.json.bak。\n· 这份文件含令牌 —— 确认是你自己导出的那份再导。",
    null, function(){ sendImport(text) }, "覆盖导入", {danger:true});
}
function onImportFile(inp){
  var f = (inp.files || [])[0];
  if (!f) return;
  var fr = new FileReader();
  fr.onload = function(){ confirmImport(String(fr.result || ""), "文件") };
  fr.onerror = function(){ toast("这个文件读不出来", "bad") };
  fr.readAsText(f);
}
$("#impFile").addEventListener("change", function(){ onImportFile(this) });
function pasteImport(){
  sheet("粘贴导入用户表",
    "把导出那份 JSON 整段粘进来（粘完点「下一步」）。\n⚠️ 整张表覆盖 —— 现在的 " +
    USERS.length + " 个人会被替掉。",
    "", function(v){
      confirmImport(v, "粘贴");
    }, "下一步", {rows:8, placeholder:'{"版本":1,"用户":[…]}',
      invalid:function(v){ return v ? "" : "什么都没粘。" }});
}
document.addEventListener("click", function(ev){
  if (ev.target.closest && ev.target.closest("[data-adduser]")){ addUser(); return }
  var b = ev.target.closest ? ev.target.closest("button[data-invite],button[data-edit],button[data-revoke]") : null;
  if (!b) return;
  if (b.dataset.invite) showInvite(b.dataset.invite);
  else if (b.dataset.edit) editUser(b.dataset.edit);
  else if (b.dataset.revoke) revokeUser(b.dataset.revoke);
});
$("#userQ").addEventListener("input", renderUsers);
$("#memQ").addEventListener("input", function(){ renderPeople(true) });
$("#pubUrl").addEventListener("blur", function(){
  var v = tidyHost(this.value);
  if (this.value !== v) this.value = v;
});

/* ══ 待处理申请（好友申请 + 群邀请）──────────────────────────────
   动作走 POST /api 的 request.*（**只有主人**能调，别人 403 空正文）。
   · 通过 / 拒绝 = **真调** NapCat（好友会加上 / 她真进群 / 真回绝）——
     所以两个都要**二次确认**，并在弹窗里把后果说清；
   · 忽略 = **一个 API 都不调**，只是从这一列收起来（QQ 那边还挂着），
     所以不用确认，而且「处理过的申请」里能一键放回来；
   · 服务端返回里**没有 flag**（那是一次性凭据，只待在手机本地 requests.json 里）。 */
function loadRequests(btn){
  busy(btn, true);
  return post({action:"request.list"}).then(function(r){
    if (r && r.requests){
      drawRequests(r.requests, r.history || []);
      say("✓ 待处理申请：" + r.requests.length + " 条"
          + ((r.history || []).length ? "，另有 " + r.history.length + " 条处理过的" : ""));
    } else {
      say("✗ 读申请失败：" + ((r && r.message) || "?"), true);
    }
    return r;
  }).catch(function(e){ say("✗ 读申请失败：" + e, true); return null })
    .then(function(r){ busy(btn, false); return r });
}
function drawRequests(list, hist){
  REQS = list || [];
  REQHIST = hist || [];
  var n = REQS.length;
  var h = $("#reqHead");
  if (h) h.textContent = n ? ("待处理（" + n + "）") : "待处理";
  $("#reqCount").textContent = n ? (n + " 条") : "没有";
  $("#reqDoneCount").textContent = REQHIST.length + " 条";
  var b = $("#reqNav");
  if (b){ b.textContent = n > 99 ? "99+" : String(n); b.className = "navcnt" + (n ? " on" : "") }
  renderReqs();
  renderReqHist();
}
function reqWho(r){
  /* 申请队列里那个人怎么显示：**走显示名**（备注 → 称呼 → 昵称 → QQ 号，后端算好的
     `显示名`）——⛔ 不再只摆一串裸 QQ 号。认不出来的陌生人照样是他那个昵称。 */
  if (!r) return "这条";
  var no = (r["类型"] === "好友") ? ("QQ " + (r.qq || "?")) : ("群 " + (r["群"] || "?"));
  var nm = r["显示名"] || r["名字"] || "";
  return nm ? (nm + "（" + no + "）") : no;
}
function renderReqs(){
  if (!REQS.length){
    $("#reqList").innerHTML = '<div class="empty"><b>没有待处理的申请</b>。</div>';
    return;
  }
  $("#reqList").innerHTML = REQS.map(function(r){
    var isF = r["类型"] === "好友";
    var bits = [isF ? ("QQ " + esc(r.qq)) : ("群 " + esc(r["群"]))];
    if (r["多久之前"]) bits.push(esc(r["多久之前"]) + "收到");
    if (r["显示名"] || r["名字"]) bits.push("显示名：" + esc(r["显示名"] || r["名字"]));
    else if (isF) bits.push("QQ 昵称没查到");
    return '<div class="fact"><span class="dot" style="background:var(--accent)"></span>' +
      '<div class="txt"><b>' + (isF ? "好友申请" : "群邀请") + '</b> ' +
      '<span class="chip accent">' + esc(r["类型"]) + "</span>" +
      (r["显示名"] || r["名字"] ? "" : ' <span class="chip">名字没查到</span>') +
      '<div class="hint">' + bits.join(" · ") + "</div>" +
      (r["验证消息"] ? '<div class="hint">验证消息：「' + esc(r["验证消息"]) + "」</div>" : "") +
      "</div>" +
      '<span class="rowacts">' +
        '<button class="btn sm primary" data-rap="' + esc(r.id) + '" title="真的同意">通过</button>' +
        '<button class="btn sm danger" data-rrej="' + esc(r.id) + '" title="真的回绝">拒绝</button>' +
        '<button class="iconbtn" data-rig="' + esc(r.id) +
        '" title="只是这里不看了，QQ 那边还挂着">' + I.eyeoff +
        '<span class="lbl">忽略</span></button>' +
      "</span></div>";
  }).join("");
}
function renderReqHist(){
  if (!REQHIST.length){
    $("#reqDone").innerHTML = '<div class="empty">还没有处理过的申请。</div>';
    return;
  }
  $("#reqDone").innerHTML = REQHIST.map(function(r){
    var isF = r["类型"] === "好友";
    var bits = [isF ? ("QQ " + esc(r.qq)) : ("群 " + esc(r["群"]))];
    if (r["显示名"] || r["名字"]) bits.push("显示名：" + esc(r["显示名"] || r["名字"]));
    if (r["多久之前"]) bits.push(esc(r["多久之前"]) + "收到");
    if (r["处理时间文字"]) bits.push(esc(r["处理时间文字"]) + "处理");
    if (r["处理结果"]) bits.push(esc(r["处理结果"]));
    var chip = (r["状态"] === "已通过") ? "ok"
      : ((r["状态"] === "已拒绝" || r["状态"] === "已过期") ? "bad" : "");
    var act = r["能恢复"]
      ? '<span class="rowacts"><button class="iconbtn" data-rrst="' + esc(r.id) +
        '" title="放回待处理，重新决定">' + I.plus +
        '<span class="lbl">放回待处理</span></button></span>'
      : "";
    return '<div class="fact"><span class="dot" style="background:var(--faint)"></span>' +
      '<div class="txt"><b>' + (isF ? "好友申请" : "群邀请") + '</b> ' +
      '<span class="chip ' + chip + '">' + esc(r["状态"]) + "</span>" +
      '<div class="hint">' + bits.join(" · ") + "</div></div>" + act + "</div>";
  }).join("");
}
function reqOf(id){
  var i;
  for (i = 0; i < REQS.length; i++) if (String(REQS[i].id) === String(id)) return REQS[i];
  for (i = 0; i < REQHIST.length; i++) if (String(REQHIST[i].id) === String(id)) return REQHIST[i];
  return null;
}
function doReq(action, id, label, reason){
  post({action:action, id:id, reason:(reason || "")}).then(function(r){
    say((r && r.ok ? "✓ " : "✗ ") + label + "：" + ((r && r.message) || "?"), !(r && r.ok));
    toast(r && r.ok ? (r.message || (label + "好了")) : ("没成：" + ((r && r.message) || "?")),
          r && r.ok ? "ok" : "bad");
    if (r && r.requests) drawRequests(r.requests, r.history || []);
  }).catch(function(e){ say("✗ " + label + "失败：" + e, true); toast("请求失败：" + e, "bad") });
}
function approveReq(id){
  var r = reqOf(id) || {}, isF = r["类型"] === "好友";
  sheet(isF ? ("通过好友申请：" + reqWho(r) + "？") : ("同意进群：" + reqWho(r) + "？"),
    isF
      ? "· 通过 = **真的同意**：对方立刻出现在她的好友列表里，以后能给她发私聊。\n" +
        "· 她会不会回，还是按原来那套规矩（叫名字 / 触发词…），不是通过就一定有回音。\n" +
        "· 不认识这个人就别通过 —— 点了就真加上了。"
      : "· 通过 = **她真的进那个群**（QQ 那边立刻生效）。\n" +
        "· 进群 ≠ 她会理那个群：要不要理，还要在「群」那一页把她加进名单。\n" +
        "· 不认识这个群就别通过 —— 点了就真进去了。",
    null, function(){ doReq("request.approve", id, "通过申请", "") }, "通过",
    {danger:false});
}
function rejectReq(id){
  var r = reqOf(id) || {}, isF = r["类型"] === "好友";
  sheetForm(isF ? ("拒绝好友申请：" + reqWho(r) + "？") : ("拒绝群邀请：" + reqWho(r) + "？"),
    isF
      ? "· 拒绝 = **真回绝**，对方那边收到「被拒绝」，不能再申请同一条。\n" +
        "· ⚠️ QQ 的**好友接口不带原因** —— 你在下面写的话**发不出去**，只记在这个面板里给你自己看。"
      : "· 拒绝 = **真回绝**，邀请人那边会看到你写的那句话。\n· 不写就用默认那句。",
    [{key:"reason", label:"拒绝原因（可选）", required:false, value:"",
      placeholder: isF ? "给自己记一句，例如 不认识" : "发给对方的，例如 暂时不加群",
      hint: isF ? "好友接口不带原因 —— 这句只存在这台手机上，对方看不到。"
                : "这句话会<b>发给邀请人看</b>。"}],
    "拒绝", function(v){ doReq("request.reject", id, "拒绝申请", v.reason) },
    {danger:true});
}
function ignoreReq(id){
  var r = reqOf(id) || {};
  doReq("request.ignore", id, "忽略申请", "");
}
function restoreReq(id){
  doReq("request.restore", id, "放回待处理", "");
}
document.addEventListener("click", function(ev){
  var b = ev.target.closest
    ? ev.target.closest("button[data-rap],button[data-rrej],button[data-rig],button[data-rrst]") : null;
  if (!b) return;
  if (b.dataset.rap) approveReq(b.dataset.rap);
  else if (b.dataset.rrej) rejectReq(b.dataset.rrej);
  else if (b.dataset.rig) ignoreReq(b.dataset.rig);
  else if (b.dataset.rrst) restoreReq(b.dataset.rrst);
});

/* ══ 群管理（她理哪些群 + 最近见过的群）──────────────────────────
   动作走 POST /api 的 group.*（**只有主人**能调，别人 403 空正文）。
   ⚠️ 加/删**立刻生效**：服务端写的是手机本地的 groups.json，按 mtime 热重载 ——
      不用重启她，下一句消息就按新名单走。
   ⛔ 移除**不退群**：只让她不再处理那个群的消息。
   ⛔ 这一页永远不带令牌（看令牌走「🔑 看共享令牌」那条 /api）。 */
function loadGroups(btn){
  busy(btn, true);
  return post({action:"group.list"}).then(function(r){
    if (r && r.groups){
      drawGroups(r.groups, r.seen || []);
      say("✓ 群名单：" + r.groups.length + " 条"
          + ((r.seen || []).length ? "，另有 " + r.seen.length + " 个最近见过的群等着你加" : ""));
    } else {
      say("✗ 读群名单失败：" + ((r && r.message) || "?"), true);
    }
    return r;
  }).catch(function(e){ say("✗ 读群名单失败：" + e, true); return null })
    .then(function(r){ busy(btn, false); return r });
}
function drawGroups(list, seen){
  GROUPS = list || [];
  SEEN = seen || [];
  $("#groupCount").textContent = GROUPS.length + " 条";
  $("#seenCount").textContent = SEEN.length + " 个";
  renderSeen();
  renderGroups();
}
function renderSeen(){
  /* ① 最近见过的群：她收到过不在名单里的群消息 —— 一键加进来（这才是实用入口） */
  if (!SEEN.length){
    $("#groupRecent").innerHTML = '<div class="empty">还没有「最近见过的群」。</div>';
    return;
  }
  $("#groupRecent").innerHTML = SEEN.map(function(g){
    var bits = [];
    if (g["最后见到"]) bits.push("最后见到 " + esc(g["最后见到"]));
    if (g["谁在说话"]) bits.push("在说话：" + esc(g["谁在说话"]));
    if (g["邀请人"]) bits.push("邀请人：" + esc(g["邀请人显示名"] || g["邀请人"]));
    if (g["次数"]) bits.push(esc(g["次数"]) + " 条消息");
    bits.push("群 " + esc(g.id));
    return '<div class="fact"><span class="dot" style="background:var(--warn)"></span>' +
      '<div class="txt"><b>' + esc(g["名字"] || "（群名没查到）") +
      '</b><div class="hint">' + bits.join(" · ") + "</div></div>" +
      '<span class="rowacts"><button class="iconbtn" data-gadd="' + esc(g.id) +
      '" title="添加到目标群">' + I.plus + '<span class="lbl">加入白名单</span></button>' +
      '<span class="sep"></span><button class="iconbtn danger" data-gforget="' + esc(g.id) +
      '" title="从这一列里去掉">' + I.trash + '<span class="lbl">忽略</span></button></span></div>';
  }).join("");
}
function renderGroups(){
  var q = deepTrim(($("#groupQ") || {}).value || "").toLowerCase();
  var hit = GROUPS.filter(function(g){
    if (!q) return true;
    return [g.id, g["名字"], g["备注"], g["来源"]].join(" ").toLowerCase().indexOf(q) >= 0;
  });
  if (!GROUPS.length){
    $("#groupList").innerHTML = '<div class="empty">暂无目标群。</div>';
    return;
  }
  if (!hit.length){
    $("#groupList").innerHTML = '<div class="empty">没找到 —— 换个词试试。</div>';
    return;
  }
  /* ② 当前名单：群名一行，群号 + 备注 + 来源 + 加入时间 弱化在下面 */
  $("#groupList").innerHTML = hit.map(function(g){
    var bits = ["群 " + esc(g.id)];
    if (g["备注"]) bits.push("备注：" + esc(g["备注"]));
    if (g["加入时间"]) bits.push("加入于 " + esc(g["加入时间"]));
    if (g["来源"] === "config") bits.push("来自 config.json 的 bot.groups");
    else if (g["来源"] === "user") bits.push("来自用户表里某人登记的群");
    var state = g["生效"] ? '<span class="chip ok">现在生效</span>'
                          : '<span class="chip bad">没生效</span>';
    var acts = '<span class="rowacts"><button class="iconbtn" data-gnote="' + esc(g.id) +
      '" title="给自己看的备注">' + I.note + '<span class="lbl">备注</span></button>';
    acts += g["能移除"]
      ? '<span class="sep"></span><button class="iconbtn danger" data-gdel="' + esc(g.id) +
        '" title="从目标群移除（不会退群）">' + I.trash +
        '<span class="lbl">移除</span></button>'
      : '<span class="sep"></span><button class="iconbtn" disabled ' +
        'title="这条来自 config.json / 用户表，只能改那份文件">不可移除</button>';
    acts += "</span>";
    return '<div class="fact"><span class="dot" style="background:' +
      (g["生效"] ? "var(--ok)" : "var(--faint)") + '"></span><div class="txt"><b>' +
      esc(g["名字"] || "（群名没查到）") + "</b> " + state +
      '<div class="hint">' + bits.join(" · ") + "</div></div>" + acts + "</div>";
  }).join("");
}
function groupOf(id){
  for (var i=0;i<GROUPS.length;i++) if (String(GROUPS[i].id) === String(id)) return GROUPS[i];
  return null;
}
function addGroup(btn){
  var el = $("#newGroupId");
  var gid = digitsOnly(el.value);
  if (el.value !== gid) el.value = gid;             // 全角 / 空格 / 杂字符就地收拾掉
  if (!gid){ fieldErr(el, "群号得是纯数字。"); return }
  if (!gidOk(gid)){ fieldErr(el, "群号是 5~12 位数字，现在 " + gid.length + " 位。"); return }
  if (groupOf(gid)){ fieldErr(el, "群里已经有 " + gid + " 了。"); return }
  fieldErr(el, "");
  busy(btn, true);
  post({action:"group.add", id:gid}).then(function(r){
    say((r && r.ok ? "✓ " : "✗ ") + "加群：" + ((r && r.message) || "?"), !(r && r.ok));
    toast(r && r.ok ? "加好了 —— 立刻生效" : ("没加成：" + ((r && r.message) || "?")),
          r && r.ok ? "ok" : "bad");
    if (r && r.ok) el.value = "";
    if (r && r.groups) drawGroups(r.groups, r.seen || []);
  }).catch(function(e){ fieldErr(el, "请求失败：" + e); toast("请求失败：" + e, "bad") })
    .then(function(){ busy(btn, false) });
}
$("#addGroupBtn").addEventListener("click", function(){ addGroup(this) });
$("#newGroupId").addEventListener("blur", function(){
  var gid = digitsOnly(this.value);
  if (this.value !== gid) this.value = gid;
});
$("#groupQ").addEventListener("input", renderGroups);
function delGroup(id, btn){
  var g = groupOf(id) || {};
  sheet("移除「" + (g["名字"] || id) + "」？",
    "· 她立刻就不再收这个群的消息（不用重启她）。\n· ⚠️ 她**不会退群** —— 只是不再理那个群。\n" +
    "· 要不要退群，你自己在 QQ 里点。",
    null, function(){
      post({action:"group.del", id:id}).then(function(r){
        say((r && r.ok ? "✓ " : "✗ ") + "移除群：" + ((r && r.message) || "?"), !(r && r.ok));
        toast(r && r.ok ? "移除了（她没退群）" : ("没移除：" + ((r && r.message) || "?")),
              r && r.ok ? "ok" : "bad");
        if (r && r.groups) drawGroups(r.groups, r.seen || []);
      });
    }, "移除", {danger:true});
}
function noteGroup(id){
  var g = groupOf(id) || {};
  sheetForm("给群 " + id + " 写个备注",
    "只给你自己看。",
    [{key:"note", label:"备注", required:false, value:g["备注"] || "",
      placeholder:"输入群备注", hint:"留空则清除备注。"}],
    "存下来", function(v){
      post({action:"group.note", id:id, note:v.note}).then(function(r){
        say((r && r.ok ? "✓ " : "✗ ") + "备注：" + ((r && r.message) || "?"), !(r && r.ok));
        toast(r && r.ok ? "备注已保存" : ("保存失败：" + ((r && r.message) || "?")),
              r && r.ok ? "ok" : "bad");
        if (r && r.groups) drawGroups(r.groups, r.seen || []);
      });
    });
}
function addSeenGroup(id){
  sheet("把群 " + id + " 加进白名单？",
    "加进来 = 她能收到这个群的消息、也可能说话。\n立刻生效，不用重启她。",
    null, function(){
      post({action:"group.add", id:id}).then(function(r){
        say((r && r.ok ? "✓ " : "✗ ") + "加群：" + ((r && r.message) || "?"), !(r && r.ok));
        toast(r && r.ok ? "加好了 —— 立刻生效" : ("没加成：" + ((r && r.message) || "?")),
              r && r.ok ? "ok" : "bad");
        if (r && r.groups) drawGroups(r.groups, r.seen || []);
      });
    }, "加入白名单");
}
function forgetSeenGroup(id){
  post({action:"group.forget", id:id}).then(function(r){
    say((r && r.ok ? "✓ " : "✗ ") + "忽略：" + ((r && r.message) || "?"), !(r && r.ok));
    toast(r && r.ok ? "忽略掉了" : ("没忽略掉：" + ((r && r.message) || "?")), r && r.ok ? "ok" : "bad");
    if (r && r.groups) drawGroups(r.groups, r.seen || []);
  });
}
document.addEventListener("click", function(ev){
  var b = ev.target.closest
    ? ev.target.closest("button[data-gadd],button[data-gdel],button[data-gnote],button[data-gforget]") : null;
  if (!b) return;
  if (b.dataset.gadd) addSeenGroup(b.dataset.gadd);
  else if (b.dataset.gdel) delGroup(b.dataset.gdel, b);
  else if (b.dataset.gnote) noteGroup(b.dataset.gnote);
  else if (b.dataset.gforget) forgetSeenGroup(b.dataset.gforget);
});

/* ══ 初始化（新部署的人在这里配完，一个文件都不用碰）════════════════
   数据：GET /onboard（只给主人；token 只有 ****）；动作走 /api 的 onboarding.*
   （`onboarding.save` / `.probe` / `.groups` / `.persona`，全部只有主人能调）。
   D 块「她的大脑」**不重复实现** —— 它只显示现状 + 跳去「设置」那张卡。
   ⛔ 这里永远不会拿到 token 明文：要换就整把重填（不填就不改）。 */
var OB = null;

function obState(sel, ok, why){
  var el = $(sel); if (!el) return;
  el.className = "obstate " + (ok ? "ok" : "bad");
  el.textContent = ok ? "已配置" : "待配置";
  el.title = ok ? "" : (why || "");
}
function obMsg(sel, text, bad){
  var el = $(sel); if (!el) return;
  el.textContent = text || "";
  el.className = "msg" + (bad ? "" : "");
}
function obRandomToken(){
  var t = "";
  try {
    var a = new Uint8Array(24);
    window.crypto.getRandomValues(a);
    for (var i = 0; i < a.length; i++) t += ("0" + a[i].toString(16)).slice(-2);
  } catch(e){
    // 极老的浏览器 / 没有 crypto 的壳子：退回 Math.random（只影响"随机"的成色）
    for (var j = 0; j < 48; j++) t += "0123456789abcdef"[Math.floor(Math.random() * 16)];
  }
  return t;
}
/* 群列表：textarea 一行一个「群号 备注」 */
function obGroupText(rows){
  return (rows || []).map(function(g){
    return String(g.id) + (g.note ? " " + g.note : "");
  }).join("\n");
}
function parseObGroups(){
  var out = [], bad = "";
  String(($("#obGroups") || {}).value || "").split(/\n/).forEach(function(line){
    line = deepTrim(line);
    if (!line) return;
    var m = line.match(/^([0-9]{5,12})(?:\s+([\s\S]*))?$/);
    if (!m){ if (!bad) bad = "这一行看不出群号：" + line; return }
    out.push({id: m[1], note: m[2] || ""});
  });
  return {rows: out, bad: bad};
}

function fillObBlock(name, d){
  var v = (d && d.values) || {};
  if (name === "a"){
    $("#obQQ").value = v["bot.selfId"] ? String(v["bot.selfId"]) : "";
    $("#obNick").value = v["agent.name"] || "";
    OBWAKE = String(v["agent.wakeWords"] || "").split(/[\u3001,\uff0c/|\s]+/)
      .filter(function(x){ return !!x });
    drawWake();
  } else if (name === "b"){
    $("#obPort").value = v["port"] ? String(v["port"]) : "";
    $("#obToken").value = "";
    $("#obToken").type = "password";
    $("#obTokenEye").textContent = "显示";
    $("#obToken").placeholder = v["bot.tokenSet"]
      ? "已设置（****）；留空不修改" : "填写或随机生成";
    $("#obNapUrl").value = v["napcat.baseUrl"] || "";
    $("#obAccept").checked = !!v["bot.autoAcceptGroupInvite"];
  } else if (name === "c"){
    $("#obGroups").value = obGroupText(v["bot.groups"]);
  } else if (name === "e"){
    $("#obPersona").value = ((d && d.persona) || {}).text || "";
    $("#obPersonaNow").textContent = "现在 " + (((d && d.persona) || {}).chars || 0) + " 字";
  } else if (name === "f"){
  } else if (name === "g"){
    $("#obChance").value = String(v["agent.chimeIn.chancePercent"] == null
      ? "" : v["agent.chimeIn.chancePercent"]);
    $("#obPokeBack").checked = !!v["agent.pokeBack.enabled"];
    $("#obAllowPublic").checked = !!v["bot.control.allowPublic"];
    $("#obMaxGroup").value = String(v["agent.maxGroupReplyChars"] == null
      ? "" : v["agent.maxGroupReplyChars"]);
    $("#obMaxPrivate").value = String(v["agent.maxPrivateReplyChars"] == null
      ? "" : v["agent.maxPrivateReplyChars"]);
  }
}
function drawObStatus(d){
  OB = d;
  var b = (d && d.blocks) || {};
  obState("#obAState", b.a && b.a.ok, b.a && b.a.why);
  obState("#obBState", b.b && b.b.ok, b.b && b.b.why);
  obState("#obCState", b.c && b.c.ok, b.c && b.c.why);
  /* obD 卡已并进下面 cardBrain（2026-11-01） */
  obState("#obEState", b.e && b.e.ok, b.e && b.e.why);
  obState("#obGState", b.g && b.g.ok, b.g && b.g.why);
  var br = (d && d.brain) || {};
  var np = (d && d.napcat) || {};
  if (np.reachable) $("#obProbeMsg").textContent = "✓ " + (np.detail || "连得上");
  var list = (d && d.checklist) || [];
  var checksHtml = list.length ? list.map(function(c){
    return '<div class="obchk ' + (c.ok ? "ok" : "bad") + '"><span class="mk">' +
      (c.ok ? "✓" : "✗") + "</span><span>" + esc(c.label) + "</span>" +
      (c.ok ? "" : '<span class="why">' + esc(c.hint || "") + "</span>") + "</div>";
  }).join("") : "";
  $("#obCheck").innerHTML = checksHtml;
  var overview = $("#overviewCheck"); if (overview) overview.innerHTML = checksHtml;
  var sm = (d && d.summary) || {};
  var sum = $("#obSum");
  sum.textContent = sm.text || "";
  sum.className = "obsum " + (sm.ok ? "ok" : "bad");
  var os = $("#overviewSum");
  if (os){ os.textContent = sm.text || ""; os.className = "obsum " + (sm.ok ? "ok" : "bad") }
}
function fillOnboard(d){
  ["a", "b", "c", "e", "f", "g"].forEach(function(k){ fillObBlock(k, d) });
  fillNetwork(d);
}
function obFetch(){
  /* ⚠️ 不用 get()：那个 403 会当"令牌不认"把门禁盖上来。
     这一页**只有主人**能看，朋友的令牌拿到 403 是正常的，不该踢他重新登录。 */
  return fetch("/onboard", {headers: hdr()}).then(function(r){
    if (r.status === 401 || r.status === 403)
      return {ok: false, message: "这一页只有主人能打开"};
    if (!r.ok) throw new Error("HTTP " + r.status);
    return r.json();
  });
}
var NET_ALLOW_IPS = [], NET_PROXIES = [];
function fillNetwork(d){
  var s = (d && d.server) || {};
  var remote = $("#netAllowRemote"), host = $("#netHost");
  if (remote) remote.checked = !!s.allowRemote;
  if (host) host.value = s.host || "";
  NET_ALLOW_IPS = (s.allowIps || []).slice();
  NET_PROXIES = (s.trustedProxies || []).slice();
  renderNetworkLists();
}
function renderNetworkLists(){
  var a = $("#allowIpsChips"), p = $("#proxyChips");
  if (a) a.innerHTML = NET_ALLOW_IPS.length ? NET_ALLOW_IPS.map(function(x,i){
    return '<span class="tchip"><span class="tt">' + esc(x) + '</span>' +
      '<button type="button" class="tx" data-net-del="allow" data-net-i="' + i + '" aria-label="删除来源 IP">×</button></span>';
  }).join("") : '<span class="none">未设置</span>';
  if (p) p.innerHTML = NET_PROXIES.length ? NET_PROXIES.map(function(x,i){
    return '<span class="tchip"><span class="tt">' + esc(x) + '</span>' +
      '<button type="button" class="tx" data-net-del="proxy" data-net-i="' + i + '" aria-label="删除代理地址">×</button></span>';
  }).join("") : '<span class="none">未设置</span>';
}
function netMsg(kind, text, bad){
  var el = $(kind === "allow" ? "#allowIpsMsg" : "#proxyMsg");
  if (el){ el.textContent = text || ""; el.className = "msg" + (bad ? " bad" : "") }
}
function saveNetworkList(kind, next){
  var key = kind === "allow" ? "bot.control.allowIps" : "panel.trustedProxies";
  if (kind === "proxy" && !next.length){ netMsg(kind, "可信代理至少保留一个地址。", true); return Promise.resolve({ok:false}) }
  if (next.length > 32){ netMsg(kind, "最多 32 项。", true); return Promise.resolve({ok:false}) }
  var values = {}; values[key] = next.slice();
  netMsg(kind, "保存中…", false);
  return post({action:"onboarding.save", values:values}).then(function(r){
    if (r && r.ok){
      if (kind === "allow") NET_ALLOW_IPS = next.slice(); else NET_PROXIES = next.slice();
      if (r.onboard) fillNetwork(r.onboard); else renderNetworkLists();
      netMsg(kind, r.message || "已保存 · 立即生效", false);
    } else netMsg(kind, (r && r.message) || "没保存上", true);
    return r;
  }).catch(function(e){ netMsg(kind, "保存失败：" + e, true); return {ok:false} });
}
function addNetworkItem(kind){
  var title = kind === "allow" ? "添加 API 来源 IP / CIDR" : "添加可信代理 IP / CIDR";
  sheet(title, "填写一个 IP 地址或 CIDR 网段。", "", function(raw){
    var value = deepTrim(raw);
    if (!value){ netMsg(kind, "地址不能为空。", true); return }
    var list = kind === "allow" ? NET_ALLOW_IPS : NET_PROXIES;
    if (list.indexOf(value) >= 0){ netMsg(kind, "这项已经存在。", true); return }
    saveNetworkList(kind, list.concat([value]));
  }, "添加", {rows:1, placeholder:"例如 192.168.1.0/24"});
}
document.addEventListener("click", function(ev){
  var b = ev.target.closest ? ev.target.closest("[data-net-del]") : null;
  if (b){
    var kind = b.dataset.netDel, i = parseInt(b.dataset.netI, 10);
    var list = kind === "allow" ? NET_ALLOW_IPS : NET_PROXIES;
    if (kind === "proxy" && list.length <= 1){ netMsg(kind, "可信代理至少保留一个地址。", true); return }
    saveNetworkList(kind, list.filter(function(_, n){ return n !== i })); return;
  }
  if (ev.target && ev.target.id === "allowIpsAdd"){ addNetworkItem("allow"); return }
  if (ev.target && ev.target.id === "proxyAdd"){ addNetworkItem("proxy"); return }
  if (ev.target && ev.target.id === "netSaveRemote"){
    var btn = ev.target, enable = $("#netAllowRemote").checked;
    if (enable && !NET_PROXIES.length){ $("#netRemoteMsg").textContent = "先添加可信反向代理地址，再启用公网登录。"; return }
    busy(btn, true);
    post({action:"onboarding.save", values:{"panel.allowRemote":enable}}).then(function(r){
      $("#netRemoteMsg").textContent = r && r.ok ? (r.message || "已保存 · 立即生效") : ((r && r.message) || "没保存上");
      if (r && r.onboard) fillNetwork(r.onboard);
    }).catch(function(e){ $("#netRemoteMsg").textContent = "保存失败：" + e })
      .then(function(){ busy(btn, false) });
    return;
  }
  if (ev.target && ev.target.id === "netSaveHost"){
    var btn2 = ev.target, host = deepTrim($("#netHost").value);
    if (!host){ $("#netHostMsg").textContent = "监听地址不能为空。"; return }
    busy(btn2, true);
    post({action:"onboarding.save", values:{host:host}}).then(function(r){
      $("#netHostMsg").textContent = r && r.ok ? ((r.message || "已保存") + " · 重启后生效") : ((r && r.message) || "没保存上");
      if (r && r.onboard) fillNetwork(r.onboard);
    }).catch(function(e){ $("#netHostMsg").textContent = "保存失败：" + e })
      .then(function(){ busy(btn2, false) });
    return;
  }
});
/* ══════ 首次配置弹窗 ══════════════════════════════════════════════
   缺东西时自己弹出；可以关（关了在设置页顶上留一条提示）。
   必填：主人QQ / 她的QQ / token / 群 / 模型（地址+密钥+模型名）
   能跑但也要问：名字 / 触发词 / 性格正文 / 对主人的称呼 */
var SETUP_ITEMS = [];
function setupCollect(d){
  var v = (d && d.values) || {};
  var missing = [], soft = [];
  if (!String(v["bot.ownerQQ"] || "").trim()) missing.push("主人 QQ");
  if (!String(v["bot.selfId"] || "").trim()) missing.push("机器人 QQ");
  if (!v["bot.tokenSet"]) missing.push("共用令牌");
  if (!(v["bot.groups"] || []).length) missing.push("目标群");
  if (!(d && d.brain && d.brain.ok)) missing.push("模型服务");
  if (!String(v["agent.name"] || "").trim()) soft.push("机器人名字");
  if (!(v["agent.triggerWords"] || []).length) soft.push("触发词");
  var pe = (d && d.persona) || {};
  if (!(pe.chars > 0)) soft.push("人设正文");
  return {missing: missing, soft: soft};
}
var SETUP_SNAPSHOT = null, SETUP_STEP = 1, QSWAKE = [];
function setupFill(d){
  SETUP_SNAPSHOT = d || null;
  var v = (d && d.values) || {};
  $("#qsOwnerQQ").value = v["bot.ownerQQ"] || "";
  $("#qsQQ").value = v["bot.selfId"] || "";
  $("#qsToken").value = "";
  $("#qsGroups").value = (v["bot.groups"] || []).map(function(g){
    return g.id + (g.note ? (" " + g.note) : "");
  }).join("\n");
  $("#qsNapUrl").value = v["napcat.baseUrl"] || "";
  $("#qsName").value = v["agent.name"] || "";
  $("#qsOwnerTitle").value = v["bot.ownerCallName"] || "";
  TRIG = Array.isArray(v["agent.triggerWords"]) ? v["agent.triggerWords"].slice() : [];
  renderTriggers();
  var wake = v["agent.wakeWords"] || "";
  QSWAKE = Array.isArray(wake) ? wake.slice() : String(wake).split(/[、,，/|\s]+/).filter(Boolean);
  renderSetupWake();
  var br = (d && d.brain) || {};
  $("#qsModel").value = br.model || "";
  $("#qsBase").value = br.baseUrl || "";
  $("#qsKey").value = "";
  $("#qsKey").placeholder = br.key === "已配置" ? "已配置，留空 = 不改" : "填写模型服务密钥";
  var pe = (d && d.persona) || {};
  $("#qsPersona").value = pe.text || "";
  $("#qsPersonaHint").textContent = pe.chars > 0
    ? "已载入当前人设；未修改时会原样保留。" : "可载入 .md 文件后继续编辑。";
  setupStep(1);
}
function setupShow(){
  $("#setup").classList.add("on");
  setupStep(1);
  var first = $("#qsOwnerQQ");
  if (first) setTimeout(function(){ try{ first.focus() }catch(e){} }, 40);
}
function setupStep(n){
  SETUP_STEP = Math.max(1, Math.min(3, n|0));
  $$('[data-setup-step]').forEach(function(x){ x.hidden = Number(x.dataset.setupStep) !== SETUP_STEP });
  $("#setupStepLabel").textContent = "第 " + SETUP_STEP + " 步，共 3 步";
  $("#setupStepBar").style.width = (SETUP_STEP * 33.333) + "%";
  $("#setupBack").hidden = SETUP_STEP === 1;
  $("#setupNext").hidden = SETUP_STEP === 3;
  $("#setupSave").hidden = SETUP_STEP !== 3;
  $("#setupErr").textContent = "";
  if ($("#setup").classList.contains("on")) setTimeout(function(){
    var step = document.querySelector('[data-setup-step="' + SETUP_STEP + '"]');
    var first = step && step.querySelector('input:not([type="file"]),textarea');
    if (first) first.focus();
  }, 0);
}
function setupGroups(){
  var rows = [], bad = "";
  String($("#qsGroups").value || "").split(/\n/).forEach(function(line){
    line = half(line).trim(); if (!line) return;
    var m = line.match(/^([0-9]{5,12})(?:\s+([\s\S]*))?$/);
    if (!m){ if (!bad) bad = "群号格式不对，请检查这一行：" + line; return }
    if (!rows.some(function(x){ return x.id === m[1] })) rows.push({id:m[1], note:m[2] || ""});
  });
  return {rows:rows, bad:bad};
}
function setupStepValid(n){
  var d = SETUP_SNAPSHOT || {}, v = d.values || {}, br = d.brain || {};
  if (n === 1){
    var owner = digitsOnly($("#qsOwnerQQ").value), self = digitsOnly($("#qsQQ").value);
    if (!/^\d{5,12}$/.test(owner)){ $("#setupErr").textContent = "请填写 5–12 位主人 QQ 号。"; $("#qsOwnerQQ").focus(); return false }
    if (!/^\d{5,12}$/.test(self) || self === "10000"){
      $("#setupErr").textContent = "请填写有效的机器人 QQ 号。"; $("#qsQQ").focus(); return false;
    }
    if (!deepTrim($("#qsToken").value) && !v["bot.tokenSet"]){
      $("#setupErr").textContent = "请填写或生成共用令牌。"; $("#qsToken").focus(); return false;
    }
    var groups = setupGroups();
    if (groups.bad){ $("#setupErr").textContent = groups.bad; $("#qsGroups").focus(); return false }
    if (!groups.rows.length && !(v["bot.groups"] || []).length){
      $("#setupErr").textContent = "请至少填写一个目标群。"; $("#qsGroups").focus(); return false;
    }
  }
  if (n === 2 && !br.ok){
    if (!deepTrim($("#qsBase").value)){ $("#setupErr").textContent = "请填写模型接口地址。"; $("#qsBase").focus(); return false }
    if (!deepTrim($("#qsModel").value)){ $("#setupErr").textContent = "请填写模型名。"; $("#qsModel").focus(); return false }
    if (!deepTrim($("#qsKey").value) && br.key !== "已配置"){
      $("#setupErr").textContent = "请填写模型密钥。"; $("#qsKey").focus(); return false;
    }
  }
  return true;
}
function setupNext(){ if (setupStepValid(SETUP_STEP)) setupStep(SETUP_STEP + 1) }
function setupBack(){ setupStep(SETUP_STEP - 1) }
function renderSetupWake(){
  var box = $("#qsWakeChips"); if (!box) return;
  box.innerHTML = QSWAKE.length ? QSWAKE.map(function(w, i){
    return '<span class="tchip"><span class="tt">' + esc(w) + '</span>' +
      '<button type="button" class="tx" data-qwake-del="' + i + '" aria-label="删除唤醒词">×</button></span>';
  }).join("") : '<span class="none">未设置</span>';
}
function addSetupWake(){
  var el = $("#qsWakeNew"), w = deepTrim(el.value);
  if (!w){ $("#setupErr").textContent = "先填写一个唤醒词。"; return }
  if (/\s/.test(w) || w.length > 20){ $("#setupErr").textContent = "唤醒词不能有空格，最多 20 个字。"; return }
  if (QSWAKE.indexOf(w) >= 0){ $("#setupErr").textContent = "这个唤醒词已经存在。"; return }
  if (QSWAKE.length >= 12){ $("#setupErr").textContent = "唤醒词最多 12 个。"; return }
  QSWAKE.push(w); el.value = ""; renderSetupWake(); $("#setupErr").textContent = "";
}
function addSetupTrigger(){
  var el = $("#qTrigNew"), w = deepTrim(el.value);
  if (!w){ $("#qTrigMsg").textContent = "先填写一个触发词。"; return }
  if (/\s/.test(w) || w.length > 12){ $("#qTrigMsg").textContent = "触发词不能有空格，最多 12 个字。"; return }
  if (TRIG.indexOf(w) >= 0){ $("#qTrigMsg").textContent = "这个触发词已经存在。"; return }
  if (TRIG.length >= 50){ $("#qTrigMsg").textContent = "触发词最多 50 个。"; return }
  TRIG.push(w); renderTriggers(); el.value = ""; $("#qTrigMsg").textContent = "";
}
function setupHint(d){
  var r = setupCollect(d), all = r.missing.concat(r.soft);
  var card = $("#setupHintCard"), overview = $("#overviewSetupCard");
  if (!all.length){
    if (card) card.hidden = true;
    if (overview) overview.hidden = true;
    try{ localStorage.setItem("fgSetupDone", "1") }catch(e){}
    return;
  }
  if (card){
    card.hidden = false;
    $("#setupHint").textContent = "配置未完成（还差 " + all.length + " 项）";
    $("#setupHintWhy").textContent = "缺：" + all.join(" / ");
  }
  if (overview){
    overview.hidden = false;
    $("#overviewSetupTitle").textContent = r.missing.length ? "初始配置未完成" : "还有可补充的配置";
    $("#overviewSetupWhy").textContent = all.join(" / ");
  }
}
function setupMaybeOpen(d, force){
  var r = setupCollect(d);
  setupHint(d);
  var nag = true;
  try{ nag = localStorage.getItem("fgSetupSkip") !== "1" }catch(e){}
  if (force || ((r.missing.length || r.soft.length) && nag)){
    setupFill(d);
    setupShow(r.missing.length ? "hard" : "soft");
  }
}
function setupSaveLegacy(btn){
  var vals = {};
  var empty = function(id){ return String(($("#" + id) || {}).value || "").trim() };
  var oq = empty("qsOwnerQQ"), qq = empty("qsQQ"), tok = empty("qsToken");
  var gs = empty("qsGroups"), base = empty("qsBase"), key = empty("qsKey"), mdl = empty("qsModel");
  var nm = empty("qsName"), ot = empty("qsOwnerTitle"), pe = String(($("#qsPersona") || {}).value || "");
  if (oq) vals["bot.ownerQQ"] = oq;
  if (qq) vals["bot.selfId"] = qq;
  if (tok) vals["bot.token"] = tok;
  if (gs) vals["bot.groups"] = gs.split("\n").map(function(x){ return x.trim() }).filter(Boolean);
  if (base) vals["llm.baseUrl"] = base;
  if (mdl) vals["llm.model"] = mdl;
  if (key) vals["llm.apiKey"] = key;
  if (nm) vals["agent.name"] = nm;
  if (ot) vals["bot.ownerCallName"] = ot;
  busy(btn, true);
  $("#setupErr").textContent = "";
  return post({action: "onboarding.save", values: vals}).then(function(r){
    if (!r || !r.ok){
      $("#setupErr").textContent = (r && r.message) || "没保存上";
      return r;
    }
    // 性格正文单独存（走人设那条路）
    var after = function(){
      if (pe.trim()){
        return post({action: "onboarding.persona", text: pe}).then(function(){
          return loadOnboard(null, false);
        });
      }
      return loadOnboard(null, false);
    };
    return after().then(function(d){
      try{ localStorage.removeItem("fgSetupSkip") }catch(e){}
      var rr = setupCollect(d);
      if (!rr.missing.length){ $("#setup").classList.remove("on") }
      setupHint(d);
      say("✓ 已保存");
      return d;
    });
  }).catch(function(e){
    $("#setupErr").textContent = "没保存上：" + e;
  }).then(function(){ busy(btn, false) });
}
function setupSave(btn){
  if (!setupStepValid(1)){ setupStep(1); setupStepValid(1); return }
  if (!setupStepValid(2)){ setupStep(2); setupStepValid(2); return }
  var parsed = setupGroups();
  if (parsed.bad){ setupStep(1); $("#setupErr").textContent = parsed.bad; return }
  var vals = {};
  var val = function(id){ return String($("#" + id).value || "").trim() };
  var oq = val("qsOwnerQQ"), qq = val("qsQQ"), tok = deepTrim(val("qsToken"));
  var nap = tidyUrl(val("qsNapUrl")), base = tidyUrl(val("qsBase"));
  var key = deepTrim(val("qsKey")), mdl = val("qsModel");
  var nm = val("qsName"), ot = val("qsOwnerTitle"), pe = String($("#qsPersona").value || "");
  var oldPersona = String(((SETUP_SNAPSHOT || {}).persona || {}).text || "");
  if (oq) vals["bot.ownerQQ"] = oq;
  if (qq) vals["bot.selfId"] = qq;
  if (tok) vals["bot.token"] = tok;
  if (parsed.rows.length) vals["bot.groups"] = parsed.rows;
  if (nap) vals["napcat.baseUrl"] = nap;
  if (base) vals["llm.baseUrl"] = base;
  if (mdl) vals["llm.model"] = mdl;
  if (key) vals["llm.apiKey"] = key;
  if (nm) vals["agent.name"] = nm;
  if (ot) vals["bot.ownerCallName"] = ot;
  vals["agent.wakeWords"] = QSWAKE.slice();
  vals["agent.triggerWords"] = TRIG.slice();
  if (pe !== oldPersona && !pe.trim()){
    $("#setupErr").textContent = "人设正文不能为空；如不修改，请恢复原文或退出。"; return;
  }
  busy(btn, true);
  $("#setupErr").textContent = "";
  try{ localStorage.setItem("fgSetupSkip", "1") }catch(e){}
  return post({action:"onboarding.save", values:vals}).then(function(r){
    if (!r || !r.ok){ $("#setupErr").textContent = (r && r.message) || "没保存上"; return r }
    if (!PANEL_REMOTE && tok){
      TOKEN = tok; TOKEN_FROM_URL = false;
      try{ localStorage.setItem("fgPanelToken", tok) }catch(e){}
    }
    var after = function(){
      if (pe !== oldPersona && pe.trim()){
        return post({action:"onboarding.persona", text:pe}).then(function(pr){
          if (!pr || !pr.ok) throw new Error((pr && pr.message) || "人设没保存上");
          return loadOnboard(null, false);
        });
      }
      return loadOnboard(null, false);
    };
    return after().then(function(d){
      var rr = setupCollect(d);
      if (!rr.missing.length){
        $("#setup").classList.remove("on");
        if (!rr.soft.length){ try{ localStorage.removeItem("fgSetupSkip") }catch(e){} }
      }
      setupHint(d); say("✓ 初始配置已保存"); return d;
    });
  }).catch(function(e){ $("#setupErr").textContent = "没保存上：" + e })
    .then(function(){ busy(btn, false) });
}
document.addEventListener("click", function(ev){
  var t = ev.target;
  if (!t || !t.id) return;
  if (t.id === "setupHintOpen"){ loadOnboard(null, false).then(function(d){ setupMaybeOpen(d, true) }); return }
  if (t.id === "setupLater"){
    try{ localStorage.setItem("fgSetupSkip", "1") }catch(e){}
    $("#setup").classList.remove("on");
    return;
  }
  if (t.id === "setupSave"){ setupSave(t); return }
  if (t.id === "setupNext"){ setupNext(); return }
  if (t.id === "setupBack"){ setupBack(); return }
  if (t.id === "qTrigAdd"){ addSetupTrigger(); return }
  if (t.id === "qsWakeAdd"){ addSetupWake(); return }
  if (t.id === "qsTokenGen"){
    var ab = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789", out = "";
    for (var i = 0; i < 16; i++){ out += ab[Math.floor(Math.random() * ab.length)] }
    $("#qsToken").value = out;
    return;
  }
  if (t.id === "qsPersonaLoad"){ $("#qsPersonaFile").click(); return }
});
document.addEventListener("change", function(ev){
  var f = ev.target;
  if (!f || f.id !== "qsPersonaFile" || !f.files || !f.files[0]) return;
  var fr = new FileReader();
  fr.onload = function(){
    $("#qsPersona").value = String(fr.result || "");
    $("#qsPersonaHint").textContent = "已载入 " + f.files[0].name + "，可以改。";
  };
  fr.readAsText(f.files[0]);
});
document.addEventListener("click", function(ev){
  var b = ev.target.closest ? ev.target.closest("[data-qwake-del]") : null;
  if (!b) return;
  var i = parseInt(b.dataset.qwakeDel, 10);
  if (i >= 0 && i < QSWAKE.length){ QSWAKE.splice(i, 1); renderSetupWake() }
});
document.addEventListener("keydown", function(ev){
  if (ev.key !== "Enter") return;
  if (ev.target && ev.target.id === "qTrigNew"){ ev.preventDefault(); addSetupTrigger() }
  if (ev.target && ev.target.id === "qsWakeNew"){ ev.preventDefault(); addSetupWake() }
});
function loadOnboard(btn, keepValues){
  busy(btn, true);
  return obFetch().then(function(d){
    if (!d || !d.ok){
      $("#obCheck").innerHTML = "";
      $("#obSum").className = "obsum bad";
      $("#obSum").textContent = (d && d.message) || "读不到这一页的数据";
      var oc = $("#overviewCheck"), os = $("#overviewSum");
      if (oc) oc.innerHTML = "";
      if (os){ os.className = "obsum bad"; os.textContent = (d && d.message) || "读不到连接状态" }
      return d;
    }
    // 「重新检查」只刷状态 / 检查表，**不冲掉还没保存的输入**；
    // 打开页面那一次（boot）才整页回填。
    if (!keepValues) fillOnboard(d);
    drawObStatus(d);
    setupMaybeOpen(d, false);
    return d;
  }).catch(function(e){
    $("#obSum").className = "obsum bad";
    $("#obSum").textContent = "读不到这一页的数据：" + e;
  }).then(function(d){ busy(btn, false); return d });
}
function obSave(btn, values, msgSel, block){
  busy(btn, true);
  obMsg(msgSel, "保存中…");
  return post({action: "onboarding.save", values: values}).then(function(r){
    if (!r){ obMsg(msgSel, "请求没回来，再点一次。", true); return }
    if (r.onboard){
      drawObStatus(r.onboard);
      if (r.ok){
        // 只回填**刚保存的这一块**（别的块里手打还没保存的值不许被冲掉）
        if (block) fillObBlock(block, r.onboard);
      }
    }
    obMsg(msgSel, (r.ok ? "" : "✗ ") + (r.message || ""), !r.ok);
    toast(r.ok ? (r.message || "已保存") : ("保存失败：" + (r.message || "?")),
          r.ok ? "ok" : "bad");
    say((r.ok ? "✓ " : "✗ ") + "初始化：" + (r.message || ""));
    return r;
  }).catch(function(e){
    obMsg(msgSel, "请求失败：" + e, true);
    toast("请求失败：" + e, "bad");
  }).then(function(r){ busy(btn, false); return r });
}
/* ══ 唤醒词：一个词一个 chip（单独加 / 单独改 / 单独删）══════════
   和触发词同一套操作；保存走 onboarding.save 的 agent.wakeWords（数组）。 */
var OBWAKE = [];
function drawWake(){
  var box = $("#obWakeChips");
  if (!box) return;
  box.innerHTML = "";
  if (!OBWAKE.length){
    var em = document.createElement("span");
    em.className = "hint";
    em.textContent = "空";
    box.appendChild(em);
    return;
  }
  OBWAKE.forEach(function(w, i){
    var c = document.createElement("span");
    c.className = "chip";
    var t = document.createElement("b");
    t.textContent = w;
    var e = document.createElement("button");
    e.type = "button"; e.className = "chipx"; e.textContent = "✎"; e.title = "改这个";
    e.addEventListener("click", function(){ editWake(i) });
    var x = document.createElement("button");
    x.type = "button"; x.className = "chipx"; x.textContent = "×"; x.title = "删掉这个";
    x.addEventListener("click", function(){ delWake(w) });
    c.appendChild(t); c.appendChild(e); c.appendChild(x);
    box.appendChild(c);
  });
}
function saveWake(btn, next, label){
  busy(btn, true);
  return post({action: "onboarding.save", values: {"agent.wakeWords": next}}).then(function(r){
    if (r && r.ok){
      OBWAKE = next.slice();
      drawWake();
      say("✓ " + label);
      if (r.onboard) drawObStatus(r.onboard);
    } else {
      say((r && r.message) || "没保存上", true);
    }
    return r;
  }).catch(function(e){ say("没保存上：" + e, true) })
    .then(function(){ busy(btn, false) });
}
function addWake(btn){
  sheet("加一个唤醒词", "她在群里被这么叫也算在叫她。", "", function(v){
    v = String(v || "").trim();
    if (!v) return;
    if (OBWAKE.indexOf(v) >= 0){ say("已经有这个词了", true); return }
    if (v.length > 20){ say("一个词最多 20 个字", true); return }
    saveWake(btn, OBWAKE.concat([v]), "唤醒词 ＋" + v);
  });
}
function editWake(i){
  var w = OBWAKE[i];
  sheet("改唤醒词", "改完立刻生效。留空 = 把这个词删掉。", w, function(v){
    v = String(v || "").trim();
    var next = OBWAKE.slice();
    if (!v){ next.splice(i, 1) } else { next[i] = v }
    saveWake(null, next, "唤醒词 " + (v || "－" + w));
  });
}
function delWake(w){
  sheet("删掉唤醒词「" + w + "」？", "删了以后群里这么叫就不算在叫她了。", null, function(){
    saveWake(null, OBWAKE.filter(function(x){ return x !== w }), "唤醒词 －" + w);
  });
}
document.addEventListener("click", function(ev){
  var b = ev.target.closest ? ev.target.closest("#obWakeAdd") : null;
  if (b){ addWake(b); return }
});

function saveObA(btn){
  obSave(btn, {
    "bot.selfId": digitsOnly($("#obQQ").value),
    "agent.name": deepTrim($("#obNick").value),
    "agent.wakeWords": OBWAKE.slice()
  }, "#obAMsg", "a");
}
function saveObB(btn){
  var v = {
    "port": digitsOnly($("#obPort").value),
    "napcat.baseUrl": tidyUrl($("#obNapUrl").value),
    "bot.autoAcceptGroupInvite": $("#obAccept").checked
  };
  var tok = deepTrim($("#obToken").value);
  if (tok) v["bot.token"] = tok;          // 空 = 不改（下面那行只是提示，不是错误）
  return obSave(btn, v, "#obBMsg", "b").then(function(r){
    // ⚠️ 换了 token 就是**换了面板登录那把** —— 这个浏览器得跟着换，
    //    不然紧接着的请求全 403（门禁又弹出来，用户会以为没存上）。
    //    值来自用户刚敲进这个框的内容（不是服务端回显），存 localStorage 不算泄漏。
    if (r && r.ok && tok){
      TOKEN = tok;
      TOKEN_FROM_URL = false;
      try { localStorage.setItem("fgPanelToken", tok); } catch(e){}
      toast("令牌换了 —— 这个浏览器已经自动用新令牌登录", "ok");
    }
    return r;
  });
}
function tidyUrl(s){
  var v = deepTrim(s).replace(/\s+/g, "");
  if (v && v.indexOf("://") < 0) v = "http://" + v;
  return v.replace(/\/+$/, "");
}
function saveObC(btn){
  var p = parseObGroups();
  if (p.bad){ fieldErr($("#obGroups"), p.bad); return }
  fieldErr($("#obGroups"), "");
  obSave(btn, {"bot.groups": p.rows}, "#obCMsg", "c");
}
function saveObG(btn){
  obSave(btn, {
    "agent.chimeIn.chancePercent": digitsOnly($("#obChance").value),
    "agent.pokeBack.enabled": $("#obPokeBack").checked,
    "bot.control.allowPublic": $("#obAllowPublic").checked,
    "agent.maxGroupReplyChars": digitsOnly($("#obMaxGroup").value),
    "agent.maxPrivateReplyChars": digitsOnly($("#obMaxPrivate").value)
  }, "#obGMsg", "g");
}
function saveObPersona(btn){
  var text = $("#obPersona").value;
  if (!text.trim()){ fieldErr($("#obPersona"), "人设正文不能为空。"); return }
  fieldErr($("#obPersona"), "");
  busy(btn, true);
  post({action: "onboarding.persona", text: text}).then(function(r){
    obMsg("#obEMsg", (r && r.ok ? "" : "✗ ") + ((r && r.message) || ""), !(r && r.ok));
    toast(r && r.ok ? "人设已保存" : ("保存失败：" + ((r && r.message) || "未知错误")),
          r && r.ok ? "ok" : "bad");
    if (r && r.onboard){ drawObStatus(r.onboard); fillObBlock("e", r.onboard) }
  }).catch(function(e){ obMsg("#obEMsg", "请求失败：" + e, true) })
    .then(function(){ busy(btn, false) });
}
function obProbe(btn){
  busy(btn, true);
  $("#obProbeMsg").textContent = "检测中…";
  post({action: "onboarding.probe"}).then(function(r){
    $("#obProbeMsg").textContent = (r && r.ok ? "✓ " : "✗ ") +
      ((r && r.message) || "没测成");
    toast(r && r.ok ? ("NapCat 连上了：" + (r.message || "")) :
          ("连不上：" + ((r && r.message) || "?")), r && r.ok ? "ok" : "bad");
    if (r && r.onboard) drawObStatus(r.onboard);
  }).catch(function(e){ $("#obProbeMsg").textContent = "请求失败：" + e })
    .then(function(){ busy(btn, false) });
}
function obGroupPicker(list){
  var box = sheetShell("导入群列表",
    "选择要添加的群。", "添加所选", false, "取消");
  box.innerHTML = '<div class="mp-list" id="obgList">' + (list || []).map(function(g){
    return '<label class="mp-item' + (g.known ? " done" : "") + '">' +
      '<input type="checkbox" data-ogid="' + esc(g.id) + '" data-ogname="' + esc(g.name || "") + '"' +
      (g.known ? " checked disabled" : "") + ">" +
      '<span class="mid">' + esc(g.id) + "</span>" +
      '<span class="mname">' + esc(g.name || "") + "</span>" +
      (g.known ? '<span class="chip">已在名单</span>' : "") + "</label>";
  }).join("") + '</div><p class="msg" id="obgMsg"></p>';
  SHEET_ENTER = false;
  SHEET_RUN = function(){
    var picked = $$("#obgList input[type=checkbox]").filter(function(c){
      return c.checked && !c.disabled;
    });
    if (!picked.length){ $("#obgMsg").textContent = "先勾几个群。"; return }
    var ta = $("#obGroups");
    var lines = String(ta.value || "").split("\n").filter(function(x){ return deepTrim(x) });
    picked.forEach(function(c){
      var gid = c.dataset.ogid;
      var dup = lines.some(function(x){ return deepTrim(x).indexOf(gid) === 0 });
      if (!dup) lines.push(gid + (c.dataset.ogname ? " " + c.dataset.ogname : ""));
    });
    ta.value = lines.join("\n");
    closeSheet();
    toast("群已添加；保存后生效。", "ok");
  };
}
function obPull(btn){
  busy(btn, true);
  $("#obPullMsg").textContent = "拉取中…";
  post({action: "onboarding.groups"}).then(function(r){
    if (!r || !r.ok || !(r.groups || []).length){
      $("#obPullMsg").textContent = (r && r.message) || "无法导入，请手动输入群号。";
      return;
    }
    $("#obPullMsg").textContent = "✓ " + (r.message || "");
    obGroupPicker(r.groups);
  }).catch(function(e){ $("#obPullMsg").textContent = "拉取失败：" + e })
    .then(function(){ busy(btn, false) });
}
$("#obASave").addEventListener("click", function(){ saveObA(this) });
$("#obBSave").addEventListener("click", function(){ saveObB(this) });
$("#obCSave").addEventListener("click", function(){ saveObC(this) });
$("#obGSave").addEventListener("click", function(){ saveObG(this) });
$("#obESave").addEventListener("click", function(){ saveObPersona(this) });
$("#obProbe").addEventListener("click", function(){ obProbe(this) });
$("#obPull").addEventListener("click", function(){ obPull(this) });
$("#obRefresh").addEventListener("click", function(){ loadOnboard(this, true) });
$("#obTokenGen").addEventListener("click", function(){
  var el = $("#obToken");
  el.value = obRandomToken();
  el.focus(); el.select();
  toast("已生成令牌，保存后生效。", "ok");
});
$("#obTokenEye").addEventListener("click", function(){
  var el = $("#obToken"), show = el.type === "password";
  el.type = show ? "text" : "password";
  this.textContent = show ? "隐藏" : "显示";
  el.focus();
});

/* ══ 扩展（扩展包 / 知识锁）═══════════════════════════════════
   动作走 POST /api 的 capability.*（**只有主人**能调，别人 403 空正文）。
   · 一行一个包：名字 / 一句话 / 带不带工具 / 状态（已加载 · 校验失败：第 N 条 · 已停用）；
   · 按钮：启用 / 停用 / 卸载 / 安装（上传 zip）；
   · 报错显示校验规则编号 + 一句人话；**成功静默**（只把列表重画）。
   ⛔ 这一块一个字都不进给模型看的材料 —— 它只决定"装了什么、能不能用"。 */
var CAPS = [];
function capMsg(t, bad){
  var el = $("#capMsg");
  if (!el) return;
  el.textContent = t || "";
  el.className = "msg" + (bad ? " bad" : "");
}
function capChip(c){
  if (!c.loaded) return '<span class="chip bad">校验失败：第 ' + (c.error_rule || 1) + " 条</span>";
  if (!c.enabled) return '<span class="chip">已停用</span>';
  return '<span class="chip ok">已加载</span>';
}
function drawCapabilities(){
  var box = $("#capList");
  if (!box) return;
  $("#capCount").textContent = CAPS.length + " 个包";
  if (!CAPS.length){
    box.innerHTML = '<div class="empty">还没有任何扩展包。用一个 zip 装一个试试。</div>';
    return;
  }
  box.innerHTML = CAPS.map(function(c){
    var bits = [];
    bits.push(c.has_tools ? ("带工具 " + (c.tools || []).join("、")) : "只有说明");
    bits.push(c.builtin ? "仓库自带" : "装的");
    return '<div class="fact"><span class="dot" style="background:' +
      (c.loaded && c.enabled ? "var(--ok)" : "var(--faint)") + '"></span>' +
      '<div class="txt"><b>' + esc(c.name) + "</b> " + capChip(c) +
      '<div class="hint">' + esc(c.description || "（没写一句话）") + " · " + bits.join(" · ") + "</div>" +
      (c.error ? '<div class="hint">' + esc(c.error) + "</div>" : "") + "</div>" +
      '<span class="rowacts">' +
        (c.loaded
          ? '<button class="iconbtn" data-cap-toggle="' + esc(c.name) + '" data-cap-on="' +
            (c.enabled ? "0" : "1") + '" title="' + (c.enabled ? "停用" : "启用") + '">' +
            I.eyeoff + '<span class="lbl">' + (c.enabled ? "停用" : "启用") + "</span></button>"
          : "") +
        (c.can_remove
          ? '<span class="sep"></span><button class="iconbtn danger" data-cap-rm="' +
            esc(c.name) + '" title="卸载">' + I.trash + '<span class="lbl">卸载</span></button>'
          : "") +
      "</span></div>";
  }).join("");
}
function loadCapabilities(btn){
  busy(btn, true);
  return post({action: "capability.list"}).then(function(r){
    if (r && r.capabilities){ CAPS = r.capabilities; drawCapabilities() }
    else capMsg((r && r.message) || "读不到扩展包列表", true);
    if (r && typeof r.extraHosts !== "undefined"){
      CAPHOSTS = (r.extraHosts || []).slice();
      drawHosts();
    }
    var px = $("#capProxy");
    if (px && r && typeof r.downloadProxy !== "undefined"){
      px.value = r.downloadProxy || "";
    }
    return r;
  }).catch(function(e){ capMsg("读扩展包失败：" + e, true); return null })
    .then(function(r){ busy(btn, false); return r });
}
function capToggle(name, on, btn){
  busy(btn, true);
  post({action: on ? "capability.enable" : "capability.disable", name: name}).then(function(r){
    if (r && r.capabilities){ CAPS = r.capabilities; drawCapabilities() }
    capMsg(r && r.ok ? "" : ((r && r.message) || "没改成"), !(r && r.ok));
    return r;
  }).catch(function(e){ capMsg("没改成：" + e, true) })
    .then(function(){ busy(btn, false) });
}
function capRemove(name, btn){
  sheet("卸载「" + name + "」？",
    "· 这个包的目录会从 capabilities/ 里删掉（有备份也一起清）。\n" +
    "· 想留着以后再用：改成「停用」就行 —— 目录行消失、工具也解锁不了。",
    null, function(){
      busy(btn, true);
      post({action: "capability.remove", name: name}).then(function(r){
        if (r && r.capabilities){ CAPS = r.capabilities; drawCapabilities() }
        capMsg(r && r.ok ? "" : ((r && r.message) || "没卸掉"), !(r && r.ok));
        return r;
      }).catch(function(e){ capMsg("没卸掉：" + e, true) })
        .then(function(){ busy(btn, false) });
    }, "卸载", {danger: true});
}
function pickCapability(btn){
  var f = $("#capFile");
  if (!f) return;
  f.value = "";
  f.onchange = function(){
    var file = f.files && f.files[0];
    if (!file) return;
    if (file.size > 600 * 1024){
      capMsg("这个 zip 太大了（" + file.size + " 字节）—— 扩展包应该很小（说明 + 一个 tool.py）", true);
      return;
    }
    var rd = new FileReader();
    rd.onload = function(){ capInstall(btn, String(rd.result || ""), file.name) };
    rd.onerror = function(){ capMsg("读不了这个文件", true) };
    rd.readAsDataURL(file);
  };
  f.click();
}
function capInstall(btn, dataUrl, filename){
  busy(btn, true);
  capMsg("正在装 " + (filename || "这个包") + "…");
  post({action: "capability.install", zip: dataUrl, filename: filename}).then(function(r){
    if (r && r.capabilities){ CAPS = r.capabilities; drawCapabilities() }
    /* 成功静默：清掉提示就行；失败才把编号 + 人话摆出来 */
    capMsg(r && r.ok ? "" : ((r && r.message) || "没装上"), !(r && r.ok));
    return r;
  }).catch(function(e){ capMsg("没装上：" + e, true) })
    .then(function(){ busy(btn, false) });
}

/* ── 从网址安装（2026-10-31）────────────────────────────────────
   两步：预检（服务端下载 → 校验 → 回执直接摆出来）→ 「确认安装」（按票据装，不重下）。
   ⛔ 预检不落进 capabilities/；只有确认那一下才装。 */
var CAPTICKET = "";
function capReceipt(r){
  var box = $("#capReceipt");
  if (!box) return;
  if (!r || !r["包名"]){ box.hidden = true; box.innerHTML = ""; return }
  var rules = (r["六条校验"] || []).map(function(x){
    return '<div class="hint">' + (x["通过"] ? "✓" : "✗") + " 第 " + x["规则"] + " 条" +
      (x["说明"] ? "：" + esc(x["说明"]) : (x["警告"] ? "：（只警告，不拒）" : "")) + "</div>";
  }).join("");
  var tools = (r["会新增的工具"] || []);
  box.innerHTML = '<div class="fact"><div class="txt"><b>' + esc(r["包名"]) + "</b> " +
    '<span class="chip ' + (r.ok ? "ok" : "bad") + '">' + (r.ok ? "预检通过" : "预检没过") + "</span>" +
    '<div class="hint">' + esc(r["一句话"] || "（没写一句话）") + "</div>" +
    '<div class="hint">工具：' + (tools.length ? esc(tools.join("、")) : "只有说明") +
    " ｜ 大小 " + esc(r["大小"] || "?") + "</div>" +
    '<div class="hint">文件：' + esc((r["文件清单"] || []).join("、")) + "</div>" +
    '<div class="hint">sha256 ' + esc(r["sha256"] || "") + "</div>" + rules +
    (r["下一步"] ? '<div class="hint">' + esc(r["下一步"]) + "</div>" : "") +
    "</div></div>" +
    (r.ok ? '<div class="rowsep mt"><button class="btn primary sm" type="button" ' +
      'onclick="capUrlInstall(this)">确认安装</button></div>' : "");
  box.hidden = false;
}
function capUrlCheck(btn){
  var el = $("#capUrl");
  var url = el ? String(el.value || "").trim() : "";
  if (!url){ capMsg("先填一个网址", true); return }
  busy(btn, true);
  capMsg("正在下载并预检…");
  post({action: "capability.check_url", url: url}).then(function(r){
    CAPTICKET = (r && r.ticket) || "";
    if (r && r.capabilities){ CAPS = r.capabilities; drawCapabilities() }
    capReceipt(r);
    capMsg(r && r.ok ? "" : ((r && r.message) || "预检没过"), !(r && r.ok));
    return r;
  }).catch(function(e){
    CAPTICKET = ""; capReceipt(null); capMsg("预检失败：" + e, true);
  }).then(function(){ busy(btn, false) });
}
function capUrlInstall(btn){
  if (!CAPTICKET){ capMsg("先做一次预检", true); return }
  busy(btn, true);
  capMsg("正在装…");
  post({action: "capability.install_url", ticket: CAPTICKET}).then(function(r){
    if (r && r.capabilities){ CAPS = r.capabilities; drawCapabilities() }
    if (r && r.ok){
      CAPTICKET = ""; capReceipt(null); capMsg("装好了");
    } else {
      capMsg((r && r.message) || "没装上", true);
    }
    return r;
  }).catch(function(e){ capMsg("没装上：" + e, true) })
    .then(function(){ busy(btn, false) });
}
function capSaveProxy(btn){
  var el = $("#capProxy");
  var v = String((el && el.value) || "").trim();
  busy(btn, true);
  post({action: "onboarding.save", values: {"capability.downloadProxy": v}}).then(function(r){
    if (r && r.ok){
      capMsg(v ? ("下载代理：" + v) : "下载代理清空了（直连）");
      if (el) el.value = v;
    } else {
      capMsg((r && r.message) || "没保存上", true);
    }
    return r;
  }).catch(function(e){ capMsg("没保存上：" + e, true) })
    .then(function(){ busy(btn, false) });
}
/* ══ 额外允许域名：一个域名一个 chip（单独加 / 单独删）══════ */
var CAPHOSTS = [];
function drawHosts(){
  var box = $("#capHostChips");
  if (!box) return;
  box.innerHTML = "";
  if (!CAPHOSTS.length){
    var em = document.createElement("span");
    em.className = "hint";
    em.textContent = "空";
    box.appendChild(em);
    return;
  }
  CAPHOSTS.forEach(function(h){
    var c = document.createElement("span");
    c.className = "chip";
    var t = document.createElement("b");
    t.textContent = h;
    var x = document.createElement("button");
    x.type = "button"; x.className = "chipx"; x.textContent = "×"; x.title = "删掉这个";
    x.addEventListener("click", function(){ delHost(h) });
    c.appendChild(t); c.appendChild(x);
    box.appendChild(c);
  });
}
function saveHosts(next, label){
  return post({action: "onboarding.save", values: {"capability.extraHosts": next}}).then(function(r){
    if (r && r.ok){ CAPHOSTS = next.slice(); drawHosts(); capMsg(label); }
    else { capMsg((r && r.message) || "没保存上", true); }
    return r;
  }).catch(function(e){ capMsg("没保存上：" + e, true) });
}
function addHost(btn){
  sheet("加一个允许下载的域名", "写域名就行（含子域），例如 ghproxy.com。", "", function(v){
    v = String(v || "").trim().toLowerCase();
    if (!v) return;
    if (!/^[a-z0-9.-]+\.[a-z]{2,}$/.test(v)){ capMsg("这不像域名：" + v, true); return }
    if (CAPHOSTS.indexOf(v) >= 0){ capMsg("已经有这个域名了", true); return }
    saveHosts(CAPHOSTS.concat([v]), "额外允许域名 ＋" + v);
  });
}
function delHost(h){
  sheet("删掉域名「" + h + "」？", "删了以后从它下载扩展包会被拒。", null, function(){
    saveHosts(CAPHOSTS.filter(function(x){ return x !== h }), "额外允许域名 －" + h);
  });
}
document.addEventListener("click", function(ev){
  var b = ev.target.closest ? ev.target.closest("#capHostAdd") : null;
  if (b){ addHost(b); return }
});

/* capSaveHosts 已废弃：额外允许域名改成芯片（2026-11-01） */
document.addEventListener("click", function(ev){
  var b = ev.target.closest ? ev.target.closest("[data-cap-toggle]") : null;
  if (b) { capToggle(b.dataset.capToggle, b.dataset.capOn === "1", b); return }
  var d = ev.target.closest ? ev.target.closest("[data-cap-rm]") : null;
  if (d) capRemove(d.dataset.capRm, d);
});

/* ══ 危险操作（二次确认在 resetChat / restartHer 里）════════════ */
function resetChat(btn){
  sheet("重置对话？",
    "· 她下一条消息就当第一次见你们。\n· 正在聊的那场对话会被清掉。\n" +
    "· 她的**称呼和长期记忆都还在**，群名单、API 配置也不动。",
    null, function(){ act("reset", "重置对话", null, btn) }, "重置对话", {danger:true});
}
function restartHer(btn){
  act("restart", "重启机器人（约 10 秒；期间消息可能漏掉）", null, btn);
}

/* ══ 启动 ══════════════════════════════════════════════════════ */
function boot(){
  if (PANEL_REMOTE){
    // 反代后面：服务端在给这一页之前已经验过登录（凭据在 HttpOnly cookie 里）。
    // ⛔ 页面里没有令牌；这个浏览器本地存过的那把也清掉（不靠它、也不带 Bearer）。
    TOKEN = "";
    TOKEN_FROM_URL = false;
    try { localStorage.removeItem("fgPanelToken"); } catch(e){}
    $("#gate").className = "backdrop";
    var _lb = $("#logoutBtn"); if (_lb) _lb.hidden = false;
  } else if (!TOKEN){ needToken(); return }
  else {
    $("#gate").className = "backdrop";       // 这个浏览器已经记住令牌了 —— 收起门禁
  }
  if (TOKEN_FROM_URL){
    // 地址栏那一次（`?token=`）：值在这里已经用上了、参数在 <head> 里也抹了 —— 说一句就走。
    say("✓ 链接里的令牌收到了");
    toast("链接里的令牌收好了 ✓ 地址栏那截已清掉", "ok");
  }
  refresh(false);
  loadRequests(null);                         // 申请那一页 + 左边导航上的条数
  loadMem(null);
  loadUsers(null);
  loadGroups(null);
  loadParams(null);                           // 设置页：运行参数 / 高级参数
  loadProviders(null);                        // 设置页：她的大脑 / 后台模型
  loadOnboard(null);                          // 设置页（只有主人；朋友拿到的是"只有主人能打开"）
  loadCapabilities(null);                     // 扩展页（只有主人；扩展包列表 / 装 / 卸）
  if (!boot._t) boot._t = setInterval(function(){
    if (document.hidden) return;              // 远程模式下没有 TOKEN，凭据在 cookie 里
    refresh(false);
    loadRequests(null);                       // 有人申请加好友/拉群时，导航上的数字自己会变
    // 提供商 / 后台模型也跟着刷（App 那边改了这边能看见）—— 编辑中 / 正在选就不打扰
    var ae = document.activeElement;
    var editing = Object.keys(POPEN).some(function(k){ return POPEN[k] });
    if (!editing && !(ae && ae.closest && ae.closest("#cardBrain, #cardUtility")))
      loadProviders(null);
  }, 15000);
}
applyTheme(document.documentElement.getAttribute("data-theme") || "auto");
bindNumeric($("#newGroupId"));
go((location.hash || "").replace("#", "") || "overview", false);
boot();
</script>
</body></html>
"""


def render(token="", remote=False):
    """渲染面板页面。

    `token` **忽略掉**（留着只是为了兼容老调用）：页面里**一个凭据都不带**。
    `remote=True` 是**公网 / 反代后面**那一页（2026-10-31）：服务端先过了 `/login`，
    凭据在 `HttpOnly` cookie 里 —— 页面照样**不含令牌**，只是门禁换成"401 就跳登录页"、
    右上角多一个「退出」（见 TEMPLATE 里 `PANEL_REMOTE` 那几处）。
    ⛔ 任何时候都别把令牌拼进这份 HTML —— 要看令牌走 `/api` 的 `token.show`。
    """
    return TEMPLATE.replace("__PANEL_REMOTE__", "true" if remote else "false")
