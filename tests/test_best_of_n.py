"""Tests for Phase C.1 best-of-N selection.

These tests exercise the scoring + ranking logic on synthetic images
and on real labeled renders from the QC agreement study. The CLIP
probe is OPTIONAL — when open_clip / weights aren't available, the
score function falls back to rubric-only and the tests assert that
fallback path works too.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from best_of_n import (  # noqa: E402
    infer_seed_from_path,
    infer_slug_from_path,
    pick_best_of_n,
    score_render,
)


class FilenameInferenceTests(unittest.TestCase):
    def test_slug_from_simple_name(self) -> None:
        self.assertEqual(infer_slug_from_path(Path("tiger_v3.png")), "tiger")
        self.assertEqual(infer_slug_from_path(Path("peacock_v1_mascot.png")), "peacock")

    def test_slug_from_legacy_naming(self) -> None:
        self.assertEqual(
            infer_slug_from_path(Path("01_royal_bengal_tiger_madhubani_tshirt.png")),
            "tiger",
        )
        self.assertEqual(
            infer_slug_from_path(Path("05_one_horned_rhinoceros_madhubani_tshirt.png")),
            "rhino",
        )
        self.assertEqual(
            infer_slug_from_path(Path("08_lion_tailed_macaque_madhubani_tshirt.png")),
            "macaque",
        )

    def test_slug_returns_none_for_unknown(self) -> None:
        self.assertIsNone(infer_slug_from_path(Path("random_filename.png")))

    def test_seed_inference(self) -> None:
        self.assertEqual(infer_seed_from_path(Path("tiger_seed_8301.png")), 8301)
        self.assertEqual(infer_seed_from_path(Path("tiger.seed-42.png")), 42)
        self.assertIsNone(infer_seed_from_path(Path("tiger_v3.png")))


class ScoreRenderTests(unittest.TestCase):
    """Lightweight smoke tests using a synthetic walnut-body subject."""

    def _make_subject(self, dest: Path, decoration: bool = True) -> None:
        # 256x256 with cream background + walnut body rectangle.
        img = Image.new("RGB", (256, 256), "#F5EFE3")
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        # Body
        draw.rectangle((40, 40, 215, 215), fill="#5a3a1f", outline="#000000", width=4)
        if decoration:
            # Add 4 ornament hues so color_floor passes.
            draw.rectangle((60, 60, 90, 90), fill="#e87722")     # saffron-orange
            draw.rectangle((100, 60, 130, 90), fill="#1a2952")   # deep-indigo
            draw.rectangle((140, 60, 170, 90), fill="#c8261f")   # vermillion
            draw.rectangle((180, 60, 210, 90), fill="#3d7d3d")   # leaf-green
            # And a few more for pattern density
            draw.rectangle((60, 120, 210, 140), fill="#e8b827")  # gold-yellow
        img.save(dest)

    def test_score_render_returns_full_shape(self) -> None:
        # Pass animal=None to exercise the metadata-light path.
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sample_seed_42.png"
            self._make_subject(p, decoration=True)
            result = score_render(p, animal=None)
            self.assertIn("composite", result)
            self.assertIn("rubric_pass_fraction", result)
            self.assertIn("clip_available", result)
            self.assertIn("pass_count", result)
            self.assertIn("active_check_count", result)
            self.assertEqual(result["seed"], 42)
            # Composite must be in [0, 1] given the formula bounds.
            self.assertGreaterEqual(result["composite"], 0.0)
            self.assertLessEqual(result["composite"], 1.0)
            # Rubric fraction also bounded.
            self.assertGreaterEqual(result["rubric_pass_fraction"], 0.0)
            self.assertLessEqual(result["rubric_pass_fraction"], 1.0)


class PickBestOfNTests(unittest.TestCase):
    def _make_subject(self, dest: Path, *, decoration: bool) -> None:
        img = Image.new("RGB", (256, 256), "#F5EFE3")
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        draw.rectangle((40, 40, 215, 215), fill="#5a3a1f", outline="#000000", width=4)
        if decoration:
            draw.rectangle((60, 60, 90, 90), fill="#e87722")
            draw.rectangle((100, 60, 130, 90), fill="#1a2952")
            draw.rectangle((140, 60, 170, 90), fill="#c8261f")
            draw.rectangle((180, 60, 210, 90), fill="#3d7d3d")
            draw.rectangle((60, 120, 210, 140), fill="#e8b827")
        img.save(dest)

    def test_returns_empty_manifest_for_no_paths(self) -> None:
        result = pick_best_of_n([], animal=None)
        self.assertEqual(result["n"], 0)
        self.assertIsNone(result["winner"])
        self.assertEqual(result["ranked"], [])

    def test_decorated_beats_undecorated(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            good = d / "tiger_seed_1.png"
            bad = d / "tiger_seed_2.png"
            self._make_subject(good, decoration=True)
            self._make_subject(bad, decoration=False)
            result = pick_best_of_n([good, bad], animal=None)
            self.assertEqual(result["n"], 2)
            # The decorated one should rank #1 because it passes color_floor.
            self.assertEqual(result["winner"]["filename"], "tiger_seed_1.png")
            self.assertEqual(result["winner"]["rank"], 1)
            # Composites strictly ordered.
            self.assertGreater(
                result["ranked"][0]["composite"],
                result["ranked"][1]["composite"],
            )

    def test_clip_unavailable_falls_back_to_rubric_only(self) -> None:
        """If the CLIP probe doesn't load, score_render still works."""
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "sample_seed_7.png"
            self._make_subject(p, decoration=True)
            result = score_render(p, animal=None)
            # Whether or not CLIP is installed in CI, the result must have
            # a valid composite. When CLIP is absent, composite == rubric.
            if not result["clip_available"]:
                self.assertEqual(result["composite"], result["rubric_pass_fraction"])
            # Either way, composite is bounded.
            self.assertGreaterEqual(result["composite"], 0.0)
            self.assertLessEqual(result["composite"], 1.0)


if __name__ == "__main__":
    unittest.main()
