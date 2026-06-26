#!/usr/bin/env bash

set -euo pipefail

if [[ "${DEBUG:-0}" == "1" ]]; then
    set -x
fi

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <NAME>" >&2
    echo "Environment: LIST_FILE, OUTPUT_DIR, DEBUG=1" >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NAME="$1"
LIST_FILE="${LIST_FILE:-${SCRIPT_DIR}/data/list.txt}"
OUTPUT_DIR="${OUTPUT_DIR:-${HOME}/work/c-work/8007-output}"
OUTPUT_FILE="${OUTPUT_DIR}/${NAME}.mov"

if [[ ! -s "$LIST_FILE" ]]; then
    echo "Input list is missing or empty: $LIST_FILE" >&2
    echo "Run list.sh first, or set LIST_FILE to a populated list file." >&2
    exit 1
fi

mkdir -p "$OUTPUT_DIR"

uv run concatenate_videos.py \
    --reverse \
    --inputs-file "$LIST_FILE" \
    --output "$OUTPUT_FILE"
