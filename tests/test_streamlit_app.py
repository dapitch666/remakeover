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
    return _write_config(
        tmp_path,
        {"devices": {name: {"ip": "10.0.0.1", "password": "pw", "device_type": "reMarkable 2"}}},
    )


def _with_two_devices(tmp_path):
    return _write_config(
        tmp_path,
        {
            "devices": {
                "D1": {"ip": "10.0.0.1", "password": "pw", "device_type": "reMarkable 2"},
                "D2": {"ip": "10.0.0.2", "password": "pw2", "device_type": "reMarkable 2"},
            }
        },
    )


def _test_env(tmp_path, cfg_path: str) -> dict:
    """Return env overrides that redirect both config and data dir to tmp_path."""
    return {"RM_CONFIG_PATH": cfg_path, "RM_DATA_DIR": str(tmp_path)}


def test_main_page_renders(tmp_path):
    """With no config, the app redirects to Configuration on the initial load."""
    with patch.dict(os.environ, _test_env(tmp_path, _empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
    assert not at.exception
    assert at.title and any("Configuration" in t.value for t in at.title)


def test_no_config_redirects_to_configuration(tmp_path):
    """When no devices are configured, opening the app navigates to Configuration."""
    with patch.dict(os.environ, _test_env(tmp_path, _empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
    assert not at.exception
    # The configuration page title must be visible
    assert at.title and any("Configuration" in t.value for t in at.title)
    # The redirect flag must have been set so the redirect does not loop
    assert at.session_state["_auto_config_redirect"] is True


def test_images_page_warns_when_no_devices(tmp_path):
    """Images page shows 'Aucun appareil' message with an empty config."""
    with patch.dict(os.environ, _test_env(tmp_path, _empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()  # first run redirects to configuration (flag set)
        at.switch_page("pages/images.py").run()  # second run: flag prevents re-redirect
    assert not at.exception
    assert any("Aucun appareil" in m.value for m in at.markdown)


# ---------------------------------------------------------------------------
# Configuration page
# ---------------------------------------------------------------------------


def test_configuration_save_requires_name(tmp_path):
    """Switch to Configuration and click Save without a device name."""
    with patch.dict(os.environ, _test_env(tmp_path, _empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()
        at.button[0].click().run()

    assert at.error and any("Veuillez donner un nom" in e.value for e in at.error)


def test_configuration_save_rejects_duplicate_name(tmp_path):
    """Creating a new device with the same name as an existing one shows an error."""
    with patch.dict(os.environ, _test_env(tmp_path, _with_device(tmp_path, name="D1"))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()
        # Enter creation mode
        new_btn = next(b for b in at.button if "nouvel appareil" in b.label.lower())
        new_btn.click().run()
        # Type the name of the already-existing device
        at.text_input[0].set_value("D1").run()
        save_btn = next(b for b in at.button if "sauvegarder" in b.label.lower())
        save_btn.click().run()

    assert not at.exception
    assert at.error and any("existe déjà" in e.value for e in at.error)


def test_configuration_save_rejects_empty_ip(tmp_path):
    """Saving a device with no IP shows a validation error."""
    with patch.dict(os.environ, _test_env(tmp_path, _empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()
        # Fill name but leave IP empty
        at.text_input[0].set_value("MyTablet").run()
        save_btn = next(b for b in at.button if "sauvegarder" in b.label.lower())
        save_btn.click().run()

    assert not at.exception
    assert at.error and any("adresse ip" in e.value.lower() for e in at.error)


def test_configuration_save_rejects_invalid_ip(tmp_path):
    """Saving a device with a malformed IP shows a validation error."""
    with patch.dict(os.environ, _test_env(tmp_path, _empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()
        at.text_input[0].set_value("MyTablet").run()
        at.text_input[1].set_value("not-an-ip").run()
        save_btn = next(b for b in at.button if "sauvegarder" in b.label.lower())
        save_btn.click().run()

    assert not at.exception
    assert at.error and any("valide" in e.value.lower() for e in at.error)


def test_configuration_page_shows_device_selectbox(tmp_path):
    """When a device exists, Configuration shows its edit form and a 'Nouvel appareil' button."""
    with patch.dict(os.environ, _test_env(tmp_path, _with_device(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()

    assert not at.exception
    button_labels = [b.label for b in at.button]
    assert any("nouvel appareil" in lbl.lower() for lbl in button_labels)


def test_configuration_device_type_selectbox_shows_all_models(tmp_path):
    """Device-type selectbox must list all known models, not just the current one."""
    with patch.dict(os.environ, _test_env(tmp_path, _with_device(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()

    assert not at.exception
    # Find the "Type de tablette" selectbox options
    type_selectbox = next((s for s in at.selectbox if "tablette" in s.label.lower()), None)
    assert type_selectbox is not None, "Device-type selectbox not found"
    options = type_selectbox.options
    assert "reMarkable 2" in options
    assert "reMarkable Paper Pro" in options
    assert "reMarkable Paper Pro Move" in options
    assert len(options) >= 3, "Expected at least 3 device types"


def test_saving_new_device_sets_pending_selected_tablet(tmp_path):
    """Saving a new device on the configuration page causes the sidebar to select it."""
    cfg_path = _empty_cfg(tmp_path)
    with patch.dict(os.environ, _test_env(tmp_path, cfg_path)):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()
        at.text_input[0].set_value("NewTablet").run()
        at.text_input[1].set_value("192.168.1.1").run()
        # Find and click the Sauvegarder button
        save_btn = next(b for b in at.button if "sauvegarder" in b.label.lower())
        save_btn.click().run()

    assert not at.exception
    # After save + rerun, app.py consumes pending_selected_tablet and updates the sidebar
    assert at.session_state["selected_tablet_select"] == "NewTablet"
    assert "pending_selected_tablet" not in at.session_state


def test_pending_selected_tablet_is_applied_to_sidebar(tmp_path):
    """pending_selected_tablet set in session state is transferred to the sidebar selectbox on next run
    without raising a StreamlitAPIException."""
    cfg_path = _with_two_devices(tmp_path)
    with patch.dict(os.environ, _test_env(tmp_path, cfg_path)):
        at = AppTest.from_file("app.py")
        at.run()
        # Simulate the configuration page having requested a selection change
        at.session_state["pending_selected_tablet"] = "D2"
        at.run()

    assert not at.exception
    assert at.session_state["selected_tablet_select"] == "D2"
    assert "pending_selected_tablet" not in at.session_state


def test_cancel_button_shown_in_creation_mode_when_device_exists(tmp_path):
    """When clicking 'Nouvel appareil', a Cancel button appears alongside Save."""
    with patch.dict(os.environ, _test_env(tmp_path, _with_device(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()
        # Enter creation mode
        new_btn = next(b for b in at.button if "nouvel appareil" in b.label.lower())
        new_btn.click().run()

    assert not at.exception
    button_labels = [b.label for b in at.button]
    assert any("annuler" in lbl.lower() for lbl in button_labels)


def test_cancel_button_not_shown_on_first_device_creation(tmp_path):
    """With no existing devices, there is nowhere to cancel to — no Cancel button shown."""
    with patch.dict(os.environ, _test_env(tmp_path, _empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()

    assert not at.exception
    button_labels = [b.label for b in at.button]
    assert not any("annuler" in lbl.lower() for lbl in button_labels)


def test_cancel_button_returns_to_edit_mode(tmp_path):
    """Clicking Cancel in creation mode clears config_creating_new and shows the edit form."""
    with patch.dict(os.environ, _test_env(tmp_path, _with_device(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()
        # Enter creation mode
        new_btn = next(b for b in at.button if "nouvel appareil" in b.label.lower())
        new_btn.click().run()
        # Click Cancel
        cancel_btn = next(b for b in at.button if "annuler" in b.label.lower())
        cancel_btn.click().run()

    assert not at.exception
    assert "config_creating_new" not in at.session_state
    # Back to edit mode: "Nouvel appareil" button is visible again
    button_labels = [b.label for b in at.button]
    assert any("nouvel appareil" in lbl.lower() for lbl in button_labels)


# ---------------------------------------------------------------------------
# Deploiement page
# ---------------------------------------------------------------------------


def test_deploiement_page_warns_when_no_devices(tmp_path):
    """Deploiement page shows 'Aucun appareil' message with empty config."""
    with patch.dict(os.environ, _test_env(tmp_path, _empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/deploiement.py").run()

    assert not at.exception
    assert any("Aucun appareil" in m.value for m in at.markdown)


def test_deploiement_page_prompts_tablet_selection(tmp_path):
    """With a device configured and selected, deploiement page renders the deployment description."""
    with patch.dict(os.environ, _test_env(tmp_path, _with_device(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/deploiement.py").run()

    assert not at.exception
    # The page always renders either an info box or a warning box; no uncaught exception
    assert at.info or at.warning


def test_deploiement_page_shows_info_when_actions_available(tmp_path):
    """Deploiement page shows info box (not warning) when there are meaningful actions."""
    # carousel=True by default in _with_device → has_meaningful_actions=True
    cfg_path = _with_device(tmp_path)
    with patch.dict(os.environ, _test_env(tmp_path, cfg_path)):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/deploiement.py").run()

    assert not at.exception
    deploy_btn = next(
        (b for b in at.button if "d" in b.label.lower() and "ployer" in b.label.lower()), None
    )
    assert deploy_btn is not None
    assert not deploy_btn.disabled
    # No "nothing to deploy" warning
    assert not any("aucune action" in w.value.lower() for w in at.warning)


def test_deploiement_page_shows_warning_and_disables_button_when_no_actions(tmp_path):
    """When a device has no images, templates=False and carousel=False, a warning is shown
    and the deploy button is disabled."""
    cfg = {
        "devices": {
            "D1": {
                "ip": "10.0.0.1",
                "password": "pw",
                "device_type": "reMarkable 2",
                "templates": False,
                "carousel": False,
            }
        }
    }
    cfg_path = _write_config(tmp_path, cfg)
    with patch.dict(os.environ, _test_env(tmp_path, cfg_path)):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/deploiement.py").run()

    assert not at.exception
    assert any("aucune action" in w.value.lower() for w in at.warning)
    deploy_btn = next((b for b in at.button if "ployer" in b.label.lower()), None)
    assert deploy_btn is not None
    assert deploy_btn.disabled


def test_deploiement_page_shows_warning_when_templates_enabled_but_no_local_files(tmp_path):
    """When templates=True but no local SVG files exist, it's not a meaningful action."""
    cfg = {
        "devices": {
            "D1": {
                "ip": "10.0.0.1",
                "password": "pw",
                "device_type": "reMarkable 2",
                "templates": True,
                "carousel": False,
            }
        }
    }
    cfg_path = _write_config(tmp_path, cfg)
    # No SVG files created in data dir → list_device_templates returns []
    with patch.dict(os.environ, _test_env(tmp_path, cfg_path)):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/deploiement.py").run()

    assert not at.exception
    assert any("aucune action" in w.value.lower() for w in at.warning)
    deploy_btn = next((b for b in at.button if "ployer" in b.label.lower()), None)
    assert deploy_btn is not None
    assert deploy_btn.disabled


# ---------------------------------------------------------------------------
# Templates page
# ---------------------------------------------------------------------------


def test_templates_page_warns_when_no_devices(tmp_path):
    """Templates page shows 'Aucun appareil' message with empty config."""
    with patch.dict(os.environ, _test_env(tmp_path, _empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/templates.py").run()

    assert not at.exception
    assert any("Aucun appareil" in m.value for m in at.markdown)


# ---------------------------------------------------------------------------
# Logs page
# ---------------------------------------------------------------------------


def test_logs_page_renders_empty(tmp_path):
    """Logs page renders without exception and shows 'Aucun log' info when empty."""
    with patch.dict(os.environ, _test_env(tmp_path, _empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/logs.py").run()

    assert not at.exception
    assert any("Aucun log" in i.value for i in at.info)
