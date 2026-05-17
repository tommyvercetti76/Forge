# Forge Alignment Review and Execution Plan

Created: 2026-05-17

## Executive Read

Forge is no longer just a pile of scripts. It is a working local production
system with a clear center of gravity: book/text/video inputs become branded,
offline, multi-language media bundles backed by local models.

The vision in `PLAN_V2.md` is still ahead of the implementation, but the gap is
not existential. The core substrate is in place: canonical model storage,
doctor/warmup checks, FLUX generation/editing, Whisper transcription, Sarvam
translation, Kokoro/macOS TTS, ffmpeg assembly, presets, series locks, manifests,
and QC JSON.

The main gap is trust. Forge can generate outputs, but it does not yet make a
strong enough publishability claim. Today it mostly says, "I produced this and
here are notes." The vision requires, "I verified this, blocked the bad parts,
and gave you one review surface to approve or repair."

Working estimate: Forge is about 60-65% of the way to the V2 story-studio
vision.

## Current State

### What Is Real Now

- `forge episode` can produce a shot-based mini episode from text or a book.
- `forge audiobook` can produce source and translated audiobook WAV outputs.
- `process-video` can transcribe, analyze, generate captions, overlays,
  thumbnails, and an upload-ready burned-caption video.
- `forge edit` is implemented against FLUX.1-Kontext-dev with FLUX.1-dev
  img2img fallback.
- Sarvam translation is integrated through local Ollama and does two-pass
  translation/back-translation QC inside episode/audiobook flows.
- Voice routing distinguishes English, Hindi, and Marathi fallback risk.
- Resource locks exist for `metal-heavy`, `llm`, and `tts`.
- Unit tests pass for runtime helpers, language parsing, validation, lock state,
  caption timing, and translation parsing.
- The local model substrate is ready: `forge doctor --json` reports no issues
  when allowed to reach local Ollama.

### Evidence From This Review

- `python3 -m unittest tests/test_runtime.py`: 8 tests passed.
- `python3 bin/forge.py list`: 4 visual presets and 4 voice presets available.
- `python3 bin/forge.py doctor --json`: all required tools/models ready outside
  the sandbox, including `qwen3:8b` and Sarvam.
- `python3 bin/forge.py models scan`: 289G model home, including Ollama,
  HuggingFace, BFL FLUX, and Kokoro assets.
- Tiny no-FLUX smoke test completed:
  `/private/tmp/forge-review-smoke/videos/final/episode.en.mp4`
- Smoke video has both audio and video streams and duration about 5.02 seconds.

## Gap To Vision

### Vision Contract

From `PLAN_V2.md`, Forge wants to be a local story studio where:

1. A book, excerpt, or script becomes a tight video episode.
2. Audiobook, subtitles, thumbnails, and translated editions are generated.
3. Hindi and Marathi use local Sarvam.
4. Every output is checked twice before publishable.
5. The pipeline resumes safely, reports what failed, and avoids wasting heat.

### Distance By Area

| Area | Current Readiness | Gap |
| --- | ---: | --- |
| Local model/tool substrate | 90% | Mostly ready. Need better stale-state reporting. |
| Brand/preset system | 80% | Strong data model. Needs visual bible per episode. |
| Episode generation | 65% | Works. Needs preflight, hard blockers, aligned subtitles, dashboard. |
| Translation | 65% | Two-pass Sarvam exists. Needs glossary, critic, leakage checks. |
| Narration | 55% | English good. Hindi usable. Marathi risk visible but not gated. |
| Video processing | 70% | Good pipeline. Music ducking and portrait handling are still missing. |
| QC/publishability | 35% | QC records exist, but do not yet block or guide repairs enough. |
| Resume/repair/batch | 30% | Some caching exists. No formal stage graph or repair mode. |
| Operator experience | 45% | CLI is usable. No single review dashboard yet. |

## Important Findings

### 1. The Core Episode Pipeline Works

