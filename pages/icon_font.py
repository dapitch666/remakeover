"""Icon font browser — extract and browse the icomoon glyphs embedded in xochitl."""

import os

import streamlit as st

from src.i18n import _
from src.icon_font import fetch_icon_font, get_icon_codepoints, get_icon_font_path
from src.models import Device
from src.templates import get_device_templates_json_path, load_templates_json
from src.ui_common import deferred_toast, rainbow_divider, require_device


@st.dialog("Icône sélectionnée", width="small")
def _show_icon_detail(cp: int) -> None:
    hex_str = f"{cp:04X}"
    glyph = chr(cp)
    st.html(
        f'<div style="display:flex;flex-direction:column;align-items:center;'
        f'gap:12px;padding:16px 0;">'
        f'<span style="font-family:icomoon,sans-serif;font-size:96px;'
        f'line-height:1;color:#222;">{glyph}</span>'
        f'<code style="font-size:15px;color:#555;">\\u{hex_str}</code>'
        f"</div>"
    )
    st.info(
        _("Code `\\u{hex}` — copy this code to use it in a template.").format(hex=hex_str),
        icon=":material/check_circle:",
    )


st.title(_(":material/style: Icon Font"))
rainbow_divider()

config = st.session_state.get("config", {})
add_log = st.session_state.get("add_log", lambda msg: None)
selected_name = st.session_state.get("selected_name")

DEVICES = config.get("devices", {})
require_device(DEVICES, selected_name)
assert isinstance(selected_name, str)

device = Device.from_dict(selected_name, DEVICES[selected_name])

# ── Re-extraction control ─────────────────────────────────────────────────────

codepoints = get_icon_codepoints()
font_path = get_icon_font_path()
size_kb = os.path.getsize(font_path) // 1024
col_info, col_btn = st.columns([3, 1], vertical_alignment="center")
with col_info:
    st.caption(
        _("Icomoon font · {size_kb} KB · {count} glyph(s)").format(
            size_kb=size_kb, count=len(codepoints)
        )
    )
with col_btn:
    if st.button(
        _("Re-extract"),
        key="icon_font_refetch",
        icon=":material/refresh:",
        width="stretch",
        help=_("Download xochitl from the tablet and re-extract the font"),
    ):
        with st.spinner(_("Downloading xochitl and extracting the font…")):
            ok, msg = fetch_icon_font(device.ip, device.password or "", selected_name)
        if ok:
            add_log(f"Icomoon font re-extracted for '{selected_name}' : {msg}")
            deferred_toast(_("Font extracted successfully"), ":material/task_alt:")
            st.rerun()
        else:
            st.error(_("Error: {msg}").format(msg=msg), icon=":material/error:")
            add_log(f"Error extracting icon font for '{selected_name}' : {msg}")

# ── Usage filter ─────────────────────────────────────────────────────────────

templates_json_path = get_device_templates_json_path(selected_name)
if os.path.exists(templates_json_path):
    templates_data = load_templates_json(selected_name)
    used_codepoints: set[int] = {
        ord(t["iconCode"]) for t in templates_data.get("templates", []) if t.get("iconCode")
    }
    _FILTER_OPTIONS = {
        _("All"): None,
        _("Used by the tablet"): True,
        _("Unused"): False,
    }
    filter_label = st.radio(
        _("Show"),
        options=list(_FILTER_OPTIONS.keys()),
        horizontal=True,
        key="icon_filter",
    )
    filter_used = _FILTER_OPTIONS[filter_label]
    if filter_used is True:
        codepoints = [cp for cp in codepoints if cp in used_codepoints]
    elif filter_used is False:
        codepoints = [cp for cp in codepoints if cp not in used_codepoints]

# ── Icon grid ─────────────────────────────────────────────────────────────────

# Inject icomoon at the front of the button font stack so PUA glyphs render.
# Normal characters simply fall through to the next font — no visual side effects.
st.html(
    "<style>"
    '.st-key-icon_grid [data-testid="stButton"] button p {'
    '  font-family: icomoon, "Source Sans Pro", sans-serif;'
    "  font-size: 32px;"
    "}"
    '.st-key-icon_grid [data-testid="stButton"] button {'
    "  border: none;"
    "}"
    "</style>"
)

_GRID_COLS = 14
with st.container(key="icon_grid"):
    rows = [codepoints[i : i + _GRID_COLS] for i in range(0, len(codepoints), _GRID_COLS)]
    for row in rows:
        cols = st.columns(_GRID_COLS)
        for col, cp in zip(cols, row, strict=False):
            with col:
                if st.button(
                    chr(cp),
                    key=f"icon_{cp}",
                    help=f"U+{cp:04X}",
                    width="stretch",
                ):
                    st.session_state["icon_detail_cp"] = cp

    if "icon_detail_cp" in st.session_state:
        _show_icon_detail(st.session_state.pop("icon_detail_cp"))
