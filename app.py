import importlib
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
from src import ui as _ui


# Session logging helper (module-level so UI and non-UI code can use it)
def add_log(message: str):
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


def _sidebar_version(version):
    if not version:
        return
    html = (
        f'<div style="position:fixed;left:20px;bottom:8px;font-size:12px;">'
        f'<a href="https://github.com/dapitch666/rm-manager" target="_blank" '
        f'style="color:rgba(0,0,0,0.6);text-decoration:none;">'
        f"rm-manager - version {version}</a></div>"
    )
    try:
        st.sidebar.html(html)
    except Exception:
        st.sidebar.caption(f"rm-manager version {version}")


def _debug_overlay():
    try:
        debug_mode = (BASE_DIR != "/app") or os.environ.get("DEBUG", "").lower() in ("1", "true", "yes")
    except Exception:
        debug_mode = False
    if not debug_mode:
        return

    # Sidebar expander is the reliable fallback; always shown in debug mode.
    try:
        st.sidebar.expander("session_state (debug)", expanded=False).write(dict(st.session_state))
    except Exception:
        pass

    # Additionally inject a floating overlay for quick in-page inspection.
    try:
        import json, html as _pyhtml
        safe = _pyhtml.escape(json.dumps(dict(st.session_state), default=str, indent=2))
        st.markdown(
            f'<div style="position:fixed;right:8px;top:8px;max-width:420px;max-height:45vh;'
            f'overflow:auto;background:rgba(255,255,255,0.95);border:1px solid rgba(0,0,0,0.12);'
            f'padding:8px;font-size:12px;z-index:99999;font-family:monospace;'
            f'box-shadow:0 4px 12px rgba(0,0,0,0.08);">'
            f"<details><summary style='font-weight:600;cursor:pointer'>session_state (debug)</summary>"
            f"<pre style='white-space:pre-wrap;margin:6px 0 0 0;'>{safe}</pre>"
            f"</details></div>",
            unsafe_allow_html=True,
        )
    except Exception:
        pass


def main():
    # Re-execute src.ui on every render so that test patches applied to
    # src.images.* / src.ssh.* are picked up (those modules use from-imports).
    importlib.reload(_ui)

    st.set_page_config(page_title="rM Manager", page_icon="assets/favicon.png")
    st.logo(image="assets/logo.svg", size="large")

    st.session_state.setdefault("logs", [])
    config = load_config()

    page = st.sidebar.radio(
        "Navigation",
        [
            ":material/mobile_gear: Gestion des tablettes",
            ":material/settings: Configuration",
            ":material/description: Logs",
        ],
    )

    if page == ":material/description: Logs":
        _ui.render_logs_page()
    elif page == ":material/settings: Configuration":
        _ui.render_config_page(config, save_config, add_log, resolve_device_type, DEFAULT_DEVICE_TYPE)
    else:
        _ui.render_main_page(config, save_config, add_log, resolve_device_type, BASE_DIR)

    _sidebar_version(_read_version())
    _debug_overlay()


if __name__ == "__main__":
    main()
