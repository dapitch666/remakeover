"""Template list panel rendered in the left column of the Templates page."""

from collections.abc import Callable

import streamlit as st

import src.dialog as _dialog
from src.i18n import _, _n
from src.manifest_templates import load_manifest
from src.models import Device
from src.template_renderer import svg_as_img_tag
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
    decode_icon_data,
    get_all_categories,
    get_all_labels,
    get_template_entry_by_uuid,
    list_template_entries,
    save_device_template,
)
from src.ui_common import deferred_toast, format_datetime_for_ui, normalise_filename

_SENTINEL_NEW = "__new__"


def _sync_status_key(selected_device: str) -> str:
    return f"tpl_sync_check_result_{selected_device}"


def _set_sync_status_assumed_in_sync(selected_device: str, state: str) -> None:
    st.session_state[_sync_status_key(selected_device)] = build_assumed_sync_status(
        selected_device, state
    )


def refresh_sync_snapshot_after_remote_change(
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
    on_select: Callable[[str], None],
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
                on_select(pending_uuid)
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

    on_select(template_uuid)
    st.rerun()


@st.cache_data(ttl=60)
def get_template_icon_svg(device_name: str, template_uuid: str) -> str:
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


def render_left_panel(
    device: Device,
    add_log: Callable,
    *,
    sentinel_new: str,
    on_new: Callable[[], None],
    on_select: Callable[[str], None],
    on_deselect: Callable[[], None],
    selected_uuid: Callable[[], str | None],
) -> None:
    """Render the scrollable template list with filters and actions."""

    # Action buttons: New / Import
    col_new, col_import = st.columns(2, gap="small")
    with col_new:
        st.button(
            _("New"),
            key="tpl_btn_new",
            icon=":material/add:",
            width="stretch",
            help=_("Create a new template from scratch"),
            on_click=on_new,
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
                refresh_sync_snapshot_after_remote_change(
                    device,
                    add_log,
                    "assumed_after_sync",
                )
                deferred_toast(_("Templates synced"), ":material/task_alt:")
                _current = selected_uuid()
                if _current and _current != sentinel_new:
                    on_select(str(_current))
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
                refresh_sync_snapshot_after_remote_change(
                    device,
                    add_log,
                    "assumed_after_reinitialize",
                )
                deferred_toast(_("Templates synced"), ":material/task_alt:")
                _current = selected_uuid()
                if (
                    _current
                    and _current != sentinel_new
                    and any(
                        entry.get("uuid") == _current
                        for entry in list_template_entries(device.name)
                    )
                ):
                    on_select(str(_current))
                else:
                    on_deselect()
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
                st.caption(_("Last remote check on {date} at {time}").format(date=date, time=time))
            _render_sync_name_line(
                _("Added locally (upload)"),
                list(check_result.get("to_upload_added_uuids", [])),
                _("none"),
                name_by_uuid=check_result.get("to_upload_added_name_by_uuid", {}),
                device=device,
                is_device_only=False,
                row_key="added",
                add_log=add_log,
                on_select=on_select,
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
                on_select=on_select,
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
                on_select=on_select,
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
    selected = selected_uuid()
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
        icon_svg = get_template_icon_svg(device.name, template_uuid)

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
                    on_select(uuid_)

                st.button(
                    display_name,
                    key=f"tpl_list_btn_{template_uuid}_{list_gen}",
                    type="primary" if is_selected else "tertiary",
                    width="stretch",
                    on_click=_on_select_template,
                )
