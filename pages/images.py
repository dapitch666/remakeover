"""Image library page."""

import os
from datetime import datetime

import streamlit as st

import src.dialog as _dialog
import src.images as _images
import src.ssh as _ssh
from src.config import save_config
from src.constants import DEVICE_SIZES, GRID_COLUMNS, SUSPENDED_PNG_PATH
from src.models import Device
from src.ui_common import (
    deferred_toast,
    normalise_filename,
    rainbow_divider,
    require_device,
    send_suspended_png,
)

# ── Image card ────────────────────────────────────────────────────────────────


def _render_image_card(img_name, selected_name, device, config, save_config, add_log):
    """Render one image card: name/rename button, thumbnail, and action controls."""
    img_data = _images.load_device_image(selected_name, img_name)
    star_icon = ":material/star:" if device.is_preferred(img_name) else None

    # ── name / inline rename ──────────────────────────────────────────────
    if st.session_state.get("img_renaming") == img_name:

        def do_rename(_old=img_name):
            raw = st.session_state.get(f"rename_input_{_old}", "").strip()
            new_name = normalise_filename(raw) if raw else None
            if new_name and new_name != _old:
                _images.rename_device_image(selected_name, _old, new_name)
                if device.is_preferred(_old):
                    device.set_preferred(new_name)
                    config["devices"][selected_name] = device.to_dict()
                    save_config(config)
                    add_log(
                        f"Preferred image renamed '{_old}' \u2192 '{new_name}' for '{selected_name}'"
                    )
                add_log(f"Renamed image '{_old}' to '{new_name}' for '{selected_name}'")
            st.session_state["img_renaming"] = None

        with st.form(key=f"img_rename_form_{img_name}", border=False):
            col_in, col_btn = st.columns([3, 1], vertical_alignment="center", gap="xxsmall")
            with col_in:
                st.text_input(
                    "Renommer l'image",
                    value="",
                    placeholder=os.path.splitext(img_name)[0],
                    key=f"rename_input_{img_name}",
                    label_visibility="collapsed",
                )
            with col_btn:
                st.form_submit_button(
                    ":material/check:",
                    on_click=do_rename,
                    width="stretch",
                )
    else:
        bare = os.path.splitext(img_name)[0]
        display_name = bare if len(bare) <= 13 else bare[:10] + "..."
        if st.button(
            f"**{display_name}**",
            key=f"name_{img_name}",
            help="Cliquez pour renommer",
            icon=star_icon,
            type="tertiary",
            width="stretch",
        ):
            st.session_state["img_renaming"] = img_name
            st.rerun()

    st.image(img_data, width="stretch")

    # Deletion confirmation
    if st.session_state.get("img_pending_delete") == img_name:
        _dialog.confirm(
            "Confirmer la suppression",
            f"Confirmez-vous la suppression de {img_name} ?",
            key="confirm_del_img",
        )
        result = st.session_state.get("confirm_del_img")
        if result is True:
            _images.delete_device_image(selected_name, img_name)
            if device.is_preferred(img_name):
                device.set_preferred(None)
                config["devices"][selected_name] = device.to_dict()
                save_config(config)
                add_log(
                    f"Preferred image removed for '{selected_name}' because {img_name} was deleted"
                )
            add_log(f"Deleted {img_name} from '{selected_name}'")
            st.session_state.pop("confirm_del_img", None)
            st.session_state["img_pending_delete"] = None
            st.rerun()
        elif result is False:
            st.session_state.pop("confirm_del_img", None)
            st.session_state["img_pending_delete"] = None
            st.rerun()

    # Segmented control
    action_key = f"action_{img_name}"
    option_map = {0: ":material/cloud_upload:", 1: ":material/star:", 2: ":material/delete:"}

    def on_action(_img_name=img_name, _action_key=action_key, _img_data=img_data):
        selection = st.session_state.get(_action_key)
        if selection is None:
            return
        try:
            if selection == 0:
                if send_suspended_png(device, _img_data, _img_name, selected_name, add_log):
                    st.toast(
                        f":green[{_img_name} envoyée à {selected_name} !]",
                        icon=":material/task_alt:",
                    )
                else:
                    st.toast(
                        f":red[Erreur lors de l'envoi de {_img_name}]", icon=":material/error:"
                    )
            elif selection == 1:
                if device.is_preferred(_img_name):
                    device.set_preferred(None)
                    add_log(f"Preferred image removed for '{selected_name}'")
                else:
                    device.set_preferred(_img_name)
                    add_log(f"Preferred image set: {_img_name} for '{selected_name}'")
                config["devices"][selected_name] = device.to_dict()
                save_config(config)
            elif selection == 2:
                st.session_state["img_pending_delete"] = _img_name
        finally:
            st.session_state[_action_key] = None

    st.segmented_control(
        "Actions",
        options=list(option_map.keys()),
        format_func=lambda o: option_map[o],
        key=action_key,
        selection_mode="single",
        label_visibility="hidden",
        on_change=on_action,
        width="stretch",
    )


