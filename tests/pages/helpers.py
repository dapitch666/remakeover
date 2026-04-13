"""Shared helpers for pages/ AppTest-based integration tests.

These utilities are imported directly by each page test module.
"""

import base64
import json
import os
from contextlib import ExitStack
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

# ---------------------------------------------------------------------------
# Synthetic media
# ---------------------------------------------------------------------------

# Minimal valid 1×1 PNG used wherever image bytes are needed.
PNG_BYTES = base64.b64decode(
    b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)

# ---------------------------------------------------------------------------
# Config file factories
# ---------------------------------------------------------------------------


def write_config(tmp_path, cfg: dict) -> str:
    """Write *cfg* to a temp config file and return its absolute path."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    return str(cfg_file)


def empty_cfg(tmp_path) -> str:
    """Config with no devices."""
    return write_config(tmp_path, {"devices": {}})


def with_device(tmp_path, name: str = "D1") -> str:
    """Config with a single fully-configured device."""
    return write_config(
        tmp_path,
        {
            "devices": {
                name: {
                    "ip": "10.0.0.1",
                    "password": "pw",
                    "device_type": "reMarkable 2",
                }
            }
        },
    )


def with_two_devices(tmp_path) -> str:
    """Config with two devices (D1 and D2)."""
    return write_config(
        tmp_path,
        {
            "devices": {
                "D1": {"ip": "10.0.0.1", "password": "pw", "device_type": "reMarkable 2"},
                "D2": {"ip": "10.0.0.2", "password": "pw2", "device_type": "reMarkable 2"},
            }
        },
    )


# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------


def make_env(tmp_path, cfg_path: str) -> dict:
    """Return env overrides that redirect both config and data dir to tmp_path."""
    return {"RM_CONFIG_PATH": cfg_path, "RM_DATA_DIR": str(tmp_path)}


# ---------------------------------------------------------------------------
# AppTest shortcuts
# ---------------------------------------------------------------------------


def at_page(
    tmp_path,
    page: str,
    cfg_path: str | None = None,
    patches: list | None = None,
    session_state: dict | None = None,
) -> AppTest:
    """Boot app.py then switch to *page*, applying optional patches and session state overrides."""
    cfg_path = cfg_path or with_device(tmp_path)
    env = make_env(tmp_path, cfg_path)
    # noinspection PyAbstractClass
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, env))
        for p in patches or []:
            stack.enter_context(p)
        at = AppTest.from_file("app.py")
        at.run()
        if session_state:
            for key, value in session_state.items():
                at.session_state[key] = value
        at.switch_page(page).run()
        return at


# ---------------------------------------------------------------------------
# Integration-flow patches (SSH + images side-effects)
# ---------------------------------------------------------------------------


def flow_patches(images_dir, upload_calls, run_cmds, saved_files):
    """Return a list of patch() context managers for all src.* side-effectful calls."""

    def _save_device_image(_device_name, img_data, filename):
        out = os.path.join(str(images_dir), filename)
        with open(out, "wb") as f:
            f.write(img_data)
        saved_files.append(out)
        return True

    def _load_device_image(_device_name, img_name):
        p = os.path.join(str(images_dir), img_name)
        return open(p, "rb").read() if os.path.exists(p) else b""

    return [
        patch(
            "src.ssh.upload_file_ssh",
            side_effect=lambda ip, _pw, _blob, path: upload_calls.append((ip, path))
            or (True, "ok"),
        ),
        patch("src.ssh.download_file_ssh", return_value=(PNG_BYTES, "")),
        patch(
            "src.ssh.run_ssh_cmd",
            side_effect=lambda ip, _pw, cmds: run_cmds.append((ip, tuple(cmds))),
        ),
        patch("src.images.process_image", return_value=b"processed"),
        patch("src.images.get_device_images_dir", return_value=str(images_dir)),
        patch(
            "src.images.list_device_images",
            side_effect=lambda name: sorted(os.listdir(str(images_dir))),
        ),
        patch("src.images.save_device_image", side_effect=_save_device_image),
        patch("src.images.load_device_image", side_effect=_load_device_image),
        patch("src.images.delete_device_image", return_value=True),
        patch("src.images.rename_device_image", return_value=True),
        patch("src.dialog.confirm", return_value=True),
    ]


# ---------------------------------------------------------------------------
# Template-test helpers
# ---------------------------------------------------------------------------


def backup_dir(tmp_path, device: str = "D1"):
    """Create device data dir with manifest.json and templates/ directory."""
    d = tmp_path / device
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.json").write_text(
        '{"last_modified": null, "templates": {}}',
        encoding="utf-8",
    )
    (d / "templates").mkdir(exist_ok=True)
    return d
