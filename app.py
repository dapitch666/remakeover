import html as _pyhtml
import json
import os
from contextlib import suppress
from datetime import datetime, timedelta

import streamlit as st

from src.config import (
    BASE_DIR,
    load_config,
    save_config,
)

# noinspection PyProtectedMember
from src.i18n import SUPPORTED_LANGUAGES, _
from src.ui_common import deferred_toast

_LANG_FLAGS = {"en": ("🇬🇧", "English"), "fr": ("🇫🇷", "Français")}

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


def _on_device_change():
    for key in _CONFIG_INPUT_KEYS:
        if key in st.session_state:
            del st.session_state[key]
    st.session_state["config_panel_open"] = st.session_state["device"] == _NEW_DEVICE


def _normalize_lang_value(raw: str | None) -> str | None:
    """Normalize language query values to canonical short codes (en/fr)."""
    if raw is None:
        return None

    value = str(raw).strip()
    if not value:
        return None

    lowered = value.lower()
    if lowered in SUPPORTED_LANGUAGES:
        return lowered

    for code, (flag, name) in _LANG_FLAGS.items():
        if lowered in {name.lower(), f"{flag} {name}".lower()}:
            return code

    return None


def _init_language() -> None:
    """Set ``st.session_state["lang"]`` on the first visit when no URL param is present.

    A canonical short value (``en``/``fr``) is always kept in URL params,
    session state and the language selector state. Legacy URL values containing
    full labels (with flags) are normalized to short codes.
    """
    query_lang = _normalize_lang_value(st.query_params.get("lang"))
    if query_lang:
        st.session_state["lang"] = query_lang
    elif "lang" not in st.session_state:
        browser_lang = (st.context.locale or "en").split("-")[0].lower()
        st.session_state["lang"] = browser_lang if browser_lang in SUPPORTED_LANGUAGES else "en"

    # Keep URL in canonical short form (en/fr), including after legacy links.
    if st.query_params.get("lang") != st.session_state["lang"]:
        st.query_params["lang"] = st.session_state["lang"]


def _language_selector() -> None:
    """Render a compact flag+label toggle in the sidebar using ``st.segmented_control``.

    The widget shows a rich label (flag + full name), while URL/query state is
    explicitly synced using canonical short codes (``en``/``fr``).
    """

    def _on_lang_change():
        selected = st.session_state.get("lang_selector")
        if selected:
            st.session_state["lang"] = selected
            st.query_params["lang"] = selected

    with st.sidebar:
        st.segmented_control(
            "Language",
            options=list(SUPPORTED_LANGUAGES),
            format_func=lambda lang: f"{_LANG_FLAGS[lang][0]} {_LANG_FLAGS[lang][1]}",
            label_visibility="collapsed",
            key="lang_selector",
            default=st.session_state.get("lang", "en"),
            width="stretch",
            on_change=_on_lang_change,
        )


