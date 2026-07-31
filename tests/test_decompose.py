"""Parsing the model's answer, and the gates that answer must pass.

No test here reaches the network. Everything below is the part of the
pipeline that stays deterministic once the model has spoken.
"""

import pytest

from lenses.decompose import (
    DecompositionError,
    build_user_prompt,
    check,
    number_lines,
    parse_parts,
)
from lenses.model import Part


def payload(**overrides):
    base = {
        "kind": "lens",
        "summary": "Stability patterns.",
        "parts": [
            {
                "id": "circuit-breaker",
                "title": "Circuit breaker",
                "applies_to": "Use when a dependency can be slow or down.",
                "spans": [[10, 20]],
                "preamble_spans": [[1, 4]],
            }
        ],
    }
    base.update(overrides)
    return base


def part(part_id="alpha", spans=((10, 20),), requires=(), preamble=()):
    return Part(
        id=part_id,
        title=part_id,
        applies_to=f"Use when {part_id}.",
        spans=list(spans),
        preamble_spans=list(preamble),
        requires=list(requires),
    )


def test_line_numbering_is_one_indexed():
    assert number_lines(["first", "second"]).splitlines()[0].startswith("1 |")


def test_prompt_states_the_line_count_the_model_must_respect():
    assert "Total lines: 2" in build_user_prompt("x/y", ["a", "b"])


def test_parses_a_well_formed_answer():
    parts = parse_parts(payload())
    assert [p.id for p in parts] == ["circuit-breaker"]
    assert parts[0].spans == [(10, 20)]
    assert parts[0].preamble_spans == [(1, 4)]


def test_missing_parts_is_an_error():
    with pytest.raises(DecompositionError):
        parse_parts({"kind": "lens", "parts": []})


def test_non_slug_id_is_rejected():
    with pytest.raises(DecompositionError, match="kebab-case"):
        parse_parts(payload(parts=[{"id": "Circuit Breaker", "applies_to": "Use when.", "spans": [[1, 2]]}]))


def test_missing_applies_to_is_rejected():
    with pytest.raises(DecompositionError, match="applies_to"):
        parse_parts(payload(parts=[{"id": "ok", "applies_to": "  ", "spans": [[1, 2]]}]))


def test_unknown_part_kind_is_rejected():
    with pytest.raises(DecompositionError, match="unknown kind"):
        parse_parts(
            payload(parts=[{"id": "ok", "applies_to": "Use when.", "spans": [[1, 2]], "kind": "vibes"}])
        )


def test_malformed_span_pair_is_rejected():
    with pytest.raises(DecompositionError, match="expected"):
        parse_parts(payload(parts=[{"id": "ok", "applies_to": "Use when.", "spans": [[1, 2, 3]]}]))


def test_clean_decomposition_has_no_problems():
    assert check([part(spans=((1, 60),))], line_count=100, min_coverage=0.5) == []


def test_overlapping_parts_are_reported():
    problems = check(
        [part("alpha", ((1, 50),)), part("bravo", ((40, 90),))],
        line_count=100,
        min_coverage=0.1,
    )
    assert any("overlapping" in problem for problem in problems)


def test_span_past_the_end_is_reported():
    problems = check([part(spans=((1, 500),))], line_count=100, min_coverage=0.0)
    assert any("runs past the last line" in problem for problem in problems)


def test_coverage_below_the_floor_is_reported_with_the_gaps():
    problems = check([part(spans=((1, 10),))], line_count=100, min_coverage=0.5)
    assert any("below the 50% floor" in problem for problem in problems)
    assert any("11-100" in problem for problem in problems)


def test_dangling_requires_is_reported():
    problems = check([part("alpha", requires=("ghost",))], line_count=100, min_coverage=0.0)
    assert any("requires unknown part" in problem for problem in problems)


def test_self_reference_is_reported():
    problems = check([part("alpha", requires=("alpha",))], line_count=100, min_coverage=0.0)
    assert any("requires itself" in problem for problem in problems)


def test_duplicate_ids_are_reported():
    problems = check(
        [part("alpha", ((1, 10),)), part("alpha", ((11, 20),))],
        line_count=100,
        min_coverage=0.0,
    )
    assert any("duplicate part id" in problem for problem in problems)


def test_a_part_with_no_spans_is_reported():
    problems = check([part(spans=())], line_count=100, min_coverage=0.0)
    assert any("no spans" in problem for problem in problems)
