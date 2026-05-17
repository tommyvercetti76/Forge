# Forge — local-AI factory

> English-driven production system. Drop a video, get an upload-ready bundle.
> Drop a topic, get a brand-consistent thumbnail + voiceover + script. All
> local, all offline-capable, no API keys.

## What's in here

```
Forge/
├── README.md                 ← you are here (how to use)
├── SKILL.md                  ← when/why to use each tool (mental model)
├── PLAN.md                   ← future work, definitions of done
├── BRAND-LORA.md             ← training recipe for a brand LoRA
├── docs/                     ← feature inventory, architecture, mechanisms, doc protocol
├── bin/                      ← CLI tools, runtime modules, and local engines
│   ├── forge.py              brand factory: thumbnails, voices, full briefs
│   ├── mandala_engine.py     procedural mandalas + symmetric children's pages
│   ├── process-video.py      video pipeline: transcribe + thumbs + overlays + burn-in
│   └── watch-folder.sh       auto-process every video dropped into a folder
├── brand/                    ← versioned design system (palettes, fonts, voices, loras)
│   ├── presets/
│   │   ├── tartakovsky.json  (cel animation, 4 colors)
│   │   ├── editorial.json    (magazine, refined)
│   │   ├── cinematic.json    (movie poster, dramatic)
│   │   └── documentary.json  (news/explainer, restrained)
│   ├── loras/                ← drop trained .safetensors here (see BRAND-LORA.md)
│   └── voices.json           4 voices (2 male, 2 female)
├── series/                   ← consistency-lock files (style/world/characters per batch)
│   └── example.json          fully-worked reference series
├── system/
│   └── com.kaayko.videoprep.plist  ← launchd agent for auto-watching
└── archive/                  ← earlier scripts kept for reference
    ├── prompt-forge.py
    ├── make-thumbnail.py
    └── transcribe-video.sh
```

## Install

```sh
# 1. Move the bundle to your home (or anywhere)
mv outputs/Forge ~/Desktop/Forge

# 2. Symlink the two CLIs for easy invocation
mkdir -p ~/.local/bin
ln -sf ~/Desktop/Forge/bin/forge.py         ~/.local/bin/forge
ln -sf ~/Desktop/Forge/bin/process-video.py ~/.local/bin/process-video
chmod +x ~/Desktop/Forge/bin/*.py ~/Desktop/Forge/bin/*.sh

# 3. Confirm prereqs installed (one-time, online)
forge list                          # smoke-test the brand factory
process-video warmup                # pre-cache Whisper + FLUX + verify Ollama
forge doctor --deep                 # verify canonical model paths + tools
```

## Quickstart recipes

Forge prints LLM token usage by default whenever it calls Ollama or an MLX
fallback. You should see lines like `tokens[forge.llm-json] prompt=...` during
LLM-backed commands. Set `FORGE_TOKEN_USAGE=0` only for quiet automation.

### 1. Render a single thumbnail

```sh
forge thumbnail \
  --preset tartakovsky \
  --concept "lone paddler at sunrise on alpine lake, cinematic, golden hour" \
  --headline "WHY I PADDLE ALONE" \
  --sub "what 200 lakes taught me" \
  --seed 1 \
  --out ~/Pictures/podcast-thumb.png
```

### 1b. Render exact procedural mandalas

These do not use FLUX. They are generated from polar geometry, repeated by exact
symmetry order, and written as both SVG and PNG with a QC JSON.

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
```

### 1c. Render symmetric children's drawing-book pages

This engine is also procedural: playful, elaborate, printable line art without
cartoon prompts, phantom artist names, or diffusion artifacts.

```sh
forge childrens-book \
  --theme all \
  --pages 3 \
  --symmetry 12 \
  --rings 7 \
  --complexity max \
  --width 2400 \
  --height 2400 \
  --out ~/Pictures/symmetric-childrens-book/
```

### 2. Synthesize a voiceover

```sh
# First time only — installs Kokoro-TTS (~80 MB) for neural-quality voices.
# Without this, Forge falls back to macOS `say` which sounds dated.
forge setup-voices --kokoro

forge voice \
  --preset male_warm \
  --text "Welcome back to the channel. Today we're talking about why I paddle alone." \
  --out ~/Sounds/intro.wav

