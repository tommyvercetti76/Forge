#!/usr/bin/env python3
"""Build the v6 init-image index from a species-curation export.

Reads `species_curation_<date>.json` (exported from the species curation
contact sheet) and emits `brand/madhubani/v6_init_images.json` — a
mapping from `slug → canonical photo path + metadata` that the v6 batch
driver uses to feed Kontext img2img during rendering.

The init-image is passed to mflux as `--image-path` with strength 0.4
(tunable per-species). Strength 0.4 means: "the species photo seeds the
diffusion's spatial geometry, but the Madhubani prompt still drives the
final style + decoration." Higher strength = more anatomical fidelity to
the photo; lower = more model creative freedom.

Usage:
  # Standard — pick up the freshest curation export from Downloads:
  python3 bin/build_v6_init_index.py \\
      --curation ~/Downloads/species_curation_2026-05-22.json

  # Override default strength:
  python3 bin/build_v6_init_index.py \\
      --curation ~/Downloads/species_curation_2026-05-22.json \\
      --default-strength 0.5

Output schema:
  {
    "schema": "forge.v6_init_images.v1",
    "established": "2026-05-22T...",
    "default_strength": 0.4,
    "n_species_with_canonical": 37,
    "n_species_missing_canonical": 4,
    "missing_slugs": ["..."],
    "init_images": {
      "snow-leopard": {
        "image_path": "brand/references/species/snow-leopard/01_wikimedia_commons.jpg",
        "strength": 0.4,
        "photo_id": "01_wikimedia_commons",
        "sex_tag": "unknown",
        "pose_tag": "side-profile",
        "notes": "...",
        "attribution_path": "...attribution.json",
        "sha256": "...",
        "width": 4250,
        "height": 2888,
        "photographer": "H. Zell",
        "license": "CC BY-SA 3.0"
      },
      ...
    }
  }
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECIES_ROOT = ROOT / "brand" / "references" / "species"
DEFAULT_OUT = ROOT / "brand" / "madhubani" / "v6_init_images.json"


def find_canonical_photo(slug: str, photo_id: str) -> Path | None:
    """Locate the actual binary file for (slug, photo_id). Photos might
    have .jpg/.png extension (after audit) or no extension (pre-audit)."""
    species_dir = SPECIES_ROOT / slug
    if not species_dir.exists():
        return None
    # Try with common extensions first
    for ext in (".jpg", ".jpeg", ".png", ".webp", ""):
        candidate = species_dir / (photo_id + ext)
        if candidate.exists() and not candidate.name.endswith(".attribution.json"):
            return candidate
    return None


def find_attribution(image_path: Path) -> Path | None:
    """Locate the .attribution.json paired with image_path."""
    candidates = [
        image_path.parent / f"{image_path.stem}.attribution.json",
        image_path.parent / f"{image_path.name}.attribution.json",
        image_path.with_suffix(image_path.suffix + ".attribution.json"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--curation", type=Path, required=True,
                        help="Path to the species_curation_*.json export")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"Output path (default: {DEFAULT_OUT.relative_to(ROOT)})")
    parser.add_argument("--default-strength", type=float, default=0.4,
                        help="Default --init-image-strength when species doesn't override (default: 0.4)")
    args = parser.parse_args()

    if not args.curation.exists():
        raise SystemExit(f"curation export not found: {args.curation}")

    curation = json.loads(args.curation.read_text())
    canonical_by_slug = curation.get("canonical_by_slug", {})
    photos_by_key = {}
    for p in curation.get("photos", []):
        key = f"{p['slug']}::{p['photo_id']}"
        photos_by_key[key] = p

    init_images = {}
    missing = []
    for slug, photo_key in canonical_by_slug.items():
        if not photo_key:
            missing.append(slug)
            continue
        photo_meta = photos_by_key.get(photo_key, {})
        photo_id = photo_meta.get("photo_id") or photo_key.split("::")[-1]
        image_path = find_canonical_photo(slug, photo_id)
        if not image_path:
            print(f"  ! {slug}: canonical photo '{photo_id}' not found on disk", file=sys.stderr)
            missing.append(slug)
            continue
        attr_path = find_attribution(image_path)
        attr_data = {}
        if attr_path:
            try:
                attr_data = json.loads(attr_path.read_text())
            except Exception:
                pass
        try:
            rel_image = str(image_path.relative_to(ROOT))
        except ValueError:
            rel_image = str(image_path)
        init_images[slug] = {
            "image_path": rel_image,
            "strength": args.default_strength,
            "photo_id": photo_id,
            "sex_tag": photo_meta.get("sex", "unknown"),
            "pose_tag": photo_meta.get("pose", ""),
            "notes": photo_meta.get("notes", ""),
            "attribution_path": str(attr_path.relative_to(ROOT)) if attr_path else None,
            "sha256": attr_data.get("sha256"),
            "width": attr_data.get("width"),
            "height": attr_data.get("height"),
            "photographer": attr_data.get("photographer"),
            "license": attr_data.get("license"),
            "source_url": attr_data.get("source_url"),
        }

    # Find species in animals.json that don't have a canonical pick
    animals_path = ROOT / "brand" / "madhubani" / "animals.json"
    all_slugs = {a["slug"] for a in json.loads(animals_path.read_text())["animals"]}
    fully_missing = sorted(all_slugs - set(canonical_by_slug.keys()) - set(missing))

    payload = {
        "schema": "forge.v6_init_images.v1",
        "established": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "default_strength": args.default_strength,
        "curation_source": str(args.curation),
        "curation_ts": curation.get("ts"),
        "n_species_with_canonical": len(init_images),
        "n_species_missing_canonical": len(fully_missing) + len(missing),
        "missing_slugs": fully_missing + missing,
        "init_images": init_images,
    }
    args.out.write_text(json.dumps(payload, indent=2))

    print(f"Built v6 init-image index → {args.out.relative_to(ROOT)}")
    print(f"  Species with canonical photo: {len(init_images)}")
    print(f"  Species missing canonical:    {len(fully_missing) + len(missing)}")
    if fully_missing or missing:
        all_missing = sorted(set(fully_missing) | set(missing))
        print(f"  Missing slugs (need curation): {all_missing[:15]}{'...' if len(all_missing) > 15 else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
