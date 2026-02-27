"""Shared rendering helpers used by multiple UI modules."""

import os

import src.ssh as _ssh
from src.constants import SUSPENDED_PNG_PATH, CMD_RESTART_XOCHITL


def _normalise_filename(filename: str, ext: str = ".png") -> str:
    """Sanitise a filename and ensure it ends with the specified extension."""
    filename = filename.replace(" ", "_")
    if not filename.endswith(ext):
        filename = os.path.splitext(filename)[0] + ext
    return filename


def _send_suspended_png(device, img_data: bytes, img_name: str, selected_name: str, add_log) -> bool:
    """Upload *img_data* as suspended.png and restart xochitl. Returns True on success."""
    success, msg = _ssh.upload_file_ssh(device.ip, device.password or "", img_data, SUSPENDED_PNG_PATH)
    if success:
        _ssh.run_ssh_cmd(device.ip, device.password or "", [CMD_RESTART_XOCHITL])
        add_log(f"Sent {img_name} to '{selected_name}'")
        return True
    add_log(f"Error sending {img_name} to '{selected_name}': {msg}")
    return False
