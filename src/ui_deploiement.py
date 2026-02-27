"""Deployment page rendering (post-update script)."""

import os
import random

import streamlit as st

import src.images as _images
import src.maintenance as _maint


def render_page(selected_name, device, add_log, BASE_DIR):
    imgs_available = _images.list_device_images(selected_name)

    # Resolve the image that will be uploaded
    if device.preferred_image:
        image = device.preferred_image
        image_desc = f"image préférée (`{os.path.splitext(device.preferred_image)[0]}`)"
    elif imgs_available:
        image = random.choice(imgs_available)
        image_desc = f"`{os.path.splitext(image)[0]}` (choix aléatoire, aucune image préférée)"
    else:
        image = None
        image_desc = None

    # ── Description block ────────────────────────────────────────────────
    lines = ["**Ce script va :**"]
    if image_desc:
        lines.append(f"- Téléverser {image_desc} comme `suspended.png` sur la tablette")
    else:
        lines.append("- *(Aucune image locale — étape suspended.png ignorée)*")
    if getattr(device, "templates", False):
        lines.append(
            "- Uploader les templates SVG locaux, créer les liens symboliques "
            "et pousser `templates.json` sur la tablette"
        )
    if getattr(device, "carousel", False):
        lines.append(
            "- Désactiver le carrousel en déplaçant les illustrations "
            "dans un dossier de backup"
        )
    lines.append("- Redémarrer `xochitl` pour appliquer les changements")
    st.info("\n".join(lines))

    # ── Run / result state ───────────────────────────────────────────────
    result_key = f"maint_result_{selected_name}"
    result = st.session_state.get(result_key)

    if result is not None:
        if result.get("ok"):
            st.success("Maintenance terminée avec succès.", icon=":material/task_alt:")
        else:
            st.error("Maintenance terminée avec des erreurs :", icon=":material/error:")
            for e in result.get("errors", []):
                st.markdown(f"- `{e}`")
        if st.button(
            "Réinitialiser",
            key=f"maint_reset_{selected_name}",
            icon=":material/refresh:",
        ):
            del st.session_state[result_key]
            st.rerun()
        return

    # ── Launch button ────────────────────────────────────────────────────
    _, col, _ = st.columns([1, 3, 1])
    with col:
        if st.button(
            "Lancer le script complet",
            key=f"ui_launch_maintenance_{selected_name}",
            icon=":material/autorenew:",
            help="Exécuter les actions de maintenance post-mise à jour",
            type="primary",
            width="stretch",
        ):
            with st.status("Maintenance en cours…", expanded=True) as status:
                progress = st.progress(0)

                def _step(msg: str) -> None:
                    try:
                        status.text(msg)
                    except Exception:
                        pass

                result = _maint.run_maintenance(
                    selected_name, device, image,
                    step_fn=_step,
                    progress_fn=lambda pct: progress.progress(pct),
                    toast_fn=lambda msg: st.toast(msg, icon=":material/task_alt:"),
                    log_fn=add_log,
                )

            st.session_state[result_key] = result
            st.rerun()
