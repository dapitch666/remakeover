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

    def _on_clear_logs_click():
        st.session_state["pending_clear_logs"] = True

    st.button(
        _("Clear session logs"),
        key="ui_clear_logs",
        icon=":material/delete:",
        help=_("Clear logs stored in the current session"),
        on_click=_on_clear_logs_click,
    )

    if st.session_state.get("pending_clear_logs"):
        _dialog.confirm(_("Clear logs"), _("Clear logs for this session?"), key="clear_logs")
        result = st.session_state.get("clear_logs")
        if result is True:
            st.session_state["logs"] = []
            st.session_state.pop("clear_logs", None)
            st.session_state.pop("pending_clear_logs", None)
            st.rerun()
        elif result is False:
            st.session_state.pop("clear_logs", None)
            st.session_state.pop("pending_clear_logs", None)
            st.rerun()
