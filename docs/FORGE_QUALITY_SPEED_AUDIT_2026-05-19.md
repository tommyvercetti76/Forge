# Forge Quality + Speed Audit — 2026-05-19

## Scope

This audit focused on the active Forge image paths that matter for the current
catalog push:

- Madhubani / Mithila-inspired animal T-shirt catalog
- Minimalist T-shirt engine
- Beta exact-stroke minimal animal lane
- Runtime scheduling for local Apple Metal / mflux jobs

## Definitions

The requested targets are only meaningful with measurable proxies:

- **Quality +40% target:** increase the share of the Madhubani quality rubric
  enforced automatically before a design can be promoted.
- **Speed +20% target:** reduce wall-clock time for a four-pose Madhubani set
  without lowering per-render step count or falling back to CPU.

This is not a claim that every future FLUX image is 40% more beautiful. It is a
claim that a larger fraction of known failure modes is now machine-gated before
mastering.

## Audit Findings

### Quality

Before this pass, Madhubani renders had strong prompt rules but no automatic
image gate for the first four rubric checks. That meant known failures could
still move forward if the human review missed them.

Highest-value objective gates:

1. Palette floor: catch two-tone mascot/logo regressions.
2. Clean corners: catch signature glyphs and stray painter marks.
3. Subject centered: catch cropped or tiny marks.
4. Saturated body fill: catch blank silhouettes and all-cream bodies.

These four checks are 4 of 7 rubric items, or 57% of the catalog rubric. They
are now scored into per-pose `*.qc.json` receipts.

### Speed

Before this pass, `bin/forge_madhubani.py render <animal> --all-poses` launched
the four poses sequentially. The runtime already had capacity-aware Metal slots,
but the catalog driver was not using them at the set level.

The set renderer now accepts `--jobs N`. For a four-pose set:

- `--jobs 2` reduces ideal render waves from 4 to 2: up to 50% wall-clock
  reduction when two Metal slots fit in memory.
- `--jobs 4` reduces ideal render waves from 4 to 1: up to 75% wall-clock
  reduction when four Metal slots fit in memory.

The child renders request matching `FORGE_METAL_SLOTS` when unset, and
`forge_runtime.ResourceLock` still caps the actual slots by memory. GPU/Metal
guarding remains in the child render path; CPU ML fallback is still refused by
default.

## Implemented Changes

- Added `bin/madhubani_qc.py`.
- Added per-pose auto-QC writes after successful catalog/freeform renders.
- Added auto-QC fields to `render-manifest.json` and workflow events.
- Changed `promote` to block failed auto-QC unless `--force` is supplied.
- Copied `auto-qc.json` into mastered/flagged folders.
- Added `--jobs` / `FORGE_MADHUBANI_JOBS` for parallel pose renders.
- Cached FLUX model readiness checks inside a single `forge.py` process.
- Tightened the Metal guard with an actual `mflux-generate --help` probe so a
  headless session that reports Metal hardware but cannot load an MLX Metal
  device fails before a render launch.
- Updated catalog docs and README with QC and parallel render behavior.

## Remaining Quality Risks

Checks 5–7 still require human review:

- Anatomy correctness
- Expression / eye character
- Whether the result reads as Madhubani at 4-inch shirt scale

The next real quality jump is an image-review harness for those subjective
checks: downscaled thumbnail sheet, OCR/text leak check, CLIP-style prompt-image
alignment, and a labeled pass/fail corpus from mastered vs flagged attempts.

## Remaining Speed Risks

`--jobs` improves throughput only when the machine can safely host multiple
mflux jobs. If `FORGE_METAL_SLOT_RAM_GB` caps the runtime to one slot, jobs will
queue safely and wall-clock speed will not improve. That is intentional.

Actual speed should be measured with a real four-pose render on the target
machine:

```bash
time python bin/forge_madhubani.py render tiger --all-poses --steps 14 --jobs 1
time python bin/forge_madhubani.py render tiger --all-poses --steps 14 --jobs 2 --retry
```

Expected pass condition for the 20% speed target: the `--jobs 2` run is at
least 20% faster wall-clock while all child manifests show Metal/GPU execution.

This audit attempted a low-step GPU benchmark from the current Codex session,
but the mflux/MLX runtime reported `No Metal device available` in this
headless/sandboxed context. That is now caught by `forge doctor` and by the
pre-render Metal guard. Run the timing commands from a local session with
actual Metal access to validate wall-clock speed.
