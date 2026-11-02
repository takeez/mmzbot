#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**身份 = QQ**；称呼 / 群名片 / 昵称都只是别名（用户 2026-10-04 / 10-06 拍板）。

这一份是**全项目唯一一处**「拿一个词找一个人」和「把一个人显示成一行字」的实现。
别的地方（工具认人、播报材料、面板）一律调这里 —— ⛔ 不许再各写一份。

═══ 两条口径 ═══

① **认人**（`identify` / `resolve` / `qq`）：把那个词解析成**一个人**。
   顺序是**定死的**（见 `_ORDER`）：
     ① 纯数字 = QQ 号　② **称呼**　③ **本群**名片　④ **昵称**　⑤ 兜底（她记的那件事）。
   ⛔ `users.json.名字`（面板备注）与 `users.json.备注`（私有备注）**完全不参与认人**
      —— 用户 2026-10-06 拍板：那两条只用于**面板显示**（`display_name` 的第一档）。
   ⛔ 2026-10-06（用户拍板）**「电脑名」这一档整条删掉了**：心跳里那个名字**只写日志**
      （`statuscache.record`），⛔ 不许当人的别名、也不许进任何给模型看的材料。
   ⛔ 群名片**按群各一张**（`memory.json[qq].cards[群号]`）：只有 `ctx` 里带着**当前群号**
      才启用这一档；私聊（没有"本群"）→ **整档不可用**。
   ⛔ 记忆里那个老的单字段 `card`（历史残留）**一个字节都不读**。
   ⚠️ **每档必须唯一命中才定案**：同一档里 ≥2 个**不同 QQ** = **重名 → 一律不猜**
      （`identify` 返回原因 `"ambiguous"`，调用方回**既有那句**，别自己拟新话术）；
      同一个 QQ 的多条记录（同一个人两台电脑）**不算重名**，由 `_pick()` 在它们之间挑。

② **显示名**（`display_name`）：**统一**的四级降级，取第一个有值的 ——
      群聊：① `users.json.名字`（面板备注，**只有面板那一份**有这一档）
            ② 她的记忆里的**称呼**　③ **本群**名片　④ **QQ 昵称**　⑤ 兜底 **QQ 号本身**
      私聊：同上，但**没有群名片那一档**（私聊没有"本群"）。
      ⚠️ QQ 昵称那一档：她记忆里见过的 → 调用方给的 → 调用方允许时才现取
         （`get_stranger_info`，只有面板那条路开）。
   ⛔ 绝不返回空、绝不抛异常（取不到就是那串 QQ 号）。
   ⛔ 2026-10-06（用户拍板）：**格式就是 `名字: `** —— 以前那截
      `称呼[群名片:X]` / `称呼[qq昵称:X]` **整条去掉了**，名片/昵称降级成 fallback 档。
      群名片**按群各有一张**，所以只有调用方**声明了群**（`is_group=True` + `group_id=`，
      或把当下那张 `card_now=` 传进来）才启用那一档。⛔ 老单字段 `card` 不读。

═══ 同一个 QQ 有多条记录（同一个人两台电脑）═══

`users.json` 的主键仍是那个**短 id**，同一个人**允许两条**。那时候：
`who._pick()` 只按**心跳最新**挑一条（并列时按文件里的先后，保证确定性）。
⛔ 2026-10-06（用户拍板）：**电脑名不再参与挑记录** —— 它整条链路清干净了，
   心跳里那个名字**只写日志**（`statuscache.record`），不进任何材料。

⚠️ 这一段的所有函数都**不吃网络**：只有 `display_name(..., fetch=True)` 那一处会去问一次
   NapCat 现取昵称，而且结果只放进程内缓存（**不落盘**，见 `_NICK`）。
