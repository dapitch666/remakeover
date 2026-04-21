"""Tests for src/ssh.py — all tests use mocked paramiko, no real device needed."""

from unittest.mock import MagicMock, patch

import pytest

from src.models import Device
from src.ssh import (
    SshSession,
    detect_device_info,
    download_file_ssh,
    run_detection,
    run_ssh_cmd,
    ssh_session,
    upload_file_ssh,
)

IP = "192.168.1.42"
PW = "secret"
DEVICE = Device(name="test", ip=IP, password=PW)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _exec_response(stdout: bytes, stderr: bytes = b""):
    """Return a single (stdin, stdout, stderr) triple for exec_command side_effect."""
    out = MagicMock()
    out.read.return_value = stdout
    err = MagicMock()
    err.read.return_value = stderr
    return MagicMock(), out, err


def _make_exec(*responses: tuple[bytes, bytes]):
    """Return a side_effect callable that yields successive responses to exec_command."""
    it = iter(responses)

    def _exec(cmd, **kwargs):
        out_bytes, err_bytes = next(it)
        return _exec_response(out_bytes, err_bytes)

    return _exec


def _patched_client(instance: MagicMock):
    """Patch paramiko.SSHClient so that SSHClient() returns *instance*."""
    return patch("src.ssh.paramiko.SSHClient", return_value=instance)


# ---------------------------------------------------------------------------
# run_ssh_cmd
# ---------------------------------------------------------------------------


class TestRunSshCmd:
    def test_happy_path(self):
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec((b"hello\n", b""))
        with _patched_client(inst):
            out, err = run_ssh_cmd(DEVICE, ["echo hello"])
        assert out == "hello\n"
        assert err == ""

    def test_empty_commands_returns_empty(self):
        inst = MagicMock()
        with _patched_client(inst):
            out, err = run_ssh_cmd(DEVICE, [])
        assert out == "" and err == ""

    def test_exec_command_exception(self):
        inst = MagicMock()
        inst.exec_command.side_effect = OSError("exec error")
        with _patched_client(inst):
            out, err = run_ssh_cmd(DEVICE, ["bad cmd"])
        assert out == ""
        assert "exec error" in err

    def test_connect_error(self):
        inst = MagicMock()
        inst.connect.side_effect = OSError("timeout")
        with _patched_client(inst):
            out, err = run_ssh_cmd(DEVICE, ["ls"])
        assert out == ""
        assert "timeout" in err

    def test_multiple_commands_joined(self):
        """Multiple commands are joined with && and sent as one exec_command call."""
        inst = MagicMock()
        captured = []

        def _exec(cmd, **kwargs):
            captured.append(cmd)
            return _exec_response(b"done", b"")

        inst.exec_command.side_effect = _exec
        with _patched_client(inst):
            run_ssh_cmd(DEVICE, ["cmd1", "cmd2"])
        assert captured[0] == "cmd1 && cmd2"


# ---------------------------------------------------------------------------
# upload_file_ssh
# ---------------------------------------------------------------------------


class TestUploadFileSsh:
    @staticmethod
    def _make_sftp():
        sftp = MagicMock()
        # sftp.file() used as context manager — MagicMock handles __enter__/__exit__
        return sftp

    def test_happy_path(self):
        inst = MagicMock()
        sftp = self._make_sftp()
        inst.open_sftp.return_value = sftp
        with _patched_client(inst):
            ok, msg = upload_file_ssh(DEVICE, b"data", "/remote/path")
        assert ok is True
        assert msg == ""

    def test_sftp_write_error(self):
        inst = MagicMock()
        sftp = MagicMock()
        sftp.file.side_effect = OSError("disk full")
        inst.open_sftp.return_value = sftp
        with _patched_client(inst):
            ok, msg = upload_file_ssh(DEVICE, b"data", "/remote/path")
        assert ok is False
        assert "disk full" in msg

    def test_connect_error(self):
        inst = MagicMock()
        inst.connect.side_effect = OSError("no route")
        with _patched_client(inst):
            ok, msg = upload_file_ssh(DEVICE, b"data", "/remote/path")
        assert ok is False
        assert "no route" in msg


# ---------------------------------------------------------------------------
# download_file_ssh
# ---------------------------------------------------------------------------


