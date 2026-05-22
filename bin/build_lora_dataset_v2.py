#!/usr/bin/env python3
"""Build the LoRA-v2 training dataset from user-graded PASS images.

This is the overnight-pilot dataset builder. Unlike the smoke-test pilot
(`bin/forge_madhubani_lora.py`) which trained on Wikimedia reference
paintings, this builder uses the **user's PASS-graded model outputs**
plus their winning prompts — so the LoRA learns the user's specific
aesthetic register, not a heterogeneous mix of Mithila styles.

Two input modes (use whichever is current):

  1. `--labels brand/madhubani/labels_v1.json`
       Existing label manifest with `entries: [{filename, label, path,
       rationale, md5}, ...]`.  Use this before fresh grading lands.

  2. `--votes <user-export.json> --summary <_batch_summary.json>`
       Fresh from `_contact_sheet.html` export. Joins user's vote
       (slug → pass/fail/skip) with the batch summary's winner_path
       to produce a synthetic labels manifest under
       `brand/madhubani/labels_v2.json`.

Held-out species (from `brand/madhubani/lora_v1_holdout.json`) are
ALWAYS excluded from the training set so the eval can measure
true style transfer rather than memorization.

Outputs:
  training/madhubani_lora_v2/
    images/
      <slug>.png         # symlinked source render (or copy if --copy)
      <slug>.txt         # short style-key + subject caption
      preview.txt        # held-out species 1 preview (for in-training samples)
      preview_<n>.txt    # additional held-out previews
    train.json           # mflux-train config (z-image-turbo, ~750 iter, rank 16)
    DATASET.md           # provenance + license summary
    HELD_OUT.json        # copy of lora_v1_holdout.json (eval contract)
    MANIFEST.json        # {samples: [...], held_out: [...]} — eval references this

Usage:
  # After grading lands (most common path tonight):
  python3 bin/build_lora_dataset_v2.py \
      --votes /Users/Rohan/Downloads/v4_user_votes_2026-05-20.json \
      --summary generated/madhubani_animals/v4/_batch_summary.json \
      --emit-labels brand/madhubani/labels_v2.json

  # Then validate the emitted mflux-train config:
  mflux-train --config training/madhubani_lora_v2/train.json --dry-run

  # Then real training (overnight):
  mflux-train --config training/madhubani_lora_v2/train.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]

DEFAULT_OUT = ROOT / "training/madhubani_lora_v2"
HOLDOUT_PATH = ROOT / "brand/madhubani/lora_v1_holdout.json"
ANIMALS_PATH = ROOT / "brand/madhubani/animals.json"
RUNS_LEDGER = ROOT / "brand/madhubani/learning/runs.jsonl"

# Short style-key caption — what the LoRA learns to associate the
# rendered images with. Kept under 100 tokens so it fits in the
# z-image-turbo text encoder without truncation.
STYLE_KEY = (
    "a madhubani folk art painting in the mithila tradition of bihar, india: "
    "double-line black outlines, flat folk-color panels in indigo and vermillion "
    "and saffron, seven ornamental decoration zones on the body, almond eyes with "
    "watchful ceremonial gravity, no naturalistic species coloring."
)


@dataclass
class TrainingSample:
    slug: str
    display_name: str
    body_type: str
    src_image: Path
    dst_image: Path
    dst_caption: Path
    caption: str
    md5: str
    rationale: str = ""
    winning_prompt_hash: Optional[str] = None
    winning_composite: Optional[float] = None


@dataclass
class DatasetSummary:
    pass_total: int = 0
    held_out_excluded: int = 0
    missing_images: list[str] = field(default_factory=list)
    no_winning_prompt: list[str] = field(default_factory=list)


# ──────────────────────────────────────────────────────────────────────
# 1. Input adapters: labels-mode and votes-mode
# ──────────────────────────────────────────────────────────────────────


def load_held_out_slugs() -> set[str]:
    payload = json.loads(HOLDOUT_PATH.read_text())
    return {x["slug"] for x in payload["held_out_species"]}


def load_animals_index() -> dict[str, dict]:
    payload = json.loads(ANIMALS_PATH.read_text())
    return {a["slug"]: a for a in payload["animals"]}


def labels_from_manifest(labels_path: Path) -> list[dict]:
    """Adapter for `brand/madhubani/labels_v?.json`."""
    payload = json.loads(labels_path.read_text())
    entries = payload.get("entries", [])
    pass_entries = [e for e in entries if e.get("label") == "pass"]
    # Slugify: take filename stem, strip version/style suffixes.
    for e in pass_entries:
        stem = Path(e["filename"]).stem
        # 'elephant_v2', 'peacock_v1_plumage_ideal' → 'elephant', 'peacock'
        # Take the first underscore-delimited token that looks like a species.
        e["_derived_slug"] = stem.split("_")[0].lower()
    return pass_entries


def labels_from_votes(votes_path: Path, summary_path: Path,
                      emit_labels: Optional[Path] = None) -> list[dict]:
    """Adapter for {votes.json, _batch_summary.json}. Detects the export
    schema version and dispatches: v2/v3 (per-species winner votes) or
    v4 (per-image votes with attempt + seed). Returns labels entries.
    """
    votes_payload = json.loads(votes_path.read_text())
    schema = votes_payload.get("schema", "")
    if schema == "forge.user_grading.v4":
        return _labels_from_votes_v4(votes_payload, summary_path, emit_labels)
    # v2 / v3 / unknown → fall back to per-species winner logic
    return _labels_from_votes_v2(votes_payload, summary_path, emit_labels)


def _labels_from_votes_v4(votes_payload: dict, summary_path: Path,
                          emit_labels: Optional[Path] = None) -> list[dict]:
    """v4 schema: per-image PASS/FAIL votes. Each PASS becomes one
    training-set entry. Render paths are reconstructed from
    `_batch_summary.json`'s reasoning_result_path per species (the
    contact-sheet's render_path field carries embedded base64, not
    on-disk paths — we ignore it here)."""
    summary_payload = json.loads(summary_path.read_text())
    # Build slug → v4-session dir (parent of reasoning_result.json)
    slug_to_session: dict[str, Path] = {}
    for s in summary_payload.get("statuses", []):
        slug = s.get("slug")
        rrp = s.get("reasoning_result_path", "")
        if not slug or not rrp:
            continue
        rr_abs = (ROOT / rrp) if not Path(rrp).is_absolute() else Path(rrp)
        slug_to_session[slug] = rr_abs.parent
    entries = []
    skipped_missing = []
    for v in votes_payload.get("votes", []):
        if v.get("vote") != "pass":
            continue
        slug = v.get("slug")
        attempt = v.get("attempt")
        seed = v.get("seed")
        if slug is None or attempt is None or seed is None:
            continue
        session = slug_to_session.get(slug)
        if not session:
            continue
        # Match the on-disk convention: attempt_<NN>/seed<NN>.png
        path = session / f"attempt_{int(attempt):02d}" / f"seed{int(seed):02d}.png"
        if not path.exists():
            skipped_missing.append(str(path))
            continue
        try:
            rel_path = str(path.relative_to(ROOT))
        except ValueError:
            rel_path = str(path)
        md5 = ""
        try:
            md5 = hashlib.md5(path.read_bytes()).hexdigest()
        except Exception:
            pass
        entries.append({
            "filename": f"{slug}__a{int(attempt):02d}_s{int(seed):02d}.png",
            "label": "pass",
            "md5": md5,
            "path": rel_path,
            "rationale": (
                f"v4 user-PASS · attempt {attempt} seed {seed} · "
                f"composite {v.get('composite','?')} · "
                f"picker_pick={v.get('is_picker_winner')} · "
                f"my_pick={v.get('is_my_winner')}"
            ),
            "_derived_slug": slug,
            "_attempt": int(attempt),
            "_seed": int(seed),
        })
    if skipped_missing:
        print(f"  WARN: {len(skipped_missing)} PASS votes had missing on-disk images:",
              file=sys.stderr)
        for p in skipped_missing[:5]:
            print(f"    - {p}", file=sys.stderr)
    if emit_labels:
        emit_labels.parent.mkdir(parents=True, exist_ok=True)
        emit_labels.write_text(json.dumps({
            "schema": "forge.madhubani_labels.v2",
            "version": "2.0.0",
            "established": votes_payload.get("ts", "unknown"),
            "labeler": "Rohan Ramekar (v4 contact-sheet export, per-image votes)",
            "source_schema": "forge.user_grading.v4",
            "n_pass": len(entries),
            "n_total": len(entries),
            "n_skipped_missing_on_disk": len(skipped_missing),
            "description": (
                "User-graded PASS labels from v4 contact-sheet export "
                "(per-image votes across all 146 renders). Built by "
                "bin/build_lora_dataset_v2.py via forge.user_grading.v4."
            ),
            "entries": entries,
        }, indent=2))
        try:
            print(f"  emitted labels manifest → {emit_labels.relative_to(ROOT)}", file=sys.stderr)
        except ValueError:
            print(f"  emitted labels manifest → {emit_labels}", file=sys.stderr)
    return entries


def _labels_from_votes_v2(votes_payload: dict, summary_path: Path,
                          emit_labels: Optional[Path] = None) -> list[dict]:
    """v2/v3 schema: per-species winner votes. Each species' PASS becomes
    one entry with the picker's winner_path."""
    summary_payload = json.loads(summary_path.read_text())
    slug_to_winner = {
        s["slug"]: s for s in summary_payload.get("statuses", [])
        if s.get("winner_path")
    }
    entries = []
    for v in votes_payload.get("votes", []):
        slug = v.get("slug")
        vote = v.get("vote", "skip")
        if vote != "pass":
            continue
        st = slug_to_winner.get(slug)
        if not st:
            continue
        winner_abs = Path(st["winner_path"])
        try:
            winner_path = str(winner_abs.relative_to(ROOT))
        except ValueError:
            winner_path = str(winner_abs)
        md5 = ""
        try:
            md5 = hashlib.md5(winner_abs.read_bytes()).hexdigest() if winner_abs.exists() else ""
        except Exception:
            pass
        entries.append({
            "filename": winner_abs.name,
            "label": "pass",
            "md5": md5,
            "path": winner_path,
            "rationale": f"v4 batch user-PASS — composite {st.get('winner_composite','?')}",
            "_derived_slug": slug,
        })
    if emit_labels:
        emit_labels.parent.mkdir(parents=True, exist_ok=True)
        emit_labels.write_text(json.dumps({
            "schema": "forge.madhubani_labels.v2",
            "version": "2.0.0",
            "established": votes_payload.get("ts", "unknown"),
            "labeler": "Rohan Ramekar (v4 contact-sheet export)",
            "n_pass": len([e for e in entries if e["label"] == "pass"]),
            "n_total": len(entries),
            "description": (
                "User-graded PASS labels from v4 contact-sheet export. "
                "Joined with `_batch_summary.json` to recover the winner_path "
                "per species. Built by bin/build_lora_dataset_v2.py."
            ),
            "entries": entries,
        }, indent=2))
        try:
            print(f"  emitted labels manifest → {emit_labels.relative_to(ROOT)}", file=sys.stderr)
        except ValueError:
            print(f"  emitted labels manifest → {emit_labels}", file=sys.stderr)
    return entries


