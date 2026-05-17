# LoRA library — per-engine curation

A LoRA (Low-Rank Adapter) modifies the **weights** of FLUX, not just the
prompt. Stacking 1-3 well-chosen LoRAs is the single biggest quality jump
available short of training your own (`BRAND-LORA.md`).

This file documents the curated FLUX LoRAs for each Forge engine. Some
ecosystems are mature (realism), others patchy (Indian classical). Picks
below are surveyed from HuggingFace by download count + relevance.

## How to download and use

```sh
# Pick a LoRA, download into brand/loras/
hf download Shakker-Labs/FLUX.1-dev-LoRA-add-details \
   --include "*.safetensors" \
   --local-dir ~/Desktop/Forge/brand/loras/

# Use with any engine render or thumbnail
forge engine render noir-cinema --recipe noir-detective-alley \
   --config "..." \
   --lora add-details.safetensors --lora-scale 0.6 \
   --lora flux-lora-film-noir.safetensors --lora-scale 0.85
```

`--lora` is repeatable for stacking; `--lora-scale` matches by order. Typical
scales: 0.4-0.6 for "subtle nudge", 0.7-0.9 for "strong adherence", 1.0+
rarely improves anything.

## Per-engine recommendations

### noir-cinema — film-noir + ink-and-shadow comic

| LoRA | HF repo | Size hint | Why |
|---|---|---|---|
| **add-details** (universal) | `Shakker-Labs/FLUX.1-dev-LoRA-add-details` | ~200 MB | Micro-detail booster. Pairs well with any specialist LoRA. Recommended scale 0.4-0.6. |
| **film-noir** | `dvyio/flux-lora-film-noir` | ~200 MB | Explicit noir. Low download count → quality unknown; test before relying on. |
| **dark-fantasy** | `Shakker-Labs/FLUX.1-dev-LoRA-Dark-Fantasy` | ~200 MB | Darker/grittier aesthetic; useful for `subgenre=pulp-comic`. |

Stack suggestion: `add-details @ 0.5 + film-noir @ 0.85` for classic-1940s,
`add-details @ 0.5 + dark-fantasy @ 0.75` for pulp-comic.

### wildlife-photo — the mature ecosystem

| LoRA | HF repo | Size hint | Why |
|---|---|---|---|
| **flux-RealismLora** (XLabs) | `XLabs-AI/flux-RealismLora` | ~700 MB | THE realism LoRA — 15k downloads. Sharpens textures, fixes plastic-skin tendencies. Recommended scale 0.7-0.9. |
| **Flux-Super-Realism-LoRA** | `strangerzonehf/Flux-Super-Realism-LoRA` | ~200 MB | Alternative realism boost, more contemporary photo grade. |
| **add-details** (universal) | `Shakker-Labs/FLUX.1-dev-LoRA-add-details` | ~200 MB | Micro-detail on fur/feathers. |

Stack suggestion: `flux-RealismLora @ 0.8 + add-details @ 0.5`. **This is the
best-curated stack of any engine here** — wildlife realism on FLUX is solved.

### impressionist — patchy

| LoRA | HF repo | Size hint | Why |
|---|---|---|---|
| **Vincent van Gogh** | `twn39/Vincent_van_Gogh_flux` | ~200 MB | Only Van Gogh-specific FLUX LoRA with any downloads. Niche, untested at scale. |
| **add-details** (universal) | `Shakker-Labs/FLUX.1-dev-LoRA-add-details` | ~200 MB | Helps brushwork micro-detail. |
| **Midjourney-Mix2** | `strangerzonehf/Flux-Midjourney-Mix2-LoRA` | ~200 MB | Painterly Midjourney aesthetic, can push impasto feel. |

Stack suggestion: `twn39/Vincent_van_Gogh_flux @ 0.85 + Midjourney-Mix2 @ 0.4`.
**Honest caveat**: the engine's prompt already names master works directly,
which often does more than these mid-quality LoRAs. Try without LoRAs first.

### indian-classical — no curated option

The FLUX LoRA ecosystem doesn't have a strong Tanjore / Ravi-Varma / Pahari
specialist as of this curation. Options:

