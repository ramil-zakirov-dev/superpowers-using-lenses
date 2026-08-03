"""MCP adapter: the corpus, exposed to an agent over stdio.

Thin on purpose. Ranking lives in `search`, the second pass in `llm_rerank`,
resolution in `resolve` — this module only turns their results into tool
responses, and `second_pass` below is the one place that knows whether a
second pass is configured at all.

Every one of them takes its model as an argument rather than reaching for one:
`search.rank` takes a vector, `llm_rerank` a completer. A test swaps in a fake
and touches no network, so
arguments about relevance are settled by a test rather than by starting a
server.

    LENSES_HOME=/path/to/repo python -m lenses.mcp_server

The index is read once at startup. Re-running ingest does not reach a server
that is already running: restart the client after rebuilding the corpus.
"""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from mcp.server.mcpserver import MCPServer

from .config import Config, ConfigError, load_config
from .embed import EmbedError, embed_query
from .llm_rerank import LlmRerankError, completer_for, listwise_rank
from .resolve import resolve_all
from .search import Corpus, Hit, SearchError, load_index, rank
from .taxonomy import Taxonomy, classify, load_taxonomy

HOME = Path(os.environ.get("LENSES_HOME", "")).expanduser() or Path.cwd()

#: Candidates handed to the second pass before it is cut down to `limit`. A
#: bigger, loosely-capped pool gives it real breadth to judge — pre-filtering
#: down to `limit` with the cosine pass first would just reproduce the
#: bi-encoder's mistakes one stage later.
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
_taxonomy: Taxonomy | None = None


def startup() -> tuple[Config, Corpus]:
    """Load configuration and index once, failing loudly if either is absent.

    A configured ranking endpoint is probed here, once per process. The reason
    is that `_find_one` degrades to the dense ordering when that endpoint
    fails, and a degradation that also covered typos would make its `warning`
    mean two unrelated things. Probing at launch leaves it meaning exactly one:
    an endpoint that was working has stopped.
    """
    global _config, _corpus, _taxonomy
    if _config is None or _corpus is None:
        config = load_config(HOME / ".env")
        # Read at launch, and a hard failure: it is committed beside the
        # catalogue it describes, and a search that cannot say which subject
        # areas exist cannot say a need falls outside them either.
        taxonomy = load_taxonomy(HOME / "catalog" / "taxonomy.yaml")
        # The width is checked against the configured embedder here, at launch,
        # rather than being discovered as bad answers later: a query and an
        # index built by different models score against each other silently.
        corpus = Corpus(
            load_index(HOME / "index" / "embeddings.jsonl", config.embedder_dim)
        )
        if config.reranker is not None:
            try:
                completer_for(config.reranker)("ping", "1. a\n\nTop 1:")
            except LlmRerankError as exc:
                raise ConfigError(
                    f"reranker_base_url is configured but the ranking endpoint "
                    f"did not answer: {exc}. Remove the three reranker_* "
                    f"settings to search without a second pass."
                ) from exc
        # Assigned only once every check has passed, so a failed probe leaves
        # startup retryable rather than caching a half-built state.
        _config, _corpus, _taxonomy = config, corpus, taxonomy
    return _config, _corpus


def classifier(config: Config) -> Callable[[str], str | None] | None:
    """Decides which subject area a need belongs to, or `None` for none of them.

    Runs on the ranking endpoint, so a caller who configured that has this too
    and a caller who did not gets neither. That is a real consequence and is
    documented rather than worked around: without the endpoint the catalogue
    stops reporting its own edges, which is the strongest argument for
    configuring it.
    """
    if config.classifier is None or _taxonomy is None:
        return None
    complete = completer_for(config.classifier)
    return lambda intent: classify(intent, _taxonomy, complete)


def second_pass(config: Config) -> Callable[[str, list[Hit], int], list[Hit]] | None:
    """The configured way of cutting the candidate pool down to the answer.

    `None` means none is configured, which is a supported answer and not a
    failure: the dense ordering is then what `_find_one` returns, and it says
    so in `ranked_by`.
    """
    if config.reranker is None:
        return None
    complete = completer_for(config.reranker)
    return lambda intent, hits, limit: listwise_rank(intent, hits, limit, complete)


def _dense_answer(
    vector: list[float], corpus: Corpus, limit: int,
    kind: str | None, stack: str | None,
) -> list[Hit]:
    """The answer when no second pass ordered it.

    Deliberately not `candidates[:limit]`. The pool is built with
    `per_skill=CANDIDATE_PER_SKILL` (4) to give the ranker breadth, while
    `rank`'s own default is 2, so the pool's head is a different list — one
    that can carry four parts of one skill where the dense answer carries two.
    The 60/68 baseline in the README was measured with `rank(limit=n)` and its
    default, and this is the call that reproduces it.
    """
    return rank(vector, corpus.parts, limit=limit, kind=kind, stack=stack)


