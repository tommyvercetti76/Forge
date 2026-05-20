#!/usr/bin/env python3
"""Phase C.2 — Art Reasoning Engine retry-with-targeted-boost loop.

Closes the loop. Given a render attempt + its QC result:

  1. Identify the weakest active failed check.
  2. Look up a per-check boost clause from
     `brand/madhubani/boost_prompts.json` and fill its template slots
     from the QC detail (target band, missing zones, measured count).
  3. Compose a new prompt by appending the boost to the base prompt.
  4. Re-render via the injected `render_fn`, score, pick best of the
     new N, and either accept or recurse — up to `max_attempts`.

Design choice: `render_fn` is injected so unit tests use a stub and
production wires in `flux_generate_batch`. The engine doesn't know
about mflux directly — it knows about prompts, QC results, boosts,
and rank decisions.

Usage (Python):
  from art_reasoning_engine import render_with_reasoning, propose_boost

  result = render_with_reasoning(
      base_prompt=subject_string,
      animal=animal_metadata,
      render_fn=my_render_fn,   # (prompt, seeds) -> list[Path]
      max_attempts=3,
      seeds_per_attempt=4,
      accept_score=0.85,
  )
  # result["winner"]["path"]  — final selected render
  # result["attempts"]         — full ledger: prompt, QC, boost used per attempt
  # result["accepted"]         — bool
  # result["weakest_dimension"] — last weakest check name if not accepted

Usage (offline CLI — diagnose a failing variant without re-rendering):
  python3 bin/art_reasoning_engine.py diagnose \\
      --animal tiger generated/madhubani_animals/.../tiger.png
  # → prints the boost clause that WOULD be appended if the engine
  # retried this render
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from best_of_n import pick_best_of_n, score_render, load_animals_index, infer_slug_from_path  # noqa: E402

BOOST_TABLE_PATH = ROOT / "brand/madhubani/boost_prompts.json"


# ──────────────────────────────────────────────────────────────────────
# Boost table loading
# ──────────────────────────────────────────────────────────────────────


_BOOST_CACHE: dict | None = None


def load_boost_table(path: Path = BOOST_TABLE_PATH) -> dict:
    global _BOOST_CACHE
    if _BOOST_CACHE is not None:
        return _BOOST_CACHE
    _BOOST_CACHE = json.loads(path.read_text())
    return _BOOST_CACHE


# ──────────────────────────────────────────────────────────────────────
# Weakest-dimension identification
# ──────────────────────────────────────────────────────────────────────


# Severity weights. Higher = more important to fix first when multiple
# checks fail in the same attempt. The values reflect the
# discrimination findings from QC_AGREEMENT_STUDY: checks with strong
# positive signal (subject_centered +0.40, anatomy +0.30, body_fill
# +0.20) get top priority because they actually distinguish pass from
# fail. Saturated checks (corners_clean, text_leak, eye_character) get
# lower priority because they rarely fire in practice anyway.
_CHECK_SEVERITY: dict[str, float] = {
    "subject_centered": 5.0,
    "anatomy": 4.5,
    "body_fill": 4.0,
    "decoration_zone_presence": 3.5,
    "anatomy_feature_count": 3.0,
    "color_floor": 2.5,
    "pattern_density": 2.0,
    "corners_clean": 1.5,
    "text_leak": 1.5,
    "eye_character": 1.0,
}


def identify_weakest_check(qc: dict[str, Any]) -> str | None:
    """Return the name of the highest-severity failed check, or None
    if every check passed. Ignores informational/disabled-by-default
    checks unless they're the ONLY failure (informational checks are
    surfaced last so retries don't waste compute on them)."""
    disabled = set(qc.get("disabled_by_default", []))
    checks = qc.get("checks", {})
    active_failed: list[tuple[float, str]] = []
    info_failed: list[tuple[float, str]] = []
    for name, item in checks.items():
        if item.get("pass"):
            continue
        severity = _CHECK_SEVERITY.get(name, 1.0)
        if name in disabled:
            info_failed.append((severity, name))
        else:
            active_failed.append((severity, name))
    if active_failed:
        active_failed.sort(key=lambda t: -t[0])
        return active_failed[0][1]
    if info_failed:
        info_failed.sort(key=lambda t: -t[0])
        return info_failed[0][1]
    return None


