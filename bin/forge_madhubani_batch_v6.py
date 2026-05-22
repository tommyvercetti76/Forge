#!/usr/bin/env python3
"""v6 batch: signature_features prompts + Kontext img2img init from species photos.

Identical to the v5 driver, with one critical addition: per-species, the
batch reads `brand/madhubani/v6_init_images.json` to find the canonical
species photo and passes it to `bin/forge_madhubani_reasoning.py` as
`--init-image <path> --init-image-strength <s>`. The reasoning loop then
threads this through to mflux as `--image-path` / `--image-strength`
during rendering.

This is the hypothesis: photo-grounded init images defeat the FLUX/Z-Image
species priors (snow-leopard-as-cheetah, cobra-double-tongue) that the
signature_features prompt clauses alone couldn't fully overcome.

Usage:
  # Full 41-species v6 batch with init images from curation:
  python3 bin/forge_madhubani_batch_v6.py

  # Smoke test on 3 species:
  python3 bin/forge_madhubani_batch_v6.py --limit 3

  # Override init-image strength globally:
  python3 bin/forge_madhubani_batch_v6.py --init-image-strength 0.5
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
V6_ROOT = ROOT / "generated" / "madhubani_animals" / "v6"
SUMMARY_PATH = V6_ROOT / "_batch_summary.json"
BATCH_LOG_DIR = V6_ROOT / "_logs"
INIT_IMAGES_PATH = ROOT / "brand" / "madhubani" / "v6_init_images.json"


def load_animals() -> list[dict]:
    data = json.loads(ANIMALS_PATH.read_text())
    return data.get("animals", [])


def load_init_images() -> dict:
    if not INIT_IMAGES_PATH.exists():
        return {"init_images": {}, "default_strength": 0.4}
    return json.loads(INIT_IMAGES_PATH.read_text())


def run_one_species(animal: dict, init_images: dict, args: argparse.Namespace) -> dict:
    """Invoke reasoning.py for one species, passing the canonical species
    photo as init-image (if curated)."""
    slug = animal["slug"]
    start = time.time()
    BATCH_LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = BATCH_LOG_DIR / f"{slug}.log"

    init_entry = init_images.get("init_images", {}).get(slug)
    init_image_path: Path | None = None
    init_image_strength: float = init_images.get("default_strength", 0.4)
    if init_entry:
        init_image_path = ROOT / init_entry["image_path"]
        init_image_strength = init_entry.get("strength", init_image_strength)
        # Override global strength if CLI specified it
        if args.init_image_strength is not None:
            init_image_strength = args.init_image_strength
        if not init_image_path.exists():
            print(f"  ! {slug}: init-image not found at {init_image_path} — falling back to no-init", file=sys.stderr)
            init_image_path = None

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
    if init_image_path is not None:
        cmd.extend(["--init-image", str(init_image_path),
                    "--init-image-strength", str(init_image_strength)])

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
        "init_image_used": str(init_image_path.relative_to(ROOT)) if init_image_path else None,
        "init_image_strength": init_image_strength if init_image_path else None,
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
    parser.add_argument("--per-species-timeout", type=int, default=600)
    parser.add_argument("--init-image-strength", type=float, default=None,
                        help="Override the per-species init-image strength globally")
    args = parser.parse_args()

    animals = load_animals()
    init_images = load_init_images()

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

    V6_ROOT.mkdir(parents=True, exist_ok=True)
    BATCH_LOG_DIR.mkdir(parents=True, exist_ok=True)

    n_init = sum(1 for a in animals if a["slug"] in init_images.get("init_images", {}))
    print("=" * 72)
    print(f"v6 batch start: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"  species:           {len(animals)}")
    print(f"  with init-image:   {n_init}/{len(animals)}")
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
        has_init = "📷" if slug in init_images.get("init_images", {}) else "  "
        print(f"\n[{i}/{len(animals)}] {has_init} {slug:25s} body={body:20s} ", end="", flush=True)
        status = run_one_species(animal, init_images, args)
        statuses.append(status)
        if status["rc"] == 0 and status.get("winner_composite") is not None:
            tag = "✓ accepted" if status.get("accepted") else f"⚠ stopped@{status.get('stopped_on_attempt')}"
            print(f"composite={status['winner_composite']:.4f}  {tag}  ({status['elapsed_seconds']:.0f}s)")
        elif status["rc"] == -2:
            print(f"✗ TIMEOUT after {status['elapsed_seconds']:.0f}s")
        else:
            print(f"✗ rc={status['rc']}  ({status['elapsed_seconds']:.0f}s)  log={status['log_path']}")
        SUMMARY_PATH.write_text(json.dumps({
            "schema": "forge.v6_batch_summary.v1",
            "start_ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "args": vars(args),
            "init_images_source": str(INIT_IMAGES_PATH.relative_to(ROOT)),
            "n_init_images": n_init,
            "n_done": len(statuses),
            "n_total": len(animals),
            "statuses": statuses,
        }, indent=2, default=str))

    batch_elapsed = time.time() - batch_start
    print()
    print("=" * 72)
    print(f"v6 batch finished in {batch_elapsed/60:.1f} min")
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
