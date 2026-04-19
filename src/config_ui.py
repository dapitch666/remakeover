"""Device configuration panel rendered in the sidebar."""

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
from src.i18n import _
from src.models import Device
from src.ssh import run_detection
from src.ui_common import deferred_toast

_INPUT_KEY_BASES = ("config_device_name", "config_device_ip", "config_device_password")


def _clear_input_keys():
    for base in _INPUT_KEY_BASES:
        for key in (base, f"new_{base}"):
            if key in st.session_state:
                del st.session_state[key]


def render_config_panel(config: dict, selected_name: str | None, add_log) -> None:
    """Render the device configuration form inside the sidebar."""
    devices = config.get("devices", {})

    if devices and selected_name and selected_name in devices:
        st.subheader(_("Edit: {name}").format(name=selected_name))
        device_name: str = selected_name
        device_config = devices[selected_name].copy()
        is_new = False
    else:
        st.subheader(_("Create a new device"))
        st.info(
            _(
                "💡 To find the IP address and root password of your reMarkable, enable developer mode if needed, "
                "go to Settings > Help > About > Copyrights and licenses, then scroll the right column if necessary."
            )
        )
        device_name = ""
        device_config = {"ip": "", "password": ""}
        is_new = True

    key_prefix = "new_" if is_new else ""
    name = st.text_input(
        _("Device name"),
        device_name,
        placeholder=_("My reMarkable"),
        key=f"{key_prefix}config_device_name",
    )
    ip = st.text_input(
        _("IP Address"),
        device_config.get("ip", ""),
        placeholder="192.168.x.x",
        key=f"{key_prefix}config_device_ip",
    )
    ip_stripped = ip.strip()
    password = st.text_input(
        _("SSH Password"),
        device_config.get("password", ""),
        type="password",
        key=f"{key_prefix}config_device_password",
    )

    if is_new:

        def _on_test_connection():
            if not ip_stripped:
                st.session_state.pop("connection_test_result", None)
                st.session_state["_test_feedback_error"] = _("Enter an IP address before testing.")
            else:
                result = run_detection(Device(name="", ip=ip_stripped, password=password))
                st.session_state["connection_test_result"] = {
                    **result,
                    "ip": ip_stripped,
                    "mode": "new",
                    "device_name": device_name,
                }
                st.session_state.pop("_test_feedback_error", None)

        st.button(
            _("Test Connection"),
            key="ui_config_test_connection",
            icon=":material/wifi_find:",
            width="stretch",
            help=_("Test SSH connection to the device and detect its type and firmware version"),
            on_click=_on_test_connection,
        )

    test_result = st.session_state.get("connection_test_result") or {}
    test_matches_context = (
        test_result.get("mode", "new" if is_new else "edit") == ("new" if is_new else "edit")
        and test_result.get("device_name", device_name) == device_name
        and test_result.get("ip", ip_stripped) == ip_stripped
    )

    detected_type = ""
    detected_fw = ""
    detected_sleep = False
    if test_matches_context and test_result.get("ok"):
        detected_type = test_result.get("device_type", "")
        detected_fw = test_result.get("firmware_version", "")
        detected_sleep = test_result.get("sleep_screen_enabled", False)
    elif not is_new:
        detected_type = device_config.get("device_type", "")
        detected_fw = device_config.get("firmware_version", "")
        detected_sleep = device_config.get("sleep_screen_enabled", False)

    if detected_type or detected_fw:
        st.caption(
            _("Detected: {dt}, Firmware: {fw}").format(
                dt=detected_type or _("unknown"),
                fw=detected_fw or _("unknown"),
            )
        )

    final_name = name.strip()
    valid_ip = False
    if ip_stripped:
        try:
            ipaddress.ip_address(ip_stripped)
            valid_ip = True
        except ValueError:
            valid_ip = False

    name_is_unique = final_name not in devices or final_name == device_name
    has_required_fields = bool(
        final_name and ip_stripped and password and detected_type and detected_fw
    )
    can_save = has_required_fields and valid_ip and name_is_unique

    col_save, col_action = st.columns(2)
    with col_save:

        def _on_save():
            new_device_config = {
                "ip": ip_stripped,
                "password": password,
                "device_type": detected_type,
                "firmware_version": detected_fw,
                "sleep_screen_enabled": detected_sleep,
            }
            try:
                if not is_new and final_name != device_name:
                    rename_device_data_dir(device_name, final_name)
                    config["devices"].pop(device_name, None)
                config["devices"][final_name] = new_device_config
                save_config(config)
            except FileExistsError:
                st.session_state["_save_feedback_error"] = _(
                    "A local data folder already exists for '{name}'. Choose another device name."
                ).format(name=final_name)
            except OSError as err:
                st.session_state["_save_feedback_error"] = _(
                    "Could not save configuration: {error}"
                ).format(error=str(err))
            else:
                add_log(f"Configuration saved for '{final_name}'")
                deferred_toast(
                    _("Configuration of '{name}' saved").format(name=final_name),
                    ":material/task_alt:",
                )
                _clear_input_keys()
                st.session_state["pending_selected_device"] = final_name
                st.session_state.pop("connection_test_result", None)
                st.session_state["config_panel_open"] = False

        st.button(
            _("Save"),
            key=f"ui_config_save_{device_name or 'new'}",
            width="stretch",
            icon=":material/save:",
            help=_("Save device configuration"),
            disabled=not can_save,
            on_click=_on_save,
        )

    with col_action:
        if not is_new:

            def _on_delete_click():
                st.session_state["pending_delete_device"] = device_name

            st.button(
                _("Delete"),
                key=f"ui_config_delete_{device_name}",
                type="primary",
                width="stretch",
                icon=":material/delete:",
                help=_("Delete this device and its local images and templates"),
                on_click=_on_delete_click,
            )
        elif is_new and devices:

            def _on_cancel():
                _clear_input_keys()
                st.session_state.pop("connection_test_result", None)
                fallback = list(devices.keys())[0]
                st.session_state["device"] = st.session_state.get("_last_real_device", fallback)
                st.session_state["config_panel_open"] = False

            st.button(
                _("Cancel"),
                key="ui_config_cancel",
                width="stretch",
                icon=":material/close:",
                on_click=_on_cancel,
                help=_("Cancel editing this device"),
            )

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
            _data_dir_error = None
            if os.path.exists(device_data_dir):
                try:
                    shutil.rmtree(device_data_dir)
                    add_log(f"Device data directory removed for '{device_name}'")
                except OSError as e:
                    _data_dir_error = str(e)
                    add_log(f"Could not fully remove data dir for '{device_name}': {e}")
            if device_name in config.get("devices", {}):
                del config["devices"][device_name]
                save_config(config)
            add_log(f"Configuration deleted for '{device_name}'")
            if _data_dir_error:
                deferred_toast(
                    _("'{name}' deleted, but local data could not be fully removed").format(
                        name=device_name, err=_data_dir_error
                    ),
                    ":material/error:",
                )
            else:
                deferred_toast(
                    _("'{name}' deleted").format(name=device_name), ":material/task_alt:"
                )
            del st.session_state["pending_delete_device"]
            del st.session_state[f"del_device_{device_name}"]
            st.session_state["config_panel_open"] = False
            st.rerun()
        elif st.session_state.get(f"del_device_{device_name}") is False:
            del st.session_state[f"del_device_{device_name}"]
            del st.session_state["pending_delete_device"]
            st.rerun()

    save_feedback_error = st.session_state.pop("_save_feedback_error", "")
    test_feedback_error = st.session_state.pop("_test_feedback_error", "")
    if save_feedback_error:
        st.error(save_feedback_error, icon=":material/error:")
    elif test_feedback_error:
        st.error(test_feedback_error, icon=":material/error:")
    elif not can_save:
        st.warning(
            _(
                "To save, fill all fields, turn the device on and run Test Connection to detect device model and firmware."
            ),
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
