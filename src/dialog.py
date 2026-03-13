import streamlit as st

from src.i18n import _


def confirm(title: str = "Confirmer", message: str = "Confirmer ?", key: str = "default") -> None:
    """
    Displays a confirmation dialog with the given title.
    Updates st.session_state[key] with True (confirmed) or False (cancelled).
    """

    @st.dialog(title)
    def _dialog():
        st.write(message)

        _l, c1, _m, c2, _r = st.columns([0.3, 1, 0.5, 1, 0.3])

        if c1.button(_("Cancel"), icon=":material/cancel:", width="stretch"):
            st.session_state[key] = False
            st.rerun()

        if c2.button(_("Confirm"), icon=":material/check:", width="stretch", type="primary"):
            st.session_state[key] = True
            st.rerun()

    _dialog()
