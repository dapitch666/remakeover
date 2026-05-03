"""Device-level and application constants.

All paths and commands are relative to the reMarkable device filesystem.
Import from here rather than hard-coding strings in individual modules.
"""

# ---------------------------------------------------------------------------
# Remote filesystem paths
# ---------------------------------------------------------------------------

# Suspended / sleep-screen image shown when the device is locked.
# Stored in the user's home directory so it persists across firmware updates.
SUSPENDED_PNG_PATH = "/home/root/suspended.png"

# xochitl configuration file — holds the SleepScreenPath key that points
# xochitl to the custom sleep image and disables the image carousel.
XOCHITL_CONF_PATH = "/home/root/.config/remarkable/xochitl.conf"

# rmMethods template storage directory (persists across firmware updates)
REMOTE_XOCHITL_DATA_DIR = "/home/root/.local/share/remarkable/xochitl"

# Manifest filename stored alongside templates on the device
REMOTE_MANIFEST_FILENAME = ".manifest.json"

# ---------------------------------------------------------------------------
# Remote commands
# ---------------------------------------------------------------------------

# Restart the main reMarkable UI process to apply changes
CMD_RESTART_XOCHITL = "systemctl restart xochitl"

# Read the hardware board identifier (e.g. "reMarkable 2.0", "ferrari")
CMD_READ_MACHINE = "cat /sys/devices/soc0/machine"

# Extract the firmware version line from os-release
CMD_READ_FIRMWARE = "grep IMG_VERSION /etc/os-release"

# Check whether SleepScreenPath is configured; add it under [General] if not.
# Outputs 'already_set' or 'just_set' so the caller knows whether a restart is needed.
CMD_CHECK_OR_SET_SLEEP_SCREEN = (
    f"if grep -q '^SleepScreenPath=' {XOCHITL_CONF_PATH}; "
    f"then echo 'already_set'; "
    f"else sed -i '/^\\[General\\]/a SleepScreenPath={SUSPENDED_PNG_PATH}' {XOCHITL_CONF_PATH}"
    f" && echo 'just_set'; fi"
)

# Check whether SleepScreenPath is configured in xochitl.conf
CMD_CHECK_SLEEP_SCREEN = f"grep -q '^SleepScreenPath=' {XOCHITL_CONF_PATH} && echo yes || echo no"

# Remove SleepScreenPath from xochitl.conf
CMD_REMOVE_SLEEP_SCREEN = f"sed -i '/^SleepScreenPath=/d' {XOCHITL_CONF_PATH}"

# Delete the suspended.png image file from the device
CMD_DELETE_SUSPENDED_PNG = f"rm -f {SUSPENDED_PNG_PATH}"

# ---------------------------------------------------------------------------
# Device catalogue
# ---------------------------------------------------------------------------

DEVICE_SIZES = {
    "reMarkable 1": (1404, 1872),
    "reMarkable 2": (1404, 1872),
    "reMarkable Paper Pro": (1620, 2160),
    "reMarkable Paper Pro Move": (954, 1696),
}
DEFAULT_DEVICE_TYPE: str = "reMarkable Paper Pro"

# Maps the substring found in /sys/devices/soc0/machine to the canonical device type name.
# The kernel machine string is the full board description (e.g. "Freescale i.MX7 Dual reMarkable 2"),
# so keys are matched as substrings of the lowercased raw value.
MACHINE_TO_DEVICE_TYPE: dict[str, str] = {
    "remarkable 1": "reMarkable 1",
    "remarkable 2": "reMarkable 2",
    "ferrari": "reMarkable Paper Pro",
    "chiappa": "reMarkable Paper Pro Move",
}

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
