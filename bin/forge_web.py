#!/usr/bin/env python3
"""Local web wizard for Forge.

This is intentionally dependency-light: stdlib HTTP server, local-only bind by
default, and child processes still run the normal Forge CLI commands.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import signal
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

try:
    import psutil  # type: ignore
    _PSUTIL = True
except ImportError:
    psutil = None  # type: ignore
    _PSUTIL = False

import forge_gallery
from forge_runtime import FORGE_STATE_HOME, child_env


HERE = Path(__file__).resolve().parent
FORGE_HOME = HERE.parent.resolve()
FORGE_BIN = HERE / "forge.py"
BRAND_DIR = FORGE_HOME / "brand"
PRESETS_DIR = BRAND_DIR / "presets"
VOICES_FILE = BRAND_DIR / "voices.json"
SERIES_DIR = FORGE_HOME / "series"
DEFAULT_OUTPUT_ROOT = Path.home() / "Desktop" / "forge-test"
WEB_RUNS_DIR = FORGE_STATE_HOME / "web-runs"
PROCESS_VIDEO_BIN = HERE / "process-video.py"
AUDIOBOOK_BIN = HERE / "audiobook.py"
PROCESS_VIDEO_QUALITIES = ["fast", "good", "best", "cool", "balanced", "max"]
AUDIOBOOK_BEDS = ["none", "radio-static", "vinyl-crackle", "warm-hum"]
AUDIOBOOK_MODES = ["normal", "asmr"]
AUDIOBOOK_ENGINES = ["kokoro", "sarvam"]

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _append_jsonl(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _expand(path: str | None) -> Path | None:
    if not path:
        return None
    return Path(path).expanduser().resolve()


def _display_path(path: Path) -> str:
    home = Path.home().resolve()
    try:
        rel = path.resolve().relative_to(home)
        return "~/" + str(rel)
    except ValueError:
        return str(path)


def _safe_stat(path: Path) -> dict[str, Any]:
    st = path.stat()
    return {
        "path": str(path),
        "display": _display_path(path),
        "name": path.name,
        "is_dir": path.is_dir(),
        "size": st.st_size if path.is_file() else None,
        "mtime": st.st_mtime,
        "mime": mimetypes.guess_type(str(path))[0] or "application/octet-stream",
    }


def _roots() -> list[dict[str, str]]:
    candidates = [
        ("Home", Path.home()),
        ("Desktop", Path.home() / "Desktop"),
        ("Pictures", Path.home() / "Pictures"),
        ("Downloads", Path.home() / "Downloads"),
        ("Movies", Path.home() / "Movies"),
        ("Music", Path.home() / "Music"),
        ("Forge", FORGE_HOME),
        ("Temp", Path("/private/tmp")),
    ]
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for label, path in candidates:
        try:
            resolved = path.expanduser().resolve()
        except OSError:
            continue
        if resolved.exists() and str(resolved) not in seen:
            seen.add(str(resolved))
            out.append({"label": label, "path": str(resolved), "display": _display_path(resolved)})
    return out


def _scan_artifacts(watch_dirs: list[str], started_at: float, limit: int = 240) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in watch_dirs:
        root = _expand(raw)
        if root is None:
            continue
        if root.is_file():
            roots = [root]
        elif root.exists():
            roots = [root]
        else:
            roots = [root.parent]
        for base in roots:
            if not base.exists():
                continue
            if base.is_file():
                candidates = [base]
            else:
                candidates = []
                for current, dirs, files in os.walk(base):
                    current_path = Path(current)
                    depth = len(current_path.relative_to(base).parts) if current_path != base else 0
                    if depth >= 4:
                        dirs[:] = []
                    for name in files:
                        candidates.append(current_path / name)
                    if len(candidates) >= limit:
                        break
            for path in candidates:
                try:
                    if not path.is_file():
                        continue
                    resolved = path.resolve()
                    if str(resolved) in seen:
                        continue
                    st = resolved.stat()
                    if st.st_mtime < started_at - 2:
                        continue
                    seen.add(str(resolved))
                    item = _safe_stat(resolved)
                    item["url"] = "/api/file?path=" + urllib.parse.quote(str(resolved))
                    artifacts.append(item)
                except OSError:
                    continue
    artifacts.sort(key=lambda item: item["mtime"], reverse=True)
    return artifacts[:limit]


def _command_base() -> list[str]:
    return [sys.executable, str(FORGE_BIN)]


def _add(cmd: list[str], flag: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, str):
        value = value.strip()
        if value == "":
            return
    cmd.extend([flag, str(value)])


def _add_bool(cmd: list[str], flag: str, value: Any) -> None:
    if value is True or value == "true" or value == "on" or value == "1":
        cmd.append(flag)


def _add_repeatable(cmd: list[str], flag: str, value: Any) -> None:
    if value is None:
        return
    if isinstance(value, list):
        values = value
    else:
        values = re.split(r"[\n,]+", str(value))
    for raw in values:
        item = str(raw).strip()
        if item:
            cmd.extend([flag, item])


def _join_kv_pairs(pairs: list[tuple[str, Any]]) -> str:
    """Build a comma-separated 'k1=v1,k2=v2' string from a list of (key, value)
    tuples, skipping entries whose value is None/blank. Used by the
    coloring-page and mandala-art-page actions to synthesize --config from
    the friendly dropdowns."""
    parts: list[str] = []
    for k, v in pairs:
        if v is None:
            continue
        s = str(v).strip()
        if not s:
            continue
        parts.append(f"{k}={s}")
    return ",".join(parts)


def _payload_paths(payload: dict[str, Any], *keys: str) -> list[str]:
    paths: list[str] = []
    for key in keys:
        raw = str(payload.get(key) or "").strip()
        if raw:
            paths.append(str(Path(raw).expanduser()))
    return paths


def _watch_dirs_for(action: str, payload: dict[str, Any]) -> list[str]:
    paths: list[str] = []
    if action == "thumbnail":
        paths += _payload_paths(payload, "out", "bg")
        out = _expand(str(payload.get("out") or ""))
        if out and not str(payload.get("bg") or "").strip():
            paths.append(str(out.with_name(out.stem + "-bg.png")))
    elif action in {"edit", "voice", "video", "mandala", "folk-art"}:
        paths += _payload_paths(payload, "out")
    elif action in {"brief", "episode", "audiobook", "audiobook-simple", "childrens-book", "engine", "coloring-page", "mandala-art-page", "indian-folk-page", "stylized-cinematic-page"}:
        paths += _payload_paths(payload, "out")
        if action in {"engine", "coloring-page", "mandala-art-page", "indian-folk-page", "stylized-cinematic-page"} and not str(payload.get("out") or "").strip():
            paths.append(str(DEFAULT_OUTPUT_ROOT / "engine-renders"))
        if action == "audiobook-simple" and not str(payload.get("out") or "").strip():
            paths.append(str(DEFAULT_OUTPUT_ROOT / "audiobook"))
    elif action == "audiobook-asmr":
        paths += _payload_paths(payload, "folder", "out_dir")
        folder = _expand(str(payload.get("folder") or ""))
        if folder:
            paths.append(str(folder / "output"))
    elif action == "process-video-process":
        paths += _payload_paths(payload, "out")
    elif action in {"series-new", "series-show", "series-list"}:
        paths.append(str(SERIES_DIR))
    elif action == "models-adopt":
        paths.append(str(Path.home() / "Models"))
    if not paths:
        paths.append(str(DEFAULT_OUTPUT_ROOT))

    watch_dirs: list[str] = []
    for raw in paths:
        path = Path(raw).expanduser()
        if path.suffix:
            watch_dirs.append(str(path.parent))
        else:
            watch_dirs.append(str(path if path.exists() or not path.suffix else path.parent))
    unique: list[str] = []
    for path in watch_dirs:
        if path not in unique:
            unique.append(path)
    return unique


def build_command(action: str, payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    cmd = _command_base()
    if action == "thumbnail":
        cmd.append("thumbnail")
        _add(cmd, "--preset", payload.get("preset"))
        _add(cmd, "--concept", payload.get("concept"))
        _add(cmd, "--headline", payload.get("headline"))
        _add(cmd, "--sub", payload.get("sub"))
        _add(cmd, "--bg", payload.get("bg"))
        _add(cmd, "--seed", payload.get("seed"))
        _add(cmd, "--series", payload.get("series"))
        _add(cmd, "--frame-offset", payload.get("frame_offset"))
        _add_bool(cmd, "--draft", payload.get("draft"))
        _add(cmd, "--profile", payload.get("profile"))
        _add(cmd, "--steps", payload.get("steps"))
        _add_repeatable(cmd, "--lora", payload.get("lora"))
        _add_repeatable(cmd, "--lora-scale", payload.get("lora_scale"))
        _add(cmd, "--out", payload.get("out"))
    elif action == "brief":
        cmd.append("brief")
        _add(cmd, "--topic", payload.get("topic"))
        _add(cmd, "--preset", payload.get("preset"))
        _add(cmd, "--voice", payload.get("voice"))
        _add(cmd, "--series", payload.get("series"))
        _add_bool(cmd, "--draft", payload.get("draft"))
        _add(cmd, "--profile", payload.get("profile"))
        _add(cmd, "--steps", payload.get("steps"))
        _add(cmd, "--translate", payload.get("translate"))
        _add_repeatable(cmd, "--lora", payload.get("lora"))
        _add_repeatable(cmd, "--lora-scale", payload.get("lora_scale"))
        _add_bool(cmd, "--video", payload.get("video"))
        _add(cmd, "--out", payload.get("out"))
    elif action == "engine":
        cmd.extend(["engine", "render"])
        _add(cmd, "--recipe", payload.get("recipe"))
        _add(cmd, "--subject", payload.get("subject"))
        _add(cmd, "--config", payload.get("config"))
        _add(cmd, "--negative", payload.get("negative"))
        _add(cmd, "--seeds", payload.get("seeds"))
        _add_bool(cmd, "--refine", payload.get("refine"))
        _add(cmd, "--refine-strength", payload.get("refine_strength"))
        _add_bool(cmd, "--hi-res", payload.get("hi_res"))
        _add_bool(cmd, "--ultra-res", payload.get("ultra_res"))
        _add(cmd, "--width", payload.get("width"))
        _add(cmd, "--height", payload.get("height"))
        _add(cmd, "--guidance", payload.get("guidance"))
        _add(cmd, "--seed", payload.get("seed"))
        _add(cmd, "--from-image", payload.get("from_image"))
        _add(cmd, "--from-image-strength", payload.get("from_image_strength"))
        _add_bool(cmd, "--draft", payload.get("draft"))
        _add(cmd, "--profile", payload.get("profile"))
        _add(cmd, "--quantize", payload.get("quantize"))
        _add(cmd, "--upscale", payload.get("upscale"))
        _add_bool(cmd, "--no-default-loras", payload.get("no_default_loras"))
        _add(cmd, "--out", payload.get("out"))
        engine_name = str(payload.get("name") or "").strip()
        if engine_name:
            cmd.append(engine_name)
    elif action == "create":
        # Unified Create page — dispatches to the per-engine handler based on
        # payload.style. The 4 per-engine page handlers are kept as-is so the
        # legacy sidebar entries still work; "create" just routes to one of
        # them with the same payload.
        style = str(payload.get("style") or "").strip()
        dispatch = {
            "childrens-coloring-book":  "coloring-page",
            "mandala-art":              "mandala-art-page",
            "indian-classical":         "indian-folk-page",
            "stylized-cinematic":       "stylized-cinematic-page",
        }
        target = dispatch.get(style)
        if not target:
            sys.exit(red(f"unknown style {style!r} (expected one of {sorted(dispatch)})"))
        return build_command(target, payload)
    elif action == "coloring-page":
        cmd.extend(["engine", "render", "childrens-coloring-book"])
        _add(cmd, "--recipe", payload.get("recipe"))
        _add(cmd, "--subject", payload.get("subject"))
        # Synthesize --config from the friendly dropdowns. Recipes (if set)
        # already supply these; CLI overrides win, so dropdowns layered on a
        # recipe behave as overrides.
        cb_config = _join_kv_pairs([
            ("style.tradition",                payload.get("cb_tradition")),
            ("style.age_range",                payload.get("cb_age_range")),
            ("scene.environmental_density",    payload.get("cb_density")),
            ("subject.character_archetype",    payload.get("cb_archetype")),
            ("scene.setting",                  payload.get("cb_setting")),
            ("narrative.moment",               payload.get("cb_moment")),
            ("subject.emotion",                payload.get("cb_emotion")),
            ("subject.props",                  payload.get("cb_props")),
            ("composition.character_count",    payload.get("cb_character_count")),
        ])
        _add(cmd, "--config", cb_config)
        _add(cmd, "--negative", payload.get("negative"))
        _add(cmd, "--seeds", payload.get("seeds"))
        _add(cmd, "--seed", payload.get("seed"))
        _add(cmd, "--guidance", payload.get("guidance"))
        _add_bool(cmd, "--refine", payload.get("refine"))
        _add(cmd, "--refine-strength", payload.get("refine_strength"))
        _add_bool(cmd, "--hi-res", payload.get("hi_res"))
        _add_bool(cmd, "--ultra-res", payload.get("ultra_res"))
        _add(cmd, "--width", payload.get("width"))
        _add(cmd, "--height", payload.get("height"))
        _add(cmd, "--from-image", payload.get("from_image"))
        _add(cmd, "--from-image-strength", payload.get("from_image_strength"))
        _add_bool(cmd, "--draft", payload.get("draft"))
        _add(cmd, "--profile", payload.get("profile"))
        _add(cmd, "--quantize", payload.get("quantize"))
        _add(cmd, "--upscale", payload.get("upscale"))
        _add_bool(cmd, "--no-default-loras", payload.get("no_default_loras"))
        _add(cmd, "--out", payload.get("out"))
    elif action == "indian-folk-page":
        cmd.extend(["engine", "render", "indian-classical"])
        _add(cmd, "--recipe", payload.get("recipe"))
        _add(cmd, "--subject", payload.get("subject"))
        ic_config = _join_kv_pairs([
            ("style.tradition",       payload.get("ic_tradition")),
            ("style.ground",          payload.get("ic_ground")),
            ("subject.mudra",         payload.get("ic_mudra")),
            ("subject.composition",   payload.get("ic_composition")),
        ])
        _add(cmd, "--config", ic_config)
        _add(cmd, "--negative", payload.get("negative"))
        _add(cmd, "--seeds", payload.get("seeds"))
        _add(cmd, "--seed", payload.get("seed"))
        _add(cmd, "--guidance", payload.get("guidance"))
        _add_bool(cmd, "--refine", payload.get("refine"))
        _add(cmd, "--refine-strength", payload.get("refine_strength"))
        _add_bool(cmd, "--hi-res", payload.get("hi_res"))
        _add_bool(cmd, "--ultra-res", payload.get("ultra_res"))
        _add(cmd, "--width", payload.get("width"))
        _add(cmd, "--height", payload.get("height"))
        _add(cmd, "--from-image", payload.get("from_image"))
        _add(cmd, "--from-image-strength", payload.get("from_image_strength"))
        _add_bool(cmd, "--draft", payload.get("draft"))
        _add(cmd, "--profile", payload.get("profile"))
        _add(cmd, "--quantize", payload.get("quantize"))
        _add(cmd, "--upscale", payload.get("upscale"))
        _add_bool(cmd, "--no-default-loras", payload.get("no_default_loras"))
        _add(cmd, "--out", payload.get("out"))
    elif action == "mandala-art-page":
        cmd.extend(["engine", "render", "mandala-art"])
        _add(cmd, "--recipe", payload.get("recipe"))
        _add(cmd, "--subject", payload.get("subject"))
        ma_config = _join_kv_pairs([
            ("style.tradition",       payload.get("ma_tradition")),
            ("subject.treatment",     payload.get("ma_treatment")),
            ("style.symmetry",        payload.get("ma_symmetry")),
            ("style.complexity",      payload.get("ma_complexity")),
            ("composition.border",    payload.get("ma_border")),
        ])
        _add(cmd, "--config", ma_config)
        _add(cmd, "--negative", payload.get("negative"))
        _add(cmd, "--seeds", payload.get("seeds"))
        _add(cmd, "--seed", payload.get("seed"))
        _add(cmd, "--guidance", payload.get("guidance"))
        _add_bool(cmd, "--refine", payload.get("refine"))
        _add(cmd, "--refine-strength", payload.get("refine_strength"))
        _add_bool(cmd, "--hi-res", payload.get("hi_res"))
        _add_bool(cmd, "--ultra-res", payload.get("ultra_res"))
        _add(cmd, "--width", payload.get("width"))
        _add(cmd, "--height", payload.get("height"))
        _add(cmd, "--from-image", payload.get("from_image"))
        _add(cmd, "--from-image-strength", payload.get("from_image_strength"))
        _add_bool(cmd, "--draft", payload.get("draft"))
        _add(cmd, "--profile", payload.get("profile"))
        _add(cmd, "--quantize", payload.get("quantize"))
        _add(cmd, "--upscale", payload.get("upscale"))
        _add_bool(cmd, "--no-default-loras", payload.get("no_default_loras"))
        _add(cmd, "--out", payload.get("out"))
    elif action == "stylized-cinematic-page":
        cmd.extend(["engine", "render", "stylized-cinematic"])
        _add(cmd, "--recipe", payload.get("recipe"))
        _add(cmd, "--subject", payload.get("subject"))
        sc_config = _join_kv_pairs([
            ("style.tradition",             payload.get("sc_tradition")),
            ("light.time_of_day",           payload.get("sc_time_of_day")),
            ("light.sky_state",             payload.get("sc_sky_state")),
            ("light.twinkles_and_glow",     payload.get("sc_twinkles")),
            ("light.atmospheric_medium",    payload.get("sc_atmosphere")),
        ])
        _add(cmd, "--config", sc_config)
        _add(cmd, "--negative", payload.get("negative"))
        _add(cmd, "--seeds", payload.get("seeds"))
        _add(cmd, "--seed", payload.get("seed"))
        _add(cmd, "--guidance", payload.get("guidance"))
        _add_bool(cmd, "--refine", payload.get("refine"))
        _add(cmd, "--refine-strength", payload.get("refine_strength"))
        _add_bool(cmd, "--hi-res", payload.get("hi_res"))
        _add_bool(cmd, "--ultra-res", payload.get("ultra_res"))
        _add(cmd, "--width", payload.get("width"))
        _add(cmd, "--height", payload.get("height"))
        _add(cmd, "--from-image", payload.get("from_image"))
        _add(cmd, "--from-image-strength", payload.get("from_image_strength"))
        _add_bool(cmd, "--draft", payload.get("draft"))
        _add(cmd, "--profile", payload.get("profile"))
        _add(cmd, "--quantize", payload.get("quantize"))
        _add(cmd, "--upscale", payload.get("upscale"))
        _add_bool(cmd, "--no-default-loras", payload.get("no_default_loras"))
        _add(cmd, "--out", payload.get("out"))
    elif action == "edit":
        cmd.append("edit")
        _add(cmd, "--image", payload.get("image"))
        _add(cmd, "--preset", payload.get("preset"))
        _add(cmd, "--instruction", payload.get("instruction"))
        _add(cmd, "--strength", payload.get("strength"))
        _add(cmd, "--profile", payload.get("profile"))
        _add_bool(cmd, "--draft", payload.get("draft"))
        _add(cmd, "--steps", payload.get("steps"))
        _add(cmd, "--seed", payload.get("seed"))
        _add(cmd, "--out", payload.get("out"))
    elif action == "voice":
        cmd.append("voice")
        _add(cmd, "--preset", payload.get("preset"))
        _add(cmd, "--text", payload.get("text"))
        _add(cmd, "--translate", payload.get("translate"))
        _add(cmd, "--out", payload.get("out"))
    elif action == "video":
        cmd.append("video")
        _add(cmd, "--image", payload.get("image"))
        _add(cmd, "--audio", payload.get("audio"))
        _add_bool(cmd, "--no-kenburns", payload.get("no_kenburns"))
        _add(cmd, "--zoom-max", payload.get("zoom_max"))
        _add(cmd, "--fade-out", payload.get("fade_out"))
        _add(cmd, "--out", payload.get("out"))
    elif action == "mandala":
        cmd.append("mandala")
        _add(cmd, "--style", payload.get("style"))
        _add(cmd, "--symmetry", payload.get("symmetry"))
        _add(cmd, "--rings", payload.get("rings"))
        _add(cmd, "--complexity", payload.get("complexity"))
        _add(cmd, "--seed", payload.get("seed"))
        _add(cmd, "--width", payload.get("width"))
        _add(cmd, "--height", payload.get("height"))
        _add(cmd, "--stroke-width", payload.get("stroke_width"))
        _add(cmd, "--palette", payload.get("palette"))
        _add(cmd, "--supersample", payload.get("supersample"))
        _add_bool(cmd, "--no-mirror", payload.get("no_mirror"))
        _add(cmd, "--out", payload.get("out"))
    elif action == "childrens-book":
        cmd.append("childrens-book")
        _add(cmd, "--theme", payload.get("theme"))
        _add(cmd, "--pages", payload.get("pages"))
        _add(cmd, "--symmetry", payload.get("symmetry"))
        _add(cmd, "--rings", payload.get("rings"))
        _add(cmd, "--complexity", payload.get("complexity"))
        _add(cmd, "--seed", payload.get("seed"))
        _add(cmd, "--width", payload.get("width"))
        _add(cmd, "--height", payload.get("height"))
        _add(cmd, "--palette", payload.get("palette"))
        _add(cmd, "--supersample", payload.get("supersample"))
        _add(cmd, "--out", payload.get("out"))
    elif action == "folk-art":
        cmd.append("folk-art")
        _add(cmd, "--theme", payload.get("theme"))
        _add(cmd, "--width", payload.get("width"))
        _add(cmd, "--height", payload.get("height"))
        _add(cmd, "--complexity", payload.get("complexity"))
        _add(cmd, "--stroke-width", payload.get("stroke_width"))
        _add(cmd, "--palette", payload.get("palette"))
        _add(cmd, "--supersample", payload.get("supersample"))
        _add(cmd, "--out", payload.get("out"))
    elif action == "episode":
        cmd.append("episode")
        _add(cmd, "--book", payload.get("book"))
        _add(cmd, "--text", payload.get("text"))
        _add(cmd, "--title", payload.get("title"))
        _add(cmd, "--preset", payload.get("preset"))
        _add(cmd, "--voice", payload.get("voice"))
        _add(cmd, "--translate", payload.get("translate"))
        _add(cmd, "--segments", payload.get("segments"))
        _add(cmd, "--seconds", payload.get("seconds"))
        _add(cmd, "--shots-per-segment", payload.get("shots_per_segment"))
        _add_bool(cmd, "--draft", payload.get("draft"))
        _add(cmd, "--profile", payload.get("profile"))
        _add(cmd, "--steps", payload.get("steps"))
        _add_bool(cmd, "--no-flux", payload.get("no_flux"))
        _add(cmd, "--out", payload.get("out"))
    elif action == "audiobook":
        cmd.append("audiobook")
        _add(cmd, "--book", payload.get("book"))
        _add(cmd, "--text", payload.get("text"))
        _add(cmd, "--title", payload.get("title"))
        _add(cmd, "--voice", payload.get("voice"))
        _add(cmd, "--translate", payload.get("translate"))
        _add(cmd, "--chunk-chars", payload.get("chunk_chars"))
        _add(cmd, "--max-chunks", payload.get("max_chunks"))
        _add(cmd, "--out", payload.get("out"))
    elif action == "audiobook-simple":
        cmd.append("audiobook")
        book = str(payload.get("book") or "").strip()
        if not book:
            raise ValueError("Pick a book file (.txt / .rtf / .pdf) — required.")
        book_path = Path(book).expanduser()
        if not book_path.exists():
            raise ValueError(f"Book file not found: {book_path}")
        _add(cmd, "--book", str(book_path))
        # Title: explicit user value, else derive from filename stem.
        title = str(payload.get("title") or "").strip() or book_path.stem
        _add(cmd, "--title", title)
        _add(cmd, "--voice", payload.get("voice"))
        # Translate list — Hindi and/or Marathi, never include English in --translate
        # (the forge audiobook flow always produces English from the source text).
        translate = []
        if str(payload.get("do_hi")).lower() in {"true", "on", "1"}:
            translate.append("hi")
        if str(payload.get("do_mr")).lower() in {"true", "on", "1"}:
            translate.append("mr")
        if translate:
            cmd.extend(["--translate", ",".join(translate)])
        # Sarvam speaker overrides — pushed via env vars (the audiobook code
        # reads FORGE_SARVAM_SPEAKER and FORGE_SARVAM_SPEAKER_MR). Prepended as
        # `/usr/bin/env VAR=val python3 forge.py ...` so the subprocess inherits
        # them without touching the parent shell.
        hi_speaker = str(payload.get("sarvam_hi_speaker") or "").strip()
        mr_speaker = str(payload.get("sarvam_mr_speaker") or "").strip()
        env_overrides = []
        if hi_speaker:
            env_overrides.append(f"FORGE_SARVAM_SPEAKER={hi_speaker}")
        if mr_speaker:
            env_overrides.append(f"FORGE_SARVAM_SPEAKER_MR={mr_speaker}")
        if env_overrides:
            cmd[:0] = ["/usr/bin/env"] + env_overrides
        # Output folder — default per-book if blank
        out = str(payload.get("out") or "").strip()
        if not out:
            safe_stem = re.sub(r"[^a-zA-Z0-9._-]+", "-", title).strip("-") or "audiobook"
            out = str(DEFAULT_OUTPUT_ROOT / "audiobook" / safe_stem)
        cmd.extend(["--out", out])
        # Sensible defaults for chunking — user shouldn't have to tune these
        cmd.extend(["--chunk-chars", "1400"])
    elif action == "audiobook-asmr":
        cmd = [sys.executable, str(AUDIOBOOK_BIN)]
        _add(cmd, "--folder", payload.get("folder"))
        _add(cmd, "--rtf", payload.get("rtf"))
        _add(cmd, "--video", payload.get("video"))
        _add(cmd, "--out-dir", payload.get("out_dir"))
        _add(cmd, "--langs", payload.get("langs"))
        _add(cmd, "--max-chars", payload.get("max_chars"))
        _add(cmd, "--max-words", payload.get("max_words"))
        _add(cmd, "--batch-pages", payload.get("batch_pages"))
        _add(cmd, "--page-words", payload.get("page_words"))
        _add(cmd, "--spoken-words", payload.get("spoken_words"))
        _add(cmd, "--batches", payload.get("batches"))
        _add(cmd, "--bed", payload.get("bed"))
        _add(cmd, "--mode", payload.get("mode"))
        _add(cmd, "--english-engine", payload.get("english_engine"))
        _add(cmd, "--subtitles", payload.get("subtitles"))
        if payload.get("thumbnail") is False:
            cmd.append("--no-thumbnail")
        else:
            cmd.append("--thumbnail")
        _add(cmd, "--thumb-preset", payload.get("thumb_preset"))
        _add(cmd, "--thumb-seed", payload.get("thumb_seed"))
        _add(cmd, "--thumb-frame-at", payload.get("thumb_frame_at"))
        _add(cmd, "--sarvam-speaker", payload.get("sarvam_speaker"))
        _add(cmd, "--sarvam-speaker-mr", payload.get("sarvam_speaker_mr"))
        _add(cmd, "--sent-pause-ms", payload.get("sent_pause_ms"))
        _add(cmd, "--para-pause-ms", payload.get("para_pause_ms"))
        _add_bool(cmd, "--dry-run", payload.get("dry_run"))
    elif action == "engine-list":
        cmd.extend(["engine", "list"])
    elif action == "engine-describe":
        cmd.extend(["engine", "describe"])
        name = str(payload.get("name") or "").strip()
        if name:
            cmd.append(name)
    elif action == "engine-recipes":
        cmd.extend(["engine", "recipes"])
        _add(cmd, "--engine", payload.get("engine"))
    elif action == "list":
        cmd.append("list")
    elif action == "show":
        cmd.append("show")
        preset = str(payload.get("preset") or "").strip()
        if preset:
            cmd.append(preset)
    elif action == "series-list":
        cmd.extend(["series", "list"])
    elif action == "series-show":
        cmd.extend(["series", "show"])
        series_id = str(payload.get("id") or "").strip()
        if series_id:
            cmd.append(series_id)
    elif action == "series-new":
        cmd.extend(["series", "new"])
        series_id = str(payload.get("id") or "").strip()
        if series_id:
            cmd.append(series_id)
        _add(cmd, "--preset", payload.get("preset"))
        _add_bool(cmd, "--force", payload.get("force"))
    elif action == "setup-voices":
        cmd.append("setup-voices")
        _add_bool(cmd, "--kokoro", payload.get("kokoro"))
    elif action == "doctor":
        cmd.append("doctor")
        _add_bool(cmd, "--deep", payload.get("deep"))
        _add_bool(cmd, "--repair", payload.get("repair"))
        _add_bool(cmd, "--json", payload.get("json"))
        _add_bool(cmd, "--verbose", payload.get("verbose"))
    elif action == "status":
        cmd.append("status")
        _add(cmd, "--limit", payload.get("limit"))
    elif action == "bench":
        cmd.append("bench")
        _add_bool(cmd, "--real", payload.get("real"))
    elif action == "models-scan":
        cmd.extend(["models", "scan"])
        _add_bool(cmd, "--full", payload.get("full"))
    elif action == "models-list":
        cmd.extend(["models", "list"])
        _add_bool(cmd, "--full", payload.get("full"))
    elif action == "models-clean":
        cmd.extend(["models", "clean"])
        _add_bool(cmd, "--full", payload.get("full"))
        _add_bool(cmd, "--dry-run", payload.get("dry_run"))
        _add_bool(cmd, "--yes", payload.get("yes"))
        _add_repeatable(cmd, "--remove", payload.get("remove"))
    elif action == "models-adopt":
        cmd.extend(["models", "adopt"])
        path = str(payload.get("path") or "").strip()
        if path:
            cmd.append(path)
        _add(cmd, "--as", payload.get("as"))
        _add_bool(cmd, "--delete-source", payload.get("delete_source"))
    elif action == "process-video-warmup":
        cmd = [sys.executable, str(PROCESS_VIDEO_BIN), "warmup"]
        _add(cmd, "--quality", payload.get("quality"))
        _add_bool(cmd, "--dry-run", payload.get("dry_run"))
    elif action == "process-video-process":
        cmd = [sys.executable, str(PROCESS_VIDEO_BIN), "process"]
        video = str(payload.get("video") or "").strip()
        if video:
            cmd.append(video)
        _add(cmd, "--out", payload.get("out"))
        _add(cmd, "--quality", payload.get("quality"))
        _add_bool(cmd, "--noisy", payload.get("noisy"))
        _add_bool(cmd, "--no-burn", payload.get("no_burn"))
        _add_bool(cmd, "--no-thumbs", payload.get("no_thumbs"))
        _add(cmd, "--captions", payload.get("captions"))
        _add_bool(cmd, "--force", payload.get("force"))
        _add_bool(cmd, "--offline-skip-check", payload.get("offline_skip_check"))
    else:
        raise ValueError(f"unknown action: {action}")
    return cmd, _watch_dirs_for(action, payload)


class ResourceSampler:
    """Lightweight CPU + memory + child-process sampler for a running Job.

    Runs in its own daemon thread, polls every `interval_sec` seconds via psutil,
    and stores the latest values in `latest`. Apple Silicon doesn't expose a
    non-sudo GPU %, so we surface the heaviest child process (mflux-generate,
    ffmpeg, kokoro, etc.) — when that process is hot, the GPU is hot.
    """

    HEAVY_NAMES = (
        "mflux-generate", "mflux-generate-kontext", "mflux", "python3", "python",
        "ffmpeg", "ffprobe", "kokoro", "sarvam", "whisper",
    )

    def __init__(self, parent_pid: int, interval_sec: float = 1.0):
        self.parent_pid = parent_pid
        self.interval_sec = interval_sec
        self.latest: dict[str, Any] = {}
        self.history: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._parent: Any = None

    def start(self) -> None:
        if not _PSUTIL:
            self.latest = {"available": False, "note": "psutil not installed"}
            return
        try:
            self._parent = psutil.Process(self.parent_pid)
            # Prime cpu_percent so subsequent calls return real deltas
            psutil.cpu_percent(interval=None)
            self._parent.cpu_percent(interval=None)
        except Exception:
            self.latest = {"available": False, "note": "process gone before sampling"}
            return
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _heaviest_child(self) -> dict[str, Any] | None:
        if self._parent is None:
            return None
        try:
            kids = self._parent.children(recursive=True)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None
        heaviest: dict[str, Any] | None = None
        for p in kids:
            try:
                name = p.name()
                lower_name = name.lower()
                if not any(h in lower_name for h in self.HEAVY_NAMES):
                    # Skip light helpers (sh, less, head, etc.) unless big anyway
                    pass
                cpu = p.cpu_percent(interval=None)
                mem_mb = p.memory_info().rss / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
            if heaviest is None or cpu > heaviest["cpu"]:
                heaviest = {"name": name, "pid": p.pid, "cpu": round(cpu, 1), "mem_mb": round(mem_mb, 0)}
        return heaviest

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                cpu = psutil.cpu_percent(interval=None)
                vm = psutil.virtual_memory()
                sample = {
                    "available": True,
                    "ts": time.time(),
                    "cpu_pct": round(cpu, 1),
                    "cpu_cores": psutil.cpu_count(logical=True) or 0,
                    "mem_pct": round(vm.percent, 1),
                    "mem_used_gb": round(vm.used / (1024 ** 3), 2),
                    "mem_total_gb": round(vm.total / (1024 ** 3), 2),
                    "worker": self._heaviest_child(),
                }
                self.latest = sample
                self.history.append({"ts": sample["ts"], "cpu_pct": sample["cpu_pct"], "mem_pct": sample["mem_pct"],
                                     "worker_cpu": (sample["worker"] or {}).get("cpu", 0)})
                # cap history at 240 samples (~4 min @ 1s)
                if len(self.history) > 240:
                    self.history = self.history[-240:]
            except psutil.NoSuchProcess:
                self.latest = {"available": False, "note": "parent process exited"}
                break
            except Exception as e:
                self.latest = {"available": False, "note": f"sampler error: {e}"}
            self._stop.wait(self.interval_sec)


class Job:
    def __init__(self, job_id: int, action: str, cmd: list[str], watch_dirs: list[str]):
        self.id = job_id
        self.action = action
        self.cmd = cmd
        self.watch_dirs = watch_dirs
        self.started_at = time.time()
        self.ended_at: float | None = None
        self.returncode: int | None = None
        self.logs: list[str] = []
        self.lock = threading.Lock()
        self.proc: subprocess.Popen[str] | None = None
        self.resources: ResourceSampler | None = None
        self.progress: dict[str, Any] = {}
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.started_at))
        safe_action = re.sub(r"[^a-zA-Z0-9_.-]+", "-", action).strip("-") or "job"
        self.run_dir = WEB_RUNS_DIR / f"{stamp}-{job_id:04d}-{safe_action}"
        self.log_path = self.run_dir / "stdout.log"
        self.events_path = self.run_dir / "events.jsonl"
        self.manifest_path = self.run_dir / "manifest.json"

    def start(self) -> None:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self._event("started", {"cmd": self.cmd, "watch_dirs": self.watch_dirs})
        self._write_manifest("running")
        env = child_env({"PYTHONUNBUFFERED": "1", "FORGE_MFLUX_HEARTBEAT_SEC": os.environ.get("FORGE_MFLUX_HEARTBEAT_SEC", "15")})
        self.proc = subprocess.Popen(
            self.cmd,
            cwd=str(FORGE_HOME),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            start_new_session=True,
        )
        threading.Thread(target=self._read_output, daemon=True).start()
        threading.Thread(target=self._wait, daemon=True).start()
        # Resource sampler — tracks system CPU/Mem + heaviest child process.
        if self.proc is not None:
            self.resources = ResourceSampler(self.proc.pid)
            self.resources.start()

    def _append(self, line: str) -> None:
        clean = ANSI_RE.sub("", line.rstrip("\n"))
        with self.lock:
            self.logs.append(clean)
            if len(self.logs) > 1200:
                self.logs = self.logs[-1200:]
            self._parse_progress(clean)
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(clean + "\n")

    # Match tqdm-style mflux progress lines. mflux's carriage-return-updated
    # output gets concatenated by line-based readline, so we look for the LAST
    # "STEP/TOTAL [elapsed<eta, rate s/it|it/s]" segment in the line.
    _PROGRESS_RE = re.compile(
        r"(\d+)/(\d+)\s*\[(\d+:\d+)(?:<(\d+:\d+|\?))?,?\s*([\d.]+|\?)\s*(s/it|it/s)\]"
    )

    def _parse_progress(self, line: str) -> None:
        matches = self._PROGRESS_RE.findall(line)
        if not matches:
            return
        step_s, total_s, elapsed, eta, rate, unit = matches[-1]
        try:
            step, total = int(step_s), int(total_s)
            if total <= 0:
                return
            pct = round(100.0 * step / total, 1)
            self.progress = {
                "step": step,
                "total": total,
                "percent": pct,
                "elapsed": elapsed,
                "eta": eta or "",
                "rate": rate,
                "rate_unit": unit,
                "ts": time.time(),
            }
        except ValueError:
            return

    def _event(self, kind: str, payload: dict[str, Any] | None = None) -> None:
        _append_jsonl(self.events_path, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "kind": kind,
            "payload": payload or {},
        })

    def _issues(self) -> list[str]:
        patterns = ("traceback", " error", "error:", "failed", "timed out", "not found", "exception")
        issues: list[str] = []
        with self.lock:
            lines = list(self.logs)
        for line in lines:
            lower = line.lower()
            if any(p in lower for p in patterns):
                issues.append(line)
        if self.returncode not in (None, 0):
            issues.append(f"process exited {self.returncode}")
        deduped: list[str] = []
        for issue in issues:
            if issue not in deduped:
                deduped.append(issue)
        return deduped[-20:]

    def _write_manifest(self, status: str) -> None:
        artifacts = _scan_artifacts(self.watch_dirs, self.started_at)
        _write_json(self.manifest_path, {
            "id": self.id,
            "action": self.action,
            "status": status,
            "returncode": self.returncode,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "elapsed": round((self.ended_at or time.time()) - self.started_at, 1),
            "cmd": self.cmd,
            "cmd_display": " ".join(shlex_quote(part) for part in self.cmd),
            "watch_dirs": self.watch_dirs,
            "artifacts": artifacts,
            "issues": self._issues(),
            "paths": {
                "run_dir": str(self.run_dir),
                "stdout_log": str(self.log_path),
                "events": str(self.events_path),
                "manifest": str(self.manifest_path),
            },
        })

    def _read_output(self) -> None:
        assert self.proc is not None and self.proc.stdout is not None
        for line in self.proc.stdout:
            self._append(line)

    def _wait(self) -> None:
        assert self.proc is not None
        rc = self.proc.wait()
        with self.lock:
            self.returncode = rc
            self.ended_at = time.time()
            self.logs.append(f"forge web: process exited {rc}")
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"forge web: process exited {rc}\n")
        if self.resources is not None:
            self.resources.stop()
        self._event("finished", {"returncode": rc})
        self._write_manifest("ok" if rc == 0 else "failed")

    def stop(self) -> None:
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        self._event("stop-requested")
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except Exception:
            proc.terminate()

    def snapshot(self) -> dict[str, Any]:
        proc = self.proc
        running = proc is not None and proc.poll() is None
        with self.lock:
            logs = list(self.logs)
            returncode = self.returncode
            ended_at = self.ended_at
        status = "running" if running else ("ok" if returncode == 0 else "failed")
        issues = self._issues()
        artifacts = _scan_artifacts(self.watch_dirs, self.started_at)
        if not running:
            self._write_manifest(status)
        resources = self.resources.latest if self.resources is not None else {"available": False, "note": "no sampler"}
        with self.lock:
            progress = dict(self.progress) if self.progress else {}
        return {
            "id": self.id,
            "action": self.action,
            "status": status,
            "returncode": returncode,
            "started_at": self.started_at,
            "ended_at": ended_at,
            "elapsed": round((ended_at or time.time()) - self.started_at, 1),
            "cmd": self.cmd,
            "cmd_display": " ".join(shlex_quote(part) for part in self.cmd),
            "logs": logs,
            "watch_dirs": self.watch_dirs,
            "artifacts": artifacts,
            "issues": issues,
            "resources": resources,
            "progress": progress,
            "run_dir": str(self.run_dir),
            "log_path": str(self.log_path),
            "events_path": str(self.events_path),
            "manifest_path": str(self.manifest_path),
        }


def shlex_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)


class JobRegistry:
    def __init__(self) -> None:
        self._jobs: dict[int, Job] = {}
        self._next_id = 1
        self._lock = threading.Lock()

    def create(self, action: str, payload: dict[str, Any]) -> Job:
        cmd, watch_dirs = build_command(action, payload)
        with self._lock:
            job_id = self._next_id
            self._next_id += 1
            job = Job(job_id, action, cmd, watch_dirs)
            self._jobs[job_id] = job
        job.start()
        return job

    def get(self, job_id: int) -> Job | None:
        with self._lock:
            return self._jobs.get(job_id)

    def recent(self) -> list[dict[str, Any]]:
        with self._lock:
            jobs = list(self._jobs.values())[-20:]
        return [job.snapshot() for job in reversed(jobs)]


REGISTRY = JobRegistry()


def config_payload() -> dict[str, Any]:
    voices = _read_json(VOICES_FILE, {"presets": []}).get("presets", [])
    try:
        import mandala_engine
        import style_engines

        engines = style_engines.list_engines()
        mandala_styles = sorted(mandala_engine.MANDALA_STYLES)
        child_themes = list(mandala_engine.CHILD_THEMES)
        folk_themes = list(getattr(mandala_engine, "FOLK_ART_THEMES", ()))
        complexity = list(mandala_engine.COMPLEXITY_LEVELS)
    except Exception:
        engines, mandala_styles, child_themes, folk_themes, complexity = [], [], [], [], ["low", "medium", "max"]
    library = _read_json(BRAND_DIR / "prompts" / "library.json", {})
    # Ship recipe contents (subject + config) along with metadata so the client
    # can prefill the form when a recipe is selected — fixes the leak where
    # form defaults silently override the recipe's content.
    recipes = [
        {
            "id":          rid,
            "engine":      spec.get("engine"),
            "description": spec.get("description", ""),
            "subject":     spec.get("subject", ""),
            "config":      spec.get("config", {}) if isinstance(spec.get("config"), dict) else {},
            "seed":        spec.get("seed"),
            "guidance":    spec.get("guidance"),
        }
        for rid, spec in sorted(library.items())
        if isinstance(spec, dict)
    ]
    return {
        "home": str(Path.home()),
        "forge_home": str(FORGE_HOME),
        "default_output_root": str(DEFAULT_OUTPUT_ROOT),
        "presets": sorted(p.stem for p in PRESETS_DIR.glob("*.json")),
        "voices": [{"id": v.get("id"), "label": v.get("label") or v.get("name") or v.get("id")} for v in voices],
        "series": sorted(p.stem for p in SERIES_DIR.glob("*.json")) if SERIES_DIR.exists() else [],
        "engines": engines,
        "recipes": recipes,
        "profiles": ["", "cool", "balanced", "max"],
        "process_qualities": PROCESS_VIDEO_QUALITIES,
        "audiobook_beds": AUDIOBOOK_BEDS,
        "audiobook_modes": AUDIOBOOK_MODES,
        "audiobook_engines": AUDIOBOOK_ENGINES,
        "subtitle_modes": ["srt", "vtt", "none"],
        "mandala_styles": mandala_styles,
        "child_themes": ["all", *child_themes],
        "folk_themes": folk_themes,
        "complexity": complexity,
        # Sarvam Bulbul v3 speakers — validated against the live API on
        # 2026-05-17 by reading a 400-error response listing the supported
        # set (some older docs / pipecat references list speakers like
        # anushka / vidya / soham that are NOT in v3 — those names belong
        # to other Sarvam products). Trust this list, not the marketing.
        # Defaults: priya (Hindi female narrator) + shreya (Marathi
        # female narrator) — both confirmed in the validated set.
        "sarvam_speakers": [
            # Male voices (12)
            "shubh", "aditya", "rahul", "rohan", "amit", "dev",
            "ratan", "varun", "manan", "sumit", "kabir", "aayan",
            "ashutosh", "advait", "anand", "tarun",
            # Female voices (10)
            "priya", "neha", "pooja", "simran", "kavya", "ishita",
            "shreya", "roopa", "ritu", "tanya",
        ],
        "roots": _roots(),
    }


def browse_payload(raw_path: str | None) -> dict[str, Any]:
    path = _expand(raw_path) if raw_path else Path.home()
    if path is None:
        path = Path.home()
    if path.is_file():
        path = path.parent
    if not path.exists():
        path = Path.home()
    entries: list[dict[str, Any]] = []
    try:
        for child in sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))[:500]:
            try:
                if child.name.startswith(".") and child.name not in {".forge", ".kaayko-pipeline"}:
                    continue
                item = _safe_stat(child)
                entries.append(item)
            except OSError:
                continue
    except OSError as e:
        return {"ok": False, "error": str(e), "path": str(path), "entries": [], "roots": _roots()}
    return {
        "ok": True,
        "path": str(path),
        "display": _display_path(path),
        "parent": str(path.parent) if path.parent != path else str(path),
        "entries": entries,
        "roots": _roots(),
    }


def recorded_runs(limit: int = 40) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []
    if not WEB_RUNS_DIR.exists():
        return runs
    for manifest in sorted(WEB_RUNS_DIR.glob("*/manifest.json"), reverse=True)[:limit]:
        data = _read_json(manifest, None)
        if not isinstance(data, dict):
            continue
        # Reconcile stale "running" status — a manifest still claiming running
        # at server boot can't be alive (the process was a child of a server
        # that has since died). Mark abandoned + rewrite so it stays correct
        # across reloads.
        if data.get("status") == "running" and data.get("ended_at") is None:
            now = time.time()
            data["status"] = "abandoned"
            data["ended_at"] = now
            data["elapsed"] = round(now - data.get("started_at", now), 1)
            issues = list(data.get("issues") or [])
            note = "server shut down before this job finished"
            if note not in issues:
                issues.append(note)
            data["issues"] = issues[-20:]
            try:
                _write_json(manifest, data)
            except Exception:
                pass
        runs.append(data)
    return runs


class Handler(BaseHTTPRequestHandler):
    server_version = "ForgeWeb/0.1"

    def log_message(self, _fmt: str, *_args: Any) -> None:
        return

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _text(self, body: str, content_type: str = "text/html; charset=utf-8", status: int = 200) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/":
                self._text(INDEX_HTML)
            elif parsed.path == "/api/config":
                self._json(config_payload())
            elif parsed.path == "/api/jobs":
                self._json({"jobs": REGISTRY.recent()})
            elif parsed.path == "/api/runs":
                self._json({"runs": recorded_runs()})
            elif parsed.path.startswith("/api/jobs/"):
                job_id = int(parsed.path.rsplit("/", 1)[-1])
                job = REGISTRY.get(job_id)
                if not job:
                    self._json({"error": "job not found"}, HTTPStatus.NOT_FOUND)
                else:
                    self._json(job.snapshot())
            elif parsed.path == "/api/browse":
                self._json(browse_payload(query.get("path", [None])[0]))
            elif parsed.path == "/api/gallery":
                engine = query.get("engine", [None])[0] or None
                recipe = query.get("recipe", [None])[0] or None
                rating_raw = query.get("rating", [None])[0]
                rating = int(rating_raw) if rating_raw not in (None, "", "all") else None
                limit = int(query.get("limit", ["120"])[0])
                offset = int(query.get("offset", ["0"])[0])
                order_by = query.get("order_by", ["ts_desc"])[0]
                self._json({
                    "renders": forge_gallery.list_renders(
                        engine=engine, recipe=recipe, rating=rating,
                        limit=limit, offset=offset, order_by=order_by,
                    ),
                    "stats": forge_gallery.stats(),
                })
            elif parsed.path.startswith("/api/gallery/"):
                tail = parsed.path[len("/api/gallery/"):]
                if tail == "stats":
                    self._json(forge_gallery.stats())
                else:
                    try:
                        render_id = int(tail)
                    except ValueError:
                        self._json({"error": "invalid render id"}, HTTPStatus.BAD_REQUEST)
                        return
                    row = forge_gallery.get_render(render_id)
                    if not row:
                        self._json({"error": "render not found"}, HTTPStatus.NOT_FOUND)
                    else:
                        self._json(row)
            elif parsed.path == "/api/suggestions":
                engine = query.get("engine", [""])[0]
                if not engine:
                    self._json({"error": "engine query param required"}, HTTPStatus.BAD_REQUEST)
                    return
                self._json({"suggestion": forge_gallery.top_rated_config(engine)})
            elif parsed.path == "/api/file":
                raw = query.get("path", [""])[0]
                path = _expand(raw)
                if path is None or not path.is_file():
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(path.stat().st_size))
                self.end_headers()
                with path.open("rb") as fh:
                    while True:
                        chunk = fh.read(1024 * 256)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as e:
            self._json({"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path == "/api/jobs":
                body = self._read_body()
                action = str(body.get("action") or "").strip()
                payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
                job = REGISTRY.create(action, payload)
                self._json(job.snapshot(), HTTPStatus.CREATED)
            elif parsed.path.endswith("/stop") and parsed.path.startswith("/api/jobs/"):
                job_id = int(parsed.path.split("/")[-2])
                job = REGISTRY.get(job_id)
                if not job:
                    self._json({"error": "job not found"}, HTTPStatus.NOT_FOUND)
                else:
                    job.stop()
                    self._json({"ok": True})
            elif parsed.path == "/api/preview-command":
                # Server-side command preview — runs the same build_command()
                # that startJob would invoke, so the user sees the REAL cmd
                # (including nested forge subcommands or python script paths),
                # not a naive synthesis. Used by updateCommandPreview() in the
                # form layer, debounced on form input.
                body = self._read_body()
                action = str(body.get("action") or "").strip()
                payload = body.get("payload") if isinstance(body.get("payload"), dict) else {}
                try:
                    cmd, _env = build_command(action, payload)
                    cmd_display = " ".join(shlex_quote(p) for p in cmd)
                    self._json({"cmd_display": cmd_display})
                except SystemExit as e:
                    self._json({"cmd_display": f"# preview unavailable: {e}", "error": True})
                except Exception as e:
                    self._json({"cmd_display": f"# preview error: {type(e).__name__}: {e}", "error": True})
                return
            elif parsed.path == "/api/ratings":
                body = self._read_body()
                rid = body.get("render_id")
                rating = body.get("rating")
                notes = body.get("notes")
                if rid is None or rating is None:
                    self._json({"error": "render_id and rating required"}, HTTPStatus.BAD_REQUEST)
                    return
                forge_gallery.set_rating(int(rid), int(rating), notes if isinstance(notes, str) else None)
                self._json({"ok": True, "render": forge_gallery.get_render(int(rid))})
            elif parsed.path == "/api/reveal":
                body = self._read_body()
                path = _expand(str(body.get("path") or ""))
                if path is None or not path.exists():
                    self._json({"error": "path not found"}, HTTPStatus.NOT_FOUND)
                    return
                if sys.platform == "darwin":
                    target = path if path.is_file() else path
                    args = ["open", "-R", str(target)] if path.is_file() else ["open", str(target)]
                    subprocess.Popen(args)
                self._json({"ok": True})
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as e:
            self._json({"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_DELETE(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        try:
            if parsed.path.startswith("/api/gallery/"):
                # DELETE /api/gallery/<id>?file=1 — drop the render row from
                # the gallery DB. If ?file=1 is set, also remove the PNG +
                # sidecar from disk.
                tail = parsed.path[len("/api/gallery/"):]
                try:
                    render_id = int(tail)
                except ValueError:
                    self._json({"error": "invalid render id"}, HTTPStatus.BAD_REQUEST)
                    return
                row = forge_gallery.get_render(render_id)
                if not row:
                    self._json({"error": "render not found"}, HTTPStatus.NOT_FOUND)
                    return
                query = urllib.parse.parse_qs(parsed.query)
                delete_file = query.get("file", ["0"])[0] in {"1", "true", "yes"}
                forge_gallery.delete_render(render_id)
                if delete_file:
                    try:
                        Path(row["png_path"]).unlink(missing_ok=True)
                        Path(row["png_path"] + ".directive.json").unlink(missing_ok=True)
                    except Exception:
                        pass
                self._json({"ok": True, "deleted_file": delete_file})
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as e:
            self._json({"error": str(e)}, HTTPStatus.INTERNAL_SERVER_ERROR)


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>FORGE ▣ WIZARD</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Pixelify+Sans:wght@400;500;700&family=JetBrains+Mono:wght@400;500;700&display=swap" rel="stylesheet">
<style>
/*  FORGE WIZARD — pixel-game theme
 *  Dark-forest-tavern palette. Press Start 2P for chrome, Pixelify Sans for
 *  body, JetBrains Mono for logs/paths. Hard borders, no anti-aliasing on
 *  borders, drop shadows are pixel-stepped (no blur).
 */
:root {
  color-scheme: dark;

  /* Surfaces — deep forest */
  --bg:        #0e1714;
  --bg-deep:   #050b09;
  --surface:   #1a2925;
  --surface-2: #142220;
  --surface-3: #233a35;
  --hover:     #2a4540;

  /* Borders */
  --line:      #355048;
  --line-hi:   #4d7a6c;
  --line-dim:  #1a2925;

  /* Text */
  --ink:        #d9e8e0;
  --ink-bright: #ecf6ee;
  --muted:      #82998d;
  --muted-dim:  #5a6e64;

  /* Accents */
  --green:     #7eda6b;
  --green-dim: #4a8d3a;
  --green-deep:#2a5520;
  --blue:      #6db4e1;
  --amber:     #f0c447;
  --rose:      #e85067;
  --gold:      #d6a754;

  /* Pixel shadows (hard, no blur) */
  --shadow:       0 4px 0 var(--bg-deep);
  --shadow-press: 0 1px 0 var(--bg-deep);

  /* Type stacks */
  --font-pixel: "Press Start 2P", "Courier New", monospace;
  --font-ui:    "Pixelify Sans", "VT323", "Courier New", monospace;
  --font-mono:  "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}

* { box-sizing: border-box; }

html, body { background: var(--bg); }

body {
  margin: 0;
  min-height: 100vh;
  color: var(--ink);
  font: 16px/1.45 var(--font-ui);
  /* Subtle scanline texture — 1px every 2px, very low opacity, only the
     gentlest CRT feel without hurting readability */
  background-image:
    repeating-linear-gradient(
      0deg,
      rgba(255,255,255,0.012) 0,
      rgba(255,255,255,0.012) 1px,
      transparent 1px,
      transparent 2px
    );
  image-rendering: pixelated;
}

::selection { background: var(--green-dim); color: var(--ink-bright); }

/* Scrollbars — chunky pixel */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: var(--bg-deep); }
::-webkit-scrollbar-thumb { background: var(--surface-3); border: 2px solid var(--bg-deep); }
::-webkit-scrollbar-thumb:hover { background: var(--line-hi); }

button, input, select, textarea { font: inherit; }

/* Generic button — chunky pixel slab with hard drop shadow */
button {
  font: 10px/1 var(--font-pixel);
  letter-spacing: 1px;
  text-transform: uppercase;
  background: var(--surface);
  color: var(--ink);
  border: 2px solid var(--line);
  border-radius: 0;
  padding: 10px 14px;
  cursor: pointer;
  box-shadow: var(--shadow);
  transition: transform 60ms ease-out, box-shadow 60ms ease-out, background 60ms ease-out, border-color 60ms ease-out;
}
button:hover {
  background: var(--hover);
  border-color: var(--line-hi);
  color: var(--ink-bright);
}
button:active {
  transform: translateY(3px);
  box-shadow: var(--shadow-press);
}
button.primary {
  background: var(--green-deep);
  color: var(--green);
  border-color: var(--green-dim);
}
button.primary:hover { background: var(--green-dim); color: var(--ink-bright); border-color: var(--green); }
button.danger { color: var(--rose); border-color: var(--rose); }
button.danger:hover { background: var(--rose); color: var(--bg-deep); }
button:focus-visible {
  outline: 2px solid var(--green);
  outline-offset: 2px;
}

/* Layout grid — each column gets its own scroll context so the right
 * Process panel + the left Sidebar stay locked in view while the user
 * scrolls through a long form in the middle column. */
.app {
  display: grid;
  grid-template-columns: 296px minmax(420px, 1fr) minmax(360px, .9fr);
  height: 100vh;
  overflow: hidden;
}
.sidebar, .main, .process {
  height: 100vh;
  overflow-y: auto;
  overflow-x: hidden;
}
.sidebar {
  border-right: 2px solid var(--line);
  background: var(--surface-2);
  padding: 22px 18px;
}
.process {
  border-left: 2px solid var(--line);
}
.brand {
  font: 14px/1 var(--font-pixel);
  letter-spacing: 2px;
  color: var(--gold);
  margin-bottom: 8px;
  text-shadow: 2px 2px 0 var(--bg-deep);
}
.brand::before { content: "▣ "; color: var(--green); }
.meta {
  color: var(--muted);
  font: 11px/1.4 var(--font-mono);
  overflow-wrap: anywhere;
  letter-spacing: 0;
}
.group-title {
  margin: 26px 0 10px;
  color: var(--muted);
  font: 9px/1 var(--font-pixel);
  letter-spacing: 2px;
  padding-bottom: 6px;
  border-bottom: 2px dashed var(--line);
}
.action-list { display: grid; gap: 4px; }
.action {
  width: 100%;
  text-align: left;
  background: transparent;
  color: var(--muted);
  border: 2px solid transparent;
  box-shadow: none;
  padding: 9px 12px;
  font: 11px/1 var(--font-ui);
  letter-spacing: 0.5px;
  text-transform: none;
  white-space: pre;   /* preserve leading spaces for "  ↳" nesting */
}
.action:hover { background: var(--surface); color: var(--ink-bright); border-color: var(--line); transform: none; }
.action.active {
  background: var(--surface);
  color: var(--green);
  border-color: var(--green-dim);
  box-shadow: var(--shadow-press);
  font-weight: 700;
}
.action.active::before { content: "▶ "; color: var(--green); }

.main, .process {
  padding: 22px;
  overflow: auto;
}
.main { border-right: 2px solid var(--line); background: var(--bg); }
.process { background: var(--bg); }

.panel {
  background: var(--surface);
  border: 2px solid var(--line);
  border-radius: 0;
  box-shadow: var(--shadow);
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 2px solid var(--line);
  background: var(--surface-2);
}
h1, h2 {
  margin: 0;
  font-family: var(--font-pixel);
  color: var(--gold);
  letter-spacing: 2px;
  text-transform: uppercase;
}
h1 { font-size: 13px; }
h2 { font-size: 12px; }
h2::before { content: "◆ "; color: var(--green); }

/* Forms — sunken pixel inputs */
form { padding: 18px; display: grid; gap: 14px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; }
.field { display: grid; gap: 6px; min-width: 0; }
.field label {
  font: 9px/1 var(--font-pixel);
  letter-spacing: 1.5px;
  color: var(--muted);
  text-transform: uppercase;
}
.label-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.label-row label { flex: 1; min-width: 0; }
.info-icon {
  font: 9px/1 var(--font-pixel);
  width: 18px;
  height: 18px;
  padding: 0;
  border: 2px solid var(--line);
  background: var(--surface-2);
  color: var(--gold);
  border-radius: 0;
  cursor: help;
  letter-spacing: 0;
  text-transform: none;
  box-shadow: var(--shadow-press);
  display: inline-flex;
  align-items: center;
  justify-content: center;
}
.info-icon:hover {
  background: var(--gold);
  color: var(--bg-deep);
  border-color: var(--gold);
  transform: none;
}
.info-icon:active { transform: translateY(1px); box-shadow: none; }
.check .info-icon { margin-left: 4px; }

/* Section header inside a form — full-width row, gold pixel-font marker */
.form-section {
  margin: 14px 0 4px;
  padding: 8px 12px;
  background: var(--bg-deep);
  border: 2px solid var(--line);
  border-left: 4px solid var(--gold);
  font: 11px/1 var(--font-pixel);
  letter-spacing: 2px;
  text-transform: uppercase;
  color: var(--gold);
  box-shadow: var(--shadow-press);
}
.form-section:first-child { margin-top: 0; }

/* Toast banner — pixel-framed strip near the top of the form panel */
.toast {
  margin: 0 18px 12px;
  padding: 12px 14px;
  border: 2px solid var(--line-hi);
  border-left-width: 6px;
  background: var(--bg-deep);
  color: var(--ink-bright);
  font: 13px/1.4 var(--font-ui);
  letter-spacing: 0.3px;
  box-shadow: var(--shadow);
}
.toast.error   { border-left-color: var(--rose);  color: var(--rose);  }
.toast.success { border-left-color: var(--green); color: var(--green); }
.toast.info    { border-left-color: var(--gold);  color: var(--gold);  }

/* Smart-suggestion banner — shown above engine forms when prior ratings exist */
.suggestion-banner {
  margin: 0 18px 12px;
  padding: 12px 14px;
  border: 2px solid var(--green-dim);
  border-left-width: 6px;
  background: var(--surface-2);
  display: grid;
  gap: 8px;
  grid-template-columns: 1fr auto;
  align-items: center;
  box-shadow: var(--shadow);
}
.suggestion-banner .suggestion-summary {
  font: 13px/1.5 var(--font-ui);
  color: var(--ink);
}
.suggestion-banner .suggestion-summary::before { content: "💡 "; }
.suggestion-banner strong { color: var(--green); }
.suggestion-banner button {
  font-size: 10px;
  padding: 8px 12px;
}

/* Gallery — render grid + filter row + rating buttons + detail modal layout */
.gallery-filters {
  display: flex;
  gap: 14px;
  align-items: center;
  flex-wrap: wrap;
  padding: 14px 18px;
  background: var(--surface-2);
  border: 2px solid var(--line);
  margin-bottom: 16px;
}
.gallery-filters label {
  display: flex;
  align-items: center;
  gap: 8px;
  font: 9px/1 var(--font-pixel);
  letter-spacing: 1.2px;
  color: var(--muted);
  text-transform: uppercase;
}
.gallery-filters select {
  border: 2px solid var(--line);
  background: var(--bg-deep);
  color: var(--ink-bright);
  padding: 6px 10px;
  font: 13px var(--font-ui);
  border-radius: 0;
  appearance: none;
  padding-right: 24px;
  background-image: linear-gradient(45deg, transparent 50%, var(--green) 50%), linear-gradient(-45deg, transparent 50%, var(--green) 50%);
  background-position: right 10px center, right 5px center;
  background-size: 5px 5px;
  background-repeat: no-repeat;
}
.gallery-stats {
  margin-left: auto;
  font: 12px/1 var(--font-mono);
  color: var(--muted);
}
.gallery-stats strong { color: var(--gold); font-size: 14px; }

.gallery-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 14px;
  padding: 0 18px 18px;
}
.gallery-card {
  background: var(--surface);
  border: 2px solid var(--line);
  box-shadow: var(--shadow);
  display: grid;
  grid-template-rows: auto auto auto;
  overflow: hidden;
}
.gallery-card.rating-2  { border-color: var(--gold);   box-shadow: 0 4px 0 var(--bg-deep), 0 0 0 1px var(--gold)   inset; }
.gallery-card.rating-1  { border-color: var(--green);  box-shadow: 0 4px 0 var(--bg-deep), 0 0 0 1px var(--green)  inset; }
.gallery-card.rating--1 { border-color: var(--rose);   opacity: 0.55; }
.gallery-thumb {
  display: block;
  background: var(--bg-deep);
  aspect-ratio: 16 / 9;
  overflow: hidden;
}
.gallery-thumb img {
  width: 100%; height: 100%;
  object-fit: cover;
  display: block;
  image-rendering: auto;
}
.gallery-meta {
  padding: 10px 12px 4px;
  display: grid;
  gap: 3px;
}
.gallery-engine {
  font: 9px/1 var(--font-pixel);
  letter-spacing: 1.5px;
  color: var(--gold);
  text-transform: uppercase;
}
.gallery-sub {
  font: 11px/1 var(--font-mono);
  color: var(--muted);
}
.gallery-subject {
  font: 12px/1.4 var(--font-ui);
  color: var(--ink);
  overflow: hidden;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  min-height: 32px;
}
.gallery-ratings {
  display: flex;
  gap: 4px;
  padding: 8px 12px 10px;
  border-top: 2px solid var(--line);
  background: var(--surface-2);
}
.rate-btn {
  flex: 1;
  font: 14px/1 var(--font-ui);
  padding: 6px;
  border: 2px solid var(--line);
  background: var(--surface);
  color: var(--ink);
  border-radius: 0;
  letter-spacing: 0;
  text-transform: none;
  cursor: pointer;
  box-shadow: var(--shadow-press);
}
.rate-btn:hover { background: var(--hover); border-color: var(--line-hi); transform: none; }
.rate-btn.active.rate--1 { background: var(--rose);  color: var(--bg-deep); border-color: var(--rose);  }
.rate-btn.active.rate-1  { background: var(--green); color: var(--bg-deep); border-color: var(--green); }
.rate-btn.active.rate-2  { background: var(--gold);  color: var(--bg-deep); border-color: var(--gold);  }
.rate-btn.rate-detail { flex: 0 0 32px; color: var(--muted); }

.empty-state {
  padding: 40px;
  text-align: center;
  color: var(--muted);
  font: 14px var(--font-ui);
}

/* Detail modal — uses help-card scaffolding but wider for the image+meta layout */
.detail-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}
.detail-image img {
  width: 100%; height: auto;
  border: 2px solid var(--line);
  background: var(--bg-deep);
  display: block;
}
.detail-meta {
  display: grid;
  gap: 8px;
  font: 13px/1.5 var(--font-ui);
  color: var(--ink);
}
.detail-meta strong { color: var(--gold); font: 10px/1 var(--font-pixel); letter-spacing: 1px; text-transform: uppercase; }
.detail-meta code { font-family: var(--font-mono); color: var(--ink-bright); font-size: 11px; word-break: break-all; }
.detail-meta hr { border: 0; border-top: 1px dashed var(--line); margin: 4px 0; }
.detail-meta textarea {
  width: 100%;
  border: 2px solid var(--line);
  background: var(--bg-deep);
  color: var(--ink-bright);
  padding: 8px;
  font: 13px var(--font-mono);
  border-radius: 0;
  resize: vertical;
}
.detail-rating-row {
  display: flex;
  gap: 6px;
}
.detail-rating-row .rate-btn { font-size: 12px; flex: 1; }
.detail-subject {
  font: 12px/1.5 var(--font-mono);
  color: var(--muted);
  background: var(--bg-deep);
  border: 1px solid var(--line);
  padding: 8px;
  max-height: 180px;
  overflow: auto;
  white-space: pre-wrap;
}
/* Make the help-card wider when it holds the detail-grid */
.help-card:has(.detail-grid) {
  width: min(1100px, 96vw);
}

/* A/B select indicator on each thumbnail — small clickable corner badge */
.gallery-thumb { position: relative; }
.gallery-select {
  position: absolute;
  top: 8px;
  right: 8px;
  width: 22px;
  height: 22px;
  border: 2px solid var(--ink-bright);
  background: rgba(5, 11, 9, 0.55);
  cursor: pointer;
  transition: background 80ms, border-color 80ms;
}
.gallery-select:hover {
  background: var(--green-dim);
  border-color: var(--green);
}
.gallery-card.selected .gallery-select {
  background: var(--gold);
  border-color: var(--gold);
}
.gallery-card.selected .gallery-select::after {
  content: "✓";
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  font: 13px/1 var(--font-pixel);
  color: var(--bg-deep);
}
.gallery-card.selected {
  outline: 3px solid var(--gold);
  outline-offset: -3px;
}

/* Compare modal — two columns of image + metadata, diff fields highlighted */
.compare-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 18px;
}
.compare-side {
  display: grid;
  gap: 12px;
}
.compare-head {
  font: 11px/1 var(--font-pixel);
  letter-spacing: 1.5px;
  color: var(--gold);
  padding: 6px 0;
  border-bottom: 2px solid var(--line);
}
.compare-side img {
  width: 100%;
  height: auto;
  border: 2px solid var(--line);
  background: var(--bg-deep);
  display: block;
}
.compare-meta {
  display: grid;
  gap: 6px;
  font: 13px/1.4 var(--font-ui);
  color: var(--ink);
}
.compare-meta strong {
  color: var(--muted);
  font: 9px/1 var(--font-pixel);
  letter-spacing: 1px;
  text-transform: uppercase;
  display: inline-block;
  min-width: 80px;
}
.compare-meta hr {
  border: 0;
  border-top: 1px dashed var(--line);
  margin: 4px 0;
}
.compare-meta .diff {
  background: var(--surface-3);
  border-left: 3px solid var(--gold);
  padding-left: 6px;
}
.compare-meta .diff strong {
  color: var(--gold);
}
.compare-subject {
  font: 12px/1.5 var(--font-mono);
  background: var(--bg-deep);
  border: 1px solid var(--line);
  padding: 8px;
  max-height: 200px;
  overflow: auto;
  white-space: pre-wrap;
  color: var(--muted);
}
.compare-subject.diff {
  color: var(--ink-bright);
  border-color: var(--gold);
}

.help-card:has(.compare-grid) {
  width: min(1280px, 96vw);
}
.form-section-hint {
  font: 13px/1.5 var(--font-ui);
  color: var(--muted);
  letter-spacing: 0;
  text-transform: none;
  margin-top: 6px;
}

/* Collapsed "power-user knobs" expander — wraps rarely-touched fields. */
details.form-expander {
  margin: 18px 0 14px;
  padding: 10px 12px;
  border: 1px dashed var(--line);
  background: rgba(255, 255, 255, 0.02);
  border-radius: 3px;
}
details.form-expander > summary {
  cursor: pointer;
  font: 10px/1 var(--font-pixel);
  letter-spacing: 2px;
  color: var(--muted);
  user-select: none;
  padding: 4px 0;
}
details.form-expander[open] > summary { color: var(--gold); margin-bottom: 6px; }
details.form-expander > summary::marker { color: var(--muted); }
details.form-expander > .field { margin-top: 10px; }

/* Help modal — same pixel-frame as picker, narrower */
.help-card {
  width: min(560px, 92vw);
  max-height: 78vh;
  background: var(--surface);
  border: 2px solid var(--line-hi);
  border-radius: 0;
  box-shadow: var(--shadow), 0 0 0 4px var(--bg-deep);
  display: grid;
  grid-template-rows: auto 1fr;
}
.help-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  border-bottom: 2px solid var(--line);
  background: var(--surface-2);
}
.help-head strong {
  font: 11px/1 var(--font-pixel);
  letter-spacing: 1.5px;
  color: var(--gold);
}
.help-head strong::before { content: "? "; color: var(--green); }
.help-body {
  padding: 18px;
  font: 14px/1.55 var(--font-ui);
  color: var(--ink);
  overflow: auto;
  white-space: pre-wrap;
}
.field input, .field select, .field textarea {
  width: 100%;
  border: 2px solid var(--line);
  border-radius: 0;
  padding: 10px 12px;
  background: var(--bg-deep);
  color: var(--ink-bright);
  font: 15px/1.4 var(--font-ui);
  box-shadow: inset 0 2px 0 rgba(0,0,0,0.45);
}
.field input:focus, .field select:focus, .field textarea:focus {
  outline: none;
  border-color: var(--green);
  color: var(--green);
}
.field input::placeholder, .field textarea::placeholder { color: var(--muted-dim); }
.field textarea { min-height: 100px; resize: vertical; font-family: var(--font-mono); font-size: 13px; }
.field select { appearance: none; padding-right: 28px; background-image: linear-gradient(45deg, transparent 50%, var(--green) 50%), linear-gradient(-45deg, transparent 50%, var(--green) 50%); background-position: right 14px center, right 8px center; background-size: 6px 6px; background-repeat: no-repeat; }

.path-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
.path-row button { padding: 0 14px; font-size: 9px; }

.checks { display: flex; gap: 14px; flex-wrap: wrap; }
.check { display: flex; gap: 8px; align-items: center; color: var(--ink); font-size: 13px; }
.check input[type="checkbox"] {
  appearance: none;
  width: 18px; height: 18px;
  border: 2px solid var(--line);
  background: var(--bg-deep);
  display: inline-block;
  cursor: pointer;
  box-shadow: inset 0 2px 0 rgba(0,0,0,0.45);
  margin: 0;
}
.check input[type="checkbox"]:checked {
  background: var(--green-dim);
  border-color: var(--green);
  background-image: linear-gradient(45deg, transparent 38%, var(--ink-bright) 38%, var(--ink-bright) 50%, transparent 50%), linear-gradient(-45deg, transparent 38%, var(--ink-bright) 38%, var(--ink-bright) 50%, transparent 50%);
  background-size: 6px 6px;
  background-position: 5px 5px, 9px 9px;
  background-repeat: no-repeat;
}

.runbar { display: flex; gap: 10px; align-items: center; justify-content: flex-end; padding-top: 6px; }
.cmd {
  margin: 0 18px 18px;
  padding: 12px 14px;
  background: var(--bg-deep);
  color: var(--green);
  border: 2px solid var(--line);
  border-radius: 0;
  overflow-wrap: anywhere;
  font: 12px/1.6 var(--font-mono);
  box-shadow: inset 0 2px 0 rgba(0,0,0,0.45);
}
.cmd::before { content: "> "; color: var(--gold); }

/* Process column — job cards, paths, logs, artifacts */
.job-list { display: grid; gap: 6px; margin-bottom: 16px; }

/* Active job (only one) — flat card, no collapse */
.job {
  display: grid;
  gap: 4px;
  padding: 12px 14px;
  border: 2px solid var(--green-dim);
  background: var(--surface-3);
  text-align: left;
  cursor: pointer;
  box-shadow: var(--shadow);
  font-family: var(--font-ui);
  font-size: 13px;
}
.job:hover { background: var(--hover); border-color: var(--line-hi); }
.job.active { border-color: var(--green-dim); background: var(--surface-3); }
.job .meta { font-size: 10px; }

/* Recorded runs — collapsible cards */
.run-card {
  border: 2px solid var(--line);
  background: var(--surface);
  box-shadow: var(--shadow);
  display: grid;
  grid-template-rows: auto 0fr;
  transition: grid-template-rows 180ms ease-out, border-color 100ms ease-out;
}
.run-card.expanded {
  grid-template-rows: auto 1fr;
  border-color: var(--line-hi);
}
.run-card-head {
  display: grid;
  grid-template-columns: auto 1fr auto auto auto;
  gap: 10px;
  align-items: center;
  padding: 10px 12px;
  background: transparent;
  border: none;
  box-shadow: none;
  text-align: left;
  cursor: pointer;
  font-family: var(--font-ui);
  text-transform: none;
  letter-spacing: 0;
  color: var(--ink);
}
.run-card-head:hover { background: var(--hover); transform: none; }
.run-card-head:active { transform: none; box-shadow: none; }
.run-action {
  font: 10px/1 var(--font-pixel);
  letter-spacing: 1.5px;
  color: var(--ink-bright);
  text-transform: uppercase;
}
.run-elapsed {
  font: 11px/1 var(--font-mono);
  color: var(--muted);
  letter-spacing: 0;
}
.art-count {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 22px;
  padding: 3px 5px;
  font: 9px/1 var(--font-pixel);
  letter-spacing: 1px;
  color: var(--bg-deep);
  background: var(--gold);
  border: 2px solid var(--gold);
  border-radius: 0;
}
.chevron {
  font: 10px/1 var(--font-pixel);
  color: var(--green);
  transition: transform 180ms ease-out;
}
.run-card.expanded .chevron { transform: rotate(90deg); }

.run-card-body {
  overflow: hidden;
  display: grid;
  gap: 10px;
}
.run-card.expanded .run-card-body {
  padding: 0 12px 12px;
}
.run-cmd {
  padding: 10px 12px;
  background: var(--bg-deep);
  color: var(--green);
  border: 2px solid var(--line);
  font: 11px/1.55 var(--font-mono);
  overflow-wrap: anywhere;
  box-shadow: inset 0 2px 0 rgba(0,0,0,0.45);
  max-height: 140px;
  overflow: auto;
}
.run-card-actions {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.run-card-actions button {
  padding: 7px 10px;
  font-size: 9px;
  letter-spacing: 1px;
}
.run-card-actions button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.run-card-actions button:disabled:hover {
  background: var(--surface);
  border-color: var(--line);
  color: var(--ink);
  transform: none;
}

.status {
  display: inline-block;
  font: 9px/1 var(--font-pixel);
  letter-spacing: 1.5px;
  padding: 4px 7px;
  border: 2px solid currentColor;
  background: var(--bg-deep);
  align-self: start;
  width: fit-content;
}
.status.running { color: var(--blue); animation: pixelBlink 1.2s steps(2, end) infinite; }
.status.ok { color: var(--green); }
.status.failed { color: var(--rose); }
.status.abandoned { color: var(--muted); }
@keyframes pixelBlink {
  50% { opacity: 0.45; }
}

.log {
  height: 360px;
  overflow: auto;
  background: var(--bg-deep);
  color: #c6f0a8;
  border: 2px solid var(--line);
  border-radius: 0;
  padding: 14px;
  font: 12px/1.55 var(--font-mono);
  white-space: pre-wrap;
  box-shadow: inset 0 2px 0 rgba(0,0,0,0.45);
}
.log::-webkit-scrollbar-track { background: var(--bg-deep); }

.issues {
  display: grid;
  gap: 6px;
  margin-bottom: 12px;
}
.issue {
  padding: 9px 12px;
  border: 2px solid var(--rose);
  background: var(--bg-deep);
  color: var(--rose);
  overflow-wrap: anywhere;
  font: 12px/1.45 var(--font-mono);
  box-shadow: var(--shadow);
}

.run-paths {
  display: grid;
  gap: 6px;
  margin-bottom: 12px;
  color: var(--muted);
  font: 11px/1.5 var(--font-mono);
  padding: 10px 12px;
  background: var(--bg-deep);
  border: 2px solid var(--line);
  box-shadow: inset 0 2px 0 rgba(0,0,0,0.45);
}
.run-paths div { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
.run-paths strong { color: var(--gold); font: 9px/1 var(--font-pixel); letter-spacing: 1.5px; min-width: 60px; }
.run-paths span { color: var(--ink); overflow-wrap: anywhere; }
.run-paths button { padding: 5px 9px; font-size: 8px; box-shadow: none; }

/* Resources — segmented pixel bars (Metroid energy-bar feel) */
.resources {
  display: grid;
  gap: 12px;
  margin-bottom: 14px;
  padding: 16px;
  background: var(--surface-2);
  border: 2px solid var(--line);
  box-shadow: var(--shadow);
  position: relative;
}
.resources::before {
  content: "▣ SYSTEM";
  position: absolute;
  top: -7px;
  left: 12px;
  padding: 0 6px;
  background: var(--bg);
  font: 8px/1 var(--font-pixel);
  letter-spacing: 1.5px;
  color: var(--gold);
}
.resBar { display: grid; gap: 5px; }
.resLabel {
  display: flex;
  justify-content: space-between;
  font: 9px/1 var(--font-pixel);
  letter-spacing: 1.2px;
  color: var(--muted);
  text-transform: uppercase;
}
.resLabel span { color: var(--ink-bright); font-family: var(--font-mono); font-size: 11px; letter-spacing: 0; text-transform: none; }
.resTrack {
  height: 16px;
  background: var(--bg-deep);
  border: 2px solid var(--line);
  border-radius: 0;
  overflow: hidden;
  box-shadow: inset 0 2px 0 rgba(0,0,0,0.45);
  position: relative;
}
.resFill {
  height: 100%;
  width: 0%;
  background: var(--green);
  /* Segment dividers — 6px wide blocks with 1px gap */
  background-image: repeating-linear-gradient(
    90deg,
    transparent 0,
    transparent 5px,
    var(--bg-deep) 5px,
    var(--bg-deep) 6px
  );
  border-radius: 0;
  transition: width 0.25s linear, background-color 0.2s ease;
  box-shadow: inset 0 2px 0 rgba(255,255,255,0.18);
}
.resFill.warn { background-color: var(--amber); }
.resFill.hot  { background-color: var(--rose); }

.artifacts { display: grid; gap: 8px; margin-top: 16px; }
.artifact {
  display: grid;
  grid-template-columns: 1fr auto auto auto;
  gap: 8px;
  align-items: center;
  padding: 11px;
  border: 2px solid var(--line);
  background: var(--surface);
  box-shadow: var(--shadow);
  font-family: var(--font-mono);
  font-size: 12px;
}
.artifact:hover { border-color: var(--line-hi); }
.artifact-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--ink-bright); }
.artifact button { padding: 6px 9px; font-size: 8px; }

.preview { margin-top: 16px; }
.preview img, .preview video {
  max-width: 100%;
  border: 2px solid var(--line);
  background: var(--bg-deep);
  border-radius: 0;
  box-shadow: var(--shadow);
  image-rendering: pixelated;
}
.preview audio { width: 100%; }

/* Modal — pixel-frame floating panel */
.modal {
  position: fixed;
  inset: 0;
  background: rgba(5, 11, 9, 0.78);
  display: none;
  align-items: center;
  justify-content: center;
  padding: 24px;
  backdrop-filter: blur(2px);
}
.modal.open { display: flex; }
.picker {
  width: min(960px, 96vw);
  max-height: 86vh;
  background: var(--surface);
  border: 2px solid var(--line-hi);
  border-radius: 0;
  box-shadow: var(--shadow), 0 0 0 4px var(--bg-deep);
  display: grid;
  grid-template-rows: auto auto 1fr;
}
.picker-top, .picker-path {
  padding: 14px;
  border-bottom: 2px solid var(--line);
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  background: var(--surface-2);
}
.picker-path input {
  flex: 1;
  min-width: 260px;
  padding: 10px 12px;
  border: 2px solid var(--line);
  border-radius: 0;
  background: var(--bg-deep);
  color: var(--ink-bright);
  font-family: var(--font-mono);
  font-size: 13px;
  box-shadow: inset 0 2px 0 rgba(0,0,0,0.45);
}
.entries { overflow: auto; padding: 8px; background: var(--bg); }
.entry {
  display: grid;
  grid-template-columns: 44px 1fr auto;
  align-items: center;
  gap: 10px;
  width: 100%;
  border: 0;
  background: transparent;
  text-align: left;
  color: var(--ink);
  padding: 9px 12px;
  font: 13px/1.4 var(--font-mono);
  text-transform: none;
  letter-spacing: 0;
  box-shadow: none;
}
.entry:hover { background: var(--hover); color: var(--green); transform: none; }
.entry > span:first-child { color: var(--gold); font: 8px/1 var(--font-pixel); letter-spacing: 1px; text-transform: uppercase; }

.hidden { display: none !important; }

@media (max-width: 1060px) {
  /* Below 3-column threshold: stop locking columns to viewport height so the
   * page can scroll normally as one tall document. */
  .app { grid-template-columns: 240px 1fr; height: auto; overflow: visible; }
  .sidebar, .main, .process { height: auto; overflow: visible; }
  .process { grid-column: 1 / -1; border-top: 2px solid var(--line); border-left: 0; }
}
@media (max-width: 760px) {
  .app { display: block; }
  .sidebar, .main { border-right: 0; border-bottom: 2px solid var(--line); }
  .grid-2 { grid-template-columns: 1fr; }
}
</style>
</head>
<body>
<div class="app">
  <aside class="sidebar">
    <div class="brand">Forge Wizard</div>
    <div id="forgeHome" class="meta"></div>
    <div id="actions"></div>
  </aside>
  <main class="main">
    <section class="panel">
      <div class="panel-head">
        <h1 id="formTitle">Loading</h1>
        <button id="refreshConfig" type="button">Refresh</button>
      </div>
      <div id="toast" class="toast" hidden></div>
      <form id="jobForm"></form>
      <pre id="commandPreview" class="cmd"></pre>
    </section>
  </main>
  <aside class="process">
    <div class="panel">
      <div class="panel-head">
        <h2>Process</h2>
        <button id="stopJob" class="danger" type="button">Stop</button>
      </div>
      <div style="padding:14px">
        <div id="jobList" class="job-list"></div>
        <div id="runPaths" class="run-paths"></div>
        <div id="resources" class="resources" hidden>
          <div class="resBar"><div class="resLabel">CPU <span id="cpuLabel">—</span></div><div class="resTrack"><div id="cpuFill" class="resFill"></div></div></div>
          <div class="resBar"><div class="resLabel">RAM <span id="memLabel">—</span></div><div class="resTrack"><div id="memFill" class="resFill"></div></div></div>
          <div class="resBar"><div class="resLabel">Steps <span id="stepsLabel">—</span></div><div class="resTrack"><div id="stepsFill" class="resFill"></div></div></div>
          <div class="resBar"><div class="resLabel">Worker <span id="workerLabel">—</span></div><div class="resTrack"><div id="workerFill" class="resFill"></div></div></div>
        </div>
        <div id="issues" class="issues"></div>
        <div id="log" class="log"></div>
        <div id="artifacts" class="artifacts"></div>
        <div id="preview" class="preview"></div>
      </div>
    </div>
  </aside>
</div>
<div id="pickerModal" class="modal" aria-hidden="true">
  <div class="picker">
    <div class="picker-top">
      <strong>Files</strong>
      <span id="pickerTarget" class="meta"></span>
      <span style="flex:1"></span>
      <button id="useFolder" type="button">Use Folder</button>
      <button id="closePicker" type="button">Close</button>
    </div>
    <div class="picker-path">
      <button id="parentDir" type="button">Up</button>
      <input id="pickerPath" spellcheck="false">
      <button id="goPath" type="button">Go</button>
      <div id="roots"></div>
    </div>
    <div id="entries" class="entries"></div>
  </div>
</div>
<div id="helpModal" class="modal" aria-hidden="true">
  <div class="help-card">
    <div class="help-head">
      <strong id="helpTitle">Field info</strong>
      <button id="closeHelp" type="button">Close</button>
    </div>
    <div id="helpBody" class="help-body"></div>
  </div>
</div>
<script>
const state = { config: null, action: "thumbnail", activeJob: null, pickerField: null, pickerPath: "", expandedRuns: new Set() };

// Top-level nav — Gallery / Create / Edit / Pipelines / Library / System.
// Coming in P2.3 we'll collapse the four per-engine entries into a single
// "Create" surface with a Style picker. For now they sit under the same
// CREATE group with consistent labels.
const groups = [
  ["GALLERY", [
    ["gallery", "All renders + ratings"],
  ]],
  ["CREATE", [
    ["create",                   "▸ Create (any style — recommended)"],
    ["thumbnail",                "▸ Thumbnail (preset + headline overlay)"],
    ["engine",                   "▸ Other engine (advanced)"],
    ["coloring-page",            "  · Children's coloring book (legacy direct page)"],
    ["mandala-art-page",         "  · Mandala art (legacy direct page)"],
    ["indian-folk-page",         "  · Indian folk art (legacy direct page)"],
    ["stylized-cinematic-page",  "  · Stylized cinematic (legacy direct page)"],
  ]],
  ["EDIT", [
    ["edit",                     "Edit / restyle an existing image"],
  ]],
  ["PIPELINES", [
    ["brief",                    "Episode kit"],
    ["episode",                  "Episode"],
    ["audiobook-simple",         "Audiobook (book → en+hi+mr)"],
    ["audiobook",                "Audiobook (advanced)"],
    ["audiobook-asmr",           "ASMR audiobook (+ optional video)"],
    ["voice",                    "Voiceover"],
    ["video",                    "Mux image+audio → mp4"],
    ["process-video-process",    "Process video"],
    ["process-video-warmup",     "Video warmup"]
  ]],
  ["LIBRARY", [
    ["engine-list",              "Engines list"],
    ["engine-recipes",           "Engine recipes"],
    ["engine-describe",          "Engine details"],
    ["list",                     "Presets + voices"],
    ["show",                     "Show preset"],
    ["series-list",              "Series list"],
    ["series-show",              "Series show"],
    ["series-new",               "New series"],
    ["mandala",                  "Procedural mandala (SVG, no FLUX)"],
    ["childrens-book",           "Procedural children's pages (SVG)"],
    ["folk-art",                 "Procedural folk-art page (SVG)"],
  ]],
  ["SYSTEM", [
    ["doctor",                   "Doctor"],
    ["status",                   "Status"],
    ["setup-voices",             "Install Kokoro voices"],
    ["models-list",              "Models list"],
    ["models-scan",              "Models scan"],
    ["models-clean",             "Models clean"],
    ["models-adopt",             "Models adopt"],
    ["bench",                    "Bench"]
  ]]
];

const specs = {
  thumbnail: {
    title: "Thumbnail",
    fields: [
      {name:"preset", label:"Preset", type:"select", options:"presets", required:true, value:"darksiders"},
      {name:"series", label:"Series", type:"select", options:"seriesOptional"},
      {name:"concept", label:"Prompt", type:"textarea", required:true, value:"A dragon holding a puppy in Pixar Style"},
      {name:"headline", label:"Headline", type:"text", required:true, value:"CAREGIVER"},
      {name:"sub", label:"Sub", type:"text", value:"ALLY"},
      {name:"bg", label:"Background path (skip BG render — supply your own)", type:"path"},
      {name:"profile", label:"Render mode", type:"select", options:"profiles", value:"balanced"},
      {name:"seed", label:"Seed", type:"number", value:"1"},
      {name:"frame_offset", label:"Frame offset", type:"number", value:"0"},
      {name:"steps", label:"Steps override", type:"number"},
      {name:"lora", label:"LoRA paths", type:"textarea"},
      {name:"lora_scale", label:"LoRA scales", type:"text"},
      {name:"out", label:"Output path", type:"path", required:true, value:"~/Desktop/forge-test/thumb.png"}
    ]
  },
  engine: {
    title: "Branded Image",
    fields: [
      {name:"name", label:"Engine (optional if a Recipe is selected — recipe carries its engine)", type:"select", options:"engines"},
      {name:"recipe", label:"Recipe", type:"select", options:"recipesOptional"},
      {name:"subject", label:"Prompt", type:"textarea"},
      {name:"config", label:"Config overrides", type:"text"},
      {name:"negative", label:"Extra negatives", type:"text"},
      {name:"from_image", label:"Source image", type:"path"},
      {name:"from_image_strength", label:"Image strength", type:"number", value:"0.85", showWhen:{from_image:"__nonempty"}},
      {name:"seeds", label:"Variants", type:"number", value:"1"},
      {name:"profile", label:"Render mode", type:"select", options:"profiles", value:"balanced"},
      {name:"seed", label:"Seed", type:"number", value:"1"},
      {name:"width", label:"Width", type:"number"},
      {name:"height", label:"Height", type:"number"},
      {name:"guidance", label:"Guidance", type:"number"},
      {name:"refine", label:"Refine", type:"checkbox"},
      {name:"refine_strength", label:"Refine strength", type:"number", value:"0.25"},
      {name:"upscale", label:"Final resolution (RealESRGAN upscale)", type:"select", options:"upscaleOptions"},
      {name:"hi_res", label:"Native Hi-res 1920×1080 (txt2img only)", type:"checkbox"},
      {name:"ultra_res", label:"Native Ultra-res 2048×1152 (RISKY)", type:"checkbox"},
      {name:"no_default_loras", label:"Skip engine's default LoRA stack", type:"checkbox"},
      {name:"out", label:"Output path", type:"path"}
    ]
  },

  // Unified Create page — one surface for ALL image styles. Style picker
  // switches which engine + which set of Style Details are visible. All
  // other fields (prompt, source image, render mode, final size, seed,
  // variants) are shared across styles.
  "create": {
    title: "Create — any style",
    fields: [
      // ── Always visible ──────────────────────────────────────────────────
      {name:"style",        label:"Style", type:"select", options:"styleOptions", value:"childrens-coloring-book"},
      {name:"subject",      label:"Prompt — describe what you want", type:"textarea", required:true, value:"a curious bear cub holding a balloon in a meadow"},
      {name:"recipe",       label:"Recipe (optional — prefills prompt + style details)", type:"select", options:"recipesAll"},
      {name:"from_image",   label:"Source image (optional — img2img / Kontext restyle)", type:"path"},
      {name:"profile",      label:"Render mode", type:"select", options:"profiles", value:"balanced"},
      {name:"upscale",      label:"Final size (RealESRGAN upscale)", type:"select", options:"upscaleOptions"},
      {name:"seed",         label:"Seed", type:"number", value:"1"},
      {name:"seeds",        label:"Variants (best-of contact sheet)", type:"number", value:"1"},

      // ── Style Details — engine-specific fields, conditional on Style ────
      {name:"_style", label:"▾ Style details", type:"expander", hint:"Engine-specific knobs. Auto-filtered to your Style choice above. Defaults are tuned.", fields:[
        // childrens-coloring-book
        {name:"cb_tradition",       label:"Tradition", type:"select", options:"cbTraditions", value:"mo-willems-minimal",     showWhen:{style:"childrens-coloring-book"}},
        {name:"cb_age_range",       label:"Age range", type:"select", options:"cbAgeRanges", value:"kids-6-9",                showWhen:{style:"childrens-coloring-book"}},
        {name:"cb_density",         label:"Density", type:"select", options:"cbDensity", value:"balanced",                    showWhen:{style:"childrens-coloring-book"}},
        {name:"cb_archetype",       label:"Character", type:"select", options:"cbArchetypes", value:"from-prompt",            showWhen:{style:"childrens-coloring-book"}},
        {name:"cb_setting",         label:"Setting", type:"select", options:"cbSettings", value:"from-prompt",                showWhen:{style:"childrens-coloring-book"}},
        {name:"cb_moment",          label:"Narrative moment", type:"select", options:"cbMoments", value:"from-prompt",        showWhen:{style:"childrens-coloring-book"}},
        {name:"cb_emotion",         label:"Emotion", type:"select", options:"cbEmotions", value:"from-prompt",                showWhen:{style:"childrens-coloring-book"}},
        {name:"cb_props",           label:"Prop", type:"select", options:"cbProps", value:"no-prop",                          showWhen:{style:"childrens-coloring-book"}},
        {name:"cb_character_count", label:"Characters in scene", type:"number", value:"1",                                    showWhen:{style:"childrens-coloring-book"}},
        // mandala-art
        {name:"ma_tradition",       label:"Tradition", type:"select", options:"maTraditions", value:"zentangle-organic",      showWhen:{style:"mandala-art"}},
        {name:"ma_treatment",       label:"Treatment", type:"select", options:"maTreatments", value:"from-prompt",            showWhen:{style:"mandala-art"}},
        {name:"ma_symmetry",        label:"Symmetry", type:"select", options:"maSymmetries", value:"from-prompt",             showWhen:{style:"mandala-art"}},
        {name:"ma_complexity",      label:"Complexity", type:"select", options:"maComplexity", value:"from-prompt",           showWhen:{style:"mandala-art"}},
        {name:"ma_border",          label:"Border", type:"select", options:"maBorders", value:"from-prompt",                  showWhen:{style:"mandala-art"}},
        // indian-classical
        {name:"ic_tradition",       label:"Tradition", type:"select", options:"icTraditions", value:"madhubani",              showWhen:{style:"indian-classical"}},
        {name:"ic_composition",     label:"Composition", type:"select", options:"icCompositions", value:"from-prompt",        showWhen:{style:"indian-classical"}},
        {name:"ic_mudra",           label:"Mudra / pose", type:"select", options:"icMudras", value:"from-prompt",             showWhen:{style:"indian-classical"}},
        {name:"ic_ground",          label:"Ground / setting", type:"select", options:"icGrounds", value:"from-prompt",        showWhen:{style:"indian-classical"}},
        // stylized-cinematic
        {name:"sc_tradition",       label:"Tradition", type:"select", options:"scTraditions", value:"tartakovsky-cel",        showWhen:{style:"stylized-cinematic"}},
        {name:"sc_time_of_day",     label:"Time of day", type:"select", options:"scTimeOfDay", value:"from-prompt",           showWhen:{style:"stylized-cinematic"}},
        {name:"sc_sky_state",       label:"Sky state", type:"select", options:"scSkyStates", value:"from-prompt",             showWhen:{style:"stylized-cinematic"}},
        {name:"sc_twinkles",        label:"Twinkles + glow", type:"select", options:"scTwinkles", value:"from-prompt",        showWhen:{style:"stylized-cinematic"}},
        {name:"sc_atmosphere",      label:"Atmospheric medium", type:"select", options:"scAtmospheres", value:"from-prompt",  showWhen:{style:"stylized-cinematic"}},
      ]},

      {name:"_imgctrl", label:"▾ Image control — guidance, refine, negatives, LoRA", type:"expander", hint:"Affect HOW the engine paints. Defaults are tuned per style.", fields:[
        {name:"from_image_strength", label:"Source image strength (only if you uploaded a photo)", type:"number", value:"0.85", showWhen:{from_image:"__nonempty"}},
        {name:"guidance",            label:"Guidance (leave blank = engine default)", type:"number"},
        {name:"refine",              label:"Refine (extra ~30 s, micro-detail pass)", type:"checkbox"},
        {name:"refine_strength",     label:"Refine strength", type:"number", value:"0.25"},
        {name:"negative",            label:"Extra negative terms — engine has 50-94 baked in already", type:"text"},
        {name:"no_default_loras",    label:"Skip engine's default LoRA stack", type:"checkbox"},
      ]},

      {name:"_output", label:"▾ Output", type:"expander", fields:[
        {name:"out", label:"Output path", type:"path"},
      ]},

      {name:"_perf", label:"▾ Performance — M5 Max specific", type:"expander", fields:[
        {name:"quantize", label:"Quantize (FLUX weight precision)", type:"select", options:"quantizeOptions"},
      ]},

      {name:"_danger", label:"⚠ Danger zone — native hi-res / ultra-res", type:"expander", hint:"DO NOT use with --from-image. Use Final Size upscale above.", fields:[
        {name:"hi_res",    label:"Native Hi-res 1920×1080 (txt2img only)", type:"checkbox"},
        {name:"ultra_res", label:"Native Ultra-res 2048×1152 (RISKY)", type:"checkbox"},
        {name:"width",     label:"Width override (px)", type:"number"},
        {name:"height",    label:"Height override (px)", type:"number"},
      ]},
    ]
  },

  "coloring-page": {
    title: "Children's Coloring Page",
    fields: [
      // ── Always visible (the daily-driver controls) ──────────────────────
      {name:"subject", label:"Prompt — what to draw", type:"textarea", required:true, value:"a curious bear cub holding a balloon in a meadow"},
      {name:"recipe", label:"Recipe (optional — prefills prompt + style details)", type:"select", options:"recipesColoring"},
      {name:"from_image", label:"Source image (optional — turn your photo into a coloring page)", type:"path"},
      {name:"profile", label:"Render mode", type:"select", options:"profiles", value:"balanced"},
      {name:"upscale", label:"Final size (RealESRGAN upscale)", type:"select", options:"upscaleOptions"},
      {name:"seed", label:"Seed", type:"number", value:"1"},
      {name:"seeds", label:"Variants (best-of contact sheet)", type:"number", value:"1"},

      {name:"_style", label:"▾ Style details — tradition, age, density, character", type:"expander", hint:"Engine-specific knobs. Defaults are tuned. Leave any 'from-prompt' to let your prompt decide that aspect.", fields:[
        {name:"cb_tradition",       label:"Tradition", type:"select", options:"cbTraditions", value:"mo-willems-minimal"},
        {name:"cb_age_range",       label:"Age range", type:"select", options:"cbAgeRanges", value:"kids-6-9"},
        {name:"cb_density",         label:"Density", type:"select", options:"cbDensity", value:"balanced"},
        {name:"cb_archetype",       label:"Character", type:"select", options:"cbArchetypes", value:"from-prompt"},
        {name:"cb_setting",         label:"Setting", type:"select", options:"cbSettings", value:"from-prompt"},
        {name:"cb_moment",          label:"Narrative moment", type:"select", options:"cbMoments", value:"from-prompt"},
        {name:"cb_emotion",         label:"Emotion", type:"select", options:"cbEmotions", value:"from-prompt"},
        {name:"cb_props",           label:"Prop", type:"select", options:"cbProps", value:"no-prop"},
        {name:"cb_character_count", label:"Characters in scene", type:"number", value:"1"},
      ]},

      {name:"_imgctrl", label:"▾ Image control — guidance, refine, negatives, LoRA", type:"expander", hint:"Affect HOW the engine paints (not what). Defaults are tuned.", fields:[
        {name:"from_image_strength", label:"Source image strength (only if you uploaded a photo above)", type:"number", value:"0.85", showWhen:{from_image:"__nonempty"}},
        {name:"guidance",            label:"Guidance (prompt adherence — 6.5 default)", type:"number", value:"6.5"},
        {name:"refine",              label:"Refine (extra ~30 s, micro-detail pass)", type:"checkbox"},
        {name:"refine_strength",     label:"Refine strength (only if Refine is on)", type:"number", value:"0.25"},
        {name:"negative",            label:"Extra negative terms — engine has 80+ baked in already", type:"text"},
        {name:"no_default_loras",    label:"Skip engine's default LoRA stack", type:"checkbox"},
      ]},

      {name:"_output", label:"▾ Output", type:"expander", hint:"Where the file lands. Leave blank for the default (~/Desktop/forge-test/engine-renders/<engine>/<slug>.png).", fields:[
        {name:"out", label:"Output path", type:"path"},
      ]},

      {name:"_perf", label:"▾ Performance — M5 Max specific", type:"expander", hint:"Quantization. Defaults (q8) are fine for nearly everything.", fields:[
        {name:"quantize", label:"Quantize", type:"select", options:"quantizeOptions"},
      ]},

      {name:"_danger", label:"⚠ Danger zone — native hi-res / ultra-res", type:"expander", hint:"DO NOT use these with --from-image (Kontext) — auto-clamped because the combination crashed Metal on M5 Max. Use Final Size upscale above for high resolution.", fields:[
        {name:"hi_res",    label:"Native Hi-res 1920×1080 (txt2img only)", type:"checkbox"},
        {name:"ultra_res", label:"Native Ultra-res 2048×1152 (RISKY)", type:"checkbox"},
        {name:"width",     label:"Width override (px)", type:"number"},
        {name:"height",    label:"Height override (px)", type:"number"},
      ]},
    ]
  },

  "indian-folk-page": {
    title: "Indian folk art (Madhubani / Warli / Tanjore / Pahari / Ravi Varma)",
    fields: [
      {name:"subject", label:"Prompt — what to depict", type:"textarea", required:true, value:"Rama, Lakshmana and Sita standing side by side in a triple-figure portrait"},
      {name:"recipe", label:"Recipe (optional — prefills prompt + style details)", type:"select", options:"recipesIndian"},
      {name:"from_image", label:"Source image (optional — restyle your photo in the chosen tradition)", type:"path"},
      {name:"profile", label:"Render mode", type:"select", options:"profiles", value:"balanced"},
      {name:"upscale", label:"Final size (RealESRGAN upscale)", type:"select", options:"upscaleOptions"},
      {name:"seed", label:"Seed", type:"number", value:"7"},
      {name:"seeds", label:"Variants (best-of contact sheet)", type:"number", value:"1"},

      {name:"_style", label:"▾ Style details — tradition, composition, mudra, ground", type:"expander", hint:"Madhubani / Warli / Tanjore / Pahari / Ravi-Varma. Each has its own visual language. Leave any 'from-prompt' to let your prompt decide that aspect.", fields:[
        {name:"ic_tradition",   label:"Tradition", type:"select", options:"icTraditions", value:"madhubani"},
        {name:"ic_composition", label:"Composition", type:"select", options:"icCompositions", value:"from-prompt"},
        {name:"ic_mudra",       label:"Mudra / pose", type:"select", options:"icMudras", value:"from-prompt"},
        {name:"ic_ground",      label:"Ground / setting", type:"select", options:"icGrounds", value:"from-prompt"},
      ]},

      {name:"_imgctrl", label:"▾ Image control — guidance, refine, negatives, LoRA", type:"expander", hint:"Affect HOW the engine paints (not what). Defaults are tuned.", fields:[
        {name:"from_image_strength", label:"Source image strength", type:"number", value:"0.85", showWhen:{from_image:"__nonempty"}},
        {name:"guidance",            label:"Guidance (5.0 default — iconographic detail)", type:"number", value:"5.0"},
        {name:"refine",              label:"Refine (extra ~30 s, micro-detail pass)", type:"checkbox"},
        {name:"refine_strength",     label:"Refine strength (only if Refine is on)", type:"number", value:"0.25"},
        {name:"negative",            label:"Extra negative terms — engine has 50+ baked in already", type:"text"},
        {name:"no_default_loras",    label:"Skip engine's default LoRA stack", type:"checkbox"},
      ]},

      {name:"_output", label:"▾ Output", type:"expander", hint:"Where the file lands. Leave blank for the default.", fields:[
        {name:"out", label:"Output path", type:"path"},
      ]},

      {name:"_perf", label:"▾ Performance — M5 Max specific", type:"expander", hint:"Quantization. Defaults (q8) are fine.", fields:[
        {name:"quantize", label:"Quantize", type:"select", options:"quantizeOptions"},
      ]},

      {name:"_danger", label:"⚠ Danger zone — native hi-res / ultra-res", type:"expander", hint:"DO NOT use these with --from-image. Use Final Size upscale above for high resolution.", fields:[
        {name:"hi_res",    label:"Native Hi-res 1920×1080 (txt2img only)", type:"checkbox"},
        {name:"ultra_res", label:"Native Ultra-res 2048×1152 (RISKY)", type:"checkbox"},
        {name:"width",     label:"Width override (px)", type:"number"},
        {name:"height",    label:"Height override (px)", type:"number"},
      ]},
    ]
  },

  "mandala-art-page": {
    title: "Mandala Art (FLUX)",
    fields: [
      {name:"subject", label:"Prompt — what to mandalize", type:"textarea", required:true, value:"a humpback whale"},
      {name:"recipe", label:"Recipe (optional — prefills prompt + style details)", type:"select", options:"recipesMandala"},
      {name:"from_image", label:"Source image (optional — re-render your subject as ornamental mandala)", type:"path"},
      {name:"profile", label:"Render mode", type:"select", options:"profiles", value:"balanced"},
      {name:"upscale", label:"Final size (RealESRGAN upscale)", type:"select", options:"upscaleOptions"},
      {name:"seed", label:"Seed", type:"number", value:"1"},
      {name:"seeds", label:"Variants (best-of contact sheet)", type:"number", value:"1"},

      {name:"_style", label:"▾ Style details — tradition, treatment, symmetry, complexity, border", type:"expander", hint:"Mandala-specific knobs. Defaults are tuned. Leave any 'from-prompt' to let your prompt decide that aspect.", fields:[
        {name:"ma_tradition",   label:"Tradition", type:"select", options:"maTraditions", value:"zentangle-organic"},
        {name:"ma_treatment",   label:"Treatment", type:"select", options:"maTreatments", value:"from-prompt"},
        {name:"ma_symmetry",    label:"Symmetry", type:"select", options:"maSymmetries", value:"from-prompt"},
        {name:"ma_complexity",  label:"Complexity", type:"select", options:"maComplexity", value:"from-prompt"},
        {name:"ma_border",      label:"Border", type:"select", options:"maBorders", value:"from-prompt"},
      ]},

      {name:"_imgctrl", label:"▾ Image control — guidance, refine, negatives, LoRA", type:"expander", hint:"Affect HOW the engine paints (not what). Defaults are tuned.", fields:[
        {name:"from_image_strength", label:"Source image strength", type:"number", value:"0.85", showWhen:{from_image:"__nonempty"}},
        {name:"guidance",            label:"Guidance (8.5 default — strict line-art adherence)", type:"number", value:"8.5"},
        {name:"refine",              label:"Refine (extra ~30 s, micro-detail pass)", type:"checkbox"},
        {name:"refine_strength",     label:"Refine strength (only if Refine is on)", type:"number", value:"0.25"},
        {name:"negative",            label:"Extra negative terms — engine has 94 baked in already", type:"text"},
        {name:"no_default_loras",    label:"Skip engine's default LoRA stack", type:"checkbox"},
      ]},

      {name:"_output", label:"▾ Output", type:"expander", hint:"Where the file lands. Leave blank for the default.", fields:[
        {name:"out", label:"Output path", type:"path"},
      ]},

      {name:"_perf", label:"▾ Performance — M5 Max specific", type:"expander", hint:"Quantization. Defaults (q8) are fine.", fields:[
        {name:"quantize", label:"Quantize", type:"select", options:"quantizeOptions"},
      ]},

      {name:"_danger", label:"⚠ Danger zone — native hi-res / ultra-res", type:"expander", hint:"DO NOT use these with --from-image. Use Final Size upscale above.", fields:[
        {name:"hi_res",    label:"Native Hi-res 1920×1080 (txt2img only)", type:"checkbox"},
        {name:"ultra_res", label:"Native Ultra-res 2048×1152 (RISKY)", type:"checkbox"},
        {name:"width",     label:"Width override (px)", type:"number"},
        {name:"height",    label:"Height override (px)", type:"number"},
      ]},
    ]
  },

  "stylized-cinematic-page": {
    title: "Stylized cinematic (Tartakovsky / Darksiders / Mignola / McQuarrie / Ghibli)",
    fields: [
      {name:"subject", label:"Prompt — describe the scene", type:"textarea", required:true, value:"a lone samurai on a windswept hill at dusk"},
      {name:"recipe", label:"Recipe (optional — prefills prompt + style details)", type:"select", options:"recipesOptional"},
      {name:"from_image", label:"Source image (optional — restyle your photo in chosen tradition)", type:"path"},
      {name:"profile", label:"Render mode", type:"select", options:"profiles", value:"balanced"},
      {name:"upscale", label:"Final size (RealESRGAN upscale)", type:"select", options:"upscaleOptions"},
      {name:"seed", label:"Seed", type:"number", value:"7"},
      {name:"seeds", label:"Variants (best-of contact sheet)", type:"number", value:"1"},

      {name:"_style", label:"▾ Style details — tradition + cinematography (light / sky / atmosphere)", type:"expander", hint:"Tartakovsky / Darksiders / Mignola / McQuarrie / Ghibli — each is a different drawn-painted register. Cinematography knobs lock specific aspects (color temperature, sun angle) — leave any 'from-prompt' to let your prompt decide.", fields:[
        {name:"sc_tradition",   label:"Tradition", type:"select", options:"scTraditions", value:"tartakovsky-cel"},
        {name:"sc_time_of_day", label:"Time of day (Kelvin + sun angle)", type:"select", options:"scTimeOfDay", value:"from-prompt"},
        {name:"sc_sky_state",   label:"Sky state", type:"select", options:"scSkyStates", value:"from-prompt"},
        {name:"sc_twinkles",    label:"Twinkles + glow (fireflies, lanterns, city lights)", type:"select", options:"scTwinkles", value:"from-prompt"},
        {name:"sc_atmosphere",  label:"Atmospheric medium (fog, mist, dust, rain, snow)", type:"select", options:"scAtmospheres", value:"from-prompt"},
      ]},

      {name:"_imgctrl", label:"▾ Image control — guidance, refine, negatives, LoRA", type:"expander", hint:"Affect HOW the engine paints (not what). Defaults are tuned.", fields:[
        {name:"from_image_strength", label:"Source image strength", type:"number", value:"0.85", showWhen:{from_image:"__nonempty"}},
        {name:"guidance",            label:"Guidance (4.5 default — stylized register)", type:"number", value:"4.5"},
        {name:"refine",              label:"Refine (extra ~30 s, micro-detail pass)", type:"checkbox"},
        {name:"refine_strength",     label:"Refine strength (only if Refine is on)", type:"number", value:"0.25"},
        {name:"negative",            label:"Extra negative terms — engine has 44 baked in already", type:"text"},
        {name:"no_default_loras",    label:"Skip engine's default LoRA stack", type:"checkbox"},
      ]},

      {name:"_output", label:"▾ Output", type:"expander", hint:"Where the file lands. Leave blank for the default.", fields:[
        {name:"out", label:"Output path", type:"path"},
      ]},

      {name:"_perf", label:"▾ Performance — M5 Max specific", type:"expander", hint:"Quantization. Defaults (q8) are fine.", fields:[
        {name:"quantize", label:"Quantize", type:"select", options:"quantizeOptions"},
      ]},

      {name:"_danger", label:"⚠ Danger zone — native hi-res / ultra-res", type:"expander", hint:"DO NOT use these with --from-image. Use Final Size upscale above.", fields:[
        {name:"hi_res",    label:"Native Hi-res 1920×1080 (txt2img only)", type:"checkbox"},
        {name:"ultra_res", label:"Native Ultra-res 2048×1152 (RISKY)", type:"checkbox"},
        {name:"width",     label:"Width override (px)", type:"number"},
        {name:"height",    label:"Height override (px)", type:"number"},
      ]},
    ]
  },
  edit: {
    title: "Edit Image",
    fields: [
      {name:"image", label:"Source image", type:"path", required:true},
      {name:"preset", label:"Preset", type:"select", options:"presetsOptional"},
      {name:"instruction", label:"Instruction", type:"textarea"},
      {name:"strength", label:"Strength (0.3 minor edit, 0.6 default, 0.9 major restyle)", type:"number", value:"0.6"},
      {name:"profile", label:"Render mode", type:"select", options:"profiles", value:"balanced"},
      {name:"steps", label:"Steps override (blank = use render mode)", type:"number"},
      {name:"seed", label:"Seed", type:"number", value:"1"},
      {name:"out", label:"Output path", type:"path"}
    ]
  },
  brief: {
    title: "Episode Kit",
    fields: [
      {name:"topic", label:"Topic", type:"textarea", required:true},
      {name:"preset", label:"Preset", type:"select", options:"presets", value:"cinematic"},
      {name:"voice", label:"Voice", type:"select", options:"voices"},
      {name:"series", label:"Series", type:"select", options:"seriesOptional"},
      {name:"profile", label:"Render mode", type:"select", options:"profiles", value:"balanced"},
      {name:"steps", label:"Steps override", type:"number"},
      {name:"lora", label:"LoRA paths", type:"textarea"},
      {name:"lora_scale", label:"LoRA scales", type:"text"},
      {name:"translate", label:"Translate", type:"text"},
      {name:"video", label:"Mux video", type:"checkbox"},
      {name:"out", label:"Output dir", type:"path", value:"~/Desktop/forge-test/brief"}
    ]
  },
  episode: {
    title: "Episode",
    fields: [
      {name:"book", label:"Book path", type:"path"},
      {name:"text", label:"Text", type:"textarea"},
      {name:"title", label:"Title", type:"text"},
      {name:"preset", label:"Preset", type:"select", options:"presets", value:"cinematic"},
      {name:"voice", label:"Voice", type:"select", options:"voices"},
      {name:"translate", label:"Translate", type:"text", value:"hi,mr"},
      {name:"segments", label:"Segments", type:"number", value:"4"},
      {name:"seconds", label:"Seconds", type:"number", value:"15"},
      {name:"shots_per_segment", label:"Shots per segment", type:"number", value:"4"},
      {name:"profile", label:"Render mode", type:"select", options:"profiles", value:"balanced"},
      {name:"steps", label:"Steps override", type:"number"},
      {name:"no_flux", label:"No FLUX", type:"checkbox"},
      {name:"out", label:"Output dir", type:"path", value:"~/Desktop/forge-test/episode"}
    ]
  },
  "audiobook-simple": {
    title: "Audiobook — simple (book → en + hi + mr audio)",
    fields: [
      {name:"_s1", label:"BOOK", type:"section", hint:"Pick a .txt, .rtf, or .pdf file. The pipeline reads the full text, translates to Hindi + Marathi (if selected), and narrates each language as a separate audio file."},
      {name:"book", label:"Book file (.txt / .rtf / .pdf)", type:"path", required:true},
      {name:"title", label:"Title (blank = use filename)", type:"text"},

      {name:"_s2", label:"VOICES", type:"section", hint:"English uses Kokoro neural TTS. Hindi + Marathi use Sarvam Bulbul v3 cloud TTS (40+ speakers). Pick whichever sounds most natural for narration — recommended defaults: Anushka (Hindi female narrator) and Vidya (Marathi female narrator). For male narration, try Shubh (Hindi) or Rohan (Marathi)."},
      {name:"voice", label:"English voice preset", type:"select", options:"voices"},
      {name:"sarvam_hi_speaker", label:"Hindi speaker (Sarvam)", type:"select", options:"sarvam_speakers"},
      {name:"sarvam_mr_speaker", label:"Marathi speaker (Sarvam)", type:"select", options:"sarvam_speakers"},

      {name:"_s3", label:"LANGUAGES", type:"section", hint:"All three are on by default. Uncheck any you don't want. English is always produced (it's the source narration); turning off the others just skips translation."},
      {name:"do_en_note", label:"English is always produced (Kokoro). Tick boxes below to ALSO render Hindi / Marathi via Sarvam.", type:"section"},
      {name:"do_hi", label:"Hindi (Sarvam)", type:"checkbox", checked:true},
      {name:"do_mr", label:"Marathi (Sarvam)", type:"checkbox", checked:true},

      {name:"_s4", label:"OUTPUT", type:"section", hint:"Folder where audio files land. One audio file per selected language. Defaults to ~/Desktop/forge-test/audiobook/<title>/."},
      {name:"out", label:"Output folder (blank = auto)", type:"path"}
    ]
  },

  audiobook: {
    title: "Audiobook — audio only (single voice)",
    fields: [
      {name:"_s1", label:"INPUT", type:"section", hint:"Provide either a book file or paste raw text. One of the two is required."},
      {name:"book", label:"Book file (.rtf / .txt)", type:"path"},
      {name:"title", label:"Title (used in filename)", type:"text", value:"Untitled"},
      {name:"text", label:"OR — paste raw text instead", type:"textarea"},

      {name:"_s2", label:"VOICE & LANGUAGE", type:"section", hint:"Voice preset picks engine + speaker. Translate languages will produce additional audio files in those tongues."},
      {name:"voice", label:"Voice preset", type:"select", options:"voices"},
      {name:"translate", label:"Translate to (comma-separated)", type:"text", value:""},

      {name:"_s3", label:"CHUNKING", type:"section", hint:"Long books are split into chunks for TTS. Defaults work for most books — only adjust if you hit memory limits or want shorter previews."},
      {name:"chunk_chars", label:"Chars per chunk", type:"number", value:"1400"},
      {name:"max_chunks", label:"Max chunks (blank = all)", type:"number"},

      {name:"_s4", label:"OUTPUT", type:"section", hint:"Folder where audio files land. Each language gets its own .wav/.m4a."},
      {name:"out", label:"Output folder", type:"path", value:"~/Desktop/forge-test/audiobook"}
    ]
  },
  "audiobook-asmr": {
    title: "ASMR Audiobook — multilingual + optional video mux",
    fields: [
      {name:"_s1", label:"INPUT", type:"section", hint:"Pick a folder containing the transcript (and optionally a loop video) — OR set the transcript path directly. Folder mode auto-detects RTF + video."},
      {name:"folder", label:"Input folder (auto-detects transcript + video)", type:"path"},
      {name:"rtf", label:"OR — transcript file path directly", type:"path"},
      {name:"out_dir", label:"Output folder", type:"path", value:"~/Desktop/forge-test/asmr-audiobook"},

      {name:"_s2", label:"OPTIONAL VIDEO MUX", type:"section", hint:"Leave Loop video blank for audio-only output. Set a video path to produce one .mp4 per language with the audio overlaid (loops if shorter than audio)."},
      {name:"video", label:"Loop video (blank = audio only)", type:"path"},

      {name:"_s3", label:"LANGUAGES & VOICES", type:"section", hint:"Comma-separated language codes: en (English / Kokoro), hi (Hindi / Sarvam), mr (Marathi / Sarvam). Each becomes a separate audio + video output."},
      {name:"langs", label:"Languages", type:"text", value:"en,hi,mr"},
      {name:"english_engine", label:"English TTS engine", type:"select", options:"audiobook_engines", value:"kokoro"},
      {name:"mode", label:"Voice pacing mode", type:"select", options:"audiobook_modes", value:"asmr"},
      {name:"sarvam_speaker", label:"Hindi speaker (Sarvam)", type:"select", options:"sarvam_speakers"},
      {name:"sarvam_speaker_mr", label:"Marathi speaker (Sarvam)", type:"select", options:"sarvam_speakers"},

      {name:"_s4", label:"ASMR MASTERING", type:"section", hint:"Pacing pauses and ambient bed. Defaults are tuned for sleep-friendly narration."},
      {name:"bed", label:"Ambient bed", type:"select", options:"audiobook_beds", value:"vinyl-crackle"},
      {name:"sent_pause_ms", label:"Pause between sentences (ms)", type:"number", value:"600"},
      {name:"para_pause_ms", label:"Pause between paragraphs (ms)", type:"number", value:"1200"},

      {name:"_s5", label:"PAGES / BATCHES", type:"section", hint:"Audiobooks are chunked into ~10-page batches to fit in TTS memory and produce manageable file sizes. Defaults: 10 pages × 250 words → ~150 spoken words per page, ~one-minute clips."},
      {name:"batch_pages", label:"Pages per batch", type:"number", value:"10"},
      {name:"page_words", label:"Words per page (source)", type:"number", value:"250"},
      {name:"spoken_words", label:"Target spoken words / page", type:"number", value:"150"},
      {name:"max_words", label:"Total spoken words cap (blank = all)", type:"number"},
      {name:"max_chars", label:"Sentence character cap", type:"number", value:"500"},
      {name:"batches", label:"Only run specific batches (e.g. '1,3-5')", type:"text"},

      {name:"_s6", label:"THUMBNAILS & SUBTITLES (only for video mode)", type:"section", hint:"When a loop video is set, each .mp4 can get its own thumbnail (extracted from the video frame + overlaid headline + body text) and a subtitle file."},
      {name:"thumb_preset", label:"Thumbnail preset", type:"select", options:"presets", value:"thumbnail-bold"},
      {name:"thumb_seed", label:"Thumbnail seed", type:"number", value:"42"},
      {name:"thumb_frame_at", label:"Frame to grab at (seconds; blank = middle)", type:"number"},
      {name:"subtitles", label:"Subtitle format", type:"select", options:"subtitle_modes", value:"srt"},

      {name:"thumbnail", label:"Generate thumbnails per language", type:"checkbox", checked:true},
      {name:"dry_run", label:"Dry run (preview only — no audio synthesized)", type:"checkbox"}
    ]
  },
  voice: {
    title: "Voiceover",
    fields: [
      {name:"preset", label:"Voice", type:"select", options:"voices"},
      {name:"text", label:"Text", type:"textarea", required:true},
      {name:"translate", label:"Translate", type:"text"},
      {name:"out", label:"Output path", type:"path", value:"~/Desktop/forge-test/voice.wav"}
    ]
  },
  video: {
    title: "Mux Video",
    fields: [
      {name:"image", label:"Image", type:"path", required:true},
      {name:"audio", label:"Audio", type:"path", required:true},
      {name:"no_kenburns", label:"Static image", type:"checkbox"},
      {name:"zoom_max", label:"Zoom max", type:"number", value:"1.15"},
      {name:"fade_out", label:"Fade out", type:"number", value:"1.0"},
      {name:"out", label:"Output path", type:"path", value:"~/Desktop/forge-test/video.mp4"}
    ]
  },
  mandala: {
    title: "Mandala",
    fields: [
      {name:"style", label:"Style", type:"select", options:"mandala_styles"},
      {name:"symmetry", label:"Symmetry", type:"number", value:"12"},
      {name:"rings", label:"Rings", type:"number", value:"7"},
      {name:"complexity", label:"Complexity", type:"select", options:"complexity", value:"max"},
      {name:"seed", label:"Seed", type:"number", value:"1"},
      {name:"width", label:"Width", type:"number", value:"2400"},
      {name:"height", label:"Height", type:"number", value:"2400"},
      {name:"stroke_width", label:"Stroke width", type:"number", value:"3"},
      {name:"palette", label:"Palette", type:"select", choices:["ink","soft","royal"], value:"ink"},
      {name:"supersample", label:"Supersample", type:"number", value:"2"},
      {name:"no_mirror", label:"No mirror", type:"checkbox"},
      {name:"out", label:"Output path", type:"path", value:"~/Desktop/forge-test/mandala.png"}
    ]
  },
  "childrens-book": {
    title: "Children's Pages",
    fields: [
      {name:"theme", label:"Theme", type:"select", options:"child_themes", value:"all"},
      {name:"pages", label:"Pages", type:"number", value:"3"},
      {name:"symmetry", label:"Symmetry", type:"number", value:"12"},
      {name:"rings", label:"Rings", type:"number", value:"7"},
      {name:"complexity", label:"Complexity", type:"select", options:"complexity", value:"max"},
      {name:"seed", label:"Seed", type:"number", value:"101"},
      {name:"width", label:"Width", type:"number", value:"2400"},
      {name:"height", label:"Height", type:"number", value:"2400"},
      {name:"palette", label:"Palette", type:"select", choices:["ink","soft","royal"], value:"ink"},
      {name:"supersample", label:"Supersample", type:"number", value:"2"},
      {name:"out", label:"Output dir", type:"path", value:"~/Desktop/forge-test/childrens-book"}
    ]
  },
  "folk-art": {
    title: "Folk Art Page",
    fields: [
      {name:"theme", label:"Theme", type:"select", options:"folk_themes"},
      {name:"width", label:"Width", type:"number", value:"2400"},
      {name:"height", label:"Height", type:"number", value:"1800"},
      {name:"complexity", label:"Complexity", type:"select", options:"complexity", value:"max"},
      {name:"stroke_width", label:"Stroke width", type:"number", value:"3"},
      {name:"palette", label:"Palette", type:"select", choices:["ink","soft"], value:"ink"},
      {name:"supersample", label:"Supersample", type:"number", value:"2"},
      {name:"out", label:"Output path", type:"path", value:"~/Desktop/forge-test/folk-art.png"}
    ]
  },
  "engine-list": { title:"Engines", fields: [] },
  "engine-describe": { title:"Engine Details", fields: [{name:"name", label:"Engine", type:"select", options:"engines", required:true}] },
  "engine-recipes": { title:"Engine Recipes", fields: [{name:"engine", label:"Engine filter", type:"select", options:"enginesOptional"}] },
  "process-video-warmup": {
    title:"Video Warmup",
    fields: [
      {name:"quality", label:"Quality", type:"select", options:"process_qualities", value:"good"},
      {name:"dry_run", label:"Dry run", type:"checkbox"}
    ]
  },
  "process-video-process": {
    title:"Process Video",
    fields: [
      {name:"video", label:"Video", type:"path", required:true},
      {name:"out", label:"Output root", type:"path", value:"~/Desktop/forge-test/videos-out"},
      {name:"quality", label:"Quality", type:"select", options:"process_qualities", value:"good"},
      {name:"captions", label:"Captions", type:"text"},
      {name:"noisy", label:"Noisy audio", type:"checkbox"},
      {name:"no_burn", label:"Skip burn-in", type:"checkbox"},
      {name:"no_thumbs", label:"Skip thumbnails", type:"checkbox"},
      {name:"force", label:"Force", type:"checkbox"},
      {name:"offline_skip_check", label:"Offline skip check", type:"checkbox"}
    ]
  },
  list: { title:"List Presets", fields: [] },
  show: { title:"Show Preset", fields: [{name:"preset", label:"Preset", type:"select", options:"presets", required:true}] },
  "series-list": { title:"Series List", fields: [] },
  "series-show": { title:"Series Show", fields: [{name:"id", label:"Series", type:"select", options:"series", required:true}] },
  "series-new": { title:"Series New", fields: [{name:"id", label:"Series id", type:"text", required:true}, {name:"preset", label:"Preset", type:"select", options:"presets", required:true}, {name:"force", label:"Force overwrite", type:"checkbox"}] },
  doctor: { title:"Doctor", fields: [{name:"deep", label:"Deep", type:"checkbox", checked:true}, {name:"repair", label:"Repair", type:"checkbox"}, {name:"json", label:"JSON", type:"checkbox"}, {name:"verbose", label:"Verbose", type:"checkbox"}] },
  status: { title:"Status", fields: [{name:"limit", label:"Limit", type:"number", value:"12"}] },
  "setup-voices": { title:"Setup Voices", fields: [{name:"kokoro", label:"Install / refresh Kokoro", type:"checkbox", checked:true}] },
  "models-list": { title:"Models List", fields: [{name:"full", label:"Full", type:"checkbox"}] },
  "models-scan": { title:"Models Scan", fields: [{name:"full", label:"Full", type:"checkbox"}] },
  "models-clean": { title:"Models Clean", fields: [{name:"dry_run", label:"Dry run", type:"checkbox", checked:true}, {name:"yes", label:"Yes", type:"checkbox"}, {name:"full", label:"Full", type:"checkbox"}, {name:"remove", label:"Remove repos", type:"textarea"}] },
  "models-adopt": { title:"Models Adopt", fields: [{name:"path", label:"Model file", type:"path", required:true}, {name:"as", label:"As", type:"select", choices:["flux-bfl","kokoro","huggingface","ollama"]}, {name:"delete_source", label:"Delete source", type:"checkbox"}] },
  bench: { title:"Bench", fields: [{name:"real", label:"Probe metadata only — real model microbenchmarks not yet implemented", type:"checkbox"}] }
};

// Field help text — shown when the ? icon next to a label is clicked.
// Keyed by field.name (matches the specs object above).
const FIELD_HELP = {
  preset: "Visual brand preset. Locks the palette, typography, and FLUX positive prefix. Try cinematic, batman-noir, darksiders, tartakovsky, editorial, documentary, thumbnail-bold.",
  series: "Optional series ID to lock the look (palette + typography + character cast) across multiple renders. Leave blank if you don't have a series defined.",
  concept: "Free-form description of what you want drawn. This becomes the FLUX prompt. Use [name] to inline a series cast member (e.g. '[keeper] at the harbor wall').",
  subject: "Free-form description of what's in the image. Goes in as the SUBJECT block — keep it specific and concrete, e.g. 'a humpback whale in side profile' beats 'an animal'.",
  headline: "Big text drawn on top of the thumbnail. ≤6 words. Will be auto-capitalized.",
  sub: "Smaller subtitle text below the headline. Optional — leave blank to skip.",
  bg: "If you have an existing background image, pick its path to reuse it instead of generating new. Otherwise FLUX renders fresh from the preset + prompt.",
  seed: "Random seed for FLUX. Same prompt + same seed = same image, every time. Bump to get a new variation. Engines pick a 'good' default seed per recipe.",
  steps: "FLUX denoising steps. Higher = more detail + slower. 25-32 is the sweet spot on dev. Schnell wants 2-4. Past 36 rarely helps.",
  steps_override: "Override the engine's default step count. Leave blank to use the recipe defaults (32 for childrens-coloring-book, 36 for mandala-art).",
  frame_offset: "When a series is set, each integer here gives a unique-but-consistent seed. Use it to render frame 0, 1, 2... of the same series with locked style.",
  profile: "Speed profile: cool = schnell @ 4 steps (fastest, lowest quality), balanced = dev @ 18, max = dev @ 25. Leave as preset-default to use the engine's own runtime.",
  draft: "Use the schnell model @ 4 steps. Cool/fast preview mode. Output quality lower — use to scout compositions before final render.",
  lora: "LoRA file paths (one per line). Each LoRA adjusts FLUX's weights toward a particular trained style.",
  lora_paths: "LoRA file paths (one per line). Each LoRA adjusts FLUX's weights toward a particular trained style.",
  lora_scale: "Strength per LoRA, one number per line, in same order as paths. 0.4-0.6 subtle nudge, 0.7-0.9 strong adherence, 1.0+ rarely improves anything.",
  lora_scales: "Strength per LoRA, one number per line, in same order as paths. 0.4-0.6 subtle, 0.7-0.9 strong, 1.0+ rarely improves.",
  out: "Where to save the output file. Leave blank to use the default (~/Desktop/forge-test/...).",
  output_path: "Where to save the output file. Leave blank to use the default (~/Desktop/forge-test/...).",
  engine: "Domain-expert style engine. noir-cinema, wildlife-photo, impressionist, indian-classical, childrens-coloring-book, mandala-art. Each has its own vocabulary — see Engine details.",
  recipe: "Pre-vetted preset combo from brand/prompts/library.json. Browse all via the 'Engine recipes' action. Recipes pre-fill subject, config, seed.",
  config: "Engine knob overrides as comma-separated key=value (e.g. 'subject.character_archetype=brave-rabbit,style.tradition=mo-willems-minimal'). See Engine details for valid knobs.",
  seeds: "Render N variants with consecutive seeds (seed, seed+1, ...) into a gallery folder with an HTML contact sheet for picking the best.",
  refine: "Two-pass refinement: after base composition lands, low-denoise img2img refines for micro-detail. Adds ~30s per image.",
  refine_strength: "Refinement denoising strength. 0.05 barely touches, 0.25 default, 0.40 significant rework. Keep low to preserve composition.",
  hi_res: "Render at 1920×1080 (~2x compute vs default 1280×720). Use for final/output-grade images.",
  ultra_res: "Render at 2048×1152 (~3x compute, max detail). Pair with --refine for best results. Slow.",
  width: "Output width in pixels. Overrides resolution presets.",
  height: "Output height in pixels. Overrides resolution presets.",
  guidance: "FLUX guidance scale (how strictly to follow the prompt). 3.0-3.8 photorealism, 3.5-6.0 paintings/line-art, 6.0-8.0 strict adherence, 8+ may burn highlights.",
  negative: "Comma-separated extra negative terms. FLUX largely ignores these (flow-matching, CFG=1) — better to phrase positively in the subject. Kept here for compatibility.",
  extra_negatives: "Comma-separated extra negative terms. FLUX largely ignores these — see the science doc.",
  from_image: "Source image to restyle with the engine's directive (img2img via FLUX-Kontext). Turns your photo into the engine's style — e.g. a photo of a bird into a coloring-book illustration.",
  from_image_strength: "How aggressively to restyle. 0.3 = minor edit, 0.85 = major rework (default), 0.95 = near-replace.",
  voice: "Voice preset. Uses Kokoro-TTS (neural, ~80MB) if installed; falls back to macOS `say`. Run 'Setup voices' to install Kokoro.",
  preset_voice: "Voice preset. Uses Kokoro-TTS if installed; falls back to macOS `say`.",
  text: "Text to synthesize as speech. Plain text only.",
  translate: "Comma-separated language codes to translate into before synthesizing (e.g. 'hi,mr' for Hindi + Marathi). Uses the locally-installed Sarvam-translate model.",
  image: "Source image path to edit/restyle.",
  instruction: "Free-form edit instruction (e.g. 'swap background to teal alpine lake', 'add snow on roof'). Sent verbatim to FLUX-Kontext.",
  strength: "How much to transform: 0.3 = minor edit, 0.6 = moderate rework, 0.9 = major restyle. img2img mode only.",
  kenburns: "Apply Ken-Burns zoom/pan motion to the still image.",
  zoom_max: "Max zoom factor for Ken-Burns: 1.0 = no zoom, 1.15 = subtle, 1.3 = strong.",
  fade_out: "Fade-out duration at end of video, in seconds.",
  pages: "Number of pages to generate.",
  symmetry: "Radial symmetry order (4/6/8/12/16/24). 12 is the classic mandala count.",
  rings: "Number of concentric motif rings. Typical 3-9. More rings = denser mandala.",
  complexity: "Pattern density. simple < balanced < elaborate < max. Pick max for adult-coloring-grade work.",
  palette: "Color theme. ink = B&W (best for coloring), soft = pastel, royal = jewel tones.",
  style: "Geometric register. coloring / floral / sacred / luxury / playful / geometric — each picks a different motif vocabulary.",
  size: "Output square size in pixels. 2400 is a good default for printable mandalas.",
  theme: "Children's-book theme. Determines the motif vocabulary (e.g. rabbits-garden, crows-texas, blue-jay).",
  topic: "Topic sentence for the episode brief. The LLM expands this into 3 thumbnails + an intro.",
  video: "Video file to mux audio onto, or to use as the loop track for an audiobook.",
  rtf: "Source RTF or text file for the audiobook pipeline.",
  langs: "Comma-separated language codes (e.g. 'en,hi,mr' for English + Hindi + Marathi).",
  audio: "Audio file to mux onto the image to produce a Ken-Burns video.",
  bed: "Ambient sound bed under the narration. vinyl-static gives that ASMR podcast feel.",
  mode: "ASMR pacing mode. asmr = slower with longer pauses, normal = standard reading pace.",
  english_engine: "English TTS engine. kokoro = neural (best quality), say = macOS built-in (zero-install).",
  caption: "Subtitle / caption format to emit alongside the audio.",
  captions: "Subtitle / caption format to emit alongside the audio.",
  subtitle_mode: "Subtitle output format. srt = classic, vtt = modern web standard, none = skip.",
  force: "Re-render even if cached output exists.",
  offline_skip_check: "Skip the model-readiness check (offline mode only).",
  real: "Note: real GPU microbenchmarks are NOT yet implemented. The current backend only writes conservative probe metadata regardless of this flag. Tracked as a separate task.",
  full: "Include the per-model breakdown (slower).",
  dry_run: "Preview-only — show what would happen without doing it.",
  yes: "Skip per-file confirmations.",
  remove: "Repos to remove entirely, one per line (e.g. 'org/repo').",
  delete_source: "Delete the source file after adopting it into ~/Models/.",
  as: "Where in ~/Models/ to adopt the file: flux-bfl, kokoro, huggingface, ollama.",
  path: "File path on disk.",
  id: "Identifier (kebab-case).",
  // Children's coloring book — friendly form fields
  cb_tradition: "Illustrator tradition. mo-willems-minimal (12-20 strokes, two-dot eyes), sandra-boynton-whimsical (chunky rounded animals), eric-carle-bold (thick outlines, large fillable shapes), beatrix-potter-naturalistic (pen-and-ink small mammals), miyazaki-storyboard (confident pen line, environmental detail), hanna-barbera-flat-cartoon (geometric forms, white-sclera dot-pupil eyes).",
  cb_age_range: "Target age. toddler-3-5 (min region 30mm, ≤5 elements, thick outlines), kids-6-9 (min 8mm, ≤10 elements, medium line), pre-teen-10-12 (min 4mm, ≤20 elements, fine detail).",
  cb_density: "Scene density. sparse = 3-5 named elements (toddler-grade), balanced = 7-12 (kids), rich = 15+ (pre-teen). Pulled from the npj 2020 streamlining research — fewer elements = better comprehension.",
  cb_archetype: "Central character template. The engine injects the archetype's description (e.g. curious-bear-cub = rounded body, small ears, ALWAYS gentle — never showing teeth). Pick the closest match to your prompt's subject.",
  cb_setting: "Where the scene takes place. Each setting has its own descriptive expansion in the prompt (e.g. enchanted-forest = 3-5 stylized trees + mushrooms + ferns; texas-backyard-patio = live oak + plank fence + bluebonnets).",
  cb_moment: "The single narrative beat the page captures. first-meeting / shared-secret / bedtime-blessing require ≥2 characters. The engine baking in 'one moment per page' is the +32.86% comprehension boost from the npj research.",
  cb_emotion: "What the central character is feeling. Surfaces as specific facial-expression directives (e.g. gentle = eyes half-lidded, small closed smile, body relaxed).",
  cb_props: "What the character is holding or with. Pick no-prop for character-only focus. Engine-defined props include balloon, picnic-basket, lantern-glowing, steel-thali-of-seed (Marathi feeding-birds), chai-cup-and-saucer, etc.",
  cb_character_count: "Exact count of named figures in the scene. 1-6. Some narrative moments (first-meeting, shared-secret) require ≥2 and will fail validation if set lower.",
  // Mandala art — friendly form fields
  ma_tradition: "Decorative tradition. zentangle-organic (Thomas + Roberts 2003: micro-pattern fills per region), sacred-geometry (Sri Yantra, Flower of Life — needs rotational symmetry), henna-mehndi (paisley + lotus + vine, bridal-grade density), madhubani-mandala (Mithila folk tradition with double-line borders), floral-art-nouveau (Mucha-style botanical framing).",
  ma_treatment: "How the subject relates to the mandala. subject-silhouette-filled (whale outline filled with patterns), subject-at-center-rings (lotus at center, rings build outward), subject-radial-composed (butterflies tiled radially — needs rotational symmetry), subject-emerging-mandala (tree roots ARE the mandala).",
  ma_symmetry: "Symmetry order. bilateral = left-right mirror (animals). 4/6/8/12/16-fold-rotational = repeats around center every 90/60/45/30/22.5°. kaleidoscope = full dihedral.",
  ma_complexity: "Pattern density. medium-adult (~50 regions, 30-60min coloring), high-meditation (~100-150 regions, 2-4 hrs), extreme-zentangle (200+ regions, evening-long page).",
  ma_border: "Outer frame. concentric-rings (multiple bands), outer-frame-square (square around the circle), freeform-bleed (no formal border), hexagonal-frame (sacred-geometry style).",
  // Audiobook common
  book: "Path to source book file. Supported: .rtf, .txt. Use the Browse button to pick from your filesystem.",
  title: "Used in the output filename. Keep it short and filesystem-friendly (no slashes). Defaults to 'Untitled' if blank.",
  chunk_chars: "How many characters per TTS chunk. 1400 is the safe default — bigger chunks risk running out of memory on long passages, smaller chunks produce more concatenation artifacts. Only change if you hit OOM or want chunked previews.",
  max_chunks: "Cap on number of chunks to render. Blank = render the whole book. Useful for quick previews — set to 1 or 2 to hear the first minute before committing to a full run.",
  // Audiobook-ASMR specific
  folder: "Pick a folder that contains a transcript file (.rtf or .txt) and optionally a loop video (.mp4, .mov). The pipeline will auto-detect those and place outputs in <folder>/output/. The fastest way to start: drop a transcript and a 1-minute video into a folder, point this here, hit Run.",
  rtf: "Transcript file path. RTF or plain text. Only needed if you're not using the Folder mode above. The pipeline parses paragraphs from this file as the audio script.",
  out_dir: "Where outputs land. Each language gets its own <lang>.wav (or .mp4 if video is set), plus thumbnails and a manifest.json with timings. If you used Folder mode, this is auto-set to <folder>/output/.",
  video: "Optional loop video (.mp4 / .mov / .m4v). When set, the rendered audio is overlaid onto this video — looped seamlessly if the video is shorter than the audio. Leave blank for pure-audio output (no video).",
  langs: "Comma-separated language codes. en = English (Kokoro neural or macOS say). hi = Hindi (Sarvam Bulbul). mr = Marathi (Sarvam Bulbul, default speaker 'manan'). Each language produces a complete separate output.",
  max_chars: "Maximum characters per spoken sentence. Long sentences get broken at this limit (with re-punctuation) so the TTS doesn't choke. 500 works well for most books; lower to 300 if you hear glitches.",
  max_words: "Total spoken-word cap for the WHOLE audiobook (across all batches). Blank = render every word. Set to e.g. 200 if you want a quick preview.",
  batch_pages: "How many source pages per render batch. The full audiobook is rendered batch-by-batch and stitched together. Default 10 pages × 250 words = ~one minute of audio per batch.",
  page_words: "Approximate words per source page. Used only for splitting batches; doesn't change how the text is spoken.",
  spoken_words: "Target spoken words per page in the OUTPUT (after translation and ASMR pacing). Slightly less than source page-words because ASMR mode adds pauses.",
  batches: "Render only specific batch numbers. e.g. '1' for just the first batch, '2-4' for batches 2 through 4, '1,3,5' for non-contiguous. Useful when re-rendering specific sections without redoing the whole book.",
  bed: "Ambient sound bed layered under the narration. vinyl-crackle = warm record-player static (sleep-friendly). silence = no bed. Other choices reflect the AUDIOBOOK_BEDS options compiled into bin/audiobook.py.",
  mode: "Voice pacing. asmr = slower with longer sentence + paragraph pauses (good for sleep / meditation). normal = standard reading pace. The mode shifts the default pause-lengths but you can still override them below.",
  english_engine: "English TTS backend. kokoro = neural (best quality, ~80MB model). say = macOS built-in (zero-install, lower quality). Auto-falls-back to say if Kokoro isn't installed — run 'Setup voices' to install it once.",
  subtitles: "Subtitle/caption format produced alongside the audio. srt = classic format (works in VLC + most players). vtt = WebVTT (modern web video standard). none = skip subtitles.",
  thumbnail: "Generate one thumbnail per language. Each is a single frame grabbed from the video (or rendered fresh if no video) + the headline/subhead text overlaid. Defaults on — uncheck if you'll add your own.",
  thumb_preset: "Brand preset for the overlaid text on thumbnails. thumbnail-bold is tuned specifically for video-thumbnail use (96px title, 34px sub, 1/3-screen dim band).",
  thumb_seed: "Seed for the thumbnail FLUX render (only used if no video is provided — otherwise we grab a frame from the video, no FLUX involved).",
  thumb_frame_at: "When grabbing a frame from the video for the thumbnail, which second to grab. Blank = use the middle of the video.",
  sarvam_speaker: "Hindi speaker voice for Sarvam Bulbul v3 cloud TTS. 22 speakers in v3 (validated against the live API). Recommended for audiobook narration: Priya (warm female, current default), Shreya, or Neha. For male narration: Shubh (Sarvam's neutral default) or Rohan (warmer). Aditya / Manan are correct but flat for long-form.",
  sarvam_speaker_mr: "Marathi speaker. Defaults to Shreya (warm female narrator). Other good Marathi narration options: Priya, Neha, Rohan. Manan was the older default — correct but neutral/flat for long-form.",
  sarvam_hi_speaker: "Hindi narrator voice. 22 Sarvam Bulbul v3 speakers validated against the live API. For audiobook warmth: Priya (female, default), Shreya, Neha, Pooja. Clear male narration: Shubh, Rohan. Default Priya.",
  sarvam_mr_speaker: "Marathi narrator voice. Same Sarvam v3 speaker pool. For audiobook narration: Shreya (female, default), Priya, Neha (female) or Rohan, Sumit (male). Default Shreya.",
  sent_pause_ms: "Silent pause between sentences, in milliseconds. ASMR default 600ms makes the narration breathe; normal mode trims this to ~300ms.",
  para_pause_ms: "Silent pause between paragraphs (slightly longer than sentence pauses). ASMR default 1200ms gives proper section breathing room.",
  // Indian folk art — friendly form fields
  ic_tradition: "Indian folk/classical tradition. madhubani = Mithila double-line borders + huge eyes + flat saturated colors (Sita Devi). warli = monochrome white-rice-paste on brown earth, geometric stick figures (Maharashtra). tanjore = hieratic gold-leaf deity panels (Tamil Nadu). pahari-miniature = delicate jewel-tone scenes (Punjab Hills, Basohli/Kangra). ravi-varma-oleograph = European-realist 19th-c oleograph naturalism.",
  ic_mudra: "Hand gesture / body pose. abhaya = right hand raised, palm out (fearlessness). varada = palm down (giving). dhyana = both palms in lap (meditation). vitarka = thumb + index touching (teaching). anjali = palms together at chest (greeting). tribhanga-flute = three-bend Krishna stance with flute.",
  ic_ground: "Where the scene takes place. madhubani-paper = cream paper with floral border bands (use with madhubani tradition). warli-mud-wall = brown earth wall, white pigment only (use with warli). warli-tarpa-circle = brown ground with central chauk + circular tarpa dance (use with warli). temple-interior / forest-grove / river-bank-yamuna / cosmic-water / celestial-sky / village-pastoral = classical settings for tanjore / pahari / ravi-varma.",
  ic_composition: "Figure arrangement. hieratic-centered = one large deity at center, attendants small around. narrative-multi-figure = scene unfolding across the canvas (e.g. tarpa dance, Krishna's leelas). lyric-intimate = two-figure close composition. cosmic-cosmic = vast multi-scale cosmological tableau.",
  // Stylized cinematic — friendly form fields
  sc_tradition: "Visual register. tartakovsky-cel = flat-color cel + thick uniform ink (Samurai Jack 2001, Primal 2019). darksiders-comic = thick-ink heroic anatomy + apocalyptic palette (Joe Mad). mignola-hellboy-ink = pure black masses + single saturated accent (Hellboy 1993). mcquarrie-conceptual = painterly skies dominating hard-edged silhouettes (Star Wars concept 1975-83). studio-ghibli-painterly = soft gouache+watercolor backgrounds (Kazuo Oga, Yoji Takeshige).",
  sc_time_of_day: "Cinematographer-grounded time-of-day. pre-dawn-blue (8000-10000K, sun -6° to -12°). civil-dawn (4500-6500K, sun -3° to +3°). golden-hour-late (2700-3500K, sun +3° to +10°). harsh-noon (5500-6500K, sun +60°+). blue-hour (9000-12000K, sun -4° to -8°, the cinematic moment for city lights). urban-night-sodium (2200-2800K street lamps). moonlit-night (4100K reflected sunlight). starlit-night-rural (deep cobalt sky, no light pollution).",
  sc_sky_state: "Sky as a character. clear-blue = smooth gradient. partly-cumulus = friendly cotton-puff sky. dramatic-cumulus = vertical stacks with crepuscular rays. cirrus-streak = high wispy ice clouds. overcast-blanket = featureless soft-shadow sky. sunset-pastel = magenta + amber gradient. starfield-rural / milky-way-band = deep-sky astronomy. aurora-curtain = green/magenta high-latitude. stormy-cloud-anvil = anvil-headed cumulonimbus.",
  sc_twinkles: "Small light sources. none = subject + major light only. scattered-fireflies = 8-20 warm-yellow specks. distant-city-lights = pin-prick window-lights at horizon. candle-cluster = warm 1850K candle flames. fairy-lights-string = even-spaced warm-white dots. lantern-cluster = paper lanterns (Diwali / Mid-Autumn register). sparse-stars = 30-80 visible stars (early evening). dense-star-field = 200+ stars (rural deep sky). bioluminescent-water = blue-green plankton glow.",
  sc_atmosphere: "Air medium. clear-dry = sharp colors + distance visibility. fog-low = ground-level dense fog, mystery+isolation register. mist-mid = waist-to-head-height mist, painterly depth (Ghibli classic). rain-streak = diagonal rain lines + wet surfaces. smoke-haze = warm-tinted hanging smoke (urban / fire / cigar register). dust-mote = floating particles caught in light shafts. snow-fall = active snowflakes + breath-puffs. volumetric-shaft = visible god-rays through windows / canopy / barn doors.",
  upscale: "Post-render upscale via RealESRGAN-ncnn-vulkan. The SAFE path to high resolution on M5 Max — renders FLUX at default 1280×720 (low memory, ~3 min), then external upscaler boosts to 4× / 8× in ~6-15 seconds. 8× = 10240×5760 (59 MP), comfortably print-ready. Native Hi-res / Ultra-res checkboxes below are now SECONDARY — use upscale instead. (For --from-image / Kontext runs, native Hi-res is auto-clamped to default size because Kontext + high-res over-subscribes Metal memory and can freeze the GPU.)",
  quantize: "mflux model weight quantization (Apple Silicon). Lower bits = lower RAM + slightly faster. Default q8 is indistinguishable from fp16. q4 is ~10 % faster on M5 Max with mild face softening. q0 forces full fp16 (max quality, slowest, ~24 GB). Set FORGE_FLUX_QUANTIZE env var to change the default for all renders. NOTE: weight quantization is NOT the big speed lever on Apple Silicon — the activations stay fp16. The big levers are step count + resolution + schnell vs dev.",
  no_default_loras: "By default, each engine auto-applies its curated LoRA stack (see brand/loras/README.md) — RealismLora + add-details for wildlife, film-noir + add-details for noir-cinema, Coloring-Book LoRA for childrens-coloring-book, Van Gogh for impressionist, Indo-Realism for indian-classical. Check this box to render WITHOUT them (vanilla FLUX) — useful for A/B comparison or when iterating on a new prompt without LoRA bias. Engines without curated picks (mandala-art) ignore this flag.",
};

function optionsFor(field) {
  const cfg = state.config || {};
  if (field.choices) return field.choices.map(v => ({ value:v, label:v }));
  // Render Mode — unified speed/quality knob. Replaces the separate draft
  // checkbox. Preview is the fast-scout pass; Production is the print-grade
  // final. Backend values stay stable (cool/balanced/max/quality) so existing
  // scripts and CLI invocations keep working.
  if (field.options === "profiles") return [
    {value:"",          label:"(engine default)"},
    {value:"cool",      label:"Preview — schnell @ 4 steps (~25 s)"},
    {value:"balanced",  label:"Balanced — dev @ 18 steps (~3 min)"},
    {value:"max",       label:"Max — dev @ 25 steps (~5 min)"},
    {value:"quality",   label:"Production — dev @ 36 steps + fp16 (~12 min)"},
  ];
  if (field.options === "seriesOptional") return [{value:"", label:"none"}, ...(cfg.series || []).map(v => ({value:v, label:v}))];
  if (field.options === "presetsOptional") return [{value:"", label:"none"}, ...(cfg.presets || []).map(v => ({value:v, label:v}))];
  if (field.options === "enginesOptional") return [{value:"", label:"all"}, ...(cfg.engines || []).map(v => ({value:v, label:v}))];
  if (field.options === "recipesOptional") return [{value:"", label:"none"}, ...(cfg.recipes || []).map(v => ({value:v.id, label:v.engine ? `${v.id} · ${v.engine}` : v.id}))];
  if (field.options === "recipesColoring") return [{value:"", label:"(write your own prompt)"}, ...((cfg.recipes || []).filter(r => r.engine === "childrens-coloring-book").map(r => ({value:r.id, label:r.id})))];
  if (field.options === "recipesMandala") return [{value:"", label:"(write your own prompt)"}, ...((cfg.recipes || []).filter(r => r.engine === "mandala-art").map(r => ({value:r.id, label:r.id})))];
  if (field.options === "voices") return (cfg.voices || []).map(v => ({value:v.id, label:v.label || v.id}));
  // Children's coloring book enums (mirror bin/style_engines.py)
  if (field.options === "cbTraditions") return ["mo-willems-minimal", "sandra-boynton-whimsical", "eric-carle-bold", "beatrix-potter-naturalistic", "miyazaki-storyboard", "hanna-barbera-flat-cartoon"].map(v => ({value:v, label:v}));
  if (field.options === "cbAgeRanges") return ["toddler-3-5", "kids-6-9", "pre-teen-10-12"].map(v => ({value:v, label:v}));
  if (field.options === "cbDensity") return ["sparse", "balanced", "rich"].map(v => ({value:v, label:v}));
  if (field.options === "cbArchetypes") return [{value:"from-prompt", label:"(from prompt — let your text decide)"}, ...["friendly-dragon", "curious-bear-cub", "brave-rabbit", "wise-owl", "whimsical-fox", "gentle-giant", "adventurous-child", "helpful-elephant", "mischievous-mouse", "elderly-marathi-couple", "songbird-flock", "blue-jay-with-finches", "cottontail-rabbit-and-kit"].map(v => ({value:v, label:v}))];
  if (field.options === "cbSettings") return [{value:"from-prompt", label:"(from prompt — let your text decide)"}, ...["enchanted-forest", "cozy-cottage-interior", "magical-meadow", "by-the-pond", "treehouse-platform", "starry-night-rooftop", "village-square", "mountain-cave", "texas-backyard-patio"].map(v => ({value:v, label:v}))];
  if (field.options === "cbMoments") return [{value:"from-prompt", label:"(from prompt — let your text decide)"}, ...["first-meeting", "shared-secret", "problem-discovered", "decision-to-help", "big-leap", "triumph-celebration", "quiet-rest", "bedtime-blessing", "wildlife-visit"].map(v => ({value:v, label:v}))];
  if (field.options === "cbEmotions") return [{value:"from-prompt", label:"(from prompt — let your text decide)"}, ...["curious", "joyful", "worried-but-brave", "gentle", "triumphant", "sleepy-content", "determined", "surprised-delighted"].map(v => ({value:v, label:v}))];
  if (field.options === "cbProps") return ["no-prop", "balloon", "teacup-and-saucer", "picnic-basket", "storybook-open", "paper-boat", "flower-bouquet", "lantern-glowing", "kite-and-string", "steel-thali-of-seed", "bird-feeder-tube", "chai-cup-and-saucer", "rocking-chair-side"].map(v => ({value:v, label:v}));
  // Mandala-art enums (mirror bin/style_engines.py)
  if (field.options === "maTraditions") return ["zentangle-organic", "sacred-geometry", "henna-mehndi", "madhubani-mandala", "floral-art-nouveau"].map(v => ({value:v, label:v}));
  if (field.options === "maTreatments") return [{value:"from-prompt", label:"(from prompt — let your text decide)"}, ...["subject-silhouette-filled", "subject-at-center-rings", "subject-radial-composed", "subject-emerging-mandala"].map(v => ({value:v, label:v}))];
  if (field.options === "maSymmetries") return [{value:"from-prompt", label:"(from prompt — let your text decide)"}, ...["bilateral", "4-fold-rotational", "6-fold-rotational", "8-fold-rotational", "12-fold-rotational", "16-fold-rotational", "kaleidoscope"].map(v => ({value:v, label:v}))];
  if (field.options === "maComplexity") return [{value:"from-prompt", label:"(from prompt — let your text decide)"}, ...["medium-adult", "high-meditation", "extreme-zentangle"].map(v => ({value:v, label:v}))];
  if (field.options === "maBorders") return [{value:"from-prompt", label:"(from prompt — let your text decide)"}, ...["concentric-rings", "outer-frame-square", "freeform-bleed", "hexagonal-frame"].map(v => ({value:v, label:v}))];
  // Indian-classical (folk) enums (mirror bin/style_engines.py)
  if (field.options === "recipesIndian") return [{value:"", label:"(write your own prompt)"}, ...((cfg.recipes || []).filter(r => r.engine === "indian-classical").map(r => ({value:r.id, label:r.id})))];
  if (field.options === "icTraditions") return ["madhubani", "warli", "tanjore", "pahari-miniature", "ravi-varma-oleograph"].map(v => ({value:v, label:v}));
  if (field.options === "icMudras") return [{value:"from-prompt", label:"(from prompt — let your text decide)"}, ...["abhaya", "varada", "dhyana", "vitarka", "anjali", "tribhanga-flute"].map(v => ({value:v, label:v}))];
  if (field.options === "icGrounds") return [{value:"from-prompt", label:"(from prompt — let your text decide)"}, ...["madhubani-paper", "warli-mud-wall", "warli-tarpa-circle", "temple-interior", "forest-grove", "river-bank-yamuna", "cosmic-water", "celestial-sky", "village-pastoral"].map(v => ({value:v, label:v}))];
  if (field.options === "icCompositions") return [{value:"from-prompt", label:"(from prompt — let your text decide)"}, ...["hieratic-centered", "narrative-multi-figure", "lyric-intimate", "cosmic-cosmic"].map(v => ({value:v, label:v}))];
  // Stylized-cinematic enums (mirror bin/style_engines.py)
  if (field.options === "scTraditions") return [{value:"from-prompt", label:"(from prompt — let your text decide)"}, ...["tartakovsky-cel", "darksiders-comic", "mignola-hellboy-ink", "mcquarrie-conceptual", "studio-ghibli-painterly"].map(v => ({value:v, label:v}))];
  if (field.options === "scTimeOfDay") return [{value:"from-prompt", label:"(from prompt — let your text decide)"}, ...["pre-dawn-blue", "civil-dawn", "mid-morning", "harsh-noon", "golden-hour-late", "golden-hour-low", "blue-hour", "urban-night-sodium", "moonlit-night", "starlit-night-rural", "aurora-magic"].map(v => ({value:v, label:v}))];
  if (field.options === "scSkyStates") return [{value:"from-prompt", label:"(from prompt — let your text decide)"}, ...["clear-blue", "partly-cumulus", "dramatic-cumulus", "cirrus-streak", "overcast-blanket", "sunset-pastel", "starfield-rural", "milky-way-band", "aurora-curtain", "stormy-cloud-anvil"].map(v => ({value:v, label:v}))];
  if (field.options === "scTwinkles") return [{value:"from-prompt", label:"(from prompt — let your text decide)"}, ...["none", "scattered-fireflies", "distant-city-lights", "candle-cluster", "fairy-lights-string", "lantern-cluster", "sparse-stars", "dense-star-field", "bioluminescent-water"].map(v => ({value:v, label:v}))];
  if (field.options === "scAtmospheres") return [{value:"from-prompt", label:"(from prompt — let your text decide)"}, ...["clear-dry", "fog-low", "mist-mid", "rain-streak", "smoke-haze", "dust-mote", "snow-fall", "volumetric-shaft"].map(v => ({value:v, label:v}))];
  // Unified Create page style picker — maps to engine names used by build_command.
  if (field.options === "styleOptions") return [
    {value:"childrens-coloring-book", label:"Children's coloring book — B&W line-art for kids"},
    {value:"mandala-art",             label:"Mandala art — ornamental B&W line-art"},
    {value:"indian-classical",        label:"Indian folk art — Madhubani / Warli / Tanjore / Pahari (colored)"},
    {value:"stylized-cinematic",      label:"Stylized cinematic — Tartakovsky / Mignola / McQuarrie / Ghibli"},
  ];
  // Recipes filtered to currently-selected Style on the unified Create page.
  if (field.options === "recipesAll") {
    const styleEl = document.querySelector('[name="style"]');
    const currentStyle = styleEl ? styleEl.value : "";
    const all = (cfg.recipes || []);
    const filtered = currentStyle ? all.filter(r => r.engine === currentStyle) : all;
    return [{value:"", label:"(write your own prompt)"}, ...filtered.map(r => ({value:r.id, label:r.id}))];
  }
  // RealESRGAN post-render upscale — safer than native hi-res, near-zero memory cost.
  // Native binary supports 2/3/4; non-native factors (6/8/12/16) chain two passes.
  if (field.options === "upscaleOptions") return [
    {value:"",    label:"none (base size — 1280×720 default)"},
    {value:"2x",  label:"2× → 2560×1440 (~6 s)"},
    {value:"3x",  label:"3× → 3840×2160 / 4K UHD (~6 s)"},
    {value:"4x",  label:"4× → 5120×2880 (~6 s)"},
    {value:"6x",  label:"6× → 7680×4320 / 8K UHD (~12 s, chained 3×→2×)"},
    {value:"8x",  label:"8× → 10240×5760 (~15 s, chained 4×→2×) — recommended for print"},
    {value:"12x", label:"12× → 15360×8640 (~18 s, chained 4×→3×)"},
    {value:"16x", label:"16× → 20480×11520 (~30 s, chained 4×→4×) — experimental"},
  ];
  // mflux --quantize selector (env default = q8 if not set)
  if (field.options === "quantizeOptions") return [
    {value:"",  label:"default (q8 — balanced, indistinguishable from fp16)"},
    {value:"0", label:"q0 — fp16 (max quality, slowest, ~24 GB)"},
    {value:"8", label:"q8 — 8-bit (default, ~12 GB, no quality loss)"},
    {value:"6", label:"q6 — 6-bit (~9 GB, very mild quality dip)"},
    {value:"5", label:"q5 — 5-bit (~8 GB, mild dip)"},
    {value:"4", label:"q4 — 4-bit (~6 GB, ~10% faster, faces softer)"},
    {value:"3", label:"q3 — 3-bit (~5 GB, visible quality drop)"},
  ];
  return (cfg[field.options] || []).map(v => ({value:v, label:v}));
}

function renderActions() {
  const root = document.getElementById("actions");
  root.innerHTML = "";
  for (const [title, rows] of groups) {
    const h = document.createElement("div");
    h.className = "group-title";
    h.textContent = title;
    root.appendChild(h);
    const list = document.createElement("div");
    list.className = "action-list";
    for (const [id, label] of rows) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "action" + (id === state.action ? " active" : "");
      btn.textContent = label;
      btn.onclick = () => { state.action = id; renderActions(); renderForm(); };
      list.appendChild(btn);
    }
    root.appendChild(list);
  }
}

function fieldElement(field) {
  // Helper: tag the returned node with data-show-when so applyShowWhen()
  // can hide/show it based on another field's value. Inner inputs are
  // disabled when hidden so gatherPayload skips them.
  function withShowWhen(node, field) {
    if (field && field.showWhen) {
      try { node.dataset.showWhen = JSON.stringify(field.showWhen); }
      catch (e) { /* ignore */ }
    }
    return node;
  }
  // Collapsed <details> wrapping a list of inner fields — for "power-user
  // knobs that most people never touch". Form input events bubble up so the
  // command preview still updates when these are tweaked.
  if (field.type === "expander") {
    const details = document.createElement("details");
    details.className = "form-expander";
    const summary = document.createElement("summary");
    summary.textContent = field.label;
    details.appendChild(summary);
    if (field.hint) {
      const hint = document.createElement("div");
      hint.className = "form-section-hint";
      hint.textContent = field.hint;
      details.appendChild(hint);
    }
    for (const sub of (field.fields || [])) {
      details.appendChild(fieldElement(sub));
    }
    return withShowWhen(details, field);
  }
  if (field.type === "section") {
    const sec = document.createElement("div");
    sec.className = "form-section";
    sec.textContent = field.label;
    if (field.hint) {
      const hint = document.createElement("div");
      hint.className = "form-section-hint";
      hint.textContent = field.hint;
      sec.appendChild(hint);
    }
    return withShowWhen(sec, field);
  }
  const wrap = document.createElement("div");
  wrap.className = "field";
  // Label + optional ? info icon in a flex row.
  const labelRow = document.createElement("div");
  labelRow.className = "label-row";
  const label = document.createElement("label");
  label.htmlFor = `field-${field.name}`;
  label.textContent = field.label;
  labelRow.appendChild(label);
  const help = FIELD_HELP[field.name];
  if (help) {
    const info = document.createElement("button");
    info.type = "button";
    info.className = "info-icon";
    info.textContent = "?";
    info.title = "What's this?";
    info.onclick = (e) => { e.preventDefault(); showHelpModal(field.label, help); };
    labelRow.appendChild(info);
  }
  wrap.appendChild(labelRow);
  if (field.type === "textarea") {
    const el = document.createElement("textarea");
    el.id = `field-${field.name}`;
    el.name = field.name;
    el.value = field.value || "";
    el.required = !!field.required;
    wrap.appendChild(el);
  } else if (field.type === "select") {
    const el = document.createElement("select");
    el.id = `field-${field.name}`;
    el.name = field.name;
    el.required = !!field.required;
    for (const opt of optionsFor(field)) {
      const option = document.createElement("option");
      option.value = opt.value || "";
      option.textContent = opt.label || opt.value || "";
      if ((field.value || "") === option.value) option.selected = true;
      el.appendChild(option);
    }
    wrap.appendChild(el);
  } else if (field.type === "checkbox") {
    wrap.classList.add("check");
    wrap.innerHTML = "";
    const el = document.createElement("input");
    el.type = "checkbox";
    el.id = `field-${field.name}`;
    el.name = field.name;
    el.checked = !!field.checked;
    const span = document.createElement("label");
    span.htmlFor = el.id;
    span.textContent = field.label;
    wrap.append(el, span);
  } else if (field.type === "path") {
    const row = document.createElement("div");
    row.className = "path-row";
    const el = document.createElement("input");
    el.id = `field-${field.name}`;
    el.name = field.name;
    el.value = field.value || "";
    el.required = !!field.required;
    el.spellcheck = false;
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = "Browse";
    btn.onclick = () => openPicker(field.name);
    row.append(el, btn);
    wrap.appendChild(row);
  } else {
    const el = document.createElement("input");
    el.id = `field-${field.name}`;
    el.name = field.name;
    el.type = field.type || "text";
    el.value = field.value || "";
    el.required = !!field.required;
    el.spellcheck = false;
    wrap.appendChild(el);
  }
  return withShowWhen(wrap, field);
}

async function fetchAndRenderSuggestion(engine, formEl) {
  if (!engine) return;
  try {
    const res = await fetch(`/api/suggestions?engine=${encodeURIComponent(engine)}`);
    if (!res.ok) return;
    const data = await res.json();
    const s = data.suggestion;
    if (!s) return;  // not enough rated data yet
    const banner = document.createElement("div");
    banner.className = "suggestion-banner";
    banner.innerHTML = `
      <div class="suggestion-summary">${escapeHtml(s.summary)}</div>
      <button type="button" id="applySuggestion">Apply</button>
    `;
    formEl.insertBefore(banner, formEl.firstChild);
    document.getElementById("applySuggestion").onclick = () => applySuggestion(s);
  } catch (e) {
    // silent — suggestion is an enhancement, not a blocker
  }
}

function applySuggestion(s) {
  // Set form fields from the suggestion's modal/avg values where they apply.
  // We only touch fields the user hasn't explicitly modified yet — but for
  // simplicity here we just overwrite. User can always change after.
  const setIfPresent = (name, val) => {
    if (val == null) return;
    const el = document.getElementById(`field-${name}`);
    if (el) {
      if (el.type === "checkbox") el.checked = !!val;
      else el.value = val;
      el.dispatchEvent(new Event("input", {bubbles: true}));
    }
  };
  if (s.seed_modal != null) setIfPresent("seed", s.seed_modal);
  if (s.guidance_avg != null) setIfPresent("guidance", s.guidance_avg);
  if (s.refine_ratio >= 0.6) setIfPresent("refine", true);
  if (s.hi_res_ratio >= 0.6) setIfPresent("hi_res", true);
  if (s.ultra_res_ratio >= 0.6) setIfPresent("ultra_res", true);
  if (s.top_recipes && s.top_recipes[0]) setIfPresent("recipe", s.top_recipes[0]);
  showToast(`Applied top-rated config (${s.sample_size} rated renders)`, "success");
}

// ─── Gallery view ─────────────────────────────────────────────────────────
// All historical renders, filterable, with inline ratings. Repurposes the
// form panel as a 3-up grid; cards show thumbnail + metadata + 4 rating
// buttons (👎 — 👍 ⭐). Click a card to open the detail modal.

const state_gallery = { engine: "all", rating: "all", order: "ts_desc", selected: new Set() };

async function renderGalleryPanel() {
  document.getElementById("formTitle").textContent = "Gallery";
  document.getElementById("commandPreview").textContent = "";
  const form = document.getElementById("jobForm");
  form.innerHTML = "";

  // Rating-system explainer — collapsed by default. Surfaces the
  // "what happens when I rate?" question directly so users know
  // the system isn't a black box.
  const explainer = document.createElement("details");
  explainer.className = "form-expander";
  explainer.innerHTML = `
    <summary>▾ What happens when I rate a render?</summary>
    <div class="form-section-hint" style="margin-top:8px; line-height:1.5;">
      Ratings drive a <strong>config-level learning loop</strong>, NOT FLUX weight retraining.
      The FLUX model itself stays frozen — what we tune is the engine's <em>recipe defaults</em>:
      <ul style="margin:8px 0 0 18px; padding:0;">
        <li><strong>👍 / ⭐ Liked renders</strong> contribute to that engine's "top-rated config":
            their seed family, guidance value, refine/hi-res flags get averaged into the
            smart-suggestion banner that appears at the top of every Create form.</li>
        <li><strong>👎 Disliked renders</strong> are downweighted — their seeds + configs are
            avoided in future suggestions.</li>
        <li><strong>Aggregate signal</strong>: after ~10 ratings per engine, the engine's
            default seed shifts toward the modal liked seed, default guidance toward your
            preferred mean, and refine/hi-res toggles toward your habits.</li>
        <li><strong>Notes</strong> you write on a render are kept in the gallery DB but don't
            currently feed back into prompt construction (planned: surface them when picking
            recipes).</li>
      </ul>
      Bottom line: <em>rate ruthlessly — every 👍 / 👎 makes the next render closer to what
      you actually want, at the engine level, without any model retraining.</em>
    </div>
  `;
  form.appendChild(explainer);

  // Filter row + A/B compare control
  const filters = document.createElement("div");
  filters.className = "gallery-filters";
  filters.innerHTML = `
    <label>Engine
      <select id="galEngine"></select>
    </label>
    <label>Rating
      <select id="galRating">
        <option value="all">all</option>
        <option value="2">⭐ favorites</option>
        <option value="1">👍 likes</option>
        <option value="0">— unrated</option>
        <option value="-1">👎 dislikes</option>
      </select>
    </label>
    <label>Sort
      <select id="galOrder">
        <option value="ts_desc">newest first</option>
        <option value="ts_asc">oldest first</option>
        <option value="rating_desc">highest-rated first</option>
      </select>
    </label>
    <button type="button" id="galCompare" class="primary" disabled>Compare (0)</button>
    <button type="button" id="galClearSel">Clear</button>
    <div id="galStats" class="gallery-stats"></div>
  `;
  form.appendChild(filters);

  // Grid container
  const grid = document.createElement("div");
  grid.id = "galleryGrid";
  grid.className = "gallery-grid";
  form.appendChild(grid);

  // Populate filter selects from cfg
  const cfg = state.config || {};
  const engineSel = document.getElementById("galEngine");
  engineSel.innerHTML = `<option value="all">all</option>` +
    (cfg.engines || []).map(e => `<option value="${e}">${e}</option>`).join("");
  engineSel.value = state_gallery.engine;
  document.getElementById("galRating").value = state_gallery.rating;
  document.getElementById("galOrder").value = state_gallery.order;

  engineSel.onchange = (e) => { state_gallery.engine = e.target.value; loadGallery(); };
  document.getElementById("galRating").onchange = (e) => { state_gallery.rating = e.target.value; loadGallery(); };
  document.getElementById("galOrder").onchange = (e) => { state_gallery.order = e.target.value; loadGallery(); };
  document.getElementById("galCompare").onclick = openCompareModal;
  document.getElementById("galClearSel").onclick = () => {
    state_gallery.selected.clear();
    updateCompareButton();
    document.querySelectorAll(".gallery-card.selected").forEach(c => c.classList.remove("selected"));
  };

  await loadGallery();
}

function updateCompareButton() {
  const btn = document.getElementById("galCompare");
  if (!btn) return;
  const n = state_gallery.selected.size;
  btn.textContent = `Compare (${n})`;
  btn.disabled = (n !== 2);
}

async function loadGallery() {
  const params = new URLSearchParams();
  if (state_gallery.engine !== "all") params.set("engine", state_gallery.engine);
  if (state_gallery.rating !== "all") params.set("rating", state_gallery.rating);
  if (state_gallery.order !== "ts_desc") params.set("order_by", state_gallery.order);
  params.set("limit", "120");
  const res = await fetch(`/api/gallery?${params}`);
  if (!res.ok) {
    document.getElementById("galleryGrid").innerHTML = `<div class="empty-state">Failed to load gallery (HTTP ${res.status})</div>`;
    return;
  }
  const data = await res.json();
  renderGalleryStats(data.stats);
  renderGalleryGrid(data.renders);
}

function renderGalleryStats(s) {
  const el = document.getElementById("galStats");
  if (!el) return;
  const ratings = s.by_rating || {};
  el.innerHTML = `<strong>${s.total}</strong> renders · ⭐ ${ratings.favorite || 0} · 👍 ${ratings.like || 0} · 👎 ${ratings.dislike || 0}`;
}

function renderGalleryGrid(renders) {
  const grid = document.getElementById("galleryGrid");
  if (!renders || renders.length === 0) {
    grid.innerHTML = `<div class="empty-state">No renders match the current filters. Run something via the engine actions on the left, then come back here.</div>`;
    return;
  }
  grid.innerHTML = "";
  for (const r of renders) {
    const card = document.createElement("div");
    const isSelected = state_gallery.selected.has(r.id);
    card.className = "gallery-card rating-" + r.rating + (isSelected ? " selected" : "");
    card.dataset.renderId = r.id;
    const fileUrl = `/api/file?path=${encodeURIComponent(r.png_path)}`;
    const seedTxt = r.seed != null ? `seed ${r.seed}` : "";
    const recipeTxt = r.recipe ? `· ${r.recipe}` : "";
    card.innerHTML = `
      <a class="gallery-thumb" href="${fileUrl}" target="_blank" rel="noreferrer">
        <img src="${fileUrl}" loading="lazy" alt="${escapeAttr(r.subject || '')}">
        <span class="gallery-select" title="Click to select for A/B compare"></span>
      </a>
      <div class="gallery-meta">
        <div class="gallery-engine">${r.engine}</div>
        <div class="gallery-sub">${seedTxt} ${recipeTxt}</div>
        <div class="gallery-subject" title="${escapeAttr(r.subject || '')}">${escapeHtml((r.subject || "").slice(0, 90))}</div>
      </div>
      <div class="gallery-ratings" data-render-id="${r.id}">
        ${ratingButton(r.id, -1, r.rating, '👎')}
        ${ratingButton(r.id,  1, r.rating, '👍')}
        ${ratingButton(r.id,  2, r.rating, '⭐')}
        <button class="rate-btn rate-detail" data-detail="${r.id}" title="Details">⋯</button>
        <button class="rate-btn rate-delete" data-delete="${r.id}" title="Delete this render">🗑</button>
      </div>
    `;
    // Click the small select-spot to toggle A/B selection
    card.querySelector(".gallery-select").onclick = (e) => {
      e.preventDefault();
      e.stopPropagation();
      toggleCompareSelect(r.id, card);
    };
    grid.appendChild(card);
  }
  updateCompareButton();
  // Wire rating buttons
  grid.querySelectorAll(".rate-btn[data-rating]").forEach(btn => {
    btn.onclick = async (e) => {
      e.preventDefault();
      const rid = parseInt(btn.dataset.renderId);
      const rating = parseInt(btn.dataset.rating);
      // Toggle behavior: click the same rating → clear it (set to 0)
      const cur = parseInt(btn.parentElement.dataset.currentRating || "0");
      const newRating = (cur === rating) ? 0 : rating;
      const res = await fetch("/api/ratings", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({render_id: rid, rating: newRating}),
      });
      if (res.ok) loadGallery();
      else showToast("Failed to save rating", "error");
    };
  });
  // Detail buttons
  grid.querySelectorAll(".rate-detail").forEach(btn => {
    btn.onclick = () => openRenderDetail(parseInt(btn.dataset.detail));
  });
  // Delete buttons — two-step confirmation (first click = arm; second = delete).
  // Also deletes the PNG file on disk (?file=1).
  grid.querySelectorAll(".rate-delete").forEach(btn => {
    btn.onclick = async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const rid = parseInt(btn.dataset.delete);
      if (btn.dataset.armed !== "1") {
        btn.dataset.armed = "1";
        btn.textContent = "❌ confirm?";
        btn.style.background = "var(--rose)";
        btn.style.color = "var(--bg-deep)";
        setTimeout(() => {
          if (btn.dataset.armed === "1") {
            btn.dataset.armed = "0";
            btn.textContent = "🗑";
            btn.style.background = "";
            btn.style.color = "";
          }
        }, 3500);
        return;
      }
      const res = await fetch(`/api/gallery/${rid}?file=1`, {method: "DELETE"});
      if (res.ok) {
        showToast(`Render #${rid} deleted (DB + file)`, "success");
        loadGallery();
      } else {
        const body = await res.json().catch(() => ({}));
        showToast(body.error || `Delete failed: HTTP ${res.status}`, "error");
      }
    };
  });
}

function toggleCompareSelect(renderId, cardEl) {
  if (state_gallery.selected.has(renderId)) {
    state_gallery.selected.delete(renderId);
    cardEl.classList.remove("selected");
  } else {
    if (state_gallery.selected.size >= 2) {
      // Drop the oldest selection
      const oldest = state_gallery.selected.values().next().value;
      state_gallery.selected.delete(oldest);
      const oldCard = document.querySelector(`.gallery-card[data-render-id="${oldest}"]`);
      if (oldCard) oldCard.classList.remove("selected");
    }
    state_gallery.selected.add(renderId);
    cardEl.classList.add("selected");
  }
  updateCompareButton();
}

async function openCompareModal() {
  const ids = [...state_gallery.selected];
  if (ids.length !== 2) return;
  const [a, b] = await Promise.all([
    fetch(`/api/gallery/${ids[0]}`).then(r => r.json()),
    fetch(`/api/gallery/${ids[1]}`).then(r => r.json()),
  ]);
  const aUrl = `/api/file?path=${encodeURIComponent(a.png_path)}`;
  const bUrl = `/api/file?path=${encodeURIComponent(b.png_path)}`;
  // Compute config-diff highlighting
  const diff = compareConfigs(a, b);
  const body = `<div class="compare-grid">
      <div class="compare-side">
        <div class="compare-head">A · #${a.id} · ${escapeHtml(a.engine)}</div>
        <a href="${aUrl}" target="_blank"><img src="${aUrl}"></a>
        <div class="compare-meta">${renderCompareMeta(a, diff, "a")}</div>
      </div>
      <div class="compare-side">
        <div class="compare-head">B · #${b.id} · ${escapeHtml(b.engine)}</div>
        <a href="${bUrl}" target="_blank"><img src="${bUrl}"></a>
        <div class="compare-meta">${renderCompareMeta(b, diff, "b")}</div>
      </div>
    </div>`;
  showHelpModal(`Compare · #${a.id} vs #${b.id}`, "");
  const bodyEl = document.getElementById("helpBody");
  bodyEl.innerHTML = body;
}

function compareConfigs(a, b) {
  // Return a Set of field keys whose values differ between A and B
  const diff = new Set();
  const fields = ["engine", "recipe", "seed", "guidance", "refine", "hi_res", "ultra_res", "width", "height"];
  for (const f of fields) {
    if (a[f] !== b[f]) diff.add(f);
  }
  // LoRA stack — compare normalized
  const aLora = JSON.stringify(a.lora_stack || []);
  const bLora = JSON.stringify(b.lora_stack || []);
  if (aLora !== bLora) diff.add("lora_stack");
  // Subject text
  if ((a.subject || "") !== (b.subject || "")) diff.add("subject");
  // Rating
  if ((a.rating || 0) !== (b.rating || 0)) diff.add("rating");
  return diff;
}

function renderCompareMeta(r, diff, side) {
  const lora = (r.lora_stack || []).map(l => `${(l.path || '').split('/').pop()}@${l.scale}`).join(", ") || "—";
  const flags = [r.refine && "refine", r.hi_res && "hi-res", r.ultra_res && "ultra-res"].filter(Boolean).join(" · ") || "(default)";
  const ratingLabel = {0: "—", 1: "👍 like", 2: "⭐ favorite", "-1": "👎 dislike"}[String(r.rating || 0)] || "—";
  const dim = (key) => diff.has(key) ? "diff" : "";
  return `
    <div class="${dim('engine')}"><strong>Engine</strong> ${escapeHtml(r.engine)}</div>
    <div class="${dim('recipe')}"><strong>Recipe</strong> ${escapeHtml(r.recipe || '—')}</div>
    <div class="${dim('seed')}"><strong>Seed</strong> ${r.seed ?? '—'}</div>
    <div class="${dim('guidance')}"><strong>Guidance</strong> ${r.guidance ?? 'default'}</div>
    <div class="${dim('refine') || dim('hi_res') || dim('ultra_res')}"><strong>Flags</strong> ${flags}</div>
    <div class="${dim('width') || dim('height')}"><strong>Size</strong> ${r.width || '?'}×${r.height || '?'}</div>
    <div class="${dim('lora_stack')}"><strong>LoRAs</strong> ${escapeHtml(lora)}</div>
    <div class="${dim('rating')}"><strong>Rating</strong> ${ratingLabel}</div>
    <hr>
    <div class="${dim('subject')}"><strong>Subject</strong></div>
    <pre class="compare-subject ${dim('subject')}">${escapeHtml(r.subject || '')}</pre>
  `;
}

function ratingButton(rid, value, current, emoji) {
  const active = current === value ? " active" : "";
  return `<button class="rate-btn rate-${value}${active}" data-render-id="${rid}" data-rating="${value}" title="${value === -1 ? 'Dislike' : value === 1 ? 'Like' : 'Favorite'}">${emoji}</button>`;
}

async function openRenderDetail(rid) {
  const res = await fetch(`/api/gallery/${rid}`);
  if (!res.ok) return;
  const r = await res.json();
  const cfg = r.config_json || {};
  const lora = (r.lora_stack || []).map(l => `${(l.path || '').split('/').pop()}@${l.scale}`).join(", ") || "—";
  const flags = [];
  if (r.refine) flags.push("refine");
  if (r.hi_res) flags.push("hi-res");
  if (r.ultra_res) flags.push("ultra-res");
  const fileUrl = `/api/file?path=${encodeURIComponent(r.png_path)}`;
  const body = `<div class="detail-grid">
      <div class="detail-image"><a href="${fileUrl}" target="_blank"><img src="${fileUrl}"></a></div>
      <div class="detail-meta">
        <div><strong>Engine:</strong> ${r.engine}</div>
        <div><strong>Recipe:</strong> ${r.recipe || "—"}</div>
        <div><strong>Seed:</strong> ${r.seed ?? "—"}</div>
        <div><strong>Guidance:</strong> ${r.guidance ?? "default"}</div>
        <div><strong>Size:</strong> ${r.width || "?"}×${r.height || "?"}</div>
        <div><strong>Flags:</strong> ${flags.join(" · ") || "(default)"}</div>
        <div><strong>LoRAs:</strong> ${escapeHtml(lora)}</div>
        <div><strong>Path:</strong> <code>${escapeHtml(r.png_path)}</code></div>
        <hr>
        <div class="detail-rating-row">
          ${ratingButton(r.id, -1, r.rating, '👎 dislike')}
          ${ratingButton(r.id,  1, r.rating, '👍 like')}
          ${ratingButton(r.id,  2, r.rating, '⭐ favorite')}
        </div>
        <div><strong>Notes</strong></div>
        <textarea id="detailNotes" rows="3" placeholder="What's good/bad about this render?">${escapeHtml(r.notes || '')}</textarea>
        <button id="detailSaveNotes" class="primary">Save notes</button>
        <hr>
        <div><strong>Subject</strong></div>
        <pre class="detail-subject">${escapeHtml(r.subject || '')}</pre>
      </div>
    </div>`;
  showHelpModal(`Render #${r.id}`, "");  // re-use the help modal infrastructure
  // Override body — help modal expects textContent; we want innerHTML for this rich view
  const bodyEl = document.getElementById("helpBody");
  bodyEl.innerHTML = body;
  // Re-wire rating buttons inside the modal
  bodyEl.querySelectorAll(".rate-btn[data-rating]").forEach(btn => {
    btn.onclick = async (e) => {
      e.preventDefault();
      const newRating = parseInt(btn.dataset.rating);
      const res = await fetch("/api/ratings", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({render_id: rid, rating: newRating}),
      });
      if (res.ok) {
        closeHelpModal();
        loadGallery();
      }
    };
  });
  document.getElementById("detailSaveNotes").onclick = async () => {
    const notes = document.getElementById("detailNotes").value;
    await fetch("/api/ratings", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({render_id: rid, rating: r.rating || 0, notes}),
    });
    showToast("Notes saved", "success");
  };
}

function renderForm() {
  // Gallery view is a special case — no form, just a render-grid + filter
  // controls. Repurposes the form panel for browsing instead of submitting.
  if (state.action === "gallery") {
    renderGalleryPanel();
    return;
  }
  const spec = specs[state.action];
  if (!spec) {
    // Unknown action — clear and bail
    document.getElementById("formTitle").textContent = state.action;
    document.getElementById("jobForm").innerHTML = "";
    document.getElementById("commandPreview").textContent = "";
    return;
  }
  document.getElementById("formTitle").textContent = spec.title;
  const form = document.getElementById("jobForm");
  form.innerHTML = "";

  // Smart-suggestion banner — fetch top-rated config for whichever engine
  // this action maps to. Engine-driven actions surface the suggestion
  // automatically; pure pipelines (audiobook / brief / etc) get nothing.
  const engineForAction = {
    "create": null,  // dynamic — derived from the Style picker
    "engine": null,  // user picks engine; we don't know yet
    "coloring-page": "childrens-coloring-book",
    "mandala-art-page": "mandala-art",
    "indian-folk-page": "indian-classical",
    "stylized-cinematic-page": "stylized-cinematic",
  };
  const sugEngine = engineForAction[state.action];
  if (sugEngine !== undefined) {
    // On the Create page, derive engine from the Style picker.
    let engine = sugEngine;
    if (state.action === "create") {
      const styleEl = form.querySelector('[name="style"]');
      engine = styleEl ? styleEl.value : "childrens-coloring-book";
    }
    fetchAndRenderSuggestion(engine || state.pendingEngineForSuggestion, form);
  }

  // Walk fields in order. Sections + textareas span full width; other fields
  // pair into a 2-column grid until interrupted by a section/textarea.
  const fields = spec.fields.filter(f => f.type !== "checkbox");
  const checks = spec.fields.filter(f => f.type === "checkbox");
  let buffer = []; // pending two-col fields
  const flush = () => {
    if (buffer.length === 0) return;
    if (buffer.length === 1) {
      // single dangling field — render full-width
      form.appendChild(fieldElement(buffer[0]));
    } else {
      for (let i = 0; i < buffer.length; i += 2) {
        const row = document.createElement("div");
        row.className = "grid-2";
        row.appendChild(fieldElement(buffer[i]));
        if (buffer[i + 1]) row.appendChild(fieldElement(buffer[i + 1]));
        form.appendChild(row);
      }
    }
    buffer = [];
  };
  for (const f of fields) {
    // Sections, textareas, and expander drawers always span full width.
    // (Expanders contain their own nested fields — they can't share a row.)
    if (f.type === "section" || f.type === "textarea" || f.type === "expander") {
      flush();
      form.appendChild(fieldElement(f));
    } else {
      buffer.push(f);
    }
  }
  flush();
  if (checks.length) {
    const row = document.createElement("div");
    row.className = "checks";
    for (const f of checks) row.appendChild(fieldElement(f));
    form.appendChild(row);
  }
  const runbar = document.createElement("div");
  runbar.className = "runbar";
  const run = document.createElement("button");
  run.type = "submit";
  run.className = "primary";
  run.textContent = "Run";
  runbar.appendChild(run);
  form.appendChild(runbar);
  // Recipe prefill — when the recipe dropdown changes, populate the matching
  // form fields from the recipe's contents. Fixes the leak where form defaults
  // silently override the recipe's subject/config when --recipe is also sent.
  const recipeEl = form.querySelector('[name="recipe"]');
  if (recipeEl) {
    recipeEl.addEventListener("change", () => {
      const recipeId = recipeEl.value;
      if (!recipeId) return;
      const recipe = (state.config.recipes || []).find(r => r.id === recipeId);
      if (!recipe) return;
      const fieldMap = RECIPE_FIELD_MAP[recipe.engine] || {};
      // Generic Engine page: auto-fill the engine select from the recipe so a
      // recipe-only run becomes a one-click flow.
      const engineEl = form.querySelector('[name="name"]');
      if (engineEl && recipe.engine) engineEl.value = recipe.engine;
      if (recipe.subject) {
        const el = form.querySelector('[name="subject"]');
        if (el) el.value = recipe.subject;
      }
      for (const [cfgKey, formFieldName] of Object.entries(fieldMap)) {
        const val = (recipe.config || {})[cfgKey];
        if (val === undefined || val === null || val === "") continue;
        const el = form.querySelector(`[name="${formFieldName}"]`);
        if (el) el.value = String(val);
      }
      if (recipe.seed != null) {
        const el = form.querySelector('[name="seed"]');
        if (el) el.value = recipe.seed;
      }
      if (recipe.guidance != null) {
        const el = form.querySelector('[name="guidance"]');
        if (el) el.value = recipe.guidance;
      }
      updateCommandPreview();
      showToast(`Loaded recipe: ${recipeId}`, "success");
    });
  }
  // Smart-disable: form fields that are no-ops under certain modes get a
  // visual disabled state + tooltip, so the user doesn't believe they're
  // changing the image when they're not. Re-evaluated on every form input.
  function applyFieldGating() {
    const fromImage = (form.querySelector('[name="from_image"]') || {}).value || "";
    const upscale = (form.querySelector('[name="upscale"]') || {}).value || "";
    // When Kontext mode active (from_image set), several controls are no-op:
    //   - guidance: Kontext ignores explicit guidance (uses model default 2.5)
    //   - refine / refine_strength: not run on img2img path
    //   - hi_res / ultra_res: backend rejects native >1280×720 for img2img
    //   - negative: engine negatives still apply but extra terms are dropped
    const kontextNoOps = ["guidance", "refine", "refine_strength", "hi_res", "ultra_res", "negative", "no_default_loras"];
    for (const name of kontextNoOps) {
      const el = form.querySelector(`[name="${name}"]`);
      if (!el) continue;
      const wrap = el.closest(".field") || el.parentElement;
      if (fromImage) {
        el.disabled = true;
        if (wrap) {
          wrap.style.opacity = "0.45";
          wrap.title = "Not used in --from-image (Kontext) mode";
        }
      } else {
        el.disabled = false;
        if (wrap) {
          wrap.style.opacity = "";
          wrap.title = "";
        }
      }
    }
    // Upscale supersedes native hi-res / ultra-res — if user picks an upscale
    // factor, mute the native-resolution checkboxes. (Backend accepts both but
    // the user wants upscale to be THE high-res path.)
    for (const name of ["hi_res", "ultra_res"]) {
      const el = form.querySelector(`[name="${name}"]`);
      if (!el || fromImage) continue;   // already handled above when Kontext
      const wrap = el.closest(".field") || el.parentElement;
      if (upscale) {
        el.disabled = true;
        el.checked = false;
        if (wrap) {
          wrap.style.opacity = "0.45";
          wrap.title = "Upscale supersedes native hi-res / ultra-res";
        }
      } else {
        el.disabled = false;
        if (wrap) {
          wrap.style.opacity = "";
          wrap.title = "";
        }
      }
    }
    // Thumbnail-only: when series is set, seed is derived from base_seed +
    // frame_offset — explicit seed is ignored.
    const seriesEl = form.querySelector('[name="series"]');
    const seedEl = form.querySelector('[name="seed"]');
    if (seriesEl && seedEl) {
      const seriesPicked = (seriesEl.value || "").trim() !== "";
      const wrap = seedEl.closest(".field") || seedEl.parentElement;
      if (seriesPicked) {
        seedEl.disabled = true;
        if (wrap) {
          wrap.style.opacity = "0.45";
          wrap.title = "Series-locked: derived from series base_seed + frame_offset";
        }
      } else {
        seedEl.disabled = false;
        if (wrap) {
          wrap.style.opacity = "";
          wrap.title = "";
        }
      }
    }
  }
  // Conditional visibility: fields tagged with showWhen:{otherField: value}
  // appear only when the named control matches the expected value. Used by
  // the unified Create page to swap engine-specific Style Details based on
  // the top-level Style picker.
  function applyShowWhen() {
    for (const node of form.querySelectorAll("[data-show-when]")) {
      try {
        const spec = JSON.parse(node.dataset.showWhen || "{}");
        let visible = true;
        for (const [key, expected] of Object.entries(spec)) {
          const probe = form.querySelector(`[name="${key}"]`);
          const val = probe ? (probe.type === "checkbox" ? String(probe.checked) : (probe.value || "")) : "";
          // Special tokens: "__nonempty" matches any non-empty value;
          // "__empty" matches only the empty string.
          if (expected === "__nonempty") {
            if (!val) { visible = false; break; }
          } else if (expected === "__empty") {
            if (val) { visible = false; break; }
          } else if (Array.isArray(expected)) {
            if (!expected.includes(val)) { visible = false; break; }
          } else if (val !== String(expected)) {
            visible = false; break;
          }
        }
        node.style.display = visible ? "" : "none";
        // Disable the input inside so its value is skipped by gatherPayload.
        const innerInput = node.querySelector("input, select, textarea");
        if (innerInput) innerInput.disabled = !visible || innerInput.dataset.gatedDisabled === "1";
      } catch (e) { /* malformed showWhen — skip */ }
    }
  }
  // On the Create page, the recipe dropdown is filtered by Style. When user
  // switches Style, repopulate the recipe options to match.
  const styleEl = form.querySelector('[name="style"]');
  const recipeForStyle = form.querySelector('[name="recipe"]');
  if (styleEl && recipeForStyle) {
    styleEl.addEventListener("change", () => {
      const newOpts = optionsFor({options: "recipesAll"});
      const currentVal = recipeForStyle.value;
      recipeForStyle.innerHTML = "";
      let preserved = false;
      for (const opt of newOpts) {
        const o = document.createElement("option");
        o.value = opt.value || "";
        o.textContent = opt.label || opt.value || "";
        if (opt.value === currentVal) { o.selected = true; preserved = true; }
        recipeForStyle.appendChild(o);
      }
      if (!preserved) recipeForStyle.value = "";
    });
  }
  applyShowWhen();
  applyFieldGating();
  updateCommandPreview();
  form.addEventListener("input", () => { applyShowWhen(); applyFieldGating(); updateCommandPreview(); });
  form.addEventListener("change", () => { applyShowWhen(); applyFieldGating(); });
}

// Reverse map of build_command's --config synthesizers: maps each engine's
// recipe config keys → form field name. Kept in sync with the per-engine
// build_command handlers (search for _join_kv_pairs in bin/forge_web.py).
const RECIPE_FIELD_MAP = {
  "childrens-coloring-book": {
    "style.tradition":              "cb_tradition",
    "style.age_range":              "cb_age_range",
    "scene.environmental_density":  "cb_density",
    "subject.character_archetype":  "cb_archetype",
    "scene.setting":                "cb_setting",
    "narrative.moment":             "cb_moment",
    "subject.emotion":              "cb_emotion",
    "subject.props":                "cb_props",
    "composition.character_count":  "cb_character_count",
  },
  "mandala-art": {
    "style.tradition":      "ma_tradition",
    "subject.treatment":    "ma_treatment",
    "style.symmetry":       "ma_symmetry",
    "style.complexity":     "ma_complexity",
    "composition.border":   "ma_border",
  },
  "indian-classical": {
    "style.tradition":      "ic_tradition",
    "style.ground":         "ic_ground",
    "subject.mudra":        "ic_mudra",
    "subject.composition":  "ic_composition",
  },
  "stylized-cinematic": {
    "style.tradition":             "sc_tradition",
    "light.time_of_day":           "sc_time_of_day",
    "light.sky_state":             "sc_sky_state",
    "light.twinkles_and_glow":     "sc_twinkles",
    "light.atmospheric_medium":    "sc_atmosphere",
  },
};

function gatherPayload() {
  const payload = {};
  const form = document.getElementById("jobForm");
  for (const el of form.elements) {
    if (!el.name) continue;
    // Skip disabled fields — they're gated by applyFieldGating() and would
    // otherwise leak default values into the cmd (e.g. hi_res=on when upscale
    // is set, or guidance=preset when from_image is set).
    if (el.disabled) continue;
    if (el.type === "checkbox") payload[el.name] = el.checked;
    else payload[el.name] = el.value;
  }
  return payload;
}

// Server-side command preview — calls /api/preview-command which runs the
// SAME build_command() that startJob will invoke. So the preview is the
// real cmd (including nested forge subcommands + python script paths),
// not a naive synthesis. Debounced 150ms to absorb fast typing.
let _previewAbort = null;
let _previewTimer = null;
function updateCommandPreview() {
  clearTimeout(_previewTimer);
  _previewTimer = setTimeout(async () => {
    if (_previewAbort) _previewAbort.abort();
    _previewAbort = new AbortController();
    const payload = gatherPayload();
    try {
      const res = await fetch("/api/preview-command", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({action: state.action, payload}),
        signal: _previewAbort.signal,
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      document.getElementById("commandPreview").textContent = data.cmd_display || "";
    } catch (e) {
      if (e.name === "AbortError") return;
      document.getElementById("commandPreview").textContent =
        `# preview unavailable (${e.message || e})`;
    }
  }, 150);
}

async function startJob(event) {
  event.preventDefault();
  clearToast();
  const res = await fetch("/api/jobs", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action: state.action, payload: gatherPayload()})
  });
  const body = await res.json();
  if (!res.ok) {
    showToast(body.error || `request failed: HTTP ${res.status}`, "error");
    return;
  }
  state.activeJob = body.id;
  state.lastStatus = body.status;
  renderJob(body);
  pollNow();
}

function showToast(message, kind = "info") {
  const t = document.getElementById("toast");
  if (!t) return;
  t.textContent = message;
  t.className = "toast " + kind;
  t.hidden = false;
  if (t._timer) clearTimeout(t._timer);
  t._timer = setTimeout(() => clearToast(), kind === "error" ? 10000 : 5000);
}
function clearToast() {
  const t = document.getElementById("toast");
  if (!t) return;
  t.hidden = true;
  t.textContent = "";
  if (t._timer) clearTimeout(t._timer);
}

function renderJob(job) {
  const list = document.getElementById("jobList");
  list.innerHTML = "";
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "job active";
  btn.innerHTML = `<span class="status ${job.status}">${job.status.toUpperCase()} · #${job.id}</span><span>${job.action} · ${job.elapsed}s</span><span class="meta">${job.cmd_display || ""}</span>`;
  list.appendChild(btn);
  renderProcess(job);
}

function renderProcess(job) {
  const paths = document.getElementById("runPaths");
  const pathItems = [
    ["Run", job.run_dir],
    ["Log", job.log_path],
    ["Events", job.events_path],
    ["Manifest", job.manifest_path]
  ].filter(([, value]) => value);
  paths.innerHTML = pathItems.map(([label, value]) => `
    <div><strong>${label}</strong> <span title="${escapeAttr(value)}">${escapeHtml(value)}</span>
    <button type="button" data-copy="${escapeAttr(value)}">Copy</button></div>
  `).join("");
  for (const btn of paths.querySelectorAll("button[data-copy]")) {
    btn.onclick = () => navigator.clipboard.writeText(btn.dataset.copy);
  }
  renderResources(job);
  const issues = document.getElementById("issues");
  issues.innerHTML = (job.issues || []).map(issue => `<div class="issue">${escapeHtml(issue)}</div>`).join("");
  const log = document.getElementById("log");
  const nearBottom = log.scrollTop + log.clientHeight >= log.scrollHeight - 24;
  log.textContent = (job.logs || []).join("\n");
  if (nearBottom) log.scrollTop = log.scrollHeight;
  const artifacts = document.getElementById("artifacts");
  artifacts.innerHTML = "";
  for (const file of job.artifacts || []) {
    const row = document.createElement("div");
    row.className = "artifact";
    const name = document.createElement("div");
    name.className = "artifact-name";
    name.title = file.path;
    name.textContent = file.display;
    const preview = document.createElement("button");
    preview.type = "button";
    preview.textContent = "Preview";
    preview.onclick = () => previewFile(file);
    const copy = document.createElement("button");
    copy.type = "button";
    copy.textContent = "Copy";
    copy.onclick = () => navigator.clipboard.writeText(file.path);
    const reveal = document.createElement("button");
    reveal.type = "button";
    reveal.textContent = "Reveal";
    reveal.onclick = () => fetch("/api/reveal", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({path:file.path})});
    row.append(name, preview, copy, reveal);
    artifacts.appendChild(row);
  }
}

function renderResources(job) {
  const box = document.getElementById("resources");
  const r = job.resources || {};
  const prog = job.progress || {};
  const isRunning = job.status === "running";

  if (!r.available && !isRunning) {
    box.hidden = true;
    return;
  }
  box.hidden = false;

  // CPU + RAM from the sampler (system-wide)
  const cpuPct = r.cpu_pct || 0;
  const memPct = r.mem_pct || 0;
  document.getElementById("cpuLabel").textContent = r.available ? `${cpuPct.toFixed(1)}%` : (r.note || "sampling…");
  document.getElementById("memLabel").textContent = r.available
    ? `${memPct.toFixed(1)}% · ${r.mem_used_gb}/${r.mem_total_gb} GB`
    : "—";
  setBar("cpuFill", cpuPct);
  setBar("memFill", memPct);

  // Steps — the real GPU-work signal on Apple Silicon, parsed from mflux output
  const stepsEl = document.getElementById("stepsLabel");
  if (prog.total) {
    const rateLabel = prog.rate_unit
      ? `${prog.rate} ${prog.rate_unit}`
      : "";
    const etaLabel = prog.eta && prog.eta !== "?" ? ` · ETA ${prog.eta}` : "";
    stepsEl.textContent = `${prog.step}/${prog.total} (${prog.percent}%) · ${rateLabel}${etaLabel}`;
    setBar("stepsFill", prog.percent || 0);
  } else if (isRunning) {
    stepsEl.textContent = "(no step counter — pre-flight)";
    setBar("stepsFill", 0);
  } else {
    stepsEl.textContent = "—";
    setBar("stepsFill", 0);
  }

  // Worker — the heaviest child process. Honest: on Apple Silicon mflux Python
  // CPU is near-zero while the GPU works, so this often shows 0%. The Steps
  // bar above is the better signal of GPU activity.
  const worker = r.worker || null;
  const cores = r.cpu_cores || 0;
  const workerCpuRaw = worker ? (worker.cpu || 0) : 0;
  const workerCpuNorm = cores > 0 ? Math.min(100, workerCpuRaw / cores) : Math.min(100, workerCpuRaw);
  if (worker) {
    document.getElementById("workerLabel").textContent =
      `${worker.name} · ${workerCpuRaw.toFixed(0)}% CPU (${(worker.mem_mb/1024).toFixed(1)} GB) — GPU work not shown`;
  } else {
    document.getElementById("workerLabel").textContent = isRunning ? "(no heavy child detected)" : "—";
  }
  setBar("workerFill", workerCpuNorm);
}

function setBar(id, pct) {
  const el = document.getElementById(id);
  el.style.width = Math.min(100, Math.max(0, pct)) + "%";
  el.className = "resFill" + (pct >= 85 ? " hot" : (pct >= 60 ? " warn" : ""));
}

function escapeHtml(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;");
}

function escapeAttr(value) {
  return escapeHtml(value).replaceAll("'", "&#39;");
}

function previewFile(file) {
  const box = document.getElementById("preview");
  const mime = file.mime || "";
  if (mime.startsWith("image/")) box.innerHTML = `<img alt="${file.name}" src="${file.url}">`;
  else if (mime.startsWith("audio/")) box.innerHTML = `<audio controls src="${file.url}"></audio>`;
  else if (mime.startsWith("video/")) box.innerHTML = `<video controls src="${file.url}"></video>`;
  else box.innerHTML = `<a href="${file.url}" target="_blank" rel="noreferrer">${file.display}</a>`;
}

async function pollNow() {
  if (!state.activeJob) return;
  const res = await fetch(`/api/jobs/${state.activeJob}`);
  if (!res.ok) return;
  const job = await res.json();
  renderJob(job);
  // Status-transition handling — surface the user-facing outcome
  const prev = state.lastStatus;
  if (prev === "running" && job.status === "ok") {
    showToast("✓ Job completed — previewing first output", "success");
    const arts = job.artifacts || [];
    if (arts.length > 0) previewFile(arts[0]);
  } else if (prev === "running" && job.status === "failed") {
    const issues = (job.issues || []).slice(0, 1)[0] || `process exited ${job.returncode}`;
    showToast("✗ Job failed: " + issues, "error");
  }
  state.lastStatus = job.status;
  if (job.status !== "running") loadRuns();
}

async function loadRuns() {
  if (state.activeJob) return;
  const res = await fetch("/api/runs");
  if (!res.ok) return;
  const data = await res.json();
  const list = document.getElementById("jobList");
  list.innerHTML = "";
  for (const run of (data.runs || []).slice(0, 12)) {
    list.appendChild(buildRunCard(run));
  }
}

function buildRunCard(run) {
  const id = String(run.id || "");
  const card = document.createElement("div");
  card.className = "run-card";
  if (state.expandedRuns && state.expandedRuns.has(id)) card.classList.add("expanded");

  // ── header (always visible, click to expand)
  const head = document.createElement("button");
  head.type = "button";
  head.className = "run-card-head";
  const status = String(run.status || "").toUpperCase();
  const action = escapeHtml(run.action || "run");
  const elapsed = `${run.elapsed || 0}s`;
  const artCount = (run.artifacts || []).length;
  const artBadge = artCount > 0 ? `<span class="art-count">${artCount}</span>` : "";
  head.innerHTML = `
    <span class="status ${run.status}">${status} · #${id}</span>
    <span class="run-action">${action}</span>
    <span class="run-elapsed">${elapsed}</span>
    ${artBadge}
    <span class="chevron">▶</span>`;
  head.onclick = () => {
    if (!state.expandedRuns) state.expandedRuns = new Set();
    if (state.expandedRuns.has(id)) state.expandedRuns.delete(id);
    else state.expandedRuns.add(id);
    card.classList.toggle("expanded");
  };
  card.appendChild(head);

  // ── body (visible only when expanded)
  const body = document.createElement("div");
  body.className = "run-card-body";

  // Truncated cmd preview
  const cmd = run.cmd_display || "";
  const cmdShort = cmd.length > 240 ? cmd.slice(0, 240) + "…" : cmd;
  if (cmdShort) {
    const pre = document.createElement("div");
    pre.className = "run-cmd";
    pre.textContent = "> " + cmdShort;
    body.appendChild(pre);
  }

  // Action buttons row
  const actions = document.createElement("div");
  actions.className = "run-card-actions";

  const artifacts = run.artifacts || [];
  const paths = run.paths || {};

  // Output button — opens first artifact
  const outBtn = document.createElement("button");
  outBtn.type = "button";
  outBtn.textContent = artifacts.length > 0
    ? (artifacts.length === 1 ? "Output" : `Outputs (${artifacts.length})`)
    : "No output";
  outBtn.disabled = artifacts.length === 0;
  if (artifacts.length === 1) {
    outBtn.onclick = () => openRunArtifact(run, artifacts[0]);
  } else if (artifacts.length > 1) {
    outBtn.onclick = () => openRunDetail(run);
  }
  actions.appendChild(outBtn);

  // Log button
  const logBtn = document.createElement("button");
  logBtn.type = "button";
  logBtn.textContent = "Log";
  logBtn.onclick = () => openRunLog(run);
  if (!paths.stdout_log) logBtn.disabled = true;
  actions.appendChild(logBtn);

  // Reveal folder button
  const revealBtn = document.createElement("button");
  revealBtn.type = "button";
  revealBtn.textContent = "Reveal";
  revealBtn.onclick = () => {
    if (paths.run_dir) {
      fetch("/api/reveal", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({path: paths.run_dir})});
    }
  };
  if (!paths.run_dir) revealBtn.disabled = true;
  actions.appendChild(revealBtn);

  // Open in detail (re-uses existing detail panel)
  const detailBtn = document.createElement("button");
  detailBtn.type = "button";
  detailBtn.textContent = "Detail";
  detailBtn.onclick = () => openRunDetail(run);
  actions.appendChild(detailBtn);

  body.appendChild(actions);
  card.appendChild(body);
  return card;
}

function openRunDetail(run) {
  renderProcess({
    ...run,
    logs: [`Recorded run: ${run.paths?.run_dir || ""}`],
    run_dir: run.paths?.run_dir,
    log_path: run.paths?.stdout_log,
    events_path: run.paths?.events,
    manifest_path: run.paths?.manifest,
  });
}

function openRunArtifact(run, file) {
  // Show this run in the detail panel + preview the artifact
  openRunDetail(run);
  previewFile(file);
}

async function openRunLog(run) {
  // Switch detail view to this run, then fetch & display historical stdout.log
  openRunDetail(run);
  const path = run.paths?.stdout_log;
  if (!path) return;
  try {
    const res = await fetch(`/api/file?path=${encodeURIComponent(path)}`);
    if (!res.ok) {
      document.getElementById("log").textContent = `(failed to fetch log: HTTP ${res.status})`;
      return;
    }
    const text = await res.text();
    const log = document.getElementById("log");
    log.textContent = text || "(empty log file)";
    log.scrollTop = log.scrollHeight;
  } catch (e) {
    document.getElementById("log").textContent = `(error loading log: ${e})`;
  }
}

async function openPicker(fieldName) {
  state.pickerField = fieldName;
  const field = document.getElementById(`field-${fieldName}`);
  state.pickerPath = field && field.value ? field.value : (state.config.home || "/");
  document.getElementById("pickerTarget").textContent = fieldName;
  document.getElementById("pickerModal").classList.add("open");
  await browse(state.pickerPath);
}

async function browse(path) {
  const res = await fetch(`/api/browse?path=${encodeURIComponent(path || "")}`);
  const data = await res.json();
  state.pickerPath = data.path;
  document.getElementById("pickerPath").value = data.path;
  const roots = document.getElementById("roots");
  roots.innerHTML = "";
  for (const root of data.roots || []) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.textContent = root.label;
    btn.onclick = () => browse(root.path);
    roots.appendChild(btn);
  }
  const entries = document.getElementById("entries");
  entries.innerHTML = "";
  for (const entry of data.entries || []) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "entry";
    row.innerHTML = `<span>${entry.is_dir ? "dir" : "file"}</span><span>${entry.name}</span><span class="meta">${entry.is_dir ? "" : formatBytes(entry.size)}</span>`;
    row.ondblclick = () => entry.is_dir ? browse(entry.path) : choosePath(entry.path);
    row.onclick = () => entry.is_dir ? browse(entry.path) : choosePath(entry.path);
    entries.appendChild(row);
  }
  document.getElementById("parentDir").onclick = () => browse(data.parent);
  document.getElementById("useFolder").onclick = () => choosePath(data.path);
}

function choosePath(path) {
  const field = document.getElementById(`field-${state.pickerField}`);
  if (field) {
    field.value = path;
    field.dispatchEvent(new Event("input", {bubbles:true}));
  }
  closePicker();
}

function closePicker() {
  document.getElementById("pickerModal").classList.remove("open");
}

function formatBytes(value) {
  if (!value && value !== 0) return "";
  const units = ["B","KB","MB","GB"];
  let size = Number(value);
  let idx = 0;
  while (size >= 1024 && idx < units.length - 1) { size /= 1024; idx++; }
  return `${size.toFixed(idx ? 1 : 0)} ${units[idx]}`;
}

async function loadConfig() {
  const res = await fetch("/api/config");
  state.config = await res.json();
  document.getElementById("forgeHome").textContent = state.config.forge_home;
  renderActions();
  renderForm();
}

document.getElementById("jobForm").addEventListener("submit", startJob);
document.getElementById("refreshConfig").onclick = loadConfig;
document.getElementById("stopJob").onclick = () => state.activeJob && fetch(`/api/jobs/${state.activeJob}/stop`, {method:"POST"});
document.getElementById("closePicker").onclick = closePicker;

function showHelpModal(title, body) {
  document.getElementById("helpTitle").textContent = title || "Field info";
  document.getElementById("helpBody").textContent = body || "";
  document.getElementById("helpModal").classList.add("open");
  document.getElementById("helpModal").setAttribute("aria-hidden", "false");
}
function closeHelpModal() {
  document.getElementById("helpModal").classList.remove("open");
  document.getElementById("helpModal").setAttribute("aria-hidden", "true");
}
document.getElementById("closeHelp").onclick = closeHelpModal;
document.getElementById("helpModal").addEventListener("click", (e) => {
  if (e.target.id === "helpModal") closeHelpModal();
});
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (document.getElementById("helpModal").classList.contains("open")) closeHelpModal();
    else if (document.getElementById("pickerModal").classList.contains("open")) closePicker();
  }
});
document.getElementById("goPath").onclick = () => browse(document.getElementById("pickerPath").value);
document.getElementById("pickerPath").addEventListener("keydown", event => { if (event.key === "Enter") browse(event.target.value); });
setInterval(pollNow, 1500);
loadConfig();
loadRuns();
</script>
</body>
</html>
"""


def run_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    DEFAULT_OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), Handler)
    actual_port = server.server_address[1]
    url = f"http://{host}:{actual_port}/"
    print(f"forge web: {url}")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
