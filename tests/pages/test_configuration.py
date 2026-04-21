"""Tests for the device configuration panel (rendered in the sidebar expander).

Covers: form validation, device creation, cancel/delete flows.
"""

import json
import os
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests.pages.helpers import (
    empty_cfg,
    make_env,
    with_device,
    with_two_devices,
)

_DETECT_PATCH = "src.config_ui.run_detection"


def _ok_result(device_type="reMarkable 2", fw="3.5.2.1896", sleep=False):
    return {
        "ok": True,
        "device_type": device_type,
        "firmware_version": fw,
        "sleep_screen_enabled": sleep,
        "error": "",
    }


def _fail_result(error="Connection refused"):
    return {
        "ok": False,
        "device_type": "",
        "firmware_version": "",
        "sleep_screen_enabled": False,
        "error": error,
    }


# ---------------------------------------------------------------------------
# Form validation
# ---------------------------------------------------------------------------


def test_configuration_save_requires_name(tmp_path):
    """Save stays disabled until a device name is provided."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        save_btn = next(b for b in at.button if "save" in b.label.lower())
        assert save_btn.disabled is True

    assert not at.exception


def test_configuration_save_rejects_duplicate_name(tmp_path):
    """Save stays disabled when creating a device with an existing name."""
    with patch.dict(os.environ, make_env(tmp_path, with_device(tmp_path, name="D1"))):
        at = AppTest.from_file("app.py")
        at.run()
        device_box = next(s for s in at.selectbox if s.key == "device")
        device_box.set_value("─ New device ─").run()
        at.text_input[0].set_value("D1").run()
        at.text_input[1].set_value("192.168.1.20").run()
        at.text_input[2].set_value("pw").run()
        at.session_state["connection_test_result"] = {
            "ok": True,
            "device_type": "reMarkable 2",
            "firmware_version": "3.1.0",
            "error": "",
            "ip": "192.168.1.20",
            "mode": "new",
            "device_name": "",
        }
        at.run()
        save_btn = next(b for b in at.button if "save" in b.label.lower())
        assert save_btn.disabled is True

    assert not at.exception


def test_configuration_save_rejects_empty_ip(tmp_path):
    """Save stays disabled when IP is empty."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.text_input[0].set_value("MyDevice").run()
        at.text_input[2].set_value("pw").run()
        save_btn = next(b for b in at.button if "save" in b.label.lower())
        assert save_btn.disabled is True

    assert not at.exception


def test_configuration_save_rejects_invalid_ip(tmp_path):
    """Save stays disabled when IP is malformed."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.text_input[0].set_value("MyDevice").run()
        at.text_input[1].set_value("not-an-ip").run()
        at.text_input[2].set_value("pw").run()
        save_btn = next(b for b in at.button if "save" in b.label.lower())
        assert save_btn.disabled is True

    assert not at.exception


# ---------------------------------------------------------------------------
# Device selectbox / device-type options
# ---------------------------------------------------------------------------


def test_configuration_page_shows_device_selectbox(tmp_path):
    """When a device exists, the device selectbox offers a '─ New device ─' option."""
    with patch.dict(os.environ, make_env(tmp_path, with_device(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()

    assert not at.exception
    device_box = next(s for s in at.selectbox if s.key == "device")
    assert "─ New device ─" in device_box.options


def test_configuration_edit_mode_has_no_device_type_selectbox(tmp_path):
    """Device model is auto-detected, so edit mode must not show a model dropdown."""
    with patch.dict(os.environ, make_env(tmp_path, with_device(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()

    assert not at.exception
    type_selectbox = next((s for s in at.selectbox if "model" in s.label.lower()), None)
    assert type_selectbox is None


# ---------------------------------------------------------------------------
# Save creates device and updates sidebar
# ---------------------------------------------------------------------------


def test_saving_new_device_sets_pending_selected_device(tmp_path):
    """Saving a new device writes all fields to config and selects it in the sidebar."""
    cfg_path = empty_cfg(tmp_path)
    with patch.dict(os.environ, make_env(tmp_path, cfg_path)):
        at = AppTest.from_file("app.py")
        at.run()
        at.session_state["connection_test_result"] = {
            "ok": True,
            "device_type": "reMarkable 2",
            "firmware_version": "3.5.0",
            "sleep_screen_enabled": False,
            "error": "",
            "ip": "192.168.1.1",
            "mode": "new",
            "device_name": "",
        }
        at.text_input[0].set_value("NewDevice").run()
        at.text_input[1].set_value("192.168.1.1").run()
        at.text_input[2].set_value("pw").run()
        save_btn = next(b for b in at.button if "save" in b.label.lower())
        save_btn.click().run()

    assert not at.exception
    assert at.session_state["device"] == "NewDevice"
    assert "pending_selected_device" not in at.session_state
    assert at.session_state["config_panel_open"] is False

    saved = json.loads((tmp_path / "config.json").read_text())
    entry = saved["devices"]["NewDevice"]
    assert entry["ip"] == "192.168.1.1"
    assert entry["password"] == "pw"
    assert entry["device_type"] == "reMarkable 2"
    assert entry["firmware_version"] == "3.5.0"
    assert entry["sleep_screen_enabled"] is False


# ---------------------------------------------------------------------------
# Cancel button
# ---------------------------------------------------------------------------


def test_cancel_button_shown_in_creation_mode_when_device_exists(tmp_path):
    """Selecting '─ New device ─' shows a Cancel button alongside Save."""
    with patch.dict(os.environ, make_env(tmp_path, with_device(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        device_box = next(s for s in at.selectbox if s.key == "device")
        device_box.set_value("─ New device ─").run()

    assert not at.exception
    assert any("cancel" in b.label.lower() for b in at.button)


def test_cancel_button_not_shown_on_first_device_creation(tmp_path):
    """With no existing devices, there is nowhere to cancel to — no Cancel button shown."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()

    assert not at.exception
    assert not any("cancel" in b.label.lower() for b in at.button)


