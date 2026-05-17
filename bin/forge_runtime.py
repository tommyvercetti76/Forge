"""Shared runtime helpers for Forge.

This module is intentionally dependency-light. It owns the boring but crucial
parts of a local ML appliance: canonical paths, artifact validation, resource
locks, job state, and machine health reporting.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


FORGE_HOME = Path(os.environ.get("FORGE_HOME") or Path(__file__).resolve().parent.parent).resolve()
MODELS_HOME = Path(os.environ.get("MODELS_HOME") or Path.home() / "Models").resolve()
ENV_HF_HOME = os.environ.get("HF_HOME")
HF_HOME = Path(os.environ.get("FORGE_HF_HOME") or MODELS_HOME / "huggingface").resolve()
FORGE_STATE_HOME = Path(os.environ.get("FORGE_STATE_HOME") or Path.home() / ".forge").resolve()
PIPELINE_HOME = Path(os.environ.get("PIPELINE_HOME") or Path.home() / ".kaayko-pipeline").resolve()
LOCAL_BIN = Path.home() / ".local" / "bin"
OLLAMA_URL = os.environ.get("FORGE_OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("FORGE_OLLAMA_MODEL", "qwen3:8b")
TRANSLATE_MODEL = os.environ.get(
    "FORGE_TRANSLATE_MODEL",
    "hf.co/mradermacher/sarvam-translate-GGUF:Q4_K_M",
)
TOKEN_USAGE_ENABLED = os.environ.get("FORGE_TOKEN_USAGE", "1").lower() not in {"0", "false", "no", "off"}

LANGUAGE_NAMES: dict[str, str] = {
    "en": "English",
    "hi": "Hindi",
    "mr": "Marathi",
    "gu": "Gujarati",
    "ta": "Tamil",
    "te": "Telugu",
    "kn": "Kannada",
    "ml": "Malayalam",
    "bn": "Bengali",
    "pa": "Punjabi",
    "ur": "Urdu",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
}

LANGUAGE_ALIASES: dict[str, str] = {
    "english": "en",
    "hindi": "hi",
    "marathi": "mr",
    "gujarati": "gu",
    "tamil": "ta",
    "telugu": "te",
    "kannada": "kn",
    "malayalam": "ml",
    "bengali": "bn",
    "punjabi": "pa",
    "urdu": "ur",
    "spanish": "es",
    "french": "fr",
    "german": "de",
    "portuguese": "pt",
}


def estimate_token_count(text: str | None) -> int:
    """Cheap cross-model token estimate for places where a backend gives no count."""
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _seconds_from_ns(value: Any) -> float | None:
    try:
        ns = float(value)
    except (TypeError, ValueError):
        return None
    if ns <= 0:
        return None
    return ns / 1_000_000_000.0


def print_token_usage(
    label: str,
    *,
    model: str,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    prompt_text: str | None = None,
    completion_text: str | None = None,
    context: int | None = None,
    temperature: float | None = None,
    total_seconds: float | None = None,
    exact: bool = False,
) -> None:
    """Always-visible LLM token telemetry for Forge commands.

    Ollama reports exact prompt/completion token counts. MLX and other fallback
    paths may not, so this function falls back to a clearly labeled estimate.
    """
    if not TOKEN_USAGE_ENABLED:
        return
    if prompt_tokens is None:
        prompt_tokens = estimate_token_count(prompt_text)
    if completion_tokens is None:
        completion_tokens = estimate_token_count(completion_text)
    total = int(prompt_tokens or 0) + int(completion_tokens or 0)
    confidence = "exact" if exact else "est"
    pieces = [
        f"  · tokens[{label}]",
        f"model={model}",
        f"prompt={int(prompt_tokens or 0)}",
        f"completion={int(completion_tokens or 0)}",
        f"total={total}",
        confidence,
    ]
    if context:
        pieces.append(f"ctx={context}")
    if temperature is not None:
        pieces.append(f"T={temperature:g}")
    if total_seconds is not None:
        pieces.append(f"time={total_seconds:.2f}s")
    print(" ".join(pieces), file=sys.stderr)


def print_ollama_token_usage(
    response: dict[str, Any],
    *,
    label: str,
    model: str,
    prompt_text: str | None = None,
    completion_text: str | None = None,
    context: int | None = None,
    temperature: float | None = None,
) -> None:
    prompt_tokens = response.get("prompt_eval_count")
    completion_tokens = response.get("eval_count")
    exact = prompt_tokens is not None and completion_tokens is not None
    total_seconds = _seconds_from_ns(response.get("total_duration"))
    print_token_usage(
        label,
        model=model,
        prompt_tokens=int(prompt_tokens) if prompt_tokens is not None else None,
        completion_tokens=int(completion_tokens) if completion_tokens is not None else None,
        prompt_text=prompt_text,
        completion_text=completion_text,
        context=context,
        temperature=temperature,
        total_seconds=total_seconds,
        exact=exact,
    )


def forge_path() -> str:
    parts = [str(LOCAL_BIN), "/opt/homebrew/bin", "/usr/local/bin", os.environ.get("PATH", "")]
    out: list[str] = []
    for part in ":".join(parts).split(":"):
        if part and part not in out:
            out.append(part)
    return ":".join(out)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def configure_environment() -> None:
    """Make child tools agree with Forge's canonical model/cache layout."""
    os.environ["MODELS_HOME"] = str(MODELS_HOME)
    os.environ["HF_HOME"] = str(HF_HOME)
    os.environ["HF_HUB_CACHE"] = str(HF_HOME / "hub")
    os.environ["PATH"] = forge_path()


