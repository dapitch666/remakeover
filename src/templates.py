"""Templates management.

Local helpers (list, save, load, delete, rename SVG templates per device)
and remote helpers (upload, backup/replace templates.json).
"""

import hashlib
import json
import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from src.config import get_device_data_dir
from src.constants import (
    CMD_RESTART_XOCHITL,
    REMOTE_CUSTOM_TEMPLATES_DIR,
    REMOTE_TEMPLATES_DIR,
    REMOTE_TEMPLATES_JSON,
)
from src.ssh import download_file_ssh, run_ssh_cmd, upload_file_ssh

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


def get_backup_stems(device_name: str) -> set[str]:
    """Return the set of template filename stems from templates.backup.json (stock templates)."""
    backup_path = get_device_templates_backup_path(device_name)
    if not os.path.exists(backup_path):
        return set()
    try:
        with open(backup_path, encoding="utf-8") as f:
            data = json.load(f)
        return {t.get("filename", "") for t in data.get("templates", [])}
    except Exception:
        return set()


def list_device_templates(device_name: str) -> list[str]:
    """Return sorted list of .svg and .template filenames stored locally for *device_name*."""
    device_dir = get_device_templates_dir(device_name)
    files = [f for f in os.listdir(device_dir) if f.lower().endswith((".svg", ".template"))]
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
    """Return filename stem (strips .svg or .template extension, case-insensitive)."""
    if filename.lower().endswith((".svg", ".template")):
        return Path(filename).stem
    return filename


