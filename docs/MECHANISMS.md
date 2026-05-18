# Forge Mechanisms

Created: 2026-05-17

This document explains the implementation mechanisms Forge uses across features.

## Canonical Model Cache

Forge centralizes model files under `~/Models`:

- `~/Models/ollama`
- `~/Models/huggingface`
- `~/Models/flux-bfl`
- `~/Models/kokoro`

`forge_runtime.child_env()` sets `MODELS_HOME`, `HF_HOME`, `HF_HUB_CACHE`, and
`PATH` for child tools so FLUX, Whisper, and local LLM calls agree on cache
locations.

## Atomic Writes

Generated files are written to temporary siblings first and moved into place
with `os.replace()`. This keeps crashes from leaving half-written final outputs.

Used by:

- JSON/text helpers in `forge_runtime.py`.
- Media outputs in `forge.py`.
- Video pipeline outputs in `process-video.py`.
- Procedural SVG/PNG/QC artifacts in `mandala_engine.py`.

## Validation

Forge validates generated artifacts before reporting success:

- `validate_png()`
- `validate_audio()`
- `validate_video()`
- ffprobe-backed stream and duration checks.

Known direction: episode QC needs blocker aggregation so validation failures and
publishability warnings produce `qc/blockers.json`.

## Resource Locks

`ResourceLock` coordinates expensive local resources:

- `metal-heavy`: FLUX and Whisper/MLX-heavy stages.
- `llm`: Ollama/Sarvam local LLM calls.
- `tts`: Kokoro/macOS voice generation.

Locks are advisory and cross-process. `forge status` reads lock files, but stale
lock file labeling should be improved.

## Job Store

`JobStore` stores job metadata in SQLite under `~/.forge/jobs.sqlite`. It is used
by `process-video` and surfaced by `forge status`.

## Local LLM JSON Contract

LLM-dependent flows ask for structured JSON. The implementation extracts JSON,
validates expected shapes, retries, and falls back to deterministic templates
when a response cannot be trusted.

Used by:

- `forge brief`
- `forge episode`
- `process-video` analysis
- Shot planning and timing repair loops

## Token Usage Telemetry

Forge prints token usage for every local LLM call by default. Ollama responses
provide exact `prompt_eval_count` and `eval_count` values, which Forge reports as
prompt, completion, and total tokens. Backends that do not expose token counts
use a clearly labeled estimate.

Implemented by:

- `print_ollama_token_usage()` and `print_token_usage()` in `forge_runtime.py`.
- Main Forge JSON calls in `forge.py`.
- Sarvam/Ollama translation calls in `forge_runtime.py`.
- `process-video.py` Ollama and MLX fallback calls.
- `audiobook.py` thumbnail-brief calls.

The default is intentionally noisy because token usage is part of quality and
cost awareness. Set `FORGE_TOKEN_USAGE=0` for rare quiet runs.

## Translation

Translation uses local Sarvam through Ollama:

```text
hf.co/mradermacher/sarvam-translate-GGUF:Q4_K_M
```

Episode and audiobook flows use two translation passes and back-translation QC
for Hindi/Marathi outputs. Translation quality is recorded, but not yet enforced
as a hard publishability gate.

## TTS Routing

English voice generation prefers Kokoro when installed:

```text
FORGE_TTS_ENGINE=auto|kokoro|say
```

Hindi/Marathi routing uses macOS `say` voice defaults in the `forge.py`
episode/audiobook wrapper. Marathi fallback risk is recorded in QC and should
become a blocker until a native route or manual approval exists.

## FLUX Generation

FLUX generation is used for:

- Thumbnails.
- Brief thumbnail variants.
- Episode visuals.
- Image editing.
- Specialist engine renders.

Profiles:

- `cool`: schnell, 4 steps.
- `balanced`: dev, 18 steps.
- `max`: dev, 25 steps.

## Specialist Style Engines

`style_engines.py` turns small domain-specific configs into dense FLUX
directives. These engines are still diffusion-based, but they improve control by
encoding vocabulary, invariants, and negative prompts.

## Procedural Geometry

`mandala_engine.py` is deliberately not diffusion-based. It constructs exact
vector geometry and emits SVG first. PNG is a rasterized derivative.

Used by:

- `forge mandala`
- `forge childrens-book`

This is the correct mechanism when symmetry must be mathematical.

Mandala styles use distinct geometry grammars:

- `coloring`: bold fillable rosettes and closed page-friendly cells.
- `floral`: lotus rosettes, petal rings, and leaf borders.
- `geometric`: polygon lattices, radial lines, diamonds, and angular borders.
- `sacred`: yantra-like triangles, nested circles, lotus rings, and square/circle
  scaffolds.
- `playful`: bubbles, stars, scallops, and lighter child-friendly spacing.
- `luxury`: dark-ground gold filigree, jewel dots, fine arcs, and delicate
  concentric polygons.

Each output QC records `style_grammar.motif_families` so style collapse is
detectable in tests and review.

For mathematical strictness, repeated mandala motifs are now generated as
canonical templates and copied by SVG `rotate(angle cx cy)` groups. This follows
the fundamental-region pattern used in computational geometric ornament work:
define the motif once, then apply the symmetry operation. The PNG remains a
raster derivative, so SVG is the authoritative mathematical artifact.

## ffmpeg Assembly

ffmpeg handles:

- Audio extraction.
- Audio format conversion.
- Subtitle burn-in.
- Overlay composition.
- Video concat.
- Audio concat.
- Image+audio MP4 muxing.

The pipeline favors explicit codecs and stream validation over ffmpeg defaults.

## Structured Logs And Receipts

Forge's receipt pattern:

- `brief.json`
- `episode-manifest.json`
- `episode-qc.json`
- `audiobook-manifest.json`
- `audiobook-qc.json`
- `prep-manifest.json`
- `pipeline.log`
- Procedural `.qc.json`
- Engine directive sidecars

The strategic goal is one review surface and explicit blocker files for
publishability decisions.
