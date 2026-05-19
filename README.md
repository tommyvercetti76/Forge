# Forge

Local-first media factory for Apple Silicon.

Forge turns prompts, books, scripts, images, and videos into production assets:
branded thumbnails, specialist FLUX images, procedural line art, voiceovers,
episodes, audiobooks, subtitles, and upload-ready video bundles.

Forge is built for a real production desk, not a demo folder. It has brand
presets, series locks, local model cache rules, job state, web controls, CLI
controls, and audit handoffs for the parts that still need to become perfect.

## Reality Check

This section is intentionally blunt. Trust this over older notes.

- Forge is local-first, not local-only. Most image, LLM, translation, and English
  TTS workflows can run locally after setup. High-quality Hindi and Marathi TTS
  can use Sarvam Bulbul through `SARVAM_TTS_KEY`.
- Forge targets macOS on Apple Silicon. The performance profile assumes an M-series
  machine with enough unified memory for FLUX workloads.
- FLUX rendering depends on `mflux` and cached model weights. `forge doctor --deep`
  is the first thing to run when renders behave strangely.
- `forge audiobook` and `bin/audiobook.py` are not the same product surface.
  `forge audiobook` is the general CLI wrapper. `bin/audiobook.py` is the deeper
  multilingual ASMR/book-video pipeline.
- Near-perfect 10-page book localization in Hindi, English, and Marathi is a
  defined target, not fully guaranteed by the current implementation. The audit,
  gaps, target pipeline, and definition of done live in
  [docs/BOOK_LOCALIZATION_AUDIT_HANDOFF.md](docs/BOOK_LOCALIZATION_AUDIT_HANDOFF.md).
- `bin/audiobook.py --batch-pages 10 --spoken-words 150` speaks the first 150
  words of each 10-page batch by default. That is excerpt mode, not full-page
  translation coverage.

## What Forge Can Do Today

| Area | Primary entrypoints | Output |
| --- | --- | --- |
| Web console | `forge web` | Browser wizard, run console, galleries, form-driven generation |
| Brand thumbnails | `forge thumbnail`, `forge brief` | PNG thumbnails, background generations, title/metadata kits |
| Specialist image engines | `forge engine ...` | FLUX renders plus directive JSON and gallery metadata |
| Image editing | `forge edit` | Edited variants from an existing image |
| High-res via upscaler | `forge engine render ... --upscale {2x,3x,4x,6x,8x,12x,16x}` | RealESRGAN-ncnn-vulkan post-render upscale, safe on M5 Max |
| Procedural art | `forge mandala`, `forge childrens-book`, `forge folk-art`, `forge minimal-animal` | SVG/PNG line art and QC JSON |
| Voiceover | `forge voice`, `forge setup-voices` | English audio plus translated sidecars |
| Episodes | `forge episode` | Mini-segment videos, scripts, stills, subtitles, QC manifests |
| Audiobooks | `forge audiobook`, `bin/audiobook.py` | Chunked narration, translations, subtitles, optional video mux |
| Video prep | `process-video warmup`, `process-video process` | Transcripts, captions, overlays, thumbnails, final MP4 |
| WhatsApp joke factory | `bin/whatsapp_joke_factory.py` | Share-ready joke packs for Indian audiences over 60, with QC + manifest |
| Ops | `forge doctor`, `forge status`, `forge models`, `forge bench` | Runtime checks, job state, model inventory, profiles |

## Specialist Engines

Each engine declares its native canvas — typing `forge engine render <name>` without `--width`/`--height` uses the genre's natural aspect.

| Engine | Native canvas | Register |
| --- | --- | --- |
| `childrens-coloring-book` | 1024×1280 portrait (4:5) | Bold B&W ink line art, 8.5×11 coloring page |
| `mandala-art` | 1280×1280 square (1:1) | Radial mandalas with subject at center |
| `indian-classical` | 1024×1280 portrait (4:5) | Madhubani / Warli / Tanjore / Pahari / Ravi-Varma |
| `impressionist` | 1280×960 landscape (4:3) | Monet / Renoir / Seurat / Van Gogh painterly |
| `noir-cinema` | 1280×720 widescreen (16:9) | Roger Deakins / Gordon Willis film stills |
| `wildlife-photo` | 1280×720 widescreen (16:9) | Nat Geo / BBC Earth editorial framing |
| `stylized-cinematic` | 1280×720 widescreen (16:9) | Tartakovsky / Mignola / McQuarrie / Ghibli |
| `minimalist-tshirt` | 1280×1280 square (1:1) | Screen-printable apparel graphics ([docs/MINIMALIST_TSHIRT_ENGINE.md](docs/MINIMALIST_TSHIRT_ENGINE.md)) |

