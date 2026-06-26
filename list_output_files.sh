#!/usr/bin/env bash

set -euo pipefail

if [[ "${DEBUG:-0}" == "1" ]]; then
    set -x
fi

OUTPUT_DIR="${OUTPUT_DIR:-${HOME}/work/c-work/8007-output}"

if [[ ! -d "$OUTPUT_DIR" ]]; then
    echo "Output directory does not exist: $OUTPUT_DIR" >&2
    exit 1
fi

ls -lt "$OUTPUT_DIR"
