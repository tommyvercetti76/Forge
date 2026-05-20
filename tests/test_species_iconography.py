"""Tests for the species iconography table (Lever B, A1, 2026-05-20).

Contract as of 2026-05-20 (after the Madhubani regression fix):

  - brand/madhubani/species_iconography.json still loads and is well-formed.
  - The _match_species() helper still detects species keys + aliases.
  - The MinimalistTShirtEngine deliberately DOES NOT consume the table:
    its phrases are photorealistic and conflict with the Madhubani folk
    register. The engine records a skipped_reason in the directive audit
    so reviewers see this was intentional.

If a future non-Madhubani engine (wildlife-photo, noir, …) wants to use
the table, the helper is here for it. This test locks both the table
correctness and the deliberate skip in minimalist-tshirt.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import style_engines  # noqa: E402
from style_engines import (  # noqa: E402
    MTCompositionConfig,
    MTProductionConfig,
    MTStyleConfig,
    MTSubjectConfig,
    MinimalistTShirtConfig,
    MinimalistTShirtEngine,
    _match_species,
)


SPECIES_JSON = ROOT / "brand" / "madhubani" / "species_iconography.json"


def _config_for(subject: str, *, species_iconography: bool = True) -> MinimalistTShirtConfig:
    return MinimalistTShirtConfig(
        subject=MTSubjectConfig(subject=subject, motif="madhubani-folk-icon"),
        style=MTStyleConfig(
            tradition="madhubani-contemporary",
            detail="maximal-but-printable",
            symmetry="handmade-balanced",
            accents="micro-folk-dots",
        ),
        production=MTProductionConfig(
            output="print-art",
            ink="vibrant-folk",
            shirt_color="cream-or-black",
        ),
        composition=MTCompositionConfig(
            placement="center-chest",
            layout="single-mark",
            background="no-background",
            border="none",
        ),
        species_iconography=species_iconography,
    )


class SpeciesIconographyTableTests(unittest.TestCase):
    """The species table itself stays well-formed even though minimalist-tshirt no longer consumes it."""

    def test_json_file_loads_and_parses_without_error(self) -> None:
        data = json.loads(SPECIES_JSON.read_text(encoding="utf-8"))
        self.assertEqual(data.get("schema"), "forge.species_iconography.v1")
        species = data.get("species") or {}
        self.assertEqual(
            set(species.keys()),
            {"tiger", "peacock", "elephant", "cobra", "fish",
             "horse", "deer", "parrot", "turtle", "lion"},
        )
        for key, entry in species.items():
            self.assertIsInstance(entry, dict, f"{key} entry must be a dict")
            self.assertTrue(entry.get("identity"), f"{key} must carry an identity phrase")
            self.assertIsInstance(entry.get("aliases") or [], list)


class MatchSpeciesHelperTests(unittest.TestCase):
    """The matcher still works for future engines that want to consume the table."""

    def test_tiger_key_matches(self) -> None:
        hit = _match_species("Royal Bengal Tiger in side profile")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["species"], "tiger")

    def test_snake_alias_resolves_to_cobra(self) -> None:
        hit = _match_species("a coiled snake rising")
        self.assertIsNotNone(hit)
        self.assertEqual(hit["species"], "cobra")

    def test_unknown_subject_returns_none(self) -> None:
        self.assertIsNone(_match_species("a sleek xenomorph"))


class MinimalistTShirtDeliberateSkipTests(unittest.TestCase):
    """The Madhubani-targeting engine MUST NOT inject the photorealistic phrases.

    The fix on 2026-05-20 made minimalist-tshirt always skip the species
    iconography table because its phrases (e.g. "rust-orange body with broken
    vertical black stripes") force FLUX out of the Madhubani folk register
    (deep navy/indigo body + folk-pattern overlay). The pass_examples corpus
    is the source of truth for what "good" Madhubani looks like; the audit
    field on every render carries a skipped_reason explaining the choice.
    """

    def test_tiger_subject_does_not_inject_photorealistic_phrase(self) -> None:
        directive = MinimalistTShirtEngine.build(
            _config_for("single centered Royal Bengal tiger in full-body side profile")
        )
        positive_lower = directive.positive.lower()
        # The exact photorealistic phrase from species_iconography.json must not appear:
        self.assertNotIn("amber-gold eyes with vertical slit pupils", positive_lower)
        self.assertNotIn("rust-orange body with broken vertical black stripes", positive_lower)
        # No " — species: " injection marker either.
        self.assertNotIn(" — species: ", directive.positive)

    def test_audit_records_skip_with_reason(self) -> None:
        directive = MinimalistTShirtEngine.build(
            _config_for("Royal Bengal Tiger")
        )
        entry = directive.audit.get("species_iconography")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.get("applied"), False)
        self.assertIsNone(entry.get("species"))
        self.assertIn("folk register", entry.get("skipped_reason", "").lower())

    def test_opt_out_flag_is_effectively_a_noop_now(self) -> None:
        # With the skip in place, the species_iconography=False config flag
        # produces the same outcome as species_iconography=True: no injection,
        # audit records skip. Both routes converge on the same contract.
        d_on = MinimalistTShirtEngine.build(_config_for("Tiger", species_iconography=True))
        d_off = MinimalistTShirtEngine.build(_config_for("Tiger", species_iconography=False))
        self.assertNotIn(" — species: ", d_on.positive)
        self.assertNotIn(" — species: ", d_off.positive)

    def test_no_phrase_for_unknown_species_either(self) -> None:
        directive = MinimalistTShirtEngine.build(_config_for("a sleek xenomorph"))
        self.assertNotIn(" — species: ", directive.positive)


if __name__ == "__main__":
    unittest.main()
