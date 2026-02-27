import os
import json
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _empty_config(tmp_path):
    """Write a minimal empty-devices config and return the path."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps({"devices": {}}), encoding="utf-8")
    return cfg_file


def test_main_page_renders(tmp_path):
    """App renders without exception on initial load (Images page shown by default)."""
    cfg_file = _empty_config(tmp_path)
    with patch.dict(os.environ, {"RM_CONFIG_PATH": str(cfg_file)}):
        at = AppTest.from_file("app.py")
        at.run()
    assert not at.exception
    assert at.title and any("Images" in t.value for t in at.title)


def test_configuration_save_requires_name(tmp_path):
    """Switch to Configuration and click Save without a device name."""
    cfg_file = _empty_config(tmp_path)
    with patch.dict(os.environ, {"RM_CONFIG_PATH": str(cfg_file)}):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()
        at.button[0].click().run()

    assert at.error and any("Veuillez donner un nom" in e.value for e in at.error)
