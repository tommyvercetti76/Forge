# Gond — Cultural Protocol

**Status:** Draft v0.1 (2026-05-22). Pre-consultation. Subject to revision after Pardhan Gond / Jangarh Singh Shyam family consultation.

This document defines Forge's cultural commitments when generating in the Gond folk-art tradition — specifically the **Jangarh Kalam** contemporary form that emerged from Patangarh village in the 1980s.

## Tradition ownership

The contemporary Gond folk-art tradition (Jangarh Kalam, or "Jangarh's style") originated in **Patangarh village, Mandla district, Madhya Pradesh**, with the **Pardhan Gond community** (one of the sub-communities of the broader Gond Adivasi people). It was inaugurated as a paper-and-canvas form by **Jangarh Singh Shyam (1962–2001)** in the early 1980s.

Two layers of ownership apply:

1. **Community ownership** — Pardhan Gond Adivasi community, Patangarh, MP
2. **Named lineage** — Jangarh Singh Shyam's family and direct artistic descendants:
   - Nankusia Shyam (his widow, continues to paint)
   - Bhajju Shyam (his nephew, "The London Jungle Book," Padma Shri 2018)
   - Durgabai Vyam, Subhash Vyam (cousins; "Bhimayana: Experiences of Untouchability")
   - Venkat Raman Singh Shyam (cousin)
   - Roshni Vyam, and the wider Patangarh artistic lineage

Unlike Warli (broadly community-owned) or Madhubani (broadly women-of-Mithila-owned), **Gond's contemporary form has named individual ownership through the Jangarh lineage**. This changes attribution requirements.

## What this changes for attribution

| Decision | Mechanism |
|---|---|
| Attribution names BOTH the community AND the Jangarh lineage | Receipt's `cultural_attribution.tradition_owners` field includes "Pardhan Gond community of Patangarh, with lineage acknowledgment to Jangarh Singh Shyam (1962-2001) and his artistic family" |
| LoRA training references must come from EITHER community-published work OR named-artist-published work (with attribution) — NOT decontextualized "Gond-style" stock graphics | Reference corpus standards enforce this |
| Forge does NOT claim to render "in the style of" any specific named living artist (Bhajju Shyam, Nankusia Shyam) without their explicit consent | Default prompts target the Jangarh Kalam GRAMMAR (style), not any individual's specific signature |
| Downstream commercial use is recommended to support the Jangarh family and Patangarh cooperatives | `commercial_use_note` in every receipt |

## What Forge attributes

Every Gond-tradition Forge artifact ships with a `receipt.json` containing:

1. **Tradition acknowledgment** — explicit naming of the Pardhan Gond community of Patangarh AND the Jangarh lineage
2. **Reference manifest** — Wikimedia/published references with license, URL, accessed-at, SHA-256
3. **Commercial-use note** — Jangarh family + Patangarh cooperative support recommendation
4. **Novelty disclosure** when the subject extends beyond traditional Gond vocabulary

Reference corpus location: `brand/references/gond/` (empty, scheduled week 2; target 50 references).

## What Forge will not do

| Refusal category | Reason |
|---|---|
| **Generate plain-fill bodies labeled as "Gond"** | The defining feature of Jangarh Kalam is the rhythmic interior pattern (dots, dashes, fishscale, crescents). Without it, this is not Gond. |
| **Use single-color minimalism labeled as "Gond"** | Gond is multi-color and vibrant. Two-color is Warli's discipline, not Gond's. |
| **Claim to be "in the style of [named living artist]" without consent** | Forge generates Jangarh Kalam grammar, not Bhajju-Shyam-specific or Nankusia-Shyam-specific signatures. |
| **Use "Gond" interchangeably with generic "tribal pattern"** | Gond is a specific Adivasi tradition with specific named lineage. "Tribal pattern" is decontextualization. |
| **Train on stock-photo "Gond-style" images** | Many "Gond-style" graphics online are non-community-produced. Reference corpus is restricted to community-published or named-artist-published work. |

## What Forge requires for novel subjects

Gond has **stronger precedent for subject expansion** than Madhubani or Warli, because the Jangarh lineage has actively extended the tradition in published work:

