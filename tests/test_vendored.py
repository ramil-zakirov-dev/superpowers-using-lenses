"""The verification point between vendoring and decomposing.

`skills/` holds quotations. If one has been edited, the decomposition that
cites its hash is a claim about text that no longer exists — so an edited file
is refused rather than decomposed around.
"""

import pytest
import yaml

from lenses.spans import content_hash
from lenses.vendored import VendorError, load_corpus, load_skill

BODY = "---\nname: release-it\n---\n\n# Release It\n\nStability patterns.\n"


def vendor(root, label="wondelai", name="release-it", body=BODY, **overrides):
    directory = root / label / name
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "SKILL.md").write_text(body, encoding="utf-8")
    sidecar = {
        "name": name,
        "label": label,
        "version": content_hash(body)[:12],
        "sha256": content_hash(body),
        "upstream": {"url": "https://example.invalid", "path": f"{name}/SKILL.md"},
        "license": "MIT",
        "files": {"SKILL.md": "unused-by-these-tests"},
    }
    sidecar.update(overrides)
    (directory / "skill.yaml").write_text(yaml.safe_dump(sidecar), encoding="utf-8")
    return directory


def test_reads_provenance_from_the_sidecar(tmp_path):
    skill = load_skill(vendor(tmp_path))
    assert skill.id == "wondelai/release-it"
    assert skill.license == "MIT"
    assert skill.url == "https://example.invalid"


def test_relative_path_is_what_the_catalogue_records(tmp_path):
    assert load_skill(vendor(tmp_path)).relative_path == "release-it/SKILL.md"


def test_an_edited_skill_is_refused(tmp_path):
    directory = vendor(tmp_path)
    (directory / "SKILL.md").write_text(BODY + "\nsomeone added this\n", encoding="utf-8")
    with pytest.raises(VendorError, match="does not match its sidecar"):
        load_skill(directory)


def test_line_endings_alone_do_not_count_as_editing(tmp_path):
    """A Windows checkout must not invalidate a corpus vendored on Linux."""
    directory = vendor(tmp_path)
    (directory / "SKILL.md").write_bytes(BODY.replace("\n", "\r\n").encode("utf-8"))
    assert load_skill(directory).name == "release-it"


def test_a_missing_sidecar_is_refused(tmp_path):
    directory = vendor(tmp_path)
    (directory / "skill.yaml").unlink()
    with pytest.raises(VendorError, match="no skill.yaml"):
        load_skill(directory)


def test_a_missing_main_file_is_refused(tmp_path):
    directory = vendor(tmp_path)
    (directory / "SKILL.md").unlink()
    with pytest.raises(VendorError, match="SKILL.md is missing"):
        load_skill(directory)


def test_corpus_collects_every_skill(tmp_path):
    vendor(tmp_path, name="release-it")
    vendor(tmp_path, name="clean-code", body="# Clean Code\n")
    vendor(tmp_path, label="ecc", name="postgres-patterns", body="# Postgres\n")
    corpus, problems = load_corpus(tmp_path)
    assert sorted(skill.id for skill in corpus) == [
        "ecc/postgres-patterns",
        "wondelai/clean-code",
        "wondelai/release-it",
    ]
    assert problems == []


def test_corpus_reports_a_broken_skill_without_losing_the_rest(tmp_path):
    vendor(tmp_path, name="release-it")
    broken = vendor(tmp_path, name="clean-code", body="# Clean Code\n")
    (broken / "SKILL.md").write_text("# Edited\n", encoding="utf-8")

    corpus, problems = load_corpus(tmp_path)
    assert [skill.name for skill in corpus] == ["release-it"]
    assert len(problems) == 1 and "clean-code" in problems[0]


def test_an_empty_corpus_is_not_an_error(tmp_path):
    assert load_corpus(tmp_path) == ([], [])
