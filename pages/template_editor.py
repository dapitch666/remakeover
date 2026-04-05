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
    list_json_templates,
    load_json_template,
    save_json_template,
)
from src.ui_common import deferred_toast, init_page, normalise_filename, rainbow_divider

# ---------------------------------------------------------------------------
# Meta fields — shown as dedicated form controls, hidden from the raw textarea
# ---------------------------------------------------------------------------

# Fields extracted out of the JSON body and shown as separate widgets.
# "orientations" is an alias for "orientation" accepted on paste/load.
_META_FIELDS = frozenset(
    [
        "name",
        "author",
        "templateVersion",
        "formatVersion",
        "categories",
        "orientation",
        "orientations",
        "iconData",
        "labels",
    ]
)

# Canonical write order for meta fields in the reconstructed full JSON.
_META_FIELD_ORDER = [
    "name",
    "author",
    "templateVersion",
    "formatVersion",
    "categories",
    "orientation",
    "labels",
    "iconData",
]

# Session-state key → default value for every meta form widget.
_META_DEFAULTS: dict[str, str | int] = {
    "tpl_meta_name": "",
    "tpl_meta_author": "",
    "tpl_meta_template_version": "1.0.0",
    "tpl_meta_format_version": "1",
    "tpl_meta_categories": "Perso",
    "tpl_meta_orientation": "portrait",
    "tpl_meta_icon_data": "",
    "tpl_meta_labels": "",
}

_DEFAULT_JSON: str = DEFAULT_TEMPLATE_JSON


# ---------------------------------------------------------------------------
# Meta helpers
# ---------------------------------------------------------------------------


def _extract_meta_and_body(json_str: str) -> tuple[dict, str]:
    """Parse *json_str* and split into ``(meta_dict, body_json_str)``.

    *meta_dict* holds only the recognised meta fields.
    *body_json_str* is the remaining JSON without those fields.
    Returns ``({}, json_str)`` when the input is not valid JSON.
    """
    try:
        data = json.loads(json_str)
    except Exception:
        return {}, json_str
    if not isinstance(data, dict):
        return {}, json_str
    meta = {k: v for k, v in data.items() if k in _META_FIELDS}
    body = {k: v for k, v in data.items() if k not in _META_FIELDS}
    return meta, json.dumps(body, indent=4, ensure_ascii=True)


def _meta_to_session(meta: dict) -> None:
    """Write extracted meta values into form session-state keys."""
    if "name" in meta:
        st.session_state["tpl_meta_name"] = str(meta["name"])
    if "author" in meta:
        st.session_state["tpl_meta_author"] = str(meta["author"]).strip()
    if "templateVersion" in meta:
        version = str(meta["templateVersion"]).strip()
        st.session_state["tpl_meta_template_version"] = version or str(
            _META_DEFAULTS["tpl_meta_template_version"]
        )
    if "formatVersion" in meta:
        with suppress(Exception):
            parsed = str(int(meta["formatVersion"])).strip()
            st.session_state["tpl_meta_format_version"] = parsed or str(
                _META_DEFAULTS["tpl_meta_format_version"]
            )
    if "categories" in meta:
        cats = meta["categories"]
        st.session_state["tpl_meta_categories"] = (
            ", ".join(str(c) for c in cats) if isinstance(cats, list) else str(cats)
        )
    # Accept both "orientation" and "orientations"
    orientation = meta.get("orientation") or meta.get("orientations")
    if orientation is not None:
        val = str(orientation).lower()
        st.session_state["tpl_meta_orientation"] = (
            val if val in ("portrait", "landscape") else "portrait"
        )
    if "iconData" in meta:
        st.session_state["tpl_meta_icon_data"] = str(meta["iconData"])
    if "labels" in meta:
        lbls = meta["labels"]
        st.session_state["tpl_meta_labels"] = (
            ", ".join(str(lbl) for lbl in lbls) if isinstance(lbls, list) else str(lbls)
        )


def _meta_from_session() -> dict:
    """Build a meta dict from the current form session-state values."""
    cats_raw = str(
        st.session_state.get("tpl_meta_categories", _META_DEFAULTS["tpl_meta_categories"])
    )
    cats = [c.strip() for c in cats_raw.split(",") if c.strip()]

    lbls_raw = str(st.session_state.get("tpl_meta_labels", _META_DEFAULTS["tpl_meta_labels"]))
    lbls = [lbl.strip() for lbl in lbls_raw.split(",") if lbl.strip()]

    try:
        fmt_ver = int(
            st.session_state.get(
                "tpl_meta_format_version", _META_DEFAULTS["tpl_meta_format_version"]
            )
        )
    except (TypeError, ValueError):
        fmt_ver = 1

    return {
        "name": str(st.session_state.get("tpl_meta_name", _META_DEFAULTS["tpl_meta_name"])),
        "author": str(st.session_state.get("tpl_meta_author", _META_DEFAULTS["tpl_meta_author"])),
        "templateVersion": str(
            st.session_state.get(
                "tpl_meta_template_version", _META_DEFAULTS["tpl_meta_template_version"]
            )
        ),
        "formatVersion": fmt_ver,
        "categories": cats if cats else ["Perso"],
        "orientation": str(
            st.session_state.get("tpl_meta_orientation", _META_DEFAULTS["tpl_meta_orientation"])
        ),
        "labels": lbls,
        "iconData": str(
            st.session_state.get("tpl_meta_icon_data", _META_DEFAULTS["tpl_meta_icon_data"])
        ),
    }


