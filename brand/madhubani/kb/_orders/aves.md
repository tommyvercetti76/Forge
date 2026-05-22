# Order: Aves (birds)

**Inherits from:** (root tier)
**Inherited by families:** phasianidae, gruidae, ciconiidae, phoenicopteridae, bucerotidae, laridae, accipitridae (and ~10 more avian families when catalog expands to 100 species)
**Includes from our 100-species catalog:** peacock, sarus-crane, painted-stork, greater-flamingo, great-indian-hornbill, indian-skimmer, plus 30+ birds from branch expansion

## 1. Anatomical ground truth (order-universal rules)

Every bird in the catalog inherits these rules. Family/species files override only with specifics.

- **Limbs:** 2 legs (NOT 4 — common AI hallucination). Two wings.
- **Eyes:** 2, laterally positioned in most birds (broad field of view for predator/prey detection). Owls + raptors are exceptions with forward-facing eyes. Render eye on the visible side only in pure side profile.
- **Beak:** 1 (NEVER 2 mouths or extra mouth parts). Shape strongly family-diagnostic — strong + heavy in hornbills, long + downcurved in flamingos, long + straight in storks, hooked in raptors.
- **Feathers:** Continuous covering — flight feathers on wings, contour feathers on body, down underlay. **No fur, no scales (except legs).**
- **Legs:** Visible from drumstick down; thigh feathered. Feet have 3-4 toes typically (3 forward + 1 back, "anisodactyl"). **NEVER paw-like or hoof-like.**
- **Tail:** Made of rectrices (tail feathers), NOT a fur-and-bone tail. Visible in flight and at rest.
- **Wings:** 2, folded against body at rest; spread in flight or display. Folded wings tuck against flanks, NOT held out.
- **Tongue:** 1 (no two-tongues hallucinations applicable here).
- **Teeth:** NONE — birds are toothless. Render mouth closed by default to avoid hallucinated teeth.
- **Body symmetry:** Bilateral. Pure side profile shows half the body, one wing's outline, one leg full + one leg partially visible at toe.

## 2. Sexual dimorphism (order-level)

Sexual dimorphism in birds varies hugely. Some families are extreme (Phasianidae — peacock vs peahen); some near-monomorphic (Laridae, Gruidae — cranes, skimmers). See family files. Default: render dimorphic species as male (more visually distinctive plumage drives folk-art icon value); render monomorphic species without sex specification.

## 3. Photo references

Maintained at species level — 8 photos per species, 4M+4F where dimorphic, 8 mixed-pose otherwise.

## 4. Pose preferences (cited)

Order-level pose vocabulary for Aves (family files refine):
- **standing-two-legs** (default) — both legs visible OR one-leg-tucked (cranes, flamingos common)
- **perching** — on branch, both feet gripping, body upright
- **wading** — partial in water, long legs visible (cranes, storks, herons)
- **swimming-floating** — body on water surface (ducks, skimmers when resting)
- **displaying** — male courtship pose; family-specific (peacock-fan, crane-dance)
- **in-flight-soaring** — wings spread, body horizontal — raptors, large birds
- **in-flight-stooping** — wings tucked, fast descent — raptors hunting

**AVOID:**
- Two-legged stand with legs visibly different / asymmetric (anatomy hallucination)
- Mid-flight transitions (between soar and flap) — too dynamic, often hallucinated incorrectly

## 5. Folk-art conversion (Mithila register, order-level for birds)

- **Body fill color:** indigo `#1a2952` override default — overrides natural plumage color (peacock blue, flamingo pink) to defeat FLUX/Z-Image's natural-color prior. **Exception:** species where natural color IS the species identity (flamingo pink, peacock iridescence) — those break the indigo rule per their species file.
- **Eye character:** Almond folk-eye with watchful gravity. Bird eyes are typically round in nature but folk-icon convention reshapes to almond.
- **Decoration density:** **balanced** for most birds (4-5 zones). Some birds (peacock-with-tail-fan) use **ornate** because the plumage IS the decoration.
- **Required zones (order-level minimum for birds):**
  1. Tikka medallion on forehead/crown (universal Mithila signature)
  2. Wing-feather panel (back/wing decoration with folk-feather pattern)
  3. Body color field with dot accents
  4. Tail-feather panel (varies by species — flamboyant for peacock, modest for skimmer)
  - *Bird-specific:* Madhubani tradition has a strong "fish-and-bird" iconography heritage; bird forms are particularly canonical in Mithila art.
- **Leg + foot rendering:** Match folk-art bird convention — clean two-toed-forward feet rendered in fine line, anklets at ankle joints.

## 6. Cited research (4 open-access sources)

1. **Prum, R.O. et al. (2015).** "A comprehensive phylogeny of birds (Aves) using targeted next-generation DNA sequencing." *Nature* 526(7574): 569-573. DOI: 10.1038/nature15697. — **open via PMC + author repository.**
   - *Cited for:* Modern bird phylogeny; family relationships across Neoaves.
2. **Jarvis, E.D. et al. (2014).** "Whole-genome analyses resolve early branches in the tree of life of modern birds." *Science* 346(6215): 1320-1331. DOI: 10.1126/science.1253451. — **open via PMC.**
   - *Cited for:* Genomic basis of avian evolution; supports family-level taxonomy.
3. **Mayr, G. (2017).** *Avian Evolution: The Fossil Record of Birds and its Paleobiological Significance*. Wiley. — partial open via author repositories.
   - *Cited for:* Anatomical evolution + body-plan structure; supports order-universal anatomy.
4. **del Hoyo, J. (chief ed.) (2020).** *Birds of the World*. Cornell Lab of Ornithology. — partial open via species accounts on `birdsoftheworld.org`.
   - *Cited for:* Canonical species accounts + family-level behavioral data; used for pose preferences.

---
*Last updated: 2026-05-22. Inherited by all avian families.*
