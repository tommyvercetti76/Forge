# Body type: Bird (terrestrial / wading / display-capable)

**Inherits from:** [_orders/aves.md](../_orders/aves.md)
**Inherited by species:** All avian species in the catalog (currently: peacock, sarus-crane, painted-stork, greater-flamingo, great-indian-hornbill, indian-skimmer; growing to ~44 with branch expansion)

This file collects body-type-level rules that apply across multiple bird families. Family-specific rules (e.g., peacock's display, hornbill's casque) live in family files.

## 1. Motor pattern (the bird silhouette)

Universal across all birds in our catalog:

- **Limbs:** 2 legs + 2 wings (= 4 appendages total but not 4 limbs in the mammalian sense).
- **Legs:** **TWO** — visible from drumstick down. Render BOTH legs in standing pose (or explicitly one-leg-tucked for cranes/flamingos).
- **Wings:** **TWO**, folded against body at rest (default) OR spread for display/flight. In side profile, the visible wing's outline runs from shoulder to tail-base.
- **Feet:** 3 forward toes + 1 back toe typically (anisodactyl). Render visible toe structure on the ground — NOT paw, NOT hoof.
- **Beak:** **ONE** — single, family-specific shape. NEVER duplicated.
- **Eyes:** **TWO** — lateral in most species (one visible in side profile). Almond folk-eye.
- **Ears:** Visible openings under feathers (not pointed structures).
- **Tail:** Rectrices (tail feathers), visible behind body. Length varies hugely (peacock train extreme; songbird short).
- **Feathers:** Continuous body covering — NO fur, NO scales (except on legs where reptilian scales remain).

## 2. Anatomical count constraints (the "limbs missing" + extra-limb fix)

For ALL birds in **standing-side-profile** pose:

| Feature | Required count | Note |
|---|---|---|
| Legs visible | 2 | TWO legs, not four. Common AI failure: rendering bird with 4 legs (mammal hallucination). Both legs must be visible UNLESS species-canonical one-leg-tucked pose (flamingo, sometimes crane). |
| Wings visible | 1 (side profile) | Visible wing tucked against body OR spread |
| Eyes | 1 visible | Lateral eye, almond folk-shape |
| Beak | 1 | Family-specific shape |
| Tail | 1 (rectrices, varies hugely in length) | Render based on species; peacock has the extreme train, others modest |
| Feet — toes per foot | 3 forward + 1 back | Anisodactyl standard; render visible toe outlines |

## 3. Decoration grammar (Mithila register for birds)

- **Decoration density:** **balanced** to **ornate** depending on species:
  - **Ornate (6-7 zones):** Peacock (train IS most of the decoration), sarus crane, hornbill — large/display birds
  - **Balanced (4-5 zones):** Flamingo, painted stork, skimmer — emphasize body color + leg detail
- **Required zones (priority order):**
  1. Crown / head crest (tikka medallion + species-specific crest if present)
  2. Wing-feather panel (folk-feather pattern on visible wing)
  3. Body color field with dot accents
  4. Tail-feather panel (varies by species — flamboyant or modest)
  5. Leg-anklet rhythm (where leg structure prominent — cranes, flamingos)
  6. *Species-specific:* casque (hornbill), throat patch (cranes), beak detail
- **Madhubani heritage note:** Birds are particularly canonical in Mithila tradition. Lotus-and-bird, fish-and-bird, peacock-medallion are all classical motifs. Lean into these when possible.

## 4. Default pose preferences (cited)

Bird pose vocabulary:
- **standing-side-profile** (default) — both legs visible, body upright, wings folded
- **one-leg-tucked-standing** — single leg visible on ground, other tucked into body feathers — flamingo/crane signature
- **wading** — partial in water (legs in water), body above; storks, herons
- **swimming-floating** — body on water surface; skimmers, ducks
- **perching** — on branch, both feet gripping, body upright
- **displaying-full** — courtship pose; peacock-fan, crane-dance
- **in-flight-soaring** — wings spread, body horizontal; raptors, large birds
- **in-flight-stooping** — wings tucked, fast descent; raptors hunting

**AVOID:**
- Mid-flight transitions (between soar and flap) — hallucinated wing positions
- Asymmetric two-legged stance with one leg shorter (geometric error)
- 4 legs (mammal hallucination)
- Multiple beaks
- Beak chimera (mixing two species' beak shapes)

## 5. Cited research (4 open-access sources)

1. **Prum, R.O. et al. (2015).** "A comprehensive phylogeny of birds (Aves) using targeted next-generation DNA sequencing." *Nature* 526(7574): 569-573. DOI: 10.1038/nature15697. — **open via PMC.**
   - *Cited for:* Modern bird phylogeny; family relationships.
2. **Mayr, G. (2017).** *Avian Evolution: The Fossil Record of Birds and its Paleobiological Significance.* Wiley. — partial open.
   - *Cited for:* Avian anatomy + body-plan evolution; supports universal feathers + 2-leg + 2-wing rules.
3. **Gill, F.B. (2007).** *Ornithology*, 3rd ed. W.H. Freeman. — partial open via author archives.
   - *Cited for:* Comprehensive bird body-form + behavioral pose reference.
4. **del Hoyo, J. (chief ed.) (2020).** *Birds of the World.* Cornell Lab of Ornithology. — partial open via species accounts on `birdsoftheworld.org`.
   - *Cited for:* Family-by-family pose preferences + canonical postures.

---
*Last updated: 2026-05-22. Inherited by all bird species; ~44 species will inherit from this when catalog hits 100.*
