# Minimalist T-Shirt Design Engine

Created: 2026-05-18

## Goal

`minimalist-tshirt` is a Forge specialist engine for screen-printable apparel
graphics.

It is not a generic poster engine. It is built for designs that must survive:

- cotton/fabric context
- screen-print ink limits
- thumbnail browsing
- across-the-room readability
- later exact typography added outside the diffusion model

The engine prefers simple, production-safe marks over beautiful but unusable
illustrations.

## Command Surface

List engines:

```sh
forge engine list
```

Inspect the vocabulary:

```sh
forge engine describe minimalist-tshirt
```

List recipes:

```sh
forge engine recipes --engine minimalist-tshirt
```

Render from a recipe:

```sh
forge engine render --recipe tshirt-mountain-one-line --profile balanced
```

Render directly:

```sh
forge engine render minimalist-tshirt \
  --subject "a single continuous line drawing of a mountain ridge with a small rising sun" \
  --config "subject.motif=monoline-icon,production.output=print-art,production.ink=one-ink-black,production.shirt_color=natural-cream,composition.placement=center-chest,composition.layout=single-mark" \
  --profile balanced \
  --out ~/Pictures/tshirt-mountain.png
```

Exact beta minimalism, no diffusion uncertainty:

```sh
forge minimal-animal \
  --animal "alert tiger in side profile with a long tail" \
  --max-lines 8 \
  --out ~/Pictures/tiger-eight-line.png
```

Use this lane when the requirement is a hard stroke budget. It writes SVG/PNG,
QC, and manifest receipts; see `docs/MINIMAL_ANIMAL_LINES.md`.

For fast batches, keep the canvas square but lower the diffusion pass:

```sh
forge engine render minimalist-tshirt \
  --subject "single centered Indian elephant in full-body side profile, Madhubani folk T-shirt mark" \
  --config "subject.motif=madhubani-folk-icon,style.tradition=madhubani-contemporary,style.detail=maximal-but-printable,style.symmetry=handmade-balanced,style.accents=micro-folk-dots,production.output=print-art,production.ink=vibrant-folk,production.shirt_color=cream-or-black,composition.background=no-background,composition.border=none" \
  --profile balanced \
  --steps 14
```

## Engine Vocabulary

### Subject

| Knob | Values |
| --- | --- |
| `subject.motif` | `monoline-icon`, `geometric-silhouette`, `negative-space-symbol`, `madhubani-folk-icon`, `tiny-line-scene`, `retro-minimal-badge`, `abstract-type-safe` |
| `style.tradition` | `modern-minimal`, `madhubani-contemporary`, `madhubani-master-painter`, `warli-minimal`, `gond-minimal` |
| `style.detail` | `ultra-minimal`, `subtle-folk-detail`, `ornamental-balanced`, `maximal-but-printable` |
| `style.symmetry` | `none`, `handmade-balanced`, `near-bilateral` |
| `style.accents` | `none`, `small-floral-only`, `micro-folk-dots` |

### Production

| Knob | Values |
| --- | --- |
| `production.output` | `print-art`, `shirt-mockup` |
| `production.ink` | `one-ink-black`, `one-ink-white`, `two-ink-earth`, `two-ink-retro`, `tonal-on-tonal`, `three-ink-popti-red-black`, `vibrant-folk` |
| `production.shirt_color` | `white`, `black`, `natural-cream`, `heather-grey`, `navy`, `forest-green`, `cream-or-black` |

### Composition

| Knob | Values |
| --- | --- |
| `composition.placement` | `center-chest`, `left-pocket`, `back-large` |
| `composition.layout` | `single-mark`, `icon-plus-caption-zone`, `circular-badge`, `stacked-symbols`, `repeat-mini-pattern` |
| `composition.background` | `no-background`, `transparent-feel` |
| `composition.border` | `none`, `hairline-badge` |

## Output Modes

### `print-art`

Use this when you want production artwork or a clean design candidate.

The engine asks for:

- flat artwork only
- plain high-contrast field
- no shirt mockup
- no model
- no fabric folds
- no hanger

This is the best mode for iteration and downstream vectorization.

### `shirt-mockup`

Use this when you want to preview placement on a blank tee.

The engine asks for:

- one blank shirt
- front-facing or clean flat-lay view
- design clearly printed in the requested placement
- no human model
- no store-rack or e-commerce clutter

## Design Contract

Every render should obey:

- One or two screen-print inks for minimalist designs; approved folk-art modes
  can use richer flat palettes when the design remains printable.
- No gradients.
- No photorealistic background scene.
- No tiny details that disappear at shirt scale.
- No fake typography or invented slogans.
- At least 70% empty or low-detail design area.
- Fewer than 12 major shapes.
- Strong silhouette readability.
- Negative space used as a design material.

## Text Policy

FLUX should not be trusted for exact shirt typography.

The engine intentionally tells the model:

- do not invent readable words
- do not generate slogans
- do not create fake brand names
- reserve a blank caption zone when text is needed

Exact text should be added later by Forge/PIL/vector tooling.

## Recipes

Current starter recipes:

| Recipe | Use |
| --- | --- |
| `tshirt-mountain-one-line` | One-line outdoor mountain mark |
| `tshirt-chai-club-pocket` | Tiny left-pocket chai icon mockup |
| `tshirt-tiger-negative-space` | Geometric tiger head with cutout stripes |
| `tshirt-lotus-tonal-badge` | Quiet tonal lotus badge on navy shirt |
| `tshirt-popti-parrot-madhubani` | Modern Madhubani-inspired popti green parrot print art |

## Quality Gates

A generated design passes only if:

- It reads at phone thumbnail size.
- It can be described in one phrase.
- The main subject is clear from silhouette.
- It uses one or two ink colors.
- No generated text appears unless it is intentionally blank/placeholder-like.
- It is not a poster, scene illustration, sticker sheet, or logo copy.
- Shirt mockups do not obscure the print with wrinkles or folds.

## Future Improvements

Recommended next steps:

- Add a deterministic PIL/SVG card that places exact typography below the FLUX
  mark.
- Add image-side checks for ink count and edge complexity.
- Add a vectorization handoff path for SVG cleanup.
- Add a `forge tshirt` wrapper once the engine proves stable.
- Add benchmark prompts and semantic tokens using
  [PRESET_PROMPT_TEMPLATE.md](PRESET_PROMPT_TEMPLATE.md).
