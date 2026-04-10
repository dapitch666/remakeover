"""Unit tests for src/template_renderer.py.

Covers: expression evaluator (including security sandbox), path builder,
color parser, item renderers, repeat logic, public API, and SVG output helpers.
"""

import base64
import json

import pytest

# noinspection PyProtectedMember
from src.template_renderer import (
    _build_ctx,
    _build_path_d,
    _calc_offsets,
    _eval_expr,
    _js_to_python,
    _linear_offsets,
    _parse_color,
    _render_group,
    _render_path,
    _render_text,
    render_template_json_str,
    render_template_to_svg,
    svg_as_img_tag,
)

# ---------------------------------------------------------------------------
# _js_to_python
# ---------------------------------------------------------------------------


class TestJsToPython:
    def test_logical_or(self):
        assert "or" in _js_to_python("a || b")

    def test_logical_and(self):
        assert "and" in _js_to_python("a && b")

    def test_ternary(self):
        result = _js_to_python("x > 0 ? x : 0")
        assert "if" in result and "else" in result

    def test_no_ternary_unchanged_structure(self):
        result = _js_to_python("1 + 2")
        assert "if" not in result

    def test_combined(self):
        result = _js_to_python("a && b ? a : b")
        assert "and" in result
        assert "if" in result


# ---------------------------------------------------------------------------
# _eval_expr
# ---------------------------------------------------------------------------


class TestEvalExpr:
    def test_int_value(self):
        assert _eval_expr(5, {}) == 5.0

    def test_float_value(self):
        assert _eval_expr(3.14, {}) == pytest.approx(3.14)

    def test_numeric_string(self):
        assert _eval_expr("42.5", {}) == pytest.approx(42.5)

    def test_negative_numeric_string(self):
        assert _eval_expr("-7", {}) == pytest.approx(-7.0)

    def test_variable_lookup(self):
        assert _eval_expr("x", {"x": 10.0}) == pytest.approx(10.0)

    def test_arithmetic(self):
        assert _eval_expr("x + 2", {"x": 3.0}) == pytest.approx(5.0)

    def test_multiplication(self):
        assert _eval_expr("templateWidth * 0.5", {"templateWidth": 1404.0}) == pytest.approx(702.0)

    def test_ternary_true_branch(self):
        assert _eval_expr("x > 0 ? x : 0", {"x": 5.0}) == pytest.approx(5.0)

    def test_ternary_false_branch(self):
        assert _eval_expr("x > 0 ? x : 0", {"x": -1.0}) == pytest.approx(0.0)

    def test_ternary_js_style(self):
        # Raw JS ternary should be converted before evaluation
        result = _eval_expr("x > 10 ? 1 : 2", {"x": 20.0})
        assert result == pytest.approx(1.0)

    def test_unknown_variable_returns_zero(self):
        assert _eval_expr("undeclared", {}) == 0.0

    def test_non_string_non_numeric_returns_zero(self):
        assert _eval_expr(None, {}) == 0.0
        assert _eval_expr([], {}) == 0.0

    def test_malformed_expression_returns_zero(self):
        assert _eval_expr("1 + + + +", {}) == 0.0

    # Security: blocked AST nodes must return 0 (not raise, not execute)
    def test_call_node_blocked(self):
        assert _eval_expr("__import__('os')", {}) == 0.0

    def test_attribute_node_blocked(self):
        assert _eval_expr("x.y", {"x": 1}) == 0.0

    def test_subscript_node_blocked(self):
        assert _eval_expr("x[0]", {"x": [1, 2]}) == 0.0

    def test_lambda_blocked(self):
        assert _eval_expr("lambda: 42", {}) == 0.0

    def test_no_builtins_leaked(self):
        # open, print, exec … should all return 0.0
        assert _eval_expr("open('x')", {}) == 0.0


# ---------------------------------------------------------------------------
# _build_ctx
# ---------------------------------------------------------------------------


class TestBuildCtx:
    def test_builtins_present(self):
        ctx = _build_ctx({}, 1404, 1872)
        assert ctx["templateWidth"] == 1404.0
        assert ctx["templateHeight"] == 1872.0
        assert ctx["parentWidth"] == 1404.0
        assert ctx["parentHeight"] == 1872.0

    def test_constants_evaluated(self):
        template = {"constants": [{"margin": 120}, {"half": "templateWidth * 0.5"}]}
        ctx = _build_ctx(template, 1404, 1872)
        assert ctx["margin"] == 120.0
        assert ctx["half"] == pytest.approx(702.0)

    def test_constant_can_reference_previous_constant(self):
        template = {"constants": [{"a": 10}, {"b": "a * 2"}]}
        ctx = _build_ctx(template, 1404, 1872)
        assert ctx["b"] == pytest.approx(20.0)

    def test_empty_template(self):
        ctx = _build_ctx({}, 100, 200)
        assert "templateWidth" in ctx