# ──────────────────────────────────────────────────────────────────────
# 2. Sample assembly
# ──────────────────────────────────────────────────────────────────────


def load_winning_prompts() -> dict[str, dict]:
    """Index `runs.jsonl` → best (highest-composite, accepted=True) per slug."""
    best: dict[str, dict] = {}
    if not RUNS_LEDGER.exists():
        return best
    with RUNS_LEDGER.open() as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            slug = rec.get("animal_slug")
            comp = rec.get("composite")
            if slug is None or comp is None:
                continue
            cur = best.get(slug)
            if cur is None or comp > cur.get("composite", -1):
                best[slug] = rec
    return best


def caption_for(animal: dict) -> str:
    """Short conditioning caption: style key + subject. Stays under
    100 tokens so the z-image-turbo text encoder doesn't truncate."""
    display = animal.get("display_name") or animal["slug"]
    body = animal.get("body_type", "")
    pose = "side profile, standing alert"
    return (
        f"{STYLE_KEY} a {display.lower()} ({body}), {pose}, "
        f"centered composition on cream background."
    )


def assemble_samples(
    pass_entries: list[dict],
    held_out: set[str],
    animals_idx: dict[str, dict],
    winning_prompts: dict[str, dict],
    out_image_dir: Path,
) -> tuple[list[TrainingSample], DatasetSummary]:
    summary = DatasetSummary()
    summary.pass_total = len(pass_entries)
    seen_filenames: set[str] = set()
    samples: list[TrainingSample] = []
    for entry in pass_entries:
        slug = entry.get("_derived_slug") or Path(entry["filename"]).stem.split("_")[0]
        if slug in held_out:
            summary.held_out_excluded += 1
            continue
        animal = animals_idx.get(slug, {"slug": slug, "display_name": slug, "body_type": "?"})
        src = Path(entry["path"])
        if not src.is_absolute():
            src = ROOT / src
        if not src.exists():
            summary.missing_images.append(str(src))
            continue
        # Deduplicate by filename (which is unique for v4 per-image entries
        # like elephant__a01_s02.png, but stays sane for v2 manifests too).
        fname = entry.get("filename") or src.name
        if fname in seen_filenames:
            continue
        seen_filenames.add(fname)
        winning = winning_prompts.get(slug)
        ext = src.suffix.lower() or ".png"
        # If filename already carries attempt/seed (v4), use it as the dst stem.
        # Otherwise fall back to slug (v2/v3 — one image per species).
        stem = Path(fname).stem if "__a" in fname else slug
        dst_image = out_image_dir / f"{stem}{ext}"
        dst_caption = out_image_dir / f"{stem}.txt"
        samples.append(TrainingSample(
            slug=slug,
            display_name=animal.get("display_name", slug),
            body_type=animal.get("body_type", "?"),
            src_image=src,
            dst_image=dst_image,
            dst_caption=dst_caption,
            caption=caption_for(animal),
            md5=entry.get("md5", ""),
            rationale=entry.get("rationale", ""),
            winning_prompt_hash=(winning or {}).get("prompt_hash"),
            winning_composite=(winning or {}).get("composite"),
        ))
        if winning is None:
            summary.no_winning_prompt.append(slug)
    return samples, summary


