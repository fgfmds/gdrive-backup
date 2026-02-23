#!/bin/bash
# backup.sh — Sync a project directory to Google Drive via rclone
# Usage: ./backup.sh [--config <path>] [--dry-run] [--restore]
set -euo pipefail

# ── Defaults ─────────────────────────────────────────────────────────
CONFIG_FILE="./config.toml"
DRY_RUN=false
RESTORE=false

# ── Parse arguments ──────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --restore)
            RESTORE=true
            shift
            ;;
        -h|--help)
            echo "Usage: $(basename "$0") [--config <path>] [--dry-run] [--restore]"
            echo ""
            echo "Options:"
            echo "  --config <path>  Path to config.toml (default: ./config.toml)"
            echo "  --dry-run        Preview what would be transferred (no actual upload)"
            echo "  --restore        Download from Drive to local (reverse direction)"
            echo "  -h, --help       Show this help message"
            exit 0
            ;;
        *)
            echo "Error: Unknown argument '$1'. Use --help for usage." >&2
            exit 1
            ;;
    esac
done

# ── Check dependencies ───────────────────────────────────────────────
if ! command -v rclone &>/dev/null; then
    echo "Error: rclone is not installed. Run ./setup.sh first." >&2
    exit 1
fi

# ── Read config ──────────────────────────────────────────────────────
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "Error: Config file not found: $CONFIG_FILE" >&2
    echo "Copy config.template.toml to config.toml and edit it." >&2
    exit 1
fi

# Parse TOML config using Python (available everywhere, handles TOML properly)
eval "$(python3 -c "
import tomllib, sys, shlex
with open(sys.argv[1], 'rb') as f:
    cfg = tomllib.load(f)
print(f'REMOTE_NAME={shlex.quote(cfg[\"remote\"][\"name\"])}')
print(f'REMOTE_FOLDER={shlex.quote(cfg[\"remote\"][\"folder\"])}')
print(f'SOURCE_PATH={shlex.quote(cfg[\"source\"][\"path\"])}')
# Build exclude flags
excludes = cfg.get('exclude', {}).get('patterns', [])
parts = []
for e in excludes:
    parts.append(f'--exclude {shlex.quote(e)}')
print(f'EXCLUDE_FLAGS={chr(34)}{\" \".join(parts)}{chr(34)}')
" "$CONFIG_FILE")"

# ── Validate config ──────────────────────────────────────────────────
if [[ ! -d "$SOURCE_PATH" ]]; then
    echo "Error: Source path does not exist: $SOURCE_PATH" >&2
    exit 1
fi

# Check rclone remote exists
if ! rclone listremotes | grep -q "^${REMOTE_NAME}:$"; then
    echo "Error: rclone remote '$REMOTE_NAME' not found." >&2
    echo "Run: rclone config  (or ./setup.sh)" >&2
    exit 1
fi

REMOTE_DEST="${REMOTE_NAME}:${REMOTE_FOLDER}"

# ── Set up logging ───────────────────────────────────────────────────
LOG_DIR="${SOURCE_PATH}/logs"
mkdir -p "$LOG_DIR"
TIMESTAMP=$(date '+%Y-%m-%d_%H-%M-%S')

if $RESTORE; then
    LOGFILE="${LOG_DIR}/${TIMESTAMP}_gdrive_restore.log"
    DIRECTION_LABEL="RESTORE"
    RCLONE_SRC="$REMOTE_DEST"
    RCLONE_DST="$SOURCE_PATH"
else
    LOGFILE="${LOG_DIR}/${TIMESTAMP}_gdrive_backup.log"
    DIRECTION_LABEL="BACKUP"
    RCLONE_SRC="$SOURCE_PATH"
    RCLONE_DST="$REMOTE_DEST"
fi

# ── Build rclone command ─────────────────────────────────────────────
RCLONE_CMD="rclone sync"
RCLONE_ARGS=(
    "$RCLONE_SRC"
    "$RCLONE_DST"
    --progress
    --stats-one-line
    --stats 10s
    --log-file "$LOGFILE"
    --log-level INFO
)

# Add exclude flags
eval "RCLONE_ARGS+=($EXCLUDE_FLAGS)"

if $DRY_RUN; then
    RCLONE_ARGS+=(--dry-run)
fi

# ── Run backup ───────────────────────────────────────────────────────
echo "=== Google Drive ${DIRECTION_LABEL} ==="
echo "Started:  $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "Source:   $RCLONE_SRC"
echo "Dest:     $RCLONE_DST"
echo "Log:      $LOGFILE"
if $DRY_RUN; then
    echo "Mode:     DRY RUN (no files will be transferred)"
fi
echo ""

# Run rclone with live progress to terminal + log file
if $RCLONE_CMD "${RCLONE_ARGS[@]}"; then
    EXIT_CODE=0
    echo ""
    echo "=== ${DIRECTION_LABEL} COMPLETE ==="
else
    EXIT_CODE=$?
    echo ""
    echo "=== ${DIRECTION_LABEL} FAILED (exit code: $EXIT_CODE) ==="
fi

echo "Finished: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo "Log:      $LOGFILE"

# ── Show transfer summary from log ──────────────────────────────────
if [[ -f "$LOGFILE" ]]; then
    echo ""
    echo "--- Transfer Summary ---"
    grep -E "(Transferred|Checks|Elapsed|Errors)" "$LOGFILE" | tail -6
fi

exit $EXIT_CODE
