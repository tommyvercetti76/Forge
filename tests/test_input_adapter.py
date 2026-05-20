"""Tests for bin/input_adapter.py — the unified text-ingestion adapter.

These tests must pass WITHOUT pdfplumber, pytesseract, or mlx_whisper being
installed: optional-dep dispatches use `unittest.skipUnless` so the core
module stays unit-testable on a minimal environment.
"""

from __future__ import annotations

import hashlib
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import input_adapter
from input_adapter import read_as_text


HAS_PDFPLUMBER = importlib.util.find_spec("pdfplumber") is not None
HAS_STRIPRTF = importlib.util.find_spec("striprtf") is not None
HAS_MLX_WHISPER = shutil.which("mlx_whisper") is not None


class RawTextDispatchTests(unittest.TestCase):
    def test_raw_string_passthrough_returns_same_text_and_correct_sha256(self) -> None:
        text = "Hello, world! This is a raw string."
        result = read_as_text(text)
        self.assertEqual(result["text"], text)
        self.assertEqual(result["source_kind"], "text")
        self.assertEqual(result["length_chars"], len(text))
        self.assertEqual(result["length_words"], len(text.split()))
        expected_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        self.assertEqual(result["sha256"], expected_hash)

    def test_kind_text_override_on_path_looking_string_is_treated_as_text(self) -> None:
        # This string LOOKS like a path, but kind="text" forces passthrough.
        path_looking = "/etc/passwd"
        result = read_as_text(path_looking, kind="text")
        self.assertEqual(result["text"], path_looking)
        self.assertEqual(result["source_kind"], "text")
        # Crucially, no FileNotFoundError, no read attempt.

    def test_sha256_is_deterministic_across_two_calls(self) -> None:
        text = "The quick brown fox jumps over the lazy dog."
        r1 = read_as_text(text)
        r2 = read_as_text(text)
        self.assertEqual(r1["sha256"], r2["sha256"])
        self.assertEqual(r1["text"], r2["text"])
        self.assertEqual(r1["length_words"], r2["length_words"])


class TxtFileDispatchTests(unittest.TestCase):
    def test_txt_file_is_read_correctly(self) -> None:
        body = "Line one.\nLine two.\nLine three."
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as f:
            f.write(body)
            path = Path(f.name)
        try:
            result = read_as_text(path)
            self.assertEqual(result["source_kind"], "txt")
            self.assertEqual(result["text"], body.strip())
            self.assertEqual(result["length_words"], 6)
            self.assertEqual(result["metadata"]["path"], str(path))
        finally:
            path.unlink()

    def test_malformed_txt_not_utf8_still_reads_via_latin1_fallback(self) -> None:
        # Bytes that are valid latin-1 but invalid UTF-8 (lone 0xE9 = é in latin-1)
        garbled = b"Caf\xe9 con leche y croissant.\nSegunda l\xednea."
        with tempfile.NamedTemporaryFile("wb", suffix=".txt", delete=False) as f:
            f.write(garbled)
            path = Path(f.name)
        try:
            result = read_as_text(path)
            self.assertEqual(result["source_kind"], "txt")
            # Decoded via latin-1 — should contain "Café"
            self.assertIn("Caf", result["text"])
            self.assertIn("\xe9", result["text"])
        finally:
            path.unlink()


class ErrorPathTests(unittest.TestCase):
    def test_missing_file_raises_clear_file_not_found(self) -> None:
        missing = "/tmp/forge_input_adapter_does_not_exist_xyz123.txt"
        with self.assertRaises(FileNotFoundError) as cm:
            read_as_text(missing)
        # Error message should reference the missing file
        self.assertIn("forge_input_adapter_does_not_exist_xyz123", str(cm.exception))

    def test_missing_file_with_explicit_kind_also_raises(self) -> None:
        missing = "/tmp/forge_input_adapter_does_not_exist_xyz123.pdf"
        with self.assertRaises(FileNotFoundError):
            read_as_text(missing, kind="pdf")


@unittest.skipUnless(HAS_STRIPRTF, "striprtf not installed")
class RtfDispatchTests(unittest.TestCase):
    def test_rtf_via_inline_fixture_extracts_plain_text(self) -> None:
        # Minimal valid RTF document
        rtf_bytes = rb"{\rtf1\ansi Hello, this is RTF content. Second sentence.}"
        with tempfile.NamedTemporaryFile("wb", suffix=".rtf", delete=False) as f:
            f.write(rtf_bytes)
            path = Path(f.name)
        try:
            result = read_as_text(path)
            self.assertEqual(result["source_kind"], "rtf")
            self.assertIn("Hello", result["text"])
            self.assertIn("RTF content", result["text"])
            # No control codes should leak through
            self.assertNotIn(r"\rtf1", result["text"])
            self.assertNotIn(r"\ansi", result["text"])
            # sha256 should be over the raw RTF bytes, not the extracted text
            self.assertEqual(
                result["sha256"],
                hashlib.sha256(rtf_bytes).hexdigest(),
            )
        finally:
            path.unlink()


@unittest.skipUnless(HAS_PDFPLUMBER, "pdfplumber not installed")
class PdfDispatchTests(unittest.TestCase):
    def test_pdf_dispatch_extracts_text_when_pdfplumber_available(self) -> None:
        # Build a tiny one-page PDF using reportlab if available; otherwise
        # fall back to pdfplumber's own ability to read a hand-crafted file.
        # We use pdfplumber + pypdf-like minimal PDF generator inline.
        try:
            from reportlab.pdfgen import canvas  # type: ignore
        except ImportError:
            self.skipTest("reportlab not installed; cannot synthesize a PDF for the test")

        with tempfile.NamedTemporaryFile("wb", suffix=".pdf", delete=False) as f:
            path = Path(f.name)
        try:
            c = canvas.Canvas(str(path))
            c.drawString(100, 750, "Translation studio adapter test page.")
            c.showPage()
            c.save()
            result = read_as_text(path)
            self.assertEqual(result["source_kind"], "pdf")
            self.assertIn("Translation studio", result["text"])
            self.assertEqual(result["metadata"]["page_count"], 1)
            self.assertEqual(result["metadata"]["extractor"], "pdfplumber")
        finally:
            path.unlink()


# Search for any .wav fixture in the repo to run the audio dispatch test
def _find_audio_fixture() -> Path | None:
    candidates = [
        ROOT / "tests" / "fixtures",
        ROOT / "fixtures",
        ROOT / "tests",
    ]
    for root in candidates:
        if not root.exists():
            continue
        for suffix in (".wav", ".mp3", ".m4a", ".flac"):
            for p in root.rglob(f"*{suffix}"):
                if p.is_file() and p.stat().st_size > 0:
                    return p
    return None


AUDIO_FIXTURE = _find_audio_fixture()


@unittest.skipUnless(HAS_MLX_WHISPER and AUDIO_FIXTURE is not None,
                     "mlx_whisper or audio fixture not available")
class AudioDispatchTests(unittest.TestCase):
    def test_audio_dispatch_transcribes_with_mlx_whisper(self) -> None:
        assert AUDIO_FIXTURE is not None
        result = read_as_text(AUDIO_FIXTURE)
        self.assertEqual(result["source_kind"], "audio")
        self.assertIsInstance(result["text"], str)
        self.assertIn("language", result["metadata"])


if __name__ == "__main__":
    unittest.main()
