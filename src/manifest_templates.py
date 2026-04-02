"""Manifest-based template metadata management.

`manifest.json` is the source of truth for custom templates state.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from src.config import get_device_data_dir

SYNC_STATUS_SYNCED = "synced"
SYNC_STATUS_PENDING = "pending"
SYNC_STATUS_ORPHAN = "orphan"
SYNC_STATUS_DELETED = "deleted"

SYNC_STATUSES = {
    SYNC_STATUS_SYNCED,
    SYNC_STATUS_PENDING,
    SYNC_STATUS_ORPHAN,
    SYNC_STATUS_DELETED,
}


@dataclass
class ManifestTemplateEntry:
    """Template record stored in `manifest.json`."""

    name: str
    filename: str
    iconCode: str
    categories: list[str]
    syncStatus: str
    addedAt: str
    modifiedAt: str


def _utc_now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stem(filename: str) -> str:
    if filename.lower().endswith((".svg", ".template")):
        return Path(filename).stem
    return filename


def _default_manifest() -> dict[str, Any]:
    return {"version": 1, "lastSync": None, "templates": []}


def get_device_manifest_path(device_name: str) -> str:
    return os.path.join(get_device_data_dir(device_name), "manifest.json")


def manifest_exists(device_name: str) -> bool:
    return os.path.exists(get_device_manifest_path(device_name))


def load_manifest(device_name: str) -> dict[str, Any]:
    path = get_device_manifest_path(device_name)
    if not os.path.exists(path):
        return _default_manifest()
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    templates = data.get("templates", [])
    if not isinstance(templates, list):
        templates = []

    normalized: list[dict[str, Any]] = []
    now = _utc_now_iso()
    for entry in templates:
        if not isinstance(entry, dict):
            continue
        status = entry.get("syncStatus", SYNC_STATUS_PENDING)
        if status not in SYNC_STATUSES:
            status = SYNC_STATUS_PENDING
        normalized.append(
            {
                "name": str(entry.get("name", "")),
                "filename": str(entry.get("filename", "")),
                "iconCode": str(entry.get("iconCode", "\\ue9fe")),
                "categories": sorted(
                    [c for c in entry.get("categories", []) if isinstance(c, str)]
                ),
                "syncStatus": status,
                "addedAt": str(entry.get("addedAt") or now),
                "modifiedAt": str(entry.get("modifiedAt") or now),
            }
        )

    return {
        "version": int(data.get("version", 1)),
        "lastSync": data.get("lastSync"),
        "templates": normalized,
    }


def save_manifest(device_name: str, data: dict[str, Any]) -> None:
    path = get_device_manifest_path(device_name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=True)


def _find_entry(data: dict[str, Any], filename: str) -> dict[str, Any] | None:
    stem = _stem(filename)
    for entry in data.get("templates", []):
        if entry.get("filename") == stem:
            return entry
    return None


def ensure_manifest_from_templates_json(device_name: str, templates_data: dict[str, Any]) -> None:
    """Create `manifest.json` if it does not exist yet.

    Only templates that exist as local files are imported into the manifest.
    This keeps stock templates (present only in templates.json/backup) out of
    manifest.json, which is reserved for locally managed templates state.
    """
    if manifest_exists(device_name):
        return

    def _parse_template_categories(path: str) -> list[str] | None:
        try:
            with open(path, encoding="utf-8") as f:
                payload = json.load(f)
        except Exception:
            return None

        categories = payload.get("categories", [])
        if not isinstance(categories, list):
            return None
        return sorted([c for c in categories if isinstance(c, str)])

    now = _utc_now_iso()
    manifest = _default_manifest()
    manifest["lastSync"] = now

    templates = templates_data.get("templates", []) if isinstance(templates_data, dict) else []
    if not isinstance(templates, list):
        templates = []

    templates_dir = os.path.join(get_device_data_dir(device_name), "templates")
    local_template_names: list[str] = []
    if os.path.isdir(templates_dir):
        local_template_names = [
            name
            for name in sorted(os.listdir(templates_dir))
            if name.lower().endswith((".svg", ".template"))
        ]
    local_stems = {Path(name).stem for name in local_template_names}

    # Source of truth priority #1: metadata from imported templates.json,
    # but only for templates that are present locally.
    by_stem: dict[str, dict[str, Any]] = {}
    for t in templates:
        if not isinstance(t, dict):
            continue
        stem = str(t.get("filename", ""))
        if not stem:
            continue
        if stem not in local_stems:
            continue

        by_stem[stem] = {
            "name": str(t.get("name") or stem),
            "filename": stem,
            "iconCode": str(t.get("iconCode") or "\\ue9fe"),
            "categories": sorted([c for c in t.get("categories", []) if isinstance(c, str)]),
            "syncStatus": SYNC_STATUS_SYNCED,
            "addedAt": now,
            "modifiedAt": now,
        }

    # Source of truth priority #2: local files not referenced in templates.json.
    for name in local_template_names:
        lower = name.lower()
        stem = Path(name).stem
        if stem in by_stem:
            continue

        categories = ["Perso"]
        if lower.endswith(".template"):
            parsed = _parse_template_categories(os.path.join(templates_dir, name))
            if parsed is not None:
                categories = parsed

        by_stem[stem] = {
            "name": stem,
            "filename": stem,
            "iconCode": "\\ue9fe",
            "categories": categories,
            "syncStatus": SYNC_STATUS_SYNCED,
            "addedAt": now,
            "modifiedAt": now,
        }

    manifest["templates"] = list(by_stem.values())
    save_manifest(device_name, manifest)


def get_manifest_entry(device_name: str, filename: str) -> dict[str, Any] | None:
    return _find_entry(load_manifest(device_name), filename)


def list_manifest_entries(device_name: str) -> list[dict[str, Any]]:
    return list(load_manifest(device_name).get("templates", []))


def add_or_update_template_entry(
    device_name: str,
    filename: str,
    categories: list[str],
    icon_code: str = "\ue9fe",
    *,
    sync_status: str = SYNC_STATUS_PENDING,
) -> None:
    stem = _stem(filename)
    data = load_manifest(device_name)
    now = _utc_now_iso()

    entry = _find_entry(data, stem)
    if entry is None:
        data.setdefault("templates", []).append(
            {
                "name": stem,
                "filename": stem,
                "iconCode": icon_code,
                "categories": sorted(categories),
                "syncStatus": sync_status,
                "addedAt": now,
                "modifiedAt": now,
            }
        )
    else:
        entry["name"] = stem
        entry["filename"] = stem
        entry["iconCode"] = icon_code
        entry["categories"] = sorted(categories)
        entry["syncStatus"] = sync_status
        entry["modifiedAt"] = now

    save_manifest(device_name, data)


def mark_template_deleted(device_name: str, filename: str) -> None:
    stem = _stem(filename)
    data = load_manifest(device_name)
    now = _utc_now_iso()
    entry = _find_entry(data, stem)
    if entry is None:
        data.setdefault("templates", []).append(
            {
                "name": stem,
                "filename": stem,
                "iconCode": "\\ue9fe",
                "categories": ["Perso"],
                "syncStatus": SYNC_STATUS_DELETED,
                "addedAt": now,
                "modifiedAt": now,
            }
        )
    else:
        entry["syncStatus"] = SYNC_STATUS_DELETED
        entry["modifiedAt"] = now
    save_manifest(device_name, data)


def rename_entry(device_name: str, old_filename: str, new_filename: str) -> None:
    old_stem = _stem(old_filename)
    new_stem = _stem(new_filename)
    data = load_manifest(device_name)
    now = _utc_now_iso()

    for entry in data.get("templates", []):
        if entry.get("filename") == old_stem:
            entry["filename"] = new_stem
            entry["name"] = new_stem
            entry["syncStatus"] = SYNC_STATUS_PENDING
            entry["modifiedAt"] = now
            break

    save_manifest(device_name, data)


def update_categories(device_name: str, filename: str, categories: list[str]) -> None:
    data = load_manifest(device_name)
    now = _utc_now_iso()
    entry = _find_entry(data, filename)
    if entry is not None:
        entry["categories"] = sorted(categories)
        entry["syncStatus"] = SYNC_STATUS_PENDING
        entry["modifiedAt"] = now
        save_manifest(device_name, data)


def update_icon_code(device_name: str, filename: str, icon_code: str) -> None:
    data = load_manifest(device_name)
    now = _utc_now_iso()
    entry = _find_entry(data, filename)
    if entry is not None:
        entry["iconCode"] = icon_code
        entry["syncStatus"] = SYNC_STATUS_PENDING
        entry["modifiedAt"] = now
        save_manifest(device_name, data)


def set_sync_status(device_name: str, filename: str, sync_status: str) -> bool:
    """Set sync status for one manifest entry and update modifiedAt.

    Returns True when the entry exists and was updated.
    """
    if sync_status not in SYNC_STATUSES:
        return False

    data = load_manifest(device_name)
    entry = _find_entry(data, filename)
    if entry is None:
        return False

    entry["syncStatus"] = sync_status
    entry["modifiedAt"] = _utc_now_iso()
    save_manifest(device_name, data)
    return True


def get_sync_status(device_name: str, filename: str) -> str | None:
    entry = get_manifest_entry(device_name, filename)
    if not entry:
        return None
    return str(entry.get("syncStatus"))


def has_unsynced_changes(device_name: str) -> bool:
    data = load_manifest(device_name)
    return any(
        entry.get("syncStatus") in {SYNC_STATUS_PENDING, SYNC_STATUS_ORPHAN, SYNC_STATUS_DELETED}
        for entry in data.get("templates", [])
    )


def mark_synced(
    device_name: str,
    *,
    remove_deleted_entries: bool = True,
) -> None:
    data = load_manifest(device_name)
    now = _utc_now_iso()

    templates: list[dict[str, Any]] = []
    for entry in data.get("templates", []):
        status = entry.get("syncStatus")
        if status == SYNC_STATUS_DELETED and remove_deleted_entries:
            continue
        if status == SYNC_STATUS_PENDING:
            entry["syncStatus"] = SYNC_STATUS_SYNCED
        templates.append(entry)

    data["templates"] = templates
    data["lastSync"] = now
    save_manifest(device_name, data)


def upsert_orphan_entry(
    device_name: str,
    filename: str,
    categories: list[str],
    icon_code: str = "\ue9fe",
) -> None:
    add_or_update_template_entry(
        device_name,
        filename,
        categories,
        icon_code,
        sync_status=SYNC_STATUS_ORPHAN,
    )


def get_sync_overview(device_name: str) -> dict[str, int]:
    counts = {
        SYNC_STATUS_SYNCED: 0,
        SYNC_STATUS_PENDING: 0,
        SYNC_STATUS_ORPHAN: 0,
        SYNC_STATUS_DELETED: 0,
    }
    data = load_manifest(device_name)
    for entry in data.get("templates", []):
        status = entry.get("syncStatus")
        if status in counts:
            counts[status] += 1
    return counts
