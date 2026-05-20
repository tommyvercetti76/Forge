# WhatsApp Joke Factory - Agent Blueprint

Created: 2026-05-18

## Goal

Build a Forge workflow that produces share-ready WhatsApp joke packs for Indian
audiences over 60.

The factory must create gentle, repeatable, culturally familiar humor that works
inside family groups, senior circles, morning-walk groups, alumni groups, and
regional language WhatsApp forwards. It must never become spam automation,
political propaganda, hate content, scammy "forward this" material, or humor that
punches down at old age, disability, illness, caste, religion, gender, region, or
class.

## What The Factory Produces

One run should produce a complete pack:

- Text jokes ready to paste into WhatsApp.
- Square image cards with large readable text.
- Optional voice-note audio in English, Hindi, and Marathi.
- Optional short MP4s made from a joke card plus voiceover.
- A manifest that records every prompt, output path, score, safety decision, and
  language variant.
- A QC report that says which jokes are approved, which were rewritten, and which
  were rejected.

Default daily pack:

| Asset | Count | Format |
| --- | ---: | --- |
| Text jokes | 12 | `.txt` plus manifest JSON |
| Image cards | 4 | 1080x1080 PNG |
| Voice notes | 2 | WAV or M4A |
| Short videos | 2 | MP4, 15-30 seconds target |
| Review sheet | 1 | Markdown or HTML |
| Run manifest | 1 | JSON |
| QC report | 1 | JSON |

## Non-Goals

- Do not automate sending messages to WhatsApp contacts.
- Do not scrape WhatsApp groups.
- Do not build a bulk spam sender.
- Do not generate political persuasion, party attacks, communal jokes, caste
  jokes, sexist in-law jokes, medical misinformation, miracle cures, investment
  advice, religious claims, or "forward to 10 people" content.
- Do not depend on new model downloads for V1.

## Existing Forge Substrate

Use what already exists before adding anything new.

| Need | Existing capability |
| --- | --- |
| Local structured generation | `bin/forge.py::call_llm` and Ollama JSON mode |
| Translation | `bin/forge_runtime.py::translate_texts_ollama` |
| Hindi/Marathi TTS | Sarvam path through `SARVAM_TTS_KEY` and `tts_sarvam` |
| English TTS | `forge voice`, Kokoro when installed, macOS `say` fallback |
| Devanagari font safety | `bin/forge.py::font_for_text` and related helpers |
| Image/card rendering patterns | `bin/forge.py::render_thumbnail`, PIL, brand presets |
| Video mux | `forge video` or the existing ffmpeg patterns in `bin/forge.py` |
| Atomic JSON writes | `bin/forge_runtime.py::write_json` |
| Runtime state | `bin/forge_runtime.py::JobStore`, `FORGE_STATE_HOME` |
| Model/cache sanity | `forge doctor --deep`, `forge status`, `forge models scan` |
| Web UI pattern | `bin/forge_web.py` action specs and command builder |

Important implementation choice:

For V1, do not use FLUX for every joke card. Render cards with PIL templates and
large text. Use FLUX only for optional themed backgrounds after the text pipeline
is stable. This keeps the factory fast, deterministic, cheap, and less likely to
produce unreadable text.

## Audience Contract

The target audience is Indian adults over 60 who share content in private
WhatsApp groups. The humor should feel warm, familiar, clean, and quick.

### Voice

- Gentle, affectionate, and dignified.
- Observational rather than insulting.
- Family-safe.
- Easy to understand in one read.
- Uses simple language, not internet slang-heavy youth humor.
- Punchline should land within 1-3 lines for text jokes and within 8-20 seconds
  for audio/video jokes.

### Best Humor Lanes

Use these lanes first:

- Morning walk group banter.
- Chai, snacks, dabba, and kitchen timing.
- WhatsApp group habits: good morning messages, missed calls, voice notes,
  family group confusion, emoji overuse.
- Grandparent wisdom beating modern technology.
- Retirement schedule being busier than office life.
- Doctor's simple advice misunderstood in a harmless way.
- Spectacles, remote controls, charger hunting, OTP confusion.
- TV serial suspense, cricket commentary, train journeys, bank queues.
- Festival preparation, guests, sweets, and family logistics.
- English/Hindi/Marathi code-switching that sounds natural.
- Nostalgia: radio, landline, postcards, old cinema, school reunions.

