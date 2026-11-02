# -*- coding: utf-8 -*-
"""命令行子命令：--check / --init-config / --set / --persona-file / --list-models / 扩展包。"""
import json
import os
import sys
import urllib.error
import urllib.request

from . import base, capabilities


def cli_help():
    print("""用法：
  python3 phone-bot-v2.py                     起服务
  python3 phone-bot-v2.py --list-models [地址] [密钥]   问那家 API 有哪些模型
  python3 phone-bot-v2.py --init-config       没有 config.json 就从模板生成一份（幂等）
  python3 phone-bot-v2.py --check             打印「能不能跑」检查表（退出码 0/1）
  python3 phone-bot-v2.py --set k=v [k=v …]   无头配置：写 local-config.json，立刻生效
  python3 phone-bot-v2.py --persona-file F    把人设正文从文件写进去（注释不动）
  python3 phone-bot-v2.py --selftest          离线自检
  python3 phone-bot-v2.py --check-capability P   只校验一个扩展包（zip / 目录），逐条打印
  python3 phone-bot-v2.py --install-capability P 装一个扩展包（校验不过一个文件都不落地）
  python3 phone-bot-v2.py --list-capabilities    列出扩展包：名字 / 一句话 / 带不带工具 / 状态
  python3 phone-bot-v2.py --remove-capability N  卸载一个扩展包（备份一起清）

键和面板「初始化」页一一对应：
  bot.selfId                    她的 QQ 号
  bot.token                     两边的 token（同时写 bot.napcatToken）
  port                          上报端口
  host                          监听地址（默认 0.0.0.0；反代后面填 127.0.0.1）
  panel.allowRemote             公网能打开登录页（true/false，默认 false）
  panel.trustedProxies          信任的反代 IP/CIDR，逗号分开（例：127.0.0.1/32）
  napcat.baseUrl                NapCat 的 API 地址
  bot.autoAcceptGroupInvite     自动同意群邀请（true/false）
  bot.groups                    群号，逗号分开（例如 123456789,987654321）
  agent.name                    她叫什么（名字只从这里来）
  agent.wakeWords               唤醒词，顿号分开（可空）
  agent.triggerWords            触发词，顿号或逗号分开
  agent.chimeIn.chancePercent   随机接话概率 0~100
  agent.pokeBack.enabled        戳一戳回击（true/false）
  bot.control.allowPublic       公网能调 /api（true/false）
  agent.maxGroupReplyChars      群聊回复上限（字）
  agent.maxPrivateReplyChars    私聊回复上限（字）
  pcStatus.enabled              电脑状态开关（true/false）
  pcStatus.reportWindow         上报时段（只显示）
  pcStatus.dayCutoff            日期切换点 HH:mm
  pcStatus.computerName         电脑名
  capability.extraHosts         扩展包下载额外允许的域名，逗号分开（例：ghproxy.com,xxx.com）
  capability.downloadProxy      下载扩展包走的 HTTP 代理（例：http://127.0.0.1:7890；空=直连）
  llm.baseUrl / model / apiKey  模型接口（和面板「她的大脑」等价）
  napcat.token                  她调 NapCat 用的 token（和 NapCat 那边一致）
  bot.control.allowIps          允许用面板的来源网段，逗号分开""")
    return 0


def cli_check():
    """`--check`：把「能不能跑」那张表打到终端（和面板 H 块同一套逻辑）。

    ⚠️ 先**真去问一次 NapCat**：以前只看内存里的时间戳，独立进程永远 ✗，
       于是「退出码 0」根本拿不到。
    """
    from fgbot import onboard
    _ok, _why = onboard.probe_napcat()
    if not _ok:
        print("（没问到 NapCat：%s）" % (_why or "没响应"))
    s = onboard.snapshot()
    print("=== 能不能跑 ===")
    for c in s["checklist"]:
        print("  %s %s%s" % ("✓" if c["ok"] else "✗", c["label"],
                            ("  —— " + c["hint"]) if c["hint"] else ""))
    print()
    print("  " + s["summary"]["text"])
    return 0 if s["summary"]["ok"] else 1


