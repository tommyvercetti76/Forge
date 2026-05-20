# Art Reasoning Engine — architecture spec

> A closed-loop image-generation system that **enforces** the art identity rather than **hopes** the prompt is heard. The user named this after Phase A hit the prompt-only ceiling: even with 17,000-character prompts containing MANDATORY DECORATION ZONES + ANATOMICAL COUNTS + DECORATION DENSITY, FLUX.2 still rendered cobras with two tongues, peacocks with sparse plumage, and tigers missing the named decoration zones. The text encoder truncates past ~2k chars. Prompt iteration alone cannot solve this.
>
> **Established:** 2026-05-20, after Phase A. Spec doc precedes implementation.

---

## Why this exists

| Wall hit | Evidence |
|---|---|
| FLUX text encoder context limit | Tiger prompt of 17,563 chars; T5-XXL effective context ~256-512 tokens (~1500-2000 chars); new MANDATORY clauses at the prompt tail are demonstrably not landing |
| Per-feature instruction dilution | "ANATOMICAL COUNTS (strict): tongue=1 forked-tip, NOT two separate tongues" present in prompt; cobra still rendered with two tongues |
| Reference vs prompt conflict | v3 tiger style-reference at strength 0.55-0.67 OVERRODE the prompt's MANDATORY DECORATION ZONES; tiger came out as a copy of the (sparse) reference rather than the (dense) prompt directive |
| Decoration density target failure | `decoration_density: maximal` directive in the prompt for peacock; rendered output is sparse |

The unifying observation: **the system has no notion of "did the output actually meet the rules."** Renders ship if they file-validate (>1KB, correct dimensions, correct codec) — but the artistic correctness of the output relative to the schema is not measured.

We need to:
1. **Make the schema machine-readable and testable** (already started in Phase A — `required_decoration_zones`, `anatomical_count_constraints`, `decoration_density`).
2. **Measure the rendered output against the schema** (Phase B — the verification layer).
3. **Re-render with targeted boosts when verification fails** (Phase C — the reasoning loop).
4. **Learn over time which prompt variants score highest per (species, pose)** (Phase D — feedback memory).

---

## The four components

```
                          ┌────────────────────────────────┐
                          │  brand/madhubani/animals.json  │
                          │  brand/madhubani/poses.json    │  ← (1) SCHEMA
                          │  brand/madhubani/palette.json  │
                          └──────────────┬─────────────────┘
                                         │
                                         ▼
   prompt assembly  ──▶  mflux-generate-flux2  ──▶  PNG output
                                                      │
                                                      ▼
                          ┌────────────────────────────────┐
                          │  bin/madhubani_qc.py           │
                          │  (palette + corners + center   │
                          │   + body_fill + text_leak +    │
                          │   eye + pattern_density +      │
                          │   anatomy_heuristics +         │
                          │   decoration_zone_presence)    │  ← (2) VERIFICATION
                          └──────────────┬─────────────────┘
                                         │
                                         ▼ score per dimension
                          ┌────────────────────────────────┐
                          │  bin/art_reasoning_engine.py   │
                          │  → identify weakest dimension  │
                          │  → assemble targeted boost     │
                          │  → re-render OR pick best of N │  ← (3) REASONING LOOP
                          └──────────────┬─────────────────┘
                                         │
                                         ▼ final accepted render
                          ┌────────────────────────────────┐
                          │  brand/madhubani/learning/     │
                          │    runs.jsonl                  │
                          │    score_by_prompt.jsonl       │  ← (4) FEEDBACK MEMORY
                          │    species_winning_prompts.md  │
                          └────────────────────────────────┘
```

---

## (1) Schema — machine-readable rules

**Already shipped (Phase A):**
- `animals.json:body_type` — taxonomy + per-body-type anatomy_rules
- `animals.json:body_fill_color` — Madhubani convention (indigo / walnut / forest-teal)
- `animals.json:anatomy_must_include` — diagnostic field marks per species
- `animals.json:required_decoration_zones` — named zones the output must show
- `animals.json:anatomical_count_constraints` — per-feature count rules
- `animals.json:decoration_density` — minimal / balanced / ornate / maximal
- `poses.json:body_type_overrides` — per-body-type pose semantics

**Future schema additions (Phase B/C):**
- `decoration_zone_locations` — bounding-box hints where each zone is expected to appear (head=top-25%, neck=top-35%-to-50%, anklets=bottom-20% near legs)
- `palette_zone_compliance` — which folk colors each zone should use
- `prompt_boost_per_failure` — per-(species, failure-dimension) a targeted prompt addition that fixes that failure

---

## (2) Verification layer

