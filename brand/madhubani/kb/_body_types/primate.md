# Body type: Primate (operational body-type, mostly cercopithecid)

**Inherits from:** [_orders/primates.md](../_orders/primates.md)
**Inherited by species:** macaque · golden-langur · nilgiri-langur · hoolock-gibbon (with deltas — see below)

## 1. Motor pattern (the primate silhouette)

The primate body plan is distinct from quadrupedal mammals — designed for **sitting upright** and **arboreal locomotion**:

- **Body shape:** Compact torso, often with a "human-like" upright sitting posture as default rest pose. Distinct shoulder structure (rotatable arms) for arboreal life.
- **Limbs:** 4 — **forelimbs and hindlimbs are anatomically distinct** unlike most quadrupeds where they look similar. Hands have 5 digits with opposable thumb. Feet have 5 digits, often opposable hallux (toe) in cercopithecids.
- **Hands:** Visible, with curled or extended fingers. NEVER render as paws (predator) or hooves (ungulate).
- **Tail:** Family-dependent:
  - Cercopithecidae (macaque, langur): **Long tail** (often longer than body)
  - Hylobatidae (gibbon): **NO TAIL** — gibbon-with-tail is the #1 hallucination class for apes
- **Face:** Often partially bare-skinned, with prominent expressive features. Forward eyes (almond), visible brow ridges.
- **Posture:** Default sit-upright with back straight, hands on legs or holding food. Standing bipedal is rare but possible. Quadrupedal (palms on ground) is the locomotion pose.

## 2. Anatomical count constraints (limb-missing + tail-hallucination fix)

For ALL primates in **sitting-upright** pose:

| Feature | Required count | Note |
|---|---|---|
| Limbs visible | 4 | 2 arms + 2 legs. NEVER 2 (loss-of-arms hallucination). NEVER 6 (extra-limb hallucination). |
| Hands visible | 2 | Both hands visible (one may be folded under but should be visible) |
| Hand digits per hand | 5 | Standard 5-finger anatomy, opposable thumb visible |
| Foot digits per foot | 5 | Standard 5-toe anatomy, opposable hallux for arboreal species |
| Eyes | 2 | Forward-facing, almond folk-eye |
| Ears | 2 | Visible, varying sizes |
| Tail | **Family-specific: 1 for cercopithecidae, 0 for hylobatidae (gibbon)** | THE critical distinction. Gibbon with tail = wrong species. |

## 3. Decoration grammar (Mithila register for primates)

- **Decoration density:** **balanced** (4-5 zones). Primates have moderate body surface; over-decoration would obscure the distinctive face + hands.
- **Required zones (priority order):**
  1. Tikka medallion on forehead/crown
  2. Body color field (cleaner — face/hands shouldn't be decorated)
  3. Shoulder vine motif
  4. Tail-band rhythm (where tail present)
  5. *Hand/face emphasis:* render hands + face with minimal decoration so expressive features remain readable
- **Face rendering:** Bare-faced primates (macaque) get clean skin-tone face with prominent eye + brow + mouth shape. Even almond folk-eye is more EXPRESSIVE on primates than predators.
- **Hand rendering:** 5-finger hands visible — render fingers as folk-line work, opposable thumb visible.

## 4. Default pose preferences (cited)

Primate poses:
- **sitting-upright** (default) — back straight, hands resting on legs or holding food, tail visible if present (cercopithecidae)
- **branch-perch-upright** — sitting on a branch, body upright, tail balanced
- **quadrupedal-walking-arboreal** — moving along a branch, palms + soles on substrate
- **hanging-arm-suspension** — **hylobatidae-signature** (gibbon): hanging from one or both arms below a branch. ICONIC gibbon pose.
- **knuckle-walking-quadrupedal** — possible but uncommon for our species
- **bipedal-standing** — rare; macaques can but rarely shown in folk art

**AVOID:**
- Tail on gibbon
- Paw-foot rendering (primates have hands + feet, not paws)
- Quadrupedal-low like a cat (primates sit upright, even when on ground)

## 5. Cited research (4 open-access sources)

1. **Fleagle, J.G. (2013).** *Primate Adaptation and Evolution*, 3rd ed. Academic Press. — partial open via author repository.
   - *Cited for:* Comprehensive primate body-plan + locomotion modes; supports sit-upright default + arboreal pose vocabulary.
2. **Perelman, P. et al. (2011).** "A molecular phylogeny of living primates." *PLOS Genetics* 7(3): e1001342. DOI: 10.1371/journal.pgen.1001342. — **fully open access (PLOS).**
   - *Cited for:* Primate phylogeny — supports family-level distinctions (cercopithecidae vs hylobatidae).
3. **Cant, J.G.H. (1992).** "Positional behavior of female Bornean orangutans." *American Journal of Primatology* 27(2): 99-113. DOI: 10.1002/ajp.1350270204. — partial open via author repository.
   - *Cited for:* Positional/postural behavior framework, basis for "sitting-upright vs hanging" pose vocabulary.
4. **Hunt, K.D. (1992).** "Positional behavior of *Pan troglodytes* in the Mahale Mountains and Gombe Stream National Parks, Tanzania." *American Journal of Physical Anthropology* 87(1): 83-105. DOI: 10.1002/ajpa.1330870108. — partial open.
   - *Cited for:* Positional behavior of apes; supports knuckle-walking + hanging vocabulary for hylobatidae extension.

---
*Last updated: 2026-05-22. Inherited by 4 primate species. Cercopithecid vs hylobatid distinction is critical for tail-rendering.*
