"""Tests for pages/configuration.py.

Covers: form validation, device creation, cancel/delete flows.
"""

import json
import os
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests.pages.helpers import (
    at_page,
    empty_cfg,
    make_env,
    with_device,
)

# ---------------------------------------------------------------------------
# Form validation
# ---------------------------------------------------------------------------


def test_configuration_save_requires_name(tmp_path):
    """Clicking Save without a device name shows a validation error."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()
        at.button[0].click().run()

    assert at.error and any("Please enter a name" in e.value for e in at.error)


def test_configuration_save_rejects_duplicate_name(tmp_path):
    """Creating a device with the same name as an existing one shows an error."""
    with patch.dict(os.environ, make_env(tmp_path, with_device(tmp_path, name="D1"))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()
        new_btn = next(b for b in at.button if "new device" in b.label.lower())
        new_btn.click().run()
        at.text_input[0].set_value("D1").run()
        save_btn = next(b for b in at.button if "save" in b.label.lower())
        save_btn.click().run()

    assert not at.exception
    assert at.error and any("already exists" in e.value for e in at.error)


def test_configuration_save_rejects_empty_ip(tmp_path):
    """Saving a device with no IP shows a validation error."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()
        at.text_input[0].set_value("MyTablet").run()
        save_btn = next(b for b in at.button if "save" in b.label.lower())
        save_btn.click().run()

    assert not at.exception
    assert at.error and any("ip address" in e.value.lower() for e in at.error)


def test_configuration_save_rejects_invalid_ip(tmp_path):
    """Saving a device with a malformed IP shows a validation error."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()
        at.text_input[0].set_value("MyTablet").run()
        at.text_input[1].set_value("not-an-ip").run()
        save_btn = next(b for b in at.button if "save" in b.label.lower())
        save_btn.click().run()

    assert not at.exception
    assert at.error and any("valid" in e.value.lower() for e in at.error)


# ---------------------------------------------------------------------------
# Device selectbox / device-type options
# ---------------------------------------------------------------------------


def test_configuration_page_shows_device_selectbox(tmp_path):
    """When a device exists, Configuration shows its edit form and a 'Nouvel appareil' button."""
    with patch.dict(os.environ, make_env(tmp_path, with_device(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()

    assert not at.exception
    assert any("new device" in b.label.lower() for b in at.button)


def test_configuration_device_type_selectbox_shows_all_models(tmp_path):
    """Device-type selectbox must list all known models."""
    with patch.dict(os.environ, make_env(tmp_path, with_device(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()

    assert not at.exception
    type_selectbox = next((s for s in at.selectbox if "tablet" in s.label.lower()), None)
    assert type_selectbox is not None, "Device-type selectbox not found"
    options = type_selectbox.options
    assert "reMarkable 2" in options
    assert "reMarkable Paper Pro" in options
    assert "reMarkable Paper Pro Move" in options
    assert len(options) >= 3


# ---------------------------------------------------------------------------
# Save creates device and updates sidebar
# ---------------------------------------------------------------------------


def test_saving_new_device_sets_pending_selected_tablet(tmp_path):
    """Saving a new device causes the sidebar to select it."""
    cfg_path = empty_cfg(tmp_path)
    with patch.dict(os.environ, make_env(tmp_path, cfg_path)):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()
        at.text_input[0].set_value("NewTablet").run()
        at.text_input[1].set_value("192.168.1.1").run()
        save_btn = next(b for b in at.button if "save" in b.label.lower())
        save_btn.click().run()

    assert not at.exception
    assert at.session_state["tablet"] == "NewTablet"
    assert "pending_selected_tablet" not in at.session_state


# ---------------------------------------------------------------------------
# Cancel button
# ---------------------------------------------------------------------------


def test_cancel_button_shown_in_creation_mode_when_device_exists(tmp_path):
    """When clicking 'Nouvel appareil', a Cancel button appears alongside Save."""
    with patch.dict(os.environ, make_env(tmp_path, with_device(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()
        new_btn = next(b for b in at.button if "new device" in b.label.lower())
        new_btn.click().run()

    assert not at.exception
    assert any("cancel" in b.label.lower() for b in at.button)


def test_cancel_button_not_shown_on_first_device_creation(tmp_path):
    """With no existing devices, there is nowhere to cancel to — no Cancel button shown."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()

    assert not at.exception
    assert not any("cancel" in b.label.lower() for b in at.button)


def test_cancel_button_returns_to_edit_mode(tmp_path):
    """Clicking Cancel in creation mode clears config_creating_new and shows the edit form."""
    with patch.dict(os.environ, make_env(tmp_path, with_device(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/configuration.py").run()
        new_btn = next(b for b in at.button if "new device" in b.label.lower())
        new_btn.click().run()
        cancel_btn = next(b for b in at.button if "cancel" in b.label.lower())
        cancel_btn.click().run()

    assert not at.exception
    assert "config_creating_new" not in at.session_state
    assert any("new device" in b.label.lower() for b in at.button)


# ---------------------------------------------------------------------------
# Delete flow
# ---------------------------------------------------------------------------


class TestConfigurationDeleteFlow:
    def test_delete_button_is_shown_for_existing_device(self, tmp_path):
        """When editing an existing device, a Delete button must be rendered."""
        cfg_path = with_device(tmp_path, "D1")
        at = at_page(tmp_path, "pages/configuration.py", cfg_path)
        assert not at.exception
        labels = [b.label for b in at.button]
        assert any("Delete" in lbl for lbl in labels), f"No delete button found: {labels}"

    def test_delete_button_click_sets_pending_state(self, tmp_path):
        """Clicking Delete sets pending_delete_device in session state."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/configuration.py").run()
            del_btn = next((b for b in at.button if b.label == "Delete"), None)
            assert del_btn is not None
            del_btn.click().run()

        assert not at.exception
        assert at.session_state["pending_delete_device"] == "D1"

    def test_delete_confirmed_removes_device(self, tmp_path):
        """Confirming deletion removes the device from the saved config."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["pending_delete_device"] = "D1"
            at.session_state["del_device_D1"] = True
            at.switch_page("pages/configuration.py").run()

        assert not at.exception
        saved = json.loads((tmp_path / "config.json").read_text())
        assert "D1" not in saved.get("devices", {})

    def test_delete_cancelled_keeps_device(self, tmp_path):
        """Cancelling deletion keeps the device and clears pending state."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["pending_delete_device"] = "D1"
            at.session_state["del_device_D1"] = False
            at.switch_page("pages/configuration.py").run()

        assert not at.exception
        assert "pending_delete_device" not in at.session_state
        saved = json.loads((tmp_path / "config.json").read_text())
        assert "D1" in saved.get("devices", {})

    def test_cancel_new_device_returns_to_edit(self, tmp_path):
        """The Cancel button in new-device mode clears the creating_new flag."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/configuration.py").run()
            new_btn = next((b for b in at.button if "new device" in b.label.lower()), None)
            assert new_btn is not None
            new_btn.click().run()
            cancel_btn = next((b for b in at.button if "cancel" in b.label.lower()), None)
            assert cancel_btn is not None
            cancel_btn.click().run()

        assert not at.exception
        assert "config_creating_new" not in at.session_state
