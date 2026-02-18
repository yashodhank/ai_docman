"""High-level file analysis combining extraction + LLM classification."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from docman.ai.extractor import analyze_file, extract_text, get_file_metadata
from docman.ai.llm import (
    classify_with_llm,
    classify_image_with_llm,
    is_ollama_available,
    get_available_models,
    pull_model,
    suggest_filename,
    DEFAULT_MODEL,
    DEFAULT_VISION_MODEL,
)
from docman.rules.registry import RuleRegistry

logger = logging.getLogger("docman")


def _build_categories() -> list[str]:
    """Build the CATEGORIES list dynamically from file_rules.yaml."""
    try:
        registry = RuleRegistry()
        return registry.all_categories
    except Exception:
        logger.debug("Failed to load rules for category discovery, using empty list")
        return []


# Categories are derived from file_rules.yaml destinations at import time
CATEGORIES = _build_categories()


class SmartAnalyzer:
    """Combines rule-based and AI-powered classification."""

    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif", ".webp"}

    def __init__(self, model: str = DEFAULT_MODEL, use_ai: bool = True,
                 vision_model: str = DEFAULT_VISION_MODEL, vision_enabled: bool = True):
        self.model = model
        self.vision_model = vision_model
        self.vision_enabled = vision_enabled
        self.use_ai = use_ai and is_ollama_available()
        self.registry = RuleRegistry()
        # Refresh CATEGORIES from this instance's registry
        global CATEGORIES
        CATEGORIES = self.registry.all_categories

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
        is_image = path.suffix.lower() in self.IMAGE_EXTENSIONS
        if self.use_ai and is_image and self.vision_enabled:
            # Use vision model for images
            try:
                ai_result = classify_image_with_llm(
                    image_path=path,
                    filename=path.name,
                    categories=CATEGORIES,
                    model=self.vision_model,
                )
                ai_result["source_model"] = "vision"
                result["ai_classification"] = ai_result
            except Exception as e:
                result["ai_error"] = str(e)
        elif self.use_ai and text:
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
        filename = analysis.get("filename", "")

        # Consult adaptive learning for adjustments
        adjustments = self._get_learning_adjustments(filename)

        # If rule matched something specific (not fallback), use it
        if rule.get("rule") != "fallback":
            category = rule["category"]
            # Check if learning suggests a different category
            if adjustments.get(category, 0) < -0.3:
                # Strong negative signal — check if there's a better option
                best_alt = max(adjustments, key=adjustments.get, default=None) if adjustments else None
                if best_alt and adjustments[best_alt] > 0.3 and best_alt in CATEGORIES:
                    return {
                        "category": best_alt,
                        "source": "learned",
                        "confidence": "high",
                        "confidence_score": 0.85,
                        "suggested_name": None,
                    }
            return {
                "category": category,
                "source": "rules",
                "confidence": "high",
                "confidence_score": 0.95,
                "suggested_name": None,
            }

        # Validate AI category against allowlist
        ai_category = ai.get("category", "")
        if ai_category and ai_category not in CATEGORIES:
            logger.warning("AI returned invalid category %r, ignoring", ai_category)
            ai_category = ""

        # Sanitize suggested filename — strip directory components
        ai_suggested = ai.get("suggested_name")
        if ai_suggested:
            ai_suggested = Path(ai_suggested).name

        # Apply learning adjustments to AI confidence
        confidence_map = {"high": 0.9, "medium": 0.6, "low": 0.3}
        ai_conf_score = confidence_map.get(ai.get("confidence", "low"), 0.3)
        if ai_category and ai_category in adjustments:
            ai_conf_score = max(0.0, min(1.0, ai_conf_score + adjustments[ai_category]))

        # Map adjusted score back to label
        if ai_conf_score >= 0.7:
            ai_conf_label = "high"
        elif ai_conf_score >= 0.4:
            ai_conf_label = "medium"
        else:
            ai_conf_label = "low"

        # If AI classified with high confidence, use it
        if ai_conf_label == "high" and ai_category:
            return {
                "category": ai_category,
                "source": "ai",
                "confidence": "high",
                "confidence_score": round(ai_conf_score, 2),
                "suggested_name": ai_suggested,
            }

        # Medium confidence AI
        if ai_conf_label == "medium" and ai_category:
            return {
                "category": ai_category,
                "source": "ai",
                "confidence": "medium",
                "confidence_score": round(ai_conf_score, 2),
                "suggested_name": ai_suggested,
            }

        # Check if learning alone suggests a category
        if adjustments:
            best_learned = max(adjustments, key=adjustments.get)
            if adjustments[best_learned] > 0.2 and best_learned in CATEGORIES:
                return {
                    "category": best_learned,
                    "source": "learned",
                    "confidence": "medium",
                    "confidence_score": round(min(adjustments[best_learned], 0.8), 2),
                    "suggested_name": None,
                }

        # Fallback to inbox (use registry's fallback destination)
        return {
            "category": self.registry.fallback_dest,
            "source": "fallback",
            "confidence": "low",
            "confidence_score": 0.1,
            "suggested_name": None,
        }

    def _get_learning_adjustments(self, filename: str) -> dict[str, float]:
        """Get confidence adjustments from learning DB."""
        try:
            from docman.ai.learning import LearningDB
            index_dir = Path.home() / "Documents" / "_System" / "_Indexes"
            db = LearningDB(index_dir / "learning.json")
            return db.get_category_adjustments(filename)
        except Exception:
            return {}

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
