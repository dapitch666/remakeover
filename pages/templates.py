import streamlit as st
from src.models import Device
from src.ui_common import rainbow_divider
from src.ui_templates import render_page

st.title(":material/description: Templates")
rainbow_divider()

config = st.session_state.get("config", {})
add_log = st.session_state.get("add_log", lambda msg: None)
selected_name = st.session_state.get("selected_name")

DEVICES = config.get("devices", {})

if not DEVICES:
    st.warning(
        "Aucun appareil configuré. Ajoutez-en un dans ⚙️ **Configuration**.",
        icon=":material/info:",
    )
    st.stop()

if not selected_name or selected_name not in DEVICES:
    st.info("Sélectionnez une tablette dans la barre latérale.")
    st.stop()

device = Device.from_dict(selected_name, DEVICES[selected_name])
render_page(selected_name, device, add_log)
