"""Shared file operations: hashing, safe destinations, atomic moves."""
from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path

MAX_HASH_SIZE = 500 * 1024 * 1024  # 500 MB
_SAFE_DEST_MAX_ITER = 10000


def sha256_file(path: Path) -> str:
    """Compute SHA-256 hex digest. Returns sentinel strings for special cases."""
    if path.is_dir():
        return "directory"
    try:
        # Resolve symlinks before hashing
        resolved = path.resolve()
        if not resolved.is_file():
            return "error"
        sz = resolved.stat().st_size
        if sz > MAX_HASH_SIZE:
            return "skipped_too_large"
        h = hashlib.sha256()
        with open(resolved, "rb") as f:
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
    while n <= _SAFE_DEST_MAX_ITER:
        candidate = dest_dir / f"{stem}__dup{n}{suffix}"
        if not candidate.exists():
            return candidate
        n += 1
    raise RuntimeError(f"Could not find a unique name after {_SAFE_DEST_MAX_ITER} attempts for {src.name}")


def safe_move(src: Path, dst: Path) -> None:
    """Move src to dst, creating parent directories as needed."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))


# Backwards compatibility alias
atomic_move = safe_move

_LOCK_FILE = Path.home() / ".docman.lock"


def acquire_lock() -> bool:
    """Acquire a PID-based process lock. Returns True if acquired."""
    if _LOCK_FILE.exists():
        try:
            pid = int(_LOCK_FILE.read_text().strip())
            # Check if the process is still alive
            os.kill(pid, 0)
            return False  # Process is still running
        except (ValueError, ProcessLookupError, PermissionError):
            # Stale lock file — remove it
            _LOCK_FILE.unlink(missing_ok=True)
    _LOCK_FILE.write_text(str(os.getpid()))
    return True


def release_lock() -> None:
    """Release the process lock."""
    try:
        if _LOCK_FILE.exists():
            pid = int(_LOCK_FILE.read_text().strip())
            if pid == os.getpid():
                _LOCK_FILE.unlink(missing_ok=True)
    except (ValueError, OSError):
        _LOCK_FILE.unlink(missing_ok=True)
