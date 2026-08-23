"""rmfakecloud re-pairing panel UI — install command output and verification code display."""

from collections.abc import Callable

import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from src.i18n import _
from src.models import Device
from src.rmfakecloud import fetch_pairing_code, run_install


def _render_boxed_code(code: str) -> None:
    """Render *code* as a row of individual boxed/tiled characters."""
    boxes = "".join(f'<div class="rmfc-code-box">{ch}</div>' for ch in code)
    st.html(
        "<style>"
        ".rmfc-code-row { display: flex; gap: 0.5rem; }"
        ".rmfc-code-box {"
        "  font-size: 1.75rem;"
        "  border: 1px solid rgba(128, 128, 128, 0.45);"
        "  border-radius: 8px;"
        "  width: 2.5rem; height: 3.25rem;"
        "  display: flex; justify-content: center;"
        "  background: rgba(128, 128, 128, 0.08);"
        "}"
        "</style>"
        f'<div class="rmfc-code-row">{boxes}</div>'
    )


def _render_install_output(placeholder: DeltaGenerator) -> None:
    """Render the persisted install output/error into *placeholder*, as one atomic unit.

    Called both to show a prior run's persisted output and, via _run_install(),
    to redraw the final state after a live run completes — always through the
    same placeholder so a subsequent run's own atomic redraws (see _run_install)
    can never leave this stale while they're in progress.
    """
    with placeholder.container():
        output = st.session_state.get("rmfc_install_output")
        if output is None:
            return
        st.subheader(_(":material/terminal: Install command output"), divider="rainbow")
        st.code(output, language=None)
        if st.session_state.get("rmfc_install_ok") is False:
            st.error(_("Install command failed — see output above."), icon=":material/error:")


def _run_install(
    device: Device, add_log: Callable[[str], None], placeholder: DeltaGenerator
) -> None:
    """Run the install command, live-updating *placeholder* as output arrives.

    Every chunk redraws the subheader + accumulated output together as one
    atomic unit into the *same* placeholder used for the persisted/final
    display — a chunk-only update would leave a *different*, not-yet-reached
    element (the subheader) missing until the run finishes, and would leave a
    previous run's separate final block stale below it on a re-run.
    """
    st.session_state.pop("rmfc_code", None)
    st.session_state.pop("rmfc_code_error", None)

    lines: list[str] = []

    def _on_chunk(text: str) -> None:
        lines.append(text)
        with placeholder.container():
            st.subheader(_(":material/terminal: Install command output"), divider="rainbow")
            st.code("".join(lines), language=None)

    ok, output = run_install(device, on_chunk=_on_chunk)
    st.session_state["rmfc_install_output"] = output
    st.session_state["rmfc_install_ok"] = ok
    _render_install_output(placeholder)

    if not ok:
        add_log(f"rmfakecloud install failed on '{device.name}'")
        return

    add_log(f"rmfakecloud install succeeded on '{device.name}'")
    code_ok, code, error = fetch_pairing_code(
        device.rmfakecloud_url, device.rmfakecloud_email, device.rmfakecloud_password
    )
    if code_ok:
        st.session_state["rmfc_code"] = code
        add_log(f"rmfakecloud verification code generated for '{device.name}'")
    else:
        st.session_state["rmfc_code_error"] = error
        add_log(f"rmfakecloud verification code fetch failed for '{device.name}': {error}")


def _refresh_code(device: Device, add_log: Callable[[str], None]) -> None:
    """Fetch a fresh verification code without re-running the install command."""
    code_ok, code, error = fetch_pairing_code(
        device.rmfakecloud_url, device.rmfakecloud_email, device.rmfakecloud_password
    )
    if code_ok:
        st.session_state["rmfc_code"] = code
        st.session_state.pop("rmfc_code_error", None)
        add_log(f"rmfakecloud verification code refreshed for '{device.name}'")
    else:
        st.session_state.pop("rmfc_code", None)
        st.session_state["rmfc_code_error"] = error
        add_log(f"rmfakecloud verification code refresh failed for '{device.name}': {error}")


def _display_code() -> None:
    """Render the persisted verification code/error and the "Get a new code" control."""
    code = st.session_state.get("rmfc_code")
    code_error = st.session_state.get("rmfc_code_error")
    if code:
        st.subheader(_(":material/lock_open: Verification code"), divider="rainbow")

        with st.container(
            horizontal=True, width="content", vertical_alignment="center", gap="medium"
        ):
            st.info(_("Settings → General → Account → Pair"), icon=":material/settings:")
            _render_boxed_code(code)

            def _on_new_code_click():
                st.session_state["rmfc_code_pending"] = True

            st.button(
                _("Get a new code"),
                key="ui_rmfc_new_code",
                icon=":material/cached:",
                help=_("Fetch a fresh verification code without re-running the install command"),
                on_click=_on_new_code_click,
            )
    elif code_error:
        st.error(
            _("Could not get a verification code: {error}").format(error=code_error),
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
            "Runs the install command over SSH, then fetches a fresh verification code from rmfakecloud."
        )
    )

    def _on_repair_click():
        st.session_state["rmfc_install_pending"] = True

    st.button(
        _("Re-pair now"),
        key="ui_rmfc_repair",
        icon=":material/cloud_sync:",
        type="primary",
        help=_("Run the install command over SSH and fetch a fresh verification code"),
        on_click=_on_repair_click,
    )

    output_placeholder = st.empty()
    if st.session_state.pop("rmfc_install_pending", False):
        _run_install(device, add_log, output_placeholder)
    else:
        _render_install_output(output_placeholder)

    _display_code()
