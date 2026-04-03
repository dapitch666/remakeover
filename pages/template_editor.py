"""Template editor — create and edit reMarkable JSON templates with live SVG preview.

The editor lets you write (or load a previously saved) template in the
reMarkable native JSON vector format, see an instant SVG preview, and
save the result so it can be deployed to the tablet from the Templates page.

The JSON source (``.template``) files are stored under
``data/<device>/templates/`` and deployed as-is to the tablet. The SVG
preview shown in the editor is generated locally for visual feedback only.
"""

import json
import os
from contextlib import suppress

import streamlit as st

from src.constants import DEFAULT_TEMPLATE_JSON, DEVICE_SIZES
from src.i18n import _
from src.models import Device
from src.template_renderer import render_template_json_str, svg_as_img_tag
from src.templates import (
    add_template_entry,
    get_all_labels,
    list_json_templates,
    load_json_template,
    save_json_template,
)
from src.ui_common import deferred_toast, normalise_filename, rainbow_divider

# ---------------------------------------------------------------------------
# Default template shown when the editor is opened fresh
# ---------------------------------------------------------------------------

_DEFAULT_JSON: str = DEFAULT_TEMPLATE_JSON

# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title(_(":material/edit_document: Template Editor"))
rainbow_divider()

config = st.session_state.get("config", {})
add_log = st.session_state.get("add_log", lambda msg: None)
selected_name = st.session_state.get("selected_name")
DEVICES = config.get("devices", {})

_selected_device = Device.from_dict(str(selected_name or ""), DEVICES.get(selected_name, {}))
_portrait_w, _portrait_h = DEVICE_SIZES[_selected_device.resolve_type()]

# Keep editor and preview visually aligned: derive textarea height from the
# selected template canvas aspect ratio, anchored to the historical RM2 size.
_rm2_w, _rm2_h = DEVICE_SIZES["reMarkable 2"]
_base_editor_width = 650 * (_rm2_w / _rm2_h)
_orientation = "portrait"
with suppress(Exception):
    _for_height = json.loads(st.session_state.get("tpl_editor_textarea", _DEFAULT_JSON))
    if _for_height.get("orientation") == "landscape":
        _orientation = "landscape"

if _orientation == "landscape":
    _canvas_w, _canvas_h = _portrait_h, _portrait_w
else:
    _canvas_w, _canvas_h = _portrait_w, _portrait_h

_editor_height = int(round(_base_editor_width * (_canvas_h / _canvas_w)))
_editor_height = max(450, min(1200, _editor_height))

# ---------------------------------------------------------------------------
# Load / New controls
# ---------------------------------------------------------------------------

col_sel, col_new = st.columns([5, 1], vertical_alignment="bottom")
_new_choice_label = _("— New —")

# Apply any pre-run selectbox override before the widget is instantiated
# (writing to a widget's session-state key after creation raises an error).
# tpl_editor_reset_choice=True → reset to "— New —" (the sentinel first option)
# tpl_editor_load_choice may also be pre-set by the Templates page to pre-select a file.
if st.session_state.pop("tpl_editor_reset_choice", False):
    st.session_state["tpl_editor_load_choice"] = _new_choice_label

# Device change: reset one-time load guard for the selectbox autoload.
if st.session_state.get("tpl_editor_selected_device") != selected_name:
    st.session_state["tpl_editor_selected_device"] = selected_name
    st.session_state.pop("tpl_editor_loaded_choice", None)

with col_sel:
    existing: list[str] = []
    if selected_name and selected_name in DEVICES:
        existing = list_json_templates(selected_name)
    load_choice = st.selectbox(
        _("Load an existing JSON template"),
        options=[_new_choice_label] + existing,
        key="tpl_editor_load_choice",
        label_visibility="visible",
    )

# Auto-load immediately when a template is selected from the dropdown.
_already_loaded_choice = st.session_state.get("tpl_editor_loaded_choice")
if (
    selected_name
    and selected_name in DEVICES
    and existing
    and load_choice != _new_choice_label
    and load_choice != _already_loaded_choice
):
    st.session_state["tpl_editor_loaded_choice"] = load_choice
    st.session_state["tpl_editor_textarea"] = load_json_template(selected_name, load_choice)
    st.rerun()
elif load_choice == _new_choice_label:
    if _already_loaded_choice != _new_choice_label:
        st.session_state["tpl_editor_textarea"] = _DEFAULT_JSON
    st.session_state["tpl_editor_loaded_choice"] = _new_choice_label

with col_new:
    if st.button(
        _("New"),
        key="tpl_editor_new_btn",
        icon=":material/add:",
        width="stretch",
    ):
        st.session_state["tpl_editor_textarea"] = _DEFAULT_JSON
        st.session_state["tpl_editor_loaded_choice"] = _new_choice_label
        st.session_state["tpl_editor_reset_choice"] = True
        st.rerun()

# ---------------------------------------------------------------------------
# Editor / Preview split layout
# ---------------------------------------------------------------------------

col_edit, col_preview = st.columns(2, gap="medium")

