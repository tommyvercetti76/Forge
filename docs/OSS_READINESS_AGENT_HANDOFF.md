# OSS Readiness Agent Handoff

Created: 2026-05-20

Status: action plan for the next agent. This is not an implementation summary.

## Mission

Turn Forge from a strong personal ML systems project into a credible public
open-source portfolio project.

The public story should be:

> Forge is an eval-driven, local-first Apple Silicon ML workstation for image
> generation, with domain schemas, automated QC, model/runtime ops, cultural
> attribution, and closed-loop quality improvement.

Do not present it as a universal AI media platform. That is too broad for a
first public impression and invites skepticism.

## Audit Snapshot

Verified on 2026-05-20 after `git fetch --prune origin`.

Remote state:

- `HEAD` and `origin/main` were equal: `0 ahead / 0 behind`.
- Worktree had local uncommitted documentation edits plus one untracked mockup
  test.

Validation commands that passed:

```sh
python3 -m unittest discover -s tests
git ls-files -z 'tests/test_*.py' | xargs -0 python3 -m unittest
python3 -m compileall -q bin tests archive
python3 bin/forge.py doctor --deep
python3 bin/forge.py models scan --full
python3 bin/forge.py bench
python3 bin/forge.py engine list
python3 bin/forge_madhubani.py list animals
python3 bin/forge_madhubani.py list poses
python3 bin/forge.py mockup init --out /private/tmp/forge-mockup-audit
python3 bin/forge.py minimal-animal --animal 'alert tiger side profile' --max-lines 8 --out /private/tmp/forge-minimal-audit/tiger.svg
```

Observed results:

- Full local discovery: 128 tests, 2 skipped.
- Tracked-only suite: 122 tests, 2 skipped.
- `forge doctor --deep` passed outside the sandbox: Metal, Ollama, mflux,
  Whisper, and model cache were ready.
- `forge models scan --full` found a 338 GB canonical local model store.
- `forge engine list` listed 8 specialist engines.
- `forge_madhubani.py list animals` listed 41 animals.
- `forge mockup init` generated 50 mockup variants.
- `forge minimal-animal` generated an 8-line tiger mark with QC pass.

## Current Verdict

Forge can be a serious open-source credibility project, especially for an
applied ML / ML systems portfolio.

The strongest angle is not "I made an AI app." The strong angle is:

> I built a local ML production system with model ops, evaluation gates, domain
> schemas, cultural attribution, and closed-loop quality improvement.

The codebase is credible, but the OSS surface is not yet polished enough.

## Strengths To Preserve

- Real test suite and fast local validation.
- Concrete runtime/model ops: doctor, model scan, cache layout, Metal checks.
- Domain schemas for Madhubani animals, poses, palettes, iconography, and
  quality gates.
- Automated QC posture, especially `madhubani_qc.py` and `engine_qc.py`.
- Strong cultural attribution posture for Mithila / Madhubani inspiration.
- Honest docs that distinguish shipped work from planned work in several places.
- Local-first Apple Silicon focus, which is sharper than a generic AI project.

## Top Blockers

### P0. Add A Real Project Manifest

Problem:

- There is no `pyproject.toml`, `requirements.txt`, `uv.lock`, `setup.py`,
  `setup.cfg`, or equivalent dependency manifest.
- `CONTRIBUTING.md` currently says to install dependencies "as declared in the
  project manifest", but no manifest exists.

Why it matters:

- A public OSS reviewer cannot reproduce the environment from clone.
- This undermines the otherwise strong tests and doctor checks.

Recommended fix:

- Add `pyproject.toml`.
- Declare Python version, package metadata, core dependencies, and optional
  extras.
- Add console scripts for at least:
  - `forge = bin.forge:main` only if packaging is adjusted into importable
    modules, or keep scripts as direct files and document that packaging is
    provisional.
- If packaging the current `bin/` layout would be too invasive, ship a minimal
  dependency manifest first and explicitly say CLI installation still uses
  symlinks.

Acceptance criteria:

- A fresh clone can run:

```sh
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
python3 -m unittest discover -s tests
```

- `CONTRIBUTING.md` setup instructions match reality.

### P0. Add CI

Problem:

- No `.github/workflows/` exists.
- README test badge is static, not backed by CI.

Why it matters:

- Public claims about tests are much more credible with a green workflow.

Recommended fix:

- Add `.github/workflows/tests.yml`.
- Run unit tests on macOS if budget allows; otherwise run Linux tests that do
  not require Metal and mark Metal/model checks as local-only.
- Keep heavy model tests skipped or mocked.

Acceptance criteria:

- GitHub Actions shows a passing test workflow.
- README test badge links to the workflow instead of a static badge, or the
  badge is removed until CI exists.

### P0. Align Test Count Claims

Problem:

- Full local discovery reported 128 tests because an untracked
  `tests/test_mockup_compositor.py` exists.
- Tracked-only tests reported 122 tests.
- README claims 128 passing tests.

Recommended fix:

- Either commit `tests/test_mockup_compositor.py`, or change README claims to
  the tracked count.

