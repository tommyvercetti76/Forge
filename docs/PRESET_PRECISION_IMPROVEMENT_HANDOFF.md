# Preset Precision Improvement Handoff

Status: research-backed implementation handoff  
Target: improve Forge brand preset precision by at least 40% relative  
Scope: `brand/presets/*.json`, prompt assembly, preset evaluation, and gallery feedback loops

## Goal

Improve the precision of Forge's brand presets so a user can pick a preset, write a normal prompt, and get an image that more reliably matches the intended visual contract: style, subject layout, lighting, palette, thumbnail-safe space, and technical quality.

This is not a vibe rewrite. This is a measurable preset-quality project.

## Definition Of Precision

For this project, preset precision means:

> The percentage of generated images that satisfy the preset's declared visual contract without manual prompt rescue.

Each output is scored against preset-specific pass/fail criteria:

- Style identity: does the image clearly belong to the preset?
- Subject adherence: does the requested subject appear correctly?
- Composition: does the subject placement match the preset and overlay needs?
- Palette: does the image approximate the 60/30/10 palette intent?
- Lighting/rendering: does the image honor the preset's lighting/material contract?
- Failure suppression: no text artifacts, watermark, obvious anatomy failures, wrong style, or AI-gloss.
- Thumbnail usability: if the preset is used for thumbnails, the headline zone remains readable.

## 40% Improvement Target

Measure baseline before changing presets.

Formula:

```text
precision = passing_images / total_images
target_precision = min(0.95, baseline_precision * 1.40)
```

Examples:

- Baseline 45% -> target 63%.
- Baseline 55% -> target 77%.
- Baseline 65% -> target 91%.

If baseline is below 40%, require at least +20 percentage points as a floor because a pure relative target can still leave the tool weak.

## Current Preset Inventory

Forge currently has seven JSON presets:

| Preset | Current Role | Main Risk |
|---|---|---|
| `cinematic` | movie-poster / dramatic thumbnail background | Generic cinematic language; weak layout-safe contract |
| `documentary` | restrained journalistic image | Uses prompt negation for "not staged"; no verification of documentary realism |
| `editorial` | magazine-cover / essay image | White/cream negative-space intent is not structurally enforced |
| `thumbnail-bold` | text-over-video-frame thumbnail | Good overlay preset, but background generation still weakly protects lower third |
| `darksiders` | weathered gothic fantasy illustration | Stronger identity than most; too much packed into one prose block |
| `batman-noir` | monochrome comic-noir | Strong style, but optional red accent and monochrome rules can conflict |
| `tartakovsky` | flat cel animation | Master primer can fight flat-color cel style by asking for micro-details |

Current shared pattern:

- Each preset has `flux.positive_prefix`, `flux.positive_suffix`, `flux.negatives`, `guidance`, and `steps`.
- Each has 3-5 `prompt_rules.always_add`.
- Each has `palette_60_30_10`.
- Each has thumbnail composition metadata.
- None has a benchmark suite, evaluation rubric, reference image set, style atom list, or expected failure modes.

## Research Basis

These rules are grounded in current text-to-image evaluation and FLUX behavior:

