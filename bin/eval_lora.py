#!/usr/bin/env python3
"""Held-out evaluation harness for the Madhubani LoRA.

Renders the four held-out species (rhino, peacock, elephant, snow-leopard
— defined in `brand/madhubani/lora_v1_holdout.json`) under TWO conditions:

  1. **base**:  z-image-turbo, no LoRA
  2. **lora**:  z-image-turbo + the trained adapter (--lora-paths)

Same prompts, same seeds, fully paired. Scores every render via the
existing composite formula (rubric 0.6 + CLIP-likeness-v2 0.4) and
emits:

  - `eval_lora_report.json` — numeric deltas + ship/iterate/shelve decision
  - `eval_lora_report.html` — side-by-side grid (base | LoRA), labeled with
    deltas per (species, seed), suitable for breakfast browsing

The decision thresholds come straight from `lora_v1_holdout.json`:

  - ΔComposite ≥ +0.05  → SHIP the LoRA
  - ΔComposite ∈ [-0.02, +0.05] → ITERATE (per-species investigation)
  - ΔComposite < -0.02 → SHELVE (LoRA hurt; documented negative result)

Usage:
  # Standard: eval one LoRA checkpoint
  python3 bin/eval_lora.py \\
      --lora training/madhubani_lora_v2/training/<ts>/checkpoints/lora_adapter.safetensors

  # Compare multiple LoRA scales (sweep)
  python3 bin/eval_lora.py --lora <path> --scales 0.5,0.75,1.0

  # Use a smaller resolution to iterate faster (eval-time only)
  python3 bin/eval_lora.py --lora <path> --width 768 --height 768

The base-condition renders are cached in `eval_lora_cache/base/`
keyed by (slug, seed, width, height). Repeat invocations of this
script with the same dimensions reuse the cached base renders, so
only the LoRA condition re-renders. Pass `--no-cache` to force fresh
baselines.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from best_of_n import score_render  # noqa: E402

HOLDOUT_PATH = ROOT / "brand/madhubani/lora_v1_holdout.json"
ANIMALS_PATH = ROOT / "brand/madhubani/animals.json"
DEFAULT_OUT = ROOT / "generated/madhubani_animals/lora_eval"
BASE_CACHE = ROOT / "generated/madhubani_animals/lora_eval/_base_cache"

STYLE_KEY = (
    "a madhubani folk art painting in the mithila tradition of bihar, india: "
    "double-line black outlines, flat folk-color panels in indigo and vermillion "
    "and saffron, seven ornamental decoration zones on the body, almond eyes with "
    "watchful ceremonial gravity, no naturalistic species coloring."
)


def load_holdout() -> dict[str, Any]:
    return json.loads(HOLDOUT_PATH.read_text())


def load_animals_index() -> dict[str, dict]:
    payload = json.loads(ANIMALS_PATH.read_text())
    return {a["slug"]: a for a in payload["animals"]}


def eval_prompt(animal: dict) -> str:
    """Same caption template as build_lora_dataset_v2.STYLE_KEY +
    subject — keeps eval honest (same conditioning shape as training)."""
    display = animal.get("display_name") or animal["slug"]
    body = animal.get("body_type", "")
    return (
        f"{STYLE_KEY} a {display.lower()} ({body}), side profile, standing alert, "
        f"centered composition on cream background."
    )


def run_render(prompt: str, seed: int, out_path: Path, *,
               width: int, height: int, steps: int,
               quantize: int, lora_path: Path | None, lora_scale: float,
               timeout: int) -> int:
    """Invoke `mflux-generate-z-image` for one render. Returns the
    subprocess return code (0 = success)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "mflux-generate-z-image",
        "--model", "z-image-turbo",
        "--quantize", str(quantize),
        "--prompt", prompt,
        "--seed", str(seed),
        "--steps", str(steps),
        "--width", str(width),
        "--height", str(height),
        "--output", str(out_path),
    ]
    if lora_path is not None:
        cmd.extend(["--lora-paths", str(lora_path),
                    "--lora-scales", str(lora_scale)])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            print(f"  ! render failed (rc={proc.returncode}): {proc.stderr[-400:]}",
                  file=sys.stderr)
        return proc.returncode
    except subprocess.TimeoutExpired:
        print(f"  ! render timed out after {timeout}s", file=sys.stderr)
        return -2
    except FileNotFoundError:
        print("  ! mflux-generate-z-image not on PATH. Install mflux (pip install mflux).",
              file=sys.stderr)
        return -3


