"""Template library page."""

import os

import streamlit as st

import src.dialog as _dialog
from src.constants import (
    DEFAULT_TEMPLATE_JSON,
    GRID_COLUMNS,
)
from src.i18n import _
from src.manifest_templates import load_manifest
from src.models import Device
from src.template_sync import check_sync_status, fetch_and_init_templates, sync_templates_to_tablet
from src.templates import (
    add_template_entry,
    delete_device_template,
    extract_categories_from_template_content,
    get_all_categories,
    get_all_labels,
    get_device_manifest_json_path,
    get_device_templates_dir,
    get_template_entry,
    list_device_templates,
    refresh_local_manifest,
    remove_template_entry,
    rename_device_template,
    save_device_template,
    update_template_categories,
    update_template_labels,
    upload_template_to_tablet,
)
from src.ui_common import deferred_toast, normalise_filename, rainbow_divider, require_device

# ── Category dialog ───────────────────────────────────────────────────────────


@st.dialog(_("Edit categories"))
def _show_category_dialog(selected_name: str, tpl_name: str, add_log) -> None:
    """Modal dialog for editing the categories of a template."""
    entry = get_template_entry(selected_name, tpl_name)
    current_cats = entry.get("categories", []) if entry else []
    all_cats = get_all_categories(selected_name)

    new_sel = st.multiselect(
        _("Existing categories"),
        options=sorted(set(all_cats) | set(current_cats)),
        default=current_cats,
        key=f"dialog_cats_select_{tpl_name}",
    )
    extra = st.text_input(
        _("New categories (comma-separated)"),
        key=f"dialog_cats_extra_{tpl_name}",
        placeholder="NewCategory, ...",
    )

    col_ok, col_cancel = st.columns(2)
    with col_ok:
        if st.button(
            _("Apply"),
            key=f"dialog_cats_ok_{tpl_name}",
            type="primary",
            help=_("Apply category changes"),
            width="stretch",
        ):
            new_cats = list(new_sel)
            if extra:
                new_cats += [c.strip() for c in extra.split(",") if c.strip()]
            update_template_categories(selected_name, tpl_name, new_cats)
            add_log(f"Categories updated for '{tpl_name}' ({selected_name})")
            deferred_toast(_("Categories updated"), ":material/task_alt:")
            st.rerun()
    with col_cancel:
        if st.button(
            _("Cancel"),
            key=f"dialog_cats_cancel_{tpl_name}",
            help=_("Close without saving category changes"),
            width="stretch",
        ):
            st.rerun()


# ── Labels dialog ────────────────────────────────────────────────────────────


@st.dialog(_("Edit labels"))
def _show_labels_dialog(selected_name: str, tpl_name: str, add_log) -> None:
    """Modal dialog for editing the labels of a template."""
    entry = get_template_entry(selected_name, tpl_name)
    current_labels = entry.get("labels", []) if entry else []
    all_labels = get_all_labels(selected_name)

    new_labels = st.multiselect(
        _("Labels"),
        options=sorted(set(all_labels) | set(current_labels)),
        default=current_labels,
        key=f"dialog_labels_select_{tpl_name}",
        help=_("Add custom labels to organize your template"),
    )
    extra = st.text_input(
        _("New labels (comma-separated)"),
        key=f"dialog_labels_extra_{tpl_name}",
        placeholder="work, meeting, ...",
    )

    col_ok, col_cancel = st.columns(2)
    with col_ok:
        if st.button(
            _("Apply"),
            key=f"dialog_labels_ok_{tpl_name}",
            type="primary",
            help=_("Apply label changes"),
            width="stretch",
        ):
            final_labels = list(new_labels)
            if extra:
                final_labels += [lbl.strip() for lbl in extra.split(",") if lbl.strip()]
            update_template_labels(selected_name, tpl_name, sorted(set(final_labels)))
            add_log(f"Labels updated for '{tpl_name}' ({selected_name})")
            deferred_toast(_("Labels updated"), ":material/task_alt:")
            st.rerun()
    with col_cancel:
        if st.button(
            _("Cancel"),
            key=f"dialog_labels_cancel_{tpl_name}",
            help=_("Close without saving label changes"),
            width="stretch",
        ):
            st.rerun()


