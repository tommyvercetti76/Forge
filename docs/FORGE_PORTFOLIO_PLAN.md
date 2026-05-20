# Forge — multi-day plan toward an ML portfolio

**Goal:** Forge becomes a publicly visible, respected, reproducible ML showcase that demonstrates serious local-first Apple Silicon work. Built by someone making a career pivot from frontend engineering into ML.

**Established:** 2026-05-20, after the tiger-anatomy-regression conversation that exposed two things: (a) the current renders have real quality problems, and (b) the repo's presentation hasn't kept up with the engineering inside it.

**Scope of this doc:** explicit, sequenced, file-level plan covering 5 work lanes over ~4 working sessions. Honest effort estimates. No code shipped here — execution starts after this plan is approved.

---

## Why now / why this

Forge has serious engineering underneath. The metrics we've already measured:

- **P1 multi-seed batch:** 106.7s → 41.9s for 4 seeds at cool/schnell. Verified -60.8% wall-clock on M5 Max.
- **128 passing tests** (1 skipped optional dep) across 15 test files; engine_qc trust layer with blockers/publishable semantics.
- **8 specialist FLUX engines** plus a procedural mandala/folk-art lane.
- **41-species Madhubani catalog** across 21 national parks, with 12 body types and per-body-type pose semantics.
- **50-reference Mithila corpus** from Wikimedia Commons with full attribution.
- **FLUX.2-klein-4b migration** (M1-M4) + flat-silhouette tuning (L1+L2+N1-rev2) that broke the photorealism lock for high-pull species.
- **Multi-format input adapter** (text / .txt / .pdf / .rtf / audio).
- **Translation Studio** with glossary + leakage + repeated-line blockers.

That's portfolio-grade work. **What's missing is presentation, completeness, and the gallery moment that says "this is the result" on first glance.**

This plan closes those gaps.

---

## The five lanes

| # | Lane | Effort | Outcome | Branch strategy |
|---|---|---|---|---|
| **1** | Tiger anatomy regression fix (stripes-stay-visible) + Kontext img2img from `_legacy/v3/` | ~1.5 hrs | Tigers actually look like tigers; the existing corpus finally informs new renders | `feature/madhubani-flux2-migration` (continue) |
| **2** | `poses.json` v3 — per-body-type slot names | ~3 hrs | "Seated peacock" semantic nonsense gone; birds get perched/in-flight/tail-fanned slots | `feature/poses-v3-by-body-type` (new) |
| **3** | Portfolio README rewrite + `forge demo` + gallery rebrand | ~6 hrs (across 2 sessions) | First-glance "this is real" reaction; instant-gratification CTA | `feature/portfolio-presentation` (new) |
| **4** | Open-source prep — LICENSE files, CONTRIBUTING, FLUX-license disclosure | ~2 hrs | Repo legally + culturally ready to be shown | `feature/oss-prep` (new) |
| **5** | (Stretch) LoRA training pilot on pass_examples + _legacy/v3 + Wikimedia corpus | 3 days | Definitive lock on Madhubani style; one safetensors file that anyone can drop in | separate branch + cloud GPU |

Lanes 1-4 are realistic over 2-3 focused sessions. Lane 5 is a "future" item that ships AFTER 1-4.

---

## Lane 1 — Tiger anatomy regression fix + use the existing corpus

**Problem (verified today):** today's tiger renders (after L1+L2+N1-rev2) look like generic large cats / lions because the engine clause "stripes translated into multi-color folk panels" was interpreted as "REPLACE stripes with floral panels." The vertical-band stripe rhythm is gone. The legacy v3 tiger has obviously-tiger vertical stripes; today's tiger doesn't.

**Root cause:** the prompt asks the model to "translate" stripes; the model interpreted that as substitution. We need the model to keep the stripe PATTERN as flat folk shapes — bold vertical bands still visible.

### Tasks

| Task | File | What changes |
|---|---|---|
| 1.1 Rewrite the stripe-translation clause | `bin/forge_madhubani.py:build_subject_string()` + `brand/madhubani/animals.json:tiger.signature_features` | Change "stripes translated into multi-color folk panels" to "bold vertical-band STRIPE pattern rendered as flat folk-color zones — the stripes remain VISUALLY as 8-12 distinct vertical bands across the body silhouette, just flat-color (indigo/vermillion/leaf-green/gold) instead of black-on-orange fur. The TIGER stripe rhythm stays visible." Plus similar adjustments for other patterned species (snow-leopard rosettes, blackbuck white-cheek, etc.) |
| 1.2 Wire Kontext img2img path for Madhubani renders | `bin/forge_madhubani.py:execute_render()` + new flag `--style-reference <path>` | Optional `--style-reference` arg passes `--from-image <path>` to `forge engine render`. When set, FLUX-Kontext conditions the render on a visual reference. Pick a `_legacy/v3/` or `pass_examples/` image for each species as the default reference. |
| 1.3 Per-species default style references | `brand/madhubani/animals.json` | Add optional `style_reference_path` field per animal pointing at the best historical render. Tiger → `_legacy/indian_animals_v3/01_royal_bengal_tiger...`. Elephant → `pass_examples/elephant_v2.png`. Etc. |
| 1.4 Verification render: tiger + 3 others with Kontext | manual | Render tiger + lion (test new species) + leopard + cheetah with the new clause + Kontext from legacy v3 tiger as reference. Compare against today's lion-like render. |

