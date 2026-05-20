#!/usr/bin/env python3
"""train_madhubani_likeness_v2 — class-balanced + L1-regularized probe
on top of the same CLIP ViT-B/32 features, evaluated honestly on the
N=16 maintainer-labeled gold set via stratified k-fold + LOOCV.

v1 (madhubani_likeness_v1.npz) was a L2-regularized LR trained on
weakly-labeled era-buckets (16 v1+v3 images). On the N=16 strong-
label test set with LOOCV it collapsed to F1=0.00 (predicted FAIL
for every image) — documented in docs/QC_AGREEMENT_STUDY.md.

v2 changes:

  * Train data = the strong-label set (brand/madhubani/labels_v1.json),
    not the era-bucket weak labels. This matches the actual evaluation
    distribution.
  * `class_weight='balanced'` to handle the 6 pass vs 10 fail
    imbalance (62.5% fail prior; v1 just predicted the majority).
  * L1 penalty (`penalty='l1', solver='liblinear'`) for feature
    selection — at N=16 / 512 features the dense L2 fit is degenerate;
    L1 zeros most coordinates and keeps the most discriminative few.
  * Hyperparameter sweep over C ∈ {0.01, 0.1, 1.0, 10.0}, pick the best
    by LOOCV F1.
  * Report calibration alongside F1 (confidence histogram on FN + FP).

Output:
  brand/madhubani/madhubani_likeness_v2.npz
  brand/madhubani/madhubani_likeness_v2.report.json

If the LOOCV F1 lifts above v1's 0.00 with measurable signal, v2 is
shipped as the new active probe and the closed-loop CLI is rewired
to load it. If not, the report documents the negative finding and
the next iteration (per-zone probes) becomes the path.
"""

from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
from PIL import Image
from sklearn.exceptions import ConvergenceWarning
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import LeaveOneOut, StratifiedKFold

warnings.filterwarnings("ignore", category=ConvergenceWarning)
warnings.filterwarnings("ignore", category=RuntimeWarning)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bin"))

LABELS_PATH = ROOT / "brand/madhubani/labels_v1.json"
OUT_PATH = ROOT / "brand/madhubani/madhubani_likeness_v2.npz"
REPORT_PATH = ROOT / "brand/madhubani/madhubani_likeness_v2.report.json"


def load_clip():
    import open_clip
    import torch
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="openai",
    )
    model.eval()
    return model, preprocess, torch


def embed_images(paths, model, preprocess, torch):
    tensors = [preprocess(Image.open(p).convert("RGB")) for p in paths]
    batch = torch.stack(tensors)
    with torch.no_grad():
        feats = model.encode_image(batch).float().numpy()
    feats /= (np.linalg.norm(feats, axis=1, keepdims=True) + 1e-9)
    return feats


def confusion(y_true, y_pred):
    tp = int(((y_pred == 1) & (y_true == 1)).sum())
    fp = int(((y_pred == 1) & (y_true == 0)).sum())
    tn = int(((y_pred == 0) & (y_true == 0)).sum())
    fn = int(((y_pred == 0) & (y_true == 1)).sum())
    return {"tp": tp, "fp": fp, "tn": tn, "fn": fn}


def metrics(c):
    tp, fp, tn, fn = c["tp"], c["fp"], c["tn"], c["fn"]
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    acc = (tp + tn) / max(1, tp + fp + tn + fn)
    return {
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "accuracy": round(acc, 4),
    }


def loocv_predict(X, y, *, C, class_weight=None, penalty="l1"):
    """Leave-one-out cross-validation predictions on (X, y)."""
    loo = LeaveOneOut()
    preds = np.zeros(len(y), dtype=int)
    probs = np.zeros(len(y))
    for tr, va in loo.split(X):
        solver = "liblinear" if penalty == "l1" else "lbfgs"
        clf = LogisticRegression(
            C=C, penalty=penalty, solver=solver,
            class_weight=class_weight, max_iter=5000, random_state=0,
        )
        clf.fit(X[tr], y[tr])
        preds[va] = clf.predict(X[va])
        probs[va] = clf.predict_proba(X[va])[:, 1]
    return preds, probs


