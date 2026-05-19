#!/usr/bin/env python3
"""forge_web_v2 — Madhubani Atelier UI (NES mode).

Companion to bin/forge_web.py (the legacy generic dashboard, port 8080).
This is a focused, opinionated, freeform-first UI for the Madhubani
catalog work — radically cut from 388 form fields to ~6 controls. See
docs/catalog/WEB_UI_V2_PLAN.md for the design rationale.

Launch:
  python3 bin/forge_web_v2.py
  python3 bin/forge_web_v2.py --port 8085
  FORGE_V2_PORT=9090 python3 bin/forge_web_v2.py

Stdlib only — same constraint as V1. Backend uses subprocess to call
bin/forge_madhubani.py for renders + bin/forge.py for engine work.
Per-render state in an in-memory dict, no DB.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import signal
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional

# --- Paths ---------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent  # Forge/
FORGE_MAD = ROOT / "bin" / "forge_madhubani.py"
FORGE_BIN = ROOT / "bin" / "forge.py"
SCHEMA_DIR = ROOT / "brand" / "madhubani"
GEN_DIR = ROOT / "generated" / "madhubani_animals"
STATIC_DIR = ROOT / "bin" / "static"
SPRITES_DIR = STATIC_DIR / "sprites"

# Make forge_gallery (SQLite-backed render registry + ratings) importable.
# Every render via `forge.py engine render` already captures into this DB;
# V2 reads + writes ratings through it.
sys.path.insert(0, str(ROOT / "bin"))
try:
    import forge_gallery  # type: ignore
    GALLERY_AVAILABLE = True
except Exception as _e:  # noqa: BLE001
    forge_gallery = None  # type: ignore
    GALLERY_AVAILABLE = False
    sys.stderr.write(f"[v2] WARN forge_gallery import failed: {_e}; ratings disabled\n")

# --- Render-job state ---------------------------------------------------

# Per-render job: id → {queue: Queue, status: str, image_path: str|None,
#                       started: float, finished: float|None, error: str|None}
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = threading.Lock()


def _new_job() -> str:
    """Allocate a render-job id and seed an empty event queue."""
    jid = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[jid] = {
            "queue": queue.Queue(),
            "status": "pending",
            "image_path": None,
            "image_url": None,
            "directive_url": None,
            "started": time.time(),
            "finished": None,
            "error": None,
            "subject_string": None,
            "config_string": None,
            "decision": None,  # filled by chat path: {animal, pose, register, reasoning}
            "proc": None,      # the subprocess.Popen object, so KILL can reach it
            "pgid": None,      # process-group id (start_new_session=True)
        }
    return jid


def _kill_all_active() -> dict:
    """SIGTERM every active render-job process group, then SIGKILL after
    a short grace period for anything that didn't exit. Returns a summary
    of what was killed for the UI / logs."""
    killed: list[str] = []
    grace: list[tuple[str, int]] = []  # (job_id, pgid) to SIGKILL after grace

    with JOBS_LOCK:
        for jid, job in list(JOBS.items()):
            if job.get("status") not in ("pending", "running"):
                continue
            pgid = job.get("pgid")
            if pgid is None:
                continue
            try:
                os.killpg(pgid, signal.SIGTERM)
                killed.append(jid)
                grace.append((jid, pgid))
                # Emit a synthetic event so the SSE stream tells the UI
                # the user pulled the cord (otherwise UI would wait for
                # the process to die quietly).
                job["queue"].put(("error", "user requested KILL — SIGTERM sent to process group"))
                job["status"] = "killing"
            except ProcessLookupError:
                # already exited between checks; nothing to do
                pass
            except Exception as e:  # noqa: BLE001
                job["queue"].put(("error", f"KILL failed: {e}"))

    # Grace period (1s) then SIGKILL the holdouts. Run async so the HTTP
    # response can return immediately.
    def _force_kill_after_grace() -> None:
        time.sleep(1.0)
        for jid, pgid in grace:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass  # already gone, fine
            except Exception:
                pass
            with JOBS_LOCK:
                if jid in JOBS:
                    JOBS[jid]["status"] = "killed"
                    JOBS[jid]["finished"] = time.time()
                    # Send poison-pill so the SSE loop exits cleanly
                    JOBS[jid]["queue"].put(("done", json.dumps({"status": "killed", "error": "killed by user"})))
                    JOBS[jid]["queue"].put(None)
    if grace:
        threading.Thread(target=_force_kill_after_grace, daemon=True).start()

    return {"killed_count": len(killed), "killed_job_ids": killed}


def _emit(jid: str, event: str, data: Any = "") -> None:
    """Push an event onto a job's SSE queue."""
    with JOBS_LOCK:
        job = JOBS.get(jid)
    if not job:
        return
    payload = data if isinstance(data, str) else json.dumps(data)
    job["queue"].put((event, payload))


def _close_job(jid: str, status: str = "done", error: Optional[str] = None) -> None:
    with JOBS_LOCK:
        job = JOBS.get(jid)
    if not job:
        return
    job["status"] = status
    job["finished"] = time.time()
    if error:
        job["error"] = error
    job["queue"].put(("done", json.dumps({"status": status, "error": error})))
    job["queue"].put(None)  # poison pill — SSE loop exits


# --- Subprocess runner: parses stdout into events -----------------------

# Patterns we look for in forge_madhubani.py / mflux-generate stdout
# so we can synthesize structured events for the terminal UI.
_STEP_RE = re.compile(r"\b(\d+)\s*/\s*(\d+)\b")  # "12/24" anywhere
_DONE_RE = re.compile(r"^\s*✓\s+(?P<path>.+\.png)\s*$")
_FAIL_RE = re.compile(r"render failed|✗ render failed", re.I)
_RUNNING_RE = re.compile(r"^\s*──\s*\[(\d+)/(\d+)\]\s*(\S+)\s+—\s+(\S+)\s+\(seed=(\d+)")
_DECISION_RE = re.compile(r"^\s*🤖")  # chat-decision banner from forge_madhubani.py


def _run_madhubani(jid: str, args: list[str]) -> None:
    """Run forge_madhubani.py with given args; parse stdout line-by-line
    and emit events for the terminal UI. The subprocess is placed in its
    own process group via start_new_session=True so that a KILL signal
    propagates to children (forge.py → mflux-generate → FLUX inference)."""
    cmd = [sys.executable, str(FORGE_MAD), *args]
    _emit(jid, "process.start", f"$ {' '.join(cmd[1:])}")
    try:
        proc = subprocess.Popen(
            cmd, cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
            start_new_session=True,  # ← critical: gives this proc + descendants a fresh pgid
        )
        with JOBS_LOCK:
            JOBS[jid]["proc"] = proc
            JOBS[jid]["pgid"] = os.getpgid(proc.pid)
            JOBS[jid]["status"] = "running"
    except FileNotFoundError as e:
        _emit(jid, "error", f"could not launch forge_madhubani.py: {e}")
        _close_job(jid, "error", str(e))
        return

    saw_subject_next = False
    saw_decision_next = 0  # count of post-banner lines we still capture

    for raw_line in proc.stdout:  # type: ignore[union-attr]
        line = raw_line.rstrip()
        if not line:
            continue

        # Forward the literal line — every line shows in the terminal.
        _emit(jid, "log", line)

        # Pattern-spot for richer events:
        m = _STEP_RE.search(line)
        if m and ("step" in line.lower() or "/" in line):
            try:
                cur, total = int(m.group(1)), int(m.group(2))
                if 1 <= cur <= total <= 200:  # sanity bound for flux step counter
                    _emit(jid, "render.engine.step", {"current": cur, "total": total})
            except ValueError:
                pass

        m = _DONE_RE.match(line)
        if m:
            png_path = Path(m.group("path").strip())
            if not png_path.is_absolute():
                png_path = (ROOT / png_path).resolve()
            with JOBS_LOCK:
                JOBS[jid]["image_path"] = str(png_path)
                # Surface via /file/<absolute-path-or-rel>
                rel = png_path.relative_to(ROOT) if str(png_path).startswith(str(ROOT)) else png_path
                JOBS[jid]["image_url"] = f"/file/{rel}"
                # Surface directive too
                drv = png_path.with_suffix(png_path.suffix + ".directive.json")
                if drv.exists():
                    rel_d = drv.relative_to(ROOT) if str(drv).startswith(str(ROOT)) else drv
                    JOBS[jid]["directive_url"] = f"/file/{rel_d}"
            _emit(jid, "render.complete", {
                "image_url": JOBS[jid]["image_url"],
                "directive_url": JOBS[jid]["directive_url"],
            })

        if _FAIL_RE.search(line):
            _emit(jid, "error", line)

        # Chat decision banner: capture the next 4 indented lines as the
        # routing decision (animal / pose / register / reasoning)
        if _DECISION_RE.match(line):
            saw_decision_next = 4
        elif saw_decision_next > 0:
            saw_decision_next -= 1
            # crude key:value parse
            if ":" in line:
                key, _, val = line.strip().partition(":")
                key = key.strip().lower().replace(" ", "_")
                with JOBS_LOCK:
                    JOBS[jid].setdefault("decision", {})[key] = val.strip()

    rc = proc.wait()
    _emit(jid, "process.exit", f"rc={rc}")
    _close_job(jid, "done" if rc == 0 else "error", error=None if rc == 0 else f"rc={rc}")


