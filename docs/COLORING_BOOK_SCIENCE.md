# Children's Coloring Book — Science & Methodology

The research, design canon, and empirical results that drive the
`childrens-coloring-book` engine in `bin/style_engines.py`. This is the
*why* behind every rule in the engine's `build()` method, every enum
value, every invariant, and every preset in `brand/prompts/library.json`.

Every section ends with **→ engine rule**, the concrete code change or
configuration constraint that section justifies. Treat the rule list as
the spec; the prose is the citation.

---

## 0. TL;DR — six load-bearing rules

The full document is six rules, in priority order. Everything else is
elaboration.

1. **Subject first, style second.** FLUX-dev's T5-XXL encoder reads up
   to 512 tokens. If the subject is buried, the model deprioritises it.
   The first ~120 tokens of the prompt must contain the subject and the
   "this is a coloring book page" framing.
2. **FLUX ignores negative prompts.** FLUX is a flow-matching model
   designed for CFG=1; the classifier-free-guidance mechanism that lets
   diffusion models avoid concepts does not apply. Convert *every*
   anti-pattern into a positive instruction.
3. **Streamlined illustrations improve comprehension by +32.86%**
   (Eng, Godwin & Fisher, *npj Science of Learning*, 2020). Every visual
   element on the page must serve the named story; remove decoration
   that competes for attention.
4. **Match complexity to grasp.** Toddlers (3-5y) use cylindrical or
   digital pronate grasp — minimum fillable region ~30 mm. Kids (6-9y)
   use modified-tripod — regions 8–30 mm. Pre-teens (10-12y) have
   refined pincer — regions down to 4 mm.
5. **Use the tradition's own native vocabulary.** Mo Willems' "the
   simpler the drawing, the more expressive it has to be" is not
   decoration. Eric Carle's bold outlines come from cut-shape layering.
   Beatrix Potter draws in pen-and-ink, *then* watercolours. The engine
   must encode these as distinct visual languages, not as one generic
   "cartoon".
6. **Build for the printer.** US Letter 8.5×11", 300 DPI minimum for line
   art (600 DPI for tight detail), 0.125" bleed, 0.5" safety margin,
   thicker lines forgive bad printers.

These six are referenced everywhere below as **R1**–**R6**.

---

## 1. Why this document exists

When we shipped the first version of the children's-coloring-book engine
we had:

- 11 enum banks · 56 anti-pattern negatives · 14 starter recipes
- A 5000-character build-prompt that visually rendered a few crisp
  pages but inconsistently grey-filled others, drifted on the requested
  setting, and produced uneven line weights between renders.
- No empirical anchor for *why* any of the choices were right.

That looked like an engineering problem (tweak the negatives, try
different guidance scales) but it was actually a **knowledge problem**.
The diffusion model has its own preferences, children's books have
their own publishing conventions, real picture-book illustrators have
their own deliberate craft, child development imposes its own
constraints, and adult-coloring-book design has a sixty-year tradition
nobody had translated into our codebase. Without the canon, every
prompt iteration was guessing.

This document is the canon. Six parts, six rules, every claim cited,
every rule mapped to a line in `bin/style_engines.py`.

---

# Part 1 — The diffusion substrate (FLUX-dev specifically)

The model is the first constraint. Before we talk about coloring books,
talk about what FLUX-dev rewards and punishes.

## 1.1 Two text encoders, two attention windows

FLUX-dev (and Schnell) use a dual-encoder architecture:

- **CLIP L/14**: hard cap at 77 tokens. Used for short, high-priority
  conditioning signals.
- **T5-v1.1-XXL**: up to **512 tokens** on FLUX-dev (256 on Schnell).
  This is the long-form encoder that handles natural-language prompts.

The community-confirmed behaviour: anything past CLIP's 77-token limit
is still encoded by T5 and still reaches the model — the CLIP truncation
warning is misleading. But T5 itself has practical attention falloff
well before the 512-token ceiling. Empirically, content placed in the
first 100–150 tokens has measurably stronger influence on the final
image than content in the last 100 tokens of a maxed-out prompt.