# ──────────────────────────────────────────────────────────────────────
# Boost composition
# ──────────────────────────────────────────────────────────────────────


def _format_missing_zones(zone_check: dict[str, Any]) -> str:
    failed = [z for z in zone_check.get("zones", []) if z.get("pass") is False]
    if not failed:
        return "(no specific zones flagged)"
    return ", ".join(f["zone"].split(":")[0] for f in failed[:5])


def _format_feature_failure(feature_check: dict[str, Any]) -> tuple[str, str, str]:
    """Return (feature_name, expected_text, failure_specific_clause_key).
    Picks the FIRST failed feature in the anatomy_feature_count check."""
    features = feature_check.get("features", [])
    failed = [f for f in features if f.get("pass") is False]
    if not failed:
        return ("(none)", "(none)", "unexpected_zero")
    f = failed[0]
    name = f.get("feature", "(unknown)")
    measured = f.get("measured")
    parsed = f.get("parsed", {})
    if parsed.get("expects_zero"):
        expected_text = "no visible " + name
        clause = "too_many" if (measured or 0) > 0 else "unexpected_zero"
    else:
        lo, hi = parsed.get("min"), parsed.get("max")
        if lo is not None and hi is not None:
            expected_text = f"between {lo} and {hi} {name}"
            if measured is None:
                clause = "unexpected_zero"
            elif measured > hi:
                clause = "too_many"
            elif measured < lo:
                clause = "too_few" if measured > 0 else "unexpected_zero"
            else:
                clause = "unexpected_zero"
        else:
            expected_text = f"{name} in the declared range"
            clause = "unexpected_zero"
    return (name, expected_text, clause)


def propose_boost(weakest_check: str, qc: dict[str, Any], boost_table: dict | None = None) -> str:
    """Pure function: given the name of the weakest failed check and the
    full QC result, return the boost clause to append to the next
    render's prompt. Returns empty string if the check isn't in the
    boost table."""
    table = boost_table if boost_table is not None else load_boost_table()
    entry = table.get("boosts", {}).get(weakest_check)
    if not entry:
        return ""
    clause: str = entry["boost_clause"]
    check_detail = qc.get("checks", {}).get(weakest_check, {})

    # Per-check slot fills.
    if weakest_check == "pattern_density":
        clause = clause.format(
            target_band=check_detail.get("target_band") or "ornate",
            target_min=float(check_detail.get("target_min") or 0.4),
        )
    elif weakest_check == "decoration_zone_presence":
        clause = clause.format(missing_zones_list=_format_missing_zones(check_detail))
    elif weakest_check == "anatomy_feature_count":
        feat_name, expected_text, clause_key = _format_feature_failure(check_detail)
        specific = table.get("feature_specific_clauses", {}).get(feat_name, {}).get(clause_key, "")
        clause = clause.format(
            feature=feat_name,
            measured=(check_detail.get("features", [{}])[0].get("measured", "?")),
            expected_text=expected_text,
            failure_specific_clause=specific,
        )
    return clause


def compose_boosted_prompt(base_prompt: str, boost_clause: str) -> str:
    """Append the boost to the base prompt. Boosts are appended (not
    prepended) so the original intent stays the lead and the corrective
    direction lands at the prompt tail — which the text encoder does
    weight on FLUX.2 / Z-Image-Turbo per A1.7's empirical finding."""
    if not boost_clause.strip():
        return base_prompt
    # Idempotent: don't append if the boost is already there verbatim.
    if boost_clause.strip() in base_prompt:
        return base_prompt
    return base_prompt.rstrip() + "\n\n" + boost_clause.strip()


# ──────────────────────────────────────────────────────────────────────
# Closed-loop orchestrator (with injectable render_fn for testability)
# ──────────────────────────────────────────────────────────────────────


