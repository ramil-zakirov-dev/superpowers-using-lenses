---
slice_id: "slice-02-one-ranking-path"
spec: docs/superpowers/specs/2026-08-03-slice-02-one-ranking-path-design.md
status: PLAN_GENERATED
target_version: "0.3.0"
---
# One Ranking Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Leave this repository with exactly one second-pass ranking implementation, selected by whether an endpoint is configured rather than by a setting, and degrading to the dense ordering instead of erasing the answer.

**Architecture:** `reranker_kind` and the whole `cross-encoder` path are deleted; `Config.reranker` being `None` becomes the supported "no second pass" configuration. `_find_one` gains the only branch that knows the difference, catches `LlmRerankError` itself, and answers with the pure dense top-`limit` plus a `warning` key. `startup()` probes a configured ranking endpoint once so a typo fails at launch rather than degrading forever.

**Tech Stack:** Python 3.10+, pytest, httpx, MCP. No torch after this slice.

## Global Constraints

- Every file written in this repository uses **LF** line endings. Never let an editor or script write CRLF.
- Run tests as `./.venv/Scripts/python.exe -m pytest tests/ -p no:cacheprovider -q`. The `-p no:cacheprovider` is not optional.
- Baseline before Task 1: **265 passed**. Every task's test run must be green before its commit.
- Commit messages follow Conventional Commits and end with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.
- No new dependency may be added. One is being removed.
- Do not add a cache, a retry, or a circuit breaker anywhere in this slice. The spec puts all three out of scope.
- `scripts/eval_retrieval.py` calls a live endpoint and costs real time. Run it only where a task says to.

---

### Task 1: The prompt hypothesis, measured behind a gate

This task is first because it is the only one that can be invalidated by the
others: after Task 5 the cross-encoder column can never be re-measured, and a
prompt change is the one thing here that could make the `llm` path worse.

**Files:**
- Modify: `src/lenses/llm_rerank.py:52-59` (the `system` string in `build_prompt`)
- Test: `tests/test_llm_rerank.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: nothing later tasks depend on. `build_prompt(intent: str, hits: list[Hit], top_n: int) -> tuple[str, str]` keeps its signature either way.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_llm_rerank.py`, after `test_the_prompt_states_the_pool_size_and_the_wanted_count`:

```python
def test_the_prompt_says_the_entries_are_already_ordered():
    """Measured 2026-08-03: shown an unlabelled list, the model selects
    positionally — on one query it skipped the entry reading "Over-mocked
    tests pass while production breaks", dense rank 1 and +0.14 clear of the
    runner-up, and answered 4,5,17,18,19,20. Nothing in the prompt told it the
    list already carried an opinion."""
    system, _ = build_prompt("a need", pool(20), top_n=6)
    assert "already ordered" in system.lower()
    assert "disagree" in system.lower()
```

Both assertions name something the current prompt does not say. `best first`
would not have worked — the existing text already contains it, describing the
*reply* rather than the input.

- [ ] **Step 2: Run it and watch it fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_llm_rerank.py::test_the_prompt_says_the_entries_are_already_ordered -p no:cacheprovider -v
```

Expected: FAIL — `assert "already ordered" in system.lower()`. The current
system message never says the entries arrive in any order.

The two neighbouring prompt tests must keep passing: they assert
`"20 numbered entries"` and `"the 6 most relevant"`, and the replacement in
Step 3 preserves both substrings on purpose. If either breaks, the replacement
was mistyped.

- [ ] **Step 3: Add the sentence to the prompt**

In `src/lenses/llm_rerank.py`, replace the `system` assignment in `build_prompt`:

```python
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
```

- [ ] **Step 4: Run the unit tests**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -p no:cacheprovider -q
```

Expected: 266 passed.

- [ ] **Step 5: Measure on the 34-pair eval**

```bash
./.venv/Scripts/python.exe scripts/eval_retrieval.py
```

Read the last four lines. The numbers to compare against, measured 2026-08-03
with the current prompt:

| | before |
|---|---|
| `ranked` (need-only) | 31/34 |
| `concrete phrasing` | 32/34 |
| `total across both axes` | 63/68 |

- [ ] **Step 6: Apply the gate**

**The change ships only if `total` > 63/68 AND `concrete phrasing` >= 32/34.**
`temperature` is 0 and six runs of one query returned one answer, so one run
is evidence here. Do not re-run hoping for a better number.

