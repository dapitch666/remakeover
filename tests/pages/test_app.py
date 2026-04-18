"""Tests for the main app entry-point (app.py) behavior.

Covers: initial render, auto-redirect to configuration, sidebar state propagation,
SSH connectivity result display.
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


def test_main_page_renders(tmp_path):
    """With no devices, the app shows a warning and the config panel in create mode."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
    assert not at.exception
    assert any(at.warning)


def test_no_config_shows_config_panel_in_create_mode(tmp_path):
    """When no devices are configured, the sidebar config panel opens in create mode."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
    assert not at.exception
    assert any("test connection" in b.label.lower() for b in at.button)


def test_pending_selected_device_is_applied_to_sidebar(tmp_path):
    """pending_selected_device set in session state is transferred to the sidebar selectbox
    on the next run without raising a StreamlitAPIException."""
    cfg_path = with_two_devices(tmp_path)
    with patch.dict(os.environ, make_env(tmp_path, cfg_path)):
        at = AppTest.from_file("app.py")
        at.run()
        at.session_state["pending_selected_device"] = "D2"
        at.run()

    assert not at.exception
    assert at.session_state["device"] == "D2"
    assert "pending_selected_device" not in at.session_state


def test_ssh_test_success_shows_sidebar_success(tmp_path):
    """Clicking the SSH test button stores a success result shown in the sidebar."""
    cfg_path = with_device(tmp_path)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch(
            "src.ssh.detect_device_info", return_value=(True, "reMarkable 2", "3.0.0", False, "")
        ),
    ):
        at = AppTest.from_file("app.py")
        at.run()
        at.button(key="sidebar_test_ssh").click().run()

    assert not at.exception
    result = at.session_state["_ssh_test_result"]
    assert result["ok"] is True
    assert result["device"] == "D1"
    assert result["error"] == ""
    assert any("SSH connection OK" in s.body for s in at.success)


def test_ssh_test_failure_shows_sidebar_error(tmp_path):
    """Clicking the SSH test button stores a failure result shown in the sidebar."""
    cfg_path = with_device(tmp_path)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch(
            "src.ssh.detect_device_info", return_value=(False, "", "", False, "Connection refused")
        ),
    ):
        at = AppTest.from_file("app.py")
        at.run()
        at.button(key="sidebar_test_ssh").click().run()

    assert not at.exception
    assert at.session_state["_ssh_test_result"]["ok"] is False
    assert any("Connection refused" in e.body for e in at.error)


def test_ssh_result_cleared_on_device_change(tmp_path):
    """Changing the selected device clears a stale SSH test result."""
    cfg_path = with_two_devices(tmp_path)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch(
            "src.ssh.detect_device_info", return_value=(True, "reMarkable 2", "3.0.0", False, "")
        ),
    ):
        at = AppTest.from_file("app.py")
        at.run()
        # Test SSH on D1
        at.button(key="sidebar_test_ssh").click().run()
        assert at.session_state["_ssh_test_result"]["device"] == "D1"
        # Switch to D2 — stale result should be cleared
        at.session_state["_ssh_test_result"] = {"ok": True, "error": "", "device": "D1"}
        at.selectbox(key="device").set_value("D2").run()

    assert not at.exception
    assert "_ssh_test_result" not in at.session_state


def test_sidebar_ssh_test_updates_firmware_in_config(tmp_path):
    """Successful detection updates firmware/version fields in config when changed."""
    cfg_path = with_device(tmp_path)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch(
            "src.ssh.detect_device_info", return_value=(True, "reMarkable 2", "4.0.1", False, "")
        ),
    ):
        at = AppTest.from_file("app.py")
        at.run()
        at.button(key="sidebar_test_ssh").click().run()

    assert not at.exception
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["devices"]["D1"]["firmware_version"] == "4.0.1"


def test_ssh_test_persists_sleep_screen_disabled_when_detected_false(tmp_path):
    """Detection returning False when config says True must write False back to config.

    Regression guard: the original code only persisted the True direction, so a device
    whose SleepScreenPath had been removed on-device would never sync back to False.
    """
    cfg_path = with_device(tmp_path, sleep_screen_enabled=True)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch(
            "src.ssh.detect_device_info",
            return_value=(True, "reMarkable 2", "3.0.0", False, ""),
        ),
    ):
        at = AppTest.from_file("app.py")
        at.run()
        at.button(key="sidebar_test_ssh").click().run()

    assert not at.exception
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["devices"]["D1"]["sleep_screen_enabled"] is False


def test_ssh_test_persists_sleep_screen_enabled_when_detected_true(tmp_path):
    """Detection returning True when config says False must write True to config."""
    cfg_path = with_device(tmp_path, sleep_screen_enabled=False)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch(
            "src.ssh.detect_device_info",
            return_value=(True, "reMarkable 2", "3.0.0", True, ""),
        ),
    ):
        at = AppTest.from_file("app.py")
        at.run()
        at.button(key="sidebar_test_ssh").click().run()

    assert not at.exception
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["devices"]["D1"]["sleep_screen_enabled"] is True


def test_sidebar_ssh_test_keeps_config_when_detection_is_unchanged(tmp_path):
    """No config write-side change is made when detected values are unchanged."""
    cfg_file = tmp_path / "config.json"
    cfg_file.write_text(
        json.dumps(
            {
                "devices": {
                    "D1": {
                        "ip": "10.0.0.1",
                        "password": "pw",
                        "device_type": "reMarkable 2",
                        "firmware_version": "3.0.0",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    before = cfg_file.read_text(encoding="utf-8")

    with (
        patch.dict(os.environ, make_env(tmp_path, str(cfg_file))),
        patch(
            "src.ssh.detect_device_info", return_value=(True, "reMarkable 2", "3.0.0", False, "")
        ),
    ):
        at = AppTest.from_file("app.py")
        at.run()
        at.button(key="sidebar_test_ssh").click().run()

    assert not at.exception
    after = cfg_file.read_text(encoding="utf-8")
    assert before == after
