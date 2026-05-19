# Madhubani Tee — Prompt Grammar Reference

The MinimalistTShirtEngine assembles each render's positive prompt from
a layered set of rules. This document is the operator's reference for
those layers — what each one does, when each fires, and which register
to choose.

For the *why* behind each rule, read `CATALOG_PLAN.md` §4–§6a and
`generated/madhubani_animals/_learning/PRINCIPLES.md`.

---

## The two Madhubani registers

The engine offers two `style.tradition` values for Madhubani work.
**Pick one per render.** They cannot be combined.

### `madhubani-contemporary`

> *"Madhubani / Mithila-inspired contemporary apparel translation:
> double black contour lines, almond eye, decorative feather/leaf
> infill, small floral symbols, handmade symmetry, and flat color
> fields."*

**Use when:**
- The design is for a mass-market tee, capsule basic, or volume product
- Vector-clean, screen-print-friendly polish is the priority
- You want the safest path with the fewest texture/anatomy surprises

**Masters cited:** Sita Devi (Madhubani painting), Ganga Devi (linework),
Mithila kohbar bird motifs.

### `madhubani-master-painter`  *(default for premium catalog)*

> *"Madhubani master-painter register: the work reads as if a Mithila
> wall-painting master had been commissioned to paint a single subject
> for an apparel print."*

**Use when:**
- The design is for the premium / gallery / collector tier
- Expressive character matters more than mass-market polish
- The piece is being marketed with a full artist card

**Six concrete shifts vs contemporary:**

| # | Shift | Effect |
|---|---|---|
| 1 | Hand-drawn line weight (varied along stroke) | Lines look painted, not vector-stroked |
| 2 | Composed palette (all 6 hexes in relationships) | Color is intentional dialogue, not just spread |
| 3 | Hand-drawn ornament (small irregularities per motif) | Decoration looks painted, never rubber-stamped |
| 4 | Character-bearing eyes (species + pose specific) | Eyes are not interchangeable across animals |
| 5 | Hand-painted texture cues (subtle pigment unevenness) | Reads as natural-fibre brush on absorbent paper |
| 6 | Reference standard = the ORIGINAL ART | Sita Devi kohbar, Ganga Devi bharni, Baua Devi matsya, pre-1970 bridal-chamber paintings |

**Masters cited:** Sita Devi (kohbar wall paintings), Ganga Devi
(bharni style), Baua Devi (matsya and naga motifs), Mithila kohbar
bridal-chamber tradition.

**Risk:** Shift #5 (hand-painted texture) may push the output beyond
screen-print viability. If it lands as noise rather than expression,
dial back or revert to contemporary for that subject.

---

## The universal rule stack (fires in both registers)

These rules layer on top of whichever tradition is active. Order matters
— they appear in this order at the top of the assembled prompt.

### 1. ANATOMY FIRST
*"Render a clean, anatomically correct animal silhouette FIRST;
decoration goes ON TOP. For quadrupeds in side profile, all FOUR legs
must be clearly visible."*

→ Fixes the v2 tiger missing-leg failure mode.

### 2. NO SIGNATURE, NO MARK, NO MONOGRAM
*"The composition contains ZERO artist marks, painter signatures, chop
seals, decorative glyphs, calligraphic flourishes, or text-like
squiggles in any corner or edge."*

→ Promoted to top-level positive after the v2 cobra had a stray
signature glyph despite "signature" being in the negatives list.

### 3. FACE & EXPRESSION  *(vibrant-folk Madhubani only)*
*"The almond eye conveys alertness, calm dignity, and folk-icon
presence. NEVER cartoonish surprise, NEVER round Western-cartoon eyes
with tiny dot pupils."*

→ Fixes the v2 macaque "round shocked cartoon eyes" failure.

### 4. COLOR FLOOR — NON-NEGOTIABLE  *(vibrant-folk Madhubani only)*
*"The rendered image MUST contain at least FOUR of these six folk hues
visibly: indigo, saffron, leaf-green, vermillion, cream, gold. The
animal's BODY FILL is a saturated color, NEVER blank cream, NEVER pure
black silhouette."*

→ Fixes the v1 mascot-logo regression (6 of 8 v1 designs were 2-tone).

### 5. BODY FILL OVERRIDE FOR LEAN PREDATORS  *(vibrant-folk only)*
*"Tigers, leopards, snakes, peacocks, deer, monkeys must NOT be drawn
as a flat black mascot silhouette. Their bodies are filled with a
saturated folk-art color and decorated INSIDE."*

