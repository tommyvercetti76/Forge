"""Forge Gallery — SQLite store for renders + ratings + smart suggestions.

Every successful `forge engine render` writes one row into ~/.forge/gallery.db.
The user rates renders via the web UI; over time the system learns which
configs (seed, LoRA scale, guidance, refine, hi-res) earn the highest ratings
per engine, and surfaces those as smart suggestions for new renders.

This is config learning, not model fine-tuning — we don't update FLUX weights.
We learn YOUR preferred parameters.

Schema:
  renders   — one row per render with the full directive metadata
  ratings   — one row per rated render (-1 / 0 / 1 / 2 = dislike / none / like / favorite)
  tags      — optional thematic tags per render
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

# State / config root — same convention as forge_runtime.FORGE_STATE_HOME
_FORGE_STATE = Path(os.environ.get("FORGE_STATE_HOME", str(Path.home() / ".forge")))
DB_PATH = _FORGE_STATE / "gallery.db"

# Rating constants
RATING_NONE = 0
RATING_DISLIKE = -1
RATING_LIKE = 1
RATING_FAVORITE = 2
RATING_LABELS = {-1: "dislike", 0: "—", 1: "like", 2: "favorite"}
RATING_EMOJI = {-1: "👎", 0: "—", 1: "👍", 2: "⭐"}

_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    """Create tables + indices if they don't exist. Idempotent."""
    with _lock, _connect() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS renders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts INTEGER NOT NULL,
                engine TEXT NOT NULL,
                recipe TEXT,
                subject TEXT,
                seed INTEGER,
                guidance REAL,
                refine INTEGER DEFAULT 0,
                hi_res INTEGER DEFAULT 0,
                ultra_res INTEGER DEFAULT 0,
                width INTEGER,
                height INTEGER,
                lora_stack TEXT,         -- JSON array of {path, scale}
                config_json TEXT,        -- JSON of full engine config
                directive_json TEXT,     -- path to .directive.json sidecar
                png_path TEXT NOT NULL,
                png_bytes INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_renders_engine ON renders(engine);
            CREATE INDEX IF NOT EXISTS idx_renders_recipe ON renders(recipe);
            CREATE INDEX IF NOT EXISTS idx_renders_ts ON renders(ts DESC);

            CREATE TABLE IF NOT EXISTS ratings (
                render_id INTEGER PRIMARY KEY REFERENCES renders(id) ON DELETE CASCADE,
                rating INTEGER NOT NULL DEFAULT 0,
                notes TEXT,
                rated_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ratings_rating ON ratings(rating);

            CREATE TABLE IF NOT EXISTS tags (
                render_id INTEGER REFERENCES renders(id) ON DELETE CASCADE,
                tag TEXT NOT NULL,
                PRIMARY KEY (render_id, tag)
            );
            CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
        """)


def add_render(
    *,
    engine: str,
    subject: str,
    png_path: Path | str,
    recipe: str | None = None,
    seed: int | None = None,
    guidance: float | None = None,
    refine: bool = False,
    hi_res: bool = False,
    ultra_res: bool = False,
    width: int | None = None,
    height: int | None = None,
    lora_stack: list[dict[str, Any]] | None = None,
    config: dict[str, Any] | None = None,
    directive_json: Path | str | None = None,
) -> int:
    """Insert a render row. Returns the new render id."""
    init_db()
    png = Path(png_path)
    png_bytes = png.stat().st_size if png.exists() else None
    with _lock, _connect() as conn:
        cur = conn.execute(
            """INSERT INTO renders
               (ts, engine, recipe, subject, seed, guidance, refine, hi_res, ultra_res,
                width, height, lora_stack, config_json, directive_json, png_path, png_bytes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                int(time.time()),
                engine,
                recipe,
                subject,
                int(seed) if seed is not None else None,
                float(guidance) if guidance is not None else None,
                1 if refine else 0,
                1 if hi_res else 0,
                1 if ultra_res else 0,
                int(width) if width else None,
                int(height) if height else None,
                json.dumps(lora_stack or []),
                json.dumps(config or {}, default=str),
                str(directive_json) if directive_json else None,
                str(png),
                png_bytes,
            ),
        )
        return int(cur.lastrowid)


