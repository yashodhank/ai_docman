"""High-level file analysis combining extraction + LLM classification."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from docman.ai.extractor import analyze_file, extract_text, get_file_metadata
from docman.ai.llm import (
    classify_with_llm,
    is_ollama_available,
    get_available_models,
    pull_model,
    suggest_filename,
    DEFAULT_MODEL,
)
from docman.rules.registry import RuleRegistry

logger = logging.getLogger("docman")

# Standard categories for classification
CATEGORIES = [
    "01_Business/Admin_Legal",
    "01_Business/Certifications_Compliance",
    "01_Business/Clients",
    "01_Business/Finance_Accounting",
    "01_Business/HR_Team",
    "01_Business/Projects",
    "01_Business/Sales_Marketing",
    "01_Business/Taxation",
    "01_Business/Vendors_Subscriptions",
    "02_Personal/Education",
    "02_Personal/Finance",
    "02_Personal/Health",
    "02_Personal/Home_Family",
    "02_Personal/IDs_Legal",
    "02_Personal/Photos_Docs_Scans",
    "02_Personal/Travel",
    "03_Reference_Library/Manuals_Guides",
    "03_Reference_Library/Receipts_Warranties",
    "03_Reference_Library/Templates",
    "99_Archive",
    "00_Inbox_Documents",
]


class SmartAnalyzer:
    """Combines rule-based and AI-powered classification."""

    def __init__(self, model: str = DEFAULT_MODEL, use_ai: bool = True):
        self.model = model
        self.use_ai = use_ai and is_ollama_available()
        self.registry = RuleRegistry()

        if use_ai and not self.use_ai:
            logger.warning("Ollama not available, falling back to rule-based only")

    def ensure_model(self) -> bool:
        """Ensure the required model is available."""
        if not self.use_ai:
            return False
        models = get_available_models()
        if self.model not in models and self.model.split(":")[0] not in [m.split(":")[0] for m in models]:
            return pull_model(self.model)
        return True

    def analyze(self, path: Path, docs_root: Path) -> dict[str, Any]:
        """Full analysis: metadata, text extraction, rule-based + AI classification."""
        result = {
            "path": str(path),
            "filename": path.name,
            "exists": path.exists(),
        }

        if not path.exists():
            result["error"] = "File not found"
            return result

        # Get metadata and text
        try:
            meta = get_file_metadata(path)
            result.update(meta)
        except Exception as e:
            result["metadata_error"] = str(e)
            meta = {}

        try:
            text = extract_text(path)
            result["text_preview"] = text[:1000] + "..." if len(text) > 1000 else text
            result["text_length"] = len(text)
        except Exception as e:
            result["text_error"] = str(e)
            text = ""

        # Rule-based classification
        rule_proposal = self.registry.classify(path, docs_root)
        result["rule_classification"] = {
            "category": rule_proposal.category,
            "rule": rule_proposal.rule,
            "destination": str(rule_proposal.destination),
        }

        # AI classification (if available and enabled)
        if self.use_ai and text:
            try:
                ai_result = classify_with_llm(
                    filename=path.name,
                    text_preview=text,
                    metadata=meta,
                    categories=CATEGORIES,
                    model=self.model,
                )
                result["ai_classification"] = ai_result
            except Exception as e:
                result["ai_error"] = str(e)

        # Determine final recommendation
        result["recommendation"] = self._determine_recommendation(result)

        return result

    def _determine_recommendation(self, analysis: dict[str, Any]) -> dict[str, Any]:
        """Combine rule-based and AI results for final recommendation."""
        rule = analysis.get("rule_classification", {})
        ai = analysis.get("ai_classification", {})

        # If rule matched something specific (not fallback), use it
        if rule.get("rule") != "fallback":
            return {
                "category": rule["category"],
                "source": "rules",
                "confidence": "high",
                "suggested_name": None,
            }

        # If AI classified with high confidence, use it
        if ai.get("confidence") == "high" and ai.get("category"):
            return {
                "category": ai["category"],
                "source": "ai",
                "confidence": "high",
                "suggested_name": ai.get("suggested_name"),
            }

        # Medium confidence AI
        if ai.get("confidence") == "medium" and ai.get("category"):
            return {
                "category": ai["category"],
                "source": "ai",
                "confidence": "medium",
                "suggested_name": ai.get("suggested_name"),
            }

        # Fallback to inbox
        return {
            "category": "00_Inbox_Documents",
            "source": "fallback",
            "confidence": "low",
            "suggested_name": None,
        }

    def suggest_name(self, path: Path) -> dict[str, Any]:
        """Suggest a better filename based on content analysis."""
        if not self.use_ai:
            return {"suggested_name": path.name, "success": False, "reason": "AI not available"}

        try:
            meta = get_file_metadata(path)
            text = extract_text(path)
            return suggest_filename(path.name, text, meta, model=self.model)
        except Exception as e:
            return {"suggested_name": path.name, "success": False, "reason": str(e)}

    def batch_analyze(self, paths: list[Path], docs_root: Path) -> list[dict[str, Any]]:
        """Analyze multiple files."""
        return [self.analyze(p, docs_root) for p in paths]
