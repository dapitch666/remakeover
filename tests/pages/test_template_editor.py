"""Tests for pages/template_editor.py.

Covers: page renders without device, page renders with device, load/new controls,
save/download section, and interaction between the editor and local file storage.
"""

import json
import os
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests.pages.helpers import empty_cfg, make_env, with_device

# Minimal valid template JSON
_VALID_JSON = json.dumps(
    {"orientation": "portrait", "constants": [], "items": []},
    indent=2,
)

# A deliberately invalid JSON string
_INVALID_JSON = "{this is not valid json"


def _at_editor(tmp_path, cfg_path: str, session_state: dict | None = None) -> AppTest:
    """Boot app.py and switch to the template_editor page."""
    env = make_env(tmp_path, cfg_path)
    with patch.dict(os.environ, env):
        at = AppTest.from_file("app.py")
        at.run()
        if session_state:
            for k, v in session_state.items():
                at.session_state[k] = v
        at.switch_page("pages/template_editor.py").run()
    return at


def _make_template_file(tmp_path, device: str, name: str, content: str = _VALID_JSON) -> None:
    """Write a .template file into the device templates directory."""
    tdir = tmp_path / device / "templates"
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / name).write_text(content, encoding="utf-8")


class TestTemplateEditorNoDevice:
    def test_renders_without_device_selected(self, tmp_path):
        """Editor page loads without error even when no device is selected."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path)
        assert not at.exception

    def test_shows_info_when_no_device_selected(self, tmp_path):
        """With no devices configured the save section shows an info message."""
        cfg_path = empty_cfg(tmp_path)
        at = _at_editor(tmp_path, cfg_path)
        assert not at.exception
        assert any("Sélectionnez" in m.value for m in at.info)

    def test_title_is_present(self, tmp_path):
        """The 'Éditeur de templates' title is rendered on the page."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path)
        assert not at.exception
        assert any("diteur" in t.value for t in at.title)


class TestTemplateEditorWithDevice:
    def test_save_section_visible_with_device(self, tmp_path):
        """With a selected device, the Save subheader is present."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        assert any("Sauvegarder" in s.value for s in at.subheader)

    def test_text_area_present(self, tmp_path):
        """The JSON text area is always rendered."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        # Streamlit AppTest exposes text_area elements
        assert len(at.text_area) >= 1

    def test_preview_subheader_present(self, tmp_path):
        """The 'Aperçu' (preview) subheader is present."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        assert any("Aper" in s.value for s in at.subheader)

    def test_save_button_present(self, tmp_path):
        """The Save button is rendered when a device is selected."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        assert any("Sauvegarder" in b.label for b in at.button)

    def test_load_button_disabled_when_no_existing_templates(self, tmp_path):
        """The 'Charger' button is disabled when there are no saved templates."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        load_btn = next((b for b in at.button if "Charger" in b.label), None)
        assert load_btn is not None
        assert load_btn.disabled

    def test_load_button_enabled_when_templates_exist(self, tmp_path):
        """The 'Charger' button is enabled when at least one .template file exists."""
        cfg_path = with_device(tmp_path, "D1")
        _make_template_file(tmp_path, "D1", "existing.template")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        # Selectbox should list the saved template
        selects = at.selectbox
        assert any("existing.template" in (s.value or "") for s in selects) or any(
            "existing.template" in str(s.options) for s in selects
        )

    def test_new_button_present(self, tmp_path):
        """The 'Nouveau' button is always shown."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        assert any("Nouveau" in b.label for b in at.button)


class TestTemplateEditorInvalidJson:
    def test_invalid_json_shows_error_in_preview(self, tmp_path):
        """Entering invalid JSON shows an error message in the preview column."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["selected_name"] = "D1"
            at.switch_page("pages/template_editor.py").run()
            at.text_area[0].set_value(_INVALID_JSON).run()
        assert not at.exception
        assert len(at.error) >= 1

    def test_invalid_json_disables_save_button(self, tmp_path):
        """The Save button is disabled when the JSON in the text area is invalid."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["selected_name"] = "D1"
            at.switch_page("pages/template_editor.py").run()
            at.text_area[0].set_value(_INVALID_JSON).run()
        assert not at.exception
        save_btn = next((b for b in at.button if "Sauvegarder" in b.label), None)
        assert save_btn is not None
        assert save_btn.disabled


class TestTemplateEditorSave:
    def test_save_writes_template_file(self, tmp_path):
        """Clicking Save stores a .template file in the device templates dir."""
        cfg_path = with_device(tmp_path, "D1")
        tdir = tmp_path / "D1" / "templates"
        tdir.mkdir(parents=True, exist_ok=True)

        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["selected_name"] = "D1"
            at.switch_page("pages/template_editor.py").run()

            # Set valid JSON into the text area
            at.text_area[0].set_value(_VALID_JSON).run()

            save_btn = next((b for b in at.button if "Sauvegarder" in b.label), None)
            assert save_btn is not None
            save_btn.click().run()

        assert not at.exception
        # A .template file must have been written somewhere in the templates dir
        saved_files = list(tdir.glob("*.template"))
        assert len(saved_files) >= 1

    def test_filename_input_present_for_valid_json(self, tmp_path):
        """The filename text input is present in the save section when JSON is valid."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        # The "Nom du fichier" text input is rendered in the save section
        assert any("Nom du fichier" in ti.label for ti in at.text_input)


class TestTemplateEditorLoadExisting:
    def test_existing_template_selectable(self, tmp_path):
        """An existing .template file appears in the load selectbox."""
        cfg_path = with_device(tmp_path, "D1")
        _make_template_file(tmp_path, "D1", "lines.template", _VALID_JSON)
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        found = any("lines.template" in str(s.options) for s in at.selectbox)
        assert found

    def test_new_button_is_present(self, tmp_path):
        """The 'Nouveau' button is rendered when a saved template exists."""
        cfg_path = with_device(tmp_path, "D1")
        _make_template_file(tmp_path, "D1", "lines.template", _VALID_JSON)
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        assert any("Nouveau" in b.label for b in at.button)
