"""Template library page."""

import os
from contextlib import suppress

import streamlit as st

import src.dialog as _dialog
from src.constants import (
    DEFAULT_TEMPLATE_JSON,
    GRID_COLUMNS,
)
from src.i18n import _
from src.icon_font import (
    get_icon_font_path,
    render_icon_grid_html,
    render_icon_link_html,
    render_icon_preview_html,
)
from src.models import Device
from src.template_sync import sync_templates_to_tablet
from src.templates import (
    add_template_entry,
    delete_device_template,
    delete_template_from_tablet,
    extract_categories_from_template_content,
    fetch_and_init_templates,
    get_all_categories,
    get_device_manifest_json_path,
    get_device_templates_dir,
    get_template_entry,
    get_template_sync_status,
    get_templates_sync_overview,
    is_templates_dirty,
    list_device_templates,
    remove_template_entry,
    rename_device_template,
    rename_template_entry,
    reset_and_initialize_templates_from_tablet,
    save_device_template,
    set_template_sync_status,
    update_template_categories,
    update_template_icon_code,
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
        if st.button(_("Apply"), key=f"dialog_cats_ok_{tpl_name}", type="primary", width="stretch"):
            new_cats = list(new_sel)
            if extra:
                new_cats += [c.strip() for c in extra.split(",") if c.strip()]
            update_template_categories(selected_name, tpl_name, new_cats)
            add_log(f"Categories updated for '{tpl_name}' ({selected_name})")
            deferred_toast(_("Categories updated"), ":material/task_alt:")
            st.rerun()
    with col_cancel:
        if st.button(_("Cancel"), key=f"dialog_cats_cancel_{tpl_name}", width="stretch"):
            st.rerun()


# ── Icon dialog ─────────────────────────────────────────────────────────────────


@st.dialog(_("Edit icon"), width="large")
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

    st.caption(_("Enter a hexadecimal code directly or click an icon below:"))

    new_hex_input = st.text_input(
        _("Hex code (e.g.\u00a0E9FE)"),
        value=current_hex,
        max_chars=5,
        key=f"icon_hex_input_{tpl_name}",
    )
    col_ok, col_cancel = st.columns(2)
    with col_ok:
        if st.button(_("Apply"), key=f"icon_ok_{tpl_name}", type="primary", width="stretch"):
            try:
                cp = int(new_hex_input.strip(), 16)
                icon_code = chr(cp)
            except ValueError:
                st.error(_("Invalid hexadecimal code."))
                return
            update_template_icon_code(selected_name, tpl_name, icon_code)
            add_log(
                f"Icon updated for '{tpl_name}' ({selected_name}): \\u{new_hex_input.strip().upper()}"
            )
            deferred_toast(_("Icon updated"), ":material/task_alt:")
            st.rerun()
    with col_cancel:
        if st.button(_("Cancel"), key=f"icon_cancel_{tpl_name}", width="stretch"):
            st.rerun()

    if font_available:
        st.caption(_("Click an icon to apply it directly\u00a0:"))
        st.html(
            render_icon_grid_html(
                selected_cp=ord(current_code) if current_code else None,
                href_extra=f"&tpl_icon_for={stem}",
            )
        )
    else:
        st.info(
            _(
                "The icomoon font has not been extracted yet. "
                "Use the \u00ab\u202fIcon Font\u202f\u00bb page to extract it."
            ),
            icon=":material/info:",
        )


# ── Reload dialog ────────────────────────────────────────────────────────────


@st.dialog(_("Reload template"))
def _show_reload_dialog(tpl_name: str, selected_name: str, device, add_log) -> None:
    """Modal dialog to replace a template file locally and push it to the tablet."""
    _is_json_tpl = tpl_name.lower().endswith(".template")
    _accepted = ["template"] if _is_json_tpl else ["svg"]
    _label = _("New .template file") if _is_json_tpl else _("New SVG file")
    reload_file = st.file_uploader(
        _label,
        type=_accepted,
        key=f"tpl_reload_file_{tpl_name}",
    )
    col_save, col_cancel = st.columns(2, gap="xxsmall")
    with col_save:
        if st.button(
            _("Save"),
            key=f"tpl_reload_save_{tpl_name}",
            type="primary",
            disabled=reload_file is None,
            width="stretch",
        ):
            assert reload_file is not None
            content = reload_file.read()
            save_device_template(selected_name, content, tpl_name)
            add_log(f"Template '{tpl_name}' reloaded locally for '{selected_name}'")
            ok, msg = upload_template_to_tablet(
                device.ip, device.password or "", selected_name, tpl_name
            )
            if ok:
                deferred_toast(
                    _("{name} updated on the tablet").format(name=tpl_name), ":material/task_alt:"
                )
                add_log(f"Template {tpl_name} sent to '{selected_name}'")
            else:
                add_log(f"Failed to send {tpl_name} to '{selected_name}': {msg}")
                deferred_toast(_("Error sending {name}").format(name=tpl_name), ":material/error:")
            st.session_state["tpl_reloading"] = None
            st.rerun()
    with col_cancel:
        if st.button(
            _("Cancel"),
            key=f"tpl_reload_cancel_{tpl_name}",
            width="stretch",
        ):
            st.session_state["tpl_reloading"] = None
            st.rerun()


@st.dialog(_("Delete template"))
def _show_delete_dialog(tpl_name: str, selected_name: str, device, add_log) -> None:
    """Confirm local deletion and optionally delete remotely on the tablet."""
    st.write(_("Delete {name} locally?").format(name=tpl_name))
    delete_remote = st.checkbox(
        _("Also delete it from the tablet"),
        value=True,
        key=f"tpl_delete_remote_{tpl_name}",
    )

    col_cancel, col_delete = st.columns(2)
    with col_cancel:
        if st.button(
            _("Cancel"),
            key=f"tpl_del_cancel_{tpl_name}",
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
            width="stretch",
        ):
            delete_device_template(selected_name, tpl_name)
            remove_template_entry(selected_name, tpl_name)
            add_log(f"Template '{tpl_name}' deleted locally from '{selected_name}'")

            if delete_remote:
                ok, msg = delete_template_from_tablet(
                    device.ip, device.password or "", selected_name, tpl_name
                )
                if ok:
                    add_log(f"Template '{tpl_name}' deleted from tablet for '{selected_name}'")
                    deferred_toast(
                        _("'{name}' deleted locally and on tablet").format(name=tpl_name),
                        ":material/task_alt:",
                    )
                else:
                    add_log(f"Remote delete failed for '{tpl_name}' on '{selected_name}': {msg}")
                    deferred_toast(
                        _("'{name}' deleted locally, tablet delete failed").format(name=tpl_name),
                        ":material/error:",
                    )
            else:
                deferred_toast(_("'{name}' deleted").format(name=tpl_name), ":material/delete:")

            st.session_state["tpl_pending_delete_local"] = None
            st.rerun()


# ── Template card ─────────────────────────────────────────────────────────────


def _render_template_card(tpl_name, selected_name, device, add_log):
    """Render one template card: name/rename, SVG preview, categories, upload & delete actions."""
    tpl_path = os.path.join(get_device_templates_dir(selected_name), tpl_name)
    renaming = st.session_state.get("tpl_renaming") == tpl_name
    stem = os.path.splitext(tpl_name)[0]
    entry = get_template_entry(selected_name, tpl_name)
    current_icon_code = entry.get("iconCode", "\ue9fe") if entry else "\ue9fe"
    sync_status = get_template_sync_status(selected_name, tpl_name) or "pending"
    # ── name / inline rename ──────────────────────────────────────────────
    if renaming:

        def do_rename(_old=tpl_name):
            raw = st.session_state.get(f"tpl_rename_input_{_old}", "").strip()
            _ext = ".template" if _old.lower().endswith(".template") else ".svg"
            new_name = normalise_filename(raw, ext=_ext) if raw else None
            renamed_to = None
            if new_name and new_name != _old:
                if new_name in list_device_templates(selected_name):
                    st.session_state["tpl_pending_rename"] = (_old, new_name)
                    return
                rename_device_template(selected_name, _old, new_name)
                rename_template_entry(selected_name, _old, new_name)
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
                    help=_("Edit icon"),
                    type="tertiary",
                ):
                    _show_icon_dialog(selected_name, tpl_name, add_log)
        with col_name:
            if st.button(
                f"**{display_name}**",
                key=f"tpl_name_{tpl_name}",
                help=_("Click to rename"),
                type="tertiary",
                width="stretch",
            ):
                st.session_state["tpl_renaming"] = tpl_name
                st.rerun()

    # ── preview ───────────────────────────────────────────────────────────
    if tpl_name.lower().endswith(".template"):
        from src.template_renderer import render_template_json_str, svg_as_img_tag

        with open(tpl_path, encoding="utf-8") as _f:
            _tpl_src = _f.read()
        _svg, _render_err = render_template_json_str(_tpl_src)
        if _render_err:
            st.warning(_render_err, icon=":material/error:")
        else:
            st.html(svg_as_img_tag(_svg, max_height=300))
    else:
        st.image(tpl_path, width="stretch")

    # Rename overwrite confirmation
    pending_rename = st.session_state.get("tpl_pending_rename")
    if pending_rename and pending_rename[0] == tpl_name:
        _old_r, _new_r = pending_rename
        _dialog.confirm(
            _("Confirm replacement"),
            _("'{new}' already exists. Replace this template?").format(new=_new_r),
            key="confirm_rename_tpl",
        )
        result = st.session_state.get("confirm_rename_tpl")
        if result is True:
            rename_device_template(selected_name, _old_r, _new_r)
            rename_template_entry(selected_name, _old_r, _new_r)
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
    st.caption(_("Sync status: {status}").format(status=sync_status))

    if sync_status == "orphan":
        col_adopt, col_remove = st.columns(2)
        with col_adopt:
            if st.button(
                _("Add orphan"),
                key=f"tpl_orphan_add_{tpl_name}",
                icon=":material/add_task:",
                width="stretch",
            ):
                set_template_sync_status(selected_name, tpl_name, "pending")
                deferred_toast(
                    _("'{name}' marked for sync").format(name=tpl_name),
                    ":material/task_alt:",
                )
                st.rerun()
        with col_remove:
            if st.button(
                _("Delete orphan"),
                key=f"tpl_orphan_delete_{tpl_name}",
                icon=":material/delete:",
                width="stretch",
            ):
                set_template_sync_status(selected_name, tpl_name, "deleted")
                deferred_toast(
                    _("'{name}' marked for deletion").format(name=tpl_name),
                    ":material/delete:",
                )
                st.rerun()

    if st.button(
        cats_str,
        key=f"tpl_cats_btn_{tpl_name}",
        type="tertiary",
        help=_("Edit categories"),
        width="stretch",
    ):
        _show_category_dialog(selected_name, tpl_name, add_log)

    # Local delete confirmation (+ optional tablet delete)
    if st.session_state.get("tpl_pending_delete_local") == tpl_name:
        _show_delete_dialog(tpl_name, selected_name, device, add_log)

    # ── segmented control (reload + delete) ──────────────────────────────
    action_key = f"tpl_action_{tpl_name}"
    is_json_tpl = tpl_name.lower().endswith(".template")
    if is_json_tpl:
        option_map = {
            "upload": ":material/upload_file:",
            "edit": ":material/edit:",
            "delete": ":material/delete:",
        }
    else:
        option_map = {"upload": ":material/upload_file:", "delete": ":material/delete:"}

    def on_tpl_action(_tpl=tpl_name, _akey=action_key):
        sel = st.session_state.get(_akey)
        if sel == "delete":
            st.session_state["tpl_pending_delete_local"] = _tpl
        elif sel == "upload":
            st.session_state["tpl_reloading"] = _tpl
        elif sel == "edit":
            st.session_state["tpl_editor_load_choice"] = _tpl
            st.session_state["tpl_edit_target"] = _tpl
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
    if st.session_state.get("tpl_edit_target") == tpl_name:
        st.session_state.pop("tpl_edit_target", None)
        from src.templates import load_json_template

        st.session_state["tpl_editor_textarea"] = load_json_template(selected_name, tpl_name)
        st.session_state["tpl_editor_load_choice"] = tpl_name
        st.switch_page("pages/template_editor.py")


