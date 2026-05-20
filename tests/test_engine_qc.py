"""Tests for the engine_qc trust layer — derive_blockers, write_blockers_json,
is_publishable, and the file conventions (.qc.json sibling, .blockers.json
sibling, stale-cleanup on re-pass)."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

BIN = Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

import engine_qc  # noqa: E402


def _qc_payload(*, fail: list[str] = ()) -> dict:
    """Build a QC sidecar payload mirroring the Madhubani schema."""
    checks: dict[str, dict] = {
        "color_floor": {
            "pass": "color_floor" not in fail,
            "present_count": 2 if "color_floor" in fail else 5,
            "required_count": 4,
        },
        "corners_clean": {
            "pass": "corners_clean" not in fail,
            "min_clean_ratio": 0.62 if "corners_clean" in fail else 0.98,
        },
        "subject_centered": {
            "pass": "subject_centered" not in fail,
            "bbox_width_ratio": 0.22 if "subject_centered" in fail else 0.74,
            "center": [0.40, 0.50],
        },
        "body_fill": {
            "pass": "body_fill" not in fail,
            "best_body_fraction": 0.005 if "body_fill" in fail else 0.41,
            "black_subject_fraction": 0.92 if "body_fill" in fail else 0.18,
            "cream_subject_fraction": 0.55 if "body_fill" in fail else 0.12,
        },
    }
    pass_count = sum(1 for c in checks.values() if c["pass"])
    return {
        "schema": "forge.madhubani_auto_qc.v1",
        "auto_check_count": 4,
        "pass_count": pass_count,
        "score": pass_count / 4 * 100,
        "auto_qc_pass": pass_count == 4,
        "checks": checks,
    }


class DeriveBlockersTests(unittest.TestCase):
    def test_all_pass_yields_no_blockers(self) -> None:
        self.assertEqual(engine_qc.derive_blockers(_qc_payload()), [])

    def test_each_failed_check_becomes_one_blocker(self) -> None:
        qc = _qc_payload(fail=["color_floor", "body_fill"])
        blockers = engine_qc.derive_blockers(qc)
        self.assertEqual({b["check"] for b in blockers}, {"color_floor", "body_fill"})

    def test_blocker_order_is_deterministic(self) -> None:
        qc = _qc_payload(fail=["body_fill", "color_floor", "corners_clean", "subject_centered"])
        names = [b["check"] for b in engine_qc.derive_blockers(qc)]
        self.assertEqual(names, sorted(names), "blocker order must be stable across runs")

    def test_handles_missing_or_malformed_qc(self) -> None:
        self.assertEqual(engine_qc.derive_blockers(None), [])
        self.assertEqual(engine_qc.derive_blockers({}), [])
        self.assertEqual(engine_qc.derive_blockers({"checks": "not-a-dict"}), [])

    def test_reasons_are_human_readable(self) -> None:
        qc = _qc_payload(fail=["color_floor"])
        reason = engine_qc.derive_blockers(qc)[0]["reason"]
        self.assertIn("2", reason)
        self.assertIn("4", reason)


class WriteBlockersJsonTests(unittest.TestCase):
    def test_passing_qc_writes_no_file(self) -> None:
        with TemporaryDirectory() as td:
            png = Path(td) / "tiger.png"
            png.write_bytes(b"fake-png-bytes")
            qc_path = png.with_suffix(".qc.json")
            qc_path.write_text(json.dumps(_qc_payload()))
            blockers_path, blockers = engine_qc.write_blockers_json(png)
            self.assertIsNone(blockers_path)
            self.assertEqual(blockers, [])
            self.assertFalse((png.parent / "tiger.png.blockers.json").exists())

    def test_failing_qc_writes_sibling(self) -> None:
        with TemporaryDirectory() as td:
            png = Path(td) / "tiger.png"
            png.write_bytes(b"fake")
            qc_path = png.with_suffix(".qc.json")
            qc_path.write_text(json.dumps(_qc_payload(fail=["body_fill"])))
            blockers_path, blockers = engine_qc.write_blockers_json(png)
            self.assertIsNotNone(blockers_path)
            self.assertTrue(blockers_path.exists())
            self.assertEqual(len(blockers), 1)
            payload = json.loads(blockers_path.read_text())
            self.assertEqual(payload["schema"], "forge.engine_qc.blockers.v1")
            self.assertEqual(payload["blocker_count"], 1)

    def test_repassing_clears_stale_blockers_file(self) -> None:
        """When a re-rendered PNG now passes, the stale blockers.json must go."""
        with TemporaryDirectory() as td:
            png = Path(td) / "tiger.png"
            png.write_bytes(b"fake")
            qc_path = png.with_suffix(".qc.json")
            # First pass: failing → blockers.json exists
            qc_path.write_text(json.dumps(_qc_payload(fail=["corners_clean"])))
            engine_qc.write_blockers_json(png)
            blockers_file = png.with_suffix(png.suffix + engine_qc.BLOCKERS_SUFFIX)
            self.assertTrue(blockers_file.exists())
            # Second pass: passing → blockers.json must be deleted
            qc_path.write_text(json.dumps(_qc_payload()))
            engine_qc.write_blockers_json(png)
            self.assertFalse(blockers_file.exists())

    def test_no_qc_sidecar_means_no_blockers(self) -> None:
        with TemporaryDirectory() as td:
            png = Path(td) / "tiger.png"
            png.write_bytes(b"fake")
            blockers_path, blockers = engine_qc.write_blockers_json(png)
            self.assertIsNone(blockers_path)
            self.assertEqual(blockers, [])


class PublishabilityTests(unittest.TestCase):
    def test_no_blockers_is_publishable(self) -> None:
        self.assertTrue(engine_qc.is_publishable([]))
        self.assertTrue(engine_qc.is_publishable([], allow_warnings=True))

    def test_blockers_block_unless_warnings_allowed(self) -> None:
        blockers = engine_qc.derive_blockers(_qc_payload(fail=["body_fill"]))
        self.assertFalse(engine_qc.is_publishable(blockers))
        self.assertTrue(engine_qc.is_publishable(blockers, allow_warnings=True))

    def test_summary_lists_failed_checks(self) -> None:
        blockers = engine_qc.derive_blockers(_qc_payload(fail=["color_floor", "corners_clean"]))
        summary = engine_qc.summarize(blockers)
        self.assertIn("color_floor", summary)
        self.assertIn("corners_clean", summary)
        self.assertIn("2 blocker", summary)


class TranslationBlockersTests(unittest.TestCase):
    """B6 — translation_report_to_qc + write_translation_blockers."""

    def test_empty_report_passes_all_checks(self) -> None:
        from engine_qc import translation_report_to_qc
        qc = translation_report_to_qc(None)
        self.assertTrue(qc["auto_qc_pass"])
        self.assertEqual(qc["pass_count"], 3)
        self.assertEqual(qc["auto_check_count"], 3)
        self.assertEqual(qc["schema"], "forge.translation_qc.v1")
        for check in qc["checks"].values():
            self.assertTrue(check["pass"])

    def test_glossary_violation_fails_glossary_check(self) -> None:
        from engine_qc import translation_report_to_qc, derive_blockers
        report = {
            "glossary_violations": [{"line_index": 0, "expected_term": "बाघ", "missing_in": "see the tiger"}],
            "leakage_flags": [],
            "repeated_lines": False,
        }
        qc = translation_report_to_qc(report)
        self.assertFalse(qc["auto_qc_pass"])
        self.assertFalse(qc["checks"]["glossary_enforced"]["pass"])
        # And it bubbles up through the standard derive_blockers
        blockers = derive_blockers(qc)
        self.assertEqual({b["check"] for b in blockers}, {"glossary_enforced"})

    def test_leakage_flag_fails_leakage_check(self) -> None:
        from engine_qc import translation_report_to_qc, derive_blockers
        report = {"glossary_violations": [], "leakage_flags": [{"line_index": 2, "ascii_word_fraction": 0.8, "text": "hello world"}], "repeated_lines": False}
        qc = translation_report_to_qc(report)
        self.assertFalse(qc["checks"]["no_english_leakage"]["pass"])
        self.assertEqual({b["check"] for b in derive_blockers(qc)}, {"no_english_leakage"})

    def test_repeated_lines_fails_repeated_check(self) -> None:
        from engine_qc import translation_report_to_qc, derive_blockers
        report = {"glossary_violations": [], "leakage_flags": [], "repeated_lines": True, "repeated_line_value": "मुझे माफ़ करें।"}
        qc = translation_report_to_qc(report)
        self.assertFalse(qc["checks"]["no_repeated_lines"]["pass"])
        self.assertEqual({b["check"] for b in derive_blockers(qc)}, {"no_repeated_lines"})

    def test_write_translation_blockers_writes_both_sidecars_on_failure(self) -> None:
        from engine_qc import write_translation_blockers
        with TemporaryDirectory() as td:
            out_path = Path(td) / "translation.txt"
            out_path.write_text("see the tiger", encoding="utf-8")
            report = {
                "glossary_violations": [{"line_index": 0, "expected_term": "बाघ", "missing_in": "see the tiger"}],
                "leakage_flags": [], "repeated_lines": False,
            }
            blockers_path, blockers, publishable = write_translation_blockers(out_path, report)
            self.assertFalse(publishable)
            self.assertEqual(len(blockers), 1)
            self.assertTrue((out_path.with_suffix(".qc.json")).exists())
            self.assertIsNotNone(blockers_path)
            self.assertTrue(blockers_path.exists())

    def test_write_translation_blockers_writes_only_qc_on_success(self) -> None:
        from engine_qc import write_translation_blockers
        with TemporaryDirectory() as td:
            out_path = Path(td) / "translation.txt"
            out_path.write_text("see the tiger", encoding="utf-8")
            blockers_path, blockers, publishable = write_translation_blockers(out_path, None)
            self.assertTrue(publishable)
            self.assertEqual(blockers, [])
            self.assertIsNone(blockers_path)
            self.assertTrue((out_path.with_suffix(".qc.json")).exists())


if __name__ == "__main__":
    unittest.main()
