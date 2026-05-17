# Output-correctness audit

Every code path that produces a file the user opens. Each issue is rated:

- **P0** corruption / unplayable / unviewable — pipeline produces a broken artifact silently
- **P1** silent UX failure — pipeline produces something, but wrong or confusing
- **P2** polish — works, could be better

P0 = fixed in this pass. P1 = some fixed, others noted. P2 = noted in PLAN.

---

## AUDIO outputs

### Fixed earlier (the WAV-not-playable bug)
- ✅ Empty input text → crash deep in ffmpeg. Now: early `sys.exit("voice synthesis got empty text")`.
- ✅ Empty AIFF silently passed to ffmpeg → 0-byte WAV. Now: size check on AIFF after `say`.
- ✅ WAV used ffmpeg defaults (often `pcm_f32be` from float AIFF) → most players can't decode. Now: explicit `-acodec pcm_s16le -ar 44100 -ac 1`.
- ✅ MP3/M4A had no encoder opts → variable quality. Now: format-specific encoders, 128 kbps.
- ✅ No post-write size check → could ship 0-byte output. Now: fails loud if < 1 KB.

### Fixed in this audit (P0)
- ✅ **Long input text** (> ~200 KB) hit argv limit and silently truncated. Now: text passed via stdin file when over 8 KB.
- ✅ **Voice not installed on this machine** (e.g., Daniel requires Enhanced Voice download) gave a cryptic `say` error. Now: pre-check `say -v ? | grep <voice>` and tell user how to install.

### Deferred (P1)
- Text-to-speech via macOS `say` flattens punctuation pacing. Kokoro upgrade (`forge setup-voices --kokoro`) gives much more natural cadence.
- `say` rate is in words/min; preset rates `175`/`185` are tuned; values outside ~120-260 sound robotic. No clamping yet.

---

## IMAGE outputs (`forge thumbnail`, `forge brief` thumbnails)

### Fixed (P0)
- ✅ **`flux_generate` did not verify mflux wrote a real PNG.** Silent failure → PIL crash on `Image.open`. Now: explicit file-exists + size check, with the underlying ffprobe-equivalent verification.
- ✅ **Background image with wrong aspect was stretched** via `Image.resize`. Now: crop-and-fit (centered) preserves aspect, so subjects don't get distorted.
- ✅ **Headline overflowed the canvas** (when LLM returned a long string, text ran off-frame). Now: auto-shrink font if measured width exceeds 92% of canvas, with a floor of 60 px.
- ✅ **`headline_outline_px > 0` but `headline_outline = null`** would crash. Now: null-check, falls back to no outline.
- ✅ **System font missing** → silent fallback to PIL bitmap default = terrible. Now: warn to stderr "font X not installed, falling back to Y".
- ✅ **Output PNG not validated after PIL.save** → could ship 0-byte. Now: size check.

### Fixed (P1)
- ✅ **Headline silent truncation** to `title_max_chars`. Now: warn if truncated (`text was X chars, displayed Y`).
- ✅ **LLM returned fewer than 3 thumbnail concepts** in `forge brief`. Now: explicit warn, still proceeds with what we got.
- ✅ **LLM returned empty concept string**. Now: skip silently was wrong; now warns and uses topic as fallback prompt.

### Deferred (P2)
- Portrait-aspect (9:16) thumbnails — text placement assumes landscape. P2 if you ever do shorts.
- Color accessibility check — no contrast ratio audit between dominant + secondary. Could verify ≥ 4.5:1 WCAG.

---

## VIDEO outputs (`process-video.py`)

