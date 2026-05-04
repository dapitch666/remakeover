"""Template editor panel rendered in the right column of the Templates page."""

import json
import os
from collections.abc import Callable

import streamlit as st

from src.constants import DEFAULT_ICON_DATA, DEFAULT_TEMPLATE_JSON, DEVICE_SIZES, META_DEFAULTS
from src.i18n import _
from src.models import Device
from src.template_list_ui import get_template_icon_svg
from src.template_renderer import render_template_json_str, svg_as_img_tag
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
    meta_from_dict,
    meta_to_dict,
    normalise_string_list,
    remove_template_entry,
    save_device_template,
    save_json_template,
    validate_svg_size,
)
from src.ui_common import deferred_toast, normalise_filename


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


def _on_icon_svg_upload() -> None:
    gen = st.session_state.get("tpl_icon_upload_gen", 0)
    upload = st.session_state.get(f"tpl_meta_icon_upload_{gen}")
    if upload is None:
        st.session_state.pop("_icon_upload_error", None)
        return
    orientation = str(st.session_state.get("tpl_meta_orientation", "portrait"))
    try:
        upl_svg = upload.read().decode("utf-8")
    except UnicodeDecodeError:
        st.session_state["_icon_upload_error"] = _("File is not valid UTF-8 text.")
        return
    ok, err = validate_svg_size(upl_svg, orientation=orientation, translate=_)
    if not ok:
        st.session_state["_icon_upload_error"] = err
        return
    st.session_state.pop("_icon_upload_error", None)
    new_b64 = encode_svg_to_icon_data(upl_svg)
    st.session_state["tpl_meta_icon_data"] = new_b64
    st.session_state["tpl_meta_icon_svg_code"] = upl_svg
    st.session_state["_icon_b64_prev"] = new_b64
    st.session_state["tpl_icon_upload_gen"] = gen + 1
    st.session_state["_icon_upload_pending_log"] = upload.name


def _meta_to_session(meta: dict) -> None:
    normalized = meta_to_dict(meta)
    for template_key, session_key in {
        "name": "tpl_meta_name",
        "author": "tpl_meta_author",
        "templateVersion": "tpl_meta_template_version",
        "formatVersion": "tpl_meta_format_version",
        "categories": "tpl_meta_categories",
        "labels": "tpl_meta_labels",
        "iconData": "tpl_meta_icon_data",
    }.items():
        if template_key in normalized:
            st.session_state[session_key] = normalized[template_key]
    if "orientation" in meta or "orientations" in meta:
        st.session_state["tpl_meta_orientation"] = normalized["orientation"]


def _meta_from_session() -> dict:
    flat = {k: st.session_state.get(k, META_DEFAULTS[k]) for k in META_DEFAULTS}
    return meta_from_dict(flat)


def _get_template_uuid_caption(template_uuid: str, sentinel_new: str) -> str:
    if template_uuid == sentinel_new:
        return _("New")
    return template_uuid


def load_template_into_editor(device_name: str, template_uuid: str) -> None:
    """Clear meta state and load the given template file into the editor."""
    for key in META_DEFAULTS:
        st.session_state.pop(key, None)
    st.session_state.pop("tpl_meta_icon_svg_code", None)
    st.session_state.pop("_icon_b64_prev", None)
    st.session_state["tpl_editor_textarea"] = load_json_template(
        device_name, f"{template_uuid}.template"
    )


def reset_editor_for_new() -> None:
    """Reset editor to blank template state."""
    for key in META_DEFAULTS:
        st.session_state.pop(key, None)
    st.session_state.pop("tpl_meta_icon_svg_code", None)
    st.session_state.pop("_icon_b64_prev", None)
    st.session_state["tpl_editor_textarea"] = DEFAULT_TEMPLATE_JSON


def _duplicate_template_into_editor(
    device: Device,
    template_uuid: str,
    add_log,
    *,
    on_select: Callable[[str], None],
    sentinel_new: str,
) -> None:
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

    on_select(sentinel_new)
    add_log(f"Template '{ui_name}' duplicated in editor for '{device.name}' (not saved)")
    deferred_toast(_("Template duplicated (not saved)"), ":material/task_alt:")


