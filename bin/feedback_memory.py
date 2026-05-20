#!/usr/bin/env python3
"""Phase D.1 + D.2 — feedback memory for the Art Reasoning Engine.

Records every render attempt (and the engine's reasoning about it) into an
append-only JSONL ledger so the prompt distribution can self-improve over
time. Pairs with C.1 (best_of_n) and C.2 (art_reasoning_engine) — the
reasoning loop calls `RunsWriter.record_attempt` once per attempt; the
mining job `forge madhubani learn` reads the ledger and surfaces winning
prompts per (species, pose, density) into a human-readable digest.

JSONL schema (forge.run_attempt.v1):

  {
    "schema": "forge.run_attempt.v1",
    "ts": "2026-05-20T14:00:00Z",
    "session_id": "<uuid4>",
    "animal_slug": "rhino",
    "pose_slug": "standing-alert",
    "attempt": 1,
    "seed": 8201,
    "prompt": "<full subject string>",
    "prompt_hash": "sha256:abc...",
    "model": "z-image-turbo|flux2-klein-4b|...",
    "composite": 0.7056,
    "rubric_pass_fraction": 0.857,
    "clip_likeness_probability": 0.4782,
    "auto_qc_pass": false,
    "active_check_count": 7,
    "pass_count": 6,
    "failed_checks": ["color_floor"],
    "weakest_dimension": "color_floor",
    "boost_applied": "URGENT PALETTE FIX: ...",
    "accepted": false,
    "render_path": "generated/.../foo.png"
  }

Storage layout:
  brand/madhubani/learning/runs.jsonl                  ← canonical ledger
  brand/madhubani/learning/species_winning_prompts.md  ← D.2 mining output
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import sys
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
LEARNING_DIR = ROOT / "brand/madhubani/learning"
RUNS_PATH = LEARNING_DIR / "runs.jsonl"
WINNING_PATH = LEARNING_DIR / "species_winning_prompts.md"

SCHEMA = "forge.run_attempt.v1"


@dataclass
class RunAttempt:
    """One row in runs.jsonl. Build via the constructor — RunsWriter.record_attempt
    converts a C.1 best_of_n winner + the C.2 engine state into one of these."""
    animal_slug: str
    pose_slug: str | None
    attempt: int
    seed: int | None
    prompt: str
    composite: float
    rubric_pass_fraction: float
    clip_likeness_probability: float | None
    auto_qc_pass: bool
    active_check_count: int
    pass_count: int
    failed_checks: list[str]
    weakest_dimension: str | None
    boost_applied: str | None
    accepted: bool
    render_path: str | None = None
    model: str | None = None
    session_id: str = ""
    ts: str = ""
    prompt_hash: str = ""
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        if not self.ts:
            self.ts = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not self.prompt_hash:
            self.prompt_hash = "sha256:" + hashlib.sha256(self.prompt.encode("utf-8")).hexdigest()


class RunsWriter:
    """Append-only JSONL writer. One writer per reasoning-loop session;
    session_id is shared across all attempts so D.2 can group them."""

    def __init__(self, runs_path: Path = RUNS_PATH, *, session_id: str | None = None) -> None:
        self.runs_path = runs_path
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.runs_path.parent.mkdir(parents=True, exist_ok=True)

    def record_attempt(self, attempt: RunAttempt) -> None:
        """Append one attempt to the ledger. Atomic-ish via append-only writes;
        if the process crashes mid-line the worst case is one partial line at
        the tail of the file, which RunsReader filters out."""
        attempt.session_id = self.session_id
        line = json.dumps(asdict(attempt), separators=(",", ":"), ensure_ascii=False)
        with self.runs_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    @classmethod
    def from_reasoning_result(
        cls,
        result: dict,
        *,
        animal_slug: str,
        pose_slug: str | None = None,
        model: str | None = None,
        writer: "RunsWriter | None" = None,
    ) -> "RunsWriter":
        """Convert the dict returned by `art_reasoning_engine.render_with_reasoning`
        into a sequence of RunAttempt rows and append them all. Returns the
        writer so the caller can keep the session_id for follow-up."""
        w = writer or cls()
        attempts = result.get("attempts", [])
        accepted_final = bool(result.get("accepted"))
        for i, attempt_dict in enumerate(attempts):
            winner = attempt_dict.get("winner", {})
            is_final = (i == len(attempts) - 1)
            row = RunAttempt(
                animal_slug=animal_slug,
                pose_slug=pose_slug,
                attempt=int(attempt_dict.get("attempt", i + 1)),
                seed=winner.get("seed"),
                prompt=str(attempt_dict.get("prompt", "")),
                composite=float(winner.get("composite", 0.0)),
                rubric_pass_fraction=float(winner.get("rubric_pass_fraction", 0.0)),
                clip_likeness_probability=winner.get("clip_likeness_probability"),
                auto_qc_pass=bool(winner.get("auto_qc_pass", False)),
                active_check_count=int(winner.get("active_check_count", 0)),
                pass_count=int(winner.get("pass_count", 0)),
                failed_checks=list(winner.get("qc_summary", {}).get("failed_checks", [])),
                weakest_dimension=attempt_dict.get("weakest_check"),
                boost_applied=attempt_dict.get("boost_clause_used_for_next_attempt"),
                accepted=(is_final and accepted_final),
                render_path=winner.get("path"),
                model=model,
            )
            w.record_attempt(row)
        return w


class RunsReader:
    """Iterate the JSONL ledger. Tolerates partial lines + schema drift —
    rows missing required fields are skipped with a counter."""

    def __init__(self, runs_path: Path = RUNS_PATH) -> None:
        self.runs_path = runs_path
        self._skipped = 0

    def __iter__(self) -> Iterable[dict]:
        if not self.runs_path.exists():
            return
        for line in self.runs_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                self._skipped += 1
                continue
            if row.get("schema") != SCHEMA:
                self._skipped += 1
                continue
            yield row

    def best_per_group(self, key_fields: list[str] = None) -> dict[tuple, dict]:
        """Return the highest-composite row per (animal_slug, pose_slug) by default.
        Pass `key_fields=['animal_slug']` to group only by species."""
        key_fields = key_fields or ["animal_slug", "pose_slug"]
        best: dict[tuple, dict] = {}
        for row in self:
            key = tuple(row.get(k) for k in key_fields)
            current = best.get(key)
            if current is None or float(row.get("composite", 0)) > float(current.get("composite", 0)):
                best[key] = row
        return best

    def per_session_lineage(self) -> dict[str, list[dict]]:
        """Group rows by session_id, sorted by attempt within each session.
        Useful for D.2's lineage column ("how did the engine get here?")."""
        by_session: dict[str, list[dict]] = defaultdict(list)
        for row in self:
            by_session[row.get("session_id", "")].append(row)
        for sid in by_session:
            by_session[sid].sort(key=lambda r: int(r.get("attempt", 0)))
        return dict(by_session)