# ---------------------------------------------------------------------------
# _build_path_d
# ---------------------------------------------------------------------------


class TestBuildPathD:
    def test_move_line(self):
        d = _build_path_d(["M", 0, 0, "L", 100, 0], {})
        assert d.startswith("M 0.000 0.000")
        assert "L 100.000 0.000" in d

    def test_close_path(self):
        d = _build_path_d(["M", 0, 0, "Z"], {})
        assert "Z" in d

    def test_curve(self):
        d = _build_path_d(["M", 0, 0, "C", 10, 10, 20, 20, 30, 0], {})
        assert "C" in d

    def test_expression_coords(self):
        d = _build_path_d(
            ["M", "margin", 0, "L", "parentWidth", 0], {"margin": 50.0, "parentWidth": 400.0}
        )
        assert "M 50.000 0.000" in d
        assert "L 400.000 0.000" in d

    def test_unknown_command_skipped(self):
        # An unknown letter should not crash; known commands still render
        d = _build_path_d(["X", 0, "M", 0, 0, "L", 10, 10], {})
        assert "M 0.000 0.000" in d

    def test_empty_data(self):
        assert _build_path_d([], {}) == ""


# ---------------------------------------------------------------------------
# _parse_color
# ---------------------------------------------------------------------------


class TestParseColor:
    def test_rgb(self):
        rgb, alpha = _parse_color("#abc123")
        assert rgb == "#abc123"
        assert alpha == 1.0

    def test_rgb_shorthand(self):
        rgb, alpha = _parse_color("#abc")
        assert rgb == "#abc"
        assert alpha == 1.0

    def test_rgba_full_alpha(self):
        rgb, alpha = _parse_color("#abc123ff")
        assert rgb == "#abc123"
        assert alpha == pytest.approx(1.0)

    def test_rgba_half_alpha(self):
        _, alpha = _parse_color("#00000080")
        assert 0.49 < alpha < 0.51

    def test_rgba_zero_alpha(self):
        _, alpha = _parse_color("#00000000")
        assert alpha == pytest.approx(0.0)

    def test_no_hash(self):
        rgb, alpha = _parse_color("abc123")
        assert rgb == "#abc123"
        assert alpha == 1.0

    def test_bad_value_fallback(self):
        rgb, alpha = _parse_color("INVALID")
        assert rgb == "#000000"
        assert alpha == 1.0


# ---------------------------------------------------------------------------
# Item renderers
# ---------------------------------------------------------------------------


class TestRenderPath:
    _ctx = {
        "templateWidth": 1404.0,
        "templateHeight": 1872.0,
        "parentWidth": 1404.0,
        "parentHeight": 1872.0,
    }

    def test_basic_path(self):
        item = {"type": "path", "data": ["M", 0, 0, "L", 100, 0], "strokeColor": "#000000"}
        svg = _render_path(item, self._ctx)
        assert "<path" in svg
        assert 'stroke="#000000"' in svg

    def test_empty_data_returns_empty(self):
        item = {"type": "path", "data": []}
        assert _render_path(item, self._ctx) == ""

    def test_fill_color(self):
        item = {"type": "path", "data": ["M", 0, 0, "Z"], "fillColor": "#ff0000"}
        svg = _render_path(item, self._ctx)
        assert 'fill="#ff0000"' in svg

    def test_stroke_zero_alpha_becomes_none(self):
        item = {"type": "path", "data": ["M", 0, 0, "L", 10, 0], "strokeColor": "#00000000"}
        svg = _render_path(item, self._ctx)
        assert 'stroke="none"' in svg


class TestRenderText:
    _ctx = {
        "templateWidth": 1404.0,
        "templateHeight": 1872.0,
        "parentWidth": 1404.0,
        "parentHeight": 1872.0,
        "textWidth": 0.0,
    }

    def test_basic_text(self):
        item = {"type": "text", "text": "Hello", "position": {"x": 10, "y": 20}}
        svg = _render_text(item, self._ctx)
        assert "<text" in svg
        assert "Hello" in svg

    def test_special_chars_escaped(self):
        item = {"type": "text", "text": '<b>&"test"</b>', "position": {"x": 0, "y": 0}}
        svg = _render_text(item, self._ctx)
        assert "&lt;" in svg
        assert "&amp;" in svg
        assert "&quot;" in svg
        assert "<b>" not in svg


