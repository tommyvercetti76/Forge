# Forge — when to use what, and why it's built this way

> Read [README.md](README.md) for *how* to invoke each command.
> Read this for *when* and *why*, and to understand the full surface area.
> Read [docs/INDEX.md](docs/INDEX.md) for the maintained feature docs,
> architecture diagrams, mechanisms, and documentation protocol.
> Read [PLAN.md](PLAN.md) for *what's next*.

---

## 1. What Forge is, in one paragraph

Forge is a **local-AI factory** for English-driven content production on Apple Silicon. Drop an English brief → get a branded thumbnail + voiceover + episode kit. Drop a video → get a captioned, branded, upload-ready bundle. Drop a book → get a multilingual ASMR audiobook with a video loop. All offline, no API keys, no cloud round-trips. Every output goes through a versioned brand preset so the look stays consistent across a batch.

---

## 2. Architecture at a glance

```
              ┌─────────────────────────────────────────────────────────┐
              │                Shared local-AI substrate                │
              │  • mlx_whisper · mflux (FLUX schnell/dev/Kontext) · MLX │
              │  • Ollama · qwen3:8b · sarvam-translate-GGUF            │
              │  • Kokoro v1.0 · macOS `say` · procedural geometry       │
              │  • ffmpeg + libx264 + librubberband · Pillow            │
              └─┬──────────┬──────────┬──────────┬──────────┬───────────┘
                │          │          │          │          │
       ┌────────▼────┐ ┌───▼─────┐ ┌──▼─────┐ ┌──▼──────┐ ┌─▼──────────┐
       │ brand       │ │ video   │ │ episode│ │audiobook│ │ procedural │
       │ factory     │ │pipeline │ │pipeline│ │pipeline │ │ engines    │
       │ forge.py    │ │process- │ │ forge  │ │audio    │ │ mandala /  │
       │             │ │video.py │ │episode │ │book.py  │ │ childrens- │
       │ English →   │ │Video →  │ │Book →  │ │RTF/text │ │ book       │
       │ thumb /     │ │captioned│ │4-shot  │ │→ multi- │ │            │
       │ brief /     │ │bundle   │ │episode │ │lingual  │ │ Exact SVG  │
       │ edit /      │ │         │ │        │ │ASMR mp4 │ │ + PNG via  │
       │ voice /     │ │         │ │        │ │         │ │ polar geom │
       │ video       │ │         │ │        │ │         │ │            │
       └─────────────┘ └─────────┘ └────────┘ └─────────┘ └────────────┘
              │
              ▼
       ┌────────────────────────────────────────────────────────────────┐
       │ Style engines layer (bin/style_engines.py)                     │
       │   noir-cinema · wildlife-photo · impressionist · indian-class. │
       │   childrens-coloring-book (B&W line-art, picture-book grade)   │
       │   Typed configs · enum banks · domain invariants · masters     │
       │   ~30 token input → ~2.5k token dense FLUX directive           │
       │   Multi-seed · two-pass refine · LoRA stack · prompt library   │
       └────────────────────────────────────────────────────────────────┘
                                  │
              ┌────── share `brand/` ──────┐
              │  presets · voices · fonts  │
              │  palettes · loras · series │
              │  prompts/library.json      │
              └────────────────────────────┘
```

Several command groups, one design system. **What changes is the input medium and the output medium; the brand never drifts.**

---

## 3. Command surface

### 3.1 MAKE — produce something new

| Command | Input | Output | Engines used |
|---|---|---|---|
| `forge brief` | a topic sentence | metadata + 3 thumbnails + voiceover intro, all in one directory | qwen3 + FLUX + Kokoro/say |
| `forge episode` | a book or text blob | 4-part multi-shot subtitled video episode per language | qwen3 + FLUX + Kokoro + Whisper + ffmpeg |
| `forge audiobook` | an RTF or text file + a loop video | one ~1-min ASMR-mastered video per batch per language | Kokoro + Parler-TTS + sarvam-translate + ffmpeg |
| `forge mandala` | symmetry/ring/style parameters | exact SVG + PNG mandala + QC JSON | procedural polar geometry + Pillow |
| `forge childrens-book` | theme/page/symmetry parameters | symmetric drawing-book pages as SVG + PNG + QC | procedural vector geometry + Pillow |
| `forge engine render <id>` | engine + subject + knob overrides + (optional) recipe | one (or N) branded PNG with full directive sidecar | FLUX (dev / Kontext) + Pillow |
| `forge engine list` / `recipes` / `describe` | (none) / `--engine X` / engine id | browse engines + recipe library + full vocabulary | — |
| `forge thumbnail` | a preset + concept + headline | one branded PNG | FLUX (schnell or dev) + PIL overlay |
| `forge edit` | an existing image + instruction | restyled / instruction-edited PNG | FLUX.1-Kontext-dev |
| `forge voice` | a text string + voice preset | a `.wav`/`.mp3`/`.m4a`/`.aiff` | Kokoro (default) or macOS `say` |
| `forge video` | a thumbnail + audio | a Ken-Burns'd `.mp4` | ffmpeg `zoompan` |

