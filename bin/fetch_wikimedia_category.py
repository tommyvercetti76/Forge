#!/usr/bin/env python3
"""Fetch open-licensed reference images from Wikimedia Commons for a tradition.

Queries the Wikimedia Commons category API, filters by license (CC-BY / CC0 /
Public Domain / GODL-India only — per Forge's open-source-only policy), and
writes attribution.json receipts under brand/references/<tradition>/_general/
in the existing schema. The actual binary fetch is handled by
bin/rehydrate_references.py — this script only creates manifests, which is
the standard Forge pattern (manifests in git, binaries fetched on demand).

Usage:
    # The 4 traditions Forge officially supports beyond Madhubani:
    python3 bin/fetch_wikimedia_category.py --tradition pahari \\
        --category "Pahari_painting" --target 50

    python3 bin/fetch_wikimedia_category.py --tradition kalighat \\
        --category "Kalighat_painting" --target 50

    python3 bin/fetch_wikimedia_category.py --tradition tanjore \\
        --category "Tanjore_painting" --target 50

    python3 bin/fetch_wikimedia_category.py --tradition ravi-varma \\
        --category "Paintings_by_Raja_Ravi_Varma" --target 50

    # Then: rehydrate to actually download the binaries
    python3 bin/rehydrate_references.py --style pahari
    python3 bin/rehydrate_references.py --style kalighat
    python3 bin/rehydrate_references.py --style tanjore
    python3 bin/rehydrate_references.py --style ravi-varma

Idempotent — re-running skips already-written receipts. License-filtered —
images under any non-permitted license (all-rights-reserved, unknown) are
silently skipped and logged. Polite rate-limited (1s default between API
calls; --pace to tune).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REFS_ROOT = Path(__file__).resolve().parent.parent / "brand" / "references"
USER_AGENT = (
    "Forge-LoRA-Research/1.0 "
    "(https://github.com/tommyvercetti76/Forge; local LoRA training pilot; "
    "fetching openly-licensed references per attribution.json manifests)"
)
COMMONS_API = "https://commons.wikimedia.org/w/api.php"

# Permitted licenses per Forge's open-source-only policy.
# Match the existing _general/devi4.jpg.attribution.json schema's `license` values.
PERMITTED_LICENSES = {
    "CC0", "CC0 1.0",
    "Public domain", "Public Domain", "PD",
    "CC BY 2.0", "CC BY 3.0", "CC BY 4.0",
    "CC BY-SA 2.0", "CC BY-SA 2.5", "CC BY-SA 3.0", "CC BY-SA 4.0",
    "GODL-India",
}


def http_get_json(url: str, *, timeout: float = 30) -> dict:
    """GET JSON from a URL with Forge's User-Agent header."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def list_category_files(category: str, limit: int) -> list[str]:
    """Return up to `limit` File: titles in a Wikimedia Commons category."""
    params = {
        "action": "query",
        "format": "json",
        "list": "categorymembers",
        "cmtitle": f"Category:{category}",
        "cmtype": "file",
        "cmlimit": str(min(limit, 500)),
    }
    url = f"{COMMONS_API}?{urllib.parse.urlencode(params)}"
    data = http_get_json(url)
    members = data.get("query", {}).get("categorymembers", [])
    return [m["title"] for m in members][:limit]


def get_file_info(title: str) -> dict | None:
    """Fetch URL + metadata + license info for a Commons file."""
    params = {
        "action": "query",
        "format": "json",
        "titles": title,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime",
        "iiurlwidth": "1280",
    }
    url = f"{COMMONS_API}?{urllib.parse.urlencode(params)}"
    data = http_get_json(url)
    pages = data.get("query", {}).get("pages", {})
    for _page_id, page in pages.items():
        infos = page.get("imageinfo", [])
        if infos:
            return infos[0]
    return None


def _strip_html(s: str) -> str:
    """Wikimedia extmetadata returns HTML in some fields (Artist, Credit)."""
    return re.sub(r"<[^>]+>", "", s).strip() if s else ""


def extract_license(info: dict) -> str:
    """Pull the normalized license short-name from extmetadata."""
    meta = info.get("extmetadata", {})
    return meta.get("LicenseShortName", {}).get("value", "").strip()


def is_permitted(license_str: str) -> bool:
    """True if the license is in Forge's open-source allowlist."""
    return license_str in PERMITTED_LICENSES


