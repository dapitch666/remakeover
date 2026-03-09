"""icomoon font extraction from the reMarkable xochitl binary.

The icomoon TrueType font is compiled into the xochitl binary via the Qt resource
system, compressed with zstd (Qt 6 default).  This module locates and extracts it,
caches it in static/icomoon.ttf (served via Streamlit static file serving), and
enumerates its Private Use Area codepoints.

The font is registered globally in .streamlit/config.toml via [[theme.fontFaces]],
so HTML snippets only need to reference font-family:"icomoon" without inlining
base64 font data.
"""

import io
import logging
import os

from src.ssh import download_file_ssh

# Resolved at import time — works regardless of cwd.
_REPO_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ICON_FONT_PATH = os.path.join(_REPO_DIR, "static", "icomoon.ttf")

logger = logging.getLogger(__name__)

REMOTE_XOCHITL = "/usr/bin/xochitl"
_ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"
_ICOMOON_FAMILY = b"icomoon"
# Template icon codes live in the 0xE960–0xEA10 range; require at least a handful.
_MIN_TEMPLATE_PUA = 20
_TEMPLATE_PUA_MIN_CP = 0xE960


def get_icon_font_path() -> str:
    """Return the local path to icomoon.ttf (served via Streamlit static file serving)."""
    return _ICON_FONT_PATH


def _all_pua_codepoints(font) -> set[int]:
    """Return all Private Use Area codepoints across ALL cmap tables in *font*."""
    cps: set[int] = set()
    for tbl in font["cmap"].tables:
        cps.update(cp for cp in tbl.cmap if 0xE000 <= cp <= 0xF8FF)
    return cps


def _extract_icomoon_ttf(data: bytes) -> bytes | None:
    """Scan *data* (xochitl binary) for the icomoon font compressed with zstd.

    Strategy:
    1. Quick-reject if no zstd magic bytes are present.
    2. For every zstd stream in the binary, try decompressing it.
    3. If the result is a valid TTF named "icomoon" that contains PUA codepoints
       in the template icon range (≥ 0xE960), keep the one with the most such
       codepoints and return it.
    """
    if _ZSTD_MAGIC not in data:
        logger.warning("No zstd streams found in xochitl binary")
        return None

    try:
        import zstandard as zstd_mod
        from fontTools.ttLib import TTFont
    except ImportError as e:
        logger.error("Missing dependency for font extraction: %s", e)
        return None

    dctx = zstd_mod.ZstdDecompressor()
    best_candidate: bytes | None = None
    best_pua_count = 0

    pos = 0
    while True:
        loc = data.find(_ZSTD_MAGIC, pos)
        if loc < 0:
            break
        pos = loc + 1

        try:
            dec = dctx.decompress(data[loc:], max_output_size=500_000)
        except Exception:
            continue

        # Must look like a TTF (0x00010000) or CFF (OTTO)
        if dec[:4] not in (b"\x00\x01\x00\x00", b"OTTO"):
            continue

        # Must be named "icomoon"
        if _ICOMOON_FAMILY not in dec:
            continue

        try:
            font = TTFont(io.BytesIO(dec), lazy=True)
            pua = _all_pua_codepoints(font)
            template_pua = [cp for cp in pua if cp >= _TEMPLATE_PUA_MIN_CP]
            if len(template_pua) >= _MIN_TEMPLATE_PUA and len(pua) > best_pua_count:
                best_pua_count = len(pua)
                best_candidate = dec
                logger.info(
                    "icomoon candidate at offset %d: %d bytes, %d PUA glyphs (%d template-range)",
                    loc,
                    len(dec),
                    len(pua),
                    len(template_pua),
                )
        except Exception as e:
            logger.debug("TTFont parse failed for zstd candidate at %d: %s", loc, e)

    if best_candidate is None:
        logger.error("icomoon TTF not found in xochitl binary")
    return best_candidate


def fetch_icon_font(ip: str, password: str, device_name: str) -> tuple[bool, str]:
    """Download /usr/bin/xochitl from *device_name*, extract the embedded icomoon TTF,
    and save it to static/icomoon.ttf.

    The xochitl binary is large (~50–100 MB); this is a one-time operation.
    Returns (ok, message).
    """
    logger.info("Downloading %s from %s …", REMOTE_XOCHITL, ip)
    try:
        xochitl_bytes = download_file_ssh(ip, password, REMOTE_XOCHITL)
    except Exception as e:
        return False, f"download_failed: {e}"

    ttf = _extract_icomoon_ttf(xochitl_bytes)
    if ttf is None:
        return False, "extraction_failed: icomoon TTF not found in xochitl"

    font_path = get_icon_font_path()
    try:
        with open(font_path, "wb") as f:
            f.write(ttf)
    except Exception as e:
        return False, f"write_failed: {e}"

    num_glyphs = len(get_icon_codepoints())
    logger.info("icomoon TTF saved at %s (%d bytes, %d glyphs)", font_path, len(ttf), num_glyphs)
    return True, f"ok ({len(ttf)} bytes, {num_glyphs} glyphs)"


