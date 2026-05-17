#!/Library/Frameworks/Python.framework/Versions/3.13/bin/python3
"""audiobook — RTF → multilingual ASMR audiobook → video-mux bundle.

Pipeline:
    RTF        →  plain text       (striprtf)
    text       →  chunk plan       (sentence-aware, ~500 chars/chunk)
    per lang   →  translate        (sarvam-translate via Ollama, en source)
    per lang   →  TTS              (Kokoro for en; Parler-TTS for hi/mr)
    per chunk  →  concat WAV       (soundfile + numpy, 80ms inter-chunk gap)
    per lang   →  ASMR DSP master  (ffmpeg: slow + warm EQ + compress + loudnorm)
    per lang   →  loop video       (ffmpeg stream_loop to match audio length)
    per lang   →  mux              (ffmpeg: looped video + mastered audio → final mp4)

Outputs (under --out-dir):
    audio/book.<lang>.master.wav    mastered ASMR audio per language
    final/book.<lang>.mp4           video-muxed deliverable per language
    manifest.json                   what was produced + timings + checksums
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Optional

# Quiet the transformers/tokenizers noise BEFORE any imports trigger logging.
# These print 80+ lines of config dumps per model load otherwise. Set early so
# subprocess children inherit them too.
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from forge_runtime import (
    HF_HOME,
    MODELS_HOME,
    TRANSLATE_MODEL,
    child_env,
    language_name,
    print_ollama_token_usage,
    translate_texts_ollama,
    validate_audio,
)


# ─────────────── language config ───────────────

LANG_ENGINE = {
    "en": "kokoro",
    # Indic languages route to Sarvam Bulbul (cloud API). Set SARVAM_TTS_KEY
    # to enable. Falls back to Parler-TTS if no key is present, but Parler is
    # unreliable on long Devanagari inputs — Sarvam is the production path.
    "hi": "sarvam",
    "mr": "sarvam",
    "gu": "sarvam", "ta": "sarvam", "te": "sarvam", "kn": "sarvam",
    "ml": "sarvam", "bn": "sarvam", "pa": "sarvam",
}

# Sarvam Bulbul speakers. v3 has 30+; default to `aditya` (Hindi-strong) but
# Marathi sounds better on `manan` based on A/B listening test, so per-lang
# overrides are available.
SARVAM_SPEAKER = os.environ.get("FORGE_SARVAM_SPEAKER", "aditya")
SARVAM_SPEAKER_BY_LANG: dict[str, str] = {
    "mr": os.environ.get("FORGE_SARVAM_SPEAKER_MR", "manan"),
}
SARVAM_MODEL = os.environ.get("FORGE_SARVAM_MODEL", "bulbul:v3")
SARVAM_LANG_CODE = {
    "en": "en-IN", "hi": "hi-IN", "mr": "mr-IN", "gu": "gu-IN",
    "ta": "ta-IN", "te": "te-IN", "kn": "kn-IN", "ml": "ml-IN",
    "bn": "bn-IN", "pa": "pa-IN", "od": "od-IN",
}

# Voice descriptions for Parler-TTS. Speaker name matters — not every name in
# `Divya/Rohit/Aman/...` is wired up for every language in Indic-Parler-TTS.
# Verified working speakers (loud, audible output) per probe on this model:
#   hi: Aman (-3.7 dBFS peak), Krishna (-4.6), Aryan (-15.6)
#   mr: Aman (-1.6),           Krishna (-7.8),  Sanjay (-15.1)
# `Divya` (default in old code) produced -41 dBFS = silent for Hindi — fix.
PARLER_DESC = {
    "hi": (
        "Aman speaks in a clear, warm, well-articulated voice with a steady "
        "unhurried pace. His tone is calm and reflective with full natural "
        "presence. The recording is studio-clean with no background noise."
    ),
    "mr": (
        "Aman speaks in a clear, warm, well-articulated voice with a steady "
        "unhurried pace. His tone is calm and reflective with full natural "
        "presence. The recording is studio-clean with no background noise."
    ),
}

# Kokoro voice preset for English. bf_emma (British female) reads more like a
# proper audiobook narrator than the warmer-but-younger af_bella. Override with
# FORGE_KOKORO_EN_VOICE env var.
KOKORO_EN_VOICE_ID = os.environ.get("FORGE_KOKORO_EN_VOICE", "bf_emma")
KOKORO_EN_SPEED = float(os.environ.get("FORGE_KOKORO_EN_SPEED", "1.0"))

# Voice processing chain per mode. Two modes shipped:
#   * normal: human-like, no time-stretch, gentle EQ + compression only
#   * asmr:   slow + warm rubberband, tight LP, compressed, with bed
VOICE_CHAINS = {
    "normal": (
        "aresample=44100,"
        "highpass=f=80,"
        "acompressor=threshold=-22dB:ratio=1.5:attack=20:release=300"
    ),
    "asmr": (
        "aresample=44100,"
        "rubberband=tempo=0.88:pitch=0.96,"
        "highpass=f=70,lowpass=f=9500,"
        "acompressor=threshold=-22dB:ratio=2.0:attack=12:release=250"
    ),
}

# Procedural ambient beds. Bandpass moved OUT of voice formant range (≈300-3500 Hz)
# so the bed doesn't mask the voice. Levels chosen so bed is audibly present
# without competing — final loudnorm + amix weights keep voice in front.
BEDS = {
    "none": None,
    "radio-static": (
        # Bandpassed above core voice formants (3.5-7 kHz) + slow vibrato for shortwave feel
        "anoisesrc=color=pink:amplitude=0.18:d=3600,"
        "bandpass=f=5000:width_type=h:w=3000,"
        "vibrato=f=0.3:d=0.015,"
        "volume=-20dB"
    ),
    "vinyl-crackle": (
        # High-frequency only (6-13 kHz) — that's where actual vinyl noise sits,
        # well above voice. Tremolo gives the slow "needle drift" character.
        "anoisesrc=color=brown:amplitude=0.22:d=3600,"
        "highpass=f=6000,lowpass=f=13000,"
        "tremolo=f=0.7:d=0.05,"
        "volume=-19dB"
    ),
    "warm-hum": (
        # Low-end (60-120 Hz) tube/amp hum — sits below voice fundamentals
        "anoisesrc=color=brown:amplitude=0.25:d=3600,"
        "highpass=f=55,lowpass=f=120,"
        "volume=-24dB"
    ),
}


def build_filter_complex(bed: str, mode: str = "normal") -> str:
    """Compose the audio filter graph for one mastered output.

    `mode` picks the voice chain (normal vs asmr).
    `bed` picks the procedural ambient bed (or 'none' for voice-only).
    Voice and bed are mixed with weights=4:1 so the voice clearly dominates;
    a single final loudnorm normalizes the combined signal to -19 LUFS.
    """
    voice = VOICE_CHAINS.get(mode, VOICE_CHAINS["normal"])
    bed_src = BEDS.get(bed)
    if bed_src is None:
        return f"[0:a]{voice},loudnorm=I=-19:TP=-1.5:LRA=11[out]"
    return (
        f"[0:a]{voice}[v];"
        f"{bed_src}[bed];"
        "[v][bed]amix=inputs=2:duration=first:dropout_transition=0:weights=4 1,"
        "loudnorm=I=-19:TP=-1.5:LRA=11[out]"
    )


# ─────────────── small helpers ───────────────

def now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def cyan(s: str) -> str: return f"\033[36m{s}\033[0m"
def green(s: str) -> str: return f"\033[32m{s}\033[0m"
def red(s: str) -> str: return f"\033[31m{s}\033[0m"
def dim(s: str) -> str: return f"\033[2m{s}\033[0m"
def yellow(s: str) -> str: return f"\033[33m{s}\033[0m"


def die(msg: str) -> "None":
    sys.exit(red(f"audiobook: {msg}"))


def atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2, ensure_ascii=False))


def run(cmd: list[str], *, capture: bool = False, check: bool = True, timeout: Optional[float] = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        env=child_env(),
        capture_output=capture,
        text=capture,
        check=check,
        timeout=timeout,
    )


def _srt_timestamp(seconds: float) -> str:
    """Format a float-seconds value as SRT timestamp `HH:MM:SS,mmm`."""
    if seconds < 0:
        seconds = 0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


WHISPER_LANG = {"en": "en", "hi": "hi", "mr": "mr", "bn": "bn", "ta": "ta",
                "te": "te", "kn": "kn", "ml": "ml", "gu": "gu", "pa": "pa", "ur": "ur"}


def generate_subtitles(audio_wav: Path, srt_out: Path, *, lang: str) -> dict[str, Any]:
    """Run mlx_whisper on the mastered audio and emit a .srt sidecar.

    Why on the *generated* audio (not the source text): the audio is the ground
    truth of what plays, so subtitle timing matches the playback to the millisecond.
    Whisper-large-v3-turbo handles all Sarvam-supported Indic languages.
    """
    try:
        from mlx_whisper import transcribe  # type: ignore
    except ImportError:
        print(yellow(f"  ! mlx_whisper not installed — skipping subtitles for {lang}"))
        return {"ok": False, "reason": "mlx_whisper missing"}

    whisper_lang = WHISPER_LANG.get(lang, lang)
    t0 = time.time()
    try:
        result = transcribe(
            str(audio_wav),
            path_or_hf_repo="mlx-community/whisper-large-v3-turbo",
            language=whisper_lang,
            word_timestamps=False,  # segment-level is enough for srt
        )
    except Exception as e:
        print(yellow(f"  ! whisper failed for {lang}: {e}"))
        return {"ok": False, "reason": str(e)}
    segments = result.get("segments", [])
    if not segments:
        print(yellow(f"  ! whisper returned no segments for {lang}"))
        return {"ok": False, "reason": "no segments"}

    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        start = float(seg.get("start", 0.0))
        end = float(seg.get("end", start + 1.0))
        lines.append(str(i))
        lines.append(f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}")
        lines.append(text)
        lines.append("")
    atomic_write_text(srt_out, "\n".join(lines))
    return {
        "ok": True, "segments": len(segments),
        "wall_s": round(time.time() - t0, 1),
        "srt": str(srt_out),
    }


def derive_thumbnail_brief(text_en: str, *, model: str = "qwen3:8b", timeout: float = 60) -> dict[str, str]:
    """LLM-derive a YouTube thumbnail brief from the transcript.

    Returns {title, concept, sub}:
      - title: 2-5 word CAPS phrase, the thing on the thumbnail in big letters
      - concept: 10-15 word cinematic visual description for FLUX
      - sub: optional 4-6 word subtitle in title case
    """
    import urllib.request
    system = (
        "You write YouTube thumbnail copy. Return STRICT JSON ONLY (no prose, no "
        "explanation, no code fences). HARD CONSTRAINTS: title MUST be ≤4 words "
        "AND ≤22 characters total (every char counts). Schema: "
        '{"title": "≤4 words, ≤22 chars, CAPS, punchy",'
        '"concept": "12-word cinematic visual prompt for an image generator,'
        ' describing the most striking moment from the transcript with light/composition cues",'
        '"sub": "4-6 word title-case subtitle ≤40 chars (optional, empty string ok)"}'
    )
    prompt = f"Transcript (first 1500 chars):\n{text_en[:1500]}\n\nReturn JSON now."
    context_tokens = 4096
    body = json.dumps({
        "model": model, "system": system, "prompt": prompt, "stream": False,
        "format": "json",  # force JSON mode
        "options": {"temperature": 0.4, "num_ctx": context_tokens},
    }).encode("utf-8")
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=body, headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        payload = json.loads(resp.read())
    raw = payload.get("response", "")
    print_ollama_token_usage(
        payload,
        label="audiobook.thumbnail-brief",
        model=model,
        prompt_text=f"{system}\n{prompt}",
        completion_text=raw,
        context=context_tokens,
        temperature=0.4,
    )
    try:
        brief = json.loads(raw)
    except json.JSONDecodeError:
        # Repair attempt: find first {...}
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            die(f"LLM did not return JSON for thumbnail brief: {raw[:200]!r}")
        brief = json.loads(m.group(0))
    # Normalize
    title = str(brief.get("title", "")).strip().upper()
    # When the LLM ignores the ≤22-char rule, truncate at a word boundary AND
    # drop trailing prepositions/articles so we don't end on "SILENT KILLER OF THE".
    _TRAILING_SKIP = {"OF", "THE", "A", "AN", "IN", "ON", "AT", "FROM",
                      "WITH", "BY", "FOR", "TO", "AND", "OR", "&", "—", "-"}
    if len(title) > 26:
        words = title.split()
        kept: list[str] = []
        used = 0
        for w in words:
            extra = used + (1 if used else 0) + len(w)
            if extra > 26:
                break
            kept.append(w)
            used = extra
        while kept and kept[-1] in _TRAILING_SKIP:
            kept.pop()
        title = " ".join(kept) if kept else title[:22]
    # Also clean trailing prepositions on already-short titles (LLM sometimes
    # produces "GHOST OF THE" intentionally — clip to "GHOST" rather than
    # leaving the dangler).
    words = title.split()
    while len(words) > 1 and words[-1] in _TRAILING_SKIP:
        words.pop()
    title = " ".join(words)
    return {
        "title": title or "AUDIOBOOK",
        "concept": str(brief.get("concept", "")).strip()[:300] or "cinematic outdoor scene, dramatic lighting",
        "sub": str(brief.get("sub", "")).strip()[:50],
    }


def extract_thumbnail_frame(video_path: Path, out_png: Path, *, at_seconds: float | None = None) -> dict[str, Any]:
    """Grab a representative frame from `video_path` as the thumbnail background.

    Default: midpoint of the video. Output is 1280x720 (THUMB_W x THUMB_H),
    scaled+cropped to fit. We pick midpoint over the first frame because most
    videos open on a fade-in or a less-representative shot; the middle is
    usually a steady, content-rich moment.
    """
    duration = ffprobe_duration(video_path)
    t = at_seconds if at_seconds is not None else max(0.5, duration / 2)
    tmp = out_png.with_suffix(".tmp.png")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-ss", f"{t:.3f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
        str(tmp),
    ]
    run(cmd, timeout=60)
    if not tmp.exists() or tmp.stat().st_size < 1024:
        die(f"frame extraction failed for {video_path.name} at t={t}s")
    os.replace(tmp, out_png)
    return {"source_video": str(video_path), "frame_at_s": round(t, 2),
            "video_dur_s": round(duration, 2), "size_kb": round(out_png.stat().st_size / 1024)}


def make_thumbnails_for_batch(
    *, text_en: str, video_path: Path, langs: list[str], batch_idx: int,
    final_dir: Path, preset_id: str = "documentary", seed: int = 42,
    frame_at_seconds: float | None = None,
) -> dict[str, Any]:
    """Build per-language thumbnails from an ACTUAL VIDEO FRAME + transcript-derived title.

    Pipeline:
      1. Extract a single frame from the video → this is the shared background.
      2. LLM-derive a 2-5 word title + 4-6 word sub from the transcript.
      3. Translate title+sub to each non-English language.
      4. Per language, render preset typography over the extracted frame.

    The thumbnail PREVIEWS the actual video — it's not a FLUX-invented scene.
    Better for YouTube CTR and brand honesty.
    """
    brief = derive_thumbnail_brief(text_en)
    print(dim(f"    · brief from transcript: title={brief['title']!r}, sub={brief['sub']!r}"))
    print(dim(f"    · background: a frame from {video_path.name} (not FLUX-generated)"))

    # Translate titles + subs to other languages.
    titles = {"en": brief["title"]}
    subs = {"en": brief["sub"]}
    for lang in langs:
        if lang == "en":
            continue
        try:
            titles[lang] = translate_texts_ollama([brief["title"]], lang, model=TRANSLATE_MODEL)[0]
            if brief["sub"]:
                subs[lang] = translate_texts_ollama([brief["sub"]], lang, model=TRANSLATE_MODEL)[0]
            else:
                subs[lang] = ""
        except Exception as e:
            print(yellow(f"    ! title translate {lang!r} failed ({e}); using English"))
            titles[lang] = brief["title"]
            subs[lang] = brief["sub"]

    forge_bin = HERE / "forge.py"
    meta: dict[str, Any] = {
        "preset": preset_id, "seed": seed, "brief": brief, "langs": {},
        "background_source": "video_frame",
    }

    # Extract ONE frame from the video to serve as the shared background.
    bg_path = final_dir / f"book.batch{batch_idx:02d}.thumb-bg.png"
    frame_meta = extract_thumbnail_frame(video_path, bg_path, at_seconds=frame_at_seconds)
    meta["frame"] = frame_meta
    print(dim(f"      · frame extracted @ {frame_meta['frame_at_s']}s → {bg_path.name}"))

    # Per-language: forge thumbnail with --bg pointing at the extracted frame.
    for lang in langs:
        thumb_path = final_dir / f"book.batch{batch_idx:02d}.{lang}.thumb.png"
        cmd = [
            str(forge_bin), "thumbnail",
            "--preset", preset_id,
            "--concept", "(reusing extracted video frame, concept unused)",
            "--bg", str(bg_path),
            "--headline", titles[lang],
            "--sub", subs.get(lang, ""),
            "--seed", str(seed),
            "--out", str(thumb_path),
        ]
        print(dim(f"    · thumbnail [{lang}] → {thumb_path.name}"))
        rc = subprocess.run(cmd, env=child_env())
        if rc.returncode != 0:
            print(red(f"    ! thumbnail failed for {lang} (rc={rc.returncode})"))
            meta["langs"][lang] = {"ok": False, "rc": rc.returncode}
            continue
        meta["langs"][lang] = {"ok": True, "path": str(thumb_path)}

    return meta


def ffprobe_duration(path: Path) -> float:
    cp = run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture=True,
    )
    return float(cp.stdout.strip())


# ─────────────── RTF parsing + chunking ───────────────

def parse_rtf(rtf_path: Path) -> str:
    """Read RTF / plain text / PDF → clean plain text.

    Auto-detects format by suffix and content:
      - .pdf  → extracted via pypdf
      - .rtf  (or any file starting with `{\\rtf`) → striprtf
      - everything else → UTF-8 plain text

    Function name is historical — accepts more than just RTF now.
    """
    suffix = rtf_path.suffix.lower()
    if suffix == ".pdf":
        try:
            import pypdf  # type: ignore
        except ImportError:
            raise RuntimeError(
                "PDF input needs pypdf. Install with: pip install pypdf"
            )
        reader = pypdf.PdfReader(str(rtf_path))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
    else:
        raw = rtf_path.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".rtf" or raw.lstrip().startswith("{\\rtf"):
            from striprtf.striprtf import rtf_to_text
            text = rtf_to_text(raw)
        else:
            text = raw
    # Normalize whitespace; preserve paragraph breaks.
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# Glob patterns for folder mode — transcript first, then video.
TRANSCRIPT_EXTS = (".rtf", ".txt", ".md", ".pdf")
VIDEO_EXTS = (".mp4", ".mov", ".m4v", ".webm")


def find_inputs_in_folder(folder: Path) -> tuple[Path, Path]:
    """Auto-detect transcript + base video inside a folder.

    Picks the first transcript-like and first video-like file alphabetically.
    Errors loudly if either is missing or ambiguous (so the user fixes the
    folder layout instead of getting a surprising output).
    """
    folder = folder.expanduser().resolve()
    if not folder.is_dir():
        die(f"--folder is not a directory: {folder}")
    transcripts = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in TRANSCRIPT_EXTS
        and not p.name.startswith(".")
        and not p.stem.endswith((".en", ".hi", ".mr", ".gu", ".ta", ".te", ".kn", ".ml", ".bn", ".pa", ".ur"))
    )
    videos = sorted(
        p for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS and not p.name.startswith(".")
    )
    if not transcripts:
        die(f"no transcript file (.rtf/.txt/.md) found in {folder}")
    if not videos:
        die(f"no video file (.mp4/.mov/.m4v/.webm) found in {folder}")
    if len(transcripts) > 1:
        names = ", ".join(p.name for p in transcripts)
        print(yellow(f"  ! multiple transcripts found ({names}); using {transcripts[0].name}"))
    if len(videos) > 1:
        names = ", ".join(p.name for p in videos)
        print(yellow(f"  ! multiple videos found ({names}); using {videos[0].name}"))
    return transcripts[0], videos[0]


# Estimated speech rate AFTER the rubberband 0.88 slowdown. Calibrated against
# our Kokoro+Parler output: ~110 WPM end-to-end.
ASMR_WORDS_PER_MINUTE = 110


def advise_length(words: int, video_seconds: float, target_words: int | None = None) -> dict[str, Any]:
    """Compare the transcript's spoken-words count against the base video length.

    Returns a dict so callers can print or store; emits a verdict string a human
    can act on without doing the math.
    """
    if words <= 0 or video_seconds <= 0:
        return {"verdict": "unknown", "audio_est_s": 0, "ratio": 0}
    audio_est_s = (words / ASMR_WORDS_PER_MINUTE) * 60.0
    ratio = audio_est_s / video_seconds
    if ratio < 0.5:
        verdict = "too_short"
        action = (f"audio ≈ {audio_est_s:.0f}s but video is {video_seconds:.0f}s — "
                  f"video will be mostly silent at the end. Add more transcript or use a shorter video.")
    elif ratio < 0.9:
        verdict = "short_ok"
        action = (f"audio ≈ {audio_est_s:.0f}s vs video {video_seconds:.0f}s — "
                  f"last ~{video_seconds - audio_est_s:.0f}s of video plays silent. Acceptable.")
    elif ratio <= 1.15:
        verdict = "just_right"
        action = f"audio ≈ {audio_est_s:.0f}s, video {video_seconds:.0f}s — well-matched."
    elif ratio <= 2.0:
        verdict = "long"
        loops = ratio
        action = (f"audio ≈ {audio_est_s:.0f}s vs video {video_seconds:.0f}s — "
                  f"video will loop ~{loops:.1f}× under the audio.")
    else:
        verdict = "too_long"
        action = (f"audio ≈ {audio_est_s:.0f}s vs video only {video_seconds:.0f}s — "
                  f"transcript far too long for a {video_seconds:.0f}s video. "
                  f"Trim to ~{int(video_seconds * ASMR_WORDS_PER_MINUTE / 60)} words "
                  f"with --max-words, or use a longer source video.")
    return {
        "verdict": verdict, "action": action,
        "words": words, "audio_est_s": round(audio_est_s, 1),
        "video_s": round(video_seconds, 1), "ratio": round(ratio, 2),
        "wpm_assumption": ASMR_WORDS_PER_MINUTE,
    }


def chunk_text(text: str, *, max_chars: int = 500) -> list[str]:
    """Sentence-aware chunking. Mirrors forge.py:_synthesize_kokoro chunking
    logic so chunks stay under the TTS engine's attention budget without
    breaking sentences mid-clause."""
    sentences = re.split(r"(?<=[.!?।])\s+", text)
    chunks: list[str] = []
    buf = ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(buf) + len(s) + 1 > max_chars and buf:
            chunks.append(buf)
            buf = s
        else:
            buf = f"{buf} {s}".strip()
    if buf:
        chunks.append(buf)
    return chunks


def word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def normalize_for_tts(text: str) -> str:
    """Clean up text so the TTS engines pronounce it naturally.

    - Em/en-dashes become commas (creates a short pause; TTS engines stumble on
      raw '—').
    - Ellipses become periods (longer pause; full sentence break).
    - Smart quotes become straight quotes (Kokoro mispronounces curly ones).
    - Multiple newlines collapse to '\\n\\n' so paragraph detection still works.
    """
    text = text.replace("—", ", ").replace("–", ", ")
    text = text.replace("…", ". ").replace("...", ". ")
    text = text.replace("“", '"').replace("”", '"')  # smart double-quotes
    text = text.replace("‘", "'").replace("’", "'")  # smart single-quotes
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_for_prosody(text: str) -> list[list[str]]:
    """Split into paragraphs, each a list of sentences. Devanagari `।`
    counts as a sentence terminator alongside Latin `.!?`.

    The shape (paragraphs × sentences) lets us put a longer silence between
    paragraphs and a shorter one between sentences — which is what reads as
    natural ASMR breath cadence.
    """
    text = normalize_for_tts(text)
    paragraphs = re.split(r"\n{2,}", text)
    out: list[list[str]] = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        sents = [s.strip() for s in re.split(r"(?<=[.!?।])\s+", p) if s.strip()]
        out.append(sents or [p])
    return out


def plan_synth_units(text: str, *, max_chars: int = 260) -> list[dict[str, Any]]:
    """Group sentences into paragraph-sized synthesis units, ~max_chars each.

    Why: single-sentence Parler calls produce ~30 boundaries per minute, each
    a chance for the model to emit a noise-burst token or extra silence padding.
    Grouping into ~3-second units lets the model plan prosody across multiple
    sentences and cuts the boundary count ~5x.

    Returns a flat list of {text, is_paragraph_start, is_chunk_break} dicts so
    the synth loop can insert the right size of inter-unit silence.
    """
    paragraphs = split_for_prosody(text)
    units: list[dict[str, Any]] = []
    for pi, sentences in enumerate(paragraphs):
        first_in_para = True
        buf = ""
        for s in sentences:
            # If adding this sentence would exceed the cap, flush the buffer first.
            if buf and len(buf) + len(s) + 1 > max_chars:
                units.append({"text": buf, "is_paragraph_start": first_in_para})
                first_in_para = False
                buf = s
            else:
                buf = f"{buf} {s}".strip() if buf else s
        if buf:
            units.append({"text": buf, "is_paragraph_start": first_in_para})
    return units


def trim_edge_silence(audio: Any, sr: int, *, threshold_db: float = -45.0,
                       keep_pad_ms: float = 30.0) -> Any:
    """Trim leading + trailing silence from a TTS chunk.

    Parler emits 100-400 ms of dead air at the start AND end of each generation,
    plus occasional first/last-token noise bursts. Trimming kills both. The
    `keep_pad_ms` margin preserves a tiny breath so concatenation doesn't sound
    surgically dry.
    """
    import numpy as np
    if audio.size == 0:
        return audio
    # Frame-wise RMS in dB
    win = max(1, int(sr * 0.020))  # 20 ms window
    n_frames = audio.size // win
    if n_frames < 2:
        return audio
    frames = audio[: n_frames * win].reshape(n_frames, win).astype(np.float32)
    rms = np.sqrt(np.mean(frames ** 2, axis=1) + 1e-12)
    db = 20.0 * np.log10(rms + 1e-12)
    voiced = db > threshold_db
    if not voiced.any():
        return audio  # all silent — return as-is rather than zero-length
    first = int(max(0, voiced.argmax() * win - sr * keep_pad_ms / 1000.0))
    last = int(min(audio.size, (len(voiced) - voiced[::-1].argmax()) * win + sr * keep_pad_ms / 1000.0))
    return audio[first:last]


# ─────────────── TTS engines ───────────────

_PARLER_CACHE: dict[str, Any] = {}


def _parler_load() -> dict[str, Any]:
    """Lazy-load Parler-TTS model and tokenizers. Cached across calls."""
    if _PARLER_CACHE:
        return _PARLER_CACHE
    # Quiet HF before any sub-config printout fires
    try:
        from transformers.utils import logging as hf_logging  # type: ignore
        hf_logging.set_verbosity_error()
    except Exception:
        pass
    import torch
    from parler_tts import ParlerTTSForConditionalGeneration
    from transformers import AutoTokenizer

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    dtype = torch.float32  # Parler is finicky on MPS at fp16; fp32 is the safe default
    repo = "ai4bharat/indic-parler-tts"

    print(dim(f"  · loading parler-tts on {device} ({dtype})…"))
    t0 = time.time()
    model = ParlerTTSForConditionalGeneration.from_pretrained(repo, torch_dtype=dtype).to(device)
    tokenizer = AutoTokenizer.from_pretrained(repo)
    desc_tokenizer = AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path)
    print(dim(f"  · loaded in {time.time()-t0:.1f}s | sampling_rate={model.config.sampling_rate}"))

    _PARLER_CACHE.update(
        model=model,
        tokenizer=tokenizer,
        desc_tokenizer=desc_tokenizer,
        device=device,
        sample_rate=model.config.sampling_rate,
    )
    return _PARLER_CACHE


def tts_parler(text: str, *, lang: str, description: str | None = None) -> tuple[Any, int]:
    """Generate one chunk of audio via Parler-TTS. Returns (np.float32 array, sample_rate).

    Decoding strategy is language-dependent because Indic-Parler-TTS behaves
    differently on different scripts:
      * English+Latin → greedy (do_sample=False) — fast, deterministic, EOS-reliable
      * Devanagari   → sampling (do_sample=True, temp 0.7) — greedy gets stuck in
        degenerate "produce silence padding" states on certain Devanagari inputs;
        sampling escapes them and reliably completes the text.
    """
    import numpy as np
    import torch

    cache = _parler_load()
    desc = description or PARLER_DESC.get(lang)
    if not desc:
        die(f"no Parler voice description for lang={lang!r}")

    desc_tok = cache["desc_tokenizer"](desc, return_tensors="pt")
    prompt_tok = cache["tokenizer"](text, return_tensors="pt")
    input_ids = desc_tok.input_ids.to(cache["device"])
    prompt_input_ids = prompt_tok.input_ids.to(cache["device"])
    # Explicit attention masks — without these, Parler's pad==EOS quirk causes
    # the decoder to terminate immediately on certain inputs (Hindi especially),
    # producing near-silent output. The model's own warning flagged it.
    attention_mask = desc_tok.attention_mask.to(cache["device"])
    prompt_attention_mask = prompt_tok.attention_mask.to(cache["device"])

    # Language-aware decoding settings — Devanagari needs sampling + a generous
    # token budget; greedy can stall mid-utterance and emit silence padding.
    has_devanagari = bool(re.search(r"[ऀ-ॿ]", text))
    if has_devanagari:
        # Generous cap (4 tok/char + 200) so the model never truncates mid-speech,
        # plus sampling so it doesn't lock into a degenerate silence state.
        max_new_tokens = min(1500, max(400, int(len(text) * 4) + 200))
        gen_kwargs = dict(do_sample=True, temperature=0.7, top_k=50)
    else:
        # Latin/English: greedy is fine. Conservative cap (6 tok/char + 200).
        max_new_tokens = min(2048, max(400, int(len(text) * 6) + 200))
        gen_kwargs = dict(do_sample=False)

    with torch.no_grad():
        generation = cache["model"].generate(
            input_ids=input_ids,
            attention_mask=attention_mask,
            prompt_input_ids=prompt_input_ids,
            prompt_attention_mask=prompt_attention_mask,
            max_new_tokens=max_new_tokens,
            **gen_kwargs,
        )
    audio = generation.cpu().to(torch.float32).numpy().squeeze()
    # Free MPS scratch buffers between sentences — prevents the slow accumulation
    # that culminates in an OOM kill after a few dozen generations.
    if hasattr(torch, "mps") and torch.backends.mps.is_available():
        with contextlib.suppress(Exception):
            torch.mps.empty_cache()
    return audio, cache["sample_rate"]


def tts_kokoro(text: str) -> tuple[Any, int]:
    """Generate one chunk via Kokoro (English ASMR). Uses Forge's existing engine."""
    from forge import _kokoro_engine  # type: ignore  # reuse existing loader
    engine = _kokoro_engine()
    samples, sr = engine.create(text, voice=KOKORO_EN_VOICE_ID, speed=KOKORO_EN_SPEED, lang="en-us")
    return samples, sr


