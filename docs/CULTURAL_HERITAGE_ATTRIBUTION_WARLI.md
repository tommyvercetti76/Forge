# Warli — Cultural Protocol

**Status:** Draft v0.1 (2026-05-22). Pre-consultation. Subject to revision after Warli Adivasi Mahasabha and Jivya Soma Mashe estate review.

This document defines Forge's cultural commitments when generating in the Warli folk-art tradition. Adivasi (tribal) traditions carry community ownership that requires distinct handling from caste-Hindu traditions like Madhubani.

## Tradition ownership

The Warli (Varli) folk-art tradition originated and is sustained by the **Warli Adivasi community of the North Sahyadri Range, Maharashtra**, with secondary practice in Gujarat and Daman & Diu. The tradition is approximately 1,000 years old and is tied to:

- **Tarpa dance ceremonies** (harvest, spring rituals)
- **Marriage paintings** (Chowk wall paintings; central marriage-mandapa motif)
- **Ritual wall art** on mud-plaster home interiors

Modern international recognition is largely owed to **Jivya Soma Mashe** (1934–2018, Padma Shri 2011), who began painting on paper in the 1970s and brought Warli to galleries. The tradition is **community-owned, not individual-owned**.

## Community ownership — what this changes

Warli is an **Adivasi (tribal) tradition.** Adivasi cultural practices in India face ongoing risks from:

1. **Commercial appropriation** without community benefit
2. **Misattribution** to individual artists when the practice is community-held
3. **Dilution** through corporate "tribal aesthetic" branding that detaches motifs from origin

Forge's commitments reflect these risks:

| Commitment | Mechanism |
|---|---|
| Attribute to the **community**, not individuals (unless individual consent is explicit) | Receipt's `cultural_attribution.tradition_owners` field reads "Warli Adivasi community" |
| Acknowledge Jivya Soma Mashe and other named contemporary practitioners ONLY when their specific style or recognized work is referenced | Default is community attribution; named-artist attribution requires explicit reference |
| Encourage downstream commercial use to support Warli artist cooperatives | `commercial_use_note` in receipt |
| Refuse to generate "Warli-inspired" content that is in fact decontextualized geometric design with no actual tradition fidelity | Rubric checks (two-color, geometric primitives, single-line discipline) gate publishability |

## What Forge attributes

Every Warli-tradition Forge artifact ships with a `receipt.json` containing:

1. **Tradition acknowledgment** — explicit naming of the Warli Adivasi community of Maharashtra
2. **Reference manifest** — every Wikimedia or public-domain reference used in training or composition, with license, URL, accessed-at timestamp, and SHA-256 hash
3. **Commercial-use note** — recommendation to support Warli artist cooperatives, the Warli Adivasi Mahasabha, and Adivasi cultural-preservation organizations
4. **Novelty disclosure** when the subject is a species or motif not historically depicted in Warli (snow leopards, hoolock gibbons, marine megafauna, etc.)

The reference corpus is currently empty — collection scheduled for week 1 of the catalog buildout. Target: 50 attributable references from Wikimedia, the Jivya Soma Mashe published catalog, V&A Museum public archive, and the Warli Adivasi Mahasabha public collection.

## What Forge will not do

| Refusal category | Reason |
|---|---|
| **Color-fill Warli figures with multi-color body decoration** | Warli is strictly two-color (white + terracotta). Multi-color decorated figures are NOT Warli; they're a different aesthetic and should be labeled as such. |
| **Render anatomically realistic animals "in Warli style"** | Warli reduces animals to geometric primitives (triangle bodies, line legs). "Realistic animal in Warli style" is a category error — the abstraction IS the tradition. |
| **Use Western "tribal pattern" framings** | Warli is a specific Adivasi tradition with origin in Maharashtra, not a generic "tribal aesthetic." Captions, prompts, and outputs should never call Warli "tribal pattern" or "ethnic design" — name the tradition. |
| **Attribute Warli to a single artist without explicit reference** | Community attribution is default. Single-artist attribution requires that artist's work to be specifically referenced. |
| **Refuse to disclose novelty** | Snow leopards, dugongs, etc. were never historically depicted in Warli. The receipt MUST flag this as a contemporary interpolation. |

