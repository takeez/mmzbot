#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""扩展包（**知识锁**）：发现 / 校验 / 加载 / 解锁 / 一键安装。

格式规范见 `docs/capability-format.md`（v1）—— 这一份是**按那份规范实现的唯一一处**：
安装（`--install-capability` / 面板「扩展」页）和运行时加载（每一轮现扫）走的是
**同一个** `validate()`，⛔ 不许另写一套。

═══ 一个包是什么 ═══

    capabilities/<包名>/
        SKILL.md          必需：frontmatter（name / description / version / tools /
                          formatVersion）+ 正文（读技能时原样给她）
        tool.py           可选：带工具（NAME/DESC/PARAMS/run，或 TOOLS 列表）
        config.json       可选（这一份不读，留给包自己）
        assets/           可选

两个地方都认：

    <数据目录>/capabilities/*/     用户装上去的（面板 / CLI 写这里，deploy 不覆盖）
    仓库自带的 capabilities/*/     跟着代码走（`pack-manager`；`_` 开头的是模板，跳过）

同名时**数据目录那份优先**（用户装的覆盖自带的）。两处指向同一个物理目录时
（就地部署 / 本地开发）只扫一遍。

═══ 知识锁（会话级） ═══

平时：技能目录里只有一行「- 名字：一句话」，**工具 schema 不发**。
她调 `skill(name)` 读正文 → 这个包声明的工具 schema **追加**到本轮及后续请求的
tools 末尾（不重排已有工具）；同时最多 6 个包，超了摘最久没用的（`_skills_opened`
里的记录保留，只是不发了）。一场对话结束 / 换会话 → 清空。

`ctx["_skills_opened"]` 是**这场对话**已读技能的有序列表（最新在末尾）。它由这里
按会话 key 保管，ctx 上挂的是**同一个 list 对象** —— 所以一轮一个新 ctx 也接得上。

═══ 校验（docs §6 六条；安装与加载共用） ═══

    ① 包名合法、SKILL.md 存在、frontmatter 有 name + description
    ② name 与文件夹名一致；description ≤ 60 字
    ③ tool.py 能被 import，且 NAME/DESC/PARAMS/run 齐全、类型对
    ④ 工具名不撞主程序内置、不撞已装包的别的工具
    ⑤ PARAMS 是合法 JSON Schema（type/properties/required 至少齐全）
    ⑥ 不出现 eval/exec/os.system（**只警告不拒**）

校验不过：这个包**跳过**（`list()` 里仍然看得见，状态写明第几条）+ 日志一行；
不影响别的包，不炸启动。

⚠️ 这个模块**不在 import 时扫盘 / import 任何包**：`toolkit` 顶部就 import 它，
   而包的 tool.py 又会（合法地）import `fgbot` 的东西 —— 两边一旦在 import 期互相
   等，启动就会卡住。所有扫描都推迟到函数调用里。
