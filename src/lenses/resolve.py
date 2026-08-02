"""Turn a part reference into the text it names, or refuse.

The reference carries a version, the catalogue carries a hash, and the
vendored file carries the bytes. All three must agree before a single line is
handed to an agent: a citation that resolves to changed text is worse than one
that fails, because nobody notices it.

`resolve_all` adds the second half of that honesty. Decomposition records, per
part, the siblings that must travel with it when a preamble cannot carry the
context — a whole section rather than a heading. Returning the fragment alone
is worse than returning nothing: the catalogue knew it was incomplete and said
so, and an agent that cites it has no way to tell.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .model import load_skill_doc
from .search import SearchError, parse_ref
from .spans import content_hash, extract, split_lines
from .vendored import MAIN_FILE

#: Ceiling on what one requested reference can drag in with it. The measured
#: worst closure in this corpus is 7, so this does not bind today — the point
#: is that the size of an answer stays a property of this code rather than of
#: whatever a model wrote into a catalogue file.
MAX_PARTS_PER_REF = 12


@dataclass(frozen=True)
class ResolvedPart:
    ref: str
    title: str
    applies_to: str
    kind: str
    text: str
    file: str
    license: str
    url: str
    tags: tuple[str, ...] = ()
    #: Sibling part ids the catalogue says must travel with this one, for the
    #: case a preamble cannot cover — a whole section, not a header.
    requires: tuple[str, ...] = ()
    #: The refs that pulled this part in. Empty for a part the caller named:
    #: `resolve` cannot know, so only `resolve_all` ever sets it.
    required_by: tuple[str, ...] = ()


def catalogue_path(catalog_dir: Path, skill_id: str, version: str) -> Path:
    label, _, name = skill_id.partition("/")
    if not name:
        raise SearchError(f"{skill_id!r} must look like label/name")
    return Path(catalog_dir) / label / name / f"{version}.yaml"


def resolve(ref: str, catalog_dir: Path, skills_dir: Path) -> ResolvedPart:
    """The text a reference names, verified against its pin."""
    skill_id, part_id, version = parse_ref(ref)

    catalogue = catalogue_path(catalog_dir, skill_id, version)
    if not catalogue.is_file():
        raise SearchError(f"{ref}: no catalogue entry at {catalogue}")
    document = load_skill_doc(catalogue.read_text(encoding="utf-8"))

    part = next((item for item in document.get("parts") or [] if item["id"] == part_id), None)
    if part is None:
        available = sorted(item["id"] for item in document.get("parts") or [])
        raise SearchError(f"{ref}: no part {part_id!r}. Available: {available}")

    skill_dir = Path(skills_dir) / skill_id
    relative = part.get("file") or MAIN_FILE
    source = skill_dir / relative
    if not source.is_file():
        raise SearchError(f"{ref}: vendored file missing at {source}")

    lines = split_lines(source.read_text(encoding="utf-8"))
    spans = [tuple(span) for span in part.get("preamble_spans") or []]
    spans += [tuple(span) for span in part["spans"]]
    text = extract(lines, spans)

    if content_hash(text) != part["sha256"]:
        # Either the vendored file was edited or the catalogue is stale. Both
        # mean this reference no longer names what it claims to name.
        raise SearchError(
            f"{ref}: text does not match its pin — {source} was edited, or the "
            f"catalogue is stale. Re-vendor and re-ingest rather than trusting this"
        )

    return ResolvedPart(
        ref=ref,
        title=part.get("title", part_id),
        applies_to=part["applies_to"],
        kind=part.get("kind") or document.get("kind") or "reference",
        text=text,
        file=f"{skill_id}/{relative}",
        license=document.get("license", "unknown"),
        url=(document.get("source") or {}).get("url", ""),
        tags=tuple(part.get("tags") or ()),
        requires=tuple(part.get("requires") or ()),
    )


def resolve_all(
    refs: list[str], catalog_dir: Path, skills_dir: Path
) -> tuple[list[ResolvedPart], list[str]]:
    """The requested parts, plus everything their `requires` closure names.

    Requested parts come first in the order asked for, then required ones in
    the order first reached. Grouping each requirement under its requirer would
    be ambiguous once two parts need the same sibling; `required_by` carries
    that provenance instead, and carries it for every requirer.

    Nothing is dropped silently. A requirement that will not resolve, and a
    closure that outgrows `MAX_PARTS_PER_REF`, both surface in the returned
    errors while the parts that did resolve are still returned — an incomplete
    answer that announces itself is the whole point of following the field.
    """
    parts: dict[str, ResolvedPart] = {}
    requested: list[str] = []
    errors: list[str] = []

    for ref in refs:
        try:
            part = resolve(ref, catalog_dir, skills_dir)
        except SearchError as exc:
            errors.append(str(exc))
            continue
        if part.ref not in parts:
            requested.append(part.ref)
        parts[part.ref] = part
    asked_for = set(requested)

    for root in requested:
        # Per root: one budget, one visited set. The visited set is what makes
        # a cycle terminate — `decompose` rejects unknown ids and self-reference
        # but not a → b → a, so the corpus having none today is an observation
        # about one model's output, not an invariant to lean on.
        seen = {root}
        queue = [root]
        budget = MAX_PARTS_PER_REF - 1
        dropped: list[str] = []

        while queue:
            current = queue.pop(0)
            skill_id, _, version = parse_ref(current)
            for needed_id in parts[current].requires:
                # `requires` names siblings in the same document — decompose
                # validates it against that document's own ids — so the ref is
                # the requirer's, with the part swapped.
                needed = f"{skill_id}#{needed_id}@{version}"
                if needed in seen:
                    continue
                seen.add(needed)

                fresh = needed not in parts
                if fresh and budget <= 0:
                    dropped.append(needed)
                    continue
                if fresh:
                    try:
                        parts[needed] = resolve(needed, catalog_dir, skills_dir)
                    except SearchError as exc:
                        errors.append(
                            f"{current}: requires {needed_id!r}, which does not "
                            f"resolve: {exc}"
                        )
                        continue
                    budget -= 1
                if needed not in asked_for:
                    parts[needed] = replace(
                        parts[needed],
                        required_by=parts[needed].required_by + (current,),
                    )
                queue.append(needed)

        if dropped:
            errors.append(
                f"{root}: needs more than {MAX_PARTS_PER_REF} parts; "
                f"dropped {sorted(dropped)}"
            )

    return list(parts.values()), errors
