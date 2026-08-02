"""List the skills in a checkout by name and description, without their bodies.

    upstream checkout --> scripts/survey.py --> what is there, and is it vendored?

A skill's `SKILL.md` is frontmatter followed by a few thousand words of body.
Deciding *which* skills to take needs only the frontmatter, so this reads line
by line and stops at the closing `---`: choosing from 62 skills costs the
descriptions, not the corpus.

    python scripts/survey.py [ROOT] [--vendored DIR] [--only new|vendored]
                             [--match TEXT] [--full] [--format table|md|json]

ROOT defaults to the upstream wondelai checkout under `sources_root`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from lenses.config import ConfigError, load_config  # noqa: E402
from lenses.vendored import MAIN_FILE  # noqa: E402

FENCE = "---"
SUMMARY_CHARS = 150


@dataclass
class Skill:
    """One skill, seen from its frontmatter and its directory listing."""

    name: str
    directory: Path
    description: str = ""
    version: str = ""
    files: int = 0
    kilobytes: int = 0
    vendored_as: str = ""
    error: str = ""

    references: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "path": self.directory.as_posix(),
            "description": self.description,
            "version": self.version,
            "files": self.files,
            "kilobytes": self.kilobytes,
            "vendored_as": self.vendored_as,
            "references": self.references,
            "error": self.error,
        }


def read_frontmatter(main_file: Path) -> dict:
    """Parse the leading `---` block. The body is never read.

    Raises ValueError when the file does not open with a fence or never closes
    it — a skill whose frontmatter cannot be found is a defect, not an empty
    description.
    """
    lines: list[str] = []
    with main_file.open(encoding="utf-8") as handle:
        first = handle.readline()
        if first.strip() != FENCE:
            raise ValueError("no frontmatter fence on line 1")
        for line in handle:
            if line.strip() == FENCE:
                break
            lines.append(line)
        else:
            raise ValueError("frontmatter fence never closes")

    parsed = yaml.safe_load("".join(lines))
    if not isinstance(parsed, dict):
        raise ValueError("frontmatter is not a mapping")
    return parsed


def cross_references(description: str) -> list[str]:
    """The `see other-skill` pointers a description ends with.

    These are the catalogue's own topology: a skill that three others point at
    is load-bearing, and taking it alone leaves those pointers dangling.
    """
    found: list[str] = []
    for sentence in description.replace("\n", " ").split("."):
        _, separator, tail = sentence.partition("see ")
        if not separator:
            continue
        candidate = tail.strip().strip("'\"").rstrip(",;:")
        if candidate and " " not in candidate:
            found.append(candidate)
    return found


def weigh(directory: Path) -> tuple[int, int]:
    """(file count, kilobytes) — how much context taking this skill costs."""
    files = [path for path in directory.rglob("*") if path.is_file()]
    return len(files), round(sum(path.stat().st_size for path in files) / 1024)


def vendored_names(skills_dir: Path) -> dict[str, str]:
    """Skill name -> `label/name`, for everything already in the corpus."""
    if not skills_dir.is_dir():
        return {}
    return {
        main_file.parent.name: f"{main_file.parent.parent.name}/{main_file.parent.name}"
        for main_file in skills_dir.rglob(MAIN_FILE)
    }


def survey(root: Path, vendored: dict[str, str]) -> list[Skill]:
    skills: list[Skill] = []
    for main_file in sorted(root.rglob(MAIN_FILE)):
        directory = main_file.parent
        files, kilobytes = weigh(directory)
        skill = Skill(
            name=directory.name,
            directory=directory,
            files=files,
            kilobytes=kilobytes,
            vendored_as=vendored.get(directory.name, ""),
        )
        try:
            front = read_frontmatter(main_file)
        except (ValueError, yaml.YAMLError, UnicodeDecodeError) as exc:
            skill.error = str(exc)
        else:
            skill.name = str(front.get("name") or directory.name)
            skill.description = " ".join(str(front.get("description") or "").split())
            metadata = front.get("metadata")
            skill.version = str((metadata or {}).get("version", "")) if isinstance(metadata, dict) else ""
            skill.references = cross_references(skill.description)
        skills.append(skill)
    return skills


def summarise(description: str, full: bool) -> str:
    if full or len(description) <= SUMMARY_CHARS:
        return description
    return description[:SUMMARY_CHARS].rsplit(" ", 1)[0] + "…"


def print_table(skills: list[Skill], full: bool) -> None:
    width = max((len(skill.name) for skill in skills), default=4)
    for skill in skills:
        mark = "*" if skill.vendored_as else " "
        text = skill.error and f"BROKEN: {skill.error}" or summarise(skill.description, full)
        print(f"{mark} {skill.name:<{width}}  {skill.files:>3}f {skill.kilobytes:>4}K  {text}")


def print_markdown(skills: list[Skill], full: bool) -> None:
    print("| Skill | Vendored | Size | Description |")
    print("|---|---|---|---|")
    for skill in skills:
        text = (skill.error and f"**BROKEN**: {skill.error}" or summarise(skill.description, full))
        cell = text.replace("|", "\\|")
        print(
            f"| `{skill.name}` | {skill.vendored_as or '—'} "
            f"| {skill.files}f / {skill.kilobytes}K | {cell} |"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("root", nargs="?", type=Path,
                        help="checkout to survey (default: the wondelai upstream)")
    parser.add_argument("--vendored", type=Path, default=REPO / "skills",
                        help="corpus to mark against (default: skills/)")
    parser.add_argument("--only", choices=("new", "vendored"),
                        help="show only what is missing from, or already in, the corpus")
    parser.add_argument("--match", action="append", metavar="TEXT",
                        help="case-insensitive substring of name or description; repeatable")
    parser.add_argument("--full", action="store_true", help="whole description, not a summary")
    parser.add_argument("--format", choices=("table", "md", "json"), default="table")
    args = parser.parse_args(argv)

    root = args.root
    if root is None:
        try:
            root = load_config(REPO / ".env").sources_root / "wondelai-skills"
        except ConfigError as exc:
            print(f"config: {exc}", file=sys.stderr)
            return 2
    if not root.is_dir():
        print(f"survey: {root} does not exist", file=sys.stderr)
        return 2

    skills = survey(root, vendored_names(args.vendored))
    if args.only == "new":
        skills = [skill for skill in skills if not skill.vendored_as]
    elif args.only == "vendored":
        skills = [skill for skill in skills if skill.vendored_as]
    for text in args.match or []:
        needle = text.lower()
        skills = [s for s in skills if needle in s.name.lower() or needle in s.description.lower()]

    if args.format == "json":
        print(json.dumps([skill.as_dict() for skill in skills], indent=2, ensure_ascii=False))
        return 0

    if not skills:
        print("no skills matched")
        return 0
    (print_markdown if args.format == "md" else print_table)(skills, args.full)

    broken = sum(1 for skill in skills if skill.error)
    taken = sum(1 for skill in skills if skill.vendored_as)
    print(f"\n{len(skills)} skill(s) under {root}: {taken} vendored (*), "
          f"{len(skills) - taken} not, {broken} unreadable")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main())
