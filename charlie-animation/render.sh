#!/usr/bin/env bash
# Build, render and encode CHARLIE.  Usage: ./render.sh [WxH] [samples]
set -euo pipefail
cd "$(dirname "$0")"
RES="${1:-960x540}"
SAMPLES="${2:-14}"
BLENDER="${BLENDER:-blender}"

"$BLENDER" -b -P build_charlie.py -- --save charlie.blend --render frames/ \
  --res "$RES" --samples "$SAMPLES"
python3 make_soundtrack.py soundtrack.wav
ffmpeg -y -framerate 24 -i frames/frame_%04d.png -i soundtrack.wav \
  -c:v libx264 -pix_fmt yuv420p -crf 18 -preset slow -c:a aac -b:a 160k -shortest \
  charlie.mp4
echo "done -> charlie.mp4"
