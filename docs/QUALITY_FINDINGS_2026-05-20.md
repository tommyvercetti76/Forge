# Forge Quality Findings — 2026-05-20

Companion to [FORGE_QUALITY_SPEED_AUDIT_2026-05-19.md](FORGE_QUALITY_SPEED_AUDIT_2026-05-19.md). Captures everything learned in the second pass after measured perf/quality benchmarks against the wildlife-photo engine and a `mflux` free-form 1280²/36-step comparison.

## What shipped today

- **P1 — multi-seed batch.** `flux_generate_batch` collapses Forge's per-seed subprocess loop into a single `mflux-generate --seed S1 S2 ...` invocation. Measured **−60.8% wall-clock** (106.7 s → 41.9 s) for a 4-seed cool/schnell render at 640². Applies to every FLUX-based engine that uses `--seeds N` via `forge engine render`. Code: [bin/forge.py](../bin/forge.py) `flux_generate_batch` + the engine render loop. Img2img / Kontext path remains per-seed (different conditioning per call).
- **Q1 — trust plumbing.** `bin/engine_qc.py` adds three load-bearing primitives: `derive_blockers`, `write_blockers_json`, `is_publishable`. Every engine render now writes a `*.blockers.json` sibling iff the QC sidecar contains failed checks; the manifest records `publishable` per variant; `--allow-qc-warnings` overrides at run time. Madhubani's `render` and `promote` paths use the same primitive so the contract is identical across CLI surfaces.

## Why fine details collapse (verified on tiger renders)

Six independent causes, ranked by what they cost the cool/schnell baseline:

| # | Cause | Today | Magnitude on the tiger test |
|---|---|---|---|
| 1 | Step count | 4 (schnell) | Dominant. Whiskers and ocelli need late-stage denoising; they never appear at 4 steps. |
| 2 | Resolution → latent grid | 640² = 80×80 latent | Severe. A tiger ocellus is ~4–6 px at 640² ≈ 1 latent cell. Sub-pixel detail is unrepresentable. |
| 3 | Quantization | q4 in `cool` | Real. q4 → q8 typically restores fur micro-texture ~10–15%. |
| 4 | Prompt has no species feature list | 5 master citations, 42 negatives, **0 iconography** | Big. Even at quality profile, ocelli + whisker counts were missing on every render. |
| 5 | Negatives prevent failure, do not compel detail | "no melted eyes" ≠ "two amber-gold vertical-slit eyes" | Medium. Active positives carry weight; absence-of-bad does not. |
| 6 | No subject-aware conditioning | Engine doesn't know the species until text-only inference | Medium. No per-species hook in `build()`. |

Causes 1 and 2 account for ~70% of the gap. **Causes 4 and 6 persist at the quality profile** — that is what makes prompt-side mastery the next leverage point.

## Mastery levers — ranked by yield-per-effort

| Lever | Effort | Expected detail gain | Lands where |
|---|---|---|---|
| **A. Dials already in code** — `--profile quality --width 1280 --height 1280` | none | +60–80% perceived | `PROFILES` at [bin/forge.py](../bin/forge.py) ≈ line 300 |
| **B. Per-species iconography block** in engine prompts (see appendix) | ~3 hrs | +30–40% on top of A | `style_engines.py` per-engine `build()` |
| **C. Default-on `--refine` for `quality` profile** | ~1 hr | +20–30% on top of A+B | `forge.py` refine path already exists |
| **D. Render → upscale → low-denoise polish** (`mflux --image-path --image-strength 0.25`) | ~half day | +15–25%, especially fur micro-texture | mflux supports `--image-path` natively |
| **E. Wildlife / per-engine LoRA** (~30–50 references, ~$50 cloud GPU) | ~2 days curate + 1 train | Largest absolute jump; details become baked into the model | `brand/loras/` is already wired |
| **F. Region inpaint pass** (crop head, polish, composite) | days; new code | Tightest control; standard in pro pipelines | Not in mflux today; would need a small shim |

