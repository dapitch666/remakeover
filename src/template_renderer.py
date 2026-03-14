"""Renderer for the reMarkable native template JSON format → SVG.

Supports the JSON vector template format used by modern reMarkable firmware.
Templates describe their geometry using mathematical expressions evaluated
against a set of named constants and built-in canvas variables.

Security note
-------------
Expression strings are evaluated with a restricted AST validator that
only permits arithmetic, comparison, boolean and ternary operations on
named constants and numeric literals.  ``__builtins__`` is emptied and
the AST is checked for any ``Call``, ``Attribute``, ``Subscript`` and
similar nodes before compilation, so user-supplied expressions cannot
escape the sandbox.
"""

from __future__ import annotations

import ast
import json
from typing import Any

# ---------------------------------------------------------------------------
# Canvas dimensions (pixels)
# ---------------------------------------------------------------------------

_PORTRAIT_W: int = 1404
_PORTRAIT_H: int = 1872
_LANDSCAPE_W: int = 1872
_LANDSCAPE_H: int = 1404

# Maximum instances per repeat direction (safety cap for "infinite")
_MAX_REPEAT: int = 60

# ---------------------------------------------------------------------------
# Expression evaluator
# ---------------------------------------------------------------------------

_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.BinOp,
    ast.UnaryOp,
    ast.Compare,
    ast.IfExp,
    ast.Constant,
    ast.Name,
    ast.Load,  # required: every Name node carries a Load context
    # Operators
    ast.And,
    ast.Or,
    ast.Not,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.USub,
    ast.UAdd,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)


def _js_to_python(expr: str) -> str:
    """Convert JS logical operators and ternary syntax to Python equivalents.

    Handles ``||``, ``&&``, and single-level ``cond ? then : else`` recursively
    so nested ternaries in the *then* or *else* branches are also converted.
    """
    expr = expr.replace("||", " or ").replace("&&", " and ")
    if "?" not in expr:
        return expr
    q = expr.index("?")
    cond = expr[:q].strip()
    rest = expr[q + 1 :]
    c = rest.index(":")
    then_expr = rest[:c].strip()
    else_expr = rest[c + 1 :].strip()
    return (
        f"({_js_to_python(then_expr)}) if ({_js_to_python(cond)}) else ({_js_to_python(else_expr)})"
    )


def _eval_expr(val: Any, ctx: dict[str, Any]) -> float:
    """Evaluate *val* as a numeric expression.

    *val* may be an ``int``, ``float``, or a string containing an arithmetic /
    comparison / ternary expression that references names from *ctx*.
    Returns ``0.0`` for anything that cannot be evaluated safely.
    """
    if isinstance(val, int | float):
        return float(val)
    if not isinstance(val, str):
        return 0.0
    # Fast path: pure numeric string (e.g. "-5", "78.3")
    try:
        return float(val)
    except ValueError:
        pass

    py_expr = _js_to_python(val.strip())
    try:
        tree = ast.parse(py_expr, mode="eval")
    except SyntaxError:
        return 0.0

    # Whitelist-validate every AST node
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            return 0.0

    try:
        result = eval(compile(tree, "<template_expr>", "eval"), {"__builtins__": {}}, ctx)  # noqa: S307
        return float(result)
    except Exception:
        return 0.0


def _build_ctx(template: dict[str, Any], canvas_w: float, canvas_h: float) -> dict[str, Any]:
    """Build the initial evaluation context from built-in variables and template constants."""
    ctx: dict[str, Any] = {
        "templateWidth": canvas_w,
        "templateHeight": canvas_h,
        "parentWidth": canvas_w,
        "parentHeight": canvas_h,
        "paperOriginX": 0.0,
        "textWidth": 0.0,
    }
    for entry in template.get("constants", []):
        if not isinstance(entry, dict):
            continue
        for k, v in entry.items():
            ctx[k] = _eval_expr(v, ctx) if isinstance(v, str) else float(v)
    return ctx


# ---------------------------------------------------------------------------
# SVG path builder
# ---------------------------------------------------------------------------

_PATH_ARGS: dict[str, int] = {"M": 2, "L": 2, "C": 6, "Z": 0}


