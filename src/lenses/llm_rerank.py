"""Second pass by an instruction-tuned model, shown the whole pool at once.

This is the only second pass. It is optional: with no endpoint configured the
dense ordering is the answer, and on 34 paired needs that scores 60/68 against
this pass's **65/68** — five cases, all of them on the axis that occurs in
production.

Why a model at all. Queries arrive carrying a project's proper nouns — Stripe,
the checkout service, our React dashboard — while `applies_to` is written in
the register of moments. Anything that compares two strings lets vocabulary
overlap decide, and the right part loses to whatever shares nouns with the
query. An LLM reads past that: the need beneath "keeping a Stripe call from
hanging" is the need a resilience part states. A cross-encoder second pass was
tried for exactly this and retired on 2026-08-03 at 57/68 — below having no
second pass at all.

The shape matters as much as the model. Asked to score candidates one by one
with a digit, the same model scored 23 of 34 queries; shown all twenty and
asked which six are best, 32. A small model has no stable absolute scale —
"is this a 7 or an 8?" is a question it answers inconsistently — but
comparison inside a visible set needs no scale at all.

**What the numbers above do not say, and a wider eval does.** They come from
seventeen pairs. At thirty-four (2026-08-03) this pass scored 31/34 on
need-only phrasing against the dense pass's 33/34 — it was subtracting from
the ranking it was added to improve, reproducibly, since `temperature` is 0
below. Asked about tests that over-mock, it skipped the entry reading
"Over-mocked tests pass while production breaks" — dense rank 1, +0.14 clear
of the next candidate — and replied `4,5,17,18,19,20`: two picks and then the
end of the list in order.

`build_prompt` now says the entries arrive ordered best first and asks the
model to move one only where it disagrees. That is worth **31→32 and 32→33**,
total **63/68 → 65/68**, which is why it is in the prompt.

**It did not fix the case that motivated it, and that is the finding.** On
the same query the reply went from `4,5,17,18,19,20` to `4,5,17,16,18,20` —
the entry at rank 1 is still discarded. So the cause was never that the model
did not know the list was ordered.

What the six chosen entries have in common is their phrasing. Every one of
them opens "Use when …"; the one it will not pick opens with a title. That
split is not incidental — **108 of 405 parts** carry an `applies_to` that is
not in the "Use when" register, and they are exactly the parts that arrived
through `importer` rather than `decompose`, where the field is the upstream
author's frontmatter instead of the model's sentence. Every one of the 108 is
in one of eight skills. A ranker that reads `applies_to` and prefers one
register therefore has a structural blind spot over a quarter of the corpus,
and no query-side work reaches it. Normalising the imported register at
ingest is the next thing to measure; nothing here does it.
"""

from __future__ import annotations

import re
from typing import Callable

import httpx

from .config import Endpoint
from .search import Hit

#: Given a system and a user message, return the model's reply. Injectable so
#: the parsing below — which is where the failure modes live — is testable
#: without a server, a model, or a network.
Completer = Callable[[str, str], str]


class LlmRerankError(RuntimeError):
    """The ranking model was unreachable or returned something unusable."""


def build_prompt(intent: str, hits: list[Hit], top_n: int) -> tuple[str, str]:
    """The system and user messages for one ranking call.

    Kept as a function so a test can assert what the model is actually asked,
    and so the prompt is one reviewable thing rather than a string spliced
    together at the call site. It is a tuning surface with no unit test that
    can judge it: only scripts/eval_retrieval.py says whether a wording is
    better, so change it and re-run that, never just read it and agree.
    """
    system = (
        "You judge whether a catalogue entry is worth reading for a stated "
        "engineering need. Judge the underlying need, not the vocabulary: a "
        "need naming a specific product, framework or feature is still the "
        f"general need beneath it. You will see {len(hits)} numbered entries, "
        "already ordered best first by an estimate of relevance. Treat that "
        "order as the starting point: move an entry only where you disagree "
        f"with it. Reply with the {top_n} most relevant numbers, best first, "
        "comma separated. Use each number at most once. Numbers only."
    )
    catalogue = "\n".join(
        f"{index + 1}. {hit.part.applies_to}" for index, hit in enumerate(hits)
    )
    user = f"Need: {intent}\n\n{catalogue}\n\nTop {top_n}:"
    return system, user


def parse_order(answer: str, pool_size: int) -> list[int]:
    """The distinct, in-range indices the model named, in the order it named them.

    Everything here is a measured failure, not defensive habit: on 34 queries
    the model repeated a number in four of them. Dropping the duplicate is
    right — but silently returning five results for a `limit` of six is not,
    which is why the caller backfills rather than this returning short.
    """
    seen: set[int] = set()
    order: list[int] = []
    for token in re.findall(r"\d+", answer):
        index = int(token) - 1
        if 0 <= index < pool_size and index not in seen:
            seen.add(index)
            order.append(index)
    return order


def listwise_rank(
    intent: str,
    hits: list[Hit],
    top_n: int,
    complete: Completer,
) -> list[Hit]:
    """Reorder `hits` by one ranking call, and never return fewer than asked.

    The returned Hits are the ones passed in, untouched: their `score` stays
    the dense cosine that built the pool. The ordering is the model's, the
    number beside each result is not — which is deliberate, because a pool of
    uniformly poor matches is a thing the caller needs to be able to see, and
    an ordering alone always looks confident.
    """
    if top_n < 1:
        raise LlmRerankError("top_n must be at least 1")
    if not hits:
        return []

    system, user = build_prompt(intent, hits, top_n)
    order = parse_order(complete(system, user), len(hits))

    # Anything the model did not name keeps its dense position at the tail. A
    # reply that is empty or unparseable therefore degrades to the dense
    # ordering — worse, but never emptier, than what it replaced.
    chosen = list(order)
    named = set(order)
    for index in range(len(hits)):
        if len(chosen) >= top_n:
            break
        if index not in named:
            chosen.append(index)
    return [hits[index] for index in chosen[:top_n]]


def completer_for(endpoint: Endpoint, timeout: float = 5.0) -> Completer:
    """A Completer backed by an OpenAI-compatible /chat/completions endpoint.

    Five seconds is roughly twenty times the measured median for this call and
    sits on every search. The previous 120 s made a hung endpoint cost the
    caller two minutes before `_find_one` could fall back to the dense
    ordering, which is the failure a slow response causes and a refused
    connection does not.
    """

    def complete(system: str, user: str) -> str:
        try:
            response = httpx.post(
                f"{endpoint.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {endpoint.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": endpoint.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    # Enough for a comma-separated list and nothing else; a
                    # model that starts explaining is cut off rather than
                    # billed for prose no one reads.
                    "max_tokens": 60,
                    "temperature": 0.0,
                },
                timeout=timeout,
            )
        except httpx.HTTPError as exc:
            raise LlmRerankError(f"{endpoint.base_url}: {exc}") from exc
        if response.status_code >= 400:
            raise LlmRerankError(
                f"{endpoint.base_url} returned {response.status_code} for model "
                f"{endpoint.model!r}: {response.text[:500]}"
            )
        try:
            return response.json()["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, ValueError) as exc:
            raise LlmRerankError(
                f"{endpoint.model} returned no usable message: {response.text[:300]}"
            ) from exc

    return complete
