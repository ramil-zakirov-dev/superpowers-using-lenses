---
slice_id: "slice-02-one-ranking-path"
title: "One ranking path: delete the cross-encoder, derive the rest, degrade instead of failing"
status: DRAFT_SPEC
target_version: "0.3.0"
depends_on: []
lenses:
- wondelai/software-design-philosophy#general-purpose-vs-special-purpose@7fd97d295832
- wondelai/release-it#stability-anti-patterns@34ac73394a51
---
# Slice 02 — One ranking path

## 1. Problem

`reranker_kind` offers a choice between two second passes. Measured 2026-08-03
on the 34-pair eval, against a dense baseline scored on both axes for the first
time:

| second pass | need-only | project phrasing | total | cost |
|---|---|---|---|---|
| none — dense top 6 | **33/34** | 27/34 | 60/68 | 0 |
| `cross-encoder` — **the default** | 30/34 | 27/34 | **57/68** | 0.09 s/query |
| `llm` | 31/34 | **32/34** | **63/68** | 0.23 s/query |
| pool-20 recall | 34/34 | 33/34 | 67/68 | — the ceiling |

Three findings, in descending order of how much they cost today.

**The default is worse than not having the feature.** `cross-encoder` gives up
three cases on need-only phrasing and gains nothing on project phrasing — the
axis it was chosen for, and the only one that occurs in production. It is also
the sole reason `sentence-transformers`, and therefore torch, sits in this
project's *required* dependencies: one import, at `src/lenses/rerank.py:55`.

**A ranking failure returns nothing at all.** `find_lenses`
(`src/lenses/mcp_server.py:187`) turns `LlmRerankError` into `{"error": ...}`
and discards the dense pool it has already computed and paid for. The caller's
loss is not 63/68 against 60/68; it is 63/68 against no answer. `completer_for`
defaults to a **120-second** timeout for a call whose measured median is
0.23 s, so an endpoint that hangs rather than refuses takes two minutes of the
caller's time before returning that nothing.

`find_lenses_batch` is the same defect, larger. `src/lenses/mcp_server.py:219`
runs every intent inside one `try`, as a list comprehension, so a ranking
failure on the last of eight needs discards the seven that already resolved —
the batch call exists to gather everything a slice spec needs at once, and it
is the call that loses the most to this. That is the same rule the previous
slice wrote down for `get_lenses`: one failed part does not turn the whole
answer into nothing. It was never applied here.

**The choice is not a choice.** Given the table, no configuration of this
system should select `cross-encoder`, and `llm` versus none is not a judgement
the caller makes — it is a fact about whether they have an endpoint. A
parameter whose correct value is derivable is complexity charged to the caller
for nothing, which is the configuration antipattern
`wondelai/software-design-philosophy#general-purpose-vs-special-purpose` names
directly: *"configuration parameters often represent a failure to decide."*

### Why this was not visible before

The eval ran 17 pairs and never scored the dense baseline on the `concrete`
axis. Both omissions mattered: at 17 pairs `cross-encoder` looked like a
reasonable default that merely lost on project phrasing, and with no baseline
there was no number saying it lost to nothing at all.

## 2. Design

### D1 — Delete the `cross-encoder` path

`src/lenses/rerank.py`, its branch in `second_pass`, its tests, its two
`.env.example` settings, and `sentence-transformers` from `dependencies`.

Rejected — keeping it behind a flag. A path that scores below its own absence
is not an option, it is a way to make this system worse by configuring it.
Keeping it also keeps torch in every install of a package that otherwise talks
to everything over HTTP.

The measurements it produced are not lost: they are in the README, and deleting
the code is what makes them final. Which is the reason for the sequencing in
D6 — after this deletion the comparison can no longer be re-run.

### D2 — `reranker_kind` disappears; the behaviour is derived

If the ranking endpoint is configured, the listwise pass runs. If it is not,
the dense ordering is the answer. There is no enum, no default to be wrong, and
one fewer thing in `.env` than before this slice — not one more.

`Config` keeps the endpoint as an optional value. Its absence is a supported
configuration, not a missing one, and nothing is inferred from it beyond
"do not make that call".

### D3 — A runtime ranking failure degrades; it does not erase

On `LlmRerankError` the dense top `limit` is returned, `ranked_by` is
`"dense"`, and a `warning` key — present only in this case — names the failure.

```json
{"intent": "…", "ranked_by": "dense", "warning": "the ranking pass was unavailable: …", "results": [...]}
```

`ranked_by` already exists for exactly this: to say who actually answered. A
caller that reads only `results` still gets 60/68 worth of answer; a caller
that reads `warning` knows why it is not 63.

Rejected — degrading silently. The measured difference is five cases on the
axis that occurs in production, and a system quietly running three points below
itself for a month is the failure this project keeps writing down.

Rejected also — a `degraded: bool`. `warning` carries the reason, and a caller
testing `"warning" in response` gets the boolean for free.

### D4 — Configured-but-unreachable refuses to start

`startup()` makes one ranking call when the endpoint is configured, and raises
`ConfigError` if it fails. A typo in `.env` is then a server that does not
start, not a server that answers every query three points worse than it
claims.

This keeps D3 honest. Without it, degradation covers for misconfiguration and
`warning` becomes something everyone learns to ignore. With it, degradation
only ever means *an endpoint that was working stopped*, which is the only case
where continuing is the right answer.

