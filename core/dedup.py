"""Duplicate quarantine/removal logic."""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from docman.fileops import safe_dest, atomic_move
from docman.logging_setup import log_operation

logger = logging.getLogger("docman")


def run_dedup(cfg: dict[str, Any], scope: str = "downloads",
              action: str = "quarantine", dry_run: bool = False,
              verbose: bool = False) -> int:
    """Quarantine or remove duplicates. Returns count of processed files."""
    docs = Path(cfg["docs_dir"]).resolve()
    downloads = Path(cfg["downloads_dir"]).resolve()
    index_dir = docs / cfg["index_dir"]
    quarantine = docs / cfg["quarantine_dir"]
    dupes_file = index_dir / "duplicates_report.csv"

    if not dupes_file.exists():
        print("No duplicates report found. Run 'docman duplicates' first.")
        return 0

    to_process: list[tuple[Path, str]] = []
    with open(dupes_file, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        for row in reader:
            if len(row) < 3:
                continue
            dup_paths = [p.strip() for p in row[2].split("|") if p.strip()]
            for dp in dup_paths:
                p = Path(dp).resolve()
                if not p.exists():
                    continue
                # Validate path is within expected directories
                if not (p.is_relative_to(docs) or p.is_relative_to(downloads)):
                    logger.warning("Skipping path outside managed dirs: %s", p)
                    continue
                if scope == "downloads" and not p.is_relative_to(downloads):
                    continue
                to_process.append((p, row[0]))

    if not to_process:
        print("No duplicates to process.")
        return 0

    # Confirm before delete
    if action == "delete" and not dry_run:
        answer = input(f"Delete {len(to_process)} files? [y/N]: ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return 0

    processed = 0
    for p, sha in to_process:
        if dry_run:
            print(f"  [{action}] {p}")
            processed += 1
            continue
        if action == "quarantine":
            dest = safe_dest(p, quarantine)
            atomic_move(p, dest)
            log_operation(logger, op="dedup", action="quarantine",
                          src=str(p), dst=str(dest), sha256=sha,
                          dry_run=False, status="ok")
        elif action == "delete":
            p.unlink()
            log_operation(logger, op="dedup", action="delete",
                          src=str(p), sha256=sha,
                          dry_run=False, status="ok")
        processed += 1

    tag = " [DRY RUN]" if dry_run else ""
    print(f"Dedup complete: {processed} files {action}d{tag}")
    return processed
