"""Retrieval quality: realistic design-time queries against the live corpus.

Not a pytest test — it calls the configured embedding endpoint for real, so
it is slower than the suite and depends on that endpoint being up. Run it by
hand after touching the corpus, the embedder config, or `search.rank`:

    python scripts/eval_retrieval.py

Each case is a moment an agent mid-design would actually stop and call
find_lenses, phrased as a need rather than a solution — the same convention
the tool itself documents. `expect_any` is a loose, human-reviewable signal
(a substring of a `skill_id` or `part_id` known to be in the corpus), not a
pinned ref: the corpus grows and "best answer" is often a judgement call. The
printed top-6 is the actual verdict; pass/fail is only a regression trip-wire.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from lenses.config import load_config  # noqa: E402
from lenses.embed import embed_query  # noqa: E402
from lenses.rerank import confident, rerank  # noqa: E402
from lenses.search import load_index, rank  # noqa: E402

#: Mirrors mcp_server.CANDIDATE_POOL / CANDIDATE_PER_SKILL — kept as literals
#: here rather than imported, so this eval reflects what find_lenses actually
#: does without importing the MCP server module (and its stdio machinery)
#: just to read two constants.
CANDIDATE_POOL = 20
CANDIDATE_PER_SKILL = 4
FINAL_LIMIT = 6


@dataclass(frozen=True)
class Case:
    scenario: str
    intent: str
    expect_any: tuple[str, ...]


CASES = [
    Case(
        scenario="Calling a third-party payment API from the request path",
        intent="an external call in the request path can hang or be down "
        "and must not take the whole service with it",
        expect_any=("stability", "circuit", "timeout"),
    ),
    Case(
        scenario="Structuring a new FastAPI service",
        intent="where business rules should live so they don't get tangled "
        "with the HTTP framework",
        expect_any=("hexagonal-architecture", "clean-architecture"),
    ),
    Case(
        scenario="Writing tests for code that hits Postgres and an email API",
        intent="tests over-mock internal logic and stop meaning anything",
        expect_any=("mock-boundaries", "mocking"),
    ),
    Case(
        scenario="Reviewing a PR that catches Exception broadly and logs a generic message",
        intent="a function swallows exceptions with a broad catch and a "
        "generic log message",
        expect_any=("silent-exceptions", "generic-except"),
    ),
    Case(
        scenario="Designing a new public API endpoint",
        intent="deciding resource shape, versioning and pagination for a "
        "new REST endpoint",
        expect_any=("api-design",),
    ),
    Case(
        scenario="Bootstrapping a brand-new Python service repo",
        intent="which linter, type checker and formatter to wire into a "
        "new python project's CI",
        expect_any=("ludo/tooling",),
    ),
    Case(
        scenario="A React dashboard component re-renders on every keystroke",
        intent="a react component re-renders too often because of an "
        "unrelated state change",
        expect_any=("react-performance",),
    ),
    Case(
        scenario="Recording why the team chose Postgres over DynamoDB",
        intent="capturing the reasoning behind an architecture decision so "
        "the team remembers it in a year",
        expect_any=("architecture-decision-records",),
    ),
]


def matched(case: Case, hits) -> bool:
    refs = [hit.part.ref for hit in hits]
    return any(needle in ref for needle in case.expect_any for ref in refs)


def show(label: str, case: Case, hits) -> bool:
    ok = matched(case, hits)
    print(f"  [{'OK  ' if ok else 'MISS'}] {label}")
    for hit in hits:
        print(f"          {hit.score:8.4f}  {hit.part.ref}  — {hit.part.title}")
    return ok


def main() -> int:
    config = load_config(REPO / ".env")
    parts = load_index(REPO / "index" / "embeddings.jsonl")
    print(f"corpus: {len(parts)} parts\n")

    dense_failures = reranked_failures = gated_failures = 0
    gate_fell_back = 0
    for case in CASES:
        vector = embed_query(config.embedder, case.intent, config.embedder_dim)

        dense_hits = rank(vector, parts, limit=FINAL_LIMIT)
        candidates = rank(vector, parts, limit=CANDIDATE_POOL, per_skill=CANDIDATE_PER_SKILL)
        reranked_hits = rerank(case.intent, candidates, top_n=FINAL_LIMIT)
        trust_rerank = confident(reranked_hits)
        gated_hits = reranked_hits if trust_rerank else dense_hits
        gate_fell_back += 0 if trust_rerank else 1

        print(f"=== {case.scenario} ===")
        print(f"    intent: {case.intent!r}")
        dense_failures += 0 if show("dense   ", case, dense_hits) else 1
        reranked_failures += 0 if show("reranked", case, reranked_hits) else 1
        label = f"gated   (trusted reranked)" if trust_rerank else f"gated   (fell back to dense)"
        gated_failures += 0 if show(label, case, gated_hits) else 1
        print()

    total = len(CASES)
    print(f"done: dense {total - dense_failures}/{total}, "
          f"reranked {total - reranked_failures}/{total}, "
          f"gated {total - gated_failures}/{total} matched a loose expectation "
          f"({gate_fell_back}/{total} cases fell back to dense)")
    return 1 if gated_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
