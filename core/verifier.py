"""Post-move verification — replaces verify_moves.sh + dry_run.sh."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from docman.fileops import sha256_file
from docman.logging_setup import log_operation
from docman.models import VerificationResult

logger = logging.getLogger("docman")

SKIP_SHA = {"directory", "skipped_too_large", "error", "icloud_placeholder"}


def run_verify(cfg: dict[str, Any], dry_run: bool = False, verbose: bool = False) -> None:
    """Verify integrity of moved files by reading the JSONL log."""
    docs = Path(cfg["docs_dir"])
    log_dir = docs / cfg["log_dir"]
    jsonl = log_dir / "docman.jsonl"

    if not jsonl.exists():
        print("No log file found. Run some operations first.")
        return

    results: list[VerificationResult] = []
    total = verified = failed = skipped = 0

    with open(jsonl, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if rec.get("op") not in ("move", "quarantine"):
                continue

            total += 1
            dst = Path(rec.get("dst", ""))
            expected = rec.get("sha256", "")

            if not dst.exists():
                results.append(VerificationResult(dst, expected, "", "missing"))
                failed += 1
                continue

            if expected in SKIP_SHA:
                results.append(VerificationResult(dst, expected, expected, "skipped"))
                verified += 1
                skipped += 1
                continue

            actual = sha256_file(dst)
            if actual == expected:
                results.append(VerificationResult(dst, expected, actual, "ok"))
                verified += 1
            else:
                results.append(VerificationResult(dst, expected, actual, "mismatch"))
                failed += 1

    # Print report
    rate = (verified * 100 // total) if total > 0 else 0
    print("=" * 42)
    print("  VERIFICATION REPORT")
    print("=" * 42)
    print(f"\nTotal entries:    {total}")
    print(f"Verified:         {verified}")
    print(f"Failed:           {failed}")
    print(f"Skipped SHA:      {skipped}")
    print(f"Pass rate:        {rate}%")

    missing = [r for r in results if r.status == "missing"]
    mismatches = [r for r in results if r.status == "mismatch"]

    if missing:
        print(f"\nMISSING FILES ({len(missing)}):")
        for r in missing:
            print(f"  {r.path}")

    if mismatches:
        print(f"\nSHA-256 MISMATCHES ({len(mismatches)}):")
        for r in mismatches:
            print(f"  {r.path}")
            print(f"    Expected: {r.expected_sha}")
            print(f"    Actual:   {r.actual_sha}")

    if failed == 0:
        print("\nSTATUS: ALL VERIFIED")
    else:
        print("\nSTATUS: ISSUES FOUND")

    log_operation(logger, op="verify", total=total, verified=verified,
                  failed=failed, dry_run=dry_run, status="ok" if failed == 0 else "issues")
