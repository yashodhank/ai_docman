"""Daily Downloads triage — replaces daily_triage.sh."""
from __future__ import annotations

import logging
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from docman.fileops import sha256_file
from docman.logging_setup import log_operation
from docman.rules.registry import RuleRegistry

logger = logging.getLogger("docman")

HIGH_VALUE_EXTS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".csv",
    ".pptx", ".ppt", ".txt", ".rtf", ".odt", ".ods",
}


def run_triage(cfg: dict[str, Any], weekly: bool = False,
               dry_run: bool = False, verbose: bool = False) -> None:
    """Daily Downloads capture + optional weekly hygiene."""
    docs = Path(cfg["docs_dir"])
    downloads = Path(cfg["downloads_dir"])
    inbox = docs / cfg["inbox_dir"]
    triage_dir = inbox / "Downloads_Triage"
    dl_exclude = set(cfg.get("downloads_exclude", []))
    now = datetime.now()
    month_dir = triage_dir / now.strftime("%Y-%m")

    if not dry_run:
        month_dir.mkdir(parents=True, exist_ok=True)

    # Part 1: Capture high-value new files from Downloads (last 24h)
    captured = 0
    cutoff = now.timestamp() - 86400  # 24 hours ago
    if downloads.exists():
        for fpath in downloads.rglob("*"):
            if not fpath.is_file():
                continue
            try:
                rel = fpath.relative_to(downloads)
            except ValueError:
                continue
            if len(rel.parts) > 2:
                continue
            if rel.parts and rel.parts[0] in dl_exclude:
                continue
            if fpath.suffix.lower() not in HIGH_VALUE_EXTS:
                continue
            try:
                if fpath.stat().st_mtime < cutoff:
                    continue
            except OSError:
                continue
            dest = month_dir / fpath.name
            if dest.exists():
                continue
            if dry_run:
                print(f"  [capture] {fpath.name}")
            else:
                shutil.copy2(str(fpath), str(dest))
                if verbose:
                    print(f"  Captured: {fpath.name}")
            captured += 1

    print(f"Captured {captured} new files" + (" [DRY RUN]" if dry_run else f" to {month_dir}"))

    # Part 2: Classify captured files using RuleRegistry
    registry = RuleRegistry()
    proposed = 0
    if month_dir.exists():
        for fpath in month_dir.iterdir():
            if not fpath.is_file():
                continue
            proposal = registry.classify(fpath, docs)
            if proposal.rule != "fallback":
                proposed += 1
                if verbose or dry_run:
                    print(f"  [propose] {fpath.name} -> {proposal.category}/ [{proposal.rule}]")

    print(f"Proposed {proposed} placements")

    # Part 3: Weekly hygiene
    if weekly:
        print("\n=== Weekly Hygiene Report ===")

        # Check for duplicates in triage against index
        index_file = docs / cfg["index_dir"] / "file_index.csv"
        dup_count = 0
        if index_file.exists() and triage_dir.exists():
            import csv as csv_mod
            index_shas: set[str] = set()
            with open(index_file, encoding="utf-8") as f:
                reader = csv_mod.DictReader(f)
                for row in reader:
                    sha = row.get("sha256", "")
                    if sha and sha not in ("icloud_placeholder", "skipped_too_large", "error"):
                        index_shas.add(sha)

            for fpath in triage_dir.rglob("*"):
                if not fpath.is_file():
                    continue
                sha = sha256_file(fpath)
                if sha in index_shas:
                    dup_count += 1
                    if verbose:
                        print(f"  Potential duplicate: {fpath.name}")
            print(f"Found {dup_count} potential duplicates in triage")

        # Inbox backlog
        inbox_count = 0
        if inbox.exists():
            inbox_count = sum(1 for p in inbox.rglob("*")
                              if p.is_file() and p.name != "notes.txt")
        print(f"Inbox backlog: {inbox_count} files")

        # Naming violations
        violations = 0
        for org_dir in ["01_Business", "02_Personal"]:
            d = docs / org_dir
            if d.exists():
                for f in d.rglob("*"):
                    if f.is_file() and " " in f.name and f.name != "notes.txt":
                        violations += 1
        print(f"Naming violations (files with spaces): {violations}")

    log_operation(logger, op="triage", captured=captured, proposed=proposed,
                  weekly=weekly, dry_run=dry_run, status="ok")
