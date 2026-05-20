#!/usr/bin/env python3
"""forge — the brand factory.

Run with no arguments to see the menu.
Run `forge wizard` for full interactive mode.
Every subcommand prompts for missing required args when run in a terminal.
"""

from __future__ import annotations

import argparse
import atexit
import contextlib
import hashlib
import json
import math
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import textwrap
import time
import urllib.request
from pathlib import Path
from typing import Any, Optional

from forge_runtime import (
    FORGE_STATE_HOME,
    HF_HOME,
    MODELS_HOME as RUNTIME_MODELS_HOME,
    PIPELINE_HOME,
    TRANSLATE_MODEL,
    JobStore,
    ResourceLock,
    child_env,
    doctor as runtime_doctor,
    hf_cache_root,
    hf_model_status,
    language_name,
    parse_language_codes,
    print_ollama_token_usage,
    require_metal_acceleration,
    translate_texts_ollama,
    validate_audio,
    validate_png,
    write_json,
    write_text,
)
from mandala_engine import (
    CHILD_THEMES,
    COMPLEXITY_LEVELS,
    FOLK_ART_THEMES,
    MANDALA_STYLES,
    ChildrensBookConfig,
    FolkArtConfig,
    MandalaConfig,
    write_childrens_book,
    write_folk_art_page,
    write_mandala,
)
from minimal_animal_engine import MinimalAnimalConfig, write_minimal_animal

HERE = Path(__file__).resolve().parent
FORGE_HOME = Path(os.environ.get("FORGE_HOME") or HERE.parent).resolve()
BRAND_DIR = FORGE_HOME / "brand"
PRESETS_DIR = BRAND_DIR / "presets"
LORAS_DIR = BRAND_DIR / "loras"
VOICES_FILE = BRAND_DIR / "voices.json"
MODELS_HOME = RUNTIME_MODELS_HOME

OLLAMA_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "qwen3:8b"
AUDIO_TRANSLATE_ENV = "FORGE_AUDIO_LANGS"

THUMB_W, THUMB_H = 1280, 720

# RealESRGAN upscaler — ncnn-vulkan binary + bundled models. Lets us render
# FLUX at a safe size (1024², 1280×720) and reach 4K/8K resolution at near-
# zero memory cost on M5 Max. See bin/forge.py::_upscale_image.
REALESRGAN_HOME = MODELS_HOME / "realesrgan"
REALESRGAN_BIN = REALESRGAN_HOME / "realesrgan-ncnn-vulkan"
REALESRGAN_MODELS_DIR = REALESRGAN_HOME / "models"
# Model choice depends on subject register: anime model preserves clean
# line work better (mandala / coloring-book), plus model is better at photo
# detail (wildlife / cinematic / indian-classical).
def _make_transparent_bg(src: Path, dst: Path, *, tolerance: int = 24) -> None:
    """Save src with the detected background color turned to alpha=0.

    Auto-detects background by sampling the 4 corner regions; pixels within
    `tolerance` of the dominant corner color become transparent (with
    anti-aliased alpha falloff at edges so the cut isn't hard-binary).

    Used for T-shirt mockup workflows. Handles pure-white, cream, and
    any other clean solid-color background — not just #FFFFFF.

    tolerance=24 catches background + faint anti-alias halo while keeping
    subject color regions intact. Bump higher (40) for noisier backgrounds.
    """
    try:
        from PIL import Image
    except ImportError:
        sys.exit(red("transparent-bg requires Pillow: pip install Pillow"))
    img = Image.open(src).convert("RGBA")
    w, h = img.size
    # Sample background color from the 4 corners (10×10 regions averaged).
    samples_r: list[int] = []
    samples_g: list[int] = []
    samples_b: list[int] = []
    sample_box = 10
    for (cx, cy) in [(0, 0), (w - sample_box, 0), (0, h - sample_box), (w - sample_box, h - sample_box)]:
        for dx in range(sample_box):
            for dy in range(sample_box):
                px = img.getpixel((cx + dx, cy + dy))
                samples_r.append(px[0]); samples_g.append(px[1]); samples_b.append(px[2])
    bg_r = sum(samples_r) // len(samples_r)
    bg_g = sum(samples_g) // len(samples_g)
    bg_b = sum(samples_b) // len(samples_b)
    pixels = img.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            dr, dg, db = abs(r - bg_r), abs(g - bg_g), abs(b - bg_b)
            max_d = max(dr, dg, db)
            if max_d <= tolerance:
                # Smooth alpha based on how close to the bg color — soft edges.
                # 0 at exact bg color → ~240 at the tolerance boundary.
                alpha = max(0, min(255, int(max_d / tolerance * 240)))
                pixels[x, y] = (r, g, b, alpha)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "PNG", optimize=True)


# Engines whose output is intended for T-shirt / sticker / die-cut use —
# auto-produce a transparent-background sibling alongside each render.
_TRANSPARENT_BG_AUTO_ENGINES: set[str] = {"minimalist-tshirt"}


REALESRGAN_MODEL_FOR_ENGINE = {
    "mandala-art":              "realesrgan-x4plus-anime",
    "childrens-coloring-book":  "realesrgan-x4plus-anime",
    "indian-classical":         "realesrgan-x4plus",
    "noir-cinema":              "realesrgan-x4plus",
    "wildlife-photo":           "realesrgan-x4plus",
    "impressionist":            "realesrgan-x4plus",
    "stylized-cinematic":       "realesrgan-x4plus-anime",
}
REALESRGAN_DEFAULT_MODEL = "realesrgan-x4plus"

DEFAULT_SUBPROCESS_TIMEOUT_SEC = float(os.environ.get("FORGE_SUBPROCESS_TIMEOUT_SEC", "1800"))
MFLUX_TIMEOUT_SEC = float(os.environ.get("FORGE_MFLUX_TIMEOUT_SEC", str(DEFAULT_SUBPROCESS_TIMEOUT_SEC)))
MFLUX_HEARTBEAT_SEC = float(os.environ.get("FORGE_MFLUX_HEARTBEAT_SEC", "30"))

# M5 Max optimization — mflux supports on-the-fly model quantization via --quantize {3,4,5,6,8}.
# fp16 (the implicit default if we never pass --quantize) is the slow path: it uses ~24 GB and is
# ~25-50 % slower than int8 / int4 with near-zero quality loss for FLUX-dev. Forge defaults to q4
# (FORGE_FLUX_QUANTIZE=4) for throughput-first iteration; use q8 for higher-fidelity finals.
# 0 / "none" forces fp16.
def _realesrgan_ready() -> tuple[bool, str]:
    """Return (ready, note) for the bundled RealESRGAN binary + at least one model."""
    if not REALESRGAN_BIN.exists():
        return False, f"binary not found at {REALESRGAN_BIN} (run: forge upscale --install)"
    if not os.access(REALESRGAN_BIN, os.X_OK):
        return False, f"binary not executable at {REALESRGAN_BIN} (run: chmod +x {REALESRGAN_BIN})"
    if not REALESRGAN_MODELS_DIR.exists() or not list(REALESRGAN_MODELS_DIR.glob("*.bin")):
        return False, f"no models in {REALESRGAN_MODELS_DIR} (run: forge upscale --install)"
    return True, ""


def _upscale_image(src: Path, dst: Path, *, scale: int, model: str | None = None) -> None:
    """Upscale src → dst by the given factor via realesrgan-ncnn-vulkan.

    scale must be 2, 3, or 4 (binary's --scale flag). For 8× we chain a 4× then
    a 2× pass via the caller — this helper only does one pass.
    """
    ready, note = _realesrgan_ready()
    if not ready:
        sys.exit(red(f"RealESRGAN unavailable: {note}"))
    if scale not in (2, 3, 4):
        sys.exit(red(f"upscale scale must be 2/3/4 (got {scale})"))
    model_name = model or REALESRGAN_DEFAULT_MODEL
    # The bundled binary's `realesrgan-x4plus` model produces 4× output regardless
    # of -s; the -s flag is for the alternate animevideov3 models. So if scale!=4
    # with an x4 model, we'd over-shoot. Pick the matching model per scale.
    if scale != 4 and "x4plus" in model_name:
        # Fallback to anime-video models for non-4x scales.
        kind = "realesr-animevideov3"
        model_name = f"{kind}-x{scale}"
    cmd = [
        str(REALESRGAN_BIN),
        "-i", str(src),
        "-o", str(dst),
        "-s", str(scale),
        "-n", model_name,
        "-m", str(REALESRGAN_MODELS_DIR),
    ]
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = _register_tmp(_tmp_sibling(dst))
    cmd[cmd.index("-o") + 1] = str(tmp)
    print(dim(f"  · upscale {scale}× via {model_name}: {src.name} → {dst.name}"))
    run_subprocess(cmd, check=True, timeout=300)
    if not tmp.exists() or tmp.stat().st_size < 4096:
        sys.exit(red(f"RealESRGAN produced no usable output at {tmp}"))
    os.replace(tmp, dst)
    _discard_tmp(tmp)


def _upscale_to_factor(src: Path, dst: Path, *, factor: int, model: str | None = None) -> None:
    """Upscale by 2/3/4/6/8/12/16× — chains multiple passes for non-native factors.

    Native binary supports 2/3/4. For 8×, we do 4× then 2× (faster + cleaner than 2×2×2).
    For 12×, 4× then 3×. For 16×, 4× then 4×.
    """
    if factor in (2, 3, 4):
        _upscale_image(src, dst, scale=factor, model=model)
        return
    # Multi-pass chain
    chain = {6: (3, 2), 8: (4, 2), 12: (4, 3), 16: (4, 4)}.get(factor)
    if not chain:
        sys.exit(red(f"unsupported upscale factor {factor}× — valid: 2, 3, 4, 6, 8, 12, 16"))
    first, second = chain
    intermediate = dst.with_name(dst.stem + f".pass1-x{first}.png")
    _upscale_image(src, intermediate, scale=first, model=model)
    try:
        _upscale_image(intermediate, dst, scale=second, model=model)
    finally:
        with contextlib.suppress(Exception):
            intermediate.unlink()


_MFLUX_MIN_FREE_GB = float(os.environ.get("FORGE_MFLUX_MIN_FREE_GB", "20"))

def _preflight_memory(label: str = "mflux") -> None:
    """Refuse to launch a heavy Metal job if free RAM is too low.

    On M5 Max with 64-80 GB unified memory, a single FLUX-dev mflux render
    needs ~6-12 GB activations + 12 GB weights (q8). Kontext doubles that.
    If the system is already memory-pressured, the launch will Metal-page-
    fault and freeze WindowServer. Better to bail with a clear message.
    """
    try:
        import psutil  # type: ignore
    except ImportError:
        return  # psutil not installed — skip silently
    vm = psutil.virtual_memory()
    free_gb = vm.available / (1024 ** 3)
    if free_gb < _MFLUX_MIN_FREE_GB:
        used_pct = vm.percent
        sys.exit(red(
            f"refusing to launch {label}: only {free_gb:.1f} GB RAM free "
            f"(threshold {_MFLUX_MIN_FREE_GB:.0f} GB, system at {used_pct:.0f}% used).\n"
            + dim(f"  close memory-heavy apps (Chrome / Xcode / VS Code) and retry.\n"
                  f"  override: FORGE_MFLUX_MIN_FREE_GB=10 forge engine render …  (risky)")
        ))

def _resolve_quantize(override: int | None = None) -> int | None:
    """Return the int to pass to mflux --quantize, or None to skip the flag (= fp16)."""
    if override is not None:
        return None if override == 0 else int(override)
    raw = os.environ.get("FORGE_FLUX_QUANTIZE", "4").strip().lower()
    if raw in {"", "0", "none", "fp16", "off"}:
        return None
    try:
        v = int(raw)
        if v in {3, 4, 5, 6, 8}:
            return v
    except ValueError:
        pass
    return 8  # safe fallback when the env var is malformed

MLX_CACHE_LIMIT_GB = int(os.environ.get("FORGE_MLX_CACHE_LIMIT_GB", "96"))

def _mflux_runtime_args(quantize: int | None = None) -> list[str]:
    """Return the mflux runtime flags shared across every mflux invocation."""
    args: list[str] = []
    q = _resolve_quantize(quantize)
    if q is not None:
        args.extend(["--quantize", str(q)])
    if MLX_CACHE_LIMIT_GB > 0:
        args.extend(["--mlx-cache-limit-gb", str(MLX_CACHE_LIMIT_GB)])
    return args

VOICE_TIMEOUT_SEC = float(os.environ.get("FORGE_VOICE_TIMEOUT_SEC", "600"))
# Cooldown between consecutive heavy mflux gens — lets the Metal GPU/SoC dissipate heat
# rather than running pinned at 100%. 0 = off. 10–30 s is reasonable on a hot chassis.
FLUX_COOLDOWN_SEC = float(os.environ.get("FORGE_FLUX_COOLDOWN_SEC", "0"))

# Profile presets — match `forge bench` so they're a real shared vocabulary.
PROFILES = {
    "cool":     {"flux_model": "schnell", "flux_steps": 4,  "flux_guidance": 0.0, "cooldown": 20.0},
    # Keep balanced thermally reasonable via step count/quantization, but avoid
    # forced idle gaps so sustained throughput stays high in batch workloads.
    "balanced": {"flux_model": "dev",     "flux_steps": 18, "flux_guidance": None, "cooldown": 0.0},
    "max":      {"flux_model": "dev",     "flux_steps": 25, "flux_guidance": None, "cooldown": 0.0},
    # Production-grade: keep q8 by default. On Apple Silicon this preserves
    # visual quality while avoiding the memory pressure that makes parallel
    # FLUX jobs page/throttle. Use --quantize 0 only for explicit fp16 tests.
    # `default_refine: True` makes `--refine` automatic at `quality` because at
    # 36 steps the second-pass img2img polish meaningfully crystallizes fur,
    # eye character, and edge detail. Override with `--no-refine` if the heat
    # cost or the extra wall-clock isn't wanted.
    "quality":  {"flux_model": "dev",     "flux_steps": 36, "flux_guidance": None, "cooldown": 0.0, "quantize": 8, "default_refine": True},
}

_TMP_PATHS: set[Path] = set()
_CHILD_PROCS: set[subprocess.Popen] = set()
_RUNTIME_GUARDS_INSTALLED = False
_FLUX_READY_CACHE: dict[str, tuple[bool, str]] = {}


def _cmd_display(cmd: list[str]) -> str:
    parts = [str(p) for p in cmd]
    for i, part in enumerate(parts[:-1]):
        if part in {"--prompt"}:
            parts[i + 1] = "<prompt>"
    return " ".join(shlex.quote(p if len(p) <= 120 else p[:117] + "...") for p in parts)


