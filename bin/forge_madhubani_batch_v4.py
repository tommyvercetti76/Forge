#!/usr/bin/env python3
"""v4 batch: run the Art Reasoning Engine on every species in the catalog.

Walks `brand/madhubani/animals.json` (41 species across 21 Indian
national parks) and runs `bin/forge_madhubani_reasoning.py` per
species with default settings tuned for the v4 batch:

  --max-attempts 3   --seeds-per-attempt 2   --accept-score 0.70

This is the largest single Madhubani render run yet attempted. Each
species runs the full C.2 closed loop (render → score → diagnose →
boost → re-render up to 3 attempts) and persists every attempt to
`brand/madhubani/learning/runs.jsonl` (D.1).

**Wall-clock budget on M5 Max:**

Best case (every species accepts on attempt 1):
  41 species × ~52 s per species (cold-load + 2 seeds at 24 s each)
  = ~36 min

Realistic mix (most accept attempt 1, ~20% need 2 attempts, ~5% need 3):
  ≈ 50-65 min

Worst case (every species hits max-attempts):
  41 species × 3 attempts × ~52 s
  = ~107 min

**Resilience:**
- Each species runs in its own subprocess. A render failure in one
  species does NOT stop the batch — the failure is logged and the
  driver moves to the next species.
- Output: `generated/madhubani_animals/v4/<slug>/<run_id>/` per species.
- Summary manifest: `generated/madhubani_animals/v4/_batch_summary.json`
  records {species, status, attempts, final_composite, winner_path}.
- Contact-sheet generation is a separate step after the batch lands.

Usage:
  # Full 41-species batch in background
  python3 bin/forge_madhubani_batch_v4.py

  # Smoke test with 3 species first
  python3 bin/forge_madhubani_batch_v4.py --limit 3

  # Filter to a body-type subset
  python3 bin/forge_madhubani_batch_v4.py --body-types bird,serpent

  # Resume from a particular species
  python3 bin/forge_madhubani_batch_v4.py --start-from peacock
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REASONING_CLI = ROOT / "bin" / "forge_madhubani_reasoning.py"
ANIMALS_PATH = ROOT / "brand" / "madhubani" / "animals.json"
V4_ROOT = ROOT / "generated" / "madhubani_animals" / "v4"
SUMMARY_PATH = V4_ROOT / "_batch_summary.json"
BATCH_LOG_DIR = V4_ROOT / "_logs"


def load_animals() -> list[dict]:
    data = json.loads(ANIMALS_PATH.read_text())
    return data.get("animals", [])


def run_one_species(animal: dict, args: argparse.Namespace) -> dict:
    """Invoke `forge_madhubani_reasoning.py` for one species. Returns a
    status dict for the batch summary."""
    slug = animal["slug"]
    start = time.time()
    # Log per-species output to disk so the orchestrator log stays scannable.
    BATCH_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = BATCH_LOG_DIR / f"{slug}.log"
    cmd = [
        sys.executable, str(REASONING_CLI),
        "--slug", slug,
        "--pose", args.pose,
        "--max-attempts", str(args.max_attempts),
        "--seeds-per-attempt", str(args.seeds_per_attempt),
        "--accept-score", str(args.accept_score),
        "--steps", str(args.steps),
        "--profile", args.profile,
    ]
    rc = -1
    try:
        with log_path.open("w") as fh:
            proc = subprocess.run(cmd, stdout=fh, stderr=subprocess.STDOUT, timeout=args.per_species_timeout)
            rc = proc.returncode
    except subprocess.TimeoutExpired:
        rc = -2
    except Exception as exc:
        rc = -3
        log_path.write_text(f"orchestrator exception: {exc}\n")
    elapsed = time.time() - start

    # Pull the result manifest the reasoning CLI wrote.
    result_dir = ROOT / "generated/madhubani_animals/reasoning_runs" / slug
    if result_dir.exists():
        latest = sorted(result_dir.iterdir())[-1] if result_dir.iterdir() else None
        result_path = latest / "reasoning_result.json" if latest else None
    else:
        result_path = None

    status = {
        "slug": slug,
        "display_name": animal.get("display_name", slug),
        "body_type": animal.get("body_type"),
        "park": animal.get("park"),
        "rc": rc,
        "elapsed_seconds": round(elapsed, 1),
        "log_path": str(log_path.relative_to(ROOT)),
        "reasoning_result_path": (
            str(result_path.relative_to(ROOT)) if result_path and result_path.exists() else None
        ),
    }
    if result_path and result_path.exists():
        try:
            result = json.loads(result_path.read_text())
            winner = result.get("winner") or {}
            status["accepted"] = bool(result.get("accepted"))
            status["stopped_on_attempt"] = result.get("stopped_on_attempt")
            status["winner_composite"] = winner.get("composite")
            status["winner_path"] = winner.get("path")
            status["winner_auto_qc_pass"] = winner.get("auto_qc_pass")
        except Exception:
            status["parse_error"] = True
    return status


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pose", default="standing-alert")
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--seeds-per-attempt", type=int, default=2)
    parser.add_argument("--accept-score", type=float, default=0.70)
    parser.add_argument("--steps", type=int, default=25)
    parser.add_argument("--profile", default="madhubani")
    parser.add_argument("--limit", type=int, default=0,
                        help="Stop after N species (for smoke testing; 0 = all)")
    parser.add_argument("--body-types", default="",
                        help="Comma-separated body types to filter (e.g., bird,serpent)")
    parser.add_argument("--start-from", default="",
                        help="Skip until this slug, then resume")
    parser.add_argument("--per-species-timeout", type=int, default=600,
                        help="Hard timeout per species in seconds")
    args = parser.parse_args()

    animals = load_animals()
    # Filter
    if args.body_types:
        wanted = {bt.strip() for bt in args.body_types.split(",")}
        animals = [a for a in animals if a.get("body_type") in wanted]
    if args.start_from:
        for i, a in enumerate(animals):
            if a["slug"] == args.start_from:
                animals = animals[i:]
                break
    if args.limit > 0:
        animals = animals[:args.limit]

    V4_ROOT.mkdir(parents=True, exist_ok=True)
    BATCH_LOG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print(f"v4 batch start: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"  species:           {len(animals)}")
    print(f"  pose:              {args.pose}")
    print(f"  max_attempts:      {args.max_attempts}")
    print(f"  seeds_per_attempt: {args.seeds_per_attempt}")
    print(f"  accept_score:      {args.accept_score}")
    print(f"  profile / steps:   {args.profile} / {args.steps}")
    print(f"  per-species logs:  {BATCH_LOG_DIR.relative_to(ROOT)}/")
    print(f"  summary path:      {SUMMARY_PATH.relative_to(ROOT)}")
    print("=" * 72)

    batch_start = time.time()
    statuses: list[dict] = []
    for i, animal in enumerate(animals, start=1):
        slug = animal["slug"]
        body = animal.get("body_type", "?")
        print(f"\n[{i}/{len(animals)}] {slug:25s} body={body:20s} ", end="", flush=True)
        status = run_one_species(animal, args)
        statuses.append(status)
        if status["rc"] == 0 and status.get("winner_composite") is not None:
            tag = "✓ accepted" if status.get("accepted") else f"⚠ stopped@{status.get('stopped_on_attempt')}"
            print(f"composite={status['winner_composite']:.4f}  {tag}  ({status['elapsed_seconds']:.0f}s)")
        elif status["rc"] == -2:
            print(f"✗ TIMEOUT after {status['elapsed_seconds']:.0f}s")
        else:
            print(f"✗ rc={status['rc']}  ({status['elapsed_seconds']:.0f}s)  log={status['log_path']}")
        # Atomic-ish summary write after each species so a crash doesn't lose state.
        SUMMARY_PATH.write_text(json.dumps({
            "schema": "forge.v4_batch_summary.v1",
            "start_ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "args": vars(args),
            "n_done": len(statuses),
            "n_total": len(animals),
            "statuses": statuses,
        }, indent=2, default=str))

    batch_elapsed = time.time() - batch_start

    # Final summary
    print()
    print("=" * 72)
    print(f"v4 batch finished in {batch_elapsed/60:.1f} min")
    print(f"  total species:     {len(statuses)}")
    accepted = sum(1 for s in statuses if s.get("accepted"))
    rc_zero = sum(1 for s in statuses if s["rc"] == 0)
    failed = sum(1 for s in statuses if s["rc"] != 0)
    composites = [s.get("winner_composite") for s in statuses if s.get("winner_composite") is not None]
    print(f"  accepted (qc pass): {accepted}")
    print(f"  rc=0 (rendered):    {rc_zero}")
    print(f"  failed:             {failed}")
    if composites:
        print(f"  composite mean:     {sum(composites)/len(composites):.4f}")
        print(f"  composite range:    {min(composites):.4f} – {max(composites):.4f}")
    print(f"\nSummary: {SUMMARY_PATH.relative_to(ROOT)}")
    print(f"Next: python3 bin/feedback_memory.py learn")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
