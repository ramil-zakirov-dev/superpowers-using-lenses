"""The catalogue's data model, and its YAML form.

One file per skill *version*, committed to git. The YAML is the source of
truth; the embedding index is derived from it and can be thrown away. That
direction is what makes a pinned reference survive a rebuild, and what lets a
contributor propose a change as a reviewable diff rather than a row in
somebody's database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml

from .spans import Span

#: What the skill is for, as a whole. A `pipeline` is still catalogued: the
#: point of parts is to mine one for the few sections that are lenses without
#: adopting the workflow that comes with it.
SKILL_KINDS = ("lens", "pipeline", "reference")


@dataclass
class Part:
    """A stretch of a skill that stands on its own.

    Usually a span of the skill's own `SKILL.md`. When `file` is set the part
    is a whole separate file inside the skill — an upstream that already ships
    one rule per file has drawn the boundaries itself, and re-cutting them with
    a model would be paying to do worse.
    """

    id: str
    title: str
    applies_to: str
    spans: list[Span]
    preamble_spans: list[Span] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    kind: str | None = None
    sha256: str = ""
    #: Path inside the skill directory. None means the spans cut `SKILL.md`.
    file: str | None = None
    #: Author-supplied keywords, kept because discarding them would mean
    #: re-reading the corpus to get them back once lexical search exists.
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "applies_to": self.applies_to,
        }
        if self.kind:
            data["kind"] = self.kind
        if self.file:
            data["file"] = self.file
        if self.preamble_spans:
            data["preamble_spans"] = [list(span) for span in self.preamble_spans]
        data["spans"] = [list(span) for span in self.spans]
        if self.requires:
            data["requires"] = list(self.requires)
        if self.tags:
            data["tags"] = list(self.tags)
        data["sha256"] = self.sha256
        return data


@dataclass
class SkillDoc:
    """One upstream skill, at one version, decomposed."""

    id: str
    version: str
    source: dict[str, Any]
    kind: str
    summary: str
    parts: list[Part]
    license: str = "unknown"
    stacks: list[str] = field(default_factory=lambda: ["any"])
    document_kinds: list[str] = field(default_factory=list)
    #: The model that marked up this file. Provenance, not decoration: a
    #: decomposition cut by the fallback deserves a closer read than one cut
    #: by the model the catalogue was calibrated on.
    decomposed_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "source": self.source,
            "license": self.license,
            "kind": self.kind,
            "stacks": list(self.stacks),
            "document_kinds": list(self.document_kinds),
            "summary": self.summary,
            "decomposed_by": self.decomposed_by,
            "parts": [part.to_dict() for part in self.parts],
        }

    def to_yaml(self) -> str:
        return yaml.safe_dump(
            self.to_dict(),
            sort_keys=False,
            allow_unicode=True,
            width=88,
        )


def load_skill_doc(text: str) -> dict[str, Any]:
    """Parse a catalogue file back into plain data."""
    parsed = yaml.safe_load(text)
    if not isinstance(parsed, dict):
        raise ValueError("a catalogue file must be a YAML mapping")
    return parsed
