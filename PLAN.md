# Forge — future work (no new model downloads)

> Inventory of what's possible with the models already installed on this Mac,
> ranked by impact × effort. Each item has a Definition of Done so we know
> when to stop.

## Inventory we're building on (no new downloads required)

**Ollama (11 models, 79 GB):**
qwen2.5-coder:32b, :14b, :7b · deepseek-coder-v2:16b · qwen3:8b · deepseek-r1:8b · llama3.1:8b · aya-expanse:8b · glm-4.7-flash · sarvam-translate-GGUF (Indic translation)

**MLX (HF cache, 77 GB):**
Qwen2.5-Coder-32B-Instruct-4bit · Qwen2.5-Coder-1.5B-Instruct-4bit · DeepSeek-R1-Distill-Qwen-32B-4bit · Qwen2.5-72B-Instruct-4bit (partial) · Qwen2.5-VL-7B-Instruct-4bit (partial) · BAAI/bge-m3 (embeddings) · FLUX.1-Kontext-dev (image editing, 24 GB) · meta-llama/Llama-3.1-8B (base)

**Audio:**
mlx-whisper Whisper-large-v3-turbo · Kokoro-TTS v1.0 (neural, default after `setup-voices --kokoro`) · macOS `say` (4 voices, fallback)

**Image:**
mflux FLUX.1-schnell + .1-dev · FLUX.1-Kontext-dev for editing

---

## Priority 1 — high-impact, fits the "factory" ethos

### P1.1 — Thumbnail editor mode (use FLUX.1-Kontext-dev we already have)
**Why:** 24 GB of FLUX.1-Kontext-dev is sitting unused. Kontext is the *editing* variant — it preserves a source image's composition while applying directed changes. Perfect for "swap the background in this thumbnail" or "make this photo look like the tartakovsky preset."
**Models:** FLUX.1-Kontext-dev + Qwen3:8b (to expand edit instructions into FLUX-ready prompts)
**New subcommand:** `forge edit --image existing.png --instruction "swap background to teal" --preset tartakovsky --out edited.png`
**Definition of Done:**
- `forge edit` accepts a source PNG + a natural-language edit instruction
- Uses Kontext-dev with proper init-image conditioning + denoising strength control
- Validates that output dimensions match input
- Has a `--strength` flag (0.3 light, 0.6 moderate, 0.9 aggressive)
- Round-trip preservation: identity edit (strength 0) returns near-identical image (PSNR ≥ 40 dB)

### P1.2 — Background music ducking in video pipeline
**Why:** Driving/paddling videos sound much better when background music auto-dips during voice. Today the pipeline does nothing with music.
**Models:** Whisper word timestamps (already producing them) + ffmpeg's `sidechaincompress` filter
**Where it goes:** new step in `process-video.py` between transcribe and burn-in
**Definition of Done:**
- Accepts `--music path/to/track.mp3` flag
- Music plays at full volume during silence, ducks to -18 dB during voice (timestamps from Whisper segments)
- Music fades in/out on video boundaries (1-sec fade)
- Final mixed audio length matches video length to the frame
- One A/B test against a manual ducking pass shows ≤ 2 dB level difference at any time

### P1.3 — Multi-language captions (English → Indic)
**Why:** You have sarvam-translate-GGUF in Ollama. Free local Marathi/Hindi captions for any English video.
**Models:** Whisper-large-v3-turbo (English transcript) + sarvam-translate (translation)
**New subcommand:** `process-video process video.mp4 --captions en,mr,hi`
**Definition of Done:**
- Pipeline produces `transcript/<stem>.<lang>.srt` for each language
- Translation done per-segment (preserves timing exactly)
- Manual spot-check on 5 segments: translation reads naturally to a native Marathi speaker
- Failed translations don't block English output (graceful per-segment fallback)
- Languages configurable via `LANGUAGES` env var for the watcher

### P1.4 — Vision agent on Desktop ("auto-organize my screenshots")
**Why:** Your Desktop has 195+ items. Qwen2.5-VL-7B (once download finishes) can look at each screenshot and decide what folder it belongs in. One-shot Desktop sanity.
**Models:** Qwen2.5-VL-7B-Instruct-4bit (vision-language) + Qwen3:8b (categorization rationale)
**New tool:** `forge organize ~/Desktop --dry-run` then `--apply`
**Definition of Done:**
- Walks Desktop, identifies images / PDFs / screenshots
- VLM extracts content summary (one line per file)
- LLM proposes a folder per file from a fixed taxonomy (Screenshots, Receipts, Reference, Trash candidates, Keep on Desktop)
- `--dry-run` writes a CSV proposal; `--apply` moves files with timestamped move-log
- Reversible: keeps a move-log JSON that supports `forge organize --undo <log>`