### Success criteria

- Tiger render shows VISIBLE vertical stripe pattern (even if rendered as flat folk color bands, not photorealistic fur)
- Species identity preserved: tiger is unambiguously a tiger, not a lion
- Anatomy correct (4 legs, almond eye, tail wrap, dignified pose)
- Body fill color honored (walnut-brown)
- Folk-icon flat 2D style preserved (no 3D fur)

### Estimate: ~1.5 hrs

---

## Lane 2 — `poses.json` v3 with per-body-type slot names

**Problem (you flagged today):** "seated-rest peacock" is semantic nonsense; birds don't sit. Today's v2 fixed this with body-type overrides on the same 4 slots, but the slot NAME is still "seated-rest" for birds, which is wrong. The architectural fix is per-body-type slot dictionaries.

### Tasks

| Task | File | What changes |
|---|---|---|
| 2.1 Author `poses.json` v3 schema | `brand/madhubani/poses.json` | Restructure: instead of 4 universal slots, a `poses_by_body_type` map. Each body type gets its 4 canonical poses with idiomatic slugs. Birds: `perched-resting / in-flight / tail-fanned-display / frontal-portrait`. Serpents: `coiled-resting / rearing-hood-spread / s-curve-strike / frontal-portrait`. Mammals: unchanged. Etc. |
| 2.2 Update `forge_madhubani.py` to pick slot dictionary by body type | `bin/forge_madhubani.py:_pose_action_clause()` + `RenderPlan` | Resolve `(body_type, pose_slug)` to the right slot text. Slot validity check: only allow slugs valid for that body type. |
| 2.3 Migrate seed-block allocation | `brand/madhubani/poses.json:seed_allocation` | Per-body-type seed offsets so file paths stay disambiguated. |
| 2.4 Backward compat | `bin/forge_madhubani.py` | Recognize old slot names (`seated-rest`) as aliases for the new per-body-type equivalents (`perched-resting` for birds) during transition. |
| 2.5 Update tests | `tests/test_madhubani_a3_a4.py` + new `tests/test_poses_v3.py` | New tests cover slot validity per body type + alias resolution + seed math |
| 2.6 Update `docs/MADHUBANI_ART_IDENTITY.md` §6 | doc | Reflect what v3 actually shipped vs the forward-spec written today |
| 2.7 Verification renders | manual | Render peacock @ `perched-resting`, peacock @ `in-flight`, cobra @ `rearing-hood-spread`, cetacean @ `gliding`. Confirm slot-name accurately predicts the visual. |

### Success criteria

- Birds NEVER render under a "seated-rest" slot — only valid bird slots
- Existing `_legacy/` and `attempts/` paths still resolve (backward compat layer)
- All 119 tests still pass + new poses-v3 tests pass
- Peacock renders for `perched-resting` and `in-flight` visually differ correctly

### Estimate: ~3 hrs

---

## Lane 3 — Portfolio README rewrite + `forge demo` + gallery rebrand

**Problem:** the README opens with a paragraph. For a portfolio reviewer scanning GitHub, you have ~10 seconds before they bounce. The current README never says, on first glance, "this is impressive and reproducible."

### Tasks

| Task | File | What changes |
|---|---|---|
| 3.1 README hero rewrite | `README.md` (top 60 lines) | Hero image, value-prop sentence, 3-number claim ("60% faster than naïve mflux loop · 119 tests · 41-species catalog"), three CTAs (Install / Try the demo / See the gallery). Move the current intro to "About". |
| 3.2 Architecture diagram | `docs/ARCHITECTURE.md` + inline mermaid in README | Single mermaid diagram showing engine → dispatcher → mflux variant → QC trust layer → promote flow |
| 3.3 Quantified benchmarks section | `README.md` + `docs/BENCHMARKS.md` | Formal table with our measured numbers: P1 perf, FLUX.2 migration speed, multi-format input timings, catalog render estimates |
| 3.4 The "hard problems solved" section | `README.md` | Walk the 6 problems: tiger orange-lock, body-type-pose semantics, flat-folk vs photoreal, trust layer Q1, multi-seed batch P1, cultural-heritage attribution. Each links to a deeper doc. |
| 3.5 `forge demo` command | `bin/forge.py` | New CLI subcommand. `forge demo madhubani-tiger` renders one canonical Madhubani tiger in ~25s and prints the path. Maybe also `forge demo translate`, `forge demo audiobook`. Instant-gratification. |
| 3.6 Gallery rebrand | `bin/forge_gallery.py` + HTML templates | Make the local gallery landing page portfolio-grade: artist citations visible, the 7-item rubric explained per render, every output links to its directive.json for reproducibility. |
| 3.7 Top-of-README install simplification | `README.md` + `install.sh` (new) | One-command setup: `bash <(curl -fsSL ...)`. Handles `pip install -e .`, model cache check, `forge doctor --deep` confirmation. |

