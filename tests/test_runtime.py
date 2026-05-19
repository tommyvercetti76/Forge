from __future__ import annotations

import json
import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import forge_runtime
from forge_runtime import JobStore, ResourceLock, estimate_token_count, ffmpeg_filter_escape, parse_language_codes, validate_png
from mandala_engine import ChildrensBookConfig, FolkArtConfig, MandalaConfig, build_mandala, write_childrens_book, write_folk_art_page, write_mandala
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

    def test_resource_lock_falls_back_when_lock_file_open_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_home = forge_runtime.FORGE_STATE_HOME
            old_claim = forge_runtime.ResourceLock._claim_slot
            blocked_dir = Path(td) / "locks"
            forge_runtime.FORGE_STATE_HOME = Path(td)

            def flaky_claim(self, lock_dir: Path, slot: int, *, blocking: bool):
                if lock_dir == blocked_dir:
                    raise PermissionError("blocked lock file")
                return old_claim(self, lock_dir, slot, blocking=blocking)

            forge_runtime.ResourceLock._claim_slot = flaky_claim
            try:
                with ResourceLock("unit-fallback") as lock:
                    self.assertIn(str(Path(tempfile.gettempdir()) / "forge" / "locks"), str(lock.path))
            finally:
                forge_runtime.ResourceLock._claim_slot = old_claim
                forge_runtime.FORGE_STATE_HOME = old_home

    def test_resource_lock_honors_metal_slots_env(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_home = forge_runtime.FORGE_STATE_HOME
            old_slots = os.environ.get("FORGE_METAL_SLOTS")
            old_slot_ram = os.environ.get("FORGE_METAL_SLOT_RAM_GB")
            old_hard_cap = os.environ.get("FORGE_METAL_MAX_SLOTS")
            old_total = forge_runtime._memory_total_gb
            forge_runtime.FORGE_STATE_HOME = Path(td)
            forge_runtime._memory_total_gb = lambda: 128.0
            os.environ["FORGE_METAL_SLOTS"] = "2"
            os.environ["FORGE_METAL_SLOT_RAM_GB"] = "32"
            os.environ.pop("FORGE_METAL_MAX_SLOTS", None)
            try:
                with ResourceLock("metal-heavy") as lock:
                    self.assertEqual(lock.slots, 2)
                    self.assertIn(lock.slot, {1, 2})
                    self.assertIn("metal-heavy.", lock.path.name)
            finally:
                forge_runtime.FORGE_STATE_HOME = old_home
                forge_runtime._memory_total_gb = old_total
                if old_slots is None:
                    os.environ.pop("FORGE_METAL_SLOTS", None)
                else:
                    os.environ["FORGE_METAL_SLOTS"] = old_slots
                if old_slot_ram is None:
                    os.environ.pop("FORGE_METAL_SLOT_RAM_GB", None)
                else:
                    os.environ["FORGE_METAL_SLOT_RAM_GB"] = old_slot_ram
                if old_hard_cap is None:
                    os.environ.pop("FORGE_METAL_MAX_SLOTS", None)
                else:
                    os.environ["FORGE_METAL_MAX_SLOTS"] = old_hard_cap

    def test_resource_slots_cap_metal_by_memory(self) -> None:
        old_slots = os.environ.get("FORGE_METAL_SLOTS")
        old_slot_ram = os.environ.get("FORGE_METAL_SLOT_RAM_GB")
        old_hard_cap = os.environ.get("FORGE_METAL_MAX_SLOTS")
        old_total = forge_runtime._memory_total_gb
        os.environ["FORGE_METAL_SLOTS"] = "16"
        os.environ["FORGE_METAL_SLOT_RAM_GB"] = "32"
        os.environ.pop("FORGE_METAL_MAX_SLOTS", None)
        forge_runtime._memory_total_gb = lambda: 128.0
        try:
            self.assertEqual(forge_runtime._resource_slot_count("metal-heavy"), 4)
        finally:
            forge_runtime._memory_total_gb = old_total
            if old_slots is None:
                os.environ.pop("FORGE_METAL_SLOTS", None)
            else:
                os.environ["FORGE_METAL_SLOTS"] = old_slots
            if old_slot_ram is None:
                os.environ.pop("FORGE_METAL_SLOT_RAM_GB", None)
            else:
                os.environ["FORGE_METAL_SLOT_RAM_GB"] = old_slot_ram
            if old_hard_cap is None:
                os.environ.pop("FORGE_METAL_MAX_SLOTS", None)
            else:
                os.environ["FORGE_METAL_MAX_SLOTS"] = old_hard_cap

    def test_write_json_refuses_silent_temp_redirect_by_default(self) -> None:
        old_writer = forge_runtime._write_atomic_text
        old_fallback = os.environ.get("FORGE_ALLOW_TEMP_ARTIFACT_FALLBACK")

        def blocked_writer(path: Path, text: str) -> None:
            raise PermissionError("blocked")

        forge_runtime._write_atomic_text = blocked_writer
        os.environ.pop("FORGE_ALLOW_TEMP_ARTIFACT_FALLBACK", None)
        try:
            with self.assertRaisesRegex(PermissionError, "refusing to redirect"):
                forge_runtime.write_json(Path("/blocked/receipt.json"), {"ok": True})
        finally:
            forge_runtime._write_atomic_text = old_writer
            if old_fallback is None:
                os.environ.pop("FORGE_ALLOW_TEMP_ARTIFACT_FALLBACK", None)
            else:
                os.environ["FORGE_ALLOW_TEMP_ARTIFACT_FALLBACK"] = old_fallback

    def test_write_json_explicit_temp_fallback_returns_actual_path(self) -> None:
        target = Path("/blocked/receipt.json")
        old_writer = forge_runtime._write_atomic_text
        old_fallback = os.environ.get("FORGE_ALLOW_TEMP_ARTIFACT_FALLBACK")
        written: dict[str, Any] = {}

        def fallback_writer(path: Path, text: str) -> None:
            if path == target:
                raise PermissionError("blocked")
            written["path"] = path
            written["text"] = text

        forge_runtime._write_atomic_text = fallback_writer
        os.environ["FORGE_ALLOW_TEMP_ARTIFACT_FALLBACK"] = "1"
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                actual = forge_runtime.write_json(target, {"ok": True})
            self.assertEqual(actual, Path(tempfile.gettempdir()) / "forge" / "receipt.json")
            self.assertEqual(written["path"], actual)
            self.assertIn('"ok": true', written["text"])
        finally:
            forge_runtime._write_atomic_text = old_writer
            if old_fallback is None:
                os.environ.pop("FORGE_ALLOW_TEMP_ARTIFACT_FALLBACK", None)
            else:
                os.environ["FORGE_ALLOW_TEMP_ARTIFACT_FALLBACK"] = old_fallback

    def test_metal_report_can_require_actual_mflux_probe(self) -> None:
        old_system_cache = forge_runtime._METAL_REPORT_CACHE
        old_probe_cache = forge_runtime._MFLUX_METAL_PROBE_CACHE
        old_probe = forge_runtime._mflux_metal_probe
        forge_runtime._METAL_REPORT_CACHE = {"ok": True, "chip": "Apple Test", "metal": "Supported", "reason": None}
        forge_runtime._MFLUX_METAL_PROBE_CACHE = None
        forge_runtime._mflux_metal_probe = lambda: {"ok": False, "path": "mflux-generate", "reason": "no actual Metal device"}
        try:
            report = forge_runtime.metal_acceleration_report(require_mflux=True)
            self.assertFalse(report["ok"])
            self.assertEqual(report["reason"], "no actual Metal device")
            with self.assertRaisesRegex(RuntimeError, "requires Apple Metal acceleration"):
                forge_runtime.require_metal_acceleration("unit render")
        finally:
            forge_runtime._METAL_REPORT_CACHE = old_system_cache
            forge_runtime._MFLUX_METAL_PROBE_CACHE = old_probe_cache
            forge_runtime._mflux_metal_probe = old_probe

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
            svg = Path(artifact["svg"]).read_text(encoding="utf-8")
            self.assertIn('transform="rotate(', svg)
            self.assertFalse(qc["symmetry_contract"]["recomputed_independent_copies"])

    def test_mandala_styles_use_distinct_geometry_grammars(self) -> None:
        grammars = set()
        signatures = set()
        for style in ("coloring", "floral", "geometric", "luxury", "playful", "sacred"):
            canvas, qc = build_mandala(
                MandalaConfig(style=style, width=512, height=512, rings=4, symmetry=12, seed=7, supersample=1),
            )
            grammars.add(tuple(qc["style_grammar"]["motif_families"]))
            signatures.add(
                tuple((shape["type"], len(shape.get("points", []))) for shape in canvas.shapes[:24])
            )
        self.assertEqual(len(grammars), 6)
        self.assertGreaterEqual(len(signatures), 5)

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

    def test_folk_art_engine_writes_devotional_coloring_page(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            artifact = write_folk_art_page(
                FolkArtConfig(width=900, height=900, stroke_width=1.5, supersample=1),
                Path(td) / "folk.png",
            )
            validate_png(Path(artifact["png"]), width=900, height=900, min_bytes=1024)
            self.assertTrue(Path(artifact["svg"]).exists())
            qc = json.loads(Path(artifact["qc"]).read_text(encoding="utf-8"))
            self.assertEqual(qc["engine"], "forge.procedural-folk-art.v1")
            self.assertIn("paired peacocks", qc["style_grammar"]["motif_families"])


if __name__ == "__main__":
    unittest.main()