# ── Reload dialog ────────────────────────────────────────────────────────────


@st.dialog(_("Reload template"))
def _show_reload_dialog(tpl_name: str, selected_name: str, device, add_log) -> None:
    """Modal dialog to replace a template file locally and push it to the tablet."""
    entry = get_template_entry(selected_name, tpl_name)
    ui_name = str(entry.get("name") or tpl_name) if entry else tpl_name
    reload_file = st.file_uploader(
        _("New .template file"),
        type=["template"],
        key=f"tpl_reload_file_{tpl_name}",
    )
    col_save, col_cancel = st.columns(2, gap="xxsmall")
    with col_save:
        if st.button(
            _("Save"),
            key=f"tpl_reload_save_{tpl_name}",
            type="primary",
            disabled=reload_file is None,
            help=_("Replace this template with the selected file"),
            width="stretch",
        ):
            assert reload_file is not None
            content = reload_file.read()
            save_device_template(selected_name, content, tpl_name)
            add_log(f"Template '{ui_name}' reloaded locally for '{selected_name}'")
            ok, msg = upload_template_to_tablet(
                device.ip, device.password or "", selected_name, tpl_name
            )
            if ok:
                deferred_toast(
                    _("{name} updated on the tablet").format(name=ui_name), ":material/task_alt:"
                )
                add_log(f"Template {ui_name} sent to '{selected_name}'")
            else:
                add_log(f"Failed to send {ui_name} to '{selected_name}': {msg}")
                deferred_toast(_("Error sending {name}").format(name=ui_name), ":material/error:")
            st.session_state["tpl_reloading"] = None
            st.rerun()
    with col_cancel:
        if st.button(
            _("Cancel"),
            key=f"tpl_reload_cancel_{tpl_name}",
            help=_("Close without reloading this template"),
            width="stretch",
        ):
            st.session_state["tpl_reloading"] = None
            st.rerun()


@st.dialog(_("Delete template"))
def _show_delete_dialog(tpl_name: str, selected_name: str, add_log) -> None:
    """Confirm local-only deletion of a template."""
    entry = get_template_entry(selected_name, tpl_name)
    ui_name = str(entry.get("name") or tpl_name) if entry else tpl_name
    st.write(_("Do you really want to delete {name}?").format(name=ui_name))

    col_cancel, col_delete = st.columns(2)
    with col_cancel:
        if st.button(
            _("Cancel"),
            key=f"tpl_del_cancel_{tpl_name}",
            help=_("Close without deleting this template"),
            width="stretch",
        ):
            st.session_state["tpl_pending_delete_local"] = None
            st.rerun()
    with col_delete:
        if st.button(
            _("Delete"),
            key=f"tpl_del_confirm_{tpl_name}",
            icon=":material/delete:",
            type="primary",
            help=_("Delete this template"),
            width="stretch",
        ):
            delete_device_template(selected_name, tpl_name)
            remove_template_entry(selected_name, tpl_name)
            add_log(f"Template '{ui_name}' deleted locally from '{selected_name}'")
            deferred_toast(_("'{name}' deleted").format(name=ui_name), ":material/delete:")

            st.session_state["tpl_pending_delete_local"] = None
            st.rerun()


# ── Template card ─────────────────────────────────────────────────────────────


