#!/bin/bash
# setup.sh — Install rclone and configure Google Drive remote
# Run this once per machine before using backup.sh
#
# Usage:
#   ./setup.sh [remote-name]          Normal setup (default remote: gdrive)
#   ./setup.sh --export-crypt [file]  Export crypt config for another machine
#   ./setup.sh --import-crypt <file>  Import crypt config from another machine
set -euo pipefail

# ── Helper: Offer optional encryption setup ──────────────────────────
offer_crypt_setup() {
    local base_remote="$1"
    local crypt_name="${base_remote}-crypt"

    echo ""
    echo "--- Optional: Encrypt backups ---"
    echo ""
    echo "rclone crypt encrypts all file contents and names before upload."
    echo "Files on Google Drive will be unreadable without the password."
    echo ""
    echo "  WARNING: If you lose the encryption password, your backups"
    echo "           are PERMANENTLY UNRECOVERABLE. Store it safely"
    echo "           (password manager, printed copy, etc.)."
    echo ""
    echo "  TIP: If another machine already has encryption set up, use"
    echo "       ./setup.sh --import-crypt <file> instead to ensure"
    echo "       the same password is used."
    echo ""

    read -p "Enable encryption? [y/N] " enable_crypt
    if [[ "${enable_crypt,,}" != "y" ]]; then
        return 0
    fi

    # Check if crypt remote already exists
    if rclone listremotes 2>/dev/null | grep -q "^${crypt_name}:$"; then
        echo ""
        echo "Encrypted remote '$crypt_name' already exists."
        echo "To recreate, first remove it: rclone config delete $crypt_name"
        return 0
    fi

    echo ""

    # Password entry (hidden input)
    while true; do
        read -sp "Encryption password: " crypt_pass
        echo
        read -sp "Confirm password: " crypt_pass2
        echo
        if [[ "$crypt_pass" == "$crypt_pass2" ]]; then
            break
        fi
        echo "Passwords don't match. Try again."
        echo ""
    done

    # Optional salt (second password)
    local salt_pass=""
    echo ""
    read -p "Add a salt password for extra security? [y/N] " add_salt
    if [[ "${add_salt,,}" == "y" ]]; then
        while true; do
            read -sp "Salt password: " salt_pass
            echo
            read -sp "Confirm salt: " salt_pass2
            echo
            if [[ "$salt_pass" == "$salt_pass2" ]]; then
                break
            fi
            echo "Passwords don't match. Try again."
            echo ""
        done
    fi

    echo ""
    echo "Creating encrypted remote '$crypt_name' wrapping '$base_remote:'..."

    # Create the crypt remote (non-interactive)
    rclone config create "$crypt_name" crypt \
        remote="${base_remote}:" \
        filename_encryption=standard \
        directory_name_encryption=true

    # Set passwords (rclone config password auto-obscures)
    rclone config password "$crypt_name" password "$crypt_pass"
    if [[ -n "$salt_pass" ]]; then
        rclone config password "$crypt_name" password2 "$salt_pass"
    fi

    # Clear passwords from shell variables
    unset crypt_pass crypt_pass2 salt_pass salt_pass2

    # Verify
    echo ""
    if rclone lsd "${crypt_name}:" --max-depth 0 &>/dev/null; then
        echo "Encrypted remote '$crypt_name' is working."
        echo ""
        echo "  To copy this encryption config to another machine:"
        echo "    ./setup.sh --export-crypt"
        CRYPT_CREATED="$crypt_name"
    else
        echo "Warning: Encrypted remote created but verification failed."
        echo "Check: rclone config show $crypt_name"
    fi
}

# ── Helper: Print next steps ─────────────────────────────────────────
print_next_steps() {
    echo ""
    echo "Next steps:"
    echo "  1. Copy config.template.toml to config.toml"
    echo "  2. Edit config.toml with your project path and Drive folder"
    if [[ -n "${CRYPT_CREATED:-}" ]]; then
        echo "  3. Set name = \"$CRYPT_CREATED\" in config.toml for encrypted backups"
        echo "  4. Run: ./backup.sh --dry-run"
    else
        echo "  3. Run: ./backup.sh --dry-run"
    fi
}