### Risky Humor Lanes

These are allowed only if extremely gentle:

- Health and doctor jokes: no disease, death, hospitalization, dementia, stroke,
  disability, medicine non-compliance, or medical advice.
- In-law jokes: avoid misogyny and cruelty. Prefer mutual family chaos.
- Money jokes: avoid scams, debt shame, poverty jokes, pension misinformation, or
  investment advice.
- Religious/festival jokes: use food/family/logistics, not theology or mockery.
- Regional jokes: only self-contained local flavor, never stereotypes.

### Hard Rejects

Reject or rewrite any joke that includes:

- Caste, religion, communal identity, or political party targeting.
- Gender humiliation, body shaming, widow/widower jokes, infertility, or dowry.
- Disability, dementia, memory loss, serious illness, hospital suffering, death,
  or medication jokes.
- Ageist framing where seniors are stupid, useless, slow, senile, or a burden.
- Sexual content, double meaning, vulgarity, alcohol/drug humor.
- Fake news, miracles, medical cures, investment tips, "share this to get luck",
  or anything that resembles misinformation.
- Mocking accents, regions, languages, class, domestic workers, rural people, or
  education level.
- Real public figures or party-coded jokes.

## Product Modes

### 1. Daily Clean Jokes

Default. Twelve text jokes, four cards, two voice/video assets. Good for family
groups.

### 2. Morning Pack

Short, optimistic, chai/walk/WhatsApp group jokes. Must not become generic "Good
Morning" spam.

### 3. Festival Pack

Festival-specific but non-religious in the joke target. Laugh at sweets, guests,
shopping lists, lights, cleaning, travel, and family coordination.

### 4. Regional Pack

Language-first pack for Hindi, Marathi, Gujarati, Tamil, etc. V1 must support
English, Hindi, and Marathi because Forge already has those paths.

### 5. Voice Note Pack

Audio-first jokes with expressive narrator timing. Best for users who forward
audio clips rather than reading cards.

## Output Layout

Every run writes a self-contained folder:

```text
whatsapp-jokes-YYYYMMDD-HHMMSS/
|-- manifest.json
|-- qc-report.json
|-- review.md
|-- prompts/
|   |-- generator.system.txt
|   |-- generator.user.txt
|   |-- critic.system.txt
|   `-- critic.user.txt
|-- text/
|   |-- en/
|   |-- hi/
|   `-- mr/
|-- cards/
|   |-- en/
|   |-- hi/
|   `-- mr/
|-- audio/
|   |-- en/
|   |-- hi/
|   `-- mr/
`-- video/
    |-- en/
    |-- hi/
    `-- mr/
```

All filenames must be deterministic:

```text
joke-001.en.txt
joke-001.hi.txt
joke-001.mr.txt
joke-001.en.png
joke-001.hi.wav
joke-001.hi.mp4
```

## Manifest Contract

The manifest must be JSON and stable enough for future tools to read.

```json
{
  "schema_version": "whatsapp_joke_pack.v1",
  "created_at": "2026-05-18T00:00:00Z",
  "factory_version": "v1",
  "audience": "indian_over_60",
  "mode": "daily",
  "languages": ["en", "hi", "mr"],
  "counts": {
    "text": 12,
    "cards": 4,
    "audio": 2,
    "video": 2
  },
  "jokes": [
    {
      "id": "joke-001",
      "topic": "morning walk",
      "humor_lane": "daily_life",
      "risk_level": "low",
      "status": "approved",
      "source_language": "en",
      "texts": {
        "en": {
          "setup": "string",
          "punchline": "string",
          "card_text": "string",
          "voice_script": "string"
        },
        "hi": {
          "setup": "string",
          "punchline": "string",
          "card_text": "string",
          "voice_script": "string"
        },
        "mr": {
          "setup": "string",
          "punchline": "string",
          "card_text": "string",
          "voice_script": "string"
        }
      },
      "scores": {
        "clarity": 0,
        "elder_resonance": 0,
        "shareability": 0,
        "kindness": 0,
        "language_naturalness": 0,
        "punchline_strength": 0,
        "overall": 0
      },
      "safety": {
        "decision": "approved",
        "flags": [],
        "notes": "string"
      },
      "artifacts": {
        "text": {},
        "cards": {},
        "audio": {},
        "video": {}
      }
    }
  ]
}
```

