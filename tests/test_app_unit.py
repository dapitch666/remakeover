from pathlib import Path

# Load only the non-Streamlit portion of app.py (stop before the STREAMLIT INTERFACE)
SRC = Path(__file__).resolve().parents[0].parent / "app.py"
SRC_TEXT = SRC.read_text(encoding="utf-8")
_MARK = "# --- STREAMLIT INTERFACE ---"
if _MARK in SRC_TEXT:
    PREAMBLE = SRC_TEXT.split(_MARK)[0]
else:
    PREAMBLE = SRC_TEXT

ns = {}
# Provide __file__ so app.py's preamble can compute BASE_DIR
ns["__file__"] = str(SRC)
exec(compile(PREAMBLE, str(SRC), "exec"), ns)


def test_truncate_display_name_short():
    assert ns["truncate_display_name"]("Anne") == "Anne"


def test_truncate_display_name_exact():
    s = "ABCDEFGHIJKLM"  # 13 chars default max
    assert len(s) == 13
    assert ns["truncate_display_name"](s) == s


def test_truncate_display_name_long():
    s = "A" * 20
    res = ns["truncate_display_name"](s, max_len=10)
    assert res.endswith("...")
    assert len(res) == 10


def test_truncate_display_name_non_string():
    assert ns["truncate_display_name"](123) == "123"


def test_resolve_device_type_known():
    dev = {"device_type": "reMarkable 2"}
    assert ns["resolve_device_type"](dev) == "reMarkable 2"


def test_resolve_device_type_unknown():
    dev = {"device_type": "Unknown Device"}
    assert ns["resolve_device_type"](dev) == ns["DEFAULT_DEVICE_TYPE"]


def test_save_and_load_config_roundtrip(tmp_path, monkeypatch):
    cfg = {"devices": {"X": {"ip": "1.2.3.4"}}}
    cfg_file = tmp_path / "config.json"
    monkeypatch.setitem(ns, "CONFIG_PATH", str(cfg_file))
    # When exec'd in ns, save_config/load_config are present in ns
    ns["save_config"](cfg)
    assert cfg_file.exists()
    loaded = ns["load_config"]()
    assert loaded == cfg
