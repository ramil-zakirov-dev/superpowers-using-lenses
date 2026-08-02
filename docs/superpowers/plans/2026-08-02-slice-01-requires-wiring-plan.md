---
slice_id: "slice-01-requires-wiring"
title: "Wiring `requires` — TDD implementation plan"
status: PLAN_GENERATED
spec: "docs/superpowers/specs/2026-08-02-slice-01-requires-wiring-design.md"
depends_on: []
---

# Wiring `requires` — Implementation Plan

> **For the executing agent:** run this plan through the **Task tool — one plan
> task = one subagent**. Use the `superpowers` skills (TDD: test first, watch it
> fail for the right reason, then implement). **Do not use the `opencode` MCP
> during implementation.**

**Goal:** `Part.requires` stops being a dead field. A part whose author recorded
that it cannot stand alone arrives together with what it needs, labelled, and
anything that could not be delivered is named rather than silently dropped.

**Architecture:** The traversal lives in `src/lenses/resolve.py`, next to the
single-ref `resolve()` it calls. `mcp_server` stays thin — it converts results
into a tool response and owns no resolution logic, exactly as its module
docstring already claims. `requires` additionally reaches the search index so
`find_lenses` can report that a candidate is not standalone, without expanding
it.

**Tech stack:** Python 3.10+, `PyYAML`, `pytest`. No new runtime dependency.

**Working branch:** `feat/slice-01-requires-wiring`. Do not push; do not merge.

---

## Global constraints

- **No network, no model, in any test.** Every test builds its catalogue and
  skill files under `tmp_path`, in the style of `tests/test_resolve.py::build`.
  Nothing in this slice may call the embedder, the reranker or the LLM.
- **Test command:** `python -m pytest tests/ -v -p no:cacheprovider` — always
  with `-p no:cacheprovider`.
- **The suite is at 244 passing. It stays green at every task boundary.**
- **LF line endings — binding.** This repo is LF and Python's `Path.write_text`
  converts to CRLF on Windows; it has already corrupted three files in this
  repo once. When writing a file from a script, pass `newline="\n"`. Before
  every commit check `git diff --stat` — a file reporting far more changed
  lines than you edited is a line-ending rewrite, not a diff.
- **Comment style.** This repo's comments say *why*, and cite measurements
  rather than restating the code. Match that. Do not add narration comments.
- **Do not add a cache to the traversal.** Following a closure re-reads one
  small catalogue YAML a handful of times; at a measured worst case of 8 parts
  that cost is irrelevant, and a cache is state somebody has to invalidate.
  This is a deliberate decision, not an oversight.
- **Commits:** Conventional Commits, one per task, ending with the trailer
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- **Docs language:** English.

## File structure

**Created:**

| File | Responsibility |
|---|---|
| `tests/test_resolve_requires.py` | The closure walk: labelling, dedupe, cycles, cap, errors. |

**Modified:** `src/lenses/resolve.py`, `src/lenses/mcp_server.py`,
`src/lenses/ingest.py`, `src/lenses/search.py`, `tests/test_resolve.py`,
`tests/test_index.py`, `tests/test_search.py`, `README.md`.

---

### Task 1: `ResolvedPart` carries what the part needs

`resolve()` reads the catalogue part and discards its `requires`. Nothing can
traverse a field that never leaves the parser.

**Files:** `src/lenses/resolve.py`, `tests/test_resolve.py`

**Tests first** (extend the existing `build()` fixture with an optional
`requires` argument on the part):

- [ ] `test_a_part_exposes_what_it_requires` — a part catalogued with
      `requires: ["timeouts"]` resolves with `requires == ("timeouts",)`.
- [ ] `test_a_part_with_no_requirements_exposes_an_empty_tuple` — not `None`,
      so callers never branch on which falsy value they got.
- [ ] `test_a_resolved_part_is_not_marked_required_by_default` —
      `required_by == ()`.

**Implementation:**

- [ ] Add to `ResolvedPart`: `requires: tuple[str, ...] = ()` and
      `required_by: tuple[str, ...] = ()`. Both defaulted, so every existing
      construction site keeps compiling.
- [ ] In `resolve()`, populate `requires` from `part.get("requires") or []`.
      `required_by` is set by the caller that pulled the part in, never here —
      `resolve()` answers about one ref and knows nothing about why it was asked.

**Verification:** `python -m pytest tests/test_resolve.py -v -p no:cacheprovider`

---

### Task 2: the guarded closure — `resolve_all()`

The walk itself. This is the task that carries the slice; the rest is plumbing.

**Files:** `src/lenses/resolve.py`, `tests/test_resolve_requires.py` (new)

