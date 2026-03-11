"""Unit tests for src/icon_font.py — HTML rendering helpers and codepoint lookup."""

import os as _os
from unittest.mock import patch

import src.icon_font as icf

_FAKE_CPS = [0xE960, 0xE961, 0xE962]


# ---------------------------------------------------------------------------
# render_icon_grid_html
# ---------------------------------------------------------------------------


class TestRenderIconGridHtml:
    def test_returns_empty_when_no_codepoints(self):
        """Returns an empty string when the font has no codepoints."""
        with patch.object(icf, "get_icon_codepoints", return_value=[]):
            assert icf.render_icon_grid_html() == ""

    def test_contains_hex_string_for_each_codepoint(self):
        """Output contains the uppercase hex string for every codepoint."""
        with patch.object(icf, "get_icon_codepoints", return_value=_FAKE_CPS):
            html = icf.render_icon_grid_html()
        for cp in _FAKE_CPS:
            assert f"{cp:04X}" in html

    def test_selected_cp_uses_highlight_colour(self):
        """The selected codepoint cell uses the selection border colour."""
        with patch.object(icf, "get_icon_codepoints", return_value=_FAKE_CPS):
            html = icf.render_icon_grid_html(selected_cp=0xE960)
        assert "#4895ef" in html  # selection border colour defined in _ICON_CSS area

    def test_clickable_uses_anchor_tags(self):
        """When clickable=True, icon cells are rendered as <a> links."""
        with patch.object(icf, "get_icon_codepoints", return_value=_FAKE_CPS):
            html = icf.render_icon_grid_html(clickable=True)
        assert "<a " in html

    def test_non_clickable_uses_div_tags(self):
        """When clickable=False, icon cells are rendered as <div> elements."""
        with patch.object(icf, "get_icon_codepoints", return_value=_FAKE_CPS):
            html = icf.render_icon_grid_html(clickable=False)
        assert '<div class="icc"' in html
        assert "<a " not in html

    def test_href_extra_appended_to_links(self):
        """href_extra is appended to each icon link when clickable=True."""
        with patch.object(icf, "get_icon_codepoints", return_value=[0xE960]):
            html = icf.render_icon_grid_html(href_extra="&tpl_icon_for=alpha")
        assert "&tpl_icon_for=alpha" in html


# ---------------------------------------------------------------------------
# render_icon_link_html
# ---------------------------------------------------------------------------


class TestRenderIconLinkHtml:
    def test_returns_empty_for_empty_icon_code(self):
        """Empty icon code returns an empty string (no link rendered)."""
        assert icf.render_icon_link_html("", "?edit_icon=X") == ""

    def test_contains_href(self):
        """Rendered HTML contains the href passed to the function."""
        html = icf.render_icon_link_html("\ue960", "?edit_icon=alpha")
        assert "?edit_icon=alpha" in html

    def test_contains_hex_code_in_title(self):
        """Rendered HTML contains the uppercase hex representation of the codepoint."""
        html = icf.render_icon_link_html("\ue960", "?edit_icon=alpha")
        assert "E960" in html


# ---------------------------------------------------------------------------
# render_icon_preview_html
# ---------------------------------------------------------------------------


class TestRenderIconPreviewHtml:
    def test_returns_empty_for_empty_icon_code(self):
        """Empty icon code returns an empty string."""
        assert icf.render_icon_preview_html("") == ""

    def test_contains_hex_code(self):
        """Rendered HTML contains the uppercase hex code of the glyph."""
        html = icf.render_icon_preview_html("\ue960")
        assert "E960" in html

    def test_contains_glyph_character(self):
        """Rendered HTML contains the actual glyph character."""
        html = icf.render_icon_preview_html("\ue960")
        assert "\ue960" in html


# ---------------------------------------------------------------------------
# get_icon_codepoints
# ---------------------------------------------------------------------------


