# Translation Agent Handoff — North Star + Karpathy-Grade Roadmap

> Created: 2026-05-20
> Owner: parallel translation agent (sibling to the vision-QC + LoRA lane)
> Reads: this doc + [`docs/BOOK_LOCALIZATION_AUDIT_HANDOFF.md`](BOOK_LOCALIZATION_AUDIT_HANDOFF.md) + [`docs/QC_AGREEMENT_STUDY.md`](QC_AGREEMENT_STUDY.md) (methodology reference)

## Mission (North Star)

Forge has the world's-best-on-Apple-Silicon **image** stack today. Translation is the parallel lane that must close out by EOD. The deliverable is **one local-first multilingual pipeline** that lands six things:

1. **Transcription in EN / HI / MR** — Whisper-driven, word-level timestamps, punctuation-restored.
2. **Subtitles** — broadcast-grade SRT/VTT, forced-aligned, language-specific reading-speed gates.
3. **Book → audiobook converter** — full-page coverage (not excerpt), chapter-segmented, manifest-tracked.
4. **ASMR pre-sets** — measurable acoustic specifications, not vibes: meditation / sleep-story / soft-tale / calm-explainer.
5. **Measured translation quality** — BLEU + chrF + named-entity preservation + glossary hit-rate per language pair, on a small labeled corpus. **This is the Karpathy-bar item.**
6. **One trained or fine-tuned translation/TTS artifact** — analogous to the just-shipped LoRA pilot. A small adapter on top of Sarvam-translate or a learned punctuation-restoration probe. The point is the same: stop being inference-only.

## What's already shipped (don't re-do)