### Success criteria

- A first-time visitor reading the README top-30-lines understands: what Forge is, what's impressive about it, and how to try it
- `forge demo madhubani-tiger` produces output in <60s on M5 Max + opens the file
- The gallery page tells the cultural-heritage attribution story
- Benchmarks are reproducible (one command per row)

### Estimate: ~6 hrs (split across two sessions — 3 hrs README + arch diagram + benchmarks, 3 hrs demo command + gallery rebrand)

---

## Lane 4 — Open-source prep

**Goal:** the repo can be made public (today it's private at tommyvercetti76/Forge) with confidence about licensing + cultural attribution + clean state.

### Tasks

| Task | File | What changes |
|---|---|---|
| 4.1 `LICENSE` | new | Apache 2.0 for code. Standard text. |
| 4.2 `LICENSE-ART.md` | new | CC BY 4.0 for the Madhubani convention work, recipes, prompts, schemas. Attribution-required ("citing Sita Devi, Ganga Devi, Baua Devi, Mahasundari Devi"). |
| 4.3 `CONTRIBUTING.md` | new | How to add a species (animals.json + reference + attribution), how to add a Madhubani recipe, how to add a new specialist engine, the rubric for new tests |
| 4.4 `CODE_OF_CONDUCT.md` | new | Standard contributor covenant + Mithila-tradition respect clause |
| 4.5 FLUX licensing disclosure | `README.md` "Known Sharp Edges" section | Loud + explicit: FLUX models are under BFL's non-commercial license. Commercial use of generated outputs requires the user to obtain a commercial license from Black Forest Labs. |
| 4.6 Cultural-heritage statement | `README.md` + `LICENSE-ART.md` | The catalog is Madhubani-INSPIRED, not authentic. Customers should also support Mithila Art Institute. (Already in masters.json — surface it loudly.) |
| 4.7 Sample-data licensing | `brand/references/madhubani/_general/*.attribution.json` audit | Confirm every reference's license + attribution is captured (already verified today: 50 refs, 0 missing) |
| 4.8 `.github/` workflows | new | CI: run tests on every push. Lint Python (ruff). Validate JSON schemas. |
| 4.9 `SECURITY.md` | new | Disclosure email / process |

### Success criteria

- Anyone can read `LICENSE` + `LICENSE-ART.md` + `README` and know what they can and cannot do
- The FLUX commercial-license constraint is impossible to miss
- A first-time contributor knows how to add a new species or a new engine

### Estimate: ~2 hrs

---

## Lane 5 — LoRA training pilot (FUTURE, after lanes 1-4)

**Why park it:** today's prompt-stack work + Kontext img2img (lane 1) should get us to publishable quality WITHOUT training. LoRA becomes the "definitive lock" once the catalog is more mature.

**When to revisit:** after lane 3 lands and the README is portfolio-grade, the LoRA work becomes one of the marquee achievements rather than a debugging activity.

**Outline (for future planning):**

| Task | What |
|---|---|
| 5.1 Corpus assembly | pass_examples (4) + _legacy/v3 (~16 strong renders) + Wikimedia _general (50) = ~70 references. Filter to ~50 highest-quality. Caption each with the (animal, pose, body_type) triple. |
| 5.2 Training spec | `docs/MADHUBANI_LORA_PILOT.md`. Use mflux-train against `flux2-klein-4b`. Rank 16. Steps 1500-2000. Cloud or local (M5 Max can do this overnight). |
| 5.3 Training run | Modal/RunPod ($30-80) OR local M5 Max overnight |
| 5.4 Eval protocol | Render 8 NON-pilot species; if 6/8 visibly improved → ship; else iterate corpus |
| 5.5 Catalog render with LoRA | All 41 species × 4 poses ~75 min on M5 Max with batched mflux |
| 5.6 Hosted demo | HuggingFace Space or Modal app — let non-Mac visitors try one render |

### Estimate: 3 days (multi-session)

---

## Cross-cutting: branch + commit hygiene

- **Lane 1** continues on `feature/madhubani-flux2-migration` (it's a direct continuation of today's L1+L2+N1-rev2 work)
- **Lane 2** gets its own branch `feature/poses-v3-by-body-type` (architectural change; reviewable on its own)
- **Lane 3** gets `feature/portfolio-presentation` (presentation refactor; independent)
- **Lane 4** gets `feature/oss-prep` (legal/governance; independent)
- **Lane 5** gets `feature/madhubani-lora-pilot` (cloud + corpus + training; multi-day)

Once a lane lands, **merge to main**. The user's mockup work currently on main remains unblocked.

---

## Verification protocol — what does "lane done" mean

Per lane, before merge:

1. **All 119+ existing tests pass** (no regressions)
2. **New tests added** for the new code/data (where applicable)
3. **A verification render or output produced** that demonstrates the lane's success criterion (image, audio, manifest, log)
4. **A short verification doc** at `docs/LANE_<N>_VERIFICATION.md` linking the artifacts
5. **`forge doctor --deep`** still passes
6. **Working tree clean on the lane's branch** after commit

---

## What "portfolio-grade on first glance" means concretely

For a reviewer (recruiter, hiring manager, ML researcher) scanning GitHub:

| Time spent | What they see | Should think |
|---|---|---|
| **5 seconds** | Hero image + 3-number claim + "Local-first MLX on Apple Silicon" | "This is real, not toy" |
| **30 seconds** | Three CTAs (Install / Demo / Gallery), benchmarks table, architecture diagram visible | "This is professional. Reproducible. Local-first is a real differentiator." |
| **3 minutes** | "Hard problems solved" section, links to engine_qc trust layer, MADHUBANI_ART_IDENTITY.md, BIBLIOGRAPHY | "This person thinks in systems. They reason about prompt engineering rigorously. They cite their cultural references. They built a research-grade trust layer for QC. They know how to ship." |
| **30 minutes** | Source-dive — they read style_engines.py, forge_madhubani.py, engine_qc.py, the Q1 trust layer | "This is portfolio-grade engineering. I want to talk to this person." |

That last reaction is what makes Forge worth presenting. Lanes 1-4 are the surface area that gets them to the source code in the right state of mind.

---

## The honest "what won't be done by EOD-2"

- LoRA training (Lane 5 — needs corpus + GPU + day-cycle)
- Decoration-density temperature knob (parked from earlier in the session)
- Variant tier — Kachni / Godna / Pichwai / Warli / Gond LoRAs (post-Madhubani-pilot)
- A `forge bench` shootout against cloud Replicate/Runway equivalents (would be a great portfolio asset but heavy)
- `forge_web` UI deep polish (the Translate Studio is shipped but the rest of `forge_web.py` is dense)

These are the "v1.1" roadmap items. Document them in `README.md` as "What's next" so a portfolio viewer sees ambition without seeing them as unfinished work.

---

## My recommendation on sequence

1. **Tomorrow (or whenever you resume):** Lane 1. 1.5 hrs. **Tiger looks like a tiger; the corpus finally informs renders.** This addresses your specific feedback directly.
2. **Same session if energy holds:** Lane 2. 3 hrs. **Schema migration so "seated peacock" is gone.**
3. **Day 2:** Lane 3 first half (3 hrs). README hero + arch + benchmarks.
4. **Day 2 evening:** Lane 3 second half + Lane 4. 5 hrs. `forge demo` + gallery rebrand + LICENSE files.
5. **Day 3:** Buffer. Polish. Verification renders. Optional: open a PR from the feature branches into main, review them together as one merge sweep.
6. **Day 4+:** Lane 5 (LoRA pilot) as a separate multi-day track.

**Total elapsed: 3 focused days to portfolio-grade. Lane 5 adds 3 more for the LoRA polish.**

---

## Sign-off criteria

When you can answer YES to each of these, Forge is portfolio-ready:

- [ ] First-time GitHub visitor understands what Forge is and what's impressive about it within 30 seconds
- [ ] `forge demo madhubani-tiger` runs in <60s on M5 Max and produces a tiger that LOOKS LIKE A TIGER
- [ ] All 5 priority Madhubani species (tiger, peacock, elephant, cobra, blackbuck) render at production quality with the new poses + Kontext + style references
- [ ] Architecture diagram is in the README
- [ ] Benchmarks table is in the README with reproducible commands per row
- [ ] LICENSE files (Apache 2.0 for code, CC BY 4.0 for art identity) are present
- [ ] Cultural-heritage attribution to the Mithila tradition is loud and visible
- [ ] FLUX-non-commercial-license constraint is impossible to miss
- [ ] 119+ tests pass on main
- [ ] `forge doctor --deep` exits clean
- [ ] No `~/.forge-state/` or other transient state in the repo
- [ ] Reference image binaries gitignored; manifests committed

Done means done.