- Black Forest Labs' FLUX.1 dev model card says prompt following is heavily influenced by prompting style and that the model can fail to match prompts. Source: [FLUX.1 dev model card](https://github.com/black-forest-labs/flux/blob/main/model_cards/FLUX.1-dev.md).
- Hugging Face Diffusers documents that FLUX guidance scale increases prompt alignment at the cost of image quality. Source: [Diffusers FLUX docs](https://huggingface.co/docs/diffusers/api/pipelines/flux).
- T2I-CompBench++ shows that modern text-to-image models still struggle with compositional prompts, including attribute binding, relationships, numeracy, and complex compositions. Source: [T2I-CompBench++](https://arxiv.org/abs/2307.06350).
- GenEval argues holistic metrics such as FID/CLIPScore are insufficient for fine-grained instance-level alignment and evaluates object co-occurrence, position, count, and color. Source: [GenEval](https://arxiv.org/abs/2310.11513).
- TIFA evaluates text-to-image faithfulness by converting prompts into visual questions and using VQA. This maps well to preset contracts such as "is the lower third uncluttered?" Source: [TIFA](https://arxiv.org/abs/2303.11897).
- CLIPScore supports reference-free image-text compatibility scoring, useful as a weak automatic signal but not enough alone for preset precision. Source: [CLIPScore](https://arxiv.org/abs/2104.08718).
- ImageReward and PickScore show that human preference/ranking data is valuable for text-to-image evaluation and often correlates better with user preference than simple image-text similarity. Sources: [ImageReward](https://arxiv.org/abs/2304.05977), [Pick-a-Pic / PickScore](https://arxiv.org/abs/2305.01569).
- FLUX.1 Kontext introduced benchmark categories including style reference and character reference, reinforcing that reference-conditioned workflows are important for consistency and style precision. Source: [FLUX.1 Kontext paper](https://arxiv.org/abs/2506.15742).

## Current Gaps

### P0: Presets Have No Measurable Contract

Today a preset is prose plus palette plus typography. There is no machine-readable definition of what success means.

Required fix:

- Add `precision_contract` to every preset.
- Add contract-level evaluation questions.
- Add benchmark prompts and expected properties.
- Add pass/fail scoring.

### P0: Prompt Rules Are Not Atomized

Most presets compress style, lighting, composition, texture, and constraints into one paragraph. Text-to-image models are better evaluated and debugged when prompts are decomposed into object, attribute, color, position, and relationship atoms.

Required fix:

- Split each preset into explicit atoms:
  - `style_atoms`
  - `composition_atoms`
  - `lighting_atoms`
  - `palette_atoms`
  - `surface_atoms`
  - `camera_atoms`
  - `thumbnail_safety_atoms`
  - `failure_atoms`

### P0: Negative Language Is Overused

The current presets rely on `negatives` and suffix phrases like `NOT busy`, `NO gradients`, and `NOT staged`.

This is risky because text-to-image models often struggle with negation-like instructions, and Forge already bakes negatives into a positive prompt block as "DO NOT include." Keep hard failure terms, but rewrite stylistic exclusions as positive targets.

Examples:

| Current | Better |
|---|---|
| `NOT busy` | `one clear focal subject with empty supporting space` |
| `NO gradients` | `flat color fills with hard-edged shadow shapes` |
| `NOT staged` | `observational distance, candid posture, imperfect real environment` |
| `no crowds` | `single subject only, background contains environment not people` |

Required fix:

- Keep only concrete artifact negatives: `watermark`, `text artifacts`, `extra fingers`, `logo`.
- Move style negatives into positive constraints.

### P0: Thumbnail-Safe Composition Is Not Enforced In Background Generation

The overlay renderer knows where text goes, but background generation only weakly receives this requirement.

Example:

- `thumbnail-bold` says lower third clear.
- Other presets have lower text bands but do not always tell FLUX to keep the lower band uncluttered.

Required fix:

- Add `safe_zones` to presets.
- Prompt builder must include safe-zone instructions when generating thumbnail backgrounds.
- Evaluation must check safe-zone clutter.

### P0: No Preset Benchmark Harness

Without a benchmark, "40% better" is unknowable.

Required fix:

- Add a deterministic preset benchmark:
  - 7 presets
  - 12 prompts per preset
  - 4 seeds per prompt
  - same seeds before/after
  - human and automatic scoring

Minimum benchmark size:

```text
7 presets * 12 prompts * 4 seeds = 336 images per run
```

### P1: Master Primer Can Contaminate Stylized Presets

Forge appends a universal `MASTER_POSITIVE_HINT` to every generation. It asks for crisp edges and micro-details including pores, weave, tarnish, scratches, capillaries, leaf veins, etc.

This can help photoreal/editorial work, but it can fight presets like `tartakovsky`, where flat fills and simplified shape language are the point.

Required fix:

- Add per-preset `master_primer_policy`.
- Options:
  - `full`
  - `photo_only`
  - `style_safe`
  - `off`
- Add preset-specific craft hints instead of one universal material block.

### P1: Guidance And Steps Are Not Empirically Tuned Per Preset

Current settings:

| Preset | Guidance | Steps |
|---|---:|---:|
| `cinematic` | 4.5 | 30 |
| `documentary` | 4.0 | 22 |
| `editorial` | 4.0 | 25 |
| `thumbnail-bold` | 4.0 | 22 |
| `darksiders` | 4.5 | 28 |
| `batman-noir` | 4.5 | 28 |
| `tartakovsky` | 3.5 | 25 |

These may be reasonable, but they are not measured. Diffusers documents a prompt-alignment versus quality tradeoff for guidance, so each preset should be tuned against its own contract.

Required fix:

- Benchmark each preset at candidate guidance values.
- Recommended starting grid:
  - Photo presets: `3.0`, `3.5`, `4.0`, `4.5`
  - Illustration presets: `3.5`, `4.5`, `5.5`, `6.5`
  - Flat cel preset: `3.0`, `3.5`, `4.0`, `4.5`
- Steps grid:
  - `18`, `25`, `30`, `36`

### P1: No Reference Image Or LoRA Strategy At Preset Level

`flux_generate` already looks for `preset.get("lora_paths")` and `preset.get("lora_scales")`, but current presets do not use those fields. `brand/loras/README.md` documents useful LoRAs, yet presets are not wired to any default stack.

Required fix:

- Add optional preset-level LoRA stack fields.
- Add reference sets under `brand/references/presets/<preset>/`.
- For style-critical presets, run A/B with and without LoRA/reference conditioning.

### P1: Palette Intent Is Not Validated

The 60/30/10 palette is in the prompt, but there is no image-side measurement.

Required fix:

- Add a palette checker that samples non-text image regions.
- Compute approximate dominant/secondary/accent hue families.
- Treat palette as a soft score, not a hard fail, because lighting and subject color can legitimately vary.

### P1: Preset Roles Overlap

`cinematic`, `thumbnail-bold`, `darksiders`, and `batman-noir` all produce dramatic, high-contrast images with bottom text overlays. Their contracts need stronger separation.

Required fix:

- Add a "preset confusion" test: render the same prompt through all presets and score whether a reviewer can identify the intended preset.
- Done when preset identity classification is at least 80% accurate.

### P2: Typography Metadata Is Good But Not Connected To Evaluation

Typography is not generated by FLUX; it is applied later by `render_thumbnail`. The preset precision benchmark should separately score:

- background generation precision
- overlay legibility
- final thumbnail precision

Required fix:

- Add final-composite tests using representative headlines.
- Check truncation, font fallback, contrast, and text bounding boxes.

## Proposed Preset Schema

Add this field to each preset:

```json
{
  "precision_contract": {
    "intent": "one-sentence purpose of the preset",
    "primary_use": "thumbnail_background | editorial_image | documentary_image | title_card",
    "style_atoms": [],
    "composition_atoms": [],
    "lighting_atoms": [],
    "camera_atoms": [],
    "surface_atoms": [],
    "palette_atoms": [],
    "thumbnail_safety_atoms": [],
    "hard_failure_terms": [],
    "master_primer_policy": "full | photo_only | style_safe | off",
    "safe_zones": [
      {
        "name": "lower_third",
        "bbox_pct": [0.0, 0.62, 1.0, 1.0],
        "required": "low detail, no faces, no subject-critical object"
      }
    ],
    "eval_questions": [
      {
        "id": "style_identity",
        "question": "Does the image clearly match the preset style?",
        "required": true
      }
    ],
    "benchmark_prompts": []
  }
}
```

Add optional LoRA fields:

```json
{
  "lora_paths": [
    "brand/loras/add-details/example.safetensors"
  ],
  "lora_scales": [0.5]
}
```

## Prompt Assembly Changes

Current assembly order in `build_flux_prompt`:

1. series style lock
2. preset positive prefix
3. scene
4. world/cast
5. palette line
6. constraints
7. all negatives as `DO NOT include`
8. positive suffix
9. master positive hint

Proposed order:

1. user scene
2. preset intent
3. style atoms
4. composition atoms
5. lighting/camera atoms
6. subject detail atoms
7. palette atoms
8. thumbnail safe-zone atoms
9. hard failure exclusions only
10. preset-specific craft hint
11. optional series/cast locks near the scene block

Reason:

- Put the user subject early so the model does not overfit to style prose before knowing what to draw.
- Keep atoms separated so failures can be traced to missing contracts.
- Reduce broad negation.
- Avoid style contamination from the universal master hint.

## Preset-Specific Recommendations

### cinematic

Current issue:

- Strong cinematic mood, but generic and easily collapses into "dark AI movie still."
- Needs clearer shot grammar and thumbnail-safe composition.

Add atoms:

- one subject in upper/mid frame
- readable silhouette
- single motivated key light
- visible foreground/midground/background depth layers
- lower third remains low-detail when used as thumbnail

Tune:

- benchmark guidance `3.5`, `4.0`, `4.5`, `5.0`
- compare 25 vs 30 steps

Done:

- 75%+ outputs have clear subject silhouette and no busy lower third.

### documentary

Current issue:

- Relies on negation to avoid staged/overproduced.
- "New York Times feature" is useful but vague.

Add atoms:

- candid posture
- imperfect real environment
- neutral lens, no heroic low angle
- available light
- factual subject context visible

Rewrite:

- Replace `NOT staged` with `observational candid posture and real environmental context`.
- Replace `NOT overproduced` with `plain available-light documentary realism`.

Done:

- 80%+ outputs read as plausible documentary stills, not movie posters.

### editorial

Current issue:

- Negative space intent is strong in text but not layout-enforced.

Add atoms:

- subject occupies 35-55% of frame
- large clean margin on top-left or top-right
- soft background with low object density
- magazine cover crop

Add eval:

- "Is there enough clean space for headline?"
- "Is the subject sharp and isolated?"

Done:

- 80%+ outputs preserve a clean title zone.

### thumbnail-bold

Current issue:

- Best purpose-built preset, but should become the standard for safe overlays.

Add atoms:

- subject upper two-thirds
- lower third has simple tonal background
- no face below 60% vertical frame
- no high-frequency detail behind text

Add automatic check:

- lower-third edge density below threshold
- text contrast ratio pass on final composite

Done:

- 90%+ final thumbnails pass text legibility.

### darksiders

Current issue:

- Strong identity, but too many style clauses packed into prose.

Split into:

- gothic fantasy concept art
- charcoal/bronze/orange triad
- weathered material surfaces
- heroic asymmetric pose
- smoke/embers/dust in rim light

Move negatives:

- `clean polished surfaces` -> `weathered scratched surfaces`
- `perfect symmetry` -> `asymmetric heroic pose`
- `smooth gradient sky` -> `smoky textured atmosphere`

Done:

- 75%+ outputs preserve weathered gothic identity without drifting into generic fantasy.

### batman-noir

Current issue:

- Strong monochrome contract but optional red accent can conflict with "black-and-white."

Add modes:

- `pure_monochrome`
- `monochrome_with_single_red_accent`

Add atoms:

- 60% black ink mass
- one hard rim light
- rough paper/ink texture
- no smooth digital shading

Done:

- 85%+ outputs are truly monochrome unless red-accent mode is selected.

### tartakovsky

Current issue:

- Universal master primer asks for micro-detail that conflicts with flat cel animation.

Set:

```json
"master_primer_policy": "style_safe"
```

Add style-safe craft hint:

- hard-edged flat shapes
- two-tone shadow maximum
- thick uniform outlines
- simplified background geometry
- readable silhouette

Remove or rewrite:

- Avoid "NO gradients" as primary strategy; say "flat color fills with hard shadow edges."

Done:

- 85%+ outputs avoid photorealism, gradients, and chibi/anime drift.

## Benchmark Design

### Prompt Bank

Create:

```text
brand/presets/benchmarks/
  cinematic.json
  documentary.json
  editorial.json
  thumbnail-bold.json
  darksiders.json
  batman-noir.json
  tartakovsky.json
```

Each file should include 12 prompts:

- 4 human subjects
- 2 animals
- 2 objects/products
- 2 environments
- 1 action scene
- 1 edge case likely to break the preset

Each prompt should include expected visual atoms.

Example:

```json
{
  "id": "cinematic-hero-rain",
  "prompt": "a lone courier holding a sealed letter in heavy rain outside an old train station",
  "expected": {
    "single_subject": true,
    "rain_or_particulate": true,
    "dramatic_key_light": true,
    "lower_third_safe": true
  }
}
```

### Render Matrix

Baseline:

```text
7 presets * 12 prompts * 4 seeds = 336 images
```

Settings:

- use same seeds before/after
- render at base 1280x720
- no manual prompt edits
- save generated prompt text
- save preset version hash

### Scoring

Use a two-layer score:

1. Human reviewer pass/fail.
2. Automatic assist metrics.

Automatic metrics:

- CLIPScore for image-text compatibility.
- ImageReward or PickScore for broad preference.
- VQA/TIFA-style questions for preset-specific attributes.
- Palette sampler for color policy.
- Edge-density/face-position check for thumbnail safe zone.

Do not let automatic scores be the only source of truth. Use them to triage and catch regressions.

## Acceptance Criteria

### P0 Done

- Every preset has `precision_contract`.
- Every preset has at least 12 benchmark prompts.
- Benchmark runner renders baseline and candidate outputs with identical seeds.
- Scoring report computes precision per preset and overall.
- Overall precision improves by at least 40% relative.
- No preset regresses by more than 5 percentage points.

### P1 Done

- `build_flux_prompt` uses atomized contracts.
- Master primer policy is honored per preset.
- Safe-zone instructions are included for thumbnail/background generation.
- Preset negatives are trimmed to hard failures only.
- Guidance/steps are tuned from benchmark results.

### P2 Done

- Gallery ratings capture preset id for thumbnail/brief/background renders, not only style-engine renders.
- Web UI can show "best preset settings" based on benchmark + ratings.
- A preset confusion matrix is generated.
- A one-page preset card is generated for each preset.

## Proposed Files To Add

```text
docs/PRESET_PRECISION_SCIENCE.md
docs/PRESET_PRECISION_AUDIT_RESULTS.md
brand/presets/schema.json
brand/presets/benchmarks/cinematic.json
brand/presets/benchmarks/documentary.json
brand/presets/benchmarks/editorial.json
brand/presets/benchmarks/thumbnail-bold.json
brand/presets/benchmarks/darksiders.json
brand/presets/benchmarks/batman-noir.json
brand/presets/benchmarks/tartakovsky.json
bin/preset_bench.py
```

## Proposed Code Changes

### `bin/forge.py`

- Update `build_flux_prompt` to read `precision_contract`.
- Add per-preset `master_primer_policy`.
- Add prompt output sidecar for every thumbnail/background render.
- Add optional preset-level `lora_paths` and `lora_scales` validation.

### `bin/forge_gallery.py`

- Add preset-aware render capture for thumbnail and brief outputs.
- Store `preset_id`, `prompt_text`, `benchmark_id`, and `contract_version`.

### `bin/forge_web.py`

- Surface preset precision status:
  - "Benchmark pass rate"
  - "Best guidance"
  - "Known failure modes"
- Add "Run preset benchmark" system action later, not in the first cut.

### `brand/presets/*.json`

- Add `precision_contract`.
- Convert broad negatives into positive atoms.
- Add safe zones.
- Add primer policy.
- Add benchmark prompts or references to benchmark files.

## Work Plan For Agent

### Phase 1: Baseline Audit

Tasks:

- Render benchmark pack for all seven presets.
- Score outputs manually using the rubric.
- Record automatic scores if available.
- Write `docs/PRESET_PRECISION_AUDIT_RESULTS.md`.

Done:

- Baseline precision is known overall and per preset.
- Top three failure modes per preset are documented.

### Phase 2: Schema And Prompt Refactor

Tasks:

- Add `precision_contract` schema.
- Update presets.
- Update prompt builder.
- Keep old preset fields working for backward compatibility.

Done:

- Existing commands still run.
- New prompt sidecars show atomized prompt sections.

### Phase 3: Preset Rewrites

Tasks:

- Rewrite each preset into atoms.
- Remove broad negation.
- Add safe-zone rules.
- Add per-preset primer policies.

Done:

- JSON validates.
- Prompt output is readable and short enough.

### Phase 4: Benchmark And Tune

Tasks:

- Re-render full matrix.
- Try guidance/steps grid.
- Pick best runtime per preset.
- Run LoRA/reference A/B where useful.

Done:

- Precision improves by at least 40% relative.
- Settings are justified in audit doc.

### Phase 5: Productize

Tasks:

- Store benchmark results.
- Add preset cards.
- Add gallery preset ratings.

Done:

- User can see which presets are reliable and what they are for.

## Agent Notes

- Do not optimize for pretty one-off images. Optimize for first-try precision.
- Do not use a single global prompt trick for all presets. `tartakovsky` and `documentary` need opposite craft hints.
- Do not trust negative prompts as the primary control plane. Use positive visual instructions.
- Do not claim 40% improvement without a before/after matrix using the same prompts and seeds.
- Do not let ImageReward/PickScore override human acceptance for brand fit. Automatic scores are assistive.

## Final Definition Of Done

This project is complete when:

- Baseline precision is measured.
- All seven presets have explicit precision contracts.
- Prompt assembly uses those contracts.
- Benchmark prompts exist for every preset.
- Before/after renders are reproducible.
- Overall preset precision improves by at least 40% relative.
- No individual preset has a meaningful regression.
- The handoff includes exact before/after metrics, selected settings, and remaining known failure modes.