## QC Report Contract

`qc-report.json` must include:

```json
{
  "schema_version": "whatsapp_joke_qc.v1",
  "total_candidates": 0,
  "approved": 0,
  "rewritten": 0,
  "rejected": 0,
  "language_failures": [],
  "card_legibility_failures": [],
  "audio_failures": [],
  "video_failures": [],
  "banned_content_hits": [],
  "human_review_required": [],
  "done": false
}
```

`done` can be true only when every requested output exists and every approved
joke passes the safety and format gates.

## Generation Pipeline

### Step 1 - Build Run Plan

Inputs:

- `--mode daily|morning|festival|regional|voice-note`
- `--langs en,hi,mr`
- `--count 12`
- `--cards 4`
- `--audio 2`
- `--video 2`
- `--festival` optional string
- `--region` optional string
- `--seed` optional integer
- `--out` output directory

The run plan decides:

- Humor lanes to cover.
- Language variants required.
- Which jokes become cards/audio/video.
- Output paths.

### Step 2 - Generate Candidates

Generate at least 3 candidates for every requested approved joke. If the user
asks for 12 jokes, generate 36 candidates, then filter and rank.

Generator requirements:

- Return strict JSON.
- Include setup, punchline, card text, voice script, humor lane, risk notes.
- Keep each text joke under 450 characters.
- Keep card text under 22 words.
- Keep voice script under 45 words.
- Make every joke understandable without an image.

### Step 3 - Critic Pass

Run a second LLM pass that scores and filters candidates.

Scores are 1-5:

| Score | Meaning |
| --- | --- |
| `clarity` | Understandable on first read |
| `elder_resonance` | Feels familiar to Indian 60+ audiences |
| `shareability` | Someone would forward it without embarrassment |
| `kindness` | Laughs with people, not at them |
| `language_naturalness` | Sounds native or natural enough |
| `punchline_strength` | Has an actual twist or payoff |

Approval rule:

- Reject if any hard safety flag appears.
- Rewrite if overall score is under 4 but safety is clean.
- Approve only if `kindness >= 5`, `clarity >= 4`, and `overall >= 4`.

### Step 4 - Rewrite Weak Candidates

Each candidate can be rewritten at most twice. After two failed rewrites, reject
it and move to the next candidate.

### Step 5 - Translate And Localize

V1 language order:

1. Generate master idea in English or Hinglish.
2. Localize to Hindi and Marathi.
3. Do not literal-translate punchlines when the wordplay fails.
4. Store language-specific punchline notes in the manifest.

Use existing `translate_texts_ollama` for first pass, but require a localization
critic after translation because jokes break easily across languages.

Hindi/Marathi requirements:

- Devanagari output is preferred for cards.
- Conversational phrasing is preferred over formal translation.
- Avoid heavy Sanskritized vocabulary.
- Avoid transliteration unless the user asks for Hinglish.
- If a joke relies on English wordplay, rewrite the joke instead of translating
  it literally.

### Step 6 - Render Text Files

Write one `.txt` per language per joke.

Text format:

```text
<setup>
<punchline>

- Forge WhatsApp Joke Factory
```

The footer should be configurable. Default can be empty if the user does not want
branding on forwards.

### Step 7 - Render Cards

V1 cards should be template-based PIL renders, not diffusion renders.

Card requirements:

- 1080x1080 PNG.
- High contrast.
- No tiny text.
- Max 4 lines of main joke text.
- Minimum 54px font for Devanagari and 60px for Latin on 1080x1080 cards.
- Safe margins of at least 72px.
- Optional tiny brand mark only if it does not look like spam.
- Use `font_for_text`-style script-aware font selection so Hindi/Marathi do not
  render as boxes.

Recommended visual styles:

- Warm paper background with dark text and one accent color.
- Clean high-contrast black/white/yellow `thumbnail-bold` adaptation.
- Simple festival accent border for festival packs.

Do not generate text inside FLUX images. Text must be drawn by PIL.