def _render_template_upload_section(selected_name, add_log):
    """Section: upload local SVG or .template files as new templates, or create one from scratch."""
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
            _("Drag one or more SVG or `.template` files here"),
            type=["svg", "template"],
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

        col_existing, col_new, col_icon, col_preview = st.columns(
            [2.2, 2.2, 1.2, 0.9],
            vertical_alignment="bottom",
        )
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
        with col_icon:
            icon_hex_input = st.text_input(
                _("Icon code (hex)"),
                value="E9FE",
                max_chars=5,
                key=f"tpl_new_icon_{selected_name}_{gen}",
                help=_("Hexadecimal icomoon icon code (e.g.\u00a0E9FE). Browse icons below."),
            )
        _icn_preview = ""
        with suppress(ValueError, OverflowError):
            _icn_preview = render_icon_preview_html(chr(int(icon_hex_input.strip(), 16)))
        with col_preview:
            st.caption(_("Icon preview"))
            if _icn_preview:
                st.html(_icn_preview)
            else:
                st.write("")
        _grid_html = render_icon_grid_html(
            selected_cp=int(icon_hex_input.strip(), 16) if icon_hex_input.strip() else None,
            clickable=False,
        )
        if _grid_html:
            with st.expander(_("Browse icons"), icon=":material/grid_view:"):
                st.html(_grid_html)

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
            try:
                icon_code = chr(int(icon_hex_input.strip(), 16))
            except (ValueError, OverflowError):
                icon_code = "\ue9fe"
            saved = []
            for uf, content in uploaded_payloads:
                _ext = ".template" if uf.name.lower().endswith(".template") else ".svg"
                filename = normalise_filename(uf.name, ext=_ext)
                save_device_template(selected_name, content, filename)
                add_template_entry(selected_name, filename, categories, icon_code)
                add_log(f"{filename} template saved for '{selected_name}'")
                saved.append(filename)
            if len(saved) == 1:
                deferred_toast(
                    _("Template {name} saved").format(name=saved[0]), ":material/task_alt:"
                )
            else:
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