class TestGetIconCodepoints:
    def test_returns_empty_list_when_font_file_missing(self, tmp_path, monkeypatch):
        """Returns an empty list gracefully when the font file does not exist."""
        monkeypatch.setattr(icf, "_ICON_FONT_PATH", str(tmp_path / "nonexistent.ttf"))
        result = icf.get_icon_codepoints()
        assert result == []

    def test_returns_sorted_codepoints_from_real_font(self, monkeypatch):
        """Returns sorted PUA codepoints from the real static/icomoon.ttf fixture."""
        monkeypatch.setattr(icf, "_ICON_FONT_PATH", icf._ICON_FONT_PATH)
        result = icf.get_icon_codepoints()
        assert len(result) > 0
        assert result == sorted(result)
        assert all(0xE000 <= cp <= 0xF8FF for cp in result)


# ---------------------------------------------------------------------------
# _extract_icomoon_ttf
# ---------------------------------------------------------------------------

_REAL_TTF_PATH = _os.path.join(
    _os.path.dirname(_os.path.dirname(_os.path.dirname(__file__))), "static", "icomoon.ttf"
)


def _make_synthetic_xochitl(ttf_bytes: bytes) -> bytes:
    """Wrap *ttf_bytes* in a zstd frame and embed it in fake binary data."""
    import zstandard

    cctx = zstandard.ZstdCompressor()
    compressed = cctx.compress(ttf_bytes)
    return b"__fake_xochitl_header__" + compressed + b"__trailer__"