# Localized sidecars: intro.mr.wav + intro.mr.txt, intro.hi.wav + intro.hi.txt
forge voice --preset male_warm --text "Welcome back." --translate mr,hi --out ~/Sounds/intro.wav
```

Engine selection is automatic: Kokoro when installed, `say` as fallback. Override
with `FORGE_TTS_ENGINE=kokoro|say|auto`.
Set `FORGE_AUDIO_LANGS=mr,hi` to translate every `forge voice` and `forge brief`
voiceover by default. Translation uses your local Ollama
`hf.co/mradermacher/sarvam-translate-GGUF:Q4_K_M` model.

### 3. Process a video end-to-end

```sh
# One-shot
process-video process ~/Videos/clip.mp4 --quality good --noisy

# Watch mode — drop videos into a folder, auto-process
bash ~/Desktop/Forge/bin/watch-folder.sh ~/Videos/videos-in ~/Videos/videos-out
```

### 4. Create a four-part mini episode from a book/script

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

Produces English, Hindi, and Marathi episode videos, timed SRT subtitle files
(currently estimated from target duration rather than forced-aligned), four
shot-directed stills per 15-second segment by default, stitched audiobook WAVs,
and a two-pass QC manifest. Each shot gets its own dialog, visual prompt, image,
subtitles, and QC record.
Translation uses local Sarvam:
`hf.co/mradermacher/sarvam-translate-GGUF:Q4_K_M`.

### 5. Create an audiobook from a book/script

```sh
forge audiobook \
  --book ~/Documents/book.txt \
  --voice male_warm \
  --translate hi,mr \
  --out ~/Music/book-audiobook/
```

Produces chunked narration, stitched `audiobook.en.wav`,
`audiobook.hi.wav`, `audiobook.mr.wav`, subtitles, scripts, and QC.

## The killer feature: `forge brief`

One command, full episode kit (titles + description + 3 thumbnails + voiceover intro), all written to one directory:

```sh
forge brief \
  --topic "I paddled solo across 200 lakes — here's what changed" \
  --preset tartakovsky \
  --voice male_warm \
  --out ~/Pictures/episode-05/
```

Produces:
```
episode-05/
├── metadata/
│   ├── title.txt              (3 options)
│   ├── description.md
│   ├── tags.txt
│   └── voiceover_intro.txt
├── thumbnails/
│   ├── thumb-1.png  thumb-2.png  thumb-3.png   ← A/B test
│   └── thumb-N-bg.png                          ← raw FLUX bgs
├── voiceover-intro.wav
└── brief.json                                  ← what the LLM produced
```

## Canonical model home — never re-download what you already have

Every model file Forge or its pipelines need lives under **`~/Models/`**. Single canonical home, four subdirs:

```
~/Models/
├── ollama/           Ollama GGUF models (managed by Ollama itself)
├── huggingface/      HuggingFace cache — mflux, mlx_whisper, etc. look here
├── flux-bfl/         Raw BFL-format FLUX checkpoints (manual downloads)
└── kokoro/           Kokoro-TTS models when upgraded from `say`
```

This means: **download a model file once, drop it into the right subdir, and every tool finds it.** No more "is it in Downloads? is it in some HF cache I don't know about? do I need to re-download?"

### Migrate your existing downloads in one command

```sh
bash ~/Desktop/Forge/bin/migrate-models.sh         # interactive prompts
bash ~/Desktop/Forge/bin/migrate-models.sh --yes   # no prompts
```

This moves anything Forge recognizes (FLUX safetensors, Kokoro models) from `~/Downloads/` into the right subdir under `~/Models/`. Idempotent — safe to re-run anytime.

### Inventory what's installed

```sh
forge models scan
forge doctor --deep
forge status
```

Shows: total disk used, what's in each subdir, what FLUX/MLX/Ollama models are cached, and **stragglers** (model-shaped files lying outside `~/Models/`). Run this before any new download.

### Adopt a single file by path

```sh
forge models adopt ~/Downloads/some-checkpoint.safetensors --as flux-bfl
forge models adopt ~/Downloads/kokoro-v1.0.onnx --as kokoro
```

Moves the file into `~/Models/<subdir>/`. If the destination already exists with the same size, the source is removed.

### About BFL vs HF diffusers format (read once, save hours later)

You may have downloaded FLUX checkpoints in **two different shapes**:

| Format | Looks like | Used by |
|---|---|---|
| BFL native | `flux1-schnell.safetensors` (one 23 GB file) + `ae.safetensors` | ComfyUI, official FLUX reference impl |
| HF diffusers | `transformer/diffusion_pytorch_model-NNNNN-of-NNNNN.safetensors` (sharded) + `vae/`, `text_encoder/`, etc. | mflux, diffusers library |

**They contain the same weights but are not directly interchangeable.** Forge stores both:
- `~/Models/flux-bfl/` for BFL files
- `~/Models/huggingface/hub/models--black-forest-labs--FLUX.1-*/` for diffusers (HF auto-manages)

If you have a BFL file and want mflux to use it, the HF cache still needs to be populated separately (`hf download black-forest-labs/FLUX.1-schnell` — resumable). The BFL file in `flux-bfl/` is your reserve copy + the one you'd point a BFL-native tool at.

## Consistency across a batch — the `series` concept

A *preset* locks the look (palette, type, style fingerprint). A *series* locks
the *world*: a base seed, a one-sentence style anchor repeated in every prompt,
a character sheet, a world sheet, and locked negatives. Together: every frame
of a batch reads as one production.

```sh
# 1. Scaffold a series
forge series new harbor-tales --preset tartakovsky

