#!/usr/bin/env python3
"""Quick sanity tests for WhatsApp joke factory."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = ROOT / "bin"


class WhatsAppJokeFactoryTests(unittest.TestCase):
    def test_jokes_parser(self) -> None:
        """Test that jokes subcommands are registered."""
        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "forge.py"), "jokes", "--help"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("generate", result.stdout)
        self.assertIn("qa", result.stdout)
        self.assertIn("render", result.stdout)

    def test_jokes_dry_run(self) -> None:
        """Test dry-run generation (text only, no cards/audio/video)."""
        with tempfile.TemporaryDirectory() as td:
            result = subprocess.run(
                [
                    sys.executable,
                    str(BIN_DIR / "forge.py"),
                    "jokes",
                    "generate",
                    "--dry-run",
                    "--count",
                    "1",
                    "--langs",
                    "hi,mr",
                    "--out",
                    td,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, f"dry-run failed: {result.stderr}")

            out_dir = Path(td)
            self.assertTrue((out_dir / "manifest.json").exists())
            self.assertTrue((out_dir / "qc-report.json").exists())
            self.assertTrue((out_dir / "review.md").exists())

            manifest = json.loads((out_dir / "manifest.json").read_text())
            self.assertEqual(manifest["schema_version"], "whatsapp_joke_pack.v1")
            self.assertEqual(manifest["languages"], ["hi", "mr"])
            self.assertGreater(len(manifest["jokes"]), 0)

    def test_jokes_with_cards(self) -> None:
        """Test generation with cards."""
        with tempfile.TemporaryDirectory() as td:
            result = subprocess.run(
                [
                    sys.executable,
                    str(BIN_DIR / "forge.py"),
                    "jokes",
                    "generate",
                    "--count",
                    "1",
                    "--cards",
                    "1",
                    "--audio",
                    "0",
                    "--video",
                    "0",
                    "--langs",
                    "hi",
                    "--out",
                    td,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            out_dir = Path(td)
            cards = list(out_dir.glob("cards/**/*.png"))
            self.assertGreater(len(cards), 0, f"no cards found in {out_dir / 'cards'}")

            for card in cards:
                self.assertGreater(card.stat().st_size, 1000, f"card too small: {card}")

    def test_manifest_schema(self) -> None:
        """Test that manifest has required schema fields."""
        with tempfile.TemporaryDirectory() as td:
            result = subprocess.run(
                [
                    sys.executable,
                    str(BIN_DIR / "forge.py"),
                    "jokes",
                    "generate",
                    "--dry-run",
                    "--count",
                    "1",
                    "--langs",
                    "hi,mr",
                    "--out",
                    td,
                ],
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

            manifest = json.loads((Path(td) / "manifest.json").read_text())
            required_keys = ["schema_version", "created_at", "languages", "counts", "jokes"]
            for key in required_keys:
                self.assertIn(key, manifest, f"missing {key} in manifest")

            if manifest["jokes"]:
                joke = manifest["jokes"][0]
                required_joke_keys = ["id", "topic", "status", "texts", "safety"]
                for key in required_joke_keys:
                    self.assertIn(key, joke, f"missing {key} in joke")


if __name__ == "__main__":
    unittest.main()
