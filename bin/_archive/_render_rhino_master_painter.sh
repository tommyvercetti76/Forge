#!/bin/bash
# Rhino — Madhubani Master-Painter validation set.
#
# Purpose: First test of the `madhubani-master-painter` tradition register
# (added 2026-05-18 per MADHUBANI_CATALOG_PLAN.md §6a). Renders one
# complete animal-set (1 animal × 4 poses) so we can compare against the
# v3 rhino baseline and decide whether master-painter delivers expressive
# results worth adopting as the catalog default.
#
# The Rhino was chosen because it was the v3 winner (9/10) — best baseline
# to A/B against. If master-painter improves on the v3 rhino, it'll help
# the rest of the catalog. If it doesn't, we iterate the §6a shifts before
# scaling.
#
# What's NEW in this render vs v3:
#   - production.tradition = madhubani-master-painter (was madhubani-contemporary)
#     → engine injects the six §6a shifts: varied linework, composed palette,
#       hand-drawn ornament, character-bearing eyes, hand-painted texture,
#       original-art references (Sita Devi kohbar / Ganga Devi bharni /
#       Baua Devi matsya / Mithila kohbar tradition).
#   - 4 distinct poses, each carrying the new pose-specific eye character:
#       Pose 01 standing-alert    → watchful ceremonial gravity
#       Pose 02 seated-rest       → contemplative stillness
#       Pose 03 signature-action  → charging power
#       Pose 04 frontal-portrait  → ancient ritual presence
#
# Seeds chosen fresh for the master-painter test (8201-8204) so this set
# is independent of v3 (which used 8105 for rhino). A/B comparison is
# register vs register, not seed vs seed.

set -u
OUT=/Users/Rohan/Desktop/Forge/generated/madhubani_animals/rhino_v1
mkdir -p "$OUT"
cd /Users/Rohan/Desktop/Forge

PYBIN=/Library/Frameworks/Python.framework/Versions/3.13/bin/python3
FORGE="$PYBIN bin/forge.py engine render minimalist-tshirt"

# NOTE the tradition change: madhubani-master-painter (NOT contemporary)
CONFIG="subject.motif=madhubani-folk-icon,style.tradition=madhubani-master-painter,style.detail=maximal-but-printable,style.symmetry=handmade-balanced,style.accents=micro-folk-dots,production.output=print-art,production.ink=vibrant-folk,production.shirt_color=cream-or-black,composition.placement=center-chest,composition.layout=single-mark,composition.background=no-background,composition.border=none"

START=$(date +%s)
echo "═══════════════════════════════════════════════════════════════════"
echo "  Rhino × 4 poses — Madhubani Master-Painter validation set"
echo "  start: $(date)"
echo "  out:   $OUT"
echo "  steps: 24"
echo "  register: madhubani-master-painter (NEW)"
echo "═══════════════════════════════════════════════════════════════════"