"""

import base64
import builtins
import hashlib
import ast
import importlib.util
import json
import os
import re
import secrets
import shutil
import sys
import tempfile
import threading
import time
import types
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from . import base, guards, store

# ── 常量 ────────────────────────────────────────────────────────────

# 同时最多解锁几个**包**的 schema（超了摘最久没用的，见 docs §4）
MAX_UNLOCKED = 6
# 工具调用上限（秒）；包可以用 `TIMEOUT = 60` 覆盖
DEFAULT_TIMEOUT = 20
# 描述上限（字）
MAX_DESC = 60
# 停用名单 / 状态文件（**不进仓库**，deploy 也不覆盖）
STATE_NAME = "capabilities-state.json"
# SKILL.md 里认得的格式版本（不认识的更高版本 → 不加载，让她去升级主程序）
FORMAT_VERSION = 1

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
# 工具名：模型那边能稳定填的形状（英文 / 数字 / 下划线，不能以数字开头）
TOOL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
# `- 名字：description` 里的那个冒号是**全角**的（用户 2026-10-31 逐字批的）
CATALOG_HEAD = "【技能目录】：你的额外技能，用skill工具读取"
CATALOG_LINE = "- %s：%s"

# 六条规则的一句话人话（面板 / CLI 报错时带编号用）
RULES = {
    1: "包名合法、SKILL.md 存在、frontmatter 有 name + description",
    2: "name 与文件夹名一致、description 不超过 %d 字" % MAX_DESC,
    3: "tool.py 能被 import，且 NAME/DESC/PARAMS/run 齐全、类型对",
    4: "工具名不撞主程序内置工具、不撞已装包的别的工具",
    5: "PARAMS 是合法 JSON Schema（type/properties/required 都在）",
    6: "tool.py 里不出现 eval/exec/os.system（只警告，不拒）",
}

# ⑥ 只看这三样（docs 点名的那几个；别的"危险"写法不在这儿做道德审查）
_DANGER = (
    (re.compile(r"(?<![\w.$])eval\s*\("), "eval("),
    (re.compile(r"(?<![\w.$])exec\s*\("), "exec("),
    (re.compile(r"\bos\s*\.\s*system\s*\("), "os.system("),
)

_LOCK = threading.RLock()
_CACHE = {}          # 包目录绝对路径 -> Cap（按 mtime 复用；变了就重新 import）
_LOGGED_BAD = {}     # 包目录绝对路径 -> (签名, 第几条)：同一个坏包只写一行日志
_STATE = {}          # 会话 key -> {"opened": [...], "msg": {...}|None, "sig": tuple|None}


# ── 小工具 ──────────────────────────────────────────────────────────

def data_root():
    """用户装的包放哪：`<数据目录>/capabilities`。

    ⚠️ 走 `store.path()`（不是 `base.data_path()`）：自检一开始就把 store 指到临时
       目录，这样自检里装的包**绝不可能**落在正式目录里。
    """
    return store.path("capabilities")


def builtin_root():
    """仓库自带的包放哪（跟着代码走，只读；`capabilities/pack-manager/` 就是它）。

    ⚠️ 2026-10-31（示例外置化）：`pc-status` 搬去了 `examples/packages/`，不再在这儿；
        `capabilities/` 下 `_` 开头的（`_template`）加载器直接跳过。
    """
    return os.path.join(base.CODE_DIR, "capabilities")


def _one_line(s):
    """描述在目录里必须是一行（换行会破坏「每行一个」的形状）。"""
    return " ".join(str(s or "").split())


def _clip_desc(s):
    """目录里那行兜底截到 60 字（正常包在 ② 就拦住了，这里只是防御）。"""
    s = _one_line(s)
    return s[:MAX_DESC]


def _text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except Exception:
        return None


def _is_file(p):
    try:
        return os.path.isfile(p)
    except Exception:
        return False


def _mtime(p):
    try:
        return os.stat(p).st_mtime_ns
    except Exception:
        return 0


def _sig(path):
    """一个包的"版本指纹"（SKILL.md / tool.py / config.json 的 mtime + 大小）。

    ⚠️ 按 mtime 重载（用户要的「改文件下一轮生效」）：指纹变了就重新解析 + 重新
       import。也顺手带上大小 —— 有的文件系统 mtime 精度只有秒，同秒内改两次
       长度不同时也能认出来。
    """
    out = []
    for n in ("SKILL.md", "tool.py", "config.json"):
        p = os.path.join(path, n)
        try:
            st = os.stat(p)
            out.append((n, st.st_mtime_ns, st.st_size))
        except Exception:
            out.append((n, 0, 0))
    return tuple(out)


# ── SKILL.md：frontmatter + 正文 ────────────────────────────────────

# 认得的键（"尽量宽松但也别乱认"：英文为主，顺手认几个中文别名）
_KEYS = {
    "name": "name", "名称": "name", "技能名": "name",
    "description": "description", "说明": "description", "描述": "description",
    "version": "version", "版本": "version",
    "tools": "tools", "工具": "tools", "工具名": "tools",
    "formatversion": "formatversion", "format_version": "formatversion",
    "格式版本": "formatversion",
}


def parse_skill(text):
    """SKILL.md 原文 → `(元信息 dict 或 None, 正文)`。

    frontmatter = **文件第一行就是 `---`**，到下一行 `---`（或 `...`）为止。
    没有/没闭合 → 元信息 `None`（校验第 ① 条会拦）。
    值两边的引号会去掉；`tools` 按逗号 / 顿号拆成列表。
    """
    raw = text or ""
    lines = raw.splitlines(True)
    if not lines or lines[0].strip() != "---":
        return None, raw
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() in ("---", "..."):
            end = i
            break
    if end is None:
        return None, raw
    meta = {}
    for ln in lines[1:end]:
        s = ln.strip()
        if not s or s.startswith("#") or ":" not in s:
            continue
        k, v = s.split(":", 1)
        k = k.strip().lower()
        v = v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        key = _KEYS.get(k)
        if key:
            meta[key] = v
    if "tools" in meta:
        parts = [x.strip() for x in re.split(r"[,，、\s]+", meta["tools"]) if x.strip()]
        meta["tools"] = parts
    return meta, "".join(lines[end + 1:])


def _body_of(text):
    """SKILL.md → 正文（去掉 frontmatter 两头的空行，中间**一个字不动**）。"""
    _meta, body = parse_skill(text)
    return (body or "").strip()


# ── tool.py：import + 取定义 ────────────────────────────────────────

def _static_tool(path):
    """静态读 tool.py：**不 import、不执行**对方任何一行代码。

    ⚠️ 2026-11-02：以前校验第③条就是 `import` 对方的 tool.py —— "校验"这个动作本身
      就在执行别人的代码（装一个包 = RCE 两次）。现在只用 ast 看定义：
      模块级常量（NAME/DESC/PARAMS 等）必须是字面量才认，函数只看名字。
      真正运行时还是要 import（那是用户点了"启用"之后的事）。
    """
    src = _text(path)
    tree = ast.parse(src, filename=path)      # 语法错直接抛 SyntaxError
    ns = types.SimpleNamespace()
    required = ("NAME", "DESC", "PARAMS", "TIMEOUT",
                "name", "desc", "params", "timeout")
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if not isinstance(t, ast.Name):
                    continue
                try:
                    val = ast.literal_eval(node.value)
                except Exception:
                    if t.id in required:
                        raise ValueError("%s 不是字面量（校验时不跑代码）" % t.id)
                    continue          # 别的常量是算出来的也没关系（不在校验口径里）
                setattr(ns, t.id, val)
        elif isinstance(node, ast.FunctionDef):
            if node.name in ("run", "available", "RUN", "AVAILABLE"):
                setattr(ns, node.name, lambda *a, **k: None)
    return ns


def _import_tool(path, name):
    """把 tool.py import 出来。失败原样抛（校验第 ③ 条会把它变成一句人话）。

    ⚠️ 模块名带时间戳：改文件重新载入时**不能**复用旧模块（Python 会拿缓存）。
    ⚠️ 注册进 `sys.modules`：包自己的相对 import / `dataclass` 之类要靠它。
    """
    mod_name = "fgbot_cap_%s_%d" % (re.sub(r"[^A-Za-z0-9_]", "_", str(name or "x")),
                                    int(time.time() * 1000))
    spec = importlib.util.spec_from_file_location(mod_name, path)
    if spec is None or spec.loader is None:
        raise ImportError("不是可 import 的 Python 文件")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        sys.modules.pop(mod_name, None)
        raise
    return mod


def _pick(d, *names):
    """一个工具定义里取字段：`NAME` 和 `name` 两种写法都认（宽松但不猜）。

    `d` 可以是 dict（`TOOLS` 里的一项），也可以是模块（`tool.py` 本身）。
    """
    for n in names:
        if isinstance(d, dict):
            if n in d:
                return d[n]
        elif hasattr(d, n):
            return getattr(d, n)
    return None


def _one_tool(src, where):
    """模块 / TOOLS 里的一项 → 统一形状。返回 `(tool_dict, 错误说明)`。"""
    name = _pick(src, "NAME", "name")
    desc = _pick(src, "DESC", "desc")
    params = _pick(src, "PARAMS", "params")
    run = _pick(src, "run", "RUN")
    avail = _pick(src, "available", "AVAILABLE")
    timeout = _pick(src, "TIMEOUT", "timeout")
    if not isinstance(name, str) or not name.strip():
        return None, "%s：没给 NAME（或不是字符串）" % where
    name = name.strip()
    if not TOOL_RE.match(name):
        return None, "%s：NAME「%s」不合法（英文/数字/下划线，不能以数字开头）" % (where, name)
    if not isinstance(desc, str) or not desc.strip():
        return None, "%s：%s 没给 DESC（或不是非空字符串）" % (where, name)
    if not isinstance(params, dict):
        return None, "%s：%s 的 PARAMS 不是 JSON Schema 对象" % (where, name)
    if not callable(run):
        return None, "%s：%s 的 run 不是函数" % (where, name)
    if avail is not None and not callable(avail):
        return None, "%s：%s 的 available 不是函数" % (where, name)
    try:
        to = int(timeout) if timeout is not None else DEFAULT_TIMEOUT
    except Exception:
        return None, "%s：%s 的 TIMEOUT 不是数字" % (where, name)
    if to <= 0:
        to = DEFAULT_TIMEOUT
    return {"name": name, "desc": desc.strip(), "params": params, "run": run,
            "available": avail, "timeout": to}, ""


def _tools_of(mod):
    """一个 tool.py 模块 → `(工具列表, 错误说明)`（TOOLS 列表 / 单工具两种写法）。"""
    if mod is None:
        return [], ""
    listed = getattr(mod, "TOOLS", None)
    if listed is not None:
        if not isinstance(listed, (builtins.list, tuple)) or not listed:
            return [], "TOOLS 要是非空列表"
        out = []
        for i, item in enumerate(listed, 1):
            if not isinstance(item, dict):
                return [], "TOOLS 第 %d 项不是 dict" % i
            t, why = _one_tool(item, "TOOLS 第 %d 项" % i)
            if t is None:
                return [], why
            out.append(t)
        # 一个包多个工具时，模块级的 available / TIMEOUT 当**默认值**
        # （单项自己写了就用单项的；`_one_tool` 没写 TIMEOUT 时留的是 DEFAULT_TIMEOUT）
        mod_avail = getattr(mod, "available", None)
        try:
            mod_to = int(getattr(mod, "TIMEOUT", DEFAULT_TIMEOUT))
        except Exception:
            mod_to = DEFAULT_TIMEOUT
        if mod_to <= 0:
            mod_to = DEFAULT_TIMEOUT
        for t in out:
            if t["available"] is None and callable(mod_avail):
                t["available"] = mod_avail
            if t["timeout"] == DEFAULT_TIMEOUT:
                t["timeout"] = mod_to
        return out, ""
    if any(hasattr(mod, a) for a in ("NAME", "DESC", "PARAMS", "run")):
        t, why = _one_tool(mod, "tool.py")
        if t is None:
            return [], why
        return [t], ""
    return [], "tool.py 里既没有 NAME/DESC/PARAMS/run，也没有 TOOLS 列表"


# ── 校验（docs §6 六条；**安装和加载共用这一份**）──────────────────

def _reserved_tools():
    """主程序内置的工具名（撞上就违第 ④ 条）。

    ⚠️ 延迟 import `toolkit`：`toolkit` 顶部就 import 本模块，import 期不能反过来。
    """
    try:
        from . import toolkit
        names = set(toolkit.names())
        names.add(toolkit.END_TURN["name"])
        names.add("skill")
        return names
    except Exception:
        return {"skill"}


def _others(exclude=None):
    """已装 / 自带包里**别的包**的工具名：`{包名: [工具名]}`（第 ④ 条用）。"""
    out = {}
    for cap in _ensure():
        if exclude and cap.name == exclude:
            continue
        if not cap.ok:
            continue
        out[cap.name] = [t["name"] for t in cap.tools]
    return out


def validate(root, folder_name=None, other_tools=None):
    """按 docs §6 六条校验一个包目录。**安装与加载共用这一份实现**。

    `root`         包目录（要含 SKILL.md）
    `folder_name`  包名（默认 = 目录名；从"没有外层文件夹的 zip"装时由调用方给）
    `other_tools`  `{别的包名: [工具名]}`；None = 只看内置工具（跨包那一半由
                   加载器在扫完所有包之后补，见 `_ensure`）

    返回 `{"rules": [六条], "meta":…, "body":…, "tools":…, "mod":…, "name":…}`。
    每条规则长这样：`{"rule": 1, "ok": True/False, "warn": False, "message": "..."}`。
    ⛔ 六条**一条都不缺**（面板/CLI 要按编号打印）。
    """
    root = os.path.abspath(str(root or ""))
    folder = str(folder_name or os.path.basename(root) or "").strip()
    rules = [{"rule": i, "ok": True, "warn": False, "message": ""}
             for i in range(1, 7)]

    def fail(i, msg):
        """记一条"不过"。⚠️ 同一条规则只留**第一条**原因（最接近根因的那个），
        不然后面那些"连带的缺字段"会把真正的毛病盖掉（例如没有 SKILL.md
        却报成「frontmatter 里缺 description」）。"""
        if rules[i - 1]["ok"]:
            rules[i - 1]["ok"] = False
            rules[i - 1]["message"] = msg

    def warn(i, msg):
        rules[i - 1]["warn"] = True
        rules[i - 1]["message"] = msg

    info = {"name": folder, "meta": {}, "body": "", "tools": [], "mod": None,
            "root": root}

    # ① 包名 / SKILL.md / frontmatter 的 name + description
    if not NAME_RE.match(folder):
        fail(1, "包名「%s」不合法：只能用小写字母、数字、- 和 _，以字母或数字开头"
                "（最多 64 个字符）" % folder)
    skill = os.path.join(root, "SKILL.md")
    meta = None
    body = ""
    if not _is_file(skill):
        fail(1, "这个文件夹里没有 SKILL.md")
    else:
        meta, body = parse_skill(_text(skill))
        if meta is None:
            fail(1, "SKILL.md 开头要有 frontmatter（第一行 `---`，到下一行 `---` 为止）")
            meta = {}
    meta = meta or {}
    info["meta"] = meta
    info["body"] = (body or "").strip()
    name = str(meta.get("name") or "").strip()
    desc = str(meta.get("description") or "").strip()
    if not name:
        fail(1, "frontmatter 里缺 name")
    else:
        info["name"] = name
    if not desc:
        fail(1, "frontmatter 里缺 description（一句话：这个技能能干什么）")

    # ⑩（不单列编号）formatVersion 比主程序认识的高 → 不加载，让她去升级
    fv = str(meta.get("formatversion") or "").strip()
    if fv:
        try:
            if float(fv) > FORMAT_VERSION:
                fail(1, "这个包要 formatVersion %s，本机主程序只认 %d —— 先更新主程序"
                        % (fv, FORMAT_VERSION))
        except Exception:
            fail(1, "formatVersion「%s」不是数字" % fv)

    # ② name 与文件夹名一致；description ≤ 60 字
    if name and folder and name != folder:
        fail(2, "frontmatter 的 name（%s）和文件夹名（%s）不一致" % (name, folder))
    if desc and len(_one_line(desc)) > MAX_DESC:
        fail(2, "description 有 %d 字，超过 %d 字——删短一点再装"
                % (len(_one_line(desc)), MAX_DESC))

    # ③ tool.py 能被 import + 四件套齐全、类型对
    tool_py = os.path.join(root, "tool.py")
    declared = [str(x).strip() for x in (meta.get("tools") or []) if str(x).strip()]
    tools = []
    mod = None
    if _is_file(tool_py):
        try:
            mod = _static_tool(tool_py)
        except SyntaxError as e:
            fail(3, "tool.py 语法错误（第 %s 行）：%s" % (getattr(e, "lineno", "?"), e.msg))
            mod = None
        except Exception as e:
            fail(3, "tool.py 读不出来：%s: %s" % (type(e).__name__, e))
            mod = None
        else:
            tools, why = _tools_of(mod)
            if not tools:
                fail(3, why or "tool.py 里没取到工具")
        info["mod"] = mod
        info["tools"] = tools
        names = [t["name"] for t in tools]
        if len(set(names)) != len(names):
            dup = sorted({x for x in names if names.count(x) > 1})
            fail(3, "包里的工具名重复：%s" % "、".join(dup))
        if declared and names and set(declared) != set(names):
            fail(3, "frontmatter 的 tools（%s）和 tool.py 里的工具名（%s）不一致"
                    % ("、".join(declared), "、".join(names)))
    elif declared:
        fail(3, "frontmatter 声明了 tools（%s），但没有 tool.py" % "、".join(declared))

    # ④ 工具名不撞内置 / 不撞别的包
    names = [t["name"] for t in tools]
    if names:
        hit = sorted(set(names) & _reserved_tools())
        if hit:
            fail(4, "工具名和主程序内置的撞了：%s（换个名字）" % "、".join(hit))
        for pkg, other in sorted((other_tools or {}).items()):
            bad = sorted(set(names) & set(other))
            if bad:
                fail(4, "工具名和已装包「%s」的撞了：%s（换个名字）"
                        % (pkg, "、".join(bad)))

    # ⑤ PARAMS 是合法 JSON Schema（type/properties/required 至少齐全）
    for t in tools:
        p = t["params"]
        why = ""
        if p.get("type") != "object":
            why = "顶层 type 要是 \"object\""
        elif not isinstance(p.get("properties"), dict):
            why = "缺 properties（没有参数就写 {}）"
        elif not isinstance(p.get("required"), builtins.list):
            why = "缺 required（没有必填就写 []）"
        elif any(not isinstance(x, str) for x in p["required"]):
            why = "required 里只能放参数名字符串"
        elif any(x not in p["properties"] for x in p["required"]):
            why = "required 里有 properties 没定义的参数"
        if why:
            fail(5, "%s 的 PARAMS：%s" % (t["name"], why))

    # ⑥ eval / exec / os.system（**只警告不拒**）
    src = _text(tool_py) if _is_file(tool_py) else ""
    if src:
        hits = [label for rx, label in _DANGER if rx.search(src)]
        if hits:
            warn(6, "tool.py 里出现 %s —— 只警告不拒（装之前自己看一眼）"
                     % " / ".join(hits))

    info["rules"] = rules
    info["ok"] = all(r["ok"] for r in rules)
    info["first_bad"] = next((r for r in rules if not r["ok"]), None)
    info["declared"] = declared
    return info


def rules_text(info):
    """给 CLI / 日志的一行：第一条不过的规则。"""
    bad = info.get("first_bad")
    if not bad:
        return "全部通过"
    return "第 %d 条：%s" % (bad["rule"], bad["message"])


# ── 加载器 ──────────────────────────────────────────────────────────

class Cap(object):
    """一个扩展包（加载后的样子）。"""

    def __init__(self):
        self.name = ""
        self.dir = ""
        self.builtin = False
        self.desc = ""
        self.version = ""
        self.declared = []
        self.tools = []
        self.body = ""
        self.mod = None
        self.rules = []
        self.sig = None
        self.ok = False

    @property
    def has_tools(self):
        return bool(self.tools)

    @property
    def error_rule(self):
        bad = next((r for r in self.rules if not r["ok"]), None)
        return bad["rule"] if bad else 0

    @property
    def error_text(self):
        bad = next((r for r in self.rules if not r["ok"]), None)
        return bad["message"] if bad else ""

    @property
    def status(self):
        """面板 / CLI 那一列（用户 2026-10-31 定的三种）。"""
        if not self.ok:
            return "校验失败：第 %d 条" % self.error_rule
        if self.name in disabled():
            return "已停用"
        return "已加载"

    def clone(self):
        """复制一份（**不共享 list / dict**）。

        ⚠️ 为什么要有它：跨包的重名（第 ④ 条）是在 `_ensure()` 里判的，
           ⛔ 绝不能直接改缓存里那个对象 —— 改了会"粘住"：另一个包被删掉以后，
           这个包还一直是坏的状态（要等它自己的文件 mtime 变了才恢复）。
        """
        c = Cap()
        for k in ("name", "dir", "builtin", "desc", "version", "body", "mod",
                  "sig", "ok"):
            setattr(c, k, getattr(self, k))
        c.declared = builtins.list(self.declared)
        c.tools = builtins.list(self.tools)
        c.rules = [dict(r) for r in self.rules]
        return c


def _is_builtin_dir(path):
    """这个目录是不是**仓库自带的**那份（跟着代码走，删不得）。

    ⚠️ 就地部署时数据目录 == 代码目录（`_root_specs` 只扫一遍，`builtin` 标不出来）——
       所以这里按**真实路径**再判一次：在 `capabilities/` 下面的一律算自带，
       `remove()` 拒绝、面板也不给卸载按钮。不然 `pack-manager` 会被自己删掉。
    """
    try:
        root = os.path.normcase(os.path.realpath(builtin_root()))
        p = os.path.normcase(os.path.realpath(str(path or "")))
        return bool(p) and (p == root or p.startswith(root + os.sep))
    except Exception:
        return False


def _root_specs():
    """`[(目录, 是否内置)]`：数据目录优先；两个路径其实是同一个目录时只算一次。"""
    out, seen = [], set()
    for p, builtin in ((data_root(), False), (builtin_root(), True)):
        ap = os.path.abspath(p)
        key = os.path.normcase(os.path.realpath(ap))
        if key in seen:
            continue
        seen.add(key)
        out.append((ap, builtin))
    return out


def _candidates():
    """扫两个根目录 → `[(包目录, 是否内置, 包名)]`（同名时数据目录那份优先）。

    ⚠️ 跳过 `*.bak-*`（安装前的备份，不是包）和隐藏目录（`.git` 之类）。
    """
    out, taken = [], set()
    for root, builtin in _root_specs():
        try:
            names = sorted(os.listdir(root))
        except Exception:
            continue
        for n in names:
            if n.startswith(".") or n.startswith("_") or ".bak-" in n:
                # `_` 开头 = 模板 / 草稿（`capabilities/_template`）：**不是包**，连面板都不列。
                continue
            p = os.path.join(root, n)
            if not os.path.isdir(p):
                continue
            if n in taken:
                continue
            taken.add(n)
            out.append((p, builtin, n))
    return out


def _load_dir(path, builtin=False, folder_name=None):
    """把一个包目录读成 `Cap`（按 mtime 缓存；变了就重新 import）。

    ⚠️ 校验不过**不抛**：把规则结果留在 `cap.rules` 里，由调用方跳过它。
    ⚠️ 日志只写**一行**，而且同一个坏包（同样指纹）**只写一次** —— 每一轮都会扫，
       不这样的话日志会被一个坏包刷满。
    """
    path = os.path.abspath(path)
    folder = folder_name or os.path.basename(path)
    sig = _sig(path)
    with _LOCK:
        hit = _CACHE.get(path)
        if hit is not None and hit.sig == sig:
            return hit
    info = validate(path, folder_name=folder)
    cap = Cap()
    cap.dir = path
    # 就地部署时两个根是同一个目录（扫描时只算一次），靠路径再认一次"是不是仓库自带的"
    cap.builtin = bool(builtin) or _is_builtin_dir(path)
    cap.sig = sig
    cap.rules = info["rules"]
    cap.ok = info["ok"]
    cap.name = str(info["meta"].get("name") or folder)
    cap.desc = _one_line(info["meta"].get("description"))
    cap.version = _one_line(info["meta"].get("version"))
    cap.declared = builtins.list(info.get("declared") or [])
    cap.tools = builtins.list(info.get("tools") or [])
    cap.body = info.get("body") or ""
    # ⚠️ 校验是静态的（不执行对方代码）；**真正加载**才 import —— 这是运行时，
    #    用户已经点过"装"了，行为要和以前一致（工具函数得是真函数）。
    cap.mod = info.get("mod")
    if cap.ok:
        tool_py = os.path.join(path, "tool.py")
        if os.path.isfile(tool_py):
            try:
                cap.mod = _import_tool(tool_py, folder)
                # 工具定义（含 run 函数）以**真正 import 出来的模块**为准：
                # 校验用的是静态快照，里面的 run 只是个占位。
                real_tools, _why = _tools_of(cap.mod)
                if real_tools:
                    cap.tools = real_tools
            except Exception as e:
                cap.ok = False
                base.log("扩展包 %s 载入失败：%s: %s" % (folder, type(e).__name__, e))
        else:
            cap.mod = None
    with _LOCK:
        _CACHE[path] = cap
        prev = _LOGGED_BAD.get(path)
        if not cap.ok:
            if prev != (sig, cap.error_rule):
                _LOGGED_BAD[path] = (sig, cap.error_rule)
                base.log("扩展包 %s 跳过（第 %d 条）：%s"
                         % (folder, cap.error_rule, cap.error_text))
            # 坏包也要能让面板看见 —— 名字用文件夹名（frontmatter 可能都没读出来）
            cap.name = folder
        else:
            if prev is not None:
                _LOGGED_BAD.pop(path, None)
            if hit is not None:
                base.log("扩展包 %s 重新载入（文件改过了）" % folder)
    return cap


def _ensure():
    """现在有哪些包（按名字排序；数据目录优先、自带在后）。

    ⚠️ 每一轮都会调它（`schemas()` 每步现算）—— 只 stat，不 import；真正的
       import 只在 mtime 变了的时候发生一次（`_load_dir` 的缓存）。
    """
    caps = []
    for path, builtin, name in _candidates():
        try:
            cap = _load_dir(path, builtin, name)
        except Exception:
            base.log_exc("扩展包 %s 读不出来" % name)
            continue
        caps.append(cap)
    # ④ 的跨包那一半：同一个工具名被两个包声明 → 后面的那个算第 ④ 条不过
    #    ⚠️ 改的是**副本**（`clone()`）：直接改缓存对象会让这条失败"粘住"。
    owner = {}
    for i, cap in enumerate(caps):
        if not cap.ok:
            continue
        dup = []
        for t in cap.tools:
            other = owner.get(t["name"])
            if other is not None and other != cap.name:
                dup.append((t["name"], other))
            else:
                owner.setdefault(t["name"], cap.name)
        if dup:
            c = cap.clone()
            c.ok = False
            c.rules[3]["ok"] = False
            c.rules[3]["message"] = "工具名和已装包「%s」的撞了：%s" % (
                dup[0][1], "、".join(x for x, _y in dup))
            c.tools = []
            caps[i] = c
    caps.sort(key=lambda c: (c.name, 0 if not c.builtin else 1))
    return caps


def reload_all():
    """把缓存全丢掉，下一次扫描重新读（安装/卸载/自检用）。"""
    with _LOCK:
        _CACHE.clear()
        _LOGGED_BAD.clear()


def list():
    """面板 / CLI 用：一行一个包（含校验失败的、已停用的）。"""
    out = []
    for cap in _ensure():
        out.append({
            "name": cap.name,
            "description": cap.desc,
            "version": cap.version,
            "has_tools": cap.has_tools,
            "tools": [t["name"] for t in cap.tools],
            "enabled": cap.name not in disabled(),
            "loaded": cap.ok,
            "status": cap.status,
            "error_rule": cap.error_rule,
            "error": cap.error_text,
            "builtin": cap.builtin,
            "dir": cap.dir,
            "can_remove": (not cap.builtin) and not _is_builtin_dir(cap.dir),
            "rules": cap.rules,
        })
    return out


def get(name):
    """按名字取一个包（**校验通过**的那个；停用的也返回，由调用方看 `enabled`）。"""
    n = str(name or "").strip()
    if not n:
        return None
    for cap in _ensure():
        if cap.name == n and cap.ok:
            return cap
    return None


def tools_for(cap):
    """一个包声明的工具 → OpenAI function 格式的 schema 列表（完整复制一份）。

    ⚠️ 复制：调用方拿到的是"给请求用的那份"，⛔ 不能让谁改了 PARAMS 把包里的
       定义也改掉（下一轮就跟着变）。
    """
    out = []
    for t in (cap.tools if isinstance(cap, Cap) else []):
        out.append({"type": "function",
                    "function": {"name": t["name"],
                                 "description": t["desc"],
                                 "parameters": _json_copy(t["params"])}})
    return out


def _json_copy(obj):
    import json
    try:
        return json.loads(json.dumps(obj, ensure_ascii=False))
    except Exception:
        return {} if not isinstance(obj, dict) else dict(obj)


def _tool_available(t, ctx):
    """这个工具现在该不该出现在目录里（包的 `available(ctx)`；抛异常 = 不可见）。"""
    fn = t.get("available")
    if fn is None:
        return True
    try:
        return bool(fn(ctx))
    except Exception:
        base.log_exc("扩展包 %s 的 available()" % t.get("name"))
        return False


# ── 停用名单（state 文件）──────────────────────────────────────────

def disabled():
    """停用的包名（`capabilities-state.json` 的 `disabled`）。"""
    d = store.read_json(STATE_NAME, default={}) or {}
    raw = d.get("disabled") if isinstance(d, dict) else None
    if not isinstance(raw, (builtins.list, tuple)):
        return set()
    return {str(x) for x in raw if str(x)}


def set_enabled(name, on):
    """启用 / 停用（写 state 文件；下一轮就生效）。返回 `(ok, message)`。"""
    n = str(name or "").strip()
    if not NAME_RE.match(n):
        return False, "名字不合法：%r" % (name,)
    cur = disabled()
    if on:
        if n not in cur:
            return True, "「%s」本来就是启用的" % n
        cur.discard(n)
        msg = "已启用「%s」" % n
    else:
        if n in cur:
            return True, "「%s」本来就停着" % n
        cur.add(n)
        msg = "已停用「%s」（目录行消失、工具也解锁不了）" % n
    ok = store.write_json(STATE_NAME, {"disabled": sorted(cur)})
    if ok:
        base.log("扩展：%s" % msg)
    return ok, (msg if ok else "状态文件写不进去")


# ── 会话级解锁（知识锁）────────────────────────────────────────────

def _session_state(ctx):
    """这个 ctx 所属会话的状态（`{"opened": [...], "msg": …, "sig": …}`）。

    ⚠️ 有 `ctx["key"]`（真会话）→ 按 key 存在模块里，**跨轮次**接得上；
       没有 key（自检里随手造的 ctx）→ 挂在 ctx 自己身上，不污染会话表。
    """
    if not isinstance(ctx, dict):
        return {"opened": [], "msg": None, "sig": None}
    key = ctx.get("key")
    try:
        hash(key)
    except Exception:
        key = None
    if key is None:
        st = ctx.get("_cap_state")
        if not isinstance(st, dict):
            st = {"opened": [], "msg": None, "sig": None}
            ctx["_cap_state"] = st
        return st
    with _LOCK:
        st = _STATE.get(key)
        if st is None:
            st = _STATE[key] = {"opened": [], "msg": None, "sig": None}
        return st


def opened(ctx):
    """本场对话已读的技能名（有序，最新在末尾）—— **ctx 里就是它这一份 list**。"""
    st = _session_state(ctx)
    lst = st.setdefault("opened", [])
    if isinstance(ctx, dict) and ctx.get("_skills_opened") is not lst:
        ctx["_skills_opened"] = lst
    return lst


def mark_opened(ctx, name):
    """记下"读过这个技能"：已经有的先摘掉再放到末尾（= 最近用过）。"""
    lst = opened(ctx)
    n = str(name or "").strip()
    with _LOCK:
        while n in lst:
            lst.remove(n)
        lst.append(n)
    return lst


def unlocked(ctx):
    """现在**真的会发 schema** 的包名：`_skills_opened` 末尾那几个（上限 6）。"""
    lst = opened(ctx)
    return builtins.list(lst[-MAX_UNLOCKED:])


def clear_sessions(key=None):
    """一场对话结束 / 换会话 → 清空（面板「重置对话」走 `memory.reset()` 到这儿）。"""
    with _LOCK:
        if key is None:
            _STATE.clear()
        else:
            try:
                _STATE.pop(key, None)
            except Exception:
                pass


def tool_schemas(ctx):
    """解锁了、并且**现在可用**的工具 schema（追加到 tools 末尾用）。

    ⚠️ 每步现算（`toolkit.schemas(ctx)` 每步都调）：心跳刚到的那一步就能出现；
       包被停用 / 删掉时，已解锁的也立刻不发。
    """
    out = []
    off = disabled()
    for name in unlocked(ctx):
        if name in off:
            continue
        cap = get(name)
        if cap is None or not cap.ok:
            continue
        for t in cap.tools:
            if not _tool_available(t, ctx):
                continue
            out.append({"type": "function",
                        "function": {"name": t["name"],
                                     "description": t["desc"],
                                     "parameters": _json_copy(t["params"])}})
    return out


def note_tool_list(ctx, names):
    """工具列表变了就记一行日志（排查缓存问题时有用）。

    `names` = 这一步真正发出去的工具名（有序）。同一个会话里跟上一轮比，
    不一样才写 —— 新会话第一次不写（没有"变化"这回事）。
    """
    try:
        st = _session_state(ctx)
        sig = tuple(names or ())
        prev = st.get("sig")
        st["sig"] = sig
        if prev is not None and prev != sig:
            base.log("工具列表变了：%d 个 → %d 个（%s）"
                     % (len(prev), len(sig),
                        "、".join(sig) if sig else "（空）"))
    except Exception:
        pass


# ── 技能目录（一条独立的 user 消息）────────────────────────────────

def catalog_text():
    """技能目录的正文（**没有可用技能时返回空串**）。

    逐字形状（用户 2026-10-31 批的）：

        <system-reminder>
        【技能目录】：你的额外技能，用skill工具读取

        - 名字：description
        </system-reminder>

    每行一个、**按名字排序**；信封走 `guards.system_reminder()`（和别处同一个）。
    """
    off = disabled()
    rows = [c for c in _ensure() if c.ok and c.name not in off]
    if not rows:
        return ""
    rows.sort(key=lambda c: c.name)
    body = CATALOG_HEAD + "\n\n" + "\n".join(
        CATALOG_LINE % (c.name, _clip_desc(c.desc)) for c in rows)
    return guards.system_reminder(body)


def catalog_message(ctx):
    """这一轮要发的那条**独立的 user 消息**；没有技能可用 → `None`。

    ⚠️ 「内容变了就**原地替换那一条**，不要每轮追加」：按会话缓存**同一个 dict**，
       内容变了只改 `content`。拼装器每一轮把它放在 system 之后、历史之前 ——
       所以请求里永远只有这一条（不会一轮多一条）。
    """
    text = catalog_text()
    if not text:
        return None
    st = _session_state(ctx)
    # 顺手把 `_skills_opened` 挂到 ctx 上（同一个 list；这一轮还没解锁时就是空表）
    lst = st.setdefault("opened", [])
    if isinstance(ctx, dict) and ctx.get("_skills_opened") is not lst:
        ctx["_skills_opened"] = lst
    msg = st.get("msg")
    if not isinstance(msg, dict):
        msg = st["msg"] = {"role": "user", "content": text}
    elif msg.get("content") != text:
        msg["content"] = text
    return msg


def skill_body(name):
    """读技能要回给她的东西：`<skill_content name="…">` 包着 SKILL.md 正文原文。

    停用的 / 校验失败的 / 不存在的 → `None`（调用方回那句逐字的 error）。
    """
    n = str(name or "").strip()
    if not n or n in disabled():
        return None
    cap = get(n)
    if cap is None:
        return None
    return '<skill_content name="%s">\n%s\n</skill_content>' % (cap.name, cap.body)


def names():
    """可用的技能名（有序；面板 / 自检用）。"""
    off = disabled()
    return [c.name for c in _ensure() if c.ok and c.name not in off]


# ── 执行：`toolkit.call()` 找不到内置工具时交到这里 ─────────────────

def dispatch(name, args, ctx):
    """跑一个扩展包工具。返回 `(认不认识这个工具, 结果)`。

    ⚠️ 停用 / 校验失败的包**派发不到**（"工具不可解锁"，也不该被悄悄调到）。
    ⚠️ 不看"有没有解锁"：和内置的条件工具（`end_turn`）一样，`call()` 照旧能派发
       —— 目录里看不看得见由 `tool_schemas()` 决定。
    """
    off = disabled()
    hit = None
    for cap in _ensure():
        if not cap.ok or cap.name in off:
            continue
        for t in cap.tools:
            if t["name"] == name:
                hit = t
                break
        if hit is not None:
            break
    if hit is None:
        return False, None
    return True, _run(hit, args, ctx)


def _run(tool, args, ctx):
    """在**有超时上限**的线程里跑它；异常原样抛给 `toolkit.call` 兜底。

    ⚠️ 超时抛 `TimeoutError`（`toolkit.call` 会把它变成既有的那句
       「这个工具出错了：TimeoutError」）—— 不新造给她看的句子。
    """
    box = {}
    argv = args if isinstance(args, dict) else {}

    def work():
        try:
            box["v"] = tool["run"](argv, ctx)
        except BaseException as e:          # noqa: BLE001 —— 原样交给上层兜底
            box["e"] = e

    th = threading.Thread(target=work, daemon=True,
                          name="cap-%s" % tool["name"])
    th.start()
    th.join(float(tool.get("timeout") or DEFAULT_TIMEOUT))
    if th.is_alive():
        raise TimeoutError("扩展包工具 %s 超过 %s 秒" % (tool["name"], tool.get("timeout")))
    if "e" in box:
        raise box["e"]
    res = box.get("v")
    if isinstance(res, dict):
        return res
    # 包可以返回字符串（docs §3）—— 包成 dict，跟内置工具同一个出口
    return {"ok": True, "说明": "" if res is None else str(res)}


# ── 一键安装：check / install / remove ─────────────────────────────

def _zip_safe_extract(zf, dest):
    """解 zip 到 dest，挡住 `../` 那种越界路径（解包目录之外的写不进去）。"""
    dest_abs = os.path.abspath(dest)
    for info in zf.infolist():
        name = info.filename
        if not name or name.endswith("/"):
            continue
        base_name = os.path.basename(name)
        if name.startswith("__MACOSX") or base_name in (".DS_Store",):
            continue
        target = os.path.abspath(os.path.join(dest_abs, name))
        if target != dest_abs and not target.startswith(dest_abs + os.sep):
            raise ValueError("zip 里有越界路径：%s" % name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def _pkg_root(d, depth=0):
    """在解包目录里找**包根**（含 SKILL.md 的那一层；允许外面再套 ≤2 层文件夹）。"""
    if _is_file(os.path.join(d, "SKILL.md")):
        return d
    if depth >= 2:
        return None
    try:
        subs = [x for x in os.listdir(d)
                if not x.startswith(".") and x != "__MACOSX"
                and os.path.isdir(os.path.join(d, x))]
    except Exception:
        return None
    if len(subs) != 1:
        return None
    return _pkg_root(os.path.join(d, subs[0]), depth + 1)


def _stage(src, tmp):
    """把 zip / 目录**先弄到临时目录**里（⛔ 校验没过一个文件都不落地）。

    返回 `(包根目录, 错误说明)`。
    """
    src = os.path.abspath(str(src or ""))
    stage = os.path.join(tmp, "pkg")
    if _is_file(src) and zipfile.is_zipfile(src):
        os.makedirs(stage, exist_ok=True)
        with zipfile.ZipFile(src) as zf:
            _zip_safe_extract(zf, stage)
    elif os.path.isdir(src):
        os.makedirs(stage, exist_ok=True)
        shutil.copytree(src, os.path.join(stage, os.path.basename(src.rstrip("\\/")) or "pkg"),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.bak-*"),
                        dirs_exist_ok=True)
        stage = os.path.join(stage, os.path.basename(src.rstrip("\\/")) or "pkg")
    else:
        return None, "既不是 zip，也不是文件夹：%s" % src
    root = _pkg_root(stage)
    if root is None:
        return None, "里面没有包根目录（要有一个文件夹，里面放着 SKILL.md）"
    return root, ""


def check(src):
    """只校验（`--check-capability` / 面板用）。返回 `{"ok","name","rules","message"}`。

    ⚠️ 不落地：全程在临时目录里，结束就删。
    """
    tmp = tempfile.mkdtemp(prefix="cap-check-")
    try:
        root, why = _stage(src, tmp)
        if root is None:
            return {"ok": False, "name": "", "rules": [], "message": why}
        folder = os.path.basename(root)
        # "zip 里没有外层文件夹"那种：包名取 frontmatter 的 name
        if os.path.normcase(root) == os.path.normcase(os.path.join(tmp, "pkg")):
            meta, _b = parse_skill(_text(os.path.join(root, "SKILL.md")) or "")
            folder = str((meta or {}).get("name") or folder).strip()
        info = validate(root, folder_name=folder, other_tools=_others(exclude=folder))
        return {"ok": info["ok"], "name": info["name"], "rules": info["rules"],
                "message": rules_text(info)}
    except Exception as e:
        return {"ok": False, "name": "", "rules": [], "message": "校验时出错：%s: %s"
                % (type(e).__name__, e)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _backup_name(dest):
    """备份目录名：`<名字>.bak-<时间>`（同一秒撞了就加 -2 / -3…）。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    p = "%s.bak-%s" % (dest, stamp)
    i = 1
    while os.path.exists(p):
        i += 1
        p = "%s.bak-%s-%d" % (dest, stamp, i)
    return p