The smoke test produced a real `episode.en.mp4`, matching audio, subtitles,
thumbnail, manifest, and QC file. This is the strongest signal: Forge is already
an end-to-end production line at small scale.

### 2. QC Is Informational, Not Decisive

`episode_qc_record()` produces useful issue lists, duration checks,
pronunciation flags, and translation pass metadata. But there is no
`qc/blockers.json`, no `--allow-qc-warnings`, and no hard stop before declaring
"complete episode ready."

This is the main alignment gap.

### 3. Subtitles Still Use Estimated Timing In `forge episode`

`timed_subtitle_rows()` divides text across target duration. It does not
re-transcribe final generated audio. That means episode subtitles can look good
syntactically while still drifting from real spoken timing.

`audiobook.py` already has a better pattern: generate subtitles by Whispering the
actual final WAV. Episode should reuse that idea.

### 4. No Review Dashboard Yet

The output tree has enough data to build `review.html`, but the file does not
exist. This forces the operator to inspect JSON, folders, audio files, and videos
manually. That is too much friction for publishable media review.

### 5. Marathi Risk Is Visible But Not Enforced

Voice routing marks Marathi fallback risk when it uses `Lekha` or a non-native
voice. That is good honesty. It should become a quality gate: publishable Marathi
requires native route or explicit manual approval.

### 6. `forge status` Can Mislead On Locks

Lock files remain after old processes exit. The command prints file contents as
if they are active locks, even when the PIDs are gone. The advisory locks
themselves are probably released correctly, but the status UI needs to distinguish
"active lock" from "stale lock file."

### 7. No-FLUX Debug Mode Has A Visual Collision

In the smoke test, no-FLUX used a title-card image as a visual, then rendered a
thumbnail overlay on top of that text. The resulting thumbnail has text on text.
This is a debug-mode artifact, but debug mode is exactly where trust is built.

## Definition Of Aligned

Forge is aligned with the V2 vision when a standard run can answer these
questions in one place:

- What did Forge make?
- Which local models and settings were used?
- Which stages were reused from cache?
- Which outputs are publishable?
- Which outputs are blocked?
- Why are they blocked?
- What exact command repairs only the failed stage?
- Where is the human approval recorded?

## Execution Plan

### Phase 0: Stabilize The Truth Layer

Goal: make current behavior honest and easy to inspect before adding more
generation power.

Deliverables:

- Add `qc/blockers.json` for episode and audiobook outputs.
- Add `--allow-qc-warnings` to let the user override warnings explicitly.
- Add a `publishable` boolean to manifest outputs per language.
- Make `forge status` identify stale lock files and stop implying they are live.
- Fix no-FLUX thumbnail text collision.

Definition of done:

- A run with Marathi fallback marks Marathi as not publishable unless manually
  approved or `--allow-qc-warnings` is provided.
- `forge status` reports active, stale, and unlocked resources separately.
- The tiny smoke test produces a clean thumbnail in no-FLUX mode.

### Phase 1: Preflight And Dry Run

Goal: fail before expensive work begins.

Deliverables:

- Implement `forge episode --check`.
- Validate input path, text length, language list, preset, voice, output
  writability, and local models.
- Estimate output tree, runtime, disk, FLUX profile, and temperature risk.
- Print a stage-by-stage plan without generating assets.

Definition of done:

- A missing book path gives a helpful next command.
- Missing Sarvam blocks Hindi/Marathi production before any TTS or FLUX work.
- `--check` exits non-zero for hard blockers and zero for ready runs.

### Phase 2: Aligned Subtitles

Goal: subtitles should match what was actually spoken.

Deliverables:

- After every final shot/segment WAV, run `mlx_whisper`.
- Generate aligned SRT/VTT into `subtitles/aligned/`.
- Compare intended script to Whisper transcript.
- Store timing and similarity in `qc/timing-report.json`.
- Use intended text with Whisper timings when similarity is high.

