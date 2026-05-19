#!/bin/bash
# Indian Animals Madhubani T-shirts — v3 redraw.
#
# v3 fixes (after v2 regression review):
#
#   ENGINE-LEVEL (bin/style_engines.py, same commit):
#     A. ANATOMY FIRST contract — added as a top-level rule. v2 tiger lost
#        a foreleg; this is the prompt-level fix. "All four legs clearly
#        visible, overlapping legs as two distinct outlines."
#     B. ZONE CONFINEMENT clarifier added to the SEVEN ZONES block — fixes
#        the v2 snow-leopard "patterned-blob" failure. "Decoration confined
#        to seven zones; body between zones stays a clean color field."
#     C. FACE & EXPRESSION rule — fixes v2 macaque cartoon eyes. "Almond
#        eye, calm folk-icon presence, never round cartoon eyes."
#     D. NO SIGNATURE elevated from negative-list to positive top-level
#        constraint — fixes v2 cobra corner glyph.
#
#   SUBJECT-LEVEL (this script, below):
#     E. Tiger: walking → STANDING ALERT in side profile, all four legs
#        planted and visible (no walking-pose leg drop).
#     F. Cobra: open-mouth + tongue removed; CALM closed-mouth hood.
#     G. Snow leopard: rosettes-as-folk-panels CAPPED to 3-4 specific
#        zones; body remains clean color between them.
#     H. Elephant: saddle restraint — 2 colors max, restore v1's quieter
#        register without losing v2's body decoration.
#
#   RUNTIME:
#     I. --steps 24 (was 18) — adds ~30% per-image time but typically
#        resolves the residual anatomy/finger issues in FLUX dev.
#
# Seeds unchanged from v1/v2 (8101-8108) so v1 ↔ v2 ↔ v3 diffs are
# purely prompt-driven.

set -u
OUT=/Users/Rohan/Desktop/Forge/generated/indian_animals_madhubani_tshirts_v3
mkdir -p "$OUT"
cd /Users/Rohan/Desktop/Forge

PYBIN=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3
FORGE="$PYBIN bin/forge.py engine render minimalist-tshirt"

CONFIG="subject.motif=madhubani-folk-icon,style.tradition=madhubani-contemporary,style.detail=maximal-but-printable,style.symmetry=handmade-balanced,style.accents=micro-folk-dots,production.output=print-art,production.ink=vibrant-folk,production.shirt_color=cream-or-black,composition.placement=center-chest,composition.layout=single-mark,composition.background=no-background,composition.border=none"

START=$(date +%s)
echo "═══════════════════════════════════════════════════════════════════"
echo "  Indian Animals Madhubani T-shirts — v3 redraw"
echo "  start: $(date)"
echo "  out:   $OUT"
echo "  steps: 24 (was 18 in v1/v2)"
echo "═══════════════════════════════════════════════════════════════════"

run() {
  local idx="$1" name="$2" seed="$3" subject="$4"
  local file="$OUT/$(printf '%02d' "$idx")_${name}_madhubani_tshirt.png"
  local t0=$(date +%s)
  echo
  echo "── [$idx/8] $name  (seed=$seed)"
  $FORGE \
    --subject "$subject" \
    --config "$CONFIG" \
    --seed "$seed" \
    --steps 24 \
    --out "$file" 2>&1 | tail -20
  local rc=$?
  local t1=$(date +%s)
  echo "   → $file  (rc=$rc, this one $((t1-t0))s, total ${SECONDS}s)"
}

# ── 01. Tiger — STANDING alert, all 4 legs planted (was walking → lost a leg) ─
run 1 royal_bengal_tiger 8101 \
"single centered Royal Bengal tiger STANDING ALERT in complete full-body side profile facing right, premium Madhubani Mithila folk-art icon, all FOUR legs clearly visible and planted on the ground (near pair and far pair both fully drawn as distinct outlines, no leg hidden behind the body or saddle), strong shoulders and haunches, long curved tail held low, alert almond eye with dignified folk-icon expression, mouth closed, whisker dots, body filled with saturated walnut-brown decorated INSIDE with multi-color leaf-vein and fish-scale Madhubani panels translating the tiger stripes, ONE restrained decorated saddle-band of lotus and sun motifs across the back, anklet stripe-bands at every joint, bold black double-contour keylines, dotted Mithila ground line below all four paws, modern Indian streetwear"

# ── 02. Elephant — RESTRAINED saddle (v2 was too busy, restore v1 elegance) ──
run 2 indian_elephant 8102 \
"single centered Indian elephant in side profile facing right, premium Madhubani Mithila folk-art icon, graceful curved trunk, large decorated ear, calm almond eye with dignified folk-icon expression, small tusk, ceremonial bearing, all four legs clearly visible, body filled with saturated indigo, decoration RESTRAINED to a single ornamental saddle blanket in TWO colors maximum (saffron and cream-white with small vermillion accent only) plus subtle gold anklets and one lotus medallion on the ear, body between zones remains a clean indigo field with no all-over pattern, bold black double-contour keylines, dotted Mithila ground line below the feet, modern Indian streetwear"