def load_templates_json(device_name: str) -> dict[str, Any]:
    """Load and return data/{{device}}/templates.json, or {{"templates": []}} if absent."""
    path = get_device_templates_json_path(device_name)
    if not os.path.exists(path):
        return {"templates": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_templates_json(device_name: str, data: dict[str, Any]) -> None:
    """Persist *data* as data/{{device}}/templates.json.

    Uses ensure_ascii=True so Private Use Area icon codes (e.g. \\ue9fd) are
    written as JSON \\uXXXX escape sequences rather than the bare glyph, which
    matches the format shipped by reMarkable and avoids rendering as empty squares.
    """
    path = get_device_templates_json_path(device_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)


def get_all_categories(device_name: str) -> list[str]:
    """Return sorted list of all distinct categories found in templates.json."""
    data = load_templates_json(device_name)
    cats: set[str] = set()
    for t in data.get("templates", []):
        cats.update(t.get("categories", []))
    return sorted(cats)


def get_template_entry(device_name: str, filename: str) -> dict[str, Any] | None:
    """Return the templates.json entry whose filename matches *filename* (stem), or None."""
    stem = _stem(filename)
    for t in load_templates_json(device_name).get("templates", []):
        if t.get("filename") == stem:
            return t
    return None


@contextmanager
def _edit_templates_json(device_name: str) -> Generator[dict[str, Any], None, None]:
    """Context manager that loads templates.json, yields the data dict for mutation,
    then saves it back on exit.
    """
    data = load_templates_json(device_name)
    yield data
    save_templates_json(device_name, data)


def add_template_entry(
    device_name: str, filename: str, categories: list[str], icon_code: str = "\ue9fe"
) -> None:
    """Add or replace the templates.json entry for *filename*.

    Custom templates (those absent from templates.backup.json) are kept sorted
    alphabetically so that re-saving an existing entry does not change the file
    order and therefore does not mark templates as dirty.
    """
    stem = _stem(filename)
    backup_stems = get_backup_stems(device_name)
    with _edit_templates_json(device_name) as data:
        data["templates"] = [t for t in data["templates"] if t.get("filename") != stem]
        data["templates"].append(
            {
                "name": stem,
                "filename": stem,
                "iconCode": icon_code,
                "categories": sorted(categories),
            }
        )
        stock = [t for t in data["templates"] if t.get("filename") in backup_stems]
        custom = sorted(
            [t for t in data["templates"] if t.get("filename") not in backup_stems],
            key=lambda t: t.get("filename", "").lower(),
        )
        data["templates"] = stock + custom


def remove_template_entry(device_name: str, filename: str) -> None:
    """Remove the templates.json entry matching *filename*."""
    stem = _stem(filename)
    with _edit_templates_json(device_name) as data:
        data["templates"] = [t for t in data["templates"] if t.get("filename") != stem]


def rename_template_entry(device_name: str, old_filename: str, new_filename: str) -> None:
    """Update filename and name fields in templates.json when a template is renamed."""
    old_stem, new_stem = _stem(old_filename), _stem(new_filename)
    with _edit_templates_json(device_name) as data:
        for t in data.get("templates", []):
            if t.get("filename") == old_stem:
                t["filename"] = new_stem
                t["name"] = new_stem
                break


def update_template_categories(device_name: str, filename: str, categories: list[str]) -> None:
    """Update the categories list for *filename* in templates.json."""
    stem = _stem(filename)
    with _edit_templates_json(device_name) as data:
        for t in data.get("templates", []):
            if t.get("filename") == stem:
                t["categories"] = sorted(categories)
                break


def update_template_icon_code(device_name: str, filename: str, icon_code: str) -> None:
    """Update the iconCode for *filename* in templates.json."""
    stem = _stem(filename)
    with _edit_templates_json(device_name) as data:
        for t in data.get("templates", []):
            if t.get("filename") == stem:
                t["iconCode"] = icon_code
                break


# ---------------------------------------------------------------------------
# Remote helpers
# ---------------------------------------------------------------------------


def ensure_remote_template_dirs(
    ip: str, password: str, remote_custom_dir: str, remote_templates_dir: str
) -> tuple[bool, str]:
    """Ensure remote template directories exist. Return (ok, message)."""
    try:
        cmd = f"mkdir -p '{remote_custom_dir}' '{remote_templates_dir}'"
        out, err = run_ssh_cmd(ip, password, [cmd])
        return True, out or err
    except Exception as e:
        logger.error("ensure_remote_template_dirs failed: %s", e)
        return False, str(e)


def upload_template_svgs(
    ip: str, password: str, local_dirs: list[str], remote_custom_dir: str
) -> int:
    """Upload SVG and JSON .template files from local_dirs to remote_custom_dir. Return count uploaded."""
    sent_count = 0
    for local_templates_dir in local_dirs:
        if not os.path.exists(local_templates_dir):
            continue
        for fname in os.listdir(local_templates_dir):
            if not fname.lower().endswith((".svg", ".template")):
                continue
            local_path = os.path.join(local_templates_dir, fname)
            try:
                with open(local_path, "rb") as lf:
                    content = lf.read()
                remote_path = f"{remote_custom_dir}/{fname}"
                ok, msg = upload_file_ssh(ip, password, content, remote_path)
                if ok:
                    sent_count += 1
            except Exception as e:
                logger.warning("Failed to upload template %s: %s", local_path, e)
    return sent_count


def compare_and_backup_templates_json(ip: str, password: str, device_name: str) -> tuple[bool, str]:
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


def fetch_and_init_templates(ip: str, password: str, device_name: str) -> tuple[bool, str]:
    """Download the tablet's templates.json, save it as templates.backup.json,
    then compose the local templates.json by appending entries for any locally
    stored SVG files that are not already listed in the backup.

    Each newly discovered SVG gets the "Perso" category by default.

    Returns (ok, message).
    """
    # 1 — Download remote templates.json
    try:
        remote_content = download_file_ssh(ip, password, REMOTE_TEMPLATES_JSON)
    except Exception as e:
        logger.error("fetch_and_init_templates — download failed: %s", e)
        return False, f"download_failed: {e}"

    # 2 — Save as backup
    backup_path = get_device_templates_backup_path(device_name)
    try:
        with open(backup_path, "wb") as f:
            f.write(remote_content)
    except Exception as e:
        return False, f"backup_write_failed: {e}"

    # 3 — Parse backup
    try:
        backup_data: dict[str, Any] = json.loads(remote_content.decode("utf-8"))
    except Exception as e:
        return False, f"backup_parse_failed: {e}"

    # 4 — Append entries for local SVGs not already present in the backup
    templates_dir = get_device_templates_dir(device_name)
    existing_stems = {t.get("filename") for t in backup_data.get("templates", [])}
    appended = 0
    if os.path.exists(templates_dir):
        for svg in sorted(os.listdir(templates_dir)):
            if not svg.lower().endswith(".svg"):
                continue
            stem = _stem(svg)
            if stem not in existing_stems:
                backup_data.setdefault("templates", []).append(
                    {
                        "name": stem,
                        "filename": stem,
                        "iconCode": "\ue9fd",
                        "categories": ["Perso"],
                    }
                )
                existing_stems.add(stem)
                appended += 1

    # 5 — Persist as local templates.json
    save_templates_json(device_name, backup_data)
    logger.info(
        "fetch_and_init_templates: backup saved, %d local SVG(s) appended for '%s'",
        appended,
        device_name,
    )
    return True, f"fetched ({appended} local SVG(s) appended)"


def upload_template_to_tablet(
    ip: str, password: str, device_name: str, filename: str
) -> tuple[bool, str]:
    """Replace an existing SVG on the tablet and restart xochitl.

    The symlink and templates.json are assumed to be already in place
    (this function is only called when replacing a previously uploaded template).

    Steps:
    1. Read the local SVG.
    2. Upload SVG to REMOTE_CUSTOM_TEMPLATES_DIR.
    3. Restart xochitl.
    """
    try:
        content = load_device_template(device_name, filename)
    except Exception as e:
        return False, f"read_local_failed: {e}"

    remote_svg = f"{REMOTE_CUSTOM_TEMPLATES_DIR}/{filename}"
    ok, msg = upload_file_ssh(ip, password, content, remote_svg)
    if not ok:
        return False, f"upload_svg_failed: {msg}"

    try:
        run_ssh_cmd(ip, password, [CMD_RESTART_XOCHITL])
    except Exception as e:
        return False, f"restart_failed: {e}"

    logger.info("Template %s uploaded and xochitl restarted", filename)
    return True, "ok"


def remove_template_from_tablet(
    ip: str, password: str, device_name: str, filename: str
) -> tuple[bool, str]:
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
    with open(sync_path, encoding="utf-8") as sf:
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


# ---------------------------------------------------------------------------
# JSON template source storage (editor — stored alongside SVG templates)
# ---------------------------------------------------------------------------


def list_json_templates(device_name: str) -> list[str]:
    """Return sorted list of ``.template`` filenames stored locally for *device_name*."""
    d = get_device_templates_dir(device_name)
    return sorted(f for f in os.listdir(d) if f.lower().endswith(".template"))


def load_json_template(device_name: str, filename: str) -> str:
    """Read and return a JSON template source file as a UTF-8 string."""
    path = os.path.join(get_device_templates_dir(device_name), filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


def save_json_template(device_name: str, filename: str, content: str) -> None:
    """Write *content* to the templates directory as *filename*."""
    path = os.path.join(get_device_templates_dir(device_name), filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
