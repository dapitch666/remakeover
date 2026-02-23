"""SSH helpers scaffold.

This module should implement SSH operations used by the app:
- run_ssh_cmd(ip, password, commands) -> (stdout, stderr)
- run_ssh_cmd_no_remount(ip, password, commands) -> (stdout, stderr)
- upload_file_ssh(ip, password, content, remote_path) -> (ok, msg)
- download_file_ssh(ip, password, remote_path) -> bytes

Current file contains function signatures and docs; implementations
should be moved here from `app.py` incrementally.
"""

from typing import Tuple
import paramiko
import logging

logger = logging.getLogger(__name__)


def run_ssh_cmd(ip: str, password: str, commands) -> Tuple[str, str]:
    """Execute commands over SSH, ensuring filesystem writable when needed.

    This mirrors the behavior previously in `app.py`: checks whether `/` is
    already mounted read-write and only performs `mount -o remount,rw /` when
    necessary before running the provided commands.
    """
    logger.info("SSH connect to %s (commands=%d)", ip, len(commands))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(ip, username='root', password=password, timeout=10)

        check_cmd = (
            'if mount | grep "on / " | grep -q "(rw,"; then printf "writable"; else printf "readonly"; fi'
        )
        try:
            stdin, stdout, stderr = client.exec_command(check_cmd)
            check_out = stdout.read().decode().strip()
            check_err = stderr.read().decode().strip()
        except Exception as e:
            logger.warning("SSH check command failed on %s: %s", ip, e)
            check_out = "readonly"

        if check_out == "writable":
            full_cmd = " && ".join(commands) if commands else ""
        else:
            full_cmd = ("mount -o remount,rw / && " + " && ".join(commands)) if commands else "mount -o remount,rw /"

        try:
            stdin, stdout, stderr = client.exec_command(full_cmd)
            output = stdout.read().decode()
            error = stderr.read().decode()
        except Exception as e:
            logger.error("SSH exec failed on %s: %s", ip, e)
            client.close()
            return "", str(e)

        client.close()
        logger.info(
            "SSH exec on %s (check=%s, out_len=%d, err_len=%d)", ip, check_out, len(output), len(error)
        )
        return output, error
    except Exception as e:
        logger.error("SSH error on %s: %s", ip, e)
        return "", str(e)


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
    logger.info("SSH prepare upload to %s:%s (bytes=%d)", ip, remote_path, len(file_content))
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(ip, username='root', password=password, timeout=10)
        stdin, stdout, stderr = client.exec_command("mount -o remount,rw /")
        stdout.read()
        client.close()
    except Exception as e:
        logger.error("SSH RW mount failed on %s: %s", ip, e)
        return False, str(e)

    transport = paramiko.Transport((ip, 22))
    transport.connect(username='root', password=password)
    sftp = paramiko.SFTPClient.from_transport(transport)
    try:
        with sftp.file(remote_path, 'wb') as f:
            f.write(file_content)
        sftp.close()
        transport.close()
        logger.info("SFTP upload OK to %s:%s (bytes=%d)", ip, remote_path, len(file_content))
        return True, "OK"
    except Exception as e:
        try:
            sftp.close()
        except Exception:
            pass
        transport.close()
        logger.error("SFTP upload error to %s:%s: %s", ip, remote_path, e)
        return False, str(e)


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

