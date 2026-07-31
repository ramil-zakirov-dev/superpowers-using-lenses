"""Copy upstream skills into `skills/`, the first stage of the pipeline.

    upstream checkout --> scripts/vendor.py --> skills/ --> lenses.ingest --> catalog/

Reads `sources.yaml` for where to copy from and which skills to take. Writes
each skill's directory byte for byte — `SKILL.md` *and* its `references/`,
because a skill's main file is an index into the rest and vendoring it alone
produces something that looks complete and is not.

The version is computed here, from the text: it is the first twelve characters
of the source hash. It goes into a sidecar rather than into the file's own
frontmatter, because the version *is* that hash — writing it inside would
change the thing being identified.

    python scripts/vendor.py [--only LABEL] [--skill NAME] [--check]
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from lenses.config import ConfigError, load_config  # noqa: E402
from lenses.sources import SourceError, Source, load_sources, selects  # noqa: E402
from lenses.spans import content_hash  # noqa: E402
from lenses.vendored import MAIN_FILE, SIDECAR  # noqa: E402


def file_hash(path: Path) -> str:
    """Raw bytes, unlike the version, which hashes normalised text."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def skill_files(directory: Path) -> list[Path]:
    """Every file in the skill, relative to it, in a stable order."""
    return sorted(
        (path.relative_to(directory) for path in directory.rglob("*") if path.is_file()),
        key=lambda path: path.as_posix(),
    )


def sidecar_text(source: Source, name: str, digest: str, hashes: dict[str, str]) -> str:
    return yaml.safe_dump(
        {
            "name": name,
            "label": source.label,
            "version": digest[:12],
            "sha256": digest,
            "upstream": {"url": source.url, "path": f"{name}/{MAIN_FILE}"},
            "license": source.license,
            "files": hashes,
        },
        sort_keys=False,
        allow_unicode=True,
    )


def vendor_one(source: Source, origin: Path, skills_dir: Path) -> tuple[str, int]:
    """Copy one skill directory verbatim. Returns (version, file count)."""
    name = origin.name
    digest = content_hash((origin / MAIN_FILE).read_text(encoding="utf-8"))
    target = skills_dir / source.label / name

    hashes: dict[str, str] = {}
    for relative in skill_files(origin):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((origin / relative).read_bytes())
        hashes[relative.as_posix()] = file_hash(origin / relative)

    (target / SIDECAR).write_text(sidecar_text(source, name, digest, hashes), encoding="utf-8")
    return digest[:12], len(hashes)


def check_corpus(skills_dir: Path) -> tuple[int, int]:
    """Re-hash every vendored file against its sidecar. No model, no network."""
    ok = drifted = 0
    for sidecar in sorted(skills_dir.rglob(SIDECAR)):
        recorded = yaml.safe_load(sidecar.read_text(encoding="utf-8"))
        directory = sidecar.parent
        broken = [
            relative
            for relative, digest in (recorded.get("files") or {}).items()
            if not (directory / relative).is_file() or file_hash(directory / relative) != digest
        ]
        label = f"{recorded.get('label')}/{recorded.get('name')}"
        if broken:
            print(f"  DRIFTED  {label}: {len(broken)} file(s) changed: {broken[:3]}")
            drifted += 1
        else:
            print(f"  ok       {label} @ {recorded.get('version')} "
                  f"({len(recorded.get('files') or {})} file(s))")
            ok += 1
    return ok, drifted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vendor upstream skills into skills/.")
    parser.add_argument("--manifest", type=Path, default=REPO / "sources.yaml")
    parser.add_argument("--skills", type=Path, default=REPO / "skills")
    parser.add_argument("--only", action="append", metavar="LABEL")
    parser.add_argument("--skill", action="append", metavar="NAME", help="glob; repeatable")
    parser.add_argument("--check", action="store_true",
                        help="verify the vendored corpus; copy nothing")
    args = parser.parse_args(argv)

    if args.check:
        ok, drifted = check_corpus(args.skills)
        print(f"done: {ok} verified, {drifted} drifted")
        return 1 if drifted else 0

    try:
        config = load_config(REPO / ".env")
        sources = [s for s in load_sources(args.manifest, config.sources_root) if s.enabled]
    except (ConfigError, SourceError) as exc:
        print(f"config: {exc}", file=sys.stderr)
        return 2

    if args.only:
        sources = [source for source in sources if source.label in set(args.only)]

    copied = missing = 0
    for source in sources:
        if not source.path.exists():
            print(f"  MISSING  {source.label}: {source.path} does not exist")
            missing += 1
            continue
        for main_file in sorted(source.path.rglob(MAIN_FILE)):
            name = main_file.parent.name
            if not selects(source, name):
                continue
            if args.skill and not any(fnmatch.fnmatch(name, p) for p in args.skill):
                continue
            version, count = vendor_one(source, main_file.parent, args.skills)
            print(f"  vendored {source.label}/{name} @ {version}  ({count} file(s))")
            copied += 1

    print(f"done: {copied} vendored, {missing} source(s) missing")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
