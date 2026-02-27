"""Maintenance orchestration.

Provides a high-level `run_maintenance` function that executes the
post-update routine by calling into `src.ssh`, `src.images` and
`src.templates`.

The routine includes:
1. Uploading a `suspended.png` image (preferred from device images,
   fallback to a random library image, skipped if none available)
2. Uploading local SVG templates, creating symlinks, and pushing
   `templates.json`  — only when device.templates is True
3. Disabling the carousel by moving illustrations to a backup folder
   — only when device.carousel is True
4. Restarting `xochitl` to apply changes
"""

from typing import Dict, List
import logging
import random as _random

from src.ssh import run_ssh_cmd, upload_file_ssh
from src.images import list_device_images, load_device_image
from src.templates import (
    ensure_remote_template_dirs,
    upload_template_svgs,
    compare_and_backup_templates_json,
    get_device_templates_dir,
)
from src.models import Device
from src.constants import (
    SUSPENDED_PNG_PATH,
    REMOTE_TEMPLATES_DIR,
    REMOTE_CUSTOM_TEMPLATES_DIR,
    REMOTE_CAROUSEL_DIR,
    REMOTE_CAROUSEL_BACKUP_DIR,
    CMD_RESTART_XOCHITL,
)

logger = logging.getLogger(__name__)


def run_maintenance(
    device_name: str,
    device: Device,
    image: str = None,
    step_fn=None,
    progress_fn=None,
    toast_fn=None,
    log_fn=None,
) -> Dict:
    """Run the post-update maintenance routine for a device.

    Parameters
    ----------
    device_name : str
        Key used to locate local data (images, templates, …).
    device : Device
        Must provide ``ip``, optional ``password``, ``templates``, ``carousel``.
    image : str, optional
        Filename of the image to upload as ``suspended.png``.  When omitted the
        preferred image is used; if none is set a random library image is picked;
        if the library is empty the step is skipped.
    step_fn : callable(msg)
        Updates the progress status label (French UI string).
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

    errors: List[str] = []
    details: Dict = {}

    # Build the list of active steps to compute progress percentages correctly.
    active_steps: List[str] = []

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
        active_steps.append("Upload de l'image de veille")
    if getattr(device, "templates", False):
        active_steps.append("Ajout des templates personnalisés")
    if getattr(device, "carousel", False):
        active_steps.append("Désactivation du carrousel")
    active_steps.append("Redémarrage de xochitl")

    total = len(active_steps)
    cur = 0

    def _advance(label: str) -> None:
        nonlocal cur
        cur += 1
        pct = int((cur / total) * 100)
        try:
            step_fn(f"{cur}/{total} — {label}")
        except Exception:
            pass
        try:
            progress_fn(pct)
        except Exception:
            pass

    def _log(msg: str) -> None:
        try:
            log_fn(msg)
        except Exception:
            pass

    ip = device.ip
    pw = device.password or ""

    try:
        step_fn("Démarrage de la maintenance…")
        progress_fn(0)

        # ── 1) Upload suspended.png ────────────────────────────────────────
        if image:
            _advance("Upload de l'image de veille")
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
        if getattr(device, "templates", False):
            _advance("Ajout des templates personnalisés")

            ok, msg = ensure_remote_template_dirs(
                ip, pw, REMOTE_CUSTOM_TEMPLATES_DIR, REMOTE_TEMPLATES_DIR
            )
            if not ok:
                errors.append(f"ensure_remote_dirs_failed: {msg}")
                return {"ok": False, "errors": errors, "details": details}

            device_templates_dir = get_device_templates_dir(device_name)
            sent_count = upload_template_svgs(
                ip, pw, [device_templates_dir], REMOTE_CUSTOM_TEMPLATES_DIR
            )
            if sent_count:
                try:
                    run_ssh_cmd(
                        ip, pw,
                        [
                            f"for file in {REMOTE_CUSTOM_TEMPLATES_DIR}/*.svg; do "
                            f"[ -f \"$file\" ] || continue; "
                            f"ln -sf \"$file\" \"{REMOTE_TEMPLATES_DIR}/\"$(basename \"$file\"); "
                            "done"
                        ],
                    )
                    _log(f"{sent_count} SVG template(s) uploaded and linked")
                except Exception as e:
                    errors.append(f"symlink_failed: {e}")
                    return {"ok": False, "errors": errors, "details": details}

            # compare_and_backup_templates_json: downloads the remote templates.json,
            # saves it as templates.backup.json if different from the local copy,
            # then uploads the local version to the tablet.
            ok, msg = compare_and_backup_templates_json(ip, pw, device_name)
            if msg == "identical":
                _log("templates.json: identical on tablet, nothing to do")
            elif msg == "uploaded":
                _log("templates.json: local version uploaded (remote backed up)")
            elif msg == "no_local":
                _log("templates.json: no local version, nothing to do")
            elif not ok:
                errors.append(f"templates_json_error: {msg}")
                return {"ok": False, "errors": errors, "details": details}

        # ── 3) Disable carousel ────────────────────────────────────────────
        if getattr(device, "carousel", False):
            _advance("Désactivation du carrousel")
            carousel_cmd = (
                f"mkdir -p '{REMOTE_CAROUSEL_BACKUP_DIR}' && "
                f"mv '{REMOTE_CAROUSEL_DIR}'/*.png '{REMOTE_CAROUSEL_BACKUP_DIR}/' "
                f"2>/dev/null || true"
            )
            try:
                out, err = run_ssh_cmd(ip, pw, [carousel_cmd])
                details["carousel_out"] = out.strip()
                details["carousel_err"] = err.strip()
                _log("Carousel disabled")
            except Exception as e:
                errors.append(f"carousel_failed: {e}")
                return {"ok": False, "errors": errors, "details": details}

        # ── 4) Restart xochitl ─────────────────────────────────────────────
        _advance("Redémarrage de xochitl")
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
            toast_fn("Maintenance terminée avec succès")
        else:
            toast_fn("Maintenance terminée (avec erreurs)")
    except Exception:
        pass

    return result
