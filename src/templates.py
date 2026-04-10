"""Templates management.

Local helpers store `.template` files per device and remote helpers interact
with rmMethods template triplets in xochitl (`UUID.template`,
`UUID.metadata`, `UUID.content`).
"""

import base64
import binascii
import json
import logging
import os
import re
import shlex
import time
import uuid
from collections.abc import Callable
from contextlib import suppress
from typing import Any

import paramiko

from src.config import get_device_data_dir
from src.constants import (
    DEFAULT_ICON_DATA,
    META_FIELDS,
    REMOTE_XOCHITL_DATA_DIR,
)
from src.manifest_templates import (
    _stem,
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
from src.ssh import run_ssh_cmd

logger = logging.getLogger(__name__)


def decode_icon_data(b64: str) -> str:
    """Decode base64-encoded SVG icon data into UTF-8 text."""
    try:
        return base64.b64decode(b64).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return ""


def encode_svg_to_icon_data(svg: str) -> str:
    """Encode SVG text to the base64 iconData representation."""
    return base64.b64encode(svg.encode("utf-8")).decode("ascii")


def expected_icon_dimensions(orientation: str = "portrait") -> tuple[int, int]:
    """Return expected icon dimensions for template orientation."""
    if orientation == "landscape":
        return 200, 150
    return 150, 200


def validate_svg_size(
    svg: str,
    orientation: str = "portrait",
    translate: Callable[[str], str] | None = None,
) -> tuple[bool, str]:
    """Validate SVG root width/height according to template orientation."""
    _ = translate if callable(translate) else (lambda msg: msg)

    svg_tag_m = re.search(r"<svg\b[^>]*>", svg, re.DOTALL)
    if not svg_tag_m:
        return False, _("No <svg> root element found.")
    tag = svg_tag_m.group(0)
    w_m = re.search(r'\bwidth=["\'](\d+(?:\.\d+)?)["\']', tag)
    h_m = re.search(r'\bheight=["\'](\d+(?:\.\d+)?)["\']', tag)
    if not w_m:
        return False, _("SVG must have an explicit width attribute.")
    if not h_m:
        return False, _("SVG must have an explicit height attribute.")

    w, h = int(float(w_m.group(1))), int(float(h_m.group(1)))
    expected_w, expected_h = expected_icon_dimensions(orientation)
    if w != expected_w or h != expected_h:
        return False, _("SVG must be {ew}×{eh} px (got {w}×{h}).").format(
            ew=expected_w,
            eh=expected_h,
            w=w,
            h=h,
        )
    return True, ""


def normalise_string_list(value: str | list | tuple | set | None) -> list[str]:
    """Normalize arbitrary string/list-like values into unique non-empty strings."""
    if isinstance(value, str):
        raw_values = value.split(",")
    elif isinstance(value, list | tuple | set):
        raw_values = list(value)
    elif value is None:
        raw_values = []
    else:
        raw_values = [value]

    result: list[str] = []
    seen: set[str] = set()
    for raw_value in raw_values:
        text = str(raw_value).strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def merge_multiselect_options(*option_groups: list[str]) -> list[str]:
    """Merge option groups while preserving order and uniqueness."""
    merged: list[str] = []
    seen: set[str] = set()
    for group in option_groups:
        for option in group:
            text = str(option).strip()
            if text and text not in seen:
                seen.add(text)
                merged.append(text)
    return merged


def extract_template_meta_and_body(json_str: str) -> tuple[dict[str, Any], str]:
    """Split template JSON into metadata fields and drawable body payload."""
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return {}, json_str
    if not isinstance(data, dict):
        return {}, json_str

    meta = {k: v for k, v in data.items() if k in META_FIELDS}
    body = {k: v for k, v in data.items() if k not in META_FIELDS}
    return meta, json.dumps(body, indent=4, ensure_ascii=True)


def _epoch_ms() -> str:
    return str(int(time.time() * 1000))


def ensure_template_payload(payload: dict[str, Any]) -> dict[str, Any]:
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
        normalized["iconData"] = DEFAULT_ICON_DATA

    return normalized


def build_metadata_payload(visible_name: str) -> dict[str, Any]:
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


def build_triplet_payloads(payload: dict[str, Any], visible_name: str) -> dict[str, bytes]:
    """Return encoded rmMethods triplet payloads for one template.

    Returned keys are: `template`, `metadata`, `content`.
    """
    normalized = ensure_template_payload(payload)
    return {
        "template": json.dumps(normalized, indent=2, ensure_ascii=True).encode("utf-8"),
        "metadata": json.dumps(
            build_metadata_payload(visible_name),
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
    """Return the list of local UUID ``.template`` filenames for *device_name*."""
    refresh_local_manifest(device_name)
    device_dir = get_device_templates_dir(device_name)
    return [
        f
        for f in os.listdir(device_dir)
        if f.lower().endswith(".template") and _is_uuid_stem(_stem(f))
    ]


def save_device_template(device_name: str, content: bytes, filename: str) -> str:
    """Write *content* to the local templates dir and return the full path."""
    device_dir = get_device_templates_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    with open(filepath, "wb") as f:
        f.write(content)
    return filepath


def delete_device_template(device_name: str, filename: str) -> None:
    """Delete local UUID triplet files for a template reference."""
    template_uuid = _resolve_template_uuid(device_name, filename) or (
        _stem(filename) if _is_uuid_stem(_stem(filename)) else None
    )
    if template_uuid:
        paths = triplet_paths(device_name, template_uuid)
        for path in paths.values():
            with suppress(FileNotFoundError):
                os.remove(path)
        return

    # Fallback for unexpected non-UUID orphan files.
    path = os.path.join(get_device_templates_dir(device_name), filename)
    with suppress(FileNotFoundError):
        os.remove(path)


# ---------------------------------------------------------------------------
# Local metadata helpers
# ---------------------------------------------------------------------------


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


def triplet_paths(device_name: str, template_uuid: str) -> dict[str, str]:
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
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def write_json_file(path: str, payload: dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=True)


def ensure_local_sidecars(
    device_name: str, template_uuid: str, visible_name: str
) -> dict[str, Any]:
    paths = triplet_paths(device_name, template_uuid)

    metadata_existing = _read_json_file(paths["metadata"]) or {}
    created_time = str(metadata_existing.get("createdTime") or _epoch_ms())
    metadata_payload = dict(metadata_existing)
    metadata_payload.update(build_metadata_payload(visible_name))
    metadata_payload["createdTime"] = created_time
    write_json_file(paths["metadata"], metadata_payload)

    if not os.path.exists(paths["content"]):
        with open(paths["content"], "wb") as f:
            f.write(b"{}")

    return metadata_payload


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

        paths = triplet_paths(device_name, template_uuid)
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
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue

        normalized_payload = ensure_template_payload(payload)

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
        write_json_file(paths["template"], normalized_payload)
        sha256 = compute_template_sha256(normalized_payload)

        metadata = ensure_local_sidecars(device_name, template_uuid, display_name)
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
        except (OSError, json.JSONDecodeError):
            continue
        cats.update(_sorted_string_categories(payload.get("categories", [])))
    return sorted(cats)


def get_all_labels(device_name: str) -> list[str]:
    """Return sorted list of all distinct labels found in local template JSON files."""
    labels: set[str] = set()
    for filename in list_device_templates(device_name):
        try:
            payload = json.loads(load_json_template(device_name, filename))
        except (OSError, json.JSONDecodeError):
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
    except (OSError, json.JSONDecodeError):
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
    previous_filename: str | None = None,
) -> None:
    """Add or update one local template manifest entry using UUID-keyed schema."""
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

    paths = triplet_paths(device_name, template_uuid)
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
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return

    normalized_payload = ensure_template_payload(payload)
    payload_name = str(normalized_payload.get("name") or "").strip()
    desired_name = payload_name if (previous_filename and payload_name) else stem
    if _is_uuid_stem(desired_name):
        desired_name = str(
            (entry.get("name") if entry else "") or payload_name or template_uuid
        ).strip()
    if not desired_name:
        desired_name = template_uuid

    normalized_payload["name"] = desired_name
    write_json_file(paths["template"], normalized_payload)
    sha256 = compute_template_sha256(normalized_payload)

    metadata = ensure_local_sidecars(device_name, template_uuid, desired_name)
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


# ---------------------------------------------------------------------------
# Remote helpers
# ---------------------------------------------------------------------------


def ensure_remote_template_dirs(ip: str, password: str) -> tuple[bool, str]:
    """Ensure rmMethods xochitl directory exists. Return (ok, message)."""
    try:
        cmd = f"mkdir -p {shlex.quote(REMOTE_XOCHITL_DATA_DIR)}"
        out, err = run_ssh_cmd(ip, password, [cmd])
        if err.strip():
            return False, err.strip()
        return True, out
    except (OSError, paramiko.SSHException) as e:
        logger.error("ensure_remote_template_dirs failed: %s", e)
        return False, str(e)


def list_remote_custom_templates(ip: str, password: str) -> tuple[bool, list[str] | str]:
    """Return remote templates UUID values currently present."""
    cmd = (
        f"for file in {shlex.quote(REMOTE_XOCHITL_DATA_DIR)}/*.template; do "
        '[ -f "$file" ] || continue; '
        'basename "$file" .template; '
        "done"
    )
    try:
        out, err = run_ssh_cmd(ip, password, [cmd])
    except (OSError, paramiko.SSHException) as e:
        return False, str(e)
    if err.strip():
        return False, err.strip()
    uuids = sorted({line.strip() for line in out.splitlines() if line.strip()})
    return True, uuids


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
    except (OSError, paramiko.SSHException) as e:
        return False, str(e)
    if err.strip():
        return False, err.strip()
    return True, "ok"


# ---------------------------------------------------------------------------
# JSON template source storage (editor)
# ---------------------------------------------------------------------------


def load_json_template(device_name: str, filename: str) -> str:
    """Read and return a JSON template source file by UUID/name reference."""
    template_uuid = _resolve_template_uuid(device_name, filename)
    if template_uuid:
        path = triplet_paths(device_name, template_uuid)["template"]
    else:
        path = os.path.join(get_device_templates_dir(device_name), filename)
    with open(path, encoding="utf-8") as f:
        return f.read()


def save_json_template(device_name: str, filename: str, content: str) -> None:
    """Write *content* to local storage, resolving UUID references when available."""
    template_uuid = _resolve_template_uuid(device_name, filename)
    if template_uuid:
        path = triplet_paths(device_name, template_uuid)["template"]
    else:
        path = os.path.join(get_device_templates_dir(device_name), filename)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
