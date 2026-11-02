#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模板：一个最小的扩展包工具（复制这个文件夹再改，别直接改这里）。

这个文件是**给人看的样板**，每一行都写了"为什么"。
真正的说明在 docs/capability-format.md 的「5 分钟写一个包」那一节。
"""

# ── 只用标准库 + fgbot 现有的模块 ───────────────────────────────────
#
# 别的第三方库不要 import（手机上没有）。要用就写 requirements.txt，
# 安装时会提示主人自己装（不会自动装）。
import os

from fgbot import base          # 日志用 base.log()，别 print
from fgbot import users         # 想查用户表就用它（示例）

# ── 工具的四件套 ────────────────────────────────────────────────────
#
# NAME  模型看到的就是它：英文 / 数字 / 下划线，不能以数字开头，
#       ⛔ 不能和主程序内置的工具重名（now / memory / search …）。
NAME = "my_tool"

# DESC  一句话「什么时候用」。和普通工具一样短，不写台词。
DESC = "一句话说清这个工具能干什么"

# PARAMS  必须是合法的 JSON Schema：type / properties / required 三个都要有。
#         没有参数也要写 properties: {}, required: []。
PARAMS = {
    "type": "object",
    "properties": {
        "who": {"type": "string", "description": "他的【消息前缀】；不填=当前说话的人"},
    },
    "required": [],
}


def available(ctx=None):
    """可选。返回假 = 这个工具**不进**给模型的工具目录（技能那行还在）。

    `ctx` 和 run() 拿到的是同一个：`ctx["user_id"]` / `ctx["group_id"]` /
    `ctx["is_group"]` 这些。抛异常当"不可见"，不会炸对话。
    """
    try:
        return bool((ctx or {}).get("user_id"))
    except Exception:
        return False


def run(args, ctx):
    """真正干活的地方。返回 dict（推荐）或 str。

    · 抛异常会被兜住，变成 {"ok": false, "error": ...} 回给模型 —— 但她看到的是
      "这个工具出错了"，所以**能预料的失败自己返回 {"ok": False, "error": "人话"}**。
    · 超时默认 20 秒；要久一点就在模块级写 `TIMEOUT = 60`。
    · 副作用（发消息 / 写文件）允许，但要在 SKILL.md 正文里写明。
    """
    who = str((args or {}).get("who") or "").strip()
    qq = str((ctx or {}).get("user_id") or "")
    if not qq:
        return {"ok": False, "error": "不知道当前说话的人是谁"}
    rec = users.by_qq(qq) or {}
    name = users.owner_qq() if who == "主人" else qq
    base.log("my_tool：who=%r qq=%s 记录=%r" % (who, qq, bool(rec)))
    return {"ok": True, "QQ": qq, "问的是": name or who or qq,
            "文件": os.path.basename(__file__)}
