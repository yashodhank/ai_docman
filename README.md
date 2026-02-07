# docman -- Unified Document Manager

An AI-powered document management CLI that organizes, classifies, deduplicates, and audits your personal and business documents. Combines deterministic rule-based classification with local AI (Ollama) for intelligent file organization.

## Features

- **Rule-based classification** -- Tiered regex and context rules from `file_rules.yaml` with priority-ordered matching
- **AI-powered classification** -- Local LLM via Ollama for content-aware document sorting
- **Duplicate detection and dedup** -- SHA-256 hashing with quarantine or delete workflows
- **Daily triage** -- Automated Downloads capture with weekly hygiene reports
- **Terminal dashboard** -- Rich-powered real-time view of system health, document stats, and alerts
- **Audit reports** -- Full operation history, file chain of custody, classification breakdown, and integrity verification
- **Integrity verification** -- SHA-256 checksums to detect file corruption or tampering
- **Undo support** -- Reverse any file move from the structured operation log
- **AI file renaming** -- Content-based filename suggestions using local LLM
- **iCloud awareness** -- Detects iCloud placeholder files and skips them gracefully
- **Process locking** -- Prevents concurrent write operations from conflicting

## Prerequisites

- **Python** 3.10 or later
- **Operating System:** macOS, Linux, or Windows
- **Ollama** (optional, for AI features): https://ollama.ai

## Quick Start

```bash
# 1. Clone the repository
git clone <repo-url> docman
cd docman

# 2. Create a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -e .

# 4. Run automated setup (installs Ollama + AI model)
docman setup

# 5. Index your documents and run your first classification
docman index
docman classify --scope inbox --dry-run
```

## Command Reference

### Core Commands

| Command | Description |
|---------|-------------|
| `docman index` | Build a file index with SHA-256 checksums for all documents |
| `docman duplicates` | Detect duplicate files from the index based on hash matching |
| `docman classify` | Classify loose files using rule-based matching |
| `docman triage` | Daily Downloads capture; copies high-value files to Inbox triage |
| `docman verify` | Verify integrity of moved files against stored SHA-256 checksums |
| `docman dedup` | Quarantine or remove duplicate files |
| `docman status` | Show organization health report |
| `docman undo` | Reverse file moves from the operation log |

### AI Commands

| Command | Description |
|---------|-------------|
| `docman analyze <path>` | Analyze a file or directory with AI classification |
| `docman smart-classify` | Classify files using AI-powered content analysis |
| `docman suggest-rename <path>` | Suggest better filenames based on document content |
| `docman ai-status` | Check Ollama availability and installed models |

### System Commands

| Command | Description |
|---------|-------------|
| `docman setup` | Install all dependencies including Ollama and AI model |
| `docman system-status` | Show comprehensive system status (Python, Ollama, exiftool) |
| `docman dashboard` | Show terminal dashboard with system health, stats, and alerts |
| `docman audit` | Generate audit reports on operations, classification, and integrity |

### Command Details

#### `docman index`

Scans `~/Documents` (configurable), computes SHA-256 checksums for every file, and writes a CSV index to `_System/_Indexes/file_index.csv`. Respects `max_hash_size_mb` and skips iCloud placeholders.

```bash
docman index --dry-run          # Preview without writing
docman index --verbose          # Show each file as it is indexed
```

#### `docman classify`

Applies the tiered rules from `file_rules.yaml` to classify unorganized files. Supports scoping to inbox, downloads, or all loose files.

```bash
docman classify --scope inbox       # Only inbox items
docman classify --scope downloads   # Only Downloads folder
docman classify --scope all         # Everything not in skip_dirs
docman classify --dry-run           # Preview proposed moves
```

#### `docman triage`

Runs the daily Downloads capture workflow: copies high-value files (PDF, DOCX, XLSX, etc.) modified in the last 24 hours into a date-stamped triage directory under the Inbox.