# ── 03. Peacock — kept v2 subject (it worked); minor tail wording tweak ─────
run 3 indian_peacock 8103 \
"single centered Indian peacock standing in elegant side profile facing right, premium Madhubani Mithila folk-art icon, crested head, long elegant neck, alert almond eye with calm folk-icon expression, mouth closed, sturdy proportional legs and feet clearly visible, tail held in a graceful fanned-and-trailing curve with readable individual feather-eye motifs (NOT a triangular drape), body filled with saturated indigo and decorated INSIDE with three or four sparse folk panels, tail feathers rendered as multi-color folk eyes (saffron centers, leaf-green surrounds, vermillion outer rings), gold-yellow neck-band, cream and vermillion dots used as ornament not as all-over pattern, bold black double-contour keylines, small dotted ground line below the feet, modern Indian streetwear"

# ── 04. Blackbuck — kept v2 (worked well) ───────────────────────────────────
run 4 blackbuck 8104 \
"single centered Indian blackbuck antelope in side profile facing right, premium Madhubani Mithila folk-art icon, elegant spiral horns, slender neck, alert almond eye with calm folk-icon expression, mouth closed, white cheek patch as flat folk shape, all four legs clearly visible, body filled with saturated indigo and decorated INSIDE with a single sun-medallion at flank, restrained fish-scale band across the chest, saffron-orange dot-band across the back, vermillion hooves, body between zones stays a clean indigo field, bold black double-contour keylines, paired peepal-leaf ground sprigs below the hooves, modern Indian streetwear"

# ── 05. Rhino — kept v2 (best result; reference design) ─────────────────────
run 5 one_horned_rhinoceros 8105 \
"single centered Great Indian one-horned rhinoceros in side profile facing right, premium Madhubani Mithila folk-art icon, heavy armor plates simplified into folk panels, single nose horn, calm alert almond eye with dignified folk-icon expression, mouth closed, strong arched back, all four legs clearly visible, body filled with saturated indigo and decorated INSIDE with seven distinct zones of multi-color Madhubani ornament (lotus saddle, vermillion floral medallion at flank, gold-yellow dot-bands across armor plates, leaf-green vine at shoulder, anklets at every joint), body between zones stays a clean indigo field, bold black double-contour keylines, dotted Mithila ground line below the feet, modern Indian streetwear"

# ── 06. Cobra — CLOSED mouth, NO tongue, NO flame (v2 had double-tongue) ────
run 6 king_cobra 8106 \
"single centered Indian king cobra rearing with hood spread frontal-facing, body coiling in an elegant S-curve below, premium Madhubani Mithila folk-art icon, clear spectacle mark on hood, alert almond eyes with dignified folk-icon expression, MOUTH CLOSED in calm meditative posture, no tongue, no fangs, no flame, no decorative object near the mouth, hood filled with saturated indigo and decorated INSIDE with lotus petal panels in saffron and vermillion, fish-scale rows along the body in leaf-green and gold-yellow, cream-white ventral scales, body between zones remains clean, bold black double-contour keylines, small decorative platform of folk dots beneath the coiled base, clean negative space in all four corners, modern Indian streetwear"

# ── 07. Snow Leopard — rosettes as SPARSE medallions (was patterned blob) ───
run 7 snow_leopard 8107 \
"single centered Himalayan snow leopard STANDING ALERT in complete full-body side profile facing right, premium Madhubani Mithila folk-art icon, all FOUR legs clearly visible and planted (near and far pair both fully drawn as distinct outlines), flowing long tail held low and visible, rounded ears, alert almond eye with dignified folk-icon expression, mouth closed, powerful proportional paws, body filled with saturated walnut-brown or forest-teal, rosette markings translated into ONLY 4 or 5 SPARSE folk floral medallions placed at specific zones (one at shoulder, one at flank, one at hip, one at base of tail) with saffron centers and vermillion petals — NOT an all-over body pattern, NOT a fabric texture, the body BETWEEN these sparse medallions remains a clean saturated color field, additional restraint: one decorated saddle-band across the back, gold-yellow neck-band, dotted anklets, bold black double-contour keylines, paired peepal-leaf ground sprigs below the paws, modern Indian streetwear"

# ── 08. Macaque — calm folk-icon face, NOT cartoon eyes ─────────────────────
run 8 lion_tailed_macaque 8108 \
"single centered lion-tailed macaque from the Western Ghats seated calmly in side profile facing right, premium Madhubani Mithila folk-art icon, signature silver mane halo around the dark face translated into a radiant folk sunburst (cream-white and gold-yellow rays with vermillion tips), CALM ALMOND EYE with dignified folk-icon expression (NOT round cartoon eyes, NOT wide surprised eyes, NOT comic book eyes), mouth closed in serene contemplative posture, curved tail with leaf-shaped tuft visible, hands gently folded, body filled with saturated indigo and decorated INSIDE with one chest medallion plus a sparse leaf-vein band on the limbs — NOT an all-over pattern, body between decorated zones remains a clean indigo field, bold black double-contour keylines, small dotted ground line and a peepal-leaf sprig beside the figure, modern Indian streetwear"

END=$(date +%s)
echo
echo "═══════════════════════════════════════════════════════════════════"
echo "  v3 redraw done at $(date)  (total $((END-START))s)"
echo "  outputs: $OUT"
echo "═══════════════════════════════════════════════════════════════════"
ls -la "$OUT" | grep -v '\.directive\.json$\|transparent\.png$'
