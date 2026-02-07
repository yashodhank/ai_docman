"""Cross-platform detection and setup utilities."""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple


class PlatformInfo(NamedTuple):
    os_type: str  # "darwin", "linux", "windows"
    os_name: str  # "macOS", "Ubuntu", "Debian", "Windows"
    os_version: str
    arch: str  # "arm64", "x86_64", "amd64"
    is_apple_silicon: bool
    home_dir: Path
    shell: str


def detect_platform() -> PlatformInfo:
    """Detect the current platform and return info."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    version = platform.version()

    # Normalize OS type
    if system == "darwin":
        os_type = "darwin"
        os_name = "macOS"
        os_version = platform.mac_ver()[0]
        is_apple_silicon = machine in ("arm64", "aarch64")
    elif system == "linux":
        os_type = "linux"
        # Detect distro
        os_name, os_version = _detect_linux_distro()
        is_apple_silicon = False
    elif system == "windows":
        os_type = "windows"
        os_name = "Windows"
        os_version = platform.win32_ver()[0]
        is_apple_silicon = False
    else:
        os_type = system
        os_name = system
        os_version = version
        is_apple_silicon = False

    # Normalize arch
    if machine in ("x86_64", "amd64"):
        arch = "x86_64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = machine

    # Detect shell
    shell = os.environ.get("SHELL", "")
    if not shell and os_type == "windows":
        shell = "powershell"

    return PlatformInfo(
        os_type=os_type,
        os_name=os_name,
        os_version=os_version,
        arch=arch,
        is_apple_silicon=is_apple_silicon,
        home_dir=Path.home(),
        shell=shell,
    )


def _detect_linux_distro() -> tuple[str, str]:
    """Detect Linux distribution."""
    try:
        with open("/etc/os-release") as f:
            info = {}
            for line in f:
                if "=" in line:
                    key, value = line.strip().split("=", 1)
                    info[key] = value.strip('"')
        name = info.get("NAME", "Linux")
        version = info.get("VERSION_ID", "")
        return name, version
    except FileNotFoundError:
        return "Linux", ""


def check_command_exists(cmd: str) -> bool:
    """Check if a command exists in PATH."""
    return shutil.which(cmd) is not None


def run_command(cmd: list[str], timeout: int = 30, capture: bool = True) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except FileNotFoundError:
        return -1, "", f"Command not found: {cmd[0]}"
    except Exception as e:
        return -1, "", str(e)


def get_python_info() -> dict:
    """Get Python environment info."""
    return {
        "version": platform.python_version(),
        "executable": sys.executable,
        "prefix": sys.prefix,
        "is_venv": hasattr(sys, "real_prefix") or (
            hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
        ),
    }


def check_ollama_status() -> dict:
    """Check Ollama installation and service status."""
    result = {
        "installed": False,
        "path": None,
        "running": False,
        "version": None,
        "models": [],
    }

    # Check if installed
    ollama_path = shutil.which("ollama")
    if ollama_path:
        result["installed"] = True
        result["path"] = ollama_path

        # Get version
        code, stdout, _ = run_command(["ollama", "--version"])
        if code == 0:
            result["version"] = stdout.strip()

        # Check if running
        code, stdout, _ = run_command(["ollama", "list"], timeout=5)
        if code == 0:
            result["running"] = True
            # Parse models
            lines = stdout.strip().split("\n")[1:]  # Skip header
            result["models"] = [line.split()[0] for line in lines if line.strip()]

    return result


def check_exiftool_status() -> dict:
    """Check exiftool installation."""
    result = {"installed": False, "path": None, "version": None}

    path = shutil.which("exiftool")
    if path:
        result["installed"] = True
        result["path"] = path
        code, stdout, _ = run_command(["exiftool", "-ver"])
        if code == 0:
            result["version"] = stdout.strip()

    return result


def check_all_dependencies() -> dict:
    """Check all external dependencies."""
    platform_info = detect_platform()

    return {
        "platform": platform_info._asdict(),
        "python": get_python_info(),
        "ollama": check_ollama_status(),
        "exiftool": check_exiftool_status(),
        "git": {"installed": check_command_exists("git")},
        "curl": {"installed": check_command_exists("curl")},
    }


def print_status_report():
    """Print a formatted status report."""
    deps = check_all_dependencies()

    print("=" * 60)
    print("  DOCMAN SYSTEM STATUS")
    print("=" * 60)

    # Platform
    p = deps["platform"]
    print(f"\nPlatform: {p['os_name']} {p['os_version']} ({p['arch']})")
    if p["is_apple_silicon"]:
        print("  Apple Silicon: Yes (MLX optimizations available)")

    # Python
    py = deps["python"]
    print(f"\nPython: {py['version']}")
    print(f"  Executable: {py['executable']}")
    print(f"  Virtual env: {'Yes' if py['is_venv'] else 'No'}")

    # Ollama
    o = deps["ollama"]
    print(f"\nOllama:")
    if o["installed"]:
        print(f"  Installed: Yes ({o['path']})")
        print(f"  Version: {o['version'] or 'unknown'}")
        print(f"  Running: {'Yes' if o['running'] else 'No'}")
        if o["models"]:
            print(f"  Models: {', '.join(o['models'])}")
        else:
            print("  Models: None installed")
    else:
        print("  Installed: No")

    # Exiftool
    e = deps["exiftool"]
    print(f"\nExiftool:")
    if e["installed"]:
        print(f"  Installed: Yes (v{e['version']})")
    else:
        print("  Installed: No (optional - for metadata extraction)")

    print()
