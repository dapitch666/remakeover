"""Configuration page."""

import os
import shutil

import streamlit as st

import src.dialog as _dialog
from src.config import get_device_data_dir
from src.ui_common import rainbow_divider

config = st.session_state.get("config", {})
add_log = st.session_state.get("add_log", lambda msg: None)
save_config = st.session_state.get("save_config", lambda c: None)
resolve_device_type = st.session_state.get("resolve_device_type")
DEFAULT_DEVICE_TYPE = st.session_state.get("DEFAULT_DEVICE_TYPE", "reMarkable 2")

st.title(":material/settings: Configuration des appareils")
rainbow_divider()

if st.session_state.get("config_saved_name"):
    saved_name = st.session_state.pop("config_saved_name")
    st.success(f"Configuration de '{saved_name}' sauvegardée !", icon=":material/task_alt:")

if st.session_state.get("config_deleted_name"):
    deleted_name = st.session_state.pop("config_deleted_name")
    st.success(f"'{deleted_name}' supprimé !", icon=":material/task_alt:")

DEVICES = config.get("devices", {})
if DEVICES:
    st.subheader("Appareils configurés", divider="rainbow")
    device_names = list(DEVICES.keys())
    if device_names:
        selected_device = st.selectbox("Sélectionner un appareil à modifier", ["-- Créer un nouvel appareil --"] + device_names)
    else:
        selected_device = "-- Créer un nouvel appareil --"

if not DEVICES or selected_device == "-- Créer un nouvel appareil --":
    st.subheader("Créer un nouvel appareil", divider="rainbow")
    device_name = st.text_input("Nom de l'appareil", "")
    device_config = {
        "ip": "",
        "password": "",
        "device_type": DEFAULT_DEVICE_TYPE,
        "templates": True,
        "carousel": True,
    }
    is_new = True
else:
    st.subheader(f"Modifier: {selected_device}", divider="rainbow")
    device_name = selected_device
    device_config = DEVICES[selected_device].copy()
    is_new = False

col1, col2 = st.columns(2)
with col1:
    ip = st.text_input("Adresse IP", device_config.get("ip", ""), placeholder="192.168.x.x")
    password = st.text_input("Mot de passe SSH", device_config.get("password", ""), type="password")

with col2:
    device_type = st.selectbox(
        "Type de tablette",
        list(resolve_device_type.__self__ if hasattr(resolve_device_type, "__self__") else []) or [device_config.get("device_type", DEFAULT_DEVICE_TYPE)],
        index=0,
    )
    templates = st.toggle("Activer les templates", value=device_config.get("templates", True))
    carousel = st.toggle("Désactiver le carousel", value=device_config.get("carousel", True))

st.info("💡 Pour trouver l'adresse IP et le mot de passe root de votre reMarkable, activez le mode développeur si nécessaire, allez dans Paramètres > Aide > À propos > Copyrights et licences, puis faites défiler la colonne de droite si nécessaire.")

col_save, col_delete = st.columns([3, 1])
with col_save:
    if st.button("Sauvegarder", key=f"ui_config_save_{device_name}", width="stretch", icon=":material/save:", help="Enregistrer la configuration de l'appareil"):
        if is_new and not device_name:
            st.error("Veuillez donner un nom à l'appareil", icon=":material/error:")
        else:
            new_config = {
                "ip": ip,
                "password": password,
                "device_type": device_type,
                "templates": templates,
                "carousel": carousel,
            }
            config["devices"][device_name] = new_config
            save_config(config)
            add_log(f"Configuration saved for '{device_name}'")
            st.session_state["config_saved_name"] = device_name
            st.rerun()

with col_delete:
    if not is_new and st.button("Supprimer", key=f"ui_config_delete_{device_name}", type="primary", width="stretch", icon=":material/delete:", help="Supprimer cet appareil et ses images locales"):
        st.session_state["pending_delete_device"] = device_name
        st.rerun()

if st.session_state.get("pending_delete_device") == device_name:
    _dialog.confirm(
        "Confirmer la suppression",
        f"Confirmez-vous la suppression de l'appareil '{device_name}' ? Cette action supprimera aussi ses images locales.",
        key=f"del_device_{device_name}",
    )
    if st.session_state.get(f"del_device_{device_name}") is True:
        device_data_dir = get_device_data_dir(device_name)
        if os.path.exists(device_data_dir):
            try:
                shutil.rmtree(device_data_dir)
                add_log(f"Device data directory removed for '{device_name}'")
            except OSError as e:
                add_log(f"Could not fully remove data dir for '{device_name}': {e}")
        if device_name in config.get("devices", {}):
            del config["devices"][device_name]
            save_config(config)
        add_log(f"Configuration deleted for '{device_name}'")
        st.session_state["config_deleted_name"] = device_name
        del st.session_state["pending_delete_device"]
        del st.session_state[f"del_device_{device_name}"]
        st.rerun()
    elif st.session_state.get(f"del_device_{device_name}") is False:
        del st.session_state[f"del_device_{device_name}"]
        del st.session_state["pending_delete_device"]
        st.rerun()
