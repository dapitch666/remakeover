"""High-level template sync orchestration.

Provides :func:`sync_templates_to_tablet`, which pushes all local SVG and
JSON templates plus ``templates.json`` to the device and restarts xochitl.

The function is intentionally side-effect-free with respect to Streamlit: it
receives an ``add_log`` callback so that callers can route messages to any
logging facility without creating a dependency on ``st.*``.
"""

import json
import os
import shlex

import src.ssh as _ssh
import src.templates as _tpl
from src.constants import (
    CMD_RESTART_XOCHITL,
    REMOTE_CUSTOM_TEMPLATES_DIR,
    REMOTE_TEMPLATES_DIR,
    REMOTE_TEMPLATES_JSON,
)
from src.manifest_templates import (
    SYNC_STATUS_DELETED,
    SYNC_STATUS_ORPHAN,
    SYNC_STATUS_PENDING,
    get_manifest_entry,
    list_manifest_entries,
    load_manifest,
    mark_synced,
    upsert_orphan_entry,
)


def _is_symlink_valid(ip: str, pw: str, filename: str) -> tuple[bool, str]:
    remote_link = f"{REMOTE_TEMPLATES_DIR}/{filename}"
    expected = f"{REMOTE_CUSTOM_TEMPLATES_DIR}/{filename}"
    cmd = (
        f"if [ -L {shlex.quote(remote_link)} ] && "
        f'[ "$(readlink {shlex.quote(remote_link)})" = {shlex.quote(expected)} ]; '
        "then echo ok; else echo missing; fi"
    )
    out, _ = _ssh.run_ssh_cmd(ip, pw, [cmd])
    state = out.strip()
    return state == "ok", state


def _rebuild_templates_json(selected_name: str) -> bytes | None:
    backup_path = _tpl.get_device_templates_backup_path(selected_name)
    if not os.path.exists(backup_path):
        return None

    with open(backup_path, encoding="utf-8") as f:
        backup_data = json.load(f)

    local_json_data: dict[str, object] = {"templates": []}
    local_json_path = _tpl.get_device_templates_json_path(selected_name)
    if os.path.exists(local_json_path):
        try:
            with open(local_json_path, encoding="utf-8") as jf:
                local_json_data = json.load(jf)
        except Exception:
            local_json_data = {"templates": []}

    local_meta_by_stem: dict[str, dict[str, object]] = {}
    raw_templates = local_json_data.get("templates", [])
    for item in raw_templates if isinstance(raw_templates, list) else []:
        if not isinstance(item, dict):
            continue
        stem = str(item.get("filename", ""))
        if stem:
            local_meta_by_stem[stem] = item

    templates_dir = _tpl.get_device_templates_dir(selected_name)

    stock_templates = backup_data.get("templates", [])
    stock_templates_list: list[dict[str, object]] = (
        stock_templates if isinstance(stock_templates, list) else []
    )
    custom_entries: list[dict[str, object]] = []
    for entry in list_manifest_entries(selected_name):
        status = entry.get("syncStatus")
        if status in {SYNC_STATUS_DELETED, SYNC_STATUS_ORPHAN}:
            continue

        stem = str(entry.get("filename", ""))
        if not stem:
            continue

        inferred = local_meta_by_stem.get(stem, {})

        raw_entry_cats = entry.get("categories", [])
        categories: list[str] = sorted(
            [
                c
                for c in (raw_entry_cats if isinstance(raw_entry_cats, list) else [])
                if isinstance(c, str)
            ]
        )
        if not categories:
            raw_inferred_cats = inferred.get("categories", [])
            categories = sorted(
                [
                    c
                    for c in (raw_inferred_cats if isinstance(raw_inferred_cats, list) else [])
                    if isinstance(c, str)
                ]
            )

        # Last-resort inference from local .template JSON metadata.
        if not categories:
            local_template_path = os.path.join(templates_dir, f"{stem}.template")
            if os.path.exists(local_template_path):
                try:
                    with open(local_template_path, "rb") as tf:
                        parsed = _tpl.extract_categories_from_template_content(tf.read())
                    if parsed is not None:
                        categories = sorted(parsed)
                except Exception:
                    pass

        if not categories:
            categories = ["Perso"]

        custom_entries.append(
            {
                "name": str(entry.get("name") or inferred.get("name") or stem),
                "filename": stem,
                "iconCode": str(entry.get("iconCode") or inferred.get("iconCode") or "\ue9fe"),
                "categories": categories,
            }
        )

    # Keep stock templates first (original order) then custom templates sorted by filename.
    stock_stems = {t.get("filename") for t in stock_templates_list}
    deduped_custom = [c for c in custom_entries if c.get("filename") not in stock_stems]
    deduped_custom.sort(key=lambda t: str(t.get("filename", "")).lower())

    payload = {"templates": stock_templates_list + deduped_custom}
    return json.dumps(payload, indent=2, ensure_ascii=True).encode("utf-8")


def _detect_remote_orphans(selected_name: str, ip: str, pw: str, add_log) -> int:
    ok, payload = _tpl.list_remote_custom_templates(ip, pw)
    if not ok:
        return 0
    assert isinstance(payload, set)

    manifest_stems = {
        str(entry.get("filename", ""))
        for entry in list_manifest_entries(selected_name)
        if entry.get("filename")
    }

    orphan_count = 0
    for remote_name in sorted(payload):
        remote_stem = os.path.splitext(remote_name)[0]
        if remote_stem in manifest_stems:
            continue

        content, err = _ssh.download_file_ssh(
            ip, pw, f"{REMOTE_CUSTOM_TEMPLATES_DIR}/{remote_name}"
        )
        if content is None:
            add_log(f"Orphan detect — failed to download '{remote_name}': {err}")
            continue

        # Keep a local copy so orphan templates can be reviewed/edited before adoption.
        _tpl.save_device_template(selected_name, content, remote_name)

        categories = ["Perso"]
        if remote_name.lower().endswith(".template"):
            parsed = _tpl.extract_categories_from_template_content(content)
            if parsed is not None:
                categories = sorted(parsed)

        upsert_orphan_entry(selected_name, remote_name, categories)
        orphan_count += 1

    return orphan_count


