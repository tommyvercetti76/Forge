#!/usr/bin/env python3
"""Build the complete grading UI for the v4 batch — rich, click-driven.

Reads `generated/madhubani_animals/v4/_batch_summary.json` AND each
species' `reasoning_result.json` to surface EVERY rendered image
(not just the picker's winners). For 41 species × 2-6 attempts × 2
seeds each ≈ **146 graded cards**, grouped by species with the
picker's winner badged so you can see whether you agree with C.1.

Per card you can:
  - 320×320 thumbnail, click-to-open full resolution
  - PASS / FAIL / SKIP vote buttons (big click targets)
  - Diagnostic reason chips (pass reasons differ from fail reasons)
  - Species-feature checklist (shows on anatomy_broken/species_mismatch)
  - Per-image free-text notes
  - 🏆 "my pick" toggle (mark your preferred winner per species —
    diverges from the composite picker so we can measure C.1 accuracy)

Plus toolbar:
  - Progress bar (X/146 graded · N pass · N fail · N skip)
  - Filter (all / ungraded / passed / failed / skipped / picker-disagrees)
  - Sort within species (composite desc/asc / attempt order)
  - Keyboard shortcuts (P/F/S vote, J/K navigate, 1-9 toggle chips,
    W toggle "my pick", ⌘E export)
  - localStorage persistence — refresh-safe, keyed by batch start ts
  - Export emits `forge.user_grading.v4` schema (per-image votes
    with attempt + seed + composite + my-winner annotations),
    consumable by `bin/build_lora_dataset_v2.py --votes <export>`

All assets (CSS, JS, images) are inlined as data: URLs so the file is
portable — works opened from anywhere via `open`.

Usage:
  python3 bin/build_v4_contact_sheet.py
  open generated/madhubani_animals/v4/_contact_sheet.html

  # Or while the batch is still in flight (uses the partial summary):
  python3 bin/build_v4_contact_sheet.py
"""

from __future__ import annotations

import argparse
import base64
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V4_ROOT = ROOT / "generated/madhubani_animals/v4"
SUMMARY_PATH = V4_ROOT / "_batch_summary.json"
OUT_PATH = V4_ROOT / "_contact_sheet.html"
FEATURES_PATH = ROOT / "brand/madhubani/species_features.json"
ANIMALS_PATH = ROOT / "brand/madhubani/animals.json"

THUMB_SIZE = 360  # px, max dimension (smaller than v2 because 3.5× more cards)
FULL_SIZE = 1024  # px, click-to-expand modal size


# ──────────────────────────────────────────────────────────────────────
# Reason chips. Each entry is (id, label, hint). The id is what gets
# serialized in the export JSON. The hint shows on hover.
# ──────────────────────────────────────────────────────────────────────

PASS_REASONS = [
    ("style",         "Style",          "Madhubani folk-art register correct"),
    ("palette",       "Palette",        "Saturated indigo / vermillion / saffron"),
    ("anatomy",       "Anatomy",        "Species recognizable + features correct"),
    ("decoration",    "Decoration",     "7 ornamental zones intact, not all-over"),
    ("eyes",          "Eyes",           "Almond folk-eye, watchful"),
    ("gold_standard", "Gold standard",  "Reference quality for this species"),
]

FAIL_REASONS = [
    ("photoreal",        "Photoreal",        "Too 3D / shaded / wildlife-photo register"),
    ("cartoon",          "Cartoon",          "Mascot or chibi, not folk"),
    ("wrong_palette",    "Wrong palette",    "Natural species colors instead of indigo body fill"),
    ("anatomy_broken",   "Anatomy broken",   "Missing / wrong features (tail, legs, horns)"),
    ("no_zones",         "No zones",         "Body bare OR all-over textile pattern"),
    ("cartoon_eyes",     "Cartoon eyes",     "Round Disney eyes instead of almond"),
    ("silhouette",       "Silhouette",       "Body fill not saturated (just outline)"),
    ("wrong_style",      "Wrong style",      "Different folk tradition or generic stylized"),
    ("species_mismatch", "Species mismatch", "Doesn't read as the labeled species"),
    ("other",            "Other",            "See notes field"),
]


# ──────────────────────────────────────────────────────────────────────
# Species feature registry — drives the per-card fidelity checklist
# ──────────────────────────────────────────────────────────────────────


def load_species_features() -> dict:
    """Return {schema, species: {slug: [feature_dicts]}, generic_by_body_type: {...}}.
    Falls back to a minimal empty registry if the file is missing so the
    contact sheet still builds."""
    if not FEATURES_PATH.exists():
        return {"species": {}, "generic_features_by_body_type": {"default": []}}
    try:
        return json.loads(FEATURES_PATH.read_text())
    except Exception as exc:
        print(f"  ! species_features.json malformed: {exc} — continuing with empty registry")
        return {"species": {}, "generic_features_by_body_type": {"default": []}}


def features_for(slug: str, body_type: str, registry: dict) -> list[dict]:
    """Resolve features for one species. Prefer the species-specific list;
    fall back to the body-type generic list; finally fall back to the
    default generic list."""
    species_map = registry.get("species", {})
    if slug in species_map:
        return species_map[slug]
    generic = registry.get("generic_features_by_body_type", {})
    if body_type in generic:
        return generic[body_type]
    return generic.get("default", [])


# ──────────────────────────────────────────────────────────────────────
# Enumerate ALL rendered images for each species from per-species
# reasoning_result.json files. Returns one card record per (slug,
# attempt, seed) tuple — 3.5× the data the legacy "winners-only"
# sheet showed.
# ──────────────────────────────────────────────────────────────────────


