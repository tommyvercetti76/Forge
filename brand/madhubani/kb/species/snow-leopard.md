# Species: Snow leopard (*Panthera uncia*)

**Inherits from:**
- Order: [_orders/carnivora.md](../_orders/carnivora.md) — 4 limbs, forward eyes, fur, predator alertness
- Family: [_families/felidae.md](../_families/felidae.md) — retractile claws, vertical pupils, whiskers, mouth closed, 30 teeth
- Body type: [_body_types/lean-predator.md](../_body_types/lean-predator.md) — elongated body, long lean legs with visible joints, digitigrade, 4-zone decoration density

**This file writes only the deltas specific to snow leopard.**

---

## 1. Anatomical ground truth (species deltas)

Override / specify on top of felidae base:

- **Pelage:** Smoky grey-white base (NOT golden tan like leopard, NOT orange like tiger). Background fur is pale grey with white belly. **Dark rosette pattern** (open-center rosettes with internal small black dots) scattered across body, head, and tail. The rosettes are larger and more spaced than leopard rosettes.
- **Eye color:** **Pale grey-green** (NOT amber, NOT yellow). Distinguishes snow leopard from leopard at a glance.
- **Tail:** **Extraordinarily thick and long — 80-100% of body length.** The longest tail of any felid relative to body. Held in characteristic curled position when sitting; used as scarf in cold weather. This is the species' #1 visual differentiator.
- **Body proportions:** Stocky / compact relative to leopard. Head-body length 90-115 cm; substantially shorter than leopard (110-140 cm) but with that thick tail extending another 80-105 cm.
- **Paws:** Oversized, fur-covered (snowshoe adaptation for high-altitude snow). In side profile, the paw silhouette is broader and rounder than leopard's; visible fur tufts between toe pads.
- **Body fill (Madhubani override):** **EXCEPTION to the carnivora indigo-fill rule.** Snow leopard's species identity is so tied to its smoky-grey pelage that the folk-art conversion **keeps the smoky-grey body fill** (not indigo). The rosettes overlay as dark folk-medallions on the grey base. This is the only felid in our catalog where natural color is preserved for species fidelity.
- **Limb count (re-confirmed):** 4 legs visible in side profile (per body-type rule).

## 2. Sexual dimorphism

**Minimal** (per felidae table). Males ~10% body-weight heavier; otherwise visually identical. Render both sexes identically by default; do not specify "male snow leopard" or "female snow leopard" in prompts unless context demands it.

## 3. Photo references (8 photos, gender-balanced)

Stored in `brand/references/species/snow-leopard/`. License floor: CC-BY / CC-BY-SA / CC0 / PD strict.

| # | Sex | Description | Source (planned) | License | Status |
|---|---|---|---|---|---|
| 01 | male | Side profile, full body, standing on rock | Wikimedia Commons | CC-BY-SA 4.0 | to fetch |
| 02 | male | Full body in winter habitat (shows pelage + snow context) | iNaturalist research-grade | CC-BY 4.0 | to fetch |
| 03 | male | Head close-up (shows pale eye color) | Wikimedia Commons | CC0 / PD | to fetch |
| 04 | male | Paw / forelimb close (shows snowshoe paw fur) | Wikimedia Commons | CC-BY-SA 3.0 | to fetch |
| 05 | female | Side profile, full body | Wikimedia Commons | CC-BY-SA 4.0 | to fetch |
| 06 | female | Sitting with tail wrapped (shows tail thickness) | iNaturalist | CC-BY 4.0 | to fetch |
| 07 | female | Rosette pattern detail (close-up of flank) | Wikimedia Commons | CC-BY-SA 4.0 | to fetch |
| 08 | female | Stalking pose (low-body, head down) | Wikimedia Commons | CC-BY-SA 4.0 | to fetch |

Each photo will have a matching `.attribution.json` sidecar with: title, source_url, photographer, license, sha256, fetched_at.

## 4. Pose preferences (cited)

For folk-art Madhubani render:

| Priority | Pose | Citation |
|---|---|---|
| 1 (default) | side-profile-standing-alert | (general felid; see lean-predator.md) |
| 2 | sitting-with-tail-wrapped | McCarthy & Mallon (2016); behavioral observation of cold-weather tail-as-scarf |
| 3 | side-profile-stalking-low | Jackson (1996) field notes; hunting behavior |
| AVOID | rearing / mid-leap | Extremely rare in field (Jackson 1996); unnecessary anatomy hallucination risk |