**Contract:**

```python
MAX_PARTS_PER_REF = 12

def resolve_all(
    refs: list[str], catalog_dir: Path, skills_dir: Path
) -> tuple[list[ResolvedPart], list[str]]:
    """Requested parts, plus everything their `requires` closure names."""
```

Rules, all from the spec:

1. **Order:** every requested part first, in the order given; then required
   parts, in the order first reached. Deterministic, and `required_by` carries
   the provenance that grouping would otherwise have to.
2. **A required ref is built from its requirer.** `requires` holds sibling part
   ids in the same document, so the ref is
   `f"{skill_id}#{required_id}@{version}"` taken from the requiring part's own
   ref via `parse_ref`.
3. **Full transitive closure**, guarded by a visited set of refs.
4. **Dedupe by ref. An explicit request outranks an implied one** — a part the
   caller named is never labelled `required_by`, whichever order it is reached
   in. A part reached from two requirers carries both refs in `required_by`.
5. **Cap:** the closure of one requested ref contributes at most
   `MAX_PARTS_PER_REF - 1` required parts.
6. **A failure is an entry in `errors`, never a lost request.** A requested ref
   that will not resolve behaves as it does today (its `SearchError` text goes
   to `errors`); a *required* ref that will not resolve adds an error and leaves
   the requested part in `parts`.

Error strings — fixed here so they are not invented per site:

```
f"{requiring_ref}: requires {missing_id!r}, which does not resolve: {reason}"
f"{requested_ref}: needs more than {MAX_PARTS_PER_REF} parts; dropped {dropped}"
```

**Tests first** (`tests/test_resolve_requires.py`; build a multi-part catalogue
fixture — one skill, several parts, `requires` edges set per test):

- [ ] `test_a_standalone_part_comes_back_alone` — one part in, one part out,
      `required_by` empty. (Acceptance 1)
- [ ] `test_a_required_sibling_travels_with_the_part` — `required_by` names the
      ref that pulled it in. (Acceptance 2)
- [ ] `test_the_closure_is_followed_past_the_first_hop` — a → b → c returns all
      three. This is the case depth-1 would drop, and the reason the spec chose
      closure; measured on four real parts in `ecc/fastapi-patterns`.
- [ ] `test_a_part_reached_twice_appears_once` — and `required_by` holds both
      requirers. (Acceptance 3)
- [ ] `test_an_explicitly_requested_part_is_never_marked_required` — asked for
      a and b where a requires b; b comes back with `required_by == ()`.
      (Acceptance 4)
- [ ] `test_a_cycle_terminates` — a ⇄ b, each returned once. The corpus has no
      cycles today, and `decompose.py` does not forbid them, so this guard must
      not depend on the corpus. (Acceptance 5)
- [ ] `test_a_broken_requirement_is_reported_and_does_not_hide_the_part` — the
      requested part is in `parts`, the failure is in `errors`, and the error
      names both the requirer and the missing id. (Acceptance 6)
- [ ] `test_the_cap_reports_what_it_dropped` — build a fan-out past
      `MAX_PARTS_PER_REF`, assert the length and an error naming the dropped
      refs. Silent truncation would recreate the exact disease this slice
      removes. (Acceptance 7)
- [ ] `test_a_failed_request_does_not_suppress_a_good_one` — two refs, one
      bogus: one part, one error.

**Implementation:**

- [ ] Write `resolve_all` in `resolve.py`. Requested refs resolved first into an
      ordered `dict[str, ResolvedPart]` keyed by ref; then a per-requested-ref
      walk (queue plus visited set) appending required parts.
- [ ] `required_by` accumulates: a part reached from two requirers ends with
      both. Rebuild the frozen dataclass with `dataclasses.replace`.
- [ ] Module docstring gains a paragraph on why the closure is followed at all —
      the catalogue records that a fragment is not self-sufficient, and handing
      it over silently is worse than refusing it.

**Verification:** `python -m pytest tests/test_resolve_requires.py -v -p no:cacheprovider`

---

### Task 3: `get_lenses` returns the closure

**Files:** `src/lenses/mcp_server.py`, `tests/test_resolve_requires.py`

**Tests first:**

- [ ] `test_get_lenses_returns_required_parts_in_one_list` — one `parts` list,
      not a second key. A consumer reading only `parts` must not lose the
      context; that is the failure being fixed.
- [ ] `test_get_lenses_labels_where_a_part_came_from` — each row carries
      `required_by` and `requires`.
- [ ] `test_get_lenses_still_reports_errors_alongside_parts` — the existing
      `{parts, errors}` contract is extended, not replaced.