## Comparison: cool/scout (640²/4-step) vs quality (1280²/36-step)

Same prompt, same 4 seeds, same Bengal tiger.

| Detail | Cool | Quality |
|---|---|---|
| Eye character | cartoon-flat, sometimes asymmetric | crisp amber-gold irises, vertical pupils, catchlight on 3 of 4 |
| Whiskers | absent or smudged | visible on seeds 3 + 4 (but count still ~5 vs real ~8–12) |
| Ocelli (white false-eye behind ears) | absent on all 4 | **still absent on all 4** — prompt-side failure, not profile-side |
| Fur texture | painterly mush | individual stripe edges, fur tufts |
| Anatomy | seeds 2/3 had shape issues | seed 1 stubby body, seed 3 stretched front paws; 2/4 read correct |
| Stripes | broad bands | broken vertical bands with finer secondary stripes |
| Background depth | flat | proper bokeh, atmospheric haze, water reflections |
| Wall time | 19 s for 4 | ~18 min for 4 (~57× slower) |

**Top takeaway:** ocelli + whisker counts are *prompt failures*, not step/resolution/quantize failures. They will not be solved by dialing harder.

## Per-species iconography (Lever B) — first draft

A small dict keyed by species name, consulted in the engine builder when a known subject appears. Drop-in for `wildlife-photo`, `indian-classical`, `minimalist-tshirt`, and `stylized-cinematic`.

```text
tiger     — amber-gold eyes with vertical slit pupils; sharp white ocelli behind both ears; 8–12 long pale whiskers per side; rust-orange body with broken vertical black stripes; pale belly fur
peacock   — iridescent blue-green neck; ocellus eye-spots on tail feathers; crest of small fan feathers on head; bright orange feet
elephant  — small alert eyes with long lashes; trunk with visible ring lines; tusks (for males) or short tushes; broad triangular ears; wrinkled grey skin texture
cobra     — flared hood with two oval black eye-spots; forked tongue mid-flicker; pale belly scales; defined diamond head
fish      — large round eyes; gill plates clearly delineated; layered overlapping scales; paired fins + tail
horse     — bright forward-set eyes; long mane and tail in continuous strokes; visible muscle lines on flank
deer      — large dark eyes; white throat patch; branching antlers (males) or smooth poll (females); slender legs
parrot    — strong curved beak; visible cere above beak; long pointed tail feathers; defined wing bars
turtle    — geometric scute pattern on shell; lined skin folds at neck; webbed feet
lion      — round eyes with golden iris; full ringed mane (males); muscular shoulder; tufted tail tip
```

These are positive *iconography* phrases — they reinforce species identity at the prompt level. They should be appended after the master citations and before the universal negatives, so the model treats them as compositional anchors.

## Cross-engine applicability

| Engine | FLUX-based? | P1 (perf) | Q1 (trust) | Lever B (iconography) |
|---|---|---|---|---|
| `wildlife-photo` | yes | ✓ ships now | plumbing ✓; gates need Q7 | direct fit |
| `noir-cinema` | yes | ✓ | plumbing ✓; gates need Q7 | not species-driven; per-shot composition table instead |
| `impressionist` | yes | ✓ | plumbing ✓; gates need Q7 | per-period palette + brushwork table instead |
| `stylized-cinematic` | yes | ✓ | plumbing ✓; gates need Q7 | per-archetype hook (warrior / sage / beast) |
| `indian-classical` | yes | ✓ | plumbing ✓; gates need Q7 | species iconography + per-tradition palette anchor |
| `minimalist-tshirt` | yes | ✓ | plumbing ✓; gates need Q7 | species iconography critical (silhouette read) |
| `mandala-art` (engine) | yes | ✓ | plumbing ✓; gates need Q7 | per-subject "centerpiece" table |
| `childrens-coloring-book` (engine) | yes | ✓ | plumbing ✓; gates need Q7 | per-character archetype + setting block |
| Madhubani via `forge_madhubani.py` | yes | ✓ stacks with `--jobs` parallelism | ✓ full — already has 4/7 rubric gates | per-animal iconography already exists in `animals.json`; tune scales |
| `forge mandala` / `childrens-book` / `folk-art` / `minimal-animal` (CLI procedural) | **no — SVG** | N/A (no mflux) | plumbing ✓ via existing QC JSON | N/A |
| `forge edit` (Kontext) | yes | partial — separate path | plumbing ✓ | N/A (img2img) |