## 5. Folk-art conversion (Mithila register, species-specific)

- **Body fill color (EXCEPTION):** smoky grey `#9aa6ad` — **not indigo** (only felid in catalog with natural-color preservation, to defend species identity against leopard/cheetah drift)
- **Pattern overlay:** dark rosette folk-medallions distributed across body, head, and tail (matching natural rosette density — ~30-40 rosettes total)
- **Tail emphasis:** Render the tail as the dominant visual element; should be visibly thick and as long as the body. **The tail thickness alone identifies the species.**
- **Decoration zones (4 — balanced density, fewer to preserve rosette readability):**
  1. tikka medallion on forehead
  2. dot-band collar at neck
  3. saddle lotus on back
  4. anklets at all 4 joints
- **Eye character:** Almond folk-eye, **pale grey-green** (not amber). Watchful, NOT cartoon.
- **Ear style:** Small rounded triangles (smaller than tiger/leopard ears).

## 6. Known v4 failure modes (from user grading)

From the v4 grading export:
- × 2 missing `rosette_spots` — model rendered as plain grey or with leopard-style spots
- × 2 missing `smoky_grey_white` — defaulted to leopard tan
- × 2 missing `wide_paws` — narrow leopard-style paws
- Common drift: becomes generic leopard or cheetah
- User feedback (text): "all snow leopards mid in Madhubani art"

These specific failures drive the v6 prompt clauses below.

## 7. Prompt clauses (data-grounded, supersedes earlier guesses)

### Subject (positive)
> "...smoky-grey-and-white body fill (NOT yellow leopard, NOT orange tiger), extraordinarily thick tail equal to body length held in characteristic curled position (the snow leopard's signature, never thin or short), prominent dark rosette folk-medallions distributed across body and tail (open-center rosettes with internal dots, larger and more spaced than leopard rosettes), pale grey-green almond eye (NOT amber), oversized fur-covered snowshoe paws visibly broader than leopard paws, small rounded triangular ears..."

### Anti-negative
> "no golden-tan body, no yellow body, no leopard tan coloring, no thin tail, no short tail, no missing tail, no leopard body proportions, no cheetah body proportions, no amber eye, no yellow eye, no narrow paws, no all-over leopard rosette density"

### Anatomical count constraints
```json
{
  "legs_visible": 4,
  "eyes": 2,
  "tail": 1,
  "ears": 2,
  "horns": 0
}
```

### Required decoration zones (priority order)
1. tikka medallion (forehead)
2. dot-band collar (neck)
3. saddle lotus (back)
4. anklets (every joint)

## 8. Cited research (4 species-specific open-access papers)

1. **Janečka, J.E. et al. (2017).** "Range-wide snow leopard phylogeography supports three subspecies." *Journal of Heredity* 108(6): 597-607. DOI: 10.1093/jhered/esx044. — **open via PMC.**
   - *Cited for:* Three subspecies designation (P. u. uncia northern, P. u. uncioides Himalayan, P. u. irbis Central Asian); taxonomic basis.
2. **Lyngdoh, S. et al. (2014).** "Prey preferences of the snow leopard (*Panthera uncia*): regional diet specificity holds global significance for conservation." *PLOS ONE* 9(2): e88349. DOI: 10.1371/journal.pone.0088349. — **fully open access.**
   - *Cited for:* Behavioral context — prey selection, habitat use, supports "stalking" as a primary hunting pose.
3. **McCarthy, T.M., Mallon, D., Jackson, R., et al. (eds.) (2016).** *Snow Leopards: Biodiversity of the World*. Academic Press. Author-archived chapters via Snow Leopard Trust.
   - *Cited for:* Comprehensive anatomy chapter; behavioral pose vocabulary (tail-wrapped sitting documented here).
4. **Jackson, R.M. (1996).** "Home Range, Movements and Habitat Use of Snow Leopard (*Uncia uncia*) in Nepal." PhD dissertation, University of London. — **open via Snow Leopard Network archive.**
   - *Cited for:* Field-observed pose frequencies; supports "side-profile-stalking" as biologically iconic; documents rearing/mid-leap as rare.

---
*Last updated: 2026-05-22. v6 prompts derive from this file.*
