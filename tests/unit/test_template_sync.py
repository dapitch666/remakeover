"""Unit tests for src/template_sync.py (manifest-based synchronization)."""

from collections.abc import Callable
from unittest.mock import MagicMock, patch

from src.template_sync import sync_templates_to_tablet


def _device(ip: str = "10.0.0.1", password: str = "pw") -> MagicMock:
    dev = MagicMock()
    dev.ip = ip
    dev.password = password
    return dev


def _logs() -> tuple[list[str], Callable[[str], None]]:
    msgs: list[str] = []
    return msgs, msgs.append


class TestManifestSyncSuccess:
    def test_sync_success_uploads_pending_and_marks_synced(self, tmp_path):
        logs, add_log = _logs()
        dev = _device()

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "MyTpl.svg").write_text("<svg/>", encoding="utf-8")
        backup = tmp_path / "templates.backup.json"
        backup.write_text('{"templates": []}', encoding="utf-8")

        with (
            patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
            patch("src.templates.get_device_templates_dir", return_value=str(templates_dir)),
            patch("src.templates.get_device_templates_backup_path", return_value=str(backup)),
            patch(
                "src.templates.get_device_templates_json_path",
                return_value=str(tmp_path / "templates.json"),
            ),
            patch("src.templates.list_remote_custom_templates", return_value=(True, set())),
            patch(
                "src.template_sync.load_manifest",
                return_value={
                    "version": 1,
                    "lastSync": None,
                    "templates": [
                        {
                            "name": "MyTpl",
                            "filename": "MyTpl",
                            "iconCode": "\\ue9fe",
                            "categories": ["Perso"],
                            "syncStatus": "pending",
                        }
                    ],
                },
            ),
            patch(
                "src.template_sync.list_manifest_entries",
                return_value=[
                    {
                        "name": "MyTpl",
                        "filename": "MyTpl",
                        "iconCode": "\\ue9fe",
                        "categories": ["Perso"],
                        "syncStatus": "pending",
                    }
                ],
            ),
            patch("src.template_sync.get_manifest_entry", return_value={"filename": "MyTpl"}),
            patch("src.template_sync.mark_synced") as mock_mark,
            patch("src.ssh.upload_file_ssh", return_value=(True, "ok")) as mock_upload,
            patch("src.ssh.run_ssh_cmd", return_value=("missing", "")),
            patch("src.templates.remove_remote_custom_templates", return_value=(True, "ok")),
        ):
            ok = sync_templates_to_tablet("D1", dev, add_log)

        assert ok is True
        assert mock_mark.call_count == 1
        assert mock_upload.call_count >= 2  # pending file + templates.json

    def test_sync_without_restart_does_not_call_restart_cmd(self, tmp_path):
        logs, add_log = _logs()
        dev = _device()

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        backup = tmp_path / "templates.backup.json"
        backup.write_text('{"templates": []}', encoding="utf-8")

        with (
            patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
            patch("src.templates.get_device_templates_dir", return_value=str(templates_dir)),
            patch("src.templates.get_device_templates_backup_path", return_value=str(backup)),
            patch(
                "src.templates.get_device_templates_json_path",
                return_value=str(tmp_path / "templates.json"),
            ),
            patch("src.templates.list_remote_custom_templates", return_value=(True, set())),
            patch("src.template_sync.load_manifest", return_value={"templates": []}),
            patch("src.template_sync.list_manifest_entries", return_value=[]),
            patch("src.template_sync.mark_synced"),
            patch("src.ssh.upload_file_ssh", return_value=(True, "ok")),
            patch("src.ssh.run_ssh_cmd") as mock_cmd,
            patch("src.templates.remove_remote_custom_templates", return_value=(True, "ok")),
        ):
            ok = sync_templates_to_tablet("D1", dev, add_log, restart_xochitl=False)

        assert ok is True
        # Only symlink checks/repairs can run; no explicit restart command at the end.
        assert all("xochitl" not in str(call.args) for call in mock_cmd.call_args_list)


