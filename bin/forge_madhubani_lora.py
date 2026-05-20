#!/usr/bin/env python3
"""Forge Madhubani LoRA pilot — data prep + config emit + dry-run gate.

Wires the Mithila reference corpus (`brand/references/madhubani/_general/`)
into a self-contained training dataset under `training/madhubani_lora/`
and emits an `mflux-train`-compatible `train.json`. Defaults target the
local Apple Silicon stack:

  - Base model: z-image-turbo (small, fast, Apple-Silicon native)
  - LoRA rank: 16
  - 200 steps, batch_size=1 (a real but bounded pilot)
  - Quantize: 4-bit on-the-fly (fits comfortably on M5 Max)
  - Auto-generated captions from the per-asset `attribution.json` sidecars

To run training:

  # 1. Prepare the dataset + config (this script)
  python3 bin/forge_madhubani_lora.py prep --out training/madhubani_lora

  # 2. Sanity-check the config without burning compute
  mflux-train --config training/madhubani_lora/train.json --dry-run

  # 3. Real training (writes loss plot + samples every N steps)
  mflux-train --config training/madhubani_lora/train.json

  # 4. The trained adapter lands at:
  #    training/madhubani_lora/training/<timestamp>/checkpoints/lora_adapter.safetensors

Outputs:
  training/madhubani_lora/
    images/
      <slug>.jpg          # symlink to brand/references/madhubani/_general/<file>
      <slug>.txt          # caption (auto-derived from attribution.json)
      preview.png         # one preview image (smallest reference)
      preview.txt         # one preview prompt
      preview_tiger.txt   # a second preview prompt for variety
    train.json            # mflux-train config
    DATASET.md            # provenance + license summary
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CORPUS_ROOT = ROOT / "brand/references/madhubani/_general"
DEFAULT_OUT = ROOT / "training/madhubani_lora"

# Caption template — concise, includes tradition + visual register cues so
# the LoRA learns the style key "madhubani folk art" rather than the
# subject of any individual training image.
CAPTION_TEMPLATE = (
    "a madhubani folk art painting in the mithila tradition of bihar, "
    "india, with double-line black outlines, flat folk-color panels in "
    "indigo / vermillion / saffron / leaf-green, fish-eye motifs, "
    "densely decorated with floral medallions and lotus patterns. "
    "{specific}"
)


@dataclass
class Sample:
    src: Path
    dst_image: Path
    dst_caption: Path
    caption: str
    license: str
    source_url: str


def derive_caption(attribution: dict, filename: str) -> str:
    """Build a caption from attribution metadata. Falls back gracefully
    when fields are missing."""
    title = attribution.get("title") or attribution.get("description") or filename
    # Strip the prefix "File:" if present (Wikimedia convention).
    if title.lower().startswith("file:"):
        title = title[5:].strip()
    # Trim the extension; soften file-name slugification to natural text.
    if "." in title:
        title = title.rsplit(".", 1)[0]
    title = title.replace("-", " ").replace("_", " ").strip().lower()
    # Cap length so the conditioning prompt isn't dominated by metadata.
    if len(title) > 80:
        title = title[:80].rsplit(" ", 1)[0]
    return CAPTION_TEMPLATE.format(specific=title)


def collect_samples(corpus_root: Path, out_image_dir: Path) -> list[Sample]:
    """Find every image with a sibling attribution.json. Skip extensions
    that mflux-train won't load."""
    accepted_exts = {".jpg", ".jpeg", ".png", ".webp"}
    samples: list[Sample] = []
    for path in sorted(corpus_root.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in accepted_exts:
            continue
        attr_path = path.with_name(path.name + ".attribution.json")
        if not attr_path.exists():
            continue
        try:
            attribution = json.loads(attr_path.read_text())
        except json.JSONDecodeError:
            print(f"WARN: skipping {path.name} — malformed attribution.json", file=sys.stderr)
            continue
        # Use a slugified stem so the dataset dir is clean.
        slug_parts = []
        for ch in path.stem.lower():
            if ch.isalnum():
                slug_parts.append(ch)
            elif ch in "-_ ":
                slug_parts.append("-")
        slug = "".join(slug_parts).strip("-")
        while "--" in slug:
            slug = slug.replace("--", "-")
        if not slug:
            slug = f"img-{len(samples):03d}"
        # Suffix preserved to match source.
        ext = path.suffix.lower()
        if ext == ".jpeg":
            ext = ".jpg"
        dst_image = out_image_dir / f"{slug}{ext}"
        dst_caption = out_image_dir / f"{slug}.txt"
        caption = derive_caption(attribution, path.stem)
        samples.append(Sample(
            src=path,
            dst_image=dst_image,
            dst_caption=dst_caption,
            caption=caption,
            license=str(attribution.get("license", "unknown")),
            source_url=str(attribution.get("source_url", "")),
        ))
    return samples


def write_dataset(samples: list[Sample], out_image_dir: Path) -> None:
    out_image_dir.mkdir(parents=True, exist_ok=True)
    # Symlink images instead of copying — preserves disk usage and keeps
    # provenance obvious. Captions are written fresh each time.
    for sample in samples:
        if sample.dst_image.exists() or sample.dst_image.is_symlink():
            sample.dst_image.unlink()
        os.symlink(sample.src.resolve(), sample.dst_image)
        sample.dst_caption.write_text(sample.caption, encoding="utf-8")


def write_preview(out_image_dir: Path, samples: list[Sample]) -> None:
    """Style-LoRA preview prompts (no preview image — those are reserved
    for edit-training only per mflux-train)."""
    if not samples:
        return
    # Two preview prompts so the loss/preview view shows generalization, not
    # just the conditioning prompt overfitting.
    (out_image_dir / "preview.txt").write_text(
        "a madhubani folk art painting of a tiger, double-line black outlines, "
        "flat folk-color panels with lotus medallions, indigo and vermillion "
        "palette, cream background, mithila tradition",
        encoding="utf-8",
    )
    (out_image_dir / "preview_peacock.txt").write_text(
        "a madhubani folk art painting of a peacock with full tail fan, "
        "double-line black outlines, dense floral medallions, indigo body "
        "with vermillion ocellus motifs, mithila tradition",
        encoding="utf-8",
    )


def write_config(out_dir: Path, image_subdir: str) -> Path:
    """Emit mflux-train config. Targets z-image-turbo because (1) it has
    Apple Silicon-native MLX weights, (2) trains end-to-end fast enough
    for a pilot, and (3) is the same encoder family Forge already uses
    in production for the Z-Image path."""
    # Pilot defaults are sized for one M5 Max session, not a real LoRA.
    # Empirically: ~60-115 s / training iteration at max_resolution=1024,
    # so num_epochs=200 over 50 images = 10000 iterations ≈ multi-day.
    # We default to a SMOKE pilot here (num_epochs=1, max_resolution=512)
    # that completes in ~30-50 min on M5 Max and produces a real adapter
    # checkpoint end-to-end. The full overnight recipe is documented in
    # docs/LORA_TRAINING_RECIPE.md.
    config = {
        "model": "z-image-turbo",
        "data": image_subdir,
        "seed": 42,
        "steps": 9,
        "guidance": 0.0,
        "quantize": 4,
        "max_resolution": 512,
        "low_ram": False,
        "training_loop": {
            "num_epochs": 1,
            "batch_size": 1,
            "timestep_low": 4,
            "timestep_high": 9,
        },
        "optimizer": {
            "name": "AdamW",
            "learning_rate": 1e-4,
        },
        "checkpoint": {
            "save_frequency": 25,
            "output_path": "training",
        },
        "monitoring": {
            "preview_width": 512,
            "preview_height": 512,
            "plot_frequency": 1,
            "generate_image_frequency": 50,
            "smooth_loss": True,
            "smooth_loss_window": 5,
        },
        "lora_layers": {
            "targets": [
                {"module_path": "layers.{block}.attention.to_q", "blocks": {"start": 0, "end": 30}, "rank": 16},
                {"module_path": "layers.{block}.attention.to_k", "blocks": {"start": 0, "end": 30}, "rank": 16},
                {"module_path": "layers.{block}.attention.to_v", "blocks": {"start": 0, "end": 30}, "rank": 16},
                {"module_path": "layers.{block}.attention.to_out.0", "blocks": {"start": 0, "end": 30}, "rank": 16},
                {"module_path": "layers.{block}.feed_forward.w1", "blocks": {"start": 0, "end": 30}, "rank": 16},
                {"module_path": "layers.{block}.feed_forward.w2", "blocks": {"start": 0, "end": 30}, "rank": 16},
                {"module_path": "layers.{block}.feed_forward.w3", "blocks": {"start": 0, "end": 30}, "rank": 16},
                {"module_path": "cap_embedder.1", "rank": 16},
                {"module_path": "all_final_layer.2-1.linear", "rank": 16},
            ],
        },
    }
    config_path = out_dir / "train.json"
    config_path.write_text(json.dumps(config, indent=2))
    return config_path


def write_dataset_md(out_dir: Path, samples: list[Sample]) -> None:
    lines = [
        "# Madhubani LoRA training dataset (pilot)",
        "",
        f"Total samples: **{len(samples)}**",
        "",
        "Every training image is symlinked from `brand/references/madhubani/_general/`",
        "and ships with attribution under the same source URL + license. Captions",
        "are derived from each asset's `attribution.json` plus a shared style key",
        "(`madhubani folk art painting in the mithila tradition of bihar, india ...`)",
        "so the LoRA learns the *style*, not any particular subject identity.",
        "",
        "## Licenses",
        "",
        "| Image | License | Source |",
        "| :--- | :--- | :--- |",
    ]
    for sample in samples:
        url = sample.source_url[:80] + ("..." if len(sample.source_url) > 80 else "")
        lines.append(f"| `{sample.dst_image.name}` | {sample.license} | <{url}> |")
    lines.extend([
        "",
        "## Captions",
        "",
        "Every `<slug>.txt` follows this template — the *style* key is shared and",
        "the *specific* phrase is derived from the source title:",
        "",
        "```",
        CAPTION_TEMPLATE,
        "```",
        "",
        "## Preview prompts",
        "",
        "`preview.txt` and `preview_peacock.txt` are out-of-distribution prompts",
        "used by `mflux-train` to render samples every `generate_image_frequency`",
        "steps. They are *not* in the training set — they test generalization.",
    ])
    (out_dir / "DATASET.md").write_text("\n".join(lines) + "\n")


def cmd_prep(args: argparse.Namespace) -> int:
    out_dir = Path(args.out).resolve()
    image_subdir = "images"
    out_image_dir = out_dir / image_subdir

    print(f"Scanning corpus: {CORPUS_ROOT.relative_to(ROOT)}")
    samples = collect_samples(CORPUS_ROOT, out_image_dir)
    if not samples:
        print(f"ERROR: no samples found under {CORPUS_ROOT}", file=sys.stderr)
        return 1
    print(f"Found {len(samples)} images with attribution.json sidecars.")

    if out_dir.exists() and args.force:
        print(f"Removing existing {out_dir}")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Writing dataset to {out_dir.relative_to(ROOT)}/{image_subdir}/")
    write_dataset(samples, out_image_dir)
    write_preview(out_image_dir, samples)
    config_path = write_config(out_dir, image_subdir)
    write_dataset_md(out_dir, samples)

    print()
    print(f"Wrote {config_path.relative_to(ROOT)}")
    print(f"Wrote {out_dir.relative_to(ROOT)}/DATASET.md")
    print(f"Total artifacts in {out_image_dir.relative_to(ROOT)}: {len(list(out_image_dir.iterdir()))}")
    print()
    print("Next steps:")
    print(f"  mflux-train --config {config_path.relative_to(ROOT)} --dry-run     # validate config")
    print(f"  mflux-train --config {config_path.relative_to(ROOT)}               # real training")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    prep = sub.add_parser("prep", help="Build the training dataset + config")
    prep.add_argument("--out", default=str(DEFAULT_OUT.relative_to(ROOT)),
                      help="Output directory (default: training/madhubani_lora)")
    prep.add_argument("--force", action="store_true",
                      help="Remove existing output directory first")
    prep.set_defaults(func=cmd_prep)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
