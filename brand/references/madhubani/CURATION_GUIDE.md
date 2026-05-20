# Madhubani reference corpus — curation guide

This corpus is the **training data** for a planned LoRA fine-tune that
lifts Madhubani render quality across the catalog. It is **not** a
gallery and not redistributable — it's a private research asset.

If you only read one section: jump to [How to add a reference](#how-to-add-a-reference)
and [What makes a good reference](#what-makes-a-good-reference).

---

## Why this corpus exists

The `minimalist-tshirt` engine currently relies on prompt-side
overrides ("deep-indigo body anchor", "no orange tiger fur", etc.) to
push FLUX away from its photographic priors and toward Madhubani
folk-art convention. Those overrides leak.

> Verified 2026-05-20: prompting "Royal Bengal Tiger, Madhubani style,
> deep-indigo body" still produces a bright-orange photographic tiger.
> FLUX's pretrained association between "tiger" and orange fur
> outweighs the style instructions.

A **LoRA fine-tune on a curated Madhubani corpus** is the
research-backed way to break that lock. The LoRA learns the *style
signature* (palette, line-grammar, panel composition) and rebinds
animal subjects to that signature at inference time. Prompt-side
hacks become unnecessary.

**Target lift:** roughly +40% style adherence (measured against
hold-out Madhubani master images) once the corpus is curated and the
LoRA is trained at 1024×1024 for ~1500 steps.

---

## Target corpus size

| Bucket          | Count target | Notes                                  |
|-----------------|--------------|----------------------------------------|
| Total           | 50–100       | Quality > quantity. 60 strong > 100 weak. |
| Per priority species | 5–8     | Tiger, peacock, elephant, cobra, fish, rhino get top priority. |
| Per non-priority species | 0–3 | OK to skip species the masters never painted. |
| `_general/`     | 20–30        | Geometric motifs, palette swatches, kohbar walls, non-animal masterworks. |

**Hard cap: 8 references per species.** Over-representation biases the
LoRA toward that animal's specific masters and you lose generality.

---

## What makes a good reference

A "good" Madhubani reference for LoRA training has **all** of these:

1. **Authentic Mithila convention.** Body anchors in
   deep-indigo / walnut-brown / forest-teal, with multi-color folk
   panels (red, mustard, dot-rosette, lotus, fish-scale) *inside* the
   silhouette. If the body is bright orange or photographic, it is
   not a Madhubani reference — skip it.

2. **High-resolution source.** Scans or studio photos at **1024×1024
   or larger**. Low-res mobile snaps teach the LoRA noise patterns.

3. **Single subject, centered.** The catalog targets one-subject-per-tee.
   Multi-figure scenes confuse the silhouette objective.

4. **Clean background.** Cream paper or hand-pressed black ground
   only. No tourist-shop framing, no museum placards, no environmental
   clutter.

5. **Diverse artist hands.** Across the corpus, references should span
   multiple masters: **Sita Devi, Ganga Devi, Baua Devi, Mahasundari
   Devi**, plus contemporary practitioners. A single artist's hand
   over-represents her ornament vocabulary. See
   `brand/madhubani/masters.json` for the canonical list of cited
   influences.

6. **Mix of poses.** Side-profile (60%), frontal (25%),
   signature-action like leaping/dancing/drinking (15%). Same animal
   from multiple angles is *fine* — it helps pose generalization.

---

## What to avoid

Each of these will actively **degrade** the LoRA:

- **AI-generated "Madhubani-style" images.** They encode whatever bias
  the upstream model had. Including them poisons the training set
  with the very style drift we're trying to fix. *Do not include
  outputs from Midjourney, DALL-E, FLUX, SDXL, or any other generator.*
- **Tourist-shop mass prints and Etsy knockoffs.** These are usually
  screen-prints derived from one or two source paintings, not
  original folk art. They flatten the corpus.
- **Heavily watermarked images.** The LoRA will learn the watermark
  as a style feature and ghost it into every generation.
- **Images with text or script.** Devanagari, English captions, museum
  labels — FLUX treats text as a graphic element and will hallucinate
  garbled script into outputs. Crop the text out or skip the image.
- **Murals/walls with environmental clutter.** Brick, dirt, hands in
  frame, exhibition lighting. The LoRA will learn "Madhubani means
  brick wall in the background."
- **Photographic species.** A "natural" tiger photo or a "real"
  peacock plumage shot teaches the wrong style. Even if you label it
  "reference for anatomy," it leaks into the style channel.
- **Mixed-tradition images.** Pattachitra, Kalamkari, Warli, and
  Pichwai are *adjacent* folk traditions with overlapping subjects.
  Putting them in the Madhubani corpus blurs the engine signature.

---

## Sourcing guide (legal venues, suggested)

### Public domain / Creative Commons (preferred)

- **Wikimedia Commons** — search "Madhubani painting" and
  "Mithila painting". Most are public-domain scans of older works.
- **Brooklyn Museum** open collection — has digitized Mithila
  watercolors with explicit CC0 / public-domain marks.
- **Met Museum** open access — small Mithila holdings but
  high-quality scans, public-domain.
- **Indian Council for Cultural Relations (ICCR)** open archives —
  attribution required but often permitted for research.
- **Cultural India / IGNCA** (Indira Gandhi National Centre for the
  Arts) — check per-image license; many are research-use permitted.

### Academic sources (attribution required)

- Research papers on Mithila art — figures are often copyrighted by
  the journal but reproducible under fair-use research norms with
  citation. Note the journal and figure number in `notes`.
- Museum catalog scans — when the museum's terms permit
  non-commercial reuse, copy the relevant terms verbatim into the
  attribution file's `notes`.

### Books to scan ethically (own a copy, scan figures you cite)

- **Yves Vequaud — "Women Painters of Mithila" (1977)** — canonical
  visual record of the 1960s–70s masters. Many figures are now
  effectively in the public domain in source jurisdictions; verify
  per-image.
- **Carolyn Brown Heinz publications** — academic ethnographic
  documentation with master-painter attributions.
- **NCERT Mithila art textbook plates** — official Indian education
  material, generally permitted for research and educational use.

### Do NOT use without explicit license

- **Pinterest** — most pins are unlicensed reproductions or
  AI-generated. Pinning does not confer rights.
- **Generic Google Images** — license signal is unreliable;
  treat as "rights unknown" by default.
- **Etsy, Instagram, social media** — overwhelmingly AI-generated
  or unattributed knockoffs. Skip these.

---

## Attribution discipline

**Every image must have a sibling `<image>.attribution.json`.** No
exceptions. The audit script (`_audit.py`) will flag any image without
one and refuse to certify the corpus as LoRA-ready.

### Schema

```json
{
  "source_url": "https://commons.wikimedia.org/wiki/File:Tiger_Madhubani.jpg",
  "artist": "Sita Devi",
  "year": "circa 1972",
  "license": "public-domain",
  "permitted_uses": ["LoRA training", "Kontext seed", "private reference"],
  "added_by": "Rohan",
  "added_at": "2026-05-20",
  "notes": "Figure 4 from Brown Heinz 2006. Cropped to remove caption."
}
```

### Field guide

| Field             | Allowed values                                                                 |
|-------------------|-------------------------------------------------------------------------------|
| `source_url`      | Direct URL to the image source. Required.                                     |
| `artist`          | Master's name (Sita Devi, Ganga Devi, Baua Devi, Mahasundari Devi, …) or "unknown master". |
| `year`            | Approximate year or decade. "unknown" acceptable.                             |
| `license`         | One of: `public-domain`, `CC0`, `CC-BY-4.0`, `CC-BY-SA-3.0`, `fair-use-research`, `permitted-by-museum`, `owned-by-user`. **No "unknown" or "all-rights-reserved"** unless you have a written permission record attached. |
| `permitted_uses`  | Subset of: `["LoRA training", "Kontext seed", "private reference"]`.          |
| `added_by`        | Your name.                                                                    |
| `added_at`        | ISO date (YYYY-MM-DD).                                                        |
| `notes`           | Free text. Cite figure number, page, museum accession ID.                    |

See `_general/_example_attribution.json` for the canonical filled-in
example. (That is the only example file in the corpus; do not commit
other `_*.json` files unless you update the audit script's ignore
list.)

---

## LoRA-readiness checklist

Before kicking off training, the corpus must satisfy:

- [ ] **At least 50 images** present across **at least 30 of the 40
      species**.
- [ ] **100% of images have `<image>.attribution.json` siblings.**
      Run `python3 brand/references/madhubani/_audit.py` and confirm
      `missing_attribution = 0`.
- [ ] **All images ≥ 1024×1024.** LoRA training resolution is
      typically 512–1024; smaller inputs teach low-frequency noise.
- [ ] **License audit clean.** No `unknown` and no
      `all-rights-reserved` without a written permission record in
      `notes`.
- [ ] **Per-species cap respected.** No species has more than 8
      references. The audit flags over-representation.
- [ ] **Artist diversity.** At least 4 distinct named masters
      represented across the corpus.

`_audit.py` reports against this checklist. When all checks pass,
the corpus is training-ready.

---

## How to add a reference

1. **Save the source image somewhere temporary** (e.g. `~/Downloads`).
2. **Verify license / attribution.** If you can't pin the license,
   stop. Don't add it. Move on.
3. **Rename** to `<species-slug>-<short-descriptor>.png` (or `.jpg`).
   Examples:
   - `tiger-sita-devi-1970s.png`
   - `peacock-ganga-devi-bharni-1985.jpg`
   - `cobra-baua-devi-naga-motif.png`
   - `_general-kohbar-lotus-square.png` (for `_general/`)
4. **Write the sibling `.attribution.json`.** Copy
   `_general/_example_attribution.json` as a starting point.
5. **Drop both files** into
   `brand/references/madhubani/<species-slug>/`.
6. **Run the audit:**
   ```bash
   python3 brand/references/madhubani/_audit.py
   ```
7. **Commit** with a message like:
   ```
   references: add tiger-sita-devi-1970s from Wikimedia Commons
   ```

---

## Privacy and copyright caveat

This corpus is **local-only and not redistributed**. The user
committing AI-trained outputs (the LoRA weights, generated images)
does **not** redistribute the source images — only the *learned
style*. Under fair-use research norms in most jurisdictions, training
a model on copyrighted works for research and personal use is
generally permitted; redistributing the source images is not.

For **commercial use of LoRA-trained outputs** (selling tees with
generated Madhubani-style art), you should:

1. Consult your own legal counsel.
2. Re-audit the corpus for explicit commercial-use permissions.
3. Credit and support the Mithila artisan community through
   organizations listed in `brand/madhubani/masters.json` —
   the Mithila Art Institute being the primary one.

The corpus directory is in `.gitignore`-eligible territory; **do not
push image files to a public remote**. The `.gitkeep` files and this
guide are the only intended remote-tracked content under
`brand/references/madhubani/`.

---

## Directory layout

```
brand/references/madhubani/
├── CURATION_GUIDE.md         (this file)
├── _audit.py                 (corpus audit script)
├── _general/                 (non-species-specific references)
│   └── _example_attribution.json
├── tiger/
├── peacock/
├── elephant/
├── cobra/
├── ... (38 more species)
└── indian-skimmer/
```

Forty-one species subdirectories (the 9 existing engine subjects
plus 32 catalog expansion species — `cobra` is kept as one slug per
animals.json convention) plus `_general/`. Each subdirectory ships
with a `.gitkeep` so the structure survives `git clean`.
