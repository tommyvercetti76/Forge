"""Tests for the per-species iconography table (Lever B, A1, 2026-05-20).

The MinimalistTShirtEngine consults brand/madhubani/species_iconography.json
once at module import time. For a known species name (or alias) appearing in
the subject string, the engine appends the iconography phrase to the positive
prompt and records the hit in the directive audit dict. Recipes can opt out by
setting ``species_iconography=False`` on the config.
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
)


SPECIES_JSON = ROOT / "brand" / "madhubani" / "species_iconography.json"


def _tiger_config(subject: str, *, species_iconography: bool = True) -> MinimalistTShirtConfig:
    """Build a vibrant-folk Madhubani config keyed to ``subject``.

    The vibrant-folk path is the production path the iconography table is
    aimed at, so we exercise the same branch the engine actually runs in
    production.
    """
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
    """The species table itself should be loadable, well-formed, and complete."""

    def test_json_file_loads_and_parses_without_error(self) -> None:
        data = json.loads(SPECIES_JSON.read_text(encoding="utf-8"))
        self.assertEqual(data.get("schema"), "forge.species_iconography.v1")
        self.assertIn("version", data)
        species = data.get("species") or {}
        self.assertEqual(
            set(species.keys()),
            {
                "tiger", "peacock", "elephant", "cobra", "fish",
                "horse", "deer", "parrot", "turtle", "lion",
            },
            "species_iconography.json must cover exactly the 10 species in the findings draft",
        )
        for key, entry in species.items():
            self.assertIsInstance(entry, dict, f"{key} entry must be a dict")
            self.assertTrue(entry.get("identity"), f"{key} must carry an identity phrase")
            aliases = entry.get("aliases") or []
            self.assertIsInstance(aliases, list, f"{key} aliases must be a list")
            self.assertGreaterEqual(
                len(aliases), 2,
                f"{key} should have at least 2 aliases for resilient subject matching",
            )


class SpeciesIconographyInjectionTests(unittest.TestCase):
    """The engine should inject the matching iconography phrase + audit entry."""

    def test_tiger_subject_string_injects_ocelli_whisker_phrase(self) -> None:
        directive = MinimalistTShirtEngine.build(
            _tiger_config("single centered Royal Bengal tiger in full-body side profile")
        )
        # The exact phrase from the findings doc / species_iconography.json
        # must end up in the positive prompt so FLUX has the compositional anchor.
        self.assertIn("ocelli", directive.positive.lower())
        self.assertIn("whiskers", directive.positive.lower())
        self.assertIn(" — species: ", directive.positive)
        # The audit dict must record the hit so reproducibility is intact.
        audit_entry = directive.audit.get("species_iconography")
        self.assertIsNotNone(audit_entry)
        self.assertEqual(audit_entry["species"], "tiger")
        self.assertIn("ocelli", audit_entry["phrase"])
        self.assertIn(audit_entry["matched_via"], {"tiger", "bengal tiger", "royal bengal tiger"})

    def test_cobra_alias_snake_matches(self) -> None:
        directive = MinimalistTShirtEngine.build(
            _tiger_config("a single coiled snake rising in folk-art register")
        )
        # The snake alias should resolve to the cobra entry, so the flared-hood
        # phrase ends up in the prompt.
        self.assertIn("flared hood", directive.positive.lower())
        self.assertIn(" — species: ", directive.positive)
        audit_entry = directive.audit.get("species_iconography")
        self.assertEqual(audit_entry["species"], "cobra")
        self.assertEqual(audit_entry["matched_via"], "snake")

    def test_opt_out_flag_suppresses_injection(self) -> None:
        directive = MinimalistTShirtEngine.build(
            _tiger_config(
                "single centered Royal Bengal tiger in full-body side profile",
                species_iconography=False,
            )
        )
        # No appended species block, no audit entry pointing at a species.
        self.assertNotIn(" — species: ", directive.positive)
        # Specifically: even though "tiger" is in the subject, the phrase must
        # not be injected.
        self.assertNotIn(
            "amber-gold eyes with vertical slit pupils",
            directive.positive,
        )
        audit_entry = directive.audit.get("species_iconography")
        self.assertIsNotNone(audit_entry)
        self.assertIsNone(audit_entry["species"])
        self.assertTrue(audit_entry.get("disabled"))

    def test_unknown_species_xenomorph_is_a_noop(self) -> None:
        directive = MinimalistTShirtEngine.build(
            _tiger_config("a sleek xenomorph stalking through industrial mist")
        )
        # Prompt body unchanged shape-wise: no species suffix appended.
        self.assertNotIn(" — species: ", directive.positive)
        audit_entry = directive.audit.get("species_iconography")
        self.assertIsNotNone(audit_entry)
        self.assertIsNone(audit_entry["species"])


if __name__ == "__main__":
    unittest.main()
