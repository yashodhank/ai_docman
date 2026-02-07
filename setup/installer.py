"""Cross-platform installer for docman dependencies."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from docman.setup.platform import (
    detect_platform,
    check_command_exists,
    run_command,
    check_ollama_status,
)


class Installer:
    """Handles installation of dependencies across platforms."""

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.platform = detect_platform()

    def log(self, msg: str):
        if self.verbose:
            print(msg)

    def install_ollama(self) -> bool:
        """Install Ollama based on platform."""
        status = check_ollama_status()
        if status["installed"]:
            self.log(f"Ollama already installed at {status['path']}")
            return True

        self.log(f"Installing Ollama for {self.platform.os_name}...")

        if self.platform.os_type == "darwin":
            return self._install_ollama_macos()
        elif self.platform.os_type == "linux":
            return self._install_ollama_linux()
        elif self.platform.os_type == "windows":
            return self._install_ollama_windows()
        else:
            self.log(f"Unsupported platform: {self.platform.os_type}")
            return False

    def _install_ollama_macos(self) -> bool:
        """Install Ollama on macOS."""
        # Try Homebrew first
        if check_command_exists("brew"):
            self.log("Installing via Homebrew...")
            code, _, err = run_command(["brew", "install", "ollama"], timeout=300)
            if code == 0:
                self.log("Ollama installed successfully via Homebrew")
                return True
            self.log(f"Homebrew install failed: {err}")

        # Fallback to curl install
        self.log("Installing via official script...")
        code, out, err = run_command(
            ["curl", "-fsSL", "https://ollama.ai/install.sh"],
            timeout=30,
        )
        if code != 0:
            self.log(f"Failed to download installer: {err}")
            return False

        # Run the install script
        code, _, err = run_command(["sh", "-c", out], timeout=300)
        if code == 0:
            self.log("Ollama installed successfully")
            return True

        self.log(f"Install failed: {err}")
        return False

    def _install_ollama_linux(self) -> bool:
        """Install Ollama on Linux (Ubuntu/Debian)."""
        self.log("Installing via official script...")

        # Use the official install script
        code, _, err = run_command(
            ["sh", "-c", "curl -fsSL https://ollama.ai/install.sh | sh"],
            timeout=300,
        )

        if code == 0:
            self.log("Ollama installed successfully")
            return True

        self.log(f"Install failed: {err}")
        self.log("\nManual installation instructions:")
        self.log("  curl -fsSL https://ollama.ai/install.sh | sh")
        return False

    def _install_ollama_windows(self) -> bool:
        """Install Ollama on Windows."""
        self.log("Windows installation requires manual steps:")
        self.log("  1. Download from: https://ollama.ai/download/windows")
        self.log("  2. Run the installer")
        self.log("  3. Restart your terminal")
        self.log("\nAlternatively, use winget:")
        self.log("  winget install Ollama.Ollama")

        # Try winget if available
        if check_command_exists("winget"):
            self.log("\nAttempting winget install...")
            code, _, err = run_command(
                ["winget", "install", "Ollama.Ollama", "-e"],
                timeout=300,
            )
            if code == 0:
                self.log("Ollama installed successfully via winget")
                return True

        return False

    def start_ollama_service(self) -> bool:
        """Start the Ollama service."""
        status = check_ollama_status()
        if status["running"]:
            self.log("Ollama service already running")
            return True

        self.log("Starting Ollama service...")

        if self.platform.os_type == "windows":
            # On Windows, start in background
            subprocess.Popen(
                ["ollama", "serve"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            # On Unix, use nohup or background
            subprocess.Popen(
                ["ollama", "serve"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )

        # Wait for service to start
        import time
        for _ in range(10):
            time.sleep(1)
            if check_ollama_status()["running"]:
                self.log("Ollama service started")
                return True

        self.log("Failed to start Ollama service")
        return False

    def pull_model(self, model: str = "phi3:mini") -> bool:
        """Pull an Ollama model."""
        status = check_ollama_status()
        if model in status.get("models", []):
            self.log(f"Model {model} already available")
            return True

        if not status["running"]:
            self.log("Ollama not running, starting...")
            if not self.start_ollama_service():
                return False

        self.log(f"Pulling model {model}... (this may take a few minutes)")
        code, out, err = run_command(
            ["ollama", "pull", model],
            timeout=600,
        )

        if code == 0:
            self.log(f"Model {model} pulled successfully")
            return True

        self.log(f"Failed to pull model: {err}")
        return False

    def install_python_deps(self, requirements_file: Path | None = None) -> bool:
        """Install Python dependencies in current environment."""
        if requirements_file is None:
            requirements_file = Path(__file__).parent.parent / "requirements.txt"

        if not requirements_file.exists():
            self.log(f"Requirements file not found: {requirements_file}")
            return False

        self.log(f"Installing Python dependencies from {requirements_file}...")
        code, _, err = run_command(
            [sys.executable, "-m", "pip", "install", "-r", str(requirements_file)],
            timeout=300,
        )

        if code == 0:
            self.log("Python dependencies installed successfully")
            return True

        self.log(f"Failed to install dependencies: {err}")
        return False

    def install_exiftool(self) -> bool:
        """Install exiftool if not present."""
        if check_command_exists("exiftool"):
            self.log("exiftool already installed")
            return True

        self.log("Installing exiftool...")

        if self.platform.os_type == "darwin":
            if check_command_exists("brew"):
                code, _, _ = run_command(["brew", "install", "exiftool"], timeout=120)
                return code == 0
        elif self.platform.os_type == "linux":
            # Try apt for Debian/Ubuntu
            if check_command_exists("apt-get"):
                code, _, _ = run_command(
                    ["sudo", "apt-get", "install", "-y", "libimage-exiftool-perl"],
                    timeout=120,
                )
                return code == 0
        elif self.platform.os_type == "windows":
            self.log("Download exiftool from: https://exiftool.org/")
            self.log("Extract and add to PATH")
            return False

        self.log("Could not auto-install exiftool")
        return False

    def setup_all(self, model: str = "phi3:mini") -> dict:
        """Run full setup: install all dependencies."""
        results = {
            "python_deps": False,
            "ollama_install": False,
            "ollama_service": False,
            "model_pull": False,
            "exiftool": False,
        }

        self.log("=" * 50)
        self.log("  DOCMAN SETUP")
        self.log("=" * 50)

        # Python deps
        self.log("\n[1/5] Python dependencies...")
        results["python_deps"] = self.install_python_deps()

        # Ollama install
        self.log("\n[2/5] Ollama installation...")
        results["ollama_install"] = self.install_ollama()

        # Ollama service
        self.log("\n[3/5] Ollama service...")
        results["ollama_service"] = self.start_ollama_service()

        # Model pull
        self.log("\n[4/5] AI model...")
        results["model_pull"] = self.pull_model(model)

        # Exiftool (optional)
        self.log("\n[5/5] Exiftool (optional)...")
        results["exiftool"] = self.install_exiftool()

        # Summary
        self.log("\n" + "=" * 50)
        self.log("  SETUP COMPLETE")
        self.log("=" * 50)

        success = all([
            results["python_deps"],
            results["ollama_install"],
            results["ollama_service"],
            results["model_pull"],
        ])

        if success:
            self.log("\nAll required components installed successfully!")
            self.log(f"AI model '{model}' is ready to use.")
        else:
            self.log("\nSome components failed to install.")
            for k, v in results.items():
                status = "OK" if v else "FAILED"
                self.log(f"  {k}: {status}")

        return results


def run_setup(model: str = "phi3:mini", verbose: bool = True) -> bool:
    """Convenience function to run full setup."""
    installer = Installer(verbose=verbose)
    results = installer.setup_all(model=model)
    return all([
        results["python_deps"],
        results["ollama_install"],
        results["ollama_service"],
        results["model_pull"],
    ])
