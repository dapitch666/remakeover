import streamlit as st

import os
import json
from datetime import datetime
from src.dialog import confirm

# --- CONFIGURATION ---
# Detect environment (Docker or local)
if os.path.exists("/app"):
    # Docker mode
    BASE_DIR = "/app"
else:
    # Local development mode
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, "data", "config.json")
IMAGES_DIR = os.path.join(BASE_DIR, "data", "images")

DEVICE_SIZES = {
    "reMarkable 2": (1404, 1872),
    "reMarkable Paper Pro": (1620, 2160),
    "reMarkable Paper Pro Move": (954, 1696),
}
DEFAULT_DEVICE_TYPE = "reMarkable Paper Pro"


def truncate_display_name(name: str, max_len: int = 13) -> str:
    """Return a truncated version of the name for display (adds '...' when truncated)."""
    if not isinstance(name, str):
        return str(name)
    if len(name) <= max_len:
        return name
    # Keep a bit of room for an extension indicator if present
    return name[: max_len - 3] + "..."

def load_config():
    """Load configuration from the JSON file."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    elif BASE_DIR != "/app":
        # Default configuration if the file doesn't exist
        default_config = {
            "devices": {
                "Anne (rM Paper Pro)": {
                    "ip": "192.168.1.174",
                    "password": "a5g7du9FkY",
                    "device_type": "reMarkable Paper Pro",
                    "templates": False,
                    "carousel": True
                },
                "Benoît (rM Move)": {
                    "ip": "192.168.1.144",
                    "password": "3JRpokPWbA",
                    "device_type": "reMarkable Paper Pro Move",
                    "templates": False,
                    "carousel": True
                }
            }
        }
        save_config(default_config)
        return default_config
    else:
        return {"devices": {}}

def save_config(config):
    """Save configuration to the JSON file."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

from src.ssh import (
    run_ssh_cmd,
    upload_file_ssh,
    download_file_ssh,
    test_ssh_connection,
)
from src.images import (
    process_image,
    get_device_images_dir,
    list_device_images,
    save_device_image,
    load_device_image,
    delete_device_image,
    rename_device_image,
)
from src.maintenance import run_maintenance

def resolve_device_type(device):
    device_type = device.get("device_type")
    if device_type in DEVICE_SIZES:
        return device_type

    return DEFAULT_DEVICE_TYPE

# --- STREAMLIT INTERFACE ---


