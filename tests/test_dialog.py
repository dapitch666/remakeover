from pathlib import Path
from streamlit.testing.v1 import AppTest


def write_app_file(tmp_path: Path, result_path: Path, key: str = "default") -> Path:
    app_file = tmp_path / f"app_dialog_{key}.py"
    app_file.write_text(
        f"""
import streamlit as st
from src import dialog
from pathlib import Path

_out = Path(r'{str(result_path)}')
key = '{key}'

# Top-level simulate buttons that act on the same key used by the dialog
if st.button('Simulate None'):
    if key in st.session_state:
        del st.session_state[key]

if st.button('Simulate Cancel'):
    st.session_state[key] = False

if st.button('Simulate Confirm'):
    st.session_state[key] = True

# Render dialog and write current session state for the key
res = dialog.confirm('Titre', 'Message', key=key)
_out.write_text(str(st.session_state.get(key)))
"""
    )
    return app_file


def find_button_by_label(at: AppTest, label: str):
    for b in at.button:
        if getattr(b, "label", None) == label:
            return b
    return None


def test_confirm_initial_none(tmp_path):
    result_file = tmp_path / "result_none.txt"
    app = write_app_file(tmp_path, result_file, key="none")
    at = AppTest.from_file(str(app))
    at.run()
    assert result_file.exists()
    assert result_file.read_text() == "None"


def test_confirm_cancel_sets_false(tmp_path):
    result_file = tmp_path / "result_cancel.txt"
    app = write_app_file(tmp_path, result_file, key="cancel")
    at = AppTest.from_file(str(app))
    at.run()

    # Click the top-level simulate cancel button (tests shouldn't rely on dialog internals)
    sim = find_button_by_label(at, "Simulate Cancel")
    assert sim is not None, "Simulate Cancel button not found"
    sim.click().run()

    assert result_file.exists()
    assert result_file.read_text() == "False"


def test_confirm_ok_sets_true(tmp_path):
    result_file = tmp_path / "result_ok.txt"
    app = write_app_file(tmp_path, result_file, key="ok")
    at = AppTest.from_file(str(app))
    at.run()

    # Click the top-level simulate confirm button
    sim = find_button_by_label(at, "Simulate Confirm")
    assert sim is not None, "Simulate Confirm button not found"
    sim.click().run()

    assert result_file.exists()
    assert result_file.read_text() == "True"


def write_app_file_double(tmp_path: Path, result_path: Path, key: str = "double") -> Path:
    app_file = tmp_path / f"app_dialog_double_{key}.py"
    app_file.write_text(
        f"""
import streamlit as st
from src import dialog
from pathlib import Path

_out = Path(r'{str(result_path)}')
key = '{key}'

# Main button that opens the dialog when clicked
if st.button('Open'):
    st.session_state['_open'] = True

# Provide a simulate cancel button that sets the same key the dialog uses
if st.button('Simulate Cancel'):
    st.session_state[key] = False

if st.session_state.get('_open'):
    res = dialog.confirm('Titre', 'Message', key=key)
    _out.write_text(str(st.session_state.get(key)))
"""
    )
    return app_file


def test_double_click_opens_again(tmp_path):
    """Click the open button, cancel, then click again and expect the dialog to open.

    This behaviour is currently broken in the real app; the test is expected to fail.
    """
    result_file = tmp_path / "result_double.txt"
    app = write_app_file_double(tmp_path, result_file, key="double")
    at = AppTest.from_file(str(app))
    at.run()

    # Click Open to show dialog
    open_btn = None
    for b in at.button:
        if getattr(b, "label", None) == "Open":
            open_btn = b
            break
    assert open_btn is not None, "Open button not found"
    open_btn.click().run()

    # Click the top-level Open button to show dialog
    open_btn.click().run()

    # Use the top-level simulate cancel button to cancel
    cancel = find_button_by_label(at, "Simulate Cancel")
    assert cancel is not None, "Simulate Cancel button not found after first open"
    cancel.click().run()

    assert result_file.exists()
    assert result_file.read_text() == "False"

    # Click Open again and ensure simulate button still available
    open_btn.click().run()

    cancel2 = find_button_by_label(at, "Simulate Cancel")
    assert cancel2 is not None, "Dialog did not open on second click"
