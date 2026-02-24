# gdrive-backup

Sync entire directory trees to Google Drive using [rclone](https://rclone.org/) with versioned archiving of changed and deleted files. Configure once per machine, back up multiple project directories with a single command.

## How It Works

```
Local machine                          Google Drive
─────────────                          ────────────
/projects/                             backups/
  llm-harness/         ──sync──►         claude-projects/
  drafter/                                 current/           ← latest mirror
  rcl-hybrid/                                llm-harness/
                                             drafter/
/training-data/        ──sync──►               rcl-hybrid/
  llm-data/                                .changed/
  datasets/                                  2026-02-23/      ← old versions of modified files
                                           .deleted/
                                             2026-02-23/      ← files removed locally
                                       training-data/
                                         current/
                                           llm-data/
                                           datasets/
                                         .changed/
                                         .deleted/
```

Each backup run, per source:

1. **Compares** local vs remote to classify every file (unchanged, changed, new, deleted)
2. **Archives changed files** — server-side copy of old version from `current/` to `.changed/<timestamp>/`
3. **Archives deleted files** — server-side copy from `current/` to `.deleted/<timestamp>/`
4. **Syncs** — updates `current/` to match local (only uploads new/changed files)
5. **Prunes** — removes old version directories beyond the configured retention limits

Unchanged files are never re-uploaded or duplicated.

## Quick Start

```bash
# 1. Clone this repo
git clone https://github.com/fgfmds/gdrive-backup.git
cd gdrive-backup

# 2. Install rclone and authenticate with Google Drive
./setup.sh

# 3. Create a config
cp config.template.toml config.toml
# Edit config.toml — add your directory trees

# 4. Preview what would be backed up
./backup.sh --dry-run

# 5. Run the actual backup
./backup.sh
```

## Encryption (Optional)

All backups can be encrypted at rest using rclone's built-in crypt remote. File contents, names, and directory names are encrypted before upload.

### How it works

rclone crypt creates a transparent encryption layer:

```
local -> gdrive-crypt:backups/   (encrypts automatically)
         └── wraps gdrive:       (the actual Google Drive remote)
```

All backup operations (sync, archive, prune, restore) work identically through the encrypted remote. No changes to your workflow.

### Enable encryption

1. Run setup with encryption:
   ```bash
   ./setup.sh
   # Answer 'y' when asked about encryption
   ```

2. Update `config.toml`:
   ```toml
   [remote]
   name = "gdrive-crypt"    # Use the encrypted remote
   root = "backups"
   ```

3. Back up as usual:
   ```bash
   ./backup.sh --dry-run
   ./backup.sh
   ```

### Important warnings

- **Password loss = permanent data loss.** There is no recovery mechanism. Store your encryption password in a password manager or other secure location.
- **Switching from unencrypted to encrypted** does not migrate existing data. Old unencrypted files remain on Drive and a fresh full upload occurs. Delete old unencrypted data manually after verifying encrypted backups work.
- **Inspect encrypted files** using the crypt remote:
  ```bash
  rclone ls gdrive-crypt:backups/claude-projects/current/
  ```
  Looking at `gdrive:backups/` directly will show encrypted filenames.

### Share encryption across machines

All machines must use the **same encryption password** to read each other's backups. Rather than retyping the password (risking typos), export the crypt config from one machine and import it on others:

```bash
# On Machine A (where encryption is already set up):
./setup.sh --export-crypt crypt-config.json

# Transfer the file to Machine B (scp, USB, etc.)

# On Machine B (after running ./setup.sh for the base remote):
./setup.sh --import-crypt crypt-config.json

# Delete the config file after importing
rm crypt-config.json
```

The exported file contains the obscured (not plaintext) password. Delete it after importing — do not commit it to git.

### Add encryption to an existing setup

If you already have a working unencrypted backup:

```bash
# 1. Create the crypt remote manually
rclone config create gdrive-crypt crypt remote=gdrive: \
    filename_encryption=standard directory_name_encryption=true
rclone config password gdrive-crypt password YOUR_PASSWORD

# 2. Change name in config.toml from "gdrive" to "gdrive-crypt"

# 3. Run a full backup (all files re-uploaded encrypted)
./backup.sh

# 4. After verifying, remove old unencrypted data
rclone purge gdrive:backups/
```

## Prerequisites

- **Python 3.11+** (for TOML config parsing via `tomllib`)
- **Google account** with Drive access
- **Browser access** for initial OAuth (WSL2 can use the Windows browser)

## Files

| File | Purpose |
|------|---------|
| `backup.sh` | Entry point — checks dependencies, calls Python implementation |
| `_backup_impl.py` | Core logic — classification, archiving, sync, pruning |
| `setup.sh` | One-time setup — installs rclone and configures Drive auth |
| `config.template.toml` | Template config — copy to `config.toml` and customize |

## Usage

### Back up all sources

```bash
./backup.sh
```

### Back up a single source

```bash
./backup.sh --source claude-projects
```

### Preview without uploading

```bash
./backup.sh --dry-run
```

### Restore from Drive to local

```bash
# Restore all sources
./backup.sh --restore

# Restore one source
./backup.sh --restore --source claude-projects

# Preview restore
./backup.sh --restore --dry-run
```

### Custom config path

```bash
./backup.sh --config /path/to/config.toml
```

### Inspect remote files

```bash
# List backup folders on Drive
rclone lsd gdrive:backups/

# List current files for a source
rclone ls gdrive:backups/claude-projects/current/

# List changed-file archives
rclone lsd gdrive:backups/claude-projects/.changed/

# List deleted-file archives
rclone lsd gdrive:backups/claude-projects/.deleted/

# Check total backup size
rclone size gdrive:backups/
```

## Config Reference

```toml
[remote]
name = "gdrive"          # rclone remote name (from setup)
root = "backups"          # Root folder on Google Drive

[versions]
keep_changed = 5          # Retain 5 most recent changed-file archives
keep_deleted = 10         # Retain 10 most recent deleted-file archives

[schedule]
cron = "0 2 * * *"        # Cron expression for --cron-install (default)

[exclude]
patterns = [              # Global excludes — applied to ALL sources
    ".git/**",
    "__pycache__/**",
    "*.pyc",
    ".remote_secrets.toml",
]

[[sources]]
path = "/path/to/projects"         # Local directory tree
folder = "my-projects"             # Subfolder under remote.root on Drive
# exclude = ["large-data/**"]      # Optional per-source excludes

[[sources]]
path = "/path/to/training-data"
folder = "training-data"
```

### Config fields

| Field | Required | Default | Description |
|-------|:--------:|:-------:|-------------|
| `remote.name` | Yes | — | rclone remote name (created during `./setup.sh`) |
| `remote.root` | Yes | — | Root folder on Google Drive for all backups |
| `versions.keep_changed` | No | 5 | Number of changed-file archive directories to retain |
| `versions.keep_deleted` | No | 10 | Number of deleted-file archive directories to retain |
| `schedule.cron` | No | `0 2 * * *` | Cron expression used by `--cron-install` |
| `exclude.patterns` | No | [] | Global exclude patterns applied to all sources |
| `sources[].path` | Yes | — | Absolute path to directory tree to back up |
| `sources[].folder` | Yes | — | Subfolder name under `remote.root` on Drive |
| `sources[].exclude` | No | [] | Additional exclude patterns for this source only |

### Version retention example

With `keep_changed = 3` and `keep_deleted = 5`:

- `.changed/` keeps the 3 most recent timestamp directories. Older ones are automatically deleted.
- `.deleted/` keeps the 5 most recent timestamp directories. Older ones are automatically deleted.
- Empty archive runs (no changed/deleted files) do not create empty directories.

### Exclude pattern syntax

Uses [rclone filtering rules](https://rclone.org/filtering/):

| Pattern | Matches |
|---------|---------|
| `*.pyc` | All `.pyc` files anywhere |
| `.git/**` | The `.git` directory and everything in it |
| `logs/` | Any directory named `logs` |
| `secret.txt` | Any file named `secret.txt` |

## Logging

Each backup run creates a timestamped log file in each source's `logs/` directory:

```
/path/to/projects/logs/2026-02-23_14-30-00_gdrive_backup.log
/path/to/training-data/logs/2026-02-23_14-30-00_gdrive_backup.log
```

## Automation

Schedule backups to run automatically via cron. Works on Linux (native and WSL2) and macOS.

### Set up automated backups

```bash
# Install cron job (uses schedule from config.toml)
./backup.sh --cron-install

# Check status — last backup time and cron schedule
./backup.sh --status

# Remove the cron job
./backup.sh --cron-remove
```

### Configure the schedule

Add a `[schedule]` section to `config.toml`:

```toml
[schedule]
cron = "0 2 * * *"    # Daily at 2:00 AM (default)
```

Common schedules:

| Schedule | Cron Expression |
|----------|----------------|
| Daily at 2 AM | `0 2 * * *` |
| Every 6 hours | `0 */6 * * *` |
| Weekdays at midnight | `0 0 * * 1-5` |
| Every Sunday at 3 AM | `0 3 * * 0` |

### How it works

- `--cron-install` adds an entry to your user's crontab (no sudo required)
- The cron job runs `backup.sh` with the absolute path to your `config.toml`
- Output is appended to `logs/cron_backup.log` in the gdrive-backup directory
- Each config file gets its own cron entry — multiple configs can coexist
- Re-running `--cron-install` replaces the existing entry (no duplicates)

### Verify cron is running

```bash
# Check that cron service is active
# Linux/WSL2:
service cron status

# macOS:
launchctl list | grep cron

# View your crontab
crontab -l
```

## Deploying to Another Machine

1. Clone the repo: `git clone https://github.com/fgfmds/gdrive-backup.git`
2. Run setup: `./setup.sh` (installs rclone, authenticates with Google Drive)
3. Import encryption (if using crypt): `./setup.sh --import-crypt crypt-config.json`
4. Create config: `cp config.template.toml config.toml` and edit with local paths
5. Test: `./backup.sh --dry-run`
6. Automate: `./backup.sh --cron-install`

Each machine has its own `config.toml` with its local paths. The `config.toml` file is gitignored so it won't conflict across machines.

### Cross-machine encryption

If Machine A already has encryption set up, export the config before deploying to Machine B:

```bash
# Machine A: export crypt config
./setup.sh --export-crypt crypt-config.json
# Transfer crypt-config.json to Machine B

# Machine B: after step 2 (base remote created)
./setup.sh --import-crypt crypt-config.json
rm crypt-config.json
```

This ensures both machines use identical encryption keys. Data encrypted by Machine A can be decrypted by Machine B and vice versa.

## Troubleshooting

### WSL2: Browser doesn't open for OAuth

If the browser doesn't open automatically during `./setup.sh`:

1. Run `rclone config` and choose your remote
2. When asked "Use auto config?", answer `n`
3. rclone will print a URL — copy it and open in your Windows browser
4. Complete the OAuth flow, then paste the token back into the terminal

### Token expired

rclone tokens auto-refresh. If auth fails after a long time:

```bash
rclone config reconnect gdrive:
```

### "Remote not found" error

Make sure the remote name in `config.toml` matches what you created:

```bash
rclone listremotes
```

### Slow uploads

rclone defaults are conservative. For faster transfers on good connections, edit `_backup_impl.py` sync args:

```python
"--transfers", "8",              # Parallel file transfers (default: 4)
"--drive-chunk-size", "64M",     # Larger upload chunks (default: 8M)
```

## License

MIT
