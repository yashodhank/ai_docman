"""Adaptive learning — stores classification corrections and confidence overrides."""
from __future__ import annotations

import fnmatch
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("docman")


class LearningDB:
    """JSON-based learning database for classification feedback."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._data: dict[str, Any] = {"corrections": [], "confidence_overrides": {}}
        self._load()

    def _load(self) -> None:
        if self.db_path.exists():
            try:
                self._data = json.loads(self.db_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as e:
                logger.warning("Failed to load learning DB: %s", e)
                self._data = {"corrections": [], "confidence_overrides": {}}

    def _save(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path.write_text(
            json.dumps(self._data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def record_correction(self, filename: str, from_category: str, to_category: str) -> None:
        """Record a classification correction (e.g., from undo)."""
        # Generalize the filename into a pattern
        stem = Path(filename).stem.lower()
        ext = Path(filename).suffix.lower()
        # Simple pattern: keep extension, wildcard the stem
        pattern = f"*{ext}" if ext else filename

        # Try to find more specific pattern from stem
        # e.g., "invoice_2024_01.pdf" -> "invoice*pdf"
        words = stem.replace("-", "_").split("_")
        if words:
            pattern = f"{words[0]}*{ext}"

        # Check if this correction already exists
        for correction in self._data["corrections"]:
            if (correction["pattern"] == pattern and
                correction["from_category"] == from_category and
                    correction["to_category"] == to_category):
                correction["count"] += 1
                self._save()
                return

        self._data["corrections"].append({
            "pattern": pattern,
            "from_category": from_category,
            "to_category": to_category,
            "count": 1,
        })
        self._save()

    def get_category_adjustments(self, filename: str) -> dict[str, float]:
        """Get confidence adjustments for categories based on learned corrections.

        Returns dict of category -> adjustment (-1.0 to +1.0).
        Positive = boost, negative = penalize.
        """
        adjustments: dict[str, float] = {}

        for correction in self._data["corrections"]:
            if fnmatch.fnmatch(filename.lower(), correction["pattern"]):
                # Penalize the from_category
                from_cat = correction["from_category"]
                weight = min(correction["count"] * 0.1, 0.5)
                adjustments[from_cat] = adjustments.get(from_cat, 0) - weight

                # Boost the to_category
                to_cat = correction["to_category"]
                adjustments[to_cat] = adjustments.get(to_cat, 0) + weight

        # Apply stored confidence overrides
        for cat, override in self._data.get("confidence_overrides", {}).items():
            adjustments[cat] = adjustments.get(cat, 0) + (override - 0.5)

        return adjustments

    def show(self) -> dict[str, Any]:
        """Return the current learning data for display."""
        return dict(self._data)

    def reset(self) -> None:
        """Clear all learning data."""
        self._data = {"corrections": [], "confidence_overrides": {}}
        self._save()