### 3.2 BROWSE — inspect the design system

```sh
forge list              # all presets + voices with palette swatches
forge show <preset>     # full JSON dump of one preset
forge series list       # all defined consistency-lock series
forge series show <id>  # the full character/world/style lock
```

### 3.3 CONSISTENCY — lock the look of a batch

```sh
forge series new <id>                            # scaffold a series JSON
forge thumbnail --series <id> --frame-offset N   # deterministic seed = base + N
forge brief --series <id> ...                    # all 3 thumbs share style/world/cast
```

### 3.4 MODELS — manage the local cache

```sh
forge models scan [--full]      # inventory ~/Models/ (and find stragglers)
forge models adopt <path>       # move a downloaded file into the canonical home
forge models clean [--dry-run]  # remove partial/orphan blobs
forge models clean --remove org/repo --yes   # nuke an entire repo
```

### 3.5 SYSTEM — health, profiles, jobs

```sh
forge doctor [--deep]    # verify every tool, every model path, every env var
forge status             # last N jobs + active resource locks
forge bench              # write machine-tuned quality profiles
forge setup-voices --kokoro   # upgrade voice engine from `say` to Kokoro
forge wizard             # interactive menu mode (option 6 = audiobook)
```

### 3.6 VIDEO PIPELINE — a separate CLI (`process-video`)

```sh
process-video warmup                # pre-fetch all models (online, once)
process-video process <video.mp4>   # one video → upload-ready bundle
bash bin/watch-folder.sh IN OUT     # batch via auto-watch dir
```

---

## 4. When to use which command — decision tree

```
You have …
├── only a topic (no video yet)
│   └── want titles + 3 thumbs + voiceover intro → forge brief
│
├── a topic + an image concept                                 → forge thumbnail
├── a long script you wrote                                    → forge voice
├── an existing image you want restyled                        → forge edit
├── a thumbnail + a voice file, want to mux into mp4           → forge video
├── a book/text + a loop video, want multilingual ASMR         → forge audiobook
├── a book/text, want a 4-part subtitled video episode         → forge episode
│
├── a 1–3 min recorded video
│   ├── one video                                              → process-video process <v>
│   └── many videos to process automatically                   → watch-folder.sh IN OUT
│
├── a multi-frame batch that must look like one production     → series new, then --series <id>
├── a brand fingerprint that prompts can't drift from          → train a LoRA (BRAND-LORA.md)
│
└── disk pressure / want to inventory models                   → forge models scan / clean
```

---

## 5. Core design principles

These are the load-bearing decisions; knowing them helps you extend Forge without breaking it.

### 5.1 Presets are data, not code
Each visual style is **one JSON file** in `brand/presets/`. Code reads them; code does not know about specific presets. Adding a 5th look = adding a 5th JSON file. No Python edits.

### 5.2 Three-color rule, enforced
Every preset declares exactly three hex codes with roles: `dominant` (60%), `secondary` (30%), `accent` (10%). Renderer reads role names. You cannot accidentally use the accent color where the dominant should go — the rule lives in the data.

### 5.3 Type hierarchy is declared once
Each preset names `display_family`, `body_family`, and a pixel-scale (`title_px`, `sub_px`, `caption_px`). Different preset, different fonts and sizes — but the *roles* are the same so any tool emits them correctly.

### 5.4 Offline-first; lazy downloads are bugs
`process-video warmup` is the contract: run it once online and the system **must** work everywhere afterwards. `~/.kaayko-pipeline/ready.json` is the gate. `forge audiobook`, `forge brief`, etc. all fail loud if their model isn't on disk.

### 5.5 Schema-validated LLM output, three retries, deterministic fallback
LLM calls always go through JSON-shape validation. Up to 3 retries with rising temperature. If all fail, a deterministic template fallback runs. The pipeline cannot fail because the LLM hiccuped.

### 5.6 Atomic outputs, never half-written
Every file goes to `.tmp` first, then `os.replace()` atomically. A crashed run never leaves a half-rendered thumbnail or a corrupt JSON manifest. Restart picks up where it left off via cached outputs (`forge audiobook --batches 4` resumes from batch 4).

### 5.7 Each job emits a structured log
- Video pipeline writes `~/Videos/videos-out/<vid>/pipeline.log` (JSONL of step/status/seconds)
- Audiobook writes `logs/sentences.<lang>.jsonl` per language per batch
- Brief writes `brief.json` with the full LLM round-trip

