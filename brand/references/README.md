# Reference images — visual targets for the engines

Drop curated reference images here. The engines aim to *produce* output
that matches these visual targets, and the descriptions in this README
expand on what each reference shows so engine prompts can name the
specifics in plain English.

When you save a new reference, give it a clear name that includes
both the tradition and a short tag (e.g. `madhubani-triple-deities.jpg`).

---

## Indian folk art baselines (2026-05-17)

Three baselines the `indian-classical` engine should be able to reach
when you pick the corresponding `style.tradition`. Save the source
files locally with the names below; the descriptions are written so
prompts can call out the matching features.

### `madhubani-triple-deities.png` — Madhubani triple-figure portrait

Three deity figures standing side-by-side in frieze composition. What
to call out in prompts:

- **HUGE eyes** — white sclera with oversized round black pupils that
  dominate every face (single biggest visual signature of Madhubani)
- **Double-line border** around every form (parallel inner contour
  along every outline)
- **Crowns / mukutas** — tall conical, stacked with multiple color
  registers, dot-rosette band, tip jewel
- **Tilak / bindi** marks on every forehead
- **Multi-strand pearl/bead malas** (garlands) cascading down the chest
- **Kundalas** (large round disc earrings), nose ring on female figures
- **Sari / dhoti with deeply decorated border patterns**, knot-belts
- **Peepal-leaf clusters** scattered as background motifs
- **Floral / geometric border bands** running along the canvas edges
- **6-7 color palette**: red + yellow + green + blue + orange + black
  on cream paper. Flat, no shading, no gradient.

### `warli-village-life.png` — Warli daily-life scene

Brown earth-ochre ground covered in white-rice-paste pigment. What to
call out:

- **Two-triangles-joined-at-apex** torsos (the Warli human-figure
  signature — point-up triangle on top of point-down triangle)
- **Small round head**, thin stick limbs, **NO facial detail**
- **Stick-figure animals**: cow, dog, deer, peacock, snake
- **Tree of life** with dense leaf clusters
- **Bullock cart** with circular wheels and yoked cattle
- **Spiral motifs** (snake or sacred-spiral)
- Repetitive small forms scattered across the surface — figures
  carrying baskets, walking between trees
- ONLY two colors: white pigment + brown ground

### `warli-tarpa-dance.png` — Warli festival composition

Same brown ground + white pigment, but with a symmetric ceremonial
composition. What to call out:

- **Central sacred-square chauk** (square containing a fine dotted
  texture, used for wedding/festival/ritual scenes)
- **Concentric tarpa dance ring** — stick-figure dancers holding
  hands in a circle around the chauk
- **Peacocks with circular eye-feathers** at corners (signature Warli
  bird, drawn as a rounded body with a swirling tail-feather disc)
- **Geometric pattern bands**: zigzag, dot-clusters, X-shaped lattices
- **Symmetric mirroring** across vertical axis
- Group scenes (line of dancers, animal pairs) layered above and
  below the central square

---

## How the engine uses these

The `indian-classical` engine in `bin/style_engines.py` exposes
matching enum values:

- `style.tradition = madhubani | warli | tanjore | pahari-miniature |
  ravi-varma-oleograph`
- `style.ground = madhubani-paper | warli-mud-wall | warli-tarpa-circle
  | temple-interior | forest-grove | river-bank-yamuna | cosmic-water |
  celestial-sky | village-pastoral`

The web wizard's **Indian folk art** action surfaces these as
dropdowns with a free-form subject textarea on top.
