# Body type: Serpent

**Inherits from:** [_orders/serpentes.md](../_orders/serpentes.md)
**Inherited by species:** cobra (and future kraits, vipers, pythons, sea snakes)

This file collects body-type-level rules for snake rendering. Family-specific traits (cobra hood, viper triangular head) live in family files.

## 1. Motor pattern (the serpent silhouette)

- **Body shape:** Elongated cylinder, ratio length-to-width typically 30:1 to 50:1.
- **Limbs:** **ZERO** — universal serpent rule. NEVER any legs, feet, arms, or claws. The #1 anatomy hallucination class for snakes.
- **Locomotion:** Achieved through body undulation. Ventral scales (large transverse plates on belly) provide grip.
- **Head:** Distinct from body (slight neck constriction). Shape family-specific:
  - **Round / oval** (elapidae, colubridae) — including cobras
  - **Triangular** (viperidae) — distinct + diagnostic for vipers
  - **Pointed** (pythonidae) — slightly elongated
- **Eyes:** 2, lateral, **no eyelids** (transparent brille covers eye). Always open in render. Pupil shape varies by family.
- **Tongue:** **EXACTLY ONE forked tongue** — universal rule. NEVER two parallel tongues. Top failure mode for snake renders.

## 2. Anatomical count constraints (the limbs-missing fix turned inside out)

For ALL serpents in **any pose**:

| Feature | Required count | Note |
|---|---|---|
| Legs / limbs | **0** | ZERO. Never any limbs. Never stub-legs. Never lizard-feet. |
| Eyes | 2 (1 visible in side profile, lateral) | No eyelids; always open |
| Tongue | **1 (FORKED at tip)** | EXACTLY ONE — the cobra "two tongues" failure class. The tongue is a single Y-shape when extended. Render mouth closed if tongue is uncertain. |
| Body | 1 continuous from head to tail-tip | No clear neck-body-tail divisions (tail-tip is just where body tapers) |

## 3. Decoration grammar (Mithila register for serpents)

- **Decoration density:** **minimal** to **balanced** (3-4 zones). Snakes have continuous body — over-decoration ruins the serpentine flow.
- **Required zones (priority order):**
  1. Head crown medallion (small tikka above eyes)
  2. Body scale pattern (continuous from neck to tail, folk-translated)
  3. Belly band (visible ventral side where body curves)
  4. *Cobra-specific:* hood spectacle marking (V or O shape on back of hood)
- **Madhubani heritage note:** Snake (Nāga) iconography is deeply rooted in Mithila tradition. Serpent forms are folk-canonical — render with cultural respect to the Nāga aesthetic.

## 4. Default pose preferences (cited)

Serpent pose vocabulary:
- **coiled-S** — body in S-curve or loose coil, head raised, resting/defensive
- **coiled-striking** — body tightly coiled with head + neck raised in strike-ready posture
- **spread-hooded** — **elapid-specific (cobras)**: body coiled below, neck flat-spread, head facing viewer
- **glide-straight** — body in flowing curves, head leading, locomotion pose

**AVOID:**
- Any standing or upright body posture beyond the head/neck
- Any limb suggestion whatsoever
- Coiled in unnatural geometry (perfect circle, perfect square)
- More than one tongue
- Eyelid-suggesting eye rendering (snakes lack eyelids)

## 5. Cited research (4 open-access sources)

1. **Hsiang, A.Y. et al. (2015).** "The origin of snakes: revealing the ecology, behavior, and evolutionary history of early snakes using genomics, phenomics, and the fossil record." *BMC Evolutionary Biology* 15: 87. DOI: 10.1186/s12862-015-0358-5. — **fully open access (BMC).**
   - *Cited for:* Snake origins; supports "limbless ancestral state" foundational rule.
2. **Greene, H.W. (1997).** *Snakes: The Evolution of Mystery in Nature.* University of California Press. — partial open via author repository.
   - *Cited for:* Comprehensive snake body-plan + behavior; supports pose vocabulary.
3. **Cundall, D. & Greene, H.W. (2000).** "Feeding in snakes." In: Schwenk, K. (ed.) *Feeding: Form, Function, and Evolution in Tetrapod Vertebrates.* Academic Press. — partial open via author.
   - *Cited for:* Snake head + jaw structure; supports pose rendering rules (mouth closed by default).
4. **Lillywhite, H.B. (2014).** *How Snakes Work: Structure, Function and Behavior of the World's Snakes.* Oxford University Press. — partial open via author repository.
   - *Cited for:* Snake locomotion + body-form physiology; supports body-curve in coiled and glide poses.

---
*Last updated: 2026-05-22. Inherited by cobra and future serpent species.*