def tts_sarvam(text: str, *, lang: str, speaker: str | None = None, model: str | None = None) -> tuple[Any, int]:
    """Call Sarvam Bulbul TTS API. Returns (np.float32 audio, sample_rate).

    Sarvam supports up to 2500 chars per call (bulbul:v3) — entire batch text
    typically fits in one call, giving best prosody continuity. Production-grade
    Indic TTS; replaces the unreliable Parler-TTS path.
    """
    import base64
    import io
    import urllib.request
    import urllib.error
    import numpy as np
    import soundfile as sf

    api_key = os.environ.get("SARVAM_TTS_KEY")
    if not api_key:
        # Auto-load from the standard credential file so the wizard works
        # without users having to set the env var on every shell.
        key_file = Path.home() / ".sarvam" / "key"
        if key_file.is_file():
            api_key = key_file.read_text().strip()
    if not api_key:
        die(
            "Sarvam API key not found.\n"
            "  Get a key at https://dashboard.sarvam.ai → API Keys, then either:\n"
            "    • echo 'sk_...' > ~/.sarvam/key && chmod 600 ~/.sarvam/key   (recommended)\n"
            "    • export SARVAM_TTS_KEY=sk_...                                (per-shell)"
        )

    lang_code = SARVAM_LANG_CODE.get(lang)
    if not lang_code:
        die(f"Sarvam does not support lang={lang!r}; map it in SARVAM_LANG_CODE or switch engines.")

    chosen_speaker = speaker or SARVAM_SPEAKER_BY_LANG.get(lang) or SARVAM_SPEAKER
    body = json.dumps({
        "text": text,
        "target_language_code": lang_code,
        "model": model or SARVAM_MODEL,
        "speaker": chosen_speaker.lower(),
        "pace": 1.0,
        "speech_sample_rate": 24000,
        "output_audio_codec": "wav",
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.sarvam.ai/text-to-speech",
        data=body,
        headers={
            "api-subscription-key": api_key,
            "Content-Type": "application/json",
        },
    )

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read())
            audios = data.get("audios") or []
            if not audios:
                raise RuntimeError(f"Sarvam returned no audio: {data}")
            audio_bytes = base64.b64decode(audios[0])
            audio, sr = sf.read(io.BytesIO(audio_bytes), dtype="float32")
            if audio.ndim > 1:  # stereo → mono
                audio = audio.mean(axis=1)
            return audio.astype(np.float32), int(sr)
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", errors="replace")
            except Exception:
                detail = ""
            last_err = RuntimeError(f"Sarvam HTTP {e.code}: {detail[:300]}")
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 * (attempt + 1))
                continue
            break  # 401/403/422 — don't retry
        except Exception as e:
            last_err = e
            time.sleep(1)
    die(f"Sarvam TTS failed after 3 attempts: {last_err}")


