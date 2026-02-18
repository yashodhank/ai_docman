"""Filesystem watcher daemon — monitors directories for new files and auto-triages."""
from __future__ import annotations

import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from docman.logging_setup import log_operation

logger = logging.getLogger("docman")

PID_FILE = Path.home() / ".docman-watcher.pid"


def _triage_file(cfg: dict[str, Any], file_path: Path,
                 dry_run: bool = False, verbose: bool = False) -> None:
    """Classify and move a single file using rule-based classification."""
    from docman.rules.registry import RuleRegistry
    from docman.fileops import safe_dest, atomic_move, sha256_file

    docs = Path(cfg["docs_dir"])
    inbox = docs / cfg["inbox_dir"]
    watch_cfg = cfg.get("watch", {})
    min_confidence = watch_cfg.get("auto_classify_confidence", "high")

    registry = RuleRegistry()
    proposal = registry.classify(file_path, docs)

    # Only auto-move if confidence meets threshold
    confidence_ok = (
        min_confidence == "low" or
        (min_confidence == "medium" and proposal.rule != "fallback") or
        (min_confidence == "high" and proposal.rule != "fallback" and proposal.category != cfg["inbox_dir"])
    )

    if confidence_ok and proposal.category != cfg["inbox_dir"]:
        dest_dir = docs / proposal.category
        dest = safe_dest(file_path, dest_dir)
    else:
        dest = safe_dest(file_path, inbox)

    if dry_run:
        print(f"  [auto] {file_path.name} -> {dest.parent.name}/")
        return

    try:
        sha = sha256_file(file_path) if file_path.is_file() else "directory"
        size = file_path.stat().st_size if file_path.is_file() else 0
        atomic_move(file_path, dest)
        log_operation(logger, op="auto_triage", src=str(file_path), dst=str(dest),
                      sha256=sha, size=size, category=proposal.category,
                      rule=proposal.rule, dry_run=False, status="ok")
        if verbose:
            print(f"  Auto-triaged: {file_path.name} -> {dest.parent.name}/")
    except Exception as e:
        logger.error("Auto-triage failed for %s: %s", file_path, e)


def start_watcher(cfg: dict[str, Any], watch_dirs: list[Path] | None = None,
                  debounce_seconds: int = 5, dry_run: bool = False,
                  verbose: bool = False) -> None:
    """Start the filesystem watcher."""
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler, FileCreatedEvent, FileModifiedEvent
    except ImportError:
        print("watchdog is required for watch mode.")
        print("Install it with: pip install 'docman[watch]'")
        sys.exit(1)

    watch_cfg = cfg.get("watch", {})
    if watch_dirs is None:
        watch_dirs = [Path(d).expanduser() for d in watch_cfg.get("directories", ["~/Downloads"])]

    # Write PID file
    PID_FILE.write_text(str(os.getpid()))

    class DebouncedHandler(FileSystemEventHandler):
        """Handles file events with debouncing to ensure downloads complete."""

        def __init__(self):
            super().__init__()
            self._pending: dict[str, float] = {}

        def on_created(self, event):
            if not event.is_directory:
                self._pending[event.src_path] = time.time()

        def on_modified(self, event):
            if not event.is_directory and event.src_path in self._pending:
                self._pending[event.src_path] = time.time()

        def process_pending(self):
            """Process files that have been stable for debounce_seconds."""
            now = time.time()
            ready = [p for p, t in self._pending.items()
                     if now - t >= debounce_seconds]
            for path_str in ready:
                del self._pending[path_str]
                file_path = Path(path_str)
                if file_path.exists() and file_path.is_file():
                    if file_path.name.startswith(".") or file_path.name in (".DS_Store",):
                        continue
                    print(f"  New file detected: {file_path.name}")
                    _triage_file(cfg, file_path, dry_run=dry_run, verbose=verbose)

    handler = DebouncedHandler()
    observer = Observer()

    for d in watch_dirs:
        if d.exists():
            observer.schedule(handler, str(d), recursive=False)
            print(f"Watching: {d}")
        else:
            print(f"Warning: {d} does not exist, skipping")

    def _shutdown(signum, frame):
        print("\nStopping watcher...")
        observer.stop()
        PID_FILE.unlink(missing_ok=True)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    observer.start()
    print(f"Watcher started (PID {os.getpid()}, debounce {debounce_seconds}s)")
    print("Press Ctrl+C to stop.\n")

    try:
        while observer.is_alive():
            handler.process_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        PID_FILE.unlink(missing_ok=True)
        print("Watcher stopped.")


def stop_watcher() -> None:
    """Stop a running watcher daemon."""
    if not PID_FILE.exists():
        print("No watcher is running.")
        return

    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Sent stop signal to watcher (PID {pid})")
        # Wait briefly for cleanup
        time.sleep(1)
        PID_FILE.unlink(missing_ok=True)
    except ProcessLookupError:
        print("Watcher process not found. Cleaning up PID file.")
        PID_FILE.unlink(missing_ok=True)
    except ValueError:
        print("Invalid PID file. Cleaning up.")
        PID_FILE.unlink(missing_ok=True)
    except PermissionError:
        print(f"Permission denied sending signal to PID. Try: kill {pid}")
