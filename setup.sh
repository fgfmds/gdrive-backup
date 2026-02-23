#!/bin/bash
# setup.sh — Install rclone and configure Google Drive remote
# Run this once per machine before using backup.sh
set -euo pipefail

REMOTE_NAME="${1:-gdrive}"

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
        echo "Remote '$REMOTE_NAME' is working. You're all set."
        echo ""
        echo "Next steps:"
        echo "  1. Copy config.template.toml to config.toml"
        echo "  2. Edit config.toml with your project path and Drive folder"
        echo "  3. Run: ./backup.sh --dry-run"
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
        echo ""
        echo "=== Setup complete ==="
        echo ""
        echo "Next steps:"
        echo "  1. Copy config.template.toml to config.toml"
        echo "  2. Edit config.toml with your project path and Drive folder"
        echo "  3. Run: ./backup.sh --dry-run"
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
