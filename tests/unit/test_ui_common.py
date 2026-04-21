"""Unit tests for src/ui_common.py — Streamlit-free logic."""

from types import SimpleNamespace
from unittest.mock import patch

from src.ui_common import format_datetime_for_ui, normalise_filename


class TestNormaliseFilename:
    # ── spaces ───────────────────────────────────────────────────────────

    def test_spaces_are_preserved(self):
        assert normalise_filename("my file.png") == "my file.png"

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


# ---------------------------------------------------------------------------
# format_datetime_for_ui
# ---------------------------------------------------------------------------


class TestFormatDatetimeForUi:
    def test_returns_unknown_when_value_missing(self):
        result_date, result_time = format_datetime_for_ui(None)
        assert result_date == "Unknown"
        assert result_time == ""

    def test_formats_in_french_when_ui_language_is_french(self):
        with (
            patch("src.ui_common.st.context", SimpleNamespace(locale="fr", timezone="UTC")),
            patch("src.ui_common.get_language", return_value="fr"),
        ):
            result_date, result_time = format_datetime_for_ui("2026-04-08T13:30:00Z")
        assert "avr" in result_date.lower()
        assert result_time.endswith("13:30")

    def test_formats_in_english_when_ui_language_is_english(self):
        with (
            patch("src.ui_common.st.context", SimpleNamespace(locale="en", timezone="UTC")),
            patch("src.ui_common.get_language", return_value="en"),
        ):
            result_date, result_time = format_datetime_for_ui("2026-01-08T13:30:00Z")
        assert "Jan" in result_date
        assert result_time.endswith("13:30")

    def test_applies_timezone_conversion(self):
        with (
            patch(
                "src.ui_common.st.context", SimpleNamespace(locale="fr", timezone="Europe/Paris")
            ),
            patch("src.ui_common.get_language", return_value="fr"),
        ):
            result_date, result_time = format_datetime_for_ui("2026-04-08T12:30:00Z")
        assert "avr" in result_date.lower()
        assert result_time.endswith("14:30")

    def test_falls_back_to_language_when_context_locale_missing(self):
        with (
            patch("src.ui_common.st.context", SimpleNamespace(locale=None, timezone="UTC")),
            patch("src.ui_common.get_language", return_value="fr"),
        ):
            result_date, result_time = format_datetime_for_ui("2026-04-08T13:30:00Z")
        assert "avr" in result_date.lower()
        assert result_time.endswith("13:30")

    def test_forced_english_ui_overrides_french_context_locale(self):
        with (
            patch(
                "src.ui_common.st.context", SimpleNamespace(locale="fr", timezone="Europe/Paris")
            ),
            patch("src.ui_common.get_language", return_value="en"),
        ):
            result_date, result_time = format_datetime_for_ui("2026-04-08T12:30:00Z")
        assert "Apr" in result_date
        assert "avr" not in result_date.lower()
        assert result_time.endswith("14:30")

    def test_invalid_datetime_returns_original_value(self):
        raw = "not-a-date"
        assert format_datetime_for_ui(raw) == ("not-a-date", "")