# ──────────────────────────────────────────────────────────────────────
# 3. Output writers
# ──────────────────────────────────────────────────────────────────────


def materialize_dataset(samples: list[TrainingSample], out_image_dir: Path,
                        copy_mode: bool) -> None:
    out_image_dir.mkdir(parents=True, exist_ok=True)
    for s in samples:
        if s.dst_image.exists() or s.dst_image.is_symlink():
            s.dst_image.unlink()
        if copy_mode:
            shutil.copy2(s.src_image, s.dst_image)
        else:
            os.symlink(s.src_image.resolve(), s.dst_image)
        s.dst_caption.write_text(s.caption, encoding="utf-8")


def write_preview_prompts(out_image_dir: Path) -> None:
    """Preview prompts test generalization to the held-out species
    during training. mflux-train renders these every
    `generate_image_frequency` steps so we can watch convergence."""
    held = json.loads(HOLDOUT_PATH.read_text())["held_out_species"]
    for i, h in enumerate(held):
        slug = h["slug"]
        prompt = (
            f"{STYLE_KEY} a {slug.replace('-', ' ')}, side profile, "
            f"standing alert, centered composition on cream background."
        )
        path = out_image_dir / ("preview.txt" if i == 0 else f"preview_{slug}.txt")
        path.write_text(prompt, encoding="utf-8")


