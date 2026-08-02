"""MCP adapter: the corpus, exposed to an agent over stdio.

Thin on purpose. Ranking lives in `search`, the second pass in `rerank` or
`llm_rerank`, resolution in `resolve` — this module only turns their results
into tool responses, and `second_pass` below is the one place that knows which
of the two is configured.

Every one of them takes its model as an argument rather than reaching for one:
`search.rank` takes a vector, `rerank.rerank` a scorer, `llm_rerank` a
completer. A test swaps in a fake and touches neither torch nor a network, so
arguments about relevance are settled by a test rather than by starting a
server.

    LENSES_HOME=/path/to/repo python -m lenses.mcp_server

The index is read once at startup. Re-running ingest does not reach a server
that is already running: restart the client after rebuilding the corpus.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Callable

from mcp.server.mcpserver import MCPServer

from .config import Config, ConfigError, load_config
from .embed import EmbedError, embed_query
from .llm_rerank import LlmRerankError, completer_for, listwise_rank
from .rerank import RerankError, rerank, scorer_for
from .resolve import resolve_all
from .search import Corpus, Hit, SearchError, load_index, rank

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
        # The width is checked against the configured embedder here, at launch,
        # rather than being discovered as bad answers later: a query and an
        # index built by different models score against each other silently.
        _corpus = Corpus(
            load_index(HOME / "index" / "embeddings.jsonl", _config.embedder_dim)
        )
    return _config, _corpus


def second_pass(config: Config) -> Callable[[str, list[Hit], int], list[Hit]]:
    """The configured way of cutting the candidate pool down to the answer.

    One signature for both, so `_find_one` holds no branch: they disagree
    about what a score means, not about what ranking is.
    """
    if config.reranker_kind == "llm":
        complete = completer_for(config.reranker)
        return lambda intent, hits, limit: listwise_rank(intent, hits, limit, complete)
    scorer = scorer_for(config.reranker_model)
    return lambda intent, hits, limit: rerank(intent, hits, top_n=limit, score=scorer)


def _find_one(
    intent: str,
    config: Config,
    corpus: Corpus,
    limit: int,
    kind: str | None,
    stack: str | None,
) -> dict[str, Any]:
    """One need, searched and reordered. Raises EmbedError, RerankError or
    LlmRerankError."""
    vector = embed_query(config.embedder, intent, config.embedder_dim)
    candidates = rank(
        vector, corpus.parts,
        limit=max(CANDIDATE_POOL, limit), per_skill=CANDIDATE_PER_SKILL,
        kind=kind, stack=stack,
    )
    # Kept before the second pass reorders, because that pass may return the
    # dense score unchanged (llm) or replace it with its own logit
    # (cross-encoder), and the caller is owed the one that means something.
    dense_score = {hit.part.ref: hit.score for hit in candidates}
    hits = second_pass(config)(intent, candidates, limit)
    return {
        "intent": intent,
        "ranked_by": config.reranker_kind,
        "results": [
            {
                "ref": hit.part.ref,
                "title": hit.part.title,
                "applies_to": hit.part.applies_to,
                "kind": hit.part.kind,
                "tags": list(hit.part.tags),
                # Named, not followed. `get_lenses` on this ref returns these
                # too; seeing them here is what makes that predictable.
                "requires": list(hit.part.requires),
                # Cosine against the query, NOT the ordering key — the second
                # pass decided that. It will not descend down the list, and
                # that is the point: six results all near 0.55 is a corpus
                # with nothing to say, which an ordering alone always hides.
                "dense_score": round(dense_score[hit.part.ref], 4),
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

    State the need itself, stripped of the project it arose in:

        best:  "an external call in the request path can hang or be down
                and must not take the whole service with it"
        risky: "keeping a call to an external Stripe payment API from
                hanging and taking the whole checkout service down"

    Same need. The proper nouns in the second — "Stripe", "checkout",
    "API" — pull the query toward parts that merely share that vocabulary,
    because `applies_to` is written in the register of moments, not of
    technologies.

    How much that costs depends on how this server is configured, which is
    why the first form is worth the habit: it is the one that works either
    way. Measured on seventeen paired needs, the `llm` second pass absorbs
    project vocabulary almost completely (16 of 17, against 16 of 17 for
    need-only phrasing); the `cross-encoder` pass does not (14 of 17), and
    nothing downstream rescues the difference — narrowing by `stack` first
    was tried and changed nothing. `ranked_by` in the response says which
    one answered you.

    Know why the need matters — you want that for the record you leave in
    `lenses:` — but keep the why out of the query.

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
    except (RerankError, LlmRerankError) as exc:
        return {"error": f"the second ranking pass is unavailable: {exc}"}


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
    like a single find_lenses response (`intent`, `ranked_by`, `results`).
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
    except (RerankError, LlmRerankError) as exc:
        return {"error": f"the second ranking pass is unavailable: {exc}"}


@server.tool()
def get_lenses(refs: list[str]) -> dict[str, Any]:
    """Read the parts named by `label/name#part@version` references.

    Each part is verbatim upstream text, verified against the hash recorded
    when it was catalogued. A reference whose text has changed is reported as
    an error rather than returned: a citation that resolves to different text
    is worse than one that fails, because nobody notices it.

    A part whose decomposition recorded that it cannot stand alone arrives with
    what it needs. Those extra parts are in the same `parts` list, each naming
    the reference that pulled it in under `required_by`; a part you asked for
    has an empty `required_by`, and that is the distinction to cite from —
    `lenses:` should record what you chose, not what came along with it.

    Nothing is dropped in silence. A requirement that will not resolve, and a
    request whose requirements outgrow the per-reference ceiling, are named in
    `errors` while everything that did resolve is still returned.
    """
    try:
        startup()
    except (ConfigError, SearchError) as exc:
        return {"error": str(exc)}

    found, errors = resolve_all(refs, HOME / "catalog", HOME / "skills")
    return {
        "parts": [
            {
                "ref": part.ref,
                "title": part.title,
                "applies_to": part.applies_to,
                "kind": part.kind,
                "tags": list(part.tags),
                "requires": list(part.requires),
                "required_by": list(part.required_by),
                "license": part.license,
                "source": part.url or part.file,
                "text": part.text,
            }
            for part in found
        ],
        "errors": errors,
    }


@server.tool()
def list_skills() -> dict[str, Any]:
    """What the corpus holds: every skill, its parts, kinds and document kinds.

    Read it *before* writing the needs you will search with, not after a search
    comes back thin. `coverage` counts the skills bearing on a milestone brief,
    a slice spec and a plan; a stage the corpus barely covers is a stage whose
    needs you will have to source elsewhere, and the only way to know that is
    to look. `document_kinds` is reported, never filtered on — it shapes the
    questions worth asking, not the ranking of the answers.
    """
    try:
        _, corpus = startup()
    except (ConfigError, SearchError) as exc:
        return {"error": str(exc)}

    skills = []
    coverage: dict[str, int] = {}
    unclassified = 0
    for skill_id, parts in sorted(corpus.skills.items()):
        kinds: dict[str, int] = {}
        for part in parts:
            kinds[part.kind] = kinds.get(part.kind, 0) + 1
        document_kinds = sorted({dk for part in parts for dk in part.document_kinds})
        for document_kind in document_kinds:
            coverage[document_kind] = coverage.get(document_kind, 0) + 1
        unclassified += 0 if document_kinds else 1
        skills.append(
            {
                "skill_id": skill_id,
                "version": parts[0].version,
                "parts": len(parts),
                "kinds": kinds,
                "document_kinds": document_kinds,
                "stacks": sorted({stack for part in parts for stack in part.stacks}),
            }
        )
    return {
        "home": str(HOME),
        "skills": skills,
        "total_parts": len(corpus.parts),
        # Skills per document kind, plus the ones nobody has classified —
        # reported rather than folded into the counts, because "unknown" read
        # as "covers everything" is how a gap stops being visible.
        "coverage": {**coverage, "unclassified": unclassified},
    }


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
