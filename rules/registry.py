"""Single source of truth — loads, compiles, and exposes classification rules."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from docman.models import MoveProposal
from docman.rules.context_rules import check_context_rules


class RuleRegistry:
    """Loads file_rules.yaml once, precompiles all regex, provides classify()."""

    def __init__(self, rules_path: Path | None = None):
        if rules_path is None:
            rules_path = Path(__file__).parent / "file_rules.yaml"
        with open(rules_path, encoding="utf-8") as f:
            self._raw = yaml.safe_load(f)

        self.dir_map: dict[str, str] = self._raw.get("directory_mappings", {})
        self.dotfiles_dest: str = self._raw.get("dotfiles", "99_Archive")
        self.fallback_dest: str = self._raw.get("fallback", "00_Inbox_Documents")
        self.context_rules: list[dict[str, Any]] = self._raw.get("context_rules", [])
        self.spiritual_file_keywords: list[str] = self._raw.get("spiritual_file_keywords", [])
        self.spiritual_pdf_dest: str = self._raw.get("spiritual_pdf_dest", "02_Personal/Education")
        self.csv_finance_dest: str = self._raw.get("csv_finance_dest", "01_Business/Finance_Accounting")

        # Precompile tier patterns sorted by priority
        tiers = self._raw.get("tiers", [])
        tiers.sort(key=lambda t: t.get("priority", 9999))
        self._compiled_tiers: list[tuple[str, str, list[re.Pattern]]] = []
        for tier in tiers:
            compiled = [re.compile(p) for p in tier.get("patterns", [])]
            self._compiled_tiers.append((tier["name"], tier["destination"], compiled))

        # Build discovered categories from all rule destinations
        self._all_categories: set[str] = set()
        self._all_categories.update(self.dir_map.values())
        for _, dest, _ in self._compiled_tiers:
            self._all_categories.add(dest)
        for ctx in self.context_rules:
            if ctx.get("destination"):
                self._all_categories.add(ctx["destination"])
        self._all_categories.add(self.dotfiles_dest)
        self._all_categories.add(self.fallback_dest)
        self._all_categories.add(self.spiritual_pdf_dest)
        self._all_categories.add(self.csv_finance_dest)

    @property
    def all_categories(self) -> list[str]:
        """All unique destination categories discovered from rules, sorted."""
        return sorted(self._all_categories)

    @property
    def top_level_dirs(self) -> list[str]:
        """Top-level directory names (e.g. '01_Business') derived from rules."""
        return sorted({cat.split("/")[0] for cat in self._all_categories})

    @property
    def organized_dirs(self) -> list[str]:
        """Top-level dirs that represent organized content (excludes inbox/quarantine)."""
        return sorted(
            d for d in self.top_level_dirs
            if d != self.fallback_dest.split("/")[0]
        )

    def classify(self, path: Path, docs_root: Path) -> MoveProposal:
        """Classify a file/directory and return a MoveProposal."""
        name = path.name
        is_dir = path.is_dir()

        # 1) Dotfile check
        if name.startswith("."):
            dest = docs_root / self.dotfiles_dest
            return MoveProposal(source=path, destination=dest / name,
                                category=self.dotfiles_dest, rule="dotfile")

        # 2) DIR_MAP exact match (dirs only)
        if is_dir and name in self.dir_map:
            cat = self.dir_map[name]
            dest = docs_root / cat
            return MoveProposal(source=path, destination=dest / name,
                                category=cat, rule="dir_map")

        # 3) Tier patterns (first match wins)
        for tier_name, destination, patterns in self._compiled_tiers:
            for pat in patterns:
                if pat.search(name):
                    dest = docs_root / destination
                    return MoveProposal(source=path, destination=dest / name,
                                        category=destination, rule=tier_name)

        # 4) Context rules (directories only)
        if is_dir:
            ctx_dest = check_context_rules(path, self.context_rules)
            if ctx_dest:
                dest = docs_root / ctx_dest
                return MoveProposal(source=path, destination=dest / name,
                                    category=ctx_dest, rule="context")

        # 4b) Spiritual PDF file keyword check
        if not is_dir and path.suffix.lower() == ".pdf":
            name_lower = name.lower()
            if any(kw in name_lower for kw in self.spiritual_file_keywords):
                cat = self.spiritual_pdf_dest
                dest = docs_root / cat
                return MoveProposal(source=path, destination=dest / name,
                                    category=cat, rule="spiritual_pdf")

        # 4c) CSV price/export check
        if not is_dir and path.suffix.lower() == ".csv":
            name_lower = name.lower()
            if "price" in name_lower or "export" in name_lower:
                cat = self.csv_finance_dest
                dest = docs_root / cat
                return MoveProposal(source=path, destination=dest / name,
                                    category=cat, rule="csv_finance")

        # 5) Fallback
        dest = docs_root / self.fallback_dest
        return MoveProposal(source=path, destination=dest / name,
                            category=self.fallback_dest, rule="fallback")
