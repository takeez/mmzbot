#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""语义召回的**纯逻辑**：条数曲线 + 排序 + 时间戳 tiebreak。

这个文件**不许 import 任何模型/数值库** —— 它是纯函数，只用标准库。
原因：离线自检要拿一个**假 embedder** 把它整条路跑通（曲线、tiebreak、三种形状），
模型不在手机上也必须能自检。真正的向量计算在 `embed.py` 里。

═══════════ 条数曲线（POC 调好的，别自己重调）═══════════

    raw = Σ_i max(0, s_i − THETA) ** P      # 只累加高过噪声底的，P 让高分更值钱
    n   = round(raw / C)                    # C = 比例系数
    n   = min(n, 高过 THETA 的条数, N_MAX)   # 只有那么多条值得发，别硬凑
    if n == 0 and max(s) >= S_MIN_SEND:     # 只有一个中等的也发一条
        n = 1

形状是连续、单调上升、封顶的（不分档，没有 if-else 阶梯）。四锚点全绿：
无关查询泄漏 0/9；代价是 34 条真查询里 5 条会「没找到相关的」。

═══════════ 时间戳 tiebreak（用户同意的补丁）═══════════

向量治不了「旧事实压过新事实」：`住在杭州` 和 `住在青岛` 都是「住哪」那一类，
谁分高谁赢，跟先后无关。所以**两条分数相差在 TIE_WINDOW 以内时，优先新的那条**。

为了这个，每条记忆要记一个写入时间。时间戳放**旁挂的 vectors.json** 里，
不放 memory.json —— 后者的 `facts` 必须继续是**字符串数组**（面板和手机 App 在读它，
改形状会把它们读坏）。老数据没有时间戳就当作并列，tiebreak 静默跳过。
"""

from __future__ import annotations

import math

# =====================================================================
#  ★★★ 系数就在这里，改这一块就行（POC 在 instruct+A 形态上定的）★★★
# =====================================================================
THETA = 0.30        # 噪声底：相似度低于它的完全不计数
P = 2.0             # 高分溢价：2 = 平方，越高的分越值钱；1 = 线性
C = 0.08            # 比例系数：raw / C = 想回的条数。C 越小越发，越大越抠
N_MAX = 10          # 封顶，最多回几条
S_MIN_SEND = 0.42   # 兜底门槛：n 算出 0 但最高分够这个数，还是回 1 条
# =====================================================================

TIE_WINDOW = 0.05   # 分数差在这个以内算并列 → 新的排前面


def how_many(scores, theta=THETA, p=P, c=C, n_max=N_MAX, s_min_send=S_MIN_SEND):
    """给一串相似度（已 L2 归一化后的点乘），返回该回几条。"""
    ss = [float(s) for s in scores]
    if not ss:
        return 0
    over = [s for s in ss if s > theta]
    raw = sum((s - theta) ** p for s in over)
    n = int(math.floor(raw / c + 0.5))
    n = min(n, len(over), n_max)          # 没有那么多条就回不了那么多
    if n == 0 and max(ss) >= s_min_send:
        n = 1
    return max(0, n)


def rank(scores, times=None, seq=None):
    """按分数降序排索引，**并列时新的排前面**。

    `times` 是每条记忆的写入时间（跟 scores 一一对应），可以给 None/0
    —— 老数据没有时间就是并列，静默跳过 tiebreak。

    判据是**相邻两条**分数差 < TIE_WINDOW 就算一档，一档之内按时间新的优先。
    这样「差 0.04 的两条」会被时间翻过来，而「差 0.30 的两条」永远按分数。

    ⚠️ **时间也一样时的兜底：按写入顺序，后写的排前面。**
       这条不是装饰，实测会用上：老记忆第一次被补算向量时，一次补算里的几条
       拿到的是**同一个**时间戳（都是"刚才"）。这时候「住在杭州」和「住在青岛」
       就靠写入顺序决胜负 —— `memory.add_fact` 是 append，所以**下标大的更新**。
       所以并列的最后一级是 `-seq`（seq 默认就是下标）。

       ⚠️ 别把这一级删掉换成"靠稳定排序保序"：`sorted` 确实是稳定的，但它保的是
          **列表里的先后**，而列表里**旧的在前** —— 那正好是反的（第一版就这么
          写错了，手机上实测「住在杭州」压着「住在青岛」）。
    """
    n = len(scores)
    idx = list(range(n))
    if n <= 1:
        return idx
    if times is None:
        times = [0] * n
    times = [float(t or 0) for t in times]
    if seq is None:
        seq = list(range(n))

    # 先按分数降序（并列保持原顺序）
    idx.sort(key=lambda i: -float(scores[i]))

    # 再在「分数接近」的档内按时间降序；时间也一样就按下标降序（后写的在前）。
    # 分档看的是**原始相邻差**，所以先记下排序后的分数，再一档一档处理。
    def within(band):
        return sorted(band, key=lambda j: (-times[j], -seq[j]))

    out = []
    band = [idx[0]]
    for i in idx[1:]:
        if abs(float(scores[band[-1]]) - float(scores[i])) < TIE_WINDOW:
            band.append(i)
        else:
            out.extend(within(band))
            band = [i]
    out.extend(within(band))
    return out


def select(facts, scores, times=None, seq=None, **kw):
    """按相似度排序，取前 `how_many(...)` 条。返回 [(这条记忆, 分数), …]。

    一条都没过门槛就返回 []（调用方回「没找到相关的」）。
    """
    if not facts:
        return []
    order = rank(scores, times, seq)
    k = how_many([float(scores[i]) for i in order], **kw)
    return [(facts[i], float(scores[i])) for i in order[:k]]


def dot(a, b):
    """余弦相似度。两边都已是单位向量 ⇒ 就是点乘。

    ⚠️ 模型输出的 `sentence_embedding` **已经 L2 归一化**（手机上实测
       norm=1.000000000），所以这里不除模长。万一哪条没归一化，
       `embed.Embedder.encode` 也会先兜一次。
    """
    return sum(float(x) * float(y) for x, y in zip(a, b))


def scores_against(query_vec, vectors):
    """查询向量 × 一批记忆向量 → 相似度列表（缺向量的位置给 -1.0）。

    -1.0 而不是 0.0：它必须**低于任何门槛**（THETA=0.30），
    这样「这条还没算向量」永远不会被当成一条命中的记忆发出去。
    """
    return [dot(query_vec, v) if v else -1.0 for v in vectors]
