"""Telling a caller when the catalogue does not cover what they asked.

Measured 2026-08-03: `find_lenses` answers a question about milling aluminium
with a usability heuristic, at a dense score inside the range genuine hits
occupy. Nothing in the response distinguishes that from an answer, so an agent
cites it. This is the signal that does.

It reports and never filters. Results come back either way — the model that
produces this label is the same one that showed a register bias and a
positional habit elsewhere in this project, and filtering on its judgement
would trade a visible wrong label for an invisible missing answer.
"""

from types import SimpleNamespace

import pytest

from lenses import mcp_server
from lenses.llm_rerank import LlmRerankError
from lenses.search import Corpus, IndexedPart
from lenses.taxonomy import Taxonomy, Label

TAXONOMY = Taxonomy(
    boundary="About software. Answer NONE for anything else.",
    labels=(
        Label(id="testing-practice", scope="writing automated tests",
              excludes="research with users", skills=("lab/skill",)),
    ),
)


def indexed(part_id: str, vector=(1.0, 0.0)) -> IndexedPart:
    return IndexedPart(
        skill_id="lab/skill", version="v1", part_id=part_id, title=part_id,
        applies_to=f"Use when {part_id}.", kind="reference", sha256="h",
        vector=vector,
    )


@pytest.fixture
def corpus() -> Corpus:
    return Corpus([indexed("alpha"), indexed("beta", (0.9, 0.1))])


@pytest.fixture
def config():
    return SimpleNamespace(
        embedder=None, embedder_dim=2,
        reranker=SimpleNamespace(base_url="http://local/v1", model="m", api_key="k"),
    )


@pytest.fixture(autouse=True)
def stubs(monkeypatch):
    monkeypatch.setattr(mcp_server, "embed_query", lambda *a, **k: [1.0, 0.0])
    monkeypatch.setattr(
        mcp_server, "second_pass",
        lambda config: lambda intent, hits, limit: hits[:limit],
    )
    monkeypatch.setattr(mcp_server, "_taxonomy", TAXONOMY)


def answering(label):
    """A classifier that always returns `label`, in the module's own shape."""
    return lambda config: (lambda intent: label)


def test_a_covered_need_reports_its_subject(monkeypatch, config, corpus):
    monkeypatch.setattr(mcp_server, "classifier", answering("testing-practice"))
    answer = mcp_server._find_one("a need", config, corpus, 2, None, None)
    assert answer["subject"] == "testing-practice"
    assert "warning" not in answer
    assert len(answer["results"]) == 2


def test_an_uncovered_need_is_said_out_loud_and_still_answered(
    monkeypatch, config, corpus
):
    monkeypatch.setattr(mcp_server, "classifier", answering(None))
    answer = mcp_server._find_one("milling aluminium", config, corpus, 2, None, None)

    assert answer["subject"] is None
    assert "does not cover" in answer["warning"]
    assert len(answer["results"]) == 2, "report, never filter"


def test_an_unreadable_classification_makes_no_claim(monkeypatch, config, corpus):
    """A model that answered nothing usable has not said the corpus is empty.
    Warning here would put a scare on a perfectly good result."""
    monkeypatch.setattr(mcp_server, "classifier", answering(""))
    answer = mcp_server._find_one("a need", config, corpus, 2, None, None)
    assert answer["subject"] is None
    assert "warning" not in answer


def test_a_classifier_failure_never_costs_the_search(monkeypatch, config, corpus):
    """The coverage signal is an addition. If the endpoint that produces it
    falls over, the search it was added to must still answer."""
    def explode(config):
        def fail(intent):
            raise LlmRerankError("http://local/v1: connection refused")
        return fail

    monkeypatch.setattr(mcp_server, "classifier", explode)
    answer = mcp_server._find_one("a need", config, corpus, 2, None, None)
    assert answer["subject"] is None
    assert "warning" not in answer
    assert len(answer["results"]) == 2


def test_without_a_ranking_endpoint_there_is_no_coverage_signal(
    monkeypatch, config, corpus
):
    """The classifier runs on the ranking endpoint. Configure neither and the
    catalogue stops reporting its own edges - which is the strongest reason to
    configure it, and is documented rather than worked around."""
    monkeypatch.setattr(mcp_server, "second_pass", lambda config: None)
    config.reranker = None
    answer = mcp_server._find_one("milling aluminium", config, corpus, 2, None, None)
    assert answer["subject"] is None
    assert "warning" not in answer
    assert answer["ranked_by"] == "dense"


def test_a_ranking_failure_and_an_uncovered_need_are_both_reported(
    monkeypatch, config, corpus
):
    def explode(intent, hits, limit):
        raise LlmRerankError("down")

    monkeypatch.setattr(mcp_server, "second_pass", lambda config: explode)
    monkeypatch.setattr(mcp_server, "classifier", answering(None))
    answer = mcp_server._find_one("milling aluminium", config, corpus, 2, None, None)

    assert answer["ranked_by"] == "dense"
    assert "does not cover" in answer["warning"]
    assert "ranking pass was unavailable" in answer["warning"]
    assert len(answer["results"]) == 2