### P1.5 — Personal voice agent (push-to-talk)
**Why:** Whisper → Qwen → say is a full local Siri replacement. No cloud, no eavesdropping. Hold a hotkey, talk, get a spoken answer.
**Models:** Whisper-large-v3-turbo + Qwen3:8b (or 32B for harder questions) + macOS say
**New tool:** `forge talk` (foreground) or a menubar app (later)
**Definition of Done:**
- Records audio while Cmd+Option is held, transcribes on release
- Sends transcript to local LLM with conversation history (last 6 turns)
- Speaks the answer via `say` using the male_warm preset
- Round-trip latency < 5 sec for a 10-word question
- Conversation log saved to `~/.forge/conversations/<date>.jsonl`

---

## Priority 2 — high value, narrower use cases

### P2.1 — RAG over local docs (Kaayko + paddle-llm notes)
**Why:** Semantic search over your own writing. bge-m3 (already on disk) + a chat model.
**Models:** BAAI/bge-m3 (embeddings) + Qwen3:8b (synthesis)
**Definition of Done:**
- `forge index ~/Kaayko_v6/**/*.md` builds an embedding index in `~/.forge/rag/<corpus>/`
- `forge ask "<question>"` retrieves top-3 chunks, cites sources, refuses to answer when no relevant chunks
- Index update is incremental (only re-embed changed files)
- Citation links resolve back to file:line in the answer

### P2.2 — Code review on git diffs (replace external review tools)
**Why:** Qwen2.5-Coder-32B is competitive with paid Sonnet for review-quality criticism.
**Models:** Qwen2.5-Coder-32B-Instruct-4bit
**Definition of Done:**
- `forge review` (or git alias) runs against `git diff HEAD~1` by default
- Output: per-file comments with line refs, severity tags (bug/perf/style/nit)
- A "definitely real bug" run on a tagged-test commit catches ≥ 80 % of seeded bugs
- Latency < 60 sec for a 500-LOC diff on M5 Max

### P2.3 — Receipt/document OCR + structured extraction
**Why:** VLM can OCR + extract amount/vendor/date in one pass. Goodbye Photos search.
**Models:** Qwen2.5-VL-7B-Instruct-4bit
**Definition of Done:**
- `forge receipt scan ~/Pictures/receipts/` walks a folder
- Per-image JSON: `{vendor, amount, currency, date, line_items[], confidence}`
- Outputs a CSV summary suitable for spreadsheet import
- ≥ 90 % accuracy on amount + vendor on a hand-labeled set of 30 receipts

### P2.4 — Translate paddle-llm UI to multiple languages
**Why:** sarvam-translate already installed. Internationalize Kaayko's paddle-llm admin / paddlingout site cheaply.
**Models:** sarvam-translate (Indic) + Qwen3:8b (review)
**Definition of Done:**
- `forge i18n` reads a source language JSON, writes target language JSONs preserving keys
- ICU placeholders (`{count}`, `{name}`) untouched
- Generated translations reviewed (locally) for naturalness on 20 random strings

### P2.5 — Auto-B-roll cue detection from transcripts
**Why:** Pipeline already has word-timestamped transcripts. Identify "and here's the thing" / "watch this" type cues that should get a B-roll cut.
**Models:** Qwen3:8b
**Definition of Done:**
- New `process-video` step writes `broll-cues.json` with `{sec, text, suggested_clip_type}`
- Suggested types match a small taxonomy (motion / nature / detail / quote-card)
- Manual review on 10 videos: ≥ 70 % of cues are sensible places to cut

---

## Priority 3 — nice-to-have, no urgency

### P3.1 — Auto-chapter generation for videos > 5 min
**Why:** YouTube's chapter feature boosts retention. Easy from sentence-level transcripts.
**Models:** Qwen3:8b
**DoD:** writes `chapters.txt` in YouTube's `MM:SS — Title` format; chapters land on sentence boundaries; min 3 / max 8 chapters; ≥ 30 sec between chapters

