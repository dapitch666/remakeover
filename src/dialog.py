import streamlit as st


def confirm(title: str = "Confirmer", message: str = "Confirmer ?", key: str = "default") -> None:
    """
    Displays a confirmation dialog with the given title.
    Updates st.session_state[key] with True (confirmed) or False (cancelled).
    """

    @st.dialog(title)
    def _dialog():
        st.write(message)

        _, c1, _, c2, _ = st.columns([0.3, 1, 0.5, 1, 0.3])

        if c1.button("Annuler", icon=":material/cancel:", width="stretch"):
            st.session_state[key] = False
            st.rerun()

        if c2.button("Confirmer", icon=":material/check:", width="stretch", type="primary"):
            st.session_state[key] = True
            st.rerun()

    _dialog()
