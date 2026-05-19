# Forge Web UI V2 — Madhubani Atelier (NES Mode)

**Author:** Rohan + Claude
**Date:** 2026-05-18
**Status:** IMPLEMENTED BETA — `bin/forge_web_v2.py` exists. This document is
the design reference; verify behavior against the code before making UI changes.

---

## 1. Why V2

V1 (`bin/forge_web.py`, 4,926 lines, 388 form fields) was built as a
generic Forge dashboard — every engine, every option, every knob exposed
as a form field. For the Madhubani catalog work specifically, that
shape is wrong:

- **For one render, you fill 12 dropdowns** (motif, tradition, detail,
  symmetry, accents, output, ink, shirt-color, placement, layout,
  background, border) plus 3 collapsible expanders. By the time you've
  picked your way through, you've spent more time on the form than the
  render takes.
- **No freeform-prompt entry point.** You can type a subject string but
  there's no "just tell the system what you want" path. Yet we built
  exactly that path on the CLI (`forge_madhubani.py chat`).
- **The NES theme exists but is invisible.** It's currently *fonts +
  colors* sitting on top of an Office-style form. It doesn't feel like
  a game — it feels like a tax return rendered in Press Start 2P.
- **No window into the model's reasoning.** You hit RENDER, you wait,
  you get an image. You don't see *why* the model picked what it picked.
  That's especially painful with the `chat` command where Ollama is
  literally interpreting your request — the most interesting part is
  hidden.

V2 keeps V1 alive (legacy generic dashboard) and adds a **focused,
opinionated, freeform-first, NES-themed UI for the Madhubani workflow
specifically**.

---

## 2. Design principles for V2

1. **Freeform first, dropdowns last.** The default input is a single big
   text box. You type "make me a Madhubani tiger tee in alert pose" and
   it works. Dropdowns appear only when you've asked for them
   ("ADVANCED MODE" toggle, NES-style).
2. **Lean into the NES theme as a game, not a font choice.** Title
   screen, menu chimes (optional), pixel-art animal sprites for the
   8 animals we've seeded, dialog boxes with the [▼] cursor, palette
   restricted to the existing dark-forest-tavern colors (no new hexes).
3. **Reasoning is the show.** A persistent on-screen "TERMINAL" panel
   streams what the model is thinking, what subject was built, what
   seed got picked, what FLUX is doing. The render output is the
   payoff; the reasoning is the entertainment.
