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


def test_the_classifier_falls_back_to_the_ranking_model(env, monkeypatch):
    """One model can do both jobs, and until 2026-08-03 one did. Naming a
    second is an optimisation, not a requirement."""
    monkeypatch.setenv("reranker_base_url", "http://localhost:1234/v1")
    monkeypatch.setenv("reranker_model", "gemma-4-e2b-it-qat")
    monkeypatch.setenv("reranker_api_key", "k")
    config = load_config(env)
    assert config.classifier.model == "gemma-4-e2b-it-qat"
    assert config.classifier.base_url == config.reranker.base_url


def test_a_named_classifier_model_shares_the_endpoint(env, monkeypatch):
    """Two model names on one server. Nothing needs this today - the ranking
    latency that motivated it was ~2.1s of per-request overhead rather than
    the model - but the setting is what a future measurement would use."""
    monkeypatch.setenv("reranker_base_url", "http://localhost:1234/v1")
    monkeypatch.setenv("reranker_model", "gemma-4-e2b-it-qat")
    monkeypatch.setenv("reranker_api_key", "k")
    monkeypatch.setenv("classifier_model", "gemma-4-e4b-it-qat")
    config = load_config(env)
    assert config.reranker.model == "gemma-4-e2b-it-qat"
    assert config.classifier.model == "gemma-4-e4b-it-qat"
    assert config.classifier.api_key == config.reranker.api_key


def test_a_classifier_model_without_a_ranking_endpoint_is_refused(env, monkeypatch):
    """It names a model on an endpoint that was never configured. Loading it
    as if it meant something would search with a classifier and no ranker."""
    monkeypatch.setenv("classifier_model", "gemma-4-e4b-it-qat")
    with pytest.raises(ConfigError, match="classifier_model"):
        load_config(env)


def test_no_ranking_endpoint_means_no_classifier(env):
    assert load_config(env).classifier is None


def test_reranker_kind_is_gone(env, monkeypatch):
    """A leftover setting in someone's .env must not silently do nothing that
    looks like something. It is simply not read."""
    monkeypatch.setenv("reranker_kind", "cross-encoder")
    config = load_config(env)
    assert not hasattr(config, "reranker_kind")
    assert config.reranker is None
