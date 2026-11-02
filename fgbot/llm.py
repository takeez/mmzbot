#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跟模型说话：一次请求怎么拼、一轮工具怎么转、错了怎么办。

**这一层是照 DSH 的 DeepSeek 适配器写的**（`@deepseek-ai/dsh-llm-deepseek`），
下面几条是从它的源码/文档里抄下来的**协议事实**，不是我自己想当然：

  · **思考**：请求里发 `thinking: {"type": "enabled"}` 和 `reasoning_effort: "high"`
    （`off` 只发 `thinking: {"type":"disabled"}`，绝不把 "off" 当强度发出去）。
    实测：打开之后返回的 message 里多一个 `reasoning_content`，`completion_tokens_details`
    里能看到 `reasoning_tokens` —— 是真思考，不是装饰。
  · **上一轮的 `reasoning_content` 要原样传回**下一轮（DSH 的注释：
    「此前 assistant 轮次的推理内容会原样传回，无论该轮次是否调用了工具」）。
  · **工具结果**是独立的一条消息：`{role:"tool", tool_call_id, content}`，
    内容为空时兜一句 `"(no output)"`（DSH 的适配器就是这么兜的）。
  · **每一个 `tool_calls` 都必须有对应的 `tool` 回复**，少一条就是 400
    （实测原文：`An assistant message with 'tool_calls' must be followed by tool
    messages responding to each 'tool_call_id'`）—— 所以就算工具名字不认识、
    工具自己炸了，也必须回一条。
  · **纯文本的 user 消息用紧凑的字符串形式**，只有带图才用多段内容
    （DSH：`Keep text-only user messages on the compact string wire form.`）。
  · **空回复要重试**：没有内容块、也没有工具调用的终止，DSH 把它当 `EMPTY_RESPONSE`
    交给重试执行器处理。
  · **重试策略**照 DSH 的 normal mode：只重试 `EMPTY_RESPONSE / RATE_LIMIT / SERVER /
    TRANSPORT`，有界预算、指数退避、遵守 `Retry-After`。
    ⚠️ **唯一的例外是超时**（DSH 会重试它，这个项目不重试）：v1 的教训是
    「超时重试 = 白等 + 可能重复计费」，而手机上的她让用户多等两分钟比少答一句更糟。

⚠️ 这里是**唯一的出网点**：全项目只有这个文件发 HTTP 给模型。
   自检要离线跑，所以留了 `set_transport()` 换掉传输层（假模型）。
