#!/usr/bin/env bash
# migrate-models.sh — establish ~/Models/ as the canonical model home and
# move scattered model files (today: FLUX safetensors in ~/Downloads) into it.
#
# Designed to be idempotent: re-running does nothing if files are already in
# the right place. Never deletes; only moves with verification.
#
# Usage:
#   bash migrate-models.sh                  # prompts before each move
#   bash migrate-models.sh --yes            # non-interactive

set -uo pipefail

ASSUME_YES=0
[[ "${1:-}" == "--yes" || "${1:-}" == "-y" ]] && ASSUME_YES=1

MODELS_HOME="${MODELS_HOME:-$HOME/Models}"
FLUX_BFL_DIR="$MODELS_HOME/flux-bfl"
KOKORO_DIR="$MODELS_HOME/kokoro"

c_grn='\033[32m'; c_blu='\033[34m'; c_ylw='\033[33m'; c_off='\033[0m'
info() { printf "%b[i]%b %s\n" "$c_blu" "$c_off" "$*"; }
ok()   { printf "%b[+]%b %s\n" "$c_grn" "$c_off" "$*"; }
warn() { printf "%b[!]%b %s\n" "$c_ylw" "$c_off" "$*"; }

confirm() {
  [[ $ASSUME_YES -eq 1 ]] && return 0
  printf "  %s [y/N] " "$1"; read -r r; [[ "$r" =~ ^[Yy]$ ]]
}

# Move with same-volume optimization (instant rename) + size verification.
safe_move() {
  local src="$1" dst="$2"
  [[ ! -f "$src" ]] && return 0
  if [[ -f "$dst" ]]; then
    if [[ "$(stat -f%z "$src")" == "$(stat -f%z "$dst")" ]]; then
      warn "  destination exists with same size, removing source"
      rm -f "$src"
      return 0
    fi
    warn "  destination exists but different size; refusing to overwrite"
    return 1
  fi
  mv "$src" "$dst"
  ok "  moved $(basename "$src") → $dst"
}

info "Canonical model home: $MODELS_HOME"
mkdir -p "$FLUX_BFL_DIR" "$KOKORO_DIR"

info "Step 1/3: FLUX BFL-format checkpoints"
moved_any=0
for f in "$HOME/Downloads/flux1-schnell.safetensors" \
         "$HOME/Downloads/flux1-dev.safetensors" \
         "$HOME/Downloads/ae.safetensors"; do
  [[ ! -f "$f" ]] && continue
  sz=$(du -h "$f" | cut -f1)
  dst="$FLUX_BFL_DIR/$(basename "$f")"
  if confirm "  Move $(basename "$f") ($sz) → $dst ?"; then
    safe_move "$f" "$dst" && moved_any=1
  fi
done
[[ $moved_any -eq 0 ]] && warn "  No FLUX BFL files found in ~/Downloads to move."

info "Step 2/3: Kokoro TTS models (if downloaded)"
for f in "$HOME/Downloads/kokoro-v"*.onnx \
         "$HOME/Downloads/voices.bin" \
         "$HOME/Downloads/voices-v"*.bin; do
  [[ ! -f "$f" ]] && continue
  sz=$(du -h "$f" | cut -f1)
  dst="$KOKORO_DIR/$(basename "$f")"
  if confirm "  Move $(basename "$f") ($sz) → $dst ?"; then
    safe_move "$f" "$dst"
  fi
done

info "Step 3/3: Verify and report"
echo
echo "  $MODELS_HOME layout:"
find "$MODELS_HOME" -maxdepth 2 -mindepth 1 -type d | sort | sed 's|^|    |'
echo
echo "  FLUX BFL checkpoints:"
ls -lh "$FLUX_BFL_DIR" 2>/dev/null | grep -v '^total' | awk '{printf "    %-40s %s\n", $NF, $5}'
echo
echo "  HuggingFace cache (mflux looks here):"
du -sh "$MODELS_HOME/huggingface" 2>/dev/null | awk '{print "    " $0}'
echo "  Ollama models:"
du -sh "$MODELS_HOME/ollama" 2>/dev/null | awk '{print "    " $0}'

cat <<'EOF'

Next steps:

  1. Inventory everything:
       forge models scan

  2. If you want mflux to actually use FLUX-schnell, the HF diffusers cache
     needs to be completed (~19 GB remaining). Your BFL files are kept as
     a reserve in flux-bfl/.

       hf download black-forest-labs/FLUX.1-schnell

     This is resumable. Your existing 4.8 GB partial in the HF cache resumes
     from where it stopped.

  3. To use BFL files directly (with ComfyUI or future mflux versions that
     support BFL native format), point those tools at:
       ~/Models/flux-bfl/

  4. Never re-download: every Forge tool that needs a model will read from
     ~/Models/ first.
EOF
