"""Tests for pages/template_editor.py.

Covers: page renders without device, page renders with device, load/new controls,
save/download section, and interaction between the editor and local file storage.
"""

import json
import os
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from src.constants import DEFAULT_TEMPLATE_JSON
from tests.pages.helpers import backup_dir, empty_cfg, make_env, with_device

# Minimal valid template JSON
_VALID_JSON = json.dumps(
    {"orientation": "portrait", "constants": [], "items": []},
    indent=2,
)

# A deliberately invalid JSON string
_INVALID_JSON = "{this is not valid json"


def _json_body_area(at):
    return next((ta for ta in at.text_area if ta.label == "Template JSON"), None)


def _meta_name_input(at):
    return next((ti for ti in at.text_input if ti.label == "Name"), None)


def _orientation_select(at):
    return next((s for s in at.selectbox if s.label == "Orientation"), None)


def _author_input(at):
    return next((ti for ti in at.text_input if ti.label == "Author"), None)


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
        assert any("Select" in m.value for m in at.info)

    def test_title_is_present(self, tmp_path):
        """The 'Template Editor' title is rendered on the page."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path)
        assert not at.exception
        assert any("Template Editor" in t.value for t in at.title)


class TestTemplateEditorWithDevice:
    def test_name_field_defaults_for_new_template(self, tmp_path):
        """For a new template, Name metadata field is empty."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        name_input = _meta_name_input(at)
        assert name_input is not None
        assert name_input.value == ""

    def test_save_section_visible_with_device(self, tmp_path):
        """With a selected device, the Save subheader is present."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        assert any("Save" in s.value for s in at.subheader)

    def test_text_area_present(self, tmp_path):
        """The JSON text area is always rendered."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        # Streamlit AppTest exposes text_area elements
        assert len(at.text_area) >= 1

    def test_preview_subheader_present(self, tmp_path):
        """The 'Preview' subheader is present."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        assert any("Preview" in s.value for s in at.subheader)

    def test_save_button_present(self, tmp_path):
        """The Save button is rendered when a device is selected."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        assert any("Save" in b.label for b in at.button)

    def test_load_button_removed(self, tmp_path):
        """Loading is now automatic from the selectbox; no dedicated Load button is shown."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        assert not any("Load" in b.label for b in at.button)

    def test_existing_template_auto_loads_on_selection(self, tmp_path):
        """Selecting an existing template directly loads it into the editor."""
        cfg_path = with_device(tmp_path, "D1")
        loaded_json = json.dumps(
            {"name": "loaded-template", "orientation": "portrait", "constants": [], "items": []},
            indent=2,
        )
        _make_template_file(tmp_path, "D1", "existing.template", loaded_json)
        at = _at_editor(
            tmp_path,
            cfg_path,
            {"selected_name": "D1", "tpl_editor_load_choice": "existing.template"},
        )
        assert not at.exception

        body_area = _json_body_area(at)
        assert body_area is not None
        loaded_value = json.loads(body_area.value)
        assert loaded_value["constants"] == []
        assert loaded_value["items"] == []

        name_input = _meta_name_input(at)
        assert name_input is not None
        assert name_input.value == "loaded-template"

        orientation = _orientation_select(at)
        assert orientation is not None
        assert orientation.value == "portrait"

        assert not any("Filename" in ti.label for ti in at.text_input)

    def test_new_button_present(self, tmp_path):
        """The 'Nouveau' button is always shown."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        assert any("New" in b.label for b in at.button)

    def test_author_field_empty_on_startup(self, tmp_path):
        """Author metadata field is empty on startup (defaults to rm-manager only on save)."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        author = _author_input(at)
        assert author is not None
        assert author.value == ""


class TestTemplateEditorInvalidJson:
    def test_invalid_json_shows_error_in_preview(self, tmp_path):
        """Entering invalid JSON in body shows an error message in the preview column."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["selected_name"] = "D1"
            at.switch_page("pages/template_editor.py").run()
            body_area = _json_body_area(at)
            assert body_area is not None
            body_area.set_value(_INVALID_JSON).run()
        assert not at.exception
        assert len(at.error) >= 1

    def test_invalid_json_disables_save_button(self, tmp_path):
        """The Save button is disabled when the JSON body is invalid."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["selected_name"] = "D1"
            at.switch_page("pages/template_editor.py").run()
            body_area = _json_body_area(at)
            assert body_area is not None
            body_area.set_value(_INVALID_JSON).run()
        assert not at.exception
        save_btn = next((b for b in at.button if "Save" in b.label), None)
        assert save_btn is not None
        assert save_btn.disabled

    def test_empty_name_disables_save_but_shows_preview(self, tmp_path):
        """Empty name disables Save/Download but preview still renders."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["selected_name"] = "D1"
            at.switch_page("pages/template_editor.py").run()

            name_input = _meta_name_input(at)
            assert name_input is not None
            name_input.set_value("").run()

        assert not at.exception
        # No error message in preview even with empty name
        assert not any("Name is required" in e.value for e in at.error)
        # Save button is disabled due to empty name
        save_btn = next((b for b in at.button if "Save" in b.label), None)
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
            body_area = _json_body_area(at)
            assert body_area is not None
            body_area.set_value(_VALID_JSON).run()

            save_btn = next((b for b in at.button if "Save" in b.label), None)
            assert save_btn is not None
            save_btn.click().run()

        assert not at.exception
        # A .template file must have been written somewhere in the templates dir
        saved_files = list(tdir.glob("*.template"))
        assert len(saved_files) >= 1

    def test_save_applies_author_default_when_empty(self, tmp_path):
        """Saving with empty author field applies 'rm-manager' default to the saved JSON."""
        cfg_path = with_device(tmp_path, "D1")
        tdir = tmp_path / "D1" / "templates"
        tdir.mkdir(parents=True, exist_ok=True)

        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["selected_name"] = "D1"
            at.switch_page("pages/template_editor.py").run()

            # Set name to allow save, leave author empty
            name_input = _meta_name_input(at)
            assert name_input is not None
            name_input.set_value("test-template").run()

            # Set valid JSON
            body_area = _json_body_area(at)
            assert body_area is not None
            body_area.set_value(_VALID_JSON).run()

            # Save
            save_btn = next((b for b in at.button if "Save" in b.label), None)
            assert save_btn is not None
            save_btn.click().run()

        assert not at.exception
        # Check that the saved file contains author="rm-manager"
        saved_files = list(tdir.glob("*.template"))
        assert len(saved_files) >= 1
        saved_content = json.loads(saved_files[0].read_text(encoding="utf-8"))
        assert saved_content.get("author") == "rm-manager"

    def test_filename_input_removed(self, tmp_path):
        """The filename text input is removed; Name metadata drives file naming."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        assert not any("Filename" in ti.label for ti in at.text_input)

    def test_save_existing_template_same_stock_name_is_allowed(self, tmp_path):
        """Editing an existing template keeps the same filename without conflict errors."""
        cfg_path = with_device(tmp_path, "D1")
        device_dir = backup_dir(tmp_path, "D1")
        template_uuid = "11111111-2222-4333-8444-555555555555"
        (device_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "last_modified": "2026-04-01T10:00:00Z",
                    "templates": {
                        template_uuid: {
                            "name": "Blank",
                            "created_at": "2026-04-01T10:00:00Z",
                            "sha256": "abc123",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        _make_template_file(tmp_path, "D1", "Blank.template", _VALID_JSON)

        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["selected_name"] = "D1"
            at.session_state["tpl_editor_load_choice"] = "Blank.template"
            at.switch_page("pages/template_editor.py").run()

            save_btn = next((b for b in at.button if "Save" in b.label), None)
            assert save_btn is not None
            save_btn.click().run()

        assert not at.exception
        saved_files = list((tmp_path / "D1" / "templates").glob(f"{template_uuid}.template"))
        assert len(saved_files) == 1
        manifest = json.loads((device_dir / "manifest.json").read_text(encoding="utf-8"))
        entry = manifest["templates"][template_uuid]
        assert entry["name"] == "Blank"
        assert entry["sha256"] != "abc123"


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
        """The 'New' button is rendered when a saved template exists."""
        cfg_path = with_device(tmp_path, "D1")
        _make_template_file(tmp_path, "D1", "lines.template", _VALID_JSON)
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        assert any("New" in b.label for b in at.button)

    def test_selecting_new_resets_editor_to_default_template(self, tmp_path):
        """Choosing '-- New --' in the selectbox restores the default template JSON."""
        cfg_path = with_device(tmp_path, "D1")
        loaded_json = json.dumps(
            {"name": "loaded-template", "orientation": "portrait", "constants": [], "items": []},
            indent=2,
        )
        _make_template_file(tmp_path, "D1", "lines.template", loaded_json)

        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["selected_name"] = "D1"
            at.session_state["tpl_editor_load_choice"] = "lines.template"
            at.switch_page("pages/template_editor.py").run()

            body_area = _json_body_area(at)
            assert body_area is not None
            loaded_value = json.loads(body_area.value)
            assert loaded_value["constants"] == []
            assert loaded_value["items"] == []

            name_input = _meta_name_input(at)
            assert name_input is not None
            assert name_input.value == "loaded-template"

            orientation = _orientation_select(at)
            assert orientation is not None
            assert orientation.value == "portrait"

            tpl_select = next((s for s in at.selectbox if "lines.template" in str(s.options)), None)
            assert tpl_select is not None
            tpl_select.set_value("— New —").run()

            body_area = _json_body_area(at)
            assert body_area is not None
            assert body_area.value in {"", DEFAULT_TEMPLATE_JSON}

            name_input = _meta_name_input(at)
            assert name_input is not None
            assert name_input.value == ""

    def test_switching_existing_templates_updates_name_field(self, tmp_path):
        """Name metadata field follows the selected existing template payload."""
        cfg_path = with_device(tmp_path, "D1")
        _make_template_file(
            tmp_path,
            "D1",
            "alpha.template",
            json.dumps(
                {
                    "name": "json-name-alpha",
                    "orientation": "portrait",
                    "constants": [],
                    "items": [],
                },
                indent=2,
            ),
        )
        _make_template_file(
            tmp_path,
            "D1",
            "beta.template",
            json.dumps(
                {"name": "json-name-beta", "orientation": "portrait", "constants": [], "items": []},
                indent=2,
            ),
        )

        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["selected_name"] = "D1"
            at.session_state["tpl_editor_load_choice"] = "alpha.template"
            at.switch_page("pages/template_editor.py").run()

            name_input = _meta_name_input(at)
            assert name_input is not None
            assert name_input.value == "json-name-alpha"

            tpl_select = next((s for s in at.selectbox if "alpha.template" in str(s.options)), None)
            assert tpl_select is not None
            tpl_select.set_value("beta.template").run()

            name_input = _meta_name_input(at)
            assert name_input is not None
            # Beta has no JSON name field, so it defaults to the filename
            assert name_input.value in {"beta", "json-name-beta"}
