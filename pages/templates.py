"""Template library and editor page."""

import os

import streamlit as st

# noinspection PyProtectedMember
from src.i18n import _
from src.manifest_templates import get_device_manifest_path
from src.models import Device
from src.template_editor_ui import (
    load_template_into_editor,
    render_editor_panel,
    reset_editor_for_new,
)
from src.template_list_ui import refresh_sync_snapshot_after_remote_change, render_left_panel
from src.template_sync import fetch_and_init_templates
from src.templates import refresh_local_manifest
from src.ui_common import deferred_toast, init_page, rainbow_divider

_SENTINEL_NEW = "__new__"
_SESSION_SELECTED_UUID_KEY = "tpl_selected_uuid"
_TEMPLATE_DEVICE_SCOPED_KEYS = (
    "tpl_filter_text",
    "tpl_filter_cats",
    "tpl_filter_labels",
    "tpl_filter_orientation",
    "tpl_pill_expanded_rows",
)


def _selected_template_uuid() -> str | None:
    selected = st.session_state.get(_SESSION_SELECTED_UUID_KEY)
    return str(selected) if isinstance(selected, str) else None


def _set_selected_template_uuid(template_uuid: str | None) -> None:
    st.session_state[_SESSION_SELECTED_UUID_KEY] = template_uuid


# ── Page ──────────────────────────────────────────────────────────────────────

st.title(_(":material/description: Templates"))
rainbow_divider()

config, selected_name, DEVICES = init_page()
add_log_fn = st.session_state.get("add_log", lambda msg: None)
assert isinstance(selected_name, str)

current_device = Device.from_dict(selected_name, DEVICES[selected_name])

# Reset selection and filter state when device changes
if st.session_state.get("tpl_device") != current_device.name:
    st.session_state["tpl_device"] = current_device.name
    _set_selected_template_uuid(None)
    for _k in _TEMPLATE_DEVICE_SCOPED_KEYS:
        st.session_state.pop(_k, None)

# Guard: not initialized yet → show init screen, not the split layout
manifest_path = get_device_manifest_path(current_device.name)
if not os.path.exists(manifest_path):
    st.warning(
        _(
            "The template list for this device has not been imported yet. "
            "Turn on the device and click the button below to start."
        ),
        icon=":material/backup:",
    )

    def _on_init_templates():
        ok, msg = fetch_and_init_templates(current_device, overwrite_backup=False)
        if ok:
            add_log_fn(f"Templates initialized for '{current_device.name}' : {msg}")
            refresh_sync_snapshot_after_remote_change(
                current_device,
                add_log_fn,
                "initialized_from_device",
            )
            deferred_toast(_("Templates imported successfully"), ":material/task_alt:")
        else:
            add_log_fn(f"Error initializing templates for '{current_device.name}' : {msg}")
            st.session_state["_tpl_page_init_error"] = msg

    st.button(
        _("Initialize templates from this device"),
        key=f"tpl_fetch_backup_{current_device.name}",
        type="primary",
        icon=":material/download:",
        help=_("Import templates from this device and initialize local metadata"),
        on_click=_on_init_templates,
    )
    _page_init_error = st.session_state.pop("_tpl_page_init_error", None)
    if _page_init_error:
        st.error(_("Error: {msg}").format(msg=_page_init_error), icon=":material/error:")
    st.stop()

refresh_local_manifest(current_device.name)

st.markdown(
    _(
        "Browse and manage templates for this device in the **left panel**.  \n"
        "Click a template to open it in the **editor** on the right, where you can update its name, category, labels, icon, and body.  \n"
        "Use **:material/add: New template** to create one from scratch.  \n"
        "When you're done editing, click **:material/save: Save** to save locally, then **:material/sync: Sync now** to push all changes to the device."
    )
)
st.divider()

# ── Main split layout: list (left) | editor (right) ──────────────────────────

list_col, editor_col = st.columns([1, 3], gap="large")

with list_col:

    def _on_new_template():
        reset_editor_for_new()
        _set_selected_template_uuid(_SENTINEL_NEW)

    def _on_select_template(uuid: str):
        load_template_into_editor(current_device.name, uuid)
        _set_selected_template_uuid(uuid)

    def _on_deselect_template():
        _set_selected_template_uuid(None)

    render_left_panel(
        current_device,
        add_log_fn,
        sentinel_new=_SENTINEL_NEW,
        on_new=_on_new_template,
        on_select=_on_select_template,
        on_deselect=_on_deselect_template,
        selected_uuid=_selected_template_uuid,
    )

with editor_col:

    def _on_editor_select(uuid: str):
        _set_selected_template_uuid(uuid)

    def _on_editor_deselect():
        _set_selected_template_uuid(None)

    render_editor_panel(
        current_device,
        add_log_fn,
        sentinel_new=_SENTINEL_NEW,
        selected_uuid=_selected_template_uuid,
        on_select=_on_editor_select,
        on_deselect=_on_editor_deselect,
    )
