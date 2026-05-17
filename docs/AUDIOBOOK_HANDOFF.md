# Audiobook Perfection — Handoff Brief

You are the agent tasked with making Forge's audiobook pipeline genuinely
*perfect*. Drop in a `.pdf`, `.txt`, or `.rtf`. Get back a publication-grade
multilingual audiobook (English + Hindi + Marathi at minimum), with accurate
phonetics, professional pacing, and clean masters ready for either pure
audio (Audible / Spotify) or audio-over-video (YouTube).

You work on branch `audiobook-perfection` in a separate git worktree. The
rest of Forge keeps shipping on `main`. We meet at the public API contract
defined in [`AUDIOBOOK_API.md`](AUDIOBOOK_API.md). Don't break the contract
without filing a PR for review.

---

## 0. Where to read first, before you touch any code

1. **`docs/AUDIOBOOK_API.md`** — the public API surface you cannot silently change
2. **`docs/COLORING_BOOK_SCIENCE.md`** — the methodology pattern (research → engine rules → 50 vetted presets) that produced our best image work. Same shape applies here.
3. **`BACKLOG.md`** — full Forge feature state. Audiobook items live there.
4. **`bin/audiobook.py`** — current production code path (multilingual ASMR pipeline)
5. **`bin/forge.py::cmd_audiobook`** and **`cmd_audiobook_simple`** — the basic audiobook CLI flow
6. **User priors** (saved in chat, recorded here):
   - The user found Hindi + Marathi output "robotic and pathetic". Marketing-list speakers (anushka, vidya, soham, gokul) that we tried first **don't exist in `bulbul:v3`** — only the 22 names the API actually returns are valid (see `bin/forge_web.py::config_payload`).
   - Sarvam Bulbul v3 is the production Indic TTS. We currently call it at `pace=1.0`, `temperature=0.65`, `sample_rate=48000`, `enable_preprocessing=True` — but no per-text prosody tuning, no phonetic correction, no Indic-specific pre-processing.
   - English narration runs on Kokoro v1.0 (local neural). Fallback is macOS `say`.

---

## 1. Definition of done

A successful audiobook for *Old Man and the Sea* (Hemingway, ~26 000 words, English source) should:

- Render in **English** at podcast-grade quality: -16 LUFS integrated loudness, -1 dBTP peak, professional pacing (~160 WPM with paragraph beats), no audible glitches
- Render in **Hindi** with: correct Devanagari schwa-deletion, correct stress on multi-syllable words, English proper nouns transliterated *but pronounced English-ish* (not over-Indianised), numbers spoken as Hindi cardinals, dialogue distinguished from narration via subtle pace + pitch shift
- Render in **Marathi** with: schwa **retention** (Marathi keeps schwa Hindi drops), correct anuswara nasalisation, female default narrator (current default `shreya`) that sounds like a published Marathi audiobook reader, not a robot
- Produce one **clean WAV master per language** at 48 kHz mono
- Produce one **listener-ready MP3** at 128 kbps with ID3 tags (title, language, chapter marks)
- Produce one **YouTube-ready MP4** when a loop video is supplied
- Produce one **SRT subtitle file per language** time-aligned to the audio
- Produce a **single QC manifest JSON** with: total duration, chapter durations, LUFS/peak measurements, list of detected mispronunciations (via Whisper transcription compare), TTS engine + speaker used per chunk

The user must be able to **drop the book file in the web wizard, click Run, and walk away.** Everything above happens automatically.

---

## 2. Science scope — what to research first

You MUST cite sources for every load-bearing rule you add. Same standard as `docs/COLORING_BOOK_SCIENCE.md` (921 lines, every section ends with `→ engine rule`).

### 2.1 Professional narration pacing (audio engineering literature)

