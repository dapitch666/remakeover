"""Unit tests for src/config.py — config persistence, path helpers, and device-type resolution."""

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
