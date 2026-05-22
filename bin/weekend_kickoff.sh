#!/usr/bin/env bash
# weekend_kickoff.sh — Forge v3.0 ship in one command.
#
# Target: Saturday evening release.
# Start time: Friday evening (kick off before bed).
# Total wall-clock: ~18-22 hours, dominated by the 12-hour LoRA training.
#
# Sequential phases:
#   1. Fetch Wikimedia receipts for 4 new traditions          ~30 min  (network)
#   2. Rehydrate all reference binaries (madhubani + 4 new)    ~15 min  (network)
#   3. Audit Madhubani reference corpus                          <1 min
#   4. Prep Madhubani LoRA training dataset + config              <5 min
#   5. Madhubani LoRA training (mflux-train)                    ~12 hrs  (Metal saturated)
#   6. Render the 87-entry catalog × 4 canonical poses           ~3-4 hrs (Metal x4 slots)
#   7. Run QC + best-of-N picker                                 ~30 min
#
# All logs land in logs/weekend-<timestamp>/ for the technical writeup.
#
# Failure handling: set -euo pipefail means any non-zero exit halts the chain.
# Re-running is idempotent for phases 1-2 (fetcher skips existing receipts,
# rehydrate skips existing binaries). Phases 3-7 will re-run from scratch.
#
# To resume from a specific phase, comment out earlier phases or pass
# --start-from <phase> (TODO if needed).

set -euo pipefail

cd "$(dirname "$0")/.." || exit 1
START_TS=$(date +%s)
LOG_DIR="logs/weekend-$(date +%Y%m%d-%H%M)"
mkdir -p "$LOG_DIR"

log() {
    echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG_DIR/_orchestrator.log"
}

elapsed_human() {
    local secs=$1
    printf "%dh %dm %ds" $((secs/3600)) $(( (secs%3600)/60 )) $((secs%60))
}

log "================================================================"
log "Forge v3.0 weekend kickoff — Saturday evening ship target"
log "Logs: $LOG_DIR"
log "================================================================"

# ─────────────── Phase 1: Wikimedia fetch ───────────────
log ""
log "=== Phase 1/7: Wikimedia receipt fetch (4 traditions, ~30 min) ==="

for combo in \
    "pahari:Pahari_painting" \
    "kalighat:Kalighat_painting" \
    "tanjore:Tanjore_painting" \
    "ravi-varma:Paintings_by_Raja_Ravi_Varma"
do
    tradition="${combo%%:*}"
    category="${combo#*:}"
    log "  → Fetching tradition=$tradition category=$category target=50"
    python3 bin/fetch_wikimedia_category.py \
        --tradition "$tradition" \
        --category "$category" \
        --target 50 \
        --pace 1.0 \
        2>&1 | tee -a "$LOG_DIR/01-fetch-$tradition.log"
done

# ─────────────── Phase 2: Rehydrate binaries ───────────────
log ""
log "=== Phase 2/7: Rehydrate binaries (madhubani + 4 new, ~15 min) ==="
python3 bin/rehydrate_references.py 2>&1 | tee "$LOG_DIR/02-rehydrate.log"

# ─────────────── Phase 3: Audit ───────────────
log ""
log "=== Phase 3/7: Audit Madhubani reference corpus ==="
python3 brand/references/madhubani/_audit.py 2>&1 | tee "$LOG_DIR/03-audit-madhubani.log"

# ─────────────── Phase 4: Prep LoRA training dataset ───────────────
log ""
log "=== Phase 4/7: Prep Madhubani LoRA training dataset ==="
python3 bin/forge_madhubani_lora.py prep \
    --out training/madhubani_lora_v3 \
    --force \
    2>&1 | tee "$LOG_DIR/04-prep.log"

# ─────────────── Phase 5: LoRA training ───────────────
log ""
log "=== Phase 5/7: Madhubani LoRA training (~12 hrs Metal-saturated) ==="
log "  Kicking off mflux-train. Sleep now."
log "  Loss + sample logs go to $LOG_DIR/05-train.log"

PHASE5_START=$(date +%s)
mflux-train --config training/madhubani_lora_v3/train.json \
    2>&1 | tee "$LOG_DIR/05-train.log"
PHASE5_ELAPSED=$(($(date +%s) - PHASE5_START))
log "  LoRA training done in $(elapsed_human $PHASE5_ELAPSED)"

# Sanity check the LoRA output before continuing
LORA_PATH="training/madhubani_lora_v3/madhubani-lora-final.safetensors"
if [[ ! -f "$LORA_PATH" ]]; then
    log "  ERROR: expected $LORA_PATH after training, not found. Halt."
    exit 1
fi
LORA_MB=$(du -m "$LORA_PATH" | cut -f1)
log "  LoRA saved: $LORA_PATH ($LORA_MB MB)"

# ─────────────── Phase 6: Render catalog ───────────────
log ""
log "=== Phase 6/7: Render 87-entry catalog × 4 poses (~3-4 hrs) ==="
log "  Set FORGE_METAL_SLOTS=4 in env for parallel rendering."

export FORGE_METAL_SLOTS="${FORGE_METAL_SLOTS:-4}"

for pose in standing-alert seated-rest signature-action frontal-portrait; do
    log "  → Rendering pose: $pose"
    POSE_START=$(date +%s)
    python3 bin/forge_madhubani_batch_v4.py \
        --pose "$pose" \
        --seeds-per-attempt 2 \
        --max-attempts 3 \
        --accept-score 0.70 \
        --steps 25 \
        2>&1 | tee "$LOG_DIR/06-render-$pose.log"
    POSE_ELAPSED=$(($(date +%s) - POSE_START))
    log "  ← Pose $pose done in $(elapsed_human $POSE_ELAPSED)"
done

# ─────────────── Phase 7: QC + best-of-N ───────────────
log ""
log "=== Phase 7/7: QC + best-of-N picker (~30 min) ==="
log "  best_of_n.py and madhubani_qc.py write blockers.json sidecars"
log "  per-render; publishable: true/false in manifests."

# These are mostly informational summaries since QC ran per-render in phase 6
python3 -c "
import json
from pathlib import Path
generated_root = Path('generated/madhubani_animals')
total = sum(1 for _ in generated_root.rglob('*.png')) if generated_root.exists() else 0
blockers = sum(1 for _ in generated_root.rglob('*.blockers.json')) if generated_root.exists() else 0
publishable = total - blockers
print(f'Renders generated: {total}')
print(f'Publishable:       {publishable}')
print(f'Blocked (QC):      {blockers}')
" 2>&1 | tee "$LOG_DIR/07-qc-summary.log"

# ─────────────── Done ───────────────
TOTAL_ELAPSED=$(($(date +%s) - START_TS))
log ""
log "================================================================"
log "DONE. Total wall-clock: $(elapsed_human $TOTAL_ELAPSED)"
log "Logs: $LOG_DIR"
log "================================================================"
log ""
log "Ship checklist:"
log "  □ Bump README badges (41-species → 87 / 100)"
log "  □ Commit v3.0 catalog + LoRA + sample renders"
log "  □ Tag release: git tag v3.0 && git push --tags"
log "  □ Update docs/PAPER_OUTLINE.md with measured numbers from phase 7"
log "  □ Draft arXiv preprint section: empirical results (Table 1)"
log ""
log "Saturday evening release window. Ship it."
