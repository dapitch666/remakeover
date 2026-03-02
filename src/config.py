"""Application-level configuration and pure helper functions.

All symbols here are Streamlit-free so they can be imported and tested
without a running Streamlit session.
"""

import os
import json
from typing import Dict, Any, Optional

from src.constants import DEVICE_SIZES, DEFAULT_DEVICE_TYPE  # re-exported for back-compat

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _repo_root() -> str:
    """Return the repository root (parent of src/)."""
    if os.path.exists("/app"):
        return "/app"
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


BASE_DIR = _repo_root()
# Default path — can be overridden at call time via the RM_CONFIG_PATH env var.
CONFIG_PATH: str = os.path.join(BASE_DIR, "data", "config.json")


def get_device_data_dir(device_name: str) -> str:
    """Return (and create) the per-device data directory: data/{device}/

    The base data directory can be overridden via the ``RM_DATA_DIR`` environment
    variable — used in tests to avoid writing into the real ``data/`` tree.
    """
    safe = device_name.replace("/", "_").replace(" ", "_")
    base = os.environ.get("RM_DATA_DIR") or os.path.join(BASE_DIR, "data")
    path = os.path.join(base, safe)
    os.makedirs(path, exist_ok=True)
    return path


def _active_config_path() -> str:
    """Return the config path, honouring RM_CONFIG_PATH at call time."""
    return os.environ.get("RM_CONFIG_PATH") or CONFIG_PATH

# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def truncate_display_name(name: str, max_len: int = 13) -> str:
    """Return a display-safe version of *name*, truncated to *max_len* chars."""
    if not isinstance(name, str):
        return str(name)
    if len(name) <= max_len:
        return name
    return name[: max_len - 3] + "..."

# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------

def load_config(path: Optional[str] = None) -> Dict[str, Any]:
    """Load and return the device configuration.

    *path* overrides the default ``CONFIG_PATH`` (useful in tests).
    Falls back to a built-in default config for local development when the
    file does not exist and the app is not running inside Docker.
    """
    if path is None:
        path = _active_config_path()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"devices": {}}


def save_config(config: Dict[str, Any], path: Optional[str] = None) -> None:
    """Persist *config* to *path* (defaults to the active config path)."""
    if path is None:
        path = _active_config_path()  # re-read env var at call time
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

# ---------------------------------------------------------------------------
# Device-type resolution
# ---------------------------------------------------------------------------

def resolve_device_type(device: Any) -> str:
    """Return the device's type string if known, otherwise ``DEFAULT_DEVICE_TYPE``."""
    device_type = getattr(device, "device_type", None)
    if device_type in DEVICE_SIZES:
        return device_type
    return DEFAULT_DEVICE_TYPE
