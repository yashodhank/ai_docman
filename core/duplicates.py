"""Duplicate detection — replaces detect_duplicates.sh with proper CSV parsing."""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from docman.logging_setup import log_operation
from docman.models import DuplicateGroup

logger = logging.getLogger("docman")

SKIP_SHA = {"icloud_placeholder", "skipped_too_large", "error", ""}


def run_duplicates(cfg: dict[str, Any], dry_run: bool = False, verbose: bool = False) -> Path:
    """Detect duplicates from file_index.csv. Returns path to report."""
    docs = Path(cfg["docs_dir"])
    index_dir = docs / cfg["index_dir"]
    index_file = index_dir / "file_index.csv"
    output = index_dir / "duplicates_report.csv"

    if not index_file.exists():
        raise FileNotFoundError(f"{index_file} not found. Run 'docman index' first.")

    # Group by SHA-256
    sha_groups: dict[str, list[str]] = {}
    with open(index_file, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sha = row.get("sha256", "")
            path = row.get("path", "")
            if sha in SKIP_SHA or not path:
                continue
            sha_groups.setdefault(sha, []).append(path)

    # Filter to groups with >1 file
    groups: list[DuplicateGroup] = []
    for sha, paths in sha_groups.items():
        if len(paths) < 2:
            continue
        # Prefer ~/Documents over ~/Downloads, then shortest path
        paths.sort(key=lambda p: (0 if "/Documents/" in p else 1, len(p)))
        canonical = Path(paths[0])
        duplicates = [Path(p) for p in paths[1:]]
        try:
            size = canonical.stat().st_size if canonical.exists() else 0
        except OSError:
            size = 0
        groups.append(DuplicateGroup(sha256=sha, size_bytes=size,
                                     canonical=canonical, duplicates=duplicates))

    if dry_run:
        print(f"[DRY RUN] Would find {len(groups)} duplicate groups.")
        return output

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["sha256", "canonical_path", "duplicate_paths"])
        for g in groups:
            dup_str = "|".join(str(d) for d in g.duplicates)
            writer.writerow([g.sha256, str(g.canonical), dup_str])

    print(f"Done. Found {len(groups)} duplicate groups. Output: {output}")
    log_operation(logger, op="duplicates", groups_found=len(groups),
                  output=str(output), dry_run=False, status="ok")
    return output