def _render_template_card(tpl_name, selected_name, device, add_log):
    """Render one template card: name/rename, preview, categories, upload & delete actions."""
    tpl_path = os.path.join(get_device_templates_dir(selected_name), tpl_name)
    renaming = st.session_state.get("tpl_renaming") == tpl_name
    entry = get_template_entry(selected_name, tpl_name)
    display_name = (
        str(entry.get("name") or os.path.splitext(tpl_name)[0])
        if entry
        else os.path.splitext(tpl_name)[0]
    )
    template_display_ref = f"{display_name}.template"
    renaming = st.session_state.get("tpl_renaming") in {tpl_name, template_display_ref}
    # ── name / inline rename ──────────────────────────────────────────────
    if renaming:

        def do_rename(_old=template_display_ref):
            raw = st.session_state.get(f"tpl_rename_input_{_old}", "").strip()
            new_name = normalise_filename(raw, ext=".template") if raw else None
            new_display_name = os.path.splitext(new_name)[0] if new_name else ""
            renamed_to = None
            if new_name and new_name != _old:
                existing_display_names = {
                    str((get_template_entry(selected_name, candidate) or {}).get("name") or "")
                    for candidate in list_device_templates(selected_name)
                    if candidate != _old
                }
                if new_display_name in existing_display_names:
                    st.session_state["tpl_pending_rename"] = (_old, new_name)
                    return
                rename_device_template(selected_name, _old, new_name)
                add_log(f"Renamed template '{_old}' \u2192 '{new_name}' for '{selected_name}'")
                renamed_to = new_name
            if renamed_to:
                deferred_toast(
                    _("Template renamed to '{name}'").format(name=renamed_to),
                    ":material/task_alt:",
                )
            st.session_state["tpl_renaming"] = None

        with st.form(key=f"tpl_rename_form_{tpl_name}", border=False):
            col_in, col_btn = st.columns([3, 1], vertical_alignment="center", gap="xxsmall")
            with col_in:
                st.text_input(
                    _("Rename template"),
                    value="",
                    placeholder=display_name,
                    key=f"tpl_rename_input_{template_display_ref}",
                    label_visibility="collapsed",
                )
            with col_btn:
                st.form_submit_button(
                    ":material/check:",
                    on_click=do_rename,
                    width="stretch",
                )
    else:
        bare = display_name
        display_name = bare if len(bare) <= 20 else bare[:17] + "..."
        if st.button(
            f"**{display_name}**",
            key=f"tpl_name_{tpl_name}",
            help=_("Click to rename"),
            type="tertiary",
            width="stretch",
        ):
            st.session_state["tpl_renaming"] = template_display_ref
            st.rerun()

    # ── preview ───────────────────────────────────────────────────────────
    from src.template_renderer import render_template_json_str, svg_as_img_tag

    with open(tpl_path, encoding="utf-8") as _f:
        _tpl_src = _f.read()
    _svg, _render_err = render_template_json_str(_tpl_src)
    if _render_err:
        st.warning(_render_err, icon=":material/error:")
    else:
        st.html(svg_as_img_tag(_svg, max_height=300))

    # Rename overwrite confirmation
    pending_rename = st.session_state.get("tpl_pending_rename")
    if pending_rename and pending_rename[0] in {tpl_name, template_display_ref}:
        _old_r, _new_r = pending_rename
        _dialog.confirm(
            _("Confirm replacement"),
            _("'{new}' already exists. Replace this template?").format(new=_new_r),
            key="confirm_rename_tpl",
        )
        result = st.session_state.get("confirm_rename_tpl")
        if result is True:
            rename_device_template(selected_name, _old_r, _new_r)
            add_log(f"Renamed template '{_old_r}' \u2192 '{_new_r}' for '{selected_name}'")
            deferred_toast(
                _("Template renamed to '{name}'").format(name=_new_r), ":material/task_alt:"
            )
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
        help=_("Edit categories"),
        width="stretch",
    ):
        _show_category_dialog(selected_name, tpl_name, add_log)

    # Labels button
    labels = entry.get("labels", []) if entry else []
    labels_str = _("Labels") if not labels else f"Labels: {', '.join(labels)}"
    if st.button(
        labels_str,
        key=f"tpl_labels_btn_{tpl_name}",
        type="tertiary",
        help=_("Edit labels"),
        width="stretch",
    ):
        _show_labels_dialog(selected_name, tpl_name, add_log)

    # Local delete confirmation (+ optional tablet delete)
    if st.session_state.get("tpl_pending_delete_local") in {tpl_name, template_display_ref}:
        _show_delete_dialog(tpl_name, selected_name, add_log)

    # ── segmented control (reload + delete) ──────────────────────────────
    action_key = f"tpl_action_{template_display_ref}"
    option_map = {
        "upload": ":material/upload_file:",
        "edit": ":material/edit:",
        "delete": ":material/delete:",
    }

    def on_tpl_action(_tpl=tpl_name, _akey=action_key):
        sel = st.session_state.get(_akey)
        if sel == "delete":
            st.session_state["tpl_pending_delete_local"] = template_display_ref
        elif sel == "upload":
            st.session_state["tpl_reloading"] = template_display_ref
        elif sel == "edit":
            st.session_state["tpl_editor_load_choice"] = f"{display_name}.template"
            st.session_state["tpl_edit_target"] = template_display_ref
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
    if st.session_state.get("tpl_reloading") in {tpl_name, template_display_ref}:
        _show_reload_dialog(tpl_name, selected_name, device, add_log)
    if st.session_state.get("tpl_edit_target") in {tpl_name, template_display_ref}:
        st.session_state.pop("tpl_edit_target", None)
        from src.templates import load_json_template

        st.session_state["tpl_editor_textarea"] = load_json_template(selected_name, tpl_name)
        st.session_state["tpl_editor_load_choice"] = f"{display_name}.template"
        st.switch_page("pages/template_editor.py")


