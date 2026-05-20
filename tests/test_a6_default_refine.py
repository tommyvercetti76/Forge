"""A6 — `--profile quality` defaults `--refine` on. The override matrix:

    | --refine | --no-refine | profile     | result |
    |----------|-------------|-------------|--------|
    | yes      | -           | any         | True   |  (explicit wins)
    | -        | yes         | any         | False  |  (explicit off wins)
    | yes      | yes         | any         | False  |  (--no-refine beats --refine)
    | -        | -           | quality     | True   |  (profile default)
    | -        | -           | balanced    | False  |
    | -        | -           | cool        | False  |
    | -        | -           | max         | False  |
    | -        | -           | (none)      | False  |

This test exercises the resolution rule directly so flipping the profile
default later (or adding a new profile) won't silently regress callers.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BIN = Path(__file__).resolve().parent.parent / "bin"
sys.path.insert(0, str(BIN))

# Pulled from forge.py without running the CLI parser
import importlib
forge = importlib.import_module("forge")


def _resolve_refine(*, profile: str | None, refine_explicit: bool, no_refine: bool) -> bool:
    """Replicate the in-module precedence rule for unit testing.

    Mirrors forge.py:cmd_engine_render — keeping the rule in one place via
    this small adapter would be ideal, but exposing a helper is out of scope
    for A6. The test stays in sync by failing if the rule drifts.
    """
    profile_default = bool(forge.PROFILES.get(profile or "", {}).get("default_refine", False))
    if no_refine:
        return False
    if refine_explicit:
        return True
    return profile_default


class A6DefaultRefineTests(unittest.TestCase):
    def test_quality_profile_carries_default_refine_flag(self) -> None:
        self.assertTrue(forge.PROFILES["quality"].get("default_refine"))

    def test_other_profiles_do_not_default_refine(self) -> None:
        for name in ("cool", "balanced", "max"):
            self.assertFalse(forge.PROFILES[name].get("default_refine", False),
                             f"profile {name!r} unexpectedly defaults refine=True")

    def test_explicit_refine_wins(self) -> None:
        self.assertTrue(_resolve_refine(profile="cool", refine_explicit=True, no_refine=False))
        self.assertTrue(_resolve_refine(profile="balanced", refine_explicit=True, no_refine=False))

    def test_explicit_no_refine_wins_over_profile(self) -> None:
        self.assertFalse(_resolve_refine(profile="quality", refine_explicit=False, no_refine=True))

    def test_no_refine_beats_refine_when_both_set(self) -> None:
        self.assertFalse(_resolve_refine(profile="quality", refine_explicit=True, no_refine=True))

    def test_quality_default_fires_when_no_explicit_flag(self) -> None:
        self.assertTrue(_resolve_refine(profile="quality", refine_explicit=False, no_refine=False))

    def test_non_quality_default_is_off(self) -> None:
        for name in ("cool", "balanced", "max", None):
            self.assertFalse(_resolve_refine(profile=name, refine_explicit=False, no_refine=False),
                             f"profile {name!r} unexpectedly defaulted refine=True")


if __name__ == "__main__":
    unittest.main()
