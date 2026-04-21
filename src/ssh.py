"""SSH helpers for reMarkable device communication.

All public functions open a fresh SSH connection, perform their
operation, and return an ``(ok, msg)`` or ``(output, error)`` pair.

Public API
----------
- run_ssh_cmd(device, commands) -> (stdout, stderr)
- upload_file_ssh(device, content, remote_path) -> (ok, msg)
- download_file_ssh(device, remote_path) -> (bytes | None, msg)
- detect_device_info(device) -> (ok, device_type, firmware_version, sleep_screen_enabled, error_msg)
"""

import logging
from collections.abc import Generator
from contextlib import contextmanager, suppress

import paramiko

from src.constants import (
    CMD_CHECK_SLEEP_SCREEN,
    CMD_READ_FIRMWARE,
    CMD_READ_MACHINE,
    MACHINE_TO_DEVICE_TYPE,
)
from src.models import Device

logger = logging.getLogger(__name__)

# Timeout (seconds) applied to exec_command calls.
# Quick: short-lived shell one-liners (connectivity probe, etc.).
# Long: operations that may block — systemctl restart, symlink loops, etc.
_CMD_TIMEOUT_QUICK: int = 10
_CMD_TIMEOUT_LONG: int = 60


@contextmanager
def _ssh_client(ip: str, password: str) -> Generator[paramiko.SSHClient, None, None]:
    """Context manager that opens, yields and always closes a paramiko SSHClient."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ip, username="root", password=password, timeout=10)
    try:
        yield client
    finally:
        with suppress(Exception):
            client.close()


def run_ssh_cmd(device: Device, commands) -> tuple[str, str]:
    """Execute commands over SSH."""
    ip = device.ip
    logger.info("SSH connect to %s (commands=%d)", ip, len(commands))
    try:
        with _ssh_client(ip, device.password) as client:
            full_cmd = " && ".join(commands)
            if not full_cmd:
                return "", ""

            try:
                _, stdout, stderr = client.exec_command(full_cmd, timeout=_CMD_TIMEOUT_LONG)
                output = stdout.read().decode()
                error = stderr.read().decode()
            except Exception as e:
                logger.error("SSH exec failed on %s: %s", ip, e)
                return "", str(e)

            logger.info("SSH exec on %s (out_len=%d, err_len=%d)", ip, len(output), len(error))
            return output, error
    except Exception as e:
        logger.error("SSH error on %s: %s", ip, e)
        return "", str(e)


def detect_device_info(device: Device) -> tuple[bool, str, str, bool, str]:
    """Detect device type, firmware version, and sleep-screen config via SSH.

    Reads ``/sys/devices/soc0/machine`` to identify the hardware,
    ``/etc/os-release`` to extract the firmware version string, and checks
    whether ``SleepScreenPath`` is already configured in xochitl.conf.

    Returns ``(ok, device_type, firmware_version, sleep_screen_enabled, error_msg)``.
    On success ``ok=True`` and ``error_msg=""``.
    On failure ``ok=False``, ``device_type`` and ``firmware_version`` are ``""``
    and ``sleep_screen_enabled`` is ``False``.
    """
    ip = device.ip
    logger.info("detect_device_info start for %s", ip)
    try:
        with _ssh_client(ip, device.password) as client:
            _, stdout, _ = client.exec_command(CMD_READ_MACHINE, timeout=_CMD_TIMEOUT_QUICK)
            machine_raw = stdout.read().decode().strip()

            _, stdout2, _ = client.exec_command(CMD_READ_FIRMWARE, timeout=_CMD_TIMEOUT_QUICK)
            fw_raw = stdout2.read().decode().strip()

            _, stdout3, _ = client.exec_command(CMD_CHECK_SLEEP_SCREEN, timeout=_CMD_TIMEOUT_QUICK)
            sleep_raw = stdout3.read().decode().strip()

        machine_lower = machine_raw.lower()
        device_type = next(
            (name for key, name in MACHINE_TO_DEVICE_TYPE.items() if key in machine_lower), ""
        )

        firmware_version = ""
        for line in fw_raw.splitlines():
            if line.startswith("IMG_VERSION="):
                firmware_version = line.split("=", 1)[1].strip().strip('"')
                break

        sleep_screen_enabled = sleep_raw == "yes"

        if not device_type:
            logger.warning(
                "detect_device_info: unrecognised machine string '%s' for %s", machine_raw, ip
            )
            return False, "", firmware_version, False, f"Unknown machine: '{machine_raw}'"

        logger.info(
            "detect_device_info OK for %s: type=%s fw=%s sleep=%s",
            ip,
            device_type,
            firmware_version,
            sleep_screen_enabled,
        )
        return True, device_type, firmware_version, sleep_screen_enabled, ""
    except Exception as e:
        logger.error("detect_device_info error for %s: %s", ip, e)
        return False, "", "", False, str(e)


def run_detection(device: Device) -> dict:
    """Call detect_device_info and return a normalised result dict.

    Keys: ok, device_type, firmware_version, sleep_screen_enabled, error.
    """
    ok, device_type, fw, sleep_enabled, err = detect_device_info(device)
    return {
        "ok": ok,
        "device_type": device_type if ok else "",
        "firmware_version": fw if ok else "",
        "sleep_screen_enabled": sleep_enabled if ok else False,
        "error": err if not ok else "",
    }


def upload_file_ssh(device: Device, file_content: bytes, remote_path: str) -> tuple[bool, str]:
    """Upload *file_content* to *remote_path* via SFTP."""
    ip = device.ip
    logger.info("SSH prepare upload to %s:%s (bytes=%d)", ip, remote_path, len(file_content))
    try:
        with _ssh_client(ip, device.password) as client:
            sftp = client.open_sftp()
            try:
                with sftp.file(remote_path, "wb") as f:
                    f.write(file_content)
                logger.info(
                    "SFTP upload OK to %s:%s (bytes=%d)", ip, remote_path, len(file_content)
                )
                return True, "OK"
            except Exception as e:
                logger.error("SFTP upload error to %s:%s: %s", ip, remote_path, e)
                return False, str(e)
            finally:
                with suppress(Exception):
                    sftp.close()
    except Exception as e:
        logger.error("SSH upload connect error on %s: %s", ip, e)
        return False, str(e)


def download_file_ssh(device: Device, remote_path: str) -> tuple[bytes | None, str]:
    """Download *remote_path* via SFTP.

    Returns ``(content, "")`` on success, ``(None, error_message)`` on failure.
    """
    ip = device.ip
    logger.info("SFTP download start from %s:%s", ip, remote_path)
    try:
        with _ssh_client(ip, device.password) as client:
            sftp = client.open_sftp()
            try:
                with sftp.file(remote_path, "rb") as f:
                    content = f.read()
            finally:
                with suppress(Exception):
                    sftp.close()
        logger.info("SFTP download OK from %s:%s (bytes=%d)", ip, remote_path, len(content))
        return content, ""
    except Exception as e:
        logger.error("SFTP download error from %s:%s: %s", ip, remote_path, e)
        return None, str(e)


class SshSession:
    """Reusable SSH session over a single open connection.

    Opens one paramiko SSHClient and one SFTP channel (lazily) for the
    lifetime of the session.  All operations share the same TCP connection,
    so callers avoid repeated handshake and RW-check overhead.

    Do not instantiate directly — use the :func:`ssh_session` context manager.
    """

    def __init__(self, client: paramiko.SSHClient) -> None:
        self._client = client
        self._sftp: paramiko.SFTPClient | None = None

    # ------------------------------------------------------------------
    # Shell execution
    # ------------------------------------------------------------------

    def run(self, commands: list[str]) -> tuple[str, str]:
        """Join *commands* with ``&&`` and execute in one shot."""
        full_cmd = " && ".join(commands) if commands else ""
        if not full_cmd:
            return "", ""
        try:
            _, stdout, stderr = self._client.exec_command(full_cmd, timeout=_CMD_TIMEOUT_LONG)
            return stdout.read().decode(), stderr.read().decode()
        except Exception as e:
            logger.error("SshSession.run failed: %s", e)
            return "", str(e)

    # ------------------------------------------------------------------
    # File transfer
    # ------------------------------------------------------------------

    def upload(self, content: bytes, remote_path: str) -> tuple[bool, str]:
        """Write *content* to *remote_path* via the shared SFTP channel."""
        sftp = self._sftp_channel()
        try:
            with sftp.file(remote_path, "wb") as f:
                f.write(content)
            logger.info("SshSession upload OK → %s (%d bytes)", remote_path, len(content))
            return True, "OK"
        except Exception as e:
            logger.error("SshSession upload error → %s: %s", remote_path, e)
            return False, str(e)

    def download(self, remote_path: str) -> tuple[bytes | None, str]:
        """Read *remote_path* via the shared SFTP channel."""
        sftp = self._sftp_channel()
        try:
            with sftp.file(remote_path, "rb") as f:
                content = f.read()
            logger.info("SshSession download OK ← %s (%d bytes)", remote_path, len(content))
            return content, ""
        except Exception as e:
            logger.error("SshSession download error ← %s: %s", remote_path, e)
            return None, str(e)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _sftp_channel(self) -> paramiko.SFTPClient:
        if self._sftp is None:
            self._sftp = self._client.open_sftp()
        return self._sftp

    def close(self) -> None:
        if self._sftp is not None:
            with suppress(Exception):
                self._sftp.close()
            self._sftp = None


@contextmanager
def ssh_session(device: Device) -> Generator[SshSession, None, None]:
    """Open one SSH connection and yield a reusable :class:`SshSession`.

    Usage::

        with ssh_session(device) as s:
            s.upload(data, "/path/to/file")
            out, err = s.run(["systemctl restart xochitl"])
    """
    with _ssh_client(device.ip, device.password) as client:
        session = SshSession(client)
        try:
            yield session
        finally:
            session.close()
