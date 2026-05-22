# Species: Indian Peafowl / Peacock (*Pavo cristatus*)

**Inherits from:**
- Order: [_orders/aves.md](../_orders/aves.md)
- Family: [_families/phasianidae.md](../_families/phasianidae.md)
- Body type: [_body_types/bird.md](../_body_types/bird.md)

## 1. Anatomical ground truth (species deltas)

- **Body coloring (male):** Iridescent **sapphire-blue** neck and breast. Greenish-bronze body. Brown wings. The iridescence shifts with viewing angle.
- **Body coloring (female / peahen):** Mottled brown, white belly, plain. NO iridescent neck.
- **Train (male only):** **Elongated upper tail-covert feathers**, NOT the actual tail. Train length can reach 1.5 m in mature males. Contains 100-200 "eye-spot" (ocellus) ornaments arranged in a fan when displayed.
- **Eye-spots (ocelli):** Each is a concentric medallion: gold-bronze outer ring, sapphire-blue inner ring, dark center. Distributed across the train.
- **Crown crest:** Spray-shaped crest of 20-25 wire-thin feathers each ending in a small disc — fan-like spray on the crown.
- **Beak:** Pale gray, moderate, slightly downcurved.
- **Legs:** Pale gray, long, strong (galliform — adapted for ground living).
- **Tail (the actual tail, hidden under the train):** Short, gray-brown. Only visible when train is folded down.
- **Female adaptations:** No train, no iridescent neck, smaller crown crest (still present but modest), brown cryptic body. Designed for camouflage while incubating.

## 2. Sexual dimorphism

**EXTREME** — among the strongest dimorphism in birds. Male = full iridescent display. Female = brown cryptic. Render decisions:
- **Default species rendering = MALE in full display.** This is THE peacock identity.
- Female (peahen) is a separate rendering goal — render distinctly when explicitly asked.

## 3. Photo references (8 photos, 4M + 4F)

Stored in `brand/references/species/peacock/`.

| # | Sex | Description | Source | Status |
|---|---|---|---|---|
| 01 | male | Full train fan in display (THE iconic image) | Wikimedia | to fetch |
| 02 | male | Side profile body, train trailing behind folded | Wikimedia | to fetch |
| 03 | male | Head close-up — sapphire neck + spray crest | Wikimedia | to fetch |
| 04 | male | Ocellus detail close-up | Wikimedia | to fetch |
| 05 | female | Side profile peahen — brown cryptic body | Wikimedia | to fetch |
| 06 | female | Female with chicks (family group) | iNat | to fetch |
| 07 | female | Female head close — modest crest | Wikimedia | to fetch |
| 08 | female | Female full body | Wikimedia | to fetch |

## 4. Pose preferences (cited)

| Priority | Pose | Citation |
|---|---|---|
| 1 (default for male) | **displaying-full-fan** | Petrie 1991 — courtship display; folk-canonical |
| 2 | standing-side-profile (male, train trailing) | (general phasianid) |
| 3 | walking-side | (general phasianid) |
| 1 (default for female) | side-profile-standing | (general phasianid) |
| AVOID | mid-flight | Galliforms fly poorly + briefly |

## 5. Folk-art conversion (Mithila register, species-specific)

- **Body coloring (EXCEPTION to indigo override):** **Preserve the iridescent multi-color palette** — sapphire-blue neck, emerald-green body accents, gold-bronze wing panels, vermillion / orange accents. The species' identity IS its color. This breaks the indigo-override rule for valid species-identity reasons.
- **Train rendering (CRITICAL):**
  - The fanned train must be **the dominant visual element** of the composition — occupying ≥ 60% of frame width.
  - **NEVER stubby, NEVER partial, NEVER folded-down for the default render.** The species identity = fanned train.
  - The train carries 100+ folk-painted ocellus medallions: concentric circles in gold + blue + green + vermillion + dark center.
