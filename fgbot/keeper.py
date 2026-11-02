#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""memory-keeper：**后台管家**。她每写下一 `text` 事实，程序立刻拿这个人的全部记忆
+ 这条新的，去问一次**低级模型**：有没有冲突 / 重复 / 过时，该删哪几条、该拆成哪几句。

为什么要有它（用户 2026-10-30 定的）：新版 `memory` 工具**没有** `old` / `new` 了 ——
增删改是「记忆库自己判断」。她只管一条一件事地往里写，收拾旧账是这个管家的事。

规矩（用户逐条批的，第 11 条 + 我的落地口径）：

  · 正文**逐字**用第 11 条那段（⛔ 不带 system、⛔ 不带性格）；
  · 用 `llm.utility`（low）—— 不花主模型那么高的思考强度；
  · 记忆列表**每行带序号**（`1. 住在青岛`），新的那条单独列出来；
  · 它只回 `{"删": [1,3], "加": ["…"]}`，程序照着删旧的、加新的：
      - 序号越界 → **忽略并记日志**；
      - 重复（跟已有的、跟它自己给的）→ **去重**；
      - 一次要删超过 3 条 → **整次放弃**（一条都不动）并记日志；
      - 写之前 **备份 memory.json，留最近 5 版**；
      - **只给新条目算向量**（旧的向量按指纹搬过去，不重算）。
  · 它说什么都不许影响这一轮对话：出任何事只写日志，绝不抛给工具调用方。

⚠️ 这段正文虽然她看不到，但它**是一次会发出去的 LLM 请求**，所以改字要先问用户。
"""

import json
import re
import time

from . import base, memory, settings

# ── 管家那次请求的正文（用户 2026-10-30 逐字批的，⛔ 一个字都不许改）──────
KEEPER_BODY = """这是一个人的记忆，一行一条，行首的数字是编号：

%s

刚记下的这一条：
%s

只做一件事：这条如果和上面某条冲突、重复或者已经过时，就把那几条的编号写进「删」；如果这条该拆成更准的几句，就把新句子写进「加」。
一次最多删 3 条；拿不准的不删。只输出一个 JSON，不要解释：{"删": [1, 3], "加": ["<新句>", …]}"""

MAX_DELETE = 3          # 一次最多删几条（超了整次放弃）—— 运行时 settings.get
MAX_ADD = 10            # 一次最多加几条（防它抽风倒一大堆）—— 运行时 settings.get
MAX_TOKENS = 1200        # 2026-10-30：600 时测出"5 条冲突"那类会被思考吃掉、正文空


def _parse_json(text):
    """从模型那句话里抠出 JSON（容忍 ```json 围栏 / 前后多一句解释）。"""
    s = (text or "").strip()
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s = re.sub(r"\s*```$", "", s).strip()
    try:
        d = json.loads(s)
        if isinstance(d, dict):
            return d
    except Exception:
        pass
    i, j = s.find("{"), s.rfind("}")
    if i >= 0 and j > i:
        try:
            d = json.loads(s[i:j + 1])
            if isinstance(d, dict):
                return d
        except Exception:
            pass
    # 只给了数组（`[1,3]`）这种也认：当成「删」
    if isinstance(s, str) and s.strip().startswith("["):
        try:
            d = json.loads(s.strip())
            if isinstance(d, list):
                return {"删": d, "加": []}
        except Exception:
            pass
    return None


def _int_list(v):
    out = []
    if isinstance(v, (int, float)):
        v = [v]
    for x in (v or []):
        try:
            out.append(int(str(x).strip()))
        except Exception:
            continue
    return out


def _str_list(v):
    if isinstance(v, str):
        v = [v]
    out = []
    for x in (v or []):
        s = str(x or "").strip()
        if s:
            out.append(s[:200])
    return out


