"""Maintenance orchestration.

Provides a high-level `run_maintenance` function that executes the
post-update routine by calling into `src.ssh`, `src.images` and
`src.templates`.

The routine includes:
1. Uploading a `suspended.png` image (preferred from device images,
   fallback to a random library image, skipped if none available)
2. Syncing local `.template` files to rmMethods UUID triplets in xochitl
   — only when `device.templates` is True
3. Disabling the carousel by moving illustrations to a backup folder
   — only when device.carousel is True
4. Restarting `xochitl` to apply changes
"""

import logging
import random as _random
from contextlib import suppress

from src.constants import (
    CMD_CAROUSEL_BACKUP_DIR,
    CMD_CAROUSEL_DISABLE,
    CMD_RESTART_XOCHITL,
    SUSPENDED_PNG_PATH,
)
from src.i18n import _
from src.images import list_device_images, load_device_image
from src.models import Device
from src.ssh import run_ssh_cmd, upload_file_ssh
from src.template_sync import sync_templates_to_tablet

logger = logging.getLogger(__name__)


def run_maintenance(
    device_name: str,
    device: Device,
    image: str | None = None,
    step_fn=None,
    progress_fn=None,
    toast_fn=None,
    log_fn=None,
) -> dict:
    """Run the post-update maintenance routine for a device.

    Parameters
    ----------
    device_name : str
        Key used to locate local data (images, templates, …).
    device : Device
        Must provide ``ip``, ``password`` (required string field), ``templates``, ``carousel``.
    image : str, optional
        Filename of the image to upload as ``suspended.png``.  When omitted the
        preferred image is used; if none is set a random library image is picked;
        if the library is empty the step is skipped.
    step_fn : callable(msg)
        Updates the progress status label (English string).
    progress_fn : callable(pct: int)
        Updates the progress bar (0–100).
    toast_fn : callable(msg)
        Shows a completion toast notification.
    log_fn : callable(msg)
        Writes a result message to the log (English).

    Returns
    -------
    dict
        ``{"ok": bool, "errors": [...], "details": {...}}``
    """
    if step_fn is None or progress_fn is None or toast_fn is None or log_fn is None:
        raise ValueError("step_fn, progress_fn, toast_fn and log_fn are required")

    errors: list[str] = []
    details: dict = {}

    # Build the list of active steps to compute progress percentages correctly.
    active_steps: list[str] = []

    # Resolve which image to upload (may be None → step skipped)
    if image is None:
        if device.preferred_image:
            image = device.preferred_image
        else:
            try:
                imgs = list_device_images(device_name) or []
            except Exception:
                imgs = []
            if imgs:
                image = _random.choice(imgs)

    if image:
        active_steps.append(_("Upload suspended image"))
    if device.templates:
        active_steps.append(_("Sync templates"))
    if device.carousel:
        active_steps.append(_("Disable carousel"))
    active_steps.append(_("Restart xochitl"))

    total = len(active_steps)
    cur = 0

    def _advance(label: str) -> None:
        nonlocal cur
        cur += 1
        pct = int((cur / total) * 100)
        try:
            step_fn(f"{cur}/{total} — {label}")
        except Exception as e:
            logger.warning("step_fn raised: %s", e)
        try:
            progress_fn(pct)
        except Exception as e:
            logger.warning("progress_fn raised: %s", e)

    def _log(msg: str) -> None:
        with suppress(Exception):
            log_fn(msg)

    ip = device.ip
    pw = device.password or ""

    try:
        step_fn(_("Starting deployment…"))
        progress_fn(0)

        # ── 1) Upload suspended.png ────────────────────────────────────────
        if image:
            _advance(_("Upload suspended image"))
            try:
                img_blob = load_device_image(device_name, image)
            except Exception as e:
                errors.append(f"load_image_failed: {e}")
                return {"ok": False, "errors": errors, "details": details}

            ok, msg = upload_file_ssh(ip, pw, img_blob, SUSPENDED_PNG_PATH)
            if not ok:
                errors.append(f"upload_suspended_failed: {msg}")
                return {"ok": False, "errors": errors, "details": details}
            _log(f"Image '{image}' uploaded as suspended.png")

        # ── 2) Custom templates ────────────────────────────────────────────
        if device.templates:
            _advance(_("Sync templates"))
            ok = sync_templates_to_tablet(
                device_name,
                device,
                _log,
                force=True,
                restart_xochitl=False,
            )
            if not ok:
                errors.append("templates_sync_failed: sync_failed")
                return {"ok": False, "errors": errors, "details": details}

        # ── 3) Disable carousel ────────────────────────────────────────────
        if device.carousel:
            _advance(_("Disable carousel"))
            try:
                out, err = run_ssh_cmd(ip, pw, [CMD_CAROUSEL_BACKUP_DIR, CMD_CAROUSEL_DISABLE])
                details["carousel_out"] = out.strip()
                details["carousel_err"] = err.strip()
                _log("Carousel disabled")
            except Exception as e:
                errors.append(f"carousel_failed: {e}")
                return {"ok": False, "errors": errors, "details": details}

        # ── 4) Restart xochitl ─────────────────────────────────────────────
        _advance(_("Restart xochitl"))
        try:
            out, err = run_ssh_cmd(ip, pw, [CMD_RESTART_XOCHITL])
            details["restart_out"] = out.strip()
            details["restart_err"] = err.strip()
            _log("xochitl restarted")
        except Exception as e:
            errors.append(f"restart_failed: {e}")
            return {"ok": False, "errors": errors, "details": details}

        progress_fn(100)

    except Exception as e:
        logger.exception("Unexpected error during maintenance: %s", e)
        errors.append(str(e))

    result = {"ok": len(errors) == 0, "errors": errors, "details": details}

    try:
        if result["ok"]:
            toast_fn(_("Deployment completed successfully."))
        else:
            toast_fn(_("Deployment completed with errors."))
    except Exception:
        pass

    return result