def enumerate_renders(summary: dict) -> dict[str, list[dict]]:
    """For each species in the batch summary, walk the v4 session's
    reasoning_result.json and produce a list of card-record dicts
    (one per non-transparent render). Returns {slug: [records]}.
    """
    by_species: dict[str, list[dict]] = {}
    for status in summary.get("statuses", []):
        slug = status.get("slug")
        rrp = status.get("reasoning_result_path")
        if not slug or not rrp:
            continue
        rr_path = (ROOT / rrp) if not Path(rrp).is_absolute() else Path(rrp)
        if not rr_path.exists():
            continue
        try:
            rr = json.loads(rr_path.read_text())
        except Exception:
            continue
        picker_winner_path = (rr.get("winner") or {}).get("path") or status.get("winner_path", "")
        records: list[dict] = []
        seen_paths: set[str] = set()
        for att in rr.get("attempts", []):
            att_n = att.get("attempt")
            for r in att.get("ranked", []):
                path = r.get("path", "")
                if not path or path.endswith(".transparent.png"):
                    continue
                # Some sessions list the same render twice (winner + ranked entry).
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                abs_path = (ROOT / path) if not Path(path).is_absolute() else Path(path)
                records.append({
                    "slug": slug,
                    "display_name": status.get("display_name", slug),
                    "body_type": status.get("body_type", "?"),
                    "park": status.get("park", ""),
                    "attempt": att_n,
                    "seed": r.get("seed"),
                    "render_path": str(abs_path),
                    "composite": r.get("composite"),
                    "rubric_pass_fraction": r.get("rubric_pass_fraction"),
                    "clip_likeness_probability": r.get("clip_likeness_probability"),
                    "auto_qc_pass": r.get("auto_qc_pass"),
                    "is_picker_winner": (path == picker_winner_path
                                         or str(abs_path) == picker_winner_path),
                    "card_id": f"{slug}__a{att_n:02d}_s{r.get('seed', 0):02d}",
                    "failed_checks": (r.get("qc_summary") or {}).get("failed_checks", []),
                })
        # Sort within species by attempt asc, then seed asc
        records.sort(key=lambda r: ((r["attempt"] or 0), (r["seed"] or 0)))
        if records:
            by_species[slug] = records
    return by_species


# ──────────────────────────────────────────────────────────────────────
# Image embedding
# ──────────────────────────────────────────────────────────────────────


