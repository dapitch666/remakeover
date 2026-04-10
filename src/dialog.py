import streamlit as st

from src.i18n import _


def confirm(
    title: str = "Confirmation",
    message: str = "Confirm ?",
    key: str = "default",
    cancel_label: str | None = None,
    confirm_label: str | None = None,
    help_text: str | None = None,
) -> None:
    """
    Displays a confirmation dialog with the given title.
    Updates st.session_state[key] with True (confirmed) or False (canceled).
    """

    @st.dialog(title)
    def _dialog():
        st.write(message)
        if help_text:
            st.caption(help_text)

        cancel_text = cancel_label or _("Cancel")
        confirm_text = confirm_label or _("Confirm")

        _l, c1, _m, c2, _r = st.columns([0.3, 1, 0.5, 1, 0.3])

        if c1.button(cancel_text, icon=":material/cancel:", width="stretch"):
            st.session_state[key] = False
            st.rerun()

        if c2.button(confirm_text, icon=":material/check:", width="stretch", type="primary"):
            st.session_state[key] = True
            st.rerun()

    _dialog()
