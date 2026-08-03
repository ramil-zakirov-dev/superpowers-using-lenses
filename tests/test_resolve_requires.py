"""Following `requires`: a part that cannot stand alone must not arrive alone.

The catalogue records, per part, the siblings that must travel with it when a
preamble is not enough. Handing over the fragment and staying silent is worse
than refusing it — the incompleteness is known and invisible.

Every fixture here is built under tmp_path. Nothing in this module reads the
real catalogue: the walk is graph behaviour, and the corpus is not the place to
discover whether a cycle terminates.
"""

import pytest

from lenses.model import Part, SkillDoc
from lenses.resolve import MAX_PARTS_PER_REF, resolve_all
from lenses.spans import content_hash, extract, split_lines

SKILL_ID = "ecc/fastapi-patterns"
VERSION = "328010fb5180"


def ref(part_id):
    return f"{SKILL_ID}#{part_id}@{VERSION}"


def build(tmp_path, edges):
    """One skill whose parts are `edges`' keys, each requiring its value.

    Parts are whole files rather than spans of SKILL.md: this module is about
    the graph, and span arithmetic across fifteen sections would be fixture
    noise that tests nothing.
    """
    skill_dir = tmp_path / "skills" / SKILL_ID
    (skill_dir / "parts").mkdir(parents=True)

    parts = []
    for part_id, needs in edges.items():
        body = f"---\ntitle: {part_id}\n---\n\nThe {part_id} section.\n"
        (skill_dir / "parts" / f"{part_id}.md").write_text(body, encoding="utf-8")
        spans = [(1, len(split_lines(body)))]
        parts.append(
            Part(
                id=part_id, title=part_id, applies_to=f"Use when {part_id}.",
                spans=spans, file=f"parts/{part_id}.md",
                sha256=content_hash(extract(split_lines(body), spans)),
                requires=list(needs),
            )
        )

    document = SkillDoc(
        id=SKILL_ID, version=VERSION,
        source={"url": "https://example.invalid", "path": "SKILL.md", "sha256": "x"},
        kind="reference", summary="s", license="MIT", parts=parts,
    )
    catalogue = tmp_path / "catalog" / "ecc" / "fastapi-patterns"
    catalogue.mkdir(parents=True)
    (catalogue / f"{VERSION}.yaml").write_text(document.to_yaml(), encoding="utf-8")
    return tmp_path / "catalog", tmp_path / "skills"


def refs_of(parts):
    return [part.ref for part in parts]


def test_a_standalone_part_comes_back_alone(tmp_path):
    catalog, skills = build(tmp_path, {"alpha": [], "beta": []})
    parts, errors = resolve_all([ref("alpha")], catalog, skills)
    assert refs_of(parts) == [ref("alpha")]
    assert parts[0].required_by == ()
    assert errors == []


def test_a_required_sibling_travels_with_the_part(tmp_path):
    catalog, skills = build(tmp_path, {"alpha": ["beta"], "beta": []})
    parts, errors = resolve_all([ref("alpha")], catalog, skills)
    assert refs_of(parts) == [ref("alpha"), ref("beta")]
    assert parts[1].required_by == (ref("alpha"),)
    assert errors == []


def test_the_closure_is_followed_past_the_first_hop(tmp_path):
    """Depth-1 would drop `gamma`. Measured on the real corpus, four parts in
    ecc/fastapi-patterns need exactly this — `async-httpx-pytest` would arrive
    without configuration, pydantic-schemas and transactional-service-layer."""
    catalog, skills = build(tmp_path, {"alpha": ["beta"], "beta": ["gamma"], "gamma": []})
    parts, errors = resolve_all([ref("alpha")], catalog, skills)
    assert refs_of(parts) == [ref("alpha"), ref("beta"), ref("gamma")]
    assert parts[2].required_by == (ref("beta"),)
    assert errors == []


def test_a_part_reached_twice_appears_once(tmp_path):
    catalog, skills = build(
        tmp_path, {"alpha": ["beta", "gamma"], "beta": ["gamma"], "gamma": []}
    )
    parts, errors = resolve_all([ref("alpha")], catalog, skills)
    assert refs_of(parts).count(ref("gamma")) == 1
    assert errors == []


def test_a_part_reached_twice_names_both_requirers(tmp_path):
    """Provenance is the whole reason the extra rows are legible at all."""
    catalog, skills = build(
        tmp_path, {"alpha": ["gamma"], "beta": ["gamma"], "gamma": []}
    )
    parts, _ = resolve_all([ref("alpha"), ref("beta")], catalog, skills)
    gamma = next(part for part in parts if part.ref == ref("gamma"))
    assert set(gamma.required_by) == {ref("alpha"), ref("beta")}


def test_an_explicitly_requested_part_is_never_marked_required(tmp_path):
    """Asked for is asked for, whichever order the walk reaches it in."""
    catalog, skills = build(tmp_path, {"alpha": ["beta"], "beta": []})
    parts, _ = resolve_all([ref("alpha"), ref("beta")], catalog, skills)
    beta = next(part for part in parts if part.ref == ref("beta"))
    assert beta.required_by == ()


def test_the_requested_parts_come_first_and_in_order(tmp_path):
    catalog, skills = build(
        tmp_path, {"alpha": ["gamma"], "beta": [], "gamma": []}
    )
    parts, _ = resolve_all([ref("beta"), ref("alpha")], catalog, skills)
    assert refs_of(parts) == [ref("beta"), ref("alpha"), ref("gamma")]


