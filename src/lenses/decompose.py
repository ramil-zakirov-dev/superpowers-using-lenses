"""Ask a model where a skill's parts begin and end.

The model returns line numbers and metadata. It never returns instruction
text, so no downstream agent can be handed a sentence the upstream author did
not write. That is why a cheap model is a deliberate choice here rather than a
compromise: the expensive judgement — what the instruction should say — was
already made upstream, and we are only marking it up.
"""

from __future__ import annotations

import json
import re

import httpx

from .config import Endpoint
from .model import SKILL_KINDS, Part
from .spans import (
    Span,
    covered_lines,
    coverage,
    find_overlaps,
    uncovered_ranges,
    validate_span,
)

#: A part this long *and* this large a share of its document is not a part —
#: it is the document with the edges trimmed, and it defeats the point of
#: cutting skills up at all. Both thresholds must be exceeded, so a genuinely
#: short skill is never forced to split.
#:
#: Found by a real decomposition that put six disciplines of `clean-code` into
#: one 166-line span and passed every other gate: coverage, bounds and overlap
#: all say nothing about granularity.
MAX_PART_LINES = 100
MAX_PART_SHARE = 0.35

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

SYSTEM_PROMPT = """\
You mark up agent skill documents. You do not rewrite them.

You are given a skill document with every line numbered. You return JSON that
says which line ranges form parts that can be used on their own, and metadata
about each. You never return the document's text: only line numbers, titles,
and applicability statements you write yourself.

A PART is a stretch of the document that a different agent could follow
correctly having read only that stretch plus its preamble. If following it
would require reading something else in the document, either widen the
preamble or do not make it a part.

A PREAMBLE is the minimal parent context — definitions, conventions, the
vocabulary the part assumes — quoted from elsewhere in the same document by
line range. It is not a summary you write.

Rules:
- Line numbers are 1-indexed and inclusive at both ends.
- Part ranges must not overlap each other.
- Do not make parts out of YAML frontmatter, the document title, or a table of
  contents.
- Prefer few self-sufficient parts over many fragments. A part that cannot be
  acted on alone is worse than no part.
- One part per topic the document itself separates. If the document has
  sections, cut along them. A part covering most of the document is not a
  part: someone who needs the section on naming must not also receive the
  sections on error handling and testing.
- Each part carries its OWN `kind`, judged on that part alone and not
  inherited from the document. A section stating principles and criteria you
  reason with is `lens`; a section listing APIs, syntax, checklists or scoring
  rubrics is `reference`; a section prescribing a sequence of steps to carry
  out is `pipeline`. A document is routinely a mix, and labelling every part
  the same as the whole loses exactly the distinction being asked for.
- `applies_to` states WHEN the part is relevant and nothing else. Begin it with
  "Use when". Never summarise what the part says — a reader matches their
  situation against this field, and a summary invites them to act on it
  instead of reading the part.
- `requires` names sibling part ids that must travel with this one when a
  preamble is not enough.

Return ONLY a JSON object of this shape:

{
  "kind": "lens" | "pipeline" | "reference",
  "summary": "one sentence on what the whole skill is for",
  "stacks": ["any"] or e.g. ["react", "typescript"],
  "document_kinds": subset of ["milestone", "spec", "plan"],
  "parts": [
    {
      "id": "kebab-case-slug",
      "title": "Short human title",
      "kind": "lens" | "pipeline" | "reference",
      "applies_to": "Use when ...",
      "preamble_spans": [[3, 14]],
      "spans": [[128, 171]],
      "requires": ["other-part-id"]
    }
  ]
}

"kind" of the whole skill: `lens` if it supplies vocabulary and criteria for
judgement; `pipeline` if it supplies its own route from work to release;
`reference` if it is domain or API documentation. A pipeline is still worth
marking up — its individual parts are often lenses.
"""


class DecompositionError(RuntimeError):
    """The model's answer cannot be used as a decomposition."""


def number_lines(lines: list[str]) -> str:
    """The document as the model sees it: every line prefixed with its number."""
    width = len(str(len(lines)))
    return "\n".join(f"{index:>{width}} | {line}" for index, line in enumerate(lines, 1))


def build_user_prompt(skill_id: str, lines: list[str]) -> str:
    return (
        f"Skill id: {skill_id}\n"
        f"Total lines: {len(lines)}\n\n"
        f"{number_lines(lines)}"
    )


def _strip_fence(raw: str) -> str:
    return _FENCE.sub("", raw).strip()


def call_model(endpoint: Endpoint, skill_id: str, lines: list[str], timeout: float = 300.0) -> dict:
    """One chat completion, parsed as JSON."""
    response = httpx.post(
        f"{endpoint.base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {endpoint.api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": endpoint.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": build_user_prompt(skill_id, lines)},
            ],
        },
        timeout=timeout,
    )
    if response.status_code >= 400:
        # The server's body is the only place that says *why*. raise_for_status
        # throws it away and leaves a status code, which sends you reading your
        # own code for a fault that is on the other end of the socket.
        raise DecompositionError(
            f"{endpoint.base_url} returned {response.status_code} for model "
            f"{endpoint.model!r}: {response.text[:500]}"
        )
    payload = response.json()
    try:
        content = payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError) as exc:
        raise DecompositionError(f"unexpected response shape: {payload!r}") from exc

    try:
        parsed = json.loads(_strip_fence(content))
    except json.JSONDecodeError as exc:
        raise DecompositionError(
            f"model did not return JSON for {skill_id}: {content[:400]!r}"
        ) from exc
    if not isinstance(parsed, dict):
        raise DecompositionError(f"model returned {type(parsed).__name__}, expected object")
    return parsed


