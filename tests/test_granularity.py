"""A part must not be the whole document.

`clean-code` was decomposed into one 166-line span covering six disciplines
and passed every gate there was: coverage, bounds and overlap say nothing
about granularity. A slice needing the section on naming would have received
error handling and unit testing along with it.
"""

import pytest

from pathlib import Path

from lenses.decompose import MAX_PART_LINES, MAX_PART_SHARE, check
from lenses.ingest import build_plan
from lenses.model import Part
from lenses.vendored import VendoredSkill


def part(part_id, spans):
    return Part(id=part_id, title=part_id, applies_to=f"Use when {part_id}.", spans=list(spans))


def test_one_part_swallowing_the_document_is_reported():
    problems = check([part("everything", [(14, 179)])], line_count=222, min_coverage=0.5)
    assert any("not a part of it" in problem for problem in problems)


def test_the_message_gives_both_numbers():
    problems = check([part("everything", [(14, 179)])], line_count=222, min_coverage=0.5)
    message = next(p for p in problems if "not a part of it" in p)
    assert "166 lines" in message and "75%" in message


def test_sections_of_a_long_document_are_fine():
    """clean-architecture's real shape: ten parts, none dominant."""
    parts = [part(f"s{index}", [(index * 20 + 1, index * 20 + 20)]) for index in range(10)]
    assert check(parts, line_count=210, min_coverage=0.5) == []


def test_a_short_document_is_not_forced_to_split():
    """Half of a 60-line skill is a legitimate part; the absolute floor guards it."""
    problems = check([part("half", [(1, 30)])], line_count=60, min_coverage=0.4)
    assert problems == []


def test_a_long_part_of_a_much_longer_document_is_allowed():
    """Above the line floor but well under the share: api-design's biggest part."""
    problems = check([part("big", [(1, 110)])], line_count=520, min_coverage=0.1)
    assert problems == []


def test_both_thresholds_must_be_exceeded():
    just_over_lines = MAX_PART_LINES + 1
    line_count = int(just_over_lines / MAX_PART_SHARE) + 50  # share stays under
    assert check([part("x", [(1, just_over_lines)])], line_count, min_coverage=0.0) == []


def test_disjoint_spans_are_summed_not_taken_separately():
    """Two 90-line halves of a 220-line document are still the document."""
    problems = check([part("split", [(1, 90), (100, 189)])], line_count=220, min_coverage=0.0)
    assert any("not a part of it" in problem for problem in problems)


def vendored(label, name):
    return VendoredSkill(label=label, name=name, path=Path(name) / "SKILL.md", version="v")


@pytest.fixture
def corpus():
    return [
        vendored("wondelai", "clean-code"),
        vendored("wondelai", "clean-architecture"),
        vendored("wondelai", "release-it"),
        vendored("ecc", "postgres-patterns"),
    ]


def test_skill_filter_narrows_the_plan(corpus):
    plan = build_plan(corpus, names=("clean-code", "clean-architecture"))
    assert sorted(skill.name for skill in plan) == ["clean-architecture", "clean-code"]


def test_skill_filter_accepts_globs(corpus):
    assert len(build_plan(corpus, names=("clean-*",))) == 2


def test_label_filter_narrows_to_one_upstream(corpus):
    plan = build_plan(corpus, labels=("ecc",))
    assert [skill.id for skill in plan] == ["ecc/postgres-patterns"]


def test_label_and_skill_filters_intersect(corpus):
    assert build_plan(corpus, labels=("ecc",), names=("clean-*",)) == []


def test_limit_caps_the_run(corpus):
    assert len(build_plan(corpus, limit=2)) == 2


def test_no_filter_keeps_everything(corpus):
    assert len(build_plan(corpus)) == 4
