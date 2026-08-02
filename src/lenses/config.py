"""Configuration, loaded from .env and validated before anything runs.

Fails closed: a missing or unreadable setting stops the run rather than
falling back to a default that would quietly produce a different catalogue.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


#: Kept here rather than in `rerank` so that reading the configuration tells
#: you what will run without importing torch. Measured against two stronger
#: candidates and left in place — see .env.example for the numbers.
DEFAULT_RERANKER = "cross-encoder/ms-marco-MiniLM-L-12-v2"

#: How the candidate pool is narrowed to the answer. `cross-encoder` scores
#: each candidate against the query independently; `llm` shows one model the
#: whole numbered pool and takes back an ordering. Named explicitly rather
#: than inferred from the model string, because the two need different
#: settings and a typo should fail loudly instead of picking the other one.
RERANKER_KINDS = ("cross-encoder", "llm")


class ConfigError(RuntimeError):
    """A setting is missing or cannot be read."""


@dataclass(frozen=True)
class Endpoint:
    base_url: str
    model: str
    api_key: str


@dataclass(frozen=True)
class Config:
    llm: Endpoint
    embedder: Endpoint
    embedder_dim: int
    min_coverage: float
    #: Second model on the same endpoint, tried once when the first fails.
    #: Optional: absent means a failure is a failure.
    llm_fallback: Endpoint | None = None
    #: Where a manifest's relative source paths resolve from. Machine-specific,
    #: which is exactly why it lives here and not in the committed manifest.
    sources_root: Path = Path(".")
    #: Which second pass runs; one of RERANKER_KINDS.
    reranker_kind: str = "cross-encoder"
    #: The model that pass uses. For `cross-encoder` this is a local model
    #: name with no endpoint — it reads a (query, passage) pair in one forward
    #: pass, and no OpenAI-compatible server exposes that. For `llm` it is the
    #: model served at `reranker` below.
    reranker_model: str = DEFAULT_RERANKER
    #: Where the `llm` second pass is served. None for `cross-encoder`, which
    #: needs no endpoint at all. Kept separate from `llm` above: that one is
    #: the decomposition model and is typically a hosted provider, while this
    #: one runs on every search and wants to be local.
    reranker: Endpoint | None = None


def _require(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return value


def _require_number(name: str, cast):
    raw = _require(name)
    try:
        return cast(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def load_config(env_file: Path | None = None) -> Config:
    """Read .env into a validated Config.

    The path is explicit — `.env` beside the working directory unless told
    otherwise. python-dotenv's default discovery walks the call stack instead,
    which resolves differently depending on whether the package was installed
    editable or for real, and that is not a thing configuration should depend
    on. Values already in the environment win, so CI needs no file at all.
    """
    path = Path(env_file) if env_file else Path.cwd() / ".env"
    if path.is_file():
        load_dotenv(path, override=False)

    min_coverage = _require_number("min_coverage", float)
    if not 0.0 <= min_coverage <= 1.0:
        raise ConfigError(f"min_coverage must be between 0 and 1, got {min_coverage}")

    dim = _require_number("embedder_dim", int)
    if dim <= 0:
        raise ConfigError(f"embedder_dim must be positive, got {dim}")

    llm_base_url = _require("llm_base_url").rstrip("/")
    llm_api_key = _require("llm_api_key")
    fallback_model = os.environ.get("llm_model_fallback", "").strip()

    reranker_kind = os.environ.get("reranker_kind", "").strip() or "cross-encoder"
    if reranker_kind not in RERANKER_KINDS:
        raise ConfigError(
            f"reranker_kind must be one of {list(RERANKER_KINDS)}, got {reranker_kind!r}"
        )
    if reranker_kind == "llm":
        # Fail closed: an llm second pass with no endpoint would otherwise
        # fall back to the cross-encoder and quietly rank by the model nobody
        # configured, which is the kind of silence this project keeps out.
        reranker_endpoint = Endpoint(
            base_url=_require("reranker_base_url").rstrip("/"),
            model=_require("reranker_model"),
            api_key=_require("reranker_api_key"),
        )
        reranker_model = reranker_endpoint.model
    else:
        reranker_endpoint = None
        reranker_model = os.environ.get("reranker_model", "").strip() or DEFAULT_RERANKER

    return Config(
        llm=Endpoint(
            base_url=llm_base_url,
            model=_require("llm_model"),
            api_key=llm_api_key,
        ),
        llm_fallback=(
            Endpoint(base_url=llm_base_url, model=fallback_model, api_key=llm_api_key)
            if fallback_model
            else None
        ),
        embedder=Endpoint(
            base_url=_require("embedder_base_url").rstrip("/"),
            model=_require("embedder_model"),
            api_key=_require("embedder_api_key"),
        ),
        embedder_dim=dim,
        min_coverage=min_coverage,
        sources_root=Path(os.environ.get("sources_root", ".").strip() or "."),
        reranker_kind=reranker_kind,
        reranker_model=reranker_model,
        reranker=reranker_endpoint,
    )
