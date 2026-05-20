#!/usr/bin/env python3
"""Audit the Madhubani reference corpus.

Reports total count, per-species count, license distribution,
missing-attribution count, and a resolution histogram.

Runnable as:
    python3 brand/references/madhubani/_audit.py

No install required. Uses Pillow for resolution if available;
gracefully degrades to "unknown" resolution if not.

Designed to run cleanly on an EMPTY corpus and report zeros.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable

# --- optional Pillow ----------------------------------------------------------
try:
    from PIL import Image  # type: ignore
    _PIL_AVAILABLE = True
except Exception:  # pragma: no cover — Pillow missing is a normal case
    _PIL_AVAILABLE = False


# --- constants ----------------------------------------------------------------
CORPUS_ROOT = Path(__file__).resolve().parent
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".tif", ".tiff"}

# Files/dirs that should be ignored when walking the corpus.
# Anything starting with "_" or "." is treated as scaffolding, not data.
IGNORE_NAME_PREFIXES = ("_", ".")

# Resolution buckets for the histogram.
RES_BUCKETS = [
    ("<512",        lambda w, h: max(w, h) < 512),
    ("512-1023",    lambda w, h: 512 <= max(w, h) < 1024),
    ("1024-1535",   lambda w, h: 1024 <= max(w, h) < 1536),
    ("1536-2047",   lambda w, h: 1536 <= max(w, h) < 2048),
    (">=2048",      lambda w, h: max(w, h) >= 2048),
]


def is_ignored(name: str) -> bool:
    return name.startswith(IGNORE_NAME_PREFIXES)


def species_dirs(root: Path) -> list[Path]:
    """Return all species directories (and _general/)."""
    if not root.is_dir():
        return []
    out = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        out.append(child)
    return out


def image_files(species_dir: Path) -> list[Path]:
    """Image files in a species directory, excluding scaffolding files."""
    out = []
    for p in sorted(species_dir.iterdir()):
        if not p.is_file():
            continue
        if is_ignored(p.name):
            continue
        if p.suffix.lower() in IMAGE_EXTS:
            out.append(p)
    return out


def attribution_path(image: Path) -> Path:
    """Sibling attribution file for an image."""
    return image.with_suffix(image.suffix + ".attribution.json")


def load_attribution(image: Path) -> dict | None:
    """Return parsed attribution JSON, or None if missing/invalid."""
    attr = attribution_path(image)
    if not attr.is_file():
        return None
    try:
        with attr.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def image_resolution(image: Path) -> tuple[int, int] | None:
    """Return (width, height) or None if Pillow unavailable / unreadable."""
    if not _PIL_AVAILABLE:
        return None
    try:
        with Image.open(image) as im:  # type: ignore[union-attr]
            return im.size  # (w, h)
    except Exception:
        return None


def bucket_resolution(w: int, h: int) -> str:
    for label, predicate in RES_BUCKETS:
        if predicate(w, h):
            return label
    return "unknown"


# --- reporting ----------------------------------------------------------------
def render_section(title: str) -> str:
    return f"\n{title}\n{'-' * len(title)}"


def render_count_table(items: Iterable[tuple[str, int]], indent: str = "  ") -> list[str]:
    lines = []
    items = list(items)
    if not items:
        return [f"{indent}(none)"]
    width = max(len(k) for k, _ in items)
    for key, count in items:
        lines.append(f"{indent}{key.ljust(width)}  {count}")
    return lines


def audit(root: Path) -> int:
    """Walk the corpus and print a report. Returns exit code."""
    print(f"Madhubani reference corpus audit")
    print(f"root: {root}")
    if not _PIL_AVAILABLE:
        print("note: Pillow not installed — resolution checks unavailable")

    dirs = species_dirs(root)
    if not dirs:
        print("\nNo species directories found. Corpus appears uninitialized.")
        return 0

    total_images = 0
    per_species: Counter[str] = Counter()
    license_dist: Counter[str] = Counter()
    artist_dist: Counter[str] = Counter()
    missing_attr: list[Path] = []
    res_buckets: Counter[str] = Counter()
    unknown_res_count = 0
    over_cap_species: list[tuple[str, int]] = []
    PER_SPECIES_CAP = 8

    for sdir in dirs:
        imgs = image_files(sdir)
        per_species[sdir.name] = len(imgs)
        total_images += len(imgs)

        if sdir.name != "_general" and len(imgs) > PER_SPECIES_CAP:
            over_cap_species.append((sdir.name, len(imgs)))

        for img in imgs:
            attr = load_attribution(img)
            if attr is None:
                missing_attr.append(img)
            else:
                lic = str(attr.get("license", "unspecified")).strip() or "unspecified"
                license_dist[lic] += 1
                artist = str(attr.get("artist", "unspecified")).strip() or "unspecified"
                artist_dist[artist] += 1

            res = image_resolution(img)
            if res is None:
                unknown_res_count += 1
            else:
                w, h = res
                res_buckets[bucket_resolution(w, h)] += 1

    # --- summary --------------------------------------------------------------
    print(render_section("Summary"))
    print(f"  total references     : {total_images}")
    print(f"  species directories  : {len(dirs)}")
    species_with_refs = sum(1 for c in per_species.values() if c > 0)
    print(f"  species with refs    : {species_with_refs}")
    print(f"  missing attribution  : {len(missing_attr)}")
    distinct_artists = sum(1 for a in artist_dist if a not in ("unspecified", "unknown master"))
    print(f"  distinct named artists: {distinct_artists}")

    # --- per-species counts ---------------------------------------------------
    print(render_section("Per-species reference counts"))
    if total_images == 0:
        print("  (corpus is empty — drop curated references into each species directory)")
    else:
        non_empty = [(k, v) for k, v in sorted(per_species.items()) if v > 0]
        if non_empty:
            for line in render_count_table(non_empty):
                print(line)
        empty = sorted(k for k, v in per_species.items() if v == 0)
        if empty:
            print(f"  empty species ({len(empty)}): {', '.join(empty)}")

    # --- license distribution -------------------------------------------------
    print(render_section("License distribution"))
    if not license_dist:
        print("  (no licensed images yet)")
    else:
        for line in render_count_table(sorted(license_dist.items(), key=lambda kv: -kv[1])):
            print(line)

    # --- artist distribution --------------------------------------------------
    print(render_section("Artist distribution"))
    if not artist_dist:
        print("  (no attributed images yet)")
    else:
        for line in render_count_table(sorted(artist_dist.items(), key=lambda kv: -kv[1])):
            print(line)

    # --- resolution histogram -------------------------------------------------
    print(render_section("Resolution histogram"))
    if total_images == 0:
        print("  (no images)")
    elif not _PIL_AVAILABLE:
        print("  (install Pillow to enable resolution audit: pip install Pillow)")
    else:
        ordered = [(label, res_buckets.get(label, 0)) for label, _ in RES_BUCKETS]
        for line in render_count_table(ordered):
            print(line)
        if unknown_res_count:
            print(f"  unreadable           : {unknown_res_count}")

    # --- LoRA-readiness gates -------------------------------------------------
    print(render_section("LoRA-readiness checklist"))
    gates = []

    species_count_target = 30
    image_count_target = 50
    gates.append((
        f">= {image_count_target} images total",
        total_images >= image_count_target,
        f"have {total_images}",
    ))
    gates.append((
        f">= {species_count_target} species with refs",
        species_with_refs >= species_count_target,
        f"have {species_with_refs}",
    ))
    gates.append((
        "100% attribution coverage",
        len(missing_attr) == 0,
        f"missing {len(missing_attr)}",
    ))
    gates.append((
        "no species over 8-reference cap",
        not over_cap_species,
        ", ".join(f"{n}={c}" for n, c in over_cap_species) or "ok",
    ))
    bad_license_count = sum(
        license_dist.get(bad, 0)
        for bad in ("unknown", "all-rights-reserved", "unspecified")
    )
    gates.append((
        "no unlicensed / unspecified images",
        bad_license_count == 0,
        f"{bad_license_count} flagged",
    ))
    if _PIL_AVAILABLE and total_images > 0:
        below_1024 = res_buckets.get("<512", 0) + res_buckets.get("512-1023", 0)
        gates.append((
            "all images >= 1024 px",
            below_1024 == 0,
            f"{below_1024} below 1024",
        ))
    gates.append((
        ">= 4 distinct named artists",
        distinct_artists >= 4,
        f"have {distinct_artists}",
    ))

    all_pass = True
    for label, ok, detail in gates:
        mark = "PASS" if ok else "FAIL"
        all_pass = all_pass and ok
        print(f"  [{mark}] {label}  ({detail})")

    if missing_attr:
        print(render_section("Images missing attribution"))
        for p in missing_attr[:20]:
            print(f"  {p.relative_to(root.parent.parent.parent)}")
        if len(missing_attr) > 20:
            print(f"  ... and {len(missing_attr) - 20} more")

    print()
    if total_images == 0:
        print("Corpus is empty. Drop curated references in and re-run.")
        return 0
    if all_pass:
        print("Corpus is LoRA-ready.")
        return 0
    print("Corpus is NOT yet LoRA-ready — see FAIL lines above.")
    return 1


def main(argv: list[str]) -> int:
    root = CORPUS_ROOT
    if len(argv) > 1:
        root = Path(argv[1]).resolve()
    return audit(root)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
