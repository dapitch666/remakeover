"""Image library page."""

import os
from datetime import datetime

import streamlit as st

import src.dialog as _dialog
import src.images as _images
import src.ssh as _ssh
from src.config import save_config, truncate_display_name
from src.constants import DEVICE_SIZES, GRID_COLUMNS, SUSPENDED_PNG_PATH

# noinspection PyProtectedMember
from src.i18n import _
from src.images import rollback_sleep_screen, send_suspended_png
from src.models import Device
from src.ui_common import (
    deferred_toast,
    handle_rename_confirmation,
    init_page,
    normalise_filename,
    rainbow_divider,
)

# ── Image card ────────────────────────────────────────────────────────────────


def _render_image_card(img_name, device, add_log, config):
    """Render one image card: name/rename button, thumbnail, and action controls."""
    img_data = _images.load_device_image(device.name, img_name)

    # ── name / inline rename ──────────────────────────────────────────────
    if st.session_state.get("img_renaming") == img_name:

        def do_rename(old):
            raw = st.session_state.get(f"rename_input_{old}", "").strip()
            new_name = normalise_filename(raw) if raw else None
            if new_name and new_name != old:
                if new_name in _images.list_device_images(device.name):
                    st.session_state["img_pending_rename"] = (old, new_name)
                    return
                try:
                    _images.rename_device_image(device.name, old, new_name)
                    add_log(f"Renamed image '{old}' to '{new_name}' for '{device.name}'")
                    deferred_toast(
                        _("Image renamed from '{o}' to {n}").format(o=old, n=new_name),
                        ":material/task_alt:",
                    )
                except OSError as _err:
                    add_log(f"Error renaming image '{old}' for '{device.name}': {_err}")
                    deferred_toast(
                        _("Error renaming image '{o}'").format(o=old), ":material/error:"
                    )

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
                    args=(img_name,),
                    width="stretch",
                )
    else:
        bare = os.path.splitext(img_name)[0]
        display_name = truncate_display_name(bare)

        def _enter_rename(name):
            st.session_state["img_renaming"] = name

        st.button(
            f"**{display_name}**",
            key=f"name_{img_name}",
            help=_("Click to rename"),
            type="tertiary",
            width="stretch",
            on_click=_enter_rename,
            args=(img_name,),
        )

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

        def _do_rename_img() -> None:
            try:
                _images.rename_device_image(device.name, _old_r, _new_r)
                add_log(f"Renamed image '{_old_r}' to '{_new_r}' for '{device.name}'")
                deferred_toast(
                    _("Image renamed from '{o}' to {n}").format(o=_old_r, n=_new_r),
                    ":material/task_alt:",
                )
            except OSError as _err:
                add_log(f"Error renaming image '{_old_r}' for '{device.name}': {_err}")
                deferred_toast(_("Error renaming image '{o}'").format(o=_old_r), ":material/error:")

        handle_rename_confirmation(
            "confirm_rename_img", "img_pending_rename", "img_renaming", _do_rename_img
        )

    # Deletion confirmation
    if st.session_state.get("img_pending_delete") == img_name:
        _dialog.confirm(
            _("Confirm deletion"),
            _("Confirm deletion of {name}?").format(name=img_name),
            key="confirm_del_img",
        )
        result = st.session_state.get("confirm_del_img")
        if result is True:
            try:
                _images.delete_device_image(device.name, img_name)
                add_log(f"Deleted {img_name} from '{device.name}'")
                deferred_toast(
                    _("{img_name} deleted").format(img_name=img_name), ":material/delete:"
                )
            except OSError as e:
                add_log(f"Error deleting {img_name} from '{device.name}': {e}")
                deferred_toast(
                    _("Error deleting {img_name}").format(img_name=img_name), ":material/error:"
                )
            st.session_state.pop("confirm_del_img", None)
            st.session_state["img_pending_delete"] = None
            st.rerun()
        elif result is False:
            st.session_state.pop("confirm_del_img", None)
            st.session_state["img_pending_delete"] = None
            st.rerun()

    # Segmented control
    action_key = f"action_{img_name}"
    option_map = {0: ":material/cloud_upload:", 1: ":material/delete:"}

    def on_action(name, a_key, data):
        selection = st.session_state.get(a_key)
        if selection is None:
            return
        try:
            if selection == 0:
                if send_suspended_png(device, data, name, add_log):
                    config["devices"][device.name]["sleep_screen_enabled"] = True
                    save_config(config)
                    deferred_toast(
                        _("{name} sent to {device}").format(name=name, device=device.name),
                        ":material/task_alt:",
                    )
                else:
                    deferred_toast(_("Error sending {name}").format(name=name), ":material/error:")
            elif selection == 1:
                st.session_state["img_pending_delete"] = name
        finally:
            st.session_state[a_key] = None

    st.segmented_control(
        "Actions",
        options=list(option_map.keys()),
        format_func=lambda o: option_map[o],
        key=action_key,
        selection_mode="single",
        label_visibility="hidden",
        on_change=on_action,
        args=(img_name, action_key, img_data),
        width="stretch",
    )


