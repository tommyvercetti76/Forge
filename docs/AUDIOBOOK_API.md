# Audiobook — public API contract

This is the contract between the audiobook subsystem (worked on by the
`audiobook-perfection` agent) and the rest of Forge (image engines,
gallery, web UI). Anything in this file is **stable** — change requires a
PR and review. Anything *not* in this file is implementation detail of
whichever side owns it.

## 1. CLI surface — must remain callable with these flag names

### 1.1 Basic audiobook (single voice → audio)

```
forge audiobook --book PATH --title TITLE --voice VOICE_ID \
                [--translate LANG_CODES] [--chunk-chars N] [--max-chunks N] \
                [--out DIR]
```

- `--book` accepts `.txt`, `.md`, `.rtf`, `.pdf`. Returns non-zero if missing/unreadable.
- `--voice` is a Kokoro voice preset id (e.g. `am_michael`) for English; the per-language Sarvam speaker is auto-picked unless overridden by env (`FORGE_SARVAM_SPEAKER`, `FORGE_SARVAM_SPEAKER_MR`, etc.).
- `--translate` is a comma list of ISO codes from `{hi, mr, bn, ta, te, gu, kn, ml, pa}`. English is always produced from the source.
- `--out` defaults to `~/Desktop/forge-test/audiobook/<title>/`.

### 1.2 ASMR audiobook (multilingual + optional video mux)

Already lives in `bin/audiobook.py` standalone. Public flags:

```
audiobook.py [--folder DIR | --rtf PATH] --out-dir DIR \
             [--video PATH] [--langs en,hi,mr] [--bed NAME] [--mode asmr|normal] \
             [--english-engine kokoro|sarvam] [--sent-pause-ms N] [--para-pause-ms N] \
             [--batch-pages N] [--page-words N] [--spoken-words N] \
             [--max-chars N] [--max-words N] [--batches N,N-N] \
             [--subtitles srt|vtt|none] [--thumbnail|--no-thumbnail] \
             [--thumb-preset NAME] [--thumb-seed N] [--thumb-frame-at SEC] \
             [--sarvam-speaker NAME] [--sarvam-speaker-mr NAME] \
             [--dry-run]
```

**Don't remove or rename any of these flags. Add new ones freely.**

## 2. Web UI surface — form actions that must keep working

These three actions in `bin/forge_web.py::specs` are the public web surface:

- `audiobook-simple` — minimal "book → en+hi+mr" flow
- `audiobook` — basic forge audiobook (advanced)
- `audiobook-asmr` — multilingual + video mux

The web form's **field names** must keep mapping to the CLI flags above:

| Form field name | Maps to CLI flag |
|---|---|
| `book` | `--book` |
| `title` | `--title` |
| `voice` | `--voice` |
| `translate` | `--translate` |
| `out` | `--out` |
| `folder` | `--folder` (ASMR) |
| `rtf` | `--rtf` |
| `video` | `--video` |
| `out_dir` | `--out-dir` |
| `langs` | `--langs` |
| `bed` | `--bed` |
| `mode` | `--mode` |
| `english_engine` | `--english-engine` |
| `sarvam_speaker` | `--sarvam-speaker` |
| `sarvam_speaker_mr` | `--sarvam-speaker-mr` |
| `sent_pause_ms` | `--sent-pause-ms` |
| `para_pause_ms` | `--para-pause-ms` |
| `batch_pages` | `--batch-pages` |
| `page_words` | `--page-words` |
| `spoken_words` | `--spoken-words` |
| `max_chars` | `--max-chars` |
| `max_words` | `--max-words` |
| `batches` | `--batches` |
| `subtitles` | `--subtitles` |
| `thumbnail` | `--thumbnail` / `--no-thumbnail` |
| `thumb_preset` | `--thumb-preset` |
| `thumb_seed` | `--thumb-seed` |
| `thumb_frame_at` | `--thumb-frame-at` |
| `dry_run` | `--dry-run` |
| `do_en` `do_hi` `do_mr` | (audiobook-simple only — checkbox UI; maps to --translate) |
| `sarvam_hi_speaker` `sarvam_mr_speaker` | (audiobook-simple only — env-var prepend) |

**You can add new fields freely.** You can't rename or remove the above without coordination.

## 3. Python API — module-level functions

