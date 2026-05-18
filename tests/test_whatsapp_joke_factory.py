#!/usr/bin/env python3
"""Quick sanity tests for WhatsApp joke factory."""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BIN_DIR = ROOT / "bin"

def test_jokes_parser():
    """Test that jokes subcommands are registered."""
    result = subprocess.run(
        [sys.executable, str(BIN_DIR / "forge.py"), "jokes", "--help"],
        capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "generate" in result.stdout
    assert "qa" in result.stdout
    assert "render" in result.stdout
    print("✓ jokes parser registered")

def test_jokes_dry_run():
    """Test dry-run generation (text only, no cards/audio/video)."""
    with tempfile.TemporaryDirectory() as td:
        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "forge.py"), "jokes", "generate",
             "--dry-run", "--count", "1", "--langs", "hi,mr", "--out", td],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            print(result.stderr)
        assert result.returncode == 0, f"dry-run failed: {result.stderr}"
        
        out_dir = Path(td)
        assert (out_dir / "manifest.json").exists()
        assert (out_dir / "qc-report.json").exists()
        assert (out_dir / "review.md").exists()
        
        manifest = json.loads((out_dir / "manifest.json").read_text())
        assert manifest["schema_version"] == "whatsapp_joke_pack.v1"
        assert manifest["languages"] == ["hi", "mr"]
        assert len(manifest["jokes"]) > 0
        
        print(f"✓ dry-run generated {len(manifest['jokes'])} jokes with manifest")

def test_jokes_with_cards():
    """Test generation with cards."""
    with tempfile.TemporaryDirectory() as td:
        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "forge.py"), "jokes", "generate",
             "--count", "1", "--cards", "1", "--audio", "0", "--video", "0",
             "--langs", "hi", "--out", td],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            print(result.stderr)
        assert result.returncode == 0
        
        out_dir = Path(td)
        cards = list(out_dir.glob("cards/**/*.png"))
        assert len(cards) > 0, f"no cards found in {out_dir / 'cards'}"
        
        # Verify PNG validity
        for card in cards:
            assert card.stat().st_size > 1000, f"card too small: {card}"
        
        print(f"✓ card generation produced {len(cards)} images")

def test_manifest_schema():
    """Test that manifest has required schema fields."""
    with tempfile.TemporaryDirectory() as td:
        result = subprocess.run(
            [sys.executable, str(BIN_DIR / "forge.py"), "jokes", "generate",
             "--dry-run", "--count", "1", "--langs", "hi,mr", "--out", td],
            capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0
        
        manifest = json.loads((Path(td) / "manifest.json").read_text())
        required_keys = ["schema_version", "created_at", "languages", "counts", "jokes"]
        for key in required_keys:
            assert key in manifest, f"missing {key} in manifest"
        
        if manifest["jokes"]:
            joke = manifest["jokes"][0]
            required_joke_keys = ["id", "topic", "status", "texts", "safety"]
            for key in required_joke_keys:
                assert key in joke, f"missing {key} in joke"
        
        print("✓ manifest schema valid")

if __name__ == "__main__":
    try:
        test_jokes_parser()
        test_jokes_dry_run()
        test_jokes_with_cards()
        test_manifest_schema()
        print("\n✓ all sanity tests passed")
    except Exception as e:
        print(f"\n✗ test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
