---
slice_id: "slice-01-requires-wiring"
title: "Wire up `requires`: a part that cannot stand alone must not arrive alone"
status: SPEC_APPROVED
target_version: "0.2.0"
depends_on: []
lenses:
- wondelai/clean-code#error-handling@f9efbdff87b0
- ecc/api-design#response-format@42345c22191b
---
# Slice 01 — Wiring `requires`

## 1. Problem

`Part.requires` is a dead field. It is produced, validated, persisted and
committed to git, and then read by nothing.

| stage | where | what happens |
|---|---|---|
| produced | `src/lenses/decompose.py:255` | parsed out of the model's answer |
| validated | `src/lenses/decompose.py:284-288` | unknown part ids and self-reference rejected |
| persisted | `src/lenses/model.py:62-63` | written to the catalogue YAML, committed |
| **read** | — | **nowhere** |

`ResolvedPart` (`src/lenses/resolve.py:20-30`) has no such field. `resolve()`
reads `preamble_spans` and `spans` and nothing else. `catalog_parts()`
(`src/lenses/ingest.py:129-153`) does not carry it into the index. `get_lenses`
(`src/lenses/mcp_server.py:224-257`) therefore cannot report it.

Measured against the catalogue as committed — 41 skills, 405 parts:

| context carrier | parts | share |
|---|---|---|
| `preamble_spans` only | 175 | 43.2% |
| `requires` only | 5 | 1.2% |
| both | 21 | 5.2% |
| **neither** | **204** | **50.4%** |

76 `requires` edges, across 26 parts, in 11 of 41 skills.

**The consequence.** When a part carries `requires`, the decomposition has
recorded, in the catalogue, that this fragment does not stand on its own.
`get_lenses` hands over the fragment and says nothing about it. That is worse
than an incomplete answer: it is an incomplete answer the catalogue already
knew about, delivered with the same confidence as a complete one. An agent
cites it in `lenses:` and proceeds on a section whose author said it needed a
sibling.

Note the asymmetry with `preamble_spans`, which addresses the same disease and
is fully wired: it pulls upstream lines into the part's own text and into its
own `sha256` (`ingest.py:92`, `resolve.py:61`), so the preamble is verbatim and
hash-verified like everything else. `requires` exists for the case a preamble
cannot cover — a whole sibling section, not a header — and it is precisely that
case which currently does nothing.

## 2. Why this slice, and not index-side paraphrase expansion

The alternative on the table was generating paraphrases of `applies_to` in the
caller's register and indexing them as extra vectors. Measured this session,
against the 17-pair eval:

| axis | recall in pool-20 | median unfiltered rank of the target |
|---|---|---|
| `intent` | 17/17 | 1 |
| `concrete` | 16/17 | 5 |

The listwise second pass already returns 16/17 on `concrete`. **It is at the
ceiling of what the dense pass hands it** — retrieval-side work has at most one
case of headroom on the current eval, and that one case sits at unfiltered rank
42, far outside any plausible pool.

The register gap is still real (median rank 5 against 1) and will cost hits as
the corpus grows past a fixed pool of 20. It is not urgent, and it cannot be
measured by a 17-pair eval scored on hit@6. Both are tracked separately.

Meanwhile half the corpus carries no context carrier at all, and the mechanism
for the worst half of that is already built and unplugged.

## 3. Design

### D1 — Follow `requires` transitively, with a visited set and a cap

Measured over all 76 edges:

- **0 cycles of any length** (colour DFS over the whole graph).
- Depth ≥2 adds parts for **4 of 26** requiring parts, all in `ecc/fastapi-patterns`.
- **Worst full closure: 7 extra parts** — identical to the worst depth-1 fan-out.
- Every edge is intra-skill: `decompose.py` validates `requires` against sibling
  ids in the same document, so traversal never leaves one catalogue file.

**Decision: full transitive closure.**

Rejected — depth-1 only. It is simpler and matches a narrow reading of the
field, but it drops the four measured cases: `async-httpx-pytest` would arrive
without `configuration`, `pydantic-schemas` and `transactional-service-layer`.
That is exactly the incompleteness this slice exists to remove, in the skill
that uses the field most heavily. Closure costs a visited set and buys those
four; at a worst case of 7 extra parts it costs nothing else today.

The cycle guard is not defensive decoration. `decompose.py:284-288` rejects
unknown ids and self-reference and **does not check for cycles**. Today's zero
is a property of what one model happened to write, not an invariant of the
format. The visited set is what keeps traversal safe against the next ingest.

### D2 — Required parts arrive in the same list, labelled

`ResolvedPart` gains `required_by: tuple[str, ...]` — empty for a part the
caller named, otherwise the refs that pulled it in.

Rejected — a separate `required_parts` key in the response. It forces every
consumer to merge two lists, and a consumer that reads only `parts` silently
loses the context, reproducing the failure being fixed. One list, one shape,
provenance on the row. (`ecc/api-design#response-format` argues the envelope
case; the reason it does not apply here is that the extra rows are not
metadata about the request, they are more of the answer.)

### D3 — An explicit request outranks an implied one

Deduplicate by ref. A part the caller named is never labelled `required_by`,
regardless of the order it is reached in.

### D4 — Every reduction is visible in `errors`

`get_lenses` already returns `{parts, errors}` — partial results alongside
named failures. This slice extends that contract rather than inventing one:

- A `requires` that cannot be resolved — hand-edited catalogue, stale pin —
  becomes an `errors` entry naming the requiring part and the missing id. The
  requested part is still returned.
- Hitting the cap emits an `errors` entry naming what was dropped.

Silent truncation is forbidden here, because it would recreate the disease
precisely: a fragment that is incomplete and does not say so.

This is `wondelai/clean-code#error-handling@f9efbdff87b0` applied — an error
carries the operation and the state that produced it, and one failed edge does
not turn the whole call into nothing.

### D5 — `find_lenses` reports requirements, does not expand them

`catalog_parts` carries `requires` into the index row; `IndexedPart` reads it
with `row.get(...)`, so an index built before this change loads as empty rather
than failing — no forced rebuild, the field appears after the next ingest.
`find_lenses` results gain `requires: [part_id, ...]`.

Search returns candidates for a decision. Expanding bodies there would spend
the caller's `limit` on parts they did not choose. But knowing that a candidate
is not standalone is part of choosing it, and it makes the later `get_lenses`
expansion predictable instead of surprising.

**Separable:** D5 can be dropped without invalidating D1–D4.

### D6 — Cap at 12 parts per requested ref

Observed worst closure is 7. Twelve leaves headroom for the coverage work
below while keeping the response size a property of this code rather than of
whatever a model wrote into a YAML file.

## 4. Out of scope

- **Raising `requires` coverage above 6.4%.** A decompose-prompt change plus a
  re-ingest of 41 skills against a paid endpoint, with a full catalogue diff to
  review. Different cost, different risk, different review. `decompose.py:80-81`
  gives `requires` a single line where `kind` and `applies_to` each get a
  paragraph — the likely cause of the 6.4%, and the next slice.
- **Cycle validation at decompose time.** The runtime guard makes it
  non-urgent; the check is cheap and belongs with the coverage work.
- **Index-side paraphrase expansion.** See §2.

## 5. Acceptance

Behaviour, each covered by a test that touches neither network nor model:

1. A part with no `requires` returns exactly one part, `required_by` empty.
2. A part with `requires` returns it plus its full closure, each labelled with
   what pulled it in.
3. A part reachable by two paths appears once.
4. A part both requested and required is not labelled required.
5. A constructed cycle terminates and returns each part once. (Built in a
   fixture — the corpus has none, and the guard must not depend on that.)
6. An unresolvable `requires` produces an `errors` entry and does **not**
   suppress the requested part.
7. Exceeding the cap produces an `errors` entry naming what was dropped.
8. `find_lenses` reports `requires`; an index row without the key loads as
   empty rather than raising.

End-to-end, against the real catalogue and no fixtures:
`ecc/fastapi-patterns#async-httpx-pytest` returns 7 parts and no errors (a
closure of 6), and `wondelai/pragmatic-programmer#common-pragmatic-mistakes` —
the corpus's widest — returns 8 (a closure of 7).

## 6. Risks and honest limits

- **Response size.** Eight `fastapi-patterns` parts is a large read, and an
  agent asking for three such refs gets a great deal of text. Mitigated by the
  cap and by D5, which lets a caller see the fan-out before asking. Not
  eliminated. If it bites, the answer is a `follow_requires: bool = True`
  argument — deliberately not added now, because a switch nobody has needed yet
  is a guess about which way they will want it.
- **A closure repeats the preamble.** Measured against the real catalogue after
  the slice landed, not predicted before it: 23 of the 26 closures serve
  siblings that share a `preamble_spans` prefix, so the same upstream lines
  arrive once per part. 23 236 duplicated characters against 231 413 returned —
  10% overall, 24% at the worst (`lean-startup#innovation-accounting`, a
  closure of 2), 3 156 characters at the largest
  (`team-topologies#quick-diagnostic`, a closure of 7). Longest common prefix,
  so a lower bound.

  **Deliberately not deduplicated.** Stripping the shared prefix from all but
  the first part would hand back text that no longer hashes to the part's
  recorded `sha256`, which is the one thing this catalogue refuses to do — a
  citation resolving to different text is worse than one that fails, because
  nobody notices. Ten percent is the price of every part in the answer being
  independently verifiable, and it is the right trade. Recorded here because
  §6 named response size and cited the cap and D5 as the mitigations, and
  neither mitigates this: the cap counts parts, and D5 shows fan-out, while
  the cost is per-part text nobody asked for twice.

- **Narrow blast radius.** At 6.4% coverage this changes behaviour for 26 of
  405 parts. The value is real but stays small until the coverage slice lands.
  Recorded here so it is not met later as disappointment.
- **The corpus said little about this slice.** Five need-only queries were run
  against it; two returned anything that bore on the design, and the dense
  scores across the pool were flat (top 0.54, spread 0.058 on the composition
  question) — the corpus's own signature for "nothing here". This is a catalogue
  of design and product lenses, not of retrieval-service internals. Recorded
  because a spec that cites two lenses and implies it consulted a library would
  be overstating what the corpus gave.

## 7. Operational note

The running `using-lenses` MCP server holds pre-`25f1eb2` code: its
`find_lenses_batch` schema still advertises `reranked`, and it answers through
the cross-encoder with the confidence gate that commit removed. Restart the
client before judging any retrieval behaviour by hand.