# --- HTTP handler -------------------------------------------------------


class V2Handler(BaseHTTPRequestHandler):
    server_version = "ForgeV2/0.1"

    # quieter access log
    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write("%s - - %s\n" % (self.address_string(), fmt % args))

    # --- routes ---

    def do_GET(self) -> None:
        path = self.path.split("?", 1)[0]
        if path == "/" or path == "/home":
            return self._serve_html(HOME_HTML)
        if path == "/gallery":
            return self._serve_html(GALLERY_HTML)
        if path == "/api/animals":
            return self._serve_json(_load_schema("animals.json"))
        if path == "/api/poses":
            return self._serve_json(_load_schema("poses.json"))
        if path == "/api/state":
            return self._serve_json(self._state_payload())
        if path == "/api/renders":
            return self._serve_json(self._renders_payload())
        if path == "/api/gallery-stats":
            return self._serve_json(self._gallery_stats_payload())
        if path.startswith("/events/"):
            jid = path.split("/", 2)[2]
            return self._serve_sse(jid)
        if path.startswith("/file/"):
            return self._serve_file(path[len("/file/"):])
        if path == "/file-abs":
            return self._serve_file_abs()
        if path.startswith("/static/"):
            return self._serve_static(path[len("/static/"):])
        return self._404()

    def do_POST(self) -> None:
        path = self.path.split("?", 1)[0]
        length = int(self.headers.get("Content-Length", "0") or 0)
        body_raw = self.rfile.read(length) if length else b""
        try:
            body = json.loads(body_raw) if body_raw else {}
        except json.JSONDecodeError:
            return self._json_error(400, "invalid JSON body")

        if path == "/render":
            return self._handle_render(body)
        if path == "/chat":
            return self._handle_chat(body)
        if path == "/promote":
            return self._handle_promote(body)
        if path == "/flag":
            return self._handle_flag(body)
        if path == "/api/rate":
            return self._handle_rate(body)
        if path == "/api/delete-render":
            return self._handle_delete_render(body)
        if path == "/api/kill-all":
            return self._handle_kill_all(body)
        return self._404()

    # --- handlers ---

    def _handle_render(self, body: dict) -> None:
        """Render a set or single pose via forge_madhubani.py render."""
        # Defensive: frontend may send null for pose when "all four" is chosen;
        # `None.strip()` would crash, so coalesce first.
        animal = (body.get("animal") or "").strip()
        pose = (body.get("pose") or "").strip() or None
        register = (body.get("register") or "madhubani-master-painter").strip()
        retry = bool(body.get("retry", False))
        if not animal:
            return self._json_error(400, "missing 'animal'")

        jid = _new_job()
        args = ["render", animal]
        if pose:
            args.append(pose)
        else:
            args.append("--all-poses")
        args.extend(["--register", register])
        if body.get("steps"):
            try:
                steps = max(1, min(80, int(body["steps"])))
            except (TypeError, ValueError):
                return self._json_error(400, "invalid 'steps'")
            args.extend(["--steps", str(steps)])
        if retry:
            args.append("--retry")

        threading.Thread(target=_run_madhubani, args=(jid, args), daemon=True).start()
        return self._serve_json({"job_id": jid})

    def _handle_chat(self, body: dict) -> None:
        """Natural-language render via forge_madhubani.py chat.
        Frontend can override Ollama's pose/register decisions if the user
        explicitly picked them on the form."""
        text = (body.get("text") or "").strip()
        if not text:
            return self._json_error(400, "missing 'text'")
        jid = _new_job()
        args = ["chat", text]
        if body.get("steps"):
            try:
                steps = max(1, min(80, int(body["steps"])))
            except (TypeError, ValueError):
                return self._json_error(400, "invalid 'steps'")
            args.extend(["--steps", str(steps)])
        if body.get("all_poses"):
            args.append("--all-poses")
        pose = (body.get("pose") or "").strip()
        if pose and not body.get("all_poses"):
            args.extend(["--pose", pose])
        register = (body.get("register") or "").strip()
        if register:
            args.extend(["--register", register])
        threading.Thread(target=_run_madhubani, args=(jid, args), daemon=True).start()
        return self._serve_json({"job_id": jid})

    def _handle_promote(self, body: dict) -> None:
        animal = (body.get("animal") or "").strip()
        pose = (body.get("pose") or "").strip()
        from_version = body.get("from_version") or "v1"
        if not (animal and pose):
            return self._json_error(400, "missing 'animal' or 'pose'")
        jid = _new_job()
        args = ["promote", animal, pose, "--from-version", from_version]
        threading.Thread(target=_run_madhubani, args=(jid, args), daemon=True).start()
        return self._serve_json({"job_id": jid})

    def _handle_flag(self, body: dict) -> None:
        animal = (body.get("animal") or "").strip()
        pose = (body.get("pose") or "").strip()
        notes = (body.get("notes") or "").strip() or "(no notes provided)"
        from_version = body.get("from_version") or "v1"
        if not (animal and pose):
            return self._json_error(400, "missing 'animal' or 'pose'")
        jid = _new_job()
        args = ["flag", animal, pose, "--notes", notes, "--from-version", from_version]
        threading.Thread(target=_run_madhubani, args=(jid, args), daemon=True).start()
        return self._serve_json({"job_id": jid})

    # --- SSE ---

    def _serve_sse(self, jid: str) -> None:
        with JOBS_LOCK:
            job = JOBS.get(jid)
        if not job:
            return self._json_error(404, f"unknown job_id: {jid}")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            while True:
                item = job["queue"].get()
                if item is None:  # poison pill — render finished
                    break
                event, data = item
                msg = f"event: {event}\ndata: {data}\n\n"
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # browser disconnected — that's fine

    # --- helpers ---

    def _serve_html(self, html: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        body = html.encode("utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json_error(self, status: int, msg: str) -> None:
        self._serve_json({"error": msg}, status=status)

    def _serve_file(self, relpath: str) -> None:
        """Serve a file from within the Forge root (renders, directives)."""
        p = (ROOT / relpath).resolve()
        try:
            p.relative_to(ROOT)  # path traversal guard
        except ValueError:
            return self._404()
        if not p.exists() or p.is_dir():
            return self._404()
        ctype = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".json": "application/json",
            ".md": "text/markdown; charset=utf-8",
        }.get(p.suffix.lower(), "application/octet-stream")
        data = p.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_file_abs(self) -> None:
        """Serve a file given its absolute path via ?p=<urlencoded>.
        Safety guards: must exist, must be regular file, must be under
        $HOME (so we can't be tricked into serving /etc/passwd), must
        have an allowlisted extension. The user is running this server
        as themselves, so any file under $HOME is fair game."""
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        raw = q.get("p", [""])[0]
        if not raw:
            return self._json_error(400, "missing 'p' query parameter")
        try:
            p = Path(raw).resolve()
        except OSError as e:
            return self._json_error(400, f"path resolution failed: {e}")
        # Safety: must be under user's home dir
        try:
            p.relative_to(_USER_HOME)
        except ValueError:
            return self._json_error(403, f"path outside HOME ({_USER_HOME}) is not servable")
        if not p.exists() or not p.is_file():
            return self._404()
        ext = p.suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".json", ".md", ".txt"}:
            return self._json_error(403, f"extension {ext!r} not in allowlist")
        ctype = {
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".webp": "image/webp", ".gif": "image/gif",
            ".json": "application/json",
            ".md": "text/markdown; charset=utf-8",
            ".txt": "text/plain; charset=utf-8",
        }[ext]
        data = p.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, relpath: str) -> None:
        """Serve from bin/static/ — sprites, sounds, etc."""
        p = (STATIC_DIR / relpath).resolve()
        try:
            p.relative_to(STATIC_DIR)
        except ValueError:
            return self._404()
        if not p.exists() or p.is_dir():
            return self._404()
        ctype = {".png": "image/png", ".svg": "image/svg+xml",
                 ".wav": "audio/wav", ".mp3": "audio/mpeg"}.get(p.suffix.lower(), "application/octet-stream")
        data = p.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _state_payload(self) -> dict:
        """Compact catalog state for the GALLERY page."""
        out = {"mastered": [], "flagged": [], "attempts": []}
        for kind, base in [
            ("mastered", GEN_DIR / "mastered"),
            ("flagged", GEN_DIR / "flagged"),
        ]:
            if not base.exists():
                continue
            for slug_dir in sorted(base.iterdir()):
                if not slug_dir.is_dir() or slug_dir.name.startswith("_"):
                    continue
                for pose_dir in sorted(slug_dir.iterdir()):
                    if pose_dir.is_dir():
                        pngs = sorted(pose_dir.glob("*.png"))
                        if pngs:
                            rel = pngs[0].relative_to(ROOT)
                            out[kind].append({
                                "animal": slug_dir.name,
                                "pose": pose_dir.name,
                                "url": f"/file/{rel}",
                            })
        attempts_base = GEN_DIR / "attempts"
        if attempts_base.exists():
            for slug_dir in sorted(attempts_base.iterdir()):
                if not slug_dir.is_dir() or slug_dir.name.startswith("_"):
                    continue
                for version_dir in sorted(slug_dir.iterdir()):
                    if version_dir.is_dir():
                        for png in sorted(version_dir.glob("*.png")):
                            if ".transparent" in png.name:
                                continue
                            rel = png.relative_to(ROOT)
                            out["attempts"].append({
                                "animal": slug_dir.name,
                                "version": version_dir.name,
                                "filename": png.name,
                                "url": f"/file/{rel}",
                            })
        return out

    # --- Gallery-DB-backed endpoints ---

    def _renders_payload(self) -> dict:
        """Return ALL captured renders from forge_gallery.db (not filtered
        by engine), most recent first, with their current rating + a /file/
        URL for the thumbnail. Supports ?engine=<name> as an optional
        filter via the parsed query string."""
        if not GALLERY_AVAILABLE:
            return {"error": "forge_gallery not available", "renders": [], "count": 0}
        # Parse optional engine filter from query string
        from urllib.parse import urlparse, parse_qs
        q = parse_qs(urlparse(self.path).query)
        engine_filter = q.get("engine", [None])[0]
        try:
            rows = forge_gallery.list_renders(engine=engine_filter, limit=500)  # type: ignore
        except Exception as e:  # noqa: BLE001 — surface DB errors instead of hiding
            return {"error": f"list_renders failed: {e!r}", "renders": [], "count": 0}
        out = []
        for r in rows:
            try:
                png_path = Path(r.get("png_path") or "")
                animal, pose, version = _infer_animal_pose_version(png_path)
                subject_full = r.get("subject") or ""
                out.append({
                    "id": r.get("id"),
                    "ts": r.get("ts"),
                    "engine": r.get("engine"),
                    "seed": r.get("seed"),
                    "rating": r.get("rating", 0),
                    "notes": r.get("notes"),
                    "subject_preview": subject_full[:140] + ("…" if len(subject_full) > 140 else ""),
                    "url": _file_url_for(png_path) if png_path.exists() else None,
                    "exists": png_path.exists(),
                    "png_path": str(png_path),
                    "animal": animal,
                    "pose": pose,
                    "version": version,
                    "directive_url": _file_url_for(r.get("directive_json")) if r.get("directive_json") else None,
                })
            except Exception as e:  # noqa: BLE001 — never crash the whole list because of one bad row
                out.append({
                    "id": r.get("id"),
                    "error": f"render row failed: {e!r}",
                    "png_path": r.get("png_path"),
                })
        return {"renders": out, "count": len(out)}

    def _gallery_stats_payload(self) -> dict:
        """Tallies across ALL engines in the gallery DB — total, ratings,
        plus a per-engine breakdown so it's obvious what's actually in there."""
        if not GALLERY_AVAILABLE:
            return {"available": False, "reason": "forge_gallery import failed at startup"}
        try:
            rows = forge_gallery.list_renders(engine=None, limit=10_000)  # type: ignore
        except Exception as e:  # noqa: BLE001
            return {"available": False, "reason": f"list_renders failed: {e!r}"}
        by_rating = {-1: 0, 0: 0, 1: 0, 2: 0}
        by_engine: dict[str, int] = {}
        for r in rows:
            by_rating[int(r.get("rating", 0))] = by_rating.get(int(r.get("rating", 0)), 0) + 1
            eng = str(r.get("engine") or "?")
            by_engine[eng] = by_engine.get(eng, 0) + 1
        return {
            "available": True,
            "total": len(rows),
            "dislike": by_rating[-1],
            "unrated": by_rating[0],
            "like": by_rating[1],
            "favorite": by_rating[2],
            "by_engine": by_engine,
            "db_path": str(forge_gallery.DB_PATH),  # type: ignore
        }

    def _handle_rate(self, body: dict) -> None:
        if not GALLERY_AVAILABLE:
            return self._json_error(503, "forge_gallery not available")
        try:
            render_id = int(body.get("render_id") or 0)
            rating = int(body.get("rating") or 0)
        except (TypeError, ValueError):
            return self._json_error(400, "render_id and rating must be integers")
        if render_id <= 0 or rating not in (-1, 0, 1, 2):
            return self._json_error(400, "invalid render_id or rating (must be -1, 0, 1, or 2)")
        notes = (body.get("notes") or "").strip() or None
        try:
            forge_gallery.set_rating(render_id, rating, notes=notes)  # type: ignore
        except Exception as e:  # noqa: BLE001
            return self._json_error(500, f"set_rating failed: {e}")
        return self._serve_json({"ok": True, "render_id": render_id, "rating": rating})

    def _handle_kill_all(self, body: dict) -> None:
        """Kill every active render job (and its descendants like
        mflux-generate). Safe: never kills the V2 server itself."""
        summary = _kill_all_active()
        return self._serve_json({"ok": True, **summary})

    def _handle_delete_render(self, body: dict) -> None:
        if not GALLERY_AVAILABLE:
            return self._json_error(503, "forge_gallery not available")
        try:
            render_id = int(body.get("render_id") or 0)
        except (TypeError, ValueError):
            return self._json_error(400, "render_id must be an integer")
        if render_id <= 0:
            return self._json_error(400, "invalid render_id")
        try:
            forge_gallery.delete_render(render_id)  # type: ignore
        except Exception as e:  # noqa: BLE001
            return self._json_error(500, f"delete_render failed: {e}")
        return self._serve_json({"ok": True, "render_id": render_id})

    def _404(self) -> None:
        self._json_error(404, "not found")


