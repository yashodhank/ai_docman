"""Semantic search using Ollama embeddings API."""
from __future__ import annotations

import json
import logging
import os
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any

from docman.logging_setup import log_operation

logger = logging.getLogger("docman")

DEFAULT_EMBEDDING_MODEL = "nomic-embed-text"


def _get_embedding(text: str, model: str = DEFAULT_EMBEDDING_MODEL) -> list[float] | None:
    """Get embedding vector from Ollama API."""
    try:
        payload = json.dumps({
            "model": model,
            "prompt": text,
        }).encode("utf-8")
        req = urllib.request.Request(
            "http://localhost:11434/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("embedding")
    except Exception as e:
        logger.debug("Embedding request failed: %s", e)
        return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors using stdlib."""
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _cosine_similarity_np(a, b):
    """Compute cosine similarity using numpy for performance."""
    import numpy as np
    dot = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def _extract_file_text(path: Path) -> str:
    """Extract text from a file for embedding."""
    try:
        from docman.ai.extractor import extract_text
        text = extract_text(path)
        if text:
            return text[:2000]  # Limit for embedding
    except Exception:
        pass
    # Fallback: use filename
    return path.stem.replace("_", " ").replace("-", " ")


def _should_skip_dir(name: str) -> bool:
    """Check if a directory should be skipped during traversal."""
    return name in {"node_modules", ".git", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache"}


def _walk_with_depth(root: Path, max_depth: int = 0) -> list[Path]:
    """Walk a directory tree, optionally limiting depth. max_depth=0 means unlimited."""
    files: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dp = Path(dirpath)
        # Skip junk directories
        dirnames[:] = [d for d in dirnames if not _should_skip_dir(d)]
        # Depth limiting
        if max_depth > 0:
            depth = len(dp.relative_to(root).parts)
            if depth >= max_depth:
                dirnames.clear()
        for fn in filenames:
            if not fn.startswith("."):
                files.append(dp / fn)
    return files


def build_search_index(cfg: dict[str, Any], dry_run: bool = False,
                       verbose: bool = False) -> None:
    """Build or update the semantic search index."""
    docs = Path(cfg["docs_dir"])
    downloads = Path(cfg["downloads_dir"])
    index_dir = docs / cfg["index_dir"]
    search_cfg = cfg.get("search", {})
    model = search_cfg.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
    downloads_max_depth = cfg.get("downloads_max_depth", 3)

    embeddings_map_path = index_dir / "embeddings_map.json"
    embeddings_path = index_dir / "embeddings.npz"

    # Load existing map for incremental updates
    existing_map: dict[str, dict[str, Any]] = {}
    if embeddings_map_path.exists():
        try:
            existing_map = json.loads(embeddings_map_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Collect files to embed from Documents and Downloads
    files_to_embed: list[Path] = []

    # Scan Documents — skip only _System (internal data dir)
    for p in _walk_with_depth(docs):
        try:
            rel = p.relative_to(docs)
            if rel.parts and rel.parts[0] == "_System":
                continue
        except ValueError:
            continue

        path_str = str(p)
        if path_str in existing_map:
            try:
                mtime = p.stat().st_mtime
                if mtime <= existing_map[path_str].get("mtime", 0):
                    continue
            except OSError:
                continue
        files_to_embed.append(p)

    # Scan Downloads with depth limit
    if downloads.exists():
        downloads_exclude = set(cfg.get("downloads_exclude", []))
        for p in _walk_with_depth(downloads, max_depth=downloads_max_depth):
            try:
                rel = p.relative_to(downloads)
                if rel.parts and rel.parts[0] in downloads_exclude:
                    continue
            except ValueError:
                continue

            path_str = str(p)
            if path_str in existing_map:
                try:
                    mtime = p.stat().st_mtime
                    if mtime <= existing_map[path_str].get("mtime", 0):
                        continue
                except OSError:
                    continue
            files_to_embed.append(p)

    if dry_run:
        print(f"[DRY RUN] Would embed {len(files_to_embed)} files (model: {model})")
        print(f"Already indexed: {len(existing_map)} files")
        return

    if not files_to_embed:
        print(f"Search index is up to date ({len(existing_map)} files indexed).")
        return

    print(f"Embedding {len(files_to_embed)} files (model: {model})...")

    # Build embeddings
    new_embeddings: dict[str, list[float]] = {}
    for i, file_path in enumerate(files_to_embed, 1):
        if verbose:
            print(f"  [{i}/{len(files_to_embed)}] {file_path.name}")

        text = _extract_file_text(file_path)
        embedding = _get_embedding(text, model=model)

        if embedding:
            path_str = str(file_path)
            new_embeddings[path_str] = embedding
            try:
                mtime = file_path.stat().st_mtime
            except OSError:
                mtime = 0
            existing_map[path_str] = {
                "mtime": mtime,
                "text_preview": text[:200],
            }

    # Save map
    index_dir.mkdir(parents=True, exist_ok=True)
    embeddings_map_path.write_text(
        json.dumps(existing_map, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # Save embeddings — try numpy, fall back to JSON
    all_paths = list(existing_map.keys())
    try:
        import numpy as np

        # Load existing embeddings
        existing_vectors: dict[str, list[float]] = {}
        if embeddings_path.exists():
            npz = np.load(embeddings_path, allow_pickle=True)
            old_paths = list(npz.get("paths", []))
            old_vectors = npz.get("vectors", np.array([]))
            for path_str, vec in zip(old_paths, old_vectors):
                existing_vectors[path_str] = vec.tolist()

        # Merge
        existing_vectors.update(new_embeddings)

        # Filter to only paths still in the map
        final_paths = [p for p in all_paths if p in existing_vectors]
        final_vectors = [existing_vectors[p] for p in final_paths]

        np.savez_compressed(
            embeddings_path,
            paths=np.array(final_paths),
            vectors=np.array(final_vectors, dtype=np.float32),
        )
    except ImportError:
        # Fall back to JSON storage
        json_path = index_dir / "embeddings.json"

        existing_vectors = {}
        if json_path.exists():
            try:
                existing_vectors = json.loads(json_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass

        existing_vectors.update(new_embeddings)
        # Filter
        final = {k: v for k, v in existing_vectors.items() if k in existing_map}
        json_path.write_text(
            json.dumps(final, ensure_ascii=False),
            encoding="utf-8",
        )

    print(f"Search index updated: {len(new_embeddings)} new embeddings, {len(existing_map)} total files.")
    log_operation(logger, op="search_index", new_embeddings=len(new_embeddings),
                  total_indexed=len(existing_map), model=model,
                  dry_run=False, status="ok")


def run_search(cfg: dict[str, Any], query: str,
               top_k: int | None = None) -> list[dict[str, Any]]:
    """Search files by semantic similarity."""
    docs = Path(cfg["docs_dir"])
    index_dir = docs / cfg["index_dir"]
    search_cfg = cfg.get("search", {})
    model = search_cfg.get("embedding_model", DEFAULT_EMBEDDING_MODEL)
    if top_k is None:
        top_k = search_cfg.get("top_k", 10)

    embeddings_map_path = index_dir / "embeddings_map.json"
    embeddings_path = index_dir / "embeddings.npz"
    embeddings_json_path = index_dir / "embeddings.json"

    # Get query embedding
    query_embedding = _get_embedding(query, model=model)
    if not query_embedding:
        print("Failed to generate query embedding. Is Ollama running with the embedding model?")
        return []

    # Load map
    if not embeddings_map_path.exists():
        print("No search index found. Run 'docman search-index' first.")
        return []

    emap = json.loads(embeddings_map_path.read_text(encoding="utf-8"))

    # Load embeddings — try numpy first
    paths: list[str] = []
    vectors: list[list[float]] = []
    use_np = False

    try:
        import numpy as np
        if embeddings_path.exists():
            npz = np.load(embeddings_path, allow_pickle=True)
            paths = list(npz["paths"])
            vectors_np = npz["vectors"]
            use_np = True
    except ImportError:
        pass

    if not paths and embeddings_json_path.exists():
        try:
            data = json.loads(embeddings_json_path.read_text(encoding="utf-8"))
            paths = list(data.keys())
            vectors = list(data.values())
        except (json.JSONDecodeError, OSError):
            pass

    if not paths:
        print("No embeddings found. Run 'docman search-index' first.")
        return []

    # Compute similarities
    results: list[dict[str, Any]] = []
    if use_np:
        import numpy as np
        query_vec = np.array(query_embedding, dtype=np.float32)
        for i, path_str in enumerate(paths):
            score = _cosine_similarity_np(query_vec, vectors_np[i])
            snippet = emap.get(path_str, {}).get("text_preview", "")
            results.append({"path": path_str, "score": score, "snippet": snippet})
    else:
        for i, path_str in enumerate(paths):
            score = _cosine_similarity(query_embedding, vectors[i])
            snippet = emap.get(path_str, {}).get("text_preview", "")
            results.append({"path": path_str, "score": score, "snippet": snippet})

    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]
