"""Second-pass ranking: score the dense candidate pool against the literal
query, not just its vector.

A bi-encoder embeds the query and every part independently, so it can only
ever compare two vectors after the fact. A cross-encoder reads the query and
one candidate together in a single forward pass, which is what lets it tell
"on-topic" apart from "shares vocabulary with the topic" — the failure mode
`search.rank` cannot see because by the time it runs, the query and the part
are already two unrelated points in space.

The model loads once per process, lazily — this module can be imported, and
`rerank` called with a fake `score`, without ever pulling in torch.
"""

from __future__ import annotations

from typing import Callable

from .search import Hit, SearchError

Scorer = Callable[[str, list[str]], list[float]]

MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-12-v2"

#: Below this raw logit, the reranker is not discriminating — not "confident
#: in the wrong answer" but scoring the whole pool in a narrow, uniformly bad
#: band, which is what an out-of-distribution query looks like to this model.
#: Calibrated on 8 cases (2 below, 6 clear of it by >2 points either way);
#: a starting point, not a constant to trust blindly — see
#: scripts/eval_retrieval.py.
CONFIDENCE_THRESHOLD = -8.0

_model = None


class RerankError(RuntimeError):
    """The reranker could not be loaded or could not score the candidates."""


def _model_scorer(intent: str, documents: list[str]) -> list[float]:
    global _model
    try:
        if _model is None:
            from sentence_transformers import CrossEncoder

            _model = CrossEncoder(MODEL_NAME)
        pairs = [(intent, document) for document in documents]
        return [float(value) for value in _model.predict(pairs)]
    except Exception as exc:
        # sentence-transformers/torch/huggingface_hub raise their own
        # exception types for a missing package, a failed download, or a
        # bad forward pass — collapsing them here gives find_lenses one
        # readable failure instead of a stack trace the client will swallow.
        raise RerankError(f"{MODEL_NAME}: {exc}") from exc


def rerank(intent: str, hits: list[Hit], top_n: int, score: Scorer = _model_scorer) -> list[Hit]:
    """Re-score `hits` against `intent` and keep the best `top_n`.

    Scores `applies_to` — the same field the dense pass and the index embed
    — not the part's title or id, and not its body: the pool has already
    been narrowed by `search.rank`, so this is a precision pass over that
    pool, not a second retrieval over the whole corpus.
    """
    if top_n < 1:
        raise SearchError("top_n must be at least 1")
    if not hits:
        return []

    documents = [hit.part.applies_to for hit in hits]
    scores = score(intent, documents)
    reordered = sorted(zip(scores, hits), key=lambda pair: -pair[0])
    return [Hit(score=value, part=matched.part) for value, matched in reordered[:top_n]]


def confident(hits: list[Hit], threshold: float = CONFIDENCE_THRESHOLD) -> bool:
    """Whether the top-ranked hit clears the reranker's own confidence bar.

    `hits` is assumed sorted best-first — the output of `rerank`, not an
    arbitrary list. Only the top score is checked: a query the reranker has
    an opinion about looks like one good score, not an average of six
    mediocre ones.
    """
    return bool(hits) and hits[0].score >= threshold
