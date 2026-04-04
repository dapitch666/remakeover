import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from src.manifest_templates import get_manifest_entry, load_manifest
from src.template_sync import sync_templates_to_tablet
from src.templates import add_template_entry, save_json_template


class _Device(SimpleNamespace):
    pass


def _set_data_dir(tmp_path):
    os.environ["RM_DATA_DIR"] = str(tmp_path)


def _uuid_for_filename(device_name: str, filename: str) -> str | None:
    stem = os.path.splitext(filename)[0]
    templates = load_manifest(device_name).get("templates", {})
    if not isinstance(templates, dict):
        return None
    for template_uuid, entry in templates.items():
        if isinstance(template_uuid, str) and isinstance(entry, dict) and entry.get("name") == stem:
            return template_uuid
    if len(templates) == 1:
        only_uuid = next(iter(templates.keys()))
        return only_uuid if isinstance(only_uuid, str) else None
    return None


def _device():
    return _Device(ip="10.0.0.1", password="pw")


def _logger_bucket():
    logs = []

    def add_log(msg):
        logs.append(msg)

    return logs, add_log


def test_sync_uploads_template_and_manifest_when_remote_manifest_is_missing(tmp_path):
    _set_data_dir(tmp_path)
    logs, add_log = _logger_bucket()

    filename = "sync_me.template"
    save_json_template("D1", filename, json.dumps({"name": "Sync Me", "categories": ["Perso"]}))
    add_template_entry("D1", filename, ["Perso"], "\ue9fe")

    uploaded_paths = []

    def _upload(_ip, _pw, _content, remote_path):
        uploaded_paths.append(remote_path)
        return True, "ok"

    def _download(_ip, _pw, remote_path):
        if remote_path.endswith("/.manifest.json"):
            return None, "No such file"
        return None, "missing"

    with (
        patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
        patch("src.template_sync._ssh.download_file_ssh", side_effect=_download),
        patch("src.ssh.upload_file_ssh", side_effect=_upload),
        patch("src.ssh.run_ssh_cmd", return_value=("", "")),
        patch("src.templates.remove_remote_custom_templates", return_value=(True, "ok")),
    ):
        ok = sync_templates_to_tablet("D1", _device(), add_log)

    assert ok is True
    assert any(path.endswith(".template") for path in uploaded_paths)
    assert any(path.endswith(".metadata") for path in uploaded_paths)
    assert any(path.endswith(".content") for path in uploaded_paths)
    assert any(path.endswith("/.manifest.json") for path in uploaded_paths)

    template_uuid = _uuid_for_filename("D1", filename)
    assert template_uuid is not None
    entry = get_manifest_entry("D1", template_uuid)
    assert entry is not None
    assert isinstance(entry.get("uuid"), str)
    assert entry.get("sha256")
    assert any("Templates synced" in msg for msg in logs)


def test_sync_deletes_remote_entries_absent_from_local_manifest(tmp_path):
    _set_data_dir(tmp_path)
    logs, add_log = _logger_bucket()

    remote_uuid = "99999999-8888-4777-8666-555555555555"
    remote_manifest = {
        "last_modified": "2026-04-04T10:00:00Z",
        "templates": {
            remote_uuid: {
                "name": "Ghost",
                "created_at": "2026-04-04T09:00:00Z",
                "sha256": "deadbeef",
            }
        },
    }

    removed_payloads = []

    def _download(_ip, _pw, remote_path):
        if remote_path.endswith("/.manifest.json"):
            return json.dumps(remote_manifest).encode("utf-8"), ""
        return None, "missing"

    def _remove(_ip, _pw, filenames):
        removed_payloads.append(set(filenames))
        return True, "ok"

    with (
        patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
        patch("src.template_sync._ssh.download_file_ssh", side_effect=_download),
        patch("src.ssh.upload_file_ssh", return_value=(True, "ok")),
        patch("src.ssh.run_ssh_cmd", return_value=("", "")),
        patch("src.templates.remove_remote_custom_templates", side_effect=_remove),
    ):
        ok = sync_templates_to_tablet("D1", _device(), add_log)

    assert ok is True
    assert removed_payloads
    assert {remote_uuid} in removed_payloads


