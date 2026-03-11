"""SSH helpers for reMarkable tablet communication.

All public functions open a fresh SSH connection, remount the root
filesystem read-write if necessary (via ``_ensure_rw``), perform their
operation, and return an ``(ok, msg)`` or ``(output, error)`` pair.

Public API
----------
- run_ssh_cmd(ip, password, commands) -> (stdout, stderr)
- ssh_connectivity_test(ip, password) -> (ok, msg)
- upload_file_ssh(ip, password, content, remote_path) -> (ok, msg)
- download_file_ssh(ip, password, remote_path) -> (bytes | None, msg)
"""

import logging
from collections.abc import Generator
from contextlib import contextmanager, suppress

import paramiko

from src.constants import CMD_CHECK_RW, CMD_REMOUNT_RW

logger = logging.getLogger(__name__)

# Timeout (seconds) applied to exec_command calls.
# Quick: short-lived shell one-liners (RW check, remount, connectivity probe).
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


def _ensure_rw(client: paramiko.SSHClient) -> tuple[bool, str]:
    """Check if `/` is mounted read-write on an open *client* and remount if not.

    Returns (True, "already_rw"|"remounted") on success, (False, error) on failure.
    Reuses the provided open connection — no extra TCP round-trip.
    """
    try:
        _, stdout, _ = client.exec_command(CMD_CHECK_RW, timeout=_CMD_TIMEOUT_QUICK)
        status = stdout.read().decode().strip()
    except Exception as e:
        logger.warning("RW check failed, assuming read-only: %s", e)
        status = "readonly"

    if status == "writable":
        logger.debug("Filesystem already read-write, skipping remount")
        return True, "already_rw"

    logger.info("Filesystem is read-only, remounting read-write")
    try:
        _, stdout, stderr = client.exec_command(CMD_REMOUNT_RW, timeout=_CMD_TIMEOUT_QUICK)
        stdout.read()
        err = stderr.read().decode().strip()
        if err:
            logger.warning("remount stderr: %s", err)
        return True, "remounted"
    except Exception as e:
        logger.error("remount failed: %s", e)
        return False, str(e)


def run_ssh_cmd(ip: str, password: str, commands) -> tuple[str, str]:
    """Execute commands over SSH, ensuring filesystem is writable first."""
    logger.info("SSH connect to %s (commands=%d)", ip, len(commands))
    try:
        with _ssh_client(ip, password) as client:
            ok, rw_msg = _ensure_rw(client)
            if not ok:
                return "", f"remount failed: {rw_msg}"

            full_cmd = " && ".join(commands) if commands else ""
            if not full_cmd:
                return "", ""

            try:
                _, stdout, stderr = client.exec_command(full_cmd, timeout=_CMD_TIMEOUT_LONG)
                output = stdout.read().decode()
                error = stderr.read().decode()
            except Exception as e:
                logger.error("SSH exec failed on %s: %s", ip, e)
                return "", str(e)

            logger.info(
                "SSH exec on %s (rw=%s, out_len=%d, err_len=%d)",
                ip,
                rw_msg,
                len(output),
                len(error),
            )
            return output, error
    except Exception as e:
        logger.error("SSH error on %s: %s", ip, e)
        return "", str(e)


def ssh_connectivity_test(ip: str, password: str) -> tuple[bool, str]:
    """Test simple SSH connectivity without modifying the device."""
    logger.info("SSH connectivity test start for %s", ip)
    try:
        with _ssh_client(ip, password) as client:
            _, stdout, stderr = client.exec_command("echo ok", timeout=_CMD_TIMEOUT_QUICK)
            output = stdout.read().decode().strip()
            error = stderr.read().decode().strip()
        logger.info("SSH connectivity test OK for %s (out=%s, err_len=%d)", ip, output, len(error))
        return output == "ok", error
    except Exception as e:
        logger.error("SSH connectivity test error for %s: %s", ip, e)
        return False, str(e)


def upload_file_ssh(
    ip: str, password: str, file_content: bytes, remote_path: str
) -> tuple[bool, str]:
    """Ensure filesystem is writable, then upload *file_content* to *remote_path* via SFTP.

    Uses a single SSH connection for both the RW check/remount and the SFTP transfer.
    """
    logger.info("SSH prepare upload to %s:%s (bytes=%d)", ip, remote_path, len(file_content))
    try:
        with _ssh_client(ip, password) as client:
            ok, msg = _ensure_rw(client)
            if not ok:
                return False, f"remount failed: {msg}"

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


def download_file_ssh(ip: str, password: str, remote_path: str) -> tuple[bytes | None, str]:
    """Download *remote_path* via SFTP.

    Returns ``(content, "")`` on success, ``(None, error_message)`` on failure.
    """
    logger.info("SFTP download start from %s:%s", ip, remote_path)
    try:
        with _ssh_client(ip, password) as client:
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
