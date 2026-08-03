"""The catalogue's own subject areas, and deciding which one a need belongs to.

A search cannot say "I have nothing for this". `find_lenses` always returns
`limit` results, shaped identically whether the corpus covers the need or not,
and measured 2026-08-03 the dense score does not separate the two: a question
about JVM garbage collection, absent from this corpus entirely, scored 0.563
where a genuine hit on `release-it` scored 0.561. No threshold exists.

So the question is asked differently. Instead of "is any of these twenty
relevant" — an open judgement about relevance, which small models answer
badly and which this project has watched them answer badly twice — it becomes
"which of these nineteen subject areas does this need belong to, if any". That
is classification against a closed set, which the same model does well.

Two things make it work, and neither is the model:

**The taxonomy is derived from the corpus**, so it covers the catalogue by
construction. That is what lets "no label fits" mean "the catalogue does not
cover this" rather than "the taxonomy was written by someone with other
interests". `test_taxonomy.py` fails if a skill ever loses its label.

**Every label carries what it does not cover.** Measured over five needs the
corpus cannot answer, bare labels sent four of five to a plausible-looking
category; the same labels carrying scope and exclusions sent five of five to
NONE. The `excludes` lines are the mechanism.

What this reports is a subject area, never a filter. A need classified `NONE`
still gets its results — see `mcp_server._find_one`, and the reason is the
same one `document_kinds` carries: a wrong label you can see costs less than a
wrong label that narrowed your search.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

#: Given a system and a user message, return the model's reply. Same shape as
#: `llm_rerank.Completer`, and deliberately the same endpoint: one local model
#: serves both, so a caller who configured ranking has configured this too.
Completer = Callable[[str, str], str]

#: What `classify` returns when the model's reply cannot be read at all —
#: distinct from `None`, which is the model saying the corpus has nothing.
#: Collapsing the two would put a warning on a good answer every time the
#: endpoint hiccuped.
UNREADABLE = ""


class TaxonomyError(RuntimeError):
    """The taxonomy file is missing, empty or unreadable."""


@dataclass(frozen=True)
class Label:
    id: str
    scope: str
    #: What this area is *not*, which is what makes abstention work. Empty for
    #: an area with no neighbour it gets confused with.
    excludes: str
    skills: tuple[str, ...]


@dataclass(frozen=True)
class Taxonomy:
    #: Stated once, applying to every label: what this catalogue is about, and
    #: when to answer NONE. Drawn by domain rather than by how specific a
    #: question is — see the comment in catalog/taxonomy.yaml for why.
    boundary: str
    labels: tuple[Label, ...]

    def label_for_skill(self, skill_id: str) -> str | None:
        for label in self.labels:
            if skill_id in label.skills:
                return label.id
        return None


def load_taxonomy(path: Path) -> Taxonomy:
    if not Path(path).is_file():
        raise TaxonomyError(f"no taxonomy at {path}")
    document = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    labels = tuple(
        Label(
            id=entry["id"],
            scope=" ".join(entry["scope"].split()),
            excludes=" ".join((entry.get("excludes") or "").split()),
            skills=tuple(entry.get("skills") or ()),
        )
        for entry in document.get("labels") or ()
    )
    if not labels:
        raise TaxonomyError(f"{path} names no labels")
    return Taxonomy(boundary=" ".join((document.get("boundary") or "").split()),
                    labels=labels)


def build_prompt(taxonomy: Taxonomy, intent: str) -> tuple[str, str]:
    """The system and user messages for one classification call.

    Kept as a function so a test can assert what the model is actually asked.
    Like `llm_rerank.build_prompt` this is a tuning surface no unit test can
    judge: only a run against the live endpoint says whether a wording is
    better, so change it and re-measure, never just read it and agree.
    """
    catalogue = "\n".join(
        f"- {label.id}: {label.scope}"
        + (f" EXCLUDES: {label.excludes}" if label.excludes else "")
        for label in taxonomy.labels
    )
    system = (
        "You assign one label to a stated need, from a fixed list. A need that "
        "falls outside every scope is not a bad need — it is simply outside "
        f"this catalogue.\n\n{taxonomy.boundary}\n\nReply with one label or "
        f"NONE. Nothing else.\n\nLabels:\n{catalogue}"
    )
    return system, f"Need: {intent}\n\nLabel:"


def classify(intent: str, taxonomy: Taxonomy, complete: Completer) -> str | None:
    """The subject area this need belongs to, `None` for none of them.

    Returns `UNREADABLE` when the reply is neither — a model that answered
    nothing usable has made no claim about the corpus, and reporting one would
    warn a caller off a result that is fine.
    """
    reply = complete(*build_prompt(taxonomy, intent))
    known = {label.id for label in taxonomy.labels}
    # Small models decorate: a leading bullet, bold markers, a "Label:" prefix,
    # a sentence of reasoning on the next line. Every form handled here came
    # off a live model that had been asked for a bare label.
    for token in re.findall(r"[A-Za-z][A-Za-z-]+", reply):
        lowered = token.lower()
        if lowered in known:
            return lowered
        if lowered == "none":
            return None
        if lowered != "label":
            break
    return UNREADABLE