**If it passes**, record the new figures in the `llm_rerank.py` module
docstring by replacing the paragraph beginning `**What the numbers above do
not say` with the measured outcome, then go to Step 7.

**If it fails**, revert the prompt with `git checkout -- src/lenses/llm_rerank.py`,
delete the test added in Step 1, and instead append this to the module
docstring, filling in the three numbers actually observed:

```python
"""
Tried and rejected 2026-08-03: telling the model in `build_prompt` that its
entries arrive ordered best first, so it would reorder rather than reselect.
Scored <ranked>/34 need-only, <concrete>/34 project phrasing, <total>/68 —
against 31, 32 and 63 for the prompt as it stands. The positional selection
described above survives it, so the cause is not that the model was unaware
of the ordering.
"""
```

Then run the suite again (expected: 265 passed) and go to Step 7.

- [ ] **Step 7: Commit**

If the gate passed:

```bash
git add src/lenses/llm_rerank.py tests/test_llm_rerank.py
git commit -m "feat(rank): tell the ranking model its candidates are already ordered"
```

If the gate failed:

```bash
git add src/lenses/llm_rerank.py
git commit -m "docs(rank): record a rejected prompt hypothesis with its numbers"
```

---

### Task 2: `reranker_kind` disappears; the endpoint decides

**Files:**
- Modify: `src/lenses/config.py:16-26` (drop `DEFAULT_RERANKER`, `RERANKER_KINDS`), `:52-63` (Config fields), `:108-125` (loading)
- Modify: `src/lenses/mcp_server.py:74-84` (`second_pass`), `:110` (`ranked_by`)
- Modify: `scripts/eval_retrieval.py` (the `second pass:` banner line)
- Modify: `tests/test_resolve_requires.py:238` (stale `reranker_kind` in a fake config)
- Create: `tests/test_config_ranking.py`
- Modify: `tests/test_rerank.py` (remove the config tests it holds; the file itself dies in Task 5)

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - `Config` no longer has `reranker_kind` or `reranker_model`. It keeps `reranker: Endpoint | None = None`.
  - `second_pass(config: Config) -> Callable[[str, list[Hit], int], list[Hit]] | None` — **`None` now means no second pass is configured.** Task 3 relies on this.
  - `lenses.config.DEFAULT_RERANKER` and `RERANKER_KINDS` no longer exist.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_config_ranking.py`:

```python
"""Which second pass runs is not a setting any more — it is whether an
endpoint is configured. What must still fail loudly is a half-configured one."""

from pathlib import Path

import pytest

from lenses.config import ConfigError, load_config