def normalize_filename(title: str) -> str:
    """'File:Some Painting.jpg' → 'some-painting.jpg' (Forge naming convention)."""
    name = title.split(":", 1)[1] if ":" in title else title
    # Match the existing brand/references/madhubani/_general/ naming style:
    # lowercase, spaces → hyphens, kept the original extension.
    return re.sub(r"[\s_]+", "-", name).lower()


def build_attribution(title: str, info: dict, license_str: str) -> dict:
    """Construct attribution.json matching existing schema (see _example_attribution.json)."""
    meta = info.get("extmetadata", {})

    def m(key: str) -> str:
        return meta.get(key, {}).get("value", "")

    return {
        "source_url": f"https://commons.wikimedia.org/wiki/{urllib.parse.quote(title)}",
        "image_url": info.get("thumburl") or info.get("url"),
        "wikimedia_title": title,
        "artist": _strip_html(m("Artist")),
        "credit": _strip_html(m("Credit")),
        "date": m("DateTimeOriginal") or m("DateTime"),
        "license": license_str,
        "license_url": meta.get("LicenseUrl", {}).get("value", ""),
        "permitted_uses": [
            "LoRA training",
            "Kontext seed",
            "private reference",
        ],
        "added_by": "auto-curator/wikimedia-commons/fetch_wikimedia_category.py",
        "added_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "notes": (
            f"Downloaded at thumbnail width 1280px from Wikimedia CDN; "
            f"original {info.get('width', '?')}x{info.get('height', '?')} "
            f"{info.get('mime', 'unknown')}."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch open-licensed Wikimedia Commons references for a folk-art tradition."
    )
    parser.add_argument(
        "--tradition",
        required=True,
        help="Tradition slug — creates brand/references/<tradition>/_general/ if missing.",
    )
    parser.add_argument(
        "--category",
        required=True,
        help='Wikimedia Commons category name (without "Category:" prefix). '
        'E.g. "Pahari_painting", "Kalighat_painting".',
    )
    parser.add_argument(
        "--target",
        type=int,
        default=50,
        help="Target number of receipts to write (default 50).",
    )
    parser.add_argument(
        "--pace",
        type=float,
        default=1.0,
        help="Seconds between Wikimedia API calls (default 1.0 — polite throttle).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be written without touching disk.",
    )
    args = parser.parse_args()

    out_dir = REFS_ROOT / args.tradition / "_general"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"Fetching Wikimedia Category:{args.category} → "
        f"brand/references/{args.tradition}/_general/ (target {args.target})"
    )

    try:
        files = list_category_files(args.category, args.target * 2)
    except Exception as e:
        print(f"ERROR: failed to list category: {e}", file=sys.stderr)
        return 1

    print(f"Category lists {len(files)} files. Filtering by license + writing receipts...\n")

    written = 0
    skipped_existing = 0
    skipped_unlicensed = 0
    skipped_error = 0

    for title in files:
        if written >= args.target:
            break

        filename = normalize_filename(title)
        receipt_path = out_dir / f"{filename}.attribution.json"

        if receipt_path.exists():
            print(f"  [skip-existing]  {filename}")
            skipped_existing += 1
            continue

        try:
            info = get_file_info(title)
            if not info:
                print(f"  [no-info]        {title}", file=sys.stderr)
                skipped_error += 1
                time.sleep(args.pace)
                continue

            license_str = extract_license(info)
            if not is_permitted(license_str):
                print(f"  [skip-license]   {filename}  (license: {license_str!r})")
                skipped_unlicensed += 1
                time.sleep(args.pace)
                continue

            attribution = build_attribution(title, info, license_str)

            if args.dry_run:
                print(f"  [DRY-RUN]        would write {receipt_path.name} (license: {license_str})")
            else:
                with open(receipt_path, "w") as f:
                    json.dump(attribution, f, indent=2, ensure_ascii=False)
                print(f"  [+]              {receipt_path.name}  (license: {license_str})")
            written += 1
        except Exception as e:
            print(f"  [error]          {title}: {e}", file=sys.stderr)
            skipped_error += 1

        time.sleep(args.pace)

    print()
    print(f"Receipts written:   {written}  (target was {args.target})")
    print(f"Skipped existing:   {skipped_existing}")
    print(f"Skipped unlicensed: {skipped_unlicensed}")
    print(f"Skipped errors:     {skipped_error}")
    print()
    print(
        f"Next:  python3 bin/rehydrate_references.py --style {args.tradition}"
    )
    print("       (rehydrates binaries from the receipts just written)")

    return 0 if written > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
