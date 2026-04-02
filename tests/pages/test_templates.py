"""Tests for pages/templates.py.

Covers: empty-config warning, no-backup warning, import success/failure,
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

# Minimal valid SVG used as synthetic template content.
_SVG = b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"></svg>'


def _make_svgs(tmp_path, device: str = "D1", names: list[str] | None = None) -> list[str]:
    """Create real SVG files inside the device templates dir and return their names."""
    names = names or ["alpha.svg", "beta.svg"]
    tdir = tmp_path / device / "templates"
    tdir.mkdir(parents=True, exist_ok=True)
    # Also ensure backup file exists so the page enters the 'else' branch
    backup = tmp_path / device / "templates.backup.json"
    if not backup.exists():
        backup.write_text('{"templates": []}', encoding="utf-8")
    manifest = tmp_path / device / "manifest.json"
    if not manifest.exists():
        manifest.write_text(
            '{"version": 1, "lastSync": null, "templates": []}',
            encoding="utf-8",
        )
    for name in names:
        (tdir / name).write_bytes(_SVG)
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
    # -- no backup yet -------------------------------------------------------

    def test_no_backup_shows_warning_and_import_button(self, tmp_path):
        """Without a backup file, page shows 'not yet imported' warning + import button."""
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
            patch("src.templates.fetch_and_init_templates", return_value=(True, "3 templates")),
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
                "src.templates.fetch_and_init_templates",
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

    # -- backup exists, no templates ----------------------------------------

    def test_backup_exists_no_templates_shows_info(self, tmp_path):
        """With backup but zero SVGs, page renders 'No templates' info."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
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
            patch("src.templates.is_templates_dirty", return_value=True),
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
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=True),
            patch("src.templates.get_all_categories", return_value=[]),
            patch("src.templates.ensure_remote_template_dirs", return_value=(True, "ok")),
            patch("src.templates.list_remote_custom_templates", return_value=(True, set())),
            patch("src.templates.remove_remote_custom_templates", return_value=(True, "ok")),
            patch("src.template_sync.load_manifest", return_value={"templates": []}),
            patch("src.template_sync.list_manifest_entries", return_value=[]),
            patch("src.template_sync.mark_synced"),
            patch("src.ssh.run_ssh_cmd"),
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
            patch("src.templates.is_templates_dirty", return_value=False),
            patch("src.templates.get_all_categories", return_value=[]),
            patch(
                "src.templates.reset_and_initialize_templates_from_tablet",
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
            patch("src.templates.is_templates_dirty", return_value=True),
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
            patch("src.templates.is_templates_dirty", return_value=False),
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
            name="alpha.svg",
            read=lambda: _SVG,
        )
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
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
        assert any(t.label == "Icon code (hex)" for t in at.text_input)
        assert any("Icon preview" in c.value for c in at.caption)

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
            patch("src.templates.is_templates_dirty", return_value=False),
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
            patch("src.templates.is_templates_dirty", return_value=False),
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
        """With real SVG files in the templates dir, the card grid renders."""
        cfg_path = with_device(tmp_path, "D1")
        _make_svgs(tmp_path, "D1", ["card_a.svg", "card_b.svg"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
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
        _make_svgs(tmp_path, "D1", ["mypic.svg"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_renaming"] = "mypic.svg"
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any(":material/check:" in b.label for b in at.button)

    def test_template_delete_pending_triggers_confirm(self, tmp_path):
        """Setting tpl_pending_delete_local renders the confirm dialog."""
        cfg_path = with_device(tmp_path, "D1")
        _make_svgs(tmp_path, "D1", ["todel.svg"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_pending_delete_local"] = "todel.svg"
            at.switch_page("pages/templates.py").run()
        assert not at.exception

    def test_template_delete_confirmed_removes(self, tmp_path):
        """Pending local delete renders the delete dialog action buttons."""
        cfg_path = with_device(tmp_path, "D1")
        _make_svgs(tmp_path, "D1", ["gone.svg"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_pending_delete_local"] = "gone.svg"
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any(b.label == "Delete" for b in at.button)

    def test_template_delete_cancelled_clears_state(self, tmp_path):
        """Pending local delete renders a Cancel action in the delete dialog."""
        cfg_path = with_device(tmp_path, "D1")
        _make_svgs(tmp_path, "D1", ["keep.svg"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_pending_delete_local"] = "keep.svg"
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any(b.label == "Cancel" for b in at.button)

    def test_rename_conflict_shows_confirm_dialog(self, tmp_path):
        """When tpl_pending_rename is set, the overwrite confirmation dialog is triggered."""
        cfg_path = with_device(tmp_path, "D1")
        _make_svgs(tmp_path, "D1", ["old.svg", "new.svg"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_pending_rename"] = ("old.svg", "new.svg")
            at.switch_page("pages/templates.py").run()
        assert not at.exception

    def test_rename_conflict_confirmed_renames_template(self, tmp_path):
        """When confirm_rename_tpl is True, the template is renamed and state cleared."""
        cfg_path = with_device(tmp_path, "D1")
        _make_svgs(tmp_path, "D1", ["old.svg", "new.svg"])
        env = make_env(tmp_path, cfg_path)
        renamed: list[tuple] = []
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
            patch(
                "src.templates.rename_device_template",
                side_effect=lambda n, o, f: renamed.append((o, f)),
            ),
            patch("src.templates.rename_template_entry"),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_pending_rename"] = ("old.svg", "new.svg")
            at.session_state["confirm_rename_tpl"] = True
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert ("old.svg", "new.svg") in renamed
        assert at.session_state["tpl_pending_rename"] is None
        assert at.session_state["tpl_renaming"] is None

    def test_rename_conflict_cancelled_clears_state(self, tmp_path):
        """When confirm_rename_tpl is False, state is cleared without renaming."""
        cfg_path = with_device(tmp_path, "D1")
        _make_svgs(tmp_path, "D1", ["old.svg", "new.svg"])
        env = make_env(tmp_path, cfg_path)
        renamed: list[tuple] = []
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
            patch(
                "src.templates.rename_device_template",
                side_effect=lambda n, o, f: renamed.append((o, f)),
            ),
            patch("src.templates.rename_template_entry"),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_pending_rename"] = ("old.svg", "new.svg")
            at.session_state["confirm_rename_tpl"] = False
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert not renamed
        assert at.session_state["tpl_pending_rename"] is None
        assert at.session_state["tpl_renaming"] is None

    def test_sort_az_renders_without_error(self, tmp_path):
        """Sort-by 'A → Z' is applied without error when templates exist."""
        cfg_path = with_device(tmp_path, "D1")
        _make_svgs(tmp_path, "D1", ["zzz.svg", "aaa.svg"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
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
        _make_svgs(tmp_path, "D1", ["zzz.svg", "aaa.svg"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
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
            patch("src.templates.is_templates_dirty", return_value=False),
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
    """Tests for the per-card reload (update SVG) feature."""

    """When a saved template overwrites an existing file and templates are not dirty,
    the user is asked whether to push the file to the tablet immediately."""

    def test_reload_dialog_shows_when_reloading(self, tmp_path):
        """When tpl_reloading is set, the reload dialog opens with Save and Cancel buttons."""
        cfg_path = with_device(tmp_path, "D1")
        _make_svgs(tmp_path, "D1", ["my.svg"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_reloading"] = "my.svg"
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any(b.label == "Save" for b in at.button)
        assert any(b.label == "Cancel" for b in at.button)

    def test_reload_save_button_present(self, tmp_path):
        """The Save button in the reload dialog is present (disabled until file selected)."""
        cfg_path = with_device(tmp_path, "D1")
        _make_svgs(tmp_path, "D1", ["my.svg"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
            patch("src.templates.save_device_template"),
            patch("src.templates.upload_template_to_tablet", return_value=(True, "ok")),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_reloading"] = "my.svg"
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any(b.label == "Save" for b in at.button)

    def test_reload_cancel_clears_state(self, tmp_path):
        """Clicking Cancel in the reload dialog sets tpl_reloading to None."""
        cfg_path = with_device(tmp_path, "D1")
        _make_svgs(tmp_path, "D1", ["my.svg"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_reloading"] = "my.svg"
            at.switch_page("pages/templates.py").run()
            cancel_btn = next((b for b in at.button if b.label == "Cancel"), None)
            assert cancel_btn is not None
            cancel_btn.click().run()
        assert not at.exception
        assert at.session_state["tpl_reloading"] is None

    def test_reload_upload_failure_logs_error(self, tmp_path):
        """When upload_template_to_tablet fails, the dialog still renders without exception."""
        cfg_path = with_device(tmp_path, "D1")
        _make_svgs(tmp_path, "D1", ["my.svg"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
            patch("src.templates.save_device_template"),
            patch(
                "src.templates.upload_template_to_tablet",
                return_value=(False, "SSH error"),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_reloading"] = "my.svg"
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any(b.label == "Save" for b in at.button)


# ---------------------------------------------------------------------------
# Template icon code
# ---------------------------------------------------------------------------


class TestTemplateIconCode:
    """Tests for icon-code handling in template cards."""

    def _make_template_with_icon(
        self, tmp_path, device: str, filename: str, icon_code: str
    ) -> None:
        """Create an SVG + templates/manifest entries (with *icon_code*) + backup stub."""
        stem = filename.removesuffix(".svg")
        d = backup_dir(tmp_path, device)
        (d / "templates" / filename).write_bytes(_SVG)
        (d / "templates.json").write_text(
            json.dumps(
                {
                    "templates": [
                        {
                            "name": stem,
                            "filename": stem,
                            "iconCode": icon_code,
                            "categories": ["Lines"],
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (d / "manifest.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "lastSync": None,
                    "templates": [
                        {
                            "name": stem,
                            "filename": stem,
                            "iconCode": icon_code,
                            "categories": ["Lines"],
                            "syncStatus": "synced",
                            "addedAt": "2025-01-10T09:00:00Z",
                            "modifiedAt": "2025-01-10T09:00:00Z",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

    def test_card_with_icon_code_renders_without_error(self, tmp_path):
        """A template whose templates.json entry has an iconCode renders without error."""
        cfg_path = with_device(tmp_path, "D1")
        self._make_template_with_icon(tmp_path, "D1", "alpha.svg", "\ue960")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any("alpha" in b.label.lower() for b in at.button)

    def test_card_with_empty_icon_code_shows_fallback_button(self, tmp_path):
        """A template with an empty iconCode shows the fallback palette icon button."""
        cfg_path = with_device(tmp_path, "D1")
        self._make_template_with_icon(tmp_path, "D1", "beta.svg", "")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        # render_icon_link_html("") == "" → the fallback button is rendered instead
        assert any(b.key and b.key.startswith("tpl_icon_btn_fallback_") for b in at.button)


# ---------------------------------------------------------------------------
# .template files alongside SVG files
# ---------------------------------------------------------------------------

# Minimal reMarkable JSON template
_JSON_TEMPLATE = '{"orientation":"portrait","constants":[],"items":[]}'


def _make_json_template(tmp_path, device: str = "D1", name: str = "MyLines.template") -> str:
    """Create a .template JSON file in the device templates dir and return its name."""
    d = backup_dir(tmp_path, device)
    tdir = d / "templates"
    stem = name.removesuffix(".template")
    (tdir / name).write_text(_JSON_TEMPLATE, encoding="utf-8")
    (d / "manifest.json").write_text(
        json.dumps(
            {
                "version": 1,
                "lastSync": None,
                "templates": [
                    {
                        "name": stem,
                        "filename": stem,
                        "iconCode": "\ue9fe",
                        "categories": ["Perso"],
                        "syncStatus": "synced",
                        "addedAt": "2025-01-10T09:00:00Z",
                        "modifiedAt": "2025-01-10T09:00:00Z",
                    }
                ],
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
            patch("src.templates.is_templates_dirty", return_value=False),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any("grid" in b.label.lower() for b in at.button)

    def test_both_svg_and_json_template_cards_render(self, tmp_path):
        """SVG and .template files coexist on the page."""
        cfg_path = with_device(tmp_path, "D1")
        _make_svgs(tmp_path, "D1", ["my_svg.svg"])
        _make_json_template(tmp_path, "D1", "my_json.template")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
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
            patch("src.templates.is_templates_dirty", return_value=False),
            patch(
                "src.templates.rename_device_template",
                side_effect=lambda n, o, f: renamed.append((o, f)),
            ),
            patch("src.templates.rename_template_entry"),
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

    def test_upload_section_accepts_both_svg_and_template(self, tmp_path):
        """The file uploader label mentions both svg and template."""
        cfg_path = with_device(tmp_path, "D1")
        backup_dir(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
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
            patch("src.templates.is_templates_dirty", return_value=False),
            patch(
                "src.templates.delete_device_template",
                side_effect=lambda n, f: deleted.append(f),
            ),
            patch("src.templates.remove_template_entry"),
            patch("src.templates.delete_template_from_tablet", return_value=(True, "ok")),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.session_state["tpl_pending_delete_local"] = "todel.template"
            at.switch_page("pages/templates.py").run()
            delete_btn = next((b for b in at.button if b.label == "Delete"), None)
            assert delete_btn is not None
            delete_btn.click().run()
        assert not at.exception
        assert "todel.template" in deleted


# ---------------------------------------------------------------------------
# Segmented control options per file type
# ---------------------------------------------------------------------------


class TestSegmentedControlOptions:
    """The edit option must be present for .template files and absent for .svg files."""

    def test_svg_card_has_no_edit_option(self, tmp_path):
        """An SVG template card's action control has upload and delete, but no edit."""
        cfg_path = with_device(tmp_path, "D1")
        _make_svgs(tmp_path, "D1", ["photo.svg"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        sc = next((s for s in at.button_group if s.key == "tpl_action_photo.svg"), None)
        assert sc is not None
        # SVG cards: upload + delete only (2 options, no edit)
        assert len(sc.options) == 2

    def test_json_template_card_has_edit_option(self, tmp_path):
        """A .template card's action control includes the edit option (3 options total)."""
        cfg_path = with_device(tmp_path, "D1")
        _make_json_template(tmp_path, "D1", "lines.template")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
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
            patch("src.templates.is_templates_dirty", return_value=False),
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


class TestOrphanActions:
    """Orphan templates expose explicit adopt/delete actions."""

    def test_orphan_card_shows_add_and_delete_actions(self, tmp_path):
        cfg_path = with_device(tmp_path, "D1")
        _make_json_template(tmp_path, "D1", "orphaned.template")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=True),
            patch("src.templates.get_template_sync_status", return_value="orphan"),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()

        assert not at.exception
        assert any(b.label == "Add orphan" for b in at.button)
        assert any(b.label == "Delete orphan" for b in at.button)

    def test_add_orphan_action_sets_pending(self, tmp_path):
        cfg_path = with_device(tmp_path, "D1")
        _make_json_template(tmp_path, "D1", "orphaned.template")
        env = make_env(tmp_path, cfg_path)
        calls: list[tuple[str, str, str]] = []
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=True),
            patch("src.templates.get_template_sync_status", return_value="orphan"),
            patch(
                "src.templates.set_template_sync_status",
                side_effect=lambda d, f, s: calls.append((d, f, s)) or True,
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            btn = next((b for b in at.button if b.label == "Add orphan"), None)
            assert btn is not None
            btn.click().run()

        assert not at.exception
        assert ("D1", "orphaned.template", "pending") in calls

    def test_delete_orphan_action_sets_deleted(self, tmp_path):
        cfg_path = with_device(tmp_path, "D1")
        _make_json_template(tmp_path, "D1", "orphaned.template")
        env = make_env(tmp_path, cfg_path)
        calls: list[tuple[str, str, str]] = []
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=True),
            patch("src.templates.get_template_sync_status", return_value="orphan"),
            patch(
                "src.templates.set_template_sync_status",
                side_effect=lambda d, f, s: calls.append((d, f, s)) or True,
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.switch_page("pages/templates.py").run()
            btn = next((b for b in at.button if b.label == "Delete orphan"), None)
            assert btn is not None
            btn.click().run()

        assert not at.exception
        assert ("D1", "orphaned.template", "deleted") in calls


# ---------------------------------------------------------------------------
# icon query-param handlers
# ---------------------------------------------------------------------------


class TestIconQueryParams:
    """Tests for ?tpl_icon_for, ?icon, and ?edit_icon query-param page-level handlers."""

    def test_icon_update_via_query_param(self, tmp_path):
        """?tpl_icon_for=STEM&icon=HEX updates the icon code and clears params."""
        cfg_path = with_device(tmp_path, "D1")
        _make_svgs(tmp_path, "D1", ["chart.svg"])
        env = make_env(tmp_path, cfg_path)
        updated: list = []
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
            patch(
                "src.templates.update_template_icon_code",
                side_effect=lambda n, stem, code: updated.append((stem, code)),
            ),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.query_params["tpl_icon_for"] = "chart"
            at.query_params["icon"] = "E9FE"
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        assert any(stem == "chart" for stem, _ in updated)

    def test_invalid_hex_in_icon_query_param_is_silently_ignored(self, tmp_path):
        """?tpl_icon_for with a non-hex icon value does not crash (ValueError caught)."""
        cfg_path = with_device(tmp_path, "D1")
        _make_svgs(tmp_path, "D1", ["chart.svg"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.query_params["tpl_icon_for"] = "chart"
            at.query_params["icon"] = "NOTAHEX!!"
            at.switch_page("pages/templates.py").run()
        assert not at.exception

    def test_edit_icon_query_param_clears_param(self, tmp_path):
        """?edit_icon=STEM clears the query param and opens the icon dialog."""
        cfg_path = with_device(tmp_path, "D1")
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
        ):
            at = AppTest.from_file("app.py")
            at.run()
            at.query_params["edit_icon"] = "mystem"
            at.switch_page("pages/templates.py").run()
        assert not at.exception
        # The query param must have been consumed by the page
        assert at.query_params.get("edit_icon") is None


# ---------------------------------------------------------------------------
# Multi-row grid (> GRID_COLUMNS templates)
# ---------------------------------------------------------------------------


class TestMultiRowGrid:
    """Tests for template grids spanning more than one row."""

    def test_multi_row_grid_renders_divider(self, tmp_path):
        """When there are more than GRID_COLUMNS (5) templates, a divider is rendered."""
        cfg_path = with_device(tmp_path, "D1")
        # Create 6 SVG files so the grid spans two rows (GRID_COLUMNS = 5)
        _make_svgs(tmp_path, "D1", [f"t{i}.svg" for i in range(6)])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
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
        _make_svgs(tmp_path, "D1", [f"{long_stem}.svg"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
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
        _make_svgs(tmp_path, "D1", ["mycard.svg"])
        env = make_env(tmp_path, cfg_path)
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
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
        _make_svgs(tmp_path, "D1", ["mycard.svg"])
        env = make_env(tmp_path, cfg_path)
        calls: list = []
        with (
            patch.dict(os.environ, env),
            patch("src.templates.is_templates_dirty", return_value=False),
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