def _load_schema(name: str) -> dict:
    with (SCHEMA_DIR / name).open() as f:
        return json.load(f)


_USER_HOME = Path(os.path.expanduser("~")).resolve()


def _file_url_for(p: Path | str) -> Optional[str]:
    """Build a URL the browser can use to fetch a file on disk.
    Files inside Forge/ go through the existing /file/ endpoint (relative
    path in URL). Files anywhere else under $HOME go through /file-abs?p=…
    which serves any extension-allowlisted file under the user's home dir.
    Files outside $HOME or non-existent return None."""
    if not p:
        return None
    pp = Path(p) if not isinstance(p, Path) else p
    try:
        rel = pp.resolve().relative_to(ROOT)
        return f"/file/{rel}"
    except (ValueError, OSError):
        pass
    try:
        pp_resolved = pp.resolve()
        pp_resolved.relative_to(_USER_HOME)  # raises if not under $HOME
        from urllib.parse import quote
        return f"/file-abs?p={quote(str(pp_resolved))}"
    except (ValueError, OSError):
        return None


# Filename pattern: NN_{slug}_{pose}.png  (e.g. 01_rhino_standing-alert.png)
# Path pattern:    .../attempts/{slug}/{version}/NN_{slug}_{pose}.png
_FN_RE = re.compile(r"^\d{1,3}_(?P<slug>[a-z0-9][a-z0-9-]*)_(?P<pose>[a-z][a-z0-9-]+)(?:\.transparent)?\.png$", re.IGNORECASE)


