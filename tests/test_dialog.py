from unittest.mock import MagicMock, patch
import src.dialog as dialog_mod


def _make_columns_mock(cancel_clicked: bool, confirm_clicked: bool):
    """Return (c_cancel, c_ok) mocks matching the 5-column layout in dialog.py."""
    c_cancel, c_ok = MagicMock(), MagicMock()
    c_cancel.button.return_value = cancel_clicked
    c_ok.button.return_value = confirm_clicked
    return c_cancel, c_ok


def _patched_st(cancel_clicked: bool, confirm_clicked: bool, initial_state=None):
    """Context manager that patches src.dialog.st with controllable buttons."""
    st = MagicMock()
    st.session_state = {} if initial_state is None else initial_state
    # st.dialog(title) must act as a no-op decorator so _dialog() runs directly
    st.dialog.side_effect = lambda title: lambda fn: fn
    c_cancel, c_ok = _make_columns_mock(cancel_clicked, confirm_clicked)
    st.columns.return_value = (MagicMock(), c_cancel, MagicMock(), c_ok, MagicMock())
    return patch("src.dialog.st", st), st


def test_confirm_no_click_leaves_state_unchanged():
    patcher, st = _patched_st(cancel_clicked=False, confirm_clicked=False)
    with patcher:
        dialog_mod.confirm("Titre", "Message", key="k")

    assert "k" not in st.session_state
    st.rerun.assert_not_called()


def test_confirm_cancel_sets_false():
    patcher, st = _patched_st(cancel_clicked=True, confirm_clicked=False)
    with patcher:
        dialog_mod.confirm("Titre", "Message", key="k")

    assert st.session_state["k"] is False
    st.rerun.assert_called_once()


def test_confirm_ok_sets_true():
    patcher, st = _patched_st(cancel_clicked=False, confirm_clicked=True)
    with patcher:
        dialog_mod.confirm("Titre", "Message", key="k")

    assert st.session_state["k"] is True
    st.rerun.assert_called_once()


def test_confirm_uses_custom_key():
    """State is written under the supplied key, leaving other keys untouched."""
    patcher, st = _patched_st(cancel_clicked=False, confirm_clicked=True,
                               initial_state={"other": "unchanged"})
    with patcher:
        dialog_mod.confirm("Titre", "Message", key="my_key")

    assert st.session_state["my_key"] is True
    assert st.session_state["other"] == "unchanged"


def test_confirm_message_is_displayed():
    patcher, st = _patched_st(cancel_clicked=False, confirm_clicked=False)
    with patcher:
        dialog_mod.confirm("My Title", "Hello world", key="k")

    st.dialog.assert_called_once_with("My Title")
    st.write.assert_called_once_with("Hello world")