# ── Handle icon change from grid navigation ───────────────────────────────────────
# Clicking an icon in the dialog grid (?tpl_icon_for=STEM) navigates here with ?icon=HEX.
_tpl_icon_for = st.query_params.get("tpl_icon_for")
_icon_hex = st.query_params.get("icon")
if _tpl_icon_for and _icon_hex:
    try:
        _icon_cp = int(_icon_hex, 16)
        update_template_icon_code(selected_name, _tpl_icon_for, chr(_icon_cp))
        add_log(f"Icon updated for '{_tpl_icon_for}' ({selected_name}): \\u{_icon_hex.upper()}")
        deferred_toast(_("Icon updated"), ":material/task_alt:")
    except ValueError:
        pass
    del st.query_params["tpl_icon_for"]
    del st.query_params["icon"]
    st.rerun()
elif st.query_params.get("edit_icon"):
    _edit_stem = st.query_params["edit_icon"]
    del st.query_params["edit_icon"]
    _show_icon_dialog(selected_name, _edit_stem + ".svg", add_log)

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
    ):
        with st.spinner(_("Importing…")):
            ok, msg = fetch_and_init_templates(
                device.ip,
                device.password or "",
                selected_name,
                include_remote_custom_templates=True,
                overwrite_backup=False,
            )
        if ok:
            add_log(f"Templates initialized for '{selected_name}' : {msg}")
            deferred_toast(_("Templates imported successfully"), ":material/task_alt:")
            st.rerun()
        add_log(f"Error initializing templates for '{selected_name}' : {msg}")
        st.error(_("Error: {msg}").format(msg=msg), icon=":material/error:")