"""

from . import memory, statuscache, users

# 认人的**固定顺序**（先精确、后模糊；同一档里按 users.json 里的先后）。
# ①`称呼` = 她给他定的叫法 ②`群名片` = **当前这个群**里那张 ③`昵称` = 她记忆里见过的
# ⛔ 2026-10-06（用户拍板）：**`电脑名` 这一档删掉了** —— 心跳载荷里那个名字只写日志，
#    ⛔ 不许当人的别名（「台式机」「张三的笔记本」这种词再也认不出人来）。
# ⛔ `名字`（面板备注）/ `备注`（私有备注）**不在这一串里** —— 用户 2026-10-06 拍板：
#    那两条只用于面板显示，认人一律不看。
_ORDER = ("称呼", "群名片", "昵称")

# 「指的是她自己 / 主人自己」那几个词（原来长在 `toolkit._SELF` 里）。
# ⚠️ 它们**不是别名**（`resolve` 不认）：同一个词在"问谁的电脑"里指主人、
#    在"查记忆"里指她自己 —— 语义不一样，所以留在各自调用方，这里只放一份字面表。
SELF_WORDS = ("自己", "我自己", "MMZ", "MMZ自己", "MMZBOT", "小悦")

# 现取到的昵称：**进程内缓存，不落盘**（用户说了"不落盘或落缓存你定"）。
# 取不到也记一笔（免得每个面板请求都去问一次 NapCat）。
_NICK = {}
_NICK_TRIED = set()


# ── 小工具 ──────────────────────────────────────────────────────────

def _clean(x):
    """去空白 + 把 QQ 那套占位符（"未设置"之类）当空 —— 判定口径跟记忆层同一份。"""
    s = str(x if x is not None else "").strip()
    if not s or s.lower() in memory.PLACEHOLDER:
        return ""
    return s


def _qq_of(x):
    """记录 / QQ 号 / 别的什么 → 那串 QQ 号（字符串，取不到给空串）。"""
    if isinstance(x, dict):
        return _clean(x.get("主人QQ"))
    return _clean(x)


def _rec_of(x):
    """参数是记录就直接用；是 QQ 号就翻用户表（同 QQ 多条时取心跳最新那条）。"""
    if isinstance(x, dict):
        return x
    qq = _clean(x)
    return users.by_qq(qq) if qq else None


def _hb_age(rec):
    """这条记录的心跳有多旧（秒）。**没有心跳给一个很大的数**（排最后）。"""
    try:
        a = statuscache.last_seen(str((rec or {}).get("id") or ""))
    except Exception:
        a = None
    return float("inf") if a is None else float(a)


def _gid(ctx):
    """**当前群**的群号（私聊 / 没给 ctx → 空串）。

    ⚠️ 认人只认**这个群**里的那张名片（用户 2026-10-06 拍板）：群名片按群各有一张，
       私聊里根本没有"本群"这回事 —— 那时候**名片档整档不可用**。
    """
    if not isinstance(ctx, dict):
        return ""
    return _clean(ctx.get("group_id"))


def _pick(cands, 词=""):
    """**同一个 QQ** 的多条记录里挑一条（同一个人两台电脑）。

    ⛔ 2026-10-06（用户拍板）：**只按"心跳最新"挑**（都没有心跳就按文件先后，结果照样确定）。
       `电脑名` **不再参与** —— 它整条链路清干净了（只写日志，见 `statuscache.record`），
       ⛔ 不许拿它当人的别名、也不许拿它挑记录。

    ⛔ **只许用来挑"同一个 QQ"的那几条**（用户 2026-10-06 拍板）：
       **跨人静默挑一条是禁止的** —— 那是重名，认人的规矩是"一律不猜"。
       `_decide()` 先按 QQ 分组，确认只剩一个 QQ 才调这里。
    """
    cands = [c for c in (cands or []) if isinstance(c, dict)]
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    best, best_age = cands[0], _hb_age(cands[0])
    for r in cands[1:]:
        a = _hb_age(r)
        if a < best_age:                 # 越小越新；严格小于 → 并列时保持文件先后
            best, best_age = r, a
    return best


def _aliases(rec, gid="", qq=""):
    """这个人的**全部别名**，按 `_ORDER` 分档（每档一串去重后的字符串）。

    `rec` 可以是 `users.json` 的一条记录，也可以是 `None` —— 那种人只在她记忆里、
    没有电脑（没有记录）：称谓/昵称他一样有，所以照样能认（那时候只有前三档）。

    ⛔ `users.json.名字`（面板备注）与 `users.json.备注`（私有备注）**不进这里** ——
       用户 2026-10-06 拍板：那两条只用于面板显示，**完全不参与认人**。
    ⛔ 记忆里的**老单字段 `card`** 也不读（历史残留）；名片档只读 `cards[当前群]`。
    ⛔ `电脑名` 这一档 2026-10-06 **整条删掉**（只写日志，不当别名）。
    """
    qq = qq or (_qq_of(rec) if isinstance(rec, dict) else "")
    m = memory.record_of(qq) if qq else {}
    raw = {
        "称呼": (m.get("name"),),
        "群名片": (memory.card_in(qq, gid),),
        "昵称": (m.get("nick"), _NICK.get(qq)),
    }
    out = {}
    for k, vs in raw.items():
        got = []
        for v in vs:
            s = _clean(v)
            if s and s not in got:
                got.append(s)
        out[k] = got
    return out


def _cands(gid=""):
    """所有候选人：`[(qq, 记录或 None, 别名字典)]`。

    · `users.json` **每条记录**一份 —— 同一个人两台电脑就是两条，它们是**同一个 QQ**；
    · 只在她记忆里、用户表里没有的那种人也算：他在群里叫「華仙」她照样该认得出
      （昵称 / **本群**名片对他一样算数）。
    """
    out, seen = [], set()
    for r in users.records():
        if not isinstance(r, dict):
            continue
        qq = _qq_of(r)
        if not qq:
            continue
        out.append((qq, r, _aliases(r, gid, qq)))
        seen.add(qq)
    for qq, _blk in (memory.all_records() or {}).items():
        qq = _clean(qq)
        if not qq or qq in seen:
            continue                      # 用户表里有的 QQ 已经在上面了（不重复算）
        out.append((qq, None, _aliases(None, gid, qq)))
    return out


def _tier_hits(cands, key, w, how):
    """某一档里命中的候选（`how` 决定精确还是模糊口径）。"""
    out = []
    for qq, rec, a in cands:
        vs = a.get(key) or ()
        if how == "exact":
            hit = w in vs
        elif how == "in_word":            # **别名出现在那个词里**（"张三同志那台"）
            hit = any(len(x) >= 2 and x in w for x in vs)
        else:                             # **那个词是别名的一部分**（跟 memory.find 一个口径）
            hit = any(w in x for x in vs)
        if hit:
            out.append((qq, rec, a))
    return out


def _decide(hits, w):
    """一档里的命中 → `(qq, 记录, "")`；**没人命中** → `None`；**重名** → `("", None, "ambiguous")`。

    用户 2026-10-06 拍板：**每档必须唯一命中才定案** —— 同一档里 ≥2 个**不同 QQ**
    就是重名，**一律不猜**（⛔ 绝不许跨人静默挑一条）。同一个 QQ 的多条记录（同一个人
    两台电脑）**不算重名**，交给 `_pick()` 按"心跳最新"挑。
    """
    if not hits:
        return None
    qqs = []
    for qq, _rec, _a in hits:
        if qq not in qqs:
            qqs.append(qq)
    if len(qqs) > 1:
        return "", None, "ambiguous"
    qq = qqs[0]
    recs = [r for q, r, _a in hits if q == qq and isinstance(r, dict)]
    return qq, (_pick(recs, w) if recs else None), ""


# ── ① 认人 ──────────────────────────────────────────────────────────

def identify(词, ctx=None):
    """⭐「一个词 → 那个人」的**唯一实现**（`resolve` / `qq` 都只是它的壳）。

    返回 `(qq, 记录或 None, 原因)`：
      · 原因 `""`          —— 认出来了；
      · 原因 `"none"`      —— 谁都没命中；
      · 原因 `"ambiguous"` —— **重名**（同一档 ≥2 个**不同 QQ**），**一律不猜**。

    顺序（用户 2026-10-06 拍板，见模块开头）：
      ① 纯数字 = QQ 号 → ② 称呼 → ③ **本群**名片 → ④ 昵称 → ⑤ 兜底（她记的那件事）。
    每一档**唯一命中**才定案；精确扫完再扫"别名出现在那个词里"、最后"那个词是别名的一部分"。
    ⛔ `电脑名` **不在**这一串里（2026-10-06 用户拍板整条删掉，它只写日志）。

    `ctx` 只用来取**当前群号**（`ctx["group_id"]`）：私聊 / 没给 → 名片档整档不可用。
    """
    w = _clean(词)
    if not w:
        return "", None, "none"
    gid = _gid(ctx)
    cands = _cands(gid)
    if not cands:
        return "", None, "none"

    # ① 纯数字 = QQ 号（她给号的时候不用猜）。5 位以上一律当号 —— 老行为不变。
    if w.isdigit() and len(w) >= 5:
        recs = [r for q, r, _a in cands if q == w and isinstance(r, dict)]
        return w, (_pick(recs, w) if recs else users.by_qq(w)), ""
    if w.isdigit():
        got = _decide([c for c in cands if c[0] == w], w)
        if got is not None:
            return got

    # ②③④ 别名：先**精确**，再模糊两档（都在精确之后，保证"精确优先"）。
    for key in _ORDER:
        got = _decide(_tier_hits(cands, key, w, "exact"), w)
        if got is not None:
            return got
    for key in _ORDER:
        got = _decide(_tier_hits(cands, key, w, "in_word"), w)
        if got is not None:
            return got
    if len(w) >= 2:
        for key in _ORDER:
            got = _decide(_tier_hits(cands, key, w, "word_in"), w)
            if got is not None:
                return got

    # ⑤ 兜底：她**记着的那件事**（`facts` 里的内容）—— 同样只许唯一命中。
    hit = []
    seen = []
    for qq, _blk in memory.find_all(w):
        if qq in seen:
            continue
        seen.append(qq)
        hit.append((qq, users.by_qq(qq), {}))
    got = _decide(hit, w)
    if got is not None:
        return got
    return "", None, "none"


def resolve(词, ctx=None):
    """把一个词解析成 `users.json` 里的**一条记录**；认不出来 / **重名**都给 `None`。

    ⚠️ 要分清"认不出来"和"重名"（重名也是一律不猜，但给模型的那句话不一样）就用
       `identify()` —— 它多回一个原因。这里只是它的薄壳（老接口，探针/面板还在用）。
    """
    return identify(词, ctx)[1]


def qq(词, ctx=None):
    """「一个词 → 那个人」的入口。返回 `(qq, 记录或 None)`；认不出来 / **重名**都 `("", None)`。

    ⚠️ 只在用户表里、没有记录的**那种人也在**（`identify` 会退到记忆层）——
       所以"工具认人"和"记忆认人"从 2026-10-06 起是**同一份实现、同一套顺序**。
    """
    got, rec, _why = identify(词, ctx)
    return got, rec


# ── ② 显示名 ────────────────────────────────────────────────────────

def fetch_nick(qq号):
    """**现取**一个 QQ 号的昵称（`get_stranger_info`，每个号每进程只问一次）。

    取到放进程内缓存 `_NICK`（**不落盘** —— 少一个 deploy 的 NEVER 要记）；
    取不到也记下"试过了"，返回空串。面板上"填完 QQ 立刻显示昵称给你核"用它。
    """
    q = _clean(qq号)
    if not q or not q.isdigit():
        return ""
    if q in _NICK:
        return _NICK[q]
    if q in _NICK_TRIED:
        return ""
    _NICK_TRIED.add(q)
    try:
        from . import im                    # 懒 import：出站那套（它只依赖 base/chunker/fgsig）
        got = _clean(im.stranger_name(q))
    except Exception:
        got = ""
    if got:
        _NICK[q] = got
    return got


def display_name(x, fetch=False, nick_hint="", card_now=None, is_group=False,
                 group_id=""):
    """**一个人显示成一行字**（用户 2026-10-06 拍板的**统一**四级降级）：

        群聊：① 称呼 → ② **本群**名片 → ③ QQ 昵称 → ④ QQ 号
        私聊：① 称呼 → ③ QQ 昵称 → ④ QQ 号
        （面板那一份在最前面还有一档 `users.json.名字` = 面板备注，见下）

    ⛔ 2026-10-06（用户拍板）：**格式就是 `名字: ` 那一截** —— 以前拼的
       `称呼[群名片:X]` / `称呼[qq昵称:X]` **整条去掉了**（前缀/材料两侧都不再有方括号）；
       名片/昵称从"方括号里的补充"降级成**降级链里的一档**。

    ⚠️ 群名片**按群各有一张**（`memory.cards[群号]`）：只有调用方**声明了群**
       （`is_group=True`，最好再给 `group_id=`）才启用这一档 ——
       私聊（没有"本群"）→ **整档不可用**。
       `card_now=` 是调用方手里那张**当下的**名片（当前消息的 `sender.card`），
       有就优先用它；没有就退到记忆里**这个群**那张（`memory.card_in(qq, group_id)`）。
       ⛔ 记忆里那份**老单字段 `card`** 这里**不读**（历史残留）；
          认人那边只看**按群那张表**（`cards[当前群]`，见 `identify`）。

    `x` 可以是记录（`users.json` 的一条）或一个 QQ 号。
    `fetch=True` 才允许**现取**昵称（那一处会问一次 NapCat，只在面板那条路上开）；
    默认 `False` —— 给模型看的材料、工具返回里绝不为一个昵称去等网络。
    `nick_hint` 是调用方手里**已有的**昵称（例如申请队列里 NapCat 早取过的那一个）。

    ⛔ 不返回空、不抛异常：实在什么都没有就给那串 QQ 号。
    """
    rec = x if isinstance(x, dict) else None
    qq = _qq_of(x)
    # ① 面板备注（`users.json.名字`）
    if rec is not None:
        got = _clean(rec.get("名字"))
        if got:
            return got
    m = memory.record_of(qq) if qq else {}
    # ② 她的记忆：称呼
    got = _clean(m.get("name"))
    if got:
        return got
    # ③ **本群**名片（只在调用方声明了群时才有这一档；私聊整档不可用）
    if is_group:
        side = _clean(card_now)
        if not side and qq:
            side = memory.card_in(qq, group_id)
        if side:
            return side
    # ④ QQ 昵称：她记忆里见过的 → 调用方给的 → （**允许时**才）现取。
    #    ⚠️ 现取那一步只在 `fetch=True` 时走：否则"面板开过一次"会悄悄改掉
    #       给模型看的材料（同一条记录，开面板前后显示不一样）—— 那种耦合不能有。
    got = _clean(m.get("nick")) or _clean(nick_hint)
    if not got and fetch and qq:
        got = fetch_nick(qq)
    if got:
        return got
    # ⑤ 兜底：QQ 号本身
    return qq or ""


def aliases(rec, group_id=""):
    """面板上要摆的那几个别名（`{档: [词, …]}`）—— `_aliases` 的对外名字。

    `group_id` 给了才带**那个群**的名片（面板是跨群的，默认就不摆名片）。
    """
    return _aliases(rec, _clean(group_id)) if isinstance(rec, dict) else {}


def forget_caches():
    """把进程内那两张昵称缓存清掉（**自检用**；正式路径不需要）。"""
    _NICK.clear()
    _NICK_TRIED.clear()
