"""The paid-run confirmation must count money, not skills.

It counted every non-import skill, catalogued or not. Forty-one skills with a
complete catalogue meant thirty-three "paid" ones and a refusal to run — on a
rebuild of the embedding index, which is local and costs nothing. The damage
is not the extra flag: it is that an operator who meets a confirmation on a
free run stops reading it, and it is no longer there on the run that spends.
"""

from pathlib import Path

import pytest

from lenses.ingest import CONFIRM_ABOVE, catalog_target, main, plan_mode
from lenses.vendored import VendoredSkill


def vendored(tmp_path, name, label="wondelai", version="deadbeef1234", imported=False):
    """A skill on disk, optionally one that ships its own parts."""
    directory = tmp_path / "skills" / label / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text("# x\n", encoding="utf-8")
    if imported:
        (directory / "rules").mkdir()
    return VendoredSkill(label=label, name=name, path=directory / "SKILL.md", version=version)


def catalogued(tmp_path, skill):
    target = catalog_target(skill, tmp_path / "catalog")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("id: x\n", encoding="utf-8")
    return target


def test_a_catalogued_skill_costs_nothing(tmp_path):
    skill = vendored(tmp_path, "clean-code")
    catalogued(tmp_path, skill)
    assert plan_mode(skill, tmp_path / "catalog", force=False) == "skip"


def test_force_puts_a_catalogued_skill_back_on_the_bill(tmp_path):
    skill = vendored(tmp_path, "clean-code")
    catalogued(tmp_path, skill)
    assert plan_mode(skill, tmp_path / "catalog", force=True) == "decompose"


def test_an_uncatalogued_skill_costs_a_call(tmp_path):
    skill = vendored(tmp_path, "clean-code")
    assert plan_mode(skill, tmp_path / "catalog", force=False) == "decompose"


def test_an_imported_skill_never_costs_a_call(tmp_path):
    """The author already cut it up; --force re-reads files, it does not buy."""
    skill = vendored(tmp_path, "coding-standards", label="ludo", imported=True)
    assert plan_mode(skill, tmp_path / "catalog", force=True) == "import"


def test_a_new_version_of_a_catalogued_skill_costs_a_call(tmp_path):
    """The catalogue is keyed by content hash, so an edit upstream is a miss."""
    old = vendored(tmp_path, "clean-code", version="aaaaaaaaaaaa")
    catalogued(tmp_path, old)
    new = vendored(tmp_path, "clean-code", version="bbbbbbbbbbbb")
    assert plan_mode(new, tmp_path / "catalog", force=False) == "decompose"


def corpus_of(tmp_path, count, catalogue_them):
    """`count` vendored skills, each with a sidecar so load_corpus finds them."""
    import yaml

    from lenses.spans import content_hash

    for index in range(count):
        name = f"skill-{index:03d}"
        directory = tmp_path / "skills" / "wondelai" / name
        directory.mkdir(parents=True, exist_ok=True)
        text = f"# skill {index}\n"
        (directory / "SKILL.md").write_text(text, encoding="utf-8")
        digest = content_hash(text)
        (directory / "skill.yaml").write_text(
            yaml.safe_dump({
                "name": name, "label": "wondelai", "version": digest[:12],
                "sha256": digest, "upstream": {"url": "", "path": f"{name}/SKILL.md"},
                "license": "MIT", "files": {},
            }),
            encoding="utf-8",
        )
        if catalogue_them:
            target = tmp_path / "catalog" / "wondelai" / name / f"{digest[:12]}.yaml"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("id: x\n", encoding="utf-8")


def run(tmp_path, *extra):
    return main([
        "--skills", str(tmp_path / "skills"),
        "--out", str(tmp_path / "catalog"),
        "--index", str(tmp_path / "index"),
        *extra,
    ])


@pytest.fixture
def configured(monkeypatch):
    """Enough environment for load_config; no endpoint is ever called."""
    for name, value in {
        "llm_base_url": "http://localhost:9/v1", "llm_model": "m", "llm_api_key": "k",
        "embedder_base_url": "http://localhost:9/v1",
        "embedder_model": "e", "embedder_api_key": "k",
        "embedder_dim": "384", "min_coverage": "0.5",
    }.items():
        monkeypatch.setenv(name, value)
    monkeypatch.chdir(Path(__file__).resolve().parent.parent)


def test_thirty_catalogued_skills_do_not_trip_the_gate(configured, tmp_path):
    """The regression: a free index rebuild demanded --yes."""
    assert CONFIRM_ABOVE < 30
    corpus_of(tmp_path, 30, catalogue_them=True)
    assert run(tmp_path, "--no-embed") == 0


def test_the_same_thirty_trip_it_under_force(configured, tmp_path, capsys):
    """--force is exactly the run the confirmation exists for."""
    corpus_of(tmp_path, 30, catalogue_them=True)
    assert run(tmp_path, "--force", "--no-embed") == 2
    assert "30 skills is a paid run" in capsys.readouterr().err


def test_thirty_uncatalogued_skills_trip_it(configured, tmp_path):
    corpus_of(tmp_path, 30, catalogue_them=False)
    assert run(tmp_path, "--no-embed") == 2


def test_the_dry_run_counts_what_the_gate_counts(configured, tmp_path, capsys):
    """A plan that disagrees with the run is worse than no plan."""
    corpus_of(tmp_path, 30, catalogue_them=True)
    assert run(tmp_path, "--dry-run") == 0
    assert "0 decomposed, 0 imported, 30 already catalogued" in capsys.readouterr().out