Definition of done:

- Episode subtitle timing is audio-derived, not estimated.
- Any low-similarity transcript becomes a blocker or manual-review item.
- A 4 x 15 second episode lands within 60 seconds +/- 1 second.

### Phase 3: Review Dashboard

Goal: one file tells the truth.

Deliverables:

- Generate `review.html` for every episode run.
- Include final videos, segment videos, audio players, scripts, translations,
  back-translations, thumbnails, subtitle previews, QC issues, and blockers.
- Add approve/reject fields as local JSON next to the dashboard.

Definition of done:

- The operator can review an episode without opening raw JSON.
- Every blocker links to the exact segment, shot, language, and artifact.
- `review.html` opens offline.

### Phase 4: Translation Studio

Goal: translation should be consistent, inspectable, and repairable.

Deliverables:

- Add glossary support.
- Add English leakage detection.
- Add placeholder/empty/repeated-line blockers.
- Add local `qwen3:8b` critic pass over Sarvam candidate A/B and
  back-translations.
- Store `qc/translation-report.json`.

Definition of done:

- Glossary terms are enforced across all segments.
- Empty placeholders are hard blockers.
- The selected translation has a recorded reason.

### Phase 5: Resume And Repair

Goal: failed runs should be repair jobs, not restarts.

Deliverables:

- Add stage hashes to manifest.
- Add `forge episode --resume`.
- Add `forge episode --only translations|audio|visuals|mux|qc`.
- Add `forge episode --repair-qc`.
- Keep failed-stage records in `qc/blockers.json`.

Definition of done:

- Killing a run midway leaves no corrupt final artifacts.
- Re-running resumes from the last good stage.
- A failed Marathi translation can be repaired without regenerating English
  visuals or video.

### Phase 6: Production Polish

Goal: make the system feel like a real studio tool.

Deliverables:

- Soft subtitle muxing and clean master video.
- Music ducking in `process-video`.
- Portrait-safe overlay/layout support.
- Per-stage runtime telemetry.
- Visual bible per episode.
- Batch mode over input folders.

Definition of done:

- Final output includes clean master and burned-caption editions.
- Dashboard shows runtime, cache reuse, and heat-heavy stage timing.
- Portrait inputs no longer get landscape overlay assumptions.

## Immediate Next Sprint

1. Fix `forge status` stale lock reporting.
2. Fix no-FLUX thumbnail text collision.
3. Add blocker aggregation and `qc/blockers.json`.
4. Add `--allow-qc-warnings` and publishable flags.
5. Add `forge episode --check`.
6. Port audio-derived subtitle alignment from audiobook flow into episode flow.
7. Generate a first simple `review.html`.

## Success Test For The Next Sprint

Run:

```sh
forge episode \
  --book ~/Documents/forge-inputs/still-water.txt \
  --title "Still Water" \
  --preset cinematic \
  --voice male_warm \
  --translate hi,mr \
  --segments 4 \
  --seconds 15 \
  --shots-per-segment 4 \
  --profile balanced \
  --out ~/Pictures/still-water-aligned/
```

Pass criteria:

- `episode.en.mp4`, `episode.hi.mp4`, and `episode.mr.mp4` exist.
- Each final video is 60 seconds +/- 1 second.
- `review.html` exists and opens offline.
- `qc/blockers.json` exists.
- `qc/timing-report.json` is generated from actual audio.
- Marathi fallback is visible and blocks publishability unless approved.
- The manifest marks each language as publishable or blocked.

## Strategic Order

Do not build more generators first. Forge already generates. Build trust,
inspection, and repair next.

The strongest path is:

1. Truth layer.
2. Preflight.
3. Aligned subtitles.
4. Dashboard.
5. Resume/repair.
6. Then add music ducking, RAG, organizer, and other expansion features.

That order keeps Forge aligned with the North Star instead of becoming a wide
set of impressive but hard-to-trust tools.
