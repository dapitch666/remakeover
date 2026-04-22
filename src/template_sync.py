"""High-level synchronization based on local/remote template manifests."""

from __future__ import annotations

import json
import os
import shlex
from collections.abc import Callable
from contextlib import suppress
from typing import Any

import src.ssh as _ssh
import src.templates as _tpl
from src.constants import CMD_RESTART_XOCHITL, REMOTE_MANIFEST_FILENAME, REMOTE_XOCHITL_DATA_DIR
from src.manifest_templates import (
    default_manifest,
    get_device_manifest_path,
    load_manifest,
    normalize_manifest,
    utc_now_iso,
)
from src.models import Device


def _remote_manifest_path() -> str:
    return f"{REMOTE_XOCHITL_DATA_DIR}/{REMOTE_MANIFEST_FILENAME}"


def _is_missing_remote_manifest_error(err: str) -> bool:
    lowered = err.lower()
    return "no such file" in lowered or "not found" in lowered


def _parse_remote_manifest_bytes(
    content: bytes | None, err: str
) -> tuple[bool, dict[str, Any], str]:
    """Parse a downloaded manifest blob into a normalized result triple.

    Returns ``(True, manifest, "missing")`` when the file did not exist,
    ``(True, manifest, "ok")`` on success, or ``(False, default, error)`` on failure.
    """
    if content is None:
        if _is_missing_remote_manifest_error(err):
            return True, default_manifest(), "missing"
        return False, default_manifest(), err
    try:
        parsed = json.loads(content.decode("utf-8"))
    except Exception as exc:
        return False, default_manifest(), f"invalid_remote_manifest: {exc}"
    return True, normalize_manifest(parsed), "ok"


def _serialise_manifest(manifest: dict[str, Any]) -> bytes:
    """Encode *manifest* to the canonical wire format used by all push operations."""
    return json.dumps(normalize_manifest(manifest), indent=2, ensure_ascii=True).encode("utf-8")


def _fetch_remote_manifest(device: Device) -> tuple[bool, dict[str, Any], str]:
    return _parse_remote_manifest_bytes(*_ssh.download_file_ssh(device, _remote_manifest_path()))


def _push_remote_manifest(device: Device, manifest: dict[str, Any]) -> tuple[bool, str]:
    return _ssh.upload_file_ssh(device, _serialise_manifest(manifest), _remote_manifest_path())


def _fetch_remote_manifest_s(session: _ssh.SshSession) -> tuple[bool, dict[str, Any], str]:
    return _parse_remote_manifest_bytes(*session.download(_remote_manifest_path()))


def _push_remote_manifest_s(session: _ssh.SshSession, manifest: dict[str, Any]) -> tuple[bool, str]:
    return session.upload(_serialise_manifest(manifest), _remote_manifest_path())


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