def _build_full_json(body_str: str) -> str:
    """Merge meta form fields with *body_str* and return the full JSON string."""
    meta = _meta_from_session()

    # Ensure author has a default value when saving
    if not str(meta.get("author") or "").strip():
        meta["author"] = "rm-manager"

    try:
        body = json.loads(body_str)
    except Exception as exc:
        raise ValueError(f"invalid_json_body: {exc}") from exc
    if not isinstance(body, dict):
        raise ValueError("json_body_must_be_object")
    full: dict = {}
    for key in _META_FIELD_ORDER:
        val = meta.get(key)
        # Omit iconData when empty (ensure_template_payload_for_rmethods fills in the default)
        if key == "iconData" and not val:
            continue
        # Omit labels when empty list
        if key == "labels" and not val:
            continue
        full[key] = val
    full.update(body)
    return json.dumps(full, indent=4, ensure_ascii=True)


# ---------------------------------------------------------------------------
# Page
# ---------------------------------------------------------------------------

st.title(_(":material/edit_document: Template Editor"))
rainbow_divider()

config, selected_name, DEVICES = init_page(require_selected=False)
add_log = st.session_state.get("add_log", lambda msg: None)

_selected_device = Device.from_dict(str(selected_name or ""), DEVICES.get(selected_name, {}))
_portrait_w, _portrait_h = DEVICE_SIZES[_selected_device.resolve_type()]

# ---------------------------------------------------------------------------
# Initialize meta field defaults on first run
# ---------------------------------------------------------------------------

for _key, _default in _META_DEFAULTS.items():
    if _key not in st.session_state:
        st.session_state[_key] = _default

# Ensure non-empty defaults for template/format versions (but not for name/author)
for _key in ("tpl_meta_template_version", "tpl_meta_format_version"):
    if not str(st.session_state.get(_key, "")).strip():
        st.session_state[_key] = _META_DEFAULTS[_key]

# ---------------------------------------------------------------------------
# Sync: extract meta fields from textarea content (handles paste + template load)
# Runs BEFORE widgets are created so updated values are picked up immediately.
# ---------------------------------------------------------------------------

_textarea_current = st.session_state.get("tpl_editor_textarea", _DEFAULT_JSON)
_meta_detected, _body_detected = _extract_meta_and_body(_textarea_current)
if _meta_detected:
    _meta_to_session(_meta_detected)
    st.session_state["tpl_editor_textarea"] = _body_detected

# ---------------------------------------------------------------------------
# Compute editor height from orientation (read from meta form state)
# ---------------------------------------------------------------------------

_rm2_w, _rm2_h = DEVICE_SIZES["reMarkable 2"]
_base_editor_width = 650 * (_rm2_w / _rm2_h)
_orientation = st.session_state.get("tpl_meta_orientation", "portrait")
if _orientation == "landscape":
    _canvas_w, _canvas_h = _portrait_h, _portrait_w
else:
    _canvas_w, _canvas_h = _portrait_w, _portrait_h

_editor_height = int(round(_base_editor_width * (_canvas_h / _canvas_w)))
_editor_height = max(300, min(1000, _editor_height))

# ---------------------------------------------------------------------------
# Load / New controls
# ---------------------------------------------------------------------------

col_sel, col_new = st.columns([5, 1], vertical_alignment="bottom")
_new_choice_label = _("— New —")

# Apply any pre-run selectbox override before the widget is instantiated.
if st.session_state.pop("tpl_editor_reset_choice", False):
    st.session_state["tpl_editor_load_choice"] = _new_choice_label

_pending_load_choice = st.session_state.pop("tpl_editor_set_load_choice", None)
if isinstance(_pending_load_choice, str) and _pending_load_choice:
    st.session_state["tpl_editor_load_choice"] = _pending_load_choice

# Device change: reset one-time load guard.
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

_already_loaded_choice = st.session_state.get("tpl_editor_loaded_choice")
if (
    selected_name
    and selected_name in DEVICES
    and existing
    and load_choice != _new_choice_label
    and load_choice != _already_loaded_choice
):
    # Clear meta form state so the sync step on the next run picks up fresh values.
    for _key in _META_DEFAULTS:
        st.session_state.pop(_key, None)
    st.session_state["tpl_editor_loaded_choice"] = load_choice
    st.session_state["tpl_editor_textarea"] = load_json_template(selected_name, load_choice)
    st.rerun()
