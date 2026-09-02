"""rmfakecloud re-pairing page — only reachable for devices with rmfakecloud_enabled."""

import streamlit as st

# noinspection PyProtectedMember
from src.i18n import _
from src.models import Device
from src.rmfakecloud_ui import render_rmfakecloud_page
from src.ui_common import init_page, rainbow_divider

_RMFC_DEVICE_SCOPED_KEYS = (
    "rmfc_install_output",
    "rmfc_install_ok",
    "rmfc_code",
    "rmfc_code_error",
    "rmfc_install_pending",
    "rmfc_code_pending",
)


# ── Page ─────────────────────────────────────────────────────────────────────

st.title(_("rmfakecloud"), icon=":material/cloud:")
rainbow_divider()

config, selected_name, DEVICES = init_page()
add_log_fn = st.session_state.get("add_log", lambda msg: None)
assert isinstance(selected_name, str)

if st.session_state.get("rmfc_device") != selected_name:
    st.session_state["rmfc_device"] = selected_name
    for _k in _RMFC_DEVICE_SCOPED_KEYS:
        st.session_state.pop(_k, None)

if not DEVICES[selected_name].get("rmfakecloud_enabled"):
    st.info(
        _(
            "rmfakecloud re-pairing is not enabled for this device. Enable it in the device settings."
        )
    )
    st.stop()

current_device = Device.from_dict(selected_name, DEVICES[selected_name])
render_rmfakecloud_page(current_device, add_log_fn)