RenderFn = Callable[[str, Sequence[int]], list[Path]]
"""(prompt, seeds) -> list of N rendered PNG paths."""


def render_with_reasoning(
    base_prompt: str,
    animal: dict | None,
    render_fn: RenderFn,
    *,
    max_attempts: int = 3,
    seeds_per_attempt: int = 4,
    seed_offset: int = 0,
    accept_score: float = 0.85,
    persist_to_ledger: bool = False,
    pose_slug: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Render → score → boost → re-render closed loop.

    Each attempt renders `seeds_per_attempt` variants at consecutive
    seed integers starting at `seed_offset + attempt_idx * seeds_per_attempt`.
    Picks the best of each batch via `pick_best_of_n`. If the winner's
    composite >= `accept_score`, the loop accepts and returns. Otherwise
    it identifies the weakest failed check, composes a targeted boost,
    appends it to the prompt, and retries up to `max_attempts`.

    Returns a full attempt-by-attempt ledger:
      {
        accepted: bool,
        winner: <pick_best_of_n winner dict>,
        attempts: [
          {attempt, prompt, seeds, ranked, winner, weakest_check, boost_clause_used_for_NEXT_attempt},
          ...
        ],
        final_prompt: str,
        accept_score, max_attempts, seeds_per_attempt,
      }
    """
    boost_table = load_boost_table()
    attempts: list[dict[str, Any]] = []
    current_prompt = base_prompt
    final_winner = None

    for attempt_idx in range(max_attempts):
        seeds = list(range(
            seed_offset + attempt_idx * seeds_per_attempt,
            seed_offset + (attempt_idx + 1) * seeds_per_attempt,
        ))
        rendered_paths = render_fn(current_prompt, seeds)
        ranking = pick_best_of_n(rendered_paths, animal)
        winner = ranking["winner"]
        winner_qc_summary = winner.get("qc_summary", {})

        attempt_entry: dict[str, Any] = {
            "attempt": attempt_idx + 1,
            "prompt": current_prompt,
            "seeds": seeds,
            "ranked": ranking["ranked"],
            "winner": winner,
            "weakest_check": None,
            "boost_clause_used_for_next_attempt": None,
        }

        # Acceptance gate: composite + auto_qc_pass both required.
        if winner["composite"] >= accept_score and winner["auto_qc_pass"]:
            attempts.append(attempt_entry)
            final_winner = winner
            early_result = {
                "schema": "forge.art_reasoning_engine.v1",
                "accepted": True,
                "winner": winner,
                "attempts": attempts,
                "final_prompt": current_prompt,
                "accept_score": accept_score,
                "max_attempts": max_attempts,
                "seeds_per_attempt": seeds_per_attempt,
                "stopped_on_attempt": attempt_idx + 1,
            }
            if persist_to_ledger and animal is not None:
                try:
                    from feedback_memory import RunsWriter
                    RunsWriter.from_reasoning_result(
                        early_result,
                        animal_slug=str(animal.get("slug", "unknown")),
                        pose_slug=pose_slug,
                        model=model,
                    )
                    early_result["persisted_to_ledger"] = True
                except Exception as exc:
                    early_result["persist_error"] = str(exc)
            return early_result

        # We need a fresh full QC dict to drive boost composition.
        # `winner` only carries the summary; re-score the winner path
        # to get the full check dict for boost lookup.
        full_qc = score_render(Path(winner["path"]), animal)
        # Hack: pick_best_of_n's score_render returns the summary-only
        # row. We need the underlying full QC. Re-call madhubani_qc.
        from madhubani_qc import score_madhubani_png
        full_qc_dict = score_madhubani_png(
            Path(winner["path"]),
            palette_path=ROOT / "brand/madhubani/palette.json",
            expected_body_fill=(animal or {}).get("body_fill_color"),
            body_type=(animal or {}).get("body_type"),
            decoration_density=(animal or {}).get("decoration_density"),
            required_decoration_zones=(animal or {}).get("required_decoration_zones"),
            anatomical_count_constraints=(animal or {}).get("anatomical_count_constraints"),
        )
        weakest = identify_weakest_check(full_qc_dict)
        attempt_entry["weakest_check"] = weakest
        if weakest is None:
            # Nothing failed — but composite still below accept_score?
            # That means the heuristic rubric passed but CLIP says low.
            # We can't meaningfully boost without a failed signal; stop.
            attempts.append(attempt_entry)
            final_winner = winner
            break

        boost = propose_boost(weakest, full_qc_dict, boost_table)
        attempt_entry["boost_clause_used_for_next_attempt"] = boost
        attempts.append(attempt_entry)

        if not boost:
            # No boost mapping for this check (e.g. unknown new check) — stop.
            final_winner = winner
            break

        if attempt_idx + 1 < max_attempts:
            current_prompt = compose_boosted_prompt(current_prompt, boost)
        else:
            final_winner = winner

    result = {
        "schema": "forge.art_reasoning_engine.v1",
        "accepted": False,
        "winner": final_winner,
        "attempts": attempts,
        "final_prompt": current_prompt,
        "accept_score": accept_score,
        "max_attempts": max_attempts,
        "seeds_per_attempt": seeds_per_attempt,
        "stopped_on_attempt": len(attempts),
    }
    if persist_to_ledger and animal is not None:
        # Phase D.1 hook — the reasoning loop dumps its attempt ledger into
        # brand/madhubani/learning/runs.jsonl so D.2's `forge madhubani learn`
        # mining job can surface winning prompts later. Lazy import so the
        # engine stays importable without the feedback_memory module on path.
        try:
            from feedback_memory import RunsWriter
            RunsWriter.from_reasoning_result(
                result,
                animal_slug=str(animal.get("slug", "unknown")),
                pose_slug=pose_slug,
                model=model,
            )
            result["persisted_to_ledger"] = True
        except Exception as exc:
            result["persist_error"] = str(exc)
    return result


# ──────────────────────────────────────────────────────────────────────
# Offline CLI: diagnose a single render without re-rendering
# ──────────────────────────────────────────────────────────────────────


def cmd_diagnose(args: argparse.Namespace) -> int:
    animals = load_animals_index()
    slug = args.animal or infer_slug_from_path(args.path)
    if slug is None:
        print("ERROR: pass --animal or use a filename containing a known slug.", file=sys.stderr)
        return 2
    animal = animals.get(slug)
    if animal is None:
        print(f"ERROR: animal slug '{slug}' not in animals.json", file=sys.stderr)
        return 2

    from madhubani_qc import score_madhubani_png
    qc = score_madhubani_png(
        args.path,
        palette_path=ROOT / "brand/madhubani/palette.json",
        expected_body_fill=animal.get("body_fill_color"),
        body_type=animal.get("body_type"),
        decoration_density=animal.get("decoration_density"),
        required_decoration_zones=animal.get("required_decoration_zones"),
        anatomical_count_constraints=animal.get("anatomical_count_constraints"),
    )
    weakest = identify_weakest_check(qc)
    print(f"Diagnosed: {args.path}")
    print(f"  Animal:           {slug}")
    print(f"  auto_qc_pass:     {qc['auto_qc_pass']}")
    print(f"  pass_count:       {qc['pass_count']}/{qc['active_check_count']}")
    failed = [n for n, item in qc["checks"].items() if not item.get("pass")]
    print(f"  Failed checks:    {failed}")
    print(f"  Weakest (highest-severity failed): {weakest}")
    if weakest is None:
        print("  No boost needed — every check passed.")
        return 0
    boost = propose_boost(weakest, qc)
    if not boost:
        print(f"  No boost mapping for check '{weakest}'.")
        return 0
    print(f"\n=== Proposed boost clause for next attempt ===\n{boost}\n")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("diagnose", help="Score an existing render and emit the boost clause that would be used for a retry")
    d.add_argument("path", type=Path)
    d.add_argument("--animal", default=None)
    d.set_defaults(func=cmd_diagnose)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
