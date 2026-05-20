# Forge Roadmap

> Last updated: 2026-05-20

Forge is built in waves. Each wave ships standalone — earlier waves do not
require later waves to be useful. This roadmap distinguishes what is
**shipped**, what is **in progress**, what is **next**, and what is
**explicitly not in scope**.

If you want to contribute, the "Next" section is the place to start.
Open an issue first for anything in "In progress" so we don't collide.

---

## Shipped

(verifiable in tree)

### Engine + render pipeline
- 8 specialist FLUX engines, each with its own native canvas and recipe set — `forge engine list` ([style_engines.py](../bin/style_engines.py))
- Procedural mandala / folk-art / children's-book line-art lane (no diffusion) ([mandala_engine.py](../bin/mandala_engine.py))
- Beta minimal-animal renderer with `<=8` strokes, SVG-as-source-of-truth ([MINIMAL_ANIMAL_LINES](MINIMAL_ANIMAL_LINES.md))
- Multi-format input adapter — `.txt` / `.pdf` / `.rtf` / audio transcription
- Translation Studio with glossary enforcement, leakage detection, and repeated-line blockers
- Product mockup pipeline — 50 open-license SVG templates with per-asset attribution receipts
- RealESRGAN upscale chain (`2x`-`16x`) for print-grade output without oversubscribing Metal
- FLUX.2-klein-4b migration (M1-M4) plus flat-silhouette tuning (L1+L2+N1-rev2) that broke the photorealism lock for high-pull Madhubani species
- Kontext img2img wired into Madhubani renders with per-species `--style-reference` defaults

### Quality + trust layer
- 9-check Madhubani QC rubric: color floor, corners, centering, body fill, text leak, eye character, anatomy (informational), pattern density, decoration zone presence ([madhubani_qc.py](../bin/madhubani_qc.py))
- Shared blockers / `publishable: true|false` contract across engines ([engine_qc.py](../bin/engine_qc.py))
- Phase A schema enrichment — `required_decoration_zones`, `anatomical_count_constraints`, `decoration_density` in `animals.json`
- Phase B.1 — `pattern_density` verification primitive (Δ-E LAB measurement of decoration coverage vs body fill)
- Phase B.2 — `decoration_zone_presence` check (named zones examined against non-body-fill pixels)
- `forge doctor --deep` pre-flight covering Metal, mflux, Ollama, Whisper, model cache
- Free-memory guard before heavy FLUX renders + auto-clamp of Kontext renders to ≤1280×720
- Multi-seed batch P1 — single `mflux-generate --seed S1 S2 S3 S4` invocation, **−60.8%** wall-clock measured on 4-seed cool/schnell ([QUALITY_FINDINGS](QUALITY_FINDINGS_2026-05-20.md))

### Models + ops
- Canonical `~/Models/` layout with adopt/scan/clean ops (`forge models scan --full`, `forge models adopt`)
- 4 resource profiles (`cool` / `balanced` / `max` / `quality`) shared across CLI and web UI
- Parallel-Metal slot manager with per-slot memory budget (`FORGE_METAL_SLOTS`, `FORGE_METAL_SLOT_RAM_GB`)
- Web console with 6-area information architecture (Gallery / Create / Edit / Pipelines / Library / System)

### Cultural attribution
- 41-species Madhubani catalog across 21 national parks, 12 body types, per-body-type pose semantics ([MADHUBANI_ART_IDENTITY](MADHUBANI_ART_IDENTITY.md))
- 50-reference Mithila corpus from Wikimedia Commons with per-asset `attribution.json`
- Cultural-heritage statement — Madhubani-inspired, not authentic, with pointers to Mithila Art Institute ([CULTURAL_HERITAGE_ATTRIBUTION](CULTURAL_HERITAGE_ATTRIBUTION.md))
- Master bibliography of Sita Devi, Ganga Devi, Baua Devi, Mahasundari Devi influences ([MADHUBANI_BIBLIOGRAPHY](MADHUBANI_BIBLIOGRAPHY.md))

### OSS readiness
- [LICENSE](../LICENSE) (MIT for code)
- [NOTICE](../NOTICE) (model licenses + cultural attribution + cloud-TTS boundary)
- [CONTRIBUTING.md](../CONTRIBUTING.md)
- [CODE_OF_CONDUCT.md](../CODE_OF_CONDUCT.md)
- [SECURITY.md](../SECURITY.md)
- 128 tracked tests (1 skipped), fast local discovery, no heavy model downloads required

---

## In progress

- **LoRA pilot smoke run** — `mflux-train` against `z-image-turbo` with the 50-image Mithila corpus. Pipeline shipped: [`bin/forge_madhubani_lora.py`](../bin/forge_madhubani_lora.py) + [`LORA_TRAINING_RECIPE`](LORA_TRAINING_RECIPE.md). Smoke run completes in ~7 min at 512 px on M5 Max; checkpoint will land at `training/madhubani_lora/training/<ts>/checkpoints/lora_adapter.safetensors`. Full overnight recipe (~15 hrs) documented but not yet run.
- **Phase B.3 — anatomy_feature_count heuristics** — queued next in the Art Reasoning Engine sequence; spec done, no code yet.
- **HuggingFace publication of the LoRA checkpoint** — upload + model card with cultural attribution + before/after F1 measurement vs baseline auto-QC. Pending the full overnight training run.

---

## Next (open to contribution)

### Art Reasoning Engine (closed-loop verification)

Spec: [ART_REASONING_ENGINE](ART_REASONING_ENGINE.md).