# 2. Edit series/harbor-tales.json — fill style_anchor, world_sheet, character_sheet
#    (Use placeholders like [keeper] in concepts; they expand to the locked description.)
#    See series/example.json for a fully-worked reference.

# 3. Use it
forge brief --topic "the lighthouse keeper's daily ritual" \
  --preset tartakovsky --voice male_warm --series harbor-tales

forge thumbnail --preset tartakovsky --series harbor-tales \
  --concept "wide shot of [keeper] at the harbor wall, salt fog" \
  --headline "DAWN WATCH" --frame-offset 4 --out ~/Pictures/dawn-watch.png

forge series list                # see all series
forge series show harbor-tales   # full dump
```

Each thumbnail in a series gets `seed = base_seed + frame_offset`, so frames
within a series are deterministic and reproducible. Negatives from the series
stack on top of the preset's negatives.

For maximum lock-in — train a brand LoRA. Recipe in [BRAND-LORA.md](BRAND-LORA.md).

## Resource profiles — draft vs. final

Three named profiles match `forge bench`:

| Profile | Model | Steps | Cooldown | Use for |
|---|---|---|---|---|
| `cool` | schnell | 4 | 20s | Drafts, A/B tests, ideation. Cool & fast. |
| `balanced` | dev | 18 | 5s | Default for production runs. |
| `max` | dev | 25 | 0s | Final approved frame. Hottest run. |

```sh
forge thumbnail --preset cinematic --concept "..." --headline "..." --draft
# or equivalently:
forge thumbnail --preset cinematic ... --profile cool
forge thumbnail --preset cinematic ... --profile max --out final.png
forge brief --topic "..." --preset X --voice Y --draft   # whole brief in draft mode
```

Override cooldown with `FORGE_FLUX_COOLDOWN_SEC=10`. Useful on a hot chassis
where you want the SoC to dissipate between consecutive gens.

## Reclaim disk — model cache cleanup

```sh
forge models clean --dry-run               # preview reclaimable (partial+orphan blobs)
forge models clean                         # remove them (prompts before)
forge models clean --remove black-forest-labs/FLUX.1-schnell --yes
```

Cleans `.lock` / `.incomplete` artifacts and orphaned blobs (HF cache often
keeps duplicates after a resumed download). `--remove` deletes a whole repo.

## Adding a new look (5 minutes, no code)

```sh
cp ~/Desktop/Forge/brand/presets/tartakovsky.json ~/Desktop/Forge/brand/presets/zine.json
# Edit: change id, name, palette hex codes, fonts, FLUX prompt prefix
forge list                              # → now shows your new preset
forge thumbnail --preset zine ...       # use it
```

Every preset is a single JSON file. Drop one in, it's selectable everywhere.

## Auto-start on login (optional)

The video watcher can run as a background launchd agent:

```sh
# Edit ~/Desktop/Forge/system/com.kaayko.videoprep.plist if your video-in/out dirs are different
cp ~/Desktop/Forge/system/com.kaayko.videoprep.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.kaayko.videoprep.plist
launchctl kickstart gui/$UID/com.kaayko.videoprep

# Tail what it's doing
tail -f ~/Library/Logs/kaayko-videoprep.log

# Stop later
launchctl bootout gui/$UID/com.kaayko.videoprep
```

## Prerequisites (verified by `process-video warmup`)

| Tool | What for | Install |
|---|---|---|
| `ffmpeg` | audio/video processing | `curl -L https://evermeet.cx/ffmpeg/getrelease/zip -o /tmp/f.zip && unzip /tmp/f.zip -d ~/.local/bin/` |
| `mlx_whisper` | local transcription | `uv tool install --with mlx-whisper mlx-whisper` |
| `mflux-generate` | local image gen (FLUX) | `uv tool install --with mflux mflux` |
| `Pillow` | text overlay rendering | `pip install pillow --break-system-packages` |
| Ollama + qwen3:8b | local LLM for `brief`/analyze | `open -a Ollama && ollama pull qwen3:8b` |
| Kokoro-TTS (recommended) | neural TTS, replaces `say` for real production audio | `forge setup-voices --kokoro` |
| (fallback) macOS `say` | works zero-install but sounds dated | built-in |

