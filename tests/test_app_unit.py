from src.config import (
    DEFAULT_DEVICE_TYPE,
    truncate_display_name,
    load_config,
    save_config,
    resolve_device_type,
)
from src.models import Device


def test_truncate_display_name_short():
    assert truncate_display_name("Anne") == "Anne"


def test_truncate_display_name_exact():
    s = "ABCDEFGHIJKLM"  # 13 chars, default max
    assert len(s) == 13
    assert truncate_display_name(s) == s


def test_truncate_display_name_long():
    s = "A" * 20
    res = truncate_display_name(s, max_len=10)
    assert res.endswith("...")
    assert len(res) == 10


def test_truncate_display_name_non_string():
    assert truncate_display_name(123) == "123"


def test_resolve_device_type_known():
    dev = Device.from_dict("X", {"device_type": "reMarkable 2"})
    assert resolve_device_type(dev) == "reMarkable 2"


def test_resolve_device_type_unknown():
    dev = Device.from_dict("X", {"device_type": "Unknown Device"})
    assert resolve_device_type(dev) == DEFAULT_DEVICE_TYPE


def test_save_and_load_config_roundtrip(tmp_path):
    cfg = {"devices": {"X": {"ip": "1.2.3.4"}}}
    cfg_file = tmp_path / "config.json"
    save_config(cfg, str(cfg_file))
    assert cfg_file.exists()
    loaded = load_config(str(cfg_file))
    assert loaded == cfg
