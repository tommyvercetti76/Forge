#!/usr/bin/env python3
"""process-video.py v2 — offline-first, production-grade upload prep.

Architectural fixes over v1:
  1. `warmup` subcommand — pre-downloads every model and writes ~/.kaayko-pipeline/ready
     so a field run never tries to fetch a model when offline.
  2. Health check at start of every run — refuses unless warmup succeeded
     (override with --offline-skip-check if you know what you're doing).
  3. Ollama probe with MLX-LLM fallback — if Ollama dies or isn't running, the
     analyze step transparently uses local mlx_lm.generate against a Qwen MLX
     model instead. Pipeline still works.
  4. LLM output schema-validated with up to 3 retries (increasing temperature)
     before falling back to deterministic templates. No silent dict-shape bugs.
  5. Audio denoise (ffmpeg afftdn) before transcription. Wind/engine noise
     becomes a much smaller transcription liability.
  6. Hook overlay anchored to first detected speech word (from Whisper word
     timestamps), not always 0:00.
  7. Overlay duration = max(3.0, len(text) / 15 + 1.0) — reading-time-aware.
  8. CTA duration scales with video length (5% of video, clamped [2, 6]).
  9. Stable-file detection coordinated with watcher (see watch-folder.sh).
 10. Atomic outputs — every write goes through .tmp + rename.
 11. Structured per-video JSONL log at videos-out/<stem>/pipeline.log.
 12. Manifest carries SCHEMA_VERSION so future readers can refuse old versions.
 13. Video integrity preflight (ffprobe video stream + duration).
 14. Sentence-aligned moments — Qwen picks from numbered sentence list with
     start_sec, not free-text guess.
 15. Per-segment confidence flagging — low-confidence Whisper segments saved
     to transcript/low-confidence.json for human review.

Usage:
    # ONLINE, once: pre-cache all models + verify deps
    python3 process-video.py warmup

    # Process any single video (works offline once warmup is done)
    python3 process-video.py process path/to/video.mp4

    # Quality presets
    python3 process-video.py process video.mp4 --quality best   # large-v3 + FLUX-dev 25-step
    python3 process-video.py process video.mp4 --quality fast   # turbo + schnell 4-step
    python3 process-video.py process video.mp4 --quality cool   # alias for less heat
    python3 process-video.py process video.mp4 --quality max    # alias for highest local quality

    # Useful flags
    --noisy           force aggressive audio denoise (driving / wind / engine)
    --captions en,mr  emit per-language SRT/VTT/TXT via local Ollama translation
    --no-burn         assets only, no burned upload-ready.mp4
    --no-thumbs       skip FLUX (if FLUX not warmed up)
    --force           redo cached steps
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import hashlib
import json
import os
import re
import shlex
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from forge_runtime import (
    JobStore,
    ResourceLock,
    TRANSLATE_MODEL,
    child_env,
    ffmpeg_filter_escape,
    hf_cache_root,
    language_name,
    parse_language_codes,
    print_ollama_token_usage,
    print_token_usage,
    translate_texts_ollama,
    validate_audio,
    validate_png,
    validate_video,
)

# ────────────────── constants ──────────────────

SCHEMA_VERSION = 2
PIPELINE_HOME = Path.home() / ".kaayko-pipeline"
READY_MARKER = PIPELINE_HOME / "ready.json"

OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = "qwen3:8b"
MLX_FALLBACK_MODEL = "mlx-community/Qwen2.5-Coder-32B-Instruct-4bit"

WHISPER_TURBO = "mlx-community/whisper-large-v3-turbo"
WHISPER_BEST = "mlx-community/whisper-large-v3-mlx"
FLUX_SCHNELL = "schnell"
FLUX_DEV = "dev"

QUALITY_PRESETS = {
    "fast": {"whisper": WHISPER_TURBO, "flux": FLUX_SCHNELL, "flux_steps": 4},
    "good": {"whisper": WHISPER_TURBO, "flux": FLUX_DEV, "flux_steps": 18},
    "best": {"whisper": WHISPER_BEST, "flux": FLUX_DEV, "flux_steps": 25},
    "cool": {"whisper": WHISPER_TURBO, "flux": FLUX_SCHNELL, "flux_steps": 4},
    "balanced": {"whisper": WHISPER_TURBO, "flux": FLUX_DEV, "flux_steps": 18},
    "max": {"whisper": WHISPER_BEST, "flux": FLUX_DEV, "flux_steps": 25},
}

THUMB_W, THUMB_H = 1280, 720
LOW_CONF_THRESHOLD = -0.6  # avg_logprob, more negative = less confident
DEFAULT_SUBPROCESS_TIMEOUT_SEC = float(os.environ.get("PROCESS_VIDEO_SUBPROCESS_TIMEOUT_SEC", "3600"))
SHORT_SUBPROCESS_TIMEOUT_SEC = float(os.environ.get("PROCESS_VIDEO_SHORT_TIMEOUT_SEC", "60"))
CAPTION_LANGS_ENV = "LANGUAGES"
FORGE_CAPTION_LANGS_ENV = "FORGE_CAPTION_LANGS"

_TMP_PATHS: set[Path] = set()
_CHILD_PROCS: set[subprocess.Popen] = set()
_RUNTIME_GUARDS_INSTALLED = False


# ────────────────── small utilities ──────────────────


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _cmd_display(cmd: list[str]) -> str:
    parts = [str(p) for p in cmd]
    for i, part in enumerate(parts[:-1]):
        if part in {"--prompt"}:
            parts[i + 1] = "<prompt>"
    return " ".join(shlex.quote(p if len(p) <= 120 else p[:117] + "...") for p in parts)


def _register_tmp(path: Path) -> Path:
    path = path.resolve()
    _TMP_PATHS.add(path)
    if path.exists():
        path.unlink()
    return path


def _discard_tmp(path: Path) -> None:
    _TMP_PATHS.discard(path.resolve())


def _cleanup_tmp_paths() -> None:
    for path in list(_TMP_PATHS):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
        finally:
            _TMP_PATHS.discard(path)


def _terminate_proc(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _terminate_children() -> None:
    for proc in list(_CHILD_PROCS):
        _terminate_proc(proc)
        _CHILD_PROCS.discard(proc)


def _handle_shutdown(_signum, _frame) -> None:
    _terminate_children()
    _cleanup_tmp_paths()
    raise KeyboardInterrupt


def install_runtime_guards() -> None:
    global _RUNTIME_GUARDS_INSTALLED
    if _RUNTIME_GUARDS_INSTALLED:
        return
    atexit.register(_cleanup_tmp_paths)
    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)
    _RUNTIME_GUARDS_INSTALLED = True


def run_subprocess(
    cmd: list[str],
    *,
    timeout: Optional[float] = DEFAULT_SUBPROCESS_TIMEOUT_SEC,
    capture_output: bool = False,
    text: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess:
    display = _cmd_display(cmd)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        text=text,
        env=child_env(),
    )
    _CHILD_PROCS.add(proc)
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_proc(proc)
        raise subprocess.TimeoutExpired(display, timeout)
    finally:
        _CHILD_PROCS.discard(proc)
    if check and proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, display, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(display, proc.returncode, stdout, stderr)


def shell(cmd: list[str], capture: bool = False, timeout: Optional[float] = None) -> str:
    timeout = DEFAULT_SUBPROCESS_TIMEOUT_SEC if timeout is None else timeout
    if capture:
        return run_subprocess(cmd, check=True, capture_output=True, text=True, timeout=timeout).stdout
    run_subprocess(cmd, check=True, timeout=timeout)
    return ""


def shell_ok(cmd: list[str], timeout: Optional[float] = None) -> bool:
    try:
        timeout = SHORT_SUBPROCESS_TIMEOUT_SEC if timeout is None else timeout
        run_subprocess(cmd, check=True, capture_output=True, timeout=timeout)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _register_tmp(path.with_suffix(path.suffix + ".tmp"))
    try:
        tmp.write_bytes(data)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
        _discard_tmp(tmp)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, obj: Any) -> None:
    atomic_write_text(path, json.dumps(obj, indent=2))


def sha16(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def file_sha16(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


# ────────────────── structured logger ──────────────────


class StepLog:
    def __init__(self, log_path: Path):
        self.path = log_path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("")

    def append(self, **kwargs: Any) -> None:
        rec = {"ts": now_iso(), **kwargs}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    @contextlib.contextmanager
    def step(self, name: str, **meta: Any):
        t0 = time.monotonic()
        self.append(step=name, status="start", **meta)
        try:
            yield
        except Exception as e:
            self.append(step=name, status="error", error=str(e), seconds=round(time.monotonic() - t0, 2))
            raise
        else:
            self.append(step=name, status="ok", seconds=round(time.monotonic() - t0, 2))


# ────────────────── warmup ──────────────────


@dataclass
class WarmupReport:
    online: bool
    ffmpeg: bool
    ffprobe: bool
    mlx_whisper: bool
    mflux: bool
    pillow: bool
    ollama: bool
    ollama_model_present: bool
    whisper_cached: bool
    flux_cached: bool
    issues: list[str]

    def is_ready(self) -> bool:
        return not self.issues


def check_online(host: str = "huggingface.co", timeout: float = 3.0) -> bool:
    try:
        socket.create_connection((host, 443), timeout=timeout).close()
        return True
    except OSError:
        return False


def check_ollama() -> tuple[bool, bool]:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=3) as r:
            tags = json.loads(r.read().decode("utf-8"))
        names = {m.get("name", "").split(":")[0] for m in tags.get("models", [])}
        family = OLLAMA_MODEL.split(":")[0]
        return True, family in names
    except (OSError, ValueError):
        return False, False


def hf_model_cached(repo: str) -> bool:
    """Return True if every safetensors/bin shard for `repo` is present locally."""
    repo_dir = hf_cache_root() / f"models--{repo.replace('/', '--')}"
    snapshots = repo_dir / "snapshots"
    if not snapshots.exists():
        return False
    for snapshot in snapshots.iterdir():
        weights = list(snapshot.rglob("*.safetensors")) + list(snapshot.rglob("*.bin")) + list(snapshot.rglob("*.npz"))
        if not weights:
            continue
        # Confirm each weight file points at a real blob (HF uses symlinks).
        if all(p.exists() and p.stat().st_size > 1024 for p in weights):
            return True
    return False


def cmd_warmup(args: argparse.Namespace) -> int:
    """Pre-download every model, verify every dependency, write ready marker."""
    PIPELINE_HOME.mkdir(parents=True, exist_ok=True)
    issues: list[str] = []

    print("== Pipeline warmup ==")
    online = check_online()
    print(f"  online?              {'yes' if online else 'NO — limited warmup possible'}")

    ffmpeg = shell_ok(["ffmpeg", "-version"])
    print(f"  ffmpeg               {'✓' if ffmpeg else '✗ (install from evermeet.cx)'}")
    if not ffmpeg:
        issues.append("ffmpeg not found")

    ffprobe = shell_ok(["ffprobe", "-version"])
    print(f"  ffprobe              {'✓' if ffprobe else '✗ (install ffprobe alongside ffmpeg)'}")
    if not ffprobe:
        issues.append("ffprobe not found")

    mlx_whisper = shutil.which("mlx_whisper") is not None
    print(f"  mlx_whisper          {'✓' if mlx_whisper else '✗ (uv tool install mlx-whisper)'}")
    if not mlx_whisper:
        issues.append("mlx_whisper not found")

    mflux = shutil.which("mflux-generate") is not None
    print(f"  mflux-generate       {'✓' if mflux else '✗ (uv tool install mflux)'}")
    if not mflux:
        issues.append("mflux-generate not found")

    pillow = shell_ok([sys.executable, "-c", "import PIL"])
    print(f"  Pillow               {'✓' if pillow else '✗ (pip install pillow --break-system-packages)'}")
    if not pillow:
        issues.append("Pillow not installed")

    ollama_up, ollama_has = check_ollama()
    print(f"  Ollama running       {'✓' if ollama_up else '✗ (open Ollama.app)'}")
    print(f"  Ollama has {OLLAMA_MODEL:11s} {'✓' if ollama_has else '✗ (ollama pull ' + OLLAMA_MODEL + ')'}")

    if ollama_up and not ollama_has:
        if online and not args.dry_run:
            print(f"  → pulling {OLLAMA_MODEL} …")
            shell(["ollama", "pull", OLLAMA_MODEL])
            ollama_has = True

    # Whisper cache
    whisper_repo = WHISPER_BEST if args.quality in ("best", "max") else WHISPER_TURBO
    whisper_cached = hf_model_cached(whisper_repo)
    print(f"  Whisper cached       {'✓' if whisper_cached else '✗'} ({whisper_repo})")
    if not whisper_cached and online and not args.dry_run:
        print(f"  → pre-downloading {whisper_repo} (one-time, ~1.5 GB) …")
        shell(["hf", "download", whisper_repo])
        whisper_cached = True

    # FLUX cache (uses HF cache regardless of mflux model alias)
    flux_repo = "black-forest-labs/FLUX.1-schnell" if args.quality in ("fast", "cool") else "black-forest-labs/FLUX.1-dev"
    flux_cached = hf_model_cached(flux_repo)
    print(f"  FLUX cached          {'✓' if flux_cached else '✗'} ({flux_repo})")
    if not flux_cached and online and not args.dry_run:
        print(f"  → pre-downloading {flux_repo} (one-time, 6-24 GB) …")
        shell(["hf", "download", flux_repo])
        flux_cached = True

    # MLX-LLM fallback weights
    mlx_fallback_cached = hf_model_cached(MLX_FALLBACK_MODEL)
    print(f"  MLX-LLM fallback     {'✓' if mlx_fallback_cached else '✗'} ({MLX_FALLBACK_MODEL})")
    if not mlx_fallback_cached:
        # Not fatal — only needed if Ollama goes down
        print("    (only needed if Ollama is unavailable; skipping auto-pull)")

    if not (ffmpeg and ffprobe):
        issues.append("ffmpeg/ffprobe missing")
    if not (mlx_whisper and pillow):
        issues.append("missing tooling")
    if not (whisper_cached and flux_cached):
        issues.append("models not cached")
    if not (ollama_up and ollama_has) and not mlx_fallback_cached:
        issues.append("neither Ollama nor MLX-LLM fallback is ready for analyze step")

    report = WarmupReport(
        online=online,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        mlx_whisper=mlx_whisper,
        mflux=mflux,
        pillow=pillow,
        ollama=ollama_up,
        ollama_model_present=ollama_has,
        whisper_cached=whisper_cached,
        flux_cached=flux_cached,
        issues=issues,
    )

    payload = {
        "warmup_at": now_iso(),
        "schema_version": SCHEMA_VERSION,
        "quality": args.quality,
        "ok": report.is_ready(),
        "report": report.__dict__,
    }
    atomic_write_json(READY_MARKER, payload)

    print()
    if report.is_ready():
        print(f"✓ Ready — marker at {READY_MARKER}")
        return 0
    print(f"✗ Issues: {', '.join(issues)}")
    print(f"  Marker still written so you can inspect: {READY_MARKER}")
    return 1


def assert_ready(skip_check: bool) -> dict:
    if skip_check:
        return {"warmup_at": "skipped", "ok": True}
    if not READY_MARKER.exists():
        sys.exit(
            "ERROR: pipeline never warmed up. Run `python3 process-video.py warmup` "
            "while online before processing in the field."
        )
    payload = json.loads(READY_MARKER.read_text())
    if not payload.get("ok"):
        sys.exit(
            f"ERROR: warmup marked NOT ready (issues: {payload.get('report', {}).get('issues')}). "
            "Re-run warmup or pass --offline-skip-check to override."
        )
    return payload


# ────────────────── LLM client (Ollama + MLX fallback) ──────────────────


def call_ollama_json(system: str, user: str, *, temperature: float, timeout: float = 120) -> Any:
    context_tokens = 8192
    body = json.dumps(
        {
            "model": OLLAMA_MODEL,
            "system": system,
            "prompt": user,
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature, "num_ctx": context_tokens},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode("utf-8"))
    raw = resp.get("response", "")
    print_ollama_token_usage(
        resp,
        label="process-video.llm-json",
        model=OLLAMA_MODEL,
        prompt_text=f"{system}\n{user}",
        completion_text=raw,
        context=context_tokens,
        temperature=temperature,
    )
    return _extract_json(raw)


def call_mlx_json(system: str, user: str, *, temperature: float) -> Any:
    """Fallback: run a one-shot via mlx_lm.generate as a subprocess. Slower than Ollama."""
    prompt = f"<|im_start|>system\n{system}\n<|im_end|>\n<|im_start|>user\n{user}\n<|im_end|>\n<|im_start|>assistant\n"
    raw = run_subprocess(
        [
            "mlx_lm.generate",
            "--model", MLX_FALLBACK_MODEL,
            "--prompt", prompt,
            "--max-tokens", "1500",
            "--temp", str(temperature),
        ],
        capture_output=True, text=True, check=True, timeout=180,
    ).stdout
    # mlx_lm prints prompt + completion separated by "==========" markers
    parts = raw.split("==========")
    text = parts[1] if len(parts) >= 2 else raw
    print_token_usage(
        "process-video.mlx-json",
        model=MLX_FALLBACK_MODEL,
        prompt_text=prompt,
        completion_text=text,
        temperature=temperature,
        exact=False,
    )
    return _extract_json(text.strip())


def _extract_json(text: str) -> Any:
    text = text.strip()
    text = re.sub(r"^```json\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    # Try direct parse first
    with contextlib.suppress(json.JSONDecodeError):
        return json.loads(text)
    # Fall back to first {...} or [...] block
    m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON in response: {text[:200]!r}")
    return json.loads(m.group(1))


def llm_json(
    system: str,
    user: str,
    *,
    schema_check: callable,
    fallback: Any,
    log: StepLog,
    label: str,
) -> Any:
    """Call LLM (Ollama → MLX fallback), validate, retry, fallback."""
    last_err = None
    use_mlx = False
    for attempt in range(3):
        try:
            if use_mlx:
                result = call_mlx_json(system, user, temperature=0.4 + attempt * 0.2)
            else:
                result = call_ollama_json(system, user, temperature=0.4 + attempt * 0.2)
            schema_check(result)
            return result
        except (urllib.error.URLError, OSError) as e:
            last_err = e
            log.append(step=label, status="ollama_unreachable", note=str(e))
            use_mlx = True
        except (ValueError, KeyError, TypeError, AssertionError) as e:
            last_err = e
            log.append(step=label, status="bad_schema", attempt=attempt + 1, note=str(e)[:200])
    log.append(step=label, status="fallback", note=str(last_err)[:200])
    return fallback


# ────────────────── ffmpeg helpers ──────────────────


def ffprobe_json(video: Path) -> dict:
    raw = shell(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(video)],
        capture=True,
    )
    return json.loads(raw)


def integrity_check(video: Path) -> tuple[float, dict]:
    info = ffprobe_json(video)
    streams = info.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not video_streams:
        raise ValueError(f"{video.name} has no video stream")
    if not audio_streams:
        raise ValueError(f"{video.name} has no audio stream; Forge needs audio for transcription/captions")
    duration = float(info.get("format", {}).get("duration", 0))
    if duration < 1.0:
        raise ValueError(f"{video.name} duration is {duration:.2f}s — too short")
    return duration, info


def extract_audio(video: Path, audio_out: Path, denoise: bool) -> None:
    audio_out.parent.mkdir(parents=True, exist_ok=True)
    af = ["-af", "afftdn=nf=-25"] if denoise else []
    tmp = _register_tmp(audio_out.with_name(f"{audio_out.stem}.tmp{audio_out.suffix}"))
    shell(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(video), "-vn", "-ac", "1", "-ar", "16000",
            *af, "-f", "wav", str(tmp),
        ]
    )
    os.replace(tmp, audio_out)
    _discard_tmp(tmp)
    validate_audio(audio_out)


# ────────────────── steps ──────────────────


def step_transcribe(video: Path, base: Path, log: StepLog, preset: dict, noisy: bool, force: bool) -> Path:
    transcript_dir = base / "transcript"
    srt = transcript_dir / f"{video.stem}.srt"
    json_path = transcript_dir / f"{video.stem}.json"
    if srt.exists() and json_path.exists() and not force:
        log.append(step="transcribe", status="cached")
        return transcript_dir

    audio = base / "audio.wav"
    with log.step("extract_audio", denoise=noisy):
        extract_audio(video, audio, denoise=noisy)

    with log.step("whisper", model=preset["whisper"]):
        with ResourceLock("metal-heavy") as lock:
            if lock.wait_seconds > 0.1:
                log.append(step="resource_wait", resource="metal-heavy", seconds=round(lock.wait_seconds, 2))
            shell(
                [
                    "mlx_whisper", str(audio),
                    "--model", preset["whisper"],
                    "--output-dir", str(transcript_dir),
                    "--output-format", "srt",
                    "--output-format", "vtt",
                    "--output-format", "txt",
                    "--output-format", "json",
                    "--word-timestamps", "True",
                ]
            )
    if not srt.exists() or srt.stat().st_size < 20:
        raise ValueError(f"Whisper produced missing/tiny SRT: {srt}")
    if not json_path.exists() or json_path.stat().st_size < 20:
        raise ValueError(f"Whisper produced missing/tiny JSON: {json_path}")

    # Surface low-confidence segments for human review
    try:
        data = json.loads(json_path.read_text())
        low = [
            {
                "id": s.get("id"),
                "start": s.get("start"),
                "end": s.get("end"),
                "avg_logprob": s.get("avg_logprob"),
                "text": s.get("text", "").strip(),
            }
            for s in data.get("segments", [])
            if (s.get("avg_logprob") or 0) < LOW_CONF_THRESHOLD
        ]
        atomic_write_json(transcript_dir / "low-confidence.json", low)
        log.append(step="confidence_check", low_segments=len(low))
    except Exception as e:
        log.append(step="confidence_check", status="warn", note=str(e))

    return transcript_dir


def _requested_caption_languages(raw: str | None) -> list[str]:
    if raw is None:
        raw = os.environ.get(FORGE_CAPTION_LANGS_ENV) or os.environ.get(CAPTION_LANGS_ENV)
    try:
        langs = parse_language_codes(raw)
    except ValueError as e:
        raise ValueError(str(e)) from e
    return langs or ["en"]


def _caption_timestamp(seconds: float, *, vtt: bool = False) -> str:
    seconds = max(0.0, float(seconds))
    millis = int(round(seconds * 1000))
    h, rem = divmod(millis, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    sep = "." if vtt else ","
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def _segments_from_whisper_json(transcript_dir: Path, video_stem: str) -> list[dict[str, Any]]:
    json_path = transcript_dir / f"{video_stem}.json"
    data = json.loads(json_path.read_text(encoding="utf-8"))
    segments: list[dict[str, Any]] = []
    for seg in data.get("segments", []):
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        start = float(seg.get("start", 0.0) or 0.0)
        end = float(seg.get("end", start + 2.0) or start + 2.0)
        if end <= start:
            end = start + 2.0
        segments.append({"start": start, "end": end, "text": text})
    return segments


def _srt_text(segments: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for i, seg in enumerate(segments, 1):
        blocks.append(
            f"{i}\n"
            f"{_caption_timestamp(seg['start'])} --> {_caption_timestamp(seg['end'])}\n"
            f"{seg['text'].strip()}\n"
        )
    return "\n".join(blocks).rstrip() + "\n"


def _vtt_text(segments: list[dict[str, Any]]) -> str:
    blocks = ["WEBVTT\n"]
    for seg in segments:
        blocks.append(
            f"{_caption_timestamp(seg['start'], vtt=True)} --> {_caption_timestamp(seg['end'], vtt=True)}\n"
            f"{seg['text'].strip()}\n"
        )
    return "\n".join(blocks).rstrip() + "\n"


def _write_caption_triplet(transcript_dir: Path, video_stem: str, lang: str, segments: list[dict[str, Any]]) -> dict[str, str]:
    base = transcript_dir / f"{video_stem}.{lang}"
    srt = base.with_suffix(".srt")
    vtt = base.with_suffix(".vtt")
    txt = base.with_suffix(".txt")
    atomic_write_text(srt, _srt_text(segments))
    atomic_write_text(vtt, _vtt_text(segments))
    atomic_write_text(txt, "\n".join(seg["text"].strip() for seg in segments) + "\n")
    return {"srt": str(srt), "vtt": str(vtt), "txt": str(txt)}


def step_translate_captions(
    transcript_dir: Path,
    video_stem: str,
    languages: list[str],
    log: StepLog,
    force: bool,
) -> dict[str, Any]:
    """Produce per-language caption files, preserving Whisper segment timing."""
    segments = _segments_from_whisper_json(transcript_dir, video_stem)
    if not segments:
        raise ValueError("no transcript segments available for captions")

    outputs: dict[str, Any] = {}
    for lang in languages:
        lang = lang.lower()
        target_srt = transcript_dir / f"{video_stem}.{lang}.srt"
        target_vtt = transcript_dir / f"{video_stem}.{lang}.vtt"
        target_txt = transcript_dir / f"{video_stem}.{lang}.txt"
        if all(p.exists() and p.stat().st_size > 0 for p in (target_srt, target_vtt, target_txt)) and not force:
            outputs[lang] = {
                "language": language_name(lang),
                "status": "cached",
                "srt": str(target_srt),
                "vtt": str(target_vtt),
                "txt": str(target_txt),
            }
            continue

        if lang == "en":
            files = _write_caption_triplet(transcript_dir, video_stem, lang, segments)
            outputs[lang] = {"language": language_name(lang), "status": "source", **files}
            log.append(step="captions", status="source", lang=lang, segments=len(segments))
            continue

        translated_segments = [dict(seg) for seg in segments]
        batch_size = 12
        fallback_batches = 0
        with log.step("translate_captions", lang=lang, model=TRANSLATE_MODEL, segments=len(segments)):
            for start in range(0, len(segments), batch_size):
                batch = segments[start : start + batch_size]
                try:
                    with ResourceLock("llm") as lock:
                        if lock.wait_seconds > 0.1:
                            log.append(step="resource_wait", resource="llm", seconds=round(lock.wait_seconds, 2))
                        translated = translate_texts_ollama(
                            [seg["text"] for seg in batch],
                            lang,
                            model=TRANSLATE_MODEL,
                            timeout=240,
                        )
                except Exception as e:
                    log.append(
                        step="translate_captions",
                        status="fallback_batch",
                        lang=lang,
                        start=start,
                        error=str(e)[:240],
                    )
                    fallback_batches += 1
                    translated = [seg["text"] for seg in batch]
                for offset, text in enumerate(translated):
                    translated_segments[start + offset]["text"] = text
        files = _write_caption_triplet(transcript_dir, video_stem, lang, translated_segments)
        outputs[lang] = {
            "language": language_name(lang),
            "status": "translated" if fallback_batches == 0 else "partial_fallback",
            "fallback_batches": fallback_batches,
            "translation_model": TRANSLATE_MODEL,
            **files,
        }

    atomic_write_json(
        transcript_dir / "caption-translations.json",
        {"source_lang": "en", "languages": languages, "outputs": outputs, "translation_model": TRANSLATE_MODEL},
    )
    return outputs


def first_speech_sec(transcript_dir: Path, video_stem: str) -> float:
    json_path = transcript_dir / f"{video_stem}.json"
    if not json_path.exists():
        return 0.0
    try:
        data = json.loads(json_path.read_text())
        for seg in data.get("segments", []):
            for word in seg.get("words") or []:
                t = word.get("start")
                if t is not None and word.get("word", "").strip():
                    return float(t)
            if seg.get("text", "").strip():
                return float(seg.get("start", 0.0))
    except Exception:
        pass
    return 0.0


def numbered_sentences(transcript_dir: Path, video_stem: str) -> list[dict]:
    json_path = transcript_dir / f"{video_stem}.json"
    if not json_path.exists():
        return []
    data = json.loads(json_path.read_text())
    out = []
    for i, seg in enumerate(data.get("segments", []), 1):
        txt = (seg.get("text") or "").strip()
        if not txt:
            continue
        out.append({"i": i, "start": float(seg.get("start", 0)), "text": txt})
    return out


# ─── schemas ───


def assert_meta_schema(obj: Any) -> None:
    assert isinstance(obj, dict), "meta must be object"
    titles = obj.get("titles", [])
    assert isinstance(titles, list) and 1 <= len(titles) <= 5, "titles 1-5 strings"
    assert all(isinstance(t, str) and len(t) <= 80 for t in titles), "titles ≤80 chars"
    assert isinstance(obj.get("description", ""), str), "description string"
    tags = obj.get("tags", [])
    assert isinstance(tags, list) and 1 <= len(tags) <= 20, "tags 1-20 strings"


def assert_hook_schema(obj: Any) -> None:
    assert isinstance(obj, dict), "hook must be object"
    assert isinstance(obj.get("text", ""), str), "text string"
    assert 1 <= len(obj["text"].split()) <= 10, "hook 1-10 words"


def assert_moments_schema(obj: Any) -> None:
    moments = obj.get("moments") if isinstance(obj, dict) else obj
    assert isinstance(moments, list) and moments, "moments non-empty list"
    for m in moments:
        assert isinstance(m, dict), "each moment is object"
        assert isinstance(m.get("text", ""), str) and m["text"].strip(), "moment text non-empty"
        assert isinstance(m.get("sec", -1), (int, float)) and m["sec"] >= 0, "sec ≥ 0"


def assert_concepts_schema(obj: Any) -> None:
    concepts = obj if isinstance(obj, list) else obj.get("concepts")
    assert isinstance(concepts, list) and 1 <= len(concepts) <= 5, "concepts 1-5"
    for c in concepts:
        assert isinstance(c, dict), "concept is object"
        assert isinstance(c.get("prompt", ""), str) and len(c["prompt"]) > 5, "prompt non-trivial"
        assert isinstance(c.get("headline", ""), str), "headline string"


def transcript_digest(text: str, *, max_chars: int = 9000) -> str:
    """Keep beginning, middle, and ending context instead of only the opening."""
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    third = max_chars // 3
    mid_start = max(0, len(text) // 2 - third // 2)
    return "\n\n".join(
        [
            "BEGINNING:\n" + text[:third],
            "MIDDLE:\n" + text[mid_start : mid_start + third],
            "ENDING:\n" + text[-third:],
        ]
    )


def step_analyze(
    transcript_dir: Path, video_stem: str, duration: float, base: Path, log: StepLog, force: bool
) -> dict:
    cache = base / "metadata" / "analysis.json"
    if cache.exists() and not force:
        log.append(step="analyze", status="cached")
        return json.loads(cache.read_text())

    transcript_text = (transcript_dir / f"{video_stem}.txt").read_text(encoding="utf-8")
    transcript_short = transcript_digest(transcript_text)
    sentences = numbered_sentences(transcript_dir, video_stem)
    sentence_list = "\n".join(f"[{s['i']} @{s['start']:.1f}s] {s['text']}" for s in sentences[:80])

    # 1. Title / description / tags
    with log.step("llm_meta"):
        meta = llm_json(
            system=(
                "You are a YouTube SEO copywriter. Reply STRICT JSON, no markdown. Schema: "
                '{"titles":[3 strings ≤60 chars each, hook-driven, sentence-case],'
                '"description":"2-4 paragraph markdown ending in subscribe CTA",'
                '"tags":[8-15 lowercase strings, no #]}'
            ),
            user=f"Video duration {int(duration)}s. Transcript:\n\n{transcript_short}\n\nReturn JSON now.",
            schema_check=assert_meta_schema,
            fallback={
                "titles": [transcript_short[:60].strip() or "Untitled video"],
                "description": "Auto-generated. Edit me.\n\nSubscribe for more.",
                "tags": ["video"],
            },
            log=log, label="llm_meta",
        )

    # 2. Hook
    with log.step("llm_hook"):
        hook = llm_json(
            system='Reply JSON {"text":"3-6 word ALL CAPS hook"}. Stop-scroll text for 0:00–0:03.',
            user=f"Transcript opening:\n\n{transcript_short[:1200]}",
            schema_check=assert_hook_schema,
            fallback={"text": (sentences[0]["text"][:40].upper() if sentences else "WATCH THIS")},
            log=log, label="llm_hook",
        )

    # 3. Sentence-aligned moments
    n_moments = 3 if duration < 120 else 4
    with log.step("llm_moments"):
        moments = llm_json(
            system=(
                "Pick exactly " + str(n_moments) + " sentences from the numbered list below that "
                "would be PUNCHY emphasis text overlays. Reply JSON "
                '{"moments":[{"i": int (sentence index), "sec": int (≥0), "text": "3-6 WORD ALL CAPS"}]}. '
                "The sec value must equal the @s value of the sentence you picked. "
                "Spread picks roughly evenly across the video."
            ),
            user=f"Numbered sentences:\n{sentence_list}",
            schema_check=assert_moments_schema,
            fallback={"moments": _heuristic_moments(sentences, duration, n_moments)},
            log=log, label="llm_moments",
        )

    # 4. Thumbnail concepts
    with log.step("llm_concepts"):
        concepts = llm_json(
            system=(
                "Reply JSON [3 objects]: "
                '{"prompt":"cinematic 16:9 image prompt, no text on image", '
                '"headline":"3-6 word ALL CAPS thumbnail text"}. Three distinct concepts.'
            ),
            user=f"Transcript:\n\n{transcript_short[:3000]}",
            schema_check=assert_concepts_schema,
            fallback=[
                {
                    "prompt": "cinematic 16:9 dramatic outdoor scene, golden hour, no text",
                    "headline": (sentences[0]["text"][:30].upper() if sentences else "WATCH"),
                }
            ],
            log=log, label="llm_concepts",
        )

    analysis = {
        "titles": meta["titles"],
        "description": meta["description"],
        "tags": meta["tags"],
        "hook": hook["text"],
        "moments": (moments if isinstance(moments, list) else moments.get("moments", [])),
        "thumbnail_concepts": concepts if isinstance(concepts, list) else concepts.get("concepts", []),
    }
    atomic_write_json(cache, analysis)
    meta_dir = base / "metadata"
    meta_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(meta_dir / "title.txt", "\n".join(analysis["titles"]) + "\n")
    atomic_write_text(meta_dir / "description.md", analysis["description"] + "\n")
    atomic_write_text(meta_dir / "tags.txt", ", ".join(analysis["tags"]) + "\n")
    return analysis


def _heuristic_moments(sentences: list[dict], duration: float, n: int) -> list[dict]:
    if not sentences:
        return [{"sec": int(duration * (i + 1) / (n + 1)), "text": f"MOMENT {i + 1}"} for i in range(n)]
    picks = []
    for i in range(n):
        target = duration * (i + 1) / (n + 1)
        nearest = min(sentences, key=lambda s: abs(s["start"] - target))
        picks.append({"i": nearest["i"], "sec": int(nearest["start"]), "text": nearest["text"][:40].upper()})
    return picks


def step_silences(video: Path, base: Path, log: StepLog, force: bool) -> list[dict]:
    out_path = base / "cuts.json"
    if out_path.exists() and not force:
        return json.loads(out_path.read_text())
    with log.step("silencedetect"):
        raw = run_subprocess(
            [
                "ffmpeg", "-hide_banner", "-i", str(video),
                "-af", "silencedetect=noise=-30dB:d=0.6",
                "-f", "null", "-",
            ],
            capture_output=True, text=True,
            timeout=DEFAULT_SUBPROCESS_TIMEOUT_SEC,
        ).stderr
    starts = [float(m) for m in re.findall(r"silence_start: (\d+\.?\d*)", raw)]
    ends = [float(m) for m in re.findall(r"silence_end: (\d+\.?\d*) ", raw)]
    cuts = [{"start": s, "end": e, "duration": round(e - s, 3)} for s, e in zip(starts, ends)]
    atomic_write_json(out_path, cuts)
    return cuts


# ─── PIL overlay generators ───


def _font(name: str, size: int):
    from PIL import ImageFont
    for path in (f"/System/Library/Fonts/Supplemental/{name}", f"/System/Library/Fonts/{name}"):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def render_hook(text: str, out_path: Path, width: int, height: int) -> None:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _font("Impact.ttf", int(height * 0.13))
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = (width - tw) // 2, int(height * 0.36)
    draw.rectangle([0, y - 30, width, y + th + 30], fill=(0, 0, 0, 170))
    for dx, dy in [(-4, 0), (4, 0), (0, -4), (0, 4), (-3, -3), (3, 3), (-3, 3), (3, -3)]:
        draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 255))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    atomic_write_bytes(out_path, _png_bytes(img))


def render_moment(text: str, out_path: Path, width: int, height: int) -> None:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _font("Impact.ttf", int(height * 0.085))
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x, y = 40, int(height * 0.13)
    draw.rectangle([0, y - 16, 14, y + th + 16], fill=(212, 169, 55, 255))
    draw.rectangle([0, y - 16, x + tw + 30, y + th + 16], fill=(0, 0, 0, 170))
    for dx, dy in [(-3, 0), (3, 0), (0, -3), (0, 3)]:
        draw.text((x + dx, y + dy), text, font=font, fill=(0, 0, 0, 255))
    draw.text((x, y), text, font=font, fill=(255, 255, 255, 255))
    atomic_write_bytes(out_path, _png_bytes(img))


def render_cta(text: str, out_path: Path, width: int, height: int) -> None:
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _font("Helvetica.ttc", int(height * 0.045))
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    pad = 24
    box_w, box_h = tw + pad * 2, th + pad
    x, y = width - box_w - 60, height - box_h - 60
    draw.rounded_rectangle([x, y, x + box_w, y + box_h], radius=12, fill=(212, 169, 55, 240))
    draw.text((x + pad, y + pad // 2), text, font=font, fill=(10, 10, 10, 255))
    atomic_write_bytes(out_path, _png_bytes(img))


def _png_bytes(img) -> bytes:
    from io import BytesIO
    buf = BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def reading_time_sec(text: str) -> float:
    # ~3 chars/sec reading rate for caps text; floor 3.0, ceiling 6.0
    return max(3.0, min(6.0, len(text) / 15.0 + 1.0))


def step_overlays(
    analysis: dict, base: Path, video: Path, duration: float, first_speech: float, log: StepLog, force: bool
) -> dict:
    ov_dir = base / "overlays"
    ov_dir.mkdir(parents=True, exist_ok=True)
    probe = shell(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height",
         "-of", "csv=p=0", str(video)],
        capture=True,
    ).strip()
    vw, vh = (int(x) for x in probe.split(",")[:2])

    hook_text = (analysis.get("hook") or "WATCH THIS").upper().strip()
    hook_png = ov_dir / "hook.png"
    if not hook_png.exists() or force:
        with log.step("render_hook"):
            render_hook(hook_text, hook_png, vw, vh)
    hook_start = max(0.0, first_speech - 0.2)
    hook_dur = reading_time_sec(hook_text)

    moments_meta: list[dict] = []
    for i, m in enumerate(analysis.get("moments", [])):
        text = str(m.get("text", "")).upper().strip()
        if not text:
            continue
        png = ov_dir / f"moment-{i}.png"
        if not png.exists() or force:
            with log.step("render_moment", i=i):
                render_moment(text, png, vw, vh)
        moments_meta.append(
            {
                "png": png.name,
                "sec": float(m.get("sec", 0)),
                "duration": reading_time_sec(text),
                "text": text,
            }
        )

    cta_png = ov_dir / "subscribe.png"
    if not cta_png.exists() or force:
        with log.step("render_cta"):
            render_cta("SUBSCRIBE — more like this", cta_png, vw, vh)
    cta_dur = max(2.0, min(6.0, duration * 0.05))

    return {
        "hook": {"png": hook_png.name, "text": hook_text, "start": hook_start, "duration": hook_dur},
        "moments": moments_meta,
        "cta": {"png": cta_png.name, "duration": cta_dur},
        "video_w": vw, "video_h": vh,
    }


def step_thumbnails(analysis: dict, base: Path, preset: dict, log: StepLog, skip: bool, force: bool) -> list[str]:
    if skip:
        log.append(step="thumbnails", status="skipped")
        return []
    thumb_dir = base / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    concepts = (analysis.get("thumbnail_concepts") or [])[:3]
    atomic_write_json(thumb_dir / "concepts.json", concepts)
    produced: list[str] = []
    for i, c in enumerate(concepts, start=1):
        prompt = c.get("prompt", "")
        headline = (c.get("headline") or "").upper()
        if not prompt:
            continue
        bg = thumb_dir / f"hook-{i}-bg.png"
        final = thumb_dir / f"hook-{i}.png"
        if final.exists() and not force:
            produced.append(final.name)
            continue
        bg_tmp = _register_tmp(bg.with_name(f"{bg.stem}.tmp{bg.suffix}"))
        with log.step("flux", i=i, model=preset["flux"], steps=preset["flux_steps"]):
            with ResourceLock("metal-heavy") as lock:
                if lock.wait_seconds > 0.1:
                    log.append(step="resource_wait", resource="metal-heavy", seconds=round(lock.wait_seconds, 2))
                shell(
                    [
                        "mflux-generate",
                        "--model", preset["flux"],
                        "--prompt", prompt,
                        "--width", str(THUMB_W),
                        "--height", str(THUMB_H),
                        "--steps", str(preset["flux_steps"]),
                        "--guidance", "0.0" if preset["flux"] == "schnell" else "3.5",
                        "--seed", str(i),
                        "--output", str(bg_tmp),
                    ]
                )
        validate_png(bg_tmp, width=THUMB_W, height=THUMB_H, min_bytes=4096)
        os.replace(bg_tmp, bg)
        _discard_tmp(bg_tmp)
        _compose_thumb(bg, final, headline)
        produced.append(final.name)
    return produced


def _compose_thumb(bg: Path, out_path: Path, headline: str) -> None:
    from PIL import Image, ImageDraw
    img = Image.open(bg).convert("RGBA")
    if headline:
        font = _font("Impact.ttf", int(img.height * 0.13))
        overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(overlay).rectangle(
            [0, int(img.height * 0.55), img.width, img.height], fill=(0, 0, 0, 170)
        )
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)
        bbox = draw.textbbox((0, 0), headline, font=font)
        th = bbox[3] - bbox[1]
        x, y = 40, int(img.height * 0.65)
        for dx, dy in [(-4, 0), (4, 0), (0, -4), (0, 4), (-3, -3), (3, 3)]:
            draw.text((x + dx, y + dy), headline, font=font, fill=(0, 0, 0, 255))
        draw.text((x, y), headline, font=font, fill=(255, 255, 255, 255))
        draw.rectangle([x, y + th + 16, x + 240, y + th + 22], fill=(212, 169, 55, 255))
    tmp = _register_tmp(out_path.with_name(f"{out_path.stem}.tmp{out_path.suffix}"))
    try:
        img.convert("RGB").save(tmp, "PNG", optimize=True)
        os.replace(tmp, out_path)
    finally:
        if tmp.exists():
            tmp.unlink()
        _discard_tmp(tmp)
    validate_png(out_path, min_bytes=1024)


def step_burn_in(
    video: Path,
    transcript_dir: Path,
    overlays: dict,
    duration: float,
    base: Path,
    log: StepLog,
    force: bool,
    require_audio: bool,
) -> Path:
    final = base / "upload-ready.mp4"
    if final.exists() and not force:
        log.append(step="burn_in", status="cached")
        return final
    srt = transcript_dir / f"{video.stem}.srt"
    ov_dir = base / "overlays"

    inputs: list[str] = ["-i", str(video)]
    pngs = [ov_dir / overlays["hook"]["png"]] + [ov_dir / m["png"] for m in overlays["moments"]] + [ov_dir / overlays["cta"]["png"]]
    for p in pngs:
        validate_png(p, min_bytes=1024)
        inputs += ["-loop", "1", "-i", str(p)]

    style = (
        "FontName=Helvetica,FontSize=22,PrimaryColour=&HFFFFFF&,"
        "OutlineColour=&H000000&,Outline=2,BorderStyle=1,Alignment=2,MarginV=80"
    )
    if not srt.exists() or srt.stat().st_size < 20:
        raise ValueError(f"missing/tiny subtitles file: {srt}")
    chain = [f"[0:v]subtitles='{ffmpeg_filter_escape(srt)}':force_style='{ffmpeg_filter_escape(style)}'[v0]"]
    last = "v0"
    h = overlays["hook"]
    h_start = max(0.0, min(float(h["start"]), max(0.0, duration - 0.1)))
    h_end = max(h_start + 0.1, min(duration, h_start + float(h["duration"])))
    chain.append(
        f"[{last}][1:v]overlay=enable='between(t,{h_start:.2f},{h_end:.2f})':x=0:y=0[v1]"
    )
    last = "v1"
    for i, m in enumerate(overlays["moments"]):
        s = max(0.0, float(m["sec"]))
        s = min(s, max(0.0, duration - 0.1))
        e = max(s + 0.1, min(duration, s + float(m["duration"])))
        idx = 2 + i
        nxt = f"v{i + 2}"
        chain.append(
            f"[{last}][{idx}:v]overlay=enable='between(t,{s:.2f},{e:.2f})':x=0:y=0[{nxt}]"
        )
        last = nxt
    cta = overlays["cta"]
    cta_duration = max(0.1, min(float(cta["duration"]), max(0.1, duration - 0.1)))
    cta_start = max(0.0, duration - cta_duration)
    cta_idx = 2 + len(overlays["moments"])
    chain.append(f"[{last}][{cta_idx}:v]overlay=enable='gte(t,{cta_start:.2f})':x=0:y=0[vout]")
    filter_str = ";".join(chain)

    tmp_out = _register_tmp(final.with_name(f"{final.stem}.tmp{final.suffix}"))
    with log.step("burn_in"):
        shell(
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
                *inputs,
                "-filter_complex", filter_str,
                "-map", "[vout]", "-map", "0:a?",
                "-c:v", "libx264", "-preset", "slow", "-crf", "18",
                "-pix_fmt", "yuv420p",
                "-c:a", "copy", "-movflags", "+faststart", "-shortest",
                str(tmp_out),
            ]
        )
    os.replace(tmp_out, final)
    _discard_tmp(tmp_out)
    validate_video(final, expected_duration=duration, require_audio=require_audio)
    return final


# ────────────────── orchestrate `process` ──────────────────


def _cmd_process_inner(args: argparse.Namespace, job_id: int | None = None) -> int:
    warmup = assert_ready(args.offline_skip_check)
    preset = QUALITY_PRESETS[args.quality]

    video = Path(args.video).resolve()
    if not video.exists():
        sys.exit(f"missing video: {video}")

    base = Path(args.out).resolve() / video.stem
    base.mkdir(parents=True, exist_ok=True)
    log = StepLog(base / "pipeline.log")

    log.append(
        step="run_start", video=str(video), pipeline_schema=SCHEMA_VERSION,
        quality=args.quality, warmup=warmup.get("warmup_at"), job_id=job_id,
    )

    with log.step("integrity"):
        duration, info = integrity_check(video)
    input_has_audio = any(s.get("codec_type") == "audio" for s in info.get("streams", []))
    print(f"video: {video.name}  duration {duration:.1f}s  quality={args.quality}")

    transcript_dir = step_transcribe(video, base, log, preset, noisy=args.noisy, force=args.force)
    caption_langs = _requested_caption_languages(args.captions)
    caption_outputs = step_translate_captions(transcript_dir, video.stem, caption_langs, log, args.force)
    first_speech = first_speech_sec(transcript_dir, video.stem)
    print(f"  · first speech at {first_speech:.2f}s")
    print(f"  · captions: {', '.join(caption_outputs)}")

    analysis = step_analyze(transcript_dir, video.stem, duration, base, log, args.force)
    print(f"  · hook: {analysis.get('hook')!r}")
    print(f"  · moments: {len(analysis.get('moments', []))}")

    overlays = step_overlays(analysis, base, video, duration, first_speech, log, args.force)
    print(f"  · overlays rendered for {overlays['video_w']}×{overlays['video_h']}")

    thumbs = step_thumbnails(analysis, base, preset, log, skip=args.no_thumbs, force=args.force)
    silences = step_silences(video, base, log, args.force)
    print(f"  · thumbnails: {len(thumbs)}   silences: {len(silences)}")

    final_path: Optional[Path] = None
    if not args.no_burn:
        final_path = step_burn_in(video, transcript_dir, overlays, duration, base, log, args.force, input_has_audio)
        print(f"  · upload-ready.mp4 written ({final_path.stat().st_size // (1 << 20)} MB)")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "video": {
            "path": str(video),
            "duration_sec": duration,
            "size_bytes": video.stat().st_size,
            "sha16": file_sha16(video),
            "ffprobe_format": info.get("format", {}).get("format_name"),
        },
        "quality_preset": args.quality,
        "warmup": warmup,
        "analysis": analysis,
        "overlays": overlays,
        "thumbnails": thumbs,
        "captions": caption_outputs,
        "silences": silences,
        "first_speech_sec": first_speech,
        "upload_ready": str(final_path) if final_path else None,
    }
    atomic_write_json(base / "prep-manifest.json", manifest)
    log.append(step="run_done")
    print(f"\nDone. Output: {base}")
    return 0


def cmd_process(args: argparse.Namespace) -> int:
    video = Path(args.video).resolve()
    base = Path(args.out).resolve() / video.stem
    store = JobStore()
    job_id = store.create_job(
        "process-video",
        str(video),
        str(base),
        profile=args.quality,
        metadata={
            "noisy": args.noisy,
            "no_burn": args.no_burn,
            "no_thumbs": args.no_thumbs,
            "force": args.force,
            "captions": args.captions,
        },
    )
    try:
        code = _cmd_process_inner(args, job_id=job_id)
    except Exception as e:
        store.finish_job(job_id, "failed", str(e))
        raise
    store.finish_job(job_id, "done")
    return code


# ────────────────── argparse ──────────────────


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Local upload-ready video prep, v2")
    sub = p.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("warmup", help="Pre-download all models, verify deps")
    w.add_argument("--quality", choices=list(QUALITY_PRESETS), default="good")
    w.add_argument("--dry-run", action="store_true")
    w.set_defaults(func=cmd_warmup)

    pr = sub.add_parser("process", help="Process a single video")
    pr.add_argument("video")
    pr.add_argument("--out", default="videos-out")
    pr.add_argument("--quality", choices=list(QUALITY_PRESETS), default="good")
    pr.add_argument("--noisy", action="store_true", help="aggressive audio denoise (driving / wind)")
    pr.add_argument("--no-burn", action="store_true")
    pr.add_argument("--no-thumbs", action="store_true")
    pr.add_argument(
        "--captions",
        default=None,
        help=f"comma-separated caption languages, e.g. en,mr,hi (env {FORGE_CAPTION_LANGS_ENV} or {CAPTION_LANGS_ENV})",
    )
    pr.add_argument("--force", action="store_true")
    pr.add_argument("--offline-skip-check", action="store_true", help="run without warmup marker")
    pr.set_defaults(func=cmd_process)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    install_runtime_guards()
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[interrupted]", file=sys.stderr)
        sys.exit(130)
    except subprocess.TimeoutExpired as e:
        print(f"\n[error] subprocess timed out after {e.timeout}s: {e.cmd}", file=sys.stderr)
        sys.exit(124)
    except subprocess.CalledProcessError as e:
        print(f"\n[error] subprocess failed: {e}", file=sys.stderr)
        sys.exit(e.returncode)
    except ValueError as e:
        print(f"\n[error] validation failed: {e}", file=sys.stderr)
        sys.exit(2)
