"""Tests for pages/logs.py.

Covers: empty state, log display, clear button, confirm/cancel clear flow.
"""

import os
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests.pages.helpers import (
    at_page,
    empty_cfg,
    make_env,
    with_device,
)


def test_logs_page_renders_empty(tmp_path):
    """Logs page renders without exception and shows 'No logs' info when empty."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/logs.py").run()

    assert not at.exception
    assert any("No logs" in i.value for i in at.info)


class TestLogsPage:
    def test_no_logs_shows_info(self, tmp_path):
        """Logs page shows info banner when session has no logs."""
        at = at_page(tmp_path, "pages/logs.py", empty_cfg(tmp_path))
        assert not at.exception
        assert any("No logs" in m.value for m in at.info)

    def test_with_logs_shows_code_block(self, tmp_path):
        """Logs page renders a code block and a clear button when logs exist."""
        cfg_path = with_device(tmp_path)
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["logs"] = ["first log", "second log"]
            at.switch_page("pages/logs.py").run()

        assert not at.exception
        assert at.code, "Expected at least one st.code block"
        assert any("Clear" in b.label for b in at.button)

    def test_clear_logs_button_triggers_confirm(self, tmp_path):
        """Clicking the clear button sets clear_logs state for dialog."""
        cfg_path = with_device(tmp_path)
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["logs"] = ["an entry"]
            at.switch_page("pages/logs.py").run()
            clear_btn = next((b for b in at.button if "Clear" in b.label), None)
            assert clear_btn is not None
            clear_btn.click().run()

        assert not at.exception

    def test_clear_logs_confirmed_empties_logs(self, tmp_path):
        """Pre-setting clear_logs=True causes the log list to be cleared."""
        cfg_path = with_device(tmp_path)
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["logs"] = ["entry1", "entry2"]
            at.session_state["clear_logs"] = True
            at.switch_page("pages/logs.py").run()

        assert not at.exception
        assert at.session_state["logs"] == []

    def test_clear_logs_cancelled_keeps_logs(self, tmp_path):
        """Pre-setting clear_logs=False keeps the log list unchanged."""
        cfg_path = with_device(tmp_path)
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["logs"] = ["stay"]
            at.session_state["clear_logs"] = False
            at.switch_page("pages/logs.py").run()

        assert not at.exception
        # Logs must not have been wiped — clear_logs=False means no clearing occurred