def _sort_pairs_by_name(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    return sorted(pairs, key=lambda p: p[0].casefold())


def _enrich_diff_with_names(
    diff: dict[str, Any],
    local_manifest: dict[str, Any],
    remote_manifest: dict[str, Any],
) -> dict[str, Any]:
    local_templates = local_manifest.get("templates", {})
    remote_templates = remote_manifest.get("templates", {})

    to_upload_added_pairs: list[tuple[str, str]] = []
    to_upload_modified_pairs: list[tuple[str, str]] = []
    to_delete_remote_pairs: list[tuple[str, str]] = []

    for job in diff.get("to_upload", []):
        template_uuid = str(job.get("uuid") or "").strip()
        reason = str(job.get("reason") or "").strip()
        if not template_uuid:
            continue

        name = _manifest_entry_name(local_templates.get(template_uuid), template_uuid)
        if reason == "missing_remote":
            to_upload_added_pairs.append((name, template_uuid))
        else:
            to_upload_modified_pairs.append((name, template_uuid))

    for template_uuid in diff.get("to_delete_remote", []):
        template_id = str(template_uuid).strip()
        if not template_id:
            continue
        name = _manifest_entry_name(remote_templates.get(template_id), template_id)
        to_delete_remote_pairs.append((name, template_id))

    def _uuids(pairs: list[tuple[str, str]]) -> list[str]:
        return [uuid for _, uuid in _sort_pairs_by_name(pairs)]

    def _name_by_uuid(pairs: list[tuple[str, str]]) -> dict[str, str]:
        return {uuid: n for n, uuid in pairs}

    enriched = dict(diff)
    enriched["to_upload_added_uuids"] = _uuids(to_upload_added_pairs)
    enriched["to_upload_modified_uuids"] = _uuids(to_upload_modified_pairs)
    enriched["to_delete_remote_uuids"] = _uuids(to_delete_remote_pairs)
    enriched["to_upload_added_name_by_uuid"] = _name_by_uuid(to_upload_added_pairs)
    enriched["to_upload_modified_name_by_uuid"] = _name_by_uuid(to_upload_modified_pairs)
    enriched["to_delete_remote_name_by_uuid"] = _name_by_uuid(to_delete_remote_pairs)
    return enriched


def compute_sync_status_from_cached_remote(
    selected_name: str,
    cached_remote_manifest: dict[str, Any],
) -> dict[str, Any]:
    """Compute sync status locally from current manifest and a cached remote snapshot."""
    local_manifest = load_manifest(selected_name)
    remote_manifest = normalize_manifest(cached_remote_manifest)

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


def check_sync_status(
    device: Device, add_log: Callable[[str], None]
) -> tuple[bool, dict[str, Any] | str]:
    """Compare local and remote manifests without mutating local state."""
    local_manifest = load_manifest(device.name)

    ok_remote, remote_manifest, status_msg = _fetch_remote_manifest(device)
    if not ok_remote:
        return False, status_msg

    result = _compare_manifests(local_manifest, remote_manifest)
    result = _enrich_diff_with_names(result, local_manifest, remote_manifest)
    result["remote_manifest_state"] = status_msg
    result["remote_manifest_snapshot"] = remote_manifest
    result["checked_at"] = utc_now_iso()

    add_log(
        f"Sync check on '{device.name}' "
        f"(local={result['local_count']}, remote={result['remote_count']}, "
        f"upload={len(result['to_upload'])}, delete_remote={len(result['to_delete_remote'])})"
    )
    return True, result


def list_remote_custom_templates(device: Device) -> tuple[bool, list[str] | str]:
    """Return UUID values of rmMethods templates currently present on the device."""
    cmd = (
        f"for file in {shlex.quote(REMOTE_XOCHITL_DATA_DIR)}/*.template; do "
        '[ -f "$file" ] || continue; '
        'basename "$file" .template; '
        "done"
    )
    out, err = _ssh.run_ssh_cmd(device, [cmd])
    if err.strip():
        return False, err.strip()
    uuids = sorted({line.strip() for line in out.splitlines() if line.strip()})
    return True, uuids


def remove_remote_custom_templates(
    session: _ssh.SshSession,
    uuids: set[str],
) -> tuple[bool, str]:
    """Remove rmMethods UUID triplets from *uuids* on the device."""
    if not uuids:
        return True, "ok"

    rm_args = []
    for template_uuid in sorted(uuids):
        stem = _tpl._stem(template_uuid)
        if not _tpl._is_uuid_stem(stem):
            continue
        for ext in (".template", ".metadata", ".content"):
            rm_args.append(shlex.quote(f"{REMOTE_XOCHITL_DATA_DIR}/{stem}{ext}"))

    if not rm_args:
        return True, "ok"

    _, err = session.run([f"rm -f {' '.join(rm_args)}"])
    if err.strip():
        return False, err.strip()
    return True, "ok"


def fetch_and_init_templates(
    device: Device,
    overwrite_backup: bool = False,
) -> tuple[bool, str]:
    """Import rmMethods templates from xochitl, build local manifest, then push it."""

    if overwrite_backup:
        templates_dir = _tpl.get_device_templates_dir(device.name)
        for filename in os.listdir(templates_dir):
            if filename.lower().endswith((".template", ".metadata", ".content")):
                with suppress(OSError):
                    os.remove(os.path.join(templates_dir, filename))
        manifest_path = get_device_manifest_path(device.name)
        with suppress(FileNotFoundError):
            os.remove(manifest_path)

    ok, payload = list_remote_custom_templates(device)
    if not ok:
        return False, f"list_remote_templates_failed: {payload}"
    if not isinstance(payload, list):
        raise TypeError(f"Expected list from list_remote_custom_templates, got {type(payload)}")

    imported = 0
    for remote_uuid in payload:
        metadata_bytes, meta_err = _ssh.download_file_ssh(
            device, f"{REMOTE_XOCHITL_DATA_DIR}/{remote_uuid}.metadata"
        )
        if metadata_bytes is None:
            _tpl.logger.warning("Skipping %s: metadata download failed (%s)", remote_uuid, meta_err)
            continue

        template_bytes, tpl_err = _ssh.download_file_ssh(
            device, f"{REMOTE_XOCHITL_DATA_DIR}/{remote_uuid}.template"
        )
        if template_bytes is None:
            _tpl.logger.warning("Skipping %s: template download failed (%s)", remote_uuid, tpl_err)
            continue

        content_bytes, content_err = _ssh.download_file_ssh(
            device, f"{REMOTE_XOCHITL_DATA_DIR}/{remote_uuid}.content"
        )
        if content_bytes is None:
            _tpl.logger.info(
                "No remote .content for %s (%s), using empty object", remote_uuid, content_err
            )
            content_bytes = b"{}"

        try:
            metadata = json.loads(metadata_bytes.decode("utf-8"))
            payload_json = json.loads(template_bytes.decode("utf-8"))
        except json.JSONDecodeError:
            continue

        if metadata.get("type") != "TemplateType":
            continue

        normalized_payload = _tpl.ensure_template_payload(payload_json)
        visible_name = str(
            metadata.get("visibleName") or normalized_payload.get("name") or remote_uuid
        )
        paths = _tpl.triplet_paths(device.name, remote_uuid)
        (_tpl.write_json_file(paths["template"], normalized_payload))
        with open(paths["metadata"], "wb") as f:
            f.write(metadata_bytes)
        with open(paths["content"], "wb") as f:
            f.write(content_bytes)

        _tpl.ensure_local_sidecars(device.name, remote_uuid, visible_name)
        sha256 = _tpl.compute_template_sha256(normalized_payload)
        created_at = _tpl.iso_from_epoch_ms(metadata.get("createdTime")) or _tpl.utc_now_iso()
        _tpl.upsert_manifest_template(
            device.name,
            remote_uuid,
            name=visible_name,
            created_at=created_at,
            sha256=sha256,
        )
        imported += 1

    ok_manifest_upload, manifest_upload_msg = _push_remote_manifest(
        device, load_manifest(device.name)
    )
    if not ok_manifest_upload:
        return False, f"upload_remote_manifest_failed: {manifest_upload_msg}"

    return True, f"fetched ({imported} template(s) imported from rmMethods)"


def fetch_single_template_from_device(
    device: Device,
    template_uuid: str,
) -> tuple[bool, str]:
    """Download a single template triplet from the device and save it locally.

    Used when a remote-only template is clicked in the sync status pills —
    it imports that one template without touching anything else.
    """
    metadata_bytes, meta_err = _ssh.download_file_ssh(
        device, f"{REMOTE_XOCHITL_DATA_DIR}/{template_uuid}.metadata"
    )
    if metadata_bytes is None:
        return False, f"metadata_download_failed: {meta_err}"

    template_bytes, tpl_err = _ssh.download_file_ssh(
        device, f"{REMOTE_XOCHITL_DATA_DIR}/{template_uuid}.template"
    )
    if template_bytes is None:
        return False, f"template_download_failed: {tpl_err}"

    content_bytes, content_err = _ssh.download_file_ssh(
        device, f"{REMOTE_XOCHITL_DATA_DIR}/{template_uuid}.content"
    )
    if content_bytes is None:
        _tpl.logger.info(
            "No remote .content for %s (%s), using empty object", template_uuid, content_err
        )
        content_bytes = b"{}"

    try:
        metadata = json.loads(metadata_bytes.decode("utf-8"))
        payload_json = json.loads(template_bytes.decode("utf-8"))
    except json.JSONDecodeError as exc:
        return False, f"json_decode_failed: {exc}"

    if metadata.get("type") != "TemplateType":
        return False, f"not_a_template: type={metadata.get('type')!r}"

    normalized_payload = _tpl.ensure_template_payload(payload_json)
    visible_name = str(
        metadata.get("visibleName") or normalized_payload.get("name") or template_uuid
    )
    paths = _tpl.triplet_paths(device.name, template_uuid)
    _tpl.write_json_file(paths["template"], normalized_payload)
    with open(paths["metadata"], "wb") as f:
        f.write(metadata_bytes)
    with open(paths["content"], "wb") as f:
        f.write(content_bytes)

    _tpl.ensure_local_sidecars(device.name, template_uuid, visible_name)
    sha256 = _tpl.compute_template_sha256(normalized_payload)
    created_at = _tpl.iso_from_epoch_ms(metadata.get("createdTime")) or _tpl.utc_now_iso()
    _tpl.upsert_manifest_template(
        device.name,
        template_uuid,
        name=visible_name,
        created_at=created_at,
        sha256=sha256,
    )

    # Do not push the manifest back to the device: the template already exists
    # there, so nothing on the device changes. Pushing would cause the template
    # to disappear from the "remote-only" list on the next status recompute.

    return True, f"imported '{visible_name}' from device"


def sync_templates_to_device(
    selected_name: str,
    device,
    add_log: Callable[[str], None],
) -> bool:
    """Synchronize local templates to device using manifest comparison."""
    local_manifest = load_manifest(selected_name)

    try:
        with _ssh.ssh_session(device) as s:
            ok_remote, remote_manifest, remote_state = _fetch_remote_manifest_s(s)
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
                    add_log(
                        f"Sync templates — invalid local manifest entry for UUID {template_uuid}"
                    )
                    return False

                local_filename = f"{template_uuid}.template"

                try:
                    payload = json.loads(_tpl.load_json_template(selected_name, local_filename))
                except Exception as exc:
                    add_log(f"Sync templates — invalid template JSON '{local_filename}': {exc}")
                    return False

                payload = _tpl.ensure_template_payload(payload)
                for ext, blob in _tpl.build_triplet_payloads(payload, visible_name).items():
                    ok_upload, upload_msg = s.upload(
                        blob,
                        f"{REMOTE_XOCHITL_DATA_DIR}/{template_uuid}.{ext}",
                    )
                    if not ok_upload:
                        add_log(
                            f"Sync templates — upload '{local_filename}' ({ext}, {template_uuid}): {upload_msg}"
                        )
                        return False
                thumbnails_dir = f"{REMOTE_XOCHITL_DATA_DIR}/{template_uuid}.thumbnails"
                _, cleanup_err = s.run([f"rm -rf {shlex.quote(thumbnails_dir)}"])
                if cleanup_err.strip():
                    add_log(
                        f"Sync templates — cleanup thumbnails '{template_uuid}': {cleanup_err.strip()}"
                    )
                uploaded += 1

            deleted = 0
            to_delete = set(diff["to_delete_remote"])
            if to_delete:
                ok_delete, delete_msg = remove_remote_custom_templates(s, to_delete)
                if not ok_delete:
                    add_log(f"Sync templates — delete remote entries: {delete_msg}")
                    return False
                deleted = len(to_delete)

            ok_manifest_upload, manifest_upload_msg = _push_remote_manifest_s(s, local_manifest)
            if not ok_manifest_upload:
                add_log(f"Sync templates — upload remote manifest failed: {manifest_upload_msg}")
                return False

            device_changed = uploaded > 0 or deleted > 0
            if device_changed:
                _, err = s.run([CMD_RESTART_XOCHITL])
                if err.strip():
                    add_log(f"Sync templates — restart xochitl: {err.strip()}")
                    return False

    except Exception as exc:
        add_log(f"Sync templates — SSH session failed: {exc}")
        return False

    add_log(
        f"Templates synced on '{selected_name}' "
        f"(uploaded={uploaded}, deleted_remote={deleted}, unchanged={diff['in_sync_count']}, "
        f"remote_manifest={remote_state}, xochitl_restarted={device_changed})"
    )
    return True
