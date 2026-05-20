# Rhino end-to-end test of the Art Reasoning Engine

> 2026-05-20. Walks the **full closed-loop** on a single species (rhino,
> Indian one-horned rhinoceros). Originally written when only the
> scoring half had been demonstrated; updated 2026-05-20 PM with the
> live mflux run that exercised render → score → rank → diagnose →
> boost → persist end-to-end.
>
> | Loop step | Demonstrated? | How |
> | :--- | :-: | :--- |
> | Score | ✓ | Real `score_madhubani_png` on real PNGs |
> | Composite rank | ✓ | Real `pick_best_of_n` with CLIP probabilities |
> | Diagnose weakest | ✓ | Real `identify_weakest_check` |
> | Compose boost | ✓ | Real boost clause from `brand/madhubani/boost_prompts.json` |
> | **Re-render with mflux** | ✓ | `forge_madhubani_reasoning.py` wraps `forge engine render --profile madhubani` and feeds the boosted prompt into a fresh `flux_generate_batch` call. 2 seeds × 25-step FLUX.2-klein-4b q4 = ~42 s per attempt. |
> | **Re-score** | ✓ | New attempts get a fresh `pick_best_of_n` pass against the same 10-check rubric + CLIP probe |
> | **Persist to ledger** | ✓ | D.1 `RunsWriter.from_reasoning_result` writes every attempt to `brand/madhubani/learning/runs.jsonl`; D.2 `forge madhubani learn` mines the digest |

## What this test exercises

| Component | File | Phase |
| :--- | :--- | :--- |
| 10-check Madhubani auto-QC rubric | [`bin/madhubani_qc.py`](../bin/madhubani_qc.py) | A2 + B.1 + B.2 + B.3 |
| Auto-QC ↔ human agreement measurement | [`bin/qc_agreement_study.py`](../bin/qc_agreement_study.py) · [QC_AGREEMENT_STUDY](QC_AGREEMENT_STUDY.md) | (eval methodology) |
| CLIP + sklearn learned Madhubani-likeness probe | [`bin/train_madhubani_likeness.py`](../bin/train_madhubani_likeness.py) · [`brand/madhubani/madhubani_likeness_v1.npz`](../brand/madhubani/madhubani_likeness_v1.npz) | (trained model) |
| Composite rubric + CLIP scorer + best-of-N picker | [`bin/best_of_n.py`](../bin/best_of_n.py) | C.1 |
| Per-check boost table | [`brand/madhubani/boost_prompts.json`](../brand/madhubani/boost_prompts.json) | C.2 |
| Weakest-check identification + boost compose + retry loop | [`bin/art_reasoning_engine.py`](../bin/art_reasoning_engine.py) | C.2 |

## Test corpus — four rhino variants held in tree

| Variant | Era | Source |
| :--- | :--- | :--- |
| v1 mascot | Pre-tuning, cartoon-style era | `generated/madhubani_animals/_legacy/indian_animals_v1/05_one_horned_rhinoceros_madhubani_tshirt.png` |
| v2 mid | Pre-A1 fixes | `generated/madhubani_animals/_legacy/indian_animals_v2/05_one_horned_rhinoceros_madhubani_tshirt.png` |
| v3 baseline | Post-Lane-1 flat-folk tuning | `generated/madhubani_animals/_legacy/indian_animals_v3/05_one_horned_rhinoceros_madhubani_tshirt.png` |
| pass_example | User-curated gold | `generated/madhubani_animals/_learning/pass_examples/rhino_v3.png` |

> Note: `pass_examples/rhino_v3.png` is byte-identical to the v3 baseline
> (md5 `1e170bb04c3ebe4149ef67eb89f5da94`). It appears in both
> `_legacy/` and `_learning/` because the user promoted it into the
> gold-standard test set. The picker correctly ties these two at rank
> 1, then breaks the tie deterministically by filename order.

## Step 1 — Best-of-N picker (C.1)

Command:

```sh
python3 bin/best_of_n.py --animal rhino \
  generated/madhubani_animals/_legacy/indian_animals_v1/05_one_horned_rhinoceros_madhubani_tshirt.png \
  generated/madhubani_animals/_legacy/indian_animals_v2/05_one_horned_rhinoceros_madhubani_tshirt.png \
  generated/madhubani_animals/_legacy/indian_animals_v3/05_one_horned_rhinoceros_madhubani_tshirt.png \
  generated/madhubani_animals/_learning/pass_examples/rhino_v3.png \
  --json /tmp/rhino_e2e_ranked.json
```

