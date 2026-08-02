"""Retrieval quality: realistic design-time queries against the live corpus.

Not a pytest test — it calls the configured embedding endpoint for real, so
it is slower than the suite and depends on that endpoint being up. Run it by
hand after touching the corpus, the embedder config, or `search.rank`:

    python scripts/eval_retrieval.py

Each case is a moment an agent mid-design would actually stop and call
find_lenses, and carries the same need in two registers:

`intent`   — the need alone, phrased the way find_lenses asks for it.
`concrete` — the same need as a caller with a real project in front of them
             writes it, carrying that project's proper nouns.

Both matter, and only one of them occurs in production. An eval written
solely in the first register grades the corpus against queries drawn from
the corpus's own vocabulary, and will report health it has not measured:
this suite passed 17/17 on `intent` while `concrete` lost six of the same
seventeen outright. That gap is the finding, not a footnote to it.

`expect_any` is a loose, human-reviewable signal (a substring of a
`skill_id` or `part_id` known to be in the corpus), not a pinned ref: the
corpus grows and "best answer" is often a judgement call. The printed top-6
is the actual verdict; pass/fail is only a regression trip-wire.

Only the `intent` axis sets the exit code. `concrete` is reported and not
gated on deliberately — it is failing now, and a gate that is red on arrival
is one everybody learns to pass without reading, which is how it comes to be
absent on the day it would have caught something.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from lenses.config import load_config  # noqa: E402
from lenses.embed import embed_query  # noqa: E402
from lenses.mcp_server import second_pass  # noqa: E402
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
    concrete: str
    expect_any: tuple[str, ...]


CASES = [
    # Implementation-time needs: a slice is being built and something in the
    # code has to be decided.
    Case(
        scenario="Calling a third-party payment API from the request path",
        intent="an external call in the request path can hang or be down "
        "and must not take the whole service with it",
        concrete="keeping a call to an external Stripe payment API from "
        "hanging and taking the whole checkout service down",
        expect_any=("stability", "circuit", "timeout"),
    ),
    Case(
        scenario="Structuring a new FastAPI service",
        intent="where business rules should live so they don't get tangled "
        "with the HTTP framework",
        concrete="where the pricing rules should live in our new FastAPI "
        "billing service so they don't get tangled with the HTTP routes",
        expect_any=("hexagonal-architecture", "clean-architecture"),
    ),
    Case(
        scenario="Writing tests for code that hits Postgres and an email API",
        intent="tests over-mock internal logic and stop meaning anything",
        concrete="our pytest suite mocks the Postgres repository and the "
        "SendGrid client so heavily the tests stopped meaning anything",
        expect_any=("mock-boundaries", "mocking"),
    ),
    Case(
        scenario="Reviewing a PR that catches Exception broadly and logs a generic message",
        intent="a function swallows exceptions with a broad catch and a "
        "generic log message",
        concrete="a Django view swallows exceptions with a broad except and "
        "logs 'something went wrong'",
        expect_any=("silent-exceptions", "generic-except"),
    ),
    Case(
        scenario="Designing a new public API endpoint",
        intent="deciding resource shape, versioning and pagination for a "
        "new REST endpoint",
        concrete="deciding the resource shape, versioning and pagination for "
        "a new /v1/invoices REST endpoint in our billing API",
        expect_any=("api-design",),
    ),
    Case(
        scenario="Bootstrapping a brand-new Python service repo",
        intent="which linter, type checker and formatter to wire into a "
        "new python project's CI",
        concrete="which linter, type checker and formatter to wire into the "
        "GitHub Actions CI of our new Python microservice",
        expect_any=("ludo/tooling",),
    ),
    Case(
        scenario="A React dashboard component re-renders on every keystroke",
        intent="a react component re-renders too often because of an "
        "unrelated state change",
        concrete="our React analytics dashboard re-renders the whole chart "
        "grid on every keystroke in the filter input",
        expect_any=("react-performance",),
    ),
    Case(
        scenario="Recording why the team chose Postgres over DynamoDB",
        intent="capturing the reasoning behind an architecture decision so "
        "the team remembers it in a year",
        concrete="capturing why we picked Postgres over DynamoDB for the "
        "events store so the team remembers it in a year",
        expect_any=("architecture-decision-records",),
    ),

    # Design-time needs: nothing is being written yet. A milestone brief or a
    # slice spec is being argued about, and the question is what to build and
    # where the expensive-to-reverse lines fall. These queries cover the half
    # of the corpus the cases above never reach — an engineering-only eval
    # cannot tell whether a product or architecture lens is retrievable at all.
    Case(
        scenario="A milestone brief that lists targets and calls them a strategy",
        intent="a plan names where we want to end up but never says what is "
        "actually in the way",
        concrete="our Q3 milestone brief lists OKR targets for the payments "
        "platform but never says what is actually in the way",
        expect_any=("good-strategy-bad-strategy",),
    ),
    Case(
        scenario="A slice that keeps growing past the time it was worth",
        intent="deciding how much work one delivery cycle is worth before "
        "committing to it, and cutting to fit rather than slipping",
        concrete="the checkout redesign slice keeps growing past the sprint "
        "it was worth and we need to cut scope rather than slip",
        expect_any=("37signals-way",),
    ),
    Case(
        scenario="An objective everyone agrees with and nobody can test",
        intent="turning a vague objective into something that can be proven "
        "wrong before the team commits to building it",
        concrete="turning 'improve onboarding conversion' into something we "
        "can prove wrong before the team builds it",
        expect_any=("continuous-discovery", "lean-startup"),
    ),
    Case(
        scenario="A feature requested by name, with no stated problem behind it",
        intent="understanding what progress a customer is trying to make, "
        "rather than which feature they asked for",
        concrete="a customer asked us for a CSV export button and we don't "
        "know what progress they are actually trying to make",
        expect_any=("jobs-to-be-done", "inspired-product"),
    ),
    Case(
        scenario="Two teams keep blocking each other on the same subsystem",
        intent="deciding which team owns which part of the system so changes "
        "stop needing three teams to agree",
        concrete="the payments team and the platform team keep blocking each "
        "other on the same billing subsystem",
        expect_any=("team-topologies",),
    ),
    Case(
        scenario="A service whose data has to be readable from two regions",
        intent="choosing how data is replicated and what consistency callers "
        "can rely on when it is spread across regions",
        concrete="choosing replication and consistency for our Postgres order "
        "data that has to be readable from eu-west and us-east",
        expect_any=("ddia-systems", "system-design"),
    ),
    Case(
        scenario="A module whose interface is as complicated as its insides",
        intent="judging whether an interface hides enough complexity to be "
        "worth its own existence",
        concrete="judging whether our NotificationDispatcher class hides "
        "enough complexity to be worth existing",
        expect_any=("software-design-philosophy",),
    ),
    Case(
        scenario="Proving the whole path works before filling in any of it",
        intent="reaching end to end through every layer with something thin "
        "and real, rather than finishing one layer at a time",
        concrete="getting one request end to end through the React app, the "
        "FastAPI gateway and Postgres before filling in any of the layers",
        expect_any=("pragmatic-programmer",),
    ),
    Case(
        scenario="A plan that starts with tests for code that has none",
        intent="establishing what untested code currently does before "
        "changing it, when its dependencies resist being replaced",
        concrete="establishing what our untested legacy PaymentProcessor "
        "actually does before we change it, when it hard-codes its own "
        "DB session",
        expect_any=("working-with-legacy-code",),
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


def pipeline(intent: str, parts, config):
    """What find_lenses does, in one place, so both axes are scored alike.

    The second pass comes from the configuration, not from a literal here: an
    eval that grades a different ranker from the one the server runs measures
    something nobody ships.
    """
    vector = embed_query(config.embedder, intent, config.embedder_dim)
    dense_hits = rank(vector, parts, limit=FINAL_LIMIT)
    candidates = rank(vector, parts, limit=CANDIDATE_POOL, per_skill=CANDIDATE_PER_SKILL)
    return dense_hits, second_pass(config)(intent, candidates, FINAL_LIMIT)


def main() -> int:
    config = load_config(REPO / ".env")
    parts = load_index(REPO / "index" / "embeddings.jsonl", config.embedder_dim)
    print(f"corpus: {len(parts)} parts")
    print(f"second pass: {config.reranker_kind} — {config.reranker_model}\n")

    dense_failures = ranked_failures = concrete_failures = 0
    lost_to_phrasing = []
    for case in CASES:
        dense_hits, ranked_hits = pipeline(case.intent, parts, config)

        print(f"=== {case.scenario} ===")
        print(f"    intent: {case.intent!r}")
        dense_failures += 0 if show("dense   ", case, dense_hits) else 1
        ranked_failures += 0 if show("ranked  ", case, ranked_hits) else 1

        # The same need in the caller's register. Reported compactly: what it
        # is here to answer is whether the need survives being written the way
        # it will actually be written, not to re-print six rows that agree.
        _, concrete_hits = pipeline(case.concrete, parts, config)
        print(f"    concrete: {case.concrete!r}")
        if matched(case, concrete_hits):
            print("  [OK  ] concrete")
        else:
            concrete_failures += 1
            lost_to_phrasing.append(case.scenario)
            print("  [MISS] concrete — displaced by:")
            for hit in concrete_hits[:3]:
                print(f"          {hit.score:8.4f}  {hit.part.ref}  — {hit.part.title}")
        print()

    total = len(CASES)
    print(f"done: dense {total - dense_failures}/{total}, "
          f"ranked {total - ranked_failures}/{total} matched a loose expectation")
    print(f"concrete phrasing: {total - concrete_failures}/{total} — the same needs "
          f"carrying their project's proper nouns")
    for scenario in lost_to_phrasing:
        print(f"  lost: {scenario}")
    print(f"total across both axes: "
          f"{2 * total - ranked_failures - concrete_failures}/{2 * total}")
    # Only the need axis gates. See the module docstring for why a red-on-
    # arrival gate is worse than a reported number.
    return 1 if ranked_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
