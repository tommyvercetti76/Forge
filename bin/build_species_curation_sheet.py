#!/usr/bin/env python3
"""Build the species photo CURATION contact sheet — review + tag the 328 refs.

Reads `brand/references/species/<slug>/*.jpg` + matching `.attribution.json`
files and produces an HTML curation UI at
`brand/references/species/_curation_sheet.html`.

Per-species section shows 8 reference photos. Per-photo controls:

  - ⭐  "canonical" radio — pick ONE per species (the photo that becomes the
        init-image for that species in the v6 batch)
  - ✗   "drop" toggle — mark a photo as bad (low-quality, wrong species,
        watermarked, etc.) so it gets excluded from future use
  - sex tag radio — male / female / unknown (for dimorphic species)
  - pose tag dropdown — side-profile / head-close / full-body / displaying /
        stalking / wading / swimming / other
  - notes textarea — free-text per photo

Sticky toolbar:
  - progress: "X/41 species canonicalized · Y dropped · Z untagged"
  - filter (all / no-canonical-yet / has-drops)
  - export → `species_curation_<date>.json` (forge.species_curation.v1)

localStorage persistence (refresh-safe). Self-contained HTML — all photos
embedded as data: URLs.

Usage:
  python3 bin/build_species_curation_sheet.py
  open brand/references/species/_curation_sheet.html
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPECIES_ROOT = ROOT / "brand" / "references" / "species"
ANIMALS_PATH = ROOT / "brand" / "madhubani" / "animals.json"
OUT_PATH = SPECIES_ROOT / "_curation_sheet.html"

THUMB_SIZE = 360
FULL_SIZE = 1280

# Universal poses available to every body type (close-ups + multi-individual shots).
_UNIVERSAL_POSES = [
    ("head-close-up", "Head close-up"),
    ("signature-feature-close", "Signature feature close-up"),
    ("family-group", "Family group / multiple individuals"),
    ("other", "Other"),
]

# Body-type-specific pose taxonomies — mirrors brand/madhubani/kb/_body_types/*.md.
# Each species' dropdown is the body-type's poses + the universal poses.
POSES_BY_BODY_TYPE = {
    "lean-predator": [
        ("side-profile-standing-alert", "Standing alert (side profile)"),
        ("side-profile-walking", "Walking (side)"),
        ("side-profile-stalking-low", "Stalking-low (hunting silhouette)"),
        ("sitting-upright", "Sitting upright"),
        ("sitting-with-tail-curled", "Sitting (tail curled — felid signature)"),
        ("lying-head-up", "Lying with head up"),
        ("full-body-habitat", "Full body in habitat"),
    ],
    "heavy-quadruped": [
        ("side-profile-standing-alert", "Standing alert (side profile)"),
        ("side-profile-walking", "Walking (side)"),
        ("side-profile-grazing", "Grazing (head lowered)"),
        ("full-body-habitat", "Full body in habitat"),
        ("mud-bathing", "Mud-bathing / dust-bathing"),
    ],
    "lean-quadruped": [
        ("side-profile-standing-alert", "Standing alert (side profile)"),
        ("side-profile-grazing", "Grazing (head lowered)"),
        ("side-profile-trotting", "Trotting (mid-step)"),
        ("lying-with-head-up", "Lying with head up"),
        ("rutting-display", "Rutting / mating display"),
        ("leaping-pronking", "Leaping / pronking (chinkara, blackbuck)"),
        ("full-body-habitat", "Full body in habitat"),
        ("antler-or-horn-detail", "Antler / horn detail close"),
    ],
    "stocky-omnivore": [
        ("side-profile-standing-alert", "Standing alert (side profile)"),
        ("side-profile-walking", "Walking (side)"),
        ("side-profile-foraging", "Foraging (head down — rooting/termite mound)"),
        ("rearing-bipedal", "Rearing bipedal (bear / boar threat display)"),
        ("full-body-habitat", "Full body in habitat"),
    ],
    "primate": [
        ("sitting-upright", "Sitting upright (default)"),
        ("branch-perch-upright", "Sitting on branch (upright)"),
        ("quadrupedal-walking", "Quadrupedal walking (palms + soles down)"),
        ("knuckle-walking", "Knuckle-walking"),
        ("hanging-arm-suspension", "Hanging by arm (brachiation)"),
        ("bipedal-standing", "Bipedal standing (rare)"),
        ("full-body-habitat", "Full body in habitat"),
    ],
    "arboreal-primate": [
        ("hanging-arm-suspension", "Hanging by arm (brachiation — gibbon signature)"),
        ("branch-perch-upright", "Sitting on branch (upright)"),
        ("quadrupedal-walking-branch", "Walking along a branch"),
        ("sitting-upright", "Sitting upright"),
        ("full-body-habitat", "Full body in habitat"),
    ],
    "small-mammal": [
        ("side-profile-standing", "Standing alert (side profile)"),
        ("sitting-upright-rodent", "Sitting upright (haunches, hands forward)"),
        ("climbing-branch", "Climbing / on branch (arboreal)"),
        ("walking-low", "Walking low (mongoose locomotion)"),
        ("full-body-habitat", "Full body in habitat"),
    ],
    "armored-quadruped": [
        ("side-profile-standing", "Standing alert (side profile)"),
        ("curled-defensive-ball", "Curled defensive ball (pangolin signature)"),
        ("foraging-low", "Foraging (head down, claws digging)"),
        ("full-body-habitat", "Full body in habitat"),
        ("scale-pattern-detail", "Scale pattern detail close"),
    ],
    "bird": [
        ("standing-side-profile", "Standing (side profile, both legs)"),
        ("one-leg-tucked", "One leg tucked (cranes, flamingos)"),
        ("perching", "Perching (small birds, hornbills)"),
        ("wading", "Wading (storks, herons in water)"),
        ("swimming-floating", "Swimming / floating (water birds)"),
        ("displaying-full-fan", "Displaying full fan (peacock SIGNATURE)"),
        ("in-flight-soaring", "In flight — soaring (wings spread)"),
        ("in-flight-stooping", "In flight — stooping / hunting"),
        ("full-body-habitat", "Full body in habitat"),
    ],
    "serpent": [
        ("spread-hooded", "Spread-hooded (cobra SIGNATURE)"),
        ("coiled-S-resting", "Coiled S-curve (resting)"),
        ("coiled-striking", "Coiled strike-ready"),
        ("glide-straight", "Glide locomotion (straight body)"),
        ("tongue-extended", "Tongue extended (single forked)"),
        ("scale-pattern-detail", "Scale pattern detail close"),
    ],
    "cetacean": [
        ("swimming-side", "Swimming (side profile)"),
        ("surfacing", "Surfacing (blowhole visible)"),
        ("breaching", "Breaching (leaping out)"),
        ("resting-floating", "Resting / floating at surface"),
        ("group-pod", "Pod / multiple individuals"),
    ],
    "crocodilian": [
        ("basking-side", "Basking on bank (side profile)"),
        ("submerged-eyes-only", "Submerged (eyes + nostrils only)"),
        ("walking-low", "Walking low (locomotion)"),
        ("mouth-open-thermoregulation", "Mouth open (thermoregulation)"),
        ("full-body-habitat", "Full body in habitat"),
    ],
    "whale-shark": [   # technically a fish (Rhincodontidae), not a cetacean
        ("swimming-side", "Swimming (side profile)"),
        ("front-view-mouth-open", "Front view, mouth open (filter-feeding SIGNATURE)"),
        ("group-aggregation", "Multiple individuals (aggregation)"),
        ("spot-pattern-detail", "Spot pattern detail close"),
    ],
}


def pose_options_for(body_type: str) -> list[tuple[str, str]]:
    """Return the dropdown options for a species, given its body_type.
    Builds [empty-default] + body-type-specific + universal. Falls back
    to a generic list when body_type is unknown."""
    out: list[tuple[str, str]] = [("", "—")]
    out.extend(POSES_BY_BODY_TYPE.get(body_type, [
        ("side-profile", "Side profile"),
        ("walking", "Walking"),
        ("full-body-habitat", "Full body in habitat"),
    ]))
    out.extend(_UNIVERSAL_POSES)
    return out


def thumb_data_url(path: Path, max_dim: int = THUMB_SIZE) -> str | None:
    """Read photo, resize to max_dim, encode as JPEG data URL."""
    if not path.exists():
        return None
    try:
        from PIL import Image
        import io
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=78, optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return None


def full_data_url(path: Path, max_dim: int = FULL_SIZE) -> str | None:
    if not path.exists():
        return None
    try:
        from PIL import Image
        import io
        with Image.open(path) as img:
            img = img.convert("RGB")
            img.thumbnail((max_dim, max_dim), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, "JPEG", quality=85, optimize=True)
            b64 = base64.b64encode(buf.getvalue()).decode("ascii")
            return f"data:image/jpeg;base64,{b64}"
    except Exception:
        return None


def load_animals_index() -> dict[str, dict]:
    payload = json.loads(ANIMALS_PATH.read_text())
    return {a["slug"]: a for a in payload["animals"]}


def collect_photos(slug_dir: Path) -> list[dict]:
    """Walk one species' photo dir, return list of {photo_id, image_path,
    attribution} dicts. Skips _* files."""
    photos = []
    for p in sorted(slug_dir.iterdir()):
        if p.name.startswith("_") or p.name.endswith(".attribution.json"):
            continue
        # Match attribution.json (handles both .jpg and no-extension cases)
        attr_candidates = [
            p.parent / f"{p.stem}.attribution.json",
            p.parent / f"{p.name}.attribution.json",
            p.with_suffix(p.suffix + ".attribution.json"),
        ]
        attribution = {}
        for ac in attr_candidates:
            if ac.exists():
                try:
                    attribution = json.loads(ac.read_text())
                    break
                except Exception:
                    pass
        photo_id = p.stem if p.suffix in (".jpg", ".jpeg", ".png", ".webp") else p.name
        photos.append({
            "photo_id": photo_id,
            "image_path": str(p),
            "attribution": attribution,
        })
    return photos


def build_photo_card(slug: str, photo_idx: int, photo: dict, body_type: str = "") -> str:
    """Render one photo card with all curation controls.
    `body_type` selects the species-appropriate pose dropdown."""
    image_path = Path(photo["image_path"])
    attr = photo["attribution"]
    photo_key = f"{slug}::{photo['photo_id']}"

    thumb = thumb_data_url(image_path) or ""
    full = full_data_url(image_path) or thumb
    if not thumb:
        thumb_html = '<div class="missing">image not loadable</div>'
    else:
        thumb_html = (
            f'<img class="thumb-img" src="{thumb}" data-full="{full}" '
            f'alt="{photo["photo_id"]}" loading="lazy">'
        )

    license_str = attr.get("license", "—")
    photographer = (attr.get("photographer") or "—")[:32]
    dim_str = ""
    if attr.get("width") and attr.get("height"):
        dim_str = f'{attr["width"]}×{attr["height"]}'

    pose_opts = "".join(
        f'<option value="{v}">{l}</option>' for v, l in pose_options_for(body_type)
    )

    return f"""
    <div class="photo-card" data-photo-key="{photo_key}" data-slug="{slug}" data-photo-id="{photo['photo_id']}">
      <div class="thumb-wrap">
        {thumb_html}
        <label class="canonical-pin" title="Mark as the canonical photo for this species — becomes the v6 init-image">
          <input type="radio" name="canonical-{slug}" data-canonical="1">
          <span class="star">⭐</span>
        </label>
        <label class="drop-toggle" title="Drop this photo from the corpus (low quality, wrong species, watermarked, etc.)">
          <input type="checkbox" data-drop="1">
          <span class="x">✗</span>
        </label>
      </div>
      <div class="meta">
        <div class="meta-line"><b>{photo['photo_id']}</b> · {dim_str}</div>
        <div class="meta-line meta-muted">{photographer} · {license_str}</div>
        <div class="tags-row">
          <label>Sex
            <select class="sex-tag" data-field="sex">
              <option value="unknown">unknown</option>
              <option value="male">male</option>
              <option value="female">female</option>
              <option value="na">n/a (monomorphic)</option>
            </select>
          </label>
          <label>Pose
            <select class="pose-tag" data-field="pose">
              {pose_opts}
            </select>
          </label>
        </div>
        <textarea class="notes" placeholder="Notes (optional)" rows="1"></textarea>
      </div>
    </div>"""


def build_species_section(slug: str, animal: dict, photos: list[dict]) -> str:
    display = animal.get("display_name", slug)
    body = animal.get("body_type", "?")
    park = animal.get("park", "")
    n = len(photos)
    photos_html = "\n".join(
        build_photo_card(slug, i, p, body_type=body) for i, p in enumerate(photos)
    )
    return f"""
    <section class="species-section" data-slug="{slug}">
      <div class="species-header">
        <div class="species-title">
          <span class="species-name">{display}</span>
          <span class="species-sub"><code>{slug}</code> · {body} · {park}</span>
        </div>
        <div class="species-meta">
          <span class="photo-count">{n} photos</span>
          <span class="canonical-status" id="canon-status-{slug}">no canonical pick</span>
        </div>
      </div>
      <div class="photo-grid">{photos_html}</div>
    </section>"""


CSS = """
:root {
  --bg: #F5EFE3; --fg: #1a2952; --muted: #6b6258;
  --ok: #3d7d3d; --warn: #e87722; --bad: #c8261f;
  --gold: #e8b827; --gold-bg: #fdf6d6;
  --card: #fff; --line: #d8cfb8;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; }
body { background: var(--bg); color: var(--fg);
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif;
  font-size: 14px; line-height: 1.4; }
header { position: sticky; top: 0; z-index: 50; background: var(--bg);
  border-bottom: 1px solid var(--line); padding: 12px 20px; }
h1 { margin: 0 0 4px; font-size: 18px; font-weight: 700; }
.subtitle { color: var(--muted); font-size: 13px; margin-bottom: 10px; }
.progress-row { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.progress-bar { flex: 1; height: 8px; background: var(--line); border-radius: 4px; overflow: hidden; }
.progress-fill { height: 100%; background: var(--gold); width: 0%; transition: width 0.2s; }
.progress-text { font-variant-numeric: tabular-nums; font-size: 13px; min-width: 240px; }
.progress-text strong { color: var(--fg); }
.progress-text .canon-count { color: var(--gold); }
.progress-text .drop-count { color: var(--bad); }
.progress-text .untagged-count { color: var(--muted); }
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; }
.toolbar select { font: inherit; padding: 5px 10px; border: 1px solid var(--line);
  border-radius: 4px; background: var(--card); color: var(--fg); }
.toolbar label { color: var(--muted); font-size: 12px; }
.toolbar button { font: inherit; padding: 6px 14px; border: 1px solid var(--fg);
  border-radius: 4px; cursor: pointer; background: var(--fg); color: var(--bg);
  font-weight: 600; }
.toolbar button.secondary { background: transparent; color: var(--fg); }
.toolbar .draft-status { margin-left: auto; color: var(--muted); font-size: 12px; }
main { padding: 16px 20px 80px; }

.species-section { margin-bottom: 24px; background: rgba(255,255,255,0.4);
  border: 1px solid var(--line); border-radius: 10px; padding: 12px 16px; }
.species-section.hidden { display: none; }
.species-header { display: flex; justify-content: space-between; align-items: baseline;
  gap: 16px; flex-wrap: wrap; margin-bottom: 10px; padding-bottom: 8px;
  border-bottom: 1px solid var(--line); }
.species-name { font-size: 17px; font-weight: 700; }
.species-sub { color: var(--muted); font-size: 12px; margin-left: 8px; }
.species-sub code { background: var(--bg); padding: 1px 4px; border-radius: 2px; font-size: 11px; }
.species-meta { display: flex; gap: 8px; font-size: 12px; color: var(--muted); }
.canonical-status.has-pick { color: var(--gold); font-weight: 600; }

.photo-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 10px; }
.photo-card { background: var(--card); border: 1px solid var(--line); border-radius: 6px;
  overflow: hidden; display: flex; flex-direction: column; transition: border-color 0.2s; }
