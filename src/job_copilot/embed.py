"""本地向量化（M6 匹配模块的基础）。

用 fastembed + BAAI/bge-small-zh-v1.5（512维中文语义模型），全程离线：
模型文件在 data/models/fast-bge-small-zh-v1.5/（跑 tools/download-model.sh 获取，GCS 直连）。
不依赖任何 embedding API——DeepSeek 无 embedding 接口，且本地化本身是简历可写的实操。

设计：单例懒加载模型；embed() 批量返回 np.ndarray (n, 512)。
下一步（pgvector 到位后）：向量存储从 SQLite blob 换成 pgvector，这层接口不变。
"""

from __future__ import annotations

import os
from typing import List

import numpy as np

from .config import DATA_DIR

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
MODEL_CACHE = str(DATA_DIR / "models")
DIM = 512

# 离线：跳过 HuggingFace 网络探测，直接用本地 GCS 目录（本机代理无法访问 HF）
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

_model = None


def get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(model_name=MODEL_NAME, cache_dir=MODEL_CACHE)
    return _model


def embed(texts: List[str]) -> np.ndarray:
    """批量向量化，返回 L2 归一化后的 (n, DIM) 数组（点积即余弦相似度）。"""
    if not texts:
        return np.zeros((0, DIM), dtype=np.float32)
    vecs = np.array(list(get_model().embed(list(texts))), dtype=np.float32)
    vecs = np.nan_to_num(vecs, nan=0.0, posinf=0.0, neginf=0.0)  # 兜底异常输出
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (vecs / norms).astype(np.float32)


def embed_one(text: str) -> np.ndarray:
    return embed([text])[0]
