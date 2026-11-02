#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一句话变成 512 维向量（bge-small-zh-v1.5 的 int8 ONNX 导出）。

这份文件是**唯一** import 模型库的地方（onnxruntime / tokenizers / numpy）。
它上面那层 `semantic.py` 是纯函数，所以模型装不上时整条路还能自己降级 ——
`get_embedder()` 返回 None，调用方退回「把这个人的全部记忆给她」。

═══════════ 四条实测出来的纪律（照着做，别改）═══════════

① **int8 模型拆成两个文件**：`model_quantized.onnx`(图, 168 KB) +
   `model_quantized.onnx_data`(权重, 23.8 MB)。ONNX external-data 格式，
   必须**同目录、不能改名**，少一个就加载失败。

② **只用 `tokenizers`（Rust），不要 `transformers`**：向量逐位相同，
   冷启动 316ms vs 2633ms、内存 78MB vs 120MB。

③ **查询逐条编码（batch=1）**：这个 int8 是动态量化，激活的 scale 是按**整批**
   统计的 —— 批里混进一句长句会让**整批所有行**的输出都变（手机实测 top1 最大差
   0.0137，和我们想量的效应同量级）。所以永远 batch=1；反正查询只有一句。
   ⚠️ 记忆向量也必须固定同一种批法，否则已存的向量全部作废。

④ **线程数必须钉成 1**。这一条是**在手机上量出来的**，和直觉相反：
       ORT 默认 599 ms／2 线程 125 ms／4 线程 271 ms／**1 线程 65 ms**
   默认拿满 8 核，但手机上还有 NapCat 和机器人本体在抢 CPU，多线程只是在互相拖；
   单线程复测 37~41 ms。所以下面写死 `intra_op_num_threads = 1`。

═══════════ 其它已验的事实 ═══════════

· 512 维；ONNX 直接输出 `sentence_embedding`，**已经 CLS 池化、已经 L2 归一化**
  （norm 实测 1.000000000，再归一化一次逐位不变）⇒ 代码里直接点乘即可。
