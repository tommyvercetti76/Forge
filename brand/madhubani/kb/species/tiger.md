# Species: Tiger (*Panthera tigris*)

**Inherits from:**
- Order: [_orders/carnivora.md](../_orders/carnivora.md)
- Family: [_families/felidae.md](../_families/felidae.md)
- Body type: [_body_types/lean-predator.md](../_body_types/lean-predator.md)

## 1. Anatomical ground truth (species deltas)

- **Pelage:** Background coat is **deep rust-orange (NATURAL)** with **bold black vertical stripes**. White underside (belly, chest, chin, inner legs, throat). **Stripes are unique per individual** (like fingerprints).
- **Eye color:** **Amber gold** with vertical-slit pupil in light. Distinguishes tiger from snow leopard (pale grey-green) and leopard (amber-gold but smaller eye).
- **Body proportions:** Largest cat in the world. Indian tiger (Bengal subspecies) — adult males 200-260 cm head-body + 80-100 cm tail.
- **Face markings:** **WHITE markings** on cheeks, chin, around eyes, and BLACK markings (ocelli — ear spots) on the back of the ears. The white cheek ruff is dramatic in mature individuals.
- **Tail:** Long (about 1/3 of body length), with prominent black rings, ending in solid black tip.
- **Limb proportions:** Heavy muscular legs (vs cheetah's lean racer-legs), powerful shoulders.

## 2. Sexual dimorphism

**Moderate** — males ~25% heavier, broader head, fuller cheek ruff, larger overall. Females sleeker. Visual differences are subtle in folk-art rendering (males = more imposing presence). Default render is male.

## 3. Photo references (8 photos, gender-balanced)

Stored in `brand/references/species/tiger/`. License floor: CC-BY / CC-BY-SA / CC0 / PD strict.

| # | Sex | Description | Source | Status |
|---|---|---|---|---|
| 01 | male | Side profile, full body, full stripe display | Wikimedia / iNat | to fetch |
| 02 | male | Head close-up — amber eye + white face markings | Wikimedia | to fetch |
| 03 | male | Stalking-low pose — hunting silhouette | iNat | to fetch |
| 04 | male | Full body in habitat — Bengal grassland or forest | Wikimedia | to fetch |
| 05 | female | Side profile, slightly sleeker build | Wikimedia | to fetch |
| 06 | female | Female with cubs (if available) | iNat | to fetch |
| 07 | female | Stripe pattern close-up | Wikimedia | to fetch |
| 08 | female | Resting / lying pose | iNat | to fetch |

## 4. Pose preferences (cited)

| Priority | Pose | Citation |
|---|---|---|
| 1 (default) | side-profile-standing-alert | (general felid) |
| 2 | side-profile-stalking-low | Schaller (1967) — *The Deer and the Tiger* |
| 3 | sitting-with-tail-curled | Sunquist & Sunquist (2002) |
| AVOID | mid-leap | Anatomy hallucination risk |
| AVOID | roaring-mouth-open | Dental hallucination risk |

## 5. Folk-art conversion (Mithila register, species-specific)

- **Body fill (CRITICAL — defeats FLUX's natural-tiger-orange):**
  - Choice A (Mithila-canonical override): **deep-indigo `#1a2952` body fill** with bold black stripe pattern overlaid (defeats the natural-orange prior — what most v4 tigers failed on).
  - Choice B (selective natural-color preservation): **deep rust-orange `#cc4d1a` body fill** with bold black stripes. ONLY use this for editorial decisions to preserve tiger's iconic color.
  - **Default for v6: Choice A** (indigo) — to fix the v4 failure mode where tigers came out cinematic-orange instead of folk-art.
- **Stripe rendering:** **Bold vertical folk-painted black stripes** across body, neck, legs, and tail. Stripes must be clean folk-painted bands, NOT photographic fur. Each stripe is a single confident brush stroke.
- **White face markings:** Preserved as folk-white panels — cheeks, chin, eye-corner whiskers, inside ears. Critical for species identity.
- **Eye character:** Almond folk-eye in amber-gold, with vertical-slit pupil rendered as thin almond inside outer almond.
- **Decoration density:** **balanced** (4-5 zones; stripes are species-mark, additional decoration must not obscure them)
- **Required zones for tiger:**
  1. Tikka medallion on forehead
  2. Dot-band collar at neck
  3. Saddle lotus on back
  4. Joint anklets
  5. Stripe pattern overlay (preserves species identity)

## 6. Known v4 failure modes (from user grading)

- Marked FAIL with reasons: **wrong_palette · cartoon · wrong_style**
- All v1/v2/v3 tigers marked FAIL ("all tigers mid in Madhubani art")
- User verbal note: "Tiger in Cinematic mode looks great" — implies tiger works WHEN model lets the natural orange show; FAILS when forced into Madhubani register
- DRIFT: model wants to render the cinematic Nat-Geo orange tiger; can't reconcile with Madhubani folk register

## 7. Prompt clauses (data-grounded, addresses v4 failures)

### Subject (positive)
> "...flat-filled with saturated DEEP INDIGO #1a2952 as the dominant base color (the folk-art canvas — DEFEATS the model's pretrained natural-tiger-orange prior), with bold black folk-painted vertical tiger stripes across body, neck, legs, and tail (stripes are clean confident brush strokes, NOT photographic fur, NOT natural-orange background), preserved white folk-panels on cheeks + chin + inside ears (white face markings are non-negotiable species identity), amber-gold almond folk-eye with vertical-slit pupil..."

### Anti-negative
> "no natural tiger orange body color, no rust-orange body fill, no Nat-Geo wildlife photo register, no photographic fur texture, no cinematic-tiger coloring, no national-geographic palette, no missing white face markings, no missing black stripes, no missing ear ocelli"

### Anatomical count constraints
```json
{
  "legs_visible": 4,
  "eyes": 2,
  "tail": 1,
  "ears": 2,
  "stripes_minimum": 8
}
```

## 8. Cited research (4 species-specific open-access papers)

1. **Schaller, G.B. (1967).** *The Deer and the Tiger: A Study of Wildlife in India.* University of Chicago Press. — partial open via author archives.
   - *Cited for:* Foundational tiger behavior + ecology in Indian subcontinent; supports stalking pose.
2. **Luo, S.-J. et al. (2004).** "Phylogeography and genetic ancestry of tigers (*Panthera tigris*)." *PLOS Biology* 2(12): e442. DOI: 10.1371/journal.pbio.0020442. — **fully open access (PLOS).**
   - *Cited for:* Tiger subspecies phylogeny; supports Bengal tiger (*P. t. tigris*) identity.
3. **Mondol, S. et al. (2009).** "Why the Indian subcontinent holds the key to global tiger recovery." *PLOS Genetics* 5(8): e1000585. DOI: 10.1371/journal.pgen.1000585. — **fully open access (PLOS).**
   - *Cited for:* Indian tiger population structure + conservation context.
4. **Goodrich, J. et al. (2015).** "*Panthera tigris*." *The IUCN Red List of Threatened Species*. — **fully open access (IUCN).**
   - *Cited for:* Tiger species account + global distribution + body-form details.

---
*Last updated: 2026-05-22. v6 prompts derive from this file.*