def child_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["MODELS_HOME"] = str(MODELS_HOME)
    env["HF_HOME"] = str(HF_HOME)
    env["HF_HUB_CACHE"] = str(HF_HOME / "hub")
    env["PATH"] = forge_path()
    if extra:
        env.update(extra)
    return env


def hf_cache_root() -> Path:
    return Path(os.environ.get("HF_HOME") or HF_HOME).expanduser().resolve() / "hub"


def hf_repo_dir(repo: str) -> Path:
    return hf_cache_root() / f"models--{repo.replace('/', '--')}"


@dataclass(frozen=True)
class ModelSpec:
    key: str
    backend: str
    repo: str
    role: str
    required_for: str = "optional"


MODEL_REGISTRY: tuple[ModelSpec, ...] = (
    ModelSpec("whisper-turbo", "hf", "mlx-community/whisper-large-v3-turbo", "transcription", "process-video fast/good"),
    ModelSpec("whisper-best", "hf", "mlx-community/whisper-large-v3-mlx", "transcription", "process-video best"),
    ModelSpec("flux-schnell", "hf", "black-forest-labs/FLUX.1-schnell", "image-draft", "thumbnail fast"),
    ModelSpec("flux-dev", "hf", "black-forest-labs/FLUX.1-dev", "image-final", "thumbnail good/best"),
    ModelSpec("flux-kontext", "hf", "black-forest-labs/FLUX.1-Kontext-dev", "image-edit", "forge edit"),
    ModelSpec("mlx-fallback", "hf", "mlx-community/Qwen2.5-Coder-32B-Instruct-4bit", "local-llm-fallback", "analyze fallback"),
    ModelSpec("bge-m3", "hf", "BAAI/bge-m3", "embeddings", "rag"),
)


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code.lower(), code)


def parse_language_codes(raw: str | None) -> list[str]:
    """Parse comma/space-separated BCP-47-ish language codes, preserving order."""
    if not raw:
        return []
    value = raw.strip()
    if value.lower() in {"0", "false", "none", "off", "no"}:
        return []
    out: list[str] = []
    for part in re.split(r"[,\s]+", value):
        if not part:
            continue
        code = LANGUAGE_ALIASES.get(part.lower(), part.lower())
        if not re.match(r"^[a-z]{2,3}(?:-[a-z0-9]+)?$", code):
            raise ValueError(f"invalid language code: {part!r}")
        if code not in out:
            out.append(code)
    return out


def _extract_json(text: str) -> Any:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.MULTILINE).strip()
    with contextlib.suppress(json.JSONDecodeError):
        return json.loads(text)
    match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON in response: {text[:200]!r}")
    return json.loads(match.group(1))


