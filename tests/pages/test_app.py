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
    """With no config, the app redirects to Configuration on the initial load."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
    assert not at.exception
    assert at.title and any("Configuration" in t.value for t in at.title)


def test_no_config_redirects_to_configuration(tmp_path):
    """When no devices are configured, opening the app navigates to Configuration."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
    assert not at.exception
    assert at.title and any("Configuration" in t.value for t in at.title)
    assert at.session_state["_auto_config_redirect"] is True


def test_pending_selected_tablet_is_applied_to_sidebar(tmp_path):
    """pending_selected_tablet set in session state is transferred to the sidebar selectbox
    on the next run without raising a StreamlitAPIException."""
    cfg_path = with_two_devices(tmp_path)
    with patch.dict(os.environ, make_env(tmp_path, cfg_path)):
        at = AppTest.from_file("app.py")
        at.run()
        at.session_state["pending_selected_tablet"] = "D2"
        at.run()

    assert not at.exception
    assert at.session_state["tablet"] == "D2"
    assert "pending_selected_tablet" not in at.session_state


def test_ssh_test_success_shows_sidebar_success(tmp_path):
    """Clicking the SSH test button stores a success result shown in the sidebar."""
    cfg_path = with_device(tmp_path)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch("src.ssh.detect_device_info", return_value=(True, "reMarkable 2", "3.0.0", "")),
    ):
        at = AppTest.from_file("app.py")
        at.run()
        at.button(key="sidebar_test_ssh").click().run()

    assert not at.exception
    assert at.session_state["_ssh_test_result"] == {"ok": True, "err": "", "tablet": "D1"}
    assert any("SSH connection OK" in s.body for s in at.success)


def test_ssh_test_failure_shows_sidebar_error(tmp_path):
    """Clicking the SSH test button stores a failure result shown in the sidebar."""
    cfg_path = with_device(tmp_path)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch("src.ssh.detect_device_info", return_value=(False, "", "", "Connection refused")),
    ):
        at = AppTest.from_file("app.py")
        at.run()
        at.button(key="sidebar_test_ssh").click().run()

    assert not at.exception
    assert at.session_state["_ssh_test_result"]["ok"] is False
    assert any("Connection refused" in e.body for e in at.error)


def test_ssh_result_cleared_on_tablet_change(tmp_path):
    """Changing the selected tablet clears a stale SSH test result."""
    cfg_path = with_two_devices(tmp_path)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch("src.ssh.detect_device_info", return_value=(True, "reMarkable 2", "3.0.0", "")),
    ):
        at = AppTest.from_file("app.py")
        at.run()
        # Test SSH on D1
        at.button(key="sidebar_test_ssh").click().run()
        assert at.session_state["_ssh_test_result"]["tablet"] == "D1"
        # Switch to D2 — stale result should be cleared
        at.session_state["_ssh_test_result"] = {"ok": True, "err": "", "tablet": "D1"}
        at.selectbox(key="tablet").set_value("D2").run()

    assert not at.exception
    assert "_ssh_test_result" not in at.session_state


def test_sidebar_ssh_test_updates_firmware_in_config(tmp_path):
    """Successful detection updates firmware/version fields in config when changed."""
    cfg_path = with_device(tmp_path)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch("src.ssh.detect_device_info", return_value=(True, "reMarkable 2", "4.0.1", "")),
    ):
        at = AppTest.from_file("app.py")
        at.run()
        at.button(key="sidebar_test_ssh").click().run()

    assert not at.exception
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["devices"]["D1"]["firmware_version"] == "4.0.1"


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
        patch("src.ssh.detect_device_info", return_value=(True, "reMarkable 2", "3.0.0", "")),
    ):
        at = AppTest.from_file("app.py")
        at.run()
        at.button(key="sidebar_test_ssh").click().run()

    assert not at.exception
    after = cfg_file.read_text(encoding="utf-8")
    assert before == after
