"""A ranking failure must cost the caller the ordering, not the answer.

The dense pool is already computed and paid for by the time the second pass
runs. Turning that into {"error": ...} - which is what find_lenses did before
this - throws away 60/68 worth of results to report that 65/68 was not
available.
"""

from types import SimpleNamespace

import pytest

from lenses import mcp_server
from lenses.llm_rerank import LlmRerankError
from lenses.search import Corpus, IndexedPart


def indexed(part_id: str, vector=(1.0, 0.0), skill_id="lab/skill") -> IndexedPart:
    return IndexedPart(
        skill_id=skill_id, version="v1", part_id=part_id, title=part_id,
        applies_to=f"Use when {part_id}.", kind="reference", sha256="h",
        vector=vector,
    )


@pytest.fixture
def corpus() -> Corpus:
    return Corpus([indexed("alpha"), indexed("beta", (0.9, 0.1)),
                   indexed("gamma", (0.8, 0.2))])


@pytest.fixture
def config():
    return SimpleNamespace(embedder=None, embedder_dim=2, reranker=None)


@pytest.fixture(autouse=True)
def no_embedder(monkeypatch):
    monkeypatch.setattr(mcp_server, "embed_query", lambda *a, **k: [1.0, 0.0])


def _raise_llm_error(intent, hits, limit):
    raise LlmRerankError("down")


def test_with_no_ranking_configured_the_dense_order_answers(monkeypatch, config, corpus):
    monkeypatch.setattr(mcp_server, "second_pass", lambda config: None)
    answer = mcp_server._find_one("a need", config, corpus, 2, None, None)
    assert answer["ranked_by"] == "dense"
    assert "warning" not in answer
    assert [r["ref"] for r in answer["results"]] == [
        "lab/skill#alpha@v1", "lab/skill#beta@v1"]


def test_a_configured_pass_is_reported_as_llm(monkeypatch, config, corpus):
    monkeypatch.setattr(
        mcp_server, "second_pass",
        lambda config: lambda intent, hits, limit: list(reversed(hits))[:limit],
    )
    answer = mcp_server._find_one("a need", config, corpus, 2, None, None)
    assert answer["ranked_by"] == "llm"
    assert "warning" not in answer


def test_a_ranking_failure_returns_the_dense_answer(monkeypatch, config, corpus):
    def explode(intent, hits, limit):
        raise LlmRerankError("localhost:1234 refused the connection")

    monkeypatch.setattr(mcp_server, "second_pass", lambda config: explode)
    answer = mcp_server._find_one("a need", config, corpus, 2, None, None)

    assert answer["ranked_by"] == "dense"
    assert len(answer["results"]) == 2, "the pool was paid for; do not throw it away"
    assert "refused the connection" in answer["warning"]


def test_the_degraded_answer_is_the_dense_top_n_not_the_pool_head(monkeypatch, config):
    """The 60/68 baseline was measured with `rank(limit=n)` - whose `per_skill`
    default is 2. The candidate pool uses 4, so its head is a different list.

    Here skill A holds the three best parts. The dense answer for limit=3 is
    A0, A1 and then B0, because A2 is over A's cap of two. Slicing the pool
    would answer A0, A1, A2 - an ordering nothing measured.
    """
    parts = [
        indexed("a0", (1.0, 0.0), "lab/a"),
        indexed("a1", (1.0, 0.1), "lab/a"),
        indexed("a2", (1.0, 0.2), "lab/a"),
        indexed("b0", (1.0, 0.3), "lab/b"),
    ]
    monkeypatch.setattr(mcp_server, "second_pass", lambda config: _raise_llm_error)
    answer = mcp_server._find_one("a need", config, Corpus(parts), 3, None, None)
    assert [r["ref"] for r in answer["results"]] == [
        "lab/a#a0@v1", "lab/a#a1@v1", "lab/b#b0@v1"]


def test_find_lenses_does_not_turn_a_ranking_failure_into_an_error(
    monkeypatch, config, corpus
):
    monkeypatch.setattr(mcp_server, "startup", lambda: (config, corpus))
    monkeypatch.setattr(mcp_server, "second_pass", lambda config: _raise_llm_error)
    answer = mcp_server.find_lenses("a need", limit=2)
    assert "error" not in answer
    assert answer["ranked_by"] == "dense"
    assert answer["results"]


def test_one_failing_intent_does_not_erase_a_batch(monkeypatch, config, corpus):
    """find_lenses_batch ran every intent inside one try, as a comprehension,
    so a failure on the last of eight discarded the seven that resolved. The
    batch call exists to gather a whole spec's needs at once, which makes it
    the call that loses the most."""
    calls = {"n": 0}

    def flaky(intent, hits, limit):
        calls["n"] += 1
        if calls["n"] == 2:
            raise LlmRerankError("down")
        return hits[:limit]

    monkeypatch.setattr(mcp_server, "startup", lambda: (config, corpus))
    monkeypatch.setattr(mcp_server, "second_pass", lambda config: flaky)
    answer = mcp_server.find_lenses_batch(["first", "second", "third"], limit=2)

    assert "error" not in answer
    kinds = [entry["ranked_by"] for entry in answer["results"]]
    assert kinds == ["llm", "dense", "llm"]
    assert all(entry["results"] for entry in answer["results"])
    assert "warning" in answer["results"][1]
    assert "warning" not in answer["results"][0]


def test_startup_probes_a_configured_ranking_endpoint(monkeypatch):
    """A typo in .env must be a server that does not start, not a server that
    answers every query five points worse than it says it does."""
    from lenses.config import ConfigError

    monkeypatch.setattr(mcp_server, "_config", None)
    monkeypatch.setattr(mcp_server, "_corpus", None)
    monkeypatch.setattr(
        mcp_server, "load_config",
        lambda path: SimpleNamespace(
            embedder=None, embedder_dim=2,
            reranker=SimpleNamespace(base_url="http://nowhere/v1", model="m",
                                     api_key="k"),
        ),
    )
    monkeypatch.setattr(mcp_server, "load_index", lambda path, dim: [])

    def refuse(system, user):
        raise LlmRerankError("http://nowhere/v1: connection refused")

    monkeypatch.setattr(mcp_server, "completer_for", lambda endpoint, **kw: refuse)
    with pytest.raises(ConfigError, match="http://nowhere/v1"):
        mcp_server.startup()

    assert mcp_server._config is None, "a failed probe must leave startup retryable"


def test_startup_probes_nothing_when_no_endpoint_is_configured(monkeypatch):
    """No endpoint is a supported configuration, so there is nothing to probe
    and startup must not invent a reason to fail."""
    monkeypatch.setattr(mcp_server, "_config", None)
    monkeypatch.setattr(mcp_server, "_corpus", None)
    monkeypatch.setattr(
        mcp_server, "load_config",
        lambda path: SimpleNamespace(embedder=None, embedder_dim=2, reranker=None),
    )
    monkeypatch.setattr(mcp_server, "load_index", lambda path, dim: [])
    monkeypatch.setattr(
        mcp_server, "completer_for",
        lambda endpoint, **kw: pytest.fail("nothing to probe"),
    )
    config, _ = mcp_server.startup()
    assert config.reranker is None


def test_the_ranking_timeout_is_short_enough_to_degrade_from():
    """Measured median for this call is 0.23 s. The old default was 120 s, so
    a hung endpoint cost two minutes before returning nothing - which is the
    anti-pattern that a slow response is worse than no response."""
    import inspect

    from lenses.llm_rerank import completer_for

    assert inspect.signature(completer_for).parameters["timeout"].default == 5.0
