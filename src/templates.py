"""Templates management.

Local helpers (list, save, load, delete, rename SVG templates per device)
and remote helpers (upload, backup/replace templates.json).
"""

import json
import logging
import os
import shlex
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import streamlit as st

from src.config import get_device_data_dir
from src.constants import (
    CMD_RESTART_XOCHITL,
    REMOTE_CUSTOM_TEMPLATES_DIR,
    REMOTE_TEMPLATES_DIR,
    REMOTE_TEMPLATES_JSON,
)
from src.manifest_templates import (
    SYNC_STATUS_DELETED,
    SYNC_STATUS_PENDING,
    ensure_manifest_from_templates_json,
    get_device_manifest_path,
    get_manifest_entry,
    get_sync_overview,
    get_sync_status,
    has_unsynced_changes,
    mark_template_deleted,
    rename_entry,
    set_sync_status,
)
from src.manifest_templates import (
    add_or_update_template_entry as manifest_add_or_update_template_entry,
)
from src.manifest_templates import (
    update_categories as manifest_update_categories,
)
from src.manifest_templates import (
    update_icon_code as manifest_update_icon_code,
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


def get_device_manifest_json_path(device_name: str) -> str:
    """Return the path to data/{device}/manifest.json."""
    return get_device_manifest_path(device_name)


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


def extract_categories_from_template_content(content: bytes) -> list[str] | None:
    """Return categories from a `.template` JSON payload, or None when parsing fails.

    Only string values are kept. Empty or missing category arrays are treated as
    valid and therefore return an empty list.
    """
    try:
        data = json.loads(content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
        return None

    categories = data.get("categories", [])
    if not isinstance(categories, list):
        return None
    return [category for category in categories if isinstance(category, str)]


@st.cache_data(ttl=5)
def load_templates_json(device_name: str) -> dict[str, Any]:
    """Load and return data/{{device}}/templates.json, or {{"templates": []}} if absent.

    Results are cached for up to 5 seconds (Streamlit cache_data).  Every
    call to :func:`save_templates_json` clears the cache so mutations are
    always visible on the very next read.
    """
    path = get_device_templates_json_path(device_name)
    if not os.path.exists(path):
        return {"templates": []}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_templates_json(device_name: str, data: dict[str, Any]) -> None:
    """Persist *data* as data/{{device}}/templates.json.

    Uses ensure_ascii=True so Private Use Area icon codes (e.g. \ue9fe) are
        written as JSON \\uXXXX escape sequences rather than the bare glyph, which
    matches the format shipped by reMarkable and avoids rendering as empty squares.

    Clears the :func:`load_templates_json` cache so the freshly written data
    is visible on the very next read.
    """
    path = get_device_templates_json_path(device_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)
    load_templates_json.clear()


def get_all_categories(device_name: str) -> list[str]:
    """Return sorted list of all distinct categories found in templates.json."""
    data = load_templates_json(device_name)
    cats: set[str] = set()
    for t in data.get("templates", []):
        cats.update(t.get("categories", []))
    return sorted(cats)


def get_template_entry(device_name: str, filename: str) -> dict[str, Any] | None:
    """Return the manifest entry whose filename matches *filename* (stem), or None."""
    entry = get_manifest_entry(device_name, filename)
    if entry and entry.get("syncStatus") == SYNC_STATUS_DELETED:
        return None
    if entry is not None:
        return entry

    # Compatibility path for legacy test/data setups that still provide only templates.json.
    stem = _stem(filename)
    for item in load_templates_json(device_name).get("templates", []):
        if item.get("filename") == stem:
            return item
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

    manifest_add_or_update_template_entry(
        device_name,
        filename,
        categories,
        icon_code,
        sync_status=SYNC_STATUS_PENDING,
    )


def remove_template_entry(device_name: str, filename: str) -> None:
    """Remove from templates.json and mark as deleted in manifest.json."""
    stem = _stem(filename)
    with _edit_templates_json(device_name) as data:
        data["templates"] = [t for t in data["templates"] if t.get("filename") != stem]
    mark_template_deleted(device_name, filename)


def rename_template_entry(device_name: str, old_filename: str, new_filename: str) -> None:
    """Update filename and name fields in templates.json when a template is renamed."""
    old_stem, new_stem = _stem(old_filename), _stem(new_filename)
    with _edit_templates_json(device_name) as data:
        for t in data.get("templates", []):
            if t.get("filename") == old_stem:
                t["filename"] = new_stem
                t["name"] = new_stem
                break
    rename_entry(device_name, old_filename, new_filename)


def update_template_categories(device_name: str, filename: str, categories: list[str]) -> None:
    """Update the categories list for *filename* in templates.json."""
    stem = _stem(filename)
    with _edit_templates_json(device_name) as data:
        for t in data.get("templates", []):
            if t.get("filename") == stem:
                t["categories"] = sorted(categories)
                break
    manifest_update_categories(device_name, filename, categories)


def update_template_icon_code(device_name: str, filename: str, icon_code: str) -> None:
    """Update the iconCode for *filename* in templates.json."""
    stem = _stem(filename)
    with _edit_templates_json(device_name) as data:
        for t in data.get("templates", []):
            if t.get("filename") == stem:
                t["iconCode"] = icon_code
                break
    manifest_update_icon_code(device_name, filename, icon_code)


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


def _list_remote_custom_templates(ip: str, password: str) -> tuple[bool, list[str] | str]:
    """Return custom template filenames present on the tablet.

    The result only includes files from REMOTE_CUSTOM_TEMPLATES_DIR ending
    with .svg or .template.
    """
    cmd = (
        f"for file in {shlex.quote(REMOTE_CUSTOM_TEMPLATES_DIR)}/*.svg "
        f"{shlex.quote(REMOTE_CUSTOM_TEMPLATES_DIR)}/*.template; do "
        '[ -f "$file" ] || continue; '
        'basename "$file"; '
        "done"
    )
    try:
        out, err = run_ssh_cmd(ip, password, [cmd])
    except Exception as e:
        return False, str(e)
    if err.strip():
        return False, err.strip()
    names = [line.strip() for line in out.splitlines() if line.strip()]
    return True, names


def remote_templates_dir_has_symlinks(ip: str, password: str) -> tuple[bool, bool | str]:
    """Return whether `/usr/share/remarkable/templates` currently contains symlinks."""
    cmd = (
        f"if find {shlex.quote(REMOTE_TEMPLATES_DIR)} -maxdepth 1 -type l | grep -q .; "
        "then echo yes; else echo no; fi"
    )
    try:
        out, err = run_ssh_cmd(ip, password, [cmd])
    except Exception as e:
        return False, str(e)
    if err.strip():
        return False, err.strip()
    return True, out.strip() == "yes"


def refresh_templates_backup_from_tablet(
    ip: str,
    password: str,
    device_name: str,
) -> tuple[bool, str]:
    """Download remote stock templates.json and overwrite local templates.backup.json."""
    remote_content, err = download_file_ssh(ip, password, REMOTE_TEMPLATES_JSON)
    if remote_content is None:
        return False, f"download_failed: {err}"

    backup_path = get_device_templates_backup_path(device_name)
    try:
        os.makedirs(os.path.dirname(backup_path), exist_ok=True)
        with open(backup_path, "wb") as f:
            f.write(remote_content)
        data = json.loads(remote_content.decode("utf-8"))
        ensure_manifest_from_templates_json(device_name, data)
    except Exception as e:
        return False, f"backup_write_failed: {e}"

    return True, "ok"


def reset_and_initialize_templates_from_tablet(
    ip: str,
    password: str,
    device_name: str,
) -> tuple[bool, str]:
    """Delete local template metadata and files, then re-import from the tablet."""
    templates_dir = get_device_templates_dir(device_name)
    removed_templates = 0

    if os.path.isdir(templates_dir):
        for filename in os.listdir(templates_dir):
            if not filename.lower().endswith((".svg", ".template")):
                continue
            filepath = os.path.join(templates_dir, filename)
            try:
                os.remove(filepath)
                removed_templates += 1
            except OSError as e:
                return False, f"local_template_delete_failed ({filename}): {e}"

    for metadata_path in (
        get_device_templates_json_path(device_name),
        get_device_templates_backup_path(device_name),
        get_device_manifest_json_path(device_name),
    ):
        if not os.path.exists(metadata_path):
            continue
        try:
            os.remove(metadata_path)
        except OSError as e:
            return False, f"local_metadata_delete_failed ({os.path.basename(metadata_path)}): {e}"

    ok, msg = fetch_and_init_templates(
        ip,
        password,
        device_name,
        include_remote_custom_templates=True,
        overwrite_backup=True,
    )
    if not ok:
        return False, f"reinitialize_failed: {msg}"

    return True, f"reset ({removed_templates} local template(s) deleted) then {msg}"


def list_remote_custom_templates(ip: str, password: str) -> tuple[bool, set[str] | str]:
    """Return the set of custom template filenames currently present on the tablet."""
    ok, payload = _list_remote_custom_templates(ip, password)
    if not ok:
        assert isinstance(payload, str)
        return False, payload
    assert isinstance(payload, list)
    return True, set(payload)


def remove_remote_custom_templates(
    ip: str,
    password: str,
    filenames: set[str],
) -> tuple[bool, str]:
    """Remove custom template files and their symlinks for *filenames* on the tablet."""
    if not filenames:
        return True, "ok"

    rm_args = []
    for fname in sorted(filenames):
        rm_args.append(shlex.quote(f"{REMOTE_CUSTOM_TEMPLATES_DIR}/{fname}"))
        rm_args.append(shlex.quote(f"{REMOTE_TEMPLATES_DIR}/{fname}"))

    cmd = f"rm -f {' '.join(rm_args)}"
    try:
        _, err = run_ssh_cmd(ip, password, [cmd])
    except Exception as e:
        return False, str(e)
    if err.strip():
        return False, err.strip()
    return True, "ok"


def fetch_and_init_templates(
    ip: str,
    password: str,
    device_name: str,
    include_remote_custom_templates: bool = False,
    overwrite_backup: bool = False,
) -> tuple[bool, str]:
    """Download tablet templates.json and initialize local template metadata.

    When ``include_remote_custom_templates`` is True, custom .svg/.template
    files already present on the tablet are also downloaded locally and added
    to the resulting local templates.json when missing.
    """
    backup_path = get_device_templates_backup_path(device_name)
    backup_exists = os.path.exists(backup_path)

    # 1 — Prefer the tablet's templates.json whenever it can be downloaded.
    remote_content, err = download_file_ssh(ip, password, REMOTE_TEMPLATES_JSON)
    if remote_content is not None:
        try:
            backup_data = json.loads(remote_content.decode("utf-8"))
        except Exception as e:
            if not (backup_exists and not overwrite_backup):
                return False, f"backup_parse_failed: {e}"
            backup_data = None
        else:
            try:
                os.makedirs(os.path.dirname(backup_path), exist_ok=True)
                with open(backup_path, "wb") as f:
                    f.write(remote_content)
            except Exception as e:
                return False, f"backup_write_failed: {e}"
    elif backup_exists and not overwrite_backup:
        try:
            with open(backup_path, encoding="utf-8") as f:
                backup_data = json.load(f)
        except Exception as e:
            return False, f"backup_parse_failed: {e}"
    else:
        logger.error("fetch_and_init_templates — download failed: %s", err)
        return False, f"download_failed: {err}"

    if backup_data is None:
        try:
            with open(backup_path, encoding="utf-8") as f:
                backup_data = json.load(f)
        except Exception as e:
            return False, f"backup_parse_failed: {e}"

    templates_dir = get_device_templates_dir(device_name)
    existing_stems = {t.get("filename") for t in backup_data.get("templates", [])}
    appended = 0
    remote_downloaded = 0

    # 4 — Optionally download custom files from tablet first
    if include_remote_custom_templates:
        ok, payload = _list_remote_custom_templates(ip, password)
        if not ok:
            return False, f"list_remote_custom_failed: {payload}"
        assert isinstance(payload, list)
        for fname in payload:
            content, dl_err = download_file_ssh(
                ip, password, f"{REMOTE_CUSTOM_TEMPLATES_DIR}/{fname}"
            )
            if content is None:
                return False, f"download_custom_failed ({fname}): {dl_err}"
            save_device_template(device_name, content, fname)
            remote_downloaded += 1

    # 5 — Append entries for local SVG/.template files not already present in backup
    if os.path.exists(templates_dir):
        for file_name in sorted(os.listdir(templates_dir)):
            if not file_name.lower().endswith((".svg", ".template")):
                continue
            stem = _stem(file_name)
            if stem not in existing_stems:
                backup_data.setdefault("templates", []).append(
                    {
                        "name": stem,
                        "filename": stem,
                        "iconCode": "\ue9fe",
                        "categories": ["Perso"],
                    }
                )
                existing_stems.add(stem)
                appended += 1

    # 6 — Persist as local templates.json
    save_templates_json(device_name, backup_data)
    ensure_manifest_from_templates_json(device_name, backup_data)
    logger.info(
        "fetch_and_init_templates: backup saved, %d local custom template(s) appended for '%s'",
        appended,
        device_name,
    )
    mode = "backup_refreshed" if remote_content is not None else "backup_preserved"
    return (
        True,
        (
            f"fetched ({appended} local custom template(s) appended, "
            f"{remote_downloaded} downloaded, {mode})"
        ),
    )


def delete_template_from_tablet(
    ip: str, password: str, device_name: str, filename: str
) -> tuple[bool, str]:
    """Delete one template file on tablet, upload local templates.json, and restart xochitl."""
    q_custom = shlex.quote(f"{REMOTE_CUSTOM_TEMPLATES_DIR}/{filename}")
    q_symlink = shlex.quote(f"{REMOTE_TEMPLATES_DIR}/{filename}")
    try:
        _, err = run_ssh_cmd(ip, password, [f"rm -f {q_custom} {q_symlink}"])
    except Exception as e:
        return False, f"delete_remote_failed: {e}"
    if err.strip():
        return False, f"delete_remote_failed: {err.strip()}"

    local_json_path = get_device_templates_json_path(device_name)
    if os.path.exists(local_json_path):
        with open(local_json_path, "rb") as f:
            json_content = f.read()
        ok, msg = upload_file_ssh(ip, password, json_content, REMOTE_TEMPLATES_JSON)
        if not ok:
            return False, f"upload_json_failed: {msg}"

    try:
        run_ssh_cmd(ip, password, [CMD_RESTART_XOCHITL])
    except Exception as e:
        return False, f"restart_failed: {e}"

    return True, "ok"


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


def is_templates_dirty(device_name: str) -> bool:
    """Return True when manifest.json contains unsynced template states."""
    return has_unsynced_changes(device_name)


def get_template_sync_status(device_name: str, filename: str) -> str | None:
    """Return template sync status from manifest.json."""
    return get_sync_status(device_name, filename)


def get_templates_sync_overview(device_name: str) -> dict[str, int]:
    """Return per-status template counts from manifest.json."""
    return get_sync_overview(device_name)


def set_template_sync_status(device_name: str, filename: str, status: str) -> bool:
    """Set sync status for one template entry in manifest.json."""
    return set_sync_status(device_name, filename, status)


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
