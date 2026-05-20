# Madhubani Art Identity — single source of truth

> This document is the canonical reference for every Madhubani render Forge produces. When a JSON file, engine prompt, recipe, or test contradicts this doc, **this doc wins** and the offending file must be updated. The rules are scattered across `bin/style_engines.py`, `bin/forge_madhubani.py`, and the `brand/madhubani/*.json` schemas; this is the document that pulls them together so they stop overwriting each other.
>
> Established 2026-05-20 from prior content in `generated/madhubani_animals/_learning/PRINCIPLES.md` and the v2 catalog schemas. The bibliography at the bottom is the academic + cultural provenance behind every master citation we use.

---

## 1. Identity statement

The Madhubani catalog is a **Madhubani-INSPIRED** apparel-graphics line. It draws from the living Mithila folk-painting tradition of Bihar, India, but is **not authentic Mithila art**. Authentic Mithila painting is a Geographically Indicated cultural heritage produced predominantly by women in family lineages within the Mithila region. The catalog's design language references that tradition; the catalog's commercial output is a respectful derivative, not a substitute.

**Customers who love these designs should also support the living tradition directly** via [Mithila Art Institute](https://mithilaartinstitute.org) and similar organizations.

---

## 2. The five Madhubani schools

The Madhubani tradition isn't a single style — it's a family of sub-traditions with distinct visual rules. The catalog primarily uses **Bharni** (filled-color) but each school is a valid axis for catalog variants.

| School | Visual signature | Use in catalog |
|---|---|---|
| **Bharni** (भरनी) | Solid bold-color fills inside heavy double-contour outlines. The "classic" Madhubani look — flat color zones inside flat silhouettes, geometric and floral folk panels covering most of the body. | **Default**. Today's renders sit here. |
| **Kachni** (कचनी) | Fine line work, intricate cross-hatching, sparse fills. Often monochrome or two-tone. Ganga Devi's signature style. | Reserved for monochrome-tee variants (planned recipe). |
| **Tantric** | Religious / ritual subjects — Mahavidya goddesses, mandalas, yantras. Geometric and meditative. | Out of catalog scope (we don't render deities). |
| **Godna** (गोदना) | Tattoo-style geometric, often single-color, originating from women's body-tattoo practice. | Reserved for stark-monochrome variants. |
| **Gobar** | Earthier palette (cow-dung ochres, browns). Often outdoor wall murals. | Reserved for "rustic" variant tier; not used today. |

We currently render in the **master-painter register**, an explicit framing inside the engine prompt that cites Sita Devi, Ganga Devi, Baua Devi, and Mahasundari Devi by name. See §5 below for the bibliography behind those citations.

---

## 3. Palette

The catalog's six-color folk palette is defined in `brand/madhubani/palette.json`. Summary:

| Role | Color | Hex | Used for |
|---|---|---|---|
| body-fill primary | **deep-indigo** | `#1a2952` | Most subjects' body silhouette anchor |
| body-fill alt | **walnut-brown** | `#5a3a1f` | Big cats, large mammals, ground-dwellers, warm-fur species |
| body-fill alt | **forest-teal** | `#1f4a3f` | Serpents, forest reptiles, occasionally cats |
| accent | saffron-orange | `#e87722` | Ornament zone (saddle blanket, anklets, dot bands) |
| accent | vermillion-red | (palette.json) | Ornament zone (floral medallions, feet) |
| accent | leaf-green | (palette.json) | Ornament zone (vine motifs, leaf panels) |

**Rule:** The body silhouette is FILLED with one of the three body-fill colors. The remaining ornament colors appear ONLY inside decoration zones (saddle blankets, anklets, neck collars, leaf-vein panels). The body never becomes accent-color (no orange tigers, no green parrots, no blue peacocks). This is the **`BODY FILL OVERRIDE`** clause that ships in `bin/forge_madhubani.py:build_subject_string()`.

---

## 4. Body-type taxonomy + body-fill convention

The catalog covers 41 species across 8 body types. The body-type → body-fill assignment is encoded in `brand/madhubani/animals.json` per-species. The convention rule:

| Body type | Default body-fill | Examples |
|---|---|---|
| heavy-quadruped | deep-indigo | elephant, rhino, gaur, water-buffalo |
| lean-predator | **walnut-brown** | tiger, leopard, lion, snow-leopard, hyena, dhole, sloth-bear |
| lean-quadruped | deep-indigo | sambar, chital, blackbuck, nilgai, nilgiri-tahr, bharal, barasingha, chinkara |
| serpent | **forest-teal** | cobra |
| crocodilian | deep-indigo | saltwater-crocodile |
| bird | deep-indigo (with species-specific tail/wing accents) | peacock, sarus-crane, painted-stork, flamingo, hornbill, skimmer |
| primate | deep-indigo | macaque, golden-langur, nilgiri-langur, hoolock-gibbon |
| armored-quadruped | deep-indigo | pangolin |
| cetacean | deep-indigo | irrawaddy-dolphin, whale-shark |
| small-mammal | **walnut-brown** (warm-fur convention) | indian-fox, red-panda, indian-grey-mongoose, indian-giant-squirrel |
| stocky-omnivore | **walnut-brown** | sloth-bear, indian-wild-boar, pygmy-hog |

When `species_render_name` is set on an animal (currently only tiger), it replaces the rendered subject name (e.g. "Royal Bengal Tiger" → "Madhubani folk-art tiger icon") to anchor the model in the folk-art register without losing species anatomy. See `bin/forge_madhubani.py` for the mechanism.

---

## 5. Master citations (with bibliography)

The engine's "FINGERPRINT — render in the visual register of:" clause cites:

| Master | Style school | Honors | Why we cite | Primary source |
|---|---|---|---|---|
| **Sita Devi** | Bharni + Kohbar wall paintings | Padma Shri (1981), Bihar Ratna (1984), National Award (1969) | Mid-century kohbar wall-painting line grammar; the signature almond-eye treatment carried across all our sets | [Saffronart](https://blog.saffronart.com/2013/02/11/sita-devi-a-legendary-mithila-artist/) · [Wikipedia](https://en.wikipedia.org/wiki/Sita_Devi_(painter)) |
| **Ganga Devi** | Kachni (line-style) pioneer | Padma Shri (1984), National Award (1984) | Bharni-style fill rhythm, dot-and-petal aura; subject of academic study by Tokio Hasegawa | [Inditales](https://inditales.com/madhubani-artist-ganga-devi-mithila/) |
| **Baua Devi** | Bharni, narrative compositions | Padma Shri (2017) | Matsya (fish) and Naga (serpent) compositional motifs; living master | [Wikipedia: Madhubani art](https://en.wikipedia.org/wiki/Madhubani_art) |
| **Mahasundari Devi** | Bharni, Mithila-everyday genre | Padma Shri (2011) | Daily-life motif vocabulary; Maithili community scenes | [MAP Academy](https://mapacademy.io/article/madhubani-painting/) |

**Full bibliography** lives in [`MADHUBANI_BIBLIOGRAPHY.md`](MADHUBANI_BIBLIOGRAPHY.md) (sibling doc). The `brand/madhubani/masters.json` carries the structured data.

---

## 6. Body-type-specific poses (v2 — replaces the generic-4 set)

The v1 `poses.json` defined **4 generic poses** (standing-alert, seated-rest, signature-action, frontal-portrait) and claimed they "generalize across mammals, birds, reptiles, and primates." **That claim is wrong.** Birds aren't "seated" — they're perched, in flight, displaying their tails, or preening. Serpents aren't "standing." Cetaceans aren't on legs at all.

The v2 pose taxonomy is per-body-type. Each animal's body_type (from animals.json) selects the right pose dictionary:

| Body type | Pose dictionary |
|---|---|
| Mammal (quadruped / predator / primate) | **standing-alert**, **seated-rest**, **signature-action**, **frontal-portrait** |
| Bird | **perched-resting**, **in-flight-display**, **tail-fanned-or-courting**, **frontal-portrait** |
| Serpent | **coiled-resting**, **rearing-hood-spread**, **S-curve-midstrike**, **frontal-portrait** |
| Crocodilian | **basking-on-bank**, **floating-half-submerged**, **jaws-open-defensive**, **frontal-portrait** |
| Cetacean / marine | **gliding-deep**, **breaching-or-surface**, **suspended-still**, **frontal-portrait** |
| Small-mammal | **alert-standing**, **curled-resting**, **foraging**, **frontal-portrait** |

**Status:** the v2 pose taxonomy is **implemented** in `brand/madhubani/poses.json` v2.0.0. The four canonical slot names (standing-alert / seated-rest / signature-action / frontal-portrait) remain catalog positions; the `body_type_overrides` map (12 body types covered) is the source of truth for what each slot MEANS for each body type. `bin/forge_madhubani.py:build_subject_string()` consults `body_type_overrides` first and falls back to the per-slot `subject_template` only when no override applies — so a "seated-rest" bird perches on a branch, a "seated-rest" serpent coils with hood lowered, and a "seated-rest" cetacean is suspended motionless. What is **still planned** (see [`docs/FORGE_PORTFOLIO_PLAN.md`](FORGE_PORTFOLIO_PLAN.md) Lane 2): a deeper per-body-type slot-name vocabulary (e.g. `perched-resting` / `in-flight` as their own slots, not just semantic overrides on the legacy slot names).

---

## 7. Anatomical correctness — NOT optional

Even with the flat-2D folk-icon styling (the post-L1+L2 tuning), anatomical correctness is **non-negotiable**. Madhubani's flatness is graphical, not structural. The animal's anatomy reads correctly; the rendering is just 2D.

Per-body-type anatomy rules (from `animals.json:body_types`):

- **Heavy-quadruped**: pillar-broad legs proportional to body mass, broad shoulders + hips, sturdy hocks, **all four legs clearly visible** in side profile.
- **Lean-predator**: body fill is saturated color (not silhouette black), all four legs visible as **distinct outlines**, proportional muscular limbs, long tail in natural position.
- **Lean-quadruped**: slender legs proportional to body, tail visible, alert head carriage.
- **Serpent**: **continuous coil with no broken segments**, hood proportional to body where applicable, calm closed mouth as default.
- **Bird**: two sturdy legs on a visible **perch or ground line**, head and tail proportional, wing visible against body in resting pose.
- **Primate**: **almond eyes**, NOT round cartoon eyes; proportional hands and feet; tail length appropriate to species; expressive face with intentional gravity.
- **Crocodilian**: long body with short legs, scales as flat folk panels, jaw line distinct.
- **Cetacean**: streamlined body silhouette, fluke and dorsal fin visible, water ground-mark of folk dots instead of land.
- **Armored-quadruped**: body plates simplified into folk panels, all four legs visible, characteristic tail visible.
- **Small-mammal / stocky-omnivore**: proportions read correctly; no exaggerated cute proportions; the species' field marks are present.

**Species-specific anatomy** (when the species has a diagnostic feature that's easy to lose): stored as `anatomy_must_include` per-animal in `animals.json`. 22 of 41 species carry this field today — typically those with a single defining feature (rhino's single horn, skimmer's longer lower mandible, blackbuck's spiral horns).

The engine prompt's `ANATOMY FIRST` clause (in `bin/style_engines.py`) enforces this:

> ANATOMY FIRST — FLAT 2D SILHOUETTE: render a clean, HAND-DRAWN folk-art silhouette FIRST — a single FLAT-COLOR shape with confident double-contour outlines, NEVER a photorealistic 3D-rendered animal, NEVER a sculpted body, NEVER fur texture, NEVER dimensional shading. The body is a FLAT FOLK ICON painted in 2D, like the Mithila wall-paintings of Sita Devi, Ganga Devi, and Baua Devi — not a National Geographic photograph wrapped in patterns. **DECORATION goes INSIDE the flat silhouette as FLAT color zones** — geometric folk panels, lotus medallions, vermillion dot-bands, leaf-vein linework — each rendered as solid flat color shapes that sit inside the body silhouette like ink on paper. Decoration NEVER becomes 3D shading; decoration NEVER replaces, consumes, or obscures the underlying anatomy.

---

## 8. Decoration density (forward-spec — knob to be added)

A **density temperature** lets one species produce multiple visually-distinct SKUs:

| Density | Inner zones | Coverage of body silhouette | Use case |
|---|---:|---:|---|
| `minimal` | 0–1 | ≤20% | Stark Kachni-school single-line look |
| `balanced` | 3–4 | 30–50% | The "tasteful merch mark" sweet spot |
| `ornate` | 5–7 | 50–80% | Today's default — saddle blanket + leg bands + medallions |
| `maximal` | 7–9 | ≥80% | Full Madhubani density — body almost entirely patterned |

**Status:** implemented in Phase A (schema) + Phase B.1 (verification). Each animal in `brand/madhubani/animals.json` declares a `decoration_density` field (minimal / balanced / ornate / maximal); `bin/forge_madhubani.py:_decoration_density_clause()` injects the right directive into the subject string, and `bin/madhubani_qc.py:_score_pattern_density()` measures the rendered density against the declared band (`PATTERN_DENSITY_BANDS`) and fails the auto-QC if it's below the band's minimum. See [`docs/ART_REASONING_ENGINE.md`](ART_REASONING_ENGINE.md).

---

## 9. The 7-item quality rubric

Lives in `docs/catalog/RUBRIC.md`. Summary:

1. **Color floor** — at least 4 of 6 folk hues visibly present (machine-gated)
2. **Corners clean** — no painter marks / signatures / glyphs (machine-gated)
3. **Subject centered** — single subject, balanced composition (machine-gated)
4. **Body fill saturated** — not blank silhouette, not all-cream (machine-gated)
5. **Anatomy correctness** — leg count, field marks, proportions (machine-gated for some body types; `disabled_by_default` for others due to 50% FP rate on the curated corpus)
6. **OCR text-leak** — no hallucinated glyphs (machine-gated when pytesseract installed)
7. **Eye character** — alert almond-eye contrast in head region (machine-gated)

Machine-gated checks fail → write `<png>.blockers.json` → `publishable: false` in manifest → `forge_madhubani promote` refuses unless `--force` is provided.

---

## 10. Engine prompt assembly order

The engine prompt is assembled in this order. Token position matters in diffusion models — see PRINCIPLES.md Principle 2 ("Promote your single most important rule to the top").

1. **MINIMALIST T-SHIRT DESIGN ENGINE** (purpose framing)
2. **SUBJECT / IDEA** (the species + pose + body-type anatomy clause + eye character)
3. **BODY FILL OVERRIDE** (loud, CAPS — bypasses pretrained species color)
4. **ANATOMY FIRST — FLAT 2D SILHOUETTE** (the flat-folk-icon mandate)
5. **NO SIGNATURE, NO MARK, NO MONOGRAM** (corner cleanliness)
6. **FACE & EXPRESSION** (almond-eye character)
7. **COLOR FLOOR — NON-NEGOTIABLE** (saturated multi-color requirement)
8. **CULTURAL / STYLE REGISTER** (master-painter or contemporary)
9. **INK SYSTEM** (vibrant-folk palette declaration)
10. **COLOR PALETTE** (six-color hand-painted folk register, with hex values)
11. **BODY DECORATION — SEVEN ZONES** (the ornament inventory)
12. **COMPOSITION DISCIPLINE** (centered, clean margins, no tangents)
13. **FINGERPRINT — render in the visual register of:** (the master citations)
14. **Universal negatives** (anti-3D, anti-photorealism, anti-mascot, anti-signature)

See `docs/catalog/PROMPT_GRAMMAR.md` for the full grammar; see `bin/style_engines.py:MinimalistTShirtEngine.build()` for the implementation.

---

## 11. References to other documents

| Doc | Authority over |
|---|---|
| [docs/catalog/PROMPT_GRAMMAR.md](catalog/PROMPT_GRAMMAR.md) | The exact order + wording of engine prompt clauses |
| [docs/catalog/RUBRIC.md](catalog/RUBRIC.md) | The 7-item quality rubric |
| [docs/catalog/WORKFLOW.md](catalog/WORKFLOW.md) | Render → review → master/flag flow |
| [generated/madhubani_animals/_learning/PRINCIPLES.md](../generated/madhubani_animals/_learning/PRINCIPLES.md) | The "what we learned" appendix — distilled wisdom |
| [docs/MADHUBANI_BIBLIOGRAPHY.md](MADHUBANI_BIBLIOGRAPHY.md) | Academic + cultural citations |
| [brand/madhubani/animals.json](../brand/madhubani/animals.json) | The 41-species catalog data |
| [brand/madhubani/poses.json](../brand/madhubani/poses.json) | Pose dictionary v2.0.0 — 4 catalog slots × `body_type_overrides` for 12 body types |
| [brand/madhubani/palette.json](../brand/madhubani/palette.json) | The 6-color folk palette with hex values |
| [brand/madhubani/masters.json](../brand/madhubani/masters.json) | Master-painter citation data |
| [brand/madhubani/species_iconography.json](../brand/madhubani/species_iconography.json) | Photorealistic per-species iconography (currently UNUSED by minimalist-tshirt — see code comment) |
| [docs/QUALITY_FINDINGS_2026-05-20.md](QUALITY_FINDINGS_2026-05-20.md) | Yesterday's performance + quality audit |
| [docs/IMAGE_INVENTORY_2026-05-20.md](IMAGE_INVENTORY_2026-05-20.md) | Today's inventory of generated images |

When any of those files conflicts with this doc, **this doc is authoritative**. Update the file.

---

## 12. Governance

- This doc is updated whenever a Madhubani convention changes.
- Engine prompt edits MUST reference the relevant section here in their commit message.
- New species added to `animals.json` MUST conform to §4 (body-type) and §7 (anatomy_must_include if the species has a diagnostic feature).
- New pose taxonomies added to `poses.json` MUST conform to §6.
- New style variants (Kachni / Godna monochrome) MUST conform to §2 and §8.
