from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import forge_madhubani


class MadhubaniWorkflowTests(unittest.TestCase):
    def test_freeform_seed_is_stable(self) -> None:
        first = forge_madhubani._synthesize_transient_animal("whale-shark", {}, "whale shark")
        second = forge_madhubani._synthesize_transient_animal("whale-shark", {}, "whale shark")
        self.assertEqual(first["seed_block_start"], second["seed_block_start"])

    def test_render_set_dry_run_writes_manifest_and_workflow_event(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            old_gen = forge_madhubani.GEN_DIR
            old_attempts = forge_madhubani.ATTEMPTS_DIR
            forge_madhubani.GEN_DIR = Path(td) / "madhubani_animals"
            forge_madhubani.ATTEMPTS_DIR = forge_madhubani.GEN_DIR / "attempts"
            try:
                rc = forge_madhubani.render_set(
                    "tiger",
                    "madhubani-master-painter",
                    only_pose="standing-alert",
                    dry_run=True,
                    jobs=2,
                )
                self.assertEqual(rc, 0)
                manifest_path = forge_madhubani.ATTEMPTS_DIR / "tiger" / "v1" / "render-manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self.assertEqual(manifest["status"], "DRY_RUN")
                self.assertEqual(manifest["pose_count"], 1)
                self.assertEqual(manifest["jobs"], 1)
                self.assertEqual(manifest["auto_qc_contract"], "4/7 rubric checks machine-scored; promotion blocks failed auto-QC unless --force")
                event_log = forge_madhubani.GEN_DIR / "workflow-events.jsonl"
                self.assertIn('"action": "render_set"', event_log.read_text(encoding="utf-8"))
            finally:
                forge_madhubani.GEN_DIR = old_gen
                forge_madhubani.ATTEMPTS_DIR = old_attempts


if __name__ == "__main__":
    unittest.main()