def _render_template_upload_section(selected_name, add_log):
    """Section: upload local .template files as new templates, or create one from scratch."""
    st.subheader(_("Add a template"), divider="rainbow")

    tab_import, tab_create = st.tabs(
        [
            _(":material/upload_file: Import a file"),
            _(":material/edit_document: Create from scratch"),
        ]
    )

    with tab_create:
        st.write(
            _(
                "Open the template editor to create a new `.template` file "
                "in the reMarkable JSON format, with live SVG preview."
            )
        )
        if st.button(
            _("Open template editor"),
            key=f"tpl_new_{selected_name}",
            icon=":material/edit_document:",
            help=_("Create a new .template file in the editor"),
            width="stretch",
        ):
            st.session_state["tpl_editor_textarea"] = DEFAULT_TEMPLATE_JSON
            st.session_state["tpl_editor_reset_choice"] = True
            st.session_state.pop("tpl_editor_load_choice", None)
            st.switch_page("pages/template_editor.py")

    with tab_import:
        gen = st.session_state.get(f"tpl_upload_gen_{selected_name}", 0)
        cats_key = f"tpl_new_cats_{selected_name}_{gen}"
        extra_cats_key = f"tpl_new_extra_cats_{selected_name}_{gen}"
        prefill_signature_key = f"tpl_upload_prefill_sig_{selected_name}_{gen}"

        uploaded_files = st.file_uploader(
            _("Drag one or more `.template` files here"),
            type=["template"],
            accept_multiple_files=True,
            key=f"tpl_uploader_{selected_name}_{gen}",
        )
        if not uploaded_files:
            return

        uploaded_payloads = []
        template_categories: list[list[str]] = []
        only_template_files = True
        for uploaded_file in uploaded_files:
            content = (
                uploaded_file.getvalue()
                if hasattr(uploaded_file, "getvalue")
                else uploaded_file.read()
            )
            uploaded_payloads.append((uploaded_file, content))
            if uploaded_file.name.lower().endswith(".template"):
                categories = extract_categories_from_template_content(content)
                if categories is None:
                    only_template_files = False
                    break
                template_categories.append(sorted(set(categories)))
            else:
                only_template_files = False

        all_cats = get_all_categories(selected_name)
        upload_signature = tuple(
            (uploaded_file.name, len(content), tuple(categories))
            for (uploaded_file, content), categories in zip(
                uploaded_payloads,
                template_categories
                + [[]] * max(0, len(uploaded_payloads) - len(template_categories)),
                strict=False,
            )
        )
        common_categories = None
        if only_template_files and template_categories:
            first_categories = template_categories[0]
            if all(categories == first_categories for categories in template_categories[1:]):
                common_categories = first_categories

        if st.session_state.get(prefill_signature_key) != upload_signature:
            if common_categories is not None:
                st.session_state[cats_key] = [cat for cat in common_categories if cat in all_cats]
                st.session_state[extra_cats_key] = ", ".join(
                    cat for cat in common_categories if cat not in all_cats
                )
            else:
                st.session_state[cats_key] = []
                st.session_state[extra_cats_key] = ""
            st.session_state[prefill_signature_key] = upload_signature

        col_existing, col_new = st.columns([1, 1], vertical_alignment="bottom")
        with col_existing:
            sel_cats = st.multiselect(
                _("Existing categories"),
                options=all_cats,
                key=cats_key,
            )
        with col_new:
            extra_cats_input = st.text_input(
                _("New categories (comma-separated)"),
                key=extra_cats_key,
                placeholder="Color, Perso, ...",
            )

        if st.button(
            _("Save ({count} file(s))").format(count=len(uploaded_files)),
            key=f"ui_tpl_save_{selected_name}_{gen}",
            icon=":material/save:",
            help=_("Save templates locally"),
            width="stretch",
        ):
            extra_list = (
                [c.strip() for c in extra_cats_input.split(",") if c.strip()]
                if extra_cats_input
                else []
            )
            categories = list(sel_cats) + extra_list
            icon_code = "\ue9fe"
            saved = []
            for uf, content in uploaded_payloads:
                filename = normalise_filename(uf.name, ext=".template")
                save_device_template(selected_name, content, filename)
                add_template_entry(selected_name, filename, categories, icon_code)
                add_log(f"{filename} template saved for '{selected_name}'")
                saved.append(filename)
            if len(saved) == 1:
                deferred_toast(
                    _("Template {name} saved").format(name=saved[0]), ":material/task_alt:"
                )
            elif len(saved) > 1:
                deferred_toast(
                    _("{count} templates saved").format(count=len(saved)), ":material/task_alt:"
                )
            st.session_state[f"tpl_upload_gen_{selected_name}"] = gen + 1
            st.rerun()


