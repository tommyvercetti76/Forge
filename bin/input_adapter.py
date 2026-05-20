"""input_adapter — one-call ingestion of text, .txt, .pdf, .rtf, or audio.

A single `read_as_text()` function returns plain text + metadata for any
supported source. This is the foundation for the Translation Studio UI
(forge_web /translate tab) and is reused by `audiobook.py` for RTF parsing.

Design rules:
  * No new HARD deps. pdfplumber and mlx_whisper are OPTIONAL — if absent,
    the corresponding dispatch raises a clear ImportError; the rest of the
    module stays usable.
  * RTF parsing reuses `audiobook.parse_rtf` rather than re-implementing it.
  * Output shape is identical across dispatches so downstream code can be
    written once.

Return shape (every dispatch):
    {
        "text": str,                # extracted plain text
        "source_kind": str,         # one of: text|txt|rtf|pdf|audio
        "length_chars": int,        # len(text)
        "length_words": int,        # len(text.split())
        "sha256": str,              # hex digest of the source bytes
        "metadata": {...},          # source_kind-specific extras
    }
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Literal

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))


SourceKind = Literal["auto", "text", "txt", "pdf", "rtf", "audio"]

_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aiff", ".flac"}


def _envelope(text: str, source_kind: str, source_bytes: bytes, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Wrap an extracted text into the standard return shape."""
    return {
        "text": text,
        "source_kind": source_kind,
        "length_chars": len(text),
        "length_words": len(text.split()),
        "sha256": hashlib.sha256(source_bytes).hexdigest(),
        "metadata": metadata or {},
    }


def _read_text_file(path: Path) -> str:
    """UTF-8 read with latin-1 fallback for malformed bytes."""
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="latin-1")


def _read_pdf(path: Path) -> tuple[str, dict[str, Any]]:
    """Extract text from a PDF.

    Tries pdfplumber first (page-by-page), falls back to subprocess pdftotext.
    Raises ImportError with a clear install hint if neither is available.
    """
    try:
        import pdfplumber  # type: ignore
    except ImportError:
        pdfplumber = None  # type: ignore

    if pdfplumber is not None:
        pages: list[str] = []
        with pdfplumber.open(str(path)) as pdf:
            for page in pdf.pages:
                pages.append(page.extract_text() or "")
        text = "\n\n".join(pages).strip()
        return text, {"page_count": len(pages), "extractor": "pdfplumber"}

    # Fallback: pdftotext CLI via stdin
    try:
        cp = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            capture_output=True,
            text=True,
            check=True,
        )
        return cp.stdout.strip(), {"page_count": None, "extractor": "pdftotext"}
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    raise ImportError("install pdfplumber: pip install pdfplumber")