`process-video warmup` checks every one of these, downloads models, and writes a ready marker. **Run it once while online before going off-grid.** Then everything works offline.

## Where to look when lost

| Question | Document |
|---|---|
| "How do I do X?" | this file (README) |
| "What features exist and how do they work?" | [docs/FEATURES.md](docs/FEATURES.md) |
| "How does Forge fit together?" | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| "What mechanisms does Forge use?" | [docs/MECHANISMS.md](docs/MECHANISMS.md) |
| "How should new features be documented?" | [docs/DOCUMENTATION_PROTOCOL.md](docs/DOCUMENTATION_PROTOCOL.md) |
| "Which tool is for what? Why does it work this way?" | [SKILL.md](SKILL.md) |
| "What could I build next with the models I already have?" | [PLAN.md](PLAN.md) |
| "What does this preset look like inside?" | `forge show <preset>` |
| "What are all the presets/voices?" | `forge list` |
| "Why did the pipeline fail on this video?" | `~/Videos/videos-out/<video>/pipeline.log` (JSONL) |

## Common operations cheatsheet

```sh
# Brand
forge list                           # see all presets + voices
forge show tartakovsky               # full spec dump
forge mandala --style floral --symmetry 24 --rings 9 --complexity max --out ~/Pictures/mandala.png
forge childrens-book --theme all --pages 3 --complexity max --out ~/Pictures/symmetric-childrens-book/
forge thumbnail --preset X --concept "..." --headline "..." --out ...
forge thumbnail --preset X ... --draft                        # schnell @ 4 steps (cool/fast)
forge thumbnail --preset X ... --profile max                  # dev @ 25 steps (final)
forge thumbnail --preset X --series harbor-tales ...          # locked style/world/cast
forge thumbnail --preset X --lora kaayko_style.safetensors --lora-scale 0.8 ...
forge voice --preset male_warm --text "..." --out ...
forge audiobook --book book.txt --translate hi,mr --out DIR/
forge episode --book excerpt.txt --segments 4 --seconds 15 --translate hi,mr --out DIR/
forge setup-voices --kokoro          # one-time, ~80 MB, makes audio not sound like 2000s
forge brief --topic "..." --preset X --voice Y --series Z --out DIR/
forge series new <id>                # scaffold a consistency-lock file
forge series list / show <id>
forge doctor --deep                  # inspect model/tool/runtime health
forge bench                          # write conservative local quality profiles
forge status                         # recent jobs + resource locks
forge models scan --full             # inventory all cached models
forge models clean --dry-run         # preview reclaimable disk
forge models clean --remove org/repo --yes   # nuke a model

# Video
process-video warmup                 # one-time, online
process-video process video.mp4      # process one
process-video process video.mp4 --quality cool      # lower heat / faster
process-video process video.mp4 --quality max       # highest local quality
process-video process video.mp4 --captions en,mr,hi # English + translated caption files
process-video process video.mp4 --noisy --quality best   # outdoor/wind
process-video process video.mp4 --force                  # redo cached steps
bash ~/Desktop/Forge/bin/watch-folder.sh IN OUT                  # auto-watch

# Inspection
cat ~/.kaayko-pipeline/ready.json    # last warmup status
cat ~/Videos/videos-out/<vid>/prep-manifest.json
tail -f ~/Library/Logs/kaayko-videoprep.log
```

## What's deliberately not here

- **No cloud API calls.** Everything runs on your hardware.
- **Metal is doing real work.** `mflux` runs through MLX/Metal locally; lower `--steps` (or `process-video --quality fast`) when you want less sustained GPU heat.
- **One canonical model cache.** Forge sets `HF_HOME=~/Models/huggingface` for child tools so `mflux`, `mlx_whisper`, and warmup agree.
- **Runtime state is tracked.** Jobs and resource locks live under `~/.forge/`; use `forge status` when a background run looks stuck.
- **No model downloads at runtime.** `warmup` pre-fetches; field runs refuse to fetch.
- **No editor required.** All assets generated; you pick from variants.
- **No brand drift.** Every output goes through a preset; presets are versioned JSON.

For *why* each piece exists the way it does, read [SKILL.md](SKILL.md). For *what comes next*, read [PLAN.md](PLAN.md).