# ─────────────── per-lang synthesis ───────────────

def synth_language(
    text: str,
    *,
    lang: str,
    out_wav: Path,
    log_dir: Path,
    sent_pause_ms: int = 200,
    para_pause_ms: int = 500,
    unit_chars: int | None = None,
) -> dict[str, Any]:
    """Paragraph-unit synthesis with edge-trimmed Parler output.

    Per-language unit sizes (max_chars per Parler call):
      * Latin / Kokoro: 260 chars (long-form is fine)
      * Devanagari (Hindi/Marathi): 130 chars — Indic-Parler renders short inputs
        much more reliably; long inputs occasionally hit degenerate decode states
    """
    import numpy as np
    import soundfile as sf

    engine = LANG_ENGINE[lang]
    t0 = time.time()
    pieces: list[Any] = []
    sample_rate = 24000
    sent_gap = None
    para_gap = None

    if unit_chars is None:
        if engine == "sarvam":
            # Sarvam Bulbul:v3 handles up to 2500 chars in a single call. Pack
            # the entire batch text into 1-2 units for best prosody continuity.
            unit_chars = 2400
        elif engine == "parler" and re.search(r"[ऀ-ॿ]", text):
            unit_chars = 130
        else:
            unit_chars = 260
    units = plan_synth_units(text, max_chars=unit_chars)
    total = len(units)
    print(dim(f"    plan: {total} unit(s) (target ≤{unit_chars} chars/unit)"))

    unit_log = log_dir / f"units.{lang}.jsonl"
    with unit_log.open("w", encoding="utf-8") as logf:
        for idx, unit in enumerate(units, 1):
            text_unit = unit["text"]
            s0 = time.time()
            tag = "paragraph" if unit["is_paragraph_start"] else "continuation"
            print(dim(f"    [{lang}] {idx}/{total} {tag} ({len(text_unit)} chars)…"),
                  end="", flush=True)
            try:
                if engine == "kokoro":
                    audio, sr = tts_kokoro(text_unit)
                elif engine == "sarvam":
                    audio, sr = tts_sarvam(text_unit, lang=lang)
                else:
                    audio, sr = tts_parler(text_unit, lang=lang)
            except Exception as e:
                print(red(f" FAIL: {e}"))
                logf.write(json.dumps({"idx": idx, "ok": False, "err": str(e), "text": text_unit[:200]}) + "\n")
                raise
            # Trim leading + trailing silence/noise bursts (Parler especially).
            audio_pre = len(audio) / sr
            audio = trim_edge_silence(audio, sr, threshold_db=-45.0, keep_pad_ms=30.0)
            audio_post = len(audio) / sr
            sample_rate = sr
            if sent_gap is None:
                sent_gap = np.zeros(int(sr * sent_pause_ms / 1000.0), dtype=audio.dtype)
                para_gap = np.zeros(int(sr * para_pause_ms / 1000.0), dtype=audio.dtype)
            if idx > 1:
                # Bigger pause when we cross into a new paragraph.
                pieces.append(para_gap if unit["is_paragraph_start"] else sent_gap)
            pieces.append(audio)
            wall = time.time() - s0
            print(green(f" ok ({wall:.1f}s, {audio_post:.1f}s audio, trim {audio_pre-audio_post:.2f}s)"))
            logf.write(json.dumps({
                "idx": idx, "is_paragraph_start": unit["is_paragraph_start"],
                "chars": len(text_unit),
                "ok": True, "wall_s": round(wall, 2),
                "audio_s_pre_trim": round(audio_pre, 2),
                "audio_s": round(audio_post, 2),
            }) + "\n")

    full = np.concatenate(pieces) if len(pieces) > 1 else pieces[0]
    tmp = out_wav.with_suffix(".tmp.wav")
    sf.write(str(tmp), full, sample_rate, subtype="PCM_16")
    os.replace(tmp, out_wav)
    validate_audio(out_wav)

    return {
        "lang": lang,
        "engine": engine,
        "units": total,
        "unit_chars": unit_chars,
        "sent_pause_ms": sent_pause_ms,
        "para_pause_ms": para_pause_ms,
        "sample_rate": sample_rate,
        "duration_s": round(len(full) / sample_rate, 2),
        "gen_wall_s": round(time.time() - t0, 1),
    }


