"""Templates management.

Local helpers (list, save, load, delete, rename SVG templates per device)
and remote helpers (upload, backup/replace templates.json).
"""

from typing import Any, Dict, List, Optional, Tuple
import hashlib
import json
import os
import logging

from src.ssh import run_ssh_cmd, upload_file_ssh, download_file_ssh
from src.constants import REMOTE_CUSTOM_TEMPLATES_DIR, REMOTE_TEMPLATES_DIR, REMOTE_TEMPLATES_JSON
from src.config import get_device_data_dir

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Local template management (mirrors src/images.py pattern)
# ---------------------------------------------------------------------------

def get_device_templates_dir(device_name: str) -> str:
    """Return (and create) the local directory that stores SVGs for *device_name*."""
    device_dir = os.path.join(get_device_data_dir(device_name), "templates")
    os.makedirs(device_dir, exist_ok=True)
    return device_dir


def get_device_templates_json_path(device_name: str) -> str:
    """Return the path to data/{device}/templates.json."""
    return os.path.join(get_device_data_dir(device_name), "templates.json")


def get_device_templates_backup_path(device_name: str) -> str:
    """Return the path to data/{device}/templates.backup.json."""
    return os.path.join(get_device_data_dir(device_name), "templates.backup.json")


def list_device_templates(device_name: str) -> List[str]:
    """Return sorted list of .svg filenames stored locally for *device_name*."""
    device_dir = get_device_templates_dir(device_name)
    if not os.path.exists(device_dir):
        return []
    files = [f for f in os.listdir(device_dir) if f.lower().endswith(".svg")]
    return sorted(files, key=lambda f: os.path.getmtime(os.path.join(device_dir, f)), reverse=True)


def save_device_template(device_name: str, content: bytes, filename: str) -> str:
    """Write *content* to the local templates dir and return the full path."""
    device_dir = get_device_templates_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    with open(filepath, "wb") as f:
        f.write(content)
    return filepath


def load_device_template(device_name: str, filename: str) -> bytes:
    """Read and return the bytes of a locally stored SVG template."""
    device_dir = get_device_templates_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    with open(filepath, "rb") as f:
        return f.read()


def delete_device_template(device_name: str, filename: str) -> None:
    """Delete a locally stored SVG template."""
    device_dir = get_device_templates_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    if os.path.exists(filepath):
        os.remove(filepath)


def rename_device_template(device_name: str, old_filename: str, new_filename: str) -> bool:
    """Rename a locally stored SVG template. Returns True if successful."""
    device_dir = get_device_templates_dir(device_name)
    old_path = os.path.join(device_dir, old_filename)
    new_path = os.path.join(device_dir, new_filename)
    if os.path.exists(old_path):
        os.rename(old_path, new_path)
        return True
    return False


# ---------------------------------------------------------------------------
# templates.json management
# ---------------------------------------------------------------------------

def _stem(filename: str) -> str:
    """Return filename without .svg extension (case-insensitive)."""
    return filename[:-4] if filename.lower().endswith(".svg") else filename


