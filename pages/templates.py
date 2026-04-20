"""Template library and editor page."""

import json
import os
from contextlib import suppress

import streamlit as st

import src.dialog as _dialog
from src.constants import (
    DEFAULT_ICON_DATA,
    DEFAULT_TEMPLATE_JSON,
    DEVICE_SIZES,
    META_DEFAULTS,
)

# noinspection PyProtectedMember
from src.i18n import _, _n
from src.manifest_templates import get_device_manifest_path, load_manifest
from src.models import Device
from src.template_renderer import render_template_json_str, svg_as_img_tag
from src.template_sync import (
    build_assumed_sync_status,
    check_sync_status,
    fetch_and_init_templates,
    fetch_single_template_from_device,
    refresh_cached_sync_status,
    sync_templates_to_device,
)
from src.templates import (
    add_template_entry,
    build_full_json,
    decode_icon_data,
    delete_device_template,
    encode_svg_to_icon_data,
    expected_icon_dimensions,
    extract_template_meta_and_body,
    get_all_categories,
    get_all_labels,
    get_template_entry_by_uuid,
    list_template_entries,
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
_SESSION_SELECTED_UUID_KEY = "tpl_selected_uuid"
_SESSION_LOADED_UUID_KEY = "tpl_loaded_uuid"


def _sync_status_key(selected_device: str) -> str:
    return f"tpl_sync_check_result_{selected_device}"


def _set_sync_status_assumed_in_sync(selected_device: str, state: str) -> None:
    st.session_state[_sync_status_key(selected_device)] = build_assumed_sync_status(
        selected_device, state
    )


def _refresh_sync_snapshot_after_remote_change(
    _device: Device,
    _add_log,
    fallback_state: str,
) -> None:
    """Refresh cached remote snapshot after a successful remote write operation.

    Prefer a real remote check, then gracefully fallback to an assumed in-sync state.
    """
    ok_check, payload = check_sync_status(_device, _add_log)
    if ok_check and isinstance(payload, dict):
        payload["last_remote_check_at"] = payload.get("checked_at")
        st.session_state[_sync_status_key(_device.name)] = payload
        return

    _set_sync_status_assumed_in_sync(_device.name, fallback_state)


def _get_realtime_sync_status(device: Device) -> dict | None:
    cached = st.session_state.get(_sync_status_key(device.name))
    if not isinstance(cached, dict):
        return None

    refreshed = refresh_cached_sync_status(device.name, cached)
    if refreshed is None:
        return cached

    return refreshed


def _render_sync_name_line(
    label: str,
    uuids: list[str],
    empty_message: str,
    *,
    name_by_uuid: dict | None = None,
    device: Device | None = None,
    is_device_only: bool = False,
    row_key: str = "",
    add_log,
) -> None:
    if not uuids:
        st.caption(f"{label}: {empty_message}")
        return

    expanded_rows: set = st.session_state.setdefault("tpl_pill_expanded_rows", set())
    is_expanded = row_key in expanded_rows

    if is_expanded:
        visible = uuids
        remaining = 0
    else:
        visible = uuids[:6]
        remaining = len(uuids) - len(visible)

    pill_options = list(visible)
    expand_label = f"+{remaining}"
    collapse_label = "−"
    if remaining > 0:
        pill_options.append(expand_label)
    elif is_expanded:
        pill_options.append(collapse_label)

    pill_key = f"tpl_pills_{row_key}"
    pending_key = f"tpl_pills_{row_key}_pending"

    def _on_pill_change() -> None:
        val = st.session_state.get(pill_key)
        if val is not None:
            st.session_state[pending_key] = val
            st.session_state[pill_key] = None

    def _format_pill(value: str) -> str:
        if value in (expand_label, collapse_label):
            return value
        return (name_by_uuid or {}).get(value, value)

    st.pills(label, pill_options, key=pill_key, on_change=_on_pill_change, format_func=_format_pill)

    selected = st.session_state.pop(pending_key, None)

    # Expand "+N" pill (st.rerun() stops further execution)
    if selected == expand_label:
        expanded_rows.add(row_key)
        st.rerun()

    # Collapse "−" pill
    if selected == collapse_label:
        expanded_rows.discard(row_key)
        st.rerun()

    # Template pills need device context
    if name_by_uuid is None or device is None:
        return

    confirm_uuid_key = f"tpl_pills_{row_key}_confirm_uuid"
    confirm_result_key = f"tpl_pills_{row_key}_confirm_result"

    # Handle a pending recovery confirmation from a previous run.
    # This must be checked before the `selected is None` guard so it runs
    # on reruns triggered by the dialog (where no new pill was clicked).
    pending_uuid = st.session_state.get(confirm_uuid_key)
    if pending_uuid:
        template_name = name_by_uuid.get(pending_uuid, pending_uuid)
        result = st.session_state.get(confirm_result_key)
        if result is True:
            st.session_state.pop(confirm_uuid_key, None)
            st.session_state.pop(confirm_result_key, None)
            import_ok, import_msg = fetch_single_template_from_device(device, pending_uuid)
            if import_ok:
                deferred_toast(
                    _("'{name}' recovered from device").format(name=template_name),
                    ":material/download:",
                )
                _load_template_into_editor(device.name, pending_uuid)
                _set_selected_template_uuid(pending_uuid)
            else:
                add_log(
                    f"Error recovering template '{template_name}' from '{device.name}': {import_msg}"
                )
                deferred_toast(
                    _("Import failed: {msg}").format(msg=import_msg),
                    ":material/error:",
                )
            st.rerun()
        elif result is False:
            st.session_state.pop(confirm_uuid_key, None)
            st.session_state.pop(confirm_result_key, None)
            st.rerun()
        else:
            _dialog.confirm(
                title=_("Recover template"),
                message=_(
                    "'{name}' only exists on the device. Recover it to local storage?"
                ).format(name=template_name),
                key=confirm_result_key,
            )
        return

    # No pending confirmation — handle a fresh pill selection
    if selected is None:
        return

    template_uuid = selected
    if is_device_only:
        st.session_state[confirm_uuid_key] = template_uuid
        st.rerun()

    _load_template_into_editor(device.name, template_uuid)
    _set_selected_template_uuid(template_uuid)
    st.rerun()


def _selected_template_uuid() -> str | None:
    selected = st.session_state.get(_SESSION_SELECTED_UUID_KEY)
    return str(selected) if isinstance(selected, str) else None


def _set_selected_template_uuid(template_uuid: str | None) -> None:
    st.session_state[_SESSION_SELECTED_UUID_KEY] = template_uuid


def _set_loaded_template_uuid(template_uuid: str | None) -> None:
    st.session_state[_SESSION_LOADED_UUID_KEY] = template_uuid


def _on_icon_svg_change() -> None:
    svg = str(st.session_state.get("tpl_meta_icon_svg_code") or "")
    if not svg.strip():
        return
    orientation = str(st.session_state.get("tpl_meta_orientation", "portrait"))
    _ok, _err = validate_svg_size(svg, orientation=orientation, translate=_)
    if _ok:
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
    labels = normalise_string_list(
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
        "labels": labels,
        "iconData": str(
            st.session_state.get("tpl_meta_icon_data", META_DEFAULTS["tpl_meta_icon_data"])
        ),
    }


@st.cache_data(ttl=60)
def _get_template_icon_svg(device_name: str, template_uuid: str) -> str:
    """Return the decoded icon SVG for a template (cached 60 s)."""
    if template_uuid == _SENTINEL_NEW:
        return ""
    entry = get_template_entry_by_uuid(device_name, template_uuid)
    if not entry:
        return ""
    icon_data = entry.get("iconData", "")
    if not icon_data:
        return ""
    return decode_icon_data(str(icon_data))


def _get_template_uuid_caption(template_uuid: str) -> str:
    """Return the current template UUID caption text for the editor header area."""
    if template_uuid == _SENTINEL_NEW:
        return _("New")
    return template_uuid


def _load_template_into_editor(device_name: str, template_uuid: str) -> None:
    """Clear meta state and load the given template file into the editor."""
    for key in META_DEFAULTS:
        st.session_state.pop(key, None)
    st.session_state.pop("tpl_meta_icon_svg_code", None)
    st.session_state.pop("_icon_b64_prev", None)
    st.session_state["tpl_editor_textarea"] = load_json_template(
        device_name, f"{template_uuid}.template"
    )
    _set_loaded_template_uuid(template_uuid)


def _reset_editor_for_new() -> None:
    """Reset editor to blank template state."""
    for key in META_DEFAULTS:
        st.session_state.pop(key, None)
    st.session_state.pop("tpl_meta_icon_svg_code", None)
    st.session_state.pop("_icon_b64_prev", None)
    st.session_state["tpl_editor_textarea"] = DEFAULT_TEMPLATE_JSON
    _set_loaded_template_uuid(_SENTINEL_NEW)


def _duplicate_template_into_editor(device: Device, template_uuid: str, add_log) -> None:
    """Queue a copy of an existing template into the unsaved editor state."""
    entry = get_template_entry_by_uuid(device.name, template_uuid)
    ui_name = (
        str(entry.get("display_name") or entry.get("name") or template_uuid)
        if entry
        else template_uuid
    )

    duplicated_raw = load_json_template(device.name, f"{template_uuid}.template")
    try:
        duplicated_payload = json.loads(duplicated_raw)
    except json.JSONDecodeError:
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

    _set_selected_template_uuid(_SENTINEL_NEW)
    _set_loaded_template_uuid(_SENTINEL_NEW)

    add_log(f"Template '{ui_name}' duplicated in editor for '{device.name}' (not saved)")
    deferred_toast(_("Template duplicated (not saved)"), ":material/task_alt:")


# ── Dialogs ───────────────────────────────────────────────────────────────────


@st.dialog(_("Delete template"), dismissible=False)
def _show_delete_dialog(template_uuid: str, device: Device, add_log) -> None:
    entry = get_template_entry_by_uuid(device.name, template_uuid)
    ui_name = (
        str(entry.get("display_name") or entry.get("name") or template_uuid)
        if entry
        else template_uuid
    )
    st.write(_("Do you really want to delete {name}?").format(name=ui_name))
    col_cancel, col_delete = st.columns(2)
    with col_cancel:
        if st.button(_("Cancel"), key=f"tpl_del_cancel_{template_uuid}", width="stretch"):
            st.rerun()
    with col_delete:
        if st.button(
            _("Delete"),
            key=f"tpl_del_confirm_{template_uuid}",
            icon=":material/delete:",
            type="primary",
            width="stretch",
        ):
            try:
                delete_device_template(device.name, template_uuid)
                remove_template_entry(device.name, template_uuid)
                add_log(f"Template '{ui_name}' deleted locally from '{device.name}'")
                deferred_toast(_("'{name}' deleted").format(name=ui_name), ":material/delete:")
            except OSError as e:
                add_log(f"Error deleting template '{ui_name}' from '{device.name}': {e}")
                deferred_toast(
                    _("Error deleting '{name}'").format(name=ui_name), ":material/error:"
                )
            _get_template_icon_svg.clear()
            _set_selected_template_uuid(None)
            _set_loaded_template_uuid(None)
            st.rerun()


@st.dialog(_("Replace template file"), dismissible=False)
def _show_reload_dialog(template_uuid: str, device: Device, add_log) -> None:
    entry = get_template_entry_by_uuid(device.name, template_uuid)
    ui_name = (
        str(entry.get("display_name") or entry.get("name") or template_uuid)
        if entry
        else template_uuid
    )
    reload_file = st.file_uploader(
        _("New .template file"),
        type=["template"],
        key=f"tpl_reload_file_{template_uuid}",
    )
    col_save, col_cancel = st.columns(2, gap="xxsmall")
    with col_save:
        if st.button(
            _("Save"),
            key=f"tpl_reload_save_{template_uuid}",
            type="primary",
            disabled=reload_file is None,
            width="stretch",
        ):
            assert reload_file is not None
            content = reload_file.read()
            save_device_template(device.name, content, f"{template_uuid}.template")
            add_log(f"Template '{ui_name}' reloaded locally for '{device.name}'")
            deferred_toast(
                _("'{name}' updated locally").format(name=ui_name), ":material/task_alt:"
            )
            _get_template_icon_svg.clear()
            _load_template_into_editor(device.name, template_uuid)
            st.rerun()
    with col_cancel:
        if st.button(_("Cancel"), key=f"tpl_reload_cancel_{template_uuid}", width="stretch"):
            st.rerun()


@st.dialog(_("Import templates"), dismissible=False)
def _show_import_dialog(device: Device, add_log) -> None:
    gen = st.session_state.get(f"tpl_upload_gen_{device.name}", 0)

    uploaded_files = st.file_uploader(
        _("Drag one or more `.template` files here"),
        type=["template"],
        accept_multiple_files=True,
        key=f"tpl_uploader_{device.name}_{gen}",
    )
    uploaded_payloads = []
    for uf in uploaded_files:
        content = uf.getvalue() if hasattr(uf, "getvalue") else uf.read()
        uploaded_payloads.append((uf, content))

    col_save, col_cancel = st.columns(2)
    with col_save:
        if st.button(
            _("Save"),
            key=f"ui_tpl_save_{device.name}_{gen}",
            type="primary",
            disabled=not uploaded_payloads,
            width="stretch",
        ):
            saved = []
            for uf, content in uploaded_payloads:
                filename = normalise_filename(uf.name, ext=".template")
                save_device_template(device.name, content, filename)
                add_template_entry(device.name, filename)
                add_log(f"{filename} template saved for '{device.name}'")
                saved.append(filename)
            if len(saved) == 1:
                deferred_toast(
                    _("Template {name} saved").format(name=saved[0]), ":material/task_alt:"
                )
            elif len(saved) > 1:
                deferred_toast(
                    _("{count} templates saved").format(count=len(saved)), ":material/task_alt:"
                )
            st.session_state[f"tpl_upload_gen_{device.name}"] = gen + 1
            st.rerun()
    with col_cancel:
        if st.button(_("Cancel"), key=f"tpl_import_cancel_{device.name}", width="stretch"):
            st.rerun()


# ── Left panel ────────────────────────────────────────────────────────────────


def _render_left_panel(device: Device, add_log) -> None:
    """Render the scrollable template list with filters and actions."""

    # Action buttons: New / Import
    col_new, col_import = st.columns(2, gap="small")
    with col_new:

        def _on_new():
            _reset_editor_for_new()
            _set_selected_template_uuid(_SENTINEL_NEW)

        st.button(
            _("New"),
            key="tpl_btn_new",
            icon=":material/add:",
            width="stretch",
            help=_("Create a new template from scratch"),
            on_click=_on_new,
        )
    with col_import:

        def _on_import():
            _show_import_dialog(device, add_log)

        st.button(
            _("Import"),
            key="tpl_btn_import",
            icon=":material/upload_file:",
            width="stretch",
            help=_("Import .template files from your computer"),
            on_click=_on_import,
        )

    # Sync section (collapsed)
    with st.expander(_(":material/sync: Sync"), expanded=False):
        manifest_json_path = get_device_manifest_path(device.name)
        if not os.path.exists(manifest_json_path):
            st.warning(_("Not initialized yet."), icon=":material/backup:")

            def _on_sync_init_from_device():
                _ok, _msg = fetch_and_init_templates(device, overwrite_backup=False)
                if _ok:
                    add_log(f"Templates initialized for '{device.name}' : {_msg}")
                    _refresh_sync_snapshot_after_remote_change(
                        device,
                        add_log,
                        "initialized_from_device",
                    )
                    deferred_toast(_("Templates imported successfully"), ":material/task_alt:")
                else:
                    add_log(f"Error initializing templates for '{device.name}' : {_msg}")
                    st.session_state["_tpl_sync_init_error"] = _msg
                    deferred_toast(_("Error: {msg}").format(msg=_msg), ":material/error:")

            st.button(
                _("Initialize from device"),
                key=f"tpl_fetch_init_{device.name}",
                type="primary",
                icon=":material/download:",
                width="stretch",
                on_click=_on_sync_init_from_device,
            )
            _sync_init_error = st.session_state.pop("_tpl_sync_init_error", None)
            if _sync_init_error:
                st.error(_("Error: {msg}").format(msg=_sync_init_error), icon=":material/error:")
        else:
            local_manifest = load_manifest(device.name)
            if local_manifest.get("last_modified"):
                date, time = format_datetime_for_ui(local_manifest["last_modified"])
                st.caption(_("Last modified on {date} at {time}").format(date=date, time=time))

            def _on_check_sync():
                ok_check, payload = check_sync_status(device, add_log)
                if ok_check:
                    if isinstance(payload, dict):
                        payload["last_remote_check_at"] = payload.get("checked_at")
                    st.session_state[_sync_status_key(device.name)] = payload
                    deferred_toast(_("Sync status checked"), ":material/task_alt:")
                else:
                    deferred_toast(_("Sync check error"), ":material/error:")

            st.button(
                _("Check sync"),
                key=f"tpl_check_status_{device.name}",
                icon=":material/compare:",
                help=_(
                    "Connect to the device and check if templates are in sync (does not change anything)"
                ),
                width="stretch",
                on_click=_on_check_sync,
            )

            def _on_sync_now():
                _ok = sync_templates_to_device(device.name, device, add_log)
                if _ok:
                    _refresh_sync_snapshot_after_remote_change(
                        device,
                        add_log,
                        "assumed_after_sync",
                    )
                    deferred_toast(_("Templates synced"), ":material/task_alt:")
                    _current = _selected_template_uuid()
                    if _current and _current != _SENTINEL_NEW:
                        _load_template_into_editor(device.name, str(_current))
                    st.session_state["tpl_list_gen"] = st.session_state.get("tpl_list_gen", 0) + 1
                else:
                    deferred_toast(_("Sync error"), ":material/error:")

            st.button(
                _("Sync now"),
                key=f"tpl_check_sync_{device.name}",
                icon=":material/sync:",
                help=_(
                    "Sync templates between this manager and the device (uploads new/modified templates, deletes remote-only templates)"
                ),
                width="stretch",
                on_click=_on_sync_now,
            )

            def _on_reset_reinit():
                _ok, _msg = fetch_and_init_templates(device, overwrite_backup=True)
                if _ok:
                    _refresh_sync_snapshot_after_remote_change(
                        device,
                        add_log,
                        "assumed_after_reinitialize",
                    )
                    deferred_toast(_("Templates synced"), ":material/task_alt:")
                    _current = _selected_template_uuid()
                    if (
                        _current
                        and _current != _SENTINEL_NEW
                        and any(
                            entry.get("uuid") == _current
                            for entry in list_template_entries(device.name)
                        )
                    ):
                        _load_template_into_editor(device.name, str(_current))
                    else:
                        _set_selected_template_uuid(None)
                        _set_loaded_template_uuid(None)
                else:
                    deferred_toast(_("Error: {msg}").format(msg=_msg), ":material/error:")

            st.button(
                _("Reset & reinitialize"),
                key=f"tpl_reset_reinit_{device.name}",
                icon=":material/settings_backup_restore:",
                help=_(
                    "Delete all local templates and re-fetch from the device (use if you think the local state is corrupted)"
                ),
                width="stretch",
                on_click=_on_reset_reinit,
            )

            check_result = _get_realtime_sync_status(device)
            if isinstance(check_result, dict):
                _local_count = check_result.get("local_count", 0)
                _remote_count = check_result.get("remote_count", 0)
                _to_upload_count = len(check_result.get("to_upload", []))
                _to_delete_count = len(check_result.get("to_delete_remote", []))
                st.info(
                    "  \n".join(
                        [
                            _n("{n} local template", "{n} local templates", _local_count).format(
                                n=_local_count
                            ),
                            _n("{n} remote template", "{n} remote templates", _remote_count).format(
                                n=_remote_count
                            ),
                            _n(
                                "{n} template to upload",
                                "{n} templates to upload",
                                _to_upload_count,
                            ).format(n=_to_upload_count),
                            _n(
                                "{n} template to delete on device",
                                "{n} templates to delete on device",
                                _to_delete_count,
                            ).format(n=_to_delete_count),
                        ]
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
                    list(check_result.get("to_upload_added_uuids", [])),
                    _("none"),
                    name_by_uuid=check_result.get("to_upload_added_name_by_uuid", {}),
                    device=device,
                    is_device_only=False,
                    row_key="added",
                    add_log=add_log,
                )
                _render_sync_name_line(
                    _("Modified locally (upload)"),
                    list(check_result.get("to_upload_modified_uuids", [])),
                    _("none"),
                    name_by_uuid=check_result.get("to_upload_modified_name_by_uuid", {}),
                    device=device,
                    is_device_only=False,
                    row_key="modified",
                    add_log=add_log,
                )
                _render_sync_name_line(
                    _("Remote-only (delete on sync)"),
                    list(check_result.get("to_delete_remote_uuids", [])),
                    _("none"),
                    name_by_uuid=check_result.get("to_delete_remote_name_by_uuid", {}),
                    device=device,
                    is_device_only=True,
                    row_key="remote_only",
                    add_log=add_log,
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
        all_cats = get_all_categories(device.name)
        filter_cats: list[str] = []
        if all_cats:
            filter_cats = st.multiselect(
                _("Categories"),
                options=all_cats,
                key="tpl_filter_cats",
                label_visibility="collapsed",
                placeholder=_("Filter by category…"),
            )
        all_labels = get_all_labels(device.name)
        filter_labels: list[str] = []
        if all_labels:
            filter_labels = st.multiselect(
                _("Labels"),
                options=all_labels,
                key="tpl_filter_labels",
                label_visibility="collapsed",
                placeholder=_("Filter by label…"),
            )
        filter_orientation = st.selectbox(
            _("Orientation"),
            options=["", "portrait", "landscape"],
            key="tpl_filter_orientation",
            label_visibility="collapsed",
            format_func=lambda v: _("All orientations") if not v else _(v.capitalize()),
        )

    # Build filtered template list
    template_entries = list_template_entries(device.name)
    entries: dict[str, dict] = {str(entry.get("uuid") or ""): entry for entry in template_entries}

    def _matches(_template_uuid: str) -> bool:
        entry = entries[_template_uuid]
        name = str(entry.get("display_name") or entry.get("name") or _template_uuid)
        if filter_text and filter_text.lower() not in name.lower():
            return False
        if filter_cats and not any(c in entry.get("categories", []) for c in filter_cats):
            return False
        if filter_labels and not any(lbl in entry.get("labels", []) for lbl in filter_labels):
            return False
        return not filter_orientation or entry.get("orientation") == filter_orientation

    filtered = [entry for entry in template_entries if _matches(str(entry.get("uuid") or ""))]
    selected = _selected_template_uuid()
    list_gen = st.session_state.get("tpl_list_gen", 0)

    if not template_entries:
        st.caption(_("No templates yet. Click 'New' or 'Import'."))
        return

    if not filtered:
        st.caption(_("No templates match the filter."))
        return

    _n_filtered = len(filtered)
    st.caption(_n("{n} template", "{n} templates", _n_filtered).format(n=_n_filtered))

    for entry in filtered:
        template_uuid = str(entry.get("uuid") or "")
        display_name = str(entry.get("display_name") or entry.get("name") or template_uuid)
        is_selected = selected == template_uuid
        icon_svg = _get_template_icon_svg(device.name, template_uuid)

        with st.container():
            icon_col, name_col = st.columns([1, 3], gap="xxsmall")
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

                def _on_select_template(uuid_=template_uuid):
                    _load_template_into_editor(device.name, uuid_)
                    _set_selected_template_uuid(uuid_)

                st.button(
                    display_name,
                    key=f"tpl_list_btn_{template_uuid}_{list_gen}",
                    type="primary" if is_selected else "tertiary",
                    width="stretch",
                    on_click=_on_select_template,
                )


# ── Right panel: editor ───────────────────────────────────────────────────────


def _render_editor_panel(device: Device, add_log) -> None:
    """Render the editor for the selected or new template."""
    selected = _selected_template_uuid()

    if selected is None:
        if not list_template_entries(device.name):
            st.info(
                _(
                    "No templates yet. Click **:material/add: New** to create one, or **:material/upload_file: Import** to add "
                    "from your computer."
                ),
                icon=":material/arrow_left_alt:",
            )
        else:
            st.info(
                _(
                    "Select a template from the list, or click **:material/add: New** to create one."
                ),
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
        _set_loaded_template_uuid(_SENTINEL_NEW)

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
    ) or list(META_DEFAULTS["tpl_meta_categories"])
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
    st.caption("UUID: " + _get_template_uuid_caption(str(selected)))
    _mf1, _mf2, _mf3 = st.columns(3)
    _mf4, _mf5, _mf6, _mf7 = st.columns([2, 2, 1, 1])
    with _mf1:
        st.text_input(_("Name"), key="tpl_meta_name", placeholder="my template")
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
            options=merge_multiselect_options(get_all_categories(device.name), _current_categories),
            key="tpl_meta_categories",
            accept_new_options=True,
            placeholder=_("Select or add categories"),
            help=_("Categories are used on the device to filter templates."),
        )
    with _mf5:
        _current_labels = normalise_string_list(st.session_state.get("tpl_meta_labels"))
        st.multiselect(
            _("Labels"),
            options=merge_multiselect_options(get_all_labels(device.name), _current_labels),
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

            _icon_upload_gen = st.session_state.get("tpl_icon_upload_gen", 0)
            _svg_upload = st.file_uploader(
                _("Upload SVG file"),
                type=["svg"],
                key=f"tpl_meta_icon_upload_{_icon_upload_gen}",
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
                    st.session_state["tpl_icon_upload_gen"] = _icon_upload_gen + 1
                    add_log(
                        f"Icon '{_svg_upload.name}' uploaded for template editor (device: '{device.name}')"
                    )
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
            _full_json_preview = build_full_json(_meta_from_session(), json_str)
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
        _full_json_str = build_full_json(_meta_from_session(), json_str)
    except ValueError:
        _full_json_str = ""
        _json_valid = False

    _name_is_provided = bool(str(st.session_state.get("tpl_meta_name", "")).strip())
    _gen: int = st.session_state.get("tpl_editor_save_gen", 0)

    col_save, col_dl, col_duplicate, col_reload, col_delete = st.columns(5)

    with col_save:

        def _on_tpl_save():
            _base = str(st.session_state.get("tpl_meta_name", "")).strip() or (
                str(selected) if not is_new else "My Template"
            )
            filename_tpl = normalise_filename(_base, ext=".template")
            save_json_template(device.name, filename_tpl, _full_json_str)
            saved_uuid = add_template_entry(
                device.name,
                filename_tpl,
                previous_filename=None if is_new else str(selected),
                preferred_name=str(st.session_state.get("tpl_meta_name", "")).strip(),
            )
            add_log(f"Template '{filename_tpl}' saved for '{device.name}'")
            deferred_toast(
                _("Template {name} saved").format(name=filename_tpl), ":material/task_alt:"
            )
            _get_template_icon_svg.clear()
            if saved_uuid:
                _set_selected_template_uuid(saved_uuid)
                _set_loaded_template_uuid(saved_uuid)
            st.session_state["tpl_editor_save_gen"] = _gen + 1

        st.button(
            _("Save"),
            key=f"tpl_editor_save_{_gen}",
            type="primary",
            icon=":material/save:",
            disabled=not (_json_valid and _name_is_provided),
            width="stretch",
            help=_("Save the .template file to the selected device's library."),
            on_click=_on_tpl_save,
        )

    with col_dl:
        enabled = _json_valid and _name_is_provided
        _dl_name = (
            normalise_filename(
                str(st.session_state.get("tpl_meta_name", "")).strip(), ext=".template"
            )
            if enabled
            else "template.template"
        )

        def _on_tpl_export():
            add_log(f"Exported template '{_dl_name}' for '{device.name}'")

        st.download_button(
            _("Export"),
            data=_full_json_str.encode("utf-8"),
            file_name=_dl_name,
            mime="application/json",
            icon=":material/download:",
            disabled=not enabled,
            width="stretch",
            help=_("Download the .template file to your computer"),
            on_click=_on_tpl_export,
        )

    with col_duplicate:

        def _on_tpl_duplicate():
            _duplicate_template_into_editor(device, str(selected), add_log)

        st.button(
            _("Duplicate"),
            key=f"tpl_duplicate_btn_{selected}",
            icon=":material/content_copy:",
            width="stretch",
            disabled=is_new,
            help=_("Create an unsaved copy in the editor"),
            on_click=_on_tpl_duplicate,
        )
    with col_reload:

        def _on_tpl_reload():
            _show_reload_dialog(selected, device, add_log)

        st.button(
            _("Replace file"),
            key=f"tpl_reload_btn_{selected}",
            icon=":material/upload_file:",
            disabled=is_new,
            width="stretch",
            help=_("Replace this template with a new .template file"),
            on_click=_on_tpl_reload,
        )
    with col_delete:

        def _on_tpl_delete():
            _show_delete_dialog(selected, device, add_log)

        st.button(
            _("Delete"),
            key=f"tpl_delete_btn_{selected}",
            icon=":material/delete:",
            disabled=is_new,
            width="stretch",
            help=_("Delete this template"),
            on_click=_on_tpl_delete,
        )
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
add_log_fn = st.session_state.get("add_log", lambda message: None)
assert isinstance(selected_name, str)

current_device = Device.from_dict(selected_name, DEVICES[selected_name])

# Reset selection when device changes
if st.session_state.get("tpl_device") != current_device.name:
    st.session_state["tpl_device"] = current_device.name
    _set_selected_template_uuid(None)
    _set_loaded_template_uuid(None)

# Guard: not initialized yet → show init screen, not the split layout
manifest_path = get_device_manifest_path(current_device.name)
if not os.path.exists(manifest_path):
    st.warning(
        _(
            "The template list for this device has not been imported yet. "
            "Turn on the device and click the button below to start."
        ),
        icon=":material/backup:",
    )

    def _on_init_templates():
        ok, msg = fetch_and_init_templates(current_device, overwrite_backup=False)
        if ok:
            add_log_fn(f"Templates initialized for '{current_device.name}' : {msg}")
            _refresh_sync_snapshot_after_remote_change(
                current_device,
                add_log_fn,
                "initialized_from_device",
            )
            deferred_toast(_("Templates imported successfully"), ":material/task_alt:")
        else:
            add_log_fn(f"Error initializing templates for '{current_device.name}' : {msg}")
            st.session_state["_tpl_page_init_error"] = msg

    st.button(
        _("Initialize templates from this device"),
        key=f"tpl_fetch_backup_{current_device.name}",
        type="primary",
        icon=":material/download:",
        help=_("Import templates from this device and initialize local metadata"),
        on_click=_on_init_templates,
    )
    _page_init_error = st.session_state.pop("_tpl_page_init_error", None)
    if _page_init_error:
        st.error(_("Error: {msg}").format(msg=_page_init_error), icon=":material/error:")
    st.stop()

refresh_local_manifest(current_device.name)

st.markdown(
    _("""Browse and manage templates for this device in the **left panel**.  
         Click a template to open it in the **editor** on the right, where you can update its 
         name, category, labels, icon, and body.  
         Use **:material/add: New template** to create one from scratch.  
         When you're done editing, click **:material/save: Save** to save locally, then 
         **:material/sync: Sync now** to push all changes to the device.
    """)
)
st.divider()

# ── Main split layout: list (left) | editor (right) ──────────────────────────

list_col, editor_col = st.columns([1, 3], gap="large")

with list_col:
    _render_left_panel(current_device, add_log_fn)

with editor_col:
    _render_editor_panel(current_device, add_log_fn)
