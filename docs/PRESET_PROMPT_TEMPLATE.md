# Preset Prompt Template And Dependency Vectors

Created: 2026-05-18

## Goal

Create a complete preset authoring template for Forge so every preset can move
from vague style prose to a structured visual contract.

The template is designed to create:

- More meaningful prompt tokens.
- Better dependency vectors between visual instructions.
- Better benchmark and evaluation questions.
- Backward-compatible fields for existing Forge rendering paths.
- A clear handoff for agents upgrading `brand/presets/*.json`.

The machine-readable version lives at:

```text
brand/prompts/preset_authoring_template.json
brand/presets/templates/semantic-preset-template.json
```

## Why This Exists

Current Forge presets mostly depend on:

- `flux.positive_prefix`
- `flux.positive_suffix`
- `flux.negatives`
- `prompt_rules.always_add`
- `palette_60_30_10`
- `composition.thumbnail`

That works, but it hides too much inside prose. The model sees a paragraph, while
we need a controllable contract. When a render fails, we cannot tell whether the
failure came from style, subject placement, lighting, safe-zone conflict, palette
drift, prompt order, or an incompatible master primer.

The fix is to define presets as tokens plus vectors.

## Definitions

### Semantic Token

A semantic token is one atomic visual instruction.

A good token is:

- Observable in the image.
- Bound to a target such as subject, face, background, lower third, frame,
  palette, or typography.
- Weighted by importance.
- Connected to an evaluation question.
- Specific enough that a reviewer can say yes or no.

Weak token:

```text
cinematic
```

Better token:

```text
single warm key light from frame-left creates rim light on the subject edge
```

Best token:

```json
{
  "id": "cinematic.lighting.warm_rim_key",
  "dimension": "lighting",
  "prompt_text": "single warm key light from frame-left creating a visible rim on the subject edge",
  "weight": 0.9,
  "priority": "core",
  "visible_evidence": "one warm edge highlight separates the subject from dark background",
  "binds_to": ["subject", "background"],
  "failure_if_missing": true,
  "evaluation_question": "Is there a warm rim/key light visibly separating the subject from the background?"
}
```

### Dependency Vector

A dependency vector is a typed relationship between two tokens.

It explains how one instruction changes another instruction.

Example:

```json
{
  "from_token": "thumbnail.composition.lower_third_clear",
  "to_token": "cinematic.composition.subject_upper_two_thirds",
  "relation": "requires",
  "strength": 1.0,
  "reason": "A readable headline needs the subject and detailed objects out of the lower third.",
  "prompt_assembly_effect": "Place the subject-position token before safe-zone text, then repeat lower-third safety in prompt_rules.always_add."
}
```

## Token Taxonomy

Use these dimensions. Do not invent a new dimension unless it cannot fit here.

| Dimension | Purpose | Example |
| --- | --- | --- |
| `subject` | Main object/person and identity constraints | `single elderly storyteller seated near a window` |
| `composition` | Placement, scale, relationship, crop | `subject occupies upper two-thirds, lower third low detail` |
| `lighting` | Source, direction, contrast, mood | `soft window light from frame-right` |
| `camera` | Lens, perspective, distance, framing | `medium-format portrait, 85mm equivalent, shallow depth` |
| `palette` | Dominant/secondary/accent color behavior | `deep blue-black shadows with one burnt-orange accent` |
| `surface` | Texture, material, rendering substrate | `matte ink on aged paper, visible grain` |
| `typography` | Overlay-readiness, not generated text | `clear band for external headline overlay` |
| `safe_zone` | Reserved areas for text/crop | `lower third has low edge density and no faces` |
| `style` | Visual grammar, not generic vibe | `flat cel fills with thick uniform contour lines` |
| `era` | Period-specific evidence | `1970s radio studio props, analog dials` |
| `cultural` | Specific cultural detail without stereotypes | `Marathi household brass dabba on side table` |
| `quality` | Technical quality gate | `clean silhouette, no duplicated hands` |
| `exclusion` | True defects only | `text in image`, `watermark`, `logo` |

