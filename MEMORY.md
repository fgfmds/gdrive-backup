<!-- SYNC RULE: This file has a git-tracked copy at the project root (MEMORY.md).
     Whenever you update this file, copy it to /mnt/d/Lumina/ai-agents/claude/gdrive-backup/MEMORY.md
     and vice versa. Both copies must always have identical content. -->

# gdrive-backup — Project Memory

## Overview
Google Drive backup tool using rclone. Syncs local directory trees to Drive with versioned archiving of changed/deleted files.

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
| `setup.sh` | One-time rclone install + OAuth |
| `check_status.py` | Session-start status overview |
| `SESSION_STATE.md` | Current project state + decisions |

## Current Config (ffarhat workstation)
- Source: `/mnt/d/Lumina/ai-agents/claude` -> `gdrive:backups/claude-projects/`
- Self-excludes `gdrive-backup/**`
- Schedule: Daily 2 AM, retention: 5 changed / 10 deleted

## Git
- Remote: `https://github.com/fgfmds/gdrive-backup.git`
- Branch: `master`
- 4 commits as of 2026-02-24

## Status
Feature-complete. Next steps: first real backup, cron install, possibly add more sources.
