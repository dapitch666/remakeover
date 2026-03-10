# reMarkable Template Format Specification

Format version: **1** (`"formatVersion": 1`)  
Template version: **1.0.0** (`"templateVersion": "1.0.0"`)

---

## Root Object

```json
{
  "name": "Template Name",
  "author": "reMarkable",
  "templateVersion": "1.0.0",
  "formatVersion": 1,
  "categories": ["Lines"],
  "orientation": "portrait",
  "supportedDevices": ["rm2", "rmPP"],
  "constants": [...],
  "items": [...]
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `name` | string | yes | Display name of the template |
| `author` | string | yes | Author name |
| `templateVersion` | string | yes | Template schema version (`"1.0.0"`) |
| `formatVersion` | integer | yes | File format version (`1`) |
| `categories` | array of strings | yes | One or more category tags (see below) |
| `orientation` | string | yes | `"portrait"` or `"landscape"` |
| `supportedDevices` | array of strings | no | Restricts template to specific devices (e.g. `["rm2", "rmPP"]`) |
| `constants` | array of objects | no | Named values and expressions used throughout the template |
| `items` | array of item objects | yes | Top-level list of graphical elements |

### Known categories

- `"Lines"`
- `"Grids"`
- `"Planners"`
- `"Creative"`

---

## Constants

`constants` is an array of single-key objects. Each object defines one named variable:

```json
"constants": [
  { "mobileMaxWidth": 1000 },
  { "boxSize": 55 },
  { "offsetX": "templateWidth / 2 - lineWidth / 2" },
  { "ypos": "templateWidth > mobileMaxWidth ? 240.7 : 120" }
]
```

- Values can be **numbers** (integers or floats) or **expression strings**.
- Expression strings support arithmetic operators (`+`, `-`, `*`, `/`), the ternary operator (`? :`), and parentheses.
- A constant can reference previously defined constants and built-in variables.

### Built-in variables

These are always available in any expression:

| Variable | Description |
|---|---|
| `templateWidth` | Total width of the template canvas |
| `templateHeight` | Total height of the template canvas |
| `parentWidth` | Width of the enclosing `group`'s `boundingBox` |
| `parentHeight` | Height of the enclosing `group`'s `boundingBox` |
| `paperOriginX` | X origin of the paper area (used for centering) |
| `textWidth` | Rendered width of the current `text` item's string |

---

## Items

`items` is a flat list at the top level, and also the `children` list inside a `group`. Three item types exist: `path`, `text`, and `group`.

All items support the optional `id` field:

```json
{ "id": "my-element", "type": "...", ... }
```

---

### `path`

Draws vector lines and shapes using SVG-like path commands.

```json
{
  "id": "my-path",
  "type": "path",
  "strokeWidth": 2,
  "strokeColor": "#000000",
  "fillColor": "#000000",
  "data": [
    "M", 0, 0,
    "L", "parentWidth", 0,
    "C", 5.8, 160, 7.3, 163, 9.3, 169.3,
    "Z"
  ]
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | yes | `"path"` |
| `data` | array | yes | Interleaved path commands and coordinate values |
| `strokeWidth` | number | no | Line width in px (default: `1`) |
| `strokeColor` | string | no | Stroke color as hex string (e.g. `"#000000"`) |
| `fillColor` | string | no | Fill color as hex string (e.g. `"#ffffff"`, `"#00000000"` for transparent) |

#### Path commands (`data` array)

Commands follow SVG conventions. Each command string is followed by its coordinate arguments. Coordinate values can be **numbers** or **expression strings**.

| Command | Arguments | Description |
|---|---|---|
| `"M"` | x, y | Move to absolute position (starts a sub-path) |
| `"L"` | x, y | Line to absolute position |
| `"C"` | x1, y1, x2, y2, x, y | Cubic Bézier curve (two control points + end point) |
| `"Z"` | *(none)* | Close path (line back to the last `M` point) |

**Example using expressions as coordinates:**

```json
"data": [
  "M", "templateWidth / 2 - lineWidth / 2", 0,
  "L", "parentWidth", 0
]
```

---

### `text`

Renders a static text label.

```json
{
  "id": "label",
  "type": "text",
  "text": "Monday",
  "fontSize": 32,
  "position": {
    "x": "xVerLine1 - dayColumnWidth / 2 - textWidth / 2",
    "y": "yDayLabel"
  }
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | yes | `"text"` |
| `text` | string | yes | The text string to display |
| `fontSize` | number | yes | Font size in px |
| `position` | object | yes | `{ "x": ..., "y": ... }` — coordinates relative to the parent container |

`position.x` and `position.y` accept number literals or expression strings. The built-in `textWidth` variable can be used in `position.x` to centre-align text.

---

### `group`

A container that positions, clips, and optionally repeats its children.

```json
{
  "id": "hlines",
  "type": "group",
  "boundingBox": {
    "x": "offsetX",
    "y": "offsetY",
    "width": "lineWidth",
    "height": "gridSize"
  },
  "repeat": {
    "rows": "down",
    "columns": "infinite"
  },
  "children": [ ...items... ]
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `type` | string | yes | `"group"` |
| `boundingBox` | object | yes | Position and size of the group |
| `repeat` | object | no | Repetition rules along rows and/or columns |
| `children` | array | yes | Nested items (`path`, `text`, or `group`) |

#### `boundingBox`

```json
"boundingBox": {
  "x": 0,
  "y": "offsetY",
  "width": "templateWidth",
  "height": "gridSize"
}
```

All four fields (`x`, `y`, `width`, `height`) accept number literals or expression strings. Coordinates are relative to the parent container. Inside a child item, `parentWidth` and `parentHeight` resolve to the `boundingBox`'s `width` and `height`.

#### `repeat`

Controls tiling of the group's bounding box across the canvas.

```json
"repeat": {
  "rows": "down",
  "columns": "infinite"
}
```

| Field | Values | Description |
|---|---|---|
| `rows` | integer | Repeat exactly N times downward |
| `rows` | `"down"` | Repeat downward until the canvas bottom is reached |
| `rows` | `"up"` | Repeat upward until the canvas top is reached |
| `rows` | `"infinite"` | Repeat in both vertical directions |
| `rows` | expression string | Number of repetitions from a constant/expression |
| `columns` | integer | Repeat exactly N times to the right |
| `columns` | `"right"` | Repeat rightward until the canvas right edge is reached |
| `columns` | `"infinite"` | Repeat in both horizontal directions |

Both `rows` and `columns` are optional. A group without `repeat` renders exactly once.

#### Nesting

Groups can be nested to arbitrary depth:

```json
{
  "type": "group",
  "boundingBox": { ... },
  "repeat": { "rows": 4 },
  "children": [
    {
      "type": "group",
      "boundingBox": { ... },
      "repeat": { "rows": 5 },
      "children": [
        { "type": "path", "data": [ ... ] }
      ]
    }
  ]
}
```

---

## Expression Language

Constants, coordinates, sizes, and positions all accept expression strings where a plain number is expected. Expressions are evaluated before rendering.

### Supported syntax

| Feature | Example |
|---|---|
| Arithmetic | `"templateWidth / 2 - boxSize"` |
| Ternary | `"templateWidth > mobileMaxWidth ? 240 : 120"` |
| Comparison | `>`, `<`, `>=`, `<=` |
| Parentheses | `"(templateWidth - timeColumnWidth) / 7"` |
| String literal (numeric) | `"-5"` (negative constant) |

Constants are referenced by name and can depend on previously declared constants:

```json
"constants": [
  { "mobileMaxWidth": 1000 },
  { "boxSize": 55 },
  { "offsetX": "templateWidth / 2 - boxSize / 2" },
  { "ypos": "templateWidth > mobileMaxWidth ? 699 : templateHeight / 2" }
]
```

---

## Complete minimal example

```json
{
  "name": "Simple Lines",
  "author": "reMarkable",
  "templateVersion": "1.0.0",
  "formatVersion": 1,
  "categories": ["Lines"],
  "orientation": "portrait",
  "constants": [
    { "lineSpacing": 62 },
    { "marginLeft": 120 }
  ],
  "items": [
    {
      "type": "group",
      "boundingBox": {
        "x": 0,
        "y": "lineSpacing",
        "width": "templateWidth",
        "height": "lineSpacing"
      },
      "repeat": { "rows": "down" },
      "children": [
        {
          "type": "path",
          "data": [ "M", "marginLeft", 0, "L", "parentWidth", 0 ]
        }
      ]
    }
  ]
}
```
