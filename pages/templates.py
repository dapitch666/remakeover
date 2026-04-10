"""Unified template library and editor page."""

import json
import os
from contextlib import suppress
from typing import cast

import streamlit as st

from src.constants import (
    DEFAULT_ICON_DATA,
    DEFAULT_TEMPLATE_JSON,
    DEVICE_SIZES,
    META_DEFAULTS,
    META_FIELDS,
)
from src.i18n import _
from src.manifest_templates import load_manifest
from src.models import Device
from src.template_renderer import render_template_json_str, svg_as_img_tag
from src.template_sync import (
    build_assumed_sync_status,
    check_sync_status,
    fetch_and_init_templates,
    refresh_cached_sync_status,
    sync_templates_to_tablet,
)
from src.templates import (
    add_template_entry,
    decode_icon_data,
    delete_device_template,
    encode_svg_to_icon_data,
    expected_icon_dimensions,
    extract_template_meta_and_body,
    get_all_categories,
    get_all_labels,
    get_device_manifest_json_path,
    get_template_entry,
    list_device_templates,
    load_json_template,
    merge_multiselect_options,
    normalise_string_list,
    refresh_local_manifest,
    remove_template_entry,
    save_device_template,
    save_json_template,
    validate_svg_size,
)
from src.ui_common import (
    deferred_toast,
    format_datetime_for_ui,
    init_page,
    normalise_filename,
    rainbow_divider,
)

_SENTINEL_NEW = "__new__"


def _sync_status_key(selected_name: str) -> str:
    return f"tpl_sync_check_result_{selected_name}"


def _set_sync_status_assumed_in_sync(selected_name: str, state: str) -> None:
    st.session_state[_sync_status_key(selected_name)] = build_assumed_sync_status(
        selected_name, state
    )


def _refresh_sync_snapshot_after_remote_change(
    selected_name: str,
    device,
    add_log,
    fallback_state: str,
) -> None:
    """Refresh cached remote snapshot after a successful remote write operation.

    Prefer a real remote check, then gracefully fallback to an assumed in-sync state.
    """
    ok_check, payload = check_sync_status(selected_name, device, add_log)
    if ok_check and isinstance(payload, dict):
        payload["last_remote_check_at"] = payload.get("checked_at")
        st.session_state[_sync_status_key(selected_name)] = payload
        return

    _set_sync_status_assumed_in_sync(selected_name, fallback_state)


def _get_realtime_sync_status(selected_name: str) -> dict | None:
    cached = st.session_state.get(_sync_status_key(selected_name))
    if not isinstance(cached, dict):
        return None

    refreshed = refresh_cached_sync_status(selected_name, cached)
    if refreshed is None:
        return cached

    return refreshed


def _render_sync_name_line(label: str, names: list[str], empty_message: str) -> None:
    if not names:
        st.caption(f"{label}: {empty_message}")
        return

    visible = names[:6]
    remaining = len(names) - len(visible)
    pill_options = list(visible)
    if remaining > 0:
        pill_options.append(f"+{remaining}")

    st.pills(
        label,
        pill_options,
    )


def _on_icon_svg_change() -> None:
    svg = str(st.session_state.get("tpl_meta_icon_svg_code") or "")
    if not svg.strip():
        return
    orientation = str(st.session_state.get("tpl_meta_orientation", "portrait"))
    ok, _err = validate_svg_size(svg, orientation=orientation, translate=_)
    if ok:
        new_b64 = encode_svg_to_icon_data(svg)
        st.session_state["tpl_meta_icon_data"] = new_b64
        st.session_state["_icon_b64_prev"] = new_b64


# ── Meta helpers ──────────────────────────────────────────────────────────────


def _meta_to_session(meta: dict) -> None:
    if "name" in meta:
        st.session_state["tpl_meta_name"] = str(meta["name"])
    if "author" in meta:
        st.session_state["tpl_meta_author"] = str(meta["author"]).strip()
    if "templateVersion" in meta:
        version = str(meta["templateVersion"]).strip()
        st.session_state["tpl_meta_template_version"] = version or str(
            META_DEFAULTS["tpl_meta_template_version"]
        )
    if "formatVersion" in meta:
        with suppress(Exception):
            parsed = str(int(meta["formatVersion"])).strip()
            st.session_state["tpl_meta_format_version"] = parsed or str(
                META_DEFAULTS["tpl_meta_format_version"]
            )
    if "categories" in meta:
        st.session_state["tpl_meta_categories"] = normalise_string_list(meta["categories"])
    orientation = meta.get("orientation") or meta.get("orientations")
    if orientation is not None:
        val = str(orientation).lower()
        st.session_state["tpl_meta_orientation"] = (
            val if val in ("portrait", "landscape") else "portrait"
        )
    if "iconData" in meta:
        st.session_state["tpl_meta_icon_data"] = str(meta["iconData"])
    if "labels" in meta:
        st.session_state["tpl_meta_labels"] = normalise_string_list(meta["labels"])


