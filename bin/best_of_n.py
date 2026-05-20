#!/usr/bin/env python3
"""Phase C.1 — multi-seed best-of-N selection.

Given N rendered variants of the same prompt (e.g. from the existing
P1 multi-seed batch `flux_generate_batch`), score each via:

  1. The 9-check Madhubani auto-QC rubric (heuristic checks; F1 0.67
     vs human review on a 9-image strong-label set).
  2. The CLIP+sklearn `madhubani_likeness_v1` probe (learned; F1 0.89
     vs human review on the same set).

Compute a composite score and return the winner with a ranked manifest.

This is the C.1 step in the Art Reasoning Engine
([docs/ART_REASONING_ENGINE.md](../docs/ART_REASONING_ENGINE.md)) — what
follows is C.2 retry-with-boost on the loser variants.

Composite formula:

    composite = 0.6 * rubric_pass_fraction + 0.4 * clip_likeness_probability

  where:
    rubric_pass_fraction = pass_count / active_check_count   (0..1)
    clip_likeness_probability = sigmoid(probe.coef @ clip_emb + probe.intercept)
                                  in [0, 1] — present only if open_clip
                                  is installed AND the probe weights load

If the probe is unavailable (open_clip not installed, weights missing,
etc.), the composite degrades to `rubric_pass_fraction` and an
informational note is logged. Tie-breaks: higher CLIP probability >
seed value (lower seed wins, deterministic).

Usage (standalone):
  python3 bin/best_of_n.py --animal tiger path/v1.png path/v2.png path/v3.png
  python3 bin/best_of_n.py --animal peacock --json out/ranked.json *.png

Usage (Python):
  from best_of_n import pick_best_of_n
  result = pick_best_of_n(png_paths, animal_metadata)
  winner = result["winner"]["path"]
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from madhubani_qc import score_madhubani_png  # noqa: E402


ANIMALS_PATH = ROOT / "brand/madhubani/animals.json"
PALETTE_PATH = ROOT / "brand/madhubani/palette.json"
LIKENESS_WEIGHTS_PATH = ROOT / "brand/madhubani/madhubani_likeness_v1.npz"

DEFAULT_RUBRIC_WEIGHT = 0.6
DEFAULT_CLIP_WEIGHT = 0.4


# ──────────────────────────────────────────────────────────────────────
# CLIP likeness probe — lazy loaded, gracefully skips if absent.
# ──────────────────────────────────────────────────────────────────────


_PROBE_CACHE: dict[str, Any] | None = None


def _load_likeness_probe() -> dict[str, Any] | None:
    """Return {coef, intercept, threshold, model, preprocess, torch} or
    None if open_clip / weights / torch can't be loaded.

    Cached on first call. Lazy import keeps `best_of_n` importable when
    open_clip is absent (it's an optional `[ml]` extra in pyproject)."""
    global _PROBE_CACHE
    if _PROBE_CACHE is not None:
        return _PROBE_CACHE or None
    try:
        import torch
        import open_clip
    except ImportError:
        _PROBE_CACHE = {}
        return None
    if not LIKENESS_WEIGHTS_PATH.exists():
        _PROBE_CACHE = {}
        return None
    try:
        weights = np.load(LIKENESS_WEIGHTS_PATH)
        coef = np.asarray(weights["clip_classifier_coef"], dtype=np.float32)
        intercept = float(weights["clip_classifier_intercept"][0])
        threshold = float(weights["decision_threshold"][0])
    except Exception:
        _PROBE_CACHE = {}
        return None
    try:
        model, _, preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="openai",
        )
        model.eval()
    except Exception:
        _PROBE_CACHE = {}
        return None
    _PROBE_CACHE = {
        "coef": coef,
        "intercept": intercept,
        "threshold": threshold,
        "model": model,
        "preprocess": preprocess,
        "torch": torch,
    }
    return _PROBE_CACHE


