"""Ranking over the index. No network, no model — a vector comes in.

Keeping the embedding call outside means the ranking is testable exhaustively
and deterministically, which is what lets the tuning arguments be settled with
numbers rather than opinions.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

#: `label/name#part@version` — a citation a spec can carry. The version is the
#: point: an unpinned reference silently starts naming different text the day
#: upstream is rewritten.
REF = re.compile(r"^(?P<skill_id>[^#@\s]+)#(?P<part_id>[^#@\s]+)@(?P<version>[0-9a-f]{6,64})$")


class SearchError(ValueError):
    """A query or reference cannot be understood."""


@dataclass(frozen=True)
class IndexedPart:
    skill_id: str
    version: str
    part_id: str
    title: str
    applies_to: str
    kind: str
    sha256: str
    vector: tuple[float, ...]
    stacks: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    #: Which documents this part's skill bears on: milestone, spec, plan.
    #: Reported, never filtered on — see `catalog_parts` for the measurement
    #: that decided it. Empty means the skill was never classified.
    document_kinds: tuple[str, ...] = ()
    #: Sibling part ids that must be read with this one. Reported by a search,
    #: expanded only by `get_lenses` — a candidate is something the caller is
    #: still deciding about, and pulling its dependencies in would spend their
    #: `limit` on parts they have not chosen.
    requires: tuple[str, ...] = ()

    @property
    def ref(self) -> str:
        return f"{self.skill_id}#{self.part_id}@{self.version}"


@dataclass
class Hit:
    score: float
    part: IndexedPart


def parse_ref(ref: str) -> tuple[str, str, str]:
    """`label/name#part@version` -> its three pieces."""
    match = REF.match(ref.strip())
    if not match:
        raise SearchError(
            f"{ref!r} is not a part reference. Expected label/name#part@version"
        )
    return match["skill_id"], match["part_id"], match["version"]


def _unit(vector: list[float]) -> tuple[float, ...]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        raise SearchError("a zero vector cannot be compared")
    return tuple(value / norm for value in vector)


def load_index(path: Path, expected_dim: int | None = None) -> list[IndexedPart]:
    """Read embeddings.jsonl, normalising every vector once at load.

    `expected_dim` is the width the configured embedder produces. Checking it
    here is the only place the mismatch can be caught: `similarity` zips the
    query against the row, and zip stops at the shorter one — so a 384-wide
    query against a 768-wide index scores the halves that happen to line up
    and returns confident nonsense with no exception at all (observed: a
    resilience query answering with legacy-code and ADR parts at 0.10). The
    index is derived, so this state is one forgotten reindex away after any
    change of embedder.
    """
    path = Path(path)
    if not path.is_file():
        raise SearchError(f"no index at {path}. Run lenses.ingest first")
    parts: list[IndexedPart] = []
    width: int | None = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        vector = row["vector"]
        if width is None:
            width = len(vector)
            if expected_dim is not None and width != expected_dim:
                raise SearchError(
                    f"{path} holds {width}-dimensional vectors but embedder_dim "
                    f"is {expected_dim}. The index was built with a different "
                    f"embedder — re-run lenses.ingest, or put the previous "
                    f"embedder_model back in .env."
                )
        elif len(vector) != width:
            # A run that died partway leaves exactly this.
            raise SearchError(
                f"{path} mixes {width}- and {len(vector)}-dimensional vectors "
                f"at {row.get('skill_id')}#{row.get('part_id')}. Re-run lenses.ingest"
            )
        parts.append(
            IndexedPart(
                skill_id=row["skill_id"],
                version=row["version"],
                part_id=row["part_id"],
                title=row.get("title", row["part_id"]),
                applies_to=row["applies_to"],
                kind=row.get("kind") or "reference",
                sha256=row["sha256"],
                vector=_unit(vector),
                stacks=tuple(row.get("stacks") or ()),
                tags=tuple(row.get("tags") or ()),
                document_kinds=tuple(row.get("document_kinds") or ()),
                requires=tuple(row.get("requires") or ()),
            )
        )
    return parts


def similarity(query: tuple[float, ...], part: IndexedPart) -> float:
    return sum(a * b for a, b in zip(query, part.vector))


def matches_stack(part: IndexedPart, stack: str | None) -> bool:
    """A stack filter that fails open only for a real claim of "any".

    `any` is an author's positive statement that a part is language-agnostic,
    and must match every query — a filter that hid it would remove exactly
    the lenses worth finding. An *empty* `stacks` is a different thing: it
    means nobody has classified this part yet, and letting that masquerade
    as "any" is how a part written for one stack quietly shows up under every
    other one. Unclassified content still matches when nothing was asked for
    (`stack=None`) — it only stops matching a specific, wrong guess.
    """
    if not stack:
        return True
    if "any" in part.stacks:
        return True
    wanted = stack.strip().lower()
    return any(wanted == item.strip().lower() for item in part.stacks)


def rank(
    query: list[float],
    parts: list[IndexedPart],
    limit: int = 6,
    per_skill: int = 2,
    kind: str | None = None,
    stack: str | None = None,
) -> list[Hit]:
    """Best parts for a query, with at most `per_skill` from any one skill.

    The cap is the whole reason this is not a plain sort. Sixty-one percent of
    this corpus is reference material and neighbouring sections of one skill
    score alike, so an uncapped top six is routinely six slices of the same
    document — which is exactly the choice the caller wanted made for them.
    """
    if limit < 1:
        raise SearchError("limit must be at least 1")
    unit = _unit(query)

    candidates = [
        Hit(similarity(unit, part), part)
        for part in parts
        if (kind is None or part.kind == kind) and matches_stack(part, stack)
    ]
    candidates.sort(key=lambda hit: (-hit.score, hit.part.ref))

    taken: dict[str, int] = {}
    chosen: list[Hit] = []
    for hit in candidates:
        if taken.get(hit.part.skill_id, 0) >= per_skill:
            continue
        taken[hit.part.skill_id] = taken.get(hit.part.skill_id, 0) + 1
        chosen.append(hit)
        if len(chosen) == limit:
            break
    return chosen


@dataclass
class Corpus:
    """Everything the server answers from."""

    parts: list[IndexedPart] = field(default_factory=list)

    @property
    def skills(self) -> dict[str, list[IndexedPart]]:
        grouped: dict[str, list[IndexedPart]] = {}
        for part in self.parts:
            grouped.setdefault(part.skill_id, []).append(part)
        return grouped

    def find(self, ref: str) -> IndexedPart:
        skill_id, part_id, version = parse_ref(ref)
        for part in self.parts:
            if (part.skill_id, part.part_id, part.version) == (skill_id, part_id, version):
                return part
        known = [p.version for p in self.parts if p.skill_id == skill_id and p.part_id == part_id]
        if known:
            raise SearchError(
                f"{ref}: version {version} is not in the index; catalogued as {known[0]}"
            )
        raise SearchError(f"{ref}: no such part in the index")