def render_and_score(
    animal: dict,
    seed: int,
    out_dir: Path,
    *,
    width: int, height: int, steps: int, quantize: int,
    lora_path: Path | None, lora_scale: float,
    use_cache: bool, base_cache_dir: Path,
    timeout: int,
) -> dict[str, Any]:
    """Render one (animal × seed × condition), score it, return the row."""
    prompt = eval_prompt(animal)
    is_base = lora_path is None
    if is_base:
        cached = base_cache_dir / f"{animal['slug']}_seed{seed}_{width}x{height}.png"
        if use_cache and cached.exists():
            render_path = cached
            cached_hit = True
        else:
            render_path = cached
            cached_hit = False
            rc = run_render(prompt, seed, render_path,
                            width=width, height=height, steps=steps,
                            quantize=quantize, lora_path=None, lora_scale=1.0,
                            timeout=timeout)
            if rc != 0:
                return {"slug": animal["slug"], "seed": seed, "condition": "base",
                        "render_path": None, "error": f"render rc={rc}"}
    else:
        scale_tag = f"s{int(lora_scale * 100):03d}"
        render_path = out_dir / f"{animal['slug']}_seed{seed}_lora_{scale_tag}.png"
        cached_hit = False
        rc = run_render(prompt, seed, render_path,
                        width=width, height=height, steps=steps,
                        quantize=quantize, lora_path=lora_path, lora_scale=lora_scale,
                        timeout=timeout)
        if rc != 0:
            return {"slug": animal["slug"], "seed": seed, "condition": "lora",
                    "render_path": None, "error": f"render rc={rc}"}

    scored = score_render(render_path, animal)
    return {
        "slug": animal["slug"],
        "seed": seed,
        "condition": "base" if is_base else "lora",
        "lora_scale": None if is_base else lora_scale,
        "cached": cached_hit,
        "prompt": prompt,
        "render_path": str(render_path),
        "composite": scored["composite"],
        "rubric_pass_fraction": scored["rubric_pass_fraction"],
        "clip_likeness_probability": scored["clip_likeness_probability"],
        "auto_qc_pass": scored["auto_qc_pass"],
        "failed_checks": scored.get("qc_summary", {}).get("failed_checks", []),
    }


