"""Shared local state for the GUI and MCP; nothing is written beside source."""
import os
from pathlib import Path
import uuid


def runtime_directory() -> Path:
    default = Path.home() / "Library" / "Application Support" / "BandBoxStudio" / "state"
    return Path(os.environ.get("BANDBOX_RUNTIME_DIR", str(default))).expanduser().resolve()


def pinned_identifier() -> str | None:
    value = os.environ.get("BANDBOX_DEVICE_UUID", "").strip()
    if not value:
        return None
    try:
        return str(uuid.UUID(value)).upper()
    except ValueError as exc:
        raise ValueError("BANDBOX_DEVICE_UUID must be a CoreBluetooth UUID, not a Bluetooth MAC address.") from exc
