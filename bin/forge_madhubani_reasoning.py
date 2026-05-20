#!/usr/bin/env python3
"""End-to-end reasoning-loop demo: real mflux + C.1 picker + C.2 boost
+ D.1 ledger persistence on a single Madhubani species.

Wires the test-stub `render_fn` in `art_reasoning_engine.render_with_reasoning`
to the real `forge engine render` subprocess so we can actually exercise:

  render N seeds → score → rank → diagnose weakest → compose boost →
  re-render with boosted prompt → re-score → re-rank → accept or loop

This is the production wire-up that the maintainer's "did we actually
run the closed loop on rhino" question requires.

Defaults are sized for an honest M5 Max demo:
  --slug rhino  --max-attempts 2  --seeds-per-attempt 2  --steps 25

Each attempt invokes one subprocess (paying one mflux cold-load) that
renders `seeds_per_attempt` variants via the existing P1 multi-seed
batch. Subsequent attempts get the boosted prompt as the conditioning.
Total wall-clock budget: ~3-5 min on M5 Max.

Output:
  - generated/madhubani_animals/reasoning_runs/<timestamp>/
      attempt_1/  attempt_2/  ...   ← variant PNGs
      reasoning_result.json         ← full C.2 attempt ledger
  - brand/madhubani/learning/runs.jsonl       ← D.1 append-only ledger
  - prints attempt-by-attempt receipt to stdout

Usage:
  python3 bin/forge_madhubani_reasoning.py --slug rhino \\
      --max-attempts 2 --seeds-per-attempt 2

  # Dry-run (no mflux, just the prompt assembly + boost logic):
  python3 bin/forge_madhubani_reasoning.py --slug rhino --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from art_reasoning_engine import render_with_reasoning  # noqa: E402
from forge_madhubani import build_subject_string  # noqa: E402

FORGE_BIN = ROOT / "bin" / "forge.py"
ANIMALS_PATH = ROOT / "brand" / "madhubani" / "animals.json"
POSES_PATH = ROOT / "brand" / "madhubani" / "poses.json"
RUNS_ROOT = ROOT / "generated" / "madhubani_animals" / "reasoning_runs"


def load_animal(slug: str) -> dict:
    data = json.loads(ANIMALS_PATH.read_text())
    for entry in data.get("animals", []):
        if entry["slug"] == slug:
            return entry
    raise SystemExit(f"animal slug '{slug}' not in animals.json")


def load_pose(slug: str | None) -> dict:
    data = json.loads(POSES_PATH.read_text())
    poses = data.get("poses") or data.get("slots") or []
    if not poses:
        raise SystemExit("no poses defined in poses.json")
    if slug is None:
        slug = poses[0].get("slug") or "standing-alert"
    for pose in poses:
        if pose.get("slug") == slug:
            return pose
    raise SystemExit(f"pose slug '{slug}' not in poses.json")


def make_render_fn(
    animal: dict,
    base_run_dir: Path,
    *,
    profile: str = "madhubani",
    steps: int = 25,
    dry_run: bool = False,
):
    """Returns render_fn(prompt, seeds) -> list[Path] that wraps the
    real `forge engine render` subprocess. One subprocess per attempt;
    each invocation renders len(seeds) variants in one mflux batch."""
    attempt_counter = {"n": 0}

    def render_fn(prompt: str, seeds: Sequence[int]) -> list[Path]:
        attempt_counter["n"] += 1
        attempt_dir = base_run_dir / f"attempt_{attempt_counter['n']:02d}"
        attempt_dir.mkdir(parents=True, exist_ok=True)
        seeds_list = list(seeds)
        seeds_n = len(seeds_list)
        # forge engine render writes seed01.png, seed02.png ... when --seeds N>1.
        # The variants use base_seed + i; we pass our first requested seed as
        # --seed so the on-disk seed numbering matches what we expect.
        out_path = attempt_dir / "render.png"
        cmd = [
            sys.executable, str(FORGE_BIN),
            "engine", "render", "minimalist-tshirt",
            "--subject", prompt,
            "--profile", profile,
            "--steps", str(steps),
            "--seed", str(seeds_list[0]),
            "--seeds", str(seeds_n),
            "--out", str(out_path),
        ]
        # Style-reference pass-through (Lane 1 wiring)
        ref_rel = animal.get("style_reference_path")
        if ref_rel:
            ref_abs = ROOT / ref_rel
            if ref_abs.exists():
                cmd.extend(["--style-reference", str(ref_abs)])
                strength = animal.get("style_reference_strength")
                if strength is not None:
                    cmd.extend(["--style-reference-strength", str(strength)])
        print(f"\n── Attempt #{attempt_counter['n']}: rendering {seeds_n} seeds "
              f"[{', '.join(str(s) for s in seeds_list)}] via {profile} ──")
        if dry_run:
            print(f"   [dry-run] would run: {' '.join(cmd[:6])} ...")
            # Return placeholder paths so the loop can proceed
            return [attempt_dir / f"seed{i+1:02d}.png" for i in range(seeds_n)]
        t0 = time.time()
        env = os.environ.copy()
        rc = subprocess.call(cmd, env=env)
        dt = time.time() - t0
        if rc != 0:
            raise SystemExit(f"render subprocess failed (rc={rc}); see output above")
        # Multi-seed mode emits seedNN.png in attempt_dir
        if seeds_n == 1:
            generated = [out_path]
        else:
            generated = sorted(attempt_dir.glob("seed*.png"))
            # Filter out -base.png variants (refine artifacts)
            generated = [p for p in generated if "-base" not in p.name]
        print(f"   ✓ {seeds_n} variants rendered in {dt:.1f}s "
              f"({dt / max(1, seeds_n):.1f}s/variant)")
        return generated

    return render_fn


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--slug", default="rhino", help="animal slug from animals.json")
    parser.add_argument("--pose", default="standing-alert", help="pose slug from poses.json")
    parser.add_argument("--register", default="madhubani-master-painter")
    parser.add_argument("--max-attempts", type=int, default=2)
    parser.add_argument("--seeds-per-attempt", type=int, default=2)
    parser.add_argument("--accept-score", type=float, default=0.80)
    parser.add_argument("--steps", type=int, default=25)
    parser.add_argument("--profile", default="madhubani")
    parser.add_argument("--dry-run", action="store_true",
                        help="Don't call mflux; just exercise the prompt + boost logic")
    args = parser.parse_args()

    animal = load_animal(args.slug)
    pose = load_pose(args.pose)
    subject = build_subject_string(animal, pose, args.register)
    seed_offset = int(animal.get("seed_block_start", 8200))

    run_id = time.strftime("%Y%m%d_%H%M%S")
    base_run_dir = RUNS_ROOT / args.slug / run_id
    base_run_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print(f"REASONING-LOOP RUN: {args.slug} / {args.pose}")
    print(f"  max_attempts={args.max_attempts}  seeds_per_attempt={args.seeds_per_attempt}  "
          f"accept_score={args.accept_score}")
    print(f"  seed_offset={seed_offset}  profile={args.profile}  steps={args.steps}")
    print(f"  output dir: {base_run_dir.relative_to(ROOT)}")
    print(f"  base prompt: {subject[:120]}...")
    print("=" * 72)

    render_fn = make_render_fn(
        animal, base_run_dir,
        profile=args.profile, steps=args.steps,
        dry_run=args.dry_run,
    )

    result = render_with_reasoning(
        base_prompt=subject,
        animal=animal,
        render_fn=render_fn,
        max_attempts=args.max_attempts,
        seeds_per_attempt=args.seeds_per_attempt,
        seed_offset=seed_offset,
        accept_score=args.accept_score,
        persist_to_ledger=not args.dry_run,
        pose_slug=args.pose,
        model=args.profile,
    )

    # Save the full reasoning result for the rhino-doc receipts
    (base_run_dir / "reasoning_result.json").write_text(json.dumps(result, indent=2, default=str))

    print()
    print("=" * 72)
    print("RECEIPTS (real attempt-by-attempt deltas)")
    print("=" * 72)
    for entry in result["attempts"]:
        n = entry["attempt"]
        winner = entry["winner"]
        weakest = entry["weakest_check"]
        boost = entry["boost_clause_used_for_next_attempt"]
        print(f"\nAttempt {n}:")
        print(f"  winner path:        {winner.get('filename')}")
        print(f"  composite:          {winner.get('composite'):.4f}")
        print(f"  rubric pass frac:   {winner.get('rubric_pass_fraction'):.3f}")
        clip_p = winner.get("clip_likeness_probability")
        print(f"  CLIP P:             {clip_p:.4f}" if clip_p is not None else "  CLIP P:             (unavailable)")
        print(f"  active checks:      {winner.get('pass_count')}/{winner.get('active_check_count')}")
        print(f"  auto_qc_pass:       {winner.get('auto_qc_pass')}")
        print(f"  failed checks:      {winner.get('qc_summary', {}).get('failed_checks')}")
        print(f"  weakest check:      {weakest or '(none — passed)'}")
        print(f"  boost for next:     {(boost or '(none)')[:100]}")
    print()
    print(f"ACCEPTED: {result['accepted']}  on attempt {result['stopped_on_attempt']}")
    if len(result["attempts"]) >= 2:
        c1 = result["attempts"][0]["winner"]["composite"]
        c2 = result["attempts"][-1]["winner"]["composite"]
        delta = c2 - c1
        sign = "+" if delta >= 0 else ""
        print(f"COMPOSITE DELTA attempt 1 → attempt {result['stopped_on_attempt']}: "
              f"{c1:.4f} → {c2:.4f}  ({sign}{delta:.4f})")
    if result.get("persisted_to_ledger"):
        print("\nLedger updated: brand/madhubani/learning/runs.jsonl")
        print("Mine winning prompts: python3 bin/feedback_memory.py learn")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
