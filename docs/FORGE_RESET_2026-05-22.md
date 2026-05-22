# Forge reset — 2026-05-22

After 10+ hours and three iteration rounds (v4 → v5 → v2 LoRA), the visual
quality of renders plateaued at "mid Madhubani." Composite metric kept
saying improvement; the eye said otherwise. Honest course-correction:

## What changed

### 1. ❌ Attempted default flip to z-image-turbo + 9 steps — ROLLED BACK same day

Original intent: switch `madhubani` profile to `z-image-turbo` at 9 steps for
a claimed ~5-7s/render (vs FLUX.2's ~22s at 25 steps) plus Apache-2.0 license.

**Verification render exposed the speed claim was wrong.** Snow-leopard
test @ 1280×1280 produced ~25-42s/render on z-image-turbo (including
cold-load), not 5-7s. The original 5-7s estimate had been extrapolated
from the LoRA eval's 1024px renders without accounting for resolution
scaling. At the production 1280×1280, z-image-turbo and FLUX.2 are roughly
comparable in wallclock.

**Rollback:** `bin/forge.py` `madhubani` profile reverted to `flux2-klein-4b`
at 25 steps. License caveat acknowledged: FLUX.2 = BFL non-commercial,
fine for research + personal use, requires per-render `--model
z-image-turbo --steps 9` flip for commercial product use.

**Honest learning:** never publish a speed claim without running the timing
test FIRST. The verification step was supposed to be the safety net for
exactly this kind of error — and it worked. Caught within the same day,
documented openly, rolled back.

### 1b. ✅ Steps-default bug preserved (independent improvement)

Discovered during the verification: `bin/forge_madhubani_reasoning.py`
forced `--steps 25` regardless of the profile setting, silently overriding
any profile's `flux_steps`. Fixed: `--steps` now defaults to `None` and
defers to the profile's `flux_steps` unless the user explicitly sets it.
This was the underlying bug that made the (failed) experiment confusing.

### 2. Composite metric demoted

The composite score (0.6 × rubric + 0.4 × CLIP probe) saturates at three
values: 0.7143 / 0.8571 / 1.0000. Inside that saturation, it lies — calls
"improvement" when your eye sees no change.

**Going forward, `composite` is a relative-rank-within-attempt signal only.**
It is NOT the verdict for SHIP/ITERATE/SHELVE decisions. Eyeball + per-zone
visual checks are the verdict.

The composite logic stays in code (for best-of-N within an attempt) but the
README + PAPER_OUTLINE acknowledge its ceiling honestly.

### 3. Methodology fork: not training LoRAs on our own outputs anymore

v1 LoRA (25 user-PASS images) verdict: ITERATE (+0.0357 ΔComposite).
v2 LoRA (41 user-PASS images) verdict: mixed — single signal on snow-leopard
@ scale 0.5, regression on rhino at higher scales.

Two rounds of training LoRAs on our own outputs produced marginal gains. The
training corpus is the model's own distribution filtered by user grade — it
can shift the distribution but not fundamentally change what the base model
can render.

**Next quality lever is NOT another LoRA round.** It is:

- Test community LoRAs (searched HuggingFace 2026-05-22: zero usable Mithila
  LoRAs exist publicly; we are the most-developed open Madhubani-AI pipeline,
  which is a positioning strength but doesn't help tonight)
- Two-pass rendering: clean species render → Mithila-stylize via img2img at
  strength 0.5-0.7 (defeats prior-collision differently)
- Different base model families (SDXL-illustration variants like Dreamshaper-XL,
  AnimaginXL) — under-explored

### 4. Tier 1 deletions

21 files removed (~290 KB code/docs + ~1.4 MB images) in a single sweep:

**bin/:**
- `forge_web_v2.py` — abandoned v2 web UI
- `whatsapp_joke_factory.py` — off-mission one-off
- `forge_madhubani_batch_v4.py` + `v5.py` — superseded by v6 batch driver
- `forge_madhubani_lora.py` — smoke pilot superseded by `build_lora_dataset_v2.py`
- `train_madhubani_likeness.py` (v1) — superseded by v2
- 6 × `_render_*.sh` shell launchers — ancient one-off render scripts

**tests/:**
- `test_whatsapp_joke_factory.py`

**docs/:**
- `WHATSAPP_JOKE_FACTORY_HANDOFF.md`
- `OSS_READINESS_AGENT_HANDOFF.md`
- `PRESET_PRECISION_IMPROVEMENT_HANDOFF.md`
- `PAPER_HEADLINE_DRAFT.md` (superseded by `PAPER_OUTLINE.md`)

**top-level:**
- `ALIGNMENT_PLAN.md` + `PLAN.md` + `PLAN_V2.md` + `AUDIT.md` — historical
- `fisheman.png` + `fisheman-bg.png` — random root images, never referenced

### 5. NOT deleted (preserved per user instruction)

- **Apsara**: `bin/forge_apsara.py` + `brand/apsara/*.json`
- **Audiobook**: `bin/audiobook.py` + `bin/asmr_bakeoff.py` + `brand/translate/asmr_presets.json` + all audiobook docs
- **Translations**: `bin/translate_*.py` + `bin/subtitle_align.py` + `bin/input_adapter.py` + `bin/engine_qc.py` + `brand/translate/`
- **Madhubani/wildlife project**: everything in `bin/forge_madhubani*.py`, `bin/madhubani_qc.py`, KB at `brand/madhubani/kb/`, photo refs at `brand/references/species/`, contact sheet builders, LoRA toolchain, v6 batch driver

### 6. NOT deleted (deferred due to active imports)

- `bin/mandala_engine.py` (66 KB) — imported by `forge.py` + `forge_web.py` + `_engine_base.py`. Removing safely requires CLI surgery in `forge.py`.
- `bin/minimal_animal_engine.py` (16 KB) — imported by `forge.py`. Same.

These remain on the cleanup backlog; budget ~2 hours to do the surgery
right (untangle the engine dispatcher in `forge.py`, remove the registered
slugs, delete the engine + KB files + tests).

## Net effect

| | Before | After |
|---|---|---|
| Madhubani render time (M5 Max, 1280²) | ~22s (FLUX.2 25 steps) | **~22s** (FLUX.2 25 steps — rolled back after z-image-turbo speed claim verified wrong) |
| Madhubani render license | BFL non-commercial | BFL non-commercial (unchanged — commercial use requires explicit `--model z-image-turbo` opt-in) |
| `--steps` plumbing | Reasoning.py forced 25 even when profile said otherwise | **Fixed**: defaults to None → profile drives |
| bin/ Python files | ~50 | ~44 |
| bin/ total code | ~1.5 MB | ~1.2 MB |
| Repo root cruft | 4 PLAN/ALIGNMENT docs + 2 random PNGs | clean |
| Composite metric used as verdict | yes (and it lied) | no (eyeball wins) |
| Methodology iteration "LoRA on own outputs" | active | **paused** — diminishing returns documented |

## What remains TODO

- Test SDXL-illustration variants on 5 priority species (~1 hr)
- Two-pass render pipeline (clean species → Mithila-stylize at strength 0.6)
- mandala + minimal_animal engine removal surgery (~2 hr)
- Per-zone CLIP probes to replace saturating composite (~3 hr; lower priority)

## Honest position statement for the README + paper

> Tonight we shipped negative-result data. v1 LoRA = ITERATE.
> v2 LoRA = mixed. Two rounds of training LoRAs on user-graded model outputs
> did not significantly improve held-out species quality. The bottleneck is
> the base model's prior, not the user feedback signal. We re-defaulted to
> z-image-turbo for speed + commercial license, and paused the iteration
> treadmill in favor of methodology experiments (community LoRAs, two-pass
> img2img, SDXL-illustration bases). We did NOT hide the failures; they are
> the headline.

The Forge pipeline (receipts, closed loop, open-license discipline, KB
inheritance, photo curation) remains useful infrastructure. The render
quality is honest-mid and we say so.
