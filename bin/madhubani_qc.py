"""Automatic QC gates for the Madhubani tee catalog.

This module covers the four rubric checks that are intentionally mechanical:
palette floor, clean corners, centered subject, and saturated body fill. It is
not a replacement for the human review gates around anatomy, expression, and
Madhubani read.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


AUTO_CHECK_COUNT = 4


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


def score_madhubani_png(
    png_path: Path,
    *,
    palette_path: Path,
    expected_body_fill: str | None = None,
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
    }
    pass_count = sum(1 for item in checks.values() if item["pass"])
    return {
        "schema": "forge.madhubani_auto_qc.v1",
        "png_path": str(png_path),
        "width": original_size[0],
        "height": original_size[1],
        "sampled_width": width,
        "sampled_height": height,
        "auto_check_count": AUTO_CHECK_COUNT,
        "pass_count": pass_count,
        "score": round(pass_count / AUTO_CHECK_COUNT * 100, 2),
        "auto_qc_pass": pass_count == AUTO_CHECK_COUNT,
        "checks": checks,
    }