# ── Page ─────────────────────────────────────────────────────────────────────

st.title(_(":material/description: Templates"))
rainbow_divider()

config = st.session_state.get("config", {})
add_log = st.session_state.get("add_log", lambda msg: None)
selected_name = st.session_state.get("selected_name")

DEVICES = config.get("devices", {})

require_device(DEVICES, selected_name)
assert isinstance(selected_name, str)

device = Device.from_dict(selected_name, DEVICES[selected_name])

manifest_path = get_device_manifest_json_path(selected_name)
if not os.path.exists(manifest_path):
    st.warning(
        _(
            "The template list for this tablet has not been imported yet. "
            "Turn on the tablet and click the button below to start."
        ),
        icon=":material/backup:",
    )
    if st.button(
        _("Initialize templates from this tablet"),
        key=f"tpl_fetch_backup_{selected_name}",
        type="primary",
        icon=":material/download:",
        help=_("Import templates from this tablet and initialize local metadata"),
    ):
        with st.spinner(_("Importing…")):
            ok, msg = fetch_and_init_templates(
                device.ip,
                device.password or "",
                selected_name,
                overwrite_backup=False,
            )
        if ok:
            add_log(f"Templates initialized for '{selected_name}' : {msg}")
            deferred_toast(_("Templates imported successfully"), ":material/task_alt:")
            st.rerun()
        add_log(f"Error initializing templates for '{selected_name}' : {msg}")
        st.error(_("Error: {msg}").format(msg=msg), icon=":material/error:")
