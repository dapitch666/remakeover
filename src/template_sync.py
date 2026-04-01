"""High-level template sync orchestration.

Provides :func:`sync_templates_to_tablet`, which pushes all local SVG and
JSON templates plus ``templates.json`` to the device and restarts xochitl.

The function is intentionally side-effect-free with respect to Streamlit: it
receives an ``add_log`` callback so that callers can route messages to any
logging facility without creating a dependency on ``st.*``.
"""

import os

import src.ssh as _ssh
import src.templates as _tpl
from src.constants import (
    CMD_RESTART_XOCHITL,
    REMOTE_CUSTOM_TEMPLATES_DIR,
    REMOTE_TEMPLATES_DIR,
    REMOTE_TEMPLATES_JSON,
)


def sync_templates_to_tablet(selected_name: str, device, add_log, force: bool = False) -> bool:
    """Push all local SVG and JSON templates + templates.json to the tablet, restart xochitl.

    Uses module-level references to ``src.templates`` and ``src.ssh`` so that
    unit tests can patch those modules in the normal way.

    Returns ``True`` on success, ``False`` if any step fails (error details are
    forwarded to ``add_log``).
    """
    ip = device.ip
    pw = device.password or ""

    ok, msg = _tpl.ensure_remote_template_dirs(
        ip, pw, REMOTE_CUSTOM_TEMPLATES_DIR, REMOTE_TEMPLATES_DIR
    )
    if not ok:
        add_log(f"Sync templates — ensure dirs: {msg}")
        return False

    device_templates_dir = _tpl.get_device_templates_dir(selected_name)
    sent = _tpl.upload_template_svgs(ip, pw, [device_templates_dir], REMOTE_CUSTOM_TEMPLATES_DIR)

    if sent:
        ok, msg = _tpl.symlink_templates_on_device(ip, pw)
        if not ok:
            add_log(f"Sync templates — symlinks: {msg}")
            return False

    local_json_path = _tpl.get_device_templates_json_path(selected_name)
    if os.path.exists(local_json_path):
        with open(local_json_path, "rb") as f:
            json_content = f.read()
        ok, msg = _ssh.upload_file_ssh(ip, pw, json_content, REMOTE_TEMPLATES_JSON)
        if not ok:
            add_log(f"Sync templates — templates.json upload: {msg}")
            return False

    try:
        _ssh.run_ssh_cmd(ip, pw, [CMD_RESTART_XOCHITL])
    except Exception as e:
        add_log(f"Sync templates — restart xochitl: {e}")
        return False

    _tpl.mark_templates_synced(selected_name)
    mode = "forced" if force else "standard"
    add_log(
        f"Templates synced on '{selected_name}' "
        f"[{mode}] "
        f"({sent} file(s) uploaded, "
        f"templates.json {'uploaded' if os.path.exists(local_json_path) else 'not found locally'})"
    )
    return True