Anything in `bin/audiobook.py` that today gets imported elsewhere must remain importable with the same signature.

Currently imported by `bin/forge.py::synthesize_voice_for_language`:

```python
from audiobook import tts_sarvam
audio, sample_rate = tts_sarvam(text: str, *, lang: str,
                                 speaker: str | None = None,
                                 model: str | None = None)
                                 -> tuple[np.ndarray, int]
```

Returns float32 mono audio array + integer sample rate. **Signature stable.**

If you refactor `bin/audiobook.py` into a package (`bin/audiobook/`), keep `bin/audiobook.py` as a thin re-export so `from audiobook import tts_sarvam` still works for `forge.py`. Concretely:

```python
# bin/audiobook.py  (after refactor)
from audiobook.tts.sarvam import tts_sarvam  # noqa: F401
from audiobook.pipeline import main as cli_main  # for `python audiobook.py` invocation
# ... re-export anything else forge.py imports
```

## 4. Output contract — what the rest of Forge expects

Every audiobook run must produce, at minimum, in the output directory:

```
<out_dir>/
  manifest.json                          # required, machine-readable
  audio/
    final/
      <chapter_or_chunk_id>.en.wav       # required for English
      <chapter_or_chunk_id>.hi.wav       # required if hi in --languages
      <chapter_or_chunk_id>.mr.wav       # required if mr in --languages
  subtitles/
    <chapter_or_chunk_id>.en.srt         # required (or .vtt / skipped per --subtitles)
    <chapter_or_chunk_id>.hi.srt
    <chapter_or_chunk_id>.mr.srt
  video/                                 # required if --video supplied
    <chapter_or_chunk_id>.en.mp4
    ...
```

**`manifest.json` schema** (the rest of Forge reads this — keep stable):

```json
{
  "schema_version": 1,
  "title": "Old Man and the Sea",
  "source_file": "/Users/Rohan/Desktop/Old_Man_And_Sea.rtf",
  "started_at": "2026-05-17T10:34:00Z",
  "ended_at": "2026-05-17T10:46:23Z",
  "languages": ["en", "hi", "mr"],
  "chunks": [
    {
      "id": "chapter-001",
      "source_text": "...",
      "languages": {
        "en": {
          "audio": "audio/final/chapter-001.en.wav",
          "subtitles": "subtitles/chapter-001.en.srt",
          "duration_sec": 64.3,
          "engine": "kokoro",
          "speaker": "am_michael",
          "lufs": -16.1,
          "peak_dbtp": -1.0,
          "whisper_loopback_char_accuracy": 0.997
        },
        "hi": { ... },
        "mr": { ... }
      }
    },
    ...
  ],
  "totals": {
    "duration_sec_per_lang": {"en": 4823.2, "hi": 5102.7, "mr": 5210.8},
    "chunk_count": 73,
    "whisper_loopback_mean_accuracy": {"en": 0.997, "hi": 0.952, "mr": 0.948}
  }
}
```

Adding fields to this schema is fine. **Removing or renaming a documented field is not.**

## 5. Configuration / state surface

- **Env vars** (read by audiobook code, set by user or web wizard):
  - `SARVAM_TTS_KEY` (or `~/.sarvam/key` file)
  - `FORGE_SARVAM_SPEAKER` — default speaker for all Sarvam languages
  - `FORGE_SARVAM_SPEAKER_MR` — Marathi override
  - `FORGE_SARVAM_MODEL` — defaults to `bulbul:v3`
  - `FORGE_SARVAM_PACE` `FORGE_SARVAM_SAMPLE_RATE` `FORGE_SARVAM_TEMPERATURE` — quality knobs
- **State / DB** (audiobook may add its own):
  - You may create `~/.forge/audiobook.db` or similar for telemetry / preference learning
  - Don't touch `~/.forge/gallery.db` — that's the image-side gallery

## 6. Versioning + deprecation

Treat this doc + `AUDIOBOOK_HANDOFF.md` as semver-ish:

- Patch changes (new optional fields, new optional CLI flags) — free
- Minor changes (new required behaviour that existing callers can opt into) — note in commit message + this doc's changelog
- Major changes (rename / remove / change signatures) — open PR, get review

## 7. Changelog

- **2026-05-17** — Initial API contract authored at audiobook-perfection handoff.
