"""The second model is tried once, and the catalogue records which one answered.

The retried unit is call *and* validate. A real run lost `refactoring-patterns`
to a part with no `applies_to` — well-formed JSON, unusable content — while the
fallback sat unused because only transport failures reached it.
"""

import httpx
import pytest

from lenses.config import Endpoint
from lenses.decompose import DecompositionError, decompose_with_fallback

PRIMARY = Endpoint(base_url="https://example.invalid/v1", model="xiaomi/mimo-v2.5", api_key="k")
FALLBACK = Endpoint(base_url="https://example.invalid/v1", model="qwen/qwen3.6-flash", api_key="k")

GOOD = '{"kind": "lens", "summary": "s", "parts": [{"id": "a", "applies_to": "Use when a.", "spans": [[1, 2]]}]}'
NO_APPLIES_TO = '{"kind": "lens", "parts": [{"id": "a", "spans": [[1, 2]]}]}'
BAD_ID = '{"kind": "lens", "parts": [{"id": "Not A Slug", "applies_to": "Use when.", "spans": [[1, 2]]}]}'


class FakeResponse:
    def __init__(self, status_code, content=None, text=""):
        self.status_code = status_code
        self.text = text
        self._content = content

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def sequence(monkeypatch, responses):
    """Serve `responses` in order, recording the model each call asked for."""
    asked: list[str] = []

    def fake_post(url, **kwargs):
        asked.append(kwargs["json"]["model"])
        result = responses[len(asked) - 1]
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(httpx, "post", fake_post)
    return asked


def test_primary_success_never_touches_the_fallback(monkeypatch):
    asked = sequence(monkeypatch, [FakeResponse(200, GOOD)])
    payload, parts, model = decompose_with_fallback(PRIMARY, FALLBACK, "x/y", ["a", "b"])
    assert model == "xiaomi/mimo-v2.5"
    assert asked == ["xiaomi/mimo-v2.5"]
    assert payload["kind"] == "lens"
    assert [part.id for part in parts] == ["a"]


def test_http_failure_falls_back_and_reports_the_model_that_answered(monkeypatch):
    asked = sequence(monkeypatch, [FakeResponse(429, text="rate limited"), FakeResponse(200, GOOD)])
    _, _, model = decompose_with_fallback(PRIMARY, FALLBACK, "x/y", ["a"])
    assert model == "qwen/qwen3.6-flash"
    assert asked == ["xiaomi/mimo-v2.5", "qwen/qwen3.6-flash"]


def test_connection_error_also_falls_back(monkeypatch):
    sequence(monkeypatch, [httpx.ConnectError("refused"), FakeResponse(200, GOOD)])
    _, _, model = decompose_with_fallback(PRIMARY, FALLBACK, "x/y", ["a"])
    assert model == "qwen/qwen3.6-flash"


def test_unparseable_answer_falls_back(monkeypatch):
    sequence(monkeypatch, [FakeResponse(200, "I think that..."), FakeResponse(200, GOOD)])
    _, _, model = decompose_with_fallback(PRIMARY, FALLBACK, "x/y", ["a"])
    assert model == "qwen/qwen3.6-flash"


def test_missing_applies_to_falls_back(monkeypatch):
    """Valid JSON, unusable content — the failure that lost a real skill."""
    asked = sequence(monkeypatch, [FakeResponse(200, NO_APPLIES_TO), FakeResponse(200, GOOD)])
    _, _, model = decompose_with_fallback(PRIMARY, FALLBACK, "x/y", ["a"])
    assert model == "qwen/qwen3.6-flash"
    assert asked == ["xiaomi/mimo-v2.5", "qwen/qwen3.6-flash"]


def test_malformed_part_id_falls_back(monkeypatch):
    sequence(monkeypatch, [FakeResponse(200, BAD_ID), FakeResponse(200, GOOD)])
    _, _, model = decompose_with_fallback(PRIMARY, FALLBACK, "x/y", ["a"])
    assert model == "qwen/qwen3.6-flash"


def test_schema_failure_on_both_names_both_models(monkeypatch):
    sequence(monkeypatch, [FakeResponse(200, NO_APPLIES_TO), FakeResponse(200, BAD_ID)])
    with pytest.raises(DecompositionError) as caught:
        decompose_with_fallback(PRIMARY, FALLBACK, "x/y", ["a"])
    message = str(caught.value)
    assert "xiaomi/mimo-v2.5" in message and "qwen/qwen3.6-flash" in message
    assert "applies_to" in message


def test_both_failing_names_both_models(monkeypatch):
    sequence(monkeypatch, [FakeResponse(500, text="boom"), FakeResponse(503, text="also boom")])
    with pytest.raises(DecompositionError) as caught:
        decompose_with_fallback(PRIMARY, FALLBACK, "x/y", ["a"])
    message = str(caught.value)
    assert "boom" in message and "also boom" in message


def test_without_a_fallback_the_first_failure_propagates(monkeypatch):
    asked = sequence(monkeypatch, [FakeResponse(400, text="no models loaded")])
    with pytest.raises(DecompositionError, match="no models loaded"):
        decompose_with_fallback(PRIMARY, None, "x/y", ["a"])
    assert asked == ["xiaomi/mimo-v2.5"]


def test_without_a_fallback_a_schema_failure_also_propagates(monkeypatch):
    sequence(monkeypatch, [FakeResponse(200, NO_APPLIES_TO)])
    with pytest.raises(DecompositionError, match="applies_to"):
        decompose_with_fallback(PRIMARY, None, "x/y", ["a"])


def test_the_fallback_is_tried_once_not_repeatedly(monkeypatch):
    asked = sequence(monkeypatch, [FakeResponse(500, text="a"), FakeResponse(500, text="b")])
    with pytest.raises(DecompositionError):
        decompose_with_fallback(PRIMARY, FALLBACK, "x/y", ["a"])
    assert len(asked) == 2