def write_train_config(out_dir: Path) -> Path:
    """Emit the overnight z-image-turbo LoRA config.

    Design choices (documented for the morning post-mortem):
    - max_resolution: 512 → matches smoke-pilot proven path; ~30-60s per
      iteration on M5 Max so 750 iterations finishes in ~5-9 hrs.
    - num_epochs: 30 → with ~25 training images, yields ~750 iterations.
      Enough to see real loss reduction without overrunning the overnight
      window.
    - LoRA targets: CROSS-ATTENTION ONLY (to_q, to_k, to_v, to_out) at
      rank 16. Style lives in cross-attention; restricting targets reduces
      overfit surface relative to the smoke pilot's full attention+ffn
      coverage. Skipping feed_forward, cap_embedder, and final_layer.
    - learning_rate: 1e-4 → standard LoRA initial LR.
    - checkpoints: every 100 iter → ~7 checkpoints across the run, lets
      us pick the best at morning rather than relying on the final one.
    - preview_frequency: every 100 iter → in-training samples for all 4
      held-out species so we can watch generalization land.
    """
    config = {
        "model": "z-image-turbo",
        "data": "images",
        "seed": 42,
        "steps": 9,                # inference steps for preview generation
        "guidance": 0.0,
        "quantize": 4,
        "max_resolution": 512,
        "low_ram": False,
        "training_loop": {
            "num_epochs": 30,
            "batch_size": 1,
            "timestep_low": 4,
            "timestep_high": 9,
        },
        "optimizer": {
            "name": "AdamW",
            "learning_rate": 1e-4,
        },
        "checkpoint": {
            "save_frequency": 100,
            "output_path": "training",
        },
        "monitoring": {
            "preview_width": 512,
            "preview_height": 512,
            "plot_frequency": 10,
            "generate_image_frequency": 100,
            "smooth_loss": True,
            "smooth_loss_window": 10,
        },
        "lora_layers": {
            "targets": [
                {"module_path": "layers.{block}.attention.to_q",     "blocks": {"start": 0, "end": 30}, "rank": 16},
                {"module_path": "layers.{block}.attention.to_k",     "blocks": {"start": 0, "end": 30}, "rank": 16},
                {"module_path": "layers.{block}.attention.to_v",     "blocks": {"start": 0, "end": 30}, "rank": 16},
                {"module_path": "layers.{block}.attention.to_out.0", "blocks": {"start": 0, "end": 30}, "rank": 16},
            ],
        },
    }
    config_path = out_dir / "train.json"
    config_path.write_text(json.dumps(config, indent=2))
    return config_path


