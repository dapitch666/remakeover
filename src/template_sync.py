"""High-level synchronization based on local/remote template manifests."""

from __future__ import annotations

import json
import os
from typing import Any

import src.ssh as _ssh
import src.templates as _tpl
from src.constants import CMD_RESTART_XOCHITL, REMOTE_XOCHITL_DATA_DIR
from src.manifest_templates import load_manifest

REMOTE_MANIFEST_FILENAME = ".manifest.json"


def _remote_manifest_path() -> str:
    return f"{REMOTE_XOCHITL_DATA_DIR}/{REMOTE_MANIFEST_FILENAME}"


def _default_manifest() -> dict[str, Any]:
    return {"last_modified": None, "templates": {}}


def _normalize_manifest(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        return _default_manifest()

    templates_raw = data.get("templates", {})
    if not isinstance(templates_raw, dict):
        templates_raw = {}

    templates: dict[str, dict[str, str]] = {}
    for template_uuid, entry in templates_raw.items():
        if not isinstance(template_uuid, str) or not template_uuid:
            continue
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        created_at = str(entry.get("created_at") or "").strip()
        sha256 = str(entry.get("sha256") or "").strip().lower()
        if not name or not created_at or not sha256:
            continue
        templates[template_uuid] = {
            "name": name,
            "created_at": created_at,
            "sha256": sha256,
        }

    last_modified_raw = data.get("last_modified")
    last_modified = str(last_modified_raw).strip() if last_modified_raw else None
    return {"last_modified": last_modified, "templates": templates}


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


def check_sync_status(selected_name: str, device, add_log) -> tuple[bool, dict[str, Any] | str]:
    """Compare local and remote manifests without mutating local state."""
    ip = device.ip
    pw = device.password or ""

    _tpl.refresh_local_manifest(selected_name)
    local_manifest = load_manifest(selected_name)

    ok_remote, remote_manifest, status_msg = _fetch_remote_manifest(ip, pw)
    if not ok_remote:
        return False, status_msg

    result = _compare_manifests(local_manifest, remote_manifest)
    result["remote_manifest_state"] = status_msg

    add_log(
        f"Sync check on '{selected_name}' "
        f"(local={result['local_count']}, remote={result['remote_count']}, "
        f"upload={len(result['to_upload'])}, delete_remote={len(result['to_delete_remote'])})"
    )
    return True, result


def _find_local_template_filename(selected_name: str, stem: str) -> str | None:
    templates_dir = _tpl.get_device_templates_dir(selected_name)
    for ext in (".template", ".svg"):
        candidate = f"{stem}{ext}"
        if os.path.exists(os.path.join(templates_dir, candidate)):
            return candidate
    return None


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

    _tpl.refresh_local_manifest(selected_name)
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
        stem = str(local_entry.get("name") or "")
        if not stem:
            add_log(f"Sync templates — invalid local manifest entry for UUID {template_uuid}")
            return False

        local_filename = _find_local_template_filename(selected_name, stem)
        if local_filename is None:
            add_log(f"Sync templates — local file missing for '{stem}'")
            return False

        try:
            payload = json.loads(_tpl.load_json_template(selected_name, local_filename))
        except Exception as exc:
            add_log(f"Sync templates — invalid template JSON '{local_filename}': {exc}")
            return False

        payload = _tpl.ensure_template_payload_for_rmethods(payload)
        visible_name = str(local_entry.get("name") or stem)
        for ext, blob in _tpl.build_rmethods_triplet_payloads(payload, visible_name).items():
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
        uploaded += 1

    deleted = 0
    to_delete = {f"{template_uuid}.template" for template_uuid in diff["to_delete_remote"]}
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
