# Family: Felidae (cats)

**Inherits from:** [_orders/carnivora.md](../_orders/carnivora.md)
**Inherited by species:** tiger, sundarbans-tiger, snow-leopard, indian-leopard, asiatic-lion
**Inherited by body type (operational):** [_body_types/lean-predator.md](../_body_types/lean-predator.md)

## 1. Family-universal anatomical features (deltas from Carnivora)

All Felidae share these features regardless of species:

- **Claws:** Retractile (all extant felids except cheetah). In folk-art side profile, claws are **not visible by default** — show pad-shape under foot, claws sheathed. Drawing extended claws should be reserved for "attacking" pose.
- **Pupils:** Vertical slit in bright light (round at night). For folk-icon render, **vertical-slit pupil** is the cat-family marker that distinguishes felidae from canidae (round pupils).
- **Whiskers:** 4 rows of horizontal whiskers above mouth + brow whiskers + cheek whiskers. In folk-icon render, render as 2-3 stylized whisker strokes per side.
- **Ears:** Triangular, erect, with white spot on back (most felids — "ocelli") — visible from rear view; in side profile, one ear's back may be partially visible.
- **Tongue:** Single (NEVER two — that's a cobra/serpent hallucination class).
- **Teeth:** 30 teeth total (dental formula 3.1.3.1 / 3.1.2.1). Render mouth closed by default.
- **Tail:** Long (60-100% of body length). Held in species-specific position (see species files).

## 2. Sexual dimorphism (family-level)

Felid sexual dimorphism varies markedly. Render carefully — wrong-sex caricatures damage species identity.

| Species | Dimorphism level | Visual cue (male vs female) |
|---|---|---|
| Tiger | Moderate | Males ~25% heavier, broader head, fuller cheek ruff. Females sleeker, smaller. |
| Lion | **Extreme** | Mane in males only (chestnut-to-black). Females manless. **Always render male with mane unless explicitly "lioness."** |
| Snow leopard | Minimal (~10% male weight advantage) | Visually near-identical; render as "snow leopard" without sex specification by default. |
| Indian leopard | Subtle (~20% weight) | Males larger, broader head, fuller cheek tuft. |
| Cheetah | Minimal | Near-identical. |

## 3. Photo references

Maintained at species level (see `species/<slug>.md` files for 8 photos each = 4M + 4F where dimorphic). The family file does not curate photos.

## 4. Pose preferences (family-level)

Felid-specific pose vocabulary (additive to body-type defaults):

- **side-profile-stalking-low** — head lowered, body horizontal, weight on forelimbs, tail extended for balance. Hunting silhouette. Cited: Schaller (1972) for big cats.
- **sitting-with-tail-wrapped** — upright sit, tail curled around forelegs. Cat-family characteristic. Cited: Sunquist & Sunquist (2002).
- **prowling-side** — between standing and stalking; head level, body slightly low.
- **flehmen-response** is NOT recommended for folk-art (too anatomically specific; render mouth closed instead).
- **mid-leap** is NOT recommended (anatomy hallucination risk).

## 5. Folk-art conversion (Mithila register, felid-specific)

- **Body fill:** indigo `#1a2952` override (per Carnivora/Madhubani convention) — defeats FLUX's pre-trained tiger-orange, leopard-tan, snow-leopard-grey.
- **Species fur pattern:** **Layered onto the indigo body fill as folk-pattern translation**, NOT as natural fur. Specifically:
  - Tiger: bold black tiger-stripe bands across body and tail rendered as folk-painted stripes
  - Snow leopard: dark rosette spots as folk-medallions on smoky-grey (snow leopard alone breaks the indigo-fill rule — see species file)
  - Leopard: rosette clusters as folk-medallions
  - Lion: solid indigo body, no spots; male carries indigo mane with vermillion highlights
- **Eye character:** Almond folk-eye with **watchful ceremonial gravity** (carnivore alertness). Vertical-slit pupil rendered as a thin almond shape inside the larger almond eye, NOT a round black dot.
- **Decoration density:** balanced (4-5 zones — see lean-predator body type). The fur pattern is the species mark; decoration is contextual ornament.
- **Required zones (priority order):**
  1. tikka medallion (forehead)
  2. dot-band collar (neck)
  3. saddle/back panel (lotus medallion)
  4. anklets at every joint (knee, hock)
  5. *species-specific:* fur-pattern overlay on body (tiger stripes, leopard rosettes, etc.)

## 6. Indian felid species in our catalog

| Slug | Latin | Park | Body type | Sex dimorphism |
|---|---|---|---|---|
| tiger | *Panthera tigris tigris* | Various (Bandhavgarh, Kanha, Ranthambore) | lean-predator | Moderate |
| sundarbans-tiger | *P. t. tigris* (subpopulation) | Sundarbans NP | lean-predator | Moderate |
| snow-leopard | *Panthera uncia* | Hemis NP, Ladakh | lean-predator | Minimal |
| indian-leopard | *Panthera pardus fusca* | Various (Sariska, Nagarhole) | lean-predator | Subtle |
| asiatic-lion | *Panthera leo persica* | Gir NP, Gujarat | lean-predator | **Extreme (mane)** |

## 7. Cited research (4 open-access sources)

1. **Kitchener, A.C. et al. (2017).** "A revised taxonomy of the Felidae: The final report of the Cat Classification Task Force of the IUCN Cat Specialist Group." *Cat News* Special Issue 11. IUCN. — **fully open access.**
   - *Cited for:* Authoritative current felid taxonomy + subspecies designations (e.g. Asiatic lion = *P. l. persica*, Indian leopard = *P. p. fusca*).
2. **Johnson, W.E. et al. (2006).** "The Late Miocene radiation of modern Felidae: a genetic assessment." *Science* 311(5757): 73-77. DOI: 10.1126/science.1122277 — open via author repository / PMC.
   - *Cited for:* Felid phylogeny; divergence of Panthera lineage from other big cats.
3. **O'Brien, S.J. & Johnson, W.E. (2007).** "The evolution of cats." *Scientific American* 297(1): 68-75. — open via author repository.
   - *Cited for:* Accessible synthesis of cat evolution + species distribution.
4. **Werdelin, L., Yamaguchi, N., Johnson, W.E. & O'Brien, S.J. (2010).** "Phylogeny and evolution of cats (Felidae)." In: Macdonald & Loveridge (eds.). *The Biology and Conservation of Wild Felids*. — author-archived open.
   - *Cited for:* Comprehensive Felidae phylogeny + morphological evolution.

---
*Last updated: 2026-05-22. 5 species in catalog inherit from this file.*
