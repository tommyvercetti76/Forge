# Body type: Cetacean

**Inherits from:** [_orders/cetacea.md](../_orders/cetacea.md)
**Inherited by species:** irrawaddy-dolphin (and future cetacean additions)

Note: whale-shark is NOT a cetacean — it's a cartilaginous fish (Rhincodontidae) and uses its own body type file (not built yet; defer until catalog expands). This file applies only to true cetaceans.

## 1. Motor pattern (the cetacean silhouette)

- **Body shape:** Fully streamlined, fusiform (torpedo). Smooth surface.
- **Limbs:** **NO hindlimbs (vestigial only, invisible).** Forelimbs are **pectoral fins (flippers)** — flat paddles.
- **Visible appendages in side profile:**
  - 1 pectoral fin (lateral)
  - 1 dorsal fin (top of back)
  - 1 fluke (tail) — **horizontal flukes**, NOT vertical
- **Skin:** Smooth, hairless, no scales. Often grey or dark-toned naturally.
- **Eyes:** 2, small relative to body, lateral.
- **Blowhole:** 1 on top of head (not visible in pure side profile but visible from 3/4 angle).
- **Beak / rostrum:** Family-specific — most delphinids have prominent rostrum; **irrawaddy-dolphin uniquely has a rounded blunt head (no prominent rostrum)** — diagnostic.
- **Tail (fluke):** **HORIZONTAL** orientation (perpendicular to body's vertical axis), located at the very end of the body. Distinguishes cetaceans from fish (which have vertical tail fins).

## 2. Anatomical count constraints

For ALL cetaceans in **swimming-side** pose:

| Feature | Required count | Note |
|---|---|---|
| Limbs / legs | **0** | NO mammalian legs visible. Forelimbs only as flippers. |
| Pectoral fins visible | 1 in side profile | Lateral flipper, flat paddle shape |
| Dorsal fin | 1 | Top of back, position + shape varies by species (irrawaddy: small triangular, set far back) |
| Fluke | 1 | At body tail-end, HORIZONTAL orientation |
| Eyes | 1 visible (side profile) | Small almond folk-eye, lateral position |
| Blowhole | 0 visible in pure side profile (1 if angled view) | Top of head |
| Mouth | 1, closed by default | Teeth present in delphinids but mouth closed |
| Body | 1 continuous fusiform shape | No clear neck-body division |

## 3. Decoration grammar (Mithila register for cetaceans)

- **Decoration density:** **minimal** to **balanced** (3-4 zones). Cetaceans have smooth skin — over-decoration is unnatural for the form.
- **Required zones (priority order):**
  1. Head/blowhole-area tikka medallion
  2. Body color field with folk-pattern flow lines (suggesting motion through water)
  3. Dorsal-fin folk band
  4. Fluke decorative pattern (folk-stripes on the horizontal fluke surface)
- **Water context:** Madhubani folk tradition has rich water + fish iconography. Cetacean renders can include folk-water elements (parallel wave lines, fish companions) as background — culturally appropriate and reinforces the marine setting.

## 4. Default pose preferences (cited)

Cetacean pose vocabulary:
- **swimming-side** (default) — body horizontal, profile view, pectoral fin + dorsal fin + fluke all visible
- **surfacing** — body partially above water, dorsal fin breaking surface
- **breaching** — body partially or fully out of water, leaping vertical; common for some species
- **resting-floating** — body horizontal at surface, calm pose

**AVOID:**
- Vertical-tail (fish style)
- Limbs of any kind
- Standing posture
- Wing-shaped pectoral fins (flippers are flat paddles, not wings)

## 5. Cited research (4 open-access sources)

1. **McGowen, M.R. et al. (2020).** "Phylogenomic resolution of the cetacean tree of life using target sequence capture." *Systematic Biology* 69(3): 479-501. DOI: 10.1093/sysbio/syz068. — **open via PMC.**
   - *Cited for:* Cetacean phylogeny; supports delphinid placement.
2. **Berta, A., Sumich, J.L. & Kovacs, K.M. (2015).** *Marine Mammals: Evolutionary Biology*, 3rd ed. Academic Press. — partial open via author repositories.
   - *Cited for:* Marine mammal anatomy + locomotion; pose vocabulary.
3. **Smith, B.D. et al. (2008).** "*Orcaella brevirostris*: Mekong River subpopulation." *The IUCN Red List of Threatened Species*. DOI: 10.2305/IUCN.UK.2008.RLTS.T39427A10221511.en. — **fully open access (IUCN).**
   - *Cited for:* Irrawaddy dolphin (*Orcaella brevirostris*) anatomy + distribution + behavior.
4. **Stacey, P.J., Leatherwood, S. & Baird, R.W. (1994).** "*Pseudorca crassidens*." *Mammalian Species* 456: 1-6. American Society of Mammalogists. — open via ASM repository.
   - *Cited for:* Delphinid body-form + species accounts; supports family-level locomotion rules.

---
*Last updated: 2026-05-22. Inherited by irrawaddy-dolphin and future cetacean species.*