def _attempt(endpoint: Endpoint, skill_id: str, lines: list[str]) -> tuple[dict, list[Part]]:
    """One model's answer, only if it satisfies the schema."""
    payload = call_model(endpoint, skill_id, lines)
    return payload, parse_parts(payload)


def decompose_with_fallback(
    primary: Endpoint,
    fallback: Endpoint | None,
    skill_id: str,
    lines: list[str],
) -> tuple[dict, list[Part], str]:
    """Ask the primary model, then the fallback once.

    The retried unit is *call and validate*, not just call. A model that
    returns well-formed JSON with a part missing `applies_to` has failed as
    completely as one that timed out — the answer is unusable either way — and
    the second model may well not repeat the mistake. Retrying only transport
    failures leaves the commonest failure of a cheap model uncovered.

    The model that answered is returned rather than assumed: it goes into the
    catalogue's provenance, and a curator reviewing a suspect decomposition
    should not have to guess which one produced it.
    """
    try:
        payload, parts = _attempt(primary, skill_id, lines)
        return payload, parts, primary.model
    except (DecompositionError, httpx.HTTPError) as first_failure:
        if fallback is None:
            raise
        try:
            payload, parts = _attempt(fallback, skill_id, lines)
            return payload, parts, fallback.model
        except (DecompositionError, httpx.HTTPError) as second_failure:
            raise DecompositionError(
                f"both models failed for {skill_id}. "
                f"{primary.model}: {first_failure} || "
                f"{fallback.model}: {second_failure}"
            ) from second_failure


def _as_spans(raw, field: str, part_id: str) -> list[Span]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise DecompositionError(f"{part_id}.{field} must be a list of pairs, got {raw!r}")
    spans: list[Span] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise DecompositionError(f"{part_id}.{field} contains {item!r}, expected [start, end]")
        spans.append((int(item[0]), int(item[1])))
    return spans


def parse_parts(payload: dict) -> list[Part]:
    """Turn the model's JSON into Part objects, without touching the document."""
    raw_parts = payload.get("parts")
    if not isinstance(raw_parts, list) or not raw_parts:
        raise DecompositionError("model returned no parts")

    parts: list[Part] = []
    for raw in raw_parts:
        if not isinstance(raw, dict):
            raise DecompositionError(f"part must be an object, got {raw!r}")
        part_id = str(raw.get("id", "")).strip()
        if not _SLUG.match(part_id):
            raise DecompositionError(f"part id {part_id!r} is not a kebab-case slug")
        applies_to = str(raw.get("applies_to", "")).strip()
        if not applies_to:
            raise DecompositionError(f"{part_id} has no applies_to")
        kind = raw.get("kind")
        if kind is not None and kind not in SKILL_KINDS:
            raise DecompositionError(f"{part_id} has unknown kind {kind!r}")
        parts.append(
            Part(
                id=part_id,
                title=str(raw.get("title", part_id)).strip(),
                applies_to=applies_to,
                spans=_as_spans(raw.get("spans"), "spans", part_id),
                preamble_spans=_as_spans(raw.get("preamble_spans"), "preamble_spans", part_id),
                requires=[str(name) for name in raw.get("requires", []) or []],
                kind=kind,
            )
        )
    return parts


def check(parts: list[Part], line_count: int, min_coverage: float) -> list[str]:
    """Every mechanical gate. Returns the problems found, empty when clean.

    These are the checks that need no model: bounds, overlap, coverage,
    dangling references, duplicate ids. The one gate that does need a model —
    is this part really usable alone — is deliberately not here.
    """
    problems: list[str] = []

    ids = [part.id for part in parts]
    duplicates = {name for name in ids if ids.count(name) > 1}
    for name in sorted(duplicates):
        problems.append(f"duplicate part id: {name}")

    for part in parts:
        if not part.spans:
            problems.append(f"{part.id}: no spans")
        for span in list(part.spans) + list(part.preamble_spans):
            try:
                validate_span(span, line_count)
            except ValueError as exc:
                problems.append(f"{part.id}: {exc}")
        for name in part.requires:
            if name not in ids:
                problems.append(f"{part.id}: requires unknown part {name!r}")
            elif name == part.id:
                problems.append(f"{part.id}: requires itself")

    for part in parts:
        span_lines = len(covered_lines(part.spans))
        share = span_lines / line_count if line_count else 0.0
        if span_lines > MAX_PART_LINES and share > MAX_PART_SHARE:
            problems.append(
                f"{part.id}: covers {span_lines} lines, {share:.0%} of the document — "
                f"that is the document, not a part of it. Expect the section "
                f"headings to be cut apart"
            )

    body_spans = [span for part in parts for span in part.spans]
    for first, second in find_overlaps(body_spans):
        problems.append(f"overlapping part spans: {list(first)} and {list(second)}")

    got = coverage(body_spans, line_count)
    if got < min_coverage:
        gaps = ", ".join(f"{start}-{end}" for start, end in uncovered_ranges(body_spans, line_count))
        problems.append(
            f"coverage {got:.0%} is below the {min_coverage:.0%} floor; "
            f"unclaimed lines: {gaps or 'none'}"
        )

    return problems