def _meta_from_session() -> dict:
    cats = normalise_string_list(
        st.session_state.get("tpl_meta_categories", META_DEFAULTS["tpl_meta_categories"])
    )
    if not cats:
        cats = ["Perso"]
    lbls = normalise_string_list(
        st.session_state.get("tpl_meta_labels", META_DEFAULTS["tpl_meta_labels"])
    )
    try:
        fmt_ver = int(
            st.session_state.get(
                "tpl_meta_format_version", META_DEFAULTS["tpl_meta_format_version"]
            )
        )
    except (TypeError, ValueError):
        fmt_ver = 1
    return {
        "name": str(st.session_state.get("tpl_meta_name", META_DEFAULTS["tpl_meta_name"])),
        "author": str(st.session_state.get("tpl_meta_author", META_DEFAULTS["tpl_meta_author"])),
        "templateVersion": str(
            st.session_state.get(
                "tpl_meta_template_version", META_DEFAULTS["tpl_meta_template_version"]
            )
        ),
        "formatVersion": fmt_ver,
        "categories": cats if cats else ["Perso"],
        "orientation": str(
            st.session_state.get("tpl_meta_orientation", META_DEFAULTS["tpl_meta_orientation"])
        ),
        "labels": lbls,
        "iconData": str(
            st.session_state.get("tpl_meta_icon_data", META_DEFAULTS["tpl_meta_icon_data"])
        ),
    }


def _build_full_json(body_str: str) -> str:
    meta = _meta_from_session()
    if not str(meta.get("author") or "").strip():
        meta["author"] = "rm-manager"
    try:
        body = json.loads(body_str)
    except Exception as exc:
        raise ValueError(f"invalid_json_body: {exc}") from exc
    if not isinstance(body, dict):
        raise ValueError("json_body_must_be_object")
    full: dict = {}
    for key in META_FIELDS:
        val = meta.get(key)
        if key == "iconData" and not val:
            continue
        if key == "labels" and not val:
            continue
        full[key] = val
    full.update(body)
    return json.dumps(full, indent=4, ensure_ascii=True)


@st.cache_data(ttl=60)
def _get_template_icon_svg(selected_name: str, tpl_name: str) -> str:
    """Return the decoded icon SVG for a template (cached 60 s)."""
    entry = get_template_entry(selected_name, tpl_name)
    if not entry:
        return ""
    icon_data = entry.get("iconData", "")
    if not icon_data:
        return ""
    return decode_icon_data(str(icon_data))


def _get_template_uuid_caption(selected_name: str, tpl_name: str) -> str:
    """Return the current template UUID caption text for the editor header area."""
    if tpl_name == _SENTINEL_NEW:
        return _("New")

    entry = get_template_entry(selected_name, tpl_name)
    template_uuid = str(entry.get("uuid") or "").strip() if entry else ""
    if template_uuid:
        return template_uuid
    return _("New")


def _load_template_into_editor(selected_name: str, tpl_name: str) -> None:
    """Clear meta state and load the given template file into the editor."""
    for key in META_DEFAULTS:
        st.session_state.pop(key, None)
    st.session_state.pop("tpl_meta_icon_svg_code", None)
    st.session_state.pop("_icon_b64_prev", None)
    st.session_state["tpl_editor_textarea"] = load_json_template(selected_name, tpl_name)
    st.session_state["tpl_unified_loaded"] = tpl_name


def _reset_editor_for_new() -> None:
    """Reset editor to blank template state."""
    for key in META_DEFAULTS:
        st.session_state.pop(key, None)
    st.session_state.pop("tpl_meta_icon_svg_code", None)
    st.session_state.pop("_icon_b64_prev", None)
    st.session_state["tpl_editor_textarea"] = DEFAULT_TEMPLATE_JSON
    st.session_state["tpl_unified_loaded"] = _SENTINEL_NEW


