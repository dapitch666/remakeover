import streamlit as st
import os
import random
from datetime import datetime
from src.dialog import confirm
from src.ssh import (
    run_ssh_cmd,
    upload_file_ssh,
    download_file_ssh,
    test_ssh_connection,
)
from src.images import (
    process_image,
    list_device_images,
    save_device_image,
    load_device_image,
    delete_device_image,
    rename_device_image,
)
from src.templates import (
    list_device_templates,
    save_device_template,
    delete_device_template,
    rename_device_template,
    rename_template_entry,
    get_device_templates_dir,
    get_device_templates_backup_path,
    get_template_entry,
    get_all_categories,
    add_template_entry,
    remove_template_entry,
    update_template_categories,
    ensure_remote_template_dirs,
    upload_template_svgs,
    get_device_templates_json_path,
    fetch_and_init_templates,
    is_templates_dirty,
    mark_templates_synced,
)
from src.config import get_device_data_dir
from src.maintenance import run_maintenance
from src.models import Device
from src.constants import (
    SUSPENDED_PNG_PATH,
    CMD_RESTART_XOCHITL,
    REMOTE_CUSTOM_TEMPLATES_DIR,
    REMOTE_TEMPLATES_DIR,
    REMOTE_TEMPLATES_JSON,
)

from src.ui_adapter import UIAdapter as _UIAdapter

def _normalise_filename(filename: str, ext: str = ".png") -> str:
    """Sanitise a filename and ensure it ends with the specified extension."""
    filename = filename.replace(" ", "_")
    if not filename.endswith(ext):
        filename = os.path.splitext(filename)[0] + ext
    return filename


def _send_suspended_png(device, img_data: bytes, img_name: str, selected_name: str, add_log) -> bool:
    """Upload *img_data* as suspended.png and restart xochitl. Returns True on success."""
    success, msg = upload_file_ssh(device.ip, device.password or "", img_data, SUSPENDED_PNG_PATH)
    if success:
        run_ssh_cmd(device.ip, device.password or "", [CMD_RESTART_XOCHITL])
        add_log(f"Sent {img_name} to '{selected_name}'")
        return True
    add_log(f"Error sending {img_name} to '{selected_name}': {msg}")
    return False


