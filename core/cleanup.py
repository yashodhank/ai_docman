"""Cleanup scanners: empty dirs, broken symlinks, temp/junk files, large files."""
from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path
from typing import Any

from docman.logging_setup import log_operation

logger = logging.getLogger("docman")

DEFAULT_TEMP_PATTERNS = [
    ".DS_Store", "Thumbs.db", "desktop.ini", "*.tmp", "*.swp", "~$*",
    "*.pyc", "__pycache__",
]

DEFAULT_LARGE_THRESHOLD_MB = 100


def _matches_temp_pattern(name: str, patterns: list[str]) -> bool:
    """Check if a filename matches any temp/junk pattern."""
    for pattern in patterns:
        if fnmatch.fnmatch(name, pattern):
            return True
    return False


def scan_empty_dirs(dirs: list[Path], recursive: bool = True) -> list[Path]:
    """Find empty directories. If recursive, also finds dirs containing only empty dirs."""
    empty: list[Path] = []

    for root_dir in dirs:
        if not root_dir.exists():
            continue
        # Walk bottom-up so we can detect recursively empty dirs
        for dirpath, dirnames, filenames in os.walk(str(root_dir), topdown=False):
            dp = Path(dirpath)
            if dp == root_dir:
                continue
            try:
                children = list(dp.iterdir())
            except PermissionError:
                continue

            if not children:
                empty.append(dp)
            elif recursive:
                # Check if all children are directories that are already marked empty
                if all(c.is_dir() and c in empty for c in children):
                    empty.append(dp)

    return sorted(set(empty))


def scan_broken_symlinks(dirs: list[Path]) -> list[Path]:
    """Find broken symbolic links."""
    broken: list[Path] = []
    for root_dir in dirs:
        if not root_dir.exists():
            continue
        try:
            for p in root_dir.rglob("*"):
                if p.is_symlink() and not p.exists():
                    broken.append(p)
        except PermissionError:
            pass
    return sorted(broken)


def scan_temp_files(dirs: list[Path], patterns: list[str] | None = None) -> list[Path]:
    """Find temp/junk files matching configured patterns."""
    if patterns is None:
        patterns = DEFAULT_TEMP_PATTERNS

    found: list[Path] = []
    for root_dir in dirs:
        if not root_dir.exists():
            continue
        try:
            for p in root_dir.rglob("*"):
                if p.is_file() or p.is_dir():
                    if _matches_temp_pattern(p.name, patterns):
                        found.append(p)
        except PermissionError:
            pass
    return sorted(found)


def scan_large_files(dirs: list[Path], threshold_mb: float = DEFAULT_LARGE_THRESHOLD_MB) -> list[tuple[Path, int]]:
    """Find files above size threshold. Returns list of (path, size_bytes)."""
    threshold_bytes = int(threshold_mb * 1024 * 1024)
    large: list[tuple[Path, int]] = []
    for root_dir in dirs:
        if not root_dir.exists():
            continue
        try:
            for p in root_dir.rglob("*"):
                if p.is_file():
                    try:
                        size = p.stat().st_size
                        if size >= threshold_bytes:
                            large.append((p, size))
                    except OSError:
                        pass
        except PermissionError:
            pass
    return sorted(large, key=lambda x: x[1], reverse=True)


def run_cleanup(cfg: dict[str, Any], empty_dirs: bool = False,
                broken_links: bool = False, temp_files: bool = False,
                large_files: bool = False, run_all: bool = False,
                action: str = "report", dry_run: bool = False,
                verbose: bool = False) -> dict[str, Any]:
    """Run cleanup scanners and optionally delete findings."""
    docs = Path(cfg["docs_dir"])
    downloads = Path(cfg["downloads_dir"])
    managed_dirs = [docs, downloads]

    cleanup_cfg = cfg.get("cleanup", {})
    temp_patterns = cleanup_cfg.get("temp_patterns", DEFAULT_TEMP_PATTERNS)
    threshold_mb = cleanup_cfg.get("large_file_threshold_mb", DEFAULT_LARGE_THRESHOLD_MB)

    if run_all:
        empty_dirs = broken_links = temp_files = large_files = True

    if not any([empty_dirs, broken_links, temp_files, large_files]):
        print("No scanners selected. Use --empty-dirs, --temp-files, --broken-links, --large-files, or --all.")
        return {}

    results: dict[str, Any] = {}
    total_found = 0

    if empty_dirs:
        found = scan_empty_dirs(managed_dirs)
        results["empty_dirs"] = [str(p) for p in found]
        total_found += len(found)
        print(f"\nEmpty directories: {len(found)}")
        for p in found:
            print(f"  {p}")
        if action == "delete" and found and not dry_run:
            deleted = 0
            for p in found:
                try:
                    p.rmdir()
                    deleted += 1
                    log_operation(logger, op="cleanup_empty_dir",
                                  path=str(p), dry_run=False, status="ok")
                except OSError as e:
                    print(f"  ERROR removing {p}: {e}")
            print(f"  Removed {deleted} empty directories")

    if broken_links:
        found = scan_broken_symlinks(managed_dirs)
        results["broken_links"] = [str(p) for p in found]
        total_found += len(found)
        print(f"\nBroken symlinks: {len(found)}")
        for p in found:
            print(f"  {p}")
        if action == "delete" and found and not dry_run:
            deleted = 0
            for p in found:
                try:
                    p.unlink()
                    deleted += 1
                    log_operation(logger, op="cleanup_broken_link",
                                  path=str(p), dry_run=False, status="ok")
                except OSError as e:
                    print(f"  ERROR removing {p}: {e}")
            print(f"  Removed {deleted} broken symlinks")

    if temp_files:
        found = scan_temp_files(managed_dirs, temp_patterns)
        results["temp_files"] = [str(p) for p in found]
        total_found += len(found)
        print(f"\nTemp/junk files: {len(found)}")
        for p in found:
            size_str = ""
            if p.is_file():
                try:
                    size_str = f" ({p.stat().st_size:,} bytes)"
                except OSError:
                    pass
            print(f"  {p}{size_str}")
        if action == "delete" and found and not dry_run:
            deleted = 0
            for p in found:
                try:
                    if p.is_dir():
                        import shutil
                        shutil.rmtree(p)
                    else:
                        p.unlink()
                    deleted += 1
                    log_operation(logger, op="cleanup_temp_file",
                                  path=str(p), dry_run=False, status="ok")
                except OSError as e:
                    print(f"  ERROR removing {p}: {e}")
            print(f"  Removed {deleted} temp/junk items")

    if large_files:
        found_large = scan_large_files(managed_dirs, threshold_mb)
        results["large_files"] = [{"path": str(p), "size_mb": s / 1_048_576}
                                  for p, s in found_large]
        total_found += len(found_large)
        print(f"\nLarge files (>{threshold_mb} MB): {len(found_large)}")
        for p, size in found_large:
            print(f"  {size / 1_048_576:>8.1f} MB  {p}")

    tag = " [DRY RUN]" if dry_run else ""
    print(f"\nCleanup scan complete: {total_found} items found{tag}")

    log_operation(logger, op="cleanup", total_found=total_found,
                  scanners={"empty_dirs": empty_dirs, "broken_links": broken_links,
                            "temp_files": temp_files, "large_files": large_files},
                  action=action, dry_run=dry_run, status="ok")

    return results
