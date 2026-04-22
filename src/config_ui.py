"""Device configuration panel rendered in the sidebar."""

import ipaddress
import os
import shutil
from collections.abc import Callable
from datetime import datetime, timedelta

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

_NEW_DEVICE = "__new_device__"
_SSH_RESULT_STALE_AFTER = timedelta(minutes=5)

_CONFIG_INPUT_KEYS = (
    "config_device_name",
    "config_device_ip",
    "config_device_password",
    "new_config_device_name",
    "new_config_device_ip",
    "new_config_device_password",
    "connection_test_result",
)


def _clear_input_keys():
    for base in _INPUT_KEY_BASES:
        for key in (base, f"new_{base}"):
            if key in st.session_state:
                del st.session_state[key]


def _on_device_change():
    for key in _CONFIG_INPUT_KEYS:
        if key in st.session_state:
            del st.session_state[key]
    st.session_state["config_panel_open"] = st.session_state["device"] == _NEW_DEVICE


def render_config_panel(
    config: dict, selected_name: str | None, add_log: Callable[[str], None]
) -> None:
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
        elif devices:

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
                        name=device_name
                    ),
                    ":material/error:",
                )
            else:
                deferred_toast(
                    _("'{name}' deleted").format(name=device_name), ":material/task_alt:"
                )
            st.session_state.pop("pending_delete_device", None)
            st.session_state.pop(f"del_device_{device_name}", None)
            st.session_state["config_panel_open"] = False
            st.rerun()
        elif st.session_state.get(f"del_device_{device_name}") is False:
            st.session_state.pop(f"del_device_{device_name}", None)
            st.session_state.pop("pending_delete_device", None)
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


def _apply_detected_metadata(
    selected_name: str, devices: dict, config: dict, result: dict, add_log: Callable[[str], None]
) -> None:
    """Update device config in-place with newly detected metadata and persist if changed."""
    old_type = devices[selected_name].get("device_type", "")
    old_fw = devices[selected_name].get("firmware_version", "")
    old_sleep = devices[selected_name].get("sleep_screen_enabled", False)
    detected_type = result["device_type"]
    detected_fw = result["firmware_version"]
    sleep_screen_enabled = result["sleep_screen_enabled"]

    details: list[str] = []
    if detected_type and detected_type != old_type:
        devices[selected_name]["device_type"] = detected_type
        details.append(
            _("model: {old} -> {new}").format(old=old_type or _("unknown"), new=detected_type)
        )
    if detected_fw and detected_fw != old_fw:
        devices[selected_name]["firmware_version"] = detected_fw
        details.append(
            _("firmware: {old} -> {new}").format(old=old_fw or _("unknown"), new=detected_fw)
        )
    if sleep_screen_enabled != old_sleep:
        devices[selected_name]["sleep_screen_enabled"] = sleep_screen_enabled
        details.append(
            _("sleep screen now enabled")
            if sleep_screen_enabled
            else _("sleep screen now disabled")
        )

    if not details:
        return

    try:
        save_config(config)
    except OSError as exc:
        add_log(f"Detected metadata change for '{selected_name}' but failed to persist: {exc}")
        deferred_toast(
            _("Could not save detected metadata for '{name}'").format(name=selected_name),
            ":material/error:",
        )
        return

    deferred_toast(
        _("Detected update for '{name}': {details}").format(
            name=selected_name, details=", ".join(details)
        ),
        ":material/task_alt:",
    )
    add_log(f"Updated detected metadata for '{selected_name}': {', '.join(details)}")