## What Forge requires for novel subjects

Warli's historic subject vocabulary covered local Maharashtrian fauna: tiger (then-still-present in Sahyadri), deer (sambar, chital), peacock, fish (river and coastal), bullock, snake, scorpion, and the human figure in dance/harvest/marriage scenes.

Extending Warli to:
- **Non-Maharashtrian Indian fauna** (snow leopard, golden langur, one-horned rhino) — requires novelty disclosure
- **Global fauna** (kangaroo, polar bear, giraffe) — requires both novelty disclosure AND a stronger acknowledgment that Warli was never designed to depict these subjects

Default disclosure text:

> *"{subject} is not traditionally depicted in Warli; this rendering applies Warli's geometric-primitive grammar (single-thickness lines, two-color, body-as-stylization) to a subject from outside the tradition's historic Maharashtrian fauna. This is a contemporary extension of the tradition, not a recovery of historic Warli depiction."*

## What Forge defers to human judgment

The following are NOT mechanically verified:

1. **Cultural appropriateness of any specific application** — particularly commercial use. Forge cannot verify whether downstream use supports Warli artist communities.
2. **Tarpa-dance and ritual-scene fidelity** — Forge generates Tarpa-dance circles but cannot validate whether the depicted ritual context is appropriate (e.g., depicting Tarpa outside its harvest-season context).
3. **Sacred-restricted motifs** — this list is currently empty pending Warli Adivasi Mahasabha consultation; the section will be populated upon dialogue.

## Forbidden categories

These categories are explicit refusals:

1. **Hate symbolism rendered in Warli style** — refused.
2. **Sexually explicit content in Warli style** — refused.
3. **"Tribal aesthetic" branding that decontextualizes Warli** — Forge will not generate content labeled "tribal," "ethnic," or "primitive" as a style descriptor when the underlying request is for Warli; the tradition name MUST be used.
4. **Subjects flagged by Warli Adivasi Mahasabha consultation as sacred-restricted** — currently empty pending consultation.

## Reference corpus standards

References used in LoRA training must meet:

- Public-domain or CC-BY / CC-BY-SA licensed
- Original Warli-tradition work (NOT derived "Warli-inspired" Western graphic design)
- Attributable to a named artist (Jivya Soma Mashe, Madhukar Vadu, others) OR the community (Warli Adivasi Mahasabha collection)
- Hashed (SHA-256) and timestamped at ingest
- **Special caution**: many "Warli-style" images on stock-photo sites are non-community-produced graphic design and must NOT be used in training

Reference corpus location: `brand/references/warli/` (currently empty, target 50 references).

## Consultation and revision

This protocol is a **draft awaiting consultation**. Forge maintainers commit to:

1. **Outreach to the Warli Adivasi Mahasabha** for review of this protocol
2. **Outreach to the Jivya Soma Mashe estate / Madhukar Vadu** for input on community-attribution language
3. **Outreach to at least 2 contemporary Warli artists** for feedback on novel-subject extension
4. **Public revision log** when this protocol changes based on that feedback
5. **Refusal to override expert input** — if Warli community consultation flags a Forge behavior as inappropriate, the behavior changes

Until that consultation completes, this protocol is **provisional, code-reviewed but not culture-reviewed**. The distinction is preserved in receipts (`cultural_attribution.protocol_version` records the version that governed generation).

## Acknowledgment text (for public-facing artifacts)

Any public-facing Warli-tradition Forge artifact should carry:

> *Generated in the Warli folk-art tradition of the Warli Adivasi community, North Sahyadri Range, Maharashtra, India. The tradition is approximately 1,000 years old, community-owned, and brought to international recognition through Jivya Soma Mashe (Padma Shri, 2011). Commercial use should support Warli artist cooperatives and the Warli Adivasi Mahasabha.*

---

**Protocol version**: `warli.protocol.v0.1` (draft, pre-consultation)
**Last revised**: 2026-05-22
**Consultation status**: not yet initiated
**Reference corpus status**: not yet collected (target 50)
**LoRA status**: not yet trained