- WPM ranges by genre (fiction / non-fiction / children's / textbook)
- Sentence-end pauses (typical 300-600 ms)
- Paragraph-end pauses (typical 800-1500 ms)
- Chapter break pauses (typical 2-3 s)
- Dialogue vs narration register shifts
- Cite: Audible Approved Producer Style Guide, AES standards for audiobook loudness, ACX guidelines

### 2.2 Indic phonetics — the hard problem

**Hindi (Devanagari)**:
- Schwa deletion rule: the final inherent `अ` (a) on consonants is silent in modern Hindi but pronounced in classical Sanskrit. Modern TTS often gets this wrong on rare words.
- Sandhi rules at word boundaries
- Loan-word handling: English words in Hindi text should stay English-pronounced, not transliterated phonetically (e.g. "computer" → /kəmˈpjuː.tər/, not /kɒmpjuː.t̪er/)
- Reference papers: Pandey (1990) on Hindi schwa-deletion; Choudhury et al. (2004) computational rule for schwa-deletion

**Marathi**:
- **Schwa is retained** — opposite of Hindi. "रामा" is pronounced /ɾaːmaː/ in Marathi, /ɾaːm/ in Hindi.
- Anuswara (ं) nasalisation rules differ from Hindi
- Sanskrit loan-word emphasis differs from Hindi
- Reference: Dhongde & Wali (2009), *Marathi*, Mouton Grammar Library

**Tamil / Bengali / Telugu / Gujarati / Punjabi** (lower priority, but Sarvam supports them):
- Each has distinct phonotactic constraints
- Document per-language quirks if you scope them in

### 2.3 Phonetic pre-processing — the engineering opportunity

Local LLM (qwen3:8b via Ollama) can pre-process text BEFORE sending to Sarvam. Examples of what to ask the LLM:

- **Annotate proper nouns**: tag `<en>` around English names so Sarvam doesn't over-transliterate them
- **Disambiguate homographs**: in Marathi "जा" is "go" (verb) but in compound "जागा" is "place" — context matters for stress
- **Expand abbreviations**: "Dr." → "Doctor"; "P.M." → "after-noon" (or "post-meridiem" depending on register)
- **Spell out numbers in language**: "1947" → "उन्नीस सौ सैंतालीस" (Hindi) but "एक हजार नऊशे सत्तेचाळीस" (Marathi)
- **Mark dialogue**: wrap "..." quoted speech so the prosody engine can shift register
- **Identify ambiguous words**: flag the top N most-likely-to-mispronounce words per chunk, render them, compare via Whisper back-transcription, and reject + reroll if too far off

Build this as a `text_prep.py` pipeline stage. Document every prompt you give the LLM in `docs/AUDIOBOOK_SCIENCE.md`.

### 2.4 Whisper-loopback QC

We already have `mlx_whisper` running locally for subtitle generation. Use it as a quality check:

1. TTS the chunk
2. Whisper-transcribe the resulting audio
3. Compute character-level edit distance against the input text
4. If edit distance / total > threshold (e.g. 5%), the TTS got it wrong — try a different speaker, slower pace, or LLM-pre-processed text
5. Log all misses to the QC manifest with timestamps

This is the closest thing to "the system learns" within today's tooling. Cite: Radford et al. (2022) for Whisper accuracy benchmarks per language; you'll need to validate Whisper's Hindi/Marathi performance is good enough to be a useful QC oracle (it's better than people think for Sarvam-quality input).

### 2.5 Loudness mastering (broadcast standards)

- **Audible**: -23 to -18 LUFS integrated, -3 dBTP peak max, mono or stereo
- **Spotify**: -14 LUFS integrated, -1 dBTP
- **YouTube**: -14 LUFS integrated
- **Podcast standard**: -16 LUFS integrated, -1 dBTP

Implement via `ffmpeg` `loudnorm` filter (EBU R128). Should be a single function call per output, parameterised by target spec.

---

## 3. Existing tooling you already have

| Capability | Where | Notes |
|---|---|---|
| Sarvam Bulbul v3 TTS | `bin/audiobook.py::tts_sarvam` | hi, mr, bn, ta, te, gu, kn, ml, pa, od. 22 validated speakers. API key in `~/.sarvam/key` or `SARVAM_TTS_KEY` env var. |
| Kokoro v1.0 TTS (English) | `bin/forge.py::_kokoro_engine` | Local neural, ~80 MB model, real-time on M5 Max |
| macOS `say` (fallback) | `bin/forge.py::_synthesize_say` | Zero-install fallback |
| Whisper STT | `mlx_whisper.transcribe(audio, language='hi')` | Already used for subtitle generation |
| sarvam-translate (en↔hi, en↔mr) | `bin/forge_runtime.py::translate_texts_ollama` | Local LLM via Ollama, retry-with-rising-temperature on placeholder echo |
| qwen3:8b | Ollama | Available for text annotation / pre-processing prompts |
| ffmpeg | system | for all audio mux / loudnorm / encoding |
| .rtf parsing | `bin/audiobook.py::parse_rtf` (now handles `.rtf`, `.txt`, `.md`, `.pdf`) | striprtf + pypdf |
| .pdf parsing | same — uses pypdf | Already wired |

