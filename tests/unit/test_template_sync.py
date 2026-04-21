import json
import os
import shlex
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch

from src.manifest_templates import get_manifest_entry, load_manifest
from src.models import Device
from src.template_sync import (
    _sort_pairs_by_name,
    build_assumed_sync_status,
    check_sync_status,
    compute_sync_status_from_cached_remote,
    fetch_and_init_templates,
    fetch_single_template_from_device,
    refresh_cached_sync_status,
    sync_templates_to_device,
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
    return Device(name="D1", ip="10.0.0.1", password="pw")


def _logger_bucket():
    logs = []

    def add_log(msg):
        logs.append(msg)

    return logs, add_log


# ---------------------------------------------------------------------------
# Session-level test helpers
# ---------------------------------------------------------------------------


class _FakeSession:
    """Lightweight stand-in for SshSession used in sync tests."""

    def __init__(self, remote_manifest_bytes=None, run_side_effect=None):
        self.uploaded: list[str] = []  # remote paths passed to upload(), in call order
        self.uploaded_content: dict[str, bytes] = {}  # path → bytes for content inspection
        self.run_calls: list[list[str]] = []  # command lists passed to run()
        self._remote_manifest_bytes = remote_manifest_bytes
        self._run_side_effect = run_side_effect  # callable(commands) -> (out, err)

    def download(self, path: str):
        if path.endswith("/.manifest.json"):
            if self._remote_manifest_bytes is None:
                return None, "No such file"
            return self._remote_manifest_bytes, ""
        return None, "missing"

    def upload(self, content: bytes, path: str):
        self.uploaded.append(path)
        self.uploaded_content[path] = content
        return True, "ok"

    def run(self, commands: list[str]):
        self.run_calls.append(commands)
        if self._run_side_effect:
            return self._run_side_effect(commands)
        return "", ""


def _patch_session(fake: _FakeSession):
    """Return a context-manager patch that injects *fake* as the SSH session."""

    @contextmanager
    def _cm(_device):
        yield fake

    return patch("src.template_sync._ssh.ssh_session", _cm)


# ---------------------------------------------------------------------------
# sync_templates_to_device tests
# ---------------------------------------------------------------------------


def test_sync_uploads_template_and_manifest_when_remote_manifest_is_missing(tmp_path):
    _set_data_dir(tmp_path)
    logs, add_log = _logger_bucket()

    filename = "sync_me.template"
    save_json_template("D1", filename, json.dumps({"name": "Sync Me", "categories": ["Perso"]}))
    add_template_entry("D1", filename)

    fake = _FakeSession(remote_manifest_bytes=None)  # missing → use default

    with _patch_session(fake):
        ok = sync_templates_to_device("D1", _device(), add_log)

    assert ok is True
    assert any(p.endswith(".template") for p in fake.uploaded)
    assert any(p.endswith(".metadata") for p in fake.uploaded)
    assert any(p.endswith(".content") for p in fake.uploaded)
    assert any(p.endswith("/.manifest.json") for p in fake.uploaded)

    template_uuid = _uuid_for_filename("D1", filename)
    assert template_uuid is not None
    entry = get_manifest_entry("D1", template_uuid)
    assert entry is not None
    assert isinstance(entry.get("uuid"), str)
    assert entry.get("sha256")
    assert any("Templates synced" in msg for msg in logs)

    # --- payload content assertions ---
    # The manifest entry's name field is the source of truth for what gets uploaded.
    # Asserting against it (rather than a literal string) tests the invariant that
    # the template JSON, metadata visibleName, and manifest are all consistent.
    manifest_name = entry["name"]

    # .template bytes must carry the name that the manifest records.
    tpl_path = next(p for p in fake.uploaded if p.endswith(".template"))
    uploaded_tpl = json.loads(fake.uploaded_content[tpl_path].decode("utf-8"))
    assert uploaded_tpl["name"] == manifest_name

    # .metadata bytes must carry the same visible name and the rmMethods type tag.
    meta_path = next(p for p in fake.uploaded if p.endswith(".metadata"))
    uploaded_meta = json.loads(fake.uploaded_content[meta_path].decode("utf-8"))
    assert uploaded_meta["visibleName"] == manifest_name
    assert uploaded_meta["type"] == "TemplateType"

    # The manifest pushed to the device must list the template UUID.
    manifest_path = next(p for p in fake.uploaded if p.endswith("/.manifest.json"))
    pushed_manifest = json.loads(fake.uploaded_content[manifest_path].decode("utf-8"))
    assert template_uuid in pushed_manifest.get("templates", {})


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

    fake = _FakeSession(remote_manifest_bytes=json.dumps(remote_manifest).encode())

    with _patch_session(fake):
        ok = sync_templates_to_device("D1", _device(), add_log)

    assert ok is True
    rm_calls = [cmds[0] for cmds in fake.run_calls if cmds and cmds[0].startswith("rm -f ")]
    assert any(remote_uuid in cmd for cmd in rm_calls)


def test_sync_check_reports_manifest_diff(tmp_path):
    _set_data_dir(tmp_path)
    logs, add_log = _logger_bucket()

    filename = "check.template"
    save_json_template("D1", filename, json.dumps({"name": "Check", "categories": ["Perso"]}))
    add_template_entry("D1", filename)

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

    with patch(
        "src.template_sync._ssh.download_file_ssh",
        return_value=(json.dumps(remote_manifest).encode("utf-8"), ""),
    ):
        ok, payload = check_sync_status(_device(), add_log)

    assert ok is True
    assert isinstance(payload, dict)
    assert payload["local_count"] == 1
    assert payload["remote_count"] == 2
    assert len(payload["to_upload"]) == 1
    assert len(payload["to_delete_remote"]) == 1
    assert payload["to_upload_modified_uuids"] == [local_uuid]
    assert payload["to_upload_added_uuids"] == []
    assert payload["to_delete_remote_uuids"] == ["aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"]
    assert isinstance(payload.get("remote_manifest_snapshot"), dict)
    # name-by-uuid maps
    assert payload["to_upload_modified_name_by_uuid"].get(local_uuid) == "check"
    assert payload["to_upload_added_name_by_uuid"] == {}
    assert (
        payload["to_delete_remote_name_by_uuid"].get("aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee")
        == "remote_only"
    )


def test_compute_sync_status_from_cached_remote_reports_added_and_deleted_names(tmp_path):
    _set_data_dir(tmp_path)

    save_json_template(
        "D1",
        "alpha.template",
        json.dumps({"name": "Alpha", "categories": ["Perso"]}),
    )
    add_template_entry("D1", "alpha.template")

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

    alpha_uuid = _uuid_for_filename("D1", "alpha.template")
    assert alpha_uuid is not None

    payload = compute_sync_status_from_cached_remote("D1", remote_manifest)

    assert payload["local_count"] == 1
    assert payload["remote_count"] == 1
    assert payload["to_upload_added_uuids"] == [alpha_uuid]
    assert payload["to_upload_modified_uuids"] == []
    assert payload["to_delete_remote_uuids"] == ["bbbbbbbb-cccc-4ddd-8eee-ffffffffffff"]
    assert payload["remote_manifest_state"] == "cached_snapshot"
    # name-by-uuid maps
    assert payload["to_upload_added_name_by_uuid"].get(alpha_uuid) == "alpha"
    assert payload["to_upload_modified_name_by_uuid"] == {}
    assert (
        payload["to_delete_remote_name_by_uuid"].get("bbbbbbbb-cccc-4ddd-8eee-ffffffffffff")
        == "Remote Ghost"
    )


def test_build_assumed_sync_status_uses_local_manifest_as_cached_snapshot(tmp_path):
    _set_data_dir(tmp_path)

    save_json_template(
        "D1",
        "local_only.template",
        json.dumps({"name": "Local Only", "categories": ["Perso"]}),
    )
    add_template_entry("D1", "local_only.template")

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
    add_template_entry("D1", "one.template")

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
    assert len(refreshed["to_upload_added_uuids"]) == 1
    assert refreshed["to_upload_added_name_by_uuid"][refreshed["to_upload_added_uuids"][0]] == "one"
    assert (
        refreshed["to_delete_remote_name_by_uuid"].get(refreshed["to_delete_remote_uuids"][0])
        == "Remote Only"
    )
    assert refreshed["last_remote_manifest_state"] == "checked"


def test_sync_does_not_refresh_local_manifest(tmp_path):
    _set_data_dir(tmp_path)
    logs, add_log = _logger_bucket()

    filename = "no_refresh_needed.template"
    save_json_template("D1", filename, json.dumps({"name": "No Refresh", "categories": []}))
    add_template_entry("D1", filename)

    fake = _FakeSession(remote_manifest_bytes=None)

    with (
        _patch_session(fake),
        patch("src.templates.refresh_local_manifest", side_effect=AssertionError("unexpected")),
    ):
        ok = sync_templates_to_device("D1", _device(), add_log)

    assert ok is True
    assert any("Templates synced" in msg for msg in logs)


def test_sync_thumbnail_cleanup_uses_single_quoted_rm_command(tmp_path):
    _set_data_dir(tmp_path)
    logs, add_log = _logger_bucket()

    filename = "quote test.template"
    save_json_template("D1", filename, json.dumps({"name": "Quote Test", "categories": ["Perso"]}))
    add_template_entry("D1", filename)

    fake = _FakeSession(remote_manifest_bytes=None)

    with _patch_session(fake):
        ok = sync_templates_to_device("D1", _device(), add_log)

    assert ok is True
    cleanup_calls = [
        cmds
        for cmds in fake.run_calls
        if len(cmds) == 1 and cmds[0].startswith("rm -rf ") and ".thumbnails" in cmds[0]
    ]
    assert cleanup_calls
    cleanup_cmd = cleanup_calls[0][0]
    assert " && " not in cleanup_cmd
    template_uuid = _uuid_for_filename("D1", filename)
    assert template_uuid is not None
    expected_dir = f"/home/root/.local/share/remarkable/xochitl/{template_uuid}.thumbnails"
    assert cleanup_cmd == f"rm -rf {shlex.quote(expected_dir)}"


def test_sync_thumbnail_cleanup_stderr_is_best_effort(tmp_path):
    _set_data_dir(tmp_path)
    logs, add_log = _logger_bucket()

    filename = "cleanup_warn.template"
    save_json_template(
        "D1",
        filename,
        json.dumps({"name": "Cleanup Warn", "categories": ["Perso"]}),
    )
    add_template_entry("D1", filename)

    def _run_side_effect(commands):
        if (
            len(commands) == 1
            and commands[0].startswith("rm -rf ")
            and ".thumbnails" in commands[0]
        ):
            return "", "permission denied"
        return "", ""

    fake = _FakeSession(remote_manifest_bytes=None, run_side_effect=_run_side_effect)

    with _patch_session(fake):
        ok = sync_templates_to_device("D1", _device(), add_log)

    assert ok is True
    assert any("cleanup thumbnails" in msg for msg in logs)
    assert any("permission denied" in msg for msg in logs)


def test_sync_does_not_restart_xochitl_when_nothing_changed(tmp_path):
    """When local and remote are already in sync, xochitl must NOT be restarted."""
    _set_data_dir(tmp_path)
    logs, add_log = _logger_bucket()

    filename = "already_synced.template"
    save_json_template(
        "D1", filename, json.dumps({"name": "Already Synced", "categories": ["Perso"]})
    )
    add_template_entry("D1", filename)

    local_manifest = load_manifest("D1")
    # Build a remote manifest that is identical to the local one
    fake = _FakeSession(remote_manifest_bytes=json.dumps(local_manifest).encode())

    with _patch_session(fake):
        ok = sync_templates_to_device("D1", _device(), add_log)

    assert ok is True
    restart_calls = [cmds for cmds in fake.run_calls if any("restart xochitl" in c for c in cmds)]
    assert not restart_calls, "xochitl should not be restarted when nothing changed"
    assert any("xochitl_restarted=False" in msg for msg in logs)


def test_sync_restarts_xochitl_when_templates_uploaded(tmp_path):
    """When templates are uploaded to the device, xochitl must be restarted."""
    _set_data_dir(tmp_path)
    logs, add_log = _logger_bucket()

    filename = "new_one.template"
    save_json_template("D1", filename, json.dumps({"name": "New One", "categories": ["Perso"]}))
    add_template_entry("D1", filename)

    fake = _FakeSession(remote_manifest_bytes=None)  # missing → upload needed

    with _patch_session(fake):
        ok = sync_templates_to_device("D1", _device(), add_log)

    assert ok is True
    restart_calls = [cmds for cmds in fake.run_calls if any("restart xochitl" in c for c in cmds)]
    assert restart_calls, "xochitl should be restarted when templates were uploaded"
    assert any("xochitl_restarted=True" in msg for msg in logs)


def test_sync_ssh_connection_error_returns_false_and_logs(tmp_path):
    """OSError from ssh_session (e.g. unreachable host) must not bubble up."""
    _set_data_dir(tmp_path)
    logs, add_log = _logger_bucket()

    @contextmanager
    def _failing_session(_device):
        raise OSError("Connection refused")
        yield  # noqa: unreachable

    with patch("src.template_sync._ssh.ssh_session", _failing_session):
        ok = sync_templates_to_device("D1", _device(), add_log)

    assert ok is False
    assert any("Connection refused" in msg for msg in logs)


def test_fetch_single_template_from_device_downloads_and_saves(tmp_path):
    _set_data_dir(tmp_path)

    remote_uuid = "cccccccc-dddd-4eee-8fff-000000000001"
    metadata = {
        "type": "TemplateType",
        "visibleName": "My Remote Template",
        "createdTime": "1712574000000",
    }
    payload = {"name": "My Remote Template", "categories": ["Perso"]}

    def _download(_device, remote_path):
        if remote_path.endswith(".metadata"):
            return json.dumps(metadata).encode("utf-8"), ""
        if remote_path.endswith(".template"):
            return json.dumps(payload).encode("utf-8"), ""
        if remote_path.endswith(".content"):
            return b"{}", ""
        return None, "missing"

    with (
        patch("src.template_sync._ssh.download_file_ssh", side_effect=_download),
        patch("src.ssh.upload_file_ssh") as mock_upload,
    ):
        ok, msg = fetch_single_template_from_device(_device(), remote_uuid)

    assert ok is True
    assert "My Remote Template" in msg
    mock_upload.assert_not_called()  # recovering a remote-only template must not push the manifest

    from src.manifest_templates import get_manifest_entry

    entry = get_manifest_entry("D1", remote_uuid)
    assert entry is not None
    assert entry["name"] == "My Remote Template"
    assert entry["sha256"]


def test_fetch_single_template_from_device_fails_gracefully_on_metadata_error(tmp_path):
    _set_data_dir(tmp_path)

    remote_uuid = "cccccccc-dddd-4eee-8fff-000000000002"

    with patch(
        "src.template_sync._ssh.download_file_ssh",
        return_value=(None, "connection refused"),
    ):
        ok, msg = fetch_single_template_from_device(_device(), remote_uuid)

    assert ok is False
    assert "metadata_download_failed" in msg


def test_fetch_single_template_rejects_non_template_type(tmp_path):
    _set_data_dir(tmp_path)

    remote_uuid = "cccccccc-dddd-4eee-8fff-000000000003"
    metadata = {"type": "DocumentType", "visibleName": "Not A Template"}
    payload = {"name": "Not A Template"}

    def _download(_device, remote_path):
        if remote_path.endswith(".metadata"):
            return json.dumps(metadata).encode("utf-8"), ""
        if remote_path.endswith(".template"):
            return json.dumps(payload).encode("utf-8"), ""
        return b"{}", ""

    with (
        patch("src.template_sync._ssh.download_file_ssh", side_effect=_download),
        patch("src.ssh.upload_file_ssh", return_value=(True, "ok")),
    ):
        ok, msg = fetch_single_template_from_device(_device(), remote_uuid)

    assert ok is False
    assert "not_a_template" in msg


def test_sort_pairs_by_name_is_case_insensitive():
    pairs = [("Zeta", "uuid-z"), ("alpha", "uuid-a"), ("Beta", "uuid-b")]
    result = _sort_pairs_by_name(pairs)
    assert [name for name, _ in result] == ["alpha", "Beta", "Zeta"]


def test_enrich_diff_preserves_both_uuids_for_same_template_name(tmp_path):
    """Two uploads with the same display name must both appear as separate UUIDs."""
    _set_data_dir(tmp_path)

    for filename in ("dup1.template", "dup2.template"):
        save_json_template("D1", filename, json.dumps({"name": "Duplicate", "categories": []}))
        # preferred_name forces the manifest to store the given display name
        # rather than the filename stem ("dup1" / "dup2").
        add_template_entry("D1", filename, preferred_name="Duplicate")

    from src.manifest_templates import load_manifest

    templates = load_manifest("D1").get("templates", {})
    all_uuids = set(templates.keys())
    assert len(all_uuids) == 2, "both entries must be in the manifest"

    # Remote is empty → both are "added" (missing_remote)
    payload = compute_sync_status_from_cached_remote("D1", {"templates": {}})

    added_uuids = payload["to_upload_added_uuids"]
    name_map = payload["to_upload_added_name_by_uuid"]

    assert set(added_uuids) == all_uuids, "both UUIDs must be present"
    assert all(name_map[u] == "Duplicate" for u in added_uuids), "both map to the same name"


# ---------------------------------------------------------------------------
# sync delete — precise UUID targeting
# ---------------------------------------------------------------------------


def test_sync_delete_targets_exact_uuid_paths_and_not_local_uuid(tmp_path):
    """rm -f must target all three extensions of the ghost UUID and never touch the local UUID."""
    _set_data_dir(tmp_path)
    logs, add_log = _logger_bucket()

    # Create a local template so its UUID appears in the local manifest.
    save_json_template("D1", "keeper.template", json.dumps({"name": "Keeper", "categories": []}))
    add_template_entry("D1", "keeper.template")
    local_manifest = load_manifest("D1")
    local_uuid = next(iter(local_manifest["templates"]))

    # Remote manifest: local template in sync (same sha256) + one ghost UUID to delete.
    ghost_uuid = "deadbeef-dead-4bee-8fde-adbeefdeadbe"
    remote_manifest = {
        "last_modified": "2026-04-20T10:00:00Z",
        "templates": {
            local_uuid: local_manifest["templates"][local_uuid],
            ghost_uuid: {"name": "Ghost", "created_at": "2026-04-20T09:00:00Z", "sha256": "old"},
        },
    }

    fake = _FakeSession(remote_manifest_bytes=json.dumps(remote_manifest).encode())
    with _patch_session(fake):
        ok = sync_templates_to_device("D1", _device(), add_log)

    assert ok is True

    rm_calls = [cmds[0] for cmds in fake.run_calls if cmds and cmds[0].startswith("rm -f ")]
    assert rm_calls, "expected at least one rm -f call"
    rm_cmd = rm_calls[0]

    from src.constants import REMOTE_XOCHITL_DATA_DIR

    for ext in (".template", ".metadata", ".content"):
        expected_quoted = shlex.quote(f"{REMOTE_XOCHITL_DATA_DIR}/{ghost_uuid}{ext}")
        assert expected_quoted in rm_cmd, f"expected {expected_quoted} in rm command"

    assert local_uuid not in rm_cmd, "local (in-sync) UUID must never appear in the delete command"


# ---------------------------------------------------------------------------
# fetch_and_init_templates — happy path and overwrite_backup
# ---------------------------------------------------------------------------


def test_fetch_and_init_templates_saves_files_and_builds_manifest(tmp_path):
    """Happy path: remote templates are downloaded, saved to disk, and manifest is populated."""
    _set_data_dir(tmp_path)

    remote_uuid = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    metadata = {
        "type": "TemplateType",
        "visibleName": "Pulled Template",
        "createdTime": "1712574000000",
    }
    template_payload = {"name": "Pulled Template", "categories": ["Lines"]}

    def _download(_device, remote_path):
        if remote_path.endswith(f"{remote_uuid}.metadata"):
            return json.dumps(metadata).encode("utf-8"), ""
        if remote_path.endswith(f"{remote_uuid}.template"):
            return json.dumps(template_payload).encode("utf-8"), ""
        if remote_path.endswith(f"{remote_uuid}.content"):
            return b"{}", ""
        return None, "missing"

    with (
        patch("src.templates.list_remote_custom_templates", return_value=(True, [remote_uuid])),
        patch("src.template_sync._ssh.download_file_ssh", side_effect=_download),
        patch("src.template_sync._ssh.upload_file_ssh", return_value=(True, "ok")),
    ):
        ok, msg = fetch_and_init_templates(_device())

    assert ok is True
    assert "1 template" in msg

    from src.manifest_templates import get_manifest_entry
    from src.templates import triplet_paths

    paths = triplet_paths("D1", remote_uuid)
    assert os.path.exists(paths["template"]), ".template file must exist on disk"
    assert os.path.exists(paths["metadata"]), ".metadata file must exist on disk"

    with open(paths["template"], encoding="utf-8") as f:
        saved_payload = json.loads(f.read())
    assert saved_payload["name"] == "Pulled Template"

    entry = get_manifest_entry("D1", remote_uuid)
    assert entry is not None
    assert entry["name"] == "Pulled Template"
    assert entry["sha256"], "sha256 must be computed and stored"


def test_fetch_and_init_templates_overwrite_backup_clears_existing_files(tmp_path):
    """overwrite_backup=True must delete pre-existing local template files before pulling."""
    _set_data_dir(tmp_path)

    # Write a local template that should be wiped.
    save_json_template("D1", "stale.template", json.dumps({"name": "Stale"}))
    add_template_entry("D1", "stale.template")
    stale_manifest = load_manifest("D1")
    stale_uuid = next(iter(stale_manifest["templates"]))

    from src.templates import triplet_paths

    stale_paths = triplet_paths("D1", stale_uuid)
    assert os.path.exists(stale_paths["template"]), "pre-condition: stale file must exist"

    # Remote returns nothing so we can focus purely on the wipe.
    with (
        patch("src.templates.list_remote_custom_templates", return_value=(True, [])),
        patch("src.template_sync._ssh.upload_file_ssh", return_value=(True, "ok")),
    ):
        ok, msg = fetch_and_init_templates(_device(), overwrite_backup=True)

    assert ok is True
    assert not os.path.exists(stale_paths["template"]), "stale .template must be deleted"
    assert not load_manifest("D1").get("templates"), (
        "manifest must be empty after wipe with no remote templates"
    )
