# Madhubani Animal Tee Catalog — Master Plan

**Scope:** 60 animals × 4 poses = **240 mastered designs**
**Author:** Rohan + Claude
**Date:** 2026-05-18
**Status:** Planning. No build yet. This document is the single source of truth
for what we agree on before any code lands.

---

## Revision history

**v2 — 2026-05-18 (this revision).** Rohan revised the production model:
- **Not batch generation.** Rendering one animal-set (4 poses) at a time.
- **Workflow gate:** review → identify gaps → retry once → review → move on or flag.
- **Expressive register lift:** shift from "contemporary apparel translation"
  to "Mithila master-painter register" — looser linework, palette richness,
  expressive eyes with character, hand-painted texture cues.
- **AI-artist provenance:** every design ships with a citation + methodology
  card so each piece carries its tradition acknowledgment, stylistic
  influences, and generation method — like a real artist signing a work.

Sections §6, §7, §10, §11, §13, §14 are rewritten below. Two new sections
added: §6a (Expressive Register) and §6b (AI-Artist Citation & Methodology).

---

## 1. Why this document exists

Going from 8 hand-tuned designs (the Indian Animals v1 → v3 work) to 240
production designs is a category change, not a quantity change. Up to now the
process has been:

> *Write a subject string → render → eyeball → iterate prompt → repeat.*

That doesn't scale to 240. At 60 animals × 4 poses × 3 candidate seeds you
are looking at ~720 renders, ~12–18 hours of compute on Apple Silicon, and
about 8,000 small decisions if you make them one at a time. The only way
through is to **freeze decisions upfront** (pose taxonomy, animal list,
quality rubric, palette) so the per-design work shrinks from "creative
decision" to "is this output above the bar — yes/no."

This plan is what we freeze.

---

## 2. The four poses (the most important decision in the whole plan)

The catalog only feels like a *set* if every animal uses the same four
named poses. Otherwise we have 240 one-offs. Recommended taxonomy, designed
to travel across mammals, birds, and reptiles:

### Pose 01 — `standing-alert`  (the hero pose)
Full-body side profile, all four legs / both legs planted, head looking
forward or slightly toward camera, calm dignified expression. This is the
catalog's flagship — every animal must be recognizable in this pose alone.
The first impression a customer gets from a thumbnail.

### Pose 02 — `seated-rest`
Resting position appropriate to the species: cats and primates seated with
forelimbs upright, snakes coiled with hood lowered, birds perched with feet
folded, large herbivores reclining (camel-fold for hooved animals). Quieter,
more contemplative — pairs well with neutral / cream tees.

### Pose 03 — `signature-action`
The single most iconic action for that species: tiger crouched, peacock
fanned tail, cobra reared with hood spread, elephant trumpeting trunk raised,
horse rearing, eagle wings spread, hummingbird hovering. The "wow shot."

### Pose 04 — `frontal-portrait`
Head-and-shoulders frontal mark, almond eyes facing forward, decorative
crown/halo motif above. This is the close-detail design that rewards close
inspection — best for the back of a tee or as a pocket-print companion to
one of the full-body poses.

**Why this taxonomy survives 60 animals:** every species has these four
states. A serpent's "standing-alert" is its body extended straight; its
"seated-rest" is coiled. A bird's "standing-alert" is perched; its
"signature-action" is wings-spread. The poses generalize.

**What we reject:** "walking" as a pose. v2 proved it: walking quadrupeds
in side profile drop the far legs more often than they keep them. Standing
alert sidesteps the leg-occlusion failure mode entirely.

---

## 3. The 60 animals (proposed — for your review)

Per your call: Indian wildlife + African wildlife + Birds as their own
series. Twenty each is the cleanest split, totals to 60, and gives each
sub-series enough depth to be browseable on a storefront category page.

### Indian wildlife (20)
Royal Bengal Tiger · Indian Elephant · King Cobra · Blackbuck · One-horned
Rhinoceros · Snow Leopard · Lion-tailed Macaque · Sloth Bear · Gaur (Indian
Bison) · Sambar Deer · Nilgai · Asiatic Lion · Indian Wolf · Striped Hyena
· Indian Pangolin · Gangetic Dolphin · Dhole (Indian Wild Dog) · Hanuman
Langur · Indian Leopard · Chinkara Gazelle

