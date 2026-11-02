# -*- coding: utf-8 -*-
"""面板 HTML（{{CSS}} / {{JS1..3}} 由 panel.py 填）。"""

PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN" data-theme="auto">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#F4F7F8" id="themeColor">
<title>机魂小悦 · 面板</title>
<style>{{CSS}}</style>
<script>{{JS1}}</script>
<script>{{JS2}}</script>
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

<script>{{JS3}}</script>
</body></html>
"""
