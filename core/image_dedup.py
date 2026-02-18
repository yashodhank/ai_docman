"""Perceptual image hashing for finding visually similar images."""
from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from docman.logging_setup import log_operation

logger = logging.getLogger("docman")

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif", ".webp"}


def _dhash(image_path: Path, hash_size: int = 8) -> int | None:
    """Compute difference hash (dHash) for an image. Returns integer hash or None on error."""
    try:
        from PIL import Image
    except ImportError:
        logger.warning("Pillow not installed — cannot compute image hashes")
        return None

    try:
        import warnings
        with warnings.catch_warnings():
            # Suppress PIL warnings (Palette/Transparency UserWarning, DecompressionBombWarning)
            warnings.simplefilter("ignore", UserWarning)
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(image_path) as img:
                img = img.convert("L").resize((hash_size + 1, hash_size))
            pixels = list(img.getdata())

            # Compare adjacent pixels horizontally
            hash_val = 0
            for row in range(hash_size):
                for col in range(hash_size):
                    offset = row * (hash_size + 1) + col
                    if pixels[offset] < pixels[offset + 1]:
                        hash_val |= 1 << (row * hash_size + col)
            return hash_val
    except Exception as e:
        logger.debug("Failed to hash image %s: %s", image_path, e)
        return None


def _hamming_distance(hash1: int, hash2: int) -> int:
    """Compute Hamming distance between two integer hashes."""
    return bin(hash1 ^ hash2).count("1")


def run_image_dedup(cfg: dict[str, Any], dry_run: bool = False,
                    verbose: bool = False, threshold: int = 10) -> Path:
    """Find visually similar images using perceptual hashing."""
    docs = Path(cfg["docs_dir"])
    downloads = Path(cfg["downloads_dir"])
    index_dir = docs / cfg["index_dir"]
    output = index_dir / "similar_images_report.csv"

    # Collect image files
    images: list[Path] = []
    for root_dir in [docs, downloads]:
        if not root_dir.exists():
            continue
        for p in root_dir.rglob("*"):
            if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
                images.append(p)

    if verbose:
        print(f"Computing perceptual hashes for {len(images)} images...")

    # Compute dHash for each image
    hashes: list[tuple[Path, int]] = []
    for img_path in images:
        h = _dhash(img_path)
        if h is not None:
            hashes.append((img_path, h))

    if verbose:
        print(f"Hashed {len(hashes)} images successfully.")

    # Find similar pairs
    similar: list[tuple[Path, Path, int]] = []
    for i, (p1, h1) in enumerate(hashes):
        for p2, h2 in hashes[i + 1:]:
            dist = _hamming_distance(h1, h2)
            if dist <= threshold:
                similar.append((p1, p2, dist))

    similar.sort(key=lambda x: x[2])

    if dry_run:
        print(f"[DRY RUN] Would find {len(similar)} similar image pairs.")
        for p1, p2, dist in similar[:20]:
            print(f"  [distance={dist}] {p1.name} <-> {p2.name}")
        return output

    index_dir.mkdir(parents=True, exist_ok=True)
    with open(output, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["image_a", "image_b", "hamming_distance"])
        for p1, p2, dist in similar:
            writer.writerow([str(p1), str(p2), dist])

    print(f"Image dedup done. {len(similar)} similar pairs found. Output: {output}")
    log_operation(logger, op="image_dedup", pairs_found=len(similar),
                  images_scanned=len(hashes), output=str(output),
                  dry_run=False, status="ok")
    return output
