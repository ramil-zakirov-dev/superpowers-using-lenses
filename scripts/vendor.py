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

Where the bytes came from is recorded twice, on purpose. `sources.yaml` names
the upstream commit this catalogue was built against — a declaration, written
by a human, that a reader can check out. Each sidecar records the HEAD the
copy actually observed — derived, and so unable to drift. This refuses to run
when the two disagree, because vendoring anyway would leave the manifest
describing a state the corpus did not come from.

    python scripts/vendor.py [--only LABEL] [--skill NAME] [--check]
                             [--accept-upstream]
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import subprocess
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


def checkout_commit(path: Path) -> str:
    """The upstream's HEAD, or "" when the path is not a git checkout.

    A source that is a plain directory is legitimate and unpinned. What is not
    legitimate is a manifest that names a commit while the bytes come from
    somewhere else — see the check in `main`.
    """
    try:
        done = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout.strip() if done.returncode == 0 else ""


def skill_files(directory: Path) -> list[Path]:
    """Every file in the skill, relative to it, in a stable order."""
    return sorted(
        (path.relative_to(directory) for path in directory.rglob("*") if path.is_file()),
        key=lambda path: path.as_posix(),
    )


def sidecar_text(
    source: Source, name: str, digest: str, hashes: dict[str, str], commit: str
) -> str:
    upstream = {"url": source.url, "path": f"{name}/{MAIN_FILE}"}
    if commit:
        # The observed HEAD, not the manifest's declaration: this records where
        # these bytes actually came from, and cannot go stale the way a
        # hand-written pin can.
        upstream["commit"] = commit
    return yaml.safe_dump(
        {
            "name": name,
            "label": source.label,
            "version": digest[:12],
            "sha256": digest,
            "upstream": upstream,
            "license": source.license,
            "files": hashes,
        },
        sort_keys=False,
        allow_unicode=True,
    )


def vendor_one(source: Source, origin: Path, skills_dir: Path, commit: str = "") -> tuple[str, int]:
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

    (target / SIDECAR).write_text(
        sidecar_text(source, name, digest, hashes, commit), encoding="utf-8"
    )
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
    parser.add_argument("--accept-upstream", action="store_true",
                        help="vendor even where the checkout has moved past the pinned commit")
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

    copied = missing = moved = 0
    for source in sources:
        if not source.path.exists():
            print(f"  MISSING  {source.label}: {source.path} does not exist")
            missing += 1
            continue

        head = checkout_commit(source.path)
        if source.commit and head and head != source.commit and not args.accept_upstream:
            # Copying anyway would make the manifest describe a state these
            # bytes did not come from. Refuse: the point of the pin is that a
            # deliberate catalogue moves upstream deliberately.
            print(f"  MOVED    {source.label}: manifest pins {source.commit[:12]}, "
                  f"checkout is at {head[:12]}")
            print(f"           re-run with --accept-upstream, then set "
                  f"commit: {head} in the manifest")
            moved += 1
            continue

        for main_file in sorted(source.path.rglob(MAIN_FILE)):
            name = main_file.parent.name
            if not selects(source, name):
                continue
            if args.skill and not any(fnmatch.fnmatch(name, p) for p in args.skill):
                continue
            version, count = vendor_one(source, main_file.parent, args.skills, head)
            print(f"  vendored {source.label}/{name} @ {version}  ({count} file(s))")
            copied += 1

        if source.commit and head and head != source.commit:
            print(f"  ACCEPTED {source.label}: vendored from {head[:12]}, not the "
                  f"pinned {source.commit[:12]} — set commit: {head} in the manifest")
        elif source.commit and not head:
            print(f"  UNPINNED {source.label}: {source.path} is not a git checkout, "
                  f"but the manifest pins {source.commit[:12]}")

    print(f"done: {copied} vendored, {missing} source(s) missing, {moved} moved upstream")
    return 1 if missing or moved else 0


if __name__ == "__main__":
    raise SystemExit(main())