def _clip_likeness_probability(png_path: Path) -> float | None:
    """Return P(Madhubani-likeness) in [0, 1] for one image, or None
    when the probe is unavailable."""
    probe = _load_likeness_probe()
    if not probe:
        return None
    from PIL import Image  # local — already a hard dep via pyproject
    img = Image.open(png_path).convert("RGB")
    tensor = probe["preprocess"](img).unsqueeze(0)
    with probe["torch"].no_grad():
        feat = probe["model"].encode_image(tensor).float().numpy()[0]
    feat /= (np.linalg.norm(feat) + 1e-9)
    logit = float(np.dot(feat, probe["coef"]) + probe["intercept"])
    return 1.0 / (1.0 + math.exp(-logit))


# ──────────────────────────────────────────────────────────────────────
# Filename → animal slug inference (matches the agreement-study pattern)
# ──────────────────────────────────────────────────────────────────────


FILENAME_HINTS: dict[str, str] = {
    "tiger": "tiger",
    "royal_bengal_tiger": "tiger",
    "elephant": "elephant",
    "indian_elephant": "elephant",
    "peacock": "peacock",
    "indian_peacock": "peacock",
    "blackbuck": "blackbuck",
    "rhino": "rhino",
    "one_horned_rhinoceros": "rhino",
    "cobra": "cobra",
    "king_cobra": "cobra",
    "snow_leopard": "snow-leopard",
    "lion_tailed_macaque": "macaque",
    "macaque": "macaque",
}


def infer_slug_from_path(path: Path) -> str | None:
    stem = path.stem.lower()
    for key, slug in FILENAME_HINTS.items():
        if key in stem:
            return slug
    return None


def infer_seed_from_path(path: Path) -> int | None:
    """Pull a numeric seed out of the filename if present
    (matches the existing convention seed-NNN, _seed_NNN, .NNN.)."""
    m = re.search(r"seed[_-]?(\d+)", path.stem.lower())
    if m:
        return int(m.group(1))
    return None


def load_animals_index() -> dict[str, dict]:
    data = json.loads(ANIMALS_PATH.read_text())
    return {entry["slug"]: entry for entry in data.get("animals", [])}


# ──────────────────────────────────────────────────────────────────────
# Scoring
# ──────────────────────────────────────────────────────────────────────


def score_render(
    png_path: Path,
    animal: dict | None,
    *,
    rubric_weight: float = DEFAULT_RUBRIC_WEIGHT,
    clip_weight: float = DEFAULT_CLIP_WEIGHT,
) -> dict[str, Any]:
    """Score one render. Returns:
      {
        path, pass_count, active_check_count, rubric_pass_fraction,
        clip_likeness_probability, composite, clip_available,
        qc:  <full QC dict from score_madhubani_png>,
      }
    """
    qc = score_madhubani_png(
        png_path,
        palette_path=PALETTE_PATH,
        expected_body_fill=animal.get("body_fill_color") if animal else None,
        body_type=animal.get("body_type") if animal else None,
        decoration_density=animal.get("decoration_density") if animal else None,
        required_decoration_zones=animal.get("required_decoration_zones") if animal else None,
        anatomical_count_constraints=animal.get("anatomical_count_constraints") if animal else None,
    )
    pass_count = qc["pass_count"]
    active = qc["active_check_count"]
    rubric_frac = pass_count / max(1, active)
    clip_p = _clip_likeness_probability(png_path)
    clip_available = clip_p is not None

    if clip_available:
        composite = rubric_weight * rubric_frac + clip_weight * float(clip_p)
    else:
        composite = rubric_frac

    return {
        "path": str(png_path),
        "filename": png_path.name,
        "seed": infer_seed_from_path(png_path),
        "pass_count": pass_count,
        "active_check_count": active,
        "rubric_pass_fraction": round(rubric_frac, 4),
        "clip_likeness_probability": (
            round(float(clip_p), 4) if clip_available else None
        ),
        "clip_available": clip_available,
        "composite": round(composite, 4),
        "auto_qc_pass": bool(qc["auto_qc_pass"]),
        "qc_summary": {
            "failed_checks": [
                name for name, item in qc["checks"].items() if not item.get("pass")
            ],
        },
    }


