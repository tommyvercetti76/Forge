# Madhubani — Winning Prompts (mined from runs.jsonl)

> Mined: 2026-05-20T21:12:19Z
> Source: `brand/madhubani/learning/runs.jsonl`
> Rows scanned: 1, sessions: 1, groups: 1

Best-composite render per `(animal_slug, pose_slug)`, ordered by composite descending.

## Top render per species

| Species | Best composite | Best (slug, pose) | auto_qc_pass | Render |
| :--- | -: | :--- | :-: | :--- |
| rhino | 0.8199 | (rhino, standing-alert) | yes | `/Users/Rohan/Desktop/Forge/generated/madhubani_animals/reasoning_runs/rhino/20260520_161049/attempt_01/seed02.png` |

## Per-`(species, pose)` winner + lineage

### `rhino` / `standing-alert`

- **Best composite:** 0.8199  (auto_qc_pass: True)
- **Rubric pass fraction:** 1.000
- **CLIP likeness probability:** 0.5498
- **Active checks:** 7/7  
- **Failed:** ['anatomy', 'anatomy_feature_count']
- **Final boost applied (if any):** (none)
- **Prompt hash:** `sha256:931709aa0e4ba860c800e573fd6ffb5ce20c8f141e2957c28b4d9a3331dc6e42`
- **Render path:** `/Users/Rohan/Desktop/Forge/generated/madhubani_animals/reasoning_runs/rhino/20260520_161049/attempt_01/seed02.png`

**Winning prompt:**

```
single centered Great Indian One-horned Rhinoceros STANDING ALERT in complete full-body side profile
 facing right, premium Madhubani Mithila folk-art icon painted in the master-painter register (flat 
folk-icon, never naturalistic illustration), SPECIES ANATOMY: EXACTLY ONE nose horn (Indian one-horn
ed rhinoceros has a single horn, NEVER two); armored skin folds across shoulders and haunches; recta
ngular ears, pillar-broad legs proportional to body mass, broad shoulders and hips, sturdy hocks and
 fetlocks, all four legs clearly visible in side profile, single nose horn, armored skin plates simp
lified into folk panels, strong arched back, almond eye carrying WATCHFUL CEREMONIAL GRAVITY (alert 
intensity, not blank stare, not surprise, not cartoon), mouth closed, BODY FILL OVERRIDE (CRITICAL —
 this OVERRIDES the model's pretrained species-natural color): the entire body silhouette MUST be fl
at-filled with saturated deep-indigo (#1a2952) as the dominant base color — this is a Madhubani folk
-art convention, NOT a naturalistic species render. DO NOT use natural species coloring (no natural 
tiger orange, no realistic lion tan, no realistic peacock blue body, no national-geographic-style fu
r/feather/skin tones). The deep-indigo fill is the canvas; multi-color folk panels go ON TOP of it, 
decorated INSIDE with seven distinct zones of hand-drawn multi-color Madhubani ornament — tikka meda
llion on forehead, leaf-vein panel at ear, dot-band at neck, large ornamental panel on back, vine mo
tif at shoulder, vermillion floral medallion at hip, rhythmic stripe anklets at every joint, body BE
TWEEN zones remains a clean saturated color field (NOT all-over pattern), bold hand-drawn double-con
tour keylines with weight variation, dotted Mithila ground line below the feet, 8-12 small ornamenta
l flourishes scattered tastefully in negative space, modern Indian streetwear, MANDATORY DECORATION 
ZONES (ALL must be visibly present in the rendered output — failure on any one means the design is i
ncomplete): FOREHEAD: tikka medallion; NECK: folk collar band; ARMOR PLATES (most important): the rh
ino's armor folds rendered as ornate folk panels — shoulder plate with sun-medallion, flank plate wi
th vine motif, haunch plate with rosette pattern; FOUR ANKLETS: vermillion + saffron bands; NOSE-HOR
N: single horn proportional (NOT two horns); EARS: 2 small rectangular ears; TAIL: short with tufted
 tip, ANATOMICAL COUNTS (strict — these specific feature-count rules MUST be satisfied for the speci
es identity to read correctly): horns_on_nose: 1 (single horn — Indian one-horned rhinoceros; NEVER 
2 horns, that would be an African rhino); legs_visible: 4 (all four legs as distinct outlines); ears
: 2 small rectangular; tail: 1 short tufted, DECORATION DENSITY: ornate — 5-7 distinct interior deco
ration zones across the body silhouette; saddle blanket + leg anklets + neck collar + forehead tikka
 + body-zone medallions; classic full Madhubani density; the body is ornately patterned but anatomy 
remains clearly readable
```