→ Fixes the systematic v1 failure where lean-bodied subjects collapsed
into Western mascot silhouettes.

### 6. The motif and style descriptors (per-tradition)
- `MOTIF SYSTEM` — folk-icon grammar
- `CULTURAL / STYLE REGISTER` — contemporary or master-painter (the big choice)
- `DETAIL DENSITY`, `SYMMETRY`, `ORNAMENTAL ACCENTS` — style modifiers

### 7. SEVEN ZONES with ZONE CONFINEMENT  *(vibrant-folk only)*
*"Decorative motifs span SEVEN visible zones of the body: forehead,
ear/mane, neck, back/saddle, flank/shoulder, hip/haunch, leg anklets.
Each zone uses a different color combination. ZONE CONFINEMENT:
decoration is CONFINED to these seven zones — the body BETWEEN zones
remains a clean saturated color field, NEVER an all-over fabric
pattern."*

→ Fixes the v2 snow-leopard "patterned blob" failure where decoration
covered the entire body silhouette.

### 8. ORNAMENTAL AURA  *(vibrant-folk only)*
8–14 small Madhubani-style flourishes scattered in the negative space.

### 9. GROUND MARK  *(vibrant-folk only)*
A small Madhubani ground anchor below the figure (dotted line, paired
peepal leaves, or vine band). Replaces blank floating with anchored
folk-icon presence.

### 10. DENSITY CONTRACT  *(vibrant-folk Madhubani only)*
Replaces the generic MINIMALISM CONTRACT, which contradicts the
seven-zone density rule. *"The subject is FILLED with culturally
meaningful Madhubani decoration. Negative space around the subject
stays balanced, but the SUBJECT ITSELF is densely ornamented."*

### 11. LIMB PROPORTIONS
Body-type-aware leg/limb rules. Elephants get pillar-broad legs; cats
get muscular legs; birds get sturdy joints.

### 12. Composition discipline + apparel readability + text policy
Standard print-graphic constraints.

---

## What is REJECTED from the prompt (always, in both registers)

Western design-master references are **explicitly removed** from this
engine (Paul Rand, Saul Bass, Müller-Brockmann, Otl Aicher, Japanese
mon crests). v1 showed they pull the model toward black-silhouette
mascot logos when combined with Madhubani vibrant-folk instructions.

Also in the engine negatives list:
- western mascot logo, vector mascot head, flat sticker decal
- sports team logo style, single-color logo reduction
- Saul Bass silhouette mark, Paul Rand reduction mark
- monochrome silhouette, black silhouette body fill, blank-body silhouette
- two-tone screen-print mark only
- artist signature glyph, painter mark in corner, hand-drawn signature squiggle, calligraphic monogram

If you find any of these in a render, the engine has regressed —
check the recent commits to `style_engines.py`.

---

## Subject string anatomy

Per-pose subject strings should follow this anatomy:

```
single centered {animal_subject} {pose_action_clause} {orientation_clause},
premium Madhubani Mithila folk-art icon {painted in the master-painter
register, IF master-painter}, {body_type_anatomy_clause}, {signature_features},
{eye_character_clause carrying SPECIFIC CHARACTER for this pose},
mouth closed, {body_fill_color_clause with saturation cue},
decorated INSIDE with seven distinct zones of hand-drawn multi-color
Madhubani ornament — {per-zone breakdown if specific}, body BETWEEN
zones remains clean color field, bold hand-drawn double-contour
keylines with weight variation, {ground_mark_clause}, 8-12 small
ornamental flourishes in negative space, modern Indian streetwear
```

The per-pose templates in `brand/madhubani/poses.json` carry the
boilerplate; the per-animal entries in `brand/madhubani/animals.json`
fill the slots.

---

## What changes between versions

- **v1 → v2:** added COLOR FLOOR + BODY FILL OVERRIDE + DENSITY CONTRACT + GROUND MARK + stripped Western masters.
- **v2 → v3:** added ANATOMY FIRST + NO SIGNATURE (promoted to top-level) + FACE & EXPRESSION rule + ZONE CONFINEMENT.
- **v3 → master-painter:** added `madhubani-master-painter` tradition with six expressive shifts; original engine path remains as `madhubani-contemporary`.