def pick_best_of_n(
    png_paths: list[Path],
    animal: dict | None,
    *,
    rubric_weight: float = DEFAULT_RUBRIC_WEIGHT,
    clip_weight: float = DEFAULT_CLIP_WEIGHT,
) -> dict[str, Any]:
    """Score every render, rank by composite (tie-break by clip
    probability then by lower seed), return winner + ranked manifest."""
    if not png_paths:
        return {
            "schema": "forge.best_of_n.v1",
            "n": 0,
            "winner": None,
            "ranked": [],
            "reason": "no input paths",
        }
    rows = [score_render(p, animal, rubric_weight=rubric_weight, clip_weight=clip_weight) for p in png_paths]
    # Sort by (composite desc, clip_prob desc, seed asc, filename asc).
    rows.sort(
        key=lambda r: (
            -r["composite"],
            -(r["clip_likeness_probability"] if r["clip_likeness_probability"] is not None else -1),
            r["seed"] if r["seed"] is not None else 10**9,
            r["filename"],
        )
    )
    # Add rank field.
    for i, r in enumerate(rows):
        r["rank"] = i + 1

    winner = rows[0]
    clip_available = any(r["clip_available"] for r in rows)
    return {
        "schema": "forge.best_of_n.v1",
        "n": len(rows),
        "clip_probe_loaded": clip_available,
        "weights": {"rubric": rubric_weight, "clip": clip_weight if clip_available else 0.0},
        "winner": winner,
        "ranked": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="+", type=Path, help="Variant PNGs to score")
    parser.add_argument("--animal", default=None,
                        help="Animal slug. If omitted, inferred from filename.")
    parser.add_argument("--json", type=Path, default=None,
                        help="Write ranked manifest to this JSON path")
    parser.add_argument("--rubric-weight", type=float, default=DEFAULT_RUBRIC_WEIGHT)
    parser.add_argument("--clip-weight", type=float, default=DEFAULT_CLIP_WEIGHT)
    args = parser.parse_args()

    animals = load_animals_index()
    slug = args.animal
    if slug is None:
        for p in args.paths:
            inferred = infer_slug_from_path(p)
            if inferred is not None:
                slug = inferred
                break
    if slug is None:
        print("ERROR: could not infer --animal slug from any filename. Pass --animal explicitly.", file=sys.stderr)
        return 2
    animal = animals.get(slug)
    if animal is None:
        print(f"ERROR: animal slug '{slug}' not found in animals.json", file=sys.stderr)
        return 2

    print(f"Scoring {len(args.paths)} variant(s) of animal '{slug}'...")
    result = pick_best_of_n(
        args.paths, animal,
        rubric_weight=args.rubric_weight,
        clip_weight=args.clip_weight,
    )
    if not result["clip_probe_loaded"]:
        print("NOTE: CLIP likeness probe unavailable (open_clip not installed "
              "or madhubani_likeness_v1.npz missing). Falling back to rubric-only score.")
    print()
    print(f"{'rank':>4}  {'composite':>9}  {'rubric':>8}  {'clip':>6}  {'pass/active':>11}  filename")
    for r in result["ranked"]:
        clip_str = f"{r['clip_likeness_probability']:.3f}" if r["clip_likeness_probability"] is not None else " —  "
        print(f"  {r['rank']:>2}  {r['composite']:>9.4f}  {r['rubric_pass_fraction']:>8.3f}  {clip_str:>6}  "
              f"{r['pass_count']:>4}/{r['active_check_count']:<4}  {r['filename']}")
    print()
    print(f"WINNER: {result['winner']['filename']}  (composite={result['winner']['composite']:.4f})")
    if result["winner"]["qc_summary"]["failed_checks"]:
        print(f"  Failed checks (informational): {result['winner']['qc_summary']['failed_checks']}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(result, indent=2))
        print(f"\nWrote {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
