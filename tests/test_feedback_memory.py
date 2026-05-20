"""Tests for Phase D.1 + D.2 — feedback memory.

Covers RunAttempt construction (hash + timestamp defaults), RunsWriter
append behavior, RunsReader iteration + group-by, the `from_reasoning_result`
adapter that converts a C.2 engine output into ledger rows, and the D.2
mining job that produces species_winning_prompts.md.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from feedback_memory import (  # noqa: E402
    RunAttempt,
    RunsReader,
    RunsWriter,
    SCHEMA,
    mine_winning_prompts,
)


def _mk_attempt(**overrides) -> RunAttempt:
    """Default RunAttempt — overrideable per test."""
    base = dict(
        animal_slug="rhino",
        pose_slug="standing-alert",
        attempt=1,
        seed=8201,
        prompt="single centered Madhubani folk-art rhino ...",
        composite=0.82,
        rubric_pass_fraction=1.0,
        clip_likeness_probability=0.55,
        auto_qc_pass=True,
        active_check_count=7,
        pass_count=7,
        failed_checks=[],
        weakest_dimension=None,
        boost_applied=None,
        accepted=True,
        render_path="generated/test/rhino.png",
        model="z-image-turbo",
    )
    base.update(overrides)
    return RunAttempt(**base)


class RunAttemptTests(unittest.TestCase):
    def test_defaults_timestamp_and_hash(self) -> None:
        r = _mk_attempt()
        self.assertTrue(r.ts.endswith("Z"))
        self.assertTrue(r.prompt_hash.startswith("sha256:"))
        self.assertEqual(len(r.prompt_hash), len("sha256:") + 64)
        self.assertEqual(r.schema, SCHEMA)

    def test_prompt_hash_is_content_stable(self) -> None:
        a = _mk_attempt(prompt="foo")
        b = _mk_attempt(prompt="foo", seed=999)  # different seed, same prompt
        self.assertEqual(a.prompt_hash, b.prompt_hash)
        c = _mk_attempt(prompt="foo bar")
        self.assertNotEqual(a.prompt_hash, c.prompt_hash)


class RunsWriterTests(unittest.TestCase):
    def test_record_attempt_appends_jsonl_line(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "runs.jsonl"
            w = RunsWriter(path)
            w.record_attempt(_mk_attempt())
            w.record_attempt(_mk_attempt(attempt=2, composite=0.85))
            lines = path.read_text().splitlines()
            self.assertEqual(len(lines), 2)
            r1 = json.loads(lines[0])
            r2 = json.loads(lines[1])
            self.assertEqual(r1["session_id"], r2["session_id"])
            self.assertEqual(r1["attempt"], 1)
            self.assertEqual(r2["attempt"], 2)

    def test_writer_creates_parent_dir(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "nested/learning/runs.jsonl"
            w = RunsWriter(path)
            w.record_attempt(_mk_attempt())
            self.assertTrue(path.exists())

    def test_session_id_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "runs.jsonl"
            w = RunsWriter(path, session_id="fixed-sid-1234")
            w.record_attempt(_mk_attempt())
            row = json.loads(path.read_text().splitlines()[0])
            self.assertEqual(row["session_id"], "fixed-sid-1234")


class RunsReaderTests(unittest.TestCase):
    def _seed(self, path: Path) -> RunsWriter:
        w = RunsWriter(path, session_id="sess-a")
        w.record_attempt(_mk_attempt(animal_slug="rhino", attempt=1, composite=0.71))
        w.record_attempt(_mk_attempt(animal_slug="rhino", attempt=2, composite=0.82,
                                     weakest_dimension="color_floor",
                                     boost_applied="URGENT PALETTE FIX"))
        # different species + pose, separate session
        w2 = RunsWriter(path, session_id="sess-b")
        w2.record_attempt(_mk_attempt(animal_slug="peacock", pose_slug="tail-fanned",
                                      attempt=1, composite=0.65))
        w2.record_attempt(_mk_attempt(animal_slug="peacock", pose_slug="tail-fanned",
                                      attempt=1, composite=0.79))
        return w

    def test_iter_returns_all_valid_rows(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "runs.jsonl"
            self._seed(path)
            rows = list(RunsReader(path))
            self.assertEqual(len(rows), 4)

    def test_iter_skips_malformed_lines(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "runs.jsonl"
            self._seed(path)
            with path.open("a") as f:
                f.write("not-json-at-all\n")
                f.write('{"schema":"forge.something.else","attempt":99}\n')
            reader = RunsReader(path)
            rows = list(reader)
            self.assertEqual(len(rows), 4)  # both invalid skipped
            self.assertEqual(reader._skipped, 2)

    def test_best_per_group_picks_max_composite(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "runs.jsonl"
            self._seed(path)
            best = RunsReader(path).best_per_group(["animal_slug", "pose_slug"])
            self.assertIn(("rhino", "standing-alert"), best)
            self.assertIn(("peacock", "tail-fanned"), best)
            self.assertEqual(best[("rhino", "standing-alert")]["composite"], 0.82)
            self.assertEqual(best[("peacock", "tail-fanned")]["composite"], 0.79)

    def test_per_session_lineage_sorted_by_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "runs.jsonl"
            self._seed(path)
            sessions = RunsReader(path).per_session_lineage()
            self.assertEqual(len(sessions["sess-a"]), 2)
            self.assertEqual(sessions["sess-a"][0]["attempt"], 1)
            self.assertEqual(sessions["sess-a"][1]["attempt"], 2)


class FromReasoningResultTests(unittest.TestCase):
    """The adapter that converts a C.2 engine output into ledger rows."""

    def test_adapter_persists_all_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "runs.jsonl"
            writer = RunsWriter(path, session_id="reasoning-session-1")
            reasoning_result = {
                "schema": "forge.art_reasoning_engine.v1",
                "accepted": False,
                "max_attempts": 2,
                "attempts": [
                    {
                        "attempt": 1,
                        "prompt": "rhino render base prompt",
                        "seeds": [1, 2, 3, 4],
                        "winner": {
                            "path": "out/r1.png", "seed": 1,
                            "composite": 0.71, "rubric_pass_fraction": 0.857,
                            "clip_likeness_probability": 0.478,
                            "auto_qc_pass": False,
                            "pass_count": 6, "active_check_count": 7,
                            "qc_summary": {"failed_checks": ["color_floor"]},
                        },
                        "weakest_check": "color_floor",
                        "boost_clause_used_for_next_attempt": "URGENT PALETTE FIX",
                    },
                    {
                        "attempt": 2,
                        "prompt": "rhino render base prompt\n\nURGENT PALETTE FIX",
                        "seeds": [5, 6, 7, 8],
                        "winner": {
                            "path": "out/r2.png", "seed": 6,
                            "composite": 0.82, "rubric_pass_fraction": 1.0,
                            "clip_likeness_probability": 0.55,
                            "auto_qc_pass": True,
                            "pass_count": 7, "active_check_count": 7,
                            "qc_summary": {"failed_checks": []},
                        },
                        "weakest_check": None,
                        "boost_clause_used_for_next_attempt": None,
                    },
                ],
            }
            RunsWriter.from_reasoning_result(
                reasoning_result, animal_slug="rhino", pose_slug="standing-alert",
                model="z-image-turbo", writer=writer,
            )
            rows = list(RunsReader(path))
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]["attempt"], 1)
            self.assertEqual(rows[0]["weakest_dimension"], "color_floor")
            self.assertEqual(rows[0]["boost_applied"], "URGENT PALETTE FIX")
            self.assertFalse(rows[0]["accepted"])
            self.assertEqual(rows[1]["attempt"], 2)
            self.assertTrue(rows[1]["composite"] > rows[0]["composite"])
            # accepted should track the overall result, only the LAST row when accepted
            self.assertEqual(rows[1]["session_id"], "reasoning-session-1")


class MiningTests(unittest.TestCase):
    """D.2 — `forge madhubani learn` mining job."""

    def _seed_ledger(self, path: Path) -> None:
        w = RunsWriter(path, session_id="sess-a")
        w.record_attempt(_mk_attempt(animal_slug="rhino", attempt=1, composite=0.71,
                                     weakest_dimension="color_floor",
                                     boost_applied="URGENT PALETTE FIX"))
        w.record_attempt(_mk_attempt(animal_slug="rhino", attempt=2, composite=0.82,
                                     prompt="rhino render\n\nURGENT PALETTE FIX",
                                     boost_applied=None))
        RunsWriter(path, session_id="sess-b").record_attempt(
            _mk_attempt(animal_slug="peacock", pose_slug="tail-fanned",
                        attempt=1, composite=0.79))

    def test_mine_writes_markdown_with_top_per_species(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            runs = Path(td) / "runs.jsonl"
            out = Path(td) / "winning.md"
            self._seed_ledger(runs)
            summary = mine_winning_prompts(runs_path=runs, out_path=out)
            self.assertEqual(summary["n_rows"], 3)
            self.assertEqual(summary["n_species"], 2)
            md = out.read_text()
            self.assertIn("# Madhubani — Winning Prompts", md)
            self.assertIn("rhino", md)
            self.assertIn("peacock", md)
            # Top-per-species should surface the better rhino row (0.82)
            self.assertIn("0.8200", md)

    def test_mine_includes_session_lineage_for_multi_attempt(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            runs = Path(td) / "runs.jsonl"
            out = Path(td) / "winning.md"
            self._seed_ledger(runs)
            mine_winning_prompts(runs_path=runs, out_path=out)
            md = out.read_text()
            # Multi-attempt session should show its lineage
            self.assertIn("Session lineage", md)
            self.assertIn("attempt 1: composite=0.7100", md)
            self.assertIn("attempt 2: composite=0.8200", md)

    def test_mine_handles_empty_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            runs = Path(td) / "runs.jsonl"
            out = Path(td) / "winning.md"
            # No seed.
            summary = mine_winning_prompts(runs_path=runs, out_path=out)
            self.assertEqual(summary["n_rows"], 0)
            self.assertEqual(summary["n_groups"], 0)
            self.assertTrue(out.exists())
            self.assertIn("Rows scanned: 0", out.read_text())


if __name__ == "__main__":
    unittest.main()
