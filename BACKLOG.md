# Forge — feature backlog

One table, current state, honest. Legend: ✅ ships · 🟡 partial · ❌ missing · ⏸️ parked.

## Pipelines (`forge <cmd>`)

| Command | Status | Output | Known gaps |
|---|---|---|---|
| `forge brief` | ✅ | topic → 3 thumbs + intro VO | — |
| `forge episode` | ✅ | book/text → multi-shot subtitled mp4 | — |
| `forge audiobook` | ✅ | RTF + loop video → en/hi/mr ASMR mp4 | Sarvam Bulbul cloud TTS for Indic; production-tested |
| `forge thumbnail` | ✅ | preset + prompt → branded PNG | — |
| `forge edit` | ✅ | image + instruction → restyled PNG | Kontext path proven |
| `forge voice` | ✅ | text + voice preset → wav/mp3 | Kokoro + macOS say |
| `forge video` | ✅ | image + audio → Ken-Burns mp4 | — |
| `forge mandala` | ✅ | procedural symmetric mandala SVG+PNG | no subject (by design) |
| `forge childrens-book` | ✅ | procedural symmetric drawing-book pages | no subject (by design) |
| `forge wizard` | ✅ | sectioned interactive menu | free-form prompt input for text→image flows |

## Style engines (`forge engine render <id>`)

| Engine | Status | Recipes | Quality notes |
|---|---|---|---|
| `noir-cinema` | ✅ | 4 | strong — masters work, sub-genres distinct |
| `wildlife-photo` | ✅ | 4 | strong — lens/light/anatomy correct |
| `impressionist` | ✅ | 4 | strong — period-aware Van Gogh |
| `indian-classical` | ✅ | 4 | OK — sometimes loses tradition specificity |
| `childrens-coloring-book` | 🟡 | 14 | works but inconsistent — grey-fill leaks, setting drift, no A4 print format, no PDF compile |
| `mandala-art` | ⏸️ | 7 | built but 60/30/10 primer not landing; deferred until coloring-book done |

## Engine plumbing

| Feature | Status | Notes |
|---|---|---|
| Typed configs + enum banks with metadata | ✅ | reusable across engines |
| Domain invariants (ValueError on conflict) | ✅ | all engines have them |
| Master citations baked into prompts | ✅ | 3-5 per engine |
| Recipe library (`brand/prompts/library.json`) | ✅ | 37 recipes |
| Strict knob validation (no silent ignores) | ✅ | fixed earlier |
| Int/float type coercion on `--config` | ✅ | fixed earlier |
| Multi-seed gallery + HTML contact sheet | ✅ | `--seeds N` |
| Two-pass img2img refinement | ✅ | `--refine` |
| Hi-res / ultra-res | ✅ | `--hi-res` / `--ultra-res` |
| Custom guidance | ✅ | `--guidance N` |
| Extra negatives | ✅ | `--negative "..."` |
| `--from-image` (engine drives img2img) | ⏸️ | code in place, **uncommitted**; Kontext path produced noise on long prompts |
| LoRA stacking per-engine defaults | ❌ | currently ad-hoc CLI only |
| A4 / print-ready page format | ❌ | landscape 1280×720 default; no portrait, no DPI awareness |
| Multi-page PDF compile | ❌ | each render is a single PNG |
| Series-consistency lock for engine renders | ❌ | only the thumbnail flow has `--series` |

## Master primer (`bin/forge.py`)

| Feature | Status |
|---|---|
| Universal MASTER_NEGATIVES (50+ anti-failure) | ✅ |
| MASTER_POSITIVE_HINT (sub-detail + crisp edges) | ✅ |
| Anti-glow + halation negatives | ✅ |
| Devanagari font handling (Kohinoor Bold) | ✅ |

## Browse / configure / system

| Area | Feature | Status |
|---|---|---|
| Browse | `forge list` / `show` / `series list` | ✅ |
| Configure | `series new` / `setup-voices` | ✅ |
| Configure | `models scan` / `adopt` / `clean` | ✅ |
| System | `doctor` / `status` / `bench` | ✅ |

---

# Today's delivery — Children's Coloring Book to ship-ready

Focus: nothing else gets touched. Goal at end of day: `forge engine render --recipe X` produces a print-ready page reliably, and `forge engine compile-book` produces a print-ready multi-page PDF.

### Step 1 — Audit the 14 existing recipes (≤30 min GPU, background)
Render each recipe once at default settings. Tag each output: PASS / GREY-FILL / SETTING-DRIFT / COMPOSITION-OFF. Builds the evidence base for step 2.

### Step 2 — Targeted prompt fix (≤30 min)
Based on step 1's failure tags, make **one** focused prompt edit:
- If grey-fill is the main fail → strengthen the B&W lead + a few negatives
- If setting drift → make setting description come BEFORE character archetype in the template
- If composition-off → strengthen the layout/framing block
No primer rewrites, no enum reshuffles. One surgical fix.

### Step 3 — A4 portrait output (≤45 min)
Add `--page-format` flag accepting `a4-portrait` / `a4-landscape` / `letter-portrait`. Maps to:
- a4-portrait → 2480×3508 (300 DPI, 8.27×11.69")
- a4-landscape → 3508×2480
- letter-portrait → 2550×3300

Falls back to existing `--hi-res` / `--ultra-res` / `--width`/`--height` when not set.

### Step 4 — `forge engine compile-book` (≤1 h)
New sub-command:
```
forge engine compile-book \
  --recipes coloring-aaji-aajoba-page1-morning-sparrows,coloring-aaji-aajoba-page2...,page3...,page4... \
  --title "Aaji and Aajoba — A Texas Garden Story" \
  --author "..." \
  --out ~/Pictures/aaji-aajoba-book.pdf
```
Reuses already-rendered PNGs from `~/Desktop/forge-test/engine-renders/childrens-coloring-book/`. If a recipe's PNG doesn't exist, render it first. Output: print-ready PDF with title page + numbered pages.

### Step 5 — Re-render all 14 recipes at A4 portrait + compile a sample book (≤1 h GPU, background)
Validate the full pipeline end-to-end. Pick the Aaji-Aajoba 4-page series as the canonical "did we ship?" deliverable: PDF in hand, print test on actual paper if you want.

---

## Deferred until Step 5 is green

- mandala-art primer tuning
- `--from-image` for engines (Kontext noise bug unresolved)
- LoRA per-engine defaults
- Series-consistency lock for engine renders
- Per-page text overlays inside the PDF