**Already shipped (Wave 1 Q1 + A2):**
- color_floor (≥4 of 6 folk hues visibly present)
- corners_clean (no painter marks in corners)
- subject_centered (subject bbox + center within bounds)
- body_fill (saturated color, not blank silhouette)
- text_leak (Tesseract OCR for hallucinated Devanagari glyphs)
- eye_character (head-region luminance contrast)
- anatomy (leg pillar count — currently disabled_by_default due to 50% FP on curated corpus)

**Phase B additions:**

| Check | Method | Threshold per density |
|---|---|---|
| `pattern_density` | Compute % of subject mask pixels that are NOT close to body_fill_color (Δ-E LAB > 14). Higher = more decoration. | minimal ≥10%, balanced ≥25%, ornate ≥45%, maximal ≥65% |
| `decoration_zone_presence` | For each required_decoration_zone in animals.json, look at the expected region (head/neck/joints/etc.) and verify there's non-body-fill color there. | All required zones must show decoration |
| `anatomy_feature_count` | For each anatomical_count_constraint, attempt a heuristic count. E.g., cobra tongue: detect red elongated shapes in mouth region; count them. Limited but catches gross failures. | Count matches constraint |
| `palette_compliance` | For each named zone, check that the dominant colors match palette.json. | Body matches body_fill_color; ornaments use folk palette |
| `clip_prompt_alignment` (stretch) | If mlx-clip available, score prompt-image cosine similarity. Catches "subject doesn't match prompt." | ≥0.22 |

Each check returns `{pass: bool, score: float, detail: dict}`. The `disabled_by_default` mechanism (already in `engine_qc.derive_blockers`) lets us ship checks that aren't yet reliable.

---

## (3) Reasoning loop

```python
def render_with_reasoning(
    animal_slug: str,
    pose_slug: str,
    *,
    max_attempts: int = 3,
    seeds_per_attempt: int = 4,
    accept_score: float = 0.85,
) -> RenderResult:
    """
    Render an animal × pose with iterative refinement.
    Each attempt:
      1. Build subject_string from animals.json + poses.json + animal's current targeted boosts
      2. Render seeds_per_attempt seeds (uses the existing P1 multi-seed batch)
      3. For each seed, run madhubani_qc.score_madhubani_png()
      4. Pick the best-scoring render
      5. If best_score >= accept_score → return it (success)
      6. Else: identify the weakest failed dimension(s); assemble targeted boost; retry
    
    Failure → return the best attempted render with all blockers documented.
    """
```

**The targeted boost** is per-failed-dimension. Examples:

| Failed dimension | Boost added to next attempt's prompt |
|---|---|
| `pattern_density: 0.18 (need 0.45)` | "URGENT: the body silhouette is TOO SPARSE. Add 3-4 more decoration zones inside the body — saddle blanket + anklets + neck collar + shoulder medallion. The body must NOT be a flat shape." |
| `decoration_zone_presence: missing 'forehead tikka'` | "URGENT: render a small circular tikka medallion (vermillion + saffron, ~2cm) BETWEEN the eyes on the forehead — this is REQUIRED." |
| `anatomy_feature_count: cobra has 2 tongues (need 1)` | "ABSOLUTE: the cobra has EXACTLY ONE forked tongue — ONE structure with a single split tip. NOT two separate tongues. Mouth closed by default; remove the extra tongue." |
| `color_floor: 2 hues (need 4)` | "URGENT: the design currently uses only 2 colors. Add at least 2 more folk hues from the palette (indigo / leaf-green / saffron / vermillion / gold)." |
| `subject_centered: bbox at 0.32 (need 0.55-0.85)` | "URGENT: the subject is too small relative to the canvas. Render it larger so its bounding box fills 55-85% of the frame." |

**Best-of-N seed selection** is a cheaper variant: render 4 seeds with the same prompt, score each, pick the best. Avoids the retry-with-boost cost when the dispersion across seeds happens to include a good render.

---

## (4) Feedback memory

`brand/madhubani/learning/runs.jsonl` — one JSON line per render attempt:

```json
{
  "ts": "2026-05-20T22:14:00Z",
  "animal_slug": "tiger",
  "pose_slug": "seated-rest",
  "attempt": 1,
  "seed": 8302,
  "prompt_hash": "sha256:...",
  "prompt_length_chars": 4126,
  "scores": {
    "pattern_density": 0.62,
    "color_floor": true,
    "decoration_zone_presence": {"forehead_tikka": false, "neck_collar": true, "anklets": false, "body_zones": true},
    "anatomy_feature_count": {"legs_visible": 4, "tongue": "ok"}
  },
  "accepted": false,
  "weakest_dimension": "decoration_zone_presence.forehead_tikka",
  "boost_applied": "URGENT: render small circular tikka medallion between eyes ..."
}
```

