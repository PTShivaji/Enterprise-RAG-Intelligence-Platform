"""Data-quality checks for the bundled evaluation dataset.

Every evidence phrase must be found in its expected document under exactly the
same matching rule the retrieval metrics use; otherwise a labelling mistake
would silently lower (or inflate) the reported benchmark numbers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.evaluation.metrics import evidence_hits
from app.evaluation.runner import SAMPLE_DATASET, load_sample_dataset
from app.ingestion.parsers import detect_file_type, parse_document

CORPUS = SAMPLE_DATASET.parent / "sample_corpus"


@pytest.fixture(scope="module")
def corpus_text() -> dict[str, str]:
    texts = {}
    for path in CORPUS.iterdir():
        data = path.read_bytes()
        texts[path.name] = parse_document(detect_file_type(path.name, data[:8]), data).text
    return texts


def test_dataset_loads_and_ids_are_unique() -> None:
    items = load_sample_dataset()
    assert len(items) >= 30
    assert len({i.id for i in items}) == len(items)
    assert sum(not i.answerable for i in items) >= 3
    raw = json.loads(Path(SAMPLE_DATASET).read_text(encoding="utf-8"))
    assert {i["category"] for i in raw["items"]} >= {"direct", "paraphrase", "distractor", "multi", "unanswerable"}


HOLDOUT = SAMPLE_DATASET.parent / "sample_qa_holdout.json"


@pytest.mark.parametrize("dataset", [SAMPLE_DATASET, HOLDOUT], ids=["dev", "holdout"])
def test_every_evidence_phrase_exists_in_its_expected_document(corpus_text: dict[str, str], dataset: Path) -> None:
    from app.schemas.rag import EvalItem

    items = [EvalItem.model_validate(i) for i in json.loads(dataset.read_text(encoding="utf-8"))["items"]]
    dev_questions = {i.question for i in load_sample_dataset()}
    if dataset == HOLDOUT:
        assert not dev_questions & {i.question for i in items}, "holdout must not overlap the dev set"
    for item in items:
        if not item.answerable:
            assert not item.evidence
            continue
        assert item.evidence and item.expected_documents, item.id
        (doc,) = item.expected_documents
        assert doc in corpus_text, f"{item.id}: unknown document {doc}"
        hits = evidence_hits(corpus_text[doc], item.evidence)
        assert hits == set(range(len(item.evidence))), f"{item.id}: evidence not found in {doc}"
