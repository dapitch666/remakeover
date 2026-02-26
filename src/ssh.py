"""SSH helpers scaffold.

This module should implement SSH operations used by the app:
- ensure_rw_filesystem(ip, password) -> (ok, msg)
- run_ssh_cmd(ip, password, commands) -> (stdout, stderr)
- upload_file_ssh(ip, password, content, remote_path) -> (ok, msg)
- download_file_ssh(ip, password, remote_path) -> bytes

Current file contains function signatures and docs; implementations
should be moved here from `app.py` incrementally.
"""

from typing import List, Tuple
import paramiko
import logging

from src.constants import CMD_CHECK_RW, CMD_REMOUNT_RW

logger = logging.getLogger(__name__)



def _ensure_rw(client: paramiko.SSHClient) -> Tuple[bool, str]:
    """Check if `/` is mounted read-write on an open *client* and remount if not.

    Returns (True, "already_rw"|"remounted") on success, (False, error) on failure.
    Reuses the provided open connection — no extra TCP round-trip.
    """
    try:
        _, stdout, _ = client.exec_command(CMD_CHECK_RW)
        status = stdout.read().decode().strip()
    except Exception as e:
        logger.warning("RW check failed, assuming read-only: %s", e)
        status = "readonly"

    if status == "writable":
        logger.debug("Filesystem already read-write, skipping remount")
        return True, "already_rw"

    logger.info("Filesystem is read-only, remounting read-write")
    try:
        _, stdout, stderr = client.exec_command(CMD_REMOUNT_RW)
        stdout.read()
        err = stderr.read().decode().strip()
        if err:
            logger.warning("remount stderr: %s", err)
        return True, "remounted"
    except Exception as e:
        logger.error("remount failed: %s", e)
        return False, str(e)


def ensure_rw_filesystem(ip: str, password: str) -> Tuple[bool, str]:
    """Open a fresh SSH connection, check if `/` is RW, remount if needed.

    Returns (True, "already_rw"|"remounted") on success, (False, error) on failure.
    Use this when you need to guarantee a writable filesystem before a sequence
    of operations (e.g. before opening an SFTP session).
    """
    logger.info("ensure_rw_filesystem: connecting to %s", ip)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(ip, username="root", password=password, timeout=10)
        ok, msg = _ensure_rw(client)
        return ok, msg
    except Exception as e:
        logger.error("ensure_rw_filesystem connect error on %s: %s", ip, e)
        return False, str(e)
    finally:
        try:
            client.close()
        except Exception:
            pass


def run_ssh_cmd(ip: str, password: str, commands) -> Tuple[str, str]:
    """Execute commands over SSH, ensuring filesystem is writable first."""
    logger.info("SSH connect to %s (commands=%d)", ip, len(commands))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(ip, username="root", password=password, timeout=10)

        ok, rw_msg = _ensure_rw(client)
        if not ok:
            return "", f"remount failed: {rw_msg}"

        full_cmd = " && ".join(commands) if commands else ""
        if not full_cmd:
            return "", ""

        try:
            _, stdout, stderr = client.exec_command(full_cmd)
            output = stdout.read().decode()
            error = stderr.read().decode()
        except Exception as e:
            logger.error("SSH exec failed on %s: %s", ip, e)
            return "", str(e)

        logger.info("SSH exec on %s (rw=%s, out_len=%d, err_len=%d)", ip, rw_msg, len(output), len(error))
        return output, error
    except Exception as e:
        logger.error("SSH error on %s: %s", ip, e)
        return "", str(e)
    finally:
        try:
            client.close()
        except Exception:
            pass


def test_ssh_connection(ip: str, password: str) -> Tuple[bool, str]:
    """Test simple SSH connectivity without modifying the device."""
    logger.info("SSH connectivity test start for %s", ip)
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(ip, username='root', password=password, timeout=10)
        stdin, stdout, stderr = client.exec_command("echo ok")
        output = stdout.read().decode().strip()
        error = stderr.read().decode().strip()
        client.close()
        logger.info("SSH connectivity test OK for %s (out=%s, err_len=%d)", ip, output, len(error))
        return output == "ok", error
    except Exception as e:
        logger.error("SSH connectivity test error for %s: %s", ip, e)
        return False, str(e)


def upload_file_ssh(ip: str, password: str, file_content: bytes, remote_path: str) -> Tuple[bool, str]:
    """Ensure filesystem is writable, then upload *file_content* to *remote_path* via SFTP.

    Uses a single SSH connection for both the RW check/remount and the SFTP transfer.
    """
    logger.info("SSH prepare upload to %s:%s (bytes=%d)", ip, remote_path, len(file_content))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(ip, username="root", password=password, timeout=10)

        ok, msg = _ensure_rw(client)
        if not ok:
            return False, f"remount failed: {msg}"

        sftp = client.open_sftp()
        try:
            with sftp.file(remote_path, "wb") as f:
                f.write(file_content)
            logger.info("SFTP upload OK to %s:%s (bytes=%d)", ip, remote_path, len(file_content))
            return True, "OK"
        except Exception as e:
            logger.error("SFTP upload error to %s:%s: %s", ip, remote_path, e)
            return False, str(e)
        finally:
            try:
                sftp.close()
            except Exception:
                pass
    except Exception as e:
        logger.error("SSH upload connect error on %s: %s", ip, e)
        return False, str(e)
    finally:
        try:
            client.close()
        except Exception:
            pass


def download_file_ssh(ip: str, password: str, remote_path: str) -> bytes:
    logger.info("SFTP download start from %s:%s", ip, remote_path)
    transport = paramiko.Transport((ip, 22))
    transport.connect(username='root', password=password)
    sftp = paramiko.SFTPClient.from_transport(transport)
    with sftp.file(remote_path, 'rb') as f:
        content = f.read()
    sftp.close()
    transport.close()
    logger.info("SFTP download OK from %s:%s (bytes=%d)", ip, remote_path, len(content))
    return content


def list_remote_dir_ssh(ip: str, password: str, remote_dir: str) -> Tuple[List[str], str]:
    """Return a sorted list of filenames in *remote_dir* via SFTP.

    Returns (filenames, error_message). On success *error_message* is empty.
    """
    logger.info("SFTP listdir start from %s:%s", ip, remote_dir)
    transport = None
    try:
        transport = paramiko.Transport((ip, 22))
        transport.connect(username="root", password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        try:
            entries = sftp.listdir(remote_dir)
        except Exception as e:
            logger.error("SFTP listdir error on %s:%s: %s", ip, remote_dir, e)
            return [], str(e)
        finally:
            sftp.close()
        logger.info("SFTP listdir OK from %s:%s (%d entries)", ip, remote_dir, len(entries))
        return sorted(entries), ""
    except Exception as e:
        logger.error("SFTP listdir connect error on %s: %s", ip, e)
        return [], str(e)
    finally:
        if transport:
            try:
                transport.close()
            except Exception:
                pass