def _render_upload_section(selected_name, device, add_log):
    """Render the 'add an image' column: auto-save on upload, then ask to send."""
    width, height = DEVICE_SIZES[device.resolve_type()]

    st.subheader("Ajouter une image", divider="rainbow")

    uploader_key = f"img_uploader_{selected_name}_{st.session_state.get(f'img_uploader_rev_{selected_name}', 0)}"
    uploaded_file = st.file_uploader(
        f"Glisser une image ici (sera convertie en PNG {width}x{height})",
        type=["png", "jpg", "jpeg"],
        key=uploader_key,
    )
    if not uploaded_file:
        return

    # Auto-save once; guard against re-processing on every rerun with the same file
    upload_key = f"img_last_upload_{selected_name}"
    if st.session_state.get(upload_key) != uploaded_file.name:
        img_data = _images.process_image(uploaded_file, width, height)
        filename = normalise_filename(uploaded_file.name)
        _images.save_device_image(selected_name, img_data, filename)
        add_log(f"Image saved locally: {filename} for '{selected_name}'")
        deferred_toast(f"Image sauvegardée : {filename}", ":material/task_alt:")
        st.session_state[upload_key] = uploaded_file.name
        st.session_state[f"img_send_data_{selected_name}"] = (img_data, filename)
        _dialog.confirm(
            "Envoyer sur la tablette ?",
            f"L'image a été sauvegardée localement.\nVoulez-vous aussi l'envoyer sur **{selected_name}** ?",
            key=f"img_send_confirm_{selected_name}",
        )

    def _reset_uploader():
        """Bump the revision counter to remount the file_uploader as empty."""
        rev_key = f"img_uploader_rev_{selected_name}"
        st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1
        st.session_state.pop(upload_key, None)

    result = st.session_state.get(f"img_send_confirm_{selected_name}")
    if result is True:
        img_data, filename = st.session_state.get(f"img_send_data_{selected_name}", (None, None))
        if img_data and filename:
            if send_suspended_png(device, img_data, filename, selected_name, add_log):
                deferred_toast(f"{filename} envoyée sur {selected_name} !", ":material/task_alt:")
            else:
                deferred_toast("Erreur lors de l'envoi.", ":material/error:")
        st.session_state.pop(f"img_send_confirm_{selected_name}", None)
        st.session_state.pop(f"img_send_data_{selected_name}", None)
        _reset_uploader()
        st.rerun()
    elif result is False:
        st.session_state.pop(f"img_send_confirm_{selected_name}", None)
        st.session_state.pop(f"img_send_data_{selected_name}", None)
        _reset_uploader()
        st.rerun()


# ── Page ─────────────────────────────────────────────────────────────────────

st.title(":material/image: Images")
rainbow_divider()

config = st.session_state.get("config", {})
add_log = st.session_state.get("add_log", lambda msg: None)
selected_name = st.session_state.get("selected_name")

DEVICES = config.get("devices", {})

require_device(DEVICES, selected_name)

device = Device.from_dict(selected_name, DEVICES[selected_name])

stored_images = _images.list_device_images(selected_name)

if stored_images:
    st.markdown(
        "Retrouvez ci-dessous toutes les images enregistrées pour cette tablette. "
        "Cliquez sur le **nom** d'une image pour la renommer. "
        "Les trois boutons sous chaque image permettent de l'**envoyer comme écran de veille** "
        "(:material/cloud_upload:), de la définir comme **image préférée** (:material/star:) "
        "— utilisée en priorité lors d'un déploiement — ou de la **supprimer** (:material/delete:). "
        "En bas de page, vous pouvez **récupérer l'image actuellement affichée sur la tablette** "
        "ou **ajouter une nouvelle image depuis votre ordinateur** — elle sera automatiquement "
        "convertie au bon format et aux bonnes dimensions."
    )
    st.divider()

    for row_start in range(0, len(stored_images), GRID_COLUMNS):
        row_items = stored_images[row_start : row_start + GRID_COLUMNS]
        cols = st.columns(GRID_COLUMNS, gap="medium")
        for col_idx, img_name in enumerate(row_items):
            with cols[col_idx]:
                _render_image_card(img_name, selected_name, device, config, save_config, add_log)
        if row_start + GRID_COLUMNS < len(stored_images):
            st.divider()
else:
    st.info(
        "Aucune image enregistrée pour cette tablette. "
        "Importez l'image actuellement sur la tablette ou ajoutez-en une depuis votre ordinateur ci-dessous.",
        icon=":material/image:",
    )

col1, col2 = st.columns(2, gap="large")
with col1:
    st.subheader("Récupérer l'image actuelle", divider="rainbow")
    if st.button(
        "Importer depuis la tablette",
        key=f"ui_import_from_tablet_{selected_name}",
        icon=":material/download:",
        width="stretch",
        help="Télécharger l'image actuelle de l'écran de veille depuis la tablette",
    ):
        try:
            img_data = _ssh.download_file_ssh(device.ip, device.password or "", SUSPENDED_PNG_PATH)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}.png"
            _images.save_device_image(selected_name, img_data, filename)
            add_log(f"suspended.png from téléchargé de '{selected_name}' sous {filename}")
            st.toast(f":green[Image sauvegardée : {filename}]", icon=":material/task_alt:")
            st.rerun()
        except Exception as e:
            st.error(f"Erreur : {str(e)}", icon=":material/error:")
            add_log(
                f"Erreur lors du téléchargement de suspended.png depuis '{selected_name}': {str(e)}"
            )

with col2:
    _render_upload_section(selected_name, device, add_log)
