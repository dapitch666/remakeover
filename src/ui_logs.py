"""Logs page rendering."""

import streamlit as st

import src.dialog as _dialog


def render_page():
    st.title(":material/list: Logs de session")
    if not st.session_state.get("logs"):
        st.info("Aucun log pour cette session.")
    else:
        for entry in reversed(st.session_state["logs"]):
            st.text(entry)
        if st.button("Effacer les logs de cette session", key="ui_clear_logs", icon=":material/delete:", help="Efface les logs stockés dans la session en cours"):
            st.session_state.clear_logs = None
            _dialog.confirm("Effacer les logs", "Effacer les logs de cette session ?", key="clear_logs")
        if st.session_state.get("clear_logs") is True:
            st.session_state["logs"] = []
            st.success("Logs effacés.", icon=":material/task_alt:")
            del st.session_state.clear_logs
            st.rerun()