### Step 8 - Render Audio

Audio requirements:

- 8-25 seconds per joke.
- Natural pause before punchline.
- English: Kokoro if installed, `say` fallback.
- Hindi/Marathi: Sarvam if `SARVAM_TTS_KEY` is set.
- If Sarvam is not configured, skip Hindi/Marathi audio and mark
  `audio_failures` with a clear reason. Do not silently generate bad audio.

Use existing voice style defaults:

- English: `male_warm` or `female_warm`.
- Hindi/Marathi Sarvam: default speakers from existing environment variables,
  unless user overrides.

### Step 9 - Render Video

Video V1 can use the existing `forge video` pattern:

- Joke card as still image.
- Voice note as audio.
- Slow zoom optional.
- Target 15-30 seconds.
- MP4 file small enough to forward comfortably.

### Step 10 - Build Review Sheet

`review.md` should show:

- Approved jokes grouped by language.
- Rejected candidates and reasons.
- Thumbnail/card paths.
- Audio/video paths.
- Human review checklist.

## Prompt Templates

Store prompt templates in `brand/prompts/whatsapp_jokes.json`.

### Generator System Prompt

```text
You write clean, affectionate WhatsApp jokes for Indian adults over 60.
The joke must be family-safe, dignified, and easy to understand in one read.
Do not mock old age, illness, disability, caste, religion, gender, region,
language, class, or politics. Do not include misinformation, medical advice,
miracle claims, investment advice, or "forward this" pressure.
Return only valid JSON that matches the requested schema.
```

### Generator User Prompt

```text
Create {candidate_count} joke candidates for:
- audience: Indian adults over 60
- mode: {mode}
- languages required later: {languages}
- humor lanes to cover: {lanes}
- festival/region if any: {context}

Each candidate must include:
- topic
- humor_lane
- setup
- punchline
- card_text under 22 words
- voice_script under 45 words
- why_it_works
- risk_notes

Avoid all hard rejects from the safety policy.
Return JSON with a top-level "candidates" array.
```

### Critic System Prompt

```text
You are a strict safety and humor editor for Indian WhatsApp jokes for adults
over 60. Your job is to approve only jokes that are kind, clear, culturally
familiar, and safe to forward in a family group. Reject anything offensive,
ageist, political, communal, medical, sexual, scam-like, or mean.
Return only valid JSON.
```

### Critic User Prompt

```text
Score each candidate from 1 to 5 for:
clarity, elder_resonance, shareability, kindness, language_naturalness,
punchline_strength.

For each candidate return:
- id
- decision: approved | rewrite | rejected
- scores
- flags
- editor_notes
- rewrite_instruction if needed
```

## Proposed Files To Add

V1 should be mostly isolated.

```text
bin/whatsapp_joke_factory.py
brand/prompts/whatsapp_jokes.json
brand/presets/whatsapp-senior.json
tests/test_whatsapp_joke_factory.py
docs/WHATSAPP_JOKE_FACTORY_HANDOFF.md
```

Files that may be touched:

```text
bin/forge.py
bin/forge_web.py
docs/FEATURES.md
docs/INDEX.md
README.md
```

Files that should not be touched for V1:

```text
bin/style_engines.py
bin/_engine_base.py
bin/mandala_engine.py
bin/audiobook.py
bin/process-video.py
brand/presets/*.json other than whatsapp-senior.json
```

## Proposed CLI

Add a new command group:

```sh
forge jokes --help
forge jokes generate --help
forge jokes qa --help
forge jokes render --help
```

Primary command:

```sh
forge jokes generate \
  --mode daily \
  --langs en,hi,mr \
  --count 12 \
  --cards 4 \
  --audio 2 \
  --video 2 \
  --voice male_warm \
  --seed 1 \
  --out ~/Desktop/forge-test/whatsapp-jokes/
```

Dry run:

```sh
forge jokes generate \
  --mode daily \
  --langs en,hi,mr \
  --count 12 \
  --cards 0 \
  --audio 0 \
  --video 0 \
  --dry-run \
  --out ~/Desktop/forge-test/whatsapp-jokes-dry/
```

QA-only command:

```sh
forge jokes qa ~/Desktop/forge-test/whatsapp-jokes/manifest.json
```

