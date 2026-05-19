#!/bin/bash
# Indian Animals Madhubani T-shirts — v2 redraw.
#
# Why v2 exists:
#   v1 (generated/indian_animals_madhubani_tshirts/) had a consistency problem:
#   only 2 of 8 designs (elephant, rhinoceros) actually rendered in the
#   six-color vibrant-folk palette demanded by the prompt. The other six
#   (tiger, peacock, blackbuck, cobra, snow-leopard, macaque) collapsed into
#   stark 2-tone silhouettes that looked like Western mascot logos rather
#   than Madhubani folk-art.
#
# Root cause:
#   The engine prompt was simultaneously asking for "Paul Rand / Saul Bass /
#   Swiss-grid minimalism" AND "seven-zone vibrant-folk density." With lean-
#   bodied predators the model picked the easier instruction (logo) and
#   abandoned the harder one (folk density).
#
# Fix (landed in bin/style_engines.py, same commit):
#   - Removed the Western design-logo masters from MinimalistTShirtEngine
#   - Promoted a COLOR FLOOR + BODY FILL OVERRIDE block to the top of the
#     prompt when motif=madhubani-folk-icon AND ink=vibrant-folk
#   - Replaced MINIMALISM CONTRACT with DENSITY CONTRACT in the vibrant-folk
#     path so the seven-zone block isn't competing with itself
#   - Added a GROUND MARK rule so quadrupeds anchor as folk icons
#   - Loaded new anti-mascot and anti-signature negatives
#
# Subject strings below have also been rewritten:
#   - "intricacy level 80 out of 100" removed (numeric scales don't help)
#   - tiger changed from HEAD to full-body side profile
#   - cobra explicitly anchored on a dot platform (it's coiled, no ground line)
#   - every subject now repeats "body filled with saturated indigo/walnut/
#     forest-teal and decorated INSIDE with multi-color Madhubani panels"
#     as a per-subject reinforcement of the engine-level COLOR FLOOR
#
# Seeds are kept the same as v1 (8101-8108) so a side-by-side comparison
# isolates the prompt change as the only variable.

set -u
OUT=/Users/Rohan/Desktop/Forge/generated/indian_animals_madhubani_tshirts_v2
mkdir -p "$OUT"
cd /Users/Rohan/Desktop/Forge

PYBIN=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3
FORGE="$PYBIN bin/forge.py engine render minimalist-tshirt"

CONFIG="subject.motif=madhubani-folk-icon,style.tradition=madhubani-contemporary,style.detail=maximal-but-printable,style.symmetry=handmade-balanced,style.accents=micro-folk-dots,production.output=print-art,production.ink=vibrant-folk,production.shirt_color=cream-or-black,composition.placement=center-chest,composition.layout=single-mark,composition.background=no-background,composition.border=none"

START=$(date +%s)
echo "═══════════════════════════════════════════════════════════════════"
echo "  Indian Animals Madhubani T-shirts — v2 redraw"
echo "  start: $(date)"
echo "  out:   $OUT"
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
    --out "$file" 2>&1 | tail -20
  local rc=$?
  local t1=$(date +%s)
  echo "   → $file  (rc=$rc, this one $((t1-t0))s, total ${SECONDS}s)"
}

# ── 01. Royal Bengal Tiger — full body, NOT mascot head ─────────────────
run 1 royal_bengal_tiger 8101 \
"single centered Royal Bengal tiger in complete full-body side profile walking calmly left to right, premium Madhubani Mithila folk-art icon, strong shoulders, four proportional muscular legs, long curved tail, almond eye, whisker dots, decorated saddle-band of lotus and sun motifs across the back, anklet stripe-bands at every joint, body filled with saturated walnut-brown or indigo and decorated INSIDE with multi-color leaf-vein and fish-scale Madhubani panels translating the tiger stripes, saffron and vermillion ornamental accents, bold black double-contour keylines, dotted Mithila ground line below the paws, modern Indian streetwear"

# ── 02. Indian Elephant — already great in v1, keep as reference ────────
run 2 indian_elephant 8102 \
"single centered Indian elephant in side profile, premium Madhubani Mithila folk-art icon, graceful curved trunk, large decorated ear, calm almond eye, small tusk, ceremonial bearing, body filled with saturated indigo and decorated INSIDE with lotus medallions, leaf-vein panels and fish-scale linework across seven body zones, saffron-orange decorated saddle blanket, vermillion anklets, bold black double-contour keylines, dotted Mithila ground line below the feet, modern Indian streetwear"

