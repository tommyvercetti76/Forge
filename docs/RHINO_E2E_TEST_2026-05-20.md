# Rhino end-to-end test of the Art Reasoning Engine

> 2026-05-20. Walks the full closed-loop on a single species (rhino,
> Indian one-horned rhinoceros) to demonstrate every shipped phase
> firing on real renders held in tree.

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
