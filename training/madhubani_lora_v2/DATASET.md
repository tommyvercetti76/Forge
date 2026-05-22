# Madhubani LoRA-v2 training dataset

**Training samples:** 25
**Excluded (held-out):** 4
**Source label pool:** 29 PASS images

Built by `bin/build_lora_dataset_v2.py` from user-graded PASS
labels. Each training image is the model's own render that the
user marked PASS — NOT a Wikimedia reference painting. The LoRA
therefore learns the user's curated subset of the base model's
distribution.

## Held-out species (not in training)

- `rhino` — v3 PASS — 'good that we picked'
- `peacock` — v1 plumage ideal, v2 colors ideal (gold standard)
- `elephant` — v2 gold standard
- `snow-leopard` — all v1/v2/v3 FAIL — 'all snow leopards mid in Madhubani art'

## Caption template

Every training image gets a short caption built from a shared
style key plus the species' display name and body type. This is
intentionally simpler than the verbose 1000-token rendering prompts —
the LoRA needs to generalize the style cue across many subjects,
not memorize a specific prompt.

```
a madhubani folk art painting in the mithila tradition of bihar, india: double-line black outlines, flat folk-color panels in indigo and vermillion and saffron, seven ornamental decoration zones on the body, almond eyes with watchful ceremonial gravity, no naturalistic species coloring.
```

## Samples

| Slug | Body | Composite (winner) | MD5 |
| :--- | :--- | :--- | :--- |
| `saltwater-crocodile` | crocodilian | 0.7965 | `9a7a3835…` |
| `sambar-deer` | lean-quadruped | 0.8099 | `ab4f52be…` |
| `nilgiri-tahr` | lean-quadruped | 0.8132 | `c213eb79…` |
| `nilgiri-tahr` | lean-quadruped | 0.8132 | `949d7122…` |
| `barasingha` | lean-quadruped | 0.8092 | `3898e8a6…` |
| `dhole` | lean-predator | 0.7988 | `17495dc1…` |
| `dhole` | lean-predator | 0.7988 | `8d766fe4…` |
| `chinkara` | lean-quadruped | 0.8099 | `03baee3b…` |
| `pygmy-hog` | stocky-omnivore | 0.8094 | `8394cf3d…` |
| `bharal` | lean-quadruped | 0.8120 | `eba7cbfe…` |
| `sarus-crane` | bird | 0.5541 | `6d6eb80d…` |
| `sarus-crane` | bird | 0.5541 | `d69de72a…` |
| `painted-stork` | bird | 0.8048 | `673352af…` |
| `indian-pangolin` | armored-quadruped | 0.6332 | `b7c15144…` |
| `indian-pangolin` | armored-quadruped | 0.6332 | `53b17bce…` |
| `indian-giant-squirrel` | small-mammal | 0.7927 | `cc789a5b…` |
| `indian-giant-squirrel` | small-mammal | 0.7927 | `4d39d5dc…` |
| `indian-grey-mongoose` | small-mammal | 0.7858 | `746b8fd9…` |
| `indian-fox` | small-mammal | 0.7943 | `f3d98647…` |
| `indian-fox` | small-mammal | 0.7943 | `0e04c47d…` |
| `red-panda` | small-mammal | 0.7818 | `bbb1ba09…` |
| `greater-flamingo` | bird | 0.6364 | `f80ce09b…` |
| `great-indian-hornbill` | bird | 0.8025 | `323cdd30…` |
| `blackbuck` | lean-quadruped | 0.8186 | `350d1f56…` |
| `blackbuck` | lean-quadruped | 0.8186 | `f5b63fa9…` |
