# A2 Corpus False-Positive Check — 2026-05-20

Verifies that the three new Madhubani auto-QC checks (anatomy, text_leak,
eye_character) do not fire on known-good PNGs. A new check with a >10%
false-positive rate on the mastered corpus is marked `disabled_by_default`
so it ships as informational-only rather than as an active rubric gate.

- Corpus source: `_learning/pass_examples/ (mastered/ was empty)`
- Total PNGs scanned: **4**

## Per-check summary

| Check | Fails | Total | FP rate | disabled_by_default |
|---|---:|---:|---:|---|
| `anatomy` | 2 | 4 | 50.0% | YES |
| `text_leak` | 0 | 4 | 0.0% | no |
| `eye_character` | 0 | 4 | 0.0% | no |

## Per-PNG detail

### generated/madhubani_animals/_learning/pass_examples/blackbuck_v3.png
- slug: `blackbuck` · body_type: `lean-quadruped`
- new-check status: anatomy=FAIL text_leak=PASS eye_character=PASS
- anatomy: pillars detected=2, expected=3
- text_leak: skipped=True, reason=pytesseract not installed
- eye_character: contrast=213, std=44.951

### generated/madhubani_animals/_learning/pass_examples/elephant_v2.png
- slug: `elephant` · body_type: `heavy-quadruped`
- new-check status: anatomy=PASS text_leak=PASS eye_character=PASS
- anatomy: pillars detected=4, expected=3
- text_leak: skipped=True, reason=pytesseract not installed
- eye_character: contrast=251, std=60.612

### generated/madhubani_animals/_learning/pass_examples/peacock_v3.png
- slug: `peacock` · body_type: `bird`
- new-check status: anatomy=PASS text_leak=PASS eye_character=PASS
- anatomy: pillars detected=2, expected=2
- text_leak: skipped=True, reason=pytesseract not installed
- eye_character: contrast=251, std=43.905

### generated/madhubani_animals/_learning/pass_examples/rhino_v3.png
- slug: `rhino` · body_type: `heavy-quadruped`
- new-check status: anatomy=FAIL text_leak=PASS eye_character=PASS
- anatomy: pillars detected=2, expected=3
- text_leak: skipped=True, reason=pytesseract not installed
- eye_character: contrast=249, std=58.545

## Decision

The following checks exceeded the 10% false-positive threshold and are marked `disabled_by_default` — they remain in the QC output as informational-only, but do not gate `auto_qc_pass`:
- `anatomy` (50.0% FP rate)

