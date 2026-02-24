<!-- SYNC RULE: This file has a git-tracked copy at the project root (MEMORY.md).
     Whenever you update this file, copy it to /mnt/d/Lumina/ai-agents/claude/gdrive-backup/MEMORY.md
     and vice versa. Both copies must always have identical content. -->

# gdrive-backup — Project Memory

## Overview
Google Drive backup tool using rclone. Syncs local directory trees to Drive with versioned archiving of changed/deleted files. Optional client-side encryption via rclone crypt with cross-machine export/import.

## Architecture
- **Single Python file**: `_backup_impl.py` (all logic)
- **Shell wrapper**: `backup.sh` (dependency check + exec)
- **Config**: `config.toml` (TOML, parsed with Python 3.11+ `tomllib`)
- **No external Python dependencies** — stdlib only
- Flat project structure (no `scripts/` or `src/` directories)

## Key Files
| File | Purpose |
|------|---------|
| `_backup_impl.py` | Core logic — classify, archive, sync, prune, cron |
| `backup.sh` | Entry point — checks rclone + python, forwards to impl |
| `config.toml` | Machine-specific config (gitignored) |
| `config.template.toml` | Template for new machines |
| `setup.sh` | One-time rclone install + OAuth + optional crypt setup + export/import |
| `check_status.py` | Session-start status overview |
| `SESSION_STATE.md` | Current project state + decisions |

## Encryption
- rclone crypt wraps at root level: `gdrive-crypt` wraps `gdrive:`
- Config just changes `name = "gdrive-crypt"` — `root` stays the same
- All backup/restore/archive/prune logic is unchanged (crypt is transparent)
- `setup.sh` offers optional crypt setup after base remote verification
- `setup.sh --export-crypt [file]` / `--import-crypt <file>` for cross-machine setup
- Export uses `rclone config dump` (JSON, obscured passwords) — portable across machines
- Password loss = permanent data loss (prominently warned)

## Current Config (ffarhat workstation)
- Source: `/mnt/d/Lumina/ai-agents/claude` -> `gdrive:backups/claude-projects/`
- Self-excludes `gdrive-backup/**`
- Schedule: Daily 2 AM, retention: 5 changed / 10 deleted
- Encryption: not yet enabled

## Git
- Remote: `https://github.com/fgfmds/gdrive-backup.git`
- Branch: `master`
- 7 commits as of 2026-02-24

## Status
Feature-complete (including encryption + cross-machine export/import). Next steps: first real backup, enable crypt, cron install.
