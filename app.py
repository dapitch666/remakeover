import streamlit as st
import os
from datetime import datetime

from src.config import (
    BASE_DIR,
    DEFAULT_DEVICE_TYPE,
    load_config,
    save_config,
    resolve_device_type,
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
        "[data-testid='stSidebarNavLink'] span {"
        "    font-size: 1.1rem !important;"
        "}"
        "</style>"
    )


def _sidebar_version(version):
    if not version:
        return
    html = (
        f'<div style="position:fixed;left:20px;bottom:8px;font-size:12px;">'
        f'<a href="https://github.com/dapitch666/rm-manager" target="_blank" '
        f'style="color:rgba(0,0,0,0.6);text-decoration:none;">'
        f"rm-manager - version {version}</a></div>"
    )
    st.sidebar.html(html)



def _debug_overlay():
    try:
        debug_mode = (BASE_DIR != "/app") or os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")
    except Exception:
        debug_mode = False
    if not debug_mode:
        return

    try:
        st.sidebar.expander("session_state (debug)", expanded=False).write(dict(st.session_state))
    except Exception:
        pass

    try:
        import json, html as _pyhtml
        safe = _pyhtml.escape(json.dumps(dict(st.session_state), default=str, indent=2))
        st.html(
            f'<div style="position:fixed;right:8px;top:8px;max-width:420px;max-height:45vh;'
            f'overflow:auto;background:rgba(255,255,255,0.95);border:1px solid rgba(0,0,0,0.12);'
            f'padding:8px;font-size:12px;z-index:99999;font-family:monospace;'
            f'box-shadow:0 4px 12px rgba(0,0,0,0.08);">'
            f"<details><summary style='font-weight:600;cursor:pointer'>session_state (debug)</summary>"
            f"<pre style='white-space:pre-wrap;margin:6px 0 0 0;'>{safe}</pre>"
            f"</details></div>"
        )
    except Exception:
        pass


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
    st.session_state["save_config"] = save_config
    st.session_state["resolve_device_type"] = resolve_device_type
    st.session_state["DEFAULT_DEVICE_TYPE"] = DEFAULT_DEVICE_TYPE

    # ── Navigation ────────────────────────────────────────────────────────
    pages = [
        st.Page("pages/images.py", title="Images", icon=":material/image:"),
        st.Page("pages/templates.py", title="Templates", icon=":material/description:"),
        st.Page("pages/deploiement.py", title="Déploiement", icon=":material/rocket_launch:"),
        st.Page("pages/configuration.py", title="Configuration", icon=":material/settings:"),
        st.Page("pages/logs.py", title="Logs", icon=":material/list:"),
    ]

    pg = st.navigation(pages)

    # ── Sidebar: tablet selector (appears below the navigation menu) ──────
    DEVICES = config.get("devices", {})
    if DEVICES:
        device_names = list(DEVICES.keys())

        # Restore selection from URL query param on fresh loads.
        if "selected_tablet_select" not in st.session_state:
            saved = st.query_params.get("tablet")
            if saved and saved in device_names:
                st.session_state["selected_tablet_select"] = saved

        with st.sidebar:
            from src.ssh import test_ssh_connection
            from src.models import Device as _Device

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
                    ok, err = test_ssh_connection(_device.ip, _device.password or "")
                    if ok:
                        st.toast("Connexion SSH OK", icon=":material/task_alt:")
                        _add_log(f"SSH connection successful to '{selected_name}'")
                    else:
                        st.toast(f"Connexion SSH impossible : {err}", icon=":material/error:")
                        _add_log(f"SSH connection failed to '{selected_name}': {err}")

        # Persist selection in URL and session state for pages to consume.
        st.query_params["tablet"] = selected_name
        st.session_state["selected_name"] = selected_name
    else:
        st.session_state["selected_name"] = None

    _inject_css()
    _sidebar_version(_read_version())
    _debug_overlay()

    pg.run()


if __name__ == "__main__":
    main()