class TestDownloadFileSsh:
    def test_happy_path(self):
        inst = MagicMock()
        sftp = MagicMock()
        fake_file = MagicMock()
        fake_file.__enter__ = lambda s: s
        fake_file.__exit__ = MagicMock(return_value=False)
        fake_file.read.return_value = b"file content"
        sftp.file.return_value = fake_file
        inst.open_sftp.return_value = sftp
        with _patched_client(inst):
            data, err = download_file_ssh(DEVICE, "/remote/file")
        assert data == b"file content"
        assert err == ""

    def test_connect_error_returns_none(self):
        inst = MagicMock()
        inst.connect.side_effect = OSError("timeout")
        with _patched_client(inst):
            data, err = download_file_ssh(DEVICE, "/remote/file")
        assert data is None
        assert "timeout" in err


# ---------------------------------------------------------------------------
# detect_device_info
# ---------------------------------------------------------------------------


class TestDetectDeviceInfo:
    def test_rm2_detected(self):
        """/sys/devices/soc0/machine value 'rm2' maps to 'reMarkable 2'."""
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"rm2", b""),
            (b"IMG_VERSION=3.5.2.1896", b""),
            (b"no", b""),
        )
        with _patched_client(inst):
            ok, device_type, fw, sleep, err = detect_device_info(DEVICE)
        assert ok is True
        assert device_type == "reMarkable 2"
        assert fw == "3.5.2.1896"
        assert sleep is False
        assert err == ""

    def test_rm1_detected(self):
        """/sys/devices/soc0/machine value 'rm1' maps to 'reMarkable 1'."""
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"rm1", b""),
            (b"IMG_VERSION=2.15.0.999", b""),
            (b"no", b""),
        )
        with _patched_client(inst):
            ok, device_type, fw, sleep, err = detect_device_info(DEVICE)
        assert ok is True
        assert device_type == "reMarkable 1"
        assert fw == "2.15.0.999"

    def test_ferrari_detected(self):
        """/sys/devices/soc0/machine value 'ferrari' maps to 'reMarkable Paper Pro'."""
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"ferrari", b""),
            (b"IMG_VERSION=4.0.0.100", b""),
            (b"no", b""),
        )
        with _patched_client(inst):
            ok, device_type, fw, sleep, err = detect_device_info(DEVICE)
        assert ok is True
        assert device_type == "reMarkable Paper Pro"

    def test_chiappa_detected(self):
        """/sys/devices/soc0/machine value 'chiappa' maps to 'reMarkable Paper Pro Move'."""
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"chiappa", b""),
            (b"IMG_VERSION=4.1.0.50", b""),
            (b"no", b""),
        )
        with _patched_client(inst):
            ok, device_type, fw, sleep, err = detect_device_info(DEVICE)
        assert ok is True
        assert device_type == "reMarkable Paper Pro Move"

    def test_firmware_version_quoted(self):
        """IMG_VERSION with surrounding quotes is stripped correctly."""
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"reMarkable rm2", b""),
            (b'IMG_VERSION="3.5.2.1896"', b""),
            (b"no", b""),
        )
        with _patched_client(inst):
            ok, _, fw, _, _ = detect_device_info(DEVICE)
        assert ok is True
        assert fw == "3.5.2.1896"

    def test_unknown_machine_returns_false(self):
        """Unrecognised machine string returns ok=False with a descriptive error."""
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"Raspberry Pi 4", b""),
            (b"IMG_VERSION=0.0.0", b""),
            (b"no", b""),
        )
        with _patched_client(inst):
            ok, device_type, fw, sleep, err = detect_device_info(DEVICE)
        assert ok is False
        assert device_type == ""
        assert sleep is False
        assert "Raspberry Pi 4" in err

    def test_empty_firmware_is_tolerated(self):
        """If grep returns nothing, firmware_version is '' but device_type still works."""
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"rm2", b""),
            (b"", b""),
            (b"no", b""),
        )
        with _patched_client(inst):
            ok, device_type, fw, sleep, err = detect_device_info(DEVICE)
        assert ok is True
        assert device_type == "reMarkable 2"
        assert fw == ""

    def test_connect_failure(self):
        """SSH connection error returns ok=False with error message."""
        inst = MagicMock()
        inst.connect.side_effect = OSError("Connection refused")
        with _patched_client(inst):
            ok, device_type, fw, sleep, err = detect_device_info(DEVICE)
        assert ok is False
        assert device_type == ""
        assert fw == ""
        assert sleep is False
        assert "Connection refused" in err

    def test_sleep_screen_enabled_detected(self):
        """When SleepScreenPath is present in xochitl.conf, sleep_screen_enabled is True."""
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"rm2", b""),
            (b"IMG_VERSION=3.5.2.1896", b""),
            (b"yes", b""),
        )
        with _patched_client(inst):
            ok, _, _, sleep, _ = detect_device_info(DEVICE)
        assert ok is True
        assert sleep is True

    def test_sleep_screen_disabled_detected(self):
        """When SleepScreenPath is absent from xochitl.conf, sleep_screen_enabled is False."""
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"rm2", b""),
            (b"IMG_VERSION=3.5.2.1896", b""),
            (b"no", b""),
        )
        with _patched_client(inst):
            ok, _, _, sleep, _ = detect_device_info(DEVICE)
        assert ok is True
        assert sleep is False