def _infer_animal_pose_version(png_path: Path) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """Best-effort inference of (animal_slug, pose_slug, version) from a
    render path. Returns (None, None, None) for paths that don't follow
    our convention."""
    m = _FN_RE.match(png_path.name)
    animal = m.group("slug") if m else None
    pose = m.group("pose") if m else None
    version = None
    # If parent dir name looks like "v1", "v2" etc., capture it
    if png_path.parent.name and png_path.parent.name.startswith("v"):
        try:
            int(png_path.parent.name[1:])
            version = png_path.parent.name
        except ValueError:
            pass
    return (animal, pose, version)


# --- HTML / CSS / JS (single-file embed, matches V1 pattern) ------------

# Shared CSS — both HOME and GALLERY pages use it.
SHARED_CSS = r"""
:root{
  --bg: #1a2014; --bg-deep: #0e1209;
  --surface-1: #2a3220; --surface-2: #3a4530; --surface-3: #4a5740;
  --line: #2a3a20; --line-hi: #5a6a3a;
  --ink: #d8d0b4; --ink-bright: #f5efd5; --ink-dim: #8a8a6a;
  --green: #6ab548; --green-dim: #4a8d3a; --green-deep: #2a5520;
  --blue: #6db4e1; --amber: #f0c447; --rose: #e85067; --gold: #d6a754;
  --shadow: 0 4px 0 var(--bg-deep);
  --shadow-press: 0 1px 0 var(--bg-deep);
  --font-pixel: "Press Start 2P", "Courier New", monospace;
  --font-ui:    "Pixelify Sans", "VT323", "Courier New", monospace;
  --font-mono:  "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
}
@import url('https://fonts.googleapis.com/css2?family=Press+Start+2P&family=Pixelify+Sans:wght@400;500;700&display=swap');
*{box-sizing:border-box}
html,body{background:var(--bg);margin:0}
body{
  min-height:100vh; color:var(--ink); font:16px/1.5 var(--font-ui);
  background-image: repeating-linear-gradient(0deg,
    rgba(255,255,255,0.020) 0, rgba(255,255,255,0.020) 1px,
    transparent 1px, transparent 2px);
  image-rendering: pixelated;
}
::selection{background:var(--green-dim);color:var(--ink-bright)}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-track{background:var(--bg-deep)}
::-webkit-scrollbar-thumb{background:var(--surface-3);border:2px solid var(--bg-deep)}

/* === TOP BAR — pixel banner === */
.topbar{
  background:var(--surface-1); border-bottom:4px solid var(--green-deep);
  padding:14px 24px; display:flex; align-items:center; gap:24px;
}
.brand{
  font-family:var(--font-pixel); font-size:16px; color:var(--green);
  letter-spacing:1px; text-shadow:2px 2px 0 var(--bg-deep);
}
.brand .cursor{color:var(--amber); animation:blink 1s steps(2) infinite}
@keyframes blink{50%{opacity:0}}
.brand .sep{color:var(--ink-dim); margin:0 6px}
.brand .sub{color:var(--gold); font-size:14px}
.nav{margin-left:auto; display:flex; gap:8px}
.nav a{
  font-family:var(--font-pixel); font-size:10px;
  background:var(--surface-2); color:var(--ink); padding:10px 14px;
  border:2px solid var(--line-hi); box-shadow:var(--shadow);
  text-decoration:none; letter-spacing:1px;
}
.nav a:hover{background:var(--surface-3); color:var(--ink-bright)}
.nav a:active{transform:translateY(3px); box-shadow:var(--shadow-press)}
.nav a.current{background:var(--green-deep); color:var(--amber); border-color:var(--green)}
.nav button.kill-nav{
  font-family:var(--font-pixel); font-size:9px; padding:9px 12px;
  background:#3a1414; color:var(--rose); border:2px solid var(--rose);
  box-shadow:var(--shadow); letter-spacing:1px; cursor:pointer; margin-left:4px;
}
.nav button.kill-nav:hover{background:var(--rose); color:#fff; border-color:#fff}
.nav button.kill-nav:active{transform:translateY(3px); box-shadow:var(--shadow-press)}

/* === MAIN CONTAINER === */
.page{max-width:900px; margin:24px auto; padding:0 16px}
.section{margin-bottom:28px}
.section-label{
  font-family:var(--font-pixel); font-size:10px; color:var(--gold);
  letter-spacing:1.5px; margin-bottom:8px; text-shadow:1px 1px 0 var(--bg-deep);
}

/* === FREEFORM INPUT (the big text box) === */
.prompt-box{
  background:var(--bg-deep); border:3px solid var(--green-deep);
  padding:18px 20px; box-shadow:inset 0 0 0 2px var(--bg-deep), var(--shadow);
  position:relative;
}
.prompt-box::before{
  content:">"; position:absolute; left:8px; top:18px;
  color:var(--green); font-family:var(--font-pixel); font-size:14px;
}
.prompt-box textarea{
  width:100%; background:transparent; border:none; outline:none; resize:none;
  color:var(--ink-bright); font-family:var(--font-ui); font-size:18px;
  padding-left:18px; min-height:60px; line-height:1.4;
  caret-color:var(--amber);
}
.prompt-box textarea::placeholder{color:var(--ink-dim)}

/* === QUICK-PICK CHIPS === */
.chips{display:flex; flex-wrap:wrap; gap:10px}
.chip{
  background:var(--surface-2); border:2px solid var(--line-hi);
  padding:10px 14px; box-shadow:var(--shadow); cursor:pointer;
  font-family:var(--font-pixel); font-size:9px; color:var(--ink);
  letter-spacing:1px; display:flex; align-items:center; gap:10px;
  min-width:140px;
}
.chip:hover{background:var(--surface-3); color:var(--ink-bright); border-color:var(--green)}
.chip:active, .chip.armed{transform:translateY(3px); box-shadow:var(--shadow-press); background:var(--green-deep); color:var(--amber)}
.chip .sprite{width:24px; height:24px; image-rendering:pixelated; font-size:22px; line-height:1}
.chip .sprite img{width:24px; height:24px; image-rendering:pixelated; display:block}

/* === RADIO ROWS === */
.row{display:flex; gap:18px; flex-wrap:wrap; align-items:center}
.radio{display:inline-flex; align-items:center; gap:6px; font-family:var(--font-pixel); font-size:9px; color:var(--ink); letter-spacing:1px; cursor:pointer}
.radio input{accent-color:var(--green); transform:scale(1.3)}
.radio.selected{color:var(--amber)}

/* === BIG RENDER BUTTON === */
.btn-big{
  display:block; margin:24px auto; padding:18px 56px;
  font-family:var(--font-pixel); font-size:14px; letter-spacing:2px;
  background:var(--green-deep); color:var(--amber); border:3px solid var(--green);
  box-shadow:var(--shadow); cursor:pointer; text-shadow:2px 2px 0 var(--bg-deep);
}
.btn-big:hover{background:var(--green-dim); color:var(--ink-bright)}
.btn-big:active{transform:translateY(3px); box-shadow:var(--shadow-press)}
.btn-big:disabled{background:var(--surface-2); color:var(--ink-dim); border-color:var(--line); cursor:not-allowed}

/* === TERMINAL === */
.terminal{
  background:#050805; border:3px solid var(--line-hi); padding:14px 16px;
  font-family:var(--font-mono); font-size:13px; color:var(--green);
  min-height:240px; max-height:480px; overflow-y:auto;
  box-shadow:inset 0 0 0 2px #000, 0 0 18px rgba(106,181,72,0.12);
  position:relative;
  background-image:repeating-linear-gradient(0deg,
    rgba(106,181,72,0.06) 0, rgba(106,181,72,0.06) 1px,
    transparent 1px, transparent 3px);
}
.terminal-head{
  display:flex; align-items:center; gap:12px;
  font-family:var(--font-pixel); font-size:10px; color:var(--amber);
  margin-bottom:10px; padding-bottom:8px;
  border-bottom:1px dashed var(--green-deep);
}
.terminal-head .actions{margin-left:auto; display:flex; gap:6px}
.terminal-head button{
  font-family:var(--font-pixel); font-size:8px; padding:4px 8px;
  background:var(--surface-2); color:var(--ink); border:1px solid var(--line-hi);
  cursor:pointer; letter-spacing:1px;
}
.terminal-head button:hover{background:var(--surface-3); color:var(--amber)}
.terminal-head .kill-btn{
  background:#3a1414; color:var(--rose); border:1px solid var(--rose);
  text-shadow:1px 1px 0 #000; padding:4px 10px; margin-left:4px;
}
.terminal-head .kill-btn:hover{background:var(--rose); color:#fff; border-color:#fff}
.terminal-head .kill-btn:active{transform:translateY(1px)}
.term-line{white-space:pre-wrap; word-break:break-word; padding:1px 0}
.term-line.prompt::before{content:"> "; color:var(--green); opacity:0.7}
.term-line.event-decision{color:var(--amber)}
.term-line.event-reasoning{color:var(--ink-bright); padding-left:12px; font-style:italic}
.term-line.event-error{color:var(--rose); font-weight:bold}
.term-line.event-step{color:var(--blue)}
.term-line.event-done{color:var(--green); font-weight:bold; margin-top:8px}
.term-line.event-subject{color:var(--gold); padding-left:12px; white-space:pre-wrap}
.term-cursor{display:inline-block; width:8px; height:14px; background:var(--green); animation:blink 1s steps(2) infinite; vertical-align:middle}

/* === RENDER PAYOFF === */
.payoff{display:none; margin-top:20px; gap:20px}
.payoff.visible{display:grid; grid-template-columns: 1fr 220px}
.payoff img{
  width:100%; max-width:512px; image-rendering:pixelated; image-rendering:crisp-edges;
  border:3px solid var(--green-deep); box-shadow:var(--shadow);
}
.payoff-actions{display:flex; flex-direction:column; gap:10px}
.payoff-actions button, .payoff-actions a{
  font-family:var(--font-pixel); font-size:10px; padding:12px 14px;
  border:2px solid var(--line-hi); box-shadow:var(--shadow); cursor:pointer;
  letter-spacing:1px; text-align:left; background:var(--surface-2); color:var(--ink);
  text-decoration:none; display:block;
}
.payoff-actions button:hover, .payoff-actions a:hover{background:var(--surface-3); color:var(--amber); border-color:var(--green)}
.payoff-actions .master{background:var(--green-deep); color:var(--amber); border-color:var(--green)}
.payoff-actions .flag{background:#553a1a; color:var(--amber); border-color:var(--gold)}

/* === GALLERY === */
.tabs{display:flex; gap:8px; margin-bottom:18px}
.tabs a{
  font-family:var(--font-pixel); font-size:10px; padding:10px 14px;
  background:var(--surface-2); color:var(--ink); border:2px solid var(--line-hi);
  box-shadow:var(--shadow); text-decoration:none; letter-spacing:1px; cursor:pointer;
}
.tabs a.current{background:var(--green-deep); color:var(--amber); border-color:var(--green)}
.grid{display:grid; grid-template-columns:repeat(auto-fill, minmax(180px, 1fr)); gap:14px}
.grid .card{background:var(--surface-1); border:2px solid var(--line); padding:8px; box-shadow:var(--shadow)}
.grid .card img{width:100%; image-rendering:pixelated; image-rendering:crisp-edges; background:#000}
.grid .card .meta{font-family:var(--font-pixel); font-size:9px; color:var(--ink); margin-top:6px; letter-spacing:1px}
.grid .card .meta .pose{color:var(--gold)}
.empty{color:var(--ink-dim); font-style:italic; padding:32px; text-align:center}
"""