def _render_upload_section(device, add_log):
    """Render the 'add an image' column: auto-save on upload, then ask to send."""
    width, height = DEVICE_SIZES[device.resolve_type()]

    st.subheader(_("Add an image"), divider="rainbow")

    uploader_key = (
        f"img_uploader_{device.name}_{st.session_state.get(f'img_uploader_rev_{device.name}', 0)}"
    )
    uploaded_file = st.file_uploader(
        _("Drag an image here (will be converted to PNG {w}x{h})").format(w=width, h=height),
        type=["png", "jpg", "jpeg"],
        key=uploader_key,
    )
    if not uploaded_file:
        return

    # Auto-save once; guard against re-processing on every rerun with the same file
    upload_key = f"img_last_upload_{device.name}"
    if st.session_state.get(upload_key) != uploaded_file.name:
        img_data = _images.process_image(uploaded_file, width, height)
        filename = normalise_filename(uploaded_file.name)
        _images.save_device_image(device.name, img_data, filename)
        add_log(f"Image saved locally: {filename} for '{device.name}'")
        deferred_toast(
            _("Image saved: {filename}").format(filename=filename), ":material/task_alt:"
        )
        st.session_state[upload_key] = uploaded_file.name
        st.session_state[f"img_send_data_{device.name}"] = (img_data, filename)
        _dialog.confirm(
            _("Send to device?"),
            _("Image saved locally.\nDo you also want to send it to **{device}**?").format(
                device=device.name
            ),
            key=f"img_send_confirm_{device.name}",
            cancel_label=_("No"),
            confirm_label=_("Yes"),
            help_text=_("You can still send it later from the image actions."),
        )

    def _reset_uploader():
        """Bump the revision counter to remount the file_uploader as empty."""
        rev_key = f"img_uploader_rev_{current_device.name}"
        st.session_state[rev_key] = st.session_state.get(rev_key, 0) + 1
        st.session_state.pop(upload_key, None)

    result = st.session_state.get(f"img_send_confirm_{current_device.name}")
    if result is True:
        img_data, filename = st.session_state.get(
            f"img_send_data_{current_device.name}", (None, None)
        )
        if img_data and filename:
            if send_suspended_png(device, img_data, filename, add_log):
                config["devices"][current_device.name]["sleep_screen_enabled"] = True
                save_config(config)
                deferred_toast(
                    _("{name} sent to {device}").format(name=filename, device=current_device.name),
                    ":material/task_alt:",
                )
            else:
                deferred_toast(_("Error sending image."), ":material/error:")
        st.session_state.pop(f"img_send_confirm_{current_device.name}", None)
        st.session_state.pop(f"img_send_data_{current_device.name}", None)
        _reset_uploader()
        st.rerun()
    elif result is False:
        st.session_state.pop(f"img_send_confirm_{current_device.name}", None)
        st.session_state.pop(f"img_send_data_{current_device.name}", None)
        _reset_uploader()
        st.rerun()


# ── Page ─────────────────────────────────────────────────────────────────────

st.title(_(":material/image: Images"))
rainbow_divider()

config, selected_name, DEVICES = init_page()
add_log_fn = st.session_state.get("add_log", lambda msg: None)
assert isinstance(selected_name, str)

current_device = Device.from_dict(selected_name, DEVICES[selected_name])
stored_images = _images.list_device_images(current_device.name)