Render-only command:

```sh
forge jokes render ~/Desktop/forge-test/whatsapp-jokes/manifest.json --cards --audio --video
```

## Implementation Plan For Agent

### Phase 0 - Read Before Editing

Read these files:

- `README.md`
- `docs/INDEX.md`
- `docs/FEATURES.md`
- `docs/ARCHITECTURE.md`
- `bin/forge.py`
- `bin/forge_runtime.py`
- `brand/voices.json`
- `brand/presets/thumbnail-bold.json`

Then run:

```sh
python3 bin/forge.py --help
python3 bin/forge.py voice --help
python3 bin/forge.py video --help
python3 bin/forge.py list
```

### Phase 1 - Build Isolated Script

Create `bin/whatsapp_joke_factory.py`.

It should expose:

```python
def build_parser() -> argparse.ArgumentParser: ...
def generate_pack(args: argparse.Namespace) -> int: ...
def qa_pack(args: argparse.Namespace) -> int: ...
def render_pack(args: argparse.Namespace) -> int: ...
def main(argv: list[str] | None = None) -> int: ...
```

Internal functions:

```python
def load_prompt_templates(path: Path) -> dict: ...
def generate_candidates(plan: dict) -> list[dict]: ...
def critique_candidates(candidates: list[dict], plan: dict) -> list[dict]: ...
def rewrite_candidate(candidate: dict, critique: dict, plan: dict) -> dict: ...
def localize_joke(joke: dict, lang: str) -> dict: ...
def render_text_artifacts(pack: dict, out_dir: Path) -> dict: ...
def render_card(joke: dict, lang: str, out_path: Path, style: dict) -> Path: ...
def render_audio(joke: dict, lang: str, out_path: Path, voice: str) -> Path | None: ...
def render_video(card_path: Path, audio_path: Path, out_path: Path) -> Path | None: ...
def write_review(pack: dict, out_dir: Path) -> Path: ...
```

Use `write_json` for JSON files. Use temp-file then `os.replace` for text,
images, audio, and video outputs.

### Phase 2 - Add Prompt Config

Create `brand/prompts/whatsapp_jokes.json`.

Minimum keys:

```json
{
  "schema_version": "whatsapp_joke_prompts.v1",
  "generator_system": "...",
  "critic_system": "...",
  "localizer_system": "...",
  "rewrite_system": "...",
  "humor_lanes": {
    "daily": [],
    "morning": [],
    "festival": [],
    "regional": [],
    "voice-note": []
  },
  "hard_reject_categories": []
}
```

### Phase 3 - Add Visual Preset

Create `brand/presets/whatsapp-senior.json`.

It should define:

- Warm, high-contrast card colors.
- Display and body font families that work with Devanagari fallback.
- 1080x1080 card template values.
- Optional accent border and footer style.

Do not modify existing presets in V1.

### Phase 4 - Wire Into `forge.py`

Add parser support:

```text
forge jokes generate
forge jokes qa
forge jokes render
```

Implementation can call into `bin/whatsapp_joke_factory.py` directly or import
its `main` functions. Keep this small and boring.

### Phase 5 - Tests

Add `tests/test_whatsapp_joke_factory.py`.

Minimum tests:

- Parser accepts `generate`, `qa`, and `render`.
- Safety filter rejects hard categories.
- Card text wrapping never exceeds configured line count.
- Manifest schema has required top-level keys.
- Dry run writes manifest, QC report, review sheet, and text files without
  requiring Sarvam or FLUX.
- `--cards 0 --audio 0 --video 0` works.
- Missing `SARVAM_TTS_KEY` marks Hindi/Marathi audio as skipped, not successful.

### Phase 6 - Web UI Later

Do not add web UI until CLI tests pass.

When adding web UI:

- Add one action: `whatsapp-jokes`.
- Show only essential controls by default: mode, languages, count, cards, audio,
  video, voice, output folder.
- Put festival, region, seed, footer, speakers, and advanced rendering inside a
  collapsed advanced section.
- Do not expose raw prompt text in default UI.

## Safety Filter Implementation

Use two layers.

### Deterministic Layer

Hard keyword/category checks:

- caste/community slurs and caste names used as joke targets
- political party names and living politicians
- explicit sexual terms
- death/hospital/serious disease terms
- miracle cure and investment-forward language
- "forward to", "share with 10", "good luck if you send"

The deterministic layer catches obvious failures before LLM critique.

### LLM Critic Layer

The critic must explain every rejection using one or more categories:

```text
ageist
medical
political
communal
caste
religious_mockery
sexist
body_shaming
classist
regional_stereotype
misinformation
scam_like
too_mean
not_funny
unclear
translation_failed
```

Any of these categories except `not_funny`, `unclear`, and
`translation_failed` is an automatic rejection, not a rewrite.

## Card Renderer Details

Card rendering is the place most factories fail because text becomes unreadable.

Rules:

- Measure every line with `ImageDraw.textbbox`.
- Wrap by rendered pixel width, not character count.
- Dynamically shrink font only within safe bounds.
- If text still does not fit, mark card render failed and choose a shorter card
  text. Do not write a cramped card.
- Use Devanagari-capable fonts for Hindi and Marathi.
- Use enough line spacing for older eyes.
- Keep contrast ratio visually obvious: dark text on light background or white
  text on dark band.

Recommended card structure:

```text
top: small category label, optional
middle: joke card_text, 2-4 lines
bottom: tiny optional footer
border: one accent color
```

## Audio Timing Details

Voice scripts should include a pause marker internally:

```text
Setup sentence. [pause] Punchline sentence.
```

Renderer behavior:

- Strip `[pause]` for TTS engines that do not support SSML.
- Insert silence during post-processing when possible.
- Keep final audio under 25 seconds.
- If the punchline is too long, rewrite rather than speed up unnaturally.

## Review Rubric

A human reviewer should answer:

- Would I forward this to a family group without explaining it?
- Is the senior character respected?
- Is the joke still funny if read aloud?
- Is the language natural?
- Is the card readable on a phone held at arm's length?
- Is there any hidden political, caste, religious, sexist, or medical risk?

Human approval target for first release:

- At least 8 of 12 text jokes approved by the user.
- At least 3 of 4 cards approved.
- At least 1 of 2 audio/video clips approved.

## Definition Of Done

The agent is done only when all of these pass:

- `forge jokes --help` works.
- `forge jokes generate --dry-run --count 12 --langs en,hi,mr --cards 0 --audio 0 --video 0` works without network or Sarvam.
- A full run produces `manifest.json`, `qc-report.json`, `review.md`, text files,
  four cards, and skipped-or-rendered audio/video according to available TTS.
- Missing Sarvam credentials never crash the run unless the user explicitly asks
  for required Indic audio.
- Every JSON file is schema-stable and valid.
- Every generated card is 1080x1080 PNG and passes text fit checks.
- Every generated MP4 has one video stream and one audio stream when audio is
  requested and available.
- No approved joke contains a hard reject category.
- Rejected jokes and rewrite reasons are recorded.
- Tests pass:

```sh
python3 -m unittest tests.test_runtime tests.test_whatsapp_joke_factory
python3 -m py_compile bin/forge.py bin/whatsapp_joke_factory.py bin/forge_runtime.py
```

- Docs are updated:

```text
README.md
docs/INDEX.md
docs/FEATURES.md
```

## First Sprint Checklist

- [ ] Add `brand/prompts/whatsapp_jokes.json`.
- [ ] Add `brand/presets/whatsapp-senior.json`.
- [ ] Add isolated `bin/whatsapp_joke_factory.py`.
- [ ] Implement dry-run text generation and manifest writing.
- [ ] Implement deterministic safety filter.
- [ ] Implement critic pass.
- [ ] Implement text artifact writing.
- [ ] Implement 1080x1080 PIL card renderer.
- [ ] Implement optional audio render.
- [ ] Implement optional video render.
- [ ] Wire `forge jokes`.
- [ ] Add tests.
- [ ] Update `docs/FEATURES.md`, `docs/INDEX.md`, and `README.md`.

## Agent Notes

Keep the first version boring and reliable. A fast, clean, text/card/audio pack
with strong safety gates is more valuable than a fancy FLUX-heavy system that
produces unreadable cards or risky jokes.

The product lives or dies on taste: kind, familiar, dignified, readable, and
forwardable.
