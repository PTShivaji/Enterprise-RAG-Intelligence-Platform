"""Local Sentence-Transformers embedding model."""

from __future__ import annotations

import threading

import numpy as np

from app.core.logging import get_logger
from app.embeddings.base import EmbeddingModel

logger = get_logger(__name__)

# Some retrieval models are trained with asymmetric instruction prefixes.
_QUERY_PREFIXES = {
    "intfloat/e5": ("query: ", "passage: "),
    "BAAI/bge": ("Represent this sentence for searching relevant passages: ", ""),
}


class SentenceTransformerEmbedding(EmbeddingModel):
    """Wraps ``sentence_transformers.SentenceTransformer`` (loaded once, thread-safe encode)."""

    def __init__(self, model_name: str, *, device: str = "cpu") -> None:
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model", extra={"model": model_name, "device": device})
        self._model = SentenceTransformer(model_name, device=device)
        self._lock = threading.Lock()
        self.name = model_name
        get_dim = getattr(self._model, "get_embedding_dimension", None) or self._model.get_sentence_embedding_dimension
        dim = get_dim()
        if dim is None:
            raise RuntimeError(f"Could not determine embedding dimension for {model_name}")
        self.dimension = int(dim)
        self.max_seq_length = int(self._model.max_seq_length)
        self._query_prefix, self._doc_prefix = next(
            (v for k, v in _QUERY_PREFIXES.items() if model_name.startswith(k)), ("", "")
        )

    def count_tokens(self, text: str) -> int:
        return len(self._model.tokenizer.tokenize(text))

    def _encode(self, texts: list[str], *, batch_size: int, is_query: bool) -> np.ndarray:
        prefix = self._query_prefix if is_query else self._doc_prefix
        inputs = [prefix + t for t in texts] if prefix else texts
        with self._lock:  # torch modules are not guaranteed re-entrant across threads
            return self._model.encode(
                inputs,
                batch_size=batch_size,
                convert_to_numpy=True,
                normalize_embeddings=False,
                show_progress_bar=False,
            )
