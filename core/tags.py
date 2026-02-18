"""Tag system — JSON-based tag storage and query engine."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("docman")


class TagDB:
    """JSON-based tag database mapping file paths to tag lists."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """Load tag database from disk."""
        if self.db_path.exists():
            try:
                self._data = json.loads(self.db_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load tag DB: %s", e)
                self._data = {}

    def _save(self) -> None:
        """Persist tag database to disk."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def add_tags(self, path: str, tags: list[str]) -> None:
        """Add tags to a file."""
        entry = self._data.get(path, {"tags": [], "updated": ""})
        existing = set(entry["tags"])
        existing.update(t.lower().strip() for t in tags)
        entry["tags"] = sorted(existing)
        entry["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self._data[path] = entry
        self._save()

    def remove_tags(self, path: str, tags: list[str]) -> None:
        """Remove tags from a file."""
        if path not in self._data:
            return
        remove_set = {t.lower().strip() for t in tags}
        self._data[path]["tags"] = [t for t in self._data[path]["tags"] if t not in remove_set]
        self._data[path]["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        if not self._data[path]["tags"]:
            del self._data[path]
        self._save()

    def get_tags(self, path: str) -> list[str]:
        """Get tags for a file."""
        entry = self._data.get(path, {})
        return entry.get("tags", [])

    def list_all(self) -> dict[str, dict[str, Any]]:
        """List all tagged files."""
        return dict(self._data)

    def search_by_tag(self, tag: str) -> list[str]:
        """Find all files with a given tag."""
        tag = tag.lower().strip()
        return [path for path, entry in self._data.items()
                if tag in entry.get("tags", [])]

    def update_path(self, old_path: str, new_path: str) -> None:
        """Update path in tag DB after a file move."""
        if old_path in self._data:
            self._data[new_path] = self._data.pop(old_path)
            self._data[new_path]["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            self._save()

    def get_stats(self) -> dict[str, Any]:
        """Get tag statistics for dashboard."""
        all_tags: dict[str, int] = {}
        for entry in self._data.values():
            for tag in entry.get("tags", []):
                all_tags[tag] = all_tags.get(tag, 0) + 1
        top_tags = sorted(all_tags.items(), key=lambda x: x[1], reverse=True)[:10]
        return {
            "total_tagged_files": len(self._data),
            "total_unique_tags": len(all_tags),
            "top_tags": top_tags,
        }


def auto_tag_from_categories(cfg: dict[str, Any], db: TagDB) -> int:
    """Auto-tag files based on their category directory structure."""
    docs = Path(cfg["docs_dir"])
    count = 0

    try:
        from docman.rules.registry import RuleRegistry
        registry = RuleRegistry()
        org_dirs = registry.organized_dirs
    except Exception:
        org_dirs = []

    for org_dir in org_dirs:
        d = docs / org_dir
        if not d.exists():
            continue
        # Use the top-level category name as a tag
        # e.g., "01_Business/Finance" -> tags: ["business", "finance"]
        parts = org_dir.replace("/", "_").split("_")
        tags = [p.lower() for p in parts if p and not p[0].isdigit()]

        try:
            for f in d.rglob("*"):
                if f.is_file() and not f.name.startswith("."):
                    path_str = str(f.resolve())
                    existing = db.get_tags(path_str)
                    new_tags = [t for t in tags if t not in existing]
                    if new_tags:
                        db.add_tags(path_str, new_tags)
                        count += 1
        except PermissionError:
            pass

    return count