class TestRenderGroup:
    _ctx = {
        "templateWidth": 1404.0,
        "templateHeight": 1872.0,
        "parentWidth": 1404.0,
        "parentHeight": 1872.0,
    }

    def test_group_with_single_path(self):
        item = {
            "type": "group",
            "boundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
            "children": [{"type": "path", "data": ["M", 0, 0, "L", 100, 0]}],
        }
        parts = _render_group(item, self._ctx)
        assert len(parts) >= 1
        assert all("<g " in p for p in parts)

    def test_group_zero_size_empty(self):
        item = {
            "type": "group",
            "boundingBox": {"x": 0, "y": 0, "width": 0, "height": 0},
            "children": [{"type": "path", "data": ["M", 0, 0, "L", 10, 0]}],
        }
        assert _render_group(item, self._ctx) == []

    def test_group_no_children_empty(self):
        item = {
            "type": "group",
            "boundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
            "children": [],
        }
        assert _render_group(item, self._ctx) == []


# ---------------------------------------------------------------------------
# _linear_offsets and _calc_offsets
# ---------------------------------------------------------------------------


class TestLinearOffsets:
    def test_none_gives_single_zero(self):
        assert _linear_offsets(0, 50, None, 500) == [0.0]

    def test_integer_count(self):
        offsets = _linear_offsets(0, 50, 3, 500)
        assert offsets == [0.0, 50.0, 100.0]

    def test_down_fills_canvas(self):
        offsets = _linear_offsets(0, 100, "down", 500)
        # Should produce offsets 0, 100, 200, 300, 400 (pos=0+offset < 500)
        assert offsets[0] == 0.0
        assert all(o < 500 for o in offsets)
        assert 100.0 in offsets

    def test_up_goes_backward(self):
        offsets = _linear_offsets(200, 100, "up", 500)
        # Forward pass starts at pos=200; backward offsets should be negative
        assert any(o < 0 for o in offsets)

    def test_infinite_includes_both_directions(self):
        offsets = _linear_offsets(250, 50, "infinite", 500)
        assert any(o < 0 for o in offsets)
        assert any(o >= 0 for o in offsets)

    def test_right_alias_forward(self):
        offsets = _linear_offsets(0, 100, "right", 400)
        assert offsets[0] == 0.0
        assert all(o >= 0 for o in offsets)


class TestCalcOffsets:
    _ctx = {"templateWidth": 1404.0, "templateHeight": 1872.0}

    def test_no_repeat(self):
        offsets = _calc_offsets(0, 0, 100, 50, {}, self._ctx)
        assert offsets == [(0.0, 0.0)]

    def test_integer_rows(self):
        offsets = _calc_offsets(0, 0, 100, 50, {"rows": 3}, self._ctx)
        assert len(offsets) == 3

    def test_rows_and_cols(self):
        offsets = _calc_offsets(0, 0, 100, 50, {"rows": 2, "columns": 3}, self._ctx)
        assert len(offsets) == 6


# ---------------------------------------------------------------------------
# render_template_to_svg
# ---------------------------------------------------------------------------


