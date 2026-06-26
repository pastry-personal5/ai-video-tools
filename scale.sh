#!/usr/bin/env bash

set -euo pipefail

if [[ "${DEBUG:-0}" == "1" ]]; then
    set -x
fi

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <NAME>" >&2
    echo "Environment: OUTPUT_DIR, TARGET_HEIGHT, DEBUG=1" >&2
    exit 1
fi

NAME="$1"
OUTPUT_DIR="${OUTPUT_DIR:-${HOME}/work/c-work/8007-output}"
TARGET_HEIGHT="${TARGET_HEIGHT:-2160}"
INPUT_FILE="${OUTPUT_DIR}/${NAME}.mov"
OUTPUT_FILE="${OUTPUT_DIR}/${NAME}_${TARGET_HEIGHT}p.mov"

if [[ ! -f "$INPUT_FILE" ]]; then
    echo "Input video does not exist: $INPUT_FILE" >&2
    exit 1
fi

uv run upscale_video_fx.py \
    "$INPUT_FILE" \
    "$OUTPUT_FILE" \
    --height "$TARGET_HEIGHT"