- **B.3 — anatomy_feature_count heuristics** — Cobra renders still hallucinate two tongues; rhinos sometimes grow a second horn. Skeletonization + connected-component analysis on the subject mask, gated by `body_type`, to count tongues / horns / feet / eyes against `anatomical_count_constraints`. ETA ~4 hrs.
- **B.4 — wire new checks into `engine_qc.derive_blockers`** — Phase B.1/B.2/B.3 currently score but do not block promotion. Plumb each into the existing blockers / `publishable` contract so `promote_pose` refuses non-passing renders by default. ETA ~1 hr.
- **C.1 — multi-seed best-of-N selection** — Today `--seeds 4` renders 4 variants and the caller picks. Add `--pick-best N` that scores each via `madhubani_qc.score_madhubani_png()` and returns the highest-scoring variant with its score sidecar. ETA ~3 hrs.
- **C.2 — retry-with-targeted-boost loop** — New `bin/art_reasoning_engine.py` that on QC failure identifies the weakest dimension, assembles a per-dimension prompt boost (table in the spec), and retries up to `max_attempts`. ETA ~5 hrs.
- **D.1 — feedback memory schema** — `brand/madhubani/learning/runs.jsonl` writer + read API. One JSON line per render attempt: scores, prompt hash, weakest dimension, boost applied. ETA ~2 hrs.
- **D.2 — `forge madhubani learn` command** — Periodic job that mines `runs.jsonl` for prompt variants scoring highest per (species, pose, density) and outputs `species_winning_prompts.md`. ETA ~4 hrs.

### Catalog growth
- **`poses.json` v3 — per-body-type slot names** — "Seated peacock" is semantic nonsense even though v2 overrides the behavior. Restructure to `poses_by_body_type` so birds get `perched-resting / in-flight / tail-fanned-display / frontal-portrait` slugs natively. Keep aliases for backward compat. ETA ~3 hrs.
- **Per-species iconography expansion** — 41 species today; the long tail (e.g. flamingo, sloth bear, gharial) still inherits generic decoration zones. Author species-specific `required_decoration_zones` and `signature_features` for the remaining 20. ETA ~1 hr per 5 species.
- **National-park scene presets** — Beyond animal-on-blank, add park-context backgrounds (Sundarbans mangrove, Velavadar grassland, Kaziranga floodplain) as engine recipes. ETA ~2 hrs per park.

### Engines
- **Per-engine auto-QC** — Madhubani writes rich `.qc.json` sidecars; the other 7 engines emit nothing. Port the `engine_qc.py` rubric into each (`childrens-coloring-book`, `mandala-art`, `wildlife-photo`, etc.) with engine-appropriate checks. ETA ~3 hrs per engine.
- **`forge demo` instant-gratification command** — `forge demo madhubani-tiger` renders one canonical Madhubani tiger in ~25s and opens it. Same for `forge demo translate` and `forge demo audiobook`. ETA ~2 hrs.
- **Reproducible `forge bench` multi-seed harness** — Today's `forge bench` does runtime smoke checks but does not reproduce the headline `−60.8%` number. Author a dedicated harness so the README claim is one command away. ETA ~3 hrs.

### Translation
- **Full 10-page book localization** — `--spoken-words 150` is excerpt mode. Forced alignment, glossary enforcement, bilingual QA, coverage metrics, and subtitle-timing gates per [BOOK_LOCALIZATION_AUDIT_HANDOFF](BOOK_LOCALIZATION_AUDIT_HANDOFF.md). ETA ~2 days.

### Packaging + DX
- **One-command install** — `bash <(curl -fsSL ...)` that handles `pip install -e .`, model-cache check, and `forge doctor --deep` confirmation. Depends on the in-progress `pyproject.toml`. ETA ~3 hrs.
- **Mermaid architecture diagram inline in README** — Single diagram showing engine → dispatcher → mflux → QC trust layer → promote. ETA ~2 hrs.
- **LoRA training pilot (Madhubani)** — Corpus of ~50 references (pass_examples + `_legacy/v3` + Wikimedia `_general`), captioned with `(animal, pose, body_type)`. Rank 16, 1500-2000 steps against `flux2-klein-4b`. Cloud GPU or M5 Max overnight. ETA ~2 days for the pilot run + eval.

---

## Explicitly not in scope

- **Web SaaS / hosted Forge.** Forge is local-first by design. A hosted version would mean credential management, queueing, and per-user model isolation — those are different problems with different priorities. We will not build them here.
- **Windows or Linux support.** The performance profile assumes Apple Silicon unified memory and Metal. Porting to CUDA or Windows is out of scope; if you want a generic image-gen tool, ComfyUI is excellent.
- **Cloud-API integrations beyond Sarvam Bulbul.** Sarvam covers high-quality Hindi/Marathi TTS where local options fall short. We will not add OpenAI/Anthropic/Google API paths — the privacy posture is the point.
- **Re-licensing FLUX weights for commercial output.** FLUX models are under Black Forest Labs' non-commercial license. Commercial use of generated outputs requires the user to obtain their own commercial license from BFL. Forge does not redistribute weights and cannot re-license them.
- **Claim of authentic Madhubani painting.** Forge produces renders *inspired by* the Mithila tradition. Authentic Madhubani is hand-painted on handmade paper by trained artists. Buyers of Madhubani art should support practicing artists at the Mithila Art Institute and similar cooperatives, not substitute Forge output for the real thing.

---

## How decisions get made

The maintainer ([Rohan Ramekar](https://github.com/tommyvercetti76)) decides
direction. Cultural-heritage attribution and license calls are firm — those
are not open to PR. Everything else is open to contribution: open a GitHub
issue first to discuss approach, then submit a PR referencing the issue.
Substantial changes should land behind a `feature/` branch with tests and a
verification artifact before merging to `main`.