.photo-card.is-canonical { border-color: var(--gold); box-shadow: 0 0 0 2px var(--gold-bg); }
.photo-card.is-dropped { opacity: 0.45; border-left: 4px solid var(--bad); }
.thumb-wrap { position: relative; width: 100%; aspect-ratio: 1; background: #ece2cf;
  display: flex; align-items: center; justify-content: center; overflow: hidden;
  cursor: zoom-in; }
.thumb-img { width: 100%; height: 100%; object-fit: cover; }
.missing { color: var(--bad); font-size: 11px; padding: 8px; text-align: center; }

.canonical-pin, .drop-toggle { position: absolute; top: 5px; cursor: pointer;
  background: rgba(255,255,255,0.9); border: 1px solid var(--line); border-radius: 50%;
  width: 30px; height: 30px; display: flex; align-items: center; justify-content: center;
  z-index: 5; transition: background 0.15s, border-color 0.15s; }
.canonical-pin { right: 5px; }
.drop-toggle { right: 40px; }
.canonical-pin input, .drop-toggle input { display: none; }
.canonical-pin .star, .drop-toggle .x { font-size: 16px; filter: grayscale(1) opacity(0.45); }
.canonical-pin:hover { background: var(--gold-bg); border-color: var(--gold); }
.canonical-pin:hover .star { filter: none; }
.drop-toggle:hover { background: #fbdbd8; border-color: var(--bad); }
.drop-toggle:hover .x { filter: none; color: var(--bad); }
.is-canonical .canonical-pin { background: var(--gold); border-color: var(--gold); }
.is-canonical .canonical-pin .star { filter: none; }
.is-dropped .drop-toggle { background: var(--bad); border-color: var(--bad); color: #fff; }
.is-dropped .drop-toggle .x { filter: none; color: #fff; }

.meta { padding: 8px 10px; display: flex; flex-direction: column; gap: 5px; }
.meta-line { font-size: 12px; }
.meta-muted { color: var(--muted); font-size: 11px; }
.tags-row { display: flex; gap: 6px; flex-wrap: wrap; }
.tags-row label { font-size: 10px; color: var(--muted); text-transform: uppercase;
  letter-spacing: 0.04em; display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 90px; }
.tags-row select { font: inherit; font-size: 11px; padding: 3px 5px; border: 1px solid var(--line);
  border-radius: 3px; background: var(--bg); }
textarea.notes { font: inherit; font-size: 11px; width: 100%; padding: 4px 6px;
  border: 1px solid var(--line); border-radius: 3px; background: var(--bg); color: var(--fg);
  resize: vertical; min-height: 24px;
  font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif; }

.modal { position: fixed; inset: 0; background: rgba(26, 41, 82, 0.92); display: none;
  align-items: center; justify-content: center; z-index: 100; cursor: zoom-out; padding: 32px; }
.modal.open { display: flex; }
.modal img { max-width: 100%; max-height: 100%; box-shadow: 0 4px 24px rgba(0,0,0,0.4); }
.modal .modal-caption { position: absolute; bottom: 20px; left: 50%;
  transform: translateX(-50%); background: var(--bg); color: var(--fg); padding: 8px 16px;
  border-radius: 4px; font-size: 13px; }

.flash { position: fixed; bottom: 20px; right: 20px; background: var(--fg); color: var(--bg);
  padding: 10px 16px; border-radius: 4px; font-size: 13px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.2); opacity: 0; transform: translateY(10px);
  transition: all 0.3s; pointer-events: none; z-index: 60; }
.flash.show { opacity: 1; transform: translateY(0); }
"""


JS_TEMPLATE = r"""
(function () {
  const STORAGE_KEY = 'forge_species_curation_v1';
  // State: { [photo_key]: { canonical: bool, drop: bool, sex, pose, notes } }
  //  Plus state.canonicalBySlug[slug] = photo_key (single pick per species).
  const state = { byPhoto: {}, canonicalBySlug: {} };
  document.querySelectorAll('.photo-card').forEach(c => {
    const key = c.dataset.photoKey;
    state.byPhoto[key] = { canonical: false, drop: false, sex: 'unknown', pose: '', notes: '' };
  });

  function save() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); flash('Draft saved', 800); }
    catch (e) { console.warn('save failed:', e); }
  }

  function restore() {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return;
      const saved = JSON.parse(raw);
      if (saved.byPhoto) Object.keys(saved.byPhoto).forEach(k => {
        if (state.byPhoto[k]) Object.assign(state.byPhoto[k], saved.byPhoto[k]);
      });
      if (saved.canonicalBySlug) Object.assign(state.canonicalBySlug, saved.canonicalBySlug);
    } catch (e) { console.warn('restore failed:', e); }
  }

  function flash(msg, dur = 1400) {
    let el = document.getElementById('flash');
    if (!el) { el = document.createElement('div'); el.id = 'flash'; el.className = 'flash'; document.body.appendChild(el); }
    el.textContent = msg; el.classList.add('show');
    clearTimeout(el._timer); el._timer = setTimeout(() => el.classList.remove('show'), dur);
  }

  function renderCard(card) {
    const key = card.dataset.photoKey;
    const slug = card.dataset.slug;
    const s = state.byPhoto[key];
    card.classList.toggle('is-canonical', s.canonical);
    card.classList.toggle('is-dropped', s.drop);
    card.querySelector('[data-canonical]').checked = s.canonical;
    card.querySelector('[data-drop]').checked = s.drop;
    card.querySelector('.sex-tag').value = s.sex;
    card.querySelector('.pose-tag').value = s.pose;
    const ta = card.querySelector('.notes');
    if (ta.value !== s.notes) ta.value = s.notes;
  }

  function renderSpeciesStatus(slug) {
    const status = document.getElementById('canon-status-' + slug);
    const canonKey = state.canonicalBySlug[slug];
    if (canonKey) {
      const photoId = canonKey.split('::')[1];
      status.textContent = '⭐ canonical: ' + photoId;
      status.classList.add('has-pick');
    } else {
      status.textContent = 'no canonical pick';
      status.classList.remove('has-pick');
    }
  }

  function renderAll() {
    document.querySelectorAll('.photo-card').forEach(renderCard);
    const slugs = new Set();
    document.querySelectorAll('.species-section').forEach(s => slugs.add(s.dataset.slug));
    slugs.forEach(renderSpeciesStatus);
    renderProgress();
    applyFilter();
  }

  function renderProgress() {
    const allKeys = Object.keys(state.byPhoto);
    const slugs = new Set(allKeys.map(k => k.split('::')[0]));
    const nSpecies = slugs.size;
    const nCanonical = Object.keys(state.canonicalBySlug).length;
    const nDrop = allKeys.filter(k => state.byPhoto[k].drop).length;
    const nUntagged = allKeys.filter(k => {
      const s = state.byPhoto[k];
      return !s.canonical && !s.drop && s.sex === 'unknown' && !s.pose;
    }).length;
    const pct = nSpecies > 0 ? (100 * nCanonical / nSpecies) : 0;
    document.getElementById('progress-fill').style.width = pct.toFixed(1) + '%';
    document.getElementById('progress-text').innerHTML =
      `<strong>${nCanonical}/${nSpecies}</strong> species canonicalized · ` +
      `<span class="canon-count">${nCanonical} ⭐</span> · ` +
      `<span class="drop-count">${nDrop} ✗ dropped</span> · ` +
      `<span class="untagged-count">${nUntagged} untagged</span>`;
  }

  function applyFilter() {
    const filter = document.getElementById('filter').value;
    document.querySelectorAll('.species-section').forEach(section => {
      const slug = section.dataset.slug;
      let visible = true;
      if (filter === 'no-canonical') visible = !state.canonicalBySlug[slug];
      else if (filter === 'has-drops') {
        visible = Object.keys(state.byPhoto).some(k =>
          k.startsWith(slug + '::') && state.byPhoto[k].drop
        );
      } else if (filter === 'canonical-set') visible = !!state.canonicalBySlug[slug];
      section.classList.toggle('hidden', !visible);
    });
  }

  function wireCard(card) {
    const key = card.dataset.photoKey;
    const slug = card.dataset.slug;
    const canonicalInput = card.querySelector('[data-canonical]');
    canonicalInput.addEventListener('change', (e) => {
      e.stopPropagation();
      // Clear other canonicals in this species
      Object.keys(state.byPhoto).forEach(k => {
        if (k.startsWith(slug + '::') && k !== key) state.byPhoto[k].canonical = false;
      });
      state.byPhoto[key].canonical = canonicalInput.checked;
      state.canonicalBySlug[slug] = canonicalInput.checked ? key : null;
      if (!canonicalInput.checked) delete state.canonicalBySlug[slug];
      // Re-render every photo card for this species
      document.querySelectorAll('.photo-card[data-slug="' + slug + '"]').forEach(renderCard);
      renderSpeciesStatus(slug);
      renderProgress();
      save();
    });
    card.querySelector('[data-drop]').addEventListener('change', (e) => {
      e.stopPropagation();
      state.byPhoto[key].drop = e.target.checked;
      renderCard(card);
      renderProgress();
      save();
    });
    card.querySelectorAll('select').forEach(sel => {
      sel.addEventListener('change', () => {
        state.byPhoto[key][sel.dataset.field] = sel.value;
        renderProgress();
        save();
      });
    });
    const ta = card.querySelector('.notes');
    ta.addEventListener('input', () => { state.byPhoto[key].notes = ta.value; save(); });
    // Image modal
    const img = card.querySelector('.thumb-img');
    if (img) {
      card.querySelector('.thumb-wrap').addEventListener('click', (e) => {
        // Don't open modal when clicking the canonical pin or drop toggle
        if (e.target.closest('.canonical-pin, .drop-toggle')) return;
        openModal(img.dataset.full || img.src, slug + ' :: ' + card.dataset.photoId);
      });
    }
  }

  function openModal(src, caption) {
    const modal = document.getElementById('modal');
    modal.querySelector('img').src = src;
    modal.querySelector('.modal-caption').textContent = caption;
    modal.classList.add('open');
  }
  function closeModal() { document.getElementById('modal').classList.remove('open'); }

  function exportCuration() {
    const photos = Object.keys(state.byPhoto).map(key => {
      const [slug, photo_id] = key.split('::');
      const s = state.byPhoto[key];
      return { slug, photo_id, ...s };
    });
    const data = {
      schema: 'forge.species_curation.v1',
      ts: new Date().toISOString(),
      n_species: new Set(photos.map(p => p.slug)).size,
      n_photos: photos.length,
      n_canonical: photos.filter(p => p.canonical).length,
      n_dropped: photos.filter(p => p.drop).length,
      canonical_by_slug: state.canonicalBySlug,
      photos: photos
    };
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'species_curation_' + new Date().toISOString().slice(0, 10) + '.json';
    a.click();
    URL.revokeObjectURL(url);
    flash('Exported ' + photos.length + ' photo tags (' + Object.keys(state.canonicalBySlug).length + ' canonical picks)', 2400);
  }

  function resetAll() {
    if (!confirm('Reset all canonical picks, drops, sex tags, pose tags, and notes? Cannot be undone.')) return;
    Object.keys(state.byPhoto).forEach(k => {
      state.byPhoto[k] = { canonical: false, drop: false, sex: 'unknown', pose: '', notes: '' };
    });
    state.canonicalBySlug = {};
    save();
    renderAll();
    flash('Reset', 1200);
  }

  // Wire up
  restore();
  document.querySelectorAll('.photo-card').forEach(wireCard);
  document.getElementById('btn-export').addEventListener('click', exportCuration);
  document.getElementById('btn-reset').addEventListener('click', resetAll);
  document.getElementById('filter').addEventListener('change', applyFilter);
  document.getElementById('modal').addEventListener('click', closeModal);
  document.querySelector('.modal img').addEventListener('click', (e) => e.stopPropagation());
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeModal();
  });
  renderAll();
})();
"""


def build_html(species_data: list[tuple[str, dict, list[dict]]]) -> str:
    sections_html = "\n".join(
        build_species_section(slug, animal, photos)
        for slug, animal, photos in species_data
    )
    n_species = len(species_data)
    n_photos = sum(len(p) for _, _, p in species_data)
    summary_line = f"<b>{n_species}</b> species · <b>{n_photos}</b> photos · 100% open-license"

    js = JS_TEMPLATE
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Forge — species photo curation</title>
<style>{CSS}</style>
</head>
<body>
  <header>
    <h1>Forge — curate species photo references ({n_species} species, {n_photos} photos)</h1>
    <div class="subtitle">{summary_line}</div>
    <div class="progress-row">
      <div class="progress-bar"><div class="progress-fill" id="progress-fill"></div></div>
      <div class="progress-text" id="progress-text"><strong>0/{n_species}</strong> species canonicalized</div>
    </div>
    <div class="toolbar">
      <label>Filter
        <select id="filter">
          <option value="all">All species</option>
          <option value="no-canonical">No canonical pick yet</option>
          <option value="canonical-set">Canonical pick set</option>
          <option value="has-drops">Has dropped photos</option>
        </select>
      </label>
      <button id="btn-export">Export curation (JSON)</button>
      <button id="btn-reset" class="secondary">Reset all</button>
      <span style="color: var(--muted); font-size: 12px; margin-left: 8px;">
        Click ⭐ to mark canonical (= v6 init-image). Click ✗ to drop. Tag sex + pose for richer downstream use.
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
    parser.add_argument("--out", type=Path, default=OUT_PATH)
    parser.add_argument("--species", help="Only one species (default: all)")
    args = parser.parse_args()

    if not SPECIES_ROOT.exists():
        raise SystemExit(f"species refs root missing: {SPECIES_ROOT}")

    animals_idx = load_animals_index()
    if args.species:
        slugs = [args.species]
    else:
        slugs = sorted([d.name for d in SPECIES_ROOT.iterdir()
                        if d.is_dir() and not d.name.startswith("_")])

    species_data = []
    for slug in slugs:
        species_dir = SPECIES_ROOT / slug
        if not species_dir.exists():
            continue
        photos = collect_photos(species_dir)
        if not photos:
            continue
        animal = animals_idx.get(slug, {"slug": slug, "display_name": slug, "body_type": "?", "park": ""})
        species_data.append((slug, animal, photos))

    n_species = len(species_data)
    n_photos = sum(len(p) for _, _, p in species_data)
    print(f"Building curation sheet for {n_species} species, {n_photos} photos...")
    print(f"  Embedding thumbs at {THUMB_SIZE}px + full at {FULL_SIZE}px (base64)...")
    html = build_html(species_data)
    args.out.write_text(html, encoding="utf-8")
    size_mb = args.out.stat().st_size / (1024 * 1024)
    print(f"Wrote {args.out}  ({size_mb:.1f} MB)")
    print(f"  open {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
