"""Local image management helpers used by the UI and maintenance logic.

All images are stored as PNG files under ``data/{device}/images/``.
"""

import io
import logging
import os
from contextlib import suppress

from PIL import Image

import src.ssh as _ssh
from src.config import get_device_data_dir
from src.constants import CMD_RESTART_XOCHITL, SUSPENDED_PNG_PATH, XOCHITL_CONF_PATH

logger = logging.getLogger(__name__)


def get_device_images_dir(device_name: str) -> str:
    """Return (and create) the per-device images directory: ``data/{device}/images/``."""
    device_dir = os.path.join(get_device_data_dir(device_name), "images")
    os.makedirs(device_dir, exist_ok=True)
    return device_dir


def list_device_images(device_name: str) -> list[str]:
    """Return PNG filenames in the device image directory, sorted by modification time (newest first)."""
    device_dir = get_device_images_dir(device_name)
    files = [f for f in os.listdir(device_dir) if f.endswith(".png")]
    return sorted(files, key=lambda f: os.path.getmtime(os.path.join(device_dir, f)), reverse=True)


def save_device_image(device_name: str, image_data: bytes, filename: str) -> str:
    """Write *image_data* to ``{images_dir}/{filename}`` and return the full path."""
    device_dir = get_device_images_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    with open(filepath, "wb") as f:
        f.write(image_data)
    return filepath


def load_device_image(device_name: str, filename: str) -> bytes:
    """Read and return the raw bytes of ``{images_dir}/{filename}``."""
    device_dir = get_device_images_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    with open(filepath, "rb") as f:
        return f.read()


def delete_device_image(device_name: str, filename: str) -> None:
    """Delete ``{images_dir}/{filename}`` if it exists."""
    device_dir = get_device_images_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    if os.path.exists(filepath):
        os.remove(filepath)


def rename_device_image(device_name: str, old_filename: str, new_filename: str) -> bool:
    """Rename an image file; returns True on success, False if the source does not exist."""
    device_dir = get_device_images_dir(device_name)
    old_path = os.path.join(device_dir, old_filename)
    new_path = os.path.join(device_dir, new_filename)
    if os.path.exists(old_path):
        os.rename(old_path, new_path)
        return True
    return False


def process_image(uploaded_file, width: int, height: int) -> bytes:
    """Resize and convert *uploaded_file* to a PNG of exactly *width* × *height* pixels.

    If the file is already a PNG at the target size it is returned as-is.
    """
    img = Image.open(uploaded_file)
    if img.format == "PNG" and img.size == (width, height):
        with suppress(Exception):
            uploaded_file.seek(0)
        return uploaded_file.read()
    result = img.resize((width, height), Image.Resampling.LANCZOS).convert("RGB")
    buf = io.BytesIO()
    result.save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Sleep-screen device operations
# ---------------------------------------------------------------------------

# Shell command that checks whether SleepScreenPath is already set in xochitl.conf
# and adds it under [General] if not. Outputs 'already_set' or 'just_set' so the
# caller can decide whether a xochitl restart is needed.
_CMD_CHECK_OR_SET_SLEEP_SCREEN = (
    f"if grep -q '^SleepScreenPath=' {XOCHITL_CONF_PATH}; "
    f"then echo 'already_set'; "
    f"else sed -i '/^\\[General\\]/a SleepScreenPath={SUSPENDED_PNG_PATH}' {XOCHITL_CONF_PATH}"
    f" && echo 'just_set'; fi"
)


def _ensure_sleep_screen_path(ip: str, password: str) -> tuple[bool, str]:
    """Ensure SleepScreenPath is configured in xochitl.conf.

    Returns ``(restart_needed, error)``.  *restart_needed* is True when the key
    was newly added (xochitl must be restarted to pick it up).  *error* is
    non-empty if the command produced unexpected output or stderr, indicating
    that the config file could not be read or written.
    """
    stdout, stderr = _ssh.run_ssh_cmd(ip, password, [_CMD_CHECK_OR_SET_SLEEP_SCREEN])
    if "just_set" in stdout:
        return True, ""
    if "already_set" in stdout:
        return False, ""
    return False, stderr or "unexpected output from SleepScreenPath check"


def send_suspended_png(device, img_data: bytes, img_name: str, add_log) -> bool:
    """Upload *img_data* as the sleep screen and configure xochitl if needed.

    Restarts xochitl only on the first send (when SleepScreenPath is newly
    written to xochitl.conf). Subsequent sends just replace the file.
    Returns True on success.
    """
    pw = device.password or ""
    success, msg = _ssh.upload_file_ssh(device.ip, pw, img_data, SUSPENDED_PNG_PATH)
    if not success:
        add_log(f"Error sending {img_name} to '{device.name}': {msg}")
        return False
    restart_needed, err = _ensure_sleep_screen_path(device.ip, pw)
    if err:
        add_log(f"Error configuring sleep screen on '{device.name}': {err}")
        return False
    if restart_needed:
        _ssh.run_ssh_cmd(device.ip, pw, [CMD_RESTART_XOCHITL])
    add_log(f"Sent {img_name} to '{device.name}'")
    return True


def rollback_sleep_screen(device, add_log) -> bool:
    """Remove the custom sleep screen from the device and restore the default.

    Deletes SleepScreenPath from xochitl.conf, removes the image file, and
    restarts xochitl. Returns True on success.
    """
    pw = device.password or ""
    _, stderr = _ssh.run_ssh_cmd(
        device.ip,
        pw,
        [
            f"sed -i '/^SleepScreenPath=/d' {XOCHITL_CONF_PATH}",
            f"rm -f {SUSPENDED_PNG_PATH}",
            CMD_RESTART_XOCHITL,
        ],
    )
    if stderr:
        add_log(f"Error rolling back sleep screen on '{device.name}': {stderr}")
        return False
    add_log(f"Sleep screen reset to default on '{device.name}'")
    return True
