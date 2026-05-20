# Generated-image inventory — 2026-05-20

Stocktake of all generated artifacts across the system. Surfaces what's
promotable, what's legacy, what's not relevant, and what can be archived.

## Top-level breakdown

| Location | Total size | Image PNGs | Notes |
|---|---:|---:|---|
| `~/Desktop/forge-test/` | **3.9 GB** | 190 | Bloated — most is audio/video, not images |
| `~/Desktop/` (top level) | n/a | 54 | Working files + experiments + screenshots |
| `Forge/generated/` | 289 MB | 175 | The proper Forge output tree |

**3.9 GB of forge-test is heavy.** Most of it is non-image work from older sessions.

## Madhubani-relevant images (what matters for the catalog)

| Location | Count | Status | Action |
|---|---:|---|---|
| `Forge/generated/madhubani_animals/_learning/pass_examples/` | 4 | **GOLD STANDARD** — blackbuck_v3, elephant_v2, peacock_v3, rhino_v3 | KEEP, reference for all future work |
| `Forge/generated/madhubani_animals/attempts/` | 50 | Recent rendering work | REVIEW — today's L1+L2+N1-rev2 renders are pass-examples-tier; **candidates for promotion** |
| `Forge/generated/madhubani_animals/_legacy/indian_animals_v1` | 16 | v1 corpus, pre-current-engine | Keep for history; don't delete |
| `Forge/generated/madhubani_animals/_legacy/indian_animals_v2` | 16 | v2 corpus, post-color-floor fix | Keep for history |
| `Forge/generated/madhubani_animals/_legacy/indian_animals_v3` | 16 | v3 corpus, post-anatomy-first | Keep for history |
| `Forge/generated/madhubani_animals/_learning/fail_examples/` | varies | Labeled failures with reasons | KEEP — primary training-signal corpus |
| `~/Desktop/*.shekru-madhubani-*` | 10 | User's recent freeform Madhubani experiments | REVIEW — likely worth moving into `freeform/` under Madhubani |
| `~/Desktop/forge-test/showcase/` | 44 | Curated brand demo across all engines | KEEP — multi-engine showcase |
| `~/Desktop/forge-test/engine-renders/minimalist-tshirt/` | (some) | Per-engine systematic test renders | KEEP for test reference |

**Total truly-Madhubani PNGs:** ~140 (50 attempts + 48 legacy + 4 pass + ~10 shekru + ~28 in showcase/_archive). Of these, **0 have been promoted to `mastered/`** — the catalog is entirely in `attempts/` and `_learning/`.

## Per-animal coverage in `attempts/`

| Animal | Attempt count | Most recent work |
|---|---:|---|
| tiger | 14 | Today (L1+L2+N1-rev2 — production quality) |
| blackbuck | 8 | Earlier today (v1 with 4-pose set) |
| rhino | 8 | Earlier session |
| whale-shark | 8 | Earlier session |
| macaque | 6 | Earlier session |
| cobra | 2 | Today (production quality) |
| elephant | 2 | Today (production quality) |
| peacock | 2 | Today (production quality, but pose was "seated" which is wrong for a bird — flag) |

**33 of 41 species have ZERO attempts yet.** We've only explored ~20% of the catalog.

## Non-image work in forge-test (archive candidates)

| Directory | Size | What it is | Recommendation |
|---|---:|---|---|
| `~/Desktop/forge-test/SnowLeopard/` | **1.3 GB** | 4 image files + likely videos | Investigate, likely archive |
| `~/Desktop/forge-test/AudioBook_test/` | 826 MB | Zero images — audiobook artifacts | Archive |
| `~/Desktop/forge-test/Seattle/` | 678 MB | Zero images — likely video work | Archive |
| `~/Desktop/forge-test/folder-test/` | 465 MB | Zero images — folder-watcher test | Archive |
| `~/Desktop/forge-test/audiobook/` | 288 MB | Zero images — audiobook artifacts | Archive |
| `~/Desktop/forge-test/engine-renders/` | 165 MB | 82 image PNGs across all engines | **KEEP** — useful test corpus |
| `~/Desktop/forge-test/showcase/` | 120 MB | 44 image PNGs, curated showcase | **KEEP** — brand reference |
| `~/Desktop/forge-test/portal_images/` | 21 MB | 23 image PNGs | Review |
| `~/Desktop/forge-test/Forge_Thumbnails/` | 24 MB | 22 thumbnails | KEEP — brand workflow |

