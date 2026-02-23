#!/usr/bin/env python3
"""
Google Drive backup with versioned archiving of changed and deleted files.
Supports multiple source directories in a single config.

Architecture (per source):
  local dir/  ──sync──►  remote:root/folder/current/
                            ├── .changed/<timestamp>/   (old versions of modified files)
                            └── .deleted/<timestamp>/   (files removed from local)

Steps per source per backup run:
  1. rclone check: classify every file as unchanged / changed / new / deleted
  2. Server-side copy changed files from current/ to .changed/<timestamp>/
  3. Server-side copy deleted files from current/ to .deleted/<timestamp>/
  4. rclone sync: update current/ to match local
  5. Prune .changed/ beyond keep_changed, .deleted/ beyond keep_deleted
"""

import argparse
import glob
import os
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(
        description="Sync directory trees to Google Drive with version history"
    )
    p.add_argument(
        "--config", default="./config.toml",
        help="Path to config.toml (default: ./config.toml)"
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Preview what would be transferred (no actual changes)"
    )
    p.add_argument(
        "--restore", action="store_true",
        help="Download from Drive to local (reverse direction)"
    )
    p.add_argument(
        "--source", default=None,
        help="Only process the source with this folder name (skip others)"
    )
    p.add_argument(
        "--cron-install", action="store_true",
        help="Install a cron job for automated backups"
    )
    p.add_argument(
        "--cron-remove", action="store_true",
        help="Remove the automated backup cron job"
    )
    p.add_argument(
        "--status", action="store_true",
        help="Show last backup time and cron schedule"
    )
    return p.parse_args()


def load_config(path):
    if not os.path.isfile(path):
        print(f"Error: Config file not found: {path}", file=sys.stderr)
        print("Copy config.template.toml to config.toml and edit it.", file=sys.stderr)
        sys.exit(1)
    with open(path, "rb") as f:
        return tomllib.load(f)


def run_rclone(args, capture=False, check=True):
    """Run an rclone command, printing output live unless capture=True."""
    if capture:
        result = subprocess.run(
            ["rclone"] + args,
            capture_output=True, text=True
        )
        if check and result.returncode != 0:
            print(f"  rclone error (exit {result.returncode}):", file=sys.stderr)
            if result.stderr:
                print(f"  {result.stderr.strip()}", file=sys.stderr)
        return result
    else:
        return subprocess.run(["rclone"] + args)


def validate_remote(cfg):
    """Validate rclone remote exists. Returns (remote_name, remote_root)."""
    remote_name = cfg["remote"]["name"]
    remote_root = cfg["remote"]["root"]

    result = run_rclone(["listremotes"], capture=True, check=False)
    remotes = result.stdout.strip().split("\n") if result.stdout.strip() else []
    if f"{remote_name}:" not in remotes:
        print(f"Error: rclone remote '{remote_name}' not found.", file=sys.stderr)
        print("Run: rclone config  (or ./setup.sh)", file=sys.stderr)
        sys.exit(1)

    return remote_name, remote_root


def build_exclude_args(global_excludes, source_excludes=None):
    """Build rclone --exclude flags from global + per-source pattern lists."""
    args = []
    for pattern in global_excludes:
        args.extend(["--exclude", pattern])
    if source_excludes:
        for pattern in source_excludes:
            args.extend(["--exclude", pattern])
    return args


def classify_files(source_path, remote_current, exclude_args):
    """
    Use rclone check --combined to classify files.

    Combined output format:
      = path   — match (unchanged)
      * path   — size/hash differs (changed)
      - path   — only in source (new)
      + path   — only in destination (deleted locally)
      ! path   — error
    """
    args = [
        "check", source_path, remote_current,
        "--combined", "-",
    ] + exclude_args

    result = run_rclone(args, capture=True, check=False)

    changed = []
    deleted = []
    new_files = []
    errors = []

    for line in result.stdout.strip().split("\n"):
        if not line or len(line) < 3:
            continue
        marker = line[0]
        filepath = line[2:].strip()
        if marker == "*":
            changed.append(filepath)
        elif marker == "+":
            deleted.append(filepath)
        elif marker == "-":
            new_files.append(filepath)
        elif marker == "!":
            errors.append(filepath)
        # '=' is unchanged, skip

    return changed, deleted, new_files, errors


