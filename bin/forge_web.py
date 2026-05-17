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
    elif action in {"brief", "episode", "audiobook", "childrens-book", "engine"}:
        paths += _payload_paths(payload, "out")
        if action == "engine" and not str(payload.get("out") or "").strip():
            paths.append(str(DEFAULT_OUTPUT_ROOT / "engine-renders"))
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
        _add(cmd, "--out", payload.get("out"))
        engine_name = str(payload.get("name") or "").strip()
        if engine_name:
            cmd.append(engine_name)
    elif action == "edit":
        cmd.append("edit")
        _add(cmd, "--image", payload.get("image"))
        _add(cmd, "--preset", payload.get("preset"))
        _add(cmd, "--instruction", payload.get("instruction"))
        _add(cmd, "--strength", payload.get("strength"))
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
        with self.log_path.open("a", encoding="utf-8") as fh:
            fh.write(clean + "\n")

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
    recipes = [
        {"id": rid, "engine": spec.get("engine"), "description": spec.get("description", "")}
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
        if isinstance(data, dict):
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


INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Forge Wizard</title>
<style>
:root {
  color-scheme: light;
  --bg: #f6f4ef;
  --surface: #fffdf8;
  --surface-2: #ebe7de;
  --ink: #211f1b;
  --muted: #6f6a60;
  --line: #d8d1c4;
  --green: #196f5b;
  --blue: #2d609e;
  --amber: #a76312;
  --rose: #a43d55;
  --shadow: 0 14px 38px rgba(43, 36, 24, .10);
}
* { box-sizing: border-box; }
body {
  margin: 0;
  min-height: 100vh;
  background: var(--bg);
  color: var(--ink);
  font: 14px/1.45 ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}
button, input, select, textarea { font: inherit; }
button {
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--ink);
  border-radius: 8px;
  padding: 8px 10px;
  cursor: pointer;
}
button:hover { border-color: #b8ad9a; }
button.primary { background: var(--green); border-color: var(--green); color: white; }
button.danger { color: #8b1e32; }
.app {
  display: grid;
  grid-template-columns: 280px minmax(420px, 1fr) minmax(360px, .9fr);
  min-height: 100vh;
}
.sidebar {
  border-right: 1px solid var(--line);
  background: #ede9df;
  padding: 18px;
  overflow: auto;
}
.brand { font-size: 22px; font-weight: 800; letter-spacing: 0; margin-bottom: 4px; }
.meta { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; }
.group-title {
  margin: 22px 0 8px;
  color: var(--muted);
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
  letter-spacing: .06em;
}
.action-list { display: grid; gap: 6px; }
.action {
  width: 100%;
  text-align: left;
  border-color: transparent;
  background: transparent;
  padding: 9px 10px;
}
.action.active {
  background: var(--surface);
  border-color: var(--line);
  box-shadow: 0 1px 0 rgba(0,0,0,.03);
}
.main, .process {
  padding: 18px;
  overflow: auto;
}
.main { border-right: 1px solid var(--line); }
.panel {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: var(--shadow);
}
.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--line);
}
h1, h2 { margin: 0; letter-spacing: 0; }
h1 { font-size: 20px; }
h2 { font-size: 15px; }
form { padding: 16px; display: grid; gap: 13px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.field { display: grid; gap: 6px; min-width: 0; }
.field label { font-weight: 700; font-size: 12px; color: #3e3a33; }
.field input, .field select, .field textarea {
  width: 100%;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 9px 10px;
  background: white;
  color: var(--ink);
}
.field textarea { min-height: 96px; resize: vertical; }
.path-row { display: grid; grid-template-columns: 1fr auto; gap: 8px; }
.checks { display: flex; gap: 14px; flex-wrap: wrap; }
.check { display: flex; gap: 8px; align-items: center; }
.runbar { display: flex; gap: 10px; align-items: center; justify-content: flex-end; padding-top: 4px; }
.cmd {
  margin: 0 16px 16px;
  padding: 10px;
  background: #27231d;
  color: #f4ead6;
  border-radius: 8px;
  overflow-wrap: anywhere;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}
.job-list { display: grid; gap: 8px; margin-bottom: 14px; }
.job {
  display: grid;
  gap: 3px;
  padding: 10px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
  text-align: left;
}
.job.active { border-color: var(--green); }
.status { font-size: 12px; font-weight: 800; }
.status.running { color: var(--blue); }
.status.ok { color: var(--green); }
.status.failed { color: var(--rose); }
.log {
  height: 330px;
  overflow: auto;
  background: #1f1d19;
  color: #f6ecd8;
  border-radius: 8px;
  padding: 12px;
  font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  white-space: pre-wrap;
}
.issues {
  display: grid;
  gap: 6px;
  margin-bottom: 10px;
}
.issue {
  padding: 8px 10px;
  border: 1px solid #e0acba;
  border-radius: 8px;
  background: #fff4f6;
  color: #7b1f36;
  overflow-wrap: anywhere;
}
.run-paths {
  display: grid;
  gap: 6px;
  margin-bottom: 10px;
  color: var(--muted);
  font-size: 12px;
}
.run-paths button { padding: 5px 7px; font-size: 12px; }
.resources {
  display: grid;
  gap: 8px;
  margin-bottom: 12px;
  padding: 12px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-radius: 10px;
}
.resBar { display: grid; gap: 4px; }
.resLabel {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  font-weight: 600;
  color: var(--muted);
  letter-spacing: 0.02em;
}
.resLabel span { font-weight: 500; color: var(--ink); }
.resTrack {
  height: 8px;
  background: rgba(0,0,0,0.07);
  border-radius: 999px;
  overflow: hidden;
}
.resFill {
  height: 100%;
  width: 0%;
  background: var(--green);
  border-radius: 999px;
  transition: width 0.4s ease, background 0.4s ease;
}
.resFill.warn { background: var(--amber); }
.resFill.hot  { background: var(--rose); }
.artifacts { display: grid; gap: 8px; margin-top: 14px; }
.artifact {
  display: grid;
  grid-template-columns: 1fr auto auto auto;
  gap: 8px;
  align-items: center;
  padding: 9px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}
.artifact-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.preview { margin-top: 14px; }
.preview img, .preview video { max-width: 100%; border-radius: 8px; border: 1px solid var(--line); background: white; }
.preview audio { width: 100%; }
.modal {
  position: fixed;
  inset: 0;
  background: rgba(23, 21, 18, .42);
  display: none;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
.modal.open { display: flex; }
.picker {
  width: min(940px, 96vw);
  max-height: 86vh;
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: 8px;
  box-shadow: var(--shadow);
  display: grid;
  grid-template-rows: auto auto 1fr;
}
.picker-top, .picker-path {
  padding: 12px;
  border-bottom: 1px solid var(--line);
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}
.picker-path input { flex: 1; min-width: 260px; padding: 9px 10px; border: 1px solid var(--line); border-radius: 8px; }
.entries { overflow: auto; padding: 8px; }
.entry {
  display: grid;
  grid-template-columns: 28px 1fr auto;
  align-items: center;
  gap: 8px;
  width: 100%;
  border: 0;
  border-radius: 8px;
  background: transparent;
  text-align: left;
}
.entry:hover { background: #f2eee5; }
.hidden { display: none !important; }
@media (max-width: 1060px) {
  .app { grid-template-columns: 220px 1fr; }
  .process { grid-column: 1 / -1; border-top: 1px solid var(--line); }
}
@media (max-width: 760px) {
  .app { display: block; }
  .sidebar, .main { border-right: 0; border-bottom: 1px solid var(--line); }
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
<script>
const state = { config: null, action: "thumbnail", activeJob: null, pickerField: null, pickerPath: "" };

const groups = [
  ["TEXT TO IMAGE", [
    ["thumbnail", "Thumbnail"],
    ["engine", "Branded image"],
    ["edit", "Edit image"],
    ["engine-list", "Engines"],
    ["engine-recipes", "Engine recipes"],
    ["engine-describe", "Engine details"]
  ]],
  ["CONTENT", [
    ["brief", "Episode kit"],
    ["episode", "Episode"],
    ["audiobook", "Audiobook"],
    ["audiobook-asmr", "ASMR audiobook"],
    ["voice", "Voiceover"],
    ["video", "Mux video"],
    ["process-video-process", "Process video"],
    ["process-video-warmup", "Video warmup"]
  ]],
  ["PROCEDURAL", [
    ["mandala", "Mandala"],
    ["childrens-book", "Children's pages"],
    ["folk-art", "Folk art page"]
  ]],
  ["SYSTEM", [
    ["list", "List presets"],
    ["show", "Show preset"],
    ["series-list", "Series list"],
    ["series-show", "Series show"],
    ["series-new", "Series new"],
    ["doctor", "Doctor"],
    ["status", "Status"],
    ["setup-voices", "Setup voices"],
    ["models-list", "Models list"],
    ["models-scan", "Models scan"],
    ["models-clean", "Models clean"],
    ["models-adopt", "Models adopt"],
    ["bench", "Bench"]
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
      {name:"bg", label:"Background path", type:"path"},
      {name:"draft", label:"Draft / cool", type:"checkbox"},
      {name:"profile", label:"Speed profile", type:"select", options:"profiles", value:"balanced"},
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
      {name:"name", label:"Engine", type:"select", options:"engines", required:true},
      {name:"recipe", label:"Recipe", type:"select", options:"recipesOptional"},
      {name:"subject", label:"Prompt", type:"textarea"},
      {name:"config", label:"Config overrides", type:"text"},
      {name:"negative", label:"Extra negatives", type:"text"},
      {name:"from_image", label:"Source image", type:"path"},
      {name:"from_image_strength", label:"Image strength", type:"number", value:"0.85"},
      {name:"seeds", label:"Variants", type:"number", value:"1"},
      {name:"draft", label:"Draft / cool", type:"checkbox"},
      {name:"profile", label:"Speed profile", type:"select", options:"profiles"},
      {name:"seed", label:"Seed", type:"number", value:"1"},
      {name:"width", label:"Width", type:"number"},
      {name:"height", label:"Height", type:"number"},
      {name:"guidance", label:"Guidance", type:"number"},
      {name:"refine", label:"Refine", type:"checkbox"},
      {name:"refine_strength", label:"Refine strength", type:"number", value:"0.25"},
      {name:"hi_res", label:"Hi-res", type:"checkbox"},
      {name:"ultra_res", label:"Ultra-res", type:"checkbox"},
      {name:"out", label:"Output path", type:"path"}
    ]
  },
  edit: {
    title: "Edit Image",
    fields: [
      {name:"image", label:"Source image", type:"path", required:true},
      {name:"preset", label:"Preset", type:"select", options:"presetsOptional"},
      {name:"instruction", label:"Instruction", type:"textarea"},
      {name:"strength", label:"Strength", type:"number", value:"0.6"},
      {name:"steps", label:"Steps", type:"number", value:"25"},
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
      {name:"draft", label:"Draft / cool", type:"checkbox"},
      {name:"profile", label:"Speed profile", type:"select", options:"profiles", value:"balanced"},
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
      {name:"draft", label:"Draft / cool", type:"checkbox"},
      {name:"profile", label:"Speed profile", type:"select", options:"profiles", value:"balanced"},
      {name:"steps", label:"Steps override", type:"number"},
      {name:"no_flux", label:"No FLUX", type:"checkbox"},
      {name:"out", label:"Output dir", type:"path", value:"~/Desktop/forge-test/episode"}
    ]
  },
  audiobook: {
    title: "Audiobook",
    fields: [
      {name:"book", label:"Book path", type:"path"},
      {name:"text", label:"Text", type:"textarea"},
      {name:"title", label:"Title", type:"text"},
      {name:"voice", label:"Voice", type:"select", options:"voices"},
      {name:"translate", label:"Translate", type:"text", value:"hi,mr"},
      {name:"chunk_chars", label:"Chunk chars", type:"number", value:"1400"},
      {name:"max_chunks", label:"Max chunks", type:"number"},
      {name:"out", label:"Output dir", type:"path", value:"~/Desktop/forge-test/audiobook"}
    ]
  },
  "audiobook-asmr": {
    title: "ASMR Audiobook",
    fields: [
      {name:"folder", label:"Input folder", type:"path"},
      {name:"rtf", label:"Transcript path", type:"path"},
      {name:"video", label:"Loop video", type:"path"},
      {name:"out_dir", label:"Output dir", type:"path", value:"~/Desktop/forge-test/asmr-audiobook"},
      {name:"langs", label:"Languages", type:"text", value:"en,hi,mr"},
      {name:"max_chars", label:"Sentence char cap", type:"number", value:"500"},
      {name:"max_words", label:"Excerpt max words", type:"number"},
      {name:"batch_pages", label:"Batch pages", type:"number", value:"10"},
      {name:"page_words", label:"Page words", type:"number", value:"250"},
      {name:"spoken_words", label:"Spoken words", type:"number", value:"150"},
      {name:"batches", label:"Batches", type:"text"},
      {name:"bed", label:"Ambient bed", type:"select", options:"audiobook_beds", value:"vinyl-crackle"},
      {name:"mode", label:"Voice mode", type:"select", options:"audiobook_modes", value:"normal"},
      {name:"english_engine", label:"English engine", type:"select", options:"audiobook_engines", value:"kokoro"},
      {name:"subtitles", label:"Subtitles", type:"select", options:"subtitle_modes", value:"srt"},
      {name:"thumbnail", label:"Generate thumbnails", type:"checkbox", checked:true},
      {name:"thumb_preset", label:"Thumbnail preset", type:"select", options:"presets", value:"thumbnail-bold"},
      {name:"thumb_seed", label:"Thumbnail seed", type:"number", value:"42"},
      {name:"thumb_frame_at", label:"Frame at seconds", type:"number"},
      {name:"sarvam_speaker", label:"Sarvam speaker", type:"text"},
      {name:"sarvam_speaker_mr", label:"Marathi speaker", type:"text"},
      {name:"sent_pause_ms", label:"Sentence pause ms", type:"number"},
      {name:"para_pause_ms", label:"Paragraph pause ms", type:"number"},
      {name:"dry_run", label:"Dry run", type:"checkbox"}
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
  bench: { title:"Bench", fields: [{name:"real", label:"Real microbenchmarks", type:"checkbox"}] }
};

function optionsFor(field) {
  const cfg = state.config || {};
  if (field.choices) return field.choices.map(v => ({ value:v, label:v }));
  if (field.options === "profiles") return [{value:"", label:"preset default"}, {value:"cool", label:"cool"}, {value:"balanced", label:"balanced"}, {value:"max", label:"max"}];
  if (field.options === "seriesOptional") return [{value:"", label:"none"}, ...(cfg.series || []).map(v => ({value:v, label:v}))];
  if (field.options === "presetsOptional") return [{value:"", label:"none"}, ...(cfg.presets || []).map(v => ({value:v, label:v}))];
  if (field.options === "enginesOptional") return [{value:"", label:"all"}, ...(cfg.engines || []).map(v => ({value:v, label:v}))];
  if (field.options === "recipesOptional") return [{value:"", label:"none"}, ...(cfg.recipes || []).map(v => ({value:v.id, label:v.engine ? `${v.id} · ${v.engine}` : v.id}))];
  if (field.options === "voices") return (cfg.voices || []).map(v => ({value:v.id, label:v.label || v.id}));
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
  const wrap = document.createElement("div");
  wrap.className = "field";
  const label = document.createElement("label");
  label.htmlFor = `field-${field.name}`;
  label.textContent = field.label;
  wrap.appendChild(label);
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
  return wrap;
}

function renderForm() {
  const spec = specs[state.action];
  document.getElementById("formTitle").textContent = spec.title;
  const form = document.getElementById("jobForm");
  form.innerHTML = "";
  const normal = spec.fields.filter(f => f.type !== "checkbox");
  const checks = spec.fields.filter(f => f.type === "checkbox");
  for (let i = 0; i < normal.length; i += 2) {
    const row = document.createElement("div");
    row.className = "grid-2";
    row.appendChild(fieldElement(normal[i]));
    if (normal[i + 1]) row.appendChild(fieldElement(normal[i + 1]));
    form.appendChild(row);
  }
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
  updateCommandPreview();
  form.oninput = updateCommandPreview;
}

function gatherPayload() {
  const payload = {};
  const form = document.getElementById("jobForm");
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") payload[el.name] = el.checked;
    else payload[el.name] = el.value;
  }
  return payload;
}

function updateCommandPreview() {
  const payload = gatherPayload();
  const parts = ["forge", state.action];
  for (const [k, v] of Object.entries(payload)) {
    if (v === "" || v === false) continue;
    if (v === true) parts.push(`--${k.replaceAll("_","-")}`);
    else parts.push(`--${k.replaceAll("_","-")} ${String(v).includes(" ") ? JSON.stringify(v) : v}`);
  }
  document.getElementById("commandPreview").textContent = parts.join(" ");
}

async function startJob(event) {
  event.preventDefault();
  const res = await fetch("/api/jobs", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({action: state.action, payload: gatherPayload()})
  });
  const job = await res.json();
  state.activeJob = job.id;
  renderJob(job);
  pollNow();
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
  if (!r.available) {
    if (job.status === "running") {
      box.hidden = false;
      document.getElementById("cpuLabel").textContent = r.note || "sampling…";
      document.getElementById("memLabel").textContent = "";
      document.getElementById("workerLabel").textContent = "";
      for (const id of ["cpuFill","memFill","workerFill"]) {
        const el = document.getElementById(id);
        el.style.width = "0%";
        el.className = "resFill";
      }
    } else {
      box.hidden = true;
    }
    return;
  }
  box.hidden = false;
  const cpuPct = r.cpu_pct || 0;
  const memPct = r.mem_pct || 0;
  const worker = r.worker || null;
  const cores = r.cpu_cores || 0;
  const workerCpuRaw = worker ? (worker.cpu || 0) : 0;
  // worker.cpu is in single-core %; normalize to "% of total CPU available" for the bar
  const workerCpuNorm = cores > 0 ? Math.min(100, workerCpuRaw / cores) : Math.min(100, workerCpuRaw);

  document.getElementById("cpuLabel").textContent = `${cpuPct.toFixed(1)}%`;
  document.getElementById("memLabel").textContent = `${memPct.toFixed(1)}% · ${r.mem_used_gb}/${r.mem_total_gb} GB`;
  document.getElementById("workerLabel").textContent = worker
    ? `${worker.name} · ${workerCpuRaw.toFixed(0)}% (${(worker.mem_mb/1024).toFixed(1)} GB)`
    : "—";

  setBar("cpuFill", cpuPct);
  setBar("memFill", memPct);
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
  if (job.status !== "running") loadRuns();
}

async function loadRuns() {
  if (state.activeJob) return;
  const res = await fetch("/api/runs");
  if (!res.ok) return;
  const data = await res.json();
  const list = document.getElementById("jobList");
  list.innerHTML = "";
  for (const run of (data.runs || []).slice(0, 8)) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "job";
    btn.innerHTML = `<span class="status ${run.status}">${String(run.status || "").toUpperCase()} · #${run.id || ""}</span><span>${escapeHtml(run.action || "run")} · ${run.elapsed || 0}s</span><span class="meta">${escapeHtml(run.cmd_display || "")}</span>`;
    btn.onclick = () => renderProcess({...run, logs:[`Recorded run: ${run.paths?.run_dir || ""}`], run_dir:run.paths?.run_dir, log_path:run.paths?.stdout_log, events_path:run.paths?.events, manifest_path:run.paths?.manifest});
    list.appendChild(btn);
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
