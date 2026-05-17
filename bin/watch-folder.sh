#!/usr/bin/env bash
# watch-folder.sh v2 — stable-file detection, atomic locking, offline-safe.
#
# Improvements over v1:
#   - Refuses to process a file until its size + mtime have been unchanged for
#     STABLE_SECS (default 8s). Prevents picking up AirDrop / rsync / camera
#     mid-write partials.
#   - Uses flock on a sidecar .lock file to prevent races if you accidentally
#     run two watchers, or the launchd agent overlaps with a manual run.
#   - On processing failure, writes a .failed marker (with stderr) so the same
#     bad video doesn't get retried indefinitely. Delete the .failed file to
#     retry.
#   - Verifies pipeline warmup before starting and exits cleanly if missing.
#   - No external deps beyond the python script and ffmpeg / mlx_whisper /
#     mflux already verified by warmup.
#
# Usage:
#   bash watch-folder.sh ~/Videos/videos-in ~/Videos/videos-out
#
# Env overrides:
#   STABLE_SECS=8       seconds the file must be unchanged before we process
#   POLL_SECS=5         polling interval
#   QUALITY=good        passed to process-video.py --quality
#   LANGUAGES=en        comma-separated captions, e.g. en,mr,hi
#   NOISY=0|1           pass --noisy to denoise outdoor audio aggressively
#   MAX_RETRIES=2       transient failures retry before .failed is written
#   RETRY_SECS=300      seconds to wait between retry attempts

set -uo pipefail

IN_DIR="${1:?usage: watch-folder.sh <in-dir> <out-dir>}"
OUT_DIR="${2:?usage: watch-folder.sh <in-dir> <out-dir>}"
SCRIPT="$(cd "$(dirname "$0")" && pwd)/process-video.py"
READY_FILE="$HOME/.kaayko-pipeline/ready.json"

STABLE_SECS="${STABLE_SECS:-8}"
POLL_SECS="${POLL_SECS:-5}"
QUALITY="${QUALITY:-good}"
LANGUAGES="${LANGUAGES:-en}"
NOISY="${NOISY:-0}"
MAX_RETRIES="${MAX_RETRIES:-2}"
RETRY_SECS="${RETRY_SECS:-300}"

if [[ ! -f "$SCRIPT" ]]; then
  echo "[fatal] cannot find process-video.py at $SCRIPT" >&2
  exit 1
fi

if [[ ! -f "$READY_FILE" ]]; then
  echo "[fatal] pipeline not warmed up. Run while online:" >&2
  echo "        python3 \"$SCRIPT\" warmup --quality $QUALITY" >&2
  exit 1
fi

mkdir -p "$IN_DIR" "$OUT_DIR"
echo "watch  in:  $IN_DIR"
echo "watch  out: $OUT_DIR"
echo "stable: ${STABLE_SECS}s   poll: ${POLL_SECS}s   quality: $QUALITY   captions: $LANGUAGES   noisy: $NOISY   retries: $MAX_RETRIES"

# stat -f %m %z is BSD/macOS syntax
stable_size_mtime() {
  local f="$1"
  stat -f '%z %m' "$f" 2>/dev/null
}

retry_ready() {
  local marker="$1"
  [[ ! -f "$marker" ]] && return 0
  local next_epoch
  next_epoch="$(awk -F= '/^next_epoch=/{print $2}' "$marker" 2>/dev/null | tail -1)"
  [[ -z "$next_epoch" ]] && return 0
  [[ "$(date +%s)" -ge "$next_epoch" ]]
}

retry_attempts() {
  local marker="$1"
  [[ ! -f "$marker" ]] && { echo 0; return; }
  awk -F= '/^attempts=/{print $2}' "$marker" 2>/dev/null | tail -1
}

trap 'echo; echo "watcher stopped."; exit 0' INT TERM

while true; do
  while IFS= read -r -d '' video; do
    marker_done="${video}.done"
    marker_fail="${video}.failed"
    marker_retry="${video}.retry"
    lock="${video}.lock"
    [[ -f "$marker_done" ]] && continue
    [[ -f "$marker_fail" ]] && continue
    retry_ready "$marker_retry" || continue

    # Stable-file check: take two snapshots STABLE_SECS apart, only proceed if equal.
    snap1=$(stable_size_mtime "$video")
    [[ -z "$snap1" ]] && continue
    sleep "$STABLE_SECS"
    snap2=$(stable_size_mtime "$video")
    if [[ "$snap1" != "$snap2" ]]; then
      # File is still being written; come back next loop.
      continue
    fi
    if command -v lsof >/dev/null 2>&1 && lsof "$video" >/dev/null 2>&1; then
      continue
    fi

    # Atomic lock via mkdir (works on every filesystem including iCloud Drive).
    if ! mkdir "$lock" 2>/dev/null; then
      continue
    fi
    trap 'rmdir "$lock" 2>/dev/null; exit 130' INT TERM

    echo
    echo "─── $(basename "$video") ───"
    extra_args=()
    [[ "$NOISY" == "1" ]] && extra_args+=("--noisy")
    attempts="$(retry_attempts "$marker_retry")"
    attempts="${attempts:-0}"
    if python3 "$SCRIPT" process "$video" \
         --out "$OUT_DIR" --quality "$QUALITY" --captions "$LANGUAGES" "${extra_args[@]}" 2>"${video}.stderr"; then
      date -u +"%FT%TZ ok" > "$marker_done"
      rm -f "${video}.stderr"
      rm -f "$marker_retry"
      echo "✓ $(basename "$video") done"
    else
      attempts=$((attempts + 1))
      if [[ "$attempts" -le "$MAX_RETRIES" ]]; then
        next_epoch=$(( $(date +%s) + RETRY_SECS ))
        {
          echo "attempts=$attempts"
          echo "next_epoch=$next_epoch"
          echo "last_failed_at=$(date -u +"%FT%TZ")"
          echo "stderr=${video}.stderr"
        } > "$marker_retry"
        echo "↻ $(basename "$video") retry $attempts/$MAX_RETRIES scheduled in ${RETRY_SECS}s"
      else
        mv "${video}.stderr" "$marker_fail"
        rm -f "$marker_retry"
        echo "✗ $(basename "$video") FAILED permanently — see $marker_fail. Delete to retry."
      fi
    fi
    rmdir "$lock" 2>/dev/null
    trap 'echo; echo "watcher stopped."; exit 0' INT TERM
  done < <(find "$IN_DIR" -type f \
              \( -iname '*.mp4' -o -iname '*.mov' -o -iname '*.mkv' -o -iname '*.m4v' \) \
              -print0)

  sleep "$POLL_SECS"
done
