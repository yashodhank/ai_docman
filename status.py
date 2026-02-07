"""Health report generation."""
from __future__ import annotations

import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("docman")


def generate_report(cfg: dict[str, Any]) -> str:
    """Build and return a health report string."""
    docs = Path(cfg["docs_dir"])
    log_dir = docs / cfg["log_dir"]
    index_dir = docs / cfg["index_dir"]
    inbox = docs / cfg["inbox_dir"]

    lines: list[str] = []
    lines.append("Document Organization Health")
    lines.append("-" * 40)

    # Inbox backlog
    inbox_count = 0
    if inbox.exists():
        inbox_count = sum(1 for p in inbox.iterdir() if p.name not in (".DS_Store", "notes.txt", "Downloads_Triage"))
    lines.append(f"Inbox backlog:       {inbox_count} items")

    # Unclassified top-level
    skip = set(cfg["skip_dirs"])
    top_level = 0
    if docs.exists():
        top_level = sum(1 for p in docs.iterdir() if p.name not in skip and not p.name.startswith("."))
    lines.append(f"Unclassified:        {top_level} top-level items")

    # Total indexed
    index_file = index_dir / "file_index.csv"
    indexed = 0
    if index_file.exists():
        with open(index_file, encoding="utf-8") as f:
            indexed = sum(1 for _ in f) - 1  # minus header
    lines.append(f"Total indexed:       {indexed:,} files")

    # Duplicate groups
    dup_file = index_dir / "duplicates_report.csv"
    dup_groups = 0
    dup_waste = 0
    if dup_file.exists():
        with open(dup_file, encoding="utf-8") as f:
            reader = csv.reader(f)
            next(reader, None)  # skip header
            for row in reader:
                dup_groups += 1
                try:
                    canonical = Path(row[1].strip('"'))
                    if canonical.exists():
                        n_dupes = len(row[2].split("|")) if len(row) > 2 else 0
                        dup_waste += canonical.stat().st_size * n_dupes
                except (IndexError, OSError):
                    pass
    waste_mb = dup_waste / 1_048_576
    lines.append(f"Duplicate groups:    {dup_groups} ({waste_mb:.0f} MB wasted)")

    # Last operation timestamps from JSONL log
    jsonl = log_dir / "docman.jsonl"
    last_ops: dict[str, str] = {}
    if jsonl.exists():
        with open(jsonl, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    op = rec.get("op", "")
                    ts = rec.get("ts", "")
                    if op:
                        last_ops[op] = ts
                except json.JSONDecodeError:
                    pass

    for op_name, label in [("index", "Last index"), ("classify", "Last classify"), ("triage", "Last triage")]:
        ts = last_ops.get(op_name, "never")
        lines.append(f"{label + ':':21s}{ts}")

    # Naming violations (files with spaces in organized folders)
    violations = 0
    try:
        from docman.rules.registry import RuleRegistry
        org_dirs = RuleRegistry().organized_dirs
    except Exception:
        org_dirs = []
    for org_dir in org_dirs:
        d = docs / org_dir
        if d.exists():
            for f in d.rglob("*"):
                if f.is_file() and " " in f.name and f.name != "notes.txt":
                    violations += 1
    lines.append(f"Naming violations:   {violations} files with spaces")

    return "\n".join(lines)
