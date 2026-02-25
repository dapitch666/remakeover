import streamlit as st
import os
import json
from datetime import datetime

from src.config import (
    BASE_DIR,
    DEFAULT_DEVICE_TYPE,
    load_config,
    save_config,
    resolve_device_type,
)


# Session logging helper (module-level so UI and non-UI code can use it)
def add_log(message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Ensure logs list exists
    try:
        if 'logs' not in st.session_state:
            st.session_state['logs'] = []
        st.session_state['logs'].append(f"{ts} - {message}")
    except Exception:
        # When called outside of Streamlit runtime, fallback to printing
        try:
            print(f"{ts} - {message}")
        except Exception:
            pass


# UI adapter used by `run_maintenance` to update Streamlit UI elements.
# Defined at module level so it can be referenced outside `main()`.
class UIAdapter:
    def __init__(self, status_obj, progress_obj):
        self._status = status_obj
        self._progress = progress_obj

    def step(self, msg: str):
        try:
            self._status.text(msg)
        except Exception:
            pass
        add_log(msg)

    def progress(self, pct: int):
        try:
            self._progress.progress(pct)
        except Exception:
            pass

    def toast(self, msg: str):
        try:
            st.toast(msg, icon=":material/task_alt:")
        except Exception:
            pass

def main():
    st.set_page_config(page_title="rM Manager", page_icon="assets/favicon.png")
    st.logo(image="assets/logo.svg", size="large")

    # Display the image version if provided via environment or a VERSION file
    IMAGE_VERSION = os.environ.get("IMAGE_VERSION")
    if not IMAGE_VERSION:
        try:
            with open(os.path.join(BASE_DIR, "VERSION"), "r", encoding="utf-8") as vf:
                IMAGE_VERSION = vf.read().strip()
        except Exception:
            IMAGE_VERSION = None

    # --- SESSION LOGS ---
    if 'logs' not in st.session_state:
        st.session_state['logs'] = []

    # Load configuration
    config = load_config()

    # Navigation
    # Load UI module dynamically from src/ui.py to avoid package import issues
    import importlib.util
    import sys
    ui_path = os.path.join(BASE_DIR, "src", "ui.py")
    # Load the UI module by file path but register it as `src.ui` so
    # internal imports like `from src.models import Device` resolve
    try:
        spec = importlib.util.spec_from_file_location("src.ui", ui_path)
        ui = importlib.util.module_from_spec(spec)
        # register early so imports within the module that import `src.*`
        # can resolve to the expected package name
        sys.modules["src.ui"] = ui
        spec.loader.exec_module(ui)
    except Exception:
        # If loading fails, re-raise so test harness can see the original error
        raise

    page = st.sidebar.radio("Navigation", [":material/mobile_gear: Gestion des tablettes", ":material/settings: Configuration", ":material/description: Logs"])

    if page == ":material/description: Logs":
        ui.render_logs_page()
    elif page == ":material/settings: Configuration":
        ui.render_config_page(config, save_config, add_log, resolve_device_type, DEFAULT_DEVICE_TYPE)
    else:
        ui.render_main_page(config, save_config, add_log, resolve_device_type, BASE_DIR)


    # Display the image version at the bottom of the sidebar via CSS (fixed position)
    def _display_image_version_bottom(version_text: str):
        if not version_text:
            return
        # CSS to fix at the bottom of the sidebar
        html = f"""
        <div style="position: fixed; left: 20px; bottom: 8px; font-size: 12px;">
          <a href="https://github.com/dapitch666/rm-manager" target="_blank" style="color: rgba(0, 0, 0, 0.6); text-decoration: none;">rm-manager - version {version_text}</a>
        </div>
        """
        try:
            st.sidebar.html(html)
        except Exception:
            # Fallback: simple caption if injection fails
            try:
                st.sidebar.caption(f"rm-manager version {version_text} (Unable to inject custom HTML/CSS)")
            except Exception:
                pass


    _display_image_version_bottom(IMAGE_VERSION)

    # Debug overlay: show `st.session_state` in a small corner when running locally or when
    # the `DEBUG` env var is set. Uses BASE_DIR detection (if not in /app assume local).
    try:
        debug_mode = (BASE_DIR != "/app") or os.environ.get("DEBUG", "") .lower() in ("1", "true", "yes")
    except Exception:
        debug_mode = False

    if debug_mode:
        try:
            import html as _pyhtml
            state_snapshot = {k: v for k, v in st.session_state.items()}
            state_json = json.dumps(state_snapshot, default=str, indent=2)
            safe_json = _pyhtml.escape(state_json)
            debug_html = f"""
            <div style="position:fixed; right:8px; top:8px; max-width:420px; max-height:45vh; overflow:auto; background:rgba(255,255,255,0.95); border:1px solid rgba(0,0,0,0.12); padding:8px; font-size:12px; z-index:99999; font-family:monospace; box-shadow:0 4px 12px rgba(0,0,0,0.08);">
              <details style="margin:0"><summary style="font-weight:600; cursor:pointer">session_state (debug)</summary>
              <pre style="white-space:pre-wrap; margin:6px 0 0 0;">{safe_json}</pre>
              </details>
            </div>
            """
            st.markdown(debug_html, unsafe_allow_html=True)
        except Exception:
            # If HTML injection fails, fall back to sidebar expander (guaranteed).
            st.sidebar.expander("session_state (debug)", expanded=False).write(dict(st.session_state))
        else:
            # Also show a sidebar expander as a robust fallback/visible area for debugging.
            try:
                st.sidebar.expander("session_state (debug)", expanded=False).write(dict(st.session_state))
            except Exception:
                pass


if __name__ == "__main__":
    main()
