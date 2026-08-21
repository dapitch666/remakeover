"""rmfakecloud re-pairing panel UI — install command output and pairing code display."""

from collections.abc import Callable

import streamlit as st

from src.i18n import _
from src.models import Device
from src.rmfakecloud import fetch_pairing_code, run_install


def _render_boxed_code(code: str) -> None:
    """Render *code* as a row of individual boxed/tiled characters."""
    boxes = "".join(f'<div class="rmfc-code-box">{ch}</div>' for ch in code)
    st.html(
        "<style>"
        ".rmfc-code-row { display: flex; gap: 0.5rem; margin: 0.5rem 0 1.25rem 0; }"
        ".rmfc-code-box {"
        "  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', monospace;"
        "  font-size: 1.75rem; font-weight: 700; text-transform: uppercase;"
        "  letter-spacing: 0;"
        "  border: 2px solid rgba(128, 128, 128, 0.45);"
        "  border-radius: 8px;"
        "  width: 2.5rem; height: 3.25rem;"
        "  display: flex; align-items: center; justify-content: center;"
        "  background: rgba(128, 128, 128, 0.08);"
        "}"
        "</style>"
        f'<div class="rmfc-code-row">{boxes}</div>'
    )


def _display_install_output() -> None:
    """Render the persisted install output/error, whether just-produced or from a prior run."""
    output = st.session_state.get("rmfc_install_output")
    if output is None:
        return
    st.caption(_("Install command output"))
    st.code(output, language=None)
    if st.session_state.get("rmfc_install_ok") is False:
        st.error(_("Install command failed — see output above."), icon=":material/error:")


def _run_install(device: Device, add_log: Callable[[str], None]) -> None:
    """Run the install command with a live-updating output placeholder."""
    st.session_state.pop("rmfc_code", None)
    st.session_state.pop("rmfc_code_error", None)

    placeholder = st.empty()
    lines: list[str] = []

    def _on_chunk(text: str) -> None:
        lines.append(text)
        placeholder.code("".join(lines), language=None)

    ok, output = run_install(device, on_chunk=_on_chunk)
    placeholder.empty()  # the unconditional _display_install_output() below takes over
    st.session_state["rmfc_install_output"] = output
    st.session_state["rmfc_install_ok"] = ok

    if not ok:
        add_log(f"rmfakecloud install failed on '{device.name}'")
        return

    add_log(f"rmfakecloud install succeeded on '{device.name}'")
    code_ok, code, error = fetch_pairing_code(
        device.rmfakecloud_url, device.rmfakecloud_email, device.rmfakecloud_password
    )
    if code_ok:
        st.session_state["rmfc_code"] = code
        add_log(f"rmfakecloud pairing code generated for '{device.name}'")
    else:
        st.session_state["rmfc_code_error"] = error
        add_log(f"rmfakecloud pairing code fetch failed for '{device.name}': {error}")


def _refresh_code(device: Device, add_log: Callable[[str], None]) -> None:
    """Fetch a fresh pairing code without re-running the install command."""
    code_ok, code, error = fetch_pairing_code(
        device.rmfakecloud_url, device.rmfakecloud_email, device.rmfakecloud_password
    )
    if code_ok:
        st.session_state["rmfc_code"] = code
        st.session_state.pop("rmfc_code_error", None)
        add_log(f"rmfakecloud pairing code refreshed for '{device.name}'")
    else:
        st.session_state.pop("rmfc_code", None)
        st.session_state["rmfc_code_error"] = error
        add_log(f"rmfakecloud pairing code refresh failed for '{device.name}': {error}")


def _display_code() -> None:
    """Render the persisted pairing code/error and the "Get a new code" control."""
    code = st.session_state.get("rmfc_code")
    code_error = st.session_state.get("rmfc_code_error")
    if code:
        st.success(
            _("Pairing code — enter it now on the device (expires in 5 minutes):"),
            icon=":material/lock_open:",
        )
        _render_boxed_code(code)

        def _on_new_code_click():
            st.session_state["rmfc_code_pending"] = True

        st.button(
            _("Get a new code"),
            key="ui_rmfc_new_code",
            icon=":material/refresh:",
            help=_("Fetch a fresh pairing code without re-running the install command"),
            on_click=_on_new_code_click,
        )
    elif code_error:
        st.error(
            _("Could not get a pairing code: {error}").format(error=code_error),
            icon=":material/error:",
        )


def render_rmfakecloud_page(device: Device, add_log: Callable[[str], None]) -> None:
    """Render the rmfakecloud re-pairing panel for *device*."""
    # Pending actions are processed first so this run's display reflects their
    # outcome immediately, whether just-produced or persisted from an earlier run.
    if st.session_state.pop("rmfc_code_pending", False):
        _refresh_code(device, add_log)

    st.markdown(
        _(
            "Runs the install command over SSH, then fetches a fresh pairing code from "
            "rmfakecloud. Enter the code on the device within 5 minutes: "
            "Settings → General → Account → Pair with the reMarkable Cloud."
        )
    )

    def _on_repair_click():
        st.session_state["rmfc_install_pending"] = True

    st.button(
        _("Re-pair now"),
        key="ui_rmfc_repair",
        icon=":material/sync_lock:",
        type="primary",
        help=_("Run the install command over SSH and fetch a fresh pairing code"),
        on_click=_on_repair_click,
    )

    if st.session_state.pop("rmfc_install_pending", False):
        _run_install(device, add_log)

    _display_install_output()
    _display_code()
