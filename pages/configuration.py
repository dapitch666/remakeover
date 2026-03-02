"""Configuration page."""

import ipaddress
import os
import shutil

import streamlit as st

import src.dialog as _dialog
from src.config import get_device_data_dir, save_config, resolve_device_type
from src.constants import DEVICE_SIZES, DEFAULT_DEVICE_TYPE
from src.ui_common import rainbow_divider, deferred_toast

config = st.session_state.get("config", {})
add_log = st.session_state.get("add_log", lambda msg: None)

st.title(":material/settings: Configuration des appareils")
rainbow_divider()

DEVICES = config.get("devices", {})
selected_name = st.session_state.get("selected_name")

# Determine whether we're in "create new" mode
creating_new = st.session_state.get("config_creating_new", False)

if DEVICES and selected_name in DEVICES and not creating_new:
    col_title, col_btn = st.columns([3, 1], vertical_alignment="bottom")
    with col_title:
        st.subheader(f"Modifier : {selected_name}", divider="rainbow")
    with col_btn:
        if st.button("Nouvel appareil", key="ui_config_new", icon=":material/add:", width="stretch"):
            st.session_state["config_creating_new"] = True
            st.rerun()
    device_name = selected_name
    device_config = DEVICES[selected_name].copy()
    is_new = False
else:
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

col1, col2 = st.columns(2)
with col1:
    ip = st.text_input("Adresse IP", device_config.get("ip", ""), placeholder="192.168.x.x")
    password = st.text_input("Mot de passe SSH", device_config.get("password", ""), type="password")

with col2:
    _device_types = list(DEVICE_SIZES.keys())
    _current_type = device_config.get("device_type", DEFAULT_DEVICE_TYPE)
    _type_index = _device_types.index(_current_type) if _current_type in _device_types else 0
    device_type = st.selectbox(
        "Type de tablette",
        _device_types,
        index=_type_index,
    )
    templates = st.toggle("Activer les templates", value=device_config.get("templates", True))
    carousel = st.toggle("Désactiver le carousel", value=device_config.get("carousel", True))

st.info("💡 Pour trouver l'adresse IP et le mot de passe root de votre reMarkable, activez le mode développeur si nécessaire, allez dans Paramètres > Aide > À propos > Copyrights et licences, puis faites défiler la colonne de droite si nécessaire.")

col_save, col_delete = st.columns([3, 1])
with col_save:
    if st.button("Sauvegarder", key=f"ui_config_save_{device_name}", width="stretch", icon=":material/save:", help="Enregistrer la configuration de l'appareil"):
        if is_new and not device_name:
            st.error("Veuillez donner un nom à l'appareil", icon=":material/error:")
        elif is_new and device_name in DEVICES:
            st.error(f"Un appareil nommé '{device_name}' existe déjà. Choisissez un autre nom.", icon=":material/error:")
        elif not ip.strip():
            st.error("Veuillez saisir une adresse IP.", icon=":material/error:")
        else:
            try:
                ipaddress.ip_address(ip.strip())
            except ValueError:
                st.error(f"'{ip}' n'est pas une adresse IP valide (ex. : 192.168.1.100).", icon=":material/error:")
            else:
                new_config = {
                    "ip": ip.strip(),
                    "password": password,
                    "device_type": device_type,
                    "templates": templates,
                    "carousel": carousel,
                }
                config["devices"][device_name] = new_config
                save_config(config)
                add_log(f"Configuration saved for '{device_name}'")
                deferred_toast(f"Configuration de '{device_name}' sauvegardée !", ":material/task_alt:")
                st.session_state["pending_selected_tablet"] = device_name
                st.session_state.pop("config_creating_new", None)
                st.rerun()

with col_delete:
    if not is_new and st.button("Supprimer", key=f"ui_config_delete_{device_name}", type="primary", width="stretch", icon=":material/delete:", help="Supprimer cet appareil et ses images locales"):
        st.session_state["pending_delete_device"] = device_name
        st.rerun()
    if is_new and selected_name in DEVICES and st.button("Annuler", key="ui_config_cancel", width="stretch", icon=":material/close:"):
        st.session_state.pop("config_creating_new", None)
        st.rerun()

if st.session_state.get("pending_delete_device") == device_name:
    _dialog.confirm(
        "Confirmer la suppression",
        f"Confirmez-vous la suppression de l'appareil '{device_name}' ? Cette action supprimera aussi ses images et templates locaux.",
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
        deferred_toast(f"'{device_name}' supprimé !", ":material/task_alt:")
        del st.session_state["pending_delete_device"]
        del st.session_state[f"del_device_{device_name}"]
        st.rerun()
    elif st.session_state.get(f"del_device_{device_name}") is False:
        del st.session_state[f"del_device_{device_name}"]
        del st.session_state["pending_delete_device"]
        st.rerun()
