"""Undo (reverse) moves from JSONL log."""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from docman.fileops import sha256_file, atomic_move
from docman.logging_setup import log_operation

logger = logging.getLogger("docman")


def _record_undo_correction(cfg: dict[str, Any], rec: dict, src: Path, dst: Path) -> None:
    """Record an undo as a classification correction for adaptive learning."""
    try:
        docs = Path(cfg["docs_dir"]).resolve()
        index_dir = docs / Path(cfg["index_dir"])
        from docman.ai.learning import LearningDB
        db = LearningDB(index_dir / "learning.json")

        # Determine categories from paths
        from_category = rec.get("category", "")
        if not from_category and src.is_relative_to(docs):
            # Extract category from the src path (where the file currently is)
            rel = src.relative_to(docs)
            from_category = str(rel.parts[0]) if rel.parts else ""

        to_category = ""
        if dst.is_relative_to(docs):
            rel = dst.relative_to(docs)
            to_category = str(rel.parts[0]) if rel.parts else ""

        if from_category and to_category and from_category != to_category:
            db.record_correction(src.name, from_category, to_category)
    except Exception as e:
        logger.debug("Failed to record undo correction: %s", e)


def run_undo(cfg: dict[str, Any], last: int | None = None,
             since: str | None = None, dry_run: bool = False,
             verbose: bool = False) -> int:
    """Reverse moves from JSONL log. Returns count of undone moves."""
    docs = Path(cfg["docs_dir"]).resolve()
    downloads = Path(cfg["downloads_dir"]).resolve()
    log_dir = docs / cfg["log_dir"]
    jsonl = log_dir / "docman.jsonl"

    if not jsonl.exists():
        print("No log file found.")
        return 0

    # Validate --last
    if last is not None and last <= 0:
        print("Error: --last must be a positive integer.")
        sys.exit(1)

    # Validate --since
    if since:
        try:
            datetime.fromisoformat(since)
        except ValueError:
            print(f"Error: --since must be ISO format (e.g. 2024-01-15T10:00:00). Got: {since}")
            sys.exit(1)

    # Collect move records
    moves: list[dict] = []
    with open(jsonl, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("op") not in ("move", "quarantine"):
                continue
            if not rec.get("src") or not rec.get("dst"):
                continue
            moves.append(rec)

    # Filter
    if since:
        moves = [m for m in moves if m.get("ts", "") >= since]
    if last:
        moves = moves[-last:]

    # Reverse in reverse order
    moves.reverse()

    undone = 0
    for rec in moves:
        src = Path(rec["dst"]).resolve()   # current location
        dst = Path(rec["src"]).resolve()   # original location
        expected_sha = rec.get("sha256", "")

        # Validate paths are within expected directories
        if not (src.is_relative_to(docs) or src.is_relative_to(downloads)):
            logger.warning("Skipping undo — source outside managed dirs: %s", src)
            continue
        if not (dst.is_relative_to(docs) or dst.is_relative_to(downloads)):
            logger.warning("Skipping undo — destination outside managed dirs: %s", dst)
            continue

        if not src.exists():
            print(f"  SKIP (missing): {src}")
            continue

        # Verify SHA before undo
        if expected_sha and expected_sha not in ("directory", "skipped_too_large", "error"):
            actual = sha256_file(src)
            if actual != expected_sha:
                print(f"  SKIP (SHA mismatch): {src}")
                continue

        if dry_run:
            print(f"  [undo] {src} -> {dst}")
        else:
            atomic_move(src, dst)
            log_operation(logger, op="undo", src=str(src), dst=str(dst),
                          sha256=expected_sha, dry_run=False, status="ok")
            # Record correction for adaptive learning
            _record_undo_correction(cfg, rec, src, dst)
            if verbose:
                print(f"  Undone: {src.name} -> {dst.parent}")
        undone += 1

    tag = " [DRY RUN]" if dry_run else ""
    print(f"\nUndo complete: {undone} moves reversed{tag}")
    return undone
