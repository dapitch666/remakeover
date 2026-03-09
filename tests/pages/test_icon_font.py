"""Tests for pages/icon_font.py.

Covers: no-device guard, basic rendering (caption, re-extract button, icon grid),
usage-filter radio (Tous / Utilisés / Non utilisés), and the re-extraction flow.
"""

import json
import os
from contextlib import ExitStack
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests.pages.helpers import at_page, empty_cfg, make_env, with_device

# ── Synthetic font data ───────────────────────────────────────────────────────

_CP_A = 0xE960  # put in templates.json → "used"
_CP_B = 0xE961  # not in templates.json → "unused"
_CP_C = 0xE962  # not in templates.json → "unused"
_FAKE_CPS = [_CP_A, _CP_B, _CP_C]


def _fake_font_path(tmp_path) -> str:
    """Create a minimal dummy file representing icomoon.ttf and return its path."""
    p = tmp_path / "icomoon.ttf"
    p.write_bytes(b"\x00\x01\x00\x00FAKE")  # 6 bytes → 0 KB after // 1024
    return str(p)


def _icon_patches(font_path: str) -> list:
    """Patches that bypass real font I/O for the icon_font page."""
    return [
        patch("src.icon_font.get_icon_codepoints", return_value=_FAKE_CPS),
        patch("src.icon_font.get_icon_font_path", return_value=font_path),
    ]


def _write_templates_json(tmp_path, device: str, icon_codepoints: list[int]) -> None:
    """Write templates.json with one entry per codepoint under tmp_path/device/."""
    d = tmp_path / device
    d.mkdir(parents=True, exist_ok=True)
    templates = [
        {"name": f"T{i}", "filename": f"T{i}", "iconCode": chr(cp), "categories": []}
        for i, cp in enumerate(icon_codepoints)
    ]
    (d / "templates.json").write_text(json.dumps({"templates": templates}), encoding="utf-8")


def _run_page(tmp_path, cfg_path: str, extra_patches: list | None = None) -> AppTest:
    """Render app.py → pages/icon_font.py under icon patches + optional extra patches."""
    font_path = _fake_font_path(tmp_path)
    return at_page(
        tmp_path, "pages/icon_font.py", cfg_path, _icon_patches(font_path) + (extra_patches or [])
    )


# ── Guard ─────────────────────────────────────────────────────────────────────


def test_icon_font_page_warns_when_no_devices(tmp_path):
    """Icon font page shows the 'Aucun appareil' guard when config has no devices."""
    at = _run_page(tmp_path, empty_cfg(tmp_path))
    assert not at.exception
    assert any("Aucun appareil" in m.value for m in at.markdown)


# ── Basic rendering ───────────────────────────────────────────────────────────


class TestIconFontPageRender:
    def test_renders_glyph_count_in_caption(self, tmp_path):
        """Caption shows the number of glyphs reported by get_icon_codepoints."""
        at = _run_page(tmp_path, with_device(tmp_path))
        assert not at.exception
        assert any(f"{len(_FAKE_CPS)} glyphe" in c.value for c in at.caption)

    def test_renders_reextract_button(self, tmp_path):
        """Ré-extraire button is rendered on the page."""
        at = _run_page(tmp_path, with_device(tmp_path))
        assert not at.exception
        assert any("Ré-extraire" in b.label for b in at.button)

    def test_renders_one_button_per_codepoint(self, tmp_path):
        """Each codepoint from get_icon_codepoints has a matching button in the grid."""
        at = _run_page(tmp_path, with_device(tmp_path))
        assert not at.exception
        icon_keys = {
            b.key for b in at.button if b.key and b.key.startswith("icon_") and b.key[5:].isdigit()
        }
        for cp in _FAKE_CPS:
            assert f"icon_{cp}" in icon_keys

    def test_no_filter_radio_without_templates_json(self, tmp_path):
        """When templates.json does not exist, no usage filter radio is rendered."""
        at = _run_page(tmp_path, with_device(tmp_path))
        assert not at.exception
        assert not at.radio

    def test_filter_radio_shown_when_templates_json_exists(self, tmp_path):
        """When templates.json exists for the device, the Afficher radio appears."""
        _write_templates_json(tmp_path, "D1", [_CP_A])
        at = _run_page(tmp_path, with_device(tmp_path))
        assert not at.exception
        assert any("Afficher" in r.label for r in at.radio)


# ── Usage filter ──────────────────────────────────────────────────────────────


class TestIconFontUsageFilter:
    """Tests for the Tous / Utilisés par la tablette / Non utilisés radio filter."""

    def _at_with_filter(self, tmp_path, radio_value: str) -> AppTest:
        """Render page (templates.json contains only _CP_A), then select *radio_value*."""
        _write_templates_json(tmp_path, "D1", [_CP_A])
        font_path = _fake_font_path(tmp_path)
        env = make_env(tmp_path, with_device(tmp_path))
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env))
            for p in _icon_patches(font_path):
                stack.enter_context(p)
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/icon_font.py").run()
            at.radio[0].set_value(radio_value).run()
        return at

    def _icon_button_keys(self, at: AppTest) -> set[str]:
        return {
            b.key for b in at.button if b.key and b.key.startswith("icon_") and b.key[5:].isdigit()
        }

    def test_filter_tous_shows_all_codepoints(self, tmp_path):
        """Selecting 'Tous' keeps all codepoints visible in the grid."""
        at = self._at_with_filter(tmp_path, "Tous")
        assert not at.exception
        assert self._icon_button_keys(at) == {f"icon_{cp}" for cp in _FAKE_CPS}

    def test_filter_used_shows_only_used_codepoints(self, tmp_path):
        """Selecting 'Utilisés par la tablette' shows only codepoints in templates.json."""
        at = self._at_with_filter(tmp_path, "Utilisés par la tablette")
        assert not at.exception
        assert self._icon_button_keys(at) == {f"icon_{_CP_A}"}

    def test_filter_unused_shows_only_unused_codepoints(self, tmp_path):
        """Selecting 'Non utilisés' shows codepoints NOT present in templates.json."""
        at = self._at_with_filter(tmp_path, "Non utilisés")
        assert not at.exception
        assert self._icon_button_keys(at) == {f"icon_{_CP_B}", f"icon_{_CP_C}"}


# ── Re-extraction button ──────────────────────────────────────────────────────


class TestIconFontRefetch:
    def _click_refetch(self, tmp_path, fetch_result: tuple) -> AppTest:
        """Render the page for D1, click Ré-extraire with *fetch_result*, return AppTest."""
        font_path = _fake_font_path(tmp_path)
        extra = [patch("src.icon_font.fetch_icon_font", return_value=fetch_result)]
        env = make_env(tmp_path, with_device(tmp_path))
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env))
            for p in _icon_patches(font_path) + extra:
                stack.enter_context(p)
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/icon_font.py").run()
            next(b for b in at.button if "Ré-extraire" in b.label).click().run()
        return at

    def test_success_shows_no_error(self, tmp_path):
        """A successful re-extraction produces no error widget."""
        at = self._click_refetch(tmp_path, (True, "ok (1024 bytes, 3 glyphs)"))
        assert not at.exception
        assert not at.error

    def test_failure_shows_error_message(self, tmp_path):
        """A failed re-extraction shows an error widget containing the failure reason."""
        at = self._click_refetch(tmp_path, (False, "SSH timeout"))
        assert not at.exception
        assert any("SSH timeout" in e.value for e in at.error)