def test_sync_check_reports_manifest_diff(tmp_path):
    _set_data_dir(tmp_path)
    logs, add_log = _logger_bucket()

    filename = "check.template"
    save_json_template("D1", filename, json.dumps({"name": "Check", "categories": ["Perso"]}))
    add_template_entry("D1", filename, ["Perso"], "\ue9fe")

    template_uuid = _uuid_for_filename("D1", filename)
    assert template_uuid is not None
    local_entry = get_manifest_entry("D1", template_uuid)
    assert local_entry is not None
    local_uuid = local_entry["uuid"]

    remote_manifest = {
        "last_modified": "2026-04-04T10:00:00Z",
        "templates": {
            local_uuid: {
                "name": local_entry["name"],
                "created_at": local_entry["created_at"],
                "sha256": "0000different",
            },
            "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee": {
                "name": "remote_only",
                "created_at": "2026-04-04T09:00:00Z",
                "sha256": "1111",
            },
        },
    }

    from src.template_sync import check_sync_status

    with patch(
        "src.template_sync._ssh.download_file_ssh",
        return_value=(json.dumps(remote_manifest).encode("utf-8"), ""),
    ):
        ok, payload = check_sync_status("D1", _device(), add_log)

    assert ok is True
    assert isinstance(payload, dict)
    assert payload["local_count"] == 1
    assert payload["remote_count"] == 2
    assert len(payload["to_upload"]) == 1
    assert len(payload["to_delete_remote"]) == 1


def test_sync_removes_deleted_remote_uuid_triplet(tmp_path):
    # Legacy behavior removed: keep this test name to preserve intent coverage,
    # now validating that missing-local UUIDs are removed from tablet.
    _set_data_dir(tmp_path)
    logs, add_log = _logger_bucket()

    remote_uuid = "11111111-aaaa-4bbb-8ccc-222222222222"
    remote_manifest = {
        "last_modified": "2026-04-04T10:00:00Z",
        "templates": {
            remote_uuid: {
                "name": "Delete Me",
                "created_at": "2026-04-04T09:00:00Z",
                "sha256": "2222",
            }
        },
    }

    removed_payloads = []

    def _download(_ip, _pw, remote_path):
        if remote_path.endswith("/.manifest.json"):
            return json.dumps(remote_manifest).encode("utf-8"), ""
        return None, "missing"

    def _remove(_ip, _pw, filenames):
        removed_payloads.append(set(filenames))
        return True, "ok"

    with (
        patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
        patch("src.template_sync._ssh.download_file_ssh", side_effect=_download),
        patch("src.ssh.upload_file_ssh", return_value=(True, "ok")),
        patch("src.ssh.run_ssh_cmd", return_value=("", "")),
        patch("src.templates.remove_remote_custom_templates", side_effect=_remove),
    ):
        ok = sync_templates_to_tablet("D1", _device(), add_log)

    assert ok is True
    assert removed_payloads
    assert {remote_uuid} in removed_payloads


def test_sync_does_not_refresh_local_manifest(tmp_path):
    _set_data_dir(tmp_path)
    logs, add_log = _logger_bucket()

    filename = "no_refresh_needed.template"
    save_json_template("D1", filename, json.dumps({"name": "No Refresh", "categories": []}))
    add_template_entry("D1", filename, [], "\ue9fe")

    def _download(_ip, _pw, remote_path):
        if remote_path.endswith("/.manifest.json"):
            return None, "No such file"
        return None, "missing"

    with (
        patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
        patch("src.template_sync._ssh.download_file_ssh", side_effect=_download),
        patch("src.ssh.upload_file_ssh", return_value=(True, "ok")),
        patch("src.ssh.run_ssh_cmd", return_value=("", "")),
        patch("src.templates.remove_remote_custom_templates", return_value=(True, "ok")),
        patch("src.templates.refresh_local_manifest", side_effect=AssertionError("unexpected")),
    ):
        ok = sync_templates_to_tablet("D1", _device(), add_log)

    assert ok is True
    assert any("Templates synced" in msg for msg in logs)
