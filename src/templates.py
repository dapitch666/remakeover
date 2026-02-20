"""Templates management scaffold.

Helpers to upload SVG templates, create symlinks and manage
templates.json backups on the remote device.
"""

from typing import List, Tuple
import os
import logging

from src.ssh import run_ssh_cmd, upload_file_ssh, download_file_ssh

logger = logging.getLogger(__name__)


def ensure_remote_template_dirs(ip: str, password: str, remote_custom_dir: str, remote_templates_dir: str) -> Tuple[bool, str]:
    """Ensure remote template directories exist. Return (ok, message)."""
    try:
        cmd = f"mkdir -p '{remote_custom_dir}' '{remote_templates_dir}'"
        out, err = run_ssh_cmd(ip, password, [cmd])
        return True, out or err
    except Exception as e:
        logger.error("ensure_remote_template_dirs failed: %s", e)
        return False, str(e)


def upload_template_svgs(ip: str, password: str, local_dirs: List[str], remote_custom_dir: str) -> int:
    """Upload SVG files from local_dirs to remote_custom_dir. Return count uploaded."""
    sent_count = 0
    for local_templates_dir in local_dirs:
        if not os.path.exists(local_templates_dir):
            continue
        for fname in os.listdir(local_templates_dir):
            if not fname.lower().endswith('.svg'):
                continue
            local_path = os.path.join(local_templates_dir, fname)
            try:
                with open(local_path, 'rb') as lf:
                    content = lf.read()
                remote_path = f"{remote_custom_dir}/{fname}"
                ok, msg = upload_file_ssh(ip, password, content, remote_path)
                if ok:
                    sent_count += 1
            except Exception as e:
                logger.warning("Failed to upload template %s: %s", local_path, e)
                continue
    return sent_count


def backup_and_replace_templates_json(ip: str, password: str, local_templates_json_path: str, remote_templates_dir: str, base_dir: str) -> Tuple[bool, str]:
    """Fetch remote templates.json, compare to local, backup if different and replace.

    Returns (ok, message).
    """
    remote_templates_json = f"{remote_templates_dir}/templates.json"
    try:
        remote_content = download_file_ssh(ip, password, remote_templates_json)
    except Exception as e:
        logger.info("No remote templates.json found or download failed: %s", e)
        return False, f"download_failed: {e}"

    if not os.path.exists(local_templates_json_path):
        return False, "no_local"

    with open(local_templates_json_path, 'rb') as lf:
        local_content = lf.read()

    if remote_content == local_content:
        return True, "identical"

    # backup remote
    try:
        backup_path = os.path.join(base_dir, 'templates.backup.json')
        with open(backup_path, 'wb') as bf:
            bf.write(remote_content)
        logger.info("Backed up remote templates.json to %s", backup_path)
    except Exception as e:
        logger.warning("Failed to write backup templates.json: %s", e)

    # replace remote with local
    ok, msg = upload_file_ssh(ip, password, local_content, remote_templates_json)
    return ok, msg
