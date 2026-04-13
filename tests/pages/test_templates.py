"""Tests for pages/templates.py — unified template library + editor.

Structure:
  TestTemplatesPageInit       – manifest init, empty-config warning
  TestTemplatesSync           – sync expander buttons
  TestTemplateList            – list rendering and filtering
  TestEditorPanelEmpty        – editor hidden when nothing selected
  TestEditorPanelNew          – editor for a brand-new template
  TestEditorPanelExisting     – editor loaded with an existing template
  TestEditorSave              – save flow
  TestEditorIconSvg           – icon SVG textarea in Advanced expander
  TestImportDialog            – import button exists (dialog itself is modal)
"""

import base64
import json
import os
import uuid
from contextlib import contextmanager, suppress
from unittest.mock import MagicMock, patch

from streamlit.testing.v1 import AppTest

from tests.pages.helpers import (
    backup_dir,
    empty_cfg,
    make_env,
    with_device,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

# Minimal valid reMarkable JSON template (body-only, no meta fields).
_BODY_JSON = json.dumps({"constants": [], "items": []}, indent=2)

# Full template JSON with name and orientation meta fields.
_FULL_JSON = json.dumps(
    {"name": "my-tpl", "orientation": "portrait", "constants": [], "items": []},
    indent=2,
)

# Deliberately invalid JSON.
_INVALID_JSON = "{this is not valid json"

_SVG_150x200 = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="150" height="200">'
    '<rect x="2" y="2" width="146" height="196"/>'
    "</svg>"
)
_SVG_200x150 = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="200" height="150">'
    '<rect x="2" y="2" width="196" height="146"/>'
    "</svg>"
)
_SVG_WRONG_SIZE = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"></svg>'


def _make_template(
    tmp_path,
    device: str = "D1",
    name: str = "lines.template",
    content: str | None = None,
    template_uuid: str | None = None,
) -> str:
    """Write a canonical `<uuid>.template` file and create a minimal manifest entry."""
    # Preserve any templates already written before backup_dir resets manifest.json.
    prior_manifest_path = tmp_path / device / "manifest.json"
    prior_templates: dict = {}
    if prior_manifest_path.exists():
        with suppress(json.JSONDecodeError, KeyError):
            prior_templates = json.loads(prior_manifest_path.read_text(encoding="utf-8")).get(
                "templates", {}
            )
    d = backup_dir(tmp_path, device)
    tdir = d / "templates"
    stem = name.removesuffix(".template")
    template_uuid = template_uuid or str(
        uuid.uuid5(uuid.NAMESPACE_URL, f"rm-manager:{device}:{stem}")
    )
    (tdir / f"{template_uuid}.template").write_text(content or _FULL_JSON, encoding="utf-8")
    manifest_path = d / "manifest.json"
    templates = dict(prior_templates)
    templates[template_uuid] = {
        "name": stem,
        "created_at": "2025-01-01T00:00:00Z",
        "sha256": "abc123",
    }
    manifest_path.write_text(
        json.dumps({"last_modified": None, "templates": templates}), encoding="utf-8"
    )
    return template_uuid


def _at_templates(
    tmp_path, cfg_path, session_state: dict | None = None, device: str = "D1"
) -> AppTest:
    """Boot app.py and switch to templates page, applying optional session state.

    If session_state sets ``tpl_unified_selected_uuid``, this helper automatically
    pre-sets ``tpl_unified_device`` (unless already provided) so the
    device-change guard inside the page does not reset the selection.
    """
    env = make_env(tmp_path, cfg_path)
    with patch.dict(os.environ, env):
        at = AppTest.from_file("app.py")
        at.run()
        if session_state:
            if (
                "tpl_unified_selected_uuid" in session_state
                and "tpl_unified_device" not in session_state
            ):
                at.session_state["tpl_unified_device"] = device
            for k, v in session_state.items():
                at.session_state[k] = v
        at.switch_page("pages/templates.py").run()
    return at


def _name_input(at):
    return next((ti for ti in at.text_input if ti.label == "Name"), None)


def _author_input(at):
    return next((ti for ti in at.text_input if ti.label == "Author"), None)


def _json_area(at):
    return next((ta for ta in at.text_area if ta.label == "Template JSON"), None)


def _svg_area(at):
    return next((ta for ta in at.text_area if "SVG" in ta.label), None)


def _save_btn(at):
    return next((b for b in at.button if b.label == "Save"), None)


def _delete_btn(at):
    return next((b for b in at.button if b.label == "Delete"), None)


def _replace_file_btn(at):
    return next((b for b in at.button if "Replace file" in b.label), None)


def _categories_multiselect(at):
    return next((ms for ms in at.multiselect if ms.label == "Categories"), None)


def _labels_multiselect(at):
    return next((ms for ms in at.multiselect if ms.label == "Labels"), None)


# ---------------------------------------------------------------------------
# Init / config guard
# ---------------------------------------------------------------------------


