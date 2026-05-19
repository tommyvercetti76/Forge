from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from forge_runtime import validate_png
from minimal_animal_engine import MinimalAnimalConfig, infer_animal_type, write_minimal_animal


class MinimalAnimalEngineTests(unittest.TestCase):
    def test_infers_common_animal_classes(self) -> None:
        self.assertEqual(infer_animal_type("a cobra rising in a calm curve"), "serpent")
        self.assertEqual(infer_animal_type("an elephant walking left"), "elephant")
        self.assertEqual(infer_animal_type("a blue jay perched on a branch"), "bird")

    def test_writes_closed_loop_artifacts_with_no_more_than_eight_lines(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "tiger.png"
            artifact = write_minimal_animal(
                MinimalAnimalConfig(
                    description="alert tiger in side profile with a long tail",
                    max_lines=8,
                    width=512,
                    height=512,
                    supersample=1,
                ),
                out,
            )
            validate_png(Path(artifact["png"]), width=512, height=512, min_bytes=512)
            svg = Path(artifact["svg"]).read_text(encoding="utf-8")
            self.assertIn('data-forge-engine="minimal-animal-lines"', svg)
            self.assertEqual(svg.count("<polyline"), 8)
            qc = json.loads(Path(artifact["qc"]).read_text(encoding="utf-8"))
            self.assertTrue(qc["closed_loop_pass"])
            self.assertLessEqual(qc["line_count"], 8)
            manifest = json.loads(Path(artifact["manifest"]).read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "PASS")
            self.assertFalse(manifest["closed_loop"]["cpu_ml_fallback"])

    def test_respects_lower_line_budget(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            artifact = write_minimal_animal(
                MinimalAnimalConfig(description="minimal elephant", max_lines=5, width=512, height=512, supersample=1),
                Path(td) / "elephant.png",
            )
            qc = json.loads(Path(artifact["qc"]).read_text(encoding="utf-8"))
            self.assertEqual(qc["line_count"], 5)
            self.assertTrue(qc["line_count_pass"])


if __name__ == "__main__":
    unittest.main()