def _render_image_card(img_name, selected_name, device, config, save_config, add_log):
    """Render one image card: name/rename button, thumbnail, and action controls."""
    img_data = load_device_image(selected_name, img_name)
    star_icon = ":material/star:" if device.is_preferred(img_name) else None

    # ── name / inline rename ──────────────────────────────────────────────────
    if st.session_state.get("img_renaming") == img_name:
        def do_rename(_old=img_name):
            raw = st.session_state.get(f"rename_input_{_old}", "").strip()
            new_name = _normalise_filename(raw) if raw else None
            if new_name and new_name != _old:
                rename_device_image(selected_name, _old, new_name)
                if device.is_preferred(_old):
                    device.set_preferred(new_name)
                    config["devices"][selected_name] = device.to_dict()
                    save_config(config)
                    add_log(f"Preferred image renamed '{_old}' \u2192 '{new_name}' for '{selected_name}'")
                add_log(f"Renamed image '{_old}' to '{new_name}' for '{selected_name}'")
            st.session_state["img_renaming"] = None

        with st.form(key=f"img_rename_form_{img_name}", border=False):
            col_in, col_btn = st.columns([3, 1], vertical_alignment="center", gap="xxsmall")
            with col_in:
                st.text_input(
                    "Renommer l'image",
                    value="",
                    placeholder=os.path.splitext(img_name)[0],
                    key=f"rename_input_{img_name}",
                    label_visibility="collapsed",
                )
            with col_btn:
                st.form_submit_button(
                    ":material/check:",
                    on_click=do_rename,
                    width="stretch",
                )
    else:
        bare = os.path.splitext(img_name)[0]
        display_name = bare if len(bare) <= 13 else bare[:10] + "..."
        if st.button(
            f"**{display_name}**",
            key=f"name_{img_name}",
            help="Cliquez pour renommer",
            icon=star_icon,
            type="tertiary",
            width="stretch",
        ):
            st.session_state["img_renaming"] = img_name
            st.rerun()

    st.image(img_data, width="stretch")

    # Deletion confirmation
    if st.session_state.get("img_pending_delete") == img_name:
        confirm(
            "Confirmer la suppression",
            f"Confirmez-vous la suppression de {img_name} ?",
            key="confirm_del_img",
        )
        result = st.session_state.get("confirm_del_img")
        if result is True:
            delete_device_image(selected_name, img_name)
            if device.is_preferred(img_name):
                device.set_preferred(None)
                config["devices"][selected_name] = device.to_dict()
                save_config(config)
                add_log(f"Preferred image removed for '{selected_name}' because {img_name} was deleted")
            add_log(f"Deleted {img_name} from '{selected_name}'")
            st.session_state.pop("confirm_del_img", None)
            st.session_state["img_pending_delete"] = None
            st.rerun()
        elif result is False:
            st.session_state.pop("confirm_del_img", None)
            st.session_state["img_pending_delete"] = None
            st.rerun()

    # Segmented control
    action_key = f"action_{img_name}"
    option_map = {0: ":material/cloud_upload:", 1: ":material/star:", 2: ":material/delete:"}

    def on_action(_img_name=img_name, _action_key=action_key, _img_data=img_data):
        selection = st.session_state.get(_action_key)
        if selection is None:
            return
        try:
            if selection == 0:
                if _send_suspended_png(device, _img_data, _img_name, selected_name, add_log):
                    st.toast(f"{_img_name} envoyée à {selected_name} !", icon=":material/task_alt:")
            elif selection == 1:
                if device.is_preferred(_img_name):
                    device.set_preferred(None)
                    add_log(f"Preferred image removed for '{selected_name}'")
                else:
                    device.set_preferred(_img_name)
                    add_log(f"Preferred image set: {_img_name} for '{selected_name}'")
                config["devices"][selected_name] = device.to_dict()
                save_config(config)
            elif selection == 2:
                st.session_state["img_pending_delete"] = _img_name
        finally:
            st.session_state[_action_key] = None

    st.segmented_control(
        "Actions",
        options=list(option_map.keys()),
        format_func=lambda o: option_map[o],
        key=action_key,
        selection_mode="single",
        label_visibility="hidden",
        on_change=on_action,
    )


def _render_upload_section(selected_name, device, width, height, config, save_config, add_log):
    """Render the 'add an image' column: file uploader with save / send buttons."""
    st.subheader("Ajouter une image", divider="rainbow")
    uploaded_file = st.file_uploader(
        f"Glisser une image ici (sera convertie en PNG {width}x{height})",
        type=["png", "jpg", "jpeg"],
    )
    if not uploaded_file:
        return

    col_save, col_send = st.columns(2)
    with col_save:
        if st.button("Sauvegarder", key=f"ui_save_uploaded_{selected_name}", icon=":material/save:", help="Sauvegarder l'image localement"):
            img_data = process_image(uploaded_file, width, height)
            filename = _normalise_filename(uploaded_file.name)
            save_device_image(selected_name, img_data, filename)
            add_log(f"Image uploaded and saved: {filename} for '{selected_name}'")
            st.toast(f"Image sauvegardée : {filename}", icon=":material/task_alt:")
            st.rerun()

    with col_send:
        if st.button(f"Envoyer sur {selected_name}", key=f"ui_send_uploaded_{selected_name}", icon=":material/cloud_upload:", help=f"Envoyer l'image sur {selected_name} et la sauvegarder localement"):
            img_data = process_image(uploaded_file, width, height)
            filename = _normalise_filename(uploaded_file.name)
            save_device_image(selected_name, img_data, filename)
            if _send_suspended_png(device, img_data, filename, selected_name, add_log):
                st.toast(f"{filename} envoyée et sauvegardée !", icon=":material/task_alt:")
                st.rerun()
            else:
                st.toast("Erreur lors de l'envoi", icon=":material/error:")


# ---------------------------------------------------------------------------
# Templates tab
# ---------------------------------------------------------------------------