def sync_templates_to_tablet(
    selected_name: str,
    device,
    add_log,
    force: bool = False,
    restart_xochitl: bool = True,
) -> bool:
    """Synchronize templates according to `manifest.json` and rebuild templates.json.

    Uses module-level references to ``src.templates`` and ``src.ssh`` so that
    unit tests can patch those modules in the normal way.

    Returns ``True`` on success, ``False`` if any step fails (error details are
    forwarded to ``add_log``).
    """
    ip = device.ip
    pw = device.password or ""

    # 1) Ensure directories exist.
    ok, msg = _tpl.ensure_remote_template_dirs(
        ip, pw, REMOTE_CUSTOM_TEMPLATES_DIR, REMOTE_TEMPLATES_DIR
    )
    if not ok:
        add_log(f"Sync templates — ensure dirs: {msg}")
        return False

    # 2) Detect orphans (remote custom templates not in manifest) and register them.
    orphan_count = _detect_remote_orphans(selected_name, ip, pw, add_log)

    manifest = load_manifest(selected_name)
    entries = manifest.get("templates", [])
    pending_entries = [e for e in entries if e.get("syncStatus") == SYNC_STATUS_PENDING]
    deleted_entries = [e for e in entries if e.get("syncStatus") == SYNC_STATUS_DELETED]
    synced_entries = [e for e in entries if e.get("syncStatus") == "synced"]

    # 3) Upload pending template files.
    sent = 0
    device_templates_dir = _tpl.get_device_templates_dir(selected_name)
    for entry in pending_entries:
        stem = str(entry.get("filename", ""))
        if not stem:
            continue

        local_file = None
        for ext in (".svg", ".template"):
            candidate = os.path.join(device_templates_dir, f"{stem}{ext}")
            if os.path.exists(candidate):
                local_file = candidate
                break
        if local_file is None:
            add_log(f"Sync templates — pending file missing locally: {stem}")
            continue

        with open(local_file, "rb") as f:
            content = f.read()
        ok, msg = _ssh.upload_file_ssh(
            ip, pw, content, f"{REMOTE_CUSTOM_TEMPLATES_DIR}/{os.path.basename(local_file)}"
        )
        if not ok:
            add_log(f"Sync templates — upload pending '{stem}': {msg}")
            return False
        sent += 1

    # 4) Ensure symlinks for pending and synced templates.
    repaired_symlinks = 0
    for entry in pending_entries + synced_entries:
        stem = str(entry.get("filename", ""))
        if not stem:
            continue
        manifest_entry = get_manifest_entry(selected_name, stem)
        if manifest_entry is None:
            continue

        filename = None
        for ext in (".svg", ".template"):
            candidate = f"{stem}{ext}"
            if os.path.exists(os.path.join(device_templates_dir, candidate)):
                filename = candidate
                break
        if filename is None:
            continue

        is_valid, _ = _is_symlink_valid(ip, pw, filename)
        if is_valid:
            continue

        cmd = (
            f"ln -sf {shlex.quote(f'{REMOTE_CUSTOM_TEMPLATES_DIR}/{filename}')} "
            f"{shlex.quote(f'{REMOTE_TEMPLATES_DIR}/{filename}')}"
        )
        try:
            _ssh.run_ssh_cmd(ip, pw, [cmd])
            repaired_symlinks += 1
        except Exception as e:
            add_log(f"Sync templates — symlink repair '{filename}': {e}")
            return False

    # 5) Remove templates marked deleted.
    removed = 0
    for entry in deleted_entries:
        stem = str(entry.get("filename", ""))
        if not stem:
            continue

        # Try both known extensions defensively.
        for ext in (".svg", ".template"):
            fname = f"{stem}{ext}"
            ok_rm, _ = _tpl.remove_remote_custom_templates(ip, pw, {fname})
            if ok_rm:
                removed += 1

    # 6) Rebuild and upload merged templates.json.
    json_content = _rebuild_templates_json(selected_name)
    if json_content is not None:
        ok, msg = _ssh.upload_file_ssh(ip, pw, json_content, REMOTE_TEMPLATES_JSON)
        if not ok:
            add_log(f"Sync templates — templates.json upload: {msg}")
            return False
        # Keep local templates.json aligned with what was uploaded.
        local_json_path = _tpl.get_device_templates_json_path(selected_name)
        with open(local_json_path, "wb") as f:
            f.write(json_content)
    else:
        local_json_path = _tpl.get_device_templates_json_path(selected_name)

    if restart_xochitl:
        try:
            _ssh.run_ssh_cmd(ip, pw, [CMD_RESTART_XOCHITL])
        except Exception as e:
            add_log(f"Sync templates — restart xochitl: {e}")
            return False

    # 7) Update manifest statuses.
    mark_synced(selected_name)
    mode = "forced" if force else "standard"
    restart_mode = "with restart" if restart_xochitl else "without restart"
    add_log(
        f"Templates synced on '{selected_name}' "
        f"[{mode}] "
        f"[{restart_mode}] "
        f"({sent} file(s) uploaded, {removed} file(s) removed, {repaired_symlinks} symlink(s) repaired, "
        f"{orphan_count} orphan(s) detected, "
        f"templates.json {'uploaded' if os.path.exists(local_json_path) else 'not found locally'})"
    )
    return True
