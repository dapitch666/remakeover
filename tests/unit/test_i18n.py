"""Unit tests for src/i18n.py."""

from unittest.mock import patch

import pytest

import src.i18n as i18n


@pytest.fixture(autouse=True)
def clear_catalog_cache():
    """Clear the module-level catalog cache between tests."""
    # noinspection PyProtectedMember
    i18n._catalogs.clear()
    yield
    # noinspection PyProtectedMember
    i18n._catalogs.clear()


class TestGetLanguage:
    def test_returns_en_by_default(self):
        with patch("streamlit.session_state", {}):
            assert i18n.get_language() == "en"

    def test_returns_session_language(self):
        with patch("streamlit.session_state", {"lang": "fr"}):
            assert i18n.get_language() == "fr"


class TestGetCatalog:
    def test_en_returns_null_translations(self):
        import gettext

        catalog = i18n._get_catalog("en")
        assert isinstance(catalog, gettext.NullTranslations)

    def test_en_is_cached(self):
        c1 = i18n._get_catalog("en")
        c2 = i18n._get_catalog("en")
        assert c1 is c2

    def test_fr_returns_gnu_translations(self):
        import gettext

        catalog = i18n._get_catalog("fr")
        assert isinstance(catalog, gettext.GNUTranslations)

    def test_fr_is_cached(self):
        c1 = i18n._get_catalog("fr")
        c2 = i18n._get_catalog("fr")
        assert c1 is c2

    def test_unknown_lang_falls_back_to_null_translations(self):
        import gettext

        catalog = i18n._get_catalog("de")
        assert isinstance(catalog, gettext.NullTranslations)


class TestTranslateFunction:
    def test_en_returns_original_string(self):
        with patch("streamlit.session_state", {"lang": "en"}):
            assert i18n._("Save") == "Save"

    def test_en_unknown_string_is_returned_as_is(self):
        with patch("streamlit.session_state", {"lang": "en"}):
            assert i18n._("Some unknown string xyz") == "Some unknown string xyz"

    def test_fr_translates_known_string(self):
        with patch("streamlit.session_state", {"lang": "fr"}):
            assert i18n._("Save") == "Sauvegarder"

    def test_fr_unknown_string_falls_back_to_msgid(self):
        with patch("streamlit.session_state", {"lang": "fr"}):
            assert (
                i18n._("Unknown string not in catalog xyz") == "Unknown string not in catalog xyz"
            )

    def test_fr_cancel(self):
        with patch("streamlit.session_state", {"lang": "fr"}):
            assert i18n._("Cancel") == "Annuler"

    def test_fr_confirm(self):
        with patch("streamlit.session_state", {"lang": "fr"}):
            assert i18n._("Confirm") == "Confirmer"
