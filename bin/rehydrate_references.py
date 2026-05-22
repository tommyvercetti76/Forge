#!/usr/bin/env python3
"""Rehydrate the Madhubani reference corpus from its attribution.json manifests.

The reference image binaries are deliberately NOT tracked in git — only the
sibling `<name>.attribution.json` files are. This script reads each
attribution.json, downloads the corresponding binary from its source_url
(or the recorded image_url for Wikimedia thumbnail-backed entries), and
restores the corpus locally.

This is the standard ML manifest-vs-binary pattern: provenance travels in
git, binaries are fetched on demand. Anyone fresh-cloning the repo can run
this script and end up with the same corpus the original curator had.

Usage:
    python3 bin/rehydrate_references.py                       # rehydrate all missing binaries
    python3 bin/rehydrate_references.py --dry-run             # show what would be fetched
    python3 bin/rehydrate_references.py --style madhubani     # only one style subtree (default: all)
    python3 bin/rehydrate_references.py --force               # re-download even if file exists
    python3 bin/rehydrate_references.py --pace 3.0            # seconds between downloads (default: 3s, kind to CDNs)

Exit code 0 if every manifested file was successfully present after the run,
non-zero if any failed. The audit script (`_audit.py`) is the source of
truth for corpus health.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Iterable

REFS_ROOT = Path(__file__).resolve().parent.parent / "brand" / "references"
USER_AGENT = (
    "Forge-Madhubani-LoRA-Research/1.0 "
    "(https://github.com/tommyvercetti76/Forge; local LoRA training pilot; "
    "fetching openly-licensed references per attribution.json manifests)"
)


def find_manifests(style: str | None = None) -> list[Path]:
    """Return every attribution.json file under brand/references/, optionally
    scoped to a single style subtree (e.g. 'madhubani')."""
    root = REFS_ROOT / style if style else REFS_ROOT
    if not root.exists():
        return []
    return sorted(root.rglob("*.attribution.json"))


def expected_image_for(manifest_path: Path) -> Path:
    """attribution.json → expected image path on disk.
    e.g.  tiger.png.attribution.json → tiger.png"""
    # Strip the trailing ".attribution.json" suffix
    name = manifest_path.name
    if name.endswith(".attribution.json"):
        return manifest_path.with_name(name[: -len(".attribution.json")])
    raise ValueError(f"unexpected manifest name: {manifest_path.name}")


def fetch_one(url: str, dest: Path, *, timeout: float = 90) -> tuple[bool, str]:
    """Single GET + atomic write. Returns (ok, message)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            content_type = r.headers.get("Content-Type", "").lower()
            blob = r.read()
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}"
    except Exception as e:
        return False, str(e)
    if len(blob) < 1024:
        return False, f"response too small ({len(blob)} bytes)"
    # Reject HTML responses — common when we get redirected to a description
    # page instead of the binary itself. Either Content-Type says text/html
    # OR the magic bytes start with `<` (covers servers that lie about MIME).
    if content_type.startswith(("text/", "application/xhtml")) or blob[:1] == b"<":
        return False, f"got HTML/text not binary (Content-Type: {content_type})"
    tmp = dest.with_suffix(dest.suffix + ".part")
    tmp.write_bytes(blob)
    tmp.replace(dest)
    return True, f"{len(blob) // 1024} KB"


def rehydrate(
    manifests: Iterable[Path],
    *,
    force: bool = False,
    dry_run: bool = False,
    pace: float = 3.0,
) -> dict[str, int]:
    """Iterate the manifests and ensure each has its binary on disk.

    Returns a counts dict so callers can act on the outcome.
    """
    counts = {"present": 0, "fetched": 0, "failed": 0, "skipped_dry": 0}
    manifests = list(manifests)
    for i, manifest in enumerate(manifests, start=1):
        try:
            data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"  [{i}/{len(manifests)}] ✗ {manifest.name}: cannot read ({e})")
            counts["failed"] += 1
            continue

        image_path = expected_image_for(manifest)
        if image_path.exists() and not force:
            counts["present"] += 1
            continue

        # Prefer image_url (Madhubani-style legacy field) → binary_url (species-
        # photo schema field) → source_url (fallback; this is the Wikimedia
        # description page, which is HTML — only valid when image_url/binary_url
        # was a thumbnail-API URL that gets redirected).
        url = (
            data.get("image_url")
            or data.get("binary_url")
            or data.get("source_url")
            or ""
        ).strip()
        # Reject obvious HTML description URLs masquerading as binary
        if "commons.wikimedia.org/wiki/" in url and not url.endswith((".jpg", ".jpeg", ".png", ".webp")):
            print(f"  [{i}/{len(manifests)}] ✗ {manifest.name}: source_url is HTML page (no image_url/binary_url in manifest)")
            counts["failed"] += 1
            continue
        if not url:
            print(f"  [{i}/{len(manifests)}] ✗ {manifest.name}: no image_url/binary_url/source_url in manifest")
            counts["failed"] += 1
            continue

        if dry_run:
            print(f"  [{i}/{len(manifests)}] would fetch {image_path.name} ← {url}")
            counts["skipped_dry"] += 1
            continue

        ok, msg = fetch_one(url, image_path)
        tag = "✓" if ok else "✗"
        print(f"  [{i}/{len(manifests)}] {tag} {image_path.name}  ({msg})")
        if ok:
            counts["fetched"] += 1
        else:
            counts["failed"] += 1
            if msg.startswith("HTTP 429"):
                print("    rate-limited; sleeping 30s before continuing")
                time.sleep(30)
        time.sleep(pace)
    return counts


def main() -> int:
    p = argparse.ArgumentParser(description="Rehydrate the reference corpus from attribution.json manifests.")
    p.add_argument("--style", default=None, help="restrict to one style subtree (e.g. madhubani)")
    p.add_argument("--force", action="store_true", help="re-download even if the image already exists")
    p.add_argument("--dry-run", action="store_true", help="report what would be fetched without downloading")
    p.add_argument("--pace", type=float, default=3.0, help="seconds between downloads (kind to CDNs; default 3)")
    args = p.parse_args()

    if not REFS_ROOT.exists():
        print(f"references root missing: {REFS_ROOT}", file=sys.stderr)
        return 2

    manifests = find_manifests(args.style)
    if not manifests:
        print(f"no attribution.json files found under {REFS_ROOT}{'/' + args.style if args.style else ''}")
        return 0

    print(f"Rehydrating {len(manifests)} manifest(s) under {REFS_ROOT}")
    if args.dry_run:
        print("  (dry-run — nothing will be downloaded)")
    counts = rehydrate(manifests, force=args.force, dry_run=args.dry_run, pace=args.pace)

    print()
    print(f"present:  {counts['present']}")
    print(f"fetched:  {counts['fetched']}")
    print(f"failed:   {counts['failed']}")
    if args.dry_run:
        print(f"dry-skip: {counts['skipped_dry']}")
    return 0 if counts["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