def _refresh_vectors(qq, old_facts, new_facts):
    """把向量旁挂文件改成**新的事实表**：旧条目按指纹搬过去，只给新的那几条算。

    ⚠️ 算不出来就安静跳过 —— 下次 `memory` 查的时候自愈（`recall._fix_missing`）。
    """
    try:
        from . import embed, vecstore
        emb = embed.get_embedder()
        if emb is None:
            return
        st = embed.stamp()
        vectors, times = vecstore.load_for(qq, old_facts, st)
        pool = {}
        for f, v, t in zip(old_facts, vectors, times):
            if v:
                pool.setdefault(vecstore._fp(f), (v, t))
        nv, nt, gaps = [], [], []
        for i, f in enumerate(new_facts):
            hit = pool.get(vecstore._fp(f))
            if hit:
                nv.append(hit[0])
                nt.append(hit[1])
            else:
                nv.append(None)
                nt.append(0)
                gaps.append(i)
        if gaps:
            got = emb.encode_facts([new_facts[i] for i in gaps])
            now = time.time()
            for k, i in enumerate(gaps):
                nv[i] = list(got[k])
                nt[i] = now
        vecstore.put(qq, new_facts, nv, nt, st)
        if gaps:
            base.log("管家：只给 %d 条新记忆算了向量（其它按指纹搬过去）" % len(gaps))
    except Exception as e:
        base.log("管家：向量没跟上（不影响记忆本身，下次查询会自愈）：%r" % (e,))


def review(qq, new_text):
    """跑一次管家。返回 `True` = 真的动了记忆。**绝不抛**。"""
    qq = str(qq or "").strip()
    new_text = (new_text or "").strip()
    if not qq or not new_text:
        return False
    facts = [f for f in memory.facts_of(qq) if isinstance(f, str) and f.strip()]
    if not facts:
        return False
    lines = "\n".join("%d. %s" % (i, f) for i, f in enumerate(facts, 1))
    body = KEEPER_BODY % (lines, new_text)
    # ⚠️ 2026-10-30：空回复要再问一次 —— 模型偶尔把 token 全用在思考上、正文是空的
    #    （测出过连续 3 次 finish_reason=length）。问两次都没正文才放弃。
    got = ""
    max_tokens = settings.get("keeper.maxTokens")
    for _try in (1, 2):
        try:
            from . import llm
            got = llm.utility_text([{"role": "user", "content": body}], max_tokens=max_tokens)
        except Exception as e:
            base.log("管家：这次没问成（%r）—— 记忆原样不动" % (e,))
            return False
        if got:
            break
        base.log("管家：第 %d 次回了空的（记忆还没动）" % _try)
    if not got:
        base.log("管家：模型两次都回空的 —— 这次算了（记忆原样不动）")
        return False
    cmds = _parse_json(got)
    if cmds is None:
        base.log("管家：回的不是 JSON（%r）—— 这次算了" % got[:80])
        return False

    # ── 删：序号越界忽略、去重、超 3 条整次放弃 ──
    want_del = []
    for i in _int_list(cmds.get("删")):
        if i < 1 or i > len(facts):
            base.log("管家：「删」里的序号 %s 越界（一共 %d 条），忽略" % (i, len(facts)))
            continue
        if i in want_del:
            continue
        want_del.append(i)
    max_delete = settings.get("keeper.maxDelete")
    max_add = settings.get("keeper.maxAdd")
    if len(want_del) > max_delete:
        base.log("管家：一次要删 %d 条（上限 %d）—— 整次放弃，记忆一条都不动"
                 % (len(want_del), max_delete))
        return False

    # ── 加：去重（跟留下来的、跟它自己给的都去重）──
    rest = [f for i, f in enumerate(facts, 1) if i not in want_del]
    adds = []
    for s in _str_list(cmds.get("加"))[:max_add]:
        if s in rest or s in adds:
            base.log("管家：「加」里的「%s」重复了，去重" % s[:20])
            continue
        adds.append(s)
    if not want_del and not adds:
        base.log("管家：这次没有要改的（%s）" % got[:60])
        return False

    new_facts = rest + adds
    if not new_facts:
        # 兜底：别让一次"全删"把一个人的记忆清空（用户定的口径是"收拾"，不是"抹掉"）
        base.log("管家：删完就一条不剩了 —— 整次放弃（宁可留旧的）")
        return False

    memory.backup_versions()
    ok = memory.set_facts(qq, new_facts)
    if not ok:
        base.log("管家：新的记忆写不进去（磁盘？），这次算了")
        return False
    _refresh_vectors(qq, facts, new_facts)
    base.log("管家：%s 的记忆动过了 —— 删 %s、加 %d 条（现在 %d 条）"
             % (qq, want_del or "无", len(adds), len(new_facts)))
    # ⚠️ 2026-10-30：返回的是【这次加进去的句子列表】（不是 True）。
    #    调用方 `t_memory` 靠它判断"这条新的有没有已经由管家写进去"—— 有就不再重复加。
    return list(adds)
