"""Template library page."""

import os
from contextlib import suppress

import streamlit as st

import src.dialog as _dialog
import src.ssh as _ssh
from src.constants import (
    CMD_RESTART_XOCHITL,
    GRID_COLUMNS,
    REMOTE_CUSTOM_TEMPLATES_DIR,
    REMOTE_TEMPLATES_DIR,
    REMOTE_TEMPLATES_JSON,
)
from src.icon_font import (
    get_icon_font_path,
    render_icon_grid_html,
    render_icon_link_html,
    render_icon_preview_html,
)
from src.models import Device
from src.templates import (
    add_template_entry,
    delete_device_template,
    ensure_remote_template_dirs,
    fetch_and_init_templates,
    get_all_categories,
    get_device_templates_backup_path,
    get_device_templates_dir,
    get_device_templates_json_path,
    get_template_entry,
    is_templates_dirty,
    list_device_templates,
    mark_templates_synced,
    remove_template_entry,
    rename_device_template,
    rename_template_entry,
    save_device_template,
    update_template_categories,
    update_template_icon_code,
    upload_template_svgs,
    upload_template_to_tablet,
)
from src.ui_common import deferred_toast, normalise_filename, rainbow_divider, require_device

# ── Sync helper ───────────────────────────────────────────────────────────────


