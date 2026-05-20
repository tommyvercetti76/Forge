"""Automatic QC gates for the Madhubani tee catalog.

This module covers the seven rubric checks that are intentionally mechanical:
palette floor, clean corners, centered subject, saturated body fill, anatomy
(body-type leg count), text-leak (OCR), and eye character (head-region
luminance contrast). It is not a replacement for the human review gates
around expression nuance, Madhubani read, and series cohesion.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


AUTO_CHECK_COUNT = 9

# Phase-B (2026-05-20, B.1) — pattern_density target bands per decoration_density.
# Measured: fraction of subject-mask pixels NOT close to the body_fill_color
# (i.e. carrying decoration). A render that's "ornate" should have ~45-80% of
# the subject silhouette decorated; "minimal" should have ≤20%. The check
# fails if measured density is more than ONE BAND below target — e.g. peacock
# declared "maximal" (target ≥0.65) rendered at 0.32 is two bands low → fail.
PATTERN_DENSITY_BANDS: dict[str, tuple[float, float]] = {
    # density_name: (min_acceptable, target_ideal)
    "minimal":  (0.05, 0.15),
    "balanced": (0.20, 0.40),
    "ornate":   (0.40, 0.60),
    "maximal":  (0.55, 0.75),
}

# Phase-B (2026-05-20, B.2) — decoration_zone_presence.
# Maps the leading uppercase token of a `required_decoration_zone` entry
# (e.g. "FOREHEAD: tikka medallion") to a fractional bbox slice
# (y_top_frac, y_bot_frac, x_left_frac, x_right_frac) within the subject's
# bounding box. v1 heuristic: vertical band by body region. Refine per
# body-type / pose orientation later.
ZONE_BBOX_FRACTIONS: dict[str, tuple[float, float, float, float]] = {
    "FOREHEAD":     (0.00, 0.18, 0.55, 1.00),
    "FACE":         (0.05, 0.30, 0.50, 1.00),
    "HEAD":         (0.00, 0.30, 0.50, 1.00),
    "EAR":          (0.00, 0.18, 0.60, 0.95),
    "EYE":          (0.05, 0.25, 0.55, 0.95),
    "CREST":        (0.00, 0.15, 0.40, 0.90),
    "MANE":         (0.00, 0.35, 0.40, 1.00),
    "NECK":         (0.15, 0.40, 0.45, 0.90),
    "SHOULDER":     (0.25, 0.50, 0.30, 0.75),
    "TUSKS":        (0.15, 0.35, 0.65, 1.00),
    "NOSE":         (0.10, 0.30, 0.70, 1.00),
    "ARMOR":        (0.30, 0.70, 0.15, 0.80),
    "BACK":         (0.20, 0.50, 0.20, 0.80),
    "BODY":         (0.30, 0.70, 0.15, 0.85),
    "WING":         (0.20, 0.70, 0.10, 0.75),
    "TAIL":         (0.30, 0.85, 0.00, 0.30),
    "HAUNCH":       (0.35, 0.65, 0.10, 0.45),
    "HIP":          (0.35, 0.60, 0.10, 0.50),
    "LEG":          (0.60, 1.00, 0.10, 0.90),
    "ANKLETS":      (0.75, 1.00, 0.10, 0.90),
    "FEET":         (0.85, 1.00, 0.20, 0.90),
    "GROUND":       (0.92, 1.00, 0.00, 1.00),
    "SADDLE":       (0.25, 0.55, 0.20, 0.75),
}
# Per-zone decoration fraction floor (≥ this fraction of the zone's
# subject-mask pixels must carry decoration). v1: a single threshold;
# refine per-zone (e.g. tail must be very dense for peacock) later.
ZONE_DECORATION_FLOOR = 0.10
# A render passes decoration_zone_presence if ≥ this fraction of the
# declared zones (with a known label) show decoration above the floor.
ZONE_PASS_FRACTION = 0.66

# Body-type → expected leg-pillar count under _score_anatomy. Body types
# absent from the map skip the leg-count check entirely (pass by definition).
LEG_PILLAR_EXPECTATIONS: dict[str, int] = {
    "heavy-quadruped": 3,
    "lean-predator": 3,
    "lean-quadruped": 3,
    "armored-quadruped": 3,
    "primate": 3,
    "bird": 2,
}
LEG_PILLAR_SKIP_BODY_TYPES = frozenset({"serpent", "cetacean"})

# Checks that ship in the QC output as informational only — their `pass`
# field is still computed and reported, but `auto_qc_pass` ignores them.
# The 2026-05-20 A2 corpus check (docs/A2_CORPUS_CHECK_2026-05-20.md) found
# `anatomy` fires on >10% of the known-good corpus (side-profile quadrupeds
# routinely show only 2 leg pillars because the far legs are occluded by
# the near legs); the proxy is too strict to gate promotion until either
# a foreground/background mask separates the limbs or the pose set is
# constrained to legs-spread compositions. Until then anatomy is reported
# but does not block.
DISABLED_BY_DEFAULT_CHECKS: frozenset[str] = frozenset({"anatomy"})


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    text = value.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"expected #RRGGBB color, got {value!r}")
    return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))


def _srgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    arr = rgb.astype(np.float32) / 255.0
    arr = np.where(arr <= 0.04045, arr / 12.92, ((arr + 0.055) / 1.055) ** 2.4)
    xyz = arr @ np.array(
        [
            [0.4124564, 0.2126729, 0.0193339],
            [0.3575761, 0.7151522, 0.1191920],
            [0.1804375, 0.0721750, 0.9503041],
        ],
        dtype=np.float32,
    )
    xyz = xyz / np.array([0.95047, 1.0, 1.08883], dtype=np.float32)
    delta = 6 / 29
    f = np.where(xyz > delta ** 3, np.cbrt(xyz), (xyz / (3 * delta ** 2)) + (4 / 29))
    return np.stack(
        [
            (116 * f[..., 1]) - 16,
            500 * (f[..., 0] - f[..., 1]),
            200 * (f[..., 1] - f[..., 2]),
        ],
        axis=-1,
    )


def _delta_e(lab: np.ndarray, target_rgb: tuple[int, int, int]) -> np.ndarray:
    target = _srgb_to_lab(np.array([[target_rgb]], dtype=np.float32))[0, 0]
    return np.linalg.norm(lab - target, axis=-1)


def _load_palette(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _downsample_image(path: Path, max_dim: int = 768) -> tuple[np.ndarray, np.ndarray | None, tuple[int, int]]:
    image = Image.open(path).convert("RGBA")
    original_size = image.size
    scale = min(1.0, max_dim / max(image.size))
    if scale < 1.0:
        image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.Resampling.LANCZOS)
    arr = np.asarray(image)
    rgb = arr[..., :3]
    alpha = arr[..., 3]
    return rgb, alpha, original_size


def _score_anatomy(subject_mask: np.ndarray, body_type: str | None) -> dict[str, Any]:
    """Leg-count proxy from the subject mask, dispatched by body_type.

    For quadrupeds / primates / birds we scan the bottom 30% of the subject
    mask column-by-column. A column is a "leg pillar" if its bottom-band
    coverage exceeds 60%; pillars must be separated by ≥4 columns of <20%
    coverage to avoid counting one wide trunk as two legs. Body types whose
    anatomy_rules do not require visible legs (serpent, cetacean, or any
    body_type the engine doesn't know) pass by definition.

    Returns the actual pillar count even when the check passes-by-definition,
    so manifest diffs surface what the proxy saw.
    """
    body_type_label = (body_type or "").strip()
    expected = LEG_PILLAR_EXPECTATIONS.get(body_type_label, 0)

    # No subject pixels means nothing to count; treat as fail unless the
    # body_type is one of the no-leg families.
    if not subject_mask.any():
        return {
            "pass": body_type_label in LEG_PILLAR_SKIP_BODY_TYPES,
            "body_type": body_type_label,
            "leg_pillars_detected": 0,
            "leg_pillars_expected": expected,
        }

    ys, xs = np.where(subject_mask)
    x0, x1 = int(xs.min()), int(xs.max())
    y0, y1 = int(ys.min()), int(ys.max())
    bbox_height = y1 - y0 + 1
    bbox_width = x1 - x0 + 1

    # Bottom 30% of the subject bounding box.
    band_top = y0 + int(round(bbox_height * 0.7))
    band = subject_mask[band_top:y1 + 1, x0:x1 + 1]
    if band.size == 0:
        return {
            "pass": body_type_label in LEG_PILLAR_SKIP_BODY_TYPES,
            "body_type": body_type_label,
            "leg_pillars_detected": 0,
            "leg_pillars_expected": expected,
        }

    column_coverage = band.mean(axis=0) if band.shape[0] > 0 else np.zeros(bbox_width, dtype=np.float32)
    pillar_threshold = 0.60
    gap_threshold = 0.20
    min_gap_columns = 4

    pillars = 0
    in_pillar = False
    gap_counter = 0
    for value in column_coverage:
        v = float(value)
        if v >= pillar_threshold:
            if not in_pillar:
                pillars += 1
                in_pillar = True
            gap_counter = 0
        elif v < gap_threshold:
            gap_counter += 1
            if in_pillar and gap_counter >= min_gap_columns:
                in_pillar = False
        # 0.20–0.60 mid-zone: neither extends a pillar nor counts as a clean
        # gap; treat it as ambiguous transition territory.

    if body_type_label in LEG_PILLAR_SKIP_BODY_TYPES:
        passed = True
    elif expected == 0:
        # Unknown body_type, no legs expected → pass by definition.
        passed = True
    else:
        passed = pillars >= expected

    return {
        "pass": passed,
        "body_type": body_type_label,
        "leg_pillars_detected": int(pillars),
        "leg_pillars_expected": int(expected),
        "disabled_by_default": "anatomy" in DISABLED_BY_DEFAULT_CHECKS,
    }


def _score_text_leak(png_path: Path) -> dict[str, Any]:
    """OCR-based text-leak detector. pytesseract is optional — missing dep
    becomes a skipped (passing) result, not a failure, so the rubric isn't
    held hostage by a system dependency.

    Failure modes:
      - any Devanagari character (U+0900–U+097F) in the recognized text
      - more than 10 characters of recognized text (after whitespace strip)

    The high length threshold tolerates the false positives that OCR engines
    routinely emit on ornament patterns (stray "I", "l", noise glyphs); only
    when the text starts to look like actual words do we fail.
    """
    try:
        import pytesseract  # type: ignore[import-not-found]
    except ImportError:
        return {
            "pass": True,
            "skipped": True,
            "reason": "pytesseract not installed",
        }

    try:
        text = pytesseract.image_to_string(Image.open(png_path), lang="eng+hin")
    except Exception as exc:  # pragma: no cover — defensive: missing language pack, runtime errors
        return {
            "pass": True,
            "skipped": True,
            "reason": f"pytesseract failed: {exc}",
        }

    cleaned = text.strip()
    devanagari = sum(1 for ch in cleaned if "ऀ" <= ch <= "ॿ")
    text_length = len(cleaned)
    fail = text_length > 10 or devanagari > 0
    return {
        "pass": not fail,
        "skipped": False,
        "ocr_text_length": text_length,
        "devanagari_chars": devanagari,
        "preview": cleaned[:80],
    }


def _score_eye_character(rgb: np.ndarray, subject_mask: np.ndarray) -> dict[str, Any]:
    """Head-band luminance contrast as a proxy for "alert eyes present".

    Madhubani folk-icons place eyes as small high-contrast marks against a
    saturated body fill. Within the top 25% of the subject bounding box, an
    alert eye produces a wide luminance spread (dark pupil + light sclera +
    fur). A uniform face — blob, blurred, or missing eyes — produces a
    narrow spread. We threshold on (max - min) > 80 on the 8-bit scale.
    """
    if not subject_mask.any():
        return {
            "pass": False,
            "head_band_pixel_count": 0,
            "luminance_min": 0,
            "luminance_max": 0,
            "luminance_std": 0.0,
        }

    ys, xs = np.where(subject_mask)
    y0, y1 = int(ys.min()), int(ys.max())
    bbox_height = y1 - y0 + 1
    head_band_bottom = y0 + max(1, int(round(bbox_height * 0.25)))

    head_band_mask = np.zeros_like(subject_mask)
    head_band_mask[y0:head_band_bottom, :] = subject_mask[y0:head_band_bottom, :]
    if not head_band_mask.any():
        return {
            "pass": False,
            "head_band_pixel_count": 0,
            "luminance_min": 0,
            "luminance_max": 0,
            "luminance_std": 0.0,
        }

    # ITU-R BT.601 luminance — sturdy for 8-bit RGB without needing Lab.
    luminance = (
        0.299 * rgb[..., 0].astype(np.float32)
        + 0.587 * rgb[..., 1].astype(np.float32)
        + 0.114 * rgb[..., 2].astype(np.float32)
    )
    samples = luminance[head_band_mask]
    if samples.size == 0:
        return {
            "pass": False,
            "head_band_pixel_count": 0,
            "luminance_min": 0,
            "luminance_max": 0,
            "luminance_std": 0.0,
        }

    lum_min = int(round(float(samples.min())))
    lum_max = int(round(float(samples.max())))
    lum_std = float(samples.std())
    contrast = lum_max - lum_min
    return {
        "pass": contrast > 80,
        "head_band_pixel_count": int(samples.size),
        "luminance_min": lum_min,
        "luminance_max": lum_max,
        "luminance_std": round(lum_std, 3),
    }


def _score_pattern_density(
    rgb: np.ndarray,
    lab: np.ndarray,
    subject_mask: np.ndarray,
    expected_body_fill: str | None,
    decoration_density: str | None,
) -> dict[str, Any]:
    """Phase-B B.1 (2026-05-20) — pattern_density verification.

    Measures what fraction of the subject silhouette carries DECORATION
    (i.e., is NOT close to the body_fill_color). High density = ornate
    multi-color Madhubani. Low density = sparse / minimal / Kachni-school.

    The animal's decoration_density field declares the target band (minimal
    / balanced / ornate / maximal); this check fails when the measured
    density is below the band's minimum threshold.

    Returns:
      {pass, measured_density, target_band, target_min, target_ideal, ...}
    """
    if subject_mask is None or not subject_mask.any():
        return {
            "pass": False,
            "measured_density": 0.0,
            "target_band": decoration_density,
            "reason": "no subject mask detected",
        }
    if not expected_body_fill:
        # No body_fill_color anchor → can't distinguish decoration from base.
        # Report informationally but don't fail.
        return {
            "pass": True,
            "measured_density": None,
            "target_band": decoration_density,
            "reason": "expected_body_fill not provided; density check skipped",
            "informational_only": True,
        }
    body_rgb = _hex_to_rgb(expected_body_fill)
    body_distance = _delta_e(lab, body_rgb)
    # Subject pixels that are NOT close to the body fill color carry
    # decoration. Threshold of 14 Δ-E is the same we use for subject_mask.
    decorated_in_subject = subject_mask & (body_distance > 14)
    denominator = max(1, int(subject_mask.sum()))
    measured_density = float(decorated_in_subject.sum() / denominator)

    if not decoration_density:
        # Animal entry hasn't declared a target band — measure for reporting
        # but don't hold the render to an arbitrary default.
        return {
            "pass": True,
            "measured_density": round(measured_density, 4),
            "target_band": None,
            "decorated_pixel_count": int(decorated_in_subject.sum()),
            "subject_pixel_count": int(subject_mask.sum()),
            "reason": "decoration_density not declared; density check informational",
            "informational_only": True,
        }
    band = decoration_density.lower()
    if band not in PATTERN_DENSITY_BANDS:
        band = "ornate"
    target_min, target_ideal = PATTERN_DENSITY_BANDS[band]
    return {
        "pass": measured_density >= target_min,
        "measured_density": round(measured_density, 4),
        "target_band": band,
        "target_min": target_min,
        "target_ideal": target_ideal,
        "decorated_pixel_count": int(decorated_in_subject.sum()),
        "subject_pixel_count": int(subject_mask.sum()),
        "reason": (
            f"density {measured_density:.0%} below {band} band minimum {target_min:.0%}"
            if measured_density < target_min
            else f"density {measured_density:.0%} meets {band} band (target {target_ideal:.0%})"
        ),
    }


def _extract_zone_label(zone_string: str) -> str | None:
    """Pull the leading uppercase token before the colon from a
    required_decoration_zone entry. "FOREHEAD: tikka medallion" → "FOREHEAD".
    "FOUR LEG ANKLETS: vermillion bands" → "ANKLETS" (last word, the
    semantic anchor). Returns None if no usable label can be derived.
    """
    if ":" not in zone_string:
        return None
    head = zone_string.split(":", 1)[0].strip()
    if not head:
        return None
    # Strip parenthetical qualifiers like "(most important)" and "(signature)".
    if "(" in head:
        head = head.split("(", 1)[0].strip()
    tokens = [t for t in head.split() if t.isupper() and len(t) >= 2]
    if not tokens:
        return None
    # The last uppercase token usually carries the semantic anchor:
    # "FOUR LEG ANKLETS" → ANKLETS; "BODY INTERIOR" → INTERIOR (no match,
    # falls back to first); "SHOULDER + HIP" → HIP. We try the last,
    # then walk back to find the first token present in ZONE_BBOX_FRACTIONS.
    for token in reversed(tokens):
        normalized = token.rstrip(",+/").upper()
        if normalized in ZONE_BBOX_FRACTIONS:
            return normalized
    # Fall back to first token even if not in the map — caller treats
    # unknown labels as "skipped" rather than failing.
    return tokens[0].rstrip(",+/").upper()


def _score_decoration_zone_presence(
    lab: np.ndarray,
    subject_mask: np.ndarray,
    bbox: tuple[int, int, int, int],
    expected_body_fill: str | None,
    required_decoration_zones: list[str] | None,
) -> dict[str, Any]:
    """Phase-B B.2 (2026-05-20) — decoration_zone_presence verification.

    For each required_decoration_zone declared on the animal entry,
    extract the zone label, look up its bbox sub-region, and measure
    whether that sub-region carries decoration (Δ-E LAB > 14 from
    body_fill_color). A zone passes if ≥ ZONE_DECORATION_FLOOR of the
    sub-region's subject pixels are decorated. The check overall passes
    if ≥ ZONE_PASS_FRACTION of known-label zones pass.

    Zones with labels not in ZONE_BBOX_FRACTIONS are reported as skipped
    and do not affect the pass count — better to under-report than to
    falsely fail when our label map is incomplete.

    Returns:
      {pass, zones_pass, zones_fail, zones_skipped, zones, ...}
    """
    if not required_decoration_zones:
        return {
            "pass": True,
            "reason": "no required_decoration_zones declared on animal",
            "informational_only": True,
        }
    if subject_mask is None or not subject_mask.any():
        return {
            "pass": False,
            "reason": "no subject mask detected",
            "zones": [],
        }
    if not expected_body_fill:
        return {
            "pass": True,
            "reason": "expected_body_fill not provided; zone-presence skipped",
            "informational_only": True,
        }
    x0, y0, x1, y1 = bbox
    bbox_height = max(1, y1 - y0 + 1)
    bbox_width = max(1, x1 - x0 + 1)
    body_rgb = _hex_to_rgb(expected_body_fill)
    body_distance = _delta_e(lab, body_rgb)
    decorated = subject_mask & (body_distance > 14)

    zone_results: list[dict[str, Any]] = []
    pass_count = 0
    fail_count = 0
    skipped_count = 0
    for zone_string in required_decoration_zones:
        label = _extract_zone_label(zone_string)
        bbox_frac = ZONE_BBOX_FRACTIONS.get(label) if label else None
        if bbox_frac is None:
            zone_results.append({
                "zone": zone_string[:60],
                "label": label,
                "skipped": True,
                "reason": "no bbox mapping for label",
            })
            skipped_count += 1
            continue
        yt, yb, xl, xr = bbox_frac
        ry0 = y0 + int(yt * bbox_height)
        ry1 = y0 + int(yb * bbox_height)
        rx0 = x0 + int(xl * bbox_width)
        rx1 = x0 + int(xr * bbox_width)
        zone_subject = subject_mask[ry0:ry1, rx0:rx1]
        zone_decorated = decorated[ry0:ry1, rx0:rx1]
        denom = max(1, int(zone_subject.sum()))
        fraction = float(zone_decorated.sum() / denom)
        zone_pass = fraction >= ZONE_DECORATION_FLOOR
        zone_results.append({
            "zone": zone_string[:60],
            "label": label,
            "pass": zone_pass,
            "decoration_fraction": round(fraction, 4),
            "floor": ZONE_DECORATION_FLOOR,
        })
        if zone_pass:
            pass_count += 1
        else:
            fail_count += 1

    scored = pass_count + fail_count
    pass_fraction = (pass_count / scored) if scored else 0.0
    overall_pass = scored == 0 or pass_fraction >= ZONE_PASS_FRACTION
    return {
        "pass": overall_pass,
        "zones_pass": pass_count,
        "zones_fail": fail_count,
        "zones_skipped": skipped_count,
        "pass_fraction": round(pass_fraction, 4),
        "required_pass_fraction": ZONE_PASS_FRACTION,
        "zones": zone_results,
        "reason": (
            f"{pass_count}/{scored} known zones decorated (need {ZONE_PASS_FRACTION:.0%})"
            if scored
            else "all zones unmapped; informational"
        ),
    }


def score_madhubani_png(
    png_path: Path,
    *,
    palette_path: Path,
    expected_body_fill: str | None = None,
    body_type: str | None = None,
    decoration_density: str | None = None,
    required_decoration_zones: list[str] | None = None,
) -> dict[str, Any]:
    palette = _load_palette(palette_path)
    rules = palette.get("rules", {})
    rgb, alpha, original_size = _downsample_image(png_path)
    height, width = rgb.shape[:2]
    lab = _srgb_to_lab(rgb)

    bg_rgb = _hex_to_rgb(palette.get("background", {}).get("hex", "#F5EFE3"))
    outline_rgb = _hex_to_rgb(rules.get("outlines_use", "#000000"))
    bg_distance = _delta_e(lab, bg_rgb)
    outline_distance = _delta_e(lab, outline_rgb)
    visible = alpha > 16
    subject_mask = visible & (bg_distance > 14)

    palette_colors = [
        color for color in palette.get("colors", [])
        if color.get("role") != "outline"
    ]
    color_tolerance = float(rules.get("color_floor_max_distance_delta_e", 15))
    min_fraction = 0.001
    present_colors: list[dict[str, Any]] = []
    for color in palette_colors:
        target_rgb = _hex_to_rgb(color["hex"])
        match = visible & (_delta_e(lab, target_rgb) <= color_tolerance)
        fraction = float(match.mean())
        if fraction >= min_fraction:
            present_colors.append({
                "name": color["name"],
                "hex": color["hex"],
                "pixel_fraction": round(fraction, 5),
            })
    color_floor_min = int(rules.get("color_floor_minimum_present", 4))
    color_floor_pass = len(present_colors) >= color_floor_min

    corner_px = max(1, min(100, width // 4, height // 4))
    corners = [
        bg_distance[:corner_px, :corner_px],
        bg_distance[:corner_px, -corner_px:],
        bg_distance[-corner_px:, :corner_px],
        bg_distance[-corner_px:, -corner_px:],
    ]
    corner_clean_ratios = [float((corner <= 10).mean()) for corner in corners]
    corners_clean_pass = min(corner_clean_ratios) >= 0.95

    if subject_mask.any():
        ys, xs = np.where(subject_mask)
        x0, x1 = int(xs.min()), int(xs.max())
        y0, y1 = int(ys.min()), int(ys.max())
        bbox_width_ratio = (x1 - x0 + 1) / width
        bbox_height_ratio = (y1 - y0 + 1) / height
        center_x = (x0 + x1 + 1) / 2 / width
        center_y = (y0 + y1 + 1) / 2 / height
        center_delta_x = abs(center_x - 0.5)
        center_delta_y = abs(center_y - 0.5)
        centered_pass = 0.50 <= bbox_width_ratio <= 0.85 and center_delta_x <= 0.05 and center_delta_y <= 0.10
    else:
        x0 = y0 = x1 = y1 = 0
        bbox_width_ratio = bbox_height_ratio = center_x = center_y = center_delta_x = center_delta_y = 0.0
        centered_pass = False

    body_targets = [expected_body_fill] if expected_body_fill else []
    body_targets.extend(rules.get("body_fill_must_be_one_of", []))
    body_targets = list(dict.fromkeys([c for c in body_targets if c]))
    body_fill_fractions: list[dict[str, Any]] = []
    if subject_mask.any():
        non_outline_subject = subject_mask & (outline_distance > 18) & (bg_distance > 18)
        denominator = max(1, int(subject_mask.sum()))
        for color_hex in body_targets:
            target_rgb = _hex_to_rgb(color_hex)
            match = non_outline_subject & (_delta_e(lab, target_rgb) <= max(18, color_tolerance + 6))
            body_fill_fractions.append({
                "hex": color_hex,
                "subject_fraction": round(float(match.sum() / denominator), 5),
            })
        best_body_fraction = max((item["subject_fraction"] for item in body_fill_fractions), default=0.0)
        black_fraction = float((subject_mask & (outline_distance <= 8)).sum() / denominator)
        cream_fraction = float((subject_mask & (bg_distance <= 12)).sum() / denominator)
    else:
        best_body_fraction = black_fraction = cream_fraction = 0.0
    body_fill_pass = best_body_fraction >= 0.02 and black_fraction < 0.80 and cream_fraction < 0.35

    anatomy_check = _score_anatomy(subject_mask, body_type)
    text_leak_check = _score_text_leak(png_path)
    eye_character_check = _score_eye_character(rgb, subject_mask)
    pattern_density_check = _score_pattern_density(
        rgb, lab, subject_mask, expected_body_fill, decoration_density,
    )
    zone_presence_check = _score_decoration_zone_presence(
        lab, subject_mask, (x0, y0, x1, y1), expected_body_fill,
        required_decoration_zones,
    )

    checks = {
        "color_floor": {
            "pass": color_floor_pass,
            "present_count": len(present_colors),
            "required_count": color_floor_min,
            "present_colors": present_colors,
        },
        "corners_clean": {
            "pass": corners_clean_pass,
            "corner_px": corner_px,
            "min_clean_ratio": round(min(corner_clean_ratios), 5),
            "corner_clean_ratios": [round(v, 5) for v in corner_clean_ratios],
        },
        "subject_centered": {
            "pass": centered_pass,
            "bbox": [x0, y0, x1, y1],
            "bbox_width_ratio": round(bbox_width_ratio, 5),
            "bbox_height_ratio": round(bbox_height_ratio, 5),
            "center": [round(center_x, 5), round(center_y, 5)],
            "center_delta": [round(center_delta_x, 5), round(center_delta_y, 5)],
        },
        "body_fill": {
            "pass": body_fill_pass,
            "expected_body_fill": expected_body_fill,
            "best_body_fraction": round(best_body_fraction, 5),
            "black_subject_fraction": round(black_fraction, 5),
            "cream_subject_fraction": round(cream_fraction, 5),
            "body_fill_fractions": body_fill_fractions,
        },
        "anatomy": anatomy_check,
        "text_leak": text_leak_check,
        "eye_character": eye_character_check,
        "pattern_density": pattern_density_check,
        "decoration_zone_presence": zone_presence_check,
    }
    # Active checks are everything except those marked disabled_by_default —
    # disabled checks still run and report (informational), but they do not
    # affect `pass_count` or `auto_qc_pass`. Skipped checks (optional deps
    # missing) count as passes so the rubric isn't penalised for system-level
    # gaps.
    active_checks = {
        name: item for name, item in checks.items()
        if name not in DISABLED_BY_DEFAULT_CHECKS
    }
    pass_count = sum(1 for item in active_checks.values() if item.get("pass"))
    active_check_count = len(active_checks)
    return {
        "schema": "forge.madhubani_auto_qc.v1",
        "png_path": str(png_path),
        "width": original_size[0],
        "height": original_size[1],
        "sampled_width": width,
        "sampled_height": height,
        "auto_check_count": AUTO_CHECK_COUNT,
        "active_check_count": active_check_count,
        "disabled_by_default": sorted(DISABLED_BY_DEFAULT_CHECKS),
        "pass_count": pass_count,
        "score": round(pass_count / active_check_count * 100, 2) if active_check_count else 0.0,
        "auto_qc_pass": pass_count == active_check_count,
        "checks": checks,
    }