```bash
docman triage                       # Daily capture
docman triage --weekly              # Extended weekly hygiene report
docman triage --dry-run             # Preview without copying
```

#### `docman dedup`

Handles duplicate files found by the index. Can quarantine (move to `90_Quarantine_Duplicates`) or permanently delete duplicates.

```bash
docman dedup --scope downloads --action quarantine
docman dedup --scope all --action delete --dry-run
```

#### `docman undo`

Reverses file moves recorded in the structured JSONL operation log.

```bash
docman undo --last 5                # Undo the last 5 moves
docman undo --since 2025-01-15      # Undo all moves since a date
docman undo --dry-run               # Preview what would be reversed
```

#### `docman analyze`

Uses both rule-based and AI classification to analyze a single file or directory. Outputs category recommendation, confidence level, and optional filename suggestion.

```bash
docman analyze ~/Documents/mystery_file.pdf
docman analyze ~/Downloads/ --model phi3:mini --json
docman analyze report.pdf --no-ai               # Rules only
docman analyze report.pdf --ensure-model         # Auto-pull model
```

#### `docman smart-classify`

Like `classify`, but uses the local LLM to read document contents and make smarter classification decisions. Especially useful for files that do not match any rule pattern.

```bash
docman smart-classify --scope inbox --dry-run
docman smart-classify --scope downloads --limit 10
docman smart-classify --scope inbox --rename      # Apply AI-suggested renames
docman smart-classify --model llama3.2:3b         # Use a different model
```

#### `docman suggest-rename`

Analyzes file content with the LLM and suggests more descriptive filenames following naming conventions (underscores, dates in YYYY-MM-DD, lowercase).

```bash
docman suggest-rename ~/Documents/00_Inbox_Documents/
docman suggest-rename ./report.pdf --model phi3:mini
docman suggest-rename ~/Downloads/ --limit 10
```

#### `docman dashboard`

Displays a Rich-powered terminal dashboard with four panels: System Health, Document Stats, Recent Operations, and Alerts. Falls back to plain text if Rich is not installed.

```bash
docman dashboard                    # One-time display
docman dashboard --watch            # Auto-refresh every 5 seconds
docman dashboard --json             # Output as JSON
```

#### `docman audit`

Generates comprehensive audit reports covering operation history, classification breakdown (rules vs. AI), integrity verification, and duplicate handling.

```bash
docman audit                                     # Full text report
docman audit --format json                       # JSON output
docman audit --format csv --output report.csv    # CSV export
docman audit --since 2025-01-01 --until 2025-02-01
docman audit --op move                           # Filter by operation type
docman audit --file ~/Documents/important.pdf    # File chain of custody
```

### Global Flags

All commands support the following flags:

| Flag | Description |
|------|-------------|
| `--dry-run` | Preview actions without executing them |
| `--verbose` | Enable detailed console output |
| `--quiet` | Suppress all console output |
| `--log-level` | Set log level: DEBUG, INFO, WARNING, ERROR |
| `--config <path>` | Use a custom config file instead of the default |

## Configuration Guide

docman uses a YAML configuration file. The default config is `config.default.yaml` in the package directory. Override it with `--config /path/to/custom.yaml`.

### Configuration Options

```yaml
# Root directories
docs_dir: ~/Documents              # Primary document root
downloads_dir: ~/Downloads         # Downloads folder to monitor

# Internal directories (relative to docs_dir)
log_dir: _System/_Logs             # Operation logs (JSONL + rotating file logs)
index_dir: _System/_Indexes        # File index and duplicate reports
quarantine_dir: 90_Quarantine_Duplicates  # Where duplicates are quarantined
inbox_dir: 00_Inbox_Documents      # Unsorted file inbox

# Indexing controls
max_hash_size_mb: 500              # Skip hashing files larger than this
downloads_max_depth: 3             # Max directory depth in Downloads scan
downloads_exclude:                 # Directories to skip in Downloads
  - Projects

# Directories to skip during classification (already organized)
skip_dirs:
  - _System
  - 00_Inbox_Documents
  - 01_Business
  - 02_Personal
  - 03_Reference_Library
  - 90_Quarantine_Duplicates
  - 99_Archive

# Items to leave in inbox (never classify)
keep_in_inbox:
  - Downloads_Triage
  - notes.txt

# Logging
log_max_bytes: 10485760            # 10 MB per log file
log_backup_count: 10               # Number of rotated log files to keep
```