def list_renders(
    *,
    engine: str | None = None,
    recipe: str | None = None,
    rating: int | None = None,
    limit: int = 60,
    offset: int = 0,
    order_by: str = "ts_desc",
) -> list[dict[str, Any]]:
    """Return a list of render rows joined with their ratings.

    rating filter: None = all, otherwise filter by exact rating value.
    order_by: ts_desc | ts_asc | rating_desc.
    """
    init_db()
    sql = """
        SELECT r.*, COALESCE(rt.rating, 0) AS rating, rt.notes, rt.rated_at
        FROM renders r
        LEFT JOIN ratings rt ON rt.render_id = r.id
        WHERE 1=1
    """
    params: list[Any] = []
    if engine:
        sql += " AND r.engine = ?"
        params.append(engine)
    if recipe:
        sql += " AND r.recipe = ?"
        params.append(recipe)
    if rating is not None:
        sql += " AND COALESCE(rt.rating, 0) = ?"
        params.append(int(rating))
    if order_by == "ts_asc":
        sql += " ORDER BY r.ts ASC"
    elif order_by == "rating_desc":
        sql += " ORDER BY rating DESC, r.ts DESC"
    else:
        sql += " ORDER BY r.ts DESC"
    sql += " LIMIT ? OFFSET ?"
    params.extend([int(limit), int(offset)])
    with _lock, _connect() as conn:
        return [_row_to_dict(row) for row in conn.execute(sql, params).fetchall()]


def get_render(render_id: int) -> dict[str, Any] | None:
    init_db()
    with _lock, _connect() as conn:
        row = conn.execute(
            """SELECT r.*, COALESCE(rt.rating, 0) AS rating, rt.notes, rt.rated_at
               FROM renders r
               LEFT JOIN ratings rt ON rt.render_id = r.id
               WHERE r.id = ?""",
            (int(render_id),),
        ).fetchone()
        if row is None:
            return None
        return _row_to_dict(row)


def set_rating(render_id: int, rating: int, notes: str | None = None) -> None:
    if rating not in {-1, 0, 1, 2}:
        raise ValueError(f"rating must be one of -1,0,1,2 (got {rating})")
    init_db()
    with _lock, _connect() as conn:
        conn.execute(
            """INSERT INTO ratings (render_id, rating, notes, rated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(render_id) DO UPDATE SET
                   rating = excluded.rating,
                   notes = excluded.notes,
                   rated_at = excluded.rated_at""",
            (int(render_id), int(rating), notes, int(time.time())),
        )


def delete_render(render_id: int) -> None:
    init_db()
    with _lock, _connect() as conn:
        conn.execute("DELETE FROM renders WHERE id = ?", (int(render_id),))


def stats() -> dict[str, Any]:
    """Aggregate counts for the gallery header."""
    init_db()
    with _lock, _connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS n FROM renders").fetchone()["n"]
        by_engine = {
            row["engine"]: row["n"]
            for row in conn.execute(
                "SELECT engine, COUNT(*) AS n FROM renders GROUP BY engine ORDER BY n DESC"
            ).fetchall()
        }
        rated = conn.execute(
            "SELECT COALESCE(rating, 0) AS r, COUNT(*) AS n FROM ratings GROUP BY r"
        ).fetchall()
        by_rating = {RATING_LABELS[r["r"]]: r["n"] for r in rated}
    return {"total": total, "by_engine": by_engine, "by_rating": by_rating}


def top_rated_config(engine: str, *, min_rating: int = 1, limit: int = 10) -> dict[str, Any] | None:
    """Return the 'best config' summary for an engine, derived from rated renders.

    This is the SMART-SUGGESTION primitive: given an engine, find what configs
    earned ratings of `like` (1) or `favorite` (2) and report the modal /
    median values across them.

    Returns None if not enough rated data exists to suggest anything yet.
    """
    init_db()
    with _lock, _connect() as conn:
        rows = conn.execute(
            """SELECT r.*, rt.rating
               FROM renders r
               INNER JOIN ratings rt ON rt.render_id = r.id
               WHERE r.engine = ? AND rt.rating >= ?
               ORDER BY rt.rating DESC, r.ts DESC
               LIMIT ?""",
            (engine, int(min_rating), int(limit)),
        ).fetchall()
    if len(rows) < 2:
        return None
    # Aggregate: modal seed family, modal recipe, average guidance, ratios for
    # refine/hi_res. "Modal" used loosely — we report the most-common bucket.
    seeds = sorted(r["seed"] for r in rows if r["seed"] is not None)
    guidances = [r["guidance"] for r in rows if r["guidance"] is not None]
    recipes = [r["recipe"] for r in rows if r["recipe"]]
    refine_on = sum(1 for r in rows if r["refine"])
    hi_res_on = sum(1 for r in rows if r["hi_res"])
    ultra_res_on = sum(1 for r in rows if r["ultra_res"])

    suggestion = {
        "engine": engine,
        "sample_size": len(rows),
        "favorites_count": sum(1 for r in rows if r["rating"] >= 2),
        "likes_count": sum(1 for r in rows if r["rating"] == 1),
        # Seed family — report range so user can vary within it
        "seed_range": [seeds[0], seeds[-1]] if seeds else None,
        "seed_modal": _modal(seeds, bucket_size=10) if seeds else None,
        # Average guidance, rounded to 0.5
        "guidance_avg": round(sum(guidances) / len(guidances) * 2) / 2 if guidances else None,
        # Booleans → ratio
        "refine_ratio": refine_on / len(rows),
        "hi_res_ratio": hi_res_on / len(rows),
        "ultra_res_ratio": ultra_res_on / len(rows),
        # Top-rated recipes (most-frequent among rated)
        "top_recipes": _top_n([r for r in recipes], 3),
        # Generated human-readable summary line
        "summary": "",
    }
    parts: list[str] = []
    if suggestion["seed_modal"] is not None:
        parts.append(f"seed family ~{suggestion['seed_modal']}")
    if suggestion["guidance_avg"] is not None:
        parts.append(f"guidance ~{suggestion['guidance_avg']}")
    if suggestion["refine_ratio"] >= 0.6:
        parts.append("refine ON")
    elif suggestion["refine_ratio"] <= 0.2:
        parts.append("refine OFF")
    if suggestion["hi_res_ratio"] >= 0.6:
        parts.append("hi-res ON")
    if suggestion["ultra_res_ratio"] >= 0.6:
        parts.append("ultra-res ON")
    if suggestion["top_recipes"]:
        top = suggestion["top_recipes"][0]
        parts.append(f"recipe: {top}")
    suggestion["summary"] = (
        f"Based on {suggestion['sample_size']} rated {engine} renders "
        f"({suggestion['favorites_count']} ⭐, {suggestion['likes_count']} 👍): "
        + " · ".join(parts)
        if parts else
        f"Based on {suggestion['sample_size']} rated renders, no clear pattern yet."
    )
    return suggestion


