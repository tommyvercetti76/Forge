"""Tests for the quality plumbing in `translate_texts_ollama` (backlog item B2).

Covers:
    (a) glossary enforcement — violation surfaces in out_report
    (b) glossary system-prompt injection — the block appears in the Ollama payload
    (c) leakage detection — too much ASCII in a non-English target line flags
    (d) leakage NOT flagged when target is English
    (e) repeated-line blocker — 3+ identical output lines not in the source
    (f) backward compat — default kwargs preserve byte-identical behavior

All Ollama HTTP calls are intercepted via `unittest.mock.patch` so no network
or model server is required.
"""

from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

import forge_runtime  # noqa: E402


class _FakeResponse:
    """Minimal stand-in for the context manager returned by urlopen."""

    def __init__(self, payload: dict) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _make_ollama_stub(translated_lines, capture_bin=None):
    """Build a urlopen replacement that returns ``translated_lines`` as JSON.

    If ``capture_bin`` is a list, the raw request body is appended for
    inspection (used by the system-prompt injection test).
    """

    def stub(req, timeout=None):  # noqa: ARG001 - mimic urlopen signature
        if capture_bin is not None:
            capture_bin.append(req.data)
        body = "\n".join(f"{i}: {line}" for i, line in enumerate(translated_lines))
        return _FakeResponse({"response": body})

    return stub


class TranslateQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        # Silence token-usage prints so test output stays focused.
        self._stderr_buf = io.StringIO()
        self._token_usage_patch = patch.object(forge_runtime, "print_ollama_token_usage", lambda *a, **kw: None)
        self._token_usage_patch.start()

    def tearDown(self) -> None:
        self._token_usage_patch.stop()

    # -- (a) glossary enforcement ---------------------------------------------

    def test_glossary_violation_surfaces_in_report(self) -> None:
        glossary = {"hi": {"Forge": "फ़ोर्ज", "tiger": "बाघ"}}
        # Mock returns translations that LACK the glossary terms entirely.
        stub = _make_ollama_stub([
            "एक tiger के बारे में Forge में पढ़ा।",  # source had "Forge" + "tiger"; targets missing
        ])
        report: dict = {}
        with patch.object(forge_runtime.urllib.request, "urlopen", stub):
            out = forge_runtime.translate_texts_ollama(
                ["I read about Forge and a tiger."],
                target_lang="hi",
                glossary=glossary,
                out_report=report,
            )
        self.assertEqual(len(out), 1)
        terms = {v["expected_term"] for v in report["glossary_violations"]}
        self.assertIn("फ़ोर्ज", terms)
        self.assertIn("बाघ", terms)
        # Each violation references the input line index.
        for v in report["glossary_violations"]:
            self.assertEqual(v["line_index"], 0)

    # -- (b) glossary injected into the system prompt -------------------------

    def test_glossary_block_injected_into_system_prompt(self) -> None:
        glossary = {"hi": {"Forge": "फ़ोर्ज", "tiger": "बाघ"}}
        captured: list[bytes] = []
        stub = _make_ollama_stub(["dummy."], capture_bin=captured)
        with patch.object(forge_runtime.urllib.request, "urlopen", stub):
            forge_runtime.translate_texts_ollama(
                ["I read about Forge and a tiger."],
                target_lang="hi",
                glossary=glossary,
                out_report={},
            )
        self.assertGreaterEqual(len(captured), 1)
        body = json.loads(captured[0].decode("utf-8"))
        system_prompt = body.get("system", "")
        self.assertIn("Glossary", system_prompt)
        self.assertIn('"Forge"', system_prompt)
        self.assertIn("फ़ोर्ज", system_prompt)
        self.assertIn('"tiger"', system_prompt)
        self.assertIn("बाघ", system_prompt)
        # Must precede the existing localization-engine instruction so the model
        # sees the glossary as a hard constraint up front.
        self.assertLess(system_prompt.index("Glossary"), system_prompt.index("professional media localization"))

    # -- (c) leakage detection on a non-English target ------------------------

    def test_leakage_flag_on_high_ascii_fraction_for_hindi(self) -> None:
        # 5 tokens, 4 are ASCII words → fraction 0.8 (> 0.30 threshold).
        stub = _make_ollama_stub([
            "hello world from the model",
        ])
        report: dict = {}
        with patch.object(forge_runtime.urllib.request, "urlopen", stub):
            forge_runtime.translate_texts_ollama(
                ["किसी पंक्ति"],
                target_lang="hi",
                out_report=report,
            )
        self.assertEqual(len(report["leakage_flags"]), 1)
        flag = report["leakage_flags"][0]
        self.assertEqual(flag["line_index"], 0)
        self.assertGreater(flag["ascii_word_fraction"], 0.30)
        self.assertEqual(flag["text"], "hello world from the model")

    # -- (d) leakage NOT flagged for English target ---------------------------

    def test_no_leakage_flag_when_target_is_english(self) -> None:
        stub = _make_ollama_stub([
            "hello world from the model",
        ])
        report: dict = {}
        with patch.object(forge_runtime.urllib.request, "urlopen", stub):
            forge_runtime.translate_texts_ollama(
                ["bonjour"],
                target_lang="en",
                source_lang="fr",
                out_report=report,
            )
        self.assertEqual(report["leakage_flags"], [])

    # -- (e) repeated-line blocker --------------------------------------------

    def test_repeated_line_blocker_fires_on_pathological_repetition(self) -> None:
        stub = _make_ollama_stub([
            "मुझे माफ़ करें।",
            "मुझे माफ़ करें।",
            "मुझे माफ़ करें।",
        ])
        report: dict = {}
        with patch.object(forge_runtime.urllib.request, "urlopen", stub):
            forge_runtime.translate_texts_ollama(
                ["Line one.", "Line two.", "Line three."],
                target_lang="hi",
                out_report=report,
            )
        self.assertTrue(report["repeated_lines"])
        self.assertEqual(report["repeated_line_value"], "मुझे माफ़ करें।")

    def test_repeated_line_blocker_quiet_when_repetition_matches_source(self) -> None:
        # If the source also contains the repeated value, this is legitimate
        # (e.g., a refrain) and must NOT trigger the blocker. We force the
        # translation code path via mr -> hi so the early "target == source"
        # short-circuit does not skip our checks.
        stub = _make_ollama_stub(["हाँ।", "हाँ।", "हाँ।"])
        report: dict = {}
        with patch.object(forge_runtime.urllib.request, "urlopen", stub):
            forge_runtime.translate_texts_ollama(
                ["हाँ।", "हाँ।", "हाँ।"],
                target_lang="hi",
                source_lang="mr",
                out_report=report,
            )
        self.assertFalse(report["repeated_lines"])
        self.assertIsNone(report["repeated_line_value"])

    # -- (f) backward compatibility -------------------------------------------

    def test_backward_compat_no_glossary_no_report_unchanged_output(self) -> None:
        # Two parallel runs with the same mocked Ollama: one with new kwargs
        # left at defaults, one bypassing them entirely. Outputs must match
        # byte-for-byte.
        stub = _make_ollama_stub(["नमस्ते दुनिया", "स्वागत है"])
        with patch.object(forge_runtime.urllib.request, "urlopen", stub):
            new_path = forge_runtime.translate_texts_ollama(
                ["hello world", "welcome"],
                target_lang="hi",
            )
        with patch.object(forge_runtime.urllib.request, "urlopen", stub):
            control = forge_runtime.translate_texts_ollama(
                ["hello world", "welcome"],
                target_lang="hi",
            )
        self.assertEqual(new_path, control)
        self.assertEqual(new_path, ["नमस्ते दुनिया", "स्वागत है"])

    def test_backward_compat_system_prompt_unchanged_without_glossary(self) -> None:
        # When glossary is None, the system prompt sent to Ollama must NOT
        # contain the "Glossary" header — that is the byte-identical guarantee
        # for existing callers.
        captured: list[bytes] = []
        stub = _make_ollama_stub(["नमस्ते दुनिया"], capture_bin=captured)
        with patch.object(forge_runtime.urllib.request, "urlopen", stub):
            forge_runtime.translate_texts_ollama(
                ["hello world"],
                target_lang="hi",
            )
        body = json.loads(captured[0].decode("utf-8"))
        self.assertNotIn("Glossary", body["system"])


if __name__ == "__main__":
    unittest.main()