# Session logging helper (module-level so UI and non-UI code can use it)
def add_log(message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Ensure logs list exists
    try:
        if 'logs' not in st.session_state:
            st.session_state['logs'] = []
        st.session_state['logs'].append(f"{ts} - {message}")
    except Exception:
        # When called outside of Streamlit runtime, fallback to printing
        try:
            print(f"{ts} - {message}")
        except Exception:
            pass


# UI adapter used by `run_maintenance` to update Streamlit UI elements.
# Defined at module level so it can be referenced outside `main()`.
class UIAdapter:
    def __init__(self, status_obj, progress_obj):
        self._status = status_obj
        self._progress = progress_obj

    def step(self, msg: str):
        try:
            self._status.text(msg)
        except Exception:
            pass
        add_log(msg)

    def progress(self, pct: int):
        try:
            self._progress.progress(pct)
        except Exception:
            pass

    def toast(self, msg: str):
        try:
            st.toast(msg, icon=":material/task_alt:")
        except Exception:
            pass

def main():
    st.set_page_config(page_title="rM Manager", page_icon="assets/favicon.png")
    st.logo(image="assets/logo.svg", size="large")

    # Display the image version if provided via environment or a VERSION file
    IMAGE_VERSION = os.environ.get("IMAGE_VERSION")
    if not IMAGE_VERSION:
        try:
            with open(os.path.join(BASE_DIR, "VERSION"), "r", encoding="utf-8") as vf:
                IMAGE_VERSION = vf.read().strip()
        except Exception:
            IMAGE_VERSION = None

    # --- SESSION LOGS ---
    if 'logs' not in st.session_state:
        st.session_state['logs'] = []

    # Load configuration
    config = load_config()
    DEVICES = config.get("devices", {})


    def submit_rename_factory(img, device_name):
        def _cb():
            key = f"rename_input_{img}"
            new_name = st.session_state.get(key, "")
            if new_name and new_name != img:
                try:
                    if rename_device_image(device_name, img, new_name):
                        # Update preferred image if needed
                        dev = config.get("devices", {}).get(device_name)
                        if dev and dev.get("preferred_image") == img:
                            config["devices"][device_name]["preferred_image"] = new_name
                            save_config(config)
                            add_log(f"Preferred image updated: {img} -> {new_name} for '{device_name}'")
                        add_log(f"Renamed {img} to {new_name} for '{device_name}'")
                        try:
                            st.toast(f"Renommé : {new_name}", icon=":material/task_alt:")
                        except Exception:
                            pass
                except Exception as e:
                    add_log(f"Error renaming {img} -> {new_name}: {e}")
            # exit edit mode (no st.rerun() — Streamlit will refresh on next interaction)
            st.session_state.pop(f"edit_{img}", None)

        return _cb

    # Navigation
    page = st.sidebar.radio("Navigation", [":material/mobile_gear: Gestion des tablettes", ":material/settings: Configuration", ":material/description: Logs"])

    # --- PAGE: Logs ---
    if page == ":material/description: Logs":
        st.title(":material/description: Logs de session")
        if not st.session_state['logs']:
            st.info("Aucun log pour cette session.")
        else:
            for entry in reversed(st.session_state['logs']):
                st.text(entry)
            if st.button("Effacer les logs de cette session", icon=":material/delete:", help="Efface les logs stockés dans la session en cours"):
                st.session_state.clear_logs = None
                confirm("Effacer les logs", "Effacer les logs de cette session ?", key="clear_logs")
            if st.session_state.get("clear_logs") is True:
                st.session_state['logs'] = []
                st.success("Logs effacés.", icon=":material/task_alt:")
                del st.session_state.clear_logs
                st.rerun()
        

    # --- PAGE: Configuration ---
    elif page == ":material/settings: Configuration":
        st.title(":material/settings: Configuration des appareils")

        if st.session_state.get("config_saved_name"):
            saved_name = st.session_state.pop("config_saved_name")
            st.success(f"Configuration de '{saved_name}' sauvegardée !", icon=":material/task_alt:")

        if st.session_state.get("config_deleted_name"):
            deleted_name = st.session_state.pop("config_deleted_name")
            st.success(f"'{deleted_name}' supprimé !", icon=":material/task_alt:")
        
        if DEVICES:
            # List existing devices
            st.subheader("Appareils configurés", divider="rainbow")
        
            # Select device to edit
            device_names = list(DEVICES.keys())
            if device_names:
                selected_device = st.selectbox("Sélectionner un appareil à modifier", ["-- Créer un nouvel appareil --"] + device_names)
            else:
                selected_device = "-- Créer un nouvel appareil --"
        
        
        # Edit form
        if not DEVICES or selected_device == "-- Créer un nouvel appareil --":
            st.subheader("Créer un nouvel appareil", divider="rainbow")
            device_name = st.text_input("Nom de l'appareil", "")
            device_config = {
                "ip": "",
                "password": "",
                "device_type": DEFAULT_DEVICE_TYPE,
                "templates": True,
                "carousel": True
            }
            is_new = True
        else:
            st.subheader(f"Modifier: {selected_device}", divider="rainbow")
            device_name = selected_device
            device_config = DEVICES[selected_device].copy()
            is_new = False
        
        # Form
        col1, col2 = st.columns(2)
        
        with col1:
            ip = st.text_input("Adresse IP", device_config.get("ip", ""), placeholder="192.168.x.x")
            password = st.text_input("Mot de passe SSH", device_config.get("password", ""), type="password")
        
        with col2:
            device_type = st.selectbox(
                "Type de tablette",
                list(DEVICE_SIZES.keys()),
                index=list(DEVICE_SIZES.keys()).index(resolve_device_type(device_config)),
            )
            templates = st.checkbox("Activer les templates", value=device_config.get("templates", True))
            carousel = st.checkbox("Désactiver le carousel", value=device_config.get("carousel", True))
        
        st.info("💡 Pour trouver l’adresse IP et le mot de passe root de votre reMarkable, activez le mode développeur si nécessaire, allez dans Paramètres > Aide > À propos > Copyrights et licences, puis faites défiler la colonne de droite si nécessaire.")
        
        col_save, col_delete = st.columns([3, 1])
        
        with col_save:
            if st.button("Sauvegarder", width='stretch', icon=":material/save:", help="Enregistrer la configuration de l'appareil"):
                if is_new and not device_name:
                    # TODO: Make a more robust check
                    st.error("Veuillez donner un nom à l'appareil", icon=":material/error:")
                else:
                    new_config = {
                        "ip": ip,
                        "password": password,
                        "device_type": device_type,
                        "templates": templates,
                        "carousel": carousel
                    }
                    
                    config["devices"][device_name] = new_config
                    save_config(config)
                    add_log(f"Configuration saved for '{device_name}'")
                    st.session_state["config_saved_name"] = device_name
                    st.rerun()
        
        with col_delete:
            if not is_new and st.button("Supprimer", type="primary", width='stretch', icon=":material/delete:", help="Supprimer cet appareil et ses images locales"):
                st.session_state["pending_delete_device"] = device_name
                st.rerun()

        # If a device deletion is pending, ask for confirmation
        if st.session_state.get("pending_delete_device") == device_name:
            confirm(
                "Confirmer la suppression",
                f"Confirmez-vous la suppression de l'appareil '{device_name}' ? Cette action supprimera aussi ses images locales.",
                key=f"del_device_{device_name}",
            )
            if st.session_state.get(f"del_device_{device_name}") is True:
                # Remove associated images
                device_images_dir = get_device_images_dir(device_name)
                if os.path.exists(device_images_dir):
                    for f in os.listdir(device_images_dir):
                        os.remove(os.path.join(device_images_dir, f))
                        add_log(f"Image '{f}' deleted for '{device_name}'")
                    try:
                        os.rmdir(device_images_dir)
                    except OSError:
                        pass
                # Remove configuration
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


    # PAGE: Main management page
    else:
        st.title("reMarkable Manager")
        
        if not DEVICES:
            st.warning("Aucun appareil configuré. Ajoutez-en un dans Configuration.")
            st.stop()
        
        col1, col2 = st.columns([2, 1], vertical_alignment="bottom")
        with col1:
            selected_name = st.selectbox("Choisir la tablette", list(DEVICES.keys()))
            device = DEVICES[selected_name]
            device_type = resolve_device_type(device)
            width, height = DEVICE_SIZES[device_type]
            preferred_image = device.get("preferred_image")

        with col2:
            if st.button("Tester la connectivité", icon=":material/wifi:", width='stretch', help="Vérifier la connexion SSH vers la tablette"):
                ok, err = test_ssh_connection(device['ip'], device.get('password', ''))
                if ok:
                    st.toast("Connexion SSH OK", icon=":material/task_alt:")
                    add_log(f"SSH connection successful to '{selected_name}'")
                else:
                    st.toast(f"Connexion SSH impossible : {err}", icon=":material/error:")
                    add_log(f"SSH connection failed to '{selected_name}': {err}")

        st.space()

        # Image Library
        st.subheader("Bibliothèque d'images suspended.png", divider="rainbow")
        
        # List stored images for this tablet
        stored_images = list_device_images(selected_name)
        
        if stored_images:
            # Single help expander explaining the actions available for images
            with st.expander("Aide — Actions des images (cliquer pour développer)", expanded=False):
                st.markdown(":material/cloud_upload: **Envoyer** — Mettre l'image comme écran de veille sur la tablette  ")
                st.markdown(":material/star: **Favori** — Définir ou supprimer l'image préférée  ")
                st.markdown(":material/delete: **Supprimer** — Effacer l'image localement  ")

            # Select existing images in a 4-column grid
            cols = st.columns(4, gap="medium")
            for idx, img_name in enumerate(stored_images):
                col_index = idx % 4
                with cols[col_index]:
                    img_data = load_device_image(selected_name, img_name)
                    
                    # Unique edit key for this image (defined before buttons)
                    edit_key = f"edit_{img_name}"
                    
                    star_prefix = ":material/star:" if img_name == preferred_image else None
                    # Show inline rename field if in edit mode, otherwise show name button
                    if st.session_state.get(edit_key):
                        # Inline text field that submits the rename on Enter
                        st.text_input(
                            "Renommer l'image",
                            value=img_name,
                            key=f"rename_input_{img_name}",
                            label_visibility="collapsed",
                            on_change=submit_rename_factory(img_name, selected_name),
                        )
                    else:
                        # Clicking the name activates edit mode (display truncated to avoid breaking layout)
                        display_name = truncate_display_name(img_name)
                        if st.button(f"**{display_name}**",
                                     key=f"name_{img_name}",
                                     help="Cliquez pour renommer",
                                     icon=star_prefix,
                                     type="tertiary",
                                     width='stretch'):
                            st.session_state[edit_key] = True
                            st.rerun()
                    
                    # Image
                    st.image(img_data, width='stretch')

                    # If not editing this name, display actions (send / delete)
                    if not st.session_state.get(edit_key):
                        pending_key = f"pending_delete_image_{img_name}"
                        if st.session_state.get(pending_key):
                            confirm(
                                "Confirmer la suppression",
                                f"Confirmez-vous la suppression de {img_name} ?",
                                key=f"del_img_{img_name}",
                            )
                            if st.session_state.get(f"del_img_{img_name}") is True:
                                delete_device_image(selected_name, img_name)
                                if preferred_image == img_name:
                                    config["devices"][selected_name].pop("preferred_image", None)
                                    save_config(config)
                                    add_log(f"Preferred image removed for '{selected_name}' because {img_name} was deleted")
                                add_log(f"Deleted {img_name} from '{selected_name}'")
                                del st.session_state[f"del_img_{img_name}"]
                                del st.session_state[pending_key]
                                st.rerun()
                            elif st.session_state.get(f"del_img_{img_name}") is False:
                                del st.session_state[f"del_img_{img_name}"]
                                del st.session_state[pending_key]
                                st.rerun()
                        
                        # Compact segmented control under each image using icons
                        action_key = f"action_{img_name}"
                        option_map = {
                            0: ":material/cloud_upload:",
                            1: ":material/star:",
                            2: ":material/delete:",
                        }

                        # Ensure session state key exists so the on_change handler can reset it
                        if action_key not in st.session_state:
                            st.session_state[action_key] = None

                        # Handler factory binds values to avoid closure loop issues
                        def make_action_handler(img_local=img_name, sel_key=action_key, pending_k=pending_key, sel_name=selected_name, dev=device, img_blob=img_data, pref=preferred_image):
                            def _handler():
                                selection = st.session_state.get(sel_key)
                                if selection is None:
                                    return
                                try:
                                    if selection == 0:
                                        success, msg = upload_file_ssh(dev['ip'], dev.get('password', ''), img_blob, "/usr/share/remarkable/suspended.png")
                                        if success:
                                            run_ssh_cmd(dev['ip'], dev.get('password', ''), ["systemctl restart xochitl"])
                                            add_log(f"Sent {img_local} to '{sel_name}'")
                                            try:
                                                st.toast("Envoyée !", icon=":material/task_alt:")
                                            except Exception:
                                                pass
                                        else:
                                            add_log(f"Error sending {img_local} to '{sel_name}': {msg}")
                                            try:
                                                st.toast(f"Erreur", icon=":material/error:")
                                            except Exception:
                                                pass
                                    elif selection == 1:
                                        # Toggle preferred image
                                        current_pref = config.get("devices", {}).get(sel_name, {}).get("preferred_image")
                                        if current_pref == img_local:
                                            config["devices"][sel_name].pop("preferred_image", None)
                                            add_log(f"Preferred image removed for '{sel_name}'")
                                            try:
                                                st.toast("Favori supprimé", icon=":material/task_alt:")
                                            except Exception:
                                                pass
                                        else:
                                            config["devices"][sel_name]["preferred_image"] = img_local
                                            add_log(f"Preferred image set: {img_local} for '{sel_name}'")
                                            try:
                                                st.toast("Favori défini", icon=":material/task_alt:")
                                            except Exception:
                                                pass
                                        save_config(config)
                                    elif selection == 2:
                                        st.session_state[pending_k] = True
                                        st.rerun()
                                finally:
                                    # Deselect the control so it appears unselected for the user
                                    try:
                                        st.session_state[sel_key] = None
                                    except Exception:
                                        pass

                            return _handler

                        st.segmented_control(
                            "Actions",
                            options=list(option_map.keys()),
                            format_func=lambda option: option_map[option],
                            key=action_key,
                            selection_mode="single",
                            label_visibility="hidden",
                            on_change=make_action_handler(),
                        )
        
        col1, col2 = st.columns(2)
        with col1:
            # Retrieve the current image from the tablet
            st.subheader("Récupérer l'image actuelle", divider="rainbow")
            if st.button("Importer depuis la tablette", icon=":material/download:", width='stretch', help="Télécharger l'image actuelle de l'écran de veille depuis la tablette"):
                try:
                    img_data = download_file_ssh(device['ip'], device.get('password', ''), "/usr/share/remarkable/suspended.png")
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    filename = f"{timestamp}.png"
                    save_device_image(selected_name, img_data, filename)
                    add_log(f"suspended.png from téléchargé de '{selected_name}' sous {filename}")
                    st.toast(f"Image sauvegardée : {filename}", icon=":material/task_alt:")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur : {str(e)}", icon=":material/error:")
                    add_log(f"Erreur lors du téléchargement de suspended.png depuis '{selected_name}': {str(e)}")
        
        with col2:
            # Upload new image
            st.subheader("Ajouter une image", divider="rainbow")
            uploaded_file = st.file_uploader(f"Glisser une image ici (sera convertie en PNG {width}x{height})", type=["png", "jpg", "jpeg"])
            
            if uploaded_file:
                col_save, col_send = st.columns(2)

                with col_save:
                    if st.button("Sauvegarder", icon=":material/save:", help="Sauvegarder l'image localement"):
                        img_data = process_image(uploaded_file, width, height)
                        filename = uploaded_file.name.replace(" ", "_")
                        if not filename.endswith('.png'):
                            filename = os.path.splitext(filename)[0] + '.png'
                        save_device_image(selected_name, img_data, filename)
                        add_log(f"Image uploaded and saved: {filename} for '{selected_name}'")
                        st.toast(f"Image sauvegardée : {filename}", icon=":material/task_alt:")
                        st.rerun()

                with col_send:
                    if st.button(f"Envoyer sur {selected_name}", icon=":material/cloud_upload:", help=f"Envoyer l'image sur {selected_name} et la sauvegarder localement"):
                        img_data = process_image(uploaded_file, width, height)
                        # Also save the image
                        filename = uploaded_file.name.replace(" ", "_")
                        if not filename.endswith('.png'):
                            filename = os.path.splitext(filename)[0] + '.png'
                        save_device_image(selected_name, img_data, filename)
                        # Send to the tablet
                        success, msg = upload_file_ssh(device['ip'], device.get('password', ''), img_data, "/usr/share/remarkable/suspended.png")
                        if success:
                            run_ssh_cmd(device['ip'], device.get('password', ''), ["systemctl restart xochitl"])
                            add_log(f"Image {filename} sent and saved on '{selected_name}'")
                            st.toast(f"{filename} envoyée et sauvegardée !", icon=":material/task_alt:")
                            st.rerun()
                        else:
                            add_log(f"Error sending {filename} to '{selected_name}': {msg}")
                            st.toast(f"Erreur lors de l'envoi : {msg}", icon=":material/error:")

        # Post-update maintenance actions
        st.subheader(":material/build: Maintenance après mise à jour", divider="rainbow")
        # gather local image/library info for later
        imgs_available = list_device_images(selected_name)
        has_images = bool(imgs_available)
        image = None
        
        # Expliquer les actions qui seront effectuées par le script de maintenance
        steps = []
        with st.expander("Ce que le script va faire : (cliquer pour développer)", expanded=False):
            st.markdown("**Ce script va :**")
            st.markdown("- Vérifier que le système de fichiers est writable et le remonter en lecture-écriture si nécessaire")
            
            if device.get('preferred_image'):
                image = device.get('preferred_image')
                st.markdown(f"- Téléverser l'image préférée (`{image}`) comme `suspended.png` sur la tablette")
            elif has_images:
                import random
                image = random.choice(imgs_available)
                st.markdown(f"- Téléverser `{image}` de la bibliothèque locale comme `suspended.png` sur la tablette (aucune image préférée définie)")
            if image:
                steps.append(f"Upload de l'image de suspension")
            if device.get('template'):
                st.markdown("- Assurer l'existence des dossiers de templates custom sur la tablette")
                st.markdown("- Uploader les fichiers SVG de templates locaux vers la tablette et créer les liens nécessaires")
                st.markdown("- Sauvegarder le `templates.json` distant, le comparer avec une version locale si elle existe, et remplacer le distant par la version locale si elles diffèrent")
                steps.append("Ajout des templates personnalisés")
            if device.get('carousel'):
                st.markdown("- Désactiver le carrousel en déplaçant les illustrations actuelles dans un dossier de backup")
                steps.append("Désactivation du carrousel")
            st.markdown("- Redémarrer le service `xochitl` pour appliquer les changements")
            steps.append("Redémarrage de xochitl")

        col1, col2, col3 = st.columns([1, 3, 1])
        with col2:
            if st.button("Lancer le script complet",
                         icon=":material/autorenew:",
                         help="Exécuter les actions de maintenance post-mise à jour",
                         type="primary",
                         width='stretch'):
                with st.status("Démarrage de la maintenance...") as status:
                    progress = st.progress(0)

                    ui = UIAdapter(status, progress)
                    result = run_maintenance(selected_name, device, BASE_DIR, steps, image, ui)

                # after exiting the status context manager
                if result.get("ok"):
                    ui.step("Maintenance terminée")
                    ui.progress(100)
                    ui.toast("Maintenance terminée")
                else:
                    ui.step("Maintenance terminée (avec erreurs)")
                    ui.toast("Maintenance terminée (avec erreurs)")
                    for e in result.get('errors', []):
                        add_log(f"Maintenance error: {e}")


    # Display the image version at the bottom of the sidebar via CSS (fixed position)
    def _display_image_version_bottom(version_text: str):
        if not version_text:
            return
        # CSS to fix at the bottom of the sidebar
        html = f"""
        <div style="position: fixed; left: 20px; bottom: 8px; font-size: 12px;">
          <a href="https://github.com/dapitch666/rm-manager" target="_blank" style="color: rgba(0, 0, 0, 0.6); text-decoration: none;">rm-manager - version {version_text}</a>
        </div>
        """
        try:
            st.sidebar.html(html)
        except Exception:
            # Fallback: simple caption if injection fails
            try:
                st.sidebar.caption(f"rm-manager version {version_text} (Unable to inject custom HTML/CSS)")
            except Exception:
                pass


    _display_image_version_bottom(IMAGE_VERSION)

    # Debug overlay: show `st.session_state` in a small corner when running locally or when
    # the `DEBUG` env var is set. Uses BASE_DIR detection (if not in /app assume local).
    try:
        debug_mode = (BASE_DIR != "/app") or os.environ.get("DEBUG", "") .lower() in ("1", "true", "yes")
    except Exception:
        debug_mode = False

    if debug_mode:
        try:
            import html as _pyhtml
            state_snapshot = {k: v for k, v in st.session_state.items()}
            state_json = json.dumps(state_snapshot, default=str, indent=2)
            safe_json = _pyhtml.escape(state_json)
            debug_html = f"""
            <div style="position:fixed; right:8px; top:8px; max-width:420px; max-height:45vh; overflow:auto; background:rgba(255,255,255,0.95); border:1px solid rgba(0,0,0,0.12); padding:8px; font-size:12px; z-index:99999; font-family:monospace; box-shadow:0 4px 12px rgba(0,0,0,0.08);">
              <details style="margin:0"><summary style="font-weight:600; cursor:pointer">session_state (debug)</summary>
              <pre style="white-space:pre-wrap; margin:6px 0 0 0;">{safe_json}</pre>
              </details>
            </div>
            """
            st.markdown(debug_html, unsafe_allow_html=True)
        except Exception:
            # If HTML injection fails, fall back to sidebar expander (guaranteed).
            st.sidebar.expander("session_state (debug)", expanded=False).write(dict(st.session_state))
        else:
            # Also show a sidebar expander as a robust fallback/visible area for debugging.
            try:
                st.sidebar.expander("session_state (debug)", expanded=False).write(dict(st.session_state))
            except Exception:
                pass


if __name__ == "__main__":
    main()