@st.dialog("Modifier les catégories")
def _show_category_dialog(selected_name: str, tpl_name: str, add_log) -> None:
    """Modal dialog for editing the categories of a template."""
    entry = get_template_entry(selected_name, tpl_name)
    current_cats = entry.get("categories", []) if entry else []
    all_cats = get_all_categories(selected_name)

    new_sel = st.multiselect(
        "Catégories existantes",
        options=sorted(set(all_cats) | set(current_cats)),
        default=current_cats,
        key=f"dialog_cats_select_{tpl_name}",
    )
    extra = st.text_input(
        "Nouvelles catégories (séparées par virgule)",
        key=f"dialog_cats_extra_{tpl_name}",
        placeholder="NouvelleCategorie, ...",
    )

    col_ok, col_cancel = st.columns(2)
    with col_ok:
        if st.button("Valider", key=f"dialog_cats_ok_{tpl_name}", type="primary", width="stretch"):
            new_cats = list(new_sel)
            if extra:
                new_cats += [c.strip() for c in extra.split(",") if c.strip()]
            update_template_categories(selected_name, tpl_name, new_cats)
            add_log(f"Catégories mises à jour pour '{tpl_name}' ({selected_name})")
            st.rerun()
    with col_cancel:
        if st.button("Annuler", key=f"dialog_cats_cancel_{tpl_name}", width="stretch"):
            st.rerun()


def _render_template_card(tpl_name, selected_name, device, add_log):
    """Render one template card: name/rename, SVG preview, categories, upload & delete actions."""
    tpl_path = os.path.join(get_device_templates_dir(selected_name), tpl_name)
    renaming = st.session_state.get("tpl_renaming") == tpl_name

    # ── name / inline rename ──────────────────────────────────────────────
    if renaming:
        def do_rename(_old=tpl_name):
            raw = st.session_state.get(f"tpl_rename_input_{_old}", "").strip()
            new_name = _normalise_filename(raw, ext=".svg") if raw else None
            if new_name and new_name != _old:
                rename_device_template(selected_name, _old, new_name)
                rename_template_entry(selected_name, _old, new_name)
                add_log(f"Renamed template '{_old}' \u2192 '{new_name}' for '{selected_name}'")
            st.session_state["tpl_renaming"] = None

        with st.form(key=f"tpl_rename_form_{tpl_name}", border=False):
            col_in, col_btn = st.columns([3, 1], vertical_alignment="center", gap="xxsmall")
            with col_in:
                st.text_input(
                    "Renommer le template",
                    value="",
                    placeholder=os.path.splitext(tpl_name)[0],
                    key=f"tpl_rename_input_{tpl_name}",
                    label_visibility="collapsed",
                )
            with col_btn:
                st.form_submit_button(
                    ":material/check:",
                    on_click=do_rename,
                    width="stretch",
                )
    else:
        bare = os.path.splitext(tpl_name)[0]
        display_name = bare if len(bare) <= 20 else bare[:17] + "..."
        if st.button(
            f"**{display_name}**",
            key=f"tpl_name_{tpl_name}",
            help="Cliquez pour renommer",
            type="tertiary",
            width="stretch",
        ):
            st.session_state["tpl_renaming"] = tpl_name
            st.rerun()

    # ── SVG preview ───────────────────────────────────────────────────────
    st.image(tpl_path, width="stretch")

    # ── categories button → modal ─────────────────────────────────────────
    entry = get_template_entry(selected_name, tpl_name)
    current_cats = entry.get("categories", []) if entry else []
    cats_str = " \u00b7 ".join(current_cats) if current_cats else "\u2014"
    if st.button(
        cats_str,
        key=f"tpl_cats_btn_{tpl_name}",
        type="tertiary",
        help="Modifier les cat\u00e9gories",
        width="stretch",
    ):
        _show_category_dialog(selected_name, tpl_name, add_log)

    # Local delete confirmation
    if st.session_state.get("tpl_pending_delete_local") == tpl_name:
        confirm(
            "Supprimer localement",
            f"Supprimer {tpl_name} localement ?",
            key="confirm_del_tpl_local",
        )
        result = st.session_state.get("confirm_del_tpl_local")
        if result is True:
            delete_device_template(selected_name, tpl_name)
            remove_template_entry(selected_name, tpl_name)
            add_log(f"Template {tpl_name} supprim\u00e9 localement de '{selected_name}'")
            st.session_state.pop("confirm_del_tpl_local", None)
            st.session_state["tpl_pending_delete_local"] = None
            st.rerun()
        elif result is False:
            st.session_state.pop("confirm_del_tpl_local", None)
            st.session_state["tpl_pending_delete_local"] = None
            st.rerun()
        return

    # ── delete button ─────────────────────────────────────────────────────
    if st.button(
        ":material/delete: Supprimer",
        key=f"tpl_del_{tpl_name}",
        help="Supprimer ce template localement",
        type="tertiary",
        width="stretch",
    ):
        st.session_state["tpl_pending_delete_local"] = tpl_name
        st.rerun()


