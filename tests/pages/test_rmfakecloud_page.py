"""Tests for pages/rmfakecloud.py — the rmfakecloud re-pairing page.

Covers: the not-enabled guard, the manual re-pair flow (install + code fetch),
the standalone "get a new code" flow, device-switch state cleanup, and the
firmware-change redirect triggered from the sidebar SSH-test button.
"""

import os
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests.pages.helpers import APP_PY, make_env, write_config

_RUN_INSTALL_PATCH = "src.rmfakecloud_ui.run_install"
_FETCH_CODE_PATCH = "src.rmfakecloud_ui.fetch_pairing_code"
_DETECT_PATCH = "src.config_ui.run_detection"
_SWITCH_PAGE_PATCH = "src.config_ui.st.switch_page"

URL = "https://remarkable.example.com"


def _device_cfg(**overrides):
    cfg = {
        "ip": "10.0.0.1",
        "password": "pw",
        "device_type": "reMarkable 2",
        "firmware_version": "3.5.0",
        "rmfakecloud_enabled": True,
        "rmfakecloud_url": URL,
        "rmfakecloud_email": "anne@example.com",
        "rmfakecloud_password": "rmfc-secret",
        "rmfakecloud_install_cmd": "./installer-rmpro.sh install {url}",
    }
    cfg.update(overrides)
    return cfg


def _cfg(tmp_path, **overrides):
    return write_config(tmp_path, {"devices": {"D1": _device_cfg(**overrides)}})


def _goto_page(at):
    return at.switch_page("pages/rmfakecloud.py").run()


# ---------------------------------------------------------------------------
# Not-enabled guard
# ---------------------------------------------------------------------------


def test_page_stops_when_not_enabled_for_selected_device(tmp_path):
    """The in-page guard stops rendering when the *selected* device lacks rmfakecloud_enabled.

    Two devices: D2 has rmfakecloud enabled (so app.py registers the nav page and
    ``switch_page`` can reach it), but D1 — selected on load — does not, so
    ``pages/rmfakecloud.py``'s own ``st.info`` + ``st.stop()`` guard fires.

    A single disabled device is a different case: app.py never registers the nav
    page, and since Streamlit 1.63 (streamlit/streamlit#16611) ``switch_page`` to
    an unregistered page raises instead of silently reaching the script — so that
    layer is covered by app.py's registration gate, not this in-page guard.
    """
    cfg_path = write_config(
        tmp_path,
        {"devices": {"D1": _device_cfg(rmfakecloud_enabled=False), "D2": _device_cfg()}},
    )
    with patch.dict(os.environ, make_env(tmp_path, cfg_path)):
        at = AppTest.from_file(APP_PY)
        at.run()
        at = _goto_page(at)

    assert not at.exception
    assert at.session_state["selected_name"] == "D1"
    assert any("not enabled" in i.value.lower() for i in at.info)
    assert not any(b.key == "ui_rmfc_repair" for b in at.button)


def test_page_renders_when_enabled(tmp_path):
    """The page renders its content for a device with rmfakecloud_enabled."""
    cfg_path = _cfg(tmp_path)
    with patch.dict(os.environ, make_env(tmp_path, cfg_path)):
        at = AppTest.from_file(APP_PY)
        at.run()
        at = _goto_page(at)

    assert not at.exception
    assert any(b.key == "ui_rmfc_repair" for b in at.button)


def test_install_output_subheader_hidden_before_any_run(tmp_path):
    """The "Install command output" subheader is absent until an install has run."""
    cfg_path = _cfg(tmp_path)
    with patch.dict(os.environ, make_env(tmp_path, cfg_path)):
        at = AppTest.from_file(APP_PY)
        at.run()
        at = _goto_page(at)

    assert not at.exception
    assert not any("Install command output" in s.value for s in at.subheader)
    assert not at.code


# ---------------------------------------------------------------------------
# Re-pair now
# ---------------------------------------------------------------------------


def test_repair_now_runs_install_then_fetches_code(tmp_path):
    """Clicking Re-pair now runs the install command, streams output, then fetches a code."""
    cfg_path = _cfg(tmp_path)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch(_RUN_INSTALL_PATCH, return_value=(True, "Starting xochitl...\n")) as mock_install,
        patch(_FETCH_CODE_PATCH, return_value=(True, "abcdefgh", "")) as mock_fetch,
    ):
        at = AppTest.from_file(APP_PY)
        at.run()
        at = _goto_page(at)
        at.button(key="ui_rmfc_repair").click().run()

    assert not at.exception
    mock_install.assert_called_once()
    assert mock_install.call_args.args[0].name == "D1"
    mock_fetch.assert_called_once_with(URL, "anne@example.com", "rmfc-secret")
    assert at.session_state["rmfc_install_output"] == "Starting xochitl...\n"
    assert at.session_state["rmfc_install_ok"] is True
    assert at.session_state["rmfc_code"] == "abcdefgh"
    code_values = [c.value for c in at.code]
    assert sum("Starting xochitl" in v for v in code_values) == 1
    assert any("Install command output" in s.value for s in at.subheader)
    assert any(b.key == "ui_rmfc_new_code" for b in at.button)