You DO NOT need to reinvent any of these. You DO need to wire them together with intelligent text pre-processing and per-chunk QC.

---

## 4. Architecture proposal (you can reshape, but the public API must hold)

Suggested package layout once you refactor:

```
bin/audiobook/
  __init__.py            # public API — see AUDIOBOOK_API.md
  pipeline.py            # main orchestrator
  readers/
    pdf.py
    rtf.py
    txt.py
  chunker.py             # sentence / paragraph / chapter splitting
  text_prep.py           # LLM annotation, expansion, disambiguation
  phonetics/
    hindi.py             # schwa-deletion, sandhi, loan-words
    marathi.py           # schwa retention, anuswara
  tts/
    kokoro.py            # English
    sarvam.py            # Indic
    say.py               # fallback
    router.py            # per-language engine selection
  prosody.py             # pause durations, dialogue shifts
  qc.py                  # Whisper loopback compare
  mastering.py           # loudnorm, normalise, mix bed
  outputs/
    wav.py
    mp3.py
    mp4.py
    srt.py
    manifest.py
  science/
    bench.py             # quality benchmarks
    eval_corpus/         # reference texts + expected outputs

bin/audiobook.py         # thin shim → from audiobook import *
```

Keep `bin/audiobook.py` importable as a module for backwards-compatibility during transition.

---

## 5. Hard boundaries — what you DO NOT touch

| Path | Why |
|---|---|
| `bin/style_engines.py` | Image engines, unrelated |
| `bin/_engine_base.py` | Image engine base, unrelated |
| `bin/forge_gallery.py` | Gallery system, unrelated |
| `bin/forge_web.py` **non-audiobook code** | Web UI for image actions, gallery, etc. **You may edit the audiobook web form specs only.** |
| `bin/forge.py` **non-audiobook commands** | Other CLI subcommands |
| `brand/prompts/` `brand/presets/` `brand/loras/` `brand/references/` | Image-side brand assets |
| `docs/COLORING_BOOK_SCIENCE.md` | Image-side methodology |

If you find a bug in one of these, file an issue / PR description explaining what — don't fix it on your branch. Otherwise the merge gets painful.

### 5.1 Shared zones — change only with coordination

These you CAN edit, but every change needs a clear commit message + a one-line note in `docs/AUDIOBOOK_HANDOFF.md`'s `## Shared-zone changes` log so we know what to expect at merge:

- `bin/forge.py::cmd_audiobook` and `cmd_audiobook_simple`
- `bin/forge_web.py` — only the audiobook actions: `audiobook`, `audiobook-simple`, `audiobook-asmr` specs and their `build_command` branches
- `bin/forge_runtime.py` — only audiobook-relevant additions (e.g. new Ollama helpers used by `text_prep.py`)

---

## 6. Acceptance criteria — how we know you're done

You can self-test against this corpus, no human review needed. The deliverable is **YES** to every one of these:

### Functional
- [ ] `forge audiobook --book /any/file.pdf --languages en,hi,mr` → produces 3 valid WAVs + 3 MP3s + manifest.json + (if video supplied) 3 MP4s
- [ ] `forge audiobook --book file.rtf` works
- [ ] `forge audiobook --book file.txt` works
- [ ] Files larger than 100 000 characters chunk + stitch correctly (no audible seams)
- [ ] The web wizard "Audiobook (simple)" action runs the same pipeline end-to-end

