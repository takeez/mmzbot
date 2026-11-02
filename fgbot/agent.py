#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""agent 层 —— **她就是这一层**。怎么想、该不该回、怎么说、记什么，全在这儿。

═══ 这一层照 DSH 的 agent 循环搭，不自己发明 ═══

一轮对话的形状（`_build`）：

    [system]  身份 + 性格 + 说话约定          ← 稳定前缀（前缀缓存友好）
    [user]    技能目录（**至少一个技能可用时才发**；⛔ 只有一条）  ← 扩展包 / 知识锁
    [user]    群聊：「你看到的是这个群最近 N 条消息」；私聊没有
    [history] 之前看得见的对话（只含 user/assistant 文本）
    [user]    场合事实（在哪个群 / 跟谁说话）—— 单独一条快照
    [user]    「张三（QQ 10001）: 你好」   ← 最后一条必须是他的原话本身

为什么不能把场合事实拼进 system：DeepSeek 的端点**把 messages 里最新的一条 system
当成完整的有效系统提示词**（DSH 的适配器把这个特性声明为 `systemPromptUpdate: in-history`，
并因此选择「把变化后的提示词追加到已缓存历史之后，而不是改写开头的 system 消息」）。
所以场合事实不能作为一小段 system 拼在尾巴上 —— 那样她的性格和约定会被整段顶掉。
这也是 v1 那条教训的正解：旁路信息走 `user` 角色、**单独成一条**、绝不粘在用户那句话前面。

═══ 说话这件事 ═══

除判活（ping）之外，**用户看到的每一句话都由模型组织**：
提醒到点、取消成功、称呼记下，一律是把事实递过去、把她叫醒，让她自己说。
代码只提供事实（工具结果、场合、时间）和唤醒，不提供台词。

═══ 代码兜底（提示词是概率的，代码是硬的）═══

  · 内心独白：发出去**之前**削掉（guards.strip_monologue）。
  · 「说做了其实没做」：核这一轮的工具调用记录，对不上就给她一次机会改口
    （把真相作为 system 事实递回去重说），第二次还不改就把那句假话删掉。
