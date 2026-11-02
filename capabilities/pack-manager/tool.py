#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`package` 工具：装 / 卸扩展包，下载消息里的文件（**只有主人能用**）。

这是仓库自带的包（`capabilities/pack-manager/`），不是"装上去的"：
它把已经存在的那套能力接到聊天里 —— ⛔ 校验 / 安装 / 备份 / 回滚 / 卸载
**一处都不重写**，全部走 `fgbot.capabilities`（`--install-capability` 和面板
「扩展」页用的是同一份实现）。

规则

  · `available(ctx)` = **说话的人是主人**（用户表 `主人: true` 那条的 `主人QQ`）；
    不是主人 → 这个工具根本不进她的工具目录；真被派发到也回「只有主人能装。」
  · `op=install`：第一段只预检（下载 → 校验 → 回执：包名 / 一句话 / 会新增的工具 /
    文件清单 / 大小 / sha256 / 六条校验 / 下一步），`confirm=true` 才真装；
    装完跑一次加载器自检，失败回滚（都在 `capabilities.install()` 里）。
  · `op=remove`：同样两段式；仓库自带的包拒绝（话术沿用 `capabilities.remove` 那句）。
  · `op=fetch`：把这条消息里的文件下到 `<数据目录>/files/`，回本地路径 + 大小。
  · 网址只认白名单（含子域）：github / gitee / jsdelivr + 镜像站 +
    `capability.extraHosts`；最大 5 MB；重定向 ≤5 跳；⛔ 不带 cookie / 凭据；只收 zip。

⚠️ 工具返回里的中文键 / 那几句 error 是**给模型看的文本**（改这些文字要先问维护者）：
   `capabilities.ERR_*` 与 `NEXT_STEP` 都是用户 原样定的，别改。
"""

import os

from fgbot import capabilities, files, users

NAME = "package"

DESC = "装或卸扩展包、下载消息里的文件"

PARAMS = {
    "type": "object",
    "properties": {
        "op": {"type": "string", "enum": ["install", "remove", "fetch"],
               "description": "install / remove / fetch"},
        "source": {"type": "string",
                   "description": "网址（github / gitee / jsdelivr）或本地路径，install 用"},
        "name": {"type": "string", "description": "包名，remove 用"},
        "file": {"type": "string", "description": "文件 id 或名字，fetch 用"},
        "confirm": {"type": "boolean", "description": "真要动手就传 true"},
    },
    "required": [],
}


def _is_owner(ctx):
    """说话的人是不是主人（= 用户表 `主人: true` 那条的 `主人QQ`）。

    ⚠️ 别用 `base.owner_mode()`：那是"这台机器的主人模式开没开"，不是"这句话是谁说的"。
       配置里 `role: owner` 但用户表还没标主人时，认不出是谁 → 不给这个工具。
    """
    try:
        qq = users.owner_qq()
        return bool(qq) and str((ctx or {}).get("user_id") or "").strip() == qq
    except Exception:
        return False


def available(ctx=None):
    """主人看得见 `package`；别人连目录里都没有它。"""
    return _is_owner(ctx)


def _yes(v):
    """`confirm` 只认真的 true（也认字符串 "true"/"1" —— 模型偶尔会写成字符串）。"""
    if v is True:
        return True
    return str(v or "").strip().lower() in ("true", "1", "yes")


def _bad(error, **extra):
    out = {"ok": False, "error": error}
    out.update(extra)
    return out


def _install(args, ctx, confirm):
    src = str(args.get("source") or "").strip()
    if not src:
        return _bad("没说从哪里装")
    is_url = src.lower().startswith(("http://", "https://"))
    if is_url:
        if not capabilities.host_allowed(src):
            return _bad(capabilities.ERR_SOURCE)
    else:
        if not os.path.isfile(src):
            return _bad("本地没有这个文件")
        try:
            if os.path.getsize(src) > capabilities.MAX_PACKAGE_BYTES:
                return _bad(capabilities.ERR_TOO_BIG_PKG)
        except Exception:
            pass

    # 第一段：只预检（下载 → 校验 → 回执），⛔ 一个文件都不落进 capabilities/
    token, rc = capabilities.stage_source(src, zip_only=True)
    if not rc.get("ok"):
        return _bad(rc.get("error") or "预检没过",
                    六条校验=rc.get("六条校验") or [])
    if not confirm:
        return rc                       # 回执里已经有「下一步」

    # 第二段：真装（`install()` 里跑一次加载器自检，失败回滚）
    res = capabilities.install_ticket(token)
    if not res.get("ok"):
        return _bad(res.get("message") or "没装上")
    return {"ok": True, "装好了": res.get("name") or rc.get("包名") or "",
            "说明": res.get("message") or ""}


def _remove(args, confirm):
    name = str(args.get("name") or "").strip()
    if not name:
        return _bad("没说卸哪个包")
    row = next((c for c in capabilities.list() if c["name"] == name), None)
    if row is None:
        return _bad("没装过这个包：%s" % name)
    if not row.get("can_remove"):
        # 仓库自带的包（跟着代码走）：只能停用。话术和 `capabilities.remove()` 同一句。
        return _bad(capabilities.ERR_BUILTIN)
    if not confirm:
        return {"ok": True, "预检": True, "包名": name,
                "一句话": row.get("description") or "",
                "带工具": bool(row.get("has_tools")),
                "工具": row.get("tools") or [],
                "下一步": "要删就再调一次，confirm=true"}
    res = capabilities.remove(name)
    if not res.get("ok"):
        return _bad(res.get("message") or "没卸掉")
    return {"ok": True, "卸掉了": name, "说明": res.get("message") or ""}


def _fetch(args, ctx):
    want = str(args.get("file") or "").strip()
    refs = (ctx or {}).get("files_all") if isinstance(ctx, dict) else None
    if not isinstance(refs, list) or not refs:
        refs = files.all_refs(ctx)
    if not refs:
        return _bad("这条消息里没有文件")
    ref = files.find(ctx, want, refs) if want else (refs[0] if len(refs) == 1 else None)
    if ref is None:
        names = "、".join((r.get("name") or r.get("id") or "?") for r in refs)
        return _bad("没找到这个文件（这条消息里的文件：%s）" % names)
    return files.download(ref, ctx)


def run(args, ctx):
    """执行一个动作。返回 dict；异常由 `toolkit.call` 兜底。"""
    a = args if isinstance(args, dict) else {}
    if not _is_owner(ctx):
        return _bad(capabilities.ERR_OWNER)
    op = str(a.get("op") or "").strip().lower()
    if op == "install":
        return _install(a, ctx, _yes(a.get("confirm")))
    if op == "remove":
        return _remove(a, _yes(a.get("confirm")))
    if op == "fetch":
        return _fetch(a, ctx)
    return _bad("op 只认 install / remove / fetch")
