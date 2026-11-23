"""Token counting for LLM context budgeting.

Two different tokenizers matter in a RAG system:

* the **embedding model's** tokenizer bounds chunk size (see ``EmbeddingModel.count_tokens``);
* the **LLM's** tokenizer bounds the prompt. We use tiktoken ``cl100k_base`` as a
  provider-neutral approximation. If its BPE file cannot be loaded (offline first run),
  we fall back to a conservative heuristic and log it once — never silently.
"""

from __future__ import annotations

import math
import re
from functools import lru_cache

from app.core.logging import get_logger

logger = get_logger(__name__)
_WORD_RE = re.compile(r"\w+|[^\w\s]", re.UNICODE)


class TokenCounter:
    """Counts LLM tokens for budgeting prompts."""

    def __init__(self) -> None:
        self._encoding = None
        self.exact = False
        try:
            import tiktoken

            self._encoding = tiktoken.get_encoding("cl100k_base")
            self.exact = True
        except Exception as exc:  # network/IO failure on first download
            logger.warning(
                "tiktoken unavailable; using heuristic token counts",
                extra={"error": type(exc).__name__},
            )

    def count(self, text: str) -> int:
        """Return the number of tokens in ``text``."""
        if not text:
            return 0
        if self._encoding is not None:
            return len(self._encoding.encode(text, disallowed_special=()))
        # Heuristic: ~1.3 tokens per word/punctuation unit, rounded up (over-estimates).
        return math.ceil(len(_WORD_RE.findall(text)) * 1.3)

    def truncate(self, text: str, max_tokens: int) -> str:
        """Truncate ``text`` to at most ``max_tokens`` tokens."""
        if max_tokens <= 0:
            return ""
        if self._encoding is not None:
            ids = self._encoding.encode(text, disallowed_special=())
            return text if len(ids) <= max_tokens else self._encoding.decode(ids[:max_tokens])
        words = text.split()
        return " ".join(words[: int(max_tokens / 1.3)])


@lru_cache
def get_token_counter() -> TokenCounter:
    """Process-wide token counter."""
    return TokenCounter()
