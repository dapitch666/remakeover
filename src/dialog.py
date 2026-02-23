import streamlit as st


def confirm(title: str = "Confirmer", message: str = "Confirmer ?", key: str = "default") -> bool | None:
    """Afficher une boîte de dialogue de confirmation réutilisable.

    Retourne True si l'utilisateur confirme, False si annule, ou None
    si la boîte vient juste d'être ouverte (le flux Streamlit rerun sera déclenché).

    Exemple:
        res = confirm("Supprimer", "Voulez-vous supprimer cet élément ?", key="del1")
        if res is True:
            # confirmed
        elif res is False:
            # cancelled
    """
    result_key = f"_confirm_result_{key}"
    cancel_key = f"_confirm_cancel_{key}"
    confirm_key = f"_confirm_ok_{key}"

    if result_key not in st.session_state:
        st.session_state[result_key] = None

    @st.dialog(title)
    def _dialog():
        st.write(message)
        _, c1, _, c2, _ = st.columns([0.5, 1, 0.5, 1, 0.5])
        if c1.button("Annuler", key=cancel_key, width="stretch"):
            st.session_state[result_key] = False
            st.rerun()
        if c2.button("Confirmer", key=confirm_key, width="stretch", type="primary"):
            st.session_state[result_key] = True
            st.rerun()

    _dialog()
    return st.session_state.get(result_key)
