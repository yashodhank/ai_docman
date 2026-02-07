"""iCloud placeholder detection."""
from __future__ import annotations

from pathlib import Path


def is_icloud_placeholder(path: Path) -> bool:
    """Check if a file is an iCloud placeholder (.filename.icloud)."""
    name = path.name
    if name.endswith(".icloud") and name.startswith("."):
        return True
    return False


def has_icloud_placeholder(path: Path) -> bool:
    """Check if a local file has an iCloud evicted placeholder sibling."""
    parent = path.parent
    placeholder = parent / f".{path.name}.icloud"
    return placeholder.exists()


def real_name_from_placeholder(path: Path) -> str:
    """Extract the real filename from a .filename.icloud placeholder."""
    name = path.name
    if name.startswith(".") and name.endswith(".icloud"):
        return name[1:-7]  # strip leading dot and trailing .icloud
    return name
