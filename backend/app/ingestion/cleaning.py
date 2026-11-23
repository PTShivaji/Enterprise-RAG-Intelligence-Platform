"""Text normalisation applied to every extracted block before chunking."""

from __future__ import annotations

import re
import unicodedata

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_HYPHEN_BREAK = re.compile(r"(\w)-\n(\w)")
_SPACES = re.compile(r"[ \t ]+")
_MANY_NEWLINES = re.compile(r"\n{3,}")
_LIGATURES = {"ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl"}


def normalize_text(text: str) -> str:
    """Normalise unicode, repair hyphenated line breaks and collapse whitespace.

    Paragraph breaks (blank lines) are preserved because the recursive chunker
    uses them as its highest-priority split points.
    """
    if not text:
        return ""
    for lig, repl in _LIGATURES.items():
        text = text.replace(lig, repl)
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL.sub("", text)
    text = _HYPHEN_BREAK.sub(r"\1\2", text)
    text = _SPACES.sub(" ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _MANY_NEWLINES.sub("\n\n", text)
    return text.strip()


def join_wrapped_lines(text: str) -> str:
    """Join visually wrapped lines inside a paragraph into a single line."""
    return " ".join(part.strip() for part in text.split("\n") if part.strip())
