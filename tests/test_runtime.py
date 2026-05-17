from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import forge_runtime
from forge_runtime import JobStore, ResourceLock, estimate_token_count, ffmpeg_filter_escape, parse_language_codes, validate_png
from mandala_engine import ChildrensBookConfig, MandalaConfig, write_childrens_book, write_mandala
import importlib.util

process_video_spec = importlib.util.spec_from_file_location("process_video", ROOT / "bin" / "process-video.py")
process_video = importlib.util.module_from_spec(process_video_spec)
assert process_video_spec and process_video_spec.loader
sys.modules["process_video"] = process_video
process_video_spec.loader.exec_module(process_video)


class RuntimeTests(unittest.TestCase):
    def test_png_validator_checks_dimensions(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "image.png"
            Image.new("RGB", (64, 32), (1, 2, 3)).save(path)
            info = validate_png(path, width=64, height=32, min_bytes=1)
            self.assertEqual(info["width"], 64)
            self.assertEqual(info["height"], 32)

    def test_job_store_records_recent_job(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            store = JobStore(Path(td) / "jobs.sqlite")
            job_id = store.create_job("test", "input.mov", "out", profile="cool")
            store.finish_job(job_id, "done")
            recent = store.recent_jobs(1)
            self.assertEqual(recent[0]["id"], job_id)
            self.assertEqual(recent[0]["status"], "done")

    def test_resource_lock_writes_state(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_home = forge_runtime.FORGE_STATE_HOME
            forge_runtime.FORGE_STATE_HOME = Path(td)
            try:
                with ResourceLock("unit-test") as lock:
                    self.assertGreaterEqual(lock.wait_seconds, 0)
            finally:
                forge_runtime.FORGE_STATE_HOME = old_home

    def test_ffmpeg_filter_escape(self) -> None:
        escaped = ffmpeg_filter_escape("/tmp/it won't:break.srt")
        self.assertIn("\\'", escaped)
        self.assertIn("\\:", escaped)

    def test_transcript_digest_keeps_middle_and_end(self) -> None:
        text = " ".join(f"token{i}" for i in range(2000))
        digest = process_video.transcript_digest(text, max_chars=600)
        self.assertIn("BEGINNING:", digest)
        self.assertIn("MIDDLE:", digest)
        self.assertIn("ENDING:", digest)

    def test_language_parser_accepts_names_and_codes(self) -> None:
        self.assertEqual(parse_language_codes("en, marathi hi"), ["en", "mr", "hi"])
        self.assertEqual(parse_language_codes("none"), [])

    def test_token_estimator_is_conservative_and_stable(self) -> None:
        self.assertEqual(estimate_token_count(""), 0)
        self.assertEqual(estimate_token_count("abcd"), 1)
        self.assertEqual(estimate_token_count("abcde"), 2)

    def test_translation_parser_accepts_sarvam_numbered_text(self) -> None:
        raw = "यहाँ अनुवाद है:\n\nआइटम:\n0: नमस्ते दुनिया\n1: स्वागत है"
        self.assertEqual(forge_runtime._parse_translation_response(raw, expected=2), ["नमस्ते दुनिया", "स्वागत है"])
        self.assertTrue(forge_runtime._looks_like_translation_placeholder("<अनुवाद>"))

    def test_caption_triplet_preserves_timing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            transcript_dir = Path(td)
            files = process_video._write_caption_triplet(
                transcript_dir,
                "clip",
                "mr",
                [{"start": 1.25, "end": 2.5, "text": "नमस्कार"}],
            )
            srt = Path(files["srt"]).read_text(encoding="utf-8")
            vtt = Path(files["vtt"]).read_text(encoding="utf-8")
            self.assertIn("00:00:01,250 --> 00:00:02,500", srt)
            self.assertIn("WEBVTT", vtt)
            self.assertIn("00:00:01.250 --> 00:00:02.500", vtt)

    def test_mandala_engine_writes_png_svg_and_qc(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "mandala.png"
            artifact = write_mandala(
                MandalaConfig(width=512, height=512, rings=4, symmetry=12, seed=7, supersample=1),
                out,
            )
            validate_png(Path(artifact["png"]), width=512, height=512, min_bytes=1024)
            self.assertTrue(Path(artifact["svg"]).exists())
            qc = json.loads(Path(artifact["qc"]).read_text(encoding="utf-8"))
            self.assertTrue(qc["construction_pass"])
            self.assertEqual(qc["symmetry_order"], 12)
            self.assertGreater(qc["shape_count"], 50)

    def test_childrens_book_engine_writes_pages(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            manifest = write_childrens_book(
                ChildrensBookConfig(width=512, height=512, pages=3, rings=3, symmetry=8, seed=5, supersample=1),
                Path(td),
            )
            self.assertEqual(len(manifest["pages"]), 3)
            themes = {page["theme"] for page in manifest["pages"]}
            self.assertEqual(themes, {"rabbits-garden", "crows-texas", "blue-jay"})
            for page in manifest["pages"]:
                validate_png(Path(page["png"]), width=512, height=512, min_bytes=1024)
                self.assertTrue(Path(page["svg"]).exists())
                self.assertTrue(Path(page["qc"]).exists())


if __name__ == "__main__":
    unittest.main()
