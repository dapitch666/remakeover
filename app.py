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
from src.i18n import SUPPORTED_LANGUAGES, _

_LANG_FLAGS = {"en": ("🇬🇧", "English"), "fr": ("🇫🇷", "Français")}


def _normalize_lang_value(raw: str | None) -> str | None:
    """Normalize language query values to canonical short codes (en/fr).

    Accepts legacy values such as full labels (with or without flag) so old
    links continue to work.
    """
    if raw is None:
        return None

    value = str(raw).strip()
    if not value:
        return None

    lowered = value.lower()
    if lowered in SUPPORTED_LANGUAGES:
        return lowered

    for code, (flag, name) in _LANG_FLAGS.items():
        if lowered in {name.lower(), f"{flag} {name}".lower()}:
            return code

    return None


def _init_language() -> None:
    """Set ``st.session_state["lang"]`` on the first visit when no URL param is present.

    A canonical short value (``en``/``fr``) is always kept in URL params,
    session state and the language selector state. Legacy URL values containing
    full labels (with flags) are normalized to short codes.
    """
    query_lang = _normalize_lang_value(st.query_params.get("lang"))
    if query_lang:
        st.session_state["lang"] = query_lang
    elif "lang" not in st.session_state:
        browser_lang = (st.context.locale or "en").split("-")[0].lower()
        st.session_state["lang"] = browser_lang if browser_lang in SUPPORTED_LANGUAGES else "en"

    # Keep URL in canonical short form (en/fr), including after legacy links.
    if st.query_params.get("lang") != st.session_state["lang"]:
        st.query_params["lang"] = st.session_state["lang"]


def _language_selector() -> None:
    """Render a compact flag+label toggle in the sidebar using ``st.segmented_control``.

    The widget shows a rich label (flag + full name), while URL/query state is
    explicitly synced using canonical short codes (``en``/``fr``).
    """
    with st.sidebar:
        selected_lang = st.segmented_control(
            "Language",
            options=list(SUPPORTED_LANGUAGES),
            format_func=lambda lang: f"{_LANG_FLAGS[lang][0]} {_LANG_FLAGS[lang][1]}",
            label_visibility="collapsed",
            key="lang_selector",
            default=st.session_state.get("lang", "en"),
            width="stretch",
        )

    if selected_lang and selected_lang != st.session_state.get("lang"):
        st.session_state["lang"] = selected_lang

    if st.query_params.get("lang") != st.session_state["lang"]:
        st.query_params["lang"] = st.session_state["lang"]


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
        "       max-width: 90%;"
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
        st.sidebar.expander("session_state (debug)", expanded=False).write(
            dict(st.session_state)
        )  # not translated — dev only

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


def _device_selector(config: dict) -> str | None:
    """Render device selector and SSH test controls in the sidebar.

    Returns the selected device name when at least one device is configured,
    otherwise returns ``None``.
    """
    devices = config.get("devices", {})
    if not devices:
        st.session_state["selected_name"] = None
        return None

    device_names = list(devices.keys())

    # Apply an explicit `?tablet=` URL selection only when session state
    # has no valid selection yet, so user interactions keep priority.
    qp_tablet = st.query_params.get("tablet")
    if (
        st.session_state.get("tablet") not in device_names
        and qp_tablet
        and qp_tablet in device_names
    ):
        st.session_state["tablet"] = qp_tablet

    # Consume pending selection set by another page (e.g. after saving a new device).
    pending = st.session_state.pop("pending_selected_tablet", None)
    if pending and pending in device_names:
        st.session_state["tablet"] = pending

    # Keep a valid selected tablet in session state when the list changes.
    if st.session_state.get("tablet") not in device_names:
        st.session_state["tablet"] = device_names[0]

    with st.sidebar:
        from src.models import Device as _Device
        from src.ssh import ssh_connectivity_test

        col1, col2 = st.columns([4, 1], vertical_alignment="bottom")
        with col1:
            selected_name = st.selectbox(
                _("Tablet"),
                device_names,
                key="tablet",
            )
        with col2:
            if st.button(
                ":material/wifi:",
                key="sidebar_test_ssh",
                help=_("Test SSH connection"),
            ):
                _device = _Device.from_dict(selected_name, devices[selected_name])
                ok, err = ssh_connectivity_test(_device.ip, _device.password or "")
                st.session_state["_ssh_test_result"] = {
                    "ok": ok,
                    "err": err,
                    "tablet": selected_name,
                }
                if ok:
                    _add_log(f"SSH connection successful to '{selected_name}'")
                else:
                    _add_log(f"SSH connection failed to '{selected_name}': {err}")

        _ssh_result = st.session_state.get("_ssh_test_result")
        if _ssh_result and _ssh_result.get("tablet") != selected_name:
            del st.session_state["_ssh_test_result"]
            _ssh_result = None
        if _ssh_result:
            if _ssh_result["ok"]:
                st.success(_("SSH connection OK"), icon=":material/task_alt:")
            else:
                st.error(
                    _("SSH connection failed: {err}").format(err=_ssh_result["err"]),
                    icon=":material/error:",
                )

    # Persist selection in session state for pages to consume.
    st.session_state["selected_name"] = selected_name
    st.query_params["tablet"] = selected_name
    return selected_name


def main():
    st.set_page_config(
        page_title="rM Manager",
        page_icon="assets/favicon.png",
        layout="wide",
        initial_sidebar_state="auto",
    )
    st.logo(image="assets/logo.svg", size="large")

    # ── Shared session state ──────────────────────────────────────────────
    st.session_state.setdefault("logs", [])
    st.session_state["add_log"] = _add_log
    st.session_state["BASE_DIR"] = BASE_DIR

    # Resolve language from URL param before any _() call (page titles, etc.)
    _init_language()

    # Load config from disk only on the very first run of this session.
    # Pages keep st.session_state["config"] up-to-date when they mutate it,
    # so re-reading from disk on every rerun is unnecessary.
    if "config" not in st.session_state:
        st.session_state["config"] = load_config()
    config = st.session_state["config"]

    # ── Navigation ────────────────────────────────────────────────────────
    config_page = st.Page(
        "pages/configuration.py", title="Configuration", icon=":material/settings:"
    )
    pages = [
        st.Page("pages/images.py", title="Images", icon=":material/image:"),
        st.Page("pages/templates.py", title="Templates", icon=":material/description:"),
        st.Page("pages/deployment.py", title=_("Deployment"), icon=":material/rocket_launch:"),
        config_page,
        st.Page("pages/logs.py", title="Logs", icon=":material/list:"),
    ]

    pg = st.navigation(pages)

    _language_selector()

    selected_name = _device_selector(config)
    # On the very first visit with no devices configured, send the user
    # straight to the configuration page.  The flag prevents the redirect
    # from firing again for the rest of the session (so the warning pages
    # remain reachable via the sidebar navigation if the user wants to).
    if (
        selected_name is None
        and pg is not config_page
        and not st.session_state.get("_auto_config_redirect")
    ):
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