def _duplicate_template_into_editor(selected_name: str, tpl_name: str, add_log) -> None:
    """Queue a copy of an existing template into the unsaved editor state."""
    entry = get_template_entry(selected_name, tpl_name)
    ui_name = str(entry.get("name") or tpl_name) if entry else tpl_name

    duplicated_raw = load_json_template(selected_name, tpl_name)
    try:
        duplicated_payload = json.loads(duplicated_raw)
    except Exception:
        duplicated_payload = {}
    if isinstance(duplicated_payload, dict):
        duplicated_payload.pop("name", None)
        st.session_state["tpl_pending_editor_textarea"] = json.dumps(
            duplicated_payload,
            indent=4,
            ensure_ascii=True,
        )
    else:
        st.session_state["tpl_pending_editor_textarea"] = duplicated_raw

    st.session_state["tpl_unified_selected"] = _SENTINEL_NEW
    st.session_state["tpl_unified_loaded"] = _SENTINEL_NEW

    add_log(f"Template '{ui_name}' duplicated in editor for '{selected_name}' (not saved)")
    deferred_toast(_("Template duplicated (not saved)"), ":material/task_alt:")


# ── Dialogs ───────────────────────────────────────────────────────────────────


@st.dialog(_("Delete template"), dismissible=False)
def _show_delete_dialog(tpl_name: str, selected_name: str, add_log) -> None:
    entry = get_template_entry(selected_name, tpl_name)
    ui_name = str(entry.get("name") or tpl_name) if entry else tpl_name
    st.write(_("Do you really want to delete {name}?").format(name=ui_name))
    col_cancel, col_delete = st.columns(2)
    with col_cancel:
        if st.button(_("Cancel"), key=f"tpl_del_cancel_{tpl_name}", width="stretch"):
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
            add_log(f"Template '{ui_name}' deleted locally from '{selected_name}'")
            deferred_toast(_("'{name}' deleted").format(name=ui_name), ":material/delete:")
            _get_template_icon_svg.clear()
            st.session_state["tpl_unified_selected"] = None
            st.session_state["tpl_unified_loaded"] = None
            st.rerun()


@st.dialog(_("Replace template file"), dismissible=False)
def _show_reload_dialog(tpl_name: str, selected_name: str, add_log) -> None:
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
            width="stretch",
        ):
            assert reload_file is not None
            content = reload_file.read()
            save_device_template(selected_name, content, tpl_name)
            add_log(f"Template '{ui_name}' reloaded locally for '{selected_name}'")
            deferred_toast(
                _("'{name}' updated locally").format(name=ui_name), ":material/task_alt:"
            )
            _get_template_icon_svg.clear()
            _load_template_into_editor(selected_name, tpl_name)
            st.rerun()
    with col_cancel:
        if st.button(_("Cancel"), key=f"tpl_reload_cancel_{tpl_name}", width="stretch"):
            st.rerun()


@st.dialog(_("Import templates"), dismissible=False)
def _show_import_dialog(selected_name: str, add_log) -> None:
    gen = st.session_state.get(f"tpl_upload_gen_{selected_name}", 0)

    uploaded_files = st.file_uploader(
        _("Drag one or more `.template` files here"),
        type=["template"],
        accept_multiple_files=True,
        key=f"tpl_uploader_{selected_name}_{gen}",
    )
    uploaded_payloads = []
    for uf in uploaded_files:
        content = uf.getvalue() if hasattr(uf, "getvalue") else uf.read()
        uploaded_payloads.append((uf, content))

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button(
            _("Save"),
            key=f"ui_tpl_save_{selected_name}_{gen}",
            type="primary",
            disabled=not uploaded_payloads,
            width="stretch",
        ):
            saved = []
            for uf, content in uploaded_payloads:
                filename = normalise_filename(uf.name, ext=".template")
                save_device_template(selected_name, content, filename)
                add_template_entry(selected_name, filename, [])
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
    with col_cancel:
        if st.button(_("Cancel"), key=f"tpl_import_cancel_{selected_name}", width="stretch"):
            st.rerun()


# ── Left panel ────────────────────────────────────────────────────────────────


