"""Resolving a citation to text, and refusing when the text has moved."""

import pytest

from lenses.model import Part, SkillDoc
from lenses.resolve import resolve
from lenses.search import SearchError
from lenses.spans import content_hash, extract, split_lines

SKILL = """\
---
name: release-it
---

# Release It

Overview line.

## Circuit breaker

Trip on repeated failure, fail fast, page on staying open.
"""

RULE = """\
---
title: No Mutable Defaults
---

Never use mutable defaults.
"""


def build(tmp_path, *, file_part=False, requires=()):
    skills = tmp_path / "skills" / "wondelai" / "release-it"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text(SKILL, encoding="utf-8")

    lines = split_lines(SKILL)
    if file_part:
        (skills / "rules").mkdir()
        (skills / "rules" / "r.md").write_text(RULE, encoding="utf-8")
        part = Part(id="circuit-breaker", title="Circuit breaker",
                    applies_to="Use when a dependency fails.", spans=[(1, len(split_lines(RULE)))],
                    file="rules/r.md", sha256=content_hash(RULE), requires=list(requires))
    else:
        # Normalised lines: 1-3 frontmatter, 5 heading, 7 overview,
        # 9 section heading, 11 the section's one sentence.
        preamble, spans = [(5, 7)], [(9, 11)]
        part = Part(id="circuit-breaker", title="Circuit breaker",
                    applies_to="Use when a dependency fails.", spans=spans,
                    preamble_spans=preamble, requires=list(requires),
                    sha256=content_hash(extract(lines, [*preamble, *spans])))

    document = SkillDoc(
        id="wondelai/release-it", version="abcdef123456",
        source={"url": "https://example.invalid", "path": "release-it/SKILL.md", "sha256": "x"},
        kind="lens", summary="s", license="MIT", parts=[part],
    )
    catalogue = tmp_path / "catalog" / "wondelai" / "release-it"
    catalogue.mkdir(parents=True)
    (catalogue / "abcdef123456.yaml").write_text(document.to_yaml(), encoding="utf-8")
    return tmp_path / "catalog", tmp_path / "skills"


REF = "wondelai/release-it#circuit-breaker@abcdef123456"


def test_resolves_a_span_of_the_main_file(tmp_path):
    catalog, skills = build(tmp_path)
    found = resolve(REF, catalog, skills)
    assert "fail fast" in found.text               # the section itself
    assert "Overview line." in found.text          # its preamble travels with it
    assert "name: release-it" not in found.text    # frontmatter does not


def test_resolves_a_whole_file_part(tmp_path):
    catalog, skills = build(tmp_path, file_part=True)
    found = resolve(REF, catalog, skills)
    assert found.text.strip().endswith("Never use mutable defaults.")
    assert found.file == "wondelai/release-it/rules/r.md"


def test_carries_licence_and_provenance(tmp_path):
    catalog, skills = build(tmp_path)
    found = resolve(REF, catalog, skills)
    assert found.license == "MIT"
    assert found.url == "https://example.invalid"


def test_a_part_exposes_what_it_requires(tmp_path):
    """The catalogue records that a fragment is not self-sufficient. Discarding
    that at resolution is why the field has never done anything."""
    catalog, skills = build(tmp_path, requires=["timeouts"])
    assert resolve(REF, catalog, skills).requires == ("timeouts",)


def test_a_part_with_no_requirements_exposes_an_empty_tuple(tmp_path):
    """Not None — a caller should never have to ask which falsy value it got."""
    catalog, skills = build(tmp_path)
    assert resolve(REF, catalog, skills).requires == ()


def test_a_resolved_part_is_not_marked_required_by_default(tmp_path):
    """`resolve` answers about one reference and knows nothing about why it was
    asked for. Only the caller that pulled a part in can say that."""
    catalog, skills = build(tmp_path, requires=["timeouts"])
    assert resolve(REF, catalog, skills).required_by == ()


def test_an_edited_vendored_file_is_refused(tmp_path):
    """A citation that resolves to changed text is worse than one that fails."""
    catalog, skills = build(tmp_path)
    target = skills / "wondelai" / "release-it" / "SKILL.md"
    target.write_text(SKILL.replace("fail fast", "fail slowly"), encoding="utf-8")
    with pytest.raises(SearchError, match="does not match its pin"):
        resolve(REF, catalog, skills)


def test_an_edit_outside_the_cited_lines_leaves_the_part_valid(tmp_path):
    """The pin covers the part, not the file — other sections are not its business.

    Whole-file integrity is `vendor.py --check`; the two layers are separate
    on purpose, so one skill's edit does not invalidate every citation in it.
    """
    catalog, skills = build(tmp_path)
    target = skills / "wondelai" / "release-it" / "SKILL.md"
    target.write_text(SKILL.replace("name: release-it", "name: release-it-v2"), encoding="utf-8")
    assert "fail fast" in resolve(REF, catalog, skills).text


def test_a_missing_catalogue_entry_names_the_path(tmp_path):
    catalog, skills = build(tmp_path)
    with pytest.raises(SearchError, match="no catalogue entry"):
        resolve("wondelai/release-it#circuit-breaker@000000000000", catalog, skills)


def test_an_unknown_part_lists_what_is_there(tmp_path):
    catalog, skills = build(tmp_path)
    with pytest.raises(SearchError, match="circuit-breaker"):
        resolve("wondelai/release-it#nope@abcdef123456", catalog, skills)


def test_a_missing_vendored_file_is_reported(tmp_path):
    catalog, skills = build(tmp_path)
    (skills / "wondelai" / "release-it" / "SKILL.md").unlink()
    with pytest.raises(SearchError, match="vendored file missing"):
        resolve(REF, catalog, skills)


def test_a_malformed_reference_is_refused(tmp_path):
    catalog, skills = build(tmp_path)
    with pytest.raises(SearchError, match="not a part reference"):
        resolve("wondelai/release-it", catalog, skills)