Acceptance criteria:

- `git status --short` is clean or the README explicitly excludes untracked
  local tests.
- README test count matches the tracked suite.

### P0. Fix README Cloud Claim

Problem:

- README hero says "No cloud APIs", while reality check correctly says Sarvam
  cloud TTS is optional.

Recommended wording:

> No cloud required for core local paths. Optional cloud TTS for high-quality
> Hindi/Marathi narration.

Acceptance criteria:

- README does not contradict itself.
- `NOTICE` and README both clearly distinguish code license, model licenses,
  and optional cloud boundaries.

### P1. Fix Benchmark Reproducibility

Problem:

- README reports a verified `-60.8%` wall-clock benchmark, but says the
  dedicated multi-seed benchmark harness is planned.
- `forge bench` currently writes local profile metadata; it does not reproduce
  the multi-seed measurement.

Recommended fix:

- Either add a real reproducible benchmark command, or move the benchmark into
  a "measured once, not yet automated" section.

Acceptance criteria:

- A user can reproduce the headline number with a documented command, or the
  README clearly labels it as historical measured evidence.

### P1. Update Stale Madhubani Pose Docs

Problem:

- `docs/MADHUBANI_ART_IDENTITY.md` says v2 pose taxonomy is not implemented.
- `brand/madhubani/poses.json` appears to contain v2 metadata and body-type
  overrides.

Recommended fix:

- Audit actual `poses.json` behavior.
- Update the doc to distinguish:
  - implemented schema/data,
  - implemented render behavior,
  - still-planned UI or quality gates.

Acceptance criteria:

- README, Madhubani identity docs, and catalog docs agree on pose-taxonomy
  status.

### P1. Correct Attribution Manifest Paths

Problem:

- `NOTICE` refers to `brand/madhubani/references/attribution.json`.
- Actual checked attribution files live under
  `brand/references/madhubani/_general/*.attribution.json`.

Recommended fix:

- Update `NOTICE`, `CONTRIBUTING.md`, and any rehydration docs to point to the
  real manifest layout.
- Ensure `bin/rehydrate_references.py` expects the same layout the docs describe.

Acceptance criteria:

- `find brand/references/madhubani -name '*.attribution.json'` matches the docs.
- A contributor adding a reference image knows exactly where attribution goes.

### P1. Clarify Model And Output Licensing

Problem:

- Code is MIT, but several model weights and potentially outputs are governed by
  upstream model licenses.
- The `NOTICE` is good, but public-facing wording should be sharper.

Recommended wording:

> Forge code is MIT. Model weights are not redistributed. Generated-output use
> depends on the upstream model license you choose.

Acceptance criteria:

- README, NOTICE, and CONTRIBUTING all use consistent wording.

### P2. Narrow The Public Front Door

Problem:

- Forge does many things: images, audiobooks, jokes, mockups, episodes,
  translation, video prep, reasoning-engine planning.
- This is impressive locally, but chaotic publicly.

Recommendation:

- Make the first public story about eval-driven local image generation.
- Lead with:
  - Madhubani animal catalog,
  - automated QC,
  - model/runtime ops,
  - Art Reasoning Engine plan.
- Move secondary workflows lower in the README.

Acceptance criteria:

- A new reader can explain the project in one sentence after 30 seconds.
- README top half does not read like a feature dump.

### P2. Add A Public Roadmap

Recommended file:

```text
docs/ROADMAP.md
```

Include:

- Shipped.
- In progress.
- Next.
- Explicitly not supported.

Acceptance criteria:

- Planned work is not scattered across handoffs only.
- README links to roadmap instead of over-explaining every future item.

## Suggested Work Order

1. Make the tree internally consistent:
   - commit or remove untracked mockup test,
   - align README test count,
   - fix cloud claim.
2. Add `pyproject.toml` and update `CONTRIBUTING.md`.
3. Add CI.
4. Fix attribution paths in `NOTICE` and docs.
5. Fix stale Madhubani pose status docs.
6. Add or soften benchmark reproducibility.
7. Refocus README around the flagship story.
8. Add `docs/ROADMAP.md`.

## Do Not Do

- Do not remove reality-check caveats to make the project sound stronger.
- Do not claim "local-only" while Sarvam remains an optional path.
- Do not claim model-output commercial rights that upstream licenses do not
  grant.
- Do not add heavy model downloads to CI.
- Do not rewrite the whole codebase into a package before first public polish;
  dependency reproducibility matters more than perfect package structure.

## Final Positioning

Use this phrasing in public materials:

> Forge is a local-first Apple Silicon ML workstation for eval-driven image
> generation. It combines FLUX/mflux rendering, domain schemas, automated QC,
> model-cache ops, and cultural attribution into a reproducible creative
> pipeline.

Use this phrasing for career/portfolio materials:

> I built Forge to learn serious applied ML engineering: local model ops,
> evaluation loops, multimodal generation, artifact receipts, and domain-specific
> quality gates. The project shows I can build systems around models, not just
> call model APIs.

