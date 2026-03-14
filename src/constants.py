"""Device-level and application constants.

All paths and commands are relative to the reMarkable tablet filesystem.
Import from here rather than hard-coding strings in individual modules.
"""

import json

# ---------------------------------------------------------------------------
# Remote filesystem paths
# ---------------------------------------------------------------------------

# Suspended / sleep-screen image shown when the tablet is locked
SUSPENDED_PNG_PATH = "/usr/share/remarkable/suspended.png"

# Built-in templates directory (read-only on stock firmware)
REMOTE_TEMPLATES_DIR = "/usr/share/remarkable/templates"

# User-writable directory for custom templates
REMOTE_CUSTOM_TEMPLATES_DIR = "/home/root/templates"

# Carousel illustrations directory
REMOTE_CAROUSEL_DIR = "/usr/share/remarkable/carousel"

# Backup sub-folder for disabled carousel illustrations
REMOTE_CAROUSEL_BACKUP_DIR = "/usr/share/remarkable/carousel/backupIllustrations"

# Remote templates.json (inside REMOTE_TEMPLATES_DIR)
REMOTE_TEMPLATES_JSON = f"{REMOTE_TEMPLATES_DIR}/templates.json"

# ---------------------------------------------------------------------------
# Remote commands
# ---------------------------------------------------------------------------

# Restart the main reMarkable UI process to apply changes
CMD_RESTART_XOCHITL = "systemctl restart xochitl"

# Check whether `/` is currently mounted read-write
CMD_CHECK_RW = 'mount | grep "on / " | grep -q "(rw," && printf "writable" || printf "readonly"'

# Remount the root filesystem as read-write
CMD_REMOUNT_RW = "mount -o remount,rw /"

# Disable carousel: back up illustrations then clear the source folder
CMD_CAROUSEL_BACKUP_DIR = f"mkdir -p '{REMOTE_CAROUSEL_BACKUP_DIR}'"
CMD_CAROUSEL_DISABLE = (
    f"mv '{REMOTE_CAROUSEL_DIR}'/*.png '{REMOTE_CAROUSEL_BACKUP_DIR}/' 2>/dev/null || true"
)

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

# Number of columns in the image / template grid
GRID_COLUMNS = 5

# ---------------------------------------------------------------------------
# Template editor
# ---------------------------------------------------------------------------

# Default JSON used when creating a new template from scratch.
DEFAULT_TEMPLATE_JSON: str = json.dumps(
    {
        "name": "mytemplate",
        "author": "",
        "templateVersion": "1.0.0",
        "formatVersion": 1,
        "categories": ["Perso"],
        "orientation": "portrait",
        "constants": [{"marginLeft": 120}, {"lineSpacing": 62}],
        "items": [
            {
                "type": "group",
                "boundingBox": {
                    "x": 0,
                    "y": "lineSpacing",
                    "width": "templateWidth",
                    "height": "lineSpacing",
                },
                "repeat": {"rows": "down"},
                "children": [
                    {
                        "type": "path",
                        "data": ["M", "marginLeft", 0, "L", "parentWidth", 0],
                    }
                ],
            }
        ],
    },
    indent=2,
    ensure_ascii=False,
)