def _render_left_panel(selected_name: str, device, add_log) -> None:
    """Render the scrollable template list with filters and actions."""

    # Action buttons: New / Import
    col_new, col_import = st.columns(2, gap="small")
    with col_new:
        if st.button(
            _("New"),
            key="tpl_btn_new",
            icon=":material/add:",
            width="stretch",
            help=_("Create a new template from scratch"),
        ):
            _reset_editor_for_new()
            st.session_state["tpl_unified_selected"] = _SENTINEL_NEW
            st.rerun()
    with col_import:
        if st.button(
            _("Import"),
            key="tpl_btn_import",
            icon=":material/upload_file:",
            width="stretch",
            help=_("Import .template files from your computer"),
        ):
            _show_import_dialog(selected_name, add_log)

    # Sync section (collapsed)
    with st.expander(_(":material/sync: Sync"), expanded=False):
        manifest_path = get_device_manifest_json_path(selected_name)
        if not os.path.exists(manifest_path):
            st.warning(_("Not initialized yet."), icon=":material/backup:")
            if st.button(
                _("Initialize from tablet"),
                key=f"tpl_fetch_init_{selected_name}",
                type="primary",
                icon=":material/download:",
                width="stretch",
            ):
                with st.spinner(_("Importing…")):
                    ok, msg = fetch_and_init_templates(
                        device.ip, device.password or "", selected_name, overwrite_backup=False
                    )
                if ok:
                    add_log(f"Templates initialized for '{selected_name}' : {msg}")
                    _refresh_sync_snapshot_after_remote_change(
                        selected_name,
                        device,
                        add_log,
                        "initialized_from_tablet",
                    )
                    deferred_toast(_("Templates imported successfully"), ":material/task_alt:")
                    st.rerun()
                add_log(f"Error initializing templates for '{selected_name}' : {msg}")
                st.error(_("Error: {msg}").format(msg=msg), icon=":material/error:")
        else:
            local_manifest = load_manifest(selected_name)
            if local_manifest.get("last_modified"):
                date, time = format_datetime_for_ui(local_manifest["last_modified"])
                st.caption(_("Last modified on {date} at {time}").format(date=date, time=time))

            if st.button(
                _("Check sync"),
                key=f"tpl_check_status_{selected_name}",
                icon=":material/compare:",
                help=_(
                    "Connect to the tablet and check if templates are in sync (does not change anything)"
                ),
                width="stretch",
            ):
                with st.spinner(_("Checking…")):
                    ok_check, payload = check_sync_status(selected_name, device, add_log)
                if ok_check:
                    if isinstance(payload, dict):
                        payload["last_remote_check_at"] = payload.get("checked_at")
                    st.session_state[_sync_status_key(selected_name)] = payload
                    st.toast(_(":green[Sync status checked]"), icon=":material/task_alt:")
                else:
                    st.toast(_(":red[Sync check error]"), icon=":material/error:")

            if st.button(
                _("Sync now"),
                key=f"tpl_check_sync_{selected_name}",
                icon=":material/sync:",
                help=_(
                    "Sync templates between this manager and the tablet (uploads new/modified templates, deletes remote-only templates)"
                ),
                width="stretch",
            ):
                with st.spinner(_("Syncing…")):
                    ok = sync_templates_to_tablet(selected_name, device, add_log)
                if ok:
                    _refresh_sync_snapshot_after_remote_change(
                        selected_name,
                        device,
                        add_log,
                        "assumed_after_sync",
                    )
                    deferred_toast(_("Templates synced"), ":material/task_alt:")
                    _current = st.session_state.get("tpl_unified_selected")
                    if _current and _current != _SENTINEL_NEW:
                        _load_template_into_editor(selected_name, str(_current))
                    st.session_state["tpl_list_gen"] = st.session_state.get("tpl_list_gen", 0) + 1
                    st.rerun()
                deferred_toast(_("Sync error"), ":material/error:")

            if st.button(
                _("Reset & reinitialize"),
                key=f"tpl_reset_reinit_{selected_name}",
                icon=":material/settings_backup_restore:",
                help=_(
                    "Delete all local templates and re-fetch from the tablet (use if you think the local state is corrupted)"
                ),
                width="stretch",
            ):
                with st.spinner(_("Syncing…")):
                    ok, msg = fetch_and_init_templates(
                        device.ip, device.password or "", selected_name, overwrite_backup=True
                    )
                if ok:
                    _refresh_sync_snapshot_after_remote_change(
                        selected_name,
                        device,
                        add_log,
                        "assumed_after_reinitialize",
                    )
                    deferred_toast(_("Templates synced"), ":material/task_alt:")
                    _current = st.session_state.get("tpl_unified_selected")
                    if (
                        _current
                        and _current != _SENTINEL_NEW
                        and _current in list_device_templates(selected_name)
                    ):
                        _load_template_into_editor(selected_name, str(_current))
                    else:
                        st.session_state["tpl_unified_selected"] = None
                        st.session_state["tpl_unified_loaded"] = None
                else:
                    deferred_toast(_("Sync error"), ":material/error:")
                st.rerun()

            check_result = _get_realtime_sync_status(selected_name)
            if isinstance(check_result, dict):
                st.info(
                    _("""Local templates: {local_count}  
                                  Remote templates: {remote_count}  
                                  To upload: {to_upload_count}  
                                  To delete on tablet: {to_delete_count}
                                  """).format(
                        local_count=check_result.get("local_count", 0),
                        remote_count=check_result.get("remote_count", 0),
                        to_upload_count=len(check_result.get("to_upload", [])),
                        to_delete_count=len(check_result.get("to_delete_remote", [])),
                    )
                )
                last_remote_check = check_result.get("last_remote_check_at")
                if last_remote_check:
                    date, time = format_datetime_for_ui(last_remote_check)
                    st.caption(
                        _("Last remote check on {date} at {time}").format(date=date, time=time)
                    )
                _render_sync_name_line(
                    _("Added locally (upload)"),
                    list(check_result.get("to_upload_added_names", [])),
                    _("none"),
                )
                _render_sync_name_line(
                    _("Modified locally (upload)"),
                    list(check_result.get("to_upload_modified_names", [])),
                    _("none"),
                )
                _render_sync_name_line(
                    _("Remote-only (delete on sync)"),
                    list(check_result.get("to_delete_remote_names", [])),
                    _("none"),
                )

    st.divider()

    # Filter: text search + category multiselect
    with st.expander(_(":material/filter_list: Filters"), expanded=False):
        filter_text = st.text_input(
            _("Search"),
            key="tpl_filter_text",
            placeholder=_("Filter by name…"),
            label_visibility="collapsed",
        )
        all_cats = get_all_categories(selected_name)
        filter_cats: list[str] = []
        if all_cats:
            filter_cats = st.multiselect(
                _("Categories"),
                options=all_cats,
                key="tpl_filter_cats",
                label_visibility="collapsed",
                placeholder=_("Filter by category…"),
            )
        all_labels = get_all_labels(selected_name)
        filter_labels: list[str] = []
        if all_labels:
            filter_labels = st.multiselect(
                _("Labels"),
                options=all_labels,
                key="tpl_filter_labels",
                label_visibility="collapsed",
                placeholder=_("Filter by label…"),
            )

    # Build filtered template list
    stored_templates = list_device_templates(selected_name)
    entries: dict[str, dict] = {
        t: (get_template_entry(selected_name, t) or {}) for t in stored_templates
    }

    def _matches(tpl_name: str) -> bool:
        entry = entries[tpl_name]
        name = str(entry.get("name") or os.path.splitext(tpl_name)[0])
        if filter_text and filter_text.lower() not in name.lower():
            return False
        if filter_cats and not any(c in entry.get("categories", []) for c in filter_cats):
            return False
        return not filter_labels or any(lbl in entry.get("labels", []) for lbl in filter_labels)

    filtered = sorted(
        [t for t in stored_templates if _matches(t)],
        key=lambda t: str(entries[t].get("name") or "").lower(),
    )
    selected = st.session_state.get("tpl_unified_selected")
    list_gen = st.session_state.get("tpl_list_gen", 0)

    if not stored_templates:
        st.caption(_("No templates yet. Click 'New' or 'Import'."))
        return

    if not filtered:
        st.caption(_("No templates match the filter."))
        return

    st.caption(_("{n} template(s)").format(n=len(filtered)))

    for tpl_name in filtered:
        entry = get_template_entry(selected_name, tpl_name)
        display_name = (
            str(entry.get("name") or os.path.splitext(tpl_name)[0])
            if entry
            else os.path.splitext(tpl_name)[0]
        )
        is_selected = selected == tpl_name
        icon_svg = _get_template_icon_svg(selected_name, tpl_name)

        with st.container():
            icon_col, name_col = st.columns([1, 3], gap="xxsmall", vertical_alignment="center")
            with icon_col:
                if icon_svg:
                    st.html(svg_as_img_tag(icon_svg, max_width=30, max_height=40))
                else:
                    st.html(
                        '<div style="width:30px;height:40px;background:#f0f0f0;'
                        "border:1px dashed #ccc;border-radius:4px;"
                        'display:inline-block;"></div>'
                    )
            with name_col:
                if st.button(
                    display_name,
                    key=f"tpl_list_btn_{tpl_name}_{list_gen}",
                    type="primary" if is_selected else "tertiary",
                    width="stretch",
                ):
                    _load_template_into_editor(selected_name, tpl_name)
                    st.session_state["tpl_unified_selected"] = tpl_name
                    st.rerun()


