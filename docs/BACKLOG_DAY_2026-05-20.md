# Forge — Day Backlog, 2026-05-20

Already shipped today: **P1 multi-seed batch** (−60.8% wall on cool/schnell), **Q1 blockers/publishable trust layer**, and [docs/QUALITY_FINDINGS_2026-05-20.md](QUALITY_FINDINGS_2026-05-20.md). One commit: `b618f2c`.

Two end-of-day goals stack vertically (do A before B unless something blocks). Each goal has a clear "done", a current-state snapshot, a ranked task list, and one recommended next ship.

---

## Goal A — Highest-quality Minimalist T-shirt images, Madhubani Animals priority

### Definition of done

A 60-animal Madhubani catalog where every promotable PNG:

1. Renders at production resolution (≥1280²) at `quality` profile in one batch per pose set.
2. Carries species-defining iconography (ocelli for tigers, hood for cobras, train for peacocks, etc.) consistently across all 4 poses of the same animal.
3. Passes 5+ of the 7 rubric checks auto (vs 4/7 today).
4. Has a `publishable: true` manifest entry and no `blockers.json` sibling.
5. Renders end-to-end in ≤120 s per 4-pose set on M5 Max (was ~10–14 min before P1 + `--jobs`).

### What's working now (don't break)

- Madhubani schema at [brand/madhubani/animals.json](../brand/madhubani/animals.json) (8 body types, 3 series, body-fill anchors per animal).
- Pose schema, palette schema, masters schema all in `brand/madhubani/`.
- `bin/forge_madhubani.py render <animal> --all-poses --jobs N` (parallel poses).
- `madhubani_qc.py` — 4/7 auto rubric checks (color_floor, corners_clean, subject_centered, body_fill).
- Promote gate at `forge_madhubani promote --force` (now also reads `blockers.json` via Q1).
- LoRA stack `realism-xlabs@0.8 + add-details@0.5` auto-applied for the minimalist-tshirt engine.

### Ranked tasks for Goal A

| # | Task | Why this matters | Effort | Yield |
|---|---|---|---|---|
| **A1** | **Lever B: per-species iconography table inside the minimalist-tshirt builder** | Closes the visible gap (ocelli, whiskers, hood, train) that even quality profile leaves on the floor. Draft text already in [QUALITY_FINDINGS_2026-05-20.md](QUALITY_FINDINGS_2026-05-20.md). | S (~3 h) | Largest single-shot quality gain available without training |
| **A2** | **Q7-α: extend Madhubani QC checks to the rest of the minimalist-tshirt rubric** | Adds 3 of the remaining 3 rubric items as machine gates: anatomy proportions (body-type rules from animals.json), eye/character presence, text-leak (OCR via tesseract). Makes the 5/7 → 6/7 → 7/7 progression real. | M (~1 day) | Lifts auto-gated rubric coverage from 57% → 86% → 100% |
| **A3** | **Per-pose deterministic seed bible per animal** | Same animal across 4 poses → consistent palette, same posture language, same eye character. `forge_madhubani.py` line 333 today derives per-pose seeds independently; add a `--series-seed` override that locks visual continuity. | S (~3 h) | Catalog cohesion; reviewer sees one tiger, not four different tigers |
| **A4** | **Promote-flow integrates blockers.json into the workflow event log** | Q1 ships the file; the workflow log doesn't yet quote *which* blockers were overridden when `--force` is used. Audit trail value. | S (~1 h) | Cleaner forensics on why a render was force-promoted |
| **A5** | **Default `--profile quality` + `--upscale 4x` for promote-ready Madhubani runs** | The quality test today proved dev/36/q8 brings whiskers + eye character. Cool/schnell stays the default for `attempts/`; `mastered/` should re-render at quality before promotion. | S (~2 h) | Closes the cool→mastered quality drop |
| **A6** | **Lever C: default `--refine` on for `quality` profile** | Existing code, just a default flip. Adds img2img polish pass. Costs ~25 extra seconds per render but adds visible micro-texture. | S (~1 h) | Compounds with A1/A5 |
| **A7** | **Wildlife-photo + minimalist-tshirt LoRA training** | Largest absolute jump, but ~$50 cloud GPU + 2 days curation. Park until A1+A2+A3 are exhausted. | L (3 days) | Burned-in species identity |

### One recommended next ship for Goal A

**A1 (per-species iconography table).** Smallest, highest-impact, no infrastructure. Concrete plan:

1. Add `SPECIES_ICONOGRAPHY` dict in `bin/style_engines.py` keyed by lowercase species name. Body draft already in [QUALITY_FINDINGS_2026-05-20.md](QUALITY_FINDINGS_2026-05-20.md).
2. In `MinimalistTShirtEngine.build()`, parse `clean_subject` for known species names; if found, append the iconography phrase after master citations and before universal negatives.
3. Lock under a `lore: "species-v1"` audit field so old recipes can opt out via a recipe-level flag.
4. Re-render `tiger`, `cobra`, `peacock`, `elephant` 4-pose sets at quality profile (cost: ~4 min/animal × 4 = 16 min). Compare ocelli/whisker/hood/train fidelity to today's baselines.
5. Tune the phrases until ≥3 of 4 poses per animal render the iconic feature visibly. Document the verified set in `docs/MINIMALIST_TSHIRT_ENGINE.md`.

**Done = the new dict, the wiring, one round of empirical tuning on 4 priority animals, and updated engine docs.** No need to expand to 60 animals on day one — establish the contract on 4 marquee species first.

### Open decisions to make before starting A1

- **Where does the dict live?** In `style_engines.py` (close to the engine that consumes it) or in `brand/madhubani/species_iconography.json` (data, not code)? Data file is easier to edit; code is faster to merge. Recommend data file for the long tail.
- **Should the dict apply only when the user picks a known species, or also when an LLM classifier infers it?** Recommend: explicit-only on day one; LLM inference is Q9 territory.

---

## Goal B — Translation Studio: one-click language convert with multi-format inputs

### Definition of done

A dedicated web page (e.g. `forge web` adds a top-level **TRANSLATE** tab next to GALLERY · CREATE · EDIT · PIPELINES · LIBRARY · SYSTEM) where:

1. Input is one of: raw textarea, file upload (`.txt`, `.pdf`, `.rtf`), or recorded/uploaded voice (`.wav`/`.mp3`/`.m4a`).
2. User picks a target language from a single dropdown (en, hi, mr, plus add ta/bn/gu/te/kn/pa as data grows). Defaults to last-used pair.
3. One **Translate** button kicks off the pipeline; progress streams in the same tab (no full-page reload).
4. Result page shows: source text, translated text, optional outputs (subtitles SRT/VTT, thumbnail card PNG, audiobook WAV).
5. Every run produces a manifest with: source hash, target lang, glossary used, translator model, latency, blockers (if any).
6. Output bundle is one click away as a downloadable folder.

### What's working now (don't rebuild)

- `translate_texts_ollama` ([bin/forge_runtime.py:263](../bin/forge_runtime.py:263)) — 3-retry batch with placeholder detection + per-item fallback. **No glossary yet.**
- `bin/audiobook.py` — full pipeline already does book → translation → narration → subtitles → muxed MP4. Has `parse_rtf` ([line 475](../bin/audiobook.py:475)), `generate_subtitles` ([line 233](../bin/audiobook.py:233)), `derive_thumbnail_brief` ([line 282](../bin/audiobook.py:282)), Whisper STT, Kokoro/Sarvam TTS.
- Sarvam Bulbul cloud TTS for hi/mr via `SARVAM_TTS_KEY`.
- `mlx_whisper` is ready (`forge doctor` confirmed) — voice → text is one call away.
- Web UI scaffolding at [bin/forge_web.py](../bin/forge_web.py) with the 6-area decluttered layout.

### Ranked tasks for Goal B

| # | Task | Why this matters | Effort | Yield |
|---|---|---|---|---|
| **B1** | **Input adapter module: `bin/input_adapter.py`** | One function `read_as_text(path_or_string) -> str` that handles raw text, .txt, .pdf (pdfplumber), .rtf (existing `parse_rtf`), and audio (Whisper). Pre-req for the UI and a clean unit-testable surface. | M (~half day) | Reusable across translate, audiobook, episode |
| **B2** | **Translation core lift: glossary + leakage detection** | Take `translate_texts_ollama` and add `glossary: dict[str, dict[str, str]]` + English-leakage detector + repeated-line blocker. Existing function gets enriched, NOT replaced. Engine-quality plumbing for the new UI. | M (~1 day) | Closes Q4 of the prior backlog; gives the UI a translator it can trust |
| **B3** | **Translate web tab: minimal flow** | New `/translate` route in `forge_web.py`; reuses input adapter (B1) + translation core (B2). Form fields: source picker (radio: paste/upload/voice), target lang dropdown, output options (sub: SRT/VTT/none, thumb mask: yes/no, audiobook: yes/no), submit. Streams progress via existing job pattern. | M (~1 day) | The UI surface the user asked for |
| **B4** | **One-click subtitle output** | Reuse `bin/audiobook.py`'s subtitle path: source text + synthesized audio → Whisper-aligned SRT/VTT. Already works for audiobook; expose under the new tab. | S (~3 h) | Big perceived value; no new code |
| **B5** | **Thumbnail mask: localized headline over a brand-preset background** | Pulls in `forge thumbnail` with `--headline <translated>`. New: a `mask` flag that just renders the text card without generating a background (so user can drop their own video frame in). | S (~3 h) | Closes the "thumbnail masks" item from the user ask |
| **B6** | **Manifest + blockers for translation runs** | Lift the Q1 contract (publishable, blockers.json, --allow-qc-warnings) to translation outputs: missing glossary terms, residual English in non-English target, length-ratio anomalies. | S (~3 h) | Trust layer parity with image renders |
| **B7** | **Voice input round-trip: record → translate → speak** | Mic capture in the browser (MediaRecorder), Whisper STT server-side, translate, Kokoro/Sarvam TTS, drop the WAV next to the manifest. Convenience layer over B1–B4. | M (~1 day) | The "voice in, voice out" demo |
| **B8** | **Batch mode: drop a folder, get a translated folder** | CLI side: `forge translate <input-dir> --target hi --out <out-dir>`. Reuses B1+B2; iterates over each file. | S (~3 h) | Power users; library translation |