# ─────────────── ASMR mastering ───────────────

def master_asmr(raw_wav: Path, out_wav: Path, *, bed: str = "none", mode: str = "normal") -> None:
    """Apply voice chain + optional procedural ambient bed → 44.1k/16-bit/mono.

    `mode` selects the voice processing flavor: 'normal' (human-like, no time-stretch)
    or 'asmr' (slow + warm rubberband + tighter EQ).
    """
    tmp = out_wav.with_suffix(".tmp.wav")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(raw_wav),
        "-filter_complex", build_filter_complex(bed, mode=mode),
        "-map", "[out]",
        "-ac", "1",
        "-ar", "44100",
        "-acodec", "pcm_s16le",
        str(tmp),
    ]
    run(cmd, timeout=600)
    if not tmp.exists() or tmp.stat().st_size < 1024:
        die(f"ASMR master produced empty file for {raw_wav.name}")
    os.replace(tmp, out_wav)
    validate_audio(out_wav)


# ─────────────── video loop + mux ───────────────

def mux_video(*, video_in: Path, audio_in: Path, out_mp4: Path) -> dict[str, Any]:
    """Loop the input video to cover audio duration and mux audio onto it.
    Uses -stream_loop -1 on the video input and -shortest on output so we end
    at the audio's tail (audio is the longest stream by design)."""
    audio_dur = ffprobe_duration(audio_in)
    video_dur = ffprobe_duration(video_in)
    loops_needed = max(1, int(audio_dur // video_dur) + 1)
    tmp = out_mp4.with_suffix(".tmp.mp4")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-stream_loop", "-1", "-i", str(video_in),
        "-i", str(audio_in),
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-movflags", "+faststart",
        "-shortest",
        str(tmp),
    ]
    t0 = time.time()
    run(cmd, timeout=3600)
    if not tmp.exists() or tmp.stat().st_size < 1024:
        die(f"video mux produced empty file for {out_mp4.name}")
    os.replace(tmp, out_mp4)

    final_dur = ffprobe_duration(out_mp4)
    if abs(final_dur - audio_dur) > 0.5:
        print(yellow(f"  ! duration drift: audio={audio_dur:.2f}s output={final_dur:.2f}s"))
    return {
        "audio_dur_s": round(audio_dur, 2),
        "video_loop_seed_s": round(video_dur, 2),
        "loops_expected": loops_needed,
        "final_dur_s": round(final_dur, 2),
        "mux_wall_s": round(time.time() - t0, 1),
    }


# ─────────────── top-level orchestrator ───────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="RTF → multilingual ASMR audiobook → video-mux bundle (en/hi/mr).",
    )
    ap.add_argument("--folder", type=Path, default=None,
                    help="Auto-detect transcript + base video inside this folder, write outputs to <folder>/output/. "
                         "Supersedes --rtf/--video/--out-dir.")
    ap.add_argument("--rtf", type=Path, default=None, help="Source RTF or text transcript (alt to --folder)")
    ap.add_argument("--video", type=Path, default=None, help="Loop video — any length, any aspect")
    ap.add_argument("--out-dir", type=Path, default=None, help="Output directory")
    ap.add_argument("--langs", default="en,hi,mr", help="Comma-sep BCP47 codes; default en,hi,mr")
    ap.add_argument("--max-chars", type=int, default=500, help="Sentence-chunk char cap")
    ap.add_argument("--max-words", type=int, default=None,
                    help="Single-excerpt mode: cap source to first N words. Mutually exclusive with --batch-pages.")
    ap.add_argument("--batch-pages", type=int, default=None,
                    help="Batch mode: walk the book in N-page batches. With --page-words, default 10.")
    ap.add_argument("--page-words", type=int, default=250,
                    help="Words per page assumption for batch mode. Default 250 (standard novel).")
    ap.add_argument("--spoken-words", type=int, default=150,
                    help="Words actually spoken per batch (head of each batch). Default 150 ≈ 60s ASMR.")
    ap.add_argument("--batches", default=None,
                    help="Comma-sep batch indices to run (1-based). Default all. e.g. '1,2,3'.")
    ap.add_argument("--bed", default="vinyl-crackle", choices=list(BEDS),
                    help="Ambient bed under voice. Default vinyl-crackle.")
    ap.add_argument("--mode", default="normal", choices=list(VOICE_CHAINS),
                    help="'normal' = human-like, real-time speed. 'asmr' = slowed + warm.")
    ap.add_argument("--english-engine", default="kokoro", choices=["kokoro", "sarvam"],
                    help="English TTS: 'kokoro' (local, default) or 'sarvam' (en-IN, paid, same engine as hi/mr)")
    ap.add_argument("--subtitles", default="srt", choices=["srt", "vtt", "none"],
                    help="Emit subtitle sidecars per language via Whisper. Default srt (YouTube picks up auto).")
    ap.add_argument("--thumbnail", action="store_true", default=True,
                    help="Generate a branded thumbnail per language (default on).")
    ap.add_argument("--no-thumbnail", action="store_false", dest="thumbnail",
                    help="Skip thumbnail generation.")
    ap.add_argument("--thumb-preset", default="thumbnail-bold",
                    help="Brand preset for thumbnail typography overlay. Default 'thumbnail-bold' is tuned for video-frame overlays (big white outlined headline + dim band). Other options: documentary, cinematic, editorial, tartakovsky.")
    ap.add_argument("--thumb-seed", type=int, default=42,
                    help="(Legacy) seed, retained for compatibility. Background now comes from the video frame.")
    ap.add_argument("--thumb-frame-at", type=float, default=None,
                    help="Seconds into the video to grab the thumbnail frame from. Default: midpoint.")
    ap.add_argument("--sarvam-speaker", default=None,
                    help="Override default Sarvam speaker for hi/mr/en-Sarvam. e.g. 'manan', 'pooja'.")
    ap.add_argument("--sarvam-speaker-mr", default=None,
                    help="Override Sarvam speaker for Marathi only (when it needs a different voice than Hindi).")
    ap.add_argument("--sent-pause-ms", type=int, default=None,
                    help="Silence between sentences in ms. Default 200 (normal) / 400 (asmr).")
    ap.add_argument("--para-pause-ms", type=int, default=None,
                    help="Silence between paragraphs in ms. Default 500 (normal) / 900 (asmr).")
    ap.add_argument("--dry-run", action="store_true", help="Parse + measure only; no TTS/mux")
    args = ap.parse_args()

    # Folder mode: pull transcript from the folder, write outputs to <folder>/output/.
    # `--video` is independent — pass it whether or not you use --folder. If --video
    # is omitted in folder mode, we still try to auto-detect a video in the folder.
    # Apply CLI engine override for English.
    if args.english_engine == "sarvam":
        LANG_ENGINE["en"] = "sarvam"
    # Apply Sarvam speaker overrides (CLI > env var > default).
    global SARVAM_SPEAKER
    if args.sarvam_speaker:
        SARVAM_SPEAKER = args.sarvam_speaker

    if args.folder is not None:
        folder_resolved = args.folder.expanduser().resolve()
        if not folder_resolved.is_dir():
            die(f"--folder not a directory: {folder_resolved}")
        # Auto-detect transcript if none given.
        if args.rtf is None:
            transcripts = sorted(
                p for p in folder_resolved.iterdir()
                if p.is_file() and p.suffix.lower() in TRANSCRIPT_EXTS
                and not p.name.startswith(".")
                and not p.stem.endswith((".en", ".hi", ".mr", ".gu", ".ta", ".te", ".kn", ".ml", ".bn", ".pa", ".ur"))
            )
            if not transcripts:
                die(f"no transcript file (.rtf/.txt/.md) found in {folder_resolved} — pass --rtf explicitly")
            args.rtf = transcripts[0]
            if len(transcripts) > 1:
                print(yellow(f"  ! multiple transcripts in folder; using {args.rtf.name}"))
        # Auto-detect video if none given. --video takes precedence over folder contents.
        if args.video is None:
            videos = sorted(
                p for p in folder_resolved.iterdir()
                if p.is_file() and p.suffix.lower() in VIDEO_EXTS and not p.name.startswith(".")
            )
            if not videos:
                die(f"no video file (.mp4/.mov/.m4v/.webm) in {folder_resolved} — pass --video <path> to use one from elsewhere")
            args.video = videos[0]
            if len(videos) > 1:
                print(yellow(f"  ! multiple videos in folder; using {args.video.name}"))
        if args.out_dir is None:
            args.out_dir = folder_resolved / "output"
        print(cyan(f"▶ folder mode: {folder_resolved}"))
        print(f"  · transcript: {args.rtf.name}{'  (from folder)' if args.rtf.parent == folder_resolved else '  (from --rtf)'}")
        print(f"  · base video: {args.video}{'  (from folder)' if args.video.parent == folder_resolved else '  (from --video)'}")
        print(f"  · outputs   : {args.out_dir}")

    if args.rtf is None or args.video is None or args.out_dir is None:
        die("provide --folder DIR (with files inside), or --rtf + --video + --out-dir, or --folder + --video.")

    # Mode-aware pause defaults — overridden if the user passed --sent-pause-ms / --para-pause-ms.
    if args.sent_pause_ms is None:
        args.sent_pause_ms = 400 if args.mode == "asmr" else 200
    if args.para_pause_ms is None:
        args.para_pause_ms = 900 if args.mode == "asmr" else 500
    if not args.rtf.exists():
        die(f"--rtf not found: {args.rtf}")
    if not args.video.exists():
        die(f"--video not found: {args.video}")
    args.out_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = args.out_dir / "audio"
    final_dir = args.out_dir / "final"
    log_dir = args.out_dir / "logs"
    for d in (audio_dir, final_dir, log_dir):
        d.mkdir(parents=True, exist_ok=True)

    target_langs = [s.strip().lower() for s in args.langs.split(",") if s.strip()]
    for lang in target_langs:
        if lang not in LANG_ENGINE:
            die(f"unsupported lang: {lang} (supported: {sorted(LANG_ENGINE)})")

    # 1. Parse full book
    print(cyan(f"▶ parsing transcript: {args.rtf}"))
    full_text = parse_rtf(args.rtf)
    wc_full = word_count(full_text)
    print(f"  · full: {wc_full:,} words / {len(full_text):,} chars")

    # Length advisor — runs against the spoken-words budget, not the full transcript.
    try:
        video_seconds = ffprobe_duration(args.video)
    except Exception as e:
        die(f"could not read video duration: {e}")
    spoken_word_budget = args.max_words if args.max_words is not None else (
        args.spoken_words if args.batch_pages is not None else wc_full
    )
    advice = advise_length(min(spoken_word_budget, wc_full), video_seconds)
    print(cyan(f"\n▶ length check (≈{ASMR_WORDS_PER_MINUTE} WPM ASMR pace)"))
    print(f"  · base video : {advice['video_s']}s")
    print(f"  · spoken text: ~{advice['words']} words → est. {advice['audio_est_s']}s audio "
          f"(ratio {advice['ratio']}x)")
    badge = {
        "too_short": red("  ✗ TOO SHORT"),
        "short_ok":  yellow("  ⚠ SHORT but acceptable"),
        "just_right": green("  ✓ JUST RIGHT"),
        "long":      yellow("  ⚠ LONG — video will loop"),
        "too_long":  red("  ✗ TOO LONG"),
        "unknown":   dim("  ? unknown"),
    }[advice["verdict"]]
    print(f"{badge}  {advice['action']}")
    print()

    # 2. Decide on batches. Two modes:
    #    a. single-excerpt:  --max-words N → one batch from the head of the book
    #    b. batch:           --batch-pages N → walk the book in N-page batches
    if args.max_words is not None and args.batch_pages is not None:
        die("--max-words and --batch-pages are mutually exclusive")

    batches = build_batches(
        full_text,
        page_words=args.page_words,
        batch_pages=args.batch_pages,
        spoken_words=args.spoken_words,
        max_words_single=args.max_words,
    )
    print(f"  · batch plan: {len(batches)} batch(es), each spoken_words≤{args.spoken_words}")

    # Optional batch filtering for resumable runs / partial regens.
    if args.batches:
        keep = {int(s) for s in args.batches.split(",") if s.strip()}
        batches = [b for b in batches if b["idx"] in keep]
        print(f"  · filtered to batches: {sorted(b['idx'] for b in batches)}")

    if args.dry_run:
        manifest = {
            "rtf": str(args.rtf),
            "video": str(args.video),
            "out_dir": str(args.out_dir),
            "words_en_full": wc_full,
            "batch_plan": batches,
            "dry_run": True,
            "ts": now_iso(),
        }
        atomic_write_json(args.out_dir / "manifest.json", manifest)
        print(green(f"✓ dry-run manifest written ({len(batches)} batches): {args.out_dir / 'manifest.json'}"))
        return 0

    # 3. Run each batch × language
    manifest: dict[str, Any] = {
        "rtf": str(args.rtf),
        "video": str(args.video),
        "out_dir": str(args.out_dir),
        "words_en_full": wc_full,
        "bed": args.bed,
        "page_words": args.page_words,
        "batch_pages": args.batch_pages,
        "spoken_words": args.spoken_words,
        "langs": target_langs,
        "batches": [],
        "ts_started": now_iso(),
    }

    for batch in batches:
        bidx = batch["idx"]
        text_en = batch["text"]
        print(cyan(f"\n▶▶ batch {bidx:02d}/{len(batches):02d}  ({batch['words']} words / {batch['chars']} chars)"))
        atomic_write_text(args.out_dir / f"source.batch{bidx:02d}.en.txt", text_en + "\n")

        batch_record: dict[str, Any] = {**batch, "langs": {}}
        for lang in target_langs:
            print(cyan(f"  ▶ lang={lang} ({language_name(lang)}) via {LANG_ENGINE[lang]}"))
            t_lang = time.time()

            # Translate WHOLE batch text as one piece (preserves cross-sentence
            # context that chunk-by-chunk translation loses) — then hand the
            # full translation to the paragraph-unit synthesizer.
            if lang == "en":
                text_for_synth = text_en
            else:
                print(dim(f"    · translating whole batch ({len(text_en)} chars) → {language_name(lang)}…"))
                translated = translate_texts_ollama([text_en], lang, model=TRANSLATE_MODEL)
                text_for_synth = translated[0]
                atomic_write_text(args.out_dir / f"source.batch{bidx:02d}.{lang}.txt", text_for_synth + "\n")

            # Per-language Sarvam speaker override (Marathi often needs its own voice).
            lang_speaker = None
            if lang == "mr" and args.sarvam_speaker_mr:
                lang_speaker = args.sarvam_speaker_mr
            if lang_speaker:
                _saved = SARVAM_SPEAKER
                globals()["SARVAM_SPEAKER"] = lang_speaker
            raw_wav = audio_dir / f"book.batch{bidx:02d}.{lang}.raw.wav"
            try:
                synth_meta = synth_language(
                    text_for_synth, lang=lang, out_wav=raw_wav, log_dir=log_dir,
                    sent_pause_ms=args.sent_pause_ms, para_pause_ms=args.para_pause_ms,
                )
            finally:
                if lang_speaker:
                    globals()["SARVAM_SPEAKER"] = _saved

            print(dim(f"    · mastering (mode={args.mode}, bed={args.bed})…"))
            master_wav = audio_dir / f"book.batch{bidx:02d}.{lang}.master.wav"
            master_asmr(raw_wav, master_wav, bed=args.bed, mode=args.mode)

            # Subtitle sidecar from the mastered audio (perfect timing match).
            sub_meta: dict[str, Any] = {"ok": False}
            if args.subtitles != "none":
                print(dim(f"    · generating .{args.subtitles} subtitles via whisper…"))
                srt_path = final_dir / f"book.batch{bidx:02d}.{lang}.{args.subtitles}"
                sub_meta = generate_subtitles(master_wav, srt_path, lang=lang)
                if sub_meta.get("ok"):
                    print(green(f"      ✓ {srt_path.name} ({sub_meta['segments']} segments, {sub_meta['wall_s']}s)"))

            print(dim(f"    · muxing onto looped video…"))
            out_mp4 = final_dir / f"book.batch{bidx:02d}.{lang}.mp4"
            mux_meta = mux_video(video_in=args.video, audio_in=master_wav, out_mp4=out_mp4)

            batch_record["langs"][lang] = {
                **synth_meta,
                **mux_meta,
                "raw_wav": str(raw_wav),
                "master_wav": str(master_wav),
                "final_mp4": str(out_mp4),
                "lang_wall_s": round(time.time() - t_lang, 1),
            }
            print(green(f"    ✓ {out_mp4.name} ({mux_meta['final_dur_s']:.1f}s, {round(time.time()-t_lang,1)}s wall)"))

        # Thumbnails — extract one frame from the actual video as the shared
        # background, overlay localized title per language. The thumbnail PREVIEWS
        # the real video content (no FLUX-invented scene).
        if args.thumbnail:
            print(cyan(f"  ▶ thumbnails (preset={args.thumb_preset}, frame={args.thumb_frame_at or 'midpoint'})"))
            thumb_meta = make_thumbnails_for_batch(
                text_en=text_en, video_path=args.video, langs=target_langs,
                batch_idx=bidx, final_dir=final_dir,
                preset_id=args.thumb_preset, seed=args.thumb_seed,
                frame_at_seconds=args.thumb_frame_at,
            )
            batch_record["thumbnails"] = thumb_meta

        manifest["batches"].append(batch_record)
        # Checkpoint manifest after each batch so a crash mid-run still leaves a record.
        atomic_write_json(args.out_dir / "manifest.json", manifest)

    manifest["ts_finished"] = now_iso()
    atomic_write_json(args.out_dir / "manifest.json", manifest)
    print(green(f"\n✓ all done. {len(batches)} batches × {len(target_langs)} langs = {len(batches)*len(target_langs)} videos."))
    print(green(f"  manifest: {args.out_dir / 'manifest.json'}"))
    return 0