4. **One screen per intent.** No tabs, no sidebars with 12 pages. Three
   screens total: HOME (render), GALLERY (browse what you've made),
   WORKSHOP (the legacy form for when you really need it).
5. **Don't break V1.** V2 is a second server on a different port,
   sharing the same backend. Both can run simultaneously.

---

## 3. Three screens, end of story

### 3.1 HOME — `/` — the render screen

Single screen. ~70/30 vertical split. Layout described in ASCII below
so you can visualize the cut before any pixels move:

```
┌──────────────────────────────────────────────────────────────────────┐
│ ▼  FORGE  ·  MADHUBANI ATELIER                          [?] [GALLERY]│
│ ──────────────────────────────────────────────────────────────────── │
│                                                                      │
│   ┌────────────────────────────────────────────────────────────┐    │
│   │                                                            │    │
│   │   > MAKE ME A MADHUBANI TIGER STANDING ALERT_              │    │
│   │                                                            │    │
│   └────────────────────────────────────────────────────────────┘    │
│                                                                      │
│   QUICK PICK:  [🦏 RHINO] [🐅 TIGER] [🦚 PEACOCK] [🐘 ELEPHANT]    │
│                [🐍 COBRA] [🦌 BUCK]  [❄ LEOPARD] [🐒 MACAQUE]      │
│                                                                      │
│   REGISTER:    ( ) CONTEMPORARY    (●) MASTER-PAINTER               │
│   POSES:       (●) ALL FOUR  ( ) PICK: [standing ▼]                 │
│                                                                      │
│                           ┌─────────────────┐                        │
│                           │   ▶ RENDER       │                       │
│                           └─────────────────┘                        │
│                                                                      │
│   ╔══════════════════════════════════════════════════════════════╗  │
│   ║ ▣ TERMINAL                                          [CLEAR] ║  │
│   ╠══════════════════════════════════════════════════════════════╣  │
│   ║ > ollama waking up...                                       ║  │
│   ║ > loaded SKILL.md (9.2 KB)                                  ║  │
│   ║ > parsing: "make me a madhubani tiger standing alert"       ║  │
│   ║ > ANIMAL:   tiger          (confidence: high)               ║  │
│   ║ > POSE:     standing-alert                                  ║  │
│   ║ > REGISTER: master-painter (default for one-off requests)   ║  │
│   ║ > REASONING: user named tiger explicitly and asked for      ║  │
│   ║              alert pose; master-painter is premium default. ║  │
│   ║ > ──────────────────────────────────────────                ║  │
│   ║ > BUILDING SUBJECT STRING ...                               ║  │
│   ║ > seed: 8301 (tiger block + standing-alert offset)          ║  │
│   ║ > flux dev | 24 steps | guidance 5.5 | 1280×1280            ║  │
│   ║ > [████████░░░░░░░░░░░░] step 12/24                         ║  │
│   ╚══════════════════════════════════════════════════════════════╝  │
│                                                                      │
└──────────────────────────────────────────────────────────────────────┘
```

When the render completes, the image slides in BELOW the terminal:

```
   ╔══════════════════════════════════════════════════════════════╗
   ║ ✓ DONE in 87s  ·  attempts/tiger/v1/01_tiger_standing-alert ║
   ╚══════════════════════════════════════════════════════════════╝

   ┌──────────────────────────┐  ┌──────────────────────────────┐
   │                          │  │  ▶ MASTER THIS                │
   │   [the rendered image    │  │  ▶ FLAG THIS                  │
   │    sized to 512×512]     │  │  ▶ RETRY (different seed)     │
   │                          │  │  ▶ OPEN DIRECTIVE.JSON        │
   └──────────────────────────┘  └──────────────────────────────┘
```

That's the whole HOME screen.

### 3.2 GALLERY — `/gallery` — browse what you've made

Pure browsing. Three tabs (NES menu chrome, not browser tabs):
`MASTERED` · `FLAGGED` · `ATTEMPTS`. Grid of thumbnails per tab,
clicking a thumbnail opens a detail card with the directive metadata,
masters cited, and quick-action buttons (promote / flag / regenerate).
Reads from `generated/madhubani_animals/INDEX.md` for state.

No filters, no search. Small catalog (≤240 designs); a grid is enough.

### 3.3 WORKSHOP — `/workshop` — the legacy form (one click away)

For when you actually need the 12 dropdowns (LoRA work, edge cases,
non-Madhubani engines). This is just the existing V1 UI, served via
a link from the HOME header. Don't rebuild it; just expose it.

---

## 4. The NES theme — what doubling down looks like

The current theme has the *ingredients*. V2 cooks them into a meal.
Concretely:

| Element | V1 today | V2 |
|---|---|---|
| Title | "Forge Wizard" plain text | "FORGE ▸ MADHUBANI ATELIER" centered, large Press Start 2P, blinking [▼] cursor, scanline-overlaid pixel banner above |
| Navigation | Sidebar with text labels | Top bar: 3 menu items (`[NEW]`, `[GALLERY]`, `[WORKSHOP]`) in pixel-button slabs that "press down" on hover |
| Input field | Standard `<textarea>` with green border | Sunken pixel-bordered text panel with `>` prompt prefix and blinking block cursor, mono pixel font (Pixelify Sans), background slightly darker than the surface |
| Buttons | Pixel slab buttons already exist | Same slab + add the depressed-on-click 1px shadow flip + optional faint click sound (Web Audio API, beep) |
| Quick-pick animals | Doesn't exist | 8 chunky pixel chips with **small custom pixel-art sprite per animal** (~32×32 native upscaled) — rhino, tiger, peacock, elephant, cobra, blackbuck, snow-leopard, macaque |
| Terminal panel | Doesn't exist | Black background, lime-green text in mono pixel font, faint CRT scanlines stronger than the rest of the page, leading `>` per line, blinking cursor at end while active |
| Progress bar | Spinner | `[████████░░░░░░░░░░░░] step 12/24` rendered as text + chunky pixel bar block characters or actual CSS pixel rects |
| Loading / waiting | Generic spinner | "INSERT COIN TO CONTINUE..." or "PRESS START" idle states with blink animation |
| Success | Toast | "✓ MASTERED" stamp with hard pixel shadow, fades in over the image |
| Errors | Red text | Red pixel slab with "! ERROR" header — like a Pokémon battle dialog |

**What we DO NOT add:** new colors outside the existing palette, new
fonts, gradient effects, modern UI patterns (modal overlays with blur,
toast notifications, etc.). NES means stay in-period.

**What's optional (decide later):** chiptune background music toggle,
keyboard shortcuts (`1-8` to pick quick-pick animals, `enter` to render,
`esc` to abort), animal sprite animations.

---

## 5. The reasoning terminal — the headline feature

This is the part you're most asking for. Let me spec it precisely.

### What it streams

The terminal is a **server-sent-events (SSE) stream** from the backend.
Each line is one event. The backend emits events at every decision
point:

```
> ollama.boot         model=llama3.1:8b at http://localhost:11434
> ollama.context      loaded SKILL.md (9.2 KB) + animals.json + poses.json
> user.request        "make me a madhubani tiger standing alert"
> ollama.thinking     [.....]                              ← shows raw ollama tokens as they stream
> ollama.decision     {"animal":"tiger","pose":"standing-alert","register":"master-painter","reasoning":"..."}
> validation.passed   animal=tiger pose=standing-alert register=master-painter
> render.plan         seed=8301 block=tiger+1  config=12-fields  subject=1244-chars
> render.subject      single centered Royal Bengal Tiger STANDING ALERT in complete full-body side profile... (full text shown)
> render.engine.start mflux flux-dev steps=24 guidance=5.5 1280×1280
> render.engine.step  3/24
> render.engine.step  6/24
> render.engine.step  9/24
> ...
> render.engine.done  87.3 seconds
> postprocess.transparent  generated tiger_standing-alert.transparent.png
> done                attempts/tiger/v1/01_tiger_standing-alert.png
```

This isn't pretend reasoning — these are the actual events happening
in `bin/forge_madhubani.py` and the FLUX subprocess. The backend
captures them and pushes to the SSE stream.

### What it looks like

Lime-green-on-black, Pixelify Sans pixel font (sharper than Press
Start 2P for the smaller body text), each line prefixed `>`, blinking
cursor at the end of the most recent line until the next event. Long
lines wrap with a soft `  ` indent for the wrapped portion. The
TERMINAL header has `[CLEAR]` and `[COPY]` buttons.

The user can:
- Watch it in real time
- Pause / resume the stream
- Click `[COPY]` to copy the entire transcript (useful for sharing failures with me later)
- Switch between `LIVE` and `RAW JSON` views (RAW shows the underlying SSE events un-prettified)

### When it's not chatting (e.g. quick-pick animal click)

The chat / Ollama lines are skipped (we know the routing already) but
all the render-side lines still stream:

```
> quick-pick          rhino
> register            master-painter  (default)
> poses               all four
> render.plan         (per pose)
> render.engine.start ...
> ...
```

Same theatre, less LLM.

---

## 6. Architecture — how the backend works

V2 lives in `bin/forge_web_v2.py` — a new file, ~500–800 lines (vs
V1's 4,926). It does NOT extend V1. It's:

```
┌──────────────────────────────────────────────┐
│ Browser (Pixelify Sans + Press Start 2P)     │
│   HOME / GALLERY / WORKSHOP screens          │
│   SSE stream from /events/{render_id}        │
└──────────────────────────────────────────────┘
                    ▲
                    │  HTTP + SSE
                    ▼
┌──────────────────────────────────────────────┐
│ bin/forge_web_v2.py                          │
│   - GET /              → HOME html           │
│   - GET /gallery       → GALLERY html        │
│   - POST /render       → start a render job  │
│       → returns {render_id}                  │
│   - GET /events/{id}   → SSE stream of       │
│                           lifecycle events   │
│   - POST /chat         → start a chat→render │
│   - POST /promote      → calls forge_madhubani.py promote
│   - POST /flag         → calls forge_madhubani.py flag
│   - GET /api/state     → returns INDEX state │
│   - Static assets      → /static/sprites/*.png, /static/sounds/*.wav
└──────────────────────────────────────────────┘
                    │
                    │  subprocess + parse stdout
                    ▼
┌──────────────────────────────────────────────┐
│ bin/forge_madhubani.py  (already built)     │
│ bin/forge.py engine render ...              │
│ Ollama at localhost:11434                   │
│ mflux at localhost (no port, subprocess)    │
└──────────────────────────────────────────────┘
```

Key implementation notes:
- **stdlib only**, same constraint as V1. `http.server` +
  `urllib.request` + `subprocess`. No FastAPI, no async framework, no
  websockets. SSE is just a long-lived HTTP response with
  `text/event-stream`.
- **One Python process** runs the V2 server. Per-render state lives in
  a small in-memory dict keyed by `render_id`. No database.
- **Backend captures events** by parsing the stdout of the rendered
  subprocesses line-by-line. We'll add minimal structured-log lines to
  `forge_madhubani.py` so this parsing is reliable (e.g. it already
  prints `── [n/4] animal — pose (seed=N)` — we add a few more).
- **Ollama streaming** uses Ollama's `/api/generate` with `stream:true`
  so we can show tokens arriving live in the terminal.
- **mflux progress** parses `mflux-generate`'s stdout lines that
  already report step numbers, surfaces them as `render.engine.step`
  events.

Port: **8081** (V1 stays on 8080). Configurable via
`FORGE_V2_PORT` env var. Browser opens automatically on launch.

---

## 7. What gets cut from V1 → V2

Brutal list. V2 does NOT include these V1 features (they stay in V1
WORKSHOP for when you need them):

- `brief`, `episode`, `audiobook`, `audiobook-simple`, `audiobook-asmr`
  pages — non-Madhubani
- `process-video-process`, `models-adopt` admin pages
- `coloring-page`, `mandala-art-page`, `indian-folk-page`,
  `stylized-cinematic-page` — non-Madhubani engines
- `edit`, `voice`, `video`, `mandala`, `childrens-book`, `folk-art`
  pages — non-Madhubani
- All 388 form fields — V2 has ~6 controls total (text input,
  8 animal chips, register radio, poses radio, render button, advanced
  toggle to reveal a tiny "override seed / steps" panel)
- LoRA stack picker — defer; if you need LoRA control, use WORKSHOP
- Image control expander (guidance, refine, negatives, no-default-loras)
  — V2 uses engine defaults always; WORKSHOP if you need overrides

The radical-cut number: **from 388 fields to ~6.** That's the point.

---

## 8. What stays the same

- Backend engine (`bin/style_engines.py`) — unchanged
- Schemas (`brand/madhubani/*.json`) — V2 reads them directly
- `bin/forge_madhubani.py` — V2 calls it; CLI still works standalone
- Output directories (`generated/madhubani_animals/...`) — V2 reads/writes here
- Artist card generator — V2 invokes it after MASTER button
- The 12 principles, the rubric, the workflow — all unchanged
- Offline operation — V2 is local-only, no external network calls

---

## 9. The pixel-art animal sprites

The 8 quick-pick chips need sprites. Three options for source:

| Option | Effort | Result |
|---|---|---|
| (a) I draw them as SVG pixel art inline (one-time generate) | 1–2 hours | Tiny crisp 32×32 sprites, scale cleanly, no asset files. Hand-made feel. |
| (b) I generate them via Forge's own minimalist-tshirt engine at tiny size, save as PNG | ~30 min + render time | Real Madhubani-style sprites that match the catalog aesthetic. Could be too detailed at 32px though. |
| (c) Use emoji as a stand-in for V2 v0, add real sprites in V2 v1 | 0 min | Ships faster, looks slightly less polished initially. |

Recommendation: **(c) → (a)** — emoji to start, real pixel sprites in
the next iteration once the rest of V2 is stable. Don't let asset work
block the UI ship.

---

## 10. Open decisions — resolved

### Resolved 2026-05-18
- ~~**Animal sprite source**~~ — decided: **Use Forge to generate.** A
  render script will produce 8 sprite PNGs at small dimensions (~256×256
  base, displayed at ~64×64) into `bin/static/sprites/`. Until sprites
  exist, frontend falls back to emoji. (See §9 option (b)+(c) combined.)
- ~~**Show full prompt in terminal**~~ — decided: **always show full
  prompt.** Total transparency wins over visual tidiness.
- ~~**Build B1–B5 approval**~~ — decided: **yes, build now.**

### Still open / deferred to V2.1
- **Audio.** Chiptune music + UI sound effects. Defer.
- **Keyboard shortcuts.** `1–8` quick-pick, `enter` render, `g` gallery,
  `?` help, `esc` abort. Will add in B7 polish if time allows.
- **Default register on quick-pick.** Master-painter always (simplest
  mental model — matches plan default).
- **Real-time intermediate latent preview.** Defer (I/O overhead).
- **WORKSHOP integration depth.** Link out to V1 on port 8080. No iframe.

---

## 11. Build phases

Once you approve this plan, the build sequence:

| Phase | What | Estimate |
|---|---|---|
| **B1** | Minimal SSE backend — POST /render, GET /events/:id, parse forge_madhubani.py stdout | 2 hours |
| **B2** | HOME screen HTML/CSS — title bar, prompt input, quick-pick chips (emoji), register toggle, render button, empty terminal panel | 2 hours |
| **B3** | Wire HOME → backend, terminal streams events live | 1 hour |
| **B4** | Chat path — POST /chat that calls Ollama and emits events; user can choose between freeform-text and quick-pick | 1.5 hours |
| **B5** | Render-complete payoff — show image, MASTER/FLAG/RETRY buttons that POST to /promote, /flag, /render?retry=true | 1 hour |
| **B6** | GALLERY screen — read INDEX.md + glob mastered/flagged/attempts/, render grids, detail cards | 1.5 hours |
| **B7** | NES polish pass — pixel banner, chunky chips, blinking cursors, error dialogs, scanline overlay tuning, keyboard shortcuts | 2 hours |
| **B8** | Replace emoji with real pixel-art sprites for 8 animals | 1–2 hours |
| **Total** | ~12 hours of focused work | |

That's a one-week sprint at evenings-only pace, or two focused days.

---

## 12. Decision log → INDEX

Once V2 ships, update:
- `docs/catalog/INDEX.md` — add V2 to "Code map"
- `docs/catalog/SKILL.md` — note that web V2 is the recommended UI for
  catalog work
- `README.md` (Forge root) — add a launch command for V2

---

## 13. Recommended next steps

1. You read this plan, push back on §3 layout if it's not the screen
   you want.
2. You answer §10 open decisions.
3. I build B1 → B5 as the minimum viable V2 (the freeform input,
   the terminal, one quick-pick chip, the render button, the image
   payoff). Ship and test.
4. If B1–B5 lands well, I do B6 + B7 + B8 in sequence.

I don't write any code until you green-light the plan. The radical
cut from 388 fields to ~6 is the architectural decision — if you want
to keep more knobs visible, say so now and I'll revise §3 before
anything ships.