### P3.2 — Brand-consistent waveform animation for audio-only videos
**Why:** Drop an `.mp3`, get an `.mp4` with a waveform-style visualizer in your preset's palette.
**Models:** ffmpeg `showwaves` filter + preset colors
**DoD:** `forge audio-to-video file.mp3 --preset tartakovsky --out file.mp4`; output is 1920×1080 30fps, waveform uses preset's accent color, background uses preset's dominant

### P3.3 — Personal email triage
**Why:** Local LLM + Mail.app's AppleScript = no cloud, no Outlook AI subscription
**Models:** Qwen3:8b
**DoD:** runs every 15 min via launchd; categorizes unread email into {urgent / FYI / promo / delete-candidate}; never sends, never deletes — only tags

### P3.4 — Newsletter post drafter
**Why:** Topic + voice preset → full draft in your voice
**Models:** Qwen2.5-72B-Instruct (once download finishes — better at long-form structure)
**DoD:** `forge draft --topic "..." --voice editorial --words 800 --out draft.md`; output passes a structure check (intro + 3-4 sections + closing); reads naturally; cites sources when given input docs via `--source` flag

### P3.5 — Photo library auto-tagging (Apple Photos)
**Why:** Apple Photos has poor search. VLM can do per-photo tags + caption.
**Models:** Qwen2.5-VL-7B
**DoD:** processes new photos as they're added; writes Apple Photos keywords via AppleScript bridge; reaches ≥ 80 % match with manually-applied keywords on a 50-photo eval set

---

## Recently landed (2026-05)

- ✅ **Kokoro-TTS wired** — `synthesize_voice` prefers Kokoro v1.0 when installed, falls back to `say`. `forge setup-voices --kokoro` downloads ONNX + voices, runs a smoke test, ~80 MB total. `FORGE_TTS_ENGINE` overrides selection.
- ✅ **Series consistency lock** — `series/<id>.json` pins `base_seed`, `style_anchor`, `world_sheet`, `character_sheet`, `locked_negatives`. Concepts can reference cast with `[name]` placeholders; engine expands them and emits a CAST section. Each frame in a series gets `seed = base_seed + frame_offset` for deterministic-but-distinct variation. New subcommand `forge series {new,list,show}`. `forge thumbnail` and `forge brief` accept `--series`.
- ✅ **LoRA support** — `flux_generate` accepts `--lora` / `--lora-scale` (repeatable). LoRA resolution: CLI > series > preset. Bare filenames resolve against `brand/loras/`. Training recipe in `BRAND-LORA.md`.
- ✅ **Draft mode + profiles** — `--draft` and `--profile {cool,balanced,max}` map to mflux model+steps+guidance+cooldown. Cooldown is a `time.sleep()` between consecutive heavy gens to let the SoC dissipate; override globally with `FORGE_FLUX_COOLDOWN_SEC`.
- ✅ **Cache cleaner** — `forge models clean [--dry-run] [--remove <repo>]` removes partial-download artifacts and orphaned blobs; can nuke whole model repos.

## Things explicitly NOT planned (and why)

- **Voice cloning of Rohan.** Requires a separate voice-cloning model (XTTS, RVC). Out of scope: "no new models."
- **Music generation.** Requires MusicGen or similar. Out of scope.
- **Real-time avatar / lip-sync.** Specialized models needed. Out of scope.
- **Training a custom LLM from scratch.** Hardware can do small fine-tunes; full pretraining is not a Forge concern.
- **Web scraping at scale.** Use Playwright separately if needed; not Forge's job.
- **Cloud anything.** Forge is local-only by charter.

---

## Choosing what to build next

Quick triage when you sit down to build:

1. **High impact, fits ethos:** P1.1 (thumbnail editor with Kontext) — biggest near-term value, uses a model you already paid 24 GB for.
2. **High pain, low effort:** P1.2 (music ducking) — one ffmpeg filter chain, eliminates manual mixing.
3. **High curiosity:** P1.4 (Desktop organizer) — visible impact on daily-life clutter you've already complained about.
4. **Long-term leverage:** P2.1 (RAG over your writing) — every other tool gets smarter once you can ask questions over your own corpus.

When stuck on priority: pick the one with the clearest Definition of Done.
