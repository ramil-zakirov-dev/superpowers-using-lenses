"""The pure core: span arithmetic, normalisation, hashing."""

import pytest

from lenses.spans import (
    SpanError,
    content_hash,
    coverage,
    extract,
    find_overlaps,
    normalise_text,
    split_lines,
    uncovered_ranges,
    validate_span,
)

DOC = "alpha\nbravo\ncharlie\ndelta\necho"


def test_crlf_and_lf_hash_identically():
    """A pin must survive being rebuilt on another operating system."""
    assert content_hash("one\r\ntwo\r\n") == content_hash("one\ntwo\n")


def test_trailing_whitespace_does_not_change_identity():
    assert content_hash("one   \ntwo\t\n") == content_hash("one\ntwo")


def test_normalise_strips_surrounding_blank_lines():
    assert normalise_text("\n\nbody\n\n") == "body"


def test_split_lines_counts_what_the_model_will_see():
    assert split_lines(DOC) == ["alpha", "bravo", "charlie", "delta", "echo"]


@pytest.mark.parametrize(
    "span",
    [(0, 2), (3, 2), (1, 99), (2,)],
    ids=["zero-index", "reversed", "past-end", "not-a-pair"],
)
def test_invalid_spans_are_rejected(span):
    with pytest.raises(SpanError):
        validate_span(span, 5)


def test_valid_span_is_accepted():
    validate_span((1, 5), 5)


def test_extract_returns_source_text_verbatim():
    assert extract(split_lines(DOC), [(2, 3)]) == "bravo\ncharlie"


def test_extract_joins_disjoint_spans_in_the_order_given():
    assert extract(split_lines(DOC), [(4, 4), (1, 1)]) == "delta\n\nalpha"


def test_extract_rejects_a_span_past_the_end():
    with pytest.raises(SpanError):
        extract(split_lines(DOC), [(4, 9)])


def test_overlap_is_inclusive_at_the_boundary():
    assert find_overlaps([(1, 3), (3, 5)]) == [((1, 3), (3, 5))]


def test_touching_spans_do_not_overlap():
    assert find_overlaps([(1, 3), (4, 5)]) == []


def test_coverage_counts_distinct_lines():
    assert coverage([(1, 2), (2, 3)], 5) == pytest.approx(0.6)


def test_coverage_of_nothing_is_zero():
    assert coverage([], 5) == 0.0


def test_uncovered_ranges_reports_gaps_at_both_ends():
    assert uncovered_ranges([(2, 3)], 5) == [(1, 1), (4, 5)]


def test_uncovered_ranges_empty_when_fully_covered():
    assert uncovered_ranges([(1, 5)], 5) == []
