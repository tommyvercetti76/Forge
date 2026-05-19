---
name: madhubani-tshirt
description: Use this skill when working on the Madhubani-inspired animal tee catalog in this repo. Triggers include any mention of Madhubani, Mithila, the catalog plan, the set-at-a-time workflow, the rhino/tiger/peacock animal series, or any task involving the MinimalistTShirtEngine with the madhubani-folk-icon motif. Loads the full project context — workflow, prompt grammar, quality rubric, masters, schemas, and lessons learned from v1→v3 iteration.
---

# Madhubani Tee Catalog — Skill

You are picking up work on a Madhubani-inspired animal tee catalog project.
This skill loads everything you need to be productive: the workflow, the
prompt grammar, the quality bar, the master citations, the schemas, and
the lessons learned from earlier iterations.

> **Note on location:** this file lives at `docs/catalog/SKILL.md` inside
> the Forge repo (not in `.claude/skills/`) because Forge has its own
> skill conventions. Any agent working in this repo should read this
> document as the project-specific skill for the Madhubani catalog work.

## What this project is

**Scope:** 60 animals × 4 poses = 240 mastered t-shirt designs in the
Madhubani folk-art tradition of Mithila, Bihar.

**Status as of 2026-05-18:** Foundation phase. First validation set
(Rhino × 4 poses in `madhubani-master-painter` register) is queued to
render. Earlier iterations: 8 Indian animals × 3 prompt versions
(v1, v2, v3) parked in `generated/madhubani_animals/_legacy/`.

**Why this project matters:** Each design is intended to be premium,
expressive, and to ship with full provenance acknowledging the Mithila
tradition. Not "AI-generated wildlife tee" (commodity) — "AI-generated
tee citing Sita Devi and the kohbar tradition, methodology disclosed,
honest framing about authenticity, supports Mithila Art Institute"
(thoughtful product).

## Where to find what

Read these files when relevant — do not duplicate their content into
your responses:

| Need | File |
|---|---|
| Full project plan | `docs/catalog/CATALOG_PLAN.md` |
| Set-at-a-time workflow | `docs/catalog/WORKFLOW.md` |
| Prompt grammar (registers, rule stack) | `docs/catalog/PROMPT_GRAMMAR.md` |
| 7-point quality rubric | `docs/catalog/RUBRIC.md` |
| Distilled lessons v1→v3 | `generated/madhubani_animals/_learning/PRINCIPLES.md` |
| 60-animal data | `brand/madhubani/animals.json` |
| 4-pose templates | `brand/madhubani/poses.json` |
| Master citations | `brand/madhubani/masters.json` |
| 6-color palette + rules | `brand/madhubani/palette.json` |
| Engine source | `bin/style_engines.py` → `MinimalistTShirtEngine` |
| Pass examples (labeled) | `generated/madhubani_animals/_learning/pass_examples/` |
| Fail examples (annotated) | `generated/madhubani_animals/_learning/fail_examples/` |
| LoRA-ready training pairs | `generated/madhubani_animals/_learning/prompt_output_pairs.jsonl` |

## The 12 principles you must internalize

Full versions in `_learning/PRINCIPLES.md`; one-liner reminders here:

1. Audit prompts for internal contradictions; pick a side.
2. Promote your single most important rule to the top of the prompt.
3. Negatives in long arrays are weakly respected — use positive demands.
4. Diffusion does not know structure; constrain anatomy explicitly.
5. Repeating an instruction three different ways can over-fire — add counter-rules.
6. When you remove an implicit influence, make its contribution explicit.
7. Anatomy rules should be species-bucket-aware.
8. Cite primary sources, not derivative work.
9. Seeds are a knob for exploration, not a fix for a weak prompt.
10. Provenance is a feature — ethics + reproducibility + marketing.
11. Bound iteration with workflow gates; flagging is healthy.
12. Layer your registers; engine improvements lift the whole catalog.

## The set-at-a-time loop (summary)

```
Pick animal → Render 4 poses → Review → Identify gaps → Retry once
            → Review again → Master/Flag/Reject per pose
            → Generate ARTIST_CARD → Update INDEX → Next animal
```

**Retry-once-then-flag is non-negotiable.** Do not iterate indefinitely
on one animal. If the engine can't produce a pose in 2 attempts, flag
it and revisit after the engine improves.