def archive_files(remote_name, remote_base, files, archive_subdir, timestamp, dry_run):
    """
    Server-side copy files from current/ to an archive directory.
    Uses rclone copyto for each file (server-side, no data downloaded).
    """
    if not files:
        return

    src_base = f"{remote_name}:{remote_base}/current"
    dst_base = f"{remote_name}:{remote_base}/{archive_subdir}/{timestamp}"

    print(f"  Archiving {len(files)} file(s) to {archive_subdir}/{timestamp}/")

    for filepath in files:
        src = f"{src_base}/{filepath}"
        dst = f"{dst_base}/{filepath}"
        if dry_run:
            print(f"    [dry-run] would archive: {filepath}")
        else:
            result = run_rclone(["copyto", src, dst], capture=True, check=False)
            if result.returncode != 0:
                print(f"    Warning: failed to archive {filepath}: {result.stderr.strip()}")


def prune_versions(remote_name, remote_base, archive_subdir, keep_n, dry_run):
    """Remove oldest version directories beyond keep_n."""
    remote_path = f"{remote_name}:{remote_base}/{archive_subdir}"

    result = run_rclone(["lsf", remote_path, "--dirs-only"], capture=True, check=False)

    if result.returncode != 0 or not result.stdout.strip():
        return  # No versions exist yet

    versions = sorted(result.stdout.strip().split("\n"))

    if len(versions) <= keep_n:
        return

    to_remove = versions[:len(versions) - keep_n]
    print(f"  Pruning {len(to_remove)} old version(s) from {archive_subdir}/ (keeping {keep_n})")

    for v in to_remove:
        v = v.rstrip("/")
        target = f"{remote_path}/{v}"
        if dry_run:
            print(f"    [dry-run] would remove: {archive_subdir}/{v}/")
        else:
            run_rclone(["purge", target], capture=True, check=False)
            print(f"    Removed: {archive_subdir}/{v}/")


CRON_MARKER = "# gdrive-backup:"


def get_cron_marker(config_path):
    """Return a unique cron comment marker for this config file."""
    return f"{CRON_MARKER} {os.path.abspath(config_path)}"


