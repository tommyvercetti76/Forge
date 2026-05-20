# Contributing to Forge

Thanks for your interest in Forge. This document describes how to set the
project up locally, what to run before opening a pull request, and which
areas welcome outside contribution.

Forge is a local-first ML toolkit for Apple Silicon, targeting image
generation (FLUX family, Z-Image-Turbo), translation, and culturally
grounded specialist engines. It is a personal portfolio project maintained
by Rohan Ramekar (`@tommyvercetti76`).

## Local setup

Hardware:

- Apple Silicon (M3 or newer recommended).
- 36 GB of unified memory or more if you intend to load `FLUX.2-klein-4b`.
  Lower-memory machines can still run smaller engines (e.g. Z-Image-Turbo
  and lighter FLUX variants), but FLUX.2-klein-4b is the demanding case.
- Roughly 80 GB of free disk for model weights, generated samples, and the
  rehydrated reference corpus.

Software:

1. Clone the repo and `cd` into it.
2. Create a Python 3.11+ virtual environment (`python3 -m venv .venv`,
   then `source .venv/bin/activate`).
3. Install dependencies as declared in the project manifest.
4. Rehydrate the reference corpus locally:
   `python3 bin/rehydrate_references.py`. Binaries are intentionally
   gitignored; only the attribution manifests are committed.
5. Install model weights from their original sources (Hugging Face). Forge
   does not redistribute weights. Review each model's license before use;
   FLUX weights are non-commercial only (see `NOTICE`).

## Tests

Before opening a pull request, the test suite must pass:

```
python3 -m unittest discover tests
```

At the last verified run the suite reports 119+ passing tests. New code
should add tests in `tests/`, and unrelated test regressions should be
fixed in the same PR that caused them.

## Style and commits

- Python style follows the existing code: 4-space indent, type hints where
  they clarify intent, docstrings on public functions, no `print`
  debugging left in. If a `pyproject.toml` or `setup.cfg` declares a
  formatter (ruff, black) at the time you contribute, match it; otherwise
  match the surrounding file.
- Commit messages: sentence-case subject under ~72 characters, optional
  body explaining the WHY (not the WHAT — the diff already shows that).
  See `git log` for examples; representative subjects include
  "Lock M5 Max speed defaults into code (no env vars needed)" and
  "Reference corpus: 50 open-licensed Madhubani images". Group related
  changes into a single commit rather than scattering one change across
  many.

## Pull request checklist

Before requesting review:

- [ ] `python3 -m unittest discover tests` passes locally.
- [ ] New behaviour has tests, or the PR explains why it cannot be tested.
- [ ] Docs are updated when behaviour visible to users changes
      (`README.md`, files under `docs/`, engine specs).
- [ ] Attribution is preserved for any new reference image, dataset, or
      borrowed code. If you add a Madhubani reference image, drop a
      `<file>.attribution.json` sidecar next to it under
      `brand/references/madhubani/<species>/` (or
      `brand/references/madhubani/_general/` for tradition-level rather
      than species-level imagery) with `source_url`, `author`, and
      `license` fields — see existing sidecars and
      `_example_attribution.json` for the schema. Other engines use the
      same `<file>.attribution.json` convention under their own
      `brand/references/<engine>/` tree.
- [ ] No model weights, large binaries, generated samples, or secrets are
      committed. `.gitignore` is the source of truth; if you have to
      bypass it, explain why in the PR.
- [ ] You agree to the Code of Conduct (`CODE_OF_CONDUCT.md`).

## Areas welcoming contribution

- New specialist engines (single-purpose generators with their own QC
  rubric, schema, and tests).
- New species or subject schemas for the existing engines (extending
  `brand/madhubani/animals.json`, `species_iconography.json`, etc.).
- New translation glossaries and language pairs.
- Additional open-licensed reference imagery, with full attribution
  manifests and a clear license per file (CC BY-SA 4.0, CC0, GODL-India,
  or Public Domain).
- Performance work on Apple Silicon (MLX, mflux integration, scheduler
  tuning).
- Documentation: clearer setup instructions, troubleshooting, examples.

## Areas closed to outside contribution

The following are intentionally not open to drive-by changes; please open
an issue and discuss with Rohan first, or expect a polite redirect:

- Cultural-heritage attribution rules — anything in
  `docs/CULTURAL_HERITAGE_ATTRIBUTION.md`, the Mithila / Madhubani
  attribution paragraph in `NOTICE`, and the tradition-attribution
  language inside engines. These represent a deliberate ethical
  position, not a placeholder, and changes go through the maintainer.
- License selection for models or reference assets. Forge does not
  relicense third-party content.
- Major architectural pivots (e.g. swapping the base model, deprecating
  an engine) — open an issue first so we can agree on direction before
  you spend time on a PR.

## Code of conduct

By participating in this project you agree to abide by the
[Contributor Covenant v2.1](CODE_OF_CONDUCT.md). Report concerns to
`rohanramekar17@gmail.com`.

## Questions

For anything that doesn't fit an issue or PR, email
`rohanramekar17@gmail.com` with `[FORGE]` in the subject. Security issues
follow the separate process in `SECURITY.md`.
