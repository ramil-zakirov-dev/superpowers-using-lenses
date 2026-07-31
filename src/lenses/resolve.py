"""Turn a part reference into the text it names, or refuse.

The reference carries a version, the catalogue carries a hash, and the
vendored file carries the bytes. All three must agree before a single line is
handed to an agent: a citation that resolves to changed text is worse than one
that fails, because nobody notices it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .model import load_skill_doc
from .search import SearchError, parse_ref
from .spans import content_hash, extract, split_lines
from .vendored import MAIN_FILE


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
    )
