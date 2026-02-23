# gdrive-backup

Sync project directories to Google Drive using [rclone](https://rclone.org/) with versioned archiving of changed and deleted files. Designed to be reusable across multiple projects and machines.

## How It Works

```
local project/  ──sync──►  Google Drive:
                             backups/my-project/
                               current/           ← latest mirror of your project
                               .changed/
                                 2026-02-23_14-30/ ← old versions of modified files
                                 2026-02-24_10-00/
                               .deleted/
                                 2026-02-23_14-30/ ← files removed from local
                                 2026-02-24_10-00/
```

Each backup run:

1. **Compares** local vs remote to classify every file (unchanged, changed, new, deleted)
2. **Archives changed files** — copies the old version from `current/` to `.changed/<timestamp>/` (server-side, no download)
3. **Archives deleted files** — copies the file from `current/` to `.deleted/<timestamp>/` (server-side, no download)
4. **Syncs** — updates `current/` to match local (only uploads new/changed files)
5. **Prunes** — removes old version directories beyond the configured retention limits

Unchanged files are never re-uploaded or duplicated. Only modified and deleted files consume additional storage in the version archives.

## Quick Start

```bash
# 1. Clone this repo
git clone https://github.com/fgfmds/gdrive-backup.git
cd gdrive-backup

# 2. Install rclone and authenticate with Google Drive
./setup.sh

# 3. Create a config for your project
cp config.template.toml config.toml
# Edit config.toml — set your project path, Drive folder, and retention

# 4. Preview what would be backed up
./backup.sh --dry-run

# 5. Run the actual backup
./backup.sh
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
| `config.template.toml` | Template config — copy to `config.toml` per project |

## Usage

### Backup (local to Drive)

```bash
# Default config (./config.toml)
./backup.sh

# Custom config path
./backup.sh --config /path/to/config.toml

# Preview without uploading
./backup.sh --dry-run
```

### Restore (Drive to local)

```bash
# Download from Drive, overwriting local files
./backup.sh --restore

# Preview what would be restored
./backup.sh --restore --dry-run
```

### List remote files

```bash
# List top-level folders on Drive
rclone lsd gdrive:

# List files in your backup
rclone ls gdrive:backups/my-project/current/

# List archived versions of changed files
rclone lsd gdrive:backups/my-project/.changed/

# List archived versions of deleted files
rclone lsd gdrive:backups/my-project/.deleted/

# Check total backup size
rclone size gdrive:backups/my-project/
```

## Config Reference

```toml
[remote]
name = "gdrive"                    # rclone remote name (from setup)
folder = "backups/my-project"      # Drive folder (auto-created)

[source]
path = "/path/to/your/project"     # Absolute path to project root

[versions]
keep_changed = 5                   # Retain 5 most recent changed-file archives
keep_deleted = 10                  # Retain 10 most recent deleted-file archives

[exclude]
patterns = [                       # Patterns to skip (rclone filter syntax)
    ".git/**",
    "__pycache__/**",
    "*.pyc",
    ".remote_secrets.toml",
]
```

### Config fields

| Field | Required | Default | Description |
|-------|:--------:|:-------:|-------------|
| `remote.name` | Yes | — | Name of the rclone remote (created during `./setup.sh`) |
| `remote.folder` | Yes | — | Destination folder on Google Drive. Created if it doesn't exist. |
| `source.path` | Yes | — | Absolute path to the project directory to back up. |
| `versions.keep_changed` | No | 5 | Number of changed-file archive directories to retain. |
| `versions.keep_deleted` | No | 10 | Number of deleted-file archive directories to retain. |
| `exclude.patterns` | No | [] | List of rclone filter patterns. Files matching these are skipped. |

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

## Multi-Project Setup

Back up multiple projects from the same machine with separate config files:

```bash
# Option A: Named configs in the repo directory
cp config.template.toml llm-harness.toml
cp config.template.toml drafter.toml

./backup.sh --config llm-harness.toml
./backup.sh --config drafter.toml

# Option B: Store configs alongside each project
cp config.template.toml /path/to/project-a/gdrive-backup.toml
cp config.template.toml /path/to/project-b/gdrive-backup.toml

./backup.sh --config /path/to/project-a/gdrive-backup.toml
```

## Logging

Each backup run creates a timestamped log file in the project's `logs/` directory:

```
logs/2026-02-23_14-30-00_gdrive_backup.log
logs/2026-02-23_15-00-00_gdrive_restore.log
```

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
# List configured remotes
rclone listremotes

# If your remote is named differently, update config.toml
```

### Slow uploads

rclone defaults are conservative. For faster transfers on good connections:

```bash
# Add to the rclone command in _backup_impl.py if needed:
--transfers 8           # Parallel file transfers (default: 4)
--drive-chunk-size 64M  # Larger upload chunks (default: 8M)
```

## License

MIT
