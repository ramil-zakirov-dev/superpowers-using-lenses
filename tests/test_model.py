"""The catalogue file's shape."""

import yaml

from lenses.model import Part, SkillDoc, load_skill_doc


def document():
    return SkillDoc(
        id="wondelai/release-it",
        version="3e1fa0c91b2d",
        source={"url": "https://example.invalid", "path": "release-it/SKILL.md", "sha256": "3e1f"},
        kind="lens",
        summary="Stability patterns.",
        license="MIT",
        stacks=["any"],
        document_kinds=["spec"],
        parts=[
            Part(
                id="circuit-breaker",
                title="Circuit breaker",
                applies_to="Use when a dependency can be slow or down.",
                spans=[(128, 171)],
                preamble_spans=[(3, 14)],
                requires=["timeouts"],
                sha256="a71c",
            )
        ],
    )


def test_round_trips_through_yaml():
    parsed = load_skill_doc(document().to_yaml())
    assert parsed["id"] == "wondelai/release-it"
    assert parsed["parts"][0]["spans"] == [[128, 171]]
    assert parsed["parts"][0]["requires"] == ["timeouts"]


def test_spans_serialise_as_lists_not_tuples():
    """PyYAML renders a tuple as !!python/tuple, which safe_load will not read."""
    assert "!!python" not in document().to_yaml()


def test_empty_optional_fields_are_omitted():
    bare = Part(id="x", title="X", applies_to="Use when x.", spans=[(1, 2)], sha256="d")
    rendered = bare.to_dict()
    assert "requires" not in rendered
    assert "preamble_spans" not in rendered
    assert "kind" not in rendered


def test_the_pin_is_always_present():
    assert "sha256" in Part(id="x", title="X", applies_to="Use when x.", spans=[(1, 2)]).to_dict()


def test_unicode_survives_the_round_trip():
    doc = document()
    doc.summary = "Паттерны устойчивости."
    assert yaml.safe_load(doc.to_yaml())["summary"] == "Паттерны устойчивости."
