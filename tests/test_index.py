"""The index is derived from the whole catalogue, not from one run's output.

A real run truncated the index to nine rows against a ninety-four-part
catalogue, because re-running one skill rebuilt the file from that skill
alone. Nothing reported it; a search would simply have missed everything.
"""

import json

from lenses.ingest import catalog_parts, write_index
from lenses.model import Part, SkillDoc


def catalogue(tmp_path, skill_id, part_ids, kind="lens", document_kinds=()):
    document = SkillDoc(
        id=skill_id,
        version="deadbeef1234",
        source={"path": "SKILL.md", "sha256": "d"},
        kind=kind,
        summary="s",
        document_kinds=list(document_kinds),
        parts=[
            Part(id=pid, title=pid, applies_to=f"Use when {pid}.", spans=[(1, 2)], sha256=f"h-{pid}")
            for pid in part_ids
        ],
    )
    target = tmp_path / skill_id.replace("/", "_") / "deadbeef1234.yaml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(document.to_yaml(), encoding="utf-8")
    return target


def test_reads_every_part_of_every_skill(tmp_path):
    catalogue(tmp_path, "wondelai/release-it", ["a", "b"])
    catalogue(tmp_path, "ecc/api-design", ["c"])
    rows = catalog_parts(tmp_path)
    assert sorted(row["part_id"] for row in rows) == ["a", "b", "c"]


def test_a_row_carries_what_a_query_filters_on(tmp_path):
    catalogue(tmp_path, "wondelai/release-it", ["a"])
    row = catalog_parts(tmp_path)[0]
    assert row["skill_id"] == "wondelai/release-it"
    assert row["sha256"] == "h-a"
    assert row["applies_to"].startswith("Use when")
    assert row["kind"] == "lens"


def test_part_kind_overrides_the_skill_kind(tmp_path):
    document = SkillDoc(
        id="ecc/adr",
        version="v",
        source={},
        kind="pipeline",
        summary="s",
        parts=[
            Part(id="a", title="a", applies_to="Use when a.", spans=[(1, 2)], sha256="h", kind="lens"),
            Part(id="b", title="b", applies_to="Use when b.", spans=[(3, 4)], sha256="h2"),
        ],
    )
    target = tmp_path / "adr" / "v.yaml"
    target.parent.mkdir(parents=True)
    target.write_text(document.to_yaml(), encoding="utf-8")

    kinds = {row["part_id"]: row["kind"] for row in catalog_parts(tmp_path)}
    assert kinds == {"a": "lens", "b": "pipeline"}


def test_document_kinds_reach_the_index(tmp_path):
    """They are written by decomposition and were dropped here, so nothing
    downstream could report which stages the corpus actually covers."""
    catalogue(tmp_path, "wondelai/37signals-way", ["a"], document_kinds=("milestone", "plan"))
    assert catalog_parts(tmp_path)[0]["document_kinds"] == ["milestone", "plan"]


def test_an_unclassified_skill_carries_no_document_kinds(tmp_path):
    """Empty must stay empty: read as "covers every stage", it hides the gap."""
    catalogue(tmp_path, "ecc/api-design", ["a"])
    assert catalog_parts(tmp_path)[0]["document_kinds"] == []


def test_an_empty_catalogue_yields_nothing(tmp_path):
    assert catalog_parts(tmp_path) == []


def test_an_empty_title_falls_back_to_the_part_id(tmp_path):
    """`decompose` lets a model return an empty title, and a get-default only
    fires on an absent key. A row titled "" names nothing in a result list."""
    document = SkillDoc(
        id="ecc/adr",
        version="v",
        source={},
        kind="lens",
        summary="s",
        parts=[Part(id="capture-adr", title="", applies_to="Use when a.", spans=[(1, 2)], sha256="h")],
    )
    target = tmp_path / "adr" / "v.yaml"
    target.parent.mkdir(parents=True)
    target.write_text(document.to_yaml(), encoding="utf-8")

    assert catalog_parts(tmp_path)[0]["title"] == "capture-adr"


def test_index_is_one_json_object_per_line(tmp_path):
    rows = [{"part_id": "a", "vector": [0.1]}, {"part_id": "b", "vector": [0.2]}]
    target = write_index(tmp_path / "index", rows)
    lines = target.read_text(encoding="utf-8").strip().splitlines()
    assert [json.loads(line)["part_id"] for line in lines] == ["a", "b"]


def test_index_is_replaced_not_appended(tmp_path):
    write_index(tmp_path / "index", [{"part_id": "old"}])
    target = write_index(tmp_path / "index", [{"part_id": "new"}])
    assert target.read_text(encoding="utf-8").strip().count("\n") == 0
    assert "old" not in target.read_text(encoding="utf-8")
