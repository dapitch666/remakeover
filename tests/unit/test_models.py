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
        assert dev.preferred_image == "bg.png"

    def test_defaults_when_keys_missing(self):
        dev = Device.from_dict("T", {})
        assert dev.ip == ""
        assert dev.password == ""
        assert dev.device_type == ""
        assert dev.firmware_version == ""
        assert dev.preferred_image is None

    def test_ignores_legacy_templates_carousel_keys(self):
        """Old config files with templates/carousel keys must not crash or set any attribute."""
        data = {"ip": "1.2.3.4", "password": "pw", "templates": False, "carousel": True}
        dev = Device.from_dict("T", data)
        assert not hasattr(dev, "templates")
        assert not hasattr(dev, "carousel")

    def test_firmware_version_default_empty(self):
        dev = Device.from_dict("T", {"ip": "1.2.3.4"})
        assert dev.firmware_version == ""


class TestDeviceToDict:
    def test_roundtrip(self):
        data = {
            "ip": "1.2.3.4",
            "password": "pw",
            "device_type": "reMarkable 2",
            "firmware_version": "3.5.2.1896",
        }
        dev = Device.from_dict("X", data)
        assert dev.to_dict() == data

    def test_firmware_version_roundtrip(self):
        dev = Device.from_dict("X", {"firmware_version": "3.14.0"})
        assert dev.to_dict()["firmware_version"] == "3.14.0"

    def test_no_templates_carousel_in_output(self):
        dev = Device.from_dict("X", {})
        d = dev.to_dict()
        assert "templates" not in d
        assert "carousel" not in d

    def test_preferred_image_included_when_set(self):
        dev = Device.from_dict("X", {})
        dev.set_preferred("my.png")
        assert dev.to_dict()["preferred_image"] == "my.png"

    def test_preferred_image_omitted_when_none(self):
        dev = Device.from_dict("X", {})
        assert "preferred_image" not in dev.to_dict()


class TestDevicePreferredImage:
    def test_is_preferred_true(self):
        dev = Device.from_dict("X", {"preferred_image": "img.png"})
        assert dev.is_preferred("img.png") is True

    def test_is_preferred_false_different_name(self):
        dev = Device.from_dict("X", {"preferred_image": "img.png"})
        assert dev.is_preferred("other.png") is False

    def test_is_preferred_false_when_none(self):
        dev = Device.from_dict("X", {})
        assert dev.is_preferred("img.png") is False

    def test_set_preferred_updates_name(self):
        dev = Device.from_dict("X", {})
        dev.set_preferred("bg.png")
        assert dev.preferred_image == "bg.png"

    def test_set_preferred_none_clears(self):
        dev = Device.from_dict("X", {"preferred_image": "bg.png"})
        dev.set_preferred(None)
        assert dev.preferred_image is None


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