def _format_duration(seconds: float) -> str:
    seconds_i = int(max(0, seconds))
    minutes, secs = divmod(seconds_i, 60)
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _tmp_sibling(path: Path) -> Path:
    if path.suffix:
        return path.with_name(f"{path.stem}.tmp{path.suffix}")
    return path.with_name(f"{path.name}.tmp")


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
    timeout: float | None = DEFAULT_SUBPROCESS_TIMEOUT_SEC,
    capture_output: bool = False,
    text: bool = False,
    input: str | bytes | None = None,
    check: bool = True,
    heartbeat_label: str | None = None,
    heartbeat_seconds: float | None = None,
) -> subprocess.CompletedProcess:
    display = _cmd_display(cmd)
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE if input is not None else None,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        text=text,
        env=child_env(),
    )
    _CHILD_PROCS.add(proc)
    stdout = stderr = None
    try:
        use_heartbeat = (
            heartbeat_label is not None
            and heartbeat_seconds is not None
            and heartbeat_seconds > 0
            and not capture_output
            and input is None
        )
        if use_heartbeat:
            start = time.monotonic()
            while True:
                if timeout is None:
                    wait_for = heartbeat_seconds
                else:
                    elapsed = time.monotonic() - start
                    remaining = timeout - elapsed
                    if remaining <= 0:
                        _terminate_proc(proc)
                        raise subprocess.TimeoutExpired(display, timeout)
                    wait_for = min(heartbeat_seconds, remaining)
                try:
                    proc.wait(timeout=wait_for)
                    break
                except subprocess.TimeoutExpired:
                    elapsed = time.monotonic() - start
                    if timeout is not None and elapsed >= timeout:
                        _terminate_proc(proc)
                        raise subprocess.TimeoutExpired(display, timeout)
                    suffix = ""
                    if timeout is not None:
                        suffix = f", timeout {_format_duration(timeout)}"
                    print(f"  · {heartbeat_label} still running ({_format_duration(elapsed)} elapsed{suffix})", flush=True)
        else:
            stdout, stderr = proc.communicate(input=input, timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_proc(proc)
        raise subprocess.TimeoutExpired(display, timeout)
    finally:
        _CHILD_PROCS.discard(proc)
    if check and proc.returncode:
        raise subprocess.CalledProcessError(proc.returncode, display, output=stdout, stderr=stderr)
    return subprocess.CompletedProcess(display, proc.returncode, stdout, stderr)

# ─────────────── ANSI color helpers (TTY-aware) ───────────────

_TTY = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

def _c(text: str, code: str) -> str:
    if not _TTY:
        return text
    codes = {
        "gold": "\033[38;5;179m",
        "dim": "\033[2m",
        "bold": "\033[1m",
        "red": "\033[31m",
        "green": "\033[32m",
        "cyan": "\033[36m",
        "blue": "\033[34m",
        "magenta": "\033[35m",
        "reset": "\033[0m",
    }
    return f"{codes[code]}{text}{codes['reset']}"

def bold(t): return _c(t, "bold")
def dim(t):  return _c(t, "dim")
def gold(t): return _c(t, "gold")
def cyan(t): return _c(t, "cyan")
def red(t):  return _c(t, "red")
def green(t): return _c(t, "green")

# ─────────────── interactive prompts ───────────────

def prompt(label: str, *, default: str | None = None, choices: list[str] | None = None) -> str:
    """Prompt for a value. Returns the entered or default value. Loops on bad input.

    Three distinct caller intents for `default`:
      • default=None  (the default)  blank input is rejected as "required"
      • default=""    skip-allowed   blank input returns "" (caller treats as None)
      • default="x"   has-fallback   blank input returns "x"

    The suffix advertises whichever intent applies so users don't have to guess.
    """
    suffix = ""
    if choices:
        suffix = f" {dim('(' + ' / '.join(choices) + ')')}"
        if default:
            suffix += f" {dim('[Enter=' + default + ']')}"
        elif default == "":
            suffix += f" {dim('[Enter to skip]')}"
    elif default == "":
        suffix = f" {dim('[Enter to skip]')}"
    elif default is not None:
        suffix = f" {dim('[' + default + ']')}"
    while True:
        try:
            raw = input(f"  {label}{suffix} {cyan('›')} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(130)
        if raw:
            val = raw
        elif default is not None:
            val = default  # may be "" (skip) or "x" (fallback)
        else:
            print(red("  · required"))
            continue
        # Skip-allowed sentinel: accept the empty string verbatim.
        if val == "" and default == "":
            return ""
        if choices and val not in choices:
            # Prefix match: typing `max` should match `max (dev @ 25, hot)` if
            # the prefix is unambiguous. Falls back to the "must be one of" error
            # only when no choice — or multiple choices — start with the input.
            matches = [c for c in choices if c.startswith(val)]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                print(red(f"  · '{val}' is ambiguous: {', '.join(matches)}"))
                continue
            print(red(f"  · must be one of: {', '.join(choices)}"))
            continue
        return val


def confirm(label: str, *, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        raw = input(f"  {label} {dim(suffix)} {cyan('›')} ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(130)
    if not raw:
        return default
    return raw in ("y", "yes")

# ─────────────── preset loading ───────────────

def load_preset(preset_id: str) -> dict:
    path = PRESETS_DIR / f"{preset_id}.json"
    if not path.exists():
        avail = ", ".join(sorted(p.stem for p in PRESETS_DIR.glob("*.json")))
        sys.exit(red(f"unknown preset '{preset_id}'") + f"\n  available: {avail}")
    return json.loads(path.read_text())


def list_preset_ids() -> list[str]:
    return sorted(p.stem for p in PRESETS_DIR.glob("*.json"))


def load_voices() -> list[dict]:
    if not VOICES_FILE.exists():
        sys.exit(f"missing {VOICES_FILE}")
    return json.loads(VOICES_FILE.read_text())["presets"]


def list_voice_ids() -> list[str]:
    return [v["id"] for v in load_voices()]


def find_voice(voice_id: str) -> dict:
    for v in load_voices():
        if v["id"] == voice_id:
            return v
    sys.exit(red(f"unknown voice '{voice_id}'") + f"\n  available: {', '.join(list_voice_ids())}")


def system_font(family: str, size: int, *, index: int = 0):
    """Resolve `family` to a Pillow Font at `size`. `index` selects a face inside
    a `.ttc` collection (e.g. Kohinoor.ttc has Regular/Medium/Semibold/Bold/Light).
    """
    from PIL import ImageFont
    candidates = [
        f"/System/Library/Fonts/Supplemental/{family}.ttf",
        f"/System/Library/Fonts/Supplemental/{family}.ttc",  # missing earlier — ITFDevanagari etc. live here
        f"/System/Library/Fonts/{family}.ttf",
        f"/System/Library/Fonts/{family}.ttc",
        f"/Library/Fonts/{family}.ttf",
        f"/Library/Fonts/{family}.ttc",
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size, index=index)
            except (OSError, IndexError):
                # bad index for this collection — fall through and try next
                continue
    fallbacks = {"Inter": "Helvetica", "Cormorant Garamond": "Georgia"}
    if family in fallbacks:
        return system_font(fallbacks[family], size, index=index)
    return ImageFont.load_default()


# Script ranges → font families that actually carry those glyphs.
# Without this, Impact/Helvetica render Devanagari as empty tofu boxes on a thumbnail.
# Each entry: (label, regex range, [(family, ttc_index)] ordered preference).
# ttc_index picks the *bold/heavy* face inside a .ttc collection — Kohinoor.ttc
# has Regular/Medium/Semibold/Bold/Light at indices 0..4.
_SCRIPT_FONTS: list[tuple[str, str, list[tuple[str, int]]]] = [
    ("devanagari", r"[ऀ-ॿ]", [
        ("Kohinoor", 3),         # Kohinoor Devanagari Bold
        ("ITFDevanagari", 1),    # ITF Devanagari Bold
        ("DevanagariMT", 0),     # DevanagariMT Bold
        ("Devanagari Sangam MN", 0),
    ]),
    ("bengali",   r"[ঀ-৿]",  [("KohinoorBangla", 3), ("Bangla Sangam MN", 0)]),
    ("gujarati",  r"[઀-૿]",  [("KohinoorGujarati", 3), ("Gujarati Sangam MN", 0)]),
    ("tamil",     r"[஀-௿]",  [("KohinoorTamil", 3), ("Tamil Sangam MN", 0)]),
    ("telugu",    r"[ఀ-౿]",  [("KohinoorTelugu", 3), ("Telugu Sangam MN", 0)]),
    ("kannada",   r"[ಀ-೿]",  [("NotoSansKannada", 0), ("Kannada Sangam MN", 0)]),
    ("malayalam", r"[ഀ-ൿ]",  [("Malayalam Sangam MN", 0)]),
]


def _is_truetype_font(font) -> bool:
    """ImageFont.load_default() returns a BytesIO-backed bitmap font. Real
    truetype fonts loaded from a path expose `.path` as a string."""
    return isinstance(getattr(font, "path", None), str)


def font_for_text(family: str, size: int, text: str):
    """Return a font that actually has glyphs for `text`. Falls back to a
    script-appropriate family when the requested one (e.g. Impact) is Latin-only.
    """
    for _label, pattern, alternates in _SCRIPT_FONTS:
        if re.search(pattern, text):
            for alt_family, alt_index in alternates:
                f = system_font(alt_family, size, index=alt_index)
                if _is_truetype_font(f):
                    return f
    return system_font(family, size)

# ─────────────── LLM helper ───────────────

def repair_truncated_json(candidate: str) -> str:
    text = candidate.strip()
    if not text:
        return text
    if text.startswith('{"shots":['):
        last_obj = text.rfind("}")
        if last_obj > len('{"shots":['):
            text = text[: last_obj + 1]
    text = re.sub(r",\s*$", "", text)
    if text.count("[") > text.count("]"):
        text += "]" * (text.count("[") - text.count("]"))
    if text.count("{") > text.count("}"):
        text += "}" * (text.count("{") - text.count("}"))
    return text


def call_llm(system: str, user: str, *, temperature: float = 0.4, timeout: float = 90) -> dict:
    context_tokens = 8192
    body = json.dumps({
        "model": OLLAMA_MODEL, "system": system, "prompt": user,
        "stream": False, "format": "json",
        "options": {"temperature": temperature, "num_ctx": context_tokens, "num_predict": 4096},
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        response = json.loads(r.read())
    text = response["response"]
    print_ollama_token_usage(
        response,
        label="forge.llm-json",
        model=OLLAMA_MODEL,
        prompt_text=f"{system}\n{user}",
        completion_text=text,
        context=context_tokens,
        temperature=temperature,
    )
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    m = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
    candidate = m.group(1) if m else text
    try:
        return json.loads(candidate)
    except json.JSONDecodeError as e:
        repaired = repair_truncated_json(candidate)
        if repaired != candidate:
            with contextlib.suppress(json.JSONDecodeError):
                return json.loads(repaired)
        excerpt = candidate[:500].replace("\n", " ")
        raise ValueError(f"LLM returned malformed JSON: {e}; excerpt={excerpt!r}") from e

# ─────────────── thumbnail composition ───────────────

def crop_fit(img, width: int, height: int):
    """Resize and center-crop an image to exactly width x height."""
    from PIL import Image

    src_w, src_h = img.size
    if src_w <= 0 or src_h <= 0:
        sys.exit(red("cannot crop an image with empty dimensions"))
    scale = max(width / src_w, height / src_h)
    resized_w = max(width, int(round(src_w * scale)))
    resized_h = max(height, int(round(src_h * scale)))
    resample = getattr(Image, "Resampling", Image).LANCZOS
    resized = img.resize((resized_w, resized_h), resample)
    left = max(0, (resized_w - width) // 2)
    top = max(0, (resized_h - height) // 2)
    return resized.crop((left, top, left + width, top + height))


def fit_text_to_width(
    draw,
    text: str,
    family: str,
    start_px: int,
    max_width: int,
    *,
    min_px: int = 24,
):
    """Return the largest font <= start_px whose rendered text fits max_width.

    Uses `font_for_text` so non-Latin scripts (e.g. Devanagari for hi/mr) get a
    glyph-supporting family automatically — otherwise headlines would render as
    empty boxes when the preset family is Impact/Helvetica.
    """
    lo, hi = min_px, max(min_px, start_px)
    best_px = min_px
    best_font = font_for_text(family, min_px, text)
    while lo <= hi:
        px = (lo + hi) // 2
        font = font_for_text(family, px, text)
        bbox = draw.textbbox((0, 0), text, font=font)
        width = bbox[2] - bbox[0]
        if width <= max_width:
            best_px, best_font = px, font
            lo = px + 1
        else:
            hi = px - 1
    return best_font, best_px

def render_thumbnail(preset: dict, bg_image: Path, out_path: Path, *, headline: str, sub: str | None) -> None:
    from PIL import Image, ImageDraw
    if not bg_image.exists() or bg_image.stat().st_size < 1024:
        sys.exit(red(f"background image missing or too small: {bg_image}"))
    img = Image.open(bg_image).convert("RGBA")
    if img.size != (THUMB_W, THUMB_H):
        img = crop_fit(img, THUMB_W, THUMB_H).convert("RGBA")
    comp = preset["composition"]["thumbnail"]
    typo = preset["typography"]
    palette = preset["palette_60_30_10"]

    if comp["dim_band"]["opacity"] > 0:
        band = Image.new("RGBA", img.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(band)
        y0 = int(img.height * comp["dim_band"]["vertical_start"])
        d.rectangle([0, y0, img.width, img.height], fill=(0, 0, 0, int(255 * comp["dim_band"]["opacity"])))
        img = Image.alpha_composite(img, band)

    draw = ImageDraw.Draw(img)
    headline = headline.upper() if typo["display_family"] in ("Impact", "Helvetica") else headline
    if len(headline) > typo["scale"]["title_max_chars"]:
        print(f"  {red('!')} headline truncated from {len(headline)} to {typo['scale']['title_max_chars']} chars", file=sys.stderr)
        headline = headline[: typo["scale"]["title_max_chars"]]

    margin = 60
    max_text_w = img.width - margin * 2
    title_font, title_px = fit_text_to_width(
        draw, headline, typo["display_family"], typo["scale"]["title_px"], max_text_w, min_px=60
    )
    if title_px < typo["scale"]["title_px"]:
        print(f"  {dim('· headline auto-shrunk ' + str(typo['scale']['title_px']) + 'px → ' + str(title_px) + 'px to fit')}", file=sys.stderr)
    bbox = draw.textbbox((0, 0), headline, font=title_font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    anchor = comp["headline_anchor"]
    # Reserve space below the headline for the accent bar + subtitle (when present)
    # so the whole text block fits inside the dim band rather than running off the
    # bottom. Computed from the preset instead of the old magic 80px.
    reserve_below = 0
    if sub:
        reserve_below = (
            comp.get("accent_bar_height_px", 8)
            + 16  # gap below headline before bar
            + typo["scale"]["sub_px"]
            + 12  # gap between bar and sub
        )
    ty = margin if "top" in anchor else img.height - th - margin - reserve_below
    tx = margin if "left" in anchor else (img.width - tw - margin if "right" in anchor else (img.width - tw) // 2)
    tx = max(margin, min(tx, img.width - tw - margin))
    ty = max(margin, min(ty, img.height - th - margin - reserve_below))

    outline_hex = comp.get("headline_outline")
    outline_px = comp.get("headline_outline_px", 0)
    if outline_hex and outline_px > 0:
        oc = _hex(outline_hex)
        for dx in range(-outline_px, outline_px + 1, max(1, outline_px // 2)):
            for dy in range(-outline_px, outline_px + 1, max(1, outline_px // 2)):
                if dx or dy:
                    draw.text((tx + dx, ty + dy), headline, font=title_font, fill=oc)
    draw.text((tx, ty), headline, font=title_font, fill=_hex(comp["headline_color"]))

    bar_w, bar_h = comp["accent_bar_width_px"], comp["accent_bar_height_px"]
    bar_color = _hex(palette[comp.get("accent_bar_role", "accent")]["hex"])
    by = ty + th + 16
    draw.rectangle([tx, by, tx + bar_w, by + bar_h], fill=bar_color)
    if sub:
        sub_font = font_for_text(typo["body_family"], typo["scale"]["sub_px"], sub)
        draw.text((tx, by + bar_h + 12), sub, font=sub_font, fill=_hex(comp["headline_color"]))

    # Atomic write + post-write size check
    tmp = _register_tmp(_tmp_sibling(out_path))
    try:
        img.convert("RGB").save(tmp, "PNG", optimize=True)
        os.replace(tmp, out_path)
    finally:
        if tmp.exists():
            tmp.unlink()
        _discard_tmp(tmp)
    try:
        validate_png(out_path, width=THUMB_W, height=THUMB_H)
    except ValueError as e:
        sys.exit(red(str(e)))


def _hex(s: str) -> tuple[int, int, int, int]:
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), 255)


_FLUX_REPO_MAP = {
    "schnell":     "black-forest-labs/FLUX.1-schnell",
    "dev":         "black-forest-labs/FLUX.1-dev",
    "kontext-dev": "black-forest-labs/FLUX.1-Kontext-dev",
    "dev-kontext": "black-forest-labs/FLUX.1-Kontext-dev",  # alias
}

# ─────────────── series (consistency locking) ───────────────
#
# A "series" is a sibling concept to a preset. The preset locks the *look* (palette,
# typography, style fingerprint). The series locks the *world*: a base seed, a
# style-anchor preamble repeated verbatim in every prompt, locked character/world
# descriptions, and locked negative phrasings. Together: every frame of a batch
# reads as one production.
#
# Layout: <FORGE_HOME>/series/<series-id>.json
# Use `forge series new <id>` to scaffold one, `forge series show <id>` to dump.

SERIES_DIR = BRAND_DIR.parent / "series"
CHARACTER_PLACEHOLDER_RE = re.compile(r"\[([a-zA-Z][a-zA-Z0-9_-]*)\]")


def load_series(series_id: str) -> dict:
    if not series_id:
        return {}
    path = SERIES_DIR / f"{series_id}.json"
    if not path.exists():
        avail = sorted(p.stem for p in SERIES_DIR.glob("*.json")) if SERIES_DIR.exists() else []
        sys.exit(red(f"unknown series '{series_id}'") + (f"\n  available: {', '.join(avail)}" if avail else "\n  no series defined yet — run `forge series new <id>`"))
    data = json.loads(path.read_text())
    # Defensive defaults so a barely-filled file still works.
    data.setdefault("style_anchor", "")
    data.setdefault("world_sheet", "")
    data.setdefault("character_sheet", {})
    data.setdefault("locked_negatives", [])
    data.setdefault("base_seed", 1)
    return data


def list_series_ids() -> list[str]:
    if not SERIES_DIR.exists():
        return []
    return sorted(p.stem for p in SERIES_DIR.glob("*.json"))


def derive_seed(series: dict | None, frame_offset: int, fallback: int = 1) -> int:
    """Deterministic seed per frame: base_seed + frame_offset (mod 2^31-1).

    Without a series the caller's fallback wins (keeps non-series callsites unchanged).
    """
    if not series:
        return fallback
    return (int(series["base_seed"]) + int(frame_offset)) % ((1 << 31) - 1)


def expand_concept(concept: str, series: dict | None) -> tuple[str, list[str]]:
    """Replace [name] placeholders with character descriptions; return (expanded, used_names)."""
    if not series or not series.get("character_sheet"):
        return concept, []
    sheet = series["character_sheet"]
    used: list[str] = []

    def _sub(match: re.Match) -> str:
        name = match.group(1)
        if name in sheet:
            if name not in used:
                used.append(name)
            return f"the {name.replace('_', ' ')}"
        return match.group(0)  # leave unknown placeholders untouched

    expanded = CHARACTER_PLACEHOLDER_RE.sub(_sub, concept)
    return expanded, used


# ─────────────── master primer (universal anti-failure block) ───────────────
# Applied to every FLUX generation regardless of preset. Suppresses the common
# AI-image failure modes that show up across all our previous outputs:
#   - hand/finger anatomy errors (we saw fused toes on the blue jay, extra fingers on Narasimha)
#   - mirror-twin symmetry (the rabbits side-by-side problem)
#   - accidental watermarks/signatures (the "Sedi-Pi…" text on the rabbits)
#   - plastic-doll skin / cartoon gloss (Krishna + Narasimha)
#   - floating disconnected limbs (Matsya's arm-from-wrong-angle)
#   - asymmetric facial features that look wrong
#   - jpeg artifacts, lens flares pasted on, fake bloom
#
# These are MERGED with each preset's own negatives so the preset can still
# add domain-specific ones (e.g. tartakovsky already excludes "photorealistic").
MASTER_NEGATIVES: list[str] = [
    # Hand/limb anatomy
    "mangled hands", "extra fingers", "fused fingers", "six fingers",
    "missing fingers", "deformed hands", "misshapen feet", "fused toes",
    "extra toes", "extra limbs", "missing limbs", "disconnected limbs",
    "floating limbs", "broken anatomy",
    # Face
    "asymmetric eyes", "mismatched eyes", "lazy eye", "fused eyes",
    "doll face", "doll-like skin", "plastic skin", "porcelain finish",
    "uncanny valley face",
    # Surface / style
    "AI gloss", "cartoon gloss", "plastic sheen", "fake bloom",
    "lens flare overlay", "rainbow chromatic aberration",
    "oversaturated neon", "HDR bloom artifact",
    # AI-glow / dreamlike halation (the "every image looks AI" tell)
    "soft focus haze", "ambient bloom around lights", "halation glow",
    "dreamy gradient edges", "AI watercolor smudge", "milky highlight glow",
    "soft uniform contrast across frame", "blurry edge bleed",
    "out-of-focus mist around subject", "diffuse edge softening",
    "default FLUX dreamy aesthetic",
    # Composition
    "mirror twin", "perfectly symmetric subjects", "duplicate subjects",
    "identical clones",
    # Junk overlays
    "watermark", "signature", "artist signature", "stock photo logo",
    "text overlay", "subtitle bar",
    "jpeg compression artifacts", "moire pattern",
]


# Tail-end craft directive baked onto every gen. Four policies — chosen
# per preset via `preset["master_primer_policy"]` (default "full" for back-
# compat). The photoreal-grade material directives (pores, weave, tarnish,
# scratches) actively FIGHT flat-cel and ink-only presets (tartakovsky,
# batman-noir), so style_safe gives those the anti-bloom shielding without
# the photoreal-specific demands.
MASTER_POSITIVE_HINT_FULL = (
    "Render with crisp edge definition on every surface — NO soft halation, "
    "NO ambient bloom around bright objects, NO dreamy gradient haze around "
    "the subject. Every prominent material in frame carries 2-3 specific "
    "micro-detail cues: fabric shows weave + wear at stress points, metal "
    "shows tarnish gradient + scratch marks, leather shows fold creases + "
    "edge softening from use, skin shows asymmetric pores + capillary "
    "variance, foliage shows individual leaf vein structure. Contact shadows "
    "are hard where objects touch surfaces. The image must read as something "
    "made by hand or captured by camera — not as something dreamed by a model."
)
# Style-safe: keep the anti-AI-bloom guard but DROP the photoreal-only
# material directives. Flat-cel / ink / painterly presets get this.
MASTER_POSITIVE_HINT_STYLE_SAFE = (
    "Render with confident edges and a clean readable silhouette. NO soft "
    "halation, NO ambient bloom around bright objects, NO dreamy gradient "
    "haze around the subject, NO AI-glow milky highlights. Respect the "
    "named style's craft language — flat color fills stay flat, ink stays "
    "ink, paint stays paint, brushwork stays visible. The image should read "
    "as something made by hand in that tradition, not dreamed by a model."
)
# Kept for back-compat — older code references MASTER_POSITIVE_HINT.
MASTER_POSITIVE_HINT = MASTER_POSITIVE_HINT_FULL

# Map policy name → hint string. None = no hint appended.
_MASTER_PRIMER_HINTS: dict[str, str | None] = {
    "full":        MASTER_POSITIVE_HINT_FULL,
    "photo_only":  MASTER_POSITIVE_HINT_FULL,    # alias — photoreal gets full
    "style_safe":  MASTER_POSITIVE_HINT_STYLE_SAFE,
    "off":         None,
}

def _resolve_master_primer_hint(preset: dict) -> str | None:
    """Pick the right master primer hint for this preset, honoring both
    the preset's declared policy AND the FORGE_MASTER_PRIMER env override."""
    # Env var off → respect it regardless of preset policy.
    if os.environ.get("FORGE_MASTER_PRIMER", "on").lower() == "off":
        return None
    policy = str(preset.get("master_primer_policy", "full")).lower()
    return _MASTER_PRIMER_HINTS.get(policy, MASTER_POSITIVE_HINT_FULL)


def build_flux_prompt(preset: dict, concept: str, series: dict | None = None) -> str:
    """Assemble the full positive prompt. Series content is BLOCK-FORMATTED so the model
    sees clear separation between style anchor / scene / world / cast / palette / constraints.
    """
    flux = preset["flux"]
    palette = preset["palette_60_30_10"]
    rules = ", ".join(preset["prompt_rules"]["always_add"])
    palette_line = (
        f"60-30-10 palette: 60% {palette['dominant']['hex']} ({palette['dominant']['role']}), "
        f"30% {palette['secondary']['hex']} ({palette['secondary']['role']}), "
        f"10% {palette['accent']['hex']} ({palette['accent']['role']})."
    )

    expanded_concept, used = expand_concept(concept, series)

    parts: list[str] = []
    if series and series.get("style_anchor"):
        parts.append(f"SERIES STYLE LOCK: {series['style_anchor']}")
    if flux["positive_prefix"]:
        parts.append(flux["positive_prefix"])
    if expanded_concept.strip():
        parts.append(f"SCENE: {expanded_concept}.")
    if series and series.get("world_sheet"):
        parts.append(f"WORLD: {series['world_sheet']}")
    if series and series.get("character_sheet"):
        sheet = series["character_sheet"]
        # If the scene named specific characters, emit ONLY those; otherwise emit the full cast.
        names = used or list(sheet.keys())
        cast_lines = [f"- {n}: {sheet[n]}" for n in names if n in sheet]
        if cast_lines:
            parts.append("CAST IN FRAME (must match these descriptions exactly):\n" + "\n".join(cast_lines))
    parts.append(palette_line)
    if rules:
        parts.append(f"CONSTRAINTS: {rules}.")
    # Bake negatives into the positive prompt — FLUX follows English better than CFG negatives.
    # Order: preset negatives → series locked negatives → MASTER_NEGATIVES (universal anti-failure)
    seen: set[str] = set()
    all_negatives: list[str] = []
    for n in (list(flux.get("negatives", []))
              + list((series or {}).get("locked_negatives", []))
              + (MASTER_NEGATIVES if os.environ.get("FORGE_MASTER_PRIMER", "on").lower() != "off" else [])):
        key = n.strip().lower()
        if key and key not in seen:
            seen.add(key)
            all_negatives.append(n)
    if all_negatives:
        parts.append("DO NOT include: " + ", ".join(all_negatives) + ".")
    parts.append(flux["positive_suffix"])
    # Tail-end craft hint — per-preset policy (full / photo_only / style_safe / off).
    # Opt-out globally via FORGE_MASTER_PRIMER=off.
    hint = _resolve_master_primer_hint(preset)
    if hint:
        parts.append(hint)
    return "\n\n".join(parts)


def _flux_model_ready(model_id: str) -> tuple[bool, str]:
    """Check the HF cache has a fully-downloaded FLUX model. Returns (ready, reason)."""
    if model_id in _FLUX_READY_CACHE:
        return _FLUX_READY_CACHE[model_id]
    repo = _FLUX_REPO_MAP.get(model_id, model_id)
    status = hf_model_status(repo)
    if status["ready"]:
        result = (True, "")
    else:
        result = (False, f"{status['reason']} at {status['path']}")
    _FLUX_READY_CACHE[model_id] = result
    return result


def _resolve_flux_runtime(
    preset: dict,
    *,
    draft: bool = False,
    profile: str | None = None,
    steps_override: int | None = None,
) -> tuple[str, int, float]:
    """Pick (model, steps, guidance) given preset + --draft + --profile + --steps.

    Resolution: --steps > --profile > --draft > preset defaults.
    Draft is sugar for profile=cool; profile=cool/balanced/max applies bench-defined defaults.
    """
    flux = preset["flux"]
    # Draft is shorthand for "cool" — explicit profile wins if both given.
    if draft and not profile:
        profile = "cool"
    if profile:
        if profile not in PROFILES:
            sys.exit(red(f"unknown profile '{profile}'") + f"; choose: {', '.join(PROFILES)}")
        p = PROFILES[profile]
        model = p["flux_model"]
        steps = int(steps_override if steps_override is not None else p["flux_steps"])
        guidance = p["flux_guidance"] if p["flux_guidance"] is not None else float(flux["guidance"])
        return model, steps, float(guidance)
    # No profile, no draft → preset defaults
    model = flux["model"]
    steps = int(steps_override if steps_override is not None else flux["steps"])
    return model, steps, float(flux["guidance"])


def _cooldown_seconds(profile: str | None, draft: bool) -> float:
    """Resolve cooldown: explicit env wins, else profile default, else 0."""
    if FLUX_COOLDOWN_SEC > 0:
        return FLUX_COOLDOWN_SEC
    if draft and not profile:
        profile = "cool"
    if profile and profile in PROFILES:
        return float(PROFILES[profile]["cooldown"])
    return 0.0


# ─────────────── video (VO + thumbnail → mp4) ───────────────

def _probe_audio_duration(path: Path) -> float:
    """Return audio duration in seconds via ffprobe. Raises on failure."""
    if shutil.which("ffprobe") is None:
        sys.exit(red("ffprobe required for `forge video` — install via ffmpeg package"))
    out = run_subprocess(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True, timeout=30,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        sys.exit(red(f"ffprobe could not read duration from {path}: {out!r}"))


def make_podcast_video(
    image_path: Path,
    audio_path: Path,
    out_path: Path,
    *,
    kenburns: bool = True,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    fade_out_sec: float = 1.0,
    zoom_max: float = 1.15,
    crf: int = 18,
) -> None:
    """ffmpeg: looped image + Ken-Burns zoompan + Kokoro VO → 1920×1080 mp4.

    The video length is set to the audio length (we don't pad silence). Ken-Burns
    is a subtle zoom-only animation: starts at 1.0× and creeps to zoom_max over the
    full duration. End fades to black over fade_out_sec.
    """
    if shutil.which("ffmpeg") is None:
        sys.exit(red("ffmpeg required for `forge video` — install ffmpeg first"))
    if not image_path.exists() or image_path.stat().st_size < 1024:
        sys.exit(red(f"image missing or too small: {image_path}"))
    if not audio_path.exists() or audio_path.stat().st_size < 1024:
        sys.exit(red(f"audio missing or too small: {audio_path}"))

    duration = _probe_audio_duration(audio_path)
    total_frames = max(1, int(round(duration * fps)))
    fade_start = max(0.0, duration - fade_out_sec)

    if kenburns:
        # Scale to oversized canvas → zoompan crops to 1920×1080 with creeping zoom.
        # zoom expression: linear from 1.0 to zoom_max over total_frames.
        # The 'on' var is the current output frame index inside zoompan.
        zoom_delta = (zoom_max - 1.0) / max(1, total_frames - 1)
        # `on` = output frame number 0..total-1. Linear z = 1.0 + on * delta, clamped.
        video_filter = (
            f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
            f"crop={width * 2}:{height * 2},"
            f"zoompan=z='min(1.0+on*{zoom_delta:.8f}\\,{zoom_max})':"
            f"d={total_frames}:s={width}x{height}:fps={fps}:"
            f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)',"
            f"fade=out:st={fade_start:.3f}:d={fade_out_sec:.3f}"
        )
    else:
        # Static — just scale + center-crop + fade.
        video_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},"
            f"fade=out:st={fade_start:.3f}:d={fade_out_sec:.3f}"
        )

    tmp_out = _register_tmp(_tmp_sibling(out_path))
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-loop", "1", "-i", str(image_path),
        "-i", str(audio_path),
        "-filter_complex", f"[0:v]{video_filter}[v]",
        "-map", "[v]", "-map", "1:a",
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2",
        "-r", str(fps),
        # Explicit duration — zoompan can over-emit frames; `-t` clips both streams
        # to the audio length exactly. -shortest alone is unreliable here.
        "-t", f"{duration:.3f}",
        "-movflags", "+faststart",
        str(tmp_out),
    ]
    print(dim(f"  $ ffmpeg [{'kenburns' if kenburns else 'static'}] {width}x{height}@{fps} dur={duration:.1f}s fade={fade_out_sec}s"))
    try:
        run_subprocess(cmd, check=True, timeout=DEFAULT_SUBPROCESS_TIMEOUT_SEC)
    except Exception:
        if tmp_out.exists():
            tmp_out.unlink()
        raise
    if not tmp_out.exists() or tmp_out.stat().st_size < 4096:
        sys.exit(red(f"ffmpeg produced empty/tiny output: {tmp_out}"))
    os.replace(tmp_out, out_path)
    _discard_tmp(tmp_out)


def cmd_video(args) -> int:
    image = args.image or _need("image path (the thumbnail/poster)", tty=_TTY)
    audio = args.audio or _need("audio path (the voiceover)", tty=_TTY)
    out = args.out or _need(
        "output mp4 path",
        tty=_TTY,
        default=str(Path(audio).expanduser().with_suffix(".mp4")),
    )
    image_path = Path(image).expanduser().resolve()
    audio_path = Path(audio).expanduser().resolve()
    out_path = Path(out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    make_podcast_video(
        image_path, audio_path, out_path,
        kenburns=not args.no_kenburns,
        fade_out_sec=args.fade_out,
        zoom_max=args.zoom_max,
    )
    duration = _probe_audio_duration(out_path)
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(green(f"✓ {out_path}") + dim(f"  ({size_mb:.1f} MB, {duration:.1f}s)"))
    return 0


def flux_generate(
    preset: dict,
    concept: str,
    out_path: Path,
    *,
    seed: int = 1,
    steps: int | None = None,
    series: dict | None = None,
    draft: bool = False,
    profile: str | None = None,
    lora_paths: list[str] | None = None,
    lora_scales: list[float] | None = None,
    width: int | None = None,
    height: int | None = None,
    guidance_override: float | None = None,
    quantize: int | None = None,
) -> None:
    flux = preset["flux"]
    model, step_count, guidance = _resolve_flux_runtime(
        preset, draft=draft, profile=profile, steps_override=steps,
    )
    if guidance_override is not None:
        guidance = float(guidance_override)
    if step_count < 1:
        sys.exit(red("--steps must be >= 1"))

    # P0: pre-flight — refuse to silently trigger a multi-GB download
    ready, reason = _flux_model_ready(model)
    if not ready:
        repo = _FLUX_REPO_MAP.get(model, model)
        sys.exit(
            red(f"FLUX preflight failed: {reason}") + "\n"
            + dim(f"  this run wants FLUX.1-{model}, but it's not fully cached.\n\n")
            + "  Options:\n"
            + f"  1. Complete the download (resumable):\n"
            + f"       hf download {repo}\n"
            + "  2. Switch the preset to a model you HAVE — edit brand/presets/"
              f"{preset['id']}.json,\n     change flux.model to 'schnell' (or 'dev', whichever is cached).\n"
            + "  3. Inspect what's cached:\n"
            + "       forge models scan --full\n"
        )

    # Series + preset together — see build_flux_prompt for block layout.
    full_prompt = build_flux_prompt(preset, concept, series=series)

    # LoRA resolution order: caller > series > preset. Each layer provides BOTH paths and scales.
    if lora_paths is not None:
        eff_loras, eff_scales = list(lora_paths), list(lora_scales or [])
    elif series and series.get("lora_paths"):
        eff_loras = list(series.get("lora_paths") or [])
        eff_scales = list(series.get("lora_scales") or [])
    else:
        eff_loras = list(preset.get("lora_paths") or [])
        eff_scales = list(preset.get("lora_scales") or [])
    # Resolve bare filenames against brand/loras/ so users don't have to type full paths.
    resolved_loras: list[str] = []
    for p in eff_loras:
        candidate = Path(p).expanduser()
        if not candidate.is_absolute() and not candidate.exists():
            in_brand = LORAS_DIR / p
            if in_brand.exists():
                candidate = in_brand
        if not candidate.exists():
            sys.exit(red(f"LoRA file not found: {p}") + dim(f"\n  looked in CWD and {LORAS_DIR}"))
        resolved_loras.append(str(candidate.resolve()))
    eff_loras = resolved_loras
    if eff_loras and len(eff_scales) != len(eff_loras):
        # Reasonable default: 0.8 per LoRA if scales unspecified or mismatched.
        eff_scales = [0.8] * len(eff_loras)

    tmp_out = _register_tmp(_tmp_sibling(out_path))
    # Resolution priority:
    #   explicit --width/--height  >  preset["native_canvas"]  >  THUMB_W/H
    # Lets each preset declare its native aspect (movie-poster 16:9,
    # editorial 3:2, comic-cover 2:3, etc.) without requiring every CLI
    # caller to pass dimensions.
    preset_native = preset.get("native_canvas") or {}
    eff_w = int(width) if width else int(preset_native.get("width", THUMB_W))
    eff_h = int(height) if height else int(preset_native.get("height", THUMB_H))
    # Profile can override quantize (e.g. "quality" keeps dev/36 on q8).
    if quantize is None and profile and "quantize" in PROFILES.get(profile, {}):
        quantize = PROFILES[profile]["quantize"]
    cmd = [
        "mflux-generate",
        *_mflux_runtime_args(quantize),
        "--model", model, "--prompt", full_prompt,
        "--width", str(eff_w), "--height", str(eff_h),
        "--steps", str(step_count), "--guidance", str(guidance),
        "--seed", str(seed), "--output", str(tmp_out),
    ]
    if eff_loras:
        # mflux: --lora-paths and --lora-scales each take space-separated values
        cmd.extend(["--lora-paths", *eff_loras])
        cmd.extend(["--lora-scales", *[str(s) for s in eff_scales]])
    mode_tag = profile.upper() if profile else ("DRAFT" if draft else "FINAL")
    series_tag = f" series={series['id']}" if series and series.get("id") else ""
    lora_tag = f" loras={len(eff_loras)}" if eff_loras else ""
    q_resolved = _resolve_quantize(quantize)
    q_tag = f" q{q_resolved}" if q_resolved else " fp16"
    print(dim(f"  $ mflux-generate [{mode_tag}]{q_tag} model={model} steps={step_count} guidance={guidance} seed={seed}{series_tag}{lora_tag}"))
    if not draft and not profile and steps is not None and step_count < int(flux["steps"]):
        print(dim("  · lower steps reduce sustained Metal/GPU load and heat; quality may drop a bit"))
    try:
        try:
            require_metal_acceleration(label=f"mflux {model}/{step_count} steps")
        except RuntimeError as e:
            sys.exit(red(str(e)))
        with ResourceLock("metal-heavy") as lock:
            if lock.wait_seconds > 0.1:
                print(dim(f"  · waited {lock.wait_seconds:.1f}s for Metal lock"))
            _preflight_memory(label=f"mflux {model}/{step_count} steps")
            run_subprocess(
                cmd, check=True, timeout=MFLUX_TIMEOUT_SEC,
                heartbeat_label=f"mflux {model}/{step_count} steps",
                heartbeat_seconds=MFLUX_HEARTBEAT_SEC,
            )
    except Exception:
        if tmp_out.exists():
            tmp_out.unlink()
        raise
    try:
        validate_png(tmp_out, width=eff_w, height=eff_h, min_bytes=4096)
    except ValueError as e:
        sys.exit(red(f"mflux output validation failed: {e}"))
    os.replace(tmp_out, out_path)
    _discard_tmp(tmp_out)
    # Thermal cooldown — let the SoC dissipate before the next heavy gen in a batch.
    cooldown = _cooldown_seconds(profile, draft)
    if cooldown > 0:
        print(dim(f"  · cooldown {cooldown:.0f}s (FORGE_FLUX_COOLDOWN_SEC or profile)"))
        time.sleep(cooldown)


def flux_generate_batch(
    preset: dict,
    concept: str,
    out_paths: list[Path],
    *,
    seeds: list[int],
    steps: int | None = None,
    series: dict | None = None,
    draft: bool = False,
    profile: str | None = None,
    lora_paths: list[str] | None = None,
    lora_scales: list[float] | None = None,
    width: int | None = None,
    height: int | None = None,
    guidance_override: float | None = None,
    quantize: int | None = None,
) -> None:
    # mflux's native --seed S1 S2 … pays the FLUX cold-load once per batch
    # instead of once per subprocess. Measured 5.6× speedup on cool/schnell
    # scouting (107s → 19s for 4 seeds); ~15–20% on quality flows where
    # inference dominates. Single-seed callers stay on flux_generate.
    if len(seeds) != len(out_paths):
        sys.exit(red(f"flux_generate_batch: seeds ({len(seeds)}) must match out_paths ({len(out_paths)})"))
    if not seeds:
        return
    if len(seeds) == 1:
        flux_generate(
            preset, concept, out_paths[0],
            seed=seeds[0], steps=steps, series=series,
            draft=draft, profile=profile,
            lora_paths=lora_paths, lora_scales=lora_scales,
            width=width, height=height,
            guidance_override=guidance_override, quantize=quantize,
        )
        return
    if len(set(seeds)) != len(seeds):
        sys.exit(red(f"flux_generate_batch: duplicate seeds not allowed in one batch ({seeds})"))

    model, step_count, guidance = _resolve_flux_runtime(
        preset, draft=draft, profile=profile, steps_override=steps,
    )
    if guidance_override is not None:
        guidance = float(guidance_override)
    if step_count < 1:
        sys.exit(red("--steps must be >= 1"))

    ready, reason = _flux_model_ready(model)
    if not ready:
        repo = _FLUX_REPO_MAP.get(model, model)
        sys.exit(
            red(f"FLUX preflight failed: {reason}") + "\n"
            + dim(f"  this run wants FLUX.1-{model}, but it's not fully cached.\n\n")
            + "  Options:\n"
            + f"  1. Complete the download (resumable):\n"
            + f"       hf download {repo}\n"
            + "  2. Switch the preset to a model you HAVE — edit brand/presets/"
              f"{preset['id']}.json,\n     change flux.model to 'schnell' (or 'dev', whichever is cached).\n"
            + "  3. Inspect what's cached:\n"
            + "       forge models scan --full\n"
        )

    full_prompt = build_flux_prompt(preset, concept, series=series)

    if lora_paths is not None:
        eff_loras, eff_scales = list(lora_paths), list(lora_scales or [])
    elif series and series.get("lora_paths"):
        eff_loras = list(series.get("lora_paths") or [])
        eff_scales = list(series.get("lora_scales") or [])
    else:
        eff_loras = list(preset.get("lora_paths") or [])
        eff_scales = list(preset.get("lora_scales") or [])
    resolved_loras: list[str] = []
    for p in eff_loras:
        candidate = Path(p).expanduser()
        if not candidate.is_absolute() and not candidate.exists():
            in_brand = LORAS_DIR / p
            if in_brand.exists():
                candidate = in_brand
        if not candidate.exists():
            sys.exit(red(f"LoRA file not found: {p}") + dim(f"\n  looked in CWD and {LORAS_DIR}"))
        resolved_loras.append(str(candidate.resolve()))
    eff_loras = resolved_loras
    if eff_loras and len(eff_scales) != len(eff_loras):
        eff_scales = [0.8] * len(eff_loras)

    preset_native = preset.get("native_canvas") or {}
    eff_w = int(width) if width else int(preset_native.get("width", THUMB_W))
    eff_h = int(height) if height else int(preset_native.get("height", THUMB_H))
    if quantize is None and profile and "quantize" in PROFILES.get(profile, {}):
        quantize = PROFILES[profile]["quantize"]

    out_paths[0].parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix=".forge-batch-", dir=str(out_paths[0].parent)))

    cmd = [
        "mflux-generate",
        *_mflux_runtime_args(quantize),
        "--model", model, "--prompt", full_prompt,
        "--width", str(eff_w), "--height", str(eff_h),
        "--steps", str(step_count), "--guidance", str(guidance),
        "--seed", *[str(s) for s in seeds],
        "--output", str(staging_dir / "img.png"),
    ]
    if eff_loras:
        cmd.extend(["--lora-paths", *eff_loras])
        cmd.extend(["--lora-scales", *[str(s) for s in eff_scales]])

    mode_tag = profile.upper() if profile else ("DRAFT" if draft else "FINAL")
    q_resolved = _resolve_quantize(quantize)
    q_tag = f" q{q_resolved}" if q_resolved else " fp16"
    lora_tag = f" loras={len(eff_loras)}" if eff_loras else ""
    seeds_tag = ",".join(str(s) for s in seeds)
    print(dim(f"  $ mflux-generate [{mode_tag}]{q_tag} model={model} steps={step_count} guidance={guidance} seeds=[{seeds_tag}] batch{lora_tag}"))

    try:
        try:
            require_metal_acceleration(label=f"mflux batch {model}/{step_count}×{len(seeds)}")
        except RuntimeError as e:
            sys.exit(red(str(e)))
        with ResourceLock("metal-heavy") as lock:
            if lock.wait_seconds > 0.1:
                print(dim(f"  · waited {lock.wait_seconds:.1f}s for Metal lock"))
            _preflight_memory(label=f"mflux batch {model}/{step_count}×{len(seeds)}")
            run_subprocess(
                cmd, check=True, timeout=MFLUX_TIMEOUT_SEC,
                heartbeat_label=f"mflux batch {model}/{step_count}×{len(seeds)}",
                heartbeat_seconds=MFLUX_HEARTBEAT_SEC,
            )
    except Exception:
        shutil.rmtree(staging_dir, ignore_errors=True)
        raise

    # mflux writes <basename_stem>_seed_<seed_value>.<ext> (e.g. img_seed_1.png).
    # Remap each to the caller's requested out_path, validating along the way.
    for seed, out_path in zip(seeds, out_paths):
        mflux_path = staging_dir / f"img_seed_{seed}.png"
        if not mflux_path.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)
            sys.exit(red(f"mflux batch output missing for seed {seed}: {mflux_path.name}"))
        try:
            validate_png(mflux_path, width=eff_w, height=eff_h, min_bytes=4096)
        except ValueError as e:
            shutil.rmtree(staging_dir, ignore_errors=True)
            sys.exit(red(f"mflux batch output validation failed for seed {seed}: {e}"))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(mflux_path, out_path)
    shutil.rmtree(staging_dir, ignore_errors=True)

    cooldown = _cooldown_seconds(profile, draft)
    if cooldown > 0:
        print(dim(f"  · cooldown {cooldown:.0f}s (FORGE_FLUX_COOLDOWN_SEC or profile)"))
        time.sleep(cooldown)


# ─────────────── voice ───────────────


_SAY_VOICES_CACHE: set[str] | None = None
_KOKORO_INSTANCE = None  # lazy singleton — loading the ONNX model is ~1s

# Kokoro v1.0 model files (≈80 MB ONNX + ~30 MB voices). Pinned to GitHub release.
KOKORO_MODEL_FILE = "kokoro-v1.0.onnx"
KOKORO_VOICES_FILE = "voices-v1.0.bin"
KOKORO_RELEASE_BASE = (
    "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
)


def _say_voice_installed(name: str) -> bool:
    global _SAY_VOICES_CACHE
    if _SAY_VOICES_CACHE is None:
        try:
            out = run_subprocess(["say", "-v", "?"], capture_output=True, text=True, check=True, timeout=10).stdout
            _SAY_VOICES_CACHE = {ln.split()[0] for ln in out.splitlines() if ln.strip() and not ln.startswith("#")}
        except Exception:
            _SAY_VOICES_CACHE = set()
    return name in _SAY_VOICES_CACHE


def _kokoro_dir() -> Path:
    return MODELS_HOME / "kokoro"


def _kokoro_paths() -> tuple[Path, Path]:
    d = _kokoro_dir()
    return d / KOKORO_MODEL_FILE, d / KOKORO_VOICES_FILE


def _kokoro_ready() -> tuple[bool, str]:
    """Returns (ready, reason). Ready means the package is importable AND model files exist."""
    onnx_path, voices_path = _kokoro_paths()
    if not onnx_path.exists():
        return False, f"missing {onnx_path.name} (run `forge setup-voices --kokoro`)"
    if onnx_path.stat().st_size < 50 * 1024 * 1024:  # ONNX is ~80 MB; partial download → too small
        return False, f"{onnx_path.name} looks partial ({onnx_path.stat().st_size} bytes)"
    if not voices_path.exists():
        return False, f"missing {voices_path.name} (run `forge setup-voices --kokoro`)"
    try:
        import kokoro_onnx  # noqa: F401
    except ImportError:
        return False, "kokoro-onnx not installed (run `forge setup-voices --kokoro`)"
    try:
        import soundfile  # noqa: F401
    except ImportError:
        return False, "soundfile not installed (run `forge setup-voices --kokoro`)"
    return True, ""


def _kokoro_engine():
    """Lazy-load and cache the Kokoro model. Raises ImportError / RuntimeError on failure."""
    global _KOKORO_INSTANCE
    if _KOKORO_INSTANCE is not None:
        return _KOKORO_INSTANCE
    from kokoro_onnx import Kokoro  # type: ignore
    onnx_path, voices_path = _kokoro_paths()
    _KOKORO_INSTANCE = Kokoro(str(onnx_path), str(voices_path))
    return _KOKORO_INSTANCE


def _selected_tts_engine() -> str:
    """Resolve which engine to use: 'auto' (default) prefers Kokoro when ready, else 'say'.

    Env override: FORGE_TTS_ENGINE=auto|kokoro|say
    """
    requested = (os.environ.get("FORGE_TTS_ENGINE") or "auto").lower().strip()
    if requested == "say":
        return "say"
    if requested == "kokoro":
        ready, reason = _kokoro_ready()
        if not ready:
            sys.exit(red(f"FORGE_TTS_ENGINE=kokoro but not ready: {reason}"))
        return "kokoro"
    # auto
    ready, _ = _kokoro_ready()
    return "kokoro" if ready else "say"


def _synthesize_kokoro(voice: dict, text: str, out_path: Path) -> None:
    """Synthesize via Kokoro-ONNX → 24 kHz mono float WAV, then ffmpeg-reencode if requested ext != .wav.

    Long texts are split on sentence boundaries (`. ! ?`) so the model never sees a chunk
    larger than ~600 chars; pieces are concatenated in the output WAV. This avoids the
    transformer attention blow-up on long inputs and keeps memory steady.
    """
    import numpy as np
    import soundfile as sf  # type: ignore

    engine = _kokoro_engine()
    voice_id = voice.get("kokoro_voice_id") or voice["id"]
    speed = float(voice.get("kokoro_speed", 1.0))

    # Split on sentence boundaries — preserves prosody better than fixed-width chunking.
    chunks: list[str] = []
    buf = ""
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        if not sentence:
            continue
        if len(buf) + len(sentence) + 1 > 600 and buf:
            chunks.append(buf)
            buf = sentence
        else:
            buf = f"{buf} {sentence}".strip()
    if buf:
        chunks.append(buf)
    if not chunks:
        sys.exit(red("voice synthesis got empty text after sentence split"))

    print(dim(f"  · kokoro: voice={voice_id} speed={speed} chunks={len(chunks)}"))
    pieces: list[Any] = []
    sample_rate = 24000
    short_silence = None  # 80 ms gap between chunks
    for i, chunk in enumerate(chunks, 1):
        samples, sr = engine.create(chunk, voice=voice_id, speed=speed, lang="en-us")
        sample_rate = sr
        if short_silence is None:
            short_silence = np.zeros(int(sr * 0.08), dtype=samples.dtype)
        if i > 1:
            pieces.append(short_silence)
        pieces.append(samples)
    audio = np.concatenate(pieces) if len(pieces) > 1 else pieces[0]

    ext = out_path.suffix.lower()
    if ext == ".wav":
        tmp = _register_tmp(_tmp_sibling(out_path))
        sf.write(str(tmp), audio, sample_rate, subtype="PCM_16")
        os.replace(tmp, out_path)
        _discard_tmp(tmp)
    else:
        # Write WAV then re-encode for non-WAV targets
        wav_tmp = _register_tmp(_tmp_sibling(out_path.with_suffix(".wav")))
        sf.write(str(wav_tmp), audio, sample_rate, subtype="PCM_16")
        if shutil.which("ffmpeg") is None:
            os.replace(wav_tmp, out_path.with_suffix(".wav"))
            _discard_tmp(wav_tmp)
            sys.exit(red(f"ffmpeg required to convert to {ext}; got WAV at {out_path.with_suffix('.wav')}"))
        encode_opts: dict[str, list[str]] = {
            ".mp3": ["-acodec", "libmp3lame", "-b:a", "192k", "-ar", "44100", "-ac", "1"],
            ".m4a": ["-acodec", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "1"],
            ".aiff": ["-acodec", "pcm_s16be", "-ar", "44100", "-ac", "1"],
        }
        opts = encode_opts.get(ext, ["-ar", "44100", "-ac", "1"])
        out_tmp = _register_tmp(_tmp_sibling(out_path))
        run_subprocess(
            ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav_tmp), *opts, str(out_tmp)],
            check=True, timeout=VOICE_TIMEOUT_SEC,
        )
        os.replace(out_tmp, out_path)
        _discard_tmp(out_tmp)
        wav_tmp.unlink()
        _discard_tmp(wav_tmp)

    if not out_path.exists() or out_path.stat().st_size < 1024:
        sys.exit(red(f"kokoro produced empty {out_path.name}"))
    with contextlib.suppress(Exception):
        validate_audio(out_path)


def _synthesize_say(say_voice: str, say_rate: int | str, text: str, out_path: Path) -> None:
    """Synthesize via macOS `say`, used for fallback and language-specific voices."""
    if shutil.which("say") is None:
        sys.exit(red("macOS `say` not found and Kokoro not installed.")
                 + "\n" + dim("  Install Kokoro: forge setup-voices --kokoro"))

    if not _say_voice_installed(say_voice):
        sys.exit(red(f"voice '{say_voice}' not installed on this Mac") + "\n"
                 + dim("  Open System Settings → Accessibility → Spoken Content → System Voice "
                       "→ Manage Voices to download it. Or pick/configure a different voice."))

    ext = out_path.suffix.lower()
    aiff_final = out_path if ext == ".aiff" else out_path.with_suffix(".aiff")
    aiff_tmp = _register_tmp(_tmp_sibling(aiff_final))
    print(dim(f"  $ say -v {say_voice} -r {say_rate} -o {aiff_final.name}"))

    # Long text via stdin avoids argv length limits.
    if len(text) > 8 * 1024:
        run_subprocess(
            ["say", "-v", say_voice, "-r", str(say_rate), "-o", str(aiff_tmp), "-f", "/dev/stdin"],
            input=text.encode("utf-8"),
            timeout=VOICE_TIMEOUT_SEC,
            check=True,
        )
    else:
        run_subprocess(
            ["say", "-v", say_voice, "-r", str(say_rate), "-o", str(aiff_tmp), text],
            check=True,
            timeout=VOICE_TIMEOUT_SEC,
        )
    if not aiff_tmp.exists() or aiff_tmp.stat().st_size < 1024:
        sys.exit(red(f"say produced an empty/tiny file ({aiff_tmp.stat().st_size if aiff_tmp.exists() else 0} bytes)"))

    if ext == ".aiff":
        os.replace(aiff_tmp, out_path)
        _discard_tmp(aiff_tmp)
        with contextlib.suppress(Exception):
            validate_audio(out_path)
        return

    if shutil.which("ffmpeg") is None:
        os.replace(aiff_tmp, aiff_final)
        _discard_tmp(aiff_tmp)
        sys.exit(f"ffmpeg required to convert to {ext}; got AIFF at {aiff_final}")

    encode_opts: dict[str, list[str]] = {
        ".wav":  ["-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1"],
        ".mp3":  ["-acodec", "libmp3lame", "-b:a", "128k", "-ar", "44100", "-ac", "1"],
        ".m4a":  ["-acodec", "aac", "-b:a", "128k", "-ar", "44100", "-ac", "1"],
    }
    opts = encode_opts.get(ext, [])
    if not opts and ext not in (".aiff",):
        print(dim(f"  · note: no preset encode opts for {ext}; using ffmpeg defaults"))

    out_tmp = _register_tmp(_tmp_sibling(out_path))
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
           "-i", str(aiff_tmp), *opts, str(out_tmp)]
    run_subprocess(cmd, check=True, timeout=VOICE_TIMEOUT_SEC)
    os.replace(out_tmp, out_path)
    _discard_tmp(out_tmp)
    aiff_tmp.unlink()
    _discard_tmp(aiff_tmp)

    if not out_path.exists() or out_path.stat().st_size < 1024:
        sys.exit(red(f"ffmpeg produced empty {out_path.name}"))
    with contextlib.suppress(Exception):
        validate_audio(out_path)


def synthesize_voice(voice: dict, text: str, out_path: Path) -> None:
    """Synthesize voiceover audio via Kokoro-TTS (preferred) or macOS `say` (fallback).

    Engine selection:
      • FORGE_TTS_ENGINE=kokoro → require Kokoro (errors if not installed)
      • FORGE_TTS_ENGINE=say    → force `say`
      • FORGE_TTS_ENGINE=auto (default) → Kokoro if installed + model files present, else `say`

    Run `forge setup-voices --kokoro` once to install the higher-quality neural engine.
    """
    if not text or not text.strip():
        sys.exit(red("voice synthesis got empty text"))

    engine = _selected_tts_engine()
    if engine == "kokoro":
        with ResourceLock("tts") as lock:
            if lock.wait_seconds > 0.1:
                print(dim(f"  · waited {lock.wait_seconds:.1f}s for TTS lock"))
            _synthesize_kokoro(voice, text, out_path)
        return

    # Fallback: macOS `say`
    _synthesize_say(voice["say_voice"], voice["say_rate"], text, out_path)


def _audio_translation_langs(args) -> list[str]:
    raw = getattr(args, "translate", None)
    if raw is None:
        raw = os.environ.get(AUDIO_TRANSLATE_ENV)
    try:
        return [lang for lang in parse_language_codes(raw) if lang != "en"]
    except ValueError as e:
        sys.exit(red(str(e)))


def _translated_path(base: Path, lang: str, suffix: str) -> Path:
    return base.with_name(f"{base.stem}.{lang}{suffix}")


def translate_generated_audio(
    voice: dict,
    source_text: str,
    source_audio: Path,
    target_langs: list[str],
    *,
    label: str = "voiceover",
) -> list[dict[str, Any]]:
    """Translate the source script and synthesize sibling localized audio files."""
    if not target_langs:
        return []
    if not source_text.strip():
        sys.exit(red(f"cannot translate empty {label} text"))

    produced: list[dict[str, Any]] = []
    for lang in target_langs:
        print(cyan(f"  · translating {label} → {language_name(lang)} ({lang})"))
        with ResourceLock("llm") as lock:
            if lock.wait_seconds > 0.1:
                print(dim(f"    waited {lock.wait_seconds:.1f}s for local LLM lock"))
            translated = translate_texts_ollama([source_text], lang, model=TRANSLATE_MODEL)[0]
        txt_path = _translated_path(source_audio, lang, ".txt")
        audio_path = _translated_path(source_audio, lang, source_audio.suffix)
        write_text(txt_path, translated.strip() + "\n")
        synthesize_voice(voice, translated, audio_path)
        produced.append(
            {
                "lang": lang,
                "language": language_name(lang),
                "text_path": str(txt_path),
                "audio_path": str(audio_path),
                "translation_model": TRANSLATE_MODEL,
            }
        )
        print(green(f"    ✓ {audio_path.name}") + dim(f" + {txt_path.name}"))
    return produced


# ─────────────── book / episode production ───────────────

LANGUAGE_SAY_DEFAULTS = {
    "hi": "Lekha",
    # macOS does not ship a dedicated Marathi voice on this machine. Lekha is a
    # Devanagari Hindi voice: useful fallback, but QC marks pronunciation risk.
    "mr": "Lekha",
}


def _env_voice_for_lang(lang: str) -> str | None:
    key = f"FORGE_SAY_VOICE_{lang.upper().replace('-', '_')}"
    return os.environ.get(key)


_SARVAM_INDIC_LANGS = {"hi", "mr", "bn", "ta", "te", "gu", "kn", "ml", "pa", "od"}


def _sarvam_key_available() -> bool:
    if os.environ.get("SARVAM_TTS_KEY"):
        return True
    key_file = Path.home() / ".sarvam" / "key"
    return key_file.is_file() and key_file.stat().st_size > 10


def localized_tts_plan(lang: str, voice: dict) -> dict[str, Any]:
    lang = lang.lower()
    if lang == "en":
        return {
            "lang": lang,
            "engine": _selected_tts_engine(),
            "say_voice": voice.get("say_voice"),
            "native_voice": True,
            "pronunciation_risk": False,
            "note": "English voice preset",
        }
    # For Indian languages, prefer Sarvam Bulbul (cloud, production-grade) over
    # macOS `say` (which is robotic for Indic). Falls back to say only when no
    # Sarvam API key is configured.
    if lang in _SARVAM_INDIC_LANGS and _sarvam_key_available():
        return {
            "lang": lang,
            "engine": "sarvam",
            "say_voice": None,
            "native_voice": True,
            "pronunciation_risk": False,
            "note": f"Sarvam Bulbul v3 native voice for {language_name(lang)}",
        }
    configured = _env_voice_for_lang(lang)
    candidate = configured or LANGUAGE_SAY_DEFAULTS.get(lang)
    if candidate and _say_voice_installed(candidate):
        native = lang == "hi" and candidate == "Lekha"
        return {
            "lang": lang,
            "engine": "say",
            "say_voice": candidate,
            "native_voice": native,
            "pronunciation_risk": not native,
            "note": (
                "language-specific macOS voice"
                if native
                else f"fallback voice for {language_name(lang)}; configure FORGE_SAY_VOICE_{lang.upper()} for better pronunciation"
            ),
        }
    return {
        "lang": lang,
        "engine": _selected_tts_engine(),
        "say_voice": voice.get("say_voice"),
        "native_voice": False,
        "pronunciation_risk": True,
        "note": f"no configured native voice for {language_name(lang)} — run setup-voices or add SARVAM_TTS_KEY",
    }


def synthesize_voice_for_language(voice: dict, text: str, out_path: Path, lang: str) -> dict[str, Any]:
    plan = localized_tts_plan(lang, voice)
    if plan["engine"] == "sarvam":
        # Cloud TTS via Sarvam Bulbul v3 — shared helper with bin/audiobook.py
        # so prosody / sample rate / speaker defaults stay consistent across
        # both audiobook pipelines.
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from audiobook import tts_sarvam  # type: ignore
            import soundfile as sf  # type: ignore
            audio, sr = tts_sarvam(text, lang=lang)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            sf.write(out_path, audio, sr)
        except Exception as e:
            print(red(f"  · Sarvam TTS failed for {lang}: {e}; falling back to macOS say"))
            # Best-effort fallback to keep the pipeline running
            fallback_voice = LANGUAGE_SAY_DEFAULTS.get(lang)
            if fallback_voice and _say_voice_installed(fallback_voice):
                with ResourceLock("tts") as lock:
                    _synthesize_say(fallback_voice, voice.get("say_rate", 175), text, out_path)
            else:
                synthesize_voice(voice, text, out_path)
    elif plan["engine"] == "say" and plan.get("say_voice"):
        with ResourceLock("tts") as lock:
            if lock.wait_seconds > 0.1:
                print(dim(f"  · waited {lock.wait_seconds:.1f}s for TTS lock"))
            _synthesize_say(str(plan["say_voice"]), voice.get("say_rate", 175), text, out_path)
    else:
        synthesize_voice(voice, text, out_path)
    return plan


def clean_book_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"-\n(?=\w)", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def read_book_text(path: Path) -> str:
    if not path.exists():
        sys.exit(red(f"book not found: {path}"))
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md", ".markdown", ".text"}:
        return clean_book_text(path.read_text(encoding="utf-8", errors="ignore"))
    if suffix == ".rtf":
        try:
            from striprtf.striprtf import rtf_to_text  # type: ignore
        except ImportError:
            sys.exit(red("RTF input requires striprtf in this Python. Convert to .txt or install striprtf."))
        raw = path.read_text(encoding="utf-8", errors="ignore")
        return clean_book_text(rtf_to_text(raw))
    if suffix == ".pdf":
        try:
            import pypdf  # type: ignore
        except ImportError:
            sys.exit(red("PDF input requires pypdf in this Python. Convert to .txt/.md or install pypdf."))
        reader = pypdf.PdfReader(str(path))
        return clean_book_text("\n\n".join(page.extract_text() or "" for page in reader.pages))
    sys.exit(red(f"unsupported book format: {suffix}") + dim(" (use .txt, .md, .rtf, or .pdf)"))


def text_digest(text: str, *, max_chars: int = 12000) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    third = max_chars // 3
    mid_start = max(0, len(text) // 2 - third // 2)
    return "\n\n".join([
        "BEGINNING:\n" + text[:third],
        "MIDDLE:\n" + text[mid_start : mid_start + third],
        "ENDING:\n" + text[-third:],
    ])


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", text).strip())
    return [p.strip() for p in parts if p.strip()]


def fallback_episode_plan(source: str, *, title: str, segments: int) -> dict[str, Any]:
    sentences = split_sentences(source)
    if not sentences:
        sentences = [source[:300] or "A quiet opening moment becomes the start of a larger journey."]
    chunk_size = max(1, len(sentences) // segments)
    out_segments = []
    for i in range(segments):
        chunk = " ".join(sentences[i * chunk_size : (i + 1) * chunk_size]) or sentences[min(i, len(sentences) - 1)]
        words = chunk.split()[:34]
        script = " ".join(words).strip()
        if script and script[-1] not in ".!?":
            script += "."
        out_segments.append({
            "title": f"Part {i + 1}",
            "script": script,
            "visual_prompt": f"cinematic visual metaphor for {title}, part {i + 1}, no text",
            "thumbnail_headline": f"PART {i + 1}",
        })
    return {
        "title": title,
        "description": "Auto-generated four-part episode from source text.",
        "thumbnail": {
            "concept": f"cinematic hero image for {title}, no text",
            "headline": title[:34].upper(),
            "sub": "four-part mini episode",
        },
        "segments": out_segments,
    }


def plan_episode_from_source(source: str, *, title: str, preset: dict, segments: int, seconds: float) -> dict[str, Any]:
    system = (
        "You are a senior audio-video producer adapting source text into a tight mini episode. "
        "Return STRICT JSON only. Schema: "
        '{"title":"short title","description":"one sentence",'
        '"thumbnail":{"concept":"image prompt no text","headline":"2-5 words","sub":"short subtitle"},'
        '"segments":[{"title":"short","script":"28-40 spoken words, one paragraph",'
        '"visual_prompt":"cinematic 16:9 image prompt, no text",'
        '"thumbnail_headline":"2-4 words"}]}. '
        f"Return exactly {segments} segments. Each script should speak in about {seconds:.0f} seconds. "
        f"Brand style: {preset['name']} - {preset['description']}."
    )
    try:
        plan = call_llm(system, f"Episode title: {title}\n\nSource:\n{text_digest(source)}\n\nReturn JSON now.", timeout=180)
    except Exception as e:
        print(dim(f"  · episode planner fallback: {e}"))
        return fallback_episode_plan(source, title=title, segments=segments)
    if not isinstance(plan, dict) or not isinstance(plan.get("segments"), list):
        return fallback_episode_plan(source, title=title, segments=segments)
    plan.setdefault("title", title)
    plan.setdefault("description", "")
    plan.setdefault("thumbnail", {"concept": title, "headline": title[:34].upper(), "sub": ""})
    if len(plan["segments"]) < segments:
        fallback = fallback_episode_plan(source, title=title, segments=segments)
        plan["segments"].extend(fallback["segments"][len(plan["segments"]):])
    plan["segments"] = plan["segments"][:segments]
    for i, seg in enumerate(plan["segments"], 1):
        seg.setdefault("title", f"Part {i}")
        seg.setdefault("script", fallback_episode_plan(source, title=title, segments=segments)["segments"][i - 1]["script"])
        seg.setdefault("visual_prompt", f"cinematic visual metaphor for {title}, part {i}, no text")
        seg.setdefault("thumbnail_headline", f"PART {i}")
    return plan


def ensure_terminal_pause(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if text and text[-1] not in ".!?।":
        text += "."
    return text


def spoken_word_bounds(target_sec: float) -> tuple[int, int]:
    return max(6, math.ceil(target_sec * 2.4)), max(10, math.ceil(target_sec * 3.1))


def looks_like_complete_spoken_text(text: str) -> bool:
    stripped = ensure_terminal_pause(text)
    if not stripped:
        return False
    first = stripped.lstrip("\"'(")[:1]
    if first and first.isalpha() and first.islower():
        return False
    body = re.sub(r"[.!?।]+$", "", stripped).strip()
    if re.match(r"^(?:stands|steps|glides|moves|dips|paddles|watches|reaches|sets|looks|gazes)\b", body, re.I):
        return False
    if re.search(r"\b(?:a|an|the|in|on|at|to|with|of|and|or|but|for|from|by)$", body, re.I):
        return False
    if re.match(r"^(?:as|when|while|because)\b", body, re.I):
        tail = body.split(",", 1)[1].strip() if "," in body else ""
        if not tail or len(tail.split()) <= 5:
            return False
    return True


def fit_spoken_text(text: str, target_sec: float, *, label: str = "script") -> str:
    """Keep scripts near the target duration before TTS, instead of relying on speed-up."""
    text = ensure_terminal_pause(text)
    words = text.split()
    min_words, max_words = spoken_word_bounds(target_sec)
    if min_words <= len(words) <= max_words and looks_like_complete_spoken_text(text):
        return text
    system = (
        "Rewrite spoken narration to fit a strict duration. Return STRICT JSON "
        '{"script":"..."} only. Keep the meaning, make it natural aloud, use complete grammatical sentences, and end with punctuation.'
    )
    instruction = (
        f"Target duration: {target_sec:.1f}s. Target words: {min_words}-{max_words}.\n"
        f"{label}:\n{text}\n\nReturn JSON now."
    )
    best_candidate = ""
    try:
        obj = call_llm(system, instruction, temperature=0.2, timeout=90)
        candidate = ensure_terminal_pause(str(obj.get("script", "")).strip())
        if candidate:
            c_words = candidate.split()
            if len(c_words) > len(best_candidate.split()):
                best_candidate = candidate
            if min_words <= len(c_words) <= max_words + 4 and looks_like_complete_spoken_text(candidate):
                return candidate
    except Exception as e:
        print(dim(f"  · script duration fallback for {label}: {e}"))
    if len(words) < min_words and best_candidate:
        return best_candidate
    trimmed = " ".join(words[:max_words]).strip()
    return ensure_terminal_pause(trimmed)


def split_words_evenly(text: str, parts: int) -> list[str]:
    words = text.split()
    if not words:
        return [""] * parts
    size = max(1, (len(words) + parts - 1) // parts)
    chunks = [" ".join(words[i * size : (i + 1) * size]).strip() for i in range(parts)]
    while len(chunks) < parts:
        chunks.append("")
    return chunks[:parts]


def _requires_paddling_scene(text: str) -> bool:
    lower = text.lower()
    return any(word in lower for word in ("paddle", "paddler", "paddling", "canoe", "kayak", "lake", "water"))


def _has_boat_scene(text: str) -> bool:
    lower = text.lower()
    return any(word in lower for word in ("canoe", "kayak", "boat"))


def fallback_dialog_for_shot(segment: dict, chunk: str, shot_number: int, shot_count: int) -> str:
    scene_text = f"{segment.get('script') or ''} {segment.get('visual_prompt') or ''} {chunk}"
    if _requires_paddling_scene(scene_text):
        beats = [
            "Before sunrise, the paddler steadies the canoe on the quiet lake.",
            "The paddle touches the water, sending ripples through the orange reflection.",
            "The canoe glides forward as mist lifts from the lake.",
            "Still water holds the journey's first quiet secret.",
        ]
        return beats[(shot_number - 1) % len(beats)]
    candidate = ensure_terminal_pause(chunk)
    if looks_like_complete_spoken_text(candidate):
        return candidate
    title = str(segment.get("title") or "The scene")
    cleaned = re.sub(r"^[,;:\-\s]+", "", candidate).strip()
    cleaned = cleaned[:1].lower() + cleaned[1:] if cleaned else "the moment changes."
    return ensure_terminal_pause(f"{title} continues as {cleaned}")


def build_shot_visual_prompt(
    *,
    episode_title: str,
    segment_title: str,
    segment_visual: str,
    dialog: str,
    shot_number: int,
    shot_count: int,
    preset: dict,
) -> tuple[str, dict[str, Any]]:
    """Create a strict visual contract so shots depict the actual narration."""
    visual_rules = [
        "The image must literally depict the shot dialog, not a generic mood.",
        "Show the concrete subject, action, setting, and props named or implied by the dialog.",
        "No text, no captions, no title cards, no logos, no typography in the generated image.",
        "No unrelated lone silhouettes, no underwater scene, no vague spotlight portrait unless the dialog explicitly says that.",
        "Keep visual continuity with the same world, time of day, and subject across the episode.",
    ]
    lower = f"{dialog} {segment_visual} {segment_title}".lower()
    required_visuals: list[str] = []
    if _requires_paddling_scene(lower):
        required_visuals = [
            "a canoe or kayak carrying or immediately beside the paddler",
            "a paddle clearly visible in hand or touching the water",
            "the lake surface above water, not an underwater scene",
        ]
        visual_rules.append(
            "Because the dialog involves paddling/water, the image MUST visibly show a canoe or kayak, a paddle, and the lake surface above water."
        )
        visual_rules.append("Do not show a person standing in dark water without a boat or paddle.")
    if any(word in lower for word in ("sunrise", "dawn", "morning", "orange light")):
        visual_rules.append("Show dawn/sunrise light in the sky or reflected on the water.")

    contract = {
        "episode": episode_title,
        "segment_title": segment_title,
        "shot": shot_number,
        "shot_count": shot_count,
        "dialog": dialog,
        "must_convey": [
            "the action and objects in dialog",
            "clear narrative progression from previous and next shots",
            "the same theme and world as the episode",
        ],
        "rules": visual_rules,
    }
    prompt = "\n".join([
        f"EPISODE: {episode_title}",
        f"SEGMENT: {segment_title}",
        f"SHOT {shot_number} OF {shot_count}",
        f"NARRATION THIS IMAGE MUST DEPICT: {dialog}",
        f"SEGMENT VISUAL CONTEXT: {segment_visual}",
        f"BRAND VISUAL STYLE: {preset['flux']['positive_prefix']}",
        "REQUIRED VISIBLE ELEMENTS: " + ("; ".join(required_visuals) if required_visuals else "the concrete subject/action/props from the narration."),
        "STRICT VISUAL CONTRACT:",
        *[f"- {rule}" for rule in visual_rules],
        "Composition: cinematic 16:9 production still, clear readable subject/action, foreground-midground-background depth, no generated text.",
        "The final frame should be understandable even with the audio muted.",
    ])
    return prompt, contract


def fallback_shot_plan(
    segment: dict,
    *,
    episode_title: str,
    preset: dict,
    shot_count: int,
    shot_sec: float,
) -> list[dict[str, Any]]:
    script = ensure_terminal_pause(str(segment.get("script") or ""))
    chunks = split_words_evenly(script, shot_count)
    shots: list[dict[str, Any]] = []
    for i, chunk in enumerate(chunks, 1):
        base_dialog = fallback_dialog_for_shot(segment, chunk or script, i, shot_count)
        dialog = fit_spoken_text(base_dialog, shot_sec, label=f"{segment.get('title', 'segment')} shot {i}")
        visual_prompt, contract = build_shot_visual_prompt(
            episode_title=episode_title,
            segment_title=str(segment.get("title") or f"Part {i}"),
            segment_visual=str(segment.get("visual_prompt") or ""),
            dialog=dialog,
            shot_number=i,
            shot_count=shot_count,
            preset=preset,
        )
        shots.append({
            "id": f"shot-{i:02d}",
            "dialog": dialog,
            "visual_context": str(segment.get("visual_prompt") or ""),
            "visual_prompt": visual_prompt,
            "visual_contract": contract,
            "thumbnail_headline": str(segment.get("thumbnail_headline") or segment.get("title") or f"SHOT {i}")[:32],
        })
    return shots


def plan_shots_for_segment(
    segment: dict,
    *,
    episode_title: str,
    preset: dict,
    shot_count: int,
    shot_sec: float,
) -> list[dict[str, Any]]:
    min_words, max_words = spoken_word_bounds(shot_sec)
    system = (
        "You are a strict storyboard director. Break a segment into visual shots that must match narration. "
        "Return STRICT JSON only: "
        '{"shots":[{"dialog":"short spoken line","visual_prompt":"concise visible scene context, no text",'
        '"thumbnail_headline":"2-4 words"}]}. '
        f"Return exactly {shot_count} shots. Each dialog must speak in about {shot_sec:.1f}s "
        f"and contain {min_words}-{max_words} words. "
        "Every dialog must be a complete grammatical sentence, not a fragment. "
        "Every visual_prompt must literally depict its dialog with concrete visible objects/actions, but keep it under 22 words. "
        "If the dialog mentions paddling, water, lake, canoe, kayak, or paddle, the visual_prompt must show the boat/paddle/lake above water. "
        "Never use generic silhouettes, underwater spotlight scenes, or unrelated people unless the script explicitly requires them. "
        "Escape every quote inside strings, and do not include markdown."
    )
    user = (
        f"Episode: {episode_title}\n"
        f"Segment title: {segment.get('title')}\n"
        f"Segment script: {segment.get('script')}\n"
        f"Segment visual context: {segment.get('visual_prompt')}\n"
        f"Brand: {preset['name']} - {preset['description']}\n\n"
        "Return JSON now."
    )
    last_error: Exception | None = None
    raw_shots = None
    for attempt, temp in enumerate((0.25, 0.0), 1):
        try:
            obj = call_llm(system, user, temperature=temp, timeout=120)
            raw_shots = obj.get("shots") if isinstance(obj, dict) else None
            break
        except Exception as e:
            last_error = e
            if attempt == 1:
                print(dim(f"  · shot planner JSON retry: {e}"))
    if raw_shots is None and last_error is not None:
        print(dim(f"  · shot planner fallback: {last_error}"))
        return fallback_shot_plan(segment, episode_title=episode_title, preset=preset, shot_count=shot_count, shot_sec=shot_sec)
    if not isinstance(raw_shots, list) or len(raw_shots) < shot_count:
        return fallback_shot_plan(segment, episode_title=episode_title, preset=preset, shot_count=shot_count, shot_sec=shot_sec)
    for raw in raw_shots[:shot_count]:
        raw_visual = str(raw.get("visual_prompt") or "")
        scene_text = f"{raw.get('dialog') or ''} {raw_visual} {segment.get('script') or ''} {segment.get('visual_prompt') or ''}"
        if _requires_paddling_scene(scene_text) and not _has_boat_scene(raw_visual):
            print(dim("  · shot planner repair: adding canoe/kayak requirement to paddling/water shot"))
            raw["visual_prompt"] = (
                raw_visual.rstrip(". ")
                + ". Include a canoe or kayak carrying or immediately beside the paddler, with the paddle visible above the lake surface."
            )

    shots: list[dict[str, Any]] = []
    for i, raw in enumerate(raw_shots[:shot_count], 1):
        dialog = fit_spoken_text(str(raw.get("dialog") or "").strip(), shot_sec, label=f"{segment.get('title', 'segment')} shot {i}")
        if not dialog:
            dialog = fallback_shot_plan(segment, episode_title=episode_title, preset=preset, shot_count=shot_count, shot_sec=shot_sec)[i - 1]["dialog"]
        prompt, contract = build_shot_visual_prompt(
            episode_title=episode_title,
            segment_title=str(segment.get("title") or f"Part {i}"),
            segment_visual=str(raw.get("visual_prompt") or segment.get("visual_prompt") or ""),
            dialog=dialog,
            shot_number=i,
            shot_count=shot_count,
            preset=preset,
        )
        shots.append({
            "id": f"shot-{i:02d}",
            "dialog": dialog,
            "visual_context": str(raw.get("visual_prompt") or segment.get("visual_prompt") or ""),
            "visual_prompt": prompt,
            "visual_contract": contract,
            "thumbnail_headline": str(raw.get("thumbnail_headline") or segment.get("thumbnail_headline") or f"SHOT {i}")[:32],
        })
    return shots


def _slug(text: str, *, fallback: str = "episode") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug or fallback)[:48]


def timed_subtitle_rows(text: str, duration: float) -> list[dict[str, Any]]:
    sentences = split_sentences(text) or [text.strip()]
    weights = [max(1, len(s)) for s in sentences]
    total = sum(weights)
    cursor = 0.0
    rows: list[dict[str, Any]] = []
    for i, sentence in enumerate(sentences):
        if i == len(sentences) - 1:
            end = duration
        else:
            end = min(duration, cursor + duration * (weights[i] / total))
        rows.append({"start": cursor, "end": max(cursor + 0.25, end), "text": sentence})
        cursor = end
    return rows


def _subtitle_ts(seconds: float) -> str:
    millis = int(round(max(0.0, seconds) * 1000))
    h, rem = divmod(millis, 3600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(path: Path, rows: list[dict[str, Any]]) -> None:
    blocks = []
    for i, row in enumerate(rows, 1):
        blocks.append(
            f"{i}\n{_subtitle_ts(float(row['start']))} --> {_subtitle_ts(float(row['end']))}\n{row['text'].strip()}\n"
        )
    write_text(path, "\n".join(blocks).rstrip() + "\n")


def fit_audio_to_duration(audio_path: Path, target_path: Path, target_sec: float) -> dict[str, Any]:
    """Time-fit audio to exact shot length for predictable stitching.

    Short narration is slowed toward the target before any padding is added. That
    avoids the old failure mode where the voice ended early and a still image sat
    onscreen in silence.
    """
    duration = _probe_audio_duration(audio_path)
    if abs(duration - target_sec) <= 0.20:
        if audio_path != target_path:
            shutil.copy2(audio_path, target_path)
        return {
            "input_duration": duration,
            "output_duration": duration,
            "speed_factor": 1.0,
            "padded": False,
            "stretched": False,
        }
    tmp = _register_tmp(_tmp_sibling(target_path))
    if duration < target_sec:
        speed = max(0.5, duration / target_sec)
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(audio_path), "-af", f"atempo={speed:.6f},apad", "-t", f"{target_sec:.3f}",
            "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1", str(tmp),
        ]
        padded = speed <= 0.500001
        stretched = speed < 0.999
    else:
        speed = min(2.0, max(1.01, duration / target_sec))
        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(audio_path), "-af", f"atempo={speed:.6f}", "-t", f"{target_sec:.3f}",
            "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1", str(tmp),
        ]
        padded = False
        stretched = False
    run_subprocess(cmd, check=True, timeout=VOICE_TIMEOUT_SEC)
    os.replace(tmp, target_path)
    _discard_tmp(tmp)
    out_dur = _probe_audio_duration(target_path)
    return {
        "input_duration": duration,
        "output_duration": out_dur,
        "speed_factor": speed,
        "padded": padded,
        "stretched": stretched,
    }


def audio_fit_comfortable(audio_fit: dict[str, Any]) -> bool:
    speed = float(audio_fit.get("speed_factor", 1.0))
    return 0.70 <= speed <= 1.25 and not bool(audio_fit.get("padded"))


def revise_text_for_audio_fit(text: str, target_sec: float, audio_fit: dict[str, Any], *, label: str) -> str:
    speed = float(audio_fit.get("speed_factor", 1.0))
    if audio_fit_comfortable(audio_fit):
        return text
    min_words, max_words = spoken_word_bounds(target_sec)
    if speed < 0.75 or audio_fit.get("padded"):
        direction = "expand"
        min_words += 2
        max_words += 4
    else:
        direction = "shorten"
        min_words = max(6, min_words - 3)
        max_words = max(min_words, max_words - 3)
    system = (
        "Revise narration after a real TTS timing check. Return STRICT JSON "
        '{"script":"..."} only. Preserve meaning, use complete grammatical sentences, and end with punctuation.'
    )
    instruction = (
        f"Action: {direction} the line for natural audio timing.\n"
        f"Target duration: {target_sec:.1f}s. Target words: {min_words}-{max_words}.\n"
        f"Current TTS speed-fit factor: {speed:.2f}. Comfortable range is 0.70-1.25.\n"
        f"{label}:\n{text}\n\nReturn JSON now."
    )
    try:
        obj = call_llm(system, instruction, temperature=0.15, timeout=90)
        candidate = ensure_terminal_pause(str(obj.get("script", "")).strip())
        if candidate and candidate != text:
            c_words = len(candidate.split())
            if min_words <= c_words <= max_words + 4:
                print(dim(f"  · timing repair for {label}: {direction}ed line after TTS fit {speed:.2f}x"))
                return candidate
    except Exception as e:
        print(dim(f"  · timing repair skipped for {label}: {e}"))
    return text


def render_title_card(preset: dict, out_path: Path, *, headline: str, sub: str | None = None) -> None:
    from PIL import Image, ImageDraw
    palette = preset["palette_60_30_10"]
    bg = _hex(palette["dominant"]["hex"])
    accent = _hex(palette["accent"]["hex"])
    img = Image.new("RGBA", (THUMB_W, THUMB_H), bg)
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, int(THUMB_H * 0.62), THUMB_W, THUMB_H], fill=(0, 0, 0, 105))
    font, _ = fit_text_to_width(draw, headline.upper(), preset["typography"]["display_family"], 110, THUMB_W - 120, min_px=48)
    bbox = draw.textbbox((0, 0), headline.upper(), font=font)
    x = 60
    y = int(THUMB_H * 0.64)
    draw.text((x, y), headline.upper(), font=font, fill=(255, 255, 255, 255))
    draw.rectangle([x, y + (bbox[3] - bbox[1]) + 18, x + 260, y + (bbox[3] - bbox[1]) + 26], fill=accent)
    if sub:
        sub_font = system_font(preset["typography"]["body_family"], 34)
        draw.text((x, y + (bbox[3] - bbox[1]) + 42), sub, font=sub_font, fill=(255, 255, 255, 230))
    tmp = _register_tmp(_tmp_sibling(out_path))
    img.convert("RGB").save(tmp, "PNG", optimize=True)
    os.replace(tmp, out_path)
    _discard_tmp(tmp)
    validate_png(out_path, width=THUMB_W, height=THUMB_H)


def make_subtitled_podcast_video(
    image_path: Path,
    audio_path: Path,
    srt_path: Path,
    out_path: Path,
    *,
    target_sec: float,
    width: int = 1920,
    height: int = 1080,
    fps: int = 30,
    kenburns: bool = True,
) -> None:
    duration = target_sec
    total_frames = max(1, int(round(duration * fps)))
    if kenburns:
        zoom_delta = (1.12 - 1.0) / max(1, total_frames - 1)
        base_filter = (
            f"scale={width * 2}:{height * 2}:force_original_aspect_ratio=increase,"
            f"crop={width * 2}:{height * 2},"
            f"zoompan=z='min(1.0+on*{zoom_delta:.8f}\\,1.12)':d={total_frames}:s={width}x{height}:fps={fps}:"
            "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        )
    else:
        base_filter = f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}"
    style = "FontName=Helvetica,FontSize=28,PrimaryColour=&HFFFFFF&,OutlineColour=&H000000&,Outline=2,Alignment=2,MarginV=78"
    filter_str = (
        f"[0:v]{base_filter},"
        f"subtitles='{ffmpeg_filter_path(srt_path)}':force_style='{ffmpeg_filter_path(style)}'[v]"
    )
    tmp = _register_tmp(_tmp_sibling(out_path))
    run_subprocess(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-loop", "1", "-i", str(image_path),
            "-i", str(audio_path),
            "-filter_complex", filter_str,
            "-map", "[v]", "-map", "1:a",
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
            "-ar", "44100", "-ac", "2", "-r", str(fps), "-t", f"{target_sec:.3f}",
            "-movflags", "+faststart", str(tmp),
        ],
        check=True,
        timeout=DEFAULT_SUBPROCESS_TIMEOUT_SEC,
    )
    os.replace(tmp, out_path)
    _discard_tmp(tmp)


def ffmpeg_filter_path(value: str | Path) -> str:
    return str(value).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def ffconcat_line(path: Path) -> str:
    return "file '" + str(path).replace("'", "'\\''") + "'"


def concat_videos(paths: list[Path], out_path: Path) -> None:
    if not paths:
        sys.exit(red("no segment videos to stitch"))
    list_path = _register_tmp(out_path.with_suffix(".concat.txt"))
    write_text(list_path, "\n".join(ffconcat_line(p) for p in paths) + "\n")
    tmp = _register_tmp(_tmp_sibling(out_path))
    run_subprocess(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-c", "copy", "-movflags", "+faststart", str(tmp),
        ],
        check=True,
        timeout=DEFAULT_SUBPROCESS_TIMEOUT_SEC,
    )
    os.replace(tmp, out_path)
    _discard_tmp(tmp)
    if list_path.exists():
        list_path.unlink()
    _discard_tmp(list_path)


def concat_audio(paths: list[Path], out_path: Path) -> None:
    if not paths:
        sys.exit(red("no audio chunks to stitch"))
    list_path = _register_tmp(out_path.with_suffix(".concat.txt"))
    write_text(list_path, "\n".join(ffconcat_line(p) for p in paths) + "\n")
    tmp = _register_tmp(_tmp_sibling(out_path))
    run_subprocess(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(list_path),
            "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "1", str(tmp),
        ],
        check=True,
        timeout=DEFAULT_SUBPROCESS_TIMEOUT_SEC,
    )
    os.replace(tmp, out_path)
    _discard_tmp(tmp)
    if list_path.exists():
        list_path.unlink()
    _discard_tmp(list_path)


def translation_qc_twice(source: str, lang: str) -> tuple[str, list[dict[str, Any]]]:
    """Use Sarvam twice, back-translate twice, and select the steadier candidate."""
    candidates: list[dict[str, Any]] = []
    for pass_no in (1, 2):
        with ResourceLock("llm") as lock:
            translated = translate_texts_ollama([source], lang, model=TRANSLATE_MODEL, timeout=240)[0]
            back = translate_texts_ollama([translated], "en", source_lang=lang, model=TRANSLATE_MODEL, timeout=240)[0]
        src_words = max(1, len(source.split()))
        back_words = max(1, len(back.split()))
        ratio = back_words / src_words
        score = abs(1.0 - ratio)
        candidates.append({
            "pass": pass_no,
            "translation": translated,
            "back_translation": back,
            "length_ratio": ratio,
            "score": score,
            "model": TRANSLATE_MODEL,
            "wait_seconds": round(lock.wait_seconds, 2),
        })
    best = min(candidates, key=lambda c: c["score"])
    return str(best["translation"]), candidates


def episode_qc_record(
    *,
    lang: str,
    text: str,
    audio_fit: dict[str, Any],
    tts_plan: dict[str, Any],
    target_sec: float,
    translation_passes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    rows = timed_subtitle_rows(text, target_sec)
    punctuation_ok = bool(re.search(r"[.!?।]$", text.strip()))
    pause_count = len(rows)
    duration_ok = abs(float(audio_fit["output_duration"]) - target_sec) <= 0.30
    speed_factor = float(audio_fit.get("speed_factor", 1.0))
    speed_ok = 0.70 <= speed_factor <= 1.25
    issues = []
    if not punctuation_ok:
        issues.append("script lacks terminal punctuation for natural pause")
    if pause_count < 1:
        issues.append("no subtitle/pause rows generated")
    if not duration_ok:
        issues.append("audio duration outside target tolerance")
    if not speed_ok:
        issues.append(f"audio speed-fit factor outside comfortable range: {speed_factor:.2f}")
    if audio_fit.get("padded"):
        issues.append("audio shorter than shot; residual padding inserted")
    if tts_plan.get("pronunciation_risk"):
        issues.append(str(tts_plan.get("note") or "pronunciation risk"))
    return {
        "lang": lang,
        "duration_pass": duration_ok,
        "pause_pass": punctuation_ok and pause_count >= 1,
        "pronunciation_pass": not bool(tts_plan.get("pronunciation_risk")),
        "audio_fit": audio_fit,
        "tts": tts_plan,
        "subtitle_rows": pause_count,
        "translation_passes": translation_passes or [],
        "issues": issues,
    }

# ─────────────── subcommands ───────────────

def cmd_list(_args) -> int:
    print()
    print(bold("PRESETS"))
    for p in sorted(PRESETS_DIR.glob("*.json")):
        spec = json.loads(p.read_text())
        pal = spec["palette_60_30_10"]
        swatch = " · ".join([
            pal["dominant"]["hex"], pal["secondary"]["hex"], pal["accent"]["hex"]
        ])
        print(f"  {gold(spec['id']):24s} {dim(swatch)}")
        print(f"  {'':14s} {spec['description']}")
        print(f"  {'':14s} {dim('→ ' + spec['use_for'])}")
    print()
    print(bold("VOICES"))
    for v in load_voices():
        print(f"  {gold(v['id']):24s} {v['display']}")
        print(f"  {'':14s} {dim(v['tone_hint'])}")
    print()
    return 0


def cmd_show(args) -> int:
    preset_id = args.preset or prompt("preset", choices=list_preset_ids())
    print(json.dumps(load_preset(preset_id), indent=2))
    return 0


def cmd_mandala(args) -> int:
    out = args.out or str(
        Path.home()
        / "Pictures"
        / "forge-mandalas"
        / f"mandala-{args.style}-{args.symmetry}fold-seed{args.seed}.png"
    )
    out_path = Path(out).expanduser().resolve()
    config = MandalaConfig(
        style=args.style,
        symmetry=args.symmetry,
        rings=args.rings,
        complexity=args.complexity,
        seed=args.seed,
        width=args.width,
        height=args.height,
        mirror=not args.no_mirror,
        stroke_width=args.stroke_width,
        palette=args.palette,
        supersample=args.supersample,
    )
    try:
        artifact = write_mandala(config, out_path)
        validate_png(Path(artifact["png"]), width=args.width, height=args.height, min_bytes=1024)
    except ValueError as e:
        sys.exit(red(str(e)))
    print(green(f"✓ mandala PNG: {artifact['png']}"))
    print(dim(f"  SVG: {artifact['svg']}"))
    print(dim(f"  QC:  {artifact['qc']}"))
    return 0


def cmd_childrens_book(args) -> int:
    out = args.out or str(Path.home() / "Pictures" / f"forge-childrens-book-{args.theme}")
    out_dir = Path(out).expanduser().resolve()
    config = ChildrensBookConfig(
        theme=args.theme,
        pages=args.pages,
        symmetry=args.symmetry,
        rings=args.rings,
        complexity=args.complexity,
        seed=args.seed,
        width=args.width,
        height=args.height,
        palette=args.palette,
        supersample=args.supersample,
    )
    try:
        manifest = write_childrens_book(config, out_dir)
        for page in manifest["pages"]:
            validate_png(Path(page["png"]), width=args.width, height=args.height, min_bytes=1024)
    except ValueError as e:
        sys.exit(red(str(e)))
    print(green(f"✓ children's book pages: {out_dir}"))
    for page in manifest["pages"]:
        print(f"  {page['theme']:15s} {page['png']}")
    print(dim(f"  manifest: {out_dir / 'manifest.json'}"))
    return 0


def cmd_folk_art(args) -> int:
    out = args.out or str(Path.home() / "Pictures" / "forge-folk-art" / f"{args.theme}.png")
    out_path = Path(out).expanduser().resolve()
    config = FolkArtConfig(
        theme=args.theme,
        width=args.width,
        height=args.height,
        complexity=args.complexity,
        stroke_width=args.stroke_width,
        palette=args.palette,
        supersample=args.supersample,
    )
    try:
        artifact = write_folk_art_page(config, out_path)
        validate_png(Path(artifact["png"]), width=args.width, height=args.height, min_bytes=1024)
    except ValueError as e:
        sys.exit(red(str(e)))
    print(green(f"✓ folk-art page: {artifact['png']}"))
    print(dim(f"  SVG: {artifact['svg']}"))
    print(dim(f"  QC:  {artifact['qc']}"))
    return 0


def cmd_minimal_animal(args) -> int:
    """Beta closed-loop <=8-line animal mark generator."""
    description = (getattr(args, "animal", None) or getattr(args, "description", None) or "").strip()
    if not description:
        sys.exit(red("minimal-animal needs --animal/--description text"))
    slug = _slugify(description, max_len=44)
    out = args.out or str(Path.home() / "Pictures" / "forge-minimal-animals" / f"{slug}.png")
    out_path = Path(out).expanduser().resolve()

    gpu_check: dict[str, Any] | None = None
    if not getattr(args, "skip_gpu_check", False):
        try:
            gpu_check = require_metal_acceleration(label="minimal-animal workflow GPU guard", require_mflux=False)
        except RuntimeError as e:
            sys.exit(red(str(e)))

    config = MinimalAnimalConfig(
        description=description,
        max_lines=args.max_lines,
        seed=args.seed,
        width=args.width,
        height=args.height,
        stroke_width=args.stroke_width,
        background=args.background,
        stroke=args.stroke,
        supersample=args.supersample,
    )
    try:
        artifact = write_minimal_animal(config, out_path)
        validate_png(Path(artifact["png"]), width=args.width, height=args.height, min_bytes=1024)
    except ValueError as e:
        sys.exit(red(str(e)))
    if gpu_check:
        manifest_path = Path(artifact["manifest"])
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["gpu_guard"] = gpu_check
        write_json(manifest_path, manifest)
    qc = json.loads(Path(artifact["qc"]).read_text(encoding="utf-8"))
    print(green(f"✓ minimal animal mark: {artifact['png']}"))
    print(dim(f"  type: {qc['animal_type']}  lines: {qc['line_count']}/{qc['max_lines']}  status: {'PASS' if qc['closed_loop_pass'] else 'FAIL'}"))
    print(dim(f"  SVG:      {artifact['svg']}"))
    print(dim(f"  QC:       {artifact['qc']}"))
    print(dim(f"  manifest: {artifact['manifest']}"))
    return 0


# ─────────────── style engines (forge engine ...) ───────────────


PROMPT_LIBRARY_PATH = FORGE_HOME / "brand" / "prompts" / "library.json"
DEFAULT_ENGINE_OUTPUT_ROOT = Path.home() / "Desktop" / "forge-test" / "engine-renders"


def _engine_img2img(src_path: Path, prompt: str, dst_path: Path, *,
                    strength: float = 0.85, seed: int = 42, steps: int = 32,
                    guidance: float = 3.5) -> None:
    """Engine-driven img2img — restyle a source image with an engine's directive.

    Different from `_img2img_refine` (low-denoise polish, ≤0.50 strength).
    This is for the "turn my photo into the engine's style" use-case:
    high-strength restyle preferring FLUX-Kontext (true instruction-following),
    falling back to FLUX-dev img2img.

    Kontext is sensitive to prompt length — engine directives are ~2500 chars
    which overflows the model's effective attention. Truncate to ~1400 chars
    for the Kontext path; the source image carries the visual anchor anyway.
    """
    strength = max(0.05, min(0.95, float(strength)))
    tmp = _register_tmp(_tmp_sibling(dst_path))

    # Kontext-friendly prompt cap. Keep the first ~1400 chars (subject +
    # primary rules) which is where engines put the load-bearing content.
    kontext_prompt = prompt if len(prompt) <= 1400 else prompt[:1400].rsplit(". ", 1)[0] + "."

    # Kontext converges faster than dev — clamp steps to ≤30 to avoid the
    # over-iteration that produces noise on dense prompts.
    kontext_steps = min(int(steps), 30)

    kontext_ready, _ = _flux_model_ready("kontext-dev")
    dev_ready, dev_reason = _flux_model_ready("dev")

    if kontext_ready and shutil.which("mflux-generate-kontext"):
        cmd = [
            "mflux-generate-kontext",
            *_mflux_runtime_args(),
            "--base-model", "dev",
            "--prompt", kontext_prompt,
            "--image-path", str(src_path),
            "--guidance", "2.5",
            "--steps", str(kontext_steps),
            "--seed", str(seed),
            "--output", str(tmp),
        ]
        mode_label = f"Kontext (prompt {len(kontext_prompt)}/{len(prompt)} chars, steps={kontext_steps})"
    elif kontext_ready:
        cmd = [
            "mflux-generate",
            *_mflux_runtime_args(),
            "--model", "dev-kontext",
            "--prompt", kontext_prompt,
            "--init-image-path", str(src_path),
            "--steps", str(kontext_steps),
            "--guidance", "3.5",
            "--seed", str(seed),
            "--output", str(tmp),
        ]
        mode_label = f"Kontext legacy (prompt {len(kontext_prompt)}/{len(prompt)} chars, steps={kontext_steps})"
    elif dev_ready:
        cmd = [
            "mflux-generate",
            *_mflux_runtime_args(),
            "--model", "dev",
            "--prompt", prompt,
            "--image-path", str(src_path),
            "--image-strength", f"{1.0 - strength:.3f}",  # mflux: higher = preserve more
            "--steps", str(steps),
            "--guidance", str(guidance),
            "--seed", str(seed),
            "--output", str(tmp),
        ]
        mode_label = f"dev img2img (strength={strength})"
    else:
        sys.exit(red(
            f"Neither Kontext-dev nor FLUX.1-dev is ready.\n"
            f"  dev: {dev_reason}\n"
            f"  Run: hf download black-forest-labs/FLUX.1-dev"
        ))

    print(dim(f"    · {mode_label} · steps={steps} seed={seed}"))
    try:
        require_metal_acceleration(label=f"{cmd[0]} ({mode_label})")
    except RuntimeError as e:
        sys.exit(red(str(e)))
    with ResourceLock("metal-heavy") as lock:
        if lock.wait_seconds > 0.1:
            print(dim(f"    · waited {lock.wait_seconds:.1f}s for Metal lock"))
        _preflight_memory(label=f"{cmd[0]} ({mode_label})")
        run_subprocess(
            cmd, check=True, timeout=MFLUX_TIMEOUT_SEC,
            heartbeat_label=f"{cmd[0]} render",
            heartbeat_seconds=MFLUX_HEARTBEAT_SEC,
        )
    validate_png(tmp, min_bytes=4096)
    os.replace(tmp, dst_path)
    _discard_tmp(tmp)


def _img2img_refine(src_path: Path, prompt: str, dst_path: Path, *,
                    strength: float = 0.20, seed: int = 42, steps: int = 25) -> None:
    """Low-denoise img2img refinement pass via FLUX-dev. Adds micro-detail.

    `strength` is the *denoising* strength: 0.05 = barely touch, 0.40 = rework.
    mflux uses inverted semantics for --init-image-strength (higher = preserve
    original more), so we pass 1.0 - strength.
    """
    strength = max(0.05, min(0.5, float(strength)))
    tmp = _register_tmp(_tmp_sibling(dst_path))
    # mflux flag names changed between versions; current installed mflux uses
    # `--image-path` + `--image-strength` (NOT the older `--init-image-*`).
    cmd = [
        "mflux-generate",
        *_mflux_runtime_args(),
        "--model", "dev",
        "--prompt", prompt,
        "--image-path", str(src_path),
        "--image-strength", f"{1.0 - strength:.3f}",
        "--steps", str(steps),
        "--guidance", "3.5",
        "--seed", str(seed),
        "--output", str(tmp),
    ]
    try:
        require_metal_acceleration(label="mflux img2img refine")
    except RuntimeError as e:
        sys.exit(red(str(e)))
    with ResourceLock("metal-heavy") as lock:
        if lock.wait_seconds > 0.1:
            print(dim(f"    · waited {lock.wait_seconds:.1f}s for Metal lock"))
        _preflight_memory(label="mflux img2img refine")
        run_subprocess(
            cmd, check=True, timeout=MFLUX_TIMEOUT_SEC,
            heartbeat_label=f"{cmd[0]} render",
            heartbeat_seconds=MFLUX_HEARTBEAT_SEC,
        )
    validate_png(tmp, min_bytes=4096)
    os.replace(tmp, dst_path)
    _discard_tmp(tmp)


def _write_contact_sheet(gallery_dir: Path, *, engine: str, subject: str,
                          variants: list[dict[str, Any]]) -> Path:
    """Write an HTML contact sheet showing all seed variants in a grid."""
    rows = []
    for v in variants:
        seed = v["seed"]
        png = v["png_name"]
        rows.append(f"""
  <div class="card">
    <a href="{png}"><img src="{png}" loading="lazy"/></a>
    <div class="label">seed {seed:02d} · <a href="{png}.directive.json">directive</a></div>
  </div>""")
    import html as _html
    safe_subject = _html.escape(subject[:300])
    safe_engine = _html.escape(engine)
    body = (
        f"<!DOCTYPE html>\n<html><head>"
        f"<title>Engine gallery — {safe_engine}</title>"
        f"<style>"
        f"body{{background:#0e0e0e;color:#e8e4da;font-family:-apple-system,sans-serif;"
        f"margin:0;padding:24px;}}"
        f".header{{margin-bottom:20px;max-width:1100px}}"
        f"h1{{margin:0 0 8px;font-size:20px;font-weight:600;letter-spacing:.02em}}"
        f".subject{{color:#a09b8d;font-style:italic;line-height:1.4}}"
        f".grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(420px,1fr));gap:14px}}"
        f".card{{background:#1a1a1a;padding:6px;border-radius:6px}}"
        f".card img{{width:100%;height:auto;border-radius:3px;display:block}}"
        f".label{{padding:8px 4px 2px;color:#888;font-size:13px}}"
        f".label a{{color:#888;text-decoration:none}}"
        f".label a:hover{{color:#e8e4da}}"
        f"</style></head><body>"
        f"<div class='header'>"
        f"<h1>{safe_engine} · {len(variants)} seed variants</h1>"
        f"<div class='subject'>{safe_subject}</div>"
        f"</div>"
        f"<div class='grid'>{''.join(rows)}\n</div>"
        f"</body></html>\n"
    )
    sheet = gallery_dir / "contact-sheet.html"
    write_text(sheet, body)
    return sheet


def _load_prompt_library() -> dict[str, dict[str, Any]]:
    if not PROMPT_LIBRARY_PATH.is_file():
        return {}
    raw = json.loads(PROMPT_LIBRARY_PATH.read_text())
    # Strip _-prefixed metadata keys
    return {k: v for k, v in raw.items() if not k.startswith("_")}


def _slugify(text: str, *, max_len: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return s[:max_len] or "untitled"


def cmd_engine_list(_args) -> int:
    import style_engines  # type: ignore
    for name in style_engines.list_engines():
        print(name)
    return 0


def cmd_engine_recipes(args) -> int:
    library = _load_prompt_library()
    if not library:
        print(yellow(f"no recipes found at {PROMPT_LIBRARY_PATH}"))
        return 0
    filtered = (
        [(k, v) for k, v in library.items() if v.get("engine") == args.engine]
        if args.engine else list(library.items())
    )
    if not filtered:
        print(yellow(f"no recipes for engine={args.engine!r}"))
        return 0
    # Group by engine for readability.
    by_engine: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    for k, v in filtered:
        by_engine.setdefault(v.get("engine", "?"), []).append((k, v))
    for eng in sorted(by_engine):
        print(bold(f"\n{eng}"))
        for rid, recipe in sorted(by_engine[eng]):
            desc = recipe.get("description", "")
            print(f"  {gold(rid):40s} {dim(desc)}")
    print()
    print(dim(f"usage: forge engine render --recipe <id>   (override --subject/--config/--seed to remix)"))
    return 0


def cmd_engine_describe(args) -> int:
    import style_engines  # type: ignore
    try:
        info = style_engines.describe_engine(args.name)
    except ValueError as e:
        sys.exit(red(str(e)))
    print(json.dumps(info, indent=2, ensure_ascii=False))
    return 0


def _build_engine_config(engine_cls, subject: str, overrides: str | None, seed: int):
    """Construct the engine's nested-dataclass config from --subject + --config knob=value.

    Uses `typing.get_type_hints` because the engine modules use
    `from __future__ import annotations`, which makes `field.type` a string;
    we need the actual class to introspect nested dataclass groups.
    """
    from dataclasses import fields, is_dataclass
    import typing
    import style_engines  # type: ignore
    import _engine_base   # type: ignore

    # Resolve string annotations to actual types in the engine module scope.
    type_hints_top = typing.get_type_hints(
        engine_cls.config_cls,
        globalns=vars(style_engines),
        localns={**vars(_engine_base)},
    )

    overrides_map: dict[str, str] = {}
    if overrides:
        for kv in overrides.split(","):
            kv = kv.strip()
            if not kv:
                continue
            if "=" not in kv:
                sys.exit(red(f"bad override {kv!r}; expected key=value or group.key=value"))
            k, v = kv.split("=", 1)
            overrides_map[k.strip()] = v.strip()

    # Strict validation: every override key must map to a real `<group>.<field>`
    # in the engine's config schema. Build the set of all valid keys first.
    valid_keys: set[str] = set()
    for f in fields(engine_cls.config_cls):
        rt = type_hints_top.get(f.name)
        if rt is not None and is_dataclass(rt):
            for gf in fields(rt):
                valid_keys.add(f"{f.name}.{gf.name}")
                valid_keys.add(gf.name)  # bare-name shortcut tolerated too
    unknown = sorted(k for k in overrides_map if k not in valid_keys)
    if unknown:
        valid_grouped: dict[str, list[str]] = {}
        for k in sorted(valid_keys):
            if "." in k:
                g, n = k.split(".", 1)
                valid_grouped.setdefault(g, []).append(n)
        lines = [
            red(f"unknown --config knob(s): {', '.join(unknown)}"),
            "",
            "valid knobs for this engine:",
        ]
        for g, ns in sorted(valid_grouped.items()):
            lines.append(f"  {g}.{{ {', '.join(ns)} }}")
        lines.append("")
        lines.append(dim(f"see all valid VALUES with: forge engine describe {engine_cls.name}"))
        sys.exit("\n".join(lines))

    def _coerce(raw: str, resolved_type: Any) -> Any:
        # CLI / recipe values arrive as strings. Cast to the dataclass field's
        # actual type so int / float / bool fields don't break downstream.
        if resolved_type is int:
            return int(raw)
        if resolved_type is float:
            return float(raw)
        if resolved_type is bool:
            return str(raw).strip().lower() in ("1", "true", "yes", "y", "on")
        return raw

    def _resolve_group(top_field_name: str, group_cls: type, base_kwargs: dict | None = None) -> Any:
        kwargs = dict(base_kwargs or {})
        group_hints = typing.get_type_hints(
            group_cls,
            globalns=vars(style_engines),
            localns={**vars(_engine_base)},
        )
        for f in fields(group_cls):
            keyed = f"{top_field_name}.{f.name}"
            field_type = group_hints.get(f.name, str)
            if keyed in overrides_map:
                kwargs[f.name] = _coerce(overrides_map[keyed], field_type)
            elif f.name in overrides_map and f.name not in {tf.name for tf in fields(engine_cls.config_cls)}:
                kwargs[f.name] = _coerce(overrides_map[f.name], field_type)
        return group_cls(**kwargs)

    top_kwargs: dict[str, Any] = {"seed": seed}
    for f in fields(engine_cls.config_cls):
        if f.name == "seed":
            continue
        # f.type is a string under PEP 563; consult the resolved hints.
        resolved_type = type_hints_top.get(f.name)
        if resolved_type is None:
            continue
        if is_dataclass(resolved_type):
            base_kwargs: dict[str, Any] = {}
            # The subject group always has a `subject` str field — pass --subject.
            group_field_names = {gf.name for gf in fields(resolved_type)}
            if "subject" in group_field_names:
                base_kwargs["subject"] = subject
            top_kwargs[f.name] = _resolve_group(f.name, resolved_type, base_kwargs)
    return engine_cls.config_cls(**top_kwargs)


def cmd_engine_render(args) -> int:
    import style_engines  # type: ignore

    # Resolve recipe (if any) → seed engine_name/subject/config/seed defaults.
    recipe_id = args.recipe
    recipe: dict[str, Any] = {}
    if recipe_id:
        library = _load_prompt_library()
        if recipe_id not in library:
            sys.exit(red(f"unknown recipe {recipe_id!r}; see `forge engine recipes`"))
        recipe = library[recipe_id]

    engine_name = args.name or recipe.get("engine")
    if not engine_name:
        sys.exit(red("must provide engine name (e.g. noir-cinema) or --recipe"))
    try:
        eng_cls = style_engines.get_engine(engine_name)
    except ValueError as e:
        sys.exit(red(str(e)))

    # CLI args override recipe; recipe fills in what's missing.
    subject = args.subject or recipe.get("subject")
    if not subject:
        sys.exit(red("--subject is required (or use --recipe that includes one)"))

    # Merge recipe config (dict) with CLI overrides (comma string). CLI wins.
    merged_config_pairs: list[str] = []
    for k, v in (recipe.get("config") or {}).items():
        merged_config_pairs.append(f"{k}={v}")
    if args.config:
        merged_config_pairs.append(args.config)
    config_str = ",".join(merged_config_pairs) if merged_config_pairs else None

    seed = args.seed if args.seed is not None else int(recipe.get("seed", 1))

    try:
        config = _build_engine_config(eng_cls, subject, config_str, seed)
        directive = eng_cls.build(config)
    except ValueError as e:
        sys.exit(red(f"engine build failed: {e}"))

    # Append user-supplied --negative terms (comma-separated) to the directive's
    # negative list. The master primer still merges in MASTER_NEGATIVES at gen time.
    extra_negs = getattr(args, "extra_negatives", None)
    if extra_negs:
        extras = [n.strip() for n in extra_negs.split(",") if n.strip()]
        if extras:
            from _engine_base import Directive  # type: ignore
            directive = Directive(
                engine=directive.engine,
                positive=directive.positive,
                negatives=tuple(list(directive.negatives) + extras),
                palette_60_30_10=directive.palette_60_30_10,
                runtime=directive.runtime,
                seed=directive.seed,
                audit={**directive.audit, "extra_negatives": extras},
                config=directive.config,
                masters=directive.masters,
            )

    # Default output path → ~/Desktop/forge-test/engine-renders/<engine>/<recipe-or-slug>.png
    # For multi-seed (--seeds N), output lands in a directory: <engine>/<slug>/seed{NN}.png
    seeds_n = max(1, int(getattr(args, "seeds", 1) or 1))
    # A6: profile-level default_refine flips refine ON when not explicitly set.
    # `--refine` (explicit on) always wins. `--no-refine` (explicit off) wins
    # over the profile default. Otherwise the profile decides.
    explicit_refine = bool(getattr(args, "refine", False))
    explicit_no_refine = bool(getattr(args, "no_refine", False))
    profile_default_refine = bool(PROFILES.get(args.profile or "", {}).get("default_refine", False))
    if explicit_no_refine:
        refine = False
    elif explicit_refine:
        refine = True
    else:
        refine = profile_default_refine
    if refine and profile_default_refine and not explicit_refine:
        print(dim(f"  · --profile {args.profile} enables --refine by default (use --no-refine to opt out)"))
    refine_strength = float(getattr(args, "refine_strength", 0.25) or 0.25)
    # Resolution shortcuts: --ultra-res > --hi-res > explicit --width/--height >
    # engine's default_runtime width/height > falls through to THUMB_W/H (1280×720).
    # Engine-declared default aspect lets coloring-book engine pick portrait
    # and mandala-art pick square — the genres' natural canvases.
    if getattr(args, "ultra_res", False):
        eff_w, eff_h = 2048, 1152
    elif getattr(args, "hi_res", False):
        eff_w, eff_h = 1920, 1080
    else:
        eff_w = getattr(args, "width", None) or directive.runtime.get("width")
        eff_h = getattr(args, "height", None) or directive.runtime.get("height")
    guidance_override = getattr(args, "guidance", None)
    steps_override = getattr(args, "steps", None)
    if args.out:
        out_path = Path(args.out).expanduser().resolve()
        # mflux auto-appends .png when the output path has no image extension,
        # which mismatches with our temp-file naming + validation. Normalize
        # to always carry .png so _tmp_sibling and validate_png see the same
        # path mflux actually writes to.
        if out_path.suffix.lower() not in {".png", ".jpg", ".jpeg"}:
            out_path = out_path.with_suffix(out_path.suffix + ".png") if out_path.suffix else out_path.with_suffix(".png")
    else:
        slug = recipe_id or _slugify(subject)
        if seeds_n == 1:
            out_path = (DEFAULT_ENGINE_OUTPUT_ROOT / engine_name / f"{slug}.png").resolve()
        else:
            out_path = (DEFAULT_ENGINE_OUTPUT_ROOT / engine_name / slug / "seed01.png").resolve()
    gallery_dir = out_path.parent if seeds_n > 1 else None
    out_path.parent.mkdir(parents=True, exist_ok=True)

    synth = directive.to_synthetic_preset()

    # ── Auto-LoRA stack ─────────────────────────────────────────────────
    # Each engine declares a curated `default_lora_stack` (see brand/loras/
    # README.md). We auto-apply files that exist on disk, unless
    # --no-default-loras was passed, or the user supplied explicit LoRAs
    # via the preset/series path (in which case we don't override).
    if not getattr(args, "no_default_loras", False):
        engine_loras: list[str] = []
        engine_lora_scales: list[float] = []
        missing_loras: list[str] = []
        for rel_path, scale in getattr(eng_cls, "default_lora_stack", ()) or ():
            abs_path = LORAS_DIR / rel_path
            # If the declared entry is a directory (the HF download target),
            # auto-pick the largest .safetensors inside. HF preserves upstream
            # filenames so we can't hardcode the actual filename — but we can
            # rely on each LoRA repo having one main weights file in the dir
            # the user downloaded into.
            if abs_path.is_dir():
                candidates = sorted(
                    abs_path.glob("*.safetensors"),
                    key=lambda p: p.stat().st_size,
                    reverse=True,
                )
                if candidates:
                    abs_path = candidates[0]
            if abs_path.exists() and abs_path.is_file():
                engine_loras.append(str(abs_path.resolve()))
                engine_lora_scales.append(float(scale))
            else:
                missing_loras.append(rel_path)
        if engine_loras:
            synth["flux"]["lora_paths"] = engine_loras
            synth["flux"]["lora_scales"] = engine_lora_scales
            print(dim(f"  · LoRA stack: {len(engine_loras)} auto-applied — " +
                      ", ".join(f"{Path(p).parent.name}@{s}" for p, s in zip(engine_loras, engine_lora_scales))))
        elif missing_loras:
            print(dim(f"  · LoRA stack: 0 applied (curated picks not on disk — " +
                      ", ".join(missing_loras) +
                      "). See brand/loras/README.md for download commands."))

    label = f"recipe={recipe_id} " if recipe_id else ""
    print(cyan(f"▶ engine={engine_name} {label}subject={subject[:60]!r}"))
    print(dim(f"  · masters: {len(directive.masters)} citations baked into prompt"))
    print(dim(f"  · prompt: {len(directive.positive)} chars · negatives: {len(directive.negatives)}"))
    res_label = f"{eff_w}x{eff_h}" if eff_w and eff_h else "1280x720 (default)"
    print(dim(f"  · seeds: {seeds_n} (base {directive.seed})  refine: {refine}  res: {res_label}  guidance: {guidance_override or 'preset-default'}"))

    # If --from-image is set, we skip text-to-image and instead restyle the
    # source image with the engine's directive via FLUX-Kontext (or dev img2img).
    from_image = getattr(args, "from_image", None)
    from_image_strength = float(getattr(args, "from_image_strength", 0.85) or 0.85)
    src_image_path: Path | None = None
    if from_image:
        src_image_path = Path(from_image).expanduser().resolve()
        if not src_image_path.exists():
            sys.exit(red(f"--from-image not found: {src_image_path}"))
        if src_image_path.stat().st_size < 1024:
            sys.exit(red(f"--from-image too small ({src_image_path.stat().st_size} bytes): {src_image_path}"))
        # Kontext dual-conditioning paths roughly double activation memory vs
        # plain FLUX-dev. Combined with hi-/ultra-res, Metal OOMs (GPU page
        # fault → WindowServer freeze) on M5 Max with 64-80 GB unified memory.
        # Cap img2img to default 1280x720 — use --upscale 4x/8x for final
        # resolution instead. See AUDIT.md / RES.md for the math.
        if (eff_w and eff_w > 1280) or (eff_h and eff_h > 720):
            sys.exit(red(
                f"--from-image is incompatible with hi-res / ultra-res / custom "
                f"width>1280 or height>720 (would over-subscribe Metal memory).\n"
                + dim(f"  requested: {eff_w}x{eff_h}\n"
                      f"  fix: drop --hi-res / --ultra-res, OR add --upscale 4x / 8x\n"
                      f"       (renders Kontext at 1280x720, then upscales via RealESRGAN)")
            ))
        # Force the safe Kontext baseline (overrides any stray --width / --height).
        eff_w, eff_h = 1280, 720
        print(dim(f"  · from-image: {src_image_path}  strength: {from_image_strength}  res: 1280x720 (Kontext safe baseline)"))

    actual_model, actual_steps, actual_guidance = _resolve_flux_runtime(
        synth,
        draft=args.draft,
        profile=args.profile,
        steps_override=steps_override,
    )
    if guidance_override is not None:
        actual_guidance = float(guidance_override)
    actual_quantize = _resolve_quantize(getattr(args, "quantize", None))
    actual_runtime = {
        **directive.runtime,
        "model": actual_model,
        "steps": int(actual_steps),
        "guidance": float(actual_guidance),
        "width": eff_w,
        "height": eff_h,
        "profile": args.profile or ("cool" if args.draft else None),
        "quantize": actual_quantize if actual_quantize is not None else "fp16",
    }

    variants: list[dict[str, Any]] = []
    base_seed = directive.seed
    from _engine_base import Directive  # type: ignore

    # Pre-batch the txt2img base renders into a single mflux invocation when
    # we have multiple seeds. mflux loads the model once and inferences N
    # times; verified ~5.6× faster on cool/schnell, ~15-20% on quality. The
    # img2img / Kontext path stays per-seed (different conditioning per call).
    batch_pre_rendered: set[int] = set()
    if not src_image_path and seeds_n > 1:
        batch_seeds = [base_seed + i for i in range(seeds_n)]
        batch_targets = []
        for i, this_seed in enumerate(batch_seeds):
            png_path_i = gallery_dir / f"seed{i+1:02d}.png"
            base_target_i = png_path_i if not refine else png_path_i.with_name(png_path_i.stem + "-base.png")
            batch_targets.append(base_target_i)
        print(cyan(f"  ▶ batch render: {seeds_n} seeds [{', '.join(str(s) for s in batch_seeds)}] in 1 mflux call"))
        flux_generate_batch(
            synth, "", batch_targets,
            seeds=batch_seeds,
            steps=steps_override,
            series=None, draft=args.draft, profile=args.profile,
            width=eff_w, height=eff_h,
            guidance_override=guidance_override,
            quantize=getattr(args, "quantize", None),
        )
        batch_pre_rendered = set(batch_seeds)

    for i in range(seeds_n):
        this_seed = base_seed + i
        if seeds_n > 1:
            png_path = gallery_dir / f"seed{i+1:02d}.png"
        else:
            png_path = out_path

        # Per-seed directive (only seed differs)
        per_dir = Directive(
            engine=directive.engine, positive=directive.positive,
            negatives=directive.negatives, palette_60_30_10=directive.palette_60_30_10,
            runtime=actual_runtime, seed=this_seed, audit=directive.audit,
            config=directive.config, masters=directive.masters,
        )

        # First-pass render — base composition
        base_target = png_path
        if refine and not src_image_path:
            base_target = png_path.with_name(png_path.stem + "-base.png")
        if this_seed in batch_pre_rendered:
            print(cyan(f"  ▶ seed {i+1}/{seeds_n} (seed={this_seed}) → {png_path.name}  (from batch)"))
        else:
            print(cyan(f"  ▶ seed {i+1}/{seeds_n} (seed={this_seed}) → {png_path.name}"))

        if src_image_path:
            # img2img path — engine directive restyles the user's photo.
            # Honor --profile / --draft to match the txt2img path (was using
            # engine runtime steps directly, ignoring both knobs).
            steps_count = int(directive.runtime.get("steps", 32))
            if steps_override is not None:
                steps_count = int(steps_override)
            elif args.draft:
                steps_count = 4    # schnell-fast, even though Kontext uses dev base
            elif args.profile and args.profile in PROFILES:
                steps_count = int(PROFILES[args.profile].get("flux_steps", steps_count))
            if steps_count < 1:
                sys.exit(red("--steps must be >= 1"))
            guidance_val = float(guidance_override if guidance_override is not None
                                 else directive.runtime.get("guidance", 3.5))
            _engine_img2img(
                src_path=src_image_path, prompt=directive.positive, dst_path=base_target,
                strength=from_image_strength, seed=this_seed,
                steps=steps_count, guidance=guidance_val,
            )
        elif this_seed in batch_pre_rendered:
            # Already rendered above in the multi-seed batch call. The file is
            # at base_target with full PNG validation already performed inside
            # flux_generate_batch. Skip the redundant cold-load.
            pass
        else:
            # txt2img path — engine directive generates a fresh image.
            flux_generate(
                synth, "", base_target,
                seed=this_seed,
                steps=steps_override,
                series=None, draft=args.draft, profile=args.profile,
                width=eff_w, height=eff_h, guidance_override=guidance_override,
                quantize=getattr(args, "quantize", None),
            )

        # Second pass — img2img refinement at low denoise (txt2img path only)
        if refine and not src_image_path:
            print(dim(f"    · refining (strength={refine_strength}) via FLUX-dev img2img…"))
            _img2img_refine(
                src_path=base_target, prompt=directive.positive, dst_path=png_path,
                strength=refine_strength, seed=this_seed + 99_991, steps=25,
            )

        sidecar = png_path.with_suffix(png_path.suffix + ".directive.json")
        write_json(sidecar, per_dir.to_dict())
        # Post-render upscale via RealESRGAN — replaces native hi-res / ultra-res
        # with the safe two-stage path: FLUX at base size, then external upscaler.
        upscale_spec = getattr(args, "upscale", None)
        if upscale_spec:
            try:
                factor = int(str(upscale_spec).lower().rstrip("x"))
            except ValueError:
                sys.exit(red(f"--upscale value must look like 2x / 4x / 8x — got {upscale_spec!r}"))
            if factor < 2 or factor > 16:
                sys.exit(red(f"--upscale factor must be between 2 and 16 (got {factor})"))
            model = REALESRGAN_MODEL_FOR_ENGINE.get(engine_name, REALESRGAN_DEFAULT_MODEL)
            upscaled_path = png_path.with_name(png_path.stem + f".x{factor}.png")
            try:
                _upscale_to_factor(png_path, upscaled_path, factor=factor, model=model)
                # Replace the base render with the upscaled one so the gallery + path
                # the user sees is the high-res final. Keep base as .base.png for diff.
                base_kept = png_path.with_name(png_path.stem + ".base.png")
                if base_kept.exists():
                    base_kept.unlink()
                os.replace(png_path, base_kept)
                os.replace(upscaled_path, png_path)
                print(green(f"    ✓ upscaled {factor}× → {png_path}  (base kept at {base_kept.name})"))
            except SystemExit:
                raise
            except Exception as e:
                print(dim(f"    · upscale skipped — {e}"))
        # Auto-generate a transparent-background sibling for T-shirt / sticker /
        # die-cut workflows. Engine prompts force a pure white background, so
        # a luminance-threshold cut-out gives a clean alpha mask.
        if engine_name in _TRANSPARENT_BG_AUTO_ENGINES:
            transparent_path = png_path.with_name(png_path.stem + ".transparent.png")
            try:
                _make_transparent_bg(png_path, transparent_path)
                print(green(f"    ✓ transparent → {transparent_path.name}"))
            except Exception as e:
                print(dim(f"    · transparent-bg skipped — {e}"))
        final_png_info = validate_png(png_path, min_bytes=4096)
        # Gallery auto-capture — every successful engine render writes a row
        # after post-processing so png_bytes and dimensions reflect the final
        # artifact the user will rate.
        try:
            import forge_gallery  # type: ignore
            forge_gallery.capture_directive(
                per_dir, png_path,
                recipe=recipe_id,
                refine=refine, hi_res=getattr(args, "hi_res", False),
                ultra_res=getattr(args, "ultra_res", False),
                guidance_override=guidance_override,
                width=int(final_png_info.get("width") or eff_w or 0),
                height=int(final_png_info.get("height") or eff_h or 0),
                lora_stack=synth.get("flux", {}).get("lora_paths") and [
                    {"path": p, "scale": s} for p, s in zip(
                        synth["flux"].get("lora_paths", []),
                        synth["flux"].get("lora_scales", []),
                    )
                ] or [],
                directive_json=sidecar,
            )
        except Exception as e:
            print(dim(f"  · gallery capture skipped: {e}"))

        # Q1 trust layer — if the engine wrote a *.qc.json next to the PNG,
        # convert failed checks into a blockers.json sibling and tag the
        # variant `publishable`. Engines without auto-QC (today: everything
        # except Madhubani) get publishable=true and no blockers file, which
        # is correct given that we have no machine evidence of failure.
        import engine_qc  # type: ignore
        qc_sidecar = engine_qc.read_qc_sidecar(png_path)
        allow_warnings = bool(getattr(args, "allow_qc_warnings", False))
        blockers_path, blockers = engine_qc.write_blockers_json(png_path, qc_sidecar)
        publishable = engine_qc.is_publishable(blockers, allow_warnings=allow_warnings)
        if blockers:
            tag = gold("warning (override)") if allow_warnings else red("BLOCKED")
            print(f"    {tag}: {engine_qc.summarize(blockers)}")
            if blockers_path:
                print(dim(f"      blockers → {blockers_path.name}"))

        variants.append({
            "seed": this_seed,
            "png_name": png_path.name,
            "png_path": str(png_path),
            "publishable": publishable,
            "blockers": [b["check"] for b in blockers],
            "qc_pass": qc_sidecar.get("auto_qc_pass") if qc_sidecar else None,
        })
        print(green(f"    ✓ {png_path}"))

    # Contact sheet for multi-seed runs
    if seeds_n > 1 and gallery_dir is not None:
        sheet = _write_contact_sheet(gallery_dir, engine=engine_name, subject=subject, variants=variants)
        print(green(f"\n✓ gallery: {gallery_dir}") + dim(f" — {sheet.name} (open to pick)"))

    # Publishability summary across the run
    publishable_count = sum(1 for v in variants if v.get("publishable"))
    blocked_count = len(variants) - publishable_count
    if blocked_count:
        msg = f"  {publishable_count}/{len(variants)} publishable, {blocked_count} blocked by auto-QC"
        if getattr(args, "allow_qc_warnings", False):
            print(gold(msg) + dim(" (--allow-qc-warnings forced publishable=true; review blockers.json)"))
        else:
            print(red(msg) + dim(" — review *.blockers.json next to each PNG"))
    return 0


def cmd_thumbnail(args) -> int:
    # Interactive fallback when required args are missing in a TTY
    preset_id = args.preset or _need("preset", choices=list_preset_ids(), tty=_TTY)
    concept = args.concept or _need("concept (image prompt)", tty=_TTY, default="cinematic outdoor scene")
    headline = args.headline or _need("headline (≤6 words)", tty=_TTY)
    sub = args.sub if args.sub is not None else (input(f"  sub (optional) {cyan('›')} ").strip() if _TTY else None)
    out = args.out or _need("output path", tty=_TTY, default=str(Path.home() / "Pictures" / "thumb.png"))

    preset = load_preset(preset_id)
    series = load_series(args.series) if getattr(args, "series", None) else None
    out_path = Path(out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if args.bg:
        bg_path = Path(args.bg).expanduser().resolve()
    else:
        seed = derive_seed(series, args.frame_offset, fallback=args.seed)
        # Background caching — keyed on every input that affects the FLUX render.
        # When the user iterates on headline / sub text only, we reuse the cached
        # background instead of paying another 3+ min for the same image.
        cache_key_parts = [
            preset_id,
            concept,
            str(seed),
            args.series or "",
            str(args.frame_offset or 0),
            str(args.steps or ""),
            "draft" if args.draft else "",
            getattr(args, "profile", None) or "",
            "|".join(args.lora or []),
            "|".join(map(str, args.lora_scale or [])),
        ]
        cache_key = hashlib.sha256("\0".join(cache_key_parts).encode("utf-8")).hexdigest()[:16]
        cache_dir = FORGE_STATE_HOME / "thumbnail-bg-cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cached_bg = cache_dir / f"{preset_id}-{cache_key}.png"
        if cached_bg.exists() and cached_bg.stat().st_size > 4096:
            bg_path = cached_bg
            print(dim(f"  · bg cache HIT → {cached_bg.name}  (delete to force re-render)"))
        else:
            bg_path = cached_bg
            print(dim(f"  · bg cache MISS — rendering fresh ({cache_key}.png)"))
            flux_generate(
                preset, concept, bg_path,
                seed=seed, steps=args.steps,
                series=series, draft=args.draft, profile=getattr(args, "profile", None),
                lora_paths=list(args.lora) if args.lora else None,
                lora_scales=list(args.lora_scale) if args.lora_scale else None,
            )
    render_thumbnail(preset, bg_path, out_path, headline=headline, sub=sub or None)
    print(green(f"✓ {out_path}"))
    return 0


def cmd_voice(args) -> int:
    preset_id = args.preset or _need("voice preset", choices=list_voice_ids(), tty=_TTY)
    text = args.text or _need("text to speak", tty=_TTY)
    out = args.out or _need("output path", tty=_TTY, default=str(Path.home() / "Sounds" / "vo.aiff"))

    voice = find_voice(preset_id)
    out_path = Path(out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    synthesize_voice(voice, text, out_path)
    translations = translate_generated_audio(voice, text, out_path, _audio_translation_langs(args), label="voice")
    if translations:
        write_json(_translated_path(out_path, "translations", ".json"), {"source_audio": str(out_path), "translations": translations})
    print(green(f"✓ {out_path}"))
    return 0


def cmd_brief(args) -> int:
    topic = args.topic or _need("topic (one sentence describing the video)", tty=_TTY)
    preset_id = args.preset or _need("brand preset", choices=list_preset_ids(), tty=_TTY)
    voice_id = args.voice or _need("voice preset", choices=list_voice_ids(), tty=_TTY)
    default_out = str(Path.home() / "Pictures" / f"forge-brief-{re.sub(r'[^a-z0-9]+', '-', topic.lower())[:30]}")
    out = args.out or _need("output dir", tty=_TTY, default=default_out)

    preset = load_preset(preset_id)
    voice = find_voice(voice_id)
    out_dir = Path(out).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    system = (
        f"You are a YouTube content director. Brand preset: {preset['name']} ({preset['description']}). "
        "Return STRICT JSON: "
        '{"titles":[3 strings ≤60 chars],'
        '"description":"markdown, ends with CTA",'
        '"tags":[8-15 lowercase],'
        '"thumbnail_concepts":[3 objects {"concept":"image prompt without text","headline":"3-6 WORD CAPS","sub":"≤8 words"}],'
        '"voiceover_intro":"2-3 sentences in narrator voice, matches brand"}'
    )
    print(cyan("[1/4] briefing local LLM …"))
    brief = call_llm(system, f"Topic: {topic}\n\nReturn JSON now.")

    meta_dir = out_dir / "metadata"
    meta_dir.mkdir(exist_ok=True)
    write_text(meta_dir / "title.txt", "\n".join(brief.get("titles", [])) + "\n")
    write_text(meta_dir / "description.md", brief.get("description", "") + "\n")
    write_text(meta_dir / "tags.txt", ", ".join(brief.get("tags", [])) + "\n")
    write_text(meta_dir / "voiceover_intro.txt", brief.get("voiceover_intro", "") + "\n")

    print(cyan("[2/4] generating 3 thumbnails …"))
    thumb_dir = out_dir / "thumbnails"
    thumb_dir.mkdir(exist_ok=True)
    series = load_series(args.series) if getattr(args, "series", None) else None
    if series:
        print(dim(f"  · series '{series['id']}' locked — base_seed={series.get('base_seed')} chars={list((series.get('character_sheet') or {}).keys())}"))
    for i, c in enumerate(brief.get("thumbnail_concepts", [])[:3], 1):
        bg = thumb_dir / f"thumb-{i}-bg.png"
        final = thumb_dir / f"thumb-{i}.png"
        # Frame offset = i so each thumb gets a distinct-but-deterministic seed within the series.
        seed = derive_seed(series, i, fallback=i)
        flux_generate(
            preset, c.get("concept", topic), bg,
            seed=seed, steps=args.steps,
            series=series, draft=args.draft, profile=getattr(args, "profile", None),
            lora_paths=list(args.lora) if getattr(args, "lora", None) else None,
            lora_scales=list(args.lora_scale) if getattr(args, "lora_scale", None) else None,
        )
        render_thumbnail(preset, bg, final, headline=c.get("headline", ""), sub=c.get("sub"))
        print(green(f"  ✓ {final.name}"))

    print(cyan("[3/4] synthesizing voiceover intro …"))
    vo_path = out_dir / "voiceover-intro.wav"
    synthesize_voice(voice, brief.get("voiceover_intro", ""), vo_path)
    translations = translate_generated_audio(
        voice, brief.get("voiceover_intro", ""), vo_path, _audio_translation_langs(args), label="voiceover intro"
    )
    print(green(f"  ✓ {vo_path.name}"))

    # Optional: mux thumb-1 + voiceover into a podcast-style mp4
    if getattr(args, "video", False):
        thumb1 = thumb_dir / "thumb-1.png"
        if thumb1.exists() and vo_path.exists():
            print(cyan("[3.5/4] muxing podcast-style video (thumb-1 + voiceover) …"))
            video_out = out_dir / "episode-podcast.mp4"
            make_podcast_video(thumb1, vo_path, video_out, kenburns=True)
            print(green(f"  ✓ {video_out.name}"))
            for item in translations:
                translated_audio = Path(item["audio_path"])
                localized_video = out_dir / f"episode-podcast.{item['lang']}.mp4"
                make_podcast_video(thumb1, translated_audio, localized_video, kenburns=True)
                item["video_path"] = str(localized_video)
                print(green(f"  ✓ {localized_video.name}"))
        else:
            print(red(f"  · skipped video mux — missing thumb-1.png or voiceover-intro.wav"))

    print(cyan("[4/4] writing brief manifest …"))
    write_json(out_dir / "brief.json", {
        "topic": topic,
        "preset": preset["id"],
        "voice": voice["id"],
        "brief": brief,
        "translations": translations,
    })
    print()
    print(green(f"✓ episode kit ready: {out_dir}"))
    return 0


def _episode_source_from_args(args) -> tuple[str, str]:
    if getattr(args, "text", None):
        title = args.title or "Forge Mini Episode"
        return clean_book_text(args.text), title
    if getattr(args, "book", None):
        book = Path(args.book).expanduser().resolve()
        title = args.title or book.stem.replace("-", " ").replace("_", " ").title()
        return read_book_text(book), title
    sys.exit(red("episode needs --book path or --text"))


def cmd_episode(args) -> int:
    """Create a complete four-part mini episode from source text/book input."""
    source, title = _episode_source_from_args(args)
    if len(source) < 20:
        sys.exit(red("source text is too short to adapt into an episode"))

    preset_id = args.preset or _need("brand preset", choices=list_preset_ids(), tty=_TTY)
    voice_id = args.voice or _need("voice preset", choices=list_voice_ids(), tty=_TTY)
    preset = load_preset(preset_id)
    voice = find_voice(voice_id)
    try:
        target_langs = [lang for lang in parse_language_codes(args.translate or "hi,mr") if lang != "en"]
    except ValueError as e:
        sys.exit(red(str(e)))
    langs = ["en", *target_langs]
    segment_count = max(1, int(args.segments))
    target_sec = float(args.seconds)
    if target_sec < 5:
        sys.exit(red("--seconds must be at least 5"))
    shots_per_segment = max(1, int(getattr(args, "shots_per_segment", 4)))
    shot_sec = target_sec / shots_per_segment

    default_out = Path.home() / "Pictures" / f"forge-episode-{_slug(title)}"
    out_dir = Path(args.out).expanduser().resolve() if args.out else default_out.resolve()
    for subdir in ("scripts", "audio/raw", "audio/final", "subtitles", "videos/segments", "videos/final", "thumbnails", "qc"):
        (out_dir / subdir).mkdir(parents=True, exist_ok=True)

    profile = args.profile or (None if args.draft else "balanced")
    print(cyan(f"[1/6] adapting source into {segment_count} timed mini script(s) ..."))
    plan = plan_episode_from_source(source, title=title, preset=preset, segments=segment_count, seconds=target_sec)
    write_json(out_dir / "episode-plan.json", plan)

    segment_videos: dict[str, list[Path]] = {lang: [] for lang in langs}
    segment_audio: dict[str, list[Path]] = {lang: [] for lang in langs}
    shot_videos: dict[str, list[Path]] = {lang: [] for lang in langs}
    qc: dict[str, Any] = {
        "target_seconds": target_sec,
        "shots_per_segment": shots_per_segment,
        "shot_seconds": shot_sec,
        "segments": [],
    }
    visual_images: list[Path] = []

    for idx, segment in enumerate(plan["segments"], 1):
        seg_id = f"segment-{idx:02d}"
        print(cyan(f"[2/6] {seg_id}: {shots_per_segment} shot storyboard + English audio/subtitles ..."))
        script = fit_spoken_text(str(segment.get("script", "")).strip(), target_sec, label=f"{seg_id} English script")
        segment["script"] = script
        write_text(out_dir / "scripts" / f"{seg_id}.en.txt", script + "\n")
        shots = plan_shots_for_segment(
            segment,
            episode_title=str(plan.get("title") or title),
            preset=preset,
            shot_count=shots_per_segment,
            shot_sec=shot_sec,
        )
        segment["shots"] = shots

        seg_qc: dict[str, Any] = {"id": seg_id, "title": segment.get("title"), "shots": []}
        seg_video_chunks: dict[str, list[Path]] = {lang: [] for lang in langs}
        seg_audio_chunks: dict[str, list[Path]] = {lang: [] for lang in langs}

        for shot_idx, shot in enumerate(shots, 1):
            shot_id = f"{seg_id}-shot-{shot_idx:02d}"
            dialog = fit_spoken_text(str(shot.get("dialog", "")).strip(), shot_sec, label=f"{shot_id} English dialog")
            shot["dialog"] = dialog

            raw_audio = out_dir / "audio" / "raw" / f"{shot_id}.en.wav"
            final_audio = out_dir / "audio" / "final" / f"{shot_id}.en.wav"
            tts_plan: dict[str, Any] = {}
            fit: dict[str, Any] = {}
            for attempt in range(2):
                tts_plan = synthesize_voice_for_language(voice, dialog, raw_audio, "en")
                fit = fit_audio_to_duration(raw_audio, final_audio, shot_sec)
                revised = revise_text_for_audio_fit(dialog, shot_sec, fit, label=f"{shot_id} English dialog")
                if attempt == 0 and revised != dialog:
                    dialog = revised
                    shot["dialog"] = dialog
                    continue
                break
            write_text(out_dir / "scripts" / f"{shot_id}.en.txt", dialog + "\n")
            visual_prompt, visual_contract = build_shot_visual_prompt(
                episode_title=str(plan.get("title") or title),
                segment_title=str(segment.get("title") or f"Part {idx}"),
                segment_visual=str(shot.get("visual_context") or segment.get("visual_prompt") or ""),
                dialog=dialog,
                shot_number=shot_idx,
                shot_count=shots_per_segment,
                preset=preset,
            )
            shot["visual_prompt"] = visual_prompt
            shot["visual_contract"] = visual_contract
            image_path = out_dir / "thumbnails" / f"{shot_id}-visual.png"
            thumb_path = out_dir / "thumbnails" / f"{shot_id}.png"
            headline = str(shot.get("thumbnail_headline") or segment.get("title") or f"Shot {shot_idx}")
            if args.no_flux:
                render_title_card(preset, image_path, headline=headline, sub=dialog)
            else:
                flux_generate(
                    preset,
                    str(shot.get("visual_prompt") or segment.get("visual_prompt") or title),
                    image_path,
                    seed=idx * 100 + shot_idx,
                    steps=args.steps,
                    draft=args.draft,
                    profile=profile,
                )
            render_thumbnail(preset, image_path, thumb_path, headline=headline, sub=dialog[:60])
            visual_images.append(image_path)

            shot_qc: dict[str, Any] = {
                "id": shot_id,
                "dialog": dialog,
                "visual": str(image_path),
                "thumbnail": str(thumb_path),
                "visual_prompt": shot.get("visual_prompt"),
                "visual_contract": shot.get("visual_contract"),
                "languages": {},
            }
            srt = out_dir / "subtitles" / f"{shot_id}.en.srt"
            write_srt(srt, timed_subtitle_rows(dialog, shot_sec))
            video = out_dir / "videos" / "segments" / f"{shot_id}.en.mp4"
            make_subtitled_podcast_video(image_path, final_audio, srt, video, target_sec=shot_sec)
            seg_video_chunks["en"].append(video)
            seg_audio_chunks["en"].append(final_audio)
            shot_videos["en"].append(video)
            shot_qc["languages"]["en"] = episode_qc_record(
                lang="en", text=dialog, audio_fit=fit, tts_plan=tts_plan, target_sec=shot_sec
            )

            for lang in target_langs:
                print(cyan(f"[3/6] {shot_id}: Sarvam translation + QC -> {language_name(lang)} ({lang}) ..."))
                translated, passes = translation_qc_twice(dialog, lang)
                translated = ensure_terminal_pause(translated)
                write_text(out_dir / "scripts" / f"{shot_id}.{lang}.txt", translated + "\n")
                raw_lang = out_dir / "audio" / "raw" / f"{shot_id}.{lang}.wav"
                final_lang = out_dir / "audio" / "final" / f"{shot_id}.{lang}.wav"
                lang_tts = synthesize_voice_for_language(voice, translated, raw_lang, lang)
                lang_fit = fit_audio_to_duration(raw_lang, final_lang, shot_sec)
                lang_srt = out_dir / "subtitles" / f"{shot_id}.{lang}.srt"
                write_srt(lang_srt, timed_subtitle_rows(translated, shot_sec))
                lang_video = out_dir / "videos" / "segments" / f"{shot_id}.{lang}.mp4"
                make_subtitled_podcast_video(image_path, final_lang, lang_srt, lang_video, target_sec=shot_sec)
                seg_video_chunks[lang].append(lang_video)
                seg_audio_chunks[lang].append(final_lang)
                shot_videos[lang].append(lang_video)
                shot_qc["languages"][lang] = episode_qc_record(
                    lang=lang,
                    text=translated,
                    audio_fit=lang_fit,
                    tts_plan=lang_tts,
                    target_sec=shot_sec,
                    translation_passes=passes,
                )
            seg_qc["shots"].append(shot_qc)

        for lang in langs:
            seg_video = out_dir / "videos" / "segments" / f"{seg_id}.{lang}.mp4"
            concat_videos(seg_video_chunks[lang], seg_video)
            seg_audio = out_dir / "audio" / "final" / f"{seg_id}.{lang}.wav"
            concat_audio(seg_audio_chunks[lang], seg_audio)
            segment_videos[lang].append(seg_video)
            segment_audio[lang].append(seg_audio)
        qc["segments"].append(seg_qc)

    print(cyan("[4/6] stitching final language videos and audiobooks ..."))
    final_outputs: dict[str, Any] = {}
    for lang in langs:
        final_video = out_dir / "videos" / "final" / f"episode.{lang}.mp4"
        concat_videos(segment_videos[lang], final_video)
        final_audio = out_dir / "audio" / "final" / f"episode.{lang}.wav"
        concat_audio(segment_audio[lang], final_audio)
        final_outputs[lang] = {
            "video": str(final_video),
            "audio": str(final_audio),
            "segments": [str(p) for p in segment_videos[lang]],
            "shots": [str(p) for p in shot_videos[lang]],
        }

    print(cyan("[5/6] rendering main thumbnail ..."))
    thumb = plan.get("thumbnail") or {}
    main_thumb = out_dir / "thumbnail.png"
    if visual_images:
        render_thumbnail(
            preset,
            visual_images[0],
            main_thumb,
            headline=str(thumb.get("headline") or plan.get("title") or title),
            sub=str(thumb.get("sub") or "4-part mini episode"),
        )

    print(cyan("[6/6] writing QC + manifest ..."))
    qc["summary"] = {
        "translation_model": TRANSLATE_MODEL,
        "qc_passes": 2,
        "languages": langs,
        "pronunciation_risks": [
            {"segment": seg["id"], "shot": shot["id"], "lang": lang, "issues": rec["issues"]}
            for seg in qc["segments"]
            for shot in seg.get("shots", [])
            for lang, rec in shot.get("languages", {}).items()
            if rec["issues"]
        ],
    }
    write_json(out_dir / "qc" / "episode-qc.json", qc)
    write_json(out_dir / "episode-plan.json", plan)
    manifest = {
        "schema": "forge.episode.v1",
        "title": plan.get("title") or title,
        "source": {"book": str(Path(args.book).expanduser().resolve()) if getattr(args, "book", None) else None},
        "preset": preset["id"],
        "voice": voice["id"],
        "target_seconds_per_segment": target_sec,
        "shots_per_segment": shots_per_segment,
        "target_seconds_per_shot": shot_sec,
        "segments": plan["segments"],
        "languages": langs,
        "translation_model": TRANSLATE_MODEL,
        "thumbnail": str(main_thumb),
        "outputs": final_outputs,
        "qc": str(out_dir / "qc" / "episode-qc.json"),
    }
    write_json(out_dir / "episode-manifest.json", manifest)
    print()
    print(green(f"✓ complete episode ready: {out_dir}"))
    for lang, outputs in final_outputs.items():
        print(f"  {lang:3s} {outputs['video']}")
    return 0


def chunk_book_for_audio(text: str, *, max_chars: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    chunks: list[str] = []
    buf = ""
    for para in paragraphs or split_sentences(text):
        candidate = f"{buf}\n\n{para}".strip() if buf else para
        if len(candidate) <= max_chars:
            buf = candidate
            continue
        if buf:
            chunks.append(buf)
            buf = ""
        if len(para) <= max_chars:
            buf = para
        else:
            sent_buf = ""
            for sentence in split_sentences(para):
                cand = f"{sent_buf} {sentence}".strip()
                if len(cand) > max_chars and sent_buf:
                    chunks.append(sent_buf)
                    sent_buf = sentence
                else:
                    sent_buf = cand
            if sent_buf:
                chunks.append(sent_buf)
    if buf:
        chunks.append(buf)
    return [ensure_terminal_pause(c) for c in chunks if c.strip()]


def audiobook_qc_record(
    *,
    lang: str,
    text: str,
    duration: float,
    tts_plan: dict[str, Any],
    translation_passes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    words = max(1, len(text.split()))
    words_per_min = words / max(duration / 60.0, 0.01)
    issues = []
    if words_per_min > 210:
        issues.append(f"speech rate high: {words_per_min:.0f} wpm")
    if words_per_min < 80:
        issues.append(f"speech rate low: {words_per_min:.0f} wpm")
    if tts_plan.get("pronunciation_risk"):
        issues.append(str(tts_plan.get("note") or "pronunciation risk"))
    return {
        "lang": lang,
        "duration": duration,
        "words": words,
        "words_per_minute": round(words_per_min, 1),
        "tts": tts_plan,
        "translation_passes": translation_passes or [],
        "issues": issues,
    }


def cmd_audiobook(args) -> int:
    """Create source and translated audiobook audio from a book/text input."""
    source, title = _episode_source_from_args(args)
    preset_voice = args.voice or _need("voice preset", choices=list_voice_ids(), tty=_TTY)
    voice = find_voice(preset_voice)
    try:
        target_langs = [lang for lang in parse_language_codes(args.translate or "hi,mr") if lang != "en"]
    except ValueError as e:
        sys.exit(red(str(e)))
    langs = ["en", *target_langs]
    out_dir = Path(args.out).expanduser().resolve() if args.out else (Path.home() / "Music" / f"forge-audiobook-{_slug(title)}")
    for subdir in ("scripts", "audio/raw", "audio/final", "subtitles", "qc"):
        (out_dir / subdir).mkdir(parents=True, exist_ok=True)

    chunks = chunk_book_for_audio(source, max_chars=max(300, int(args.chunk_chars)))
    if args.max_chunks:
        chunks = chunks[: int(args.max_chunks)]
    if not chunks:
        sys.exit(red("no audiobook chunks could be created from the source"))

    print(cyan(f"[1/4] audiobook chunks: {len(chunks)}"))
    audio_by_lang: dict[str, list[Path]] = {lang: [] for lang in langs}
    qc: dict[str, Any] = {"title": title, "translation_model": TRANSLATE_MODEL, "qc_passes": 2, "chunks": []}

    for idx, chunk in enumerate(chunks, 1):
        chunk_id = f"chapter-{idx:03d}"
        print(cyan(f"[2/4] {chunk_id}: English audio ..."))
        write_text(out_dir / "scripts" / f"{chunk_id}.en.txt", chunk + "\n")
        raw = out_dir / "audio" / "raw" / f"{chunk_id}.en.wav"
        tts_plan = synthesize_voice_for_language(voice, chunk, raw, "en")
        final = out_dir / "audio" / "final" / f"{chunk_id}.en.wav"
        shutil.copy2(raw, final)
        duration = _probe_audio_duration(final)
        write_srt(out_dir / "subtitles" / f"{chunk_id}.en.srt", timed_subtitle_rows(chunk, duration))
        audio_by_lang["en"].append(final)
        chunk_qc: dict[str, Any] = {
            "id": chunk_id,
            "languages": {
                "en": audiobook_qc_record(lang="en", text=chunk, duration=duration, tts_plan=tts_plan)
            },
        }

        for lang in target_langs:
            print(cyan(f"[3/4] {chunk_id}: Sarvam {language_name(lang)} translation + audio ..."))
            translated, passes = translation_qc_twice(chunk, lang)
            translated = ensure_terminal_pause(translated)
            write_text(out_dir / "scripts" / f"{chunk_id}.{lang}.txt", translated + "\n")
            raw_lang = out_dir / "audio" / "raw" / f"{chunk_id}.{lang}.wav"
            lang_tts = synthesize_voice_for_language(voice, translated, raw_lang, lang)
            final_lang = out_dir / "audio" / "final" / f"{chunk_id}.{lang}.wav"
            shutil.copy2(raw_lang, final_lang)
            lang_duration = _probe_audio_duration(final_lang)
            write_srt(out_dir / "subtitles" / f"{chunk_id}.{lang}.srt", timed_subtitle_rows(translated, lang_duration))
            audio_by_lang[lang].append(final_lang)
            chunk_qc["languages"][lang] = audiobook_qc_record(
                lang=lang,
                text=translated,
                duration=lang_duration,
                tts_plan=lang_tts,
                translation_passes=passes,
            )
        qc["chunks"].append(chunk_qc)

    print(cyan("[4/4] stitching audiobook masters ..."))
    outputs: dict[str, Any] = {}
    for lang in langs:
        master = out_dir / "audio" / "final" / f"audiobook.{lang}.wav"
        concat_audio(audio_by_lang[lang], master)
        outputs[lang] = {"audio": str(master), "chunks": [str(p) for p in audio_by_lang[lang]]}
    qc["summary"] = {
        "languages": langs,
        "pronunciation_risks": [
            {"chunk": chunk["id"], "lang": lang, "issues": rec["issues"]}
            for chunk in qc["chunks"]
            for lang, rec in chunk["languages"].items()
            if rec["issues"]
        ],
    }
    write_json(out_dir / "qc" / "audiobook-qc.json", qc)
    write_json(out_dir / "audiobook-manifest.json", {
        "schema": "forge.audiobook.v1",
        "title": title,
        "voice": voice["id"],
        "languages": langs,
        "translation_model": TRANSLATE_MODEL,
        "outputs": outputs,
        "qc": str(out_dir / "qc" / "audiobook-qc.json"),
    })
    print()
    print(green(f"✓ audiobook ready: {out_dir}"))
    for lang, output in outputs.items():
        print(f"  {lang:3s} {output['audio']}")
    return 0


def _build_edit_prompt(preset: dict | None, instruction: str | None) -> str:
    """Compose an edit prompt from optional preset (style) and instruction (action)."""
    parts: list[str] = []
    if preset:
        parts.append(
            f"Transform this image into the following visual style, preserving the original "
            f"subject and composition:\n\n{preset['flux']['positive_prefix']}"
        )
        palette = preset["palette_60_30_10"]
        parts.append(
            f"60-30-10 palette must use these colors only: 60% {palette['dominant']['hex']} "
            f"({palette['dominant']['role']}), 30% {palette['secondary']['hex']} "
            f"({palette['secondary']['role']}), 10% {palette['accent']['hex']} "
            f"({palette['accent']['role']})."
        )
        rules = preset.get("prompt_rules", {}).get("always_add", [])
        if rules:
            parts.append("CONSTRAINTS: " + ", ".join(rules))
    if instruction:
        parts.append(f"EDIT INSTRUCTION: {instruction}")
    if preset:
        parts.append(preset["flux"]["positive_suffix"])
    return "\n\n".join(parts)


def cmd_edit(args) -> int:
    """Create a version of an existing image (style transfer + instruction-following edits)."""
    # Interactive fallback for missing args
    image = args.image or _need("source image (full path)", tty=_TTY)
    src = Path(image).expanduser().resolve()
    if not src.exists():
        sys.exit(red(f"source image not found: {src}"))
    if src.stat().st_size < 1024:
        sys.exit(red(f"source image too small ({src.stat().st_size} bytes): {src}"))

    preset_id = args.preset
    instruction = args.instruction
    if not preset_id and not instruction:
        if _TTY:
            print(dim("  · need a preset (style) and/or an instruction (action)"))
            preset_id = prompt("preset (or 'none' to skip)", choices=list_preset_ids() + ["none"])
            if preset_id == "none":
                preset_id = None
                instruction = _need("edit instruction (e.g., 'swap background to teal lake')", tty=True)
            else:
                add_inst = prompt("optional extra edit instruction (or 'none')", default="none")
                instruction = None if add_inst == "none" else add_inst
        else:
            sys.exit(red("must provide --preset, --instruction, or both"))
    preset = load_preset(preset_id) if preset_id else None
    prompt_text = _build_edit_prompt(preset, instruction)

    out = args.out or _need(
        "output path",
        tty=_TTY,
        default=str(src.parent / f"{src.stem}-edit-{args.seed}.png"),
    )
    out_path = Path(out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Pre-flight model selection: prefer Kontext (instruction-following), fall back to dev (img2img)
    kontext_ready, kontext_reason = _flux_model_ready("kontext-dev")
    dev_ready, dev_reason = _flux_model_ready("dev")

    if kontext_ready:
        mode, model = "kontext", "dev-kontext"
        print(green("  · using FLUX.1-Kontext-dev (true instruction-following)"))
    elif dev_ready:
        mode, model = "img2img", "dev"
        print(dim(f"  · Kontext-dev not ready: {kontext_reason}"))
        print(dim(f"  · falling back to FLUX.1-dev img2img mode (style/structure preserving)"))
        print(dim(f"  · for true instruction edits: hf download black-forest-labs/FLUX.1-Kontext-dev"))
    else:
        sys.exit(red(
            f"Neither Kontext-dev nor FLUX.1-dev is ready.\n"
            f"  kontext-dev: {kontext_reason}\n"
            f"  dev:         {dev_reason}\n"
            f"  Run: hf download black-forest-labs/FLUX.1-dev"
        ))

    # Honor --draft / --profile overrides (was ignoring both, using --steps directly).
    if getattr(args, "draft", False):
        args.steps = 4
    elif getattr(args, "profile", None) in PROFILES:
        args.steps = int(PROFILES[args.profile].get("flux_steps", args.steps))

    if args.steps < 1:
        sys.exit(red("--steps must be >= 1"))

    tmp_out = _register_tmp(_tmp_sibling(out_path))

    # Build mflux command. Newer mflux ships `mflux-generate-kontext`; older ones use `--model dev-kontext`.
    if mode == "kontext" and shutil.which("mflux-generate-kontext"):
        # IMPORTANT: in current mflux, --model takes a CUSTOM CHECKPOINT PATH;
        # the architecture variant is selected via --base-model. Passing `--model dev`
        # makes mflux look for a checkpoint file named "dev", fall back to the wrong
        # defaults, and emit pure latent noise (no denoising applied to the source image).
        cmd = [
            "mflux-generate-kontext",
            *_mflux_runtime_args(),
            "--base-model", "dev",
            "--prompt", prompt_text,
            "--image-path", str(src),
            "--guidance", "2.5",
            "--steps", str(args.steps),
            "--seed", str(args.seed),
            "--output", str(tmp_out),
        ]
    elif mode == "kontext":
        cmd = [
            "mflux-generate",
            *_mflux_runtime_args(),
            "--model", "dev-kontext",
            "--prompt", prompt_text,
            "--init-image-path", str(src),
            "--steps", str(args.steps),
            "--guidance", "3.5",
            "--seed", str(args.seed),
            "--output", str(tmp_out),
        ]
    else:  # img2img on FLUX.1-dev
        cmd = [
            "mflux-generate",
            *_mflux_runtime_args(),
            "--model", "dev",
            "--prompt", prompt_text,
            "--init-image-path", str(src),
            "--init-image-strength", str(max(0.0, min(1.0, 1.0 - args.strength))),  # mflux: higher = preserve original more
            "--steps", str(args.steps),
            "--guidance", "3.5",
            "--seed", str(args.seed),
            "--output", str(tmp_out),
        ]

    print(dim(f"  $ {cmd[0]} --steps {args.steps} --seed {args.seed} (mode={mode}, strength={args.strength})"))
    if args.steps < 25:
        print(dim("  · lower steps reduce sustained Metal/GPU load and heat; quality may drop a bit"))
    try:
        try:
            require_metal_acceleration(label=f"{cmd[0]} edit/{mode}")
        except RuntimeError as e:
            sys.exit(red(str(e)))
        with ResourceLock("metal-heavy") as lock:
            if lock.wait_seconds > 0.1:
                print(dim(f"  · waited {lock.wait_seconds:.1f}s for Metal lock"))
            _preflight_memory(label=f"{cmd[0]} edit/{mode}")
            run_subprocess(
                cmd, check=True, timeout=MFLUX_TIMEOUT_SEC,
                heartbeat_label=f"{cmd[0]} render",
                heartbeat_seconds=MFLUX_HEARTBEAT_SEC,
            )
    except Exception:
        if tmp_out.exists():
            tmp_out.unlink()
        raise

    try:
        validate_png(tmp_out, min_bytes=4096)
    except ValueError as e:
        sys.exit(red(f"edit output validation failed: {e}"))
    os.replace(tmp_out, out_path)
    _discard_tmp(tmp_out)
    print(green(f"✓ {out_path}"))
    return 0


def _download_with_progress(url: str, dest: Path, *, expected_min_bytes: int = 1024 * 1024) -> None:
    """Stream-download a URL to `dest` atomically with a tiny progress meter."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = _register_tmp(_tmp_sibling(dest))
    print(dim(f"  ↓ {url}"))
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            total = int(r.headers.get("Content-Length") or 0)
            written = 0
            last_pct = -1
            with tmp.open("wb") as f:
                while True:
                    block = r.read(1024 * 256)  # 256 KB chunks
                    if not block:
                        break
                    f.write(block)
                    written += len(block)
                    if total > 0:
                        pct = int(written * 100 / total)
                        if pct >= last_pct + 5:
                            print(dim(f"    {pct:3d}%  ({written / 1024 / 1024:.1f} / {total / 1024 / 1024:.1f} MB)"))
                            last_pct = pct
        if tmp.stat().st_size < expected_min_bytes:
            sys.exit(red(f"download too small ({tmp.stat().st_size} bytes), likely failed: {url}"))
        os.replace(tmp, dest)
        _discard_tmp(tmp)
        print(green(f"  ✓ {dest.name} ({dest.stat().st_size / 1024 / 1024:.1f} MB)"))
    except Exception as e:
        if tmp.exists():
            tmp.unlink()
        sys.exit(red(f"download failed: {url}\n  {e}"))


def cmd_series(args) -> int:
    """forge series {list,show,new} — manage consistency-lock files."""
    sub = args.action
    SERIES_DIR.mkdir(parents=True, exist_ok=True)

    if sub == "list":
        ids = list_series_ids()
        print()
        print(bold(f"SERIES  ({len(ids)} defined)"))
        if not ids:
            print(dim("  none yet — run `forge series new <id>` to scaffold one"))
        for sid in ids:
            data = load_series(sid)
            chars = ", ".join((data.get("character_sheet") or {}).keys()) or dim("(no characters)")
            print(f"  {gold(sid):24s} preset={data.get('preset','?'):14s} seed={data.get('base_seed','?')}")
            print(f"  {'':14s}        cast: {chars}")
        print()
        return 0

    if sub == "show":
        if not args.id:
            args.id = prompt("series id", choices=list_series_ids() or ["(none)"])
        print(json.dumps(load_series(args.id), indent=2))
        return 0

    if sub == "new":
        if not args.id:
            args.id = prompt("new series id (kebab-case)", default="my-series")
        path = SERIES_DIR / f"{args.id}.json"
        if path.exists() and not args.force:
            sys.exit(red(f"{path} already exists — use --force to overwrite"))
        preset_id = args.preset or (prompt("which preset locks the look?", choices=list_preset_ids()) if _TTY else "tartakovsky")
        # Deterministic-but-unique seed derived from the id; Python's built-in hash
        # is process-salted, so use a stable digest.
        seed = int(hashlib.sha256(args.id.encode("utf-8")).hexdigest()[:8], 16) % ((1 << 31) - 1)
        scaffold = {
            "id": args.id,
            "preset": preset_id,
            "base_seed": seed,
            "_about": "Edit this file to lock characters/world/style across a batch. See SKILL.md → Consistency.",
            "style_anchor": "<<replace>> ONE SENTENCE describing the universal visual feel of every frame in this series. Repeated verbatim in every prompt.",
            "world_sheet": "<<replace>> 1–2 sentences pinning setting, time of day, atmosphere, mood. Treated as ground-truth for every frame.",
            "character_sheet": {
                "protagonist": "<<replace>> ~30-word locked physical description. Age, build, face, hair, clothing, signature props. Reference with [protagonist] in concepts.",
            },
            "locked_negatives": [
                "different character per frame",
                "style drift",
                "off-model character design",
            ],
        }
        path.write_text(json.dumps(scaffold, indent=2) + "\n")
        print(green(f"✓ scaffolded {path}"))
        print(dim("  Next: edit the file to fill style_anchor, world_sheet, character_sheet."))
        print(dim(f"  Then use it: forge brief --topic '...' --preset {preset_id} --series {args.id}"))
        return 0

    sys.exit(f"unknown action: {sub}")


def cmd_setup_voices(args) -> int:
    if not args.kokoro:
        ready, reason = _kokoro_ready()
        print(bold("Voice engines"))
        if ready:
            print(green("  ✓ Kokoro-TTS — installed and ready (preferred)"))
        else:
            print(dim(f"  · Kokoro-TTS — not ready: {reason}"))
        if shutil.which("say"):
            print(green("  ✓ macOS `say` — available (fallback)"))
        else:
            print(red("  ✗ macOS `say` — missing (you're not on macOS?)"))
        print()
        print(dim("  Default engine: Kokoro when ready, else `say`."))
        print(dim("  Override with env: FORGE_TTS_ENGINE=kokoro|say|auto"))
        print()
        print("Run " + cyan("forge setup-voices --kokoro") + " to install the high-quality neural engine.")
        return 0

    print(bold("Installing Kokoro-TTS"))
    print(dim(f"  Step 1/3: Python packages (kokoro-onnx, soundfile, numpy) → {sys.executable}"))
    try:
        # Use sys.executable -m pip so the install lands in the SAME interpreter that
        # will later import kokoro_onnx. Bare `pip` may resolve to a different Python
        # (Homebrew/pyenv/system mismatch) → install succeeds, import fails.
        run_subprocess(
            [sys.executable, "-m", "pip", "install",
             "kokoro-onnx", "soundfile", "numpy", "--break-system-packages"],
            check=True, timeout=600,
        )
        print(green("  ✓ packages installed"))
    except subprocess.CalledProcessError as e:
        sys.exit(red(f"pip install failed: {e}"))

    onnx_path, voices_path = _kokoro_paths()
    print(dim(f"  Step 2/3: ONNX model → {onnx_path}"))
    if onnx_path.exists() and onnx_path.stat().st_size > 50 * 1024 * 1024:
        print(dim(f"  · already cached ({onnx_path.stat().st_size / 1024 / 1024:.1f} MB)"))
    else:
        _download_with_progress(
            f"{KOKORO_RELEASE_BASE}/{KOKORO_MODEL_FILE}",
            onnx_path,
            expected_min_bytes=50 * 1024 * 1024,
        )

    print(dim(f"  Step 3/3: voice embeddings → {voices_path}"))
    if voices_path.exists() and voices_path.stat().st_size > 5 * 1024 * 1024:
        print(dim(f"  · already cached ({voices_path.stat().st_size / 1024 / 1024:.1f} MB)"))
    else:
        _download_with_progress(
            f"{KOKORO_RELEASE_BASE}/{KOKORO_VOICES_FILE}",
            voices_path,
            expected_min_bytes=5 * 1024 * 1024,
        )

    # Smoke test — load model and synthesize a 1-word sample
    print(dim("  Smoke test: synthesizing 'hello'…"))
    try:
        engine = _kokoro_engine()
        samples, sr = engine.create("hello", voice="af_bella", speed=1.0, lang="en-us")
        if len(samples) < int(sr * 0.1):
            sys.exit(red(f"smoke test produced suspiciously short audio ({len(samples)} samples @ {sr} Hz)"))
        print(green(f"  ✓ smoke test ok ({len(samples)} samples @ {sr} Hz)"))
    except Exception as e:
        sys.exit(red(f"smoke test failed: {e}"))

    print()
    print(green("✓ Kokoro-TTS ready. ") + dim("Forge will now use it automatically; `say` remains as fallback."))
    return 0

# ─────────────── models inventory ───────────────

def _du(path: Path) -> str:
    if not path.exists():
        return "—"
    try:
        return run_subprocess(["du", "-sh", str(path)], capture_output=True, text=True, check=True, timeout=30).stdout.split()[0]
    except Exception:
        return "?"


def cmd_models(args) -> int:
    sub = args.action
    if sub in ("scan", "list", "locations"):
        print()
        # Canonical model homes — top-level summary first so user sees the layout
        # before any per-model detail. The point: one place to look for ANY model.
        print(bold("MODEL HOMES"))
        print(f"  {gold('~/Models/'):<24s}  canonical roof for every model (FLUX / Kokoro / LLMs / etc)")
        print(f"  {gold('brand/loras/'):<24s}  project-local LoRA stacks per engine (Forge-specific, version-controlled)")
        print(f"  {gold('~/.sarvam/key'):<24s}  Sarvam Bulbul API key (cloud TTS for Indic narration)")
        print(f"  {gold('~/.ollama/'):<24s}  Ollama LLM models (qwen3, sarvam-translate, etc — Ollama-managed)")
        print()

        # HF env var state — critical for `hf download` from the user's shell
        shell_hf = os.environ.get("HF_HOME", "")
        forge_hf = str(HF_HOME)
        print(bold("HF_HOME env var"))
        if shell_hf == forge_hf:
            print(f"  {green('✓')} HF_HOME={shell_hf} (matches Forge canonical)")
        elif shell_hf:
            print(f"  {yellow('⚠')} HF_HOME={shell_hf}")
            print(f"  {dim('  Forge expects:')} {forge_hf}")
            print(f"  {dim('  hf download → may land in the wrong place. Update your shell or use --local-dir.')}")
        else:
            print(f"  {red('✗')} HF_HOME is NOT exported in your shell")
            print(f"  {dim('  Forge child processes (mflux, etc) still find models — Forge sets HF_HOME itself.')}")
            print(f"  {dim('  But `hf download` from your shell goes to ~/.cache/huggingface instead of ~/Models.')}")
            print(f"  {dim('  Fix: add to ~/.zshrc:')}")
            print(f"  {gold(f'    export HF_HOME={forge_hf}')}")
            print(f"  {gold(f'    export HF_HUB_CACHE={forge_hf}/hub')}")

        # Per-bucket disk usage
        print()
        print(bold(f"~/Models/  ({_du(MODELS_HOME)} total)"))
        layout = [
            ("ollama",       "GGUF for Ollama"),
            ("huggingface",  "mflux / Whisper / MLX"),
            ("flux-bfl",     "raw BFL FLUX checkpoints"),
            ("kokoro",       "TTS models"),
        ]
        for sub_name, label in layout:
            p = MODELS_HOME / sub_name
            mark = green("✓") if p.exists() and any(p.iterdir()) else dim("·")
            print(f"  {mark} {sub_name:14s} {_du(p):>8s}  {dim(label)}")

        # Project-local LoRAs (in brand/loras/)
        loras_dir = LORAS_DIR
        if loras_dir.exists():
            print()
            print(bold(f"brand/loras/  ({_du(loras_dir)} total)"))
            for sub_dir in sorted(loras_dir.iterdir()):
                if not sub_dir.is_dir():
                    continue
                safetensors = sorted(sub_dir.glob("*.safetensors"), key=lambda p: p.stat().st_size, reverse=True)
                if safetensors:
                    main = safetensors[0]
                    print(f"  {green('✓')} {sub_dir.name:24s} {_du(main):>8s}  {dim(main.name)}")
                else:
                    print(f"  {dim('·')} {sub_dir.name:24s} {dim('empty')}")

        # Stragglers
        stragglers = []
        for d in (Path.home() / "Downloads", Path.home() / "Desktop"):
            for pat in ("*.safetensors", "*.gguf", "*.bin", "*.onnx", "*.pt"):
                for f in d.glob(pat):
                    if f.stat().st_size > 10 * 1024 * 1024:
                        stragglers.append(f)
        if stragglers:
            print()
            print(red(f"⚠ {len(stragglers)} model-shaped file(s) outside ~/Models:"))
            for f in stragglers:
                print(f"  {_du(f):>8s}  {f}")
            print(dim(f"  → tip: forge models adopt <path> --as flux-bfl"))

        if args.full:
            hf_hub = MODELS_HOME / "huggingface" / "hub"
            if hf_hub.exists():
                print()
                print(bold("Hugging Face cache"))
                for e in sorted(hf_hub.glob("models--*")):
                    short = e.name.replace("models--", "").replace("--", "/")
                    print(f"  {_du(e):>8s}  {short}")
            bfl = MODELS_HOME / "flux-bfl"
            if bfl.exists() and any(bfl.iterdir()):
                print()
                print(bold("FLUX BFL checkpoints"))
                for f in sorted(bfl.iterdir()):
                    if f.is_file():
                        print(f"  {_du(f):>8s}  {f.name}")
        else:
            print()
            print(dim("  forge models scan --full   for per-model breakdown"))
        print()
        return 0

    if sub == "clean":
        hf_hub = MODELS_HOME / "huggingface" / "hub"
        if not hf_hub.exists():
            print(dim(f"  no HF cache at {hf_hub} — nothing to clean"))
            return 0
        # Phase 1: partial / lock artifacts (always safe; HF re-creates as needed)
        partial: list[Path] = []
        for pat in ("*.lock", "*.incomplete", "*.tmp"):
            partial.extend(hf_hub.rglob(pat))
        # Phase 2: orphaned blobs (no symlink in any snapshots/ points to them)
        orphans: list[Path] = []
        for model_dir in hf_hub.glob("models--*"):
            blobs_dir = model_dir / "blobs"
            snapshots_dir = model_dir / "snapshots"
            if not blobs_dir.exists():
                continue
            referenced: set[str] = set()
            if snapshots_dir.exists():
                for link in snapshots_dir.rglob("*"):
                    if link.is_symlink():
                        try:
                            target = (link.parent / os.readlink(link)).resolve()
                            referenced.add(target.name)
                        except OSError:
                            continue
            for blob in blobs_dir.iterdir():
                if blob.is_file() and blob.name not in referenced and not blob.name.endswith((".lock", ".incomplete")):
                    orphans.append(blob)

        def _human(n: int) -> str:
            for unit in ("B", "KB", "MB", "GB"):
                if n < 1024:
                    return f"{n:.1f}{unit}"
                n /= 1024
            return f"{n:.1f}TB"

        bytes_partial = sum(p.stat().st_size for p in partial if p.exists())
        bytes_orphans = sum(p.stat().st_size for p in orphans if p.exists())
        print()
        print(bold("HF cache cleanup"))
        print(f"  partial files:   {len(partial):4d}  {_human(bytes_partial):>10s}")
        print(f"  orphaned blobs:  {len(orphans):4d}  {_human(bytes_orphans):>10s}")
        print(f"  TOTAL reclaimable: {_human(bytes_partial + bytes_orphans):>10s}")
        if args.dry_run:
            print()
            print(dim("  --dry-run; nothing removed. Re-run without it to clean."))
            for p in partial[:10]:
                print(dim(f"    would rm  {p}"))
            for p in orphans[:10]:
                print(dim(f"    would rm  {p}"))
            return 0
        if not (partial or orphans):
            print(dim("  nothing to clean."))
            return 0
        if not args.yes and _TTY and not confirm(f"remove {_human(bytes_partial + bytes_orphans)} of partial+orphan files?", default=True):
            print(dim("  aborted."))
            return 0
        removed = 0
        for p in partial + orphans:
            try:
                if p.exists():
                    p.unlink()
                    removed += 1
            except OSError as e:
                print(dim(f"  skip {p}: {e}"))
        print(green(f"  ✓ removed {removed} files, freed {_human(bytes_partial + bytes_orphans)}"))

        # Phase 3: remove whole model repos if requested
        if args.remove:
            for repo in args.remove:
                slug = "models--" + repo.replace("/", "--")
                target = hf_hub / slug
                if not target.exists():
                    print(red(f"  not in cache: {repo} ({target})"))
                    continue
                size = int(run_subprocess(["du", "-sb", str(target)], capture_output=True, text=True, check=True, timeout=30).stdout.split()[0])
                if not args.yes and _TTY and not confirm(f"REMOVE {repo} ({_human(size)})?", default=False):
                    print(dim("  skipped."))
                    continue
                shutil.rmtree(target)
                print(green(f"  ✓ removed {repo} ({_human(size)})"))
        return 0

    if sub == "adopt":
        if not args.path:
            args.path = prompt("file to adopt", default="~/Downloads/something.safetensors")
        src = Path(args.path).expanduser().resolve()
        if not src.exists():
            sys.exit(red(f"not found: {src}"))
        sub_name = args.as_ or prompt("under ~/Models/<which>?", choices=["flux-bfl", "kokoro", "huggingface", "ollama"])
        target_dir = MODELS_HOME / sub_name
        target_dir.mkdir(parents=True, exist_ok=True)
        dst = target_dir / src.name
        if dst.exists() and dst.stat().st_size == src.stat().st_size:
            print(dim(f"  already at {dst} (same size)"))
            if args.delete_source or confirm(f"remove source {src}?", default=True):
                src.unlink()
                print(green("  ✓ removed source"))
            return 0
        if dst.exists():
            sys.exit(red(f"destination exists with different size: {dst}"))
        print(f"  moving {src} → {dst} ({_du(src)})")
        shutil.move(str(src), str(dst))
        print(green("  ✓ adopted"))
        return 0

    sys.exit(f"unknown action: {sub}")


def _print_doctor_report(report: dict, *, verbose: bool = False) -> None:
    print()
    print(bold("Forge Doctor"))
    paths = report["paths"]
    print(f"  forge:     {paths['forge_home']}")
    print(f"  models:    {paths['models_home']}")
    print(f"  HF_HOME:   {paths['hf_home']}")
    print(f"  state:     {paths['state_home']}")
    print()
    print(bold("Tools"))
    for tool in report["tools"]:
        mark = green("OK") if tool["ok"] else red("NO")
        detail = tool.get("path") or tool.get("reason", "")
        print(f"  {mark:2s}  {tool['name']:15s} {dim(str(detail))}")
    if report.get("metal_runtime"):
        metal_runtime = report["metal_runtime"]
        mark = green("OK") if metal_runtime.get("ok") else red("NO")
        reason = metal_runtime.get("reason") or "ready"
        probe = metal_runtime.get("mflux_probe") or {}
        probe_path = probe.get("path") or ""
        print(f"  {mark:2s}  {'mflux-metal':15s} {dim(str(reason))} {dim(str(probe_path))}")
    if report.get("ollama_models"):
        print()
        print(bold("Ollama Models"))
        for model in report["ollama_models"]:
            mark = green("OK") if model["ready"] else red("NO")
            detail = model.get("reason", "")
            print(f"  {mark:2s}  {model['name']:42s} {dim(model['required_for'])}  {dim(detail)}")
    print()
    print(bold("Models"))
    for model in report["models"]:
        mark = green("OK") if model["ready"] else dim("--")
        size_gb = model.get("bytes", 0) / (1 << 30)
        print(f"  {mark:2s}  {model['key']:16s} {size_gb:6.1f} GB  {dim(model['reason'])}")
        if verbose:
            print(f"      {model['path']}")
    if report.get("hardware"):
        print()
        print(bold("Hardware"))
        for key, value in report["hardware"].items():
            if key != "ok":
                print(f"  {key:24s} {value}")
    if report["issues"]:
        print()
        print(red("Issues"))
        for issue in report["issues"]:
            print(f"  - {issue}")
    if report["repairs"]:
        print()
        print(green("Repairs"))
        for repair in report["repairs"]:
            print(f"  - {repair}")
    print()


def cmd_doctor(args) -> int:
    report = runtime_doctor(deep=args.deep, repair=args.repair)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_doctor_report(report, verbose=args.verbose or args.deep)
    return 1 if report["issues"] else 0


def cmd_status(args) -> int:
    store = JobStore()
    print()
    print(bold("Forge Status"))
    print(f"  state: {FORGE_STATE_HOME}")
    print(f"  jobs:  {store.path}")
    print(f"  ready: {PIPELINE_HOME / 'ready.json'}")
    print()
    print(bold("Jobs"))
    summary = store.summary()
    if summary:
        print("  " + "  ".join(f"{k}={v}" for k, v in sorted(summary.items())))
    else:
        print("  no jobs recorded yet")
    for job in store.recent_jobs(limit=args.limit):
        err = f"  {red(job['error'][:120])}" if job.get("error") else ""
        print(f"  #{job['id']:04d} {job['status']:10s} {job['kind']:14s} {job['profile'] or '-':8s} {job['input_path']}{err}")
    print()
    print(bold("Locks"))
    lock_dir = FORGE_STATE_HOME / "locks"
    if lock_dir.exists():
        for lock in sorted(lock_dir.glob("*.lock")):
            text = lock.read_text(errors="ignore").strip()
            print(f"  {lock.stem:16s} {dim(text or 'idle')}")
    else:
        print("  no locks yet")
    print()
    return 0


def cmd_bench(args) -> int:
    """Create a lightweight benchmark/profile record for this Mac."""
    report: dict[str, Any] = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "real": args.real,
        "probes": {},
        "profiles": {
            "cool": {"flux_model": "schnell", "flux_steps": 4, "whisper": "turbo", "metal_concurrency": "FORGE_METAL_SLOTS"},
            "balanced": {"flux_model": "dev", "flux_steps": 18, "whisper": "turbo", "metal_concurrency": "FORGE_METAL_SLOTS"},
            "max": {"flux_model": "dev", "flux_steps": 25, "whisper": "best", "metal_concurrency": "FORGE_METAL_SLOTS"},
            "quality": {"flux_model": "dev", "flux_steps": 36, "whisper": "best", "metal_concurrency": "FORGE_METAL_SLOTS", "quantize": 8},
        },
    }
    for name, executable, cmd in [
        ("ffmpeg", "ffmpeg", ["ffmpeg", "-version"]),
        ("ffprobe", "ffprobe", ["ffprobe", "-version"]),
        ("mflux", "mflux-generate", None),
        ("mlx_whisper", "mlx_whisper", None),
    ]:
        start = time.monotonic()
        try:
            if cmd is None:
                path = shutil.which(executable, path=child_env()["PATH"])
                if not path:
                    raise FileNotFoundError(f"{executable} not on PATH")
                report["probes"][name] = {"ok": True, "seconds": round(time.monotonic() - start, 3), "path": path}
            else:
                run_subprocess(cmd, capture_output=True, timeout=20)
                report["probes"][name] = {"ok": True, "seconds": round(time.monotonic() - start, 3)}
        except Exception as e:
            report["probes"][name] = {"ok": False, "seconds": round(time.monotonic() - start, 3), "error": str(e)}
    if args.real:
        report["note"] = "Real mflux/whisper microbenchmarks are not run automatically yet; profiles stay conservative."
    out = write_json(FORGE_STATE_HOME / "benchmarks" / "latest.json", report)
    print(green(f"✓ benchmark profile written: {out}"))
    for profile, values in report["profiles"].items():
        print(f"  {profile:8s} {values}")
    return 0


def cmd_web(args) -> int:
    from forge_web import run_server

    if getattr(args, "metal_slots", None) is not None:
        os.environ["FORGE_METAL_SLOTS"] = str(max(1, min(16, int(args.metal_slots))))
    run_server(host=args.host, port=args.port, open_browser=not args.no_open)
    return 0

# ─────────────── wizard ───────────────
#
# The wizard exposes every meaningful flag of every command. Each branch builds
# a complete argparse.Namespace by prompting interactively — no flag is left at
# CLI-default. This is the difference between "quick-fire wizard" (old) and
# "full guided fine-tuning interface" (current).

WIZARD_SECTIONS = [
    ("TEXT → IMAGE  (your free-form prompt drives the output)", [
        ("e",  "Branded image — style engine + your prompt",              "engine"),
        ("c",  "Children's coloring book page — engine + your prompt",    "engine-coloring"),
        ("t",  "Thumbnail — preset + your prompt",                        "thumbnail"),
    ]),
    ("PROCEDURAL IMAGE  (knob-driven geometry, no prompt)", [
        ("m",  "Mandala — exact SVG + PNG + QC",                          "mandala"),
        ("k",  "Symmetric children's drawing-book pages",                 "childrens-book"),
    ]),
    ("CONTENT PIPELINES  (structured inputs)", [
        ("1",  "Full episode kit — topic → 3 thumbs + intro",             "brief"),
        ("2",  "Multilingual ASMR audiobook — RTF + loop video",          "audiobook"),
        ("3",  "Voiceover — text → wav (Kokoro or say)",                  "voice"),
        ("4",  "Edit / restyle an existing image",                        "edit"),
        ("5",  "Mux thumbnail + audio → mp4",                             "video"),
    ]),
    ("BROWSE", [
        ("6",  "List all presets and voices",                             "list"),
        ("7",  "Show one preset's full spec",                             "show"),
        ("8",  "List all consistency-lock series",                        "series-list"),
    ]),
    ("CONFIGURE", [
        ("9",  "Create a new series (consistency lock)",                  "series-new"),
        ("10", "Install/upgrade voice engine (Kokoro)",                   "setup-voices"),
        ("11", "Inventory local models (~/Models/)",                      "models-scan"),
        ("12", "Adopt a model file into ~/Models/",                       "models-adopt"),
        ("13", "Reclaim disk (clean HF cache)",                           "models-clean"),
    ]),
    ("SYSTEM", [
        ("14", "Runtime health check (doctor)",                           "doctor"),
        ("15", "Recent jobs & resource locks (status)",                   "status"),
        ("16", "Write hardware quality profiles (bench)",                 "bench"),
    ]),
]

# Flat list for the legacy code-paths (choices lookup, dispatch).
WIZARD_CHOICES = [(k, lbl, act) for _section, rows in WIZARD_SECTIONS for k, lbl, act in rows]
WIZARD_CHOICES.append(("q", "Quit", "quit"))


def _w_prompt_optional(label: str, choices: list[str], default_none_label: str = "(none)") -> str | None:
    """Prompt for one of `choices` or 'none'. Returns choice or None.

    Empty input (Enter) maps to the none sentinel — the most common intent for
    optional pickers like 'series (or none)'.
    """
    if not choices:
        return None
    pick = prompt(label, choices=choices + [default_none_label], default=default_none_label)
    return None if pick == default_none_label else pick


def _w_prompt_profile() -> tuple[bool, str | None]:
    """Returns (draft, profile). draft=True for cool, else profile name, or (False, None) for preset default.

    UI: show each profile on its own line with its annotation, then prompt for the
    bare key. Prefix matching means `m` selects max, `c` selects cool, etc. Empty
    Enter selects `balanced` — the recommended production profile per README.
    """
    print(bold("\n  speed profile:"))
    print(f"    {gold('default')}    use the preset's own defaults")
    print(f"    {gold('cool')}       draft mode — schnell @ 4 steps (fastest, coolest)")
    print(f"    {gold('balanced')}   dev @ 18 steps   {dim('(recommended)')}")
    print(f"    {gold('max')}        dev @ 25 steps   {dim('(slowest, hottest, final-quality)')}")
    pick = prompt("pick", choices=["default", "cool", "balanced", "max"], default="balanced")
    if pick == "cool":     return (True, None)
    if pick == "balanced": return (False, "balanced")
    if pick == "max":      return (False, "max")
    return (False, None)


def _w_prompt_lora() -> tuple[list[str] | None, list[float] | None]:
    """Pick LoRA(s) from brand/loras/. Returns (paths, scales) or (None, None)."""
    if not LORAS_DIR.exists():
        return None, None
    available = sorted(p.name for p in LORAS_DIR.glob("*.safetensors"))
    if not available:
        return None, None
    print(dim(f"  · {len(available)} LoRA(s) in brand/loras/: {', '.join(available)}"))
    if not confirm("apply a LoRA?", default=False):
        return None, None
    pick = prompt("which LoRA", choices=available)
    scale_raw = prompt("scale (0.5–1.0 typical)", default="0.8")
    try:
        scale = float(scale_raw)
    except ValueError:
        print(red("  · not a number, using 0.8"))
        scale = 0.8
    return [pick], [scale]


def _w_prompt_int(label: str, default: int) -> int:
    raw = prompt(label, default=str(default))
    try:
        return int(raw)
    except ValueError:
        print(red(f"  · not an int, using {default}"))
        return default


def _w_prompt_float(label: str, default: float) -> float:
    raw = prompt(label, default=str(default))
    try:
        return float(raw)
    except ValueError:
        print(red(f"  · not a float, using {default}"))
        return default


def _wizard_brief() -> None:
    """Prompt for every flag of `forge brief`, then run it."""
    print(bold("\n— brief: full episode kit —"))
    topic = prompt("topic (one sentence describing the video)")
    preset = prompt("brand preset", choices=list_preset_ids())
    voice = prompt("voice preset", choices=list_voice_ids())
    series = _w_prompt_optional("series (locks style/world/characters)", list_series_ids())
    draft, profile = _w_prompt_profile()
    lora, lora_scale = _w_prompt_lora()
    video = confirm("also mux thumb-1 + voiceover into episode-podcast.mp4?", default=True)
    translate = prompt(
        "translate voiceover to (comma codes, blank for none)",
        default=os.environ.get(AUDIO_TRANSLATE_ENV, ""),
    )
    out = prompt("output dir", default=str(Path.home() / "Pictures" / f"forge-brief-{re.sub(r'[^a-z0-9]+', '-', topic.lower())[:30]}"))
    cmd_brief(argparse.Namespace(
        topic=topic, preset=preset, voice=voice, series=series,
        draft=draft, profile=profile, steps=None,
        lora=lora, lora_scale=lora_scale, video=video,
        translate=translate or None, out=out,
    ))


def _wizard_engine_render() -> None:
    """Drive the style engines (noir / wildlife / impressionist / indian / coloring book)
    from a free-form prompt OR a curated recipe."""
    import style_engines  # type: ignore
    print(bold("\n— text → branded image (style engine) —"))
    print(dim("  Each engine is a domain expert (cinematography / wildlife / impressionist /"))
    print(dim("  indian-classical / childrens-coloring-book). Pick a recipe OR write a free-form prompt."))

    engines = style_engines.list_engines()
    engine_name = prompt("engine", choices=engines)

    library = _load_prompt_library()
    eng_recipes = [rid for rid, r in library.items() if r.get("engine") == engine_name]
    if eng_recipes:
        print()
        print(dim(f"  curated recipes for {engine_name}:"))
        for rid in eng_recipes:
            desc = library[rid].get("description", "")[:90]
            print(f"    {gold(rid):<42s} {dim(desc)}")
        print()
    recipe_raw = prompt(
        "recipe id from above, or press Enter to write a free-form prompt instead",
        default="",
    )
    recipe = recipe_raw or None
    if recipe and recipe not in library:
        matches = [r for r in eng_recipes if r.startswith(recipe)]
        if len(matches) == 1:
            recipe = matches[0]
        elif len(matches) > 1:
            print(red(f"  · '{recipe_raw}' is ambiguous: {', '.join(matches)} — using free-form prompt instead"))
            recipe = None
        else:
            print(red(f"  · unknown recipe '{recipe_raw}' — using free-form prompt instead"))
            recipe = None

    subject = None
    if not recipe:
        subject = prompt("prompt — describe what you want drawn (FREE-FORM)")

    seeds = _w_prompt_int("variants (1 = single image, 4 = best-of-4 with contact sheet)", 1)
    refine = confirm("two-pass refinement for micro-detail (+30s per image)?", default=False)
    hi_res = confirm("hi-res 1920×1080 (~2× compute, finer detail)?", default=False)
    seed_default = int((library.get(recipe, {}).get("seed") if recipe else None) or 1)
    seed = _w_prompt_int("seed", seed_default)

    out_raw = prompt(
        "output path (blank → ~/Desktop/forge-test/engine-renders/<engine>/<slug>.png)",
        default="",
    )
    out = out_raw or None

    cmd_engine_render(argparse.Namespace(
        name=engine_name, recipe=recipe, subject=subject,
        config=None, extra_negatives=None,
        seeds=seeds, refine=refine, refine_strength=0.25,
        hi_res=hi_res, ultra_res=False, width=None, height=None, guidance=None,
        seed=seed, out=out, draft=False, profile=None,
    ))


def _wizard_thumbnail() -> None:
    print(bold("\n— text → thumbnail (preset + your prompt) —"))
    print(dim("  Describe what you want drawn in your own words. The preset"))
    print(dim("  supplies the brand look (palette + typography + style hint)."))
    preset = prompt("preset (style lock)", choices=list_preset_ids())
    series = _w_prompt_optional("series (or none)", list_series_ids())
    cast_hint = dim("  (use [name] for series cast — e.g. '[keeper] at the harbor wall')") if series else ""
    if cast_hint:
        print(cast_hint)
    concept = prompt("prompt — describe what you want drawn (FREE-FORM)")
    headline = prompt("headline (≤6 words, CAPS will be applied)")
    sub_raw = prompt("sub (optional, blank to skip)", default="")
    sub = sub_raw if sub_raw else None
    bg_raw = prompt("existing background image path (blank to generate)", default="")
    bg = bg_raw if bg_raw else None
    if bg is None:
        draft, profile = _w_prompt_profile()
        if series:
            frame_offset = _w_prompt_int("frame offset within series (each is unique)", 0)
            seed = 1  # ignored when series is set
        else:
            frame_offset = 0
            seed = _w_prompt_int("seed", 1)
        lora, lora_scale = _w_prompt_lora()
    else:
        draft, profile, frame_offset, seed, lora, lora_scale = False, None, 0, 1, None, None
    out = prompt("output path", default=str(Path.home() / "Pictures" / "thumb.png"))
    cmd_thumbnail(argparse.Namespace(
        preset=preset, concept=concept, headline=headline, sub=sub, bg=bg,
        seed=seed, series=series, frame_offset=frame_offset,
        draft=draft, profile=profile, steps=None,
        lora=lora, lora_scale=lora_scale, out=out,
    ))


def _wizard_edit() -> None:
    print(bold("\n— edit (restyle / instruction edit) —"))
    image = prompt("source image path")
    mode = prompt("mode", choices=["preset only", "instruction only", "both"])
    preset = prompt("preset (style)", choices=list_preset_ids()) if mode != "instruction only" else None
    instruction = prompt("edit instruction (e.g. 'swap bg to teal lake')") if mode != "preset only" else None
    strength = _w_prompt_float("strength (0.3=minor, 0.6=moderate, 0.9=major)", 0.6)
    steps = _w_prompt_int("FLUX steps (25 default, lower=cooler/faster)", 25)
    seed = _w_prompt_int("seed", 1)
    out = prompt("output path", default=str(Path(image).expanduser().with_stem(Path(image).stem + "-edit")))
    cmd_edit(argparse.Namespace(
        image=image, preset=preset, instruction=instruction,
        strength=strength, steps=steps, seed=seed, out=out,
    ))


def _wizard_voice() -> None:
    print(bold("\n— voice —"))
    # Surface which engine will run
    engine = _selected_tts_engine()
    if engine == "kokoro":
        print(green("  · using Kokoro-TTS (neural)"))
    else:
        print(dim("  · using macOS `say` (run option 10 to upgrade to Kokoro)"))
    preset = prompt("voice preset", choices=list_voice_ids())
    text = prompt("text to speak")
    translate = prompt(
        "translate to (comma codes, blank for none)",
        default=os.environ.get(AUDIO_TRANSLATE_ENV, ""),
    )
    out = prompt("output path", default=str(Path.home() / "Sounds" / "vo.wav"))
    cmd_voice(argparse.Namespace(preset=preset, text=text, translate=translate or None, out=out))


def _wizard_audiobook() -> None:
    """Build a multilingual ASMR audiobook from an RTF/text source."""
    print(bold("\n— audiobook (multilingual ASMR) —"))
    print(dim("  Parses RTF/text → translates → narrates per language → ASMR DSP master → muxes onto looped video."))

    print(bold("\n  input layout:"))
    print(f"    {gold('folder')}    pick a folder with the transcript; outputs land in <folder>/output/   {dim('(recommended)')}")
    print(f"    {gold('files')}     pick transcript + output dir paths separately")
    layout = prompt("pick", choices=["folder", "files"], default="folder")

    folder_arg = None
    rtf = None
    out_dir = None

    def _existing_file(label: str) -> str:
        while True:
            p = prompt(label)
            path = Path(p).expanduser().resolve()
            if path.is_file():
                return str(path)
            print(red(f"  · file not found: {path}"))

    if layout == "folder":
        def _existing_dir(label: str) -> str:
            while True:
                p = prompt(label)
                path = Path(p).expanduser().resolve()
                if path.is_dir():
                    return str(path)
                print(red(f"  · directory not found: {path}"))
        folder_arg = _existing_dir("folder containing the transcript")
    else:
        rtf = _existing_file("source RTF/text path")
        default_out = str(Path.home() / "Pictures" / f"forge-audiobook-{Path(rtf).stem}")
        out_dir = prompt("output directory (will be created if missing)", default=default_out)

    # Video path is ALWAYS its own prompt — never required to sit in the folder.
    # If the folder happens to contain a video, the wizard offers it as the default;
    # otherwise the user just types/pastes an absolute path.
    video_default = ""
    if folder_arg is not None:
        for ext in (".mp4", ".mov", ".m4v", ".webm"):
            cands = sorted(Path(folder_arg).glob(f"*{ext}"))
            if cands:
                video_default = str(cands[0])
                break
    if video_default:
        v_label = f"base video path [Enter for folder pick: {Path(video_default).name}]"
        video_raw = prompt(v_label, default=video_default)
    else:
        video_raw = prompt("base video path (any video, anywhere on disk)")
    while not Path(video_raw).expanduser().is_file():
        print(red(f"  · video not found: {Path(video_raw).expanduser()}"))
        video_raw = prompt("base video path")
    video = str(Path(video_raw).expanduser().resolve())

    langs = prompt("languages (comma codes; en uses Kokoro, hi/mr use Parler)", default="en,hi,mr")

    print(bold("\n  voice mode:"))
    print(f"    {gold('normal')}    human-like, real-time speed, light EQ + gentle compression   {dim('(recommended for natural narration)')}")
    print(f"    {gold('asmr')}      slowed 12%, slightly lower pitch, tight LP, more processed feel")
    mode = prompt("pick", choices=["normal", "asmr"], default="normal")

    print(bold("\n  ambient bed:"))
    print(f"    {gold('none')}            no bed — voice only")
    print(f"    {gold('radio-static')}    shortwave-style hiss with subtle tape warble (above voice band)")
    print(f"    {gold('vinyl-crackle')}   warm high-freq vinyl-record texture w/ subtle needle tremolo   {dim('(recommended)')}")
    print(f"    {gold('warm-hum')}        low-end tube amp hum (below voice fundamentals)")
    bed_default = "vinyl-crackle" if mode == "asmr" else "none"
    bed = prompt("pick", choices=["none", "radio-static", "vinyl-crackle", "warm-hum"], default=bed_default)

    print(bold("\n  scope:"))
    print(f"    {gold('batches')}    walk the whole book in N-page batches → one ~1-min video per batch per lang   {dim('(recommended)')}")
    print(f"    {gold('excerpt')}    one short excerpt from the head of the book")
    scope = prompt("pick", choices=["batches", "excerpt"], default="batches")

    extra_args: list[str] = []
    if scope == "batches":
        batch_pages = _w_prompt_int("pages per batch", 10)
        page_words = _w_prompt_int("words per page (250 = standard novel)", 250)
        spoken = _w_prompt_int("spoken words per batch (≈1 min ASMR ≈ 150)", 150)
        extra_args = [
            "--batch-pages", str(batch_pages),
            "--page-words", str(page_words),
            "--spoken-words", str(spoken),
        ]
        batches_filter = prompt(
            "specific batches to run (e.g. '1' or '1,3,5'; blank = all)",
            default="",
        )
        if batches_filter:
            extra_args += ["--batches", batches_filter]
    else:
        max_words = _w_prompt_int("max words to speak (≈150 = 1 min ASMR)", 150)
        extra_args = ["--max-words", str(max_words)]

    pause_default_sent = 400 if mode == "asmr" else 200
    pause_default_para = 900 if mode == "asmr" else 500
    sent_pause = _w_prompt_int(f"inter-sentence pause (ms) — breath between sentences", pause_default_sent)
    para_pause = _w_prompt_int(f"inter-paragraph pause (ms) — bigger beat", pause_default_para)

    print(bold("\n  subtitles:"))
    print(f"    {gold('srt')}    .srt sidecar per language (YouTube auto-picks)   {dim('(recommended)')}")
    print(f"    {gold('vtt')}    .vtt sidecar (modern web standard)")
    print(f"    {gold('none')}   skip subtitles")
    subs = prompt("pick", choices=["srt", "vtt", "none"], default="srt")

    print(bold("\n  thumbnails (frame from your video + localized title overlay per language):"))
    do_thumb = confirm("generate thumbnails?", default=True)
    thumb_preset = "documentary"
    thumb_seed = 42
    thumb_frame_at = None
    if do_thumb:
        print(dim("  preset = typography + palette overlay (background = your actual video frame)"))
        print(dim("  'thumbnail-bold' is tuned for video-frame overlays (big white headline + dim band)"))
        thumb_preset = prompt("  thumbnail preset", choices=list_preset_ids(), default="thumbnail-bold")
        custom_frame = confirm("  pick a specific frame time (default = video midpoint)?", default=False)
        if custom_frame:
            thumb_frame_at = _w_prompt_float("  grab frame at second N (e.g. 12.5)", 0.0)

    audiobook_py = HERE / "audiobook.py"
    cmd: list[str] = [str(audiobook_py)]
    if folder_arg is not None:
        cmd += ["--folder", folder_arg, "--video", video]
    else:
        cmd += ["--rtf", rtf, "--video", video, "--out-dir", out_dir]
    cmd += [
        "--langs", langs,
        "--mode", mode,
        "--bed", bed,
        "--sent-pause-ms", str(sent_pause),
        "--para-pause-ms", str(para_pause),
        "--subtitles", subs,
    ]
    if do_thumb:
        cmd += ["--thumbnail", "--thumb-preset", thumb_preset, "--thumb-seed", str(thumb_seed)]
        if thumb_frame_at is not None:
            cmd += ["--thumb-frame-at", str(thumb_frame_at)]
    else:
        cmd += ["--no-thumbnail"]
    cmd += extra_args
    print(dim(f"  $ {_cmd_display(cmd)}"))
    rc = subprocess.call(cmd, env=child_env())
    if rc != 0:
        print(red(f"  · audiobook exited {rc}"))
    else:
        if folder_arg is not None:
            out_final = Path(folder_arg).expanduser() / "output" / "final"
        else:
            out_final = Path(out_dir).expanduser() / "final"
        print(green(f"  ✓ done. Final videos under: {out_final}"))


def _wizard_mandala() -> None:
    print(bold("\n— mandala (procedural geometry — no FLUX) —"))
    print(dim("  Pure math: symmetry × rings × style → exact SVG + PNG. No prompt drives the"))
    print(dim("  geometry, but you can tag it with a title for the filename + QC sidecar."))
    print(dim("  For a FLUX-driven mandala, see option 'e' (style engine — once mandala-engine ships)."))
    title_raw = prompt("title / concept tag (blank to skip; used in filename + metadata)", default="")
    style = prompt("geometry style", choices=sorted(MANDALA_STYLES), default="coloring")
    symmetry = _w_prompt_int("symmetry order (4 / 6 / 8 / 12 / 16)", 12)
    rings = _w_prompt_int("rings (3-9 typical)", 7)
    complexity = prompt("complexity", choices=list(COMPLEXITY_LEVELS), default="max")
    seed = _w_prompt_int("seed", 1)
    palette = prompt("palette", choices=["ink", "soft", "royal"], default="ink")
    size = _w_prompt_int("square size px", 2400)
    title_slug = _slugify(title_raw) if title_raw else ""
    default_name = (f"mandala-{title_slug}-{style}-{symmetry}fold-seed{seed}.png" if title_slug
                    else f"mandala-{style}-{symmetry}fold-seed{seed}.png")
    out = prompt(
        "output PNG",
        default=str(Path.home() / "Pictures" / "forge-mandalas" / default_name),
    )
    cmd_mandala(argparse.Namespace(
        style=style, symmetry=symmetry, rings=rings, complexity=complexity, seed=seed,
        width=size, height=size, stroke_width=3.0, palette=palette, supersample=2,
        no_mirror=False, out=out,
    ))


def _wizard_childrens_book() -> None:
    print(bold("\n— childrens-book (procedural symmetric pages — no FLUX) —"))
    print(dim("  Pure math: theme × symmetry × rings → exact SVG + PNG drawing-book pages."))
    print(dim("  For a FLUX-driven coloring book with character + scene + emotion + age-range,"))
    print(dim("  use option 'e' (style engine) and pick engine = childrens-coloring-book."))
    title_raw = prompt("title / concept tag (blank to skip; used in folder name + metadata)", default="")
    theme = prompt("theme", choices=["all", *CHILD_THEMES], default="all")
    pages = _w_prompt_int("pages", 3)
    symmetry = _w_prompt_int("border symmetry order", 12)
    rings = _w_prompt_int("border rings", 7)
    complexity = prompt("complexity", choices=list(COMPLEXITY_LEVELS), default="max")
    seed = _w_prompt_int("seed", 101)
    palette = prompt("palette", choices=["ink", "soft", "royal"], default="ink")
    size = _w_prompt_int("square size px", 2400)
    title_slug = _slugify(title_raw) if title_raw else ""
    folder_name = f"forge-childrens-book-{title_slug}-{theme}" if title_slug else f"forge-childrens-book-{theme}"
    out = prompt("output folder", default=str(Path.home() / "Pictures" / folder_name))
    cmd_childrens_book(argparse.Namespace(
        theme=theme, pages=pages, symmetry=symmetry, rings=rings, complexity=complexity,
        seed=seed, width=size, height=size, palette=palette, supersample=2, out=out,
    ))


def _wizard_video() -> None:
    print(bold("\n— video (image + audio → mp4) —"))
    image = prompt("image path (thumbnail/poster)")
    audio = prompt("audio path (voiceover)")
    kenburns = confirm("apply Ken-Burns zoom/pan?", default=True)
    zoom_max = _w_prompt_float("max zoom (1.0=none, 1.15=subtle, 1.3=strong)", 1.15) if kenburns else 1.0
    fade_out = _w_prompt_float("fade-out seconds at the end", 1.0)
    out = prompt("output mp4 path", default=str(Path(audio).expanduser().with_suffix(".mp4")))
    cmd_video(argparse.Namespace(
        image=image, audio=audio, no_kenburns=not kenburns,
        zoom_max=zoom_max, fade_out=fade_out, out=out,
    ))


def _wizard_series_new() -> None:
    print(bold("\n— series new —"))
    series_id = prompt("series id (kebab-case, e.g. harbor-tales)")
    preset = prompt("preset that locks the look", choices=list_preset_ids())
    force = False
    if (SERIES_DIR / f"{series_id}.json").exists():
        force = confirm("file exists — overwrite?", default=False)
        if not force:
            print(dim("  · aborted"))
            return
    cmd_series(argparse.Namespace(action="new", id=series_id, preset=preset, force=force))


def _wizard_setup_voices() -> None:
    print(bold("\n— setup-voices —"))
    do_install = confirm("install/refresh Kokoro-TTS (~80 MB one-time download)?", default=True)
    cmd_setup_voices(argparse.Namespace(kokoro=do_install))


def _wizard_models_scan() -> None:
    print(bold("\n— models scan —"))
    full = confirm("include per-model breakdown (slower)?", default=False)
    cmd_models(argparse.Namespace(action="scan", full=full, path=None, as_=None,
                                  delete_source=False, dry_run=False, yes=False, remove=None))


def _wizard_models_adopt() -> None:
    print(bold("\n— models adopt —"))
    path = prompt("file to adopt", default=str(Path.home() / "Downloads"))
    as_ = prompt("under ~/Models/<which>?", choices=["flux-bfl", "kokoro", "huggingface", "ollama"])
    delete = confirm("remove source after copying?", default=False)
    cmd_models(argparse.Namespace(action="adopt", path=path, as_=as_,
                                  delete_source=delete, full=False, dry_run=False, yes=False, remove=None))


def _wizard_models_clean() -> None:
    print(bold("\n— models clean —"))
    dry = confirm("dry-run (preview only)?", default=True)
    remove_raw = prompt("repo to remove entirely (e.g. 'org/repo', blank to skip)", default="")
    remove = [remove_raw] if remove_raw else None
    yes = False if dry else confirm("skip per-file confirmations?", default=False)
    cmd_models(argparse.Namespace(action="clean", full=False, path=None, as_=None,
                                  delete_source=False, dry_run=dry, yes=yes, remove=remove))


def _wizard_doctor() -> None:
    print(bold("\n— doctor —"))
    deep = confirm("deep check (hardware + per-model details)?", default=True)
    repair = confirm("attempt repairs (create dirs, add env exports)?", default=False)
    cmd_doctor(argparse.Namespace(deep=deep, repair=repair, json=False, verbose=False))


def _wizard_engine_coloring_shortcut() -> None:
    """Shortcut for the children's coloring book engine — pre-selects the engine,
    then routes to the same recipe-or-prompt picker as _wizard_engine_render."""
    import style_engines  # type: ignore
    print(bold("\n— text → children's coloring book page (style engine) —"))
    print(dim("  Engine pre-selected: childrens-coloring-book."))
    print(dim("  Pick a recipe (Mo Willems / Boynton / Carle / Potter / Miyazaki style)"))
    print(dim("  OR write your own free-form prompt for the scene."))

    library = _load_prompt_library()
    engine_name = "childrens-coloring-book"
    eng_recipes = [rid for rid, r in library.items() if r.get("engine") == engine_name]
    if eng_recipes:
        print()
        print(dim("  curated recipes:"))
        for rid in eng_recipes:
            desc = library[rid].get("description", "")[:90]
            print(f"    {gold(rid):<42s} {dim(desc)}")
        print()
    recipe_raw = prompt(
        "recipe id from above, or press Enter to write a free-form prompt",
        default="",
    )
    recipe = recipe_raw or None
    if recipe and recipe not in library:
        matches = [r for r in eng_recipes if r.startswith(recipe)]
        if len(matches) == 1:
            recipe = matches[0]
        elif len(matches) > 1:
            print(red(f"  · '{recipe_raw}' is ambiguous: {', '.join(matches)} — using free-form prompt instead"))
            recipe = None
        else:
            print(red(f"  · unknown recipe '{recipe_raw}' — using free-form prompt instead"))
            recipe = None

    subject = None
    if not recipe:
        subject = prompt("prompt — describe the scene/character (FREE-FORM)")

    seeds = _w_prompt_int("variants (1 = single image, 4 = best-of-4 with contact sheet)", 1)
    seed_default = int((library.get(recipe, {}).get("seed") if recipe else None) or 1)
    seed = _w_prompt_int("seed", seed_default)
    out_raw = prompt(
        "output path (blank → ~/Desktop/forge-test/engine-renders/<engine>/<slug>.png)",
        default="",
    )

    cmd_engine_render(argparse.Namespace(
        name=engine_name, recipe=recipe, subject=subject,
        config=None, extra_negatives=None,
        seeds=seeds, refine=False, refine_strength=0.25,
        hi_res=False, ultra_res=False, width=None, height=None, guidance=None,
        seed=seed, out=(out_raw or None), draft=False, profile=None,
    ))


# ─────────────── WhatsApp joke factory ───────────────

def cmd_jokes_generate(args) -> int:
    """Bridge to whatsapp_joke_factory.py"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("whatsapp_joke_factory", HERE / "whatsapp_joke_factory.py")
    factory = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(factory)
    return factory.cmd_generate(args)


def cmd_jokes_qa(args) -> int:
    """Bridge to whatsapp_joke_factory.py"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("whatsapp_joke_factory", HERE / "whatsapp_joke_factory.py")
    factory = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(factory)
    return factory.cmd_qa(args)


def cmd_jokes_render(args) -> int:
    """Bridge to whatsapp_joke_factory.py"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("whatsapp_joke_factory", HERE / "whatsapp_joke_factory.py")
    factory = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(factory)
    return factory.cmd_render(args)


def cmd_wizard(_args) -> int:
    print_menu(short=False)
    while True:
        print(bold("\nWhat do you want to make?"))
        for section_title, rows in WIZARD_SECTIONS:
            print(dim(f"  {section_title}"))
            for k, lbl, _act in rows:
                print(f"    {gold(k):>3s}  {lbl}")
        print(f"    {gold('q'):>3s}  Quit")
        choice = prompt("pick", choices=[k for k, _, _ in WIZARD_CHOICES])
        action = dict((k, a) for k, _, a in WIZARD_CHOICES)[choice]
        try:
            if action == "quit":             return 0
            elif action == "engine":         _wizard_engine_render()
            elif action == "engine-coloring": _wizard_engine_coloring_shortcut()
            elif action == "brief":          _wizard_brief()
            elif action == "thumbnail":      _wizard_thumbnail()
            elif action == "edit":           _wizard_edit()
            elif action == "voice":          _wizard_voice()
            elif action == "video":          _wizard_video()
            elif action == "audiobook":      _wizard_audiobook()
            elif action == "mandala":        _wizard_mandala()
            elif action == "childrens-book": _wizard_childrens_book()
            elif action == "list":           cmd_list(None)
            elif action == "show":           cmd_show(argparse.Namespace(preset=None))
            elif action == "series-list":    cmd_series(argparse.Namespace(action="list", id=None, preset=None, force=False))
            elif action == "series-new":     _wizard_series_new()
            elif action == "setup-voices":   _wizard_setup_voices()
            elif action == "models-scan":    _wizard_models_scan()
            elif action == "models-adopt":   _wizard_models_adopt()
            elif action == "models-clean":   _wizard_models_clean()
            elif action == "doctor":         _wizard_doctor()
            elif action == "status":         cmd_status(argparse.Namespace(limit=12))
            elif action == "bench":          cmd_bench(argparse.Namespace(real=False))
        except SystemExit as e:
            # Don't kill the wizard if one sub-command errors — surface and continue.
            if e.code and e.code != 0:
                print(red(f"  · command failed (exit {e.code}). Returning to menu."))

# ─────────────── top-level menu ───────────────

def print_menu(short: bool = True) -> None:
    print()
    print(bold("forge ") + dim("· local-AI factory"))
    print(dim("─" * 36))
    print()
    print(gold("MAKE"))
    print(f"  forge {bold('brief')}        full episode kit from a topic (add --video for mp4)")
    print(f"  forge {bold('episode')}      book/text → 4-part subtitled video episode")
    print(f"  forge {bold('audiobook')}    book/text → narrated + translated audiobook")
    print(f"  forge {bold('mandala')}      exact procedural radial mandala (SVG + PNG + QC)")
    print(f"  forge {bold('childrens-book')} symmetric drawing-book pages (not diffusion)")
    print(f"  forge {bold('thumbnail')}    render one branded thumbnail (text → image)")
    print(f"  forge {bold('edit')}         restyle / edit an existing image")
    print(f"  forge {bold('voice')}        synthesize voiceover audio")
    print(f"  forge {bold('video')}        mux thumbnail + voiceover into mp4 (Ken Burns)")
    print()
    print(gold("BROWSE"))
    print(f"  forge {bold('list')}         all presets + voices")
    print(f"  forge {bold('show')} <p>     dump one preset's full spec")
    print(f"  forge {bold('series list')} all consistency-lock series")
    print()
    print(gold("CONSISTENCY"))
    print(f"  forge {bold('series new')} <id>    scaffold a style/world/cast lock")
    print(f"  forge {bold('series show')} <id>   inspect a series")
    print(f"  forge brief/thumbnail {bold('--series')} <id>   lock a batch to one production")
    print()
    print(gold("MODELS"))
    print(f"  forge {bold('models scan')}        inventory ~/Models")
    print(f"  forge {bold('models scan --full')} include per-model breakdown")
    print(f"  forge {bold('models adopt')} <p>   move file into ~/Models/")
    print(f"  forge {bold('models clean')}       reclaim disk (partial/orphan blobs)")
    print()
    print(gold("SYSTEM"))
    print(f"  forge {bold('wizard')}             guided interactive mode")
    print(f"  forge {bold('web')}                browser wizard + run console")
    print(f"  forge {bold('doctor')}             verify/repair local ML runtime")
    print(f"  forge {bold('status')}             recent jobs, locks, readiness")
    print(f"  forge {bold('bench')}              write machine quality profiles")
    print(f"  forge {bold('setup-voices')}       upgrade voice engine (Kokoro)")
    print()
    print(gold("VIDEO PIPELINE") + dim("  (separate tool)"))
    print(f"  process-video {bold('warmup')}             pre-cache models (online, once)")
    print(f"  process-video {bold('process')} <video>    one video → upload-ready bundle")
    if not short:
        return
    print()
    print(dim("Tip: run any command without args to be prompted interactively."))
    print(dim("Try: ") + cyan("forge wizard") + dim("  for full menu-driven mode."))
    print()

# ─────────────── helpers ───────────────

def _need(label: str, *, choices: list[str] | None = None, default: str | None = None, tty: bool = True) -> str:
    if not tty:
        sys.exit(red(f"missing required argument: {label}") + dim(" (running non-interactively)"))
    return prompt(label, choices=choices, default=default)

# ─────────────── argparse ───────────────

def main() -> int:
    if len(sys.argv) == 1:
        print_menu()
        return 0

    parser = argparse.ArgumentParser(
        prog="forge",
        description="local-AI factory — run with no args for the menu",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="cmd", required=False)

    p_list = sub.add_parser("list", help="all presets and voices")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="show one preset's full spec")
    p_show.add_argument("preset", nargs="?", help=f"preset id ({', '.join(list_preset_ids()) if PRESETS_DIR.exists() else 'see brand/presets/'})")
    p_show.set_defaults(func=cmd_show)

    p_mand = sub.add_parser("mandala", help="procedural mathematically symmetric mandala art")
    p_mand.add_argument("--style", choices=sorted(MANDALA_STYLES), default="coloring")
    p_mand.add_argument("--symmetry", type=int, default=12, help="radial symmetry order, e.g. 8, 12, 16, 24")
    p_mand.add_argument("--rings", type=int, default=7, help="concentric motif rings")
    p_mand.add_argument("--complexity", choices=list(COMPLEXITY_LEVELS), default="max")
    p_mand.add_argument("--seed", type=int, default=1)
    p_mand.add_argument("--width", type=int, default=2400)
    p_mand.add_argument("--height", type=int, default=2400)
    p_mand.add_argument("--stroke-width", type=float, default=3.0)
    p_mand.add_argument("--palette", choices=["ink", "soft", "royal"], default="ink")
    p_mand.add_argument("--supersample", type=int, default=2, help="anti-aliasing scale; 1 is fastest")
    p_mand.add_argument("--no-mirror", action="store_true", help="disable dihedral mirror contract in metadata")
    p_mand.add_argument("--out")
    p_mand.set_defaults(func=cmd_mandala)

    p_cb = sub.add_parser("childrens-book", help="procedural symmetric children's drawing-book pages")
    p_cb.add_argument("--theme", choices=["all", *CHILD_THEMES], default="all")
    p_cb.add_argument("--pages", type=int, default=3)
    p_cb.add_argument("--symmetry", type=int, default=12, help="radial border symmetry order")
    p_cb.add_argument("--rings", type=int, default=7, help="decorative border rings")
    p_cb.add_argument("--complexity", choices=list(COMPLEXITY_LEVELS), default="max")
    p_cb.add_argument("--seed", type=int, default=101)
    p_cb.add_argument("--width", type=int, default=2400)
    p_cb.add_argument("--height", type=int, default=2400)
    p_cb.add_argument("--palette", choices=["ink", "soft", "royal"], default="ink")
    p_cb.add_argument("--supersample", type=int, default=2, help="anti-aliasing scale; 1 is fastest")
    p_cb.add_argument("--out")
    p_cb.set_defaults(func=cmd_childrens_book)

    p_folk = sub.add_parser("folk-art", help="procedural folk/devotional coloring page line art")
    p_folk.add_argument("--theme", choices=list(FOLK_ART_THEMES), default="buddha-peacock")
    p_folk.add_argument("--width", type=int, default=2400)
    p_folk.add_argument("--height", type=int, default=1800)
    p_folk.add_argument("--complexity", choices=list(COMPLEXITY_LEVELS), default="max")
    p_folk.add_argument("--stroke-width", type=float, default=3.0)
    p_folk.add_argument("--palette", choices=["ink", "soft"], default="ink")
    p_folk.add_argument("--supersample", type=int, default=2, help="anti-aliasing scale; 1 is fastest")
    p_folk.add_argument("--out")
    p_folk.set_defaults(func=cmd_folk_art)

    p_min = sub.add_parser("minimal-animal", help="beta closed-loop <=8-line animal T-shirt mark")
    p_min.add_argument("--animal", "--description", dest="animal",
                       help="animal description, e.g. 'alert snow leopard with a long tail'")
    p_min.add_argument("--max-lines", type=int, default=8,
                       help="maximum SVG stroke primitives allowed; hard range 1-8")
    p_min.add_argument("--seed", type=int, default=1)
    p_min.add_argument("--width", type=int, default=1280)
    p_min.add_argument("--height", type=int, default=1280)
    p_min.add_argument("--stroke-width", type=float, default=18.0)
    p_min.add_argument("--background", default="#F5EFE3")
    p_min.add_argument("--stroke", default="#111111")
    p_min.add_argument("--supersample", type=int, default=2)
    p_min.add_argument("--skip-gpu-check", action="store_true",
                       help="skip the Metal readiness guard; exact 8-line construction itself is procedural")
    p_min.add_argument("--out")
    p_min.set_defaults(func=cmd_minimal_animal)

    # forge engine — domain-expert style engines (noir-cinema, wildlife-photo, etc.)
    p_eng = sub.add_parser("engine", help="domain-expert style engines (specialist FLUX prompt builders)")
    eng_sub = p_eng.add_subparsers(dest="engine_cmd", required=True)

    eng_list = eng_sub.add_parser("list", help="list registered engines")
    eng_list.set_defaults(func=cmd_engine_list)

    eng_describe = eng_sub.add_parser("describe", help="show one engine's full vocabulary")
    eng_describe.add_argument("name")
    eng_describe.set_defaults(func=cmd_engine_describe)

    eng_recipes = eng_sub.add_parser("recipes", help="list curated prompt-library recipes")
    eng_recipes.add_argument("--engine", default=None, help="filter by engine id")
    eng_recipes.set_defaults(func=cmd_engine_recipes)

    eng_render = eng_sub.add_parser("render", help="build a directive + render via FLUX")
    eng_render.add_argument("name", nargs="?", default=None,
                            help="engine id (e.g. noir-cinema). Omit when --recipe is given.")
    eng_render.add_argument("--recipe", default=None,
                            help="recipe id from brand/prompts/library.json (preset everything; --subject/--config/--seed still override)")
    eng_render.add_argument("--subject", default=None, help="free-text subject (required if no --recipe)")
    eng_render.add_argument("--config", default=None,
                            help="comma-separated knob=value overrides, e.g. 'cinematography.key_light=neon-practical,accent.accent_color=ice-blue'")
    eng_render.add_argument("--negative", default=None, dest="extra_negatives",
                            help="comma-separated extra negative terms appended to engine + master primer. Each item is one negative.")
    eng_render.add_argument("--seeds", type=int, default=1,
                            help="render N variants with consecutive seeds (--seed, --seed+1, ...) into a gallery dir + HTML contact sheet. Default 1.")
    eng_render.add_argument("--refine", action="store_true",
                            help="two-pass refinement: after FLUX-dev composes, img2img-refine at low denoise to add micro-detail. Adds ~30 s per image. NOTE: --profile quality enables this by default; use --no-refine to opt out.")
    eng_render.add_argument("--no-refine", action="store_true", dest="no_refine",
                            help="explicitly disable the two-pass refinement, even when --profile quality would default it on.")
    eng_render.add_argument("--refine-strength", type=float, default=0.25, dest="refine_strength",
                            help="denoising strength for refinement pass (0.05=barely-touch, 0.4=significant rework). Default 0.25.")
    eng_render.add_argument("--hi-res", action="store_true", dest="hi_res",
                            help="Render at 1920x1080 instead of default 1280x720 (~2x compute, finer detail).")
    eng_render.add_argument("--ultra-res", action="store_true", dest="ultra_res",
                            help="Render at 2048x1152 (~3x compute, max detail; pair with --refine for best results).")
    eng_render.add_argument("--width", type=int, default=None, help="Override output width (px).")
    eng_render.add_argument("--height", type=int, default=None, help="Override output height (px).")
    eng_render.add_argument("--guidance", type=float, default=None,
                            help="FLUX guidance scale. Default per-engine (~4.5). Push to 5.5-6.5 for stricter prompt adherence (less AI bloom).")
    eng_render.add_argument("--seed", type=int, default=None)
    eng_render.add_argument("--out", default=None,
                            help="output PNG path. If omitted, lands in ~/Desktop/forge-test/engine-renders/<engine>/<recipe-or-slug>.png")
    eng_render.add_argument("--from-image", default=None, dest="from_image",
                            help="source image to restyle with the engine's directive (img2img via FLUX-Kontext / dev). Turns your photo into the engine's style — e.g. a bald-eagle photo into a mandala.")
    eng_render.add_argument("--from-image-strength", type=float, default=0.85, dest="from_image_strength",
                            help="strength of the restyle when --from-image is set (0.3=minor edit, 0.85=major restyle, 0.95=near-replace). Default 0.85.")
    eng_render.add_argument("--no-default-loras", action="store_true", dest="no_default_loras",
                            help="disable the engine's curated default LoRA stack (see brand/loras/README.md). Useful for A/B comparison or when iterating on a new prompt without LoRA bias.")
    eng_render.add_argument("--draft", action="store_true", help="schnell @ 4 steps (cool/fast)")
    eng_render.add_argument("--profile", choices=list(PROFILES), default=None)
    eng_render.add_argument("--steps", type=int, default=None,
                            help="override FLUX inference steps; useful for faster engine batches. Overrides the profile step count.")
    eng_render.add_argument("--quantize", type=int, choices=[0, 3, 4, 5, 6, 8], default=None, dest="quantize",
                            help="mflux quantization (3/4/5/6/8 bits). 4=~50%% faster with mild quality drop (default), 8=near-fp16 fidelity with ~25%% speed gain, 0=force fp16. Env: FORGE_FLUX_QUANTIZE.")
    eng_render.add_argument("--upscale", type=str, default=None, dest="upscale",
                            help="post-render upscale via RealESRGAN-ncnn-vulkan (safe high-res — renders FLUX at base size, then upscales). Values: 2x / 3x / 4x / 6x / 8x / 12x / 16x. Adds ~6 s per 4× pass. Replaces --hi-res / --ultra-res when memory matters.")
    eng_render.add_argument("--allow-qc-warnings", action="store_true", dest="allow_qc_warnings",
                            help="treat failed auto-QC checks as warnings instead of blockers. Per-render blockers.json is still written; publishable=true is forced. Use only after human review.")
    eng_render.set_defaults(func=cmd_engine_render)

    p_th = sub.add_parser("thumbnail", help="render one thumbnail")
    p_th.add_argument("--preset")
    p_th.add_argument("--concept", help="FLUX image prompt (no text on image). Use [character] placeholders to inline series cast.")
    p_th.add_argument("--headline")
    p_th.add_argument("--sub", default=None)
    p_th.add_argument("--bg", help="use existing background image instead of generating")
    p_th.add_argument("--seed", type=int, default=1, help="ignored when --series is set; series base_seed is used")
    p_th.add_argument("--series", help="series id (locks style anchor, world, characters, seed)")
    p_th.add_argument("--frame-offset", type=int, default=0, dest="frame_offset",
                      help="frame index within the series (added to base_seed)")
    p_th.add_argument("--draft", action="store_true",
                      help="force schnell at 4 steps — much faster, lower heat, lower quality (alias for --profile cool)")
    p_th.add_argument("--profile", choices=list(PROFILES),
                      help="explicit resource profile (cool/balanced/max). Overrides preset defaults + --draft.")
    p_th.add_argument("--steps", type=int, default=None,
                      help="override FLUX inference steps; lower is cooler/faster")
    p_th.add_argument("--lora", action="append", default=None,
                      help="LoRA .safetensors path (or bare name in brand/loras/). Repeatable.")
    p_th.add_argument("--lora-scale", action="append", default=None, type=float, dest="lora_scale",
                      help="scale per --lora (default 0.8). Repeatable; must match --lora count.")
    p_th.add_argument("--out")
    p_th.set_defaults(func=cmd_thumbnail)

    p_v = sub.add_parser("voice", help="synthesize voiceover audio")
    p_v.add_argument("--preset")
    p_v.add_argument("--text")
    p_v.add_argument("--out")
    p_v.add_argument("--translate", default=None,
                     help=f"comma-separated target language codes for translated text+audio sidecars (env {AUDIO_TRANSLATE_ENV})")
    p_v.set_defaults(func=cmd_voice)

    p_vid = sub.add_parser("video", help="mux a thumbnail + voiceover into a podcast-style mp4")
    p_vid.add_argument("--image", help="path to the still image (thumbnail/poster)")
    p_vid.add_argument("--audio", help="path to the voiceover audio (any format ffmpeg reads)")
    p_vid.add_argument("--no-kenburns", action="store_true", dest="no_kenburns",
                       help="static image (no slow zoom/pan)")
    p_vid.add_argument("--zoom-max", type=float, default=1.15, dest="zoom_max",
                       help="Ken-Burns max zoom factor (1.0 = no zoom; 1.15 = subtle)")
    p_vid.add_argument("--fade-out", type=float, default=1.0, dest="fade_out",
                       help="fade-out duration in seconds at the end")
    p_vid.add_argument("--out")
    p_vid.set_defaults(func=cmd_video)

    p_e = sub.add_parser("edit", help="create a version of an existing image")
    p_e.add_argument("--image", help="source image path")
    p_e.add_argument("--preset", help="brand preset to apply as style")
    p_e.add_argument("--instruction", help="free-form edit (e.g., 'swap background to teal alpine lake')")
    p_e.add_argument("--strength", type=float, default=0.6,
                     help="how much to TRANSFORM (0.3=minor, 0.9=major) — img2img fallback only")
    p_e.add_argument("--steps", type=int, default=18,
                     help="FLUX inference steps. Default 18 (matches --profile balanced). "
                          "Drop to 4 with --draft, raise to 30 for max quality.")
    p_e.add_argument("--draft", action="store_true",
                     help="schnell @ 4 steps for fast preview")
    p_e.add_argument("--profile", choices=list(PROFILES), default=None,
                     help="speed profile (cool/balanced/max/quality) — overrides --steps if set")
    p_e.add_argument("--seed", type=int, default=1)
    p_e.add_argument("--out")
    p_e.set_defaults(func=cmd_edit)

    p_b = sub.add_parser("brief", help="full episode kit from a topic")
    p_b.add_argument("--topic")
    p_b.add_argument("--preset")
    p_b.add_argument("--voice")
    p_b.add_argument("--series", help="series id (locks style/world/characters across the kit)")
    p_b.add_argument("--draft", action="store_true",
                     help="schnell @ 4 steps for thumbnails — much faster, lower heat (alias for --profile cool)")
    p_b.add_argument("--profile", choices=list(PROFILES),
                     help="explicit resource profile (cool/balanced/max). Overrides preset defaults + --draft.")
    p_b.add_argument("--steps", type=int, default=None,
                     help="override FLUX thumbnail steps; lower is cooler/faster")
    p_b.add_argument("--lora", action="append", default=None,
                     help="LoRA .safetensors path or bare name in brand/loras/. Repeatable.")
    p_b.add_argument("--lora-scale", action="append", default=None, type=float, dest="lora_scale",
                     help="scale per --lora (default 0.8). Repeatable.")
    p_b.add_argument("--video", action="store_true",
                     help="also mux thumb-1 + voiceover into episode-podcast.mp4")
    p_b.add_argument("--translate", default=None,
                     help=f"comma-separated target language codes for translated voiceover text+audio (env {AUDIO_TRANSLATE_ENV})")
    p_b.add_argument("--out")
    p_b.set_defaults(func=cmd_brief)

    p_ep = sub.add_parser("episode", help="book/text → 4 mini segments stitched into a subtitled episode")
    src = p_ep.add_mutually_exclusive_group(required=False)
    src.add_argument("--book", help="source .txt/.md book/script path (.pdf works if pypdf is installed)")
    src.add_argument("--text", help="source text to adapt directly")
    p_ep.add_argument("--title", help="episode title (defaults from book filename)")
    p_ep.add_argument("--preset", default="cinematic", help="brand preset")
    p_ep.add_argument("--voice", default="male_warm", help="voice preset")
    p_ep.add_argument("--translate", default="hi,mr",
                      help="target translation languages, default hi,mr; Sarvam is used")
    p_ep.add_argument("--segments", type=int, default=4, help="number of mini segments")
    p_ep.add_argument("--seconds", type=float, default=15.0, help="target seconds per segment")
    p_ep.add_argument("--shots-per-segment", type=int, default=4,
                      help="still-image/dialog shots inside each segment; default 4")
    p_ep.add_argument("--draft", action="store_true",
                      help="schnell @ 4 steps for visuals — faster/lower heat")
    p_ep.add_argument("--profile", choices=list(PROFILES),
                      help="visual generation profile; default balanced unless --draft")
    p_ep.add_argument("--steps", type=int, default=None,
                      help="override FLUX visual inference steps")
    p_ep.add_argument("--no-flux", action="store_true",
                      help="use branded title-card visuals instead of generating FLUX images")
    p_ep.add_argument("--out")
    p_ep.set_defaults(func=cmd_episode)

    p_ab = sub.add_parser("audiobook", help="book/text → source and translated audiobook audio")
    ab_src = p_ab.add_mutually_exclusive_group(required=False)
    ab_src.add_argument("--book", help="source .txt/.md book path (.pdf works if pypdf is installed)")
    ab_src.add_argument("--text", help="source text to narrate directly")
    p_ab.add_argument("--title", help="audiobook title (defaults from book filename)")
    p_ab.add_argument("--voice", default="male_warm", help="voice preset")
    p_ab.add_argument("--translate", default="hi,mr",
                      help="target translation languages, default hi,mr; Sarvam is used")
    p_ab.add_argument("--chunk-chars", type=int, default=1400,
                      help="max source characters per narration chunk")
    p_ab.add_argument("--max-chunks", type=int, default=None,
                      help="process only the first N chunks")
    p_ab.add_argument("--out")
    p_ab.set_defaults(func=cmd_audiobook)

    p_s = sub.add_parser("series", help="manage consistency-lock files (style/world/characters)")
    p_s.add_argument("action", choices=["list", "show", "new"])
    p_s.add_argument("id", nargs="?")
    p_s.add_argument("--preset", help="(new) which preset locks the look")
    p_s.add_argument("--force", action="store_true", help="(new) overwrite existing")
    p_s.set_defaults(func=cmd_series)

    p_setup = sub.add_parser("setup-voices", help="upgrade voice engine")
    p_setup.add_argument("--kokoro", action="store_true")
    p_setup.set_defaults(func=cmd_setup_voices)

    p_doc = sub.add_parser("doctor", help="verify/repair local ML runtime")
    p_doc.add_argument("--deep", action="store_true", help="include hardware and model inventory details")
    p_doc.add_argument("--repair", action="store_true", help="create canonical dirs and shell env exports where possible")
    p_doc.add_argument("--json", action="store_true", help="print JSON report")
    p_doc.add_argument("--verbose", action="store_true")
    p_doc.set_defaults(func=cmd_doctor)

    p_status = sub.add_parser("status", help="show recent jobs and resource locks")
    p_status.add_argument("--limit", type=int, default=12)
    p_status.set_defaults(func=cmd_status)

    p_bench = sub.add_parser("bench", help="write local hardware quality profiles")
    p_bench.add_argument("--real", action="store_true", help="reserved for slow real model microbenchmarks")
    p_bench.set_defaults(func=cmd_bench)

    p_m = sub.add_parser("models", help="inventory / adopt / clean model files")
    p_m.add_argument("action", choices=["scan", "list", "adopt", "clean"])
    p_m.add_argument("path", nargs="?")
    p_m.add_argument("--as", dest="as_")
    p_m.add_argument("--delete-source", action="store_true")
    p_m.add_argument("--full", action="store_true", help="include per-model breakdown")
    p_m.add_argument("--dry-run", action="store_true", dest="dry_run",
                     help="(clean) preview reclaimable space without removing")
    p_m.add_argument("--yes", action="store_true", help="(clean) skip confirmations")
    p_m.add_argument("--remove", action="append", default=None,
                     help="(clean) remove an entire model repo, e.g. black-forest-labs/FLUX.1-schnell. Repeatable.")
    p_m.set_defaults(func=cmd_models)

    # forge jokes — WhatsApp joke pack generator
    p_jokes = sub.add_parser("jokes", help="WhatsApp joke pack generator for Indian seniors")
    jokes_sub = p_jokes.add_subparsers(dest="jokes_cmd", required=True)

    jokes_gen = jokes_sub.add_parser("generate", help="generate a new joke pack")
    jokes_gen.add_argument("--mode", choices=["daily", "morning", "festival", "regional", "voice-note"], default="daily")
    jokes_gen.add_argument("--langs", type=lambda x: x.split(","), default=["hi", "mr"], help="comma-separated language codes (default: hi,mr)")
    jokes_gen.add_argument("--count", type=int, default=12, help="number of jokes to generate")
    jokes_gen.add_argument("--cards", type=int, default=4, help="number of image cards")
    jokes_gen.add_argument("--audio", type=int, default=2, help="number of audio clips")
    jokes_gen.add_argument("--video", type=int, default=2, help="number of MP4 videos")
    jokes_gen.add_argument("--voice", default="male_warm", help="voice preset id")
    jokes_gen.add_argument("--seed", type=int, help="random seed")
    jokes_gen.add_argument("--out", required=True, help="output directory")
    jokes_gen.add_argument("--dry-run", action="store_true", help="text only, no cards/audio/video")
    jokes_gen.set_defaults(func=cmd_jokes_generate)

    jokes_qa = jokes_sub.add_parser("qa", help="QA an existing pack")
    jokes_qa.add_argument("manifest", help="path to manifest.json")
    jokes_qa.set_defaults(func=cmd_jokes_qa)

    jokes_render = jokes_sub.add_parser("render", help="re-render artifacts from manifest")
    jokes_render.add_argument("manifest", help="path to manifest.json")
    jokes_render.add_argument("--cards", action="store_true")
    jokes_render.add_argument("--audio", action="store_true")
    jokes_render.add_argument("--video", action="store_true")
    jokes_render.set_defaults(func=cmd_jokes_render)

    p_w = sub.add_parser("wizard", help="full guided interactive mode")
    p_w.set_defaults(func=cmd_wizard)

    p_web = sub.add_parser("web", help="browser wizard + run console")
    p_web.add_argument("--host", default="127.0.0.1")
    p_web.add_argument("--port", type=int, default=8765)
    p_web.add_argument("--metal-slots", type=int, default=None,
                       help="allow N concurrent heavy Metal jobs in this web session (e.g. 4 on 128 GB Macs)")
    p_web.add_argument("--no-open", action="store_true", help="serve without opening a browser")
    p_web.set_defaults(func=cmd_web)

    args = parser.parse_args()
    if not args.cmd:
        print_menu()
        return 0
    return args.func(args)


if __name__ == "__main__":
    install_runtime_guards()
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print()
        sys.exit(130)
    except subprocess.TimeoutExpired as e:
        sys.exit(red(f"subprocess timed out after {e.timeout}s: {e.cmd}"))
    except subprocess.CalledProcessError as e:
        sys.exit(red(f"subprocess failed: {e}"))
