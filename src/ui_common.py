"""Shared rendering helpers used by multiple UI modules."""

import os
from datetime import datetime
from zoneinfo import ZoneInfo

import streamlit as st
from babel.core import UnknownLocaleError
from babel.dates import format_date, format_time

from src.i18n import _, get_language

_DEFERRED_TOAST_KEY = "_deferred_toast"
_KNOWN_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".bmp", ".gif", ".webp", ".template"}


def deferred_toast(msg: str, icon: str | None = None) -> None:
    """Queue a toast to be displayed on the next rerun via show_deferred_toast()."""
    st.session_state[_DEFERRED_TOAST_KEY] = {"msg": msg, "icon": icon}


def show_deferred_toast() -> None:
    """Display and clear any queued deferred toast. Call once per rerun at app level."""
    toast = st.session_state.pop(_DEFERRED_TOAST_KEY, None)
    if toast:
        msg, icon = toast["msg"], toast["icon"]
        msg = f":red[{msg}]" if icon and icon == ":material/error:" else f":green[{msg}]"
        st.toast(msg, icon=icon)


def init_page(require_selected: bool = True) -> tuple[dict, str | None, dict]:
    """Extract common page session state and return (config, selected_name, DEVICES).

    ``config``, ``selected_name`` and ``DEVICES`` are read from
    ``st.session_state`` — the same boilerplate that every page repeats.

    When *require_selected* is True (default), calls ``_require_device`` which
    stops rendering if no device is configured or selected.
    """
    config: dict = st.session_state.get("config", {})
    selected_name: str | None = st.session_state.get("selected_name")
    devices: dict = config.get("devices", {})
    if require_selected:
        _require_device(devices, selected_name)
    return config, selected_name, devices


def _require_device(devices: dict, selected_name) -> None:
    """Guard helper called at the top of every device-specific page.

    * If *devices* is empty, shows a warning telling the user to add a device
       in the sidebar and stops rendering.
    * If *selected_name* is not set or not in *devices*, shows an info message
      prompting the user to select a device in the sidebar and stops rendering.
    """
    if not devices:
        _left, col, _right = st.columns([0.5, 3, 0.5])
        with col:
            st.warning(
                _("No device configured. Add one in the sidebar."), icon=":material/arrow_left_alt:"
            )
        st.stop()
    if not selected_name or selected_name not in devices:
        st.info(_("Select a device in the sidebar."))
        st.stop()


def rainbow_divider():
    """Render a thin rainbow gradient rule beneath a page title."""
    st.html(
        '<hr style="'
        "height: 3px; border: none; margin-bottom: 3rem;"
        " background: linear-gradient("
        "   to right, #e63946, #f4a261, #e9c46a, #52b788, #4895ef, #7b2d8b"
        ");"
        '">'
    )


def normalise_filename(filename: str, ext: str = ".png") -> str:
    """Sanitize a filename and ensure it ends with the specified extension.

    Only strips an existing suffix when it is a recognized file extension,
    so that dots inside a user-supplied base name (e.g. ``alice.et.merlin``)
    are preserved rather than being mistakenly treated as an extension.
    """
    if filename.lower().endswith(ext.lower()):
        return filename
    current_ext = os.path.splitext(filename)[1].lower()
    if current_ext in _KNOWN_EXTENSIONS:
        filename = os.path.splitext(filename)[0]
    return filename + ext


def handle_rename_confirmation(
    confirm_key: str,
    pending_key: str,
    renaming_key: str,
    on_confirm,
) -> None:
    """Handle the True/False/None result of a rename overwrite confirmation dialog.

    Cleans up session state and reruns on resolution. Calls *on_confirm()* when
    the user accepts; does nothing extra when they cancel.
    """
    result = st.session_state.get(confirm_key)
    if result is True:
        on_confirm()
        st.session_state.pop(confirm_key, None)
        st.session_state[pending_key] = None
        st.session_state[renaming_key] = None
        st.rerun()
    elif result is False:
        st.session_state.pop(confirm_key, None)
        st.session_state[pending_key] = None
        st.session_state[renaming_key] = None
        st.rerun()


def format_datetime_for_ui(
    iso_string: str | None,
) -> tuple[str, str]:
    """Format an ISO timestamp for UI display using locale-aware date and time."""
    if not iso_string:
        return "Unknown", ""

    try:
        dt_utc = datetime.fromisoformat(iso_string.replace("Z", "+00:00"))
        dt_local = dt_utc.astimezone(ZoneInfo(st.context.timezone or "UTC"))
        ui_locale = (get_language() or st.context.locale or "en").replace("-", "_")

        return format_date(dt_local.date(), format="medium", locale=ui_locale), format_time(
            dt_local.time(), format="HH:mm", locale=ui_locale
        )

    except (ValueError, KeyError, UnknownLocaleError):
        return iso_string, ""