## What's still parked

Ordered by what would move the needle next. Do not start more than one at a time.

1. **Q7 — extend the Madhubani QC harness pattern to every engine.** Generic checks: palette-floor, corner-cleanliness, text-leak (OCR), file-integrity, min-size. After Q7, Q1's blockers will actually bite on non-Madhubani engines (today they sit silent because nobody writes QC sidecars there).
2. **Lever B — per-species iconography block.** Smallest, highest-impact prompt-side change. Draft above.
3. **Q5 — CLIP-style prompt/image alignment.** The only way to auto-catch semantic regressions ("saturated multi-color" rendered as "2-tone mascot"). Requires an embedding model on disk; `mlx-clip` or `siglip` via `mlx_vlm` are local-friendly.
4. **Q6 — OCR text-leak detection.** Tesseract pass; flag if recognized text > 10 chars.
5. **Q3 — audio-derived subtitle alignment in `forge episode`.** Port `bin/audiobook.py`'s Whisper-on-final-WAV pattern. Closes the biggest production-trust gap.
6. **Q4 — glossary in `translate_texts_ollama`**. Signature adds `glossary: dict[str, dict[str, str]]`; system prompt enforces "always translate X as Y".
7. **Lever C — default `--refine` for `quality` profile.** Code exists; just toggle the default + measure.
8. **Lever E — wildlife/per-engine LoRA.** Park until Levers A+B+C are exhausted.

## Free-form stays first-class

`forge engine render` applies the engine prompt scaffold + LoRAs + negatives + master citations. `mflux-generate --prompt "..."` direct bypasses Forge entirely. Both keep their entrypoints. The benchmark above used both: the cool baseline ran through the preset (`forge engine render wildlife-photo`); the 1280²/36-step quality run was free-form mflux. The quality run **still showed dramatic detail gains without any preset scaffolding** — confirming that the dials are real and the preset's LoRAs/negatives layer on top, not under.

## Honest math on +40% / +40%

- **Performance (verified):** P1 alone delivers −60.8% wall-clock on cool/schnell scouting, ~−15–20% on `quality`/dev workflows. Above target on scouting; below target on production finals, where inference dominates. Stacking with `--jobs N` parallel pose driver (already shipped) doubles up on different axes.
- **Quality (today shipped):** Q1 is plumbing, not coverage. Madhubani gates 4/7 rubric items via auto-QC, and Q1 now makes those decisive. Across all eight engines, machine-gated rubric coverage today is roughly Madhubani (57%) and ~6% everywhere else; system-wide weighted ≈ 12–15%. Q7 + Q5 + Q6 + Lever B together would lift system-wide gated coverage past 50% — the credible path to +40%. None of those are shipped yet; they are the parked items above.

## Where to go next

The next single feature to ship — per the "stay focused" rule — is **Lever B (per-species iconography in engine prompts)**. It is the smallest piece of work that closes the visible gap (missing ocelli + whisker counts) on the engines Forge actually drives. It does not require model training, embedding models, OCR, or new infrastructure. ~3 hours.

After Lever B, the next is either **Q7** (extend auto-QC to every engine, makes Q1 bite cross-engine) or **Lever C** (default `--refine` for `quality`). Decide from a re-measurement.