"""

import contextlib
import http.client
import json
import os
import random
import re
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid

from . import base, guards, settings, store, toolkit

# opencode 中转站的会话头（进程内固定一个，懒生成）—— 见 connection()
_OC_SESSION = ""

APIS_FILE = "llm-apis.txt"
RUNTIME_FILE = "runtime.json"      # 手机上改的运行开关（App/面板），deploy 不覆盖

# ── 提供商 / 模型目录──────────────────
#
# `llm-apis.txt` 的形状（v2）：
#   {"active":  {"provider","model","effort","effortFrom"},
#    "utility": {"inherit","provider","model","effort"},
#    "providers":[{"id","name","baseUrl","key","models":[{"id","name"}]}]}
# ⚠️ 老格式 `{"active":"名字","apis":[{name,baseUrl,model,key}]}` **读的时候自动迁移**
#    并写回去，一条都不许丢（见 `_migrate_flat`）。
# ⛔ 只支持 OpenAI 兼容的 `chat/completions` —— 别的协议（Anthropic 那些）不加。
BUILTIN_PROVIDERS = (
    ("opencode-go", "OpenCode Go", "https://opencode.ai/zen/go/v1"),
    ("deepseek", "DeepSeek", "https://api.deepseek.com/v1"),
    ("openai", "OpenAI", "https://api.openai.com/v1"),
    ("google", "Google", "https://generativelanguage.googleapis.com/v1beta/openai"),
    ("moonshotai", "Moonshot AI", "https://api.moonshot.ai/v1"),
    ("minimax", "MiniMax", "https://api.minimax.chat/v1"),
    ("openrouter", "OpenRouter", "https://openrouter.ai/api/v1"),
    ("groq", "Groq", "https://api.groq.com/openai/v1"),
    ("mistral", "Mistral", "https://api.mistral.ai/v1"),
    ("xai", "xAI", "https://api.x.ai/v1"),
)
BUILTIN_URL = {i: u for i, _n, u in BUILTIN_PROVIDERS}
BUILTIN_NAME = {i: n for i, n, _u in BUILTIN_PROVIDERS}

# 思考强度：DSH 面板上那四个 + 两个老取值（App 可能还在用 off / max，别让它们被拒）。
EFFORTS = ("off", "none", "low", "medium", "high", "max")
PANEL_EFFORTS = ("none", "low", "medium", "high")

# 拉模型列表的传输层挂钩（自检打桩用；None = 真去请求）。
_MODELS_FETCH = None

# DSH normal mode 的重试口径（次数按手机上的耐心收紧：初次 + 2 次）
RETRY_STATUS = (429, 500, 502, 503, 504)
MAX_TRIES = 3
BACKOFF = (0.5, 2.0)

# 空回复进日志时，原始返回体截多长
EMPTY_BODY_CHARS = 800

_TRANSPORT = None                 # 自检挂钩：假传输层
_STARTED = time.time()

# 真网络这条路**一次只跑一个**：总时长看门狗要临时改 http.client 的内部函数
# （进程级的补丁），两个请求同时跑就会互相把补丁拆掉。串行化的代价可以忽略
# （每场对话本来就各有一个串行 worker），换来的是滴水不漏。
_REAL_LOCK = threading.Lock()


class LlmError(Exception):
    def __init__(self, msg, code="LLM", retryable=False, status=None):
        Exception.__init__(self, msg)
        self.code = code
        self.retryable = retryable
        self.status = status


def set_transport(fn):
    """自检挂钩：`fn(url, payload, headers, timeout) -> dict`（离线假模型）。"""
    global _TRANSPORT
    _TRANSPORT = fn


# ── 用哪家（llm-apis.txt v2：提供商 → 模型目录 → 当前用哪个）──────────

def _s(v):
    """任何东西 → 去掉首尾空白的字符串（None → ""）。"""
    if v is None:
        return ""
    return v.strip() if isinstance(v, str) else str(v).strip()


def _slug(s):
    """名字 → id（只留小写字母/数字/连字符）；中文名会变成空串，调用方兜底。"""
    return re.sub(r"[^a-z0-9]+", "-", _s(s).lower()).strip("-")[:40]


def _uniq_id(base, used):
    base = base or "provider"
    if base not in used:
        return base
    i = 2
    while ("%s-%d" % (base, i)) in used:
        i += 1
    return "%s-%d" % (base, i)


def _model_list(raw):
    """模型目录 → `[{"id","name"}]`：去掉空的、按 id 去重，顺序不变。

    `raw` 可以是 `["模型id", …]`（老格式 / 手填）或者 `[{"id","name"}, …]`。
    """
    out, seen = [], set()
    for m in (raw or []):
        if isinstance(m, str):
            mid, name = _s(m), ""
        elif isinstance(m, dict):
            mid = _s(m.get("id") or m.get("model") or m.get("name"))
            name = _s(m.get("name"))
        else:
            continue
        if not mid or mid in seen:
            continue
        seen.add(mid)
        out.append({"id": mid, "name": name or mid})
    return out


def _blank_doc():
    return {"active": {"provider": "", "model": "", "effort": "", "effortFrom": ""},
            "utility": {"inherit": True, "provider": "", "model": "", "effort": "low"},
            "providers": []}


def _normalize(d):
    """把读到的 v2 收拾成固定形状（不改盘；坏字段一律当空的，绝不抛异常）。"""
    if not isinstance(d, dict):
        d = {}
    doc = _blank_doc()
    act = d.get("active") if isinstance(d.get("active"), dict) else {}
    doc["active"] = {"provider": _s(act.get("provider")),
                     "model": _s(act.get("model")),
                     "effort": _s(act.get("effort")).lower(),
                     "effortFrom": _s(act.get("effortFrom"))}
    util = d.get("utility") if isinstance(d.get("utility"), dict) else {}
    inh = util.get("inherit", True)
    if isinstance(inh, str):
        inh = inh.strip().lower() not in ("0", "false", "no", "off", "")
    doc["utility"] = {"inherit": bool(inh),
                      "provider": _s(util.get("provider")),
                      "model": _s(util.get("model")),
                      "effort": _s(util.get("effort")).lower() or "low"}
    used = set()
    for p in (d.get("providers") or []):
        if not isinstance(p, dict):
            continue
        pid = _slug(p.get("id")) or _slug(p.get("name"))
        pid = _uniq_id(pid, used)
        used.add(pid)
        name = _s(p.get("name")) or BUILTIN_NAME.get(pid) or pid
        item = {"id": pid, "name": name, "baseUrl": _s(p.get("baseUrl")),
                "key": _s(p.get("key")), "models": _model_list(p.get("models"))}
        if _s(p.get("visionModel")):
            item["visionModel"] = _s(p.get("visionModel"))
        doc["providers"].append(item)
    return doc


def _is_flat(d):
    """老格式？`{"active":"名字","apis":[{name,baseUrl,model,key}]}`"""
    return isinstance(d.get("apis"), list) and not isinstance(d.get("active"), dict)


def _migrate_flat(d):
    """老格式 → v2。**一条都不丢**：每家变成一个 provider，模型进它的目录。

    `active` 从"名字"翻成"provider id + model"；思考强度取老的 `runtime.json`
    （手机 App 改过的那个值），没有就给 `low`。
    """
    doc = _blank_doc()
    used = set()
    by_name = {}
    for i, a in enumerate(d.get("apis") or []):
        if not isinstance(a, dict):
            continue
        name = _s(a.get("name"))
        if not name:
            continue
        pid = _slug(name) or ("provider-%d" % (i + 1))
        pid = _uniq_id(pid, used)
        used.add(pid)
        p = {"id": pid, "name": name, "baseUrl": _s(a.get("baseUrl")),
             "key": _s(a.get("key")),
             "models": _model_list([a.get("model")] if _s(a.get("model")) else [])}
        if _s(a.get("visionModel")):
            p["visionModel"] = _s(a.get("visionModel"))
        doc["providers"].append(p)
        by_name.setdefault(name, (p, a))
    act_name = _s(d.get("active"))
    hit = by_name.get(act_name)
    if hit:
        doc["active"]["provider"] = hit[0]["id"]
        doc["active"]["model"] = _s(hit[1].get("model"))
    old = _s(runtime_get("reasoningEffort")).lower()
    doc["active"]["effort"] = old if old in EFFORTS else "low"
    doc["active"]["effortFrom"] = "手机改的" if old in EFFORTS else "默认"
    return doc


def apis_doc():
    """读 `llm-apis.txt`。**老格式当场迁移并写回去**；坏文件当空的用（绝不抛异常）。"""
    raw = store.read_json(APIS_FILE) or {}
    if not isinstance(raw, dict):
        raw = {}
    if raw and _is_flat(raw):
        d = _migrate_flat(raw)
        _save_apis(d)
        base.log("llm-apis.txt 老格式已自动迁移到 v2（%d 家提供商，一条没丢）"
                 % len(d["providers"]))
        return d
    return _normalize(raw)


def _save_apis(d):
    return store.write_json(APIS_FILE, d)


def _find_provider(d, pid):
    pid = _s(pid)
    if not pid:
        return None
    for p in d.get("providers") or []:
        if p["id"] == pid:
            return p
    return None


def active_api():
    """当前启用那家（**返回形状跟老版本一模一样**：name/baseUrl/key/model/visionModel）。

    ⚠️ `connection()` 和别处都按这几个键取值 —— 加键可以，⛔ 改名不行。
    """
    d = apis_doc()
    act = d["active"]
    p = _find_provider(d, act.get("provider"))
    if not p:
        return None
    models = p.get("models") or []
    model = _s(act.get("model")) or (models[0]["id"] if models else "")
    return {"id": p["id"], "name": p.get("name") or p["id"],
            "baseUrl": _s(p.get("baseUrl")) or BUILTIN_URL.get(p["id"], ""),
            "key": p.get("key") or "",
            "model": model,
            "visionModel": p.get("visionModel") or ""}


def _key_from_file(cfg):
    """key 文件在哪：**跟 config.json 一个目录**（它是部署侧的秘密，不是她的状态）。

    ⚠️ 不能用 store.path() —— 那是"她的状态"目录，自检时会指到临时目录，
       于是自检里读不到 key（真机上两者是同一个目录，本地才会露出来）。
    ⚠️ 数据目录可配之后，这里用 `base.existing_or_data()`
       **先数据目录、再代码目录**。仍然是"跟 config.json 一个目录"，
       只是那个目录不再写死成代码所在目录。
    """
    # ⚠ 以前 keyFile 写成空串也会回落默认 `llm-key.txt` ✗
    #   于是「面板/--set 填了 llm.apiKey」时，数据目录里那份旧 llm-key.txt
    #   仍然盖过它 → 用户看到的是"填了不生效"（部署验收时发现的）。
    #   现在：**显式写空 = 不要文件**（自己配了 apiKey 就该听 apiKey）。
    if "keyFile" in cfg:
        name = str(cfg.get("keyFile") or "").strip()
        if not name:
            return ""
    else:
        name = "llm-key.txt"
    p = name if os.path.isabs(name) else base.existing_or_data(name)
    try:
        with open(p, encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def runtime_get(key, default=None):
    d = store.read_json(RUNTIME_FILE) or {}
    return d.get(key, default) if isinstance(d, dict) else default


def runtime_set(key, value):
    """改一个运行开关（存 runtime.json）。

    ⚠️ 为什么不直接改 config.json：那一份是**部署事实**，`deploy.py` 每次推都会
       覆盖它 —— 手机上刚调好的强度，下次推代码就被打回默认了（跟称呼表、
       提醒账本一个道理）。所以运行期改的东西一律进这个文件，它在 NEVER 名单里。
    """
    d = store.read_json(RUNTIME_FILE) or {}
    if not isinstance(d, dict):
        d = {}
    d[key] = value
    return store.write_json(RUNTIME_FILE, d)


def runtime_del(key):
    """删掉一个运行开关（面板「初始化」写 config 之后，要把老的覆盖清掉）。

    返回 `真` = 文件里本来有、现在删了；`假` = 本来就没有 / 写不进。
    """
    d = store.read_json(RUNTIME_FILE) or {}
    if not isinstance(d, dict) or key not in d:
        return False
    d.pop(key, None)
    return store.write_json(RUNTIME_FILE, d)


def effort_now(doc=None):
    """现在的思考强度。返回 `(值, 从哪来)`。

    顺序（：**手机改的 > 面板 > config.json > high**
    只是"面板"那一层从 settings.json 搬到了 `llm-apis.txt` 的 `active.effort`）：
      ① `active.effort` + `active.effortFrom`（面板 / App 都写这里）
      ② 老 `runtime.json` 的 `reasoningEffort`（升级前 App 写过的值，只兜底）
      ③ `config.json` 的 `llm.reasoningEffort`，最后 high
    ⚠️ 老 `settings.json` 里的 `llm.reasoningEffort` **不再认**（读都不读）。
    """
    d = doc if isinstance(doc, dict) else apis_doc()
    act = d.get("active") or {}
    v = _s(act.get("effort")).lower()
    if v in EFFORTS:
        return v, (_s(act.get("effortFrom")) or "面板")
    got = _s(runtime_get("reasoningEffort")).lower()
    if got in EFFORTS:
        return got, "手机改的"
    cfg = base.cfg().get("llm") or {}
    return str(cfg.get("reasoningEffort") or "high"), "config.json"


def set_effort(value):
    """改思考强度（App / 网页面板调）。返回 (ok, 给人看的一句话)。"""
    v = (value or "").strip().lower()
    if v not in EFFORTS:
        return False, "强度只能是 %s 之一（给的是「%s」）" % ("/".join(PANEL_EFFORTS), value)
    with base.lock():
        d = apis_doc()
        d["active"]["effort"] = v
        d["active"]["effortFrom"] = "手机改的"
        _save_apis(d)
    runtime_set("reasoningEffort", v)     # 老版本的地儿也留一份（回滚时还认它）
    base.log("控制面：思考强度改成 %s（下次请求生效，不用重启）" % v)
    return True, "思考强度已改成「%s」，下一条消息就用它（不用重启）" % v


def _opencode_session():
    """opencode 中转站的会话头（进程内固定一个，懒生成）。"""
    global _OC_SESSION
    if not _OC_SESSION:
        _OC_SESSION = str(uuid.uuid4())
    return _OC_SESSION


def _conn_for(d, provider_id, model_id, effort, effort_from):
    """按"提供商 + 模型 + 强度"拼出一次请求要的东西（connection / utility 共用）。

    ⚠️ 返回的键就是老 `connection()` 的整套（别的代码全靠它）。
    """
    cfg = base.cfg().get("llm") or {}
    p = _find_provider(d, provider_id) or {}
    base_url = (_s(p.get("baseUrl")) or BUILTIN_URL.get(p.get("id"), "")
                or cfg.get("baseUrl") or "https://api.deepseek.com/v1").strip()
    base_url = base_url.rstrip("/")
    if not base_url.endswith("/chat/completions"):
        base_url += "/chat/completions"
    key = _s(p.get("key")) or _key_from_file(cfg) or _s(cfg.get("apiKey"))
    thinking = (cfg.get("thinking") or "enabled").strip().lower()
    model = (_s(model_id) or cfg.get("model") or "deepseek-chat").strip()
    # ── 请求头──────────────────────────────────────────
    # ⚠️ opencode 中转站：① 默认 UA 会被 Cloudflare 拦（error code 1010）
    #    ② /zen/go 那条路必须带 `x-opencode-session`，不带就 404 / 402。
    #    → UA 一律给 curl；只有打 opencode 时才加 session 头（别的家不认这个头）。
    hdr = dict(cfg.get("headers") or {})
    hdr.setdefault("User-Agent", "curl/8.5.0")
    if "opencode.ai" in base_url:
        hdr.setdefault("x-opencode-session", _opencode_session())
    return {
        "name": p.get("name") or "config.json",
        "url": base_url,
        "model": model,
        "gemini": model.lower().startswith("gemini"),
        "visionModel": (_s(p.get("visionModel")) or cfg.get("visionModel") or "").strip(),
        "key": key,
        "thinking": thinking,
        "effort": effort,
        "effort_from": effort_from,
        "temperature": cfg.get("temperature", 0.9),
        "maxTokens": settings.get("llm.maxTokens"),
        "timeout": int(cfg.get("timeoutSeconds") or 120),
        # 总时长（wall-clock）上限。⚠️ 它**不是** recv 超时：`timeout` 只管"两次收数据之间
        # 等多久"，对端偶尔滴一个字节就能无限拖；这个管"这次请求一共最多花多久"。
        # 默认 150 = 120（recv）+ 30 秒缓冲 —— 大图那种"慢但正常"的请求不能被误杀。
        "wallSeconds": float(cfg.get("wallTimeoutSeconds") or 150),
        "headers": hdr,
    }


def sync_from_config():
    """config 里的 `llm.baseUrl/model/apiKey` 有值、而 `llm-apis.txt` 还没选过家 → 登记成一家并激活。

    ⚠ 以前这两套是分开的（面板看一套、真正跑的又是另一套）——
      现在统一成一份：config 里填了什么，面板里就能看到什么，能切探多家多模型。
    已经选过家就不动（用户在面板里手选的优先）。
    返回：可能被改过的 `apis_doc()`。
    """
    d = apis_doc()
    if _s((d.get("active") or {}).get("provider")):
        return d
    cfg = base.cfg().get("llm") or {}
    url = _s(cfg.get("baseUrl"))
    model = _s(cfg.get("model"))
    if not url or not model:
        return d
    key = _key_from_file(cfg) or _s(cfg.get("apiKey"))
    # 同一个地址已经在列表里 → 直接用那家
    pid = ""
    for p in d.get("providers") or []:
        if _s(p.get("baseUrl")).rstrip("/") == url.rstrip("/"):
            pid = p.get("id") or ""
            if key and not _s(p.get("key")):
                p["key"] = key
            break
    if not pid:
        pid = "cfg-" + (_s(model).replace("/", "-")[:12] or "default")
        host = url.split("//", 1)[-1].split("/", 1)[0]
        d.setdefault("providers", []).append({
            "id": pid, "name": host or "config.json", "baseUrl": url,
            "key": key, "models": [{"id": model, "name": model}],
        })
    else:
        for p in d.get("providers") or []:
            if p.get("id") == pid:
                ids = [m.get("id") for m in (p.get("models") or [])]
                if model not in ids:
                    p.setdefault("models", []).append({"id": model, "name": model})
    d["active"]["provider"] = pid
    d["active"]["model"] = model
    try:
        _save_apis(d)
        base.log("模型：从 config 里登记了一家提供商并激活（%s / %s）" % (pid, model))
    except Exception as e:
        base.log("模型：登记提供商失败（%r）" % (e,))
    return d


def connection():
    """现在到底用哪家、哪个模型、key 从哪来。**每次请求现算**（改了配置不用重启）。"""
    d = sync_from_config()
    effort, effort_from = effort_now(d)
    act = d["active"]
    return _conn_for(d, act.get("provider"), act.get("model"), effort, effort_from)


def mask(key):
    k = key or ""
    if len(k) <= 8:
        return "已配置" if k else "没有"
    return k[:4] + "****" + k[-4:]


def api_list_public():
    """老 App 读的那个列表（**形状照旧**：name/model/baseUrl/key/active）。

    ⚠️ 新面板走 `providers_public()`（带模型目录）；这里只为了别把老 App 弄坏。
    """
    d = apis_doc()
    act = d["active"]
    out = []
    for p in d["providers"]:
        is_act = p["id"] == act.get("provider")
        models = p.get("models") or []
        mid = _s(act.get("model")) if is_act else (models[0]["id"] if models else "")
        out.append({"name": p.get("name"), "id": p["id"],
                    "model": mid or "(用默认)",
                    "baseUrl": p.get("baseUrl") or "(用默认)",
                    "key": mask(p.get("key")), "active": is_act})
    return out


def providers_public():
    """面板 / `GET /providers` 看的东西。⛔ **任何一把明文 key 都不许出现在这里**。"""
    d = sync_from_config()
    act = d["active"]
    effort, effort_from = effort_now(d)
    out = []
    for p in d["providers"]:
        models = []
        for m in p.get("models") or []:
            models.append({"id": m["id"], "name": m["name"],
                           "active": (p["id"] == act.get("provider")
                                      and m["id"] == act.get("model"))})
        out.append({"id": p["id"], "name": p.get("name"),
                    "baseUrl": p.get("baseUrl") or "",
                    "defaultUrl": BUILTIN_URL.get(p["id"], ""),
                    "custom": p["id"] not in BUILTIN_URL,
                    "key": mask(p.get("key")),
                    "hasKey": bool(_s(p.get("key"))),
                    "models": models,
                    "active": p["id"] == act.get("provider")})
    cur = _find_provider(d, act.get("provider")) or {}
    u = d["utility"]
    return {
        "active": {"provider": act.get("provider") or "",
                   "providerName": cur.get("name") or "",
                   "model": act.get("model") or "",
                   "effort": effort, "effortFrom": effort_from},
        "utility": {"inherit": bool(u.get("inherit", True)),
                    "provider": u.get("provider") or "",
                    "model": u.get("model") or "",
                    "effort": u.get("effort") or "low"},
        "providers": out,
        "builtins": [{"id": i, "name": n, "baseUrl": url}
                     for i, n, url in BUILTIN_PROVIDERS],
        "efforts": list(PANEL_EFFORTS),
    }


# ── 提供商 / 模型目录：增删改（面板那套接口的服务端）────────────────

def _log_providers(what):
    base.log("控制面：%s" % what)


def provider_save(req):
    """增 / 改一家提供商。返回 `(ok, 给人看的一句话)`。

    · `key` 留空 = 保留已保存的那把（面板的占位就是这么写的）；
    · `models` 不传 = 目录不动，传了 = 整个替换；
    · `baseUrl` 留空 = 用内置那家的默认地址（自定义那家必须填）。
    """
    req = req or {}
    pid = _s(req.get("id"))
    name = _s(req.get("name"))
    created = False
    with base.lock():
        d = apis_doc()
        p = _find_provider(d, pid) if pid else None
        if p is None and name:
            p = next((x for x in d["providers"] if x.get("name") == name), None)
        if p is None:
            used = {x["id"] for x in d["providers"]}
            if not pid:
                pid = _uniq_id(_slug(name), used)
                if pid == "provider":
                    i = 1
                    while ("custom-%d" % i) in used:
                        i += 1
                    pid = "custom-%d" % i
            else:
                pid = _uniq_id(pid, used)
            p = {"id": pid, "name": name or BUILTIN_NAME.get(pid) or pid,
                 "baseUrl": "", "key": "", "models": []}
            d["providers"].append(p)
            created = True
        elif name:
            p["name"] = name
        if "baseUrl" in req:
            p["baseUrl"] = _s(req.get("baseUrl"))
            if not _s(p["baseUrl"]) and p["id"] not in BUILTIN_URL:
                if created:
                    d["providers"].remove(p)
                return False, "自定义提供商要填 API 地址。"
        elif created and p["id"] not in BUILTIN_URL:
            d["providers"].remove(p)
            return False, "自定义提供商要填 API 地址。"
        key = req.get("key")
        if isinstance(key, str) and key.strip():
            p["key"] = key.strip()
        if isinstance(req.get("models"), list):
            p["models"] = _model_list(req.get("models"))
        _save_apis(d)
    _log_providers("%s提供商「%s」（%d 个模型）"
                   % ("新增" if created else "保存", p["name"], len(p["models"])))
    return True, ("已添加「%s」" if created else "已保存「%s」") % p["name"]


def provider_delete(pid):
    """删一家提供商。**当前启用的不许删**（先切走）。"""
    pid = _s(pid)
    with base.lock():
        d = apis_doc()
        p = _find_provider(d, pid)
        if not p:
            return False, "没有这家。"
        if d["active"].get("provider") == pid:
            return False, "「%s」正在用，先切到别家再删。" % p["name"]
        d["providers"] = [x for x in d["providers"] if x["id"] != pid]
        if d["utility"].get("provider") == pid:
            d["utility"]["provider"] = ""
            d["utility"]["model"] = ""
        _save_apis(d)
    _log_providers("删了提供商「%s」" % p["name"])
    return True, "已删掉「%s」" % p["name"]


def provider_activate(provider, model, effort=None):
    """切当前用的提供商 / 模型 / 思考强度。返回 `(ok, 一句话)`。"""
    provider = _s(provider)
    model = _s(model)
    eff = _s(effort).lower()
    p = None
    with base.lock():
        d = apis_doc()
        if eff:
            if eff not in EFFORTS:
                return False, "强度只能是 %s 之一。" % "/".join(PANEL_EFFORTS)
            d["active"]["effort"] = eff
            d["active"]["effortFrom"] = "面板"
        if provider:
            p = _find_provider(d, provider)
            if not p:
                return False, "没有这家。"
            ids = [m["id"] for m in p.get("models") or []]
            if model and model not in ids:
                return False, "「%s」的目录里没有这个模型。" % p["name"]
            if not model:
                old = _s(d["active"].get("model"))
                model = old if old in ids else (ids[0] if ids else "")
            d["active"]["provider"] = provider
            d["active"]["model"] = model
        elif not eff:
            return False, "要给提供商，或者给思考强度。"
        _save_apis(d)
    if provider:
        _log_providers("切到「%s / %s」（思考强度 %s）"
                       % (p["name"], model or "默认模型", d["active"].get("effort") or "默认"))
        return True, "已切到「%s / %s」" % (p["name"], model or "默认模型")
    _log_providers("思考强度改成 %s（面板）" % d["active"]["effort"])
    return True, "思考强度已改成「%s」" % d["active"]["effort"]


def provider_del_model(pid, model_id):
    """从目录里删一个模型（正在用的那个不许删）。"""
    mid = _s(model_id)
    with base.lock():
        d = apis_doc()
        p = _find_provider(d, _s(pid))
        if not p:
            return False, "没有这家。"
        if d["active"].get("provider") == p["id"] and _s(d["active"].get("model")) == mid:
            return False, "这个模型正在用，先切到别的模型再删。"
        before = len(p.get("models") or [])
        p["models"] = [m for m in p.get("models") or [] if m["id"] != mid]
        if len(p["models"]) == before:
            return False, "目录里没有这个模型。"
        if d["utility"].get("model") == mid:
            d["utility"]["model"] = ""
        _save_apis(d)
    _log_providers("从「%s」目录删了模型 %s" % (p["name"], mid))
    return True, "已删掉模型「%s」" % mid


def provider_add_models(pid, models):
    """把选中的模型加进目录（已经在里面的跳过，不重复）。"""
    ms = _model_list(models)
    if not ms:
        return False, "没选模型。"
    with base.lock():
        d = apis_doc()
        p = _find_provider(d, _s(pid))
        if not p:
            return False, "没有这家。"
        have = {m["id"] for m in p.get("models") or []}
        add = [m for m in ms if m["id"] not in have]
        p["models"] = (p.get("models") or []) + add
        if add:
            _save_apis(d)
    if not add:
        return True, "这些模型已经在目录里了。"
    _log_providers("给「%s」目录加了 %d 个模型" % (p["name"], len(add)))
    return True, "已添加 %d 个模型" % len(add)


def _models_url(base_url):
    """`https://x/v1`（或 …/chat/completions）→ `https://x/v1/models`。"""
    u = _s(base_url).rstrip("/")
    if u.endswith("/chat/completions"):
        u = u[:-len("/chat/completions")].rstrip("/")
    return (u + "/models") if u else ""


def _json_err(text):
    """从错误返回体里挑一句人能看的（挑不出来就截前 80 字）。"""
    try:
        o = json.loads(text or "{}")
    except Exception:
        return _s(text).replace("\n", " ")[:80]
    if isinstance(o, dict):
        e = o.get("error")
        if isinstance(e, dict):
            e = e.get("message") or e.get("type")
        return _s(e or o.get("message") or o.get("detail"))[:80]
    return ""


def set_models_fetcher(fn):
    """自检挂钩：`fn(url, headers, timeout) -> (状态码, body)`（离线拉模型列表）。"""
    global _MODELS_FETCH
    _MODELS_FETCH = fn


def provider_fetch_models(pid):
    """拉「这家有哪些模型」。返回 `(ok, [{"id","name"}], 一句原因)`。

    ⚠️ **服务端去请求**（key 只在服务端，绝不在浏览器里带 key）；
    ⚠️ 只认 OpenAI 兼容的 `GET <baseUrl>/models`；拉不到就照实说，不假装成功。
    """
    d = apis_doc()
    p = _find_provider(d, _s(pid))
    if not p:
        return False, [], "没有这家。"
    cfg = base.cfg().get("llm") or {}
    base_url = (_s(p.get("baseUrl")) or BUILTIN_URL.get(p["id"], "")
                or _s(cfg.get("baseUrl")))
    key = _s(p.get("key")) or _key_from_file(cfg) or _s(cfg.get("apiKey"))
    if not key:
        return False, [], "这家还没填密钥，先填密钥再拉。"
    url = _models_url(base_url)
    if not url:
        return False, [], "这家还没有 API 地址。"
    hdr = {"Authorization": "Bearer " + key, "Accept": "application/json",
           "User-Agent": "curl/8.5.0"}
    if "opencode.ai" in url:
        hdr["x-opencode-session"] = _opencode_session()
    try:
        if _MODELS_FETCH is not None:
            status, body = _MODELS_FETCH(url, dict(hdr), 15)
        else:
            req = urllib.request.Request(url, method="GET")
            for k, v in hdr.items():
                req.add_header(k, v)
            with urllib.request.urlopen(req, timeout=15) as r:
                status, body = r.status, r.read()
    except urllib.error.HTTPError as e:
        status, body = e.code, b""
        try:
            body = e.read()
        except Exception:
            pass
    except Exception as e:
        return False, [], "连不上这家（%r），检查地址再试。" % (e,)
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body or "")
    if key and key in text:                    # 往回带的东西里绝不许出现 key
        text = text.replace(key, "***")
    if status != 200:
        why = _json_err(text)
        return False, [], "HTTP %d%s，手动填吧。" % (status, ("：" + why) if why else "")
    try:
        obj = json.loads(text or "{}")
    except Exception:
        return False, [], "这家回的不是 JSON（HTTP %d），手动填吧。" % status
    rows = obj.get("data") if isinstance(obj, dict) else obj
    if isinstance(rows, dict):
        rows = rows.get("items") or rows.get("models") or []
    ms, seen = [], set()
    for r in (rows or []):
        if isinstance(r, str):
            mid, nm = _s(r), ""
        elif isinstance(r, dict):
            mid = _s(r.get("id") or r.get("model") or r.get("name"))
            nm = _s(r.get("name") or r.get("display_name"))
        else:
            continue
        if not mid or mid in seen:
            continue
        seen.add(mid)
        ms.append({"id": mid, "name": nm or mid})
    if not ms:
        return False, [], "这家回了 200，但列表是空的，手动填吧。"
    return True, ms, ""


def provider_set_utility(req):
    """后台模型（管家 / 私聊压缩用哪家）：`inherit` + 三个覆盖。"""
    req = req or {}
    with base.lock():
        d = apis_doc()
        u = d["utility"]
        if "inherit" in req:
            inh = req.get("inherit")
            if isinstance(inh, str):
                inh = inh.strip().lower() not in ("0", "false", "no", "off", "")
            u["inherit"] = bool(inh)
        if "provider" in req:
            pid = _s(req.get("provider"))
            if pid and not _find_provider(d, pid):
                return False, "没有这家。"
            u["provider"] = pid
        if "model" in req:
            u["model"] = _s(req.get("model"))
        if "effort" in req:
            eff = _s(req.get("effort")).lower()
            if eff and eff not in EFFORTS:
                return False, "强度只能是 %s 之一。" % "/".join(PANEL_EFFORTS)
            u["effort"] = eff or "low"
        _save_apis(d)
    _log_providers("后台模型：%s（%s / %s / %s）"
                   % ("跟主模型一样" if u["inherit"] else "单独一套",
                      u["provider"] or "默认", u["model"] or "默认", u["effort"]))
    return True, "后台模型已保存"


# ── 老 App 的三个动作（add / use / del）：映射到 v2，别把它们弄坏 ──

def api_add(name, base_url, model, key):
    name = _s(name)
    key = _s(key)
    if not name or not key:
        return False, "名字和 key 至少得填"
    m = _s(model)
    with base.lock():
        d = apis_doc()
        p = next((x for x in d["providers"] if x.get("name") == name), None)
        if p is None:
            used = {x["id"] for x in d["providers"]}
            pid = _uniq_id(_slug(name), used)
            if pid == "provider":
                i = 1
                while ("custom-%d" % i) in used:
                    i += 1
                pid = "custom-%d" % i
            p = {"id": pid, "name": name, "baseUrl": _s(base_url), "key": key,
                 "models": []}
            d["providers"].append(p)
        else:
            p["baseUrl"] = _s(base_url) or p.get("baseUrl") or ""
            p["key"] = key
        if m and not any(x["id"] == m for x in p["models"]):
            p["models"].append({"id": m, "name": m})
        d["active"]["provider"] = p["id"]          # 新加的这家直接切过去（老语义）
        d["active"]["model"] = m
        _save_apis(d)
    _log_providers("加了一家 API「%s」（%s / %s）"
                   % (name, base_url or "默认地址", model or "默认模型"))
    return True, "已保存「%s」并切过去，下一条消息就用它" % name


def api_use(name):
    name = _s(name)
    with base.lock():
        d = apis_doc()
        p = next((x for x in d["providers"] if x.get("name") == name), None)
        if p is None:
            return False, "没有叫「%s」的这家" % name
        d["active"]["provider"] = p["id"]
        models = p.get("models") or []
        d["active"]["model"] = models[0]["id"] if models else ""
        _save_apis(d)
    _log_providers("切到 API「%s」" % name)
    return True, "已切到「%s」" % name


def api_del(name):
    name = _s(name)
    with base.lock():
        d = apis_doc()
        p = next((x for x in d["providers"] if x.get("name") == name), None)
        if p is None:
            return False, "没有叫「%s」的这家" % name
        if d["active"].get("provider") == p["id"]:
            return False, "「%s」正在用，先切到别家再删。" % name
        d["providers"] = [x for x in d["providers"] if x["id"] != p["id"]]
        if d["utility"].get("provider") == p["id"]:
            d["utility"]["provider"] = ""
            d["utility"]["model"] = ""
        _save_apis(d)
    _log_providers("删了 API「%s」" % name)
    return True, "已删掉「%s」" % name


# ── 发一次请求 ──────────────────────────────────────────────────────

def _payload(messages, tools, conn, model=None, max_tokens=None):
    p = {"model": model or conn["model"], "messages": messages, "stream": False}
    if conn.get("gemini"):
        # ⚠️ gemini 走 opencode 中转时不认 `thinking` 字段（发过去 400），
        #    只认 `reasoning_effort`。所以这条路只发 effort，取值 none/low/medium/high。
        eff = "none" if (conn["thinking"] == "disabled" or conn["effort"] == "off") else conn["effort"]
        if eff in ("none", "low", "medium", "high"):
            p["reasoning_effort"] = eff
    # 思考：DSH 的写法 —— enabled 时同时发 thinking 和 reasoning_effort，
    # off 时只发 thinking:disabled（"off" 这个强度本身绝不上线）。
    # ⚠️ 面板多了 `none` / `medium` 两个值 —— `none` 按关思考走，
    #    `medium` 原样发（只影响这两个新值，老四个的行为一个字节没动）。
    elif conn["thinking"] == "disabled" or conn["effort"] in ("off", "none"):
        p["thinking"] = {"type": "disabled"}
    else:
        p["thinking"] = {"type": "enabled"}
        if conn["effort"] in ("low", "medium", "high", "max"):
            p["reasoning_effort"] = conn["effort"]
    if tools:
        p["tools"] = tools
    if conn.get("temperature") is not None:
        p["temperature"] = conn["temperature"]
    p["max_tokens"] = int(max_tokens or conn["maxTokens"])
    return p


def _one_request(payload, conn):
    """一次 HTTP。返回解码后的 JSON。异常一律翻成 LlmError。

    ═══ 两层超时，别混═══

    · `conn["timeout"]`（config 的 `timeoutSeconds`，120 秒）是 **socket 级**的，
      走的是 `urlopen(timeout=…)` → **每一次 recv** 的上限，**不是这次请求的总时长**。
      连接只在"滴血"（隔一会儿来一个字节、永远凑不满 body）时，每来一个字节就重置一次
      —— 120 秒**永远不触发**，人就能挂 15 分钟（那三条 901 秒的请求就是这样
      日志里 0 条超时记录；实验见 `_WallDeadline`）。
    · `conn["wallSeconds"]`（`wallTimeoutSeconds`，默认 150 秒）是**总时长（wall-clock）上限**：
      从发请求那一刻起算，到了就掐断、按"被总时长掐断"报错。
      滴血流也躲不过它，而且它**会走重试**（socket 超时仍然不重试，见文件开头）。
    """
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if _TRANSPORT is not None:
        try:
            return _TRANSPORT(conn["url"], payload, {"Authorization": "Bearer " + conn["key"]},
                              conn["timeout"])
        except LlmError:
            raise
        except Exception as e:
            raise LlmError("假传输层出错：%r" % e, "TRANSPORT", retryable=True)
    req = urllib.request.Request(conn["url"], data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", "Bearer " + conn["key"])
    req.add_header("Accept", "application/json")
    for k, v in (conn.get("headers") or {}).items():
        req.add_header(str(k), str(v))
    with _REAL_LOCK:                     # 真网络这条路一次只跑一个（补丁是进程级的）
        return _request_locked(req, conn)


def _request_locked(req, conn):
    """真正发那一次请求（已经在 _REAL_LOCK 里）。看门狗、异常分类都在这里。"""
    dl = _wall(conn)
    try:
        with dl.armed():
            with urllib.request.urlopen(req, timeout=conn["timeout"]) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")[:400]
        except Exception:
            pass
        code = ("AUTH" if e.code in (401, 403) else
                "RATE_LIMIT" if e.code == 429 else
                "SERVER" if e.code >= 500 else
                "INVALID_REQUEST" if e.code == 400 else "HTTP_%d" % e.code)
        # Retry-After 是提供方给的，优先听它的（DSH 也这么做）
        ra = 0
        try:
            ra = int(e.headers.get("Retry-After") or 0)
        except Exception:
            ra = 0
        err = LlmError("HTTP %d：%s" % (e.code, body), code,
                       retryable=e.code in RETRY_STATUS, status=e.code)
        err.retry_after = ra
        raise err
    except (socket.timeout, TimeoutError):
        # ⚠️ 先分清是谁掐的：总时长（滴血绕过 recv 超时的补救）还是 recv 超时。
        if dl.hit:
            raise LlmError("这次请求被**总时长**掐断了（>%s 秒，滴血连接也躲不过）"
                           % dl.wall, "WALL_TIMEOUT", retryable=True)
        # ⚠️ 单个 recv 超时**不重试**（见文件开头；这是本项目和 DSH 唯一的刻意分歧）
        raise LlmError("等模型等到超时（%s 秒）" % conn["timeout"], "TIMEOUT", retryable=False)
    except urllib.error.URLError as e:
        if dl.hit:
            raise LlmError("这次请求被**总时长**掐断了（>%s 秒，滴血连接也躲不过）"
                           % dl.wall, "WALL_TIMEOUT", retryable=True)
        if isinstance(getattr(e, "reason", None), (socket.timeout, TimeoutError)):
            raise LlmError("等模型等到超时", "TIMEOUT", retryable=False)
        raise LlmError("连不上模型（%r）" % (e.reason,), "TRANSPORT", retryable=True)
    except Exception as e:
        if dl.hit:
            raise LlmError("这次请求被**总时长**掐断了（>%s 秒，滴血连接也躲不过）"
                           % dl.wall, "WALL_TIMEOUT", retryable=True)
        raise LlmError("请求出错：%r" % e, "TRANSPORT", retryable=True)
    finally:
        dl.cancel()


class _WallDeadline(object):
    """总时长的看门狗：**一个定时器 + 一层"真 socket 的子类"**。

    为什么用 socket 包装：`urlopen` 的 `timeout=` 是每次 recv 的上限，只要对端
    偶尔吐一个字节就一次次被重置（"滴血"），总时长无限。这里按**剩余时间**给每次
    recv 设 deadline（剩余时间到 0 就是 0.001 秒，立刻超时），定时器到点再把连接
    关掉，兜住"正在 recv 里出不来"那种情况。
    """

    def __init__(self, wall):
        self.wall = float(wall)
        self.t0 = time.monotonic()
        self.hit = False
        self._socks = []
        self._lock = threading.Lock()
        self._timer = threading.Timer(self.wall, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def remaining(self):
        return self.wall - (time.monotonic() - self.t0)

    def _fire(self):
        """到点了：标记 + 把在用的连接关掉（阻塞在 recv 里的那个立刻醒）。"""
        self.hit = True
        with self._lock:
            for s in self._socks:
                try:
                    s.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    s.close()
                except Exception:
                    pass

    def wrap(self, sock):
        """把真 socket 换成"带 deadline 的 socket"。

        public 方法直接挂到实例上（`sock.recv = …`）—— 因为 socket 是**不变的
        内建类型**，动不了它的类；而实例属性会盖住类方法，recv/sendall/accept
        全部经过这里。返回的就是**原来那个真 socket**（只是被挂了几个方法），
        所以 http.client / ssl 那两层拿到的还是货真价实的 socket，不会有不认识的属性。
        """
        dl = self
        self._socks.append(sock)

        def recv(bufsize, *a, **kw):
            dl._arm(sock)
            return sock.__class__.recv(sock, bufsize, *a, **kw)

        def recv_into(buffer, nbytes=0, *a, **kw):
            dl._arm(sock)
            return sock.__class__.recv_into(sock, buffer, nbytes, *a, **kw)

        def sendall(data, *a, **kw):
            dl._arm(sock)
            return sock.__class__.sendall(sock, data, *a, **kw)

        try:
            sock.recv = recv
            sock.recv_into = recv_into
            sock.sendall = sendall
        except Exception:
            pass          # 挂不上就算了：定时器那层还能兜底
        return sock

    def _arm(self, sock):
        """每次真正收发之前，把 socket 超时压到"离总时长还剩多久"。

        ⚠️ 这就是治"滴血"的那一刀：http.client 建连接时设的 120 秒是**每次** recv
           的上限，会被对端每个字节重置；改成"剩余总时长"之后，总时长一到，
           即使对端还在滴，下一次 recv 也立刻超时。
        """
        left = self.remaining()
        try:
            if left <= 0:
                raise socket.timeout("总时长到了（%s 秒）" % self.wall)
            cur = sock.gettimeout()
            if cur is None or cur > left:
                sock.settimeout(left)
        except socket.timeout:
            raise
        except Exception:
            pass

    def cancel(self):
        try:
            self._timer.cancel()
        except Exception:
            pass

    @contextlib.contextmanager
    def armed(self):
        """让这次请求建出来的连接套上 deadline。

        ⚠️ **怎么套**（试出来的，别乱改）：
           `urllib` → `http.client` 里，连接是 `HTTPHandler.do_open` 自己
           `klass(host, timeout=…)` **new 出来**的，建完立刻 `connect()`；
           而 `connect()` 走的是**实例属性** `self._create_connection`
           （3.10+；老版本是模块全局 `http.client._create_connection`）。
           所以只补模块全局那一个名字是**不够的**（新版 http.client 在 `__init__`
           里就把当时的全局函数抓成了实例属性，补丁根本轮不到）。

           这里两条路一起堵：临时把模块全局换掉，**并且**给这期间 new 出来的每个
           连接实例也换掉它自己的 `_create_connection`。`wrap()` 返回的就是原来那个
           真 socket（只挂了几个方法），所以 http.client / ssl 那两层拿到的还是
           货真价实的 socket —— 不会出现"不认识的属性"那种炸法。

           补丁挂不上（未来版本改了内部结构）也不会坏事：定时器那一层还兜着。
        """
        cc = getattr(http.client, "_create_connection", None)
        orig_init = http.client.HTTPConnection.__init__
        dl = self

        def wrapit(orig):
            def make(address, timeout=socket._GLOBAL_DEFAULT_TIMEOUT,
                     source_address=None, *a, **kw):
                return dl.wrap(orig(address, timeout, source_address, *a, **kw))
            return make

        def patched_init(conn_self, *a, **kw):
            orig_init(conn_self, *a, **kw)
            icc = getattr(conn_self, "_create_connection", None)
            if icc is not None:
                try:
                    conn_self._create_connection = wrapit(icc)
                except Exception:
                    pass

        try:
            if cc is not None:
                http.client._create_connection = wrapit(cc)
            http.client.HTTPConnection.__init__ = patched_init
        except Exception:
            pass
        try:
            yield
        finally:
            try:
                if cc is not None:
                    http.client._create_connection = cc
                http.client.HTTPConnection.__init__ = orig_init
            except Exception:
                pass


def _wall(conn):
    """这次请求的总时长看门狗（`wallTimeoutSeconds`，默认 150 秒）。

    ⚠️ 必须**大于**单次 recv 的 `timeoutSeconds`（120）—— 否则大图那种"慢但正常"
       的请求会被总时长误杀。150 = 120 + 30 秒缓冲。自检会把它调小来造现场。
    """
    try:
        sec = float(conn.get("wallSeconds") or 0) or 150.0
    except Exception:
        sec = 150.0
    return _WallDeadline(sec)


def _digest(payload):
    """请求的"体检报告"：每条消息的角色、长度、带不带 reasoning/tool_calls。

    被 400 拒的时候一定要打这个 —— 不然只能对着「参数不对」干瞪眼。
    """
    out = []
    for m in payload.get("messages") or []:
        c = m.get("content")
        n = len(c) if isinstance(c, str) else sum(
            len(p.get("text") or "") for p in (c or []) if isinstance(p, dict))
        tag = str(m.get("role"))
        if m.get("tool_calls"):
            tag += "+工具"
        if m.get("reasoning_content"):
            tag += "+思考"
        out.append("%s(%d)" % (tag, n))
    return " ".join(out)


def _dump(payload, conn, response=None, error=""):
    """把**这一轮真正发给模型的完整请求**原样存一份（排查用）。

    开关是**一个文件**：`dump-llm.on` 存在就存，删掉就停 —— 不用改配置、不用重启
    （她读文件是按 mtime/存在与否现判的）。存到 `llm-dump.json`，只留最近一次。
    ⚠️ 存的是 messages / tools / 模型参数 / 原始回应 —— **刻意不放 API key**，
       所以这份东西可以拿来给人看（真要排查鉴权再单独说）。看完记得把开关关掉。
    """
    try:
        if not os.path.exists(store.path("dump-llm.on")):
            return
        store.write_json("llm-dump.json", {
            "at": time.strftime("%F %T"),
            "url": conn.get("url"),
            "model": payload.get("model"),
            "thinking": payload.get("thinking"),
            "reasoning_effort": payload.get("reasoning_effort"),
            "tools": payload.get("tools") or [],
            "messages": payload.get("messages") or [],
            "response": response or None,
            "error": error,
        })
    except Exception:
        base.log_exc("_dump")


def _post(payload, conn):
    """带重试的请求（DSH normal mode 的口径，见文件开头）。

    ⚠️ **超时要能查**
       · 总时长掐断 → 日志里明写"被总时长掐断"，而且**走重试**；
       · 单次 recv 超时 → 仍然不重试（见文件开头）；
       · `timeoutSeconds` 那份 config 是 socket 级的上限（每次 recv），
         总拐杖是 `wallTimeoutSeconds`（见 _one_request 的说明）。
    """
    attempts = 0
    wall_hits = 0            # 被总时长掐断的次数（单独计数，别让它把重试次数吃光）
    while True:
        attempts += 1
        t0 = time.monotonic()
        try:
            d = _one_request(payload, conn)
            elapsed = time.monotonic() - t0
            _dump(payload, conn, response=d)
        except LlmError as e:
            if e.status == 400 and "reasoning_content" in str(e):
                # 思考模式下模型要求把上一轮的 reasoning_content 带回来，而我们的历史里
                # 只有"看得见的对话"（见 memory.py）。正常路径不会撞上，但**到点提醒**
                # 这种"没有用户那句话、最后一条是提示"的轮次撞上过（实测 400）。
                # 兜底：关掉思考重发一次 —— 提醒必须发出去，说得朴素点也比哑巴强。
                if payload.get("thinking") != {"type": "disabled"}:
                    base.log("模型嫌没带 reasoning_content，这一轮关掉思考重发一次")
                    payload["thinking"] = {"type": "disabled"}
                    payload.pop("reasoning_effort", None)
                    continue
            if e.code == "WALL_TIMEOUT":
                # 总时长掐断：**重试一次**（这次多半是连接卡死/滴血，重发就能正常回来）
                wall_hits += 1
                base.log("这次请求被总时长掐断了（%.1f 秒），第 %d 次重试"
                         % (time.monotonic() - t0, wall_hits))
                if wall_hits <= 1:
                    time.sleep(0.5)
                    continue
                base.log("又被总时长掐了一次（累计 %d 次）—— 这次不重试了，"
                         "把失败如实报上去（消息长这样：%s）" % (wall_hits, _digest(payload)))
                raise
            if not e.retryable or attempts >= MAX_TRIES:
                base.log("这次请求被拒了（%s），消息长这样：%s" % (e.code, _digest(payload)))
                raise
            wait = getattr(e, "retry_after", 0) or (BACKOFF[min(attempts - 1, len(BACKOFF) - 1)]
                                                    * (1 + random.random() * 0.2))
            base.log("模型这边 %s，%.1f 秒后重试（第 %d 次）" % (e.code, wait, attempts))
            time.sleep(min(wait, 15))
            continue
        # 空回复（既没内容也没工具调用）也重试 —— DSH 的 EMPTY_RESPONSE
        ch = (d.get("choices") or [{}])[0]
        msg = ch.get("message") or {}
        if not (msg.get("content") or "").strip() and not (msg.get("tool_calls") or []):
            # ⚠️ **原始证据一行都不能少**。
            #    finish_reason + 截断后的原始 body + HTTP 状态码 + 这次耗时，全写进日志。
            #    ⛔ 只写日志：给模型看的文本、EMPTY_RESPONSE 这个内部枚举，一个字都不动。
            body = json.dumps(d, ensure_ascii=False)
            base.log("模型回了个空的（EMPTY_RESPONSE）｜%.1f 秒 ｜第 %d 次 ｜"
                     "finish_reason=%r ｜HTTP 200 ｜返回体(前%d字) %s"
                     % (elapsed, attempts, ch.get("finish_reason") or "",
                        EMPTY_BODY_CHARS,
                        body[:EMPTY_BODY_CHARS] + ("…(截断，共 %d 字)" % len(body)
                                                   if len(body) > EMPTY_BODY_CHARS else "")))
            if attempts < MAX_TRIES:
                base.log("模型回了个空的（EMPTY_RESPONSE），重试一次")
                time.sleep(0.5)
                continue
        return d


def _clean_assistant(msg, model=""):
    """assistant 消息回填历史时的**形状**（对齐 DSH 的 serializeAssistant）。

    ⚠️ 推理内容按 DSH 的做法**原样传回**（实测 deepseek-chat/deepseek-flash 收得下）。
       但 `deepseek-reasoner` 那类旧推理模型官方要求**不要**回传，所以按模型名让开。
    """
    out = {"role": "assistant", "content": msg.get("content") or ""}
    reasoning = (msg.get("reasoning_content") or "").strip()
    if reasoning and not re.search(r"reasoner|(^|[-_/])r1($|[-_/])", model or "", re.I):
        out["reasoning_content"] = msg["reasoning_content"]
    tcs = msg.get("tool_calls") or []
    if tcs:
        out["tool_calls"] = [{"id": tc.get("id") or ("call_%d" % i), "type": "function",
                              "function": {"name": (tc.get("function") or {}).get("name") or "",
                                           "arguments": (tc.get("function") or {}).get("arguments") or "{}"}}
                             for i, tc in enumerate(tcs)]
    return out


def chat(messages, tools=None, conn=None, model=None, max_tokens=None):
    """一次对话往返（**不带工具循环**）。返回 model 的 message dict。"""
    conn = conn or connection()
    if not conn["key"] and _TRANSPORT is None:
        # 自检装了假传输层：不需要真 key（部署时暂存目录里本来就没有 key 文件）
        raise LlmError("没有 key（%s 或 config.json 的 llm.apiKey）" % "llm-key.txt",
                       "MISSING_CREDENTIAL", retryable=False)
    payload = _payload(messages, tools, conn, model=model, max_tokens=max_tokens)
    d = _post(payload, conn)
    ch = (d.get("choices") or [{}])[0]
    msg = ch.get("message") or {}
    msg["_finish"] = ch.get("finish_reason")
    msg["_usage"] = d.get("usage") or {}
    msg["_model"] = d.get("model") or payload["model"]
    return msg


# ── ⭐ 「问战况」那一回合的**第 2 次请求**：不带更早的对话历史 ──────────────
#
# （先看 dump 取了证）：`pc_status`（战况）这条路，
# 她**第 1 次请求照旧看完整历史**（该有上下文，自己决定要不要查战况 ✓）；可
# **查到数据之后再问一次**时，只许带「system（人设 + 场合）+ 当前那句 + 她的
# `tool_calls` + `tool` 结果」——更早的那些 user/assistant 历史**一条都不许带**。
#
# 为什么：第 2 次干的事是"照着刚拿到的那几行数据组织一句话"，旧历史在这儿只帮倒忙。
# 真机上出过事：群里八竿子打不着的旧话被这第 2 次扯进来，把「张三」说的话安到了
# 「王五」头上。砍掉之后她只看数据 + 当前这一句。
#
# ⛔ **只对 `pc_status` 这么做**
#   · 同一轮里**只要还混着别的工具**（`memory` / `search` / …）就**照旧带历史** ——
#     它们的材料要跟对话上下文对得上，砍了反而答错（自检里有一条回归钉着它）；
#   · 第 1 次请求**一个字都不动**（见 `run_turn`：第一次 `chat()` 用的还是原样的 messages）。
#
# ⚠️ 砍的位置 = **按本轮边界**：
#    `agent._build()` 拼完这一轮之后把历史那一段的下标记在
#    `ctx["_hist_range"] = (起点, 终点)`（半开区间，终点 = 快照那条的下标）——
#    这里只删那一段，剩下的正好是「system + 快照 + 当前那句（+ 这一轮她自己的
#    tool 往返）」。
#    ⛔ 为什么不再找"最后一条 system"：A2 之后 system 在**最前面**，按那个切会把
#       system 一起切掉、或者切出"`tool` 消息前面没有对应的 `tool_calls`"这种非法序列，
#       DeepSeek 那边**直接 400**（原文见文件头）。⛔ 也不许因为 system 挪到最前
#       就让这条静默失效 —— 所以 `_hist_range` 找不到时**记一行日志**再说。
#    切之前先过一遍 `_pairing_ok()`（对切完的**整串**验），不合法就宁可照旧带着历史。
PC_TRIM_TOOLS = ("pc_status",)


def _pairing_ok(messages):
    """序列合法性：每条 `tool` 都**紧跟**它对应的那条 `assistant.tool_calls`。

    这是 DeepSeek 的硬要求（少一条就 400，原文见文件头）。**只看结构，不看内容。**
    """
    pending = set()
    for m in messages:
        role = m.get("role")
        if role == "tool":
            if m.get("tool_call_id") not in pending:
                return False
            pending.discard(m.get("tool_call_id"))
            continue
        if pending:
            return False                      # 上一条 tool_calls 还没答完
        if role == "assistant" and m.get("tool_calls"):
            pending = {tc.get("id") for tc in m["tool_calls"]}
    return not pending


def _trim_history_after_tool(messages, names, ctx=None):
    """`pc_status` 专用：把**这一轮开始之前的历史**砍掉。返回砍掉几条。

    `ctx["_hist_range"]` 由 `agent._build()` 写：`(历史起点, 历史终点)`。
    ⛔ 只在「这一轮调的工具**全是** `pc_status`」时才砍（混着别的工具 → 照旧带历史，
       理由见上面那一段）；切完先验一次序列合法性 —— 不合法就不砍，宁可多带历史，
       也不能拼出一个会被 400 拒掉的请求。
    """
    if not names or any(n not in PC_TRIM_TOOLS for n in names):
        return 0
    if (ctx or {}).get("_hist_trimmed"):
        # 这一轮的历史已经剪过一次了 —— 再剪一次用的会是移位后的旧下标，
        # 会把「快照 + 当前那句」也删掉。
        return 0
    rng = (ctx or {}).get("_hist_range")
    if not rng:
        # ⚠️ 这条**必须留痕**：A2 改布局时最容易漏的就是这里 —— 漏了会静默变成
        #    "第 2 次请求又带上历史了"，用户看不出来，只有日志能查。
        base.log("战况那一轮：没拿到本轮历史范围（_hist_range），这次不砍历史")
        return 0
    try:
        a, b = int(rng[0]), int(rng[1])
    except Exception:
        base.log("战况那一轮：历史范围形状不对（%r），这次不砍历史" % (rng,))
        return 0
    if a == b:
        return 0                    # 这一轮本来就没有更早的历史（首条消息），没什么可砍
    if not (0 <= a < b <= len(messages)):
        base.log("战况那一轮：历史范围 %r 越界（消息 %d 条），这次不砍历史"
                 % (rng, len(messages)))
        return 0
    trial = messages[:a] + messages[b:]
    if not _pairing_ok(trial):
        base.log("战况那一轮：砍历史会拼出非法序列（tool 配不上 tool_calls）—— 这次不砍")
        return 0
    cut = b - a
    del messages[a:b]
    # ⚠️ 修：剪完要记一个"已经剪过"的标记，同一轮第二次调 pc_status 时直接跳过。
    #    不记的话第二次还用旧下标 —— 下标已移位 → 会把「快照 + 当前那句」也删掉
    #    （配对仍合法，所以不报错、静默变傻）。
    #    ⛔ 不要动 `ctx["_hist_range"]`：它是拼装器写下的"历史原来在哪"，
    #       自检拿它核对拼装结果，改了会把断言弄红。
    if isinstance(ctx, dict):
        ctx["_hist_trimmed"] = True
    return cut


# ── 一轮：带工具循环 ────────────────────────────────────────────────

# 撞到 max_tokens 上限（`finish_reason == "length"`）时**不结束这一轮**：照 DSH 的做法
# 接着问一次，让她把话说完（见 `run_turn`）。这是**连续**续写的上限 —— 连撞 3 次之后
# 第 4 次就不再续写（避免模型一直撞上限、这一轮无限转下去）。
MAX_LENGTH_CONTINUE = 3


def run_turn(messages, ctx, tools=None, max_rounds=None, conn=None):
    """把「用户这一句」跑到有最终答复为止。**就地**改 `messages`。

    返回 (文本, 这一轮调过的工具名, 错误说明或空串)。

    循环的骨架和 DSH 一样：模型要工具 → 执行 → 结果按 `tool` 消息追加回历史 →
    再问一次，直到它给出可见文本。不同的是这里有**轮次上限**（手机上不能无限转），
    用完最后一轮就把工具目录摘掉，逼它用嘴说 —— 摘掉工具目录之后它不会再要工具。

    ⚠️ 撞到 max_tokens（finish_reason == "length"）**不算结束**：照 DSH 的做法继续问，
       半截文本攒起来接着往下说（不占工具轮次）；连续撞 `MAX_LENGTH_CONTINUE` 次之后
       第 `MAX_LENGTH_CONTINUE + 1` 次收手，把已经写出来的拼起来返回。
    """
    conn = conn or connection()
    called = []
    rounds = int(max_rounds if max_rounds is not None
                 else settings.get("llm.maxToolRounds"))
    tool_rounds = 0
    # ⚠️ 撞到 max_tokens 上限时**不结束**（照 DSH：max-tokens 不算这一轮的结束状态）：
    #    半截文本先攒在 `_acc` 里，接着问一次让她往下说，最后拼成一句返回。
    #    `_len_streak` = **连续**撞了几次 length（只在正常拿到完整回复时清零）；
    #    ⛔ 续写**一个工具轮次都不占**（`tool_rounds` 只在真调工具时加）。
    _acc = []
    _len_streak = 0
    _warned_rounds = False        # 轮次快用完那条提醒，一轮只塞一次
    # 同一轮里「同工具 + 同参数」出现了几次（A4：第 3 次提醒一句，只提醒不禁止）。
    # 键 = (工具名, 规范化参数 JSON)；值 = 到这一批为止的次数。
    _call_seen = {}
    while True:
        # ⚠️ （`end_turn`）：每一步都**现算**一次目录（传 ctx）——
        #    `say` 之后 `ctx["_sends"]` 变了，**下一步**才会多出收尾工具；
        #    触发词 / 随机接话 / 唤醒也按住 `ctx["_trigger"]` 现算。
        give_tools = (toolkit.schemas(ctx)
                      if (tools is None and tool_rounds < rounds) else tools)
        try:
            msg = chat(messages, tools=give_tools, conn=conn)
        except LlmError as e:
            return "", called, str(e)
        assistant = _clean_assistant(msg, msg.get("_model") or conn["model"])
        usage = msg.get("_usage") or {}
        if usage:
            base.log("模型：%s ｜ 输入 %s + 输出 %s token（思考 %s）%s"
                     % (msg.get("_model"), usage.get("prompt_tokens"), usage.get("completion_tokens"),
                        (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0),
                        " ｜ 缓存命中 %s" % usage.get("prompt_cache_hit_tokens")
                        if usage.get("prompt_cache_hit_tokens") else ""))
        # ⚠️ 撞到输出上限时，tool_calls 可能是**半截 JSON** —— 整块丢掉、一个都不执行。
        #    DSH 的组装器也是这么处理的（finish=length 时丢弃 tool-call 块），
        #    不丢的话我们会拿着半截参数去调工具，那比不答还糟。
        # ⚠️ 但 **length 不算这一轮结束**（DSH：`max-tokens` 不覆盖结束状态）：
        #    半截文本照旧追加进历史，然后**接着问一次**让她把话说完。
        if (msg.get("_finish") or "") == "length":
            base.log("这次撞到了 max_tokens 上限，半截的工具调用一个都不执行")
            assistant.pop("tool_calls", None)
            _len_streak += 1
            # 原样攒（模型自己写的空白不删、我们也不加分隔符）；外层最后统一 strip。
            _acc.append(assistant.get("content") or "")
            messages.append(assistant)
            if _len_streak > MAX_LENGTH_CONTINUE:
                # 安全阀：连续撞太多次就别再续了，免得这一轮无限转。
                base.log("连续 %d 次撞到 max_tokens 上限，第 %d 次不再续写，"
                         "把已经写出来的直接返回" % (_len_streak, _len_streak))
                return "".join(_acc).strip(), called, ""
            # ⚠️ 这次继续**不占工具轮次**（`tool_rounds` 一个都不加）。
            base.log("第 %d 次续写：接着往下问，让她把话说完" % _len_streak)
            continue
        # 正常拿到一条完整回复 → 连续 length 的计数清零。
        _len_streak = 0
        tcs = assistant.get("tool_calls") or []
        if not tcs:
            # 撞过 length 的那几段半截文本**连续**拼在最前面（不插空格、不插换行）。
            return ("".join(_acc) + (assistant.get("content") or "")).strip(), called, ""
        messages.append(assistant)
        tool_rounds += 1
        names = [((tc.get("function") or {}).get("name") or "") for tc in tcs]
        _repeats = []
        for tc in tcs:
            fn = tc["function"]
            name = fn.get("name") or ""
            try:
                args = json.loads(fn.get("arguments") or "{}")
                if not isinstance(args, dict):
                    args = {}
            except Exception as e:
                args = {}
                base.log("工具参数不是合法 JSON（%s）：%s" % (e, str(fn.get("arguments"))[:120]))
            t0 = time.time()
            res = toolkit.call(name, args, ctx)
            called.append(name)
            base.log("调工具 %s（%s）→ %s ｜ %.1f 秒"
                     % (name, json.dumps(args, ensure_ascii=False)[:150],
                        json.dumps(res, ensure_ascii=False)[:150], time.time() - t0))
            messages.append({"role": "tool", "tool_call_id": tc["id"],
                             "content": toolkit.result_text(name, res)})
            # ── A4 重复调用检测────────────────────────────
            # 同一轮里「同工具 + 同参数」第 3 次出现 → 往消息里塞一条提醒。
            # ⚠️ 必须是**这一批 tool 消息之后**追加一条 `user`：插在 tool 之间会破坏
            #    tool_calls ↔ tool 的配对，DeepSeek 直接 400（原文见文件头）。
            # ⚠️ 只在第 3 次那一下塞一条；不禁止、不拦调用 —— 决定权还在她手里。
            try:
                _sig = (name, json.dumps(args, ensure_ascii=False, sort_keys=True,
                                         separators=(",", ":")))
            except Exception:
                _sig = (name, repr(args))
            _n = _call_seen.get(_sig, 0) + 1
            _call_seen[_sig] = _n
            if _n == 3:
                _repeats.append((name, _n))
        # ⭐ （`end_turn`）：这一批工具里她调了收尾工具 → **立刻结束这一轮**：
        #    不再请求模型、不再发任何字（这一批里 `say` 已经发出去的话照旧）。
        #    ⚠️ 她这条 assistant 消息里可能还写了文字（和 tool_calls 同一批）——
        #       按用户定的口径**不发**，只在日志里留一笔。
        if isinstance(ctx, dict) and ctx.get("_end_turn"):
            _tail = (assistant.get("content") or "").strip()
            base.log("她调了 end_turn：这一轮到此为止，不再请求模型（%s）"
                     % (("这条消息里她还写了：「%s」——不发" % _tail[:120]) if _tail
                        else "这条消息里没写别的字"))
            return "", called, ""
        # ⭐ 战况那条路：**续问（第 2 次请求）不再带更早的对话历史** ——
        #    ；只在"这一轮调的工具全是 pc_status"时生效，
        #    别的工具（memory / search / …）照旧，理由与切法见上面 `PC_TRIM_TOOLS` 那段。
        _cut = _trim_history_after_tool(messages, names, ctx)
        if _cut:
            base.log("战况那一轮：续问不带更早的对话历史了（砍掉 %d 条）" % _cut)
        for _rn, _rc in _repeats:
            base.log("同一个工具 + 同一组参数第 %d 次出现（%s），塞一句提醒" % (_rc, _rn))
            # ⚠️ 这句是定稿的—— 结尾**没有句号**，
            #    别顺手补一个（A4 第一版就多了一个「。」，跟批准的那份对不上）。
            messages.append({"role": "user", "content": guards.system_reminder(
                "同一个工具（%s）、同一组参数，这一轮你已经调了 %d 次了，结果不会变。"
                "换个参数，或者就用现在手里的东西把话说出来"
                % (_rn, _rc))})
        # ⭐ （用户定）：轮次快用完时先提醒一次，用完了再塞一句【事实】收尾。
        #    ⛔ 不写"别钻牛角尖"这类禁令 —— 只告诉她还剩多少、现在该干什么。
        if tool_rounds >= rounds - max(1, rounds // 10) and not _warned_rounds:
            _warned_rounds = True
            messages.append({"role": "user", "content": guards.system_reminder(
                "工具次数快用完了（还剩 %d 次）：用手上的资料回答。" % (rounds - tool_rounds))})
        if tool_rounds >= rounds:
            # 轮次用完了：先塞一句事实，再摘掉工具，逼它说人话（调过的事实还在历史里）
            messages.append({"role": "user", "content": guards.system_reminder(
                "工具次数用完了：现在用手上的资料回答。")})
            try:
                msg = chat(messages, tools=None, conn=conn)
            except LlmError as e:
                return "", called, str(e)
            assistant = _clean_assistant(msg, msg.get("_model") or conn["model"])
            base.log("工具轮次用完了，摘掉工具目录让她直接说")
            # 前面续写攒下的半截文本照样要带上 —— 哪怕最后这一步是"轮次用完"逼出来的。
            return ("".join(_acc) + (assistant.get("content") or "")).strip(), called, ""


# 「测试当前这家」这次请求的 token 预算。**不能小**：思考模式下，思考本身也吃
# max_tokens —— 原来给的 20 个 token 全被思考吃掉（实测 4.4 秒、finish_reason=length、
# content 空），面板却报「能用」，是个**假绿灯**。2000 够它想完再答一个字，
# 又远小于 config 里正常回复的 4000（测试不该比正常回复还贵）。
PROBE_MAX_TOKENS = 2000


# ── 后台那些「轻量请求」──────────────────
#
# 谁在用：**memory-keeper**（每记一条事实就跑一次）和**私聊自动压缩**（B3）。
# 这两件事都只需要模型"按规矩吐一句话"，⛔ 不带她的性格、⛔ 不给她工具目录。
#
# 配在哪：`llm-apis.txt` 的 `utility`（面板「后台模型」那张卡）：
#     {"inherit": true, "provider": "", "model": "", "effort": "low"}
#   · `inherit: true`（默认）= 跟主模型那套一模一样；
#   · `inherit: false` = 用下面三个覆盖（留空 = 那项跟主模型走）。
#
# ⚠️ 出错一律往上抛 `LlmError`，由调用方自己"降级 + 记日志"—— 绝不在这里吞掉。

UTILITY_MAX_TOKENS = 800


def utility_conn():
    """后台轻量请求用的连接参数（管家 / 私聊压缩）。

    起读 `llm-apis.txt` 的 `utility`
      · `inherit: true`（默认）= 跟主模型那套一样；
      · `inherit: false` = 用 `provider` / `model` / `effort` 这三个覆盖。
    ⚠️ 主配置把思考整个关了（`llm.thinking: disabled`）时，后台也不许偷偷开回来。
    """
    d = apis_doc()
    u = d["utility"]
    act = d["active"]
    if u.get("inherit", True):
        effort, effort_from = effort_now(d)
        conn = _conn_for(d, act.get("provider"), act.get("model"), effort, effort_from)
    else:
        pid = u.get("provider") or act.get("provider")
        mid = _s(u.get("model"))
        if not mid:
            # 「模型」留空 = 跟主模型；但如果后台单独选了另一家，那家用它目录里的第一个。
            p = _find_provider(d, pid)
            if u.get("provider") and p and (p.get("models") or []):
                mid = p["models"][0]["id"]
            else:
                mid = act.get("model")
        effort = _s(u.get("effort")).lower() or "low"
        conn = _conn_for(d, pid, mid, effort, "llm.utility")
    if str((base.cfg().get("llm") or {}).get("thinking") or "").strip().lower() == "disabled":
        effort = "off"
    conn["effort"] = effort
    conn["effort_from"] = "llm.utility"
    conn["thinking"] = "disabled" if effort == "off" else "enabled"
    return conn


def utility_text(messages, max_tokens=None):
    """后台轻量请求：**只要正文**（不带工具）。失败抛 `LlmError`。"""
    conn = utility_conn()
    msg = chat(messages, tools=None, conn=conn,
               max_tokens=int(max_tokens or UTILITY_MAX_TOKENS))
    return (msg.get("content") or "").strip()


def test_provider():
    """「测试当前这家」：发一句最小请求，看 key 和模型通不通。

    ⚠️ 这里**只改 token 预算和判定**，请求里那句用户文本一个字都不动
       （「回一个字：好」是 LLM 文本，要改得先问用户）。
    """
    try:
        conn = connection()
        budget = max(int(conn.get("maxTokens") or 0), PROBE_MAX_TOKENS)
        msg = chat([{"role": "user", "content": "回一个字：好"}],
                   tools=None, conn=conn, max_tokens=budget)
        txt = (msg.get("content") or "").strip()
        finish = msg.get("_finish") or ""
        if not txt:
            # 空 content **不算能用**：要么 token 全被思考吃了、要么这家真的没话说。
            # （真机上就是这么个假绿灯：thinking 把 20 个 token 吃光 → finish=length、content 空）
            return False, ("不通：%s 回了空内容（finish_reason=%s，token 预算 %d）—— "
                           "这家现在答不出东西，别用它"
                           % (msg.get("_model") or conn["model"], finish or "空", budget))
        if finish == "length":
            # 有内容但被截断：模型是活的、key 是通的，只是预算刚好卡在边界
            return True, ("能用（但这次被 token 上限截断了）：%s 回了「%s」"
                          % (msg.get("_model") or conn["model"], txt[:20]))
        return True, "能用：%s 回了「%s」" % (msg.get("_model") or conn["model"], txt[:20])
    except LlmError as e:
        return False, "不通：%s" % str(e)[:200]


def stats():
    conn = connection()
    return {"provider": conn["name"], "model": conn["model"],
            "key": mask(conn["key"]), "thinking": conn["thinking"],
            "effort": conn["effort"], "effort_from": conn.get("effort_from"),
            "timeout": conn["timeout"]}