| Item | File / commit |
| :--- | :--- |
| B1 — multi-format input adapter (`.txt` / `.rtf` / `.pdf` / audio) | [`bin/input_adapter.py`](../bin/input_adapter.py) |
| B2 — glossary + leakage primitives | [`bin/engine_qc.py`](../bin/engine_qc.py) lines 167-200 (`glossary_violations`, `leakage_flags`) |
| B3 — Translate Studio web tab | [`bin/translate_web.py`](../bin/translate_web.py) |
| B4 — SRT estimate sidecar | [`bin/translate_web.py`](../bin/translate_web.py):60-89 (`_estimate_srt`, `_srt_ts`) |
| B6 — translation blockers via `engine_qc` | [`bin/engine_qc.py`](../bin/engine_qc.py) `translation_report_to_qc` |
| ASMR pipeline scaffolding | [`bin/audiobook.py`](../bin/audiobook.py) |
| WhatsApp share format | [`bin/whatsapp_joke_factory.py`](../bin/whatsapp_joke_factory.py) |
| Translation QA double-pass | [`bin/forge.py`](../bin/forge.py) `translation_qc_twice` (audiobook path doesn't use this yet — P1 in audit) |
| Translation engine default | `hf.co/mradermacher/sarvam-translate-GGUF:Q4_K_M` via `bin/forge_runtime.py:translate_texts_ollama` |

## What's broken (canonical audit)

[`docs/BOOK_LOCALIZATION_AUDIT_HANDOFF.md`](BOOK_LOCALIZATION_AUDIT_HANDOFF.md) is the authoritative list. The P0 gaps in summary:

- **B5 / Full-page mode** — `audiobook.py --batch-pages 10` is currently excerpt mode (150 words/page default). Must add `--full-page`.
- **Subtitles aren't canonical text** — currently regenerated from Whisper transcription of mastered audio. Approved translation must be the source of truth.
- **No human review gate** — no per-segment approval state.
- **No glossary enforcement in audiobook path** — primitives exist in `engine_qc.py`, not wired into ASMR.
- **No source-extraction audit** — page boundaries, OCR garbage, repeated headers not flagged.
- **Subtitle readability not gated** — no max chars/line, no reading-speed cap, no min/max cue duration.
- **VTT output is misnamed SRT** — `--subtitles vtt` does not write a real `WEBVTT` header.
- **Audio QC is too weak** — no peak/loudness/silence/coverage gates.

## North-Star deliverables — six items, three days

### Day 1 — Foundation (measure, then improve)

**T1. Translation Agreement Study** (~3 hrs · the methodology that unlocks everything)

The vision QC went from F1 0.33 → 0.89 because we built a measurement first. Mirror that exactly:

- New file: `bin/translate_agreement_study.py`
- New corpus: `brand/translate/agreement_corpus/{en,hi,mr}/` with 15-25 short paragraphs, each language a separate `.txt` file, sentence-aligned.
- Sources: pick from public-domain Indian literature (e.g. Premchand stories, Tagore translations) so EN/HI/MR reference triples can be hand-curated without copyright headache.
- For each paragraph, run `bin/forge_runtime.translate_texts_ollama` (or whatever the current translate entry-point is) on EN → HI, EN → MR, HI → EN, MR → EN.
- Compute per-pair: **BLEU** (sacrebleu), **chrF**, **named-entity preservation rate** (use a spaCy or regex pass — Indian proper nouns must survive), **glossary hit-rate** (using existing `engine_qc.glossary_violations`).
- Emit `docs/TRANSLATION_AGREEMENT_STUDY.md` with confusion-matrix-style tables, per-language headline numbers, and a "failure modes" section pulling 3-5 actual mistranslations from the corpus.
- README hero gets a new number: e.g. *"BLEU 31.2 EN→HI, 28.4 EN→MR on a 20-paragraph labeled set."*

**T8. Full-page mode in `bin/audiobook.py`** (~2 hrs · closes a P0 from the existing audit)

- Add `--full-page` flag (or `--coverage full|excerpt`). When set, ignore `--spoken-words` and translate/narrate the entire selected page range.
- Emit a coverage receipt in the run manifest: `{source_word_count, narrated_word_count, coverage_ratio}`.
- Update README Reality Check to reflect that full-page is now the supported mode and excerpt is the explicit opt-in.
- Test: pick a 10-page sample, run with and without `--full-page`, assert ratio = 1.0 in the full-page case.

**T3. Forced-aligned subtitles** (~2 hrs · production-grade SRT)

- `_estimate_srt` in `bin/translate_web.py` uses a fixed `words_per_second` estimate. Replace with **Whisper word-level timestamps** for any input that has audio. For text-only inputs, keep the estimate path but tag the output `{aligned: false}` so downstream callers know.
- Use `mlx_whisper` (already a dep per `bin/audiobook.py` usage).
- New util: `bin/subtitle_align.py` that takes (approved_text, audio_path) → SRT/VTT with real word-level cue timing.
- **Approved translation text is canonical** (per audit P0): the alignment derives *timing* but not *content*.
- Test on the same 10-page sample from T8.

### Day 2 — Quality bar (define + measure)

**T4. ASMR acoustic spec** (~2 hrs · "ASMR" becomes a measurable thing, not a vibe)

- New file: `brand/translate/asmr_presets.json`
- Define four presets, each with numeric acoustic targets:

| Preset | Speaking rate (WPM) | Breath gap (sec) | Loudness (LUFS) | Peak (dBFS) | EQ profile |
| :--- | -: | -: | -: | -: | :--- |
| `meditation` | 80-100 | 1.2-2.0 | -22 | -3 | warm low-shelf, gentle high-roll |
| `sleep-story` | 90-110 | 0.8-1.5 | -20 | -2.5 | similar, slightly brighter |
| `soft-tale` | 110-130 | 0.5-1.0 | -19 | -2 | flat with a slight warm tilt |
| `calm-explainer` | 130-150 | 0.3-0.7 | -18 | -1.5 | flat broadcast |

- Wire each preset through `bin/audiobook.py` as a `--asmr-preset` flag.
- Implement loudness + peak verification via ffmpeg/sox; fail-loud if a render's measured loudness drifts more than 1.5 LU from target.
- Receipt format: `{preset, target_wpm, measured_wpm, target_lufs, measured_lufs, drift_ok}`.
- This is the *spec*. The user can now ask "what does ASMR mean here?" and get a JSON answer.

**T7. Local TTS benchmark** (~3 hrs · honest cost/quality story)

- Compare local TTS options vs Sarvam (cloud) for HI / MR:
  - Kokoro (already in stack for EN)
  - Bark (https://github.com/suno-ai/bark — multilingual)
  - Parler-TTS (https://github.com/huggingface/parler-tts)
  - MeloTTS (https://github.com/myshell-ai/MeloTTS — multilingual)
  - Sarvam Bulbul (current default for HI/MR)
- Run the same 5 sentences through each. Save the WAVs in `docs/gallery/tts_benchmark/`.
- Do a self-MOS: rate each on 1-5 for (intelligibility, naturalness, prosody, language identity). Be honest — your own MOS is a single labeler, document that.
- Output: `docs/TTS_BENCHMARK_2026-05-20.md` with the matrix, per-sample audio links, and a recommendation per language.
- Verdict goes in the README hard-problems table as a new entry: *"Local-vs-cloud TTS measured — local wins for X / cloud wins for Y / hybrid is the default."*

**T9. Format-preserving translation** (~2 hrs)

- Translation today returns flat strings. Markdown / code-fences / heading anchors / hyperlinks all break.
- Add a `--preserve-format` flag to whatever the current translate CLI is.
- Implementation: pre-extract markdown tokens (headings, code blocks, links, images, lists) into a `{token_id: original}` map. Translate the text-only stretches. Re-inject tokens.
- Test on `docs/MADHUBANI_ART_IDENTITY.md` (which has tables, links, code-fences). The translated output must round-trip back through markdown → HTML without breaking.

### Day 3 — Karpathy-grade depth

**T2. Round-trip drift measurement** (~1 hr · cheap baseline, no human labels)

- For each EN sentence in the T1 corpus, do EN → HI → EN and EN → MR → EN. Compute BLEU vs the original.
- Report as a single number per language pair. Honest interpretation: high BLEU drift means information loss; low BLEU drift means stable round-trip.
- Add as a column in the T1 confusion matrix.

**T5. Fine-tuned translation adapter** (~4 hrs · the "trained model" Karpathy-bar item)

- Pick the easiest local adapter target: a **LoRA on top of Sarvam-translate** or a **learned punctuation-restoration probe** on Whisper output.
- Recommended: punctuation restoration. Whisper outputs unpunctuated streams for Hindi/Marathi. Train a small bidirectional model (BiLSTM or small transformer) on a 1000-sentence corpus of (unpunct → punct) pairs. Save weights under `brand/translate/punct_restore_v1.npz`.
- This is the parallel to the just-shipped `madhubani_likeness_v1.npz` — a real trained artifact, reproducible from a script (`bin/train_punct_restore.py`).
- Document in `docs/PUNCT_RESTORE_RECIPE.md` with confusion-matrix-style numbers.

**T6. Code-switching detection** (~2 hrs · genuine technical contribution)

- Indian speech is heavily code-switched (Hinglish, Minglish — English nouns and verbs embedded in Hindi/Marathi clauses).
- Add a `detect_code_switch(text)` pass that fragments input into language-tagged spans (`[(span, "en"), (span, "hi"), ...]`).
- Route each span to the appropriate TTS voice in the audiobook path.
- Threshold: must correctly tag at least 80% of word-boundary code switches on a 50-sentence Hinglish test set you'll author from public-domain Indian Twitter/text corpora.

**T10. Technical writeup** (~2 hrs · the Karpathy-attention item)

- One blog-post-depth piece, ~1500 words, on a non-obvious technical insight from the above work. Candidates:
  - *Why English→Hindi BLEU is misleading for code-switched Indian content (and what we use instead).*
  - *Building an ASMR acoustic spec: defining "calm-explainer" as four numbers.*
  - *Local-vs-cloud TTS for Indic languages: measured cost, latency, and quality tradeoff.*
- Commit as `docs/POSTS/TRANSLATION_PILOT_LESSONS.md`. Link from README hard-problems table.

## What's Karpathy-grade about this set?

| Item | Why Karpathy would notice |
| :--- | :--- |
| **T1 (Translation Agreement Study)** | Methodology. Measuring your eval against ground truth is the differentiator between "I used Google Translate" and "I built a multilingual pipeline." |
| **T4 (ASMR acoustic spec)** | Turns vibes into numbers. Calm-explainer = 130 WPM @ -18 LUFS is checkable, not aesthetic. |
| **T5 (trained punct-restore model)** | Stops being inference-only. Even a 10K-param LSTM trained locally beats "I called an API." |
| **T6 (code-switching)** | India-specific technical depth. Most multilingual stacks fall over on Hinglish; you'd be measuring how badly and fixing it. |
| **T7 (Local TTS benchmark)** | Honest cost-quality tradeoff with audio receipts. The kind of thing he retweets. |
| **T10 (writeup)** | Karpathy's bar: "what did you learn that I couldn't already know?" |

## Implementation order summary

```
Day 1 (foundation):
  T1  Translation Agreement Study (~3 hrs)   ← do FIRST, unblocks measurement
  T8  Full-page audiobook mode (~2 hrs)      ← closes P0 from existing audit
  T3  Forced-aligned subtitles (~2 hrs)      ← uses Whisper word-level

Day 2 (quality):
  T4  ASMR acoustic spec (~2 hrs)            ← defines "what is ASMR" numerically
  T7  Local TTS benchmark (~3 hrs)           ← honest cost-quality table
  T9  Format-preserving translation (~2 hrs) ← markdown survives translate

Day 3 (Karpathy-grade depth):
  T2  Round-trip drift (~1 hr)               ← cheap baseline
  T5  Trained punct-restore model (~4 hrs)   ← the "trained model" item
  T6  Code-switching detection (~2 hrs)      ← India-specific depth
  T10 Technical writeup (~2 hrs)             ← teaches one non-obvious thing
```

Total: ~23 hrs across 3 days. Tight but doable for a focused agent.

## Off-limits (parallel-lane collisions to avoid)

While this work is happening, the vision-QC + LoRA lane (the sibling agent) is touching these files. **Do not edit them** — open a coordination PR if a change feels unavoidable:

- `bin/madhubani_qc.py`, `bin/qc_agreement_study.py`, `bin/train_madhubani_likeness.py`, `bin/forge_madhubani_lora.py`
- `docs/QC_AGREEMENT_STUDY.md`, `docs/LORA_TRAINING_RECIPE.md`, `docs/ART_REASONING_ENGINE*.md`
- `docs/gallery/lora_pilot/`, `docs/gallery/peacock_v3.png` etc.
- `brand/madhubani/madhubani_likeness_v1.npz`
- `pyproject.toml`, `.gitignore`
- README hero block (lines 1-80) — coordinate before editing this; it's been edited multiple times today

**Fair-game files** (translation lane owns these):
- `bin/translate*.py`, `bin/audiobook.py`, `bin/whatsapp_joke_factory.py`, `bin/forge_runtime.py` (the translate functions only — there's other stuff in there)
- `bin/input_adapter.py`
- New: `bin/translate_agreement_study.py`, `bin/subtitle_align.py`, `bin/train_punct_restore.py`
- `brand/translate/` subtree (does not exist yet — create it)
- `docs/AUDIOBOOK_API.md`, `docs/AUDIOBOOK_HANDOFF.md`, `docs/BOOK_LOCALIZATION_AUDIT_HANDOFF.md`, `docs/WHATSAPP_JOKE_FACTORY_HANDOFF.md`
- New: `docs/TRANSLATION_AGREEMENT_STUDY.md`, `docs/TTS_BENCHMARK_2026-05-20.md`, `docs/PUNCT_RESTORE_RECIPE.md`, `docs/POSTS/TRANSLATION_PILOT_LESSONS.md`
- `docs/gallery/tts_benchmark/`
- Sections of README OUTSIDE the hero (hard-problems table additions, capabilities table, etc.) — coordinate via PR

## Coordination protocol

1. `git pull --rebase origin main` before starting any task.
2. Work on a feature branch per task: `feature/translation-T1`, `feature/translation-T8`, etc.
3. Each task ends with: tests still passing (`python3 -m unittest discover tests` → 128+ passing, 1 skipped), feature-branch pushed, PR opened against `main`.
4. Don't push directly to `main` — coordinate with the maintainer via PR.
5. If a hot file (off-limits list above) needs editing, open a draft PR with the proposed change and stop; the maintainer will rebase or merge sibling work first.

## Success criteria — what "done" looks like by EOD Day 3

A reviewer scanning github.com/tommyvercetti76/Forge after this lane lands should see:

- README hard-problems table with two new entries: *"Multilingual translation measured against ground truth — BLEU X EN→HI, BLEU Y EN→MR on N-paragraph labeled corpus"* and *"ASMR is a measurable spec — 4 presets with numeric loudness, pace, breath-gap targets, verified per-render."*
- A new hero number alongside `F1 0.89` and `−60.8%`: *"BLEU X.X on hand-labeled HI/MR set."*
- `docs/TRANSLATION_AGREEMENT_STUDY.md` with confusion-matrix tables + failure-mode catalog (mirrors `QC_AGREEMENT_STUDY.md`).
- `docs/TTS_BENCHMARK_2026-05-20.md` with audio receipts in `docs/gallery/tts_benchmark/`.
- `docs/PUNCT_RESTORE_RECIPE.md` with one trained probe (`brand/translate/punct_restore_v1.npz`, ~5-50 KB).
- `docs/POSTS/TRANSLATION_PILOT_LESSONS.md` — one ~1500-word writeup.
- `audiobook.py --full-page` works, ASMR presets are wired, subtitles are forced-aligned.
- The full test suite is green.

## Two parallel Karpathy gaps now in flight

| Gap | Vision lane (already shipped today) | Translation lane (this handoff) |
| :--- | :--- | :--- |
| Measured eval | F1 0.89 auto-QC vs human | BLEU + chrF + NE-preservation per language pair |
| One trained model | `madhubani_likeness_v1.npz` (CLIP+LR) + 50-step LoRA | `punct_restore_v1.npz` (BiLSTM) on Indic punct restoration |
| Technical writeup | `QC_AGREEMENT_STUDY.md` + `LORA_TRAINING_RECIPE.md` | `TRANSLATION_PILOT_LESSONS.md` + `TTS_BENCHMARK_*.md` |

When both lanes land, Forge has the receipts for "I built a measured eval-driven local-first multilingual generative-AI workstation on Apple Silicon" — not the kind of claim you usually see backed by actual numbers + code + checkpoints in a portfolio repo.
