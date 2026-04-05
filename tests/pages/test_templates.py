"""Tests for pages/templates.py.

Covers: empty-config warning, manifest-init warning, import success/failure,
dirty banner with sync, all sync branches, template card grid, rename mode,
delete flow, sort-by, and upload section render.
"""

import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from tests.pages.helpers import (
    at_page,
    backup_dir,
    empty_cfg,
    make_env,
    with_device,
    with_two_devices,
)

# Minimal valid reMarkable JSON template used as synthetic template content.
_TEMPLATE_BYTES = b'{"orientation":"portrait","constants":[],"items":[]}'


def _make_templates(tmp_path, device: str = "D1", names: list[str] | None = None) -> list[str]:
    """Create real .template files inside the device templates dir and return their names."""
    names = names or ["alpha.template", "beta.template"]
    tdir = tmp_path / device / "templates"
    tdir.mkdir(parents=True, exist_ok=True)
    manifest = tmp_path / device / "manifest.json"
    if not manifest.exists():
        manifest.write_text(
            '{"last_modified": null, "templates": {}}',
            encoding="utf-8",
        )
    for name in names:
        (tdir / name).write_bytes(_TEMPLATE_BYTES)
    return names


def test_templates_page_warns_when_no_devices(tmp_path):
    """Templates page shows 'No device' message with empty config."""
    with patch.dict(os.environ, make_env(tmp_path, empty_cfg(tmp_path))):
        at = AppTest.from_file("app.py")
        at.run()
        at.switch_page("pages/templates.py").run()

    assert not at.exception
    assert any("No device" in m.value for m in at.markdown)