### African wildlife (20)
African Lion · Cheetah · Giraffe · Plains Zebra · Hippopotamus · Mountain
Gorilla · White Rhino · African Bush Elephant · African Leopard · Spotted
Hyena · Thomson's Gazelle · Wildebeest · Cape Buffalo · African Wild Dog ·
Meerkat · Aardvark · Springbok · Warthog · Okapi · Sable Antelope

### Birds (20)
Indian Peacock · Great Hornbill · Common Kingfisher · Indian Eagle Owl ·
Rose-ringed Parakeet · Crested Serpent Eagle · Hummingbird · Sarus Crane ·
Greater Flamingo · African Grey Parrot · Secretary Bird · Hoopoe · Painted
Stork · Mandarin Duck · Scarlet Macaw · Indian Roller · Hoopoe · Toucan ·
Crowned Crane · Brahminy Kite

These are *first drafts* — replace any you don't love with a personal
favourite. The system doesn't care.

**Per-animal metadata we need to capture for each entry:**

- `slug` — kebab-case ID (`royal-bengal-tiger`)
- `display_name` — human title
- `series` — `indian` / `african` / `bird`
- `body_type` — `heavy-quadruped` / `lean-predator` / `serpent` / `bird` /
  `primate` (drives which anatomy rules fire)
- `body_fill_color` — the default saturated hex from the 6-color palette
  (some animals naturally read indigo, others walnut, others forest-teal)