"""

import json
import os
import random
import re
import threading
import time

from . import (base, capabilities, clock, files, groups, guards, images, im, llm,
               memory, onboard, persona, plan, reminders, reqs, settings, statuscache,
               store, toolkit, users)
# ⚠️ 认人 / 显示名的唯一实现在 `who.py`。这里**换了个名字**引它：本文件里 `who`
#    这个局部变量满地都是（播报材料那个"谁"），直接 `import who` 会被它们遮住。
from . import who as who_mod

_STARTED = time.time()
_LOCK = threading.RLock()
_CHIME = {}          # key -> {"last": ts, "times": [ts, ...]}
_POKE = {}           # qq -> 上次回戳的时间

# 「这个动作只有主人能调，而你不是主人」—— `server.py` 看到它就回 **403 空正文**（B6）。
# 不能回 `{"ok":false}`：契约 B6 要的是 403，而且面板看到 403 会重新要 token。
FORBIDDEN = object()

# 「看共享令牌」那一组动作名（2026-10-03 加；面板上那个「🔑 看共享令牌」按钮）。
# ⚠️ **只有主人**能调（和 `user.*` 同一个口径，别人 FORBIDDEN → server 回 403 空正文）。
# ⚠️ `server.py` 拿这张表决定**响应加不加 `Cache-Control: no-store`**
#    （响应里带着凭据明文，绝不许被浏览器/中间层缓存）—— 两处共用这一份，别各写一套。
TOKEN_SHOW_ACTIONS = ("token.show", "令牌", "看令牌", "共享令牌")

# 「只有主人能调」的**控制面动作**（2026-10-05 加；用户拍板"需要只有我能调"）。
#
# 为什么要有它：这些动作以前**本机 / 局域网任何一把有用户令牌的人都能调**
# （公网那条路早就被 `server.PUBLIC_ACTIONS` 挡住了，局域网没有）：
#   · `reset`            —— 清**所有人**的对话记忆；
#   · `add`/`use`/`del`  —— 改 LLM API 配置（还能顺手把 key 写进去）；
#   · `test`             —— 拿现在这家 API 发一次真请求（花的是主人的钱）；
#   · `effort`           —— 思考强度；`triggers` —— 触发词；
#   · `memory` / `mem_*` —— 读**和写**所有人的长期记忆；
#   · `mode`             —— 人格切换（v2 已经删了，动作名还留着）；
#   · `restart` / `重启`  —— 重启她（`server.py` 里那条 `restart` 也单独加了同一道闸）。
# 口径和 `user.*` / `group.*` / `request.*` / `token.show` **一模一样**：
# 不是主人 → `FORBIDDEN` → `server.py` 回 **403 空正文**。
#
# ⛔ 只加闸：这些动作的**名字 / 参数 / 返回结构一个字都没动**（主人调它们的结果和从前逐字相同）。
# ⛔ 已经加过闸的那些（user.* / group.* / request.* / token.show）一个字节都没碰。
OWNER_ONLY_ACTIONS = (
    "reset",
    "add", "use", "del", "test",
    "effort", "reasoning", "思考强度",
    "triggers", "触发词", "关键词",
    "memory", "记忆",
    "mem_add", "记忆加", "mem_fix", "mem_del", "记忆改", "记忆删",
    "mem_name", "记忆称呼", "mem_person_add", "加人", "mem_person_del", "删人",
    "mode",
    "restart", "重启",
    # 运行参数（2026-10-30）：改 settings.json 的覆盖值 / 全部恢复默认。
    "settings.save", "参数保存", "settings.reset", "参数恢复",
    # 提供商 / 模型目录（2026-10-30，面板「她的大脑」「后台模型」两张卡）。
    # 能改 key、能切她的大脑 —— 和 add/use/del 同一档，只有主人能调。
    "providers.save", "providers.delete", "providers.activate",
    "providers.addmodels", "providers.delmodel", "providers.fetchmodels",
    "providers.utility",
    # 设置页（2026-10-31）：改的是**部署配置本身**（她的 QQ / token / 群 /
    # NapCat 地址 / 人设正文），和 add/use/del 同一档 —— 只有主人能调。
    # ⚠️ `onboarding.probe` / `onboarding.groups` 是只读的（问 NapCat 要数据），
    #    但它们的结果也会进面板的检查表，干脆一起挡在主人这一层。
    "onboarding.save", "onboarding.probe", "onboarding.groups",
    "onboarding.persona",
)

# 提供商那几条（`server.py` 的 `_handle_api` 只做主人闸，具体交给 `_providers_api`）。
PROVIDER_ACTIONS = (
    "providers.save", "providers.delete", "providers.activate",
    "providers.addmodels", "providers.delmodel", "providers.fetchmodels",
    "providers.utility",
)

# 「前台等不到了，但这条还没死」—— handle() 返回它（不是字符串、也不是 None）。
# `server.py` 看到它就**一个字都不发**：发给用户那一下由后台 job 自己完成
# （回调已经从 server 传进来了，见 _late_reply）。哨兵 = 明确的"已交给后台"，
# 不靠猜；None 仍然是"她决定不说话"。
LATE_PENDING = memory.LATE_PENDING


# ── 入口：一条消息 ──────────────────────────────────────────────────

def _plain(s):
    """把 CQ 机器码从"给她看的文本"里去掉（`[CQ:at,qq=123]`、`[CQ:image,...]` 这些）。

    ⚠️ 只动**给她看的那份文本**，`ctx["raw"]` 一个字不碰 —— 点名/@/回复的判断
       全在 raw 上做，剥了会认不出"这条是不是在叫她"。
    踩过的现场：历史里明晃晃写着一行
        `未设置（QQ 30003）: [CQ:at,qq=10001] 您能教我狗位怎么玩吗`
    —— @ 的机器码对她没有意义，还占着上下文。
    """
    s = re.sub(r"\[CQ:[^\]]*\]", " ", s or "")
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def handle(ctx, late=None):
    """收到一条消息。返回一句话就发出去（群里带引用回复）；返回 None 就不说话。

    `late`（可选）是**发送回调**（`server.py` 传进来的，格式和正常发送一模一样）：
    这条消息在 `maxWaitSeconds` 之内没算完时，`handle()` 先回 `LATE_PENDING`
    （前台什么都不发），后台 job 算完之后自己用它把结果发出去 —— 迟到也发，不丢。
    """
    try:
        base.maybe_reload()
        _consume_control()

        uid = str(ctx.get("user_id") or "")
        if not uid or uid == str(base.self_id()):
            return None                                  # 别理自己（防自问自答打转）
        if ctx.get("is_group"):
            # 2026-10-04 用户要的「群管理」：**朋友把机器人邀请到别的群**时她收到了消息，
            # 可用户根本不知道群号是多少 —— 所以这里先留一条痕（群号 + 群名 + 什么时候 +
            # 谁在说话），面板上列出来，他自己点"加入白名单"。
            # ⚠️ 这一句**必须在 `_in_scope` 前面**：不在名单里的群才需要记。
            # ⚠️ 它只记事实、**⛔ 绝不记消息内容**（见 groups.see 的 docstring）；
            #    群名这里**不查**（NapCat 一次都不打）—— 面板按需去补，见 groups.name_of。
            # ⚠️ 它**不决定理不理**：下一句照旧由 `_in_scope`（三份名单的并集）说了算。
            groups.see(ctx.get("group_id"), ctx.get("who") or "")
        if not _in_scope(ctx):
            return None                                  # 不在群名单里

        # 记下他的 QQ 昵称/群名片：面板上"没定称呼"的人就用它显示（以前只现取现用，
        # 结果面板里那几个人只能显示成一串 QQ 号）。只在变了的时候才写盘，见 memory.touch。
        # ⚠️ 从原始事件里取（ctx["evt"].sender），不劳 server.py 多塞两个字段。
        # ⚠️ 2026-10-06（用户拍板）：**群名片按群存** —— 名片要连**群号**一起交下去，
        #    私聊（`group_id` 空）那边 `touch()` 一个字都不写名片。
        sender = (ctx.get("evt") or {}).get("sender") or {}
        memory.touch(uid, sender.get("nickname") or "", sender.get("card") or "",
                     ctx.get("group_id"))

        text = _plain(ctx.get("text") or "")

        # ── 判活：唯一不经过模型的一句话（要零延迟、不花 token、不受模型抽风影响）
        if _is_ping(text):
            reply = ((base.cfg().get("agent") or {}).get("pingReply") or "在呀。").strip() or "在呀。"
            memory.record(ctx["key"], "user", text, qq=uid, name=_call(ctx))
            memory.record(ctx["key"], "assistant", reply)
            base.log("判活：直接回「%s」" % reply)
            return reply

        addressed = _why(ctx)
        memory.record(ctx["key"], "user", text or "（空消息）", qq=uid, name=_call(ctx))

        if addressed == "触发词":
            # 触发词专属限流（默认 30 秒；配 0 = 关掉）。⛔ 只拦"触发词"这条路 ——
            # 私聊/被 @/叫名字是被人点名，一律照答。
            wait = (base.cfg().get("agent") or {}).get("triggerCooldownSeconds")
            wait = 30 if wait is None else int(wait)
            if wait > 0:
                last = _TRIG_AT.get(ctx["key"])
                if last and (time.time() - last) < wait:
                    base.log("触发词：%.0f 秒前刚因为触发词接过一次，这条不接（照旧记进对话，"
                             "不打断）" % (time.time() - last))
                    return None
                _TRIG_AT[ctx["key"]] = time.time()
                base.log("触发词：接这条（%d 秒内不再因为触发词接）" % wait)

        if not addressed:
            # 没叫她。先看这次要不要"自己接一句"（1% 概率、间隔半小时、每小时最多 3 次）
            if not _chime_ok(ctx):
                return None                              # 闲聊：记下来，但不插嘴
            # 第 41 条：真的是掷到的那一轮，才算"随机接话"场合 ——
            # `toolkit.schemas(ctx)` 靠它把 end_turn 放进目录。
            ctx["_trigger"] = "chime"
        reminders.ensure_timer(_on_due)
        return memory.submit(ctx["key"], lambda: _think(ctx, addressed),
                             timeout=int(((base.cfg().get("agent") or {}).get("maxWaitSeconds")) or 300),
                             late=(lambda item, reply: _late_reply(ctx, item, reply, late)))
    except Exception:
        base.log_exc("handle")
        return None


def _late_reply(ctx, item, reply, send):
    """后台算完了、前台早走了 —— 由这里把这条**迟到的话**发出去。

    三条硬要求（用户 2026-10-02 定的）：

      ① **绝不发两遍**：发送权在 `item` 上认领（`is_sent()` / `mark_sent()`），
         前台要是已经发过了，这里直接退回去 —— 靠的是明确的标记，不是猜。
      ② **不加任何固定台词**（"我还在想"那种）—— 用户看到的每一句话都由模型组织；
         这里只管把模型算出来的那句话送出去，一个字都不加。
      ③ **纯日志**记一笔：这条迟到几秒、补发了。日志不进模型。
    """
    text = (reply or "").strip() if isinstance(reply, str) else ""
    if item.is_sent():
        base.log("后台算完了，但前台已经替她发过了 —— 不重复发（这条到此为止）")
        return
    if not text:
        # 空 = 她决定不说话（`end_turn` 收尾时 `run_turn` 返回的就是空串）——
        # 后台也不许硬发一句。
        item.mark_sent("")           # 认领掉：这条到此为止，别再有第二个人发
        base.log("后台算完了：这句话是空的，不补发（她本来就没打算说）")
        return
    if not callable(send):
        # 没给发送回调（比如自检里直接调 handle）：认领掉，别让它悬着。
        item.mark_sent("")
        base.log("后台算完了，但没有发送回调 —— 这条发不出去（只会出现在自检里）")
        return
    # **全项目唯一一处补发**：认领成功才发（认领不到就说明别人已经发过了）。
    if item.mark_sent(memory.LATE):
        delay = time.time() - (item.async_at or time.time())
        base.log("这条迟到 %.1f 秒，补发了：%s" % (delay, text[:80]))
        send(ctx, text)


def _think(ctx, addressed):
    """真正"想"这一步：拼消息 → 模型（可调工具）→ 兜底 → 产出她说的话。

    ⚠️ 这里跑在 memory 的串行 worker 里：同一场对话严格先来先服务。
    """
    key = ctx["key"]
    msgs, img = _build(ctx, addressed)
    text, called, err = llm.run_turn(msgs, ctx)
    if err:
        base.log("这一轮没答上来：%s" % err)
        # 用户 2026-10-30 定：**只有超时**才说一句（别的错不吭声，免得瞎报）。
        if "超时" in err or "掐断" in err:
            return _timeout_reply(ctx, err)
        return None

    text, removed = guards.strip_monologue(text)
    text = guards.strip_echo(text)
    if removed:
        base.log("削掉一段内心独白：%s" % removed)

    # 说做了其实没做 → 给她一次改口的机会（把真相递回去，措辞还是她自己的）
    #
    # ⚠️ extra：她手上有这个人的唤醒，就说不上是"谎报提醒"（实测的误报就这一种）。
    extra = ()
    try:
        uid = str(ctx.get("user_id") or "")
        if any(str(i.get("user_id")) == uid or str(i.get("where_qq") or "") == uid
               for i in reminders.pending()):
            extra = ("wake",)
    except Exception:
        pass
    lies = guards.find_lies(text, called, images_ok=img["ok"], extra=extra,
                            user_text=ctx.get("text") or "")
    if lies:
        base.log("这一轮有说法没兑现（%s），让她重说一遍" % "、".join(l["kind"] for l in lies))
        text = _second_chance(ctx, msgs, text, lies, extra)

    if not text:
        # 她自己选择不说（end_turn / 模型直接留空）→ 不发 ✓（用户 2026-10-30 定的）
        base.log("她选择不说话")
        return None

    # ⚠️ 2026-10-04：这里**原来有一处硬截断** ——
    #       `cap = agent.maxGroupReplyChars`（800），超了就 `text[:cap] + "…"`，
    #       **多出来的字直接丢掉**。真机上真丢过：18:18:18 那条 1020 字的回复
    #       被截到 800（日志原文「群里这条太长了（1020 字），截到 800」），220 个字没了。
    #    用户拍板「干脆别截断。自动切自动发」→ 截断**删掉**，改由发送那一层
    #    （`im.send_long` → `chunker.py`）按上限自动拆成几条**依次发**。
    #    ⚠️ 为什么放在发送层而不是这里：出口有四个（她的话 / 提醒 / 播报 / 主动插话），
    #       放在发送层才是**一处实现、多处复用**，不可能有一处偷偷截掉。
    #    ⚠️ 记进对话线程的是**完整的原话**（她说过的就是这些字，一个字不少）。
    memory.record(key, "assistant", text)
    return text


def _timeout_reply(ctx, err=""):
    """卡住/超时/出错时的兜底一句话（2026-10-30 用户要求：**最后必须有个回复**）。

    ⚠️ 只在"她该说话"的场合补：
       · 触发词 / 随机接话 → 本来就可以不吭声，不补 ✗
       · 这一轮她已经用 `say` 说过话 → 不补（免得接一句莫名其妙的话）✗
       · 其余（@她 / 叫名字 / 私聊 / 唤醒 / 播报）→ 补 ✓
    ⚠️ 这句**不进 LLM 请求**（是固定文案，不是模型说的），改起来零风险 ✓
    """
    try:
        if str(ctx.get("_trigger") or "") in ("触发词", "chime"):
            return None
        if int(ctx.get("_sends") or 0) >= 1:
            return None
    except Exception:
        pass
    line = "刚才超时了，等下再叫我一遍"
    base.log("超时，说了一句：%s（原因：%s）" % (line, (err or "空回复")[:60]))
    try:
        memory.record(ctx.get("key") or ("p", ctx.get("user_id")), "assistant", line)
    except Exception:
        pass
    return line


def _second_chance(ctx, msgs, text, lies, extra=()):
    """把"你没做"这个事实递回去，让她用自己的话重说（最多一次）。

    这就是 DSH 的 turn-stopping 那个套路：轮次要关的时候，把"数据上对不上"的事实
    作为一条新消息塞回去，让机器再跑一步 —— 决定权还在模型手里，措辞还是她自己的。

    ⚠️ 兜底顺序是有讲究的（实测踩过）：纠正轮如果她干脆不出声、或者模型抽风返回空，
       **绝不能就这么算了** —— 用户那边看到的是"她突然不吭声"，会以为她坏了。
       所以先"把那句没兑现的删掉、剩下的照发"；如果删完什么都不剩，
       宁可把原话发出去（日志会记下这笔账），也别让她凭空消失。
    """
    if text.strip():
        msgs.append({"role": "assistant", "content": text})
    # ⚠️ 这条"更正"必须是 **user** 角色，不能留成 system：
    #    实测思考模式下，最后一条是 system 会被 DeepSeek 400 掉
    #    （"The reasoning_content in the thinking mode must be passed back to the API."）。
    #    包一层 <system-reminder>（DSH 注入 AGENTS.md/技能目录用的就是这个信封），
    #    免得她把它当成"某个人在说话"。
    msgs.append({"role": "user", "content": guards.system_reminder(
        "补充事实：%s "
        "把那句处理掉：真的调工具办掉，或者改成实话、删掉；"
        "其余照原样，别换话题。"
        % " ".join(l["事实"] for l in lies))})
    text2, called2, err = llm.run_turn(msgs, ctx)
    if err:
        base.log("纠正轮没跑起来（%s），把原话里那句删掉再发" % err)
        return guards.drop_lies(text, lies) or text
    text2, _ = guards.strip_monologue(text2)
    text2 = guards.strip_echo(text2)
    if not text2:
        base.log("纠正轮她没出声 —— 把原话里那句没兑现的删掉，剩下的照发")
        return guards.drop_lies(text, lies) or text
    still = guards.find_lies(text2, called2, images_ok=True, extra=extra,
                             user_text=ctx.get("text") or "")
    if still:
        base.log("她还是没改口，把那句删掉")
        return guards.drop_lies(text2, still) or text2
    return text2


# ── 拼这一轮的消息 ──────────────────────────────────────────────────

def _build(ctx, addressed):
    """返回 (messages, {"ok": bool, "note": str})。

    ⚠️ 顺序就是契约（2026-10-30 A2 定的）：**system（只有性格）→（技能目录）→ 历史
       → user 快照 → 当前这句**。最后一条**必须**是他的原话本身，任何说明/补充都
       不能贴在那句话前面。

    ⚠️ 2026-10-31（扩展包 / 知识锁）：system 之后多一条**技能目录**（独立的 user 消息，
       只有至少一个技能可用时才发；内容变了原地替换那一条，⛔ 不是每轮追加）。
       它排在历史之前、位置固定 —— 请求开头仍然逐字稳定（前缀缓存照吃）。

    ⚠️ 2026-09-26：以前只发一条 system、放在历史之后（"最后一条 system"会被接口
       当成整份系统提示词）。2026-10-30 A2 改成 **system 放最前面、场合事实单独走
       一条 user 快照** —— 目标是请求开头逐字稳定（前缀缓存），场合那几行的字一个
       没改、只是换了位置和角色（用户逐字批的）。⛔ 别再拼回 system 末尾。

    ⚠️ 2026-10-09：这份 messages 是给**第 1 次请求**的（历史照旧在，该有上下文）。
       她可能就在这次里自己决定调 `pc_status` —— 那条路的**第 2 次请求**会把这里的
       历史砍掉，只留「system + 快照 + 当前那句 + 她自己的 tool 往返」（口径与理由见
       `llm.run_turn` 上面 `PC_TRIM_TOOLS` 那一段）。⛔ 只有 `pc_status` 这么办。
       ⚠️ 这里把历史那一段的下标记进 `ctx["_hist_range"]`（C-3：按本轮边界切）。
       ⚠️ 技能目录那一条在 `_hist_range` **之外**（切历史时它留着，和 system 一样）。
    """
    msgs = [{"role": "system", "content": persona.system_prompt()}]
    # ⭐ 2026-10-31（扩展包 / 知识锁）：**技能目录**是一条独立的 user 消息 ——
    #    位置固定：system 之后、历史之前；只有至少一个技能可用时才发。
    #    ⚠️ 「内容变了就原地替换那一条」由 `capabilities.catalog_message(ctx)` 保证
    #       （按会话缓存同一个 dict，内容变了只改 content）—— 所以请求里永远只有一条，
    #       ⛔ 不是每轮追加一条。位置固定也顺便让请求开头逐字稳定（前缀缓存）。
    _cat = capabilities.catalog_message(ctx)
    if _cat is not None:
        msgs.append(_cat)
    hist = list(memory.render(ctx["key"], drop_last=True))     # 历史（当前这条要单独拼，可能要带图）
    _hist_at = 1 + (1 if _cat is not None else 0)
    # ⭐ 2026-10-30（B1，用户批的第 13 条）：**群聊**先在历史之前告诉她一句
    #    「你看到的是这个群最近 N 条消息」；私聊一个字都不加。
    #    ⚠️ 插在历史之前、system 之后 —— 位置固定、N 也固定（threadLimit 那段窗口），
    #       所以请求开头仍然逐字稳定（前缀缓存照吃）。
    if ctx.get("is_group") and hist:
        msgs.append({"role": "user",
                     "content": "你看到的是这个群最近 %d 条消息" % len(hist)})
        _hist_at += 1
    msgs.extend(hist)
    # C-3：本轮历史段（半开区间）。`pc_status` 的续问只砍这一段 —— system 在最前面，
    # ⛔ 不能再按"最后一条 system"切（那会把 system 自己切掉 / 切出非法序列）。
    ctx["_hist_range"] = (_hist_at, _hist_at + len(hist))

    refs = images.refs_of(ctx)
    parts, note = images.load(refs) if refs else ([], "")

    # 引用（回复）里带过来的图和那句话：他引用了一条带图的老消息时，把那条里的
    # 图**也挂到这一轮**、并附一句事实（用户 2026-09-30 逐字批的，动机见 images.py）。
    # ⚠️ 单独一条路：**图失败静默** —— 所以它不并进上面那个 `load()`（那个拿不到图
    #    会回一句「这条消息带了 N 张图…」）。
    # ⚠️ 顺序：他自己这条的图在前 → 那句「他引用的那条是…」→ 引用的那张图。
    qparts, qnote = images.load_quoted(ctx)
    if qnote:
        parts.append({"type": "text", "text": qnote})
    parts = parts + qparts

    # 文件（群文件 / 私聊文件 / 引用里带的文件）：**只认事实**，正文里仍然是
    # `[文件]` 占位；这一句告诉她"带了哪个文件"。真正取到本地是 `package` 的 fetch。
    # ⚠️ 和图片那条路同一个口径：当前这条 + 引用那条都算；取不到就只是没有这一句。
    _frefs = files.all_refs(ctx)
    if isinstance(ctx, dict):
        ctx["files_all"] = _frefs
    fnote = files.note(ctx)

    # ⭐ 运行时场合事实：**单独一条 user 消息**（纯 user、不套信封，C-1/C-2）。
    #    字一个没改 —— 就是以前拼在 system 末尾的那几行（`_occasion` 原样搬过来）。
    msgs.append({"role": "user", "content": _occasion(ctx, addressed, note, fnote)})

    # ⚠️ 2026-10-06（用户拍板）：前缀格式 = **`名字: `** ——
    #    「称呼 → 本群名片 → 昵称 → QQ 号」四级降级（`memory.display_name`），
    #    ⛔ 以前那截 `[群名片:X]` 整条去掉了。这里把当前事件的 `sender.card`
    #    传进去（当下那张最新），没带就退到记忆里**这个群**那张。
    _snd = (ctx.get("evt") or {}).get("sender") or {}
    line = "%s: %s" % (memory.display_name(ctx.get("user_id"), bool(ctx.get("is_group")),
                                           card_now=(_snd.get("card") or ""),
                                           group_id=ctx.get("group_id")),
                       (ctx.get("text") or "").strip())
    if parts:
        # 文字在前、图在后（跟人一样：先看问题再看图）
        msgs.append({"role": "user", "content": [{"type": "text", "text": line}] + parts})
    else:
        msgs.append({"role": "user", "content": line})
    return msgs, {"ok": not note, "note": note}


# 收尾工具（`end_turn`）的场合说明 —— **只在触发的这两种场合**加（用户 2026-10-30 逐字定稿）：
#   · 关键词触发 → 先告诉她是**哪个词**勾的、并不是有人在叫她（第 40 条，逐字；
#     `%s` = 撞上的那个触发词本身，`_why` 记在 `ctx["_trigger_word"]`）；
#   · 随机接话（1%）→ 小概率自动接话（第 41 条，逐字；⚠️ **结尾有句号**，别漏）。
# ⛔ @/叫名字/私聊、到点唤醒、播报：一句都不加（用户拍板，别自己补）。
# ⚠️ end_turn 进不进工具目录不靠这两句，靠 `ctx["_trigger"]`（见 `toolkit.schemas(ctx)`）；
#    这两句只是让她知道"为什么忽然轮到我"。
# ⚠️ 原来那版是"不需要就回某个哨兵词"，第 42 条已经把那套**彻底删掉** —— 别再搬回来。
TRIGGER_END_TURN_NOTE = ("刚才对话的「%s」触发了关键词的自动接话功能，并不是有人叫你。"
                         "不需要回就调 end_turn。")
CHIME_END_TURN_NOTE = ("触发了小概率的自动接话功能，并不是有人叫你。不需要回就调 end_turn。")


def _occasion(ctx, addressed, img_note="", file_note=""):
    """这一轮的场合事实（**只写事实，不写规矩**）。

    ⚠️ 这里**不放**任何"关于某个人的长期信息"（他住哪、是谁、喜欢什么）——
       那些在长期记忆库里，她要用的自己调 `memory` 那个工具去取。
       常驻的附加消息越多，她的注意力越容易被背景占着（用户点名要的精简）。
       唯一常驻的是**称呼**，而且它是长在消息前缀里的（`名字（QQ 号）:`），
       属于结构，不是附加消息。
    """
    n = clock.now()
    # ⚠️ 2026-09-27 用户点名的：**不告诉她时间**（"需要时 llm 会自己调用工具"）——
    #    要时间她会调 now 工具。所以这一段只剩"在哪儿、跟谁说话"。
    out = []
    if ctx.get("is_group"):
        # ⚠️ 不告诉她自己的 QQ 号（用户点名去掉的）：那是"关于她自己"的附加消息，
        #    跟场合没关系，她也不需要 —— 少一条就少分一点注意力。
        # 名字用 display_name（跟消息前缀同一套），另外**带上 QQ 号** ——
        # 这一行是"事实"，她真要调工具（memory 查谁、私聊谁）得知道用哪个号。
        # 2026-09-27 用户改的：说话人**前缀里已经写了**（称呼/QQ + 群名片），
        # 这句不再复述，只留"在哪个群"—— 而且带上群名（查一次、缓存在 group-names.json）。
        _gname = im.group_name(ctx.get("group_id"))
        out.append("在 QQ 群 %s（群名 %s）" % (ctx.get("group_id"), _gname) if _gname
                   else "在 QQ 群 %s" % ctx.get("group_id"))
    else:
        # 2026-09-27 用户改的：这是你与<称呼或QQ号>的私聊（不再重复 QQ 号）
        out.append("这是你与 %s 的私聊"
                   % memory.display_name(ctx.get("user_id"), False))
    if img_note:
        out.append(img_note)
    if file_note:
        out.append(file_note)
    if addressed == "触发词":
        # 第 40 条：`%s` = 撞上的那个触发词本身（`_why` 记在 ctx 里）。
        # 兜底：没有记录就现扫一遍（只有测试会直接拿 "触发词" 调这个函数）。
        w = (ctx.get("_trigger_word") or "").strip()
        if not w:
            _t = (ctx.get("text") or "").strip().lstrip("，,。!！?？~～ \u3000")
            w = next((x for x in persona.trigger_words() if x and x in _t), "")
        out.append(TRIGGER_END_TURN_NOTE % w)
    elif not addressed:
        # 第 41 条：没点她、1% 掷到了才算"随机接话"。
        # ⚠️ 用户给的新版**结尾有句号**（旧版没有），照新的写。
        out.append(CHIME_END_TURN_NOTE)
    # ⭐ 2026-10-30（`plan`，用户批的第 10 条第 (3) 块）：只要她的计划里还有没做完的步骤，
    #    就把**整张表**附在快照末尾（「计划：<目标>」+ 每步一行「1. 内容 — 状态」）。
    #    ⛔ 没有计划 / 全部完成 → `plan.table()` 给空串，一个字都不加。
    #    ⚠️ 唤醒到点那一轮也走这里（`_on_due` 也调这个函数），所以那边天然也带整张表。
    _tbl = plan.table((ctx or {}).get("key"))
    if _tbl:
        out.append(_tbl)
    return "\n".join(out)


# ── 该不该搭话 ──────────────────────────────────────────────────────

_PING = {"ping", "在吗", "在么", "在不在", "还在吗", "还在不在", "活着吗", "活着没",
         "活了吗", "在", "在嘛"}


def _is_ping(text):
    """**整条消息就是**判活词才算（后面还带别的话 = 他有正事要说，交给模型）。

    这是刻意做窄的：v1 后期把命令层砍到只剩 ping，就是因为关键词拦截截掉了
    「她本该理解」的话。除判活这类零成本动作，其余全交给模型。
    """
    t = (text or "").strip().strip("。？！.!?~～ \u3000")
    return t.lower() in _PING


def _in_scope(ctx):
    """她理不理这个群。

    ⚠️ 2026-10-03（互联网改造那一批，契约 B5）：范围 = **全局 `bot.groups` ∪
       每个用户登记的 `群`** —— 朋友把自己的群拉进来、又给了主人一条码，
       她要是在那个群里一声不吭，用户只会以为"坏了"。
    ⚠️ 2026-10-04（「群管理」那一批）：**再并上 `groups.json`**（手机本地那份，
       面板上增删的就是它，deploy 永不覆盖）。三份并集只有一个取数点 ——
       `groups.known()`，谁也别再自己去读 `config.json` 的 `bot.groups`（各读各的必然飘）。
       加/删那个文件**立刻就生效**：它按 mtime 热重载，不用重启她。
       只决定"理不理这个群"，**不决定要不要被 @**（那一条行为没变）。
    """
    if ctx.get("is_group"):
        return groups.in_scope(ctx.get("group_id"))
    return True


# 触发词限流用的上次因为触发词接话是什么时候，键 = 对话的 key（群号那种）。
# 只活在内存里：重启就清空（重启本来就是重新开始的意思）。
_TRIG_AT = {}


def _why(ctx):
    """她该搭话吗、**为什么**：返回 "私聊" / "at" / "名字" / "触发词" / ""（空 = 不搭）。

    ⚠️ 三种唤她的方式**强度不同**（用户 2026-09-27 定）：
       · 私聊 / 被 @ / 名字别名 —— 那是**被人点名**，每次都答，不限流；
       · **触发词** —— 只管"把话递给她"（话题词撞上了），所以**要限流**
         （`agent.triggerCooldownSeconds`，默认 30 秒一次），不然群里聊到那个词
         她就一次一次接，既吵又烧模型 ✗。
    ⚠️ 她自己发的消息在 `handle()` 最前面就被扔了（发信人 == 她自己）—— 所以
       她自己说的话里带触发词**不会**把自己勾起来 ✗（防自问自答打转）。
    """
    ctx.pop("_trigger_word", None)        # 第 40 条：上一轮的词别留到这一轮
    ctx.pop("_trigger", None)             # 同理：这一轮的场合由下面重新判
    if not ctx.get("is_group"):
        return "私聊"
    raw = ctx.get("raw") or ""
    if "[CQ:at,qq=%d]" % base.self_id() in raw:
        return "at"
    t = (ctx.get("text") or "").strip().lstrip("，,。!！?？~～ \u3000")
    for w in persona.call_names():
        if w and t.startswith(w):
            return "名字"
    # 第 40 条：记下**是哪个触发词**勾的她（`_occasion` 填那句说明要用），
    # 同时把场合标进 `ctx["_trigger"]` —— `toolkit.schemas(ctx)` 靠它决定给不给 end_turn。
    for w in persona.trigger_words():
        if w and w in t:
            ctx["_trigger_word"] = w
            ctx["_trigger"] = "触发词"
            return "触发词"
    return ""


def _addressed(ctx):
    """她该搭话吗（私聊 / 被 @ / 叫名字 / 撞上触发词）。判定理由见 `_why`。"""
    return bool(_why(ctx))


def _chime_ok(ctx):
    """没叫她时要不要"自己接一句"。概率很小、间隔很长，接不接由模型自己定。"""
    if not ctx.get("is_group"):
        return False
    c = ((base.cfg().get("agent") or {}).get("chimeIn") or {})
    if not c.get("enabled"):
        return False
    p = float(c.get("chancePercent") or 1) / 100.0
    if random.random() >= p:
        return False
    key = ctx["key"]
    now = time.time()
    with _LOCK:
        st = _CHIME.setdefault(key, {"last": 0, "times": []})
        if now - st["last"] < float(c.get("minGapSeconds") or 1800):
            return False
        st["times"] = [t for t in st["times"] if now - t < 3600]
        if len(st["times"]) >= int(c.get("maxPerHour") or 3):
            return False
        st["last"] = now
        st["times"].append(now)
    base.log("这次没人点她，掷到了那 %g%% —— 让模型自己决定接不接" % (p * 100))
    return True


def _call(ctx):
    """他在她这儿叫什么 —— 规则在 memory.call_name()：

        群聊：定的称呼 > 群名片 > QQ 号
        私聊：定的称呼 > 昵称 > QQ 号
    """
    return memory.call_name(ctx)


# ── 唤醒到点：把她叫醒，话由她说 ────────────────────────────────────

# ⭐ 2026-10-30（A7′ / 第 43、44 条）：到点那一轮要把「设这个唤醒那一刻」的现场带上。
# 这两句是用户**逐字批的**，⛔ 一个字都不许改（第二句那个 `%s` 是摘要本身）。
WAKE_HIST_HEAD = "以下是设这个唤醒之前的对话"
WAKE_DIGEST_HEAD = "你当时查到的数据：%s"
# 账本里的 `hist` 是字符串数组（⛔ 老记录没有这个键）—— 行首带「名字: 」的是他说的，
# 没带的（以及 `hist` 之外的）按她自己的话还原。⛔ 别把她的旧话当 user 递回去。
_HIST_WHO = re.compile(r"^[^：:\n]{1,40}: ")


def _hist_role(line):
    s = line or ""
    if s.startswith("<compacted-summary>"):
        return "user"                   # 私聊压缩摘要也是"递给她的一段材料"，不是她说的
    return "user" if _HIST_WHO.match(s) else "assistant"


def _wake_ctx(rec):
    """这一轮唤醒的 ctx（`where_qq` 填了 = 醒来私聊那个人，否则就在当初那个会话）。

    ⚠️ A6 安全阀：把**这条唤醒在链里是第几层**放进 `ctx["_wake_depth"]` ——
       `wake` 工具在这一轮里再设新唤醒时会接着往下数，第 4 层直接拒。
    """
    try:
        depth = max(1, int(rec.get("depth") or 1))
    except Exception:
        depth = 1
    where_qq = str(rec.get("where_qq") or "")
    if where_qq:
        key = ("p", where_qq)
        return {"key": key, "is_group": False, "group_id": None, "user_id": where_qq,
                "who": rec.get("where_name") or where_qq, "text": "", "raw": "",
                "images": [], "files": [], "message_id": None, "at": time.time(),
                # 唤醒到点那一轮：`toolkit.schemas(ctx)` 靠它把 end_turn 放进目录。
                "_trigger": "wake",
                "_wake_depth": depth}
    gid = rec.get("group_id")
    key = tuple(rec["key"]) if rec.get("key") else (
        ("g", gid) if gid else ("p", rec.get("user_id")))
    return {"key": key, "is_group": bool(gid), "group_id": gid,
            "user_id": rec.get("user_id"), "who": rec.get("who"),
            "text": "", "raw": "", "images": [], "files": [], "message_id": None,
            "at": time.time(),
            "_trigger": "wake",
            "_wake_depth": depth}


def _on_due(rec):
    """到点了：把她叫醒。**话由她说，说不说也由她定**。

    ⚠️ 这一轮的形状是用户 2026-10-30 定死的（A7′ / 第 43、44 条）：

        [system: 性格]
        [user: 以下是设这个唤醒之前的对话]      ← 只有那 6 段在时才有
        [那 6 段对话，原样当历史]
        [user: 你当时查到的数据：…]            ← 只有 digest 非空时才有
        [user: 快照] + [user: 到点那段]

    ⭐ 目标：到点那一轮 = **那场对话的下一轮**（用的是**设唤醒那一刻**冻结下来的现场）。
    ⛔ 设完之后新聊的一句都不带（账本里存的就是那一刻的快照）；
    ⛔ 老记录（没有 `hist` / `digest`）→ 还是 快照 + 到点那段，一个字都不多；
    ✓ 允许调工具、允许多步；✓ 允许她调 `end_turn` 收尾（什么都不说，这次就算了）；
    ⛔ 不 @ 谁；发在当初那个会话（`where` 填了人 → 私聊那个人）。

    ⚠️ 为什么最后一条是 `user` 而不是 `system`：实测思考模式下最后一条留成 system
       会被 DeepSeek 直接 400（「The reasoning_content in the thinking mode must be
       passed back to the API.」），唤醒就永远发不出去。
    ⚠️ 到点那段话本身已经是 `<system-reminder>` 信封（`reminders.wake_note`），
       ⛔ 别再包一层。
    ⚠️ 2026-10-31（扩展包）：这一轮**不发技能目录** —— 它重放的是"设唤醒那一刻"的
       冻结现场，不是一场新对话；技能（`skill` 工具）照旧能读，解锁也照旧记在那个
       会话身上。主对话那条路才由 `_build` 每轮把目录放在 system 之后。
    """
    ctx = _wake_ctx(rec)
    key = ctx.get("key")
    # 唤醒到点这一轮也把**整张计划表**带上（第 10 条：有没做完的计划就附整张表）。
    # `_occasion` 自己会拼 `plan.table()`，这儿只要给它一个"点过她"的场合。
    msgs = [{"role": "system", "content": persona.system_prompt()}]
    # ⭐ A7′：「设这个唤醒那一刻」的现场（老记录没有这两个键 → 当空，⛔ 什么都不加）。
    _hist = rec.get("hist")
    if not isinstance(_hist, (list, tuple)):
        _hist = []                                   # 老记录 / 写坏了的 → 当空
    hist = [str(x) for x in _hist if isinstance(x, str) and x.strip()][:6]
    if hist:
        msgs.append({"role": "user", "content": WAKE_HIST_HEAD})
        for line in hist:
            msgs.append({"role": _hist_role(line), "content": line})
    digest = str(rec.get("digest") or "").strip()[:600]
    if digest:
        msgs.append({"role": "user", "content": WAKE_DIGEST_HEAD % digest})
    msgs.append({"role": "user", "content": _occasion(ctx, "唤醒")})
    msgs.append({"role": "user", "content": reminders.wake_note(rec)})

    text, called, err = llm.run_turn(msgs, ctx)
    if err:
        base.log("唤醒到点但模型没答上来：%s" % err)
        return
    text, _ = guards.strip_monologue(text)
    text = guards.strip_echo(text)
    if not text:
        # 2026-10-30（A5-5 / C-8）：以前这里会再逼一次（「……到点了必须说出去」）——
        # 那句连同"再逼一次"的整块**删掉了**：唤醒这一轮允许她用 `end_turn` 收尾
        # （`run_turn` 返回空串），不再逼（用户批的）。
        base.log("到点了，她选择不说（#%s）—— 这次就算了" % rec.get("id"))
        return
    lies = guards.find_lies(text, called, images_ok=True)
    if lies:
        text = guards.drop_lies(text, lies)
        if not text:
            return
    # 发在哪：`where` 填了人 → 私聊他；否则回到当初那个会话（群里 **不 @ 人**）。
    # ⚠️ 出口还是 `im.send_group / send_private`（太长自动拆、一个字都不丢）。
    gid, uid = rec.get("group_id"), rec.get("user_id")
    where_qq = str(rec.get("where_qq") or "")
    if where_qq:
        ok = im.send_private(int(where_qq) if where_qq.isdigit() else where_qq, text)
    elif gid:
        ok = im.send_group(gid, text)
    else:
        ok = im.send_private(uid, text)
    base.log("唤醒 #%s 说出口了（%s，%s）：%s"
             % (rec.get("id"), "成了" if ok else "发送没成功",
                reminders.where_text(rec), text[:60]))
    if key:
        memory.record(key, "assistant", text)


# ── notice 事件（典型：有人戳她）────────────────────────────────────

def on_notice(evt):
    """别人戳她 → 戳回去（只要动作，不用说话）。"""
    try:
        nt = evt.get("notice_type")
        sub = evt.get("sub_type")
        if nt == "notify" and sub == "poke":
            uid = str(evt.get("user_id") or "")
            gid = evt.get("group_id")
            if str(evt.get("target_id") or "") != str(base.self_id()) or uid == str(base.self_id()):
                return None                        # 不是戳她，或者她自己戳的
            c = ((base.cfg().get("agent") or {}).get("pokeBack") or {})
            if not c.get("enabled", True) or not gid:
                base.log("有人戳她（%s）" % uid)
                return None
            now = time.time()
            with _LOCK:
                if now - _POKE.get(uid, 0) < float(c.get("minGapSeconds") or 20):
                    return None
                _POKE[uid] = now
            im.poke(gid, int(uid) if uid.isdigit() else uid)
            base.log("他戳她，她戳回去（群 %s / QQ %s）" % (gid, uid))
            return None
        base.log("收到一种没处理的 notice：%s / %s" % (nt, sub))
    except Exception:
        base.log_exc("on_notice")
    return None


# ── request 事件（好友申请 / 群邀请）——**只入库排队，等面板裁决**────────
#
# 用户 2026-10-04 第二批点名改的（原话）：「可以运行加群的话，可以允许通过好友申请吗？
# 不过不要自动通过，而是把申请放到网页面板上，我决定拒绝还是通过还是忽略。然后加群
# 也改成那样。」—— 所以这一段的语义整个换了：
#
#   以前：群邀请 **自动同意**（`bot.autoAcceptGroupInvite` 默认 true）；
#         好友申请**只写一行日志、零动作**。
#   现在：**两样都只入库**（`requests.json` → `reqs.add`），一个动作都不发；
#         用户在面板上裁决（`request.approve` / `request.reject` / `request.ignore`，
#         只有主人能调，见 `_request_api`）。
#
# 三条纪律（照旧，用户定的）：
#   ① **记一笔但不加白名单**：群邀请那个群照样写进「最近见过的群」（面板上他点一下
#      就能加）；⛔ **不许顺手加进 groups.json** —— 加白名单 = 她开始收那个群的消息，
#      这必须是**用户自己**在面板上的动作。
#   ② 老开关 `bot.autoAcceptGroupInvite` **留着**（以后想自动还能开）—— 但**默认关**：
#      开着才自动同意（同时照样入库，状态直接记「已通过」，面板上看得见）。
#   ③ 整段包 try：出任何事只写日志，**绝不影响别的消息处理**。
#
# ⚠️ 事件里只取**该取的那几个字段**：号 / `flag` / `验证消息`（`comment`）。
#    `验证消息`是**申请人写的话**，它进 `requests.json` **只给用户自己在面板上看**
#    （⛔ 不进给模型看的任何文本、不进日志）；`sender` 那些一律不落盘。

def _auto_accept_invite():
    """`bot.autoAcceptGroupInvite` —— 朋友拉她进群时**要不要直接同意**。

    ⚠️ 2026-10-04 第二批改的：**默认 false**。从这一批起，群邀请和好友申请一样
       **进面板排队等用户裁决**；这颗键留着只是"以后还想让它自动同意"（用户点名：
       「键留着，以后想自动还能开」）。开着 = 收到邀请立刻同意，同时照样入库、
       状态直接记「已通过」（面板上看得到是谁什么时候拉的）。
    ⚠️ 只认**真正的布尔 `true`**（和 `bot.control.allowPublic` 一个口径）：
       键不在 / 写成 `"true"` / `1` 这种**一律当不自动** —— 错的那一头必须是
       "等用户点"，不能是"替用户点了同意"。
    """
    return base.bot_cfg().get("autoAcceptGroupInvite") is True


def on_request(evt):
    """NapCat 报了一条「请求」——**好友申请 + 群邀请都只入库排队**，一个动作都不发。

    裁决在面板上（`request.approve` / `request.reject` / `request.ignore`）。
    ⚠️ `flag` 是**一次性凭据**：只落 `requests.json`（手机本地，deploy 的 NEVER），
       ⛔ 日志里只说"有 / 没有"，绝不打它的值（老规矩，见 im.set_group_add_request）。
    """
    try:
        rt = str(evt.get("request_type") or "")
        sub = str(evt.get("sub_type") or "")
        flag = str(evt.get("flag") or "").strip()
        uid = str(evt.get("user_id") or "")
        gid = evt.get("group_id")
        comment = evt.get("comment") or ""

        if rt == "friend":
            # ── 好友申请（以前只写一行日志、什么都不做）→ 入库排队 ──
            name = im.stranger_name(uid)          # 失败留空、绝不报错（每人只问一次）
            ok, msg, _rec = reqs.add(reqs.FRIEND, qq=uid, name=name,
                                     comment=comment, flag=flag)
            if not ok:
                base.log("申请队列：好友申请（QQ %s）没收下：%s" % (uid or "?", msg))
                return None
            base.log("申请队列：%s（QQ %s%s；flag %s）—— 等面板裁决"
                     % (msg, uid or "?", ("，名字 " + name) if name else "",
                        "有" if flag else "**没有**（面板办不了，得用户自己在 QQ 里点）"))
            return None

        if rt == "group" and sub == "invite":
            # ── 群邀请（以前自动同意）→ 记一笔见过的群 + 入库排队 ──
            # 先把群记进「最近见过的群」（面板上才冒得出来，用户不可能去 QQ 里翻群号）。
            # ⚠️ 这一笔**不看开关**：开关/排队怎样都要记 —— 否则他连"有这么一个群"都不知道。
            # ⚠️ 顺手把群名问一次（`groups.name_of(lookup=True)` 自带两级缓存，只问一次），
            #    问到的名字同时喂给「最近见过的群」和申请记录，面板上显示名字而不是一串数字。
            name = groups.name_of(gid, lookup=True) or ""
            groups.see(gid, inviter=uid, name=name)
            ok, msg, rec = reqs.add(reqs.GROUP, qq=uid, group=gid, name=name,
                                    comment=comment, flag=flag)
            if not ok:
                base.log("申请队列：群邀请（群 %s，邀请人 %s）没收下：%s" % (gid, uid, msg))
                return None

            if _auto_accept_invite():
                # 老开关开着才自动同意（默认关，见 `_auto_accept_invite`）。
                ok2, why = im.set_group_add_request(flag, approve=True, sub_type="invite") \
                    if flag else (False, "事件里没有 flag")
                if ok2:
                    reqs.finish(rec["id"], reqs.APPROVED,
                                "自动同意（config.json 的 bot.autoAcceptGroupInvite 开着）")
                    base.log("申请队列：群邀请（群 %s，邀请人 %s）按 bot.autoAcceptGroupInvite "
                             "自动同意了（记录标成已通过）" % (gid, uid))
                else:
                    base.log("申请队列：群邀请（群 %s，邀请人 %s）想自动同意但没成（%s）"
                             "—— 记录留在待处理，等面板裁决" % (gid, uid, why))
                return None

            base.log("申请队列：%s（群 %s，邀请人 %s%s；flag %s）—— 没自动同意"
                     "（bot.autoAcceptGroupInvite 关着），等面板裁决"
                     % (msg, gid, uid, ("，群名 " + name) if name else "",
                        "有" if flag else "**没有**（面板办不了，得用户自己在 QQ 里点）"))
            return None

        # 加好友那种之外、别的形状的 request（典型：`group / add` = 别人申请加她的群）：
        # **不做任何动作**，只留一行痕（和 notice 那条一个口径：照原样打那两个字段）
        base.log("收到一种没处理的 request：%s / %s"
                 % (evt.get("request_type"), evt.get("sub_type")))
        return None
    except Exception:
        base.log_exc("on_request")
    return None


# ── 控制面：App / 网页面板 ──────────────────────────────────────────

def _announce(req, ident=None):
    """电脑上的 PCStatus 拦截到摸鱼 → 把**事实**递过来，让**她说**那句播报。

    ⚠️ 这是唯一一条"外部程序让她开口"的入口，守的规矩和提醒到点一样：
       电脑给的必须是**事实**（谁、什么应用、摸了多久、被做了什么），措辞由她组织。
       ⚠️ 2026-09-27 用户明确要求：**不要把电脑拼好的模板句子当材料塞给她** ——
          材料只由 `facts`（结构化键值）拼成；`title`/`body` 只留作"她不肯说时的兜底原文"，
          **不进她的材料**（她看不到那两句现成台词）。
          兼容老版本电脑：万一它只给了 title/body 没给 facts，那才拿它们当材料（总比空着强）。

    ⚠️ 兜底：她要是不想说（空文本；播报这一轮**不带** `end_turn`），就把电脑给的原文照发 ——
        播报宁可"是她没润色过的原文"，也不能因为她在发呆就丢了（这套播报本来就是 v1
        直发 NapCat 的内容）。

    ⚠️ 2026-10-03（第三批）：电脑的播报载荷**顶层多了一个 `UTC偏移`**（`±HH:mm`、恒有、
       写在 `facts` 之后，见 `规格-多电脑接入.md` §4.1 与 `答复-第三批.md` §6.1）。
       `facts{人,群,数据[]}` 那套形状**一个字节没变**，所以这里**什么都不用改** ——
       顶层多一个键，这个函数压根不读它（要动材料文本得先问用户，见 改这些文字要先问维护者）。

    ⚠️ 2026-10-03（互联网改造那一批，契约 **B3 选 (a)：按 token 认人之后覆盖**）：
       那条 token 认出来是谁，就用**他那条记录**的 `群` / `名字`：
         · `群` 非空 → 用它当收件人（payload 里的 `group_id` 直接忽略，不报错、不拒绝）；
         · `群` 为空 → 沿用 payload 的 `group_id`（老行为不变）；
         · `facts.人` → **一律用表里的 `名字`**（payload 里那个被忽略；E2 定的字段名）。
       其余（`facts.数据`、`title`/`body`/`fallback`、`severity`）**原样不动**，
       电脑侧载荷的键名一个字节都没改。⚠️ **没有新增任何中文句子**（只换了两个取值）。
    """
    rec = users.by_id((ident or {}).get("id")) if ident else None
    gid = int(req.get("group_id") or 0)
    uid = int(req.get("user_id") or 0)
    mention = int(req.get("mention") or 0)
    title = (req.get("title") or "").strip()
    body = (req.get("body") or "").strip()
    fallback = (req.get("fallback") or "").strip() or "\n".join(x for x in (title, body) if x)
    facts = req.get("facts") if isinstance(req.get("facts"), dict) else {}
    if rec:
        try:
            g_over = int(rec.get("群") or 0)
        except Exception:
            g_over = 0
        if g_over > 0:
            gid = g_over
            base.log("播报：按身份 %s 覆盖收件群 → %s" % (rec.get("id"), gid))
    if not gid and not uid:
        return _ok("播报没给收件人（group_id 或 user_id）", False)
    if not (title or body or fallback or facts):
        return _ok("播报是空的（没给 facts / fallback / title / body）", False)

    # ⚠️ 2026-09-27 用户定的材料格式（他自己写的，照着来）：
    #    抬头一句 + **一条记录一行**（顺序照电脑给的，键名就是 站点/摸鱼时间/时间，
    #    不加任何多余的字、不做「应用/站点」的区分）。
    # ⚠️ 2026-10-04（用户拍板「身份 = QQ」）：这个**值**改走 `who.display_name()`
    #    （**唯一一处显示名实现**：备注 → 称呼 → 昵称 → QQ 号）——
    #    按 token 认出来的那条记录 → 显示名。
    # ⚠️ 2026-10-04（第四批「推送只认用户令牌」）：原来那条
    #    **「认不出 QQ 就退回载荷里的 `人`」的兜底分支已经删掉**（死代码）——
    #    推送这条路进来的一定是 `users.json` 里某条记录（门禁在 server 层，
    #    见 `server.PUSH_ACTIONS`），那个分支永远不会走到。
    #    ⛔ 万一真没解析出来，`who` **保持空**即可（**不新增任何词**）——
    #    下面那句指令里的 `who or "某人"` 是**用户写的原文**，一个字没动。
    who = ""
    if rec:
        # ⚠️ 2026-10-06（用户拍板）：**播报材料也按"所在群"的名片** ——
        #    四级降级「称呼 → 本群名片 → 昵称 → QQ 号」，⛔ 方括号那截去掉了。
        who = who_mod.display_name(rec, is_group=bool(gid), group_id=(gid or "")) or ""
    rows = facts.get("数据") if isinstance(facts.get("数据"), list) else None
    # 抬头**不写名字**（写了会变成"下面是某人这个人的…"，读着绕）—— 名字在下面那句指令里
    # （用户自己写的那句）。要两处都带名字的话，把电脑配置的 notify.callName 填上就行。
    材料 = ["下面是电脑的摸鱼管理程序传上来的摸鱼数据信息："]
    if rows:
        for r in rows[:20]:
            if isinstance(r, dict):
                # separators：跟用户手写的样例一样，冒号/逗号后面不留空格
                材料.append(json.dumps(r, ensure_ascii=False, separators=(",", ":")))
            else:
                材料.append(str(r))
    elif facts:
        # 老形状（扁平键值）—— 兼容用，别丢信息
        for k, v in list(facts.items())[:16]:
            材料.append("%s：%s" % (k, v))
    else:
        材料.append("· 它给的原文：%s" % fallback)
        base.log("播报：电脑只给了原文（老版本？），只能拿它当材料")

    key = ("g", gid) if gid else ("p", uid)
    ctx = {"key": key, "is_group": bool(gid), "group_id": gid, "user_id": uid or mention,
           "who": "电脑（PCStatus）", "text": "", "raw": "", "images": [],
           "message_id": None, "at": time.time()}
    # ⭐ 2026-10-09（用户拍板）：播报是**一条独立请求** —— ⛔ 一条对话历史都不带。
    #    从前的形状是 `[system] + 历史 + [材料/指令]`（`msgs.extend(memory.render(key))`），
    #    那段历史跟这次播报**毫无关系**，只会让她把群里的旧话扯进来（第 2 次请求那次
    #    真机事故就是这么来的）。播报要的只有两样：她是谁 + 这次电脑传上来的摸鱼事实。
    #    ⛔ 材料与指令**一个字都没动**（自检里逐字钉着它们）。
    msgs = [{"role": "system", "content": persona.system_prompt()}]
    # 指令：用户 2026-09-27 的原话（"跟大家通报"的方式，不是通报给他本人）。
    # ⚠️ 他明确要求**不要加"不想说就回某个词"** —— 他的原话里没有，别自己加。
    #    她要是真不说，回空就行：下面 not text 那个分支会当成"她决定不说"，
    #    回 ok:true 结束（群里安静）。播报这一轮**不带** `end_turn`（用户定的四种场合里
    #    没有它），所以"什么都不说"只剩空文本这一条路。
    # ⚠️ 结尾那句「可以称呼这个人为某人」只在名字**确实是"某人"**时才加 —— 他哪天把
    #    电脑配置的 callName 填成真名，这句就会自相矛盾 ✗（我按条件拼，不动他的原话）。
    群 = str(gid or facts.get("群") or "")
    msgs.append({"role": "user", "content": guards.system_reminder(
                 "%s\n"
                 "请你根据摸鱼数据，在群 %s用向其他人通报的方式高度概括一下 *%s* 这个人的摸鱼情况"
                 "（可以损他、可以幸灾乐祸，稍微简略一些，你可以选择称呼这个人为某人，"
                 "也可以用 %s 这个名字）。"
                 % ("\n".join(材料), 群, who or "某人", who or "某人"))})
    text, _called, err = llm.run_turn(msgs, ctx)
    text, _ = guards.strip_monologue(text)
    text = guards.strip_echo(text)
    fell_back = False
    if err:
        # 真失败（模型/网络出错）→ **ok:false**，让电脑走降级通道补一条（可用性兜底）
        base.log("播报：这一轮没跑起来（%s）—— 回 ok:false，让电脑自己想办法" % err)
        return _ok("我这边没跑起来（%s），这条你们自己发吧" % err, False)
    if not text:
        # ⚠️ 2026-09-27 关键语义：**她主动不说 = ok:true**（"这条我处理了，决定不说"）。
        #    以前回 ok:false，导致电脑以为"她没接住"→ 拿模板补发进群 ✗
        #    （用户原话：「她不肯说肯定有原因」，所以群里就该安静）。
        #    ok:false 只留给**真失败**，见上面那个分支。
        #    （播报这一轮**不带** `end_turn` —— 见 `toolkit.schemas(ctx)` 的四种场合；
        #      她真不说就是空文本。）
        base.log("播报：她自己决定不说 —— 回 ok:true（这条到此为止，别让电脑补发）")
        return _ok("她看到了，决定不说 —— 这条到此为止", True)
    # ⚠️ 2026-10-04：这里**原来也有一处硬截断**，而且是**写死的 800**
    #    （不看 `maxGroupReplyChars` 配置，私聊那条播报也照样按 800 截）。和 `_think`
    #    一样把那两行删掉 —— 拆成几条、每条多大、两条之间停多久，全在 `im.send_long`
    #    那一处（读 config 的 `_split_cfg`）。这一段的其它逻辑一个字都没动。
    ok = im.send_group(gid, text, at=mention) if gid else im.send_private(uid, text)
    if not ok:
        return _ok("播报没发出去（NapCat 那边拒了或没连上）", False)
    memory.record(key, "assistant", text)
    base.log("播报发出去了（%s）：%s" % ("原文兜底" if fell_back else "她组织的", text[:60]))
    return _ok("播报已发出%s：%s" % ("（她没说，用的原文）" if fell_back else "", text[:60]))


def on_api(action, req, ident=None):
    """实现 reset / add / use / del / test + **用户管理（user. 开头的动作，只有主人能调）**
    + **看共享令牌（`token.show`，同样只有主人能调）**
    + **提供商 / 模型目录 / 后台模型（`providers.*`，2026-10-30 加，同样只有主人能调）**
    + **扩展包（`capability.*`，2026-10-31 加，同样只有主人能调；实现在
      `fgbot/capabilities.py`）**。

    ⚠️ 2026-10-05（用户拍板"需要只有我能调"）：`reset` / `add` / `use` / `del` / `test` /
       `effort` / `triggers` / `memory` 与所有 `mem_*` / `mode` / `restart` 这些**控制面动作
       也一律只有主人能调**（名单见 `OWNER_ONLY_ACTIONS`）—— 从前本机 / 局域网**任何一把
       有用户令牌的人**都能调它们（公网那条路早就被 `server.PUBLIC_ACTIONS` 挡住了）。
       ⛔ 那些动作的名字 / 参数 / 返回结构一个字都没动，只是前面多了一道身份闸。

    返回 `None` = 这个动作我不认识（server 回 501）；
    返回 `FORBIDDEN` = 这个动作只有主人能调，而这条请求不是主人（server 回 **403 空正文**，B6）。

    `ident` = `server._identify()` 认出来的身份（`{"id","主人","名字","群","主人QQ"}`），
    认不出来就是 None（老调用方/自检不传也能跑）。
    """
    a = (action or "").strip().lower()
    req = req or {}
    ident = ident or {}
    is_owner = bool(ident.get("主人"))
    try:
        if a.startswith("capability.") or a in ("扩展", "扩展包"):
            # ── 扩展包（2026-10-31）：面板「扩展」页那几颗按钮 ──
            #    装 / 卸 / 启用 / 停用 / 列 —— 改的是**这台机器上能跑什么代码**
            #    （包和主程序同权限），和 add/use/del 同一档：**只有主人能调**。
            #    具体实现（校验 / 备份 / 回滚 / state 文件）全在 `fgbot/capabilities.py`
            #    一处；这里只做主人闸 + 转发。
            if not is_owner:
                base.log("控制面：%s 想调 %s —— 不是主人，回 403（身份 %s）"
                         % (ident.get("id") or "（认不出）", a, ident.get("名字") or "?"))
                return FORBIDDEN
            out = capabilities.api(a, req)
            if out is not None:
                base.log("控制面：%s → %s" % (a, str((out or {}).get("message") or "")[:80]))
                return out
        if a.startswith("user.") or a in ("用户", "用户管理"):
            # ── 用户管理（契约 E1 的动作名；B6：**只有主人能调**，别人 403 空正文）──
            if not is_owner:
                base.log("控制面：%s 想调 %s —— 不是主人，回 403（身份 %s）"
                         % (ident.get("id") or "（认不出）", a, ident.get("名字") or "?"))
                return FORBIDDEN
            return _user_api(a, req)
        if a.startswith("group.") or a in ("群", "群管理", "群名单"):
            # ── 群管理（2026-10-04 加）：她**理哪些群**（白名单 + 「最近见过的群」）──
            #    口径和 user.* 一模一样：**只有主人能调**，别人 403 空正文。
            #    ⛔ 这一块一个字都不进给模型看的材料 —— 它只改"理不理这个群"。
            if not is_owner:
                base.log("控制面：%s 想调 %s —— 不是主人，回 403（身份 %s）"
                         % (ident.get("id") or "（认不出）", a, ident.get("名字") or "?"))
                return FORBIDDEN
            return _group_api(a, req)
        if a.startswith("request.") or a in ("申请", "申请列表", "待处理申请",
                                             "通过申请", "拒绝申请", "忽略申请", "恢复申请"):
            # ── 待处理申请（2026-10-04 第二批加）：**好友申请 + 群邀请**排队等裁决 ──
            #    口径和 user.* / group.* 一模一样：**只有主人能调**，别人 403 空正文
            #    （"同不同意加好友"这种事不该让朋友的电脑替他决定）。
            #    ⛔ 这一块一个字都不进给模型看的材料 —— 它只改"这条申请怎么办"。
            if not is_owner:
                base.log("控制面：%s 想调 %s —— 不是主人，回 403（身份 %s）"
                         % (ident.get("id") or "（认不出）", a, ident.get("名字") or "?"))
                return FORBIDDEN
            return _request_api(a, req)
        if a in TOKEN_SHOW_ACTIONS:
            # ── 看共享令牌（2026-10-03 加）：面板上那个「🔑 看共享令牌」点它 ──
            #    ⛔ 只有主人（和 user.* 同一个口径）；⛔ 值绝不进日志、绝不进 HTML；
            #    ⛔ 响应头由 server 那边加 `Cache-Control: no-store`（见 TOKEN_SHOW_ACTIONS）。
            if not is_owner:
                base.log("控制面：%s 想调 %s —— 不是主人，回 403（身份 %s）"
                         % (ident.get("id") or "（认不出）", a, ident.get("名字") or "?"))
                return FORBIDDEN
            return _token_show(ident)

        # ── 控制面那些"改她自己的东西"的动作（2026-10-05 加）：**只有主人能调** ──
        #    口径和上面 user.* / group.* / request.* / token.show 一模一样：不是主人 →
        #    `FORBIDDEN` → `server.py` 回 **403 空正文**。
        #    ⛔ 这里**只加闸**：下面那些分支的返回值、参数、动作名一个字都没动 ——
        #       主人（面板 / 共享令牌 / 本机 / 局域网）调它们的结果与从前逐字相同。
        #    ⚠️ `mem_` 前缀也要挡（`mem_add` / `mem_person_del` … 全是**读写所有人长期记忆**的）。
        if a in OWNER_ONLY_ACTIONS or a.startswith("mem_"):
            if not is_owner:
                base.log("控制面：%s 想调 %s —— 不是主人，回 403（身份 %s）"
                         % (ident.get("id") or "（认不出）", a, ident.get("名字") or "?"))
                return FORBIDDEN

        if a == "reset":
            memory.reset()
            return _ok("对话记忆清空了 —— 她下一条消息当第一次见你们（称呼和提醒都还在）")
        if a.startswith("onboarding."):
            # ── 设置页（2026-10-31）：一条龙把新部署的人配完 ──
            #    · save / probe / groups / persona 的**校验、落点、热生效**全在
            #      `fgbot/onboard.py` 一处实现（面板和命令行 `--set` 走的是它同一份）；
            #    · 这里只做主人闸（上面 OWNER_ONLY_ACTIONS 已经挡过）+ 转发；
            #    · ⛔ 返回值里 token 永远是 `****`（`onboard.snapshot()` 打码）。
            out = onboard.api(a, req)
            if out is not None:
                base.log("控制面：%s → %s" % (a, str((out or {}).get("message") or "")[:80]))
                return out
        if a in PROVIDER_ACTIONS:
            return _providers_api(a, req)
        if a in ("restart", "重启"):
            # 她没法重启自己（进程一死就没人接这个请求了）—— 只**留个条子**：
            # 手机上的看门狗（bot-watchdog-v2.sh）每 5 秒瞄一眼 restart.txt，
            # 看见就 kill + 拉起。App 那个「重启她」按钮走的是 Termux 脚本那条路，
            # 网页面板没有执行权限，所以走这条 —— 结果一样。
            try:
                p = store.path("restart.txt")
                with open(p, "w") as f:
                    f.write("%s 面板请求\n" % time.strftime("%F %T"))
            except Exception as e:
                return _ok("写不了重启请求：%s" % e, False)
            base.log("控制面：面板请求重启她（已留 restart.txt，等看门狗办）")
            return _ok("已经跟看门狗说了 —— 她大约 10 秒后回来，这个页面会自己连上")
        if a == "add":
            ok, msg = llm.api_add(req.get("name"), req.get("baseUrl"), req.get("model"), req.get("key"))
            return _ok(msg, ok)
        if a == "use":
            ok, msg = llm.api_use(req.get("name"))
            return _ok(msg, ok)
        if a == "del":
            ok, msg = llm.api_del(req.get("name"))
            return _ok(msg, ok)
        if a == "test":
            ok, msg = llm.test_provider()
            return _ok(msg, ok)
        if a in ("effort", "reasoning", "思考强度"):
            # 思考强度：手机上改的存 runtime.json（deploy 不会覆盖它，见 llm.runtime_set）
            ok, msg = llm.set_effort(req.get("value") or req.get("effort") or req.get("level"))
            return _ok(msg, ok)
        if a in ("triggers", "触发词", "关键词"):
            # 触发词（网页面板 / 手机 App 上编辑；存 runtime.json，deploy 不覆盖）。
            # 语义：消息里出现它就把这条交给模型 —— 没有现成回复（用户定的）。
            words = req.get("words")
            if words is None:
                cur = persona.trigger_words()
                return _ok("现在的触发词：%s" % ("、".join(cur) or "（空的，一个都没有）"),
                           True, triggers=cur)
            if isinstance(words, str):
                words = re.split(r"[、,，/\s]+", words)
            clean = []
            for w in (words or []):
                w = str(w).strip()
                if w and w not in clean:
                    clean.append(w)
            ok = llm.runtime_set("triggerWords", clean)
            base.log("控制面：触发词改成 %s" % ("、".join(clean) or "（空）"))
            return _ok("触发词已存成「%s」（下一条消息生效，不用重启）"
                       % ("、".join(clean) or "空"), bool(ok), triggers=clean)
        if a in ("settings.save", "参数保存"):
            # ── 运行参数（2026-10-30）：面板「运行参数 / 高级参数」那两张卡 ──
            #   · 只接受注册表里的键，别的**直接忽略**（用户定的口径）；
            #   · 先把所有值校验一遍，有一个不合法就**整批不存**（不写一半）；
            #   · 超出范围的值由 settings 钳制，并把「你填了 999，已按 20 存」带回去。
            vals = req.get("values")
            if not isinstance(vals, dict):
                return _ok("没给要保存的参数", False, settings=settings.snapshot())
            plan, notes, skipped, errors = [], [], [], []
            for k, raw in vals.items():
                if k not in settings.REGISTRY:
                    skipped.append(str(k))
                    continue
                try:
                    settings.check(k, raw)
                except settings.SettingsError as e:
                    errors.append(str(e))
                    continue
                plan.append((k, raw))
                note = settings.clamp_note(k, raw)
                if note:
                    notes.append(note)
            if errors:
                return _ok("没保存：%s" % "；".join(errors), False,
                           settings=settings.snapshot())
            saved = 0
            for k, raw in plan:
                try:
                    settings.set(k, raw, who="面板")
                    saved += 1
                except (KeyError, settings.SettingsError) as e:
                    errors.append(str(e))
            msg = "已保存（%d 项）" % saved
            if notes:
                msg += "；" + "；".join(notes)
            if skipped:
                msg += "；忽略了 %d 个不认识的键" % len(skipped)
            if errors:
                msg += "；没存：%s" % "；".join(errors)
            return _ok(msg, not errors, settings=settings.snapshot())
        if a in ("settings.reset", "参数恢复"):
            key = str(req.get("key") or "").strip()
            if key:
                if key not in settings.REGISTRY:
                    return _ok("没有这个运行参数：%s" % key, False,
                               settings=settings.snapshot())
                had = settings.reset(key, who="面板")
                label = settings.REGISTRY[key]["label"]
                msg = ("「%s」已恢复默认" % label) if had else ("「%s」本来就是默认值" % label)
            else:
                n = settings.reset_all(who="面板")
                msg = "已全部恢复默认（清掉 %d 项面板值）" % n
            return _ok(msg, True, settings=settings.snapshot())
        if a in ("announce", "broadcast", "播报"):
            # 电脑上的 PCStatus 拦到摸鱼 → 把事实递过来，让她组织那句话（见 _announce）
            return _announce(req, ident)
        # ── 记忆的读和写（网页面板 / 手机 App 上编辑用；**控制面**，不是她的嘴）
        if a in ("memory", "记忆"):
            return _ok("记忆库：%d 个人" % len(_people()), True, memory=_people())
        if a in ("mem_add", "记忆加"):
            ok, msg = memory.add_fact(req.get("qq"), req.get("text") or "")
            base.log("控制面：%s 的记忆加一条「%s」→ %s" % (req.get("qq"), (req.get("text") or "")[:30], msg))
            return _ok(msg, ok, memory=_people())
        if a in ("mem_fix", "mem_del", "记忆改", "记忆删"):
            new = "" if a in ("mem_del", "记忆删") else (req.get("new") or "")
            ok, msg, _hit = memory.fix_fact(req.get("qq"), req.get("old") or "", new)
            base.log("控制面：改/删 %s 的「%s」→ %s" % (req.get("qq"), (req.get("old") or "")[:30], msg))
            return _ok(msg, ok, memory=_people())
        if a in ("mem_name", "记忆称呼"):
            qq = req.get("qq")
            name = (req.get("name") or "").strip()
            ok, msg = memory.remember_name(qq, name) if name else memory.forget_name(qq)
            base.log("控制面：%s 的称呼 → %s（%s）" % (qq, name or "（清掉）", msg))
            return _ok(msg, ok, memory=_people())
        if a in ("mem_person_add", "加人"):
            ok, msg = memory.ensure_person(req.get("qq"), (req.get("name") or "").strip())
            base.log("控制面：加人 %s → %s" % (req.get("qq"), msg))
            return _ok(msg, ok, memory=_people())
        if a in ("mem_person_del", "删人"):
            ok, msg = memory.forget_person(req.get("qq"))
            base.log("控制面：整块删掉 %s → %s" % (req.get("qq"), msg))
            return _ok(msg, ok, memory=_people())
        if a == "mode":
            # v1 的灵珠/魔丸人格切换在 v2 里整个删掉了（用户明确不要）。
            # 老 App 要是还在发这个动作，回一句人话，别让它看得云里雾里。
            return _ok("v2 没有人格切换了 —— 灵珠/魔丸那套已经删掉，她就一个性格", False)
    except Exception as e:
        base.log_exc("控制面 %s" % a)
        return _ok("出错了：%s" % e, False)
    return None


def _token_show(ident):
    """把**共享那把令牌**交给主人看（面板上的「🔑 看共享令牌」；2026-10-03 加）。

    值 = `base.napcat_token()`：`config.json` 的 `bot.napcatToken`，空的时候**回退**
    `bot.token`（`base.napcat_token()` 那套老兼容），也就是面板登录要输的那一把。
    ⚠️ 面板 / 电脑侧 `PCStatus` 的 `bot.token` / `notify.her.token` 填的是**同一个值**。

    三条纪律（加这个动作时用户点名要的）：
      · **只有主人能调**（`on_api` 已经判过身份；别人拿 FORBIDDEN → server 回 403 空正文）；
      · ⛔ **值绝不进日志**：日志里只有一行"某来源查看了令牌"，一个字节的值都没有；
      · ⛔ **绝不把它拼进面板 HTML**（A5 堵掉的那个洞）——只能从这条 `/api` 响应里拿；
        响应头由 server 那边加 `Cache-Control: no-store`（见 `TOKEN_SHOW_ACTIONS`）。
    """
    tok = base.napcat_token()
    if not tok:
        base.log("控制面：主人（身份 %s）想看共享令牌，但配置里那把是空的"
                 % ((ident or {}).get("id") or "?"))
        return _ok("配置里那把共享令牌是空的（`config.json` 的 `bot.napcatToken` / `bot.token`）",
                   False)
    base.log("控制面：主人（身份 %s）查看了共享令牌（**值不入日志**）"
             % ((ident or {}).get("id") or "?"))
    return _ok("这就是你手机上的**共享令牌**（= `config.json` 的 `bot.token`）—— "
               "别发给朋友", True, token=tok)


def _user_api(a, req):
    """用户管理（契约 E1 的动作名 / B2 的"谁生成、怎么撤销"）。

    **只有主人能走到这里**（`on_api` 已经判过身份，别人拿 FORBIDDEN → 403 空正文）。
    这几个动作是**控制面**，不进给她的材料、不新增任何一句台词。

    ⚠️ `user.export` / `user.import`（2026-10-03 加）是**唯一会把 token 明文吐出去 / 收进来**
       的那两个动作（另一处是邀请码）：导出那份**含密钥**，日志里只许留条数/字节数。
    """
    def rows():
        # ⚠️ 2026-10-04：`fetch_nick=True` —— 面板那一份才允许**现取一次** QQ 昵称
        #    （"没有备注就显示称呼/昵称"，别只显示一串裸号）。取回来的昵称只在
        #    进程内缓存，**不落盘**（`who.fetch_nick`）。给模型看的材料一律不现取。
        out = users.panel_rows(base.public_url(), fetch_nick=True)
        for r in out:
            secs = statuscache.last_seen(r["id"])
            r["最后心跳"] = statuscache.ago_text(secs) if secs is not None else ""
            r["心跳新鲜"] = bool(secs is not None and secs <= statuscache.STALE_SECONDS)
            # ⛔ 2026-10-06（用户拍板）：**不把设备当区分维度** —— 面板这一份
            #    不再带 `电脑名` 了（心跳里那个名字只进日志，见 `statuscache.record`）。
        return out

    if a in ("user.list", "用户", "用户列表", "用户管理"):
        rs = rows()
        return _ok("用户表：%s" % users.stats(), True,
                   users=rs, publicUrl=base.public_url(), 主人模式=bool(base.owner_mode()))
    if a in ("user.nick", "取昵称"):
        # **加人表单里"填完 QQ 立刻把昵称显示出来给他核"**（用户 2026-10-04 点名要的）。
        # 控制面动作：不进给她的材料、不新增任何一句台词；⛔ 日志里不写任何值。
        q = str(req.get("qq") or req.get("主人QQ") or "").strip()
        if not re.match(r"^\d{4,12}$", q):
            return _ok("先填一个 QQ 号（4~12 位数字）", False, nick="", qq=q)
        nick = who_mod.fetch_nick(q)
        if not nick:
            base.log("控制面：取 QQ 昵称没取到（NapCat 没连上？）")
            return _ok("取不到这个号的昵称（NapCat 没连上，或者那边查不到）—— 照样能存",
                       False, nick="", qq=q)
        base.log("控制面：取到一个 QQ 的昵称（**值不入日志**）")
        return _ok("昵称：%s" % nick, True, nick=nick, qq=q)
    if a == "user.add":
        ok_, msg, rec = users.add(req.get("name") or req.get("名字"), req.get("qq") or req.get("主人QQ"),
                                  req.get("group") or req.get("群"), req.get("note") or req.get("备注"))
        base.log("控制面：发一把新令牌 → %s" % msg)
        return _ok(msg, ok_, users=rows(), publicUrl=base.public_url(),
                   新用户=users.ident_of(rec) if rec else None)
    if a in ("user.del", "user.revoke"):
        ok_, msg = users.remove(req.get("id") or req.get("uid"))
        base.log("控制面：撤销用户 → %s" % msg)
        return _ok(msg, ok_, users=rows())
    if a == "user.set":
        ok_, msg = users.update(req.get("id") or req.get("uid"), name=req.get("name"),
                                group=req.get("group"), note=req.get("note"), qq=req.get("qq"))
        base.log("控制面：改用户 → %s" % msg)
        return _ok(msg, ok_, users=rows())
    if a == "user.invite":
        rec = users.by_id(req.get("id") or req.get("uid"))
        if not rec:
            return _ok("没有这条记录", False, users=rows())
        code, err = users.invite_code(rec, base.public_url())
        if not code:
            return _ok(err, False, users=rows(), publicUrl=base.public_url())
        base.log("控制面：给 %s 生成了一条邀请码（没写进日志）" % users.ident_of(rec)["id"])
        return _ok("邀请码好了（整行粘给对方的电脑）", True, invite=code, users=rows())
    if a in ("user.publicurl", "user.public", "user.url"):
        val = str(req.get("value") if req.get("value") is not None else req.get("url") or "").strip()
        if val and users.valid_public_url(val) is None:
            return _ok("地址形状不对：要 `公网IP:端口` 或 `DDNS名:端口`"
                       "（不带 http://、不带斜杠、端口 1~65535；端口是**光猫上填的那个**，"
                       "不是 17383）", False, publicUrl=base.public_url())
        if not base.save_local({"bot": {"publicUrl": val}}):
            return _ok("写不进 local-config.json（手机上磁盘满了？）", False)
        base.log("控制面：公网地址 → %s" % (val or "（清空）"))
        return _ok("存好了（写在手机本地的 local-config.json，部署不会覆盖它）",
                   True, publicUrl=val, users=rows())
    if a in ("user.export", "用户导出"):
        # ⚠️ 这一份里**含每个人的 token 明文** —— 走到这里说明已经是主人了
        #    （`on_api` 判过身份，别人拿 FORBIDDEN → 403 空正文）。
        #    ⛔ **内容一个字都不进日志**，日志只留字节数（E3 的日志纪律）。
        txt = users.export_text()
        name = "users-%s.json" % time.strftime("%Y%m%d-%H%M")
        base.log("控制面：导出用户表（%d 字节、%d 个人；**内容不入日志**）"
                 % (len(txt), len(users.records())))
        return _ok("导出好了（⚠️ 这份文件含密钥，别外传）", True,
                   users=rows(), **{"导出": txt, "文件名": name})
    if a in ("user.import", "用户导入"):
        data = req.get("data")
        if data is None:
            data = req.get("text")
        ok_, msg, n = users.import_text(data)
        # msg 里只有条数和 id（没有 token），可以放心写日志
        base.log("控制面：导入用户表 → %s" % msg)
        return _ok(msg, ok_, users=rows())
    return None


def _group_api(a, req):
    """**群管理**（2026-10-04 用户点名要的）：她理哪些群 + 「最近见过的群」。

    **只有主人能走到这里**（`on_api` 已经判过身份，别人拿 FORBIDDEN → 403 空正文）。
    这几个动作是**控制面**：不进给她的材料、不新增任何一句台词，
    命令一回来就生效（`groups.json` 按 mtime 热重载，不用重启她）。

    ⛔ 这一块**不许退群**：移除只是"她不再处理那个群的消息"，
       要不要退群由用户自己在 QQ 里点（用户 2026-10-04 明确要求）。
    """
    def rows():
        return groups.panel_rows()

    if a in ("group.list", "群", "群管理", "群名单", "群列表"):
        # 群名**按需补一次**：`groups.panel_rows()` 只翻缓存（一个请求都不发），
        # 这里才对"名字还空着"的那几个问一次 NapCat（`im.group_name` 自带进程内 +
        # `group-names.json` 两级缓存；取不到就留空，绝不报错）。
        rs = groups._fill_names(rows())
        return _ok("群名单：%s" % groups.stats(), True,
                   groups=rs, seen=groups.fill_seen_names(), 名单=groups.known())
    if a in ("group.add", "群加", "加群"):
        gid = req.get("id") if req.get("id") is not None else req.get("group")
        ok_, msg = groups.add(gid, name=groups.name_of(gid, lookup=True), note=req.get("note"))
        base.log("控制面：群管理加群 → %s" % msg)
        if ok_:
            groups.forget_seen(gid)          # 加进来了就不用再挂在"最近见过的群"里
        return _ok(msg, ok_, groups=groups._fill_names(rows()), seen=groups.seen_rows())
    if a in ("group.del", "group.remove", "群删", "移出群"):
        gid = req.get("id") if req.get("id") is not None else req.get("group")
        ok_, msg = groups.remove(gid)
        base.log("控制面：群管理移除群 → %s" % msg)
        return _ok(msg, ok_, groups=groups._fill_names(rows()), seen=groups.seen_rows())
    if a in ("group.note", "群备注"):
        gid = req.get("id") if req.get("id") is not None else req.get("group")
        ok_, msg = groups.set_note(gid, req.get("note"))
        base.log("控制面：群管理改备注 → %s" % msg)
        return _ok(msg, ok_, groups=groups._fill_names(rows()), seen=groups.seen_rows())
    if a in ("group.forget", "群忽略", "忽略群"):
        gid = req.get("id") if req.get("id") is not None else req.get("group")
        ok_, msg = groups.forget_seen(gid)
        base.log("控制面：群管理忽略一条见过的群 → %s" % msg)
        return _ok(msg, ok_, groups=groups._fill_names(rows()), seen=groups.seen_rows())
    return None


def _request_api(a, req):
    """**待处理申请**（2026-10-04 第二批，用户点名）：好友申请 + 群邀请排队等裁决。

    **只有主人能走到这里**（`on_api` 已经判过身份，别人拿 FORBIDDEN → 403 空正文）。
    这几个动作是**控制面**：不进给她的材料、不新增任何一句台词。

    四个动作（用户点名）+ 一个"放回来"：
      · `request.list`    —— 列出待处理（默认只列「待处理」，另给一份处理过的）；
      · `request.approve` —— **通过**（真调 NapCat：好友 / 群邀请各一个被动 API）；
      · `request.reject`  —— **拒绝**（真调，`approve=False`；`reason` 可选）；
      · `request.ignore`  —— **忽略**：**一个 API 都不调**，只是从面板收起来
                             （QQ 那边那条申请还挂着，随时能放回来）；
      · `request.restore` —— 把「已忽略 / 已过期」放回「待处理」（也不调 API）。

    ⛔ 响应里**绝不含 `flag`**（`reqs.panel()` 就不给那个字段）—— 它是一次性凭据，
       只该待在手机本地的 `requests.json` 里。
    """
    def payload():
        d = reqs.panel()
        return {"requests": d["待处理"], "history": d["已处理"],
                "pendingCount": d["待处理数"], "doneCount": d["已处理数"]}

    def rid():
        return req.get("id") if req.get("id") is not None else req.get("申请")

    def reason():
        return req.get("reason") if req.get("reason") is not None else (req.get("原因") or "")

    if a in ("request.list", "申请", "申请列表", "待处理申请"):
        d = reqs.panel()
        base.log("控制面：申请列表 —— %d 条待处理 / %d 条处理过（返回里不带 flag）"
                 % (d["待处理数"], d["已处理数"]))
        return _ok("待处理申请 %d 条" % d["待处理数"], True, **payload())

    if a in ("request.approve", "通过申请", "申请通过"):
        ok_, msg, _p = reqs.approve(rid(), reason())
        base.log("控制面：申请「通过」→ %s" % msg)
        return _ok(msg, ok_, **payload())

    if a in ("request.reject", "拒绝申请", "申请拒绝"):
        ok_, msg, _p = reqs.reject(rid(), reason())
        base.log("控制面：申请「拒绝」→ %s" % msg)
        return _ok(msg, ok_, **payload())

    if a in ("request.ignore", "忽略申请", "申请忽略"):
        # ⚠️ 这一条**一个 API 都不发**（忽略只是"面板上不看了"，QQ 那边还挂着）
        ok_, msg, _p = reqs.ignore(rid())
        base.log("控制面：申请「忽略」→ %s" % msg)
        return _ok(msg, ok_, **payload())

    if a in ("request.restore", "恢复申请", "申请恢复"):
        ok_, msg, _p = reqs.restore(rid())
        base.log("控制面：申请「放回待处理」→ %s" % msg)
        return _ok(msg, ok_, **payload())

    return None


def _providers_api(a, req):
    """提供商 / 模型目录 / 后台模型（面板「她的大脑」「后台模型」两张卡）。

    ⛔ key 只在服务端：返回的每一份列表都是打码的（`llm.providers_public()`），
       连日志里也只写名字和模型数，绝不写 key。
    """
    req = req or {}
    models = None
    if a == "providers.save":
        ok_, msg = llm.provider_save(req)
    elif a == "providers.delete":
        ok_, msg = llm.provider_delete(req.get("provider") or req.get("id"))
    elif a == "providers.activate":
        ok_, msg = llm.provider_activate(req.get("provider"), req.get("model"),
                                         req.get("effort"))
    elif a == "providers.addmodels":
        ok_, msg = llm.provider_add_models(req.get("provider"), req.get("models"))
    elif a == "providers.delmodel":
        ok_, msg = llm.provider_del_model(req.get("provider"),
                                          req.get("model") or req.get("modelId"))
    elif a == "providers.fetchmodels":
        ok_, models, why = llm.provider_fetch_models(req.get("provider"))
        msg = ("拉到 %d 个模型" % len(models)) if ok_ else (why or "没拉到模型")
    elif a == "providers.utility":
        ok_, msg = llm.provider_set_utility(req)
    else:
        return None
    base.log("控制面：%s → %s" % (a, msg))
    extra = {"providers": llm.providers_public()}
    if models is not None:
        extra["models"] = models
    return _ok(msg, ok_, **extra)


def _ok(msg, ok=True, **extra):
    d = {"ok": bool(ok), "message": msg, "status": _status(), "apis": llm.api_list_public()}
    d.update(extra)
    return d


def _people():
    """记忆库给控制面看的样子（时间戳转成人看的）。

    ⚠️ 2026-10-04：多给一个 `显示名`（备注 → 称呼 → 昵称 → QQ 号，走 `who.display_name`）
       —— 面板上"一个人一行"的那几处统一按它显示，别只摆一串裸 QQ 号。
       控制面专用：**不进给她的任何材料**，也**不现取**昵称（面板里那些昵称是聊天时顺手记下的）。
    """
    out = []
    me = str(base.self_id())
    for p in memory.all_people():
        p = dict(p)
        p["at"] = reminders.human_at(p["at"]) if p.get("at") else ""
        if p["qq"] == me:
            # 她自己那一块永远拿不到"昵称"（她自己的消息她不收，见 handle 开头），
            # 气泡上就会变成一串光秃秃的 QQ 号 —— 这里补上她的名字。
            p["nick"] = p["nick"] or (persona.name() if persona else "MMZ")
        # ⚠️ 2026-10-05 修掉的那颗雷：以前这里直接把**记忆那块**（形状是
        #    `{"qq","name","nick","card","facts"…}`）丢给 `display_name()` —— 那函数
        #    认的是 `users.json` 的形状（拿 `主人QQ` 当 QQ 号），于是 QQ 号解析成空、
        #    四级兜底全落空，`显示名` **永远等于那串裸 QQ 号**（面板「记忆」页左边
        #    那一列因此只剩一串数字）。现在先按 QQ 号回查用户表再算：
        #    备注 → 称呼 → 群名片 → 昵称 → QQ 号（跟别处同一份实现，见 who.py）。
        p["显示名"] = who_mod.display_name(users.by_qq(p["qq"]) or str(p["qq"])) or str(p["qq"])
        out.append(p)
    return out


def _status():
    """和 server.status() 一个形状，另外把 apis 放在**顶层** —— App 的列表读的是它。"""
    return {"ok": True, "version": "v2", "port": base.cfg().get("port"),
            "uptimeSeconds": int(time.time() - _STARTED),
            "pid": os.getpid(), "agent": info(), "apis": llm.api_list_public()}


# ── 面板要看的 ──────────────────────────────────────────────────────

def info():
    """附在 /status 里。**绝不放 key**（只放一个打码的样子，给面板认）。"""
    p = persona.profile()
    try:
        st = llm.stats()
    except Exception as e:
        st = {"model": "?", "provider": "?", "key": "?", "error": repr(e)[:80]}
    return {
        "ready": True,
        "note": "%s（%s）" % (st.get("model"), st.get("provider")),
        "性格": {"文件": os.path.basename(p.get("_path") or ""), "名字": persona.name(),
                 "别名": persona.call_names()[1:], "字数": len(persona.personality_text()),
                 "在不在": not p.get("_missing")},
        "提示词字数": persona.prompt_chars(),
        # 触发词（面板/App 那一栏读的就是它）：出现在**句中任何位置**就叫得动她。
        # 存在 runtime.json（deploy 不覆盖），config.json 里那份是空的默认值。
        "触发词": persona.trigger_words(),
        "模型": st,
        "思考": {"开关": st.get("thinking"), "强度": st.get("effort"),
                 "改在哪": st.get("effort_from")},
        "对话线程": memory.threads(),
        "记着几个人": memory.people(),
        "提醒": len(reminders.pending()),
        "工具": toolkit.names(),
        "apis": llm.api_list_public(),
    }


# ── 手机上的控制脚本写的请求 ────────────────────────────────────────

def _consume_control():
    """`control.txt` 是手机上的 ctl 脚本（和 App 的「重置对话」）写的请求。

    它不走 HTTP —— 手机侧没有 python3，只能写文件；这边收消息时顺手看一眼。
    """
    p = store.path("control.txt")
    if not os.path.exists(p):
        return
    try:
        with open(p, encoding="utf-8") as f:
            what = (f.read() or "").strip().lower()
        os.remove(p)
    except Exception as e:
        base.log("control.txt 读/删失败：%r" % e)
        return
    base.log("收到控制请求：%r" % what)
    if "reset" in what:
        memory.reset()
