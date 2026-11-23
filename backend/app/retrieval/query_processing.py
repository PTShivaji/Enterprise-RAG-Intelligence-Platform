"""Query preprocessing and transformation.

* ``preprocess_query``      normalise whitespace / control characters, bound length.
* ``contextualize_query``   make follow-up questions ("what about managers?")
                            retrievable by folding in the previous user question.
* ``prf_expansion_terms``   pseudo-relevance feedback (RM3-style, simplified):
                            mine discriminative terms from the top semantic hits
                            and add them to the *keyword* query. This closes the
                            vocabulary gap ("time off" vs "annual leave") for the
                            lexical retriever without any LLM call.
* ``generate_query_variants`` multi-query expansion through the configured LLM.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

from app.core.text import STOPWORDS, content_terms, tokenize
from app.retrieval.types import RetrievedChunk

MAX_QUERY_CHARS = 1000
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_ANAPHORA = {
    "it", "its", "that", "this", "those", "these", "they", "them", "their", "he", "she",
    "his", "her", "same", "above", "previous", "also",
}
_FOLLOWUP_OPENERS = ("what about", "how about", "and ", "what if", "why", "is that", "are they")


def preprocess_query(query: str) -> str:
    """Normalise a raw user query."""
    query = _CONTROL.sub(" ", query)
    query = re.sub(r"\s+", " ", query).strip()
    return query[:MAX_QUERY_CHARS]


def is_followup(question: str) -> bool:
    """Heuristic: does the question depend on previous turns to be understood?"""
    lowered = question.lower().strip()
    tokens = tokenize(lowered)
    content = [t for t in tokens if t not in STOPWORDS]
    if lowered.startswith(_FOLLOWUP_OPENERS):
        return True
    if any(t in _ANAPHORA for t in tokens) and len(content) <= 6:
        return True
    return len(content) <= 2


def contextualize_query(question: str, previous_user_questions: Sequence[str]) -> str:
    """Return the retrieval query, enriched with the last question for follow-ups.

    Only the *retrieval* query is rewritten; the LLM still sees the user's exact
    question plus the conversation history.
    """
    if not previous_user_questions or not is_followup(question):
        return question
    return f"{previous_user_questions[-1]} {question}"


def prf_expansion_terms(
    query: str,
    feedback: Sequence[RetrievedChunk],
    *,
    max_terms: int = 5,
    feedback_docs: int = 3,
    min_doc_freq: int = 2,
) -> list[str]:
    """Pick expansion terms from the top semantic results.

    Term weight = sum over feedback docs of (relevance weight x normalised tf),
    multiplied by an in-feedback IDF so terms appearing in every chunk (boilerplate)
    are penalised. Terms must occur in >= ``min_doc_freq`` feedback docs (when
    there are that many) to avoid drifting toward a single off-topic chunk.
    """
    docs = list(feedback[:feedback_docs])
    if not docs:
        return []
    query_terms = set(content_terms(query))
    doc_terms = [content_terms(d.content) for d in docs]
    df: Counter[str] = Counter()
    for terms in doc_terms:
        df.update(set(terms))
    required_df = min(min_doc_freq, len(docs))
    weights: Counter[str] = Counter()
    for doc, terms in zip(docs, doc_terms, strict=True):
        if not terms:
            continue
        rel = max(doc.vector_score or 0.0, 0.0) + 1e-3
        tf = Counter(terms)
        for term, count in tf.items():
            if term in query_terms or len(term) < 3 or term.isdigit() or df[term] < required_df:
                continue
            weights[term] += rel * (count / len(terms))
    n = len(docs)
    for term in list(weights):
        weights[term] *= math.log(1 + n / df[term]) + 0.5
    return [t for t, _ in weights.most_common(max_terms)]


MULTI_QUERY_PROMPT = (
    "Rewrite the user's search question into {n} alternative search queries that use "
    "different wording or synonyms but keep the exact meaning. Output one query per "
    "line, with no numbering and no commentary.\n\nQuestion: {question}"
)


def parse_query_variants(text: str, original: str, n: int) -> list[str]:
    """Parse an LLM's line-separated query variants, dropping junk and duplicates."""
    seen = {original.lower()}
    variants: list[str] = []
    for line in text.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip().strip('"')
        if 3 <= len(line) <= 300 and line.lower() not in seen:
            seen.add(line.lower())
            variants.append(line)
    return variants[:n]