if stored_images:
    st.markdown(
        _("""Below you will find all images saved for this device. 
             Click the **name** of an image to rename it.  
             The buttons under each image let you **:material/cloud_upload: send it as the suspended image** 
             or **:material/delete: delete** it.  
             At the bottom of the page you can **retrieve the sleep screen currently installed on the device**, 
             **add a new image from your computer** — it will be automatically converted to the correct format and dimensions. 
             — or **restore the default sleep screen** if you want to remove the custom one and go back to the 
             factory default.
        """)
    )
    st.divider()

    for row_start in range(0, len(stored_images), GRID_COLUMNS):
        row_items = stored_images[row_start : row_start + GRID_COLUMNS]
        cols = st.columns(GRID_COLUMNS, gap="medium")
        for col_idx, image_name in enumerate(row_items):
            with cols[col_idx]:
                _render_image_card(image_name, current_device, add_log_fn, config)
        if row_start + GRID_COLUMNS < len(stored_images):
            st.divider()
else:
    st.info(
        _(
            "No images saved for this device. "
            "Import the sleep screen currently installed on the device or add one from your computer below."
        ),
        icon=":material/image:",
    )

col_add, col_dl, col_restore = st.columns(3)
with col_dl:
    st.subheader(_("Get current image"), divider="rainbow")

    def _on_import_from_device():
        image_data, err = _ssh.download_file_ssh(current_device, SUSPENDED_PNG_PATH)
        if image_data is None:
            st.session_state["_import_img_error"] = err
            add_log_fn(f"Error downloading suspended.png from '{current_device.name}': {err}")
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            _filename = f"{timestamp}.png"
            _images.save_device_image(current_device.name, image_data, _filename)
            add_log_fn(f"suspended.png downloaded from '{current_device.name}' as {_filename}")
            deferred_toast(_("Image saved: {name}").format(name=_filename), ":material/task_alt:")

    st.button(
        _("Import from device"),
        key=f"ui_import_from_device_{current_device.name}",
        icon=":material/download:",
        width="stretch",
        help=(
            _("No custom sleep screen is configured on this device")
            if not current_device.sleep_screen_enabled
            else _("Download the current suspended image from the device")
        ),
        disabled=not current_device.sleep_screen_enabled,
        on_click=_on_import_from_device,
    )
    _import_img_error = st.session_state.pop("_import_img_error", None)
    if _import_img_error:
        st.error(_("Error: {err}").format(err=_import_img_error), icon=":material/error:")

with col_restore:
    st.subheader(_("Restore default"), divider="rainbow")

    _rollback_key = f"img_pending_rollback_{current_device.name}"
    _rollback_confirm_key = f"confirm_rollback_{current_device.name}"

    if st.session_state.get(_rollback_key):
        _dialog.confirm(
            _("Restore default sleep screen?"),
            _(
                "This will remove the custom sleep screen from **{device}** "
                "and restore the factory default."
            ).format(device=current_device.name),
            key=_rollback_confirm_key,
            confirm_label=_("Restore"),
        )
        _rollback_result = st.session_state.get(_rollback_confirm_key)
        if _rollback_result is True:
            if rollback_sleep_screen(current_device, add_log_fn):
                config["devices"][current_device.name]["sleep_screen_enabled"] = False
                save_config(config)
                deferred_toast(
                    _("Sleep screen reset to default on {device}").format(
                        device=current_device.name
                    ),
                    ":material/task_alt:",
                )
            else:
                deferred_toast(_("Error resetting sleep screen."), ":material/error:")
            st.session_state.pop(_rollback_key, None)
            st.session_state.pop(_rollback_confirm_key, None)
            st.rerun()
        elif _rollback_result is False:
            st.session_state.pop(_rollback_key, None)
            st.session_state.pop(_rollback_confirm_key, None)
            st.rerun()

    def _request_rollback(key):
        st.session_state[key] = True

    st.button(
        _("Restore default"),
        key=f"ui_rollback_sleep_{current_device.name}",
        icon=":material/restore:",
        width="stretch",
        help=(
            _("No custom sleep screen is configured on this device")
            if not current_device.sleep_screen_enabled
            else _("Remove the custom sleep screen from the device and restore the factory default")
        ),
        disabled=not current_device.sleep_screen_enabled,
        on_click=_request_rollback,
        args=(_rollback_key,),
    )

with col_add:
    _render_upload_section(current_device, add_log_fn)
