# -*- coding: utf-8 -*-
"""面板脚本（三块，位置不能乱）。"""

JS1 = r"""
/* 主题要在**第一帧之前**定下来，不然会闪一下白（⛔ 跟令牌无关的一个 localStorage 键）。 */
try{
  var _t = localStorage.getItem("fgPanelTheme");
  if (_t === "light" || _t === "dark") document.documentElement.setAttribute("data-theme", _t);
}catch(e){}
"""

JS2 = r"""
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
"""

JS3 = r"""
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
"""
