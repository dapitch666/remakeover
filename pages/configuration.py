"""Configuration page."""

import ipaddress
import os
import shutil

import streamlit as st

import src.dialog as _dialog
from src.config import get_device_data_dir, save_config
from src.constants import DEFAULT_DEVICE_TYPE, DEVICE_SIZES
from src.i18n import _
from src.ui_common import deferred_toast, rainbow_divider

config = st.session_state.get("config", {})
add_log = st.session_state.get("add_log", lambda msg: None)

st.title(_(":material/settings: Device Configuration"))
rainbow_divider()

DEVICES = config.get("devices", {})
selected_name = st.session_state.get("selected_name")

# Determine whether we're in "create new" mode
creating_new = st.session_state.get("config_creating_new", False)

if DEVICES and selected_name in DEVICES and not creating_new:
    assert isinstance(selected_name, str)
    col_title, col_btn = st.columns([3, 1], vertical_alignment="bottom")
    with col_title:
        st.subheader(_("Edit: {name}").format(name=selected_name), divider="rainbow")
    with col_btn:
        if st.button(_("New device"), key="ui_config_new", icon=":material/add:", width="stretch"):
            st.session_state["config_creating_new"] = True
            st.rerun()
    device_name = selected_name
    device_config = DEVICES[selected_name].copy()
    is_new = False
else:
    st.subheader(_("Create a new device"), divider="rainbow")
    device_name = st.text_input(_("Device name"), "")
    device_config = {
        "ip": "",
        "password": "",
        "device_type": DEFAULT_DEVICE_TYPE,
        "templates": True,
        "carousel": True,
    }
    is_new = True

col1, col2 = st.columns(2)
with col1:
    ip = st.text_input(_("IP Address"), device_config.get("ip", ""), placeholder="192.168.x.x")
    password = st.text_input(_("SSH Password"), device_config.get("password", ""), type="password")

with col2:
    _device_types = list(DEVICE_SIZES.keys())
    _current_type = device_config.get("device_type", DEFAULT_DEVICE_TYPE)
    _type_index = _device_types.index(_current_type) if _current_type in _device_types else 0
    device_type = st.selectbox(
        _("Tablet type"),
        _device_types,
        index=_type_index,
    )
    templates = st.toggle(_("Enable templates"), value=device_config.get("templates", True))
    carousel = st.toggle(_("Disable carousel"), value=device_config.get("carousel", True))

st.info(
    _(
        "💡 To find the IP address and root password of your reMarkable, enable developer mode if needed, go to Settings > Help > About > Copyrights and licenses, then scroll the right column if necessary."
    )
)

col_save, col_delete = st.columns([3, 1])
with col_save:
    if st.button(
        _("Save"),
        key=f"ui_config_save_{device_name}",
        width="stretch",
        icon=":material/save:",
        help=_("Save device configuration"),
    ):
        if is_new and not device_name:
            st.error(_("Please enter a name for this device."), icon=":material/error:")
        elif is_new and device_name in DEVICES:
            st.error(
                _("A device named '{name}' already exists. Choose a different name.").format(
                    name=device_name
                ),
                icon=":material/error:",
            )
        elif not ip.strip():
            st.error(_("Please enter an IP address."), icon=":material/error:")
        else:
            try:
                ipaddress.ip_address(ip.strip())
            except ValueError:
                st.error(
                    _("'{ip}' is not a valid IP address (e.g. 192.168.1.100).").format(ip=ip),
                    icon=":material/error:",
                )
            else:
                new_config = {
                    "ip": ip.strip(),
                    "password": password,
                    "device_type": device_type,
                    "templates": templates,
                    "carousel": carousel,
                }
                config["devices"][device_name] = new_config
                save_config(config)
                add_log(f"Configuration saved for '{device_name}'")
                deferred_toast(
                    _("Configuration of '{name}' saved").format(name=device_name),
                    ":material/task_alt:",
                )
                st.session_state["pending_selected_tablet"] = device_name
                st.session_state.pop("config_creating_new", None)
                st.rerun()

with col_delete:
    if not is_new and st.button(
        _("Delete"),
        key=f"ui_config_delete_{device_name}",
        type="primary",
        width="stretch",
        icon=":material/delete:",
        help=_("Delete this device and its local images"),
    ):
        st.session_state["pending_delete_device"] = device_name
        st.rerun()
    if (
        is_new
        and selected_name in DEVICES
        and st.button(_("Cancel"), key="ui_config_cancel", width="stretch", icon=":material/close:")
    ):
        st.session_state.pop("config_creating_new", None)
        st.rerun()

if st.session_state.get("pending_delete_device") == device_name:
    _dialog.confirm(
        _("Confirm deletion"),
        _(
            "Confirm deletion of device '{name}'? This will also remove its local images and templates."
        ).format(name=device_name),
        key=f"del_device_{device_name}",
    )
    if st.session_state.get(f"del_device_{device_name}") is True:
        device_data_dir = get_device_data_dir(device_name)
        if os.path.exists(device_data_dir):
            try:
                shutil.rmtree(device_data_dir)
                add_log(f"Device data directory removed for '{device_name}'")
            except OSError as e:
                add_log(f"Could not fully remove data dir for '{device_name}': {e}")
        if device_name in config.get("devices", {}):
            del config["devices"][device_name]
            save_config(config)
        add_log(f"Configuration deleted for '{device_name}'")
        deferred_toast(_("'{name}' deleted").format(name=device_name), ":material/task_alt:")
        del st.session_state["pending_delete_device"]
        del st.session_state[f"del_device_{device_name}"]
        st.rerun()
    elif st.session_state.get(f"del_device_{device_name}") is False:
        del st.session_state[f"del_device_{device_name}"]
        del st.session_state["pending_delete_device"]
        st.rerun()