- **Bhajju Shyam's "The London Jungle Book" (2004, Tara Books)** depicts London — buses, Underground, Big Ben — through Gond grammar. This is canonical authorization for Gond extending to global subjects.
- **Subhash Vyam and Durgabai Vyam's "Bhimayana" (2011)** uses Gond grammar for biographical narrative of B.R. Ambedkar.

For Forge, novel-subject disclosure remains mandatory but framed appropriately:

> *"{subject} is not part of the historic Pardhan Gond visual vocabulary; this rendering applies Jangarh Kalam grammar (bold outline, rhythmic interior pattern, vibrant flat-color regions) to a contemporary subject, following the precedent set by Bhajju Shyam (London Jungle Book, 2004) and the broader Jangarh lineage's active extension of the tradition's subject scope."*

## What Forge defers to human judgment

NOT mechanically verified:

1. **Subject appropriateness** — particularly when extending Gond to subjects with cultural sensitivity in their own context (e.g., depicting Aboriginal Australian animals — kangaroo, kookaburra — in Gond style may require additional consultation with both Pardhan Gond AND Aboriginal Australian communities; Forge defers).
2. **Religious / mythological accuracy** — Gond cosmology has specific deities (Bara Deo, Pari Kupar Lingo, etc.). Forge does not refuse cosmological generation but cannot validate ritual or theological correctness.
3. **Named-artist signature claims** — Forge generates Jangarh Kalam, not specific individual signatures. If a named-artist styling is requested, the operator must affirm artist consent in the receipt.

## Forbidden categories

1. **Hate symbolism in Gond style** — refused.
2. **Sexually explicit content in Gond style** — refused.
3. **"Primitive art" framings** — Forge will not use language like "primitive," "tribal art," "ethnic art" to describe Gond. The named tradition is used.
4. **Misattribution to any individual without consent** — refused.

## Reference corpus standards

References must meet:

- Public-domain or CC-BY / CC-BY-SA licensed
- Original Pardhan Gond / Jangarh Kalam work (NOT derived "Gond-style" graphic design)
- Attributable to a named artist (Jangarh Singh Shyam, Bhajju Shyam, others in the lineage) OR community-published collections (Tara Books catalogues, MAP Bengaluru collection, Tribal Museum Bhopal)
- Hashed (SHA-256) and timestamped at ingest

**Special caution:** Tara Books' Gond catalogues are commercial publications — community-published with artist royalty arrangements. Permission for LoRA training on their published images requires direct outreach to Tara Books AND the named artists; Forge will not assume training rights from publication.

## Consultation and revision

This protocol is a **draft awaiting consultation**. Forge maintainers commit to:

1. **Outreach to the Jangarh Singh Shyam family** (Patangarh) for review of attribution language
2. **Outreach to Bhajju Shyam** for input on subject-extension precedent and his explicit consent (or refusal) for Forge to cite his "London Jungle Book" as precedent
3. **Outreach to Tara Books** for guidance on reference corpus rights
4. **Outreach to MAP Bengaluru** (Museum of Art & Photography) and Tribal Museum Bhopal for archival reference licensing
5. **Public revision log** when this protocol changes based on feedback
6. **Refusal to override expert input** — Pardhan Gond / Jangarh lineage input governs; Forge defers

Until consultation completes, this protocol is **provisional, code-reviewed but not culture-reviewed**.

## Acknowledgment text (for public-facing artifacts)

Any public-facing Gond-tradition Forge artifact should carry:

> *Generated in the Jangarh Kalam form of Gond folk-art, originating from the Pardhan Gond community of Patangarh village, Mandla district, Madhya Pradesh, India. The contemporary paper-and-canvas form was inaugurated by Jangarh Singh Shyam (1962-2001) and is sustained today by his family lineage and the broader Patangarh artistic community. Commercial use should support the Jangarh family and Patangarh artist cooperatives.*

---

**Protocol version**: `gond.protocol.v0.1` (draft, pre-consultation)
**Last revised**: 2026-05-22
**Consultation status**: not yet initiated
**Reference corpus status**: not yet collected (target 50)
**LoRA status**: not yet trained
