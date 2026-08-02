"""Ranking and reference parsing — the parts a server must not get wrong."""

import json

import pytest

from lenses.search import (
    Corpus,
    IndexedPart,
    SearchError,
    load_index,
    matches_stack,
    parse_ref,
    rank,
)


def part(skill="wondelai/release-it", pid="circuit-breaker", vector=(1.0, 0.0),
         kind="lens", stacks=(), version="34ac73394a51"):
    return IndexedPart(
        skill_id=skill, version=version, part_id=pid, title=pid,
        applies_to=f"Use when {pid}.", kind=kind, sha256="h",
        vector=vector, stacks=stacks,
    )


def test_reference_round_trips():
    ref = part().ref
    assert ref == "wondelai/release-it#circuit-breaker@34ac73394a51"
    assert parse_ref(ref) == ("wondelai/release-it", "circuit-breaker", "34ac73394a51")


@pytest.mark.parametrize(
    "bad",
    ["wondelai/release-it#circuit-breaker", "release-it@34ac73394a51",
     "wondelai/release-it#circuit-breaker@zzz", "", "a b#c@abcdef"],
    ids=["no-version", "no-part", "bad-version", "empty", "whitespace"],
)
def test_unpinned_or_malformed_references_are_refused(bad):
    """An unpinned citation silently starts naming different text one day."""
    with pytest.raises(SearchError):
        parse_ref(bad)


def test_ranking_is_by_similarity():
    parts = [
        part(pid="near", vector=(1.0, 0.0)),
        part(skill="a/b", pid="far", vector=(0.0, 1.0)),
    ]
    hits = rank([1.0, 0.0], parts)
    assert [hit.part.part_id for hit in hits] == ["near", "far"]
    assert hits[0].score == pytest.approx(1.0)


def test_at_most_two_parts_come_from_one_skill():
    """Neighbouring sections of one skill score alike; six of them is not an answer."""
    parts = [part(pid=f"p{i}", vector=(1.0, i / 100)) for i in range(6)]
    hits = rank([1.0, 0.0], parts, limit=6)
    assert len(hits) == 2


def test_the_cap_lets_other_skills_through():
    parts = [part(pid=f"p{i}", vector=(1.0, i / 100)) for i in range(6)]
    parts += [part(skill="ecc/api-design", pid="naming", vector=(0.9, 0.1))]
    hits = rank([1.0, 0.0], parts, limit=6)
    assert sorted({hit.part.skill_id for hit in hits}) == ["ecc/api-design", "wondelai/release-it"]


def test_per_skill_cap_is_adjustable():
    parts = [part(pid=f"p{i}", vector=(1.0, i / 100)) for i in range(6)]
    assert len(rank([1.0, 0.0], parts, limit=6, per_skill=4)) == 4


def test_limit_caps_the_result():
    parts = [part(skill=f"s/{i}", pid=f"p{i}", vector=(1.0, i / 100)) for i in range(10)]
    assert len(rank([1.0, 0.0], parts, limit=3)) == 3


def test_kind_filter_narrows():
    parts = [part(pid="l", kind="lens"), part(skill="a/b", pid="r", kind="reference")]
    assert [hit.part.kind for hit in rank([1.0, 0.0], parts, kind="reference")] == ["reference"]


def test_ties_break_deterministically():
    """Two runs of the same query must not disagree."""
    parts = [part(skill="a/x", pid="p", vector=(1.0, 0.0)),
             part(skill="b/y", pid="p", vector=(1.0, 0.0))]
    assert [h.part.ref for h in rank([1.0, 0.0], parts)] == [
        h.part.ref for h in rank([1.0, 0.0], parts)
    ]


@pytest.mark.parametrize(
    "stacks,stack,expected",
    [
        ((), "react", False),           # unclassified: does not masquerade as "any"
        ((), None, True),               # unclassified still shows up unfiltered
        (("any",), "react", True),      # explicitly not stack-specific
        (("react",), "react", True),
        (("react",), "React", True),    # case-insensitive
        (("python",), "react", False),
        (("python",), None, True),      # no filter asked for
    ],
)
def test_stack_filter_fails_open(stacks, stack, expected):
    assert matches_stack(part(stacks=stacks), stack) is expected


def test_zero_limit_is_refused():
    with pytest.raises(SearchError):
        rank([1.0, 0.0], [part()], limit=0)


