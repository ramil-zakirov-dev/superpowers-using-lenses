"""Decompose the vendored corpus into parts, and index them.

    upstream checkout --> scripts/vendor.py --> skills/ --> this --> catalog/ --> index/

Input is `skills/`, never an upstream checkout: what gets decomposed is what is
committed, so a catalogue entry can be reproduced from a clone on a machine
that never had the upstream. Provenance rides in each skill's sidecar rather
than on the command line.

A catalogue file is keyed by the source's content hash, so re-running over
unchanged skills does nothing. That is not only a speed trick: decomposition
is non-deterministic, and re-deriving parts nobody asked to change would move
every part id and break every reference pinned to them.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import sys
from pathlib import Path

import httpx

from .config import Config, ConfigError, load_config
from .decompose import DecompositionError, check, decompose_with_fallback
from .embed import EmbedError, embed_texts
from .importer import check_imported, has_parts_on_disk, import_skill
from .model import SKILL_KINDS, SkillDoc, load_skill_doc
from .spans import content_hash, extract, split_lines
from .vendored import VendoredSkill, load_corpus

#: Above this many skills in one run, ask for --yes. Every skill is a paid
#: call to a hosted model; a whole corpus should not start because a flag was
#: forgotten.
CONFIRM_ABOVE = 25


def build_plan(
    corpus: list[VendoredSkill],
    limit: int | None = None,
    labels: tuple[str, ...] = (),
    names: tuple[str, ...] = (),
) -> list[VendoredSkill]:
    """The skills this run will touch, after narrowing."""
    plan = [
        skill
        for skill in corpus
        if (not labels or skill.label in labels)
        and (not names or any(fnmatch.fnmatch(skill.name, pattern) for pattern in names))
    ]
    return plan[:limit] if limit else plan


def decompose_file(skill: VendoredSkill, config: Config) -> tuple[SkillDoc, list[str]]:
    """Decompose one vendored skill. Returns the document and gate failures."""
    raw = skill.path.read_text(encoding="utf-8")
    lines = split_lines(raw)
    full_hash = content_hash(raw)

    payload, parts, model_used = decompose_with_fallback(
        config.llm, config.llm_fallback, skill.id, lines
    )
    problems = check(parts, len(lines), config.min_coverage)

    for part in parts:
        part.sha256 = content_hash(extract(lines, list(part.preamble_spans) + list(part.spans)))

    kind = payload.get("kind")
    if kind not in SKILL_KINDS:
        problems.append(f"skill kind {kind!r} is not one of {list(SKILL_KINDS)}")
        kind = "reference"

    return (
        SkillDoc(
            id=skill.id,
            version=full_hash[:12],
            source={"url": skill.url, "path": skill.relative_path, "sha256": full_hash},
            license=skill.license,
            kind=kind,
            summary=str(payload.get("summary", "")).strip(),
            stacks=[str(item) for item in payload.get("stacks") or ["any"]],
            document_kinds=[str(item) for item in payload.get("document_kinds") or []],
            decomposed_by=model_used,
            parts=parts,
        ),
        problems,
    )


def catalog_parts(catalog_dir: Path) -> list[dict]:
    """Every part in the catalogue on disk.

    The index is derived from the catalogue, so this — not whatever the current
    run happened to write — is its input. Building it from the run's output
    instead silently truncates the index to the last batch: re-running one
    skill would drop the other ninety parts, and nothing would say so until a
    search returned nothing.
    """
    rows: list[dict] = []
    for path in sorted(Path(catalog_dir).rglob("*.yaml")):
        document = load_skill_doc(path.read_text(encoding="utf-8"))
        for part in document.get("parts") or []:
            rows.append(
                {
                    "skill_id": document["id"],
                    "version": document["version"],
                    "part_id": part["id"],
                    # `or`, not a get-default: decompose lets a model return an
                    # empty title, and an empty one is not a name to index by.
                    "title": part.get("title") or part["id"],
                    "kind": part.get("kind") or document.get("kind"),
                    "stacks": document.get("stacks") or [],
                    # Which documents this skill bears on. Carried to the index
                    # for `list_skills` to report coverage from, deliberately
                    # not as a search filter: measured on this corpus, the
                    # target part is already at dense rank 1-3 in sixteen of
                    # seventeen eval cases, so a filter has nothing to remove
                    # — and the one case it could help still misses the top six
                    # after filtering. What it does buy is a caller who can see
                    # that the corpus holds one org lens and no operations
                    # ones before writing a milestone brief against it.
                    "document_kinds": document.get("document_kinds") or [],
                    "tags": part.get("tags") or [],
                    "sha256": part["sha256"],
                    "applies_to": part["applies_to"],
                }
            )
    return rows


def write_index(index_dir: Path, rows: list[dict]) -> Path:
    """The derived index: one JSON object per part, vector included."""
    index_dir.mkdir(parents=True, exist_ok=True)
    target = index_dir / "embeddings.jsonl"
    with target.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    return target


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lenses",
        description="Decompose the vendored skills in skills/ into parts, and index them.",
    )
    parser.add_argument("--skills", type=Path, default=Path("skills"),
                        help="the vendored corpus (default: skills/)")
    parser.add_argument("--only", action="append", metavar="LABEL",
                        help="run just this label; repeatable")
    parser.add_argument("--skill", action="append", metavar="NAME",
                        help="run just this skill (glob); repeatable")
    parser.add_argument("--out", type=Path, default=Path("catalog"))
    parser.add_argument("--index", type=Path, default=Path("index"))
    parser.add_argument("--force", action="store_true", help="re-decompose what is catalogued")
    parser.add_argument("--limit", type=int, help="stop after this many skills")
    parser.add_argument("--no-embed", action="store_true", help="catalogue only, skip the index")
    parser.add_argument("--dry-run", action="store_true",
                        help="list the skills that would be processed; call nothing")
    parser.add_argument("--yes", action="store_true",
                        help=f"proceed without asking above {CONFIRM_ABOVE} skills")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"config: {exc}", file=sys.stderr)
        return 2

    if not args.skills.exists():
        print(f"no vendored corpus at {args.skills}. Run scripts/vendor.py first",
              file=sys.stderr)
        return 2

    corpus, problems = load_corpus(args.skills)
    for problem in problems:
        print(f"  BROKEN   {problem}", file=sys.stderr)
    if problems:
        # An edited quotation is not a thing to decompose around.
        print(f"{len(problems)} vendored skill(s) failed verification", file=sys.stderr)
        return 2
    if not corpus:
        print(f"{args.skills} holds no vendored skills", file=sys.stderr)
        return 1

    plan = build_plan(corpus, args.limit, tuple(args.only or ()), tuple(args.skill or ()))
    if not plan:
        print("nothing selected — check --only and --skill", file=sys.stderr)
        return 1

    for label in sorted({skill.label for skill in plan}):
        count = sum(1 for skill in plan if skill.label == label)
        print(f"{label}: {count} skill(s)")

    paid = [skill for skill in plan if not has_parts_on_disk(skill.path.parent)]

    if args.dry_run:
        # Deliberately before any model call. "Show me what this would do" must
        # not itself be the expensive thing, or it is useless as a safety check.
        for skill in plan:
            mode = "decompose" if skill in paid else "import   "
            print(f"  {mode}  {skill.id} @ {skill.version}")
        print(f"done: {len(plan)} planned — {len(paid)} decomposed, "
              f"{len(plan) - len(paid)} imported; nothing called, nothing written")
        return 0

    if len(paid) > CONFIRM_ABOVE and not args.yes:
        print(
            f"\n{len(paid)} skills is a paid run against {config.llm.base_url}.\n"
            f"Re-run with --dry-run to see the plan, --limit N to try a few, "
            f"or --yes to proceed.",
            file=sys.stderr,
        )
        return 2

    written = skipped = failed = 0
    for skill in plan:
        target = args.out / skill.label / skill.name / f"{skill.version}.yaml"
        if target.exists() and not args.force:
            print(f"  skip     {skill.id} (already at {skill.version})")
            skipped += 1
            continue

        try:
            if has_parts_on_disk(skill.path.parent):
                # The author already cut this one up. Nothing to ask a model.
                document, gate_failures = import_skill(skill)
                gate_failures = gate_failures + check_imported(document.parts)
            else:
                document, gate_failures = decompose_file(skill, config)
        except (DecompositionError, httpx.HTTPError, OSError) as exc:
            # A skill that cannot be decomposed is one failure, not the end of
            # the run: a build over sixty skills should not be lost because the
            # sixth timed out.
            print(f"  FAIL     {skill.id}: {exc}")
            failed += 1
            continue

        if gate_failures:
            print(f"  FAIL     {skill.id}: {len(gate_failures)} gate failure(s)")
            for problem in gate_failures:
                print(f"             - {problem}")
            failed += 1
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document.to_yaml(), encoding="utf-8")
        print(f"  wrote    {target} ({len(document.parts)} parts)")
        written += 1

    if not args.no_embed:
        rows = catalog_parts(args.out)
        if rows:
            try:
                # `applies_to` alone, deliberately. Prefixing the title was
                # tried and measured: it fixes the one thing it should — the
                # name of a technique becomes searchable, "tracer bullets"
                # goes from rank >40 to 1 — and costs more than it buys. A
                # two-to-five word topic noun pulls the vector out of the
                # space of *moments* and into the space of *topics*, which is
                # the wrong space: find_lenses asks callers for a need, not a
                # solution. Every need-phrased query got worse (rank 9 -> 14,
                # 11 -> 26) and the eval went 16/17 -> 15/17. If the lexical
                # entrance is wanted, it needs a second signal, not a longer
                # string on this one.
                #
                # Measured on bge-small (384). The embedder has since moved to
                # bge-base (768), which fixed that same tracer-bullets case on
                # its own — dense rank 58 -> 8, enough to reach the reranker's
                # pool. So the finding stands unretested rather than refuted:
                # the reason to try the prefix again is gone, not disproved.
                vectors = embed_texts(
                    config.embedder,
                    [row["applies_to"] for row in rows],
                    config.embedder_dim,
                )
            except EmbedError as exc:
                print(f"embeddings: {exc}", file=sys.stderr)
                return 3
            for row, vector in zip(rows, vectors):
                row["vector"] = vector
            target = write_index(args.index, rows)
            print(f"indexed {len(rows)} part(s) from {args.out} -> {target}")

    print(f"done: {written} written, {skipped} skipped, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
