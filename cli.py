"""CLI — argparse subcommands for docman."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from docman.config import load_config
from docman.logging_setup import setup_logging


def _add_global_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--dry-run", action="store_true", help="Preview without executing")
    parser.add_argument("--verbose", action="store_true", help="Verbose console output")
    parser.add_argument("--quiet", action="store_true", help="Suppress console output")
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--config", type=Path, default=None, help="Custom config file")


def _setup(args: argparse.Namespace) -> dict[str, Any]:
    cfg = load_config(args.config)
    docs = Path(cfg["docs_dir"])
    log_dir = docs / cfg["log_dir"]
    setup_logging(log_dir, log_level=args.log_level,
                  max_bytes=cfg.get("log_max_bytes", 10_485_760),
                  backup_count=cfg.get("log_backup_count", 10))
    return cfg


def cmd_index(args: argparse.Namespace) -> None:
    cfg = _setup(args)
    from docman.core.indexer import run_index
    run_index(cfg, dry_run=args.dry_run, verbose=args.verbose)


def cmd_duplicates(args: argparse.Namespace) -> None:
    cfg = _setup(args)
    from docman.core.duplicates import run_duplicates
    run_duplicates(cfg, dry_run=args.dry_run, verbose=args.verbose)


def cmd_classify(args: argparse.Namespace) -> None:
    cfg = _setup(args)
    from docman.core.classifier import run_classify
    run_classify(cfg, scope=args.scope, dry_run=args.dry_run, verbose=args.verbose)


def cmd_triage(args: argparse.Namespace) -> None:
    cfg = _setup(args)
    from docman.core.triage import run_triage
    run_triage(cfg, weekly=args.weekly, dry_run=args.dry_run, verbose=args.verbose)


def cmd_verify(args: argparse.Namespace) -> None:
    cfg = _setup(args)
    from docman.core.verifier import run_verify
    run_verify(cfg, dry_run=args.dry_run, verbose=args.verbose)


def cmd_dedup(args: argparse.Namespace) -> None:
    cfg = _setup(args)
    _run_dedup(cfg, scope=args.scope, action=args.action,
               dry_run=args.dry_run, verbose=args.verbose)


def _run_dedup(cfg: dict[str, Any], scope: str = "downloads",
               action: str = "quarantine", dry_run: bool = False,
               verbose: bool = False) -> None:
    """Quarantine or remove duplicates."""
    import csv
    import logging
    from docman.fileops import safe_dest, atomic_move
    from docman.logging_setup import log_operation

    logger = logging.getLogger("docman")
    docs = Path(cfg["docs_dir"]).resolve()
    downloads = Path(cfg["downloads_dir"]).resolve()
    index_dir = docs / cfg["index_dir"]
    quarantine = docs / cfg["quarantine_dir"]
    dupes_file = index_dir / "duplicates_report.csv"

    if not dupes_file.exists():
        print("No duplicates report found. Run 'docman duplicates' first.")
        return

    to_process: list[tuple[Path, str]] = []
    with open(dupes_file, encoding="utf-8") as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        for row in reader:
            if len(row) < 3:
                continue
            dup_paths = [p.strip() for p in row[2].split("|") if p.strip()]
            for dp in dup_paths:
                p = Path(dp).resolve()
                if not p.exists():
                    continue
                # Validate path is within expected directories
                if not (p.is_relative_to(docs) or p.is_relative_to(downloads)):
                    logger.warning("Skipping path outside managed dirs: %s", p)
                    continue
                if scope == "downloads" and not p.is_relative_to(downloads):
                    continue
                to_process.append((p, row[0]))

    if not to_process:
        print("No duplicates to process.")
        return

    # Confirm before delete
    if action == "delete" and not dry_run:
        answer = input(f"Delete {len(to_process)} files? [y/N]: ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    processed = 0
    for p, sha in to_process:
        if dry_run:
            print(f"  [{action}] {p}")
            processed += 1
            continue
        if action == "quarantine":
            dest = safe_dest(p, quarantine)
            atomic_move(p, dest)
            log_operation(logger, op="dedup", action="quarantine",
                          src=str(p), dst=str(dest), sha256=sha,
                          dry_run=False, status="ok")
        elif action == "delete":
            p.unlink()
            log_operation(logger, op="dedup", action="delete",
                          src=str(p), sha256=sha,
                          dry_run=False, status="ok")
        processed += 1

    tag = " [DRY RUN]" if dry_run else ""
    print(f"Dedup complete: {processed} files {action}d{tag}")


def cmd_status(args: argparse.Namespace) -> None:
    cfg = _setup(args)
    from docman.status import generate_report
    print(generate_report(cfg))


def cmd_undo(args: argparse.Namespace) -> None:
    cfg = _setup(args)
    _run_undo(cfg, last=args.last, since=args.since,
              dry_run=args.dry_run, verbose=args.verbose)


def cmd_analyze(args: argparse.Namespace) -> None:
    """Analyze a file using AI for classification suggestions."""
    cfg = _setup(args)
    from docman.ai.analyzer import SmartAnalyzer

    analyzer = SmartAnalyzer(model=args.model, use_ai=not args.no_ai)

    if args.ensure_model:
        if not analyzer.ensure_model():
            print(f"Failed to pull model {args.model}")
            return

    path = Path(args.path).expanduser().resolve()
    docs = Path(cfg["docs_dir"])

    result = analyzer.analyze(path, docs)

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        print(f"\n{'=' * 60}")
        print(f"File: {result['filename']}")
        print(f"{'=' * 60}")
        print(f"Size: {result.get('size_bytes', 0):,} bytes")
        print(f"Type: {result.get('mime_type', 'unknown')}")
        print(f"Modified: {result.get('modified', 'unknown')}")

        if result.get("text_length", 0) > 0:
            print(f"\nText extracted: {result['text_length']} chars")
            preview = result.get("text_preview", "")[:200]
            if preview:
                print(f"Preview: {preview}...")

        rule = result.get("rule_classification", {})
        print(f"\nRule-based: {rule.get('category', 'unknown')} [{rule.get('rule', '')}]")

        ai = result.get("ai_classification", {})
        if ai:
            print(f"AI-based:   {ai.get('category', 'unknown')} [{ai.get('confidence', '')}]")
            if ai.get("suggested_name"):
                print(f"Suggested name: {ai['suggested_name']}")
            if ai.get("reason"):
                print(f"Reason: {ai['reason']}")

        rec = result.get("recommendation", {})
        print(f"\nRECOMMENDATION: {rec.get('category', 'unknown')}")
        print(f"Source: {rec.get('source', 'unknown')}, Confidence: {rec.get('confidence', 'unknown')}")


def cmd_smart_classify(args: argparse.Namespace) -> None:
    """Classify files using AI-powered analysis."""
    cfg = _setup(args)
    from docman.ai.analyzer import SmartAnalyzer
    from docman.fileops import safe_dest, atomic_move, sha256_file
    from docman.logging_setup import log_operation
    import logging

    logger = logging.getLogger("docman")
    analyzer = SmartAnalyzer(model=args.model, use_ai=True)

    if not analyzer.use_ai:
        print("AI not available. Install Ollama: https://ollama.ai")
        print("Falling back to rule-based classification...")
        from docman.core.classifier import run_classify
        run_classify(cfg, scope=args.scope, dry_run=args.dry_run, verbose=args.verbose)
        return

    if not analyzer.ensure_model():
        print(f"Failed to ensure model {args.model} is available")
        return

    docs = Path(cfg["docs_dir"])
    downloads = Path(cfg["downloads_dir"])
    skip = set(cfg["skip_dirs"])

    # Collect items
    items: list[Path] = []
    if args.scope == "inbox":
        inbox = docs / cfg["inbox_dir"]
        if inbox.exists():
            items = [p for p in inbox.iterdir()
                     if p.name not in cfg.get("keep_in_inbox", []) and p.name != ".DS_Store"]
    elif args.scope == "downloads":
        if downloads.exists():
            items = [p for p in downloads.iterdir()
                     if p.name not in cfg.get("downloads_exclude", []) and p.name != ".DS_Store"]
    else:
        items = [p for p in docs.iterdir() if p.name not in skip and p.name != ".DS_Store"]

    # Limit for AI processing
    if args.limit:
        items = items[:args.limit]

    print(f"Analyzing {len(items)} items with AI...")
    moves = []

    for i, item in enumerate(items, 1):
        if args.verbose:
            print(f"[{i}/{len(items)}] Analyzing: {item.name}")

        result = analyzer.analyze(item, docs)
        rec = result.get("recommendation", {})

        if rec.get("category") and rec["category"] != "00_Inbox_Documents":
            dest_dir = docs / rec["category"]
            suggested = rec.get("suggested_name")
            if suggested and args.rename:
                dest = safe_dest(Path(suggested), dest_dir)
            else:
                dest = safe_dest(item, dest_dir)
            moves.append((item, dest, rec["category"], rec.get("source", ""), rec.get("confidence", "")))

    if args.dry_run:
        print(f"\n=== DRY RUN: {len(moves)} items to move ===\n")
        for src, dst, cat, source, conf in moves:
            print(f"  {src.name}")
            print(f"    -> {cat}/ [{source}, {conf}]")
            if dst.name != src.name:
                print(f"    renamed: {dst.name}")
            print()
    else:
        for src, dst, cat, source, conf in moves:
            sha = sha256_file(src) if src.is_file() else "directory"
            size = src.stat().st_size if src.is_file() and src.exists() else 0
            atomic_move(src, dst)
            log_operation(logger, op="smart_move", src=str(src), dst=str(dst),
                          sha256=sha, size=size, category=cat,
                          source=source, confidence=conf,
                          dry_run=False, status="ok")
            if args.verbose:
                print(f"  {src.name} -> {cat}/")

        print(f"\n=== Done: {len(moves)} items moved ===")


def cmd_suggest_rename(args: argparse.Namespace) -> None:
    """Suggest better filenames based on content analysis."""
    cfg = _setup(args)
    from docman.ai.analyzer import SmartAnalyzer

    analyzer = SmartAnalyzer(model=args.model, use_ai=True)

    if not analyzer.use_ai:
        print("AI not available. Install Ollama: https://ollama.ai")
        return

    path = Path(args.path).expanduser().resolve()

    if path.is_dir():
        files = list(path.iterdir())[:args.limit] if args.limit else list(path.iterdir())
    else:
        files = [path]

    print(f"Analyzing {len(files)} files for rename suggestions...\n")

    for f in files:
        if not f.is_file() or f.name.startswith("."):
            continue
        result = analyzer.suggest_name(f)
        if result.get("success") and result["suggested_name"] != f.name:
            print(f"  {f.name}")
            print(f"    -> {result['suggested_name']}")
            print()


def cmd_ai_status(args: argparse.Namespace) -> None:
    """Check AI/Ollama availability and models."""
    from docman.ai.llm import is_ollama_available, get_available_models, DEFAULT_MODEL

    print("AI Status")
    print("-" * 40)

    if is_ollama_available():
        print("Ollama: AVAILABLE")
        models = get_available_models()
        print(f"Models installed: {len(models)}")
        for m in models:
            marker = " (default)" if m == DEFAULT_MODEL or m.startswith(DEFAULT_MODEL.split(":")[0]) else ""
            print(f"  - {m}{marker}")

        if not models:
            print(f"\nNo models installed. Run: ollama pull {DEFAULT_MODEL}")
    else:
        print("Ollama: NOT AVAILABLE")
        print("\nTo install Ollama:")
        print("  brew install ollama")
        print("  ollama serve  # Start the service")
        print(f"  ollama pull {DEFAULT_MODEL}  # Download the model")


def cmd_setup(args: argparse.Namespace) -> None:
    """Install all dependencies including Ollama and AI model."""
    from docman.setup.installer import Installer

    installer = Installer(verbose=not args.quiet)
    results = installer.setup_all(model=args.model)

    success = all([
        results["python_deps"],
        results["ollama_install"],
        results["ollama_service"],
        results["model_pull"],
    ])

    sys.exit(0 if success else 1)


def cmd_system_status(args: argparse.Namespace) -> None:
    """Show comprehensive system status."""
    from docman.setup.platform import print_status_report
    print_status_report()


def _run_undo(cfg: dict[str, Any], last: int | None = None,
              since: str | None = None, dry_run: bool = False,
              verbose: bool = False) -> None:
    """Reverse moves from JSONL log."""
    import logging
    from docman.fileops import sha256_file, atomic_move
    from docman.logging_setup import log_operation

    logger = logging.getLogger("docman")
    docs = Path(cfg["docs_dir"]).resolve()
    downloads = Path(cfg["downloads_dir"]).resolve()
    log_dir = docs / cfg["log_dir"]
    jsonl = log_dir / "docman.jsonl"

    if not jsonl.exists():
        print("No log file found.")
        return

    # Validate --last
    if last is not None and last <= 0:
        print("Error: --last must be a positive integer.")
        sys.exit(1)

    # Validate --since
    if since:
        try:
            datetime.fromisoformat(since)
        except ValueError:
            print(f"Error: --since must be ISO format (e.g. 2024-01-15T10:00:00). Got: {since}")
            sys.exit(1)

    # Collect move records
    moves: list[dict] = []
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
            if not rec.get("src") or not rec.get("dst"):
                continue
            moves.append(rec)

    # Filter
    if since:
        moves = [m for m in moves if m.get("ts", "") >= since]
    if last:
        moves = moves[-last:]

    # Reverse in reverse order
    moves.reverse()

    undone = 0
    for rec in moves:
        src = Path(rec["dst"]).resolve()   # current location
        dst = Path(rec["src"]).resolve()   # original location
        expected_sha = rec.get("sha256", "")

        # Validate paths are within expected directories
        if not (src.is_relative_to(docs) or src.is_relative_to(downloads)):
            logger.warning("Skipping undo — source outside managed dirs: %s", src)
            continue
        if not (dst.is_relative_to(docs) or dst.is_relative_to(downloads)):
            logger.warning("Skipping undo — destination outside managed dirs: %s", dst)
            continue

        if not src.exists():
            print(f"  SKIP (missing): {src}")
            continue

        # Verify SHA before undo
        if expected_sha and expected_sha not in ("directory", "skipped_too_large", "error"):
            actual = sha256_file(src)
            if actual != expected_sha:
                print(f"  SKIP (SHA mismatch): {src}")
                continue

        if dry_run:
            print(f"  [undo] {src} -> {dst}")
        else:
            atomic_move(src, dst)
            log_operation(logger, op="undo", src=str(src), dst=str(dst),
                          sha256=expected_sha, dry_run=False, status="ok")
            if verbose:
                print(f"  Undone: {src.name} -> {dst.parent}")
        undone += 1

    tag = " [DRY RUN]" if dry_run else ""
    print(f"\nUndo complete: {undone} moves reversed{tag}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="docman",
                                     description="Unified Document Manager")
    sub = parser.add_subparsers(dest="command", required=True)

    # index
    p = sub.add_parser("index", help="Build file index with SHA-256 checksums")
    _add_global_flags(p)
    p.set_defaults(func=cmd_index)

    # duplicates
    p = sub.add_parser("duplicates", help="Detect duplicate files from index")
    _add_global_flags(p)
    p.set_defaults(func=cmd_duplicates)

    # classify
    p = sub.add_parser("classify", help="Classify loose files")
    p.add_argument("--scope", choices=["all", "inbox", "downloads"], default="all")
    _add_global_flags(p)
    p.set_defaults(func=cmd_classify)

    # triage
    p = sub.add_parser("triage", help="Daily Downloads capture")
    p.add_argument("--weekly", action="store_true", help="Extended weekly hygiene")
    _add_global_flags(p)
    p.set_defaults(func=cmd_triage)

    # verify
    p = sub.add_parser("verify", help="Verify integrity of moved files")
    _add_global_flags(p)
    p.set_defaults(func=cmd_verify)

    # dedup
    p = sub.add_parser("dedup", help="Quarantine/remove duplicates")
    p.add_argument("--scope", choices=["downloads", "all"], default="downloads")
    p.add_argument("--action", choices=["quarantine", "delete"], default="quarantine")
    _add_global_flags(p)
    p.set_defaults(func=cmd_dedup)

    # status
    p = sub.add_parser("status", help="Show organization health report")
    _add_global_flags(p)
    p.set_defaults(func=cmd_status)

    # undo
    p = sub.add_parser("undo", help="Reverse moves from log")
    p.add_argument("--last", type=int, help="Undo last N moves")
    p.add_argument("--since", type=str, help="Undo all since timestamp (ISO format)")
    _add_global_flags(p)
    p.set_defaults(func=cmd_undo)

    # === AI Commands ===

    # analyze
    p = sub.add_parser("analyze", help="Analyze a file with AI classification")
    p.add_argument("path", help="File or directory to analyze")
    p.add_argument("--model", default="phi3:mini", help="Ollama model to use")
    p.add_argument("--no-ai", action="store_true", help="Disable AI, use rules only")
    p.add_argument("--ensure-model", action="store_true", help="Pull model if not available")
    p.add_argument("--json", action="store_true", help="Output as JSON")
    _add_global_flags(p)
    p.set_defaults(func=cmd_analyze)

    # smart-classify
    p = sub.add_parser("smart-classify", help="Classify using AI analysis")
    p.add_argument("--scope", choices=["all", "inbox", "downloads"], default="inbox")
    p.add_argument("--model", default="phi3:mini", help="Ollama model to use")
    p.add_argument("--limit", type=int, help="Limit number of files to process")
    p.add_argument("--rename", action="store_true", help="Apply AI-suggested renames")
    _add_global_flags(p)
    p.set_defaults(func=cmd_smart_classify)

    # suggest-rename
    p = sub.add_parser("suggest-rename", help="Suggest better filenames using AI")
    p.add_argument("path", help="File or directory to analyze")
    p.add_argument("--model", default="phi3:mini", help="Ollama model to use")
    p.add_argument("--limit", type=int, default=20, help="Max files to analyze")
    _add_global_flags(p)
    p.set_defaults(func=cmd_suggest_rename)

    # ai-status
    p = sub.add_parser("ai-status", help="Check AI/Ollama availability")
    _add_global_flags(p)
    p.set_defaults(func=cmd_ai_status)

    # === Setup Commands ===

    # setup
    p = sub.add_parser("setup", help="Install all dependencies (Ollama, AI model, etc.)")
    p.add_argument("--model", default="phi3:mini", help="AI model to install")
    _add_global_flags(p)
    p.set_defaults(func=cmd_setup)

    # system-status
    p = sub.add_parser("system-status", help="Show comprehensive system status")
    _add_global_flags(p)
    p.set_defaults(func=cmd_system_status)

    args = parser.parse_args()
    args.func(args)