class TestManifestSyncFailures:
    def test_fails_when_ensure_remote_dirs_fails(self, tmp_path):
        logs, add_log = _logs()
        dev = _device()

        with patch("src.templates.ensure_remote_template_dirs", return_value=(False, "boom")):
            ok = sync_templates_to_tablet("D1", dev, add_log)

        assert ok is False
        assert any("ensure dirs" in m for m in logs)

    def test_fails_when_pending_upload_fails(self, tmp_path):
        logs, add_log = _logs()
        dev = _device()

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "MyTpl.svg").write_text("<svg/>", encoding="utf-8")
        backup = tmp_path / "templates.backup.json"
        backup.write_text('{"templates": []}', encoding="utf-8")

        with (
            patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
            patch("src.templates.get_device_templates_dir", return_value=str(templates_dir)),
            patch("src.templates.get_device_templates_backup_path", return_value=str(backup)),
            patch(
                "src.templates.get_device_templates_json_path",
                return_value=str(tmp_path / "templates.json"),
            ),
            patch("src.templates.list_remote_custom_templates", return_value=(True, set())),
            patch(
                "src.template_sync.load_manifest",
                return_value={"templates": [{"filename": "MyTpl", "syncStatus": "pending"}]},
            ),
            patch("src.template_sync.list_manifest_entries", return_value=[]),
            patch("src.ssh.upload_file_ssh", return_value=(False, "upload error")),
            patch("src.templates.remove_remote_custom_templates", return_value=(True, "ok")),
        ):
            ok = sync_templates_to_tablet("D1", dev, add_log)

        assert ok is False
        assert any("upload pending" in m for m in logs)


class TestOrphanHandling:
    def test_detects_orphan_and_upserts_manifest_entry(self, tmp_path):
        logs, add_log = _logs()
        dev = _device()

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        backup = tmp_path / "templates.backup.json"
        backup.write_text('{"templates": []}', encoding="utf-8")

        with (
            patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
            patch("src.templates.get_device_templates_dir", return_value=str(templates_dir)),
            patch("src.templates.get_device_templates_backup_path", return_value=str(backup)),
            patch(
                "src.templates.get_device_templates_json_path",
                return_value=str(tmp_path / "templates.json"),
            ),
            patch(
                "src.templates.list_remote_custom_templates",
                return_value=(True, {"orphan.template"}),
            ),
            patch("src.template_sync.list_manifest_entries", return_value=[]),
            patch("src.template_sync.load_manifest", return_value={"templates": []}),
            patch(
                "src.ssh.download_file_ssh", return_value=(b'{"categories": ["Grid", "Lines"]}', "")
            ),
            patch("src.templates.save_device_template") as mock_save_local,
            patch("src.template_sync.upsert_orphan_entry") as mock_orphan,
            patch("src.template_sync.mark_synced"),
            patch("src.ssh.upload_file_ssh", return_value=(True, "ok")),
            patch("src.ssh.run_ssh_cmd", return_value=("", "")),
            patch("src.templates.remove_remote_custom_templates", return_value=(True, "ok")),
        ):
            ok = sync_templates_to_tablet("D1", dev, add_log)

        assert ok is True
        assert mock_save_local.call_count == 1
        assert mock_save_local.call_args.args[0] == "D1"
        assert mock_save_local.call_args.args[2] == "orphan.template"
        assert mock_orphan.call_count == 1
        args = mock_orphan.call_args.args
        assert args[0] == "D1"
        assert args[1] == "orphan.template"
        assert args[2] == ["Grid", "Lines"]


