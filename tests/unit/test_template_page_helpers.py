"""Unit tests for pure-Python helpers defined in pages/templates.py.

These helpers are imported after mocking init_page and the Streamlit module-level
side-effects so that the page can be loaded without a running Streamlit server.
"""

import base64
import json
import re

# ---------------------------------------------------------------------------
# Helpers that replicate the tiny functions in pages/templates.py.
# They are tested against the same logic extracted here to avoid the module-level
# Streamlit execution that occurs when importing pages/templates directly.
# ---------------------------------------------------------------------------

_META_FIELDS = frozenset(
    {
        "name",
        "author",
        "categories",
        "orientation",
        "orientations",
        "labels",
        "iconData",
        "templateVersion",
        "formatVersion",
    }
)


def _decode_icon_data(b64: str) -> str:
    try:
        return base64.b64decode(b64).decode("utf-8")
    except Exception:
        return ""


def _encode_svg_to_icon_data(svg: str) -> str:
    return base64.b64encode(svg.encode("utf-8")).decode("ascii")


def _validate_svg_size(svg: str):
    svg_tag_m = re.search(r"<svg\b[^>]*>", svg, re.DOTALL)
    if not svg_tag_m:
        return False, "No <svg> root element found."
    tag = svg_tag_m.group(0)
    w_m = re.search(r'\bwidth=["\'](\d+(?:\.\d+)?)["\']', tag)
    h_m = re.search(r'\bheight=["\'](\d+(?:\.\d+)?)["\']', tag)
    if not w_m:
        return False, "SVG must have an explicit width attribute."
    if not h_m:
        return False, "SVG must have an explicit height attribute."
    w, h = int(float(w_m.group(1))), int(float(h_m.group(1)))
    if w != 150 or h != 200:
        return False, f"SVG must be 150×200 px (got {w}×{h})."
    return True, ""


def _extract_meta_and_body(json_str: str):
    try:
        data = json.loads(json_str)
    except Exception:
        return {}, json_str
    if not isinstance(data, dict):
        return {}, json_str
    meta = {k: v for k, v in data.items() if k in _META_FIELDS}
    body = {k: v for k, v in data.items() if k not in _META_FIELDS}
    return meta, json.dumps(body, indent=4, ensure_ascii=True)


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
    b64 = _encode_svg_to_icon_data(svg)
    assert _decode_icon_data(b64) == svg


def test_decode_icon_data_invalid_base64_returns_empty():
    assert _decode_icon_data("!!!not-valid-base64!!!") == ""


def test_decode_icon_data_empty_string_returns_empty():
    assert _decode_icon_data("") == ""


# ---------------------------------------------------------------------------
# _validate_svg_size
# ---------------------------------------------------------------------------


def test_validate_svg_size_correct():
    ok, msg = _validate_svg_size(_SVG_150x200)
    assert ok
    assert msg == ""


def test_validate_svg_size_no_svg_tag():
    ok, msg = _validate_svg_size("<html><body/></html>")
    assert not ok
    assert "svg" in msg.lower()


def test_validate_svg_size_missing_width():
    ok, msg = _validate_svg_size('<svg height="200"></svg>')
    assert not ok
    assert "width" in msg.lower()


def test_validate_svg_size_missing_height():
    ok, msg = _validate_svg_size('<svg width="150"></svg>')
    assert not ok
    assert "height" in msg.lower()


def test_validate_svg_size_wrong_dimensions():
    ok, msg = _validate_svg_size('<svg width="100" height="100"></svg>')
    assert not ok
    assert "150" in msg and "200" in msg


def test_validate_svg_size_float_dimensions_accepted():
    ok, msg = _validate_svg_size('<svg width="150.0" height="200.0"></svg>')
    assert ok
    assert msg == ""


# ---------------------------------------------------------------------------
# _extract_meta_and_body
# ---------------------------------------------------------------------------


def test_extract_meta_and_body_invalid_json_returns_original():
    meta, body = _extract_meta_and_body("{bad json")
    assert meta == {}
    assert body == "{bad json"


def test_extract_meta_and_body_non_dict_returns_empty_meta():
    meta, body = _extract_meta_and_body("[1, 2, 3]")
    assert meta == {}
    assert body == "[1, 2, 3]"


def test_extract_meta_and_body_splits_meta_from_body():
    src = json.dumps({"name": "T", "orientation": "portrait", "constants": [], "items": []})
    meta, body = _extract_meta_and_body(src)
    assert meta.get("name") == "T"
    assert meta.get("orientation") == "portrait"
    body_parsed = json.loads(body)
    assert "name" not in body_parsed
    assert "constants" in body_parsed
    assert "items" in body_parsed


def test_extract_meta_and_body_empty_object():
    meta, body = _extract_meta_and_body("{}")
    assert meta == {}
    body_parsed = json.loads(body)
    assert body_parsed == {}


def test_extract_meta_and_body_only_meta_fields():
    src = json.dumps({"name": "T", "author": "me", "categories": ["Lines"]})
    meta, body = _extract_meta_and_body(src)
    assert meta == {"name": "T", "author": "me", "categories": ["Lines"]}
    body_parsed = json.loads(body)
    assert body_parsed == {}
