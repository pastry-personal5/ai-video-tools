#!/usr/bin/env bash

set -euo pipefail

if [[ "${DEBUG:-0}" == "1" ]]; then
    set -x
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${SOURCE_DIR:-${HOME}/work/c-work/8005-output}"
LIST_FILE="${LIST_FILE:-${SCRIPT_DIR}/data/list.txt}"

if [[ ! -d "$SOURCE_DIR" ]]; then
    echo "Source directory does not exist: $SOURCE_DIR" >&2
    exit 1
fi

mkdir -p "$(dirname "$LIST_FILE")"

find "$SOURCE_DIR" -maxdepth 1 -type f -name "*.mov" -exec stat -f "%m %N" {} + \
    | sort -rn \
    | cut -d' ' -f2- \
    > "$LIST_FILE"

cat "$LIST_FILE"