run() {
  local idx="$1" pose="$2" seed="$3" subject="$4"
  local file="$OUT/$(printf '%02d' "$idx")_rhino_${pose}.png"
  local t0=$(date +%s)
  echo
  echo "── [$idx/4] Rhino — pose: $pose  (seed=$seed)"
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

# ── Pose 01 — STANDING ALERT ────────────────────────────────────────────
# The hero pose. Eye carries watchful ceremonial gravity.
run 1 standing-alert 8201 \
"single centered Great Indian one-horned rhinoceros STANDING ALERT in complete full-body side profile facing right, premium Madhubani Mithila folk-art icon painted in the master-painter register, heavy armor plates simplified into hand-drawn folk panels with confident varied linework, single nose horn proportional and dignified, almond eye carrying WATCHFUL CEREMONIAL GRAVITY (alert intensity not blank stare, not surprise), mouth closed in calm posture, strong arched back, all four pillar-broad legs clearly visible and planted on the ground (near pair and far pair both fully drawn as distinct outlines), body filled with saturated indigo carrying subtle hand-painted pigment texture, decorated INSIDE with seven distinct zones of hand-drawn multi-color Madhubani ornament — small tikka medallion on forehead, leaf-vein panel at ear, dot-band at neck, large lotus-and-sun saddle across the back painted in saffron and vermillion with gold-yellow accents, vine motif at shoulder, vermillion floral medallion at hip, rhythmic stripe anklets at every joint with hand-irregularity, body BETWEEN zones remains a clean saturated indigo color field (NOT all-over pattern), bold hand-drawn double-contour keylines with weight variation, dotted Mithila ground line of saffron and gold dots below the feet, 8-12 small ornamental flourishes scattered tastefully in negative space"

# ── Pose 02 — SEATED REST ──────────────────────────────────────────────
# Reclining pose. Rhinos kneel/recline like cattle. Eye carries contemplative stillness.
run 2 seated-rest 8202 \
"single centered Great Indian one-horned rhinoceros RECLINING in calm rest position in side profile facing right (front legs folded beneath body camel-fashion, hindquarters tucked, head held up alert), premium Madhubani Mithila folk-art icon painted in the master-painter register, heavy armor plates simplified into hand-drawn folk panels with confident varied linework, single nose horn elegant, almond eye carrying CONTEMPLATIVE STILLNESS (peaceful intelligent rest, not asleep, not blank), mouth closed in serene posture, body filled with saturated walnut-brown carrying subtle hand-painted pigment texture, decorated INSIDE with seven distinct zones of hand-drawn multi-color Madhubani ornament with eye-finding variation in petal sizes and dot spacing, ONE large ornamental panel across the visible flank in saffron and vermillion with leaf-green vine accents, gold-yellow dot-bands on armor plates, leg anklets visible on folded forelimbs, body BETWEEN decorated zones remains clean walnut color field, bold hand-drawn double-contour keylines with weight variation, dotted Mithila ground mark of paired peepal leaves beneath the reclining body, 8-12 small ornamental flourishes in negative space"

# ── Pose 03 — SIGNATURE ACTION (CHARGING) ──────────────────────────────
# Rhinos are famous for the charge. Eye carries focused charging power.
run 3 signature-action 8203 \
"single centered Great Indian one-horned rhinoceros CHARGING with focused power in dynamic side profile facing right (head lowered slightly, horn forward, all four legs in mid-stride with one foreleg extended forward and one hindleg pushing back, body in motion but anatomically clear), premium Madhubani Mithila folk-art icon painted in the master-painter register, heavy armor plates simplified into hand-drawn folk panels with confident varied linework, single nose horn pointed forward as the focal point, almond eye carrying FOCUSED CHARGING POWER (intense purposeful gaze, not angry cartoon, not blank), mouth closed in determined posture, all four pillar-broad legs CLEARLY visible as distinct outlines in mid-motion (no merged legs, no hidden far pair), body filled with saturated indigo carrying subtle hand-painted pigment texture, decorated INSIDE with seven distinct zones of hand-drawn multi-color Madhubani ornament with petals and dots showing organic irregularity, dynamic decoration emphasizing forward motion (saffron arrows or fish-scale rows pointing forward, gold-yellow streamers from the haunches), body BETWEEN zones remains clean indigo color field, bold hand-drawn double-contour keylines with weight variation, dotted Mithila ground line of dust kicked up by hooves rendered as small ornamental dots and short lines, 8-12 small flourishes in negative space"

# ── Pose 04 — FRONTAL PORTRAIT ─────────────────────────────────────────
# Head-and-shoulders frontal mark. Eye carries ancient ritual presence.
run 4 frontal-portrait 8204 \
"single centered Great Indian one-horned rhinoceros FRONTAL PORTRAIT head-and-shoulders facing the viewer directly (full frontal symmetric composition, horn rising centered, both eyes visible looking forward, ears both visible flanking the head, shoulders and front of armor plates visible at the bottom of the frame), premium Madhubani Mithila folk-art icon painted in the master-painter register, hand-drawn folk panel decoration on the visible armor plates with confident varied linework, single nose horn rising as the vertical central anchor, both almond eyes carrying ANCIENT RITUAL PRESENCE (sacred ceremonial gaze, the gravity of a temple icon, calm timeless dignity, NEVER round cartoon eyes, NEVER surprised, NEVER blank), mouth closed in dignified composure, body filled with saturated indigo carrying subtle hand-painted pigment texture, decorated INSIDE with: a small tikka medallion on forehead between the eyes, two layered leaf-vein patterns one in each ear, a dot-band collar across the neck, two symmetric lotus medallions on the shoulders in saffron and vermillion, gold-yellow accents and leaf-green vines, decoration is SYMMETRIC left-right with handmade folk-art irregularity (not mechanical mirror), bold hand-drawn double-contour keylines with weight variation, a decorative aura halo of dots and small petals radiating outward from the head in cream and saffron, no ground line (frontal portrait floats), 8-12 small flourishes in negative space around the figure"

END=$(date +%s)
echo
echo "═══════════════════════════════════════════════════════════════════"
echo "  Rhino set done at $(date)  (total $((END-START))s)"
echo "  outputs: $OUT"
echo "═══════════════════════════════════════════════════════════════════"
echo
echo "Next steps:"
echo "  1. Open all 4 PNGs side-by-side"
echo "  2. Compare expressiveness vs v3 rhino (generated/indian_animals_madhubani_tshirts_v3/05_one_horned_rhinoceros_madhubani_tshirt.png)"
echo "  3. Score each pose against the 7-point rubric in CATALOG_PLAN §6"
echo "  4. Tell Claude which to MASTER, FLAG, or REJECT"
echo "  5. Claude updates the ARTIST_CARD.md with outcomes"
echo
ls -la "$OUT" | grep -v '\.directive\.json$\|transparent\.png$'
