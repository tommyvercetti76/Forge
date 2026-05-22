# Species: Indian Cobra (*Naja naja*)

**Inherits from:**
- Order: [_orders/serpentes.md](../_orders/serpentes.md)
- Family: [_families/elapidae.md](../_families/elapidae.md)
- Body type: [_body_types/serpent.md](../_body_types/serpent.md)

## 1. Anatomical ground truth (species deltas)

- **Body coloration:** Variable — light brown, dark olive, jet-black, or banded. **Spectacle marking on the back of the spread hood is more reliable than body color for identification.**
- **Hood:** Expandable neck flap formed by elongated cervical ribs flaring outward. Width ~10-15 cm when fully spread. Triggered when threatened or displaying.
- **Spectacle marking:** Distinctive **WHITE or PALE design on the BACK of the spread hood** — typically a "V" or "O" or "spectacle-glasses" pattern. Visible from rear or 3/4 view. This is THE Indian cobra identity marker.
- **Eyes:** Round pupils (NOT vertical-slit like vipers). Medium-sized, watchful.
- **Head shape:** **Oval-rounded** (NOT triangular like vipers). Distinguishes elapidae from viperidae.
- **Tongue:** Single forked tongue. Pink-black coloration. Flicked out for scent-sampling.
- **Body length:** 1.5-2 m typically. Body slender (~10:1 length-to-width when straight).
- **Scales:** Smooth (NOT keeled). Regular dorsal rows.
- **Ventral scales:** Large transverse plates on belly. Lighter in color (cream/pale) than dorsal scales.

## 2. Sexual dimorphism

**Visually none.** Males slightly longer; otherwise identical. Render without sex specification. Photo references are 8 mixed-pose rather than sex-split.

## 3. Photo references (8 photos, mixed-pose)

Stored in `brand/references/species/cobra/`. Heavy emphasis on **spread-hood pose** + **forked tongue extended**.

| # | Pose | Description | Source | Status |
|---|---|---|---|---|
| 01 | spread-hood-front | Full-spread hood, head facing camera, spectacle visible | Wikimedia / iNat | to fetch |
| 02 | spread-hood-side | Side profile of spread hood + body coil | Wikimedia | to fetch |
| 03 | spread-hood-tongue-out | Hood spread + forked tongue extended (action shot) | iNat | to fetch |
| 04 | coiled-S-resting | Body in S-curve, hood NOT spread, head NOT raised | Wikimedia | to fetch |
| 05 | head-close-up | Close-up showing round pupils + tongue | Wikimedia | to fetch |
| 06 | glide-straight | Locomotion, body in flowing curves | iNat | to fetch |
| 07 | scale-pattern-detail | Body close-up showing smooth scale pattern | Wikimedia | to fetch |
| 08 | spectacle-marking-rear | Rear-view of hood showing spectacle pattern | iNat | to fetch |

## 4. Pose preferences (cited)

| Priority | Pose | Citation |
|---|---|---|
| 1 (default) | **spread-hooded** | Wüster & Thorpe (1989) — *Naja naja* species accounts |
| 2 | coiled-S-resting | (general serpentes) |
| 3 | glide-straight | (general serpentes) |
| AVOID | standing-on-body | Snakes can't stand |
| AVOID | mid-strike-mouth-open | Dental/fang hallucination risk |
| AVOID | hood-spread-while-moving | Cobras spread hood while stationary |

## 5. Folk-art conversion (Mithila register, species-specific)

