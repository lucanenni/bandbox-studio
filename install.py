#!/usr/bin/env python3
"""Build a local macOS installation in this checkout; never accesses Bluetooth."""
import json
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def write_launchers(root: Path) -> tuple[Path, Path]:
    """Generate user-specific files locally instead of distributing paths."""
    root = root.resolve()
    app = root / "BandBox Studio.app"
    executable = app / "Contents" / "MacOS" / "launch"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_text('''#!/bin/sh
set -eu
APP_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
PROJECT_DIR="$(dirname -- "$APP_DIR")"
exec "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/gui_launch.py"
''')
    executable.chmod(0o755)
    with (app / "Contents" / "Info.plist").open("wb") as output:
        plistlib.dump({
            "CFBundleIdentifier": "local.bandbox-studio.launcher",
            "CFBundleName": "BandBox Studio",
            "CFBundleDisplayName": "BandBox Studio",
            "CFBundleExecutable": "launch",
            "CFBundlePackageType": "APPL",
            "CFBundleVersion": "1",
            "CFBundleShortVersionString": "0.1.0",
            "LSUIElement": True,
            "NSBluetoothAlwaysUsageDescription": "Connect to your JBL BandBox Trio when you request it.",
        }, output)
    config = root / ".local" / "mcp-config.json"
    config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    config.write_text(json.dumps({"mcpServers": {"jbl-bandbox": {
        "command": str(root / ".venv" / "bin" / "python"),
        "args": [str(root / "server.py")],
    }}}, indent=2) + "\n")
    config.chmod(0o600)
    return app, config


def main() -> None:
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11 or newer is required.")
    if sys.platform != "darwin":
        raise SystemExit("BandBox Studio's Bluetooth connection requires macOS.")
    if not shutil.which("xcrun"):
        raise SystemExit("Install Xcode Command Line Tools first: xcode-select --install")
    try:
        subprocess.run(["xcrun", "--find", "swiftc"], check=True, stdout=subprocess.DEVNULL)
    except subprocess.CalledProcessError:
        raise SystemExit("Install Xcode Command Line Tools first: xcode-select --install")
    environment = ROOT / ".venv"
    if not (environment / "bin" / "python").exists():
        try:
            # Copying a uv-managed macOS executable breaks its relative
            # dynamic-library lookup. Keep the executable at its source path.
            venv.EnvBuilder(with_pip=True, symlinks=True).create(environment)
        except (subprocess.CalledProcessError, OSError) as exc:
            raise SystemExit(
                f"Could not create the Python environment at {environment}. "
                "The venv/ensurepip step failed; check the command output and use a "
                "Python 3.11+ installation with working venv and ensurepip support. "
                "Preserve or move the partial .venv before retrying. No files were removed."
            ) from exc
    python = str(environment / "bin" / "python")
    try:
        subprocess.run([python, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt")], check=True)
    except (subprocess.CalledProcessError, OSError) as exc:
        raise SystemExit(
            f"Dependency installation failed in {environment}. Check the command output, "
            f"network access, and that '{python}' -m pip --version works, then rerun install.py. "
            "The environment was preserved."
        ) from exc
    subprocess.run(["sh", str(ROOT / "build.sh")], check=True)
    app, config = write_launchers(ROOT)
    print(f"Ready. Open {app}")
    print(f"MCP configuration example: {config}")
    print("No Bluetooth connection was made. Existing MCP client settings were not changed.")


if __name__ == "__main__":
    main()