## AI Features

### Ollama Setup

docman uses Ollama for local AI inference. No data leaves your machine.

```bash
# Install Ollama
brew install ollama          # macOS
curl -fsSL https://ollama.ai/install.sh | sh  # Linux

# Start the service
ollama serve

# Pull the default model
ollama pull phi3:mini
```

Alternatively, run `docman setup` to install everything automatically.

### Model Selection

The default model is `phi3:mini` (3.8B parameters), chosen for its balance of speed and classification accuracy. You can use any Ollama-compatible model:

```bash
docman analyze file.pdf --model llama3.2:3b
docman smart-classify --model mistral:7b
```

Check available models with:

```bash
docman ai-status
```

### How AI Classification Works

1. **Text extraction** -- Content is extracted from PDF, DOCX, XLSX, PPTX, and image files (via OCR)
2. **Rule-based check** -- The file is first classified by `file_rules.yaml` (deterministic, fast)
3. **AI analysis** -- If rules yield a fallback result or for `smart-classify`, the LLM analyzes the text preview
4. **Recommendation** -- The system combines both signals, preferring high-confidence AI results over fallback rules

## Dashboard

The terminal dashboard (`docman dashboard`) provides at-a-glance visibility into:

- **System Health** -- Ollama status, Python version, exiftool availability, index freshness, process lock state
- **Document Stats** -- Inbox backlog, unclassified count, total indexed files, duplicate groups, storage per category, top file types
- **Recent Operations** -- Last 10 operations with timestamps, types, and status indicators
- **Alerts** -- Stale index warnings, high inbox backlog, unresolved duplicates, naming violations, missing Ollama

## Audit Reports

The audit system (`docman audit`) provides:

- **Operation History** -- Total operations, sessions, success/failure counts, breakdown by type
- **File Chain of Custody** -- Trace any file through every operation that touched it, with SHA-256 at each step
- **Classification Audit** -- Rule-based vs. AI counts, fallback rate, confidence distribution, top rules used
- **Integrity Report** -- Results from the last verification run (pass rate, mismatches, missing files)
- **Duplicate Report** -- Groups found, quarantined, deleted, storage recovered

Output formats: text (Rich-formatted), JSON, CSV.

## Directory Structure

```
docman/
├── __init__.py              # Package metadata and version
├── __main__.py              # Entry point for python -m docman
├── cli.py                   # Argparse CLI with all subcommands
├── config.py                # Configuration loader with defaults and validation
├── config.default.yaml      # Default configuration file
├── models.py                # Data models (FileEntry, MoveProposal, DuplicateGroup, etc.)
├── dashboard.py             # Rich-powered terminal dashboard
├── fileops.py               # Safe file operations (move, lock, sha256)
├── icloud.py                # iCloud placeholder detection
├── logging_setup.py         # Structured logging (JSONL + rotating file)
├── status.py                # Organization health report generator
├── ai/
│   ├── __init__.py
│   ├── llm.py               # Ollama LLM integration (query, classify, suggest)
│   ├── analyzer.py           # Smart analysis combining rules + AI
│   └── extractor.py          # Text extraction (PDF, DOCX, XLSX, PPTX, images)
├── core/
│   ├── __init__.py
│   ├── indexer.py            # File indexing with SHA-256 checksums
│   ├── duplicates.py         # Duplicate detection from index
│   ├── classifier.py         # Rule-based file classification
│   ├── triage.py             # Daily Downloads capture and weekly hygiene
│   ├── dedup.py              # Duplicate quarantine and removal
│   ├── mover.py              # Safe file move operations
│   ├── undo.py               # Undo operations from log
│   ├── verifier.py           # Integrity verification
│   └── audit.py              # Audit report generation
├── rules/
│   ├── __init__.py
│   ├── registry.py           # Rule loading, regex compilation, classify()
│   └── file_rules.yaml       # All classification rules (tiers, dir_map, context)
├── setup/
│   ├── __init__.py
│   ├── installer.py          # Automated dependency and Ollama installer
│   └── platform.py           # Platform detection and status checks
├── requirements.txt          # Python dependencies
└── pyproject.toml            # Python packaging configuration
```

