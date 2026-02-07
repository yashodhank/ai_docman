"""Directory content inspection logic for contextual classification."""
from __future__ import annotations

from pathlib import Path
from typing import Any

MEDIA_EXTENSIONS = {".pdf", ".mp4", ".mp3", ".m4a", ".jpg", ".jpeg", ".png", ""}


def check_context_rules(item: Path, rules: list[dict[str, Any]]) -> str | None:
    """Evaluate context rules against a directory. Returns destination or None."""
    if not item.is_dir():
        return None

    for rule in rules:
        signal = rule["signal"]

        if "has_subdirs" in signal:
            required = signal["has_subdirs"]
            if all((item / name).is_dir() for name in required):
                return rule["destination"]

        if "has_children_named" in signal:
            children = {c.name.lower() for c in item.iterdir()}
            if any(name in children for name in signal["has_children_named"]):
                return rule["destination"]

        if "child_keywords" in signal:
            try:
                child_names = " ".join(
                    c.name.lower() for c in item.iterdir() if c.is_file()
                )
            except PermissionError:
                continue
            if any(kw in child_names for kw in signal["child_keywords"]):
                return rule["destination"]

        if "all_media_small" in signal and signal["all_media_small"]:
            try:
                exts = set()
                count = 0
                for f in item.rglob("*"):
                    if f.is_file():
                        exts.add(f.suffix.lower())
                        count += 1
                        if count > 500:
                            break
                if exts.issubset(MEDIA_EXTENSIONS):
                    fc = sum(1 for _ in item.rglob("*"))
                    if fc < 20:
                        return rule["destination"]
            except PermissionError:
                continue

        if "empty_dir" in signal and signal["empty_dir"]:
            try:
                if not any(item.iterdir()):
                    return rule["destination"]
            except PermissionError:
                continue

    return None
