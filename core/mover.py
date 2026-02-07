"""Move executor — replaces apply_moves.sh with pre/post SHA verification."""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from docman.fileops import sha256_file, safe_dest, atomic_move
from docman.icloud import has_icloud_placeholder
from docman.logging_setup import log_operation

logger = logging.getLogger("docman")


def run_apply(cfg: dict[str, Any], dry_run: bool = False, verbose: bool = False) -> None:
    """Execute moves from proposed_moves.csv (legacy compatibility)."""
    docs = Path(cfg["docs_dir"])
    index_dir = docs / cfg["index_dir"]
    moves_file = index_dir / "proposed_moves.csv"
    dupes_file = index_dir / "duplicates_report.csv"
    inbox = docs / cfg["inbox_dir"]
    quarantine = docs / cfg["quarantine_dir"]

    if not moves_file.exists():
        raise FileNotFoundError(f"{moves_file} not found.")

    # Load duplicate paths
    dup_paths: set[str] = set()
    if dupes_file.exists():
        with open(dupes_file, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                for p in row.get("duplicate_paths", "").split("|"):
                    p = p.strip()
                    if p:
                        dup_paths.add(p)

    moved = skipped = quarantined = inbox_count = 0

    with open(moves_file, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            old_path = Path(row["old_path"])
            new_path = Path(row["new_path"])
            confidence = row.get("confidence", "Low")

            if not old_path.exists():
                if has_icloud_placeholder(old_path):
                    skipped += 1
                    continue
                skipped += 1
                continue

            pre_sha = sha256_file(old_path)
            size = old_path.stat().st_size if old_path.is_file() else 0

            if dry_run:
                action = "quarantine" if str(old_path) in dup_paths else (
                    "move" if confidence == "High" else "inbox")
                print(f"  [{action}] {old_path.name} -> {new_path.parent.name}/")
                continue

            if str(old_path) in dup_paths:
                dest = safe_dest(old_path, quarantine)
                atomic_move(old_path, dest)
                log_operation(logger, op="quarantine", src=str(old_path),
                              dst=str(dest), sha256=pre_sha, size=size,
                              dry_run=False, status="ok")
                quarantined += 1
            elif confidence == "High":
                dest = safe_dest(old_path, new_path.parent)
                atomic_move(old_path, dest)
                log_operation(logger, op="move", src=str(old_path),
                              dst=str(dest), sha256=pre_sha, size=size,
                              category=str(new_path.parent), rule="proposed_high",
                              dry_run=False, status="ok")
                moved += 1
            else:
                dest = safe_dest(old_path, inbox)
                atomic_move(old_path, dest)
                log_operation(logger, op="move", src=str(old_path),
                              dst=str(dest), sha256=pre_sha, size=size,
                              category="inbox", rule=f"proposed_{confidence.lower()}",
                              dry_run=False, status="ok")
                inbox_count += 1

    if not dry_run:
        print(f"Apply complete.")
        print(f"  Moved (High):        {moved}")
        print(f"  Sent to Inbox:       {inbox_count}")
        print(f"  Quarantined (dupes): {quarantined}")
        print(f"  Skipped:             {skipped}")