class TestRebuildMetadataInference:
    def test_rebuild_prefers_local_templates_json_metadata_when_manifest_missing_fields(
        self, tmp_path
    ):
        logs, add_log = _logs()
        dev = _device()

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "MyTemplate.template").write_text(
            '{"categories": ["FromTemplate"]}',
            encoding="utf-8",
        )
        backup = tmp_path / "templates.backup.json"
        backup.write_text('{"templates": []}', encoding="utf-8")
        local_json = tmp_path / "templates.json"
        local_json.write_text(
            '{"templates": [{"name": "NameFromJson", "filename": "MyTemplate", "iconCode": "\\ue9ab", "categories": ["FromJson"]}]}',
            encoding="utf-8",
        )

        uploaded_payloads: list[tuple[str, bytes]] = []

        def _capture_upload(ip, pw, content, remote_path):
            uploaded_payloads.append((remote_path, content))
            return True, "ok"

        with (
            patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
            patch("src.templates.get_device_templates_dir", return_value=str(templates_dir)),
            patch("src.templates.get_device_templates_backup_path", return_value=str(backup)),
            patch("src.templates.get_device_templates_json_path", return_value=str(local_json)),
            patch("src.templates.list_remote_custom_templates", return_value=(True, set())),
            patch(
                "src.template_sync.load_manifest",
                return_value={
                    "templates": [
                        {
                            "filename": "MyTemplate",
                            "name": "",
                            "iconCode": "",
                            "categories": [],
                            "syncStatus": "synced",
                        }
                    ]
                },
            ),
            patch(
                "src.template_sync.list_manifest_entries",
                return_value=[
                    {
                        "filename": "MyTemplate",
                        "name": "",
                        "iconCode": "",
                        "categories": [],
                        "syncStatus": "synced",
                    }
                ],
            ),
            patch("src.template_sync.get_manifest_entry", return_value={"filename": "MyTemplate"}),
            patch("src.template_sync.mark_synced"),
            patch("src.ssh.upload_file_ssh", side_effect=_capture_upload),
            patch("src.ssh.run_ssh_cmd", return_value=("ok", "")),
            patch("src.templates.remove_remote_custom_templates", return_value=(True, "ok")),
        ):
            ok = sync_templates_to_tablet("D1", dev, add_log)

        assert ok is True
        json_upload = next(
            payload for path, payload in uploaded_payloads if path.endswith("templates.json")
        )
        data = __import__("json").loads(json_upload.decode("utf-8"))
        entry = data["templates"][0]
        assert entry["name"] == "NameFromJson"
        assert entry["iconCode"] == "\ue9ab"
        assert entry["categories"] == ["FromJson"]

    def test_rebuild_falls_back_to_template_json_categories(self, tmp_path):
        logs, add_log = _logs()
        dev = _device()

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "MyTemplate.template").write_text(
            '{"categories": ["Creative", "Grid"]}',
            encoding="utf-8",
        )
        backup = tmp_path / "templates.backup.json"
        backup.write_text('{"templates": []}', encoding="utf-8")
        local_json = tmp_path / "templates.json"
        local_json.write_text('{"templates": []}', encoding="utf-8")

        uploaded_payloads: list[tuple[str, bytes]] = []

        def _capture_upload(ip, pw, content, remote_path):
            uploaded_payloads.append((remote_path, content))
            return True, "ok"

        with (
            patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
            patch("src.templates.get_device_templates_dir", return_value=str(templates_dir)),
            patch("src.templates.get_device_templates_backup_path", return_value=str(backup)),
            patch("src.templates.get_device_templates_json_path", return_value=str(local_json)),
            patch("src.templates.list_remote_custom_templates", return_value=(True, set())),
            patch(
                "src.template_sync.load_manifest",
                return_value={
                    "templates": [
                        {
                            "filename": "MyTemplate",
                            "name": "",
                            "iconCode": "",
                            "categories": [],
                            "syncStatus": "synced",
                        }
                    ]
                },
            ),
            patch(
                "src.template_sync.list_manifest_entries",
                return_value=[
                    {
                        "filename": "MyTemplate",
                        "name": "",
                        "iconCode": "",
                        "categories": [],
                        "syncStatus": "synced",
                    }
                ],
            ),
            patch("src.template_sync.get_manifest_entry", return_value={"filename": "MyTemplate"}),
            patch("src.template_sync.mark_synced"),
            patch("src.ssh.upload_file_ssh", side_effect=_capture_upload),
            patch("src.ssh.run_ssh_cmd", return_value=("ok", "")),
            patch("src.templates.remove_remote_custom_templates", return_value=(True, "ok")),
        ):
            ok = sync_templates_to_tablet("D1", dev, add_log)

        assert ok is True
        json_upload = next(
            payload for path, payload in uploaded_payloads if path.endswith("templates.json")
        )
        data = __import__("json").loads(json_upload.decode("utf-8"))
        entry = data["templates"][0]
        assert entry["categories"] == ["Creative", "Grid"]
        assert entry["iconCode"] == "\ue9fe"
