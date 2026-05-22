# Desktop Pickup Plan — Resume from Mobile

**Branch:** `claude/forge-video-translation-audit-CQUOV`
**Last mobile-session commit:** `d051499` (orchestrator + paper outline)
**Status:** Ready to execute on M5 Max. All scripts written, no more planning needed.

This is your read-on-arrival document. Open this file when you sit down at the desktop.

---

## Step 1 — Pull the branch (1 minute)

```sh
cd ~/Desktop/Forge
git fetch origin
git checkout claude/forge-video-translation-audit-CQUOV
git pull origin claude/forge-video-translation-audit-CQUOV
git log --oneline -10  # verify you see the recent commits
```

Expected to see (most recent first):
```
d051499  bin+docs: weekend_kickoff orchestrator + PAPER_OUTLINE for v3.0 ship
f86ee8f  bin: fetch_wikimedia_category.py — open-license receipt fetcher
f0c6f05  catalog: +30 birds for 15 parks (Batch B of ~3)
4e0d6d6  catalog: +16 species for 4 new parks (Batch A of ~4)
883b7b4  engines: drop Gond, add Kalighat — lock to 5-tradition open-source scope
4a28092  parks: consolidate to brand/parks/_index.json as single source of truth
c552d14  refactor: drop duplicated style registry, add Gond as first-class tradition
efa4e88  parks: canonical 25-park catalog + receipt schema v0.1 draft
```

If you see those 8 commits, the branch is current.

---

## Step 2 — Sanity-check the M5 environment (2 minutes)

```sh
forge doctor --deep                    # verify mflux, MLX, ffmpeg, etc.
ls bin/weekend_kickoff.sh              # verify the orchestrator is executable
ls bin/fetch_wikimedia_category.py     # verify the fetcher is there
ls docs/PAPER_OUTLINE.md               # verify the paper outline
python3 -c "import sys; sys.path.insert(0,'bin'); from style_engines import describe_engine; print(sorted(describe_engine('indian-classical')['vocabulary']['tradition'].keys()))"
```

The last command should print: `['kalighat', 'madhubani', 'pahari-miniature', 'ravi-varma-oleograph', 'tanjore', 'warli']` — confirming the 5 supported traditions + Warli are in the engine.

---

## Step 3 — Read the catalog state (1 minute)

```sh
python3 -c "
import json
with open('brand/madhubani/animals.json') as f:
    d = json.load(f)
print(f'Catalog: {len(d[\"animals\"])} entries across {len(set(a[\"park\"] for a in d[\"animals\"]))} parks')
" 
python3 brand/references/madhubani/_audit.py | head -10
```

Expected: 87 entries across 25 parks. Reference corpus audit will show 50 receipts in `_general/` but 0 binaries (until you run rehydrate in Step 4).

---

## Step 4 — Kick off the weekend run (one command)

```sh
# Friday evening ~6pm, when you have ~22 hours of M5 time available:
bash bin/weekend_kickoff.sh
```

This runs sequentially (fail-fast):

| Phase | Wall-clock | What runs | What to do |
|---|---|---|---|
| 1. Wikimedia fetch | ~30 min | Receipts for Pahari/Kalighat/Tanjore/Ravi-Varma | Network-bound; M5 idle |
| 2. Rehydrate binaries | ~15 min | Downloads all references | Network-bound; M5 idle |
| 3. Madhubani audit | <1 min | Reports corpus health | Read the output |
| 4. LoRA prep | <5 min | Writes `training/madhubani_lora_v3/train.json` | Quick |
| 5. **LoRA training** | **~12 hrs** | `mflux-train` saturates Metal | **Sleep through this** |
| 6. Catalog render | ~3-4 hrs | 87 entries × 4 poses, FORGE_METAL_SLOTS=4 | Coffee + breakfast |
| 7. QC summary | ~30 min | Counts publishable vs blocked renders | Spot-check |

**All logs land in `logs/weekend-<timestamp>/`** for the technical writeup.

---

## Step 5 — Saturday morning checkpoint (~9am after Friday evening start)

After Step 4 has been running ~14 hours, check:

```sh
ls logs/weekend-*/05-train.log    # confirm LoRA training finished
ls training/madhubani_lora_v3/    # should contain madhubani-lora-final.safetensors
```

If the LoRA training failed mid-run, the script halted. Check `logs/weekend-*/05-train.log` for the error and re-run with the same command (Phase 1-2 idempotent skip; Phase 5 will resume from scratch but the receipts/binaries are intact).

Spot-check renders by hand:
```sh
forge engine render minimalist-tshirt \
    --subject "Royal Bengal Tiger" \
    --tradition madhubani-master-painter \
    --seeds 4
```

If the new LoRA looks visibly better than the v2 baseline (compare against `docs/gallery/voted_*.png`), the training succeeded.