# ── Session logging helper ────────────────────────────────────────────────────
def _add_log(message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"{ts} - {message}"
    try:
        st.session_state.setdefault("logs", []).append(entry)
    except (AttributeError, RuntimeError):
        print(entry)


def _read_version():
    version = os.environ.get("IMAGE_VERSION")
    if version:
        return version
    try:
        with open(os.path.join(BASE_DIR, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def _inject_css():
    st.html(
        "<style>"
        "   [data-testid='stSidebarNavLink'] span {"
        "       font-size: 1.1rem;"
        "   }"
        "   .block-container {"
        "       max-width: 90%;"
        "       padding-top: 3rem;"
        "   }"
        "</style>"
    )


def _sidebar_version(version):
    if not version:
        return
    html = (
        f'<div style="position:fixed;left:20px;bottom:8px">'
        f'  <a href="https://github.com/dapitch666/rm-manager" target="_blank">'
        f"      rm-manager - version {version}"
        f"  </a>"
        f"</div>"
    )
    st.sidebar.caption(html, unsafe_allow_html=True)


def _debug_overlay():
    debug_mode = (BASE_DIR != "/app") or os.environ.get("DEBUG", "").lower() in (
        "1",
        "true",
        "yes",
    )
    if not debug_mode:
        return

    with suppress(Exception):
        st.sidebar.expander("session_state (debug)", expanded=False).write(
            dict(st.session_state)
        )  # not translated — dev only

    with suppress(Exception):
        safe = _pyhtml.escape(json.dumps(dict(st.session_state), default=str, indent=2))
        st.html(
            f'<div style="position:fixed;right:8px;top:8px;max-width:420px;max-height:45vh;'
            f"overflow:auto;background:rgba(255,255,255,0.95);border:1px solid rgba(0,0,0,0.12);"
            f"padding:8px;font-size:12px;z-index:99999;font-family:monospace;"
            f'box-shadow:0 4px 12px rgba(0,0,0,0.08);">'
            f"<details><summary style='font-weight:600;cursor:pointer'>session_state (debug)</summary>"
            f"<pre style='white-space:pre-wrap;margin:6px 0 0 0;'>{safe}</pre>"
            f"</details></div>"
        )


def _apply_detected_metadata(
    selected_name: str, devices: dict, config: dict, result: dict, add_log
) -> None:
    """Update device config in-place with newly detected metadata and persist if changed."""
    old_type = devices[selected_name].get("device_type", "")
    old_fw = devices[selected_name].get("firmware_version", "")
    old_sleep = devices[selected_name].get("sleep_screen_enabled", False)
    detected_type = result["device_type"]
    detected_fw = result["firmware_version"]
    sleep_screen_enabled = result["sleep_screen_enabled"]

    changed_fields: list[str] = []
    if detected_type and detected_type != old_type:
        devices[selected_name]["device_type"] = detected_type
        changed_fields.append("device_type")
    if detected_fw and detected_fw != old_fw:
        devices[selected_name]["firmware_version"] = detected_fw
        changed_fields.append("firmware_version")
    if sleep_screen_enabled != old_sleep:
        devices[selected_name]["sleep_screen_enabled"] = sleep_screen_enabled
        changed_fields.append("sleep_screen_enabled")

    if not changed_fields:
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

    details: list[str] = []
    if "device_type" in changed_fields:
        details.append(
            _("model: {old} -> {new}").format(old=old_type or _("unknown"), new=detected_type)
        )
    if "firmware_version" in changed_fields:
        details.append(
            _("firmware: {old} -> {new}").format(old=old_fw or _("unknown"), new=detected_fw)
        )
    if "sleep_screen_enabled" in changed_fields:
        details.append(
            _("sleep screen now enabled")
            if sleep_screen_enabled
            else _("sleep screen now disabled")
        )
    deferred_toast(
        _("Detected update for '{name}': {details}").format(
            name=selected_name, details=", ".join(details)
        ),
        ":material/task_alt:",
    )
    add_log(
        f"Updated detected metadata for '{selected_name}': "
        f"device_type='{old_type}' -> '{detected_type}', "
        f"firmware_version='{old_fw}' -> '{detected_fw}'"
    )


def _device_selector(config: dict) -> str | None:
    """Render device selector, SSH test controls, and config panel in the sidebar.

    Returns the selected device name when at least one device is configured,
    otherwise returns ``None``.
    """
    from src.config_ui import render_config_panel

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
            from src.models import Device as _Device

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
                    _device = _Device.from_dict(selected_name, devices[selected_name])

                    def _on_ssh_test():
                        from src.ssh import run_detection

                        result = run_detection(_device)
                        st.session_state["_ssh_test_result"] = {
                            **result,
                            "device": selected_name,
                            "tested_at": datetime.now(),
                        }
                        if result["ok"]:
                            _apply_detected_metadata(
                                selected_name, devices, config, result, _add_log
                            )
                            _add_log(f"SSH connection successful to '{selected_name}'")
                        else:
                            _add_log(
                                f"SSH connection failed to '{selected_name}': {result['error']}"
                            )

                    _is_stale = (
                        _ssh_result is not None
                        and _ssh_result.get("ok")
                        and datetime.now() - _ssh_result.get("tested_at", datetime.min)
                        > _SSH_RESULT_STALE_AFTER
                    )
                    if _ssh_result and _ssh_result["ok"] and not _is_stale:
                        _status = "green"
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
                        _status = "stale"
                        _elapsed = int(
                            (datetime.now() - _ssh_result["tested_at"]).total_seconds() / 60
                        )
                        _btn_help = _(
                            "Connection status unknown (last checked {n} min ago)"
                        ).format(n=_elapsed)
                    elif _ssh_result and not _ssh_result["ok"]:
                        _status = "red"
                        _btn_help = _("SSH connection failed: {err}").format(
                            err=_ssh_result["error"]
                        )
                    else:
                        _status = "stale"
                        _btn_help = _("Test SSH connection")

                    st.button(
                        ":material/wifi:",
                        key="sidebar_test_ssh",
                        width="stretch",
                        help=_btn_help,
                        on_click=_on_ssh_test,
                        type="primary" if _status == "red" else "secondary",
                    )

            if st.session_state.get("config_panel_open", False):
                render_config_panel(config, selected_name, _add_log)

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
            render_config_panel(config, None, _add_log)

    return selected_name


def main():
    st.set_page_config(
        page_title="rM Manager",
        page_icon="assets/favicon.svg",
        layout="wide",
        initial_sidebar_state="auto",
    )
    st.logo(image="assets/logo.svg", size="large")

    # ── Shared session state ──────────────────────────────────────────────
    st.session_state.setdefault("logs", [])
    st.session_state["add_log"] = _add_log

    # Resolve language from URL param before any _() call (page titles, etc.)
    _init_language()

    # Load config from disk only on the very first run of this session.
    # Pages keep st.session_state["config"] up-to-date when they mutate it,
    # so re-reading from disk on every rerun is unnecessary.
    if "config" not in st.session_state:
        st.session_state["config"] = load_config()
    config = st.session_state["config"]

    # ── Navigation ────────────────────────────────────────────────────────
    pages = [
        st.Page("pages/images.py", title="Images", icon=":material/image:"),
        st.Page("pages/templates.py", title="Templates", icon=":material/description:"),
        st.Page("pages/logs.py", title="Logs", icon=":material/list:"),
    ]

    pg = st.navigation(pages)

    _language_selector()

    _device_selector(config)

    _inject_css()
    _sidebar_version(_read_version())
    _debug_overlay()

    from src.ui_common import show_deferred_toast

    show_deferred_toast()

    pg.run()


if __name__ == "__main__":
    main()