def write_held_out_copy(out_dir: Path) -> None:
    """Copy the held-out config alongside the dataset so the eval script
    has a self-contained reference."""
    shutil.copy2(HOLDOUT_PATH, out_dir / "HELD_OUT.json")


def write_manifest(out_dir: Path, samples: list[TrainingSample],
                   summary: DatasetSummary) -> None:
    payload = {
        "schema": "forge.lora_dataset_manifest.v1",
        "n_training_samples": len(samples),
        "n_pass_input": summary.pass_total,
        "n_held_out_excluded": summary.held_out_excluded,
        "n_missing_images": len(summary.missing_images),
        "missing_images": summary.missing_images,
        "no_winning_prompt": summary.no_winning_prompt,
        "samples": [
            {
                "slug": s.slug,
                "display_name": s.display_name,
                "body_type": s.body_type,
                "src_image": (str(s.src_image.relative_to(ROOT)) if s.src_image.is_relative_to(ROOT) else str(s.src_image)),
                "dst_image": (str(s.dst_image.relative_to(ROOT)) if s.dst_image.is_relative_to(ROOT) else str(s.dst_image)),
                "caption": s.caption,
                "md5": s.md5,
                "winning_composite": s.winning_composite,
                "rationale": s.rationale,
            }
            for s in samples
        ],
    }
    (out_dir / "MANIFEST.json").write_text(json.dumps(payload, indent=2))


def write_dataset_md(out_dir: Path, samples: list[TrainingSample],
                     summary: DatasetSummary) -> None:
    lines = [
        "# Madhubani LoRA-v2 training dataset",
        "",
        f"**Training samples:** {len(samples)}",
        f"**Excluded (held-out):** {summary.held_out_excluded}",
        f"**Source label pool:** {summary.pass_total} PASS images",
        "",
        "Built by `bin/build_lora_dataset_v2.py` from user-graded PASS",
        "labels. Each training image is the model's own render that the",
        "user marked PASS — NOT a Wikimedia reference painting. The LoRA",
        "therefore learns the user's curated subset of the base model's",
        "distribution.",
        "",
        "## Held-out species (not in training)",
        "",
    ]
    for h in json.loads(HOLDOUT_PATH.read_text())["held_out_species"]:
        lines.append(f"- `{h['slug']}` — {h['user_verdict']}")
    lines.extend([
        "",
        "## Caption template",
        "",
        "Every training image gets a short caption built from a shared",
        "style key plus the species' display name and body type. This is",
        "intentionally simpler than the verbose 1000-token rendering prompts —",
        "the LoRA needs to generalize the style cue across many subjects,",
        "not memorize a specific prompt.",
        "",
        "```",
        STYLE_KEY,
        "```",
        "",
        "## Samples",
        "",
        "| Slug | Body | Composite (winner) | MD5 |",
        "| :--- | :--- | :--- | :--- |",
    ])
    for s in samples:
        comp = f"{s.winning_composite:.4f}" if s.winning_composite is not None else "—"
        lines.append(f"| `{s.slug}` | {s.body_type} | {comp} | `{s.md5[:8]}…` |")
    if summary.missing_images:
        lines.extend([
            "",
            "## Warnings",
            "",
            f"- **{len(summary.missing_images)} PASS images missing on disk** — see MANIFEST.json",
        ])
    if summary.no_winning_prompt:
        lines.extend([
            f"- **{len(summary.no_winning_prompt)} species without a winning prompt in runs.jsonl** — captions fall back to the shared template:",
            "  " + ", ".join(summary.no_winning_prompt),
        ])
    (out_dir / "DATASET.md").write_text("\n".join(lines) + "\n")