# ──────────────────────────────────────────────────────────────────────
# D.2 — `forge madhubani learn` mining job
# ──────────────────────────────────────────────────────────────────────


def mine_winning_prompts(runs_path: Path = RUNS_PATH, *, out_path: Path = WINNING_PATH,
                        min_composite: float = 0.0) -> dict[str, Any]:
    """Read runs.jsonl, find the best-composite row per (species, pose),
    and write a markdown digest at species_winning_prompts.md.

    Returns a summary dict {n_rows, n_skipped, n_groups, top_per_species, output_path}.
    """
    reader = RunsReader(runs_path)
    all_rows = list(reader)
    best_per_pose = reader.best_per_group(["animal_slug", "pose_slug"])
    sessions = reader.per_session_lineage()

    # Per-species roll-up for the digest header
    species_top: dict[str, dict] = {}
    for (slug, _pose), row in best_per_pose.items():
        cur = species_top.get(slug)
        if cur is None or row["composite"] > cur["composite"]:
            species_top[slug] = row

    lines: list[str] = []
    lines.append("# Madhubani — Winning Prompts (mined from runs.jsonl)")
    lines.append("")
    lines.append(f"> Mined: {_dt.datetime.now(_dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    try:
        source_display = runs_path.relative_to(ROOT)
    except ValueError:
        source_display = runs_path
    lines.append(f"> Source: `{source_display}`")
    lines.append(f"> Rows scanned: {len(all_rows)}, sessions: {len(sessions)}, groups: {len(best_per_pose)}")
    lines.append("")
    lines.append("Best-composite render per `(animal_slug, pose_slug)`, ordered by composite descending.")
    lines.append("")

    # Top-by-species table
    lines.append("## Top render per species")
    lines.append("")
    lines.append("| Species | Best composite | Best (slug, pose) | auto_qc_pass | Render |")
    lines.append("| :--- | -: | :--- | :-: | :--- |")
    for slug in sorted(species_top.keys()):
        row = species_top[slug]
        pose = row.get("pose_slug") or "(any)"
        render = row.get("render_path") or "(no path)"
        qc = "yes" if row.get("auto_qc_pass") else "no"
        lines.append(f"| {slug} | {row['composite']:.4f} | ({slug}, {pose}) | {qc} | `{render}` |")
    lines.append("")

    # Per-(species, pose) lineage
    lines.append("## Per-`(species, pose)` winner + lineage")
    lines.append("")
    for (slug, pose), row in sorted(best_per_pose.items(), key=lambda kv: -kv[1]["composite"]):
        if row["composite"] < min_composite:
            continue
        pose_display = pose or "(any)"
        lines.append(f"### `{slug}` / `{pose_display}`")
        lines.append("")
        lines.append(f"- **Best composite:** {row['composite']:.4f}  (auto_qc_pass: {row.get('auto_qc_pass')})")
        lines.append(f"- **Rubric pass fraction:** {row.get('rubric_pass_fraction', 0):.3f}")
        clip = row.get("clip_likeness_probability")
        lines.append(f"- **CLIP likeness probability:** {clip:.4f}" if clip is not None else "- **CLIP:** unavailable")
        lines.append(f"- **Active checks:** {row.get('pass_count')}/{row.get('active_check_count')}  ")
        lines.append(f"- **Failed:** {row.get('failed_checks') or '(none)'}")
        lines.append(f"- **Final boost applied (if any):** {row.get('boost_applied') or '(none)'}")
        lines.append(f"- **Prompt hash:** `{row.get('prompt_hash')}`")
        lines.append(f"- **Render path:** `{row.get('render_path') or '(not recorded)'}`")
        sid = row.get("session_id")
        if sid and sid in sessions and len(sessions[sid]) > 1:
            lines.append(f"- **Session lineage** ({sid}):")
            for r in sessions[sid]:
                weakest = r.get("weakest_dimension") or "—"
                lines.append(f"  - attempt {r['attempt']}: composite={r['composite']:.4f}, weakest={weakest}, accepted={r.get('accepted')}")
        prompt = (row.get("prompt") or "").strip()
        if prompt:
            lines.append("")
            lines.append("**Winning prompt:**")
            lines.append("")
            lines.append("```")
            for chunk in [prompt[i:i + 100] for i in range(0, len(prompt), 100)]:
                lines.append(chunk)
            lines.append("```")
        lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    try:
        out_path_display = str(out_path.relative_to(ROOT))
    except ValueError:
        # out_path is outside ROOT (e.g. a tempdir during tests). Use absolute.
        out_path_display = str(out_path)
    return {
        "n_rows": len(all_rows),
        "n_skipped": reader._skipped,
        "n_groups": len(best_per_pose),
        "n_species": len(species_top),
        "output_path": out_path_display,
    }


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────


def cmd_summary(args: argparse.Namespace) -> int:
    """Print a quick summary of the ledger without writing a doc."""
    reader = RunsReader(args.runs_path)
    n = sum(1 for _ in reader)
    if n == 0:
        print(f"No rows in {args.runs_path}.")
        return 0
    print(f"Ledger:  {args.runs_path.relative_to(ROOT) if args.runs_path.is_absolute() else args.runs_path}")
    print(f"  rows:     {n}")
    print(f"  skipped:  {reader._skipped}")
    by_species = defaultdict(int)
    for row in RunsReader(args.runs_path):
        by_species[row.get("animal_slug", "?")] += 1
    print(f"  species:  {len(by_species)}")
    for s, count in sorted(by_species.items(), key=lambda kv: -kv[1]):
        print(f"    {s:25s}  {count} rows")
    return 0


def cmd_learn(args: argparse.Namespace) -> int:
    """`forge madhubani learn` — mine winning prompts into a markdown digest."""
    summary = mine_winning_prompts(
        runs_path=args.runs_path,
        out_path=args.out,
        min_composite=args.min_composite,
    )
    print(f"Mined {summary['n_rows']} rows ({summary['n_skipped']} skipped) → "
          f"{summary['n_groups']} (species, pose) groups across {summary['n_species']} species")
    print(f"Wrote {summary['output_path']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("summary", help="Print ledger summary (row counts per species)")
    s.add_argument("--runs-path", type=Path, default=RUNS_PATH)
    s.set_defaults(func=cmd_summary)

    l = sub.add_parser("learn", help="Mine the ledger into species_winning_prompts.md")
    l.add_argument("--runs-path", type=Path, default=RUNS_PATH)
    l.add_argument("--out", type=Path, default=WINNING_PATH)
    l.add_argument("--min-composite", type=float, default=0.0,
                   help="Skip groups whose best row has composite < this value")
    l.set_defaults(func=cmd_learn)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
