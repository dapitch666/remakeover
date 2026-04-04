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
    REMOTE_MANIFEST_FILENAME,
    REMOTE_XOCHITL_DATA_DIR,
)
from src.manifest_templates import (
    compute_template_sha256,
    delete_manifest_template,
    get_device_manifest_path,
    get_manifest_entry,
    iso_from_epoch_ms,
    load_manifest,
    save_manifest,
    upsert_manifest_template,
    utc_now_iso,
)
from src.ssh import run_ssh_cmd, upload_file_ssh

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
    """Return (and create) the local directory that stores UUID triplet files."""
    device_dir = os.path.join(get_device_data_dir(device_name), "templates")
    os.makedirs(device_dir, exist_ok=True)
    return device_dir


def get_device_manifest_json_path(device_name: str) -> str:
    """Return the path to data/{device}/manifest.json."""
    return get_device_manifest_path(device_name)


def list_device_templates(device_name: str) -> list[str]:
    """Return sorted list of local UUID ``.template`` filenames for *device_name*."""
    refresh_local_manifest(device_name)
    device_dir = get_device_templates_dir(device_name)
    files = [
        f
        for f in os.listdir(device_dir)
        if f.lower().endswith(".template") and _is_uuid_stem(_stem(f))
    ]
    return sorted(files, key=lambda f: os.path.getmtime(os.path.join(device_dir, f)), reverse=True)


def save_device_template(device_name: str, content: bytes, filename: str) -> str:
    """Write *content* to the local templates dir and return the full path."""
    device_dir = get_device_templates_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    with open(filepath, "wb") as f:
        f.write(content)
    return filepath


def load_device_template(device_name: str, filename: str) -> bytes:
    """Read and return bytes for a local template reference."""
    template_uuid = _resolve_template_uuid(device_name, filename)
    if template_uuid:
        filepath = _triplet_paths(device_name, template_uuid)["template"]
    else:
        filepath = os.path.join(get_device_templates_dir(device_name), filename)
    with open(filepath, "rb") as f:
        return f.read()


def delete_device_template(device_name: str, filename: str) -> None:
    """Delete local UUID triplet files for a template reference."""
    template_uuid = _resolve_template_uuid(device_name, filename) or (
        _stem(filename) if _is_uuid_stem(_stem(filename)) else None
    )
    if template_uuid:
        paths = _triplet_paths(device_name, template_uuid)
        for path in paths.values():
            with suppress(FileNotFoundError):
                os.remove(path)
        return

    # Fallback for unexpected non-UUID orphan files.
    path = os.path.join(get_device_templates_dir(device_name), filename)
    with suppress(FileNotFoundError):
        os.remove(path)


def rename_device_template(
    device_name: str, old_filename: str, new_filename: str
) -> bool:  # TODO: Rename old/new_filename to old/new_name
    """Rename logical template display name while keeping UUID filenames unchanged."""
    template_uuid = _resolve_template_uuid(device_name, old_filename)
    if not template_uuid:
        return False

    display_name = _stem(new_filename).strip()
    if not display_name:
        return False

    paths = _triplet_paths(device_name, template_uuid)
    payload = _read_json_file(paths["template"])
    if not isinstance(payload, dict):
        return False

    normalized_payload = ensure_template_payload_for_rmethods(payload)
    normalized_payload["name"] = display_name
    _write_json_file(paths["template"], normalized_payload)
    sha256 = compute_template_sha256(normalized_payload)

    metadata = _ensure_local_sidecars(device_name, template_uuid, display_name)
    existing = get_manifest_entry(device_name, template_uuid)
    created_at = str(existing.get("created_at") or "").strip() if existing else ""
    if not created_at:
        created_at = iso_from_epoch_ms(metadata.get("createdTime")) or utc_now_iso()

    upsert_manifest_template(
        device_name,
        template_uuid,
        name=display_name,
        created_at=created_at,
        sha256=sha256,
    )
    return True


