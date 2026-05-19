# Madhubani Tee Catalog — Documentation Index

**Project:** AI-generated Madhubani-inspired animal tees, 60 animals × 4 poses = 240 designs.
**Status:** Foundation phase. Madhubani catalog driver is active; minimal animal
line-art beta is available for exact-stroke exploration.
**Last updated:** 2026-05-19

This index is the landing page for any agent — human or LLM — picking up
this project. Read this first; everything else hangs off these links.

---

## Where to start (by intent)

**"I'm new — what is this project?"**
→ Read [`CATALOG_PLAN.md`](./CATALOG_PLAN.md) §1–§3. ~5 minute read.

**"I want to add or render a new animal."**
→ Read [`WORKFLOW.md`](./WORKFLOW.md) end to end (set-at-a-time loop).
→ Then read [`PROMPT_GRAMMAR.md`](./PROMPT_GRAMMAR.md) for the register definitions.

**"A render came back. How do I score it?"**
→ Read [`RUBRIC.md`](./RUBRIC.md) (the 7-point quality bar).

**"What have we learned from v1, v2, v3 of the Indian animal renders?"**
→ Read [`../../generated/madhubani_animals/_learning/PRINCIPLES.md`](../../generated/madhubani_animals/_learning/PRINCIPLES.md).

**"I'm training a LoRA — where's the labeled corpus?"**
→ See [`../../generated/madhubani_animals/_learning/`](../../generated/madhubani_animals/_learning/) — pass_examples, fail_examples, and prompt_output_pairs.jsonl.

**"I need to know what's mastered vs flagged vs in-progress."**
→ Read [`../../generated/madhubani_animals/INDEX.md`](../../generated/madhubani_animals/INDEX.md) (live state).

---

## Document map

| File | What it contains |
|---|---|
| [`CATALOG_PLAN.md`](./CATALOG_PLAN.md) | Full master plan (16 sections). Source of truth for scope, schedule, decisions. |
| [`WORKFLOW.md`](./WORKFLOW.md) | The set-at-a-time render → review → retry-once → master/flag loop. |
| [`PROMPT_GRAMMAR.md`](./PROMPT_GRAMMAR.md) | The Mithila master-painter register: 6 expressive shifts + when to use which register. |
| [`RUBRIC.md`](./RUBRIC.md) | The 7-point quality bar that defines "mastered." |
| `../../generated/madhubani_animals/_learning/PRINCIPLES.md` | Distilled lessons from v1→v3 (what works, what fails, why). |

## Schema map

| File | What it contains |
|---|---|
| `../../brand/madhubani/animals.json` | 60-animal catalog. Per-animal metadata (body type, body fill color, signature features, IUCN status). |
| `../../brand/madhubani/poses.json` | The 4 canonical poses (standing-alert, seated-rest, signature-action, frontal-portrait) with subject-string templates. |
| `../../brand/madhubani/masters.json` | The 4 cited stylistic influences (Sita Devi, Ganga Devi, Baua Devi, Mithila kohbar tradition) with honest-framing copy. |
| `../../brand/madhubani/palette.json` | The 6-color vibrant-folk palette + body-fill rules + negative constraints. |

## Code map

| File | What it contains |
|---|---|
| `../../bin/style_engines.py` → `MinimalistTShirtEngine` | The engine. Builds the prompt directive from config. |
| `../../bin/forge_madhubani.py` | **The catalog driver — use this for everything.** `list / show / render / promote / flag / card / chat`. Schema-driven, deterministic, offline. |
| `../../bin/madhubani_qc.py` | Auto-scores the four machine-checkable Madhubani rubric gates and writes per-pose `*.qc.json` receipts. |
| `../../bin/minimal_animal_engine.py` | Beta procedural <=8-line animal mark engine. Emits SVG/PNG/QC/manifest. |
| `../../bin/forge.py minimal-animal` | CLI wrapper for exact-stroke minimalist animal exploration. |
| `../../bin/forge_web.py` | Form-based local web UI. Now includes the `madhubani-master-painter` tradition option. |
| `../../bin/_archive/` | Legacy per-batch render scripts (kept for provenance, not for running). |

## Skill map

| Skill | What it provides |
|---|---|
| `../../.claude/skills/madhubani-tshirt/SKILL.md` | Loadable skill for any future Cowork session — full grammar, rubric, workflow, masters, examples. Invoke when starting work on this project. |

---

## Decision log

Architectural decisions are recorded in `CATALOG_PLAN.md` §13 (Open
Decisions). When a decision is taken, the entry is struck through in
the doc and added here:

| Date | Decision | Recorded in |
|---|---|---|
| 2026-05-18 | Set size = 1 animal × 4 poses | CATALOG_PLAN §6 |
| 2026-05-18 | Expression target = Mithila master-painter register | CATALOG_PLAN §6a |
| 2026-05-18 | Workflow = render → review → retry-once → master/flag | CATALOG_PLAN §6 |
| 2026-05-18 | First validation animal = Rhino | CATALOG_PLAN §13 |
| 2026-05-18 | Texture shift #5 = include with caution | CATALOG_PLAN §6a |
| 2026-05-18 | Citation roster locked: Sita Devi, Ganga Devi, Baua Devi, Mithila kohbar tradition | brand/madhubani/masters.json |
| 2026-05-18 | LoRA training threshold = 12 animals mastered (~50 designs) | CATALOG_PLAN §7 |
| 2026-05-19 | Every Madhubani render/promote/flag/card action writes workflow JSONL; render sets write `render-manifest.json` | `bin/forge_madhubani.py` |
| 2026-05-19 | Exact <=8-line animal marks use procedural SVG, not diffusion, so the line count is construction-guaranteed | `docs/MINIMAL_ANIMAL_LINES.md` |
| 2026-05-19 | Madhubani checks 1–4 are machine-scored; promotion blocks failed auto-QC unless forced after human review | `bin/madhubani_qc.py` |
