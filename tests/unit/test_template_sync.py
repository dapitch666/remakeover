"""Unit tests for src/template_sync.py.

These tests call sync_templates_to_tablet directly (no AppTest) so every
branch of the function is exercised without the overhead of running the full
Streamlit page.

Patches target src.templates.* and src.ssh.* — the module objects that
template_sync accesses via its module-level references (_tpl / _ssh).
"""

from collections.abc import Callable
from unittest.mock import MagicMock, patch

from src.template_sync import sync_templates_to_tablet

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_device(ip: str = "192.168.1.100", password: str = "secret") -> MagicMock:
    device = MagicMock()
    device.ip = ip
    device.password = password
    return device


def _logs() -> tuple[list[str], Callable[[str], None]]:
    """Return a fresh log list and its append function."""
    msgs: list[str] = []
    return msgs, msgs.append


# ---------------------------------------------------------------------------
# Happy-path tests
# ---------------------------------------------------------------------------


class TestSyncSuccess:
    def test_returns_true_when_all_steps_succeed(self, tmp_path):
        """Full success path: templates synced, True returned, synced marker written."""
        logs, add_log = _logs()
        device = _make_device()

        with (
            patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
            patch("src.templates.get_device_templates_dir", return_value=str(tmp_path / "tpl")),
            patch("src.templates.upload_template_svgs", return_value=2),
            patch("src.templates.symlink_templates_on_device", return_value=(True, "ok")),
            patch(
                "src.templates.get_device_templates_json_path",
                return_value=str(tmp_path / "t.json"),
            ),
            patch("src.ssh.upload_file_ssh", return_value=(True, "ok")),
            patch("src.ssh.run_ssh_cmd"),
            patch("src.templates.mark_templates_synced") as mock_mark,
        ):
            # Write a real JSON file so the upload branch is entered
            (tmp_path / "t.json").write_bytes(b'{"templates":[]}')
            result = sync_templates_to_tablet("D1", device, add_log)

        assert result is True
        mock_mark.assert_called_once_with("D1")
        assert any("D1" in m and "2 file(s)" in m for m in logs)

    def test_no_json_file_skips_json_upload(self, tmp_path):
        """When templates.json does not exist locally the upload step is skipped."""
        logs, add_log = _logs()
        device = _make_device()

        with (
            patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
            patch("src.templates.get_device_templates_dir", return_value=str(tmp_path / "tpl")),
            patch("src.templates.upload_template_svgs", return_value=0),
            # json path points to a file that does NOT exist
            patch(
                "src.templates.get_device_templates_json_path",
                return_value=str(tmp_path / "missing.json"),
            ),
            patch("src.ssh.upload_file_ssh") as mock_upload,
            patch("src.ssh.run_ssh_cmd"),
            patch("src.templates.mark_templates_synced"),
        ):
            result = sync_templates_to_tablet("D1", device, add_log)

        assert result is True
        mock_upload.assert_not_called()
        assert any("not found locally" in m for m in logs)

    def test_no_svgs_uploaded_skips_symlinks(self, tmp_path):
        """When no SVG files are uploaded, symlink_templates_on_device is not called."""
        logs, add_log = _logs()
        device = _make_device()

        with (
            patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
            patch("src.templates.get_device_templates_dir", return_value=str(tmp_path / "tpl")),
            patch("src.templates.upload_template_svgs", return_value=0),
            patch(
                "src.templates.get_device_templates_json_path",
                return_value=str(tmp_path / "missing.json"),
            ),
            patch("src.templates.symlink_templates_on_device") as mock_sym,
            patch("src.ssh.upload_file_ssh"),
            patch("src.ssh.run_ssh_cmd"),
            patch("src.templates.mark_templates_synced"),
        ):
            result = sync_templates_to_tablet("D1", device, add_log)

        assert result is True
        mock_sym.assert_not_called()

    def test_uses_device_credentials(self, tmp_path):
        """IP and password from the device object are forwarded to SSH calls."""
        logs, add_log = _logs()
        device = _make_device(ip="10.0.0.5", password="hunter2")

        with (
            patch(
                "src.templates.ensure_remote_template_dirs", return_value=(True, "ok")
            ) as mock_dirs,
            patch("src.templates.get_device_templates_dir", return_value=str(tmp_path / "tpl")),
            patch("src.templates.upload_template_svgs", return_value=0),
            patch(
                "src.templates.get_device_templates_json_path",
                return_value=str(tmp_path / "missing.json"),
            ),
            patch("src.ssh.run_ssh_cmd") as mock_cmd,
            patch("src.templates.mark_templates_synced"),
        ):
            sync_templates_to_tablet("D1", device, add_log)

        assert mock_dirs.call_args[0][0] == "10.0.0.5"
        assert mock_dirs.call_args[0][1] == "hunter2"
        assert mock_cmd.call_args[0][0] == "10.0.0.5"
        assert mock_cmd.call_args[0][1] == "hunter2"

    def test_device_with_none_password_uses_empty_string(self, tmp_path):
        """A device with password=None falls back to empty string (doesn't crash)."""
        logs, add_log = _logs()
        device = _make_device()
        device.password = None

        with (
            patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
            patch("src.templates.get_device_templates_dir", return_value=str(tmp_path / "tpl")),
            patch("src.templates.upload_template_svgs", return_value=0),
            patch(
                "src.templates.get_device_templates_json_path",
                return_value=str(tmp_path / "missing.json"),
            ),
            patch("src.ssh.run_ssh_cmd"),
            patch("src.templates.mark_templates_synced"),
        ):
            result = sync_templates_to_tablet("D1", device, add_log)

        assert result is True


