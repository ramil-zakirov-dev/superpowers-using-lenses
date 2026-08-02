"""Second pass by an instruction-tuned model, shown the whole pool at once.

A cross-encoder judges one candidate at a time, so it can only ever answer
"how well does this passage match this string". That is the wrong question
for this corpus. Queries arrive carrying a project's proper nouns — Stripe,
the checkout service, our React dashboard — while `applies_to` is written in
the register of moments. Vocabulary overlap then decides the ranking, and the
right part loses to whatever happens to share nouns with the query.

An LLM can read past that: the need beneath "keeping a Stripe call from
hanging" is the need a resilience part states. Measured on 34 paired queries,
this pass scores 16/17 on project-flavoured phrasing where the cross-encoder
scores 14/17, and matches it at 16/17 on need-only phrasing — it does not
trade one register for the other.

The shape matters as much as the model. Asked to score candidates one by one
with a digit, the same model scored 23/34; shown all twenty and asked which
six are best, 32/34. A small model has no stable absolute scale — "is this a
7 or an 8?" is a question it answers inconsistently — but comparison inside a
visible set needs no scale at all.
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
        f"general need beneath it. You will see {len(hits)} numbered entries. "
        f"Reply with the {top_n} most relevant numbers, best first, comma "
        "separated. Use each number at most once. Numbers only."
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


def completer_for(endpoint: Endpoint, timeout: float = 120.0) -> Completer:
    """A Completer backed by an OpenAI-compatible /chat/completions endpoint."""

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
