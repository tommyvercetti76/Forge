"""Tests for the three new Madhubani auto-QC checks (A2):
anatomy (leg-pillar count by body_type), text_leak (OCR), and
eye_character (head-band luminance contrast). The four existing checks
are exercised by tests/test_madhubani_qc.py and must keep passing.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from madhubani_qc import (
    AUTO_CHECK_COUNT,
    _score_anatomy,
    _score_eye_character,
    _score_text_leak,
)


def _quadruped_mask(legs: int, *, height: int = 256, width: int = 256) -> np.ndarray:
    """Synthetic subject mask: a torso slab plus N evenly-spaced leg pillars.

    Torso occupies the top 60% of the bounding box; legs occupy the bottom
    30%. Leg columns are 8px wide and separated by ≥10px gaps so the
    leg-pillar detector can resolve them.
    """
    mask = np.zeros((height, width), dtype=bool)
    # Torso: rows 60..170, cols 60..200 — sets a stable bbox top.
    mask[60:170, 60:200] = True
    leg_top = 170
    leg_bottom = 220  # well inside the bottom-30% band of the 60..220 bbox
    leg_width = 8
    # Spread N legs across the torso width with at least 10px between them.
    start = 70
    spacing = 24
    for idx in range(legs):
        x0 = start + idx * spacing
        x1 = x0 + leg_width
        if x1 >= width:
            break
        mask[leg_top:leg_bottom, x0:x1] = True
    return mask


class AnatomyCheckTests(unittest.TestCase):
    def test_pass_on_four_pillar_quadruped_mask(self) -> None:
        mask = _quadruped_mask(legs=4)
        result = _score_anatomy(mask, "lean-predator")
        self.assertTrue(result["pass"])
        self.assertGreaterEqual(result["leg_pillars_detected"], 3)
        self.assertEqual(result["leg_pillars_expected"], 3)
        self.assertEqual(result["body_type"], "lean-predator")

    def test_fail_on_one_pillar_predator(self) -> None:
        mask = _quadruped_mask(legs=1)
        result = _score_anatomy(mask, "lean-predator")
        self.assertFalse(result["pass"])
        self.assertEqual(result["leg_pillars_detected"], 1)
        self.assertEqual(result["leg_pillars_expected"], 3)

    def test_serpent_passes_by_definition(self) -> None:
        # A coil-shape mask with zero leg pillars must still pass because
        # serpents do not have legs in the rubric.
        coil = np.zeros((256, 256), dtype=bool)
        # Roughly circular coil — solid blob, no leg structure.
        ys, xs = np.indices(coil.shape)
        coil[(ys - 128) ** 2 + (xs - 128) ** 2 <= 60 ** 2] = True
        result = _score_anatomy(coil, "serpent")
        self.assertTrue(result["pass"])
        self.assertEqual(result["leg_pillars_expected"], 0)


class TextLeakCheckTests(unittest.TestCase):
    def test_skipped_when_pytesseract_missing(self) -> None:
        """Force ImportError on `import pytesseract` and verify the check
        skips gracefully (pass=True, skipped=True). This mirrors how
        production behaves on machines without the optional dep installed.
        """
        sentinel = object()
        original = sys.modules.get("pytesseract", sentinel)
        sys.modules["pytesseract"] = None  # type: ignore[assignment]
        try:
            with tempfile.TemporaryDirectory() as td:
                png_path = Path(td) / "empty.png"
                Image.new("RGB", (32, 32), "#F5EFE3").save(png_path)
                result = _score_text_leak(png_path)
            self.assertTrue(result["pass"])
            self.assertTrue(result["skipped"])
            self.assertIn("pytesseract", result["reason"].lower())
        finally:
            if original is sentinel:
                sys.modules.pop("pytesseract", None)
            else:
                sys.modules["pytesseract"] = original  # type: ignore[assignment]


class EyeCharacterCheckTests(unittest.TestCase):
    def test_pass_on_high_contrast_head_band(self) -> None:
        # Subject mask covering rows 20..200 — top 25% is rows 20..65.
        height = 256
        width = 256
        mask = np.zeros((height, width), dtype=bool)
        mask[20:200, 60:200] = True
        # Fill the RGB image with a saturated walnut body, then drop a few
        # bright sclera pixels and dark pupil pixels inside the head band.
        rgb = np.full((height, width, 3), [90, 58, 31], dtype=np.uint8)
        # Bright sclera spot (≈ luminance 230) and dark pupil (≈ luminance 5)
        rgb[30:36, 100:108] = [240, 240, 240]
        rgb[30:36, 140:148] = [5, 5, 5]
        result = _score_eye_character(rgb, mask)
        self.assertTrue(result["pass"])
        self.assertGreater(result["luminance_max"] - result["luminance_min"], 80)

    def test_fail_on_uniform_head_band(self) -> None:
        height = 256
        width = 256
        mask = np.zeros((height, width), dtype=bool)
        mask[20:200, 60:200] = True
        # Single saturated color across the entire subject — no eye marks.
        rgb = np.full((height, width, 3), [90, 58, 31], dtype=np.uint8)
        result = _score_eye_character(rgb, mask)
        self.assertFalse(result["pass"])
        self.assertLessEqual(result["luminance_max"] - result["luminance_min"], 80)


class AutoCheckCountTests(unittest.TestCase):
    def test_constant_matches_active_checks(self) -> None:
        # Bumped 7 → 8 in Phase-B B.1 (2026-05-20) when pattern_density landed.
        # The auto-check rubric now scores: color_floor, corners_clean,
        # subject_centered, body_fill, anatomy, text_leak, eye_character,
        # pattern_density. Anatomy is informational (disabled_by_default).
        self.assertEqual(AUTO_CHECK_COUNT, 8)


if __name__ == "__main__":
    unittest.main()
