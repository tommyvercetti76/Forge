# Cultural-heritage attribution: Madhubani (Mithila) painting

Forge generates art inspired by the Madhubani painting tradition of the
Mithila region of Bihar, India. This document records, plainly and in
one place, what that tradition is, what Forge is and is not, and how the
project honors the people whose work made the style possible.

## The tradition

Madhubani painting — also known as Mithila painting — is a folk-art form
practiced for many centuries in the Mithila region (northern Bihar in
present-day India, and parts of southern Nepal). It is historically a
domestic art carried forward predominantly by women, painted on freshly
plastered village walls and floors during weddings, festivals, and rites
of passage, and more recently on paper, cloth, and canvas for sale.

The tradition is studied and produced in several distinct schools:

- **Bharni** — filled-color, the most widely recognized "ornate" look.
- **Kachni** — line-only, dense crosshatching with restrained color.
- **Tantric** — religious / iconographic subjects.
- **Godna** — tattoo-style, derived from body-marking patterns of
  Dalit communities of the region.
- **Gobar** — using cow-dung as a base ground, often by Dusadh artists.

The form was recognized in India by a Geographical Indication
registration (Madhubani painting / Mithila painting GI), which restricts
the use of the name "Madhubani painting" in commerce to producers from
the geographic region. Verify the exact GI title and year against the
official register if you are doing anything where that distinction
matters legally.

## What Forge is

Forge is a local-first generative-AI toolkit. The Madhubani engine in
Forge produces images that draw on the visual conventions of the
tradition — flat-color folk silhouettes, double-line black outlines,
walnut-brown body fills, fish-eye motifs, dense decoration zones,
indigo / vermillion / saffron / leaf-green palette, motif vocabulary
(lotus, peepal, sun, bird).

## What Forge is not

- Forge is **not** authentic Madhubani painting. The output of any
  generative model is a computational synthesis, not a hand-painted
  artifact produced by a practitioner trained in the tradition.
- Forge **does not** represent any practicing artist, cooperative, or
  community.
- Forge **does not** sell, broker, or otherwise transact art on behalf
  of any practitioner.
- Forge **does not** assert ownership of the visual vocabulary it draws
  on. That vocabulary belongs to the tradition.

## What Forge does to honor the tradition

- Every reference image used to ground prompts is sourced from
  open-licensed material on Wikimedia Commons, with the source URL,
  contributor, and license recorded in
  `brand/madhubani/references/attribution.json`. Binaries are gitignored;
  the manifest is committed so the corpus is reproducible and credited.
- The render pipeline cites the school (Bharni, Kachni, Tantric, Godna,
  Gobar) and the regional roots of the form in its directive output.
- The project is licensed MIT, but the FLUX models it builds on are
  non-commercial only (see `NOTICE`). Commercial use of any Madhubani
  imagery Forge produces requires both a commercial license from Black
  Forest Labs and a separate ethical consideration about commercializing
  derivatives of a folk tradition.

## What we ask of users

If you find this work meaningful and want authentic Madhubani painting,
**buy from practitioners**. Search for the Mithila Art Institute, the
Bihar State Mithila Arts Council, regional artisan cooperatives, and
named contemporary artists. A few well-known names whose work is in
museums and books include Sita Devi, Ganga Devi, Mahasundari Devi,
Baua Devi, and Dulari Devi. Many of their successors and students sell
directly.

If you publish, exhibit, or sell anything derived from Forge's Madhubani
engine, please credit the tradition explicitly ("inspired by the
Madhubani / Mithila tradition of Bihar, India") and link or reference
this document. Do not represent the output as authentic.

## Corrections

This document will be wrong in places. If you are a practitioner, scholar,
or community member and see something here that misrepresents the
tradition, please open an issue or email `rohanramekar17@gmail.com` and
the maintainer will fix it.
