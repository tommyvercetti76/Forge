"""Tests for translate_web's pipeline core — `run_translation` and the
sentence-timed SRT estimator. Ollama is mocked; the HTTP layer is not
exercised here (it's a thin wrapper)."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BIN = Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

import translate_web  # noqa: E402


def _fake_translate(texts, target_lang, **kwargs):
    """Echo each input with a target-language prefix so the deterministic test
    can verify pipeline plumbing without hitting Ollama."""
    out_report = kwargs.get("out_report")
    if out_report is not None:
        out_report.setdefault("glossary_violations", [])
        out_report.setdefault("leakage_flags", [])
        out_report.setdefault("repeated_lines", False)
    return [f"[{target_lang}] {t}" for t in texts]


def _failing_translate(texts, target_lang, **kwargs):
    """Simulate the trust layer flagging issues so we exercise blocker paths."""
    out_report = kwargs.get("out_report")
    if out_report is not None:
        out_report.update({
            "glossary_violations": [
                {"line_index": 0, "expected_term": "बाघ", "missing_in": texts[0]}
            ],
            "leakage_flags": [],
            "repeated_lines": False,
        })
    return [f"[{target_lang}] {t}" for t in texts]


class SrtEstimatorTests(unittest.TestCase):
    def test_emits_valid_srt_header_and_cues(self) -> None:
        srt = translate_web._estimate_srt("A short sentence. Another one.", lang="hi")
        self.assertIn("NOTE forge.translate_web.v1", srt)
        # Two cues with the SRT index format
        self.assertIn("\n1\n", "\n" + srt)
        self.assertIn("\n2\n", "\n" + srt)
        self.assertIn("-->", srt)

    def test_short_cue_has_floor_duration(self) -> None:
        srt = translate_web._estimate_srt("Hi.", lang="hi")
        # Single-word cue should still get the 1.5s floor (not 0.4s)
        self.assertIn("00:00:00,000 --> 00:00:01,500", srt)

    def test_devanagari_sentence_boundary_split(self) -> None:
        # `।` is the Hindi/Marathi sentence terminator
        srt = translate_web._estimate_srt("एक वाक्य। दूसरा वाक्य।", lang="hi")
        self.assertIn("\n2\n", "\n" + srt)


class RunTranslationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="forge-translateweb-test-")
        self.job_dir = Path(self.tmpdir) / "job-001"

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch.object(translate_web, "translate_texts_ollama", side_effect=_fake_translate)
    def test_clean_run_writes_artifacts_and_marks_publishable(self, _mock) -> None:
        manifest = translate_web.run_translation(
            source_text="Hello world. This is a test.",
            target_lang="hi",
            glossary=None,
            want_subtitles=False,
            job_dir=self.job_dir,
        )
        self.assertTrue(manifest["publishable"])
        self.assertTrue(manifest["qc_pass"])
        self.assertEqual(manifest["blockers"], [])
        self.assertIsNone(manifest["srt_path"])
        # Source + translation + QC + manifest all written
        self.assertTrue(Path(manifest["source_path"]).exists())
        self.assertTrue(Path(manifest["translation_path"]).exists())
        self.assertTrue(Path(manifest["qc_path"]).exists())
        self.assertTrue((self.job_dir / "manifest.json").exists())
        # No blockers.json since publishable
        self.assertIsNone(manifest["blockers_path"])

    @patch.object(translate_web, "translate_texts_ollama", side_effect=_fake_translate)
    def test_subtitle_flag_writes_srt(self, _mock) -> None:
        manifest = translate_web.run_translation(
            source_text="First. Second.",
            target_lang="hi",
            glossary=None,
            want_subtitles=True,
            job_dir=self.job_dir,
        )
        self.assertIsNotNone(manifest["srt_path"])
        srt = Path(manifest["srt_path"]).read_text(encoding="utf-8")
        self.assertIn("-->", srt)
        self.assertIn("NOTE forge.translate_web.v1", srt)

    @patch.object(translate_web, "translate_texts_ollama", side_effect=_failing_translate)
    def test_glossary_violation_blocks_publishability(self, _mock) -> None:
        manifest = translate_web.run_translation(
            source_text="see the tiger",
            target_lang="hi",
            glossary={"hi": {"tiger": "बाघ"}},
            want_subtitles=False,
            job_dir=self.job_dir,
        )
        self.assertFalse(manifest["publishable"])
        self.assertFalse(manifest["qc_pass"])
        self.assertIn("glossary_enforced", manifest["blockers"])
        self.assertIsNotNone(manifest["blockers_path"])
        self.assertTrue(Path(manifest["blockers_path"]).exists())
        # Inspect the blockers.json payload
        blockers_payload = json.loads(Path(manifest["blockers_path"]).read_text())
        self.assertEqual(blockers_payload["schema"], "forge.engine_qc.blockers.v1")

    @patch.object(translate_web, "translate_texts_ollama", side_effect=_fake_translate)
    def test_manifest_records_glossary_used(self, _mock) -> None:
        manifest = translate_web.run_translation(
            source_text="hello",
            target_lang="hi",
            glossary={"hi": {"hello": "नमस्ते"}},
            want_subtitles=False,
            job_dir=self.job_dir,
        )
        self.assertTrue(manifest["glossary_used"])
        manifest_no_glossary = translate_web.run_translation(
            source_text="hello",
            target_lang="hi",
            glossary=None,
            want_subtitles=False,
            job_dir=self.job_dir / "no-glossary",
        )
        self.assertFalse(manifest_no_glossary["glossary_used"])


if __name__ == "__main__":
    unittest.main()