# ---------------------------------------------------------------------------
# Local metadata helpers
# ---------------------------------------------------------------------------


def _stem(filename: str) -> str:
    """Return filename stem (strips .template extension, case-insensitive)."""
    if filename.lower().endswith(".template"):
        return Path(filename).stem
    return filename


def _is_uuid_stem(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def _find_template_uuid_by_name(device_name: str, template_name: str) -> str | None:
    templates = load_manifest(device_name).get("templates", {})
    if not isinstance(templates, dict):
        return None
    for template_uuid, entry in templates.items():
        if not isinstance(template_uuid, str) or not isinstance(entry, dict):
            continue
        if str(entry.get("name") or "") == template_name:
            return template_uuid
    return None


def _resolve_template_uuid(device_name: str, template_ref: str) -> str | None:
    stem = _stem(template_ref)
    if _is_uuid_stem(stem):
        return stem
    return _find_template_uuid_by_name(device_name, stem)


def _triplet_paths(device_name: str, template_uuid: str) -> dict[str, str]:
    base = get_device_templates_dir(device_name)
    return {
        "template": os.path.join(base, f"{template_uuid}.template"),
        "metadata": os.path.join(base, f"{template_uuid}.metadata"),
        "content": os.path.join(base, f"{template_uuid}.content"),
    }


def _read_json_file(path: str) -> dict[str, Any] | None:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _write_json_file(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=True)


def _ensure_local_sidecars(
    device_name: str, template_uuid: str, visible_name: str
) -> dict[str, Any]:
    paths = _triplet_paths(device_name, template_uuid)

    metadata_existing = _read_json_file(paths["metadata"]) or {}
    created_time = str(metadata_existing.get("createdTime") or _epoch_ms())
    metadata_payload = dict(metadata_existing)
    metadata_payload.update(build_rmethods_metadata_payload(visible_name))
    metadata_payload["createdTime"] = created_time
    _write_json_file(paths["metadata"], metadata_payload)

    if not os.path.exists(paths["content"]):
        with open(paths["content"], "wb") as f:
            f.write(b"{}")

    return metadata_payload


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
    """Rebuild local manifest from UUID-keyed local triplet files.

    Local storage is canonicalized to ``<uuid>.template/.metadata/.content``.
    """
    manifest = load_manifest(device_name)
    existing_templates = manifest.get("templates", {})
    if not isinstance(existing_templates, dict):
        existing_templates = {}

    rebuilt_templates: dict[str, dict[str, str]] = {}
    templates_dir = get_device_templates_dir(device_name)
    for filename in sorted(os.listdir(templates_dir)):
        if not filename.lower().endswith(".template"):
            continue

        original_stem = _stem(filename)
        template_uuid = original_stem if _is_uuid_stem(original_stem) else None
        if not template_uuid:
            template_uuid = _find_template_uuid_by_name(device_name, original_stem) or str(
                uuid.uuid4()
            )

        paths = _triplet_paths(device_name, template_uuid)
        source_template_path = os.path.join(templates_dir, filename)
        if source_template_path != paths["template"]:
            os.replace(source_template_path, paths["template"])

        legacy_metadata = os.path.join(templates_dir, f"{original_stem}.metadata")
        legacy_content = os.path.join(templates_dir, f"{original_stem}.content")
        if legacy_metadata != paths["metadata"] and os.path.exists(legacy_metadata):
            with suppress(OSError):
                os.replace(legacy_metadata, paths["metadata"])
        if legacy_content != paths["content"] and os.path.exists(legacy_content):
            with suppress(OSError):
                os.replace(legacy_content, paths["content"])

        try:
            payload = json.loads(load_json_template(device_name, f"{template_uuid}.template"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        normalized_payload = ensure_template_payload_for_rmethods(payload)

        metadata = _read_json_file(paths["metadata"]) or {}
        existing_entry = existing_templates.get(template_uuid)
        metadata_name = str(metadata.get("visibleName") or "").strip()
        manifest_name = (
            str(existing_entry.get("name") or "").strip()
            if isinstance(existing_entry, dict)
            else ""
        )
        payload_name = str(normalized_payload.get("name") or "").strip()

        display_name = str(
            metadata_name or manifest_name or original_stem or payload_name or template_uuid
        ).strip()
        if not display_name:
            display_name = template_uuid

        # Keep legacy payload names when neither metadata nor manifest provide an explicit name.
        canonical_payload_name = payload_name
        if metadata_name or manifest_name or not canonical_payload_name:
            canonical_payload_name = display_name

        normalized_payload["name"] = canonical_payload_name
        _write_json_file(paths["template"], normalized_payload)
        sha256 = compute_template_sha256(normalized_payload)

        metadata = _ensure_local_sidecars(device_name, template_uuid, display_name)
        created_at = (
            str(existing_entry.get("created_at") or "").strip()
            if isinstance(existing_entry, dict)
            else ""
        )
        if not created_at:
            created_at = iso_from_epoch_ms(metadata.get("createdTime")) or utc_now_iso()

        rebuilt_templates[template_uuid] = {
            "name": display_name,
            "created_at": created_at,
            "sha256": sha256,
        }

    next_manifest = {"last_modified": manifest.get("last_modified"), "templates": rebuilt_templates}
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
    """Return combined manifest and JSON metadata for one template reference."""
    refresh_local_manifest(device_name)
    template_uuid = _resolve_template_uuid(device_name, filename)
    if not template_uuid:
        return None

    entry = get_manifest_entry(device_name, template_uuid)
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

    template_uuid = None
    if previous_filename:
        template_uuid = _resolve_template_uuid(device_name, previous_filename)
    if not template_uuid:
        template_uuid = _resolve_template_uuid(device_name, filename)
    stem = _stem(filename)
    if not template_uuid and _is_uuid_stem(stem):
        template_uuid = stem
    if not template_uuid:
        template_uuid = str(uuid.uuid4())

    paths = _triplet_paths(device_name, template_uuid)
    source_path = os.path.join(get_device_templates_dir(device_name), filename)
    if os.path.exists(source_path) and source_path != paths["template"]:
        os.replace(source_path, paths["template"])
    if not os.path.exists(paths["template"]):
        return

    entry = get_manifest_entry(device_name, template_uuid)
    created_at = str(entry.get("created_at") or "").strip() if entry else ""

    try:
        payload_raw = load_json_template(device_name, f"{template_uuid}.template")
        payload = json.loads(payload_raw)
    except Exception:
        return
    if not isinstance(payload, dict):
        return

    normalized_payload = ensure_template_payload_for_rmethods(payload)
    payload_name = str(normalized_payload.get("name") or "").strip()
    desired_name = payload_name if (previous_filename and payload_name) else stem
    if _is_uuid_stem(desired_name):
        desired_name = str(
            (entry.get("name") if entry else "") or payload_name or template_uuid
        ).strip()
    if not desired_name:
        desired_name = template_uuid

    normalized_payload["name"] = desired_name
    _write_json_file(paths["template"], normalized_payload)
    sha256 = compute_template_sha256(normalized_payload)

    metadata = _ensure_local_sidecars(device_name, template_uuid, desired_name)
    if not created_at:
        created_at = iso_from_epoch_ms(metadata.get("createdTime")) or utc_now_iso()

    upsert_manifest_template(
        device_name,
        template_uuid,
        name=desired_name,
        created_at=created_at,
        sha256=sha256,
    )


def remove_template_entry(device_name: str, filename: str) -> None:
    """Delete one template entry from manifest.json."""
    template_uuid = _resolve_template_uuid(device_name, filename)
    if template_uuid:
        delete_manifest_template(device_name, template_uuid)


def rename_template_entry(device_name: str, old_filename: str, new_filename: str) -> None:
    """Compatibility wrapper for logical template rename."""
    rename_device_template(device_name, old_filename, new_filename)


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
    """Return remote UUID stems for rmMethods template files."""
    cmd = (
        f"for file in {shlex.quote(REMOTE_XOCHITL_DATA_DIR)}/*.template; do "
        '[ -f "$file" ] || continue; '
        'basename "$file" .template; '
        "done"
    )
    try:
        out, err = run_ssh_cmd(ip, password, [cmd])
    except Exception as e:
        return False, str(e)
    if err.strip():
        return False, err.strip()
    uuids = sorted({line.strip() for line in out.splitlines() if line.strip()})
    return True, uuids


def list_remote_custom_templates(ip: str, password: str) -> tuple[bool, set[str] | str]:
    """Return remote rmMethods UUID values currently present."""
    ok, payload = _list_remote_custom_templates(ip, password)
    if not ok:
        assert isinstance(payload, str)
        return False, payload
    assert isinstance(payload, list)
    return True, set(payload)


def remove_remote_custom_templates(
    ip: str,
    password: str,
    uuids: set[str],
) -> tuple[bool, str]:
    """Remove rmMethods UUID triplets from *uuids* on the tablet."""
    if not uuids:
        return True, "ok"

    rm_args = []
    for template_uuid in sorted(uuids):
        stem = _stem(template_uuid)
        if not _is_uuid_stem(stem):
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


def upload_remote_manifest(ip: str, password: str, device_name: str) -> tuple[bool, str]:
    """Upload local manifest.json to rmMethods remote manifest path."""
    manifest_blob = json.dumps(load_manifest(device_name), indent=2, ensure_ascii=True).encode(
        "utf-8"
    )
    return upload_file_ssh(
        ip,
        password,
        manifest_blob,
        f"{REMOTE_XOCHITL_DATA_DIR}/{REMOTE_MANIFEST_FILENAME}",
    )


def delete_template_from_tablet(
    ip: str, password: str, device_name: str, filename: str
) -> tuple[bool, str]:
    """Delete one rmMethods template triplet on tablet and restart xochitl."""
    template_uuid = _resolve_template_uuid(device_name, filename)
    if not template_uuid:
        return False, "delete_remote_failed: missing remote UUID"

    entry = get_manifest_entry(device_name, template_uuid)
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
    template_uuid = _resolve_template_uuid(device_name, filename)
    if not template_uuid:
        return False, "missing_manifest_uuid"

    entry = get_manifest_entry(device_name, template_uuid)
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

    ok_manifest, msg_manifest = upload_remote_manifest(ip, password, device_name)
    if not ok_manifest:
        return False, f"upload_manifest_failed: {msg_manifest}"

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
# JSON template source storage (editor)
# ---------------------------------------------------------------------------


def list_json_templates(device_name: str) -> list[str]:
    """Return display names (``.template``) for templates available locally."""
    refresh_local_manifest(device_name)
    templates = load_manifest(device_name).get("templates", {})
    if not isinstance(templates, dict):
        return []

    names: list[str] = []
    for template_uuid, entry in templates.items():
        if not isinstance(template_uuid, str) or not isinstance(entry, dict):
            continue
        if not os.path.exists(_triplet_paths(device_name, template_uuid)["template"]):
            continue
        display_name = str(entry.get("name") or template_uuid).strip() or template_uuid
        names.append(f"{display_name}.template")
    return sorted(names, key=lambda value: value.lower())


def load_json_template(device_name: str, filename: str) -> str:
    """Read and return a JSON template source file by UUID/name reference."""
    template_uuid = _resolve_template_uuid(device_name, filename)
    if template_uuid:
        path = _triplet_paths(device_name, template_uuid)["template"]
    else:
        path = os.path.join(get_device_templates_dir(device_name), filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


def save_json_template(device_name: str, filename: str, content: str) -> None:
    """Write *content* to local storage, resolving UUID references when available."""
    template_uuid = _resolve_template_uuid(device_name, filename)
    if template_uuid:
        path = _triplet_paths(device_name, template_uuid)["template"]
    else:
        path = os.path.join(get_device_templates_dir(device_name), filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