# ── Right panel: editor ───────────────────────────────────────────────────────


def _render_editor_panel(selected_name: str, device, add_log) -> None:
    """Render the editor for the selected or new template."""
    selected = st.session_state.get("tpl_unified_selected")

    if selected is None:
        st.info(
            _("Select a template from the list, or click 'New' to create one."),
            icon=":material/arrow_left_alt:",
        )
        return

    is_new = selected == _SENTINEL_NEW

    pending_textarea = st.session_state.pop("tpl_pending_editor_textarea", None)
    if isinstance(pending_textarea, str):
        for key in META_DEFAULTS:
            st.session_state.pop(key, None)
        st.session_state.pop("tpl_meta_icon_svg_code", None)
        st.session_state.pop("_icon_b64_prev", None)
        st.session_state["tpl_editor_textarea"] = pending_textarea
        st.session_state["tpl_unified_loaded"] = _SENTINEL_NEW

    # Canvas size for the selected device
    _portrait_w, _portrait_h = DEVICE_SIZES[device.resolve_type()]

    # ── Initialize meta field defaults ────────────────────────────────────
    for _key, _default in META_DEFAULTS.items():
        if _key not in st.session_state:
            st.session_state[_key] = list(_default) if isinstance(_default, list) else _default
    for _key in ("tpl_meta_template_version", "tpl_meta_format_version"):
        if not str(st.session_state.get(_key, "")).strip():
            st.session_state[_key] = META_DEFAULTS[_key]
    st.session_state["tpl_meta_categories"] = normalise_string_list(
        st.session_state.get("tpl_meta_categories")
    ) or list(cast(list[str], META_DEFAULTS["tpl_meta_categories"]))
    st.session_state["tpl_meta_labels"] = normalise_string_list(
        st.session_state.get("tpl_meta_labels")
    )

    # ── Sync meta from textarea (handles fresh loads) ─────────────────────
    _textarea_current = st.session_state.get("tpl_editor_textarea", DEFAULT_TEMPLATE_JSON)
    _meta_detected, _body_detected = extract_template_meta_and_body(_textarea_current)
    if _meta_detected:
        _meta_to_session(_meta_detected)
        st.session_state["tpl_editor_textarea"] = _body_detected

    # ── Keep icon SVG textarea in sync with iconData ───────────────────────
    _icon_b64_now = st.session_state.get("tpl_meta_icon_data", DEFAULT_ICON_DATA)
    if (
        st.session_state.get("_icon_b64_prev") != _icon_b64_now
        or "tpl_meta_icon_svg_code" not in st.session_state
    ):
        st.session_state["tpl_meta_icon_svg_code"] = decode_icon_data(_icon_b64_now)
        st.session_state["_icon_b64_prev"] = _icon_b64_now

    # ── Compute editor height from orientation ────────────────────────────
    _rm2_w, _rm2_h = DEVICE_SIZES["reMarkable 2"]
    _base_editor_width = 650 * (_rm2_w / _rm2_h)
    _orientation = st.session_state.get("tpl_meta_orientation", "portrait")
    if _orientation == "landscape":
        _canvas_w, _canvas_h = _portrait_h, _portrait_w
    else:
        _canvas_w, _canvas_h = _portrait_w, _portrait_h
    _editor_height = int(round(_base_editor_width * (_canvas_h / _canvas_w)))
    _editor_height = max(300, min(1000, _editor_height))
    _icon_expected_w, _icon_expected_h = expected_icon_dimensions(_orientation)

    # ── Metadata form ──────────────────────────────────────────────────────
    st.subheader(_("Metadata"), divider="rainbow")
    st.caption("UUID: " + _get_template_uuid_caption(selected_name, str(selected)))
    _mf1, _mf2, _mf3 = st.columns(3)
    _mf4, _mf5, _mf6, _mf7 = st.columns([2, 2, 1, 1])
    with _mf1:
        st.text_input(_("Name"), key="tpl_meta_name", placeholder="mytemplate")
    with _mf2:
        st.text_input(_("Author"), key="tpl_meta_author", placeholder="rm-manager")
    with _mf3:
        st.radio(
            _("Orientation"),
            options=["portrait", "landscape"],
            key="tpl_meta_orientation",
            horizontal=True,
        )
    with _mf4:
        _current_categories = normalise_string_list(st.session_state.get("tpl_meta_categories"))
        st.multiselect(
            _("Categories"),
            options=merge_multiselect_options(
                get_all_categories(selected_name), _current_categories
            ),
            key="tpl_meta_categories",
            accept_new_options=True,
            placeholder=_("Select or add categories"),
            help=_("Categories are used on the tablet to filter templates."),
        )
    with _mf5:
        _current_labels = normalise_string_list(st.session_state.get("tpl_meta_labels"))
        st.multiselect(
            _("Labels"),
            options=merge_multiselect_options(get_all_labels(selected_name), _current_labels),
            key="tpl_meta_labels",
            accept_new_options=True,
            placeholder=_("Select or add labels"),
            help=_("Labels are only used here to filter templates."),
        )
    with _mf6:
        st.text_input(
            _("Format version"),
            key="tpl_meta_format_version",
            placeholder="1",
            help=_("Integer format version (usually 1)"),
        )
    with _mf7:
        st.text_input(_("Template version"), key="tpl_meta_template_version", placeholder="1.0.0")

    with st.expander(_(":material/grid_on: Icon"), expanded=False):
        _ico1, _ico2 = st.columns([1, 3])
        with _ico1:
            _icon_svg_now = st.session_state.get("tpl_meta_icon_svg_code", "")
            if _icon_svg_now.strip():
                _icon_valid_preview, _icon_err_msg = validate_svg_size(
                    _icon_svg_now,
                    orientation=_orientation,
                    translate=_,
                )
            else:
                _icon_valid_preview, _icon_err_msg = False, ""
            if _icon_valid_preview:
                st.html(
                    svg_as_img_tag(
                        _icon_svg_now,
                        max_width=_icon_expected_w // 2,
                        max_height=_icon_expected_h // 2,
                        label=_("Icon preview"),
                    )
                )
            else:
                st.html(
                    f'<div style="width:{_icon_expected_w}px;height:{_icon_expected_h}px;background:#eee;'
                    'border:1px dashed #aaa;display:inline-block;margin-bottom:4px;"></div>'
                )

            _svg_upload = st.file_uploader(
                _("Upload SVG file"),
                type=["svg"],
                key="tpl_meta_icon_upload",
            )
            if _svg_upload is not None:
                _upl_svg = _svg_upload.read().decode("utf-8")
                _upl_ok, _upl_err = validate_svg_size(
                    _upl_svg,
                    orientation=_orientation,
                    translate=_,
                )
                if not _upl_ok:
                    st.error(_upl_err, icon=":material/error:")
                else:
                    _new_b64 = encode_svg_to_icon_data(_upl_svg)
                    st.session_state["tpl_meta_icon_data"] = _new_b64
                    st.session_state["tpl_meta_icon_svg_code"] = _upl_svg
                    st.session_state["_icon_b64_prev"] = _new_b64
                    st.rerun()
        with _ico2:
            st.html(
                "<style>"
                ".st-key-tpl_meta_icon_svg_code textarea {"
                "  font-family: JetBrainsMono, Consolas, Menlo, monospace;"
                "  font-size: 13px;"
                "  line-height: 1.5;"
                "  white-space: pre;"
                "  overflow-x: auto;"
                "}"
                "</style>"
            )
            st.text_area(
                _("Icon SVG code ({w}×{h} px)").format(w=_icon_expected_w, h=_icon_expected_h),
                key="tpl_meta_icon_svg_code",
                height=300,
                on_change=_on_icon_svg_change,
                help=_("Raw SVG source — not base64. Must match the selected orientation."),
            )
            if _icon_err_msg:
                st.warning(_icon_err_msg, icon=":material/warning:")

    # ── JSON editor + preview ──────────────────────────────────────────────
    col_edit, col_preview = st.columns(2, gap="medium")

    with col_edit:
        st.subheader(_("JSON"), divider="rainbow")
        if "tpl_editor_textarea" not in st.session_state:
            st.session_state["tpl_editor_textarea"] = DEFAULT_TEMPLATE_JSON
        st.html(
            "<style>"
            ".st-key-tpl_editor_textarea textarea {"
            "  font-family: JetBrainsMono, Consolas, Menlo, monospace;"
            "  font-size: 13px;"
            "  line-height: 1.5;"
            "  white-space: pre;"
            "  overflow-x: auto;"
            "}"
            "</style>"
        )
        json_str: str = st.text_area(
            _("Template JSON"),
            height=_editor_height,
            key="tpl_editor_textarea",
            label_visibility="collapsed",
            help=_("Enter your reMarkable template JSON here. The preview updates automatically."),
        )

    with col_preview:
        st.subheader(_("Preview"), divider="rainbow")
        try:
            _full_json_preview = _build_full_json(json_str)
            _build_error = None
        except ValueError:
            _full_json_preview = ""
            _build_error = _("Invalid JSON body")

        if _build_error:
            st.error(_build_error, icon=":material/error:")
        else:
            svg, render_error = render_template_json_str(
                _full_json_preview, canvas_portrait=(_portrait_w, _portrait_h)
            )
            if render_error:
                st.error(render_error, icon=":material/error:")
            else:
                st.html(svg_as_img_tag(svg, max_height=_canvas_h, max_width=_canvas_w))

    # ── Actions ────────────────────────────────────────────────────────────
    st.subheader(_("Actions"), divider="rainbow")

    _json_valid = True
    try:
        _full_json_str = _build_full_json(json_str)
    except ValueError:
        _full_json_str = ""
        _json_valid = False

    _name_is_provided = bool(str(st.session_state.get("tpl_meta_name", "")).strip())
    _gen: int = st.session_state.get("tpl_editor_save_gen", 0)

    col_save, col_dl, col_duplicate, col_reload, col_delete = st.columns(5)

    with col_save:
        if st.button(
            _("Save"),
            key=f"tpl_editor_save_{_gen}",
            type="primary",
            icon=":material/save:",
            disabled=not (_json_valid and _name_is_provided),
            width="stretch",
            help=_("Save the .template file to the selected device's library."),
        ):
            _base = str(st.session_state.get("tpl_meta_name", "")).strip() or (
                os.path.splitext(str(selected))[0] if not is_new else "My Template"
            )
            filename_tpl = normalise_filename(_base, ext=".template")
            cats = normalise_string_list(st.session_state.get("tpl_meta_categories")) or ["Perso"]
            save_json_template(selected_name, filename_tpl, _full_json_str)
            add_template_entry(
                selected_name,
                filename_tpl,
                cats,
                previous_filename=None if is_new else str(selected),
            )
            add_log(f"Template '{filename_tpl}' saved for '{selected_name}'")
            deferred_toast(
                _("Template {name} saved").format(name=filename_tpl), ":material/task_alt:"
            )
            _get_template_icon_svg.clear()
            st.session_state["tpl_unified_selected"] = filename_tpl
            st.session_state["tpl_unified_loaded"] = filename_tpl
            st.session_state["tpl_editor_save_gen"] = _gen + 1
            st.rerun()

    with col_dl:
        enabled = _json_valid and _name_is_provided
        _dl_name = (
            normalise_filename(
                str(st.session_state.get("tpl_meta_name", "")).strip(), ext=".template"
            )
            if enabled
            else "template.template"
        )
        st.download_button(
            _("Export"),
            data=_full_json_str.encode("utf-8"),
            file_name=_dl_name,
            mime="application/json",
            icon=":material/download:",
            disabled=not enabled,
            width="stretch",
            help=_("Download the .template file to your computer"),
        )

    with col_duplicate:
        if st.button(
            _("Duplicate"),
            key=f"tpl_duplicate_btn_{selected}",
            icon=":material/content_copy:",
            width="stretch",
            disabled=is_new,
            help=_("Create an unsaved copy in the editor"),
        ):
            _duplicate_template_into_editor(selected_name, str(selected), add_log)
            st.rerun()
    with col_reload:
        if st.button(
            _("Replace file"),
            key=f"tpl_reload_btn_{selected}",
            icon=":material/upload_file:",
            disabled=is_new,
            width="stretch",
            help=_("Replace this template with a new .template file"),
        ):
            _show_reload_dialog(selected, selected_name, add_log)
    with col_delete:
        if st.button(
            _("Delete"),
            key=f"tpl_delete_btn_{selected}",
            icon=":material/delete:",
            disabled=is_new,
            width="stretch",
            help=_("Delete this template"),
        ):
            _show_delete_dialog(selected, selected_name, add_log)
    # Format documentation
    with st.expander(_(":material/help: reMarkable JSON format documentation"), expanded=False):
        _spec_path = os.path.join(
            os.path.dirname(__file__), "..", "docs", "template-format-spec.md"
        )
        with open(_spec_path, encoding="utf-8") as _f:
            st.markdown(_f.read())