class TestExtractIcomoonTtf:
    def test_returns_none_when_no_zstd_magic(self):
        """Returns None immediately when the binary contains no zstd magic bytes."""
        result = icf._extract_icomoon_ttf(b"binary data without any zstd magic anywhere")
        assert result is None

    def test_extracts_font_from_synthetic_binary(self):
        """Extracts the icomoon TTF from a synthetic xochitl-like binary."""
        with open(_REAL_TTF_PATH, "rb") as f:
            ttf_bytes = f.read()
        synthetic = _make_synthetic_xochitl(ttf_bytes)
        result = icf._extract_icomoon_ttf(synthetic)
        assert result is not None
        # Returned bytes should be a valid TTF
        assert result[:4] == b"\x00\x01\x00\x00"
        # Should contain icomoon family name
        assert b"icomoon" in result

    def test_returns_none_when_zstd_decompresses_to_non_ttf(self):
        """Returns None when the zstd stream decompresses to non-TTF bytes."""
        import zstandard

        cctx = zstandard.ZstdCompressor()
        # Compress bytes that don't have a TTF/CFF magic header
        compressed = cctx.compress(b"this is not a truetype font at all")
        synthetic = b"prefix" + compressed + b"suffix"
        result = icf._extract_icomoon_ttf(synthetic)
        assert result is None

    def test_returns_none_when_ttf_lacks_icomoon_family_name(self):
        """Returns None when the decompressed TTF bytes lack 'icomoon' in them."""
        import zstandard

        with open(_REAL_TTF_PATH, "rb") as f:
            ttf_bytes = f.read()
        # Replace every occurrence of b"icomoon" with b"XXXXXXX" so the family check fails
        modified = ttf_bytes.replace(b"icomoon", b"notamoon")
        cctx = zstandard.ZstdCompressor()
        compressed = cctx.compress(modified)
        synthetic = b"prefix" + compressed + b"suffix"
        result = icf._extract_icomoon_ttf(synthetic)
        assert result is None

    def test_invalid_zstd_stream_is_skipped_gracefully(self):
        """Malformed zstd stream data after the magic bytes is skipped without raising."""
        # Embed the ZSTD magic followed by garbage — decompressor will raise, should be caught
        data = b"junk" + icf._ZSTD_MAGIC + b"\xff\xff\xff\xff\xff\xff\xff\xff" + b"more junk"
        result = icf._extract_icomoon_ttf(data)
        assert result is None

    def test_returns_none_when_pua_count_below_minimum(self):
        """Returns None when the font has too few template-range PUA codepoints."""
        # The real font easily has enough PUA codepoints; use a truncated/empty cmap replacement.
        # Easiest: patch _MIN_TEMPLATE_PUA to a very high value so no font can satisfy it.
        with open(_REAL_TTF_PATH, "rb") as f:
            ttf_bytes = f.read()
        synthetic = _make_synthetic_xochitl(ttf_bytes)
        original_min = icf._MIN_TEMPLATE_PUA
        try:
            icf._MIN_TEMPLATE_PUA = 99999  # impossibly high
            result = icf._extract_icomoon_ttf(synthetic)
        finally:
            icf._MIN_TEMPLATE_PUA = original_min
        assert result is None

    def test_returns_none_when_import_fails(self, monkeypatch):
        """Returns None gracefully when zstandard or fontTools cannot be imported."""
        import builtins

        real_import = builtins.__import__

        def fail_zstd(name, *args, **kwargs):
            if name == "zstandard":
                raise ImportError("No module named 'zstandard'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fail_zstd)
        # Need the magic present so the early-return check passes
        data = b"prefix" + icf._ZSTD_MAGIC + b"some_extra"
        result = icf._extract_icomoon_ttf(data)
        assert result is None

    def test_returns_none_when_ttffont_parse_fails(self):
        """Returns None when zstd bytes pass magic/family checks but TTFont parsing raises."""
        import zstandard

        # Bytes with TTF magic + 'icomoon' embedded but structurally invalid for TTFont
        fake = b"\x00\x01\x00\x00" + b"icomoon" + b"\xff" * 200
        cctx = zstandard.ZstdCompressor()
        compressed = cctx.compress(fake)
        synthetic = b"prefix" + compressed + b"suffix"
        result = icf._extract_icomoon_ttf(synthetic)
        assert result is None


# ---------------------------------------------------------------------------
# fetch_icon_font
# ---------------------------------------------------------------------------


class TestFetchIconFont:
    def test_returns_false_on_ssh_download_failure(self):
        """Returns (False, msg) when download_file_ssh fails."""
        with patch.object(icf, "download_file_ssh", return_value=(None, "connection refused")):
            ok, msg = icf.fetch_icon_font("192.168.1.1", "pass", "test_device")
        assert ok is False
        assert "download_failed" in msg
        assert "connection refused" in msg

    def test_returns_false_when_extraction_fails(self):
        """Returns (False, msg) when _extract_icomoon_ttf returns None."""
        with (
            patch.object(icf, "download_file_ssh", return_value=(b"binary_data", "")),
            patch.object(icf, "_extract_icomoon_ttf", return_value=None),
        ):
            ok, msg = icf.fetch_icon_font("192.168.1.1", "pass", "test_device")
        assert ok is False
        assert "extraction_failed" in msg

    def test_writes_font_file_and_returns_true(self, tmp_path, monkeypatch):
        """Writes the extracted TTF to disk and returns (True, msg)."""
        fake_ttf = b"\x00\x01\x00\x00" + b"\x00" * 100
        font_path = tmp_path / "icomoon.ttf"
        monkeypatch.setattr(icf, "_ICON_FONT_PATH", str(font_path))
        with (
            patch.object(icf, "download_file_ssh", return_value=(b"xochitl_binary", "")),
            patch.object(icf, "_extract_icomoon_ttf", return_value=fake_ttf),
            patch.object(icf, "get_icon_codepoints", return_value=[0xE960, 0xE961]),
        ):
            ok, msg = icf.fetch_icon_font("192.168.1.1", "pass", "test_device")
        assert ok is True
        assert "ok" in msg
        assert font_path.read_bytes() == fake_ttf

    def test_returns_false_on_write_error(self, tmp_path, monkeypatch):
        """Returns (False, msg) when writing the font file raises an exception."""
        fake_ttf = b"\x00\x01\x00\x00" + b"\x00" * 100
        # Point at a path inside a non-existent subdirectory so the write fails
        bad_path = tmp_path / "nonexistent_dir" / "icomoon.ttf"
        monkeypatch.setattr(icf, "_ICON_FONT_PATH", str(bad_path))
        with (
            patch.object(icf, "download_file_ssh", return_value=(b"xochitl_binary", "")),
            patch.object(icf, "_extract_icomoon_ttf", return_value=fake_ttf),
        ):
            ok, msg = icf.fetch_icon_font("192.168.1.1", "pass", "test_device")
        assert ok is False
        assert "write_failed" in msg
