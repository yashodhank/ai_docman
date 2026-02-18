"""Data models for docman."""
from __future__ import annotations

import dataclasses as dc
from pathlib import Path


@dc.dataclass
class FileEntry:
    path: Path
    filename: str
    extension: str
    size_bytes: int
    modified_date: str
    sha256: str
    icloud_status: str  # "local" | "needs_download"


@dc.dataclass
class MoveProposal:
    source: Path
    destination: Path
    category: str
    rule: str  # which rule matched
    dry_run: bool = False


@dc.dataclass
class DuplicateGroup:
    sha256: str
    size_bytes: int
    canonical: Path
    duplicates: list[Path]


@dc.dataclass
class VerificationResult:
    path: Path
    expected_sha: str
    actual_sha: str
    status: str  # "ok" | "missing" | "mismatch" | "skipped"


@dc.dataclass
class CleanupResult:
    scanner: str  # "empty_dirs" | "broken_links" | "temp_files" | "large_files"
    path: Path
    size_bytes: int = 0
    action: str = "report"  # "report" | "delete"


@dc.dataclass
class TagEntry:
    path: str
    tags: list[str]
    updated: str


@dc.dataclass
class SearchResult:
    path: str
    score: float
    snippet: str = ""