# HOME page HTML — the main render screen
HOME_HTML = (r"""<!DOCTYPE html><html><head>
<meta charset="utf-8">
<title>Forge ▸ Madhubani Atelier</title>
<style>""" + SHARED_CSS + r"""</style>
</head>
<body>

<div class="topbar">
  <div class="brand">
    FORGE <span class="sep">▸</span> <span class="sub">MADHUBANI ATELIER</span>
    <span class="cursor">▌</span>
  </div>
  <div class="nav">
    <a href="/" class="current">NEW</a>
    <a href="/gallery">GALLERY</a>
    <a href="http://localhost:8080/" target="_blank">WORKSHOP</a>
    <button class="kill-nav" id="kill-nav-btn" title="Abort every active render subprocess">⏻ KILL</button>
  </div>
</div>

<div class="page">

  <div class="section">
    <div class="section-label">WHAT DO YOU WANT TO MAKE?</div>
    <div class="prompt-box">
      <textarea id="prompt" placeholder="make me a madhubani tiger standing alert..." rows="2"></textarea>
    </div>
  </div>

  <div class="section">
    <div class="section-label">OR PICK AN ANIMAL</div>
    <div class="chips" id="chips"></div>
  </div>

  <div class="section">
    <div class="section-label">OPTIONS</div>
    <div class="row" id="register-row">
      <span style="font-family:var(--font-pixel); font-size:9px; color:var(--ink-dim); letter-spacing:1px">REGISTER:</span>
      <label class="radio selected"><input type="radio" name="register" value="madhubani-contemporary" checked> CONTEMPORARY</label>
      <label class="radio"><input type="radio" name="register" value="madhubani-master-painter"> MASTER-PAINTER</label>
    </div>
    <div class="row" id="steps-row" style="margin-top:10px">
      <span style="font-family:var(--font-pixel); font-size:9px; color:var(--ink-dim); letter-spacing:1px">SPEED:</span>
      <label class="radio selected"><input type="radio" name="steps" value="14" checked> PREVIEW 14</label>
      <label class="radio"><input type="radio" name="steps" value="24"> FINAL 24</label>
    </div>
    <div class="row" id="poses-row" style="margin-top:10px">
      <span style="font-family:var(--font-pixel); font-size:9px; color:var(--ink-dim); letter-spacing:1px">POSES:</span>
      <label class="radio selected"><input type="radio" name="posescope" value="all" checked> ALL FOUR</label>
      <label class="radio"><input type="radio" name="posescope" value="single"> PICK ONE</label>
      <select id="singlepose" style="display:none; font-family:var(--font-pixel); font-size:9px; background:var(--surface-2); color:var(--ink); border:2px solid var(--line-hi); padding:8px"></select>
    </div>
  </div>

  <button class="btn-big" id="render-btn">▶ INSERT COIN TO RENDER</button>

  <div class="section">
    <div class="terminal" id="terminal">
      <div class="terminal-head">
        <span>▣ TERMINAL</span>
        <span style="color:var(--ink-dim); font-size:8px" id="job-id"></span>
        <div class="actions">
          <button id="copy-btn">COPY</button>
          <button id="clear-btn">CLEAR</button>
          <button id="kill-btn" class="kill-btn" title="Abort every active render subprocess (mflux, Ollama). Safe — won't touch the V2 server itself.">⏻ KILL ALL</button>
        </div>
      </div>
      <div id="term-body">
        <div class="term-line" style="color:var(--ink-dim)">press start... awaiting your command.</div>
      </div>
    </div>
  </div>

  <div class="payoff" id="payoff">
    <img id="payoff-img" alt="">
    <div class="payoff-actions">
      <button class="master" id="master-btn">▶ MASTER THIS</button>
      <button class="flag" id="flag-btn">▶ FLAG THIS</button>
      <button id="retry-btn">▶ RETRY (different seed)</button>
      <a id="directive-link" target="_blank">▶ OPEN DIRECTIVE.JSON</a>
    </div>
  </div>

</div>

<script>
// ── State ──
const STATE = {
  selectedAnimal: null,    // slug or null
  selectedPose: null,      // slug or null (only set when "single" chosen)
  register: "madhubani-contemporary",  // reverted default after master-painter destabilized prompts; opt-in for premium
  steps: 14,
  posescope: "all",
  currentJobId: null,
  lastRender: null,        // {animal, pose, image_url, directive_url}
};

// ── Init: load animals + poses, build chips and pose dropdown ──
async function init(){
  const [animalsResp, posesResp] = await Promise.all([
    fetch("/api/animals").then(r=>r.json()),
    fetch("/api/poses").then(r=>r.json()),
  ]);
  const animals = (animalsResp.animals || []).filter(a => a && a.slug);
  const poses = posesResp.poses || [];

  // Build animal chips
  const emojiMap = {
    rhino: "🦏", tiger: "🐅", elephant: "🐘", peacock: "🦚",
    cobra: "🐍", blackbuck: "🦌", "snow-leopard": "❄", macaque: "🐒"
  };
  const chipsEl = document.getElementById("chips");
  animals.forEach(a => {
    const chip = document.createElement("div");
    chip.className = "chip";
    chip.dataset.slug = a.slug;
    const spriteUrl = `/static/sprites/${a.slug}.png`;
    chip.innerHTML = `
      <span class="sprite">
        <img src="${spriteUrl}" onerror="this.replaceWith(document.createTextNode('${emojiMap[a.slug] || '◆'}'))">
      </span>
      <span>${a.slug.toUpperCase().replace(/-/g,' ')}</span>`;
    chip.onclick = () => selectAnimal(a.slug);
    chipsEl.appendChild(chip);
  });

  // Pose dropdown
  const sel = document.getElementById("singlepose");
  poses.forEach(p => {
    const opt = document.createElement("option");
    opt.value = p.slug; opt.textContent = p.slug;
    sel.appendChild(opt);
  });
}

function selectAnimal(slug){
  STATE.selectedAnimal = slug;
  document.querySelectorAll(".chip").forEach(c => c.classList.toggle("armed", c.dataset.slug === slug));
  // Also reflect into the textarea so the user sees the choice
  const pose = STATE.posescope === "single" ? STATE.selectedPose : "all 4 poses";
  document.getElementById("prompt").value = `${slug} — ${pose} — ${STATE.register}`;
}

// ── Radio + dropdown wiring ──
document.addEventListener("change", (e) => {
  if (e.target.name === "register"){
    STATE.register = e.target.value;
    document.querySelectorAll("#register-row .radio").forEach(l => l.classList.toggle("selected", l.querySelector("input").checked));
  }
  if (e.target.name === "steps"){
    STATE.steps = parseInt(e.target.value, 10) || 14;
    document.querySelectorAll("#steps-row .radio").forEach(l => l.classList.toggle("selected", l.querySelector("input").checked));
  }
  if (e.target.name === "posescope"){
    STATE.posescope = e.target.value;
    document.querySelectorAll("#poses-row .radio").forEach(l => l.classList.toggle("selected", l.querySelector("input").checked));
    document.getElementById("singlepose").style.display = e.target.value === "single" ? "" : "none";
  }
  if (e.target.id === "singlepose"){
    STATE.selectedPose = e.target.value;
  }
});

// ── Terminal helpers ──
const term = {
  body: () => document.getElementById("term-body"),
  add(line, cls=""){
    const div = document.createElement("div");
    div.className = "term-line " + cls;
    div.textContent = line;
    this.body().appendChild(div);
    this.body().parentElement.scrollTop = this.body().parentElement.scrollHeight;
  },
  clear(){ this.body().innerHTML = ""; },
  bootMsg(jobId){
    this.clear();
    document.getElementById("job-id").textContent = `job=${jobId}`;
    this.add("──────────────────────────────────────────────", "");
    this.add("ATELIER ONLINE. ENGINE READY.", "event-decision");
    this.add("──────────────────────────────────────────────", "");
  },
};

document.getElementById("clear-btn").onclick = () => term.clear();
document.getElementById("copy-btn").onclick = () => {
  const text = [...document.querySelectorAll(".term-line")].map(l => l.textContent).join("\n");
  navigator.clipboard.writeText(text);
  term.add("[copied to clipboard]", "event-decision");
};
async function killAll(opts){
  opts = opts || {};
  if (opts.confirm !== false && !confirm("KILL every active render subprocess?\n\nThis stops mflux mid-render and any chat-routing call to Ollama. The V2 server itself stays up.")) return null;
  if (opts.echo !== false) term.add("⏻  KILL signal sent...", "event-error");
  const resp = await fetch("/api/kill-all", {method:"POST", body: "{}"});
  const out = await resp.json();
  if (out.ok && opts.echo !== false){
    term.add(`✓ killed ${out.killed_count} process(es): ${(out.killed_job_ids||[]).join(", ") || "(none active)"}`, "event-error");
    const btn = document.getElementById("render-btn");
    if (btn){ btn.disabled = false; btn.textContent = "▶ INSERT COIN TO RENDER"; }
  } else if (!out.ok){
    if (opts.echo !== false) term.add("✗ kill failed: " + (out.error || "unknown"), "event-error");
  }
  return out;
}
document.getElementById("kill-btn").onclick = () => killAll();
const killNavBtn = document.getElementById("kill-nav-btn");
if (killNavBtn) killNavBtn.onclick = () => killAll();

// ── Render button ──
document.getElementById("render-btn").onclick = async () => {
  const prompt = document.getElementById("prompt").value.trim();
  const btn = document.getElementById("render-btn");
  btn.disabled = true; btn.textContent = "RENDERING...";
  document.getElementById("payoff").classList.remove("visible");

  let resp, body;
  if (STATE.selectedAnimal && !looksLikeFreeform(prompt)){
    // Quick-pick path — deterministic
    body = {
      animal: STATE.selectedAnimal,
      pose: STATE.posescope === "single" ? STATE.selectedPose : null,
      register: STATE.register,
      steps: STATE.steps,
    };
    resp = await fetch("/render", {method:"POST", body: JSON.stringify(body)});
  } else if (prompt){
    // Chat path — Ollama. Pass user's explicit pose/register/scope
    // selections so they override anything Ollama might pick.
    body = {
      text: prompt,
      all_poses: STATE.posescope === "all",
      pose: STATE.posescope === "single" ? STATE.selectedPose : null,
      register: STATE.register,
      steps: STATE.steps,
    };
    resp = await fetch("/chat", {method:"POST", body: JSON.stringify(body)});
  } else {
    term.add("Type a prompt or pick an animal first.", "event-error");
    btn.disabled = false; btn.textContent = "▶ INSERT COIN TO RENDER";
    return;
  }

  const {job_id, error} = await resp.json();
  if (error){
    term.add("ERROR: " + error, "event-error");
    btn.disabled = false; btn.textContent = "▶ INSERT COIN TO RENDER";
    return;
  }
  STATE.currentJobId = job_id;
  term.bootMsg(job_id);
  streamEvents(job_id, () => {
    btn.disabled = false; btn.textContent = "▶ INSERT COIN TO RENDER";
  });
};

function looksLikeFreeform(prompt){
  // If user manually edited the prompt to be a real sentence, prefer chat path.
  // Heuristic: contains a verb-like word or is longer than the auto-filled "slug — pose — register"
  if (!prompt) return false;
  if (prompt.length > 60) return true;
  if (/\b(make|give|create|render|i want|please|generate)\b/i.test(prompt)) return true;
  return false;
}

// ── SSE stream ──
function streamEvents(jobId, onDone){
  const es = new EventSource(`/events/${jobId}`);

  es.addEventListener("process.start",  e => term.add(e.data, "event-decision"));
  es.addEventListener("log",            e => term.add(e.data));
  es.addEventListener("render.engine.step", e => {
    const {current, total} = JSON.parse(e.data);
    const bar = "█".repeat(Math.floor(20 * current / total)) + "░".repeat(20 - Math.floor(20 * current / total));
    term.add(`[${bar}] step ${current}/${total}`, "event-step");
  });
  es.addEventListener("render.complete", e => {
    const {image_url, directive_url} = JSON.parse(e.data);
    STATE.lastRender = {image_url, directive_url, animal: STATE.selectedAnimal, pose: STATE.selectedPose};
    document.getElementById("payoff-img").src = image_url + "?t=" + Date.now();
    if (directive_url) document.getElementById("directive-link").href = directive_url;
    document.getElementById("payoff").classList.add("visible");
    term.add("✓ RENDER COMPLETE — image loaded above.", "event-done");
  });
  es.addEventListener("error", e => term.add("ERROR: " + (e.data || "(stream error)"), "event-error"));
  es.addEventListener("done", e => {
    es.close();
    onDone && onDone();
  });
  es.onerror = () => { es.close(); onDone && onDone(); };
}

// ── Master / Flag / Retry buttons ──
document.getElementById("master-btn").onclick = async () => {
  const r = STATE.lastRender; if (!r || !r.animal || !r.pose){ term.add("Need both animal and pose to master (try a single-pose render first).", "event-error"); return; }
  const resp = await fetch("/promote", {method:"POST", body: JSON.stringify({animal: r.animal, pose: r.pose})});
  const {job_id} = await resp.json();
  streamEvents(job_id, () => term.add("✓ Mastered.", "event-done"));
};
document.getElementById("flag-btn").onclick = async () => {
  const r = STATE.lastRender; if (!r || !r.animal || !r.pose){ term.add("Need both animal and pose to flag.", "event-error"); return; }
  const notes = prompt("Flag notes — what went wrong / what to try later?", "");
  if (notes === null) return;
  const resp = await fetch("/flag", {method:"POST", body: JSON.stringify({animal: r.animal, pose: r.pose, notes})});
  const {job_id} = await resp.json();
  streamEvents(job_id, () => term.add("⚑ Flagged.", "event-decision"));
};
document.getElementById("retry-btn").onclick = async () => {
  const r = STATE.lastRender; if (!r){ term.add("Nothing to retry.", "event-error"); return; }
  const body = {animal: r.animal, pose: r.pose, register: STATE.register, steps: STATE.steps, retry: true};
  const resp = await fetch("/render", {method:"POST", body: JSON.stringify(body)});
  const {job_id} = await resp.json();
  STATE.currentJobId = job_id;
  term.bootMsg(job_id);
  document.getElementById("payoff").classList.remove("visible");
  streamEvents(job_id);
};

init();
</script>
</body></html>
""")

