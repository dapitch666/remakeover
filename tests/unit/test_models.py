"""Unit tests for src/models.py — Device dataclass."""

from src.constants import DEFAULT_DEVICE_TYPE, DEVICE_SIZES
from src.models import Device


class TestDeviceFromDict:
    def test_all_fields_populated(self):
        data = {
            "ip": "1.2.3.4",
            "password": "secret",
            "device_type": "reMarkable 2",
            "firmware_version": "3.5.2.1896",
            "preferred_image": "bg.png",
        }
        dev = Device.from_dict("MyTablet", data)
        assert dev.name == "MyTablet"
        assert dev.ip == "1.2.3.4"
        assert dev.password == "secret"
        assert dev.device_type == "reMarkable 2"
        assert dev.firmware_version == "3.5.2.1896"

    def test_sleep_screen_enabled_parsed(self):
        data = {
            "ip": "1.2.3.4",
            "password": "pw",
            "device_type": "reMarkable 2",
            "firmware_version": "3.5.2",
            "sleep_screen_enabled": True,
        }
        dev = Device.from_dict("T", data)
        assert dev.sleep_screen_enabled is True

    def test_sleep_screen_enabled_defaults_to_false(self):
        dev = Device.from_dict("T", {"ip": "1.2.3.4"})
        assert dev.sleep_screen_enabled is False

    def test_defaults_when_keys_missing(self):
        dev = Device.from_dict("T", {})
        assert dev.ip == ""
        assert dev.password == ""
        assert dev.device_type == ""
        assert dev.firmware_version == ""
        assert dev.sleep_screen_enabled is False

    def test_firmware_version_default_empty(self):
        dev = Device.from_dict("T", {"ip": "1.2.3.4"})
        assert dev.firmware_version == ""


class TestDeviceResolveType:
    def test_known_type_returned(self):
        dev = Device.from_dict("X", {"device_type": "reMarkable 2"})
        assert dev.resolve_type(DEVICE_SIZES, DEFAULT_DEVICE_TYPE) == "reMarkable 2"

    def test_unknown_type_returns_default(self):
        dev = Device.from_dict("X", {"device_type": "Alien Tablet"})
        assert dev.resolve_type(DEVICE_SIZES, DEFAULT_DEVICE_TYPE) == DEFAULT_DEVICE_TYPE

    def test_no_args_uses_constants(self):
        """Calling resolve_type() without arguments must not raise."""
        dev = Device.from_dict("X", {"device_type": "reMarkable Paper Pro"})
        assert dev.resolve_type() == "reMarkable Paper Pro"

    def test_no_args_unknown_type_returns_default(self):
        dev = Device.from_dict("X", {"device_type": "Unknown"})
        assert dev.resolve_type() == DEFAULT_DEVICE_TYPE


class TestDeviceSizeLookup:
    """Ensure the right (width, height) is resolved for each known device type."""

    def test_remarkable1_size(self):
        dev = Device.from_dict("X", {"device_type": "reMarkable 1"})
        assert DEVICE_SIZES[dev.resolve_type()] == (1404, 1872)

    def test_remarkable2_size(self):
        dev = Device.from_dict("X", {"device_type": "reMarkable 2"})
        assert DEVICE_SIZES[dev.resolve_type()] == (1404, 1872)

    def test_paper_pro_size(self):
        dev = Device.from_dict("X", {"device_type": "reMarkable Paper Pro"})
        assert DEVICE_SIZES[dev.resolve_type()] == (1620, 2160)

    def test_paper_pro_move_size(self):
        dev = Device.from_dict("X", {"device_type": "reMarkable Paper Pro Move"})
        assert DEVICE_SIZES[dev.resolve_type()] == (954, 1696)

    def test_unknown_type_falls_back_to_default_size(self):
        dev = Device.from_dict("X", {"device_type": "Unknown"})
        assert DEVICE_SIZES[dev.resolve_type()] == DEVICE_SIZES[DEFAULT_DEVICE_TYPE]