def translate_texts_ollama(
    texts: list[str],
    target_lang: str,
    *,
    source_lang: str = "en",
    model: str | None = None,
    timeout: float = 180,
) -> list[str]:
    """Translate a batch of text strings with local Ollama, preserving item count/order.

    Matches Forge's standard LLM contract: retry up to 3 times with rising
    temperature; if a batch keeps returning the literal placeholder token
    (e.g. sarvam-translate occasionally echoes `<अनुवाद>`), fall through to
    one-at-a-time translation. Last-resort fallback returns the original text
    with a warning so the pipeline keeps moving instead of crashing.
    """
    if not texts:
        return []
    source_lang = source_lang.lower()
    target_lang = target_lang.lower()
    if target_lang == source_lang:
        return list(texts)

    # Try batch translation with rising temperature.
    for attempt, temp in enumerate((0.1, 0.4, 0.7), start=1):
        try:
            return _translate_once(
                texts, target_lang, source_lang=source_lang, model=model,
                timeout=timeout, temperature=temp,
            )
        except _PlaceholderTranslationError as e:
            sys.stderr.write(
                f"  ! translate {target_lang!r} attempt {attempt}/3 (T={temp}) "
                f"returned placeholder; retrying. ({e})\n"
            )

    # Batch failed all 3 retries → try one-at-a-time; this often works because the
    # model handles a single string with a clearer prompt better than a numbered batch.
    sys.stderr.write(f"  ! translate {target_lang!r}: batch failed, falling back to per-item.\n")
    out: list[str] = []
    for text in texts:
        item_done = False
        for temp in (0.1, 0.5):
            try:
                result = _translate_once(
                    [text], target_lang, source_lang=source_lang, model=model,
                    timeout=timeout, temperature=temp,
                )
                out.append(result[0])
                item_done = True
                break
            except _PlaceholderTranslationError:
                continue
        if not item_done:
            sys.stderr.write(
                f"  ! translate {target_lang!r}: gave up on one item, using source: {text[:60]!r}\n"
            )
            out.append(text)  # deterministic fallback — never crash the pipeline
    return out


class _PlaceholderTranslationError(ValueError):
    """Raised when the model returns a literal placeholder instead of a translation."""