**Implementation:**

- [ ] Replace the per-ref `resolve()` loop in `get_lenses` with one
      `resolve_all(refs, HOME / "catalog", HOME / "skills")` call.
- [ ] Each row gains `"requires"` and `"required_by"` (lists).
- [ ] Update the `get_lenses` docstring: say that a part naming requirements
      arrives with them, that `required_by` is empty for what the caller asked
      for, and that anything undeliverable is in `errors`. An agent decides what
      to cite in `lenses:` from this — it must be able to tell the two apart.

**Verification:** full suite green.

---

### Task 4: `requires` reaches the index and `find_lenses` (D5)

Separable from tasks 1–3: if it goes wrong, drop it without invalidating them.

**Files:** `src/lenses/ingest.py`, `src/lenses/search.py`,
`src/lenses/mcp_server.py`, `tests/test_index.py`, `tests/test_search.py`

**Tests first:**

- [ ] `test_the_index_row_carries_requires` — `catalog_parts` emits the field.
- [ ] `test_an_index_without_requires_loads_as_empty` — a row written before
      this change loads with `requires == ()` rather than raising. No forced
      rebuild; the field appears after the next ingest.
- [ ] `test_find_lenses_reports_requirements_without_expanding_them` — the
      result row names them, and the result count still honours `limit`.
      Expanding here would spend the caller's `limit` on parts they did not
      choose.

**Implementation:**

- [ ] `ingest.catalog_parts`: add `"requires": part.get("requires") or []`.
- [ ] `search.IndexedPart`: add `requires: tuple[str, ...] = ()`;
      `load_index` reads it with `row.get(...)` like the other optional fields.
- [ ] `mcp_server._find_one`: each result row gains `"requires"`.

**Verification:** full suite green. Do **not** rebuild `index/` — it is derived
and gitignored, and rebuilding is the reviewer's call, not the executor's.

---

### Task 5: documentation

**Files:** `README.md`

- [ ] Document the behaviour: what `get_lenses` returns for a part with
      requirements, what `required_by` means, and that the cap and every broken
      edge are reported in `errors`.
- [ ] Record the measurement in the same style as the existing tables: 76 edges
      over 26 parts in 11 of 41 skills; 0 cycles; worst closure 7 parts.
- [ ] Add to "What is not settled": `requires` coverage is 6.4%, so this
      changes behaviour for 26 of 405 parts until the decompose-prompt slice
      lands; and `decompose.py` still does not reject cycles — the runtime
      guard is what makes that safe.

**Verification:** full suite green.

---

## Definition of done

- [ ] All five tasks committed on `feat/slice-01-requires-wiring`, one commit each.
- [ ] `python -m pytest tests/ -v -p no:cacheprovider` — 244 prior tests plus the
      new ones, all green. Paste the real summary line; "all green" is not a result.
- [ ] Every file touched is LF. Verify, do not assume.
- [ ] Nothing pushed, nothing merged.

**End-to-end check, run and paste the output** (reads the real catalogue, no
network):

```bash
python -c "import sys; sys.path.insert(0,'src'); from pathlib import Path; from lenses.resolve import resolve_all; p,e = resolve_all(['ecc/fastapi-patterns#async-httpx-pytest@328010fb5180'], Path('catalog'), Path('skills')); print(len(p), 'parts', len(e), 'errors'); [print(' ', x.ref, '<-', x.required_by) for x in p]"
```

Expected: 7 parts, 0 errors — the requested part plus its closure of 6.

The corpus's widest closure is somewhere else; check it too, because it is the
one that would trip a cap set too low:

```bash
python -c "import sys; sys.path.insert(0,'src'); from pathlib import Path; from lenses.resolve import resolve_all; p,e = resolve_all(['wondelai/pragmatic-programmer#common-pragmatic-mistakes@6800c2f4dceb'], Path('catalog'), Path('skills')); print(len(p), 'parts', len(e), 'errors')"
```

Expected: 8 parts, 0 errors — a closure of 7, the corpus-wide maximum quoted
in the spec.

Deliberately not pytest tests: the catalogue is derived content and will
change, and a test pinned to today's corpus would fail on the next ingest for
no defect.

## Out of scope — do not do these

- Raising `requires` coverage above 6.4% (a decompose-prompt change plus a paid
  re-ingest of 41 skills — its own slice).
- Cycle validation in `decompose.py`.
- Rebuilding `index/`.
- Index-side paraphrase expansion of `applies_to`.
- A `follow_requires` toggle on `get_lenses`. Nobody has needed it yet, and a
  switch added on a guess is a guess about which default people will want.