· arm64 上出来的向量和 x86 **逐位相同**（前 8 维实测一致）。
· 模型输入要 `input_ids` / `attention_mask` / `token_type_ids`。
"""

from __future__ import annotations

import os
import threading

from . import base

# 模型放在她自己的目录下，一次性上传的（23MB 级别，不跟着每轮 deploy 走）
_DEFAULT_DIRNAME = os.path.join("models", "bge-small-zh-v1.5-onnx")
ONNX_REL = os.path.join("onnx", "model_quantized.onnx")
DATA_REL = os.path.join("onnx", "model_quantized.onnx_data")
TOKENIZER_REL = "tokenizer.json"

# BGE 的检索指令前缀。**查询要加，记忆不加**（A/B 实测：加前缀后排名更好、
# 无关查询的分数天花板从 0.47~0.54 降到 0.40~0.42）。
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

MAX_LENGTH = 128          # 和 POC 一致
DIM = 512

# ═══ 编码配方版本 ═══
# **凡是改「怎么把文本变成向量」，就把它 +1。** 涉及：模型文件 / 查询前缀 /
# 池化方式 / 维度 / 批法（batch=1 这条纪律）。改了却不 +1，旧向量会被继续用
# —— 分数悄悄变坏，而且**不报错**，是最难查的那种。
#
#   v2 = 第一次上线：bge-small-zh-v1.5 int8 + BGE 检索前缀
#        + 模型自带 CLS 池化与 L2 归一化 + 512 维 + 查询逐条编码
#
# 它和模型指纹一起写进 `vectors.json`（见 `stamp()`），对不上就整份作废、按需重算。
VEC_VERSION = 2

_LOCK = threading.RLock()
_EMB = None               # 单例：模型只加载一次
_FAILED = None            # 加载失败的原因（只报一次，别每轮都试）
_DIR = None               # 自检可以临时换目录


def model_dir():
    return _DIR or os.path.join(base.DIR, _DEFAULT_DIRNAME)


def set_model_dir(d=None):
    """自检用：临时换模型目录（None = 恢复默认）。会顺手清掉单例。"""
    global _DIR
    with _LOCK:
        _DIR = d
    reset()
    return model_dir()


class Embedder(object):
    """一个懒加载的 ONNX 会话 + 一个 Rust 分词器。"""

    def __init__(self):
        import numpy as np
        import onnxruntime as ort
        from tokenizers import Tokenizer

        self.np = np
        model = os.path.join(model_dir(), ONNX_REL)
        data = os.path.join(model_dir(), DATA_REL)
        tok_path = os.path.join(model_dir(), TOKENIZER_REL)
        for p in (model, data, tok_path):
            if not os.path.isfile(p):
                raise IOError("模型文件不在：%s" % p)

        self.tok = Tokenizer.from_file(tok_path)
        self.tok.enable_truncation(max_length=MAX_LENGTH)
        self.tok.enable_padding()

        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        # ④ 手机实测：单线程最快（ORT 默认线程数在手机上慢 15 倍）
        so.intra_op_num_threads = 1
        so.inter_op_num_threads = 1
        self.sess = ort.InferenceSession(model, so, providers=["CPUExecutionProvider"])
        self.in_names = [i.name for i in self.sess.get_inputs()]
        self.out_names = [o.name for o in self.sess.get_outputs()]

    # ------------------------------------------------------------------
    def encode(self, texts):
        """把若干条文本编成 (n, 512) 的 float32，**已 L2 归一化**。

        ⚠️ 查询那一侧必须 `len(texts) == 1`（纪律③）。这里不拦，是因为
        「补算缺失向量」那条自愈路径要一次编多条 —— 它只在写入时跑，
        而且自己保证和别处同一种批法。
        """
        np = self.np
        batch = self.tok.encode_batch(list(texts))
        feeds = {"input_ids": np.asarray([b.ids for b in batch], dtype=np.int64),
                 "attention_mask": np.asarray([b.attention_mask for b in batch],
                                              dtype=np.int64)}
        if "token_type_ids" in self.in_names:
            feeds["token_type_ids"] = np.zeros_like(feeds["input_ids"])
        named = dict(zip(self.out_names, self.sess.run(None, feeds)))
        v = np.asarray(named["sentence_embedding"], dtype=np.float32)
        # 模型自己已经是单位向量（实测 norm=1.000000000），这里兜一次底：
        # 万一换了模型/换了 ORT 版本，点乘也不会退化成非余弦。
        n = np.linalg.norm(v, axis=1, keepdims=True)
        return v / np.clip(n, 1e-12, None)

    def encode_query(self, text):
        """查一句 → (512,) 单位向量。**逐条编码**（纪律③）。"""
        return self.encode([QUERY_INSTRUCTION + (text or "")])[0]

    def encode_facts(self, texts):
        """记忆那一侧：**固定 batch_size=1**（和查询同一种批法，纪律③）。

        写入很少发生（一个人最多 30 条），成本可以忽略；换来的是
        「批里有什么」永远不影响结果，已存的向量不会因为某次批量不同而失配。
        """
        return [self.encode([t])[0] for t in texts]


# ── 单例 + 降级 ─────────────────────────────────────────────────────

def get_embedder():
    """拿到 embedder；**装不上/模型不在就返回 None**（调用方退回全部记忆）。

    ⚠️ 绝不抛异常出去。用户定的：模型文件丢了就降级 + 日志写一行，
    绝不能让 memory 那个工具直接报错。
    """
    global _EMB, _FAILED
    if _EMB is not None:
        return _EMB
    with _LOCK:
        if _EMB is not None:
            return _EMB
        if _FAILED is not None:
            return None
        try:
            _EMB = Embedder()
            base.log("语义召回：模型加载好了（%s）" % model_dir())
            return _EMB
        except Exception as e:
            _FAILED = "%s: %s" % (type(e).__name__, e)
            base.log("语义召回：模型用不了，memory 降级成"
                     "「把这个人的全部记忆给她」（%s）" % _FAILED)
            return None


def available():
    return get_embedder() is not None


def why_not():
    """为什么用不了（给面板/自检看的，不进模型请求）。"""
    get_embedder()
    return _FAILED or ""


def reset():
    """自检用：把单例清掉（换目录 / 假装没有模型）。"""
    global _EMB, _FAILED, _FP, _FP_DIR
    with _LOCK:
        _EMB = None
        _FAILED = None
        _FP = None
        _FP_DIR = None


# ── 模型指纹：这批向量到底是哪个模型算的 ────────────────────────────

_FP = None                # 缓存：见下面「为什么可以缓存」
_FP_DIR = None


def fingerprint():
    """模型指纹：**三个文件的名字 + 大小**拼成一个短串。

    为什么用大小不用哈希：这个函数**每次 memory 查询都要调一次**（拿去校验
    旁挂的 `vectors.json`），而哈希 23MB 在手机上要一百多毫秒；换模型必然
    换文件大小，够用。真碰上「换了个大小一模一样的模型」这种极端情况，
    就靠上面 `VEC_VERSION` +1 兜住。

    为什么可以按进程缓存：内存里那个 ONNX 会话在**加载那一刻**就把权重读死了，
    运行中把模型文件换掉也不会改变它算出来的向量 —— 所以"缓存的那份指纹"
    和"实际在用的那个模型"永远是一致的。

    读不到文件（模型不在）→ 返回 **None**。⚠️ 调用方必须把它当成
    「维持现状」：**绝不许因为拿不到指纹就去清空向量**（用户定的）。
    """
    global _FP, _FP_DIR
    d = model_dir()
    if _FP is not None and _FP_DIR == d:
        return _FP
    try:
        parts = []
        for rel in (ONNX_REL, DATA_REL, TOKENIZER_REL):
            p = os.path.join(d, rel)
            parts.append("%s:%d" % (os.path.basename(rel), os.path.getsize(p)))
    except Exception as e:
        base.log("语义召回：拿不到模型指纹（%r）—— 向量维持现状，不清空" % (e,))
        return None
    with _LOCK:
        _FP, _FP_DIR = "|".join(parts), d
    return _FP


def stamp():
    """`(模型指纹, 配方版本)` —— 写进 / 校验 `vectors.json` 的那个东西。

    模型不在 → **None**（调用方维持现状，不清空向量）。
    """
    fp = fingerprint()
    return None if fp is None else (fp, VEC_VERSION)


# ── 自检用的假 embedder ─────────────────────────────────────────────
#
# 离线自检不许加载真模型（慢，而且模型不在手机上时也得能跑）。
# 假的这个吐**真的 512 维单位向量**，所以 `semantic.py` 那条路（点乘、曲线、
# tiebreak）是被原样跑过的，不是另写一套。
#
# 打分规则（够简单，能一眼看出该得几分）：
#   · 查询里**相邻两字**（bigram）落在记忆里的比例 → 相似度
#   · 所以「他喜欢喝什么」× 「喜欢喝美式咖啡」≈ 0.9（对上了）
#   · 「他喜欢喝什么」× 「住在青岛」        = 0（一个字都没挨上）
# 中文原样哈希到固定的几维上，于是点乘就正好等于「重合的 bigram 占比」。

_DIM = DIM


def _char_idx(ch):
    return (ord(ch) * 2654435761) % _DIM


class FakeEmbedder(object):
    """假的：不加载任何库，确定性、可复现。给自检用。"""

    def __init__(self, scale=0.9):
        self.scale = float(scale)
        self.queries = 0
        # 自检拿来分「复用」还是「重算」：作废/自愈是不是真的发生了，看这个计数
        self.fact_batches = 0
        self.fact_rows = 0

    # -- 内部：一句话 → 512 维「bigram 指示向量」（未归一化） -----------
    @staticmethod
    def _grams(text):
        s = "".join(c for c in (text or "") if "\u4e00" <= c <= "\u9fff")
        return set(s[i:i + 2] for i in range(max(0, len(s) - 1)))

    def _vec(self, text):
        v = [0.0] * _DIM
        for g in self._grams(text):
            v[_char_idx(g[0])] = 1.0
            v[_char_idx(g[1])] = 1.0
        return v

    @staticmethod
    def _unit(v):
        n = sum(x * x for x in v) ** 0.5
        return [0.0] * _DIM if n <= 0 else [x / n for x in v]

    # -- 真 embedder 的那三个接口 --------------------------------------
    def encode(self, texts):
        return [self._unit(self._vec(t)) for t in texts]

    def encode_query(self, text):
        self.queries += 1
        return self._unit(self._vec(text))

    def encode_facts(self, texts):
        self.fact_batches += 1
        self.fact_rows += len(texts)
        return [self._unit(self._vec(t)) for t in texts]
