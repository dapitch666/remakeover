"""Maintenance orchestration scaffold.

Provides a high-level `run_maintenance` function that executes the
post-update routine by calling into `src.ssh`, `src.images` and
`src.templates`.

The implementation here is a scaffold and should be filled by moving
logic from `app.py` into testable functions. The `ui` parameter is an
optional object exposing `step(text)`, `progress(pct)` and `toast(msg)`.
"""

from typing import Optional, Dict, List
import os
import logging

from src.ssh import run_ssh_cmd, run_ssh_cmd_no_remount, upload_file_ssh, download_file_ssh
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


def run_maintenance(device_name: str, device_conf: dict, base_dir: str, preferred_image: str = None, ui: Optional[object] = None) -> Dict:
    """Run post-update maintenance routine for a device.

    device_conf: the device dict from config (must contain 'ip' and optionally 'password', 'templates', 'carousel')
    base_dir: project base dir used to locate local templates and files
    preferred_image: optional image filename to prefer for suspended.png
    ui: optional object exposing `step(text)`, `progress(pct)` and `toast(msg)`.

    Returns a summary dict: {"ok": bool, "errors": [...], "details": {...}}
    """
    if ui is None:
        ui = _DefaultUI()

    errors: List[str] = []
    details: Dict = {}

    try:
        ui.step("Démarrage de la maintenance")
        ui.progress(0)

        steps = [
            "Vérification du système de fichiers",
            "Upload suspended.png",
            "Création dossiers templates distants",
            "Upload SVG templates",
            "Backup/replace templates.json",
            "Désactivation carousel",
            "Redémarrage xochitl",
        ]

        total = len(steps)
        cur = 0

        def _step(msg: str):
            nonlocal cur
            cur += 1
            pct = int((cur / total) * 100)
            try:
                ui.step(f"{cur}/{total} — {msg}")
            except Exception:
                ui.step(msg)
            try:
                ui.progress(pct)
            except Exception:
                pass

        ip = device_conf.get('ip')
        password = device_conf.get('password', '')

        # 1) Check writable filesystem
        _step(steps[0])
        check_cmd = (
            'if mount | grep "on / " | grep -q "(rw,"; then printf "  / is already writable"; else printf "  Remounting / read-write\n"; mount -o remount,rw /; printf "  Remounted / read-write"; fi'
        )
        try:
            out, err = run_ssh_cmd_no_remount(ip, password, [check_cmd])
            details['fs_check'] = out.strip()
        except Exception as e:
            errors.append(f"fs_check_failed: {e}")
            return {"ok": False, "errors": errors, "details": details}

        # 2) Upload suspended.png
        _step(steps[1])
        imgs_available = list_device_images(device_name)
        chosen_image = None
        img_blob = None
        chosen_source = None
        if preferred_image and os.path.exists(os.path.join(getattr(os, 'getcwd')(), 'no-op')):
            # keep backward compatibility placeholder (preferred image handled below)
            pass

        if preferred_image and os.path.exists(os.path.join(base_dir, 'dummy')):
            # placeholder, real selection below
            pass

        # select preferred or library
        if preferred_image and os.path.exists(os.path.join(base_dir, 'data')):
            # attempt to load preferred from device images dir
            try:
                img_blob = load_device_image(device_name, preferred_image)
                chosen_image = preferred_image
                chosen_source = 'preferred'
            except Exception:
                img_blob = None

        if not img_blob and imgs_available:
            import random

            chosen_image = random.choice(imgs_available)
            try:
                img_blob = load_device_image(device_name, chosen_image)
                chosen_source = 'library'
            except Exception:
                img_blob = None

        if img_blob:
            try:
                ok, msg = upload_file_ssh(ip, password, img_blob, "/usr/share/remarkable/suspended.png")
                if ok:
                    _step(f"suspended.png uploadé ({chosen_image})")
                else:
                    errors.append(f"upload_suspended_failed: {msg}")
                    return {"ok": False, "errors": errors, "details": details}
            except Exception as e:
                errors.append(f"upload_suspended_exception: {e}")
                return {"ok": False, "errors": errors, "details": details}
        else:
            _step("Aucune image locale disponible pour upload comme suspended.png")

        # 3) Ensure remote template dirs and 4) upload template svgs
        _step(steps[2])
        remote_custom_dir = "/home/root/templates"
        remote_templates_dir = "/usr/share/remarkable/templates"
        if device_conf.get('templates', True):
            ok, msg = ensure_remote_template_dirs(ip, password, remote_custom_dir, remote_templates_dir)
            if not ok:
                errors.append(f"ensure_remote_dirs_failed: {msg}")
                return {"ok": False, "errors": errors, "details": details}
        else:
            ui.step("Templates disabled for this device")

        _step(steps[3])
        if device_conf.get('templates', True):
            local_templates_dirs = [os.path.join(base_dir, 'templates'), os.path.join(base_dir, 'data', 'templates')]
            sent_count = upload_template_svgs(ip, password, local_templates_dirs, remote_custom_dir)
            if sent_count:
                # create symlinks for uploaded svgs
                try:
                    run_ssh_cmd(ip, password, [f"for file in {remote_custom_dir}/*.svg; do [ -f \"$file\" ] || continue; ln -sf \"$file\" \"{remote_templates_dir}/\"$(basename \"$file\"); done"])
                    _step(f"{sent_count} templates SVG uploadés et liens créés")
                except Exception as e:
                    errors.append(f"symlink_failed: {e}")
                    return {"ok": False, "errors": errors, "details": details}
            else:
                _step("Aucun fichier SVG de template local trouvé à uploader")

        # 5) Backup/replace templates.json
        _step(steps[4])
        if device_conf.get('templates', True):
            local_templates_json = os.path.join(base_dir, 'templates.json')
            ok, msg = backup_and_replace_templates_json(ip, password, local_templates_json, remote_templates_dir, base_dir)
            if ok:
                _step("templates.json remplacé par la version locale")
            else:
                if msg == 'no_local':
                    _step("Aucun templates.json local trouvé pour comparaison")
                else:
                    errors.append(f"templates_json_error: {msg}")
                    return {"ok": False, "errors": errors, "details": details}

        # 6) Disable carousel
        _step(steps[5])
        cmds: List[str] = []
        if device_conf.get('carousel', True):
            try:
                cmds.append("mkdir -p /usr/share/remarkable/carousel/backupIllustrations")
                cmds.append("mv /usr/share/remarkable/carousel/*.png /usr/share/remarkable/carousel/backupIllustrations/ 2>/dev/null || true")
            except Exception as e:
                errors.append(f"carousel_cmds_failed: {e}")
                return {"ok": False, "errors": errors, "details": details}

        # 7) Restart xochitl
        _step(steps[6])
        try:
            cmds.append("systemctl restart xochitl")
            out, err = run_ssh_cmd(ip, password, cmds)
            details['restart_out'] = out.strip()
            details['restart_err'] = err.strip()
            _step("Redémarrage de xochitl demandé")
        except Exception as e:
            errors.append(f"restart_failed: {e}")
            return {"ok": False, "errors": errors, "details": details}

        ui.progress(100)
        ui.toast("Maintenance terminée")

    except Exception as e:
        logger.exception("Unexpected error during maintenance: %s", e)
        errors.append(str(e))

    result = {"ok": len(errors) == 0, "errors": errors, "details": details}
    return result
