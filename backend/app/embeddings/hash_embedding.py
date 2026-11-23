"""Deterministic hashed bag-of-words embedding — a fast test double.

NOT a semantic model: it only captures lexical overlap. It exists so the
database/retrieval plumbing can be tested in milliseconds without loading a
neural network. It is selected only via ``EMBEDDING_PROVIDER=hash``.
"""

from __future__ import annotations

import hashlib
import re

import numpy as np

from app.embeddings.base import EmbeddingModel

_TOKEN = re.compile(r"[a-z0-9]+")


class HashEmbedding(EmbeddingModel):
    def __init__(self, dimension: int = 384) -> None:
        self.name = f"hash-bow-{dimension}"
        self.dimension = dimension
        self.max_seq_length = 10_000

    def count_tokens(self, text: str) -> int:
        return len(_TOKEN.findall(text.lower()))

    def _encode(self, texts: list[str], *, batch_size: int, is_query: bool) -> np.ndarray:
        out = np.zeros((len(texts), self.dimension), dtype=np.float32)
        for row, text in enumerate(texts):
            for token in _TOKEN.findall(text.lower()):
                h = int.from_bytes(hashlib.md5(token.encode(), usedforsecurity=False).digest()[:4], "little")
                out[row, h % self.dimension] += 1.0 if (h >> 31) & 1 else -1.0
            if not out[row].any():
                out[row, 0] = 1.0
        return out
