"""Configuration loader with defaults."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("docman")

_DEFAULTS = {
    "docs_dir": str(Path.home() / "Documents"),
    "downloads_dir": str(Path.home() / "Downloads"),
    "log_dir": "_System/_Logs",
    "index_dir": "_System/_Indexes",
    "quarantine_dir": "90_Quarantine_Duplicates",
    "inbox_dir": "00_Inbox_Documents",
    "max_hash_size_mb": 500,
    "downloads_max_depth": 3,
    "downloads_exclude": ["Projects"],
    "skip_dirs": [],  # populated dynamically from file_rules.yaml
    "keep_in_inbox": ["Downloads_Triage", "notes.txt"],
    "log_max_bytes": 10_485_760,  # 10 MB
    "log_backup_count": 10,
}

_CONFIG_DIR = Path(__file__).parent

_FORBIDDEN_PATHS = {"/", "/etc", "/usr", "/bin", "/var", "/sbin", "/lib",
                    "/System", "/Library", "C:\\Windows", "C:\\Program Files"}


def _validate_paths(cfg: dict[str, Any]) -> None:
    """Validate that configured paths are not system-critical directories."""
    home = str(Path.home())
    for key in ("docs_dir", "downloads_dir"):
        path = cfg.get(key, "")
        resolved = str(Path(path).resolve())
        if resolved in _FORBIDDEN_PATHS:
            raise ValueError(
                f"Config error: {key}={path!r} points to a system-critical path. "
                f"Please use a user directory instead."
            )
        if not resolved.startswith(home):
            logger.warning(
                "%s=%r is outside your home directory (%s). "
                "This may be intentional but could be risky.",
                key, path, home,
            )


def _derive_skip_dirs(cfg: dict[str, Any]) -> list[str]:
    """Derive skip_dirs dynamically from file_rules.yaml destinations."""
    try:
        from docman.rules.registry import RuleRegistry
        registry = RuleRegistry()
        dirs = set(registry.top_level_dirs)
    except Exception:
        logger.debug("Could not load rules for skip_dirs derivation, using fallback")
        dirs = set()
    # Always include system/infrastructure dirs
    dirs.add("_System")
    dirs.add(cfg.get("inbox_dir", "00_Inbox_Documents").split("/")[0])
    dirs.add(cfg.get("quarantine_dir", "90_Quarantine_Duplicates").split("/")[0])
    return sorted(dirs)


def load_config(config_path: Path | None = None) -> dict[str, Any]:
    """Load config from YAML, falling back to defaults."""
    cfg = dict(_DEFAULTS)
    yaml_path = config_path or _CONFIG_DIR / "config.default.yaml"
    if yaml_path.exists():
        with open(yaml_path) as f:
            user = yaml.safe_load(f) or {}
        cfg.update(user)
    # Resolve paths
    cfg["docs_dir"] = str(Path(cfg["docs_dir"]).expanduser())
    cfg["downloads_dir"] = str(Path(cfg["downloads_dir"]).expanduser())
    # Validate paths are safe
    _validate_paths(cfg)
    # Derive skip_dirs from rules if not explicitly set in user config
    if not cfg["skip_dirs"]:
        cfg["skip_dirs"] = _derive_skip_dirs(cfg)
    return cfg
