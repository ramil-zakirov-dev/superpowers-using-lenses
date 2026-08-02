"""Skills whose parts are already files.

wispbit ships one rule per file: `SKILL.md` is a 63-line contents page and the
substance sits in `rules/*.md`. Decomposing that would cut up the contents
page, lose every rule, and bill for it.
"""

import pytest
import yaml

from lenses.importer import (
    applies_to,
    as_tags,
    check_imported,
    has_parts_on_disk,
    import_skill,
    parse_frontmatter,
    read_rules,
    slugify,
)
from lenses.spans import content_hash
from lenses.vendored import VendoredSkill

RULE = """\
---
title: No Mutable Defaults in Function Parameters
impact: CRITICAL
impactDescription: Prevents shared mutable state bugs where defaults are reused
tags: mutable-defaults, function-parameters, shared-state
---

## No Mutable Defaults

Never use mutable defaults in function parameters.
"""

MAIN = """\
---
name: python-expert
description: Python best practices for production-grade code.
license: MIT
---

# Python Expert

Read individual rule files.
"""


def build(tmp_path, rules: dict[str, str] | None = None, main: str = MAIN):
    directory = tmp_path / "wispbit" / "python-expert"
    (directory / "rules").mkdir(parents=True)
    (directory / "SKILL.md").write_text(main, encoding="utf-8")
    for name, text in (rules if rules is not None else {"no-mutable-defaults.md": RULE}).items():
        (directory / "rules" / name).write_text(text, encoding="utf-8")
    return VendoredSkill(
        label="wispbit",
        name="python-expert",
        path=directory / "SKILL.md",
        version=content_hash(main)[:12],
        url="https://example.invalid",
        license="MIT",
    )


def test_a_skill_with_rules_is_detected(tmp_path):
    skill = build(tmp_path)
    assert has_parts_on_disk(skill.path.parent) is True


def test_a_skill_without_rules_is_not(tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "SKILL.md").write_text("# x", encoding="utf-8")
    assert has_parts_on_disk(plain) is False


def test_frontmatter_is_split_from_the_body():
    frontmatter, body = parse_frontmatter(RULE)
    assert frontmatter["impact"] == "CRITICAL"
    assert body.lstrip().startswith("## No Mutable Defaults")


def test_a_file_without_frontmatter_is_all_body():
    frontmatter, body = parse_frontmatter("# Just a heading\n")
    assert frontmatter == {}
    assert body == "# Just a heading\n"


def test_applies_to_is_the_authors_own_words():
    frontmatter, _ = parse_frontmatter(RULE)
    assert applies_to(frontmatter, "fallback") == (
        "No Mutable Defaults in Function Parameters — "
        "Prevents shared mutable state bugs where defaults are reused."
    )


def test_applies_to_falls_back_to_the_title_alone():
    assert applies_to({"title": "Avoid Panic"}, "x") == "Avoid Panic."


def test_applies_to_uses_the_filename_when_there_is_no_title():
    assert applies_to({}, "avoid-panic") == "avoid-panic."


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a, b, c", ["a", "b", "c"]),
        (["a", "b"], ["a", "b"]),
        (None, []),
        ("", []),
    ],
)
def test_tags_accept_both_shapes(raw, expected):
    assert as_tags(raw) == expected


def test_slugify_makes_a_part_id():
    assert slugify("No_Mutable Defaults!") == "no-mutable-defaults"


def test_rules_are_read_in_a_stable_order(tmp_path):
    skill = build(tmp_path, {"b.md": RULE, "a.md": RULE, "c.md": RULE})
    assert [rule.relative for rule in read_rules(skill.path.parent)] == [
        "rules/a.md", "rules/b.md", "rules/c.md",
    ]


def test_leading_underscore_files_are_not_rules(tmp_path):
    """Some upstreams keep authoring scaffolding (a template, a section index)
    inside rules/ alongside the real content. It carries no applies_to worth
    indexing — `_template.md` even has *placeholder* frontmatter that reads
    like a real part until you look at what it says. The leading underscore
    is the upstream's own "not content" convention; honour it rather than
    catalogue a part nobody can use."""
    skill = build(tmp_path, {
        "no-mutable-defaults.md": RULE,
        "_template.md": RULE,
        "_sections.md": "# Section Definitions\n\nJust an index, no frontmatter.\n",
    })
    assert [rule.relative for rule in read_rules(skill.path.parent)] == [
        "rules/no-mutable-defaults.md",
    ]


def test_import_makes_one_part_per_file(tmp_path):
    skill = build(tmp_path, {"no-mutable-defaults.md": RULE, "avoid-panic.md": RULE})
    document, problems = import_skill(skill)
    assert problems == []
    assert sorted(part.id for part in document.parts) == ["avoid-panic", "no-mutable-defaults"]


def test_a_part_names_its_file_and_spans_the_whole_of_it(tmp_path):
    document, _ = import_skill(build(tmp_path))
    part = document.parts[0]
    assert part.file == "rules/no-mutable-defaults.md"
    assert part.spans == [(1, len(RULE.rstrip("\n").splitlines()))]


def test_the_pin_hashes_the_rule_file_not_the_skill(tmp_path):
    document, _ = import_skill(build(tmp_path))
    assert document.parts[0].sha256 == content_hash(RULE)


def test_author_tags_survive(tmp_path):
    document, _ = import_skill(build(tmp_path))
    assert document.parts[0].tags == [
        "mutable-defaults", "function-parameters", "shared-state",
    ]


def test_provenance_says_the_author_drew_the_boundaries(tmp_path):
    document, _ = import_skill(build(tmp_path))
    assert document.decomposed_by == "author"


def test_summary_comes_from_the_main_file(tmp_path):
    document, _ = import_skill(build(tmp_path))
    assert document.summary == "Python best practices for production-grade code."


def test_classifiers_are_left_empty_rather_than_guessed(tmp_path):
    """A stack inferred from a directory name is an invented classifier."""
    document, _ = import_skill(build(tmp_path))
    assert document.stacks == [] and document.document_kinds == []


def test_an_empty_rule_is_reported_and_skipped(tmp_path):
    skill = build(tmp_path, {"good.md": RULE, "empty.md": "---\ntitle: X\n---\n"})
    document, problems = import_skill(skill)
    assert [part.id for part in document.parts] == ["good"]
    assert any("has no body" in problem for problem in problems)


def test_a_skill_with_no_rule_files_is_reported(tmp_path):
    skill = build(tmp_path, {})
    document, problems = import_skill(skill)
    assert document.parts == []
    assert any("no part-files" in problem for problem in problems)


def test_gates_pass_on_a_well_formed_import(tmp_path):
    document, _ = import_skill(build(tmp_path))
    assert check_imported(document.parts) == []


def test_gates_reject_an_empty_import():
    assert "no parts" in check_imported([])


def test_the_catalogue_round_trips(tmp_path):
    document, _ = import_skill(build(tmp_path))
    parsed = yaml.safe_load(document.to_yaml())
    part = parsed["parts"][0]
    assert part["file"] == "rules/no-mutable-defaults.md"
    assert part["tags"][0] == "mutable-defaults"