@st.dialog(_("Delete template"), dismissible=False)
def _show_delete_dialog(
    template_uuid: str, device: Device, add_log, *, on_deselect: Callable[[], None]
) -> None:
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
            get_template_icon_svg.clear()
            on_deselect()
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
            get_template_icon_svg.clear()
            load_template_into_editor(device.name, template_uuid)
            st.rerun()
    with col_cancel:
        if st.button(_("Cancel"), key=f"tpl_reload_cancel_{template_uuid}", width="stretch"):
            st.rerun()


# ── Right panel: editor ───────────────────────────────────────────────────────


def render_editor_panel(
    device: Device,
    add_log: Callable,
    *,
    sentinel_new: str,
    selected_uuid: Callable[[], str | None],
    on_select: Callable[[str], None],
    on_deselect: Callable[[], None],
) -> None:
    """Render the editor for the selected or new template."""
    selected = selected_uuid()

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

    is_new = selected == sentinel_new

    pending_textarea = st.session_state.pop("tpl_pending_editor_textarea", None)
    if isinstance(pending_textarea, str):
        for key in META_DEFAULTS:
            st.session_state.pop(key, None)
        st.session_state.pop("tpl_meta_icon_svg_code", None)
        st.session_state.pop("_icon_b64_prev", None)
        st.session_state["tpl_editor_textarea"] = pending_textarea

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
    st.caption("UUID: " + _get_template_uuid_caption(str(selected), sentinel_new))
    _mf1, _mf2, _mf3 = st.columns(3)
    _mf4, _mf5, _mf6, _mf7 = st.columns([2, 2, 1, 1])
    with _mf1:
        st.text_input(_("Name"), key="tpl_meta_name", placeholder="my template")
    with _mf2:
        st.text_input(_("Author"), key="tpl_meta_author", placeholder="reMakeover")
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
            st.file_uploader(
                _("Upload SVG file"),
                type=["svg"],
                key=f"tpl_meta_icon_upload_{_icon_upload_gen}",
                on_change=_on_icon_svg_upload,
            )
            _upload_err = st.session_state.pop("_icon_upload_error", None)
            if _upload_err:
                st.error(_upload_err, icon=":material/error:")
            _pending_log = st.session_state.pop("_icon_upload_pending_log", None)
            if _pending_log:
                add_log(
                    f"Icon '{_pending_log}' uploaded for template editor (device: '{device.name}')"
                )
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

    _json_valid = True
    _build_error = None
    try:
        _full_json_str = build_full_json(_meta_from_session(), json_str)
    except ValueError:
        _full_json_str = ""
        _json_valid = False
        _build_error = _("Invalid JSON body")

    with col_preview:
        st.subheader(_("Preview"), divider="rainbow")
        if _build_error:
            st.error(_build_error, icon=":material/error:")
        else:
            svg, render_error = render_template_json_str(
                _full_json_str, canvas_portrait=(_portrait_w, _portrait_h)
            )
            if render_error:
                st.error(render_error, icon=":material/error:")
            else:
                st.html(svg_as_img_tag(svg, max_height=_canvas_h, max_width=_canvas_w))

    # ── Actions ────────────────────────────────────────────────────────────
    st.subheader(_("Actions"), divider="rainbow")

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
            get_template_icon_svg.clear()
            if saved_uuid:
                on_select(saved_uuid)
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
            _duplicate_template_into_editor(
                device, str(selected), add_log, on_select=on_select, sentinel_new=sentinel_new
            )

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
            _show_delete_dialog(selected, device, add_log, on_deselect=on_deselect)

        st.button(
            _("Delete"),
            key=f"tpl_delete_btn_{selected}",
            icon=":material/delete:",
            disabled=is_new,
            width="stretch",
            help=_("Delete this template"),
            on_click=_on_tpl_delete,
        )

    with st.expander(_(":material/help: reMarkable JSON format documentation"), expanded=False):
        _spec_path = os.path.join(
            os.path.dirname(__file__), "..", "docs", "template-format-spec.md"
        )
        with open(_spec_path, encoding="utf-8") as _f:
            st.markdown(_f.read())
