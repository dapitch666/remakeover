"""Tests for src/ssh.py — all tests use mocked paramiko, no real device needed."""

from unittest.mock import MagicMock, patch

# noinspection PyProtectedMember
from src.ssh import (
    _ensure_rw,
    detect_device_info,
    download_file_ssh,
    run_ssh_cmd,
    upload_file_ssh,
)

IP = "192.168.1.42"
PW = "secret"


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
# _ensure_rw
# ---------------------------------------------------------------------------


class TestEnsureRw:
    def test_already_rw(self):
        client = MagicMock()
        client.exec_command.side_effect = _make_exec((b"writable", b""))
        ok, msg = _ensure_rw(client)
        assert ok is True
        assert msg == "already_rw"

    def test_readonly_remounts_successfully(self):
        client = MagicMock()
        client.exec_command.side_effect = _make_exec(
            (b"readonly", b""),  # check → not writable
            (b"", b""),  # remount → no error
        )
        ok, msg = _ensure_rw(client)
        assert ok is True
        assert msg == "remounted"

    def test_readonly_remount_has_stderr(self):
        """Remount with stderr warning should still succeed."""
        client = MagicMock()
        client.exec_command.side_effect = _make_exec(
            (b"readonly", b""),
            (b"", b"some warning"),
        )
        ok, msg = _ensure_rw(client)
        assert ok is True
        assert msg == "remounted"

    def test_rw_check_exception_triggers_remount(self):
        """If exec_command raises during the check, assume readonly and try remount."""
        client = MagicMock()
        call_count = [0]

        def _exec(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("pipe broken")
            return _exec_response(b"", b"")

        client.exec_command.side_effect = _exec
        ok, msg = _ensure_rw(client)
        assert ok is True
        assert msg == "remounted"

    def test_remount_exception_returns_false(self):
        client = MagicMock()
        call_count = [0]

        def _exec(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _exec_response(b"readonly", b"")
            raise OSError("remount failed hard")

        client.exec_command.side_effect = _exec
        ok, msg = _ensure_rw(client)
        assert ok is False
        assert "remount failed hard" in msg


# ---------------------------------------------------------------------------
# run_ssh_cmd
# ---------------------------------------------------------------------------


class TestRunSshCmd:
    def test_happy_path_already_rw(self):
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"writable", b""),  # _ensure_rw check
            (b"hello\n", b""),  # actual command
        )
        with _patched_client(inst):
            out, err = run_ssh_cmd(IP, PW, ["echo hello"])
        assert out == "hello\n"
        assert err == ""

    def test_remount_then_exec(self):
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"readonly", b""),  # _ensure_rw → trigger remount
            (b"", b""),  # remount
            (b"ok", b""),  # actual command
        )
        with _patched_client(inst):
            out, err = run_ssh_cmd(IP, PW, ["ls"])
        assert out == "ok"

    def test_empty_commands_returns_empty(self):
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec((b"writable", b""))
        with _patched_client(inst):
            out, err = run_ssh_cmd(IP, PW, [])
        assert out == "" and err == ""

    def test_remount_failure_short_circuits(self):
        inst = MagicMock()
        call_count = [0]

        def _exec(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _exec_response(b"readonly", b"")
            raise OSError("cannot remount")

        inst.exec_command.side_effect = _exec
        with _patched_client(inst):
            out, err = run_ssh_cmd(IP, PW, ["ls"])
        assert out == ""
        assert "remount failed" in err

    def test_exec_command_exception(self):
        inst = MagicMock()
        call_count = [0]

        def _exec(cmd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return _exec_response(b"writable", b"")
            raise OSError("exec error")

        inst.exec_command.side_effect = _exec
        with _patched_client(inst):
            out, err = run_ssh_cmd(IP, PW, ["bad cmd"])
        assert out == ""
        assert "exec error" in err

    def test_connect_error(self):
        inst = MagicMock()
        inst.connect.side_effect = OSError("timeout")
        with _patched_client(inst):
            out, err = run_ssh_cmd(IP, PW, ["ls"])
        assert out == ""
        assert "timeout" in err

    def test_multiple_commands_joined(self):
        """Multiple commands are joined with && and sent as one exec_command call."""
        inst = MagicMock()
        captured = []

        def _exec(cmd, **kwargs):
            captured.append(cmd)
            return _exec_response(b"writable" if not captured[1:] else b"done", b"")

        inst.exec_command.side_effect = _exec
        with _patched_client(inst):
            run_ssh_cmd(IP, PW, ["cmd1", "cmd2"])
        assert captured[1] == "cmd1 && cmd2"


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
        inst.exec_command.side_effect = _make_exec((b"writable", b""))
        sftp = self._make_sftp()
        inst.open_sftp.return_value = sftp
        with _patched_client(inst):
            ok, msg = upload_file_ssh(IP, PW, b"data", "/remote/path")
        assert ok is True
        assert msg == "OK"

    def test_remount_failure(self):
        inst = MagicMock()
        call_count = [0]

        def _exec(cmd):
            call_count[0] += 1
            if call_count[0] == 1:
                return _exec_response(b"readonly", b"")
            raise OSError("remount error")

        inst.exec_command.side_effect = _exec
        with _patched_client(inst):
            ok, msg = upload_file_ssh(IP, PW, b"data", "/remote/path")
        assert ok is False
        assert "remount failed" in msg

    def test_sftp_write_error(self):
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec((b"writable", b""))
        sftp = MagicMock()
        sftp.file.side_effect = OSError("disk full")
        inst.open_sftp.return_value = sftp
        with _patched_client(inst):
            ok, msg = upload_file_ssh(IP, PW, b"data", "/remote/path")
        assert ok is False
        assert "disk full" in msg

    def test_connect_error(self):
        inst = MagicMock()
        inst.connect.side_effect = OSError("no route")
        with _patched_client(inst):
            ok, msg = upload_file_ssh(IP, PW, b"data", "/remote/path")
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
            data, err = download_file_ssh(IP, PW, "/remote/file")
        assert data == b"file content"
        assert err == ""

    def test_connect_error_returns_none(self):
        inst = MagicMock()
        inst.connect.side_effect = OSError("timeout")
        with _patched_client(inst):
            data, err = download_file_ssh(IP, PW, "/remote/file")
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
        )
        with _patched_client(inst):
            ok, device_type, fw, err = detect_device_info(IP, PW)
        assert ok is True
        assert device_type == "reMarkable 2"
        assert fw == "3.5.2.1896"
        assert err == ""

    def test_rm1_detected(self):
        """/sys/devices/soc0/machine value 'rm1' maps to 'reMarkable 1'."""
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"rm1", b""),
            (b"IMG_VERSION=2.15.0.999", b""),
        )
        with _patched_client(inst):
            ok, device_type, fw, err = detect_device_info(IP, PW)
        assert ok is True
        assert device_type == "reMarkable 1"
        assert fw == "2.15.0.999"

    def test_ferrari_detected(self):
        """/sys/devices/soc0/machine value 'ferrari' maps to 'reMarkable Paper Pro'."""
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"ferrari", b""),
            (b"IMG_VERSION=4.0.0.100", b""),
        )
        with _patched_client(inst):
            ok, device_type, fw, err = detect_device_info(IP, PW)
        assert ok is True
        assert device_type == "reMarkable Paper Pro"

    def test_chiappa_detected(self):
        """/sys/devices/soc0/machine value 'chiappa' maps to 'reMarkable Paper Pro Move'."""
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"chiappa", b""),
            (b"IMG_VERSION=4.1.0.50", b""),
        )
        with _patched_client(inst):
            ok, device_type, fw, err = detect_device_info(IP, PW)
        assert ok is True
        assert device_type == "reMarkable Paper Pro Move"

    def test_firmware_version_quoted(self):
        """IMG_VERSION with surrounding quotes is stripped correctly."""
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"reMarkable rm2", b""),
            (b'IMG_VERSION="3.5.2.1896"', b""),
        )
        with _patched_client(inst):
            ok, _, fw, _ = detect_device_info(IP, PW)
        assert ok is True
        assert fw == "3.5.2.1896"

    def test_unknown_machine_returns_false(self):
        """Unrecognised machine string returns ok=False with a descriptive error."""
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"Raspberry Pi 4", b""),
            (b"IMG_VERSION=0.0.0", b""),
        )
        with _patched_client(inst):
            ok, device_type, fw, err = detect_device_info(IP, PW)
        assert ok is False
        assert device_type == ""
        assert "Raspberry Pi 4" in err

    def test_empty_firmware_is_tolerated(self):
        """If grep returns nothing, firmware_version is '' but device_type still works."""
        inst = MagicMock()
        inst.exec_command.side_effect = _make_exec(
            (b"rm2", b""),
            (b"", b""),
        )
        with _patched_client(inst):
            ok, device_type, fw, err = detect_device_info(IP, PW)
        assert ok is True
        assert device_type == "reMarkable 2"
        assert fw == ""

    def test_connect_failure(self):
        """SSH connection error returns ok=False with error message."""
        inst = MagicMock()
        inst.connect.side_effect = OSError("Connection refused")
        with _patched_client(inst):
            ok, device_type, fw, err = detect_device_info(IP, PW)
        assert ok is False
        assert device_type == ""
        assert fw == ""
        assert "Connection refused" in err
