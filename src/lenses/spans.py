"""Line-span arithmetic, and the gates a decomposition must pass.

Spans are 1-indexed and inclusive at both ends: that is how a reviewer reads a
diff, and how the decomposition model is asked to count. Byte offsets would be
smaller but neither a human nor a model can check them by eye.

Nothing here calls a model or the network. This module is the part of the
pipeline that can be reasoned about and tested exhaustively, so the gates live
here rather than inside the ingest orchestration.
"""

from __future__ import annotations

import hashlib

Span = tuple[int, int]


class SpanError(ValueError):
    """A span cannot be interpreted against the document it claims to cut."""


def normalise_text(text: str) -> str:
    """Canonical form for hashing and comparison.

    Line endings collapse to ``\\n`` and trailing whitespace goes, so the same
    part hashes identically whether it was read on Windows or Linux. Without
    this a pinned reference would break the first time the catalogue was
    rebuilt on another machine — which is the whole thing the pin exists to
    prevent.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def split_lines(text: str) -> list[str]:
    """Document lines, normalised, without terminators."""
    return normalise_text(text).split("\n")


def validate_span(span: Span, line_count: int) -> None:
    """Raise unless the span names real lines, in order."""
    if len(span) != 2:
        raise SpanError(f"span must be a [start, end] pair, got {span!r}")
    start, end = span
    if not isinstance(start, int) or not isinstance(end, int):
        raise SpanError(f"span bounds must be integers, got {span!r}")
    if start < 1:
        raise SpanError(f"span starts at line {start}; lines are 1-indexed")
    if end < start:
        raise SpanError(f"span {span!r} ends before it starts")
    if end > line_count:
        raise SpanError(f"span {span!r} runs past the last line ({line_count})")


def overlaps(first: Span, second: Span) -> bool:
    """Whether two inclusive spans share at least one line."""
    return first[0] <= second[1] and second[0] <= first[1]


def find_overlaps(spans: list[Span]) -> list[tuple[Span, Span]]:
    """Every pair of spans that shares a line, in the order given."""
    clashes: list[tuple[Span, Span]] = []
    for index, first in enumerate(spans):
        for second in spans[index + 1 :]:
            if overlaps(first, second):
                clashes.append((first, second))
    return clashes


def covered_lines(spans: list[Span]) -> set[int]:
    """The set of line numbers any span touches."""
    covered: set[int] = set()
    for start, end in spans:
        covered.update(range(start, end + 1))
    return covered


def coverage(spans: list[Span], line_count: int) -> float:
    """Fraction of the document that ended up inside some span."""
    if line_count <= 0:
        return 0.0
    return len(covered_lines(spans)) / line_count


def uncovered_ranges(spans: list[Span], line_count: int) -> list[Span]:
    """Contiguous stretches no span claims — what a curator should look at."""
    covered = covered_lines(spans)
    gaps: list[Span] = []
    start: int | None = None
    for line in range(1, line_count + 1):
        if line in covered:
            if start is not None:
                gaps.append((start, line - 1))
                start = None
        elif start is None:
            start = line
    if start is not None:
        gaps.append((start, line_count))
    return gaps


def extract(lines: list[str], spans: list[Span]) -> str:
    """The document's own text at those spans, in the order given.

    The decomposition model returns line numbers and never text, so what a
    downstream agent reads is always verbatim source. That property is
    structural here, not a rule someone has to remember to check.
    """
    pieces: list[str] = []
    for span in spans:
        validate_span(span, len(lines))
        start, end = span
        pieces.append("\n".join(lines[start - 1 : end]))
    return normalise_text("\n\n".join(pieces))


def content_hash(text: str) -> str:
    """Stable identity for a part's text — the pin a spec will carry."""
    return hashlib.sha256(normalise_text(text).encode("utf-8")).hexdigest()
