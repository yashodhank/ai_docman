"""Configuration loader with defaults."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

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
    "skip_dirs": [
        "_System", "00_Inbox_Documents", "01_Business", "02_Personal",
        "03_Reference_Library", "90_Quarantine_Duplicates", "99_Archive",
    ],
    "keep_in_inbox": ["Downloads_Triage", "notes.txt"],
    "log_max_bytes": 10_485_760,  # 10 MB
    "log_backup_count": 10,
}

_CONFIG_DIR = Path(__file__).parent


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
    return cfg