### Quality
- [ ] English output at -16 LUFS ±0.5, -1 dBTP peak
- [ ] Hindi output passes Whisper-loopback at >= 95% character accuracy
- [ ] Marathi output passes Whisper-loopback at >= 95% character accuracy
- [ ] Whisper-detected misses are listed in the manifest with timestamps
- [ ] Proper nouns (e.g. "Hemingway", "Cuba") survive into Hindi/Marathi unchanged
- [ ] Numbers in source text become language-correct words in output ("1947" → "उन्नीस सौ सैंतालीस" in Hindi, etc.)

### Science
- [ ] `docs/AUDIOBOOK_SCIENCE.md` exists, ≥500 lines, every rule cited
- [ ] Each pacing rule has a published reference (Audible / ACX / Pandey 1990 / Dhongde 2009 / etc.)
- [ ] LLM-pre-processing prompts are documented verbatim in the science doc
- [ ] Whisper-loopback QC methodology + thresholds are documented

### Process
- [ ] Code coverage on the audiobook package ≥70% via the eval_corpus tests
- [ ] All public API functions documented in `AUDIOBOOK_API.md` (you co-own that file)
- [ ] No changes to "hard boundary" files (see §5)
- [ ] PRs to main are merge-conflict-free against current main + the documented "shared zone" changes

---

## 7. Git workflow

You work in a **separate git worktree** to avoid filesystem collision:

```sh
cd ~/Desktop/Forge
git worktree add ~/Desktop/Forge-audiobook audiobook-perfection
cd ~/Desktop/Forge-audiobook
# you're now on branch audiobook-perfection, all your edits stay here
```

Commit + push to your branch as often as makes sense:

```sh
git add bin/audiobook.py bin/audiobook/ docs/AUDIOBOOK_SCIENCE.md ...
git commit -m "audiobook: <what changed>"
git push origin audiobook-perfection
```

When you want a feature merged to main:
1. Push your latest to `audiobook-perfection`
2. Open a PR on GitHub (or message the user — they'll merge)
3. Don't force-merge to main; we review first

If you need to pull main into your branch (because we shipped something that affects you):

```sh
git fetch origin
git rebase origin/main
# resolve any conflicts in shared-zone files (see §5.1)
git push --force-with-lease origin audiobook-perfection
```

---

## 8. The first 5 things to do, in order

1. **Read** `AUDIOBOOK_API.md` (the contract) and `bin/audiobook.py` (current code path) end-to-end. Take 30 min. Make notes.
2. **Set up the worktree** as in §7. Verify `forge audiobook --help` runs from your worktree path.
3. **Build the eval corpus** — pick 3-5 short books (Old Man and the Sea, a Premchand short story in Hindi, a Pu La Deshpande passage in Marathi, etc.) and stage them in `bin/audiobook/science/eval_corpus/`. These are your QC benchmark forever.
4. **Run the existing pipeline** on each corpus item, save outputs. **This is your baseline.** Every change you make has to beat this baseline on the acceptance criteria.
5. **Write `docs/AUDIOBOOK_SCIENCE.md`** as the first deliverable — even before any code. Cite your sources for pacing science + Indic phonetics + loudness standards. The doc forces you to plan what the engine will encode.

Then build.

---

## 9. Shared-zone changes log

When you edit a shared-zone file (per §5.1), add a one-line entry here:

```
## Shared-zone changes
- 2026-MM-DD  bin/forge_web.py audiobook-simple spec: added <field> for <reason>
- ...
```

(Empty for now; you're the first.)

---

## 10. Open questions for the user — file as issues, don't block

- Sarvam API rate limits + cost for long books (their pricing tier?)
- Are there Sarvam **personas** (mentioned in their marketing) we can use beyond the 22 `bulbul:v3` speakers? If yes, how to access via API?
- For Audible-grade output: do we target their `-23 to -18 LUFS` envelope or the looser podcast `-16 LUFS`? Depends on intended distribution.
- Where should audiobook outputs land by default? Currently `~/Desktop/forge-test/audiobook/<title>/`. Do we want versioning (e.g. `<title>/v1/`, `<title>/v2/`)?

---

## You are not alone

Forge has a `forge-gallery` system that ranks renders by user feedback. If you build similar telemetry for audiobook chunks (which Whisper-loopback losses came back, which speakers got the fewest misses, which paragraphs needed re-rendering), the gallery is the place to surface that data. Don't reinvent — extend.

Good luck. Ship beautiful audio.
