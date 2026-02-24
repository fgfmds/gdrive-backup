#!/bin/bash
# setup.sh — Install rclone and configure Google Drive remote
# Run this once per machine before using backup.sh
set -euo pipefail

REMOTE_NAME="${1:-gdrive}"

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

# ── Main ─────────────────────────────────────────────────────────────

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