- **Body fill color:** Indigo `#1a2952` override default. Indian cobra color variability means folk-indigo serves as canonical body.
- **Hood spectacle (CRITICAL):** **Preserve the V or O spectacle pattern on the back of the spread hood as a clean folk-white panel.** When the hood is shown from rear or 3/4 angle, this marking must be visible.
- **Scale pattern:** Translate dorsal scale rows as **regular folk-leaf or folk-diamond pattern** following the body's curves. NOT individual dots. Light ventral band visible on belly side.
- **Hood rendering:** The spread hood is rendered as a **flat folk-disc behind the head**, decorated with the spectacle pattern as a central medallion. Edges of the hood show slight scalloped folk-line detail.
- **Tongue (NON-NEGOTIABLE):** **EXACTLY ONE forked tongue** when extended. Y-shape, forked at the tip. NEVER two tongues. NEVER duplicated. This is the species' top failure mode.
- **Eye character:** Round pupil inside almond folk-eye. Watchful and alert; not aggressive.
- **Madhubani Nāga heritage:** Snake iconography is deeply rooted in Mithila tradition. Render with cultural respect to Nāga aesthetic.
- **Decoration density:** **balanced** (3-4 zones) — over-decoration ruins serpentine flow.
- **Required zones for cobra:**
  1. Head crown medallion (small tikka above eyes)
  2. **Hood spectacle marking** when hood spread
  3. Body scale pattern (continuous, folk-translated)
  4. Belly/ventral band (lighter than dorsal)

## 6. Known v4 failure modes (from user verbal callout)

- v4 cobra: marked FAIL with no specific anatomy_missing tags
- User verbal note: **"Problem was double tongue."** The cobra rendered with two parallel tongues — a hallucination class.
- Earlier v2: "two-tongues hallucination" documented as original fail example
- The Madhubani render in v4 also occasionally drifted to viper-style triangular head, blurring species identity.

## 7. Prompt clauses (data-grounded, addresses v4 failures)

### Subject (positive)
> "...with EXACTLY ONE single forked tongue extending from the mouth — there is ONE tongue, not two; the tongue is a single Y-shape (forked at the tip), NEVER two parallel tongues, NEVER duplicated tongues, NEVER any hallucinated extra tongue. The cobra has ONE mouth and ONE tongue. This is non-negotiable — the rendered image must show exactly one tongue. With the iconic spread hood extended behind the head — the species' defining display posture; with the white V-shaped spectacle marking on the back of the spread hood preserved as folk-white panel; with rounded oval head shape (NOT triangular like vipers); with round pupils inside the almond folk-eye..."

### Anti-negative
> "no two tongues, no double tongue, no parallel tongues, no hallucinated extra tongue, no tongue duplicates, no triangular viper-head, no vertical-slit cobra pupils (cobras have round pupils), no missing spectacle marking on hood, no all-over body pattern that obscures serpentine flow, no limbs, no legs, no claws, no feet"

### Anatomical count constraints
```json
{
  "legs": 0,
  "eyes": 2,
  "tongue": 1,
  "hood": 1,
  "body": 1
}
```

## 8. Cited research (4 species-specific open-access papers)

1. **Wüster, W. & Thorpe, R.S. (1989).** "Population affinities of the Asiatic cobra (*Naja naja*) species complex in south-east Asia: reliability and random resampling." *Biological Journal of the Linnean Society* 36(4): 391-409. DOI: 10.1111/j.1095-8312.1989.tb00497.x. — partial open via author repository.
   - *Cited for:* Indian cobra (*N. naja*) species complex; spectacle marking as species-stable feature.
2. **Wallach, V., Wüster, W. & Broadley, D.G. (2009).** "In praise of subgenera: taxonomic status of cobras of the genus *Naja* Laurenti (Serpentes: Elapidae)." *Zootaxa* 2236: 26-36. — open via Zootaxa.
   - *Cited for:* Indian cobra (*N. naja*) taxonomy; subgenus placement.
3. **Whitaker, R. & Captain, A. (2008).** *Snakes of India: The Field Guide.* Draco Books. — partial open via author repository.
   - *Cited for:* Indian cobra anatomy + pose vocabulary; supports hood-spread + spectacle marking details.
4. **Sunagar, K. et al. (2014).** "Intraspecific venom variation in the medically significant Southern Pacific Rattlesnake (*Crotalus oreganus helleri*): biodiscovery, clinical and evolutionary implications." *Journal of Proteomics* 99: 68-83. DOI: 10.1016/j.jprot.2014.01.013. — author repo open (cited for general elapid-vs-viperid behavioral distinctions, not for venom content).
   - *Cited for:* Behavioral context for elapid front-fanged display behavior.

---
*Last updated: 2026-05-22. v6 prompts derive from this file. Cobra is THE Mithila Nāga subject — rendering quality is culturally + portfolio-critical.*
