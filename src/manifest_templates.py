"""Manifest helpers for local and remote template metadata.

The manifest schema is intentionally minimal:

{
  "last_modified": "2026-04-04T12:34:56Z",
  "templates": {
    "<uuid>": {
      "name": "TemplateName",
      "created_at": "2026-04-04T12:00:00Z",
      "sha256": "..."
    }
  }
}
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.config import get_device_data_dir


def utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_manifest() -> dict[str, Any]:
    return {"last_modified": None, "templates": {}}


def _stem(filename: str) -> str:
    if filename.lower().endswith((".svg", ".template")):
        return Path(filename).stem
    return filename


def get_device_manifest_path(device_name: str) -> str:
    return os.path.join(get_device_data_dir(device_name), "manifest.json")


def manifest_exists(device_name: str) -> bool:
    return os.path.exists(get_device_manifest_path(device_name))


def canonical_template_json(payload: dict[str, Any]) -> str:
    """Return a stable JSON representation used for SHA-256 hashing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def compute_template_sha256(payload: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_template_json(payload).encode("utf-8")).hexdigest()


def compute_template_sha256_from_template_content(content: str | bytes) -> str | None:
    raw = content.decode("utf-8") if isinstance(content, bytes) else content
    try:
        payload = json.loads(raw)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return compute_template_sha256(payload)


def iso_from_epoch_ms(value: Any) -> str | None:
    """Convert epoch milliseconds to UTC ISO string, when possible."""
    if value in (None, ""):
        return None
    try:
        epoch_ms = int(str(value))
    except (TypeError, ValueError):
        return None
    dt = datetime.fromtimestamp(epoch_ms / 1000, tz=UTC)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_manifest(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return _default_manifest()

    templates_raw = data.get("templates", {})
    if not isinstance(templates_raw, dict):
        templates_raw = {}

    now = utc_now_iso()
    normalized_templates: dict[str, dict[str, str]] = {}
    for template_uuid, entry in templates_raw.items():
        if not isinstance(template_uuid, str) or not template_uuid.strip():
            continue
        if not isinstance(entry, dict):
            continue

        name = str(entry.get("name") or "").strip()
        created_at = str(entry.get("created_at") or now).strip()
        sha256 = str(entry.get("sha256") or "").strip().lower()

        if not name or not created_at or not sha256:
            continue

        normalized_templates[template_uuid] = {
            "name": name,
            "created_at": created_at,
            "sha256": sha256,
        }

    last_modified_raw = data.get("last_modified")
    last_modified = str(last_modified_raw).strip() if last_modified_raw else None

    return {
        "last_modified": last_modified,
        "templates": normalized_templates,
    }


def load_manifest(device_name: str) -> dict[str, Any]:
    path = get_device_manifest_path(device_name)
    if not os.path.exists(path):
        return _default_manifest()
    try:
        with open(path, encoding="utf-8") as f:
            return _normalize_manifest(json.load(f))
    except Exception:
        return _default_manifest()


def save_manifest(device_name: str, data: dict[str, Any]) -> None:
    path = get_device_manifest_path(device_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    normalized = _normalize_manifest(data)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(normalized, f, indent=2, ensure_ascii=True)


def _find_uuid_by_name(data: dict[str, Any], name: str) -> str | None:
    stem = _stem(name)
    for template_uuid, entry in data.get("templates", {}).items():
        if entry.get("name") == stem:
            return template_uuid
    return None


def find_manifest_uuid_by_name(device_name: str, name: str) -> str | None:
    return _find_uuid_by_name(load_manifest(device_name), name)


def get_manifest_entry(device_name: str, template_uuid_or_name: str) -> dict[str, Any] | None:
    data = load_manifest(device_name)

    by_uuid = data.get("templates", {}).get(template_uuid_or_name)
    if isinstance(by_uuid, dict):
        return {"uuid": template_uuid_or_name, **by_uuid}

    found_uuid = _find_uuid_by_name(data, template_uuid_or_name)
    if not found_uuid:
        return None

    entry = data.get("templates", {}).get(found_uuid)
    if not isinstance(entry, dict):
        return None
    return {"uuid": found_uuid, **entry}


def list_manifest_entries(device_name: str) -> list[dict[str, Any]]:
    data = load_manifest(device_name)
    rows = [
        {"uuid": template_uuid, **entry}
        for template_uuid, entry in data.get("templates", {}).items()
        if isinstance(entry, dict)
    ]
    return sorted(rows, key=lambda row: str(row.get("name", "")).lower())


def upsert_manifest_template(
    device_name: str,
    template_uuid: str,
    *,
    name: str,
    created_at: str | None,
    sha256: str,
) -> None:
    data = load_manifest(device_name)
    entry = data.setdefault("templates", {}).get(template_uuid)

    if not isinstance(entry, dict):
        entry = {}

    preserved_created_at = str(entry.get("created_at") or "").strip() or created_at or utc_now_iso()
    data["templates"][template_uuid] = {
        "name": _stem(name),
        "created_at": preserved_created_at,
        "sha256": sha256.lower(),
    }
    data["last_modified"] = utc_now_iso()
    save_manifest(device_name, data)


def delete_manifest_template(device_name: str, template_uuid: str) -> bool:
    data = load_manifest(device_name)
    templates = data.get("templates", {})
    if not isinstance(templates, dict) or template_uuid not in templates:
        return False
    templates.pop(template_uuid, None)
    data["last_modified"] = utc_now_iso()
    save_manifest(device_name, data)
    return True


def rename_manifest_template_by_name(device_name: str, old_name: str, new_name: str) -> bool:
    data = load_manifest(device_name)
    template_uuid = _find_uuid_by_name(data, old_name)
    if not template_uuid:
        return False
    entry = data.get("templates", {}).get(template_uuid)
    if not isinstance(entry, dict):
        return False
    entry["name"] = _stem(new_name)
    data["last_modified"] = utc_now_iso()
    save_manifest(device_name, data)
    return True


def ensure_manifest_from_imported_templates(
    device_name: str, imported_templates: dict[str, Any]
) -> None:
    """Create an empty manifest file when missing.

    The previous metadata bootstrap flow is no longer used. The manifest is now
    populated directly by template import/sync operations.
    """
    if manifest_exists(device_name):
        return
    manifest = _default_manifest()
    manifest["last_modified"] = utc_now_iso()
    save_manifest(device_name, manifest)
