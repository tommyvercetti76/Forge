#!/usr/bin/env bash
# transcribe-video.sh — local-only YouTube-ready captioning
#
# Pipeline:
#   1. ffmpeg extracts mono 16 kHz audio (Whisper's native rate)
#   2. mlx-whisper transcribes on Metal using whisper-large-v3-turbo
#   3. Outputs both .srt (universal) and .vtt (WebVTT) into a captions/ dir
#      next to the input video
#
# YouTube accepts .srt and .vtt directly — upload via Studio → Subtitles.
#
# Usage:
#   ./transcribe-video.sh path/to/video.mp4
#   ./transcribe-video.sh path/to/video.mp4 en      # force language
#   MODEL=mlx-community/whisper-large-v3-mlx ./transcribe-video.sh video.mp4
#
# First run will download the model (~1.5 GB for turbo, ~3 GB for large-v3).

set -euo pipefail

VIDEO="${1:-}"
LANG_HINT="${2:-}"
MODEL="${MODEL:-mlx-community/whisper-large-v3-turbo}"

if [[ -z "$VIDEO" || ! -f "$VIDEO" ]]; then
  echo "usage: $0 <video file> [language code]"
  exit 2
fi

command -v ffmpeg >/dev/null 2>&1 || { echo "ffmpeg not found — install from evermeet.cx/ffmpeg/"; exit 1; }
command -v mlx_whisper >/dev/null 2>&1 || { echo "mlx_whisper not found — uv tool install mlx-whisper"; exit 1; }

dir="$(dirname "$VIDEO")"
base="$(basename "$VIDEO")"
stem="${base%.*}"
out="${dir}/captions"
mkdir -p "$out"

echo "[1/2] Extracting 16 kHz mono audio…"
audio="${out}/${stem}.wav"
ffmpeg -y -hide_banner -loglevel error \
  -i "$VIDEO" -vn -ac 1 -ar 16000 -f wav "$audio"
sz=$(du -h "$audio" | cut -f1)
echo "      wrote $audio ($sz)"

echo "[2/2] Transcribing with $MODEL …"
lang_args=()
[[ -n "$LANG_HINT" ]] && lang_args=(--language "$LANG_HINT")

mlx_whisper "$audio" \
  --model "$MODEL" \
  --output-dir "$out" \
  --output-format srt \
  --output-format vtt \
  --output-format txt \
  --word-timestamps True \
  "${lang_args[@]}"

# mlx_whisper names outputs by the audio stem, e.g. <stem>.srt
echo
echo "Done. Outputs:"
for ext in srt vtt txt; do
  f="${out}/${stem}.${ext}"
  [[ -f "$f" ]] && echo "  $f  ($(wc -l < "$f" | tr -d ' ') lines)"
done
echo
echo "Upload .srt to YouTube Studio → Subtitles → Add language → Upload file."
