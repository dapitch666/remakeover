"""Shared rendering helpers used by multiple UI modules."""

import os

import streamlit as st

import src.ssh as _ssh
from src.constants import CMD_RESTART_XOCHITL, SUSPENDED_PNG_PATH

_DEFERRED_TOAST_KEY = "_deferred_toast"


def deferred_toast(msg: str, icon: str | None = None) -> None:
    """Queue a toast to be displayed on the next rerun via show_deferred_toast()."""
    st.session_state[_DEFERRED_TOAST_KEY] = {"msg": msg, "icon": icon}


_ICON_COLOR = {
    ":material/task_alt:": "green",
    ":material/error:": "red",
}


def show_deferred_toast() -> None:
    """Display and clear any queued deferred toast. Call once per rerun at app level."""
    toast = st.session_state.pop(_DEFERRED_TOAST_KEY, None)
    if toast:
        msg, icon = toast["msg"], toast["icon"]
        color = _ICON_COLOR.get(icon)
        if color:
            msg = f":{color}[{msg}]"
        st.toast(msg, icon=icon)


def require_device(devices: dict, selected_name) -> None:
    """Guard helper called at the top of every device-specific page.

    * If *devices* is empty, shows a warning with a link to the configuration
      page and stops rendering.
    * If *selected_name* is not set or not in *devices*, shows an info message
      prompting the user to select a tablet in the sidebar and stops rendering.
    """
    if not devices:
        _, col, _ = st.columns([0.5, 3, 0.5])
        with col, st.container(horizontal=True, width="content", gap="xsmall", border=True):
            st.markdown(":orange[:material/warning:]")
            st.markdown("Aucun appareil configuré. Ajoutez-en un dans la page ")
            st.page_link("pages/configuration.py", icon=":material/settings:")
        st.stop()
    if not selected_name or selected_name not in devices:
        st.info("Sélectionnez une tablette dans la barre latérale.")
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


_KNOWN_EXTENSIONS = {".png", ".jpg", ".jpeg", ".svg", ".bmp", ".gif", ".webp", ".template"}


def normalise_filename(filename: str, ext: str = ".png") -> str:
    """Sanitise a filename and ensure it ends with the specified extension.

    Only strips an existing suffix when it is a recognised file extension,
    so that dots inside a user-supplied base name (e.g. ``alice.et.merlin``)
    are preserved rather than being mistakenly treated as an extension.
    """
    filename = filename.replace(" ", "_")
    if filename.lower().endswith(ext.lower()):
        return filename
    current_ext = os.path.splitext(filename)[1].lower()
    if current_ext in _KNOWN_EXTENSIONS:
        filename = os.path.splitext(filename)[0]
    return filename + ext


def send_suspended_png(device, img_data: bytes, img_name: str, selected_name: str, add_log) -> bool:
    """Upload *img_data* as suspended.png and restart xochitl. Returns True on success."""
    pw = device.password or ""
    success, msg = _ssh.upload_file_ssh(device.ip, pw, img_data, SUSPENDED_PNG_PATH)
    if success:
        _ssh.run_ssh_cmd(device.ip, pw, [CMD_RESTART_XOCHITL])
        add_log(f"Sent {img_name} to '{selected_name}'")
        return True
    add_log(f"Error sending {img_name} to '{selected_name}': {msg}")
    return False