def _render_template_upload_section(selected_name, add_log):
    """Section: upload a local SVG file as a new template."""
    st.subheader("Ajouter un template", divider="rainbow")
    # A generation counter is used to reset all form widgets after a successful
    # save, avoiding stale values in the uploader / multiselect / text_input.
    gen = st.session_state.get(f"tpl_upload_gen_{selected_name}", 0)

    # Show pending toast from the previous run (st.toast before st.rerun is not visible).
    pending_toast = st.session_state.pop(f"tpl_saved_toast_{selected_name}", None)
    if pending_toast:
        st.toast(pending_toast, icon=":material/task_alt:")

    uploaded_files = st.file_uploader(
        "Glisser un ou plusieurs fichiers SVG ici",
        type=["svg"],
        accept_multiple_files=True,
        key=f"tpl_uploader_{selected_name}_{gen}",
    )
    if not uploaded_files:
        return

    all_cats = get_all_categories(selected_name)
    sel_cats = st.multiselect(
        "Catégories existantes",
        options=all_cats,
        key=f"tpl_new_cats_{selected_name}_{gen}",
    )
    extra_cats_input = st.text_input(
        "Nouvelles catégories (séparées par virgule)",
        key=f"tpl_new_extra_cats_{selected_name}_{gen}",
        placeholder="Color, Perso, ...",
    )

    if st.button(
        f"Sauvegarder ({len(uploaded_files)} fichier(s))",
        key=f"ui_tpl_save_{selected_name}_{gen}",
        icon=":material/save:",
        help="Sauvegarder les templates localement",
        width="stretch",
    ):
        extra_list = [c.strip() for c in extra_cats_input.split(",") if c.strip()] if extra_cats_input else []
        categories = list(sel_cats) + extra_list
        saved = []
        for uf in uploaded_files:
            content = uf.read()
            filename = _normalise_filename(uf.name, ext=".svg")
            save_device_template(selected_name, content, filename)
            add_template_entry(selected_name, filename, categories)
            add_log(f"{filename} template saved for '{selected_name}'")
            saved.append(filename)
        if len(saved) == 1:
            st.session_state[f"tpl_saved_toast_{selected_name}"] = f"Template saved\u00a0: {saved[0]}"
        else:
            st.session_state[f"tpl_saved_toast_{selected_name}"] = f"{len(saved)} templates saved!"
        # Bump the generation to reset the form on the next render.
        st.session_state[f"tpl_upload_gen_{selected_name}"] = gen + 1
        st.rerun()


def _sync_templates_to_tablet(selected_name: str, device, add_log) -> bool:
    """Push all local SVG templates and templates.json to the tablet, restart xochitl.

    Returns True on success, False if any step fails.
    """
    ip = device.ip
    pw = device.password or ""

    ok, msg = ensure_remote_template_dirs(ip, pw, REMOTE_CUSTOM_TEMPLATES_DIR, REMOTE_TEMPLATES_DIR)
    if not ok:
        add_log(f"Sync templates — ensure dirs: {msg}")
        return False

    device_templates_dir = get_device_templates_dir(selected_name)
    sent = upload_template_svgs(ip, pw, [device_templates_dir], REMOTE_CUSTOM_TEMPLATES_DIR)
    if sent:
        try:
            run_ssh_cmd(
                ip, pw,
                [
                    f"for file in {REMOTE_CUSTOM_TEMPLATES_DIR}/*.svg; do "
                    f"[ -f \"$file\" ] || continue; "
                    f"ln -sf \"$file\" \"{REMOTE_TEMPLATES_DIR}/\"$(basename \"$file\"); "
                    "done"
                ],
            )
        except Exception as e:
            add_log(f"Sync templates — symlinks: {e}")
            return False

    local_json_path = get_device_templates_json_path(selected_name)
    if os.path.exists(local_json_path):
        with open(local_json_path, "rb") as f:
            json_content = f.read()
        ok, msg = upload_file_ssh(ip, pw, json_content, REMOTE_TEMPLATES_JSON)
        if not ok:
            add_log(f"Sync templates — templates.json upload: {msg}")
            return False

    try:
        run_ssh_cmd(ip, pw, [CMD_RESTART_XOCHITL])
    except Exception as e:
        add_log(f"Sync templates — restart xochitl: {e}")
        return False

    mark_templates_synced(selected_name)
    add_log(
        f"Templates synced on '{selected_name}' "
        f"({sent} SVG(s) uploaded, templates.json {'uploaded' if os.path.exists(local_json_path) else 'not found locally'})"
    )
    return True