# ---------------------------------------------------------------------------
# Failure-path tests
# ---------------------------------------------------------------------------


class TestSyncFailures:
    def test_ensure_dirs_failure_returns_false(self, tmp_path):
        """If ensure_remote_template_dirs fails, False is returned immediately."""
        logs, add_log = _logs()
        device = _make_device()

        with (
            patch(
                "src.templates.ensure_remote_template_dirs", return_value=(False, "conn refused")
            ),
            patch("src.templates.get_device_templates_dir", return_value=str(tmp_path)),
            patch("src.templates.upload_template_svgs") as mock_upload,
        ):
            result = sync_templates_to_tablet("D1", device, add_log)

        assert result is False
        mock_upload.assert_not_called()
        assert any("ensure dirs" in m for m in logs)

    def test_symlink_failure_returns_false(self, tmp_path):
        """If symlink step fails after uploading SVGs, False is returned."""
        logs, add_log = _logs()
        device = _make_device()

        with (
            patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
            patch("src.templates.get_device_templates_dir", return_value=str(tmp_path / "tpl")),
            patch("src.templates.upload_template_svgs", return_value=1),
            patch(
                "src.templates.symlink_templates_on_device", return_value=(False, "symlink error")
            ),
        ):
            result = sync_templates_to_tablet("D1", device, add_log)

        assert result is False
        assert any("symlinks" in m for m in logs)

    def test_json_upload_failure_returns_false(self, tmp_path):
        """If templates.json SSH upload fails, False is returned."""
        logs, add_log = _logs()
        device = _make_device()
        json_path = tmp_path / "t.json"
        json_path.write_bytes(b'{"templates":[]}')

        with (
            patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
            patch("src.templates.get_device_templates_dir", return_value=str(tmp_path / "tpl")),
            patch("src.templates.upload_template_svgs", return_value=0),
            patch("src.templates.get_device_templates_json_path", return_value=str(json_path)),
            patch("src.ssh.upload_file_ssh", return_value=(False, "SFTP error")),
            patch("src.templates.mark_templates_synced") as mock_mark,
        ):
            result = sync_templates_to_tablet("D1", device, add_log)

        assert result is False
        mock_mark.assert_not_called()
        assert any("templates.json upload" in m for m in logs)

    def test_restart_exception_returns_false(self, tmp_path):
        """If xochitl restart raises, False is returned and error is logged."""
        logs, add_log = _logs()
        device = _make_device()

        with (
            patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
            patch("src.templates.get_device_templates_dir", return_value=str(tmp_path / "tpl")),
            patch("src.templates.upload_template_svgs", return_value=0),
            patch(
                "src.templates.get_device_templates_json_path",
                return_value=str(tmp_path / "missing.json"),
            ),
            patch("src.ssh.run_ssh_cmd", side_effect=OSError("connection lost")),
            patch("src.templates.mark_templates_synced") as mock_mark,
        ):
            result = sync_templates_to_tablet("D1", device, add_log)

        assert result is False
        mock_mark.assert_not_called()
        assert any("restart xochitl" in m for m in logs)

    def test_mark_synced_not_called_on_ensure_dirs_failure(self, tmp_path):
        """mark_templates_synced is never called when an earlier step fails."""
        logs, add_log = _logs()
        device = _make_device()

        with (
            patch("src.templates.ensure_remote_template_dirs", return_value=(False, "err")),
            patch("src.templates.mark_templates_synced") as mock_mark,
            patch("src.templates.get_device_templates_dir", return_value=str(tmp_path)),
        ):
            sync_templates_to_tablet("D1", device, add_log)

        mock_mark.assert_not_called()
