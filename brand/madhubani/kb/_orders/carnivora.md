# Order: Carnivora (mammalian carnivores)

**Inherits from:** (root tier — no parent)
**Inherited by families:** felidae, canidae, ursidae, herpestidae, ailuridae, mustelidae (future)
**Includes from our 100-species catalog:** all cats, dholes, foxes, sloth-bear, mongoose, red-panda

## 1. Anatomical ground truth (order-universal rules)

These rules apply to **every Carnivoran** in our catalog. Family/species files only override them with specifics.

- **Limbs:** 4 (mammalian quadruped). In side profile, the rendered image must show 4 leg silhouettes — overlap is acceptable, but a missing leg is a species-identity failure.
- **Eyes:** 2, **forward-facing** (binocular vision for prey targeting). The almond folk-eye should sit in the front quarter of the head, not on the side like a deer or bird.
- **Ears:** 2, **erect or alert** by default (carnivores are predators or active foragers — ears forward-tipped). Drooping ears are wrong for the order.
- **Teeth:** Heterodont with prominent canines visible if mouth open. Render policy: mouth closed by default to avoid hallucinated dentition.
- **Tail:** Present in all (length varies by family — felidae long, ursidae short, canidae intermediate).
- **Fur/hair:** Continuous covering, no scales, no feathers. Pattern varies (spots, stripes, solid).
- **Locomotion class:** All terrestrial (some semi-aquatic: otter). All digitigrade or plantigrade — never hooved.
- **Body symmetry:** Bilateral. Rendered subject must be symmetric across long axis when facing camera, with one side dominant in profile.

## 2. Sexual dimorphism (order-level)

- Males generally larger (5-30% across families) — felids ~15-25%, canids ~5-10%, ursids ~30-40%.
- Visual dimorphism varies wildly by family — lions have manes (extreme), most other carnivorans have minimal visual dimorphism.
- See family files for specifics.

## 3. Photo references

Not maintained at the order tier — order is too abstract. See family / species files for actual photo refs.

## 4. Pose preferences (cited behavioral research)

Order-level default poses for Carnivora in side-profile rendering:
- **standing-alert** (default) — head up, ears forward, weight evenly distributed
- **sitting-upright** — common rest pose, shows tail and forelimb posture
- **stalking-low** — head lowered, body extended (predator hunting)

These map onto specific research:
- Felids: stalking is well-documented (Schaller 1972, Sunquist & Sunquist 2002).
- Canids: trotting/walking more characteristic than stalking (Mech & Boitani 2003).
- Ursids: bipedal-rearing is iconic but uncommon (Bargali et al. 2012 for sloth bear).

The pose should be **species-appropriate**, not order-default. See species files for the canonical pose per slug.

## 5. Folk-art conversion (Mithila register, order-level defaults)

- **Body fill color:** Override to indigo `#1a2952` by default (Madhubani convention) — defeats FLUX/Z-Image's species-natural-color priors.
- **Eye character:** Almond folk-eye with "watchful ceremonial gravity" — predator alertness rendered in folk-icon register, NOT round Disney eye.
- **Decoration density:** Default **balanced** for lean predators (4 zones), **ornate** for heavy carnivorans (7 zones). See body-type files for specifics.
- **Required zones (order-level minimum):** tikka medallion (forehead) + collar (neck) + saddle (back) + at least one joint anklet.

## 6. Cited research (4+ open-access sources)

1. **Eizirik, E. et al. (2010).** "Pattern and timing of diversification of the mammalian order Carnivora, inferred from multiple nuclear gene sequences." *Molecular Phylogenetics and Evolution* 56(1): 49-63. — **PMC open access.**
   - *Cited for:* Order-level phylogenetic structure; carnivoran divergence times.
2. **Wozencraft, W.C. (2005).** "Order Carnivora." In: *Mammal Species of the World*, 3rd ed. Johns Hopkins. — **Smithsonian institutional repository (open).**
   - *Cited for:* Canonical taxonomy + species list for order Carnivora.
3. **Nyakatura, K. & Bininda-Emonds, O.R.P. (2012).** "Updating the evolutionary history of Carnivora (Mammalia)." *BMC Biology* 10: 12. — **fully open (BMC).**
   - *Cited for:* Updated supertree, divergence-time calibration.
4. **Macdonald, D.W. & Loveridge, A.J. (eds.) (2010).** *The Biology and Conservation of Wild Felids*. Oxford. — partial open.
   - *Cited for:* Cross-family carnivore behavior + conservation context.

---
*Last updated: 2026-05-22. Inherited by all carnivoran families.*