def test_cancel_button_returns_to_edit_mode(tmp_path):
    """Clicking Cancel switches the selectbox back to the real device and shows the edit form."""
    with patch.dict(os.environ, make_env(tmp_path, with_device(tmp_path, name="D1"))):
        at = AppTest.from_file("app.py")
        at.run()
        device_box = next(s for s in at.selectbox if s.key == "device")
        device_box.set_value("─ New device ─").run()
        cancel_btn = next(b for b in at.button if "cancel" in b.label.lower())
        cancel_btn.click().run()

    assert not at.exception
    assert at.session_state["device"] == "D1"
    assert at.session_state["config_panel_open"] is False


# ---------------------------------------------------------------------------
# Delete flow
# ---------------------------------------------------------------------------


class TestConfigurationDeleteFlow:
    def test_delete_button_is_shown_for_existing_device(self, tmp_path):
        """When editing an existing device, a Delete button must be rendered."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.session_state["config_panel_open"] = True
            at.run()
        assert not at.exception
        labels = [b.label for b in at.button]
        assert any("Delete" in lbl for lbl in labels), f"No delete button found: {labels}"

    def test_delete_button_click_sets_pending_state(self, tmp_path):
        """Clicking Delete sets pending_delete_device; panel stays open so dialog can render."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.session_state["config_panel_open"] = True
            at.run()
            del_btn = next((b for b in at.button if b.label == "Delete"), None)
            assert del_btn is not None
            del_btn.click().run()

        assert not at.exception
        assert at.session_state["pending_delete_device"] == "D1"
        assert at.session_state["config_panel_open"] is True

    def test_delete_confirmed_removes_device(self, tmp_path):
        """Confirming deletion removes the device from the saved config."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.session_state["config_panel_open"] = True
            at.run()
            at.session_state["pending_delete_device"] = "D1"
            at.session_state["del_device_D1"] = True
            at.run()

        assert not at.exception
        saved = json.loads((tmp_path / "config.json").read_text())
        assert "D1" not in saved.get("devices", {})

    def test_delete_cancelled_keeps_device(self, tmp_path):
        """Cancelling deletion keeps the device and clears pending state."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.session_state["config_panel_open"] = True
            at.run()
            at.session_state["pending_delete_device"] = "D1"
            at.session_state["del_device_D1"] = False
            at.run()

        assert not at.exception
        assert "pending_delete_device" not in at.session_state
        saved = json.loads((tmp_path / "config.json").read_text())
        assert "D1" in saved.get("devices", {})

    def test_cancel_new_device_returns_to_edit(self, tmp_path):
        """The Cancel button in new-device mode switches the selectbox back to the real device."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            device_box = next(s for s in at.selectbox if s.key == "device")
            device_box.set_value("─ New device ─").run()
            cancel_btn = next((b for b in at.button if "cancel" in b.label.lower()), None)
            assert cancel_btn is not None
            cancel_btn.click().run()

        assert not at.exception
        assert at.session_state["device"] == "D1"
        assert at.session_state["config_panel_open"] is False


# ---------------------------------------------------------------------------
# Test Connection button — create mode only
# ---------------------------------------------------------------------------


def test_test_connection_button_exists_in_create_mode(tmp_path):
    """Create mode shows a 'Test Connection' button."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()

    assert not at.exception
    assert any("test connection" in b.label.lower() for b in at.button)


