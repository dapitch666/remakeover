import streamlit as st

import paramiko
from PIL import Image
import io
import os
import json
from datetime import datetime

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
    else:
        # Default configuration if the file doesn't exist
        return {
            "devices": {
                "Anne (rM Paper Pro)": {
                    "ip": "192.168.1.174",
                    "password": "",
                    "device_type": "reMarkable Paper Pro",
                    "templates": False,
                    "carousel": True
                },
                "Benoît (rM Move)": {
                    "ip": "192.168.1.144",
                    "password": "",
                    "device_type": "reMarkable Paper Pro Move",
                    "templates": False,
                    "carousel": True
                }
            }
        }

def save_config(config):
    """Save configuration to the JSON file."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

def run_ssh_cmd(ip, password, commands):
    add_log(f"SSH connect to {ip} (commands={len(commands)})")
    client = paramiko.SSHClient()
    # TODO: Ensure that if a hostkey changes (e.g. after an update), we still
    # accept the connection and update the stored hostkey. Currently, when the
    # hostkey changes the connection fails and users must manually remove the
    # hostkey from ~/.ssh/known_hosts, which is not ideal for non-technical users.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(ip, username='root', password=password, timeout=10)
        # First check whether root is already mounted read-write.
        check_cmd = (
            "if mount | grep \"on / \" | grep -q \"(rw,\"; then printf \"writable\"; else printf \"readonly\"; fi"
        )
        try:
            stdin, stdout, stderr = client.exec_command(check_cmd)
            check_out = stdout.read().decode().strip()
            check_err = stderr.read().decode().strip()
        except Exception as e:
            add_log(f"SSH check command failed on {ip}: {e}")
            check_out = "readonly"

        # If not writable, prepend remount command; otherwise run commands directly.
        if check_out == "writable":
            full_cmd = " && ".join(commands) if commands else ""
        else:
            full_cmd = ("mount -o remount,rw / && " + " && ".join(commands)) if commands else "mount -o remount,rw /"

        try:
            stdin, stdout, stderr = client.exec_command(full_cmd)
            output = stdout.read().decode()
            error = stderr.read().decode()
        except Exception as e:
            add_log(f"SSH exec failed on {ip}: {e}")
            client.close()
            return "", str(e)

        client.close()
        add_log(f"SSH exec on {ip} (check={check_out}, out_len={len(output)}, err_len={len(error)})")
        return output, error
    except Exception as e:
        add_log(f"SSH error on {ip}: {str(e)}")
        return "", str(e)

def test_ssh_connection(ip, password):
    """Test simple SSH connectivity without modifying the device."""
    add_log(f"SSH connectivity test start for {ip}")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(ip, username='root', password=password, timeout=10)
        stdin, stdout, stderr = client.exec_command("echo ok")
        output = stdout.read().decode().strip()
        error = stderr.read().decode().strip()
        client.close()
        add_log(f"SSH connectivity test OK for {ip} (out={output}, err_len={len(error)})")
        return output == "ok", error
    except Exception as e:
        add_log(f"SSH connectivity test error for {ip}: {str(e)}")
        return False, str(e)

def process_image(uploaded_file, width, height):
    img = Image.open(uploaded_file)
    
    # If the image is already PNG and the correct size, return it as-is
    if img.format == "PNG" and img.size == (width, height):
        uploaded_file.seek(0)
        return uploaded_file.read()
    
    # Otherwise, process the image
    if img.size != (width, height):
        img = img.resize((width, height), Image.Resampling.LANCZOS)
    
    img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def upload_file_ssh(ip, password, file_content, remote_path):
    add_log(f"SSH prepare upload to {ip}:{remote_path} (bytes={len(file_content)})")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(ip, username='root', password=password, timeout=10)
        # Mount the filesystem RW before uploading
        stdin, stdout, stderr = client.exec_command("mount -o remount,rw /")
        stdout.read()
        client.close()
    except Exception as e:
        add_log(f"SSH RW mount failed on {ip}: {str(e)}")
        return False, str(e)
    
    # Now upload the file via SFTP
    transport = paramiko.Transport((ip, 22))
    transport.connect(username='root', password=password)
    sftp = paramiko.SFTPClient.from_transport(transport)
    
    try:
        with sftp.file(remote_path, 'wb') as f:
            f.write(file_content)
        sftp.close()
        transport.close()
        add_log(f"SFTP upload OK to {ip}:{remote_path} (bytes={len(file_content)})")
        return True, "OK"
    except Exception as e:
        sftp.close()
        transport.close()
        add_log(f"SFTP upload error to {ip}:{remote_path}: {str(e)}")
        return False, str(e)

def download_file_ssh(ip, password, remote_path):
    """Download a file from the tablet."""
    add_log(f"SFTP download start from {ip}:{remote_path}")
    transport = paramiko.Transport((ip, 22))
    transport.connect(username='root', password=password)
    sftp = paramiko.SFTPClient.from_transport(transport)
    
    with sftp.file(remote_path, 'rb') as f:
        content = f.read()
    
    sftp.close()
    transport.close()
    add_log(f"SFTP download OK from {ip}:{remote_path} (bytes={len(content)})")
    return content

def get_device_images_dir(device_name):
    """Return the images directory for a device and create it if needed."""
    device_dir = os.path.join(IMAGES_DIR, device_name.replace("/", "_").replace(" ", "_"))
    os.makedirs(device_dir, exist_ok=True)
    return device_dir

def list_device_images(device_name):
    """List all stored images for a device."""
    device_dir = get_device_images_dir(device_name)
    if not os.path.exists(device_dir):
        return []
    return sorted([f for f in os.listdir(device_dir) if f.endswith('.png')])

def save_device_image(device_name, image_data, filename):
    """Save an image for a device."""
    device_dir = get_device_images_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    with open(filepath, 'wb') as f:
        f.write(image_data)
    return filepath

def load_device_image(device_name, filename):
    """Load an image from a device."""
    device_dir = get_device_images_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    with open(filepath, 'rb') as f:
        return f.read()

def delete_device_image(device_name, filename):
    """Delete an image from a device."""
    device_dir = get_device_images_dir(device_name)
    filepath = os.path.join(device_dir, filename)
    if os.path.exists(filepath):
        os.remove(filepath)

def rename_device_image(device_name, old_filename, new_filename):
    """Rename an image for a device."""
    device_dir = get_device_images_dir(device_name)
    old_path = os.path.join(device_dir, old_filename)
    new_path = os.path.join(device_dir, new_filename)
    if os.path.exists(old_path):
        os.rename(old_path, new_path)
        return True
    return False

def resolve_device_type(device):
    device_type = device.get("device_type")
    if device_type in DEVICE_SIZES:
        return device_type

    width = device.get("suspended_width")
    height = device.get("suspended_height")
    for name, (w, h) in DEVICE_SIZES.items():
        if width == w and height == h:
            return name

    return DEFAULT_DEVICE_TYPE

# --- STREAMLIT INTERFACE ---
# TODO: Change the page icon (favicon)
st.set_page_config(page_title="rM Manager", page_icon="📝")
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

def add_log(message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state['logs'].append(f"{ts} - {message}")

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

if page == ":material/description: Logs":
    st.title(":material/description: Logs de session")
    if not st.session_state['logs']:
        st.info("Aucun log pour cette session.")
    else:
        for entry in reversed(st.session_state['logs']):
            st.text(entry)

    if st.button("Effacer les logs de cette session", icon=":material/delete:", help="Efface les logs stockés dans la session en cours"):
        st.session_state['logs'] = []
        st.success("Logs effacés.", icon=":material/task_alt:")
        st.rerun()

    st.stop()

if page == ":material/settings: Configuration":
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
        st.warning(f"Confirmez-vous la suppression de l'appareil '{device_name}' ? Cette action supprimera aussi ses images locales.")
        c1, c2 = st.columns([1, 1])
        with c1:
            if st.button("Confirmer la suppression", key=f"confirm_delete_{device_name}", help="Confirme la suppression définitive de cet appareil"):
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
                st.session_state.pop("pending_delete_device", None)
                st.rerun()
        with c2:
            if st.button("Annuler", key=f"cancel_delete_{device_name}", help="Annuler la suppression de cet appareil"):
                st.session_state.pop("pending_delete_device", None)
                st.rerun()

else:  # Page principale de gestion
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
            else:
                st.toast(f"Connexion SSH impossible : {err}", icon=":material/error:")

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
                        st.warning(f"Confirmez-vous la suppression de {img_name} ?")
                        c1, c2 = st.columns([1, 1])
                        with c1:
                            if st.button("Oui", key=f"confirm_del_{img_name}", help="Confirmer la suppression", width='stretch', type="primary"):
                                delete_device_image(selected_name, img_name)
                                if preferred_image == img_name:
                                    config["devices"][selected_name].pop("preferred_image", None)
                                    save_config(config)
                                    add_log(f"Preferred image removed for '{selected_name}' because {img_name} was deleted")
                                add_log(f"Deleted {img_name} from '{selected_name}'")
                                st.session_state.pop(pending_key, None)
                                st.rerun()
                        with c2:
                            if st.button("Non", key=f"cancel_del_{img_name}", help="Annuler la suppression", width='stretch'):
                                st.session_state.pop(pending_key, None)
                                st.rerun()
                    else:
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
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"{timestamp}.png"
                save_device_image(selected_name, img_data, filename)
                add_log(f"Downloaded suspended.png from '{selected_name}' as {filename}")
                st.toast(f"Image sauvegardée : {filename}", icon=":material/task_alt:")
                st.rerun()
            except Exception as e:
                st.error(f"Erreur : {str(e)}", icon=":material/error:")
    
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
    
    # Expliquer les actions qui seront effectuées par le script de maintenance
    with st.expander("Ce que le script va faire : (cliquer pour développer)", expanded=False):
        st.markdown("**Ce script va :**")
        st.markdown("- Vérifier que le système de fichiers est writable et le remonter en lecture-écriture si nécessaire")
        if device.get('preferred_image'):
            st.markdown(f"- Uploader l'image préférée (`{device.get('preferred_image')}`) comme `suspended.png` sur la tablette")
        elif has_images:
            st.markdown("- Uploader une image de la bibliothèque locale comme `suspended.png` sur la tablette")
        if device.get('template', True):
             st.markdown("- Assurer l'existence des dossiers de templates custom sur la tablette")
             st.markdown("- Uploader les fichiers SVG de templates locaux vers la tablette et créer les liens nécessaires")
             st.markdown("- Sauvegarder le `templates.json` distant, le comparer avec une version locale si elle existe, et remplacer le distant par la version locale si elles diffèrent")
        if device.get('carousel', True):
            st.markdown("- Désactiver le carousel en déplaçant les illustrations actuelles dans un dossier de backup")
        st.markdown("- Redémarrer le service `xochitl` pour appliquer les changements")

    col1, col2, col3 = st.columns([1, 3, 1])
    with col2:
        if st.button("Lancer le script complet",
                     icon=":material/autorenew:",
                     help="Exécuter les actions de maintenance post-mise à jour",
                     type="primary",
                     width='stretch'):
            # provide a status area and progress bar for immediate feedback
            try:
                try:
                    status = st.status("Démarrage de la maintenance...")
                except Exception:
                    status = st.empty()
                    status.text("Démarrage de la maintenance...")
                progress = st.progress(0)

                # align maintenance steps with run_after_update.sh behavior
                steps = []
                steps.append("Upload de suspended.png depuis le dépôt (ou image locale si non présente)")
                steps.append("Assurer l'existence des dossiers de templates sur la tablette")
                steps.append("Upload des fichiers SVG de templates locaux vers la tablette")
                steps.append("Sauvegarde et comparaison de templates.json distant")
                steps.append("Désactivation / sauvegarde du carousel si activé")
                steps.append("Redémarrage du service xochitl")

                total = len(steps)
                current = [0]

                def step(msg):
                    current[0] += 1
                    pct = int((current[0] / total) * 100)
                    try:
                        status.text(f"{current[0]}/{total} — {msg}")
                    except Exception:
                        status.markdown(f"**{msg}**")
                    progress.progress(pct)
                    add_log(msg)

                # 1) Check writable filesystem (best-effort) using the POSIX snippet from run_after_update.sh
                step(steps[0])
                try:
                    check_cmd = (
                        "if mount | grep \"on / \" | grep -q \"(rw,\"; then\n"
                        "  printf \"  / is already writable\"\n"
                        "else\n"
                        "  printf \"  Remounting / read-write\\n\"\n"
                        "  mount -o remount,rw /\n"
                        "  printf \"  Remounted / read-write\"\n"
                        "fi"
                    )
                    remount_out, remount_err = run_ssh_cmd_no_remount(device['ip'], device.get('password', ''), [check_cmd])
                    remount_trim = remount_out.strip()
                    if remount_trim:
                        step(remount_trim)
                    else:
                        step("Vérification du système de fichiers exécutée")
                    add_log(f"Filesystem check output for {device['ip']}: {remount_trim} err_len={len(remount_err)}")
                except Exception as e:
                    add_log(f"Filesystem writable check failed: {e}")
                    step("Erreur lors de la vérification du système de fichiers")

                # 2) Upload suspended.png (prefer repo suspended.png if present)
                step(steps[1])
                try:
                    repo_suspended = os.path.join(BASE_DIR, 'suspended.png')
                    chosen_image = None
                    chosen_source = None
                    if preferred_image and os.path.exists(os.path.join(get_device_images_dir(selected_name), preferred_image)):
                        chosen_source = 'preferred'
                        img_blob = load_device_image(selected_name, preferred_image)
                        chosen_image = preferred_image
                    elif has_images:
                        import random
                        chosen_image = random.choice(imgs_available)
                        img_blob = load_device_image(selected_name, chosen_image)
                        chosen_source = 'library'

                    if chosen_image and img_blob:
                        success, msg = upload_file_ssh(device['ip'], device.get('password', ''), img_blob, "/usr/share/remarkable/suspended.png")
                        if success:
                            add_log(f"Uploaded {chosen_image} (source={chosen_source}) as suspended.png to '{selected_name}'")
                            step(f"suspended.png uploadé ({chosen_image})")
                        else:
                            add_log(f"Error uploading suspended.png: {msg}")
                            step(f"Erreur upload suspended.png: {msg}")
                    else:
                        step("Aucune image locale disponible pour upload comme suspended.png")
                except Exception as e:
                    add_log(f"Error during suspended.png upload: {e}")
                    step(f"Erreur upload suspended.png: {str(e)}")

                # 3) Ensure remote template dirs exist and upload templates
                step(steps[2])
                if device.get('templates', True):
                    try:
                        remote_custom_dir = "/home/root/templates"
                        remote_templates_dir = "/usr/share/remarkable/templates"
                        # ensure dirs
                        run_ssh_cmd(device['ip'], device.get('password', ''), [f"mkdir -p '{remote_custom_dir}' '{remote_templates_dir}'"])
                        step("Dossiers de templates créés sur la tablette (si nécessaire)")
                    except Exception as e:
                        add_log(f"Error ensuring remote template dirs: {e}")
                        step(f"Erreur création dossiers templates: {str(e)}")

                # 4) Upload template SVGs from local templates directories
                step(steps[3])
                if device.get('templates', True):
                    try:
                        local_templates_dirs = [os.path.join(BASE_DIR, 'templates'), os.path.join(BASE_DIR, 'data', 'templates')]
                        sent_count = 0
                        for local_templates_dir in local_templates_dirs:
                            if os.path.exists(local_templates_dir):
                                for fname in os.listdir(local_templates_dir):
                                    if fname.lower().endswith('.svg'):
                                        local_path = os.path.join(local_templates_dir, fname)
                                        with open(local_path, 'rb') as lf:
                                            content = lf.read()
                                        remote_path = f"{remote_custom_dir}/{fname}"
                                        ok, msg = upload_file_ssh(device['ip'], device.get('password', ''), content, remote_path)
                                        if ok:
                                            sent_count += 1
                        if sent_count:
                            # create symlinks for uploaded svgs
                            run_ssh_cmd(device['ip'], device.get('password', ''), [f"for file in {remote_custom_dir}/*.svg; do [ -f \"$file\" ] || continue; ln -sf \"$file\" \"{remote_templates_dir}/\"$(basename \"$file\"); done"])
                            step(f"{sent_count} templates SVG uploadés et liens créés")
                        else:
                            step("Aucun fichier SVG de template local trouvé à uploader")
                    except Exception as e:
                        add_log(f"Error uploading templates: {e}")
                        step(f"Erreur upload templates: {str(e)}")

                # 5) Backup/compare remote templates.json with local and replace
                step(steps[4])
                if device.get('templates', True):
                    try:
                        remote_templates_json = f"{remote_templates_dir}/templates.json"
                        try:
                            remote_content = download_file_ssh(device['ip'], device.get('password', ''), remote_templates_json)
                            local_templates_json = os.path.join(BASE_DIR, 'templates.json')
                            if os.path.exists(local_templates_json):
                                with open(local_templates_json, 'rb') as lf:
                                    local_content = lf.read()
                                if remote_content != local_content:
                                    backup_path = os.path.join(BASE_DIR, 'templates.backup.json')
                                    with open(backup_path, 'wb') as bf:
                                        bf.write(remote_content)
                                    add_log(f"Remote templates.json backed up to {backup_path}")
                                    # replace remote with local
                                    ok, msg = upload_file_ssh(device['ip'], device.get('password', ''), local_content, remote_templates_json)
                                    if ok:
                                        step("templates.json remplacé par la version locale")
                                    else:
                                        step(f"Erreur en remplaçant templates.json: {msg}")
                                else:
                                    step("templates.json distant identique au local; pas de backup nécessaire")
                            else:
                                step("Aucun templates.json local trouvé pour comparaison")
                        except Exception as e:
                            add_log(f"Impossible de télécharger templates.json: {e}")
                            step("Aucun templates.json distant trouvé ou erreur de téléchargement")
                    except Exception as e:
                        add_log(f"Error handling templates.json: {e}")

                # 5) Disable carousel
                step("Désactivation / sauvegarde du carousel si activé")
                if device.get('carousel', True):
                    try:
                        cmds = []
                        cmds.append("mkdir -p /usr/share/remarkable/carousel/backupIllustrations")
                        cmds.append("mv /usr/share/remarkable/carousel/*.png /usr/share/remarkable/carousel/backupIllustrations/ 2>/dev/null || true")
                    except Exception as e:
                        add_log(f"Error handling carousel: {e}")
                        step(f"Erreur carousel: {str(e)}")

                #6) Restart xochitl
                step("Redémarrage de xochitl")
                try:
                    cmds.append("systemctl restart xochitl")
                    out, err = run_ssh_cmd(device['ip'], device.get('password', ''), cmds)
                    add_log(f"Command executed: out={out.strip()} err={err.strip()}")
                    step("Redémarrage de xochitl demandé")
                except Exception as e:
                    add_log(f"Error restarting xochitl: {e}")
                    step(f"Erreur redémarrage xochitl: {str(e)}")


                # finish
                progress.progress(100)
                try:
                    status.text("Maintenance terminée")
                except Exception:
                    status.markdown("**Maintenance terminée**")
                st.toast("Maintenance terminée", icon=":material/task_alt:")
            except Exception as e:
                add_log(f"Unexpected error during maintenance: {e}")
                try:
                    status.text(f"Erreur inattendue: {e}")
                except Exception:
                    status.markdown(f"**Erreur inattendue: {e}**")


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