elif load_choice == _new_choice_label:
    if _already_loaded_choice != _new_choice_label:
        for _key, _default in _META_DEFAULTS.items():
            st.session_state[_key] = _default
        st.session_state["tpl_editor_textarea"] = _DEFAULT_JSON
    st.session_state["tpl_editor_loaded_choice"] = _new_choice_label

with col_new:
    if st.button(
        _("New"),
        key="tpl_editor_new_btn",
        icon=":material/add:",
        width="stretch",
    ):
        for _key in _META_DEFAULTS:
            st.session_state.pop(_key, None)
        st.session_state["tpl_editor_textarea"] = _DEFAULT_JSON
        st.session_state["tpl_editor_loaded_choice"] = _new_choice_label
        st.session_state["tpl_editor_reset_choice"] = True
        st.rerun()

# ---------------------------------------------------------------------------
# Metadata form
# ---------------------------------------------------------------------------

st.subheader(_("Metadata"), divider="rainbow")

_mf1, _mf2, _mf3, _mf4, _mf5 = st.columns([3, 3, 2, 2, 1])
with _mf1:
    st.text_input(_("Name"), key="tpl_meta_name", placeholder="mytemplate")
with _mf2:
    st.text_input(_("Author"), key="tpl_meta_author", placeholder="rm-manager")
with _mf3:
    st.selectbox(_("Orientation"), options=["portrait", "landscape"], key="tpl_meta_orientation")
with _mf4:
    st.text_input(
        _("Categories"),
        key="tpl_meta_categories",
        placeholder="Lines, Grids, …",
        help=_("Comma-separated. Known values: Lines, Grids, Planners, Creative"),
    )
with _mf5:
    st.text_input(
        _("Labels"),
        key="tpl_meta_labels",
        help=_("Comma-separated list of labels"),
    )

with st.expander(_("Advanced"), expanded=False):
    _adv1, _adv2 = st.columns([2, 1])
    with _adv1:
        st.text_area(
            _("Icon data (base64 SVG)"),
            key="tpl_meta_icon_data",
            height=80,
            help=_("Base64-encoded SVG icon. Leave empty to use the default icon."),
        )
    with _adv2:
        st.text_input(
            _("Template version"),
            key="tpl_meta_template_version",
            placeholder="1.0.0",
        )
        st.text_input(
            _("Format version"),
            key="tpl_meta_format_version",
            placeholder="1",
            help=_("Integer format version (usually 1)"),
        )

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
    # Reconstruct full JSON (meta form + textarea body) for the renderer.
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

assert selected_name is not None  # guaranteed by guard above

_loaded_choice = st.session_state.get("tpl_editor_loaded_choice", _new_choice_label)
_is_new_template = _loaded_choice == _new_choice_label

# Build full JSON (meta + body) for save / download.
try:
    _full_json_str = _build_full_json(json_str)
    _json_valid = True
except ValueError:
    _full_json_str = ""
    _json_valid = False

_gen: int = st.session_state.get("tpl_editor_save_gen", 0)

# Check if name is provided (required for save/download)
_name_is_provided = bool(str(st.session_state.get("tpl_meta_name", "")).strip())

# Save / Download buttons
col_save, col_dl = st.columns(2)

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
        _base = (
            st.session_state.get("tpl_meta_name", "").strip()
            or os.path.splitext(str(_loaded_choice))[0]
            or "My Template"
        )
        filename_tpl = normalise_filename(_base, ext=".template")

        cats = [
            c.strip()
            for c in st.session_state.get("tpl_meta_categories", "Perso").split(",")
            if c.strip()
        ] or ["Perso"]

        save_json_template(selected_name, filename_tpl, _full_json_str)
        add_template_entry(
            selected_name,
            filename_tpl,
            cats,
            previous_filename=None if _is_new_template else str(_loaded_choice),
        )

        add_log(f"Template '{filename_tpl}' saved for '{selected_name}'")
        deferred_toast(_("Template {name} saved").format(name=filename_tpl), ":material/task_alt:")

        # Pre-select the saved template in the dropdown on the next run.
        st.session_state["tpl_editor_set_load_choice"] = filename_tpl
        st.session_state["tpl_editor_loaded_choice"] = filename_tpl
        st.session_state["tpl_editor_save_gen"] = _gen + 1
        st.rerun()

with col_dl:
    if _json_valid and _name_is_provided:
        _dl_name = normalise_filename(
            str(st.session_state.get("tpl_meta_name", "")).strip(),
            ext=".template",
        )
        st.download_button(
            _("Download .template"),
            data=_full_json_str.encode("utf-8"),
            file_name=_dl_name,
            mime="application/json",
            icon=":material/download:",
            width="stretch",
        )

# ---------------------------------------------------------------------------
# Format documentation (collapsed by default)
# ---------------------------------------------------------------------------

with st.expander(_(":material/help: reMarkable JSON format documentation"), expanded=False):
    _spec_path = os.path.join(os.path.dirname(__file__), "..", "docs", "template-format-spec.md")
    with open(_spec_path, encoding="utf-8") as _f:
        st.markdown(_f.read())
