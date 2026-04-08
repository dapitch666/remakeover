import json
import os
import shlex
from types import SimpleNamespace
from unittest.mock import patch

from src.manifest_templates import get_manifest_entry, load_manifest
from src.template_sync import (
    build_assumed_sync_status,
    compute_sync_status_from_cached_remote,
    refresh_cached_sync_status,
    sync_templates_to_tablet,
)
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
    assert payload["to_upload_modified_names"] == ["Check"]
    assert payload["to_upload_added_names"] == []
    assert payload["to_delete_remote_names"] == ["remote_only"]
    assert isinstance(payload.get("remote_manifest_snapshot"), dict)


def test_compute_sync_status_from_cached_remote_reports_added_and_deleted_names(tmp_path):
    _set_data_dir(tmp_path)

    save_json_template(
        "D1",
        "alpha.template",
        json.dumps({"name": "Alpha", "categories": ["Perso"]}),
    )
    add_template_entry("D1", "alpha.template", ["Perso"], "\ue9fe")

    remote_manifest = {
        "last_modified": "2026-04-08T12:00:00Z",
        "templates": {
            "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff": {
                "name": "Remote Ghost",
                "created_at": "2026-04-08T11:00:00Z",
                "sha256": "beef",
            }
        },
    }

    payload = compute_sync_status_from_cached_remote("D1", remote_manifest)

    assert payload["local_count"] == 1
    assert payload["remote_count"] == 1
    assert payload["to_upload_added_names"] == ["Alpha"]
    assert payload["to_upload_modified_names"] == []
    assert payload["to_delete_remote_names"] == ["Remote Ghost"]
    assert payload["remote_manifest_state"] == "cached_snapshot"


def test_build_assumed_sync_status_uses_local_manifest_as_cached_snapshot(tmp_path):
    _set_data_dir(tmp_path)

    save_json_template(
        "D1",
        "local_only.template",
        json.dumps({"name": "Local Only", "categories": ["Perso"]}),
    )
    add_template_entry("D1", "local_only.template", ["Perso"], "\ue9fe")

    payload = build_assumed_sync_status("D1", "assumed_after_sync")

    assert payload["local_count"] == 1
    assert payload["remote_count"] == 1
    assert payload["to_upload"] == []
    assert payload["to_delete_remote"] == []
    assert payload["remote_manifest_state"] == "assumed_after_sync"
    assert isinstance(payload.get("remote_manifest_snapshot"), dict)


def test_refresh_cached_sync_status_recomputes_from_snapshot(tmp_path):
    _set_data_dir(tmp_path)

    save_json_template(
        "D1",
        "one.template",
        json.dumps({"name": "One", "categories": ["Perso"]}),
    )
    add_template_entry("D1", "one.template", ["Perso"], "\ue9fe")

    snapshot = {
        "last_modified": "2026-04-08T12:00:00Z",
        "templates": {
            "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee": {
                "name": "Remote Only",
                "created_at": "2026-04-08T11:00:00Z",
                "sha256": "beef",
            }
        },
    }
    cached = {
        "local_count": 0,
        "remote_count": 1,
        "in_sync_count": 0,
        "to_upload": [],
        "to_delete_remote": [],
        "remote_manifest_snapshot": snapshot,
        "remote_manifest_state": "checked",
        "checked_at": "2026-04-08T12:00:00Z",
        "last_remote_check_at": "2026-04-08T12:00:00Z",
    }

    refreshed = refresh_cached_sync_status("D1", cached)

    assert refreshed is not None
    assert refreshed["local_count"] == 1
    assert refreshed["remote_count"] == 1
    assert refreshed["to_upload_added_names"] == ["One"]
    assert refreshed["to_delete_remote_names"] == ["Remote Only"]
    assert refreshed["last_remote_manifest_state"] == "checked"


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


def test_sync_thumbnail_cleanup_uses_single_quoted_rm_command(tmp_path):
    _set_data_dir(tmp_path)
    logs, add_log = _logger_bucket()

    filename = "quote test.template"
    save_json_template("D1", filename, json.dumps({"name": "Quote Test", "categories": ["Perso"]}))
    add_template_entry("D1", filename, ["Perso"], "\ue9fe")

    run_calls = []

    def _download(_ip, _pw, remote_path):
        if remote_path.endswith("/.manifest.json"):
            return None, "No such file"
        return None, "missing"

    def _run_cmd(_ip, _pw, commands):
        run_calls.append(commands)
        return "", ""

    with (
        patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
        patch("src.template_sync._ssh.download_file_ssh", side_effect=_download),
        patch("src.ssh.upload_file_ssh", return_value=(True, "ok")),
        patch("src.ssh.run_ssh_cmd", side_effect=_run_cmd),
        patch("src.templates.remove_remote_custom_templates", return_value=(True, "ok")),
    ):
        ok = sync_templates_to_tablet("D1", _device(), add_log)

    assert ok is True
    cleanup_calls = [
        call
        for call in run_calls
        if len(call) == 1 and call[0].startswith("rm -rf ") and ".thumbnails" in call[0]
    ]
    assert cleanup_calls
    cleanup_cmd = cleanup_calls[0][0]
    assert " && " not in cleanup_cmd
    template_uuid = _uuid_for_filename("D1", filename)
    assert template_uuid is not None
    expected_dir = f"/home/root/.local/share/remarkable/xochitl/{template_uuid}.thumbnails"
    assert cleanup_cmd == (f"rm -rf {shlex.quote(expected_dir)}")


def test_sync_thumbnail_cleanup_stderr_is_best_effort(tmp_path):
    _set_data_dir(tmp_path)
    logs, add_log = _logger_bucket()

    filename = "cleanup_warn.template"
    save_json_template(
        "D1",
        filename,
        json.dumps({"name": "Cleanup Warn", "categories": ["Perso"]}),
    )
    add_template_entry("D1", filename, ["Perso"], "\ue9fe")

    def _download(_ip, _pw, remote_path):
        if remote_path.endswith("/.manifest.json"):
            return None, "No such file"
        return None, "missing"

    def _run_cmd(_ip, _pw, commands):
        if (
            len(commands) == 1
            and commands[0].startswith("rm -rf ")
            and ".thumbnails" in commands[0]
        ):
            return "", "permission denied"
        return "", ""

    with (
        patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
        patch("src.template_sync._ssh.download_file_ssh", side_effect=_download),
        patch("src.ssh.upload_file_ssh", return_value=(True, "ok")),
        patch("src.ssh.run_ssh_cmd", side_effect=_run_cmd),
        patch("src.templates.remove_remote_custom_templates", return_value=(True, "ok")),
    ):
        ok = sync_templates_to_tablet("D1", _device(), add_log)

    assert ok is True
    assert any("cleanup thumbnails" in msg for msg in logs)
    assert any("permission denied" in msg for msg in logs)
