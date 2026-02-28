import json
import os
from unittest.mock import patch
from streamlit.testing.v1 import AppTest


def _write_config(tmp_path, cfg: dict):
    """Write *cfg* to a temp config file and return its path as a string."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(json.dumps(cfg), encoding="utf-8")
    return str(cfg_file)


def _empty_cfg(tmp_path):
    return _write_config(tmp_path, {"devices": {}})


def _with_device(tmp_path, name="D1"):
    return _write_config(tmp_path, {
        "devices": {name: {"ip": "10.0.0.1", "password": "pw", "device_type": "reMarkable 2"}}
    })


# ---------------------------------------------------------------------------
# Main / Images page (default)
# ---------------------------------------------------------------------------

def test_main_page_renders(tmp_path):
    """App renders without exception on initial load (Images page shown by default)."""
    with patch.dict(os.environ, {"RM_CONFIG_PATH": _empty_cfg(tmp_path)}):
        at = AppTest.from_file("app.py")
        at.run()
    assert not at.exception
    assert at.title and any("Images" in t.value for t in at.title)


def test_images_page_warns_when_no_devices(tmp_path):
    """Images page shows 'Aucun appareil' warning with an empty config."""
    with patch.dict(os.environ, {"RM_CONFIG_PATH": _empty_cfg(tmp_path)}):
        at = AppTest.from_file("app.py")
        at.run()
    assert any("Aucun appareil" in w.value for w in at.warning)


# ---------------------------------------------------------------------------
# Configuration page
# ---------------------------------------------------------------------------

def test_configuration_save_requires_name(tmp_path):
    """Switch to Configuration and click Save without a device name."""
    with patch.dict(os.environ, {"RM_CONFIG_PATH": _empty_cfg(tmp_path)}):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()
        at.button[0].click().run()

    assert at.error and any("Veuillez donner un nom" in e.value for e in at.error)


def test_configuration_page_shows_device_selectbox(tmp_path):
    """When a device exists, Configuration renders a selectbox to pick it."""
    with patch.dict(os.environ, {"RM_CONFIG_PATH": _with_device(tmp_path)}):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()

    assert not at.exception
    labels = [s.label for s in at.selectbox]
    assert any("appareil" in lbl.lower() for lbl in labels)


# ---------------------------------------------------------------------------
# Deploiement page
# ---------------------------------------------------------------------------

def test_deploiement_page_warns_when_no_devices(tmp_path):
    """Deploiement page shows 'Aucun appareil' warning with empty config."""
    with patch.dict(os.environ, {"RM_CONFIG_PATH": _empty_cfg(tmp_path)}):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/deploiement.py").run()

    assert not at.exception
    assert any("Aucun appareil" in w.value for w in at.warning)


def test_deploiement_page_prompts_tablet_selection(tmp_path):
    """With a device configured but none selected, deploiement page asks to pick one."""
    with patch.dict(os.environ, {"RM_CONFIG_PATH": _with_device(tmp_path)}):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/deploiement.py").run()

    assert not at.exception
    assert any("tablette" in i.value.lower() for i in at.info)


# ---------------------------------------------------------------------------
# Templates page
# ---------------------------------------------------------------------------

def test_templates_page_warns_when_no_devices(tmp_path):
    """Templates page shows 'Aucun appareil' warning with empty config."""
    with patch.dict(os.environ, {"RM_CONFIG_PATH": _empty_cfg(tmp_path)}):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/templates.py").run()

    assert not at.exception
    assert any("Aucun appareil" in w.value for w in at.warning)


# ---------------------------------------------------------------------------
# Logs page
# ---------------------------------------------------------------------------

def test_logs_page_renders_empty(tmp_path):
    """Logs page renders without exception and shows 'Aucun log' info when empty."""
    with patch.dict(os.environ, {"RM_CONFIG_PATH": _empty_cfg(tmp_path)}):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/logs.py").run()

    assert not at.exception
    assert any("Aucun log" in i.value for i in at.info)