def get_icon_codepoints() -> list[int]:
    """Return sorted PUA codepoints from the icomoon font."""
    try:
        from fontTools.ttLib import TTFont

        font = TTFont(_ICON_FONT_PATH)
        return sorted(_all_pua_codepoints(font))
    except Exception as e:
        logger.error("get_icon_codepoints failed: %s", e)
        return []


# ---------------------------------------------------------------------------
# HTML rendering helpers (no Streamlit dependency)
# ---------------------------------------------------------------------------

# Layout/visual CSS for the icon grid and preview widgets.
# The icomoon @font-face is registered globally via [[theme.fontFaces]] in
# .streamlit/config.toml, so it is NOT inlined here.
_ICON_CSS = (
    "<style>"
    ".icg{display:flex;flex-wrap:wrap;gap:8px;padding:4px 0 12px 0;}"
    ".icc{display:flex;flex-direction:column;align-items:center;"
    "justify-content:center;width:72px;height:72px;border-radius:8px;"
    "cursor:pointer;transition:background .12s,border-color .12s;"
    "user-select:none;text-decoration:none;}"
    ".icc:hover{background:#f0f4ff!important;border-color:#4895ef!important;}"
    '.icg-glyph{font-family:"icomoon",sans-serif;font-size:28px;line-height:1;}'
    ".icg-hex{font-size:9px;color:#888;font-family:monospace;margin-top:4px;}"
    '.icp{font-family:"icomoon",sans-serif;font-size:32px;line-height:1;}'
    "</style>"
)


def render_icon_grid_html(
    selected_cp: int | None = None,
    href_extra: str = "",
    clickable: bool = True,
) -> str:
    """Return an HTML icon-picker grid for all icomoon codepoints.

    When *clickable* is True each cell is an ``<a href="?icon=XXXX{href_extra}">``
    link.  When False, cells are plain ``<div>`` elements (no navigation on click),
    useful when page navigation would discard in-progress form state.
    Returns an empty string if the font has not yet been extracted.
    """
    codepoints = get_icon_codepoints()
    if not codepoints:
        return ""

    items = []
    for cp in codepoints:
        hex_str = f"{cp:04X}"
        is_sel = cp == selected_cp
        border = "2px solid #4895ef" if is_sel else "1px solid #ddd"
        bg = "#ebf4ff" if is_sel else "#fff"
        if clickable:
            items.append(
                f'<a class="icc" href="?icon={hex_str}{href_extra}" target="_parent"'
                f' title="U+{hex_str}" style="border:{border};background:{bg};color:black;">'
                f'<span class="icg-glyph">{chr(cp)}</span>'
                f'<span class="icg-hex">{hex_str}</span>'
                f"</a>"
            )
        else:
            items.append(
                f'<div class="icc" title="U+{hex_str}"'
                f' style="border:{border};background:{bg};cursor:default;">'
                f'<span class="icg-glyph">{chr(cp)}</span>'
                f'<span class="icg-hex">{hex_str}</span>'
                f"</div>"
            )
    return f'{_ICON_CSS}<div class="icg">{"".join(items)}</div>'


def render_icon_link_html(icon_code: str, href: str) -> str:
    """Render a small clickable icon button using the icomoon font.

    Clicking navigates to *href* (target="_parent" is set automatically).
    """
    if not icon_code:
        return ""
    cp = ord(icon_code[0])
    hex_str = f"{cp:04X}"
    return (
        f"{_ICON_CSS}"
        f'<a href="{href}" target="_parent"'
        f' title="U+{hex_str} \u2014 cliquer pour modifier l\'icône"'
        f' style="display:inline-flex;align-items:center;justify-content:center;'
        f"width:36px;height:36px;"
        f"text-decoration:none;background:#fff;cursor:pointer;"
        f'transition:background .12s,border-color .12s;">'
        f'<span style="font-family:icomoon,sans-serif;font-size:20px;'
        f'line-height:1;color:#444;">{icon_code[0]}</span>'
        f"</a>"
    )


def render_icon_preview_html(icon_code: str) -> str:
    """Return a tiny HTML snippet rendering a single icomoon glyph plus its hex code."""
    if not icon_code:
        return ""
    cp = ord(icon_code[0])
    hex_str = f"{cp:04X}"
    return (
        f"{_ICON_CSS}"
        f'<div style="display:flex;align-items:center;gap:8px;">'
        f'<span class="icp">{icon_code[0]}</span>'
        f'<span style="font-size:11px;color:#888;font-family:monospace;">U+{hex_str}</span>'
        f"</div>"
    )