def install(src):
    """从 zip / 文件夹装一个包（docs §5 那五步）。返回 `{"ok","message","name","rules"}`。

    ① 解到临时目录 → 校验（六条）
    ② 不过 → 报**具体哪一条**，一个文件都不落地
    ③ 过了 → 复制到 `<数据目录>/capabilities/<name>/`（已存在先备份 `<name>.bak-<时间>`）
    ④ 跑一次加载器确认能被发现；失败 → 回滚到第 ③ 步的备份
    ⑤ 记一行日志
    """
    root_data = data_root()
    os.makedirs(root_data, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="cap-install-")
    dest = backup = None
    try:
        root, why = _stage(src, tmp)
        if root is None:
            return {"ok": False, "message": why, "name": "", "rules": []}
        folder = os.path.basename(root)
        bare = os.path.normcase(root) == os.path.normcase(os.path.join(tmp, "pkg"))
        if bare:
            meta, _b = parse_skill(_text(os.path.join(root, "SKILL.md")) or "")
            folder = str((meta or {}).get("name") or folder).strip()
        info = validate(root, folder_name=folder, other_tools=_others(exclude=folder))
        if not info["ok"]:
            bad = info["first_bad"]
            return {"ok": False, "name": folder, "rules": info["rules"],
                    "message": "校验没过，一个文件都没装 —— 第 %d 条：%s"
                               % (bad["rule"], bad["message"])}
        name = info["name"]
        dest = os.path.join(root_data, name)
        if os.path.isdir(dest):
            backup = _backup_name(dest)
            os.replace(dest, backup)
            base.log("扩展：装 %s 之前先备份成 %s" % (name, os.path.basename(backup)))
        shutil.copytree(root, dest,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        # ④ 跑一次加载器，确认它真的能被发现（失败 → 回滚）
        with _LOCK:
            _CACHE.pop(os.path.abspath(dest), None)
        cap = None
        for c in _ensure():
            if c.name == name and os.path.normcase(c.dir) == os.path.normcase(os.path.abspath(dest)):
                cap = c
                break
        if cap is None or not cap.ok:
            msg = ("装完加载器认不出来" + ("（第 %d 条：%s）" % (cap.error_rule, cap.error_text)
                                         if cap is not None and cap.error_rule else ""))
            shutil.rmtree(dest, ignore_errors=True)
            if backup and os.path.isdir(backup):
                os.replace(backup, dest)
                msg += "，已回滚到备份"
            else:
                msg += "，已删掉装进去的文件"
            base.log("扩展：装 %s 失败（%s）" % (name, msg))
            return {"ok": False, "name": name, "rules": info["rules"], "message": msg}
        base.log("扩展：装好了 %s（%s%s）"
                 % (name, "带工具 " + "、".join(t["name"] for t in cap.tools)
                    if cap.tools else "只有说明",
                    "，旧版本备份在 " + os.path.basename(backup) if backup else ""))
        return {"ok": True, "name": name, "rules": info["rules"],
                "message": "装好了「%s」%s" % (name, "（旧版本备份成 %s）"
                                              % os.path.basename(backup) if backup else "")}
    except Exception as e:
        # 意外（权限 / 磁盘 / zip 坏）：尽量回到装之前的样子
        try:
            if dest and os.path.isdir(dest):
                shutil.rmtree(dest, ignore_errors=True)
            if backup and os.path.isdir(backup):
                if dest:
                    os.replace(backup, dest)
        except Exception:
            pass
        base.log_exc("扩展：装 %r" % (src,))
        return {"ok": False, "name": "", "rules": [],
                "message": "装的时候出错：%s: %s" % (type(e).__name__, e)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def remove(name):
    """卸载：删 `<数据目录>/capabilities/<名字>/`（顺手把备份一起清掉）。

    ⚠️ 仓库自带的示例包**删不了**（那是代码，不是装上去的）—— 只能停用。
    """
    n = str(name or "").strip()
    if not NAME_RE.match(n):
        return {"ok": False, "message": "名字不合法：%r" % (name,)}
    root = data_root()
    dest = os.path.join(root, n)
    if _is_builtin_dir(dest):
        # 就地部署（数据目录 = 代码目录）时它也是代码 —— 一个字节都不许删
        return {"ok": False, "message": ERR_BUILTIN}
    gone = []
    if os.path.isdir(dest):
        shutil.rmtree(dest, ignore_errors=True)
        if os.path.isdir(dest):
            return {"ok": False, "message": "删不掉「%s」（没有权限？关掉占用它的东西再试）" % n}
        gone.append(n)
    try:
        for x in os.listdir(root):
            if x.startswith(n + ".bak-"):
                shutil.rmtree(os.path.join(root, x), ignore_errors=True)
                if not os.path.isdir(os.path.join(root, x)):
                    gone.append(x)
    except Exception:
        pass
    if not gone:
        built = os.path.isdir(os.path.join(builtin_root(), n))
        msg = (ERR_BUILTIN if built else "没装过这个包：%s" % n)
        return {"ok": False, "message": msg}
    with _LOCK:
        _CACHE.pop(os.path.abspath(dest), None)
    cur = disabled()
    if n in cur:
        cur.discard(n)
        store.write_json(STATE_NAME, {"disabled": sorted(cur)})
    base.log("扩展：卸载了 %s%s" % (n, "（连备份 %d 个）" % (len(gone) - 1) if len(gone) > 1 else ""))
    return {"ok": True, "message": "卸载了「%s」%s"
                                   % (n, "（备份也一起清掉）" if len(gone) > 1 else "")}


# ── 从网址装 / 预检回执（2026-10-31，`package` 工具与面板共用）────────
#
# 只用一处实现：`package` 工具（主人聊天里装包）和面板「从网址安装」走的是
# **同一条**：下载 → 预检（六条 + 文件清单 / 大小 / sha256）→ 确认后才落进
# `<数据目录>/capabilities/`。⛔ 别在工具里另写一份白名单 / 大小判断。
#
# 下载规则（用户 2026-10-31 逐字定的）：
#   · 白名单（含子域）：github / gitee / jsdelivr + 几个镜像站；
#     另外 `capability.extraHosts` 可以加（面板 / `--set` 都能设）；
#   · 最大 5 MB；重定向 ≤5 跳（每一跳都要过白名单）；
#   · ⛔ 不带 cookie / 凭据（不建 HTTPCookieProcessor、不发 Authorization）；
#   · 只收 zip。
MAX_PACKAGE_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5

# 默认允许的下载域名（含子域）。镜像站是用户 2026-10-31 点名加的
# （实测从开发机都不通 —— 所以下载失败要给一句人话 + 建议 codeload 直链）。
DEFAULT_HOSTS = (
    "github.com", "codeload.github.com", "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "gitee.com", "cdn.jsdelivr.net",
    "ghproxy.com", "gh-proxy.com", "ghfast.top", "hub.gitmirror.com",
    "gh.llkk.cc", "mirror.ghproxy.com",
)

# 给模型 / 面板看的那几句（用户 2026-10-31 定的措辞）
ERR_OWNER = "只有主人能装。"
ERR_SOURCE = "只允许从 github / gitee / jsdelivr 装。"
ERR_BUILTIN = "自带示例包装在仓库里，删不掉（不想用就停用它）"
ERR_TOO_BIG_PKG = "包太大了（上限 5 MB）"
ERR_NOT_ZIP = "只收 zip"
ERR_DOWNLOAD = "下载失败 —— 换 codeload.github.com 的直链再试"
ERR_TICKET = "预检过期了，重新从网址装一次"
NEXT_STEP = "要装就再调一次，confirm=true"

# 预检的临时票据（ticket -> {"src","temp","at"}）：确认安装时**不用重下**。
_TICKETS = {}
TICKET_TTL = 30 * 60


def extra_hosts():
    """`capability.extraHosts`（字符串数组；命令行写成逗号分隔也认）。"""
    cap = base.cfg().get("capability")
    raw = cap.get("extraHosts") if isinstance(cap, dict) else None
    if isinstance(raw, str):
        raw = re.split(r"[,，\s]+", raw)
    out = []
    for x in raw or []:
        s = str(x or "").strip().lower()
        if not s:
            continue
        if "://" in s:
            s = (urllib.parse.urlsplit(s).hostname or "")
        s = s.strip().strip(".").rstrip(".")
        if s and s not in out:
            out.append(s)
    return out


def allowed_hosts():
    """生效的白名单 = 默认 + `capability.extraHosts`。"""
    out = builtins.list(DEFAULT_HOSTS)
    for h in extra_hosts():
        if h not in out:
            out.append(h)
    return tuple(out)


def host_allowed(url):
    """这个地址的主机在不在白名单里（**域名或子域**；带用户名的地址一律不许）。"""
    try:
        p = urllib.parse.urlsplit(str(url or "").strip())
    except Exception:
        return False
    if p.scheme not in ("http", "https"):
        return False
    if p.username or p.password:
        return False
    host = (p.hostname or "").strip().lower().rstrip(".")
    if not host:
        return False
    return any(host == d or host.endswith("." + d) for d in allowed_hosts())


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """别让 urllib 自己跟重定向 —— 每一跳都要先过白名单（不然白名单能被 302 绕过）。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener():
    """按配置建一个 opener：`capability.downloadProxy` 非空就走它（支持 http/https 代理）。

    ⚠️ 只支持 http(s) 代理 —— socks5 要额外装 PySocks，我们不带第三方依赖 ✗
    """
    px = ""
    try:
        px = str((base.cfg().get("capability") or {}).get("downloadProxy") or "").strip()
    except Exception:
        px = ""
    handlers = [_NoRedirect]
    if px:
        handlers.append(urllib.request.ProxyHandler({"http": px, "https": px}))
    return urllib.request.build_opener(*handlers), px


def _download_zip(url, timeout=30):
    """把一个网址下成临时 zip 文件。返回 `(路径, 错误人话)`。

    ⛔ 不带 cookie / 凭据；只收 zip；≤ 5 MB；重定向 ≤ 5 跳。
    ⚠️ 失败原因只写日志（状态码 / 地址），给模型 / 面板的只有一句人话。
    """
    if not host_allowed(url):
        return None, ERR_SOURCE
    cur = str(url or "").strip()
    blob = None
    opener, proxy = _opener()
    if proxy:
        base.log("扩展：下载走代理 %s" % proxy)
    for _hop in range(MAX_REDIRECTS + 1):
        if not host_allowed(cur):
            return None, ERR_SOURCE
        try:
            resp = opener.open(
                urllib.request.Request(cur, headers={"User-Agent": "MMZBOT/1.0"}),
                timeout=timeout)
        except urllib.error.HTTPError as e:
            loc = (e.headers.get("Location") or "") if e.headers else ""
            if e.code in (301, 302, 303, 307, 308) and loc:
                cur = urllib.parse.urljoin(cur, loc)
                continue
            base.log("扩展：从网址下载失败（HTTP %s）%s" % (e.code, cur[:200]))
            return None, ERR_DOWNLOAD
        except Exception as e:
            base.log("扩展：从网址下载失败（%s: %s）%s"
                     % (type(e).__name__, str(e)[:120], cur[:200]))
            return None, ERR_DOWNLOAD
        try:
            cl = str(resp.headers.get("Content-Length") or "").strip()
            if cl.isdigit() and int(cl) > MAX_PACKAGE_BYTES:
                return None, ERR_TOO_BIG_PKG
            blob = resp.read(MAX_PACKAGE_BYTES + 1)
        except Exception as e:
            base.log("扩展：读下载内容失败（%s）%s" % (type(e).__name__, cur[:200]))
            return None, ERR_DOWNLOAD
        finally:
            try:
                resp.close()
            except Exception:
                pass
        break
    else:
        base.log("扩展：重定向超过 %d 跳：%s" % (MAX_REDIRECTS, str(url)[:200]))
        return None, ERR_DOWNLOAD
    if not blob:
        return None, ERR_DOWNLOAD
    if len(blob) > MAX_PACKAGE_BYTES:
        return None, ERR_TOO_BIG_PKG
    fd, path = tempfile.mkstemp(prefix="cap-url-", suffix=".zip")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
    except Exception:
        try:
            os.remove(path)
        except Exception:
            pass
        return None, ERR_DOWNLOAD
    if not zipfile.is_zipfile(path):
        try:
            os.remove(path)
        except Exception:
            pass
        return None, ERR_NOT_ZIP
    return path, ""


def _files_of(root, full=False, limit=100):
    """包目录里的文件（相对路径，`/` 分隔，排序；跳过缓存 / 备份）。"""
    out = []
    for d, dirs, names in os.walk(root):
        dirs[:] = sorted(x for x in dirs if x != "__pycache__" and ".bak-" not in x)
        for n in sorted(names):
            if n.endswith(".pyc") or n in (".DS_Store",):
                continue
            p = os.path.join(d, n)
            rel = os.path.relpath(p, root).replace(os.sep, "/")
            out.append((rel, p) if full else rel)
    if full:
        return out
    return out[:limit] + (["…"] if len(out) > limit else [])


def _dir_size(root):
    total = 0
    for rel, p in _files_of(root, full=True):
        try:
            total += os.path.getsize(p)
        except Exception:
            pass
    return total


def _human_size(n):
    try:
        n = int(n or 0)
    except Exception:
        n = 0
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%.1f MB" % (n / 1024.0 / 1024.0)


def _sha256_path(path):
    h = hashlib.sha256()
    try:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
    except Exception:
        return ""
    return h.hexdigest()


def _sha256_dir(root):
    """目录的"内容指纹"（相对路径 + 内容，排序后算）—— 和 zip 的 sha256 一样有意义。"""
    h = hashlib.sha256()
    for rel, p in _files_of(root, full=True):
        h.update(rel.encode("utf-8", "replace") + b"\0")
        try:
            with open(p, "rb") as f:
                for chunk in iter(lambda: f.read(65536), b""):
                    h.update(chunk)
        except Exception:
            h.update(b"\0missing")
        h.update(b"\0")
    return h.hexdigest()


def inspect(src):
    """**预检**一个包（zip / 目录）→ 回执 dict（⛔ 不落地到 capabilities/）。

    回执就是用户 2026-10-31 点名要的那几项：
        包名 / 一句话 / 会新增的工具 / 文件清单 / 大小 / sha256 /
        六条校验结果 / 下一步
    """
    tmp = tempfile.mkdtemp(prefix="cap-inspect-")
    try:
        root, why = _stage(src, tmp)
        if root is None:
            return {"ok": False, "error": why}
        folder = os.path.basename(root)
        if os.path.normcase(root) == os.path.normcase(os.path.join(tmp, "pkg")):
            meta, _b = parse_skill(_text(os.path.join(root, "SKILL.md")) or "")
            folder = str((meta or {}).get("name") or folder).strip()
        info = validate(root, folder_name=folder, other_tools=_others(exclude=folder))
        size = _dir_size(root)
        source = os.path.abspath(str(src or ""))
        sha = _sha256_path(source) if os.path.isfile(source) else _sha256_dir(root)
        out = {"ok": bool(info["ok"]),
               "预检": True,
               "包名": str(info["meta"].get("name") or folder),
               "一句话": _one_line(info["meta"].get("description")),
               "会新增的工具": [t["name"] for t in info["tools"]],
               "文件清单": _files_of(root),
               "大小": _human_size(size),
               "sha256": sha,
               "六条校验": [{"规则": r["rule"], "通过": bool(r["ok"]),
                              "警告": bool(r["warn"]), "说明": r["message"]}
                            for r in info["rules"]]}
        if not info["ok"]:
            bad = info["first_bad"]
            out["error"] = "校验没过：第 %d 条：%s" % (bad["rule"], bad["message"])
        else:
            out["下一步"] = NEXT_STEP
        return out
    except Exception as e:
        base.log_exc("扩展：预检 %r" % (src,))
        return {"ok": False, "error": "预检时出错：%s: %s" % (type(e).__name__, e)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _prune_tickets():
    """丢掉过期的预检票据（顺手删掉它下载的临时 zip）。"""
    now = time.time()
    for token in builtins.list(_TICKETS):
        t = _TICKETS.get(token) or {}
        if now - float(t.get("at") or 0) > TICKET_TTL:
            _TICKETS.pop(token, None)
            if t.get("temp"):
                try:
                    os.remove(t["src"])
                except Exception:
                    pass


def stage_source(src, zip_only=False, timeout=30):
    """预检 + 留一张票据（确认安装时不用重下）。返回 `(ticket, 回执)`。

    `src` 是网址或本地路径；网址先下载（白名单 / 5 MB / 只收 zip）。
    `zip_only=True`：只收 zip 文件（`package` 工具那条路 —— 她刚 fetch 下来的文件）。
    """
    s = str(src or "").strip()
    if not s:
        return "", {"ok": False, "error": "没说从哪里装"}
    temp = False
    if s.lower().startswith(("http://", "https://")):
        path, why = _download_zip(s, timeout=timeout)
        if path is None:
            return "", {"ok": False, "error": why}
        temp = True
        s = path
    elif zip_only and not (os.path.isfile(s) and zipfile.is_zipfile(s)):
        return "", {"ok": False, "error": ERR_NOT_ZIP}
    rc = inspect(s)
    token = secrets.token_hex(8)
    with _LOCK:
        _prune_tickets()
        _TICKETS[token] = {"src": os.path.abspath(s), "temp": temp,
                           "at": time.time()}
    return token, rc


def install_ticket(ticket):
    """确认安装：按预检那张票据装（⛔ 票据用完就删，下载的临时 zip 一起删）。"""
    token = str(ticket or "").strip()
    with _LOCK:
        _prune_tickets()
        t = _TICKETS.pop(token, None)
    if not t:
        return {"ok": False, "message": ERR_TICKET, "name": "", "rules": []}
    try:
        return install(t["src"])
    finally:
        if t.get("temp"):
            try:
                os.remove(t["src"])
            except Exception:
                pass


# ── 面板 / App 的控制面（agent.on_api → 这里）──────────────────────

MAX_UPLOAD = 8 * 1024 * 1024          # 解出来的 zip 上限（面板走 base64，1MB 请求体也够）


def _b64_zip(raw):
    """面板传上来的 base64 → 一个临时 zip 文件路径（调用方负责删）。"""
    s = str(raw or "").strip()
    if not s:
        return None, "没收到文件"
    if "," in s and s.split(",", 1)[0].startswith("data:"):
        s = s.split(",", 1)[1]
    try:
        blob = base64.b64decode(s, validate=False)
    except Exception as e:
        return None, "文件内容不是合法的 base64（%s）" % e
    if not blob:
        return None, "文件是空的"
    if len(blob) > MAX_UPLOAD:
        return None, "文件太大了（%d 字节，上限 %d）" % (len(blob), MAX_UPLOAD)
    fd, p = tempfile.mkstemp(prefix="cap-upload-", suffix=".zip")
    with os.fdopen(fd, "wb") as f:
        f.write(blob)
    return p, ""


def api(action, req):
    """面板「扩展」页的动作。返回 dict（形状跟别处的控制面一致：`ok` + `message`）。

    认的动作：`capability.list` / `enable` / `disable` / `remove` / `install` /
    `check`。不认识 → `None`（server 回 501）。
    """
    a = str(action or "").strip().lower()
    req = req or {}
    if a == "capability.list":
        return {"ok": True, "capabilities": list(), "message": "",
                "dataDir": data_root(), "builtinDir": builtin_root(),
                # 面板「额外允许域名」/「下载代理」两个框要显示的当前值
                "extraHosts": extra_hosts(),
                "downloadProxy": str(((base.cfg().get("capability") or {}).get("downloadProxy")) or "")}
    if a in ("capability.enable", "capability.disable"):
        name = str(req.get("name") or "").strip()
        if get(name) is None and name not in {c["name"] for c in list()}:
            return {"ok": False, "message": "没有这个包：%s" % name}
        ok, msg = set_enabled(name, a.endswith("enable"))
        return {"ok": ok, "message": msg, "capabilities": list()}
    if a == "capability.remove":
        out = remove(req.get("name"))
        out["capabilities"] = list()
        return out
    if a == "capability.install":
        p, why = _b64_zip(req.get("zip"))
        if p is None:
            return {"ok": False, "message": why, "capabilities": list()}
        try:
            out = install(p)
        finally:
            try:
                os.remove(p)
            except Exception:
                pass
        out["capabilities"] = list()
        return out
    if a == "capability.check":
        out = check(req.get("path") or "")
        out["capabilities"] = list()
        return out
    if a == "capability.check_url":
        # 面板「从网址安装」第一步：服务端下载 → 预检 → 把回执直接给面板
        token, rc = stage_source(req.get("url") or "")
        out = dict(rc)
        out["ticket"] = token
        out["message"] = str(rc.get("error")
                              or ("预检通过：%s" % (rc.get("包名") or "")))
        out["capabilities"] = list()
        return out
    if a == "capability.install_url":
        # 第二步：「确认安装」→ 按票据装（不重新下载）
        out = install_ticket(req.get("ticket") or "")
        out["capabilities"] = list()
        return out
    return None