def render_device_selector(config: dict, add_log: Callable[[str], None]) -> str | None:
    """Render device selector, SSH test controls, and config panel in the sidebar.

    Returns the selected device name when at least one device is configured,
    otherwise returns ``None``.
    """
    devices = config.get("devices", {})
    selected_name = None

    if devices:
        device_names = list(devices.keys())

        device_names_with_new = device_names + [_NEW_DEVICE]

        # Apply an explicit `?device=` URL selection only when session state
        # has no valid selection yet, so user interactions keep priority.
        # Do not override the sentinel (user is creating a new device).
        qp_device = st.query_params.get("device")
        if (
            st.session_state.get("device") not in device_names_with_new
            and qp_device
            and qp_device in device_names
        ):
            st.session_state["device"] = qp_device

        # Consume pending selection set after saving a new device.
        pending = st.session_state.pop("pending_selected_device", None)
        if pending and pending in device_names:
            st.session_state["device"] = pending

        # Keep a valid selected device in session state when the list changes.
        if st.session_state.get("device") not in device_names_with_new:
            st.session_state["device"] = device_names[0]

        with st.sidebar:
            col_device, col_btn_settings, col_btn_ssh = st.columns(
                [4, 1, 1], vertical_alignment="bottom", gap="xsmall"
            )
            with col_device:
                raw_device = st.selectbox(
                    _("Device"),
                    device_names_with_new,
                    key="device",
                    on_change=_on_device_change,
                    format_func=lambda x: _("─ New device ─") if x == _NEW_DEVICE else x,
                )
            selected_name = None if raw_device == _NEW_DEVICE else raw_device
            if (
                raw_device != _NEW_DEVICE
                and st.session_state.get("_last_real_device") != raw_device
            ):
                st.session_state["_last_real_device"] = raw_device
            with col_btn_settings:

                def _toggle_config_panel():
                    st.session_state["config_panel_open"] = not st.session_state.get(
                        "config_panel_open", False
                    )

                st.button(
                    ":material/settings:",
                    key="sidebar_config_toggle",
                    help=_("Device configuration"),
                    width="stretch",
                    type="primary"
                    if st.session_state.get("config_panel_open", False)
                    else "secondary",
                    on_click=_toggle_config_panel,
                )
            _ssh_result = st.session_state.get("_ssh_test_result")
            if _ssh_result and _ssh_result.get("device") != selected_name:
                del st.session_state["_ssh_test_result"]
                _ssh_result = None

            with col_btn_ssh:
                if selected_name:
                    _device = Device.from_dict(selected_name, devices[selected_name])

                    def _on_ssh_test():
                        result = run_detection(_device)
                        st.session_state["_ssh_test_result"] = {
                            **result,
                            "device": selected_name,
                            "tested_at": datetime.now(),
                        }
                        if result["ok"]:
                            _apply_detected_metadata(
                                selected_name, devices, config, result, add_log
                            )
                            add_log(f"SSH connection successful to '{selected_name}'")
                        else:
                            add_log(
                                f"SSH connection failed to '{selected_name}': {result['error']}"
                            )

                    _is_stale = (
                        _ssh_result is not None
                        and _ssh_result.get("ok")
                        and datetime.now() - _ssh_result.get("tested_at", datetime.min)
                        > _SSH_RESULT_STALE_AFTER
                    )
                    if _ssh_result and _ssh_result["ok"] and not _is_stale:
                        is_error = False
                        _btn_help = _("SSH connection OK")
                        st.html(
                            "<style>"
                            "   .st-key-sidebar_test_ssh button {"
                            "       background-color: rgb(37, 215, 93);"
                            "       border-color: rgb(37, 215, 93);"
                            "       color: white;"
                            "   }"
                            "   .st-key-sidebar_test_ssh button:hover, .st-key-sidebar_test_ssh button:focus-visible {"
                            "       background-color: rgb(33, 195, 84);"
                            "       border-color: rgb(33, 195, 84);"
                            "   }"
                            "</style>"
                        )
                    elif _is_stale:
                        is_error = False
                        _elapsed = int(
                            (datetime.now() - _ssh_result["tested_at"]).total_seconds() / 60
                        )
                        _btn_help = _(
                            "Connection status unknown (last checked {n} min ago)"
                        ).format(n=_elapsed)
                    elif _ssh_result and not _ssh_result["ok"]:
                        is_error = True
                        _btn_help = _("SSH connection failed: {err}").format(
                            err=_ssh_result["error"]
                        )
                    else:
                        is_error = False
                        _btn_help = _("Test SSH connection")

                    st.button(
                        ":material/wifi:",
                        key="sidebar_test_ssh",
                        width="stretch",
                        help=_btn_help,
                        on_click=_on_ssh_test,
                        type="primary" if is_error else "secondary",
                    )

            if st.session_state.get("config_panel_open", False):
                render_config_panel(config, selected_name, add_log)

        # Persist selection in session state for pages to consume.
        st.session_state["selected_name"] = selected_name
        if selected_name:
            st.query_params["device"] = selected_name
        elif "device" in st.query_params:
            del st.query_params["device"]
    else:
        st.session_state["selected_name"] = None
        if "device" in st.query_params:
            del st.query_params["device"]
        with st.sidebar:
            render_config_panel(config, None, add_log)

    return selected_name