## Dependency Relations

| Relation | Meaning |
| --- | --- |
| `requires` | The target token must exist for the source token to work. |
| `supports` | The target token improves the source token. |
| `inhibits` | The source token weakens the target token and should lower its weight. |
| `conflicts` | The two tokens should not be active together. |
| `locks` | The source token fixes a value for consistency. |
| `sequence_before` | The source token should appear earlier in prompt assembly. |
| `sequence_after` | The source token should appear later in prompt assembly. |

## Prompt Assembly Order

The preset authoring template should produce tokenized prompt blocks in this
order:

1. User subject or scene.
2. Preset intent.
3. Core style identity tokens.
4. Composition and subject binding tokens.
5. Lighting and camera tokens.
6. Palette and surface tokens.
7. Typography/safe-zone tokens.
8. Cultural or era tokens when relevant.
9. Hard exclusions only.
10. Preset-specific craft hint.
11. Series/cast locks if a series is active.

Reason:

- The model should know what to draw before it receives style pressure.
- Style should be decomposed into visible parts.
- Composition and safe-zone requirements should be close enough to reinforce
  each other.
- Hard negatives should be short and defect-focused.
- The master primer must respect the preset style instead of overriding it.

## Complete Authoring Prompt

Use this prompt when asking an agent or local LLM to create or upgrade a preset.

### System Prompt

```text
You are a Forge preset architect.

Your job is to convert vague style intent into a precise visual contract for
FLUX image generation and PIL typography overlays.

You must produce:
- observable semantic tokens
- dependency vectors
- safe-zone rules
- benchmark prompts
- failure gates
- backward-compatible Forge preset fields

Rules:
- Avoid vague words unless you bind them to visible evidence.
- Do not rely on negative prompts as the primary control plane.
- Prefer positive visual instructions.
- Keep hard exclusions short and defect-focused.
- Every token must be useful for prompt assembly, evaluation, or debugging.
- Every dependency vector must explain why the relationship matters.
- Return only valid JSON.
```

### User Prompt

```text
Create or upgrade a Forge preset using this input:

PRESET_ID: {preset_id}
PRESET_GOAL: {preset_goal}
PRIMARY_USE: {primary_use}
AUDIENCE: {audience}

CURRENT_PRESET_JSON:
{current_preset_json}

REFERENCE_DESCRIPTIONS:
{reference_descriptions}

KNOWN_FAILURES:
{known_failures}

MUST_KEEP:
{must_keep}

Return JSON with:
- standard Forge preset fields
- semantic_contract
- semantic_tokens
- dependency_vectors
- prompt_blocks
- precision_contract
- runtime_recommendation
- failure_modes
- author_notes

The preset must be backward-compatible with Forge's current preset loader.
The semantic fields must be detailed enough to drive future prompt assembly,
benchmark scoring, and gallery feedback.
```

## Required Output Shape

Every upgraded preset should include these top-level sections.

```json
{
  "id": "preset-id",
  "name": "Preset Name",
  "description": "User-facing description.",
  "use_for": "When to choose this preset.",
  "typography": {},
  "palette_60_30_10": {},
  "composition": {},
  "flux": {},
  "prompt_rules": {},
  "master_primer_policy": "full | photo_only | style_safe | off",
  "semantic_contract": {},
  "semantic_tokens": [],
  "dependency_vectors": [],
  "prompt_blocks": {},
  "precision_contract": {},
  "runtime_recommendation": {},
  "failure_modes": []
}
```

Backward compatibility:

- Existing code can keep reading `typography`, `palette_60_30_10`,
  `composition`, `flux`, `prompt_rules`, and `master_primer_policy`.
- Future code can read `semantic_tokens`, `dependency_vectors`, and
  `precision_contract`.

## Token Quality Rules

A token is accepted only if it passes all gates:

- It has a unique `id`.
- It has one taxonomy `dimension`.
- It uses positive observable wording unless it is a true hard exclusion.
- It has a `weight` from `0.0` to `1.0`.
- It has `priority`: `core`, `strong`, or `optional`.
- It binds to at least one target.
- It states visible evidence.
- It has an evaluation question.

Reject tokens like:

```text
beautiful
professional
high quality
cinematic vibe
premium look
viral thumbnail
Indian feel
```

Rewrite them as visible instructions:

```text
single subject separated from background by one warm rim light
headline safe zone has low edge density and no faces
flat cel fills with thick uniform contour lines
off-white paper grain visible in large empty areas
one saffron accent object, no more than 10 percent of frame
```

## Dependency Vector Quality Rules

A vector is accepted only if:

- `from_token` and `to_token` exist.
- `relation` is one of the approved relation values.
- `strength` is between `0.0` and `1.0`.
- `reason` explains the visual or runtime consequence.
- `prompt_assembly_effect` tells the builder what to do.

Bad vector:

```json
{
  "from_token": "cinematic",
  "to_token": "quality",
  "relation": "supports"
}
```

Good vector:

```json
{
  "from_token": "cinematic.lighting.deep_shadow_mass",
  "to_token": "cinematic.palette.off_white_highlights",
  "relation": "requires",
  "strength": 0.85,
  "reason": "Deep shadows need restrained off-white highlights so the subject remains readable.",
  "prompt_assembly_effect": "Assemble shadow token before highlight token; evaluate both as a pair."
}
```

## Precision Contract

The `precision_contract` is the bridge between prompt writing and measurement.

Required fields:

```json
{
  "intent": "one-sentence purpose",
  "primary_use": "thumbnail_background | editorial_image | documentary_image | title_card",
  "style_atoms": [],
  "composition_atoms": [],
  "lighting_atoms": [],
  "camera_atoms": [],
  "surface_atoms": [],
  "palette_atoms": [],
  "thumbnail_safety_atoms": [],
  "hard_failure_terms": [],
  "safe_zones": [],
  "eval_questions": [],
  "benchmark_prompts": []
}
```

Each `eval_question` should map to one or more token ids:

```json
{
  "id": "lower_third_clear",
  "question": "Is the lower third low-detail and free of faces or critical objects?",
  "required": true,
  "token_ids": [
    "thumbnail.safe_zone.lower_third_clear",
    "thumbnail.composition.subject_upper_two_thirds"
  ]
}
```

## Safe Zones

Any preset used for thumbnails must define safe zones.

Example:

```json
{
  "name": "lower_third",
  "bbox_pct": [0.0, 0.62, 1.0, 1.0],
  "required": "low detail, no faces, no subject-critical object, no high-contrast clutter"
}
```

Safe-zone tokens should usually have dependencies:

- `safe_zone.lower_third_clear` requires `composition.subject_upper_two_thirds`.
- `safe_zone.left_gutter_clear` inhibits `composition.subject_left_third`.
- `typography.high_contrast_overlay` requires `palette.dark_band_or_low_detail`.

## Backward-Compatible Legacy Mapping

Until `build_flux_prompt` is fully semantic-token aware, each preset still needs
legacy prompt fields.

Map tokens into current fields:

| Current field | Fill from |
| --- | --- |
| `flux.positive_prefix` | intent, core style, core composition, core lighting/camera tokens |
| `flux.positive_suffix` | craft hint and style-specific finishing tokens |
| `flux.negatives` | true hard exclusions only |
| `prompt_rules.always_add` | highest-priority safety/composition tokens |
| `palette_60_30_10` | palette tokens |
| `composition.thumbnail` | safe-zone and text overlay tokens |
| `master_primer_policy` | dependency conflicts between style and global primer |

Example:

```json
{
  "flux": {
    "positive_prefix": "Cinematic 16:9 still frame, single subject in upper two-thirds, deep shadow mass, one warm rim key light, low-detail lower third reserved for external headline overlay.",
    "positive_suffix": "Movie-poster composition with restrained atmosphere and readable silhouette.",
    "negatives": ["text in image", "watermark", "logo", "busy lower third"],
    "guidance": 4.5,
    "steps": 25,
    "model": "dev"
  }
}
```

## Example Token Set

Example for a high-impact thumbnail preset:

```json
{
  "semantic_tokens": [
    {
      "id": "thumbnail.subject.upper_two_thirds",
      "dimension": "composition",
      "prompt_text": "single dominant subject placed in the upper two-thirds of the frame",
      "weight": 1.0,
      "priority": "core",
      "visible_evidence": "subject does not overlap the headline band",
      "binds_to": ["subject", "lower_third"],
      "allowed_variants": ["center upper two-thirds", "left upper two-thirds", "right upper two-thirds"],
      "failure_if_missing": true,
      "evaluation_question": "Is the main subject outside the lower-third headline area?"
    },
    {
      "id": "thumbnail.safe_zone.lower_third_clear",
      "dimension": "safe_zone",
      "prompt_text": "lower third kept low-detail, no faces, no hands, no important objects",
      "weight": 1.0,
      "priority": "core",
      "visible_evidence": "headline can be placed over the bottom band without covering important content",
      "binds_to": ["lower_third", "typography"],
      "allowed_variants": ["dark low-detail band", "soft blurred background", "plain wall or sky"],
      "failure_if_missing": true,
      "evaluation_question": "Is the lower third clear enough for a bold headline?"
    }
  ],
  "dependency_vectors": [
    {
      "from_token": "thumbnail.safe_zone.lower_third_clear",
      "to_token": "thumbnail.subject.upper_two_thirds",
      "relation": "requires",
      "strength": 1.0,
      "reason": "The lower third cannot stay clear if the subject occupies it.",
      "prompt_assembly_effect": "Put subject placement before lower-third safety and repeat lower-third safety in prompt_rules.always_add."
    }
  ]
}
```

## Benchmark Prompt Requirements

Every preset should include at least 12 benchmark prompts:

- 4 common use cases.
- 3 composition stress tests.
- 2 palette/lighting stress tests.
- 2 subject variety tests.
- 1 edge case likely to break the preset.

Each benchmark prompt must include:

```json
{
  "id": "cinematic-common-001",
  "prompt": "a lone courier holding a sealed letter outside an old train station in heavy rain",
  "expected_tokens": [
    "cinematic.composition.single_subject",
    "cinematic.lighting.warm_rim_key",
    "cinematic.palette.deep_shadow_mass"
  ],
  "edge_case": false
}
```

## Implementation Handoff

Agent should do this in order:

1. Read `docs/PRESET_PRECISION_IMPROVEMENT_HANDOFF.md`.
2. Read `brand/prompts/preset_authoring_template.json`.
3. Read `brand/presets/templates/semantic-preset-template.json`.
4. Pick one preset, preferably `thumbnail-bold` or `cinematic`.
5. Convert it to the semantic structure without changing current legacy fields.
6. Run `python3 bin/forge.py show <preset>` to confirm JSON loads.
7. Render a small smoke test with `--profile cool`.
8. Save prompt sidecars before changing prompt assembly code.
9. Only then update `build_flux_prompt` to consume semantic tokens.

## Done Definition

This template work is done when:

- `brand/prompts/preset_authoring_template.json` exists and is valid JSON.
- `brand/presets/templates/semantic-preset-template.json` exists and is valid
  JSON.
- This doc explains token quality, dependency vectors, safe zones, output shape,
  and legacy mapping.
- README and docs index link to this doc.
- Future agents can create a new preset without guessing the schema.

The preset precision project is done later when:

- Every active preset has semantic tokens.
- Every active preset has dependency vectors.
- Every active preset has benchmark prompts.
- `build_flux_prompt` can assemble from token blocks.
- Benchmark precision improves without regressing existing presets.
