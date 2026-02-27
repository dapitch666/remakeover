"""Template library page rendering."""

import os

import streamlit as st

import src.ssh as _ssh
import src.dialog as _dialog
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
from src.ui_common import _normalise_filename, deferred_toast
from src.constants import (
    CMD_RESTART_XOCHITL,
    GRID_COLUMNS,
    REMOTE_CUSTOM_TEMPLATES_DIR,
    REMOTE_TEMPLATES_DIR,
    REMOTE_TEMPLATES_JSON,
)


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


# ── Template card ─────────────────────────────────────────────────────────────

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
            deferred_toast(f"Template saved\u00a0: {saved[0]}", ":material/task_alt:")
        else:
            deferred_toast(f"{len(saved)} templates saved!", ":material/task_alt:")
        st.session_state[f"tpl_upload_gen_{selected_name}"] = gen + 1
        st.rerun()


# ── Page entry point ──────────────────────────────────────────────────────────

def render_page(selected_name, device, add_log):
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
                ok, msg = fetch_and_init_templates(
                    device.ip, device.password or "", selected_name
                )
            if ok:
                add_log(f"Templates initialisés pour '{selected_name}' : {msg}")
                deferred_toast("Templates importés avec succès !", ":material/task_alt:")
                st.rerun()
            else:
                add_log(f"Erreur init templates pour '{selected_name}' : {msg}")
                st.error(f"Erreur : {msg}", icon=":material/error:")
        return

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
                else:
                    deferred_toast("Erreur lors de la synchronisation", ":material/error:")
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
            row_items = stored_templates[row_start:row_start + GRID_COLUMNS]
            cols = st.columns(GRID_COLUMNS, gap="medium")
            for col_idx, tpl_name in enumerate(row_items):
                with cols[col_idx]:
                    _render_template_card(tpl_name, selected_name, device, add_log)
            if row_start + GRID_COLUMNS < len(stored_templates):
                st.divider()
    else:
        st.info("Aucun template trouvé pour cet appareil.")

    _render_template_upload_section(selected_name, add_log)
