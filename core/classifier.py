"""Classifier — replaces full_organize.py + inbox_classify.py + generate_moves.sh."""
from __future__ import annotations

import logging
from collections import Counter
from pathlib import Path
from typing import Any

from docman.fileops import safe_dest, atomic_move, sha256_file
from docman.logging_setup import CSVSummaryWriter, log_operation
from docman.rules.registry import RuleRegistry

logger = logging.getLogger("docman")


def run_classify(cfg: dict[str, Any], scope: str = "all",
                 dry_run: bool = False, verbose: bool = False) -> None:
    """Classify loose files.

    scope: "all" — top-level ~/Documents
           "inbox" — items in 00_Inbox_Documents
           "downloads" — items in ~/Downloads (top-level, excluding Projects)
    """
    docs = Path(cfg["docs_dir"])
    downloads = Path(cfg["downloads_dir"])
    skip = set(cfg["skip_dirs"])
    keep_in_inbox = set(cfg.get("keep_in_inbox", []))
    registry = RuleRegistry()
    log_dir = docs / cfg["log_dir"]
    log_dir.mkdir(parents=True, exist_ok=True)

    # Collect items to classify
    items: list[Path] = []
    if scope in ("all", "documents"):
        items.extend(
            p for p in sorted(docs.iterdir())
            if p.name not in skip and p.name != ".DS_Store"
        )
    if scope == "inbox":
        inbox = docs / cfg["inbox_dir"]
        if inbox.exists():
            items.extend(
                p for p in sorted(inbox.iterdir())
                if p.name not in keep_in_inbox and p.name != ".DS_Store"
            )
    if scope == "downloads":
        dl_exclude = set(cfg.get("downloads_exclude", []))
        if downloads.exists():
            items.extend(
                p for p in sorted(downloads.iterdir())
                if p.name not in dl_exclude and p.name != ".DS_Store"
            )

    moves: list[tuple[Path, Path, str, str]] = []  # src, dst, category, rule
    for item in items:
        proposal = registry.classify(item, docs)
        # For inbox scope, skip items that would stay in inbox
        if scope == "inbox" and proposal.rule == "fallback":
            continue
        dest = safe_dest(item, proposal.destination.parent)
        moves.append((item, dest, proposal.category, proposal.rule))

    if dry_run:
        print(f"=== DRY RUN ({scope}): {len(moves)} items to move ===\n")
        for src, dst, cat, rule in moves:
            print(f"  {src.name}")
            print(f"    -> {cat}/  [{rule}]\n")
        counts = Counter(cat for _, _, cat, _ in moves)
        print(f"Total: {len(moves)} items\n\nBy destination:")
        for cat, cnt in sorted(counts.items()):
            print(f"  {cat}: {cnt}")

        inbox_items = [src.name for src, _, cat, _ in moves if cat == cfg["inbox_dir"]]
        if inbox_items:
            print(f"\n{len(inbox_items)} items going to Inbox (unclassified):")
            for name in inbox_items:
                print(f"    {name}")
    else:
        csv_writer = CSVSummaryWriter(log_dir, "classify")
        csv_writer.open(["timestamp", "source", "destination", "category", "rule"])
        from datetime import datetime
        ts = datetime.now().isoformat()

        for src, dst, cat, rule in moves:
            sha = sha256_file(src) if src.is_file() else "directory"
            size = src.stat().st_size if src.is_file() and src.exists() else 0
            atomic_move(src, dst)
            csv_writer.writerow([ts, str(src), str(dst), cat, rule])
            log_operation(logger, op="move", src=str(src), dst=str(dst),
                          sha256=sha, size=size, category=cat, rule=rule,
                          dry_run=False, status="ok")
            if verbose:
                print(f"  {src.name} -> {cat}/")

        csv_path = csv_writer.close()
        print(f"\n=== Done: {len(moves)} items moved ===")
        print(f"Log: {csv_path}")
        log_operation(logger, op="classify", scope=scope,
                      items_moved=len(moves), dry_run=False, status="ok")
