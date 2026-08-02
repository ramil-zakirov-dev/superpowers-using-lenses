"""Re-scoring the dense candidate pool against the literal query text.

A bi-encoder compares independent vectors; a cross-encoder reads the query
and a candidate together, which is what actually tells "on-topic" apart from
"shares vocabulary". The real model is swapped for a fake scorer here —
loading it would pull torch into every test run for behaviour this module
does not need a real model to verify.
"""

import pytest

from lenses.rerank import confident, rerank
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


def test_confident_when_the_top_score_clears_the_threshold():
    assert confident([hit("p", "x", score=5.0)], threshold=0.0) is True


def test_not_confident_when_the_top_score_misses_the_threshold():
    assert confident([hit("p", "x", score=-9.0)], threshold=-8.0) is False


def test_the_threshold_is_a_boundary_not_a_strict_inequality():
    assert confident([hit("p", "x", score=-8.0)], threshold=-8.0) is True


def test_nothing_to_be_confident_about_in_an_empty_list():
    assert confident([], threshold=-100.0) is False


def test_only_the_top_hit_is_checked():
    """Hits are assumed sorted best-first; a strong #2 does not rescue a weak #1."""
    hits = [hit("weak", "x", score=-9.0), hit("strong", "y", score=5.0)]
    assert confident(hits, threshold=-8.0) is False