def _sync_templates_to_tablet(selected_name: str, device, add_log) -> bool:
    """Push all local SVG templates and templates.json to the tablet, restart xochitl."""
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
            _ssh.run_ssh_cmd(
                ip,
                pw,
                [
                    f"for file in {REMOTE_CUSTOM_TEMPLATES_DIR}/*.svg; do "
                    f'[ -f "$file" ] || continue; '
                    f'ln -sf "$file" "{REMOTE_TEMPLATES_DIR}/"$(basename "$file"); '
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
        ok, msg = _ssh.upload_file_ssh(ip, pw, json_content, REMOTE_TEMPLATES_JSON)
        if not ok:
            add_log(f"Sync templates — templates.json upload: {msg}")
            return False

    try:
        _ssh.run_ssh_cmd(ip, pw, [CMD_RESTART_XOCHITL])
    except Exception as e:
        add_log(f"Sync templates — restart xochitl: {e}")
        return False

    mark_templates_synced(selected_name)
    add_log(
        f"Templates synced on '{selected_name}' "
        f"({sent} SVG(s) uploaded, templates.json {'uploaded' if os.path.exists(local_json_path) else 'not found locally'})"
    )
    return True


# ── Category dialog ───────────────────────────────────────────────────────────


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


# ── Icon dialog ─────────────────────────────────────────────────────────────────


@st.dialog("Modifier l'icône", width="large")
def _show_icon_dialog(selected_name: str, tpl_name: str, add_log) -> None:
    """Modal dialog for changing the icon of a template.

    If the icomoon font is available a full browsable grid is shown.  Clicking
    any icon navigates the page to ``?icon=HEX&tpl_icon_for=STEM`` which the
    page-level handler picks up on the next run to apply the change.
    The dialog also exposes a direct hex-code text input + OK button as an
    alternative (no navigation required).
    """
    entry = get_template_entry(selected_name, tpl_name)
    current_code = entry.get("iconCode", "\ue9fe") if entry else "\ue9fe"
    current_hex = f"{ord(current_code):04X}" if current_code else "E9FE"
    stem = os.path.splitext(tpl_name)[0]

    font_available = os.path.exists(get_icon_font_path())

    st.caption("Entrez directement un code hexadécimal ou cliquez sur une icône ci-dessous :")

    new_hex_input = st.text_input(
        "Code hex (ex\u00a0: E9FE)",
        value=current_hex,
        max_chars=5,
        key=f"icon_hex_input_{tpl_name}",
    )
    col_ok, col_cancel = st.columns(2)
    with col_ok:
        if st.button("Valider", key=f"icon_ok_{tpl_name}", type="primary", width="stretch"):
            try:
                cp = int(new_hex_input.strip(), 16)
                icon_code = chr(cp)
            except ValueError:
                st.error("Code hexadécimal invalide.")
                return
            update_template_icon_code(selected_name, tpl_name, icon_code)
            add_log(
                f"Icône mise à jour pour '{tpl_name}' ({selected_name}) : \\u{new_hex_input.strip().upper()}"
            )
            st.rerun()
    with col_cancel:
        if st.button("Annuler", key=f"icon_cancel_{tpl_name}", width="stretch"):
            st.rerun()

    if font_available:
        st.caption("Cliquez sur une icône pour l’appliquer directement\u00a0:")
        st.html(
            render_icon_grid_html(
                selected_cp=ord(current_code) if current_code else None,
                href_extra=f"&tpl_icon_for={stem}",
            )
        )
    else:
        st.info(
            "La police icomoon n'est pas encore extraite. "
            "Utilisez la page \u00ab\u202fPolice d'icônes\u202f\u00bb pour l'extraire.",
            icon=":material/info:",
        )


# ── Reload dialog ────────────────────────────────────────────────────────────


@st.dialog("Recharger le template")
def _show_reload_dialog(tpl_name: str, selected_name: str, device, add_log) -> None:
    """Modal dialog to replace a template SVG locally and push it to the tablet."""
    reload_file = st.file_uploader(
        "Nouveau fichier SVG",
        type=["svg"],
        key=f"tpl_reload_file_{tpl_name}",
    )
    col_save, col_cancel = st.columns(2, gap="xxsmall")
    with col_save:
        if st.button(
            "Sauvegarder",
            key=f"tpl_reload_save_{tpl_name}",
            type="primary",
            disabled=reload_file is None,
            width="stretch",
        ):
            content = reload_file.read()
            save_device_template(selected_name, content, tpl_name)
            add_log(f"Template {tpl_name} recharg\u00e9 localement pour '{selected_name}'")
            ok, msg = upload_template_to_tablet(
                device.ip, device.password or "", selected_name, tpl_name
            )
            if ok:
                deferred_toast(f"{tpl_name} mis à jour sur la tablette !", ":material/task_alt:")
                add_log(f"Template {tpl_name} sent to '{selected_name}'")
            else:
                add_log(f"Failed to send {tpl_name} to '{selected_name}': {msg}")
                deferred_toast(f"Erreur lors de l'envoi de {tpl_name}", ":material/error:")
            st.session_state["tpl_reloading"] = None
            st.rerun()
    with col_cancel:
        if st.button(
            "Annuler",
            key=f"tpl_reload_cancel_{tpl_name}",
            width="stretch",
        ):
            st.session_state["tpl_reloading"] = None
            st.rerun()


# ── Template card ─────────────────────────────────────────────────────────────


def _render_template_card(tpl_name, selected_name, device, add_log):
    """Render one template card: name/rename, SVG preview, categories, upload & delete actions."""
    tpl_path = os.path.join(get_device_templates_dir(selected_name), tpl_name)
    renaming = st.session_state.get("tpl_renaming") == tpl_name
    stem = os.path.splitext(tpl_name)[0]
    entry = get_template_entry(selected_name, tpl_name)
    current_icon_code = entry.get("iconCode", "\ue9fe") if entry else "\ue9fe"
    # ── name / inline rename ──────────────────────────────────────────────
    if renaming:

        def do_rename(_old=tpl_name):
            raw = st.session_state.get(f"tpl_rename_input_{_old}", "").strip()
            new_name = normalise_filename(raw, ext=".svg") if raw else None
            if new_name and new_name != _old:
                if new_name in list_device_templates(selected_name):
                    st.session_state["tpl_pending_rename"] = (_old, new_name)
                    return
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
        col_icon, col_name = st.columns([0.5, 5], vertical_alignment="center")
        with col_icon:
            _icon_link = render_icon_link_html(current_icon_code, f"?edit_icon={stem}")
            if _icon_link:
                st.html(_icon_link)
            else:
                if st.button(
                    "",
                    key=f"tpl_icon_btn_fallback_{tpl_name}",
                    icon=":material/palette:",
                    help="Modifier l'icône",
                    type="tertiary",
                ):
                    _show_icon_dialog(selected_name, tpl_name, add_log)
        with col_name:
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

    # Rename overwrite confirmation
    pending_rename = st.session_state.get("tpl_pending_rename")
    if pending_rename and pending_rename[0] == tpl_name:
        _old_r, _new_r = pending_rename
        _dialog.confirm(
            "Confirmer le remplacement",
            f"'{_new_r}' existe déjà. Voulez-vous remplacer ce template ?",
            key="confirm_rename_tpl",
        )
        result = st.session_state.get("confirm_rename_tpl")
        if result is True:
            rename_device_template(selected_name, _old_r, _new_r)
            rename_template_entry(selected_name, _old_r, _new_r)
            add_log(f"Renamed template '{_old_r}' \u2192 '{_new_r}' for '{selected_name}'")
            st.session_state.pop("confirm_rename_tpl", None)
            st.session_state["tpl_pending_rename"] = None
            st.session_state["tpl_renaming"] = None
            st.rerun()
        elif result is False:
            st.session_state.pop("confirm_rename_tpl", None)
            st.session_state["tpl_pending_rename"] = None
            st.session_state["tpl_renaming"] = None
            st.rerun()

    # ── categories button → modal ─────────────────────────────────────────
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
        _dialog.confirm(
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

    # ── segmented control (reload + delete) ──────────────────────────────
    action_key = f"tpl_action_{tpl_name}"
    option_map = {0: ":material/upload_file:", 1: ":material/delete:"}

    def on_tpl_action(_tpl=tpl_name, _akey=action_key):
        sel = st.session_state.get(_akey)
        if sel == 1:
            st.session_state["tpl_pending_delete_local"] = _tpl
        elif sel == 0:
            st.session_state["tpl_reloading"] = _tpl
        st.session_state[_akey] = None

    st.segmented_control(
        "Actions",
        options=list(option_map.keys()),
        format_func=lambda o: option_map[o],
        key=action_key,
        selection_mode="single",
        label_visibility="collapsed",
        on_change=on_tpl_action,
        width="stretch",
    )
    if st.session_state.get("tpl_reloading") == tpl_name:
        _show_reload_dialog(tpl_name, selected_name, device, add_log)


def _render_template_upload_section(selected_name, add_log):
    """Section: upload a local SVG file as a new template."""
    st.subheader("Ajouter un template", divider="rainbow")
    gen = st.session_state.get(f"tpl_upload_gen_{selected_name}", 0)

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

    # ── Icon picker ─────────────────────────────────────────────────────────────────
    icon_hex_input = st.text_input(
        "Code d'icône (hex)",
        value="E9FE",
        max_chars=5,
        key=f"tpl_new_icon_{selected_name}_{gen}",
        help="Code hexadécimal de l'icône icomoon (ex\u00a0: E9FE). Parcourez les icônes ci-dessous.",
    )
    _icn_preview = ""
    with suppress(ValueError, OverflowError):
        _icn_preview = render_icon_preview_html(chr(int(icon_hex_input.strip(), 16)))
    if _icn_preview:
        st.html(_icn_preview)
    _grid_html = render_icon_grid_html(
        selected_cp=int(icon_hex_input.strip(), 16) if icon_hex_input.strip() else None,
        clickable=False,
    )
    if _grid_html:
        with st.expander("Parcourir les icônes", icon=":material/grid_view:"):
            st.html(_grid_html)

    if st.button(
        f"Sauvegarder ({len(uploaded_files)} fichier(s))",
        key=f"ui_tpl_save_{selected_name}_{gen}",
        icon=":material/save:",
        help="Sauvegarder les templates localement",
        width="stretch",
    ):
        extra_list = (
            [c.strip() for c in extra_cats_input.split(",") if c.strip()]
            if extra_cats_input
            else []
        )
        categories = list(sel_cats) + extra_list
        try:
            icon_code = chr(int(icon_hex_input.strip(), 16))
        except (ValueError, OverflowError):
            icon_code = "\ue9fe"
        saved = []
        for uf in uploaded_files:
            content = uf.read()
            filename = normalise_filename(uf.name, ext=".svg")
            save_device_template(selected_name, content, filename)
            add_template_entry(selected_name, filename, categories, icon_code)
            add_log(f"{filename} template saved for '{selected_name}'")
            saved.append(filename)
        if len(saved) == 1:
            deferred_toast(f"Template {saved[0]} sauvegardé", ":material/task_alt:")
        else:
            deferred_toast(f"{len(saved)} templates sauvegardés", ":material/task_alt:")
        st.session_state[f"tpl_upload_gen_{selected_name}"] = gen + 1
        st.rerun()


# ── Page ─────────────────────────────────────────────────────────────────────

st.title(":material/description: Templates")
rainbow_divider()

config = st.session_state.get("config", {})
add_log = st.session_state.get("add_log", lambda msg: None)
selected_name = st.session_state.get("selected_name")

DEVICES = config.get("devices", {})

require_device(DEVICES, selected_name)

device = Device.from_dict(selected_name, DEVICES[selected_name])

# ── Handle icon change from grid navigation ───────────────────────────────────────
# Clicking an icon in the dialog grid (?tpl_icon_for=STEM) navigates here with ?icon=HEX.
_tpl_icon_for = st.query_params.get("tpl_icon_for")
_icon_hex = st.query_params.get("icon")
if _tpl_icon_for and _icon_hex:
    try:
        _icon_cp = int(_icon_hex, 16)
        update_template_icon_code(selected_name, _tpl_icon_for, chr(_icon_cp))
        add_log(f"Icon updated for '{_tpl_icon_for}' ({selected_name}) : \\u{_icon_hex.upper()}")
    except ValueError:
        pass
    del st.query_params["tpl_icon_for"]
    del st.query_params["icon"]
    st.rerun()
elif st.query_params.get("edit_icon"):
    _edit_stem = st.query_params["edit_icon"]
    del st.query_params["edit_icon"]
    _show_icon_dialog(selected_name, _edit_stem + ".svg", add_log)

backup_path = get_device_templates_backup_path(selected_name)
if not os.path.exists(backup_path):
    st.warning(
        "La liste des templates de cette tablette n'a pas encore été importée. "
        "Allumez la tablette et cliquez sur le bouton ci-dessous pour démarrer.",
        icon=":material/backup:",
    )
    if st.button(
        "Importer les templates depuis la tablette",
        key=f"tpl_fetch_backup_{selected_name}",
        type="primary",
        icon=":material/download:",
    ):
        with st.spinner("Importation en cours…"):
            ok, msg = fetch_and_init_templates(device.ip, device.password or "", selected_name)
        if ok:
            add_log(f"Templates initialized for '{selected_name}' : {msg}")
            deferred_toast("Templates importés avec succès", ":material/task_alt:")
            st.rerun()
        else:
            add_log(f"Error initializing templates for '{selected_name}' : {msg}")
            st.error(f"Erreur : {msg}", icon=":material/error:")
else:
    stored_templates = list_device_templates(selected_name)

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
                    deferred_toast("Templates synchronisés !", ":material/task_alt:")
                    add_log(f"Templates synced to tablet for '{selected_name}'")
                else:
                    deferred_toast("Erreur lors de la synchronisation", ":material/error:")
                    add_log(f"Error syncing templates to tablet for '{selected_name}'")
                st.rerun()

    if stored_templates:
        col_title, col_sort = st.columns([2, 1], vertical_alignment="center")
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

        for row_start in range(0, len(stored_templates), GRID_COLUMNS):
            row_items = stored_templates[row_start : row_start + GRID_COLUMNS]
            cols = st.columns(GRID_COLUMNS, gap="medium")
            for col_idx, tpl_name in enumerate(row_items):
                with cols[col_idx]:
                    _render_template_card(tpl_name, selected_name, device, add_log)
            if row_start + GRID_COLUMNS < len(stored_templates):
                st.divider()
    else:
        st.info("Aucun template trouvé pour cet appareil.")

    _render_template_upload_section(selected_name, add_log)
