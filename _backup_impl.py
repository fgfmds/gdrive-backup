#!/usr/bin/env python3
"""
Google Drive backup with versioned archiving of changed and deleted files.

Architecture:
  local project/  ──sync──►  remote:folder/current/
                                ├── .changed/<timestamp>/   (old versions of modified files)
                                └── .deleted/<timestamp>/   (files removed from local)

Steps per backup run:
  1. rclone check: classify every file as unchanged / changed / new / deleted
  2. Server-side copy changed files from current/ to .changed/<timestamp>/
  3. Server-side copy deleted files from current/ to .deleted/<timestamp>/
  4. rclone sync: update current/ to match local
  5. Prune .changed/ beyond keep_changed, .deleted/ beyond keep_deleted
"""

import argparse
import os
import subprocess
import sys
import tomllib
from datetime import datetime
from pathlib import Path


def parse_args():
    p = argparse.ArgumentParser(
        description="Sync a project directory to Google Drive with version history"
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
            print(f"rclone error (exit {result.returncode}):", file=sys.stderr)
            print(result.stderr, file=sys.stderr)
        return result
    else:
        return subprocess.run(["rclone"] + args)


def validate(cfg):
    """Validate config and rclone remote. Returns (remote_name, remote_folder, source_path, excludes, versions)."""
    remote_name = cfg["remote"]["name"]
    remote_folder = cfg["remote"]["folder"]
    source_path = cfg["source"]["path"]
    excludes = cfg.get("exclude", {}).get("patterns", [])
    versions = cfg.get("versions", {})
    keep_changed = versions.get("keep_changed", 5)
    keep_deleted = versions.get("keep_deleted", 10)

    if not os.path.isdir(source_path):
        print(f"Error: Source path does not exist: {source_path}", file=sys.stderr)
        sys.exit(1)

    # Check remote exists
    result = run_rclone(["listremotes"], capture=True, check=False)
    remotes = result.stdout.strip().split("\n") if result.stdout.strip() else []
    if f"{remote_name}:" not in remotes:
        print(f"Error: rclone remote '{remote_name}' not found.", file=sys.stderr)
        print("Run: rclone config  (or ./setup.sh)", file=sys.stderr)
        sys.exit(1)

    return remote_name, remote_folder, source_path, excludes, keep_changed, keep_deleted


def build_exclude_args(excludes):
    """Build rclone --exclude flags from pattern list."""
    args = []
    for pattern in excludes:
        args.extend(["--exclude", pattern])
    return args


def classify_files(source_path, remote_current, excludes):
    """
    Use rclone check --combined to classify files.

    Returns (changed, deleted, new_files) where each is a list of relative paths.
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
    ] + build_exclude_args(excludes)

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


def archive_files(remote_name, remote_folder, files, archive_subdir, timestamp, dry_run):
    """
    Server-side copy files from current/ to an archive directory.
    Uses rclone copyto for each file (server-side, no data downloaded).
    """
    if not files:
        return

    src_base = f"{remote_name}:{remote_folder}/current"
    dst_base = f"{remote_name}:{remote_folder}/{archive_subdir}/{timestamp}"

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


def prune_versions(remote_name, remote_folder, archive_subdir, keep_n, dry_run):
    """Remove oldest version directories beyond keep_n."""
    remote_path = f"{remote_name}:{remote_folder}/{archive_subdir}"

    # List version directories (timestamps sort lexicographically)
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


def do_backup(cfg, dry_run):
    remote_name, remote_folder, source_path, excludes, keep_changed, keep_deleted = validate(cfg)

    remote_current = f"{remote_name}:{remote_folder}/current"
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    exclude_args = build_exclude_args(excludes)

    # Set up logging
    log_dir = os.path.join(source_path, "logs")
    os.makedirs(log_dir, exist_ok=True)
    logfile = os.path.join(log_dir, f"{timestamp}_gdrive_backup.log")

    print("=== Google Drive BACKUP ===")
    print(f"Started:       {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Source:        {source_path}")
    print(f"Destination:   {remote_current}")
    print(f"Log:           {logfile}")
    print(f"Keep changed:  {keep_changed} versions")
    print(f"Keep deleted:  {keep_deleted} versions")
    if dry_run:
        print("Mode:          DRY RUN (no files will be transferred)")
    print()

    # ── Step 1: Classify files ───────────────────────────────────────
    print("--- Step 1: Comparing local vs remote ---")
    changed, deleted, new_files, errors = classify_files(
        source_path, remote_current, excludes
    )
    print(f"  Unchanged:   (not counted)")
    print(f"  Changed:     {len(changed)}")
    print(f"  New:         {len(new_files)}")
    print(f"  Deleted:     {len(deleted)}")
    if errors:
        print(f"  Errors:      {len(errors)}")
    print()

    # ── Step 2: Archive changed files ────────────────────────────────
    if changed:
        print("--- Step 2: Archiving changed files ---")
        archive_files(remote_name, remote_folder, changed, ".changed", timestamp, dry_run)
        print()
    else:
        print("--- Step 2: No changed files to archive ---")
        print()

    # ── Step 3: Archive deleted files ────────────────────────────────
    if deleted:
        print("--- Step 3: Archiving deleted files ---")
        archive_files(remote_name, remote_folder, deleted, ".deleted", timestamp, dry_run)
        print()
    else:
        print("--- Step 3: No deleted files to archive ---")
        print()

    # ── Step 4: Sync ─────────────────────────────────────────────────
    print("--- Step 4: Syncing to remote ---")
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

    # ── Step 5: Prune old versions ───────────────────────────────────
    print("--- Step 5: Pruning old versions ---")
    prune_versions(remote_name, remote_folder, ".changed", keep_changed, dry_run)
    prune_versions(remote_name, remote_folder, ".deleted", keep_deleted, dry_run)
    print()

    # ── Summary ──────────────────────────────────────────────────────
    if sync_exit == 0:
        print("=== BACKUP COMPLETE ===")
    else:
        print(f"=== BACKUP FAILED (exit code: {sync_exit}) ===")

    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Log:      {logfile}")

    # Show transfer summary from log
    if os.path.isfile(logfile):
        print()
        print("--- Transfer Summary ---")
        with open(logfile) as f:
            for line in f:
                if any(kw in line for kw in ("Transferred", "Checks", "Elapsed", "Errors")):
                    print(f"  {line.rstrip()}")

    return sync_exit


def do_restore(cfg, dry_run):
    remote_name, remote_folder, source_path, excludes, _, _ = validate(cfg)

    remote_current = f"{remote_name}:{remote_folder}/current"
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    exclude_args = build_exclude_args(excludes)

    log_dir = os.path.join(source_path, "logs")
    os.makedirs(log_dir, exist_ok=True)
    logfile = os.path.join(log_dir, f"{timestamp}_gdrive_restore.log")

    print("=== Google Drive RESTORE ===")
    print(f"Started:  {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Source:   {remote_current}")
    print(f"Dest:     {source_path}")
    print(f"Log:      {logfile}")
    if dry_run:
        print("Mode:     DRY RUN (no files will be transferred)")
    print()

    sync_args = [
        "sync", remote_current, source_path,
        "--progress", "--stats-one-line", "--stats", "10s",
        "--log-file", logfile, "--log-level", "INFO",
    ] + exclude_args
    if dry_run:
        sync_args.append("--dry-run")

    result = run_rclone(sync_args, capture=False, check=False)

    if result.returncode == 0:
        print("\n=== RESTORE COMPLETE ===")
    else:
        print(f"\n=== RESTORE FAILED (exit code: {result.returncode}) ===")

    print(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"Log:      {logfile}")

    return result.returncode


def main():
    args = parse_args()
    cfg = load_config(args.config)

    if args.restore:
        exit_code = do_restore(cfg, args.dry_run)
    else:
        exit_code = do_backup(cfg, args.dry_run)

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
