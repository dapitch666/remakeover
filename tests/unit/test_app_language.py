"""Unit tests for language URL normalization in app.py."""

import pytest

from app import _normalize_lang_value


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("en", "en"),
        ("fr", "fr"),
        ("EN", "en"),
        ("Fr", "fr"),
        ("  fr  ", "fr"),
        (None, None),
        ("", None),
        ("de", None),
        ("🇩🇪 Deutsch", None),
    ],
)
def test_normalize_lang_value(raw, expected):
    assert _normalize_lang_value(raw) == expected