def build_batches(
    full_text: str,
    *,
    page_words: int,
    batch_pages: int | None,
    spoken_words: int,
    max_words_single: int | None,
) -> list[dict[str, Any]]:
    """Split the book into batches. Each batch records its spoken slice (first
    `spoken_words` words from its 10-page window) and metadata for the manifest.
    """
    words = full_text.split()
    n = len(words)

    if max_words_single is not None:
        # Single-excerpt mode: one batch, head of the book.
        spoken = " ".join(words[:max_words_single])
        spoken = _trim_to_sentence(spoken, trim_start=False)
        return [{
            "idx": 1, "kind": "single",
            "source_words_start": 0, "source_words_end": max_words_single,
            "text": spoken, "words": word_count(spoken), "chars": len(spoken),
        }]

    if batch_pages is None:
        batch_pages = 10  # default when no excerpt cap and no batch flag

    window = batch_pages * page_words
    batches: list[dict[str, Any]] = []
    for i, start in enumerate(range(0, n, window), start=1):
        end = min(start + window, n)
        spoken = " ".join(words[start : start + spoken_words])
        # First batch starts at the natural book opening — don't strip-start.
        spoken = _trim_to_sentence(spoken, trim_start=(start > 0))
        batches.append({
            "idx": i, "kind": "batch",
            "source_words_start": start, "source_words_end": end,
            "spoken_words_planned": spoken_words,
            "text": spoken, "words": word_count(spoken), "chars": len(spoken),
        })
    return batches


def _trim_to_sentence(text: str, *, trim_start: bool = True) -> str:
    """Trim text so it both starts and ends on a sentence boundary.

    `trim_start=False` for the first batch where the slice starts at the
    natural beginning of the book — there's no orphan mid-clause to skip.
    """
    if trim_start:
        m_start = re.search(r"[.!?।]\s+[A-Zऀ-ॿ\"']", text)
        if m_start:
            text = text[m_start.end() - 1:].lstrip()
    m_end = re.search(r"^(.*[.!?।])(\s|$)", text + " ", re.DOTALL)
    return (m_end.group(1) if m_end else text).rstrip()


if __name__ == "__main__":
    sys.exit(main())
