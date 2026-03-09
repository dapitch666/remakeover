"""Unit tests for src/icon_font.py — HTML rendering helpers and codepoint lookup."""

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