# ---------------------------------------------------------------------------
# run_detection
# ---------------------------------------------------------------------------


class TestRunDetection:
    def test_success(self):
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"rm2", b""),
            (b"IMG_VERSION=3.5.2", b""),
            (b"yes", b""),
        )
        with _patched_client(inst):
            result = run_detection(DEVICE)
        assert result["ok"] is True
        assert result["device_type"] == "reMarkable 2"
        assert result["firmware_version"] == "3.5.2"
        assert result["sleep_screen_enabled"] is True
        assert result["error"] == ""

    def test_failure_zeroes_out_fields(self):
        inst = MagicMock()
        inst.connect.side_effect = OSError("refused")
        with _patched_client(inst):
            result = run_detection(DEVICE)
        assert result["ok"] is False
        assert result["device_type"] == ""
        assert result["firmware_version"] == ""
        assert result["sleep_screen_enabled"] is False
        assert "refused" in result["error"]


# ---------------------------------------------------------------------------
# SshSession
# ---------------------------------------------------------------------------


class TestSshSession:
    def test_run_happy_path(self):
        client = MagicMock()
        client.exec_command.side_effect = _make_exec((b"output", b"err"))
        out, err = SshSession(client).run(["ls"])
        assert out == "output"
        assert err == "err"

    def test_run_empty_commands(self):
        client = MagicMock()
        out, err = SshSession(client).run([])
        assert out == "" and err == ""
        client.exec_command.assert_not_called()

    def test_run_exception(self):
        client = MagicMock()
        client.exec_command.side_effect = OSError("broken pipe")
        out, err = SshSession(client).run(["ls"])
        assert out == ""
        assert "broken pipe" in err

    def test_upload_happy_path(self):
        client = MagicMock()
        client.open_sftp.return_value = MagicMock()
        ok, msg = SshSession(client).upload(b"data", "/path/file")
        assert ok is True
        assert msg == ""

    def test_upload_error(self):
        client = MagicMock()
        sftp = MagicMock()
        sftp.file.side_effect = OSError("disk full")
        client.open_sftp.return_value = sftp
        ok, msg = SshSession(client).upload(b"data", "/path/file")
        assert ok is False
        assert "disk full" in msg

    def test_download_happy_path(self):
        client = MagicMock()
        sftp = MagicMock()
        fake_file = MagicMock()
        fake_file.__enter__ = lambda s: s
        fake_file.__exit__ = MagicMock(return_value=False)
        fake_file.read.return_value = b"content"
        sftp.file.return_value = fake_file
        client.open_sftp.return_value = sftp
        data, err = SshSession(client).download("/path/file")
        assert data == b"content"
        assert err == ""

    def test_download_error(self):
        client = MagicMock()
        sftp = MagicMock()
        sftp.file.side_effect = OSError("not found")
        client.open_sftp.return_value = sftp
        data, err = SshSession(client).download("/path/file")
        assert data is None
        assert "not found" in err

    def test_sftp_channel_is_lazy(self):
        """open_sftp is called only once even across multiple operations."""
        client = MagicMock()
        client.open_sftp.return_value = MagicMock()
        session = SshSession(client)
        session._sftp_channel()
        session._sftp_channel()
        client.open_sftp.assert_called_once()

    def test_close_closes_sftp(self):
        client = MagicMock()
        sftp = MagicMock()
        client.open_sftp.return_value = sftp
        session = SshSession(client)
        session._sftp_channel()
        session.close()
        sftp.close.assert_called_once()
        assert session._sftp is None

    def test_close_without_sftp_is_noop(self):
        session = SshSession(MagicMock())
        session.close()  # must not raise


# ---------------------------------------------------------------------------
# ssh_session context manager
# ---------------------------------------------------------------------------


class TestSshSessionContextManager:
    def test_yields_session(self):
        inst = MagicMock()
        with _patched_client(inst), ssh_session(DEVICE) as s:
            assert isinstance(s, SshSession)

    def test_connect_error_raises(self):
        inst = MagicMock()
        inst.connect.side_effect = OSError("refused")
        with _patched_client(inst), pytest.raises(OSError, match="refused"), ssh_session(DEVICE):
            pass
