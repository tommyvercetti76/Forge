# Minimal Animal Lines

Beta closed-loop engine for ultra-minimal animal T-shirt marks.

Goal: let someone describe an animal and produce a clean SVG/PNG mark using no
more than 8 visible stroke primitives. The guarantee is construction-based, not
pixel-guessed: Forge counts the SVG `<polyline>` strokes it emitted.

## Command

```sh
forge minimal-animal \
  --animal "alert tiger in side profile with a long tail" \
  --max-lines 8 \
  --out ~/Pictures/tiger-eight-line.png
```

Outputs:

```text
tiger-eight-line.png
tiger-eight-line.svg
tiger-eight-line.qc.json
tiger-eight-line.manifest.json
```

## Closed Loop

1. Interpret the animal description into a broad body class.
2. Construct a vector stroke plan with `line_count <= max_lines`.
3. Write SVG as the source of truth.
4. Render a PNG preview.
5. Run QC for line count, bounds, and no-fill contract.
6. Write a manifest with PASS/FAIL and artifact paths.

The PNG is just a preview. The SVG and QC are the authority.

## GPU Policy

This feature is procedural because exact line count cannot be guaranteed by a
diffusion model. It performs no CPU ML fallback. By default the CLI still runs a
Metal readiness guard so the surrounding T-shirt/Madhubani workflow cannot
silently degrade into CPU-only ML for FLUX renders. Use `--skip-gpu-check` only
for tests or documentation dry runs.

## Quality Bar

Automatic:

- `line_count <= max_lines`
- all stroke points are inside the normalized canvas
- no fills, gradients, text, signatures, or model-invented marks
- manifest status is `PASS`

Human review:

- the animal should read at shirt scale
- the mark should feel intentional, not like an accidental contour trace
- no stroke should be decorative filler just to reach 8 lines

## Current Body Classes

`elephant`, `rhino`, `big-cat`, `canine`, `deer`, `bird`, `fish`, `serpent`,
`turtle`, `insect`, `primate`, and generic `quadruped`.

If the description does not match a known class, Forge uses `quadruped` and still
writes the same QC/manifest receipts.