def compute_deltas(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Per-(slug, seed, scale) paired delta = lora - base."""
    pairs: dict[tuple[str, int, float | None], dict[str, dict[str, Any]]] = {}
    for r in rows:
        if r.get("render_path") is None:
            continue
        key = (r["slug"], r["seed"], r.get("lora_scale"))
        if r["condition"] == "base":
            # base maps to each lora scale; we re-key after we know the scales
            continue
        bucket = pairs.setdefault(key, {})
        bucket["lora"] = r

    # Re-index base rows by (slug, seed); pair them with every lora scale.
    base_by_key = {(r["slug"], r["seed"]): r for r in rows if r["condition"] == "base"}
    paired_rows = []
    for key, bucket in pairs.items():
        slug, seed, scale = key
        base = base_by_key.get((slug, seed))
        if not base:
            continue
        lora = bucket["lora"]
        paired_rows.append({
            "slug": slug,
            "seed": seed,
            "lora_scale": scale,
            "base_composite": base["composite"],
            "lora_composite": lora["composite"],
            "delta_composite": round(lora["composite"] - base["composite"], 4),
            "base_rubric": base["rubric_pass_fraction"],
            "lora_rubric": lora["rubric_pass_fraction"],
            "delta_rubric": round(lora["rubric_pass_fraction"] - base["rubric_pass_fraction"], 4),
            "base_clip": base["clip_likeness_probability"],
            "lora_clip": lora["clip_likeness_probability"],
            "delta_clip": (
                round(lora["clip_likeness_probability"] - base["clip_likeness_probability"], 4)
                if base["clip_likeness_probability"] is not None
                and lora["clip_likeness_probability"] is not None
                else None
            ),
            "base_render": base["render_path"],
            "lora_render": lora["render_path"],
        })

    # Per-species aggregates (averaged across seeds, per scale).
    per_species: dict[tuple[str, float | None], dict[str, Any]] = {}
    for p in paired_rows:
        key = (p["slug"], p["lora_scale"])
        bucket = per_species.setdefault(key, {"deltas": [], "rubric_deltas": [], "clip_deltas": []})
        bucket["deltas"].append(p["delta_composite"])
        bucket["rubric_deltas"].append(p["delta_rubric"])
        if p["delta_clip"] is not None:
            bucket["clip_deltas"].append(p["delta_clip"])

    species_summary = []
    for (slug, scale), bucket in per_species.items():
        d = bucket["deltas"]
        rd = bucket["rubric_deltas"]
        cd = bucket["clip_deltas"]
        species_summary.append({
            "slug": slug,
            "lora_scale": scale,
            "n_seeds": len(d),
            "mean_delta_composite": round(sum(d) / max(1, len(d)), 4),
            "mean_delta_rubric": round(sum(rd) / max(1, len(rd)), 4),
            "mean_delta_clip": round(sum(cd) / max(1, len(cd)), 4) if cd else None,
        })

    # Overall mean (averaged across species, per scale).
    by_scale: dict[float | None, list[float]] = {}
    for sp in species_summary:
        by_scale.setdefault(sp["lora_scale"], []).append(sp["mean_delta_composite"])
    overall = []
    for scale, deltas in by_scale.items():
        overall.append({
            "lora_scale": scale,
            "n_species": len(deltas),
            "mean_delta_composite": round(sum(deltas) / max(1, len(deltas)), 4),
        })

    return {
        "paired_rows": paired_rows,
        "per_species": species_summary,
        "overall": overall,
    }


def decision_for(mean_delta: float, thresholds: dict[str, Any]) -> str:
    ship = thresholds.get("ship_lora_if_delta_composite_gte", 0.05)
    shelve = thresholds.get("shelve_lora_if_delta_composite_lt", -0.02)
    if mean_delta >= ship:
        return "SHIP"
    if mean_delta < shelve:
        return "SHELVE"
    return "ITERATE"


def write_html_report(
    rows: list[dict[str, Any]],
    deltas: dict[str, Any],
    lora_path: Path | None,
    scales: list[float],
    out_path: Path,
    thresholds: dict[str, Any],
) -> None:
    """Side-by-side base | LoRA grid, one row per (slug, seed, scale)."""
    paired = deltas["paired_rows"]
    per_species = deltas["per_species"]
    overall = deltas["overall"]

    def img_tag(p: str | None) -> str:
        if not p:
            return '<div class="missing">— no render —</div>'
        # Use relative path so the HTML works when copied around.
        try:
            rel = Path(p).resolve().relative_to(out_path.parent.resolve())
            return f'<img src="{rel}" alt="" loading="lazy">'
        except ValueError:
            return f'<img src="file://{p}" alt="" loading="lazy">'

    def delta_class(d: float, threshold_pos: float = 0.05, threshold_neg: float = -0.02) -> str:
        if d >= threshold_pos:
            return "good"
        if d < threshold_neg:
            return "bad"
        return "neutral"

    overall_html = ""
    for o in overall:
        scale_tag = f"@scale {o['lora_scale']}" if o["lora_scale"] is not None else ""
        dec = decision_for(o["mean_delta_composite"], thresholds)
        overall_html += (
            f'<div class="overall {dec.lower()}">'
            f'<div class="big">{o["mean_delta_composite"]:+.4f}</div>'
            f'<div class="sub">mean ΔComposite {scale_tag}</div>'
            f'<div class="decision">{dec}</div>'
            f'</div>'
        )

    species_rows_html = ""
    for sp in per_species:
        cls = delta_class(sp["mean_delta_composite"])
        clip_cell = (
            f'<td class="num">{sp["mean_delta_clip"]:+.4f}</td>'
            if sp["mean_delta_clip"] is not None
            else '<td class="num">—</td>'
        )
        species_rows_html += (
            f'<tr class="{cls}">'
            f'<td>{sp["slug"]}</td>'
            f'<td>{sp["lora_scale"] if sp["lora_scale"] is not None else "—"}</td>'
            f'<td>{sp["n_seeds"]}</td>'
            f'<td class="num">{sp["mean_delta_composite"]:+.4f}</td>'
            f'<td class="num">{sp["mean_delta_rubric"]:+.4f}</td>'
            f'{clip_cell}'
            f'</tr>'
        )

    pair_html = ""
    for p in sorted(paired, key=lambda x: (x["slug"], x["lora_scale"] or 0, x["seed"])):
        cls = delta_class(p["delta_composite"])
        pair_html += f"""
        <div class="pair {cls}">
          <div class="pair-header">
            <span class="slug">{p["slug"]}</span>
            <span class="meta">seed {p["seed"]} · scale {p["lora_scale"]}</span>
            <span class="delta">{p["delta_composite"]:+.4f}</span>
          </div>
          <div class="grid2">
            <div class="cell">
              <div class="label">base</div>
              {img_tag(p["base_render"])}
              <div class="score">composite <b>{p["base_composite"]:.4f}</b></div>
            </div>
            <div class="cell">
              <div class="label">LoRA</div>
              {img_tag(p["lora_render"])}
              <div class="score">composite <b>{p["lora_composite"]:.4f}</b></div>
            </div>
          </div>
        </div>"""

    lora_name = lora_path.name if lora_path else "(no-LoRA debug run)"
    ts = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>LoRA-v1 eval report — {lora_name}</title>
<style>
  :root {{
    --bg: #F5EFE3; --fg: #1a2952; --muted: #6b6258;
    --ok: #3d7d3d; --warn: #e87722; --bad: #c8261f;
    --card: #fff; --line: #d8cfb8;
  }}
  body {{ background: var(--bg); color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
    margin: 0; padding: 24px; }}
  h1 {{ margin: 0 0 4px; font-size: 22px; }}
  .meta-line {{ color: var(--muted); font-size: 13px; margin-bottom: 16px; }}
  .overall {{ display: inline-block; padding: 16px 24px; margin-right: 16px;
    background: var(--card); border-radius: 8px; border: 1px solid var(--line);
    min-width: 200px; }}
  .overall .big {{ font-size: 28px; font-weight: 700; }}
  .overall .sub {{ font-size: 12px; color: var(--muted); }}
  .overall .decision {{ margin-top: 8px; font-weight: 600; }}
  .overall.ship {{ border-color: var(--ok); }}
  .overall.ship .decision {{ color: var(--ok); }}
  .overall.shelve {{ border-color: var(--bad); }}
  .overall.shelve .decision {{ color: var(--bad); }}
  .overall.iterate {{ border-color: var(--warn); }}
  .overall.iterate .decision {{ color: var(--warn); }}
  table {{ border-collapse: collapse; background: var(--card);
    margin: 16px 0 32px; width: 100%; max-width: 800px; }}
  th, td {{ padding: 6px 12px; text-align: left; border-bottom: 1px solid var(--line);
    font-size: 13px; }}
  td.num {{ text-align: right; font-family: -apple-system; font-variant-numeric: tabular-nums; }}
  tr.good td.num {{ color: var(--ok); font-weight: 600; }}
  tr.bad td.num {{ color: var(--bad); font-weight: 600; }}
  .pair {{ background: var(--card); border: 1px solid var(--line); border-radius: 8px;
    margin-bottom: 16px; overflow: hidden; }}
  .pair.good {{ border-left: 4px solid var(--ok); }}
  .pair.bad {{ border-left: 4px solid var(--bad); }}
  .pair.neutral {{ border-left: 4px solid var(--warn); }}
  .pair-header {{ padding: 10px 14px; display: flex; justify-content: space-between;
    align-items: center; border-bottom: 1px solid var(--line); background: var(--bg); }}
  .pair-header .slug {{ font-weight: 700; }}
  .pair-header .meta {{ color: var(--muted); font-size: 12px; }}
  .pair-header .delta {{ font-family: -apple-system; font-variant-numeric: tabular-nums;
    font-weight: 700; }}
  .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 0; }}
  .cell {{ padding: 12px; border-right: 1px solid var(--line); }}
  .cell:last-child {{ border-right: none; }}
  .cell .label {{ font-size: 11px; text-transform: uppercase; color: var(--muted);
    letter-spacing: 0.05em; margin-bottom: 6px; }}
  .cell img {{ width: 100%; aspect-ratio: 1; object-fit: contain; background: #ece2cf;
    border-radius: 4px; }}
  .cell .score {{ font-size: 12px; margin-top: 6px; }}
  .missing {{ background: #ece2cf; aspect-ratio: 1; display: flex;
    align-items: center; justify-content: center; color: var(--bad); font-size: 12px; border-radius: 4px; }}
</style>
</head>
<body>
  <h1>LoRA-v1 eval report</h1>
  <div class="meta-line">{lora_name} · scales {scales} · generated {ts}</div>

  {overall_html}

  <h2>Per-species summary</h2>
  <table>
    <thead><tr><th>species</th><th>scale</th><th>n seeds</th>
      <th class="num">Δ composite</th><th class="num">Δ rubric</th><th class="num">Δ CLIP</th>
    </tr></thead>
    <tbody>{species_rows_html}</tbody>
  </table>

  <h2>Side-by-side grid</h2>
  {pair_html}
</body></html>"""
    out_path.write_text(html, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lora", type=Path,
                        help="Path to trained LoRA adapter .safetensors")
    parser.add_argument("--scales", default="1.0",
                        help="Comma-separated LoRA scales to sweep (e.g., 0.5,0.75,1.0)")
    parser.add_argument("--no-lora-debug", action="store_true",
                        help="Render base condition only — sanity-checks the eval pipeline before LoRA training finishes")
    parser.add_argument("--width", type=int, default=1024)
    parser.add_argument("--height", type=int, default=1024)
    parser.add_argument("--steps", type=int, default=9)
    parser.add_argument("--quantize", type=int, default=4)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--no-cache", action="store_true",
                        help="Force fresh base-condition renders even if cached")
    parser.add_argument("--timeout", type=int, default=180,
                        help="Per-render timeout in seconds (default: 180)")
    args = parser.parse_args()

    if not args.no_lora_debug and not args.lora:
        parser.error("--lora is required (or use --no-lora-debug for pipeline sanity check)")

    scales = [float(s.strip()) for s in args.scales.split(",") if s.strip()]
    if not scales:
        scales = [1.0]

    holdout = load_holdout()
    animals_idx = load_animals_index()
    thresholds = holdout.get("eval_protocol", {}).get("decision_thresholds", {})

    out_dir = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    base_cache = BASE_CACHE.resolve()
    base_cache.mkdir(parents=True, exist_ok=True)

    print(f"Eval output: {out_dir.relative_to(ROOT)}")
    print(f"Base-render cache: {base_cache.relative_to(ROOT)}")
    print(f"LoRA: {args.lora.name if args.lora else '— skipped —'}")
    print(f"Scales: {scales}")
    print(f"Dimensions: {args.width}×{args.height}, {args.steps} steps, q{args.quantize}")
    print()

    rows: list[dict[str, Any]] = []
    use_cache = not args.no_cache

    for h in holdout["held_out_species"]:
        slug = h["slug"]
        animal = animals_idx.get(slug)
        if not animal:
            print(f"  ! held-out species '{slug}' not in animals.json — skipping")
            continue
        for seed in h.get("eval_seeds", [42, 1337]):
            # Base render (cached by default)
            print(f"  base   {slug:18s} seed={seed} ...", end="", flush=True)
            row = render_and_score(
                animal, seed, out_dir,
                width=args.width, height=args.height, steps=args.steps,
                quantize=args.quantize, lora_path=None, lora_scale=1.0,
                use_cache=use_cache, base_cache_dir=base_cache,
                timeout=args.timeout,
            )
            if row.get("render_path") is None:
                print(f"  ✗ {row.get('error')}")
            else:
                tag = " (cached)" if row.get("cached") else ""
                print(f"  composite={row['composite']:.4f}{tag}")
            rows.append(row)

            # LoRA renders, one per scale
            if args.lora:
                for scale in scales:
                    print(f"  lora   {slug:18s} seed={seed} scale={scale} ...",
                          end="", flush=True)
                    row = render_and_score(
                        animal, seed, out_dir,
                        width=args.width, height=args.height, steps=args.steps,
                        quantize=args.quantize, lora_path=args.lora.resolve(), lora_scale=scale,
                        use_cache=False, base_cache_dir=base_cache,
                        timeout=args.timeout,
                    )
                    if row.get("render_path") is None:
                        print(f"  ✗ {row.get('error')}")
                    else:
                        print(f"  composite={row['composite']:.4f}")
                    rows.append(row)

    deltas = compute_deltas(rows)

    # Write JSON report
    json_path = out_dir / "eval_lora_report.json"
    summary_obj = {
        "schema": "forge.lora_eval.v1",
        "ts": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lora_path": str(args.lora) if args.lora else None,
        "scales": scales,
        "config": {
            "width": args.width, "height": args.height,
            "steps": args.steps, "quantize": args.quantize,
        },
        "thresholds": thresholds,
        "rows": rows,
        "deltas": deltas,
        "overall_decision": (
            [decision_for(o["mean_delta_composite"], thresholds) for o in deltas["overall"]]
            if deltas["overall"] else ["NO-PAIRS"]
        ),
    }
    json_path.write_text(json.dumps(summary_obj, indent=2))
    print()
    print(f"Wrote {json_path.relative_to(ROOT)}")

    # Write HTML report
    html_path = out_dir / "eval_lora_report.html"
    write_html_report(rows, deltas, args.lora, scales, html_path, thresholds)
    print(f"Wrote {html_path.relative_to(ROOT)}")

    # Verdict line
    print()
    for o in deltas["overall"]:
        dec = decision_for(o["mean_delta_composite"], thresholds)
        scale_tag = f" @scale {o['lora_scale']}" if o["lora_scale"] is not None else ""
        print(f"  Overall ΔComposite{scale_tag}: {o['mean_delta_composite']:+.4f}  →  {dec}")
    print()
    print(f"  open {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