Output (rounded to 4 decimals):

| Rank | Variant | Composite | Rubric pass-fraction | CLIP P(Madhubani) | Active pass count | Failed checks | `auto_qc_pass` |
| :-: | :--- | -: | -: | -: | -: | :--- | :-: |
| 1 | v3 baseline | **0.8207** | 1.000 | 0.5518 | 7/7 | (informational only) | **True** |
| 1 | pass_example (= v3) | **0.8207** | 1.000 | 0.5518 | 7/7 | (informational only) | **True** |
| 3 | v2 mid | 0.8081 | 1.000 | 0.5202 | 7/7 | (informational only) | True |
| 4 | v1 mascot | **0.7056** | 0.857 | 0.4782 | 6/7 | `color_floor` | **False** |

Notes:

- **Composite = 0.6 × rubric_pass_fraction + 0.4 × CLIP probability.**
- Every active check (color floor, corners, centering, body fill, text leak, eye character, decoration zone presence) is gated; `anatomy`, `pattern_density`, and `anatomy_feature_count` ship disabled-by-default as informational signals (see [QC_AGREEMENT_STUDY](QC_AGREEMENT_STUDY.md) for the measured discrimination findings that drove that decision).
- v3 ties with the pass_example because they're the same file. The deterministic tie-break ordering (composite desc → CLIP desc → seed asc → filename asc) is what surfaces v3 first.
- v1 is the only variant the rubric rejects (`auto_qc_pass=False`) because it fails `color_floor`. Its CLIP score also drops (0.478 vs 0.55 for v3) — the learned discriminator agrees with the heuristic verdict.

CLIP probabilities are bunched in [0.48, 0.55] — close to the decision threshold 0.5 — because all four images share the same composition + similar palette. That's expected: CLIP is doing a finer-grained ranking than a "Madhubani-or-not" gate, which is exactly its job in the composite.

## Step 2 — Diagnose the loser (C.2)

Command:

```sh
python3 bin/art_reasoning_engine.py diagnose --animal rhino \
  generated/madhubani_animals/_legacy/indian_animals_v1/05_one_horned_rhinoceros_madhubani_tshirt.png
```

Output:

```
Diagnosed: ...indian_animals_v1/05_one_horned_rhinoceros_madhubani_tshirt.png
  Animal:           rhino
  auto_qc_pass:     False
  pass_count:       6/7
  Failed checks:    ['color_floor']
  Weakest (highest-severity failed): color_floor
```

Proposed boost clause for the next attempt:

> URGENT PALETTE FIX: the render is using too few folk-palette hues.
> Include AT LEAST 4 distinct colors from the Madhubani folk palette
> — deep-indigo (#1a2952), walnut-brown (#5a3a1f), saffron-orange
> (#e87722), vermillion (#c8261f), leaf-green (#3d7d3d), gold-yellow
> (#e8b827). Each color must be visible in at least one decoration
> zone. NO monochromatic renders. NO desaturated palettes.

The engine correctly identified the v1 mascot's actual failure mode (it uses a narrow, washed-out palette) and emitted a corrective clause that names the missing colors. If this boost were appended to the next render attempt, the model would have explicit, named hues to honor.

## Step 3 — Diagnose the winner (C.2)

Command:

```sh
python3 bin/art_reasoning_engine.py diagnose --animal rhino \
  generated/madhubani_animals/_legacy/indian_animals_v3/05_one_horned_rhinoceros_madhubani_tshirt.png
```

Output:

```
Diagnosed: ...indian_animals_v3/05_one_horned_rhinoceros_madhubani_tshirt.png
  Animal:           rhino
  auto_qc_pass:     True
  pass_count:       7/7
  Failed checks:    ['anatomy', 'anatomy_feature_count']
  Weakest (highest-severity failed): anatomy
```

Proposed boost clause for refinement (since `anatomy` is informational, this would only run if explicitly requested):

> FRAMING FIX: draw ALL anatomical limbs as DISTINCT outlines. For
> quadrupeds: 4 separate leg pillars visible, near and far pair both
> rendered (do not collapse far legs into the body). For birds: 2
> perched feet visible. For serpents: coil/curve shape, no implied
> legs.

The v3 render passes every *active* check (7/7), but the informational `anatomy` check flagged it because the side-profile rhino occludes the far pair of legs into the near pair — exactly the known false-positive mode documented in `DISABLED_BY_DEFAULT_CHECKS` in [`madhubani_qc.py`](../bin/madhubani_qc.py). The engine surfaces this as a *refinement* signal: useful if you want to push past 7/7 toward an explicit four-leg rendering, but not gating promotion.

## What this proves

End-to-end, no hand-tuning per variant:

1. **The rubric correctly grades** four variants of the same species across three eras, with the v3 baseline pulling 7/7 and the v1 mascot pulling 6/7.
2. **The CLIP probe ranks consistently** with the rubric — its probability is monotonic with composite score across the four variants (0.4782 → 0.5202 → 0.5518), so the learned model and the heuristic ensemble are not in conflict.
3. **The composite tie-break is deterministic** — identical files at rank 1 break by filename, not by random chance.
4. **The boost composer targets the actual failure** on the loser (palette diversity, which is exactly what's wrong with v1) and surfaces a useful refinement on the winner (anatomy occlusion, informational only).
5. **Disabled-by-default checks behave correctly** — `anatomy`, `pattern_density`, `anatomy_feature_count` all run and report but do not affect `auto_qc_pass`. This matches the data-driven posture from the agreement study: don't promote a check active until it shows positive discrimination on a labeled set.

## The full closed-loop receipts

```
  measure                score                 reason
  ───────                ─────                 ──────
  10-check rubric       composite              identify weakest
   - F1 0.67 on N=9     = 0.6 × rubric_frac    by severity table
   - 7 active            + 0.4 × CLIP_prob     (driven by measured
   - 3 informational    (F1 0.89 on N=9         discrimination, not
                        held-out gold)          intuition)

                ▼                                  ▼
                                                  
        rank winner                       look up boost clause
        log auditable                     fill template slots
        manifest                          (target_band, missing_zones,
                                          feature_specific failure)

                                                  ▼
                                                  
                                          append boost to prompt tail
                                          (idempotent, preserves intent)

                                                  ▼

                                          re-render via render_fn
                                          (injected — stub in tests,
                                          flux_generate_batch in prod)

                                                  ▼

                                          re-rank, accept or loop
                                          (cap at max_attempts)
```

Every primitive a closed-loop image-gen system would expose is in this
test path: the learned discriminator, the rubric ensemble, the ranked
manifest, the per-check boost table, the deterministic exit gate, the
severity-weighted picker driven by *measured* discrimination — and a
small, real species (rhino) exercising it end-to-end with the receipts
visible.

## Reproduce

```sh
# 1. Best-of-N
python3 bin/best_of_n.py --animal rhino \
  generated/madhubani_animals/_legacy/indian_animals_v1/05_one_horned_rhinoceros_madhubani_tshirt.png \
  generated/madhubani_animals/_legacy/indian_animals_v2/05_one_horned_rhinoceros_madhubani_tshirt.png \
  generated/madhubani_animals/_legacy/indian_animals_v3/05_one_horned_rhinoceros_madhubani_tshirt.png \
  generated/madhubani_animals/_learning/pass_examples/rhino_v3.png

# 2. Diagnose any variant
python3 bin/art_reasoning_engine.py diagnose --animal rhino \
  generated/madhubani_animals/_legacy/indian_animals_v1/05_one_horned_rhinoceros_madhubani_tshirt.png
```

Both commands work without `open_clip` installed; the composite gracefully degrades to rubric-only and the manifest records `clip_available: false`.

---

## Live closed-loop run — 2026-05-20 PM (mflux on M5 Max)

Following the maintainer's "did we actually run it" question, the
production-CLI wire-up at [`bin/forge_madhubani_reasoning.py`](../bin/forge_madhubani_reasoning.py)
ran end-to-end on rhino. The receipts are below.

### Run #1 — `--accept-score 0.80` (default)

Command:

```sh
python3 bin/forge_madhubani_reasoning.py --slug rhino \
  --max-attempts 2 --seeds-per-attempt 2 --accept-score 0.80
```

What ran:

| Step | Detail |
| :--- | :--- |
| Subject string | 11168 chars (full per-species metadata: anatomy + zones + density + body fill + palette + boost-stack) |
| Multi-seed batch | `mflux-generate-flux2 --model flux2-klein-4b --quantize 4 --steps 25 --seed 8200 8201` — two seeds in one batched mflux call |
| Style reference | `pass_examples/rhino_v3.png` at strength 0.72 (Lane-1 wiring) |
| Wall-clock | **42.3 s for 2 variants** (21.1 s/variant on M5 Max) |
| Pick best | Real `pick_best_of_n` with CLIP probe |
| Accept gate | composite ≥ 0.80 AND auto_qc_pass=True |

Receipt:

```
Attempt 1:
  winner path:        seed02.png
  composite:          0.8199
  rubric pass frac:   1.000
  CLIP P:             0.5498
  active checks:      7/7
  auto_qc_pass:       True
  failed checks:      ['anatomy', 'anatomy_feature_count']
  weakest check:      (none — passed)
  boost for next:     (none)

ACCEPTED: True  on attempt 1
```

The two failed checks are `anatomy` and `anatomy_feature_count`, both
disabled-by-default after the QC agreement study found them noisy on a
small labeled set ([QC_AGREEMENT_STUDY](QC_AGREEMENT_STUDY.md)). The
loop correctly treats them as informational and accepts on the first
attempt's 7/7 active-check pass.

The actual winning render (composite 0.8199, real mflux output, not a
pre-existing legacy file). Copied into the in-tree gallery for
reproducibility (the source under `generated/` is gitignored):

<div align="center">
  <img src="gallery/reasoning_loop/rhino_attempt1_composite_0.8199.png" alt="Live closed-loop rhino, attempt 1" width="420">
  <br><sub><i>Live mflux output (FLUX.2-klein-4b q4 25 steps, seed 8201, 21.1 s) — rhino render with composite 0.8199, accepted on attempt 1.</i></sub>
</div>

Ledger row written to `brand/madhubani/learning/runs.jsonl`:

```json
{
  "animal_slug": "rhino",
  "pose_slug": "standing-alert",
  "attempt": 1,
  "seed": 2,
  "composite": 0.8199,
  "rubric_pass_fraction": 1.0,
  "clip_likeness_probability": 0.5498,
  "auto_qc_pass": true,
  "active_check_count": 7,
  "pass_count": 7,
  "failed_checks": ["anatomy", "anatomy_feature_count"],
  "weakest_dimension": null,
  "boost_applied": null,
  "accepted": true,
  "render_path": "generated/madhubani_animals/reasoning_runs/rhino/20260520_161049/attempt_01/seed02.png",
  "model": "madhubani",
  "session_id": "e00070151e9f",
  "ts": "2026-05-20T21:11:36Z",
  "prompt_hash": "sha256:931709aa0e4ba860c800e573fd6ffb5ce20c8f141e2957c28b4d9a3331dc6e42",
  "schema": "forge.run_attempt.v1"
}
```

D.2 mining produced
[`brand/madhubani/learning/species_winning_prompts.md`](../brand/madhubani/learning/species_winning_prompts.md)
on the first-ever real ledger row:

```
Mined 1 rows (0 skipped) → 1 (species, pose) groups across 1 species
```

### Run #2 — forced retry path with `--accept-score 0.95`

Because run #1 cleared the 0.80 gate on attempt 1, the retry-with-boost
half of the loop never fired. Run #2 raises `--accept-score` to 0.95
so attempt 1 must fail the gate and the boost composer fires.

Command:

```sh
python3 bin/forge_madhubani_reasoning.py --slug rhino \
  --max-attempts 2 --seeds-per-attempt 2 --accept-score 0.95
```

Receipt:

```
Attempt 1:
  winner path:        seed02.png
  composite:          0.8199
  rubric pass frac:   1.000
  CLIP P:             0.5498
  active checks:      7/7
  auto_qc_pass:       True
  failed checks:      ['anatomy', 'anatomy_feature_count']
  weakest check:      anatomy                         ← weakest-check picker
                                                       falls back to
                                                       informational since
                                                       no active failures
  boost for next:     FRAMING FIX: draw ALL anatomical limbs as DISTINCT outlines.
                      For quadrupeds: 4 separate leg pillars ...

Attempt 2 (prompt = base + boost appended):
  winner path:        seed01.png
  composite:          0.8206
  rubric pass frac:   1.000
  CLIP P:             0.5515
  active checks:      7/7
  auto_qc_pass:       True
  failed checks:      ['anatomy', 'anatomy_feature_count']
  weakest check:      anatomy
  boost for next:     (same FRAMING FIX — would extend the boost stack)

ACCEPTED: False  on attempt 2
COMPOSITE DELTA attempt 1 → attempt 2: 0.8199 → 0.8206  (+0.0007)
```

Wall-clock per attempt: ~53-55 s (2 seeds, FLUX.2-klein-4b q4 25 steps).
Two attempts total ~108 s + model load ≈ 2 min.

Side-by-side:

<div align="center">
  <img src="gallery/reasoning_loop/rhino_attempt1_composite_0.8199.png" alt="Attempt 1 (composite 0.8199)" width="320">
  <img src="gallery/reasoning_loop/rhino_attempt2_boosted_composite_0.8206.png" alt="Attempt 2 with boost (composite 0.8206)" width="320">
  <br><sub><i>Attempt 1 (left, composite 0.8199, base prompt) vs Attempt 2 (right, composite 0.8206, base + FRAMING-FIX boost). Visually nearly indistinguishable; the boost composer fired correctly but the rhino was already at the corpus ceiling for this rubric + probe.</i></sub>
</div>

### Honest interpretation

**What worked:**
- ✓ The retry-with-boost path **fired correctly** when attempt 1 failed
  the 0.95 gate. The weakest-check picker fell back from "no active
  failures" to the highest-severity informational failure (anatomy)
  and emitted the appropriate boost clause from
  [`brand/madhubani/boost_prompts.json`](../brand/madhubani/boost_prompts.json).
- ✓ Attempt 2's prompt was the base prompt **with the FRAMING-FIX
  clause appended** — the prompt diff between attempts is real.
- ✓ Every primitive of the loop ran on real compute. No stubs.

**What didn't move:**
- ✗ Composite barely budged: **+0.0007** from attempt 1 to attempt 2.
  Both attempts cap at rubric=1.000 (every active check passes
  on every variant); CLIP probability hovers at 0.5498 → 0.5515
  (+0.0017). The rhino was already at the corpus ceiling.

**Why the ceiling is at 0.82, not higher:**
- The composite formula is `0.6 × rubric + 0.4 × CLIP`. With rubric
  pegged at 1.0, the ceiling is `0.6 + 0.4 × CLIP`. To break 0.85
  we'd need CLIP P ≥ 0.625; the current probe's effective range on
  rhino is 0.5-0.6.
- The CLIP probe was trained on 16 weakly-labeled era-bucket samples
  (per [`madhubani_likeness_v1.report.json`](../brand/madhubani/madhubani_likeness_v1.report.json)).
  Its decision threshold is near 0.5 and its dynamic range on a
  well-rendered Madhubani rhino is narrow.
- A LoRA-tuned CLIP encoder (re-extract features through the Madhubani
  LoRA from [`LORA_TRAINING_RECIPE`](LORA_TRAINING_RECIPE.md)) is the
  path to a probe with more dynamic range. Until then, the closed
  loop's "improvement headroom" via prompt boosting is bounded.

**What this measurement actually unlocks:**

The Phase D ledger now has 3 real rows from these two runs. Future
threshold tuning, boost-table edits, and probe-retraining can be
A/B-tested by replaying against the labeled ledger — *did the rhino's
composite move?* — without re-rendering. That's the feedback memory
working as intended.

To reproduce:

```sh
# Reproduce both runs:
python3 bin/forge_madhubani_reasoning.py --slug rhino \
  --max-attempts 2 --seeds-per-attempt 2 --accept-score 0.80   # run 1
python3 bin/forge_madhubani_reasoning.py --slug rhino \
  --max-attempts 2 --seeds-per-attempt 2 --accept-score 0.95   # run 2

# Mine the ledger:
python3 bin/feedback_memory.py learn

# Open the digest:
open brand/madhubani/learning/species_winning_prompts.md
```

### What this proves end-to-end

Every primitive of the Art Reasoning Engine spec now has a real-mflux
demonstration on the rhino species:

- **B.1 + B.2 + B.3** rubric checks ran against a fresh mflux output
  (not a pre-existing file) and reported 7/7 active passes.
- **C.1** composite picker chose `seed02.png` over `seed01.png` from
  the same batch using real CLIP probabilities.
- **C.2** weakest-check identifier saw all active checks pass and
  correctly emitted no boost (the early-accept path).
- **D.1** ledger row written with session_id, prompt_hash, timestamp,
  and full scoring detail.
- **D.2** mining produced the markdown digest from the live ledger.

The earlier honesty note ("we only ran the scoring half") is **no
longer accurate** — the rest of the loop is now demonstrated with real
compute. What remains pending: a run where the boost composer fires
and changes the prompt between attempts; that's the run #2 above.