def thumb_data_url(png_path: Path, max_dim: int = THUMB_SIZE) -> str | None:
    """Read a PNG, resize to max_dim, encode as data: URL. Returns None
    if the file is missing or PIL is absent."""
    if not png_path or not png_path.exists():
        return None
    try:
        from PIL import Image
        img = Image.open(png_path).convert("RGB")
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        import io
        buf = io.BytesIO()
        img.save(buf, "PNG", optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception as exc:
        print(f"  ! thumb failed for {png_path.name}: {exc}")
        return None


def full_data_url(png_path: Path, max_dim: int = FULL_SIZE) -> str | None:
    """A larger version used when the user clicks the thumb. Same
    embedding strategy so the file stays self-contained."""
    if not png_path or not png_path.exists():
        return None
    try:
        from PIL import Image
        img = Image.open(png_path).convert("RGB")
        img.thumbnail((max_dim, max_dim), Image.LANCZOS)
        import io
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=88, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return None


# ──────────────────────────────────────────────────────────────────────
# HTML builder — kept in one place so the structure is auditable
# ──────────────────────────────────────────────────────────────────────


def build_card(rec: dict, features_registry: dict) -> str:
    slug = rec["slug"]
    body = rec.get("body_type", "?")
    attempt = rec.get("attempt")
    seed = rec.get("seed")
    comp = rec.get("composite")
    is_winner = rec.get("is_picker_winner")
    render_path = rec.get("render_path", "")
    card_id = rec["card_id"]

    thumb = thumb_data_url(Path(render_path)) if render_path else None
    full = full_data_url(Path(render_path)) if render_path else None
    thumb_src = thumb or ""
    full_src = full or thumb_src
    thumb_html = (
        f'<img class="thumb-img" src="{thumb_src}" data-full="{full_src}" '
        f'alt="{slug} a{attempt} s{seed}" loading="lazy">' if thumb_src
        else '<div class="missing">no render</div>'
    )

    winner_badge = (
        '<span class="badge ok" title="C.1 composite picker chose this as the species winner">🏆 picker pick</span>'
        if is_winner else ""
    )
    if comp is None:
        score_html = f'<span class="bad">no composite</span> {winner_badge}'
    else:
        score_html = (
            f'<span class="att-label">attempt {attempt}</span> '
            f'<span class="seed-label">seed {seed}</span> · '
            f'composite <b>{comp:.4f}</b> {winner_badge}'
        )

    pass_chips = "".join(
        f'<button type="button" class="chip chip-pass" data-reason="{rid}" '
        f'title="{hint}" tabindex="-1">{label}</button>'
        for rid, label, hint in PASS_REASONS
    )
    fail_chips = "".join(
        f'<button type="button" class="chip chip-fail" data-reason="{rid}" '
        f'title="{hint}" tabindex="-1">{label}</button>'
        for rid, label, hint in FAIL_REASONS
    )

    # Per-species fidelity checklist — shown when user clicks
    # "anatomy_broken" OR "species_mismatch" reason chip
    features = features_for(slug, body, features_registry)
    feature_chips = "".join(
        f'<button type="button" class="feat-chip" data-feature="{f["id"]}" '
        f'title="{f.get("prompt_clause","")[:140]}" tabindex="-1">'
        f'{f["label"]}</button>'
        for f in features
    )

    winner_class = " is-picker-winner" if is_winner else ""

    return f"""
    <article class="card{winner_class}" data-card-id="{card_id}" data-slug="{slug}"
             data-body="{body}" data-attempt="{attempt}" data-seed="{seed}"
             data-composite="{comp if comp is not None else -1}"
             data-picker-winner="{1 if is_winner else 0}"
             tabindex="0">
      <div class="thumb-wrap">{thumb_html}
        <button type="button" class="my-winner-btn" title="Mark as MY pick for this species (overrides picker)" tabindex="-1">🏆</button>
      </div>
      <div class="meta">
        <div class="score">{score_html}</div>
        <div class="vote-buttons" role="group" aria-label="Vote">
          <button type="button" class="vote vote-pass"  data-vote="pass">✓ PASS</button>
          <button type="button" class="vote vote-fail"  data-vote="fail">✗ FAIL</button>
          <button type="button" class="vote vote-skip"  data-vote="skip">? skip</button>
        </div>
        <div class="reasons reasons-pass" hidden>
          <div class="reason-label">why does it PASS?</div>
          <div class="chips">{pass_chips}</div>
        </div>
        <div class="reasons reasons-fail" hidden>
          <div class="reason-label">why does it FAIL?</div>
          <div class="chips">{fail_chips}</div>
        </div>
        <div class="features" hidden>
          <div class="reason-label">which species features failed? <span class="feat-hint">(tick all that apply)</span></div>
          <div class="feat-chips">{feature_chips}</div>
        </div>
        <textarea class="notes" placeholder="Notes (optional)" rows="1"></textarea>
      </div>
    </article>"""


def build_species_section(status: dict, records: list[dict], features_registry: dict) -> str:
    """Render one species' section: header + grid of all its attempt cards."""
    slug = status.get("slug", "?")
    display = status.get("display_name", slug)
    body = status.get("body_type", "?")
    park = status.get("park", "")
    n = len(records)
    composites = [r["composite"] for r in records if r.get("composite") is not None]
    if composites:
        comp_range = f"composite {min(composites):.3f}–{max(composites):.3f}"
    else:
        comp_range = "no composite"
    accepted = status.get("accepted")
    accepted_badge = (
        '<span class="badge ok">picker accepted</span>'
        if accepted else '<span class="badge warn">picker stopped@max</span>'
    )
    cards_html = "\n".join(build_card(r, features_registry) for r in records)
    return f"""
    <section class="species-section" data-slug="{slug}" data-body="{body}">
      <div class="species-header">
        <div class="species-title">
          <span class="species-name">{display}</span>
          <span class="species-sub"><code>{slug}</code> · {body} · {park}</span>
        </div>
        <div class="species-meta">
          <span class="species-count">{n} render{'s' if n != 1 else ''}</span>
          <span class="species-range">{comp_range}</span>
          {accepted_badge}
        </div>
      </div>
      <div class="grid">{cards_html}</div>
    </section>"""


CSS = """
:root {
  --bg: #F5EFE3; --fg: #1a2952; --muted: #6b6258;
  --ok: #3d7d3d; --ok-bg: #e6f0e6;
  --warn: #e87722; --warn-bg: #fbe7d6;
  --bad: #c8261f; --bad-bg: #fadbd9;
  --neutral: #b8aa8c;
  --card: #fff; --line: #d8cfb8; --line-strong: #1a2952;
  --shadow: 0 1px 3px rgba(26, 41, 82, 0.08);
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body {
  background: var(--bg); color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", "Segoe UI", sans-serif;
  font-size: 14px; line-height: 1.4;
}
header {
  position: sticky; top: 0; z-index: 50;
  background: var(--bg); border-bottom: 1px solid var(--line);
  padding: 12px 20px;
}
h1 { margin: 0 0 4px; font-size: 18px; font-weight: 700; }
.subtitle { color: var(--muted); font-size: 13px; margin-bottom: 10px; }
.progress-row { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.progress-bar { flex: 1; height: 8px; background: var(--line); border-radius: 4px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--fg); width: 0%; transition: width 0.2s; }
.progress-text { font-variant-numeric: tabular-nums; font-size: 13px; min-width: 110px; }
.progress-text strong { color: var(--fg); }
.progress-text .pass-count { color: var(--ok); }
.progress-text .fail-count { color: var(--bad); }
.progress-text .skip-count { color: var(--muted); }
.toolbar {
  display: flex; flex-wrap: wrap; align-items: center; gap: 10px;
}
.toolbar select, .toolbar input[type=text] {
  font: inherit; padding: 5px 10px; border: 1px solid var(--line);
  border-radius: 4px; background: var(--card); color: var(--fg);
}
.toolbar label { color: var(--muted); font-size: 12px; }
.toolbar button {
  font: inherit; padding: 6px 14px; border: 1px solid var(--fg);
  border-radius: 4px; cursor: pointer; background: var(--fg); color: var(--bg);
  font-weight: 600;
}
.toolbar button.secondary {
  background: transparent; color: var(--fg);
}
.toolbar button:hover { opacity: 0.85; }
.toolbar .draft-status {
  margin-left: auto; color: var(--muted); font-size: 12px;
  transition: opacity 0.4s;
}
.toolbar .shortcuts {
  color: var(--muted); font-size: 12px; margin-left: 8px;
}
.toolbar .shortcuts kbd {
  background: var(--card); border: 1px solid var(--line);
  border-radius: 3px; padding: 1px 5px; font-size: 11px; margin: 0 1px;
}
main { padding: 16px 20px 80px; }
.species-section {
  margin-bottom: 32px; background: rgba(255,255,255,0.4);
  border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px;
}
.species-section.hidden { display: none; }
.species-header {
  display: flex; justify-content: space-between; align-items: baseline;
  gap: 16px; flex-wrap: wrap; margin-bottom: 12px;
  padding-bottom: 8px; border-bottom: 1px solid var(--line);
}
.species-title .species-name { font-size: 18px; font-weight: 700; }
.species-title .species-sub { color: var(--muted); font-size: 12px; margin-left: 8px; }
.species-title .species-sub code { background: var(--bg); padding: 1px 4px; border-radius: 2px; font-size: 11px; }
.species-meta { display: flex; gap: 8px; align-items: center; font-size: 12px; color: var(--muted); }
.species-meta .species-count { font-weight: 600; color: var(--fg); }
.grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(290px, 1fr));
  gap: 12px;
}
.card {
  background: var(--card); border: 1px solid var(--line); border-radius: 8px;
  overflow: hidden; box-shadow: var(--shadow);
  display: flex; flex-direction: column;
  position: relative;
  border-left-width: 5px;
  transition: border-color 0.2s, transform 0.1s;
}
.card.is-pass { border-left-color: var(--ok); }
.card.is-fail { border-left-color: var(--bad); }
.card.is-skip { border-left-color: var(--neutral); }
.card.is-ungraded { border-left-color: var(--line); }
.card.is-picker-winner { box-shadow: 0 0 0 2px var(--warn), var(--shadow); }
.card.is-my-winner { box-shadow: 0 0 0 3px var(--ok), var(--shadow); }
.card:focus { outline: 2px solid var(--fg); outline-offset: 1px; transform: translateY(-1px); }
.card.hidden { display: none; }
.my-winner-btn {
  position: absolute; top: 6px; right: 6px;
  width: 28px; height: 28px; border-radius: 50%;
  background: rgba(255,255,255,0.85); border: 1px solid var(--line);
  cursor: pointer; font-size: 14px;
  display: flex; align-items: center; justify-content: center;
  filter: grayscale(1) opacity(0.45);
  transition: filter 0.15s, transform 0.15s;
}
.my-winner-btn:hover { filter: grayscale(0) opacity(1); transform: scale(1.1); }
.is-my-winner .my-winner-btn { filter: none; background: var(--ok); color: #fff; border-color: var(--ok); }
.att-label, .seed-label {
  display: inline-block; padding: 1px 5px; border-radius: 3px;
  background: var(--bg); font-size: 10.5px; color: var(--muted);
  letter-spacing: 0.02em; font-variant-numeric: tabular-nums;
}

.thumb-wrap {
  width: 100%; aspect-ratio: 1; background: #ece2cf;
  display: flex; align-items: center; justify-content: center;
  cursor: zoom-in; position: relative; overflow: hidden;
}
.thumb-img { width: 100%; height: 100%; object-fit: contain; }
.missing { color: var(--bad); font-size: 12px; }

.meta { padding: 10px 12px 12px; flex: 1; display: flex; flex-direction: column; gap: 6px; }
.score { font-size: 12px; }
.badge {
  display: inline-block; padding: 1px 6px; border-radius: 3px;
  font-size: 11px; font-weight: 600; color: #fff; margin-left: 4px;
}
.badge.ok { background: var(--ok); }
.badge.warn { background: var(--warn); }
.bad { color: var(--bad); }

.vote-buttons {
  display: flex; gap: 6px; margin-top: 4px;
}
.vote {
  flex: 1; padding: 8px 6px; border: 1px solid var(--line);
  background: var(--card); color: var(--fg);
  font: inherit; font-weight: 600; cursor: pointer; border-radius: 4px;
  transition: background 0.15s, border-color 0.15s, color 0.15s;
  font-size: 13px;
}
.vote-pass:hover, .vote-pass.is-active { background: var(--ok); color: #fff; border-color: var(--ok); }
.vote-fail:hover, .vote-fail.is-active { background: var(--bad); color: #fff; border-color: var(--bad); }
.vote-skip:hover, .vote-skip.is-active { background: var(--neutral); color: #fff; border-color: var(--neutral); }

.reasons { margin-top: 2px; }
.reason-label {
  font-size: 11px; color: var(--muted); text-transform: uppercase;
  letter-spacing: 0.05em; margin-bottom: 4px;
}
.chips { display: flex; flex-wrap: wrap; gap: 4px; }
.chip {
  padding: 3px 8px; border-radius: 12px; font-size: 12px;
  border: 1px solid var(--line); background: var(--card); color: var(--fg);
  cursor: pointer; font: inherit;
  transition: background 0.15s, color 0.15s, border-color 0.15s;
}
.chip-pass:hover, .chip-pass.is-active {
  background: var(--ok-bg); border-color: var(--ok); color: var(--ok);
}
.chip-fail:hover, .chip-fail.is-active {
  background: var(--bad-bg); border-color: var(--bad); color: var(--bad);
}
.chip.is-active { font-weight: 600; }

.features { margin-top: 2px; }
.feat-hint { color: var(--muted); font-weight: 400; text-transform: none; letter-spacing: 0; font-size: 11px; }
.feat-chips { display: flex; flex-wrap: wrap; gap: 4px; }
.feat-chip {
  padding: 3px 8px; border-radius: 12px; font-size: 11.5px;
  border: 1px dashed var(--neutral); background: var(--card); color: var(--fg);
  cursor: pointer; font: inherit;
  transition: background 0.15s, color 0.15s, border-color 0.15s, border-style 0.15s;
}
.feat-chip:hover {
  background: var(--warn-bg); border-color: var(--warn); color: var(--warn); border-style: solid;
}
.feat-chip.is-active {
  background: var(--warn); color: #fff; border-color: var(--warn); border-style: solid;
  font-weight: 600;
}

textarea.notes {
  font: inherit; font-size: 12px;
  width: 100%; padding: 6px 8px; border: 1px solid var(--line);
  border-radius: 4px; background: var(--bg); color: var(--fg);
  resize: vertical; min-height: 28px;
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
}
textarea.notes:focus { outline: 1px solid var(--fg); }

/* Image modal */
.modal {
  position: fixed; inset: 0; background: rgba(26, 41, 82, 0.92);
  display: none; align-items: center; justify-content: center;
  z-index: 100; cursor: zoom-out; padding: 32px;
}
.modal.open { display: flex; }
.modal img { max-width: 100%; max-height: 100%; box-shadow: 0 4px 24px rgba(0,0,0,0.4); }
.modal .modal-caption {
  position: absolute; bottom: 20px; left: 50%; transform: translateX(-50%);
  background: var(--bg); color: var(--fg); padding: 8px 16px;
  border-radius: 4px; font-size: 13px;
}

.flash {
  position: fixed; bottom: 20px; right: 20px;
  background: var(--fg); color: var(--bg); padding: 10px 16px;
  border-radius: 4px; font-size: 13px; box-shadow: 0 2px 8px rgba(0,0,0,0.2);
  opacity: 0; transform: translateY(10px); transition: all 0.3s;
  pointer-events: none; z-index: 60;
}
.flash.show { opacity: 1; transform: translateY(0); }

@media (max-width: 600px) {
  .grid { grid-template-columns: 1fr; }
  header { padding: 10px 12px; }
  main { padding: 12px; }
}
"""


JS_TEMPLATE = """
(function () {
  const STORAGE_KEY = 'forge_v4_grading_' + (window.__BATCH_TS__ || 'default');
  const PASS_REASONS = window.__PASS_REASONS__ || [];
  const FAIL_REASONS = window.__FAIL_REASONS__ || [];
  const PASS_IDS = new Set(PASS_REASONS.map(r => r[0]));
  const FAIL_IDS = new Set(FAIL_REASONS.map(r => r[0]));

  // ── State: keyed by card_id (slug__aNN_sNN). Per-image votes.
  //    Plus state.myWinners[slug] = card_id of user's pick (if any).
  const state = { byCard: {}, myWinners: {} };
  const cardIds = Array.from(document.querySelectorAll('.card')).map(c => c.dataset.cardId);
  const cardSlugMap = {};
  Array.from(document.querySelectorAll('.card')).forEach(c => {
    cardSlugMap[c.dataset.cardId] = c.dataset.slug;
  });
  cardIds.forEach(id => { state.byCard[id] = { vote: null, reasons: [], anatomy_missing: [], notes: '' }; });

  function restore() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw);
      if (saved.byCard) {
        Object.keys(saved.byCard).forEach(id => {
          if (state.byCard[id]) Object.assign(state.byCard[id], saved.byCard[id]);
        });
      }
      if (saved.myWinners) Object.assign(state.myWinners, saved.myWinners);
    } catch (e) { console.warn('restore failed:', e); }
  }

  let saveTimeout = null;
  function save() {
    if (saveTimeout) clearTimeout(saveTimeout);
    saveTimeout = setTimeout(() => {
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); }
      catch (e) { console.warn('save failed:', e); }
      flash('Draft saved', 800);
    }, 300);
  }

  function flash(msg, duration = 1400) {
    let el = document.getElementById('flash');
    if (!el) {
      el = document.createElement('div');
      el.id = 'flash';
      el.className = 'flash';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add('show');
    clearTimeout(el._timer);
    el._timer = setTimeout(() => el.classList.remove('show'), duration);
  }

  // ── Per-card render from state
  function renderCard(card) {
    const cardId = card.dataset.cardId;
    const slug = card.dataset.slug;
    const s = state.byCard[cardId];
    card.classList.remove('is-pass', 'is-fail', 'is-skip', 'is-ungraded', 'is-my-winner');
    if (s.vote === 'pass') card.classList.add('is-pass');
    else if (s.vote === 'fail') card.classList.add('is-fail');
    else if (s.vote === 'skip') card.classList.add('is-skip');
    else card.classList.add('is-ungraded');
    if (state.myWinners[slug] === cardId) card.classList.add('is-my-winner');

    card.querySelectorAll('.vote').forEach(b => {
      b.classList.toggle('is-active', b.dataset.vote === s.vote);
    });

    card.querySelector('.reasons-pass').hidden = s.vote !== 'pass';
    card.querySelector('.reasons-fail').hidden = s.vote !== 'fail';

    const activeSet = new Set(s.reasons || []);
    card.querySelectorAll('.chip').forEach(chip => {
      chip.classList.toggle('is-active', activeSet.has(chip.dataset.reason));
    });

    // Show the species-feature checklist when fail-vote AND either an
    // anatomy_broken OR species_mismatch reason chip is selected. This
    // keeps the UI uncluttered for clear-cut passes/fails while still
    // collecting fine-grained data when the user calls out a fidelity gap.
    const featRow = card.querySelector('.features');
    const showFeats = (s.vote === 'fail') &&
      (activeSet.has('anatomy_broken') || activeSet.has('species_mismatch'));
    if (featRow) featRow.hidden = !showFeats;

    const featActive = new Set(s.anatomy_missing || []);
    card.querySelectorAll('.feat-chip').forEach(chip => {
      chip.classList.toggle('is-active', featActive.has(chip.dataset.feature));
    });

    const ta = card.querySelector('textarea.notes');
    if (ta && ta.value !== s.notes) ta.value = s.notes;
  }

  function renderAll() { document.querySelectorAll('.card').forEach(renderCard); renderProgress(); applyFilterSort(); }

  function renderProgress() {
    let p = 0, f = 0, k = 0, total = cardIds.length;
    cardIds.forEach(id => {
      const v = state.byCard[id].vote;
      if (v === 'pass') p++;
      else if (v === 'fail') f++;
      else if (v === 'skip') k++;
    });
    const done = p + f + k;
    const pct = total ? (100 * done / total) : 0;
    document.getElementById('progress-fill').style.width = pct.toFixed(1) + '%';
    document.getElementById('progress-text').innerHTML =
      `<strong>${done}/${total}</strong> graded · ` +
      `<span class="pass-count">${p} pass</span> · ` +
      `<span class="fail-count">${f} fail</span> · ` +
      `<span class="skip-count">${k} skip</span>`;
  }

  // ── Filter / sort. Filter hides individual cards; sort reorders
  // within each species section. We also hide species sections when
  // they have no visible cards.
  function applyFilterSort() {
    const filter = document.getElementById('filter').value;
    const sort = document.getElementById('sort').value;

    document.querySelectorAll('.species-section').forEach(section => {
      const grid = section.querySelector('.grid');
      const cards = Array.from(grid.children);
      let visibleCount = 0;
      cards.forEach(card => {
        const cid = card.dataset.cardId;
        const slug = card.dataset.slug;
        const v = state.byCard[cid].vote;
        let visible = true;
        if (filter === 'ungraded') visible = !v;
        else if (filter === 'passed') visible = v === 'pass';
        else if (filter === 'failed') visible = v === 'fail';
        else if (filter === 'skipped') visible = v === 'skip';
        else if (filter === 'picker-disagrees') {
          // user marked this picker_winner as FAIL, OR user picked a non-picker card as my-winner
          const isPickerWinner = parseInt(card.dataset.pickerWinner) === 1;
          const isMyWinner = state.myWinners[slug] === cid;
          visible = (isPickerWinner && v === 'fail') ||
                    (isMyWinner && !isPickerWinner);
        }
        card.classList.toggle('hidden', !visible);
        if (visible) visibleCount++;
      });
      // Hide the entire section if no cards visible
      section.classList.toggle('hidden', visibleCount === 0);

      // Sort visible cards within the section
      const visCards = cards.filter(c => !c.classList.contains('hidden'));
      visCards.sort((a, b) => {
        if (sort === 'composite-desc') return parseFloat(b.dataset.composite) - parseFloat(a.dataset.composite);
        if (sort === 'composite-asc')  return parseFloat(a.dataset.composite) - parseFloat(b.dataset.composite);
        if (sort === 'attempt-asc')    return (parseInt(a.dataset.attempt) - parseInt(b.dataset.attempt)) ||
                                              (parseInt(a.dataset.seed) - parseInt(b.dataset.seed));
        if (sort === 'picker-first')   return parseInt(b.dataset.pickerWinner) - parseInt(a.dataset.pickerWinner);
        return 0;
      });
      visCards.forEach(c => grid.appendChild(c));
    });
  }

  // ── Wire up interactions
  function wireCard(card) {
    const cardId = card.dataset.cardId;
    const slug = card.dataset.slug;
    card.querySelectorAll('.vote').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const v = btn.dataset.vote;
        const s = state.byCard[cardId];
        s.vote = s.vote === v ? null : v;
        if (s.vote !== 'pass' && s.vote !== 'fail') {
          s.reasons = [];
        } else {
          s.reasons = (s.reasons || []).filter(r =>
            (s.vote === 'pass' && PASS_IDS.has(r)) ||
            (s.vote === 'fail' && FAIL_IDS.has(r))
          );
        }
        renderCard(card);
        renderProgress();
        save();
      });
    });
    card.querySelectorAll('.chip').forEach(chip => {
      chip.addEventListener('click', (e) => {
        e.stopPropagation();
        const r = chip.dataset.reason;
        const arr = state.byCard[cardId].reasons || [];
        const i = arr.indexOf(r);
        if (i >= 0) arr.splice(i, 1); else arr.push(r);
        state.byCard[cardId].reasons = arr;
        renderCard(card);
        save();
      });
    });
    card.querySelectorAll('.feat-chip').forEach(chip => {
      chip.addEventListener('click', (e) => {
        e.stopPropagation();
        const f = chip.dataset.feature;
        const arr = state.byCard[cardId].anatomy_missing || [];
        const i = arr.indexOf(f);
        if (i >= 0) arr.splice(i, 1); else arr.push(f);
        state.byCard[cardId].anatomy_missing = arr;
        renderCard(card);
        save();
      });
    });
    const myWinnerBtn = card.querySelector('.my-winner-btn');
    if (myWinnerBtn) {
      myWinnerBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleMyWinner(cardId, slug);
      });
    }
    const ta = card.querySelector('textarea.notes');
    if (ta) {
      ta.addEventListener('input', () => { state.byCard[cardId].notes = ta.value; save(); });
      ta.addEventListener('focus', () => { focusedCardId = cardId; });
    }

    // Image modal on thumbnail click (but not when my-winner button is the click target)
    const img = card.querySelector('.thumb-img');
    if (img) {
      img.parentElement.addEventListener('click', (e) => {
        if (e.target.closest('.my-winner-btn')) return;
        openModal(img.dataset.full || img.src, slug + ' · a' + card.dataset.attempt + ' s' + card.dataset.seed);
      });
    }

    card.addEventListener('focus', () => { focusedCardId = cardId; });
    card.addEventListener('click', () => { focusedCardId = cardId; });
  }

  function toggleMyWinner(cardId, slug) {
    // Per-species single-select: if this card is already the my-winner, clear it.
    // Otherwise, set this as the my-winner for the species.
    if (state.myWinners[slug] === cardId) {
      delete state.myWinners[slug];
    } else {
      state.myWinners[slug] = cardId;
    }
    // Re-render all cards for this species
    document.querySelectorAll('.card[data-slug="' + slug + '"]').forEach(renderCard);
    save();
    flash(state.myWinners[slug] ? '🏆 marked as your pick' : 'pick cleared', 1000);
  }

  // ── Modal
  function openModal(src, slug) {
    const modal = document.getElementById('modal');
    const img = modal.querySelector('img');
    const cap = modal.querySelector('.modal-caption');
    img.src = src;
    cap.textContent = slug;
    modal.classList.add('open');
  }
  function closeModal() {
    document.getElementById('modal').classList.remove('open');
  }

  // ── Toolbar actions
  function exportVotes() {
    const votes = cardIds.map(id => {
      const c = document.querySelector('.card[data-card-id="' + id + '"]');
      const slug = c.dataset.slug;
      const s = state.byCard[id];
      return {
        card_id: id,
        slug: slug,
        attempt: parseInt(c.dataset.attempt),
        seed: parseInt(c.dataset.seed),
        render_path: c.querySelector('.thumb-img') ? c.querySelector('.thumb-img').dataset.full || null : null,
        composite: parseFloat(c.dataset.composite),
        is_picker_winner: parseInt(c.dataset.pickerWinner) === 1,
        is_my_winner: state.myWinners[slug] === id,
        vote: s.vote || 'skip',
        reasons: s.reasons || [],
        anatomy_missing: s.anatomy_missing || [],
        notes: s.notes || ''
      };
    });
    const pass = votes.filter(v => v.vote === 'pass').length;
    const fail = votes.filter(v => v.vote === 'fail').length;
    const skip = votes.filter(v => v.vote === 'skip').length;
    // Detect picker disagreement: my_winner != picker_winner for any species
    const speciesPickerWinner = {};
    const speciesMyWinner = {};
    votes.forEach(v => {
      if (v.is_picker_winner) speciesPickerWinner[v.slug] = v.card_id;
      if (v.is_my_winner) speciesMyWinner[v.slug] = v.card_id;
    });
    const disagreements = Object.keys(speciesMyWinner).filter(
      slug => speciesPickerWinner[slug] !== speciesMyWinner[slug]
    );
    const data = {
      schema: 'forge.user_grading.v4',
      ts: new Date().toISOString(),
      batch_summary_ts: window.__BATCH_TS__ || null,
      n_total: votes.length,
      n_pass: pass, n_fail: fail, n_skip: skip,
      n_my_winners: Object.keys(speciesMyWinner).length,
      picker_disagreements: disagreements,
      votes
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'v4_user_votes_' + new Date().toISOString().slice(0, 10) + '.json';
    a.click();
    URL.revokeObjectURL(url);
    flash('Exported ' + votes.length + ' votes (' + pass + ' pass, ' + fail + ' fail, ' + skip + ' skip)', 2400);
  }

  function resetAll() {
    if (!confirm('Reset ALL votes, reasons, notes, and my-pick markers? This cannot be undone.')) return;
    cardIds.forEach(id => { state.byCard[id] = { vote: null, reasons: [], anatomy_missing: [], notes: '' }; });
    state.myWinners = {};
    save();
    renderAll();
    flash('Reset', 1200);
  }

  // ── Keyboard navigation
  let focusedCardId = null;
  function focusedCard() {
    return focusedCardId ? document.querySelector('.card[data-card-id="' + focusedCardId + '"]') : null;
  }
  function moveFocus(delta) {
    const visibleCards = Array.from(document.querySelectorAll('.card:not(.hidden)'));
    if (!visibleCards.length) return;
    const cur = focusedCard();
    let i = cur ? visibleCards.indexOf(cur) : -1;
    i = (i + delta + visibleCards.length) % visibleCards.length;
    const next = visibleCards[i];
    next.focus();
    next.scrollIntoView({ block: 'center', behavior: 'smooth' });
    focusedCardId = next.dataset.cardId;
  }
  function applyVote(v) {
    const card = focusedCard();
    if (!card) { moveFocus(1); return; }
    const cardId = card.dataset.cardId;
    const s = state.byCard[cardId];
    s.vote = s.vote === v ? null : v;
    if (s.vote !== 'pass' && s.vote !== 'fail') {
      s.reasons = [];
    }
    renderCard(card);
    renderProgress();
    save();
  }
  function toggleReasonByIndex(idx) {
    const card = focusedCard();
    if (!card) return;
    const cardId = card.dataset.cardId;
    const s = state.byCard[cardId];
    const list = s.vote === 'pass' ? PASS_REASONS
               : s.vote === 'fail' ? FAIL_REASONS : null;
    if (!list || idx >= list.length) return;
    const r = list[idx][0];
    const arr = s.reasons || [];
    const i = arr.indexOf(r);
    if (i >= 0) arr.splice(i, 1); else arr.push(r);
    s.reasons = arr;
    renderCard(card);
    save();
  }
  function applyMyWinnerShortcut() {
    const card = focusedCard();
    if (!card) return;
    toggleMyWinner(card.dataset.cardId, card.dataset.slug);
  }

  document.addEventListener('keydown', (e) => {
    // Don't fire shortcuts when typing in textareas / inputs / selects
    const tag = (e.target.tagName || '').toLowerCase();
    if (tag === 'textarea' || tag === 'input' || tag === 'select') return;
    if (e.key === 'Escape') { closeModal(); return; }
    // ⌘E / Ctrl+E → export
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'e') {
      e.preventDefault(); exportVotes(); return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    switch (e.key.toLowerCase()) {
      case 'p': e.preventDefault(); applyVote('pass'); break;
      case 'f': e.preventDefault(); applyVote('fail'); break;
      case 's': e.preventDefault(); applyVote('skip'); break;
      case 'j': e.preventDefault(); moveFocus(1); break;
      case 'k': e.preventDefault(); moveFocus(-1); break;
      case 'w': e.preventDefault(); applyMyWinnerShortcut(); break;
      case '1': case '2': case '3': case '4': case '5':
      case '6': case '7': case '8': case '9':
        e.preventDefault();
        toggleReasonByIndex(parseInt(e.key) - 1);
        break;
    }
  });

  // ── Init
  restore();
  document.querySelectorAll('.card').forEach(wireCard);
  document.getElementById('btn-export').addEventListener('click', exportVotes);
  document.getElementById('btn-reset').addEventListener('click', resetAll);
  document.getElementById('filter').addEventListener('change', applyFilterSort);
  document.getElementById('sort').addEventListener('change', applyFilterSort);
  document.getElementById('modal').addEventListener('click', closeModal);
  document.querySelector('.modal img').addEventListener('click', (e) => e.stopPropagation());
  // Initial focus on the first card
  const first = document.querySelector('.card');
  if (first) { focusedCardId = first.dataset.cardId; }
  renderAll();
})();
"""


def build_html(summary: dict) -> str:
    statuses = summary.get("statuses", [])
    features_registry = load_species_features()

    # Enumerate every render across every species
    renders_by_species = enumerate_renders(summary)
    n_species = len(statuses)
    n_cards = sum(len(v) for v in renders_by_species.values())
    accepted_n = sum(1 for s in statuses if s.get("accepted"))

    sections_html_parts = []
    # Iterate in the batch summary's order so user grades top-down by composite winner
    for status in statuses:
        slug = status.get("slug")
        records = renders_by_species.get(slug, [])
        if not records:
            continue
        sections_html_parts.append(build_species_section(status, records, features_registry))
    sections_html = "\n".join(sections_html_parts)

    all_composites = [r["composite"] for recs in renders_by_species.values()
                      for r in recs if r.get("composite") is not None]
    range_str = (
        f"composite range <b>{min(all_composites):.3f}</b>–<b>{max(all_composites):.3f}</b>"
        if all_composites else "no composites yet"
    )
    summary_line = (
        f"<b>{n_species}</b> species · <b>{n_cards}</b> renders · "
        f"<b>{accepted_n}</b> picker-accepted · {range_str}"
    )
    batch_ts = summary.get("start_ts", "unknown")

    # JS injection — render the reason tables and batch timestamp into JS land.
    js = (
        JS_TEMPLATE
        .replace("window.__BATCH_TS__ || 'default'", json.dumps(batch_ts))
        .replace("window.__BATCH_TS__ || null", json.dumps(batch_ts))
        .replace("window.__PASS_REASONS__ || []", json.dumps(PASS_REASONS))
        .replace("window.__FAIL_REASONS__ || []", json.dumps(FAIL_REASONS))
    )

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Forge v4 batch — grading</title>
<style>{CSS}</style>
</head>
<body>
  <header>
    <h1>Forge v4 batch — grade {n_cards} renders across {n_species} species</h1>
    <div class="subtitle">{summary_line}</div>
    <div class="progress-row">
      <div class="progress-bar"><div class="progress-fill" id="progress-fill"></div></div>
      <div class="progress-text" id="progress-text"><strong>0/{n_cards}</strong> graded</div>
    </div>
    <div class="toolbar">
      <label>Filter
        <select id="filter">
          <option value="all">All renders</option>
          <option value="ungraded">Ungraded</option>
          <option value="passed">Passed</option>
          <option value="failed">Failed</option>
          <option value="skipped">Skipped</option>
          <option value="picker-disagrees">Picker disagreements</option>
        </select>
      </label>
      <label>Sort within species
        <select id="sort">
          <option value="composite-desc">Composite ↓</option>
          <option value="composite-asc">Composite ↑</option>
          <option value="attempt-asc">Attempt order</option>
          <option value="picker-first">Picker winner first</option>
        </select>
      </label>
      <button id="btn-export">Export votes (JSON)</button>
      <button id="btn-reset" class="secondary">Reset all</button>
      <span class="shortcuts">
        <kbd>P</kbd>/<kbd>F</kbd>/<kbd>S</kbd> vote ·
        <kbd>J</kbd>/<kbd>K</kbd> next/prev ·
        <kbd>W</kbd> my pick ·
        <kbd>1</kbd>–<kbd>9</kbd> chips ·
        <kbd>⌘E</kbd> export
      </span>
    </div>
  </header>

  <main>{sections_html}</main>

  <div class="modal" id="modal">
    <img alt="">
    <div class="modal-caption"></div>
  </div>

  <script>{js}</script>
</body></html>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--summary", type=Path, default=SUMMARY_PATH)
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    args = parser.parse_args()
    if not args.summary.exists():
        raise SystemExit(f"summary not found: {args.summary}")
    summary = json.loads(args.summary.read_text())
    n = len(summary.get("statuses", []))
    print(f"Reading summary: {args.summary}")
    print(f"  {n} species in summary (n_done={summary.get('n_done', '?')}/{summary.get('n_total', '?')})")
    print(f"Walking reasoning_result.json files to enumerate every render...")
    renders_by_species = enumerate_renders(summary)
    n_cards = sum(len(v) for v in renders_by_species.values())
    print(f"  {n_cards} total renders found across {len(renders_by_species)} species")
    print(f"Building thumbs at {THUMB_SIZE}px + full-res at {FULL_SIZE}px (base64-embedded)...")
    html = build_html(summary)
    args.out.write_text(html, encoding="utf-8")
    size_kb = args.out.stat().st_size / 1024
    print(f"Wrote {args.out}  ({size_kb:.1f} KB = {size_kb/1024:.1f} MB)")
    print()
    print(f"  open {args.out}")
    print()
    print("Grading shortcuts:")
    print("  P / F / S        → vote pass / fail / skip on focused card")
    print("  J / K            → next / previous card")
    print("  W                → mark as MY pick for this species (overrides picker)")
    print("  1 – 9            → toggle reason chips on focused card")
    print("  ⌘E (Ctrl+E)      → export votes as JSON")
    print("  Click thumbnail  → open full resolution")
    print()
    print("Progress auto-saves to localStorage. Refresh-safe.")
    print()
    print("Next: drop the exported JSON into bin/build_lora_dataset_v2.py --votes <path>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