### 5.8 Consistency is layered: preset → series → LoRA
Three lock-in mechanisms compose. Pick the cheapest one that's strong enough:
1. **Preset** — palette + type + style fingerprint via prompt prefix/suffix + negatives. Free, instant.
2. **Series** — pins `base_seed`, `style_anchor`, `world_sheet`, `character_sheet`, extra negatives. Frame N gets `seed = base_seed + N`. 10-min one-time edit.
3. **LoRA** — fine-tune a small adapter on a curated reference set. Only mechanism that constrains *weights*, not just prompts. 1–2 hr training. Recipe in [BRAND-LORA.md](BRAND-LORA.md).

Resolution order for LoRA: **CLI flag > series > preset**.

### 5.9 Voice engines are pluggable; "best available" by default
`synthesize_voice` checks `FORGE_TTS_ENGINE` (default `auto`):
- `auto` → Kokoro if installed AND model files present, else `say`
- `kokoro` → force neural (errors out if not ready — good for CI)
- `say` → force macOS legacy

For Indic languages, `audiobook.py` uses `ai4bharat/indic-parler-tts` instead — same contract, different engine, dispatched by target language code.

### 5.10 Resource profiles are real, named, shared
Three profiles match `forge bench`:
| Profile | FLUX model | Steps | Cooldown | Use for |
|---|---|---|---|---|
| `cool` | schnell | 4 | 20s | drafts, A/B tests, ideation |
| `balanced` | dev | 18 | 5s | default production runs |
| `max` | dev | 25 | 0s | final-approved frames |

`--draft` is sugar for `--profile cool`. `FORGE_FLUX_COOLDOWN_SEC=10` overrides cooldowns globally.

### 5.11 Conservative defaults on M5 Max
Defaults aren't "fastest possible" — they're "highest quality this hardware can sustain without bottlenecking." `--quality good` uses FLUX-dev 18-step + whisper-large-v3-turbo. `--quality best` uses 25-step + full large-v3. Your time costs more than 30s of compute.

### 5.12 Master primer — universal anti-failure block
Every FLUX generation merges `MASTER_NEGATIVES` from [forge.py](bin/forge.py) into the preset's own negatives. ~40 items covering: hand/limb anatomy errors, mirror-twin symmetry, plastic doll skin, accidental watermarks, jpeg artifacts. Plus a tail-end `MASTER_POSITIVE_HINT` that pushes away from "AI gloss" toward physical-medium craft. Opt-out per run with `FORGE_MASTER_PRIMER=off`. Suppression is the floor; engines + presets add domain-specific negatives on top.