# ── Export crypt config ──────────────────────────────────────────────
do_export_crypt() {
    local outfile="${1:-crypt-config.json}"
    local remote_name="${REMOTE_NAME:-gdrive}"
    local crypt_name="${remote_name}-crypt"

    if ! command -v rclone &>/dev/null; then
        echo "Error: rclone is not installed." >&2
        exit 1
    fi

    if ! rclone listremotes 2>/dev/null | grep -q "^${crypt_name}:$"; then
        echo "Error: Encrypted remote '$crypt_name' not found." >&2
        echo "Set up encryption first: ./setup.sh" >&2
        exit 1
    fi

    # Extract crypt remote config as JSON using rclone config dump + python3
    python3 -c "
import json, subprocess, sys

dump = subprocess.run(['rclone', 'config', 'dump'], capture_output=True, text=True)
if dump.returncode != 0:
    print('Error: rclone config dump failed', file=sys.stderr)
    sys.exit(1)

all_remotes = json.loads(dump.stdout)
crypt_name = '${crypt_name}'

if crypt_name not in all_remotes:
    print(f'Error: {crypt_name} not found in rclone config', file=sys.stderr)
    sys.exit(1)

export = {crypt_name: all_remotes[crypt_name]}

with open('${outfile}', 'w') as f:
    json.dump(export, f, indent=2)
    f.write('\n')

print(f'Exported: {crypt_name}')
"

    echo ""
    echo "Crypt config saved to: $outfile"
    echo ""
    echo "Transfer this file to the other machine, then run:"
    echo "  ./setup.sh --import-crypt $outfile"
    echo ""
    echo "  SECURITY: This file contains your obscured encryption password."
    echo "  Delete it after importing. Do not commit it to git."
}

# ── Import crypt config ──────────────────────────────────────────────
do_import_crypt() {
    local infile="${1:-}"

    if [[ -z "$infile" ]]; then
        echo "Error: No input file specified." >&2
        echo "Usage: ./setup.sh --import-crypt <file>" >&2
        exit 1
    fi

    if [[ ! -f "$infile" ]]; then
        echo "Error: File not found: $infile" >&2
        exit 1
    fi

    if ! command -v rclone &>/dev/null; then
        echo "Error: rclone is not installed. Run ./setup.sh first." >&2
        exit 1
    fi

    # Import the crypt remote config using python3 + rclone config create
    python3 -c "
import json, subprocess, sys

with open('${infile}') as f:
    data = json.load(f)

if not data:
    print('Error: Empty config file', file=sys.stderr)
    sys.exit(1)

for crypt_name, cfg in data.items():
    if cfg.get('type') != 'crypt':
        print(f'Error: {crypt_name} is not a crypt remote (type={cfg.get(\"type\")})', file=sys.stderr)
        sys.exit(1)

    # Check that the base remote exists
    base_remote = cfg.get('remote', '').rstrip(':').rstrip('/')
    if not base_remote:
        print(f'Error: No base remote found in config', file=sys.stderr)
        sys.exit(1)

    result = subprocess.run(['rclone', 'listremotes'], capture_output=True, text=True)
    remotes = result.stdout.strip().split('\n') if result.stdout.strip() else []
    if f'{base_remote}:' not in remotes:
        print(f'Error: Base remote \"{base_remote}\" not found on this machine.', file=sys.stderr)
        print(f'Run ./setup.sh first to create the Google Drive remote.', file=sys.stderr)
        sys.exit(1)

    # Check if crypt remote already exists
    if f'{crypt_name}:' in remotes:
        print(f'Encrypted remote \"{crypt_name}\" already exists on this machine.')
        print(f'To replace it, first run: rclone config delete {crypt_name}')
        sys.exit(1)

    # Build rclone config create arguments
    # Pass all config fields (including obscured passwords) directly
    args = ['rclone', 'config', 'create', crypt_name, 'crypt']
    for key, value in cfg.items():
        if key == 'type':
            continue
        args.append(f'{key}={value}')
    # Passwords are already obscured, tell rclone not to re-obscure
    args.append('--obscure=false')

    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(f'Error creating remote: {result.stderr.strip()}', file=sys.stderr)
        sys.exit(1)

    print(f'Imported: {crypt_name}')

    # Verify
    result = subprocess.run(['rclone', 'lsd', f'{crypt_name}:', '--max-depth', '0'],
                            capture_output=True, text=True)
    if result.returncode == 0:
        print(f'Verified: {crypt_name} is working.')
    else:
        print(f'Warning: Import succeeded but verification failed.')
        print(f'Check: rclone config show {crypt_name}')
"

    echo ""
    echo "You can now delete the config file: rm $infile"
    echo ""
    echo "Set name = \"$(python3 -c "import json; d=json.load(open('${infile}')); print(list(d.keys())[0])")\" in config.toml"
}

# ── Parse arguments ──────────────────────────────────────────────────

