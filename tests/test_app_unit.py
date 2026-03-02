import src.config as config_mod
from src.config import (
    load_config,
    resolve_device_type,
    save_config,
    truncate_display_name,
)
from src.constants import DEFAULT_DEVICE_TYPE, DEVICE_SIZES
from src.models import Device

# ---------------------------------------------------------------------------
# truncate_display_name
# ---------------------------------------------------------------------------


class TestTruncateDisplayName:
    def test_short_name_unchanged(self):
        assert truncate_display_name("Anne") == "Anne"

    def test_exact_max_len_unchanged(self):
        s = "A" * 13  # default max_len
        assert truncate_display_name(s) == s

    def test_long_name_is_truncated(self):
        res = truncate_display_name("A" * 20, max_len=10)
        assert res.endswith("...")
        assert len(res) == 10

    def test_non_string_is_cast(self):
        assert truncate_display_name(123) == "123"

    def test_empty_string(self):
        assert truncate_display_name("") == ""


# ---------------------------------------------------------------------------
# Device catalogue constants
# ---------------------------------------------------------------------------


class TestDeviceSizes:
    def test_has_expected_models(self):
        assert "reMarkable 2" in DEVICE_SIZES
        assert "reMarkable Paper Pro" in DEVICE_SIZES
        assert "reMarkable Paper Pro Move" in DEVICE_SIZES

    def test_sizes_are_tuples_of_ints(self):
        for _model, size in DEVICE_SIZES.items():
            assert isinstance(size, tuple) and len(size) == 2
            assert all(isinstance(v, int) for v in size)


# ---------------------------------------------------------------------------
# resolve_device_type
# ---------------------------------------------------------------------------


class TestResolveDeviceType:
    def test_known_type_returned_unchanged(self):
        dev = Device.from_dict("X", {"device_type": "reMarkable 2"})
        assert resolve_device_type(dev) == "reMarkable 2"

    def test_unknown_type_falls_back_to_default(self):
        dev = Device.from_dict("X", {"device_type": "Unknown Device"})
        assert resolve_device_type(dev) == DEFAULT_DEVICE_TYPE

    def test_empty_type_falls_back_to_default(self):
        dev = Device.from_dict("X", {})
        assert resolve_device_type(dev) == DEFAULT_DEVICE_TYPE


# ---------------------------------------------------------------------------
# save_config / load_config
# ---------------------------------------------------------------------------


class TestConfigPersistence:
    def test_roundtrip(self, tmp_path):
        cfg = {"devices": {"X": {"ip": "1.2.3.4"}}}
        cfg_file = tmp_path / "config.json"
        save_config(cfg, str(cfg_file))
        assert cfg_file.exists()
        assert load_config(str(cfg_file)) == cfg

    def test_load_missing_file_returns_empty_outside_docker(self, tmp_path, monkeypatch):
        """Outside Docker, a missing config file returns an empty device dict (no file is created)."""
        monkeypatch.setattr(config_mod, "BASE_DIR", str(tmp_path))
        cfg_file = tmp_path / "data" / "config.json"
        result = load_config(str(cfg_file))
        assert result == {"devices": {}}
        assert not cfg_file.exists(), "no default config file should be written"

    def test_load_missing_file_returns_empty_in_docker(self, tmp_path, monkeypatch):
        """Inside Docker (BASE_DIR == /app), return empty config without writing."""
        monkeypatch.setattr(config_mod, "BASE_DIR", "/app")
        result = load_config(str(tmp_path / "nonexistent.json"))
        assert result == {"devices": {}}


# ---------------------------------------------------------------------------
# get_device_data_dir
# ---------------------------------------------------------------------------


class TestGetDeviceDataDir:
    def test_slashes_replaced(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config_mod, "BASE_DIR", str(tmp_path))
        path = config_mod.get_device_data_dir("A/B")
        assert "A_B" in path

    def test_spaces_replaced(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config_mod, "BASE_DIR", str(tmp_path))
        path = config_mod.get_device_data_dir("My Device")
        assert "My_Device" in path

    def test_directory_is_created(self, tmp_path, monkeypatch):
        import os

        monkeypatch.setattr(config_mod, "BASE_DIR", str(tmp_path))
        path = config_mod.get_device_data_dir("TestDevice")
        assert os.path.isdir(path)


# ---------------------------------------------------------------------------
# Device model
# ---------------------------------------------------------------------------


class TestDeviceFromDict:
    def test_all_fields_populated(self):
        data = {
            "ip": "1.2.3.4",
            "password": "secret",
            "device_type": "reMarkable 2",
            "templates": False,
            "carousel": True,
            "preferred_image": "bg.png",
        }
        dev = Device.from_dict("MyTablet", data)
        assert dev.name == "MyTablet"
        assert dev.ip == "1.2.3.4"
        assert dev.password == "secret"
        assert dev.device_type == "reMarkable 2"
        assert dev.templates is False
        assert dev.carousel is True
        assert dev.preferred_image == "bg.png"

    def test_defaults_when_keys_missing(self):
        dev = Device.from_dict("T", {})
        assert dev.ip == ""
        assert dev.password == ""
        assert dev.device_type == ""
        assert dev.templates is True
        assert dev.carousel is True
        assert dev.preferred_image is None


class TestDeviceToDict:
    def test_roundtrip(self):
        data = {
            "ip": "1.2.3.4",
            "password": "pw",
            "device_type": "reMarkable 2",
            "templates": True,
            "carousel": False,
        }
        dev = Device.from_dict("X", data)
        assert dev.to_dict() == data

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
