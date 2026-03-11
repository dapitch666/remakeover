"""Application-level configuration and pure helper functions.

All symbols here are Streamlit-free so they can be imported and tested
without a running Streamlit session.
"""

import json
import os
from typing import Any

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


def truncate_display_name(name: Any, max_len: int = 13) -> str:
    """Return a display-safe version of *name*, truncated to *max_len* chars."""
    if not isinstance(name, str):
        return str(name)
    if len(name) <= max_len:
        return name
    return name[: max_len - 3] + "..."


# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------


def load_config(path: str | None = None) -> dict[str, Any]:
    """Load and return the device configuration.

    *path* overrides the default ``CONFIG_PATH`` (useful in tests).
    Returns ``{"devices": {}}`` when the file does not exist.
    """
    if path is None:
        path = _active_config_path()
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"devices": {}}


def save_config(config: dict[str, Any], path: str | None = None) -> None:
    """Persist *config* to *path* (defaults to the active config path)."""
    if path is None:
        path = _active_config_path()  # re-read env var at call time
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
