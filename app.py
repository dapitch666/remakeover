import html as _pyhtml
import json
import os
from contextlib import suppress
from datetime import datetime

import streamlit as st

from src.config import (
    BASE_DIR,
    load_config,
)


# ── Session logging helper ────────────────────────────────────────────────────
def _add_log(message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"{ts} - {message}"
    try:
        st.session_state.setdefault("logs", []).append(entry)
    except Exception:
        print(entry)


def _read_version():
    version = os.environ.get("IMAGE_VERSION")
    if version:
        return version
    try:
        with open(os.path.join(BASE_DIR, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return None


def _inject_css():
    st.html(
        "<style>"
        "   [data-testid='stSidebarNavLink'] span {"
        "       font-size: 1.1rem;"
        "   }"
        "   .block-container {"
        "       max-width: 65rem;"
        "       padding-top: 3rem;"
        "   }"
        "</style>"
    )


def _sidebar_version(version):
    if not version:
        return
    html = (
        f'<div style="position:fixed;left:20px;bottom:8px">'
        f'  <a href="https://github.com/dapitch666/rm-manager" target="_blank">'
        f"      rm-manager - version {version}"
        f"  </a>"
        f"</div>"
    )
    st.sidebar.caption(html, unsafe_allow_html=True)


def _debug_overlay():
    try:
        debug_mode = (BASE_DIR != "/app") or os.environ.get("DEBUG", "").lower() in (
            "1",
            "true",
            "yes",
        )
    except Exception:
        debug_mode = False
    if not debug_mode:
        return

    with suppress(Exception):
        st.sidebar.expander("session_state (debug)", expanded=False).write(dict(st.session_state))

    with suppress(Exception):
        safe = _pyhtml.escape(json.dumps(dict(st.session_state), default=str, indent=2))
        st.html(
            f'<div style="position:fixed;right:8px;top:8px;max-width:420px;max-height:45vh;'
            f"overflow:auto;background:rgba(255,255,255,0.95);border:1px solid rgba(0,0,0,0.12);"
            f"padding:8px;font-size:12px;z-index:99999;font-family:monospace;"
            f'box-shadow:0 4px 12px rgba(0,0,0,0.08);">'
            f"<details><summary style='font-weight:600;cursor:pointer'>session_state (debug)</summary>"
            f"<pre style='white-space:pre-wrap;margin:6px 0 0 0;'>{safe}</pre>"
            f"</details></div>"
        )


def main():
    st.set_page_config(
        page_title="rM Manager",
        page_icon="assets/favicon.png",
        layout="centered",
        initial_sidebar_state="expanded",
    )
    st.logo(image="assets/logo.svg", size="large")

    # ── Shared session state ──────────────────────────────────────────────
    st.session_state.setdefault("logs", [])
    st.session_state["add_log"] = _add_log
    st.session_state["BASE_DIR"] = BASE_DIR

    config = load_config()
    st.session_state["config"] = config

    # ── Navigation ────────────────────────────────────────────────────────
    config_page = st.Page(
        "pages/configuration.py", title="Configuration", icon=":material/settings:"
    )
    pages = [
        st.Page("pages/images.py", title="Images", icon=":material/image:"),
        st.Page("pages/templates.py", title="Templates", icon=":material/description:"),
        st.Page("pages/deploiement.py", title="Déploiement", icon=":material/rocket_launch:"),
        config_page,
        st.Page("pages/logs.py", title="Logs", icon=":material/list:"),
    ]

    pg = st.navigation(pages)

    # ── Sidebar: tablet selector (appears below the navigation menu) ──────
    DEVICES = config.get("devices", {})
    if DEVICES:
        device_names = list(DEVICES.keys())

        # Restore selection from URL query param on fresh loads,
        # or from a pending selection set by another page (e.g. after saving a new device).
        if "selected_tablet_select" not in st.session_state:
            pending = st.session_state.pop("pending_selected_tablet", None)
            saved = pending or st.query_params.get("tablet")
            if saved and saved in device_names:
                st.session_state["selected_tablet_select"] = saved
        else:
            # Consume any pending selection even when the widget key already exists.
            pending = st.session_state.pop("pending_selected_tablet", None)
            if pending and pending in device_names:
                st.session_state["selected_tablet_select"] = pending

        with st.sidebar:
            from src.models import Device as _Device
            from src.ssh import ssh_connectivity_test

            col1, col2 = st.columns([4, 1], vertical_alignment="bottom")
            with col1:
                selected_name = st.selectbox(
                    "Tablette",
                    device_names,
                    key="selected_tablet_select",
                )
            with col2:
                if st.button(
                    ":material/wifi:",
                    key="sidebar_test_ssh",
                    help="Tester la connexion SSH",
                ):
                    _device = _Device.from_dict(selected_name, DEVICES[selected_name])
                    ok, err = ssh_connectivity_test(_device.ip, _device.password or "")
                    if ok:
                        st.toast(":green[Connexion SSH OK]", icon=":material/task_alt:")
                        _add_log(f"SSH connection successful to '{selected_name}'")
                    else:
                        st.toast(f":red[Connexion SSH impossible : {err}]", icon=":material/error:")
                        _add_log(f"SSH connection failed to '{selected_name}': {err}")

        # Persist selection in URL and session state for pages to consume.
        st.query_params["tablet"] = selected_name
        st.session_state["selected_name"] = selected_name
    else:
        st.session_state["selected_name"] = None
        # On the very first visit with no devices configured, send the user
        # straight to the configuration page.  The flag prevents the redirect
        # from firing again for the rest of the session (so the warning pages
        # remain reachable via the sidebar navigation if the user wants to).
        if pg is not config_page and not st.session_state.get("_auto_config_redirect"):
            st.session_state["_auto_config_redirect"] = True
            st.switch_page(config_page)

    _inject_css()
    _sidebar_version(_read_version())
    _debug_overlay()

    from src.ui_common import show_deferred_toast

    show_deferred_toast()

    pg.run()


if __name__ == "__main__":
    main()