else:
    overview = get_templates_sync_overview(selected_name)
    st.info(
        _(
            "Sync overview: {pending} pending, {orphan} orphan, {deleted} deleted, {synced} synced"
        ).format(
            pending=overview.get("pending", 0),
            orphan=overview.get("orphan", 0),
            deleted=overview.get("deleted", 0),
            synced=overview.get("synced", 0),
        ),
        icon=":material/sync:",
    )

    col_check, col_force = st.columns(2)
    with col_check:
        if st.button(
            _("Sync now"),
            key=f"tpl_check_sync_{selected_name}",
            icon=":material/sync:",
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
            width="stretch",
        ):
            with st.spinner(_("Syncing…")):
                ok, msg = reset_and_initialize_templates_from_tablet(
                    device.ip,
                    device.password or "",
                    selected_name,
                )
            if ok:
                add_log(f"Templates reset and reinitialized for '{selected_name}' : {msg}")
                deferred_toast(_("Templates synced"), ":material/task_alt:")
            else:
                add_log(f"Error resetting templates for '{selected_name}' : {msg}")
                deferred_toast(_("Sync error"), ":material/error:")
            st.rerun()

    stored_templates = list_device_templates(selected_name)

    if is_templates_dirty(selected_name):
        st.warning(
            _("Manifest contains unsynced changes."),
            icon=":material/sync:",
        )

    if stored_templates:
        st.markdown(
            _(
                "Below you will find all templates saved for this tablet. "
                "Click a **name** to rename, edit categories with the category button, "
                "customize the icon with the icon button, and use the action buttons "
                "to reload, edit, or delete templates."
            )
        )
        st.divider()

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
            stored_templates = sorted(stored_templates, key=lambda f: f.lower())
        elif sort_by == _("Categories"):

            def _cat_key(f):
                entry = get_template_entry(selected_name, f)
                cats = entry.get("categories", []) if entry else []
                return ([c.lower() for c in sorted(cats)] if cats else ["\xff"], f.lower())

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
        st.info(
            _(
                "No templates found for this device. "
                "Import templates from the tablet or add files from your computer below."
            ),
            icon=":material/description:",
        )

    _render_template_upload_section(selected_name, add_log)
