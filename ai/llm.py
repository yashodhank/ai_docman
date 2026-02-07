"""Local LLM integration via Ollama for intelligent classification."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

# Default model - small but capable
DEFAULT_MODEL = "phi3:mini"  # 3.8B params, good for classification
FALLBACK_MODEL = "llama3.2:3b"  # Alternative


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
    except Exception:
        return []


def pull_model(model: str) -> bool:
    """Pull a model if not available."""
    try:
        print(f"Pulling model {model}... (this may take a few minutes)")
        result = subprocess.run(
            ["ollama", "pull", model],
            capture_output=False, timeout=600
        )
        return result.returncode == 0
    except Exception:
        return False


def query_llm(prompt: str, model: str = DEFAULT_MODEL, timeout: int = 60) -> str:
    """Send a prompt to Ollama and get response."""
    try:
        result = subprocess.run(
            ["ollama", "run", model, prompt],
            capture_output=True, text=True, timeout=timeout
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return ""
    except subprocess.TimeoutExpired:
        return ""
    except Exception:
        return ""


def classify_with_llm(
    filename: str,
    text_preview: str,
    metadata: dict[str, Any],
    categories: list[str],
    model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """Use LLM to classify a document into categories."""
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
    except json.JSONDecodeError:
        pass

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
