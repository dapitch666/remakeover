"""Logs page."""

import streamlit as st

import src.dialog as _dialog

# noinspection PyProtectedMember
from src.i18n import _
from src.ui_common import rainbow_divider

st.title(_(":material/list: Session Logs"))
rainbow_divider()
if not st.session_state.get("logs"):
    st.info(_("No logs for this session."))
else:
    st.code("\n".join(reversed(st.session_state["logs"])), language=None)
    if st.button(
        _("Clear session logs"),
        key="ui_clear_logs",
        icon=":material/delete:",
        help=_("Clear logs stored in the current session"),
    ):
        _dialog.confirm(_("Clear logs"), _("Clear logs for this session?"), key="clear_logs")
    if st.session_state.get("clear_logs") is True:
        st.session_state["logs"] = []
        st.success(_("Logs cleared."), icon=":material/task_alt:")
        del st.session_state.clear_logs
        st.rerun()
