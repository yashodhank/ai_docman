"""Rich-powered terminal dashboard for docman."""
from __future__ import annotations

import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docman.setup.platform import check_ollama_status, check_exiftool_status, get_python_info


def _gather_dashboard_data(cfg: dict[str, Any]) -> dict[str, Any]:
    """Collect all dashboard data (read-only, no side effects)."""
    docs = Path(cfg["docs_dir"])
    downloads = Path(cfg["downloads_dir"])
    log_dir = docs / cfg["log_dir"]
    index_dir = docs / cfg["index_dir"]
    inbox = docs / cfg["inbox_dir"]
    lock_file = Path.home() / ".docman.lock"

    data: dict[str, Any] = {}

    # --- System Health ---
    ollama = check_ollama_status()
    exiftool = check_exiftool_status()
    python_info = get_python_info()
    index_file = index_dir / "file_index.csv"
    index_age_hours = None
    if index_file.exists():
        age_seconds = time.time() - index_file.stat().st_mtime
        index_age_hours = age_seconds / 3600

    data["system"] = {
        "ollama_running": ollama.get("running", False),
        "ollama_installed": ollama.get("installed", False),
        "ollama_models": ollama.get("models", []),
        "python_version": python_info.get("version", "unknown"),
        "python_venv": python_info.get("is_venv", False),
        "exiftool_installed": exiftool.get("installed", False),
        "index_age_hours": index_age_hours,
        "lock_active": lock_file.exists(),
    }

    # --- Document Stats ---
    inbox_count = 0
    if inbox.exists():
        inbox_count = sum(1 for p in inbox.iterdir()
                         if p.name not in (".DS_Store", "notes.txt", "Downloads_Triage"))

    skip = set(cfg["skip_dirs"])
    unclassified = 0
    if docs.exists():
        unclassified = sum(1 for p in docs.iterdir()
                          if p.name not in skip and not p.name.startswith("."))

    indexed_count = 0
    ext_counts: dict[str, int] = {}
    if index_file.exists():
        try:
            with open(index_file, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    indexed_count += 1
                    ext = row.get("extension", "").lower()
                    if ext:
                        ext_counts[ext] = ext_counts.get(ext, 0) + 1
        except Exception:
            pass

    top_extensions = sorted(ext_counts.items(), key=lambda x: x[1], reverse=True)[:5]

    dup_file = index_dir / "duplicates_report.csv"
    dup_groups = 0
    dup_waste = 0
    if dup_file.exists():
        try:
            with open(dup_file, encoding="utf-8") as f:
                reader = csv.reader(f)
                next(reader, None)
                for row in reader:
                    dup_groups += 1
                    try:
                        canonical = Path(row[1].strip('"'))
                        if canonical.exists():
                            n_dupes = len(row[2].split("|")) if len(row) > 2 else 0
                            dup_waste += canonical.stat().st_size * n_dupes
                    except (IndexError, OSError):
                        pass
        except Exception:
            pass

    # Storage per category
    category_sizes: dict[str, int] = {}
    for org_dir in ["01_Business", "02_Personal", "03_Reference_Library", "99_Archive"]:
        d = docs / org_dir
        if d.exists():
            total = 0
            try:
                for f in d.rglob("*"):
                    if f.is_file():
                        try:
                            total += f.stat().st_size
                        except OSError:
                            pass
            except PermissionError:
                pass
            category_sizes[org_dir] = total

    data["docs"] = {
        "inbox_count": inbox_count,
        "unclassified": unclassified,
        "indexed_count": indexed_count,
        "dup_groups": dup_groups,
        "dup_waste_mb": dup_waste / 1_048_576,
        "top_extensions": top_extensions,
        "category_sizes": category_sizes,
    }

    # --- Recent Operations ---
    jsonl = log_dir / "docman.jsonl"
    recent_ops: list[dict] = []
    ai_count = 0
    rule_count = 0
    if jsonl.exists():
        try:
            all_ops: list[dict] = []
            with open(jsonl, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        all_ops.append(rec)
                        if rec.get("source") == "ai":
                            ai_count += 1
                        elif rec.get("source") == "rules":
                            rule_count += 1
                    except json.JSONDecodeError:
                        pass
            recent_ops = all_ops[-10:]
        except Exception:
            pass

    data["operations"] = {
        "recent": recent_ops,
        "ai_count": ai_count,
        "rule_count": rule_count,
    }

    # --- Alerts ---
    alerts: list[dict[str, str]] = []
    if index_age_hours is not None and index_age_hours > 168:  # 7 days
        alerts.append({"level": "warning", "message": f"Stale index ({index_age_hours:.0f}h old)"})
    elif index_age_hours is None:
        alerts.append({"level": "info", "message": "No index found — run 'docman index'"})

    if inbox_count > 20:
        alerts.append({"level": "warning", "message": f"High inbox count: {inbox_count} items"})

    if dup_groups > 0:
        alerts.append({"level": "info", "message": f"{dup_groups} unresolved duplicate groups ({dup_waste / 1_048_576:.0f} MB)"})

    # Naming violations
    violations = 0
    for org_dir in ["01_Business", "02_Personal"]:
        d = docs / org_dir
        if d.exists():
            try:
                for f in d.rglob("*"):
                    if f.is_file() and " " in f.name and f.name != "notes.txt":
                        violations += 1
            except PermissionError:
                pass
    if violations > 0:
        alerts.append({"level": "info", "message": f"{violations} naming violations (files with spaces)"})

    if not ollama.get("installed", False):
        alerts.append({"level": "warning", "message": "Ollama not installed — AI features unavailable"})
    elif not ollama.get("running", False):
        alerts.append({"level": "info", "message": "Ollama not running — start with 'ollama serve'"})

    data["alerts"] = alerts

    return data


def render_dashboard(cfg: dict[str, Any], as_json: bool = False) -> str | None:
    """Render the dashboard. Returns JSON string if as_json=True, else prints Rich output."""
    data = _gather_dashboard_data(cfg)

    if as_json:
        return json.dumps(data, indent=2, default=str)

    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich.columns import Columns
        from rich.text import Text
    except ImportError:
        # Fallback to plain text
        return _render_plain(data)

    console = Console()

    # --- System Health Panel ---
    sys_data = data["system"]
    sys_table = Table(show_header=False, box=None, padding=(0, 1))
    sys_table.add_column("Key", style="dim")
    sys_table.add_column("Value")

    ollama_status = "[green]running[/]" if sys_data["ollama_running"] else (
        "[yellow]stopped[/]" if sys_data["ollama_installed"] else "[red]not installed[/]")
    sys_table.add_row("Ollama", ollama_status)
    if sys_data["ollama_models"]:
        sys_table.add_row("Models", ", ".join(sys_data["ollama_models"]))
    sys_table.add_row("Python", f"{sys_data['python_version']} {'(venv)' if sys_data['python_venv'] else ''}")
    sys_table.add_row("Exiftool", "[green]yes[/]" if sys_data["exiftool_installed"] else "[dim]no[/]")

    if sys_data["index_age_hours"] is not None:
        age = sys_data["index_age_hours"]
        if age < 24:
            age_str = f"[green]{age:.0f}h ago[/]"
        elif age < 168:
            age_str = f"[yellow]{age / 24:.0f}d ago[/]"
        else:
            age_str = f"[red]{age / 24:.0f}d ago[/]"
        sys_table.add_row("Index", age_str)
    else:
        sys_table.add_row("Index", "[dim]none[/]")

    sys_table.add_row("Lock", "[yellow]active[/]" if sys_data["lock_active"] else "[dim]none[/]")
    sys_panel = Panel(sys_table, title="System Health", border_style="blue")

    # --- Document Stats Panel ---
    doc_data = data["docs"]
    doc_table = Table(show_header=False, box=None, padding=(0, 1))
    doc_table.add_column("Key", style="dim")
    doc_table.add_column("Value")

    inbox_count = doc_data["inbox_count"]
    if inbox_count < 5:
        inbox_str = f"[green]{inbox_count}[/]"
    elif inbox_count < 20:
        inbox_str = f"[yellow]{inbox_count}[/]"
    else:
        inbox_str = f"[red]{inbox_count}[/]"
    doc_table.add_row("Inbox backlog", inbox_str)
    doc_table.add_row("Unclassified", str(doc_data["unclassified"]))
    doc_table.add_row("Total indexed", f"{doc_data['indexed_count']:,}")
    doc_table.add_row("Duplicates", f"{doc_data['dup_groups']} groups ({doc_data['dup_waste_mb']:.0f} MB)")

    if doc_data["top_extensions"]:
        ext_str = "  ".join(f"{ext}({cnt})" for ext, cnt in doc_data["top_extensions"])
        doc_table.add_row("Top types", ext_str)

    for cat, size in doc_data["category_sizes"].items():
        doc_table.add_row(cat, f"{size / 1_048_576:.0f} MB")

    doc_panel = Panel(doc_table, title="Document Stats", border_style="green")

    # --- Recent Operations Panel ---
    ops_data = data["operations"]
    ops_table = Table(box=None, padding=(0, 1))
    ops_table.add_column("Time", style="dim", max_width=20)
    ops_table.add_column("Op", max_width=12)
    ops_table.add_column("Details", max_width=30)
    ops_table.add_column("Status", max_width=8)

    for op in ops_data["recent"]:
        ts = op.get("ts", "")[:19]
        op_name = op.get("op", "?")
        details = op.get("src", op.get("scope", ""))
        if details:
            details = Path(details).name if "/" in str(details) else str(details)
        status = op.get("status", "?")
        style = "green" if status == "ok" else "red"
        ops_table.add_row(ts, op_name, details[:30], f"[{style}]{status}[/]")

    ratio_str = ""
    total = ops_data["ai_count"] + ops_data["rule_count"]
    if total > 0:
        ratio_str = f"\nAI: {ops_data['ai_count']} | Rules: {ops_data['rule_count']}"

    ops_panel = Panel(ops_table, title="Recent Operations" + (f" {ratio_str}" if ratio_str else ""),
                      border_style="cyan")

    # --- Alerts Panel ---
    alerts = data["alerts"]
    if alerts:
        alert_lines = []
        for a in alerts:
            icon = "[yellow]![/]" if a["level"] == "warning" else "[blue]i[/]"
            alert_lines.append(f" {icon} {a['message']}")
        alert_text = "\n".join(alert_lines)
    else:
        alert_text = " [green]No issues detected[/]"

    alerts_panel = Panel(alert_text, title="Alerts", border_style="yellow")

    # Print layout
    console.print()
    console.print(Panel("[bold]DOCMAN DASHBOARD[/bold]", style="bold blue", expand=False))
    console.print(Columns([sys_panel, doc_panel], equal=True, expand=True))
    console.print(Columns([ops_panel, alerts_panel], equal=True, expand=True))
    console.print()
    return None


def run_dashboard(cfg: dict[str, Any], as_json: bool = False,
                  watch: bool = False) -> None:
    """Run the dashboard, optionally in watch mode."""
    if as_json:
        result = render_dashboard(cfg, as_json=True)
        print(result)
        return

    if watch:
        try:
            from rich.live import Live
            from rich.console import Console

            console = Console()
            console.print("[dim]Dashboard refreshing every 5s. Press Ctrl+C to exit.[/]")

            while True:
                render_dashboard(cfg)
                time.sleep(5)
                console.clear()
        except ImportError:
            print("Watch mode requires 'rich'. Install with: pip install rich")
        except KeyboardInterrupt:
            print("\nDashboard stopped.")
    else:
        result = render_dashboard(cfg)
        if result:
            print(result)


def _render_plain(data: dict[str, Any]) -> str:
    """Fallback plain-text rendering when Rich is not available."""
    lines = []
    lines.append("=" * 60)
    lines.append("  DOCMAN DASHBOARD")
    lines.append("=" * 60)

    # System Health
    sys_d = data["system"]
    lines.append("\n--- System Health ---")
    lines.append(f"  Ollama: {'running' if sys_d['ollama_running'] else 'stopped' if sys_d['ollama_installed'] else 'not installed'}")
    lines.append(f"  Python: {sys_d['python_version']} {'(venv)' if sys_d['python_venv'] else ''}")
    lines.append(f"  Exiftool: {'yes' if sys_d['exiftool_installed'] else 'no'}")
    if sys_d["index_age_hours"] is not None:
        lines.append(f"  Index: {sys_d['index_age_hours']:.0f}h old")
    else:
        lines.append("  Index: none")

    # Document Stats
    doc_d = data["docs"]
    lines.append("\n--- Document Stats ---")
    lines.append(f"  Inbox backlog: {doc_d['inbox_count']}")
    lines.append(f"  Unclassified:  {doc_d['unclassified']}")
    lines.append(f"  Total indexed: {doc_d['indexed_count']:,}")
    lines.append(f"  Duplicates:    {doc_d['dup_groups']} groups ({doc_d['dup_waste_mb']:.0f} MB)")

    # Recent Operations
    ops_d = data["operations"]
    lines.append("\n--- Recent Operations ---")
    for op in ops_d["recent"]:
        ts = op.get("ts", "")[:19]
        lines.append(f"  {ts}  {op.get('op', '?'):12s}  {op.get('status', '?')}")

    # Alerts
    lines.append("\n--- Alerts ---")
    for a in data["alerts"]:
        lines.append(f"  [{a['level']}] {a['message']}")
    if not data["alerts"]:
        lines.append("  No issues detected")

    lines.append("")
    return "\n".join(lines)
