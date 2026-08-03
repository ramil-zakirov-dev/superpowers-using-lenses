"""Configuration, loaded from .env and validated before anything runs.

Fails closed: a missing or unreadable setting stops the run rather than
falling back to a default that would quietly produce a different catalogue.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


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
    #: Where the listwise second pass is served. `None` is a supported
    #: configuration and not a missing one: it means the dense ordering is the
    #: answer. Kept separate from `llm` above — that one decomposes skills once
    #: each and is typically hosted, while this one runs on every search and
    #: wants to be local.
    reranker: Endpoint | None = None
    #: Where a need is classified against `catalog/taxonomy.yaml`. Same server
    #: and key as `reranker`, optionally a different model.
    #:
    #: Leave it unset. It exists because the two jobs looked like they wanted
    #: different models — classifying is 8/8 on a 4B and 2/5 on a 2B, and the
    #: 2B appeared to rank ten times faster for the same score. The second half
    #: of that did not survive measurement: this server spends ~2.1s of fixed
    #: overhead per request whatever the model, so a 2B and a 4B rank in 2.25s
    #: and 2.32s and splitting buys nothing. Kept because it costs nothing and
    #: the overhead may not be permanent.
    #:
    #: `None` exactly when `reranker` is None — one endpoint, so configuring
    #: neither is a choice and configuring only the classifier is a typo.
    classifier: Endpoint | None = None


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

    # A second model on the same server, for the classification call. Optional
    # because one model can do both jobs and until 2026-08-03 one did; named
    # separately because the measurements pull in opposite directions and a
    # single GPU can hold both of these at once.
    classifier_model = os.environ.get("classifier_model", "").strip()
    if classifier_model and reranker_endpoint is None:
        raise ConfigError(
            "classifier_model names a model on an endpoint that is not "
            "configured. Set the three reranker_* settings, or remove it."
        )
    classifier_endpoint = (
        Endpoint(base_url=reranker_endpoint.base_url,
                 model=classifier_model or reranker_endpoint.model,
                 api_key=reranker_endpoint.api_key)
        if reranker_endpoint is not None
        else None
    )

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
        reranker=reranker_endpoint,
        classifier=classifier_endpoint,
    )