def _modal(values: list[int], *, bucket_size: int = 10) -> int | None:
    """Approximate modal value by bucketing into N-wide ranges."""
    if not values:
        return None
    buckets: dict[int, int] = {}
    for v in values:
        b = (v // bucket_size) * bucket_size
        buckets[b] = buckets.get(b, 0) + 1
    best_bucket = max(buckets, key=lambda k: buckets[k])
    return best_bucket + bucket_size // 2


def _top_n(values: list[str], n: int) -> list[str]:
    """Return top-N most-frequent values, ordered by frequency desc."""
    if not values:
        return []
    counts: dict[str, int] = {}
    for v in values:
        counts[v] = counts.get(v, 0) + 1
    return sorted(counts, key=lambda k: counts[k], reverse=True)[:n]


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """Convert a SQLite row to a JSON-safe dict, parsing JSON columns."""
    d = dict(row)
    for key in ("lora_stack", "config_json"):
        if d.get(key):
            try:
                d[key] = json.loads(d[key])
            except (ValueError, TypeError):
                pass
    return d


# ────────────────────────────────────────────────────────────────────────────
# Auto-capture helper — called from cmd_engine_render after a successful render.
# ────────────────────────────────────────────────────────────────────────────


def capture_directive(directive: Any, png_path: Path | str, *, recipe: str | None = None,
                       refine: bool = False, hi_res: bool = False, ultra_res: bool = False,
                       guidance_override: float | None = None,
                       width: int | None = None, height: int | None = None,
                       lora_stack: list[dict[str, Any]] | None = None,
                       directive_json: Path | str | None = None) -> int:
    """Convenience: given a Directive object (or dict) and the output path,
    insert a renders row with everything we can recover. Returns the new id.

    Caller is responsible for passing recipe/refine/hi_res/ultra_res/etc since
    the Directive doesn't carry them — they come from the CLI args.
    """
    # Accept either a Directive dataclass or its dict form
    if hasattr(directive, "to_dict"):
        d = directive.to_dict()
    elif isinstance(directive, dict):
        d = directive
    else:
        d = {"engine": "?", "config": {}, "seed": None, "positive": ""}
    runtime = d.get("runtime", {}) or {}
    return add_render(
        engine=str(d.get("engine") or "?"),
        subject=_extract_subject(d),
        png_path=png_path,
        recipe=recipe,
        seed=d.get("seed"),
        guidance=guidance_override if guidance_override is not None else runtime.get("guidance"),
        refine=refine,
        hi_res=hi_res,
        ultra_res=ultra_res,
        width=width,
        height=height,
        lora_stack=lora_stack,
        config=d.get("config"),
        directive_json=directive_json,
    )


def _extract_subject(directive_dict: dict[str, Any]) -> str:
    """Pull the user-facing subject text out of a directive's nested config."""
    config = directive_dict.get("config") or {}
    if not isinstance(config, dict):
        return ""
    # Nested style: config.subject.subject
    subj = config.get("subject")
    if isinstance(subj, dict):
        return str(subj.get("subject") or "")[:500]
    if isinstance(subj, str):
        return subj[:500]
    return ""
