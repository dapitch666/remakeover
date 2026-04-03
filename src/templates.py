"""Templates management.

Local helpers store `.template` files per device and remote helpers interact
with rmMethods template triplets in xochitl (`UUID.template`,
`UUID.metadata`, `UUID.content`).
"""

import json
import logging
import os
import shlex
import time
import uuid
from contextlib import suppress
from pathlib import Path
from typing import Any

from src.config import get_device_data_dir
from src.constants import (
    CMD_RESTART_XOCHITL,
    REMOTE_XOCHITL_DATA_DIR,
)
from src.manifest_templates import (
    compute_template_sha256,
    compute_template_sha256_from_template_content,
    delete_manifest_template,
    find_manifest_uuid_by_name,
    get_device_manifest_path,
    get_manifest_entry,
    iso_from_epoch_ms,
    load_manifest,
    rename_manifest_template_by_name,
    save_manifest,
    upsert_manifest_template,
    utc_now_iso,
)
from src.ssh import download_file_ssh, run_ssh_cmd, upload_file_ssh

logger = logging.getLogger(__name__)


def _epoch_ms() -> str:
    return str(int(time.time() * 1000))


def ensure_template_payload_for_rmethods(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized payload with required rmMethods keys.

    - `labels` is always present (empty list by default)
    - `iconData` is always present (default SVG-derived placeholder)
    """
    normalized = dict(payload)
    labels = normalized.get("labels")
    if not isinstance(labels, list):
        normalized["labels"] = []

    icon_data = normalized.get("iconData")
    if not isinstance(icon_data, str) or not icon_data.strip():
        # The value is consumed by the device as an encoded SVG payload.
        normalized["iconData"] = _DEFAULT_ICON_DATA_B64

    return normalized


_DEFAULT_ICON_DATA_B64 = (
    "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNTAiIGhlaWdodD0iMjAwIiB2aWV3Qm94PSIwIDAgMTUwIDIwMCI+"
    "PHJlY3Qgd2lkdGg9IjE1MCIgaGVpZ2h0PSIyMDAiIGZpbGw9IiNmNmY2ZjQiLz48cmVjdCB4PSIxNiIgeT0iMjQiIHdpZHRoPSIxMTgiIGhlaWdodD0iMTUy"
    "IiByeD0iOCIgZmlsbD0iI2ZmZmZmZiIgc3Ryb2tlPSIjZDdkN2QzIi8+PGxpbmUgeDE9IjI4IiB5MT0iNjQiIHgyPSIxMjIiIHkyPSI2NCIgc3Ryb2tlPSIj"
    "YzdjN2MzIiBzdHJva2Utd2lkdGg9IjMiLz48bGluZSB4MT0iMjgiIHkxPSI5MiIgeDI9IjEyMiIgeTI9IjkyIiBzdHJva2U9IiNjN2M3YzMiIHN0cm9rZS13"
    "aWR0aD0iMyIvPjxsaW5lIHgxPSIyOCIgeTE9IjEyMCIgeDI9IjEyMiIgeTI9IjEyMCIgc3Ryb2tlPSIjYzdjN2MzIiBzdHJva2Utd2lkdGg9IjMiLz48bGlu"
    "ZSB4MT0iMjgiIHkxPSIxNDgiIHgyPSIxMDAiIHkyPSIxNDgiIHN0cm9rZT0iI2M3YzdjMyIgc3Ryb2tlLXdpZHRoPSIzIi8+PC9zdmc+"
)


def build_rmethods_metadata_payload(visible_name: str) -> dict[str, Any]:
    now = _epoch_ms()
    return {
        "createdTime": now,
        "lastModified": now,
        "new": False,
        "parent": "",
        "pinned": False,
        "source": "com.remarkable.methods",
        "type": "TemplateType",
        "visibleName": visible_name,
    }


def build_rmethods_triplet_payloads(payload: dict[str, Any], visible_name: str) -> dict[str, bytes]:
    """Return encoded rmMethods triplet payloads for one template.

    Returned keys are: `template`, `metadata`, `content`.
    """
    normalized = ensure_template_payload_for_rmethods(payload)
    return {
        "template": json.dumps(normalized, indent=2, ensure_ascii=True).encode("utf-8"),
        "metadata": json.dumps(
            build_rmethods_metadata_payload(visible_name),
            indent=2,
            ensure_ascii=True,
        ).encode("utf-8"),
        "content": b"{}",
    }


# ---------------------------------------------------------------------------
# Local template management (mirrors src/images.py pattern)
# ---------------------------------------------------------------------------


def get_device_templates_dir(device_name: str) -> str:
    """Return (and create) the local directory that stores `.template` files."""
    device_dir = os.path.join(get_device_data_dir(device_name), "templates")
    os.makedirs(device_dir, exist_ok=True)
    return device_dir


def get_device_manifest_json_path(device_name: str) -> str:
    """Return the path to data/{device}/manifest.json."""
    return get_device_manifest_path(device_name)


def list_device_templates(device_name: str) -> list[str]:
    """Return sorted list of local template filenames for *device_name*."""
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
    """Read and return the bytes of a locally stored template file."""
    device_dir = get_device_templates_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    with open(filepath, "rb") as f:
        return f.read()


def delete_device_template(device_name: str, filename: str) -> None:
    """Delete a locally stored template file."""
    device_dir = get_device_templates_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    if os.path.exists(filepath):
        os.remove(filepath)


def rename_device_template(device_name: str, old_filename: str, new_filename: str) -> bool:
    """Rename a locally stored template file. Returns True if successful."""
    device_dir = get_device_templates_dir(device_name)
    old_path = os.path.join(device_dir, old_filename)
    new_path = os.path.join(device_dir, new_filename)
    if os.path.exists(old_path):
        os.rename(old_path, new_path)
        return True
    return False


# ---------------------------------------------------------------------------
# Local metadata helpers
# ---------------------------------------------------------------------------


def _stem(filename: str) -> str:
    """Return filename stem (strips .svg/.template extension, case-insensitive)."""
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


def _sorted_string_categories(raw_categories: Any) -> list[str]:
    if not isinstance(raw_categories, list):
        return []
    return sorted(category for category in raw_categories if isinstance(category, str))


def refresh_local_manifest(device_name: str) -> None:
    """Rebuild local manifest entries from current local .template files.

    Manifest entries are keyed by UUID and matched by template name.
    """
    manifest = load_manifest(device_name)
    existing_templates = manifest.get("templates", {})
    existing_by_name: dict[str, tuple[str, dict[str, Any]]] = {}
    if isinstance(existing_templates, dict):
        for template_uuid, entry in existing_templates.items():
            if not isinstance(template_uuid, str) or not isinstance(entry, dict):
                continue
            name = str(entry.get("name") or "").strip()
            if name:
                existing_by_name[name] = (template_uuid, entry)

    rebuilt_templates: dict[str, dict[str, str]] = {}
    templates_dir = get_device_templates_dir(device_name)
    for filename in sorted(os.listdir(templates_dir)):
        if not filename.lower().endswith(".template"):
            continue
        stem = _stem(filename)
        try:
            content = load_json_template(device_name, filename)
        except Exception:
            continue
        sha256 = compute_template_sha256_from_template_content(content)
        if not sha256:
            continue

        existing = existing_by_name.get(stem)
        if existing:
            template_uuid, entry = existing
            created_at = str(entry.get("created_at") or "").strip() or utc_now_iso()
        else:
            template_uuid = str(uuid.uuid4())
            created_at = utc_now_iso()

        rebuilt_templates[template_uuid] = {
            "name": stem,
            "created_at": created_at,
            "sha256": sha256,
        }

    next_manifest = {
        "last_modified": manifest.get("last_modified"),
        "templates": rebuilt_templates,
    }
    if manifest.get("templates") != rebuilt_templates:
        next_manifest["last_modified"] = utc_now_iso()
    save_manifest(device_name, next_manifest)


def get_all_categories(device_name: str) -> list[str]:
    """Return sorted list of all distinct categories found in local template JSON files."""
    cats: set[str] = set()
    for filename in list_device_templates(device_name):
        try:
            payload = json.loads(load_json_template(device_name, filename))
        except Exception:
            continue
        cats.update(_sorted_string_categories(payload.get("categories", [])))
    return sorted(cats)


def get_all_labels(device_name: str) -> list[str]:
    """Return sorted list of all distinct labels found in local template JSON files."""
    labels: set[str] = set()
    for filename in list_device_templates(device_name):
        try:
            payload = json.loads(load_json_template(device_name, filename))
        except Exception:
            continue
        raw_labels = payload.get("labels", [])
        if isinstance(raw_labels, list):
            labels.update(lbl for lbl in raw_labels if isinstance(lbl, str))
    return sorted(labels)


def get_template_entry(device_name: str, filename: str) -> dict[str, Any] | None:
    """Return combined manifest and JSON metadata for one template filename."""
    refresh_local_manifest(device_name)
    entry = get_manifest_entry(device_name, filename)
    if not entry:
        return None

    result = dict(entry)
    try:
        payload = json.loads(load_json_template(device_name, filename))
    except Exception:
        payload = {}

    result["categories"] = _sorted_string_categories(payload.get("categories", []))
    raw_labels = payload.get("labels", [])
    result["labels"] = sorted(lbl for lbl in raw_labels if isinstance(lbl, str))
    result["iconData"] = (
        payload.get("iconData") if isinstance(payload.get("iconData"), str) else None
    )
    return result


def add_template_entry(
    device_name: str,
    filename: str,
    categories: list[str],
    icon_code: str = "\ue9fe",
    previous_filename: str | None = None,
    labels: list[str] | None = None,
    icon_data: str | None = None,
) -> None:
    """Add or update one local template manifest entry using UUID-keyed schema."""
    del categories, icon_code, labels, icon_data

    stem = _stem(filename)

    template_uuid = None
    if previous_filename:
        template_uuid = find_manifest_uuid_by_name(device_name, _stem(previous_filename))
    if not template_uuid:
        template_uuid = find_manifest_uuid_by_name(device_name, stem)
    if not template_uuid:
        template_uuid = str(uuid.uuid4())

    entry = get_manifest_entry(device_name, template_uuid)
    created_at = str(entry.get("created_at") or "").strip() if entry else ""
    if not created_at:
        created_at = utc_now_iso()

    sha256 = ""
    try:
        sha256 = (
            compute_template_sha256_from_template_content(load_json_template(device_name, filename))
            or ""
        )
    except Exception:
        sha256 = ""
    if not sha256:
        return

    upsert_manifest_template(
        device_name,
        template_uuid,
        name=stem,
        created_at=created_at,
        sha256=sha256,
    )


def remove_template_entry(device_name: str, filename: str) -> None:
    """Delete one template entry from manifest.json."""
    template_uuid = find_manifest_uuid_by_name(device_name, filename)
    if template_uuid:
        delete_manifest_template(device_name, template_uuid)


def rename_template_entry(device_name: str, old_filename: str, new_filename: str) -> None:
    """Rename one template entry in manifest.json."""
    rename_manifest_template_by_name(device_name, old_filename, new_filename)


def update_template_categories(device_name: str, filename: str, categories: list[str]) -> None:
    """Update categories directly in the local template JSON file."""
    try:
        payload = json.loads(load_json_template(device_name, filename))
    except Exception:
        return
    payload["categories"] = sorted(set(categories))
    save_json_template(device_name, filename, json.dumps(payload, indent=2, ensure_ascii=True))
    add_template_entry(device_name, filename, categories)


def update_template_icon_code(device_name: str, filename: str, icon_code: str) -> None:
    """Update iconCode directly in the local template JSON file."""
    try:
        payload = json.loads(load_json_template(device_name, filename))
    except Exception:
        return
    payload["iconCode"] = icon_code
    save_json_template(device_name, filename, json.dumps(payload, indent=2, ensure_ascii=True))
    add_template_entry(device_name, filename, [])


def update_template_labels(device_name: str, filename: str, labels: list[str]) -> None:
    """Update labels directly in the local template JSON file."""
    try:
        payload = json.loads(load_json_template(device_name, filename))
    except Exception:
        return
    payload["labels"] = sorted(set(lbl for lbl in labels if isinstance(lbl, str)))
    save_json_template(device_name, filename, json.dumps(payload, indent=2, ensure_ascii=True))
    add_template_entry(device_name, filename, [])


# ---------------------------------------------------------------------------
# Remote helpers
# ---------------------------------------------------------------------------


def ensure_remote_template_dirs(ip: str, password: str) -> tuple[bool, str]:
    """Ensure rmMethods xochitl directory exists. Return (ok, message)."""
    try:
        cmd = f"mkdir -p {shlex.quote(REMOTE_XOCHITL_DATA_DIR)}"
        out, err = run_ssh_cmd(ip, password, [cmd])
        return True, out or err
    except Exception as e:
        logger.error("ensure_remote_template_dirs failed: %s", e)
        return False, str(e)


def _list_remote_custom_templates(ip: str, password: str) -> tuple[bool, list[str] | str]:
    """Return remote UUID stems for rmMethods metadata files."""
    cmd = (
        f"for file in {shlex.quote(REMOTE_XOCHITL_DATA_DIR)}/*.metadata; do "
        '[ -f "$file" ] || continue; '
        'basename "$file" .metadata; '
        "done"
    )
    try:
        out, err = run_ssh_cmd(ip, password, [cmd])
    except Exception as e:
        return False, str(e)
    if err.strip():
        return False, err.strip()
    names = sorted({line.strip() for line in out.splitlines() if line.strip()})
    return True, names


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

    for metadata_path in (get_device_manifest_json_path(device_name),):
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
        overwrite_backup=True,
    )
    if not ok:
        return False, f"reinitialize_failed: {msg}"

    return True, f"reset ({removed_templates} local template(s) deleted) then {msg}"


def list_remote_custom_templates(ip: str, password: str) -> tuple[bool, set[str] | str]:
    """Return remote rmMethods UUID `.template` filenames currently present."""
    ok, payload = _list_remote_custom_templates(ip, password)
    if not ok:
        assert isinstance(payload, str)
        return False, payload
    assert isinstance(payload, list)
    return True, {f"{remote_uuid}.template" for remote_uuid in payload}


def remove_remote_custom_templates(
    ip: str,
    password: str,
    filenames: set[str],
) -> tuple[bool, str]:
    """Remove rmMethods UUID triplets inferred from *filenames* on the tablet."""
    if not filenames:
        return True, "ok"

    rm_args = []
    for fname in sorted(filenames):
        stem = _stem(fname)
        if "." in stem:
            stem = stem.split(".", 1)[0]
        if not stem:
            continue
        for ext in (".template", ".metadata", ".content"):
            rm_args.append(shlex.quote(f"{REMOTE_XOCHITL_DATA_DIR}/{stem}{ext}"))

    if not rm_args:
        return True, "ok"

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
    overwrite_backup: bool = False,
) -> tuple[bool, str]:
    """Import rmMethods templates from xochitl and initialize local manifest."""

    if overwrite_backup:
        templates_dir = get_device_templates_dir(device_name)
        for fname in os.listdir(templates_dir):
            if fname.lower().endswith(".template"):
                with suppress(OSError):
                    os.remove(os.path.join(templates_dir, fname))
        manifest_path = get_device_manifest_json_path(device_name)
        with suppress(FileNotFoundError):
            os.remove(manifest_path)

    ok, payload = _list_remote_custom_templates(ip, password)
    if not ok:
        assert isinstance(payload, str)
        return False, f"list_remote_templates_failed: {payload}"
    assert isinstance(payload, list)

    templates_dir = get_device_templates_dir(device_name)
    used_filenames: set[str] = set()
    imported = 0

    for remote_uuid in payload:
        metadata_bytes, meta_err = download_file_ssh(
            ip, password, f"{REMOTE_XOCHITL_DATA_DIR}/{remote_uuid}.metadata"
        )
        if metadata_bytes is None:
            logger.warning("Skipping %s: metadata download failed (%s)", remote_uuid, meta_err)
            continue
        template_bytes, tpl_err = download_file_ssh(
            ip, password, f"{REMOTE_XOCHITL_DATA_DIR}/{remote_uuid}.template"
        )
        if template_bytes is None:
            logger.warning("Skipping %s: template download failed (%s)", remote_uuid, tpl_err)
            continue

        try:
            metadata = json.loads(metadata_bytes.decode("utf-8"))
            payload_json = json.loads(template_bytes.decode("utf-8"))
        except Exception:
            continue

        if metadata.get("type") != "TemplateType":
            continue

        normalized_payload = ensure_template_payload_for_rmethods(payload_json)
        visible_name = str(metadata.get("visibleName") or payload_json.get("name") or remote_uuid)
        stem = visible_name.strip().replace("/", "-").replace("\\", "-") or remote_uuid
        stem = stem.replace(" ", "_")
        filename = f"{stem}.template"
        suffix = 2
        while filename in used_filenames or os.path.exists(os.path.join(templates_dir, filename)):
            filename = f"{stem}_{suffix}.template"
            suffix += 1
        used_filenames.add(filename)

        save_json_template(
            device_name, filename, json.dumps(normalized_payload, indent=2, ensure_ascii=True)
        )
        sha256 = compute_template_sha256(normalized_payload)
        created_at = iso_from_epoch_ms(metadata.get("createdTime")) or utc_now_iso()
        upsert_manifest_template(
            device_name,
            remote_uuid,
            name=_stem(filename),
            created_at=created_at,
            sha256=sha256,
        )
        imported += 1

    # Ensure manifest file exists even when no remote template is found.
    if not os.path.exists(get_device_manifest_json_path(device_name)):
        save_manifest(device_name, load_manifest(device_name))

    return True, f"fetched ({imported} template(s) imported from rmMethods)"


def delete_template_from_tablet(
    ip: str, password: str, device_name: str, filename: str
) -> tuple[bool, str]:
    """Delete one rmMethods template triplet on tablet and restart xochitl."""
    entry = get_manifest_entry(device_name, filename)
    template_uuid = str(entry.get("uuid") or "") if entry else ""
    if not template_uuid:
        return False, "delete_remote_failed: missing remote UUID"

    q_template = shlex.quote(f"{REMOTE_XOCHITL_DATA_DIR}/{template_uuid}.template")
    q_meta = shlex.quote(f"{REMOTE_XOCHITL_DATA_DIR}/{template_uuid}.metadata")
    q_content = shlex.quote(f"{REMOTE_XOCHITL_DATA_DIR}/{template_uuid}.content")
    try:
        _, err = run_ssh_cmd(ip, password, [f"rm -f {q_template} {q_meta} {q_content}"])
    except Exception as e:
        return False, f"delete_remote_failed: {e}"
    if err.strip():
        return False, f"delete_remote_failed: {err.strip()}"

    try:
        run_ssh_cmd(ip, password, [CMD_RESTART_XOCHITL])
    except Exception as e:
        return False, f"restart_failed: {e}"

    return True, "ok"


def upload_template_to_tablet(
    ip: str, password: str, device_name: str, filename: str
) -> tuple[bool, str]:
    """Upload one local template as an rmMethods UUID triplet and restart xochitl."""
    try:
        content = load_json_template(device_name, filename)
    except Exception as e:
        return False, f"read_local_failed: {e}"

    try:
        payload = json.loads(content)
    except Exception as e:
        return False, f"invalid_template_json: {e}"
    payload = ensure_template_payload_for_rmethods(payload)

    add_template_entry(device_name, filename, [])
    entry = get_manifest_entry(device_name, filename)
    template_uuid = str(entry.get("uuid") or "") if entry else ""
    if not template_uuid:
        return False, "missing_manifest_uuid"

    manifest_name = str(entry.get("name") or "") if entry else ""
    visible_name = str(manifest_name or payload.get("name") or _stem(filename))
    triplet_payloads = build_rmethods_triplet_payloads(payload, visible_name)

    for ext, blob in triplet_payloads.items():
        ok, msg = upload_file_ssh(
            ip,
            password,
            blob,
            f"{REMOTE_XOCHITL_DATA_DIR}/{template_uuid}.{ext}",
        )
        if not ok:
            return False, f"upload_{ext}_failed: {msg}"

    try:
        run_ssh_cmd(ip, password, [CMD_RESTART_XOCHITL])
    except Exception as e:
        return False, f"restart_failed: {e}"

    logger.info("Template %s uploaded and xochitl restarted", filename)
    return True, "ok"


def is_templates_dirty(device_name: str) -> bool:
    """Legacy compatibility helper.

    Sync status is no longer persisted in manifest entries, so this now always
    returns False.
    """
    del device_name
    return False


def get_template_sync_status(device_name: str, filename: str) -> str | None:
    """Legacy compatibility helper.

    Per-template persistent sync status was removed.
    """
    del device_name, filename
    return None


def get_templates_sync_overview(device_name: str) -> dict[str, int]:
    """Legacy compatibility helper.

    Per-status counters no longer exist in the new manifest schema.
    """
    del device_name
    return {"pending": 0, "orphan": 0, "deleted": 0, "synced": 0}


def set_template_sync_status(device_name: str, filename: str, status: str) -> bool:
    """Legacy compatibility helper.

    Per-template persistent sync status was removed.
    """
    del device_name, filename, status
    return False


def set_template_remote_uuid(device_name: str, filename: str, remote_uuid: str | None) -> bool:
    """Legacy compatibility helper.

    UUID is now the manifest key and is no longer stored as a mutable field.
    """
    del device_name, filename, remote_uuid
    return False


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
