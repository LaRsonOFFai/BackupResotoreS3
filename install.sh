#!/bin/bash

set -euo pipefail

REPO_RAW="https://raw.githubusercontent.com/LaRsonOFFai/BackupResotoreS3/main"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

download_file() {
    local url="$1"
    local output="$2"

    if command -v curl >/dev/null 2>&1; then
        curl -fsSL "$url" -o "$output"
        return
    fi

    if command -v wget >/dev/null 2>&1; then
        wget -qO "$output" "$url"
        return
    fi

    echo "curl or wget is required."
    exit 1
}

echo "Downloading installer files..."
download_file "$REPO_RAW/setup.sh" "$TMP_DIR/setup.sh"
download_file "$REPO_RAW/backup_tool.py" "$TMP_DIR/backup_tool.py"
download_file "$REPO_RAW/requirements.txt" "$TMP_DIR/requirements.txt"

chmod +x "$TMP_DIR/setup.sh"

echo "Starting installation..."
cd "$TMP_DIR"
exec bash "$TMP_DIR/setup.sh"
