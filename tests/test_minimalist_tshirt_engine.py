from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import style_engines
from style_engines import (
    MTCompositionConfig,
    MTProductionConfig,
    MTStyleConfig,
    MinimalistTShirtConfig,
    MinimalistTShirtEngine,
    MTSubjectConfig,
)


class MinimalistTShirtEngineTests(unittest.TestCase):
    def test_engine_is_registered(self) -> None:
        self.assertIn("minimalist-tshirt", style_engines.list_engines())
        info = style_engines.describe_engine("minimalist-tshirt")
        self.assertIn("motif", info["vocabulary"])
        self.assertIn("tradition", info["vocabulary"])
        self.assertIn("detail", info["vocabulary"])
        self.assertIn("ink", info["vocabulary"])
        self.assertIn("placement", info["vocabulary"])

    def test_print_art_prompt_rejects_mockup_noise(self) -> None:
        directive = MinimalistTShirtEngine.build(
            MinimalistTShirtConfig(
                subject=MTSubjectConfig(
                    subject="a one-line mountain ridge with a small rising sun",
                    motif="monoline-icon",
                ),
                production=MTProductionConfig(output="print-art", ink="one-ink-black"),
                composition=MTCompositionConfig(placement="center-chest", layout="single-mark"),
                seed=9,
            )
        )
        self.assertEqual(directive.engine, "minimalist-tshirt")
        self.assertIn("screen-printable apparel", directive.positive)
        self.assertIn("no garment, no photo mockup", directive.positive)
        self.assertIn("do not invent readable words", directive.positive)
        self.assertIn("mockup", " ".join(directive.negatives))

    def test_left_pocket_gets_reduction_pressure(self) -> None:
        directive = MinimalistTShirtEngine.build(
            MinimalistTShirtConfig(
                subject=MTSubjectConfig(subject="a tiny chai cup with three steam lines"),
                production=MTProductionConfig(output="shirt-mockup", ink="one-ink-white", shirt_color="forest-green"),
                composition=MTCompositionConfig(placement="left-pocket", layout="stacked-symbols"),
            )
        )
        self.assertIn("POCKET-SIZE REDUCTION", directive.positive)
        self.assertIn("forest green blank T-shirt", directive.positive)

    def test_madhubani_popti_path_keeps_folk_detail_and_three_inks(self) -> None:
        directive = MinimalistTShirtEngine.build(
            MinimalistTShirtConfig(
                subject=MTSubjectConfig(
                    subject="single centered popti green parrot in side profile with almond eye",
                    motif="madhubani-folk-icon",
                ),
                style=MTStyleConfig(
                    tradition="madhubani-contemporary",
                    detail="ornamental-balanced",
                    symmetry="handmade-balanced",
                    accents="small-floral-only",
                ),
                production=MTProductionConfig(
                    output="print-art",
                    ink="three-ink-popti-red-black",
                    shirt_color="cream-or-black",
                ),
                composition=MTCompositionConfig(
                    placement="center-chest",
                    layout="single-mark",
                    background="no-background",
                    border="none",
                ),
            )
        )
        self.assertIn("Madhubani / Mithila-inspired contemporary apparel", directive.positive)
        self.assertIn("three screen-print inks maximum", directive.positive)
        self.assertIn("Small ornamental floral accents", directive.positive)
        self.assertIn("Sita Devi", directive.positive)
        self.assertIn("No border", directive.positive)

    def test_vibrant_madhubani_animal_series_locks_runtime_and_avoids_mascot_drift(self) -> None:
        directive = MinimalistTShirtEngine.build(
            MinimalistTShirtConfig(
                subject=MTSubjectConfig(
                    subject="single centered Royal Bengal tiger in full-body side profile",
                    motif="madhubani-folk-icon",
                ),
                style=MTStyleConfig(
                    tradition="madhubani-contemporary",
                    detail="maximal-but-printable",
                    symmetry="handmade-balanced",
                    accents="micro-folk-dots",
                ),
                production=MTProductionConfig(
                    output="print-art",
                    ink="vibrant-folk",
                    shirt_color="cream-or-black",
                ),
            )
        )
        self.assertEqual(directive.runtime["steps"], 18)
        self.assertIn("MADHUBANI ANIMAL-SERIES CONSISTENCY", directive.positive)
        self.assertIn("complete side-profile animal mark", directive.positive)
        self.assertIn("sports mascot logo", directive.negatives)
        self.assertIn("glossy sticker vector", directive.negatives)


if __name__ == "__main__":
    unittest.main()
