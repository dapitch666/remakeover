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
from src.config_ui import render_device_selector

# noinspection PyProtectedMember
from src.i18n import SUPPORTED_LANGUAGES, _

_LANG_FLAGS = {"en": ("🇬🇧", "English"), "fr": ("🇫🇷", "Français")}


def _normalize_lang_value(raw: str | None) -> str | None:
    """Normalize language query values to canonical short codes (en/fr)."""
    if raw is None:
        return None

    value = str(raw).strip()
    if not value:
        return None

    lowered = value.lower()
    if lowered in SUPPORTED_LANGUAGES:
        return lowered

    return None


def _init_language() -> None:
    """Set ``st.session_state["lang"]`` on the first visit when no URL param is present.

    A canonical short value (``en``/``fr``) is always kept in URL params,
    session state and the language selector state.
    """
    query_lang = _normalize_lang_value(st.query_params.get("lang"))
    if query_lang:
        st.session_state["lang"] = query_lang
    elif "lang" not in st.session_state:
        browser_lang = (st.context.locale or "en").split("-")[0].lower()
        st.session_state["lang"] = browser_lang if browser_lang in SUPPORTED_LANGUAGES else "en"

    # Keep URL in canonical short form (en/fr).
    if st.query_params.get("lang") != st.session_state["lang"]:
        st.query_params["lang"] = st.session_state["lang"]


def _language_selector() -> None:
    """Render a compact flag+label toggle in the sidebar using ``st.segmented_control``.

    The widget shows a rich label (flag + full name), while URL/query state is
    explicitly synced using canonical short codes (``en``/``fr``).
    """

    def _on_lang_change():
        selected = st.session_state.get("lang_selector")
        if selected:
            st.session_state["lang"] = selected
            st.query_params["lang"] = selected

    with st.sidebar:
        st.segmented_control(
            "Language",
            options=list(SUPPORTED_LANGUAGES),
            format_func=lambda lang: f"{_LANG_FLAGS[lang][0]} {_LANG_FLAGS[lang][1]}",
            label_visibility="collapsed",
            key="lang_selector",
            default=st.session_state.get("lang", "en"),
            width="stretch",
            on_change=_on_lang_change,
        )


# ── Session logging helper ────────────────────────────────────────────────────
def _add_log(message: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"{ts} - {message}"
    try:
        st.session_state.setdefault("logs", []).append(entry)
    except (AttributeError, RuntimeError):
        print(entry)


def _read_version():
    version = os.environ.get("IMAGE_VERSION")
    if version:
        return version
    try:
        with open(os.path.join(BASE_DIR, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
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
        f'  <a href="https://github.com/dapitch666/reMakeover" target="_blank">'
        f"      reMakeover - version {version}"
        f"  </a>"
        f"</div>"
    )
    st.sidebar.caption(html, unsafe_allow_html=True)


def _debug_overlay():
    debug_mode = (BASE_DIR != "/app") or os.environ.get("DEBUG", "").lower() in (
        "1",
        "true",
        "yes",
    )
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


def main():
    st.set_page_config(
        page_title="reMakeover",
        page_icon="assets/favicon.svg",
        layout="wide",
        initial_sidebar_state="auto",
    )
    st.logo(image="assets/logo.svg", size="large")

    # ── Shared session state ──────────────────────────────────────────────
    st.session_state.setdefault("logs", [])
    st.session_state["add_log"] = _add_log

    # Resolve language from URL param before any _() call (page titles, etc.)
    _init_language()

    # Load config from disk only on the very first run of this session.
    # Pages keep st.session_state["config"] up-to-date when they mutate it,
    # so re-reading from disk on every rerun is unnecessary.
    if "config" not in st.session_state:
        st.session_state["config"] = load_config()
    config = st.session_state["config"]

    # ── Navigation ────────────────────────────────────────────────────────
    pages = [
        st.Page("pages/images.py", title=_("Sleep Screen"), icon=":material/image:"),
        st.Page("pages/templates.py", title=_("Templates"), icon=":material/description:"),
        st.Page("pages/logs.py", title=_("Logs"), icon=":material/list:"),
    ]

    pg = st.navigation(pages)

    _language_selector()

    render_device_selector(config, _add_log)

    _inject_css()
    _sidebar_version(_read_version())
    _debug_overlay()

    from src.ui_common import show_deferred_toast

    show_deferred_toast()

    pg.run()


if __name__ == "__main__":
    main()