def cli_init():
    """`--init-config`：没有 config.json 就从模板拷一份（幂等，不覆盖已有的）。"""
    import os
    import shutil
    from fgbot import base
    here = os.path.dirname(os.path.abspath(__file__))
    dst = os.path.join(base.DATA_DIR, "config.json")
    src = os.path.join(here, "config.json")
    if os.path.exists(dst):
        print("✓ config.json 已经在（%s）—— 没动它" % dst)
        return 0
    if not os.path.exists(src):
        print("✗ 找不到模板 config.json（应该和主程序放一起）")
        return 2
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    print("✓ 从模板生成了 %s" % dst)
    print("  下一步：--set bot.selfId=… bot.token=… 或直接跑 --check 看还差什么")
    return 0


def cli_list_models(base=None, key=None):
    """`--list-models [地址] [密钥]`：问那家 API 有哪些模型，列 id。

    ⚠ 加：用户往往不知道一把 key 能用哪些模型、有几档思考强度。
       agent 拿到 key 后应该**先列出来再问用户选哪个**，别自己编一个模型名。
       地址/密钥不给就用配置里现在那套（llm.baseUrl / llm.apiKey）。
    """
    import json as _json
    import urllib.request as _u
    from fgbot import base as _b, llm
    cfg = _b.cfg().get("llm") or {}
    url_base = (base or "").strip() or str(cfg.get("baseUrl") or "").strip()
    api_key = ((key or "").strip() or llm._key_from_file(cfg)
               or str(cfg.get("apiKey") or "").strip())
    if not url_base:
        print("✗ 没有 API 地址：给一个，或先 --set llm.baseUrl=…")
        return 2
    if not api_key:
        print("✗ 没有密钥：给一个，或先 --set llm.apiKey=…")
        return 2
    url = llm._models_url(url_base)
    hdr = {"Authorization": "Bearer " + api_key, "Accept": "application/json",
           "User-Agent": "curl/8.5.0"}
    if "opencode.ai" in url:
        hdr["x-opencode-session"] = llm._opencode_session()
    print("查询：%s" % url)
    try:
        req = _u.Request(url, method="GET")
        for k, v in hdr.items():
            req.add_header(k, v)
        with _u.urlopen(req, timeout=20) as r:
            body = r.read()
            status = r.status
        if body[:2] == b"\x1f\x8b":          # gzip：有些中转会压，urllib 不自动解
            import gzip as _gz
            body = _gz.decompress(body)
    except Exception as e:
        print("✗ 拉不到模型列表（%s）" % (str(e)[:160],))
        print("  这家可能不是 OpenAI 兼容接口，或 /models 没开；那就只能手填 llm.model=…")
        return 1
    text = body.decode("utf-8", "replace")
    if api_key and api_key in text:
        text = text.replace(api_key, "***")
    try:
        obj = _json.loads(text or "{}")
    except Exception:
        print("✗ 回的不是 JSON（HTTP %s）" % status)
        return 1
    rows = obj.get("data") if isinstance(obj, dict) else obj
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("models") or []
    ids = []
    for r in (rows or []):
        if isinstance(r, str):
            ids.append(r)
        elif isinstance(r, dict):
            mid = str(r.get("id") or r.get("model") or r.get("name") or "").strip()
            if mid:
                ids.append(mid)
    ids = list(dict.fromkeys(ids))
    efforts = {}
    for r in (rows or []):
        if isinstance(r, dict):
            mid = str(r.get("id") or "").strip()
            eff = (((r.get("capabilities") or {}).get("reasoning") or {}).get("effort") or [])
            if mid and isinstance(eff, list) and eff:
                efforts[mid] = [str(x) for x in eff]
    if not ids:
        print("✗ 接口回了 200，但列表是空的（这台可能需要别的路径）")
        return 1
    print("模型 %d 个：" % len(ids))
    for i in ids:
        extra = ("  [思考强度：%s]" % "/".join(efforts[i])) if i in efforts else ""
        print("  " + i + extra)
    print()
    print("思考强度可选：%s（面板「她的大脑」里选）"
          % " / ".join(llm.PANEL_EFFORTS))
    print("挑一个：--set llm.model=<上面的某个 id>")
    return 0


