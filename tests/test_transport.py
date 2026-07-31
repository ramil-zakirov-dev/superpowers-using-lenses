"""A failing endpoint must say what the server said.

Written after a real run lost the message "No models loaded" behind a bare
`400 Bad Request`, which sent the reader looking for a fault in this code.
"""

import httpx
import pytest

from lenses.config import Endpoint
from lenses.decompose import DecompositionError, call_model
from lenses.embed import EmbedError, embed_texts

ENDPOINT = Endpoint(base_url="http://localhost:1234/v1", model="some-model", api_key="k")


class FakeResponse:
    def __init__(self, status_code, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        return self._payload


def respond(monkeypatch, response):
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: response)


def test_chat_error_body_reaches_the_caller(monkeypatch):
    respond(monkeypatch, FakeResponse(400, text='{"error":{"message":"No models loaded."}}'))
    with pytest.raises(DecompositionError, match="No models loaded"):
        call_model(ENDPOINT, "wondelai/release-it", ["one", "two"])


def test_chat_error_names_the_model_that_was_asked_for(monkeypatch):
    respond(monkeypatch, FakeResponse(404, text="not found"))
    with pytest.raises(DecompositionError, match="some-model"):
        call_model(ENDPOINT, "x/y", ["one"])


def test_non_json_content_is_reported_as_such(monkeypatch):
    respond(
        monkeypatch,
        FakeResponse(200, payload={"choices": [{"message": {"content": "I think that..."}}]}),
    )
    with pytest.raises(DecompositionError, match="did not return JSON"):
        call_model(ENDPOINT, "x/y", ["one"])


def test_fenced_json_is_accepted(monkeypatch):
    fenced = '```json\n{"kind": "lens", "parts": []}\n```'
    respond(monkeypatch, FakeResponse(200, payload={"choices": [{"message": {"content": fenced}}]}))
    assert call_model(ENDPOINT, "x/y", ["one"]) == {"kind": "lens", "parts": []}


def test_embed_error_body_reaches_the_caller(monkeypatch):
    respond(monkeypatch, FakeResponse(400, text="model not loaded"))
    with pytest.raises(EmbedError, match="model not loaded"):
        embed_texts(ENDPOINT, ["a"], expected_dim=384)


def test_dimension_mismatch_names_both_numbers(monkeypatch):
    respond(
        monkeypatch,
        FakeResponse(200, payload={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}),
    )
    with pytest.raises(EmbedError, match="returned 3-dimensional"):
        embed_texts(ENDPOINT, ["a"], expected_dim=384)


def test_matching_dimension_passes(monkeypatch):
    respond(
        monkeypatch,
        FakeResponse(200, payload={"data": [{"index": 0, "embedding": [0.1, 0.2, 0.3]}]}),
    )
    assert embed_texts(ENDPOINT, ["a"], expected_dim=3) == [[0.1, 0.2, 0.3]]


def test_no_texts_makes_no_request(monkeypatch):
    def explode(*args, **kwargs):
        raise AssertionError("embed_texts called the network for an empty batch")

    monkeypatch.setattr(httpx, "post", explode)
    assert embed_texts(ENDPOINT, [], expected_dim=384) == []
