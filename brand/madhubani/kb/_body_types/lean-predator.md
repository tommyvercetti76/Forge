# Body type: Lean predator

**Inherits from:** (cross-cutting — applies across multiple orders, primarily Carnivora)
**Inherited by species (via slug → body_type lookup in animals.json):**
tiger · sundarbans-tiger · snow-leopard · indian-leopard · asiatic-lion · dhole · striped-hyena

## 1. Motor pattern (the lean-predator silhouette)

Lean predators share a specific build that distinguishes them from heavy-quadrupeds (rhino, buffalo) and stocky-omnivores (boar, bear). Key features:

- **Body shape:** Elongated, muscular shoulders + haunches, narrow waist. NOT bulky like ursids; NOT thin like cervids.
- **Limb proportions:** Long, lean legs with **visible joint articulation** (knee, hock, elbow). Muscles defined but not bulging.
- **Tail:** Long (60-100% of body length in most lean predators). Used for balance during sudden turns. Snow leopard's tail is at the extreme upper bound (~100% of body length, very thick).
- **Pelage:** Sleek (close-lying fur), NOT shaggy (which is ursid/sloth-bear territory).
- **Locomotion:** Digitigrade — walks on toes, not flat feet. Heel doesn't touch ground except when sitting.
- **Foot pads:** Soft padfeet in felids, hardier in canids. Both = visible pad shape under the foot in side profile, NOT a hoof.

## 2. Anatomical count constraints (limb-missing fix)

For ALL species inheriting lean-predator in **side profile standing-alert** pose:

| Feature | Required count | Note |
|---|---|---|
| Legs visible | 4 | 2 fore + 2 hind. Two-by-two overlap acceptable but 4 distinct silhouettes must be discernible. NEVER 3 legs. NEVER 5. |
| Eyes | 1 visible (side profile) | The visible eye is forward-facing, almond folk-style |
| Ears | 2 visible | Both ears visible from side profile — one in front, one behind |
| Tail | 1 | Visible from rump, long, held in species-appropriate position |
| Mouth | 1, closed | No teeth visible (avoids dental hallucination) |

These counts get auto-enforced when the `anatomy` QC check is enabled (see `bin/madhubani_qc.py`).

## 3. Decoration grammar (Mithila register for lean predators)

- **Decoration density:** **balanced** (4-5 zones), NOT ornate. Lean predators have **species-distinguishing fur patterns** (stripes, rosettes, spots) — over-decoration with all-over Madhubani pattern would obscure the species mark.
- **Required zones (in priority order, for lean-predator side profile):**
  1. Tikka medallion on forehead (universal Mithila signature)
  2. Collar dot-band at neck (clean separator)
  3. Saddle panel on back (lotus medallion + small dot-border)
  4. Joint anklets (rhythmic stripe bands at every knee/hock joint)
  5. *Optional 5th:* hip floral medallion if body type permits without crowding the species fur pattern

- **Anti-pattern:** Do NOT cover the body silhouette with all-over decoration. The fur pattern (stripes for tiger, rosettes for leopard, smoky-grey for snow leopard) must remain readable as the species-identifying mark.

## 4. Default pose preferences (cited)

Lean predators rendered in Madhubani folk-icon register:
- **Primary:** side-profile-standing-alert (default) — shows full body proportions, all 4 legs, tail
- **Secondary:** side-profile-stalking-low (head lowered, body extended) — captures predator behavior, suits hunting species (snow leopard, tiger when staking)
- **Tertiary:** sitting-upright (rests, shows tail wrapped) — good for showing tail thickness (snow leopard)

Cited basis:
- Felids: Schaller (1972) *The Serengeti Lion*; Sunquist & Sunquist (2002) *Wild Cats of the World*.
- Canids: Mech & Boitani (2003) *Wolves: Behavior, Ecology, Conservation*.
- Cross-family motor patterns: Hudson et al. (2011), Day & Jayne (2007) — see citations below.

## 5. Cited research (4+ open-access sources)

1. **Hudson, P.E. et al. (2011).** "Functional anatomy of the cheetah (*Acinonyx jubatus*) hindlimb." *Journal of Anatomy* 218(4): 363-374. DOI: 10.1111/j.1469-7580.2010.01310.x — **open via PMC.**
   - *Cited for:* Cheetah-as-extreme-lean-predator hindlimb anatomy; baseline for all felid lean-predator joint articulation.
2. **Day, L.M. & Jayne, B.C. (2007).** "Interspecific scaling of the morphology and posture of the limbs during the locomotion of cats (Felidae)." *Journal of Experimental Biology* 210: 642-654. DOI: 10.1242/jeb.02703 — **JEB open access.**
   - *Cited for:* Inter-species limb-posture comparison across Felidae (basis for "long lean legs with visible joints" rule).
3. **Carrano, M.T. (1999).** "What, if anything, is a cursor? Categories versus continua for determining locomotor habit in mammals and dinosaurs." *Journal of Zoology* 247(1): 29-42. [partial open via author archive].
   - *Cited for:* Lean-predator vs heavy-quadruped locomotor distinction (cursor / non-cursor categorization).
4. **Gonyea, W. & Ashworth, R. (1975).** "The form and function of retractile claws in the Felidae and other representative carnivorans." *Journal of Morphology* 145(2): 229-238. [paywalled, cited for factual content].
   - *Cited for:* Paw-and-claw form in lean felids (retractile claws → "padfoot in side profile, NOT a hoof").

---
*Last updated: 2026-05-22. Inherits from no order — lean-predator is a cross-order body-type pattern. Carnivora order is the main contributor but does not strictly subsume it.*