def cli_set(pairs):
    """`--set k=v k=v`：写 local-config.json（和面板 `onboarding.save` 同一条路）。"""
    from fgbot import onboard
    if not pairs:
        print("✗ 要写成 --set 键=值（例如 --set bot.selfId=10001）")
        return 2
    vals = {}
    for p in pairs:
        if "=" not in p:
            print("✗ 每一对要写成 键=值（给的是 %r）" % p)
            return 2
        k, v = p.split("=", 1)
        k = k.strip()
        if not k:
            print("✗ 键不能是空的（给的是 %r）" % p)
            return 2
        if k == "bot.groups":
            # 命令行里用逗号分（面板那边是一行一个）
            v = [{"id": x.strip()} for x in v.replace("，", ",").split(",") if x.strip()]
        vals[k] = v
    ok, msg, _snap = onboard.save(vals)
    print(("✓ " if ok else "✗ ") + msg)
    return 0 if ok else 1


def cli_persona(path):
    """`--persona-file 文件`：把那个文件的正文写进 personality.md（注释不动）。"""
    from fgbot import onboard
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except Exception as e:
        print("✗ 读不出 %s（%s）" % (path, e))
        return 2
    ok, msg, _p = onboard.persona_save(text)
    print(("✓ " if ok else "✗ ") + msg)
    return 0 if ok else 1


# ── 扩展包：一键安装 / 校验 / 列表 / 卸载 ─────────────
#
# 规则与运行时加载**同一份实现**（`fgbot/capabilities.py` 的 `validate()`）：
#   · `--check-capability` 逐条打印六条规则的结果（只校验，一个文件都不落地）；
#   · `--install-capability` 校验 → 备份 → 落地 → 跑一次加载器（失败回滚）。

def _cap_rule_line(rule):
    """六条规则里的一条（`--check-capability` / `--install-capability` 共用）。"""
    from fgbot import capabilities
    mark = "✓" if rule["ok"] else "✗"
    if rule["ok"] and rule.get("warn"):
        mark = "⚠️"
    body = rule.get("message") or ""
    return "  %s 第 %d 条：%s%s" % (mark, rule["rule"],
                                   capabilities.RULES.get(rule["rule"], ""),
                                   ("  ｜ " + body) if body else "")


def cli_cap_check(path):
    """`--check-capability <zip|目录>`：只校验，打印逐条结果。"""
    from fgbot import capabilities
    r = capabilities.check(path)
    print("=== 校验扩展包：%s ===" % path)
    for rule in r.get("rules") or []:
        print(_cap_rule_line(rule))
    if not r.get("rules"):
        print("  ✗ %s" % (r.get("message") or "读不出这个包"))
    print()
    print(("✓ " if r.get("ok") else "✗ ") + (r.get("message") or ""))
    return 0 if r.get("ok") else 1


def cli_cap_install(path):
    """`--install-capability <zip|目录>`：装一个扩展包（失败一个文件都不落地）。"""
    from fgbot import capabilities
    r = capabilities.install(path)
    print("=== 安装扩展包：%s ===" % path)
    for rule in r.get("rules") or []:
        if not rule["ok"] or rule.get("warn"):
            print(_cap_rule_line(rule))
    print(("✓ " if r.get("ok") else "✗ ") + (r.get("message") or ""))
    return 0 if r.get("ok") else 1


def cli_cap_list():
    """`--list-capabilities`：名字 / description / 带不带工具 / 状态。"""
    from fgbot import capabilities
    rows = capabilities.list()
    print("=== 扩展包（%s）===" % capabilities.data_root())
    if not rows:
        print("  还没有任何扩展包。用 --install-capability <zip|目录> 装一个。")
        return 0
    for c in rows:
        print("  %s  ｜ %s ｜ %s ｜ %s" % (
            c["name"],
            c["description"] or "（没写一句话）",
            ("带工具：" + "、".join(c["tools"])) if c["has_tools"] else "不带工具",
            c["status"] + (("  —— " + c["error"]) if c["error"] else "")))
    return 0


def cli_cap_remove(name):
    """`--remove-capability <名字>`：删目录（有备份就一起清）。"""
    from fgbot import capabilities
    r = capabilities.remove(name)
    print(("✓ " if r.get("ok") else "✗ ") + (r.get("message") or ""))
    return 0 if r.get("ok") else 1
