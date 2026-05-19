from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from madhubani_qc import score_madhubani_png


class MadhubaniQCTests(unittest.TestCase):
    def test_scores_passing_palette_center_and_body_fill(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "passing.png"
            img = Image.new("RGB", (512, 512), "#F5EFE3")
            draw = ImageDraw.Draw(img)
            draw.rectangle((105, 135, 407, 380), fill="#5a3a1f", outline="#000000", width=8)
            for idx, color in enumerate(["#e87722", "#3d7d3d", "#c8261f", "#e8b827"]):
                x = 130 + idx * 58
                draw.rectangle((x, 180, x + 32, 310), fill=color)
            img.save(path)

            qc = score_madhubani_png(
                path,
                palette_path=ROOT / "brand" / "madhubani" / "palette.json",
                expected_body_fill="#5a3a1f",
            )

            self.assertTrue(qc["checks"]["color_floor"]["pass"])
            self.assertTrue(qc["checks"]["corners_clean"]["pass"])
            self.assertTrue(qc["checks"]["subject_centered"]["pass"])
            self.assertTrue(qc["checks"]["body_fill"]["pass"])
            self.assertTrue(qc["auto_qc_pass"])

    def test_black_silhouette_fails_body_fill_and_color_floor(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "bad.png"
            img = Image.new("RGB", (512, 512), "#F5EFE3")
            draw = ImageDraw.Draw(img)
            draw.rectangle((120, 150, 392, 360), fill="#000000")
            img.save(path)

            qc = score_madhubani_png(
                path,
                palette_path=ROOT / "brand" / "madhubani" / "palette.json",
                expected_body_fill="#5a3a1f",
            )

            self.assertFalse(qc["checks"]["color_floor"]["pass"])
            self.assertFalse(qc["checks"]["body_fill"]["pass"])
            self.assertFalse(qc["auto_qc_pass"])


if __name__ == "__main__":
    unittest.main()