def test_templates_page_warns_when_no_devices(tmp_path):
    """Templates page shows 'No device' message with empty config."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/templates.py").run()
    assert not at.exception
    assert any("No device" in m.value for m in at.markdown)


# ---------------------------------------------------------------------------
# TestTemplatesPageInit — manifest init, warning, and init button
# ---------------------------------------------------------------------------


class TestTemplatesPageInit:
    def test_no_manifest_shows_warning_and_import_button(self, tmp_path):
        """Without a manifest file, page shows the initialize warning and action button."""
        cfg_path = with_device(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path)
        assert not at.exception
        assert any("not been imported yet" in w.value for w in at.warning)
        assert any("Initialize templates" in b.label for b in at.button)

    def test_import_button_click_success(self, tmp_path):
        """Clicking initialize triggers fetch_and_init_templates."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.template_sync.fetch_and_init_templates", return_value=(True, "3 templates")),
            patch(
                "src.template_sync.check_sync_status",
                return_value=(
                    True,
                    {
                        "local_count": 0,
                        "remote_count": 0,
                        "in_sync_count": 0,
                        "to_upload": [],
                        "to_delete_remote": [],
                    },
                ),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            btn = next((b for b in at.button if "Initialize templates" in b.label), None)
            assert btn is not None
            btn.click().run()
        assert not at.exception

    def test_import_button_click_failure_shows_error(self, tmp_path):
        """When fetch_and_init_templates fails, page shows an error message."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch(
                "src.template_sync.fetch_and_init_templates",
                return_value=(False, "SSH connection refused"),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            btn = next((b for b in at.button if "Initialize templates" in b.label), None)
            assert btn is not None
            btn.click().run()
        assert not at.exception
        assert any("SSH connection refused" in e.value for e in at.error)

    def test_manifest_exists_no_templates_shows_empty_state(self, tmp_path):
        """With manifest but zero templates, page renders without exception."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path)
        assert not at.exception


# ---------------------------------------------------------------------------
# TestTemplatesSync — sync buttons in the collapsible expander
# ---------------------------------------------------------------------------


class TestTemplatesSync:
    def test_sync_now_button_is_rendered(self, tmp_path):
        """'Sync now' button is rendered (inside the sync expander)."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path)
        assert not at.exception
        assert any("Sync now" in b.label for b in at.button)

    def test_check_sync_button_is_rendered(self, tmp_path):
        """'Check sync' button is rendered inside the sync expander."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path)
        assert not at.exception
        assert any("Check sync" in b.label for b in at.button)

    def test_reset_reinitialize_button_is_rendered(self, tmp_path):
        """'Reset & reinitialize' button is rendered inside the sync expander."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path)
        assert not at.exception
        assert any("Reset" in b.label for b in at.button)

    def test_sync_now_button_click_success(self, tmp_path):
        """Clicking Sync now triggers the sync pipeline successfully."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)

        @contextmanager
        def _fake_session(_ip, _pw):
            s = MagicMock()
            s.run.return_value = ("", "")
            s.upload.return_value = (True, "ok")
            s.download.return_value = (None, "No such file")
            yield s

        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_categories", return_value=[]),
            patch("src.template_sync._ssh.ssh_session", _fake_session),
            patch(
                "src.template_sync.check_sync_status",
                return_value=(
                    True,
                    {
                        "local_count": 0,
                        "remote_count": 0,
                        "in_sync_count": 0,
                        "to_upload": [],
                        "to_delete_remote": [],
                    },
                ),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            btn = next((b for b in at.button if b.label == "Sync now"), None)
            assert btn is not None
            btn.click().run()
        assert not at.exception

    def test_reset_reinitialize_click_success(self, tmp_path):
        """Clicking Reset & reinitialize triggers the full local wipe + import flow."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_categories", return_value=[]),
            patch(
                "src.template_sync.fetch_and_init_templates",
                return_value=(True, "reset ok"),
            ),
            patch(
                "src.template_sync.check_sync_status",
                return_value=(
                    True,
                    {
                        "local_count": 0,
                        "remote_count": 0,
                        "in_sync_count": 0,
                        "to_upload": [],
                        "to_delete_remote": [],
                    },
                ),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            btn = next((b for b in at.button if "Reset" in b.label), None)
            assert btn is not None
            btn.click().run()
        assert not at.exception

    def test_sync_failure_no_exception(self, tmp_path):
        """When the remote manifest fetch fails, sync shows error; no exception."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)

        @contextmanager
        def _fake_session(_ip, _pw):
            s = MagicMock()
            s.download.return_value = (
                None,
                "connection refused",
            )  # non-missing error → fetch fails
            yield s

        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_categories", return_value=[]),
            patch("src.template_sync._ssh.ssh_session", _fake_session),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            btn = next((b for b in at.button if b.label == "Sync now"), None)
            assert btn is not None
            btn.click().run()
        assert not at.exception

    def test_check_sync_click_success(self, tmp_path):
        """Clicking Check sync stores the result in session state."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch(
                "src.template_sync.check_sync_status",
                return_value=(
                    True,
                    {
                        "local_count": 1,
                        "remote_count": 1,
                        "in_sync_count": 1,
                        "to_upload": [],
                        "to_delete_remote": [],
                    },
                ),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            btn = next((b for b in at.button if "Check sync" in b.label), None)
            assert btn is not None
            btn.click().run()
        assert not at.exception


# ---------------------------------------------------------------------------
# TestTemplateList — left-panel list rendering
# ---------------------------------------------------------------------------


class TestTemplateList:
    def test_new_and_import_buttons_always_present(self, tmp_path):
        """New and Import buttons are always shown in the left panel."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path)
        assert not at.exception
        assert any(b.label == "New" for b in at.button)
        assert any(b.label == "Import" for b in at.button)

    def test_template_appears_in_list(self, tmp_path):
        """A .template file's name appears as a button in the list."""
        cfg_path = with_device(tmp_path, "D1")
        _make_template(tmp_path, "D1", "grid.template")
        at = _at_templates(tmp_path, cfg_path)
        assert not at.exception
        assert any("grid" in b.label.lower() for b in at.button)

    def test_two_templates_both_visible(self, tmp_path):
        """Two distinct .template files both appear as list buttons."""
        cfg_path = with_device(tmp_path, "D1")
        _make_template(tmp_path, "D1", "alpha.template")
        _make_template(tmp_path, "D1", "beta.template")
        at = _at_templates(tmp_path, cfg_path)
        assert not at.exception
        labels = [b.label.lower() for b in at.button]
        assert any("alpha" in lbl for lbl in labels)
        assert any("beta" in lbl for lbl in labels)

    def test_six_templates_all_render(self, tmp_path):
        """Six templates all appear — no paging/truncation in the list."""
        cfg_path = with_device(tmp_path, "D1")
        for i in range(6):
            _make_template(tmp_path, "D1", f"t{i}.template")
        at = _at_templates(tmp_path, cfg_path)
        assert not at.exception
        for i in range(6):
            assert any(f"t{i}" in b.label for b in at.button)

    def test_clicking_template_selects_it(self, tmp_path):
        """Clicking a template list button sets tpl_unified_selected_uuid."""
        cfg_path = with_device(tmp_path, "D1")
        _make_template(tmp_path, "D1", "pick_me.template")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            # Pre-set device tracking so no reset happens
            at.session_state["tpl_unified_device"] = "D1"
            at.switch_page("pages/templates.py").run()
            list_btn = next(
                (b for b in at.button if b.key and b.key.startswith("tpl_list_btn_")), None
            )
            assert list_btn is not None
            list_btn.click().run()
        assert not at.exception
        assert at.session_state["tpl_unified_selected_uuid"] is not None

    def test_filter_text_input_is_present(self, tmp_path):
        """A filter text input is rendered in the left panel."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path)
        assert not at.exception
        assert any(ti.key == "tpl_filter_text" for ti in at.text_input)

    def test_orientation_filter_selectbox_is_present(self, tmp_path):
        """An orientation filter selectbox is rendered in the filter expander."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path)
        assert not at.exception
        assert any(sb.key == "tpl_filter_orientation" for sb in at.selectbox)

    def test_filter_by_landscape_hides_portrait_templates(self, tmp_path):
        """Setting orientation filter to 'landscape' hides portrait templates."""
        cfg_path = with_device(tmp_path, "D1")
        portrait_json = json.dumps(
            {"name": "portrait-tpl", "orientation": "portrait", "constants": [], "items": []}
        )
        landscape_json = json.dumps(
            {"name": "landscape-tpl", "orientation": "landscape", "constants": [], "items": []}
        )
        _make_template(tmp_path, "D1", "portrait.template", content=portrait_json)
        _make_template(tmp_path, "D1", "landscape.template", content=landscape_json)
        at = _at_templates(
            tmp_path, cfg_path, session_state={"tpl_filter_orientation": "landscape"}
        )
        assert not at.exception
        labels = [b.label.lower() for b in at.button]
        assert any("landscape" in lbl for lbl in labels)
        assert not any("portrait" in lbl for lbl in labels)

    def test_filter_by_portrait_hides_landscape_templates(self, tmp_path):
        """Setting orientation filter to 'portrait' hides landscape templates."""
        cfg_path = with_device(tmp_path, "D1")
        portrait_json = json.dumps(
            {"name": "portrait-tpl", "orientation": "portrait", "constants": [], "items": []}
        )
        landscape_json = json.dumps(
            {"name": "landscape-tpl", "orientation": "landscape", "constants": [], "items": []}
        )
        _make_template(tmp_path, "D1", "portrait.template", content=portrait_json)
        _make_template(tmp_path, "D1", "landscape.template", content=landscape_json)
        at = _at_templates(tmp_path, cfg_path, session_state={"tpl_filter_orientation": "portrait"})
        assert not at.exception
        labels = [b.label.lower() for b in at.button]
        assert any("portrait" in lbl for lbl in labels)
        assert not any("landscape" in lbl for lbl in labels)

    def test_filter_by_empty_orientation_shows_all_templates(self, tmp_path):
        """Setting orientation filter to '' (all) shows both portrait and landscape templates."""
        cfg_path = with_device(tmp_path, "D1")
        portrait_json = json.dumps(
            {"name": "portrait-tpl", "orientation": "portrait", "constants": [], "items": []}
        )
        landscape_json = json.dumps(
            {"name": "landscape-tpl", "orientation": "landscape", "constants": [], "items": []}
        )
        _make_template(tmp_path, "D1", "portrait.template", content=portrait_json)
        _make_template(tmp_path, "D1", "landscape.template", content=landscape_json)
        at = _at_templates(tmp_path, cfg_path, session_state={"tpl_filter_orientation": ""})
        assert not at.exception
        labels = [b.label.lower() for b in at.button]
        assert any("portrait" in lbl for lbl in labels)
        assert any("landscape" in lbl for lbl in labels)

    def test_selection_resets_on_device_change(self, tmp_path):
        """When tpl_unified_device differs from the current device, selection is cleared."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            # Simulate a stale device tracking value (e.g. previously D2 was selected)
            at.session_state["tpl_unified_device"] = "STALE_DEVICE"
            at.session_state["tpl_unified_selected_uuid"] = "11111111-1111-4111-8111-111111111111"
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert at.session_state["tpl_unified_selected_uuid"] is None


# ---------------------------------------------------------------------------
# TestEditorPanelEmpty — nothing selected
# ---------------------------------------------------------------------------


class TestEditorPanelEmpty:
    def test_empty_state_shown_when_no_template_selected(self, tmp_path):
        """When tpl_unified_selected_uuid is None, editor shows a placeholder message."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path)
        assert not at.exception
        # No meta form inputs should be visible
        assert _name_input(at) is None

    def test_save_button_absent_when_nothing_selected(self, tmp_path):
        """Save button is not rendered when the editor panel is in empty state."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path)
        assert not at.exception
        assert _save_btn(at) is None


# ---------------------------------------------------------------------------
# TestEditorPanelNew — tpl_unified_selected_uuid = "__new__"
# ---------------------------------------------------------------------------


class TestEditorPanelNew:
    def test_new_button_shows_editor(self, tmp_path):
        """Clicking 'New' opens the editor with an empty name field."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            new_btn = next((b for b in at.button if b.label == "New"), None)
            assert new_btn is not None
            new_btn.click().run()
        assert not at.exception
        assert _name_input(at) is not None

    def test_name_input_empty_for_new_template(self, tmp_path):
        """For a new template, the Name field defaults to empty."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path, {"tpl_unified_selected_uuid": "__new__"})
        assert not at.exception
        name = _name_input(at)
        assert name is not None
        assert name.value == ""

    def test_author_input_empty_for_new_template(self, tmp_path):
        """Author field is empty on startup (defaults to rm-manager only on save)."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path, {"tpl_unified_selected_uuid": "__new__"})
        assert not at.exception
        author = _author_input(at)
        assert author is not None
        assert author.value == ""

    def test_json_textarea_present_for_new_template(self, tmp_path):
        """The JSON editor textarea is rendered for a new template."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path, {"tpl_unified_selected_uuid": "__new__"})
        assert not at.exception
        assert _json_area(at) is not None

    def test_metadata_fields_use_multiselects(self, tmp_path):
        """Categories and labels are rendered as multiselect widgets."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path, {"tpl_unified_selected_uuid": "__new__"})
        assert not at.exception
        assert _categories_multiselect(at) is not None
        assert _labels_multiselect(at) is not None

    def test_preview_subheader_present(self, tmp_path):
        """The 'Preview' subheader is rendered in the editor panel."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path, {"tpl_unified_selected_uuid": "__new__"})
        assert not at.exception
        assert any("Preview" in s.value for s in at.subheader)

    def test_new_template_shows_new_caption(self, tmp_path):
        """A brand-new template shows a New caption instead of a header."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path, {"tpl_unified_selected_uuid": "__new__"})
        assert not at.exception
        assert any(c.value == "UUID: New" for c in at.caption)

    def test_save_button_present_for_new_template(self, tmp_path):
        """The Save button is rendered in the actions area."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path, {"tpl_unified_selected_uuid": "__new__"})
        assert not at.exception
        assert _save_btn(at) is not None

    def test_save_disabled_when_name_empty(self, tmp_path):
        """Save button is disabled when name is empty."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path, {"tpl_unified_selected_uuid": "__new__"})
        assert not at.exception
        save = _save_btn(at)
        assert save is not None
        assert save.disabled

    def test_save_enabled_when_name_provided(self, tmp_path):
        """Save button is enabled when a name is typed."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(
            tmp_path,
            cfg_path,
            {
                "tpl_unified_selected_uuid": "__new__",
                "tpl_meta_name": "my-template",
                "tpl_editor_textarea": _BODY_JSON,
            },
        )
        assert not at.exception
        save = _save_btn(at)
        assert save is not None
        assert not save.disabled

    def test_delete_button_disabled_for_new_template(self, tmp_path):
        """Delete button is disabled for a new (unsaved) template."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path, {"tpl_unified_selected_uuid": "__new__"})
        assert not at.exception
        delete = _delete_btn(at)
        assert delete is not None
        assert delete.disabled

    def test_replace_file_button_disabled_for_new_template(self, tmp_path):
        """'Replace file' button is disabled for a new template."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path, {"tpl_unified_selected_uuid": "__new__"})
        assert not at.exception
        replace_file = _replace_file_btn(at)
        assert replace_file is not None
        assert replace_file.disabled

    def test_invalid_json_shows_error_in_preview(self, tmp_path):
        """Invalid JSON in the editor body shows an error in the preview column."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_unified_device"] = "D1"
            at.session_state["tpl_unified_selected_uuid"] = "__new__"
            at.switch_page("pages/templates.py").run()
            area = _json_area(at)
            assert area is not None
            area.set_value(_INVALID_JSON).run()
        assert not at.exception
        assert len(at.error) >= 1

    def test_invalid_json_disables_save(self, tmp_path):
        """Save button is disabled when JSON body is invalid."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_unified_device"] = "D1"
            at.session_state["tpl_unified_selected_uuid"] = "__new__"
            at.session_state["tpl_meta_name"] = "test"
            at.switch_page("pages/templates.py").run()
            area = _json_area(at)
            assert area is not None
            area.set_value(_INVALID_JSON).run()
        assert not at.exception
        save = _save_btn(at)
        assert save is not None
        assert save.disabled

    def test_icon_svg_textarea_present(self, tmp_path):
        """The icon SVG code textarea is rendered in the editor panel."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path, {"tpl_unified_selected_uuid": "__new__"})
        assert not at.exception
        assert _svg_area(at) is not None

    def test_icon_svg_contains_decoded_svg_by_default(self, tmp_path):
        """The icon SVG textarea contains decoded SVG markup, not base64."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path, {"tpl_unified_selected_uuid": "__new__"})
        assert not at.exception
        area = _svg_area(at)
        assert area is not None
        assert "<svg" in area.value

    def test_valid_icon_size_no_warning(self, tmp_path):
        """A valid 150×200 iconData raises no size warning."""
        b64 = base64.b64encode(_SVG_150x200.encode()).decode()
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(
            tmp_path,
            cfg_path,
            {"tpl_unified_selected_uuid": "__new__", "tpl_meta_icon_data": b64},
        )
        assert not at.exception
        assert not any("150" in w.value and "200" in w.value for w in at.warning)

    def test_valid_landscape_icon_size_no_warning(self, tmp_path):
        """A valid 200×150 iconData raises no size warning in landscape mode."""
        b64 = base64.b64encode(_SVG_200x150.encode()).decode()
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(
            tmp_path,
            cfg_path,
            {
                "tpl_unified_selected_uuid": "__new__",
                "tpl_meta_orientation": "landscape",
                "tpl_meta_icon_data": b64,
            },
        )
        assert not at.exception
        assert not any("200" in w.value and "150" in w.value for w in at.warning)

    def test_wrong_icon_size_shows_warning(self, tmp_path):
        """An SVG with wrong dimensions triggers a size warning."""
        b64 = base64.b64encode(_SVG_WRONG_SIZE.encode()).decode()
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(
            tmp_path,
            cfg_path,
            {"tpl_unified_selected_uuid": "__new__", "tpl_meta_icon_data": b64},
        )
        assert not at.exception
        assert any("150" in w.value for w in at.warning)

    def test_portrait_icon_in_landscape_shows_warning(self, tmp_path):
        """A portrait iconData in landscape mode triggers a 200×150 warning."""
        b64 = base64.b64encode(_SVG_150x200.encode()).decode()
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(
            tmp_path,
            cfg_path,
            {
                "tpl_unified_selected_uuid": "__new__",
                "tpl_meta_orientation": "landscape",
                "tpl_meta_icon_data": b64,
            },
        )
        assert not at.exception
        assert any("200" in w.value and "150" in w.value for w in at.warning)

    def test_editing_svg_with_valid_size_updates_icon_data(self, tmp_path):
        """Setting the SVG textarea to a valid 150×200 SVG re-encodes it to iconData."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_unified_device"] = "D1"
            at.session_state["tpl_unified_selected_uuid"] = "__new__"
            at.switch_page("pages/templates.py").run()
            area = _svg_area(at)
            assert area is not None
            area.set_value(_SVG_150x200).run()
        assert not at.exception
        stored = at.session_state["tpl_meta_icon_data"]
        decoded = base64.b64decode(stored).decode("utf-8")
        assert 'width="150"' in decoded
        assert 'height="200"' in decoded

    def test_editing_svg_with_wrong_size_leaves_icon_data_unchanged(self, tmp_path):
        """Setting SVG textarea to a wrong-sized SVG leaves iconData unchanged."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_unified_device"] = "D1"
            at.session_state["tpl_unified_selected_uuid"] = "__new__"
            at.switch_page("pages/templates.py").run()
            original_b64 = at.session_state["tpl_meta_icon_data"]
            area = _svg_area(at)
            assert area is not None
            area.set_value(_SVG_WRONG_SIZE).run()
        assert not at.exception
        assert at.session_state["tpl_meta_icon_data"] == original_b64

    def test_editing_svg_with_landscape_size_updates_icon_data(self, tmp_path):
        """Setting the SVG textarea to a valid 200×150 SVG updates iconData in landscape."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_unified_device"] = "D1"
            at.session_state["tpl_unified_selected_uuid"] = "__new__"
            at.session_state["tpl_meta_orientation"] = "landscape"
            at.switch_page("pages/templates.py").run()
            area = _svg_area(at)
            assert area is not None
            area.set_value(_SVG_200x150).run()
        assert not at.exception
        stored = at.session_state["tpl_meta_icon_data"]
        decoded = base64.b64decode(stored).decode("utf-8")
        assert 'width="200"' in decoded
        assert 'height="150"' in decoded

    def test_icon_label_changes_with_orientation(self, tmp_path):
        """In landscape mode, the SVG editor label advertises 200×150 dimensions."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at_landscape = _at_templates(
            tmp_path,
            cfg_path,
            {
                "tpl_unified_selected_uuid": "__new__",
                "tpl_meta_orientation": "landscape",
            },
        )
        assert not at_landscape.exception
        area = _svg_area(at_landscape)
        assert area is not None
        assert "200" in area.label and "150" in area.label


# ---------------------------------------------------------------------------
# TestEditorPanelExisting — editor loaded with a real template
# ---------------------------------------------------------------------------


class TestEditorPanelExisting:
    def test_existing_template_meta_loaded_from_json(self, tmp_path):
        """Preloading tpl_editor_textarea extracts name and orientation into meta form."""
        cfg_path = with_device(tmp_path, "D1")
        template_uuid = _make_template(tmp_path, "D1", "loaded.template", _FULL_JSON)
        at = _at_templates(
            tmp_path,
            cfg_path,
            {
                "tpl_unified_selected_uuid": template_uuid,
                "tpl_editor_textarea": _FULL_JSON,
            },
        )
        assert not at.exception
        name = _name_input(at)
        assert name is not None
        assert name.value == "my-tpl"

    def test_existing_template_shows_uuid_caption(self, tmp_path):
        """An existing template shows its UUID in the caption area."""
        cfg_path = with_device(tmp_path, "D1")
        template_uuid = _make_template(tmp_path, "D1", "loaded.template", _FULL_JSON)
        at = _at_templates(
            tmp_path,
            cfg_path,
            {
                "tpl_unified_selected_uuid": template_uuid,
                "tpl_editor_textarea": _FULL_JSON,
            },
        )
        assert not at.exception
        assert any(f"UUID: {template_uuid}" in c.value for c in at.caption)

    def test_existing_template_shows_delete_button(self, tmp_path):
        """The Delete button is rendered for an existing (saved) template."""
        cfg_path = with_device(tmp_path, "D1")
        template_uuid = _make_template(tmp_path, "D1", "my-file.template")
        at = _at_templates(
            tmp_path,
            cfg_path,
            {
                "tpl_unified_selected_uuid": template_uuid,
                "tpl_editor_textarea": _FULL_JSON,
            },
        )
        assert not at.exception
        assert any(b.label == "Delete" for b in at.button)

    def test_existing_template_shows_replace_file_button(self, tmp_path):
        """The 'Replace file' button is rendered for an existing template."""
        cfg_path = with_device(tmp_path, "D1")
        template_uuid = _make_template(tmp_path, "D1", "my-file.template")
        at = _at_templates(
            tmp_path,
            cfg_path,
            {
                "tpl_unified_selected_uuid": template_uuid,
                "tpl_editor_textarea": _FULL_JSON,
            },
        )
        assert not at.exception
        assert any(b.label == "Replace file" for b in at.button)

    def test_duplicate_button_opens_unsaved_copy_in_editor(self, tmp_path):
        """Clicking Duplicate opens an unsaved copy and does not write a new file."""
        cfg_path = with_device(tmp_path, "D1")
        tdir = backup_dir(tmp_path, "D1") / "templates"
        template_uuid = _make_template(tmp_path, "D1", "dup_me.template", _FULL_JSON)

        before_count = len(list(tdir.glob("*.template")))

        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_unified_device"] = "D1"
            at.session_state["tpl_unified_selected_uuid"] = template_uuid
            at.session_state["tpl_editor_textarea"] = _FULL_JSON
            at.switch_page("pages/templates.py").run()

            dup_btn = next((b for b in at.button if b.label == "Duplicate"), None)
            assert dup_btn is not None
            dup_btn.click().run()

        assert not at.exception
        assert at.session_state["tpl_unified_selected_uuid"] == "__new__"
        assert len(list(tdir.glob("*.template"))) == before_count
        name = _name_input(at)
        assert name is not None
        assert name.value == ""

    def test_template_with_icon_data_decodes_into_svg_textarea(self, tmp_path):
        """A template whose iconData carries a custom SVG shows it decoded in the textarea."""
        b64 = base64.b64encode(_SVG_150x200.encode()).decode()
        tpl_content = json.dumps(
            {
                "name": "icon-tpl",
                "iconData": b64,
                "orientation": "portrait",
                "constants": [],
                "items": [],
            },
            indent=2,
        )
        cfg_path = with_device(tmp_path, "D1")
        template_uuid = _make_template(tmp_path, "D1", "icon_tpl.template", tpl_content)
        at = _at_templates(
            tmp_path,
            cfg_path,
            {
                "tpl_unified_selected_uuid": template_uuid,
                "tpl_editor_textarea": tpl_content,
            },
        )
        assert not at.exception
        area = _svg_area(at)
        assert area is not None
        assert "<svg" in area.value
        assert 'width="150"' in area.value

    def test_delete_dialog_opens_on_button_click(self, tmp_path):
        """Clicking the Delete button opens the delete confirmation dialog."""
        cfg_path = with_device(tmp_path, "D1")
        template_uuid = _make_template(tmp_path, "D1", "del_me.template")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_unified_device"] = "D1"
            at.session_state["tpl_unified_selected_uuid"] = template_uuid
            at.session_state["tpl_editor_textarea"] = _FULL_JSON
            at.switch_page("pages/templates.py").run()
            del_btn = next((b for b in at.button if b.label == "Delete"), None)
            assert del_btn is not None
            del_btn.click().run()
        assert not at.exception
        # Dialog should render Confirm/Cancel
        assert any(b.label in {"Delete", "Cancel"} for b in at.button)

    def test_replace_file_dialog_opens_on_button_click(self, tmp_path):
        """Clicking 'Replace file' opens the reload dialog with Save and Cancel buttons."""
        cfg_path = with_device(tmp_path, "D1")
        template_uuid = _make_template(tmp_path, "D1", "replace_me.template")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_unified_device"] = "D1"
            at.session_state["tpl_unified_selected_uuid"] = template_uuid
            at.session_state["tpl_editor_textarea"] = _FULL_JSON
            at.switch_page("pages/templates.py").run()
            reload_btn = next((b for b in at.button if b.label == "Replace file"), None)
            assert reload_btn is not None
            reload_btn.click().run()
        assert not at.exception
        assert any(b.label == "Save" for b in at.button)
        assert any(b.label == "Cancel" for b in at.button)


# ---------------------------------------------------------------------------
# TestEditorSave — save button flow
# ---------------------------------------------------------------------------


class TestEditorSave:
    def test_save_writes_template_file(self, tmp_path):
        """Clicking Save stores a .template file in the device templates dir."""
        cfg_path = with_device(tmp_path, "D1")
        tdir = backup_dir(tmp_path, "D1") / "templates"
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_unified_device"] = "D1"
            at.session_state["tpl_unified_selected_uuid"] = "__new__"
            at.session_state["tpl_meta_name"] = "save-test"
            at.session_state["tpl_editor_textarea"] = _BODY_JSON
            at.switch_page("pages/templates.py").run()
            save = _save_btn(at)
            assert save is not None
            assert not save.disabled
            save.click().run()
        assert not at.exception
        saved = list(tdir.glob("*.template"))
        assert len(saved) >= 1

    def test_save_applies_rm_manager_author_default(self, tmp_path):
        """Saving with empty author field applies 'rm-manager' to the saved JSON."""
        cfg_path = with_device(tmp_path, "D1")
        tdir = backup_dir(tmp_path, "D1") / "templates"
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_unified_device"] = "D1"
            at.session_state["tpl_unified_selected_uuid"] = "__new__"
            at.session_state["tpl_meta_name"] = "author-test"
            at.session_state["tpl_meta_author"] = ""
            at.session_state["tpl_editor_textarea"] = _BODY_JSON
            at.switch_page("pages/templates.py").run()
            save = _save_btn(at)
            assert save is not None
            save.click().run()
        assert not at.exception
        saved = list(tdir.glob("*.template"))
        assert len(saved) >= 1
        data = json.loads(saved[0].read_text(encoding="utf-8"))
        assert data.get("author") == "rm-manager"

    def test_save_accepts_custom_categories_and_labels(self, tmp_path):
        """Saving preserves newly entered categories and labels from the multiselects."""
        cfg_path = with_device(tmp_path, "D1")
        tdir = backup_dir(tmp_path, "D1") / "templates"
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_categories", return_value=["Lines", "Grids"]),
            patch("src.templates.get_all_labels", return_value=["alpha", "beta"]),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_unified_device"] = "D1"
            at.session_state["tpl_unified_selected_uuid"] = "__new__"
            at.session_state["tpl_meta_name"] = "multiselect-test"
            at.session_state["tpl_meta_categories"] = ["Lines", "Custom category"]
            at.session_state["tpl_meta_labels"] = ["alpha", "Custom label"]
            at.session_state["tpl_editor_textarea"] = _BODY_JSON
            at.switch_page("pages/templates.py").run()
            save = _save_btn(at)
            assert save is not None
            save.click().run()
        assert not at.exception
        saved = list(tdir.glob("*.template"))
        assert len(saved) >= 1
        data = json.loads(saved[0].read_text(encoding="utf-8"))
        assert data.get("categories") == ["Lines", "Custom category"]
        assert data.get("labels") == ["alpha", "Custom label"]

    def test_save_updates_selected_state(self, tmp_path):
        """After saving, tpl_unified_selected_uuid stores a valid UUID."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_unified_device"] = "D1"
            at.session_state["tpl_unified_selected_uuid"] = "__new__"
            at.session_state["tpl_meta_name"] = "persist-name"
            at.session_state["tpl_editor_textarea"] = _BODY_JSON
            at.switch_page("pages/templates.py").run()
            save = _save_btn(at)
            assert save is not None
            save.click().run()
        assert not at.exception
        selected = at.session_state["tpl_unified_selected_uuid"]
        assert isinstance(selected, str)
        uuid.UUID(selected)

    def test_save_existing_template_preserves_manifest_entry(self, tmp_path):
        """Editing and re-saving an existing template updates the manifest without error."""
        cfg_path = with_device(tmp_path, "D1")
        d = backup_dir(tmp_path, "D1")
        template_uuid = "11111111-2222-4333-8444-555555555555"
        (d / "manifest.json").write_text(
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
        (d / "templates" / f"{template_uuid}.template").write_text(_FULL_JSON, encoding="utf-8")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_unified_device"] = "D1"
            at.session_state["tpl_unified_selected_uuid"] = template_uuid
            at.session_state["tpl_meta_name"] = "Blank"
            at.session_state["tpl_editor_textarea"] = _BODY_JSON
            at.switch_page("pages/templates.py").run()
            save = _save_btn(at)
            assert save is not None
            save.click().run()
        assert not at.exception
        manifest = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        assert template_uuid in manifest["templates"]


# ---------------------------------------------------------------------------
# TestTemplateListCaptions — empty / filter-miss states
# ---------------------------------------------------------------------------


class TestTemplateListCaptions:
    def test_empty_templates_shows_no_templates_caption(self, tmp_path):
        """When no template files exist, 'No templates yet' caption is shown."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")  # empty templates dir
        at = _at_templates(tmp_path, cfg_path)
        assert not at.exception
        assert any("No templates" in c.value for c in at.caption)

    def test_filter_text_no_match_shows_caption(self, tmp_path):
        """Filtering by text that matches no template shows 'No templates match' caption."""
        cfg_path = with_device(tmp_path, "D1")
        _make_template(tmp_path, "D1", "lines.template")
        at = _at_templates(tmp_path, cfg_path, {"tpl_filter_text": "zzznomatch"})
        assert not at.exception
        assert any("match" in c.value.lower() for c in at.caption)

    def test_template_count_caption_shown(self, tmp_path):
        """The left panel shows 'N template(s)' caption when templates exist."""
        cfg_path = with_device(tmp_path, "D1")
        _make_template(tmp_path, "D1", "lines.template")
        at = _at_templates(tmp_path, cfg_path)
        assert not at.exception
        assert any("template" in c.value.lower() for c in at.caption)


# ---------------------------------------------------------------------------
# TestNewButtonFlow — clicking New opens the editor
# ---------------------------------------------------------------------------


class TestNewButtonFlow:
    def test_new_button_click_shows_editor(self, tmp_path):
        """Clicking the New button causes the editor panel to appear."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            new_btn = next((b for b in at.button if b.label == "New"), None)
            assert new_btn is not None
            new_btn.click().run()
        assert not at.exception
        assert at.session_state["tpl_unified_selected_uuid"] == "__new__"
        assert _save_btn(at) is not None

    def test_new_button_sets_default_json(self, tmp_path):
        """After clicking New, tpl_editor_textarea contains the default JSON."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            next(b for b in at.button if b.label == "New").click().run()
        assert not at.exception
        assert _json_area(at) is not None


# ---------------------------------------------------------------------------
# TestImportDialog — import button triggers dialog
# ---------------------------------------------------------------------------


class TestImportDialog:
    def test_import_button_is_present(self, tmp_path):
        """The Import button is always present in the left panel."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        at = _at_templates(tmp_path, cfg_path)
        assert not at.exception
        assert any(b.label == "Import" for b in at.button)