def _build_path_d(data: list[Any], ctx: dict[str, Any]) -> str:
    """Convert a reMarkable path ``data`` array to an SVG ``d`` attribute string."""
    parts: list[str] = []
    i = 0
    while i < len(data):
        token = data[i]
        if token not in _PATH_ARGS:
            i += 1
            continue
        n = _PATH_ARGS[token]
        if token == "Z":
            parts.append("Z")
            i += 1
        else:
            coords = [_eval_expr(data[i + 1 + j], ctx) for j in range(n)]
            parts.append(f"{token} {' '.join(f'{c:.3f}' for c in coords)}")
            i += 1 + n
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Color helpers
# ---------------------------------------------------------------------------


def _parse_color(hex_color: str) -> tuple[str, float]:
    """Parse ``#RRGGBB`` or ``#RRGGBBAA`` to ``(rgb_hex, alpha_0_1)``."""
    c = hex_color.lstrip("#")
    if len(c) == 8:
        alpha = int(c[6:8], 16) / 255.0
        return f"#{c[:6]}", alpha
    if len(c) in (3, 6):
        return f"#{c}", 1.0
    return "#000000", 1.0


# ---------------------------------------------------------------------------
# Item renderers
# ---------------------------------------------------------------------------


def _render_path(item: dict[str, Any], ctx: dict[str, Any]) -> str:
    d = _build_path_d(item.get("data", []), ctx)
    if not d:
        return ""

    stroke, stroke_alpha = _parse_color(item.get("strokeColor", "#000000"))
    if stroke_alpha == 0.0:
        stroke = "none"

    fill = "none"
    if "fillColor" in item:
        fill_color, fill_alpha = _parse_color(item["fillColor"])
        fill = fill_color if fill_alpha > 0 else "none"

    sw = item.get("strokeWidth", 1)
    attrs = f'd="{d}" stroke="{stroke}" fill="{fill}" stroke-width="{sw}"'
    if 0.0 < stroke_alpha < 1.0:
        attrs += f' stroke-opacity="{stroke_alpha:.3f}"'
    return f"<path {attrs}/>"


def _render_text(item: dict[str, Any], ctx: dict[str, Any]) -> str:
    text = item.get("text", "")
    font_size = float(item.get("fontSize", 24))
    # Approximate text width for expressions that reference textWidth
    text_w = font_size * len(text) * 0.55
    child_ctx = {**ctx, "textWidth": text_w}

    pos = item.get("position", {})
    x = _eval_expr(pos.get("x", 0), child_ctx)
    y = _eval_expr(pos.get("y", 0), child_ctx)

    safe = (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )
    return (
        f'<text x="{x:.3f}" y="{y:.3f}" '
        f'font-size="{font_size}" font-family="sans-serif" fill="#000000">'
        f"{safe}</text>"
    )


