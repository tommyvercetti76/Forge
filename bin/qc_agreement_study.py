#!/usr/bin/env python3
"""Measure how well the 9-check Madhubani auto-QC agrees with human labels.

This is the eval-methodology check that justifies the eval engineering. We
hold the QC rubric to the same standard the rubric holds renders to: does
it catch what humans catch, and does it pass what humans pass?

Ground truth comes from two sources in tree:

  Strong labels (4 + 5 = 9 images):
    generated/madhubani_animals/_learning/pass_examples/*.png     -> pass
    generated/madhubani_animals/_learning/fail_examples/*.png     -> fail

  Weak labels (8 + 8 = 16 images), used as a directional confirmation set:
    generated/madhubani_animals/_legacy/indian_animals_v3/*.png   -> pass
        (post-Lane-1 flat-folk tuning; current best baseline)
    generated/madhubani_animals/_legacy/indian_animals_v1/*.png   -> fail
        (mascot-era cartoon renders, before anti-photorealism tuning)

For each labeled image we:
  1. Infer the animal slug from the filename
  2. Look up that animal's body_type / body_fill_color /
     decoration_density / required_decoration_zones from animals.json
  3. Run score_madhubani_png with the full per-species metadata
  4. Compare the auto_qc_pass boolean against the label

Emits:
  - A confusion matrix (TP / FP / TN / FN)
  - Per-check pass-rate breakdown on the labeled pass vs fail buckets
  - Three failure modes the auto-QC misses (with image paths for inspection)
  - A JSON dump for follow-up analysis

Usage:
  python3 bin/qc_agreement_study.py
  python3 bin/qc_agreement_study.py --json out/agreement.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

from madhubani_qc import score_madhubani_png  # noqa: E402


PASS_DIR = ROOT / "generated/madhubani_animals/_learning/pass_examples"
FAIL_DIR = ROOT / "generated/madhubani_animals/_learning/fail_examples"
V3_DIR = ROOT / "generated/madhubani_animals/_legacy/indian_animals_v3"
V1_DIR = ROOT / "generated/madhubani_animals/_legacy/indian_animals_v1"
PALETTE_PATH = ROOT / "brand/madhubani/palette.json"
ANIMALS_PATH = ROOT / "brand/madhubani/animals.json"


# Hand-curated filename -> animal slug mapping. The legacy files use long
# descriptive names; the _learning files use short forms. Keep this map
# explicit so labelling stays obvious.
FILENAME_HINTS: dict[str, str] = {
    "tiger": "tiger",
    "royal_bengal_tiger": "tiger",
    "elephant": "elephant",
    "indian_elephant": "elephant",
    "peacock": "peacock",
    "indian_peacock": "peacock",
    "blackbuck": "blackbuck",
    "rhino": "rhino",
    "one_horned_rhinoceros": "rhino",
    "cobra": "cobra",
    "king_cobra": "cobra",
    "snow_leopard": "snow-leopard",
    "lion_tailed_macaque": "macaque",
    "macaque": "macaque",
}


def infer_slug(path: Path) -> str | None:
    stem = path.stem.lower()
    for key, slug in FILENAME_HINTS.items():
        if key in stem:
            return slug
    return None


def load_animals_index() -> dict[str, dict]:
    data = json.loads(ANIMALS_PATH.read_text())
    return {entry["slug"]: entry for entry in data.get("animals", [])}


def collect_corpus(animals: dict[str, dict]) -> list[dict[str, Any]]:
    corpus: list[dict[str, Any]] = []

    def add(path: Path, label: str, confidence: str) -> None:
        slug = infer_slug(path)
        if slug is None or slug not in animals:
            corpus.append({
                "path": path,
                "label": label,
                "confidence": confidence,
                "slug": slug,
                "skip_reason": "no animal slug match in animals.json",
            })
            return
        animal = animals[slug]
        corpus.append({
            "path": path,
            "label": label,
            "confidence": confidence,
            "slug": slug,
            "animal": animal,
            "skip_reason": None,
        })

    for png in sorted(PASS_DIR.glob("*.png")):
        add(png, "pass", "strong")
    for png in sorted(FAIL_DIR.glob("*.png")):
        add(png, "fail", "strong")
    for png in sorted(V3_DIR.glob("*.png")):
        if "transparent" in png.name:
            continue
        add(png, "pass", "weak")
    for png in sorted(V1_DIR.glob("*.png")):
        if "transparent" in png.name:
            continue
        add(png, "fail", "weak")
    return corpus


def score_one(entry: dict[str, Any]) -> dict[str, Any] | None:
    if entry["skip_reason"] is not None:
        return None
    animal = entry["animal"]
    qc = score_madhubani_png(
        entry["path"],
        palette_path=PALETTE_PATH,
        expected_body_fill=animal.get("body_fill_color"),
        body_type=animal.get("body_type"),
        decoration_density=animal.get("decoration_density"),
        required_decoration_zones=animal.get("required_decoration_zones"),
        anatomical_count_constraints=animal.get("anatomical_count_constraints"),
    )
    return qc


def confusion(rows: list[dict[str, Any]]) -> dict[str, int]:
    tp = fp = tn = fn = 0
    for row in rows:
        label = row["label"]
        predicted = row["auto_qc_pass"]
        if label == "pass" and predicted:
            tp += 1
        elif label == "pass" and not predicted:
            fn += 1
        elif label == "fail" and not predicted:
            tn += 1
        elif label == "fail" and predicted:
            fp += 1
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def precision_recall_f1(c: dict[str, int]) -> dict[str, float]:
    tp, fp, fn = c["tp"], c["fp"], c["fn"]
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    accuracy = (tp + c["tn"]) / max(1, sum(c.values()))
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(accuracy, 4),
    }


def per_check_rates(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    """For each of the 9 checks, compute the pass rate on label=pass vs label=fail."""
    if not rows:
        return {}
    check_names = list(rows[0]["checks"].keys())
    by_check: dict[str, dict[str, float]] = {}
    for name in check_names:
        pass_pass = pass_total = 0
        fail_pass = fail_total = 0
        for row in rows:
            check_pass = bool(row["checks"][name].get("pass"))
            if row["label"] == "pass":
                pass_total += 1
                pass_pass += int(check_pass)
            else:
                fail_total += 1
                fail_pass += int(check_pass)
        by_check[name] = {
            "pass_set_pass_rate": round(pass_pass / max(1, pass_total), 4),
            "fail_set_pass_rate": round(fail_pass / max(1, fail_total), 4),
            "discrimination": round(
                pass_pass / max(1, pass_total) - fail_pass / max(1, fail_total), 4
            ),
        }
    return by_check


def disagreements(rows: list[dict[str, Any]], k: int = 5) -> dict[str, list[dict[str, Any]]]:
    """Pull up to k images per disagreement bucket for inspection."""
    fp_rows = [r for r in rows if r["label"] == "fail" and r["auto_qc_pass"]]
    fn_rows = [r for r in rows if r["label"] == "pass" and not r["auto_qc_pass"]]

    def snip(r: dict[str, Any]) -> dict[str, Any]:
        failed_checks = [
            name for name, item in r["checks"].items() if not item.get("pass")
        ]
        return {
            "path": str(r["path"].relative_to(ROOT)),
            "slug": r["slug"],
            "label": r["label"],
            "auto_qc_pass": r["auto_qc_pass"],
            "pass_count": r["pass_count"],
            "active_check_count": r["active_check_count"],
            "failed_checks": failed_checks,
        }

    return {
        "false_positives_auto_passed_but_human_fail": [snip(r) for r in fp_rows[:k]],
        "false_negatives_auto_failed_but_human_pass": [snip(r) for r in fn_rows[:k]],
    }


def report(rows: list[dict[str, Any]], confidence_filter: str | None = None) -> dict[str, Any]:
    if confidence_filter:
        rows = [r for r in rows if r["confidence"] == confidence_filter]
    c = confusion(rows)
    metrics = precision_recall_f1(c)
    return {
        "n": len(rows),
        "confidence_filter": confidence_filter or "all",
        "confusion": c,
        "metrics": metrics,
        "per_check": per_check_rates(rows),
        "disagreements": disagreements(rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", type=Path, help="Write full results to this JSON file")
    args = parser.parse_args()

    animals = load_animals_index()
    corpus = collect_corpus(animals)

    rows: list[dict[str, Any]] = []
    skipped: list[str] = []
    for entry in corpus:
        if entry["skip_reason"]:
            skipped.append(f"{entry['path'].name}: {entry['skip_reason']}")
            continue
        qc = score_one(entry)
        if qc is None:
            continue
        rows.append({
            "path": entry["path"],
            "label": entry["label"],
            "confidence": entry["confidence"],
            "slug": entry["slug"],
            "auto_qc_pass": qc["auto_qc_pass"],
            "pass_count": qc["pass_count"],
            "active_check_count": qc["active_check_count"],
            "checks": qc["checks"],
        })

    strong = report(rows, confidence_filter="strong")
    weak = report(rows, confidence_filter="weak")
    overall = report(rows)

    print(f"Scored {len(rows)} images ({sum(1 for r in rows if r['confidence']=='strong')} strong, "
          f"{sum(1 for r in rows if r['confidence']=='weak')} weak). Skipped: {len(skipped)}")
    if skipped:
        for line in skipped[:6]:
            print(f"  skip: {line}")
    print()
    for name, rep in [("STRONG-LABEL", strong), ("WEAK-LABEL", weak), ("ALL", overall)]:
        c, m = rep["confusion"], rep["metrics"]
        print(f"=== {name} (n={rep['n']}) ===")
        print(f"  Confusion: TP={c['tp']} FP={c['fp']} TN={c['tn']} FN={c['fn']}")
        print(f"  Precision={m['precision']:.3f}  Recall={m['recall']:.3f}  "
              f"F1={m['f1']:.3f}  Accuracy={m['accuracy']:.3f}")
    print()
    print("=== Per-check discrimination (strong-label set) ===")
    print(f"  {'check':<30} {'pass_rate_on_pass':>20} {'pass_rate_on_fail':>20} {'gap':>8}")
    for name, item in strong["per_check"].items():
        print(f"  {name:<30} {item['pass_set_pass_rate']:>20.3f} "
              f"{item['fail_set_pass_rate']:>20.3f} {item['discrimination']:>+8.3f}")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": "forge.qc_agreement_study.v1",
            "n_scored": len(rows),
            "n_skipped": len(skipped),
            "skipped_filenames": skipped,
            "strong": strong,
            "weak": weak,
            "overall": overall,
        }
        args.json.write_text(json.dumps(payload, indent=2, default=str))
        print(f"\nWrote {args.json}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
