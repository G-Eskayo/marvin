#!/usr/bin/env python3
"""repo_growth.py — track repository size and find new top-level directories (ADR 0063, #339; ADR 0064, #341).

    count_files_folders_size(repo: Path) -> (int, int, int) | None
        Counts tracked files, directories, and total size in bytes. Returns None on error.

    new_top_level_this_week(repo: Path, now: datetime) -> set[str] | None
        Finds top-level directories created within the past 7 days. Returns None on error.
"""
from __future__ import annotations
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


def count_files_folders_size(repo: Path) -> tuple[int, int, int] | None:
    """Count tracked files, folders, and total bytes in a git repo.

    Returns (file_count, folder_count, total_bytes) or None on error.
    """
    try:
        # Get all tracked files with their sizes
        result = subprocess.run(
            ["git", "-C", str(repo), "ls-files", "--stage"],
            capture_output=True, text=True, timeout=30, check=True
        )

        files = set()
        folders = set()
        total_size = 0

        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            # Format: [mode] [object] [stage] [name]
            parts = line.split()
            if len(parts) < 4:
                continue
            path_str = " ".join(parts[3:])  # Handle spaces in filenames

            files.add(path_str)
            total_size += len(path_str.encode()) if path_str else 0

            # Track all parent directories
            path = Path(path_str)
            for parent in path.parents:
                if parent != Path("."):
                    folders.add(str(parent))

        # Use git ls-tree to get actual file sizes
        try:
            size_result = subprocess.run(
                ["git", "-C", str(repo), "ls-tree", "-r", "-l", "HEAD"],
                capture_output=True, text=True, timeout=30, check=True
            )
            total_size = 0
            for line in size_result.stdout.splitlines():
                if not line.strip():
                    continue
                parts = line.split()
                if len(parts) < 4:
                    continue
                try:
                    size = int(parts[3])
                    total_size += size
                except (ValueError, IndexError):
                    pass
        except subprocess.CalledProcessError:
            # If HEAD doesn't exist (empty repo), size is 0
            total_size = 0

        return len(files), len(folders), total_size
    except Exception:  # noqa: BLE001
        return None


def new_top_level_this_week(repo: Path, now: datetime) -> set[str] | None:
    """Find top-level directories added within the past 7 days.

    Returns a set of directory names, an empty set when no new dirs exist, or None on error.
    A directory is "new" if its first appearance in git history is within the past week.
    """
    try:
        # Get all top-level directories
        try:
            all_dirs_result = subprocess.run(
                ["git", "-C", str(repo), "ls-tree", "--name-only", "-d", "HEAD"],
                capture_output=True, text=True, timeout=30, check=True
            )
            all_top_level = set(all_dirs_result.stdout.strip().split('\n')) if all_dirs_result.stdout.strip() else set()
        except subprocess.CalledProcessError:
            # No HEAD yet or error
            all_top_level = set()

        if not all_top_level:
            return set()

        # For each top-level dir, find when it first appeared
        new_dirs = set()
        week_ago = now - timedelta(days=7)

        for dir_name in all_top_level:
            try:
                # Get the log of when this directory was first created
                log_result = subprocess.run(
                    ["git", "-C", str(repo), "log", "--diff-filter=A", "--name-only",
                     "--pretty=%ct", "--", dir_name],
                    capture_output=True, text=True, timeout=30, check=True
                )
                lines = log_result.stdout.strip().split('\n')
                # The first line that looks like a timestamp is when this dir was created
                for line in reversed(lines):  # Last timestamp (oldest) is first creation
                    if line.strip().isdigit():
                        created_ts = int(line.strip())
                        created_dt = datetime.fromtimestamp(created_ts, tz=timezone.utc)
                        if created_dt >= week_ago:
                            new_dirs.add(dir_name)
                        break
            except subprocess.CalledProcessError:
                # Directory might not have an explicit "A" record (shouldn't happen)
                pass

        return new_dirs
    except Exception:  # noqa: BLE001
        return None


def main(argv) -> int:
    if not argv or argv[0] == "--help":
        print(__doc__)
        return 0

    if argv[0] == "count":
        repo = Path(argv[1]) if len(argv) > 1 else Path.cwd()
        result = count_files_folders_size(repo)
        if result:
            files, folders, size = result
            print(json.dumps({"files": files, "folders": folders, "bytes": size}))
        else:
            print(json.dumps({"error": "could not count"}))
        return 0 if result else 1

    if argv[0] == "new-this-week":
        repo = Path(argv[1]) if len(argv) > 1 else Path.cwd()
        now = datetime.fromisoformat(argv[2]) if len(argv) > 2 else datetime.now(timezone.utc)
        result = new_top_level_this_week(repo, now)
        print(json.dumps({"new": sorted(result) if result else []}))
        return 0 if result else 1

    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
