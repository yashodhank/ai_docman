"""Shared file operations: hashing, safe destinations, atomic moves."""
from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

MAX_HASH_SIZE = 500 * 1024 * 1024  # 500 MB


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest. Returns sentinel strings for special cases."""
    if path.is_dir():
        return "directory"
    try:
        sz = path.stat().st_size
        if sz > MAX_HASH_SIZE:
            return "skipped_too_large"
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return "error"


def safe_dest(src: Path, dest_dir: Path) -> Path:
    """Return a collision-free destination path under dest_dir."""
    target = dest_dir / src.name
    if not target.exists():
        return target
    stem = src.stem
    suffix = src.suffix
    n = 1
    while True:
        candidate = dest_dir / f"{stem}__dup{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def atomic_move(src: Path, dst: Path) -> None:
    """Move src to dst, creating parent directories as needed."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
