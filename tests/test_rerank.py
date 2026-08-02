"""Re-scoring the dense candidate pool against the literal query text.

A bi-encoder compares independent vectors; a cross-encoder reads the query
and a candidate together, which is what actually tells "on-topic" apart from
"shares vocabulary". The real model is swapped for a fake scorer here —
loading it would pull torch into every test run for behaviour this module
does not need a real model to verify.
"""

import pytest

from lenses.config import DEFAULT_RERANKER, ConfigError, load_config
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


# Which cross-encoder runs. Unlike the embedder this is a local model name
# rather than an endpoint, and unlike the embedder a wrong value writes no
# artefact — so it is optional, and the default has to hold.

@pytest.fixture
def env(monkeypatch, tmp_path):
    """A hermetic environment: every required setting, no .env on disk."""
    for name, value in {
        "llm_base_url": "https://example.invalid/v1",
        "llm_model": "m",
        "llm_api_key": "k",
        "embedder_base_url": "https://example.invalid/v1",
        "embedder_model": "e",
        "embedder_api_key": "k",
        "embedder_dim": "768",
        "min_coverage": "0.5",
    }.items():
        monkeypatch.setenv(name, value)
    for name in ("reranker_model", "reranker_kind", "reranker_base_url",
                 "reranker_api_key"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "absent.env"


def test_the_reranker_defaults_when_unset(env):
    assert load_config(env).reranker_model == DEFAULT_RERANKER


def test_an_explicit_reranker_wins(env, monkeypatch):
    monkeypatch.setenv("reranker_model", "BAAI/bge-reranker-base")
    assert load_config(env).reranker_model == "BAAI/bge-reranker-base"


def test_a_blank_reranker_falls_back_rather_than_naming_nothing(env, monkeypatch):
    """A commented-out line left as `reranker_model=` must not load model ''."""
    monkeypatch.setenv("reranker_model", "   ")
    assert load_config(env).reranker_model == DEFAULT_RERANKER


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


# Which *kind* of second pass runs. The cross-encoder needs no endpoint; the
# llm needs one, and must say so rather than quietly running the other.

def test_the_cross_encoder_is_the_zero_config_default(env):
    config = load_config(env)
    assert config.reranker_kind == "cross-encoder"
    assert config.reranker is None


def test_an_unknown_kind_is_refused(env, monkeypatch):
    monkeypatch.setenv("reranker_kind", "crossencoder")
    with pytest.raises(ConfigError, match="reranker_kind"):
        load_config(env)


def test_the_llm_kind_needs_its_endpoint(env, monkeypatch):
    """Fail closed. Falling back to the cross-encoder here would rank by a
    model nobody configured, and say nothing about having done so."""
    monkeypatch.setenv("reranker_kind", "llm")
    monkeypatch.setenv("reranker_model", "gemma-4-e2b-it-qat")
    with pytest.raises(ConfigError, match="reranker_base_url"):
        load_config(env)


def test_the_llm_kind_reads_its_own_endpoint(env, monkeypatch):
    monkeypatch.setenv("reranker_kind", "llm")
    monkeypatch.setenv("reranker_base_url", "http://localhost:1234/v1/")
    monkeypatch.setenv("reranker_model", "gemma-4-e2b-it-qat")
    monkeypatch.setenv("reranker_api_key", "k")
    config = load_config(env)
    assert config.reranker.base_url == "http://localhost:1234/v1"   # trailing / trimmed
    assert config.reranker.model == "gemma-4-e2b-it-qat"
    assert config.reranker_model == "gemma-4-e2b-it-qat"


def test_the_ranking_endpoint_is_not_the_decomposition_one(env, monkeypatch):
    """`llm_*` is the hosted model that cuts skills up; this one runs on every
    search and wants to be local. Sharing the setting would send every query
    to a paid provider."""
    monkeypatch.setenv("reranker_kind", "llm")
    monkeypatch.setenv("reranker_base_url", "http://localhost:1234/v1")
    monkeypatch.setenv("reranker_model", "gemma-4-e2b-it-qat")
    monkeypatch.setenv("reranker_api_key", "k")
    config = load_config(env)
    assert config.reranker.base_url != config.llm.base_url
