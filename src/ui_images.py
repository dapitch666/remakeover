"""Image library page rendering."""

import os
from datetime import datetime

import streamlit as st

import src.images as _images
import src.ssh as _ssh
import src.dialog as _dialog
from src.models import Device
from src.ui_common import _normalise_filename, _send_suspended_png
from src.constants import SUSPENDED_PNG_PATH


# ── Image card ────────────────────────────────────────────────────────────────

def _render_image_card(img_name, selected_name, device, config, save_config, add_log):
    """Render one image card: name/rename button, thumbnail, and action controls."""
    img_data = _images.load_device_image(selected_name, img_name)
    star_icon = ":material/star:" if device.is_preferred(img_name) else None

    # ── name / inline rename ──────────────────────────────────────────────
    if st.session_state.get("img_renaming") == img_name:
        def do_rename(_old=img_name):
            raw = st.session_state.get(f"rename_input_{_old}", "").strip()
            new_name = _normalise_filename(raw) if raw else None
            if new_name and new_name != _old:
                _images.rename_device_image(selected_name, _old, new_name)
                if device.is_preferred(_old):
                    device.set_preferred(new_name)
                    config["devices"][selected_name] = device.to_dict()
                    save_config(config)
                    add_log(f"Preferred image renamed '{_old}' \u2192 '{new_name}' for '{selected_name}'")
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
                add_log(f"Preferred image removed for '{selected_name}' because {img_name} was deleted")
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
                if _send_suspended_png(device, _img_data, _img_name, selected_name, add_log):
                    st.toast(f"{_img_name} envoyée à {selected_name} !", icon=":material/task_alt:")
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
    )


def _render_upload_section(selected_name, device, width, height, config, save_config, add_log):
    """Render the 'add an image' column: file uploader with save / send buttons."""
    st.subheader("Ajouter une image", divider="rainbow")
    uploaded_file = st.file_uploader(
        f"Glisser une image ici (sera convertie en PNG {width}x{height})",
        type=["png", "jpg", "jpeg"],
    )
    if not uploaded_file:
        return

    col_save, col_send = st.columns(2)
    with col_save:
        if st.button("Sauvegarder", key=f"ui_save_uploaded_{selected_name}", icon=":material/save:", help="Sauvegarder l'image localement"):
            img_data = _images.process_image(uploaded_file, width, height)
            filename = _normalise_filename(uploaded_file.name)
            _images.save_device_image(selected_name, img_data, filename)
            add_log(f"Image uploaded and saved: {filename} for '{selected_name}'")
            st.toast(f"Image sauvegardée : {filename}", icon=":material/task_alt:")
            st.rerun()

    with col_send:
        if st.button(f"Envoyer sur {selected_name}", key=f"ui_send_uploaded_{selected_name}", icon=":material/cloud_upload:", help=f"Envoyer l'image sur {selected_name} et la sauvegarder localement"):
            img_data = _images.process_image(uploaded_file, width, height)
            filename = _normalise_filename(uploaded_file.name)
            _images.save_device_image(selected_name, img_data, filename)
            if _send_suspended_png(device, img_data, filename, selected_name, add_log):
                st.toast(f"{filename} envoyée et sauvegardée !", icon=":material/task_alt:")
                st.rerun()
            else:
                st.toast("Erreur lors de l'envoi", icon=":material/error:")


# ── Page entry point ──────────────────────────────────────────────────────────

def render_page(selected_name, device, width, height, config, save_config, add_log):
    stored_images = _images.list_device_images(selected_name)

    if stored_images:
        with st.expander("Aide — Actions des images (cliquer pour développer)", expanded=False):
            st.markdown(":material/cloud_upload: **Envoyer** — Mettre l'image comme écran de veille sur la tablette  ")
            st.markdown(":material/star: **Favori** — Définir ou supprimer l'image préférée  ")
            st.markdown(":material/delete: **Supprimer** — Effacer l'image localement  ")

        cols = st.columns(4, gap="medium")
        for idx, img_name in enumerate(stored_images):
            with cols[idx % 4]:
                _render_image_card(img_name, selected_name, device, config, save_config, add_log)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Récupérer l'image actuelle", divider="rainbow")
        if st.button("Importer depuis la tablette", key=f"ui_import_from_tablet_{selected_name}", icon=":material/download:", width='stretch', help="Télécharger l'image actuelle de l'écran de veille depuis la tablette"):
            try:
                img_data = _ssh.download_file_ssh(device.ip, device.password or '', SUSPENDED_PNG_PATH)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{timestamp}.png"
                _images.save_device_image(selected_name, img_data, filename)
                add_log(f"suspended.png from téléchargé de '{selected_name}' sous {filename}")
                st.toast(f"Image sauvegardée : {filename}", icon=":material/task_alt:")
                st.rerun()
            except Exception as e:
                st.error(f"Erreur : {str(e)}", icon=":material/error:")
                add_log(f"Erreur lors du téléchargement de suspended.png depuis '{selected_name}': {str(e)}")

    with col2:
        _render_upload_section(selected_name, device, width, height, config, save_config, add_log)
