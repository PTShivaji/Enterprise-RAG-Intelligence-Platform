"""Embedding model abstraction.

Any embedding backend (local Sentence-Transformers, a hosted API, a test double)
implements ``EmbeddingModel``. The rest of the system depends only on this
interface, so swapping models is a configuration change plus a re-index.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from app.core.exceptions import EmbeddingDimensionError


class EmbeddingModel(ABC):
    """Synchronous, CPU/GPU-bound embedding model (call via a thread from async code)."""

    name: str
    dimension: int
    max_seq_length: int

    @abstractmethod
    def _encode(self, texts: list[str], *, batch_size: int, is_query: bool) -> np.ndarray:
        """Return an ``(n, dimension)`` float32 array."""

    @abstractmethod
    def count_tokens(self, text: str) -> int:
        """Number of model tokens for ``text`` (excluding special tokens)."""

    def embed(self, texts: list[str], *, batch_size: int = 32, is_query: bool = False) -> np.ndarray:
        """Embed texts, L2-normalise them and validate the output dimension.

        Vectors are unit-normalised so that cosine similarity == dot product and
        pgvector's cosine distance is well-behaved regardless of model.
        """
        if not texts:
            return np.zeros((0, self.dimension), dtype=np.float32)
        vectors = np.asarray(self._encode(texts, batch_size=batch_size, is_query=is_query), dtype=np.float32)
        if vectors.ndim != 2 or vectors.shape[1] != self.dimension:
            raise EmbeddingDimensionError(
                f"Model '{self.name}' returned shape {vectors.shape}, expected (*, {self.dimension})"
            )
        if not np.all(np.isfinite(vectors)):
            raise EmbeddingDimensionError(f"Model '{self.name}' produced non-finite values")
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return vectors / norms
