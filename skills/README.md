# Vendored skills

Upstream skills, copied verbatim at the version each was decomposed at. This
directory is **quotation, not authorship** — nothing here was written by this
project, and nothing here may be edited.

## Why they are here

The catalogue in `catalog/` pins every part to a `sha256` of the source text.
A pin is only worth something if the text it names still exists: upstream
repositories are rewritten, renamed and deleted, and a catalogue that points at
a moved target is worse than no catalogue, because it looks correct. These
copies are what the pins actually refer to.

## Layout

```
skills/<label>/LICENSE              upstream licence, verbatim
skills/<label>/<name>/SKILL.md      the skill, byte for byte
skills/<label>/<name>/references/   its supporting files, byte for byte
skills/<label>/<name>/skill.yaml    version, provenance, per-file hashes
```

`skill.yaml` is the only file this project wrote. It exists because the version
cannot live inside `SKILL.md`: the version *is* the hash of that file, so
writing it into the frontmatter would change the thing being identified and
invalidate every decomposition citing it.

```yaml
version: 34ac73394a51          # first 12 of the source hash; names the catalogue file
decomposition:
  catalogue: catalog/wondelai/release-it/34ac73394a51.yaml
  source_sha256: 34ac7339…     # normalised text of SKILL.md — the pin
  decomposed_by: xiaomi/mimo-v2.5
files:                         # raw sha256 of every vendored byte
  SKILL.md: …
  references/patterns.md: …
```

## Do not edit

Editing a vendored file breaks its hash, and the decomposition that cites it
becomes a claim about text that no longer exists. To take a newer upstream
version: re-run the ingest, which writes a *new* catalogue file under the new
hash, then re-vendor. Old versions stay; nothing is overwritten in place.

Verify at any time — no model, no network:

```bash
python scripts/vendor.py --check
```

It re-hashes every vendored file against the sidecar and reports drift.

## Attribution

Both upstreams are MIT-licensed, and their licence texts are vendored beside
the skills they cover.

| Label | Upstream | Copyright |
|---|---|---|
| `wondelai` | [wondelai/skills](https://github.com/wondelai/skills) | © 2025 Wondel.ai sp. z o.o. |
| `ecc` | [affaan-m/ECC](https://github.com/affaan-m/ECC) | © 2026 Affaan Mustafa |

Only a chosen subset of each is here. From `ecc` in particular that is
deliberate: it publishes 281 skills as part of an agent harness with its own
plan → test → implement → review loop, and this project mines it for
individual sections rather than adopting the workflow. See the selection rule
in the repository README.