# ── Page ──────────────────────────────────────────────────────────────────────

st.title(_(":material/description: Templates"))
rainbow_divider()

config, selected_name, DEVICES = init_page()
add_log = st.session_state.get("add_log", lambda msg: None)
assert isinstance(selected_name, str)

device = Device.from_dict(selected_name, DEVICES[selected_name])

# Reset selection when device changes
if st.session_state.get("tpl_unified_device") != selected_name:
    st.session_state["tpl_unified_device"] = selected_name
    st.session_state["tpl_unified_selected"] = None
    st.session_state["tpl_unified_loaded"] = None

# Guard: not initialized yet → show init screen, not the split layout
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
            _refresh_sync_snapshot_after_remote_change(
                selected_name,
                device,
                add_log,
                "initialized_from_tablet",
            )
            deferred_toast(_("Templates imported successfully"), ":material/task_alt:")
            st.rerun()
        add_log(f"Error initializing templates for '{selected_name}' : {msg}")
        st.error(_("Error: {msg}").format(msg=msg), icon=":material/error:")
    st.stop()

refresh_local_manifest(selected_name)

# ── Main split layout: list (left) | editor (right) ──────────────────────────

list_col, editor_col = st.columns([1, 3], gap="large")

with list_col:
    _render_left_panel(selected_name, device, add_log)

with editor_col:
    _render_editor_panel(selected_name, device, add_log)
