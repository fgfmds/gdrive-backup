# SESSION_STATE — gdrive-backup

**Last Updated:** 2026-02-24T12:45:00Z

---

## Project Status: Feature-Complete

All planned features are implemented and committed. No known bugs.

---

## What's Built

| Feature | Status | Commit |
|---------|--------|--------|
| Core rclone sync to Google Drive | Done | `e997367` |
| Versioned archiving (changed + deleted files) | Done | `cd56e9e` |
| Multiple source directories per config | Done | `1571e9d` |
| Cron automation (install/remove/status) | Done | `b78e76a` |
| Restore from Drive to local | Done | `e997367` |
| Dry-run preview mode | Done | `e997367` |
| Configurable retention + auto-prune | Done | `cd56e9e` |
| Global + per-source exclude patterns | Done | `1571e9d` |
| Optional rclone crypt encryption | Done | `9a4918f` |
| Cross-machine crypt export/import | Done | (pending commit) |

---

## Current Config (this machine)

- **Source:** `/mnt/d/Lumina/ai-agents/claude` -> `gdrive:backups/claude-projects/`
- **Self-exclude:** `gdrive-backup/**`
- **Schedule:** Daily at 2 AM
- **Retention:** 5 changed, 10 deleted
- **Encryption:** Not yet enabled (rclone crypt support available)

---

## Key Decisions

1. **Server-side archiving** — old file versions are copied within Drive (no re-download), keeping bandwidth low.
2. **Per-source log directories** — logs live inside each source's `logs/` folder, not centrally.
3. **TOML config** — uses Python 3.11+ `tomllib` (no external dependencies).
4. **Single Python file** — `_backup_impl.py` contains all logic; `backup.sh` is a thin wrapper.
5. **Crypt wraps at root level** — `gdrive-crypt` wraps `gdrive:` (not `gdrive:backups/`), so `root = "backups"` stays unchanged in config. Zero changes needed to backup/restore logic.
6. **Crypt config export/import** — `setup.sh --export-crypt` / `--import-crypt` for safe cross-machine encryption setup (avoids password retyping and typo risk).

---

## What's Next

- [ ] Run first real backup (not just dry-run)
- [ ] Enable encryption (`./setup.sh` -> enable crypt -> update config.toml)
- [ ] Install cron job (`./backup.sh --cron-install`)
- [ ] Add more source directories as needed
- [ ] Consider: email/notification on backup failure
- [ ] Consider: bandwidth throttling options in config