REMOTE_NAME="gdrive"
ACTION="setup"
ACTION_ARG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --export-crypt)
            ACTION="export"
            ACTION_ARG="${2:-}"
            [[ -n "${2:-}" ]] && shift
            shift
            ;;
        --import-crypt)
            ACTION="import"
            ACTION_ARG="${2:-}"
            [[ -n "${2:-}" ]] && shift
            shift
            ;;
        *)
            REMOTE_NAME="$1"
            shift
            ;;
    esac
done

# ── Handle export/import commands ────────────────────────────────────

if [[ "$ACTION" == "export" ]]; then
    do_export_crypt "$ACTION_ARG"
    exit 0
fi

if [[ "$ACTION" == "import" ]]; then
    do_import_crypt "$ACTION_ARG"
    exit 0
fi

# ── Main setup flow ──────────────────────────────────────────────────

CRYPT_CREATED=""

echo "=== Google Drive Backup — Setup ==="
echo "Started: $(date '+%Y-%m-%d %H:%M:%S %Z')"
echo ""

# ── Step 1: Install rclone ───────────────────────────────────────────
echo "--- Step 1: Check rclone installation ---"

if command -v rclone &>/dev/null; then
    echo "rclone is already installed: $(rclone version | head -1)"
else
    echo "rclone not found. Installing..."

    # Try apt first (Debian/Ubuntu), fall back to official installer
    if command -v apt &>/dev/null; then
        echo "Installing via apt..."
        sudo apt update -qq && sudo apt install -y -qq rclone
    else
        echo "Installing via official script..."
        curl -fsSL https://rclone.org/install.sh | sudo bash
    fi

    if command -v rclone &>/dev/null; then
        echo "Installed: $(rclone version | head -1)"
    else
        echo "Error: rclone installation failed." >&2
        exit 1
    fi
fi

echo ""

# ── Step 2: Check for existing remote ────────────────────────────────
echo "--- Step 2: Check rclone remote '$REMOTE_NAME' ---"

if rclone listremotes 2>/dev/null | grep -q "^${REMOTE_NAME}:$"; then
    echo "Remote '$REMOTE_NAME' already exists."
    echo ""

    # Verify it works
    echo "--- Step 3: Verify remote ---"
    if rclone lsd "${REMOTE_NAME}:" --max-depth 0 &>/dev/null; then
        echo "Remote '$REMOTE_NAME' is working."

        offer_crypt_setup "$REMOTE_NAME"

        echo ""
        echo "=== Setup complete ==="
        print_next_steps
        exit 0
    else
        echo "Warning: Remote '$REMOTE_NAME' exists but failed verification."
        echo "You may need to re-authenticate. Run: rclone config reconnect ${REMOTE_NAME}:"
        exit 1
    fi
fi

# ── Step 3: Create new remote ────────────────────────────────────────
echo "Remote '$REMOTE_NAME' not found. Let's set it up."
echo ""
echo "This will open a browser window for Google OAuth."
echo "If you're on a headless server or WSL2 without browser access,"
echo "see the README for remote auth instructions."
echo ""
echo "=== Starting rclone config ==="
echo ""
echo "Follow these prompts:"
echo "  1. Choose 'n' for New remote"
echo "  2. Name: $REMOTE_NAME"
echo "  3. Storage type: search for 'drive' or enter the number for Google Drive"
echo "  4. Client ID: leave blank (press Enter)"
echo "  5. Client Secret: leave blank (press Enter)"
echo "  6. Scope: choose '1' (full access)"
echo "  7. Root folder ID: leave blank (press Enter)"
echo "  8. Service account file: leave blank (press Enter)"
echo "  9. Advanced config: 'n'"
echo "  10. Auto config: 'y' (if you have a browser)"
echo "  11. Team drive: 'n'"
echo "  12. Confirm: 'y'"
echo ""
echo "Starting interactive config now..."
echo ""

rclone config

echo ""

# ── Step 4: Verify ───────────────────────────────────────────────────
echo "--- Verifying remote '$REMOTE_NAME' ---"

if rclone listremotes 2>/dev/null | grep -q "^${REMOTE_NAME}:$"; then
    if rclone lsd "${REMOTE_NAME}:" --max-depth 0 &>/dev/null; then
        echo "Remote '$REMOTE_NAME' is working."

        offer_crypt_setup "$REMOTE_NAME"

        echo ""
        echo "=== Setup complete ==="
        print_next_steps
    else
        echo "Warning: Remote created but verification failed."
        echo "Try: rclone lsd ${REMOTE_NAME}:"
        exit 1
    fi
else
    echo "Error: Remote '$REMOTE_NAME' was not created."
    echo "Please re-run this script or run 'rclone config' manually."
    exit 1
fi