### One recommended next ship for Goal B

**B1 (input adapter module).** Everything else stacks on top, and it's the smallest unit-testable piece. Concrete plan:

1. Create `bin/input_adapter.py` with `read_as_text(path: Path | str, *, kind: Literal["auto","text","txt","pdf","rtf","audio"]="auto") -> dict[str, Any]` returning `{"text": str, "source_kind": str, "metadata": {...}}`.
2. Implement four dispatches: raw string passthrough, `.txt` UTF-8 read, `.rtf` via existing `audiobook.parse_rtf`, `.pdf` via pdfplumber (add to deps if missing), audio via `mlx_whisper`.
3. Add a `--kind` override flag for ambiguous filenames.
4. Unit tests: each source kind → expected text (synthetic small fixtures in `tests/fixtures/`).
5. Manifest entry: source hash (`hashlib.sha256` over the bytes), `source_kind`, `length_chars`, `length_words`.

**Done = the module, 4 working dispatches, ≥6 unit tests, and a one-line addition to `audiobook.py` that swaps its inline `parse_rtf` call for the new adapter to prove reuse.**

### Open decisions to make before starting B

- **Target languages for v1?** Recommend: en, hi, mr only on day one (already battle-tested via Sarvam). Add ta/bn/gu/te/kn/pa once the UI ships.
- **Local-only or cloud TTS for Indic?** Honest constraint: Sarvam needs `SARVAM_TTS_KEY`. Recommend: default to local Kokoro for en, Sarvam for hi/mr with a visible warning when key is missing.
- **Where does the translate tab live in the web nav?** Adding a 7th top-level area vs nesting under PIPELINES. Recommend: top-level **TRANSLATE** because the user called it out as a separate UI.
- **Should the UI block until translation is done, or stream chunks as they complete?** Streaming is better UX but requires plumbing the existing job event pattern. Recommend streaming — it's already how the render console works.

---

## Suggested day shape

Per the "stay focused, don't bloat" rule: **A1 → measure → A2 if A1 didn't carry. Then B1 → B2 → B3.** Do not start B until A1 is shipped *and* the Madhubani 4-animal smoke test is green.

| Block | Goal | Task | Why this order |
|---|---|---|---|
| Morning | A | **A1** Lever B iconography table + 4-animal verify | Closes the visible quality gap on the priority deliverable. Smallest, fastest win. |
| Midday checkpoint | — | Decide A2 vs jump to B | If A1 alone pushes 4/7 → 5/7 rubric, B is next. If not, do A2 first. |
| Afternoon | B | **B1** input adapter + tests | Foundation for the translation UI. Stackable, testable, no UI yet. |
| Late afternoon | B | **B2** glossary + leakage detection in `translate_texts_ollama` | Makes the translator decisive instead of hopeful. |
| Evening (if time) | B | **B3** minimal translate tab in `forge_web.py` | Now you have something demoable end-to-end. |

Everything below the day-line stays parked. The doc above will be the place to add new items as they surface — don't add half-finished work into code.

---

## Verification checklist for end-of-day claim

- [ ] A1: 4 priority animals (tiger, cobra, peacock, elephant) each have 4 poses where the iconic feature is visibly present in ≥3 of 4. Manifests show it; the auto-QC stays passing on the existing 4/7 checks.
- [ ] A1: `docs/MINIMALIST_TSHIRT_ENGINE.md` is updated with the new iconography contract.
- [ ] B1: `bin/input_adapter.py` exists; ≥6 unit tests pass under `python3 -m unittest discover -s tests`.
- [ ] B2: `translate_texts_ollama` accepts a `glossary` kwarg and a test proves enforcement on at least one term.
- [ ] B3 (stretch): a curl to `POST /translate` returns translated text + a manifest URL.
- [ ] One commit per landed task; commit messages name the task ID (A1 / A2 / B1 / B2 / B3).
- [ ] No regressions in `python3 -m unittest discover -s tests` (currently 47 passing).