Beta minimalist line-art lane: `forge minimal-animal --animal "alert tiger in
side profile" --max-lines 8` emits a construction-guaranteed SVG/PNG mark plus
QC and manifest. See [docs/MINIMAL_ANIMAL_LINES.md](docs/MINIMAL_ANIMAL_LINES.md).

Resolution priority chain: `--ultra-res` > `--hi-res` > explicit `--width`/`--height` > engine native canvas > 1280×720 fallback. The upscale path (next section) is the safest route to print-grade resolution on M5 Max.

## Repository Map

```text
Forge/
|-- README.md                         # this front door
|-- SKILL.md                          # mental model for choosing Forge tools
|-- PLAN.md                           # future work using existing local models
|-- PLAN_V2.md                        # local story-studio north star
|-- ALIGNMENT_PLAN.md                 # gap review and execution plan
|-- AUDIT.md                          # output correctness audit
|-- BACKLOG.md                        # feature backlog
|-- BRAND-LORA.md                     # brand LoRA training and install guide
|-- bin/
|   |-- forge.py                      # main CLI
|   |-- forge_web.py                  # local browser UI
|   |-- forge_runtime.py              # cache, jobs, locks, LLM/TTS helpers
|   |-- style_engines.py              # specialist FLUX engines
|   |-- _engine_base.py               # engine contracts
|   |-- mandala_engine.py             # procedural mandala/line-art renderer
|   |-- minimal_animal_engine.py      # beta <=8-line animal mark renderer
|   |-- audiobook.py                  # multilingual book/video pipeline
|   |-- process-video.py              # upload-ready video prep pipeline
|   |-- migrate-models.sh             # adopt model files into ~/Models
|   `-- watch-folder.sh               # folder watcher for video prep
|-- brand/
|   |-- presets/                      # thumbnail/image brand presets
|   |-- prompts/library.json          # reusable engine recipes
|   |-- loras/README.md               # LoRA install notes
|   |-- references/README.md          # brand/reference source notes
|   `-- voices.json                   # voice preset registry
|-- docs/                             # architecture, audits, handoffs, contracts
|-- series/                           # consistency locks for recurring worlds
|-- system/                           # launchd watcher plist
|-- tests/                            # runtime regression tests
`-- archive/                          # older scripts kept for reference
```

## Install

From this repo:

```sh
cd ~/Desktop/Forge
chmod +x bin/*.py bin/*.sh

mkdir -p ~/.local/bin
ln -sf ~/Desktop/Forge/bin/forge.py ~/.local/bin/forge
ln -sf ~/Desktop/Forge/bin/process-video.py ~/.local/bin/process-video
```

Make sure `~/.local/bin` is on your shell path:

```sh
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zprofile
source ~/.zprofile
```

Run the first checks:

```sh
forge list
forge doctor --deep
forge models scan
```

For video work, warm the video pipeline once:

```sh
process-video warmup
```

## Start The Web UI

```sh
forge web --host 127.0.0.1 --port 5002
```

Use `--no-open` if you only want the server:

```sh
forge web --host 127.0.0.1 --port 5002 --no-open
```

Four concurrent FLUX slots on a 128 GB Apple Silicon machine:

```sh
forge web --host 127.0.0.1 --port 5002 --metal-slots 4
```

The web UI is a control surface over the same CLI/runtime. When a web option
seems suspicious, confirm against the matching CLI help and the audit docs.

The web UI has been decluttered into 6 top-level areas:
**GALLERY · CREATE · EDIT · PIPELINES · LIBRARY · SYSTEM**.

The **Create** page is a unified surface — pick a Style (children's coloring /
mandala / Indian folk / stylized cinematic) and the engine-specific dropdowns
auto-swap in the "Style details" drawer. Every form leads with the daily-driver
controls (prompt, recipe, source image, render mode, final size, seed,
variants). Advanced controls (guidance, refine, quantize, LoRA stack, custom
width/height) live in closed `<details>` drawers — reachable, not in the way.
Kontext-incompatible controls auto-dim when a source image is uploaded.

## Daily Commands

### Inspect The System

```sh
forge doctor --deep
forge status
forge models scan --full
forge bench
```

### Render A Thumbnail

```sh
forge thumbnail \
  --preset tartakovsky \
  --concept "lone paddler at sunrise on an alpine lake, cinematic golden hour" \
  --headline "WHY I PADDLE ALONE" \
  --sub "what 200 lakes taught me" \
  --profile balanced \
  --seed 1 \
  --out ~/Pictures/podcast-thumb.png
```

Use an existing image as the background:

```sh
forge thumbnail \
  --preset thumbnail-bold \
  --bg ~/Pictures/frame.png \
  --headline "THE QUIET PART" \
  --sub "a field note" \
  --out ~/Pictures/thumb-from-frame.png
```

### Render With A Specialist Engine

```sh
forge engine list
forge engine recipes
forge engine describe wildlife-photo

forge engine render wildlife-photo \
  --subject "a tiger crossing a shallow forest stream at dawn" \
  --profile balanced \
  --seed 7 \
  --out ~/Pictures/wildlife-tiger.png
```

### Render An 8-Line Minimal Animal Mark

```sh
forge minimal-animal \
  --animal "alert tiger in side profile with a long tail" \
  --max-lines 8 \
  --out ~/Pictures/tiger-eight-line.png
```

Forge writes `.png`, `.svg`, `.qc.json`, and `.manifest.json`. The SVG stroke
count is the source of truth; the PNG is only the preview.

### High Resolution — The Upscale Path

Native ultra-res FLUX (`--ultra-res` at 2048×1152) over-subscribes Metal memory
on M5 Max when combined with `--from-image` (Kontext). The safer, faster path to
print-grade resolution is **render small, upscale via RealESRGAN-ncnn-vulkan**:

```sh
# 1024×1280 base render + 4× upscale → 4096×5120 final (~21 MP)
forge engine render childrens-coloring-book \
  --subject "a friendly bear cub holding a balloon" \
  --upscale 4x

# 1280×1280 base + 8× upscale → 10240×10240 final (~105 MP), chained 4×→2×
forge engine render mandala-art \
  --subject "an elephant facing forward, body filled with Madhubani patterns" \
  --upscale 8x
```

Available factors: `2x` `3x` `4x` `6x` `8x` `12x` `16x`. Non-native factors
(6/8/12/16) chain two passes. Each pass is ~6 seconds.

Pre-flight checks before any heavy mflux launch — refuses to start if
`<20 GB` free RAM (override via `FORGE_MFLUX_MIN_FREE_GB=10`). Kontext/img2img
renders are auto-clamped to ≤1280×720 because the combination with `--from-image`
oversubscribes Metal; pair Kontext with `--upscale` for the high-res final.

### Render Procedural Line Art

These engines do not use diffusion. They write deterministic SVG/PNG assets.

```sh
forge mandala \
  --style floral \
  --symmetry 24 \
  --rings 9 \
  --complexity max \
  --width 2400 \
  --height 2400 \
  --seed 45 \
  --out ~/Pictures/mandalas/floral-24.png

forge childrens-book \
  --theme all \
  --pages 3 \
  --symmetry 12 \
  --rings 7 \
  --complexity max \
  --out ~/Pictures/symmetric-childrens-book/

forge folk-art \
  --theme buddha-peacock \
  --width 2400 \
  --height 1800 \
  --stroke-width 3 \
  --out ~/Pictures/folk-art/buddha-peacock.png
```

### Create Voiceover

```sh
forge setup-voices --kokoro

forge voice \
  --preset male_warm \
  --text "Welcome back. Today we are talking about still water and memory." \
  --out ~/Sounds/intro.wav
```

Translated sidecars:

```sh
forge voice \
  --preset male_warm \
  --text "Welcome back." \
  --translate hi,mr \
  --out ~/Sounds/intro.wav
```

English defaults to Kokoro when installed, then macOS `say` as fallback. Indic
audio is best with Sarvam:

```sh
export SARVAM_TTS_KEY="sk_..."
```

### Build A Brief

```sh
forge brief \
  --topic "I paddled solo across 200 lakes and this is what changed" \
  --preset tartakovsky \
  --voice male_warm \
  --profile balanced \
  --out ~/Pictures/episode-05/
```

Expected bundle:

```text
episode-05/
|-- metadata/
|-- thumbnails/
|-- voiceover-intro.wav
`-- brief.json
```

### Build A Mini Episode

```sh
forge episode \
  --book ~/Documents/book-excerpt.txt \
  --title "Still Water" \
  --preset cinematic \
  --voice male_warm \
  --translate hi,mr \
  --segments 4 \
  --seconds 15 \
  --shots-per-segment 4 \
  --profile balanced \
  --out ~/Pictures/still-water-episode/
```

Use `--no-flux` when you want title-card visuals instead of generated stills:

```sh
forge episode --book ~/Documents/book.txt --no-flux --out ~/Pictures/episode/
```

### Build Audiobook Assets

General Forge wrapper:

```sh
forge audiobook \
  --book ~/Documents/book.txt \
  --voice male_warm \
  --translate hi,mr \
  --out ~/Music/book-audiobook/
```

Deeper multilingual book/video pipeline:

```sh
python3 bin/audiobook.py \
  --rtf ~/Documents/book.rtf \
  --video ~/Movies/loop.mp4 \
  --out-dir ~/Movies/book-output \
  --langs en,hi,mr \
  --batch-pages 10 \
  --page-words 250 \
  --spoken-words 150 \
  --subtitles srt
```

For full 10-page subtitle/audio translation, do not treat `--spoken-words 150`
as complete coverage. Follow
[docs/BOOK_LOCALIZATION_AUDIT_HANDOFF.md](docs/BOOK_LOCALIZATION_AUDIT_HANDOFF.md)
before promising production accuracy.

### Process A Video

```sh
process-video process ~/Videos/clip.mp4 --quality good --noisy
process-video process ~/Videos/clip.mp4 --quality balanced --captions en,hi,mr
```

Folder watcher:

```sh
bash ~/Desktop/Forge/bin/watch-folder.sh ~/Videos/videos-in ~/Videos/videos-out
```

## Resource Profiles

Profiles are the shared speed/quality vocabulary across CLI and web UI.

| Profile | FLUX model | Steps | Guidance | Cooldown | Intended use |
| --- | --- | ---: | ---: | ---: | --- |
| `cool` | `schnell` | 4 | 0.0 | 20s | Preview/scouting pass, fastest and lowest heat |
| `balanced` | `dev` | 18 | preset/default | 5s | Default production iteration |
| `max` | `dev` | 25 | preset/default | 0s | Better final detail when time allows |
| `quality` | `dev` | 36 | preset/default | 0s | Production-grade q8 path for line art/iconic work |

Resolution, step count, and model choice dominate speed. Quantization helps with
memory pressure, but it is not the main speed lever on Apple Silicon.

Parallel FLUX renders are opt-in. Set `FORGE_METAL_SLOTS=4` or
`FORGE_FLUX_PARALLEL_JOBS=4` before starting `forge web` or launching CLI
batches to request four simultaneous `metal-heavy` workers. Forge caps that
request by total unified memory (`FORGE_METAL_SLOT_RAM_GB`, default 24 GB per
slot) and runs the free-memory preflight after acquiring a slot. Keep
`quality`/q8 or explicit `--quantize 8`; fp16 (`--quantize 0`) is intentionally
manual because multiple fp16 FLUX-dev jobs can overrun unified memory and
throttle hard.

Madhubani set renders can request parallel pose workers directly:

```sh
python bin/forge_madhubani.py render tiger --all-poses --jobs 2
```

On a four-pose set, two jobs can cut ideal wall clock roughly in half when two
Metal slots fit in memory. The runtime still serializes or caps work if the
machine cannot safely hold it.

Common pattern:

```sh
# Scout
forge engine render wildlife-photo --subject "..." --profile cool

# Candidate
forge engine render wildlife-photo --subject "..." --profile balanced

# Final
forge engine render wildlife-photo --subject "..." --profile quality
```

## Canonical Model Home

Forge expects model-shaped files under `~/Models/`.

```text
~/Models/
|-- ollama/           # Ollama GGUF models
|-- huggingface/      # Hugging Face cache used by mflux, mlx_whisper, etc.
|-- flux-bfl/         # raw BFL-format FLUX checkpoints
`-- kokoro/           # Kokoro TTS model files
```

Adopt or inventory models:

```sh
bash ~/Desktop/Forge/bin/migrate-models.sh
bash ~/Desktop/Forge/bin/migrate-models.sh --yes

forge models scan --full
forge models adopt ~/Downloads/model.safetensors --as flux-bfl
forge models clean --dry-run
```

## Important Environment Variables

| Variable | Purpose |
| --- | --- |
| `FORGE_HOME` | Override repo root discovery |
| `FORGE_MODELS_HOME` | Override `~/Models` |
| `FORGE_HF_HOME` | Override Hugging Face cache path |
| `FORGE_STATE_HOME` | Override `~/.forge` state, jobs, locks, web runs |
| `FORGE_OLLAMA_URL` | Ollama endpoint, default `http://localhost:11434` |
| `FORGE_OLLAMA_MODEL` | Local LLM model, default `qwen3:8b` |
| `FORGE_TRANSLATE_MODEL` | Local translation model |
| `FORGE_TOKEN_USAGE` | `0` disables token usage logs |
| `FORGE_TTS_ENGINE` | `auto`, `kokoro`, or `say` |
| `FORGE_AUDIO_LANGS` | Default translation languages for voice/brief |
| `SARVAM_TTS_KEY` | Enables Sarvam cloud TTS for Indic languages |
| `FORGE_SARVAM_SPEAKER` | Default Sarvam speaker |
| `FORGE_SARVAM_SPEAKER_MR` | Marathi-specific Sarvam speaker override |
| `FORGE_SARVAM_MODEL` | Sarvam model, default `bulbul:v3` |
| `FORGE_FLUX_QUANTIZE` | mflux weight quantization, default `8`; use `0` for fp16 |
| `FORGE_METAL_SLOTS` | Requested concurrent heavy Metal workers; default `1`, capped by memory |
| `FORGE_FLUX_PARALLEL_JOBS` | Alias for `FORGE_METAL_SLOTS` focused on FLUX render batches |
| `FORGE_METAL_MAX_SLOTS` | Hard cap for `metal-heavy` slots after env request |
| `FORGE_METAL_SLOT_RAM_GB` | Memory budget per heavy Metal slot, default `24` |
| `FORGE_MADHUBANI_JOBS` | Default parallel pose workers for `bin/forge_madhubani.py render`; equivalent to `--jobs` |
| `FORGE_MFLUX_MIN_FREE_GB` | Free-memory guard before heavy FLUX renders |
| `FORGE_MLX_CACHE_LIMIT_GB` | MLX/HF cache cleanup target |
| `FORGE_ALLOW_CPU_ML` | Emergency override for Metal guard; unset by default so FLUX refuses CPU-only ML paths |
| `FORGE_ALLOW_TEMP_ARTIFACT_FALLBACK` | Explicit emergency opt-in to redirect unwritable artifact receipts to temp; default is fail loudly |
| `FORGE_CAPTION_LANGS` | Default caption languages for `process-video` |

## Documentation Map

Start here:

| Document | Use it when |
| --- | --- |
| [docs/INDEX.md](docs/INDEX.md) | You need the complete docs inventory |
| [SKILL.md](SKILL.md) | You need to choose the right Forge command/tool |
| [docs/FEATURES.md](docs/FEATURES.md) | You need current feature inventory and limits |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | You need system/data-flow diagrams |
| [docs/MECHANISMS.md](docs/MECHANISMS.md) | You need runtime mechanisms and quality contracts |
| [docs/MINIMALIST_TSHIRT_ENGINE.md](docs/MINIMALIST_TSHIRT_ENGINE.md) | You are rendering minimalist screen-printable T-shirt graphics |
| [docs/MINIMAL_ANIMAL_LINES.md](docs/MINIMAL_ANIMAL_LINES.md) | You are exploring exact <=8-line animal marks |

Critical handoffs and audits:

| Document | Use it when |
| --- | --- |
| [docs/FORGE_QUALITY_SPEED_AUDIT_2026-05-19.md](docs/FORGE_QUALITY_SPEED_AUDIT_2026-05-19.md) | You are checking the latest quality/speed audit and target math |
| [docs/BOOK_LOCALIZATION_AUDIT_HANDOFF.md](docs/BOOK_LOCALIZATION_AUDIT_HANDOFF.md) | You are building near-perfect Hindi/English/Marathi book subtitles and audio |
| [docs/PRESET_PRECISION_IMPROVEMENT_HANDOFF.md](docs/PRESET_PRECISION_IMPROVEMENT_HANDOFF.md) | You are improving preset precision by 40% or more |
| [docs/PRESET_PROMPT_TEMPLATE.md](docs/PRESET_PROMPT_TEMPLATE.md) | You are authoring semantic preset tokens and dependency vectors |
| [docs/WHATSAPP_JOKE_FACTORY_HANDOFF.md](docs/WHATSAPP_JOKE_FACTORY_HANDOFF.md) | You are building a safe WhatsApp joke factory for Indian audiences over 60 |
| [docs/AUDIOBOOK_API.md](docs/AUDIOBOOK_API.md) | You are changing audiobook public API or output contracts |
| [docs/AUDIOBOOK_HANDOFF.md](docs/AUDIOBOOK_HANDOFF.md) | You are refactoring audiobook quality end to end |
| [docs/COLORING_BOOK_SCIENCE.md](docs/COLORING_BOOK_SCIENCE.md) | You are tuning coloring-book/image prompt science |
| [AUDIT.md](AUDIT.md) | You are validating output correctness invariants |

Planning and execution:

| Document | Use it when |
| --- | --- |
| [PLAN.md](PLAN.md) | You need the practical future-work list |
| [PLAN_V2.md](PLAN_V2.md) | You need the local story-studio north star |
| [ALIGNMENT_PLAN.md](ALIGNMENT_PLAN.md) | You need the gap-to-vision execution plan |
| [BACKLOG.md](BACKLOG.md) | You need queued feature work |
| [docs/MASTERY_PLAN.md](docs/MASTERY_PLAN.md) | You need the mastery plan for images, thumbnails, audiobooks, coloring books, and mandalas |

Documentation maintenance:

| Document | Use it when |
| --- | --- |
| [docs/DOCUMENTATION_PROTOCOL.md](docs/DOCUMENTATION_PROTOCOL.md) | You are adding or changing a feature |
| [docs/FEATURE_TEMPLATE.md](docs/FEATURE_TEMPLATE.md) | You need the template for a new feature doc |
| [BRAND-LORA.md](BRAND-LORA.md) | You are training/installing a brand LoRA |
| [brand/loras/README.md](brand/loras/README.md) | You are installing LoRA files |
| [brand/references/README.md](brand/references/README.md) | You are managing brand/reference source images |

## Development And Verification

Docs-only changes usually need link review, not the full media stack. Runtime
changes should run at least:

```sh
python3 -m unittest tests.test_runtime
python3 -m py_compile bin/forge.py bin/forge_web.py bin/forge_runtime.py bin/mandala_engine.py bin/process-video.py bin/audiobook.py
```

Before declaring a media change done:

```sh
forge doctor --deep
forge status
forge models scan --full
```

For UI changes, run:

```sh
forge web --host 127.0.0.1 --port 5002
```

Then verify that the web form sends only options the backend actually consumes.
The current audit lens for this kind of mismatch is captured in the handoff docs
and should be updated whenever the UI changes.

## Known Sharp Edges

- Full book localization needs forced alignment, glossary enforcement,
  bilingual QA, coverage metrics, and subtitle timing gates before it can be
  called near-perfect.
- The web UI is powerful but easier to clutter than the CLI. Prefer fewer visible
  controls, sensible presets, progressive disclosure, and audited mapping from
  UI fields to backend settings.
- Native high-resolution FLUX can oversubscribe Metal memory. Prefer safe base
  renders plus external upscaling unless a workflow has been tested.
- Subtitles should default to SRT for video platforms unless a target workflow
  specifically requires VTT.
- Cloud TTS requires explicit credentials and should be documented as such in
  every workflow that depends on it.

## Documentation Rule

A feature is not done until the repo says what exists, what it outputs, what can
go wrong, how to verify it, and where future agents should continue. Update
[docs/INDEX.md](docs/INDEX.md) whenever you add a durable doc.
