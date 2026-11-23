"""Document-level metadata extraction (language-agnostic statistics, title fallback)."""

from __future__ import annotations

from pathlib import PurePath
from typing import Any

from app.ingestion.chunking import Chunk
from app.ingestion.parsers.base import ParsedDocument


def derive_title(parsed: ParsedDocument, filename: str) -> str:
    """Prefer embedded metadata title, then the first heading, then the file stem."""
    if parsed.title and len(parsed.title.strip()) > 2:
        return parsed.title.strip()[:500]
    if parsed.sections:
        return parsed.sections[0].title[:500]
    return PurePath(filename).stem.replace("_", " ").replace("-", " ").strip()[:500] or filename


def document_statistics(parsed: ParsedDocument, chunks: list[Chunk]) -> dict[str, Any]:
    tokens = [c.token_count for c in chunks]
    return {
        **parsed.metadata,
        "characters": len(parsed.text),
        "words": len(parsed.text.split()),
        "sections": len(parsed.sections),
        "section_titles": [s.title for s in parsed.sections[:50]],
        "chunk_tokens_avg": round(sum(tokens) / len(tokens), 1) if tokens else 0,
        "chunk_tokens_max": max(tokens) if tokens else 0,
    }
