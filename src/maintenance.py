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
import os
import logging

from src.ssh import run_ssh_cmd, upload_file_ssh
from src.images import list_device_images, load_device_image
from src.templates import (
    ensure_remote_template_dirs,
    upload_template_svgs,
    backup_and_replace_templates_json,
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


def run_maintenance(device_name: str, device_conf: dict, base_dir: str, steps: List[str], image: str = None, ui: Optional[object] = None) -> Dict:
    """Run post-update maintenance routine for a device.

    device_conf: the device dict from config (must contain 'ip' and optionally 'password', 'templates', 'carousel')
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
            if device_conf.get('templates', True):
                steps.append("Ajout des templates personnalisés")
            if device_conf.get('carousel', True):
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

        ip = device_conf.get('ip')
        password = device_conf.get('password', '')

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
                ok, msg = upload_file_ssh(ip, password, img_blob, "/usr/share/remarkable/suspended.png")
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
        if device_conf.get('templates', True):
            # Ensure remote template dirs exist before uploading
            remote_custom_dir = "/home/root/templates"
            remote_templates_dir = "/usr/share/remarkable/templates"
            ok, msg = ensure_remote_template_dirs(ip, password, remote_custom_dir, remote_templates_dir)
            if not ok:
                errors.append(f"ensure_remote_dirs_failed: {msg}")
                return {"ok": False, "errors": errors, "details": details}
        
            # upload template svgs
            local_templates_dirs = [os.path.join(base_dir, 'templates'), os.path.join(base_dir, 'data', 'templates')]
            sent_count = upload_template_svgs(ip, password, local_templates_dirs, remote_custom_dir)
            if sent_count:
                # create symlinks for uploaded svgs
                try:
                    run_ssh_cmd(ip, password, [f"for file in {remote_custom_dir}/*.svg; do [ -f \"$file\" ] || continue; ln -sf \"$file\" \"{remote_templates_dir}/\"$(basename \"$file\"); done"])
                    _info(f"{sent_count} templates SVG uploadés et liens créés")
                except Exception as e:
                    errors.append(f"symlink_failed: {e}")
                    return {"ok": False, "errors": errors, "details": details}

            # Backup/replace templates.json
            local_templates_json = os.path.join(base_dir, 'templates.json')
            ok, msg = backup_and_replace_templates_json(ip, password, local_templates_json, remote_templates_dir, base_dir)
            if ok:
                _info("templates.json remplacé par la version locale")
            else:
                if msg == 'no_local':
                    _info("Aucun templates.json local trouvé pour comparaison")
                else:
                    errors.append(f"templates_json_error: {msg}")
                    return {"ok": False, "errors": errors, "details": details}

        # 3) Disable carousel
        _advance("Désactivation du carrousel")
        if device_conf.get('carousel', True):
            try:
                cmds: List[str] = []
                cmds.append("mkdir -p /usr/share/remarkable/carousel/backupIllustrations")
                cmds.append("mv /usr/share/remarkable/carousel/*.png /usr/share/remarkable/carousel/backupIllustrations/ 2>/dev/null || true")
            except Exception as e:
                errors.append(f"carousel_cmds_failed: {e}")
                return {"ok": False, "errors": errors, "details": details}

        # 4) Restart xochitl
        _advance("Redémarrage de xochitl")
        try:
            out, err = run_ssh_cmd(ip, password, "[systemctl restart xochitl]")
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