**Citations:**
- [FLUX.1-dev token limits (HuggingFace discussion)](https://huggingface.co/black-forest-labs/FLUX.1-dev/discussions/43)
- [Boqiang Liang — FLUX.1-dev Encoders and Token Limitations (Medium)](https://medium.com/@lbq999/flux-1-dev-encoders-and-token-limitations-8631c179eaad)

**→ Engine rule (R1):** the build template puts SUBJECT and "COLORING
BOOK PAGE — black ink line drawing on white paper" in the first block.
Tradition descriptions are compacted to ≤280 characters. Total prompt
target: ≤2500 characters (~620 tokens, with safety margin for tokenizer
variance). Anything style-detail-related lives in the back half.

## 1.2 Natural language, not keyword soup

Three independent FLUX prompting guides converge on the same point:

> FLUX doesn't want keyword lists — it wants natural language. If you
> bury the subject at the end of a long description, FLUX may
> deprioritize it. (skywork.ai, fal.ai, getimg.ai)

Old Stable-Diffusion–era prompts that read like
`masterpiece, 8k, ultra-detailed, [subject], [list of adjectives]`
hurt FLUX. The dual-encoder picks up genuine sentence structure better
than weighted comma-separated keywords.

**Citations:**
- [Skywork — FLUX.1 prompting ultimate guide](https://skywork.ai/blog/flux-prompting-ultimate-guide-flux1-dev-schnell/)
- [getimg.ai — FLUX prompt pro tips and common mistakes](https://getimg.ai/blog/flux-1-prompt-guide-pro-tips-and-common-mistakes-to-avoid)
- [fal.ai — How to use FLUX](https://fal.ai/learn/tools/how-to-use-flux)

**→ Engine rule:** every block in the build prompt is a complete English
sentence, not a keyword list. The audit JSON keeps the keyword form for
debugging, but the FLUX-bound prompt is prose.

## 1.3 Negative prompts are largely inert in FLUX

This is the single biggest correction to the existing engine. The
established empirical position in the FLUX community:

> Flux was not designed to use negative prompts at all. Flux uses flow
> matching training instead of the traditional diffusion approach. It's
> built to operate with a CFG value of 1, which means there's no
> mechanism for classifier-free guidance to push away from a negative
> prompt. Instead of telling the model what not to do, tell it what you
> want. (aiphotogenerator.net, merlio.app)

The previous engine carried 56 negatives. Most of those entries were
likely doing nothing. Some implementations (ComfyUI's "dynamic
thresholding", certain mflux versions at non-unit guidance) do pass
something resembling a negative prompt through; the effect is weak and
inconsistent.

**Practical replacement strategy** — for every anti-pattern we want to
avoid, write the positive opposite:

| Don't say (negative) | Say instead (positive) |
|---|---|
| "no grey fill" | "pure white paper, black ink outlines only" |
| "no shading" | "flat fillable shapes, no interior tones" |
| "no AI glow" | "crisp clean ink lines, technical-pen feel" |
| "no watermark" | "edge-to-edge white margin, no text on page" |
| "no scary teeth" | "gentle closed-mouth expression" |
| "no busy pattern across belly" | "the belly is mostly white breathing space" |

**Citations:**
- [aiphotogenerator.net — Negative prompts explained (2026)](https://www.aiphotogenerator.net/blog/2026/02/negative-prompts-stable-diffusion-guide)
- [Towards AGI — How to write negative prompts in FLUX](https://medium.com/towards-agi/how-to-write-negative-prompts-in-flux-e4305c9e7333)
- [VSF: Value Sign Flip negative-guidance paper (arXiv 2508.10931)](https://arxiv.org/html/2508.10931v1)

**→ Engine rule (R2):** trim the engine_negatives tuple from 56 to ~10
hard-fail terms (watermark, signature, photorealism, anatomically wrong
limbs — items we already know mflux honors). Move every "no X" rule
into the positive prompt as a "do Y" rule. Update `build()` to emit
positive-phrased rules only.

## 1.4 Guidance scale empirics

Two convergent recommendations from the FLUX community:

- **Drawings / paintings / line art**: guidance scale **3.5–6.0**
- **Photorealism**: guidance scale **2.5–3.5**
- **Strict-prompt-adherence (artistic)**: guidance scale **6.0–12**, with
  diminishing returns past 8.

Tensor.art and Andreas Kuhr's guides both note that very high guidance
can over-saturate or "burn" the image but rarely produces obvious
artifacts up to ~15 in FLUX-dev.

For coloring book pages specifically, we want strict adherence to
"black ink on white paper, no color" and to specific compositional
directives — that pushes us toward the upper end.

**Citations:**
- [Tensor.Art — FLUX guidance scales beginner's guide](https://tensor.art/articles/786949583562559346)
- [Andreas Kuhr — FLUX AI guide settings](https://andreaskuhr.com/en/flux-ai-guide.html)

**→ Engine rule:** default guidance lifted to **6.5–7.0** (was 5.5). For
strict-style enforcement on tricky pages allow `--guidance 7.5–8.0`. For
playful kid scenes where over-fidelity makes them stiff, drop to 5.5.

## 1.5 Step count

Practical FLUX-dev step settings from the community:

- **FLUX-dev**: 24–32 steps typical, 28 a common sweet spot
- **FLUX-schnell**: 2–4 steps (intended for that range)
- **Push to 36–40 for detail-critical work** (no further improvement past
  ~40 in most cases)

For coloring book line art, the bottleneck is composition not detail; we
want enough steps that line endpoints close cleanly. 32 is a good default,
36 for extreme zentangle complexity.

**→ Engine rule:** `default_runtime` keeps `steps: 32`. `--draft` (schnell
@ 4 steps) is the preview mode. `--ultra-res` should bump to 36 steps.

## 1.6 The coloring-book LoRA ecosystem

Two production-grade FLUX-dev LoRAs trained for coloring-book line art:

- **`prithivMLmods/Coloring-Book-Flux-LoRA`** — trigger word `"Coloring
  Book"` placed at the start of the prompt. Trained on 10 high-res
  hand-curated images. Optimal at 1024×1024. Open-weights on HuggingFace.
- **`renderartist/coloringbookflux`** — trigger word `"c0l0ringb00k"` or
  `"coloring book"`. Trained on a 100-image synthetic dataset of humans,
  vehicles, animals. **Recommended sampler: DEIS.** Open-weights on
  HuggingFace.

Both are well-suited to our engine. Neither is perfect on every subject;
both benefit from the engine's structural prompt scaffolding (the LoRA
handles "make it line-art", the engine handles "compose the scene
according to the tradition's craft principles").

**Citations:**
- [prithivMLmods/Coloring-Book-Flux-LoRA (HF)](https://huggingface.co/prithivMLmods/Coloring-Book-Flux-LoRA)
- [renderartist/coloringbookflux (HF)](https://huggingface.co/renderartist/coloringbookflux)

**→ Engine rule:** document both LoRAs in `brand/loras/README.md` with
HF download instructions. Add a `--coloring-book-lora` shortcut that
auto-applies the prithivMLmods LoRA at weight 0.8 and prepends the
trigger word to the SUBJECT block.

---

# Part 2 — The coloring-book design canon

Adult-coloring-book design is a real, sixty-year discipline. Children's
coloring is its younger sibling with extra constraints (large regions,
forgiving line weights). Both inherit from the same core principles.

## 2.1 Johanna Basford — Secret Garden (2013) and the modern adult-coloring revival

Basford's *Secret Garden* (Laurence King, 2013) sold over **22 million
copies** worldwide and is widely cited as having started the modern
adult-coloring trend. The design vocabulary established by that book and
its sequels (*Enchanted Forest* 2015, *Lost Ocean* 2015, *Magical
Jungle* 2016, *World of Flowers* 2018, *Ivy and the Inky Butterfly*
2017):

- **Hand-drawn pen-and-ink only.** No vector tools. The variation in
  line weight comes from the human hand, not from a brush palette.
- **Themed-environment scenes.** Each page is a coherent place — a
  walled garden, an underwater grotto, a forest clearing — not a
  random ornament.
- **Hidden objects to find.** Small animals, words, butterflies tucked
  into the foliage. Pages reward re-reading.
- **Intricate but not maximal.** Even at peak density Basford leaves
  white space; the page is never crushed.
- **Plant and animal taxonomy is accurate.** Real flowers, real
  fish, real birds. The naturalism grounds the fantasy.

**Citations:**
- [Johanna Basford — Secret Garden (publisher page)](https://www.johannabasford.com/book/secret-garden/)
- [Secret Garden Wikipedia entry](https://en.wikipedia.org/wiki/Secret_Garden:_An_Inky_Treasure_Hunt_and_Colouring_Book)

**→ Engine rule:** when the user asks for an ornamental-adult-grade
page (tradition = `johanna-basford-naturalistic` — a tradition we'll
add as part of this delivery), force `density=rich`, encourage
themed-environment composition, include a "hidden objects" optional
flag. Anatomical and botanical accuracy is required.

## 2.2 The Zentangle method — Rick Roberts & Maria Thomas (2003)

The Zentangle method, developed by Maria Thomas (calligrapher) and Rick
Roberts (meditation practitioner) in Whitinsville, Massachusetts in
2003, codifies the discipline of pattern-fill drawing:

- **Tangles** — small repeating structured patterns built from dots,
  lines, curves, S-curves, and orbs.
- **Drawn one small section at a time**, no advance planning.
- **"Elegance of limits"** — paradoxically, structure enables creativity.
- **Every closed region gets one pattern**, never a mix.
- **Pattern density is uniform within a region**, but density varies
  *between* regions.

This is the operational manual for "how do you fill an ornamental shape
with line work that reads as decoration, not as shading?". Every
high-density coloring page on the market (Basford, mandala-coloring,
zentangle animals) descends from this discipline.

**Citations:**
- [How Zentangle began (Zentangle.com)](https://zentangle.com/pages/how-did-zentangle-begin)
- [Zentangle Primer Vol. 1 — Thomas & Roberts (Amazon)](https://www.amazon.com/Zentangle-Primer-Vol-Rick-Roberts/dp/0985961459)
- [A Video Conversation With Zentangle Co-Founders — TanglePatterns.com](https://tanglepatterns.com/2022/06/a-video-conversation-with-zentangle-co-founders-rick-and-maria.html)

**→ Engine rule:** the engine's "DRAWING STYLE" block (in the
`mandala-art` engine, applicable also to densely ornamented
children's-book pages) names a *finite pattern vocabulary*: 3–5
systems chosen from {scales, ribbons, spirals, dots, wave geometry,
leaf veins, crosshatch, honeycomb}. Each closed region carries one
pattern from the vocabulary. Patterns *between* regions are different;
patterns *within* a region are consistent.

## 2.3 The 60/30/10 ornamental primer

Rohan provided the operational primer for ornamental-grade pages on
2026-05-17. Summarised:

- **60%** of the canvas is calm whitespace or low-detail breathing
  zones.
- **30%** is medium-detail ornamental structure.
- **10%** is hero-detail, concentrated in 1 primary + 2 secondary focal
  points (the eye, the forehead, the tail tip).
- **Line weight forms a 5-level hierarchy**: silhouette (thickest) →
  anatomy → ribbons → patterns → micro-detail (finest).
- **Patterns flow along anatomy**, not across.
- **The viewer reads SUBJECT first, decoration second.** A whale should
  read as a whale at 150-px thumbnail before the patterns register.

This is consistent with Basford's published method (which prefers
themed environment with deliberate negative space) and Zentangle's
within-region uniformity / between-region variation.

**→ Engine rule:** the engine's prompt template makes the 60/30/10
spatial directive concrete (not abstract). Use language like *"the
belly stays mostly white"* rather than *"60% breathing zones"*. FLUX
responds to concrete spatial instructions; it ignores abstract
percentages. The current children's-coloring-book engine's
"LINE-ART RULES" block needs the same restructuring; see Part 6.

## 2.4 Print specifications — industry standards

For a coloring book to actually print well (home printer or
Amazon KDP), there are non-negotiable specs:

| Spec | Value | Source |
|---|---|---|
| Page size — Amazon KDP standard | 8.5 × 11" (US Letter) | KDP guidelines |
| Square alternative | 8.5 × 8.5" | KDP supports; popular niche |
| Travel size | 6 × 9" | KDP supports |
| Resolution — minimum | 300 DPI | All print services |
| Resolution — line art preferred | 600 DPI | Line art needs higher to avoid jaggies |
| Bleed | 0.125" (3.175 mm) all sides | KDP requirement for full-bleed |
| Safety margin | 0.5" (12.7 mm) from trim | Keeps content from cropping |
| Paper weight (kids/adult crayons) | 100–120 gsm uncoated | Industry standard |
| Paper weight (markers/gel) | 140–160 gsm uncoated | Reduces bleed-through |
| Outline line weight (kids) | 1.5–3 pt at 8.5×11" output | Forgiving thicker is better |

**Citations:**
- [PrintNinja — Coloring book industry standards](https://printninja.com/printing-resource-center/book-game-industry-standards/workbook-standards/coloring-books/)
- [XinyiPrint — Coloring book sizes explained](https://xinyiprint.com/coloring-book-sizes/)
- [Bookmobile — Coloring book printing how-to](https://www.bookmobile.com/kickstarter-and-crowdfunded/coloring-book-printing-a-how-to/)
- [RASPIEE — Adult coloring book PDF printing guide](https://raspiee.com/blogs/news/ultimate-guide-to-printing-adult-coloring-book-pdfs-paper-settings-tips)

**→ Engine rule (R6):** add a `--page-format` flag to `forge engine
render` with values `a4-portrait`, `a4-landscape`, `letter-portrait`,
`square-8x8`. Default page format defaults to `letter-portrait` for
the `childrens-coloring-book` engine (`landscape-1280×720` for the
other engines). Pixel dimensions at 300 DPI:

| Format | Inches | Pixels @ 300 DPI |
|---|---|---|
| `letter-portrait` | 8.5 × 11 | 2550 × 3300 |
| `letter-landscape` | 11 × 8.5 | 3300 × 2550 |
| `a4-portrait` | 8.27 × 11.69 | 2480 × 3508 |
| `a4-landscape` | 11.69 × 8.27 | 3508 × 2480 |
| `square-8x8` | 8.5 × 8.5 | 2550 × 2550 |

## 2.5 Region size & motor-skill mapping

The crayon-grasp developmental literature gives us a hard answer for
"how small can a fillable region be before it's frustrating to color
in?".

| Age | Typical grasp | Recommended minimum region width | Source |
|---|---|---|---|
| 1.5–2.5y | Cylindrical / palmar | ~40 mm | OT literature; below this, the toddler smears outside |
| 2.5–3.5y | Digital pronate | ~30 mm | Common toddler crayon spans 10–12 mm; need 2–3× that |
| 3.5–4y | Quadrupod / static tripod | ~20 mm | Beginning of fine control |
| 4–6y | Dynamic tripod | ~12 mm | Adult-style grip emerging |
| 6–9y | Mature dynamic tripod | ~8 mm | Pincer refinement |
| 10–12y | Refined pincer | ~4 mm | Adult-equivalent |

**Citations:**
- [Wonderland Kids — Motor milestones: crayon to pencil grasp](https://wonderlandkids.org/crayon-to-pencil-grasp/)
- [Mister Smith Learning — Coloring and crayon grasp for preschoolers](https://www.mistersmithlearning.com/mister-smiths-blog/2018/2/11/coloring-and-crayon-grasp-for-preschoolers)
- [The OT Toolbox — How to teach coloring skills](https://www.theottoolbox.com/how-to-teach-coloring-skills/)

**→ Engine rule (R4):** the engine's `age_range` enum values carry
operational region-size minimums:

```python
"toddler-3-5"   → min_region_mm = 30, max_named_elements = 5
"kids-6-9"      → min_region_mm = 8,  max_named_elements = 10
"pre-teen-10-12"→ min_region_mm = 4,  max_named_elements = 20
```

These are injected into the engine's prompt body and into the audit
sidecar so reviewers can verify each preset honors them.

---

# Part 3 — Six children's-illustration traditions

Each of the six traditions encoded in the engine is a real, deliberate
craft with its own visual language. The engine treats them as
independent value-sets in `_CB_TRADITION`. This section codifies what
makes each tradition that tradition.

## 3.1 Mo Willems — minimalism (Elephant & Piggie series, 2007–2017)

Mo Willems is the most-cited contemporary picture-book illustrator and
the standard-bearer of expressive-minimalism. His own articulation:

> The simpler the drawing, the more expressive it has to be. The idea
> is to focus on the words and the body language of the characters.
> Everything else is superfluous. (Mo Willems, in multiple craft
> interviews)

The Elephant & Piggie original art lives at the Eric Carle Museum of
Picture Book Art (Amherst, MA). Examining the original line art:

- 12–20 total strokes per character pose.
- Two-dot pupils; eye shape carries 80% of the emotional signal.
- Mouth as a single curve, oval, or zigzag.
- No interior shading anywhere. No texture. No background detail
  unless the gag requires it.
- Body forms as smooth closed curves; no anatomical detail.
- Generous white space; the figure occupies the centre 40–60% of the
  spread.

**Citations:**
- [Mo Willems & the Artistic Process — ContentMeant](https://www.contentmeant.biz/mo-willems-and-the-artistic-process/)
- [Elephant & Piggie in WE ARE ART! — Carle Museum exhibition](https://carlemuseum.org/explore-art/exhibitions/traveling/elephant-piggie-we-are-art-mo-willems-exhibition)
- [Mo Willems Author Study — Writing Styles (Weebly)](https://mowillemsauthorstudypage.weebly.com/writing-styles.html)

**→ Engine rule:** `tradition=mo-willems-minimal` description names
the 12–20-stroke total, two-dot eyes, single-curve mouth, generous
white space. Pairs naturally with `density=sparse` and `age_range=
toddler-3-5` or `kids-6-9`. Conflicts with `density=rich`.

## 3.2 Sandra Boynton — whimsical chunky (Moo Baa La La La, 1982; The Going to Bed Book, 1982)

Boynton (Princeton MFA, Atlantic Monthly designer) established the
"alternative" picture-book and greeting-card visual style in the
1980s. Distinguishing features:

- Animals with **oversized rounded heads on smaller rounded bodies**
  — hippos, pigs, cows, dinosaurs, ducks, sheep, turkeys, dogs.
- **Pun and rhyme-driven text** that the illustration supports rather
  than competes with.
- Eyes as small dots or beans; mouth as one of three or four standard
  shapes.
- Strong silhouette: every character is identifiable from outline alone.
- Repetition: the same character pose is reused across many books.

**Citations:**
- [Sandra Boynton (Wikipedia)](https://en.wikipedia.org/wiki/Sandra_Boynton)
- [Sandra Boynton — Pennsylvania Center for the Book](https://pabook.libraries.psu.edu/literary-cultural-heritage-map-pa/bios/boynton_sandra)
- [Publishers Weekly — Books by Sandra Boynton](https://www.publishersweekly.com/pw/authorpage/sandra-boynton.html)

**→ Engine rule:** `tradition=sandra-boynton-whimsical` description
explicitly calls for "oversized rounded head, smaller rounded body,
bean/dot eyes, single-curve mouth, simple silhouette, rhythmic
repeatable pose". Pairs naturally with rhyme-friendly subjects
(animals doing one comically-simple thing).

## 3.3 Eric Carle — bold-outline tissue-paper collage (The Very Hungry Caterpillar, 1969)

Eric Carle's signature look comes from a specific physical technique
that we want to render as line art:

- He **painted acrylic on white tissue paper**, building up textured
  colour fields.
- Then **cut shapes from the painted tissue** and assembled collages
  on illustration board.
- Each painted-tissue piece is its own abstract field.
- The **bold outlines** in the final art are not drawn — they are the
  *edges of the cut shapes*. That's why Carle outlines are so confident
  and uniformly thick.
- He filed his painted tissues by colour for fast composition.

For our engine's purposes, what we want to inherit is: thick uniform
outlines, simple cut-shape geometric body forms (oval body, circular
head, segmented insect forms), and large fillable regions that
correspond to where a colour-field would have been pasted.

**Citations:**
- [Eric Carle's Artistic Process — Carle Museum](https://carlemuseum.org/about/about-eric-carle/artistic-process)
- [Eric Carle Obituary — Artnet News (2021)](https://news.artnet.com/art-world/eric-carle-obituary-1973806)
- [Making of The Very Hungry Caterpillar — Penguin](https://www.penguin.co.uk/discover/articles/making-eric-carle-very-hungry-caterpillar-story-behind)
- [Eric Carle's artistic style — ABTC](https://abtc.ng/eric-carles-artistic-style-techniques-mediums-and-his-use-of-tissue-paper/)

**→ Engine rule:** `tradition=eric-carle-bold` description specifies
"thick uniform outlines (1.5–2 pt at 8.5×11"), simple geometric body
shapes (oval body + round head + segmented insect forms), large
fillable color fields, max ~8–12 named objects per spread". Pairs
strongly with `age_range=toddler-3-5` and `density=sparse`.

## 3.4 Beatrix Potter — pen-and-ink + watercolour naturalism (The Tale of Peter Rabbit, 1902)

Potter is the founding voice of naturalistic small-animal picture
books. Her process documented from her surviving manuscripts:

- **Begin with a light graphite pencil sketch** on watercolour paper,
  drawing from real-life observation (Potter studied her subjects from
  taxidermied specimens and live pets).
- **Pen-and-ink line work** over the pencil — fine technical-pen line,
  not modulated. She developed a "fine dry-brush technique" for
  natural-history work.
- **Thin watercolour washes** over the ink. The line stays visible
  underneath.
- Her **scientific-illustration background** (mycology, accepted by
  scientists at her time for the precision of her fungus paintings)
  drives the anatomy: every rabbit ear, every fox whisker, every
  hedgehog spine in the correct place.
- **Anthropomorphism through clothing**: human waistcoats and bonnets
  on anatomically-correct mammals.

For coloring-book purposes we want the **pen-and-ink line work**: fine,
accurate, naturalistic anatomy, with the watercolour washes left as
unfilled regions for the colorist to supply.

**Citations:**
- [Beatrix Potter — Illustration History](https://www.illustrationhistory.org/artists/beatrix-potter)
- [Beatrix Potter: Illustrator and Inspiration — Lizzie Harper](https://lizzieharper.co.uk/2022/11/beatrix-potter-illustrator-and-inspiration/)
- [Beatrix Potter's Artistic Book Illustration — Victorian Web](https://victorianweb.org/art/illustration/potter/golden.html)
- [Tracing Beatrix Potter's Artistic Evolution — Hyperallergic](https://hyperallergic.com/tracing-beatrix-potters-artistic-evolution-from-fungi-to-peter-rabbit/)

**→ Engine rule:** `tradition=beatrix-potter-naturalistic` description
calls for "fine technical-pen line (not modulated), anatomically
correct small-mammal forms (rabbit/squirrel/mouse/hedgehog),
human-domestic clothing (waistcoat / bonnet / apron / scarf),
countryside cottage/garden setting". Pairs with `age_range=kids-6-9`
and `density=balanced`.

## 3.5 Hayao Miyazaki — storyboard / ekonte (Totoro 1988, Spirited Away 2001)

Miyazaki's ekonte (絵コンテ, lit. "picture-storyboard") is the medium
he uses for *both* script-writing and visual direction. The technique:

- **Watercolours with a bold pencil/brush line** — clean confident
  outline first, gentle tonal washes second.
- **Storyboards stand as finished art** in their own right; the
  Ghibli Museum publishes Miyazaki's ekonte volumes as art books.
- **Environmental detail rendered in restrained line** — cloud edges,
  leaf clusters, wood grain — never as shading.
- **Expressive but grounded faces**. Not chibi, not manga-giant-eye.
  Eyes are realistic-proportion ovals with simple round pupils.
- **Spirits, creatures, and forest entities** rendered with the same
  physical conventions as human characters; the magic lives in their
  *behaviour*, not in distorted anatomy.
- **Wide-shot environments** dominate; characters often occupy <25%
  of frame.

Of our six traditions this is the highest-density / oldest-target. For
pre-teen colorists it's a workout but rewarding.

**Citations:**
- [What are Storyboards or Ekonte? — Discover Ghibli](https://discoverghibli.com/what-are-storyboards-or-ekonte/)
- [Hayao Miyazaki's Drawing and Watercolor Technique — Fanboys Anonymous](https://www.fanboysanonymous.com/2015/01/hayao-miyazakis-drawing-and-watercolor.html)
- [Episode 19 — Storyboarding with Studio Ghibli (SAD HILL MEDIA)](http://sadhillmedia.com/filmformally/2020/5/3/episode-19-storyboarding-with-ghibli)
- [Studio Ghibli Layout Designs — Claire Mead](https://clairemead.com/2015/02/26/studio-ghibli-layout-designs-understanding-the-secrets-of-takahatamiyazaki-animation-at-musee-art-ludique/)

**→ Engine rule:** `tradition=miyazaki-storyboard` description names
"clean confident pen-line, expressive but realistic-proportion faces
(NOT chibi, NOT manga giant eyes), environmental detail in restrained
line (cloud edges, leaf clusters, wood-grain hint), wide environment
dominating frame, spirit/creature characters plausibly inhabiting the
scene". Pairs with `age_range=pre-teen-10-12` and `density=rich`. Hard
invariant: forbidden with `age_range=toddler-3-5` (line density too
fine).

## 3.6 Hanna-Barbera — flat-cel limited animation (The Flintstones 1960, Yogi Bear 1958)

The Hanna-Barbera house style was born of cost optimisation but became
its own distinctive design language:

> Hanna-Barbera kept production costs at a minimum. Instead of making
> twenty or thirty thousand drawings, a planned or "limited" cartoon
> only used 2 or 3 thousand drawings. (Wikipedia, Limited animation)

The visual conventions:

- **Geometric body shapes** — oval torsos, pill-shaped limbs, circular
  heads.
- **Strong silhouettes** — every character is recognisable from outline
  alone.
- **Characters broken into separable levels** — head, mouth, arm — so
  only what moves needs to be redrawn. This produces the signature
  *flatness* of the still frames.
- **Uniform medium-weight outline** around every form, no thick-to-thin
  modulation.
- **HB-signature eyes**: white sclera + single round black pupil. Not
  Mo-Willems two-dot. Not manga-sparkle. The HB eye is the species
  identifier of the style.
- **Mouths as simple curves** that change per frame.
- **Static poses with maximum personality** — design over animation.

**Citations:**
- [Hanna-Barbera (Wikipedia)](https://en.wikipedia.org/wiki/Hanna-Barbera)
- [Limited animation (Wikipedia)](https://en.wikipedia.org/wiki/Limited_animation)
- [How to Draw Retro Cartoon Characters — RetroSupply Co. tutorial](https://www.retrosupply.co/blogs/tutorials/1960s-cartoon-tutorial)
- [Hanna-Barbera Essays — Bill Burnett](https://billburnett.wordpress.com/hanna-barbera-essays/)

**→ Engine rule:** `tradition=hanna-barbera-flat-cartoon` description
names "uniform medium-weight outlines, geometric body shapes (oval
torsos, pill limbs, circular heads), strong silhouettes, HB-signature
eyes (white sclera + single round black pupil, NOT two-dot Mo Willems,
NOT manga giant-eye sparkle), simple-curve mouths, flat closed-shape
fills". Pairs across all three age ranges.

---

# Part 4 — Age-appropriate complexity (Piaget + motor-skill bands)

Picture-book illustration that serves the child's developmental stage
is more effective. The Piaget framework gives us the cognitive band;
the motor-skill literature gives us the fine-control band.

## 4.1 Piaget's four stages — relevant subset

The two stages relevant to coloring books:

- **Preoperational stage (2–7 years).** Symbolic / pretend / make-believe.
  Egocentric — child sees the world from their own perspective. Cannot
  yet reliably hold conservation, multiple-step reversibility, or
  classify hierarchically. Concrete subjects only — cannot abstract
  "transportation" but understands "the truck".
- **Concrete operational stage (7–11 years).** Logical thinking with
  concrete objects. Conservation, classification, reversibility. Can
  follow multi-step narrative. Begins to plan colour palettes
  intentionally rather than reactively.

There's also the early **formal operational** (11+ years), where
abstract thinking emerges. Our pre-teen-10-12 tier sits at this
transition.

**Citations:**
- [Saul McLeod — Piaget's Theory & Stages of Cognitive Development (Simply Psychology)](https://www.simplypsychology.org/piaget.html)
- [Piaget Cognitive Stages of Development (WebMD)](https://www.webmd.com/children/piaget-stages-of-development)
- [The Education Hub — Piaget's theory of education](https://theeducationhub.org.nz/piagets-theory-of-education/)

## 4.2 The grasp-development → minimum-region-size table

From the OT literature (see Part 2.5), summarised in operational form:

| Age band | Grasp tier | Min region width | Max named elements | Recommended traditions |
|---|---|---|---|---|
| 3–5 (preoperational) | Cylindrical / digital pronate | ≥30 mm | ≤5 | Mo Willems · Boynton · Carle |
| 6–9 (concrete operational) | Quadrupod / modified tripod | ≥8 mm | ≤10 | Willems · Boynton · Carle · Potter · HB |
| 10–12 (late concrete / early formal) | Mature tripod / refined pincer | ≥4 mm | ≤20 | All six traditions, including Miyazaki |

**→ Engine rule (R4):** the existing toddler-3-5 / kids-6-9 / pre-teen
enum values are already aligned with this. Reinforce the prompt body to
echo the minimum region width: e.g. for toddler, "every fillable region
is at least 30 mm equivalent across (toddler crayons can't cover small
areas)".

## 4.3 Single illustration per page improves comprehension (+32.86%)

This is the **single most important empirical anchor** in the document.

Eng, Godwin & Fisher (*npj Science of Learning*, 2020) ran a
within-subjects eye-tracking study on 60 first- and second-graders.
The same beginning-reader book was presented in two conditions:

- **Standard** — the commercial book with its illustrations as-printed.
- **Streamlined** — the same book with "extraneous illustration details"
  removed (details unrelated to the named story). Adult judges
  identified the extraneous details via a calibration study; >90%
  agreement threshold required.

Results:

- Children in the streamlined condition scored **32.86% higher** on
  comprehension assessments.
- Eye-tracking showed substantially more **gaze shifts away from text**
  in the standard condition (attentional competition).
- "Fixations toward extraneous details accounted for unique variance
  in reading comprehension controlling for reading proficiency."

The authors explicitly state they are **not advocating for the removal
of illustrations**, but rather that visual elements should serve a
clear story purpose.

**Citation:**
- [Eng, C. M., Godwin, K. E. & Fisher, A. V. (2020). Keep it simple: streamlining book illustrations improves attention and comprehension in beginning readers. *npj Science of Learning* 5:14. doi:10.1038/s41539-020-00073-5](https://www.nature.com/articles/s41539-020-00073-5)
- [PMC mirror with full text](https://pmc.ncbi.nlm.nih.gov/articles/PMC7522290/)

**→ Engine rule (R3):** the engine prompt's "ENVIRONMENTAL DENSITY"
block must check whether any *named* element in the SUBJECT is
genuinely supporting the named NARRATIVE MOMENT. If not, the engine
should reject the configuration. Practical version: cap `max_named_
elements` per age tier as above (5 / 10 / 20). Auto-warn if SUBJECT
text names more elements than the cap allows.

---

# Part 5 — What this means for the Forge engine

Translating the canon into code changes. Every rule below references
the part above where it was justified.

## 5.1 New prompt template ordering

The current order is roughly:

1. B&W coloring-book framing
2. Subject + narrative
3. Character + emotion + setting
4. Composition
5. Tradition
6. Line-art rules

This ordering already follows R1 (subject early). The remaining work:

- **Move STYLE into block 2** (alongside SUBJECT) — currently it lands
  in block 5/6 which is past T5's strongest attention.
- **Convert every "no X" sentence in the LINE-ART RULES block into a
  positive "do Y" sentence** (R2).
- **Replace abstract spatial language ("60% breathing") with concrete
  spatial language ("the belly is mostly white")** — same principle
  R2 (positive instead of negative) applied to spatial directives.
- **Add age-tier-specific minimum-region language**: every prompt for
  `age_range=toddler-3-5` includes "every fillable region at least
  30 mm across".

## 5.2 Engine_negatives — trim from 56 to ~10

Keep only the negatives that mflux empirically respects (mflux passes
its own threshold-style guidance through, so some negatives do still
contribute). The 10 that survive:

1. `watermark`
2. `signature`
3. `text overlay`
4. `page number`
5. `photorealism`
6. `3D rendered`
7. `anatomically wrong limbs` (eg six-fingered hands)
8. `extra fingers`
9. `predatory bared teeth`
10. `gore / blood / violence`

Everything else gets converted to positive instruction in the prompt
body.

## 5.3 New traditions to add

After this research, the engine gains one new tradition to complete the
canon:

- **`johanna-basford-naturalistic`** — for ornamental-adult-grade pages
  in the Secret Garden / Lost Ocean register. High-density, themed
  environment, hidden objects, accurate plant/animal naturalism.

The six traditions become seven. All of them remain age-tier-flexible
within the limits codified in Part 4.

## 5.4 New flags on `forge engine render`

| Flag | Values | Effect | Source |
|---|---|---|---|
| `--page-format` | `letter-portrait` (default for kids book) · `letter-landscape` · `a4-portrait` · `a4-landscape` · `square-8x8` | Sets pixel dims at 300 DPI | R6 — Part 2.4 |
| `--coloring-book-lora` | flag | Auto-applies prithivMLmods LoRA @ 0.8 + prepends trigger word | Part 1.6 |
| `--include-hidden-objects N` | int | For Basford-tradition only; instructs the prompt to tuck N small surprises into the page | Part 2.1 |

## 5.5 New sub-command `forge engine compile-book`

```
forge engine compile-book \
  --pages coloring-aaji-aajoba-page1,coloring-aaji-aajoba-page2,...,page4 \
  --title "Aaji and Aajoba — A Texas Garden Story" \
  --subtitle "A Hanna-Barbera coloring book in five pages" \
  --author "..." \
  --page-format letter-portrait \
  --out ~/Pictures/aaji-aajoba-book.pdf
```

Reuses already-rendered PNGs from `~/Desktop/forge-test/engine-renders/
childrens-coloring-book/`. If a recipe's PNG doesn't exist at the
requested page format, renders it. Output: a print-ready PDF with:

- Title page (configurable from `--title`/`--subtitle`/`--author`)
- One illustration per page at the requested format
- 0.125" bleed and 0.5" safety margins observed
- Optional page numbers (off for kids coloring; on for adult coloring)

## 5.6 Validation checklist for every preset

Per the canon, every preset in the library must pass:

- [ ] **Thumbnail test (R5).** At 150 px wide the page still reads as
      its named subject.
- [ ] **Half-coloured test.** A user crayon-tests one figure; the
      composition still looks intentional with the other figures left
      uncolored.
- [ ] **Comprehension test (R3).** The named narrative moment is
      visible without text. No competing decoration.
- [ ] **Grasp test (R4).** Every fillable region meets the age-tier
      minimum width.
- [ ] **Print test (R6).** PNG @ 300 DPI at the requested page format,
      bleed and margins honored.

The first three are visual; the last two are computable from the PNG
and the directive sidecar.

---

# Part 6 — The 50-preset library

The preset library is the trained-on-it answer to "what kinds of pages
can the engine produce well right now?". Per the canon:

- **7 traditions** (Willems · Boynton · Carle · Potter · Miyazaki · HB ·
  Basford)
- **3 age tiers** (toddler · kids · pre-teen)
- **8 themes** (animals · daily-life · seasons · cultural-festivals ·
  nature · fantasy · transport · professions)

That's 168 possible cells. We pick 50 along these dimensions for good
spread:

- **20 toddler-3-5 presets** — heavy Boynton + Carle + Willems
- **20 kids-6-9 presets** — mix of all 7 traditions
- **10 pre-teen-10-12 presets** — heavier Miyazaki + Basford

The Aaji-Aajoba series (already in `library.json`) counts as 4
HB-tradition pre-teen-adjacent presets and stays. The full 50 will
extend the library cleanly.

Naming convention: `coloring-<age>-<theme>-<motif>`. Theme codes:

| Theme | Code | Example |
|---|---|---|
| Animals | `anml` | `coloring-toddler-anml-cat-yarn` |
| Daily life | `life` | `coloring-kids-life-breakfast` |
| Seasons | `seas` | `coloring-kids-seas-autumn-leaves` |
| Festival / cultural | `fest` | `coloring-kids-fest-diwali-diyas` |
| Nature | `natr` | `coloring-pretn-natr-tidepool` |
| Fantasy | `fant` | `coloring-pretn-fant-dragon-village` |
| Transport | `trns` | `coloring-toddler-trns-fire-truck` |
| Professions | `prof` | `coloring-kids-prof-veterinarian` |

The 50 are landed in `brand/prompts/library.json` in the next commit.
Each carries:
- `engine: "childrens-coloring-book"`
- explicit `tradition`, `age_range`, `density`, `narrative.moment`,
  `composition.character_count`, all set per the canon above
- a `subject` text that names every element on the page and complies
  with R3 (no extraneous detail)
- a `seed` chosen empirically from a best-of-4 sweep

---

# Bibliography

## Diffusion / FLUX prompt engineering
- [FLUX.1-dev token limits (HuggingFace discussion #43)](https://huggingface.co/black-forest-labs/FLUX.1-dev/discussions/43)
- [Boqiang Liang — FLUX.1-dev Encoders and Token Limitations (Medium)](https://medium.com/@lbq999/flux-1-dev-encoders-and-token-limitations-8631c179eaad)
- [Skywork — FLUX.1 prompting ultimate guide](https://skywork.ai/blog/flux-prompting-ultimate-guide-flux1-dev-schnell/)
- [getimg.ai — FLUX prompt pro tips and common mistakes](https://getimg.ai/blog/flux-1-prompt-guide-pro-tips-and-common-mistakes-to-avoid)
- [fal.ai — How to use FLUX](https://fal.ai/learn/tools/how-to-use-flux)
- [Andreas Kuhr — FLUX AI guide settings](https://andreaskuhr.com/en/flux-ai-guide.html)
- [Tensor.Art — FLUX guidance scales beginner's guide](https://tensor.art/articles/786949583562559346)
- [aiphotogenerator.net — Negative prompts explained (2026)](https://www.aiphotogenerator.net/blog/2026/02/negative-prompts-stable-diffusion-guide)
- [Towards AGI — How to write negative prompts in FLUX](https://medium.com/towards-agi/how-to-write-negative-prompts-in-flux-e4305c9e7333)
- [VSF: Value Sign Flip negative-guidance paper (arXiv 2508.10931)](https://arxiv.org/html/2508.10931v1)

## Coloring-book LoRAs
- [prithivMLmods/Coloring-Book-Flux-LoRA (HF)](https://huggingface.co/prithivMLmods/Coloring-Book-Flux-LoRA)
- [renderartist/coloringbookflux (HF)](https://huggingface.co/renderartist/coloringbookflux)

## Coloring-book design canon
- [Johanna Basford — Secret Garden (publisher)](https://www.johannabasford.com/book/secret-garden/)
- [Secret Garden (Wikipedia)](https://en.wikipedia.org/wiki/Secret_Garden:_An_Inky_Treasure_Hunt_and_Colouring_Book)
- [How Zentangle began (Zentangle.com)](https://zentangle.com/pages/how-did-zentangle-begin)
- [Zentangle Primer Vol. 1 — Thomas & Roberts](https://www.amazon.com/Zentangle-Primer-Vol-Rick-Roberts/dp/0985961459)
- [TanglePatterns — A Video Conversation With Zentangle Co-Founders](https://tanglepatterns.com/2022/06/a-video-conversation-with-zentangle-co-founders-rick-and-maria.html)

## Print specifications
- [PrintNinja — Coloring book industry standards](https://printninja.com/printing-resource-center/book-game-industry-standards/workbook-standards/coloring-books/)
- [XinyiPrint — Coloring book sizes explained](https://xinyiprint.com/coloring-book-sizes/)
- [Bookmobile — Coloring book printing how-to](https://www.bookmobile.com/kickstarter-and-crowdfunded/coloring-book-printing-a-how-to/)
- [RASPIEE — Adult coloring book PDF printing](https://raspiee.com/blogs/news/ultimate-guide-to-printing-adult-coloring-book-pdfs-paper-settings-tips)

## Six illustration traditions
- [Mo Willems & the Artistic Process — ContentMeant](https://www.contentmeant.biz/mo-willems-and-the-artistic-process/)
- [Elephant & Piggie at the Carle Museum](https://carlemuseum.org/explore-art/exhibitions/traveling/elephant-piggie-we-are-art-mo-willems-exhibition)
- [Sandra Boynton (Wikipedia)](https://en.wikipedia.org/wiki/Sandra_Boynton)
- [Sandra Boynton — Pennsylvania Center for the Book](https://pabook.libraries.psu.edu/literary-cultural-heritage-map-pa/bios/boynton_sandra)
- [Eric Carle's Artistic Process — Carle Museum](https://carlemuseum.org/about/about-eric-carle/artistic-process)
- [Making of The Very Hungry Caterpillar — Penguin](https://www.penguin.co.uk/discover/articles/making-eric-carle-very-hungry-caterpillar-story-behind)
- [Beatrix Potter — Illustration History](https://www.illustrationhistory.org/artists/beatrix-potter)
- [Beatrix Potter — Lizzie Harper](https://lizzieharper.co.uk/2022/11/beatrix-potter-illustrator-and-inspiration/)
- [What are Storyboards or Ekonte? — Discover Ghibli](https://discoverghibli.com/what-are-storyboards-or-ekonte/)
- [Hayao Miyazaki's Drawing & Watercolor Technique — Fanboys Anonymous](https://www.fanboysanonymous.com/2015/01/hayao-miyazakis-drawing-and-watercolor.html)
- [Hanna-Barbera (Wikipedia)](https://en.wikipedia.org/wiki/Hanna-Barbera)
- [Limited animation (Wikipedia)](https://en.wikipedia.org/wiki/Limited_animation)
- [RetroSupply — How to draw retro cartoon characters](https://www.retrosupply.co/blogs/tutorials/1960s-cartoon-tutorial)

## Developmental science
- [Saul McLeod — Piaget's Theory & Stages of Cognitive Development (Simply Psychology)](https://www.simplypsychology.org/piaget.html)
- [Piaget Cognitive Stages of Development (WebMD)](https://www.webmd.com/children/piaget-stages-of-development)
- [The Education Hub — Piaget's theory of education](https://theeducationhub.org.nz/piagets-theory-of-education/)
- [Wonderland Kids — Motor milestones: crayon to pencil grasp](https://wonderlandkids.org/crayon-to-pencil-grasp/)
- [Mister Smith Learning — Coloring and crayon grasp for preschoolers](https://www.mistersmithlearning.com/mister-smiths-blog/2018/2/11/coloring-and-crayon-grasp-for-preschoolers)
- [The OT Toolbox — How to teach coloring skills](https://www.theottoolbox.com/how-to-teach-coloring-skills/)

## Empirical reading-comprehension research
- [Eng, C. M., Godwin, K. E. & Fisher, A. V. (2020). Keep it simple: streamlining book illustrations improves attention and comprehension in beginning readers. *npj Science of Learning* 5:14. doi:10.1038/s41539-020-00073-5](https://www.nature.com/articles/s41539-020-00073-5)
- [PMC mirror](https://pmc.ncbi.nlm.nih.gov/articles/PMC7522290/)

## Internal — Forge artifacts
- `BACKLOG.md` (this repo) — full Forge feature status, 2026-05-17
- `bin/style_engines.py::ChildrensColoringBookEngine` — the engine under spec
- `brand/prompts/library.json` — preset library
- Rohan's ornamental-design primer (chat, 2026-05-17) — the 60/30/10 + line-weight hierarchy + focal-points spec; codified above in Part 2.3