## Architecture

```
                          ┌────────────────────────┐
                          │      CLI (cli.py)       │
                          │  argparse subcommands   │
                          └───────────┬────────────┘
                                      │
              ┌───────────────────────┼───────────────────────┐
              │                       │                       │
   ┌──────────▼──────────┐ ┌─────────▼─────────┐ ┌──────────▼──────────┐
   │     Core Module      │ │    AI Module       │ │   System Module     │
   │                      │ │                    │ │                     │
   │  indexer.py          │ │  llm.py (Ollama)   │ │  dashboard.py       │
   │  duplicates.py       │ │  analyzer.py       │ │  status.py          │
   │  classifier.py       │ │  extractor.py      │ │  setup/installer.py │
   │  triage.py           │ │                    │ │  setup/platform.py  │
   │  dedup.py            │ └────────┬───────────┘ └─────────────────────┘
   │  mover.py            │          │
   │  undo.py             │          │
   │  verifier.py         │   ┌──────▼──────┐
   │  audit.py            │   │   Ollama     │
   └──────────┬───────────┘   │  (local AI)  │
              │               └─────────────┘
   ┌──────────▼──────────┐
   │   Rules Engine       │
   │                      │
   │  registry.py         │
   │  file_rules.yaml     │
   │  context_rules       │
   └──────────┬───────────┘
              │
   ┌──────────▼──────────┐
   │   Infrastructure     │
   │                      │
   │  config.py           │
   │  fileops.py          │
   │  logging_setup.py    │
   │  models.py           │
   │  icloud.py           │
   └──────────────────────┘
```

## Troubleshooting

### "Another docman instance is already running"

docman uses a lock file (`~/.docman.lock`) to prevent concurrent write operations. If a previous run crashed:

```bash
rm ~/.docman.lock
```

### Ollama not available

```bash
# Check status
docman ai-status

# Start the service
ollama serve

# If not installed
docman setup
```

### Index is stale

The dashboard will alert you when the index is older than 7 days. Rebuild it:

```bash
docman index
```

### Files classified to fallback (Inbox)

Files landing in `00_Inbox_Documents` were not matched by any rule or AI. Options:

1. Add a pattern to `file_rules.yaml` for recurring file types
2. Use `docman smart-classify --scope inbox` to apply AI classification
3. Use `docman analyze <file>` to inspect why classification failed

### Permission errors

docman validates that configured paths are within your home directory and refuses to operate on system directories (`/`, `/etc`, `/usr`, etc.).

## Security Considerations

- **Local AI only** -- All AI inference runs locally via Ollama. No data is sent to external services.
- **Path validation** -- Configured directories are validated against a forbidden paths list to prevent accidental operations on system directories.
- **Model name validation** -- Ollama model names are validated with a strict regex to prevent command injection.
- **Process locking** -- Write operations acquire an exclusive lock to prevent data races.
- **SHA-256 integrity** -- All file moves are checksummed for verifiable chain of custody.
- **Structured audit log** -- Every operation is recorded in a JSONL log with timestamps, session IDs, and checksums.
- **No destructive defaults** -- `dedup` defaults to quarantine (not delete), and all destructive commands support `--dry-run`.

## License

MIT License. See [LICENSE](LICENSE) for details.