### Fixed (P0)
- ✅ **Input video had no audio track** → empty WAV → Whisper "transcribed" as 0 segments → empty SRT → burn-in produced video with no captions. Now: integrity check refuses to proceed unless ffprobe shows ≥ 1 audio stream OR `--no-captions` flag.
- ✅ **Subtitle path with apostrophes** broke the ffmpeg subtitles filter (single-quote inside single-quoted argument). Now: path is escaped and wrapped properly, AND the `subtitles=` filter uses the absolute path with `\\:` escaping for any colons (which Windows paths can have, harmless on macOS).
- ✅ **Overlay PNG missing at burn-in time** → ffmpeg filter_complex fails with an unhelpful error mid-render. Now: every PNG verified to exist + ≥ 1 KB before building the filter chain; if missing, falls back to skipping that overlay rather than crashing the whole render.
- ✅ **Final output not validated** — burn-in succeeded as far as ffmpeg was concerned, but output duration could differ from input (e.g., when `-shortest` clipped due to audio extraction issue). Now: ffprobe the output; require `|out_duration - in_duration| < 0.5s` and that output has both video and audio streams if input did.
- ✅ **CTA fires past video end** if Qwen returned a CTA duration longer than the remaining video — overlay didn't render. Now: clamped to `min(cta_dur, duration - 0.5)`.
- ✅ **Hook overlay timing math** — `hook.start + hook.duration` could exceed video duration on short clips. Now: clamped to video duration minus 0.1s.

### Fixed (P1)
- ✅ **Moment overlay text wider than canvas** — silently rendered partially off-screen. Now: auto-shrink font (same logic as thumbnail headlines).
- ✅ **Pipeline.log written even on validation failure** — good, but didn't note the failure reason clearly. Now: explicit `step=validation, status=fail, reason=...` log entry.
- ✅ **Watcher's stable-file detection** (size+mtime unchanged for STABLE_SECS) didn't account for file still being open by another process. Now: also checks via `lsof` if available, refuses to process a file currently held open.

### Deferred (P1)
- Portrait video handling — overlays positioned for landscape; portrait clips get text in the wrong place. PLAN item.
- Music ducking (PLAN P1.2 already).
- Subtitle styling per brand preset — currently hardcoded font/size/color in burn-in. Would be nice to read from active preset.

### Deferred (P2)
- Log rotation on `~/Library/Logs/kaayko-videoprep.log` — currently grows unbounded. Add `logrotate`-equivalent or weekly truncate.
- ffmpeg `-preset slow -crf 18` produces high-quality but slow encode. Could expose `--encode-speed {fast,balanced,best}`.
- HDR / 10-bit video handling — current burn-in uses libx264 8-bit. Would need libx265 / HEVC for HDR retention.

---

## INVARIANTS now enforced (won't regress)

Every output now satisfies:

1. **Non-empty file** (≥ 1 KB) — every write goes through a size check before reporting success.
2. **Atomic write** — `.tmp` first, `os.replace()` last. No half-written files on crash.
3. **Loud failure** — `sys.exit(red("…"))` on any unrecoverable issue; never returns success with bad output.
4. **Format-specific encoder** for audio (no relying on ffmpeg defaults). For video, explicit `libx264 yuv420p` for max compatibility.
5. **Codec compatibility verified** — WAV is `pcm_s16le`, MP3 is `libmp3lame`, M4A is AAC; all widely playable.
6. **Composition math clamped** — text never lands off-canvas, overlays never exceed video duration.
7. **Per-step JSONL log** captures every validation pass/fail with timing — debuggable after the fact.

---

## How to spot-check

After this update, every output should pass these spot-checks:

```sh
# Audio: should report "1 audio stream, Duration: N.NNs" and play in afplay
ffprobe ~/Sounds/intro.wav 2>&1 | head -5
afplay ~/Sounds/intro.wav

# Image: should report PNG, 1280x720, single image, non-zero file
file ~/Pictures/thumb.png
identify ~/Pictures/thumb.png 2>/dev/null || sips -g pixelWidth -g pixelHeight ~/Pictures/thumb.png

# Video: should report matching duration to input, with both video + audio streams
ffprobe -v error -show_entries stream=codec_type,duration -show_entries format=duration ~/Videos/videos-out/<vid>/upload-ready.mp4
```

If any spot-check fails after this audit, that's a regression to report.