- `signature_features` — short string of must-include anatomy (e.g. tiger:
  "stripes, long curved tail, almond eye"; peacock: "crest, fanned tail with
  eye motifs, long neck")
- `signature_action` — what their action-pose actually is ("crouched ready
  to leap" vs "wings spread mid-flight")

This lives in **`brand/animals.json`**, one record per animal. The render
pipeline reads from this file — no more 240 hand-written subject strings.

---

## 4. The engine — what stays from v3, what evolves

The current `MinimalistTShirtEngine` (post-v3 edits) already enforces:
- ANATOMY FIRST contract (top-level)
- NO SIGNATURE rule (top-level)
- FACE & EXPRESSION rule (vibrant-folk only)
- COLOR FLOOR — at least 4 of 6 palette hexes must appear
- BODY FILL OVERRIDE for lean predators
- SEVEN ZONES decoration with ZONE CONFINEMENT
- GROUND MARK for vibrant-folk subjects
- DENSITY CONTRACT instead of minimalism contract (vibrant-folk path)
- No Western design masters (Sita Devi / Ganga Devi / Mithila kohbar only)

These are working. We keep them.

**What the engine needs ADDED for catalog scale:**

- **Body-type dispatch.** Today, anatomy rules are written generically.
  At scale, the engine should read `body_type` from the animal record and
  inject body-type-specific rules:
  - `heavy-quadruped` → pillar legs, broad shoulders, sturdy hocks
  - `lean-predator` → saturated body fill not silhouette, all four legs
    visible, proportional muscular limbs
  - `serpent` → continuous coil, no broken segments, hood proportional to
    body, calm closed mouth as default
  - `bird` → two sturdy legs on visible perch / ground line, head and tail
    proportional, wing visible against body in resting pose
  - `primate` → almond eyes (NOT round cartoon eyes), proportional hands
    and feet, tail length appropriate to species

- **Pose dispatch.** Each of the four pose templates gets its own engine-
  level positive block, applied based on `pose` config. This is what
  guarantees pose consistency across all 60 animals.

- **Per-series accent.** Indian animals lean indigo/walnut body fills with
  saffron-vermillion ornament. African animals can lean warmer (walnut,
  ochre, deeper reds). Birds get the most permissive palette since species
  vary wildly. Encoded as series-level palette anchors in the engine.

---

## 5. The generator — the cross-product script

Current beta implementation: `bin/forge_madhubani.py` is the catalog driver for
`list / show / render / promote / flag / card / chat`. A future bulk wrapper
can sit on top of it, but the live workflow should call this CLI directly.

A future batch wrapper would:

1. Loads `brand/animals.json` and `brand/poses.json`
2. For each (animal × pose) pair, builds a `MinimalistTShirtConfig` with
   the merged metadata
3. Optionally renders multi-seed (default: 3 seeds per design, seeds
   derived deterministically from a stable digest such as SHA-256 or Adler32,
   never Python's process-salted built-in hash)
4. Writes outputs to `generated/madhubani_animals/{series}/{slug}/{pose}/`
5. Drops a `manifest.json` at the top with every design's status, seed
   chosen, render time, quality scores

This replaces the per-batch shell scripts (`_render_indian_animals_v*.sh`)
with one tool. Re-running a single failed (animal, pose) is one command,
not a script edit.

---

## 6. The set-at-a-time workflow (REVISED v2)

The catalog is built **one animal at a time**, where a "set" = **1 animal × 4
poses = 4 designs**. We do not batch. We do not multi-seed. We work the way
a print studio does: master one mini-collection, ship it or shelve it, move on.

### The loop

```
┌──── Pick next animal from catalog ────┐
│                                       │
▼                                       │
1. RENDER set       — all 4 poses, 1 seed each (4 renders, ~5 min)
   │
   ▼
2. REVIEW           — open all 4 side by side, score each against rubric
   │
   ▼
3. IDENTIFY GAPS    — which of the 4 poses have problems, what kind
   │
   ▼
4. RETRY (once)     — re-render gapped poses with adjustments:
                       (a) different seed, OR
                       (b) per-pose subject string tweak, OR
                       (c) both
                      Maximum 1 retry per pose. No infinite loops.
   │
   ▼
5. REVIEW v2        — same rubric on the retried renders
   │
   ▼
6. DECISION         — for each of the 4 poses, one of:
                       ✓ MASTERED → ship to /mastered/{slug}/{pose}/
                       ⚑ FLAGGED  → keep best attempt in /flagged/{slug}/{pose}/
                                   with notes for later return
                       ✗ REJECTED → archive in /attempts/{slug}/{pose}/v{N}/,
                                   move on (we'll come back in a later pass)
   │
   ▼
7. ARTIST CARD      — generate /mastered/{slug}/ARTIST_CARD.md for the set
                       (see §6b for schema)
   │
   ▼
8. NEXT ANIMAL      ────────────────────────────────────────┘
```

### Why retry-once-then-flag (and not retry-until-perfect)

Open-ended iteration is how 4 designs becomes a week of babysitting. The
retry-once gate forces a binary call: *the prompt + engine can produce
this, or it can't yet.* If it can't on retry, we **flag** (keep the best
attempt aside with notes) and move on. Flagged animals queue for a
second pass after we've mastered the engine further — usually after a
LoRA training cycle or a prompt revision triggered by patterns in the
flag pile.

This is also how you avoid burning emotional energy on the hard cases
while easier wins are sitting idle.

### Set-level scoring rubric (applied in step 2 and step 5)

Each of the 4 poses gets a pass/fail on these checks (same auto-rubric
from v1 of the plan, kept because the criteria are good):

| # | Check | Method |
|---|---|---|
| 1 | Color floor — ≥4 of 6 palette hexes present | PIL color quantization, ΔE ≤ 15 |
| 2 | Corners clean (no signature, no glyph) | 4× 100×100 corner sample, ≥95% within ΔE 10 of cream |
| 3 | Subject centered, 50–80% canvas width | Edge-detect bounding box of main mark |
| 4 | Body fill is saturated color, not blank | Centroid sample ≠ black/cream |
| 5 | Anatomy correct (4 legs / 2 legs / coiled body / wings present) | Visual check — no automation possible yet |
| 6 | Expression carries character (not cartoon, not blank) | Visual check |
| 7 | Reads as Madhubani-inspired at 4-inch thumbnail | Visual check, downscale + step back |

Auto-checks (1-4) gate the design before human review. Visual checks
(5-7) are the actual master/flag/reject call. **A set is MASTERED only
when all 4 poses pass all 7 checks.** Otherwise it's mixed — some
mastered, some flagged.

### What "flagged" really means

A flagged pose is parked, not abandoned. Its directory contains:
- `attempt-1.png` and `attempt-2.png` (the two seeds we tried)
- `directive.json` for each
- `FLAG_NOTES.md` written by Rohan — what specifically failed, what to
  try next (different pose phrasing? new seed? engine rule needed?)

Flagged poses get revisited in batched "flag clearance" passes after
every 5–10 animals, or after any engine/LoRA improvement. The expectation
is most flags resolve on the second engine revision; persistent flags
suggest the animal needs to be substituted or its pose needs rethinking.

---

## 6a. Expressive register — the Mithila master-painter shift (NEW v2)

The v1–v3 prompt is built around a "Madhubani-contemporary apparel
translation" register — restrained, screen-print-friendly, vector-clean.
That register produces *competent* tees but not *expressive* ones. Rohan
wants to shift toward the **Mithila master-painter register** — the
quality you'd see in a Sita Devi original wall painting, not in a
boutique apparel translation of one.

### What changes in the prompt

Six concrete shifts, layered on top of the existing engine:

1. **Linework — varied hand weight, not uniform vector outline.**
   *"Double-contour keylines are HAND-DRAWN with slight weight variation
   along their length — thicker at the natural pressure points (jaw, hip,
   knee), thinner at the trailing strokes. Lines are CONFIDENT but not
   mechanically uniform. Avoid the look of stroked vector paths."*

2. **Palette — richness over compliance.**
   The current rule says "at least 4 of 6 palette hexes." Master-painter
   register says: **"All 6 hexes present AND used in deliberate
   relationships — saffron and vermillion as warm dialogue, indigo
   and forest-teal as cool counterpoint, gold as accent jewelry, cream as
   breath. Color is COMPOSED, not just spread."**

3. **Ornament — varied within zone, not stamped.**
   v3's seven-zone block treats each zone as a slot for a motif. Master-
   painter shifts to: **"Each zone's motif is hand-drawn with small
   irregularities — petals slightly different sizes, dot spacing
   organically uneven, vine curls each unique. The decoration looks PAINTED,
   not rubber-stamped."**

4. **Eyes — expressive, character-bearing.**
   The current FACE & EXPRESSION rule says "calm, dignified, never
   cartoonish." Master-painter extends it: **"The almond eye carries SPECIFIC
   character appropriate to the species and pose — a tiger in standing-alert
   has watchful intensity; a peacock in signature-action has proud display;
   a macaque in seated-rest has gentle contemplation; an elephant in
   frontal-portrait has ancient ceremonial gravity. Eyes are NOT
   interchangeable across animals."**

5. **Hand-painted texture cues.**
   *"Allow subtle, restrained texture in the body fills — the faintest hint
   of pigment unevenness, a slight grain in the saturated color fields, as
   if painted with a natural-fibre brush on absorbent paper. NOT photographic
   grain, NOT noise, NOT distressed — the texture is the texture of
   handmade pigment on handmade surface."*
   *(This is the riskiest shift for print viability — if it shows up as
   noise on screen-print masters, scale it back. Acceptable for POD/DTG.)*

6. **Reference standard shift.**
   Current prompt cites "Daram, Bombay Shirt Company, Suta, Mithila Art
   Institute prints" — those are *translations*. Master-painter cites:
   **"Sita Devi's mid-century kohbar wall paintings; Ganga Devi's bharni
   style; Baua Devi's matsya and naga compositions; the painted
   bridal-chamber wall paintings of Madhubani district pre-1970.
   Reference standard is the ORIGINAL ART, not its commercial apparel
   adaptation."**

### How this lands in the engine

A new tradition value: `madhubani-master-painter` (in addition to the
existing `madhubani-contemporary`). The engine reads which one is active
and applies the six shifts above when the master-painter variant is on.
Both remain available — `madhubani-contemporary` for cleaner mass-market
work, `madhubani-master-painter` for the expressive premium tier.

### What this is NOT

- Not a license to abandon print viability — every render still has to
  pass the corner-cleanliness, color-floor, anatomy checks.
- Not photorealism, gradients, or atmospheric lighting — those negatives
  stay.
- Not "more ornament" — actually it's more *intention* per ornament, not
  necessarily more ornaments. A master painter's piece is rarely the
  most decorated; it's the most *deliberate*.

### Validation gate before adopting master-painter as default

Render one set (4 poses of one animal — recommend the Rhino since it was
the v3 winner) in `madhubani-master-painter` mode. Compare side-by-side
with the v3 rhino set. If 3 of 4 master-painter renders feel more
expressive AND still print-viable, adopt it as the catalog default.
Otherwise iterate the six shifts above and re-test.

---

## 6b. AI-artist citation & methodology (NEW v2)

Each mastered design ships with provenance — the way a human artist would
sign and contextualize a piece. This serves three goals at once:

1. **Ethical positioning.** Honest about AI-generation; honest about
   the tradition we're drawing from; honest about not being authentic
   Mithila artisanship.
2. **Commercial differentiator.** Collectors respond to provenance.
   "AI-generated wildlife tee" is a commodity; "AI-generated tee
   acknowledging the Sita Devi line tradition, methodology disclosed,
   tradition tagged" is a thoughtful product.
3. **Internal reproducibility.** Two years from now, when you want to
   know how a specific design was made, the answer is in the file
   alongside the design, not lost in a chat log.

### Two artifacts per mastered set

#### (i) `directive.json` — machine-readable (extends what we already write)

The engine already drops a directive sidecar per render. We extend the
schema with new fields:

```json
{
  "engine": "minimalist-tshirt",
  "positive": "...",
  "negatives": [...],
  "runtime": {...},
  "seed": 8105,

  "provenance": {
    "tradition_cited": "Madhubani / Mithila folk-painting tradition",
    "tradition_region": "Mithila region of Bihar, India",
    "tradition_gi_status": "Geographically Indicated; this work is INSPIRED BY, not authentic Madhubani",
    "stylistic_influences": [
      {"master": "Sita Devi", "what_we_drew_from": "kohbar wall-painting line grammar, almond-eye treatment"},
      {"master": "Ganga Devi", "what_we_drew_from": "bharni-style fill rhythm, dot-and-petal aura"},
      {"master": "Mithila kohbar tradition", "what_we_drew_from": "bird and animal motif vocabulary"}
    ],
    "methodology": {
      "model": "FLUX.1-dev",
      "runtime": "mflux on Apple Silicon",
      "steps": 24,
      "guidance": 5.5,
      "resolution_base": "1280×1280",
      "resolution_final": "5120×5120 via RealESRGAN 4×",
      "post_processing": ["transparent-bg via luminance threshold"],
      "lora_stack": [],
      "human_curation": "Selected from 1 of 2 attempted seeds by Rohan"
    },
    "iteration_history": [
      {"date": "2026-05-18", "version": "v3", "outcome": "MASTERED", "notes": "..."}
    ],
    "honest_framing": "This is an AI-generated apparel design that draws stylistic inspiration from the Madhubani folk-painting tradition of Mithila, Bihar. It is not authentic Madhubani art and the artisan community of Mithila are the legitimate custodians of that tradition. Sales of this design do not benefit Mithila artisans directly; if this work resonates with you, please also consider purchasing from artists at the Mithila Art Institute (mithilaartinstitute.org) and similar organizations."
  }
}
```

#### (ii) `ARTIST_CARD.md` — human-readable, per set

One markdown card per animal-set (so 4 poses share one card), structured
for both internal reference and as the source of storefront product
descriptions. Template:

```markdown
# Royal Bengal Tiger — Madhubani-Inspired Tee Series

## About this set
Four poses of the Royal Bengal Tiger rendered in the Mithila
master-painter register. Standing-alert, seated-rest, signature-action
(crouched ready to leap), and frontal-portrait. The set is designed
to function as either four standalone tees or as a coherent capsule.

## Tradition acknowledged
**Madhubani (Mithila) folk-painting tradition** — Mithila region,
Bihar, India. A wall-painting and paper tradition practiced primarily
by women of the region for over 2,500 years. Madhubani holds
Geographical Indication (GI) status in India.

**This series is Madhubani-INSPIRED, not authentic Madhubani.** The
custodians of the authentic tradition are the artisans of Mithila.
We acknowledge their living art and recommend
[Mithila Art Institute](https://mithilaartinstitute.org) and similar
organizations for those who wish to support practitioners directly.

## Stylistic influences cited
- **Sita Devi** — kohbar wall-painting line grammar; almond-eye treatment
- **Ganga Devi** — bharni-style fill rhythm; dot-and-petal ornamental aura
- **Baua Devi** — matsya and naga compositional motifs
- **Mithila kohbar tradition** — bird-and-animal motif vocabulary

## Methodology
- **Model:** FLUX.1-dev via mflux on Apple Silicon
- **Engine:** MinimalistTShirtEngine (custom), Madhubani master-painter register
- **Render parameters:** 24 steps, guidance 5.5, 1280×1280 base
- **Final resolution:** 5120×5120 via RealESRGAN 4× upscale
- **Process:** One-set-at-a-time workflow; render → review → retry once → master/flag
- **Human curation:** Each pose's final image selected from up to 2
  generation attempts by Rohan against a 7-point quality rubric
- **Code, prompts, and full directive sidecars** are versioned in this
  project's repository for full reproducibility.

## Per-pose notes
- **Standing alert** — Mastered on seed 8101 (first attempt)
- **Seated rest** — Mastered on seed 8201 after one retry
  (first attempt had stiff tail position)
- **Signature action (crouched)** — Mastered on seed 8301
- **Frontal portrait** — Flagged; first two attempts produced
  ill-proportioned face. Set aside for return after engine revision.
```

### Where the artist card surfaces in commerce

- **Inside the shipped tee package**: a small printed insert card (one per
  customer, one per set, ~3"×5") with a short version: tradition cited,
  one paragraph of influences, QR code to full card online.
- **Storefront product description**: the "About this piece" section is
  auto-extracted from the card.
- **Internal repo**: source of truth for what we made and how.

### Generator

Use `bin/forge_madhubani.py card {animal}`. It reads the mastered set and emits
`ARTIST_CARD.md` as the last step of the workflow loop.

---

## 7. The brand LoRA — deferred to after the first 50 mastered (REVISED v2)

In the set-at-a-time model we accumulate mastered designs gradually
rather than dumping 720 candidates at once. Defer LoRA training until
we have **50 mastered designs across at least 10 different animals.**

Why that threshold:
- Fewer than 50 → not enough training signal; LoRA overfits to the few
  examples and produces samey output
- Spread across ≥10 animals → ensures the LoRA learns style, not just
  "how to draw a tiger"
- Mastered, not candidates → trains the LoRA on the bar we want, not on
  the noise we're trying to clear

Practically: at ~12 animals mastered (48 designs, near the threshold),
queue a LoRA training cycle. After training, re-run the workflow loop
on the next 5 animals with the LoRA loaded. If retry rates drop and
expression improves, adopt the LoRA as the engine default and consider
re-mastering flagged designs from earlier animals.

You already have `BRAND-LORA.md` in the repo — that doc is the
"how to train" playbook; this section is the "when to train" decision.
Training itself: ~4–6 hours on rented H100 (~$10–15), one overnight on
Apple Silicon.

---

## 8. Production pipeline (mostly already exists)

What the engine already does for free on every render:
- Auto-saves directive.json sidecar (provenance — what prompt made this)
- Auto-generates `.transparent.png` sibling (alpha cutout for print)
- `--upscale 4x` flag → 5120×5120 print-ready via RealESRGAN
- Gallery row captured per render for rating

Important current boundary: `bin/forge_madhubani.py promote` promotes the
reviewed base/transparent artifacts. Optional 5120 production files are still
an explicit upscale follow-up until production upscale is wired into promote.

**What's missing for shippable storefront assets:**

- **Mockup compositor.** A 30-line PIL script that drops the transparent
  PNG onto a cream-tee mockup template and a black-tee mockup template,
  outputting `{slug}-{pose}-mockup-cream.jpg` and `{slug}-{pose}-mockup-
  black.jpg`. Total of 480 mockups (240 × 2 colors). Runs in minutes.
- **Export bundler.** Per-design folder containing `print-5120.png`,
  `transparent-print.png`, `mockup-cream.jpg`, `mockup-black.jpg`,
  `directive.json`, `listing.md`. Zip per series for handoff to fulfillment.

---

## 9. Storefront listing prep — auto-generated

For each (animal × pose) we generate:

- **Title** — formula: `{display_name} — {pose_human_name} — Madhubani-Inspired Folk-Art Tee`
  - e.g. *"Royal Bengal Tiger — Standing Alert — Madhubani-Inspired Folk-Art Tee"*
- **Description** — template with three slots: animal context (1 line,
  e.g. "the most iconic predator of the Indian subcontinent"), pose context
  (1 line, "captured in alert standing profile"), production context
  (1 line, "premium screen-print quality on heavyweight cotton")
- **Tags** — `madhubani`, `mithila`, `folk-art`, `{series}`, `{body_type}`,
  `{slug}`, `{pose}`, plus 4–5 generic tags (`indian-art`, `streetwear`,
  `wildlife-tee`, `cotton-tee`, `unisex`)
- **SKU** — `MAD-{SERIES}-{SLUG}-{POSE}-{SIZE}-{COLOR}`

All generated from the catalog file. One CSV import to Shopify / Etsy /
Printful / Printify per series. Zero hand-typing for 240 listings.

---

## 10. Compute budget (REVISED v2 — per-set cadence)

Per-render: ~75 seconds at 24 steps on Apple Silicon (FLUX dev, 1280×1280).

### Per animal-set (1 animal × 4 poses, set-at-a-time workflow)

| Step | Renders | Wall clock |
|---|---|---|
| Initial render (4 poses) | 4 | ~5 min |
| Retry pass (worst case: all 4 retry) | 4 | ~5 min |
| Upscale mastered to 5120 (avg 3 of 4 mastered) | 3 | ~2 min |
| Mockup compositing (cream + black per pose) | 6 | <1 min |
| Artist card generation | — | <30 sec |
| **Per set total (active GPU time)** | **~11** | **~12–15 min** |

Add ~10–15 min of human review time per set (open all 4 side by side,
score against rubric, decide retry adjustments, do master/flag call).

**Per-set wall clock end to end: ~25–30 minutes of focused work.**

### Catalog totals at this pace

Mastering 60 animals = 60 sets = 60 × 25–30 min = **25–30 hours of
focused work**. Spread across realistic cadence (2–4 sets per session,
3–5 sessions per week), that's **6–10 weeks** to a complete catalog.
At the lower end if a few sessions are dedicated catch-up days; at the
higher end if you average 1 session a week.

### Where the LoRA training fits

Roughly after the first 12 animals mastered (~6 hours of focused work
spread across 3 weeks), queue LoRA training. The training itself runs
in the background (overnight Apple Silicon or a rented H100 long lunch).
After training, the per-set cadence usually drops by 20–30% because the
retry rate falls.

### What's NOT in the budget

- One-time engine work to support master-painter register and per-set
  workflow scripts (~1 day of code, planned in §14).
- Periodic "flag clearance" passes — usually one half-day per 10
  animals, to revisit flagged poses with whatever engine improvements
  have landed.
- Storefront load (CSV import, image uploads, listing copy edits) —
  not GPU work, but real wall time. Plan a half-day per series.

---

## 11. Quality bar — what "mastered" means

A design is **mastered** when it passes ALL of:

1. Auto-rubric score ≥ 80 (see Section 6)
2. Color floor compliance verified
3. Anatomy clean (4 legs / 2 legs / coiled body / wings — as appropriate)
4. Face expression dignified (no cartoon eyes, no mascot vibes)
5. Corners clean (no signatures, no glyphs)
6. Recognizable as both *this species* AND *Madhubani-inspired folk art*
   at 4 inches wide (thumbnail readability test)
7. Approved by Rohan in gallery review

Target: 240/240 mastered. Realistic: 200/240 mastered after first LoRA
pass, with the remaining 40 needing a second iteration. Stretch: 230/240.

---

## 12. Legal / positioning note

**Madhubani** has Geographical Indication (GI) status in India. Strictly,
that mark is reserved for artisans in the Mithila region of Bihar.
Premium retailers (Daram, Bombay Shirt Company, Suta) market as
**"Madhubani-inspired"** or **"Mithila-inspired"** rather than authentic
Madhubani. We do the same in our storefront copy. This isn't a legal
showstopper for selling — but it's the honest framing and it inoculates
us against authenticity pushback from the Mithila artisan community.

In the prompt itself, naming Sita Devi and Ganga Devi as *stylistic
influences* is fine; the art we generate is influenced by them, not by
them. We should never claim the output IS authentic Mithila painting.

---

## 13. Open decisions — what's left to call (REVISED v2)

### Resolved in v2 of this plan

- ~~**Set size**~~ — decided: 1 animal × 4 poses = 4 designs per set.
- ~~**Expression target**~~ — decided: Mithila master-painter register.
- ~~**Workflow shape**~~ — decided: render → review → retry once → master/flag.
- ~~**LoRA timing**~~ — decided: after first 12 animals mastered (~50 designs).
- ~~**Series-vs-parallel**~~ — decided implicitly by set-at-a-time workflow:
  master one animal end to end before starting the next; series order
  is whichever animal you feel like that day.
- ~~**First animal (validation case)**~~ — decided: **Rhinoceros** (v3 winner;
  strong baseline for master-painter A/B).
- ~~**Texture shift #5**~~ — decided: **include with caution.** Land it in
  the master-painter register, evaluate on the rhino set, dial back if
  it reads as noise rather than expression.
- ~~**Artist card citation roster**~~ — decided: **Sita Devi, Ganga Devi,
  Baua Devi, Mithila kohbar tradition** — locked as the standard four.

### Still open — your call (does not block starting; affects shipping)

1. **Per-pose pricing tiers** — do all four poses sell at the same price,
   or is `frontal-portrait` a lower tier (simpler) and `signature-action`
   a premium tier (more elaborate)? Affects listing strategy.
2. **Storefront target** — Shopify? Etsy? Printful drop-ship? This shapes
   the export format and metadata schema.
3. **Print method** — POD/DTG (lower margin, zero inventory) vs.
   screen-printed runs (higher margin, inventory risk, needs CMYK
   separations). Texture shift #5 may push us toward POD/DTG anyway.
4. **Insert card production** — the printed 3"×5" provenance insert
   from §6b — print yourself, use Moo, ship via fulfillment partner,
   or skip until volume justifies?

### To not be open — defer past v2

- Marketing copy beyond product descriptions
- Photography of physical samples
- Mythological/composite tier (Phase 2 expansion, not catalog v1)

---

## 14. Phased timeline (REVISED v2 — set-at-a-time cadence)

### Foundation work (one-time, before the first set)

| Phase | What happens | Duration |
|---|---|---|
| **F1** — Engine: pose dispatch | Add 4 pose templates to engine; route per-pose rules | 0.5 day |
| **F2** — Engine: body-type dispatch | Read `body_type` from animal record; route per-body anatomy rules | 0.5 day |
| **F3** — Engine: master-painter register | Add `madhubani-master-painter` tradition + the six §6a shifts | 0.5 day |
| **F4** — Schema: `brand/animals.json` | Write the 60-animal catalog with per-animal metadata | 0.5 day |
| **F5** — Set workflow tool | `bin/forge_madhubani.py render/promote/flag` — render one set and manage retry/master/flag/archive directory structure | implemented beta |
| **F6** — Artist card generator | `bin/forge_madhubani.py card` — emit ARTIST_CARD.md from mastered directives | implemented beta |
| **F7** — Validation set | Run the workflow on the Rhino (v3 winner baseline) to validate everything end-to-end before scaling | 0.5 day |
| **Foundation total** | | **~4 days of code** |

### Mastering cadence (per animal, after foundation)

| Step | Duration |
|---|---|
| Run set workflow (render + auto-score) | ~15 min GPU |
| Human review of 4 poses | ~10 min |
| Retry adjustments (if needed) | ~5 min |
| Retry render | ~5 min GPU |
| Final review + master/flag decision | ~5 min |
| **Per set** | **~25–30 min focused work** |

### Realistic schedule

| Milestone | What | When |
|---|---|---|
| Foundation done | F1–F7 above | Week 1 |
| First 5 sets mastered | Validate workflow with real animals | Week 2 |
| First 12 sets mastered | LoRA training threshold | Week 3–4 |
| LoRA trained + adopted | Engine retuned, retry rate drops | Week 4 |
| First 30 sets mastered | Halfway, momentum compounding | Week 6 |
| All 60 sets mastered | Initial catalog complete | Week 8–10 |
| Flag-clearance passes | Resolve flagged poses with engine improvements | Week 10–11 |
| Production assets + storefront | Upscale, mockup, listing, load | Week 12 |

That's a 12-week realistic schedule assuming 3–5 mastering sessions per
week. Faster is possible if you treat it as a primary focus; slower if
it's a weekends-only project.

---

## 15. What this plan deliberately does NOT cover (yet)

- Marketing copy beyond product descriptions (Instagram strategy, etc.)
- Photography of physical samples
- Sizing curve / inventory management
- Customer service / returns
- Color profile management for actual screen-printers (CMYK separations,
  ink underbase, etc.) — needed only if going non-POD
- International shipping / sales tax / GST registration

These are all real concerns at launch but are downstream of the catalog
existing. Plan them after Phase 6.

---

## 16. Recommended next steps (REVISED v2)

1. **Read §13 open decisions** and tell me your calls on the five that
   remain — especially #1 (which animal we start with as the workflow
   validation case).
2. **Approve the §6a expressive-register shifts** or push back on any of
   the six. The riskiest is shift #5 (hand-painted texture cues) — if
   you want me to skip it for screen-print safety, say so now and I'll
   leave it out of the `madhubani-master-painter` register.
3. **Approve the §6b artist card schema** or revise it. The current
   draft cites Sita Devi, Ganga Devi, Baua Devi and the kohbar
   tradition — if you want more, fewer, or different names, tell me
   before the schema goes into code.
4. Once 1–3 are decided, ask me to do the **Foundation work (F1–F7)** in
   §14 in order. F1–F4 are no-render; you can review the engine and
   schema before any GPU spins up. F5–F7 unlock the actual workflow loop.
5. After foundation: pick the first animal, run one set through the
   workflow, and we calibrate against the result.

The biggest risk under the new model isn't burning GPU on a bad
foundation (the v1 risk) — it's **prompt-iterating one set forever**
instead of using the retry-once-then-flag gate. The whole point of the
workflow is to treat flagging as a healthy outcome, not a failure.