### D5 — A timeout matched to the measurement, not to the default

The ranking call's timeout drops from 120 s to **5 s**, roughly twenty times
the measured median and short enough that a hung endpoint costs the caller a
pause rather than an abandoned request. On expiry, D3 applies.

`wondelai/release-it#stability-anti-patterns` is blunt about which of these is
the real hazard: *"slow responses are worse than no response: they tie up
threads, exhaust pools, and propagate delay up the call chain."* This call sits
on every search, so its timeout is not a detail of the HTTP client.

### D6 — Tell the model its candidates are already ordered — then measure

`build_prompt` presents twenty entries and never says they arrive sorted by a
relevance estimate. Nothing asks the model to *reorder*; it is asked to select,
and it selects positionally. On `tests over-mock internal logic and stop
meaning anything` it skips the entry reading *"Over-mocked tests pass while
production breaks"* — dense rank 1, +0.14 clear of the runner-up — and answers
`4,5,17,18,19,20`: two picks and then the tail of the pool in order. Three of
34 answers end in such a run.

The change is one added sentence, to the effect that the entries are ordered
best-first by an estimate and should be moved only where the model disagrees.

**This is a hypothesis with a gate, not a fix.** It ships only if, on the 34
pairs, the total strictly improves on 63/68 **and** project phrasing does not
fall below 32/34. Otherwise the prompt is restored and the measurement is
written into the module docstring as a rejected attempt. `temperature` is 0 and
six runs of one query returned one answer, so a single run is evidence here in
a way it would not be for a sampling model.

**Sequencing.** D6 is measured *before* D1 deletes anything, because the
cross-encoder column can never be re-measured afterwards, and because a change
to the prompt is the one thing in this slice that could plausibly make the
`llm` path worse. D1 does not depend on the outcome: 57/68 loses to 60/68
whatever D6 returns.

## 3. Out of scope

- **Moving `find_lenses` off the dense pool of 20.** Pool recall is 67/68; the
  one case outside it is a retrieval problem, not a ranking one, and widening
  the pool is its own measurement.
- **Retrying the ranking call.** A retry on a hot-path call whose fallback is
  already good costs latency to buy back what D3 gives free. If the endpoint's
  failures turn out to be transient in practice, that is a later slice with its
  own numbers.
- **A different ranking model.** The current one's failure is positional and
  the prompt is untested against it; changing the model first would confound
  the two.

## 4. Acceptance

Behaviour, each covered by a test that touches neither network nor model — the
second pass is already injectable, so all of this is reachable with a stub:

1. With no ranking endpoint configured, `find_lenses` returns the dense
   ordering and `ranked_by == "dense"`, with no `warning`.
2. With one configured, results come from the listwise pass and
   `ranked_by == "llm"`.
3. When the ranking call raises, `find_lenses` returns the dense top `limit`,
   `ranked_by == "dense"`, and a `warning` naming the failure. The results are
   not empty.
4. In `find_lenses_batch`, an entry whose ranking call raises comes back
   degraded — dense results, `ranked_by == "dense"`, its own `warning` — while
   every other entry keeps its own result and its own `ranked_by`. The
   response is never `{"error": ...}` for a ranking failure on one intent.
5. `startup()` raises `ConfigError` when a ranking endpoint is configured and
   the probe call fails, and does not raise when none is configured.
6. The ranking client's timeout is 5 s, asserted where it is constructed.
7. Nothing imports `sentence_transformers`, and it is absent from
   `dependencies`.

Measured, not unit-tested — `scripts/eval_retrieval.py` at 34 pairs:

8. After D6, either total > 63/68 with project phrasing ≥ 32/34 and the prompt
   ships, or the prompt is restored and the number recorded.
9. The `llm` figures in the README table are re-taken after D6 and D1 land,
   and the `cross-encoder` column is replaced by the date it was retired and
   its final score.

## 5. Risks and honest limits

- **A boot-time probe turns a blip into a dead server.** D4 buys its honesty
  with availability: an endpoint that is briefly unreachable when the MCP
  client launches leaves the user with a server that failed to start rather
  than one running degraded. Accepted, because the alternative silently
  converts a misconfiguration into a permanent three-point loss, and because a
  server that will not start says so where a degraded one does not. If it
  proves annoying in practice the answer is a bounded retry at startup, not
  removing the probe.
- **D6 may return nothing.** The gate is deliberately strict and the likeliest
  outcome is a prompt that changes the number by less than the eval can
  resolve. The slice still delivers D1–D5, and a rejected hypothesis with a
  number attached is worth more than the sentence that is currently in the
  docstring guessing at it.
- **34 pairs is still not many.** Every decision here rests on differences of
  three to six cases out of 68. That is enough to retire a path scoring below
  its own absence; it is not enough to tune a ranker on, and D6's gate should
  not be read as evidence about ranking quality in general.
- **The corpus was thin again, though less so than last time.** Four needs were
  put to it; two returned parts that bear on the design and are cited above,
  and both changed it — the configuration antipattern is why D2 removes the
  enum rather than re-pointing its default, and the anti-patterns lens is why
  D5 exists at all. The other two needs returned the flat-score pattern this
  corpus produces when it has nothing: a product-strategy lens for a question
  about deleting code, and a usability lens for one about configuration.
