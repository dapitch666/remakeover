# reMarkable Template Format Specification


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
  "iconData": "PHN2ZyB4bWxu...",
  "labels": ["tag1", "tag2"],
  "constants": [...],
  "items": [...]
}
```

| Field | Type | Required | Description |
|---|---|----------|---|
| `name` | string | yes      | Display name of the template |
| `author` | string | yes      | Author name |
| `templateVersion` | string | yes      | Template schema version (e.g. `"1.0.0"`, `"2.0.0"`) |
| `formatVersion` | integer | yes      | File format version (`1`) |
| `categories` | array of strings | yes      | One or more category tags (see below) |
| `orientation` | string | yes      | `"portrait"` or `"landscape"` |
| `iconData` | string | yes      | Base64-encoded SVG used as the template icon on the device. |
| `labels` | array of strings | no       | Optional tags for filtering in rm-manager. Stored on the device but not displayed in the device UI. Defaults to `[]` if absent. |
| `constants` | array of objects | no       | Named values and expressions used throughout the template |
| `items` | array of item objects | yes      | Top-level list of graphical elements |


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
| `strokeWidth` | number | no | Line width in px (default: `1`). Use `0` to suppress the stroke entirely on filled shapes. Decimal values (e.g. `0.5`) are valid. |
| `strokeColor` | string\|null | no | Stroke color as hex string (`"#RRGGBB"` or `"#RRGGBBAA"`). `null` disables the stroke. |
| `fillColor` | string\|null | no | Fill color as hex string (`"#RRGGBB"` or `"#RRGGBBAA"`, e.g. `"#ffffff"`). `null` or absent means no fill. |
| `antialiasing` | boolean | no | When `false`, disables anti-aliasing for the path. Defaults to `true`. |

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

`position.x` and `position.y` accept number literals or expression strings. The built-in `textWidth` variable can be used in `position.x` to center-align text.

> **Fixed rendering properties:** The local SVG renderer always renders text with `fill="#000000"` (black) and `font-family="sans-serif"`. These properties cannot be customized via the template JSON.

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
| `columns` | `"left"` | Repeat leftward until the canvas left edge is reached |
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
| Comparison | `>`, `<`, `>=`, `<=`, `==`, `!=` |
| Boolean (JS-style) | `&&` (and), `\|\|` (or) |
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

## On-device storage

### Location

Templates are stored in the user's xochitl data directory on the device:

```
/home/root/.local/share/remarkable/xochitl/
```

### The template triplet

Each template is composed of exactly three files, collectively called a **triplet**, all sharing the same UUID stem:

| File | Role |
|---|---|
| `{UUID}.template` | Vector template definition (JSON, this spec) |
| `{UUID}.metadata` | xochitl metadata (JSON) |
| `{UUID}.content` | xochitl content descriptor (JSON) |

All three files must be present for xochitl to recognise the template.

#### `{UUID}.template`

A UTF-8 encoded JSON file following the format described in this document.

#### `{UUID}.metadata`

A UTF-8 encoded JSON file consumed by the device OS. Key fields:

```json
{
  "visibleName": "Template Name",
  "type": "TemplateType",
  "createdTime": "1712345678000",
  "lastModified": "1712345678000",
  "source": "com.remarkable.methods",
  "parent": "",
  "pinned": false,
  "new": false
}
```

| Field | Type | Description |
|---|---|---|
| `visibleName` | string | Display name shown in the device UI |
| `type` | string | Always `"TemplateType"` for templates |
| `createdTime` | string | Unix epoch timestamp in **milliseconds**, encoded as a string |
| `lastModified` | string | Unix epoch timestamp in **milliseconds**, encoded as a string |
| `source` | string | Origin identifier (e.g. `"com.remarkable.methods"`) |
| `parent` | string | Parent folder UUID; empty string for root |
| `pinned` | boolean | Whether the template is pinned |
| `new` | boolean | Internal flag used by xochitl |

> **Note:** `createdTime` and `lastModified` are integer values serialised as JSON strings, not JSON numbers.

#### `{UUID}.content`

A UTF-8 encoded JSON file. For custom templates this is typically an empty object:

```json
{}
```

### Thumbnails directory

xochitl may create a `{UUID}.thumbnails/` directory alongside the triplet to cache rendered previews. This directory is auto-generated and can be safely deleted; xochitl will recreate it on next startup.

### UUID

The UUID is a standard [RFC 4122 UUID v4](https://www.rfc-editor.org/rfc/rfc4122), rendered in lowercase hyphenated form:

```
3f2504e0-4f89-11d3-9a0c-0305e82c3301
```

The UUID is assigned when the template is first created and never changes. It acts as the shared key across all three files of the triplet and is used internally by xochitl to reference the template.

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
