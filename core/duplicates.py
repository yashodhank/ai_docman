"""Duplicate detection — replaces detect_duplicates.sh with proper CSV parsing."""
from __future__ import annotations

import csv
import difflib
import hashlib
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Any

from docman.logging_setup import log_operation
from docman.models import DuplicateGroup

logger = logging.getLogger("docman")

SKIP_SHA = {"icloud_placeholder", "skipped_too_large", "error", ""}

# Directories to always skip during filesystem traversal
_JUNK_DIRS = {"node_modules", ".git", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache"}

DEFAULT_FUZZY_LIMIT = 50_000


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


def _partial_sha256(path: Path, chunk_size: int = 4096) -> str:
    """Compute SHA-256 of the first + last chunk_size bytes of a file."""
    try:
        size = path.stat().st_size
        h = hashlib.sha256()
        with open(path, "rb") as f:
            h.update(f.read(chunk_size))
            if size > chunk_size * 2:
                f.seek(-chunk_size, 2)
                h.update(f.read(chunk_size))
        return h.hexdigest()
    except OSError:
        return "error"


def _full_sha256(path: Path) -> str:
    """Compute full SHA-256 of a file."""
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "error"


def _walk_managed(cfg: dict[str, Any], verbose: bool = False) -> list[Path]:
    """Walk managed directories with junk-dir skipping and depth limiting."""
    docs = Path(cfg["docs_dir"])
    downloads = Path(cfg["downloads_dir"])
    downloads_max_depth = cfg.get("downloads_max_depth", 3)
    downloads_exclude = set(cfg.get("downloads_exclude", []))

    files: list[Path] = []
    file_count = 0

    for root_dir, max_depth in [(docs, 0), (downloads, downloads_max_depth)]:
        if not root_dir.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(root_dir):
            dp = Path(dirpath)
            # Skip junk directories
            dirnames[:] = [d for d in dirnames if d not in _JUNK_DIRS]
            # Skip _System in docs
            if root_dir == docs:
                dirnames[:] = [d for d in dirnames if d != "_System"]
            # Skip excluded dirs in downloads
            if root_dir == downloads:
                try:
                    rel = dp.relative_to(downloads)
                    if rel.parts and rel.parts[0] in downloads_exclude:
                        dirnames.clear()
                        continue
                except ValueError:
                    pass
            # Depth limiting
            if max_depth > 0:
                depth = len(dp.relative_to(root_dir).parts)
                if depth >= max_depth:
                    dirnames.clear()
            for fn in filenames:
                if not fn.startswith("."):
                    files.append(dp / fn)
                    file_count += 1
                    if verbose and file_count % 10_000 == 0:
                        print(f"  Scanning... {file_count:,} files found")

    if verbose:
        print(f"  Total: {len(files):,} files to check")
    return files


def run_fast_duplicates(cfg: dict[str, Any], dry_run: bool = False,
                        verbose: bool = False) -> Path:
    """Fast 3-tier duplicate scanner: size -> partial hash -> full hash."""
    docs = Path(cfg["docs_dir"])
    index_dir = docs / cfg["index_dir"]
    output = index_dir / "fast_duplicates_report.csv"

    # Tier 1: Group all files by size
    size_groups: dict[int, list[Path]] = {}
    all_files = _walk_managed(cfg, verbose=verbose)

    for p in all_files:
        try:
            size = p.stat().st_size
            if size == 0:
                continue
            size_groups.setdefault(size, []).append(p)
        except OSError:
            continue

    # Filter to size groups with >1 file
    candidates = {s: paths for s, paths in size_groups.items() if len(paths) > 1}
    if verbose:
        total_files = sum(len(paths) for paths in candidates.values())
        print(f"Tier 1 (size): {len(candidates)} size groups, {total_files} files to check")

    # Tier 2: Compare partial hash (first+last 4KB)
    partial_groups: dict[str, list[Path]] = {}
    for size, paths in candidates.items():
        for p in paths:
            key = f"{size}:{_partial_sha256(p)}"
            partial_groups.setdefault(key, []).append(p)

    partial_candidates = {k: v for k, v in partial_groups.items() if len(v) > 1}
    if verbose:
        total_files = sum(len(paths) for paths in partial_candidates.values())
        print(f"Tier 2 (partial hash): {len(partial_candidates)} groups, {total_files} files to check")

    # Tier 3: Full SHA-256 only for remaining candidates
    full_groups: dict[str, list[Path]] = {}
    for key, paths in partial_candidates.items():
        for p in paths:
            sha = _full_sha256(p)
            if sha == "error":
                continue
            full_groups.setdefault(sha, []).append(p)

    # Build final groups
    groups: list[DuplicateGroup] = []
    for sha, paths in full_groups.items():
        if len(paths) < 2:
            continue
        paths.sort(key=lambda p: (0 if "/Documents/" in str(p) else 1, len(str(p))))
        canonical = paths[0]
        duplicates = paths[1:]
        try:
            size = canonical.stat().st_size
        except OSError:
            size = 0
        groups.append(DuplicateGroup(sha256=sha, size_bytes=size,
                                     canonical=canonical, duplicates=duplicates))

    if dry_run:
        print(f"[DRY RUN] Would find {len(groups)} duplicate groups via fast scan.")
        return output

    index_dir.mkdir(parents=True, exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["sha256", "canonical_path", "duplicate_paths", "size_bytes"])
        for g in groups:
            dup_str = "|".join(str(d) for d in g.duplicates)
            writer.writerow([g.sha256, str(g.canonical), dup_str, g.size_bytes])

    wasted = sum(g.size_bytes * len(g.duplicates) for g in groups)
    print(f"Fast scan done. {len(groups)} duplicate groups ({wasted / 1_048_576:.1f} MB wasted). Output: {output}")
    log_operation(logger, op="fast_duplicates", groups_found=len(groups),
                  wasted_mb=round(wasted / 1_048_576, 1),
                  output=str(output), dry_run=False, status="ok")
    return output


def run_fuzzy_duplicates(cfg: dict[str, Any], dry_run: bool = False,
                         verbose: bool = False, threshold: float = 0.85,
                         limit: int = 0) -> Path:
    """Find files with similar names using fuzzy matching."""
    docs = Path(cfg["docs_dir"])
    index_dir = docs / cfg["index_dir"]
    output = index_dir / "fuzzy_duplicates_report.csv"

    max_files = limit if limit > 0 else DEFAULT_FUZZY_LIMIT

    # Collect all file paths using managed walker
    all_files = _walk_managed(cfg, verbose=verbose)

    if len(all_files) > max_files:
        print(f"  Warning: {len(all_files):,} files exceeds fuzzy limit ({max_files:,}). "
              f"Truncating. Use --limit to adjust.")
        all_files = all_files[:max_files]

    if verbose:
        print(f"Comparing {len(all_files):,} files for similar names...")

    # Group files by extension to reduce comparisons (only compare within same ext)
    ext_groups: dict[str, list[Path]] = defaultdict(list)
    for f in all_files:
        ext_groups[f.suffix.lower()].append(f)

    # Compare filenames within each extension group
    fuzzy_groups: list[tuple[Path, Path, float]] = []
    seen: set[tuple[str, str]] = set()

    for ext, group in ext_groups.items():
        for i, f1 in enumerate(group):
            stem1 = f1.stem.lower()
            len1 = len(stem1)
            for f2 in group[i + 1:]:
                # Skip files in the same directory
                if f1.parent == f2.parent:
                    continue
                # Skip stems with very different lengths (>30% difference)
                stem2 = f2.stem.lower()
                len2 = len(stem2)
                if len1 > 0 and len2 > 0:
                    ratio_len = min(len1, len2) / max(len1, len2)
                    if ratio_len < 0.7:
                        continue
                ratio = difflib.SequenceMatcher(None, stem1, stem2).ratio()
                if ratio >= threshold:
                    key = tuple(sorted([str(f1), str(f2)]))
                    if key not in seen:
                        seen.add(key)
                        fuzzy_groups.append((f1, f2, ratio))

    fuzzy_groups.sort(key=lambda x: x[2], reverse=True)

    if dry_run:
        print(f"[DRY RUN] Would find {len(fuzzy_groups)} fuzzy name matches.")
        for f1, f2, ratio in fuzzy_groups[:20]:
            print(f"  [{ratio:.2f}] {f1.name} <-> {f2.name}")
        return output

    index_dir.mkdir(parents=True, exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["file_a", "file_b", "similarity"])
        for f1, f2, ratio in fuzzy_groups:
            writer.writerow([str(f1), str(f2), f"{ratio:.3f}"])

    print(f"Fuzzy scan done. {len(fuzzy_groups)} similar name pairs found. Output: {output}")
    log_operation(logger, op="fuzzy_duplicates", pairs_found=len(fuzzy_groups),
                  output=str(output), dry_run=False, status="ok")
    return output