### 5.13 Engines vs JSON presets — two parallel paths
JSON presets in `brand/presets/` are the simple path: 5-7 fields per preset (palette + typography + FLUX prefix/suffix/negatives), drop a file in, use it. **Engines** in `bin/style_engines.py` are the deeper path: typed Python modules with grouped sub-configs, enum-banks-with-metadata, encoded domain invariants, and 3-5 named master citations baked into every prompt. Engines emit `~2-2.7k token dense FLUX directives` from `~30 token input`. Both paths route into the same `flux_generate` (engines via `to_synthetic_preset()`). See [§6.3](#63-style-engines-the-deeper-path-when-presets-arent-enough).

---

## 6. Brand presets — what they are, what they aren't

A **preset** is a versioned visual identity stored as `brand/presets/<id>.json`. Each preset declares:

- `palette_60_30_10` — three hex codes with role names
- `typography.display_family`, `body_family`, `scale` — fonts + pixel sizes
- `composition.thumbnail` — headline anchor, dim band, accent bar geometry
- `composition.video_overlay` — hook/moment/CTA anchors
- `flux.positive_prefix`, `positive_suffix`, `negatives`, `guidance`, `steps`, `model`
- `prompt_rules.always_add` — fixed lines that get injected into every prompt
- `use_for` — when this preset shines

### Picking a preset (decision tree)
```
Is the content:
├── Narrative / character-driven / mythic feel?      → tartakovsky
├── Long-form thought / op-ed / founder voice?       → editorial
├── Dramatic / mystery / behind-the-scenes / reveal? → cinematic
└── Factual / explainer / data story / journalism?   → documentary
```

### Presets are NOT
- **Not themes** — a theme is "dark mode vs light mode." Presets are full visual identities.
- **Not templates** — a template is a fixed layout. Presets are *rules* that produce different specific compositions for different inputs.
- **Not bound to a project** — same preset, different topics. Rules don't know the topic.

### Adding a new preset (5 minutes, no code)
```sh
cp brand/presets/tartakovsky.json brand/presets/zine.json
# Edit: id, name, palette hex, fonts, FLUX prefix
forge list                      # now shows zine
forge thumbnail --preset zine   # use it
```

### 6.3 Style engines — the deeper path when presets aren't enough

`bin/style_engines.py` ships **five domain-expert engines** that emit a fully-composed FLUX directive (positive prompt + negatives + palette + runtime) from a small typed config. Same shape as `bin/mandala_engine.py` (frozen-dataclass config + enumerated banks + audit dict) but the output is a *prompt*, not a vector canvas.

| Engine | Specialty | Master citations baked into every prompt |
|---|---|---|
| `noir-cinema` | True cinematography model — 5 sub-genres (classic-1940s / neo-noir / nordic / tech / pulp), key:fill ratios, practical sources, period-correct wardrobe | John Alton (The Big Combo), Sin City vol.1, Blade Runner 2049, The Third Man, Chinatown |
| `wildlife-photo` | Lens + aperture + shutter mapping per species, bird-foot anatomy (zygodactyl / anisodactyl), mammal limb articulation, golden/blue-hour science | Frans Lanting, Tim Flach, Marsel van Oosten, Salgado, Vincent Munier |
| `impressionist` | Period-aware Van Gogh (Dutch-dark / Paris / Arles / Saint-Rémy / Auvers), brush technique (impasto / divisionist / broken-color), chromatic complementary pairs | Van Gogh's Cypresses '89, Monet's Haystacks, Cézanne, Seurat, Morisot |
| `indian-classical` | Tradition-aware (Tanjore / Madhubani / Pahari / Ravi Varma / Warli), mudra precision, attribute objects, hieratic composition | Raja Ravi Varma, Tanjore school, Pahari Kangra, Sita Devi (Madhubani), Nandalal Bose |
| `childrens-coloring-book` | Picture-book line-art for kids: 5 traditions (Mo-Willems-minimal / Boynton-whimsical / Carle-bold / Potter-naturalistic / Miyazaki-storyboard) × 3 age-ranges (toddler-3-5 / kids-6-9 / pre-teen-10-12) × narrative-moment beats. Pure B&W closed-shape fillable pages. | Mo Willems (Elephant & Piggie), Sandra Boynton (Moo Baa La La La), Eric Carle (Very Hungry Caterpillar), Beatrix Potter (Peter Rabbit), Miyazaki storyboards (Totoro) |

**Why engines, not just bigger JSON presets**: each engine encodes domain *invariants* that JSON can't. Example: `noir-cinema` raises a `ValueError` if you ask for `accent_color=eye-glow` with `pose=back-to-camera` (eyes hidden → can't glow). `impressionist` raises if you pair `vg_period=dutch-dark` with `palette_mode=chromatic-complementary` (Dutch period predates chromatic method historically). `indian-classical` raises if you ask for `tradition=warli` with a complex mudra (Warli's stick-figure form can't render hand detail). `childrens-coloring-book` raises if `age_range=toddler-3-5` is paired with `environmental_density=rich` (toddler hands can't color busy pages) or with `tradition=miyazaki-storyboard` (line density too fine for 3-year-olds). These rules live in code, not configuration.

#### Token math

```
Input  (you type):  --subject "..." (~30 chars) + ~5 knob overrides (~50 chars total)
Output (built):     2000-2700 char dense positive prompt + 10-13 specific negatives
                  + master primer (40 universal negatives) + craft hint
                  + palette + runtime
Expansion ratio:    ~50-90× per render
```

Each enumerated value carries a **30-50 token expansion**. You pick `lighting=venetian-blind` and the engine injects: *"horizontal slats of light from a Venetian-blind source cast diagonally across subject's face and torso in alternating bands of bright and shadow. The shadow lines are the signature of 1940s noir — they MUST be sharp-edged diagonals, never parallel to the frame."*

#### CLI surface

```sh
forge engine list                                # → childrens-coloring-book, impressionist, indian-classical, noir-cinema, wildlife-photo
forge engine describe noir-cinema | less         # full vocabulary as JSON (every knob + every value's metadata)
forge engine recipes [--engine X]                # list curated recipes from brand/prompts/library.json

# Basic render
forge engine render noir-cinema --subject "..."

# Recipe-driven (preset everything; CLI args override)
forge engine render --recipe noir-detective-alley

# Multi-seed gallery (best-of-N) + HTML contact sheet
forge engine render --recipe wildlife-snow-leopard-cliff --seeds 4

# Two-pass refinement (low-denoise img2img after base composition)
forge engine render --recipe impressionist-sunflowers-arles --refine --refine-strength 0.25

# Knob overrides — strict validation (unknown knobs fail loud with valid set listed)
forge engine render noir-cinema \
  --subject "android assassin on a Tokyo rooftop" \
  --config "cinematography.subgenre=tech-noir,cinematography.key_light=neon-practical,accent.accent_color=ice-blue"

# Extra negatives (appended to engine + master primer)
forge engine render noir-cinema --recipe noir-pulp-vigilante \
  --negative "plastic skin, anime stylization, neon glow on subject"
```

#### Defaults

- Output: `~/Desktop/forge-test/engine-renders/<engine>/<recipe-or-slug>.png` when `--out` is omitted
- Multi-seed: outputs land in `<engine>/<slug>/seed01.png` + `seed02.png` + `contact-sheet.html`
- Refinement: when on, base saved alongside as `<name>-base.png` (preserves the pre-refinement composition for comparison)
- Sidecar: every PNG gets `<name>.png.directive.json` with the full audit (which knob produced which phrase, the assembled prompt, seed) — reproducible

#### Prompt library — curated recipes

`brand/prompts/library.json` ships **20 vetted starter recipes** (4 per engine). Each is a tested combination of engine + subject + knob config + seed that produces coherent on-genre output. Invoke with `--recipe <id>`; override any field on the CLI to remix.

Recipes per engine:
- noir-cinema: `noir-detective-alley`, `noir-tech-tokyo-rooftop`, `noir-nordic-investigation`, `noir-pulp-vigilante`
- wildlife-photo: `wildlife-snow-leopard-cliff`, `wildlife-red-fox-snow`, `wildlife-blue-jay-perch`, `wildlife-eagle-flight`
- impressionist: `impressionist-starry-cypresses`, `impressionist-sunflowers-arles`, `impressionist-monet-haystacks`, `impressionist-cafe-night`
- indian-classical: `indian-krishna-yamuna-dawn`, `indian-vishnu-cosmic`, `indian-ganesha-temple`, `indian-shiva-meditation`
- childrens-coloring-book: `coloring-toddler-bear-and-balloon`, `coloring-kids-dragon-meadow`, `coloring-kids-rabbit-tea-party`, `coloring-preteen-totoro-forest`

#### Quality stack — the four techniques pros use

| Technique | Implementation | Quality gain |
|---|---|---|
| **Multi-seed gallery** | `--seeds N` flag, contact sheet HTML | ⭐⭐⭐⭐ — pick the gem from N variants; biggest practical lever |
| **Two-pass refinement** | `--refine` (img2img low-denoise FLUX-dev pass after base) | ⭐⭐⭐ — adds visible micro-detail at default strength 0.20; bump to 0.30 for stronger texture polish |
| **Higher resolution** | render at 1920×1080+ via `--width/--height` (when wired) | ⭐⭐ — finer detail, ~2× compute time |
| **LoRA stacking** | `--lora <file> --lora-scale 0.8` repeatable | ⭐⭐⭐⭐⭐ — biggest jump; see [brand/loras/README.md](brand/loras/README.md) |

#### LoRA library — per-engine recommendations

[brand/loras/README.md](brand/loras/README.md) documents surveyed FLUX LoRAs per engine, with honest assessments. Maturity varies by genre:

| Engine | Ecosystem | Recommended stack |
|---|---|---|
| wildlife-photo | ✅ Mature | `XLabs-AI/flux-RealismLora @ 0.8` + `Shakker-Labs/FLUX.1-dev-LoRA-add-details @ 0.5` |
| noir-cinema | 🟡 Patchy | `dvyio/flux-lora-film-noir @ 0.85` + add-details @ 0.5 |
| impressionist | 🟡 Sparse | `twn39/Vincent_van_Gogh_flux @ 0.85` — engine's master citations may do more |
| indian-classical | ❌ No specialist | Closest: `prithivMLmods/Flux.1-Dev-Indo-Realism-LoRA`. Best path: train your own via [BRAND-LORA.md](BRAND-LORA.md) |

Universal helpers (work with any engine):
- `Shakker-Labs/FLUX.1-dev-LoRA-add-details` — micro-detail booster, scale 0.4-0.6
- `XLabs-AI/flux-RealismLora` — the most-downloaded FLUX LoRA; photo-grade detail
- `prithivMLmods/Canopus-LoRA-Flux-FaceRealism` — if subject is a human face

LoRAs are a multiplier, not a crutch. Engines are designed to do most of the lifting via prompt-engineering alone. If a LoRA doesn't clearly improve a side-by-side test, ditch it.

#### Adding a new engine

Follow the shape in `bin/style_engines.py`:
1. Inherit `Engine` from `bin/_engine_base.py`
2. Define grouped sub-config dataclasses (`SubjectConfig`, `CinematographyConfig`, etc.)
3. Declare enum-banks (`EnumBank` with `EnumValue(key, description, implies, conflicts_with, masters)`)
4. Cite 3-5 master practitioners in `masters` class-var (named work + date + technique)
5. Implement `build(config) → Directive` that validates knobs, runs invariants, composes the prompt
6. Register in the module-level `ENGINES` dict

Each engine is a domain expert. Resist generic "more vocabulary" temptation — what makes the engine work is encoded *expertise* (period accuracy, anatomical invariants, iconographic correctness), not just longer word lists.


---

## 7. Audio engines — Kokoro, say, Parler-TTS

| Engine | Languages | Quality | Speed knob | Used by |
|---|---|---|---|---|
| **Kokoro v1.0** (default) | en | neural, very high | 0.5–1.5x | `forge voice`, `forge brief` intro, `audiobook` en |
| **macOS `say`** | en + Indic (Lekha hi) | dated, robotic | `say -r N` words/min | fallback when Kokoro not installed |
| **ai4bharat/indic-parler-tts** | en + hi + mr + 15 more Indic | neural, voice-by-description | description string controls pace | `audiobook` hi/mr |

### Why three engines?
- Kokoro is best for English ASMR/narration but is English-only (lang="en-us" hardcoded).
- macOS `say` is the zero-install fallback but sounds dated and lacks Marathi.
- Parler-TTS is the only open-weights Indic TTS that supports Marathi natively AND accepts ASMR voice descriptions ("warm, slow, intimate, breathy").

Engine selection is automatic per language in `audiobook.py:LANG_ENGINE`. Override via env var `FORGE_TTS_ENGINE` for the `forge voice` command.

### Voice presets (`brand/voices.json`)
Four canonical presets, each with both a `say_voice` and a `kokoro_voice_id` so the preset spans engines:

| ID | Use for | say | Kokoro |
|---|---|---|---|
| `male_warm` | storytelling, founder voice | Alex | am_michael |
| `male_anchor` | news-style, decisive CTAs | Daniel | am_adam |
| `female_warm` | intimate reflection, audiobook | Samantha | af_bella |
| `female_anchor` | factual delivery, data narration | Victoria | af_sarah |

---

## 8. Translation pipeline

`translate_texts_ollama()` ([bin/forge_runtime.py:171](bin/forge_runtime.py:171)) uses `hf.co/mradermacher/sarvam-translate-GGUF:Q4_K_M` via Ollama. Supports 15 target languages: en, hi, mr, gu, ta, te, kn, ml, bn, pa, ur + es/fr/de/pt.

Order-preserving batch translation. Used by:
- `forge voice --translate mr,hi` → emits sidecar `intro.mr.wav`/`intro.hi.wav` + text files
- `forge brief --translate mr,hi` → translates voiceover intro per language
- `process-video --captions en,mr,hi` → per-segment translation preserves SRT timing
- `forge audiobook --langs en,hi,mr` → per-batch chunk translation before TTS

Translation runs locally; no API. Quality varies by language pair — Hindi and Marathi are well-supported.

---

## 9. The audiobook pipeline in depth

The newest and most complex addition. Flow:

```
RTF file
   │ striprtf
   ▼
plain text
   │ normalize_for_tts: em-dash → ", ", ellipsis → ". ", smart quotes → straight
   ▼
clean text
   │ build_batches: page-windowed slices, head-N words spoken per batch,
   │                trim to sentence boundaries
   ▼
list of batches: [{idx, text, source_words_start, source_words_end}, …]
   │ per batch × per language:
   ▼
┌──────────────────────────────────────────────────────────────────┐
│ 1. translate_texts_ollama   (en source → hi/mr/etc)              │
│ 2. split_for_prosody        paragraphs × sentences               │
│ 3. tts (Kokoro for en, Parler for Indic)                         │
│    one sentence at a time → concat with silence:                 │
│      sent_pause_ms (400 default) between sentences               │
│      para_pause_ms (900 default) between paragraphs              │
│ 4. master_asmr (ffmpeg -filter_complex):                         │
│      voice chain: rubberband tempo=0.88 pitch=0.96 + HP/LP +     │
│                   gentle 2.5:1 compress + treble +1.5dB @ 8 kHz  │
│      optional bed: radio-static / vinyl-crackle  ←  --bed flag   │
│      loudnorm to -19 LUFS                                        │
│ 5. mux_video: -stream_loop -1 to loop video to audio duration,   │
│               libx264 veryfast crf=20, AAC 192k, +faststart      │
└──────────────────────────────────────────────────────────────────┘
   │
   ▼
final/book.batch{N:02d}.{lang}.mp4
```

### Ambient beds (`audiobook.py:BEDS`)
Procedural ffmpeg sources mixed under the voice. Choose with `--bed`:
- `none` — voice only
- `radio-static` (default) — band-passed pink noise with slow tape-warble vibrato, -24 dB
- `vinyl-crackle` — band-passed brown noise, -26 dB

### Batch resumption
`forge audiobook --batches 4,5,6 ...` runs only those batches. The manifest checkpoints after each batch, so a crash mid-run leaves a valid partial manifest.

---

## 10. The video pipeline in depth

`process-video.py` produces upload-ready video from a raw recording. Steps:

1. **Integrity check** — refuse to proceed unless ffprobe confirms ≥1 audio stream
2. **Transcribe** — mlx_whisper large-v3-turbo (or large-v3 at `--quality best`)
3. **Translate captions** — sarvam-translate per segment if `--captions en,mr,hi`
4. **Analyze** — qwen3:8b extracts hook + key moments + thumbnail concepts (schema-validated, 3 retries)
5. **Render overlays** — hook (top of video) + moments (left-aligned with accent bar) + CTA (bottom-right)
6. **Generate thumbnails** — FLUX with the active preset, 1–3 concepts
7. **Detect silences** — ffmpeg `silencedetect` for cut suggestions
8. **Burn in** — single filter_complex: subtitles + overlays at their timestamps + dim band
9. **Validate** — ffprobe the output; require `|out_dur - in_dur| < 0.5s`

The video pipeline is **not** a video editor. It doesn't cut, transition, or color-grade. It captions, overlays, and burns. Final-cut work still happens in your NLE.

---

## 11. Models and the canonical cache

All model files live under `~/Models/`:

```
~/Models/
├── ollama/         Ollama GGUF models (managed by Ollama itself)
├── huggingface/    HF cache — mflux, mlx_whisper, parler-tts read here
├── flux-bfl/       Raw BFL-format FLUX checkpoints (manual downloads)
└── kokoro/         Kokoro-TTS ONNX + voices
```

Forge sets `HF_HOME=~/Models/huggingface` for child tools so every engine agrees on the cache location. `forge models scan` finds stragglers (model-shaped files outside `~/Models/`).

### Currently installed models (per `forge doctor --deep`)

**Ollama (~79 GB):**
qwen2.5-coder 32/14/7B, deepseek-coder-v2:16b, qwen3:8b, deepseek-r1:8b, llama3.1:8b, aya-expanse:8b, glm-4.7-flash, sarvam-translate-GGUF

**HF cache (~80 GB):**
- Qwen2.5-Coder-32B-Instruct-4bit, DeepSeek-R1-Distill-Qwen-32B-4bit, Qwen2.5-VL-7B-Instruct-4bit
- BAAI/bge-m3 (embeddings)
- black-forest-labs/FLUX.1-schnell, FLUX.1-dev, FLUX.1-Kontext-dev (24 GB)
- ai4bharat/indic-parler-tts (3.75 GB, fp32)

**Audio:**
mlx-whisper Whisper-large-v3-turbo · Kokoro v1.0 (80 MB) · macOS `say` (fallback)

---

## 12. Resource profiles and thermal hygiene

FLUX inference pins the M5 Max GPU; sustained generation heats the SoC enough to throttle. Forge ships three named profiles ([forge.py:71](bin/forge.py:71)):

```python
PROFILES = {
    "cool":     {"flux_model": "schnell", "flux_steps": 4,  "flux_guidance": 0.0,  "cooldown": 20.0},
    "balanced": {"flux_model": "dev",     "flux_steps": 18, "flux_guidance": None, "cooldown":  5.0},
    "max":      {"flux_model": "dev",     "flux_steps": 25, "flux_guidance": None, "cooldown":  0.0},
}
```

`cooldown` is a `time.sleep()` between consecutive heavy gens. Override globally with `FORGE_FLUX_COOLDOWN_SEC=N`.

`--draft` is sugar for `--profile cool`. Use it for ideation; switch to `--profile max` only on the final approved frame.

---

## 13. Series — locking a batch to one production

A series is a JSON file at `series/<id>.json` that pins:

- `base_seed` — every frame's seed = `base_seed + frame_offset` (deterministic-but-distinct)
- `style_anchor` — one sentence repeated in every prompt
- `world_sheet` — setting, time, atmosphere, mood
- `character_sheet` — `{name: description}` map; concepts reference characters via `[name]` placeholders
- `locked_negatives` — extras that stack on the preset's negatives
- `lora_paths` / `lora_scales` — auto-applied LoRAs for this series

```sh
forge series new harbor-tales --preset tartakovsky
$EDITOR series/harbor-tales.json   # fill style/world/cast
forge thumbnail --preset tartakovsky --series harbor-tales \
  --concept "wide shot of [keeper] at the harbor wall, salt fog" \
  --headline "DAWN WATCH" --frame-offset 4
```

Frame 4 of `harbor-tales` is reproducible: same seed every run.

---

## 14. Failure modes & debugging

| Symptom | First place to look |
|---|---|
| "model not found" / silent FLUX failure | `forge doctor --deep` — checks every canonical path |
| Pipeline ran but output is wrong duration | `pipeline.log` JSONL — find the failing step |
| LLM returned malformed JSON | step logs include the raw response and the validation error |
| Kokoro not picking up | `cat ~/.kaayko-pipeline/ready.json`; `_kokoro_ready()` reports the reason |
| Ollama unreachable | `curl -s http://localhost:11434/api/tags` — empty? menu-bar app is off |
| Disk pressure | `forge models clean --dry-run` |
| Stuck job | `forge status` — shows recent jobs + active resource locks under `~/.forge/` |
| Audiobook batch crashed mid-run | manifest checkpoints after each batch; resume with `--batches 5,6,7,...` |

---

## 15. Extending Forge — playbooks

### Add a new visual preset
Copy `brand/presets/tartakovsky.json` → edit hex codes, fonts, FLUX prefix. Done.

### Add a new voice preset
Edit `brand/voices.json`. Add an entry with `id`, `display`, `use_for`, `say_voice`, `kokoro_voice_id`. Both engines auto-pick it up.

### Add a new ambient bed for audiobook
Edit `audiobook.py:BEDS`. Add a key mapping to an ffmpeg source filter chain (e.g. `anoisesrc=...,bandpass=...,volume=-NdB`). Wizard auto-discovers it.

### Add a new language
Edit `forge_runtime.py:LANGUAGE_NAMES` + `LANGUAGE_ALIASES`. Translation works automatically (sarvam-translate covers most Indic + many European). For TTS support, add the lang code to `audiobook.py:LANG_ENGINE` and `PARLER_DESC`.

### Train a brand LoRA
Recipe in [BRAND-LORA.md](BRAND-LORA.md). 20–40 reference images, mflux-train on M5 Max in ~1–2 hr. Drop the `.safetensors` into `brand/loras/` and it's selectable via `--lora <file>`.

---

## 16. What Forge is NOT

- **Not a cloud SaaS.** Everything runs on your hardware. No API keys, no exfiltration.
- **Not a video editor.** Captions, overlays, burns. No cuts/transitions/grading.
- **Not a transcription service.** Transcription is a component, not the product.
- **Not a uploader.** Forge produces files; you choose what goes live.
- **Not a music generator.** Out of scope until a quality local model lands.
- **Not a voice cloner.** XTTS/RVC are deliberately not adopted.
- **Not a real-time avatar.** Specialized models needed; not Forge's job.

---

## 17. Mental model for picking a tool when stuck

If you can describe the output in one of these noun phrases, the command is obvious:

| Noun phrase you'd use | Command |
|---|---|
| "an episode kit" | `forge brief` |
| "a thumbnail" | `forge thumbnail` |
| "a voiceover" | `forge voice` |
| "a brand-consistent rework of this image" | `forge edit` |
| "a podcast-style mp4 from this poster + audio" | `forge video` |
| "a four-shot subtitled mini-episode from this book" | `forge episode` |
| "a multilingual ASMR audiobook with a looped visual" | `forge audiobook` |
| "an upload-ready cut of this video I shot" | `process-video process` |
| "a noir / Van Gogh / wildlife-photo / Tanjore-style image with cinematography-level control" | `forge engine render <engine>` |
| "a children's-book coloring page in Mo-Willems / Boynton / Carle / Potter / Miyazaki style" | `forge engine render childrens-coloring-book --recipe …` |
| "4 variants of the same prompt; pick the best" | `forge engine render … --seeds 4` |
| "the same image but with sharper micro-detail" | `forge engine render … --refine` |
| "an exact mandala or symmetric drawing-book page" | `forge mandala` / `forge childrens-book` |

If you can't describe the output in one of those — you're outside Forge's scope. Use a different tool.

---

## 18. Reading order for a new contributor

1. [README.md](README.md) — install + cheatsheet
2. This file — the *why* of every design choice
3. [PLAN.md](PLAN.md) — what's next, ranked by impact
4. [AUDIT.md](AUDIT.md) — invariants the codebase enforces, P0/P1 bugs already fixed
5. [BRAND-LORA.md](BRAND-LORA.md) — the LoRA training recipe
6. `bin/forge.py` — start at `cmd_brief` (most representative entry point)
7. `bin/audiobook.py` — newest and most isolated; good way to understand the prosody design
8. `bin/process-video.py` — heaviest pipeline; `_cmd_process_inner` is the spine
