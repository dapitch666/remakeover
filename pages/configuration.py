"""Configuration page."""

import ipaddress
import os
import shutil

import streamlit as st

import src.dialog as _dialog
from src.config import (
    get_device_data_dir_path,
    rename_device_data_dir,
    save_config,
)

# noinspection PyProtectedMember
from src.i18n import _
from src.ssh import detect_device_info
from src.ui_common import deferred_toast, init_page, rainbow_divider

st.title(_(":material/settings: Device Configuration"))
rainbow_divider()

config, selected_name, DEVICES = init_page(require_selected=False)
add_log = st.session_state.get("add_log", lambda msg: None)

# Determine whether we're in "create new" mode
creating_new = st.session_state.get("config_creating_new", False)

if DEVICES and selected_name in DEVICES and not creating_new:
    # assert isinstance(selected_name, str)
    col_title, col_btn = st.columns([3, 1], vertical_alignment="bottom")
    with col_title:
        st.subheader(_("Edit: {name}").format(name=selected_name), divider="rainbow")
    with col_btn:
        if st.button(_("New device"), key="ui_config_new", icon=":material/add:", width="stretch"):
            st.session_state["config_creating_new"] = True
            st.session_state.pop("connection_test_result", None)
            st.rerun()
    device_name: str = selected_name or ""  # `selected_name in DEVICES` above guarantees non-None
    device_config = DEVICES[selected_name].copy()
    is_new = False
else:
    st.subheader(_("Create a new device"), divider="rainbow")
    st.info(
        _(
            "💡 To find the IP address and root password of your reMarkable, enable developer mode if needed, go to Settings > Help > About > Copyrights and licenses, then scroll the right column if necessary."
        )
    )
    device_name = ""
    device_config = {
        "ip": "",
        "password": "",
    }
    is_new = True

col_name, col_ip, col_password, col_test = st.columns(4, vertical_alignment="bottom")
with col_name:
    name = st.text_input(
        _("Device name"),
        device_name,
        placeholder=_("My reMarkable"),
    )
with col_ip:
    ip = st.text_input(_("IP Address"), device_config.get("ip", ""), placeholder="192.168.x.x")
with col_password:
    password = st.text_input(_("SSH Password"), device_config.get("password", ""), type="password")
with col_test:
    test_feedback_error = ""
    if st.button(
        _("Test Connection"),
        key="ui_config_test_connection",
        icon=":material/wifi_find:",
        width="stretch",
        help=_("Test SSH connection to the device and detect its type and firmware version"),
    ):
        if not ip.strip():
            st.session_state.pop("connection_test_result", None)
            test_feedback_error = _("Enter an IP address before testing.")
        else:
            ok, device_type_detected, fw_detected, err_msg = detect_device_info(
                ip.strip(), password
            )
            if ok:
                st.session_state["connection_test_result"] = {
                    "ok": True,
                    "device_type": device_type_detected,
                    "firmware_version": fw_detected,
                    "error": "",
                    "ip": ip.strip(),
                    "mode": "new" if is_new else "edit",
                    "device_name": device_name,
                }
            else:
                st.session_state["connection_test_result"] = {
                    "ok": False,
                    "device_type": "",
                    "firmware_version": "",
                    "error": err_msg,
                    "ip": ip.strip(),
                    "mode": "new" if is_new else "edit",
                    "device_name": device_name,
                }

test_result = st.session_state.get("connection_test_result") or {}
test_matches_context = (
    test_result.get("mode", "new" if is_new else "edit") == ("new" if is_new else "edit")
    and test_result.get("device_name", device_name) == device_name
    and test_result.get("ip", ip.strip()) == ip.strip()
)

detected_type = ""
detected_fw = ""
if test_matches_context and test_result.get("ok"):
    detected_type = test_result.get("device_type", "")
    detected_fw = test_result.get("firmware_version", "")
elif not is_new:
    detected_type = device_config.get("device_type", "")
    detected_fw = device_config.get("firmware_version", "")

if detected_type or detected_fw:
    st.caption(
        _("Detected: {dt}, Firmware: {fw}").format(
            dt=detected_type or _("unknown"),
            fw=detected_fw or _("unknown"),
        )
    )

final_name = name.strip()
valid_ip = False
if ip.strip():
    try:
        ipaddress.ip_address(ip.strip())
        valid_ip = True
    except ValueError:
        valid_ip = False

name_is_unique = final_name not in DEVICES or final_name == device_name
has_required_fields = bool(final_name and ip.strip() and password and detected_type and detected_fw)
can_save = has_required_fields and valid_ip and name_is_unique


col_save, col_delete_or_cancel = st.columns([3, 1])
save_feedback_error = ""
with col_save:
    if st.button(
        _("Save"),
        key=f"ui_config_save_{device_name or 'new'}",
        width="stretch",
        icon=":material/save:",
        help=_("Save device configuration"),
        disabled=not can_save,
    ):
        new_config = {
            "ip": ip.strip(),
            "password": password,
            "device_type": detected_type,
            "firmware_version": detected_fw,
        }
        try:
            if not is_new and final_name != device_name:
                rename_device_data_dir(device_name, final_name)
                config["devices"].pop(device_name, None)
            config["devices"][final_name] = new_config
            save_config(config)
        except FileExistsError:
            save_feedback_error = _(
                "A local data folder already exists for '{name}'. Choose another device name."
            ).format(name=final_name)
        except OSError as e:
            save_feedback_error = _("Could not save configuration: {error}").format(error=str(e))
        else:
            add_log(f"Configuration saved for '{final_name}'")
            deferred_toast(
                _("Configuration of '{name}' saved").format(name=final_name),
                ":material/task_alt:",
            )
            st.session_state["pending_selected_tablet"] = final_name
            st.session_state.pop("config_creating_new", None)
            st.session_state.pop("connection_test_result", None)
            st.rerun()

with col_delete_or_cancel:
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
    elif (
        is_new
        and selected_name in DEVICES
        and st.button(_("Cancel"), key="ui_config_cancel", width="stretch", icon=":material/close:")
    ):
        st.session_state.pop("config_creating_new", None)
        st.session_state.pop("connection_test_result", None)
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
        device_data_dir = get_device_data_dir_path(device_name)
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

if save_feedback_error:
    st.error(save_feedback_error, icon=":material/error:")
elif test_feedback_error:
    st.error(test_feedback_error, icon=":material/error:")
elif not can_save:
    st.warning(
        _("To save, fill all fields and run Test Connection to detect tablet model and firmware."),
        icon=":material/error:",
    )

if test_matches_context and test_result:
    if test_result.get("ok"):
        st.success(
            _("Connected to {device_type} (firmware {firmware_version})").format(
                device_type=test_result.get("device_type") or _("unknown"),
                firmware_version=test_result.get("firmware_version") or _("unknown"),
            ),
            icon=":material/task_alt:",
        )
    else:
        st.error(
            _("Connection failed: {error}").format(error=test_result.get("error", "")),
            icon=":material/error:",
        )
