"""Embeddings for the one field worth embedding.

We embed `applies_to`, not the part's text. A query is a statement of need
("I need grids and buttons"); `applies_to` is a statement of applicability.
Putting query and document in the same register does more for retrieval than
any choice of model. Embedding the instruction text instead pairs a need with
a directive — "use `<Grid gutter={16}>`" against "I need a grid" — and pays
distance for nothing.

This is the rule `writing-skills` states for a skill's `description`, applied
one level down to a part.
"""

from __future__ import annotations

import httpx

from .config import Endpoint


#: BGE models are trained asymmetrically: passages are embedded bare, queries
#: with this instruction in front. Omitting it costs ranking quietly rather
#: than loudly — measured on this corpus, a resilience query moved from rank
#: 10 to rank 2 once it was added. It lives in code so no caller can forget.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


class EmbedError(RuntimeError):
    """The embedding endpoint returned something unusable."""


def embed_texts(
    endpoint: Endpoint,
    texts: list[str],
    expected_dim: int,
    batch_size: int = 32,
    timeout: float = 120.0,
) -> list[list[float]]:
    """Embed in batches, asserting the dimension the caller expects.

    A silent dimension mismatch produces an index that every query misses, so
    it fails the run instead. `bge-base-en-v1.5` is natively 768 — the width of
    a vector, not the 512-token window it reads; if the configured value
    disagrees, one of the two is wrong and guessing which would be worse than
    stopping. `search.load_index` makes the matching check against the index
    already written, which is the half this one cannot see.
    """
    if not texts:
        return []

    vectors: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        response = httpx.post(
            f"{endpoint.base_url}/embeddings",
            headers={
                "Authorization": f"Bearer {endpoint.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": endpoint.model, "input": batch},
            timeout=timeout,
        )
        if response.status_code >= 400:
            raise EmbedError(
                f"{endpoint.base_url} returned {response.status_code} for model "
                f"{endpoint.model!r}: {response.text[:500]}"
            )
        payload = response.json()
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(batch):
            raise EmbedError(
                f"expected {len(batch)} embeddings, got {len(data) if isinstance(data, list) else data!r}"
            )
        for item in sorted(data, key=lambda row: row.get("index", 0)):
            vector = item.get("embedding")
            if not isinstance(vector, list) or not vector:
                raise EmbedError(f"embedding missing from {item!r}")
            if len(vector) != expected_dim:
                raise EmbedError(
                    f"{endpoint.model} returned {len(vector)}-dimensional vectors, "
                    f"but embedder_dim is {expected_dim}. Set embedder_dim to "
                    f"{len(vector)} in .env, or point at a different model — an "
                    f"index built on the wrong width answers nothing."
                )
            vectors.append([float(value) for value in vector])
    return vectors


def embed_query(endpoint: Endpoint, text: str, expected_dim: int) -> list[float]:
    """Embed a search query — prefixed, unlike the passages in the index."""
    return embed_texts(endpoint, [QUERY_PREFIX + text], expected_dim)[0]
