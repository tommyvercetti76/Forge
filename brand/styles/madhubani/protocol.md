# Madhubani / Mithila — Cultural Protocol

**Status:** Draft v1 (2026-05-22). Subject to revision after consultation with Mithila Art Institute and individual Mithila-tradition artists.

This document defines what Forge will and will not do when generating in the Madhubani / Mithila folk-art tradition. It is the **non-technical contract** that complements `style.json`. Code reads `style.json`; humans read this. Both gate the engine.

## Tradition ownership

The Madhubani / Mithila folk-art tradition originated and is sustained by **women artists of the Mithila region of Bihar, India**. The tradition has documented antiquity going back to the Ramayana era. Its modern commercial form emerged after the 1934 Bihar earthquake exposed home wall paintings to outside observers.

Three named sub-styles carry distinct grammars:
- **Kachni** (Brahmin tradition) — fine line-work, monochrome or two-color
- **Bharni** (Kayastha tradition) — color-filled, ornate, the most commercially recognized form
- **Godna / Gondh-Maithila** (Dusadh community tradition) — tattoo-like, denser fill

Forge's current implementation primarily targets the **Bharni** style. Future work should extend Kachni and Godna as distinct engines.

## What Forge attributes

Every Madhubani-tradition artifact ships with a `receipt.json` containing:

1. **Tradition acknowledgment** — explicit naming of the Mithila origin and the women artists who sustain it
2. **Reference manifest** — every Wikimedia or public-domain reference used in training or composition, with license, URL, accessed-at timestamp, and SHA-256 hash
3. **Commercial-use note** — recommendation to support Mithila-artist cooperatives, the Mithila Art Institute (Madhubani town), and the Crafts Council of India when the artifact is monetized

The reference corpus currently includes 50 attributable references. Path: `brand/references/madhubani/`.

## What Forge will not do

| Refusal category | Reason |
|---|---|
| **Pass off generated work as authentic Mithila artist work** | Every receipt explicitly labels the artifact as `Madhubani-tradition` (generative), never as `by a Madhubani artist`. The distinction is visible in metadata and recommended for visible captioning in any public-facing use. |
| **Render Madhubani in non-flat-silhouette form** | The flat-silhouette discipline is foundational. Photorealistic, 3D, or perspective-rendered "Madhubani" is a category error and is rejected by the rubric. |
| **Substitute the canonical palette with arbitrary colors** | The indigo / vermillion / saffron / leaf-green / ochre palette is part of the tradition's recognizability. Off-palette renders are flagged. |
| **Decorate body interiors with random AI-pattern noise** | The 5–9 ornament-zone count + canonical motifs (lotus, fish, peacock-eye, paisley, dots, leaf-veins) are tradition-specific. Generic ornamental noise is a rubric failure. |
| **Empty backgrounds** | Madhubani fills the canvas. Blank white space is not Madhubani. |

## What Forge requires for novel subjects

Some species in Forge's wildlife catalog (snow leopard, hoolock gibbon, dugong, Bhitarkanika saltwater crocodile, etc.) **were not historically depicted in Madhubani art.** Forge does not pretend they were.

For these subjects, the receipt's `cultural_attribution.novelty_disclosure` field is mandatory and reads:

> *"{subject} is not traditionally depicted in Madhubani; this rendering is a contemporary interpolation honoring the tradition's grammar (flat silhouette, dense interior decoration, traditional palette) while extending its subject vocabulary to include species native to {region}."*

This is a contribution to the tradition, not an erasure of its history. The disclosure is the difference.

## What Forge defers to human judgment

The following are NOT mechanically verified by `forge verify`:

1. **Cultural appropriateness** — Whether a particular novel subject (e.g., extending Madhubani to a species genuinely foreign to the tradition's region) is *welcome* to the tradition's living practitioners. Forge does not assume yes or no — it discloses the novelty and defers the welcome question to dialogue with Mithila-tradition artists.
2. **Devotional contexts** — Madhubani has deeply devotional roots (Kohbar Ghar wedding paintings; Krishna/Radha imagery; goddess representations). Forge does not refuse devotional generation but does not authorize it without explicit operator declaration in the receipt.
3. **Commercial use beyond personal scope** — Forge cannot verify whether the operator's downstream use of an artifact (sales, NFTs, brand applications) complies with the cultural recommendation to support Mithila cooperatives. This is on the operator.

## Forbidden categories

These categories are explicit refusals — Forge will not generate even when requested:

1. **Hate symbolism rendered in Madhubani style** — using the tradition's grammar to dignify hateful content is a refusal.
2. **Pornographic or sexually explicit content in Madhubani style** — including the appropriation of any traditional Madhubani sub-grammar (Kohbar Ghar marriage imagery has erotic-symbolic content, but its contemporary appropriation for pornographic intent is refused).
3. **Subjects that would be considered sacred-restricted by living Mithila tradition holders** — this list is currently empty pending consultation; this section will be populated by Mithila-tradition artist input.

## Reference corpus standards

References used in LoRA training or composition must meet:

- Public-domain or CC-BY / CC-BY-SA licensed
- Original Mithila-tradition work (not derived AI-generated work)
- Attributable to a named artist or named collection where possible (Wikimedia Commons, V&A Museum, Mithila Art Institute archive, National Museum New Delhi)
- Hashed (SHA-256) and timestamped at ingest

Reference corpus location: `brand/references/madhubani/` with per-asset `attribution.json` receipts.

## Consultation and revision

This protocol is a **draft awaiting consultation**. Forge maintainers commit to:

1. **Outreach to Mithila Art Institute** (Madhubani town, Bihar) for review of this protocol
2. **Outreach to at least 3 individual Mithila-tradition artists** for feedback
3. **Public revision log** when this protocol changes based on that feedback
4. **Refusal to override expert input** — if Mithila-tradition consultation flags a Forge behavior as inappropriate, the behavior changes; Forge does not litigate cultural authority

Until that consultation completes, this protocol is **provisional, code-reviewed but not culture-reviewed**. The distinction matters and is preserved in the receipt schema (`cultural_attribution.protocol_version` records which version of this protocol governed the generation).

## Acknowledgment text (for public-facing artifacts)

Any public-facing Madhubani-tradition Forge artifact (poster, print, social post, exhibition) should carry this text or equivalent:

> *Generated in the Madhubani / Mithila folk-art tradition of Bihar, India. The tradition is originated and sustained by women artists of the Mithila region. Commercial use should support Mithila-artist cooperatives, the Mithila Art Institute (Madhubani), or the Crafts Council of India. Reference corpus and attribution receipts available at [link to the operator's deployment of brand/references/madhubani/].*

The receipt schema (`docs/SCHEMA.md`) carries this in `cultural_attribution.tradition_owners_acknowledgment`.

---

**Protocol version**: `madhubani.protocol.v1` (draft, pre-consultation)
**Last revised**: 2026-05-22
**Consultation status**: not yet initiated — see Section "Consultation and revision"