def do_cron_install(config_path, cfg):
    """Install a cron job that runs backup.sh on the configured schedule."""
    schedule = cfg.get("schedule", {}).get("cron", "0 2 * * *")
    script_dir = os.path.dirname(os.path.abspath(__file__))
    backup_sh = os.path.join(script_dir, "backup.sh")
    abs_config = os.path.abspath(config_path)
    marker = get_cron_marker(config_path)

    # Build the cron line
    log_dir = os.path.join(script_dir, "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "cron_backup.log")

    cron_line = (
        f'{schedule} "{backup_sh}" --config "{abs_config}" '
        f'>> "{log_file}" 2>&1 {marker}'
    )

    # Read existing crontab
    result = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True
    )
    existing = result.stdout if result.returncode == 0 else ""

    # Remove any existing entry for this config
    lines = [l for l in existing.splitlines() if marker not in l]

    # Add new entry
    lines.append(cron_line)
    new_crontab = "\n".join(lines) + "\n"

    # Install
    proc = subprocess.run(
        ["crontab", "-"], input=new_crontab, capture_output=True, text=True
    )
    if proc.returncode != 0:
        print(f"Error installing cron job: {proc.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    print("Cron job installed:")
    print(f"  Schedule:  {schedule}")
    print(f"  Command:   {backup_sh} --config {abs_config}")
    print(f"  Log:       {log_file}")
    print()
    print("Verify with: crontab -l")


def do_cron_remove(config_path):
    """Remove the cron job for this config file."""
    marker = get_cron_marker(config_path)

    result = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True
    )
    if result.returncode != 0:
        print("No crontab found.")
        return

    existing = result.stdout
    lines = existing.splitlines()
    new_lines = [l for l in lines if marker not in l]

    if len(new_lines) == len(lines):
        print("No cron job found for this config.")
        return

    new_crontab = "\n".join(new_lines) + "\n" if new_lines else ""

    proc = subprocess.run(
        ["crontab", "-"], input=new_crontab, capture_output=True, text=True
    )
    if proc.returncode != 0:
        print(f"Error removing cron job: {proc.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    print("Cron job removed.")
    print("Verify with: crontab -l")


def do_status(config_path, cfg):
    """Show last backup time and cron schedule."""
    sources = cfg.get("sources", [])

    # Find most recent log across all sources
    print("=== Backup Status ===")
    print()

    for source in sources:
        source_path = source["path"]
        folder = source["folder"]
        log_dir = os.path.join(source_path, "logs")

        print(f"  {folder}:")

        if not os.path.isdir(log_dir):
            print(f"    Last backup: never (no logs/ directory)")
            print()
            continue

        log_files = sorted(glob.glob(os.path.join(log_dir, "*_gdrive_backup.log")))
        if not log_files:
            print(f"    Last backup: never (no log files)")
        else:
            latest = log_files[-1]
            basename = os.path.basename(latest)
            # Parse timestamp from filename: YYYY-MM-DD_HH-MM-SS_gdrive_backup.log
            ts_str = basename.replace("_gdrive_backup.log", "")
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%d_%H-%M-%S")
                print(f"    Last backup: {ts.strftime('%Y-%m-%d %H:%M:%S')}")
            except ValueError:
                print(f"    Last backup: {basename} (could not parse timestamp)")

            # Check if last backup had errors
            with open(latest) as f:
                content = f.read()
            if "ERROR" in content:
                print(f"    Status:      errors in last run (check {latest})")
            else:
                print(f"    Status:      OK")

        print()

    # Show cron schedule
    marker = get_cron_marker(config_path)
    result = subprocess.run(
        ["crontab", "-l"], capture_output=True, text=True
    )

    print("  Cron schedule:")
    if result.returncode != 0:
        print("    No crontab found")
    else:
        found = False
        for line in result.stdout.splitlines():
            if marker in line:
                # Extract schedule (first 5 fields)
                parts = line.split()
                schedule = " ".join(parts[:5])
                print(f"    {schedule}")
                found = True
        if not found:
            print("    Not scheduled (run --cron-install to set up)")

    print()


def backup_source(remote_name, remote_base, source_path, exclude_args,
                  keep_changed, keep_deleted, timestamp, log_dir, dry_run):
    """Back up a single source directory with versioning."""
    remote_current = f"{remote_name}:{remote_base}/current"

    logfile = os.path.join(log_dir, f"{timestamp}_gdrive_backup.log")

    print(f"  Source:        {source_path}")
    print(f"  Destination:   {remote_current}")
    print(f"  Log:           {logfile}")
    print()

    # Step 1: Classify
    print("  [1/5] Comparing local vs remote...")
    changed, deleted, new_files, errors = classify_files(
        source_path, remote_current, exclude_args
    )
    print(f"         Changed: {len(changed)}  New: {len(new_files)}  "
          f"Deleted: {len(deleted)}  Errors: {len(errors)}")
    print()

    # Step 2: Archive changed
    if changed:
        print("  [2/5] Archiving changed files...")
        archive_files(remote_name, remote_base, changed, ".changed", timestamp, dry_run)
    else:
        print("  [2/5] No changed files to archive")
    print()

    # Step 3: Archive deleted
    if deleted:
        print("  [3/5] Archiving deleted files...")
        archive_files(remote_name, remote_base, deleted, ".deleted", timestamp, dry_run)
    else:
        print("  [3/5] No deleted files to archive")
    print()

    # Step 4: Sync
    print("  [4/5] Syncing to remote...")
    sync_args = [
        "sync", source_path, remote_current,
        "--progress", "--stats-one-line", "--stats", "10s",
        "--log-file", logfile, "--log-level", "INFO",
    ] + exclude_args
    if dry_run:
        sync_args.append("--dry-run")

    result = run_rclone(sync_args, capture=False, check=False)
    sync_exit = result.returncode
    print()

    # Step 5: Prune
    print("  [5/5] Pruning old versions...")
    prune_versions(remote_name, remote_base, ".changed", keep_changed, dry_run)
    prune_versions(remote_name, remote_base, ".deleted", keep_deleted, dry_run)
    print()

    # Summary from log
    if os.path.isfile(logfile):
        print("  --- Transfer Summary ---")
        with open(logfile) as f:
            for line in f:
                if any(kw in line for kw in ("Transferred", "Checks", "Elapsed", "Errors")):
                    print(f"    {line.rstrip()}")
        print()

    return sync_exit


def restore_source(remote_name, remote_base, source_path, exclude_args,
                   timestamp, log_dir, dry_run):
    """Restore a single source directory from Drive."""
    remote_current = f"{remote_name}:{remote_base}/current"

    logfile = os.path.join(log_dir, f"{timestamp}_gdrive_restore.log")

    print(f"  Source:   {remote_current}")
    print(f"  Dest:     {source_path}")
    print(f"  Log:      {logfile}")
    print()

    sync_args = [
        "sync", remote_current, source_path,
        "--progress", "--stats-one-line", "--stats", "10s",
        "--log-file", logfile, "--log-level", "INFO",
    ] + exclude_args
    if dry_run:
        sync_args.append("--dry-run")

    result = run_rclone(sync_args, capture=False, check=False)
    print()

    return result.returncode


def main():
    args = parse_args()
    cfg = load_config(args.config)

    # Handle cron and status commands (don't need remote validation)
    if args.cron_install:
        do_cron_install(args.config, cfg)
        return
    if args.cron_remove:
        do_cron_remove(args.config)
        return
    if args.status:
        do_status(args.config, cfg)
        return

    remote_name, remote_root = validate_remote(cfg)
    global_excludes = cfg.get("exclude", {}).get("patterns", [])
    versions = cfg.get("versions", {})
    keep_changed = versions.get("keep_changed", 5)
    keep_deleted = versions.get("keep_deleted", 10)
    sources = cfg.get("sources", [])

    if not sources:
        print("Error: No [[sources]] defined in config.", file=sys.stderr)
        sys.exit(1)

    # Filter to a single source if --source specified
    if args.source:
        sources = [s for s in sources if s["folder"] == args.source]
        if not sources:
            print(f"Error: No source with folder '{args.source}' found in config.", file=sys.stderr)
            sys.exit(1)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    mode = "RESTORE" if args.restore else "BACKUP"

    print(f"=== Google Drive {mode} ===")
    print(f"Started:       {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Remote:        {remote_name}:{remote_root}/")
    print(f"Sources:       {len(sources)}")
    print(f"Keep changed:  {keep_changed} versions")
    print(f"Keep deleted:  {keep_deleted} versions")
    if args.dry_run:
        print("Mode:          DRY RUN (no files will be transferred)")
    print()

    overall_exit = 0

    for i, source in enumerate(sources, 1):
        source_path = source["path"]
        folder = source["folder"]
        source_excludes = source.get("exclude", [])

        if not os.path.isdir(source_path):
            print(f"[{i}/{len(sources)}] SKIPPED — path not found: {source_path}")
            print()
            overall_exit = 1
            continue

        remote_base = f"{remote_root}/{folder}"
        exclude_args = build_exclude_args(global_excludes, source_excludes)

        # Log directory lives inside the source being backed up
        log_dir = os.path.join(source_path, "logs")
        os.makedirs(log_dir, exist_ok=True)

        print(f"{'─' * 60}")
        print(f"[{i}/{len(sources)}] {folder}")
        print(f"{'─' * 60}")

        if args.restore:
            exit_code = restore_source(
                remote_name, remote_base, source_path, exclude_args,
                timestamp, log_dir, args.dry_run
            )
        else:
            exit_code = backup_source(
                remote_name, remote_base, source_path, exclude_args,
                keep_changed, keep_deleted, timestamp, log_dir, args.dry_run
            )

        if exit_code == 0:
            print(f"[{i}/{len(sources)}] {folder} — OK")
        else:
            print(f"[{i}/{len(sources)}] {folder} — FAILED (exit code: {exit_code})")
            overall_exit = exit_code

        print()

    # Final summary
    print("=" * 60)
    if overall_exit == 0:
        print(f"=== {mode} COMPLETE ===")
    else:
        print(f"=== {mode} FINISHED WITH ERRORS ===")
    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}")

    sys.exit(overall_exit)


if __name__ == "__main__":
    main()
