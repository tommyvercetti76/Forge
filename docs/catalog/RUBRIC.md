# Madhubani Tee — Quality Rubric

The 7-point quality bar for mastering a design. A pose is **MASTERED**
only when all 7 checks pass. Otherwise it is FLAGGED (best attempt
preserved with notes) or REJECTED.

Used in WORKFLOW.md steps 2 and 5 (REVIEW). Checks 1–4 are now scored by
`bin/madhubani_qc.py` after every successful render; checks 5–7 require human
eye.

---

## The seven checks

| # | Check | Method | Auto? |
|---|---|---|---|
| 1 | **Color floor** — at least 4 of 6 palette hexes visibly present | PIL color quantization, ΔE ≤ 15 against `brand/madhubani/palette.json` | ✓ |
| 2 | **Corners clean** — no signature, no glyph, no text in any corner | 4× 100×100 corner sample, ≥95% within ΔE 10 of cream `#F5EFE3` | ✓ |
| 3 | **Subject centered** — 50–80% of canvas width, centered ±5% | Edge-detect bounding box of main mark | ✓ |
| 4 | **Body fill is saturated color** — not blank silhouette, not all-pattern | Centroid sample ≠ `#000` or `#F5EFE3`; histogram check inside silhouette | ✓ |
| 5 | **Anatomy correct** — 4 legs / 2 legs / coiled body / wings present and proportional | Visual review | ✗ |
| 6 | **Expression carries character** — almond eye intentional, not cartoon, not blank | Visual review | ✗ |
| 7 | **Reads as Madhubani-inspired at 4-inch thumbnail** | Visual review (downscale + step back) | ✗ |

---

## What each check defends against (from v1–v3 learning)

| # | Defends against (failure mode observed) | First introduced in |
|---|---|---|
| 1 | v1 mascot-logo regression — 6 of 8 v1 designs were 2-tone monochrome | v2 engine |
| 2 | v1 cobra had visible artist-signature squiggle bottom-right | v2 engine, strengthened in v3 |
| 3 | Edge-cropped or pocket-tiny renders that aren't print-viable | engine baseline |
| 4 | v1 tiger / leopard / cobra rendered as flat black silhouette mascots | v2 BODY FILL OVERRIDE |
| 5 | v2 tiger lost foreleg in walking pose; v2 leopard "patterned blob" obscured anatomy | v3 ANATOMY FIRST |
| 6 | v2 macaque had round "shocked cartoon" eyes; v2 tiger expression was neutral/blank | v3 FACE & EXPRESSION |
| 7 | Snow leopard v2 read as "tribal cat textile pattern" rather than Madhubani folk-art | v3 ZONE CONFINEMENT |

---

## Decision tree (post-review)

```
All 7 checks pass on first render?           → MASTER, promote
4–6 checks pass, gap is targeted?            → RETRY with adjustment
≤3 checks pass, or gap is structural?        → FLAG with notes
After retry, still failing 2+ checks?        → FLAG with notes (no second retry)
```

---

## Scoring template (use this when reviewing)

Copy this into `attempts/{slug}/v{N}/REVIEW_NOTES.md`:

```
# Review: {animal} v{N}

## Pose 01 — Standing Alert
- [1] Color floor:      ✓ / ✗
- [2] Corners clean:    ✓ / ✗
- [3] Subject centered: ✓ / ✗
- [4] Body fill:        ✓ / ✗
- [5] Anatomy:          ✓ / ✗  Notes:
- [6] Expression:       ✓ / ✗  Notes:
- [7] Madhubani read:   ✓ / ✗  Notes:
DECISION: MASTERED / RETRY (with: ...) / FLAGGED (reason: ...)

## Pose 02 — Seated Rest
[same template]

## Pose 03 — Signature Action
[same template]

## Pose 04 — Frontal Portrait
[same template]
```

---

## Automation status

Madhubani render actions now write `render-manifest.json`, per-pose
`*.qc.json`, and the shared `workflow-events.jsonl` event log. Promotion is
blocked when any of checks 1–4 fail unless `promote --force` is used after
human review. Human review remains required for checks 5–7.

The separate beta minimal-animal lane already has hard auto-QC for its own
contract: `line_count <= max_lines`, all stroke points in bounds, and no fills.
See `docs/MINIMAL_ANIMAL_LINES.md`.