def _read_audio(path: Path) -> tuple[str, dict[str, Any]]:
    """Transcribe audio using mlx_whisper CLI.

    Runs `mlx_whisper <path> --output-format json --output-dir <tempdir>`,
    parses the resulting JSON sidecar, and returns the `.text` field plus
    detected language and duration in metadata.
    """
    with tempfile.TemporaryDirectory(prefix="forge_whisper_") as td:
        out_dir = Path(td)
        try:
            subprocess.run(
                [
                    "mlx_whisper", str(path),
                    "--output-format", "json",
                    "--output-dir", str(out_dir),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except FileNotFoundError:
            raise ImportError(
                "mlx_whisper not found on PATH. Install with: pip install mlx-whisper"
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"mlx_whisper failed on {path}: {exc.stderr or exc.stdout or exc}"
            )

        # mlx_whisper names the output after the input stem
        json_path = out_dir / f"{path.stem}.json"
        if not json_path.exists():
            # Fall back: pick the first .json in the tempdir
            candidates = list(out_dir.glob("*.json"))
            if not candidates:
                raise RuntimeError(f"mlx_whisper produced no JSON in {out_dir}")
            json_path = candidates[0]

        payload = json.loads(json_path.read_text(encoding="utf-8"))

    text = (payload.get("text") or "").strip()
    metadata: dict[str, Any] = {}
    if "language" in payload:
        metadata["language"] = payload["language"]
    segments = payload.get("segments") or []
    if segments:
        try:
            duration_s = float(segments[-1].get("end") or 0.0)
            if duration_s > 0:
                metadata["duration_s"] = round(duration_s, 2)
        except (TypeError, ValueError):
            pass
    metadata["segments"] = len(segments)
    return text, metadata


def read_as_text(
    source: str | Path,
    *,
    kind: SourceKind = "auto",
) -> dict[str, Any]:
    """Ingest any supported source and return plain text + metadata.

    Args:
        source: A file path (str or Path) OR a raw text string. For "auto",
            the dispatch looks at the suffix and checks whether the string
            points to an existing file.
        kind:   Override the auto-detection. One of:
            "auto" (default), "text", "txt", "pdf", "rtf", "audio".

    Returns:
        A dict with keys: text, source_kind, length_chars, length_words,
        sha256, metadata.

    Raises:
        FileNotFoundError: when an explicit file-kind is requested or the
            auto-detected suffix maps to a file dispatch but the path is
            missing.
        ImportError: when a required optional dep (pdfplumber, mlx_whisper)
            is unavailable for the requested dispatch.
    """
    # ── kind="text": raw passthrough, no path checks. ──
    if kind == "text":
        text = str(source)
        return _envelope(text, "text", text.encode("utf-8"))

    source_path: Path | None = None
    if isinstance(source, Path):
        source_path = source
    elif isinstance(source, str):
        # Heuristic: treat as a file path if the string has a known file
        # suffix OR contains a path separator + is short + single-line.
        # A multi-line string with no separator is almost certainly raw text.
        known_suffixes = _AUDIO_SUFFIXES | {".txt", ".pdf", ".rtf"}
        has_known_suffix = source.lower().endswith(tuple(known_suffixes))
        looks_like_path = (
            (has_known_suffix or "/" in source or "\\" in source)
            and "\n" not in source
            and len(source) < 4096
        )
        if looks_like_path:
            candidate = Path(source).expanduser()
            if candidate.exists():
                source_path = candidate
            elif kind != "auto" or has_known_suffix:
                # File-kind override OR a known suffix on a missing path →
                # surface a clear FileNotFoundError below instead of silently
                # treating the path-looking string as raw text.
                source_path = candidate

    # ── kind="auto" + string that isn't a valid file path → raw text. ──
    if kind == "auto" and source_path is None:
        text = str(source)
        return _envelope(text, "text", text.encode("utf-8"))

    if source_path is None:
        # File kind requested but we couldn't form a path
        raise FileNotFoundError(f"input_adapter: source is not a usable file path: {source!r}")

    # Resolve dispatch from kind override OR suffix
    suffix = source_path.suffix.lower()
    dispatch: str
    if kind == "auto":
        if suffix == ".txt":
            dispatch = "txt"
        elif suffix == ".rtf":
            dispatch = "rtf"
        elif suffix == ".pdf":
            dispatch = "pdf"
        elif suffix in _AUDIO_SUFFIXES:
            dispatch = "audio"
        else:
            # Unknown suffix → treat as text file
            dispatch = "txt"
    else:
        dispatch = kind  # type: ignore[assignment]

    if not source_path.exists():
        raise FileNotFoundError(f"input_adapter: file not found: {source_path}")

    if dispatch == "txt":
        text = _read_text_file(source_path)
        return _envelope(
            text.strip(),
            "txt",
            source_path.read_bytes(),
            {"path": str(source_path)},
        )

    if dispatch == "rtf":
        # Reuse the existing audiobook.parse_rtf — DON'T re-implement.
        from audiobook import parse_rtf
        text = parse_rtf(source_path)
        return _envelope(
            text,
            "rtf",
            source_path.read_bytes(),
            {"path": str(source_path)},
        )

    if dispatch == "pdf":
        text, extra = _read_pdf(source_path)
        meta = {"path": str(source_path)}
        meta.update(extra)
        return _envelope(text, "pdf", source_path.read_bytes(), meta)

    if dispatch == "audio":
        text, extra = _read_audio(source_path)
        meta = {"path": str(source_path)}
        meta.update(extra)
        return _envelope(text, "audio", source_path.read_bytes(), meta)

    raise ValueError(f"input_adapter: unknown dispatch kind: {dispatch!r}")


__all__ = ["read_as_text"]
