"""Local LLM integration via Ollama for intelligent classification."""
from __future__ import annotations

import json
import logging
import re
import subprocess
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

logger = logging.getLogger("docman")

# Default model - small but capable
DEFAULT_MODEL = "phi3:mini"  # 3.8B params, good for classification
FALLBACK_MODEL = "llama3.2:3b"  # Alternative

_MODEL_NAME_RE = re.compile(r"^[a-zA-Z0-9._:/-]+$")
_MODEL_NAME_MAX_LEN = 100


def _validate_model_name(model: str) -> None:
    """Validate model name to prevent injection attacks."""
    if not model or len(model) > _MODEL_NAME_MAX_LEN:
        raise ValueError(f"Invalid model name length: {len(model) if model else 0}")
    if not _MODEL_NAME_RE.match(model):
        raise ValueError(f"Invalid model name: {model!r}")


def is_ollama_available() -> bool:
    """Check if Ollama is installed and running."""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=5
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_available_models() -> list[str]:
    """List locally available Ollama models."""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode != 0:
            return []
        lines = result.stdout.strip().split("\n")[1:]  # Skip header
        return [line.split()[0] for line in lines if line.strip()]
    except Exception as e:
        logger.debug("Failed to list models: %s", e)
        return []


def pull_model(model: str) -> bool:
    """Pull a model if not available."""
    _validate_model_name(model)
    try:
        print(f"Pulling model {model}... (this may take a few minutes)")
        result = subprocess.run(
            ["ollama", "pull", model],
            capture_output=False, timeout=600
        )
        return result.returncode == 0
    except Exception as e:
        logger.debug("Failed to pull model %s: %s", model, e)
        return False


def query_llm(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 60) -> str:
    """Send a prompt to Ollama via HTTP API and get response."""
    _validate_model_name(model)
    try:
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("response", "").strip()
    except urllib.error.URLError as e:
        logger.debug("Ollama API connection error: %s", e)
        return ""
    except Exception as e:
        logger.debug("Ollama query failed: %s", e)
        return ""


def classify_with_llm(
    filename: str,
    text_preview: str,
    metadata: dict[str, Any],
    categories: list[str],
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Use LLM to classify a document into categories."""
    _validate_model_name(model)
    categories_str = "\n".join(f"- {c}" for c in categories)

    prompt = f"""You are a document classifier. Analyze this file and classify it.

FILENAME: {filename}
FILE TYPE: {metadata.get('mime_type', 'unknown')}
SIZE: {metadata.get('size_bytes', 0)} bytes

TEXT PREVIEW (first ~4000 chars):
{text_preview[:4000] if text_preview else '(no text extracted)'}

AVAILABLE CATEGORIES:
{categories_str}

INSTRUCTIONS:
1. Choose the BEST matching category from the list above
2. Suggest a better filename if the current one is unclear (use underscores, no spaces)
3. Rate your confidence: high, medium, or low

Respond in this exact JSON format:
{{"category": "category_path", "suggested_name": "new_filename.ext", "confidence": "high/medium/low", "reason": "brief explanation"}}

JSON response:"""

    response = query_llm(prompt, model=model, timeout=90)

    # Parse JSON from response
    try:
        # Strip markdown code blocks if present
        clean = response.strip()
        if clean.startswith("```"):
            # Remove ```json or ``` prefix and trailing ```
            lines = clean.split("\n")
            # Skip first line (```json or ```) and last line (```)
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            clean = "\n".join(lines)

        # Find JSON object in response (handles nested braces)
        start = clean.find("{")
        if start != -1:
            depth = 0
            end = start
            for i, c in enumerate(clean[start:], start):
                if c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            json_str = clean[start:end]
            return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.debug("Failed to parse LLM JSON response: %s", e)

    return {
        "category": "",
        "suggested_name": "",
        "confidence": "low",
        "reason": "Failed to parse LLM response",
        "raw_response": response[:500],
    }


def suggest_filename(
    current_name: str,
    text_preview: str,
    metadata: dict[str, Any],
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Use LLM to suggest a better filename based on content."""
    _validate_model_name(model)
    prompt = f"""Suggest a better filename for this document.

CURRENT FILENAME: {current_name}
FILE TYPE: {metadata.get('mime_type', 'unknown')}
CREATED: {metadata.get('created', 'unknown')}

TEXT CONTENT (preview):
{text_preview[:3000] if text_preview else '(no text)'}

RULES:
1. Use underscores instead of spaces
2. Include relevant date if found (YYYY-MM-DD format)
3. Be descriptive but concise (max 60 chars before extension)
4. Keep the original extension
5. Use lowercase

Respond with ONLY the new filename, nothing else:"""

    response = query_llm(prompt, model=model, timeout=30)
    suggested = response.strip().split("\n")[0].strip()

    # Validate suggestion
    if suggested and len(suggested) < 100 and "." in suggested:
        # Clean up
        suggested = re.sub(r"[^\w\-_.]", "_", suggested)
        suggested = re.sub(r"_+", "_", suggested)
        return {"suggested_name": suggested, "success": True}

    return {"suggested_name": current_name, "success": False}


def batch_classify(
    files: list[dict[str, Any]],
    categories: list[str],
    model: str = DEFAULT_MODEL,
) -> list[dict[str, Any]]:
    """Classify multiple files using LLM."""
    results = []
    for f in files:
        result = classify_with_llm(
            filename=f["filename"],
            text_preview=f.get("text_preview", ""),
            metadata=f,
            categories=categories,
            model=model,
        )
        result["original_path"] = f.get("path", "")
        results.append(result)
    return results