def _translate_once(
    texts: list[str],
    target_lang: str,
    *,
    source_lang: str,
    model: str | None,
    timeout: float,
    temperature: float,
) -> list[str]:
    system = (
        "You are a professional media localization engine. Translate faithfully, "
        "preserve names, numbers, punctuation intent, and line-level meaning. "
        "Output ONLY the translated text — never labels, placeholders, brackets, "
        "or explanations."
    )
    if len(texts) == 1:
        prompt = (
            f"Translate the following text from {language_name(source_lang)} "
            f"to {language_name(target_lang)}. Output the translated text only.\n\n"
            f"{texts[0]}"
        )
    else:
        # Use literal indices on both sides — no `<placeholder>` token that the
        # model might echo back as the "answer".
        prompt = (
            f"Translate each numbered line from {language_name(source_lang)} "
            f"to {language_name(target_lang)}.\n"
            "Output the same numbers with the translated text after the colon.\n"
            "Use ONLY the translated text — never write the word 'translation', "
            "never use angle brackets.\n\n"
            + "\n".join(f"{i}: {text}" for i, text in enumerate(texts))
        )
    context_tokens = 8192
    active_model = model or TRANSLATE_MODEL
    body = json.dumps(
        {
            "model": active_model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": temperature, "num_ctx": context_tokens},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate", data=body, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    raw = payload.get("response", "")
    print_ollama_token_usage(
        payload,
        label=f"translate:{source_lang}->{target_lang}",
        model=active_model,
        prompt_text=f"{system}\n{prompt}",
        completion_text=raw,
        context=context_tokens,
        temperature=temperature,
    )
    out = _parse_translation_response(raw, expected=len(texts))
    bad = [text for text in out if _looks_like_translation_placeholder(text)]
    if bad:
        raise _PlaceholderTranslationError(f"placeholder echoed: {bad[0]!r}")
    return [translated or original for translated, original in zip(out, texts)]


def _looks_like_translation_placeholder(text: str) -> bool:
    value = text.strip().lower()
    if not value:
        return True
    if re.fullmatch(r"<?\s*(translation|translate|अनुवाद)\s*>?", value):
        return True
    if re.fullmatch(r"<[^>]*(translation|अनुवाद)[^>]*>", value):
        return True
    return False


def _parse_translation_response(raw: str, *, expected: int) -> list[str]:
    raw = raw.strip()
    if not raw:
        raise ValueError("empty translation response")

    with contextlib.suppress(Exception):
        obj = _extract_json(raw)
        translations = obj.get("translations") if isinstance(obj, dict) else obj
        if isinstance(translations, list):
            by_index: dict[int, str] = {}
            for item in translations:
                if isinstance(item, dict):
                    by_index[int(item.get("i"))] = str(item.get("text", "")).strip()
                else:
                    by_index[len(by_index)] = str(item).strip()
            if len(by_index) >= expected:
                return [by_index.get(i, "") for i in range(expected)]
        if isinstance(obj, dict) and expected == 1 and len(obj) == 1:
            key, value = next(iter(obj.items()))
            return [str(value or key).strip()]

    by_index: dict[int, str] = {}
    for line in raw.splitlines():
        match = re.match(r"^\s*(\d+)\s*[:.)-]\s*(.+?)\s*$", line)
        if match:
            by_index[int(match.group(1))] = match.group(2).strip()
    if len(by_index) >= expected:
        return [by_index.get(i, "") for i in range(expected)]

    if expected == 1:
        cleaned = re.sub(r"^.*?(?:translation is|अनुवाद है)\s*:?", "", raw, flags=re.IGNORECASE | re.DOTALL).strip()
        cleaned = re.sub(r"^\s*(?:items?|आइटम)\s*:?\s*", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"^\s*0\s*[:.)-]\s*", "", cleaned).strip()
        return [cleaned or raw]

    raise ValueError(f"translation response count mismatch: got {len(by_index)}, expected {expected}; raw={raw[:200]!r}")


def ollama_model_names(timeout: float = 5) -> tuple[bool, set[str], str | None]:
    try:
        with urllib.request.urlopen(f"{OLLAMA_URL}/api/tags", timeout=timeout) as response:
            tags = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        return False, set(), str(e)
    names: set[str] = set()
    for model in tags.get("models", []):
        name = str(model.get("name") or "")
        if name:
            names.add(name)
            names.add(name.split(":", 1)[0])
    return True, names, None


def ollama_has_model(model: str, names: set[str]) -> bool:
    return model in names or model.split(":", 1)[0] in names


def model_by_key(key: str) -> ModelSpec | None:
    for spec in MODEL_REGISTRY:
        if spec.key == key:
            return spec
    return None


def hf_model_status(repo: str) -> dict[str, Any]:
    """Return a small status dict for a Hugging Face cache entry."""
    repo_dir = hf_repo_dir(repo)
    blobs = repo_dir / "blobs"
    snapshots = repo_dir / "snapshots"
    status: dict[str, Any] = {
        "repo": repo,
        "path": str(repo_dir),
        "exists": repo_dir.exists(),
        "ready": False,
        "reason": "",
        "bytes": 0,
        "incomplete_blobs": 0,
        "snapshots": 0,
    }
    if not repo_dir.exists():
        status["reason"] = "missing cache directory"
        return status
    if blobs.exists():
        files = [p for p in blobs.iterdir() if p.is_file()]
        status["bytes"] = sum(p.stat().st_size for p in files)
        status["incomplete_blobs"] = len(list(blobs.glob("*.incomplete")))
    if snapshots.exists():
        snapshot_dirs = [p for p in snapshots.iterdir() if p.is_dir()]
        status["snapshots"] = len(snapshot_dirs)
        for snapshot in snapshot_dirs:
            weights = (
                list(snapshot.rglob("*.safetensors"))
                + list(snapshot.rglob("*.bin"))
                + list(snapshot.rglob("*.npz"))
            )
            if weights and all(p.exists() and p.stat().st_size > 1024 for p in weights):
                status["ready"] = True
                status["reason"] = "ready via snapshot weights"
                return status
    if status["incomplete_blobs"]:
        status["reason"] = f"{status['incomplete_blobs']} incomplete blob(s)"
    elif status["bytes"] > 100 * 1024 * 1024:
        status["ready"] = True
        status["reason"] = "large cached blobs present"
    else:
        status["reason"] = "no usable weights found"
    return status


def ffprobe_json(path: Path) -> dict[str, Any]:
    raw = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
        check=True,
        capture_output=True,
        text=True,
        env=child_env(),
    ).stdout
    return json.loads(raw)


def validate_png(path: Path, *, width: int | None = None, height: int | None = None, min_bytes: int = 1024) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"missing PNG: {path}")
    size = path.stat().st_size
    if size < min_bytes:
        raise ValueError(f"PNG too small: {path} ({size} bytes)")
    with path.open("rb") as f:
        if f.read(8) != b"\x89PNG\r\n\x1a\n":
            raise ValueError(f"not a PNG: {path}")
    try:
        from PIL import Image

        with Image.open(path) as img:
            actual_w, actual_h = img.size
    except Exception as e:  # pragma: no cover - exercised in integration
        raise ValueError(f"PNG failed to decode: {path}: {e}") from e
    # mflux/FLUX VAE rounds output dimensions to multiples of 16 (the
    # 8× VAE × 2× patch downsample). 1080→1072, 1152→1152, 720→720, etc.
    # Allow a ±16-px tolerance on either dimension so non-aligned requests
    # don't fail validation just because the model rounded.
    if width is not None and abs(actual_w - width) > 16:
        raise ValueError(f"PNG width mismatch: {path} got {actual_w}, expected ~{width}")
    if height is not None and abs(actual_h - height) > 16:
        raise ValueError(f"PNG height mismatch: {path} got {actual_h}, expected ~{height}")
    return {"path": str(path), "bytes": size, "width": actual_w, "height": actual_h}


