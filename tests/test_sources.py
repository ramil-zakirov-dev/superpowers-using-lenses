"""The manifest: validation, path resolution, and skill selection."""

from pathlib import Path

import pytest

from lenses.sources import Source, SourceError, load_sources, parse_sources, resolve_path, selects

ROOT = Path("/repos")


def manifest(**overrides):
    entry = {"label": "ecc", "path": "affan-m-ecc/skills"}
    entry.update(overrides)
    return {"sources": [entry]}


def test_minimal_entry_gets_sane_defaults():
    source = parse_sources(manifest(), ROOT)[0]
    assert source.label == "ecc"
    assert source.license == "unknown"
    assert source.include == () and source.exclude == ()
    assert source.enabled is True


def test_relative_path_resolves_under_the_root():
    assert resolve_path("affan-m-ecc/skills", ROOT).as_posix().endswith("repos/affan-m-ecc/skills")


def test_absolute_path_ignores_the_root():
    absolute = Path("/elsewhere/skills").absolute()
    assert resolve_path(str(absolute), ROOT) == absolute


def test_tilde_expands_and_ignores_the_root():
    resolved = resolve_path("~/.claude/skills", ROOT)
    assert resolved.is_absolute()
    assert "repos" not in resolved.as_posix()


def test_empty_manifest_is_refused():
    with pytest.raises(SourceError, match="non-empty"):
        parse_sources({"sources": []}, ROOT)


def test_duplicate_labels_are_refused():
    data = {"sources": [{"label": "a", "path": "x"}, {"label": "a", "path": "y"}]}
    with pytest.raises(SourceError, match="duplicate"):
        parse_sources(data, ROOT)


def test_missing_label_is_refused():
    with pytest.raises(SourceError, match="without a label"):
        parse_sources({"sources": [{"path": "x"}]}, ROOT)


def test_missing_path_is_refused():
    with pytest.raises(SourceError, match="path is required"):
        parse_sources({"sources": [{"label": "a"}]}, ROOT)


def test_unknown_key_is_refused_rather_than_ignored():
    """A typo that silently does nothing is worse than a refused run."""
    with pytest.raises(SourceError, match="unknown key"):
        parse_sources(manifest(licence="MIT"), ROOT)


def test_commit_defaults_to_unpinned():
    """A source need not be a git checkout at all."""
    assert parse_sources(manifest(), ROOT)[0].commit == ""


def test_commit_is_kept_verbatim_and_lowercased():
    sha = "E4E4163101F162881E628F300A9CA4E6A940BCEA"
    assert parse_sources(manifest(commit=sha), ROOT)[0].commit == sha.lower()


def test_abbreviated_commit_is_refused():
    """Seven characters are unambiguous until the day they are not, and
    resolving them needs the upstream present — which a reader may not have."""
    with pytest.raises(SourceError, match="40-character"):
        parse_sources(manifest(commit="e4e4163"), ROOT)


def test_a_commit_that_is_not_an_object_name_is_refused():
    with pytest.raises(SourceError, match="40-character"):
        parse_sources(manifest(commit="HEAD"), ROOT)


def test_include_must_be_a_list_of_strings():
    with pytest.raises(SourceError, match="list of strings"):
        parse_sources(manifest(include="api-design"), ROOT)


def test_missing_manifest_file_is_refused(tmp_path):
    with pytest.raises(SourceError, match="no manifest"):
        load_sources(tmp_path / "absent.yaml", ROOT)


def source(**overrides) -> Source:
    base = {"label": "ecc", "path": Path("/x")}
    base.update(overrides)
    return Source(**base)


def test_no_filters_takes_everything():
    assert selects(source(), "anything") is True


def test_include_is_a_whitelist():
    picked = source(include=("api-design", "accessibility"))
    assert selects(picked, "api-design") is True
    assert selects(picked, "agent-sort") is False


def test_exclude_drops_a_name():
    assert selects(source(exclude=("agent-sort",)), "agent-sort") is False


def test_exclude_applies_after_include():
    both = source(include=("agent-*",), exclude=("agent-sort",))
    assert selects(both, "agent-eval") is True
    assert selects(both, "agent-sort") is False


def test_patterns_are_globs():
    assert selects(source(include=("react-*",)), "react-hooks") is True
    assert selects(source(include=("react-*",)), "vue-basics") is False


def test_include_and_exclude_together_narrow_a_real_selection():
    """The ECC case: 281 skills upstream, a handful wanted, one of those dropped."""
    picked = source(include=("a*", "hexagonal-*"), exclude=("agent-sort",))
    taken = [n for n in ("api-design", "accessibility", "agent-sort", "hexagonal-architecture",
                         "vue-patterns") if selects(picked, n)]
    assert taken == ["api-design", "accessibility", "hexagonal-architecture"]