with col_edit:
    st.subheader(_("JSON"), divider="rainbow")
    if "tpl_editor_textarea" not in st.session_state:
        st.session_state["tpl_editor_textarea"] = _DEFAULT_JSON
    st.html(
        "<style>"
        ".st-key-tpl_editor_textarea textarea {"
        "  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;"
        "  font-size: 13px;"
        "  line-height: 1.5;"
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
    svg, render_error = render_template_json_str(
        json_str, canvas_portrait=(_portrait_w, _portrait_h)
    )
    if render_error:
        st.error(render_error, icon=":material/error:")
    else:
        st.html(svg_as_img_tag(svg, max_height=_canvas_h, max_width=_canvas_w))

# ---------------------------------------------------------------------------
# Format documentation (collapsed by default)
# ---------------------------------------------------------------------------

with st.expander(_(":material/help: reMarkable JSON format documentation"), expanded=False):
    _spec_path = os.path.join(os.path.dirname(__file__), "..", "docs", "template-format-spec.md")
    with open(_spec_path, encoding="utf-8") as _f:
        st.markdown(_f.read())

# ---------------------------------------------------------------------------
# Save section  (requires a device to be selected)
# ---------------------------------------------------------------------------

st.subheader(_("Save"), divider="rainbow")

if not (selected_name and selected_name in DEVICES):
    st.info(
        _("Select a tablet in the sidebar to save the template."),
        icon=":material/info:",
    )
    st.stop()

# Pre-fill fields from the parsed JSON when possible
_loaded_choice = st.session_state.get("tpl_editor_loaded_choice", _new_choice_label)
_is_new_template = _loaded_choice == _new_choice_label
_default_name = "" if _is_new_template else os.path.splitext(str(_loaded_choice))[0]
if not _default_name and not _is_new_template:
    _default_name = "My Template"

try:
    _parsed = json.loads(json_str)
    _default_cats: list[str] = _parsed.get("categories", ["Perso"])
    _default_labels: list[str] = [lbl for lbl in _parsed.get("labels", []) if isinstance(lbl, str)]
except Exception:
    _default_cats = ["Perso"]
    _default_labels = []

_gen: int = st.session_state.get("tpl_editor_save_gen", 0)

col_name = st.columns([1], vertical_alignment="bottom")[0]
with col_name:
    _name_key = f"tpl_editor_name_{_gen}_{selected_name or ''}_{_loaded_choice}"
    tpl_filename: str = st.text_input(
        _("Filename (without extension)"),
        value=_default_name,
        placeholder=_("Name of the template file"),
        key=_name_key,
    )

# Labels and iconData fields
col_labels, col_icon = st.columns(2)
with col_labels:
    _existing_labels = get_all_labels(selected_name)
    tpl_labels = st.multiselect(
        _("Labels (optional)"),
        options=sorted(set(_existing_labels) | set(_default_labels)),
        default=_default_labels,
        key=f"tpl_editor_labels_{_gen}",
        help=_("Add custom labels to organize your template"),
    )
    tpl_labels_extra = st.text_input(
        _("New labels (comma-separated)"),
        key=f"tpl_editor_labels_extra_{_gen}",
        placeholder="work, meeting, ...",
    )

with col_icon:
    tpl_icon_data = st.text_area(
        _("Icon data (base64 SVG, optional)"),
        value="",
        height=100,
        key=f"tpl_editor_icon_data_{_gen}",
        placeholder=_("Paste base64-encoded SVG for custom icon"),
        help=_("Leave blank for default icon"),
    )

# Save / Download buttons
# Enabled as long as the JSON is syntactically valid (preview errors don't block saving).
try:
    json.loads(json_str)
    _json_valid = True
except Exception:
    _json_valid = False

col_save, col_dl = st.columns(2)

with col_save:
    if st.button(
        _("Save"),
        key=f"tpl_editor_save_{_gen}",
        type="primary",
        icon=":material/save:",
        disabled=not _json_valid,
        width="stretch",
        help=_("Save the .template file to the selected device's library."),
    ):
        _fallback_name = "My Template"
        _base = tpl_filename.strip() or _default_name or _fallback_name
        filename_tpl = normalise_filename(_base, ext=".template")

        # Final categories — read directly from the JSON source
        cats = _default_cats or ["Perso"]

        icon_code = "\ue9fe"

        # Get labels and iconData from form inputs
        labels_list = list(tpl_labels) if tpl_labels else []
        if tpl_labels_extra:
            labels_list += [lbl.strip() for lbl in tpl_labels_extra.split(",") if lbl.strip()]
        labels_list = sorted(set(labels_list))
        icon_data_str = tpl_icon_data.strip() if tpl_icon_data else None

        # Save .template JSON source file (this IS the asset deployed to the tablet)
        save_json_template(selected_name, filename_tpl, json_str)
        # Register/update manifest metadata so sync picks it up on Templates page
        add_template_entry(
            selected_name,
            filename_tpl,
            cats,
            icon_code,
            previous_filename=None if _is_new_template else str(_loaded_choice),
            labels=labels_list,
            icon_data=icon_data_str,
        )

        add_log(f"Template '{filename_tpl}' saved for '{selected_name}'")
        deferred_toast(_("Template {name} saved").format(name=filename_tpl), ":material/task_alt:")
        st.session_state["tpl_editor_save_gen"] = _gen + 1
        st.rerun()

with col_dl:
    if _json_valid:
        _fallback_name = "My Template"
        _dl_name = normalise_filename(
            (tpl_filename.strip() or _default_name or _fallback_name),
            ext=".template",
        )
        st.download_button(
            _("Download .template"),
            data=json_str.encode("utf-8"),
            file_name=_dl_name,
            mime="application/json",
            icon=":material/download:",
            width="stretch",
        )
