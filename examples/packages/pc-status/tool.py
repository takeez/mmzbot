#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""战况（pc_status）：电脑发来的**心跳缓存** → 给她一组中文键的事实材料。

这原来是 `fgbot/toolkit.py` 里的内置工具（2026-10-31 搬出来，成了**第一个示例扩展包**）。
搬的原则：**行为等价** —— desc / params / 材料那几句一个字都没动，只是换了住处：

    · 平时目录里只有一行「- pc-status：查电脑上今天干了多少活（查询今日战况）」；
    · 她调 `skill("pc-status")` 读这个包的说明 → `pc_status` 的 schema 才进请求；
    · `available(ctx)` = `pcStatus.enabled` 为真 **且** 最近有电脑心跳
      （`statuscache.fresh()`，90 分钟那条线）—— 和原来 `pc_status_offered()` 同一条口径。

⚠️ 下面那些句子（尤其 `_NO_PERSON` / desc / `who` 的参数说明 / 材料）都是定稿的，
   ⛔ 一个字都不许改（自检里逐字钉着它们）。
"""

from fgbot import base, im, statuscache, users, who
from fgbot import toolkit as _tk

NAME = "pc_status"

# ⚠️ 定稿的那两句（desc / who 的参数说明）—— 搬过来时**一个字没动**。
DESC = "查电脑上今天干了多少活、现在在忙什么"

PARAMS = {
    "type": "object",
    "properties": {
        "who": {"type": "string",
                "description": "他的【消息前缀】；不填=当前说话的人"},
    },
    "required": [],
}


def available(ctx=None):
    """现在该不该把 `pc_status` 放进工具目录（= 原来 `toolkit.pc_status_offered()`）。

    两个条件同时成立才给：
      ① `pcStatus.enabled` 是**真布尔 true**（关掉 = 她连"有战况这个能力"都不知道）；
      ② `statuscache` 里有**最近**一跳电脑心跳 —— 一台电脑都没连过还给她这个工具，
         她只会照着说明去问、然后答"没开机"。
    """
    try:
        ps = base.cfg().get("pcStatus")
        if not isinstance(ps, dict) or ps.get("enabled") is not True:
            return False
        ent = statuscache.latest()
        return ent is not None and statuscache.fresh(ent)
    except Exception:
        return False


# pc_status 里「说话人自己那台」的那两个词。
# ⚠️ 和 `who.SELF_WORDS` **不是**一回事：那一串里还有「MMZ / MMZBOT / 小悦 …」——
#    那是**她**（她不知道自己的 QQ 号，所以留了那几个词给"查记忆"用），不是说话人。
#    在「问谁的电脑」里指**当前说话的人**的只有这两个词 —— 口径跟别的工具
#    （`_tk._target`：留空 = 当前说话的人）一致。
_PC_SELF = ("自己", "我自己")


# 「说话人根本没登记过」那一句 —— **用户 逐字定稿**（他给了才写的），
# ⛔ 一个字都不许改（标点、那个破折号、空格都在内），也⛔ 不许在别的地方用。
# 触发条件只有一处：`_pc_target()` 里"空 who / 自己 → 说话人的 QQ → `users.by_qq()`
# 认不出他"那一条路（= 用户表里没有他这个人）。**有记录、只是没心跳**那种照旧用
# 原来那句（`_NO_HB` / `statuscache.material()` 那三档），⛔ 不许混。
_NO_PERSON = "问话的这个人还没登记过电脑 —— 拿不到数据"


def _pc_target(who_="", ctx=None):
    """**pc_status 的「问谁的电脑」**：把那个称呼解析成一条接入用户记录。

    用户 2026-10-03（A2）定的：**不要程序按提问者自动路由** —— 像查记忆那样，
    由 LLM 自己填 `who` 选一台电脑。这个函数只是把那个称呼翻译成"哪台"。

    ⚠️ 2026-10-05（用户拍板「真的做到所有人都一样」）：**这套里没有"主人那台"这种特例**。
       空 `who` /「自己」「我自己」= **当前说话的人**那台（`ctx` 里的 QQ → `users.by_qq()`），
       跟 `_tk._target()` / `_recall_who()` 那套已有的平等做法一样。
       ⛔ 从前那三条"兜到主人"的老路**整条删掉了**。

    返回 `(记录, 拿不到记录时给模型的人话)`：
      · 能认成一台电脑 → `(那条记录, "")`；
      · 认不出来      → `(None, 给模型的人话)`。

    认人的口径：
      · 空 `who` /「自己」→ 说话人的 QQ → `users.by_qq()`（同一个人两台电脑时由
        `who._pick()` 挑：**心跳最新**那条 —— ⛔ 电脑名不参与，见 `who._pick`）；
      · 别的词 → **`who.identify()` 那一处实现**：称呼 / **本群**名片 / 昵称 / QQ 号都认
        （⛔ 面板备注 / 私有备注不参与；名片只认 `ctx` 里那个群的那张）；
      · 别的 → `_tk._target()` 里那两句**统一**措辞（撞名 → `_AMBIGUOUS`、
        没找到 → `_NOBODY`）—— ⛔ 电脑名不再是任何一档（用户 2026-10-06 拍板）。

    ⚠️ 说话人**没登记过**（`users.json` 里没有他那条记录）→ `_NO_PERSON`：
       用户 2026-10-05 逐字定稿的那一句（**唯一**用到它的地方）。
       有记录、只是没有心跳 → 那**不是**这一档（走 `_NO_HB`，见 `run`）。
    """
    w = str(who_ or "").strip()
    if not w or w in _PC_SELF:
        # ── 说话人自己那台 ──
        uid = _tk._who(ctx)
        rec = users.by_qq(uid) if uid else None
        if rec is None:
            # 他没登记过 → 没有他的心跳缓存可读（用户给的那句话）。
            # ⛔ 绝不退回"主人那台"、也绝不退回"全体最新那条"——那两条都会答成别人的数据。
            return None, _NO_PERSON
        return rec, ""

    qq, rec, _why = who.identify(w, ctx)      # ★ 唯一一处认人（称呼/本群名片/昵称/QQ 都在里面）
    if rec is not None:
        return rec, ""

    # 认不出来 → 只用**统一**那两句（`_tk._target()` 里那两句：撞名 / 没找到）
    _qq, bad = _tk._target(ctx or {}, w)
    return None, (bad or _tk._NOBODY % w)


def _pc_forward(ctx):
    """⚠️ **2026-10-05 起这条路没有任何入口（故意留着不删）。**

    用户拍板：「我的实时就不用了，真的做到所有人都一样」—— 所以**所有人（包括主人）
    一律走电脑发来的心跳缓存**（`statuscache.material()`），局域网直连这条路
    **一个调用点都没有了**（`run` 里那条分支删掉了；自检里有一条断言：
    `_pc_forward(` 在这个文件里只出现在下面这个 `def` 上，没有任何调用）。

    ⛔ 为什么留着一份死代码：里面的字符串（那三种原因、那几个中文键名）一个一个都
       进过给模型看的材料 —— 改这些文字要先问维护者"LLM 看到的文本一个字都不许动"，
       所以**不删它、也不改它**，让它原样烂在这儿。
    ⛔ 别为了让"实时"回来而在任何新路径里调它 —— 那会让主人看到的东西跟别人不一样。

    下面是它原来的说明（原样保留）：

    局域网直连（和原来一模一样）→ 拿到摊平的中文键数据。

    返回 `(数据 或 None, 直连没给出数据的原因)` —— 原因只有三种：
    `"没开机"` / `"没接住"` / `"格式不对"`；`(None, "电脑说什么")` 表示电脑回了
    `ok:false`，那个 `error` 是**它自己**的句子，要原样交给她（不是我们说的）。
    """
    if not im.pc_alive():
        return None, "没开机"
    ok, body = im.forward_to_pc((ctx or {}).get("raw_body") or b"{}")
    if not ok:
        return None, "没接住"
    try:
        import json
        d = json.loads(body) if body else None
    except Exception:
        d = None
    if not isinstance(d, dict) or "ok" not in d:
        return None, "格式不对"
    if d.get("ok") is False:
        # 电脑明确说不行（没资格问 / 群不在白名单 / 它自己出错）→ 原话交给她
        return None, str(d.get("error") or "电脑返回的格式不对")
    out = {"ok": True}
    for k in ("日期", "专注", "摸鱼", "摸鱼来源", "现在"):
        v = d.get(k)
        if v not in (None, "", []):
            out[k] = v
    if len(out) > 1:
        return out, ""
    return None, "格式不对"


# 「没有他的心跳」那一句 —— 用户 逐字定的原话，**一个字都不许改**。
# ⚠️ 用它的只有一种情形：**他有登记、但一跳心跳都没发过**（老路，行为不变）。
#    ⛔ "说话人根本没登记过"是**另一档**（→ `_NO_PERSON`），两句绝不许混用。
# ⚠️ 这一句的**原文**在 `statuscache.NO_HEARTBEAT`（那边"跨天"那一档
#    也要用它）—— 这里**只是引用同一个常量**，字还是那一个字（自检里逐字钉着它）。
_NO_HB = statuscache.NO_HEARTBEAT


def run(args, ctx):
    """战况：只有电脑知道 —— 拿电脑发来的数据，**话由她自己组织**。

    用户点名要的形状：**电脑不认关键词、也不自己发消息**，她调用 = 直接把今日
    状态数据给她（中文键，跟她其它工具一样），话由她说。

    ⚠️ 2026-10-05（用户拍板「我的实时就不用了，真的做到所有人都一样」）：
       **所有人（包括主人）都走同一条路** —— 电脑发来的**心跳缓存**
       （`status-cache.json`：30 分钟一跳；缓存键 = 那条用户记录的 `id`）。
       ⭐ 2026-10-09（用户拍板「当天战况永不过期」）：**过期不再按 90 分钟算**，
          改成**只看日期** —— 缓存那条 `日期` == **他那台的今天**（`statuscache.computer_day()`）
          就一律可用（照旧带 `数据时间`），跨天才回现有那两句。详见 `statuscache.material()`。
       ⛔ 从前那条「主人 → 局域网直连（实时）」**一个入口都没有了**：
          `_pc_forward()` 那段代码留着不删，但**没有任何调用点**。

    ⚠️ 2026-10-03（A2）：可选参数 `who`（**要问谁的电脑**）。
       **留空 = 当前说话的人那台**（`ctx` 里的 QQ → 他自己那条记录 → 他自己的心跳缓存）；
       填了（一个称呼）就查**那个人**那台（`users.json` 里要有他那条记录，缓存键 = 那条的 `id`）。
       ⛔ 新增的两句措辞（desc / 参数说明）是定稿的；除此之外**没有新句子**。

    ⚠️ 2026-10-05（用户拍板 1(a)/2(a)/3(a)）：**同一个人（同一个 QQ）的多台电脑 → 拼成一份**
       —— 判据只看"**今天有数据**"（不看心跳新旧）、`专注`/`摸鱼` 相加、`摸鱼来源` 按来源名相加
       并按总时长降序（⛔ 不写电脑名）、`现在` 取心跳最新那条；规则与解析/格式化在
       `fgbot/merge.py`，取数在 `statuscache.merge_person`。

    返回（用户 2026-09-27 逐字定的文本，别自己改）：
      · 说话人**没登记过** → `{"ok": False, "error": _NO_PERSON}`
      · 没有他的心跳缓存 → `{"ok": False, "电脑不在线": True, "error": _NO_HB}`
      · 有心跳缓存       → 走缓存那几档（当天 + `数据时间` / 跨天 → 不在他的上报时段 或 电脑没开机）
    """
    w = (args or {}).get("who") if isinstance(args, dict) else ""
    rec, bad = _pc_target(w, ctx)
    if rec is None:
        # `who` 认不出来 —— **先停下**（不自己编句子）：返回既有那句「没找到…」。
        return {"ok": False, "error": bad}

    # ── 所有人（包括主人）都走这一条：**他自己那条心跳缓存** ──
    #    缓存键 = 那条记录的 `id`（契约：id = 缓存键）。同一个人的其它电脑由
    #    `statuscache.material()` → `merge_person()` 并进来。
    #    ⚠️ 认不出 id（理论上不该发生）就当"没有缓存" —— ⛔ 绝不退回
    #       `material(who=None)` 那个"全体最新那条"（那会答成别人的数据）。
    key = str(rec.get("id") or "")
    cached = statuscache.material(who=key) if key else None
    if cached is not None:
        return cached
    return {"ok": False, "电脑不在线": True, "error": _NO_HB}