class TestRenderTemplateToSvg:
    @staticmethod
    def _minimal(orientation="portrait") -> dict:
        return {"orientation": orientation, "constants": [], "items": []}

    def test_portrait_dimensions(self):
        svg = render_template_to_svg(self._minimal("portrait"))
        assert 'width="1404"' in svg
        assert 'height="1872"' in svg

    def test_landscape_dimensions(self):
        svg = render_template_to_svg(self._minimal("landscape"))
        assert 'width="1872"' in svg
        assert 'height="1404"' in svg

    def test_custom_portrait_canvas_dimensions(self):
        svg = render_template_to_svg(self._minimal("portrait"), canvas_portrait=(954, 1696))
        assert 'width="954"' in svg
        assert 'height="1696"' in svg

    def test_custom_landscape_canvas_dimensions_swapped(self):
        svg = render_template_to_svg(self._minimal("landscape"), canvas_portrait=(954, 1696))
        assert 'width="1696"' in svg
        assert 'height="954"' in svg

    def test_output_is_valid_svg_open_tag(self):
        svg = render_template_to_svg(self._minimal())
        assert svg.startswith("<svg ")
        assert svg.endswith("</svg>")

    def test_default_white_background_rect(self):
        svg = render_template_to_svg(self._minimal())
        assert 'fill="white"' in svg

    def test_path_item_rendered(self):
        template = {
            "orientation": "portrait",
            "constants": [],
            "items": [
                {"type": "path", "data": ["M", 0, 0, "L", 100, 100], "strokeColor": "#000000"}
            ],
        }
        svg = render_template_to_svg(template)
        assert "<path " in svg

    def test_text_item_rendered(self):
        template = {
            "orientation": "portrait",
            "constants": [],
            "items": [{"type": "text", "text": "Hello", "position": {"x": 10, "y": 20}}],
        }
        svg = render_template_to_svg(template)
        assert "<text " in svg
        assert "Hello" in svg

    def test_group_item_rendered(self):
        template = {
            "orientation": "portrait",
            "constants": [],
            "items": [
                {
                    "type": "group",
                    "boundingBox": {"x": 0, "y": 0, "width": 100, "height": 50},
                    "children": [{"type": "path", "data": ["M", 0, 0, "L", 100, 0]}],
                }
            ],
        }
        svg = render_template_to_svg(template)
        assert "<g " in svg

    def test_group_with_repeat_down_produces_multiple_groups(self):
        template = {
            "orientation": "portrait",
            "constants": [],
            "items": [
                {
                    "type": "group",
                    "boundingBox": {"x": 0, "y": 0, "width": 1404, "height": 100},
                    "repeat": {"rows": "down"},
                    "children": [{"type": "path", "data": ["M", 0, 0, "L", 100, 0]}],
                }
            ],
        }
        svg = render_template_to_svg(template)
        assert svg.count("<g ") > 1

    def test_constants_used_in_path(self):
        template = {
            "orientation": "portrait",
            "constants": [{"margin": 50}],
            "items": [
                {
                    "type": "path",
                    "data": ["M", "margin", 0, "L", 100, 0],
                    "strokeColor": "#000000",
                }
            ],
        }
        svg = render_template_to_svg(template)
        assert "M 50.000 0.000" in svg

    def test_missing_items_key(self):
        # Should not raise; just renders background
        svg = render_template_to_svg({"orientation": "portrait"})
        assert "<svg" in svg


# ---------------------------------------------------------------------------
# render_template_json_str
# ---------------------------------------------------------------------------


class TestRenderTemplateJsonStr:
    def test_valid_json_returns_svg_no_error(self):
        template = json.dumps({"orientation": "portrait", "constants": [], "items": []})
        svg, err = render_template_json_str(template)
        assert err is None
        assert "<svg" in svg

    def test_invalid_json_returns_error(self):
        svg, err = render_template_json_str("{not valid json}")
        assert svg == ""
        assert err is not None
        assert "JSON" in err or "json" in err.lower()

    def test_empty_string_returns_error(self):
        svg, err = render_template_json_str("")
        assert svg == ""
        assert err is not None

    def test_custom_canvas_dimensions_applied(self):
        template = json.dumps({"orientation": "portrait", "constants": [], "items": []})
        svg, err = render_template_json_str(template, canvas_portrait=(954, 1696))
        assert err is None
        assert 'width="954"' in svg
        assert 'height="1696"' in svg


# ---------------------------------------------------------------------------
# svg_as_img_tag
# ---------------------------------------------------------------------------


class TestSvgAsImgTag:
    @staticmethod
    def _simple_svg():
        return '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"></svg>'

    def test_output_contains_img_tag(self):
        tag = svg_as_img_tag(self._simple_svg())
        assert tag.startswith("<img ")

    def test_output_is_base64_data_uri(self):
        tag = svg_as_img_tag(self._simple_svg())
        assert "data:image/svg+xml;base64," in tag

    def test_base64_decodes_to_original(self):
        svg = self._simple_svg()
        tag = svg_as_img_tag(svg)
        # Extract the base64 portion
        b64 = tag.split("base64,")[1].split('"')[0]
        decoded = base64.b64decode(b64).decode("utf-8")
        assert decoded == svg

    def test_max_height_in_style(self):
        tag = svg_as_img_tag(self._simple_svg(), max_height=400)
        assert "400px" in tag

    def test_default_max_height(self):
        tag = svg_as_img_tag(self._simple_svg())
        assert "650px" in tag

    def test_max_width_in_style(self):
        tag = svg_as_img_tag(self._simple_svg(), max_width=954)
        assert "max-width:954px" in tag
