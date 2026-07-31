"""MCP adapter: the corpus, exposed to an agent over stdio.

Thin on purpose. Ranking lives in `search`, resolution in `resolve`, and both
are pure — this module only turns their results into tool responses. Every
argument about relevance can therefore be settled by a test rather than by
starting a server.

    LENSES_HOME=/path/to/repo python -m lenses.mcp_server

The index is read once at startup. Re-running ingest does not reach a server
that is already running: restart the client after rebuilding the corpus.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from .config import Config, ConfigError, load_config
from .embed import EmbedError, embed_query
from .resolve import resolve
from .search import Corpus, SearchError, load_index, rank

HOME = Path(os.environ.get("LENSES_HOME", "")).expanduser() or Path.cwd()

server = MCPServer(
    "using-lenses",
    instructions=(
        "A catalogue of vendored agent skills, cut into independently usable "
        "parts. Search it with find_lenses before designing a milestone, a "
        "slice spec or a plan; cite the returned references in the document's "
        "`lenses:` frontmatter; read them with get_lenses."
    ),
)

_config: Config | None = None
_corpus: Corpus | None = None


def startup() -> tuple[Config, Corpus]:
    """Load configuration and index once, failing loudly if either is absent."""
    global _config, _corpus
    if _config is None or _corpus is None:
        _config = load_config(HOME / ".env")
        _corpus = Corpus(load_index(HOME / "index" / "embeddings.jsonl"))
    return _config, _corpus


@server.tool()
def find_lenses(
    intent: str,
    limit: int = 6,
    kind: str | None = None,
    stack: str | None = None,
) -> dict[str, Any]:
    """Find the parts of vendored skills that bear on a piece of work.

    State the need, not the solution: "an external call can hang and must not
    take the system down" retrieves better than "circuit breaker", because
    parts are indexed by when they apply.

    Returns references of the form `label/name#part@version`. Cite those in a
    document's `lenses:` frontmatter — the version pins the text, so the
    citation cannot come to mean something else when upstream is rewritten.
    Pass a reference to `get_lenses` to read the part itself.

    `kind` filters to `lens` (vocabulary and criteria for judgement),
    `reference` (APIs, checklists, rules) or `pipeline` (a prescribed
    sequence). `stack` narrows to a technology; parts that are not
    stack-specific always match.
    """
    try:
        config, corpus = startup()
        vector = embed_query(config.embedder, intent, config.embedder_dim)
    except (ConfigError, SearchError) as exc:
        return {"error": str(exc)}
    except EmbedError as exc:
        return {"error": f"the embedding endpoint is unreachable or misconfigured: {exc}"}

    hits = rank(vector, corpus.parts, limit=limit, kind=kind, stack=stack)
    return {
        "intent": intent,
        "results": [
            {
                "ref": hit.part.ref,
                "title": hit.part.title,
                "applies_to": hit.part.applies_to,
                "kind": hit.part.kind,
                "tags": list(hit.part.tags),
                "score": round(hit.score, 4),
            }
            for hit in hits
        ],
    }


@server.tool()
def get_lenses(refs: list[str]) -> dict[str, Any]:
    """Read the parts named by `label/name#part@version` references.

    Each part is verbatim upstream text, verified against the hash recorded
    when it was catalogued. A reference whose text has changed is reported as
    an error rather than returned: a citation that resolves to different text
    is worse than one that fails, because nobody notices it.
    """
    try:
        startup()
    except (ConfigError, SearchError) as exc:
        return {"error": str(exc)}

    parts: list[dict[str, Any]] = []
    errors: list[str] = []
    for ref in refs:
        try:
            found = resolve(ref, HOME / "catalog", HOME / "skills")
        except SearchError as exc:
            errors.append(str(exc))
            continue
        parts.append(
            {
                "ref": found.ref,
                "title": found.title,
                "applies_to": found.applies_to,
                "kind": found.kind,
                "tags": list(found.tags),
                "license": found.license,
                "source": found.url or found.file,
                "text": found.text,
            }
        )
    return {"parts": parts, "errors": errors}


@server.tool()
def list_skills() -> dict[str, Any]:
    """What the corpus holds: every skill, its part count and its kinds.

    Use it to see whether the corpus covers a domain at all before concluding
    from an empty-looking search that nothing applies.
    """
    try:
        _, corpus = startup()
    except (ConfigError, SearchError) as exc:
        return {"error": str(exc)}

    skills = []
    for skill_id, parts in sorted(corpus.skills.items()):
        kinds: dict[str, int] = {}
        for part in parts:
            kinds[part.kind] = kinds.get(part.kind, 0) + 1
        skills.append(
            {
                "skill_id": skill_id,
                "version": parts[0].version,
                "parts": len(parts),
                "kinds": kinds,
                "stacks": sorted({stack for part in parts for stack in part.stacks}),
            }
        )
    return {"home": str(HOME), "skills": skills, "total_parts": len(corpus.parts)}


def main() -> int:
    try:
        startup()
    except (ConfigError, SearchError) as exc:
        # Fail at launch with something readable rather than on the first call
        # with a stack trace the client will swallow.
        print(f"using-lenses: {exc}", file=sys.stderr)
        return 2
    server.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
