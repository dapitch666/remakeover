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


def _write_templates_json(tmp_path, device: str, templates: list[dict]) -> None:
    """Write a templates.json file for editor metadata prefill tests."""
    ddir = tmp_path / device
    ddir.mkdir(parents=True, exist_ok=True)
    (ddir / "templates.json").write_text(json.dumps({"templates": templates}), encoding="utf-8")


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
    def test_filename_is_blank_for_new_template(self, tmp_path):
        """For a new template, filename input starts blank and remains editable."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        filename_input = next((ti for ti in at.text_input if "Filename" in ti.label), None)
        assert filename_input is not None
        assert filename_input.value == ""

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
        assert at.text_area[0].value == loaded_json
        filename_input = next((ti for ti in at.text_input if "Filename" in ti.label), None)
        assert filename_input is not None
        assert filename_input.value == "existing"

    def test_existing_template_prefills_icon_from_template_entry(self, tmp_path):
        """The icon field follows the loaded template's templates.json entry."""
        cfg_path = with_device(tmp_path, "D1")
        loaded_json = json.dumps(
            {
                "name": "loaded-template",
                "categories": ["Lines"],
                "orientation": "portrait",
                "constants": [],
                "items": [],
            },
            indent=2,
        )
        _make_template_file(tmp_path, "D1", "existing.template", loaded_json)
        _write_templates_json(
            tmp_path,
            "D1",
            [
                {
                    "name": "existing",
                    "filename": "existing",
                    "iconCode": "\ue960",
                    "categories": ["Lines"],
                }
            ],
        )
        at = _at_editor(
            tmp_path,
            cfg_path,
            {"selected_name": "D1", "tpl_editor_load_choice": "existing.template"},
        )
        assert not at.exception
        icon_input = next((ti for ti in at.text_input if "Icon code" in ti.label), None)
        assert icon_input is not None
        assert icon_input.value == "E960"

    def test_new_button_present(self, tmp_path):
        """The 'Nouveau' button is always shown."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_editor(tmp_path, cfg_path, {"selected_name": "D1"})
        assert not at.exception
        assert any("New" in b.label for b in at.button)


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
            at.text_area[0].set_value(_VALID_JSON).run()

            save_btn = next((b for b in at.button if "Save" in b.label), None)
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
        # The filename text input is rendered in the save section
        assert any("Filename" in ti.label for ti in at.text_input)

    def test_save_existing_template_same_stock_name_is_allowed(self, tmp_path):
        """Editing an existing template keeps the same name even if it matches backup stock stem."""
        cfg_path = with_device(tmp_path, "D1")
        device_dir = backup_dir(tmp_path, "D1")
        (device_dir / "templates.backup.json").write_text(
            json.dumps(
                {
                    "templates": [
                        {
                            "name": "Blank",
                            "filename": "Blank",
                            "iconCode": "\ue9fe",
                            "categories": [],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (device_dir / "templates.json").write_text(
            json.dumps(
                {
                    "templates": [
                        {
                            "name": "Blank",
                            "filename": "Blank",
                            "iconCode": "\ue9fe",
                            "categories": ["Lines"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (device_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "lastSync": "2026-04-01T10:00:00Z",
                    "templates": [
                        {
                            "name": "Blank",
                            "filename": "Blank",
                            "iconCode": "\ue9fe",
                            "categories": ["Perso"],
                            "syncStatus": "synced",
                            "addedAt": "2026-04-01T10:00:00Z",
                            "modifiedAt": "2026-04-01T10:00:00Z",
                        }
                    ],
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
        assert not any("This filename matches a stock template" in err.value for err in at.error)
        saved_files = list((tmp_path / "D1" / "templates").glob("Blank.template"))
        assert len(saved_files) == 1
        manifest = json.loads((device_dir / "manifest.json").read_text(encoding="utf-8"))
        entry = next(t for t in manifest["templates"] if t["filename"] == "Blank")
        assert entry["syncStatus"] == "pending"


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

            assert at.text_area[0].value == loaded_json

            tpl_select = next((s for s in at.selectbox if "lines.template" in str(s.options)), None)
            assert tpl_select is not None
            tpl_select.set_value("— New —").run()

            assert at.text_area[0].value == DEFAULT_TEMPLATE_JSON

    def test_switching_existing_templates_updates_filename_field(self, tmp_path):
        """Filename input follows the selected existing file stem when switching templates."""
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

            filename_input = next((ti for ti in at.text_input if "Filename" in ti.label), None)
            assert filename_input is not None
            assert filename_input.value == "alpha"

            tpl_select = next((s for s in at.selectbox if "alpha.template" in str(s.options)), None)
            assert tpl_select is not None
            tpl_select.set_value("beta.template").run()

            filename_input = next((ti for ti in at.text_input if "Filename" in ti.label), None)
            assert filename_input is not None
            assert filename_input.value == "beta"

    def test_switching_existing_templates_updates_icon_field(self, tmp_path):
        """Switching templates also refreshes the icon field from templates.json metadata."""
        cfg_path = with_device(tmp_path, "D1")
        _make_template_file(tmp_path, "D1", "alpha.template", _VALID_JSON)
        _make_template_file(tmp_path, "D1", "beta.template", _VALID_JSON)
        _write_templates_json(
            tmp_path,
            "D1",
            [
                {
                    "name": "alpha",
                    "filename": "alpha",
                    "iconCode": "\ue960",
                    "categories": ["Lines"],
                },
                {
                    "name": "beta",
                    "filename": "beta",
                    "iconCode": "\ue961",
                    "categories": ["Grid"],
                },
            ],
        )

        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["selected_name"] = "D1"
            at.session_state["tpl_editor_load_choice"] = "alpha.template"
            at.switch_page("pages/template_editor.py").run()

            icon_input = next((ti for ti in at.text_input if "Icon code" in ti.label), None)
            assert icon_input is not None
            assert icon_input.value == "E960"

            tpl_select = next((s for s in at.selectbox if "alpha.template" in str(s.options)), None)
            assert tpl_select is not None
            tpl_select.set_value("beta.template").run()

            icon_input = next((ti for ti in at.text_input if "Icon code" in ti.label), None)
            assert icon_input is not None
            assert icon_input.value == "E961"