@pytest.fixture
def env(monkeypatch, tmp_path) -> Path:
    """Every required setting, no .env on disk, no ranking endpoint."""
    for name, value in {
        "llm_base_url": "https://example.invalid/v1",
        "llm_model": "m",
        "llm_api_key": "k",
        "embedder_base_url": "https://example.invalid/v1",
        "embedder_model": "e",
        "embedder_api_key": "k",
        "embedder_dim": "768",
        "min_coverage": "0.5",
    }.items():
        monkeypatch.setenv(name, value)
    for name in ("reranker_kind", "reranker_model", "reranker_base_url",
                 "reranker_api_key"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "absent.env"


def test_no_ranking_endpoint_is_a_supported_configuration(env):
    """Absence is not a missing setting. It means the dense ordering answers."""
    assert load_config(env).reranker is None


def test_a_configured_endpoint_is_read_whole(env, monkeypatch):
    monkeypatch.setenv("reranker_base_url", "http://localhost:1234/v1/")
    monkeypatch.setenv("reranker_model", "gemma-4-e2b-it-qat")
    monkeypatch.setenv("reranker_api_key", "k")
    reranker = load_config(env).reranker
    assert reranker.base_url == "http://localhost:1234/v1"   # trailing / trimmed
    assert reranker.model == "gemma-4-e2b-it-qat"
    assert reranker.api_key == "k"


@pytest.mark.parametrize("present", ["reranker_base_url", "reranker_model",
                                     "reranker_api_key"])
def test_a_half_configured_endpoint_is_refused(env, monkeypatch, present):
    """Fail closed. Someone who set one of the three meant to search with a
    second pass, and silently giving them the dense ordering for a month is
    exactly what the warning in find_lenses must be allowed to mean something
    other than 'you have a typo'."""
    monkeypatch.setenv(present, "something")
    with pytest.raises(ConfigError, match="reranker_"):
        load_config(env)


def test_the_ranking_endpoint_is_not_the_decomposition_one(env, monkeypatch):
    """`llm_*` is the hosted model that cuts skills up and runs once per skill.
    This one runs on every search and wants to be local."""
    monkeypatch.setenv("reranker_base_url", "http://localhost:1234/v1")
    monkeypatch.setenv("reranker_model", "gemma-4-e2b-it-qat")
    monkeypatch.setenv("reranker_api_key", "k")
    config = load_config(env)
    assert config.reranker.base_url != config.llm.base_url


def test_reranker_kind_is_gone(env, monkeypatch):
    """A leftover setting in someone's .env must not silently do nothing that
    looks like something. It is simply not read."""
    monkeypatch.setenv("reranker_kind", "cross-encoder")
    config = load_config(env)
    assert not hasattr(config, "reranker_kind")
    assert config.reranker is None
```

- [ ] **Step 2: Run them and watch them fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_config_ranking.py -p no:cacheprovider -v
```

Expected: `test_no_ranking_endpoint_is_a_supported_configuration` passes by
accident (the field already defaults to `None`); the half-configured and
`reranker_kind_is_gone` tests FAIL.

- [ ] **Step 3: Rewrite the configuration**

In `src/lenses/config.py`, delete the `DEFAULT_RERANKER` and `RERANKER_KINDS`
blocks at lines 16-26 entirely. Replace the three `reranker*` fields on
`Config` (lines 52-63) with one:

```python
    #: Where the listwise second pass is served. `None` is a supported
    #: configuration and not a missing one: it means the dense ordering is the
    #: answer. Kept separate from `llm` above — that one decomposes skills once
    #: each and is typically hosted, while this one runs on every search and
    #: wants to be local.
    reranker: Endpoint | None = None
```

Replace the `reranker_kind` block (lines 108-125) with:

```python
    # Which second pass runs is not a setting. Configure the endpoint and the
    # listwise pass runs; leave it out and the dense ordering answers. Setting
    # some of the three and not the others is the one case that fails closed:
    # it is a typo, not a decision, and degrading silently would make the
    # `warning` in find_lenses mean two different things.
    ranking_settings = {
        name: os.environ.get(name, "").strip()
        for name in ("reranker_base_url", "reranker_model", "reranker_api_key")
    }
    if any(ranking_settings.values()):
        reranker_endpoint = Endpoint(
            base_url=_require("reranker_base_url").rstrip("/"),
            model=_require("reranker_model"),
            api_key=_require("reranker_api_key"),
        )
    else:
        reranker_endpoint = None
```

And in the returned `Config(...)`, delete the `reranker_kind=` and
`reranker_model=` arguments, keeping `reranker=reranker_endpoint`.

- [ ] **Step 4: Make `second_pass` able to say "none"**

In `src/lenses/mcp_server.py`, replace `second_pass` (lines 74-84) with:

```python
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
```

In `_find_one`, replace line 107 and the `ranked_by` line so the branch is
explicit (this is rewritten again in Task 3 — keep it minimal here):

```python
    ranker = second_pass(config)
    hits = candidates[:limit] if ranker is None else ranker(intent, candidates, limit)
    return {
        "intent": intent,
        "ranked_by": "dense" if ranker is None else "llm",
```

- [ ] **Step 5: Fix the two stale readers**

In `scripts/eval_retrieval.py`, replace the banner line:

```python
    print(f"second pass: {config.reranker.model if config.reranker else 'none'}\n")
```

In `tests/test_resolve_requires.py:238`, replace `reranker_kind="llm"` with
`reranker=None` — `second_pass` is monkeypatched in that test, so the field is
never read, but a fake config naming a setting that no longer exists is a lie
the next reader has to disprove:

```python
        config=SimpleNamespace(embedder=None, embedder_dim=2, reranker=None),
```

- [ ] **Step 6: Strip the config tests out of `tests/test_rerank.py`**

Delete everything from the comment `# Which *kind* of second pass runs.`
(line 133) to the end of the file, and remove `ConfigError`, `load_config` and
`DEFAULT_RERANKER` from its imports. What remains is cross-encoder behaviour
only; the file dies in Task 5.

- [ ] **Step 7: Run the tests**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -p no:cacheprovider -q
```

Expected: all green. Count is 265 or 266 (Task 1's outcome) minus 6 removed
config tests plus 7 new ones.

- [ ] **Step 8: Commit**

```bash
git add src/lenses/config.py src/lenses/mcp_server.py scripts/eval_retrieval.py tests/test_config_ranking.py tests/test_rerank.py tests/test_resolve_requires.py
git commit -m "refactor(config): let the endpoint decide the second pass, not a setting"
```

---

### Task 3: A ranking failure degrades instead of erasing the answer

**Files:**
- Modify: `src/lenses/mcp_server.py:87-129` (`_find_one`), `:183-188` (`find_lenses`), `:218-223` (`find_lenses_batch`)
- Modify: `src/lenses/llm_rerank.py:120` (`completer_for` timeout default)
- Create: `tests/test_degradation.py`

**Interfaces:**
- Consumes: `second_pass(config) -> Callable | None` from Task 2.
- Produces:
  - `_find_one` **never raises `LlmRerankError`**. Task 4 relies on that being the only remaining way a ranking failure reaches a caller.
  - The response gains an optional `"warning": str` key, present only when the ranking pass was configured and failed.
  - `completer_for(endpoint, timeout: float = 5.0)`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_degradation.py`:

```python
"""A ranking failure must cost the caller the ordering, not the answer.

The dense pool is already computed and paid for by the time the second pass
runs. Turning that into {"error": ...} - which is what find_lenses did before
this - throws away 60/68 worth of results to report that 63/68 was not
available.
"""

from types import SimpleNamespace

import pytest

from lenses import mcp_server
from lenses.llm_rerank import LlmRerankError
from lenses.search import Corpus, IndexedPart


def indexed(part_id: str, vector=(1.0, 0.0), skill_id="lab/skill") -> IndexedPart:
    return IndexedPart(
        skill_id=skill_id, version="v1", part_id=part_id, title=part_id,
        applies_to=f"Use when {part_id}.", kind="reference", sha256="h",
        vector=vector,
    )


@pytest.fixture
def corpus() -> Corpus:
    return Corpus([indexed("alpha"), indexed("beta", (0.9, 0.1)),
                   indexed("gamma", (0.8, 0.2))])


@pytest.fixture
def config():
    return SimpleNamespace(embedder=None, embedder_dim=2, reranker=None)


@pytest.fixture(autouse=True)
def no_embedder(monkeypatch):
    monkeypatch.setattr(mcp_server, "embed_query", lambda *a, **k: [1.0, 0.0])


def test_with_no_ranking_configured_the_dense_order_answers(monkeypatch, config, corpus):
    monkeypatch.setattr(mcp_server, "second_pass", lambda config: None)
    answer = mcp_server._find_one("a need", config, corpus, 2, None, None)
    assert answer["ranked_by"] == "dense"
    assert "warning" not in answer
    assert [r["ref"] for r in answer["results"]] == [
        "lab/skill#alpha@v1", "lab/skill#beta@v1"]


def test_a_configured_pass_is_reported_as_llm(monkeypatch, config, corpus):
    monkeypatch.setattr(
        mcp_server, "second_pass",
        lambda config: lambda intent, hits, limit: list(reversed(hits))[:limit],
    )
    answer = mcp_server._find_one("a need", config, corpus, 2, None, None)
    assert answer["ranked_by"] == "llm"
    assert "warning" not in answer


def test_a_ranking_failure_returns_the_dense_answer(monkeypatch, config, corpus):
    def explode(intent, hits, limit):
        raise LlmRerankError("localhost:1234 refused the connection")

    monkeypatch.setattr(mcp_server, "second_pass", lambda config: explode)
    answer = mcp_server._find_one("a need", config, corpus, 2, None, None)

    assert answer["ranked_by"] == "dense"
    assert len(answer["results"]) == 2, "the pool was paid for; do not throw it away"
    assert "refused the connection" in answer["warning"]


def _raise_llm_error(intent, hits, limit):
    raise LlmRerankError("down")


def test_the_degraded_answer_is_the_dense_top_n_not_the_pool_head(monkeypatch, config):
    """The 60/68 baseline was measured with `rank(limit=n)` — whose `per_skill`
    default is 2. The candidate pool uses 4, so its head is a different list.

    Here skill A holds the three best parts. The dense answer for limit=3 is
    A0, A1 and then B0, because A2 is over A's cap of two. Slicing the pool
    would answer A0, A1, A2 — an ordering nothing measured.
    """
    parts = [
        indexed("a0", (1.0, 0.0), "lab/a"),
        indexed("a1", (1.0, 0.1), "lab/a"),
        indexed("a2", (1.0, 0.2), "lab/a"),
        indexed("b0", (1.0, 0.3), "lab/b"),
    ]
    monkeypatch.setattr(mcp_server, "second_pass", lambda config: _raise_llm_error)
    answer = mcp_server._find_one("a need", config, Corpus(parts), 3, None, None)
    assert [r["ref"] for r in answer["results"]] == [
        "lab/a#a0@v1", "lab/a#a1@v1", "lab/b#b0@v1"]


def test_find_lenses_does_not_turn_a_ranking_failure_into_an_error(
    monkeypatch, config, corpus
):
    monkeypatch.setattr(mcp_server, "startup", lambda: (config, corpus))
    monkeypatch.setattr(mcp_server, "second_pass", lambda config: _raise_llm_error)
    answer = mcp_server.find_lenses("a need", limit=2)
    assert "error" not in answer
    assert answer["ranked_by"] == "dense"
    assert answer["results"]


def test_one_failing_intent_does_not_erase_a_batch(monkeypatch, config, corpus):
    """find_lenses_batch ran every intent inside one try, as a comprehension,
    so a failure on the last of eight discarded the seven that resolved. The
    batch call exists to gather a whole spec's needs at once, which makes it
    the call that loses the most."""
    calls = {"n": 0}

    def flaky(intent, hits, limit):
        calls["n"] += 1
        if calls["n"] == 2:
            raise LlmRerankError("down")
        return hits[:limit]

    monkeypatch.setattr(mcp_server, "startup", lambda: (config, corpus))
    monkeypatch.setattr(mcp_server, "second_pass", lambda config: flaky)
    answer = mcp_server.find_lenses_batch(["first", "second", "third"], limit=2)

    assert "error" not in answer
    kinds = [entry["ranked_by"] for entry in answer["results"]]
    assert kinds == ["llm", "dense", "llm"]
    assert all(entry["results"] for entry in answer["results"])
    assert "warning" in answer["results"][1]
    assert "warning" not in answer["results"][0]


def test_the_ranking_timeout_is_short_enough_to_degrade_from():
    """Measured median for this call is 0.23 s. The old default was 120 s, so
    a hung endpoint cost two minutes before returning nothing - which is the
    anti-pattern that a slow response is worse than no response."""
    import inspect

    from lenses.llm_rerank import completer_for

    assert inspect.signature(completer_for).parameters["timeout"].default == 5.0
```

- [ ] **Step 2: Run them and watch them fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_degradation.py -p no:cacheprovider -v
```

Expected: the three failure-path tests, the batch test and the timeout test
FAIL. `test_with_no_ranking_configured...` and `test_a_configured_pass...`
pass already from Task 2.

- [ ] **Step 3: Restructure `_find_one`**

Replace `_find_one` in `src/lenses/mcp_server.py` (lines 87-129) with:

```python
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


def _response(
    intent: str, ranked_by: str, hits: list[Hit],
    dense_score: dict[str, float], warning: str | None = None,
) -> dict[str, Any]:
    answer: dict[str, Any] = {
        "intent": intent,
        "ranked_by": ranked_by,
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
    difference between 63/68 and 60/68. `ranked_by` says who answered and
    `warning` says why it was not the other one.
    """
    vector = embed_query(config.embedder, intent, config.embedder_dim)
    ranker = second_pass(config)
    if ranker is None:
        hits = _dense_answer(vector, corpus, limit, kind, stack)
        return _response(intent, "dense", hits,
                         {hit.part.ref: hit.score for hit in hits})

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
        return _response(
            intent, "dense", fallback,
            {hit.part.ref: hit.score for hit in fallback},
            warning=f"the ranking pass was unavailable, so these are the dense "
                    f"results: {exc}",
        )
    return _response(intent, "llm", hits, dense_score)
```

- [ ] **Step 4: Stop the tool wrappers catching what no longer escapes**

In `find_lenses` (lines 183-188), delete the `LlmRerankError` arm. `RerankError`
stays until Task 5 removes the module:

```python
    try:
        return _find_one(intent, config, corpus, limit, kind, stack)
    except EmbedError as exc:
        return {"error": f"the embedding endpoint is unreachable or misconfigured: {exc}"}
    except RerankError as exc:
        return {"error": f"the second ranking pass is unavailable: {exc}"}
```

Make the identical edit in `find_lenses_batch` (lines 218-223). Its list
comprehension needs no change: with `_find_one` no longer raising for a ranking
failure, one intent's failure can no longer take the batch with it.

- [ ] **Step 5: Shorten the timeout**

In `src/lenses/llm_rerank.py`, change the signature at line 120 and its
docstring:

```python
def completer_for(endpoint: Endpoint, timeout: float = 5.0) -> Completer:
    """A Completer backed by an OpenAI-compatible /chat/completions endpoint.

    Five seconds is roughly twenty times the measured median for this call and
    sits on every search. The previous 120 s made a hung endpoint cost the
    caller two minutes before `_find_one` could fall back to the dense
    ordering, which is the failure a slow response causes and a refused
    connection does not.
    """
```

- [ ] **Step 6: Run the tests**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -p no:cacheprovider -q
```

Expected: all green, 8 more than Task 2 left behind.

- [ ] **Step 7: Commit**

```bash
git add src/lenses/mcp_server.py src/lenses/llm_rerank.py tests/test_degradation.py
git commit -m "fix(search): degrade to the dense order instead of erasing the answer"
```

---

### Task 4: A configured-but-unreachable endpoint refuses to start

Without this, degradation covers for misconfiguration and `warning` becomes
something everyone learns to ignore. With it, a `warning` can only ever mean
*an endpoint that was working stopped*.

**Files:**
- Modify: `src/lenses/mcp_server.py:60-71` (`startup`)
- Test: `tests/test_degradation.py`

**Interfaces:**
- Consumes: `Config.reranker` from Task 2, `completer_for` from Task 3.
- Produces: `startup()` raises `ConfigError` when a ranking endpoint is configured and unreachable. Nothing later depends on it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_degradation.py`:

```python
def test_startup_probes_a_configured_ranking_endpoint(monkeypatch, tmp_path):
    """A typo in .env must be a server that does not start, not a server that
    answers every query three points worse than it says it does."""
    from lenses.config import ConfigError

    monkeypatch.setattr(mcp_server, "_config", None)
    monkeypatch.setattr(mcp_server, "_corpus", None)
    monkeypatch.setattr(
        mcp_server, "load_config",
        lambda path: SimpleNamespace(
            embedder=None, embedder_dim=2,
            reranker=SimpleNamespace(base_url="http://nowhere/v1", model="m",
                                     api_key="k"),
        ),
    )
    monkeypatch.setattr(mcp_server, "load_index", lambda path, dim: [])

    def refuse(system, user):
        raise LlmRerankError("http://nowhere/v1: connection refused")

    monkeypatch.setattr(mcp_server, "completer_for", lambda endpoint, **kw: refuse)
    with pytest.raises(ConfigError, match="http://nowhere/v1"):
        mcp_server.startup()


def test_startup_probes_nothing_when_no_endpoint_is_configured(monkeypatch):
    """No endpoint is a supported configuration, so there is nothing to probe
    and startup must not invent a reason to fail."""
    monkeypatch.setattr(mcp_server, "_config", None)
    monkeypatch.setattr(mcp_server, "_corpus", None)
    monkeypatch.setattr(
        mcp_server, "load_config",
        lambda path: SimpleNamespace(embedder=None, embedder_dim=2, reranker=None),
    )
    monkeypatch.setattr(mcp_server, "load_index", lambda path, dim: [])
    monkeypatch.setattr(
        mcp_server, "completer_for",
        lambda endpoint, **kw: pytest.fail("nothing to probe"),
    )
    config, _ = mcp_server.startup()
    assert config.reranker is None
```

- [ ] **Step 2: Run them and watch them fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_degradation.py -k startup -p no:cacheprovider -v
```

Expected: `test_startup_probes_a_configured_ranking_endpoint` FAILS —
`DID NOT RAISE ConfigError`. The second test passes already.

- [ ] **Step 3: Add the probe**

Replace `startup` in `src/lenses/mcp_server.py` (lines 60-71):

```python
def startup() -> tuple[Config, Corpus]:
    """Load configuration and index once, failing loudly if either is absent.

    A configured ranking endpoint is probed here, once per process. The reason
    is that `_find_one` degrades to the dense ordering when that endpoint
    fails, and a degradation that also covers typos would make its `warning`
    mean two unrelated things. Probing at launch leaves it meaning exactly one:
    an endpoint that was working has stopped.
    """
    global _config, _corpus
    if _config is None or _corpus is None:
        config = load_config(HOME / ".env")
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
        _config, _corpus = config, corpus
    return _config, _corpus
```

Note the assignment to the globals happens **after** the probe, so a failed
probe leaves `startup()` retryable rather than caching a half-built state.

- [ ] **Step 4: Run the tests**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -p no:cacheprovider -q
```

Expected: all green, 2 more than Task 3.

- [ ] **Step 5: Commit**

```bash
git add src/lenses/mcp_server.py tests/test_degradation.py
git commit -m "feat(mcp): refuse to start when a configured ranking endpoint is unreachable"
```

---

### Task 5: Delete the cross-encoder

**Files:**
- Delete: `src/lenses/rerank.py`, `tests/test_rerank.py`
- Modify: `src/lenses/mcp_server.py:3-6` (docstring), `:32` (import), and the two `RerankError` arms left by Task 3
- Modify: `pyproject.toml:7-13` (dependencies)
- Modify: `.env.example` (the reranker block)

**Interfaces:**
- Consumes: nothing. Task 2 already made this path unreachable.
- Produces: `lenses.rerank` no longer exists; `RerankError` no longer exists.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_degradation.py`:

```python
def test_nothing_imports_sentence_transformers():
    """It was a required dependency for exactly one import, powering a second
    pass that scored 57/68 against 60/68 for having no second pass at all."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    hits = subprocess.run(
        [sys.executable, "-c",
         "import pathlib,sys;"
         "src=pathlib.Path(sys.argv[1])/'src';"
         "print([str(p) for p in src.rglob('*.py') "
         "if 'sentence_transformers' in p.read_text(encoding='utf-8')])",
         str(root)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert hits == "[]", f"still imported by {hits}"

    pyproject = (root / "pyproject.toml").read_text(encoding="utf-8")
    assert "sentence-transformers" not in pyproject
```

- [ ] **Step 2: Run it and watch it fail**

```bash
./.venv/Scripts/python.exe -m pytest tests/test_degradation.py::test_nothing_imports_sentence_transformers -p no:cacheprovider -v
```

Expected: FAIL — `still imported by ['.../src/lenses/rerank.py']`.

- [ ] **Step 3: Delete the module and its tests**

```bash
git rm src/lenses/rerank.py tests/test_rerank.py
```

- [ ] **Step 4: Remove every reference**

In `src/lenses/mcp_server.py`, delete line 32 (`from .rerank import ...`), and
delete the `except RerankError` arm from **both** `find_lenses` and
`find_lenses_batch`, leaving only the `EmbedError` arm in each. Update the
module docstring's second paragraph (lines 3-6):

```python
Thin on purpose. Ranking lives in `search`, the second pass in `llm_rerank`,
resolution in `resolve` — this module only turns their results into tool
responses, and `second_pass` below is the one place that knows whether a
second pass is configured at all.
```

In `pyproject.toml`, delete the `"sentence-transformers>=3.0",` line from
`dependencies`.

In `.env.example`, replace the whole reranker block (the commentary from
`# cross-encoder compares strings...` through `# reranker_api_key=sk-replace-me`)
with:

```
# The second pass that narrows the 20 dense candidates to the answer. All
# three settings or none: configure them and one instruction-tuned model is
# shown the whole numbered pool and asked which are best; leave them out and
# the dense ordering is the answer, which is a supported way to run this.
#
# Deliberately not llm_base_url above: that is the hosted model that
# decomposes skills and runs once per skill. This one runs on every search,
# so it wants to be local and free.
#
# Measured 2026-08-03 on 34 paired needs: 63/68 with this pass, 60/68 without.
# A cross-encoder second pass was tried and retired at 57/68 — below having no
# second pass at all. See README, "What is not settled".
# reranker_base_url=http://localhost:1234/v1
# reranker_model=gemma-4-e2b-it-qat
# reranker_api_key=sk-replace-me
```

- [ ] **Step 5: Run the tests**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -p no:cacheprovider -q
```

Expected: all green. The count drops by however many tests `test_rerank.py`
still held after Task 2 stripped its config half.

- [ ] **Step 6: Prove the dependency is really gone**

```bash
./.venv/Scripts/python.exe -c "import lenses.mcp_server, sys; print([m for m in sys.modules if 'torch' in m or 'sentence' in m])"
```

Expected: `[]`

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "refactor(rank): delete the cross-encoder second pass and its torch dependency"
```

---

### Task 6: Re-measure and correct the record

**Files:**
- Modify: `README.md` (the `reranker_kind` table and the *What is not settled* entries)
- Modify: `scripts/eval_retrieval.py` (module docstring)
- Modify: `src/lenses/llm_rerank.py` (module docstring)

**Interfaces:**
- Consumes: the final code from Tasks 1-5.
- Produces: nothing.

- [ ] **Step 1: Re-run the eval against the finished code**

```bash
./.venv/Scripts/python.exe scripts/eval_retrieval.py
```

Record `ranked`, `concrete phrasing` and `total across both axes`. These are the
figures the README must carry; do not reuse the ones from Task 1's gate, because
Tasks 2-5 changed which code path answers.

- [ ] **Step 2: Rewrite the README's second-pass table**

Replace the three-column table (the one headed `| | none | cross-encoder (default) | llm |`)
and the paragraph beginning **Read the first column before choosing** with
this, filling the four slots from Step 1:

```markdown
| | no second pass | the listwise pass |
|---|---|---|
| Sees | — | the whole numbered pool of 20 |
| Configuration | leave the three `reranker_*` settings out | set all three |
| Need-only phrasing | 33/34 | <ranked>/34 |
| **Project phrasing** | 27/34 | <concrete>/34 |
| **Total** | 60/68 | <total>/68 |
| Cost | 0 | 0.23 s/query |

Measured <date> on 34 paired needs; the ceiling is 67/68, which is what the
pool of 20 contains before either column touches it.

There is no `reranker_kind` and no default to get wrong. The three settings
are read together or not at all — setting one of them fails at load rather
than searching without the pass you asked for. Running without it is a
supported configuration, three points behind and asking nothing of you.
```

- [ ] **Step 3: Retire the cross-encoder in *What is not settled***

Replace the entry beginning **The default second pass scores below no second
pass** with its conclusion: retired 2026-08-03 at a final 57/68 against 60/68
for no second pass, and the dependency it required removed with it.

Update the entry beginning **Those numbers came from 17 pairs** so its figures
are Step 1's, and state the outcome of the prompt hypothesis — shipped with its
numbers, or rejected with its numbers, whichever Task 1 recorded.

- [ ] **Step 4: Correct the two module docstrings**

In `scripts/eval_retrieval.py`, update the paragraph beginning *Growing it paid
immediately* with the Step 1 figures, and the paragraph about the `intent` gate
being left red with whether it still is.

In `src/lenses/llm_rerank.py`, the module docstring still describes a
cross-encoder as the thing this pass is compared against. Rewrite its opening
so the comparison is against no second pass, keeping the 17-pair history
labelled as history.

- [ ] **Step 5: Verify nothing in the repo still names the removed settings**

```bash
grep -rn "reranker_kind\|RERANKER_KINDS\|DEFAULT_RERANKER\|cross-encoder" --include=*.py --include=*.toml --include=*.md --include=*.example . | grep -v "^./docs/superpowers/"
```

Expected: only the README's historical entries, each of which reads as history.
Anything under `docs/superpowers/` is a spec or plan and is a record of what was
decided — leave it alone.

- [ ] **Step 6: Run everything one last time**

```bash
./.venv/Scripts/python.exe -m pytest tests/ -p no:cacheprovider -q
```

- [ ] **Step 7: Commit**

```bash
git add README.md scripts/eval_retrieval.py src/lenses/llm_rerank.py
git commit -m "docs: re-measure the one remaining ranking path and retire the other"
```

---

## Done when

- `./.venv/Scripts/python.exe -m pytest tests/ -p no:cacheprovider -q` is green.
- `import lenses.mcp_server` pulls in neither torch nor sentence_transformers.
- `find_lenses` with a dead ranking endpoint returns results, `ranked_by: "dense"`, and a `warning`.
- `find_lenses_batch` with one dead intent returns every other intent's results.
- `startup()` refuses to start when three `reranker_*` settings name an endpoint that does not answer.
- The README's numbers were taken from the code as it stands at Task 6, not from this document.