**Potential cleanup: ~3.5 GB** if the audiobook/Seattle/folder-test/snow-leopard work is archived elsewhere (e.g., compressed tar in cold storage). User decides.

## Promotability assessment for today's renders

Based on today's session and visual inspection vs `pass_examples/`:

| Render | File | Verdict |
|---|---|---|
| Tiger seated-rest (L1+L2+N1-rev2) | `attempts/tiger/v1/02_tiger_seated-rest.png` | **PROMOTABLE** — matches Madhubani folk-icon style. Caveat: QC heuristics flagged 2 spurious blockers (corners_clean, subject_centered) due to edge-to-edge composition. |
| Peacock seated-rest (L1+L2) | `attempts/peacock/v1/02_peacock_seated-rest.png` | Subject is in standing/perched pose despite "seated-rest" label — **pose mislabel**. Bird-body-type-specific pose taxonomy needed. Image quality is production-grade. |
| Elephant seated-rest (L1+L2) | `attempts/elephant/v1/02_elephant_seated-rest.png` | **PROMOTABLE** — matches `pass_examples/elephant_v2.png` |
| Cobra seated-rest (L1+L2) | `attempts/cobra/v1/02_cobra_seated-rest.png` | **PROMOTABLE** — exemplary serpent folk-icon |

**Recommendation:** promote tiger / elephant / cobra after the QC heuristic re-tune. Peacock needs body-type-specific pose authored first.

## What's currently scattered (the user's "rules all over files" concern)

See `docs/MADHUBANI_ART_IDENTITY.md` (to be written) for the consolidated reference. The art-identity rules live in:

| File | Authority | Status |
|---|---|---|
| `brand/madhubani/animals.json` v2.0.0 | 41 species data | current |
| `brand/madhubani/poses.json` v1.0.0 | 4 generic poses | **STALE** — needs per-body-type expansion |
| `brand/madhubani/palette.json` | Canonical 6-color palette | current |
| `brand/madhubani/masters.json` | Master-painter citations | needs expansion with Padma Shri / Mithila Museum / academic provenance |
| `brand/madhubani/species_iconography.json` | 10-species iconography | **unused** by minimalist-tshirt engine (deliberately, after the photoreal-conflict revert) |
| `generated/madhubani_animals/_learning/PRINCIPLES.md` | 272 lines distilled wisdom | de-facto art-identity doc; should be promoted to `docs/` |
| `bin/style_engines.py` MinimalistTShirtEngine | ANATOMY FIRST + NO SIGNATURE + FACE & EXPRESSION clauses | code-resident; should reference the master doc |
| `bin/forge_madhubani.py` build_subject_string | Body fill override + 7-zone decoration + ornament rules | code-resident; should reference the master doc |
| `docs/catalog/PROMPT_GRAMMAR.md` | Engine prompt grammar | current |
| `docs/catalog/RUBRIC.md` | 7-item quality rubric | current |
| `docs/catalog/WORKFLOW.md` | Render → review → master/flag flow | current |
| `docs/catalog/CATALOG_PLAN.md` | The original catalog plan | current |

## Immediate actions surfaced by this inventory

1. **Consolidate art identity** — `docs/MADHUBANI_ART_IDENTITY.md` becomes the single canonical doc. [Tracked]
2. **Per-body-type poses** — `poses.json` v2 must reflect bird ≠ mammal ≠ serpent pose grammar. [Tracked]
3. **Promote today's 3 production-grade renders** — tiger / elephant / cobra (after pose fix + QC re-tune)
4. **Move `~/Desktop/shekru-madhubani-*` files** into `freeform/` under Madhubani if they're worth keeping
5. **Optionally archive 3.5 GB of non-image forge-test work** (audiobook/Seattle/folder-test)
6. **Document the citations** — `docs/MADHUBANI_BIBLIOGRAPHY.md` for the masters + scholars. [Tracked]
