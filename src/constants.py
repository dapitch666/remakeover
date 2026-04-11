"""Device-level and application constants.

All paths and commands are relative to the reMarkable tablet filesystem.
Import from here rather than hard-coding strings in individual modules.
"""

# ---------------------------------------------------------------------------
# Remote filesystem paths
# ---------------------------------------------------------------------------

# Suspended / sleep-screen image shown when the tablet is locked
SUSPENDED_PNG_PATH = "/usr/share/remarkable/suspended.png"

# rmMethods template storage directory (persists across firmware updates)
REMOTE_XOCHITL_DATA_DIR = "/home/root/.local/share/remarkable/xochitl"

# Manifest filename stored alongside templates on the tablet
REMOTE_MANIFEST_FILENAME = ".manifest.json"

# ---------------------------------------------------------------------------
# Remote commands
# ---------------------------------------------------------------------------

# Restart the main reMarkable UI process to apply changes
CMD_RESTART_XOCHITL = "systemctl restart xochitl"

# Check whether `/` is currently mounted read-write
CMD_CHECK_RW = 'mount | grep "on / " | grep -q "(rw," && printf "writable" || printf "readonly"'

# Remount the root filesystem as read-write
CMD_REMOUNT_RW = "mount -o remount,rw /"

# ---------------------------------------------------------------------------
# Device catalogue
# ---------------------------------------------------------------------------

DEVICE_SIZES = {
    "reMarkable 2": (1404, 1872),
    "reMarkable Paper Pro": (1620, 2160),
    "reMarkable Paper Pro Move": (954, 1696),
}
DEFAULT_DEVICE_TYPE: str = "reMarkable Paper Pro"

# ---------------------------------------------------------------------------
# UI layout
# ---------------------------------------------------------------------------

# Number of columns in the image gallery
GRID_COLUMNS = 5

# ---------------------------------------------------------------------------
# Template editor
# ---------------------------------------------------------------------------

# Default base64-encoded SVG used for new templates with no icon.
DEFAULT_ICON_DATA = "PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIxNTAiIGhlaWdodD0iMjAwIiB2aWV3Qm94PSIwIDAgMTUwIDIwMCI+CiAgPHJlY3QgeD0iMiIgeT0iMiIgd2lkdGg9IjE0NiIgaGVpZ2h0PSIxOTYiIGZpbGw9Im5vbmUiIHN0cm9rZT0iYmxhY2siIHN0cm9rZS13aWR0aD0iNCIvPgo8L3N2Zz4="
DEFAULT_CATEGORIES = ["Perso"]

# Editor meta field constants
META_FIELDS = (
    "name",
    "author",
    "iconData",
    "templateVersion",
    "formatVersion",
    "categories",
    "labels",
    "orientation",
)


META_DEFAULTS: dict[str, str | list[str]] = {
    "tpl_meta_name": "",
    "tpl_meta_author": "",
    "tpl_meta_icon_data": DEFAULT_ICON_DATA,
    "tpl_meta_template_version": "1.0.0",
    "tpl_meta_format_version": "1",
    "tpl_meta_categories": DEFAULT_CATEGORIES,
    "tpl_meta_labels": [],
    "tpl_meta_orientation": "portrait",
}

# Default JSON used when creating a new template from scratch.
DEFAULT_TEMPLATE_JSON: str = """{
    "constants": [
        { "marginLeft": 120 },
        { "lineSpacing": 62 }
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
            "repeat": {
                "rows": "down"
            },
            "children": [
                {
                    "type": "path",
                    "data": [
                        "M", "marginLeft", 0,
                        "L", "parentWidth", 0
                    ]
                }
            ]
        }
    ]
}"""