def _coverage(intent: str, config: Config) -> tuple[str | None, str | None]:
    """Which subject area this need belongs to, and a warning if none does.

    Never raises. The signal is an addition to a search that worked before it
    existed, so an endpoint that falls over here costs the caller the signal
    and nothing else — and an unreadable reply is not read as abstention,
    because a model that answered nothing has made no claim about the corpus.
    """
    decide = classifier(config)
    if decide is None:
        return None, None
    try:
        subject = decide(intent)
    except LlmRerankError:
        return None, None
    if subject is None:
        return None, (
            "this catalogue does not cover the need as stated — its subject "
            "areas are in catalog/taxonomy.yaml, and the results below are "
            "the nearest text it holds, not an answer to the question"
        )
    return (subject or None), None


def _response(
    intent: str, ranked_by: str, hits: list[Hit],
    dense_score: dict[str, float], warning: str | None = None,
    subject: str | None = None,
) -> dict[str, Any]:
    answer: dict[str, Any] = {
        "intent": intent,
        "ranked_by": ranked_by,
        #: Which shelf was searched, `null` when nothing decided. Reported,
        #: never filtered on: the model behind it showed a register bias
        #: elsewhere in this project, and a wrong label you can see costs less
        #: than a wrong label that narrowed the search.
        "subject": subject,
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
                # Cosine against the query, NOT the ordering key when a second
                # pass ran. It will not descend down the list, and that is the
                # point: six results all near 0.55 is a corpus with nothing to
                # say, which an ordering alone always hides.
                "dense_score": round(dense_score[hit.part.ref], 4),
            }
            for hit in hits
        ],
    }
    if warning is not None:
        answer["warning"] = warning
    return answer


def _find_one(
    intent: str,
    config: Config,
    corpus: Corpus,
    limit: int,
    kind: str | None,
    stack: str | None,
) -> dict[str, Any]:
    """One need, searched and ordered. Raises EmbedError and nothing else.

    A ranking failure is not an error here. The dense pool is computed and paid
    for before the second pass runs, so erasing it to report that the ordering
    was unavailable costs the caller everything to tell them about the
    difference between 65/68 and 60/68. `ranked_by` says who answered and
    `warning` says why it was not the other one.
    """
    # The coverage question depends on the intent alone, so it does not have to
    # wait behind the embedding and the ranking call that do. Measured against
    # the local endpoint: two calls take 5.33s in sequence and 2.50s together,
    # and embedding overlaps just as well, which is what keeps this signal from
    # costing the caller its own 2.2s on every search.
    with ThreadPoolExecutor(max_workers=1) as pool:
        coverage = pool.submit(_coverage, intent, config)
        vector = embed_query(config.embedder, intent, config.embedder_dim)
        ranker = second_pass(config)

        if ranker is None:
            hits = _dense_answer(vector, corpus, limit, kind, stack)
            subject, uncovered = coverage.result()
            return _response(intent, "dense", hits,
                             {hit.part.ref: hit.score for hit in hits},
                             warning=uncovered, subject=subject)

        candidates = rank(
            vector, corpus.parts,
            limit=max(CANDIDATE_POOL, limit), per_skill=CANDIDATE_PER_SKILL,
            kind=kind, stack=stack,
        )
        dense_score = {hit.part.ref: hit.score for hit in candidates}
        try:
            hits = ranker(intent, candidates, limit)
        except LlmRerankError as exc:
            fallback = _dense_answer(vector, corpus, limit, kind, stack)
            # Two independent things can go wrong in one call — the ordering,
            # and whether the corpus holds the subject at all — and a caller is
            # owed both rather than whichever happened to be checked last.
            degraded = (f"the ranking pass was unavailable, so these are the "
                        f"dense results: {exc}")
            subject, uncovered = coverage.result()
            return _response(
                intent, "dense", fallback,
                {hit.part.ref: hit.score for hit in fallback},
                warning=" ".join(n for n in (uncovered, degraded) if n),
                subject=subject,
            )
        subject, uncovered = coverage.result()
        return _response(intent, "llm", hits, dense_score,
                         warning=uncovered, subject=subject)


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
    way. Measured on 34 paired needs, the listwise second pass absorbs
    project vocabulary almost completely — 33 of 34, against 32 of 34 for
    need-only phrasing — where the dense ordering alone manages 27 of 34.
    Nothing downstream rescues that difference; narrowing by `stack` first
    was tried and changed nothing.

    `ranked_by` says who answered: `"llm"` if that pass ran, `"dense"` if it
    is not configured or was unavailable. In the second case a `warning` is
    present saying so, and the results are still the dense ones rather than
    nothing — worth reading before concluding the corpus is thin.

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
