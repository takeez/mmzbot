#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""`memory(ask=…)` 那条路（工具名 2026-10-06 从 `recall` 改成 `memory`）：**只把最像的几条**取出来。

一次调用的全流程：

    ① 拿这个人的 facts（只他一个人的，绝不碰别人的）
    ② 拿「模型指纹 + 配方版本」；和向量文件里存的对不上就**整份作废**
    ③ 读旁挂向量；**缺哪条就补算哪条**（自愈：面板/App 改过 memory.json 也能接住）
    ④ 查询一次编码（batch=1，带 BGE 指令前缀）
    ⑤ 打分 → 条数曲线 → 时间戳 tiebreak → 取前 n 条

**任何一步出问题都退回去「把这个人的全部记忆给她」**，绝不报错、绝不返回空
（用户定的：模型文件丢了就降级 + 日志写一行）。

写在这里而不是 `toolkit.py` 里，是为了让 `toolkit.t_recall` 保持「薄」——
它只管三件事：解析是查谁、决定填没填「ask」、把结果摆成规定的形状。
"""

from __future__ import annotations

from . import base, embed, semantic, vecstore

# 一次 memory 查询里最多补算多少条向量。防止有人把 memory.json 手改成几百条、
# 或者第一次上线时 30 条全要现算，把一轮对话拖住。
MAX_FIX = 40


def _fix_missing(emb, qq, facts, vectors, times, stamp=None):
    """把缺向量/缺指纹的位置补上，**顺手写回旁挂文件**。就地改 vectors/times。"""
    gaps = vecstore.missing(facts, vectors)
    if not gaps or len(gaps) > MAX_FIX:
        if gaps:
            base.log("语义召回：要补算的向量太多（%d 条），这一轮先不补" % len(gaps))
        return 0
    try:
        got = emb.encode_facts([facts[i] for i in gaps])
    except Exception as e:
        base.log("语义召回：补算向量失败（%r），这一轮降级" % (e,))
        return 0
    now = _now()
    for k, i in enumerate(gaps):
        vectors[i] = list(got[k])
        times[i] = now
    try:
        vecstore.put(qq, facts, vectors, times, stamp)
    except Exception as e:
        base.log("语义召回：向量写不进旁挂文件（%r），不影响这一轮" % (e,))
    return len(gaps)


def _now():
    import time
    return time.time()


def pick(qq, facts, query):
    """语义召回一个人。返回 `(挑出来的 [(记忆, 分数), …], 是否降级)`。

    · `(None, True)`  = 用不了（模型不在／出错）→ 调用方退回「全部记忆」
    · `([], False)`   = 能用，但一条都没对上 → 调用方回「没找到相关的」
    · `([(…)], False)`= 对上了这几条

    ⚠️ embedder 是**每次现取**的（不是模块加载时定死），所以自检可以把
    `embed.get_embedder` / `embed.stamp` 换成假的，整条路（作废/补算/打分/
    曲线/tiebreak）会被原样跑过。
    """
    facts = [f for f in (facts or []) if isinstance(f, str) and f.strip()]
    if not query or not facts:
        return [], False

    emb = embed.get_embedder()
    if emb is None:
        return None, True

    # 「模型指纹 + 配方版本」：和向量文件里存的对不上就把整份作废、按需重算。
    # 拿不到（模型不在／文件读不到）→ None → **维持现状，绝不清空向量**。
    st = embed.stamp()

    try:
        vectors, times = vecstore.load_for(qq, facts, st)
        _fix_missing(emb, qq, facts, vectors, times, st)
        # 补完再查一遍缺的：还有 None 的就说明补算没成功，那时分数是 -1.0，
        # 这些条不会被选中（只有全都没向量时才整体降级）
        if all(v is None for v in vectors):
            base.log("语义召回：这个人的向量一条都没有，这一轮降级")
            return None, True
        qv = emb.encode_query(query)
        scores = semantic.scores_against(qv, vectors)
        return semantic.select(facts, scores, times), False
    except Exception as e:
        base.log("语义召回出错了，这一轮降级成「全部记忆」：%r" % (e,))
        return None, True
