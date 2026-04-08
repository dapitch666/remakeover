"""High-level synchronization based on local/remote template manifests."""

from __future__ import annotations

import json
import os
import shlex
from contextlib import suppress
from typing import Any

import src.ssh as _ssh
import src.templates as _tpl
from src.constants import CMD_RESTART_XOCHITL, REMOTE_MANIFEST_FILENAME, REMOTE_XOCHITL_DATA_DIR
from src.manifest_templates import (
    _default_manifest,
    _normalize_manifest,
    load_manifest,
    utc_now_iso,
)


def _remote_manifest_path() -> str:
    return f"{REMOTE_XOCHITL_DATA_DIR}/{REMOTE_MANIFEST_FILENAME}"


def _is_missing_remote_manifest_error(err: str) -> bool:
    lowered = err.lower()
    return "no such file" in lowered or "not found" in lowered


def _fetch_remote_manifest(ip: str, pw: str) -> tuple[bool, dict[str, Any], str]:
    content, err = _ssh.download_file_ssh(ip, pw, _remote_manifest_path())
    if content is None:
        if _is_missing_remote_manifest_error(err):
            return True, _default_manifest(), "missing"
        return False, _default_manifest(), err

    try:
        parsed = json.loads(content.decode("utf-8"))
    except Exception as exc:
        return False, _default_manifest(), f"invalid_remote_manifest: {exc}"
    return True, _normalize_manifest(parsed), "ok"


def _push_remote_manifest(ip: str, pw: str, manifest: dict[str, Any]) -> tuple[bool, str]:
    payload = json.dumps(_normalize_manifest(manifest), indent=2, ensure_ascii=True).encode("utf-8")
    return _ssh.upload_file_ssh(ip, pw, payload, _remote_manifest_path())


def _compare_manifests(
    local_manifest: dict[str, Any], remote_manifest: dict[str, Any]
) -> dict[str, Any]:
    local_templates = local_manifest.get("templates", {})
    remote_templates = remote_manifest.get("templates", {})

    to_upload: list[dict[str, str]] = []
    identical: list[str] = []
    for template_uuid, local_entry in local_templates.items():
        remote_entry = remote_templates.get(template_uuid)
        if not isinstance(remote_entry, dict):
            to_upload.append({"uuid": template_uuid, "reason": "missing_remote"})
            continue
        if remote_entry.get("sha256") != local_entry.get("sha256") or remote_entry.get(
            "name"
        ) != local_entry.get("name"):
            to_upload.append({"uuid": template_uuid, "reason": "different"})
            continue
        identical.append(template_uuid)

    to_delete_remote = sorted(set(remote_templates) - set(local_templates))

    return {
        "local_count": len(local_templates),
        "remote_count": len(remote_templates),
        "in_sync_count": len(identical),
        "to_upload": to_upload,
        "to_delete_remote": to_delete_remote,
    }


def _manifest_entry_name(entry: Any, fallback: str) -> str:
    if isinstance(entry, dict):
        name = str(entry.get("name") or "").strip()
        if name:
            return name
    return fallback


def _enrich_diff_with_names(
    diff: dict[str, Any],
    local_manifest: dict[str, Any],
    remote_manifest: dict[str, Any],
) -> dict[str, Any]:
    local_templates = local_manifest.get("templates", {})
    remote_templates = remote_manifest.get("templates", {})

    to_upload_added_names: list[str] = []
    to_upload_modified_names: list[str] = []
    to_delete_remote_names: list[str] = []

    for job in diff.get("to_upload", []):
        template_uuid = str(job.get("uuid") or "").strip()
        reason = str(job.get("reason") or "").strip()
        if not template_uuid:
            continue

        name = _manifest_entry_name(local_templates.get(template_uuid), template_uuid)
        if reason == "missing_remote":
            to_upload_added_names.append(name)
        else:
            to_upload_modified_names.append(name)

    for template_uuid in diff.get("to_delete_remote", []):
        template_id = str(template_uuid).strip()
        if not template_id:
            continue
        to_delete_remote_names.append(
            _manifest_entry_name(remote_templates.get(template_id), template_id)
        )

    enriched = dict(diff)
    enriched["to_upload_added_names"] = sorted(set(to_upload_added_names), key=str.casefold)
    enriched["to_upload_modified_names"] = sorted(set(to_upload_modified_names), key=str.casefold)
    enriched["to_delete_remote_names"] = sorted(set(to_delete_remote_names), key=str.casefold)
    return enriched


