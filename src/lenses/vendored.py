"""The vendored corpus: what `skills/` holds, and whether it is intact.

Ingest reads from here, not from an upstream checkout. Two things follow.
Provenance travels with the file rather than being retyped on a command line,
and what gets decomposed is exactly what is committed — so a catalogue entry
can be reproduced from a clone, on a machine that never had the upstream.

A vendored file whose bytes no longer match its sidecar is refused rather than
decomposed. Editing one is how a pin quietly starts naming text that does not
exist, and there is no reading of an edited quotation that is worth having.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .spans import content_hash

SIDECAR = "skill.yaml"
MAIN_FILE = "SKILL.md"


class VendorError(ValueError):
    """The vendored corpus cannot be trusted as it stands."""


@dataclass(frozen=True)
class VendoredSkill:
    label: str
    name: str
    path: Path
    version: str
    url: str = ""
    license: str = "unknown"

    @property
    def id(self) -> str:
        return f"{self.label}/{self.name}"

    @property
    def relative_path(self) -> str:
        """Where this came from upstream — what the catalogue records."""
        return f"{self.name}/{MAIN_FILE}"


def read_sidecar(directory: Path) -> dict:
    sidecar = Path(directory) / SIDECAR
    if not sidecar.is_file():
        raise VendorError(f"{directory}: no {SIDECAR}. Run scripts/vendor.py")
    parsed = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise VendorError(f"{sidecar}: must be a YAML mapping")
    return parsed


def load_skill(directory: Path) -> VendoredSkill:
    """One vendored skill, verified against its sidecar."""
    directory = Path(directory)
    recorded = read_sidecar(directory)
    main = directory / MAIN_FILE

    if not main.is_file():
        raise VendorError(f"{directory}: {MAIN_FILE} is missing")

    digest = content_hash(main.read_text(encoding="utf-8"))
    if digest != recorded.get("sha256"):
        raise VendorError(
            f"{directory}: {MAIN_FILE} does not match its sidecar "
            f"({digest[:12]} vs {str(recorded.get('sha256'))[:12]}). Vendored files "
            f"are quotations; re-vendor instead of editing them"
        )

    upstream = recorded.get("upstream") or {}
    return VendoredSkill(
        label=str(recorded["label"]),
        name=str(recorded["name"]),
        path=main,
        version=str(recorded["version"]),
        url=str(upstream.get("url", "")),
        license=str(recorded.get("license", "unknown")),
    )


def load_corpus(skills_dir: Path) -> tuple[list[VendoredSkill], list[str]]:
    """Every vendored skill, plus the problems found. Never raises.

    Returning the failures rather than throwing lets one broken skill be
    reported and skipped while the rest of a corpus still builds.
    """
    skills_dir = Path(skills_dir)
    found: list[VendoredSkill] = []
    problems: list[str] = []
    for sidecar in sorted(skills_dir.rglob(SIDECAR)):
        try:
            found.append(load_skill(sidecar.parent))
        except (VendorError, KeyError) as exc:
            problems.append(str(exc))
    return found, problems
