"""Which upstream catalogues to ingest, and which of their skills to take.

The manifest is committed. Provenance — where a skill came from and under what
licence — is a property of the catalogue, not of the command someone happened
to type, and a curated catalogue that cannot say where its contents came from
is not curated.

Machine-specific paths stay out of it: an entry's `path` resolves under
`sources_root` from .env unless it is absolute, so the manifest is the same
file on every machine.
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

KNOWN_KEYS = frozenset(
    {"label", "path", "commit", "url", "license", "include", "exclude", "enabled"}
)

#: A full git object name. Abbreviations are refused: seven characters are
#: unambiguous in a repository until the day they are not, and a provenance
#: record that needs the upstream present to be resolved is not one.
COMMIT = re.compile(r"^[0-9a-f]{40}$")


class SourceError(ValueError):
    """The manifest cannot be read as written."""


@dataclass(frozen=True)
class Source:
    label: str
    path: Path
    #: The upstream commit this catalogue was built against. Declared here and
    #: verified against the checkout at vendor time — the manifest states the
    #: intent, the checkout is the fact, and `vendor.py` says when they differ.
    #: Empty means unpinned: a source that is not a git checkout at all.
    commit: str = ""
    url: str = ""
    license: str = "unknown"
    #: Skill directory names to take. Empty means all of them.
    include: tuple[str, ...] = ()
    #: Skill directory names to drop, applied after `include`.
    exclude: tuple[str, ...] = ()
    enabled: bool = True


def resolve_path(raw: str, sources_root: Path) -> Path:
    """An entry's path: absolute and `~` as given, otherwise under the root."""
    expanded = Path(raw).expanduser()
    if expanded.is_absolute():
        return expanded
    return (Path(sources_root).expanduser() / expanded).resolve()


def selects(source: Source, skill_name: str) -> bool:
    """Whether this source wants that skill.

    `include` is a whitelist when present — the sane default for a repository
    of 281 skills where a handful are wanted. `exclude` is applied afterwards,
    so a broad include can be trimmed without listing its complement.
    """
    if source.include and not any(
        fnmatch.fnmatch(skill_name, pattern) for pattern in source.include
    ):
        return False
    return not any(fnmatch.fnmatch(skill_name, pattern) for pattern in source.exclude)


def _strings(raw, field: str, label: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
        raise SourceError(f"{label}.{field} must be a list of strings, got {raw!r}")
    return tuple(raw)


def parse_sources(data: dict, sources_root: Path) -> list[Source]:
    """Validate the manifest and resolve every entry. Fails closed."""
    entries = data.get("sources")
    if not isinstance(entries, list) or not entries:
        raise SourceError("manifest must contain a non-empty 'sources' list")

    sources: list[Source] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise SourceError(f"each source must be a mapping, got {entry!r}")

        label = str(entry.get("label", "")).strip()
        if not label:
            raise SourceError(f"source without a label: {entry!r}")
        if label in seen:
            raise SourceError(f"duplicate source label: {label}")
        seen.add(label)

        unknown = set(entry) - KNOWN_KEYS
        if unknown:
            # The same guard the orchestrator applies to agent keys: a typo
            # that silently does nothing is worse than a refused run.
            raise SourceError(
                f"{label}: unknown key(s) {sorted(unknown)}. Known: {sorted(KNOWN_KEYS)}"
            )

        raw_path = str(entry.get("path", "")).strip()
        if not raw_path:
            raise SourceError(f"{label}: path is required")

        commit = str(entry.get("commit", "")).strip().lower()
        if commit and not COMMIT.match(commit):
            raise SourceError(
                f"{label}: commit must be a full 40-character git object name, got {commit!r}"
            )

        sources.append(
            Source(
                label=label,
                path=resolve_path(raw_path, sources_root),
                commit=commit,
                url=str(entry.get("url", "")),
                license=str(entry.get("license", "unknown")),
                include=_strings(entry.get("include"), "include", label),
                exclude=_strings(entry.get("exclude"), "exclude", label),
                enabled=bool(entry.get("enabled", True)),
            )
        )
    return sources


def load_sources(manifest: Path, sources_root: Path) -> list[Source]:
    """Read and validate a manifest file."""
    manifest = Path(manifest)
    if not manifest.is_file():
        raise SourceError(f"no manifest at {manifest}")
    parsed = yaml.safe_load(manifest.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise SourceError(f"{manifest} must be a YAML mapping")
    return parse_sources(parsed, sources_root)
