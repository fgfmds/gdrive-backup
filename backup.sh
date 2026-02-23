#!/bin/bash
# backup.sh — Sync directory trees to Google Drive via rclone
#              with versioned archiving of changed and deleted files
# Usage: ./backup.sh [--config <path>] [--dry-run] [--restore] [--source <name>]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Check dependencies ───────────────────────────────────────────────
if ! command -v rclone &>/dev/null; then
    echo "Error: rclone is not installed. Run ./setup.sh first." >&2
    exit 1
fi

if ! python3 -c "import tomllib" &>/dev/null; then
    echo "Error: Python 3.11+ required (for tomllib). Found: $(python3 --version)" >&2
    exit 1
fi

# ── Forward all arguments to Python implementation ───────────────────
exec python3 -u "${SCRIPT_DIR}/_backup_impl.py" "$@"