| LoRA | HF repo | Why |
|---|---|---|
| **Flux.1-Dev-Indo-Realism-LoRA** | `prithivMLmods/Flux.1-Dev-Indo-Realism-LoRA` | Indian cultural realism — closest available match. ~163 downloads, quality unknown. |
| **add-details** (universal) | `Shakker-Labs/FLUX.1-dev-LoRA-add-details` | Helps with jewelry / fabric micro-detail. |

**Better path for this engine**: train your own LoRA on 20-40 Tanjore or
Ravi-Varma reference images. The training recipe is in `BRAND-LORA.md`.
Per-tradition LoRAs would be a real quality jump.

## Universal helpers (not specific to one engine)

Worth keeping in `brand/loras/` regardless of engine choice:

| LoRA | HF repo | Universal benefit |
|---|---|---|
| **add-details** | `Shakker-Labs/FLUX.1-dev-LoRA-add-details` | Micro-detail booster; scale 0.4-0.5 + any specialist LoRA |
| **flux-RealismLora** | `XLabs-AI/flux-RealismLora` | The single most-downloaded FLUX LoRA. Photo-grade detail. |
| **Canopus-FaceRealism** | `prithivMLmods/Canopus-LoRA-Flux-FaceRealism` | If your subject is a human face, this fixes eye + skin issues |

## Bulk download all the picks above

```sh
mkdir -p ~/Desktop/Forge/brand/loras

# Universal helpers (use with most engines)
hf download Shakker-Labs/FLUX.1-dev-LoRA-add-details \
   --include "*.safetensors" --local-dir ~/Desktop/Forge/brand/loras/add-details/

hf download XLabs-AI/flux-RealismLora \
   --include "*.safetensors" --local-dir ~/Desktop/Forge/brand/loras/realism-xlabs/

# Noir
hf download dvyio/flux-lora-film-noir \
   --include "*.safetensors" --local-dir ~/Desktop/Forge/brand/loras/film-noir/

# Impressionist
hf download twn39/Vincent_van_Gogh_flux \
   --include "*.safetensors" --local-dir ~/Desktop/Forge/brand/loras/van-gogh/

# Indian classical (closest available)
hf download prithivMLmods/Flux.1-Dev-Indo-Realism-LoRA \
   --include "*.safetensors" --local-dir ~/Desktop/Forge/brand/loras/indo-realism/
```

Total disk: ~1.5 GB across the picks above.

## Wiring as engine defaults

After downloading, you can either:

1. **Use ad-hoc per call**: `--lora <file> --lora-scale 0.8` on each render
2. **Make permanent for an engine**: edit the engine's `default_lora_stack` (TODO — not wired yet; ad-hoc only as of this write-up)
3. **Per-recipe**: add `"lora_paths": [...]` + `"lora_scales": [...]` to the recipe in `brand/prompts/library.json`

## Quality-test workflow for a new LoRA

```sh
# Render the same subject with and without the LoRA
forge engine render noir-cinema --recipe noir-detective-alley --seeds 4
# → ~/Desktop/forge-test/engine-renders/noir-cinema/noir-detective-alley/contact-sheet.html

forge engine render noir-cinema --recipe noir-detective-alley --seeds 4 \
  --lora add-details/add-details.safetensors --lora-scale 0.5 \
  --lora film-noir/<file>.safetensors --lora-scale 0.85 \
  --out ~/Desktop/forge-test/engine-renders/noir-cinema/noir-detective-alley-LORA/seed01.png
```

Compare the two contact sheets. Keep the LoRA stack if it's a clear win; drop
it if it homogenizes the output or breaks the engine's voice.

## Note on FLUX LoRA ecosystem

The FLUX LoRA scene is **less mature** than the SDXL/SD 1.5 scene. For SD/SDXL
there are 10,000+ curated style LoRAs on Civitai. For FLUX it's hundreds, and
many are mediocre. The engines in `style_engines.py` are designed to do most
of the lifting via prompt-engineering alone; LoRAs are a multiplier, not a
crutch. If a LoRA isn't clearly better than no-LoRA, ditch it.