---

## Step 6 — Saturday afternoon catalog render and QC (~12pm-4pm)

By this point Phase 6 of the kickoff is rendering the full catalog. Watch progress:

```sh
ls generated/madhubani_animals/ | wc -l    # total renders so far
tail -f logs/weekend-*/06-render-*.log     # live progress
```

When Phase 7 completes, the QC summary prints to stdout. Numbers feed into `PAPER_OUTLINE.md` section 5.

---

## Step 7 — Saturday evening ship (~4pm-6pm)

```sh
# Update the paper outline TBDs with measured numbers
$EDITOR docs/PAPER_OUTLINE.md
# Search for "TBD" — replace with phase-7 QC numbers + phase-5 LoRA timings

# Update README counts (41 → 87/100, 21 → 25)
$EDITOR README.md
# Find: "41-species" → replace with "87-species" (or 100 if Batch C done)
# Find: "21 national parks" → replace with "25"

# Commit the v3.0 release
git add docs/PAPER_OUTLINE.md README.md
git add brand/references/        # commits only the new .attribution.json receipts (binaries gitignored)
git add training/madhubani_lora_v3/train.json  # config only, not weights
git commit -m "v3.0: full Madhubani LoRA + 87-entry catalog + reference corpus"

# Tag and push
git tag v3.0
git push origin claude/forge-video-translation-audit-CQUOV
git push origin v3.0
```

Saturday evening v3.0 ship: ✅

---

## What's NOT in scope for this weekend

Explicitly deferred (will not derail the Saturday-evening ship):

- **Batch C** (13 remaining catalog entries — chilika/keoladeo/marine-kutch/ranthambore/silent-valley/velavadar). Catalog ships at 87/100; reviewer-acceptable.
- **Pahari / Kalighat / Tanjore / Ravi-Varma LoRAs**. References fetched, training queued for future weekends. Ship them prompt-only via the EnumValues already in `_IC_TRADITION`.
- **Animal anatomy photo corpus** (iNaturalist, Macaulay Library). Skip for v3.0. The Madhubani LoRA learns body grammar from the painting corpus + species iconography in `species_iconography.json`. Animal photos are a v3.1 enhancement.
- **`forge verify` + `forge reproduce` CLIs**. Receipt schema is documented in `docs/SCHEMA.md`; CLI implementation is v3.1.
- **arXiv preprint submission**. Outline is ready in `docs/PAPER_OUTLINE.md`; LaTeX submission is within following week, not this weekend.

---

## When you need me back

Ping me with any of these and I pick up where we left off:

1. **Phase 5 LoRA training failed** — paste the error from `logs/weekend-*/05-train.log` here
2. **Phase 6 render failures clustered around specific species** — let me know which slugs need targeted retry-with-boost
3. **Paper-outline TBD fill-in needs prose pass** — once the numbers are measured, I can polish the abstract + section 5
4. **Batch C catalog finishing** — the 13 remaining entries when you want them
5. **Pahari LoRA training for next weekend** — wrap `forge_madhubani_lora.py` to consume a different reference dir

---

## Confidence summary for the Saturday-evening ship

| Risk | Probability | Mitigation |
|---|---|---|
| Wikimedia rate-limit / 403 on some categories | Low (10%) | Polite throttle in fetcher; user-agent set; receipts written incrementally so partial success is preserved |
| LoRA training fails OOM on 50-image corpus | Low (5%) | Pilot succeeded at rank 16, 500 steps. Full run at rank 32, 1500 steps is within M5 Max memory. |
| Renders quality regression vs. v2 | Medium (20%) | If LoRA overfits or underfits, fall back to madhubani-master-painter prompt-only (the EnumValue is unchanged) |
| Catalog render takes longer than 4 hrs | Medium (25%) | Set FORGE_METAL_SLOTS=4 (already in kickoff script). If still slow, cut to 2 poses instead of 4 — ship a 174-render gallery instead of 348 |
| Total timeline slips past Saturday evening | Medium (30%) | Sunday morning ship is the soft fallback. Paper outline framing doesn't change. |

**Net assessment:** ~70% probability of clean Saturday-evening v3.0 ship. ~95% probability of Sunday-morning ship if anything slips. Paper outline is unaffected either way.

---

## Branch hygiene reminder

This branch (`claude/forge-video-translation-audit-CQUOV`) has 8 commits beyond main. Don't merge to main until:
1. v3.0 release is tagged
2. README counts are updated
3. PAPER_OUTLINE.md is populated

Then either:
- Squash-merge to main with a clean v3.0 commit message
- Or keep the per-commit history if you want the granular trail

Either works.

---

**Last updated:** 2026-05-22 (mobile session end)
**Status:** Hand-off ready. Resume on M5 by running Step 1.
