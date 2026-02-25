import streamlit as st

import os
import json
from datetime import datetime

# --- CONFIGURATION ---
# Detect environment (Docker or local)
if os.path.exists("/app"):
    # Docker mode
    BASE_DIR = "/app"
else:
    # Local development mode
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, "data", "config.json")
IMAGES_DIR = os.path.join(BASE_DIR, "data", "images")

DEVICE_SIZES = {
    "reMarkable 2": (1404, 1872),
    "reMarkable Paper Pro": (1620, 2160),
    "reMarkable Paper Pro Move": (954, 1696),
}
DEFAULT_DEVICE_TYPE = "reMarkable Paper Pro"


def truncate_display_name(name: str, max_len: int = 13) -> str:
    """Return a truncated version of the name for display (adds '...' when truncated)."""
    if not isinstance(name, str):
        return str(name)
    if len(name) <= max_len:
        return name
    # Keep a bit of room for an extension indicator if present
    return name[: max_len - 3] + "..."

def load_config():
    """Load configuration from the JSON file."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    elif BASE_DIR != "/app":
        # Default configuration if the file doesn't exist
        default_config = {
            "devices": {
                "Anne (rM Paper Pro)": {
                    "ip": "192.168.1.174",
                    "password": "a5g7du9FkY",
                    "device_type": "reMarkable Paper Pro",
                    "templates": False,
                    "carousel": True
                },
                "Benoît (rM Move)": {
                    "ip": "192.168.1.144",
                    "password": "3JRpokPWbA",
                    "device_type": "reMarkable Paper Pro Move",
                    "templates": False,
                    "carousel": True
                }
            }
        }
        save_config(default_config)
        return default_config
    else:
        return {"devices": {}}

def save_config(config):
    """Save configuration to the JSON file."""
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

from src.ssh import (
    run_ssh_cmd,
    upload_file_ssh,
    download_file_ssh,
    test_ssh_connection,
)
from src.images import (
    process_image,
    get_device_images_dir,
    list_device_images,
    save_device_image,
    load_device_image,
    delete_device_image,
    rename_device_image,
)
from src.maintenance import run_maintenance
# Import Device robustly for environments where `src` may not be a package.
try:
    from src.models import Device
except Exception:
    import importlib.util as _il, sys as _sys
    _models_path = os.path.join(BASE_DIR, "src", "models.py")
    _spec = _il.spec_from_file_location("rm_manager_models", _models_path)
    _models = _il.module_from_spec(_spec)
    _sys.modules[_spec.name] = _models
    _spec.loader.exec_module(_models)
    Device = _models.Device

def resolve_device_type(device):
    # Accept either a dict-like device or a Device dataclass
    try:
        device_type = device.get("device_type")
    except Exception:
        # assume dataclass-like
        device_type = getattr(device, "device_type", None)

    if device_type in DEVICE_SIZES:
        return device_type

    return DEFAULT_DEVICE_TYPE

# --- STREAMLIT INTERFACE ---


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
    DEVICES = config.get("devices", {})


    def submit_rename_factory(img, device_name):
        def _cb():
            key = f"rename_input_{img}"
            new_name = st.session_state.get(key, "")
            if new_name and new_name != img:
                try:
                    if rename_device_image(device_name, img, new_name):
                        # Update preferred image if needed
                        dev = config.get("devices", {}).get(device_name)
                        if dev:
                            try:
                                # prefer Device object usage when available
                                dobj = Device.from_dict(device_name, dev)
                                if dobj.is_preferred(img):
                                    dobj.set_preferred(new_name)
                                    config["devices"][device_name] = dobj.to_dict()
                                    save_config(config)
                                    add_log(f"Preferred image updated: {img} -> {new_name} for '{device_name}'")
                            except Exception:
                                # fallback to dict manipulation
                                if dev.get("preferred_image") == img:
                                    config["devices"][device_name]["preferred_image"] = new_name
                                    save_config(config)
                                    add_log(f"Preferred image updated: {img} -> {new_name} for '{device_name}'")
                        add_log(f"Renamed {img} to {new_name} for '{device_name}'")
                        try:
                            st.toast(f"Renommé : {new_name}", icon=":material/task_alt:")
                        except Exception:
                            pass
                except Exception as e:
                    add_log(f"Error renaming {img} -> {new_name}: {e}")
            # exit edit mode (no st.rerun() — Streamlit will refresh on next interaction)
            st.session_state.pop(f"edit_{img}", None)

        return _cb

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
