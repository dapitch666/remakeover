"""Maintenance orchestration scaffold.

Provides a high-level `run_maintenance` function that executes the
post-update routine by calling into `src.ssh`, `src.images` and
`src.templates`.

The routine includes:
- Checking if the filesystem is writable and remounting if needed
- Uploading a `suspended.png` image (preferred from device images, fallback to library)
- Ensuring remote template directories exist
- Uploading local SVG templates and creating symlinks
- Backing up and replacing `templates.json` if a local version exists and differs
- Disabling the carousel by moving illustrations to a backup folder
- Restarting `xochitl` to apply changes
"""

from typing import Optional, Dict, List
import logging

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
    CMD_RESTART_XOCHITL,
    CMD_CAROUSEL_BACKUP_DIR,
    CMD_CAROUSEL_DISABLE,
)

logger = logging.getLogger(__name__)


class _DefaultUI:
    def __init__(self):
        self._progress = 0

    def step(self, msg: str):
        logger.info("step: %s", msg)

    def progress(self, pct: int):
        self._progress = pct
        logger.info("progress: %d", pct)

    def toast(self, msg: str):
        logger.info("toast: %s", msg)


def run_maintenance(device_name: str, device: Device, base_dir: str, steps: List[str], image: str = None, ui: Optional[object] = None) -> Dict:
    """Run post-update maintenance routine for a device.

    device: a `Device` instance (must contain `ip`, optional `password`, `templates`, `carousel`)
    base_dir: project base dir used to locate local templates and files
    image: optional image filename for suspended.png
    ui: optional object exposing `step(text)`, `progress(pct)` and `toast(msg)`.

    Returns a summary dict: {"ok": bool, "errors": [...], "details": {...}}
    """
    # Allow caller to pass the `ui` object as the 5th positional argument
    # (historical callers/tests do this). If `ui` is not provided but
    # `image` looks like a UI adapter, swap them.
    if ui is None and image is not None and all(hasattr(image, a) for a in ('step', 'progress', 'toast')):
        ui = image
        image = None

    if ui is None:
        ui = _DefaultUI()

    errors: List[str] = []
    details: Dict = {}

    try:
        ui.step("Démarrage de la maintenance")
        ui.progress(0)

        # If the caller didn't provide a `steps` list, build a sensible
        # fallback based on device configuration and available local images.
        if steps is None:
            steps = []
            try:
                imgs = list_device_images(device_name) or []
            except Exception:
                imgs = []
            if image or imgs:
                steps.append("Upload de l'image de suspension")
            # Use Device attributes directly
            if device.templates:
                steps.append("Ajout des templates personnalisés")
            if device.carousel:
                steps.append("Désactivation du carrousel")
            steps.append("Redémarrage de xochitl")

        total = max(1, len(steps))
        cur = 0
        steps_iter = iter(steps)

        def _advance(msg_default: str):
            """Advance to the next high-level step (consumes one item from `steps`)."""
            nonlocal cur
            cur += 1
            pct = int((cur / total) * 100)
            # prefer the next provided step label, fall back to the default
            try:
                label = next(steps_iter, msg_default)
            except Exception:
                label = msg_default
            try:
                ui.step(f"{cur}/{total} — {label}")
            except Exception:
                ui.step(label)
            try:
                ui.progress(pct)
            except Exception:
                pass

        def _info(msg: str):
            """Emit an informational step without advancing progress."""
            try:
                ui.step(msg)
            except Exception:
                pass

        ip = device.ip
        password = device.password or ''

        # 1) Upload suspended.png if image is specified
        _advance("Upload de l'image de suspension")
        img_blob = None

        # attempt to load image from device images dir
        try:
            img_blob = load_device_image(device_name, image)
        except Exception:
            img_blob = None

        if img_blob:
            try:
                ok, msg = upload_file_ssh(ip, password, img_blob, SUSPENDED_PNG_PATH)
                if not ok:
                    errors.append(f"upload_suspended_failed: {msg}")
                    return {"ok": False, "errors": errors, "details": details}
            except Exception as e:
                errors.append(f"upload_suspended_exception: {e}")
                return {"ok": False, "errors": errors, "details": details}
        else:
            _info("Aucune image de suspension spécifiée, saut de l'upload")

        # 2) Ajout des templates personnalisés
        _advance("Ajout des templates personnalisés")
        if device.templates:
            # Ensure remote template dirs exist before uploading
            ok, msg = ensure_remote_template_dirs(ip, password, REMOTE_CUSTOM_TEMPLATES_DIR, REMOTE_TEMPLATES_DIR)
            if not ok:
                errors.append(f"ensure_remote_dirs_failed: {msg}")
                return {"ok": False, "errors": errors, "details": details}
        
            # upload template svgs from the device-specific local directory
            device_templates_dir = get_device_templates_dir(device_name)
            sent_count = upload_template_svgs(ip, password, [device_templates_dir], REMOTE_CUSTOM_TEMPLATES_DIR)
            if sent_count:
                # create symlinks for uploaded svgs
                try:
                    run_ssh_cmd(ip, password, [f"for file in {REMOTE_CUSTOM_TEMPLATES_DIR}/*.svg; do [ -f \"$file\" ] || continue; ln -sf \"$file\" \"{REMOTE_TEMPLATES_DIR}/\"$(basename \"$file\"); done"])
                    _info(f"{sent_count} templates SVG uploadés et liens créés")
                except Exception as e:
                    errors.append(f"symlink_failed: {e}")
                    return {"ok": False, "errors": errors, "details": details}

            # Compare remote templates.json with local copy; backup + upload if different
            ok, msg = compare_and_backup_templates_json(ip, password, device_name)
            if msg == "identical":
                _info("templates.json identique sur la tablette, rien à faire")
            elif msg == "uploaded":
                _info("templates.json local uploadé sur la tablette (ancien sauvegardé dans templates.backup.json)")
            elif msg == "no_local":
                _info("Aucun templates.json local trouvé pour comparaison")
            elif not ok:
                errors.append(f"templates_json_error: {msg}")
                return {"ok": False, "errors": errors, "details": details}

        # 3) Disable carousel
        _advance("Désactivation du carrousel")
        if device.carousel:
            cmds: List[str] = [
                CMD_CAROUSEL_BACKUP_DIR,
                CMD_CAROUSEL_DISABLE,
            ]
        
            try:
                out, err = run_ssh_cmd(ip, password, cmds)
                details['carousel_out'] = out.strip()
                details['carousel_err'] = err.strip()
                _info("Commandes de désactivation du carrousel exécutées")

            except Exception as e:
                errors.append(f"carousel_cmds_failed: {e}")
                return {"ok": False, "errors": errors, "details": details}

        # 4) Restart xochitl
        _advance("Redémarrage de xochitl")
        try:
            out, err = run_ssh_cmd(ip, password, [CMD_RESTART_XOCHITL])
            details['restart_out'] = out.strip()
            details['restart_err'] = err.strip()
            _info("Redémarrage de xochitl demandé")
        except Exception as e:
            errors.append(f"restart_failed: {e}")
            return {"ok": False, "errors": errors, "details": details}

        ui.progress(100)

    except Exception as e:
        logger.exception("Unexpected error during maintenance: %s", e)
        errors.append(str(e))

    result = {"ok": len(errors) == 0, "errors": errors, "details": details}

    # Notify UI of completion (success or errors)
    try:
        if result.get('ok'):
            ui.toast("Maintenance terminée")
        else:
            ui.toast("Maintenance terminée (avec erreurs)")
    except Exception:
        pass

    return result
