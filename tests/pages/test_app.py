"""Tests for the main app entry-point (app.py) behaviour.

Covers: initial render, auto-redirect to configuration, sidebar state propagation.
"""

import os
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests.pages.helpers import (
    empty_cfg,
    make_env,
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
    assert at.session_state["selected_tablet_select"] == "D2"
    assert "pending_selected_tablet" not in at.session_state