## The two registers

- **`madhubani-contemporary`** — mass-market polish, vector-clean,
  screen-print safe. Default for capsule basics.
- **`madhubani-master-painter`** — premium register, hand-drawn line
  weight, composed palette, character-bearing eyes, controlled hand-
  painted texture. Default for the premium catalog. See
  `PROMPT_GRAMMAR.md` for the six concrete shifts.

## Masters cited (honest framing)

The four citations on every artist card:

1. **Sita Devi** (1914–2005) — kohbar wall paintings, almond-eye treatment
2. **Ganga Devi** (1928–1991) — bharni-style fill rhythm, dot-and-petal aura
3. **Baua Devi** (1944–) — matsya and naga compositional motifs
4. **Mithila kohbar bridal-chamber tradition** — bird-and-animal vocabulary

**Honest framing copy** appears on every artist card and storefront
listing: *"This series is Madhubani-INSPIRED, not authentic Madhubani.
The living custodians of the authentic tradition are the artisans of
Mithila — predominantly women working in family lineages. Support
them directly through the Mithila Art Institute."*

Never claim the work IS authentic Madhubani. Always credit the tradition
and direct customers to support practitioners.

## Common tasks and how to approach them

### "Render a new animal"

1. Add an entry to `brand/madhubani/animals.json` (slug, display_name,
   binomial, series, body_type, body_fill_color, signature_features,
   signature_action, rest_pose_for_species, iucn_status, conservation_note,
   seed_block_start).
2. Render 4 poses into `generated/madhubani_animals/attempts/{slug}/v1/`.
3. Apply the WORKFLOW.md loop.

### "A render came back, score it"

Use `docs/catalog/RUBRIC.md` — copy the scoring template into the set's
`REVIEW_NOTES.md`, fill in the 7 checkboxes per pose, make the
master/flag/reject call.

### "A pose is failing the same way across multiple animals"

Likely an engine-level issue. Check `_learning/fail_examples/_LABELS.json`
for similar failure modes. If the failure pattern matches one we've
solved before, the fix is already in `style_engines.py`. If it's new,
follow the v1→v2→v3 pattern: write a new positive rule for the engine,
test it on the affected animals, update `_LABELS.json` and PRINCIPLES.md
with the new lesson.

### "User wants to expand the catalog beyond 60 animals"

Pause and check Open Decisions in `CATALOG_PLAN.md` §13. Mythological /
composite tier is explicitly deferred to Phase 2. Don't add subjects
that change the body-type taxonomy without updating
`animals.json` `body_types` first.

### "User wants to skip the artist card / honest framing"

Push back gently. The provenance system is core to the project's
positioning per `CATALOG_PLAN.md` §6b. The honest-framing copy
respects the Madhubani GI status and protects against authenticity
pushback. If the user insists on stripping it, document the decision
explicitly in the artist card and flag for review.

## What NOT to do

- Don't reintroduce Western design masters (Paul Rand, Saul Bass,
  Otl Aicher, etc.) to the engine. v1 testing proved they collapse
  Madhubani designs into mascot logos. The engine `masters` tuple
  for `MinimalistTShirtEngine` is intentionally empty.
- Don't batch-render multiple animals at once. The workflow is
  one-at-a-time per `CATALOG_PLAN.md` §6.
- Don't claim authentic Madhubani in any storefront copy or artist
  card. Always "Madhubani-inspired" or "Mithila-inspired."
- Don't seed-hunt to fix a bad prompt. If a prompt fails on first
  attempt, do the one allowed retry and then flag. The flag pile is
  the engine's todo list.
- Don't add to `MinimalistTShirtEngine` without running the unit
  tests in `tests/test_minimalist_tshirt_engine.py`.

## How this skill stays current

When you complete work on the catalog, update:
1. `generated/madhubani_animals/INDEX.md` — mastered/flagged tallies
2. `_learning/PRINCIPLES.md` — if you discover a new generalizable lesson
3. `_learning/{pass,fail}_examples/_LABELS.json` — if you produce a
   notably good or bad new render worth teaching from
4. `docs/catalog/INDEX.md` decision log — if any architectural decision
   was made

Treat the teaching corpus as an asset that compounds. Every new lesson
captured here saves the next agent's time.