def validate_audio(path: Path, *, min_duration: float = 0.05) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size < 1024:
        raise ValueError(f"missing/tiny audio: {path}")
    info = ffprobe_json(path)
    audio_streams = [s for s in info.get("streams", []) if s.get("codec_type") == "audio"]
    if not audio_streams:
        raise ValueError(f"audio file has no audio stream: {path}")
    duration = float(info.get("format", {}).get("duration") or 0)
    if duration < min_duration:
        raise ValueError(f"audio duration too short: {path} ({duration:.2f}s)")
    return {"path": str(path), "duration": duration, "audio_streams": len(audio_streams)}


def validate_video(
    path: Path,
    *,
    expected_duration: float | None = None,
    max_duration_delta: float = 0.5,
    require_audio: bool = True,
) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size < 4096:
        raise ValueError(f"missing/tiny video: {path}")
    info = ffprobe_json(path)
    streams = info.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not video_streams:
        raise ValueError(f"video file has no video stream: {path}")
    if require_audio and not audio_streams:
        raise ValueError(f"video file has no audio stream: {path}")
    duration = float(info.get("format", {}).get("duration") or 0)
    if duration <= 0:
        raise ValueError(f"video duration invalid: {path}")
    if expected_duration is not None and abs(duration - expected_duration) > max_duration_delta:
        raise ValueError(
            f"video duration mismatch: {path} got {duration:.2f}s, expected {expected_duration:.2f}s"
        )
    return {
        "path": str(path),
        "duration": duration,
        "video_streams": len(video_streams),
        "audio_streams": len(audio_streams),
    }


def ffmpeg_filter_escape(value: str | Path) -> str:
    text = str(value)
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


class ResourceLock:
    """Cross-process advisory lock for expensive local resources."""

    def __init__(self, name: str):
        self.name = name
        self.path = FORGE_STATE_HOME / "locks" / f"{name}.lock"
        self._fh = None
        self.wait_seconds = 0.0

    def __enter__(self) -> "ResourceLock":
        import fcntl

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            self.path = Path(tempfile.gettempdir()) / "forge" / "locks" / f"{self.name}.lock"
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = self.path.open("a+")
        start = time.monotonic()
        fcntl.flock(self._fh, fcntl.LOCK_EX)
        self.wait_seconds = time.monotonic() - start
        self._fh.seek(0)
        self._fh.truncate()
        self._fh.write(json.dumps({"resource": self.name, "pid": os.getpid(), "acquired_at": now_iso()}) + "\n")
        self._fh.flush()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        import fcntl

        if self._fh is not None:
            with contextlib.suppress(Exception):
                fcntl.flock(self._fh, fcntl.LOCK_UN)
                self._fh.close()
            self._fh = None