def test_second_install_run_fully_replaces_first_output(tmp_path):
    """Re-running the install command replaces the previous output, leaving no stale duplicate.

    Regression guard: the live-streaming placeholder and the persisted-output
    display used to be two separate elements, so a second run's streaming
    placeholder didn't touch the first run's separate final block until the
    second run finished — leaving stale output visible in the meantime.
    """
    cfg_path = _cfg(tmp_path)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch(
            _RUN_INSTALL_PATCH,
            side_effect=[(True, "first run output"), (True, "second run output")],
        ),
        patch(_FETCH_CODE_PATCH, return_value=(True, "abcdefgh", "")),
    ):
        at = AppTest.from_file(APP_PY)
        at.run()
        at = _goto_page(at)
        at.button(key="ui_rmfc_repair").click().run()
        at.button(key="ui_rmfc_repair").click().run()

    assert not at.exception
    assert at.session_state["rmfc_install_output"] == "second run output"
    code_values = [c.value for c in at.code]
    assert code_values.count("second run output") == 1
    assert not any("first run output" in v for v in code_values)
    assert len([s for s in at.subheader if "Install command output" in s.value]) == 1


def test_install_failure_shows_output_and_error_without_fetching_code(tmp_path):
    """A failed install shows the captured output and an error, and skips the code fetch."""
    cfg_path = _cfg(tmp_path)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch(_RUN_INSTALL_PATCH, return_value=(False, "no such file\n")),
        patch(_FETCH_CODE_PATCH) as mock_fetch,
    ):
        at = AppTest.from_file(APP_PY)
        at.run()
        at = _goto_page(at)
        at.button(key="ui_rmfc_repair").click().run()

    assert not at.exception
    mock_fetch.assert_not_called()
    assert at.session_state["rmfc_install_ok"] is False
    assert "rmfc_code" not in at.session_state
    assert any(e for e in at.error)


def test_code_fetch_failure_after_successful_install_shows_error(tmp_path):
    """Install succeeding but the code fetch failing surfaces the fetch error, no code shown."""
    cfg_path = _cfg(tmp_path)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch(_RUN_INSTALL_PATCH, return_value=(True, "ok\n")),
        patch(_FETCH_CODE_PATCH, return_value=(False, "", "login failed")),
    ):
        at = AppTest.from_file(APP_PY)
        at.run()
        at = _goto_page(at)
        at.button(key="ui_rmfc_repair").click().run()

    assert not at.exception
    assert "rmfc_code" not in at.session_state
    assert at.session_state["rmfc_code_error"] == "login failed"
    assert any("login failed" in e.value for e in at.error)


# ---------------------------------------------------------------------------
# Get a new code
# ---------------------------------------------------------------------------


def test_get_new_code_only_calls_fetch_not_install(tmp_path):
    """Get a new code refreshes the pairing code without re-running the install command."""
    cfg_path = _cfg(tmp_path)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch(_RUN_INSTALL_PATCH, return_value=(True, "ok\n")) as mock_install,
        patch(_FETCH_CODE_PATCH, side_effect=[(True, "abcdefgh", ""), (True, "zzzzzzzz", "")]),
    ):
        at = AppTest.from_file(APP_PY)
        at.run()
        at = _goto_page(at)
        at.button(key="ui_rmfc_repair").click().run()
        assert at.session_state["rmfc_code"] == "abcdefgh"
        at.button(key="ui_rmfc_new_code").click().run()

    assert not at.exception
    assert mock_install.call_count == 1
    assert at.session_state["rmfc_code"] == "zzzzzzzz"


# ---------------------------------------------------------------------------
# Device-switch cleanup
# ---------------------------------------------------------------------------


def test_switching_device_clears_rmfc_state(tmp_path):
    """Selecting a different device clears the previous device's rmfakecloud page state.

    AppTest.switch_page() re-executes only the target page's script, not app.py's
    sidebar code (confirmed true even for an untouched existing page) — so the
    device switch is simulated directly via `selected_name`, the same session-state
    key the real sidebar selectbox would update, rather than the selectbox widget.
    """
    cfg_path = write_config(tmp_path, {"devices": {"D1": _device_cfg(), "D2": _device_cfg()}})
    with patch.dict(os.environ, make_env(tmp_path, cfg_path)):
        at = AppTest.from_file(APP_PY)
        at.run()
        at = _goto_page(at)
        at.session_state["rmfc_device"] = "D1"
        at.session_state["rmfc_code"] = "abcdefgh"
        at.session_state["rmfc_install_output"] = "some output"
        at.session_state["selected_name"] = "D2"
        at = _goto_page(at)

    assert not at.exception
    assert "rmfc_code" not in at.session_state
    assert "rmfc_install_output" not in at.session_state
    assert at.session_state["rmfc_device"] == "D2"


