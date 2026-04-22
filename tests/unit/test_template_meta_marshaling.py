"""Tests for the pure metadata marshaling helpers in src/templates.py.

Each test maps to coercion logic originally in:
  _meta_to_session  (pages/templates.py) — now a thin wrapper around meta_to_dict
  _meta_from_session (pages/templates.py) — now a thin wrapper around meta_from_dict
"""

from src.templates import meta_from_dict, meta_to_dict

# ---------------------------------------------------------------------------
# meta_to_dict — orientation normalization
# (pages/templates.py:273–278)
# ---------------------------------------------------------------------------


def test_meta_to_dict_lowercases_portrait_orientation():
    assert meta_to_dict({"orientation": "Portrait"})["orientation"] == "portrait"


def test_meta_to_dict_lowercases_landscape_orientation():
    assert meta_to_dict({"orientation": "LANDSCAPE"})["orientation"] == "landscape"


def test_meta_to_dict_rejects_invalid_orientation():
    assert meta_to_dict({"orientation": "sideways"})["orientation"] == "portrait"


def test_meta_to_dict_missing_orientation_defaults_to_portrait():
    assert meta_to_dict({})["orientation"] == "portrait"


def test_meta_to_dict_accepts_legacy_orientations_key():
    # _meta_to_session line 273: meta.get("orientation") or meta.get("orientations")
    assert meta_to_dict({"orientations": "landscape"})["orientation"] == "landscape"


def test_meta_to_dict_orientation_key_takes_precedence_over_orientations():
    result = meta_to_dict({"orientation": "portrait", "orientations": "landscape"})
    assert result["orientation"] == "portrait"


# ---------------------------------------------------------------------------
# meta_to_dict — author stripping
# (pages/templates.py:259)
# ---------------------------------------------------------------------------


def test_meta_to_dict_strips_author_whitespace():
    assert meta_to_dict({"author": "  Alice  "})["author"] == "Alice"


def test_meta_to_dict_all_whitespace_author_becomes_empty_string():
    assert meta_to_dict({"author": "   "})["author"] == ""


# ---------------------------------------------------------------------------
# meta_to_dict — categories and labels normalization
# (pages/templates.py:272, 282)
# ---------------------------------------------------------------------------


def test_meta_to_dict_deduplicates_categories():
    result = meta_to_dict({"categories": ["Lines", "Lines", "Grids"]})
    assert result["categories"] == ["Lines", "Grids"]


def test_meta_to_dict_strips_whitespace_from_category_entries():
    result = meta_to_dict({"categories": ["  Lines  ", "Grids"]})
    assert result["categories"] == ["Lines", "Grids"]


def test_meta_to_dict_deduplicates_labels():
    result = meta_to_dict({"labels": ["x", "y", "x"]})
    assert result["labels"] == ["x", "y"]


def test_meta_to_dict_filters_empty_label_entries():
    result = meta_to_dict({"labels": ["x", "", "  ", "y"]})
    assert result["labels"] == ["x", "y"]


# ---------------------------------------------------------------------------
# meta_from_dict — formatVersion coercion
# (pages/templates.py:294–301)
# ---------------------------------------------------------------------------


def test_meta_from_dict_coerces_format_version_string_to_int():
    result = meta_from_dict({"tpl_meta_format_version": "2"})
    assert result["formatVersion"] == 2
    assert isinstance(result["formatVersion"], int)


def test_meta_from_dict_coerces_format_version_int_passthrough():
    result = meta_from_dict({"tpl_meta_format_version": 3})
    assert result["formatVersion"] == 3
    assert isinstance(result["formatVersion"], int)


def test_meta_from_dict_invalid_format_version_falls_back_to_1():
    # pages/templates.py:300: except (TypeError, ValueError): fmt_ver = 1
    result = meta_from_dict({"tpl_meta_format_version": "not-a-number"})
    assert result["formatVersion"] == 1


def test_meta_from_dict_none_format_version_falls_back_to_1():
    result = meta_from_dict({"tpl_meta_format_version": None})
    assert result["formatVersion"] == 1


# ---------------------------------------------------------------------------
# meta_from_dict — empty categories fallback
# (pages/templates.py:289–290)
# ---------------------------------------------------------------------------


def test_meta_from_dict_empty_categories_falls_back_to_perso():
    result = meta_from_dict({"tpl_meta_categories": []})
    assert result["categories"] == ["Perso"]


def test_meta_from_dict_non_empty_categories_are_preserved():
    result = meta_from_dict({"tpl_meta_categories": ["Lines", "Grids"]})
    assert result["categories"] == ["Lines", "Grids"]


# ---------------------------------------------------------------------------
# meta_from_dict — author passthrough (no injection here)
# build_full_json injects "rm-manager" for empty author, not meta_from_dict
# (pages/templates.py:304 vs src/templates.py:150–151)
# ---------------------------------------------------------------------------


def test_meta_from_dict_empty_author_is_preserved_not_injected():
    result = meta_from_dict({"tpl_meta_author": ""})
    assert result["author"] == ""
