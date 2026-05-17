# Forge Architecture

Created: 2026-05-17

This document describes how Forge is built today. It separates the implemented
system from future work.

## System Overview

```mermaid
flowchart TB
  CLI["forge.py CLI"] --> Core["Shared runtime helpers"]
  PV["process-video.py CLI"] --> Core
  Watch["watch-folder.sh"] --> PV

  CLI --> Media["Media generation"]
  CLI --> Style["Specialist FLUX engines"]
  CLI --> Proc["Procedural geometry engines"]
  CLI --> Ops["Operations"]

  Media --> LLM["Ollama qwen3:8b"]
  Media --> Translate["Ollama Sarvam translate"]
  Media --> TTS["Kokoro / macOS say"]
  Media --> FLUX["mflux / FLUX"]
  Media --> FFMPEG["ffmpeg / ffprobe"]

  Style --> FLUX
  Proc --> SVG["SVG construction"]
  Proc --> Pillow["Pillow rasterization"]
  PV --> Whisper["mlx_whisper"]
  PV --> LLM
  PV --> Translate
  PV --> FLUX
  PV --> FFMPEG

  Core --> Models["~/Models"]
  Core --> State["~/.forge"]
  Core --> Pipeline["~/.kaayko-pipeline"]
```

## Command Surface

```mermaid
flowchart LR
  F["forge"] --> Browse["list / show"]
  F --> Make["thumbnail / brief / voice / video / episode / audiobook"]
  F --> Engines["engine"]
  F --> Procedural["mandala / childrens-book"]
  F --> Configure["series / setup-voices / models"]
  F --> Health["doctor / status / bench / wizard"]

  Engines --> E1["list"]
  Engines --> E2["describe"]
  Engines --> E3["recipes"]
  Engines --> E4["render"]

  Procedural --> M["Exact radial mandalas"]
  Procedural --> C["Symmetric children's pages"]
```

## Episode Pipeline

```mermaid
flowchart TD
  A["Book or text"] --> B["Clean + digest source"]
  B --> C["LLM episode plan"]
  C --> D["Segment script fitting"]
  D --> E["Shot planner"]
  E --> F["Per-shot English dialog"]
  F --> G["TTS"]
  G --> H["Audio fit to target seconds"]
  H --> I["Visual prompt contract"]
  I --> J{"--no-flux?"}
  J -->|yes| K["Title-card visual"]
  J -->|no| L["FLUX visual"]
  K --> M["Thumbnail overlay"]
  L --> M
  M --> N["Estimated SRT"]
  N --> O["Shot MP4"]
  O --> P["Segment MP4"]
  P --> Q["Final language MP4"]
  F --> R["Sarvam translation + back-translation QC"]
  R --> G
  Q --> S["Manifest + episode QC"]
```

Current limitation: subtitle timing in `forge episode` is estimated, not yet
forced-aligned from final generated audio.

## Process Video Pipeline

```mermaid
flowchart TD
  A["Input video"] --> B["ffprobe integrity check"]
  B --> C["Extract audio"]
  C --> D["mlx_whisper transcript"]
  D --> E["Caption translation"]
  D --> F["LLM metadata analysis"]
  F --> G["Hook / moment / CTA overlays"]
  F --> H["Thumbnail concepts"]
  H --> I["FLUX thumbnails"]
  G --> J["Burn-in captions and overlays"]
  E --> J
  J --> K["upload-ready.mp4"]
  K --> L["prep-manifest.json + pipeline.log"]
```

## Specialist FLUX Engine Flow

```mermaid
flowchart TD
  A["Small user subject + knobs"] --> B["Typed engine config"]
  B --> C["Invariant validation"]
  C --> D["Directive expansion"]
  D --> E["Synthetic preset"]
  E --> F["FLUX generation"]
  F --> G{"--seeds > 1?"}
  G -->|yes| H["Gallery + contact sheet"]
  G -->|no| I["PNG output"]
  H --> J["Directive JSON sidecars"]
  I --> J
```

## Procedural Geometry Flow

```mermaid
flowchart TD
  A["Symmetry/ring/style config"] --> B["Validate numeric bounds"]
  B --> C["Build polar geometry"]
  C --> D["Repeat motifs by exact order"]
  D --> E["Write SVG"]
  E --> F["Rasterize PNG via Pillow"]
  F --> G["Write QC JSON"]
```

Procedural engines are the right path when symmetry must be mathematical. FLUX
is not used in this path.

## Local State And Model Layout

```mermaid
flowchart TB
  Home["User home"] --> Models["~/Models"]
  Home --> ForgeState["~/.forge"]
  Home --> Pipeline["~/.kaayko-pipeline"]

  Models --> Ollama["ollama/"]
  Models --> HF["huggingface/"]
  Models --> BFL["flux-bfl/"]
  Models --> Kokoro["kokoro/"]

  ForgeState --> Jobs["jobs.sqlite"]
  ForgeState --> Locks["locks/*.lock"]
  Pipeline --> Ready["ready.json"]
```

## Artifact Philosophy

Forge should leave receipts:

- Inputs and settings are captured in manifests.
- Expensive/generated outputs are written atomically.
- QC JSON files explain what was checked.
- Long-running/background jobs write structured logs.
- Future publishability work should make blockers explicit instead of burying
  them in free-form notes.
