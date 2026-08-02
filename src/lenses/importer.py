"""Skills whose parts already exist as separate files.

Some upstreams ship one rule per file: `SKILL.md` is a table of contents and
the substance lives in `rules/*.md`, each self-contained, each with its own
frontmatter. Decomposing such a skill would cut up the contents page, drop the
rules entirely, and charge for the privilege.

So this path makes parts from files. The author drew the boundaries, wrote the
titles and stated the impact; re-deriving any of it with a model would cost
money to produce something worse and non-reproducible. No model is called
here, and a run over an imported skill is free and deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from .model import Part, SkillDoc
from .spans import content_hash, split_lines
from .vendored import VendoredSkill

#: Directories inside a skill whose files are parts in their own right.
PART_DIRECTORIES = ("rules",)

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
_SLUG = re.compile(r"[^a-z0-9]+")

#: File patterns that unambiguously mean Python. An author's own `paths:`
#: frontmatter is a real signal, not a guess from the skill's name.
_PYTHON_PATH_MARKERS = (
    ".py", "pyproject.toml", "setup.py", "setup.cfg", "conftest.py",
    "mypy.ini", "ruff.toml", "requirements",
)
#: Any of these alongside a Python marker makes the signal ambiguous — better
#: to say nothing than to tag a mixed-stack skill as just Python.
_OTHER_STACK_PATH_MARKERS = (
    ".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".kt", ".rs", ".rb", ".php", ".cs",
)

#: wispbit's own naming convention: one skill per stack, named
#: `{stack}-expert-best-practices[-code-review]`. Reading a stack out of a
#: structured name the author chose is not a guess — the same distinction
#: `stack_from_paths` draws for frontmatter, applied to a name instead.
_STACK_FROM_NAME = re.compile(
    r"^(?P<stack>[a-z0-9]+(?:-[a-z0-9]+)*)-expert-best-practices(?:-code-review)?$"
)


class ImportError_(ValueError):
    """A skill claims file-shaped parts but does not have them."""


@dataclass(frozen=True)
class RuleFile:
    relative: str
    frontmatter: dict
    body: str
    line_count: int


def has_parts_on_disk(directory: Path) -> bool:
    """Whether this skill ships its parts as files rather than as sections."""
    return any((Path(directory) / name).is_dir() for name in PART_DIRECTORIES)


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """The leading YAML block and the rest, or an empty mapping and the whole."""
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    parsed = yaml.safe_load(match.group(1))
    return (parsed if isinstance(parsed, dict) else {}), text[match.end():]


def slugify(value: str) -> str:
    return _SLUG.sub("-", value.strip().lower()).strip("-")


def read_rules(directory: Path) -> list[RuleFile]:
    """Every part-file in the skill, in a stable order."""
    found: list[RuleFile] = []
    for name in PART_DIRECTORIES:
        root = Path(directory) / name
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*.md")):
            if path.name.startswith("_"):
                # The author's own "not content" convention — a template or a
                # section index kept alongside the real rules for their own
                # tooling, not for an agent to cite.
                continue
            text = path.read_text(encoding="utf-8")
            frontmatter, body = parse_frontmatter(text)
            found.append(
                RuleFile(
                    relative=path.relative_to(directory).as_posix(),
                    frontmatter=frontmatter,
                    body=body,
                    line_count=len(split_lines(text)),
                )
            )
    return found


def applies_to(frontmatter: dict, fallback: str) -> str:
    """The author's own statement of what this is for.

    `title` names the topic, `impactDescription` states the problem it
    prevents — and a problem statement is the register a query arrives in.
    Neither is invented here: an upstream that already says why a rule matters
    has answered the question better than a paraphrase would.
    """
    title = str(frontmatter.get("title") or fallback).strip()
    impact = str(frontmatter.get("impactDescription") or "").strip().rstrip(".")
    return f"{title} — {impact}." if impact else f"{title}."


def as_tags(raw) -> list[str]:
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def stack_from_paths(paths) -> list[str]:
    """A stack read from the author's own `paths:` frontmatter.

    Fires only when every marker present is Python and none point elsewhere.
    """
    if not isinstance(paths, list) or not paths:
        return []
    text = " ".join(str(p) for p in paths).lower()
    if any(marker in text for marker in _OTHER_STACK_PATH_MARKERS):
        return []
    if any(marker in text for marker in _PYTHON_PATH_MARKERS):
        return ["python"]
    return []


def stack_from_name(name: str) -> list[str]:
    """A stack read from a known `{stack}-expert-best-practices` naming convention."""
    match = _STACK_FROM_NAME.match(name)
    return [match.group("stack")] if match else []


def infer_stacks(main_frontmatter: dict, skill_name: str) -> list[str]:
    """A stack read from a structural signal the author already provided.

    Tries `paths:` frontmatter first — a literal glob outweighs a naming
    convention — then a known naming pattern. Neither is a classifier: both
    return nothing rather than a guess when their specific signal is absent.
    """
    return stack_from_paths(main_frontmatter.get("paths")) or stack_from_name(skill_name)


def import_skill(skill: VendoredSkill) -> tuple[SkillDoc, list[str]]:
    """Build a catalogue document from a skill's part-files. Never calls a model."""
    directory = skill.path.parent
    rules = read_rules(directory)
    problems: list[str] = []

    if not rules:
        problems.append(f"{skill.id}: no part-files found under {PART_DIRECTORIES}")
        return SkillDoc(id=skill.id, version=skill.version, source={}, kind="reference",
                        summary="", parts=[]), problems

    parts: list[Part] = []
    seen: set[str] = set()
    for rule in rules:
        stem = Path(rule.relative).stem
        part_id = slugify(stem)
        if part_id in seen:
            problems.append(f"{skill.id}: duplicate part id {part_id!r} from {rule.relative}")
            continue
        seen.add(part_id)

        if not rule.body.strip():
            problems.append(f"{skill.id}: {rule.relative} has no body")
            continue

        parts.append(
            Part(
                id=part_id,
                title=str(rule.frontmatter.get("title") or stem).strip(),
                applies_to=applies_to(rule.frontmatter, stem),
                spans=[(1, rule.line_count)],
                file=rule.relative,
                tags=as_tags(rule.frontmatter.get("tags")),
                sha256=content_hash((directory / rule.relative).read_text(encoding="utf-8")),
            )
        )

    main_frontmatter, _ = parse_frontmatter(skill.path.read_text(encoding="utf-8"))
    full_hash = content_hash(skill.path.read_text(encoding="utf-8"))

    return (
        SkillDoc(
            id=skill.id,
            version=full_hash[:12],
            source={"url": skill.url, "path": skill.relative_path, "sha256": full_hash},
            license=skill.license,
            # `document_kinds` stays empty rather than being guessed: an
            # invented classifier is worse than a missing one. `stacks` gets
            # one chance to read a real signal the author already wrote —
            # see infer_stacks — and stays empty for the same reason when
            # neither signal fires.
            kind="reference",
            summary=str(main_frontmatter.get("description") or "").strip(),
            stacks=infer_stacks(main_frontmatter, skill.name),
            document_kinds=[],
            decomposed_by="author",
            parts=parts,
        ),
        problems,
    )


def check_imported(parts: list[Part]) -> list[str]:
    """Gates that apply when the author drew the boundaries.

    Coverage, overlap and granularity are not among them: those exist to catch
    a model cutting one document badly, and here there is no cutting to check.
    What remains is that every part is nameable, findable and non-empty.
    """
    problems: list[str] = []
    if not parts:
        problems.append("no parts")
    for part in parts:
        if not part.applies_to.strip():
            problems.append(f"{part.id}: no applies_to")
        if not part.file:
            problems.append(f"{part.id}: imported part without a file")
        if not part.spans or part.spans[0][1] < 1:
            problems.append(f"{part.id}: {part.file} appears to be empty")
    return problems