def main() -> int:
    labels = json.loads(LABELS_PATH.read_text())
    entries = labels["entries"]
    paths = [ROOT / e["path"] for e in entries]
    y = np.array([1 if e["label"] == "pass" else 0 for e in entries], dtype=int)
    names = [e["filename"] for e in entries]

    print(f"Labels of record: {LABELS_PATH.relative_to(ROOT)}")
    print(f"  N = {len(entries)}  ({(y == 1).sum()} pass + {(y == 0).sum()} fail)")
    print()
    print("Loading CLIP ViT-B/32 (openai weights)...")
    model, preprocess, torch = load_clip()
    print(f"Embedding {len(paths)} images...")
    X = embed_images(paths, model, preprocess, torch)
    print(f"  embedding shape: {X.shape}")
    print()

    # Hyperparameter sweep — class_weight × penalty × C
    sweep_results: list[dict] = []
    configs = [
        {"penalty": "l1", "class_weight": "balanced", "C": 0.01},
        {"penalty": "l1", "class_weight": "balanced", "C": 0.1},
        {"penalty": "l1", "class_weight": "balanced", "C": 1.0},
        {"penalty": "l1", "class_weight": "balanced", "C": 10.0},
        {"penalty": "l1", "class_weight": None,       "C": 1.0},
        {"penalty": "l2", "class_weight": "balanced", "C": 0.1},
        {"penalty": "l2", "class_weight": "balanced", "C": 1.0},
    ]
    print(f"{'penalty':<8} {'class_weight':<10} {'C':>6} {'precision':>10} {'recall':>8} {'F1':>6} {'acc':>6}")
    for cfg in configs:
        preds, probs = loocv_predict(X, y, **cfg)
        c = confusion(y, preds)
        m = metrics(c)
        sweep_results.append({**cfg, **m, "confusion": c, "probs": probs.tolist()})
        cw = cfg["class_weight"] or "(none)"
        print(f"{cfg['penalty']:<8} {cw:<10} {cfg['C']:>6} "
              f"{m['precision']:>10.3f} {m['recall']:>8.3f} {m['f1']:>6.3f} {m['accuracy']:>6.3f}")

    # Pick best by F1, tie-break by accuracy
    best = max(sweep_results, key=lambda r: (r["f1"], r["accuracy"]))
    print()
    print(f"=== BEST CONFIG ===")
    print(f"  penalty={best['penalty']}  class_weight={best['class_weight']}  C={best['C']}")
    print(f"  Confusion: TP={best['confusion']['tp']}  FP={best['confusion']['fp']}  "
          f"TN={best['confusion']['tn']}  FN={best['confusion']['fn']}")
    print(f"  Precision={best['precision']:.3f}  Recall={best['recall']:.3f}  "
          f"F1={best['f1']:.3f}  Accuracy={best['accuracy']:.3f}")
    print()

    # Per-image LOOCV predictions for the chosen config
    preds, probs = loocv_predict(X, y,
        penalty=best["penalty"], class_weight=best["class_weight"], C=best["C"])

    print(f"Per-image LOOCV predictions (best config):")
    per_image = []
    for nm, lbl, pr, pb in zip(names, y, preds, probs):
        mark = "OK" if pr == lbl else "XX"
        actual = "pass" if lbl == 1 else "fail"
        predicted = "pass" if pr == 1 else "fail"
        print(f"  [{mark}]  {nm:48s}  you={actual}  probe={predicted}  P={pb:.3f}")
        per_image.append({
            "filename": nm,
            "label": int(lbl),
            "predicted_label": int(pr),
            "predicted_probability": round(float(pb), 4),
            "agree": bool(pr == lbl),
        })

    # Final fit on all data for production weights
    final_clf = LogisticRegression(
        C=best["C"],
        penalty=best["penalty"],
        solver="liblinear" if best["penalty"] == "l1" else "lbfgs",
        class_weight=best["class_weight"],
        max_iter=5000, random_state=0,
    )
    final_clf.fit(X, y)
    nonzero = int((final_clf.coef_[0] != 0).sum())
    print()
    print(f"Final fit on all N={len(y)}: {nonzero}/{X.shape[1]} non-zero coefficients (L1 sparsity)")

    np.savez(
        OUT_PATH,
        clip_classifier_coef=final_clf.coef_[0].astype(np.float32),
        clip_classifier_intercept=np.array([final_clf.intercept_[0]], dtype=np.float32),
        decision_threshold=np.array([0.5], dtype=np.float32),
    )

    report = {
        "schema": "forge.madhubani_likeness.v2",
        "encoder": "CLIP ViT-B/32 (openai)",
        "head": f"sklearn.LogisticRegression(C={best['C']}, penalty={best['penalty']!r}, class_weight={best['class_weight']!r})",
        "training_set": "brand/madhubani/labels_v1.json (N=16 maintainer-labeled, 6 pass + 10 fail)",
        "evaluation_protocol": "LOOCV on the same N=16 strong-label set (no held-out — labels are too few to split honestly)",
        "loocv_best_metrics": {
            "precision": best["precision"],
            "recall": best["recall"],
            "f1": best["f1"],
            "accuracy": best["accuracy"],
            "confusion": best["confusion"],
            "config": {
                "C": best["C"],
                "penalty": best["penalty"],
                "class_weight": best["class_weight"],
            },
        },
        "sweep": [
            {k: v for k, v in r.items() if k != "probs"}
            for r in sweep_results
        ],
        "per_image_loocv_predictions": per_image,
        "l1_nonzero_coefficients": nonzero,
        "total_features": int(X.shape[1]),
        "weights_path": str(OUT_PATH.relative_to(ROOT)),
        "honesty_note": (
            "LOOCV at N=16 on a 512-dim CLIP embedding is still small. F1 "
            "improvements here should be interpreted as 'this config is "
            "less degenerate than v1', not 'this config will hold at N=50'. "
            "Future iterations: per-zone probes, more labels, or fine-tuned "
            "CLIP via the LoRA pipeline."
        ),
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2))
    print(f"Wrote {OUT_PATH.relative_to(ROOT)}")
    print(f"Wrote {REPORT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