else:
    refresh_local_manifest(selected_name)
    local_manifest = load_manifest(selected_name)
    if local_manifest.get("last_modified"):
        st.caption(
            _("Local manifest last modified: {date}").format(
                date=local_manifest.get("last_modified")
            )
        )

    col_verify, col_sync, col_force = st.columns(3)
    with col_verify:
        if st.button(
            _("Check sync status"),
            key=f"tpl_check_status_{selected_name}",
            icon=":material/compare:",
            help=_("Compare local and remote manifests"),
            width="stretch",
        ):
            with st.spinner(_("Checking…")):
                ok_check, payload = check_sync_status(selected_name, device, add_log)
            if ok_check:
                assert isinstance(payload, dict)
                st.session_state[f"tpl_sync_check_result_{selected_name}"] = payload
                deferred_toast(_("Sync status checked"), ":material/task_alt:")
            else:
                assert isinstance(payload, str)
                add_log(f"Sync check failed for '{selected_name}' : {payload}")
                deferred_toast(_("Sync check error"), ":material/error:")

    with col_sync:
        if st.button(
            _("Sync now"),
            key=f"tpl_check_sync_{selected_name}",
            icon=":material/sync:",
            help=_("Apply local manifest to the tablet"),
            width="stretch",
        ):
            with st.spinner(_("Syncing…")):
                ok = sync_templates_to_tablet(selected_name, device, add_log)
            if ok:
                deferred_toast(_("Templates synced"), ":material/task_alt:")
                st.rerun()
            deferred_toast(_("Sync error"), ":material/error:")
    with col_force:
        if st.button(
            _("Reset and reinitialize"),
            key=f"tpl_reset_reinit_{selected_name}",
            icon=":material/settings_backup_restore:",
            type="primary",
            help=_("Reset local template data and re-import from the tablet"),
            width="stretch",
        ):
            with st.spinner(_("Syncing…")):
                ok, msg = fetch_and_init_templates(
                    device.ip,
                    device.password or "",
                    selected_name,
                    overwrite_backup=True,
                )
            if ok:
                add_log(f"Templates reset and reinitialized for '{selected_name}' : {msg}")
                deferred_toast(_("Templates synced"), ":material/task_alt:")
            else:
                add_log(f"Error resetting templates for '{selected_name}' : {msg}")
                deferred_toast(_("Sync error"), ":material/error:")
            st.rerun()

    check_result = st.session_state.get(f"tpl_sync_check_result_{selected_name}")
    if isinstance(check_result, dict):
        st.info(
            _(
                "Sync check: {local} local, {remote} remote, {matched} matching, {upload} to upload, {delete} to delete remotely"
            ).format(
                local=check_result.get("local_count", 0),
                remote=check_result.get("remote_count", 0),
                matched=check_result.get("in_sync_count", 0),
                upload=len(check_result.get("to_upload", [])),
                delete=len(check_result.get("to_delete_remote", [])),
            ),
            icon=":material/compare:",
        )
        upload_items = check_result.get("to_upload", [])
        if upload_items:
            st.caption(_("Templates to upload or refresh:"))
            for item in upload_items:
                st.write(f"- {item.get('uuid')} ({item.get('reason')})")
        delete_items = check_result.get("to_delete_remote", [])
        if delete_items:
            st.caption(_("Templates to delete on tablet:"))
            for template_uuid in delete_items:
                st.write(f"- {template_uuid}")

    stored_templates = list_device_templates(selected_name)

    if stored_templates:
        col_title, col_sort = st.columns([2, 1], vertical_alignment="center")
        with col_title:
            st.subheader(_("Saved templates"), divider="rainbow")
        with col_sort:
            sort_by = st.segmented_control(
                _("Sort by"),
                options=[_("Date"), _("A \u2192 Z"), _("Categories")],
                default=_("Date"),
                key=f"tpl_sort_{selected_name}",
            )

        if sort_by == _("A \u2192 Z"):
            stored_templates = sorted(
                stored_templates,
                key=lambda f: str(
                    (get_template_entry(str(selected_name), f) or {}).get("name") or f
                ).lower(),
            )
        elif sort_by == _("Categories"):

            def _cat_key(f):
                entry = get_template_entry(str(selected_name), f)
                cats = entry.get("categories", []) if entry else []
                return ([c.lower() for c in sorted(cats)] if cats else ["\xff"], f.lower())

            stored_templates = sorted(stored_templates, key=_cat_key)

        st.space()
        st.markdown(
            _(
                "Below you will find all templates saved for this tablet. "
                "Click a **name** to rename, click the **categories** to add or remove categories, "
                "and use the action buttons "
                "to (:material/upload_file:) reload (upload a new file), (:material/edit:) edit, "
                "or (:material/delete:) delete templates."
            )
        )
        st.divider()

        for row_start in range(0, len(stored_templates), GRID_COLUMNS):
            row_items = stored_templates[row_start : row_start + GRID_COLUMNS]
            cols = st.columns(GRID_COLUMNS, gap="medium")
            for col_idx, tpl_name in enumerate(row_items):
                with cols[col_idx]:
                    _render_template_card(tpl_name, selected_name, device, add_log)
            if row_start + GRID_COLUMNS < len(stored_templates):
                st.divider()
    else:
        st.info(
            _(
                "No templates found for this device. "
                "Import templates from your computer or create new ones using the buttons below."
            ),
            icon=":material/description:",
        )

    _render_template_upload_section(selected_name, add_log)
