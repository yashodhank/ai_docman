"""Audit report generation for docman operations."""
from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


def _load_operations(log_dir: Path, since: str | None = None,
                     until: str | None = None,
                     op_type: str | None = None) -> list[dict]:
    """Load and filter operations from JSONL log."""
    jsonl = log_dir / "docman.jsonl"
    if not jsonl.exists():
        return []

    ops: list[dict] = []
    with open(jsonl, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            ts = rec.get("ts", "")
            if since and ts < since:
                continue
            if until and ts > until:
                continue
            if op_type and rec.get("op") != op_type:
                continue
            ops.append(rec)

    return ops


def generate_operation_history(ops: list[dict]) -> dict[str, Any]:
    """Generate operation history report."""
    if not ops:
        return {"total": 0, "operations": [], "by_type": {}, "success": 0, "failures": 0}

    by_type: dict[str, int] = Counter()
    sessions: set[str] = set()
    success = 0
    failures = 0

    for op in ops:
        by_type[op.get("op", "unknown")] += 1
        if op.get("session_id"):
            sessions.add(op["session_id"])
        if op.get("status") == "ok":
            success += 1
        elif op.get("status") == "error":
            failures += 1

    return {
        "total": len(ops),
        "unique_sessions": len(sessions),
        "by_type": dict(by_type),
        "success": success,
        "failures": failures,
        "first_ts": ops[0].get("ts", "") if ops else "",
        "last_ts": ops[-1].get("ts", "") if ops else "",
        "operations": ops[-50:],  # Last 50 for detail
    }


def generate_file_chain(ops: list[dict], file_path: str) -> dict[str, Any]:
    """Trace a specific file through all operations."""
    file_path_resolved = str(Path(file_path).resolve())
    chain: list[dict] = []

    for op in ops:
        src = op.get("src", "")
        dst = op.get("dst", "")
        if file_path_resolved in (src, dst) or file_path in (src, dst):
            chain.append({
                "timestamp": op.get("ts", ""),
                "operation": op.get("op", ""),
                "source": src,
                "destination": dst,
                "sha256": op.get("sha256", ""),
                "status": op.get("status", ""),
                "session_id": op.get("session_id", ""),
            })

    return {
        "file": file_path,
        "operations": len(chain),
        "chain": chain,
    }


def generate_classification_audit(ops: list[dict]) -> dict[str, Any]:
    """Generate classification audit report."""
    rule_count = 0
    ai_count = 0
    confidence_dist = Counter()
    rules_used = Counter()
    fallback_count = 0
    total_classified = 0

    for op in ops:
        if op.get("op") not in ("move", "smart_move"):
            continue
        total_classified += 1

        source = op.get("source", "")
        if source == "ai":
            ai_count += 1
            confidence_dist[op.get("confidence", "unknown")] += 1
        elif source == "rules":
            rule_count += 1
        else:
            # Classify by rule presence
            rule = op.get("rule", "")
            if rule == "fallback":
                fallback_count += 1
            elif rule:
                rule_count += 1
                rules_used[rule] += 1

        rule = op.get("rule", "")
        if rule and rule != "fallback":
            rules_used[rule] += 1

    top_rules = sorted(rules_used.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "total_classified": total_classified,
        "rule_based": rule_count,
        "ai_based": ai_count,
        "fallback_count": fallback_count,
        "confidence_distribution": dict(confidence_dist),
        "top_rules": top_rules,
        "fallback_rate": (fallback_count / total_classified * 100) if total_classified > 0 else 0,
    }


def generate_integrity_report(cfg: dict[str, Any]) -> dict[str, Any]:
    """Generate integrity verification report from last verify run."""
    docs = Path(cfg["docs_dir"])
    log_dir = docs / cfg["log_dir"]
    jsonl = log_dir / "docman.jsonl"

    if not jsonl.exists():
        return {"available": False}

    verify_ops: list[dict] = []
    with open(jsonl, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("op") == "verify":
                    verify_ops.append(rec)
            except json.JSONDecodeError:
                pass

    if not verify_ops:
        return {"available": False, "message": "No verification runs found"}

    last = verify_ops[-1]
    return {
        "available": True,
        "last_run": last.get("ts", ""),
        "total_checked": last.get("total_checked", 0),
        "passed": last.get("passed", 0),
        "mismatches": last.get("mismatches", 0),
        "missing": last.get("missing", 0),
        "pass_rate": last.get("pass_rate", 0),
    }


def generate_duplicate_report(cfg: dict[str, Any], ops: list[dict]) -> dict[str, Any]:
    """Generate duplicate handling report."""
    docs = Path(cfg["docs_dir"])
    index_dir = docs / cfg["index_dir"]
    dup_file = index_dir / "duplicates_report.csv"

    total_found = 0
    if dup_file.exists():
        try:
            with open(dup_file, encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)
                for _ in reader:
                    total_found += 1
        except Exception:
            pass

    quarantine_count = 0
    delete_count = 0
    storage_recovered = 0
    for op in ops:
        if op.get("op") == "dedup":
            if op.get("action") == "quarantine":
                quarantine_count += 1
            elif op.get("action") == "delete":
                delete_count += 1
                size = op.get("size", 0)
                if isinstance(size, (int, float)):
                    storage_recovered += size

    return {
        "total_groups_found": total_found,
        "quarantined": quarantine_count,
        "deleted": delete_count,
        "storage_recovered_mb": storage_recovered / 1_048_576 if storage_recovered else 0,
    }


def generate_summary(ops: list[dict]) -> dict[str, Any]:
    """Generate summary statistics."""
    if not ops:
        return {"total_operations": 0}

    files_processed = set()
    errors = 0
    for op in ops:
        if op.get("src"):
            files_processed.add(op["src"])
        if op.get("status") == "error":
            errors += 1

    return {
        "total_operations": len(ops),
        "unique_files_processed": len(files_processed),
        "errors_encountered": errors,
    }


def generate_full_report(cfg: dict[str, Any], since: str | None = None,
                         until: str | None = None, op_type: str | None = None,
                         file_path: str | None = None) -> dict[str, Any]:
    """Generate the complete audit report."""
    docs = Path(cfg["docs_dir"])
    log_dir = docs / cfg["log_dir"]

    ops = _load_operations(log_dir, since=since, until=until, op_type=op_type)

    report: dict[str, Any] = {
        "generated_at": datetime.now().isoformat(),
        "period": {"since": since, "until": until},
    }

    report["operation_history"] = generate_operation_history(ops)

    if file_path:
        all_ops = _load_operations(log_dir)
        report["file_chain"] = generate_file_chain(all_ops, file_path)

    report["classification_audit"] = generate_classification_audit(ops)
    report["integrity"] = generate_integrity_report(cfg)
    report["duplicates"] = generate_duplicate_report(cfg, ops)
    report["summary"] = generate_summary(ops)

    return report


def render_text_report(report: dict[str, Any]) -> str:
    """Render audit report as formatted text."""
    lines = []
    lines.append("=" * 60)
    lines.append("  DOCMAN AUDIT REPORT")
    lines.append("=" * 60)
    lines.append(f"  Generated: {report['generated_at']}")
    period = report.get("period", {})
    if period.get("since") or period.get("until"):
        lines.append(f"  Period: {period.get('since', 'beginning')} to {period.get('until', 'now')}")
    lines.append("")

    # Operation History
    hist = report.get("operation_history", {})
    lines.append("--- Operation History ---")
    lines.append(f"  Total operations:  {hist.get('total', 0)}")
    lines.append(f"  Unique sessions:   {hist.get('unique_sessions', 0)}")
    lines.append(f"  Successes:         {hist.get('success', 0)}")
    lines.append(f"  Failures:          {hist.get('failures', 0)}")
    by_type = hist.get("by_type", {})
    if by_type:
        lines.append("  By type:")
        for op_name, count in sorted(by_type.items()):
            lines.append(f"    {op_name}: {count}")
    lines.append("")

    # File Chain
    if "file_chain" in report:
        chain = report["file_chain"]
        lines.append(f"--- File Chain of Custody: {chain.get('file', '')} ---")
        for step in chain.get("chain", []):
            lines.append(f"  [{step.get('timestamp', '')}] {step.get('operation', '')}")
            lines.append(f"    {step.get('source', '')} -> {step.get('destination', '')}")
            lines.append(f"    SHA256: {step.get('sha256', 'N/A')}")
        lines.append("")

    # Classification Audit
    clf = report.get("classification_audit", {})
    lines.append("--- Classification Audit ---")
    lines.append(f"  Total classified:  {clf.get('total_classified', 0)}")
    lines.append(f"  Rule-based:        {clf.get('rule_based', 0)}")
    lines.append(f"  AI-based:          {clf.get('ai_based', 0)}")
    lines.append(f"  Fallback rate:     {clf.get('fallback_rate', 0):.1f}%")
    conf = clf.get("confidence_distribution", {})
    if conf:
        lines.append(f"  AI confidence:     high={conf.get('high', 0)} med={conf.get('medium', 0)} low={conf.get('low', 0)}")
    top_rules = clf.get("top_rules", [])
    if top_rules:
        lines.append("  Top rules:")
        for rule, count in top_rules:
            lines.append(f"    {rule}: {count}")
    lines.append("")

    # Integrity
    integ = report.get("integrity", {})
    lines.append("--- Integrity Report ---")
    if integ.get("available"):
        lines.append(f"  Last run:     {integ.get('last_run', 'N/A')}")
        lines.append(f"  Checked:      {integ.get('total_checked', 0)}")
        lines.append(f"  Passed:       {integ.get('passed', 0)}")
        lines.append(f"  Mismatches:   {integ.get('mismatches', 0)}")
        lines.append(f"  Missing:      {integ.get('missing', 0)}")
        lines.append(f"  Pass rate:    {integ.get('pass_rate', 0)}%")
    else:
        lines.append(f"  {integ.get('message', 'No data')}")
    lines.append("")

    # Duplicates
    dups = report.get("duplicates", {})
    lines.append("--- Duplicate Handling ---")
    lines.append(f"  Groups found:      {dups.get('total_groups_found', 0)}")
    lines.append(f"  Quarantined:       {dups.get('quarantined', 0)}")
    lines.append(f"  Deleted:           {dups.get('deleted', 0)}")
    lines.append(f"  Storage recovered: {dups.get('storage_recovered_mb', 0):.1f} MB")
    lines.append("")

    # Summary
    summary = report.get("summary", {})
    lines.append("--- Summary ---")
    lines.append(f"  Total operations:      {summary.get('total_operations', 0)}")
    lines.append(f"  Unique files:          {summary.get('unique_files_processed', 0)}")
    lines.append(f"  Errors:                {summary.get('errors_encountered', 0)}")
    lines.append("")

    return "\n".join(lines)


def render_csv_report(report: dict[str, Any]) -> str:
    """Render audit report as CSV (operation history)."""
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "session_id", "operation", "source", "destination",
                     "sha256", "status", "category", "rule"])

    ops = report.get("operation_history", {}).get("operations", [])
    for op in ops:
        writer.writerow([
            op.get("ts", ""),
            op.get("session_id", ""),
            op.get("op", ""),
            op.get("src", ""),
            op.get("dst", ""),
            op.get("sha256", ""),
            op.get("status", ""),
            op.get("category", ""),
            op.get("rule", ""),
        ])

    return output.getvalue()


def run_audit(cfg: dict[str, Any], format: str = "text",
              since: str | None = None, until: str | None = None,
              op_type: str | None = None, file_path: str | None = None,
              output_file: str | None = None) -> None:
    """Generate and output an audit report."""
    report = generate_full_report(cfg, since=since, until=until,
                                  op_type=op_type, file_path=file_path)

    if format == "json":
        content = json.dumps(report, indent=2, default=str)
    elif format == "csv":
        content = render_csv_report(report)
    else:
        try:
            from rich.console import Console
            from rich.panel import Panel
            console = Console()
            text_content = render_text_report(report)
            if output_file:
                content = text_content
            else:
                console.print(Panel(text_content, title="DOCMAN AUDIT", border_style="blue"))
                return
        except ImportError:
            content = render_text_report(report)

    if output_file:
        Path(output_file).write_text(content, encoding="utf-8")
        print(f"Report saved to: {output_file}")
    else:
        print(content)
