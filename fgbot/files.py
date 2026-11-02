#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""消息里的**文件**：认出来（入站）+ 取到本地（fetch）。

和图片那条路（`images.py`）**同一个口径**：

  · 当前这条消息：`[CQ:file,...]` 拆成 `[{id, name, size}]`（`server.build_ctx`
    把它放进 `ctx["files"]`；正文里仍然只显示 `[文件]` 这个占位）；
  · **引用（回复）那条**：只认引用关系（`ctx["reply_to"]` → `get_msg`），
    不靠关键词猜 —— 和 `images.load_quoted()` 一样；
  · 群聊 / 私聊都走同一条路：CQ 形态一模一样，区别只在问 NapCat 要地址时
    用 `get_group_file`（群）还是 `get_file`（私聊）。

⛔ 这一份只负责"拿到文件和事实"，**不往给模型看的文本里加任何台词**：
   占位、说明由调用方（`agent._occasion` 的 file_note / `package` 工具的返回）
   拼；这里只回 dict。

⚠️ 文件名 / 大小 / id 都可能缺（不同 NapCat 版本给的不一样）：
    `id` 缺了就用文件名去问，`size` 缺了当 0（真下下来再核大小）。
"""

import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import base, images, im, napcat, store

# 一轮最多认几个（和图片 MAX_IMAGES 同口径，防炸）
MAX_FILES = 3
# 单个文件上限
MAX_BYTES = 50 * 1024 * 1024
# 问 NapCat / 下载的超时（秒）
TIMEOUT = 30

# 自检钩子：换掉「下载」那一步（None = 真去下）
_FETCHER = None
# 自检钩子：换掉「问 NapCat 要地址」那一步（None = 真去问）
_PULLER = None

_FILE_CQ = re.compile(r"\[CQ:file,([^\]]*)\]")

# 给模型看的失败原因
_TOO_BIG = "文件太大了（超过 50 MB）"
_EXPIRED = "文件过期了，让他重发一份"
_NO_FILE = "拿不到这个文件"


def set_fetcher(fn):
    """自检挂钩：换成假的下载函数（离线跑完整链路）。"""
    global _FETCHER
    _FETCHER = fn


def set_puller(fn):
    """自检挂钩：只换掉「问 NapCat 要地址」那一步（不设 = 真去问 NapCat）。"""
    global _PULLER
    _PULLER = fn


# ── 认出来（入站）───────────────────────────────────────────────────

def _ref(d):
    """一段 CQ 参数 / 一个段 → `{"id","name","size"}`（缺的留空 / 0）。"""
    d = d if isinstance(d, dict) else {}
    fid = str(d.get("file_id") or d.get("id") or d.get("fileId") or "").strip()
    name = str(d.get("file") or d.get("name") or d.get("file_name")
               or d.get("fileName") or "").strip()
    size = d.get("file_size") if d.get("file_size") is not None else d.get("size")
    try:
        size = int(size)
    except Exception:
        size = 0
    return {"id": fid, "name": name, "size": max(0, size)}


def _clean_refs(items, limit):
    out = []
    for r in items or []:
        if not isinstance(r, dict):
            continue
        r = _ref(r)
        if not (r["id"] or r["name"]):
            continue
        out.append(r)
        if len(out) >= limit:
            break
    return out


def refs_from_raw(raw, limit=MAX_FILES):
    """CQ 原文里的文件段 → `[{id, name, size}]`（最多 limit 个）。"""
    out = []
    for m in _FILE_CQ.finditer(raw or ""):
        out.append(_ref(napcat.params_of(m.group(1))))
        if len(out) >= limit:
            break
    return _clean_refs(out, limit)


def refs_from_segs(segs, limit=MAX_FILES):
    """段数组那份（`get_msg` 也会给 `message`；兜底用）。"""
    out = []
    for seg in segs or []:
        if not isinstance(seg, dict) or seg.get("type") != "file":
            continue
        out.append(_ref(seg.get("data") or {}))
        if len(out) >= limit:
            break
    return _clean_refs(out, limit)


def refs_of(ctx):
    """当前这条消息里的文件（`ctx["files"]` 优先；没有就从 raw 现拆）。"""
    ctx = ctx or {}
    ctx_files = ctx.get("files")
    if isinstance(ctx_files, list):
        got = _clean_refs(ctx_files, MAX_FILES)
        if got:
            return got
    return refs_from_raw(ctx.get("raw") or "", MAX_FILES)


def _quoted_msg(ctx):
    """被引用那条消息（按 `ctx` 缓存，免得和 `images.load_quoted` 各问一遍 NapCat）。"""
    if not isinstance(ctx, dict):
        return None
    rid = ctx.get("reply_to")
    if not rid:
        return None
    if ctx.get("_quoted_msg") is not None:
        return ctx.get("_quoted_msg")
    msg = images._quoted_msg(rid)
    if msg is not None:
        ctx["_quoted_msg"] = msg
    return msg


def quoted_refs(ctx):
    """**被引用的那条消息**里的文件（最多 MAX_FILES 个）；拿不到就是 []。"""
    msg = _quoted_msg(ctx)
    if not msg:
        return []
    return (refs_from_raw(msg.get("raw_message") or "", MAX_FILES)
            or refs_from_segs(msg.get("message") or [], MAX_FILES))


def all_refs(ctx):
    """当前这条 + 引用那条的文件（按 id/名字去重，当前这条在前）。"""
    out, seen = [], set()
    for r in refs_of(ctx) + quoted_refs(ctx):
        key = (r.get("id") or "", r.get("name") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def find(ctx, want, refs=None):
    """按**文件 id 或名字**找一个（找不到返回 None）。

    ⚠️ 模型可能把完整文件名 / 只有扩展名的一部分填进来：先精确比 id，再精确比名字，
       最后比 basename（大小写不敏感）。
    `refs` 给了就在那份里找（`package` 工具用 `ctx["files_all"]` —— 当前 + 引用的）；
    没给就现解析（和 `note()` 同一套）。
    """
    w = str(want or "").strip()
    if not w:
        return None
    refs = refs if refs is not None else all_refs(ctx)
    for r in refs:
        if w == (r.get("id") or "") or w == (r.get("name") or ""):
            return r
    wb = os.path.basename(w.replace("\\", "/")).lower()
    for r in refs:
        if os.path.basename((r.get("name") or "").replace("\\", "/")).lower() == wb:
            return r
    return None


# ── 大小 / 名字 ──────────────────────────────────────────────────────

def size_text(n):
    """字节 → 一句人话（`1.2 MB` / `345 KB` / `12 B`）。"""
    try:
        n = int(n or 0)
    except Exception:
        n = 0
    if n < 1024:
        return "%d B" % n
    if n < 1024 * 1024:
        return "%.1f KB" % (n / 1024.0)
    return "%.1f MB" % (n / 1024.0 / 1024.0)


def _safe_name(name, ref=None):
    """文件名过成"能落盘"的样子（路径分隔符 / 控制符换成 _）。"""
    s = str(name or "").replace("\\", "/")
    s = os.path.basename(s)
    s = re.sub(r'[\x00-\x1f<>:"/\\|?*]', "_", s).strip(" .")
    if not s:
        s = "file-%s" % ((ref or {}).get("id") or "x")
    return s[:120]


def _dest(name):
    """`<数据目录>/files/<名字>`；重名就加 -1 / -2（不覆盖别人下过的）。"""
    d = store.path("files")
    try:
        os.makedirs(d, exist_ok=True)
    except Exception:
        pass
    p = os.path.join(d, name)
    if not os.path.exists(p):
        return p
    stem, ext = os.path.splitext(name)
    i = 1
    while os.path.exists(p):
        p = os.path.join(d, "%s-%d%s" % (stem, i, ext))
        i += 1
    return p


# ── 取到本地 ────────────────────────────────────────────────────────

def _human_reason(text):
    """NapCat / 下载那边的失败原因 → 给模型的两句话之一（过期 / 取不到）。"""
    s = str(text or "").lower()
    if any(k in s for k in ("过期", "失效", "expired", "not found", "不存在",
                            "404", "410", "403")):
        return _EXPIRED
    return _NO_FILE


def _brief_url(url):
    """日志里只留主机 + 路径 —— 查询串里可能有 rkey（凭据），⛔ 别整条抄进日志。"""
    try:
        p = urllib.parse.urlsplit(str(url or ""))
        return ("%s://%s%s" % (p.scheme, p.hostname or "", p.path))[:200]
    except Exception:
        return str(url or "")[:80]


def _addr(data):
    """NapCat 回的 data → `(url, 本地路径)`（两个都可能空）。"""
    if isinstance(data, str):
        s = data.strip()
        return (s, "") if s.startswith("http") else ("", s if os.path.isabs(s) else "")
    if not isinstance(data, dict):
        return "", ""
    url = str(data.get("url") or data.get("download_url") or data.get("downloadUrl")
              or "").strip()
    path = str(data.get("file") or data.get("path") or "").strip()
    if not url and path.startswith("http"):
        url, path = path, ""
    if url.startswith("http"):
        return url, ""
    return "", (path if os.path.isabs(path) else "")


def _ask_napcat(ref, ctx):
    """问 NapCat 要下载地址。返回 `(url, 本地路径, 给模型的原因)`。"""
    fid = str((ref or {}).get("id") or (ref or {}).get("name") or "").strip()
    if not fid:
        return "", "", _NO_FILE
    ctx = ctx or {}
    if _PULLER is not None:
        try:
            ok, data = _PULLER(fid, ctx)
        except Exception as e:
            base.log("问 NapCat 要文件炸了（%s）：%s: %s"
                     % (fid, type(e).__name__, str(e)[:160]))
            return "", "", _NO_FILE
        if not ok:
            return "", "", _human_reason(data)
        url, path = _addr(data)
        return (url, path, "") if (url or path) else ("", "", _NO_FILE)

    # ⚠️ 真机踩到：NapCat 不同版本支持的接口不一样。
    #    实测（QQ 3.2.20-40990 + NapCat 4.x）：
    #      get_group_file      → "不支持的Api"
    #      get_file            → 能用（file not found 是参数问题，接口在）
    #      get_group_file_url  → "packetBackend不可用"（QQ build 超出后端兼容区）
    #    → 所以这里**按顺序挨个试**，谁给地址就用谁；全都失败再回人话。
    attrs = []
    if ctx.get("is_group") and ctx.get("group_id"):
        gid = int(ctx["group_id"])
        attrs.append(("get_group_file", {"group_id": gid, "file_id": fid}))
        attrs.append(("get_file", {"file_id": fid}))
        attrs.append(("get_group_file_url", {"group_id": gid, "file_id": fid}))
        attrs.append(("get_private_file_url", {"file_id": fid}))
    else:
        attrs.append(("get_file", {"file_id": fid}))
        attrs.append(("get_private_file_url", {"file_id": fid}))
    reasons = []
    for act, payload in attrs:
        try:
            ok, data = im._napcat_call(act, payload, timeout=TIMEOUT)
        except Exception as e:
            base.log("问 NapCat 要文件炸了（%s / %s）：%s: %s"
                     % (fid, act, type(e).__name__, str(e)[:120]))
            continue
        if not ok:
            base.log("问 NapCat 要文件没成（%s / %s）：%s" % (fid, act, str(data)[:160]))
            why = _human_reason(data)
            if why and why not in reasons:
                reasons.append(why)
            continue
        url, path = _addr(data)
        if not url and not path:
            base.log("问 NapCat 要文件，它没给地址（%s / %s）：%s"
                     % (fid, act, str(data)[:160]))
            continue
        base.log("问 NapCat 要文件成了（%s / %s）" % (fid, act))
        return url, path, ""
    return "", "", (reasons[0] if reasons else _NO_FILE)


def _download(url):
    """下载一个地址（不带 cookie / 凭据；只读到上限 + 1 字节就停）。"""
    if _FETCHER is not None:
        return _FETCHER(url)
    req = urllib.request.Request(url)
    req.add_header("User-Agent",
                   "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120 Mobile Safari/537.36")
    req.add_header("Referer", "https://qun.qq.com/")
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        cl = str(r.headers.get("Content-Length") or "").strip()
        if cl.isdigit() and int(cl) > MAX_BYTES:
            raise ValueError("too-big")
        return r.read(MAX_BYTES + 1)


def _read_path(path):
    """读 NapCat 给的本地文件；太大 → ValueError。"""
    if os.path.getsize(path) > MAX_BYTES:
        raise ValueError("too-big")
    with open(path, "rb") as f:
        return f.read(MAX_BYTES + 1)


def download(ref, ctx=None):
    """把一个文件取到 `<数据目录>/files/`。

    返回 `{"ok": True, "本地路径": …, "文件名": …, "大小": "1.2 MB"}`，
    或者 `{"ok": False, "error": 过期/取不到/太大}`（三句人话之一）。

    ⚠️ 先看消息里带的大小（省一次下载）；下完再核一遍大小（Content-Length 不可信）。
    """
    ref = _ref(ref or {})
    name = _safe_name(ref.get("name"), ref)
    if ref.get("size") and int(ref["size"]) > MAX_BYTES:
        return {"ok": False, "error": _TOO_BIG}
    url, local, why = _ask_napcat(ref, ctx)
    if why:
        return {"ok": False, "error": why}
    t0 = time.time()
    try:
        blob = _read_path(local) if local else _download(url)
    except ValueError:
        return {"ok": False, "error": _TOO_BIG}
    except urllib.error.HTTPError as e:
        base.log("下载文件失败（HTTP %s）：%s" % (e.code, _brief_url(url)))
        return {"ok": False, "error": _human_reason("HTTP %s" % e.code)}
    except Exception as e:
        base.log("下载文件失败（%s）：%s" % (type(e).__name__, _brief_url(url)))
        return {"ok": False, "error": _NO_FILE}
    if not blob:
        return {"ok": False, "error": _NO_FILE}
    if len(blob) > MAX_BYTES:
        return {"ok": False, "error": _TOO_BIG}
    path = _dest(name)
    try:
        with open(path, "wb") as f:
            f.write(blob)
    except Exception as e:
        base.log("文件写不进数据目录（%s）：%r" % (path, e))
        return {"ok": False, "error": _NO_FILE}
    base.log("取到一个文件：%s（%d 字节、%.1f 秒）"
             % (name, len(blob), time.time() - t0))
    return {"ok": True, "本地路径": path, "文件名": name, "大小": size_text(len(blob))}


def note(ctx):
    """这一轮消息里带的文件 → 一句**事实**（给 `agent._occasion` 用；没有就空串）。

    只写名字和大小（模型要 fetch 时拿名字就够），⛔ 不写"你要做什么"。
    """
    cur = refs_of(ctx)
    q = quoted_refs(ctx)
    out = []
    if cur:
        out.append("（这条消息带了文件：%s）" % _join(cur))
    if q:
        out.append("（他引用的那条里有文件：%s）" % _join(q))
    return "".join(out)


def _join(refs):
    bits = []
    for r in refs:
        n = (r.get("name") or r.get("id") or "文件").strip()
        bits.append("%s（%s）" % (n, size_text(r.get("size"))) if r.get("size") else n)
    return "、".join(bits)
