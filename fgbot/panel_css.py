# -*- coding: utf-8 -*-
"""面板样式。"""

CSS = r"""
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
"""
