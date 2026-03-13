"""Internationalisation helpers.

English is the default / fallback language — msgids are English strings.
French translations live in ``locales/fr/LC_MESSAGES/rmmanager.po`` (.mo).

Usage in any Streamlit module::

    from src.i18n import _

    st.button(_("Save"))

Log messages must **not** be wrapped with ``_()`` — they are always English.
"""

import gettext
from pathlib import Path

import streamlit as st

_LOCALES_DIR = Path(__file__).parent.parent / "locales"
_DOMAIN = "rmmanager"
SUPPORTED_LANGUAGES = ("en", "fr")

# Cache compiled catalog objects (one per language, loaded on first use)
_catalogs: dict[str, gettext.NullTranslations] = {}


def _get_catalog(lang: str) -> gettext.NullTranslations:
    if lang not in _catalogs:
        if lang == "en":
            _catalogs[lang] = gettext.NullTranslations()
        else:
            try:
                _catalogs[lang] = gettext.translation(
                    _DOMAIN, localedir=_LOCALES_DIR, languages=[lang]
                )
            except FileNotFoundError:
                # Graceful fallback to English if .mo file is missing
                _catalogs[lang] = gettext.NullTranslations()
    return _catalogs[lang]


def get_language() -> str:
    """Return the active UI language for the current session (default: ``"en"``)."""
    return st.session_state.get("lang", "en")


def _(text: str) -> str:
    """Translate *text* to the current session language."""
    return _get_catalog(get_language()).gettext(text)
