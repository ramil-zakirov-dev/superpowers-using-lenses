"""Classifying a need against the catalogue's own subject areas.

The model is a fake here. What needs testing is not whether gemma classifies
well — the probes recorded in the taxonomy file answer that against the live
endpoint — but that a reply which is empty, unparseable, cased oddly or names
a label nobody defined still produces a decision the caller can act on.
"""

from pathlib import Path

import pytest

from lenses.taxonomy import (
    Taxonomy,
    TaxonomyError,
    build_prompt,
    classify,
    load_taxonomy,
)

FIXTURE = """
boundary: >-
  About software. Answer NONE for anything else.
labels:
- id: testing-practice
  scope: writing automated tests
  excludes: research with users
  skills: [lab/pytest, lab/unittest]
- id: data-and-storage
  scope: schemas and indexes
  skills: [lab/postgres]
"""


@pytest.fixture
def taxonomy(tmp_path) -> Taxonomy:
    path = tmp_path / "taxonomy.yaml"
    path.write_text(FIXTURE, encoding="utf-8")
    return load_taxonomy(path)


def replying(answer):
    return lambda system, user: answer


def test_a_label_carries_its_scope_and_its_exclusions(taxonomy):
    testing = taxonomy.labels[0]
    assert testing.id == "testing-practice"
    assert testing.scope == "writing automated tests"
    assert testing.excludes == "research with users"


def test_a_label_without_exclusions_loads(taxonomy):
    """Not every subject area has a neighbour it is confused with."""
    assert taxonomy.labels[1].excludes == ""


def test_the_prompt_states_the_boundary_and_every_label(taxonomy):
    system, user = build_prompt(taxonomy, "a need")
    assert "Answer NONE" in system
    assert "testing-practice" in system and "data-and-storage" in system
    assert "research with users" in system, "an exclusion is the mechanism, not a note"
    assert "a need" in user


def test_a_named_label_is_returned(taxonomy):
    assert classify("a need", taxonomy, replying("testing-practice")) == "testing-practice"


def test_none_means_the_catalogue_does_not_cover_it(taxonomy):
    assert classify("a need", taxonomy, replying("NONE")) is None


@pytest.mark.parametrize("answer", [
    "  testing-practice  ",
    "TESTING-PRACTICE",
    "- testing-practice",
    "**testing-practice**",
    "testing-practice\nBecause the need is about tests.",
    "Label: testing-practice",
])
def test_the_reply_is_read_through_the_model_s_decorations(taxonomy, answer):
    """Every form here came off a live model asked for a bare label."""
    assert classify("a need", taxonomy, replying(answer)) == "testing-practice"


@pytest.mark.parametrize("answer", ["none", "NONE.", "**NONE**", "Label: NONE"])
def test_abstention_is_read_through_the_same_decorations(taxonomy, answer):
    assert classify("a need", taxonomy, replying(answer)) is None


@pytest.mark.parametrize("answer", ["", "   ", "I am not sure", "category-7"])
def test_an_unusable_reply_is_not_read_as_abstention(taxonomy, answer):
    """Abstention is a claim about the corpus. A model that failed to answer
    has made no claim, and reporting one would put a warning on a good result.
    """
    assert classify("a need", taxonomy, replying(answer)) == ""


def test_a_taxonomy_naming_no_labels_is_refused(tmp_path):
    path = tmp_path / "taxonomy.yaml"
    path.write_text("boundary: about software\nlabels: []\n", encoding="utf-8")
    with pytest.raises(TaxonomyError, match="no labels"):
        load_taxonomy(path)


def test_a_missing_taxonomy_is_refused(tmp_path):
    with pytest.raises(TaxonomyError, match="taxonomy"):
        load_taxonomy(tmp_path / "absent.yaml")


def test_the_shipped_taxonomy_covers_every_skill_in_the_catalogue():
    """A taxonomy that does not cover the corpus cannot mean what abstention
    needs it to mean: `NONE` says the catalogue has nothing, so a skill with
    no label would make that a lie."""
    import yaml

    root = Path(__file__).resolve().parent.parent
    taxonomy = load_taxonomy(root / "catalog" / "taxonomy.yaml")
    labelled = {skill for label in taxonomy.labels for skill in label.skills}
    catalogued = {
        yaml.safe_load(f.read_text(encoding="utf-8"))["id"]
        for f in (root / "catalog").rglob("*.yaml")
        if f.name != "taxonomy.yaml"
    }
    assert catalogued - labelled == set(), "skills with no subject area"
    assert labelled - catalogued == set(), "labels naming skills that do not exist"
