"""UIAdapter — bridges run_maintenance progress callbacks to Streamlit widgets.

Pass *add_log* to also write every step message to the session log.
Omit it (or pass None) for a lightweight adapter with no side-effects
beyond updating the status / progress widgets.
"""

from __future__ import annotations
from typing import Callable, Optional
import streamlit as st


class UIAdapter:
    def __init__(self, status_obj, progress_obj, add_log: Optional[Callable[[str], None]] = None):
        self._status = status_obj
        self._progress = progress_obj
        self._add_log = add_log

    def step(self, msg: str):
        try:
            self._status.text(msg)
        except Exception:
            pass
        if self._add_log:
            self._add_log(msg)

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