def _render_tab_templates(selected_name, device, add_log):
    """Full templates management tab."""

    # ── Guard: require templates.backup.json before doing anything ────────────
    backup_path = get_device_templates_backup_path(selected_name)
    if not os.path.exists(backup_path):
        st.warning(
            "Aucun fichier de référence (`templates.backup.json`) n'a été trouvé. "
            "Veuillez d'abord récupérer le fichier `templates.json` depuis la tablette. "
            "Il servira de base pour composer la liste locale des templates.",
            icon=":material/backup:",
        )
        if st.button(
            "Récupérer les templates depuis la tablette",
            key=f"tpl_fetch_backup_{selected_name}",
            type="primary",
            icon=":material/download:",
        ):
            with st.spinner("Téléchargement de templates.json depuis la tablette…"):
                ok, msg = fetch_and_init_templates(
                    device.ip, device.password or "", selected_name
                )
            if ok:
                add_log(f"Templates initialisés pour '{selected_name}' : {msg}")
                st.toast("Templates récupérés et initialisés !", icon=":material/task_alt:")
                st.rerun()
            else:
                add_log(f"Erreur init templates pour '{selected_name}' : {msg}")
                st.error(f"Erreur : {msg}", icon=":material/error:")
        return

    stored_templates = list_device_templates(selected_name)

    # ── sync banner (shown only when local state diverges from last sync) ──
    if is_templates_dirty(selected_name):
        col_warn, col_btn = st.columns([3, 1], vertical_alignment="center")
        with col_warn:
            st.warning(
                "Des modifications locales ne sont pas encore synchronisées avec la tablette.",
                icon=":material/sync:",
            )
        with col_btn:
            if st.button(
                "Synchroniser",
                key=f"tpl_sync_{selected_name}",
                type="primary",
                icon=":material/sync:",
                width="stretch",
            ):
                with st.spinner("Synchronisation en cours..."):
                    ok = _sync_templates_to_tablet(selected_name, device, add_log)
                if ok:
                    st.toast("Templates synchronisés !", icon=":material/task_alt:")
                else:
                    st.toast("Erreur lors de la synchronisation", icon=":material/error:")
                st.rerun()

    if stored_templates:
        col_title, col_sort = st.columns([2, 2], vertical_alignment="center")
        with col_title:
            st.subheader("Templates enregistrés", divider="rainbow")
        with col_sort:
            sort_by = st.segmented_control(
                "Trier par",
                options=["Date", "A → Z", "Catégories"],
                default="Date",
                key=f"tpl_sort_{selected_name}",
            )

        if sort_by == "A → Z":
            stored_templates = sorted(stored_templates, key=lambda f: f.lower())
        elif sort_by == "Catégories":
            def _cat_key(f):
                entry = get_template_entry(selected_name, f)
                cats = entry.get("categories", []) if entry else []
                return (cats[0].lower() if cats else "\xff", f.lower())
            stored_templates = sorted(stored_templates, key=_cat_key)
        # "Date" keeps the default mtime-desc order from list_device_templates

        ncols = 4
        for row_start in range(0, len(stored_templates), ncols):
            row_items = stored_templates[row_start:row_start + ncols]
            cols = st.columns(ncols, gap="medium")
            for col_idx, tpl_name in enumerate(row_items):
                with cols[col_idx]:
                    _render_template_card(tpl_name, selected_name, device, add_log)
            if row_start + ncols < len(stored_templates):
                st.divider()

    else:
        st.info("Aucun template trouvé pour cet appareil.")

    _render_template_upload_section(selected_name, add_log)


