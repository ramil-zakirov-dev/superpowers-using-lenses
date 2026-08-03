"""Re-scoring the dense candidate pool against the literal query text.

A bi-encoder compares independent vectors; a cross-encoder reads the query
and a candidate together, which is what actually tells "on-topic" apart from
"shares vocabulary". The real model is swapped for a fake scorer here —
loading it would pull torch into every test run for behaviour this module
does not need a real model to verify.
"""

import pytest

from lenses.rerank import RerankError, _models, rerank, scorer_for
from lenses.search import Hit, IndexedPart, SearchError


def part(pid, applies_to):
    return IndexedPart(
        skill_id="a/b", version="abcdef123456", part_id=pid, title=pid,
        applies_to=applies_to, kind="lens", sha256="h", vector=(1.0, 0.0),
    )


def hit(pid, applies_to, score=0.5):
    return Hit(score=score, part=part(pid, applies_to))


def by_length(intent, documents):
    """A deterministic fake: longer applies_to scores higher."""
    return [float(len(doc)) for doc in documents]


def test_reorders_by_the_injected_scorer():
    hits = [hit("short", "x"), hit("long", "a much longer applies_to statement")]
    result = rerank("intent", hits, top_n=2, score=by_length)
    assert [h.part.part_id for h in result] == ["long", "short"]


def test_truncates_to_top_n():
    hits = [hit(f"p{i}", "x" * i) for i in range(5)]
    result = rerank("intent", hits, top_n=2, score=by_length)
    assert [h.part.part_id for h in result] == ["p4", "p3"]


def test_score_reflects_the_reranker_not_the_original():
    hits = [hit("p", "abc", score=0.1)]
    result = rerank("intent", hits, top_n=1, score=by_length)
    assert result[0].score == 3.0


def test_scores_applies_to_not_title_or_id():
    seen = {}

    def capture(intent, documents):
        seen["documents"] = documents
        return [0.0 for _ in documents]

    rerank("intent", [hit("p", "the applies_to text")], top_n=1, score=capture)
    assert seen["documents"] == ["the applies_to text"]


def test_empty_candidates_do_not_call_the_scorer():
    def explode(intent, documents):
        raise AssertionError("rerank called the model for an empty pool")

    assert rerank("intent", [], top_n=5, score=explode) == []


def test_top_n_below_one_is_refused():
    with pytest.raises(SearchError):
        rerank("intent", [hit("p", "x")], top_n=0, score=by_length)


def test_asking_for_a_scorer_does_not_load_the_model():
    """Building the scorer must stay free — importing torch at config time
    would put half a gigabyte in the path of every run that never searches."""
    scorer_for("some/model-that-does-not-exist")
    assert "some/model-that-does-not-exist" not in _models


def test_a_broken_model_is_reported_as_a_rerank_failure(monkeypatch):
    """sentence-transformers, torch and huggingface_hub each raise their own
    type; find_lenses needs one readable error, not whichever leaked out."""

    class Exploding:
        def predict(self, pairs):
            raise ValueError("weights are corrupt")

    monkeypatch.setitem(_models, "broken/model", Exploding())
    with pytest.raises(RerankError, match="broken/model"):
        scorer_for("broken/model")("intent", ["a document"])