`forge madhubani learn` — periodic batch job that:
- Mines runs.jsonl for prompt variants that produced high scores per (species, pose, density)
- Outputs `brand/madhubani/learning/species_winning_prompts.md` — the "what works" knowledge base
- Optionally proposes updates to `animals.json:required_decoration_zones` based on what scores well

---

## Implementation sequence

| Phase | What ships | Effort |
|---|---|---|
| **B.1** Pattern density verification | madhubani_qc.py gains `_score_pattern_density()`. Maps measured density to the target band. Fail if 1 band below target (e.g., maximal expected but balanced rendered). | 2 hrs |
| **B.2** Decoration zone presence | madhubani_qc.py gains `_score_decoration_zone_presence()`. For each required_decoration_zone, examines the expected region (head/neck/joints/etc.) for non-body-fill pixels. | 4 hrs |
| **B.3** Anatomy feature count heuristics | madhubani_qc.py gains per-body-type `_score_anatomy_feature_count()`. Cobra tongue count via red-shape detection; rhino horn count via top-of-head shape detection; etc. | 4 hrs |
| **B.4** Wire all new checks into engine_qc.derive_blockers → publishable | engine_qc.py + manifest schema; new checks emit blockers; promote refuses non-passing per existing Q1 contract | 1 hr |
| **C.1** Multi-seed best-of-N selection | New CLI flag `--pick-best` on forge_madhubani render. Score N seeds, output the highest-scoring + variant index. | 3 hrs |
| **C.2** Retry-with-targeted-boost loop | New module `bin/art_reasoning_engine.py`. Identifies weakest dimension, generates per-dimension prompt boost, retries up to max_attempts. | 5 hrs |
| **D.1** Feedback memory schema | runs.jsonl writer + read API | 2 hrs |
| **D.2** `forge madhubani learn` command | mines runs.jsonl for top prompts per (species, pose) | 4 hrs |

**Total: ~25 hrs across ~5-6 focused sessions.**

---

## Why this is portfolio-grade

This architecture solves a real ML engineering problem:

1. **It demonstrates closed-loop thinking** — render → measure → diagnose → retry. The standard "single-shot prompt" loop isn't enough at scale; serious systems verify.
2. **It demonstrates schema-driven generation** — rules are machine-readable, not just in prose. Future hires/contributors can reason about the system without reading every prompt.
3. **It demonstrates honest scoring** — outputs are accepted or flagged based on objective dimensions; the system doesn't lie about quality.
4. **It demonstrates compound learning** — over time the catalog gets better because winning prompts feed forward.
5. **All on Apple Silicon, MLX-native, local-first.** No cloud APIs.

When a portfolio reviewer reads `bin/art_reasoning_engine.py` they will understand they're looking at someone who **builds systems**, not someone who **calls APIs**.

---

## References / prior art

- **FLUX text encoder limits**: T5-XXL effectively ~256-512 tokens; CLIP path ~77 tokens. Position-weighted attention attenuates tail tokens. (BFL FLUX paper; mflux source)
- **Best-of-N selection in diffusion**: standard practice in production text-to-image systems; trade compute for quality.
- **CLIP-style prompt-image alignment**: OpenAI CLIP for cosine similarity; aesthetic predictors as quality proxies. `mlx-clip` ports the inference to Apple Silicon.
- **Schema-driven generation**: Stable Diffusion XL Refiner pattern (multi-stage); ControlNet for structural conditioning; LoRA for style baking.
- **Madhubani convention encoding**: per `docs/MADHUBANI_ART_IDENTITY.md`, the catalog's authoritative art-identity reference. Bibliography in `docs/MADHUBANI_BIBLIOGRAPHY.md`.

---

## Sign-off criteria

When the Art Reasoning Engine is "done":

- [ ] Tiger seated-rest renders pass `pattern_density ≥ 0.45` (ornate) on the first attempt with the new schema
- [ ] Cobra seated-rest renders pass `anatomy_feature_count.tongue == 1` on first or second attempt
- [ ] Peacock seated-rest renders pass `pattern_density ≥ 0.65` (maximal) within 3 attempts
- [ ] `forge madhubani render <animal> --reason --pick-best 4` produces a publishable render in 1 invocation
- [ ] `forge madhubani learn` outputs a winning-prompts knowledge base
- [ ] All 119 existing tests still pass; new tests cover each verification primitive
- [ ] `docs/ART_REASONING_ENGINE.md` is up-to-date with what's actually shipped

Done means done.
