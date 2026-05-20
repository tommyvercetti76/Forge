"""Shared trust-layer helpers — turns engine QC sidecars into decisive gates.

Every engine that writes a `<render>.qc.json` next to its PNG gets the same
contract here:

  - `derive_blockers(qc)` extracts failed checks as named blocker dicts.
  - `write_blockers_json(png)` reads the QC sidecar and writes a sibling
    `<png>.blockers.json` only when blockers exist.
  - `is_publishable(blockers, allow_warnings)` is the single yes/no rule.

The QC sidecar is expected to be a dict with a `checks` map of `{name: {"pass":
bool, ...}}`. Failed checks become blockers; passing checks are ignored. Engines
that don't write a QC sidecar yet (wildlife-photo, noir, etc.) emit no
blockers — `publishable: true` is the default, and Q7 will fill in real gates
per engine.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BLOCKERS_SUFFIX = ".blockers.json"
QC_SUFFIX = ".qc.json"


def qc_path_for_png(png_path: Path) -> Path:
    """`tiger.png` → `tiger.qc.json`. Mirrors madhubani_qc._qc_path_for_png."""
    return png_path.with_suffix(QC_SUFFIX)


def blockers_path_for_png(png_path: Path) -> Path:
    """`tiger.png` → `tiger.png.blockers.json`. Kept distinct from the QC sidecar."""
    return png_path.with_suffix(png_path.suffix + BLOCKERS_SUFFIX)


def read_qc_sidecar(png_path: Path) -> dict[str, Any] | None:
    """Return parsed `<png>.qc.json` if it exists, else None. Silent on missing file."""
    qc_path = qc_path_for_png(png_path)
    if not qc_path.exists():
        return None
    try:
        return json.loads(qc_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def derive_blockers(qc: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Extract failed QC checks as blocker entries.

    Returns a list of `{"check": str, "reason": str, "detail": dict}` — one per
    failed check. Order is deterministic (sorted by check name) so manifest
    diffs stay stable. Empty list means publishable.
    """
    if not qc or not isinstance(qc, dict):
        return []
    checks = qc.get("checks")
    if not isinstance(checks, dict):
        return []
    out: list[dict[str, Any]] = []
    for name in sorted(checks.keys()):
        check = checks.get(name)
        if not isinstance(check, dict):
            continue
        if check.get("pass") is False:
            out.append({
                "check": name,
                "reason": _check_reason(name, check),
                "detail": check,
            })
    return out


def _check_reason(name: str, check: dict[str, Any]) -> str:
    """Best-effort human-readable reason. Falls back to the check name."""
    if name == "color_floor":
        present = check.get("present_count")
        required = check.get("required_count")
        if present is not None and required is not None:
            return f"only {present} of {required} required folk hues present"
    if name == "corners_clean":
        ratio = check.get("min_clean_ratio")
        if ratio is not None:
            return f"corner cleanliness {ratio:.0%} (need ≥95%)"
    if name == "subject_centered":
        bbox_w = check.get("bbox_width_ratio")
        center = check.get("center")
        if bbox_w is not None and center is not None:
            return f"bbox width {bbox_w:.0%} or center {center} outside acceptable range"
    if name == "body_fill":
        best = check.get("best_body_fraction")
        black = check.get("black_subject_fraction")
        cream = check.get("cream_subject_fraction")
        if best is not None:
            return f"body-fill fraction {best:.1%} (black={black or 0:.0%}, cream={cream or 0:.0%})"
    return f"{name} failed"


def write_blockers_json(
    png_path: Path,
    qc: dict[str, Any] | None = None,
    *,
    extra_blockers: list[dict[str, Any]] | None = None,
) -> tuple[Path | None, list[dict[str, Any]]]:
    """Write `<png>.blockers.json` iff there are blockers; return (path, blockers).

    `qc` is optional — if omitted, the function reads `<png>.qc.json` itself.
    `extra_blockers` lets callers inject non-QC-derived blockers (e.g. missing
    file, validation errors) that should also gate publishability. Returns the
    written path and the full blocker list. Returns (None, []) when there are
    no blockers — no file is written, no stale file is left behind.
    """
    if qc is None:
        qc = read_qc_sidecar(png_path)
    blockers = derive_blockers(qc)
    if extra_blockers:
        blockers.extend(extra_blockers)
    blockers_path = blockers_path_for_png(png_path)
    if not blockers:
        if blockers_path.exists():
            try:
                blockers_path.unlink()
            except OSError:
                pass
        return None, []
    payload = {
        "schema": "forge.engine_qc.blockers.v1",
        "png_path": str(png_path),
        "qc_path": str(qc_path_for_png(png_path)) if qc is not None else None,
        "blockers": blockers,
        "blocker_count": len(blockers),
    }
    blockers_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return blockers_path, blockers


def is_publishable(blockers: list[dict[str, Any]], *, allow_warnings: bool = False) -> bool:
    """Single rule: publishable iff no blockers, OR --allow-qc-warnings opted in."""
    if not blockers:
        return True
    return bool(allow_warnings)


def summarize(blockers: list[dict[str, Any]]) -> str:
    """One-line summary for CLI output."""
    if not blockers:
        return "publishable"
    names = ", ".join(sorted({b["check"] for b in blockers}))
    return f"{len(blockers)} blocker(s): {names}"