def test_a_zero_query_vector_is_refused():
    with pytest.raises(SearchError):
        rank([0.0, 0.0], [part()])


def write_index(tmp_path, rows):
    target = tmp_path / "embeddings.jsonl"
    target.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return target


def test_index_loads_and_normalises(tmp_path):
    path = write_index(tmp_path, [{
        "skill_id": "a/b", "version": "abcdef123456", "part_id": "p",
        "title": "P", "kind": "lens", "sha256": "h",
        "applies_to": "Use when p.", "vector": [3.0, 4.0], "tags": ["x"],
        "document_kinds": ["milestone"],
    }])
    loaded = load_index(path)[0]
    assert loaded.vector == pytest.approx((0.6, 0.8))
    assert loaded.tags == ("x",)
    assert loaded.document_kinds == ("milestone",)


def test_an_index_written_before_document_kinds_still_loads(tmp_path):
    """The index is derived and rebuilt, but a half-rebuilt one must not crash."""
    path = write_index(tmp_path, [{
        "skill_id": "a/b", "version": "abcdef123456", "part_id": "p",
        "title": "P", "kind": "lens", "sha256": "h",
        "applies_to": "Use when p.", "vector": [1.0, 0.0],
    }])
    assert load_index(path)[0].document_kinds == ()


def test_document_kinds_do_not_narrow_a_search():
    """Reported, not filtered: the caller naming a stage before knowing the
    answer's stage would drop correct parts, and the measurement says a filter
    buys nothing here anyway."""
    parts = [
        part(pid="milestone-only", vector=(1.0, 0.0)),
        part(skill="a/b", pid="unclassified", vector=(0.9, 0.1)),
    ]
    assert len(rank([1.0, 0.0], parts, limit=6)) == 2


def row(pid="p", vector=(1.0, 0.0)):
    return {
        "skill_id": "a/b", "version": "abcdef123456", "part_id": pid,
        "title": pid, "kind": "lens", "sha256": "h",
        "applies_to": f"Use when {pid}.", "vector": list(vector),
    }


def test_an_index_of_the_wrong_width_is_refused(tmp_path):
    """`similarity` zips query against row and zip stops at the shorter one,
    so a mismatch scores the overlapping halves and answers with confident
    nonsense. Nothing downstream can notice; this is the only place that can."""
    path = write_index(tmp_path, [row(vector=(1.0, 0.0))])
    with pytest.raises(SearchError, match="embedder_dim is 768"):
        load_index(path, expected_dim=768)


def test_the_refusal_names_both_ways_out(tmp_path):
    path = write_index(tmp_path, [row(vector=(1.0, 0.0))])
    with pytest.raises(SearchError, match="re-run lenses.ingest"):
        load_index(path, expected_dim=384)


def test_a_matching_width_loads(tmp_path):
    path = write_index(tmp_path, [row(vector=(3.0, 4.0))])
    assert load_index(path, expected_dim=2)[0].vector == pytest.approx((0.6, 0.8))


def test_an_index_of_mixed_widths_is_refused(tmp_path):
    """What a run that died partway through embedding leaves behind."""
    path = write_index(tmp_path, [row("p", (1.0, 0.0)), row("q", (1.0, 0.0, 0.0))])
    with pytest.raises(SearchError, match="mixes 2- and 3-dimensional"):
        load_index(path)


def test_width_is_unchecked_when_nothing_is_expected(tmp_path):
    """Tools that only read the corpus need not know the embedder config."""
    path = write_index(tmp_path, [row(vector=(1.0, 0.0))])
    assert len(load_index(path)) == 1


def test_a_missing_index_says_what_to_run(tmp_path):
    with pytest.raises(SearchError, match="Run lenses.ingest"):
        load_index(tmp_path / "absent.jsonl")


def test_corpus_finds_a_pinned_part():
    corpus = Corpus([part()])
    assert corpus.find("wondelai/release-it#circuit-breaker@34ac73394a51").part_id == "circuit-breaker"


def test_a_stale_version_says_which_one_is_catalogued():
    corpus = Corpus([part()])
    with pytest.raises(SearchError, match="catalogued as 34ac73394a51"):
        corpus.find("wondelai/release-it#circuit-breaker@000000000000")


def test_an_unknown_part_is_reported():
    with pytest.raises(SearchError, match="no such part"):
        Corpus([part()]).find("a/b#nope@abcdef123456")
