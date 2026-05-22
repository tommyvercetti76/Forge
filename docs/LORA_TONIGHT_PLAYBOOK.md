# LoRA tonight playbook — Madhubani-v1 overnight pilot

**Goal:** train a single z-image-turbo LoRA on the user-graded PASS images
from the v4 batch, then objectively measure whether it helps on
held-out species. End state: morning eval report (`eval_lora_report.html`)
with paired ΔComposite numbers and a SHIP / ITERATE / SHELVE verdict.

**Total wall-clock budget:** ~7–10 hours from batch end to morning report.
Most of it is GPU time the user is asleep for.

---

## Pre-flight checklist (do this before bed)

```
[ ] v4 batch landed                       (29/41 → 41/41 in _batch_summary.json)
[ ] contact sheet built                    (bin/build_v4_contact_sheet.py)
[ ] user graded ≥ 25 species               (PASS votes in exported JSON)
[ ] training dataset built + ≥ 20 samples  (training/madhubani_lora_v2/)
[ ] disk space ≥ 5 GB free                 (df -h .)
[ ] AC power plugged in                    (training runs the GPU hot)
[ ] charger not on battery-saver           (mflux-train default battery floor is 5%)
```

---

## Step 1 — wait for v4 batch to finish (~30 min from now)

The batch is running in the background. It writes atomic updates to
`generated/madhubani_animals/v4/_batch_summary.json` after each species,
so a crash doesn't lose state. When it's done, the orchestrator process
(PID was 37854 at last check) will exit cleanly.

Watch progress (no need to poll — just glance):

```bash
tail -n 30 /tmp/v4_batch.log
```

Done when:
```bash
python3 -c "import json; d=json.load(open('generated/madhubani_animals/v4/_batch_summary.json')); print(f\"{d['n_done']}/{d['n_total']}\")"
# expects: 41/41
```

---

## Step 2 — build the contact sheet and grade

```bash
python3 bin/build_v4_contact_sheet.py
open generated/madhubani_animals/v4/_contact_sheet.html
```

- Click PASS / FAIL / ? for each species (~10 sec each, ~7 min total).
- Click **Export votes as JSON** when done.
- The file lands as `~/Downloads/v4_user_votes_YYYY-MM-DD.json`.

**Honesty floor:** mark FAIL anything that doesn't read as authentically
Madhubani to you. Don't reward composite scores — those are the
classifier's opinion, not yours.

---

## Step 3 — build the training dataset

```bash
python3 bin/build_lora_dataset_v2.py \
    --votes ~/Downloads/v4_user_votes_2026-05-20.json \
    --summary generated/madhubani_animals/v4/_batch_summary.json \
    --emit-labels brand/madhubani/labels_v2.json \
    --force
```

This will:
- Emit `brand/madhubani/labels_v2.json` (the new label manifest)
- Build `training/madhubani_lora_v2/` with images + captions + train.json
- **Exclude rhino, peacock, elephant, snow-leopard** from training (held out)

You need **≥ 10 training samples** for the script to proceed (≥ 20 recommended).
If you have fewer, grade more aggressively or revisit the holdout list.

Expected output:
```
Found 25 PASS entries
  → 22 training samples (after held-out exclusion + dedup)
  → 3 excluded as held-out
Wrote dataset to training/madhubani_lora_v2/
  22 training images + captions in images/
  config: training/madhubani_lora_v2/train.json
  manifest: training/madhubani_lora_v2/MANIFEST.json
```

---

## Step 4 — validate the training config (30 sec)

```bash
mflux-train --config training/madhubani_lora_v2/train.json --dry-run
```

Should print the resolved config and exit `0`. If it errors, fix the
config before kicking off real training — otherwise you'll lose hours
to a misconfigured run.

---

## Step 5 — kick off LoRA training (overnight, ~6–9 hrs)

```bash
nohup mflux-train --config training/madhubani_lora_v2/train.json \
    > /tmp/lora_v1_train.log 2>&1 &
echo "PID: $!"
```

What's happening:
- **30 epochs × ~25 samples × batch_size 1 = ~750 iterations**
- ~30–60 s per iteration at resolution 512 on M5 Max
- Checkpoints saved every 100 iterations → 7 checkpoints to compare
- Preview images generated every 100 iterations for all 4 held-out species
  → you'll see generalization land in real time when you wake up

The adapter lands at:
```
training/madhubani_lora_v2/training/<TIMESTAMP>/checkpoints/lora_adapter_<step>.safetensors
```

The latest one is symlinked to `lora_adapter.safetensors`.

---

## Step 6 — sanity-check the eval pipeline (parallel, ~3 min)

While LoRA training runs, run the base-only eval to make sure the eval
harness works end-to-end. This catches problems EARLY rather than at
morning:

```bash
python3 bin/eval_lora.py --no-lora-debug
# Should render 8 base images (4 species × 2 seeds) and score them.
# Renders are cached to generated/madhubani_animals/lora_eval/_base_cache/
# so the morning run reuses them.
```

If this fails (e.g., mflux-generate-z-image not on PATH, z-image-turbo
model not cached), fix it now while you're awake.

---

## Step 7 — morning eval (~5 min)

Wake up. Check that training finished:

```bash
tail -n 20 /tmp/lora_v1_train.log
ls -la training/madhubani_lora_v2/training/*/checkpoints/
```

Pick a checkpoint to evaluate. Default: the latest. If the loss curve
shows divergence (see preview images / loss plot), pick an earlier one.

```bash
python3 bin/eval_lora.py \
    --lora training/madhubani_lora_v2/training/<TS>/checkpoints/lora_adapter.safetensors \
    --scales 0.5,0.75,1.0
```

This will:
- Reuse cached base renders (from Step 6) → only LoRA renders are fresh
- Render 4 species × 2 seeds × 3 scales = 24 LoRA images (~5 min)
- Score everything via composite (rubric 0.6 + CLIP v2 0.4)
- Emit `generated/madhubani_animals/lora_eval/eval_lora_report.{html,json}`

Open the report:
```bash
open generated/madhubani_animals/lora_eval/eval_lora_report.html
```

---

## Decision tree (at morning report)

The report's top card shows **mean ΔComposite** per LoRA scale.

| Outcome | Action |
|---|---|
| **Best scale ≥ +0.05** | **SHIP**: commit the LoRA + bump production profile to load it by default. Document the corpus + config in docs/. |
| **Best scale ∈ [−0.02, +0.05]** | **ITERATE**: inspect per-species deltas. Common patterns: helps easy species (rhino, elephant), hurts hard ones (snow-leopard). Try shorter training (early-stop checkpoint), different scale, or expand the corpus. |
| **Best scale < −0.02** | **SHELVE**: LoRA hurt. Document as a negative result in docs/LORA_LEARNINGS_v1.md. Investigate: were the training images consistent? Was the caption template too narrow? Did we overfit the rank? |

---

## Common failure modes (debug guide)

### Training never converges (loss plateau or rising)
- LR too high — try `1e-5` instead of `1e-4`
- Rank too low for the dataset complexity — try rank 24 or 32
- Caption template too narrow — verify captions in `training/madhubani_lora_v2/images/*.txt` look right

### LoRA hurts every species
- Overfitting to a specific PASS image's artifacts. Inspect the training
  set in `training/madhubani_lora_v2/images/` — are there outliers?
- Rank too high relative to corpus size. With 25 images, rank ≤ 16 is
  the rule of thumb (alpha = 2× rank).
- Style key in caption conflicts with held-out eval prompt — verify
  STYLE_KEY matches between `bin/build_lora_dataset_v2.py` and
  `bin/eval_lora.py`.

### LoRA helps some species, hurts others
- This is actually the expected outcome for a small-N pilot.
- Per-species breakdown in `eval_lora_report.json` → see which species
  the LoRA helps. Train a **per-body-type LoRA** (one for quadrupeds,
  one for birds, one for serpents) as the next iteration.

### mflux-generate-z-image errors during eval
- Verify it's on PATH: `which mflux-generate-z-image`
- Verify z-image-turbo model is cached: `mflux-generate-z-image --model z-image-turbo --prompt "test" --seed 1 --steps 4 --width 256 --height 256 --output /tmp/test.png`
- LoRA path must be absolute (the eval script handles this with `.resolve()`)

---

## Files this playbook expects to exist

Built tonight as part of LoRA scaffolding:
- `bin/build_lora_dataset_v2.py` — dataset builder (PASS images → training corpus)
- `bin/eval_lora.py` — held-out eval harness (base vs LoRA, paired deltas)
- `brand/madhubani/lora_v1_holdout.json` — held-out species + eval seeds + decision thresholds

Already shipped:
- `bin/build_v4_contact_sheet.py` — grading UI builder
- `bin/best_of_n.py` — composite scoring (used by `eval_lora.py`)
- `bin/madhubani_qc.py` — 10-check rubric (used by `bin/best_of_n.py`)
- `bin/forge_madhubani_lora.py` — original smoke-pilot scaffolding (still works, just trained on Wikimedia refs)

---

## What this proves (and what it doesn't)

**Proves (if ΔComposite ≥ +0.05):** That training a LoRA on user-graded
PASS images of model outputs measurably improves generalization to
held-out species. This is the "human feedback → real model improvement"
loop the user asked about — at first, modest scale.

**Doesn't prove (yet):**
- That it generalizes beyond 4 held-out species (would need a larger
  held-out set + more diverse training corpus)
- That it improves human-graded quality (we measure proxy metrics
  — rubric + CLIP probe — not blind human grading. The probe's F1
  ceiling is ~0.78; over-optimizing it risks Goodhart.)
- That LoRA on z-image-turbo transfers to FLUX.2-klein-4b (it doesn't;
  weights are model-specific. We'd need to either switch production
  to z-image for Madhubani, or do a separate FLUX.2 training pass when
  mflux supports it.)

**Honest next-step backlog:**
- Per-body-type LoRA mixture-of-experts (one quadruped, one bird, one
  serpent) if the pilot shows the LoRA helps some body types but not
  others.
- Per-zone CLIP probes — train smaller probes on patches of the image
  (forehead/saddle/anklets) for finer-grained scoring than whole-image
  CLIP.
- Blind human-graded eval (50 base vs 50 LoRA, randomized order, user
  votes blind) — the only ground-truth measurement for aesthetic quality.
