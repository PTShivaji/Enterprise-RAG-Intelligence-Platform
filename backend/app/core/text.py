"""Lightweight lexical utilities shared by retrieval, context building and evaluation."""

from __future__ import annotations

import re

_STOPWORD_TEXT = """
a about above after again against all am an and any are as at be because been before being below between
both but by can could did do does doing down during each few for from further had has have having he her
here hers herself him himself his how i if in into is it its itself just me more most my myself no nor not
now of off on once only or other our ours ourselves out over own same she should so some such than that the
their theirs them themselves then there these they this those through to too under until up very was we were
what when where which while who whom why will with would you your yours yourself yourselves also may must
shall per via within without please tell explain describe give show list done get got
"""
STOPWORDS = frozenset(_STOPWORD_TEXT.split())

_TOKEN_RE = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)*")
_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\n{2,}|\n(?=\s*(?:[-*•]|\d+[.)])\s)")


def light_stem(token: str) -> str:
    """Very small suffix stripper (policies->policy, requests->request, running->run)."""
    if len(token) <= 4:
        return token
    for suffix, repl in (("ies", "y"), ("sses", "ss"), ("ing", ""), ("ed", ""), ("es", ""), ("s", "")):
        if token.endswith(suffix) and len(token) - len(suffix) >= 3:
            stem = token[: -len(suffix)] + repl
            if suffix == "es" and not token.endswith(("ches", "shes", "xes", "zes", "sses")):
                stem = token[:-1]
            return stem
    return token


def tokenize(text: str) -> list[str]:
    """Lower-cased word tokens."""
    return _TOKEN_RE.findall(text.lower())


def content_terms(text: str) -> list[str]:
    """Stemmed tokens with stopwords and 1-char tokens removed."""
    return [light_stem(t) for t in tokenize(text) if t not in STOPWORDS and len(t) > 1]


def split_sentences(text: str) -> list[str]:
    """Split text into sentences / list items (keeps bullets as separate items)."""
    return [s.strip() for s in _SENT_RE.split(text) if s and s.strip()]


def containment(needle_terms: list[str], haystack_terms: set[str]) -> float:
    """Fraction of ``needle_terms`` present in ``haystack_terms`` (0 if needle empty)."""
    if not needle_terms:
        return 0.0
    return sum(1 for t in needle_terms if t in haystack_terms) / len(needle_terms)


def jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def shingles(text: str, n: int = 3) -> set[str]:
    toks = tokenize(text)
    if len(toks) < n:
        return {" ".join(toks)} if toks else set()
    return {" ".join(toks[i : i + n]) for i in range(len(toks) - n + 1)}
