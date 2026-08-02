"""The listwise second pass: what it asks, and what it does with the answer.

The model is a fake here. What needs testing is not whether gemma ranks well
— scripts/eval_retrieval.py answers that against the live corpus — but that a
reply which is duplicated, truncated, out of range or absent still yields
`limit` results in a defensible order. Every case below was observed on the
real model except the ones marked otherwise.
"""

import pytest

from lenses.llm_rerank import (
    LlmRerankError,
    build_prompt,
    listwise_rank,
    parse_order,
)
from lenses.search import Hit, IndexedPart


def part(pid):
    return IndexedPart(
        skill_id="a/b", version="abcdef123456", part_id=pid, title=pid,
        applies_to=f"Use when {pid}.", kind="lens", sha256="h", vector=(1.0, 0.0),
    )


def pool(size=6):
    """Candidates in dense order, best first, with descending cosines."""
    return [Hit(score=0.9 - index / 100, part=part(f"p{index}")) for index in range(size)]


def replying(answer):
    return lambda system, user: answer


def ids(hits):
    return [hit.part.part_id for hit in hits]


def test_the_prompt_numbers_every_candidate():
    system, user = build_prompt("a need", pool(3), top_n=2)
    assert "1. Use when p0." in user
    assert "2. Use when p1." in user
    assert "3. Use when p2." in user


def test_the_prompt_states_the_pool_size_and_the_wanted_count():
    system, _ = build_prompt("a need", pool(20), top_n=6)
    assert "20 numbered entries" in system
    assert "the 6 most relevant" in system


def test_the_need_reaches_the_model_verbatim():
    _, user = build_prompt("keeping a Stripe call from hanging", pool(2), top_n=1)
    assert "keeping a Stripe call from hanging" in user


@pytest.mark.parametrize(
    "answer,expected",
    [
        ("3, 1, 2", [2, 0, 1]),
        ("3,1,2", [2, 0, 1]),
        ("Top 3: 3, 1, 2", [2, 0, 1]),      # a model that echoes the prompt
        ("3, 3, 1", [2, 0]),                # observed: repeats a number
        ("3, 99, 1", [2, 0]),               # out of range is dropped
        ("0, 2", [1]),                      # 0 is not a 1-based index
        ("none of them apply", []),
        ("", []),
    ],
    ids=["spaced", "tight", "echoed", "duplicate", "out-of-range", "zero",
         "prose", "empty"],
)
def test_parse_order(answer, expected):
    assert parse_order(answer, pool_size=3) == expected


def test_the_model_decides_the_order():
    assert ids(listwise_rank("need", pool(4), 3, replying("4, 2, 1"))) == ["p3", "p1", "p0"]


def test_a_duplicate_costs_a_position_not_a_result():
    """Observed on 4 of 34 live queries. Returning five for a limit of six
    would be a silent shortfall, so the dense order fills the gap."""
    hits = listwise_rank("need", pool(6), 3, replying("5, 5, 2"))
    assert ids(hits) == ["p4", "p1", "p0"]


def test_backfill_never_repeats_a_part():
    hits = listwise_rank("need", pool(6), 6, replying("2, 2, 2"))
    assert len(ids(hits)) == len(set(ids(hits))) == 6


def test_an_unusable_reply_degrades_to_the_dense_order():
    """Worse than a good ranking, never emptier than one."""
    assert ids(listwise_rank("need", pool(4), 3, replying("sorry!"))) == ["p0", "p1", "p2"]


def test_a_short_reply_is_filled_from_the_dense_order():
    assert ids(listwise_rank("need", pool(5), 4, replying("5"))) == ["p4", "p0", "p1", "p2"]


def test_the_dense_score_survives_the_reordering():
    """The number beside a result must keep meaning cosine-against-the-query,
    or a pool of uniformly poor matches stops being visible as one."""
    hits = listwise_rank("need", pool(3), 2, replying("3, 1"))
    assert [hit.score for hit in hits] == [pytest.approx(0.88), pytest.approx(0.90)]


def test_the_order_is_not_required_to_descend_by_score():
    """Consequence of the above, stated as a test so it is not read as a bug."""
    hits = listwise_rank("need", pool(3), 3, replying("3, 1, 2"))
    assert [round(hit.score, 2) for hit in hits] == [0.88, 0.90, 0.89]


def test_fewer_candidates_than_asked_for_is_not_padded():
    assert len(listwise_rank("need", pool(2), 6, replying("2, 1"))) == 2


def test_an_empty_pool_does_not_call_the_model():
    def explode(system, user):
        raise AssertionError("the model was called for an empty pool")

    assert listwise_rank("need", [], 6, explode) == []


def test_top_n_below_one_is_refused():
    with pytest.raises(LlmRerankError):
        listwise_rank("need", pool(3), 0, replying("1"))