- **Crown spray:** Render the spray-crest of 20-25 wire-thin lines each terminating in a small folk-medallion (gold-and-blue disc).
- **Neck/body palette:** Multi-color saturated panels with bold folk outlines.
- **Eye character:** Almond folk-eye in cream + black, with prominent expressive quality.
- **Decoration density:** **ornate** (6-7 zones — the train IS most of the decoration)
- **Required zones for peacock:**
  1. Crown spray-crest (head ornament with terminal medallions)
  2. Iridescent neck panel (sapphire-blue + green)
  3. Body color riot (green + bronze + saffron)
  4. **Fanned train with ocellus pattern** (60%+ of frame width)
  5. Wing-shoulder folk panel
  6. Leg/foot folk-line detail with anklets
  7. Tail-base junction medallion

## 6. Known v4 failure modes (from user verbal callout)

- v4 peacock: **stubby plumage, missing colors completely**
- Earlier v1: "plumage ideal" (Kachni-school monochromatic register worked)
- Earlier v2: "colors ideal — gold standard"
- v3 marked FAIL: "picks worse from both"
- v4 marked FAIL: stubby train + monochrome plumage

## 7. Prompt clauses (data-grounded, addresses v4 failures)

### Subject (positive)
> "...with a MASSIVE FULLY-FANNED train plumage spread wide behind the bird — the train must be the dominant visual element of the composition, occupying at least 60% of the frame width, never stubby or partial or folded-down — this is THE iconic peacock display and the rendered image is incomplete if the train is small, partial, or absent; with the FULL multi-color iridescent peacock palette — vivid emerald-green + sapphire-blue + gold + vermillion + bronze all visible as distinct folk-color zones in the train feathers — NEVER monochrome, NEVER a single dominant body color, the train must read as a riot of saturated folk colors; with the iconic peacock tail-eye-spots (ocelli) clearly painted as concentric folk-medallions distributed across the fanned train; with the spray-crest of fine wire-feathers terminating in small medallion discs on the head..."

### Anti-negative
> "no stubby tail, no folded plumage, no small train, no missing fan, no monochrome plumage, no faded colors, no single-color train, no missing colors, no all-indigo body, no peahen body on male render"

### Anatomical count constraints
```json
{
  "legs_visible": 2,
  "eyes": 2,
  "tail_actual": 1,
  "train_visible": 1,
  "wings": 2,
  "beak": 1
}
```

## 8. Cited research (4 species-specific open-access papers)

1. **Petrie, M., Halliday, T. & Sanders, C. (1991).** "Peahens prefer peacocks with elaborate trains." *Animal Behaviour* 41(2): 323-331. DOI: 10.1016/S0003-3472(05)80484-1. — partial open via author repository.
   - *Cited for:* Foundational work on peacock train function + sexual selection; supports "train as primary species feature."
2. **Loyau, A. et al. (2008).** "Multiple sexual advertisements honestly reflect health status in peacocks (*Pavo cristatus*)." *Behavioral Ecology and Sociobiology* 62(8): 1331-1340. DOI: 10.1007/s00265-008-0563-y. — open via author repository.
   - *Cited for:* Train ocellus count + condition; supports rich-ocellus rendering rule.
3. **Yorzinski, J.L. et al. (2013).** "Through their eyes: selective attention in peahens during courtship." *Journal of Experimental Biology* 216(16): 3035-3046. DOI: 10.1242/jeb.087338. — **fully open access (JEB).**
   - *Cited for:* Behavioral context for peacock display pose; supports "displaying-full-fan" as canonical species pose.
4. **Sun, K. et al. (2014).** "The complete mitochondrial genome of green peafowl (*Pavo muticus*) and a comparison of mitogenomes in the genus *Pavo*." *Mitochondrial DNA Part A* 27(2): 1010-1011. — partial open.
   - *Cited for:* *Pavo* genus taxonomy + species-level differentiation.

---
*Last updated: 2026-05-22. v6 prompts derive from this file. Peacock is THE iconic Madhubani folk-art species — rendering quality is portfolio-critical.*