# GALLERY page — every captured render with ratings + filters
GALLERY_HTML = (r"""<!DOCTYPE html><html><head>
<meta charset="utf-8">
<title>Forge ▸ Gallery</title>
<style>""" + SHARED_CSS + r"""
/* === GALLERY-specific === */
.stats-bar{
  display:flex; gap:18px; flex-wrap:wrap; margin-bottom:18px;
  font-family:var(--font-pixel); font-size:9px; letter-spacing:1px; color:var(--ink);
}
.stats-bar .stat{background:var(--surface-1); padding:8px 12px; border:2px solid var(--line-hi); box-shadow:var(--shadow)}
.stats-bar .stat b{color:var(--amber); margin-left:6px}

.filter-row{display:flex; gap:8px; flex-wrap:wrap; margin-bottom:18px}
.filter-chip{
  font-family:var(--font-pixel); font-size:9px; letter-spacing:1px; cursor:pointer;
  background:var(--surface-2); color:var(--ink); padding:8px 14px;
  border:2px solid var(--line-hi); box-shadow:var(--shadow);
}
.filter-chip:hover{background:var(--surface-3); color:var(--amber)}
.filter-chip.current{background:var(--green-deep); color:var(--amber); border-color:var(--green)}

.render-grid{display:grid; grid-template-columns:repeat(auto-fill, minmax(260px, 1fr)); gap:16px}
.render-card{
  background:var(--surface-1); border:2px solid var(--line); padding:10px;
  box-shadow:var(--shadow); display:flex; flex-direction:column;
}
.render-card .thumb{
  width:100%; aspect-ratio:1; background:#000; border:2px solid var(--bg-deep);
  image-rendering:pixelated; image-rendering:crisp-edges; object-fit:contain;
}
.render-card.rating-1 { border-color: var(--green-dim) }
.render-card.rating-2 { border-color: var(--amber); box-shadow: 0 4px 0 var(--bg-deep), 0 0 0 1px var(--amber) }
.render-card.rating--1 { opacity: 0.55 }

.render-meta{
  font-family:var(--font-pixel); font-size:9px; color:var(--ink); letter-spacing:1px;
  margin-top:8px; line-height:1.5;
}
.render-meta .animal{color:var(--amber)}
.render-meta .pose{color:var(--gold)}
.render-meta .seed{color:var(--ink-dim); font-size:8px}
.render-meta .subj{color:var(--ink-dim); font-size:8px; margin-top:4px; font-family:var(--font-mono); letter-spacing:0; white-space:normal; word-break:break-word; line-height:1.3}

.rate-row{display:flex; gap:6px; margin-top:10px; flex-wrap:wrap}
.rate-btn{
  flex:1; min-width:48px; padding:8px 6px; font-family:var(--font-pixel); font-size:11px;
  background:var(--surface-2); color:var(--ink); border:2px solid var(--line-hi);
  box-shadow:var(--shadow); cursor:pointer; text-align:center;
}
.rate-btn:hover{background:var(--surface-3); color:var(--amber)}
.rate-btn.active.r--1 {background:#5a2a2a; color:var(--rose); border-color:var(--rose)}
.rate-btn.active.r-0  {background:var(--surface-3); color:var(--ink-bright); border-color:var(--line-hi)}
.rate-btn.active.r-1  {background:var(--green-deep); color:var(--amber); border-color:var(--green)}
.rate-btn.active.r-2  {background:#553a1a; color:var(--amber); border-color:var(--amber)}

.tiny-actions{margin-top:8px; display:flex; gap:6px; font-family:var(--font-pixel); font-size:8px}
.tiny-actions a, .tiny-actions button{
  background:transparent; color:var(--ink-dim); padding:4px 8px;
  border:1px solid var(--line); cursor:pointer; text-decoration:none; letter-spacing:1px;
}
.tiny-actions a:hover, .tiny-actions button:hover{color:var(--amber); border-color:var(--line-hi)}
</style>
</head>
<body>

<div class="topbar">
  <div class="brand">
    FORGE <span class="sep">▸</span> <span class="sub">GALLERY</span>
    <span class="cursor">▌</span>
  </div>
  <div class="nav">
    <a href="/">NEW</a>
    <a href="/gallery" class="current">GALLERY</a>
    <a href="http://localhost:8080/" target="_blank">WORKSHOP</a>
    <button class="kill-nav" id="kill-nav-btn" title="Abort every active render subprocess">⏻ KILL</button>
  </div>
</div>

<div class="page">

  <div class="section">
    <div class="section-label">RENDER LEDGER</div>
    <div class="stats-bar" id="stats-bar"><span class="stat">LOADING…</span></div>
    <div id="db-diagnostics" style="font-family:var(--font-mono); font-size:11px; color:var(--ink-dim); margin-top:8px; padding:8px; background:var(--bg-deep); border:1px solid var(--line); white-space:pre-wrap; word-break:break-word"></div>
  </div>

  <div class="section">
    <div class="section-label">FILTER BY RATING</div>
    <div class="filter-row" id="filters">
      <button class="filter-chip current" data-rating="all">ALL</button>
      <button class="filter-chip" data-rating="2">⭐ FAVORITE</button>
      <button class="filter-chip" data-rating="1">👍 LIKE</button>
      <button class="filter-chip" data-rating="0">— UNRATED</button>
      <button class="filter-chip" data-rating="-1">👎 DISLIKE</button>
    </div>
  </div>

  <div id="grid-wrap">
    <div class="empty" style="font-family:var(--font-pixel); font-size:10px; color:var(--ink-dim)">Loading renders…</div>
  </div>

</div>

<script>
let RENDERS = []; let CURRENT_FILTER = "all";

async function loadAll(){
  const diag = document.getElementById("db-diagnostics");
  try {
    const [statsRes, rendersRes] = await Promise.all([
      fetch("/api/gallery-stats"),
      fetch("/api/renders"),
    ]);
    const stats = await statsRes.json();
    const data = await rendersRes.json();
    if (data.error){
      document.getElementById("stats-bar").innerHTML = `<span class="stat" style="color:var(--rose)">RENDERS ENDPOINT ERROR</span>`;
      diag.style.color = "var(--rose)";
      diag.textContent = "renders endpoint error: " + data.error;
      return;
    }
    RENDERS = data.renders || [];
    paintStats(stats);
    paintDiagnostics(stats);
    paintGrid();
  } catch (e){
    // Visible error instead of silent LOADING… forever
    document.getElementById("stats-bar").innerHTML = `<span class="stat" style="color:var(--rose)">FETCH FAILED — see diagnostics below</span>`;
    diag.style.color = "var(--rose)";
    diag.textContent = "loadAll() threw: " + (e.message || e) + "\nCheck the server terminal for the underlying Python traceback.";
  }
}

function paintStats(s){
  const el = document.getElementById("stats-bar");
  if (!s.available){
    el.innerHTML = `<span class="stat" style="color:var(--rose)">forge_gallery.db UNAVAILABLE</span>`;
    return;
  }
  el.innerHTML = `
    <span class="stat">TOTAL <b>${s.total}</b></span>
    <span class="stat">⭐ FAV <b>${s.favorite}</b></span>
    <span class="stat">👍 LIKE <b>${s.like}</b></span>
    <span class="stat">— UNRATED <b>${s.unrated}</b></span>
    <span class="stat">👎 DISLIKE <b>${s.dislike}</b></span>
  `;
}

function paintDiagnostics(s){
  const diag = document.getElementById("db-diagnostics");
  if (!s.available){
    diag.style.color = "var(--rose)";
    diag.textContent = "forge_gallery unavailable — " + (s.reason || "unknown") +
      "\n\nFix: ensure ~/.forge/gallery.db exists. Try running:\n  python3 -c 'import sys; sys.path.insert(0, \"bin\"); import forge_gallery; forge_gallery.init_db(); print(\"created:\", forge_gallery.DB_PATH)'";
    return;
  }
  const lines = [
    `db_path: ${s.db_path}`,
    `total rows across all engines: ${s.total}`,
    `── per-engine breakdown ──`,
  ];
  const eng = s.by_engine || {};
  const keys = Object.keys(eng).sort((a,b) => eng[b] - eng[a]);
  if (keys.length === 0){
    lines.push("  (no rows captured yet — first render with forge.py engine render will populate this)");
  } else {
    keys.forEach(k => lines.push(`  ${k.padEnd(28)} ${eng[k]}`));
  }
  diag.style.color = "var(--ink-dim)";
  diag.textContent = lines.join("\n");
}

function paintGrid(){
  const el = document.getElementById("grid-wrap");
  let items = RENDERS;
  if (CURRENT_FILTER !== "all"){
    const r = parseInt(CURRENT_FILTER, 10);
    items = items.filter(x => (x.rating || 0) === r);
  }
  if (!items.length){
    el.innerHTML = `<div class="empty" style="font-family:var(--font-pixel); font-size:10px; color:var(--ink-dim)">No renders match this filter.</div>`;
    return;
  }
  el.innerHTML = `<div class="render-grid">` + items.map(renderCard).join("") + `</div>`;
  // Wire up rate buttons
  document.querySelectorAll(".rate-btn").forEach(btn => {
    btn.onclick = async () => {
      const id = parseInt(btn.dataset.id, 10);
      const r  = parseInt(btn.dataset.rating, 10);
      const cur = RENDERS.find(x => x.id === id);
      // Toggle: clicking active rating clears (sends 0)
      const send = (cur && cur.rating === r) ? 0 : r;
      const resp = await fetch("/api/rate", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({render_id: id, rating: send}),
      });
      const out = await resp.json();
      if (!out.ok){ alert("Rate failed: " + (out.error||"unknown")); return; }
      if (cur) cur.rating = send;
      // Refresh stats + repaint just this card row
      const sres = await fetch("/api/gallery-stats");
      paintStats(await sres.json());
      paintGrid();
    };
  });
  // Delete buttons
  document.querySelectorAll("[data-action='delete-render']").forEach(btn => {
    btn.onclick = async () => {
      const id = parseInt(btn.dataset.id, 10);
      if (!confirm("Remove this render from the gallery DB? (the PNG file stays on disk)")) return;
      const resp = await fetch("/api/delete-render", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({render_id: id}),
      });
      const out = await resp.json();
      if (!out.ok){ alert("Delete failed: " + (out.error||"unknown")); return; }
      RENDERS = RENDERS.filter(x => x.id !== id);
      const sres = await fetch("/api/gallery-stats"); paintStats(await sres.json());
      paintGrid();
    };
  });
}

function renderCard(r){
  const animal = (r.animal || "?").toUpperCase().replace(/-/g," ");
  const pose   = (r.pose   || "?").toUpperCase();
  const ver    = r.version || "";
  const seed   = r.seed ?? "?";
  const tsLine = r.ts ? new Date(r.ts*1000).toLocaleString() : "";
  const thumb  = r.url ? `<img class="thumb" src="${r.url}" alt="${animal}" onerror="this.style.opacity=0.3">` : `<div class="thumb" style="display:flex;align-items:center;justify-content:center;color:var(--rose);font-family:var(--font-pixel);font-size:9px">FILE MISSING</div>`;
  const ratingClass = `rating-${r.rating || 0}`;
  const btn = (val, label) => `<button class="rate-btn r-${val} ${r.rating===val?'active':''}" data-id="${r.id}" data-rating="${val}">${label}</button>`;
  const dirLink = r.directive_url ? `<a href="${r.directive_url}" target="_blank">DIRECTIVE</a>` : "";
  return `
    <div class="render-card ${ratingClass}">
      <a href="${r.url}" target="_blank">${thumb}</a>
      <div class="render-meta">
        <span class="animal">${animal}</span> · <span class="pose">${pose}</span>
        ${ver ? ` · <span class="seed">${ver.toUpperCase()}</span>`:""}
        <br><span class="seed">seed ${seed}  ·  ${tsLine}</span>
        <div class="subj">${escapeHtml(r.subject_preview || "")}</div>
      </div>
      <div class="rate-row">
        ${btn(-1, "👎")}
        ${btn(0,  "—")}
        ${btn(1,  "👍")}
        ${btn(2,  "⭐")}
      </div>
      <div class="tiny-actions">
        ${dirLink}
        <button data-action="delete-render" data-id="${r.id}">DELETE</button>
      </div>
    </div>
  `;
}

function escapeHtml(s){
  return (s||"").replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
}

document.querySelectorAll(".filter-chip").forEach(b => b.onclick = () => {
  CURRENT_FILTER = b.dataset.rating;
  document.querySelectorAll(".filter-chip").forEach(x => x.classList.toggle("current", x === b));
  paintGrid();
});

// KILL ALL — from GALLERY page (no terminal here; alert summary instead)
const killNavBtn = document.getElementById("kill-nav-btn");
if (killNavBtn) killNavBtn.onclick = async () => {
  if (!confirm("KILL every active render subprocess?\n\nThis stops mflux mid-render and any chat-routing call to Ollama. The V2 server itself stays up.")) return;
  const resp = await fetch("/api/kill-all", {method:"POST", body: "{}"});
  const out = await resp.json();
  if (out.ok){
    alert(`Killed ${out.killed_count} process(es)` + (out.killed_count ? ":\n  " + (out.killed_job_ids||[]).join("\n  ") : ""));
  } else {
    alert("Kill failed: " + (out.error || "unknown"));
  }
};

loadAll();
</script>
</body></html>
""")


# --- Main ---------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description="Forge Web V2 — Madhubani Atelier (NES mode)")
    p.add_argument("--port", type=int, default=int(os.environ.get("FORGE_V2_PORT", 8081)))
    p.add_argument("--bind", default=os.environ.get("FORGE_V2_BIND", "127.0.0.1"))
    p.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    args = p.parse_args()

    SPRITES_DIR.mkdir(parents=True, exist_ok=True)

    httpd = ThreadingHTTPServer((args.bind, args.port), V2Handler)
    url = f"http://{args.bind}:{args.port}/"
    sys.stderr.write(f"\n╔══════════════════════════════════════════════════════════════╗\n")
    sys.stderr.write(  f"║  FORGE ▸ MADHUBANI ATELIER (V2)                              ║\n")
    sys.stderr.write(  f"║  → {url:<60}║\n")
    sys.stderr.write(  f"║  legacy workshop still at http://localhost:8080/             ║\n")
    sys.stderr.write(  f"╚══════════════════════════════════════════════════════════════╝\n\n")

    if not args.no_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        sys.stderr.write("\n  Shutting down V2.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
