# Forge Madhubani Knowledge Base — Index

**Purpose:** A per-species knowledge base for Forge's Madhubani folk-art wildlife pipeline. Every species' visual identity, anatomy, sexual dimorphism, and pose preferences are grounded in **photo references** and **cited open-access scientific literature** — not generative-AI priors.

This KB is the **source of truth** the prompt builder consults at render time. Every prompt clause should trace back to a line in this KB; every line should trace back to either a photo reference or a cited paper.

## Architecture — inheritance from general to specific

```
_orders/      → broadest rules (e.g. all Carnivora have 4 limbs, forward eyes, fur)
_families/    → family rules    (e.g. all Felidae have retractile claws, vertical pupils)
_body_types/  → cross-family motor patterns (lean-predator vs heavy-quadruped, etc.)
species/      → per-species deltas only (snow-leopard adds: thick body-length tail, smoky-grey)
```

A species file inherits from its order → family → body_type. Only writes the **deltas** unique to that species. Result: ~100 species expressed in ~100 thin files + ~20 family files + ~8 body-type files + ~5 order files = roughly **130 files total**, each focused.

## License floor

Every photo reference and every cited paper must be **CC-BY / CC-BY-SA / CC0 / Public Domain / GODL-India** (or equivalent open-access). **No CC-BY-NC anywhere** — we train LoRAs on these references, so commercial-use rights are required.

Citation tier policy (see `_bibliography.md`):
- Prefer fully-open journals (PLOS, eLife, PMC-deposited, IUCN Red List)
- Author-archived versions on institutional repositories count as open
- Closed-journal sources may be cited as authoritative reference; mark `[paywalled]` and only use their factual content (not their figures)

## How to read a species KB card

Open `species/<slug>.md`. The file declares its inheritance at the top, then writes only the deltas. To see the full picture for a species, follow the inheritance:

```
species/snow-leopard.md
    ↳ inherits _orders/carnivora.md
    ↳ inherits _families/felidae.md
    ↳ inherits _body_types/lean-predator.md
```

## Section structure (consistent across all files)

Every file has the same 7 sections (some sections marked N/A at higher tiers):

1. **Inheritance** — what this file inherits from (orders/families/body-types)
2. **Anatomical ground truth** — limbs, eyes, signature features (data-grounded)
3. **Sexual dimorphism** — male vs female differences (where applicable)
4. **Photo references** — 4M + 4F where dimorphic, 8 generic otherwise; with attribution
5. **Pose preferences** — cited behavioral / locomotion research
6. **Folk-art conversion** — Mithila register transposition (body fill, decoration zones, density)
7. **Cited research** — minimum 4 open-access sources

## Status — built out

| Tier | Files done | Files target | Notes |
|---|---|---|---|
| Orders | 1 | 5 | Built: carnivora. Planned: aves, serpentes, cetacea, primates |
| Body types | 1 | 8 | Built: lean-predator. Planned: heavy-quadruped, lean-quadruped, stocky-omnivore, primate, bird, serpent, cetacean |
| Families | 1 | ~24 | Built: felidae. Priority next: cervidae, bovidae, phasianidae, elapidae |
| Species | 1 | 100 | Built: snow-leopard. Existing 41 + branch 46 + complete missing 13 |

Bibliography aggregated in [_bibliography.md](./_bibliography.md).