def render_logs_page():
    st.title(":material/description: Logs de session")
    if not st.session_state.get('logs'):
        st.info("Aucun log pour cette session.")
    else:
        for entry in reversed(st.session_state['logs']):
            st.text(entry)
        if st.button("Effacer les logs de cette session", key="ui_clear_logs", icon=":material/delete:", help="Efface les logs stockés dans la session en cours"):
            st.session_state.clear_logs = None
            confirm("Effacer les logs", "Effacer les logs de cette session ?", key="clear_logs")
        if st.session_state.get("clear_logs") is True:
            st.session_state['logs'] = []
            st.success("Logs effacés.", icon=":material/task_alt:")
            del st.session_state.clear_logs
            st.rerun()


def render_config_page(config, save_config, add_log, resolve_device_type, DEFAULT_DEVICE_TYPE):
    st.title(":material/settings: Configuration des appareils")

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
            "carousel": True
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
            list(resolve_device_type.__self__ if hasattr(resolve_device_type, '__self__') else [] ) or [device_config.get("device_type", DEFAULT_DEVICE_TYPE)],
            index=0,
        )
        templates = st.checkbox("Activer les templates", value=device_config.get("templates", True))
        carousel = st.checkbox("Désactiver le carousel", value=device_config.get("carousel", True))

    st.info("💡 Pour trouver l’adresse IP et le mot de passe root de votre reMarkable, activez le mode développeur si nécessaire, allez dans Paramètres > Aide > À propos > Copyrights et licences, puis faites défiler la colonne de droite si nécessaire.")

    col_save, col_delete = st.columns([3, 1])
    with col_save:
        if st.button("Sauvegarder", key=f"ui_config_save_{device_name}", width='stretch', icon=":material/save:", help="Enregistrer la configuration de l'appareil"):
            if is_new and not device_name:
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
        if not is_new and st.button("Supprimer", key=f"ui_config_delete_{device_name}", type="primary", width='stretch', icon=":material/delete:", help="Supprimer cet appareil et ses images locales"):
            st.session_state["pending_delete_device"] = device_name
            st.rerun()

    if st.session_state.get("pending_delete_device") == device_name:
        confirm(
            "Confirmer la suppression",
            f"Confirmez-vous la suppression de l'appareil '{device_name}' ? Cette action supprimera aussi ses images locales.",
            key=f"del_device_{device_name}",
        )
        if st.session_state.get(f"del_device_{device_name}") is True:
            import shutil
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


_TABLET_QUERY_PARAM = "tablet"



def render_main_page(config, save_config, add_log, resolve_device_type, BASE_DIR):
    st.title("reMarkable Manager")

    DEVICES = config.get("devices", {})
    if not DEVICES:
        st.warning("Aucun appareil configuré. Ajoutez-en un dans Configuration.")
        return

    device_names = list(DEVICES.keys())

    # Restore selection from URL query param on fresh page loads.
    # st.query_params is set into the URL so it survives browser reloads.
    if "selected_tablet_select" not in st.session_state:
        saved = st.query_params.get(_TABLET_QUERY_PARAM)
        if saved and saved in device_names:
            st.session_state["selected_tablet_select"] = saved

    col1, col2 = st.columns([2, 1], vertical_alignment="bottom")
    with col1:
        selected_name = st.selectbox(
            "Choisir la tablette",
            device_names,
            key="selected_tablet_select",
        )
        # Persist selection in the URL so reloads restore the right tablet.
        st.query_params[_TABLET_QUERY_PARAM] = selected_name
        device_dict = DEVICES[selected_name]
        device = Device.from_dict(selected_name, device_dict)
        width, height = (1620, 2160)  # fallback; caller can pass constants if needed

    with col2:
        if st.button("Tester la connectivité", key=f"ui_test_ssh_{selected_name}", icon=":material/wifi:", width='stretch', help="Vérifier la connexion SSH vers la tablette"):
            ok, err = test_ssh_connection(device.ip, device.password or '')
            if ok:
                st.toast("Connexion SSH OK", icon=":material/task_alt:")
                add_log(f"SSH connection successful to '{selected_name}'")
            else:
                st.toast(f"Connexion SSH impossible : {err}", icon=":material/error:")
                add_log(f"SSH connection failed to '{selected_name}': {err}")

    st.space()

    tab_images, tab_templates, tab_maintenance = st.tabs([
        ":material/image: Images",
        ":material/description: Templates",
        ":material/build: Maintenance",
    ])

    with tab_images:
        _render_tab_images(selected_name, device, width, height, config, save_config, add_log)

    with tab_templates:
        _render_tab_templates(selected_name, device, add_log)

    with tab_maintenance:
        _render_tab_maintenance(selected_name, device, add_log, BASE_DIR)