# ---------------------------------------------------------------------------
# Firmware-change redirect (sidebar SSH-test button)
# ---------------------------------------------------------------------------


def _new_fw_result():
    return {
        "ok": True,
        "device_type": "reMarkable 2",
        "firmware_version": "3.6.0.2000",
        "sleep_screen_enabled": False,
        "error": "",
    }


def test_firmware_change_redirects_when_rmfakecloud_enabled(tmp_path):
    """A detected firmware change on an rmfakecloud-enabled device redirects to the page."""
    cfg_path = _cfg(tmp_path)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch(_DETECT_PATCH, return_value=_new_fw_result()),
        patch(_SWITCH_PAGE_PATCH) as mock_switch,
    ):
        at = AppTest.from_file(APP_PY)
        at.run()
        at.button(key="sidebar_test_ssh").click().run()

    assert not at.exception
    mock_switch.assert_called_once_with("pages/rmfakecloud.py")


def test_firmware_change_redirect_lands_on_the_right_device_end_to_end(tmp_path):
    """Full, real st.switch_page() flow — not mocked — matching an actual reported bug.

    D1 (the default/first device, no rmfakecloud) is selected on load; the user
    then picks D2 (rmfakecloud-enabled) and runs the SSH test. Regression guard:
    with app.py gating the nav page on the *currently selected* device instead of
    "any device has it enabled", this redirect silently landed back on the
    default "Images" page instead of pages/rmfakecloud.py.
    """
    cfg_path = write_config(
        tmp_path,
        {
            "devices": {
                "D1": _device_cfg(rmfakecloud_enabled=False, firmware_version=""),
                "D2": _device_cfg(),
            }
        },
    )
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch(_DETECT_PATCH, return_value=_new_fw_result()),
    ):
        at = AppTest.from_file(APP_PY)
        at.run()
        at.selectbox(key="device").set_value("D2").run()
        at.button(key="sidebar_test_ssh").click().run()

    assert not at.exception
    assert at.title[0].value == "rmfakecloud"
    assert at.session_state["device"] == "D2"
    assert at.session_state["selected_name"] == "D2"


_RECOVER_INVALID_SELECTION_SCRIPT = """
import streamlit as st
from src.config_ui import _recover_invalid_device_selection

st.session_state["result"] = _recover_invalid_device_selection(["D1", "D2"])
"""


def test_invalid_device_recovers_from_selected_name_not_first_device():
    """A device becoming invalid (e.g. after st.switch_page() resets query params)

    must recover to the last-known device (selected_name), not silently fall back
    to the first device in the list — regression guard for the real bug where a
    firmware-change redirect landed the user on the wrong device's rmfakecloud page.
    Exercised as a standalone function: AppTest validates a selectbox's session_state
    value against its last-rendered options before any app code runs, so this
    specific "the value became invalid" precondition can't be simulated through
    the real widget.
    """
    at = AppTest.from_string(_RECOVER_INVALID_SELECTION_SCRIPT)
    at.session_state["selected_name"] = "D2"
    at.run()

    assert not at.exception
    assert at.session_state["result"] == "D2"


def test_invalid_device_falls_back_to_first_when_selected_name_also_invalid():
    """With no valid last-known device either, falls back to the first device."""
    at = AppTest.from_string(_RECOVER_INVALID_SELECTION_SCRIPT)
    at.session_state["selected_name"] = "D_deleted"
    at.run()

    assert not at.exception
    assert at.session_state["result"] == "D1"


def test_firmware_change_does_not_redirect_when_disabled(tmp_path):
    """A firmware change on a device without rmfakecloud enabled does not redirect."""
    cfg_path = _cfg(tmp_path, rmfakecloud_enabled=False)
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch(_DETECT_PATCH, return_value=_new_fw_result()),
        patch(_SWITCH_PAGE_PATCH) as mock_switch,
    ):
        at = AppTest.from_file(APP_PY)
        at.run()
        at.button(key="sidebar_test_ssh").click().run()

    assert not at.exception
    mock_switch.assert_not_called()


def test_first_ever_detection_does_not_redirect(tmp_path):
    """A device with no previously known firmware version never triggers a redirect."""
    cfg_path = _cfg(tmp_path, firmware_version="")
    with (
        patch.dict(os.environ, make_env(tmp_path, cfg_path)),
        patch(_DETECT_PATCH, return_value=_new_fw_result()),
        patch(_SWITCH_PAGE_PATCH) as mock_switch,
    ):
        at = AppTest.from_file(APP_PY)
        at.run()
        at.button(key="sidebar_test_ssh").click().run()

    assert not at.exception
    mock_switch.assert_not_called()
