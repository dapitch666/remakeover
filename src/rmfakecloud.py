"""rmfakecloud re-pairing: SSH install step + HTTP pairing-code fetch.

Public API
----------
- fetch_pairing_code(url, email, password) -> (ok, code, error)
- run_install(device, on_chunk=None) -> (ok, output)
"""

import logging
from collections.abc import Callable

import requests

from src.models import Device
from src.ssh import stream_ssh_cmd

logger = logging.getLogger(__name__)

_TIMEOUT = 10


def fetch_pairing_code(url: str, email: str, password: str) -> tuple[bool, str, str]:
    """Log into rmfakecloud and fetch a fresh one-time device pairing code.

    The code is single-use and expires after 5 minutes on the rmfakecloud side,
    so callers should fetch it immediately before displaying it to the user.

    Returns ``(ok, code, error)``. On success ``code`` holds the pairing code
    and ``error`` is empty. On failure ``code`` is empty and ``error``
    describes what went wrong.
    """
    base = url.rstrip("/")
    session = requests.Session()

    try:
        resp = session.post(
            f"{base}/ui/api/login",
            json={"email": email, "password": password},
            timeout=_TIMEOUT,
        )
    except requests.RequestException as e:
        logger.error("rmfakecloud login request failed for %s: %s", base, e)
        return False, "", f"Could not reach {url}: {e}"
    if resp.status_code != 200:
        logger.error("rmfakecloud login failed for %s: HTTP %d", base, resp.status_code)
        return False, "", f"rmfakecloud login failed (HTTP {resp.status_code})"

    try:
        resp = session.get(f"{base}/ui/api/newcode", timeout=_TIMEOUT)
    except requests.RequestException as e:
        logger.error("rmfakecloud newcode request failed for %s: %s", base, e)
        return False, "", f"Could not reach {url}: {e}"
    if resp.status_code != 200:
        logger.error("rmfakecloud newcode failed for %s: HTTP %d", base, resp.status_code)
        return False, "", f"Could not generate pairing code (HTTP {resp.status_code})"

    try:
        code = resp.json()
    except ValueError as e:
        logger.error("rmfakecloud newcode returned non-JSON body for %s: %s", base, e)
        return False, "", "Unexpected response from rmfakecloud when generating the pairing code"
    if not isinstance(code, str) or not code:
        logger.error("rmfakecloud newcode returned unexpected payload for %s: %r", base, code)
        return False, "", "Unexpected response from rmfakecloud when generating the pairing code"

    logger.info("rmfakecloud pairing code generated for %s", base)
    return True, code, ""


def run_install(device: Device, on_chunk: Callable[[str], None] | None = None) -> tuple[bool, str]:
    """Run the device's install command over SSH, streaming output via ``on_chunk``.

    ``device.rmfakecloud_install_cmd`` may contain a ``{url}`` placeholder,
    replaced with ``device.rmfakecloud_url`` verbatim (plain substring
    replacement, not ``str.format``, since the command is arbitrary
    user-typed shell text that may itself contain other ``{`` characters).

    Success is judged by the SSH command's actual exit status, not by
    whether it printed anything to stdout/stderr — install scripts commonly
    emit harmless warnings (e.g. ``systemctl stop`` on a not-yet-loaded unit)
    while still completing successfully.

    Returns ``(ok, full_output)``, same contract as :func:`src.ssh.stream_ssh_cmd`.
    """
    install_cmd = device.rmfakecloud_install_cmd.replace("{url}", device.rmfakecloud_url)
    return stream_ssh_cmd(device, [install_cmd], on_chunk=on_chunk)
