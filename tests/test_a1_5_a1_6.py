"""A1.5 + A1.6 — strengthen the body-fill override and add hard negatives
against natural species coloration so FLUX's pretrained signal (tiger →
bright orange, lion → tan, peacock → blue, parrot → green) does not
override the Madhubani convention (deep-indigo / walnut-brown body + folk
panel overlay).

The bug surfaced today: pre-A1.5/A1.6 renders of tigers came out as
generic stylized orange tigers despite the engine prompt saying "body
filled with saturated walnut-brown". The override needed to be louder
(A1.5) and the natural reading explicitly suppressed (A1.6).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import forge_madhubani  # noqa: E402
from style_engines import MinimalistTShirtEngine  # noqa: E402


class A1_5_BodyFillOverrideTests(unittest.TestCase):
    """The subject string built for any animal must carry the loud override."""

    def _build_for(self, slug: str) -> str:
        animal = forge_madhubani.find_animal(slug)
        pose = forge_madhubani.find_pose("standing-alert")
        return forge_madhubani.build_subject_string(animal, pose, "madhubani-master-painter")

    def test_tiger_subject_carries_walnut_override(self) -> None:
        s = self._build_for("tiger")
        self.assertIn("BODY FILL OVERRIDE", s)
        self.assertIn("walnut-brown", s.lower())
        self.assertIn("#5a3a1f", s.lower())  # body_fill_color from animals.json

    def test_tiger_subject_names_what_to_avoid(self) -> None:
        s = self._build_for("tiger").lower()
        self.assertIn("natural tiger orange", s)
        self.assertIn("not a naturalistic species render", s)
        self.assertIn("national-geographic", s)

    def test_elephant_subject_carries_indigo_override(self) -> None:
        s = self._build_for("elephant")
        self.assertIn("BODY FILL OVERRIDE", s)
        # elephant's body_fill_color_name from animals.json
        self.assertIn("deep-indigo", s.lower())

    def test_override_phrase_uses_loud_language(self) -> None:
        s = self._build_for("tiger")
        self.assertIn("CRITICAL", s)
        self.assertIn("MUST", s)
        self.assertIn("DO NOT", s)


class A1_6_AntiNaturalColorNegativesTests(unittest.TestCase):
    """MinimalistTShirtEngine.engine_negatives carries explicit anti-natural-color phrases."""

    def test_natural_tiger_orange_is_a_negative(self) -> None:
        self.assertIn(
            "realistic tiger orange body",
            MinimalistTShirtEngine.engine_negatives,
        )

    def test_naturalistic_species_rendering_is_a_negative(self) -> None:
        self.assertIn(
            "naturalistic species rendering",
            MinimalistTShirtEngine.engine_negatives,
        )

    def test_other_high_pull_species_covered(self) -> None:
        joined = " | ".join(MinimalistTShirtEngine.engine_negatives)
        self.assertIn("natural lion tan", joined)
        self.assertIn("natural peacock blue", joined)
        self.assertIn("natural parrot green", joined)

    def test_pre_existing_negatives_preserved(self) -> None:
        # Anti-mascot regression negatives from 2026-05-18 must still be present.
        self.assertIn(
            "western mascot logo",
            MinimalistTShirtEngine.engine_negatives,
        )
        self.assertIn(
            "monochrome silhouette of an animal",
            MinimalistTShirtEngine.engine_negatives,
        )


if __name__ == "__main__":
    unittest.main()
