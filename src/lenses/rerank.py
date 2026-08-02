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

from .config import DEFAULT_RERANKER
from .search import Hit, SearchError

Scorer = Callable[[str, list[str]], list[float]]

#: Re-exported so callers that only want the default need not import config.
MODEL_NAME = DEFAULT_RERANKER

# There was a confidence gate here: below a raw logit of -8.0 the reranked
# ordering was discarded and the dense one served instead. It is gone, and the
# reason is worth keeping. Measured on 34 paired queries it fired on ten and
# changed the outcome on four — helping once, hurting three times. The signal
# was the category error: a cross-encoder's logit answers "is this passage
# good for this query", which is absolute relevance, and it was being read as
# "is my ordering trustworthy". Those come apart. In the worst case the
# reranker had the correct part at rank 1 while scoring -10.0, and the gate
# threw that ordering away for a dense one that had it at rank 10.

_models: dict[str, object] = {}


class RerankError(RuntimeError):
    """The reranker could not be loaded or could not score the candidates."""


def scorer_for(model_name: str) -> Scorer:
    """A scorer bound to one cross-encoder, loaded once per process per name.

    Cached by name rather than in a single global: the eval script compares
    models in one run, and reloading half a gigabyte of weights per query
    would make its latency column measure the loader instead of the model.
    """

    def score(intent: str, documents: list[str]) -> list[float]:
        try:
            if model_name not in _models:
                from sentence_transformers import CrossEncoder

                _models[model_name] = CrossEncoder(model_name)
            pairs = [(intent, document) for document in documents]
            return [float(value) for value in _models[model_name].predict(pairs)]
        except Exception as exc:
            # sentence-transformers/torch/huggingface_hub raise their own
            # exception types for a missing package, a failed download, or a
            # bad forward pass — collapsing them here gives find_lenses one
            # readable failure instead of a stack trace the client will swallow.
            raise RerankError(f"{model_name}: {exc}") from exc

    return score


def _model_scorer(intent: str, documents: list[str]) -> list[float]:
    """The default scorer: whatever `DEFAULT_RERANKER` names."""
    return scorer_for(MODEL_NAME)(intent, documents)


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