# ── 03. Indian Peacock — must be COLOR, not black silhouette ────────────
run 3 indian_peacock 8103 \
"single centered Indian peacock in side profile, premium Madhubani Mithila folk-art icon, crested head, long elegant neck, almond eye, compact fanned tail with readable feather-eye motifs, body filled with saturated indigo blue and decorated INSIDE with multi-color leaf-vein panels, tail feathers rendered as multi-color folk eyes (saffron centers, leaf-green surrounds, vermillion outer rings), gold-yellow neck-band, cream and vermillion dots scattered across the tail, bold black double-contour keylines, small dotted ground line below the feet, modern Indian streetwear"

# ── 04. Blackbuck — keep silhouette character, add COLOR fills ──────────
run 4 blackbuck 8104 \
"single centered Indian blackbuck antelope in side profile, premium Madhubani Mithila folk-art icon, elegant spiral horns, slender neck, almond eye, white cheek patch as flat folk shape, body filled with saturated indigo and decorated INSIDE with multi-color leaf-vein panels, fish-scale flank decoration, saffron-orange dot-bands across back and haunch, vermillion hooves and small lotus medallion at shoulder, bold black double-contour keylines, paired peepal-leaf ground sprigs below the hooves, modern Indian streetwear"

# ── 05. One-Horned Rhinoceros — also great in v1, keep ──────────────────
run 5 one_horned_rhinoceros 8105 \
"single centered Great Indian one-horned rhinoceros in side profile, premium Madhubani Mithila folk-art icon, heavy armor plates simplified into folk panels, single nose horn, calm almond eye, strong arched back, body filled with saturated walnut-brown or indigo and decorated INSIDE with seven zones of multi-color Madhubani ornament (lotus saddle, vermillion floral medallion at flank, gold-yellow dot-bands across armor plates, leaf-green vine at shoulder), bold black double-contour keylines, dotted Mithila ground line below the feet, modern Indian streetwear"

# ── 06. King Cobra — coiled, no ground line, dot platform instead ──────
run 6 king_cobra 8106 \
"single centered Indian king cobra rearing with open hood frontal-facing, body coiling in an elegant S-curve below, premium Madhubani Mithila folk-art icon, clear spectacle mark on hood, almond eyes, calm powerful posture, hood filled with saturated indigo and decorated INSIDE with lotus petal panels in saffron and vermillion, fish-scale rows along the body in leaf-green and gold-yellow, cream-white ventral scales, bold black double-contour keylines, small decorative platform of folk dots beneath the coiled base, modern Indian streetwear"

# ── 07. Snow Leopard — must read as MADHUBANI, not tribal cat ──────────
run 7 snow_leopard 8107 \
"single centered Himalayan snow leopard in complete full-body side profile, premium Madhubani Mithila folk-art icon, flowing long tail curled under body, rounded ears, almond eye, powerful proportional paws, rosette markings translated INTO multi-color folk floral panels (saffron centers, vermillion petals, leaf-green surrounds), body filled with saturated walnut-brown or forest-teal and decorated INSIDE with seven zones of Madhubani ornament including lotus saddle, gold-yellow neck-band, dotted anklets, bold black double-contour keylines, paired peepal-leaf ground sprigs below the paws, modern Indian streetwear"

# ── 08. Lion-tailed Macaque — keep the halo idea, add COLOR ────────────
run 8 lion_tailed_macaque 8108 \
"single centered lion-tailed macaque from the Western Ghats seated in side profile, premium Madhubani Mithila folk-art icon, signature silver mane halo around the dark face translated into a radiant folk sunburst (cream-white and gold-yellow rays with vermillion tips), almond eye, curved tail with leaf-shaped tuft, hands simplified into folk shapes, body filled with saturated indigo and decorated INSIDE with multi-color leaf-vein panels and fish-scale rows, saffron decorative band across chest, bold black double-contour keylines, small dotted ground line and a peepal-leaf sprig beside the figure, modern Indian streetwear"

END=$(date +%s)
echo
echo "═══════════════════════════════════════════════════════════════════"
echo "  v2 redraw done at $(date)  (total $((END-START))s)"
echo "  outputs: $OUT"
echo "═══════════════════════════════════════════════════════════════════"
ls -la "$OUT" | grep -v '\.directive\.json$\|transparent\.png$'
