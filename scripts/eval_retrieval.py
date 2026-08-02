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
at seventeen cases this suite passed 17/17 on `intent` while `concrete`
lost six of the same seventeen outright. That gap is the finding, not a
footnote to it.

Thirty-four cases, not seventeen, and the second seventeen are why. At n=17
every case was answerable by a part tied to no technology, and every
targeted skill was one of eighteen — the other twenty-three of forty-one
were unreachable by any expectation here, so the suite could report health
for a corpus it had never queried half of. The cases added since cover
those, and roughly a third of them are stack-specific on purpose: the
server does not make the caller pass `stack`, so whether a stack-tagged
part surfaces from prose alone is a question worth failing at.

Growing it paid immediately, and not in the direction expected. Measured
2026-08-03 — dense 33/34, ranked 31/34, `concrete` 32/34, 63/68 across both
axes — the second pass is now *behind* the dense pass it is supposed to
improve, and it is behind deterministically (`temperature` is 0). On
`tests over-mock internal logic and stop meaning anything` it discards
`ludo/testing#mock-boundaries` — dense rank 1, margin +0.14 over the runner
up, `applies_to` reading "Over-mocked tests pass while production breaks" —
and answers `4,5,17,18,19,20`, taking the last four entries of the pool in
order. Three of thirty-four answers end in such a run. That failure mode
existed at n=17 and n=17 could not see it.

The `intent` gate is therefore red as of this writing, and is being left
red. The reasoning below about red-on-arrival gates is about a gate nobody
can fix; this one is red because the ranker is wrong, which is what a gate
is for.

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
    Case(
        scenario="Comments in a module describe the code instead of the reasoning",
        intent="comments explain what the code does rather than why, and have "
        "drifted from what it now does",
        concrete="the comments in our pricing module explain what each line "
        "does rather than why, and they no longer match the code",
        expect_any=("clean-code",),
    ),
    Case(
        scenario="A conditional that has accumulated branches over two years",
        intent="restructuring a conditional that has grown branches, in steps "
        "small enough that the tests stay green throughout",
        concrete="restructuring our eight-branch discount conditional in steps "
        "small enough that the pytest suite stays green throughout",
        expect_any=("refactoring",),
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
    Case(
        scenario="Two services that use the same noun to mean different things",
        intent="one word means different things to two parts of the system and "
        "their models keep leaking into each other",
        concrete="'subscription' means different things to our billing service "
        "and our provisioning service and the models keep leaking into each "
        "other",
        expect_any=("domain-driven-design",),
    ),
    Case(
        scenario="A control whose users expect it to do something else",
        intent="people form the wrong idea of what a control will do and "
        "nothing about it signals otherwise",
        concrete="people think our Sync button uploads their local changes "
        "when it actually overwrites them, and nothing about the button says "
        "so",
        expect_any=("design-everyday-things",),
    ),
    Case(
        scenario="A screen everyone dislikes and nobody can say why",
        intent="grading an existing screen against known usability criteria "
        "and ranking which problems are worth fixing first",
        concrete="grading our account settings screen against known usability "
        "criteria and ranking which problems to fix before the release",
        expect_any=("ux-heuristics",),
    ),

    # Stack-specific needs. Every case above is answerable by a part that is
    # not tied to a technology; these are not. They are here because the
    # server does not require the caller to pass `stack` — the need arrives
    # in prose and the technology has to be inferred from it. Whether a
    # stack-tagged part surfaces on an untagged query is a different question
    # from whether a lens does, and the eval could not ask it before.
    Case(
        scenario="A custom widget that works with a mouse and nothing else",
        intent="a custom control can be operated with a pointer but not with a "
        "keyboard, and is not announced to assistive technology",
        concrete="our custom React combobox in the booking form works with a "
        "mouse but keyboard and screen-reader users cannot operate it",
        expect_any=("accessibility",),
    ),
    Case(
        scenario="Callers string-matching on an error message to decide what to do",
        intent="deciding what an error should carry so a caller further up can "
        "act on it instead of re-reading its message",
        concrete="deciding what our OrderError should carry so the FastAPI "
        "handler can act on it instead of string-matching the message",
        expect_any=("ecc/error-handling",),
    ),
    Case(
        scenario="Request-scoped objects reached through module globals",
        intent="giving each request its own database session and settings in "
        "an async python web service without module-level globals",
        concrete="giving each FastAPI request its own SQLAlchemy session and "
        "settings without module-level globals",
        expect_any=("fastapi",),
    ),
    Case(
        scenario="Designing the tools an agent will call",
        intent="shaping the tools a server exposes to a model so it can pick "
        "the right one and call it correctly without guessing",
        concrete="shaping the tools our internal MCP server exposes so Claude "
        "picks the right one and calls it correctly without guessing",
        expect_any=("mcp-server",),
    ),
    Case(
        scenario="A listing query that degraded as the table grew",
        intent="a query slowed down as its table grew and which index it needs "
        "is not obvious from the query alone",
        concrete="our orders listing query slowed down as the Postgres table "
        "passed twenty million rows and we cannot tell which index it needs",
        expect_any=("postgres",),
    ),
    Case(
        scenario="A schema change on a table that is being written to",
        intent="changing a column on a large table without holding a lock that "
        "blocks writes for the length of the deploy",
        concrete="adding a NOT NULL column to our forty-million-row Postgres "
        "payments table without blocking writes during the deploy",
        expect_any=("postgres", "alembic"),
    ),
    Case(
        scenario="An ORM migration that behaved differently in production",
        intent="a schema migration run by the ORM's migration tool did "
        "something different against production than it did locally",
        concrete="our Alembic migration did something different against "
        "production Postgres than it did against the local SQLAlchemy setup",
        expect_any=("sqlalchemy", "alembic"),
    ),
    Case(
        scenario="A payload passed around as nested dictionaries",
        intent="a structure passed between functions as nested dictionaries "
        "has become impossible to reason about or type",
        concrete="the record our ETL job passes between stages as nested dicts "
        "has become impossible to reason about or type",
        expect_any=("python-patterns", "python-expert"),
    ),
    Case(
        scenario="A slow dev server and a bundle that ships too much",
        intent="the development server reloads slowly and the production "
        "bundle ships far more than the page uses",
        concrete="our Vite dev server reloads slowly and the production bundle "
        "ships the entire icon library for three icons",
        expect_any=("vite",),
    ),
    Case(
        scenario="Pulling fields out of text a parser handles only mostly",
        intent="extracting fields from semi-structured text where a "
        "deterministic parser covers most inputs and the rest are messy",
        concrete="extracting amounts and dates from supplier invoice text "
        "where a regex covers most files and the rest are messy",
        expect_any=("regex",),
    ),
    Case(
        scenario="A nested query issuing one database call per row",
        intent="a nested query fans out into one database call per item in the "
        "list above it",
        concrete="our GraphQL orders query fans out into one Postgres call per "
        "line item",
        expect_any=("graphql",),
    ),
    Case(
        scenario="Ownership fights with the compiler settled by copying",
        intent="fights with the compiler over ownership are being settled by "
        "copying data everywhere and the habit is spreading",
        concrete="our Rust ingestion service settles every borrow-checker "
        "fight with a .clone() and the habit is spreading",
        expect_any=("rust",),
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
