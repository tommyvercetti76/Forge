# Brand LoRA — train a fingerprint your gens can't drift from

When prompt engineering isn't enough, fine-tune a small LoRA on a curated
reference set so every Flux generation reads as *your* brand. Trained
locally on Apple Silicon in ~1–2 hrs.

A LoRA is the strongest possible style/character lock — series presets
constrain the prompt, a LoRA constrains the *weights*. Use one when you
need on-model results 100% of the time.

---

## 1. Curate the reference set

Quality > quantity. **20–40 images is the sweet spot.**

For a *style* LoRA (e.g. your Tartakovsky-derived look):
- 30 frames you love that share the visual fingerprint
- diverse subjects, compositions, lighting — the LoRA learns what's
  *invariant* across the set, so variety in everything *except* style
- all the same aspect ratio (1024×1024 or 1280×720 for thumbs)

For a *character* LoRA (e.g. recurring fisherman):
- 20–25 images of the character, varied poses + angles + outfits
- same face/proportions/identity across all of them
- mix close-ups, mid-shots, wide shots

Put the set in `~/Forge/brand/loras/training/<lora-name>/images/`.

## 2. Caption every image

mflux trains better with explicit captions. For each `image.png`, write
`image.txt` alongside it.

Caption recipe (style LoRA):
```
<trigger-word>, <subject in plain English>, <lighting>, <composition>
```

Example:
```
kaayko_style, a fisherman mending nets at dawn, warm key light from
camera-left with cool teal shadow side, mid-shot 3/4 angle
```

The **trigger word** (`kaayko_style` above) is the magic phrase the LoRA
ties to. Pick something unique that's not a real English word — `kaayko_style`,
`brnd_v1`, `mythic_cel`. You'll put this word in every prompt to activate
the LoRA at gen time.

## 3. Train

mflux ships a trainer. Use `mflux-train` with these settings — they're
tuned for Apple Silicon and 20–40 images:

```sh
mflux-train \
  --model dev \
  --train-data ~/Forge/brand/loras/training/kaayko_style/images \
  --output ~/Forge/brand/loras/kaayko_style.safetensors \
  --rank 16 \
  --steps 1500 \
  --learning-rate 1e-4 \
  --batch-size 1 \
  --save-every 250 \
  --validate-every 100 \
  --resolution 1024
```

What each knob does:

| Knob | What it controls | When to change |
|---|---|---|
| `--rank` | LoRA size (higher = more capacity, bigger file) | 8 for thin styles, 16 default, 32 for complex characters |
| `--steps` | Total training steps | 1500 default; 2500 if results look under-cooked |
| `--learning-rate` | How fast weights move | 1e-4 default; halve to 5e-5 if results overfit (memorizes refs) |
| `--resolution` | Training image size | 1024 default; 720 if you only need thumbnails |

Expect **60–90 min on M2 Pro**, **30–50 min on M3 Max**. Heat goes up;
keep the lid open.

## 4. Validate

Check the saved checkpoints (`step-0500`, `step-1000`, `step-1500`) by
generating a test image with each:

```sh
forge thumbnail \
  --preset tartakovsky \
  --concept "kaayko_style, a lighthouse keeper at sunset" \
  --headline "Test" \
  --lora kaayko_style-step-1000.safetensors \
  --lora-scale 0.8 \
  --out /tmp/lora-test-1000.png
```

Compare the three checkpoints. Pick the one with the *strongest style
adherence* without overfitting (overfit = copies a reference pose
exactly, can't generalize).

## 5. Install

Move the chosen checkpoint to `brand/loras/`:

```sh
mv ~/Forge/brand/loras/kaayko_style-step-1000.safetensors \
   ~/Forge/brand/loras/kaayko_style.safetensors
```

## 6. Use

### Per-call:
```sh
forge thumbnail --preset cinematic --concept "..." --headline "..." \
  --lora kaayko_style.safetensors --lora-scale 0.8
```

### Per-series (recommended) — edit `series/<id>.json`:
```json
{
  "id": "harbor-tales",
  "lora_paths": ["kaayko_style.safetensors"],
  "lora_scales": [0.85]
}
```

Every gen in that series will load the LoRA automatically. No drift.

### Per-preset (fingerprint EVERY gen) — edit `brand/presets/<id>.json`:
```json
{
  "lora_paths": ["kaayko_style.safetensors"],
  "lora_scales": [0.7]
}
```

Use this only when the LoRA *is* the brand — every Forge call that
selects this preset will get the LoRA, with or without `--lora`.

## Scale tuning

- `0.6–0.7` — subtle nudge toward the LoRA
- `0.8` — default, strong adherence
- `1.0` — maximum (sometimes over-cooks)
- Above `1.0` rarely improves anything

You can stack LoRAs (e.g. style + character) by repeating `--lora`:

```sh
forge thumbnail ... \
  --lora kaayko_style.safetensors --lora-scale 0.7 \
  --lora fisherman_char.safetensors --lora-scale 0.85
```

Resolution order in Forge: **CLI flags > series > preset**. So a
series can override a preset's default LoRA, and a CLI flag overrides both.
