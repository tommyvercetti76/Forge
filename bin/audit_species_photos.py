#!/usr/bin/env python3
"""Audit + SHA-256 backfill for the species photo corpus.

Walks `brand/references/species/<slug>/` and for each rehydrated photo:

  1. Validates it opens as a real image (PIL — catches HTML pages, truncated
     downloads, wrong formats).
  2. Computes the SHA-256 of the binary.
  3. Reads actual width + height + mode.
  4. Renames the file to add a `.jpg` (or `.png`/`.webp`) extension if missing.
  5. Back-writes the sha256 + dimensions + final filename into the matching
     `.attribution.json` — closes the provenance loop.

Output: a per-species audit report + a single aggregate
`brand/references/species/_audit.json`.

Usage:
  python3 bin/audit_species_photos.py                       # audit all species
  python3 bin/audit_species_photos.py --species snow-leopard # one species
  python3 bin/audit_species_photos.py --no-rename            # validate + hash but don't rename
  python3 bin/audit_species_photos.py --dry-run              # report only, no writes
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECIES_ROOT = ROOT / "brand" / "references" / "species"


def sniff_image(path: Path) -> dict | None:
    """Return {format, width, height, mode, sha256, size_bytes} or None if not an image."""
    try:
        from PIL import Image
        with Image.open(path) as img:
            img.load()  # force decode (catches truncated files)
            fmt = (img.format or "").lower()
            w, h = img.size
            mode = img.mode
    except Exception:
        return None
    blob = path.read_bytes()
    return {
        "format": fmt,
        "ext": {"jpeg": ".jpg", "png": ".png", "webp": ".webp"}.get(fmt, ".bin"),
        "width": w,
        "height": h,
        "mode": mode,
        "sha256": hashlib.sha256(blob).hexdigest(),
        "size_bytes": len(blob),
    }


def find_attribution_for(image_path: Path) -> Path | None:
    """Map an image file to its sibling .attribution.json. Handles both
    `01_wikimedia_commons` (no ext, current state) and `01_wikimedia_commons.jpg`
    (after rename)."""
    candidates = [
        image_path.with_suffix(image_path.suffix + ".attribution.json"),  # X.jpg → X.jpg.attribution.json
        image_path.parent / f"{image_path.stem}.attribution.json",         # X.jpg → X.attribution.json
        image_path.parent / f"{image_path.name}.attribution.json",          # X     → X.attribution.json (no-ext case)
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def audit_one_species(species_dir: Path, *,
                      rename: bool = True, dry_run: bool = False) -> dict:
    """Walk a single species' photo dir, audit + backfill each photo."""
    slug = species_dir.name
    files = sorted([p for p in species_dir.iterdir() if not p.name.endswith(".attribution.json")])
    summary = {
        "slug": slug,
        "n_files_found": len(files),
        "n_valid": 0,
        "n_invalid": 0,
        "n_renamed": 0,
        "n_backfilled": 0,
        "photos": [],
        "errors": [],
    }
    for f in files:
        sniff = sniff_image(f)
        if sniff is None:
            summary["n_invalid"] += 1
            summary["errors"].append(f"{f.name}: not a valid image")
            continue
        summary["n_valid"] += 1
        # Locate the attribution.json
        attr_path = find_attribution_for(f)
        final_path = f
        # Rename to add proper extension if missing or wrong
        if rename and not dry_run:
            target_name = f.name if f.suffix == sniff["ext"] else f.name + sniff["ext"]
            target = f.parent / target_name
            if f != target:
                if target.exists():
                    target.unlink()  # idempotent
                f.rename(target)
                final_path = target
                summary["n_renamed"] += 1
        # Backfill attribution.json
        if attr_path and not dry_run:
            try:
                data = json.loads(attr_path.read_text())
                data["sha256"] = sniff["sha256"]
                data["width"] = sniff["width"]
                data["height"] = sniff["height"]
                data["mode"] = sniff["mode"]
                data["filename"] = final_path.name
                data["audited_at"] = dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
                attr_path.write_text(json.dumps(data, indent=2))
                summary["n_backfilled"] += 1
            except Exception as exc:
                summary["errors"].append(f"{attr_path.name}: backfill failed ({exc})")
        summary["photos"].append({
            "filename": final_path.name,
            "format": sniff["format"],
            "width": sniff["width"],
            "height": sniff["height"],
            "mode": sniff["mode"],
            "sha256": sniff["sha256"][:16],
            "size_kb": sniff["size_bytes"] // 1024,
        })
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--species", help="Audit one species (default: all)")
    parser.add_argument("--no-rename", action="store_true",
                        help="Skip renaming files (just validate + hash + backfill)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report only; don't modify any files")
    parser.add_argument("--out", type=Path,
                        default=SPECIES_ROOT / "_audit.json",
                        help="Aggregate audit report path")
    args = parser.parse_args()

    if not SPECIES_ROOT.exists():
        print(f"Species refs root missing: {SPECIES_ROOT}", file=sys.stderr)
        return 2

    if args.species:
        dirs = [SPECIES_ROOT / args.species]
        if not dirs[0].exists():
            print(f"No such species dir: {dirs[0]}", file=sys.stderr)
            return 2
    else:
        dirs = sorted([d for d in SPECIES_ROOT.iterdir() if d.is_dir() and not d.name.startswith("_")])

    print(f"Auditing {len(dirs)} species under {SPECIES_ROOT.relative_to(ROOT)}/")
    print(f"  Mode: {'DRY-RUN' if args.dry_run else 'WRITE'}, rename: {not args.no_rename}")
    print()

    summaries = []
    for d in dirs:
        s = audit_one_species(d, rename=not args.no_rename, dry_run=args.dry_run)
        status = "✓" if s["n_invalid"] == 0 and s["n_valid"] > 0 else "✗" if s["n_invalid"] > 0 else "·"
        print(f"  {status} {s['slug']:25s} valid={s['n_valid']:2d}  invalid={s['n_invalid']:2d}  "
              f"renamed={s['n_renamed']:2d}  backfilled={s['n_backfilled']:2d}")
        if s["errors"]:
            for e in s["errors"][:3]:
                print(f"      ! {e}")
        summaries.append(s)

    # Aggregate report
    total_valid = sum(s["n_valid"] for s in summaries)
    total_invalid = sum(s["n_invalid"] for s in summaries)
    species_zero = [s["slug"] for s in summaries if s["n_valid"] == 0]
    print()
    print("=" * 60)
    print(f"Total photos validated: {total_valid}")
    print(f"Total photos invalid:   {total_invalid}")
    print(f"Species with ZERO valid photos: {len(species_zero)}")
    if species_zero:
        print(f"  {species_zero[:10]}")
    if not args.dry_run:
        args.out.write_text(json.dumps({
            "schema": "forge.species_photo_audit.v1",
            "audited_at": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "n_species": len(summaries),
            "n_valid": total_valid,
            "n_invalid": total_invalid,
            "species_with_zero": species_zero,
            "summaries": summaries,
        }, indent=2))
        try:
            print(f"\nWrote aggregate audit: {args.out.relative_to(ROOT)}")
        except ValueError:
            print(f"\nWrote aggregate audit: {args.out}")
    return 0 if total_invalid == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
