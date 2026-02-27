import streamlit as st
from src.ui_config import render_page

config = st.session_state.get("config", {})
add_log = st.session_state.get("add_log", lambda msg: None)
save_config = st.session_state.get("save_config", lambda c: None)
resolve_device_type = st.session_state.get("resolve_device_type")
DEFAULT_DEVICE_TYPE = st.session_state.get("DEFAULT_DEVICE_TYPE", "reMarkable 2")

render_page(config, save_config, add_log, resolve_device_type, DEFAULT_DEVICE_TYPE)
