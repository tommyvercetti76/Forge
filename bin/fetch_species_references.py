#!/usr/bin/env python3
"""Fetch open-licensed per-species photo references for Forge's KB.

Per the brand/madhubani/kb/ knowledge base, each species needs 8 reference
photos (4 male + 4 female where sexually dimorphic, 8 mixed-pose otherwise).
This script queries:

  1. Wikimedia Commons API — by Latin binomial + common name
  2. iNaturalist API — research-grade observations by taxon_name

Strict license filter: **CC-BY, CC-BY-SA, CC0, Public Domain ONLY.**
**CC-BY-NC is explicitly excluded** (we train LoRAs on these → need
commercial-use rights).

Per-species output:
  brand/references/species/<slug>/
    01_<descriptor>.attribution.json
    02_<descriptor>.attribution.json
    ... (up to 8)

Each attribution.json receipt follows the existing Forge schema:
  {
    "schema": "forge.reference.v1",
    "title": "...",
    "filename": "<slug>_01.jpg",
    "source": "wikimedia_commons" | "inaturalist",
    "source_url": "https://...",
    "photographer": "...",
    "license": "CC BY-SA 4.0",
    "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
    "sha256": null,          # populated only when binary downloaded
    "subject_slug": "snow-leopard",
    "sex_tag": "male"|"female"|"unknown",
    "pose_descriptor": "side-profile" | "head-close" | ...,
    "fetched_at": "2026-05-22T..."
  }

This is a MANIFEST-only script — it writes JSON receipts, NOT binaries.
The companion `bin/rehydrate_references.py` (existing) downloads the
binaries on demand from the URLs in the receipts.

Usage:
  # Single species (dry-run to preview without writing):
  python3 bin/fetch_species_references.py --species snow-leopard --dry-run

  # Single species, write receipts:
  python3 bin/fetch_species_references.py --species snow-leopard --target 8

  # All species in animals.json:
  python3 bin/fetch_species_references.py --all --target 8

  # Override license floor (default already strict):
  python3 bin/fetch_species_references.py --species snow-leopard \
      --allowed-licenses "CC BY 4.0,CC BY-SA 4.0,CC0,Public Domain"
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
ANIMALS_PATH = ROOT / "brand" / "madhubani" / "animals.json"
SPECIES_REFS_ROOT = ROOT / "brand" / "references" / "species"

USER_AGENT = (
    "ForgeReferenceFetcher/1.0 "
    "(https://github.com/tommyvercetti76/Forge; "
    "open-license reference acquisition for cultural-heritage rendering pipeline)"
)

# Strict open-license floor. CC-BY-NC explicitly excluded.
DEFAULT_ALLOWED_LICENSES = frozenset({
    # CC variants (commercial-use permitted)
    "CC BY 1.0", "CC BY 2.0", "CC BY 2.5", "CC BY 3.0", "CC BY 4.0",
    "CC BY-SA 1.0", "CC BY-SA 2.0", "CC BY-SA 2.5", "CC BY-SA 3.0", "CC BY-SA 4.0",
    # Public domain / no rights reserved
    "CC0", "CC0 1.0", "Public Domain", "PD",
    # Specific country open licenses we accept
    "GODL-India", "OGL-UK-1.0", "OGL-UK-2.0", "OGL-UK-3.0",
})

# Latin binomials for each species (used as primary search term — most specific).
# Add new species as catalog grows. Empty / missing → falls back to display name.
LATIN_BINOMIALS = {
    "tiger": "Panthera tigris",
    "sundarbans-tiger": "Panthera tigris tigris",
    "elephant": "Elephas maximus",
    "rhino": "Rhinoceros unicornis",
    "wild-water-buffalo": "Bubalus arnee",
    "saltwater-crocodile": "Crocodylus porosus",
    "sloth-bear": "Melursus ursinus",
    "sambar-deer": "Rusa unicolor",
    "nilgiri-tahr": "Nilgiritragus hylocrius",
    "macaque": "Macaca mulatta",        # rhesus macaque as default; specific subspecies via species file
    "gaur": "Bos gaurus",
    "indian-leopard": "Panthera pardus fusca",
    "barasingha": "Rucervus duvaucelii",
    "dhole": "Cuon alpinus",
    "peacock": "Pavo cristatus",
    "striped-hyena": "Hyaena hyaena",
    "asiatic-lion": "Panthera leo persica",
    "chinkara": "Gazella bennettii",
    "golden-langur": "Trachypithecus geei",
    "pygmy-hog": "Porcula salvania",
    "snow-leopard": "Panthera uncia",
    "bharal": "Pseudois nayaur",
    "sarus-crane": "Antigone antigone",
    "painted-stork": "Mycteria leucocephala",
    "indian-wild-boar": "Sus scrofa cristatus",
    "indian-pangolin": "Manis crassicaudata",
    "indian-giant-squirrel": "Ratufa indica",
    "nilgiri-langur": "Semnopithecus johnii",
    "nilgai": "Boselaphus tragocamelus",
    "indian-grey-mongoose": "Urva edwardsii",
    "chital": "Axis axis",
    "indian-fox": "Vulpes bengalensis",
    "red-panda": "Ailurus fulgens",
    "hoolock-gibbon": "Hoolock hoolock",
    "irrawaddy-dolphin": "Orcaella brevirostris",
    "greater-flamingo": "Phoenicopterus roseus",
    "great-indian-hornbill": "Buceros bicornis",
    "cobra": "Naja naja",
    "whale-shark": "Rhincodon typus",
    "indian-skimmer": "Rynchops albicollis",
    "blackbuck": "Antilope cervicapra",
}

# Species known to be sexually dimorphic — fetch 4M + 4F separately if possible.
SEXUALLY_DIMORPHIC = frozenset({
    "peacock",          # extreme — train only on male
    "asiatic-lion",     # extreme — mane only on male
    "nilgai",           # strong — male blue-grey, female tawny + hornless
    "blackbuck",        # strong — male black/white spiral horns, female tawny
    "hoolock-gibbon",   # extreme — male black, female buff-tan
    "sambar-deer",      # moderate — antlers male only
    "barasingha",       # moderate — antlers male only
    "chital",           # moderate — antlers male only
    "great-indian-hornbill",  # subtle — eye color differs
    "indian-wild-boar", # moderate — tusks more prominent in male
})


# ──────────────────────────────────────────────────────────────────────
# Wikimedia Commons API
# ──────────────────────────────────────────────────────────────────────


WIKIMEDIA_API = "https://commons.wikimedia.org/w/api.php"


def _http_get_json(url: str, params: dict, timeout: int = 30) -> dict:
    full_url = url + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(full_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def search_wikimedia(search_term: str, limit: int = 20) -> list[dict]:
    """Search Wikimedia Commons for files matching search_term. Returns
    a list of file metadata dicts."""
    # First pass: search by file query in File: namespace
    search_params = {
        "action": "query",
        "format": "json",
        "list": "search",
        "srsearch": f'{search_term} filemime:image',
        "srnamespace": 6,  # File namespace
        "srlimit": min(limit, 50),
    }
    try:
        data = _http_get_json(WIKIMEDIA_API, search_params)
    except Exception as exc:
        print(f"  ! Wikimedia search failed for '{search_term}': {exc}", file=sys.stderr)
        return []
    hits = data.get("query", {}).get("search", [])
    if not hits:
        return []
    # Second pass: get imageinfo + extmetadata (license, author, source) for each hit
    titles = "|".join(h["title"] for h in hits[:limit])
    info_params = {
        "action": "query",
        "format": "json",
        "titles": titles,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime",
        "iiextmetadatafilter": "ImageDescription|Artist|LicenseShortName|LicenseUrl|UsageTerms|Credit|DateTime",
    }
    try:
        info_data = _http_get_json(WIKIMEDIA_API, info_params)
    except Exception as exc:
        print(f"  ! Wikimedia imageinfo failed for '{search_term}': {exc}", file=sys.stderr)
        return []
    pages = info_data.get("query", {}).get("pages", {})
    results = []
    for page in pages.values():
        ii = page.get("imageinfo")
        if not ii:
            continue
        ii = ii[0]  # First (and usually only) image info entry
        meta = ii.get("extmetadata", {})
        license_short = (meta.get("LicenseShortName", {}) or {}).get("value", "unknown")
        license_url = (meta.get("LicenseUrl", {}) or {}).get("value", "")
        artist_raw = (meta.get("Artist", {}) or {}).get("value", "")
        artist = _strip_html(artist_raw)
        title = page.get("title", "").replace("File:", "")
        description = _strip_html((meta.get("ImageDescription", {}) or {}).get("value", ""))
        url = ii.get("url", "")
        results.append({
            "source": "wikimedia_commons",
            "title": title,
            "description": description,
            "url": url,
            "page_url": f"https://commons.wikimedia.org/wiki/File:{urllib.parse.quote(title.replace(' ', '_'))}",
            "photographer": artist or "unknown",
            "license": license_short,
            "license_url": license_url,
            "mime": ii.get("mime", ""),
            "width": ii.get("width"),
            "height": ii.get("height"),
        })
    return results


# ──────────────────────────────────────────────────────────────────────
# iNaturalist API
# ──────────────────────────────────────────────────────────────────────


INATURALIST_API = "https://api.inaturalist.org/v1/observations"

# iNaturalist photo license enums map to our license names.
INAT_LICENSE_MAP = {
    "cc0": "CC0",
    "cc-by": "CC BY 4.0",
    "cc-by-sa": "CC BY-SA 4.0",
    "cc-by-nc": "CC BY-NC 4.0",         # NOT allowed
    "cc-by-nc-sa": "CC BY-NC-SA 4.0",   # NOT allowed
    "cc-by-nd": "CC BY-ND 4.0",          # NOT allowed (no derivatives)
    "cc-by-nc-nd": "CC BY-NC-ND 4.0",    # NOT allowed
    "pd": "Public Domain",
}


def search_inaturalist(taxon_name: str, limit: int = 30) -> list[dict]:
    """Query iNaturalist for research-grade observations of the taxon.
    Returns a list of photo metadata dicts (one per photo per observation)."""
    params = {
        "q": taxon_name,
        "taxon_name": taxon_name,
        "quality_grade": "research",
        "photo_license": "cc-by,cc-by-sa,cc0",  # exclude NC, ND
        "per_page": min(limit, 50),
        "order_by": "votes",  # most-upvoted photos surface first
        "order": "desc",
    }
    try:
        data = _http_get_json(INATURALIST_API, params)
    except Exception as exc:
        print(f"  ! iNaturalist search failed for '{taxon_name}': {exc}", file=sys.stderr)
        return []
    results = []
    for obs in data.get("results", []):
        # Each observation can have multiple photos
        obs_id = obs.get("id")
        observer = (obs.get("user") or {}).get("login") or "unknown"
        for photo in obs.get("photos", []):
            license_code = (photo.get("license_code") or "").lower()
            license_name = INAT_LICENSE_MAP.get(license_code, license_code)
            url = photo.get("url", "")
            # Bump to "large" size if available
            url_large = url.replace("/square.", "/large.").replace("/medium.", "/large.")
            results.append({
                "source": "inaturalist",
                "title": f"observation #{obs_id} by {observer}",
                "description": obs.get("species_guess", "") or obs.get("place_guess", ""),
                "url": url_large,
                "page_url": f"https://www.inaturalist.org/observations/{obs_id}",
                "photographer": observer,
                "license": license_name,
                "license_url": (
                    f"https://creativecommons.org/licenses/{license_code}/4.0/"
                    if license_code in ("cc-by", "cc-by-sa") else
                    "https://creativecommons.org/publicdomain/zero/1.0/" if license_code == "cc0" else ""
                ),
                "mime": "image/jpeg",
                "width": None,
                "height": None,
            })
    return results


# ──────────────────────────────────────────────────────────────────────
# Utilities
# ──────────────────────────────────────────────────────────────────────


_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG_RE.sub("", text or "").strip()


def is_license_allowed(license_str: str, allowed: set[str]) -> bool:
    """Match the license string (case-insensitive, whitespace-normalized)
    against the allowed set."""
    norm = re.sub(r"\s+", " ", license_str.strip()).upper()
    allowed_norm = {re.sub(r"\s+", " ", a.strip()).upper() for a in allowed}
    return norm in allowed_norm


def make_attribution(candidate: dict, slug: str, idx: int,
                     sex_tag: str = "unknown",
                     pose_descriptor: str = "general") -> dict:
    """Build the attribution.json receipt for one candidate photo."""
    return {
        "schema": "forge.reference.v1",
        "title": candidate.get("title", ""),
        "filename": f"{slug}_{idx:02d}.jpg",
        "source": candidate["source"],
        "source_url": candidate.get("page_url") or candidate.get("url", ""),
        "binary_url": candidate.get("url", ""),
        "description": candidate.get("description", ""),
        "photographer": candidate.get("photographer", "unknown"),
        "license": candidate.get("license", "unknown"),
        "license_url": candidate.get("license_url", ""),
        "mime": candidate.get("mime", "image/jpeg"),
        "width": candidate.get("width"),
        "height": candidate.get("height"),
        "sha256": None,
        "subject_slug": slug,
        "sex_tag": sex_tag,
        "pose_descriptor": pose_descriptor,
        "fetched_at": dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def load_animals() -> list[dict]:
    return json.loads(ANIMALS_PATH.read_text())["animals"]


# ──────────────────────────────────────────────────────────────────────
# Per-species fetch
# ──────────────────────────────────────────────────────────────────────


def fetch_for_species(slug: str, target: int, allowed: set[str],
                      out_root: Path, dry_run: bool = False) -> dict:
    """Fetch + filter + write receipts for one species. Returns a summary dict."""
    animal_idx = {a["slug"]: a for a in load_animals()}
    if slug not in animal_idx:
        return {"slug": slug, "error": "not_in_animals_json"}
    animal = animal_idx[slug]
    display_name = animal.get("display_name", slug)
    latin = LATIN_BINOMIALS.get(slug, display_name)
    is_dimorphic = slug in SEXUALLY_DIMORPHIC

    print(f"\n=== {slug} ({display_name}) — Latin: {latin}, dimorphic: {is_dimorphic} ===")

    # Two-source search: Wikimedia first (often higher quality + better attribution),
    # then iNaturalist (broader pose diversity).
    wm_results = search_wikimedia(latin, limit=20)
    print(f"  Wikimedia: {len(wm_results)} candidates")
    time.sleep(0.5)  # polite throttle
    inat_results = search_inaturalist(latin, limit=30)
    print(f"  iNaturalist: {len(inat_results)} candidates")

    all_candidates = wm_results + inat_results
    # Filter by license
    filtered = [c for c in all_candidates if is_license_allowed(c.get("license", ""), allowed)]
    excluded = [c for c in all_candidates if not is_license_allowed(c.get("license", ""), allowed)]
    print(f"  License-filtered: {len(filtered)} kept, {len(excluded)} excluded (NC/ND/unknown)")
    if excluded:
        # Show license distribution of what we excluded for audit
        exc_licenses = {}
        for c in excluded:
            exc_licenses[c.get("license", "?")] = exc_licenses.get(c.get("license", "?"), 0) + 1
        print(f"    Excluded by license: {dict(list(exc_licenses.items())[:5])}")

    if not filtered:
        print(f"  ! No allowed-license candidates found for {slug}")
        return {"slug": slug, "n_candidates": 0, "n_written": 0, "is_dimorphic": is_dimorphic}

    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique = []
    for c in filtered:
        url_key = c.get("url", "") or c.get("page_url", "")
        if url_key and url_key not in seen_urls:
            seen_urls.add(url_key)
            unique.append(c)
    # Order: Wikimedia first (typically higher quality + better metadata), then iNaturalist
    unique.sort(key=lambda c: (0 if c["source"] == "wikimedia_commons" else 1))

    # Take target; for dimorphic, we don't auto-tag sex — that requires human review
    # of each photo. Default sex_tag is "unknown" for all; user curates and re-tags.
    keep = unique[:target]
    out_dir = out_root / slug
    if not dry_run:
        out_dir.mkdir(parents=True, exist_ok=True)

    n_written = 0
    for i, candidate in enumerate(keep, start=1):
        attribution = make_attribution(candidate, slug, i)
        if dry_run:
            print(f"    [{i:02d}] {candidate['license']:18s} | {candidate['source']:18s} | "
                  f"{candidate['photographer'][:30]:30s} | {candidate['title'][:60]}")
        else:
            attr_path = out_dir / f"{i:02d}_{candidate['source']}.attribution.json"
            attr_path.write_text(json.dumps(attribution, indent=2))
            n_written += 1
    if not dry_run:
        print(f"  ✓ Wrote {n_written} receipts to {out_dir.relative_to(ROOT)}/")
    return {
        "slug": slug,
        "n_candidates_total": len(all_candidates),
        "n_license_filtered": len(filtered),
        "n_unique": len(unique),
        "n_written": n_written,
        "is_dimorphic": is_dimorphic,
        "latin": latin,
    }


# ──────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--species", help="Single species slug (e.g., snow-leopard)")
    group.add_argument("--all", action="store_true", help="Fetch for all species in animals.json")
    parser.add_argument("--target", type=int, default=8, help="Photos per species (default: 8)")
    parser.add_argument("--allowed-licenses", default="",
                        help="Comma-separated license names (overrides default open-license floor)")
    parser.add_argument("--out", type=Path, default=SPECIES_REFS_ROOT,
                        help="Output root dir (default: brand/references/species/)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be fetched without writing receipts")
    parser.add_argument("--throttle", type=float, default=1.0,
                        help="Seconds to wait between species (polite throttle, default: 1.0)")
    args = parser.parse_args()

    # License floor: default = strict open commercial-use set; override via --allowed-licenses
    if args.allowed_licenses:
        allowed = set(s.strip() for s in args.allowed_licenses.split(","))
    else:
        allowed = set(DEFAULT_ALLOWED_LICENSES)

    print(f"License floor: {sorted(allowed)}")
    print(f"Target photos per species: {args.target}")
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'WRITE RECEIPTS'}")
    print(f"Output root: {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}")
    print()

    if args.species:
        slugs = [args.species]
    else:
        slugs = [a["slug"] for a in load_animals()]
        print(f"Fetching for ALL {len(slugs)} species in animals.json")

    summaries = []
    for slug in slugs:
        summary = fetch_for_species(slug, args.target, allowed, args.out, args.dry_run)
        summaries.append(summary)
        time.sleep(args.throttle)

    # Final report
    print()
    print("=" * 72)
    print(f"Fetched manifests for {len(summaries)} species")
    total_written = sum(s.get("n_written", 0) for s in summaries)
    n_zero = sum(1 for s in summaries if s.get("n_written", 0) == 0)
    print(f"  Total receipts written: {total_written}")
    print(f"  Species with ZERO receipts (gap): {n_zero}")
    if n_zero > 0:
        print(f"  Gaps require manual sourcing — check rare species + verify search terms")
    print()
    print("Next steps:")
    print(f"  1. Review receipts in {args.out.relative_to(ROOT) if args.out.is_relative_to(ROOT) else args.out}")
    print(f"  2. Curate manually (sex-tag dimorphic species, drop low-quality)")
    print(f"  3. Download binaries: python3 bin/rehydrate_references.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