# ──────────────────────────────────────────────────────────────────────
# 4. Driver
# ──────────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--labels", type=Path,
                     help="Existing labels manifest (e.g., brand/madhubani/labels_v1.json)")
    src.add_argument("--votes", type=Path,
                     help="Fresh contact-sheet export JSON (votes mode)")
    parser.add_argument("--summary", type=Path,
                        help="Batch summary JSON (required with --votes)")
    parser.add_argument("--emit-labels", type=Path,
                        help="If set, also emit a labels manifest at this path (votes mode only)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"Output directory (default: {DEFAULT_OUT.relative_to(ROOT)})")
    parser.add_argument("--force", action="store_true",
                        help="Remove existing output directory first")
    parser.add_argument("--copy", action="store_true",
                        help="Copy images instead of symlinking (use if symlinks break mflux-train)")
    args = parser.parse_args()

    if args.votes and not args.summary:
        parser.error("--summary is required with --votes")

    out_dir = args.out.resolve()
    out_image_dir = out_dir / "images"

    held_out = load_held_out_slugs()
    animals_idx = load_animals_index()
    winning_prompts = load_winning_prompts()

    print(f"Loaded {len(animals_idx)} species index entries", file=sys.stderr)
    print(f"Loaded {len(winning_prompts)} winning prompts from runs.jsonl", file=sys.stderr)
    print(f"Held-out species: {sorted(held_out)}", file=sys.stderr)

    if args.labels:
        labels_abs = args.labels.resolve()
        pass_entries = labels_from_manifest(labels_abs)
        try:
            print(f"Mode: labels-manifest ({labels_abs.relative_to(ROOT)})", file=sys.stderr)
        except ValueError:
            print(f"Mode: labels-manifest ({labels_abs})", file=sys.stderr)
    else:
        pass_entries = labels_from_votes(args.votes.resolve(), args.summary.resolve(), args.emit_labels)
        print(f"Mode: votes ({args.votes.name})", file=sys.stderr)
    print(f"Found {len(pass_entries)} PASS entries", file=sys.stderr)

    samples, summary = assemble_samples(
        pass_entries, held_out, animals_idx, winning_prompts, out_image_dir,
    )
    print(f"  → {len(samples)} training samples (after held-out exclusion + dedup)", file=sys.stderr)
    if summary.held_out_excluded:
        print(f"  → {summary.held_out_excluded} excluded as held-out", file=sys.stderr)
    if summary.missing_images:
        print(f"  → WARN {len(summary.missing_images)} source images missing on disk", file=sys.stderr)

    if len(samples) < 10:
        print(f"\nERROR: only {len(samples)} training samples — need ≥10 for a meaningful LoRA.",
              file=sys.stderr)
        return 1
    if len(samples) < 20:
        print(f"\nWARN: only {len(samples)} training samples — LoRA may be undertrained.",
              file=sys.stderr)

    if out_dir.exists() and args.force:
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    materialize_dataset(samples, out_image_dir, copy_mode=args.copy)
    write_preview_prompts(out_image_dir)
    write_held_out_copy(out_dir)
    config_path = write_train_config(out_dir)
    write_manifest(out_dir, samples, summary)
    write_dataset_md(out_dir, samples, summary)

    print(file=sys.stderr)
    print(f"Wrote dataset to {out_dir.relative_to(ROOT)}/", file=sys.stderr)
    print(f"  {len(samples)} training images + captions in images/", file=sys.stderr)
    print(f"  config: {config_path.relative_to(ROOT)}", file=sys.stderr)
    print(f"  manifest: {(out_dir / 'MANIFEST.json').relative_to(ROOT)}", file=sys.stderr)
    print(file=sys.stderr)
    print("Next steps:", file=sys.stderr)
    print(f"  mflux-train --config {config_path.relative_to(ROOT)} --dry-run", file=sys.stderr)
    print(f"  mflux-train --config {config_path.relative_to(ROOT)}", file=sys.stderr)
    print(f"  python3 bin/eval_lora.py <path-to-adapter.safetensors>", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