def compute_sync_status_from_cached_remote(
    selected_name: str,
    cached_remote_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Compute sync status locally from current manifest and a cached remote snapshot."""
    local_manifest = load_manifest(selected_name)
    remote_manifest = _normalize_manifest(cached_remote_manifest)

    result = _compare_manifests(local_manifest, remote_manifest)
    enriched = _enrich_diff_with_names(result, local_manifest, remote_manifest)
    enriched["remote_manifest_state"] = "cached_snapshot"
    enriched["remote_manifest_snapshot"] = remote_manifest
    enriched["checked_at"] = utc_now_iso()
    return enriched


def build_assumed_sync_status(selected_name: str, remote_state: str) -> dict[str, Any]:
    """Build a sync status payload assuming local state is the current remote snapshot."""
    local_manifest = load_manifest(selected_name)
    payload = compute_sync_status_from_cached_remote(selected_name, local_manifest)
    payload["remote_manifest_state"] = remote_state
    payload["last_remote_check_at"] = payload.get("checked_at")
    return payload


def refresh_cached_sync_status(
    selected_name: str,
    cached_sync_status: dict[str, Any],
) -> dict[str, Any] | None:
    """Recompute a cached sync status from its stored remote snapshot."""
    snapshot = cached_sync_status.get("remote_manifest_snapshot")
    if not isinstance(snapshot, dict):
        return None

    refreshed = compute_sync_status_from_cached_remote(selected_name, snapshot)
    refreshed["last_remote_check_at"] = cached_sync_status.get(
        "last_remote_check_at"
    ) or cached_sync_status.get("checked_at")
    refreshed["last_remote_manifest_state"] = cached_sync_status.get("remote_manifest_state")
    return refreshed


def check_sync_status(selected_name: str, device, add_log) -> tuple[bool, dict[str, Any] | str]:
    """Compare local and remote manifests without mutating local state."""
    ip = device.ip
    pw = device.password or ""

    local_manifest = load_manifest(selected_name)

    ok_remote, remote_manifest, status_msg = _fetch_remote_manifest(ip, pw)
    if not ok_remote:
        return False, status_msg

    result = _compare_manifests(local_manifest, remote_manifest)
    result = _enrich_diff_with_names(result, local_manifest, remote_manifest)
    result["remote_manifest_state"] = status_msg
    result["remote_manifest_snapshot"] = remote_manifest
    result["checked_at"] = utc_now_iso()

    add_log(
        f"Sync check on '{selected_name}' "
        f"(local={result['local_count']}, remote={result['remote_count']}, "
        f"upload={len(result['to_upload'])}, delete_remote={len(result['to_delete_remote'])})"
    )
    return True, result


def fetch_and_init_templates(
    ip: str,
    password: str,
    device_name: str,
    overwrite_backup: bool = False,
) -> tuple[bool, str]:
    """Import rmMethods templates from xochitl, build local manifest, then push it."""
    pw = password or ""

    if overwrite_backup:
        templates_dir = _tpl.get_device_templates_dir(device_name)
        for fname in os.listdir(templates_dir):
            if fname.lower().endswith((".template", ".metadata", ".content")):
                with suppress(OSError):
                    os.remove(os.path.join(templates_dir, fname))
        manifest_path = _tpl.get_device_manifest_json_path(device_name)
        with suppress(FileNotFoundError):
            os.remove(manifest_path)

    ok, payload = _tpl._list_remote_custom_templates(ip, pw)
    if not ok:
        return False, f"list_remote_templates_failed: {payload}"
    if not isinstance(payload, list):
        raise TypeError(f"Expected list from _list_remote_custom_templates, got {type(payload)}")

    imported = 0
    for remote_uuid in payload:
        metadata_bytes, meta_err = _ssh.download_file_ssh(
            ip, pw, f"{REMOTE_XOCHITL_DATA_DIR}/{remote_uuid}.metadata"
        )
        if metadata_bytes is None:
            _tpl.logger.warning("Skipping %s: metadata download failed (%s)", remote_uuid, meta_err)
            continue

        template_bytes, tpl_err = _ssh.download_file_ssh(
            ip, pw, f"{REMOTE_XOCHITL_DATA_DIR}/{remote_uuid}.template"
        )
        if template_bytes is None:
            _tpl.logger.warning("Skipping %s: template download failed (%s)", remote_uuid, tpl_err)
            continue

        content_bytes, content_err = _ssh.download_file_ssh(
            ip, pw, f"{REMOTE_XOCHITL_DATA_DIR}/{remote_uuid}.content"
        )
        if content_bytes is None:
            _tpl.logger.info(
                "No remote .content for %s (%s), using empty object", remote_uuid, content_err
            )
            content_bytes = b"{}"

        try:
            metadata = json.loads(metadata_bytes.decode("utf-8"))
            payload_json = json.loads(template_bytes.decode("utf-8"))
        except Exception:
            continue

        if metadata.get("type") != "TemplateType":
            continue

        normalized_payload = _tpl.ensure_template_payload(payload_json)
        visible_name = str(
            metadata.get("visibleName") or normalized_payload.get("name") or remote_uuid
        )
        paths = _tpl._triplet_paths(device_name, remote_uuid)
        _tpl._write_json_file(paths["template"], normalized_payload)
        with open(paths["metadata"], "wb") as f:
            f.write(metadata_bytes)
        with open(paths["content"], "wb") as f:
            f.write(content_bytes)

        _tpl._ensure_local_sidecars(device_name, remote_uuid, visible_name)
        sha256 = _tpl.compute_template_sha256(normalized_payload)
        created_at = _tpl.iso_from_epoch_ms(metadata.get("createdTime")) or _tpl.utc_now_iso()
        _tpl.upsert_manifest_template(
            device_name,
            remote_uuid,
            name=visible_name,
            created_at=created_at,
            sha256=sha256,
        )
        imported += 1

    ok_manifest_upload, manifest_upload_msg = _push_remote_manifest(
        ip, pw, load_manifest(device_name)
    )
    if not ok_manifest_upload:
        return False, f"upload_remote_manifest_failed: {manifest_upload_msg}"

    return True, f"fetched ({imported} template(s) imported from rmMethods)"


def sync_templates_to_tablet(
    selected_name: str,
    device,
    add_log,
    force: bool = False,
    restart_xochitl: bool = True,
) -> bool:
    """Synchronize local templates to tablet using manifest comparison."""
    del force
    ip = device.ip
    pw = device.password or ""

    ok_dirs, msg = _tpl.ensure_remote_template_dirs(ip, pw)
    if not ok_dirs:
        add_log(f"Sync templates — ensure dirs: {msg}")
        return False

    local_manifest = load_manifest(selected_name)

    ok_remote, remote_manifest, remote_state = _fetch_remote_manifest(ip, pw)
    if not ok_remote:
        add_log(f"Sync templates — fetch remote manifest: {remote_state}")
        return False

    diff = _compare_manifests(local_manifest, remote_manifest)
    local_templates = local_manifest.get("templates", {})

    uploaded = 0
    for job in diff["to_upload"]:
        template_uuid = job["uuid"]
        local_entry = local_templates.get(template_uuid, {})
        visible_name = str(local_entry.get("name") or "")
        if not visible_name:
            add_log(f"Sync templates — invalid local manifest entry for UUID {template_uuid}")
            return False

        local_filename = f"{template_uuid}.template"

        try:
            payload = json.loads(_tpl.load_json_template(selected_name, local_filename))
        except Exception as exc:
            add_log(f"Sync templates — invalid template JSON '{local_filename}': {exc}")
            return False

        payload = _tpl.ensure_template_payload(payload)
        for ext, blob in _tpl.build_triplet_payloads(payload, visible_name).items():
            ok_upload, upload_msg = _ssh.upload_file_ssh(
                ip,
                pw,
                blob,
                f"{REMOTE_XOCHITL_DATA_DIR}/{template_uuid}.{ext}",
            )
            if not ok_upload:
                add_log(
                    f"Sync templates — upload '{local_filename}' ({ext}, {template_uuid}): {upload_msg}"
                )
                return False
        thumbnails_dir = f"{REMOTE_XOCHITL_DATA_DIR}/{template_uuid}.thumbnails"
        cleanup_cmd = f"rm -rf {shlex.quote(thumbnails_dir)}"
        _, cleanup_err = _ssh.run_ssh_cmd(ip, pw, [cleanup_cmd])
        if cleanup_err.strip():
            add_log(f"Sync templates — cleanup thumbnails '{template_uuid}': {cleanup_err.strip()}")
        uploaded += 1

    deleted = 0
    to_delete = set(diff["to_delete_remote"])
    if to_delete:
        ok_delete, delete_msg = _tpl.remove_remote_custom_templates(ip, pw, to_delete)
        if not ok_delete:
            add_log(f"Sync templates — delete remote entries: {delete_msg}")
            return False
        deleted = len(to_delete)

    ok_manifest_upload, manifest_upload_msg = _push_remote_manifest(ip, pw, local_manifest)
    if not ok_manifest_upload:
        add_log(f"Sync templates — upload remote manifest failed: {manifest_upload_msg}")
        return False

    if restart_xochitl:
        out, err = _ssh.run_ssh_cmd(ip, pw, [CMD_RESTART_XOCHITL])
        if err.strip():
            add_log(f"Sync templates — restart xochitl: {err.strip()}")
            return False
        del out

    add_log(
        f"Templates synced on '{selected_name}' "
        f"(uploaded={uploaded}, deleted_remote={deleted}, unchanged={diff['in_sync_count']}, "
        f"remote_manifest={remote_state})"
    )
    return True
