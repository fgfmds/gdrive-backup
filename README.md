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

## Deploying to Another Machine

1. Clone the repo: `git clone https://github.com/fgfmds/gdrive-backup.git`
2. Run setup: `./setup.sh` (installs rclone, authenticates with Google Drive)
3. Create config: `cp config.template.toml config.toml` and edit with local paths
4. Test: `./backup.sh --dry-run`

Each machine has its own `config.toml` with its local paths. The `config.toml` file is gitignored so it won't conflict across machines.

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
