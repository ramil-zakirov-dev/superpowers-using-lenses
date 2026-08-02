"""MCP adapter: the corpus, exposed to an agent over stdio.

Thin on purpose. Ranking lives in `search`, re-ranking in `rerank`, resolution
in `resolve` — this module only turns their results into tool responses.
`search.rank` takes a vector, never a model. `rerank.rerank` takes its scorer
as an injectable argument: the default one loads a cross-encoder, but a test
swaps in a fake and never touches torch. Either way, arguments about
relevance can be settled by a test rather than by starting a server.

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
from .rerank import RerankError, confident, rerank
from .resolve import resolve
from .search import Corpus, SearchError, load_index, rank

HOME = Path(os.environ.get("LENSES_HOME", "")).expanduser() or Path.cwd()

#: Candidates handed to the reranker before it is cut down to `limit`. A
#: bigger, loosely-capped pool gives the cross-encoder real breadth to judge
#: — pre-filtering it down to `limit` with the cosine pass first would just
#: reproduce the bi-encoder's mistakes one stage later.
CANDIDATE_POOL = 20
CANDIDATE_PER_SKILL = 4

server = MCPServer(
    "using-lenses",
    instructions=(
        "A catalogue of vendored agent skills, cut into independently usable "
        "parts. Before designing a milestone, a slice spec or a plan, search "
        "it: find_lenses for one need, find_lenses_batch for everything the "
        "document needs at once. Cite the returned references in the "
        "document's `lenses:` frontmatter; read them with get_lenses."
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


def _find_one(
    intent: str,
    config: Config,
    corpus: Corpus,
    limit: int,
    kind: str | None,
    stack: str | None,
) -> dict[str, Any]:
    """One need, searched and reranked. Raises EmbedError or RerankError."""
    vector = embed_query(config.embedder, intent, config.embedder_dim)
    dense_hits = rank(vector, corpus.parts, limit=limit, kind=kind, stack=stack)
    candidates = rank(
        vector, corpus.parts,
        limit=max(CANDIDATE_POOL, limit), per_skill=CANDIDATE_PER_SKILL,
        kind=kind, stack=stack,
    )
    reranked_hits = rerank(intent, candidates, top_n=limit)
    # A query the reranker has no opinion about scores its whole pool in a
    # narrow, uniformly bad band — trusting that ordering anyway is how a
    # correct dense answer gets silently dropped. See scripts/eval_retrieval.py.
    trusted_rerank = confident(reranked_hits)
    hits = reranked_hits if trusted_rerank else dense_hits
    return {
        "intent": intent,
        "reranked": trusted_rerank,
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
def find_lenses(
    intent: str,
    limit: int = 6,
    kind: str | None = None,
    stack: str | None = None,
) -> dict[str, Any]:
    """Find the parts of vendored skills that bear on one design need.

    Before writing a milestone brief, a slice spec or a plan, state the need
    itself, not the project it belongs to: "I need guidance on keeping a
    call to an external payment API from taking the whole service down"
    retrieves better than "circuit breaker" — and better than the same need
    with "because I'm designing the checkout slice" appended, which
    measurably drags the match toward whatever nouns that clause happens to
    contain rather than the need (verified: it can bury a part that ranked
    first without it). Know why the need matters — you want that for the
    record you leave in `lenses:` — but keep the why out of the query.

    One call is one need. To gather everything a milestone or a slice needs
    at once, call find_lenses_batch instead — same phrasing, one need per
    entry, same order back.

    Returns references of the form `label/name#part@version`. Cite those in
    the document's `lenses:` frontmatter — the version pins the text, so the
    citation cannot come to mean something else when upstream is rewritten.
    Pass a reference to `get_lenses` to read the part itself.

    `kind` filters to `lens` (vocabulary and criteria for judgement),
    `reference` (APIs, checklists, rules) or `pipeline` (a prescribed
    sequence). `stack` narrows to a technology; parts that are not
    stack-specific always match.
    """
    try:
        config, corpus = startup()
    except (ConfigError, SearchError) as exc:
        return {"error": str(exc)}
    try:
        return _find_one(intent, config, corpus, limit, kind, stack)
    except EmbedError as exc:
        return {"error": f"the embedding endpoint is unreachable or misconfigured: {exc}"}
    except RerankError as exc:
        return {"error": f"the reranker is unavailable: {exc}"}


@server.tool()
def find_lenses_batch(
    intents: list[str],
    limit: int = 6,
    kind: str | None = None,
    stack: str | None = None,
) -> dict[str, Any]:
    """Run find_lenses once per need, in one call — for a whole milestone or slice.

    Designing a milestone brief or a slice spec usually surfaces several
    distinct needs at once, not one. State each separately and need-only:
    "I need guidance on retry behaviour for a flaky upstream" and "I need
    guidance on where business rules should live relative to the HTTP
    layer" are two needs, not one, and neither should carry the project or
    framework it's being asked for — see find_lenses for why that costs
    more than it seems to.

    `results` is a list in the same order as `intents`, each shaped exactly
    like a single find_lenses response (`intent`, `reranked`, `results`).
    `limit`, `kind` and `stack` apply to every entry.
    """
    try:
        config, corpus = startup()
    except (ConfigError, SearchError) as exc:
        return {"error": str(exc)}
    if not intents:
        return {"results": []}
    try:
        return {"results": [_find_one(i, config, corpus, limit, kind, stack) for i in intents]}
    except EmbedError as exc:
        return {"error": f"the embedding endpoint is unreachable or misconfigured: {exc}"}
    except RerankError as exc:
        return {"error": f"the reranker is unavailable: {exc}"}


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