def test_a_cycle_terminates(tmp_path):
    """The corpus has no cycles today and `decompose` does not forbid them —
    it rejects unknown ids and self-reference only. Today's zero is what one
    model happened to write, so the guard must not depend on it."""
    catalog, skills = build(tmp_path, {"alpha": ["beta"], "beta": ["alpha"]})
    parts, errors = resolve_all([ref("alpha")], catalog, skills)
    assert sorted(refs_of(parts)) == [ref("alpha"), ref("beta")]
    assert errors == []


def test_a_broken_requirement_is_reported_and_does_not_hide_the_part(tmp_path):
    catalog, skills = build(tmp_path, {"alpha": ["ghost"]})
    parts, errors = resolve_all([ref("alpha")], catalog, skills)
    assert refs_of(parts) == [ref("alpha")]
    assert len(errors) == 1
    assert "ghost" in errors[0] and ref("alpha") in errors[0]


def test_the_cap_reports_what_it_dropped(tmp_path):
    """Silent truncation would recreate the exact disease this walk removes:
    an answer that is incomplete and does not say so."""
    siblings = [f"s{index}" for index in range(MAX_PARTS_PER_REF + 3)]
    catalog, skills = build(
        tmp_path, {"hub": siblings, **{name: [] for name in siblings}}
    )
    parts, errors = resolve_all([ref("hub")], catalog, skills)
    assert len(parts) == MAX_PARTS_PER_REF
    assert len(errors) == 1
    assert "dropped" in errors[0] and ref("hub") in errors[0]


def test_a_failed_request_does_not_suppress_a_good_one(tmp_path):
    catalog, skills = build(tmp_path, {"alpha": []})
    parts, errors = resolve_all([f"{SKILL_ID}#nope@{VERSION}", ref("alpha")], catalog, skills)
    assert refs_of(parts) == [ref("alpha")]
    assert len(errors) == 1


def test_no_references_is_not_an_error(tmp_path):
    catalog, skills = build(tmp_path, {"alpha": []})
    assert resolve_all([], catalog, skills) == ([], [])


# The same behaviour as an agent receives it. `get_lenses` owns no resolution
# logic; what these pin is the shape it hands back, because that shape is what
# an agent decides from when it writes its `lenses:` frontmatter.

@pytest.fixture
def served(tmp_path, monkeypatch):
    """`get_lenses` pointed at a tmp_path corpus, with startup short-circuited.

    `startup` loads a .env and an embedding index that resolution never reads —
    it goes to the catalogue and the vendored files directly. Filling both
    globals skips that rather than mocking a config and an index in pieces.
    """
    from lenses import mcp_server

    monkeypatch.setattr(mcp_server, "HOME", tmp_path)
    monkeypatch.setattr(mcp_server, "_config", object())
    monkeypatch.setattr(mcp_server, "_corpus", object())
    return mcp_server


def test_get_lenses_returns_required_parts_in_one_list(tmp_path, served):
    """One list, not a second key. A consumer that reads only `parts` must not
    lose the context — that is the failure this slice exists to remove."""
    build(tmp_path, {"alpha": ["beta"], "beta": []})
    answer = served.get_lenses([ref("alpha")])
    assert [part["ref"] for part in answer["parts"]] == [ref("alpha"), ref("beta")]
    assert answer["errors"] == []


def test_get_lenses_labels_where_a_part_came_from(tmp_path, served):
    build(tmp_path, {"alpha": ["beta"], "beta": []})
    alpha, beta = served.get_lenses([ref("alpha")])["parts"]
    assert alpha["required_by"] == [] and alpha["requires"] == ["beta"]
    assert beta["required_by"] == [ref("alpha")] and beta["requires"] == []


def test_get_lenses_still_reports_errors_alongside_parts(tmp_path, served):
    """The `{parts, errors}` contract is extended, not replaced."""
    build(tmp_path, {"alpha": ["ghost"]})
    answer = served.get_lenses([ref("alpha")])
    assert [part["ref"] for part in answer["parts"]] == [ref("alpha")]
    assert len(answer["errors"]) == 1 and "ghost" in answer["errors"][0]


def test_find_lenses_reports_requirements_without_expanding_them(monkeypatch):
    """Search returns candidates for a decision. Expanding bodies here would
    spend the caller's `limit` on parts they never chose — but knowing that a
    candidate is not standalone is part of choosing it."""
    from types import SimpleNamespace

    from lenses import mcp_server
    from lenses.search import Corpus, IndexedPart

    def indexed(part_id, requires=()):
        return IndexedPart(
            skill_id=SKILL_ID, version=VERSION, part_id=part_id, title=part_id,
            applies_to=f"Use when {part_id}.", kind="reference", sha256="h",
            vector=(1.0, 0.0), requires=tuple(requires),
        )

    monkeypatch.setattr(mcp_server, "embed_query", lambda *args, **kwargs: [1.0, 0.0])
    monkeypatch.setattr(
        mcp_server, "second_pass",
        lambda config: lambda intent, hits, limit: hits[:limit],
    )

    answer = mcp_server._find_one(
        "anything",
        config=SimpleNamespace(embedder=None, embedder_dim=2, reranker=None),
        corpus=Corpus([indexed("alpha", ["beta"]), indexed("beta")]),
        limit=1, kind=None, stack=None,
    )

    assert len(answer["results"]) == 1, "a requirement must not consume a result slot"
    assert answer["results"][0]["requires"] == ["beta"]
