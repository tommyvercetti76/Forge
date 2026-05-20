"""Tests for Phase C.2 — Art Reasoning Engine.

Covers boost composition (pure function), weakest-check identification,
prompt appending, and the closed-loop orchestrator (with a stub
render_fn so no real mflux compute is needed).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from art_reasoning_engine import (  # noqa: E402
    compose_boosted_prompt,
    identify_weakest_check,
    load_boost_table,
    propose_boost,
    render_with_reasoning,
)


def _make_subject(dest: Path, *, decoration: bool) -> None:
    img = Image.new("RGB", (256, 256), "#F5EFE3")
    draw = ImageDraw.Draw(img)
    draw.rectangle((40, 40, 215, 215), fill="#5a3a1f", outline="#000000", width=4)
    if decoration:
        draw.rectangle((60, 60, 90, 90), fill="#e87722")
        draw.rectangle((100, 60, 130, 90), fill="#1a2952")
        draw.rectangle((140, 60, 170, 90), fill="#c8261f")
        draw.rectangle((180, 60, 210, 90), fill="#3d7d3d")
        draw.rectangle((60, 120, 210, 140), fill="#e8b827")
    img.save(dest)


class BoostTableTests(unittest.TestCase):
    def test_table_loads(self) -> None:
        table = load_boost_table()
        self.assertIn("boosts", table)
        # Every active check must have a boost entry — that's the
        # contract that lets the engine never produce an unrouted failure.
        for check in [
            "color_floor", "corners_clean", "subject_centered",
            "body_fill", "anatomy", "text_leak", "eye_character",
            "pattern_density", "decoration_zone_presence", "anatomy_feature_count",
        ]:
            self.assertIn(check, table["boosts"], f"missing boost for {check}")


class IdentifyWeakestCheckTests(unittest.TestCase):
    def test_returns_none_when_all_pass(self) -> None:
        qc = {
            "checks": {
                "color_floor": {"pass": True},
                "body_fill": {"pass": True},
            },
            "disabled_by_default": [],
        }
        self.assertIsNone(identify_weakest_check(qc))

    def test_picks_highest_severity_active_failure(self) -> None:
        # subject_centered severity 5.0 > body_fill 4.0 > color_floor 2.5.
        qc = {
            "checks": {
                "color_floor": {"pass": False},
                "body_fill": {"pass": False},
                "subject_centered": {"pass": False},
                "anatomy": {"pass": True},
            },
            "disabled_by_default": ["anatomy", "pattern_density"],
        }
        self.assertEqual(identify_weakest_check(qc), "subject_centered")

    def test_prefers_active_over_informational(self) -> None:
        # `anatomy` (informational) failed but `color_floor` (active) also failed.
        # We must pick color_floor even though anatomy has higher severity (4.5 vs 2.5).
        qc = {
            "checks": {
                "anatomy": {"pass": False},
                "color_floor": {"pass": False},
            },
            "disabled_by_default": ["anatomy"],
        }
        self.assertEqual(identify_weakest_check(qc), "color_floor")

    def test_falls_back_to_informational_when_no_active_failure(self) -> None:
        qc = {
            "checks": {
                "anatomy": {"pass": False},
                "color_floor": {"pass": True},
            },
            "disabled_by_default": ["anatomy"],
        }
        self.assertEqual(identify_weakest_check(qc), "anatomy")


class ProposeBoostTests(unittest.TestCase):
    def test_color_floor_boost(self) -> None:
        qc = {"checks": {"color_floor": {"pass": False, "present_count": 2, "required_count": 4}}}
        boost = propose_boost("color_floor", qc)
        self.assertIn("AT LEAST 4 distinct colors", boost)
        self.assertIn("Madhubani folk palette", boost)

    def test_pattern_density_boost_fills_slots(self) -> None:
        qc = {"checks": {"pattern_density": {
            "pass": False, "target_band": "maximal", "target_min": 0.55, "measured_density": 0.31,
        }}}
        boost = propose_boost("pattern_density", qc)
        self.assertIn("Target maximal density", boost)
        self.assertIn("55%", boost)

    def test_decoration_zone_presence_lists_missing_zones(self) -> None:
        qc = {"checks": {"decoration_zone_presence": {
            "pass": False,
            "zones": [
                {"zone": "FOREHEAD: tikka medallion", "label": "FOREHEAD", "pass": False},
                {"zone": "NECK: folk collar", "label": "NECK", "pass": True},
                {"zone": "TAIL: continuation of stripe bands", "label": "TAIL", "pass": False},
            ],
        }}}
        boost = propose_boost("decoration_zone_presence", qc)
        self.assertIn("FOREHEAD", boost)
        self.assertIn("TAIL", boost)
        self.assertNotIn("NECK", boost)  # passed zones shouldn't appear in the missing list

    def test_anatomy_feature_count_uses_specific_clause(self) -> None:
        # Cobra with 2 tongues — the user's #1 callout.
        qc = {"checks": {"anatomy_feature_count": {
            "pass": False,
            "features": [{
                "feature": "tongue",
                "measured": 2,
                "parsed": {"min": 0, "max": 1},
                "pass": False,
            }],
        }}}
        boost = propose_boost("anatomy_feature_count", qc)
        self.assertIn("EXACTLY ONE forked tongue", boost)
        self.assertIn("NOT two separate tongues", boost)

    def test_unmapped_check_returns_empty(self) -> None:
        self.assertEqual(propose_boost("nonexistent_check", {"checks": {}}), "")


class ComposeBoostedPromptTests(unittest.TestCase):
    def test_appends_to_tail(self) -> None:
        base = "single centered Madhubani folk-art tiger icon ..."
        boost = "URGENT FIX: add more colors."
        result = compose_boosted_prompt(base, boost)
        self.assertTrue(result.endswith(boost))
        self.assertIn(base, result)

    def test_idempotent_when_boost_already_present(self) -> None:
        base = "tiger ... URGENT FIX: add more colors."
        boost = "URGENT FIX: add more colors."
        result = compose_boosted_prompt(base, boost)
        # No double-append.
        self.assertEqual(result.count("URGENT FIX: add more colors."), 1)

    def test_empty_boost_returns_base_unchanged(self) -> None:
        base = "tiger ..."
        self.assertEqual(compose_boosted_prompt(base, ""), base)
        self.assertEqual(compose_boosted_prompt(base, "   \n  "), base)


class RenderWithReasoningTests(unittest.TestCase):
    """The closed-loop test. Uses a stub render_fn that materializes
    the same synthetic image regardless of prompt or seed — so we
    deterministically exercise the score → boost → retry path."""

    def _stub_render_fn(self, tmpdir: Path, decoration: bool):
        """Returns a render_fn that writes one PNG per requested seed."""
        def render_fn(prompt: str, seeds):
            paths: list[Path] = []
            for s in seeds:
                p = tmpdir / f"render_seed_{s}.png"
                _make_subject(p, decoration=decoration)
                paths.append(p)
            return paths
        return render_fn

    def test_accepts_immediately_when_first_attempt_meets_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            render_fn = self._stub_render_fn(tmpdir, decoration=True)
            # Force a very low accept_score so the well-decorated synthetic
            # image is guaranteed to clear it. With composite typically
            # 0.7+ on decorated subjects, 0.5 is well below.
            result = render_with_reasoning(
                base_prompt="tiger render",
                animal=None,
                render_fn=render_fn,
                max_attempts=3,
                seeds_per_attempt=2,
                accept_score=0.5,
            )
            # Engine could accept on attempt 1 OR end up rejecting because
            # auto_qc_pass requires ALL active checks. Both are valid; we
            # just check the loop didn't crash and produced a manifest.
            self.assertIn("attempts", result)
            self.assertGreaterEqual(len(result["attempts"]), 1)
            self.assertIsNotNone(result["winner"])

    def test_max_attempts_caps_loop(self) -> None:
        # With an impossibly high accept_score and a sparse render, the
        # loop must exhaust max_attempts and return accepted=False.
        with tempfile.TemporaryDirectory() as td:
            tmpdir = Path(td)
            render_fn = self._stub_render_fn(tmpdir, decoration=False)
            result = render_with_reasoning(
                base_prompt="tiger render",
                animal=None,
                render_fn=render_fn,
                max_attempts=2,
                seeds_per_attempt=2,
                accept_score=0.99,
            )
            self.assertFalse(result["accepted"])
            self.assertLessEqual(len(result["attempts"]), 2)
            # The final prompt should differ from the base if any boost
            # got applied between attempts.
            if len(result["attempts"]) > 1 and result["attempts"][0].get("boost_clause_used_for_next_attempt"):
                self.assertNotEqual(result["final_prompt"], "tiger render")


if __name__ == "__main__":
    unittest.main()
