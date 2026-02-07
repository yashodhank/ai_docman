"""File indexer — replaces build_index.sh."""
from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

from docman.fileops import sha256_file
from docman.icloud import is_icloud_placeholder
from docman.logging_setup import CSVSummaryWriter, log_operation
from docman.models import FileEntry

logger = logging.getLogger("docman")


def _index_file(filepath: Path, max_hash_size: int) -> FileEntry:
    name = filepath.name
    ext = filepath.suffix.lstrip(".")
    icloud = "needs_download" if is_icloud_placeholder(filepath) else "local"
    try:
        st = filepath.stat()
        size = st.st_size
        mtime = datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        size = 0
        mtime = "unknown"

    if icloud == "needs_download":
        sha = "icloud_placeholder"
    elif size > max_hash_size:
        sha = "skipped_too_large"
    else:
        sha = sha256_file(filepath)

    return FileEntry(path=filepath, filename=name, extension=ext,
                     size_bytes=size, modified_date=mtime, sha256=sha,
                     icloud_status=icloud)


def run_index(cfg: dict[str, Any], dry_run: bool = False, verbose: bool = False) -> Path:
    """Build file index. Returns path to output CSV."""
    docs = Path(cfg["docs_dir"])
    downloads = Path(cfg["downloads_dir"])
    index_dir = docs / cfg["index_dir"]
    index_dir.mkdir(parents=True, exist_ok=True)
    output = index_dir / "file_index.csv"
    max_hash = cfg.get("max_hash_size_mb", 500) * 1024 * 1024
    dl_exclude = set(cfg.get("downloads_exclude", []))
    dl_depth = cfg.get("downloads_max_depth", 3)

    if dry_run:
        print("[DRY RUN] Would build index to:", output)
        return output

    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["path", "filename", "extension", "size_bytes",
                         "modified_date", "sha256", "icloud_status"])

        count = 0
        # Index ~/Documents (skip _System)
        for fpath in docs.rglob("*"):
            if not fpath.is_file():
                continue
            try:
                rel = fpath.relative_to(docs)
            except ValueError:
                continue
            if rel.parts and rel.parts[0] == "_System":
                continue
            entry = _index_file(fpath, max_hash)
            writer.writerow([str(entry.path), entry.filename, entry.extension,
                             entry.size_bytes, entry.modified_date, entry.sha256,
                             entry.icloud_status])
            count += 1
            if verbose and count % 500 == 0:
                print(f"  ...indexed {count} files from Documents")

        if verbose:
            print(f"Documents: {count} files indexed.")

        # Index ~/Downloads (limited depth)
        dl_count = 0
        if downloads.exists():
            for fpath in downloads.rglob("*"):
                if not fpath.is_file():
                    continue
                try:
                    rel = fpath.relative_to(downloads)
                except ValueError:
                    continue
                if len(rel.parts) > dl_depth:
                    continue
                if rel.parts and rel.parts[0] in dl_exclude:
                    continue
                entry = _index_file(fpath, max_hash)
                writer.writerow([str(entry.path), entry.filename, entry.extension,
                                 entry.size_bytes, entry.modified_date, entry.sha256,
                                 entry.icloud_status])
                dl_count += 1
                if verbose and dl_count % 500 == 0:
                    print(f"  ...indexed {dl_count} files from Downloads")

        if verbose:
            print(f"Downloads: {dl_count} files indexed.")

    total = count + dl_count
    print(f"Done. Total: {total} files. Output: {output}")
    log_operation(logger, op="index", files_indexed=total, output=str(output),
                  dry_run=False, status="ok")
    return output
