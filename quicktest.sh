#!/usr/bin/env bash
#
# Quick test for SmartSplit.
# Processes only the first clip(s) of 1 or 2 videos, on a single platform
# (TikTok by default), with the 'tiny' model, and writes to quicktest/ without
# touching your real outputs (<video>_final/).
#
# Examples:
#   ./quicktest.sh                              # first 2 videos in input_videos/
#   ./quicktest.sh "input_videos/my_video.mp4"  # a specific video
#   PLATFORM=both LIMIT=2 MODEL=small ./quicktest.sh
#
# Environment variables (with defaults):
#   MODEL=tiny       Whisper model (tiny/base/small/...)
#   LIMIT=1          clips processed per video and per platform
#   PLATFORM=tiktok  platform to test: tiktok | youtube | both
#   TIKTOKDUR=90     TikTok clip length (s, > 60)
#   START=120        start second: skips the intro (often no dialogue) to test a
#                    spoken section; set START=0 to test the very beginning
#   REFRAME=track    track | center | none
#
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f venv/bin/activate ]; then
  echo "venv not found. Run first: python3 -m venv venv && pip install -r requirements.txt"
  exit 1
fi
# shellcheck disable=SC1091
source venv/bin/activate

MODEL="${MODEL:-tiny}"
LIMIT="${LIMIT:-1}"
PLATFORM="${PLATFORM:-tiktok}"
TIKTOKDUR="${TIKTOKDUR:-90}"
START="${START:-120}"
REFRAME="${REFRAME:-track}"

# Videos: passed as arguments, otherwise the first 2 in input_videos/.
if [ "$#" -gt 0 ]; then
  videos=("$@")
else
  videos=()
  while IFS= read -r f; do videos+=("$f"); done < <(ls input_videos/*.mp4 2>/dev/null | head -2)
fi

if [ "${#videos[@]}" -eq 0 ]; then
  echo "No video found (input_videos/*.mp4 is empty and no argument was given)."
  exit 1
fi

echo "Quick test - model=$MODEL platform=$PLATFORM clips=$LIMIT from=${START}s reframe=$REFRAME"
echo "${#videos[@]} video(s) -> quicktest/"
echo

for v in "${videos[@]}"; do
  if [ ! -f "$v" ]; then
    echo "Skipped (not found): $v"
    continue
  fi
  stem="$(basename "${v%.*}")"
  echo "----------------------------------------------------------"
  echo "> $v"
  python3 -m smartsplit split "$v" \
    --model "$MODEL" --limit "$LIMIT" --platform "$PLATFORM" --tiktok-duration "$TIKTOKDUR" \
    --start "$START" --reframe "$REFRAME" --out-dir "quicktest/$stem"
  echo
done

echo "Quick test done. Results in: quicktest/"
open quicktest/ 2>/dev/null || true
