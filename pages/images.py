"""Image library page."""

import os
from datetime import datetime

import streamlit as st

import src.dialog as _dialog
import src.images as _images
import src.ssh as _ssh
from src.config import save_config, truncate_display_name
from src.constants import DEVICE_SIZES, GRID_COLUMNS, SUSPENDED_PNG_PATH
from src.i18n import _
from src.models import Device
from src.ui_common import (
    deferred_toast,
    normalise_filename,
    rainbow_divider,
    require_device,
    send_suspended_png,
)

# ── Image card ────────────────────────────────────────────────────────────────


def _render_image_card(img_name, selected_name, device, config, add_log):
    """Render one image card: name/rename button, thumbnail, and action controls."""
    img_data = _images.load_device_image(selected_name, img_name)
    star_icon = ":material/star:" if device.is_preferred(img_name) else None

    # ── name / inline rename ──────────────────────────────────────────────
    if st.session_state.get("img_renaming") == img_name:

        def do_rename(_old=img_name):
            raw = st.session_state.get(f"rename_input_{_old}", "").strip()
            new_name = normalise_filename(raw) if raw else None
            if new_name and new_name != _old:
                if new_name in _images.list_device_images(selected_name):
                    st.session_state["img_pending_rename"] = (_old, new_name)
                    return
                _images.rename_device_image(selected_name, _old, new_name)
                if device.is_preferred(_old):
                    device.set_preferred(new_name)
                    config["devices"][selected_name] = device.to_dict()
                    save_config(config)
                    add_log(
                        f"Preferred image renamed '{_old}' \u2192 '{new_name}' for '{selected_name}'"
                    )
                add_log(f"Renamed image '{_old}' to '{new_name}' for '{selected_name}'")
                deferred_toast(f"Image renomm\u00e9e : '{new_name}'", ":material/task_alt:")

        with st.form(key=f"img_rename_form_{img_name}", border=False):
            col_in, col_btn = st.columns([3, 1], vertical_alignment="center", gap="xxsmall")
            with col_in:
                st.text_input(
                    _("Rename image"),
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
        display_name = truncate_display_name(bare)
        if st.button(
            f"**{display_name}**",
            key=f"name_{img_name}",
            help=_("Click to rename"),
            icon=star_icon,
            type="tertiary",
            width="stretch",
        ):
            st.session_state["img_renaming"] = img_name
            st.rerun()

    st.image(img_data, width="stretch")

    # Rename overwrite confirmation
    pending_rename = st.session_state.get("img_pending_rename")
    if pending_rename and pending_rename[0] == img_name:
        _old_r, _new_r = pending_rename
        _dialog.confirm(
            _("Confirm replacement"),
            _("'{new}' already exists. Replace this file?").format(new=_new_r),
            key="confirm_rename_img",
        )
        result = st.session_state.get("confirm_rename_img")
        if result is True:
            _images.rename_device_image(selected_name, _old_r, _new_r)
            if device.is_preferred(_old_r):
                device.set_preferred(_new_r)
                config["devices"][selected_name] = device.to_dict()
                save_config(config)
                add_log(
                    f"Preferred image renamed '{_old_r}' \u2192 '{_new_r}' for '{selected_name}'"
                )
            add_log(f"Renamed image '{_old_r}' to '{_new_r}' for '{selected_name}'")
            deferred_toast(f"Image renommée : '{_new_r}'", ":material/task_alt:")
            st.session_state.pop("confirm_rename_img", None)
            st.session_state["img_pending_rename"] = None
            st.session_state["img_renaming"] = None
            st.rerun()
        elif result is False:
            st.session_state.pop("confirm_rename_img", None)
            st.session_state["img_pending_rename"] = None
            st.session_state["img_renaming"] = None
            st.rerun()

    # Deletion confirmation
    if st.session_state.get("img_pending_delete") == img_name:
        _dialog.confirm(
            _("Confirm deletion"),
            _("Confirm deletion of {name}?").format(name=img_name),
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
            deferred_toast(f"{img_name} supprimée", ":material/delete:")
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
                    deferred_toast(
                        _("{name} sent to {device}").format(name=_img_name, device=selected_name),
                        ":material/task_alt:",
                    )
                else:
                    deferred_toast(
                        _("Error sending {name}").format(name=_img_name), ":material/error:"
                    )
            elif selection == 1:
                if device.is_preferred(_img_name):
                    device.set_preferred(None)
                    add_log(f"Preferred image removed for '{selected_name}'")
                    deferred_toast(_("Preferred image removed"), ":material/star_border:")
                else:
                    device.set_preferred(_img_name)
                    add_log(f"Preferred image set: {_img_name} for '{selected_name}'")
                    deferred_toast(
                        _("{name} set as preferred image").format(name=_img_name), ":material/star:"
                    )
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

    st.subheader(_("Add an image"), divider="rainbow")

    uploader_key = f"img_uploader_{selected_name}_{st.session_state.get(f'img_uploader_rev_{selected_name}', 0)}"
    uploaded_file = st.file_uploader(
        _("Drag an image here (will be converted to PNG {w}x{h})").format(w=width, h=height),
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
            _("Send to tablet?"),
            _("Image saved locally.\nDo you also want to send it to **{device}**?").format(
                device=selected_name
            ),
            key=f"img_send_confirm_{selected_name}",
            cancel_label=_("No"),
            confirm_label=_("Yes"),
            help_text=_("You can still send it later from the image actions."),
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
                deferred_toast(
                    _("{name} sent to {device}").format(name=filename, device=selected_name),
                    ":material/task_alt:",
                )
            else:
                deferred_toast(_("Error sending image."), ":material/error:")
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

st.title(_(":material/image: Images"))
rainbow_divider()

config = st.session_state.get("config", {})
add_log = st.session_state.get("add_log", lambda msg: None)
selected_name = st.session_state.get("selected_name")

DEVICES = config.get("devices", {})

require_device(DEVICES, selected_name)
assert isinstance(selected_name, str)

device = Device.from_dict(selected_name, DEVICES[selected_name])

stored_images = _images.list_device_images(selected_name)

if stored_images:
    st.markdown(
        _(
            "Below you will find all images saved for this tablet. "
            "Click the **name** of an image to rename it. "
            "The three buttons under each image let you **send it as the suspended image** "
            "(:material/cloud_upload:), set it as the **preferred image** (:material/star:) "
            "— used as priority during deployment — or **delete** it (:material/delete:). "
            "At the bottom of the page you can **retrieve the image currently displayed on the tablet** "
            "or **add a new image from your computer** — it will be automatically converted to the correct format and dimensions."
        )
    )
    st.divider()

    for row_start in range(0, len(stored_images), GRID_COLUMNS):
        row_items = stored_images[row_start : row_start + GRID_COLUMNS]
        cols = st.columns(GRID_COLUMNS, gap="medium")
        for col_idx, img_name in enumerate(row_items):
            with cols[col_idx]:
                _render_image_card(img_name, selected_name, device, config, add_log)
        if row_start + GRID_COLUMNS < len(stored_images):
            st.divider()
else:
    st.info(
        _(
            "No images saved for this tablet. "
            "Import the image currently on the tablet or add one from your computer below."
        ),
        icon=":material/image:",
    )

col1, col2 = st.columns(2, gap="large")
with col1:
    st.subheader(_("Get current image"), divider="rainbow")
    if st.button(
        _("Import from tablet"),
        key=f"ui_import_from_tablet_{selected_name}",
        icon=":material/download:",
        width="stretch",
        help=_("Download the current suspended image from the tablet"),
    ):
        img_data, err = _ssh.download_file_ssh(device.ip, device.password or "", SUSPENDED_PNG_PATH)
        if img_data is None:
            st.error(_("Error: {err}").format(err=err), icon=":material/error:")
            add_log(f"Error downloading suspended.png from '{selected_name}': {err}")
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}.png"
            _images.save_device_image(selected_name, img_data, filename)
            add_log(f"suspended.png downloaded from '{selected_name}' as {filename}")
            deferred_toast(_("Image saved: {name}").format(name=filename), ":material/task_alt:")
            st.rerun()

with col2:
    _render_upload_section(selected_name, device, add_log)
