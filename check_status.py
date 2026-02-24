#!/usr/bin/env python3
"""
check_status.py — Show gdrive-backup project state at a glance.

Run at the start of any Claude session to see what's configured,
what's been backed up, and whether cron is active.
"""

import glob
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent


def section(title):
    print(f"\n{'─' * 50}")
    print(f"  {title}")
    print(f"{'─' * 50}")


def git_info():
    section("Git")
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=SCRIPT_DIR
        ).stdout.strip()

        log = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            capture_output=True, text=True, cwd=SCRIPT_DIR
        ).stdout.strip()

        status = subprocess.run(
            ["git", "status", "--short"],
            capture_output=True, text=True, cwd=SCRIPT_DIR
        ).stdout.strip()

        print(f"  Branch:  {branch}")
        print(f"  Recent commits:")
        for line in log.splitlines():
            print(f"    {line}")
        if status:
            print(f"  Uncommitted changes:")
            for line in status.splitlines():
                print(f"    {line}")
        else:
            print(f"  Working tree clean")
    except FileNotFoundError:
        print("  git not found")


def config_info():
    section("Config")
    config_path = SCRIPT_DIR / "config.toml"
    if not config_path.exists():
        print("  config.toml not found — copy config.template.toml and edit it")
        return None

    try:
        import tomllib
    except ImportError:
        print("  Python 3.11+ required for tomllib")
        return None

    with open(config_path, "rb") as f:
        cfg = tomllib.load(f)

    remote = cfg.get("remote", {})
    versions = cfg.get("versions", {})
    sources = cfg.get("sources", [])
    schedule = cfg.get("schedule", {}).get("cron", "(not set)")
    excludes = cfg.get("exclude", {}).get("patterns", [])

    print(f"  Remote:      {remote.get('name', '?')}:{remote.get('root', '?')}/")
    print(f"  Retention:   {versions.get('keep_changed', 5)} changed, {versions.get('keep_deleted', 10)} deleted")
    print(f"  Schedule:    {schedule}")
    print(f"  Excludes:    {len(excludes)} global patterns")
    print(f"  Sources:     {len(sources)}")

    for i, src in enumerate(sources, 1):
        path = src.get("path", "?")
        folder = src.get("folder", "?")
        exists = "OK" if os.path.isdir(path) else "NOT FOUND"
        src_excludes = src.get("exclude", [])
        extra = f" (+{len(src_excludes)} excludes)" if src_excludes else ""
        print(f"    [{i}] {path}")
        print(f"        -> {remote.get('name', '?')}:{remote.get('root', '?')}/{folder}/current/")
        print(f"        Path: {exists}{extra}")

    return cfg


def backup_history(cfg):
    if cfg is None:
        return

    section("Last Backup")
    sources = cfg.get("sources", [])

    for src in sources:
        folder = src.get("folder", "?")
        source_path = src.get("path", "")
        log_dir = os.path.join(source_path, "logs")

        print(f"  {folder}:")

        if not os.path.isdir(log_dir):
            print(f"    Never backed up (no logs/ directory)")
            continue

        log_files = sorted(glob.glob(os.path.join(log_dir, "*_gdrive_backup.log")))
        if not log_files:
            print(f"    Never backed up (no log files)")
            continue

        latest = log_files[-1]
        basename = os.path.basename(latest)
        ts_str = basename.replace("_gdrive_backup.log", "")
        try:
            ts = datetime.strptime(ts_str, "%Y-%m-%d_%H-%M-%S")
            print(f"    Last:   {ts.strftime('%Y-%m-%d %H:%M:%S')}")
        except ValueError:
            print(f"    Last:   {basename}")

        with open(latest) as f:
            content = f.read()
        if "ERROR" in content:
            print(f"    Result: ERRORS (check {latest})")
        else:
            print(f"    Result: OK")

        print(f"    Total:  {len(log_files)} backup(s) logged")


def cron_info():
    section("Cron")
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True
        )
        if result.returncode != 0:
            print("  No crontab configured")
            return

        found = False
        for line in result.stdout.splitlines():
            if "gdrive-backup" in line:
                parts = line.split()
                schedule = " ".join(parts[:5])
                print(f"  Active:   Yes")
                print(f"  Schedule: {schedule}")
                found = True

        if not found:
            print("  Active: No (run ./backup.sh --cron-install)")
    except FileNotFoundError:
        print("  crontab not available")


def rclone_info():
    section("rclone")
    try:
        result = subprocess.run(
            ["rclone", "--version"], capture_output=True, text=True
        )
        version_line = result.stdout.splitlines()[0] if result.stdout else "unknown"
        print(f"  Version: {version_line}")

        remotes = subprocess.run(
            ["rclone", "listremotes"], capture_output=True, text=True
        )
        remote_list = [r.strip() for r in remotes.stdout.strip().splitlines() if r.strip()]
        print(f"  Remotes: {', '.join(remote_list) if remote_list else 'none configured'}")
    except FileNotFoundError:
        print("  rclone not installed (run ./setup.sh)")


def main():
    print("=" * 50)
    print("  gdrive-backup — Project Status")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    git_info()
    cfg = config_info()
    backup_history(cfg)
    cron_info()
    rclone_info()

    print()


if __name__ == "__main__":
    main()
