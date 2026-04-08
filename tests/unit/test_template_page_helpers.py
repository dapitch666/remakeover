"""Unit tests for pure helper functions used by the templates page."""

import json

from src.templates import (
    decode_icon_data,
    encode_svg_to_icon_data,
    expected_icon_dimensions,
    extract_template_meta_and_body,
    merge_multiselect_options,
    normalise_string_list,
    validate_svg_size,
)

_SVG_150x200 = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="150" height="200">'
    '<rect x="2" y="2" width="146" height="196"/>'
    "</svg>"
)


# ---------------------------------------------------------------------------
# _decode_icon_data
# ---------------------------------------------------------------------------


def test_decode_icon_data_valid_roundtrip():
    svg = "<svg/>"
    b64 = encode_svg_to_icon_data(svg)
    assert decode_icon_data(b64) == svg


def test_decode_icon_data_invalid_base64_returns_empty():
    assert decode_icon_data("!!!not-valid-base64!!!") == ""


def test_decode_icon_data_empty_string_returns_empty():
    assert decode_icon_data("") == ""


# ---------------------------------------------------------------------------
# _validate_svg_size
# ---------------------------------------------------------------------------


def test_validate_svg_size_correct():
    ok, msg = validate_svg_size(_SVG_150x200)
    assert ok
    assert msg == ""


def test_validate_svg_size_no_svg_tag():
    ok, msg = validate_svg_size("<html><body/></html>")
    assert not ok
    assert "svg" in msg.lower()


def test_validate_svg_size_missing_width():
    ok, msg = validate_svg_size('<svg height="200"></svg>')
    assert not ok
    assert "width" in msg.lower()


def test_validate_svg_size_missing_height():
    ok, msg = validate_svg_size('<svg width="150"></svg>')
    assert not ok
    assert "height" in msg.lower()


def test_validate_svg_size_wrong_dimensions():
    ok, msg = validate_svg_size('<svg width="100" height="100"></svg>')
    assert not ok
    assert "150" in msg and "200" in msg


def test_validate_svg_size_float_dimensions_accepted():
    ok, msg = validate_svg_size('<svg width="150.0" height="200.0"></svg>')
    assert ok
    assert msg == ""


def test_validate_svg_size_landscape_expected_dimensions():
    ok, msg = validate_svg_size('<svg width="200" height="150"></svg>', orientation="landscape")
    assert ok
    assert msg == ""


def test_expected_icon_dimensions_portrait_and_landscape():
    assert expected_icon_dimensions("portrait") == (150, 200)
    assert expected_icon_dimensions("landscape") == (200, 150)


# ---------------------------------------------------------------------------
# _extract_meta_and_body
# ---------------------------------------------------------------------------


def test_extract_meta_and_body_invalid_json_returns_original():
    meta, body = extract_template_meta_and_body("{bad json")
    assert meta == {}
    assert body == "{bad json"


def test_extract_meta_and_body_non_dict_returns_empty_meta():
    meta, body = extract_template_meta_and_body("[1, 2, 3]")
    assert meta == {}
    assert body == "[1, 2, 3]"


def test_extract_meta_and_body_splits_meta_from_body():
    src = json.dumps({"name": "T", "orientation": "portrait", "constants": [], "items": []})
    meta, body = extract_template_meta_and_body(src)
    assert meta.get("name") == "T"
    assert meta.get("orientation") == "portrait"
    body_parsed = json.loads(body)
    assert "name" not in body_parsed
    assert "constants" in body_parsed
    assert "items" in body_parsed


def test_extract_meta_and_body_empty_object():
    meta, body = extract_template_meta_and_body("{}")
    assert meta == {}
    body_parsed = json.loads(body)
    assert body_parsed == {}


def test_extract_meta_and_body_only_meta_fields():
    src = json.dumps({"name": "T", "author": "me", "categories": ["Lines"]})
    meta, body = extract_template_meta_and_body(src)
    assert meta == {"name": "T", "author": "me", "categories": ["Lines"]}
    body_parsed = json.loads(body)
    assert body_parsed == {}


def test_normalise_string_list_deduplicates_and_filters_empty():
    value = ["A", "  B  ", "A", "", " "]
    assert normalise_string_list(value) == ["A", "B"]


def test_normalise_string_list_from_csv():
    assert normalise_string_list("A, B, , A") == ["A", "B"]


def test_merge_multiselect_options_preserves_order_and_uniqueness():
    merged = merge_multiselect_options(["A", "B"], ["B", "C"], [" ", "D"])
    assert merged == ["A", "B", "C", "D"]