def load_templates_json(device_name: str) -> Dict[str, Any]:
    """Load and return data/{{device}}/templates.json, or {{"templates": []}} if absent."""
    path = get_device_templates_json_path(device_name)
    if not os.path.exists(path):
        return {"templates": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_templates_json(device_name: str, data: Dict[str, Any]) -> None:
    """Persist *data* as data/{{device}}/templates.json."""
    path = get_device_templates_json_path(device_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_all_categories(device_name: str) -> List[str]:
    """Return sorted list of all distinct categories found in templates.json."""
    data = load_templates_json(device_name)
    cats: set = set()
    for t in data.get("templates", []):
        cats.update(t.get("categories", []))
    return sorted(cats)


def get_template_entry(device_name: str, filename: str) -> Optional[Dict[str, Any]]:
    """Return the templates.json entry whose filename matches *filename* (stem), or None."""
    stem = _stem(filename)
    for t in load_templates_json(device_name).get("templates", []):
        if t.get("filename") == stem:
            return t
    return None


def add_template_entry(
    device_name: str, filename: str, categories: List[str], icon_code: str = "\ue9fe"
) -> None:
    """Add or replace the templates.json entry for *filename*."""
    stem = _stem(filename)
    data = load_templates_json(device_name)
    data["templates"] = [t for t in data["templates"] if t.get("filename") != stem]
    data["templates"].append(
        {"name": stem, "filename": stem, "iconCode": icon_code, "categories": categories}
    )
    save_templates_json(device_name, data)


def remove_template_entry(device_name: str, filename: str) -> None:
    """Remove the templates.json entry matching *filename*."""
    stem = _stem(filename)
    data = load_templates_json(device_name)
    data["templates"] = [t for t in data["templates"] if t.get("filename") != stem]
    save_templates_json(device_name, data)


def rename_template_entry(device_name: str, old_filename: str, new_filename: str) -> None:
    """Update filename and name fields in templates.json when a template is renamed."""
    old_stem, new_stem = _stem(old_filename), _stem(new_filename)
    data = load_templates_json(device_name)
    for t in data.get("templates", []):
        if t.get("filename") == old_stem:
            t["filename"] = new_stem
            t["name"] = new_stem
            break
    save_templates_json(device_name, data)


def update_template_categories(
    device_name: str, filename: str, categories: List[str]
) -> None:
    """Update the categories list for *filename* in templates.json."""
    stem = _stem(filename)
    data = load_templates_json(device_name)
    for t in data.get("templates", []):
        if t.get("filename") == stem:
            t["categories"] = categories
            break
    save_templates_json(device_name, data)


# ---------------------------------------------------------------------------
# Remote helpers
# ---------------------------------------------------------------------------

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


def compare_and_backup_templates_json(ip: str, password: str, device_name: str) -> Tuple[bool, str]:
    """Fetch remote templates.json and compare to the local copy at data/{device}/templates.json.

    - If local file is absent: returns (False, "no_local").
    - If identical: returns (True, "identical").
    - If different: saves remote to data/{device}/templates.backup.json, then uploads
      the local version to the tablet and returns (True, "uploaded").
    - On download failure: returns (False, "download_failed: ...").
    - On upload failure: returns (False, "upload_failed: ...").
    """
    local_json_path = get_device_templates_json_path(device_name)
    backup_path = get_device_templates_backup_path(device_name)

    try:
        remote_content = download_file_ssh(ip, password, REMOTE_TEMPLATES_JSON)
    except Exception as e:
        logger.info("No remote templates.json found or download failed: %s", e)
        return False, f"download_failed: {e}"

    if not os.path.exists(local_json_path):
        return False, "no_local"

    with open(local_json_path, "rb") as lf:
        local_content = lf.read()

    if remote_content == local_content:
        return True, "identical"

    # Remote differs — back it up
    try:
        with open(backup_path, "wb") as bf:
            bf.write(remote_content)
        logger.info("Remote templates.json backed up to %s", backup_path)
    except Exception as e:
        logger.warning("Failed to write templates.backup.json: %s", e)
        return False, f"backup_write_failed: {e}"

    # Upload the local (enriched) version to the tablet
    ok, msg = upload_file_ssh(ip, password, local_content, REMOTE_TEMPLATES_JSON)
    if not ok:
        logger.error("Failed to upload local templates.json to tablet: %s", msg)
        return False, f"upload_failed: {msg}"

    logger.info("Local templates.json uploaded to tablet (%s)", REMOTE_TEMPLATES_JSON)
    return True, "uploaded"


def upload_template_to_tablet(
    ip: str, password: str, device_name: str, filename: str
) -> Tuple[bool, str]:
    """Upload one SVG to the tablet, create its symlink, and push templates.json.

    Steps:
    1. Read the local SVG.
    2. Upload SVG to REMOTE_CUSTOM_TEMPLATES_DIR.
    3. Create symlink in REMOTE_TEMPLATES_DIR.
    4. Push local templates.json to REMOTE_TEMPLATES_JSON.
    """
    try:
        content = load_device_template(device_name, filename)
    except Exception as e:
        return False, f"read_local_failed: {e}"

    remote_svg = f"{REMOTE_CUSTOM_TEMPLATES_DIR}/{filename}"
    ok, msg = upload_file_ssh(ip, password, content, remote_svg)
    if not ok:
        return False, f"upload_svg_failed: {msg}"

    symlink_cmd = f"ln -sf '{remote_svg}' '{REMOTE_TEMPLATES_DIR}/{filename}'"
    try:
        run_ssh_cmd(ip, password, [symlink_cmd])
    except Exception as e:
        return False, f"symlink_failed: {e}"

    local_json_path = get_device_templates_json_path(device_name)
    if os.path.exists(local_json_path):
        with open(local_json_path, "rb") as f:
            json_content = f.read()
        ok, msg = upload_file_ssh(ip, password, json_content, REMOTE_TEMPLATES_JSON)
        if not ok:
            return False, f"upload_json_failed: {msg}"
        logger.info("templates.json pushed to tablet after uploading %s", filename)

    return True, "ok"


def remove_template_from_tablet(
    ip: str, password: str, device_name: str, filename: str
) -> Tuple[bool, str]:
    """Remove an SVG and its symlink from the tablet, then push updated templates.json.

    The local templates.json must already have been updated (entry removed) before
    calling this function so the pushed version reflects the deletion.
    """
    remote_svg = f"{REMOTE_CUSTOM_TEMPLATES_DIR}/{filename}"
    remote_link = f"{REMOTE_TEMPLATES_DIR}/{filename}"
    try:
        run_ssh_cmd(ip, password, [f"rm -f '{remote_svg}' '{remote_link}'"])
    except Exception as e:
        return False, f"remove_failed: {e}"

    local_json_path = get_device_templates_json_path(device_name)
    if os.path.exists(local_json_path):
        with open(local_json_path, "rb") as f:
            json_content = f.read()
        ok, msg = upload_file_ssh(ip, password, json_content, REMOTE_TEMPLATES_JSON)
        if not ok:
            return False, f"upload_json_failed: {msg}"
        logger.info("templates.json pushed to tablet after removing %s", filename)

    return True, "ok"


# ---------------------------------------------------------------------------
# Sync-state helpers
# ---------------------------------------------------------------------------

def _get_sync_state_path(device_name: str) -> str:
    """Return the path to the .tpl_sync sentinel file for *device_name*."""
    return os.path.join(get_device_data_dir(device_name), ".tpl_sync")


def is_templates_dirty(device_name: str) -> bool:
    """Return True if templates.json has changed since the last recorded sync.

    Compares the MD5 of the current templates.json against a hash written by
    :func:`mark_templates_synced`.  Returns False when there is no local
    templates.json (nothing to sync yet).
    """
    json_path = get_device_templates_json_path(device_name)
    if not os.path.exists(json_path):
        return False
    with open(json_path, "rb") as f:
        current_hash = hashlib.md5(f.read()).hexdigest()
    sync_path = _get_sync_state_path(device_name)
    if not os.path.exists(sync_path):
        # Never synced: consider dirty only if there is at least one entry.
        data = load_templates_json(device_name)
        return bool(data.get("templates"))
    with open(sync_path, "r", encoding="utf-8") as sf:
        return sf.read().strip() != current_hash


def mark_templates_synced(device_name: str) -> None:
    """Record the current templates.json MD5 as the last-known-synced hash."""
    json_path = get_device_templates_json_path(device_name)
    sync_path = _get_sync_state_path(device_name)
    if not os.path.exists(json_path):
        if os.path.exists(sync_path):
            os.remove(sync_path)
        return
    with open(json_path, "rb") as f:
        current_hash = hashlib.md5(f.read()).hexdigest()
    with open(sync_path, "w", encoding="utf-8") as sf:
        sf.write(current_hash)
