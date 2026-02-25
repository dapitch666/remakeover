import streamlit as st

@st.dialog("Confirmation")
def confirm(title: str = "Confirmer", message: str = "Confirmer ?", key: str = "default") -> bool | None:
    """
    Displays a confirmation dialog with "Confirmer" and "Annuler" buttons. Returns True if confirmed, False if cancelled, and None if no action taken.
    Updates st.session_state[key] with True or False.
    """
    st.write(message)
    
    _, c1, _, c2, _ = st.columns([0.3, 1, 0.5, 1, 0.3])
    
    if c1.button("Annuler", icon=":material/cancel:", width="stretch"):
        st.session_state[key] = False
        st.rerun()
            
    if c2.button("Confirmer", icon=":material/check:", width="stretch", type="primary"):
        st.session_state[key] = True
        st.rerun()