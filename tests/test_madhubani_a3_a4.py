"""A3 + A4 contract tests for the Madhubani driver.

A3 — `compute_seed(..., series_lock=True)` drops the per-pose offset so all
4 poses of one animal share the same noise vector. The retry-offset still
fires under series-lock.

A4 — `promote_pose` workflow event payload carries `overridden_blockers`
and `overridden_blockers_detail` when `--force` is used to bypass a failed
auto-QC. Empty list when promotion was clean.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BIN = Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

import forge_madhubani  # noqa: E402


def _poses_fixture():
    return {
        "seed_allocation": {
            "ordinal_offset_in_block": {
                "standing-alert": 0,
                "seated-rest": 5,
                "signature-action": 10,
                "frontal-portrait": 15,
                "retry-offset": 50,
            }
        }
    }


def _pose(slug: str, ordinal: int):
    return {"slug": slug, "ordinal": ordinal}


def _animal():
    return {"slug": "tiger", "seed_block_start": 8200, "body_type": "lean-predator"}


class A3SeriesSeedTests(unittest.TestCase):
    @patch.object(forge_madhubani, "load_poses", side_effect=lambda: _poses_fixture())
    def test_default_uses_per_pose_offset(self, _mock_load):
        seed_a = forge_madhubani.compute_seed(_animal(), _pose("standing-alert", 1), retry=False)
        seed_b = forge_madhubani.compute_seed(_animal(), _pose("seated-rest", 2), retry=False)
        seed_c = forge_madhubani.compute_seed(_animal(), _pose("signature-action", 3), retry=False)
        seed_d = forge_madhubani.compute_seed(_animal(), _pose("frontal-portrait", 4), retry=False)
        # Standard mode — every pose has a distinct seed
        self.assertEqual({seed_a, seed_b, seed_c, seed_d}, {8200, 8205, 8210, 8215})

    @patch.object(forge_madhubani, "load_poses", side_effect=lambda: _poses_fixture())
    def test_series_lock_collapses_to_one_seed(self, _mock_load):
        seeds = {
            forge_madhubani.compute_seed(_animal(), _pose(p, i), retry=False, series_lock=True)
            for i, p in enumerate(["standing-alert", "seated-rest", "signature-action", "frontal-portrait"], 1)
        }
        # Visual-bible mode — all four poses share the animal's base seed
        self.assertEqual(seeds, {8200})

    @patch.object(forge_madhubani, "load_poses", side_effect=lambda: _poses_fixture())
    def test_retry_offset_fires_under_series_lock(self, _mock_load):
        normal = forge_madhubani.compute_seed(_animal(), _pose("standing-alert", 1), retry=False, series_lock=True)
        retry = forge_madhubani.compute_seed(_animal(), _pose("standing-alert", 1), retry=True, series_lock=True)
        # Retry must produce a distinct seed even under series-lock so v2/ never
        # collides with v1/'s output for the same animal+pose.
        self.assertEqual(normal, 8200)
        self.assertEqual(retry, 8250)


class A4WorkflowEventTests(unittest.TestCase):
    """Tests that promote_pose's workflow event records overridden blockers."""

    def setUp(self) -> None:
        self.tmpdir = tempfile.mkdtemp(prefix="forge-a4-test-")
        self.gen_dir = Path(self.tmpdir) / "generated" / "madhubani_animals"
        self.gen_dir.mkdir(parents=True)
        self._gen_patch = patch.object(forge_madhubani, "GEN_DIR", self.gen_dir)
        self._gen_patch.start()

    def tearDown(self) -> None:
        self._gen_patch.stop()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _read_events(self) -> list[dict]:
        path = self.gen_dir / "workflow-events.jsonl"
        if not path.exists():
            return []
        with path.open() as fh:
            return [json.loads(line) for line in fh if line.strip()]

    def test_clean_promote_records_empty_overridden_blockers(self):
        """Simulate a clean promote (qc passed). Override list must be empty."""
        forge_madhubani._append_workflow_event("promote_pose", {
            "animal_slug": "tiger", "pose": "standing-alert",
            "from_version": "v1", "destination": "/mock",
            "auto_qc_score": 100.0, "auto_qc_pass": True,
            "force": False,
            "overridden_blockers": [],
            "overridden_blockers_detail": [],
        })
        events = self._read_events()
        self.assertEqual(len(events), 1)
        payload = events[0]["payload"]
        self.assertEqual(payload["overridden_blockers"], [])
        self.assertEqual(payload["overridden_blockers_detail"], [])

    def test_force_promote_records_blocker_names_and_detail(self):
        """When --force is used on a failed QC, the event captures which checks."""
        forge_madhubani._append_workflow_event("promote_pose", {
            "animal_slug": "tiger", "pose": "seated-rest",
            "from_version": "v1", "destination": "/mock",
            "auto_qc_score": 50.0, "auto_qc_pass": False,
            "force": True,
            "overridden_blockers": ["body_fill", "corners_clean"],
            "overridden_blockers_detail": [
                {"check": "body_fill", "reason": "low fill", "detail": {"pass": False}},
                {"check": "corners_clean", "reason": "75%", "detail": {"pass": False}},
            ],
        })
        events = self._read_events()
        self.assertEqual(len(events), 1)
        payload = events[0]["payload"]
        self.assertEqual(set(payload["overridden_blockers"]), {"body_fill", "corners_clean"})
        self.assertEqual(len(payload["overridden_blockers_detail"]), 2)
        for blocker in payload["overridden_blockers_detail"]:
            self.assertIn("check", blocker)
            self.assertIn("reason", blocker)


if __name__ == "__main__":
    unittest.main()
