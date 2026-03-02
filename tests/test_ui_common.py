"""Unit tests for src.ui_common helpers (Streamlit-free logic)."""

from src.ui_common import normalise_filename

# ---------------------------------------------------------------------------
# _normalise_filename
# ---------------------------------------------------------------------------


class TestNormaliseFilename:
    # ── spaces ───────────────────────────────────────────────────────────

    def test_spaces_replaced_by_underscores(self):
        assert normalise_filename("my file.png") == "my_file.png"

    def test_already_normalised_unchanged(self):
        assert normalise_filename("my_file.png") == "my_file.png"

    # ── extension handling (default .png) ────────────────────────────────

    def test_correct_extension_already_present(self):
        assert normalise_filename("photo.png") == "photo.png"

    def test_extension_is_case_insensitive(self):
        assert normalise_filename("photo.PNG") == "photo.PNG"

    def test_known_extension_swapped(self):
        result = normalise_filename("photo.jpg")
        assert result == "photo.png"

    def test_unknown_dot_in_name_preserved(self):
        """Dots inside a base name (e.g. 'alice.et.merlin') must not be stripped."""
        result = normalise_filename("alice.et.merlin")
        assert result == "alice.et.merlin.png"

    def test_no_extension_appended(self):
        assert normalise_filename("photo") == "photo.png"

    # ── custom extension ─────────────────────────────────────────────────

    def test_svg_extension(self):
        assert normalise_filename("icon", ext=".svg") == "icon.svg"

    def test_svg_already_present(self):
        assert normalise_filename("icon.svg", ext=".svg") == "icon.svg"

    def test_known_extension_swapped_to_svg(self):
        assert normalise_filename("icon.png", ext=".svg") == "icon.svg"