def _render_tab_images(selected_name, device, width, height, config, save_config, add_log):
    stored_images = list_device_images(selected_name)

    if stored_images:
        with st.expander("Aide — Actions des images (cliquer pour développer)", expanded=False):
            st.markdown(":material/cloud_upload: **Envoyer** — Mettre l'image comme écran de veille sur la tablette  ")
            st.markdown(":material/star: **Favori** — Définir ou supprimer l'image préférée  ")
            st.markdown(":material/delete: **Supprimer** — Effacer l'image localement  ")

        cols = st.columns(4, gap="medium")
        for idx, img_name in enumerate(stored_images):
            with cols[idx % 4]:
                _render_image_card(img_name, selected_name, device, config, save_config, add_log)

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Récupérer l'image actuelle", divider="rainbow")
        if st.button("Importer depuis la tablette", key=f"ui_import_from_tablet_{selected_name}", icon=":material/download:", width='stretch', help="Télécharger l'image actuelle de l'écran de veille depuis la tablette"):
            try:
                img_data = download_file_ssh(device.ip, device.password or '', SUSPENDED_PNG_PATH)
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
        _render_upload_section(selected_name, device, width, height, config, save_config, add_log)


def _render_tab_maintenance(selected_name, device, add_log, BASE_DIR):
    imgs_available = list_device_images(selected_name)
    has_images = bool(imgs_available)
    image = None
    steps = []
    with st.expander("Ce que le script va faire : (cliquer pour développer)", expanded=False):
        st.markdown("**Ce script va :**")
        st.markdown("- Vérifier que le système de fichiers est writable et le remonter en lecture-écriture si nécessaire")
        if device.preferred_image:
            image = device.preferred_image
            st.markdown(f"- Téléverser l'image préférée (`{image}`) comme `suspended.png` sur la tablette")
        elif has_images:
            image = random.choice(imgs_available)
            st.markdown(f"- Téléverser `{image}` de la bibliothèque locale comme `suspended.png` sur la tablette (aucune image préférée définie)")
        if image:
            steps.append(f"Upload de l'image de veille ({image})")
        if getattr(device, 'templates', False):
            st.markdown("- Assurer l'existence des dossiers de templates custom sur la tablette")
            st.markdown("- Uploader les fichiers SVG de templates locaux vers la tablette et créer les liens nécessaires")
            st.markdown("- Sauvegarder le `templates.json` distant, le comparer avec une version locale si elle existe, et remplacer le distant par la version locale si elles diffèrent")
            steps.append("Ajout des templates personnalisés")
        if getattr(device, 'carousel', False):
            st.markdown("- Désactiver le carrousel en déplaçant les illustrations actuelles dans un dossier de backup")
            steps.append("Désactivation du carrousel")
        st.markdown("- Redémarrer le service `xochitl` pour appliquer les changements")
        steps.append("Redémarrage de xochitl")

    _, col, _ = st.columns([1, 3, 1])
    with col:
        if st.button("Lancer le script complet", key=f"ui_launch_maintenance_{selected_name}", icon=":material/autorenew:", help="Exécuter les actions de maintenance post-mise à jour", type="primary", width='stretch'):
            with st.status("Démarrage de la maintenance...") as status:
                progress = st.progress(0)
                ui = _UIAdapter(status, progress, add_log)

                result = run_maintenance(selected_name, device, steps, image, ui)

            if result.get("ok"):
                ui.step("Maintenance terminée")
                ui.progress(100)
                ui.toast("Maintenance terminée")
            else:
                ui.step("Maintenance terminée (avec erreurs)")
                ui.toast("Maintenance terminée (avec erreurs)")
                for e in result.get('errors', []):
                    add_log(f"Maintenance error: {e}")