def _render_group(item: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    bb = item.get("boundingBox", {})
    x = _eval_expr(bb.get("x", 0), ctx)
    y = _eval_expr(bb.get("y", 0), ctx)
    w = _eval_expr(bb.get("width", ctx.get("parentWidth", ctx["templateWidth"])), ctx)
    h = _eval_expr(bb.get("height", ctx.get("parentHeight", ctx["templateHeight"])), ctx)

    if w <= 0 or h <= 0:
        return []

    # Children see this group's dimensions as their parentWidth / parentHeight
    child_ctx = {**ctx, "parentWidth": w, "parentHeight": h}
    children_svg = [s for child in item.get("children", []) for s in _render_item(child, child_ctx)]
    if not children_svg:
        return []

    inner = "".join(children_svg)
    offsets = _calc_offsets(x, y, w, h, item.get("repeat", {}), ctx)
    return [
        f'<g transform="translate({x + dx:.3f},{y + dy:.3f})">{inner}</g>' for dx, dy in offsets
    ]


# ---------------------------------------------------------------------------
# Repeat helpers
# ---------------------------------------------------------------------------


def _eval_repeat_val(raw: Any, ctx: dict[str, Any]) -> int | str | None:
    """Coerce a raw repeat value to an integer count, a direction string, or None."""
    if raw is None:
        return None
    if isinstance(raw, str) and raw in ("down", "up", "infinite", "right", "left"):
        return raw
    if isinstance(raw, int | float):
        return max(1, int(raw))
    if isinstance(raw, str):
        v = _eval_expr(raw, ctx)
        return max(1, int(v)) if v > 0 else 1
    return None


def _linear_offsets(
    pos: float, size: float, val: int | str | None, canvas_size: float
) -> list[float]:
    """Return all delta offsets for one axis given a repeat directive value.

    ``val`` is one of:
    - ``None`` → single instance (delta = 0)
    - integer N → N instances spaced by ``size`` (forward only)
    - ``"down"`` / ``"right"`` → forward until canvas edge
    - ``"up"`` / ``"left"`` → backward until canvas edge (includes base instance)
    - ``"infinite"`` → forward + backward until both canvas edges
    """
    if val is None:
        return [0.0]

    if isinstance(val, int):
        return [i * size for i in range(val)]

    fwd: list[float] = []
    bwd: list[float] = []

    if val in ("down", "right", "infinite"):
        delta = 0.0
        for _ in range(_MAX_REPEAT):
            if pos + delta >= canvas_size:
                break
            fwd.append(delta)
            delta += size

    if val in ("up", "left", "infinite"):
        delta = size
        for _ in range(_MAX_REPEAT):
            # Stop when the bottom/right edge of the instance is at or above 0
            if pos - delta + size <= 0:
                break
            bwd.append(-delta)
            delta += size

    combined = bwd[::-1] + fwd
    return combined if combined else [0.0]


def _calc_offsets(
    x: float,
    y: float,
    w: float,
    h: float,
    repeat: dict[str, Any],
    ctx: dict[str, Any],
) -> list[tuple[float, float]]:
    """Return all ``(delta_x, delta_y)`` pairs for a group's repeat directive."""
    rows_val = _eval_repeat_val(repeat.get("rows"), ctx)
    cols_val = _eval_repeat_val(repeat.get("columns"), ctx)
    row_offsets = _linear_offsets(y, h, rows_val, ctx["templateHeight"])
    col_offsets = _linear_offsets(x, w, cols_val, ctx["templateWidth"])
    return [(dx, dy) for dy in row_offsets for dx in col_offsets]


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


def _render_item(item: dict[str, Any], ctx: dict[str, Any]) -> list[str]:
    t = item.get("type")
    if t == "path":
        s = _render_path(item, ctx)
        return [s] if s else []
    if t == "text":
        return [_render_text(item, ctx)]
    if t == "group":
        return _render_group(item, ctx)
    return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_template_to_svg(
    template_json: dict[str, Any],
    canvas_portrait: tuple[int, int] | None = None,
) -> str:
    """Render a reMarkable template JSON dict to a self-contained SVG string.

    ``canvas_portrait`` lets callers override the portrait canvas dimensions
    (``width, height``). Landscape orientation swaps this pair automatically.
    """
    orientation = template_json.get("orientation", "portrait")
    portrait_w, portrait_h = canvas_portrait or (_PORTRAIT_W, _PORTRAIT_H)
    cw, ch = (portrait_h, portrait_w) if orientation == "landscape" else (portrait_w, portrait_h)
    ctx = _build_ctx(template_json, float(cw), float(ch))
    elements = [s for item in template_json.get("items", []) for s in _render_item(item, ctx)]
    inner = "".join(elements)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg"'
        f' viewBox="0 0 {cw} {ch}" width="{cw}" height="{ch}">'
        f'<rect width="{cw}" height="{ch}" fill="white"/>'
        f"{inner}"
        f"</svg>"
    )


def render_template_json_str(
    json_str: str,
    canvas_portrait: tuple[int, int] | None = None,
) -> tuple[str, str | None]:
    """Parse *json_str* and render to SVG.

    Returns ``(svg_string, None)`` on success,
    or ``("", error_message)`` if parsing or rendering fails.
    """
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        return "", f"JSON invalide : {e}"
    try:
        return render_template_to_svg(data, canvas_portrait=canvas_portrait), None
    except Exception as e:
        return "", f"Erreur de rendu : {e}"


def svg_as_img_tag(svg: str, max_height: int = 650, max_width: int | None = None) -> str:
    """Return an ``<img>`` tag embedding *svg* as a base64 data URI.

    Using an ``<img>`` tag (rather than inline SVG) lets the browser derive
    the correct height from the viewBox aspect ratio automatically.
    """
    import base64

    b64 = base64.b64encode(svg.encode("utf-8")).decode()
    max_width_css = f"max-width:{max_width}px;" if max_width else ""
    return (
        f'<img src="data:image/svg+xml;base64,{b64}" '
        f'style="width:100%;{max_width_css}max-height:{max_height}px;object-fit:contain;'
        f'border:1px solid rgba(49,51,63,0.2);border-radius:6px;background:#ffffff;"/>'
    )