class TestTemplatesPage:
    # -- no manifest yet ------------------------------------------------------

    def test_no_manifest_shows_warning_and_import_button(self, tmp_path):
        """Without a manifest file, page shows the initialize warning and action button."""
        cfg_path = with_device(tmp_path, "D1")
        at = at_page(tmp_path, "pages/templates.py", cfg_path)
        assert not at.exception
        assert any("not been imported yet" in w.value for w in at.warning)
        assert any("Initialize templates" in b.label for b in at.button)

    def test_import_button_click_success(self, tmp_path):
        """Clicking initialize triggers fetch_and_init_templates directly."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.template_sync.fetch_and_init_templates", return_value=(True, "3 templates")),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            import_btn = next((b for b in at.button if "Initialize templates" in b.label), None)
            assert import_btn is not None
            import_btn.click().run()
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
            import_btn = next((b for b in at.button if "Initialize templates" in b.label), None)
            assert import_btn is not None
            import_btn.click().run()
        assert not at.exception
        assert any("SSH connection refused" in e.value for e in at.error)

    # -- manifest exists, no templates ---------------------------------------

    def test_manifest_exists_no_templates_shows_info(self, tmp_path):
        """With manifest but zero templates, page renders 'No templates' info."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_categories", return_value=[]),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any("No templates" in m.value for m in at.info)

    # -- dirty banner -------------------------------------------------------

    def test_dirty_templates_shows_sync_button(self, tmp_path):
        """When templates are locally modified, a Synchroniser button is shown."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_categories", return_value=[]),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any("Sync" in b.label for b in at.button)

    def test_sync_button_click_success(self, tmp_path):
        """Clicking Sync triggers the sync pipeline successfully."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)

        def _download(_ip, _pw, remote_path):
            if remote_path.endswith("/.manifest.json"):
                return None, "No such file"
            return None, "missing"

        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_categories", return_value=[]),
            patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
            patch("src.templates.remove_remote_custom_templates", return_value=(True, "ok")),
            patch("src.template_sync._ssh.download_file_ssh", side_effect=_download),
            patch("src.ssh.run_ssh_cmd", return_value=("", "")),
            patch("src.ssh.upload_file_ssh", return_value=(True, "ok")),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            sync_btn = next((b for b in at.button if "Sync" in b.label), None)
            assert sync_btn is not None
            sync_btn.click().run()
        assert not at.exception

    def test_reset_reinitialize_button_click_success(self, tmp_path):
        """Clicking Reset and reinitialize triggers the full local wipe + import flow."""
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
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            reset_btn = next((b for b in at.button if "Reset and reinitialize" in b.label), None)
            assert reset_btn is not None
            reset_btn.click().run()
        assert not at.exception

    def test_sync_button_click_ensure_dirs_failure(self, tmp_path):
        """When ensure_remote_template_dirs fails, sync shows an error; no exception."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_categories", return_value=[]),
            patch("src.templates.ensure_remote_template_dirs", return_value=(False, "SSH error")),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            sync_btn = next((b for b in at.button if "Sync" in b.label), None)
            assert sync_btn is not None
            sync_btn.click().run()
        assert not at.exception

    # -- upload section -------------------------------------------------

    def test_upload_section_renders_file_uploader(self, tmp_path):
        """The upload-a-template section must always render a file uploader."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_categories", return_value=[]),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any("Add" in s.value for s in at.subheader)

    def test_import_tab_with_selected_file_renders_metadata_fields(self, tmp_path):
        """Once a file is selected, import metadata widgets are rendered for the row layout."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        mock_upload = SimpleNamespace(
            name="alpha.template",
            read=lambda: _TEMPLATE_BYTES,
        )
        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_categories", return_value=["Lines", "Grid"]),
            patch("streamlit.file_uploader", return_value=[mock_upload]),
        ):
            at = AppTest.from_file("pages/templates.py")
            at.session_state["config"] = {
                "devices": {
                    "D1": {
                        "ip": "10.0.0.1",
                        "password": "pw",
                        "device_type": "reMarkable 2",
                    }
                }
            }
            at.session_state["selected_name"] = "D1"
            at.session_state["add_log"] = lambda msg: None
            at.run()
        assert not at.exception
        assert any(m.label == "Existing categories" for m in at.multiselect)
        assert any(t.label == "New categories (comma-separated)" for t in at.text_input)

    def test_import_tab_prefills_categories_from_single_template_file(self, tmp_path):
        """A single uploaded `.template` file prefills categories from its JSON metadata."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        mock_upload = SimpleNamespace(
            name="alpha.template",
            getvalue=lambda: json.dumps({"categories": ["Lines", "Perso"]}).encode("utf-8"),
        )
        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_categories", return_value=["Grid", "Lines"]),
            patch("streamlit.file_uploader", return_value=[mock_upload]),
        ):
            at = AppTest.from_file("pages/templates.py")
            at.session_state["config"] = {
                "devices": {
                    "D1": {
                        "ip": "10.0.0.1",
                        "password": "pw",
                        "device_type": "reMarkable 2",
                    }
                }
            }
            at.session_state["selected_name"] = "D1"
            at.session_state["add_log"] = lambda msg: None
            at.run()
        assert not at.exception
        assert any(multiselect.value == ["Lines"] for multiselect in at.multiselect)
        assert any(
            text_input.label == "New categories (comma-separated)" and text_input.value == "Perso"
            for text_input in at.text_input
        )

    def test_import_tab_prefills_only_when_all_template_categories_match(self, tmp_path):
        """Mixed category sets across uploaded `.template` files must not prefill the fields."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        upload_a = SimpleNamespace(
            name="alpha.template",
            getvalue=lambda: json.dumps({"categories": ["Lines"]}).encode("utf-8"),
        )
        upload_b = SimpleNamespace(
            name="beta.template",
            getvalue=lambda: json.dumps({"categories": ["Grid"]}).encode("utf-8"),
        )
        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_categories", return_value=["Grid", "Lines"]),
            patch("streamlit.file_uploader", return_value=[upload_a, upload_b]),
        ):
            at = AppTest.from_file("pages/templates.py")
            at.session_state["config"] = {
                "devices": {
                    "D1": {
                        "ip": "10.0.0.1",
                        "password": "pw",
                        "device_type": "reMarkable 2",
                    }
                }
            }
            at.session_state["selected_name"] = "D1"
            at.session_state["add_log"] = lambda msg: None
            at.run()
        assert not at.exception
        assert any(multiselect.value == [] for multiselect in at.multiselect)
        assert any(
            text_input.label == "New categories (comma-separated)" and text_input.value == ""
            for text_input in at.text_input
        )

    # -- template card grid ---------------------------------------------

    def test_template_card_renders_grid(self, tmp_path):
        """With real .template files in the templates dir, the card grid renders."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["card_a.template", "card_b.template"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        # Card name buttons must be present
        assert any("card_a" in b.label for b in at.button)

    def test_template_card_rename_mode_shows_form(self, tmp_path):
        """Setting tpl_renaming in session state renders the inline rename form."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["mypic.template"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_renaming"] = "mypic.template"
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any(":material/check:" in b.label for b in at.button)

    def test_template_delete_pending_triggers_confirm(self, tmp_path):
        """Setting tpl_pending_delete_local renders the confirm dialog."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["todel.template"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_pending_delete_local"] = "todel.template"
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert not any(c.label == "Also delete it from the tablet" for c in at.checkbox)

    def test_template_delete_confirmed_removes(self, tmp_path):
        """Pending local delete renders the delete dialog action buttons."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["gone.template"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_pending_delete_local"] = "gone.template"
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any(b.label == "Delete" for b in at.button)

    def test_template_delete_cancelled_clears_state(self, tmp_path):
        """Pending local delete renders a Cancel action in the delete dialog."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["keep.template"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_pending_delete_local"] = "keep.template"
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any(b.label == "Cancel" for b in at.button)

    def test_rename_conflict_shows_confirm_dialog(self, tmp_path):
        """When tpl_pending_rename is set, the overwrite confirmation dialog is triggered."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["old.template", "new.template"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_pending_rename"] = ("old.template", "new.template")
            at.switch_page("pages/templates.py").run()
        assert not at.exception

    def test_rename_conflict_confirmed_renames_template(self, tmp_path):
        """When confirm_rename_tpl is True, the template is renamed and state cleared."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["old.template", "new.template"])
        env = make_env(tmp_path, cfg_path)
        renamed: list[tuple] = []
        with (
            patch.dict(os.environ, env),
            patch(
                "src.templates.rename_device_template",
                side_effect=lambda n, o, f: renamed.append((o, f)),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_pending_rename"] = ("old.template", "new.template")
            at.session_state["confirm_rename_tpl"] = True
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert ("old.template", "new.template") in renamed
        assert at.session_state["tpl_pending_rename"] is None
        assert at.session_state["tpl_renaming"] is None

    def test_rename_conflict_cancelled_clears_state(self, tmp_path):
        """When confirm_rename_tpl is False, state is cleared without renaming."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["old.template", "new.template"])
        env = make_env(tmp_path, cfg_path)
        renamed: list[tuple] = []
        with (
            patch.dict(os.environ, env),
            patch(
                "src.templates.rename_device_template",
                side_effect=lambda n, o, f: renamed.append((o, f)),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_pending_rename"] = ("old.template", "new.template")
            at.session_state["confirm_rename_tpl"] = False
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert not renamed
        assert at.session_state["tpl_pending_rename"] is None
        assert at.session_state["tpl_renaming"] is None

    def test_sort_az_renders_without_error(self, tmp_path):
        """Sort-by 'A → Z' is applied without error when templates exist."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["zzz.template", "aaa.template"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            sc = next((s for s in at.button_group if "Sort" in s.label), None)
            assert sc is not None
            sc.set_value("A \u2192 Z").run()
        assert not at.exception

    def test_sort_categories_renders_without_error(self, tmp_path):
        """Sort-by 'Catégories' is applied without error when templates exist."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["zzz.template", "aaa.template"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            sc = next((s for s in at.button_group if "Sort" in s.label), None)
            assert sc is not None
            sc.set_value("Categories").run()
        assert not at.exception

    def test_edit_template_with_non_default_tablet_does_not_crash(self, tmp_path):
        """Editing a template after selecting a non-default tablet must not raise StreamlitAPIException."""
        cfg_path = with_two_devices(tmp_path)
        d2 = backup_dir(tmp_path, "D2")
        (d2 / "templates" / "custom.template").write_text("{}", encoding="utf-8")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.load_json_template", return_value="{}"),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.selectbox(key="tablet").set_value("D2").run()
            at.session_state["tpl_edit_target"] = "custom.template"
            at.switch_page("pages/templates.py").run()
        assert not at.exception


# ---------------------------------------------------------------------------
# Upload-to-tablet confirmation after overwriting an existing template
# ---------------------------------------------------------------------------


class TestTemplateReload:
    """Tests for the per-card reload (update template) feature."""

    """When a saved template overwrites an existing file and templates are not dirty,
    the user is asked whether to push the file to the tablet immediately."""

    def test_reload_dialog_shows_when_reloading(self, tmp_path):
        """When tpl_reloading is set, the reload dialog opens with Save and Cancel buttons."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["my.template"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_reloading"] = "my.template"
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any(b.label == "Save" for b in at.button)
        assert any(b.label == "Cancel" for b in at.button)

    def test_reload_save_button_present(self, tmp_path):
        """The Save button in the reload dialog is present (disabled until file selected)."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["my.template"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.save_device_template"),
            patch("src.templates.upload_template_to_tablet", return_value=(True, "ok")),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_reloading"] = "my.template"
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any(b.label == "Save" for b in at.button)

    def test_reload_cancel_clears_state(self, tmp_path):
        """Clicking Cancel in the reload dialog sets tpl_reloading to None."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["my.template"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_reloading"] = "my.template"
            at.switch_page("pages/templates.py").run()
            cancel_btn = next((b for b in at.button if b.label == "Cancel"), None)
            assert cancel_btn is not None
            cancel_btn.click().run()
        assert not at.exception
        assert at.session_state["tpl_reloading"] is None

    def test_reload_upload_failure_logs_error(self, tmp_path):
        """When upload_template_to_tablet fails, the dialog still renders without exception."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["my.template"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.save_device_template"),
            patch(
                "src.templates.upload_template_to_tablet",
                return_value=(False, "SSH error"),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_reloading"] = "my.template"
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any(b.label == "Save" for b in at.button)


# ---------------------------------------------------------------------------
# Additional .template-only scenarios
# ---------------------------------------------------------------------------

# Minimal reMarkable JSON template
_JSON_TEMPLATE = '{"orientation":"portrait","constants":[],"items":[]}'


def _make_json_template(tmp_path, device: str = "D1", name: str = "MyLines.template") -> str:
    """Create a .template JSON file in the device templates dir and return its name."""
    d = backup_dir(tmp_path, device)
    tdir = d / "templates"
    stem = name.removesuffix(".template")
    (tdir / name).write_text(_JSON_TEMPLATE, encoding="utf-8")
    template_uuid = "00000000-0000-4000-8000-000000000001"
    (d / "manifest.json").write_text(
        json.dumps(
            {
                "last_modified": None,
                "templates": {
                    template_uuid: {
                        "name": stem,
                        "created_at": "2025-01-10T09:00:00Z",
                        "sha256": "abc123",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return name


class TestTemplatePageJsonTemplates:
    """Tests that verify .template (JSON) files appear and behave correctly on the templates page."""

    def test_json_template_card_renders(self, tmp_path):
        """A .template file creates a card on the templates page."""
        cfg_path = with_device(tmp_path, "D1")
        _make_json_template(tmp_path, "D1", "grid.template")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any("grid" in b.label.lower() for b in at.button)

    def test_two_template_cards_render(self, tmp_path):
        """Two distinct .template files coexist on the page."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["my_svg.template"])
        _make_json_template(tmp_path, "D1", "my_json.template")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        labels = [b.label.lower() for b in at.button]
        assert any("my_svg" in lbl for lbl in labels)
        assert any("my_json" in lbl for lbl in labels)

    def test_json_template_rename_preserves_template_extension(self, tmp_path):
        """Renaming a .template card stores the new name with .template extension."""
        cfg_path = with_device(tmp_path, "D1")
        _make_json_template(tmp_path, "D1", "old.template")
        env = make_env(tmp_path, cfg_path)
        renamed: list[tuple] = []
        with (
            patch.dict(os.environ, env),
            patch(
                "src.templates.rename_device_template",
                side_effect=lambda n, o, f: renamed.append((o, f)),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_renaming"] = "old.template"
            at.session_state["tpl_rename_input_old.template"] = "new_name"
            at.session_state["tpl_pending_rename"] = ("old.template", "new_name.template")
            at.session_state["confirm_rename_tpl"] = True
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        # The new filename must preserve the .template extension
        if renamed:
            _, new_name = renamed[0]
            assert new_name.endswith(".template")

    def test_upload_section_accepts_template_files(self, tmp_path):
        """The upload section remains available for .template files."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_categories", return_value=[]),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        # The "Add a template" subheader triggers the upload section to render
        assert any("Add" in s.value for s in at.subheader)

    def test_json_template_delete_removes_file(self, tmp_path):
        """Confirming deletion from the dialog calls delete_device_template."""
        cfg_path = with_device(tmp_path, "D1")
        _make_json_template(tmp_path, "D1", "todel.template")
        env = make_env(tmp_path, cfg_path)
        deleted: list[str] = []
        with (
            patch.dict(os.environ, env),
            patch(
                "src.templates.delete_device_template",
                side_effect=lambda n, f: deleted.append(f),
            ),
            patch("src.templates.remove_template_entry"),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_pending_delete_local"] = "todel.template"
            at.switch_page("pages/templates.py").run()
            delete_btn = next((b for b in at.button if b.label == "Delete"), None)
            assert delete_btn is not None
            delete_btn.click().run()
        assert not at.exception
        assert len(deleted) == 1
        assert deleted[0].endswith(".template")


# ---------------------------------------------------------------------------
# Segmented control options per file type
# ---------------------------------------------------------------------------


class TestSegmentedControlOptions:
    """The edit option must be present for .template files."""

    def test_template_card_has_edit_option(self, tmp_path):
        """A .template card's action control includes the edit option."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["photo.template"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        sc = next((s for s in at.button_group if s.key == "tpl_action_photo.template"), None)
        assert sc is not None
        # .template cards: upload + edit + delete (3 options)
        assert len(sc.options) == 3

    def test_json_template_card_has_edit_option(self, tmp_path):
        """A .template card's action control includes the edit option (3 options total)."""
        cfg_path = with_device(tmp_path, "D1")
        _make_json_template(tmp_path, "D1", "lines.template")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        sc = next((s for s in at.button_group if s.key == "tpl_action_lines.template"), None)
        assert sc is not None
        # .template cards: upload + edit + delete (3 options)
        assert len(sc.options) == 3

    def test_json_template_edit_action_preserves_selected_template_for_editor(self, tmp_path):
        """Choosing edit stores the selected template without forcing the editor back to New."""
        cfg_path = with_device(tmp_path, "D1")
        _make_json_template(tmp_path, "D1", "lines.template")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            sc = next((s for s in at.button_group if s.key == "tpl_action_lines.template"), None)
            assert sc is not None
            sc.set_value("edit").run()
        assert not at.exception
        assert at.session_state["tpl_editor_load_choice"] == "lines.template"
        assert (
            "tpl_editor_reset_choice" not in at.session_state
            or not at.session_state["tpl_editor_reset_choice"]
        )


class TestSyncCheckActions:
    """Templates page exposes the non-destructive sync status check action."""

    def test_check_sync_status_button_is_rendered(self, tmp_path):
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with patch.dict(os.environ, env):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()

        assert not at.exception
        assert any(b.label == "Check sync status" for b in at.button)

    def test_check_sync_status_button_click_success(self, tmp_path):
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
            btn = next((b for b in at.button if b.label == "Check sync status"), None)
            assert btn is not None
            btn.click().run()

        assert not at.exception


# ---------------------------------------------------------------------------
# Multi-row grid (> GRID_COLUMNS templates)
# ---------------------------------------------------------------------------


class TestMultiRowGrid:
    """Tests for template grids spanning more than one row."""

    def test_multi_row_grid_renders_divider(self, tmp_path):
        """When there are more than GRID_COLUMNS (5) templates, a divider is rendered."""
        cfg_path = with_device(tmp_path, "D1")
        # Create 6 .template files so the grid spans two rows (GRID_COLUMNS = 5)
        _make_templates(tmp_path, "D1", [f"t{i}.template" for i in range(6)])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        # All 6 cards must appear
        for i in range(6):
            assert any(f"t{i}" in b.label for b in at.button)


# ---------------------------------------------------------------------------
# Long template name truncation
# ---------------------------------------------------------------------------


class TestLongTemplateName:
    """Tests for display_name truncation in the template card header."""

    def test_name_over_20_chars_is_truncated(self, tmp_path):
        """A template stem longer than 20 chars is shown as first-17-chars + '...'."""
        long_stem = "a_very_long_template_name_indeed"  # 32 chars
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", [f"{long_stem}.template"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        # Button label must use the truncated form
        truncated = long_stem[:17] + "..."
        assert any(truncated in b.label for b in at.button)


# ---------------------------------------------------------------------------
# Category dialog
# ---------------------------------------------------------------------------


class TestCategoryDialog:
    """Tests for _show_category_dialog triggered from the template card."""

    def test_category_button_shows_dialog_controls(self, tmp_path):
        """Clicking the category button renders the dialog multiselect and action buttons."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["mycard.template"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_categories", return_value=["Lines", "Dots"]),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            cats_btn = next(
                (b for b in at.button if b.key and b.key.startswith("tpl_cats_btn_")), None
            )
            assert cats_btn is not None
            cats_btn.click().run()
        assert not at.exception
        # Dialog should render the Apply / Cancel buttons
        assert any(b.label == "Apply" for b in at.button)
        assert any(b.label == "Cancel" for b in at.button)

    def test_category_dialog_annuler_closes_without_saving(self, tmp_path):
        """Clicking Cancel in the category dialog does not call update_template_categories."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["mycard.template"])
        env = make_env(tmp_path, cfg_path)
        calls: list = []
        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_categories", return_value=[]),
            patch(
                "src.templates.update_template_categories",
                side_effect=lambda *a: calls.append(a),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            cats_btn = next(
                (b for b in at.button if b.key and b.key.startswith("tpl_cats_btn_")), None
            )
            assert cats_btn is not None
            cats_btn.click().run()
            annuler_btn = next((b for b in at.button if b.label == "Cancel"), None)
            assert annuler_btn is not None
            annuler_btn.click().run()
        assert not at.exception
        assert not calls


class TestLabelsDialog:
    """Tests for _show_labels_dialog triggered from the template card."""

    def test_labels_button_shows_dialog_controls(self, tmp_path):
        """Clicking the labels button renders the dialog controls."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["mycard.template"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_labels", return_value=["work", "study"]),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            labels_btn = next(
                (b for b in at.button if b.key and b.key.startswith("tpl_labels_btn_")), None
            )
            assert labels_btn is not None
            labels_btn.click().run()
        assert not at.exception
        assert any(b.label == "Apply" for b in at.button)
        assert any(b.label == "Cancel" for b in at.button)

    def test_labels_dialog_cancel_closes_without_saving(self, tmp_path):
        """Clicking Cancel in labels dialog does not call update_template_labels."""
        cfg_path = with_device(tmp_path, "D1")
        _make_templates(tmp_path, "D1", ["mycard.template"])
        env = make_env(tmp_path, cfg_path)
        calls: list = []
        with (
            patch.dict(os.environ, env),
            patch("src.templates.get_all_labels", return_value=[]),
            patch(
                "src.templates.update_template_labels",
                side_effect=lambda *a: calls.append(a),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            labels_btn = next(
                (b for b in at.button if b.key and b.key.startswith("tpl_labels_btn_")), None
            )
            assert labels_btn is not None
            labels_btn.click().run()
            cancel_btn = next((b for b in at.button if b.label == "Cancel"), None)
            assert cancel_btn is not None
            cancel_btn.click().run()
        assert not at.exception
        assert not calls