class JobStore:
    def __init__(self, path: Path | None = None):
        self.path = path or FORGE_STATE_HOME / "jobs.sqlite"
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except PermissionError:
            self.path = Path(tempfile.gettempdir()) / "forge" / "jobs.sqlite"
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init(self) -> None:
        with contextlib.closing(self.connect()) as con:
            with con:
                con.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      kind TEXT NOT NULL,
                      input_path TEXT NOT NULL,
                      output_path TEXT,
                      status TEXT NOT NULL,
                      profile TEXT,
                      attempts INTEGER NOT NULL DEFAULT 0,
                      metadata_json TEXT NOT NULL DEFAULT '{}',
                      error TEXT,
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_jobs_status_updated ON jobs(status, updated_at);
                    CREATE TABLE IF NOT EXISTS job_steps (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      job_id INTEGER NOT NULL,
                      step TEXT NOT NULL,
                      status TEXT NOT NULL,
                      seconds REAL,
                      metadata_json TEXT NOT NULL DEFAULT '{}',
                      error TEXT,
                      created_at TEXT NOT NULL,
                      updated_at TEXT NOT NULL,
                      FOREIGN KEY(job_id) REFERENCES jobs(id)
                    );
                    """
                )

    def create_job(
        self,
        kind: str,
        input_path: str,
        output_path: str | None = None,
        *,
        profile: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        ts = now_iso()
        with contextlib.closing(self.connect()) as con:
            with con:
                cur = con.execute(
                    """
                    INSERT INTO jobs(kind, input_path, output_path, status, profile, metadata_json, created_at, updated_at)
                    VALUES (?, ?, ?, 'running', ?, ?, ?, ?)
                    """,
                    (kind, input_path, output_path, profile, json.dumps(metadata or {}), ts, ts),
                )
                return int(cur.lastrowid)

    def finish_job(self, job_id: int, status: str, error: str | None = None) -> None:
        ts = now_iso()
        with contextlib.closing(self.connect()) as con:
            with con:
                con.execute(
                    "UPDATE jobs SET status=?, error=?, updated_at=? WHERE id=?",
                    (status, error, ts, job_id),
                )

    def recent_jobs(self, limit: int = 12) -> list[dict[str, Any]]:
        with contextlib.closing(self.connect()) as con:
            rows = con.execute(
                "SELECT * FROM jobs ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def summary(self) -> dict[str, Any]:
        with contextlib.closing(self.connect()) as con:
            rows = con.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status").fetchall()
        return {row["status"]: row["n"] for row in rows}


def tool_status(name: str, args: Iterable[str]) -> dict[str, Any]:
    env = child_env()
    path = shutil.which(name, path=env["PATH"])
    if not path:
        return {"name": name, "ok": False, "path": None, "reason": "not on PATH"}
    try:
        subprocess.run([path, *args], capture_output=True, check=True, timeout=15, env=env)
        return {"name": name, "ok": True, "path": path}
    except Exception as e:
        return {"name": name, "ok": False, "path": path, "reason": str(e)}


def executable_status(name: str) -> dict[str, Any]:
    path = shutil.which(name, path=child_env()["PATH"])
    if not path:
        return {"name": name, "ok": False, "path": None, "reason": "not on PATH"}
    return {"name": name, "ok": True, "path": path, "reason": "executable present"}


def hardware_summary() -> dict[str, Any]:
    try:
        out = subprocess.run(
            ["system_profiler", "SPHardwareDataType", "SPDisplaysDataType"],
            capture_output=True,
            text=True,
            check=True,
            timeout=20,
        ).stdout
    except Exception as e:
        return {"ok": False, "reason": str(e)}
    fields: dict[str, Any] = {"ok": True}
    for line in out.splitlines():
        stripped = line.strip()
        for key in ("Chip", "Total Number of Cores", "Memory", "Metal"):
            if stripped.startswith(key + ":"):
                value = stripped.split(":", 1)[1].strip()
                fields.setdefault(key, value)
    return fields


def doctor(deep: bool = False, repair: bool = False) -> dict[str, Any]:
    configure_environment()
    if repair:
        for path in (MODELS_HOME, HF_HOME, HF_HOME / "hub", FORGE_STATE_HOME, PIPELINE_HOME):
            path.mkdir(parents=True, exist_ok=True)
    report: dict[str, Any] = {
        "generated_at": now_iso(),
        "paths": {
            "forge_home": str(FORGE_HOME),
            "models_home": str(MODELS_HOME),
            "hf_home": str(HF_HOME),
            "hf_hub_cache": str(HF_HOME / "hub"),
            "state_home": str(FORGE_STATE_HOME),
            "pipeline_home": str(PIPELINE_HOME),
            "parent_hf_home_env": ENV_HF_HOME,
            "active_hf_home_env": os.environ.get("HF_HOME"),
            "models_home_env": os.environ.get("MODELS_HOME"),
        },
        "tools": [
            tool_status("ffmpeg", ["-version"]),
            tool_status("ffprobe", ["-version"]),
            executable_status("mflux-generate"),
            executable_status("mlx_whisper"),
            tool_status("ollama", ["--version"]),
        ],
        "ollama_models": [],
        "models": [],
        "hardware": hardware_summary() if deep else {},
        "issues": [],
        "repairs": [],
    }
    ollama_up, ollama_names, ollama_reason = ollama_model_names(timeout=5)
    required_ollama = (
        (OLLAMA_MODEL, "local briefing/analyze"),
        (TRANSLATE_MODEL, "local audio/caption translation"),
    )
    for model_name, required_for in required_ollama:
        status = {
            "name": model_name,
            "required_for": required_for,
            "ready": ollama_up and ollama_has_model(model_name, ollama_names),
            "reason": "present" if ollama_up and ollama_has_model(model_name, ollama_names) else (ollama_reason or "not in ollama list"),
        }
        report["ollama_models"].append(status)
        if not status["ready"]:
            report["issues"].append(f"Ollama model {model_name} missing/unready for {required_for}: {status['reason']}")
    if ENV_HF_HOME and Path(ENV_HF_HOME).expanduser().resolve() != HF_HOME:
        report["issues"].append(
            f"parent shell HF_HOME points at {ENV_HF_HOME}; Forge child processes use {HF_HOME}"
        )
    for tool in report["tools"]:
        if not tool["ok"] and tool["name"] in {"ffmpeg", "ffprobe", "mflux-generate", "mlx_whisper"}:
            report["issues"].append(f"{tool['name']} is not healthy: {tool.get('reason', 'not found')}")
    for spec in MODEL_REGISTRY:
        if spec.backend == "hf":
            status = hf_model_status(spec.repo)
            status.update({"key": spec.key, "role": spec.role, "required_for": spec.required_for})
            report["models"].append(status)
            if not status["ready"] and spec.required_for.startswith(("process-video", "thumbnail", "forge edit")):
                report["issues"].append(f"{spec.key} missing/unready for {spec.required_for}: {status['reason']}")
    if repair:
        shell_profile = Path.home() / ".zprofile"
        export_line = f'export HF_HOME="{HF_HOME}"\n'
        with contextlib.suppress(Exception):
            existing = shell_profile.read_text() if shell_profile.exists() else ""
            if "export HF_HOME=" not in existing:
                with shell_profile.open("a", encoding="utf-8") as f:
                    f.write("\n# Forge canonical model cache\n")
                    f.write(f'export MODELS_HOME="{MODELS_HOME}"\n')
                    f.write(export_line)
                report["repairs"].append(f"added HF_HOME/MODELS_HOME exports to {shell_profile}")
    return report


def write_json(path: Path, obj: Any) -> Path:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        path = Path(tempfile.gettempdir()) / "forge" / path.name
        path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def write_text(path: Path, text: str) -> Path:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except PermissionError:
        path = Path(tempfile.gettempdir()) / "forge" / path.name
        path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
    return path


configure_environment()