def test_create_mode_no_device_type_selectbox(tmp_path):
    """Create mode does not have a device type selectbox."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()

    assert not at.exception
    assert not any("device" in s.label.lower() for s in at.selectbox)


def test_test_connection_success_shows_device_type(tmp_path):
    """After a successful test, detected device type and firmware are displayed."""
    with (
        patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))),
        patch(_DETECT_PATCH, return_value=_ok_result()),
    ):
        at = AppTest.from_file("app.py")
        at.run()
        at.text_input[0].set_value("MyDevice").run()
        at.text_input[1].set_value("192.168.1.1").run()
        test_btn = next(b for b in at.button if "test connection" in b.label.lower())
        test_btn.click().run()

    assert not at.exception
    assert at.session_state["connection_test_result"]["ok"] is True
    assert at.session_state["connection_test_result"]["device_type"] == "reMarkable 2"
    assert at.session_state["connection_test_result"]["firmware_version"] == "3.5.2.1896"
    assert any("reMarkable 2" in s.value for s in at.success)


def test_test_connection_failure_shows_error(tmp_path):
    """After a failed test, an error message is displayed."""
    with (
        patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))),
        patch(_DETECT_PATCH, return_value=_fail_result()),
    ):
        at = AppTest.from_file("app.py")
        at.run()
        at.text_input[1].set_value("192.168.1.99").run()
        test_btn = next(b for b in at.button if "test connection" in b.label.lower())
        test_btn.click().run()

    assert not at.exception
    assert at.session_state["connection_test_result"]["ok"] is False
    assert any("Connection refused" in e.value for e in at.error)


def test_save_uses_detected_device_type(tmp_path):
    """Saving after a successful test writes the detected device_type and firmware to config."""
    cfg_path = empty_cfg(tmp_path)
    with patch.dict(os.environ, make_env(tmp_path, cfg_path)):
        at = AppTest.from_file("app.py")
        at.run()
        at.session_state["connection_test_result"] = {
            "ok": True,
            "device_type": "reMarkable Paper Pro",
            "firmware_version": "4.0.0.1",
            "error": "",
            "ip": "192.168.1.5",
            "mode": "new",
            "device_name": "",
        }
        at.text_input[0].set_value("ProDevice").run()
        at.text_input[1].set_value("192.168.1.5").run()
        save_btn = next(b for b in at.button if "save" in b.label.lower())
        save_btn.click().run()

    assert not at.exception
    saved = json.loads((tmp_path / "config.json").read_text())
    assert "ProDevice" in saved["devices"]
    assert saved["devices"]["ProDevice"]["device_type"] == "reMarkable Paper Pro"
    assert saved["devices"]["ProDevice"]["firmware_version"] == "4.0.0.1"


def test_save_persists_sleep_screen_enabled(tmp_path):
    """When connection_test_result has sleep_screen_enabled=True, it is written to config."""
    cfg_path = empty_cfg(tmp_path)
    with patch.dict(os.environ, make_env(tmp_path, cfg_path)):
        at = AppTest.from_file("app.py")
        at.run()
        at.session_state["connection_test_result"] = {
            "ok": True,
            "device_type": "reMarkable 2",
            "firmware_version": "3.5.2.1896",
            "sleep_screen_enabled": True,
            "error": "",
            "ip": "192.168.1.10",
            "mode": "new",
            "device_name": "",
        }
        at.text_input[0].set_value("SleepDevice").run()
        at.text_input[1].set_value("192.168.1.10").run()
        save_btn = next(b for b in at.button if "save" in b.label.lower())
        save_btn.click().run()

    assert not at.exception
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["devices"]["SleepDevice"]["sleep_screen_enabled"] is True


def test_renaming_existing_device_renames_data_dir(tmp_path):
    """Renaming an existing device updates config key and local data directory."""
    cfg_path = with_device(tmp_path, "D1")
    old_dir = tmp_path / "D1"
    old_dir.mkdir(parents=True, exist_ok=True)
    (old_dir / "marker.txt").write_text("ok", encoding="utf-8")

    with patch.dict(os.environ, make_env(tmp_path, cfg_path)):
        at = AppTest.from_file("app.py")
        at.session_state["config_panel_open"] = True
        at.run()
        at.text_input[0].set_value("Renamed Device").run()
        at.text_input[1].set_value("10.0.0.11").run()
        at.text_input[2].set_value("pw").run()
        at.session_state["connection_test_result"] = {
            "ok": True,
            "device_type": "reMarkable 2",
            "firmware_version": "3.10.0",
            "error": "",
            "ip": "10.0.0.11",
            "mode": "edit",
            "device_name": "D1",
        }
        at.run()
        save_btn = next(b for b in at.button if "save" in b.label.lower())
        save_btn.click().run()

    assert not at.exception
    saved = json.loads((tmp_path / "config.json").read_text())
    assert "D1" not in saved["devices"]
    assert "Renamed Device" in saved["devices"]
    assert not (tmp_path / "D1").exists()
    assert (tmp_path / "Renamed_Device").exists()

    renamed = saved["devices"]["Renamed Device"]
    assert renamed["ip"] == "10.0.0.11"
    assert renamed["password"] == "pw"
    assert renamed["firmware_version"] == "3.10.0"


# ---------------------------------------------------------------------------
# Device switching resets config panel
# ---------------------------------------------------------------------------


def test_switching_device_closes_config_panel(tmp_path):
    """Changing the device selectbox closes the config panel."""
    with patch.dict(os.environ, make_env(tmp_path, with_two_devices(tmp_path))):
        at = AppTest.from_file("app.py")
        at.session_state["config_panel_open"] = True
        at.run()
        device_box = next(s for s in at.selectbox if s.key == "device")
        device_box.set_value("D2").run()

    assert not at.exception
    assert at.session_state["config_panel_open"] is False


def test_switching_device_clears_stale_inputs(tmp_path):
    """Changing the device selectbox removes stale typed values from session state."""
    with patch.dict(os.environ, make_env(tmp_path, with_two_devices(tmp_path))):
        at = AppTest.from_file("app.py")
        at.session_state["config_panel_open"] = True
        at.session_state["config_device_ip"] = "stale_ip"
        at.session_state["config_device_name"] = "stale_name"
        at.run()
        device_box = next(s for s in at.selectbox if s.key == "device")
        device_box.set_value("D2").run()

    assert not at.exception
    # Panel is closed so text inputs are not re-rendered; stale keys must be gone.
    assert "config_device_ip" not in at.session_state
    assert "config_device_name" not in at.session_state


def test_switching_from_sentinel_to_real_device_closes_panel(tmp_path):
    """Switching from '─ New device ─' to a real device closes the config panel."""
    with patch.dict(os.environ, make_env(tmp_path, with_two_devices(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        device_box = next(s for s in at.selectbox if s.key == "device")
        device_box.set_value("─ New device ─").run()
        assert at.session_state["config_panel_open"] is True
        device_box = next(s for s in at.selectbox if s.key == "device")
        device_box.set_value("D2").run()

    assert not at.exception
    assert at.session_state["config_panel_open"] is False


def test_new_device_sentinel_clears_stale_inputs(tmp_path):
    """Selecting '─ New device ─' replaces previously typed values with empty defaults."""
    with patch.dict(os.environ, make_env(tmp_path, with_device(tmp_path))):
        at = AppTest.from_file("app.py")
        at.session_state["config_device_ip"] = "stale_ip"
        at.session_state["config_device_name"] = "stale_name"
        at.run()
        device_box = next(s for s in at.selectbox if s.key == "device")
        device_box.set_value("─ New device ─").run()

    assert not at.exception
    ip_input = next(t for t in at.text_input if t.key == "new_config_device_ip")
    name_input = next(t for t in at.text_input if t.key == "new_config_device_name")
    assert ip_input.value == ""
    assert name_input.value == ""


def test_cancel_button_clears_stale_inputs(tmp_path):
    """Clicking Cancel restores the real device, closes the panel, and clears stale inputs."""
    with patch.dict(os.environ, make_env(tmp_path, with_device(tmp_path, name="D1"))):
        at = AppTest.from_file("app.py")
        at.run()
        device_box = next(s for s in at.selectbox if s.key == "device")
        device_box.set_value("─ New device ─").run()
        at.text_input[1].set_value("typed_ip").run()
        cancel_btn = next(b for b in at.button if "cancel" in b.label.lower())
        cancel_btn.click().run()

    assert not at.exception
    assert at.session_state["device"] == "D1"
    assert at.session_state["config_panel_open"] is False
    assert "config_device_ip" not in at.session_state
    assert "new_config_device_ip" not in at.session_state
